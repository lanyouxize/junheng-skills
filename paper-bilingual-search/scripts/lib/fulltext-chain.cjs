'use strict';
/**
 * 全文四级回退链（v4.15 / B 批）。
 *
 * 动因（一手实测，2026-10-26）：
 *   v4.14 的全文通道只有**一条路** —— 拿 enrich.pmcid 打 `EPMC/{pmcid}/fullTextXML`。
 *   上次 15 篇实测只成功 6 篇，因为：
 *     ① 6 篇只有 DOI、没有 pmcid ⇒ 连入口都进不了（noPmcid 静默跳过）；
 *     ② 9 篇有 pmcid 里 3 篇 `fullTextXML` 返回 500（不在 OA 全文子集）⇒ 全灭。
 *
 * 四级顺序与「为什么是这个顺序」：
 *   T1  EPMC JATS XML     —— 唯一能给**结构化**章节的通道，能定位方法学节 ⇒ 最优
 *   T2  PMC/EPMC 正文 HTML —— 实测三篇只有 HTML（B2/C1/D1），正文可读但无章节标记
 *   T3  Unpaywall 定位 OA  —— 覆盖「不在 PMC 但在出版商免费」的情形（bronze/gold/green）
 *   T4  出版商页（浏览器） —— 实测 Wiley/Elsevier 的 Cloudflare 在 headless 与 headed 下**都过不去**，
 *                             保留这一级是为了「明确登记被挡」，而不是假装能拿
 *
 * 三个必须守住的判据（都来自踩过的坑）：
 *   1. **抓到内容 ≠ 抓到该文内容**。挑战页（`Just a moment...`）、导航页、相关文章列表
 *      都有几千词，光看字数会全判成功 ⇒ 必须做「标题实词命中」校验。
 *   2. **Unpaywall 对占位邮箱返回 422 而不是 200**（`example.com` 被显式拉黑，
 *      message: "Please use your own email address"）⇒ 必须与「真的没有 OA」区分开，
 *      否则使用者会以为整条链坏了。
 *   3. **给得出链接 ≠ 下得下来**。Unpaywall 给 9 个 PDF 链接，实测只有 Cambridge 真的回 `%PDF`，
 *      Wiley/Elsevier/MDPI 全 403 ⇒ PDF 只登记「可访问性探测结果」，不冒充已获取全文。
 */

const fs = require('fs');
const path = require('path');
const { analyzeFullText, xmlToText, extractSignals, findMethodsSpan, decodeEntities } = require('./fulltext.cjs');
const PDFX = require('./pdf-extract.cjs');

// ---------- 常量 ----------

const EPMC_BASE = 'https://www.ebi.ac.uk/europepmc/webservices/rest';
const PMC_ARTICLE = 'https://pmc.ncbi.nlm.nih.gov/articles/';
const UNPAYWALL = 'https://api.unpaywall.org/v2/';
const UA_HTTP = 'paper-bilingual-search/4.15 (+https://kuluer.com)';
const UA_BROWSER = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
  + '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36';

/** 级标识：报告与 summary 里出现，**不得随意改名**（历史产物按此比对） */
const TIER = Object.freeze({
  EPMC_XML: 'T1_epmc_xml',
  PMC_HTML: 'T2_pmc_html',
  PMC_PDF: 'T2b_pmc_pdf',
  UNPAYWALL: 'T3_unpaywall',
  OA_PDF: 'T3b_unpaywall_pdf',
  PUBLISHER: 'T4_publisher',
});

/** 正文容器，按精度降序。实测 PMC 新版页面三者共存，`main-article-body` 最干净 */
const CONTAINERS = [
  { tag: 'section', re: /<section\b[^>]*class="[^"]*main-article-body[^"]*"[^>]*>/i },
  { tag: 'article', re: /<article\b[^>]*>/i },
  { tag: 'main', re: /<main\b[^>]*(?:id="main-content"|role="main")[^>]*>/i },
  { tag: 'main', re: /<main\b[^>]*>/i },
];

/** 需要整段剔除的块（参考文献会把词数灌到几千 ⇒ 让「太短」判据失效） */
const DROP_BLOCKS = [
  { tag: 'section', re: /<section\b[^>]*class="[^"]*(?:ref-list|references)[^"]*"[^>]*>/i },
  { tag: 'div', re: /<div\b[^>]*class="[^"]*(?:ref-list|references)[^"]*"[^>]*>/i },
  { tag: 'nav', re: /<nav\b[^>]*>/i },
  { tag: 'aside', re: /<aside\b[^>]*>/i },
  { tag: 'footer', re: /<footer\b[^>]*>/i },
  { tag: 'header', re: /<header\b[^>]*>/i },
];

/**
 * 拦截页特征。只在 title 与文档前 4KB 内查 —— 正文里出现 CAPTCHA 一词是正常的
 * （有论文研究验证码），全文搜索会制造假阴性。
 */
const CHALLENGE_PATTERNS = [
  /just a moment/i,
  /checking your browser/i,
  /verify (?:you are|that you are) (?:a )?human/i,
  /attention required/i,
  /access denied/i,
  /enable javascript and cookies/i,
  /cf-browser-verification/i,
  /unusual traffic/i,
  /preparing to download/i,
];

/**
 * 正文侧的**强特征**：只保留「正常论文正文几乎不可能出现」的短语。
 * 弱特征（captcha / verify you are human / unusual traffic）故意不放进来 ——
 * 研究验证码或网络流量的论文正文里真的会出现，那会把真全文判成挑战页。
 */
const CHALLENGE_STRONG = [
  /just a moment\.\.\./i,
  /checking your browser/i,
  /cf-browser-verification/i,
  /attention required!?\s*\|?\s*cloudflare/i,
  /enable javascript and cookies to continue/i,
];

const STOP = new Set(['the', 'and', 'for', 'with', 'from', 'that', 'this', 'with', 'into',
  'effects', 'effect', 'study', 'using', 'used', 'their', 'were', 'was', 'are', 'has', 'have']);

// ---------- 纯函数：HTML → 文本 ----------

/**
 * 从 `start` 处的开标签开始，按同名标签深度扫描出完整块。
 * 不能靠非贪婪正则：正文里嵌套同名标签必然提前截断（PMC 页面有很多嵌套 section）。
 * @returns {{html:string, end:number}|null}
 */
function extractBalanced(html, start, tag) {
  const re = new RegExp('</?' + tag + '\\b[^>]*>', 'gi');
  re.lastIndex = start;
  let depth = 0;
  let m;
  while ((m = re.exec(html)) !== null) {
    const isClose = m[0].charAt(1) === '/';
    const isSelf = /\/>$/.test(m[0]);
    if (isClose) {
      depth -= 1;
      if (depth === 0) return { html: html.slice(start, m.index + m[0].length), end: m.index + m[0].length };
    } else if (!isSelf) {
      depth += 1;
    }
  }
  return null;
}

