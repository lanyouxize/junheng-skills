#!/usr/bin/env node
/* eslint-disable */
/**
 * assemble-report.cjs — 汇总为中英对照 Markdown 报告 + CSV（v4）
 *
 * 用法: node assemble-report.cjs --dir <search 输出目录> [--md 报告.md] [--csv 报告.csv] [--format both]
 *       [--no-charts] [--no-synthesis]
 *       （`--out` 与 `--dir` 等价，避免与 search-papers 的方向记反）
 * 读取: <dir>/raw/*.json 与 <dir>/summary.json
 *
 * 输出规范:
 *   - 每条「英文在上、中文在下」段落式对照，字段顺序固定；
 *   - 中文为站点「翻译本页结果」AI 译文（报告头注明），脚本不改写、不补写；
 *   - 摘要节选如实标注（站点只给节选，不冒充完整摘要）；
 *   - 若启用 --enrich，完整摘要来自 Europe PMC 原文摘要，单独成段并标注来源与匹配状态；
 *   - 空结果/异常关键词必须在报告中显式列出（不得静默丢失）。
 *
 * v4 新增（见 CHANGELOG.md）:
 *   - 每个 raw 文件独立 try/catch：单文件损坏不再毁掉整份报告，改为跳过 + 显式登记；
 *   - 按 summary.runId 过滤非本次运行的陈旧 raw，并列出「已忽略」清单（v3 是静默并入）；
 *   - 无可识别 runId 时**不过滤**，保证旧产物仍能出报告（新旧兼容分支，零回归的基础）。
 */
'use strict';
const fs = require('fs');
const path = require('path');
const { CliError, fail, needVal } = require('./lib/cli.cjs');

function parseArgs(argv) {
  const a = { dir: null, md: null, csv: null, format: 'both', charts: true, synthesis: true };
  for (let i = 2; i < argv.length; i++) {
    const t = argv[i];
    if (t === '--dir' || t === '--out') { a.dir = needVal(argv, i, t, 'OUT_DIR'); i++; }
    else if (t === '--md') { a.md = needVal(argv, i, t, 'report.md'); i++; }
    else if (t === '--csv') { a.csv = needVal(argv, i, t, 'report.csv'); i++; }
    else if (t === '--format') { a.format = needVal(argv, i, t, 'both'); i++; }
    // v4.11：证据分布图默认出（新增文件，不改既有产物内容）；显式关闭用于「只要表不要图」的场景
    else if (t === '--charts') { a.charts = true; }
    else if (t === '--no-charts') { a.charts = false; }
    // v4.12：综合归纳章节默认出（新增章节，不改既有内容）
    else if (t === '--synthesis') { a.synthesis = true; }
    else if (t === '--no-synthesis') { a.synthesis = false; }
    else fail('未知参数: ' + t + '\n  支持: --dir/--out, --md, --csv, --format, --charts, --no-charts, --synthesis, --no-synthesis');
  }
  if (!a.dir) fail('必须提供 --dir <search 输出目录>\n  示例: --dir OUT_DIR（`--out` 与 `--dir` 等价）');
  return a;
}

const csvEsc = v => {
  if (v == null) return '';
  const s = String(v);
  return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
};

/** 多行文本转 Markdown 引用块（每行加 >，防止第二行脱离引用） */
const quote = t => String(t == null ? '' : t)
  .split(/\r?\n/)
  .map(l => '> ' + (l.trim() || ''))
  .join('\n');

