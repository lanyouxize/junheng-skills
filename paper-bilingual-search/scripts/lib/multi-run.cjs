/* eslint-disable */
/**
 * lib/multi-run.cjs — 多源结果 → CLI 记录组 的聚合层（纯函数：零 IO、零网络）
 *
 * 为什么要单独一层（2026-10-26，A-2 CLI 接线）：
 *   调度器 `runSources()` 返回的是「每个源的读数 + 合并后的记录」，而主脚本的下游
 *   （qc / enrich / fulltext / dedupe / evidence / raw 落盘 / PRISMA）全部按
 *   `{ keyword, records, aborted, diagnostics }` 这一种形状消费。若把这层映射写在主脚本里，
 *   它就变成「只能在真跑检索时才可能被验证」的代码 —— 而它恰恰是**最容易出错**的一段：
 *   哪些源的计数能相加、0 条到底算「真 0」还是「采集失败」，全都是判据问题，不是接线问题。
 *
 * 因此本层把三条判据集中在一处，并保证**可离线直测**：
 *   ① 计数语义分流：只有 `countSemantics === 'exact'` 的源参与计数相加。
 *      Crossref 的 `total-results` 是**全库软匹配规模**（实测 775136 / 358659），
 *      一旦被加进来，PRISMA 的「数据库自报命中」会凭空放大四个数量级。
 *   ② 0 条的三种可能必须分开：源明确说 0（zero_confirmed）/ 源没说话（collect_failed）/
 *      本次根本没有能计数的源（not_applicable）。混为一谈就会出现「假故障」或「假 0 命中」。
 *   ③ 全部源不可用（all_sources_failed）才算通道级故障；只要有一个源给了读数，
 *      就不是通道故障 —— 这正是多源相对单源的核心收益，不能因为一个源挂了就整批失败。
 */
'use strict';

const { COUNT_STATE } = require('./probe.cjs');
const { COUNT_NA } = require('./scheduler.cjs');

/** 计数探针模式下不保留任何记录（与 --limit 0 「只读计数不抓条目」的语义一致） */
function emptyRecords() { return []; }

/**
 * 把调度器的返回整理成主脚本的「单关键词结果组」。
 * @param {object} p
 *   res      runSources() 的返回值
 *   keyword  检索式
 *   limit    每条上限（0 = 计数探针）
 * @returns {{records:Array, aborted:string|null, diagnostics:object, multi:object}}
 */
function buildKeywordResult(p) {
  const o = p || {};
  const res = o.res || {};
  const keyword = o.keyword;
  const limit = Number(o.limit) || 0;
  const perSource = Array.isArray(res.perSource) ? res.perSource : [];

  // idx 必须按「本关键词内 1 起算」**重新连续编号**：rank-records / 报告按 idx 定位条目。
  // ★ 实测踩到（2026-10-26 e2e）：连接器的 idx 是**源内排名**，两源各从 1 开始 ⇒ 合并后
  //   出现 [1,2,3,4,5,1,2,3,4,5] 的重复序号，下游按 idx 定位会有歧义。
  //   源内排名不丢，它在 provenance.rank 里（连接器已写），两者语义不同不可互相顶替。
  const src = Array.isArray(res.records) ? res.records : [];
  const records = limit === 0 ? emptyRecords() : src.map((r, i) => Object.assign({}, r, {
    idx: i + 1,
    keyword: r.keyword || keyword,
  }));

  const exact = perSource.filter(s => s.countSemantics === 'exact');
  const aliveExact = exact.filter(s => s.ok);
  const spoken = aliveExact.filter(s => s.countState === COUNT_STATE.COUNTED || s.countState === COUNT_STATE.ZERO_CONFIRMED);

  let countState;
  let reportedTotal;
  if (spoken.length) {
    // 只有读到正式读数的源才相加；逐源展开写进 diagnostics，便于第三方复算
    const nums = spoken.map(s => Number(s.reportedTotal));
    const allNumeric = nums.every(n => Number.isFinite(n));
    reportedTotal = allNumeric ? nums.reduce((a, b) => a + b, 0) : null;
    countState = reportedTotal === 0 ? COUNT_STATE.ZERO_CONFIRMED : COUNT_STATE.COUNTED;
  } else if (exact.length) {
    // 有能计数的源，但一个读数都没读到 ⇒ 采集失败（不是 0）
    reportedTotal = null;
    countState = COUNT_STATE.COLLECT_FAILED;
  } else {
    // 本次一个可计数的源都没有（只有 bag/none 型）⇒ 计数不适用，**不是**故障
    reportedTotal = null;
    countState = COUNT_NA;
  }

  const okIds = perSource.filter(s => s.ok).map(s => s.id);
  const aborted = res.allFailed ? 'all_sources_failed' : null;

  const diagnostics = {
    keyword,
    channel: 'http',
    url: null,
    pages: null,
    strategies: [{ strategy: okIds.length ? 'http:' + okIds.join('+') : 'http:none_available' }],
    aborted,
    reportedTotal,
    noResultsSignal: countState === COUNT_STATE.ZERO_CONFIRMED,
    countState,
    // 逐源明细同时进 diagnostics：PRISMA 的「各源读数」与 summary 都从这里取，避免两处各算一遍。
    // ★ none 型源的 reportedTotal **在这里强制置 null**：连接器已返回 null，这里是第二道闸。
    //   理由：一旦某个连接器把「全库软匹配规模」写进 reportedTotal，下游所有渲染都会显示它，
    //   而它旁边写着「不计数」—— 自相矛盾的读数比没有读数更糟（实测 Crossref 会给 775136）。
    sources: perSource.map(s => ({
      id: s.id, label: s.label, kind: s.kind, ok: s.ok,
      count: s.count,
      reportedTotal: s.countSemantics === 'exact' ? (s.reportedTotal == null ? null : s.reportedTotal) : null,
      countState: s.countState,
      countSemantics: s.countSemantics, queryDialect: s.queryDialect,
      aborted: s.aborted || null, queryUsed: s.queryUsed || null,
    })),
    sourceFailures: (res.failures || []).slice(),
    sourceDedupe: res.dedupe || null,
    startedAt: null,
    endedAt: null,
    durationMs: res.durationMs == null ? null : res.durationMs,
  };

  return { records, aborted, diagnostics, multi: res };
}