/** 快速估词数（只去标签，不做容器抽取），用于在候选容器之间比较 */
function roughWords(html) {
  const t = String(html || '')
    .replace(/<(script|style|noscript|svg|iframe|template)\b[^>]*>[\s\S]*?<\/\1>/gi, ' ')
    .replace(/<[^>]+>/g, ' ');
  return (t.match(/[A-Za-z]{2,}/g) || []).length;
}

/**
 * 找出正文容器。返回 {html, container} —— container 进 attempts，便于事后核对抽的是哪块。
 *
 * ★ 判据是**正文词数**，不是 HTML 字节数。
 *   初版用 `got.html.length > 400` 判断「这个容器有料」，结果 B2（1960 年老文章）
 *   抽到一个只有 21 字符正文的 `section.main-article-body` 骨架就停了 ——
 *   标签长度够 400，正文只有 4 个词。改用词数后才会继续往下试 `article` / 整页。
 */
function extractMainHtml(html) {
  const src = String(html || '');
  const cands = [];
  for (const c of CONTAINERS) {
    const m = c.re.exec(src);
    if (!m) continue;
    const got = extractBalanced(src, m.index, c.tag);
    if (!got) continue;
    cands.push({
      html: got.html,
      container: c.tag + ':' + m[0].slice(0, 46).replace(/\s+/g, ' '),
      words: roughWords(got.html),
    });
  }
  cands.push({ html: src, container: 'whole_document', words: roughWords(src) });

  // 按优先级取第一个「正文够长」的；都不够才取词数最多的那个（多半是老式整页布局）
  const MIN = 120;
  for (const c of cands) {
    if (c.words >= MIN) return c;
  }
  let best = cands[0];
  for (const c of cands) if (c.words > best.words) best = c;
  return best;
}

/** 整段剔除干扰块（原地反复剔除，因为可能有多处） */
function dropBlocks(html) {
  let out = String(html || '');
  for (const d of DROP_BLOCKS) {
    let guard = 0;
    for (;;) {
      const m = d.re.exec(out);
      if (!m || guard++ > 24) break;
      const got = extractBalanced(out, m.index, d.tag);
      if (!got) break;
      out = out.slice(0, m.index) + ' ' + out.slice(got.end);
    }
  }
  return out;
}

/**
 * HTML → 纯文本。保留段落边界（换行），供 `findMethodsSpan` 按行找章节。
 * 偏移量语义与 T1 一致：文本是落盘载体，signals[].offset 可直接切片回查。
 */
function htmlToText(html) {
  const main = extractMainHtml(html);
  let s = dropBlocks(main.html);
  s = s.replace(/<!--[\s\S]*?-->/g, ' ');
  s = s.replace(/<(script|style|noscript|svg|iframe|template|math)\b[^>]*>[\s\S]*?<\/\1>/gi, ' ');
  s = s.replace(/<\/(p|div|section|article|li|tr|h[1-6]|blockquote|figcaption|td|dd|dt)\s*>/gi, '\n');
  s = s.replace(/<br\s*\/?>/gi, '\n');
  s = s.replace(/<[^>]+>/g, ' ');
  s = decodeEntities(s);
  s = s.replace(/\u00a0/g, ' ');
  s = s
    .split('\n')
    .map(l => l.replace(/[ \t\u00a0]+/g, ' ').trim())
    .filter(l => l.length > 0)
    .join('\n');
  return { text: stripBoilerplate(s), container: main.container };
}

/** 截掉 References 之后的内容（HTML 里有时不是独立 section 而是标题 + 列表） */
function stripRefs(text) {
  const t = String(text || '');
  const m = /^\s*(?:references|bibliography|literature cited|参考文献)\s*$/im.exec(t);
  if (m && m.index > t.length * 0.35) return t.slice(0, m.index);
  return t;
}

/**
 * PMC/NCBI 页面的**固定样板行**，整行匹配才剔除。
 *
 * 为什么需要：老文章的 PMC 页面（如 `www.ncbi.nlm.nih.gov/pmc/articles/1975637`）
 * 结构与新版不同，正文容器套不上，会落到 `whole_document` —— 于是
 * 「Skip to main content」「Official websites use .gov」这类导航混进正文。
 * 实测一篇 1939 年文章 226 词里有约 80 词是这种样板。
 *
 * 用**整行精确匹配**而不是包含匹配：正文句里出现 "search in PMC" 这类词组的
 * 可能性虽低，但整行匹配能把误删风险压到接近零。
 */
const BOILERPLATE_LINES = [
  /^skip to main content$/i,
  /^official websites use \.gov$/i,
  /^an official website of the united states government$/i,
  /^a \.gov website belongs to an official government organization in the united states\.?$/i,
  // 这些是同一段文案被 <span> 拆行后的碎片（老式 PMC 页面常见），逐条整行匹配
  /^\.gov website belongs to an official$/i,
  /^government organization in the united states\.?$/i,
  /^connected to the \.gov website\.?$/i,
  /^secure \.gov websites use https$/i,
  /^a lock \(?$/i,
  /^\)? ?or https:\/\/ means you'?ve safely connected to the \.gov website\.?$/i,
  /^share sensitive information only on official, secure websites\.?$/i,
  /^here'?s how you know$/i,
  /^pmc full-?text archive$/i,
  /^search in pmc$/i,
  /^journal list$/i,
  /^user guide$/i,
  /^permalink$/i,
  /^copy$/i,
  /^as a library, nlm provides access to scientific literature\.?$/i,
  /^inclusion in an nlm database does not imply endorsement of,?$/i,
  /^or agreement with,?$/i,
  /^the contents by nlm or the national institutes of health\.?$/i,
  /^learn more:?$/i,
  /^pmc disclaimer$/i,
  /^pmc copyright notice$/i,
  /^follow nlm$/i,
  /^national library of medicine$/i,
  /^8600 rockville pike$/i,
  /^bethesda,? md,? usa$/i,
];

/** 剔除样板行。只做整行匹配，不做包含匹配（理由见 BOILERPLATE_LINES 注释） */
function stripBoilerplate(text) {
  const lines = String(text || '').split('\n');
  const out = [];
  for (const ln of lines) {
    const s = ln.trim();
    if (s && BOILERPLATE_LINES.some(re => re.test(s))) continue;
    out.push(ln);
  }
  return out.join('\n').replace(/\n{3,}/g, '\n\n').trim();
}

/** 拦截页判定。返回命中的模式字符串，未命中返回 null */
function detectChallenge(title, body) {
  const head = String(body || '').slice(0, 4096);
  const titleS = String(title || '');
  for (const p of CHALLENGE_PATTERNS) {
    if (p.test(titleS) || p.test(head)) return p.source;
  }
  return null;
}

