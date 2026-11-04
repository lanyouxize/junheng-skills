#!/usr/bin/env node
/* eslint-disable */
/**
 * lib/evidence-charts.cjs — 证据分布三张图（纯 SVG，零依赖）
 *
 * 定位：把 `evidence.gradeAll()` 已经算好的**候选分级**画成分布图，不重新计算任何等级。
 *      report.md 里的「证据分级候选一览」是表格，67 行看不出形状；新增的三张图只回答三个问题：
 *        ① 等级分布（A/B/C/D 各多少）—— 图 `evidence-grade-dist.svg`
 *        ② 等级 × 物种相关性（哪些 A 其实是体外/非靶动物换来的）—— 图 `evidence-grade-species.svg`
 *        ③ 年份 × 等级（近年证据是否真的更强）—— 图 `evidence-year-grade.svg`
 *
 * ⚠ 三条诚实约束（画图时一条都不能破，破了就抛错）:
 *   1. **`needsReview` 恒为 true ⇒ 图上任何一档都不得画成「确定等级」**。
 *      本模块只认 `evidence.reviewed === true` 为「已人工确认」，其余全部按候选处理：
 *      候选段用斜纹 pattern + 虚线描边，全候选时图上另挂警示带。
 *      `needsReview: true` 是「必须复核」的声明，**不是**「待办计数」；
 *      绝不能因为它恒为 true 就把它当成可忽略的样板文字。
 *   2. **各档计数之和必须等于记录总数**。差额不为 0 ⇒ 抛错，不画一张自相矛盾的图。
 *      热力矩阵的**每一行之和也必须等于该等级计数**（同一份数据的第二种投影，必须自洽）。
 *   3. **年份缺失 ≠ 某个年份**。`year` 为 null 的记录进「未标注」列，与时间轴之间画断开标记；
 *      时间轴上年份连续（缺年份画空柱），因为「中间那年没有」本身是信息。
 *
 * 用法：
 *   const { buildCharts, writeCharts, collect, validate } = require('./evidence-charts.cjs');
 *   const { charts, stats } = buildCharts(records);   // records = [{evidence, year}]
 *   writeCharts(outDir, records);                     // 落盘三张 svg，返回 { files, errors }
 *
 * `buildCharts` 在不变式违反时**抛错**；`writeCharts` 兜住并返回 errors（报告仍完整）。
 */

'use strict';

const { esc, fmtNum } = require('./prisma-diagram.cjs');

const CHARTS_VERSION = 'evidence-charts/v1';

// ── 版式常量 ──────────────────────────────────────────────────
const W = 900;
const PAD = 24;
const CONTENT_W = W - PAD * 2;
const TITLE_H = 52;
const WARN_H = 42;
const FOOT_LINE_H = 16;

const GRADE_ORDER = ['A', 'B', 'C', 'D'];
// A 与 B 必须一眼分得开：旧值 #1a7f37 / #57ab5a 在 20px 高的堆叠段里几乎同色（实测截图确认）。
const GRADE_COLOR = { A: '#0f5132', B: '#7cc47f', C: '#bf8700', D: '#8c959f' };
const GRADE_HINT = {
  A: '靶动物 RCT/SR',
  B: '靶动物对照',
  C: '间接/观察/体外',
  D: '薄弱或信息不足',
};

/** 列 = 物种相关性。顺序固定，避免两次生成列序不同（可复现性）。 */
const SPECIES_COLS = [
  ['target_species', '犬猫靶动物'],
  ['mixed_species', '混杂多物种'],
  ['non_target_animal', '非靶动物'],
  ['in_vitro_only', '仅体外'],
  ['unclear', '未识别'],
];
const OTHER_KEY = '__other__';

const C = {
  ink: '#1f2328', sub: '#57606a', line: '#d0d7de', head: '#f6f8fa',
  warn: '#9a6700', warnBg: '#fff8e5', warnLine: '#d4a72c',
  ok: '#1a7f37', idle: '#8c959f', idleBg: '#f6f8fa', zero: '#f2f4f6',
};

// ── 文字宽度预算 ──────────────────────────────────────────────
/**
 * 按**转义后**字符串估宽（与 prisma-diagram.cjs 同一教训：`"`→`&quot;` 会让 1 字符变 6 字符，
 * 按未转义长度算宽度预算，实测能虚增 100+ px，于是「算着放得下」的文字在渲染时整行被裁）。
 */
function textWidth(s, fs) {
  const str = esc(s);
  let w = 0;
  for (const ch of str) w += ch.codePointAt(0) > 0x2e80 ? fs : fs * 0.55;
  return w;
}

/** 按像素预算截断，省略号只在真的截断时才加。 */
function clipText(s, maxPx, fs) {
  const raw = String(s === null || s === undefined ? '' : s);
  if (textWidth(raw, fs) <= maxPx) return raw;
  let out = raw;
  while (out.length > 1 && textWidth(out + '…', fs) > maxPx) out = out.slice(0, -1);
  return out + '…';
}

/** 千分位（不用 toLocaleString：受 locale 影响 ⇒ 两次生成结果可能不同）。 */
function num(n) {
  return fmtNum(n);
}

function pct(a, b) {
  if (!b || !Number.isFinite(a) || !Number.isFinite(b)) return '—';
  return (a / b * 100).toFixed(0) + '%';
}

// ── 数据收集（纯函数，不重算等级）────────────────────────────
/** 只有显式 `reviewed === true` 才算人工确认过；缺失/为 false 一律按候选。 */
function isConfirmed(rec) {
  const ev = rec && rec.evidence;
  return !!(ev && ev.reviewed === true);
}

/** 年份取值：区分 ok / missing / invalid —— **绝不**把 null 折成 0。 */
function pickYear(rec, ev) {
  const cands = [rec && rec.year, ev && ev.publicationYear];
  for (const c of cands) {
    if (c === null || c === undefined || c === '') continue;
    const n = Number(c);
    if (Number.isFinite(n) && n >= 1900 && n <= 2100) return { year: Math.trunc(n), state: 'ok' };
    return { year: null, state: 'invalid' };
  }
  return { year: null, state: 'missing' };
}

/**
 * 汇总成绘图所需的全部计数。不修改入参。
 * @returns {object} stats
 */
