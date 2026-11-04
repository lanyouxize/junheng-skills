#!/usr/bin/env node
/* eslint-disable */
/**
 * rank-records.cjs — 主题相关性排序（本地，**零站点请求**）
 *
 * 用法: node rank-records.cjs --dir <search 输出目录> --topic "毛球,化毛,hairball"
 *         [--near "毛发,毛皮,膳食纤维"] [--exclude "毛囊,球部,follicle"]
 *         [--top 10] [--format md|csv|json|both] [--out <前缀>] [--all] [--full]
 *
 * 读取: <dir>/raw/*.json（与 assemble-report.cjs **同一读法**，故复用其 readRawGroups）
 * 输出: <前缀>.md / <前缀>.csv / <前缀>.json（默认前缀 <dir>/ranked）
 *
 * 为什么需要它：站点检索引擎是**宽匹配** —— 术语型 AND 也会被稀释，
 *   自报命中 7 条里可能混进「毛囊球部」这类歧义命中。
 *   站点跑一次很贵（一条检索式 3~60s），**过滤却应当廉价且可反复调**
 *   ⇒ 过滤与抓取解耦：抓取落盘一次，本步骤纯本地重排，零站点请求。
 *
 * 与 --evidence 的分工：`--evidence` 判「研究设计值几分证据」（A–D），
 *   本脚本判「是不是我要的主题」（exact/near/off）—— 两者正交，可同时用于同一条记录。
 */
'use strict';
const fs = require('fs');
const path = require('path');
const { CliError, fail, needVal } = require('./lib/cli.cjs');
const REL = require('./lib/relevance.cjs');
const SG = require('./lib/suggest.cjs');   // 覆盖诊断：缺词候选（纯函数，零请求）
const IT = require('./lib/iterate.cjs');   // 多轮迭代闭环：上限探测（纯函数，零请求）
const QP = require('./lib/query-plan.cjs'); // 维度 → 建议检索式（只出方案，**不执行**）
const CSG = require('./lib/converge-state.cjs'); // 跨运行记忆（IO 只在本层，lib 侧纯函数）
const AW = require('./lib/atomic-write.cjs');    // 原子写：状态文件不得出现半截/空文件
const FL = require('./lib/file-lock.cjs');       // 互斥锁：只护「重读 → rename」的毫秒级临界区
const { readRawGroups } = require('./assemble-report.cjs');

const FORMATS = ['md', 'csv', 'json', 'both'];
const SUGGEST_SCOPES = ['exact', 'near', 'all'];
const ITERATE_PICKS = IT.PICKS;
/** `--converge-state` 裸参数的哨兵：落点由 `--dir` 推导（记忆跟着语料走，不必每次手带路径）。 */
const CONVERGE_DEFAULT = '@default';

function parseArgs(argv) {
  const a = { dir: null, topic: null, near: null, exclude: null, top: 10, format: 'both', out: null, all: false, full: false,
    suggest: true, suggestTop: SG.DEFAULT_TOP, suggestScope: SG.DEFAULT_SCOPE, minDf: SG.DEFAULT_MIN_DF,
    apply: null, iterate: null, iterateBatch: IT.DEFAULT_BATCH, iteratePick: 'all',
    species: 'auto', queryCap: QP.DEFAULT_CAP, convergeState: null };
  for (let i = 2; i < argv.length; i++) {
    const t = argv[i];
    switch (t) {
      case '--dir': a.dir = needVal(argv, i, t, './run'); i++; break;
      case '--out': a.out = needVal(argv, i, t, './run/ranked'); i++; break;
      case '--topic': a.topic = needVal(argv, i, t, '"毛球,化毛,hairball"'); i++; break;
      case '--near': a.near = needVal(argv, i, t, '"毛发,毛皮,膳食纤维"'); i++; break;
      case '--exclude': a.exclude = needVal(argv, i, t, '"毛囊,球部"'); i++; break;
      case '--top': {
        const v = needVal(argv, i, t, '10'); i++;
        const n = Number(v);
        if (!Number.isInteger(n) || n < 1) fail('[参数错误] --top 需为正整数，当前值 ' + JSON.stringify(v));
        a.top = n; break;
      }
      case '--format': {
        const v = needVal(argv, i, t, 'both'); i++;
        if (!FORMATS.includes(v)) fail('[参数错误] --format 只接受 ' + FORMATS.join('|') + '，当前值 ' + JSON.stringify(v));
        a.format = v; break;
      }
      case '--all': a.all = true; break;
      case '--full': a.full = true; break;
      // ---- 覆盖诊断（缺词候选）：默认开启，可用 --no-suggest 关闭
      case '--no-suggest': a.suggest = false; break;
      case '--suggest-top': {
        const v = needVal(argv, i, t, '20'); i++;
        const n = Number(v);
        if (!Number.isInteger(n) || n < 1) fail('[参数错误] --suggest-top 需为正整数，当前值 ' + JSON.stringify(v));
        a.suggestTop = n; break;
      }
      case '--suggest-scope': {
        const v = needVal(argv, i, t, 'exact'); i++;
        if (!SUGGEST_SCOPES.includes(v)) fail('[参数错误] --suggest-scope 只接受 ' + SUGGEST_SCOPES.join('|') + '，当前值 ' + JSON.stringify(v));
        a.suggestScope = v; break;
      }
      case '--min-df': {
        const v = needVal(argv, i, t, '2'); i++;
        const n = Number(v);
        if (!Number.isInteger(n) || n < 1) fail('[参数错误] --min-df 需为正整数，当前值 ' + JSON.stringify(v));
        a.minDf = n; break;
      }
      // ---- 补词闭环：把**人工勾选**的词并入主题词表并重排（唯一入口，不得自动生效）
      case '--apply': a.apply = needVal(argv, i, t, '"肾脏保健,乳酸杆菌"'); i++; break;
      // ---- 多轮迭代：**上限探测**（自动批量取词，产物不代表建议词表）
      case '--iterate': {
        const v = needVal(argv, i, t, '3'); i++;
        const n = Number(v);
        if (!Number.isInteger(n) || n < 1 || n > IT.MAX_ROUNDS_CAP) {
          fail('[参数错误] --iterate 需为 1–' + IT.MAX_ROUNDS_CAP + ' 的整数，当前值 ' + JSON.stringify(v));
        }
        a.iterate = n; break;
      }
      case '--iterate-batch': {
        const v = needVal(argv, i, t, String(IT.DEFAULT_BATCH)); i++;
        const n = Number(v);
        if (!Number.isInteger(n) || n < 1 || n > IT.BATCH_CAP) {
          fail('[参数错误] --iterate-batch 需为 1–' + IT.BATCH_CAP + ' 的整数，当前值 ' + JSON.stringify(v));
        }
        a.iterateBatch = n; break;
      }
      case '--iterate-pick': {
        const v = needVal(argv, i, t, 'all'); i++;
        if (!ITERATE_PICKS.includes(v)) {
          fail('[参数错误] --iterate-pick 只接受 ' + ITERATE_PICKS.join('|') + '，当前值 ' + JSON.stringify(v));
        }
        a.iteratePick = v; break;
      }
      case '--species': {
        const v = needVal(argv, i, t, 'auto'); i++;
        if (!QP.SPECIES_MODES.includes(v)) {
          fail('[参数错误] --species 只接受 ' + QP.SPECIES_MODES.join('|') + '，当前值 ' + JSON.stringify(v)
            + '\n  仅影响「建议检索式」里的物种块，**不改变排序结果**。');
        }
        a.species = v; break;
      }
      case '--query-cap': {
        const v = needVal(argv, i, t, String(QP.DEFAULT_CAP)); i++;
        const n = Number(v);
        if (!Number.isInteger(n) || n < 1 || n > QP.CAP_LIMIT) {
          fail('[参数错误] --query-cap 需为 1–' + QP.CAP_LIMIT + ' 的整数，当前值 ' + JSON.stringify(v));
        }
        a.queryCap = n; break;
      }
      case '--converge-state': {
        // 可选取值：裸参数 = 默认落点（`<dir>/converge-state.json`）。
        // ★ 紧跟 `--xxx` 时不得把它当路径 —— 否则 `--converge-state --iterate 3` 会静默丢轮数。
        const nx = argv[i + 1];
        if (nx && nx.charAt(0) !== '-') { a.convergeState = nx; i++; }
        else a.convergeState = CONVERGE_DEFAULT;
        break;
      }
      case '--help': case '-h': a.help = true; break;
      default:
        fail('[参数错误] 未知参数 ' + t + '\n  可用: --dir --topic --near --exclude --top --format --out --all --full'
          + '\n        --no-suggest --suggest-top --suggest-scope --min-df --apply --iterate --iterate-batch --iterate-pick'
          + '\n        --species --query-cap --converge-state'
          + '\n  提示: 输入目录用 --dir，输出前缀用 --out，勿记反');
    }
  }
  // ★ 跨运行记忆与 --iterate 的配对必须在**参数层**校验：静默忽略会让用户以为「状态已记下」而其实没有。
  if (a.convergeState && !a.iterate) {
    fail('[参数错误] --converge-state 需与 --iterate 同用\n'
      + '  跨运行记忆记的是「维度收敛结论」，而结论只由 --iterate 的逐轮诊断产生。\n'
      + '  示例: --iterate 3 --converge-state ./run/converge-state.json');
  }
  return a;
}

/**
 * `--converge-state` 的实际落点。
 * 裸参数 ⇒ `<dir>/converge-state.json`：状态跟着**语料目录**走（同一批 raw/*.json 的记忆放一起），
 * 换目录就是另一份记忆 —— 比固定放某个全局位置更不容易串主题。
 */
/**
 * 状态文件的「内容指纹」，用于判断期间有没有别的进程写过。
 * `null`（文件不存在）与 `{}` 必须可区分 —— 否则「刚被创建」会被当成「没变」。
 */
