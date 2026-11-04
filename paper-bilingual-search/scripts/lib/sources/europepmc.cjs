/* eslint-disable */
/**
 * lib/sources/europepmc.cjs — Europe PMC 连接器（HTTP，无需浏览器）
 *
 * 定位：**主力检索源**。选它的理由（均为 2026-10-26 一手实测，非文档推测）：
 *   ① 布尔式**直接吃**外部检索式，无需转译：`(cat OR feline) AND hairball` → hitCount 141，
 *      且同一式加 `TITLE_ABS:` 限定后得 7 条 —— 说明它真的在按布尔逻辑解析，不是软匹配；
 *   ② `hitCount` 是**精确命中数**，可直接进 PRISMA（对照 Crossref 的 total 是全库规模，见 crossref.cjs）；
 *   ③ `resultType=core` 一次返回 pmid/pmcid/doi/title/authorString/journalTitle/pubYear/
 *      abstractText/isOpenAccess/hasPDF/citedByCount/pubTypeList —— 摘要与 OA 状态同源，
 *      **零额外请求**就能填满证据表所需字段（旧实现只读 isOpenAccess 就停，是已知浪费）；
 *   ④ 响应 11.8KB / 2.5s，稳定性远高于站点通道。
 *
 * ⚠️ 语义边界（必须如实登记，不得当等价源用）：
 *   - 裸词检索是**全字段**匹配（含全文），故同一检索式在 EPMC 上的命中数天然大于
 *     Google Scholar 语义的站点源。这不是缺陷，但**两个源的计数不可直接相加**：
 *     PRISMA 里必须按源分行列出，不可汇总成一个「数据库报告记录数」。
 *   - 以英文文献为主；中文期刊覆盖弱（与技能既有结论一致）。
 */
'use strict';

const { fetchJson, qs } = require('./http.cjs');
const { canonicalRecord, stripJats, asText, asYear } = require('./normalize.cjs');

const BASE = 'https://www.ebi.ac.uk/europepmc/webservices/rest/search';

/** EPMC 单页上限 1000；实际取 min(limit,100) —— 证据表场景下 100 条已远超可用量 */
const PAGE_CAP = 100;

/** 把 EPMC 的一条 result 映射成半成品（缺字段一律 null，不省略 key） */
function mapOne(r) {
  const src = asText(r.source) || 'MED';
  const id = asText(r.id);
  const doi = asText(r.doi);
  const pmid = asText(r.pmid);
  const pmcid = asText(r.pmcid);
  const epmcUrl = id ? 'https://europepmc.org/article/' + src + '/' + id : null;
  // isOpenAccess 只有 'Y'/'N' 两值（实测），故 Y→true、N→false，缺失→null（三态，不假定 false）
  const oa = r.isOpenAccess === 'Y' ? true : (r.isOpenAccess === 'N' ? false : null);
  return {
    titleEn: asText(r.title),
    authors: asText(r.authorString),
    source: asText(r.journalInfo && r.journalInfo.journal && r.journalInfo.journal.title) || asText(r.journalTitle),
    year: asYear(r.pubYear),
    abstractEn: stripJats(asText(r.abstractText)),
    citedBy: Number.isFinite(r.citedByCount) ? r.citedByCount : null,
    paperUrl: epmcUrl,
    sourceUrl: doi ? 'https://doi.org/' + doi : epmcUrl,
    doi,
    pmid,
    pmcid,
    oaStatus: oa,
    pubType: Array.isArray(r.pubTypeList && r.pubTypeList.pubType) ? r.pubTypeList.pubType.join('; ') : asText(r.pubType),
  };
}

/**
 * 执行一次检索。
 * @param {object} p { query, limit, keyword, timeoutMs, log }
 * @returns {Promise<{records:Array, diagnostics:object}>}
 */
async function search(p) {
  const o = p || {};
  const limit = Math.max(0, Number(o.limit) || 0);
  const t0 = Date.now();
  const diag = {
    sourceId: 'europepmc',
    url: null,
    pages: 0,
    reportedTotal: null,   // ← 精确命中数（EPMC 的 hitCount），供 classifyCount 三态判定
    noResultsSignal: false,
    aborted: null,
    countSemantics: 'exact',
    durationMs: 0,
  };
  const records = [];

  if (!o.query) { diag.aborted = 'empty_query'; diag.durationMs = 0; return { records, diagnostics: diag }; }

  const pageSize = Math.min(Math.max(limit, 1), PAGE_CAP);
  let cursor = '*';
  // limit=0 是「计数探针」模式：只取 1 条以确认通道可用，但 reportedTotal 才是交付物
  const want = limit === 0 ? 1 : limit;

  try {
    while (records.length < want) {
      const params = {
        query: o.query,
        format: 'json',
        resultType: 'core',
        pageSize,
        cursorMark: cursor,
      };
      const url = BASE + '?' + qs(params);
      diag.url = url;
      const res = await fetchJson(url, { timeoutMs: o.timeoutMs || 25000, maxAttempts: 3 });
      if (!res.ok) {
        // 失败方向必须明确：reportedTotal 保持 null ⇒ 三态判 collect_failed，不冒充 0 命中
        diag.aborted = 'source_error:' + res.kind + (res.status ? ':HTTP' + res.status : '') + ':' + String(res.error || '').slice(0, 120);
        break;
      }
      const j = res.json || {};
      const hc = Number(j.hitCount);
      if (Number.isFinite(hc)) diag.reportedTotal = hc;
      if (hc === 0) { diag.noResultsSignal = true; break; }   // 站点明确说 0 条 ⇒ 真 0（有效证据）

      const list = (j.resultList && Array.isArray(j.resultList.result)) ? j.resultList.result : [];
      diag.pages++;
      if (!list.length) { diag.aborted = 'empty_page'; break; }

      for (const r of list) {
        if (records.length >= want) break;
        const raw = mapOne(r);
        if (!raw.titleEn) continue;    // 无标题记录对证据表无价值，直接丢弃（isUsable 判据同源）
        const rec = canonicalRecord(raw, {
          keyword: o.keyword,
          idx: records.length + 1,
          page: diag.pages,
          sourceId: 'europepmc',
          sourceLabel: 'Europe PMC',
          rank: records.length + 1,
          countSemantics: 'exact',
        });
        records.push(rec);
      }

      const next = asText(j.nextCursorMark);
      // 终止条件三选一：没有下一页 / 游标不再前进（EPMC 在末页会回传同一个游标，不判会死循环）
      if (!next || next === cursor) break;
      cursor = next;
      if (o.log) o.log('source_page', { source: 'europepmc', page: diag.pages, got: records.length, total: diag.reportedTotal });
    }
  } catch (e) {
    diag.aborted = 'exception:' + String(e).slice(0, 160);
  }
  diag.durationMs = Date.now() - t0;
  return { records, diagnostics: diag };
}

/** 供注册表读取的能力声明（契约校验会对照此表，见 sources/index.cjs） */
const meta = {
  id: 'europepmc',
  label: 'Europe PMC',
  kind: 'http',
  queryDialect: 'boolean',
  countSemantics: 'exact',
  capabilities: {
    abstract: true, doi: true, oa: true, pmid: true, pmcid: true,
    citedBy: true, pubType: true, translate: false, fulltextHint: true,
  },
  notes: '布尔式直传；裸词为全字段匹配（含全文），命中数天然大于站点源，PRISMA 须按源分行不可相加',
};

module.exports = { ...meta, search, mapOne };
