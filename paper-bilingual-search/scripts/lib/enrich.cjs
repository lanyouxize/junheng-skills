#!/usr/bin/env node
/* eslint-disable */
/**
 * lib/enrich.cjs — 元数据补全 + 去重 + 质量自检
 *
 * 补全通道（均为合规公开 API，不触碰出版社页面，不绕过任何验证）:
 *   ① Europe PMC: TITLE:"<title>" AND PUB_YEAR:<year> —— 实测精确命中率高，
 *      可返回英文原文摘要（abstractText）、DOI、期刊全名、OA 状态。
 *      注意：老文献常无摘要，故状态必须区分 matched_with_abstract / matched_no_abstract。
 *   ② 原文直链抽 DOI: 实测覆盖率约 20%（多数直链非 /doi/ 路径），仅作可选补强，不作为卖点。
 *
 * 反幻觉约束：标题相似度 + 年份双重校验；不匹配就返回 unmatched，绝不猜配、绝不静默采用。
 */
'use strict';

const EPMC = 'https://www.ebi.ac.uk/europepmc/webservices/rest/search';
const sleep = ms => new Promise(r => setTimeout(r, ms));

const normTitle = t => (t || '')
  .toLowerCase()
  .replace(/[^\p{L}\p{N}\s]/gu, ' ')
  .replace(/\s+/g, ' ')
  .trim();

/** 标题 token 集合相似度（Jaccard），用于校验匹配正确性 */
function titleSimilarity(a, b) {
  const A = new Set(normTitle(a).split(' ').filter(w => w.length > 2));
  const B = new Set(normTitle(b).split(' ').filter(w => w.length > 2));
  if (!A.size || !B.size) return 0;
  let inter = 0;
  for (const w of A) if (B.has(w)) inter++;
  return inter / (A.size + B.size - inter);
}

/**
 * 单条补全。返回 enrich 对象（含 status 字段，供报告如实标注）
 */
async function enrichOne(rec, { intervalMs = 300, retries = 1, timeoutMs = 12000 } = {}) {
  const out = {
    status: 'skipped', source: null, doi: null, journalFull: null, isOA: null, abstractFull: null, matchScore: null,
    // ── v4.10 全文通道（★零新增请求：这些字段与 abstractText 在**同一个** core 响应里，
    //    旧实现只读了 isOpenAccess 就停下，等于已知「这篇 OA」却拿不到全文入口）──────
    pmcid: null,          // 有它才能取 /{pmcid}/fullTextXML
    hasPDF: null,         // 三态：true / false / null(字段缺失，不得当 false)
    license: null,        // 如 'cc by'；OA 但许可不明时要如实留空，不能假定可再用
    inPMC: null,          // 是否已进 PMC 全文库
    fullTextUrl: null,    // 优先给 OA 的 html，其次 pdf，最后按 pmcid 拼 europepmc 页
    citedByCount: null,   // 引文数（排序/影响力参考，不参与证据分级）
    pubTypes: null,       // ['research-article','Journal Article'] —— 区分原始研究/综述
    funders: null,        // 资助方（COI 判据：实测 b332d970 由 Hill's Pet Nutrition 资助）
  };
  if (!rec.titleEn) { out.status = 'no_title'; return out; }

  const q = rec.year
    ? 'TITLE:"' + rec.titleEn + '" AND PUB_YEAR:' + rec.year
    : 'TITLE:"' + rec.titleEn + '"';
  const url = EPMC + '?query=' + encodeURIComponent(q) + '&resultType=core&format=json&pageSize=3';

  let j = null;
  // v4.3：把 429 与普通错误**区分开**。旧实现里 429 会被重试耗尽后归为 `error:no_response`，
  //       并发安全阀就无法识别限流（只能瞎猜）。区分后 `error:429` 可直接计数。
  let got429 = false;
  for (let i = 0; i <= retries; i++) {
    let timer = null;
    try {
      const ctl = new AbortController();
      timer = setTimeout(() => ctl.abort(), timeoutMs);
      const r = await fetch(url, { signal: ctl.signal, headers: { 'User-Agent': 'paper-bilingual-search/1.0' } });
      clearTimeout(timer);
      if (r.status === 429) { got429 = true; await sleep(1500 * (i + 1)); continue; }
      if (!r.ok) throw new Error('HTTP ' + r.status);
      j = await r.json();
      break;
    } catch (e) {
      if (timer) clearTimeout(timer);
      if (i === retries) { out.status = got429 ? 'error:429' : 'error:' + String(e).slice(0, 80); return out; }
      await sleep(1200 * (i + 1));
    }
  }
  if (!j) { out.status = got429 ? 'error:429' : 'error:no_response'; return out; }

  const hits = (j.resultList && j.resultList.result) || [];
  if (!hits.length) { out.status = 'unmatched'; return out; }

  // 双重校验：标题相似度 ≥0.6 且年份一致（有年份时）
  let best = null, bestScore = 0;
  for (const h of hits) {
    const score = titleSimilarity(rec.titleEn, h.title);
    const yearOk = !rec.year || !h.pubYear || String(h.pubYear) === String(rec.year);
    if (yearOk && score > bestScore) { bestScore = score; best = h; }
  }
  if (!best || bestScore < 0.6) { out.status = 'unmatched'; out.matchScore = +bestScore.toFixed(2); return out; }

  out.status = best.abstractText ? 'matched_with_abstract' : 'matched_no_abstract';
  out.source = 'EuropePMC';
  out.matchScore = +bestScore.toFixed(2);
  out.doi = best.doi || null;
  out.journalFull = (best.journalInfo && best.journalInfo.journal && best.journalInfo.journal.title) || null;
  out.isOA = best.isOpenAccess === 'Y';
  out.abstractFull = best.abstractText ? String(best.abstractText).replace(/<[^>]+>/g, '').trim() : null;

  // ── v4.10 全文通道字段（同一响应体，零新增请求）──────────────
  out.pmcid = best.pmcid || null;
  // hasPDF / inPMC 缺失时必须留 null：写成 false 会让「确认没有」与「EPMC 没告诉」混为一谈
  out.hasPDF = (best.hasPDF === undefined || best.hasPDF === null) ? null : best.hasPDF === 'Y';
  out.license = best.license || null;
  out.inPMC = (best.inPMC === undefined || best.inPMC === null) ? null : best.inPMC === 'Y';
  out.citedByCount = Number.isFinite(Number(best.citedByCount)) ? Number(best.citedByCount) : null;
  out.pubTypes = pickPubTypes(best.pubTypeList);
  out.funders = pickFunders(best.grantsList);
  out.fullTextUrl = pickFullTextUrl(best.fullTextUrlList, out.pmcid);
  return out;
}

