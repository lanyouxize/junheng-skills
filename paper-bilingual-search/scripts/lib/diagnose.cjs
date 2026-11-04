'use strict';
/**
 * lib/diagnose.cjs — 残差主题维度诊断（纯函数，零网络、零文件系统）
 *
 * 解决什么：`iterate.residual` 只答「**哪些**记录补词治不了」，答不了「**缺的是哪个维度**」。
 *   人拿到一份 20 条的残留清单仍要逐条通读。本模块把残留按「共现指纹」聚成维度候选：
 *     · `new-dimension` 与现有主题轴（词表 + 相邻词）**零 ≥2 字重叠** ⇒ 疑似缺一个主题维度
 *     · `axis-extend`   与现有轴有 ≥2 字重叠 ⇒ 同一轴上的写法差异，**用 --apply 补词即可**
 *   ⇒ 人只需判「这几簇是不是我要的新主题」，不必再从零读题名。
 *
 * ★ 铁律（本模块存在的全部意义）：**只提示，不自动建**。
 *   提案（`proposal.keywords`）永不回流进词表，`autoApply` 恒 false；采纳唯一通道仍是
 *   `rank-records --apply`。理由：补词与「新增主题维度」是**两种不同性质的决策**，
 *   前者只影响召回宽度，后者改变「什么算相关」—— 后者必须由人拍板。
 *   迭代层也**不得**把诊断结果当作下一轮补词输入（否则「新维度」会被悄悄升格成词表词）。
 *
 * ★ 为什么没有 covered / exclude 过滤（不是漏写，是不可达）：
 *   `relevance.rankAll` 的档位规则 = 「题名含主题词 ⇒ exact」（排除词另走 excluded 档），
 *   而本模块第一步就跳过 `exact` 与 `excluded` ⇒ 「残差题名含词表词」「残差含排除词」在语义上不存在。
 *   该前提由单测「不变量守卫」钉住：rankAll 改档位规则时先红的应是那条守卫，而不是诊断结论。
 *   同理也不写 `extendsTopic` 分支 —— 候选若包含词表词，其原文必然已被判 exact。
 *
 * ★ 已知边界（如实登记）：
 *   ① n-gram 分不清词边界 ⇒ 簇术语里会出现 `胱炎`／`猫膀` 这类接缝残渣（`isStopResidue` 只挡
 *      全通用字残渣，挡不住含实字的接缝），故 `confidence` 只表示**支持数**强弱，
 *      不表示「标签是不是一个好词」——标签一律须人核对。
 *   ② 一条记录只归**一个**簇（互斥分配）⇒ `support` 之和 ≤ 残差数，数字可对账；
 *      代价是多重身份的记录只计入最先认领它的维度。
 *   ③ 支持数为 1 的簇一律剪除（个案不是维度），被剪记录的原文仍逐条列出，不静默丢弃。
 *   ④ **簇内至少要 2 个共享指纹**才算「共同维度」。只有 1 个共享词时，簇往往由**泛学术词**
 *      拼成（一手证据：2026-10-18 猫毛球 10 条全 off，`生物` = 合成生物学／生物安全／生物风险，
 *      `肠道` = 肠道寄生虫／肠道菌群 —— 拼法各异但共享同一个泛词）⇒ 判为 `no-cohesion` 剪除。
 *      这不是「更严格」，而是把「什么算同一主题」从「一个词」抬到「两个词」。
 *   ⑤ 剪枝**不回流**：被剪记录不重新分配给别的种子（宁可少报，不可引入顺序依赖）。
 *   ⑥ **物种粘连**（`Canine chronic` / `猫膀胱`）在极大剪枝**之前**剔除：极端情况下极大剪枝会把
 *      剥掉物种词后的真主题词（`膀胱炎`）吸收进含物种前缀的长串（`猫膀胱炎`）里，于是簇术语变成
 *      「物种字 + 半个词」；该术语随后还会被写进建议检索式 ⇒ 与式自带的物种块自相矛盾。
 *      判据 = 「剥掉物种词素后剩余串已入册且 df 不逊」，故不会误剥 `catheter`（`heter` 不入册）。
 *
 * 依赖：`suggest`（extractCandidates / isStopCandidate / lcsLen）与 `relevance`（compactKey）。
 */

