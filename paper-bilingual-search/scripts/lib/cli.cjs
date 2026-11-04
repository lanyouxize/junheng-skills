#!/usr/bin/env node
/* eslint-disable */
/**
 * cli.cjs — 输入层纯逻辑（参数解析 / 关键词归一 / 文件读取 / 输出命名 / 目录准备）
 *
 * 设计约束（见 CHANGELOG.md 的 v4 条目）：
 *   1) 零第三方依赖，只用 node 内置 fs / path。
 *   2) parseArgs() 是**纯函数**：不读文件、不写文件、不打印、不退出。
 *      只做 argv → opts 的映射；遇到非法输入抛 CliError，由调用方决定怎么退出。
 *      因此它可以被离线单测直接喂一个字符串数组，不需要起浏览器、不需要起子进程。
 *   3) 数值默认值一律用 ?? / 显式比较判定，**禁止 `||`**——`||` 会把合法值 0 当 falsy 吞掉
 *      （v3 实测：`--limit 0` 实得 10、`--fill-min 0` 实得 0.9）。
 *   4) 任何「静默」行为都必须变成显式 notices：重复参数、疑似被空格拆分的检索式、
 *      plan.json 解析失败……一律打印到 stderr（stdout 是 JSON 事件流，不可污染）。
 *   5) `--site` 是**白名单枚举**（v4.1）：未接通的站点必须显式报错退出，
 *      不得静默回落到默认站点——否则产出里的 site 元数据会说谎。
 */
'use strict';

const fs = require('fs');
const path = require('path');
// v4.15（A-2）：多源通道的源白名单**必须**在输入层校验，不能等跑检索时才炸。
// 依赖方向是 cli → sources（sources 不反向依赖 cli），无环。
const { resolveSources, sourceIds } = require('./sources/index.cjs');

/** 冻结的默认值表（C2 判据冻结对象：任何改动都必须同步 CHANGELOG 与单测） */
const TOOL_DEFAULTS = Object.freeze({
  site: 'kuluer',
  // 多源 HTTP 通道：默认 null = **完全走原浏览器站点通道**（v4.14 行为，零变化）
  sources: null,
  sourceTimeoutSec: 120,
  sourceConcurrency: 2,
  mailto: null,
  limit: 10,
  headless: false,
  gateTimeoutSec: 300,
  interval: Object.freeze([2500, 4500]),
  enrich: false,
  dedupe: false,
  fulltext: false,
  fulltextConcurrency: 2,
  // v4.15（B 批）：全文链的浏览器兜底**默认关闭**。
  //   实测（15 篇真实回归）：开与不开都是 9/15，A1/A5/A6/A8 全部卡在
  //   Cloudflare 的 `Just a moment...`（headless 与 headed 都过不去），
  //   4 篇 closed 的出版商页则必然要登录。开了只多几分钟等待，换 0 篇增量。
  fulltextBrowser: false,
  fillMin: 0.9,
  plan: null,
  evidence: false,
  readyTimeoutSec: 45,
  keywordTimeoutSec: 300,
  enrichConcurrency: 4,
});

/**
 * 站点白名单：只有**抓取实现真正接通**的站点才能出现在这里。
 * 背景（v4.1 修复的缺陷）：v3/v4 把 `--site` 当普通字符串直通，`searchKuluer()` 却硬编码
 * kuluer 的 URL —— 传 `--site panda985` 不生效、**且不报错**，而 `summary.site` 与 PRISMA meta
 * 会把站点记成 panda985（元数据说谎）。故改为：白名单外的取值一律显式报错退出。
 */
const SUPPORTED_SITES = Object.freeze(['kuluer']);

/** 已探查但本版本**未接通**的站点：给出专属提示，避免用户以为是自己拼错了 */
const UNIMPLEMENTED_SITES = Object.freeze({
  panda985: '通道 B（sc.panda985.com）已探查但本版本未接通，搜索函数固定请求 kuluer。'
    + '放行它会让 summary/PRISMA 的 site 字段显示为 panda985 而实际抓的是 kuluer。',
});

