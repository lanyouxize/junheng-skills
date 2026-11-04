#!/usr/bin/env node
/* eslint-disable */
/**
 * lib/prisma.cjs — PRISMA 式检索日志（可复现性存档）
 *
 * 目的：让一次文献检索在半年后仍能被第三方逐字复跑 ——把「检索式 / 数据源 / 时间 / 命中数 /
 *      去重数 / 纳入数 / 异常」全部留痕。与 hand-only 记流水账不同，这里全部由机器写入，
 *      不存在事后补写的记忆偏差。
 *
 * ⚠ 诚实约束（不要在「让流程图更好看」时违反）:
 *   · 站点报告的「约 N 条结果」是**数据库自报命中数**，不是本次导出的记录数，两者分列。
 *   · 本工具**不做资格排除**：筛查/资格阶段的「排除」一律记 0，
 *     属于「需人工复核」的项单独列为 Crypto 子表，绝不混计入 Excluded。
 *     理由：如果自动把 30 条写进 Excluded，读者会以为这 30 条已被人工审阅并判定不合格。
 */
'use strict';

const fs = require('fs');
const path = require('path');
// 计数三态（counted / zero_confirmed / collect_failed）——与探针层共用同一判据，禁止在此另立一套
const { COUNT_STATE, classifyCount } = require('./probe.cjs');
// v4.15（A-2）：按源聚合只保留一处实现，避免「PRISMA 一处算、报告另一处算」的漂移
const { aggregateBySource } = require('./multi-run.cjs');

const VERSION = 'prisma-log/v1';

/** 计数状态的中文标签（含多源专用的 not_applicable；缺它会把「不适用」渲染成空白） */
const COUNT_TEXT = {
  counted: '已读得',
  zero_confirmed: '0（源已确认）',
  collect_failed: '未读到',
  not_applicable: '不适用（该源不提供可用计数）',
};

const GRADE_NOTE = {
  A: '靶动物 RCT/SR——优先精读',
  B: '靶动物对照/设计良好——次优先',
  C: '间接物种/观察性/体外——仅作机制线索',
  D: '证据薄弱或信息不足——不建议用于宣称支撑',
};

/**
 * @param {object} p
 * @param {Array}  p.runs     每个关键词的实测结果:
 *       { keyword, sourceRef, url, reportedTotal, retrieved, pages, strategy,
 *         translatedBySite, translateStatus, zhTranslated, aborted, startedAt, endedAt, durationMs }
 * @param {object} p.dedupe   { total, unique, duplicates, removedList } 或 null（未去重）
 * @param {object} p.evidence  evidence.gradeAll 的返回值，或 null
 * @param {Array}  p.sources  多源通道的逐「检索式 × 源」读数（v4.15）；单源通道传 null，输出与旧版逐字一致
 * @param {object} p.meta     { startedAt, endedAt, site, baseUrl, limit, enrich, dedupe, grading,
 *                               keywordSource:{file,count} | null, toolVersion, planFile }
 */