/** 只看正文里的强特征（见 CHALLENGE_STRONG 的取舍说明） */
function detectChallengeStrong(body) {
  const head = String(body || '').slice(0, 4096);
  for (const p of CHALLENGE_STRONG) if (p.test(head)) return p.source;
  return null;
}

/** 标题实词：长度 ≥4 的字母词，去停用词，去重，取前 10 个 */
function significantWords(title) {
  const seen = new Set();
  const out = [];
  for (const w of String(title || '').toLowerCase().match(/[a-z]{4,}/g) || []) {
    if (STOP.has(w) || seen.has(w)) continue;
    seen.add(w);
    out.push(w);
    if (out.length >= 10) break;
  }
  return out;
}

/**
 * ★ 全文真伪闸门：抓到的文本是否真是**该文**的正文。
 *
 * 这是本批最关键的判据。挑战页/导航页/相关文章列表动辄数千词，
 * 只看词数会把它们全判成「已获取全文」—— 那比拿不到更糟（会污染证据表）。
 *
 * @returns {{ok:boolean, reason:string|null, words:number, titleHits:number, titleNeed:number, titleCheck:string}}
 */
function assessText(text, rec, opts) {
  const o = opts || {};
  const minWords = o.minWords || 120;
  const noTitleMinWords = o.noTitleMinWords || 800;
  const t = String(text || '');
  const words = (t.match(/[A-Za-z]{2,}/g) || []).length;
  const tw = significantWords(rec && (rec.titleEn || rec.title));

  // ★ 闸门自身也要能识别挑战页，不能依赖调用方先跑 detectChallenge。
  //   初版把这道检查只放在调用方，于是「标题实词 <3 ⇒ 只看词数」的分支会让
  //   808 词的 Cloudflare 拦截页通过 —— 单测里立刻复现（ok=true）。
  const chal = detectChallengeStrong(t);
  if (chal) {
    return { ok: false, reason: 'challenge_text:' + chal, words, titleHits: 0, titleNeed: 0, titleCheck: 'challenge' };
  }

  // ★ 站点样板页（HTML 级专用）：PMC 对「只有扫描件」的老文献不提供正文，
  //   页面只剩 .gov 声明、导航、引用行。这种页面的标题就在页内，词数也过 120，
  //   于是**骗过了下面的归属校验** —— 实测 B2（1960 年 Can Vet J）227 词里
  //   正文 0 词，却被判 ok。判据取自真实样本对照（不是猜的）：
  //     样板页 散文行占比 0.04、散文行均词 13.3；成功样本 0.11–0.82、40–70。
  //   故「词数 <400 且散文行占比 <10%」判为样板，宁可漏，不可误。
  if (o.chromeCheck) {
    const lines = t.split('\n').map(s => s.trim()).filter(Boolean);
    const prose = lines.filter(l => (l.match(/[A-Za-z]{2,}/g) || []).length >= 8).length;
    const proseRatio = lines.length ? prose / lines.length : 0;
    if (lines.length >= 8 && words < (o.chromeMaxWords || 400) && proseRatio < 0.1) {
      return {
        ok: false, reason: 'page_is_chrome_' + words + 'w_' + Math.round(proseRatio * 100) + 'pct_prose',
        words, titleHits: 0, titleNeed: 0, titleCheck: 'chrome',
      };
    }
  }

  // 需要命中的标题词数：至少 2 个，且不少于标题实词的 40%。
  // 取「且」不取「或」：短文标题只有 3 个实词时，命中 1 个不足以排除同主题的另一篇。
  const need = Math.max(2, Math.ceil(tw.length * 0.4));

  if (tw.length < 3) {
    // 标题缺失或太短 ⇒ 无法做归属校验。此时只能靠更严的词数下限，并显式登记
    // 「未校验归属」，不能假装验过了。
    if (words < noTitleMinWords) {
      return { ok: false, reason: 'no_title_check_below_' + noTitleMinWords + '_words', words, titleHits: 0, titleNeed: need, titleCheck: 'unavailable' };
    }
    return { ok: true, reason: null, words, titleHits: 0, titleNeed: need, titleCheck: 'unavailable' };
  }
  if (words < minWords) {
    return { ok: false, reason: 'too_short_' + words + '_words', words, titleHits: 0, titleNeed: need, titleCheck: 'short_text' };
  }
  const lower = t.toLowerCase();
  const hits = tw.filter(w => lower.indexOf(w) >= 0).length;
  if (hits < need) {
    return { ok: false, reason: 'title_mismatch_hit_' + hits + '_of_' + tw.length, words, titleHits: hits, titleNeed: need, titleCheck: 'mismatch' };
  }
  return { ok: true, reason: null, words, titleHits: hits, titleNeed: need, titleCheck: 'ok' };
}

// ---------- 纯函数：入口与计划 ----------

