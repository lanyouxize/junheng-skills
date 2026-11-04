/* eslint-disable */
/**
 * lib/scheduler.cjs — 多源调度器（并发 / 超时隔离 / 跨源去重 / 降级上报）
 *
 * 要解决的原始故障（2026-10-26 一手实测，非推演）：
 *   同一批 4 条计数探针，kuluer 站点 **3 条 collect_failed**（page.goto 30s 超时），
 *   而整次运行只有「全 0 且无读数」这一种情况才报警 ⇒ 部分失败完全静默，
 *   使用者可能据此**误排除一条本来有效的检索式**。单源架构下这是致命的：
 *   源一挂，整次任务归零；多源架构下同样的故障只是「少一个视角」。
 *
 * 三条必须显式处理的判断（每条都有对应的闸门用例）：
 *   ① **计数语义分流**：`countSemantics: 'none'` 的源（Crossref）永远不给 reportedTotal。
 *      若照搬三态判定，它会被判成 `collect_failed`（假故障）⇒ 走 `not_applicable` 分支。
 *      ★ 这是「误报比漏报更糟」的直接应用：假故障会让降级逻辑自己制造噪音。
 *   ② **失败隔离**：单源抛异常/超时，只记一条 failure，不影响其它源，也不让整次检索失败。
 *   ③ **跨源去重的双重上限**：DOI 优先；无 DOI 时按「规范化标题 + 年份容错 ±1」合并
 *      （epub ahead of print 与正式发表的年份常差 1）。合并只用 mergeInto 的「只填空不覆盖」，
 *      保证注册表顺序 = 优先级，低可信源改不掉高可信源的正确字段。
 */
'use strict';

const { classifyCount, COUNT_STATE } = require('./probe.cjs');
const { getSource, resolveSources } = require('./sources/index.cjs');
const { mergeInto, normDoi, normTitleKey, isUsable } = require('./sources/normalize.cjs');

/** 计数语义为 'none' 的源的专用状态（与三态互斥，绝不与 collect_failed 混用） */
const COUNT_NA = 'not_applicable';

const sleep = ms => new Promise(r => setTimeout(r, ms));

/** 单源执行 + 外层超时兜底。内层连接器自带 timeoutMs，此处只防「连接器内部逻辑卡死」
 *
 * ★ 2026-10-26 实测修：初版写成 `Math.max(5000, perSourceTimeoutMs)`，把调用方给的 800ms
 *   **静默抬到 5000ms** ⇒ 3s 的源跑完了，超时分支永不触发，「全源皆挂」被误判成正常运行。
 *   静默抬高用户显式给定的上限属于「改用户意图」，不可接受。现只做下限 100ms 的防 0/NaN 保护。
 *   默认值取 120s 的理由：内层单次 HTTP 25s × 3 次重试 + 退避 ≈ 80s，外层必须大于内层最坏值，
 *   否则「连接器自己会重试」这件事会被外层提前砍断，反而制造假失败。
 */
async function runOne(mod, p) {
  const rawOuter = Number(p.perSourceTimeoutMs);
  const outerMs = Math.max(100, Number.isFinite(rawOuter) && rawOuter > 0 ? rawOuter : 120000);
  const t0 = Date.now();
  let timer = null;
  const timeout = new Promise(resolve => {
    timer = setTimeout(() => resolve({
      records: [],
      diagnostics: {
        sourceId: mod.id, aborted: 'scheduler_timeout:' + outerMs + 'ms',
        reportedTotal: null, noResultsSignal: false, durationMs: Date.now() - t0,
      },
      __timedOut: true,
    }), outerMs);
  });
  try {
    const r = await Promise.race([
      mod.search({ query: p.query, limit: p.limit, keyword: p.keyword, log: p.log, timeoutMs: p.httpTimeoutMs, mailto: p.mailto }),
      timeout,
    ]);
    return r || { records: [], diagnostics: { sourceId: mod.id, aborted: 'null_result', reportedTotal: null, noResultsSignal: false, durationMs: Date.now() - t0 } };
  } catch (e) {
    // 连接器抛异常 = 该源本次不可用，但**不向上抛**（红线②：失败隔离）
    return {
      records: [],
      diagnostics: {
        sourceId: mod.id, aborted: 'threw:' + String(e && e.message || e).slice(0, 160),
        reportedTotal: null, noResultsSignal: false, durationMs: Date.now() - t0,
      },
    };
  } finally {
    if (timer) clearTimeout(timer);
  }
}