function buildLog({ runs = [], dedupe = null, evidence = null, sources = null, meta = {} }) {
  const srcRows = Array.isArray(sources) && sources.length ? sources : null;
  const dataSources = srcRows ? aggregateBySource(srcRows) : null;
  const sum = (arr, k) => arr.reduce((a, r) => a + (Number(r[k]) || 0), 0);
  // ★ 计数三态：`reportedTotal === null` 只表示「没读到」，真 0 由 0 或 noResultsSignal 表达。
  //   旧实现在这里直接用 null 兼表两义 ⇒ 报告里「—」既可能是真 0 也可能是采集失败（不可辨）。
  const rows = runs.map(r => Object.assign({}, r, { countState: r.countState || classifyCount(r).state }));
  const reportedTotal = sum(rows, 'reportedTotal');
  const retrieved = sum(rows, 'retrieved');
  const noResultKw = rows.filter(r => r.retrieved === 0 && !r.aborted).map(r => r.keyword);
  const abnormalKw = rows.filter(r => r.aborted).map(r => ({ keyword: r.keyword, reason: r.aborted }));
  const unknownCountKw = rows.filter(r => r.countState === COUNT_STATE.COLLECT_FAILED).map(r => r.keyword);
  // 多源：本次没有可计数源（只跑了 none 型源）—— 既不是故障也没有读数，必须与「未读到」分开登记
  const naCountKw = rows.filter(r => r.countState === 'not_applicable').map(r => r.keyword);

  const duplicatesRemoved = dedupe ? dedupe.duplicates : null;
  const afterDedupe = dedupe ? dedupe.unique : retrieved;

  const identification = {
    // 多源时「数据库」是源名拼接：只写其中一个会让复跑者以为只用了一个源（元数据说谎）
    database: dataSources ? dataSources.map(s => s.label).join(' + ') : (meta.site || 'kuluer'),
    baseUrl: dataSources ? null : (meta.baseUrl || 'https://kuluer.com/scholar'),
    channel: dataSources ? 'http_multi_source' : 'site_browser',
    searchCount: rows.length,
    reportedTotalBySite: reportedTotal,      // 站点自报命中数（未经导出）
    // 「已知」= 每条都拿到了读数证据（整数计数，或站点明确说无结果）；
    // 只有 collect_failed（null 且无「无结果」信号）才判为不完全 —— 旧判据把采集失败与真 0 混为一谈。
    // ★ 多源补一条：`not_applicable`（本次没有可计数的源）同样属于「没有读数」，
    //   不能因为它不是故障就把合计当成已知 —— 否则「只跑 Crossref」会写出「合计 0 条」的假读数。
    reportedTotalKnown: unknownCountKw.length === 0 && naCountKw.length === 0,
    reportedTotalUnknownKeywords: unknownCountKw.concat(naCountKw),
    reportedTotalNotApplicableKeywords: naCountKw,
    recordsRetrieved: retrieved,
    note: 'reportedTotalBySite 为站点展示的匹配总数上限参考；recordsRetrieved 为本次实际导出条目数（受 --limit 限制）',
  };
  if (dataSources) {
    identification.dataSources = dataSources;
    identification.dataSourceCount = dataSources.length;
    identification.countSemanticsNote = '仅 countSemantics=exact 的源计入 reportedTotalBySite；'
      + 'countSemantics=none 的源（Crossref）其 total 为全库软匹配规模，只贡献记录、不计入任何计数列。';
  }
  const screening = {
    recordsAvailable: retrieved,
    duplicatesRemoved: duplicatesRemoved,
    recordsAfterDuplicates: afterDedupe,
    dedupePerformed: !!dedupe,
    note: duplicatesRemoved === null ? '本次未执行去重（未加 --dedupe）' : null,
  };
  const eligibility = {
    recordsAssessed: afterDedupe,
    excludedByTool: 0,                        // 恒为 0：工具不做资格判断
    note: '本工具不自动排除任何文献；资格判定必须由人工读全文完成。',
  };
  const included = {
    recordsIncluded: afterDedupe,
    flaggedForReview: evidence ? evidence.needsManualExcludeCount : null,
    lowConfidenceCount: evidence ? evidence.lowConfidenceCount : null,
    note: evidence ? 'Crypto 标记为「怀疑混杂非靶动物/信息不足」的候选条目，仍在纳入数内，需人工复核后方可使用或剔除。' : null,
  };

  const limitations = [
    '检索通道为单一学术镜像站（Google Scholar 架构），并非规范化数据库，同义词与 MeSH 受控词未完整覆盖。',
    '站点自报命中数为实时统计口径，重复检索可能小幅波动，不可作为精确查全率依据。',
    '本次未施加发表日期、文献类型、语言限定（界面语言仅影响 UI 文案，不等于文献语言过滤）。',
    '证据分级为启发式候选标记，未经全文核对，不得直接作为宣称支撑的强度判定。',
    '全文通道（--fulltext）为可选步骤，只补信息、**不改变证据等级**；抽出的方法学片段是关键词匹配结果，需人工回原文确认（偏移量见报告）。',
  ];
  if (dataSources) {
    // 多源通道的三条限制必须写进产物：读者若把不同源的命中数直接相加，得到的数是假的
    limitations[0] = '检索通道为多源 HTTP 拼接（' + dataSources.map(s => s.label).join(' + ')
      + '），各源学科覆盖不同（Europe PMC 偏生物医学、Crossref 全学科但相关性弱）：'
      + '同一检索式在不同源的命中数**不可相加比较**，「合计」仅表示各源自报计数之和。';
    limitations.push('计数口径：仅 countSemantics=exact 的源计入命中数；Crossref 的 total 为**全库软匹配规模**'
      + '（实测布尔式与词袋的 total 逐字相同），故该源只贡献记录、不贡献计数。');
    limitations.push('多源通道不提供站点 AI 译文（中文列由后续翻译环节产生），且各源的回退/限流策略不同：'
      + '「某源不可用」只表示该源本次未参与，不表示该检索式无效。');
  }

  const out = {
    version: VERSION,
    generatedAt: new Date().toISOString(),
    meta,
    identification,
    screening,
    eligibility,
    included,
    searches: rows,
    noResultKeywords: noResultKw,
    abnormalKeywords: abnormalKw,
    evidenceSummary: evidence
      ? {
        graded: evidence.graded,
        gradeStat: evidence.gradeStat,
        designStat: evidence.designStat,
        speciesStat: evidence.speciesStat,
        flagStat: evidence.flagStat,
      }
      : null,
    limitations,
  };
  // 仅在多源通道下挂 sourceRows：单源通道的 prisma.json 必须与 v4.14 逐字一致
  // （外部有人用 git diff 对比两次运行的 JSON 来判断「结果有没有变」）。
  if (srcRows) out.sourceRows = srcRows;
  return out;
}

