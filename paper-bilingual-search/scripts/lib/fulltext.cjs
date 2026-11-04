#!/usr/bin/env node
/* eslint-disable */
/**
 * lib/fulltext.cjs — Europe PMC 全文通道（可选，默认关闭）
 *
 * 存在的理由：摘要级判定拿不到两样东西 ——
 *   · **设计与统计的原文**（随机化/盲法/交叉/洗脱/统计方法），决定 evidence 能否从 B 升 A；
 *   · **资助方与 COI**，决定结论该被读多重。
 * 实测 `PMC13255985`（Animals 2026，膳食钾）全文 113KB，JATS XML，`license: cc by` —— 免费可取。
 *
 * ⚠ 三条纪律:
 *   1. **只补信息，不改等级**。本模块不产出、也不允许产出 evidenceLevel；
 *      分级仍由 `evidence.cjs` 的启发式候选给出，全文只是人读的材料。抓取失败**绝不**降级。
 *   2. **偏移量必须可回查**。`textOffset` 相对于 `xmlToText()` 的产物，而该产物会原样落盘为
 *      `fulltext/<pmcid>.txt` ⇒ 用 offset 直接在 txt 里切片，必须逐字等于 JSON 里的片段。
 *      因此文本化规则必须单一：抽取与回查共用同一个 `xmlToText()`，不得各写一套。
 *   3. **体积**：113KB XML / 篇，只落盘文本化后的 `.txt`（约 30KB），不存原始 XML。
 *
 * 零第三方依赖：XML 用轻量文本化（不追求通用解析器），HTTP 用 Node 内置 fetch。
 */
'use strict';

const EPMC_FULLTEXT = 'https://www.ebi.ac.uk/europepmc/webservices/rest';

/** 方法学信号表：键名稳定，报告与 JSON 都用它。命中首个即可，不做语义判断。 */
const SIGNALS = [
  { key: 'randomization', re: /randomi[sz]ation|randomi[sz]ed|randomi[sz]e\b|randomly (assigned|allocated|divided)/i, label: '随机化' },
  { key: 'allocation_concealment', re: /allocation conceal/i, label: '分配隐藏' },
  { key: 'blinding', re: /\bblin(ded|ding|d)\b/i, label: '盲法' },
  { key: 'crossover', re: /cross-?over/i, label: '交叉设计' },
  { key: 'washout', re: /wash-?out/i, label: '洗脱期' },
  { key: 'sample_size', re: /sample size|number of animals|animals were (randomly )?assigned/i, label: '样本量/分组' },
  // 只认「统计方法」本身。**不含 p 值**：p 值属结果而非方法，且它在方法学节里也常先出现
  // （实测会命中「body weight 5.11 ± 0.41 kg (p = 0.3)」这种描述），把设计信息挤掉。
  { key: 'statistics', re: /\bstatistical (analysis|analyses|methods?|significance)|an?a?lysis of variance|\banova\b|mixed[- ]effects?|t-test|chi-?square|non-?parametric|normality test/i, label: '统计方法' },
  { key: 'control_group', re: /control group|placebo|negative control/i, label: '对照组' },
  { key: 'repeated_measures', re: /repeated measures|latin square/i, label: '重复测量/拉丁方' },
];

const HEADING_MAX = 64;          // 超过这个长度就不当标题（避免正文句子被误判）
const CONTEXT_CHARS = 120;       // 片段上下文半径

// 节标题常带编号（"2. Materials and Methods" / "3. Results"），锚点必须容忍前导编号，
// 否则结束检测永远不命中 ⇒ 方法学节会一路吞到文末（实测踩过）。
const HEAD_METHODS = /^(\d+(\.\d+)*\.?\s*)?(materials?\s*(and|&)\s*methods?|methods?|methodology)\b/i;
const HEAD_END = /^(\d+(\.\d+)*\.?\s*)?(results?|discussion|conclusions?|references)\b/i;

