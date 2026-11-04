#!/usr/bin/env node
/* eslint-disable */
/**
 * lib/extract.cjs — 页面条目提取层（多策略降级链 + 字段自检）
 *
 * 拆分原因：站点使用 Tailwind/构建产物类名（wl-* / line-clamp-*），随时可能变化。
 * 提取层必须与编排层解耦，才能在类名失效时按策略快速切换，且可离线单测。
 *
 * 三条策略（自动降级，绝不静默产出空字段）:
 *   A 类名选择器（实测定稿） → B 结构位置推断 → C 纯文本正则切分
 * 每条策略都返回填充率，编排层据此判定「提取成功 / 降级 / 结构失效」。
 */
'use strict';

const nbsp = s => (s || '').replace(/ /g, ' ');

/**
 * ⚠ 序列化陷阱（2026-10-04 实踩）：以下提取函数会被 page.evaluate 序列化到浏览器上下文执行，
 * 必须自包含——不得引用模块作用域的函数/常量（如模块级 nbsp），否则页面内 ReferenceError，
 * 且异常会被上层 catch 吞掉，表现为「成功返回但 0 条」。故每个函数内部各自定义 nb()。
 */
/** 策略 A：按实测类名选择器提取（kuluer 2026-10-04 定稿） */
function extractBySelector() {
  const nbsp = s => (s || '').replace(/ /g, ' ');
  const arts = [...document.querySelectorAll('article[id^="r-"]')];
  return arts.map(a => {
    const h2 = a.querySelector('h2');
    const links = h2 ? [...h2.querySelectorAll('a')] : [];
    const titleLink = links[0] || null;
    const origLink = links.find(x =>
      (x.getAttribute('title') || '').includes('打开原文') ||
      (x.getAttribute('aria-label') || '').includes('打开原文')) || null;
    const bylineEl = h2 ? h2.nextElementSibling : null;
    const snippetEl = a.querySelector('p[class*="line-clamp"]');
    const citedEl = a.querySelector('a[href*="cites="]');
    const panel = a.querySelector('[class*="wl-ai-surface"]');
    let titleZh = null, abstractZh = null;
    if (panel) {
      const t = nbsp(panel.innerText || '');
      const m = t.match(/标题\s*\n+(.+?)\s*\n+\s*摘要节选：\s*\n?([\s\S]*)$/);
      if (m) { titleZh = m[1].trim() || null; abstractZh = m[2].trim() || null; }
    }
    return {
      id: a.id,
      titleEn: titleLink ? nbsp(titleLink.innerText).trim() : (h2 ? nbsp(h2.innerText).trim() : null),
      paperHref: titleLink ? titleLink.href : null,
      sourceUrl: origLink ? origLink.href : null,
      byline: bylineEl ? nbsp(bylineEl.innerText).trim() : null,
      abstractEn: snippetEl ? nbsp(snippetEl.innerText).trim() : null,
      citedBy: citedEl ? (() => { const m = citedEl.innerText.match(/(\d+)/); return m ? parseInt(m[1], 10) : null; })() : null,
      titleZh, abstractZh,
    };
  });
}

/** 策略 B：类名失效时，按条目内文本块的位置与形态推断 */
function extractByStructure() {
  const nbsp = s => (s || '').replace(/\u00a0/g, ' ');
  const arts = [...document.querySelectorAll('article[id^="r-"], article')];
  return arts.map((a, i) => {
    const blocks = nbsp(a.innerText || '').split(/\n+/).map(s => s.trim()).filter(Boolean);
    if (!blocks.length) return { id: a.id || ('b-' + i), titleEn: null, byline: null, abstractEn: null };
    const bylineIdx = blocks.findIndex(b => /\s-\s/.test(b));
    const cited = (a.innerText.match(/被引\s*(\d+)/) || [])[1] || null;
    // 标题 = 作者行之前的最后一个块（通常是标题；无作者行则取首块）
    const titleEn = bylineIdx > 0 ? blocks[bylineIdx - 1] : blocks[0];
    // 摘要 = 作者行之后、被引之前的最长块
    const rest = bylineIdx >= 0 ? blocks.slice(bylineIdx + 1) : blocks.slice(1);
    const abstractEn = rest.filter(b => !/^被引/.test(b) && !/个版本/.test(b)).sort((x, y) => y.length - x.length)[0] || null;
    const linkEl = a.querySelector('a[href^="/paper/"], h2 a');
    return {
      id: a.id || ('b-' + i),
      titleEn: titleEn || null,
      paperHref: linkEl ? linkEl.href : null,
      sourceUrl: null,
      byline: bylineIdx >= 0 ? blocks[bylineIdx] : null,
      abstractEn,
      citedBy: cited ? parseInt(cited, 10) : null,
      titleZh: null, abstractZh: null,
    };
  });
}