function fmtNum(n) { return n === null || n === undefined ? '—' : String(n); }
/** 计数列四态各给不同字样：「0」是**明确**说 0 条，「未读到」是采集失败，「不适用」是没有可计数的源 —— 三者不可互换。 */
function fmtCount(r) {
  if (!r) return '—';
  if (r.countState === COUNT_STATE.COLLECT_FAILED) return '未读到';
  if (r.countState === COUNT_STATE.ZERO_CONFIRMED) return '0';
  if (r.countState === 'not_applicable') return '不适用';
  const n = Number(r.reportedTotal);
  return Number.isFinite(n) ? String(n) : '未读到';
}

/**
 * @param {object} log  buildLog() 的返回值
 * @param {object} [opts]
 * @param {boolean} [opts.svg]        第 3 节是否内联引用 `PRISMA.svg`（默认 false，保持旧行为）
 * @param {string}  [opts.svgError]   图生成失败原因；给了就在第 3 节写明并指向 ASCII 兜底
 */
function renderMarkdown(log, opts = {}) {
  const L = [];
  const m = log.meta || {};
  L.push('# PRISMA 式检索日志');
  L.push('');
  L.push('> 本文件由 `lib/prisma.cjs` 自动生成，**请勿手工编辑**；重跑主脚本会整体重写。');
  L.push('> 定位：记录「本次检索做了什么、拿到多少、留下多少」，使他人可依此复跑。');
  L.push('');
  L.push('## 1. 检索概要');
  L.push('');
  L.push('| 项目 | 值 |');
  L.push('|---|---|');
  L.push('| 生成时间 | ' + log.generatedAt + ' |');
  L.push('| 数据源/数据库 | ' + log.identification.database
    + (log.identification.baseUrl ? '（' + log.identification.baseUrl + '）' : '（多源 HTTP 并行，未使用浏览器）') + ' |');
  L.push('| 执行起始 | ' + (m.startedAt || '—') + ' |');
  L.push('| 执行结束 | ' + (m.endedAt || '—') + ' |');
  L.push('| 检索式条数 | ' + log.identification.searchCount + ' |');
  L.push('| 每条结果上限 | ' + (m.limit == null ? '—' : m.limit) + (m.countOnlyProbe ? '（计数探针：0 条为预期）' : '') + ' |');
  L.push('| 关键词来源文件 | ' + (m.keywordSource ? m.keywordSource.file + '（' + m.keywordSource.count + ' 行）' : '命令行直传') + ' |');
  L.push('| 检索式溯源计划 | ' + (m.planFile || '（未使用 plan.json）') + ' |');
  L.push('| 元数据补全 | ' + (m.enrich ? '已启用（Europe PMC）' : '未启用') + ' |');
  L.push('| 跨关键词去重 | ' + (m.dedupe ? '已启用' : '未启用') + ' |');
  L.push('| 证据分级 | ' + (m.grading ? '已启用（启发式候选）' : '未启用') + ' |');
  L.push('| 工具版本 | ' + (m.toolVersion || VERSION) + ' |');
  L.push('');

  if (m.countOnlyProbe) {
    L.push('> **计数探针模式**（`--limit 0`）：本次只采集各检索式的「站点报告命中」，**不抓取任何条目** ——');
    L.push('> 故下表「实际抓取」列恒为 0，且**不进行填充率质量自检**（0 条是预期结果，非静默降级；v4.6）。');
    L.push('> 探针的唯一用途是「先比命中量、再决定跑哪条」⇒ 计数列的「未读到」必须重跑，**不可当作 0 参与比较**。');
    L.push('');
  }

  L.push('## 2. 各检索式明细（Identification）');
  L.push('');
  // 多源下这一列是「各 exact 源自报命中之和」，叫「站点报告」会说谎（本次根本没有站点）
  const multi = !!log.identification.dataSources;
  L.push('| # | 检索式 | 清单出处 | ' + (multi ? '源报告命中合计' : '站点报告命中')
    + ' | 实际抓取 | 页数 | 提取策略 | ' + (multi ? '源内译文' : '站点译文') + ' | 耗时(秒) | 异常 |');
  L.push('|---|---|---|---:|---:|---:|---|---|---:|---|');
  log.searches.forEach((r, i) => {
    // v4.7：翻译失败态不得静默 —— 旧版「站点译文」列 = **翻译动作已触发**（面板元素出现即算），
    // 站点 /api/ai/translate 429 时会与报告头「中文填充率 0%」并存（动作级假阳性）。
    // 本版该列改为**记录级真值**（该词是否真的取到译文），失败原因在「异常」列显式标出。
    const anomalies = [];
    if (r.aborted) anomalies.push(r.aborted);
    if (r.translateStatus && r.translateStatus !== 'ok') anomalies.push('translate:' + r.translateStatus);
    L.push('| ' + (i + 1) + ' | `' + String(r.keyword).replace(/\|/g, '\\|') + '` | ' + (r.sourceRef || '—')
      + ' | ' + fmtCount(r) + ' | ' + r.retrieved + ' | ' + (r.pages || 0) + ' | ' + (r.strategy || '—')
      + ' | ' + (r.translatedBySite ? '是' : '否') + ' | ' + (Math.round((r.durationMs || 0) / 100) / 10)
      + ' | ' + anomalies.join('；') + ' |');
  });
  L.push('');
  L.push(multi
    ? '> 「源报告命中合计」只累加 `countSemantics=exact` 的源（逐源见 2.1）；「实际抓取」受 `--limit` 上限约束，两者不可直接互推。'
    : '> 「站点报告命中」为该词在站点自报的匹配总数；「实际抓取」受 `--limit` 上限约束，两者不可直接互推。');
  L.push('> 「**未读到**」= 该条未取得站点读数（疑似未达就绪/渲染延迟），**不等于 0 命中** ⇒ 不得据此排除该检索式；');
  L.push('> 「0」= 站点明确回答「0 条结果」，属有效证据。两种情况在旧版里都渲染为「—」，无法区分。');
  L.push('');

  // ── 2.1 各源读数（仅多源通道）──
  // 章节号刻意用 2.1 而不是插入新的一节：后面的「3. PRISMA 流程计数」等编号被大量外部引用
  // （报告正文、旧版产物、人工核读清单），重排编号会让历史文档的交叉引用集体失效。
  const ds = log.identification.dataSources;
  if (Array.isArray(ds) && ds.length) {
    L.push('## 2.1 各源读数（多源通道）');
    L.push('');
    L.push('### 按源汇总');
    L.push('');
    L.push('| 源 | 通道 | 计数口径 | 检索式数 | 可用 | 取得记录 | 自报命中 | 失败原因 |');
    L.push('|---|---|---|---:|---:|---:|---:|---|');
    ds.forEach(s => {
      L.push('| ' + s.label + '（`' + s.id + '`） | ' + (s.kind || '—') + ' | '
        + (s.countSemantics === 'exact' ? 'exact（可计数）' : 'none（不计数）') + ' | '
        + s.searches + ' | ' + s.okSearches + ' | ' + s.records + ' | '
        + (s.reportedTotal === null ? '—' : s.reportedTotal) + ' | '
        + (s.abortedReasons.length ? s.abortedReasons.slice(0, 2).join('；') : '—') + ' |');
    });
    L.push('');
    L.push('### 逐检索式明细');
    L.push('');
    L.push('| # | 检索式 | 源 | 计数口径 | 自报命中 | 本次取得 | 读取状态 | 耗时(秒) | 实际检索式 |');
    L.push('|---|---|---|---|---:|---:|---|---:|---|');
    const kwOrder = [];
    const byKw = new Map();
    log.searches.forEach(r => { if (!byKw.has(r.keyword)) { byKw.set(r.keyword, []); kwOrder.push(r.keyword); } });
    (log.sourceRows || []).forEach(r => {
      const list = byKw.get(r.keyword);
      if (list) list.push(r);
    });
    let n = 0;
    kwOrder.forEach(kw => {
      const list = byKw.get(kw) || [];
      if (!list.length) {
        // 该检索式在本通道下没有源行（理论上不该发生）⇒ 显式登记，不留空白
        n++;
        L.push('| ' + n + ' | `' + String(kw).replace(/\|/g, '\\|') + '` | — | — | — | — | 无源行 | — | — |');
        return;
      }
      list.forEach(s => {
        n++;
        L.push('| ' + n + ' | `' + String(kw).replace(/\|/g, '\\|') + '` | ' + s.label
          + ' | ' + (s.countSemantics === 'exact' ? 'exact' : 'none') + ' | '
          + (s.reportedTotal === null ? '—' : s.reportedTotal) + ' | ' + s.count
          + ' | ' + (s.ok ? (COUNT_TEXT[s.countState] || s.countState) : '不可用')
          + ' | ' + (s.durationMs == null ? '—' : Math.round(s.durationMs / 100) / 10)
          + ' | ' + (s.queryUsed ? '`' + String(s.queryUsed).replace(/\|/g, '\\|').slice(0, 90) + '`' : '—') + ' |');
      });
    });
    L.push('');
    L.push('> **计数口径**：仅 `countSemantics=exact` 的源自报命中进入第 2 节合计；`none` 型源（Crossref）只贡献记录。');
    L.push('> 理由（实测）：Crossref 的 `total-results` 对布尔式与词袋返回**同一个数**（775136 / 358659），');
    L.push('> 它是「全库软匹配规模」而非本次检索的命中数，一旦相加会让计数凭空放大四个数量级。');
    L.push('> **「不可用」= 该源本次请求失败/超时/限流**：失败只影响该源（失败隔离），其余源照常给出读数 ⇒ ');
    L.push('> 某源不可用**不代表检索式无效**；「不适用」同理（本次没有能计数的源），二者都不是 0 命中。');
    L.push('');
  }

  L.push('## 3. PRISMA 流程计数');
  L.push('');
  // 图与 ASCII 版并存：图负责阅读，ASCII 负责在纯文本环境兜底。两者数字同源，绝不各自算。
  if (opts.svg) {
    L.push('![PRISMA 流程计数图](PRISMA.svg)');
    L.push('');
    L.push('> 上图由 `lib/prisma-diagram.cjs` 依据同一份 `prisma.json` 生成（不重新计算）；下方 ASCII 版为纯文本兜底。');
    L.push('');
  } else if (opts.svgError) {
    L.push('> ⚠ **流程图未生成**：' + opts.svgError + ' —— 请以本节 ASCII 版为准。');
    L.push('');
  }
  L.push('```');
  L.push('识别 Identification ──────────────────────────────');
  const unknown = log.identification.reportedTotalUnknownKeywords || [];
  L.push('  数据库自报命中（合计）            ' + fmtNum(log.identification.reportedTotalBySite) + ' 条'
    + (unknown.length ? '（' + unknown.join('、') + ' 未读到计数 ⇒ 合计偏低，**不等于 0 命中**）' : ''));
  L.push('  实际导出（受每条上限约束）        ' + log.identification.recordsRetrieved + ' 条');
  L.push('                    │');
  L.push('筛选 Screening ──────┼────────────────────────────');
  L.push('  进入去重              ' + log.screening.recordsAvailable + ' 条');
  L.push('  去重移除              ' + fmtNum(log.screening.duplicatesRemoved) + ' 条'
    + (log.screening.dedupePerformed ? '' : '（本次未去重）'));
  L.push('  去重后剩余            ' + log.screening.recordsAfterDuplicates + ' 条');
  L.push('                    │');
  L.push('资格 Eligibility ───┼────────────────────────────');
  L.push('  进入资格评估          ' + log.eligibility.recordsAssessed + ' 条');
  L.push('  工具自动排除          ' + log.eligibility.excludedByTool + ' 条  ← 恒为 0，本工具不做资格判断');
  L.push('                    │');
  L.push('纳入 Included ──────┴────────────────────────────');
  L.push('  最终纳入              ' + log.included.recordsIncluded + ' 条');
  L.push('  其中需人工复核标记      ' + fmtNum(log.included.flaggedForReview) + ' 条（仍计入纳入数，非排除）');
  L.push('```');
  L.push('');
  if (log.noResultKeywords.length) {
    L.push('**无结果关键词（0 条抓取且无异常）**：' + log.noResultKeywords.map(k => '`' + k + '`').join('、'));
    L.push('');
  }
  if (log.abnormalKeywords.length) {
    L.push('**异常中断关键词**：');
    L.push('');
    L.push('| 检索式 | 中断原因 |');
    L.push('|---|---|');
    log.abnormalKeywords.forEach(a => L.push('| `' + a.keyword + '` | ' + a.reason + ' |'));
    L.push('');
  }

  if (log.evidenceSummary) {
    const es = log.evidenceSummary;
    L.push('## 4. 证据分级候选分布（决策辅助，非排除依据）');
    L.push('');
    L.push('| 证据等级候选 | 条数 | 含义 |');
    L.push('|---|---:|---|');
    ['A', 'B', 'C', 'D'].forEach(g => {
      if (!es.gradeStat[g]) return;
      L.push('| ' + g + ' | ' + es.gradeStat[g] + ' | ' + GRADE_NOTE[g] + ' |');
    });
    L.push('');
    L.push('| 研究设计候选 | 条数 |');
    L.push('|---|---:|');
    Object.entries(es.designStat).sort((a, b) => b[1] - a[1]).forEach(([k, v]) => L.push('| ' + DESIGN_LABEL[k] + ' | ' + v + ' |'));
    L.push('');
    L.push('| 物种相关性 | 条数 |');
    L.push('|---|---:|');
    const SP = { target_species: '犬猫靶动物', mixed_species: '混杂多物种（需人工剔除）', non_target_animal: '非靶动物（畜禽/啮齿/人）', in_vitro_only: '仅体外', unclear: '未识别到物种' };
    Object.entries(es.speciesStat).sort((a, b) => b[1] - a[1]).forEach(([k, v]) => L.push('| ' + (SP[k] || k) + ' | ' + v + ' |'));
    L.push('');
    L.push('| 复核标记 | 条数 |');
    L.push('|---|---:|');
    const FLAG = {
      non_target_species_verify: '物种可能不是犬猫靶动物 — 源清单「十二」明确提醒需人工排除畜禽文献',
      design_conflict: '设计信号互相冲突',
      grading_from_snippet_only: '仅依据摘要节选分级（未补全全文摘要），可靠性低',
      grading_from_title_only: '仅依据标题分级，可靠性极低',
      design_unknown: '未识别到研究设计',
      small_sample_check: '样本量 <8，需确认统计效力',
      review_not_primary: '综述/述评类，非原始研究',
      in_vitro_target_species_cells: '靶动物细胞体外试验，不能直接等同于活体证据',
      text_too_short: '文本过短未分级（多为无摘要的早期文献）',
      no_engine_run: '文本不足已跳过分级引擎',
    };
    Object.entries(es.flagStat).sort((a, b) => b[1] - a[1]).forEach(([k, v]) => L.push('| ' + (FLAG[k] || k) + ' | ' + v + ' |'));
    L.push('');
  }

  L.push('## 5. 方法学限制（须随结果一并引用）');
  L.push('');
  log.limitations.forEach((t, i) => L.push((i + 1) + '. ' + t));
  L.push('');
  L.push('---');
  L.push('');
  L.push('本日志遵循 PRISMA 2020 的流程分段命名（Identification / Screening / Eligibility / Included），');
  L.push('但因数据源为学术搜索引擎镜像且未做人工资格评估，**不可作为正式系统综述的 PRISMA flow diagram 直接使用**。');
  L.push('');
  return L.join('\n');
}