function stateFingerprint(data) {
  return data == null ? '\u0000NONE' : JSON.stringify(data);
}

// CAS 重试次数：每次失败都要重读 + 重建（毫秒级），给 4 次足够覆盖偶发竞争；
// 超过就强制写最后一次结果并把原因写进报告 —— **静默失败比丢更新更糟**。
const STATE_WRITE_TRIES = 4;

/**
 * 把「不可用」的状态文件**原样**留一份副本（批 4 / M3）。
 *
 * ★ 顺序不可颠倒：`buildState` 对 CORRUPT 拿到的是 `prevFile.data = null`，其余主题槽全部不进 `keep`
 *   （实测 20 槽 → 1 槽、5,062 B → 497 B）。写下去之后原字节没有任何途径找回，
 *   所以备份是**唯一**的回退路径，必须发生在第一次写之前。
 * ★ 写**原始字节**（readFileSync 不带 encoding）：要救的正是「解析不了」的那份文件，
 *   解析后重新序列化等于什么都没救。
 * ★ `'wx'` 独占创建：绝不覆盖已存在的备份；同毫秒重复触发时按序号退让。
 * ★ 任何失败都**抛出** ⇒ 调用方 fail-closed 不写状态（救不了就别毁）。
 *
 * @param {string} convergePath 状态文件路径
 * @param {string} status `corrupt` | `legacy`
 * @param {Object} [opts] `{now}`（时间注入，仅供测试断言文件名）
 * @returns {{path:string, bytes:number, status:string}}
 */
function backupUnusableState(convergePath, status, opts) {
  const o = opts || {};
  const base = CSG.backupNameFor(convergePath, status, o.now);
  if (!base) throw new Error('backupUnusableState 只接受 corrupt / rejected，收到 ' + String(status));
  const raw = fs.readFileSync(convergePath);          // 二进制读，不让编码转换改字节
  for (let i = 1; i <= 20; i++) {
    const target = i === 1 ? base : base + '-' + i;
    let fd;
    try {
      fd = fs.openSync(target, 'wx');                 // 'wx' = 已存在即失败，永不覆盖旧备份
    } catch (e) {
      if (e.code === 'EEXIST') continue;              // 撞名（同毫秒重复触发）⇒ 退让到下一个序号
      throw e;                                        // 磁盘满 / 只读 / 无权限 ⇒ 交给调用方 fail-closed
    }
    try {
      let off = 0;
      while (off < raw.length) off += fs.writeSync(fd, raw, off, raw.length - off);
      fs.fsyncSync(fd);                               // 备份也要落盘：断电后「有备份」不能是假象
    } finally {
      fs.closeSync(fd);
    }
    return { path: target, bytes: raw.length, status };
  }
  throw new Error('备份文件重名 20 次仍未成功：' + base);
}

/**
 * 带「互斥锁 + 写前重读 + CAS 重试」地写状态文件（批 2 抽函数、批 3 加锁；抽成导出函数是为了能确定性测试）。
 *
 * ★ 三层防护各管一件事，不要混为一谈：
 *   ① 互斥锁（批 3）：把「读 → 重建 → 写」变成**串行**，消除「两进程同时确认、同时写、后写覆盖先写」。
 *   ② 原子写（批 1）：读者永远看到完整旧版或完整新版，消除「半截/空文件 ⇒ 判 CORRUPT ⇒ 清空全部槽」。
 *   ③ CAS 二次确认（批 2）：锁被 TTL 抢占或降级时的兜底，发现期间被改就丢掉本轮重来。
 *   ⇒ 只有 ① 能根治 M1；②③ 单独用都只能降低概率（实测 0% → 80%）。
 *
 * 为什么不能直接写 `stateNext`：`buildState` 里「保留其他主题的槽」取决于 `prevFile`，
 * 而调用方手里那份是 **run 开始那一刻**的快照。一次 run 中间隔着整批站点请求（分钟级），
 * 期间别的进程新建的槽会被覆盖 —— 实测并发 3 轮 3/3 只存活 1 个槽。
 *
 * 本函数把「读 → 重建 → 二次确认 → 原子写」压到毫秒级，并在确认发现别人写过时**丢掉本轮结果重来**。
 *
 * ★ 边界（不得读成「零丢失」）：
 *   ① 二次确认与 rename 之间仍有微秒级窗口；
 *   ② **同主题**的并发更新仍会互相覆盖（本主题槽永远被本轮 slot 取代）—— 那要真正的锁。
 *   无锁的「读-改-写」在文件系统上无法保证不丢更新，这是理论边界而非实现缺陷。
 *
 * @param {string} convergePath 状态文件路径
 * @param {Object} stateInput `iterateRounds` 回传的 buildState 入参（不含 prevFile）
 * @param {Object} [hooks] `{beforeWrite({attempt, before, built})}` 仅供测试注入「期间被改写」的场景
 * @returns {{built:Object, attempts:number, forced:boolean, backup?:Object}}
 */
function writeStateWithMerge(convergePath, stateInput, hooks) {
  const o = hooks || {};
  const got = FL.acquireLock(convergePath, { waitMs: o.lockWaitMs, staleMs: o.staleMs });
  if (!got.ok) {
    // ★ fail-closed：拿不到锁就**不写**，而不是无锁覆盖。
    //   代价是这一轮的「记忆」丢失（下一轮会重建），收益是绝不会覆盖掉别人刚写的槽 ——
    //   丢一次记忆可以重算，覆盖别人的槽是不可逆的数据丢失。
    return { built: null, attempts: 0, forced: false, skipped: true, reason: got.reason,
             lockWaitMs: got.waitedMs || 0, holder: got.holder || null };
  }
  try {
    // ★ 批 4 / M3：覆盖之前先给「不可用」的旧文件留一份原样副本。
    //   必须在①锁内（否则两人可能各备一份）、②第一次写之前（写下去就晚了）。
    //   CORRUPT/REJECTED 的判定只看文件形态、不看 fp（`readPrior` 在这两条分支前就返回）⇒ 传 {} 足够。
    let backup = null;
    const pre = readStateFile(convergePath);
    const preStatus = CSG.readPrior(pre, {}).status;
    if (preStatus === CSG.PRIOR.CORRUPT || preStatus === CSG.PRIOR.REJECTED) {
      try {
        backup = backupUnusableState(convergePath, preStatus, { now: o.now });
      } catch (e) {
        // ★ fail-closed：救不了就别毁。宁可这一轮不记记忆，也不覆盖掉唯一能救的那份文件。
        return { built: null, attempts: 0, forced: false, skipped: true, backupFailed: true,
                 reason: 'backup_failed: ' + e.message,
                 lockWaitMs: got.waitedMs || 0, holder: got.holder || null };
      }
    }
    for (let attempt = 0; attempt < STATE_WRITE_TRIES; attempt++) {
      const before = readStateFile(convergePath);
      const built = CSG.buildState(Object.assign({}, stateInput, { prevFile: before.data }));
      if (typeof o.beforeWrite === 'function') o.beforeWrite({ attempt, before, built });
      const check = readStateFile(convergePath);
      if (stateFingerprint(before.data) !== stateFingerprint(check.data)) continue;  // 期间被改过 ⇒ 重来
      AW.writeAtomicSync(convergePath, CSG.serialise(built.state), 'utf8');
      return { built, attempts: attempt + 1, forced: false, skipped: false, backup,
               lockSteals: got.handle.steals };
    }
    // 持锁期间仍被改（只可能是 TTL 抢占 / 有人绕过锁直接写）：用最新内容重建后强制写，
    // 并把 forced 交回调用方（不得静默当作成功）
    const before = readStateFile(convergePath);
    const built = CSG.buildState(Object.assign({}, stateInput, { prevFile: before.data }));
    AW.writeAtomicSync(convergePath, CSG.serialise(built.state), 'utf8');
    return { built, attempts: STATE_WRITE_TRIES, forced: true, skipped: false, backup,
             lockSteals: got.handle.steals };
  } finally {
    FL.releaseLock(got.handle);   // fn 抛错也放锁，不留残留
  }
}

/**
 * 读状态文件，返回 `readPrior` 需要的形态 `{exists, data, error}`。
 * 损坏**不崩**：交给 `readPrior` 判 CORRUPT（那是它的事），这里只负责「读到什么」。
 * ★ 批 2 抽成函数的原因：需要在**两处**调用 —— run 开始一次（供合并与报告）、写盘前再一次（供重建）。
 *   两处逻辑必须完全一致，复制粘贴迟早会漂。
 */
function readStateFile(p) {
  let exists = false;
  let data = null;
  let error = null;
  if (p && fs.existsSync(p)) {
    exists = true;
    try {
      data = JSON.parse(fs.readFileSync(p, 'utf8'));
    } catch (e) {
      error = e.message;
    }
  }
  return { exists, data, error };
}

function resolveConvergePath(a) {
  if (!a || !a.convergeState) return null;
  if (a.convergeState !== CONVERGE_DEFAULT) return a.convergeState;
  if (!a.dir) {
    fail('[参数错误] 缺少 --dir，无法推导 --converge-state 的默认路径（或显式给出路径）');
  }
  return path.join(a.dir, 'converge-state.json');
}