const REL = require('./relevance.cjs');
const SG = require('./suggest.cjs');

const VERSION = 'residual-diagnose/v3';

const DEFAULT_MIN_SUPPORT = 2;   // 至少 2 条残差共享才算「维度」（个案不是维度）
const DEFAULT_MAX_CLUSTERS = 5;
const DEFAULT_MAX_TERMS = 5;     // 每簇最多列几个术语
const SAMPLE_TITLES = 5;
const MIN_N = 2;                 // 中文 n-gram 下限（与 suggest 的 CJK_MIN_N 一致）
const MAX_N = 4;
const OVERLAP_MIN = 2;           // 与现有轴的最长公共子串 ≥ 该值 ⇒ 判为同一轴
const PROPOSAL_TOP = 3;

const VERDICT = Object.freeze({
  NO_RESIDUAL: 'no-residual',
  NO_SHARED_TERMS: 'no-shared-terms',
  AXIS_ONLY: 'axis-only',
  NEW_DIMENSION: 'new-dimension',
});

function clampInt(v, dflt, lo, hi) {
  const n = Number(v);
  if (!Number.isInteger(n)) return dflt;
  return Math.min(hi, Math.max(lo, n));
}

function clip(s, n) {
  const t = String(s == null ? '' : s).replace(/\s+/g, ' ').trim();
  return t.length > n ? t.slice(0, n) + '…' : t;
}

/** 记录显示名（字段名不可信：站点的 titleEn 里也可能装中文，与 relevance 同规则）。 */
function titleOf(rec) {
  const r = rec || {};
  return r.titleZh || r.titleEn || '';
}

/**
 * 诊断残差记录的「缺失维度」。
 * @param {Array}  rows  `rankAll().ranked`（`{rec, rel:{level, excluded}}`）
 * @param {Object} topic `buildTopic()` 产物（terms / near / exclude）
 * @param {Object} [opts] `minSupport（默认 2，钳 2–5）| maxClusters（默认 5，钳 1–10）| maxTerms`
 * @returns {Object} 见文件末尾 `makeResult` 形状；**恒 `autoApply: false`**
 */
