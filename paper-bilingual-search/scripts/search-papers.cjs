#!/usr/bin/env node
/* eslint-disable */
/**
 * search-papers.cjs — 论文检索·中英对照 Skill 主脚本（v4.15）
 *
 * 通道:
 *   kuluer  (默认) https://kuluer.com/scholar?q=<kw>&hl=zh-CN
 *           —— xs.essclick.com 的搜索后端；实测无验证拦截，自带「翻译本页结果」AI 译文。
 *   panda985     https://sc.panda985.com/scholar?q=<kw>&hl=zh-CN
 *           —— 实测搜索结果页触发站内图片点选验证（/verify_gate）：有头窗口内由用户手动完成，
 *              脚本轮询等待；绝不识别、绝不绕过。
 *              ⚠️ **本版本未接通**：`--site panda985` 会在输入层直接报错退出（v4.1 起），
 *              不再静默回落 kuluer——避免 summary/PRISMA 的 site 元数据与实际抓取源不一致。
 *
 * 依赖: playwright-core（托管 Node 工作区）+ 本机 Edge/Chrome。
 * 运行: NODE_PATH="<用户目录>\.workbuddy\binaries\node\workspace\node_modules"（脚本已按 os.homedir() 自动探测）
 *       node search-papers.cjs --keywords "词1" "词2" --limit 10 --out <目录> [--headless]
 *            [--enrich] [--dedupe] [--fill-min 0.9] [--keyword-timeout 300]
 *       （`--dir` 与 `--out` 等价；参数校验 / 关键词归一 / 文件读取见 lib/cli.cjs）
 *
 * 退出码: 0 成功 / 2 验证等待超时（部分结果已保留） / 3 疑似结构变化 /
 *         4 质量自检未通过（成功但字段大面积缺失 = 静默降级，必须显式失败） / 5 疑似站点侧不可用 / 1 其他错误
 *         ⚠️ `--limit 0`（计数探针：只取站点自报命中、不抓条目）**不适用填充率 QC**，故不会以码 4 结束（v4.6）。
 */
'use strict';

const fs = require('fs');
const path = require('path');
const { extractWithFallback, parseByline, extractDoi, fillRate, classifyTranslatePanel, hasSiteTranslation } = require('./lib/extract.cjs');
const { enrichAll, dedupe, qcCheck } = require('./lib/enrich.cjs');
// v4.15（B 批）：全文四级回退链。取代「只认 pmcid + 只打 EPMC fullTextXML」的单通道。
// fulltext.cjs 的 runFulltextBatch 仍保留在库里（单测与历史产物比对在用），主流程不再调用它。
const { runFulltextChain } = require('./lib/fulltext-chain.cjs');
const { gradeAll } = require('./lib/evidence.cjs');
const { buildLog, writeLog } = require('./lib/prisma.cjs');
// v4.15（A-2）：多源 HTTP 通道的聚合层（纯函数：记录组归一 / 计数语义分流 / 多源探针 / PRISMA 行）
const MR = require('./lib/multi-run.cjs');
const { runSources } = require('./lib/scheduler.cjs');
// 计数探针三态（counted / zero_confirmed / collect_failed）：把 null 拆成「没读到」与「真 0」
const { classifyCount, attachProbe, probeSummaryLine } = require('./lib/probe.cjs');
const {
  CliError, resolveInputs, ensureDir, kwIndexName, slug, describeKeywordSources, describeSources,
} = require('./lib/cli.cjs');

function loadPlaywright() {
  const os = require('os');
  const wsPath = path.join(os.homedir(), '.workbuddy', 'binaries', 'node', 'workspace', 'node_modules', 'playwright-core');
  const candidates = [
    () => require('playwright-core'),
    () => require(wsPath),
  ];
  for (const c of candidates) { try { return c(); } catch (e) { /* next */ } }
  console.error('[FATAL] 找不到 playwright-core。请先安装：');
  console.error(`  cd ${path.join(os.homedir(), '.workbuddy', 'binaries', 'node', 'workspace')} && npm install playwright-core`);
  process.exit(1);
}
// v4.15（A-2）：playwright 改为**惰性**加载。
// 旧写法在模块顶层 require 并在缺失时 process.exit(1) —— 即使跑的是 --sources 多源 HTTP 通道
// （根本不用浏览器）也起不来，等于把「无 Edge/Chrome 的 CI 环境」挡在门外。
let _chromium = null;
function chromium() {
  if (!_chromium) _chromium = loadPlaywright().chromium;
  return _chromium;
}

const BROWSER_CANDIDATES = [
  process.env.WB_BROWSER_PATH,
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
].filter(Boolean);
function findBrowser() {
  for (const p of BROWSER_CANDIDATES) { try { if (fs.existsSync(p)) return p; } catch (e) {} }
  console.error('[FATAL] 未找到 Edge/Chrome；可用 WB_BROWSER_PATH 环境变量指定');
  process.exit(1);
}