/** 参数规格表：把 16 个参数的形态集中声明，避免 16 个 if 分支各自兜底（v3 的缺陷温床） */
const ARG_SPEC = Object.freeze({
  '--keywords': { kind: 'varargs' },
  '--keywords-file': { kind: 'string', key: 'keywordsFile', example: 'keywords.txt' },
  '--plan': { kind: 'string', key: 'plan', example: 'plan.json' },
  '--evidence': { kind: 'bool', key: 'evidence' },
  '--limit': { kind: 'int', key: 'limit', min: 0, max: 10000, example: '10' },
  '--out': { kind: 'string', key: 'out', example: 'OUT_DIR' },
  '--dir': { kind: 'string', key: 'out', example: 'OUT_DIR' }, // --out 的等价别名
  '--site': { kind: 'enum', key: 'site', values: SUPPORTED_SITES, example: 'kuluer' },
  '--headless': { kind: 'bool', key: 'headless' },
  '--enrich': { kind: 'bool', key: 'enrich' },
  '--dedupe': { kind: 'bool', key: 'dedupe' },
  '--ready-timeout': { kind: 'int', key: 'readyTimeoutSec', min: 1, max: 3600, example: '45' },
  '--fill-min': { kind: 'float', key: 'fillMin', min: 0, max: 1, example: '0.9' },
  '--keyword-timeout': { kind: 'int', key: 'keywordTimeoutSec', min: 1, max: 86400, example: '300' },
  '--gate-timeout': { kind: 'int', key: 'gateTimeoutSec', min: 1, max: 86400, example: '300' },
  '--interval': { kind: 'pair', key: 'interval', min: 0, max: 600000, example: '2500,4500' },
  // v4.3：Europe PMC 补全的有界并发度（1 = 严格串行，复刻 v4.2 行为）。上限 16 防误配成压测。
  '--enrich-concurrency': { kind: 'int', key: 'enrichConcurrency', min: 1, max: 16, example: '4' },
  // v4.10：全文通道。默认关闭 —— 单篇 JATS XML 实测 113KB，只落盘文本化后的 .txt。
  // 上限 4：全文比检索响应重得多，压测风险不应靠用户自觉。
  '--fulltext': { kind: 'bool', key: 'fulltext' },
  '--fulltext-concurrency': { kind: 'int', key: 'fulltextConcurrency', min: 1, max: 4, example: '2' },
  '--fulltext-browser': { kind: 'bool', key: 'fulltextBrowser' },
  // ── v4.15（A-2）：多源 HTTP 通道 ──
  // 不给 --sources ⇒ 走原浏览器站点通道（默认，行为与 v4.14 完全一致）。
  // 给了 ⇒ 只走 HTTP 源，**不启动浏览器**（无 Edge/Chrome 的 CI 环境可用）。
  '--sources': { kind: 'string', key: 'sources', example: 'all' },
  // 礼貌池标识：Crossref 建议带 mailto（不带也能用，但被限流时无协商余地）
  '--mailto': { kind: 'string', key: 'mailto', example: 'you@example.com' },
  // 单源外层超时：必须大于连接器内层「单次 25s × 3 次重试 + 退避」的最坏值，否则会制造假失败。
  // 下限 5s 是「防手滑设成 1s」，上限 1 小时与 --keyword-timeout 对齐。
  '--source-timeout': { kind: 'int', key: 'sourceTimeoutSec', min: 5, max: 3600, example: '120' },
  // http 源并发度。上限 8：公开 API 的限流阈值普遍在 5–10 QPS，再高只会换来 429。
  '--source-concurrency': { kind: 'int', key: 'sourceConcurrency', min: 1, max: 8, example: '2' },
});

class CliError extends Error {
  constructor(message, code) {
    super(message);
    this.name = 'CliError';
    this.code = Number.isInteger(code) ? code : 1;
  }
}