/** 从记录里取三入口。enrich 优先，顶层兜底（多源通道的记录在顶层） */
function entryOf(rec) {
  const e = (rec && rec.enrich) || {};
  const pick = (...vals) => {
    for (const v of vals) {
      if (v && String(v).trim()) return String(v).trim();
    }
    return null;
  };
  // ★ 三个入口都必须「enrich 优先、顶层兜底」。
  //   多源通道（--sources）的记录 doi/pmcid 在**顶层**、根本没有 enrich；
  //   初版 doi 只写了 pick(e.doi)，于是多源记录的计划恒为空 —— 等于把
  //   「只有 DOI 就进不了全文通道」这个原缺陷原样搬到了新代码里。
  const rawDoi = pick(e.doi, rec && rec.doi);
  return {
    pmcid: pick(e.pmcid, rec && rec.pmcid),
    pmid: pick(e.pmid, rec && rec.pmid),
    doi: rawDoi ? rawDoi.replace(/^https?:\/\/(dx\.)?doi\.org\//i, '') : null,
  };
}

function normPmcid(v) {
  const s = String(v || '').toUpperCase().replace(/[^A-Z0-9]/g, '');
  const m = /^(?:PMC)?(\d+)$/.exec(s);
  return m ? 'PMC' + m[1] : null;
}

/**
 * 生成该记录的回退计划（按优先级）。**纯函数**，离线可测。
 * 无任何入口 ⇒ 返回空数组（调用方据此记 no_entry，不得伪造 tier）。
 */
function planTiers(rec) {
  const e = entryOf(rec);
  const pmcid = normPmcid(e.pmcid);
  const plan = [];
  if (pmcid) {
    plan.push({ tier: TIER.EPMC_XML, transport: 'http', url: EPMC_BASE + '/' + pmcid + '/fullTextXML', entry: 'pmcid' });
    plan.push({ tier: TIER.PMC_HTML, transport: 'http', url: PMC_ARTICLE + pmcid + '/', entry: 'pmcid' });
    plan.push({ tier: TIER.PMC_HTML, transport: 'browser', url: PMC_ARTICLE + pmcid + '/', entry: 'pmcid' });
    // ★ T2b：PMC 的 PDF 兜底。只在前面几级都拿不到正文时才走到这里 —— 实测
    //   PMC 对「只有扫描件」的老文献不提供 HTML 正文（页面只剩引用与站点样板），
    //   但 PDF 里有 OCR 文字层。PDF 路由带 PoW 人机校验，必须走浏览器（页面自己
    //   会解），所以 transport 是 browser。
    plan.push({ tier: TIER.PMC_PDF, transport: 'browser', url: PMC_ARTICLE + pmcid + '/pdf/', entry: 'pmcid' });
  }
  if (e.doi) {
    plan.push({ tier: TIER.UNPAYWALL, transport: 'http', url: UNPAYWALL + encodeURIComponent(e.doi) + '?email=' + '%EMAIL%', entry: 'doi' });
    plan.push({ tier: TIER.PUBLISHER, transport: 'browser', url: 'https://doi.org/' + e.doi, entry: 'doi' });
  }
  return plan;
}

/**
 * Unpaywall 错误分类。**这条判据来自实测踩坑**：
 * `example.com` 被官方黑名单，返回 422 + "Please use your own email address"，
 * 若不与「真的没有 OA」区分，整条 T3 会静默失效且看起来像端点挂了。
 */
function classifyUnpaywallError(status, body) {
  const b = String(body || '');
  if (status === 200) return 'ok';
  if (status === 404) return 'doi_not_found';
  if (status === 422 && /own email address/i.test(b)) return 'placeholder_email';
  if (status === 422 && /email address required/i.test(b)) return 'email_required';
  if (status === 422) return 'bad_request';
  if (status === 429) return 'rate_limited';
  return 'http_' + status;
}

/** T3 成功时挑一个可访问的 OA URL，机构库优先（机构库一般不做反爬） */
function pickOaTarget(payload) {
  const locs = (payload && payload.oa_locations) || [];
  const reps = locs.filter(l => l && l.host_type === 'repository');
  const others = locs.filter(l => l && l.host_type !== 'repository');
  for (const l of reps.concat(others)) {
    const u = l.url_for_pdf || l.url;
    if (u) return { url: u, host: l.host_type || 'unknown', license: l.license || null, version: l.version || null };
  }
  const best = (payload && payload.best_oa_location) || {};
  const u = best.url_for_pdf || best.url;
  return u ? { url: u, host: best.host_type || 'unknown', license: best.license || null, version: best.version || null } : null;
}

/** 把尝试序列压成一句人话（报告与 summary 共用，避免两处各算一遍） */
function summarizeAttempts(attempts) {
  const list = Array.isArray(attempts) ? attempts : [];
  return list.map(a => a.tier + '@' + a.transport + '=' + a.result + (a.reason ? '(' + a.reason + ')' : '')).join(' -> ');
}

/**
 * 失败原因取「最后一个**实质尝试**」的原因，不能取最后一条 attempt。
 *
 * 为什么单独抽成纯函数：浏览器级被跳过时最后一条是 `skipped(browser_disabled)`，
 * 用它当总原因会把「真的没有 OA」误报成「只是没开浏览器」——
 * 15 篇实测里 6 篇都这样被误导（A1/A7/A8/C4 明明是 closed）。
 * 抽出来才能离线锁死这条判据，不必真的跑一遍网络。
 */
function pickFailureReason(attempts) {
  const list = Array.isArray(attempts) ? attempts : [];
  const substantive = list.filter(a => a && a.result !== 'skipped');
  const last = substantive.length ? substantive[substantive.length - 1] : (list[list.length - 1] || {});
  return last.reason || last.result || 'all_tiers_failed';
}

/**
 * 某一级是否该直接跳过。目前只有一条：T3 已判定「无 OA 版本」时跳过 T4。
 * closed 文章的出版商页必然要订阅/登录，浏览器也看不到正文；
 * 实测对 4 篇 closed 各白跑一次 45s 超时，换 0 条。
 */
function shouldSkipTier(step, state) {
  const st = state || {};
  if (step && step.tier === TIER.PUBLISHER && st.oaUnavailable) return 'oa_not_available';
  return null;
}

// ---------- IO：HTTP ----------

async function httpGet(url, opts) {
  const o = opts || {};
  const timeoutMs = o.timeoutMs || 25000;
  const want = o.want || 1024 * 1024;
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeoutMs);
  try {
    const r = await fetch(url, {
      signal: ctl.signal,
      redirect: 'follow',
      headers: {
        'User-Agent': o.ua || UA_HTTP,
        Accept: o.accept || 'application/xml, text/xml, text/html, application/json, application/pdf, */*',
        ...(o.email ? { From: o.email } : {}),
      },
    });
    const buf = Buffer.from(await r.arrayBuffer());
    return {
      status: r.status,
      contentType: r.headers.get('content-type') || '',
      finalUrl: r.url || url,
      body: buf.subarray(0, want),
      bytes: buf.length,
    };
  } catch (e) {
    const aborted = e && e.name === 'AbortError';
    return { status: 0, contentType: '', finalUrl: url, body: Buffer.alloc(0), bytes: 0, error: aborted ? 'timeout' : String((e && e.message) || e).slice(0, 120) };
  } finally {
    clearTimeout(timer);
  }
}

function looksXml(buf) {
  const head = buf.subarray(0, 400).toString('utf8').replace(/^\uFEFF/, '').trim();
  return /^<\?xml|^<article\b|^<PMC/.test(head);
}

function looksHtml(buf) {
  const head = buf.subarray(0, 400).toString('utf8').toLowerCase().trim();
  return /^<!doctype html|^<html/.test(head);
}

// ---------- IO：浏览器（惰性） ----------

let _pw = null;
let _pwTried = false;

/** 惰性加载；**失败返回 null 而不 exit**（全文链是可降级步骤，不该拖死整批） */
function loadPlaywrightSoft() {
  if (_pwTried) return _pw;
  _pwTried = true;
  const os = require('os');
  const wsPath = path.join(os.homedir(), '.workbuddy', 'binaries', 'node', 'workspace', 'node_modules', 'playwright-core');
  for (const load of [() => require('playwright-core'), () => require(wsPath)]) {
    try { _pw = load(); return _pw; } catch (e) { /* next */ }
  }
  return null;
}