const HELP = [
  'rank-records.cjs — 主题相关性排序 + 覆盖诊断（本地，零站点请求）',
  '',
  'node rank-records.cjs --dir <search 输出目录> --topic "毛球,化毛,hairball" [选项]',
  '',
  '  --dir <目录>        search-papers 的输出目录（须含 raw/ 子目录）',
  '  --topic <词表>      必填。主题词，逗号分隔（中英文兼可）',
  '  --near <词表>       相邻词，只作弱信号（如 毛发,毛皮,膳食纤维）',
  '  --exclude <词表>    排除词，一票否决并标 excluded（如 毛囊,球部）',
  '  --top <N>           md/csv 输出前 N 条（默认 10；排序计算始终覆盖全量）',
  '  --format <f>        md | csv | json | both（默认 both）',
  '  --out <前缀>        输出前缀（默认 <dir>/ranked）',
  '  --all               md/csv 输出全量而非前 N 条',
  '  --full              json 内附完整原始记录',
  '',
  '覆盖诊断（缺词候选；默认开启）：',
  '  --no-suggest        关闭覆盖诊断（产物与旧版逐字节可比）',
  '  --suggest-top <N>   最多列 N 个候选（默认 20）',
  '  --suggest-scope <s> 最低档位（单调包含）：near（默认，主题档+相邻档）| exact | all',
  '  --min-df <N>        候选至少出现在 N 条记录里（默认 2）',
  '',
  '补词闭环（显式勾选后重排；**不自动改词表**）：',
  '  --apply <词表>      把勾选词并入 --topic 后重排，主视图 = 补词后，并附「补词效果对比」',
  '                      勾选词已全部在词表中 ⇒ 显式报错（避免静默空操作）',
  '',
  '多轮迭代（**上限探测**；自动批量取词，产物不代表建议词表）：',
  '  --iterate <N>       迭代轮数 1–8（默认关闭）。输出每轮增益曲线 + 停止原因 + 饱和轮次',
  '  --iterate-batch <K> 每轮补入上限 1–50（默认 5）—— 模拟「一次挑 K 个」',
  '  --iterate-pick <p>  all（默认，全取候选 = 上限探测）| extends（只补「词表词+修饰」，半重叠进 deferred）',
  '  与 --apply 互斥：--iterate 是探测，--apply 才是采纳。',
  '',
  '建议检索式（由「新维度」簇推出；**只出方案、不执行**）：',
  '  --species <s>       auto（默认，按题名探测）| both | cat | dog | none —— **仅影响建议式，不改排序**',
  '  --query-cap <N>     每条式的术语上限 1–8（默认 4），超出者进 dropped 并告警',
  '',
  '跨运行记忆（同一维度只正经报一次；需与 --iterate 同用）：',
  '  --converge-state [f] 状态文件路径。**省略路径 ⇒ <dir>/converge-state.json**（跟着语料走，不必每次手带）。',
  '                      文件是**多主题**的：每个 --topic 一个槽，换词表只新增槽、不覆盖别的主题。',
  '                      本主题无槽 ⇒ 视为首次（其他槽原样保留）；文件 v1 单主题 ⇒ 自动迁移。',
  '                      槽数上限 20，超出淘汰最旧槽并在报告里点名（丢记忆必须可见）。',
  '                      同一维度 `persistent` + `stalled` + 已报过 ≥2 次 ⇒ 不再重复出检索式。',
  '',
  '分档：主题命中 / 相邻主题 / 跑题·待人工（排除词命中一律降为跑题但**不丢记录**）',
  '覆盖诊断：扫主题档题名，报出「高频但不在词表」的领域词 —— 补词后零成本重排。',
].join('\n');

// ------------------------------------------------------------------ 渲染

function titleOf(rec) {
  return String((rec && (rec.titleZh || rec.titleEn)) || '').replace(/\s+/g, ' ').trim();
}

function clip(s, n) {
  const t = String(s == null ? '' : s);
  return t.length > n ? t.slice(0, n) + '…' : t;
}

function mdCell(s) {
  return String(s == null ? '' : s).replace(/\|/g, '\\|').replace(/\r?\n/g, ' ');
}

function termsOf(list) {
  return list.length ? list.map(h => h.term + (h.field === 'title' ? '' : '(摘)')).join('、') : '—';
}

/**
 * 覆盖诊断小节：词表外的高频领域词。
 * 定位是「给人挑词」——不自动改词表、不自动判定词边界；补词后本步骤**零站点请求**即可重排。
 */
function renderSuggestSection(sg) {
  const L = [];
  // scope 是**最低档位**（单调包含），故 `near` 读作「主题档 + 相邻档」而非「相邻档」
  const SCOPE_LABEL = { exact: '主题档', near: '主题档 + 相邻档', all: '全部档位' };
  L.push('## 建议补词（覆盖诊断 · 词表外的高频领域词）');
  L.push('');
  L.push('> 扫 **' + sg.corpus + '** 条「' + (SCOPE_LABEL[sg.scope] || sg.scope)
    + '」题名（零站点请求，纯本地统计）。');
  L.push('> 勾选后补进 `--topic` 再跑一次本步骤即可**零成本重排** —— 站点不必重跑。');
  L.push('');
  if (!sg.candidates.length) {
    L.push('（无候选：该档题名里没有出现「重复出现且不在词表」的领域词）');
    L.push('');
    return L;
  }
  L.push('| # | 候选词 | 出现 | 字数 | 与词表关系 | 备注 |');
  L.push('|---|---|---|---|---|---|');
  sg.candidates.forEach((c, i) => {
    const rel = c.extendsTopic ? '词表词+修饰' : (c.overlapsTopic ? '半重叠·待人工' : '词表外');
    const notes = [];
    if (c.inNear) notes.push('已列相邻词（可考虑升为主题词）');
    if (c.inExclude) notes.push('与排除词重叠');
    if (c.kind === 'en') notes.push('英文');
    L.push('| ' + (i + 1) + ' | `' + mdCell(c.term) + '` | ' + c.df + ' | ' + c.len + ' | ' + rel
      + ' | ' + mdCell(notes.join('；') || '—') + ' |');
  });
  L.push('');
  L.push('**可直接粘贴补词**（追加到 `--topic`）：');
  L.push('');
  L.push('```');
  L.push(sg.suggestedTopicSuffix);
  L.push('```');
  L.push('');
  const d = sg.dropped;
  L.push('> 统计留痕：原始候选 ' + d.total + ' · 过短 ' + d.tooShort + ' · 通用词 ' + d.stopword
    + ' · 已在词表 ' + d.inTopic + ' · 低于 min-df ' + d.lowDf + ' · 被长串吸收 ' + d.subsumed + '。');
  L.push('> 「半重叠·待人工」= 与某个主题词有 ≥2 字公共子串但互不包含 —— 既可能是**真缺词**');
  L.push('> （如 `菌群失调`），也可能是 **n-gram 分词错位**（如 `脏保健复`）；纯 n-gram 分不出二者，');
  L.push('> 故**只降权不丢弃**，词边界判断交给人。');
  L.push('');
  if (sg.candidates.length) {
    L.push('候选出处（首条）：');
    L.push('');
    sg.candidates.forEach((c, i) => {
      L.push((i + 1) + '. `' + c.term + '` ← ' + (c.samples[0] || '—'));
    });
    L.push('');
  }
  return L;
}

/**
 * 补词效果对比小节（`--apply` 时内嵌进主视图）。
 * ★ 方向性纪律：升级 / 降级**必须分列两个 H4 小节**，绝不混列 —— 与「相邻词不得标成主题」
 *   同源（实测踩过：口径写反会让正文与表格自相矛盾，且人眼极易读漏）。
 */
function renderApplyDiff(d, opts) {
  const o = opts || {};
  const L = [];
  const signed = n => (n > 0 ? '+' : '') + n;
  const termsList = list => (list && list.length ? list.map(t => '`' + t + '`').join('、') : '—');

  L.push('## 补词效果对比（补词前 → 补词后，零站点请求）');
  L.push('');
  L.push('- 补入词（人工勾选）: ' + termsList(d.addedTerms));
  L.push('- 主题命中: ' + d.before.stat.exact + ' → **' + d.after.stat.exact + '**（' + signed(d.delta.exact) + '）');
  L.push('- 主题命中率: ' + d.before.exactRate + '% → **' + d.after.exactRate + '%**（'
    + signed(d.delta.exactRate) + ' 个百分点）');
  L.push('- 相邻 / 跑题: ' + d.before.stat.near + ' / ' + d.before.stat.off + ' → '
    + d.after.stat.near + ' / ' + d.after.stat.off);
  L.push('- 条目配对: ' + d.pairs + ' 条（未配对 · 前 ' + d.unmatched.onlyBefore
    + ' / 后 ' + d.unmatched.onlyAfter + '）');
  L.push('');
  if (d.unmatched.onlyBefore || d.unmatched.onlyAfter) {
    L.push('> ⚠ 存在未配对条目 ⇒ 两次排序**不是同一批数据**，本对比结论不可直接采信。');
    L.push('');
  }

  L.push('#### 升级（' + d.upgraded.length + ' 条）');
  L.push('');
  if (!d.upgraded.length) {
    L.push('（0 条 —— 补入词未使任何条目升档：该词在**这批结果**里没有落点。）');
    L.push('');
  } else {
    L.push('| # | 变化 | 排名 | 分 | 年 | 新增命中词 | 标题 |');
    L.push('|---|---|---|---|---|---|---|');
    d.upgraded.forEach((u, i) => {
      L.push('| ' + (i + 1) + ' | ' + (REL.LEVEL_LABEL[u.levelFrom] || u.levelFrom) + ' → '
        + (REL.LEVEL_LABEL[u.levelTo] || u.levelTo) + ' | ' + u.rankFrom + ' → ' + u.rankTo
        + ' | ' + u.scoreFrom + ' → ' + u.scoreTo + ' | ' + (u.year || '—')
        + ' | ' + mdCell(termsList(u.newHits)) + ' | ' + mdCell(clip(u.title, 110)) + ' |');
    });
    L.push('');
  }

  L.push('#### 降级（' + d.downgraded.length + ' 条）');
  L.push('');
  if (!d.downgraded.length) {
    L.push('（0 条 ✓ 补词只会增加命中 ⇒ 分数单调不减；降级即缺陷。）');
    L.push('');
  } else {
    L.push('> ⚠ 补词产生降级 = **缺陷信号**，须人工核查（若丢失命中词含补入词，说明词表语义冲突）：');
    L.push('');
    L.push('| # | 变化 | 排名 | 分 | 年 | 丢失命中词 | 标题 |');
    L.push('|---|---|---|---|---|---|---|');
    d.downgraded.forEach((u, i) => {
      L.push('| ' + (i + 1) + ' | ' + (REL.LEVEL_LABEL[u.levelFrom] || u.levelFrom) + ' → '
        + (REL.LEVEL_LABEL[u.levelTo] || u.levelTo) + ' | ' + u.rankFrom + ' → ' + u.rankTo
        + ' | ' + u.scoreFrom + ' → ' + u.scoreTo + ' | ' + (u.year || '—')
        + ' | ' + mdCell(termsList(u.lostHits)) + ' | ' + mdCell(clip(u.title, 110)) + ' |');
    });
    L.push('');
  }

  L.push('**词表 v2（完整 `--topic` 串，可直接替换原值）**：');
  L.push('');
  L.push('```');
  L.push(o.topicTextV2 || d.addedTerms.join(','));
  L.push('```');
  L.push('');
  L.push('> 本次已用词表 v2 重排，**站点无需重跑**（消息头「站点请求」仍为 0）。');
  L.push('');
  // 对外契约与 renderMarkdown 一致：返回**字符串**（便于直测与独立落盘）
  return L.join('\n') + '\n';
}