/** 唯一失败出口：抛类型化错误，由入口统一打印 + 退出（保证错误信息可执行、不含裸栈） */
function fail(message, code) {
  throw new CliError(message, code);
}

// ---------------------------------------------------------------- 取值辅助

/** 取下一个 argv 作为本参数的值；缺失或撞上下一个 --flag 即报错（v3：会静默得到 undefined 再下游崩溃） */
function needVal(argv, i, name, example) {
  const v = argv[i + 1];
  if (v === undefined || v.startsWith('--')) {
    fail('[参数错误] ' + name + ' 缺少取值\n  示例: ' + name + ' ' + (example || '<值>'));
  }
  return v;
}

function outOfRange(name, v, o) {
  return '[参数错误] ' + name + ' 超出允许范围 [' + o.min + ', ' + o.max + ']，当前值 ' + JSON.stringify(v)
    + '\n  示例: ' + name + ' ' + (o.example || '<值>');
}

/** 统一数值解析 + 范围校验；字符串形态与数值范围双重把关，杜绝 '1.5' 混入整数参数 */
function numArg(raw, name, o) {
  const opt = o || {};
  const isInt = !!opt.int;
  const s = String(raw == null ? '' : raw).trim();
  const re = isInt ? /^[+-]?\d+$/ : /^[+-]?(\d+\.?\d*|\.\d+)$/;
  const kindText = isInt ? '整数' : '数字';
  if (!re.test(s)) {
    fail('[参数错误] ' + name + ' 需要' + kindText + '，当前值 ' + JSON.stringify(raw)
      + '\n  示例: ' + name + ' ' + (opt.example || '<值>'));
  }
  const v = isInt ? parseInt(s, 10) : parseFloat(s);
  if (!Number.isFinite(v)) {
    fail('[参数错误] ' + name + ' 需要' + kindText + '，当前值 ' + JSON.stringify(raw));
  }
  if (opt.min != null && v < opt.min) fail(outOfRange(name, v, opt));
  if (opt.max != null && v > opt.max) fail(outOfRange(name, v, opt));
  return v;
}

// ---------------------------------------------------------------- 归一与命名

/** 零宽字符（JS 的 \s 不含它们，必须单独剔除，否则会编进 URL 变成另一条检索式） */
const ZERO_WIDTH_RE = /[\u200B-\u200D\u180E]/g;

/**
 * 关键词归一：剔除零宽字符 → 任意空白（含 BOM \uFEFF、全角空格 \u3000、NBSP \u00A0、
 * CR \r）折叠为单个半角空格 → 去首尾。
 * 三条来源（--keywords / --keywords-file / plan.json）共用此函数，保证「同一个词」真正同一。
 */
function normKw(s) {
  return String(s == null ? '' : s)
    .replace(ZERO_WIDTH_RE, '')
    .replace(/\s+/g, ' ')
    .trim();
}

/** 文件名安全化（保留中英文字符；其余折叠为下划线；限长 60） */
function slug(s) {
  return String(s == null ? '' : s).replace(/[^\w一-龥-]+/g, '_').slice(0, 60) || 'kw';
}

/**
 * raw 文件名 = 保序序号 + slug（v4 新增）。
 * 序号前缀解决 v3 的磁盘层碰撞：三条不同检索式曾映射到同一个文件名而互相覆写。
 * 语义归属不靠文件名猜——以文件内的 `keyword` 字段与 summary.keywordIndex 为准。
 */
function kwIndexName(seq, kw) {
  return String(seq).padStart(2, '0') + '-' + slug(kw);
}

// ---------------------------------------------------------------- 文件通道