function findBrowserSoft() {
  const cands = [
    process.env.WB_BROWSER_PATH,
    'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
    'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  ].filter(Boolean);
  for (const p of cands) { try { if (fs.existsSync(p)) return p; } catch (e) { /* next */ } }
  return null;
}

async function openBrowser(opts) {
  const pw = loadPlaywrightSoft();
  if (!pw) return { ok: false, reason: 'playwright_not_installed' };
  const exe = findBrowserSoft();
  if (!exe) return { ok: false, reason: 'no_browser_binary' };
  const browser = await pw.chromium.launch({
    executablePath: exe,
    headless: (opts && opts.headless) !== false,
    args: ['--disable-gpu', '--no-first-run', '--disable-blink-features=AutomationControlled'],
  });
  const ctx = await browser.newContext({ userAgent: UA_BROWSER, locale: 'en-US', viewport: { width: 1280, height: 900 } });
  return { ok: true, browser, ctx };
}

/** 用浏览器取页面 HTML。JS 挑战要给它时间（实测 PMC 的 reCAPTCHA 约 3–6s 过） */
async function browserFetchHtml(ctx, url, opts) {
  const o = opts || {};
  const page = await ctx.newPage();
  try {
    const resp = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: o.timeoutMs || 45000 });
    const status = resp ? resp.status() : 0;
    await new Promise(r => setTimeout(r, o.settleMs == null ? 6000 : o.settleMs));
    let title = '';
    try { title = await page.title(); } catch (e) { title = ''; }
    const html = await page.content();
    return { status, title, html, finalUrl: page.url() };
  } catch (e) {
    return { status: 0, title: '', html: '', error: String((e && e.message) || e).slice(0, 120) };
  } finally {
    await page.close().catch(() => {});
  }
}

// ---------- 各级执行 ----------

/** T1：EPMC JATS XML */
async function tryEpmcXml(url, rec, opts) {
  const r = await httpGet(url, { timeoutMs: opts.timeoutMs, accept: 'application/xml,text/xml,*/*' });
  if (r.status === 404) return { ok: false, result: 'no_fulltext', reason: 'not_in_oa_subset' };
  if (r.status === 500) return { ok: false, result: 'no_fulltext', reason: 'upstream_500_not_in_oa_subset' };
  if (r.status !== 200) return { ok: false, result: 'failed', reason: 'http_' + r.status };
  if (!looksXml(r.body)) return { ok: false, result: 'not_xml', reason: 'response_not_jats' };
  const xml = r.body.toString('utf8');
  const analyzed = analyzeFullText(xml);
  const text = xmlToText(xml);
  const gate = { ok: true, words: (text.match(/[A-Za-z]{2,}/g) || []).length, titleCheck: 'not_needed_structured' };
  return { ok: true, tier: TIER.EPMC_XML, source: 'epmc_fulltext_xml', text, structured: true, analyzed, gate, bytes: r.bytes };
}

/** T2：PMC/EPMC 正文 HTML（http 或 browser） */
async function tryPmcHtml(url, rec, opts, ctx) {
  let html = '';
  let title = '';
  let status = 0;
  if (ctx && ctx.transport === 'browser') {
    if (!ctx.browser || !ctx.browser.ok) return { ok: false, result: 'skipped', reason: (ctx.browser && ctx.browser.reason) || 'browser_unavailable' };
    const got = await browserFetchHtml(ctx.browser.ctx, url, opts);
    html = got.html; title = got.title; status = got.status;
    if (got.error) return { ok: false, result: 'failed', reason: 'browser:' + got.error };
  } else {
    const r = await httpGet(url, { timeoutMs: opts.timeoutMs, accept: 'text/html,*/*' });
    status = r.status;
    if (status !== 200) return { ok: false, result: status === 0 ? 'failed' : 'blocked', reason: r.error || ('http_' + status) };
    html = r.body.toString('utf8');
    const m = /<title[^>]*>([\s\S]*?)<\/title>/i.exec(html);
    title = m ? m[1].replace(/\s+/g, ' ').trim() : '';
  }
  const chal = detectChallenge(title, html);
  if (chal) return { ok: false, result: 'blocked', reason: 'js_challenge:' + chal };
  if (!looksHtml(Buffer.from(html.slice(0, 400)))) {
    return { ok: false, result: 'not_html', reason: 'response_not_html' };
  }
  const conv = htmlToText(html);
  const text = stripRefs(conv.text);
  const gate = assessText(text, rec, Object.assign({}, opts, { chromeCheck: true }));
  if (!gate.ok) return { ok: false, result: 'rejected', reason: gate.reason, gate, container: conv.container };
  return { ok: true, tier: TIER.PMC_HTML, source: 'pmc_html', text, structured: false, gate, container: conv.container, title: title.slice(0, 120) };
}

/**
 * 用浏览器取 PDF 字节。
 *
 * PMC 的 PDF 路由返回的是 **proof-of-work 挑战页**（`POW_DIFFICULTY=4`，
 * cookie 名 `cloudpmc-viewer-pow`），由页面自己的 JS 解出。本模块**只负责
 * 让页面正常执行**，绝不自己手写 PoW 求解器去绕过站点的人机校验 —— 那属于
 * 规避访问控制，不是「浏览器打开一个网页」。
 *
 * 三步（缺一步都拿不到，实测）：
 *   1. 先开文章页建立同源上下文（页面 URL 变成 about:blank 后再 fetch 会被 403）
 *   2. 再开 pdf 路由触发 PoW，等同源 cookie 落地
 *   3. 回文章页执行 `fetch(pdfUrl)` —— 只有页面内同源请求才带得上那套头
 */
async function browserFetchPdfBytes(bctx, articleUrl, pdfUrl, opts) {
  const o = opts || {};
  const page = await bctx.newPage();
  try {
    await page.goto(articleUrl, { waitUntil: 'domcontentloaded', timeout: o.timeoutMs || 45000 }).catch(() => {});
    const title = await page.title().catch(() => '');
    await page.goto(pdfUrl, { waitUntil: 'domcontentloaded', timeout: Math.min(o.timeoutMs || 45000, 30000) }).catch(() => {});

    let powSeen = false;
    for (let i = 0; i < 25; i += 1) {
      let cookies = [];
      try { cookies = await bctx.cookies('https://pmc.ncbi.nlm.nih.gov'); } catch (e) { cookies = []; }
      if (cookies.some(c => c.name === 'cloudpmc-viewer-pow' && c.value)) { powSeen = true; break; }
      await new Promise(r => setTimeout(r, 1000));
    }

    await page.goto(articleUrl, { waitUntil: 'domcontentloaded', timeout: o.timeoutMs || 45000 }).catch(() => {});
    const got = await page.evaluate(async (u) => {
      try {
        const r = await fetch(u, { credentials: 'include' });
        const ct = r.headers.get('content-type') || '';
        const buf = new Uint8Array(await r.arrayBuffer());
        if (buf.length > 40 * 1024 * 1024) return { status: r.status, ct, tooBig: buf.length };
        let bin = '';
        const CH = 0x8000;
        for (let i = 0; i < buf.length; i += CH) bin += String.fromCharCode.apply(null, buf.subarray(i, i + CH));
        return { status: r.status, ct, len: buf.length, b64: btoa(bin) };
      } catch (e) {
        return { err: String((e && e.message) || e) };
      }
    }, pdfUrl);

    if (got.err) return { error: String(got.err).slice(0, 120), title, powSeen };
    if (got.tooBig) return { error: 'pdf_too_big_' + got.tooBig, title, powSeen };
    return { status: got.status, contentType: got.ct || '', bytes: Buffer.from(got.b64 || '', 'base64'), title, powSeen };
  } catch (e) {
    return { error: String((e && e.message) || e).slice(0, 120), title: '', powSeen: false };
  } finally {
    await page.close().catch(() => {});
  }
}