/** `pubTypeList.pubType` 是字符串数组；用于区分原始研究 / 综述（证据分级口径的辅助判据）。 */
function pickPubTypes(node) {
  const arr = node && node.pubType;
  if (!Array.isArray(arr)) return null;
  const out = arr.filter(x => typeof x === 'string' && x.trim());
  return out.length ? out : null;
}

/**
 * 资助方（COI）。实测 `b332d970` 的 grantsList 里是 `Hill's Pet Nutrition (United States)` ——
 * 这类信息**不改变证据等级**（等级只看设计与终点），但必须在报告里可见：
 * 一个由厂商资助、结论恰好支持该厂商品类的试验，读者有权知道。
 */
function pickFunders(node) {
  const arr = node && node.grant;
  if (!Array.isArray(arr)) return null;
  const out = [];
  for (const g of arr) {
    const a = g && g.agency;
    if (typeof a === 'string' && a.trim() && !out.includes(a.trim())) out.push(a.trim());
  }
  return out.length ? out : null;
}

/**
 * 全文入口。优先 OA 的 html，其次 OA 的 pdf，最后按 pmcid 拼 europepmc 页面。
 * 注意 `fullTextUrlList.fullTextUrl` 是**数组**（每个元素带 availabilityCode / documentStyle），
 * 而 `fullTextIdList.fullTextId` 是**嵌套对象里的数组** —— 两者形态不同，别混着用。
 */
function pickFullTextUrl(list, pmcid) {
  const arr = (list && list.fullTextUrl) || [];
  const usable = arr.filter(u => u && typeof u.url === 'string' && u.url);
  const oa = usable.filter(u => u.availabilityCode === 'OA');
  const html = oa.find(u => u.documentStyle === 'html');
  const pdf = oa.find(u => u.documentStyle === 'pdf');
  const anyPdf = usable.find(u => u.documentStyle === 'pdf');
  return (html && html.url) || (pdf && pdf.url) || (anyPdf && anyPdf.url)
    || (pmcid ? 'https://europepmc.org/articles/' + pmcid : null);
}

/**
 * 批量补全（v4.3：由「严格串行」改为**有界并发 + 429 安全阀**）
 *
 * 取证依据（`.verify/b2-epmc-probe.cjs`，2026-10-14，12 条真实题名实测）：
 *   · 串行（+300ms 节流） 24 234 ms
 *   · 并发 4            3 539 ms（**6.85×**）  429 = 0
 *   · 并发 6            1 290 ms（**18.79×**） 429 = 0
 * ⇒ v4.2 注释里「禁止并发提速：风控优先」的隐含前提被实测推翻（至少在该观测窗口与规模下）。
 *   但**探针仅 36 次请求，不构成压测** ⇒ 必须带安全阀，且必须可无条件回退：
 *     · `concurrency <= 1` 时**逐字节复刻 v4.2 串行路径**（含 `enrichOne` 完成后再 sleep 的节奏）；
 *     · 并发路径下 `intervalMs` 语义变为「两次派发之间的最小间隔」；
 *     · 连续 `degradeAfter429` 次 429 ⇒ **自动降级为串行**并在返回中标记（安全阀，不是静默）。
 *
 * 结果顺序与 `records` 严格一一对应（并发不改变顺序），`onItem` 仍逐条回调。
 */