/** 按 kind 分组：http 可并发，browser 必须串行（共用同一个浏览器实例） */
function partition(mods) {
  const http = [];
  const browser = [];
  for (const m of mods) (m.kind === 'browser' ? browser : http).push(m);
  return { http, browser };
}

/** 有界并发的 map（保持结果顺序与输入一致，便于按注册表优先级合并） */
async function mapLimit(items, limit, fn) {
  const out = new Array(items.length);
  let cursor = 0;
  const n = Math.max(1, Math.min(limit || 1, items.length || 1));
  const workers = Array.from({ length: n }, async () => {
    while (true) {
      const i = cursor++;
      if (i >= items.length) return;
      out[i] = await fn(items[i], i);
    }
  });
  await Promise.all(workers);
  return out;
}

/**
 * 跨源去重。输入是按「源优先级」排好的记录数组（同源内的顺序也要保留，它是相关性排序）。
 * @returns {{records:Array, stat:object}}
 */
function dedupeCrossSource(records) {
  const kept = [];                 // 保持顺序的代表记录
  const byDoi = new Map();
  const byTitle = new Map();
  let mergedByDoi = 0, mergedByTitle = 0, mergedCrossSource = 0;
  const before = records.length;

  for (const rec of records) {
    if (!isUsable(rec)) continue;   // 无标题记录直接不参与（与 enrich.isUsable 同源判据）
    const doi = normDoi(rec.doi) || normDoi(rec.doiFromUrl);
    const tk = normTitleKey(rec.titleEn);

    let hit = null, how = null;
    if (doi && byDoi.has(doi)) { hit = byDoi.get(doi); how = 'doi'; }
    if (!hit && tk) {
      // 标题键 + 年份容错 ±1（epub 与正式发表常见差 1 年）
      for (const dy of [0, -1, 1]) {
        const y = rec.year == null ? null : rec.year + dy;
        const k = tk + '|' + (y == null ? '?' : y);
        if (byTitle.has(k)) { hit = byTitle.get(k); how = 'title'; break; }
      }
    }
    if (hit) {
      const sameSource = hit.provenance && rec.provenance && hit.provenance.sourceId === rec.provenance.sourceId;
      mergeInto(hit, rec);
      if (how === 'doi') mergedByDoi++; else mergedByTitle++;
      if (!sameSource) mergedCrossSource++;
      // 合并后标题可能被补全，需要把标题键补登记，否则后续同篇无法再次命中
      const ntk = normTitleKey(hit.titleEn);
      if (ntk && hit.year != null) byTitle.set(ntk + '|' + hit.year, hit);
      continue;
    }

    kept.push(rec);
    if (doi) byDoi.set(doi, rec);
    if (tk && rec.year != null) byTitle.set(tk + '|' + rec.year, rec);
    else if (tk) byTitle.set(tk + '|?', rec);
  }

  return {
    records: kept,
    stat: {
      before, after: kept.length, removed: before - kept.length,
      mergedByDoi, mergedByTitle, mergedCrossSource,
    },
  };
}

/**
 * 跑一批源。
 * @param {object} p
 *   sources           string|string[]   (resolveSources 可解析的任何形态)
 *   query             string            检索式（布尔式原样传入，方言差异由连接器自理）
 *   limit             number            每源最多取几条（0 = 计数探针）
 *   keyword           string
 *   concurrency       number            http 源并发度（默认 2）
 *   perSourceTimeoutMs number           单源外层超时（默认 60s）
 *   httpTimeoutMs     number            单次 HTTP 超时（透传连接器）
 *   mailto            string            礼貌池标识（透传连接器）
 *   log               function
 *   resolve           function          可选：id → 连接器。**仅供单测注入假源**；
 *                                       缺省用注册表 getSource。注入时 sources 必须显式给 id 数组，
 *                                       因为假源不在注册表里，过不了 resolveSources 的白名单校验。
 * @returns {Promise<object>}
 */