function collect(records) {
  const list = Array.isArray(records) ? records : [];
  const gradeStat = { A: 0, B: 0, C: 0, D: 0 };
  const confirmedStat = { A: 0, B: 0, C: 0, D: 0 };
  const gradeBasis = {};                   // 全体记录的成因分布
  const dBasis = {};                       // ★只统计 D 档：图①脚注写的是「D 档成因分解」，
                                           //   拿全体记录的数去填会得出「46+23=69 但 D 只有 54」这种自相矛盾
  const matrix = {};                       // grade -> speciesKey -> count
  const speciesTotals = {};
  const extraSpecies = [];                 // 未登记过的 relevance 值（代码演进时）
  const yearTotals = {};                   // year -> {A..D}
  const badGrade = [];

  let total = 0;
  let noEvidence = 0;
  let candidateCount = 0;
  let confirmedCount = 0;
  let yearMissing = 0;
  let yearInvalid = 0;
  let speciesMissing = 0;

  for (const rec of list) {
    const ev = rec && rec.evidence;
    if (!ev) { noEvidence++; continue; }

    const g = ev.evidenceGrade;
    if (GRADE_ORDER.indexOf(g) < 0) { badGrade.push(JSON.stringify(g)); continue; }

    total++;
    gradeStat[g]++;
    if (isConfirmed(rec)) { confirmedCount++; confirmedStat[g]++; } else candidateCount++;

    const basis = ev.gradeBasis || 'unknown';
    gradeBasis[basis] = (gradeBasis[basis] || 0) + 1;
    if (g === 'D') dBasis[basis] = (dBasis[basis] || 0) + 1;

    const sr = ev.speciesRelevance;
    let key;
    if (!sr || !sr.relevance) { speciesMissing++; key = 'unclear'; }
    else {
      key = String(sr.relevance);
      if (!SPECIES_COLS.some((c) => c[0] === key)) {
        // 未登记值：单列一栏，**不丢弃**（丢弃会让行长合计对不上，那才是真正的谎）
        if (extraSpecies.indexOf(key) < 0) extraSpecies.push(key);
      }
    }
    if (!matrix[g]) matrix[g] = {};
    matrix[g][key] = (matrix[g][key] || 0) + 1;
    speciesTotals[key] = (speciesTotals[key] || 0) + 1;

    const y = pickYear(rec, ev);
    if (y.state === 'ok') {
      const z = { A: 0, B: 0, C: 0, D: 0, cA: 0, cB: 0, cC: 0, cD: 0 };
      if (!yearTotals[y.year]) yearTotals[y.year] = z;
      yearTotals[y.year][g]++;
      if (isConfirmed(rec)) yearTotals[y.year]['c' + g]++;
    } else if (y.state === 'invalid') yearInvalid++;
    else yearMissing++;
  }

  return {
    total, noEvidence, candidateCount, confirmedCount,
    gradeStat, confirmedStat, gradeBasis, dBasis,
    matrix, speciesTotals, extraSpecies,
    yearTotals, yearMissing, yearInvalid,
    speciesMissing, badGrade,
    allCandidate: total > 0 && confirmedCount === 0,
  };
}

/**
 * 不变式校验 —— 本模块敢叫「图」而不是「画」的唯一理由。
 * @returns {{ok: boolean, violations: string[], empty: boolean}}
 */
function validate(stats) {
  const v = [];
  const s = stats || {};
  if (!Number.isFinite(s.total) || s.total < 0) v.push('total 非法：' + JSON.stringify(s.total));
  if (s.badGrade && s.badGrade.length) {
    v.push('出现非 A/B/C/D 的等级 ' + s.badGrade.join('、') + '（分级矩阵只会产出 A-D，出现即数据被改过）');
  }
  if (v.length) return { ok: false, violations: v, empty: true };

  if (s.total === 0) return { ok: true, violations: [], empty: true };

  // ① 各档之和 = 记录总数
  const sum = GRADE_ORDER.reduce((a, g) => a + (s.gradeStat[g] || 0), 0);
  if (sum !== s.total) v.push('各档之和 ' + sum + ' ≠ 记录总数 ' + s.total + '（差额 ' + (s.total - sum) + '）');

  // ② 候选 + 已确认 = 总数（needsReview 的口径必须完整，不能有第三态）
  if (s.candidateCount + s.confirmedCount !== s.total) {
    v.push('候选 ' + s.candidateCount + ' + 已确认 ' + s.confirmedCount + ' ≠ 总数 ' + s.total);
  }

  // ③ 热力矩阵每一行之和 = 该等级计数（同一数据的第二种投影，必须自洽）
  for (const g of GRADE_ORDER) {
    const rowSum = Object.keys(s.matrix[g] || {}).reduce((a, k) => a + s.matrix[g][k], 0);
    if (rowSum !== (s.gradeStat[g] || 0)) {
      v.push('等级 ' + g + ' 的物种矩阵行和 ' + rowSum + ' ≠ 该档计数 ' + (s.gradeStat[g] || 0));
    }
  }

  // ④ 年份：有年份的条数 + 缺失 + 非法 = 总数（三种态都必须被登记，不许静默丢）
  const dated = Object.values(s.yearTotals).reduce(
    (a, o) => a + GRADE_ORDER.reduce((b, g) => b + o[g], 0), 0);
  if (dated + s.yearMissing + s.yearInvalid !== s.total) {
    v.push('有年份 ' + dated + ' + 未标注 ' + s.yearMissing + ' + 非法 ' + s.yearInvalid +
      ' ≠ 总数 ' + s.total + '（年份维度丢了 ' + (s.total - dated - s.yearMissing - s.yearInvalid) + ' 条）');
  }
  // 已确认数不得大于各档已确认之和（防「总数对了但分档没对」）
  const csum = GRADE_ORDER.reduce((a, g) => a + (s.confirmedStat[g] || 0), 0);
  if (csum !== s.confirmedCount) v.push('分档已确认之和 ' + csum + ' ≠ 已确认总数 ' + s.confirmedCount);

  // ⑤ D 档成因之和 = D 档计数 —— 图①脚注的「D 档成因分解」若用全体记录统计，
  //    会得出「46 + 23 = 69」而 D 档只有 54 条（实测踩过）。这条判据专门钉住它。
  if (s.gradeStat.D > 0) {
    const bsum = Object.values(s.dBasis || {}).reduce((a, n) => a + n, 0);
    if (bsum !== s.gradeStat.D) {
      v.push('D 档成因之和 ' + bsum + ' ≠ D 档计数 ' + s.gradeStat.D + '（脚注会把全体记录的成因当成 D 档的）');
    }
  }

  return { ok: v.length === 0, violations: v, empty: false };
}