/** 读取「每行一个关键词」的文本文件（支持 `#` 注释行、CRLF、BOM、全角空格） */
function readKeywordsFile(file) {
  let raw;
  try {
    raw = fs.readFileSync(file, 'utf8');
  } catch (e) {
    const code = (e && e.code) || '';
    if (code === 'ENOENT') {
      fail('[参数错误] 关键词文件不存在: ' + file
        + '\n  请检查路径拼写，或改用 --keywords "词1" "词2"。');
    }
    if (code === 'EISDIR') {
      fail('[参数错误] --keywords-file 指向的是目录: ' + file
        + '\n  请指向一个「每行一个关键词」的文本文件。');
    }
    fail('[参数错误] 无法读取关键词文件: ' + file + '\n  原因: ' + ((e && (e.code || e.message)) || 'unknown'));
  }
  return String(raw).split(/\r?\n/).map(normKw).filter(s => s && !s.startsWith('#'));
}

/**
 * 关键词合并。顺序语义**有意保留 v3 行为**：命令行关键词在前、文件关键词在后，
 * 去重保留首次出现（即命令行优先）。v3 的问题不是顺序，而是这个顺序从未被告知——
 * v4 通过 `[INFO] 关键词来源` 回显把归属显式化（不改行为）。
 */
function mergeKeywords(cliKeywords, fileKeywords) {
  return [...new Set([...(cliKeywords || []), ...(fileKeywords || [])])];
}

/**
 * plan.json → 检索式溯源映射。
 * 解析失败**只告警不中断**（v3 既有正确设计，跳过 plan 仍能出结果），故返回 warning 而非抛错。
 */