/** 在页面上下文中按策略名执行，返回 {items, strategy, fillRate} */
async function extractWithFallback(page, { titleFillThreshold = 0.6 } = {}) {
  const strategies = [
    ['selector', extractBySelector],
    ['structure', extractByStructure],
  ];
  let last = null;
  for (const [name, fn] of strategies) {
    let items = [], err = null;
    try { items = await page.evaluate(fn); } catch (e) { err = String(e).slice(0, 200); items = []; }
    if (!Array.isArray(items)) { err = err || 'non-array result'; items = []; }
    const fr = fillRate(items);
    last = { items, strategy: name, fillRate: fr, error: err };
    // 标题填充率达标即采用；否则继续降级
    if (items.length && fr.title >= titleFillThreshold) return last;
  }
  return last || { items: [], strategy: 'none', fillRate: { title: 0, byline: 0, abstract: 0 } };
}

/** 字段填充率（0~1），用于静默降级防护 */
function fillRate(items) {
  if (!items || !items.length) return { title: 0, byline: 0, abstract: 0 };
  const n = items.length;
  const c = k => items.filter(it => it && typeof it[k] === 'string' && it[k].trim().length > 0).length;
  return { title: +(c('titleEn') / n).toFixed(3), byline: +(c('byline') / n).toFixed(3), abstract: +(c('abstractEn') / n).toFixed(3) };
}

/** 作者-来源-年份行解析：「作者 - 来源, 年份 - 域名」 */
function parseByline(s) {
  const empty = { authors: null, source: null, year: null, domain: null };
  if (!s) return empty;
  const parts = nbsp(s).split(/\s+-\s+/).map(x => x.trim()).filter(Boolean);
  if (!parts.length) return empty;
  const authors = parts[0];
  let mid = '', domain = null;
  if (parts.length >= 3) { mid = parts.slice(1, -1).join(' - '); domain = parts[parts.length - 1]; }
  else if (parts.length === 2) { mid = parts[1]; }
  const ym = mid.match(/(\d{4})/);
  const year = ym ? parseInt(ym[1], 10) : null;
  const source = mid.replace(/,?\s*\d{4}\s*$/, '').trim() || null;
  return { authors, source, year, domain };
}

/** 从原文直链抽取 DOI（实测覆盖率约 20%，仅作可选补强） */
const DOI_RE = /10\.\d{4,9}\/[-._;()/:A-Za-z0-9]+/i;
function extractDoi(url) {
  if (!url) return null;
  const m = String(url).match(DOI_RE);
  return m ? m[0].replace(/[.,;)\]]+$/, '') : null;
}

// ---------- v4.7：站点 AI 翻译「失败态」识别（纯函数，离线可测） ----------
/**
 * ⚠ 背景（2026-10-16 一手实测，受控 A/B 追因所得）：站点翻译面板**出现**≠**翻译成功**。
 * `/api/ai/translate` 返回 429 时，站点自己渲染「✦ AI 翻译 · 中文 / 翻译失败 / 重试」，
 * 而旧实现只 `waitForFunction` 等 `[class*="wl-ai-surface"]` 元素出现便返回 true
 * ⇒ 每条记录都被记为「站点译文=是」，与报告头「中文填充率 0%」并存 —— **动作级假阳性**。
 *
 * 修法（两层分离，避免把真值绑死在站点文案上）：
 *   ① 面板文本分类（本函数）—— 仅作**诊断**用，站点改文案时最多标签失真，不影响真值；
 *   ② `hasSiteTranslation(rec)` —— **权威真值**：该条是否真的带译文，与站点文案无关。
 */
const TRANSLATE_FAIL_RE = /翻译失败|重试/;

/** 把页面上面板文本分类：ok / partial_failed / all_failed / no_panel */
function classifyTranslatePanel(texts) {
  const arr = (Array.isArray(texts) ? texts : [])
    .map(t => String(t == null ? '' : t).replace(/\s+/g, ' ').trim())
    .filter(Boolean);
  if (!arr.length) return { status: 'no_panel', n: 0, failed: 0 };
  const failed = arr.filter(t => TRANSLATE_FAIL_RE.test(t)).length;
  if (failed === arr.length) return { status: 'all_failed', n: arr.length, failed };
  if (failed > 0) return { status: 'partial_failed', n: arr.length, failed };
  return { status: 'ok', n: arr.length, failed: 0 };
}

/** 记录级权威判据：该条是否真的拿到了站点译文（不看站点文案，只看有无译文） */
function hasSiteTranslation(rec) {
  if (!rec) return false;
  const ok = v => typeof v === 'string' && v.trim().length > 0;
  return ok(rec.titleZh) || ok(rec.abstractZh);
}

module.exports = {
  extractWithFallback, extractBySelector, extractByStructure, fillRate, parseByline, extractDoi,
  classifyTranslatePanel, hasSiteTranslation, TRANSLATE_FAIL_RE,
};
