'use strict';
/**
 * lib/probe.cjs — 计数探针的「三态」判定（纯函数：零 IO、零网络、零 DOM）
 *
 * 背景（2026-10-16 一手实测，10 条检索式探针）：
 *   4 条 `reportedTotal` 为 null、单条耗时 30–66s，而 `summary.warnings` 为空、exit 0
 *   ⇒「采集失败」与「真的 0 命中」在产物里**无法区分** ⇒ 可能**误排除一条本来有效的检索式**
 *   （与五条诚实性红线中「不得静默降级」同源）。次轮同式重跑得 851 条 ⇒ 确认该现象为**间歇性**。
 *
 * 关键事实（决定了正确修法不是「null 就报警」，而是先把 null 拆成两义）：
 *   站点真 0 条时给的是「约 0 条结果」（正则能取到整数 0）或「找不到 … 不常见字词」文案
 *   ⇒ **null 从来不等于 0，只等于「没读到」**。故设三态，禁止再用 null 兼表两义。
 *
 * 三态（穷举互斥）：
 *   counted        读到整数（含 0 —— 0 是站点**明确说** 0 条，属有效证据）
 *   zero_confirmed 未读到整数，但页面给出明确「无结果」信号 ⇒ 真 0，可用于排除检索式
 *   collect_failed 两者皆无 ⇒ 采集失败（疑似未达就绪/渲染延迟）⇒ **不得据此排除检索式**
 *
 * 边界（如实登记）：
 *   - `noResultsSignal` 由调用方在**页面文本层**判定，本模块不看 DOM、不重算正则；
 *   - 站点改版导致文案变化时，`zero_confirmed` 会退化回 `collect_failed` ——
 *     失败方向是「多报一次采集失败」，而非「把采集失败当成 0」，属可接受方向（宁可误报，不可误排除）；
 *   - 本模块只判「读数是否可信」，不判「检索式是否有效」——后者永远由人工裁定。
 */

const COUNT_STATE = {
  COUNTED: 'counted',
  ZERO_CONFIRMED: 'zero_confirmed',
  COLLECT_FAILED: 'collect_failed',
};

// 供渲染层复用的中文标签（避免 PRISMA 与 CLI 两处文案各自漂移）
const COUNT_LABEL = {
  counted: '已读得计数',
  zero_confirmed: '0 条（站点已确认）',
  collect_failed: '采集失败',
};

/** 把「一条 run 的计数观测量」归一为三态之一。
 * @param {object|null} d  { reportedTotal, noResultsSignal }
 * @returns {{state:string, count:number|null}}
 */
function classifyCount(d) {
  const raw = d ? d.reportedTotal : null;
  let n = NaN;
  if (typeof raw === 'number') n = raw;
  else if (typeof raw === 'string' && raw.trim() !== '') n = Number(raw);
  if (Number.isFinite(n)) return { state: COUNT_STATE.COUNTED, count: n };
  if (d && d.noResultsSignal === true) return { state: COUNT_STATE.ZERO_CONFIRMED, count: 0 };
  return { state: COUNT_STATE.COLLECT_FAILED, count: null };
}

/**
 * 汇总一批 run 的探针结论。
 * @param {Array} rows [{ keyword, reportedTotal, noResultsSignal, retrieved, durationMs }]
 * @param {object} opts { limit }  —— limit === 0 即计数探针模式
 */
function probeVerdict(rows, opts) {
  const o = opts || {};
  const list = (Array.isArray(rows) ? rows : []).filter(Boolean);
  const states = list.map(r => {
    const c = classifyCount(r);
    return {
      keyword: r.keyword,
      state: c.state,
      count: c.count,
      retrieved: Number(r.retrieved) || 0,
      durationMs: Number(r.durationMs) || 0,
    };
  });
  const pick = s => states.filter(x => x.state === s).map(x => x.keyword);
  const counted = pick(COUNT_STATE.COUNTED);
  const zeroConfirmed = pick(COUNT_STATE.ZERO_CONFIRMED);
  const failed = pick(COUNT_STATE.COLLECT_FAILED);
  const allRecordsZero = states.length > 0 && states.every(x => x.retrieved === 0);
  // 「站点给出了任何读数证据」= 读得计数 或 站点明确说无结果。
  // 旧判据是 `reportedTotal != null`，会把「站点明确说 0 条」也算成「站点没反应」⇒ 误报 exit 5。
  const anyEvidence = counted.length + zeroConfirmed.length > 0;
  return {
    probe: o.limit === 0,
    total: states.length,
    states,
    counted,
    zeroConfirmed,
    failed,
    allRecordsZero,
    anyEvidence,
    allFailed: states.length > 0 && failed.length === states.length,
    // 站点侧不可用的唯一判据：一条都没抓到，且站点**一个读数都没给**（含明确无结果）
    siteDegraded: allRecordsZero && !anyEvidence,
  };
}