const DESIGN_LABEL = {
  L1: 'L1 系统综述/Meta 分析', L2: 'L2 随机对照试验', L3: 'L3 对照/交叉/饲喂试验',
  L4: 'L4 观察性/病例报告/体外', L5: 'L5 叙述性综述/建模', U: 'U 未识别设计',
};

/**
 * 写入 PRISMA.md / prisma.json / PRISMA.svg，返回文件路径。
 *
 * 顺序有讲究：**先算图 → 再写图 → 最后写 md**。因为 md 里的 `![](PRISMA.svg)`
 * 必须与实际落盘结果一致；若反过来先写 md，一旦出图失败，md 就带着断链引用，
 * 读者看到的是破图，而不是「请以 ASCII 版为准」这句该看到的话。
 *
 * 出图失败**不**影响 md/json 落盘（存档优先），但原因会写进 md 并回传给调用方（不静默）。
 *
 * @param {string} outDir
 * @param {object} log
 * @param {object} [opts]
 * @param {boolean} [opts.svg=false] 是否出图（默认 false，保持旧调用方行为不变）
 */
function writeLog(outDir, log, opts = {}) {
  fs.mkdirSync(outDir, { recursive: true });
  const mdPath = path.join(outDir, 'PRISMA.md');
  const jsonPath = path.join(outDir, 'prisma.json');

  let svgPath = null;
  let svgError = null;
  if (opts.svg) {
    try {
      const { writeSvg } = require('./prisma-diagram.cjs');
      svgPath = writeSvg(outDir, log);
    } catch (e) {
      // 不变式违反（计数被篡改/数据异常）或写盘失败 ⇒ 大声报错，不画，也不假装画了
      svgError = String((e && e.message) || e).slice(0, 240);
      console.error('[ERROR] PRISMA 流程图生成失败（PRISMA.md 的 ASCII 版仍完整）: ' + svgError);
    }
  }

  fs.writeFileSync(mdPath, renderMarkdown(log, { svg: !!svgPath, svgError }), 'utf8');
  fs.writeFileSync(jsonPath, JSON.stringify(log, null, 2), 'utf8');
  return { mdPath, jsonPath, svgPath, svgError };
}

module.exports = { VERSION, buildLog, renderMarkdown, writeLog };