/** 实体解码。`&amp;` 必须最后处理，否则 `&amp;lt;` 会被二次解码成 `<`。 */
function decodeEntities(s) {
  const safeChar = (n) => {
    try { return Number.isFinite(n) && n > 0 && n <= 0x10ffff ? String.fromCodePoint(n) : ''; }
    catch (e) { return ''; }
  };
  return s
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&nbsp;/g, ' ')
    .replace(/&#x([0-9a-f]+);/gi, (_, h) => safeChar(parseInt(h, 16)))
    .replace(/&#(\d+);/g, (_, d) => safeChar(parseInt(d, 10)))
    .replace(/&amp;/g, '&');
}

/**
 * JATS XML → 纯文本。**抽取与回查共用此函数**，任何规范化改动都会让历史 offset 失效，
 * 故改动它等同于一次数据格式迁移（需同步重抓）。
 */
function xmlToText(xml) {
  let s = String(xml || '');
  s = s.replace(/<\?[\s\S]*?\?>/g, ' ');
  s = s.replace(/<!--[\s\S]*?-->/g, ' ');
  s = s.replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, '$1');
  s = s.replace(/<(script|style)\b[\s\S]*?<\/\1>/gi, ' ');
  // 段落/标题边界换行：保留结构，否则方法学节标题与正文粘连，无法按行判标题
  s = s.replace(/<\/(p|title|sec|abstract|article-title|caption)>/gi, '\n');
  s = s.replace(/<[^>]+>/g, ' ');
  s = decodeEntities(s);
  s = s.replace(/\r\n?/g, '\n');
  s = s.replace(/[ \t\u00a0]+/g, ' ');     // 压横向空白（不动换行）
  s = s.replace(/\n{3,}/g, '\n\n');        // 压多余空行
  return s.trim();
}

/** 逐行索引（行首 offset + 行文本），供按「短行=标题」判定节边界。 */
function indexLines(text) {
  const out = [];
  let off = 0;
  for (const line of text.split('\n')) {
    out.push({ off, line });
    off += line.length + 1;
  }
  return out;
}

/**
 * 定位「材料与方法」节区间。找不到返回 null —— **不猜**（宁可在报告里写「未定位到方法学节」，
 * 也不要拿 Introduction 的片段冒充方法学）。
 */
function findMethodsSpan(text) {
  const lines = indexLines(text);
  const isHeading = (t) => t.length > 0 && t.length <= HEADING_MAX;
  let start = -1;
  for (let i = 0; i < lines.length; i++) {
    const t = lines[i].line.trim();
    if (isHeading(t) && HEAD_METHODS.test(t)) { start = i; break; }
  }
  if (start < 0) return null;
  let end = lines.length;
  for (let i = start + 1; i < lines.length; i++) {
    const t = lines[i].line.trim();
    if (isHeading(t) && HEAD_END.test(t)) { end = i; break; }
  }
  const startOff = lines[start].off;
  const endOff = end < lines.length ? lines[end].off : text.length;
  return {
    title: lines[start].line.trim(),
    start: startOff,
    end: endOff,
    chars: endOff - startOff,
  };
}

/**
 * 抽取方法学信号。**方法学节内优先**：同一关键词在摘要里出现、也在方法学节里出现时，
 * 取方法学节那处 —— 实测「cross-over」首次出现在 Abstract（off=1974），而真正定义设计的是
 * Methods 里的描述；只取全文首个命中会把摘要当方法学用。
 * 方法学节内没有时才退到全文首个，并如实标 scope='body'（不冒充方法学）。
 */
function extractSignals(text, methodsSpan) {
  const out = [];
  for (const sig of SIGNALS) {
    let base = 0;
    let hit = null;
    let scope = 'body';
    if (methodsSpan && methodsSpan.end > methodsSpan.start) {
      const m = sig.re.exec(text.slice(methodsSpan.start, methodsSpan.end));
      if (m) { hit = m; base = methodsSpan.start; scope = 'methods'; }
    }
    if (!hit) {
      const m = sig.re.exec(text);
      if (!m) continue;
      hit = m;
      base = 0;
    }
    const offset = base + hit.index;
    const len = hit[0].length;
    const from = Math.max(0, offset - CONTEXT_CHARS);
    const to = Math.min(text.length, offset + len + CONTEXT_CHARS);
    out.push({
      key: sig.key,
      label: sig.label,
      matched: hit[0],
      scope,
      offset,
      length: len,
      context: text.slice(from, to).replace(/\n+/g, ' ').trim(),
    });
  }
  return out;
}