// ── SVG 原语（约 80 行；三张图共用）──────────────────────────
/** 斜纹：候选段的唯一视觉记号。纯色 = 已人工确认，斜纹 = 候选待确认。 */
function defs(candId) {
  return [
    '<style>',
    'text{font-family:system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;}',
    '.ec-title{font-size:15px;font-weight:600;fill:' + C.ink + ';}',
    '.ec-sub{font-size:11px;fill:' + C.sub + ';}',
    '.ec-axis{font-size:10.5px;fill:' + C.sub + ';font-variant-numeric:tabular-nums;}',
    '.ec-label{font-size:12px;fill:' + C.ink + ';}',
    '.ec-label-b{font-size:12.5px;font-weight:600;fill:' + C.ink + ';}',
    '.ec-value{font-size:12.5px;font-weight:600;fill:' + C.ink + ';font-variant-numeric:tabular-nums;}',
    '.ec-cellv{font-size:12px;font-weight:600;font-variant-numeric:tabular-nums;}',
    '.ec-note{font-size:10.5px;fill:' + C.sub + ';}',
    '.ec-warn{font-size:11px;fill:' + C.warn + ';font-weight:500;}',
    '.ec-legend{font-size:10.5px;fill:' + C.sub + ';}',
    '.ec-foot{font-size:10px;fill:' + C.sub + ';}',
    '</style>',
    '<pattern id="' + candId + '" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">',
    '<rect width="7" height="7" fill="#ffffff" fill-opacity="0"/>',
    '<line x1="0" y1="0" x2="0" y2="7" stroke="#ffffff" stroke-width="2.2" stroke-opacity="0.85"/>',
    '</pattern>',
  ].join('');
}

/** 外壳：xml 声明 + 根 + defs + 白底；body 由调用方从 y=TITLE_H 往下画。 */
function wrap(h, title, desc, candId, body) {
  return [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<svg xmlns="http://www.w3.org/2000/svg" width="' + W + '" height="' + h + '" viewBox="0 0 ' + W + ' ' + h +
      '" role="img" aria-label="' + esc(title) + '">',
    '<title>' + esc(title) + '</title>',
    '<desc>' + esc(desc) + '</desc>',
    '<defs>' + defs(candId) + '</defs>',
    '<rect x="0" y="0" width="' + W + '" height="' + h + '" fill="#ffffff"/>',
  ].concat(body).concat(['</svg>', '']).join('\n');
}

/** 标题区：主标题 + 副标题（副标题右侧贴版本号）。 */
function header(title, sub) {
  return [
    '<text class="ec-title" x="' + PAD + '" y="' + (PAD + 2) + '">' + esc(clipText(title, CONTENT_W - 120, 15)) + '</text>',
    '<text class="ec-sub" x="' + PAD + '" y="' + (PAD + 20) + '">' + esc(clipText(sub, CONTENT_W - 110, 11)) + '</text>',
    '<text class="ec-sub" x="' + (W - PAD) + '" y="' + (PAD + 2) + '" text-anchor="end">' + esc(CHARTS_VERSION) + '</text>',
  ];
}

/** 警示带：全候选时必挂。它是「这不是结论」的唯一硬提示，不随美观取舍。 */
function warnBand(y, stats) {
  if (!stats.allCandidate) return [];
  const l1 = '⚠ 本图是「待审清单」的分布，不是结论：全部 ' + num(stats.total) + ' 条均为启发式候选（needsReview）';
  const l2 = '　未经人工核对原文方法学章节前，任何一档都不得用于宣称支撑';
  return [
    '<rect x="' + PAD + '" y="' + y + '" width="' + CONTENT_W + '" height="' + WARN_H + '" rx="6" fill="' + C.warnBg +
      '" stroke="' + C.warnLine + '" stroke-dasharray="4 3"/>',
    '<text class="ec-warn" x="' + (PAD + 12) + '" y="' + (y + 17) + '">' + esc(clipText(l1, CONTENT_W - 24, 11)) + '</text>',
    '<text class="ec-warn" x="' + (PAD + 12) + '" y="' + (y + 34) + '">' + esc(clipText(l2, CONTENT_W - 24, 11)) + '</text>',
  ];
}

/**
 * 横向条：候选段用斜纹叠加 + 虚线描边，确认段用实色。
 * 同一档里混合时**按比例分段**（整条画成实色等于把未核过的也算作已确认）。
 */
function bar(x, y, w, h, g, n, conf, candId) {
  if (w <= 0 || n <= 0) return [];
  const color = GRADE_COLOR[g];
  const out = [];
  const wConf = n > 0 ? w * (conf / n) : 0;
  const wCand = w - wConf;
  if (wConf > 0.5) {
    out.push('<rect x="' + x.toFixed(1) + '" y="' + y + '" width="' + wConf.toFixed(1) + '" height="' + h +
      '" rx="2" fill="' + color + '"/>');
  }
  if (wCand > 0.5) {
    const cx = x + wConf;
    // ★ 候选段**不降透明度**：0.35 透明会把 A(#0f5132) 与 B(#7cc47f) 压成几乎同色（实测截图确认）。
    //   候选的记号是「实色 + 白色斜纹 + 虚线描边」三重，颜色本身保持可辨。
    out.push('<rect x="' + cx.toFixed(1) + '" y="' + y + '" width="' + wCand.toFixed(1) + '" height="' + h +
      '" rx="2" fill="' + color + '"/>');
    out.push('<rect x="' + cx.toFixed(1) + '" y="' + y + '" width="' + wCand.toFixed(1) + '" height="' + h +
      '" rx="2" fill="url(#' + candId + ')" stroke="' + color + '" stroke-width="1" stroke-dasharray="3 2"/>');
  }
  return out;
}