/** 收敛状态/判定的中文标签（渲染层唯一一份；lib 侧只给机器码）。 */
const CONV_STATUS = {
  resolved: '已收敛', stalled: '卡住', shrinking: '缩小中',
  grew: '上升', emerged: '新出现', capped: '无法核实',
};
const CONV_STATE = {
  converged: '已收敛', converging: '收敛中', active: '未收敛',
  inconclusive: '无法判定', insufficient: '观测不足',
};

/**
 * 维度收敛追踪小节（`--iterate` 报告内嵌）。
 * ★ 它回答的是「**这一轮报出来的维度，还会不会永远报下去**」：
 *   同一个簇跨轮 support 未降 ⇒ `stalled`（补词治不了）；消失 ⇒ `resolved`（收敛）。
 *   没有这一节时，每份报告里的维度都像「新发现」，人无法判断该不该再动词表。
 */
function renderConvergence(cv) {
  const L = [];
  const c = cv.counts || {};
  L.push('### 维度收敛追踪（判据：**簇消失** 或 **support 降到阈值以下**）');
  L.push('');
  L.push('> 跨轮按**簇键**对比 support —— 这是「同一维度会不会被反复当新发现报出来」的答案。');
  L.push('> `stalled` = 末轮仍在且 support 未降 ⇒ **补词治不了**（属检索式/站点侧）；'
    + '`resolved` = 已消失 ⇒ 该维度**收敛**。');
  L.push('');
  L.push('- 判据 `' + cv.criterion + '` · 观测 ' + cv.observations + ' 轮'
    + (cv.rounds.length ? '（第 ' + cv.rounds[0] + '–' + cv.rounds[cv.rounds.length - 1] + ' 轮）' : '')
    + ' · 追踪键 ' + cv.clusters.length + ' 个');
  L.push('- 结论：**' + (CONV_STATE[cv.state] || cv.state) + '**（`' + cv.state + '`）—— ' + cv.note);
  L.push('- 分布：存活 ' + cv.live + ' 簇（卡住 ' + (c.stalled || 0) + ' · 缩小 ' + (c.shrinking || 0)
    + ' · 上升 ' + (c.grew || 0) + ' · 新出现 ' + (c.emerged || 0) + '）· 已收敛 ' + (c.resolved || 0)
    + ' · 无法核实 ' + (c.capped || 0));
  if (cv.residualSeries && cv.residualSeries.length) {
    L.push('- 残差规模（条）：' + cv.residualSeries.map(x => (x.total == null ? '—' : x.total)).join(' → ')
      + '（' + (cv.residualMonotonic ? '单调不增 ✓' : '**出现上升 ✗**') + '）');
  }
  L.push('');
  if (!cv.residualMonotonic) {
    L.push('> ⚠ 残差规模上升 ⇒ 违反「补词只增命中」不变量，须人工核查（不可当正常波动）。');
    L.push('');
  }
  if (cv.clusters && cv.clusters.length) {
    L.push('| 维度类型 | 簇标签 | support 序列 | 观测轮 | 状态 | 判定 |');
    L.push('|---|---|---|---|---|---|');
    cv.clusters.forEach(x => {
      L.push('| ' + (x.kind === 'new-dimension' ? '**新维度**' : '同轴延伸') + ' | ' + mdCell('`' + x.label + '`')
        + ' | ' + (x.supportSeries || []).join(' → ') + ' | ' + x.persistRounds
        + ' | ' + (CONV_STATUS[x.status] || x.status) + '（`' + x.status + '`）'
        + ' | ' + mdCell(x.note || '—') + ' |');
    });
    L.push('');
  }
  if (cv.cappedCount) {
    L.push('> ⚠ 有 ' + cv.cappedCount + ' 个簇在末轮「消失」，但末轮簇数超出上报上限 '
      + '⇒ 分不清是真收敛还是被挤出（判为 `capped`，**不**计入收敛）。核读残差清单后再说结论。');
    L.push('');
  }
  if (c.stalled) {
    L.push('> `stalled` 的维度**不会**因继续补词而消失 ⇒ 别再往词表里加同义写法；'
      + '下一步见下方「建议检索式」（已标注维度状态）。');
    L.push('');
  }
  return L.join('\n') + '\n';
}

/**
 * 跨运行记忆小节（`--iterate` + `--converge-state` 时内嵌）。
 * ★ 它回答的是「**这个维度是不是又来了**」：
 *   `persistent` = 上次报过、这次还一样 ⇒ 不再重复出式子；`recurred` = 上次判过收敛又回来 ⇒ 警示。
 *   没有这一节时，每份报告都是「首次发现」的口吻，人读到第三遍就不读了。
 */
const TREND_LABEL = {
  new: '首次', persistent: '沿续', resolved: '刚收敛', cleared: '消失', recurred: '**回归**',
};
const PRIOR_LABEL = {
  none: '首次运行', ok: '已合并', rejected: '拒绝合并', corrupt: '无法解析',
};

function renderCrossRun(cr) {
  const L = [];
  const s = cr.summary || {};
  const ok = cr.status === 'ok';
  L.push('### 跨运行记忆（同一维度只正经报一次）');
  L.push('');
  L.push('> 状态文件按**主题指纹**分槽：每个 `--topic` 一个槽 —— 换词表只新增槽、不覆盖别的主题；'
    + '本主题无槽 ⇒ 按首次处理（**绝不**复用别的主题的结论）。');
  L.push('');
  L.push('- 上次状态：**' + (PRIOR_LABEL[cr.status] || cr.status) + '**（`' + cr.status + '`）'
    + ' · 本次为第 **' + cr.runs + '** 次运行'
    + (cr.savedAt ? ' · 上次保存 ' + cr.savedAt : '')
    + (cr.slotCount == null ? '' : ' · 文件内主题槽 **' + cr.slotCount + '** 个'));
  if (cr.format === 'v1') {
    L.push('- ⚠ 状态文件是 **v1 单主题格式** ⇒ 本次已自动迁移为 v2（本主题槽完整保留；'
      + '以后换词表跑别的主题不会再互相覆盖）。');
  }
  if (cr.evicted && cr.evicted.length) {
    L.push('> ⚠ 主题槽数超出上限，已淘汰最旧的 ' + cr.evicted.length + ' 个记忆：'
      + cr.evicted.map(e => '`' + (e.topic || e.hash) + '`').join('、')
      + ' —— 这是**丢记忆**（不是清理），若还需要请换更大的状态文件或分目录。');
  }
  if (cr.reason) L.push('- 说明：' + cr.reason);
  L.push('- 本次分布：首次 ' + (s.new || 0) + ' · 沿续 ' + (s.persistent || 0)
    + ' · 刚收敛 ' + (s.resolved || 0) + ' · 消失 ' + (s.cleared || 0)
    + ' · **回归 ' + (s.recurred || 0) + '** · 已抑制 ' + (s.suppressed || 0));
  if (!ok) {
    L.push('- 因此本次所有维度**按首次**处理（不复用任何历史结论）。');
  }
  if (cr.corpusChanged) {
    L.push('> ⚠ 语料规模已变 ⇒ support 变动可能来自新文献而不是补词效果，判读时须分开。');
  }
  L.push('');
  if (!cr.clusters || !cr.clusters.length) {
    L.push('（无可追踪维度）');
    L.push('');
    return L.join('\n') + '\n';
  }
  L.push('| 跨运行 | 维度 | 本次状态 | support（上次→本次） | 报过 | 处置 |');
  L.push('|---|---|---|---|---|---|');
  cr.clusters.forEach(x => {
    const sup = x.support == null
      ? (x.priorSupport == null ? '—' : x.priorSupport + ' → 未出现')
      : (x.priorSupport == null ? '— → ' + x.support
        : x.priorSupport + ' → ' + x.support
          + (x.supportDelta ? '（' + (x.supportDelta > 0 ? '+' : '') + x.supportDelta + '）' : '（未变）'));
    let act;
    if (x.suppress) act = '**不再出式子**（结论未变，步子见上次报告）';
    else if (x.uncertain) act = '**无法核实**（末轮簇数超上限，「真消失」与「被挤出」不可区分）';
    else if (x.trend === 'recurred') act = '**重报**（上次的「已收敛」不可信，须核查为何回归）';
    else if (x.trend === 'cleared' || x.trend === 'resolved') act = '无需处理';
    else if (x.trend === 'persistent') act = '结论未变（首次给出式子）';
    else act = '首次给出式子';
    L.push('| ' + (TREND_LABEL[x.trend] || x.trend) + '（`' + x.trend + '`）'
      + ' | ' + mdCell('`' + x.label + '`')
      + ' | ' + (x.status ? (CONV_STATUS[x.status] || x.status) + '（`' + x.status + '`）' : '本次未出现')
      + ' | ' + mdCell(sup) + ' | ' + x.reportCount + ' | ' + mdCell(act) + ' |');
  });
  L.push('');
  if (s.recurred) {
    L.push('> ⚠ 有 ' + s.recurred + ' 个维度**上次判过收敛、本次又出现** ⇒ 上次的收敛结论不可信'
      + '（可能是词表/语料/站点索引变了），别直接沿用上次的判读。');
    L.push('');
  }
  const unc = cr.clusters.filter(x => x.uncertain).length;
  if (unc) {
    L.push('> ⚠ 有 ' + unc + ' 个维度的「本次消失」无法核实（末轮簇数超上报上限）'
      + '⇒ 不得当收敛用；提高簇上限或直接核读残差清单。');
    L.push('');
  }
  return L.join('\n') + '\n';
}