async function enrichAll(records, opts = {}) {
  const { intervalMs = 300, concurrency = 4, onItem, degradeAfter429 = 3 } = opts;
  const results = new Array(records.length);
  const stat = {};
  const bump = st => { stat[st] = (stat[st] || 0) + 1; };
  const finish = (i, e) => { results[i] = e; records[i].enrich = e; bump(e.status); if (onItem) onItem(records[i], e); };

  // —— 串行路径：v4.2 行为逐字节保留（concurrency=1 即完整回退手段）——
  if (!(concurrency > 1)) {
    for (let i = 0; i < records.length; i++) {
      finish(i, await enrichOne(records[i], opts));
      await sleep(intervalMs);
    }
    return { stat, results, concurrency: 1, degraded: false, degradedAt: null };
  }

  // —— 有界并发路径 ——
  let cursor = 0;
  let consecutive429 = 0;
  let degraded = false;
  let degradedAt = null;
  const worker = async () => {
    for (;;) {
      if (degraded) return;                       // 已降级 → 剩余条目交给下方串行兜底
      const i = cursor++;
      if (i >= records.length) return;
      const e = await enrichOne(records[i], opts);
      finish(i, e);
      if (e.status === 'error:429') {
        consecutive429++;
        if (consecutive429 >= degradeAfter429 && !degraded) { degraded = true; degradedAt = i; }
      } else if (e.status !== 'skipped' && e.status !== 'no_title') {
        consecutive429 = 0;                       // 有实质成功即清零，避免历史 429 累积误触发降级
      }
      await sleep(intervalMs);
    }
  };
  const workers = Math.min(concurrency, Math.max(1, records.length));
  await Promise.all(Array.from({ length: workers }, () => worker()));

  // 降级后补齐剩余条目（顺序遍历 ⇒ 不丢条、不重复）
  if (degraded) {
    for (let i = 0; i < records.length; i++) {
      if (results[i] !== undefined) continue;
      finish(i, await enrichOne(records[i], opts));
      await sleep(intervalMs);
    }
  }
  const statOut = { stat, results, concurrency: degraded ? 1 : workers, degraded, degradedAt };
  return statOut;
}

/**
 * DOI 归一化：小写 + 去 `https?://(dx.)?doi.org/` 前缀 + 去 `doi:` scheme + 去末尾点。
 * 未归一化时，同一 DOI 的「大小写 / 带前缀 / 带末点」三种写法会被判为三篇不同文献（漏去重）。
 */