/**
 * 多源版探针判定。返回形状与 `probe.probeVerdict` 对齐，使主脚本的后续分支
 * （verdict.failed / verdict.probe / verdict.siteDegraded）**不需要**改一行。
 *
 * 与单源版的两处差异（都是判据级的，必须写清）：
 *   · `not_applicable` 既不算「读到」也不算「失败」—— 它表示「本次没有能计数的源」，
 *     照搬三态会把它判成采集失败（假故障），进而污染 siteDegraded。
 *   · `siteDegraded` 要求「一条都没抓到 **且** 一条读数都没有」；只要有一个源说了话就不是
 *     通道故障（单源版的判据同样如此，多源下这条更容易成立）。
 * @param {Array} groups [{ keyword, records, aborted, diagnostics }]
 * @param {object} [opts] { limit }
 */
function multiProbeVerdict(groups, opts) {
  const o = opts || {};
  const list = (Array.isArray(groups) ? groups : []).filter(Boolean);
  const states = list.map(g => {
    const d = g.diagnostics || {};
    return {
      keyword: g.keyword,
      state: d.countState,
      count: d.countState === COUNT_STATE.COUNTED || d.countState === COUNT_STATE.ZERO_CONFIRMED
        ? Number(d.reportedTotal) : null,
      retrieved: Array.isArray(g.records) ? g.records.length : 0,
      durationMs: Number(d.durationMs) || 0,
      aborted: g.aborted || null,
    };
  });
  const pick = s => states.filter(x => x.state === s).map(x => x.keyword);
  const counted = pick(COUNT_STATE.COUNTED);
  const zeroConfirmed = pick(COUNT_STATE.ZERO_CONFIRMED);
  const failed = pick(COUNT_STATE.COLLECT_FAILED);
  const na = pick(COUNT_NA);
  const allRecordsZero = states.length > 0 && states.every(x => x.retrieved === 0);
  const anyEvidence = counted.length + zeroConfirmed.length > 0;
  return {
    probe: o.limit === 0,
    total: states.length,
    states,
    counted,
    zeroConfirmed,
    failed,
    notApplicable: na,
    allRecordsZero,
    anyEvidence,
    allFailed: states.length > 0 && failed.length === states.length,
    siteDegraded: allRecordsZero && !anyEvidence,
  };
}

/** 逐检索式 × 逐源的 PRISMA 行（供 buildLog 的 sources 入参） */
function prismaRows(keyword, perSource) {
  const list = Array.isArray(perSource) ? perSource : [];
  return list.map(s => ({
    keyword,
    id: s.id,
    label: s.label,
    kind: s.kind,
    queryDialect: s.queryDialect,
    countSemantics: s.countSemantics,
    count: s.count,
    // 同 buildKeywordResult：none 型源的 reportedTotal 一律置 null（不采信、不展示、不相加）
    reportedTotal: s.countSemantics === 'exact' ? (s.reportedTotal == null ? null : s.reportedTotal) : null,
    countState: s.countState,
    ok: s.ok !== false,
    aborted: s.aborted || null,
    queryUsed: s.queryUsed || null,
    durationMs: s.durationMs == null ? null : s.durationMs,
  }));
}