/**
 * 残差维度诊断小节（`--iterate` 报告内嵌）。
 * ★ 三重免责（标题 / 正文首句 / 提案标题各一处）：人眼只读到其中一处时仍不会误读为「已采纳」。
 */
function renderDiagnosis(dg) {
  const L = [];
  const V = {
    'no-residual': '无需新增维度',
    'no-shared-terms': '归纳不出共同维度',
    'axis-only': '同轴，补词即可',
    'new-dimension': '疑似缺主题维度',
  };
  const KIND = { 'new-dimension': '**新维度**', 'axis-extend': '同轴延伸' };
  const CONF = { strong: '强（≥3 条）', weak: '弱（2 条）' };
  const REASON = { 'no-shared-term': '无共享词', 'spun-off': '簇被剪（支持数不足）',
    'no-cohesion': '簇被剪（只有 1 个共享词，不足以构成同一主题）' };
  const termList = arr => (arr && arr.length ? arr.map(x => '`' + x.term + '`').join('、') : '—');
  // 跨运行记忆是否参与本次诊断：由 `iterate.cjs` 写在 diagnosis 上（**单一来源**，此处只读）。
  // ★ 不加列 = 旧报告形状完全不变 ⇒ 未传 --converge-state 时零回归。
  const crossOn = dg.crossActive === true;
  const supCl = dg.clusters.filter(c => c && c.suppress);

  L.push('### 残差维度诊断（**只提示，不自动建**）');
  L.push('');
  L.push('> 把上面「补词治不了」的残差按**共现指纹**聚成维度候选。本小节**仅提示**：'
    + '提案不会并入词表，也不影响本报告的排序结果。');
  L.push('');
  L.push('- 残差：' + dg.residual.total + ' 条（相近档 ' + dg.residual.byLevel.near
    + ' / 其他 ' + dg.residual.byLevel.off + '）· 共享指纹 ' + dg.fingerprints + ' 个'
    + ' · 最小支持数 ' + dg.minSupport + ' 条');
  if (dg.dropped.excludedRecords) {
    L.push('- 已跳过：' + dg.dropped.excludedRecords + ' 条被排除词否决的记录（不参与新维度提案）');
  }
  L.push('- 结论：**' + (V[dg.verdict] || dg.verdict) + '**（`' + dg.verdict + '`）—— ' + dg.verdictNote);
  if (crossOn) {
    L.push('- 跨运行：' + (supCl.length
      ? '已抑制 **' + supCl.length + '** 个维度（' + supCl.map(c => '`' + c.label + '`').join('、')
        + '）—— 上次报告已给过式子，本次**不重复出**；结论未变，不是新发现'
      : '本次无维度被抑制（各维度或首次出现、或结论有变化）'));
  }
  L.push('');

  if (dg.clusters.length) {
    L.push(crossOn
      ? '| 维度类型 | 簇标签 | 支持 | 置信 | 跨运行 | 簇内术语 | 代表题名 |'
      : '| 维度类型 | 簇标签 | 支持 | 置信 | 簇内术语 | 代表题名 |');
    L.push(crossOn ? '|---|---|---|---|---|---|---|' : '|---|---|---|---|---|---|');
    dg.clusters.forEach(c => {
      const sample = c.titles.length ? clip(c.titles[0].title, 46) : '—';
      // 逐簇判定，不做整表统一标记：同一张表里「首次」与「已报过」必须能共存
      const cross = !crossOn ? null
        : (c.suppress ? '**已报过 ' + c.reportCount + ' 次 · 抑制**'
          : (c.reportCount ? '已报过 ' + c.reportCount + ' 次' : '首次'));
      L.push('| ' + (KIND[c.kind] || c.kind) + ' | ' + mdCell('`' + c.label + '`') + ' | ' + c.support
        + ' | ' + (CONF[c.confidence] || c.confidence)
        + (crossOn ? ' | ' + mdCell(cross) : '')
        + ' | ' + mdCell(termList(c.terms))
        + ' | ' + mdCell(sample) + ' |');
    });
    L.push('');
    if (crossOn) {
      L.push('> 「抑制」= 该维度上次报告已出现且结论未变 ⇒ 本次不再重复给**建议检索式**；');
      L.push('> 它**仍是本轮残差**（记录与命中上下文都在上面），只是不再当新发现报一次。'
        + '提案段列出的候选词**未按抑制剔除**（本档只做标注，删词须人工判断）。');
      L.push('');
    }
  }

  if (dg.proposal.keywords.length) {
    L.push('**待人工确认的新维度候选（不自动建）**：'
      + dg.proposal.keywords.map(k => '`' + k + '`').join('、'));
    L.push('');
    L.push('> 采纳方式：先核对词边界（簇标签由 n-gram 推断，可能切在词中），确认后再加进 `--keywords` 重跑检索，'
      + '或用 `--apply` 显式补入 —— 本报告不产生任何「已采纳」结论。');
    L.push('');
  } else if (dg.verdict === 'axis-only') {
    L.push('> 残差都落在现有轴上 ⇒ **不必新增维度**；要提召回请走 `--apply` 补词（对应候选见上文「建议补词」）。');
    L.push('');
  }

  if (dg.unclustered.length) {
    L.push('未归类（' + dg.unclustered.length + ' 条，逐条判读）：');
    L.push('');
    L.push('| # | 档 | 年 | 标题 | 原因 |');
    L.push('|---|---|---|---|---|');
    dg.unclustered.forEach((x, i) => {
      L.push('| ' + (i + 1) + ' | ' + (REL.LEVEL_LABEL[x.level] || x.level) + ' | ' + (x.year || '—')
        + ' | ' + mdCell(clip(x.title, 120)) + ' | ' + (REASON[x.reason] || x.reason) + ' |');
    });
    L.push('');
  }
  return L.join('\n') + '\n';
}

/**
 * 多轮迭代报告（`--iterate` 时内嵌进主视图）。
 * ★ 免责声明是**硬要求**：迭代自动取词 ⇒ 产物不得被当成建议词表。
 *   故标题写「上限探测」、正文首句写「不代表建议词表」、词表块标题写「待人工确认」——
 *   三处冗余表达同一个约束（人眼极易只读到其中一处）。
 */
function renderIterateReport(it, opts) {
  const o = opts || {};
  const L = [];
  const REASON = {
    'no-candidates': '无候选',
    'all-covered': '候选已全部覆盖',
    'no-gain': '无增益',
    'max-rounds': '达轮数上限',
  };
  const signed = n => (n > 0 ? '+' : '') + n;
  const termsInline = list => (list && list.length ? list.map(t => '`' + t + '`').join('、') : '—');

  L.push('## 多轮迭代闭环（**上限探测**，不代表建议词表）');
  L.push('');
  L.push('> ⚠ 本小节是**模拟**结果：迭代自动按批量取词（pick=' + it.pick + '，每轮至多 ' + it.batch
    + ' 个），**不代表建议词表**。真正采纳请用 `--apply` 显式勾选。');
  L.push('');
  L.push('- 起始：主题命中 ' + it.baseline.stat.exact + ' / ' + it.baseline.total
    + '（命中率 ' + it.baseline.exactRate + '%）');
  L.push('- 停止原因：**' + (REASON[it.stopReason] || it.stopReason) + '**（`' + it.stopReason + '`）—— '
    + it.stopDetail);
  L.push('- 实际轮次：' + it.saturationRound + ' / 上限 ' + it.maxRounds
    + ' · 累计补词 ' + it.totalAppended + ' 个 · 主题命中净增 **' + signed(it.totalGain) + '**');
  L.push('- 最终：主题命中 ' + it.final.stat.exact + ' / ' + it.final.total
    + '（命中率 **' + it.final.exactRate + '%**）');
  L.push('- 站点请求：**' + it.stationRequests + '**（迭代全程纯本地，站点不重跑）');
  L.push('');
  L.push('### 每轮增益');
  L.push('');
  L.push('| 轮 | 补入 | 主题命中 | 命中率 | 本轮增量 | 降级 | 候选池 |');
  L.push('|---|---|---|---|---|---|---|');
  L.push('| 0 | （起始） | ' + it.baseline.stat.exact + ' | ' + it.baseline.exactRate + '% | — | — | — |');
  it.rounds.forEach(r => {
    L.push('| ' + r.n + ' | ' + mdCell(termsInline(r.appended)) + ' | ' + r.stat.exact
      + ' | ' + r.exactRate + '% | ' + (r.appended.length ? signed(r.deltaExact) : '—')
      + ' | ' + r.downgraded + ' | ' + r.candidatesSeen + ' |');
  });
  L.push('');
  if (it.rounds.some(r => r.downgraded > 0)) {
    L.push('> ⚠ 出现降级 ⇒ 违反「补词只增命中」不变量，须人工核查（不可当作正常波动）。');
    L.push('');
  }

  const deferAll = [];
  for (const r of it.rounds) for (const d of r.deferred) if (deferAll.indexOf(d) < 0) deferAll.push(d);
  if (deferAll.length) {
    L.push('### 待人工判断（被 pick 过滤，未自动补）');
    L.push('');
    L.push('以下候选与词表词**半重叠**（可能是真缺词，也可能是 n-gram 分词错位），'
      + '`pick=' + it.pick + '` 不自动补：');
    L.push('');
    L.push(deferAll.map(t => '`' + t + '`').join('、'));
    L.push('');
  }

  if (it.residual && it.residual.length) {
    L.push('### 收敛后仍非主题命中的记录（' + it.residual.length + ' 条 · **结构性缺口，补词治不了**）');
    L.push('');
    L.push('> 这些记录的问题**不是「词表写法不够」**，而是缺少对应的主题维度 —— 继续补词只会围绕同一批字面打转，'
      + '须人工判断是否新增主题（或确认它本属跑题）。');
    L.push('');
    L.push('| # | 档 | 年 | 标题 |');
    L.push('|---|---|---|---|');
    it.residual.forEach((x, i) => {
      L.push('| ' + (i + 1) + ' | ' + (REL.LEVEL_LABEL[x.level] || x.level) + ' | ' + (x.year || '—')
        + ' | ' + mdCell(clip(x.title, 120)) + ' |');
    });
    L.push('');
  }

  if (it.convergence) {
    L.push(renderConvergence(it.convergence).replace(/\s+$/, ''));
    L.push('');
  }
  if (it.crossRun) {
    L.push(renderCrossRun(it.crossRun).replace(/\s+$/, ''));
    L.push('');
  }
  if (it.diagnosis) L.push(renderDiagnosis(it.diagnosis).replace(/\s+$/, ''));
  if (it.diagnosis && it.diagnosis.queries) {
    L.push(renderQueryPlans(it.diagnosis.queries).replace(/\s+$/, ''));
    L.push('');
  }

  L.push('### 迭代产出的词表（**待人工确认**，勿直接当 `--topic` 用）');
  L.push('');
  L.push('```');
  L.push(it.terms.join(','));
  L.push('```');
  L.push('');
  L.push('> 确认方式：从中挑出你认可的词，用 `--apply` 显式补入 —— 本小节不产生任何「已采纳」结论。');
  L.push('');
  return L.join('\n') + '\n';
}