/** T2b：PMC PDF（扫描件 + OCR 文字层）—— HTML 拿不到正文时的兜底 */
async function tryPmcPdf(url, rec, opts, ctx) {
  if (!ctx || !ctx.browser || !ctx.browser.ok) {
    return { ok: false, result: 'skipped', reason: (ctx && ctx.browser && ctx.browser.reason) || 'browser_unavailable' };
  }
  const articleUrl = String(url).replace(/pdf\/$/, '');
  const got = await browserFetchPdfBytes(ctx.browser.ctx, articleUrl, url, opts);
  if (got.error) return { ok: false, result: 'failed', reason: 'browser:' + got.error };
  if (!PDFX.isPdf(got.bytes)) {
    return { ok: false, result: got.status === 403 ? 'blocked' : 'not_pdf', reason: 'pdf_response_not_pdf_' + (got.status || 0) };
  }
  const ext = PDFX.extractPdfText(got.bytes, { minWords: opts.pdfMinWords || 120 });
  if (!ext.ok) return { ok: false, result: 'pdf_rejected', reason: ext.reason, pdfStats: ext.stats };
  const gate = assessText(ext.text, rec, Object.assign({}, opts, { chromeCheck: false }));
  if (!gate.ok) return { ok: false, result: 'rejected', reason: gate.reason, gate, pdfStats: ext.stats };
  return {
    ok: true, tier: TIER.PMC_PDF, source: 'pmc_pdf', text: ext.text, structured: false,
    gate, title: String(got.title || '').slice(0, 120), bytes: got.bytes.length, pdfStats: ext.stats,
  };
}

/** T3：Unpaywall 定位 → 探测可访问性（**不冒充已获取**） */
async function tryUnpaywall(url, rec, opts) {
  if (!opts.email) return { ok: false, result: 'skipped', reason: 'no_email' };
  const finalUrl = url.replace('%EMAIL%', encodeURIComponent(opts.email));
  const r = await httpGet(finalUrl, { timeoutMs: opts.timeoutMs, accept: 'application/json' });
  const cls = classifyUnpaywallError(r.status, r.body.toString('utf8'));
  if (cls === 'placeholder_email') {
    return { ok: false, result: 'config_error', reason: 'unpaywall_rejects_placeholder_email', hint: '请用真实邮箱（example.com 等占位域名被官方拉黑）' };
  }
  if (cls === 'email_required') return { ok: false, result: 'config_error', reason: 'unpaywall_requires_email' };
  if (cls !== 'ok') return { ok: false, result: cls === 'rate_limited' ? 'rate_limited' : 'failed', reason: cls };

  let payload = null;
  try { payload = JSON.parse(r.body.toString('utf8')); } catch (e) { return { ok: false, result: 'failed', reason: 'bad_json' }; }
  const tgt = pickOaTarget(payload);
  if (!tgt) return { ok: false, result: 'no_oa', reason: 'is_oa=' + String(payload.is_oa) + ',status=' + String(payload.oa_status) };

  // 探测目标可访问性：给了链接不等于下得下来（实测 9 个链接只有 1 个真回 %PDF）
  const probe = await httpGet(tgt.url, { timeoutMs: Math.min(opts.timeoutMs || 25000, 20000), accept: 'application/pdf,text/html,*/*' });
  const isPdf = probe.body.subarray(0, 5).toString('latin1') === '%PDF-';
  const isHtmlOk = probe.status === 200 && looksHtml(probe.body);
  const oaInfo = {
    url: tgt.url, host: tgt.host, license: tgt.license, version: tgt.version,
    oaStatus: payload.oa_status, reachable: probe.status === 200, isPdf,
    httpStatus: probe.status, contentType: (probe.contentType || '').slice(0, 60),
  };

  if (isHtmlOk) {
    // 落地页是 HTML ⇒ 当作可能的全文页来抽（机构库常这样），但仍要过归属闸门
    const conv = htmlToText(probe.body.toString('utf8'));
    const text = stripRefs(conv.text);
    const gate = assessText(text, rec, Object.assign({}, opts, { chromeCheck: true }));
    if (gate.ok) {
      return { ok: true, tier: TIER.UNPAYWALL, source: 'unpaywall_html', text, structured: false, gate, oaInfo, container: conv.container };
    }
    return { ok: false, result: 'oa_page_not_fulltext', reason: gate.reason, gate, oaInfo };
  }
  if (isPdf) {
    // ★ v4.15 C 批：PDF 不再只是「登记可下载」。零依赖抽取 + 归属闸门都过，
    //   才算已获取全文；抽不动就**照旧只登记**，绝不拿半截乱码冒充正文。
    const full = await httpGet(tgt.url, {
      timeoutMs: Math.min(opts.timeoutMs || 25000, 30000),
      accept: 'application/pdf,*/*',
      want: 40 * 1024 * 1024,
    });
    const ext = PDFX.extractPdfText(full.body, { minWords: opts.pdfMinWords || 120 });
    if (ext.ok) {
      const gate = assessText(ext.text, rec, Object.assign({}, opts, { chromeCheck: false }));
      if (gate.ok) {
        return {
          ok: true, tier: TIER.OA_PDF, source: 'unpaywall_pdf', text: ext.text, structured: false,
          gate, oaInfo, pdfStats: ext.stats, bytes: full.bytes,
        };
      }
      return { ok: false, result: 'pdf_rejected', reason: gate.reason, gate, oaInfo, pdfStats: ext.stats };
    }
    return { ok: false, result: 'pdf_only', reason: 'pdf_' + ext.reason, oaInfo, pdfStats: ext.stats };
  }
  return { ok: false, result: probe.status === 0 ? 'unreachable' : 'blocked', reason: 'probe_http_' + probe.status, oaInfo };
}

/** T4：出版商页（浏览器）—— 实测多数是 Cloudflare，保留是为了登记被挡 */
async function tryPublisher(url, rec, opts, ctx) {
  if (!ctx || !ctx.browser || !ctx.browser.ok) {
    return { ok: false, result: 'skipped', reason: (ctx && ctx.browser && ctx.browser.reason) || 'browser_unavailable' };
  }
  const got = await browserFetchHtml(ctx.browser.ctx, url, opts);
  if (got.error) return { ok: false, result: 'failed', reason: 'browser:' + got.error };
  const chal = detectChallenge(got.title, got.html);
  if (chal) return { ok: false, result: 'blocked', reason: 'js_challenge:' + chal };
  const conv = htmlToText(got.html);
  const text = stripRefs(conv.text);
  const gate = assessText(text, rec, Object.assign({}, opts, { chromeCheck: true }));
  if (!gate.ok) return { ok: false, result: 'rejected', reason: gate.reason, gate };
  return { ok: true, tier: TIER.PUBLISHER, source: 'publisher_html', text, structured: false, gate, title: String(got.title).slice(0, 120) };
}