function loadPlan(file) {
  let doc;
  try {
    doc = JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch (e) {
    return { refs: {}, mapped: 0, warning: '[WARN] plan.json 解析失败，检索式溯源信息将缺失: ' + String(e).slice(0, 120) };
  }
  const refs = {};
  for (const p of doc.plans || []) {
    if (!p || !p.query) continue;
    const tags = [];
    if (p.source) tags.push(p.source);
    if (p.sourceRefs && p.sourceRefs.length) tags.push(p.sourceRefs.join(' / '));
    refs[normKw(p.query)] = tags.join(' | ') || '—';
  }
  return { refs, mapped: Object.keys(refs).length, warning: null };
}

/** 输出目录准备：缺失即建；已存在但**不是目录**即报错（v3：裸 EEXIST 栈） */
function ensureDir(dir) {
  const d = String(dir == null ? '' : dir);
  if (!d) fail('[参数错误] 输出目录为空\n  请用 --out <目录> 指定。');
  if (fs.existsSync(d)) {
    let st;
    try {
      st = fs.statSync(d);
    } catch (e) {
      fail('[参数错误] 无法访问输出目录: ' + d + '\n  原因: ' + ((e && (e.code || e.message)) || 'unknown'));
    }
    if (!st.isDirectory()) {
      fail('[参数错误] --out 需要目录，但指向的是已存在的文件: ' + d
        + '\n  请改为一个目录路径（该文件请自行改名或删除；脚本不会删除你的文件）。');
    }
    return d;
  }
  try {
    fs.mkdirSync(d, { recursive: true });
  } catch (e) {
    fail('[参数错误] 无法创建输出目录: ' + d
      + '\n  原因: ' + ((e && (e.code || e.message)) || 'unknown')
      + '\n  请检查路径拼写与父目录写权限。');
  }
  return d;
}

// ---------------------------------------------------------------- 参数解析

/**
 * argv → opts（纯函数）。argv 需为 process.argv 形态（前两个元素是 node 与脚本路径）。
 * 抛 CliError 的情形：未知参数 / 取值缺失 / 数值非法或越界 / --keywords 无任何取值。
 */
function parseArgs(argv) {
  const argvList = Array.isArray(argv) ? argv : [];
  const a = {
    site: TOOL_DEFAULTS.site,
    limit: TOOL_DEFAULTS.limit,
    out: process.cwd(),
    headless: TOOL_DEFAULTS.headless,
    gateTimeoutSec: TOOL_DEFAULTS.gateTimeoutSec,
    keywords: [],
    keywordsFile: null,
    interval: TOOL_DEFAULTS.interval.slice(),
    enrich: TOOL_DEFAULTS.enrich,
    dedupe: TOOL_DEFAULTS.dedupe,
    fillMin: TOOL_DEFAULTS.fillMin,
    plan: TOOL_DEFAULTS.plan,
    evidence: TOOL_DEFAULTS.evidence,
    readyTimeoutSec: TOOL_DEFAULTS.readyTimeoutSec,
    keywordTimeoutSec: TOOL_DEFAULTS.keywordTimeoutSec,
    enrichConcurrency: TOOL_DEFAULTS.enrichConcurrency,
    fulltext: TOOL_DEFAULTS.fulltext,
    fulltextConcurrency: TOOL_DEFAULTS.fulltextConcurrency,
    fulltextBrowser: TOOL_DEFAULTS.fulltextBrowser,
    sources: TOOL_DEFAULTS.sources,
    sourceIds: null,
    sourceTimeoutSec: TOOL_DEFAULTS.sourceTimeoutSec,
    sourceConcurrency: TOOL_DEFAULTS.sourceConcurrency,
    mailto: TOOL_DEFAULTS.mailto,
    sourceRefs: {},
    notices: [],
    cliKeywords: [],
    fileKeywords: [],
  };
  const seen = new Set();

  for (let i = 2; i < argvList.length; i++) {
    const tok = argvList[i];
    const spec = ARG_SPEC[tok];
    if (!spec) {
      fail('未知参数: ' + tok + '\n  请检查拼写；支持的参数见 SKILL.md《输入》表。');
    }
    if (seen.has(tok)) a.notices.push('[提示] 参数 ' + tok + ' 重复出现（重复项已忽略）');
    seen.add(tok);

    if (spec.kind === 'bool') {
      a[spec.key] = true;
      continue;
    }

    if (spec.kind === 'varargs') {
      const start = i + 1;
      let j = start;
      while (j < argvList.length && !argvList[j].startsWith('--')) j++;
      if (j === start) {
        fail('[参数错误] --keywords 缺少取值\n  示例: --keywords "牛磺酸 猫" "protein digestibility dog"');
      }
      for (let k = start; k < j; k++) a.cliKeywords.push(normKw(argvList[k]));
      i = j - 1; // 让外层循环继续处理终止处的那个 --flag（若为未知参数则正常报错）
      continue;
    }

    const raw = needVal(argvList, i, tok, spec.example);
    i++; // 吃掉取值

    if (spec.kind === 'string') {
      a[spec.key] = raw;
      continue;
    }
    if (spec.kind === 'enum') {
      const v = String(raw).trim();
      if (Object.prototype.hasOwnProperty.call(UNIMPLEMENTED_SITES, v)) {
        fail('[参数错误] --site ' + v + ' 本版本尚未接通\n  ' + UNIMPLEMENTED_SITES[v]
          + '\n  当前可用站点: ' + spec.values.join(' / ')
          + '\n  请去掉 --site 参数（默认即 kuluer）；若确需该通道，请先接通抓取实现并把它加入白名单。');
      }
      if (!spec.values.includes(v)) {
        fail('[参数错误] --site 取值不识别: ' + JSON.stringify(raw)
          + '\n  当前可用站点: ' + spec.values.join(' / ')
          + '\n  示例: --site ' + spec.example);
      }
      a[spec.key] = v;
      continue;
    }
    if (spec.kind === 'int' || spec.kind === 'float') {
      a[spec.key] = numArg(raw, tok, { int: spec.kind === 'int', min: spec.min, max: spec.max, example: spec.example });
      continue;
    }
    if (spec.kind === 'pair') {
      const parts = String(raw).split(',');
      if (parts.length !== 2) {
        fail('[参数错误] ' + tok + ' 需要两个逗号分隔的非负整数，当前值 ' + JSON.stringify(raw)
          + '\n  示例: --interval 2500,4500');
      }
      const nums = parts.map(p => numArg(String(p).trim(), tok, { int: true, min: spec.min, max: spec.max, example: spec.example }));
      if (nums[0] > nums[1]) {
        fail('[参数错误] ' + tok + ' 应为「下限,上限」且下限 ≤ 上限，当前值 ' + JSON.stringify(raw)
          + '\n  示例: --interval 2500,4500');
      }
      a.interval = nums;
      continue;
    }
  }

  // v4.15（A-2）：--sources 的三条输入层判据。全部在解析阶段完成，理由同 --site：
  // 未注册的源 / 互相矛盾的参数组合，必须**在跑之前**报错，不能等到跑完才在产物里发现元数据说谎。
  if (a.sources !== null && a.sources !== undefined) {
    const raw = String(a.sources).trim();
    if (!raw) {
      fail('[参数错误] --sources 取值不能为空\n'
        + '  可用: ' + sourceIds().join(' / ') + '\n  预设: all（全部）/ http（不依赖浏览器的源）\n'
        + '  示例: --sources all   或   --sources all,-crossref');
    }
    // kuluer 是**浏览器站点源**，尚未迁入连接器层（A 批只落了 HTTP 源）。
    // 若放行，resolveSources 会报「未知源」——那句提示会让用户以为是自己拼错了，故给专属改法。
    if (raw.split(',').map(s => s.trim()).includes('kuluer')) {
      fail('[参数错误] --sources kuluer 本版本尚未接通\n'
        + '  现状：站点通道仍是**独立实现**（浏览器渲染 + 站点 AI 译文），未迁入多源连接器层。\n'
        + '  改法：① 要跑站点通道 ⇒ **去掉 --sources**（默认即 kuluer 浏览器通道）；\n'
        + '        ② 要跑多源 HTTP 通道 ⇒ --sources ' + sourceIds().join(',') + '（或 --sources all）。\n'
        + '  两者不能混在一次运行里：译文能力与计数语义都不同，混跑会让 summary 的元数据无法自洽。');
    }
    try {
      a.sourceIds = resolveSources(raw);
    } catch (e) {
      fail('[参数错误] --sources 取值无法解析: ' + JSON.stringify(raw) + '\n  ' + String(e.message || e));
    }
    // --site 只描述浏览器站点通道；与 --sources 同给必然是「意图自相矛盾」。
    if (seen.has('--site')) {
      fail('[参数错误] --sources 与 --site 互斥\n'
        + '  原因：--site 指定浏览器站点通道的数据源，--sources 指定 HTTP 多源通道；一次运行只有一条通道。\n'
        + '  改法：跑站点通道 ⇒ 去掉 --sources；跑多源 ⇒ 去掉 --site。');
    }
    if (seen.has('--headless')) a.notices.push('[提示] --sources 通道不启动浏览器，--headless 被忽略（不影响结果）');
  }
  if (a.mailto !== null && a.mailto !== undefined) {
    const m = String(a.mailto).trim();
    // 格式错的 mailto 会被 Crossref 当成无效联系标识（礼貌池不生效）且**不会**报错 —— 静默失效最难查。
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(m)) {
      fail('[参数错误] --mailto 需要邮箱格式，当前值 ' + JSON.stringify(a.mailto)
        + '\n  示例: --mailto you@example.com');
    }
    a.mailto = m;
  }

  // v4.10：--fulltext 的入口（pmcid）只能来自 Europe PMC 补全结果。
  // v4.15 起例外：多源通道的 Europe PMC 连接器**自身**返回 pmcid ⇒ 有 --sources 时不再强制 --enrich。
  // v4.15（B 批）文案更新：全文已是四级回退链（T1 XML / T2 正文 HTML / T3 Unpaywall / T4 出版商页），
  //   但**站点检索页本身不产出 DOI/PMCID**，所以站点通道仍必须靠 --enrich 拿到入口标识。
  //   不校验的话，用户只给 --fulltext 会得到「跑完了但什么都没抓」——静默空操作，最难排查。
  if (a.fulltext && !a.enrich && !a.sourceIds) {
    fail('[参数错误] --fulltext 在站点通道下需要 --enrich\n'
      + '  原因：全文四级回退链需要一个入口标识（PMCID 或 DOI），而站点检索页不提供；'
      + '这些标识只在 Europe PMC 补全（--enrich）时取到。\n'
      + '  改法一：同时加 --enrich（可再加 --dedupe / --evidence）。\n'
      + '  改法二：改用 --sources（多源连接器自带 doi/pmcid，且不启动浏览器）。');
  }

  a.keywords = a.cliKeywords.slice();
  return a;
}