/** 一次给全文摘要（不落盘、不抓取）。 */
function analyzeFullText(xml) {
  const text = xmlToText(xml);
  const methods = findMethodsSpan(text);
  const signals = extractSignals(text, methods);
  return {
    chars: text.length,
    methods,
    signals,
    signalsInMethods: signals.filter(s => s.scope === 'methods').length,
  };
}

/**
 * 抓取全文 XML。
 * @returns {Promise<{status:string, xml?:string, bytes?:number, error?:string}>}
 *   status: ok | error:404 | error:429 | error:timeout | error:http_<n> | error:<msg>
 */
async function fetchFullText(pmcid, { timeoutMs = 25000, retries = 1 } = {}) {
  if (!pmcid || !/^PMC\d+$/.test(String(pmcid))) {
    return { status: 'error:bad_pmcid', error: 'pmcid 形如 PMC13255985，实际 ' + JSON.stringify(pmcid) };
  }
  const url = EPMC_FULLTEXT + '/' + pmcid + '/fullTextXML';
  let lastErr = '';
  for (let i = 0; i <= retries; i++) {
    let timer = null;
    try {
      const ctl = new AbortController();
      timer = setTimeout(() => ctl.abort(), timeoutMs);
      const r = await fetch(url, { signal: ctl.signal, headers: { 'User-Agent': 'paper-bilingual-search/1.0' } });
      if (timer) clearTimeout(timer);
      if (r.status === 429) { lastErr = 'error:429'; await new Promise(s => setTimeout(s, 1500 * (i + 1))); continue; }
      if (r.status === 404) return { status: 'error:404', error: '该 pmcid 无全文 XML（常见于未进 PMC 或仅摘要）' };
      if (!r.ok) { lastErr = 'error:http_' + r.status; continue; }
      const xml = await r.text();
      // 防御：有些 404 页面会以 200 返回 HTML
      if (!/^\s*<\?xml|<article\b/i.test(xml)) {
        return { status: 'error:not_xml', error: '响应不是 JATS XML（前 60 字符：' + xml.slice(0, 60).replace(/\s+/g, ' ') + '）' };
      }
      return { status: 'ok', xml, bytes: Buffer.byteLength(xml, 'utf8') };
    } catch (e) {
      if (timer) clearTimeout(timer);
      lastErr = (e && e.name === 'AbortError') ? 'error:timeout' : 'error:' + String(e && e.message || e).slice(0, 80);
      if (i === retries) break;
      await new Promise(s => setTimeout(s, 1200 * (i + 1)));
    }
  }
  return { status: lastErr || 'error:unknown', error: lastErr };
}

/**
 * 批量抓全文并落盘。
 *
 * 产物（`<outDir>/fulltext/`）：
 *   · `<pmcid>.txt`  文本化全文 —— **偏移量的回查载体**（用 signals[].offset 直接切片即可核对）
 *   · `<pmcid>.json` 抽取结果（含完整 context）
 * records 里只回填摘要（不含 context，避免把 records JSON 撑大）。
 *
 * 幂等：txt 与 json 同时存在 ⇒ 直接读回摘要并计入 skippedCached，不重复下载 113KB。
 * **失败不改任何等级**：只把 `fulltext.status` 写进记录，evidence 分级完全不读它。
 */