async function runSources(p) {
  const o = p || {};
  const inject = typeof o.resolve === 'function';
  const resolveFn = inject ? o.resolve : getSource;
  // 注入模式跳过白名单解析（假源本就不在注册表内）；正常模式一律走 resolveSources，
  // 保证「未知源必报错」这条红线在真实调用路径上不被绕过。
  const ids = inject && Array.isArray(o.sources)
    ? Array.from(new Set(o.sources))
    : resolveSources(o.sources == null ? 'default' : o.sources);
  const mods = ids.map(id => {
    const m = resolveFn(id);
    if (!m) throw new Error('未知源: ' + id);   // resolveSources 已挡，此处是双保险
    return m;
  });

  const t0 = Date.now();
  const { http, browser } = partition(mods);

  // 结果按**注册表顺序**回收：注册表顺序 = 优先级，去重时先到者胜
  const collected = new Map();
  const httpRes = await mapLimit(http, o.concurrency || 2, async m => {
    const r = await runOne(m, o);
    return [m.id, r];
  });
  for (const pair of httpRes) if (pair) collected.set(pair[0], pair[1]);

  // browser 源串行（共用浏览器实例）；当前注册表内无 browser 源，此分支为 v4.16 的站点源预留
  for (const m of browser) {
    collected.set(m.id, await runOne(m, o));
  }

  const perSource = [];
  const failures = [];
  const degraded = [];
  const allRecords = [];

  for (const m of mods) {
    const r = collected.get(m.id) || { records: [], diagnostics: {} };
    const d = r.diagnostics || {};
    const recs = Array.isArray(r.records) ? r.records : [];

    // ★ 计数语义分流（红线①）：none 型源不参与三态判定，避免被伪判为 collect_failed
    let countState, countValue;
    if (m.countSemantics === 'none') {
      countState = COUNT_NA;
      countValue = null;
    } else {
      const c = classifyCount({ reportedTotal: d.reportedTotal, noResultsSignal: d.noResultsSignal });
      countState = c.state;
      countValue = c.count;
    }

    const aborted = d.aborted || null;
    const ok = !aborted;
    if (!ok) { failures.push({ id: m.id, label: m.label, reason: aborted }); degraded.push(m.id); }

    perSource.push({
      id: m.id,
      label: m.label,
      kind: m.kind,
      ok,
      count: recs.length,
      reportedTotal: countValue,
      countState,
      countSemantics: m.countSemantics,
      queryDialect: m.queryDialect,
      aborted,
      durationMs: d.durationMs == null ? null : d.durationMs,
      url: d.url || null,
      queryUsed: d.queryUsed || null,
      pages: d.pages == null ? null : d.pages,
    });
    for (const rec of recs) allRecords.push(rec);
  }

  const dd = dedupeCrossSource(allRecords);

  // 「有证据」= 至少一个源给出 exact 计数（含 0）或明确无结果。
  // 这与 probe.siteDegraded 同判据，但作用在「多源」上：只要有一个源说了话，就不是全站不可用。
  const anyEvidence = perSource.some(s => s.countState === COUNT_STATE.COUNTED || s.countState === COUNT_STATE.ZERO_CONFIRMED);
  const allFailed = perSource.length > 0 && perSource.every(s => !s.ok);

  return {
    records: dd.records,
    perSource,
    dedupe: dd.stat,
    failures,
    degraded,
    anyEvidence,
    allFailed,
    // 全源都挂 ⇒ 站点级不可用；有一源活着就不算（这正是多源相对单源的核心收益）
    siteDegraded: allFailed,
    durationMs: Date.now() - t0,
  };
}

/**
 * 人类可读的降级摘要（一行一条，末行给结论）。供主脚本写进 summary.warnings 与 stderr。
 * @returns {string[]}
 */
function degradeWarnings(res) {
  const out = [];
  if (!res) return out;
  for (const f of res.failures || []) {
    out.push('源 ' + f.label + '(' + f.id + ') 本次不可用：' + f.reason + ' ⇒ 该源未贡献任何记录，其余源结果不受影响');
  }
  const live = (res.perSource || []).filter(s => s.ok);
  if ((res.failures || []).length && live.length) {
    out.push('本次降级运行：' + live.length + '/' + res.perSource.length + ' 个源可用（'
      + live.map(s => s.label + ' ' + s.count + ' 条').join('、') + '）；结论的证据基础弱于全源运行，报告已标注');
  }
  if (res.siteDegraded) {
    out.push('全部 ' + (res.perSource || []).length + ' 个源均不可用 ⇒ 这是站点/网络级故障，不是检索式无效；请勿据此排除任何检索式');
  }
  const na = (res.perSource || []).filter(s => s.countState === COUNT_NA);
  if (na.length) {
    out.push('以下源不提供可用计数（countSemantics=none），其命中数**不进入** PRISMA 计数：'
      + na.map(s => s.label).join('、') + '；这不是采集失败');
  }
  return out;
}

module.exports = {
  runSources, dedupeCrossSource, degradeWarnings, mapLimit, partition,
  COUNT_NA,
};