function diagnoseResidual(rows, topic, opts) {
  const o = opts || {};
  const minSupport = clampInt(o.minSupport, DEFAULT_MIN_SUPPORT, 2, 5);
  const maxClusters = clampInt(o.maxClusters, DEFAULT_MAX_CLUSTERS, 1, 10);
  const maxTerms = clampInt(o.maxTerms, DEFAULT_MAX_TERMS, 2, 10);
  const t = topic || {};
  const topicKeys = (t.terms || []).map(REL.compactKey).filter(Boolean);
  const nearKeys = (t.near || []).map(REL.compactKey).filter(Boolean);
  const axisKeys = topicKeys.concat(nearKeys);

  // ---- ① 选入残差：非 exact 且非 excluded（排除词记录已由用户显式否决，不得驱动新维度提案）
  const residualRows = [];
  let excludedRecords = 0;
  for (const r of rows || []) {
    if (!r || !r.rel) continue;
    if (r.rel.level === 'exact') continue;
    if (r.rel.excluded) { excludedRecords++; continue; }
    residualRows.push(r);
  }
  const byLevel = { near: 0, off: 0 };
  residualRows.forEach(r => { byLevel[r.rel.level] = (byLevel[r.rel.level] || 0) + 1; });

  // ---- ② 指纹：残差语料内 df ≥ minSupport 的题名词（同一条记录内同 key 只计一次）
  const dropped = { excludedRecords, stopword: 0, belowSupport: 0, speciesGlue: 0, subsumed: 0, starved: 0 };
  const stats = new Map();
  residualRows.forEach((r, i) => {
    const rec = r.rec || {};
    const raw = [rec.titleEn, rec.titleZh].filter(Boolean).join(' ');
    if (!raw.trim()) return;
    const seen = new Set();
    for (const c of SG.extractCandidates(raw, MAX_N)) {
      const k = c.key;
      if (!k || k.length < MIN_N || seen.has(k)) continue;
      seen.add(k);
      if (SG.isStopCandidate(c)) { dropped.stopword++; continue; }
      let e = stats.get(k);
      if (!e) {
        // term 保留**原文形态**（繁体/大小写/连字符）：归一只用于比较，输出不乱改用户文本
        e = { key: k, term: c.text, kind: c.kind, df: 0, docs: [], axis: false };
        stats.set(k, e);
      }
      e.df++;
      e.docs.push(i);
    }
  });

  const hit = [];
  for (const e of stats.values()) {
    if (e.df < minSupport) { dropped.belowSupport++; continue; }
    hit.push(e);
  }

  // ---- ②a 物种粘连剪枝（★ 必须在极大剪枝**之前**，顺序不可换）
  //   极大剪枝的方向是「短串被长串吸收」⇒ `膀胱炎` 会因被 `猫膀胱炎` 包含而消失，
  //   而我们要留的恰恰是**剥掉物种词后的短串**。故先剥、后吸收。
  //   两条判据（与极大剪枝同构，只把「包含」换成「剥物种词素后相等/被包含」）：
  //     ① 剩余串本身已入册且 df 不逊（`猫膀胱炎` → `膀胱炎`、`Canine chronic` → `chronic`）
  //     ② 剩余串是另一入册指纹的**真子串**（`猫膳` → `膳` ⊂ `膳食纤维`）—— 否则「剪掉 `猫膳食纤维`」
  //        之后 `猫膳` 会立刻冒出来占位（n-gram 的「按下去又弹起来」，与 `物犬` 同一现象）。
  //   因判据依赖「剩余串确实已入册/被入册串包含」，`catheter` → `heter` 不会被误剪。
  const hitByKey = new Map(hit.map(e => [e.key, e]));
  const glue = new Set();
  for (const e of hit) {
    for (const rest of SG.stripSpeciesAffixes(e.key)) {
      if (!rest || rest === e.key) continue;
      const exact = hitByKey.get(rest);
      if (exact && exact !== e && exact.df >= e.df) { glue.add(e.key); break; }
      const halfWrapped = hit.some(o => o !== e && o.key.length > rest.length
        && o.key.includes(rest) && o.df >= e.df);
      if (halfWrapped) { glue.add(e.key); break; }
    }
  }
  const keptHit = hit.filter(e => {
    if (glue.has(e.key)) { dropped.speciesGlue++; return false; }
    return true;
  });

  // ---- ②b 极大剪枝（与 suggest 同规则）：被更长的指纹包含且 df 不逊者 ⇒ 只是它的一段。
  //   ★ 这一步同时解决「物种前缀粘连」（`猫膳` ⊂ `猫膳食纤维`）—— 若不做，簇标签会退化成
  //     「物种字 + 半个词」，且因与现有轴零重叠而被误判成**新维度**（实测踩过：同轴夹具被判 new-dimension）。
  //   只对**已入册的长串**比较 ⇒ 天然取「极大串」，不误伤同长度的真词。
  keptHit.sort((a, b) => (b.key.length - a.key.length) || (a.key < b.key ? -1 : a.key > b.key ? 1 : 0));
  const fps = [];
  for (const e of keptHit) {
    if (fps.some(b => b.key.includes(e.key) && b.df >= e.df)) { dropped.subsumed++; continue; }
    e.axis = axisKeys.some(x => SG.lcsLen(e.key, x) >= OVERLAP_MIN);
    fps.push(e);
  }

  // ---- ③ 互斥分配：**novel 优先**（关键）
  //   若按 df 全局贪心，轴内高频词会先占满记录，把同时含新维度词的记录一并吞掉 ⇒ 新维度整簇消失。
  //   故排序键第一维是「是否 novel」，第二维才是 df。代价：同轴大簇会被切碎（宁可切碎，不可漏判）。
  fps.sort((a, b) => ((a.axis ? 1 : 0) - (b.axis ? 1 : 0))
    || (b.df - a.df) || (b.key.length - a.key.length) || (a.key < b.key ? -1 : a.key > b.key ? 1 : 0));
  const assigned = new Array(residualRows.length).fill(-1);
  const rawClusters = [];
  for (const e of fps) {
    const members = e.docs.filter(i => assigned[i] < 0);
    if (!members.length) { dropped.starved++; continue; }
    const cid = rawClusters.length;
    members.forEach(i => { assigned[i] = cid; });
    rawClusters.push({ seed: e, docs: members });
  }

  // ---- ④ 成簇 + 两道剪枝（**顺序不可换**：先算簇内术语，才能判「有没有第二个共享指纹」）
  //   ★ 剪枝不回流：被剪记录不会重新分配给别的种子（避免级联重分配带来的顺序依赖）。
  const pruned = new Map();     // 记录下标 → 剪枝原因
  const clusters = [];
  for (const c of rawClusters) {
    const set = new Set(c.docs);
    const inner = [];
    for (const e of fps) {
      if (e === c.seed) continue;
      let df = 0;
      for (const i of e.docs) if (set.has(i)) df++;
      if (df >= 2) inner.push({ term: e.term, key: e.key, df, axis: e.axis });
    }
    inner.sort((a, b) => (b.df - a.df) || (b.key.length - a.key.length)
      || (a.key < b.key ? -1 : a.key > b.key ? 1 : 0));

    // 剪枝一：个案不是维度
    if (c.docs.length < minSupport) {
      c.docs.forEach(i => { assigned[i] = -1; pruned.set(i, 'spun-off'); });
      continue;
    }
    // 剪枝二（★ 关键）：**只有 1 个共享词的簇不算「共同维度」**。
    //   一手证据（2026-10-18 真实回放，猫毛球 10 条全 off）：`生物`（合成生物学／生物安全／生物风险）
    //   与 `肠道`（肠道寄生虫／肠道菌群）各聚出 2~3 条，但簇内**再无第二个共享词** ——
    //   这类「泛学术词 + 互不相干的记录」会被误读成「缺一个新维度」，实为检索式召回过宽。
    //   判据：簇内须另有 ≥1 个指纹同时出现在 ≥2 条记录里 ⇒ 至少两个共享词才算同一主题。
    //   ★ 只对**新维度**簇生效：该闸防的是「把泛词当新维度」，而同轴簇（seed.axis）不产新维度提案、
    //     其术语本就与现有轴重叠 ⇒ 无此风险。若一律套用，单共享词语料（三条题名只共用 `膳食纤维`）
    //     会从 axis-extend 退化成「归纳不出共同维度」的误报（2026-10-18 物种剪枝后实测暴露）。
    if (!inner.length && !c.seed.axis) {
      c.docs.forEach(i => { assigned[i] = -1; pruned.set(i, 'no-cohesion'); });
      continue;
    }
    clusters.push({
      kind: c.seed.axis ? 'axis-extend' : 'new-dimension',
      label: c.seed.term,
      key: c.seed.key,
      confidence: c.docs.length >= 3 ? 'strong' : 'weak',
      support: c.docs.length,
      terms: [{ term: c.seed.term, key: c.seed.key, df: c.docs.length, axis: c.seed.axis }]
        .concat(inner.slice(0, maxTerms - 1)),
      idxs: c.docs.map(i => (residualRows[i].rec || {}).idx == null ? null : residualRows[i].rec.idx),
      titles: c.docs.slice(0, SAMPLE_TITLES).map(i => toRow(residualRows[i])),
    });
  }

  // 排序：新维度优先 → 支持数降 → 标签升（末项保证同分不打乱，便于 diff）
  clusters.sort((a, b) => ((a.kind === 'new-dimension' ? 0 : 1) - (b.kind === 'new-dimension' ? 0 : 1))
    || (b.support - a.support) || (a.key < b.key ? -1 : a.key > b.key ? 1 : 0));
  const shown = clusters.slice(0, maxClusters);

  // ---- ⑥ 未归类：逐条列出（不静默丢弃；原因可审计）
  const unclustered = [];
  residualRows.forEach((r, i) => {
    if (assigned[i] >= 0) return;
    unclustered.push(Object.assign(toRow(r), { reason: pruned.get(i) || 'no-shared-term' }));
  });

  const residualTotal = residualRows.length;
  let verdict;
  if (!residualTotal) verdict = VERDICT.NO_RESIDUAL;
  else if (!shown.length) verdict = VERDICT.NO_SHARED_TERMS;
  else if (shown.some(c => c.kind === 'new-dimension')) verdict = VERDICT.NEW_DIMENSION;
  else verdict = VERDICT.AXIS_ONLY;

  // ---- ⑦ 提案：**只从新维度簇取词**，且仅作提示（同轴词交给 --apply 补词通道）
  const keywords = [];
  const detail = [];
  for (const c of shown) {
    if (c.kind !== 'new-dimension') continue;
    for (const x of c.terms) {
      if (keywords.indexOf(x.term) >= 0 || keywords.length >= PROPOSAL_TOP) break;
      keywords.push(x.term);
      detail.push({ term: x.term, support: c.support, confidence: c.confidence });
    }
    if (keywords.length >= PROPOSAL_TOP) break;
  }

  return {
    version: VERSION,
    stationRequests: 0,           // 声明式：只读已排序结果，零站点请求
    autoApply: false,             // ★ 恒 false：提案不得自动并入词表
    minSupport, maxClusters,
    residual: { total: residualTotal, byLevel },
    dropped: Object.assign({}, dropped),
    fingerprints: fps.length,
    verdict,
    verdictNote: noteOf(verdict, residualTotal, shown),
    // ★ 簇总数 vs 上报数：`shown` 被 `maxClusters` 截断时，被截掉的簇**既不进 clusters 也不进
    //   unclustered**（它们的记录已被 assigned）⇒ 外部无法区分「簇消失」与「被上限挤出」。
    //   收敛追踪必须靠这两个数才能不误报（见 lib/convergence.cjs 的 `capped` 态）。
    clustersTotal: clusters.length,
    droppedByCap: clusters.length - shown.length,
    clusters: shown.map(c => Object.assign({}, c, {
      terms: c.terms.map(x => Object.assign({}, x)),
      idxs: c.idxs.slice(),
      titles: c.titles.map(x => Object.assign({}, x)),
    })),
    unclustered,
    proposal: {
      autoApply: false,
      keywords,
      detail,
      note: '仅提示：新维度提案不会自动并入词表；确认后请用 --apply 显式补入（或调整 --keywords 重跑检索）。',
    },
  };
}