const TOOL_VERSION = 'paper-bilingual-search/v4.15';

// 参数解析 / 关键词归一 / 文件通道 / 输出目录准备 已抽到 lib/cli.cjs，
// 目的是让「输入层」第一次变成可离线单测的纯逻辑（v3 时它埋在 439 行主脚本里，测不到）。
// 入口只负责：resolveInputs → 打印 notices → 校验关键词非空 → 准备输出目录。

const sleep = ms => new Promise(r => setTimeout(r, ms));
const rand = ([a, b]) => Math.floor(a + Math.random() * (b - a + 1));
const log = (event, data) => console.log(JSON.stringify({ ts: new Date().toISOString(), event, ...data }));

// ---------- 人机验证：只检测，绝不绕过 ----------
const GATE_RE = /安全验证|请点击(图片|文字)|verify_gate|Just a moment|Attention Required|验证您是真人|人机验证|Checking your browser/;
async function detectGate(page) {
  try {
    if (/verify_gate/.test(page.url())) return '站内验证页(verify_gate)';
    const head = (await page.evaluate(() => (document.body ? document.body.innerText : '')).catch(() => '')).slice(0, 2500);
    const m = head.match(GATE_RE);
    return m ? '页面出现验证文案:「' + m[0] + '」' : null;
  } catch (e) { return null; }
}
async function waitGate(page, keyword, gateTimeoutSec) {
  const reason = await detectGate(page);
  if (!reason) return true;
  log('gate_detected', { keyword, reason, url: page.url(), hint: '请在浏览器窗口手动完成验证；脚本等待，不尝试绕过' });
  const deadline = Date.now() + gateTimeoutSec * 1000;
  while (Date.now() < deadline) {
    await sleep(2000);
    if (!(await detectGate(page))) { log('gate_cleared', { keyword }); return true; }
  }
  return false;
}

async function clickTranslate(page) {
  const clicked = await page.evaluate(() => {
    const els = [...document.querySelectorAll('button, a, div[role="button"], span, div')];
    const btn = els.find(e => (e.innerText || '').trim().replace(/\s/g, '') === '翻译本页结果');
    if (btn) { btn.click(); return true; }
    return false;
  });
  if (!clicked) return { status: 'no_button', panels: null };
  try {
    await page.waitForFunction(() => !!document.querySelector('[class*="wl-ai-surface"]'), { timeout: 20000 });
    await sleep(1500);
  } catch (e) { return { status: 'panel_timeout', panels: null }; }
  // ★ v4.7：面板**出现** ≠ 翻译**成功**。站点 /api/ai/translate 失败（实测 429）时，
  // 面板自渲染「翻译失败 / 重试」，而旧实现只等元素出现即返回 true ⇒ 每条记录被记为
  // 「站点译文=是」，与报告头「中文填充率 0%」并存（动作级假阳性）。
  // 此处只做**诊断性**分类（分类失败不影响真值）；记录级真值一律由 hasSiteTranslation() 判定，
  // 故站点改文案最多让 status 标签失真，**不会**把「没译文」误报成「有译文」。
  let panels = null;
  try {
    const texts = await page.evaluate(() => [...document.querySelectorAll('[class*="wl-ai-surface"]')]
      .map(e => (e.innerText || '').slice(0, 200)));
    panels = classifyTranslatePanel(texts);
  } catch (e) { panels = { status: 'panel_unreadable', n: 0, failed: 0, error: String(e).slice(0, 120) }; }
  return { status: panels.status, panels };
}

async function gotoWithRetry(page, url, retries) {
  let lastErr = null;
  for (let i = 0; i <= retries; i++) {
    try {
      const resp = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
      if (resp && resp.status() >= 500) throw new Error('HTTP ' + resp.status());
      return resp;
    } catch (e) {
      lastErr = e;
      if (i < retries) { log('retry', { url, attempt: i + 1, err: String(e).slice(0, 160) }); await sleep(3000 * (i + 1) * 2); }
    }
  }
  throw lastErr;
}

// slug() / kwIndexName() 见 lib/cli.cjs。
// v4：文件名改为「保序序号 + slug」，并在文件内写入 runId / kwIndex ——
// 前者解决「两条不同检索式同名互相覆写」，后者让汇总端能识别「非本次运行」的陈旧数据。
function saveIncremental(opts, keyword, records, extra) {
  const dir = path.join(opts.out, 'raw');
  fs.mkdirSync(dir, { recursive: true });
  const seq = (opts.kwIndexMap && opts.kwIndexMap[keyword]) || 0;
  fs.writeFileSync(path.join(dir, kwIndexName(seq, keyword) + '.json'),
    JSON.stringify({ runId: opts.runId || null, kwIndex: seq || null, keyword, count: records.length, ...extra, records }, null, 2), 'utf8');
}