/**
 * 完整输入解析：参数 → 关键词文件 → 合并 → plan 溯源。
 * io.log 用于回传 plan_loaded 事件（保持 stdout 事件流与 v3 一致）；不传则静默，便于单测。
 */
function resolveInputs(argv, io) {
  const log = (io && io.log) || (() => {});
  const opts = parseArgs(argv);

  if (opts.keywordsFile) opts.fileKeywords = readKeywordsFile(opts.keywordsFile);
  opts.keywords = mergeKeywords(opts.cliKeywords, opts.fileKeywords);

  // 疑似被空格拆分的检索式（v3 最隐蔽的输入缺陷：意图 1 条、实得 N 条，且无任何提示）
  if (opts.cliKeywords.length >= 2 && opts.cliKeywords.every(k => !k.includes(' '))) {
    opts.notices.push('[提示] --keywords 解析出 ' + opts.cliKeywords.length + ' 条独立关键词: '
      + JSON.stringify(opts.cliKeywords)
      + '\n  若本意是「一条含空格的检索式」，请用引号包成一条: --keywords "牛磺酸 猫"');
  }

  if (opts.plan) {
    const { refs, mapped, warning } = loadPlan(opts.plan);
    opts.sourceRefs = refs;
    if (warning) opts.notices.push(warning);
    else log('plan_loaded', { file: opts.plan, mapped });
  }
  return opts;
}

