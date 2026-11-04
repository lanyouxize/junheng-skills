/* eslint-disable */
/**
 * lib/sources/crossref.cjs — Crossref 连接器（HTTP，无需浏览器）
 *
 * 定位：**补充源 / 元数据源**，不是计数源。这个定位来自实测，不是保守估计：
 *   2026-10-26 实测 `query.bibliographic=(cat OR feline) AND hairball` → `total-results` 358659；
 *   换成纯词袋 `cat feline hairball` → **total 仍是 358659，且 top4 条目与 score 逐字相同**；
 *   换成 `hairball cat fiber psyllium` → total 776322。
 *   ⇒ ① 它**完全不解析布尔运算符**（OR/AND/括号被当噪音，检索式越复杂它越偏）；
 *     ② `total-results` 是全库软匹配规模，**与检索意图无关**，绝不能进 PRISMA 的「数据库报告记录数」。
 *
 *   相关性也弱：`Cat - Osteology`（21.9 分）与真实相关文献 `Oesophageal obstruction by a hairball`
 *   （22.4 分）几乎同分 —— 故本源的命中必须在 relevance 层降权，不能与 Europe PMC 平权。
 *
 * 因此本连接器的三条硬约定：
 *   ① `countSemantics: 'none'` ⇒ `reportedTotal` 恒为 null（不填 358659 这种假数），
 *      三态判定自然落到 collect_failed 语义之外的「不适用」，由调度器按 `countSemantics` 分流；
 *   ② 布尔式必须先 `booleanToBag()` 转译，否则等于把运算符当检索词；
 *   ③ 摘要为 JATS 标签串（`<jats:p>`），必须剥标签后再入表，否则报告里全是尖括号。
 */
'use strict';

const { fetchJson, qs } = require('./http.cjs');
const { canonicalRecord, stripJats, booleanToBag, asText, asYear } = require('./normalize.cjs');

const BASE = 'https://api.crossref.org/works';
const ROWS_CAP = 100;

/** Crossref 的 author 是对象数组，拼成与 EPMC 的 authorString 一致的「姓 名首字母」风格 */
function joinAuthors(a) {
  if (!Array.isArray(a) || !a.length) return null;
  const parts = a.map(x => {
    if (!x || typeof x !== 'object') return null;
    const fam = asText(x.family);
    const giv = asText(x.given);
    if (fam && giv) {
      // 名取首字母序列（'John A.' → 'JA'），对齐 byline 解析出的 'Donadelli RA' 形态
      const ini = giv.split(/\s+/).map(w => (w.match(/\p{L}/u) || [''])[0]).filter(Boolean).join('');
      return fam + (ini ? ' ' + ini.toUpperCase() : '');
    }
    return fam || asText(x.name) || giv;
  }).filter(Boolean);
  return parts.length ? parts.join(', ') : null;
}

function mapOne(it) {
  const doi = asText(it.DOI);
  const year = (it.issued && Array.isArray(it.issued['date-parts']) && it.issued['date-parts'][0])
    ? asYear(it.issued['date-parts'][0][0]) : null;
  const title = Array.isArray(it.title) ? asText(it.title[0]) : asText(it.title);
  const container = Array.isArray(it['container-title']) ? asText(it['container-title'][0]) : asText(it['container-title']);
  const url = doi ? 'https://doi.org/' + doi : asText(it.URL);
  return {
    titleEn: title,
    authors: joinAuthors(it.author),
    source: container,
    year,
    abstractEn: stripJats(asText(it.abstract)),
    citedBy: Number.isFinite(it['is-referenced-by-count']) ? it['is-referenced-by-count'] : null,
    paperUrl: url,
    sourceUrl: url,
    doi,
    pmid: null,
    pmcid: null,
    oaStatus: null,     // Crossref 不提供 OA 状态 ⇒ null（未知），不得当 false
    pubType: asText(it.type),
    _score: Number.isFinite(it.score) ? it.score : null,
  };
}

/**
 * @param {object} p { query, limit, keyword, timeoutMs, mailto, log }
 */
async function search(p) {
  const o = p || {};
  const limit = Math.max(0, Number(o.limit) || 0);
  const t0 = Date.now();
  const diag = {
    sourceId: 'crossref',
    url: null,
    queryUsed: null,
    pages: 0,
    // ★ 恒 null：Crossref 的 total-results 与检索意图无关（实测），填报它等于制造假计数
    reportedTotal: null,
    noResultsSignal: false,
    aborted: null,
    countSemantics: 'none',
    durationMs: 0,
  };
  const records = [];
  if (!o.query) { diag.aborted = 'empty_query'; return { records, diagnostics: diag }; }

  const bag = booleanToBag(o.query);
  diag.queryUsed = bag;
  if (!bag) { diag.aborted = 'empty_bag_after_translate'; diag.durationMs = Date.now() - t0; return { records, diagnostics: diag }; }

  const want = limit === 0 ? 1 : limit;
  const rows = Math.min(want, ROWS_CAP);
  const params = {
    'query.bibliographic': bag,
    rows,
    select: 'DOI,title,abstract,author,container-title,issued,type,is-referenced-by-count,score',
  };
  // 礼貌池标识：Crossref 用 UA + mailto 识别批量客户端（不带也能用，但会被限速）
  if (o.mailto) params.mailto = o.mailto;

  const url = BASE + '?' + qs(params);
  diag.url = url;
  try {
    const res = await fetchJson(url, { timeoutMs: o.timeoutMs || 25000, maxAttempts: 3 });
    if (!res.ok) {
      diag.aborted = 'source_error:' + res.kind + (res.status ? ':HTTP' + res.status : '') + ':' + String(res.error || '').slice(0, 120);
      diag.durationMs = Date.now() - t0;
      return { records, diagnostics: diag };
    }
    const msg = (res.json && res.json.message) || {};
    const items = Array.isArray(msg.items) ? msg.items : [];
    diag.pages = 1;
    // 空 items 才算「确认无结果」；total-results 不可作依据（见文件头实测）
    if (!items.length) diag.noResultsSignal = true;
    for (const it of items) {
      if (records.length >= want) break;
      const raw = mapOne(it);
      if (!raw.titleEn) continue;
      const rec = canonicalRecord(raw, {
        keyword: o.keyword,
        idx: records.length + 1,
        page: 1,
        sourceId: 'crossref',
        sourceLabel: 'Crossref',
        rank: records.length + 1,
        countSemantics: 'none',
      });
      // Crossref 的相关性分数落进 provenance，供 relevance 层决定降权幅度（不在此处硬过滤）
      if (raw._score != null) rec.provenance.score = raw._score;
      records.push(rec);
    }
  } catch (e) {
    diag.aborted = 'exception:' + String(e).slice(0, 160);
  }
  diag.durationMs = Date.now() - t0;
  return { records, diagnostics: diag };
}

const meta = {
  id: 'crossref',
  label: 'Crossref',
  kind: 'http',
  // boolean 检索式必须转译为词袋（booleanToBag），故此源标记为 bag 方言
  queryDialect: 'bag',
  countSemantics: 'none',
  capabilities: {
    abstract: true, doi: true, oa: false, pmid: false, pmcid: false,
    citedBy: true, pubType: true, translate: false, fulltextHint: false,
  },
  notes: '不解析布尔运算符（实测：布尔式与词袋的 total 与 top4 逐字相同）；total-results 为全库软匹配规模，禁止进 PRISMA 计数；摘要为 JATS 需剥标签；相关性弱需降权',
};

module.exports = { ...meta, search, mapOne, joinAuthors };