/**
 * 建议检索式小节（诊断 → 处方）。**只出方案，不执行**。
 * 单独成节而非塞进诊断表格：检索式要能整条复制，表格会把 `|` 与换行吃掉。
 */
function renderQueryPlans(qp) {
  const L = [];
  const SP = { auto: '按题名自动探测', both: '命令行指定 both', cat: '命令行指定 cat',
    dog: '命令行指定 dog', none: '命令行指定 none（不加物种限定）' };
  L.push('### 建议检索式（**未执行** · 仅作下一步候选）');
  L.push('');
  L.push('> 由上面「新维度」簇推出，**一条都没有跑过**（站点请求 0）。逐条复核后再自行执行。');
  L.push('> 站点语法白名单 = `AND` / `OR` / 括号 / 自由词；引号短语与 `-排除词` 实测返回 0 条。');
  L.push('');
  L.push('- 物种块 `' + qp.species + '`（' + (SP[qp.speciesSource] || qp.speciesSource) + '）'
    + ' · 每条式术语上限 ' + qp.cap);
  if (qp.skipped && qp.skipped.length) {
    L.push('- 未出方案：' + qp.skipped.length + ' 个同轴簇（`axis-extend` —— 用 `--apply` 补词更省，'
      + '不必另开检索方向）');
  }
  if (qp.droppedSpeciesGlue) {
    L.push('- 已剔除含物种词素的术语 ' + qp.droppedSpeciesGlue + ' 个（式内已有物种块，'
      + '术语再带物种会让式子自相矛盾）');
  }
  if (qp.suppressed && qp.suppressed.length) {
    L.push('- 已抑制 ' + qp.suppressed.length + ' 个维度（'
      + qp.suppressed.map(x => '`' + x.cluster + '`').join('、')
      + '）：跨运行**结论未变**（`persistent` + `stalled`，已报过 ≥2 次）⇒ 不再重复出式子，'
      + '见上方「跨运行记忆」小节');
  }
  L.push('');

  if (!qp.plans.length) {
    L.push(qp.suppressed && qp.suppressed.length
      ? '（本次没有需要新出的式子：上述维度均因跨运行抑制被跳过，式子见上次报告）'
      : '（本次没有新维度簇 ⇒ 不产出检索式）');
    L.push('');
    return L.join('\n');
  }

  qp.plans.forEach((x, i) => {
    L.push('**[R' + (i + 1) + ' · ' + x.lang + ']** 来源簇 `' + x.cluster + '`'
      + '（支持 ' + (x.support == null ? '—' : x.support) + ' 条 · '
      + (x.confidence === 'strong' ? '强' : '弱') + '）');
    if (x.clusterStatus) {
      L.push('');
      L.push('- 维度状态：**' + (CONV_STATUS[x.clusterStatus] || x.clusterStatus) + '**'
        + '（`' + x.clusterStatus + '`' + (x.clusterPersistRounds ? ' · 已观测 '
          + x.clusterPersistRounds + ' 轮' : '') + '）');
    }
    L.push('');
    L.push('```');
    L.push(x.query);
    L.push('```');
    if (x.anchors && x.anchors.length) {
      L.push('- 主题锚：' + x.anchors.join('、') + '（把主题写回式子，避免只检索到「维度大类」）');
    } else {
      L.push('- 主题锚：**无** —— 该语言下词表没有可用作锚的术语，式子只限定「物种 × 维度」');
    }
    if (x.warnings && x.warnings.length) x.warnings.forEach(w => L.push('- ⚠ ' + w));
    L.push('');
  });
  L.push('> 每条式为 `verified: false`（未实测）。**不要**把它的术语直接写进词表 —— '
    + '采纳仍只走 `--apply`。');
  L.push('');
  return L.join('\n');
}

function renderMarkdown(result, opts) {
  const o = opts || {};
  const rows = o.all ? result.ranked : result.ranked.slice(0, o.top || 10);
  const t = result.topic;
  const L = [];
  L.push('# 主题相关性排序（本地打分，零站点请求）');
  L.push('');
  L.push('- 主题词: ' + t.terms.join(' / '));
  if (t.near.length) L.push('- 相邻词: ' + t.near.join(' / '));
  if (t.exclude.length) L.push('- 排除词: ' + t.exclude.join(' / '));
  L.push('- 词权重: 题名 ×' + REL.W.title + ' / 摘要 ×' + REL.W.abstract
    + '（相邻词 题名 ×' + REL.W.titleNear + ' / 摘要 ×' + REL.W.abstractNear
    + '；排除词 ' + REL.W.exclude + ' 且一票否决）');
  L.push('- 总条数: ' + result.total + ' —— 主题命中 **' + result.stat.exact + '** · 相邻 '
    + result.stat.near + ' · 跑题 ' + result.stat.off + ' · 排除 ' + result.excluded);
  L.push('- 主题命中率: **' + result.exactRate + '%**');
  L.push('- 站点请求: **' + result.stationRequests + '**（本步骤不联网，只读已落盘结果；改词表可零成本重排）');
  L.push('');
  if (o.applyDiff) L.push(renderApplyDiff(o.applyDiff, o));
  if (o.iterateReport) L.push(renderIterateReport(o.iterateReport, o));
  L.push('| # | 档 | 分 | 年 | 主题命中 | 相邻命中 | 排除 | 标题 |');
  L.push('|---|---|---|---|---|---|---|---|');
  for (const r of rows) {
    L.push('| ' + r.rank + ' | ' + r.rel.levelLabel + ' | ' + r.rel.score + ' | ' + (r.rec.year || '—')
      + ' | ' + mdCell(termsOf(r.rel.titleHits.concat(r.rel.abstractHits)))
      + ' | ' + mdCell(termsOf(r.rel.nearHits))
      + ' | ' + mdCell(r.rel.excludeHits.map(h => h.term).join('、') || '—')
      + ' | ' + mdCell(clip(titleOf(r.rec), 120)) + ' |');
  }
  if (!rows.length) L.push('| — | — | — | — | — | — | — | （无可排序记录） |');
  L.push('');
  if (result.topic.warnings && result.topic.warnings.length) {
    L.push('> 词表提示：' + result.topic.warnings.join('；'));
    L.push('');
  }

  // 命中上下文：人工判断「精确命中 vs 歧义命中」的唯一依据
  const ctx = rows.filter(r => r.rel.hits.length || r.rel.excludeHits.length);
  if (ctx.length) {
    L.push('## 命中上下文（供判断是否歧义命中）');
    L.push('');
    for (const r of ctx) {
      L.push(r.rank + '. **' + clip(titleOf(r.rec), 90) + '**（' + r.rel.levelLabel + ' / ' + r.rel.score + '）');
      for (const h of r.rel.hits.concat(r.rel.excludeHits)) {
        // 三态标注：相邻词绝不能标成「主题」，否则正文与表格口径自相矛盾（实测踩过）
        const kindLabel = h.kind === 'exclude' ? '排除' : (h.kind === 'near' ? '相邻' : '主题');
        L.push('   - [' + kindLabel + ']「' + h.term + '」命中' + (h.field === 'title' ? '题名' : '摘要') + '：' + clip(h.snippet, 110));
      }
    }
    L.push('');
  }
  if (o.suggest) L.push(...renderSuggestSection(o.suggest));
  return L.join('\n') + '\n';
}