/** 热力格：底 = 等级色，透明度随计数增强；0 单独用极浅灰并写「0」。 */
function cell(x, y, w, h, g, n, max) {
  const out = [];
  if (n <= 0) {
    out.push('<rect x="' + x + '" y="' + y + '" width="' + w + '" height="' + h + '" rx="3" fill="' + C.zero +
      '" stroke="' + C.line + '"/>');
    out.push('<text class="ec-cellv" x="' + (x + w / 2) + '" y="' + (y + h / 2 + 4) + '" text-anchor="middle" fill="' +
      C.idle + '">0</text>');
    return out;
  }
  const ratio = max > 0 ? n / max : 0;
  const op = 0.16 + 0.74 * ratio;
  out.push('<rect x="' + x + '" y="' + y + '" width="' + w + '" height="' + h + '" rx="3" fill="' + GRADE_COLOR[g] +
    '" fill-opacity="' + op.toFixed(2) + '"/>');
  out.push('<text class="ec-cellv" x="' + (x + w / 2) + '" y="' + (y + h / 2 + 4) + '" text-anchor="middle" fill="' +
    (op > 0.5 ? '#ffffff' : C.ink) + '">' + num(n) + '</text>');
  return out;
}

/** 堆叠柱：A 贴基线（读者一眼看到的是 A 的高度），依次向上 B/C/D。 */
function stackCol(x, baseY, w, counts, scale, candId, confirmedCounts) {
  const out = [];
  let acc = 0;
  for (const g of GRADE_ORDER) {
    const n = counts[g] || 0;
    if (!n) continue;
    const h = n * scale;
    const y = baseY - (acc + n) * scale;
    const conf = (confirmedCounts && confirmedCounts[g]) || 0;
    const candH = h * (1 - conf / n);
    if (conf > 0) {
      // 底部为已确认（实色），上方叠加候选（斜纹）—— 同一段内也须看得出哪部分没核过
      const yConf = baseY - (acc + conf) * scale;
      out.push('<rect x="' + x.toFixed(1) + '" y="' + yConf.toFixed(1) + '" width="' + w.toFixed(1) + '" height="' +
        (conf * scale).toFixed(1) + '" fill="' + GRADE_COLOR[g] + '"/>');
      if (candH > 0.5) {
        out.push('<rect x="' + x.toFixed(1) + '" y="' + (yConf - candH).toFixed(1) + '" width="' + w.toFixed(1) +
          '" height="' + candH.toFixed(1) + '" fill="' + GRADE_COLOR[g] + '"/>');
        out.push('<rect x="' + x.toFixed(1) + '" y="' + (yConf - candH).toFixed(1) + '" width="' + w.toFixed(1) +
          '" height="' + candH.toFixed(1) + '" fill="url(#' + candId + ')"/>');
      }
    } else {
      out.push('<rect x="' + x.toFixed(1) + '" y="' + y.toFixed(1) + '" width="' + w.toFixed(1) + '" height="' +
        h.toFixed(1) + '" fill="' + GRADE_COLOR[g] + '"/>');
      out.push('<rect x="' + x.toFixed(1) + '" y="' + y.toFixed(1) + '" width="' + w.toFixed(1) + '" height="' +
        h.toFixed(1) + '" fill="url(#' + candId + ')"/>');
    }
    acc += n;
  }
  return out;
}

/** 图例：三张图共用右侧一行；`withStripe` 决定是否解释斜纹。 */
function legend(y, withStripe, candId) {
  const out = [];
  let x = PAD;
  for (const g of GRADE_ORDER) {
    out.push('<rect x="' + x + '" y="' + (y - 8) + '" width="9" height="9" rx="2" fill="' + GRADE_COLOR[g] + '"/>');
    out.push('<text class="ec-legend" x="' + (x + 13) + '" y="' + y + '">' + g + '　' + GRADE_HINT[g] + '</text>');
    x += 13 + textWidth(g + '　' + GRADE_HINT[g], 10.5) + 18;
  }
  if (withStripe) {
    // 图例方块用与数据段**同一种**记号：实色 + 白斜纹 + 虚线边（否则图例在解释一个图上不存在的样式）
    out.push('<rect x="' + x + '" y="' + (y - 8) + '" width="9" height="9" rx="2" fill="' + C.idle + '"/>');
    out.push('<rect x="' + x + '" y="' + (y - 8) + '" width="9" height="9" rx="2" fill="url(#' + candId + ')" stroke="' +
      C.idle + '" stroke-dasharray="2 1.5"/>');
    out.push('<text class="ec-legend" x="' + (x + 13) + '" y="' + y + '">斜纹 = 候选待人工确认（未审核）</text>');
  }
  return out;
}

function foot(y, lines) {
  return lines.map((l, i) =>
    '<text class="ec-foot" x="' + PAD + '" y="' + (y + i * FOOT_LINE_H) + '">' + esc(clipText(l, CONTENT_W, 10)) + '</text>');
}

/** nice 刻度：把 max 抬到一个能被 4 整除的整数上（0 会退化为 1，避免除零）。 */
function niceMax(v) {
  if (!Number.isFinite(v) || v <= 0) return 1;
  const step = Math.ceil(v / 4);
  return step * 4;
}

/**
 * 刻度尺：返回 {max, step}，使 `ceil(v/step) ≤ 4` 且 **step 是 1/2/5×10ⁿ**。
 *
 * 为什么不用 `niceMax`（step = ceil(v/4)）：v=27 时它给出 step=7，刻度变成 0/7/14/21/28
 * —— 实测截图里读数困难（7、21 都不是人习惯的刻度）。这里改成 0/10/20/30。
 */
function niceScale(v) {
  if (!Number.isFinite(v) || v <= 0) return { max: 1, step: 1 };
  const steps = [];
  for (let p = 0; p <= 4; p++) for (const k of [1, 2, 5]) steps.push(k * Math.pow(10, p));
  for (const step of steps) {
    const n = Math.ceil(v / step);
    if (n <= 4) return { max: step * n, step: step };
  }
  return { max: Math.ceil(v / 4) * 4, step: Math.ceil(v / 4) };
}

// ── 几何校验（内置，不靠截图）────────────────────────────────
/**
 * 为什么不截图：上一轮 PRISMA 图的浏览器截图接口对本地预览页频繁触发 **10 MiB 上限**，
 * 缩尺寸/降质量都无效。于是改成「严格解析 + 自写几何判据」两道机检 —— 这比截图更早失败、
 * 且能在无浏览器的 CI 里跑。
 *
 * 判据只做**能机检且不误报**的那几条（宁可少检，不可恒绿）：
 *   G1 任一 rect 的四边不得越出画布；
 *   G2 任一 text 的估算**右缘**不得越出画布（按 text-anchor 换算起点）；
 *   G3 任一 text 的 y 不得越出画布；
 *   G4 必须存在 width/height 且与 viewBox 一致（防止改 viewBox 忘改尺寸）。
 *
 * ⚠ 本函数**必须能用真实长文本证伪**（见 test-unit：塞一条 200 字副标题必须报 G2）。
 *
 * @returns {string[]} 违规描述（空数组 = 通过）
 */