/**
 * 按源聚合 PRISMA 行。**只做求和与计数，不做任何推断**：
 * `reportedTotal` 仅对 exact 型源累加；none 型源在这里显式保留 null。
 */
function aggregateBySource(rows) {
  const list = Array.isArray(rows) ? rows : [];
  const order = [];
  const by = new Map();
  for (const r of list) {
    if (!by.has(r.id)) {
      order.push(r.id);
      by.set(r.id, {
        id: r.id, label: r.label, kind: r.kind,
        queryDialect: r.queryDialect, countSemantics: r.countSemantics,
        searches: 0, okSearches: 0, records: 0,
        reportedTotal: r.countSemantics === 'exact' ? 0 : null,
        countKnown: r.countSemantics === 'exact',
        abortedReasons: [],
      });
    }
    const a = by.get(r.id);
    a.searches++;
    if (r.ok) a.okSearches++;
    a.records += Number(r.count) || 0;
    if (a.reportedTotal !== null) a.reportedTotal += Number(r.reportedTotal) || 0;
    if (r.aborted) a.abortedReasons.push(r.aborted);
  }
  return order.map(id => by.get(id));
}

/**
 * 源级降级告警（跨检索式去重）。
 * 目的：4 条检索式都挂同一个源时，不要打印 4 遍同样的话 —— 但**也不许合并成一句「有源失败」**
 * 而丢掉是哪个源、挂了几条。故按源聚合、把受影响的检索式条数列出来。
 * @param {Array} results [{ keyword, res }]
 * @returns {string[]}
 */
function sourceWarnings(results) {
  const list = Array.isArray(results) ? results : [];
  if (!list.length) return [];
  const failMap = new Map();      // id → {label, reasons:Set, kws:[]}
  let aliveKws = 0;
  for (const it of list) {
    const res = (it && it.res) || {};
    const per = Array.isArray(res.perSource) ? res.perSource : [];
    if (per.some(s => s.ok)) aliveKws++;
    for (const s of per) {
      if (s.ok) continue;
      if (!failMap.has(s.id)) failMap.set(s.id, { label: s.label, reasons: new Set(), kws: [] });
      const f = failMap.get(s.id);
      f.kws.push(it.keyword);
      if (s.aborted) f.reasons.add(s.aborted);
    }
  }
  const out = [];
  for (const [id, f] of failMap) {
    out.push('源 ' + f.label + '(' + id + ') 在 ' + f.kws.length + '/' + list.length + ' 条检索式中不可用：'
      + Array.from(f.reasons).join('；')
      + ' ⇒ 该源未贡献记录，其余源结果不受影响');
  }
  if (failMap.size && aliveKws) {
    out.push('本次降级运行：' + aliveKws + '/' + list.length + ' 条检索式仍有可用源'
      + '；结论的证据基础弱于全源运行，PRISMA 已按源分列');
  }
  if (failMap.size && !aliveKws) {
    out.push('全部 ' + list.length + ' 条检索式的所有源均不可用 ⇒ 这是网络/服务级故障，不是检索式无效；请勿据此排除任何检索式');
  }
  return out;
}

/** 人类可读的一行源读数（供 stderr / log 事件，不含 JSON 结构）
 *
 * ★ probe=true 时必须换措辞：探针模式**不保留记录**，若仍写「取得 N 条」会与 summary 的
 *   「records 0」自相矛盾（实测 e2e 踩到：summary 说 0 条，事件流说取得 2 条）。
 */
function sourceSummaryLine(results, opts) {
  const probe = !!(opts && opts.probe);
  const list = Array.isArray(results) ? results : [];
  if (!list.length) return null;
  const agg = new Map();
  for (const it of list) {
    for (const s of ((it.res || {}).perSource || [])) {
      if (!agg.has(s.id)) agg.set(s.id, { label: s.label, ok: 0, bad: 0, count: 0, exact: s.countSemantics === 'exact', total: 0 });
      const a = agg.get(s.id);
      if (s.ok) a.ok++; else a.bad++;
      a.count += Number(s.count) || 0;
      if (s.countSemantics === 'exact') a.total += Number(s.reportedTotal) || 0;
    }
  }
  const parts = [];
  for (const [, a] of agg) {
    parts.push(a.label + ' 可用 ' + a.ok + '/失败 ' + a.bad + '，'
      + (probe ? '源返回 ' + a.count + ' 条（探针模式未保留记录）' : '取得 ' + a.count + ' 条')
      + (a.exact ? '（自报命中合计 ' + a.total + '）' : '（不提供可用计数，不计入 PRISMA 计数）'));
  }
  return '多源通道 ' + agg.size + ' 个源：' + parts.join('；');
}

module.exports = {
  buildKeywordResult, multiProbeVerdict, prismaRows, aggregateBySource,
  sourceWarnings, sourceSummaryLine,
};