// ---------- 记录级解析 ----------

/**
 * 按计划逐级尝试，第一个通过真伪闸门的即为结果。**不因某级失败而中止**。
 * @returns {Promise<{ok:boolean, plan:Array, attempts:Array, hit?:object}>}
 */
async function resolveFulltext(rec, opts, ctx) {
  const plan = planTiers(rec);
  const attempts = [];
  if (!plan.length) return { ok: false, plan, attempts, reason: 'no_entry' };
  // T3 已明确说「无 OA 版本」时，T4 不必再试：closed 文章的出版商页必然要订阅/登录，
  // 浏览器也看不到正文。实测对 4 篇 closed 各白跑一次 45s 超时，换 0 条。
  let oaUnavailable = false;
  for (const step of plan) {
    const skipWhy = shouldSkipTier(step, { oaUnavailable });
    if (skipWhy) {
      attempts.push({ tier: step.tier, transport: step.transport, result: 'skipped', reason: skipWhy });
      continue;
    }
    if (step.transport === 'browser' && !(opts.allowBrowser && ctx && ctx.browser && ctx.browser.ok)) {
      attempts.push({ tier: step.tier, transport: step.transport, result: 'skipped', reason: opts.allowBrowser ? 'browser_unavailable' : 'browser_disabled' });
      continue;
    }
    let res;
    try {
      if (step.tier === TIER.EPMC_XML) res = await tryEpmcXml(step.url, rec, opts);
      else if (step.tier === TIER.PMC_HTML) res = await tryPmcHtml(step.url, rec, opts, { transport: step.transport, browser: ctx && ctx.browser });
      else if (step.tier === TIER.PMC_PDF) res = await tryPmcPdf(step.url, rec, opts, ctx);
      else if (step.tier === TIER.UNPAYWALL) res = await tryUnpaywall(step.url, rec, opts);
      else res = await tryPublisher(step.url, rec, opts, ctx);
    } catch (e) {
      res = { ok: false, result: 'failed', reason: 'exception:' + String((e && e.message) || e).slice(0, 80) };
    }
    attempts.push({
      tier: step.tier, transport: step.transport, result: res.result || (res.ok ? 'ok' : 'failed'),
      reason: res.reason || null, url: step.url.replace('%EMAIL%', opts.email ? '***' : '%EMAIL%'),
      ...(res.container ? { container: res.container } : {}),
      ...(res.gate ? { gate: res.gate } : {}),
      ...(res.pdfStats ? { pdfStats: res.pdfStats } : {}),
      ...(res.oaInfo ? { oaInfo: res.oaInfo } : {}),
      ...(res.hint ? { hint: res.hint } : {}),
    });
    if (res.ok) return { ok: true, plan, attempts, hit: res };
    if (step.tier === TIER.UNPAYWALL && res.result === 'no_oa') oaUnavailable = true;
  }
  // ★ 失败原因取「最后一个**实质尝试**的原因」，不能取最后一条 attempt。
  //   浏览器级被跳过时最后一条是 skipped(browser_disabled)，用它当总原因会把
  //   「真的没有 OA」误报成「只是没开浏览器」—— 实测 15 篇里 6 篇都这样被误导。
  return { ok: false, plan, attempts, reason: pickFailureReason(attempts) };
}

function safeSlug(s) {
  return String(s || '').replace(/[^A-Za-z0-9._-]+/g, '_').slice(0, 60) || 'rec';
}

/** 落盘文件名：有 pmcid 用 PMCID（与 v4.14 产物同名，历史报告仍可对上），否则用 DOI */
function textFileNameFor(rec, entry) {
  const pmcid = normPmcid(entry.pmcid);
  if (pmcid) return pmcid + '.txt';
  if (entry.doi) return 'doi_' + safeSlug(entry.doi) + '.txt';
  return 'idx_' + safeSlug(rec && rec.idx) + '.txt';
}

/**
 * 批处理入口（两阶段）。
 *
 * Phase A：只用 HTTP 跑全部目标 —— 绝大多数命中在这一阶段结束，**不启动浏览器**。
 * Phase B：仅对 Phase A 失败、且允许浏览器、且计划里还有 browser 级的目标，启动**一次**浏览器统一处理。
 *
 * 这样 `--sources` 通道在全文全 HTTP 可得时不会拉起浏览器（保持 A-2 的承诺）。
 */