const FS_BY_CLASS = {
  'ec-title': 15, 'ec-sub': 11, 'ec-axis': 10.5, 'ec-label': 12, 'ec-label-b': 12.5,
  'ec-value': 12.5, 'ec-cellv': 12, 'ec-note': 10.5, 'ec-warn': 11, 'ec-legend': 10.5, 'ec-foot': 10,
};

function parseTags(svg) {
  const tags = [];
  const re = /<([a-zA-Z][\w:-]*)((?:[^>"']|"[^"]*"|'[^']*')*?)\/?>/g;
  let m;
  while ((m = re.exec(String(svg)))) {
    const attrs = {};
    const ar = /([a-zA-Z_:][\w:.-]*)\s*=\s*"([^"]*)"/g;
    let a;
    while ((a = ar.exec(m[2]))) attrs[a[1]] = a[2];
    tags.push({ name: m[1], attrs: attrs });
  }
  return tags;
}

/** XML 反转义（只处理本模块自己会产出的那五个实体，够用且可逆）。 */
function unesc(s) {
  return String(s).replace(/&#39;/g, "'").replace(/&quot;/g, '"')
    .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
}

function fontOf(attrs) {
  const st = attrs.style || '';
  const m = /font-size:\s*([\d.]+)/.exec(st);
  if (m) return Number(m[1]);
  const cls = (attrs.class || '').split(/\s+/)[0];
  return FS_BY_CLASS[cls] || 11.5;
}
/**
 * 几何校验 —— 内置，不靠截图。
 *
 * 为什么不截图：上一轮 PRISMA 图的浏览器截图接口对本地预览页频繁触发 **10 MiB 上限**，
 * 缩尺寸/降质量都无效。于是改成「严格解析 + 自写几何判据」两道机检 —— 更早失败，
 * 且能在无浏览器的环境里跑。
 *
 * 判据只做**能机检且不误报**的那几条（宁可少检，不可恒绿）：
 *   G1 任一 rect 的四边不得越出画布；
 *   G2 任一 text 的估算宽度不得越出画布（按 text-anchor 换算起点；宽度按**转义后**字符串算）；
 *   G3 任一 text 的 y 不得越出画布高；
 *   G4 width/height 必须存在且与 viewBox 一致（防止改 viewBox 忘改尺寸）。
 *
 * ⚠ 本函数**必须能用真实长文本证伪**：test-unit 塞一条 200 字副标题，必须报出 G2。
 *   恒绿的检查器等于没有检查器。
 *
 * @returns {string[]} 违规描述（空数组 = 通过）
 */
function geomCheck(svg) {
  const src = String(svg);
  const tags = parseTags(src);
  const root = tags.find((t) => t.name === 'svg');
  if (!root) return ['G4 找不到 <svg> 根元素'];

  const v = [];
  const CW = Number(root.attrs.width);
  const CH = Number(root.attrs.height);
  if (!Number.isFinite(CW) || !Number.isFinite(CH)) {
    v.push('G4 根元素缺少 width/height');
    return v;
  }
  const vb = String(root.attrs.viewBox || '').trim().split(/\s+/).map(Number);
  if (vb.length !== 4 || vb[2] !== CW || vb[3] !== CH) {
    v.push('G4 width/height(' + CW + 'x' + CH + ') 与 viewBox(' + root.attrs.viewBox + ') 不一致');
  }

  // G1：矩形四边
  const TOL = 0.6;
  for (const t of tags) {
    if (t.name !== 'rect') continue;
    const at = t.attrs;
    if (at.width === undefined || at.height === undefined) continue;
    // SVG 规范：rect 省略 x/y 时默认为 0（pattern 内的 rect 就是这种写法）。
    // 这里**不能**把「缺省」当成「非法」—— 初版就是这么误报的，真实样本一跑立刻暴露。
    const x = at.x === undefined ? 0 : Number(at.x);
    const y = at.y === undefined ? 0 : Number(at.y);
    const rw = Number(at.width);
    const rh = Number(at.height);
    if (![x, y, rw, rh].every(Number.isFinite)) {
      v.push('G1 rect 属性非数字：' + JSON.stringify(at).slice(0, 120));
      continue;
    }
    if (x < -TOL || y < -TOL || x + rw > CW + TOL || y + rh > CH + TOL) {
      v.push('G1 rect 越界 [' + x.toFixed(1) + ',' + y.toFixed(1) + ' ' + rw.toFixed(1) + 'x' + rh.toFixed(1) +
        '] 画布 ' + CW + 'x' + CH);
    }
  }

  // G2/G3：文字（宽度必须用元素内文本，属性里没有）
  const re = /<text([^>]*)>([\s\S]*?)<\/text>/g;
  let m;
  let idx = 0;
  while ((m = re.exec(src))) {
    idx++;
    const attrs = {};
    const ar = /([a-zA-Z_:][\w:.-]*)\s*=\s*"([^"]*)"/g;
    let a;
    while ((a = ar.exec(m[1]))) attrs[a[1]] = a[2];
    const inner = unesc(m[2]);
    const fs = fontOf(attrs);
    const w = textWidth(inner, fs);
    const x = Number(attrs.x);
    const y = Number(attrs.y);
    if (!Number.isFinite(x) || !Number.isFinite(y)) {
      v.push('G3 第 ' + idx + ' 段文字缺 x/y：' + JSON.stringify(inner.slice(0, 30)));
      continue;
    }
    const anchor = attrs['text-anchor'] || 'start';
    const left = anchor === 'end' ? x - w : anchor === 'middle' ? x - w / 2 : x;
    const right = left + w;
    if (left < 2 || right > CW - 2) {
      v.push('G2 第 ' + idx + ' 段文字越界 [' + left.toFixed(1) + ',' + right.toFixed(1) + '] 画布 ' + CW +
        '：' + JSON.stringify(inner.slice(0, 40)));
    }
    if (y < 0 || y > CH) v.push('G3 第 ' + idx + ' 段文字 y=' + y + ' 超出画布高 ' + CH);
  }
  return v;
}