/** 证据分级：人类可读的行渲染（候选值 + 置信度 + 依据，缺一不可） */
const FLAG_LABEL = {
  non_target_species_verify: '物种疑似非犬猫靶动物（需人工排除）',
  design_conflict: '设计信号冲突',
  grading_from_snippet_only: '仅依据摘要节选分级（可靠性低）',
  grading_from_title_only: '仅依据标题分级（可靠性极低）',
  design_unknown: '未识别到研究设计',
  small_sample_check: '样本量 <8，需确认统计效力',
  review_not_primary: '综述/述评，非原始研究',
  in_vitro_target_species_cells: '靶动物细胞体外试验，非活体证据',
  text_too_short: '文本过短未分级（多为无摘要的早期文献）',
  no_engine_run: '文本不足已跳过分级引擎',
};
function evidenceLines(ev) {
  if (!ev) return [];
  const X = [];
  X.push('- **证据等级候选**: ' + ev.evidenceGrade + ' — ' + ev.evidenceGradeLabel
    // ★v4.3：D 档成因分开呈现 —— 「设计未识别（信息不足）」与「已判定但证据薄弱」不再混为一谈。
    //   仅当字段存在时渲染（旧 raw 无此字段 ⇒ 输出与旧版逐字节一致，零回归）。
    + (ev.gradeBasis === 'design_unrecognized' ? '（**设计未识别所致**，非确证薄弱；建议补全文后再判）' : '')
    + (ev.gradeBasis === 'text_too_short' ? '（**文本过短未分级**）' : '')
    + (ev.inputs.abstractSource === 'epmc_full' ? '' : '（依据摘要' + (ev.inputs.abstractSource === 'site_snippet' ? '节选' : '标题') + '，可靠性受限）'));
  X.push('- **研究设计候选**: ' + ev.designLevel.value + ' ' + ev.designLevel.label + '（置信度: ' + ev.designLevel.confidence + '）');
  const ev0 = (ev.designLevel.candidates || [])[0];
  if (ev0 && ev0.evidence && ev0.evidence[0]) X.push('  - 依据原文: ' + String(ev0.evidence[0]).replace(/\s+/g, ' ').slice(0, 160));
  // raw/*.json 可能由旧版本脚本写出，字段不一定齐全 → 一律防御式读取，不得假设存在
  const sr = ev.speciesRelevance || {};
  X.push('- **物种相关性**: ' + (sr.label || '未知') + '（置信度: ' + (sr.confidence || 'none') + '）'
    + ((sr.targetSpecies || []).length ? '，靶动物: ' + sr.targetSpecies.join('、') : ''));
  X.push('- **样本量候选**: ' + (ev.sampleSize.value != null ? 'n=' + ev.sampleSize.value : '未识别')
    + '（置信度: ' + ev.sampleSize.confidence + '）');
  if (ev.sampleSize.candidates && ev.sampleSize.candidates[0]) X.push('  - 依据原文: ' + String(ev.sampleSize.candidates[0].evidence).replace(/\s+/g, ' ').slice(0, 160));
  if (ev.dose.candidates && ev.dose.candidates.length) {
    X.push('- **剂量/添加水平候选**: ' + ev.dose.candidates.map(d => d.raw).join('；'));
  }
  if (ev.includedStudies && ev.includedStudies.value != null) X.push('- **纳入研究数（综述）**: ' + ev.includedStudies.value);
  if (ev.recency) X.push('- **发表年**: ' + (ev.publicationYear || '未知') + '（' + ev.recency + '）');
  if (ev.flags && ev.flags.length) {
    X.push('- **复核标记**: ' + ev.flags.map(f => FLAG_LABEL[f] || f).join('；'));
  }
  X.push('> ⚠ 以上均为**启发式候选值**，needsReview=' + ev.needsReview + '，经人工核对原文方法学章节前不得用于宣称支撑。');
  return X;
}

/**
 * 读取 raw 目录并按 runId 分流。返回四类：
 *   groups         纳入报告的
 *   skippedCorrupt 解析失败（损坏）——跳过并登记，绝不让整份报告崩掉
 *   skippedStale   属于「非本次运行」——跳过并登记，绝不静默并入
 *   legacyNoRunId  本次 summary 有 runId 但该文件没有——按旧版本兼容纳入
 * summaryRunId 为 null（旧版 summary）时一律不过滤，保证旧产物可复现。
 */
function readRawGroups(rawDir, summaryRunId) {
  const files = fs.existsSync(rawDir) ? fs.readdirSync(rawDir).filter(f => f.endsWith('.json')).sort() : [];
  const groups = [];
  const skippedCorrupt = [];
  const skippedStale = [];
  const legacyNoRunId = [];
  for (const f of files) {
    let g;
    try {
      g = JSON.parse(fs.readFileSync(path.join(rawDir, f), 'utf8'));
    } catch (e) {
      skippedCorrupt.push({ file: f, error: String((e && e.message) || e).replace(/\s+/g, ' ').slice(0, 160) });
      continue;
    }
    const rid = (g && g.runId) || null;
    if (summaryRunId && rid && rid !== summaryRunId) { skippedStale.push({ file: f, runId: rid }); continue; }
    if (summaryRunId && !rid) legacyNoRunId.push(f);
    groups.push(g);
  }
  return { groups, skippedCorrupt, skippedStale, legacyNoRunId };
}