// 页面**明确**说「无结果」的文案判据。★ 单一来源：探针读数与抓取循环共用，
// 防两套判据漂移（宽判据会把「采集失败」误判成真 0 ⇒ 反向风险，故只认这几条明确文案）。
const NO_RESULT_RE = /约\s*0\s*条结果|找不到.*不常见|did not match|没有找到/;

// ---------- 单关键词检索 ----------
async function searchKuluer(browser, opts, keyword) {
  const deadline = Date.now() + opts.keywordTimeoutSec * 1000;
  const ctx = await browser.newContext({
    userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36 Edg/154.0.0.0',
    locale: 'zh-CN',
  });
  const state = { ctx, closed: false };
  const page = await ctx.newPage();
  const records = [];
  const startedAt = new Date().toISOString();
  const t0 = Date.now();
  const diagnostics = { keyword, url: null, pages: 0, strategies: [], aborted: null, reportedTotal: null, noResultsSignal: false, sourceRef: null };
  let aborted = null;
  try {
    const url = 'https://kuluer.com/scholar?q=' + encodeURIComponent(keyword) + '&hl=zh-CN';
    diagnostics.url = url;
    // PRISMA 溯源：检索式来自源清单的哪一章节（需配合 --plan）
    diagnostics.sourceRef = (opts.sourceRefs && opts.sourceRefs[keyword]) || null;
    let softRetried = false;
    await gotoWithRetry(page, url, 2);
    const waitReady = () => page.waitForFunction(() => {
      const t = document.body ? document.body.innerText : '';
      return document.querySelectorAll('article[id^="r-"]').length > 0
        || /约\s*\d[\d,]*\s*条结果/.test(t)
        || /找不到|没有找到|did not match|不常见字词/.test(t);
    }, { timeout: opts.readyTimeoutSec * 1000 }).catch(() => null);
    await waitReady();

    // 站点自报命中总数（PRISMA Identification 的「数据库报告记录数」）
    // ★ 2026-10-19：一次求值同时取「计数」与「无结果信号」—— `reportedTotal === null` 从此只表示
    //   「没读到」，真 0 由 `reportedTotal === 0` 或 `noResultsSignal === true` 表达（两者都算站点给了证据）。
    //   判定集中在 lib/probe.cjs；本处只采集观测值。
    const readReportedTotal = () => page.evaluate(noResultSrc => {
      const t = document.body ? document.body.innerText : '';
      const m = t.match(/约\s*([\d,]+)\s*条结果/);
      return { total: m ? Number(m[1].replace(/,/g, '')) : null, noResults: new RegExp(noResultSrc).test(t) };
    }, NO_RESULT_RE.source).then(r => {
      if (r && r.noResults) diagnostics.noResultsSignal = true;
      return r ? r.total : null;   // 连求值都失败 ⇒ null（三态判为 collect_failed，不是 0）
    }).catch(() => null);
    diagnostics.reportedTotal = await readReportedTotal();

    while (records.length < opts.limit) {
      if (Date.now() > deadline) { aborted = 'keyword_timeout'; log('keyword_timeout', { keyword }); break; }
      const n = await page.$$eval('article[id^="r-"]', els => els.length).catch(() => 0);
      if (n === 0) {
        const bodyText = await page.evaluate(() => (document.body ? document.body.innerText : '')).catch(() => '');
        const gate = await detectGate(page);
        if (gate) {
          const ok = await waitGate(page, keyword, opts.gateTimeoutSec);
          if (!ok) { aborted = 'gate_timeout'; break; }
          continue;
        }
        if (NO_RESULT_RE.test(bodyText)) {
          // 站点**明确**说了无结果 ⇒ 记信号（真 0 可用于排除检索式；采集失败不可，见 lib/probe.cjs）
          diagnostics.noResultsSignal = true;
          log('no_results', { keyword });
          break;
        }
        if (bodyText.length < 200) { aborted = 'page_load_suspect'; break; }
        if (!softRetried) {
          softRetried = true;
          log('soft_retry', { keyword, reason: '0 articles, text len ' + bodyText.length });
          await gotoWithRetry(page, url, 1);
          await waitReady();
          continue;
        }
        aborted = /约\s*\d[\d,]*\s*条结果/.test(bodyText) ? 'structure_changed_or_no_results' : 'no_results_unconfirmed';
        break;
      }

      // ① 英文快照（多策略降级链）
      let res = await extractWithFallback(page);
      diagnostics.strategies.push({ page: diagnostics.pages + 1, strategy: res.strategy, fillRate: res.fillRate, n: res.items.length });
      // ② 站点 AI 翻译 → 中文快照回填
      const tr = await clickTranslate(page);
      // 面板**出现**时才回读（no_button / panel_timeout 才是真的没得读）——与旧实现的行为集合一致，
      // 故本改动不减少任何一次回读，只纠正「把它记为翻译成功」这一判定。
      if (tr.status !== 'no_button' && tr.status !== 'panel_timeout') {
        const after = await extractWithFallback(page);
        const zhMap = new Map(after.items.map(it => [it.id, it]));
        res.items.forEach(it => {
          const z = zhMap.get(it.id);
          if (z) { it.titleZh = z.titleZh || it.titleZh; it.abstractZh = z.abstractZh || it.abstractZh; }
        });
      }
      // v4.7：翻译失败态必须**有声音**（旧实现在此全程静默，只在报告里留下一个假的「站点译文=是」）
      if (tr.panels && tr.panels.failed > 0) {
        log('translate_panel', {
          keyword, status: tr.status, panels: tr.panels.n, failed: tr.panels.failed,
          hint: '站点 AI 翻译失败（实测多为 /api/ai/translate 429）；本页中文列将为 0%，非本工具缺陷',
        });
      }
      diagnostics.pages++;
      for (const it of res.items) {
        if (records.length >= opts.limit) break;
        const by = parseByline(it.byline);
        records.push({
          idx: records.length + 1, keyword, page: diagnostics.pages,
          titleEn: it.titleEn, titleZh: it.titleZh,
          authors: by.authors, source: by.source, year: by.year, domain: by.domain,
          abstractEn: it.abstractEn, abstractZh: it.abstractZh,
          citedBy: it.citedBy, paperUrl: it.paperHref, sourceUrl: it.sourceUrl,
          doiFromUrl: extractDoi(it.sourceUrl),
          // v4.7：记录级真值（该条是否真的带译文），不再复用「翻译动作已触发」的动作级布尔
          translatedBySite: hasSiteTranslation(it),
          translateStatus: tr.status,
        });
      }
      saveIncremental(opts, keyword, records, { strategy: res.strategy, fillRate: res.fillRate });
      if (records.length >= opts.limit) break;

      // ③ 翻页
      const sigBefore = await page.evaluate(() => {
        const a = document.querySelector('article[id="r-1"] h2 a');
        return a ? a.innerText : (document.body.innerText.slice(0, 120));
      }).catch(() => '');
      const next = await page.evaluate(() => {
        const n = [...document.querySelectorAll('a, button')].find(e => (e.innerText || '').trim() === '下一页' && !e.disabled);
        if (!n) return null;
        if (n.tagName === 'A' && n.href) return n.href;
        n.click();
        return 'clicked';
      });
      if (!next) { log('no_more_pages', { keyword }); break; }
      if (next !== 'clicked') { await sleep(rand(opts.interval)); await gotoWithRetry(page, next, 1); }
      else {
        try {
          await page.waitForFunction(prev => {
            const a = document.querySelector('article[id="r-1"] h2 a');
            return a && a.innerText !== prev;
          }, sigBefore, { timeout: 15000 });
        } catch (e) { log('pagination_stall', { keyword }); break; }
      }
      await sleep(rand(opts.interval));
    }
    // 无结果页/加载异常会丢失计数，翻页后重读一次以填齐 PRISMA 计数
    if (diagnostics.reportedTotal == null) diagnostics.reportedTotal = await readReportedTotal();
  } catch (e) {
    aborted = 'error: ' + String(e).slice(0, 300);
  } finally {
    diagnostics.aborted = aborted;
    diagnostics.durationMs = Date.now() - t0;
    diagnostics.startedAt = startedAt;
    diagnostics.endedAt = new Date().toISOString();
    state.closed = true;
    await ctx.close().catch(() => {});
  }
  return { records, aborted, diagnostics };
}