/** 探针模式下的逐条告警文案（每条都点名关键词，且写明「不得据此排除」）。
 * @returns {string[]} 非探针模式恒返回空数组（该模式下计数缺失由 PRISMA 的 known 标记承担）
 */
function probeWarnings(v, opts) {
  const o = opts || {};
  const out = [];
  if (!v || !v.probe) return out;
  const rt = o.readyTimeoutSec == null ? null : Number(o.readyTimeoutSec);
  for (const kw of v.failed) {
    const st = v.states.find(x => x.keyword === kw);
    const secs = st && st.durationMs ? Math.round(st.durationMs / 1000) : null;
    out.push(kw + ': 计数探针未读到「约 N 条结果」，页面也没有「无结果」提示 ⇒ 判为采集失败'
      + '（不是 0 命中），不得据此排除该检索式；建议重跑该条'
      + (rt ? '或加大 --ready-timeout（当前 ' + rt + 's）' : '')
      + (secs ? '；本条耗时 ' + secs + 's' : '') + '。');
  }
  return out;
}

/**
 * 把探针结论**写进 summary**（`probe` 字段 + `warnings`），返回 verdict。
 * 主脚本只做这一次调用 ⇒ 接线本身可被单测用真实对象验证，不必靠「正则猜源码」证明它接上了。
 * @param {object} summary 主脚本的 summary（会被就地追加 probe / warnings）
 * @param {Array}  groups  [{ keyword, records, aborted, diagnostics }]
 * @param {object} opts    { limit, readyTimeoutSec }
 */
function attachProbe(summary, groups, opts) {
  const o = opts || {};
  const rows = (Array.isArray(groups) ? groups : []).map(g => {
    const d = g.diagnostics || {};
    return {
      keyword: g.keyword,
      reportedTotal: d.reportedTotal === undefined ? g.reportedTotal : d.reportedTotal,
      noResultsSignal: d.noResultsSignal === undefined ? g.noResultsSignal : d.noResultsSignal,
      retrieved: Array.isArray(g.records) ? g.records.length : (Number(g.retrieved) || 0),
      durationMs: d.durationMs === undefined ? g.durationMs : d.durationMs,
    };
  });
  const v = probeVerdict(rows, { limit: o.limit });
  summary.probe = {
    countOnlyProbe: v.probe,
    total: v.total,
    counted: v.counted,
    zeroConfirmed: v.zeroConfirmed,
    failed: v.failed,
    allFailed: v.allFailed,
    siteDegraded: v.siteDegraded,
  };
  probeWarnings(v, { readyTimeoutSec: o.readyTimeoutSec }).forEach(w => summary.warnings.push(w));
  return v;
}

/** 一行探针汇总（供 CLI 日志与 summary 使用）；非探针模式返回 null。 */
function probeSummaryLine(v, opts) {
  if (!v || !v.probe) return null;
  // v4.15：多源通道里没有「站点」，同一条文案换主语即可，不必另立一套格式化（避免两处漂移）
  const who = (opts && opts.subject) || '站点';
  let s = '计数探针：' + v.total + ' 条 —— 读得计数 ' + v.counted.length
    + ' / ' + who + '确认 0 条 ' + v.zeroConfirmed.length + ' / 采集失败 ' + v.failed.length;
  if (v.failed.length) s += '（' + v.failed.join('、') + '，不得据此排除）';
  return s;
}

module.exports = { COUNT_STATE, COUNT_LABEL, classifyCount, probeVerdict, probeWarnings, probeSummaryLine, attachProbe };