// ── 图 ①：等级分布 ───────────────────────────────────────────
function gradeDistSvg(stats) {
  const candId = 'ec-cand-1';
  const ROW = 40;
  const LBL_W = 132;
  const VAL_W = 132;
  const BAR_X = PAD + LBL_W;
  const BAR_W = CONTENT_W - LBL_W - VAL_W;
  const warnH = stats.allCandidate ? WARN_H + 12 : 0;
  const footLines = footLinesFor1(stats);
  const bodyTop = PAD + TITLE_H;
  const rowsTop = bodyTop + warnH;
  const h = Math.ceil(rowsTop + GRADE_ORDER.length * ROW + 22 + footLines.length * FOOT_LINE_H + PAD);

  const max = Math.max(1, ...GRADE_ORDER.map((g) => stats.gradeStat[g]));
  const body = header('证据等级分布（候选）',
    '共 ' + num(stats.total) + ' 条分级记录　·　候选 ' + num(stats.candidateCount) + ' / 已确认 ' + num(stats.confirmedCount) +
    '　·　数字取自 evidence 分级字段，本图不重算等级');
  body.push(...warnBand(bodyTop, stats));

  GRADE_ORDER.forEach((g, i) => {
    const y = rowsTop + i * ROW;
    const n = stats.gradeStat[g];
    const conf = stats.confirmedStat[g];
    const bw = max > 0 ? (n / max) * BAR_W : 0;
    body.push('<text class="ec-label-b" x="' + PAD + '" y="' + (y + 16) + '">' + g + '　' + esc(GRADE_HINT[g]) + '</text>');
    // 轨道：让「0 条」也看得见（空条 = 0，不是缺失）
    body.push('<rect x="' + BAR_X + '" y="' + (y + 5) + '" width="' + BAR_W + '" height="20" rx="3" fill="' + C.idleBg + '"/>');
    body.push(...bar(BAR_X, y + 5, bw, 20, g, n, conf, candId));
    if (n === 0) {
      body.push('<text class="ec-note" x="' + (BAR_X + 6) + '" y="' + (y + 19) + '">0 条</text>');
    }
    body.push('<text class="ec-value" x="' + (W - PAD) + '" y="' + (y + 15) + '" text-anchor="end">' + num(n) + ' 条</text>');
    body.push('<text class="ec-note" x="' + (W - PAD) + '" y="' + (y + 29) + '" text-anchor="end">' + pct(n, stats.total) + '</text>');
  });

  const ly = rowsTop + GRADE_ORDER.length * ROW + 14;
  body.push(...legend(ly, true, candId));
  body.push(...foot(ly + 22, footLines));
  return wrap(h, '证据等级分布（候选）',
    'A/B/C/D 四档的记录数与占比；斜纹表示该段为未经人工确认的启发式候选。', candId, body);
}

function footLinesFor1(stats) {
  const b = stats.dBasis || {};
  const out = [];
  const parts = [];
  if (b.design_unrecognized) parts.push('设计未识别 ' + b.design_unrecognized + ' 条');
  if (b.design_identified) parts.push('已判定但薄弱 ' + b.design_identified + ' 条');
  if (b.text_too_short) parts.push('文本过短 ' + b.text_too_short + ' 条');
  if (b.unknown) parts.push('成因未知 ' + b.unknown + ' 条');
  if (parts.length) out.push('D 档成因分解（合计 ' + num(stats.gradeStat.D) + ' 条）：' + parts.join(' / ') + '（设计未识别属「信息不足」，不等于「证据薄弱」）');
  if (stats.noEvidence) out.push('另有 ' + stats.noEvidence + ' 条记录无 evidence 字段（未启用分级），不在本图内');
  return out;
}

// ── 图 ②：等级 × 物种相关性 ──────────────────────────────────
function gradeSpeciesSvg(stats) {
  const candId = 'ec-cand-2';
  const LBL_W = 120;
  const cols = SPECIES_COLS.concat(stats.extraSpecies.map((k) => [k, k === OTHER_KEY ? '其他' : k]));
  const gridW = CONTENT_W - LBL_W;
  const cw = gridW / cols.length;
  const HEAD_H = 34;
  const ROW = 34;
  const warnH = stats.allCandidate ? WARN_H + 12 : 0;
  const bodyTop = PAD + TITLE_H;
  const gridTop = bodyTop + warnH + HEAD_H;
  const footLines = [];
  if (stats.speciesMissing) footLines.push('其中 ' + stats.speciesMissing + ' 条无 speciesRelevance 字段，归入「未识别」列（不是「已识别为未识别」）');
  if (stats.extraSpecies.length) footLines.push('出现未登记的物种相关性取值：' + stats.extraSpecies.join('、') + '（单列保留，不并入已有列）');
  const h = Math.ceil(gridTop + GRADE_ORDER.length * ROW + 68 + footLines.length * FOOT_LINE_H + PAD);

  // 热力强度**按行归一**：本图要回答的是「A 档里有没有体外/非靶动物换来的」，
  // 那是行内比较；用全局归一会让「条数少所以淡」被读成「这条物种关系弱」。
  const rowMax = {};
  for (const g of GRADE_ORDER) {
    const row = stats.matrix[g] || {};
    rowMax[g] = Math.max(1, ...Object.keys(row).map((k) => row[k]));
  }

  const body = header('证据等级 × 物种相关性（候选）',
    '同一批 ' + num(stats.total) + ' 条的二维投影　·　行和必须等于该档计数（自洽校验已通过）　·　' +
    '格内深浅按行归一：同一行内可比，行间请比数字');

  // 列头（两行折行，按字数硬折；中文标签短，4-6 字必然放得下）
  cols.forEach((c, i) => {
    const cx = PAD + LBL_W + i * cw;
    const label = c[1];
    const lines = label.length > 5 ? [label.slice(0, 5), label.slice(5)] : [label];
    body.push('<rect x="' + (cx + 1) + '" y="' + (bodyTop + warnH) + '" width="' + (cw - 2) + '" height="' + (HEAD_H - 4) +
      '" rx="3" fill="' + C.head + '"/>');
    lines.slice(0, 2).forEach((ln, k) => {
      body.push('<text class="ec-axis" x="' + (cx + cw / 2) + '" y="' + (bodyTop + warnH + 14 + k * 12) +
        '" text-anchor="middle">' + esc(clipText(ln, cw - 8, 10.5)) + '</text>');
    });
  });
  body.push(...warnBand(bodyTop, stats));

  GRADE_ORDER.forEach((g, r) => {
    const y = gridTop + r * ROW;
    body.push('<text class="ec-label-b" x="' + PAD + '" y="' + (y + 21) + '">' + g + '（' + num(stats.gradeStat[g]) + '）</text>');
    cols.forEach((c, i) => {
      const cx = PAD + LBL_W + i * cw;
      const n = (stats.matrix[g] || {})[c[0]] || 0;
      body.push(...cell(cx + 1, y + 2, cw - 2, ROW - 6, g, n, rowMax[g]));
    });
  });

  // 列合计行：让读者一眼看到「物种分布」而不必自己加
  const sumY = gridTop + GRADE_ORDER.length * ROW + 4;
  body.push('<line x1="' + PAD + '" y1="' + sumY + '" x2="' + (W - PAD) + '" y2="' + sumY +
    '" stroke="' + C.line + '"/>');
  body.push('<text class="ec-note" x="' + PAD + '" y="' + (sumY + 16) + '">列合计</text>');
  cols.forEach((c, i) => {
    const cx = PAD + LBL_W + i * cw;
    body.push('<text class="ec-value" x="' + (cx + cw / 2) + '" y="' + (sumY + 16) + '" text-anchor="middle">' +
      num(stats.speciesTotals[c[0]] || 0) + '</text>');
  });

  const ly = sumY + 44;            // 与「列合计」数字拉开，否则图例贴着数字（实测截图里挤成一团）
  body.push(...legend(ly, false, candId));
  body.push(...foot(ly + 20, footLines));
  return wrap(h, '证据等级 × 物种相关性（候选）',
    'A-D 四档在五种物种相关性上的分布；行和等于该档计数，列合计等于该物种的记录数。', candId, body);
}