function normalizeDoi(d) {
  if (!d) return '';
  return String(d).trim().toLowerCase()
    .replace(/^https?:\/\/(dx\.)?doi\.org\//, '')
    .replace(/^doi:\s*/, '')
    .replace(/\.+$/, '')
    .trim();
}

/** 单条记录的去重标识（用于报告追溯）；既无 DOI 也无标题时返回 null = 不参与去重 */
function dedupeTag(r) {
  const doi = normalizeDoi(r.enrich && r.enrich.doi);
  if (doi) return 'doi:' + doi;
  const t = normTitle(r.titleEn);
  if (t) return 't:' + t;
  return null;
}

/**
 * 跨关键词去重（并查集连通 + 年份冲突保护 + 空值不参与）
 *
 * 与 v4.1 及更早版本的差异（均为实测取证后修正，见 CHANGELOG v4.2）：
 *  - 旧键 `doi || 't:'+标题+'|y:'+年份 || 't:'+标题`：第三段是**死代码**
 *    （`'t:x|y:'` 恒为真值 ⇒ 兜底层从未执行）；
 *  - 旧键把年份拼进键 ⇒ **一侧缺年份就判为两篇**（漏去重）；
 *  - 旧键在「标题为空」时退化为 `t:|y:` ⇒ **多篇真实论文被塌成一篇（数据丢失）**；
 *  - 旧键直接用原始 DOI ⇒ 大小写 / 前缀 / 末点差异均漏去重。
 *
 * 现策略：
 *  ① DOI 与标题**双向互链**成连通分量（并查集），避免「有 DOI 的一条」与「无 DOI 的一条」对不上；
 *  ② 分量内若存在**已知且不同**的年份 → 视为不同文献并拆分，防止把同名不同年的真文献误删；
 *  ③ 既无 DOI 也无标题的记录**不参与去重**（宁可重复，不可丢失）。
 *
 * 返回 { unique, duplicates, total, skipped }；duplicates 每条标注首次出现的关键词，供报告追溯。
 */
function dedupe(groups) {
  // ① 展平，保留「关键词 + 记录」与出现顺序
  const flat = [];
  for (const g of groups) for (const r of g.records || []) flat.push({ g, r });

  // ② 并查集
  const parent = flat.map((_, i) => i);
  const find = i => { while (parent[i] !== i) { parent[i] = parent[parent[i]]; i = parent[i]; } return i; };
  const union = (a, b) => { a = find(a); b = find(b); if (a !== b) parent[b] = a; };

  const byDoi = new Map();
  const byTitle = new Map();
  const skipped = [];
  flat.forEach(({ r }, i) => {
    const doi = normalizeDoi(r.enrich && r.enrich.doi);
    const t = normTitle(r.titleEn);
    if (doi) { if (byDoi.has(doi)) union(byDoi.get(doi), i); else byDoi.set(doi, i); }
    if (t) { if (byTitle.has(t)) union(byTitle.get(t), i); else byTitle.set(t, i); }
    if (!doi && !t) skipped.push(i); // ③ 无可判定标识 → 不参与去重
  });

  // ③ 连通分量
  const comp = new Map();
  flat.forEach((_, i) => { const k = find(i); if (!comp.has(k)) comp.set(k, []); comp.get(k).push(i); });

  // ④ 年份冲突保护：分量内年份已知且不同 → 按年份拆分（无年份的归入首个已知年份）
  const clusters = [];
  for (const idxs of comp.values()) {
    if (idxs.length === 1) { clusters.push(idxs); continue; }
    const years = [...new Set(idxs.map(i => flat[i].r.year).filter(y => y != null && y !== ''))];
    if (years.length > 1) {
      const byYear = new Map();
      for (const i of idxs) {
        const y = flat[i].r.year || years[0];
        if (!byYear.has(y)) byYear.set(y, []);
        byYear.get(y).push(i);
      }
      for (const v of byYear.values()) clusters.push(v);
    } else {
      clusters.push(idxs);
    }
  }

  // ⑤ 稳定输出：簇按首次出现排序，簇内最小下标者为「唯一」
  const ordered = clusters
    .map(idxs => idxs.slice().sort((a, b) => a - b))
    .sort((a, b) => a[0] - b[0]);

  const unique = [];
  const duplicates = [];
  for (const idxs of ordered) {
    const first = flat[idxs[0]];
    idxs.forEach((i, n) => {
      const { g, r } = flat[i];
      if (n === 0) {
        unique.push({ ...r, keyword: g.keyword });
      } else {
        duplicates.push({
          key: dedupeTag(r) || 'no-key',
          keyword: g.keyword,
          idx: r.idx,
          titleEn: r.titleEn,
          firstSeenIn: first.g.keyword,
        });
        r.duplicateOf = { keyword: first.g.keyword, idx: first.r.idx, titleEn: first.r.titleEn };
      }
    });
  }
  return { unique, duplicates, total: unique.length + duplicates.length, skipped: skipped.length };
}

/** 质量自检：把「成功但空字段」这种静默降级变成显式失败 */
function qcCheck(groups, { titleMin = 0.9, abstractMin = 0.0, limit = null } = {}) {
  // --limit 0 = 「计数探针」：用户**显式**要求不抓条目 ⇒ 0 条是**预期结果**，不是静默降级。
  // 不豁免的话，all.length=0 会让分母退化成 1、填充率恒为 0 ⇒ 必然报「疑似选择器失效」的**假诊断**（v4.6 修）。
  if (limit === 0) {
    return { ok: true, fill: null, issues: [], n: 0, skipped: 'limit_0_count_only_probe' };
  }
  const all = [];
  for (const g of groups) for (const r of g.records) all.push(r);
  const n = all.length || 1;
  const rate = k => +(all.filter(r => r && r[k] != null && String(r[k]).trim()).length / n).toFixed(3);
  const fill = { title: rate('titleEn'), authors: rate('authors'), source: rate('source'), year: rate('year'), abstract: rate('abstractEn'), zh: rate('titleZh') };
  const issues = [];
  if (fill.title < titleMin) issues.push('标题填充率 ' + fill.title + ' < ' + titleMin + '（疑似选择器失效，非真实空值）');
  if (fill.abstract < abstractMin) issues.push('摘要填充率过低: ' + fill.abstract);
  const ok = issues.length === 0;
  return { ok, fill, issues, n: all.length };
}

module.exports = { enrichOne, enrichAll, dedupe, qcCheck, titleSimilarity, normTitle, normalizeDoi, dedupeTag };