/** 关键词来源回显（一次性、人类可读，写到 stderr；供入口在 run_start 前调用） */
function describeKeywordSources(opts) {
  const parts = [];
  if (opts.cliKeywords.length) parts.push('命令行 ' + opts.cliKeywords.length);
  if (opts.fileKeywords.length) parts.push('文件 ' + opts.fileKeywords.length + '（' + path.basename(opts.keywordsFile || '') + '）');
  return '[INFO] 生效关键词 ' + opts.keywords.length + ' 条'
    + (parts.length ? '（来源: ' + parts.join(' + ') + '）' : '')
    + ': ' + opts.keywords.map(k => JSON.stringify(k)).join(' ');
}

/** 通道回显（stderr，一次性）。让「本次走的是哪条通道、几个源」在跑之前就可见 ——
 *  v4.1 的教训是：通道选择不可见时，产物里的元数据会静默说谎。 */
function describeSources(opts) {
  const o = opts || {};
  if (!Array.isArray(o.sourceIds) || !o.sourceIds.length) {
    return '[INFO] 检索通道: 站点 ' + (o.site || TOOL_DEFAULTS.site) + '（浏览器渲染 + 站点 AI 译文）';
  }
  return '[INFO] 检索通道: HTTP 多源（' + o.sourceIds.join(', ') + '）—— 不启动浏览器'
    + '；单源超时 ' + o.sourceTimeoutSec + 's / 并发 ' + o.sourceConcurrency
    + (o.mailto ? '；mailto ' + o.mailto : '');
}

module.exports = {
  TOOL_DEFAULTS,
  ARG_SPEC,
  SUPPORTED_SITES,
  UNIMPLEMENTED_SITES,
  CliError,
  fail,
  needVal,
  numArg,
  normKw,
  slug,
  kwIndexName,
  readKeywordsFile,
  mergeKeywords,
  loadPlan,
  ensureDir,
  parseArgs,
  describeSources,
  resolveInputs,
  describeKeywordSources,
};