function csvEsc(v) {
  const s = String(v == null ? '' : v);
  return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
}

function renderCsv(result, opts) {
  const o = opts || {};
  const rows = o.all ? result.ranked : result.ranked.slice(0, o.top || 10);
  const head = ['rank', 'level', 'score', 'year', 'excluded', 'title_hits', 'abstract_hits', 'near_hits', 'exclude_hits', 'title', 'source', 'authors', 'doi', 'paper_url'];
  const L = [head.join(',')];
  for (const r of rows) {
    L.push([
      r.rank, r.rel.level, r.rel.score, r.rec.year || '', r.rel.excluded ? 1 : 0,
      r.rel.titleHits.map(h => h.term).join('|'),
      r.rel.abstractHits.map(h => h.term).join('|'),
      r.rel.nearHits.map(h => h.term).join('|'),
      r.rel.excludeHits.map(h => h.term).join('|'),
      titleOf(r.rec), r.rec.source || '', r.rec.authors || '',
      r.rec.doi || r.rec.doiFromUrl || '', r.rec.paperUrl || '',
    ].map(csvEsc).join(','));
  }
  return L.join('\r\n') + '\r\n';
}

/**
 * iterate 报告的**精简视图**（CLI 的 JSON 通道）。
 * ★ 必须抽成函数并被单测直接覆盖：JSON 通道是**逐字段显式挑选**的，漏写一个字段既不报错、
 *   也不影响 md 视图，只会静默缺字段（2026-10-18 实测：`diagnosis.queries` 就漏在这里 ——
 *   当时的用例直接喂 `iterateRounds()` 的返回值，绕过了本函数 ⇒ 全绿且线上缺字段）。
 *   故用例必须调本函数，而不是直接用原始对象。
 */
function compactIterate(it) {
  if (!it) return null;
  const dg = it.diagnosis;
  return {
    pick: it.pick, batch: it.batch, maxRounds: it.maxRounds,
    stopReason: it.stopReason, stopDetail: it.stopDetail,
    rounds: it.rounds.map(r => ({
      n: r.n, appended: r.appended, deferred: r.deferred,
      exact: r.stat.exact, deltaExact: r.deltaExact, downgraded: r.downgraded,
    })),
    totalGain: it.totalGain, totalAppended: it.totalAppended,
    terms: it.terms,
    diagnosis: dg ? {
      verdict: dg.verdict, verdictNote: dg.verdictNote,
      autoApply: dg.autoApply,
      // 跨运行记忆是否参与本次诊断（false ⇒ 后续三字段恒 null/0/false，勿当「首次」读）
      // ★ 单一来源 = iterate.cjs 写在 diagnosis 上；此处**只透传**，不重算（两处判据会漂移）
      crossActive: dg.crossActive === true,
      residual: dg.residual, fingerprints: dg.fingerprints,
      clusters: dg.clusters.map(c => ({
        kind: c.kind, label: c.label, support: c.support, confidence: c.confidence,
        terms: c.terms.map(x => x.term), idxs: c.idxs,
        // 收敛状态（由 convergence 贴回）：null = 未追踪，不得当「已收敛」读
        status: c.status == null ? null : c.status,
        stallRounds: c.stallRounds == null ? null : c.stallRounds,
        // 跨运行（由 converge-state 贴回）：trend 为 null = 未追踪，不得当「首次」
        trend: c.trend == null ? null : c.trend,
        reportCount: c.reportCount == null ? 0 : c.reportCount,
        suppress: c.suppress === true,
      })),
      proposal: dg.proposal,
      unclustered: dg.unclustered.length,
      // 建议检索式：只出方案、不执行（`executed` 恒 false 由 query-plan 保证）
      queries: dg.queries || null,
    } : null,
    // 维度收敛判据：跨轮追踪的结果（只读；不参与循环控制）
    convergence: it.convergence ? {
      criterion: it.convergence.criterion,
      state: it.convergence.state,
      converged: it.convergence.converged,
      observations: it.convergence.observations,
      rounds: it.convergence.rounds,
      residualSeries: it.convergence.residualSeries,
      residualMonotonic: it.convergence.residualMonotonic,
      live: it.convergence.live,
      cappedCount: it.convergence.cappedCount,
      counts: it.convergence.counts,
      note: it.convergence.note,
      clusters: it.convergence.clusters.map(c => ({
        key: c.key, label: c.label, kind: c.kind, status: c.status,
        support: c.support, supportSeries: c.supportSeries,
        persistRounds: c.persistRounds, stallRounds: c.stallRounds,
      })),
    } : null,
    // 跨运行记忆（null = 未传 --converge-state；★ 与「首次运行」不同，勿混读）
    crossRun: it.crossRun ? {
      status: it.crossRun.status,
      reason: it.crossRun.reason,
      runs: it.crossRun.runs,
      corpusChanged: it.crossRun.corpusChanged,
      savedAt: it.crossRun.savedAt,
      format: it.crossRun.format == null ? null : it.crossRun.format,
      otherSlots: it.crossRun.otherSlots == null ? 0 : it.crossRun.otherSlots,
      slotCount: it.crossRun.slotCount == null ? null : it.crossRun.slotCount,
      evicted: (it.crossRun.evicted || []).map(e => ({ hash: e.hash, topic: e.topic, savedAt: e.savedAt })),
      summary: it.crossRun.summary,
      suppressedKeys: it.crossRun.suppressedKeys,
      clusters: it.crossRun.clusters.map(c => ({
        key: c.key, label: c.label, kind: c.kind, trend: c.trend,
        status: c.status, priorStatus: c.priorStatus,
        support: c.support, priorSupport: c.priorSupport,
        supportDelta: c.supportDelta == null ? null : c.supportDelta,
        reportCount: c.reportCount, suppress: c.suppress,
        uncertain: !!c.uncertain,
      })),
    } : null,
  };
}

function renderJson(result, opts) {
  const o = opts || {};
  const rows = result.ranked.map(r => ({
    rank: r.rank, level: r.rel.level, levelLabel: r.rel.levelLabel, score: r.rel.score,
    excluded: r.rel.excluded, year: r.rec.year || null, keyword: r.keyword,
    titleHits: r.rel.titleHits, abstractHits: r.rel.abstractHits,
    nearHits: r.rel.nearHits, excludeHits: r.rel.excludeHits,
    title: titleOf(r.rec),
    ...(o.full ? { record: r.rec } : {}),
  }));
  return JSON.stringify({
    version: result.version, stationRequests: result.stationRequests, topic: result.topic,
    total: result.total, stat: result.stat, excluded: result.excluded, exactRate: result.exactRate,
    ...(o.suggest ? { suggest: o.suggest } : {}),
    ...(o.applyDiff ? { applyDiff: o.applyDiff } : {}),
    ...(o.iterateReport ? { iterate: o.iterateReport } : {}),
    ranked: rows,
  }, null, 2) + '\n';
}

// ------------------------------------------------------------------ 入口