// ── 图 ③：年份 × 等级 ────────────────────────────────────────
function yearGradeSvg(stats, opts) {
  const candId = 'ec-cand-3';
  const maxBuckets = (opts && opts.maxYearBuckets) || 14;
  const buckets = yearBuckets(stats.yearTotals, maxBuckets);
  const hasUnknown = stats.yearMissing > 0;

  const AXIS_L = 44;
  const AXIS_B = 40;
  const PLOT_W = CONTENT_W - AXIS_L;
  const PLOT_H = (opts && opts.plotHeight) || 190;
  const warnH = stats.allCandidate ? WARN_H + 12 : 0;
  const bodyTop = PAD + TITLE_H;
  const plotTop = bodyTop + warnH + 10;
  const baseY = plotTop + PLOT_H;

  const slotCount = buckets.length + (hasUnknown ? 1 : 0);
  const slotW = slotCount > 0 ? PLOT_W / slotCount : PLOT_W;
  const barW = Math.max(6, Math.min(34, slotW - 10));

  const totalsPerBucket = buckets.map((b) => GRADE_ORDER.reduce((a, g) => a + (b.counts[g] || 0), 0));
  const maxTotal = Math.max(1, ...totalsPerBucket, hasUnknown ? stats.yearMissing : 0);
  const sc = niceScale(maxTotal);
  const yMax = sc.max;
  const scale = PLOT_H / yMax;

  const footLines = [];
  if (stats.yearMissing) footLines.push('「未标注」列 ' + stats.yearMissing + ' 条：year 为空 ⇒ 不落在任何年份，也不得当作 0 或某一年');
  if (stats.yearInvalid) footLines.push('另有 ' + stats.yearInvalid + ' 条 year 非数字或超出 1900-2100，未计入时间轴');
  if (!buckets.length && !hasUnknown) footLines.push('全部记录均无可比较的年份，未生成时间轴');
  if (buckets.length && buckets[0].span > 1) footLines.push('年份跨度过大，按 ' + buckets[0].span + ' 年分段；段内合计而非逐年');

  const h = Math.ceil(baseY + AXIS_B + 22 + footLines.length * FOOT_LINE_H + PAD);
  const body = header('发表年份 × 证据等级（候选）',
    '柱高 = 该' + (buckets.length && buckets[0].span > 1 ? '分段' : '年份') + '的记录数，段内按 A-D 堆叠（A 贴基线）　·　共 ' +
    num(stats.total) + ' 条');

  // Y 轴网格：按 step 走（0/10/20/30 好过 0/7/14/21/28 —— 后者是 ceil(v/4) 的副产物）
  for (let val = 0; val <= yMax + 1e-9; val += sc.step) {
    const gy = baseY - val * scale;
    body.push('<line x1="' + (PAD + AXIS_L) + '" y1="' + gy.toFixed(1) + '" x2="' + (W - PAD) + '" y2="' + gy.toFixed(1) +
      '" stroke="' + (val === 0 ? C.sub : C.line) + '"' + (val === 0 ? '' : ' stroke-dasharray="2 3"') + '/>');
    body.push('<text class="ec-axis" x="' + (PAD + AXIS_L - 6) + '" y="' + (gy + 3.5).toFixed(1) +
      '" text-anchor="end">' + num(val) + '</text>');
  }
  body.push(...warnBand(bodyTop, stats));

  buckets.forEach((b, i) => {
    const cx = PAD + AXIS_L + slotW * i + slotW / 2;
    const x = cx - barW / 2;
    const conf = {};
    for (const g of GRADE_ORDER) conf[g] = b.confirmed ? (b.confirmed[g] || 0) : 0;
    body.push(...stackCol(x, baseY, barW, b.counts, scale, candId, conf));
    const tot = GRADE_ORDER.reduce((a, g) => a + (b.counts[g] || 0), 0);
    if (tot === 0) {
      // 空年份：画一条 1px 基线，明确「这年没有」，不是漏画
      body.push('<line x1="' + x.toFixed(1) + '" y1="' + baseY + '" x2="' + (x + barW).toFixed(1) + '" y2="' + baseY +
        '" stroke="' + C.idle + '" stroke-width="1"/>');
    }
    body.push('<text class="ec-axis" x="' + cx.toFixed(1) + '" y="' + (baseY + 15) + '" text-anchor="middle">' +
      esc(b.label) + '</text>');
    if (tot > 0) {
      body.push('<text class="ec-note" x="' + cx.toFixed(1) + '" y="' + (baseY - tot * scale - 5) + '" text-anchor="middle">' +
        num(tot) + '</text>');
    }
  });

  // 「未标注」列：与时间轴之间画断开标记（虚线 + 斜切），说明它不在时间轴上
  if (hasUnknown) {
    const i = buckets.length;
    const cx = PAD + AXIS_L + slotW * i + slotW / 2;
    const x = cx - barW / 2;
    const sepX = PAD + AXIS_L + slotW * i;
    body.push('<line x1="' + sepX + '" y1="' + (plotTop - 6) + '" x2="' + sepX + '" y2="' + (baseY + 6) +
      '" stroke="' + C.idle + '" stroke-dasharray="3 3"/>');
    body.push('<rect x="' + x.toFixed(1) + '" y="' + (baseY - stats.yearMissing * scale).toFixed(1) + '" width="' + barW +
      '" height="' + (stats.yearMissing * scale).toFixed(1) + '" fill="' + C.idle + '" fill-opacity="0.45" stroke="' +
      C.idle + '" stroke-dasharray="3 2"/>');
    body.push('<text class="ec-axis" x="' + cx.toFixed(1) + '" y="' + (baseY + 15) + '" text-anchor="middle">未标注</text>');
    body.push('<text class="ec-note" x="' + cx.toFixed(1) + '" y="' + (baseY - stats.yearMissing * scale - 5) +
      '" text-anchor="middle">' + num(stats.yearMissing) + '</text>');
  }

  const ly = baseY + AXIS_B + 6;
  body.push(...legend(ly, true, candId));
  body.push(...foot(ly + 20, footLines));
  return wrap(h, '发表年份 × 证据等级（候选）',
    '按年份堆叠 A-D 四档记录数' + (hasUnknown
      ? '；「未标注」列与时间轴断开，表示年份缺失'
      : '；全部记录均有年份，无「未标注」列') + '。', candId, body);
}