// ---------- 多源 HTTP 通道（v4.15 / A-2） ----------
/**
 * 与 `searchKuluer()` 返回同形状（records / aborted / diagnostics），
 * 使 qc / enrich / fulltext / dedupe / evidence / raw / PRISMA **全部无需改动**即可消费。
 *
 * 判据全部下沉到 lib/multi-run.cjs（纯函数、可离线测）—— 这里只负责「发起」与「透传」。
 * 这样做的理由：计数能不能相加、0 条算不算失败，是判据问题；判据留在主脚本里就只能靠真跑网络验证。
 */
async function searchHttpSources(opts, keyword) {
  const res = await runSources({
    sources: opts.sourceIds,
    query: keyword,
    limit: opts.limit,
    keyword,
    concurrency: opts.sourceConcurrency,
    perSourceTimeoutMs: opts.sourceTimeoutSec * 1000,
    mailto: opts.mailto || undefined,
  });
  const r = MR.buildKeywordResult({ res, keyword, limit: opts.limit });
  r.diagnostics.startedAt = new Date(new Date(res.durationMs ? Date.now() - res.durationMs : Date.now())).toISOString();
  r.diagnostics.endedAt = new Date().toISOString();
  return r;
}

// ---------- 主流程 ----------
(async () => {
  // 输入层失败（未知参数 / 取值缺失 / 非法值 / 目录不可用）必须给「可执行的提示」而非裸栈。
  // guard 覆盖 resolveInputs 与 ensureDir 两处——v4 首轮曾漏掉 ensureDir，实测仍抛栈，已修。
  const guard = fn => {
    try { return fn(); }
    catch (e) {
      if (e instanceof CliError) { console.error(e.message); process.exit(e.code); }
      throw e;
    }
  };
  const opts = guard(() => resolveInputs(process.argv, { log }));
  opts.notices.forEach(n => console.error(n)); // notices 一律走 stderr，stdout 只留 JSON 事件流
  if (!opts.keywords.length) { console.error('用法: --keywords "词1" "词2" 或 --keywords-file 文件'); process.exit(1); }
  guard(() => ensureDir(opts.out));            // 先确保输出目录可用，再宣布关键词（失败要尽早）
  console.error(describeKeywordSources(opts)); // 让「解析出几条关键词、来自哪里」可见（v3 静默拆分缺陷的可见化）

  // 本次运行标识：写入每个 raw 文件与 summary.json，供汇总端区分「本次 / 陈旧」
  const runId = new Date().toISOString().replace(/[:.]/g, '-');
  opts.runId = runId;
  opts.kwIndexMap = {};                        // 关键词 → 1 起算保序序号（决定 raw 文件名前缀）
  opts.keywords.forEach((kw, i) => { opts.kwIndexMap[kw] = i + 1; });
  const keywordIndex = {};                     // "01" → 关键词，写入 summary 供双向核对
  opts.keywords.forEach((kw, i) => { keywordIndex[String(i + 1).padStart(2, '0')] = kw; });

  // 通道分流（v4.15 / A-2）：有 sourceIds 走 HTTP 多源；否则走原浏览器站点通道（行为与 v4.14 逐字一致）
  const useMulti = Array.isArray(opts.sourceIds) && opts.sourceIds.length > 0;
  if (useMulti) console.error(describeSources(opts));

  // 浏览器只在站点通道下探测与启动：多源通道不需要 Edge/Chrome（CI 可跑）
  const exe = useMulti ? null : findBrowser();
  const startedAt = new Date().toISOString();
  log('run_start', { runId, site: useMulti ? null : opts.site, channel: useMulti ? 'http' : 'browser', sources: useMulti ? opts.sourceIds : null, keywords: opts.keywords, limit: opts.limit, headless: useMulti ? null : opts.headless, enrich: opts.enrich, dedupe: opts.dedupe, enrichConcurrency: opts.enrichConcurrency, exe });
  const browser = useMulti ? null : await chromium().launch({ executablePath: exe, headless: opts.headless, args: ['--disable-gpu', '--no-first-run'] });

  const groups = [];
  const multiResults = [];                     // [{ keyword, res }] ⇒ 源级降级告警与 PRISMA 多源行
  const summary = {
    runId, startedAt, site: useMulti ? null : opts.site, limit: opts.limit, countOnlyProbe: opts.limit === 0,
    channel: useMulti ? 'http' : 'browser',
    sources: useMulti ? opts.sourceIds.slice() : null,
    options: { enrich: opts.enrich, dedupe: opts.dedupe, fillMin: opts.fillMin, enrichConcurrency: opts.enrichConcurrency, sourceTimeoutSec: useMulti ? opts.sourceTimeoutSec : null, sourceConcurrency: useMulti ? opts.sourceConcurrency : null },
    keywords: {}, keywordIndex, errors: [], warnings: [],
  };
  let exitCode = 0;
  try {
    for (const kw of opts.keywords) {
      const { records, aborted, diagnostics, multi } = useMulti
        ? await searchHttpSources(opts, kw)
        : await searchKuluer(browser, opts, kw);
      if (multi) multiResults.push({ keyword: kw, res: multi });
      groups.push({ keyword: kw, records, aborted, diagnostics });
      // v4.7：「站点译文」改为**整批记录级真值**（有译文才算），并显式登记翻译失败态。
      const zhN = records.filter(hasSiteTranslation).length;
      const trStatus = records.length ? (records[0].translateStatus || null) : null;
      summary.keywords[kw] = { count: records.length, translatedBySite: records.some(hasSiteTranslation), translateStatus: trStatus, zhTranslated: zhN, aborted: aborted || null, strategy: (diagnostics.strategies[0] || {}).strategy || null, reportedTotal: diagnostics.reportedTotal, countState: useMulti ? diagnostics.countState : classifyCount(diagnostics).state };
      if (multi) {
        // 逐源读数进 summary：只读 summary 的下游（报告/人工核读）也能看出「这个数是哪个源给的」
        summary.keywords[kw].sources = diagnostics.sources;
        summary.keywords[kw].crossSourceDedupe = diagnostics.sourceDedupe;
      }
      // v4.7：整批 0 条译文必须显式提醒 —— 旧实现会同时输出「站点译文=是」与「中文 0%」，自相矛盾。
      // 多源通道没有站点译文（传输层就不带中文），故只在站点通道下告警，否则会误报「工具缺陷」。
      if (!useMulti && records.length && zhN === 0) {
        if (trStatus === 'ok') summary.warnings.push(kw + ': 翻译面板已出现但未解析出译文结构（疑似站点面板改版，请核对截图）');
        else summary.warnings.push(kw + ': 站点 AI 翻译未取到译文（translateStatus=' + trStatus + '）——本批中文列为空，非本工具缺陷');
      }
      if (aborted === 'all_sources_failed') {
        // 通道级故障：与站点通道的 exit 5 同语义（「不是检索式无效」），恢复后重跑即可
        exitCode = exitCode || 5;
        summary.errors.push(kw + ': 全部 ' + opts.sourceIds.length + ' 个源均不可用 —— 网络/服务级故障，不是检索式无效；请勿据此排除该检索式');
      }
      else if (aborted === 'gate_timeout') exitCode = 2;
      else if (aborted === 'structure_changed_or_no_results' && records.length === 0) { exitCode = 3; summary.errors.push(kw + ': 未提取到条目——疑似页面结构变化，请人工核对截图'); }
      else if (aborted === 'no_results_unconfirmed') summary.warnings.push(kw + ': 无条目且站点未给出明确无结果信号');
      else if (aborted === 'keyword_timeout') { exitCode = exitCode || 1; summary.warnings.push(kw + ': 单关键词超时(' + opts.keywordTimeoutSec + 's)，已保留 ' + records.length + ' 条'); }
      else if (aborted && aborted.startsWith('error:')) { exitCode = exitCode || 1; summary.errors.push(kw + ': ' + aborted); }
      if (aborted) log('keyword_aborted', { keyword: kw, reason: aborted, kept: records.length });
      else log('keyword_done', { keyword: kw, count: records.length, strategy: (diagnostics.strategies[0] || {}).strategy });
      // 多源通道无需站点节流（各源自带礼貌间隔与 429 退避）；站点通道保持原 --interval 节奏
      if (!useMulti) await sleep(rand(opts.interval));
    }

    // 计数探针三态汇总（2026-10-19 挂账修复）：把「采集失败」从「真 0 命中」里分离出来。
    // 旧实现只在「全 0 且一条计数都没有」时报警，**部分失败（4/10）完全静默**
    // —— 探针模式的用途正是「先比命中量再决定跑哪条」，静默即可能误排除一条本来有效的检索式。
    const verdict = useMulti
      ? MR.multiProbeVerdict(groups, { limit: opts.limit })
      : attachProbe(summary, groups, { limit: opts.limit, readyTimeoutSec: opts.readyTimeoutSec });
    // 多源通道不调 attachProbe：它的三态判据会把「本次没有可计数的源」判成 collect_failed（假故障），
    // 进而污染 siteDegraded。故在这里写一份同形 summary.probe + 源级告警（判据见 lib/multi-run.cjs）。
    if (useMulti) {
      summary.probe = {
        countOnlyProbe: verdict.probe,
        total: verdict.total,
        counted: verdict.counted,
        zeroConfirmed: verdict.zeroConfirmed,
        failed: verdict.failed,
        notApplicable: verdict.notApplicable,
        allFailed: verdict.allFailed,
        siteDegraded: verdict.siteDegraded,
        sources: opts.sourceIds.slice(),
      };
      const ws = MR.sourceWarnings(multiResults);
      ws.forEach(w => { summary.warnings.push(w); console.error('[WARN] ' + w); });
      if (ws.length) log('sources_degraded', { sources: opts.sourceIds, warnings: ws.length });
      log('sources_summary', { line: MR.sourceSummaryLine(multiResults, { probe: opts.limit === 0 }) });
    }
    if (verdict.failed.length) {
      log('probe_collect_failed', {
        keywords: verdict.failed, countOnlyProbe: verdict.probe,
        hint: '计数未读到且无「无结果」提示 ⇒ 采集失败，不是 0 命中；不得据此排除该检索式',
      });
    }
    if (verdict.probe) log('probe_summary', { line: probeSummaryLine(verdict, { subject: useMulti ? '源' : '站点' }) });

    // 质量自检：把「成功但字段大面积缺失」显式判为失败。
    // --limit 0 属「计数探针」（只取站点自报命中、不抓条目）⇒ 0 条是预期结果，由 qcCheck 内部豁免（v4.6）。
    const qc = qcCheck(groups, { titleMin: opts.fillMin, limit: opts.limit });

    // 全 0 且站点未给出任何读数证据 → 更可能是站点侧不可用/限流，而非所有关键词都无结果。
    // 若不区分，使用者会误以为是自己的检索式写错了（2026-10-04 实测踩过：站点延迟导致全 0）。
    // ★ 判据由「reportedTotal != null」改为「counted 或 zero_confirmed」：站点**明确说 0 条**时
    //   它已经给了证据，旧判据会把这种正常情况误报成站点不可用（exit 5 假阳性）。
    //   多源通道下这条判据由 lib/multi-run.cjs 的 multiProbeVerdict 承担（同语义，但不能把
    //   「本次没有可计数的源」算成故障）。
    if (verdict.siteDegraded) {
      exitCode = exitCode || 5;
      summary.errors.push(useMulti
        ? '全部 ' + groups.length + ' 个关键词均为 0 条，且没有任何源给出读数 —— 疑似网络/服务级故障，而非关键词无结果。建议稍后重试或改用 --sources all，勿据此判定检索式无效。'
        : '全部 ' + groups.length + ' 个关键词均为 0 条，且站点既未返回「约 N 条结果」计数、'
          + '也未给出「无结果」提示 —— 疑似站点侧不可用/限流或渲染延迟，而非关键词无结果。'
          + '建议：加大 --ready-timeout（当前 ' + opts.readyTimeoutSec + 's）或稍后重试，勿据此判定检索式无效。');
      log('site_degradation_suspect', { keywords: groups.length, readyTimeoutSec: useMulti ? null : opts.readyTimeoutSec, channel: useMulti ? 'http' : 'browser' });
    }
    summary.qc = qc;
    if (!qc.ok) {
      exitCode = exitCode || 4;
      qc.issues.forEach(i => summary.errors.push('QC: ' + i));
      log('qc_failed', { fill: qc.fill, issues: qc.issues });
    } else if (qc.skipped) {
      // 计数探针：豁免填充率 QC，但仍显式登记（不静默跳过）
      log('qc_skipped', { reason: qc.skipped, limit: opts.limit });
    } else {
      log('qc_passed', { fill: qc.fill });
    }

    // 可选：元数据补全（Europe PMC，v4.3 起为有界并发 + 429 自动降级串行）
    if (opts.enrich && groups.some(g => g.records.length)) {
      const all = groups.flatMap(g => g.records);
      const { stat, concurrency, degraded } = await enrichAll(all, { intervalMs: 300, concurrency: opts.enrichConcurrency });
      summary.enrichStat = stat;
      summary.enrichConcurrency = { requested: opts.enrichConcurrency, effective: concurrency, degraded: !!degraded };
      log('enrich_done', { stat, concurrency, degraded: !!degraded });
      if (degraded) console.error('[WARN] Europe PMC 连续出现 429，已自动降级为串行补全（effective concurrency=1）；如需强制串行请用 --enrich-concurrency 1');
      groups.forEach(g => saveIncremental(opts, g.keyword, g.records, { strategy: (g.diagnostics.strategies[0] || {}).strategy }));
    }

    // 可选：全文四级回退链（v4.15）—— 只补信息、**不改等级**；抓取失败不降级，只如实记录
    if (opts.fulltext) {
      const flat = [];
      groups.forEach(g => g.records.forEach(r => flat.push(r)));
      const { stat } = await runFulltextChain(flat, {
        outDir: opts.out,
        concurrency: opts.fulltextConcurrency,
        email: opts.mailto,
        allowBrowser: opts.fulltextBrowser === true,
        headless: opts.headless,
        timeoutMs: 25000,
        intervalMs: 300,
      });
      summary.fulltext = stat;
      log('fulltext_done', stat);
      if (stat.noEntry > 0) {
        const msg = stat.noEntry + ' 条既无 DOI 也无 PMCID ⇒ 全文链无入口可试（不是抓取失败，是这条记录本身没有可定位标识）';
        summary.warnings.push(msg);
        console.error('[WARN] ' + msg);
      }
      if (stat.pdfOnly > 0) {
        const msg = stat.pdfOnly + ' 条只能定位到 OA PDF（无法在零依赖前提下可靠抽文本）⇒ 已登记 PDF 地址，需人工打开核对；**不计入已获取全文**';
        summary.warnings.push(msg);
        console.error('[WARN] ' + msg);
      }
      if (stat.failed > 0) {
        const msg = '全文抓取失败 ' + stat.failed + ' 条（' + Object.keys(stat.byStatus).filter(k => k !== 'cached').join('、') + '）；这些记录仍按摘要级判定，**等级不变**';
        summary.warnings.push(msg);
        console.error('[WARN] ' + msg);
      }
      if (stat.byEntry && stat.byEntry.doiOnly > 0 && !opts.mailto) {
        // 旧版这一行写的是「无 pmcid ⇒ 未取全文，属预期」——v4.15 起不再成立：
        // 只有 DOI 的记录会走 T3（Unpaywall），但该级**必须**有真实邮箱，否则被跳过。
        summary.warnings.push(stat.byEntry.doiOnly + ' 条只有 DOI 无 PMCID ⇒ 全文链走 T3 Unpaywall；本次未给 --mailto，该级已跳过');
      }
      groups.forEach(g => saveIncremental(opts, g.keyword, g.records, { strategy: (g.diagnostics.strategies[0] || {}).strategy }));
    }

    // 可选：跨关键词去重
    let dedupeInfo = null;
    if (opts.dedupe) {
      const d = dedupe(groups);
      // skipped = 既无 DOI 也无标题、无法判定而未参与去重的条数（v4.2 起可见，避免"悄悄少了几条"）
      dedupeInfo = { total: d.total, unique: d.unique.length, duplicates: d.duplicates.length, skipped: d.skipped };
      summary.dedupe = dedupeInfo;
      fs.writeFileSync(path.join(opts.out, 'dedupe.json'), JSON.stringify(d, null, 2), 'utf8');
      log('dedupe_done', dedupeInfo);
    }

    // 可选：证据分级结构化（启发式候选，本地计算，无网络）
    let evidenceSummary = null;
    if (opts.evidence) {
      evidenceSummary = gradeAll(groups);
      summary.evidence = evidenceSummary;
      log('evidence_done', {
        graded: evidenceSummary.graded, gradeStat: evidenceSummary.gradeStat,
        needsManualExclude: evidenceSummary.needsManualExcludeCount,
        lowConfidence: evidenceSummary.lowConfidenceCount,
      });
      groups.forEach(g => saveIncremental(opts, g.keyword, g.records, { strategy: (g.diagnostics.strategies[0] || {}).strategy }));
    }

    fs.writeFileSync(path.join(opts.out, 'diagnostics.json'),
      JSON.stringify({ runId, startedAt, options: summary.options, keywords: groups.map(g => g.diagnostics), qc: summary.qc }, null, 2), 'utf8');

    // PRISMA 式检索日志（默认必写：可复现性是本技能的交付前提之一）
    // 多源通道额外传 sources：逐「检索式 × 源」一行，由 prisma.cjs 渲染第 2.1 节并按源聚合。
    const prismaSources = useMulti
      ? multiResults.reduce((acc, it) => acc.concat(MR.prismaRows(it.keyword, (it.res.perSource || []))), [])
      : null;
    try {
      const logObj = buildLog({
        runs: groups.map(g => ({
          keyword: g.keyword,
          sourceRef: g.diagnostics.sourceRef,
          url: g.diagnostics.url,
          reportedTotal: g.diagnostics.reportedTotal,
          // 多源通道的计数状态由聚合层显式给出（含 not_applicable「本次无可计数源」），
          // 不能让 buildLog 用单源三态重新判一次 —— 那会把 not_applicable 判成 collect_failed。
          countState: useMulti ? g.diagnostics.countState : undefined,
          retrieved: g.records.length,
          pages: g.diagnostics.pages,
          strategy: (g.diagnostics.strategies[0] || {}).strategy || null,
          translatedBySite: g.records.some(hasSiteTranslation),
          translateStatus: (g.records[0] && g.records[0].translateStatus) || null,
          zhTranslated: g.records.filter(hasSiteTranslation).length,
          aborted: g.aborted || null,
          startedAt: g.diagnostics.startedAt,
          endedAt: g.diagnostics.endedAt,
          durationMs: g.diagnostics.durationMs,
        })),
        dedupe: dedupeInfo,
        evidence: evidenceSummary,
        sources: prismaSources,
        meta: {
          runId, startedAt, endedAt: new Date().toISOString(), site: useMulti ? null : opts.site,
          channel: useMulti ? 'http' : 'browser',
          sources: useMulti ? opts.sourceIds.slice() : null,
          limit: opts.limit,
          countOnlyProbe: opts.limit === 0,
          enrich: opts.enrich, dedupe: opts.dedupe, grading: opts.evidence,
          keywordSource: opts.keywordsFile ? { file: path.basename(opts.keywordsFile), count: opts.keywords.length } : null,
          planFile: opts.plan ? path.basename(opts.plan) : null,
          toolVersion: TOOL_VERSION,
        },
      });
      const written = writeLog(opts.out, logObj, { svg: true });
      log('prisma_log_written', {
        md: path.basename(written.mdPath),
        svg: written.svgPath ? path.basename(written.svgPath) : null,
        runs: logObj.identification.searchCount,
        retrieved: logObj.identification.recordsRetrieved,
      });
      // v4.9：出图失败不让整次检索失败（结果与 md/json 存档完整），但必须进 warnings 可见
      if (written.svgError) summary.warnings.push('PRISMA 流程图未生成: ' + written.svgError);
    } catch (e) {
      // 日志写失败不应让已检索结果作废，但必须显式报错
      exitCode = exitCode || 1;
      summary.errors.push('PRISMA 日志写入失败: ' + String(e).slice(0, 200));
      log('prisma_log_failed', { err: String(e).slice(0, 200) });
    }
  } finally {
    // 多源通道没有浏览器（browser=null）⇒ 必须显式判空，否则收尾时报 TypeError 并吞掉真实退出码
    if (browser) await browser.close().catch(() => {});
    fs.writeFileSync(path.join(opts.out, 'summary.json'), JSON.stringify(summary, null, 2), 'utf8');
    log('run_end', { exitCode });
    process.exit(exitCode);
  }
})();