function toRow(r) {
  const rec = (r && r.rec) || {};
  return {
    idx: rec.idx == null ? null : rec.idx,
    title: titleOf(rec),
    year: rec.year == null ? null : rec.year,
    level: (r && r.rel && r.rel.level) || 'off',
  };
}

function noteOf(verdict, n, clusters) {
  if (verdict === VERDICT.NO_RESIDUAL) {
    return '残差为 0 —— 无需新增维度（当前词表已覆盖语料中的相关主题）。';
  }
  if (verdict === VERDICT.NO_SHARED_TERMS) {
    return '残差 ' + n + ' 条之间没有足够共现的共享词 ⇒ 归纳不出共同维度（多为个案或跑题文献），须逐条人工判读。';
  }
  const nd = clusters.filter(c => c.kind === 'new-dimension');
  const ax = clusters.length - nd.length;
  if (verdict === VERDICT.AXIS_ONLY) {
    return '残差 ' + n + ' 条均可归到现有主题轴/相邻轴（' + ax + ' 簇）⇒ 不必新增维度，用 --apply 补词即可。';
  }
  return '残差 ' + n + ' 条聚成 ' + clusters.length + ' 簇：新维度 ' + nd.length + ' 簇（与现有轴零重叠）'
    + '、同轴 ' + ax + ' 簇。簇标签由 n-gram 推断，**词边界须人工核对**。';
}

module.exports = {
  VERSION, DEFAULT_MIN_SUPPORT, DEFAULT_MAX_CLUSTERS, DEFAULT_MAX_TERMS,
  SAMPLE_TITLES, MIN_N, MAX_N, OVERLAP_MIN, PROPOSAL_TOP, VERDICT,
  diagnoseResidual, clip,
};