/** 由 opts 汇总出报告与 CSV；返回输出清单。抽成独立函数以便离线单测直接调用（不经过 CLI）。 */
function assemble(opts) {
  const rawDir = path.join(opts.dir, 'raw');
  let summary = null;
  let summaryError = null;
  try { summary = JSON.parse(fs.readFileSync(path.join(opts.dir, 'summary.json'), 'utf8')); } catch (e) { summaryError = e; }
  if (summaryError) {
    console.error('[WARN] summary.json 缺失或解析失败，关键词补全与质量统计将缺失: ' + String(summaryError).replace(/\s+/g, ' ').slice(0, 160));
  }
  const summaryRunId = (summary && summary.runId) || null;

  // raw 目录可能缺失（全部关键词均无条目）→ 不能因此崩溃；单文件损坏同理，逐个兜住
  const { groups, skippedCorrupt, skippedStale, legacyNoRunId } = readRawGroups(rawDir, summaryRunId);
  const seen = new Set(groups.map(g => g.keyword));
  // 补全：summary 中记录过但 raw 无文件的关键词（空结果/异常）必须显式列出
  const missing = summary ? Object.keys(summary.keywords || {}).filter(k => !seen.has(k)) : [];
  for (const k of missing) groups.push({ keyword: k, records: [], aborted: (summary.keywords[k] || {}).aborted });

  const total = groups.reduce((s, g) => s + (g.records || []).length, 0);
  const anyTranslated = groups.some(g => (g.records || []).some(r => r.translatedBySite));
  const anyEnriched = groups.some(g => (g.records || []).some(r => r.enrich && r.enrich.abstractFull));

  const L = [];
  L.push('# 论文检索·中英对照报告');
  L.push('');
  L.push('| 项目 | 内容 |');
  L.push('|---|---|');
  L.push('| 检索时间 | ' + ((summary && summary.startedAt) || '-') + ' |');
  L.push('| 检索通道 | ' + ((summary && summary.site) || '-') + '（数据来源 Google Scholar 镜像） |');
  L.push('| 关键词 | ' + groups.map(g => g.keyword + '（' + (g.records || []).length + ' 条）').join('；') + ' |');
  L.push('| 合计 | ' + total + ' 条 |');
  L.push('| 中文来源 | ' + (anyTranslated ? '站点「翻译本页结果」AI 译文（非人工校对）' : '本批次未获取站点译文') + ' |');
  L.push('| 摘要说明 | 检索页展示的是**摘要节选**（约 2 行、以 `…` 截断），非完整摘要' + (anyEnriched ? '；完整摘要另见各条「完整摘要（Europe PMC）」段，仅当匹配成功时出现' : '') + ' |');
  if (summary && summary.qc) L.push('| 质量自检 | 标题 ' + (summary.qc.fill.title * 100).toFixed(0) + '% / 作者 ' + (summary.qc.fill.authors * 100).toFixed(0) + '% / 来源 ' + (summary.qc.fill.source * 100).toFixed(0) + '% / 年份 ' + (summary.qc.fill.year * 100).toFixed(0) + '% / 摘要 ' + (summary.qc.fill.abstract * 100).toFixed(0) + '% / 中文 ' + (summary.qc.fill.zh * 100).toFixed(0) + '% |');
  if (summary && summary.enrichStat) L.push('| 补全统计 | ' + Object.entries(summary.enrichStat).map(([k, v]) => k + ':' + v).join('，') + ' |');
  if (summary && summary.dedupe) L.push('| 去重统计 | 合计 ' + summary.dedupe.total + ' / 唯一 ' + summary.dedupe.unique + ' / 重复 ' + summary.dedupe.duplicates + ' |');
  // ★v4.10 全文通道：把「有多少篇真能读全文」摆到汇总里。
  //   旧版只知道「是否 OA」，读者无法区分「OA 且有全文」与「自称 OA 但无入口」。
  if (summary && summary.fulltext) {
    const ft = summary.fulltext;
    if (ft.byTier) {
      // v4.15（B 批）新格式：按回退层级呈现「从哪一级拿到的」。
      // 旧格式只有「有/无 PMC 全文」，读者看不出「6 篇 XML」与「3 篇 HTML」的差别，
      // 而这两者的证据强度不同（XML 有章节结构，能定位方法学节；HTML 没有）。
      const label = {
        T1_epmc_xml: 'T1 结构化XML', T2_pmc_html: 'T2 正文HTML',
        T2b_pmc_pdf: 'T2b PMC PDF', T3_unpaywall: 'T3 Unpaywall',
        T3b_unpaywall_pdf: 'T3b Unpaywall PDF', T4_publisher: 'T4 出版商页',
      };
      const dist = Object.entries(ft.byTier || {}).map(([k, v]) => (label[k] || k) + ':' + v).join('，') || '—';
      const bits = [
        '可试入口 ' + (ft.withEntry || 0) + ' / ' + (ft.records || 0),
        '已取 ' + (ft.ok || 0) + '（新抓 ' + ((ft.ok || 0) - (ft.cached || 0)) + '，缓存 ' + (ft.cached || 0) + '）',
        '按级 ' + dist,
      ];
      if (ft.failed) bits.push('**未取 ' + ft.failed + '**');
      if (ft.pdfOnly) bits.push('**仅 PDF ' + ft.pdfOnly + '**');
      if (ft.noEntry) bits.push('无入口 ' + ft.noEntry);
      L.push('| 全文通道 | ' + bits.join('，') + ' |');
      if (ft.browserUsed) {
        L.push('| 全文通道提示 | HTTP 阶段未取到，本次启用了**浏览器兜底**（会过 JS 挑战）；浏览器不可用时该级记为 skipped，不算失败 |');
      }
    } else {
      const bits = [
        '有 PMC 全文 ' + ft.withPmcid + ' / ' + ft.records,
        '已取 ' + ((ft.ok || 0) + (ft.cached || 0)) + '（新抓 ' + (ft.ok || 0) + '，缓存 ' + (ft.cached || 0) + '）',
      ];
      if (ft.failed) bits.push('**失败 ' + ft.failed + '**');
      if (ft.oaWithoutPmcid) bits.push('**OA 但无 PMC 全文 ' + ft.oaWithoutPmcid + ' 条**');
      L.push('| 全文通道 | ' + bits.join('，') + ' |');
      if (ft.oaWithoutPmcid) {
        L.push('| 全文通道提示 | 标记 `isOA` 却无 `pmcid` 的记录**拿不到全文入口**，判定仍停在摘要级；这属 EPMC 与出版社口径不一致，**不是抓取失败** |');
      }
    }
  }
  if (summary && summary.evidence) {
    // ★v4.3：附 D 档成因分解（仅当 gradeBasisStat 存在 —— 旧 summary.json 无此字段时该行不变，零回归）
    const gb = summary.evidence.gradeBasisStat;
    L.push('| 证据分级 | ' + Object.entries(summary.evidence.gradeStat).sort().map(([k, v]) => k + ':' + v).join('，')
      + '｜需人工复核物种 ' + summary.evidence.needsManualExcludeCount + ' 条'
      + '｜低置信度 ' + summary.evidence.lowConfidenceCount + ' 条'
      + (gb ? '｜**D 档成因**：设计未识别 ' + (gb.design_unrecognized || 0) + ' 条 / 已判定但薄弱 ' + (gb.design_identified || 0) + ' 条' + (gb.text_too_short ? ' / 文本过短 ' + gb.text_too_short + ' 条' : '') : '')
      + ' |');
  }
  L.push('');
  if (summary && summary.errors && summary.errors.length) {
    L.push('> ⚠ 异常：');
    summary.errors.forEach(e => L.push('> - ' + e));
    L.push('');
  }
  if (summary && summary.warnings && summary.warnings.length) {
    L.push('> ℹ 提醒：');
    summary.warnings.forEach(e => L.push('> - ' + e));
    L.push('');
  }
  // v4：被跳过/被忽略的文件必须显式列出（v3 会静默并入陈旧数据、或因单个损坏文件整份崩掉）。
  // 三个清单均为空时这里不推任何行 —— 这正是「零回归」得以成立的前提。
  if (skippedStale.length) {
    L.push('> ⚠ 已忽略 ' + skippedStale.length + ' 个非本次运行的陈旧 raw 文件（runId 不匹配，未计入任何统计）：');
    skippedStale.forEach(s => L.push('> - `' + s.file + '`（runId: ' + s.runId + '）'));
    L.push('');
  }
  if (skippedCorrupt.length) {
    L.push('> ⚠ 已跳过 ' + skippedCorrupt.length + ' 个损坏的 raw 文件（JSON 解析失败，未计入任何统计）：');
    skippedCorrupt.forEach(s => L.push('> - `' + s.file + '`（' + s.error + '）'));
    L.push('');
  }
  if (legacyNoRunId.length) {
    L.push('> ℹ 本次 summary 标记了 runId，但有 ' + legacyNoRunId.length + ' 个 raw 文件未标记 runId（按旧版本兼容纳入）：');
    legacyNoRunId.forEach(f => L.push('> - `' + f + '`'));
    L.push('');
  }

  // 证据分级候选一览：按等级排序给出筛选视图（提升审核效率，不替代逐条核对）
  const graded = [];
  for (const g of groups) for (const r of (g.records || [])) if (r.evidence) graded.push({ g, r });
  // ★v4.11 证据分布三张图：与下表**同一份** evidence 数据（不重算等级）。
  //   不变式（各档之和 = 总数）不通过时 writeCharts 抛错并回来，报告仍完整，且**明写**失败原因
  //   —— 图可以是空的，但不能是假的。
  let chartsStat = null;
  const chartsErrors = [];
  const chartFiles = [];
  let synthStat = null;
  const synthesisErrors = [];
  if (graded.length && opts.charts !== false) {
    try {
      const { writeCharts } = require('./lib/evidence-charts.cjs');
      const cw = writeCharts(opts.dir, graded.map((x) => x.r));
      chartsStat = cw.stats;
      for (const e of cw.errors) chartsErrors.push(e);
      for (const c of cw.charts) chartFiles.push(c);
    } catch (e) {
      chartsErrors.push(String((e && e.message) || e).slice(0, 300));
    }
  }

  if (graded.length) {
    const order = { A: 0, B: 1, C: 2, D: 3 };
    // ★v4.12 排序比较器必须防 NaN：旧写法 `(y.r.year || 0) - (x.r.year || 0)` 在遇到
    //   `n.d.` / `待定` 这类字符串时相减得 NaN，比较器返回 NaN 被视作 0 ⇒ **2019 会排到 1998 后面**
    //   （实测复现）。改为「先判相等再比大小」，并把非数字年份映射为 -Infinity 使其沉底。
    const yearKey = (r) => {
      const n = Number(r && r.year);
      return Number.isFinite(n) ? n : -Infinity;
    };
    graded.sort((x, y) => {
      const d = order[x.r.evidence.evidenceGrade] - order[y.r.evidence.evidenceGrade];
      if (d) return d;
      const ax = yearKey(x.r);
      const ay = yearKey(y.r);
      if (ax === ay) return 0;
      return ay > ax ? 1 : -1;          // 年份倒序；不用相减，避免 -Inf - -Inf = NaN
    });
    // ★v4.12 综合归纳：**必须**在本 sort 之后生成 —— 归纳句里的 `[#n]` 就是下方表格的 `#` 列，
    //   换排序就会指错行。归纳失败不拖垮报告，只在本节位置明写原因。
    if (opts.synthesis !== false) {
      try {
        const { buildSynthesis } = require('./lib/synthesis.cjs');
        const startedYear = summary && summary.startedAt ? new Date(summary.startedAt).getUTCFullYear() : undefined;
        const sy = buildSynthesis(graded, {
          flagLabel: FLAG_LABEL,
          keywords: groups.map(g => g.keyword),
          nowYear: startedYear,
        });
        synthStat = sy.stats;
        for (const line of sy.md) L.push(line);
      } catch (e) {
        synthesisErrors.push(String((e && e.message) || e).slice(0, 300));
        L.push('> ⚠ 综合归纳未生成（报告其余部分完整）：' + synthesisErrors[0]);
        L.push('');
      }
    }
    // 图在前、表在后：先看形状，再逐条核 —— 表格 67 行看不出「A 只有 2 条且有 1 条来自体外」。
    if (chartFiles.length) {
      L.push('## 证据分布图');
      L.push('');
      L.push('> 三张图由 `lib/evidence-charts.cjs` 依据**同一份** evidence 数据生成，不重算任何等级；' +
        '斜纹 = 未经人工确认的启发式候选（纯色 = 已人工确认）。图的数字与下方表格逐条对应。');
      // ★「不是结论」必须在报告正文里说出来，不能只藏在 SVG 里 —— 只读 markdown 的人也要看到。
      if (chartsStat) {
        L.push('>');
        L.push(chartsStat.confirmedCount === 0
          ? '> ⚠ **这是待审清单的分布，不是结论**：全部 ' + chartsStat.total +
            ' 条均为启发式候选（needsReview），未经人工核对原文方法学章节前，任何一档都不得用于宣称支撑。'
          : '> ⚠ 已人工确认 ' + chartsStat.confirmedCount + ' 条（纯色），其余 ' + chartsStat.candidateCount +
            ' 条仍为候选（斜纹）：候选部分同样不得用于宣称支撑。');
      }
      L.push('');
      const CAP = {
        'evidence-grade-dist.svg': '各档记录数与占比；D 档另附成因分解（设计未识别 ≠ 证据薄弱）。',
        'evidence-grade-species.svg': '等级 × 物种相关性二维投影；体外/非靶动物格里的 A 是复核重点。',
        'evidence-year-grade.svg': '按年份堆叠各档；「未标注」列与时间轴断开，表示年份缺失而非某一年。',
      };
      for (const c of chartFiles) {
        L.push('### ' + c.title);
        L.push('');
        L.push('![' + c.title + '](charts/' + c.file + ')');
        L.push('');
        if (CAP[c.file]) { L.push('> ' + CAP[c.file]); L.push(''); }
      }
      L.push('---');
      L.push('');
    }
    if (chartsErrors.length) {
      L.push('> ⚠ 证据分布图未生成（报告其余部分完整，表格不受影响）：');
      chartsErrors.forEach(e => L.push('> - ' + e));
      L.push('');
    }
    L.push('## 证据分级候选一览（需逐条人工确认）');
    L.push('');
    L.push('| # | 等级 | 研究设计候选 | 物种相关性 | n | 年份 | 标题 |');
    L.push('|---|---:|---|---|---:|---:|---|');
    graded.forEach((x, i) => {
      const ev = x.r.evidence;
      L.push('| ' + (i + 1) + ' | **' + ev.evidenceGrade + '** | ' + ev.designLevel.value + ' ' + ev.designLevel.label
        + ' | ' + ev.speciesRelevance.label + ' | ' + (ev.sampleSize.value != null ? ev.sampleSize.value : '—')
        + ' | ' + (x.r.year || '—') + ' | ' + String(x.r.titleEn || '').replace(/\|/g, '\\|').slice(0, 70) + ' |');
    });
    L.push('');
    const flagged = graded.filter(x => x.r.evidence.flags && x.r.evidence.flags.length);
    if (flagged.length) {
      L.push('### 需人工处理条目');
      L.push('');
      L.push('| # | 标题 | 复核标记 |');
      L.push('|---|---|---|');
      flagged.forEach((x, i) => {
        L.push('| ' + (i + 1) + ' | ' + String(x.r.titleEn || '').replace(/\|/g, '\\|').slice(0, 60)
          + ' | ' + x.r.evidence.flags.map(f => FLAG_LABEL[f] || f).join('；') + ' |');
      });
      L.push('');
    }
    L.push('---');
    L.push('');
  }

  for (const g of groups) {
    const recs = g.records || [];
    L.push('## 关键词：' + g.keyword + '（' + recs.length + ' 条）');
    L.push('');
    if (!recs.length) {
      L.push('_未获取到结果' + (g.aborted ? '（中止原因: ' + g.aborted + '）' : '') + '。_');
      L.push('');
      continue;
    }
    recs.forEach((r, i) => {
      L.push('### [' + (i + 1) + '] ' + (r.titleEn || '(无英文标题)'));
      L.push('');
      if (r.authors) L.push('- **作者**: ' + r.authors);
      if (r.source) L.push('- **来源/期刊**: ' + r.source);
      if (r.year) L.push('- **年份**: ' + r.year);
      if (r.citedBy != null) L.push('- **被引**: ' + r.citedBy);
      if (r.enrich && r.enrich.journalFull) L.push('- **期刊全名**: ' + r.enrich.journalFull);
      if (r.enrich && r.enrich.doi) L.push('- **DOI**: ' + r.enrich.doi);
      else if (r.doiFromUrl) L.push('- **DOI(据直链抽取)**: ' + r.doiFromUrl);
      // ★v4.10：全文入口。有 pmcid 才给链接；「自称 OA 却无 pmcid」必须显式写出，
      //   否则读者会以为全文通道已覆盖它（实际拿不到任何入口）。
      if (r.enrich && r.enrich.pmcid) {
        const ftUrl = r.enrich.fullTextUrl || ('https://europepmc.org/articles/' + r.enrich.pmcid);
        L.push('- **全文**: [' + r.enrich.pmcid + '](' + ftUrl + ')'
          + (r.enrich.license ? ' · 许可 ' + r.enrich.license : ' · 许可未标注（**不得假定可再用**）')
          + (r.enrich.hasPDF === false ? ' · 无 PDF' : ''));
      } else if (r.enrich && r.enrich.isOA) {
        L.push('- **全文**: _标记开放获取但无 `pmcid` ⇒ 取不到全文入口（判定仍为摘要级）_');
      }
      if (r.enrich && r.enrich.funders) L.push('- **资助方**: ' + r.enrich.funders.join('；') + '（COI 参考，**不参与分级**）');
      if (r.domain) L.push('- **来源域**: ' + r.domain);
      L.push('- **链接**: 论文页 ' + (r.paperUrl || '-') + ' ｜ 原文 ' + (r.sourceUrl || '-'));
      if (r.duplicateOf) L.push('- **重复提示**: 与关键词「' + r.duplicateOf.keyword + '」第 ' + r.duplicateOf.idx + ' 条为同一篇');
      L.push('');
      L.push('**Abstract (节选, English)**');
      L.push('');
      L.push(quote(r.abstractEn || '_（检索页未展示摘要）_'));
      L.push('');
      if (r.enrich && r.enrich.abstractFull) {
        L.push('**完整摘要（Europe PMC 原文摘要，非改写）**');
        L.push('');
        L.push(quote(r.enrich.abstractFull));
        L.push('');
      } else if (r.enrich) {
        L.push('_完整摘要补全状态: ' + r.enrich.status + (r.enrich.status === 'unmatched' ? '（未匹配，未采用任何推测值）' : '') + '_');
        L.push('');
      }
      // ★v4.10 方法学信号：只呈现「全文里写了什么」，不据此改等级（分级仍由 evidence.cjs 的候选给出）
      if (r.fulltext && r.fulltext.status === 'ok') {
        const sigs = (r.fulltext.signals || []).filter(s => s.scope === 'methods');
        // v4.15：必须标出来源层级 —— XML 有真实章节结构，HTML 只能靠文本标题匹配定位方法学节，
        // 两者的定位可靠性不同，混在一起呈现会让读者高估 HTML 来源的精度。
        const TIER_NOTE = {
          T1_epmc_xml: '（来源：Europe PMC JATS XML，章节结构完整）',
          T2_pmc_html: '（来源：PMC 正文 HTML，**无章节结构**，方法学节靠文本标题匹配）',
          T2b_pmc_pdf: '（来源：PMC PDF 抽取（扫描件的 OCR 文字层），**无章节结构**，文字可能含 OCR 误识）',
          T3_unpaywall: '（来源：Unpaywall 定位的开放获取页面）',
          T3b_unpaywall_pdf: '（来源：Unpaywall 定位的开放获取 PDF，经零依赖抽取）',
          T4_publisher: '（来源：出版商页面渲染结果，可能不含全文）',
        };
        L.push('**方法学信号（全文抽取，供人工定级；自动等级不变）**' + (TIER_NOTE[r.fulltext.tier] || ''));
        L.push('');
        if (sigs.length) {
          L.push('| 信号 | 命中片段 | 全文偏移 |');
          L.push('|---|---|---|');
          sigs.forEach(s => L.push('| ' + s.label + ' | `' + String(s.matched).replace(/\|/g, '\\|') + '` | @' + s.offset + ' |'));
          L.push('');
          L.push('> 偏移量相对 `fulltext/' + r.fulltext.textFile + '`，可直接按该位置核对原文。');
        } else {
          L.push('_全文已取（' + (r.fulltext.methods ? r.fulltext.methods.chars + ' 字方法学节' : '未见独立方法学节')
            + '），但未命中方法学关键词 —— 这**不代表没做**，只代表没写成这些表述。_');
        }
        L.push('');
      } else if (r.fulltext) {
        L.push('_全文: ' + r.fulltext.status + '（未取得；**等级不因此改变**）_');
        L.push('');
      }
      L.push('**中文对照（站点 AI 翻译）**');
      L.push('');
      if (r.titleZh || r.abstractZh) {
        L.push(quote('**标题译文**: ' + (r.titleZh || '（缺）')));
        L.push('>');
        L.push(quote('**摘要节选译文**: ' + (r.abstractZh || '（缺）')));
      } else {
        L.push('> _（未获取到站点译文）_');
      }
      L.push('');
      if (r.evidence) {
        L.push('**证据分级候选（未经人工确认）**');
        L.push('');
        evidenceLines(r.evidence).forEach(l => L.push(l));
        L.push('');
      }
      L.push('---');
      L.push('');
    });
  }
  fs.writeFileSync(opts.md || path.join(opts.dir, 'report.md'), L.join('\n'), 'utf8');

  const header = ['keyword', 'idx', 'title_en', 'title_zh', 'authors', 'source', 'journal_full', 'year', 'cited_by', 'doi', 'abstract_en', 'abstract_full', 'abstract_full_status', 'abstract_zh', 'paper_url', 'source_url', 'page', 'duplicate_of'
    // 证据分级列（候选值，需人工确认）
    , 'evidence_grade', 'evidence_design_level', 'evidence_design_label', 'species_relevance', 'sample_size', 'dose_candidates', 'evidence_confidence', 'evidence_flags', 'needs_review'];
  const rows = [header.join(',')];
  for (const g of groups) for (const r of (g.records || [])) {
    const ev = r.evidence;
    rows.push([g.keyword, r.idx, r.titleEn, r.titleZh, r.authors, r.source,
      (r.enrich && r.enrich.journalFull) || null, r.year, r.citedBy,
      (r.enrich && r.enrich.doi) || r.doiFromUrl || null,
      r.abstractEn, (r.enrich && r.enrich.abstractFull) || null, (r.enrich && r.enrich.status) || null,
      r.abstractZh, r.paperUrl, r.sourceUrl, r.page,
      r.duplicateOf ? (r.duplicateOf.keyword + '#' + r.duplicateOf.idx) : null,
      ev ? ev.evidenceGrade : null, ev ? ev.designLevel.value : null, ev ? ev.designLevel.label : null,
      ev ? ev.speciesRelevance.relevance : null, ev ? ev.sampleSize.value : null,
      ev && ev.dose.candidates.length ? ev.dose.candidates.map(d => d.raw).join('; ') : null,
      ev ? ev.confidence : null,
      ev && ev.flags.length ? ev.flags.join('; ') : null,
      ev ? ev.needsReview : null].map(csvEsc).join(','));
  }
  const out = {
    md: opts.md || path.join(opts.dir, 'report.md'), total, keywords: groups.length,
    skippedStale: skippedStale.length, skippedCorrupt: skippedCorrupt.length, legacyNoRunId: legacyNoRunId.length,
    charts: chartFiles.map(c => c.path), chartErrors: chartsErrors,
    synthesisStat: synthStat, synthesisErrors: synthesisErrors,
    chartsStat: chartsStat
      ? { total: chartsStat.total, candidate: chartsStat.candidateCount, confirmed: chartsStat.confirmedCount }
      : null,
  };
  if (opts.format !== 'md') {
    const csvPath = opts.csv || path.join(opts.dir, 'report.csv');
    fs.writeFileSync(csvPath, '\ufeff' + rows.join('\r\n'), 'utf8');
    out.csv = csvPath;
  }
  return out;
}

function main(argv) {
  const out = assemble(parseArgs(argv));
  console.log(JSON.stringify(out, null, 2));
  return out;
}

module.exports = { parseArgs, readRawGroups, assemble, csvEsc, quote, evidenceLines, FLAG_LABEL };

if (require.main === module) {
  try {
    main(process.argv);
  } catch (e) {
    if (e instanceof CliError) { console.error(e.message); process.exit(e.code); }
    throw e;
  }
}