/**
 * 年份分桶：跨度 ≤ maxBuckets 时**逐年**（缺年份保留空柱 —— 中间那年没有是信息，不能压缩掉），
 * 否则按 5 年（仍过多则 10 年）分段。
 */
function yearBuckets(yearTotals, maxBuckets) {
  const years = Object.keys(yearTotals).map(Number).filter((y) => Number.isFinite(y)).sort((a, b) => a - b);
  if (!years.length) return [];
  const min = years[0];
  const max = years[years.length - 1];
  const span = max - min + 1;

  const mk = (label, from, to) => {
    const counts = { A: 0, B: 0, C: 0, D: 0 };
    const conf = { A: 0, B: 0, C: 0, D: 0 };
    for (let y = from; y <= to; y++) {
      const o = yearTotals[y];
      if (!o) continue;
      for (const g of GRADE_ORDER) { counts[g] += o[g] || 0; conf[g] += (o['c' + g] || 0); }
    }
    return { label: from === to ? String(from) : from + '-' + to, from, to, span: to - from + 1, counts, confirmed: conf };
  };

  if (span <= maxBuckets) {
    const out = [];
    for (let y = min; y <= max; y++) out.push(mk(String(y), y, y));
    return out;
  }
  let step = 5;
  while (Math.ceil((max - Math.floor(min / step) * step + 1) / step) > maxBuckets + 6 && step < 20) step += 5;
  const lo = Math.floor(min / step) * step;
  const out = [];
  for (let s = lo; s <= max; s += step) out.push(mk(s + '-' + (s + step - 1), s, s + step - 1));
  return out;
}

// ── 组装 / 落盘 ──────────────────────────────────────────────
/**
 * @param {Array} records 含 evidence 的记录（gradeAll 之后的 groups 里摊平即可）
 * @param {object} [opts]
 * @returns {{charts: Array<{key,file,title,svg}>, stats: object}|null} 无记录时返回 null
 * @throws 不变式违反时抛错（不画自相矛盾的图）
 */
function buildCharts(records, opts) {
  const stats = collect(records);
  const check = validate(stats);
  if (!check.ok) {
    throw new Error('证据分布不变式未通过，拒绝出图：' + check.violations.join('；'));
  }
  if (check.empty) return null;

  return {
    stats,
    charts: [
      { key: 'grade-dist', file: 'evidence-grade-dist.svg', title: '证据等级分布', svg: gradeDistSvg(stats) },
      { key: 'grade-species', file: 'evidence-grade-species.svg', title: '证据等级 × 物种相关性', svg: gradeSpeciesSvg(stats) },
      { key: 'year-grade', file: 'evidence-year-grade.svg', title: '发表年份 × 证据等级', svg: yearGradeSvg(stats, opts) },
    ],
  };
}

/**
 * 落盘。任何一张图失败都**不**影响其余图与报告：返回 errors 由调用方写进报告。
 * @returns {{files: string[], charts: Array<{file,title,path}>, errors: string[], stats: object|null}}
 */
function writeCharts(outDir, records, opts) {
  const fs = require('fs');
  const path = require('path');
  const files = [];
  const charts = [];
  const errors = [];
  let built = null;
  try {
    built = buildCharts(records, opts);
  } catch (e) {
    return { files: [], charts: [], errors: [String((e && e.message) || e).slice(0, 300)], stats: null };
  }
  if (!built) return { files: [], charts: [], errors: [], stats: null };

  const dir = path.join(outDir, 'charts');
  try { fs.mkdirSync(dir, { recursive: true }); } catch (e) {
    return { files: [], charts: [], errors: ['无法创建 charts 目录：' + String(e && e.message)], stats: built.stats };
  }
  for (const c of built.charts) {
    const p = path.join(dir, c.file);
    try {
      fs.writeFileSync(p, c.svg, 'utf8');
      files.push(p);
      charts.push({ file: c.file, title: c.title, path: p });
    } catch (e) {
      errors.push(c.file + ' 写入失败：' + String((e && e.message) || e).slice(0, 160));
    }
  }
  return { files, charts, errors, stats: built.stats };
}

module.exports = {
  CHARTS_VERSION, GRADE_ORDER, GRADE_COLOR, SPECIES_COLS,
  collect, validate, buildCharts, writeCharts, geomCheck,
  yearBuckets, pickYear, isConfirmed, clipText, textWidth, niceMax, niceScale,
};