function main(argv) {
  const o = parseArgs(argv);
  if (o.help) { console.log(HELP); return; }
  if (!o.dir) fail('[参数错误] 缺少 --dir <search 输出目录>\n  示例: --dir ./run --topic "毛球,化毛,hairball"');
  if (!o.topic) fail('[参数错误] 缺少 --topic <词表>（本步骤是靠词表过滤，无词表则无从排序）\n  示例: --topic "毛球,化毛,hairball"');

  const rawDir = path.join(o.dir, 'raw');
  if (!fs.existsSync(rawDir)) {
    fail('[输入错误] ' + o.dir + ' 下没有 raw/ 子目录\n'
      + '  rank-records 指向的是 search-papers 的**输出目录**（其中含 raw/*.json）。\n'
      + '  请先跑检索：node search-papers.cjs --keywords "…" --out ' + o.dir);
  }

  let topic = REL.buildTopic({ terms: o.topic, near: o.near, exclude: o.exclude });
  const { groups, skippedCorrupt } = readRawGroups(rawDir, null);
  let result = REL.rankAll(groups, topic);

  // 补词闭环：**必须显式** --apply 才改词表（任何「自动补词」都会让「覆盖靠人」失守）。
  // 重排完全本地进行（只读同一批 raw/*.json）⇒ 站点无需重跑，零新增请求。
  let applied = null;
  let applyDiff = null;
  if (o.apply) {
    applied = REL.mergeTerms(o.topic, o.apply);
    if (!applied.appended.length) {
      fail('[输入错误] --apply 的勾选词**已全部在 --topic 中**，无可追加项\n'
        + '  勾选词: ' + o.apply + '\n  现有词表: ' + applied.terms.join(',')
        + '\n  提示: 请从「建议补词」小节的候选里挑词（直接拷贝该词文本）');
    }
    const topicV2 = REL.buildTopic({ terms: applied.terms, near: o.near, exclude: o.exclude });
    const resultV2 = REL.rankAll(groups, topicV2);
    applyDiff = REL.diffRanks(result, resultV2, { addedTerms: applied.appended });
    result = resultV2;      // 主视图 = 补词后（对比小节内嵌其中）
    topic = topicV2;        // 覆盖诊断同基于词表 v2 ⇒ 不再重复提示刚补进去的词
  }

  // 跨运行记忆：状态文件的读在此处（lib 侧纯函数不碰 FS），写则在**报告落盘之后**。
  //   （与 --iterate 的配对已在 parseArgs 校验，此处不再重复判。）
  const convergePath = resolveConvergePath(o);
  const priorFile = convergePath ? readStateFile(convergePath) : null;

  // 多轮迭代（**上限探测**）：与 --apply 互斥 —— 前者自动取词只作估计，后者才是人工采纳。
  let iterateReport = null;
  if (o.iterate) {
    if (o.apply) {
      fail('[参数错误] --iterate 与 --apply 不可同时使用\n'
        + '  --iterate 是**上限探测**（自动批量取词，不代表建议词表）；--apply 是**人工勾选后采纳**。\n'
        + '  建议：先 --iterate 3 看上限，再用 --apply 补你认可的词。');
    }
    iterateReport = IT.iterateRounds({
      groups,
      topicSpec: { terms: o.topic, near: o.near, exclude: o.exclude },
      maxRounds: o.iterate, batch: o.iterateBatch, pick: o.iteratePick,
      minDf: o.minDf, scope: o.suggestScope, suggestTop: o.suggestTop,
      species: o.species, queryCap: o.queryCap,
      priorFile,                 // null = 不记忆（零回归：不传则行为与之前完全一致）
    });
  }

  // ★ 批 2（2026-10-24）：写前重读并重建待写状态。
  //   病灶：`buildState` 里「保留其他主题的槽」用的是传入的 `prevFile`，而 iterate 拿到的是
  //   **run 开始那一刻**的快照；中间隔着整批站点请求与多轮迭代（分钟级）。并发跑另一个主题时，
  //   它新建的槽会被这份陈旧快照覆盖 —— 实测 3 轮并发 3/3 只存活 1 个槽。
  //   ⇒ 这里重读磁盘，用新鲜快照重建。本主题槽只取决于本轮计算结果（与 prevFile 无关），
  //     所以重建不会改变本槽，只是把「别人的槽」换成最新版本。
  //   ⚠ 边界（不得读成「零丢失」）：① 重读与 rename 之间仍有毫秒级窗口；
  //     ② **同主题**的并发更新仍互相覆盖（本主题槽永远被本轮 slot 取代）—— 那要真正的锁，不在本批。
  if (convergePath && iterateReport && iterateReport.stateInput) {
    const fresh = readStateFile(convergePath);
    const rebuilt = CSG.buildState(Object.assign({}, iterateReport.stateInput, { prevFile: fresh.data }));
    iterateReport.stateNext = rebuilt.state;
    // 报告里的这两个数字必须跟着重建结果走（否则会出现「报告说 2 个槽、文件里只剩 1 个」）
    if (iterateReport.crossRun) {
      iterateReport.crossRun.slotCount = rebuilt.state.slots.length;
      iterateReport.crossRun.evicted = rebuilt.evicted;
    }
  }

  // 覆盖诊断：与排序同源数据、**零站点请求**。定位是给人挑词，不自动改词表。
  const suggest = o.suggest
    ? SG.buildSuggestions(result.ranked, topic, { scope: o.suggestScope, minDf: o.minDf, suggestTop: o.suggestTop })
    : null;
  const ropts = Object.assign({}, o, suggest ? { suggest } : {},
    applyDiff ? { applyDiff, topicTextV2: applied.terms.join(',') } : {},
    iterateReport ? { iterateReport } : {});

  const prefix = o.out || path.join(o.dir, 'ranked');
  // 输出目录可能尚不存在（--out ./run/deep/ranked）⇒ 必须先建，否则 writeFileSync 直接 ENOENT。
  // 注意：这里只管 --out 前缀，与下方 convergePath 的状态文件目录是两件独立的事。
  const outDir = path.dirname(prefix);
  if (outDir && outDir !== '.' && !fs.existsSync(outDir)) fs.mkdirSync(outDir, { recursive: true });
  const written = [];
  const want = f => o.format === 'both' || o.format === f;
  if (want('md')) {
    const p = prefix + '.md';
    fs.writeFileSync(p, renderMarkdown(result, ropts), 'utf8');
    written.push(p);
  }
  if (want('csv')) {
    const p = prefix + '.csv';
    fs.writeFileSync(p, renderCsv(result, ropts), 'utf8');
    written.push(p);
  }
  if (want('json')) {
    const p = prefix + '.json';
    fs.writeFileSync(p, renderJson(result, ropts), 'utf8');
    written.push(p);
  }

  // ★ 顺序纪律：状态必须在**报告全部落盘之后**写。反过来的话，报告没生成但状态已记「已报过」，
  //   下一轮就会静默抑制掉本该出现的建议（且人无从察觉）。
  let stateWritten = null;
  if (convergePath && iterateReport && iterateReport.stateInput) {
    // ★ 必须原子写，不能直接 writeFileSync：状态文件是「读-改-写」型，
    //   而 `readPrior` 把「解析失败」判为 CORRUPT 并**覆盖写回**。
    //   非原子写期间并发读者会读到空文件/半截 JSON（实测 200 次写：空读 128、解析失败 67），
    //   于是一次偶然并发 = 全部主题槽被清空。rename 后读者只可能看到完整旧版或完整新版。
    //   父目录自建已由模块负责（不再在调用点重复做）。
    //
    // ★ 批 3：加互斥锁 + CAS 重试（实现见 writeStateWithMerge）。
    //   批 2 只做「重读 + 写前二次确认」，实测 20 轮仍有 4 轮丢槽：两进程几乎同时确认 + 写，
    //   双双通过校验 ⇒ 后写覆盖先写。文件系统没有「比较并交换」原语，无锁做不到零丢失 ⇒ 只能加锁。
    //   锁只覆盖「重读 → rename」的毫秒级窗口（状态每次 run 只在最后写一次），不是整次 run。
    const res = writeStateWithMerge(convergePath, iterateReport.stateInput);
    if (res.backup) {
      // ★ 批 4：旧状态不可用 ⇒ 已原样留档再覆盖。必须让人看见，否则「原来那份文件去哪了」无解。
      process.stderr.write('[提示] 旧状态文件不可用（'
        + (res.backup.status === 'corrupt' ? '解析失败' : '版本不符') + '），已原样备份到 '
        + res.backup.path + '（' + res.backup.bytes + ' B）后重建\n');
    }
    if (res.skipped) {
      if (res.backupFailed) {
        // ★ 批 4：旧状态不可用**且**备份失败 ⇒ 拒绝覆盖。原因必须给全（用户要据此查磁盘/权限）。
        process.stderr.write('[警告] 旧状态文件不可用且备份失败（' + res.reason + '），'
          + '本轮**不写**状态记忆 —— 否则旧内容会被永久覆盖、再也拿不回来。'
          + '请检查磁盘空间与目录权限：' + convergePath + '\n');
      } else {
        // ★ 拿不到锁 ⇒ fail-closed：不写。必须让人看见（否则「状态已保存」是假象）。
        //   丢一轮记忆可以重算；无锁覆盖别人的槽是不可逆的数据丢失。
        process.stderr.write('[警告] 状态文件锁等待 ' + res.lockWaitMs + ' ms 超时'
          + (res.holder && res.holder.pid ? '（持有者 pid=' + res.holder.pid + '）' : '')
          + '，本轮**不写**状态记忆；下一轮会重建。锁文件：' + FL.lockPathFor(convergePath) + '\n');
      }
      if (iterateReport.crossRun) iterateReport.crossRun.writeSkipped = res.reason;
    } else if (iterateReport.crossRun) {
      // 报告里的槽数/淘汰以**真正写进文件**的为准（渲染时那次重建可能已被后续竞争取代）
      iterateReport.crossRun.slotCount = res.built.state.slots.length;
      iterateReport.crossRun.evicted = res.built.evicted;
      iterateReport.crossRun.writeAttempts = res.attempts;
      if (res.forced) {
        // 重试耗尽仍被抢 ⇒ 必须让人看见（否则「状态已保存」是假象）
        process.stderr.write('[警告] 状态文件竞争激烈，重试 ' + res.attempts
          + ' 次后强制写入，可能丢失其他主题的最新槽\n');
      }
    }
    if (!res.skipped) stateWritten = convergePath;
  } else if (convergePath && iterateReport && iterateReport.stateNext) {
    AW.writeAtomicSync(convergePath, CSG.serialise(iterateReport.stateNext), 'utf8');
    stateWritten = convergePath;
  }

  const s = REL.summarize(result, o.top);
  console.log(JSON.stringify({
    ok: true,
    stationRequests: result.stationRequests,
    dir: o.dir,
    total: s.total, stat: s.stat, excluded: s.excluded, exactRate: s.exactRate,
    skippedCorrupt: skippedCorrupt.length,
    topicWarnings: topic.warnings,
    applied: applied ? { appended: applied.appended, topicV2: applied.terms.join(',') } : null,
    iterate: compactIterate(iterateReport),
    convergeState: stateWritten,
    applyDiff: applyDiff ? {
      delta: applyDiff.delta, pairs: applyDiff.pairs, unmatched: applyDiff.unmatched,
      upgraded: applyDiff.upgraded.length, downgraded: applyDiff.downgraded.length,
      upgradedTop: applyDiff.upgraded.slice(0, 10).map(u => ({
        idx: u.idx, title: u.title, from: u.levelFrom, to: u.levelTo, newHits: u.newHits,
      })),
    } : null,
    suggest: suggest ? {
      scope: suggest.scope, corpus: suggest.corpus, dropped: suggest.dropped,
      suggestedTopicSuffix: suggest.suggestedTopicSuffix,
      candidates: suggest.candidates.map(c => ({
        term: c.term, df: c.df, extendsTopic: c.extendsTopic, overlapsTopic: c.overlapsTopic,
        inNear: c.inNear,
      })),
    } : null,
    written,
    top: s.topN,
  }, null, 2));
}

module.exports = { CONVERGE_DEFAULT, resolveConvergePath, readStateFile, stateFingerprint, backupUnusableState, writeStateWithMerge, STATE_WRITE_TRIES, FL, parseArgs, main, renderMarkdown, renderCsv, renderJson, renderApplyDiff, renderIterateReport, renderDiagnosis, renderConvergence, renderCrossRun, renderQueryPlans, compactIterate, HELP };

if (require.main === module) {
  try {
    main(process.argv);
  } catch (e) {
    if (e instanceof CliError) { console.error(e.message); process.exit(e.code); }
    throw e;
  }
}