async function runFulltextBatch(records, opts = {}) {
  const fs = require('fs');
  const path = require('path');
  const { outDir, concurrency = 2, intervalMs = 400, timeoutMs = 25000 } = opts;
  if (!outDir) throw new Error('runFulltextBatch 需要 outDir');

  const dir = path.join(outDir, 'fulltext');
  fs.mkdirSync(dir, { recursive: true });

  const targets = [];
  (records || []).forEach((r) => {
    const e = (r && r.enrich) || {};
    if (e.pmcid) targets.push({ rec: r, pmcid: e.pmcid });
  });

  const stat = {
    records: (records || []).length,
    withPmcid: targets.length,
    noPmcid: (records || []).length - targets.length,
    // ★ 矛盾态单列：报告说 isOA=true 却没有 pmcid ⇒ 已知「开放获取」但拿不到全文入口。
    //  这不等于「无 pmcid」的普通情形，必须在报告里明写，否则会让人以为全文通道已覆盖它。
    oaWithoutPmcid: (records || []).filter((r) => {
      const e = (r && r.enrich) || {};
      return e.isOA === true && !e.pmcid;
    }).length,
    ok: 0, cached: 0, failed: 0, bytes: 0, byStatus: {},
  };

  const brief = (pmcid, analyzed, txtName) => ({
    pmcid,
    chars: analyzed.chars,
    methods: analyzed.methods ? { title: analyzed.methods.title, chars: analyzed.methods.chars } : null,
    signals: analyzed.signals.map(s => ({
      key: s.key, label: s.label, scope: s.scope, offset: s.offset, length: s.length, matched: s.matched,
    })),
    signalsInMethods: analyzed.signalsInMethods,
    textFile: txtName,
  });

  // 串行化调度：每次在飞的请求数不超过 concurrency；结果按 targets 顺序落位
  let cursor = 0;
  const worker = async () => {
    while (cursor < targets.length) {
      const item = targets[cursor++];
      const txtName = item.pmcid + '.txt';
      const txtPath = path.join(dir, txtName);
      const jsonPath = path.join(dir, item.pmcid + '.json');

      // 缓存命中：两件产物都在才复用（只有 txt 没 json 说明上次中途失败，重抓）
      if (fs.existsSync(txtPath) && fs.existsSync(jsonPath)) {
        try {
          const saved = JSON.parse(fs.readFileSync(jsonPath, 'utf8'));
          item.rec.fulltext = Object.assign({ status: 'ok', cached: true }, brief(item.pmcid, {
            chars: saved.chars,
            methods: saved.methods ? { title: saved.methods.title, chars: saved.methods.chars } : null,
            signals: saved.signals || [],
            signalsInMethods: saved.signalsInMethods || 0,
          }, txtName));
          stat.cached++;
          stat.byStatus.cached = (stat.byStatus.cached || 0) + 1;
          if (typeof opts.onItem === 'function') opts.onItem(item.rec, stat);
          continue;
        } catch (e) { /* 缓存坏了就走下面的重抓 */ }
      }

      const r = await fetchFullText(item.pmcid, { timeoutMs });
      if (r.status !== 'ok') {
        item.rec.fulltext = { status: r.status, error: r.error || null, pmcid: item.pmcid };
        stat.failed++;
        stat.byStatus[r.status] = (stat.byStatus[r.status] || 0) + 1;
        if (typeof opts.onItem === 'function') opts.onItem(item.rec, stat);
        if (intervalMs) await new Promise(s => setTimeout(s, intervalMs));
        continue;
      }

      const analyzed = analyzeFullText(r.xml);
      const text = xmlToText(r.xml);          // 与 analyze 内部同一函数，保证 offset 可回查
      fs.writeFileSync(txtPath, text, 'utf8');
      fs.writeFileSync(jsonPath, JSON.stringify({
        pmcid: item.pmcid,
        bytes: r.bytes,
        fetchedAt: new Date().toISOString(),
        chars: analyzed.chars,
        methods: analyzed.methods,
        signals: analyzed.signals,
        signalsInMethods: analyzed.signalsInMethods,
      }, null, 2), 'utf8');

      // ★ status 必须在**成功路径**也写：报告层按 `r.fulltext.status === 'ok'` 决定是否展示
      //   方法学信号。初版只在缓存路径写了 status，成功路径漏了 ⇒ 新抓的记录反而不显示信号
      //   （自测只覆盖失败路径时抓不到这个洞，靠真实端到端才暴露）。
      item.rec.fulltext = Object.assign({ status: 'ok', cached: false }, brief(item.pmcid, analyzed, txtName));
      stat.ok++;
      stat.bytes += r.bytes;
      if (typeof opts.onItem === 'function') opts.onItem(item.rec, stat);
      if (intervalMs) await new Promise(s => setTimeout(s, intervalMs));
    }
  };

  const n = Math.max(1, Math.min(Number(concurrency) || 1, 4));
  await Promise.all(Array.from({ length: n }, worker));
  return { stat, dir };
}

module.exports = {
  SIGNALS, EPMC_FULLTEXT,
  xmlToText, decodeEntities, findMethodsSpan, extractSignals, analyzeFullText, fetchFullText, runFulltextBatch,
};