async function runFulltextChain(records, opts) {
  const o = opts || {};
  if (!o.outDir) throw new Error('runFulltextChain 需要 outDir');
  const list = Array.isArray(records) ? records : [];
  const dir = path.join(o.outDir, 'fulltext');
  fs.mkdirSync(dir, { recursive: true });

  const stat = {
    records: list.length,
    withEntry: 0, noEntry: 0,
    byEntry: { pmcid: 0, doiOnly: 0, both: 0 },
    ok: 0, cached: 0, failed: 0,
    byTier: {}, byStatus: {}, bytes: 0,
    browserUsed: false, browserReason: null,
    oaFound: 0, pdfOnly: 0,
    // 兼容字段：assemble-report 的旧分支读 withPmcid / noPmcid / oaWithoutPmcid。
    // 新链里「无 pmcid 也能走 doi」⇒ oaWithoutPmcid 这个概念已失效，恒为 0，
    // 报告层改用 byTier 呈现（见 assemble-report 的新分支）。
    withPmcid: 0, noPmcid: 0, oaWithoutPmcid: 0,
  };

  // 目标：有任一入口即入列，但**计数语义要说清**（旧版把 noPmcid 静默跳过）
  const targets = [];
  for (const rec of list) {
    const entry = entryOf(rec);
    const has = !!(normPmcid(entry.pmcid) || entry.doi);
    if (!has) { stat.noEntry += 1; continue; }
    stat.withEntry += 1;
    if (normPmcid(entry.pmcid) && entry.doi) stat.byEntry.both += 1;
    else if (normPmcid(entry.pmcid)) stat.byEntry.pmcid += 1;
    else stat.byEntry.doiOnly += 1;
    if (normPmcid(entry.pmcid)) stat.withPmcid += 1;
    targets.push({ rec, entry, file: textFileNameFor(rec, entry) });
  }
  stat.noPmcid = stat.records - stat.withPmcid;

  // 缓存：txt + json 同时存在才复用（只 txt 说明上次中途失败）
  const pending = [];
  for (const t of targets) {
    const txtPath = path.join(dir, t.file);
    const jsonPath = path.join(dir, t.file.replace(/\.txt$/, '.json'));
    if (o.cache !== false && fs.existsSync(txtPath) && fs.existsSync(jsonPath)) {
      try {
        const saved = JSON.parse(fs.readFileSync(jsonPath, 'utf8'));
        t.rec.fulltext = {
          status: 'ok', cached: true, tier: saved.tier || TIER.EPMC_XML, source: saved.source || 'cache',
          pmcid: normPmcid(t.entry.pmcid) || null,
          chars: saved.chars, methods: saved.methods || null, signals: saved.signals || [],
          signalsInMethods: saved.signalsInMethods || 0, textFile: t.file,
          gate: saved.gate || null, attempts: saved.attempts || [],
        };
        stat.cached += 1;
        stat.ok += 1;
        bump(stat.byTier, saved.tier || 'cache');
        continue;
      } catch (e) { /* 缓存坏了重抓 */ }
    }
    pending.push(t);
  }

  const ctx = { browser: null };
  const apply = async (t, res) => {
    const { rec, entry, file } = t;
    if (!res.ok) {
      rec.fulltext = {
        status: res.reason === 'no_entry' ? 'no_entry' : 'not_available',
        tier: null, pmcid: normPmcid(entry.pmcid) || null,
        attempts: res.attempts, reason: res.reason || null,
      };
      stat.failed += 1;
      bump(stat.byStatus, res.reason || 'failed');
      for (const a of res.attempts || []) {
        if (a.oaInfo) stat.oaFound += 1;
        if (a.result === 'pdf_only') stat.pdfOnly += 1;
      }
      return;
    }
    const hit = res.hit;
    const analyzed = hit.structured
      ? hit.analyzed
      : { chars: hit.text.length, methods: findMethodsSpan(hit.text), signals: extractSignals(hit.text, findMethodsSpan(hit.text)), signalsInMethods: 0 };
    if (!hit.structured) {
      analyzed.signalsInMethods = (analyzed.signals || []).filter(s => s.scope === 'methods').length;
    }
    const txtPath = path.join(dir, file);
    const jsonPath = path.join(dir, file.replace(/\.txt$/, '.json'));
    fs.writeFileSync(txtPath, hit.text, 'utf8');
    fs.writeFileSync(jsonPath, JSON.stringify({
      tier: hit.tier, source: hit.source, chars: analyzed.chars, methods: analyzed.methods,
      signals: analyzed.signals, signalsInMethods: analyzed.signalsInMethods,
      gate: hit.gate, attempts: res.attempts, fetchedAt: new Date().toISOString(),
      ...(hit.oaInfo ? { oaInfo: hit.oaInfo } : {}), ...(hit.pdfStats ? { pdfStats: hit.pdfStats } : {}),
      ...(hit.container ? { container: hit.container } : {}),
      ...(hit.title ? { pageTitle: hit.title } : {}),
    }, null, 2), 'utf8');

    rec.fulltext = {
      status: 'ok', cached: false, tier: hit.tier, source: hit.source,
      pmcid: normPmcid(entry.pmcid) || null,
      chars: analyzed.chars,
      methods: analyzed.methods ? { title: analyzed.methods.title, chars: analyzed.methods.chars } : null,
      signals: (analyzed.signals || []).map(s => ({
        key: s.key, label: s.label, scope: s.scope, offset: s.offset, length: s.length, matched: s.matched,
      })),
      signalsInMethods: analyzed.signalsInMethods || 0,
      textFile: file,
      gate: hit.gate || null,
      structured: !!hit.structured,
      attempts: res.attempts,
      ...(hit.oaInfo ? { oaInfo: hit.oaInfo } : {}), ...(hit.pdfStats ? { pdfStats: hit.pdfStats } : {}),
    };
    stat.ok += 1;
    stat.bytes += hit.bytes || Buffer.byteLength(hit.text, 'utf8');
    bump(stat.byTier, hit.tier);
  };

  // ---- Phase A：纯 HTTP ----
  const runPool = async (items, fn, conc) => {
    let cursor = 0;
    const n = Math.max(1, Math.min(Number(conc) || 1, 4));
    await Promise.all(Array.from({ length: n }, async () => {
      while (cursor < items.length) {
        const item = items[cursor++];
        await fn(item);
        if (o.intervalMs) await new Promise(r => setTimeout(r, o.intervalMs));
      }
    }));
  };

  const deferred = [];
  await runPool(pending, async (t) => {
    const resA = await resolveFulltext(t.rec, { ...o, allowBrowser: false }, ctx);
    if (resA.ok) { await apply(t, resA); return; }
    // 计划里还有 browser 级 ⇒ 留到 Phase B
    const hasBrowser = (resA.plan || []).some(s => s.transport === 'browser');
    if (hasBrowser && o.allowBrowser !== false) deferred.push({ t, resA });
    else await apply(t, resA);
  }, o.concurrency);

  // ---- Phase B：浏览器（只一次启动） ----
  if (deferred.length) {
    ctx.browser = await openBrowser(o);
    stat.browserUsed = !!ctx.browser.ok;
    stat.browserReason = ctx.browser.ok ? null : ctx.browser.reason;
    if (ctx.browser.ok) {
      await runPool(deferred, async (d) => {
        const resB = await resolveFulltext(d.t.rec, { ...o, allowBrowser: true }, ctx);
        await apply(d.t, resB.ok ? resB : { ...d.resA, attempts: resB.attempts, reason: resB.reason });
      }, 1);                                  // 浏览器串行：并发会触发更多风控
      await ctx.browser.browser.close().catch(() => {});
    } else {
      for (const d of deferred) {
        await apply(d.t, {
          ...d.resA,
          attempts: (d.resA.attempts || []).concat([{ tier: 'browser', transport: 'browser', result: 'skipped', reason: ctx.browser.reason }]),
          reason: d.resA.reason,
        });
      }
    }
  }

  return { stat, dir };
}

function bump(obj, key) {
  if (!key) return;
  obj[key] = (obj[key] || 0) + 1;
}

module.exports = {
  TIER, EPMC_BASE, PMC_ARTICLE, UNPAYWALL, UA_HTTP, UA_BROWSER,
  CHALLENGE_PATTERNS, CHALLENGE_STRONG,
  extractBalanced, extractMainHtml, dropBlocks, htmlToText, stripRefs, stripBoilerplate, BOILERPLATE_LINES,
  detectChallenge, detectChallengeStrong, roughWords,
  significantWords, assessText, entryOf, normPmcid, planTiers,
  findMethodsSpan, extractSignals,
  classifyUnpaywallError, pickOaTarget, summarizeAttempts, pickFailureReason, shouldSkipTier, textFileNameFor,
  resolveFulltext, runFulltextChain, openBrowser, browserFetchHtml,
  browserFetchPdfBytes, tryPmcPdf,
};
