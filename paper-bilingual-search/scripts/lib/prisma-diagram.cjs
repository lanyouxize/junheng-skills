#!/usr/bin/env node
/* eslint-disable */
/**
 * lib/prisma-diagram.cjs — PRISMA 流程计数图（纯 SVG，零依赖）
 *
 * 定位：把 `prisma.json` 里已经算好的四段计数**画成图**，不重新计算任何数字。
 *      旧版的 `renderMarkdown` 第 3 节是 ASCII 框线拼接，在浏览器 / 微信 / 打印场景下
 *      框线会错位、无法阅读；本模块用 SVG 复刻同一份计数，字号与框线在任意缩放比下都稳定。
 *
 * ⚠ 三条诚实约束（与 `lib/prisma.cjs` 头部同源，画图时一条都不能破）:
 *   1. **「未读到」≠ 0**。`reportedTotalUnknownKeywords` 非空时，合计节点必须换成警示样式
 *      并在图上明写「合计偏低，不等于 0 命中」。旧版把两者都渲染成「—」，读者无从分辨。
 *   2. **站点自报命中 ≠ 实际导出**。前者是数据库自报的匹配总数，后者受 `--limit` 约束，
 *      两者**不可互推** ⇒ 二者必须是 Identification 段内的两行并列读数，
 *      **绝不画成「1943 → 67」的漏斗步进**（那会让人以为筛掉了 1876 条）。
 *   3. **`duplicatesRemoved = null`（未去重）≠ 0**；**`excludedByTool` 恒为 0 且本工具不做资格判断**
 *      ⇒ 该节点必须标注「不做资格判断」，不能画成一条真的筛除流。
 *      同理 `flaggedForReview` 在纳入数**之内**，是旁注，不是流出箭头。
 *
 * 用法：
 *   const { renderSvg, validateFunnel, SVG_VERSION } = require('./prisma-diagram.cjs');
 *   const svg = renderSvg(log);            // log = buildLog(...) 的返回值
 *
 * 退出/异常：`validateFunnel` 不通过时 `renderSvg` **抛错**（不画一张自相矛盾的图）。
 */

'use strict';

const { COUNT_STATE } = require('./probe.cjs');

const SVG_VERSION = 'prisma-svg/v1';

// ── 版式常量（改这里即可整体缩放，勿在字符串里散落魔法数）────────────
const W = 900;
const PAD = 24;
const MAIN_X = PAD;
const MAIN_W = 600;
const SIDE_X = MAIN_X + MAIN_W + 20;
const SIDE_W = W - SIDE_X - PAD;
const HEAD_H = 28;
const ROW_H = 26;
const BLOCK_PAD_B = 10;
const GAP = 34;
const TITLE_H = 58;
const FOOT_LINE_H = 18;

const COLOR = {
  ink: '#1f2328',
  sub: '#57606a',
  line: '#d0d7de',
  head: '#f6f8fa',
  warn: '#bf8700',
  warnBg: '#fff8e5',
  ok: '#1a7f37',
  okBg: '#f0f9f3',
  idle: '#8c959f',
  idleBg: '#f6f8fa',
};

/** XML 转义：图里会拼进关键词、URL、注记，任一处漏转义都会让整张 SVG 解析失败。 */
function esc(s) {
  return String(s === null || s === undefined ? '' : s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/** 千分位。不用 toLocaleString —— 它受运行环境 locale 影响，会让两次生成结果不同。 */
function fmtNum(n) {
  if (n === null || n === undefined || !Number.isFinite(Number(n))) return '—';
  const s = String(Math.trunc(Number(n)));
  return s.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

/**
 * 漏斗不变式校验 —— 这是本模块唯一的「判据」，也是它敢叫「图」而不是「画」的理由。
 * 计数被篡改或数据源异常时，宁可抛错也不画一张自相矛盾的图。
 *
 * @returns {{ok: boolean, violations: string[]}}
 */
function validateFunnel(log) {
  const v = [];
  const g = (o, k) => (o && o[k] !== undefined ? o[k] : undefined);

  const retrieved = g(log && log.identification, 'recordsRetrieved');
  const afterDedupe = g(log && log.screening, 'recordsAfterDuplicates');
  const assessed = g(log && log.eligibility, 'recordsAssessed');
  const includedIn = g(log && log.included, 'recordsIncluded');

  const must = [
    ['identification.recordsRetrieved', retrieved],
    ['screening.recordsAfterDuplicates', afterDedupe],
    ['eligibility.recordsAssessed', assessed],
    ['included.recordsIncluded', includedIn],
  ];
  for (const [name, val] of must) {
    // ★ null/undefined 必须**先**拦下：`Number(null) === 0`，若只判 isFinite，
    //   缺失的计数会被静默当成 0 画进图里 —— 这正是本项目反复强调的「null 当 0」。
    if (val === null || val === undefined) {
      v.push(name + ' 缺失（' + JSON.stringify(val) + '）：null 不得当作 0');
    } else if (!Number.isFinite(Number(val))) {
      v.push(name + ' 不是有限数字（实际 ' + JSON.stringify(val) + '）');
    } else if (Number(val) < 0) {
      v.push(name + ' 为负数（' + val + '）');
    }
  }
  if (v.length) return { ok: false, violations: v };

  // Ident 之后每一段都只能「持平或减少」：纳入数超过导出数意味着数据被改过。
  if (Number(afterDedupe) > Number(retrieved)) {
    v.push('去重后(' + afterDedupe + ') > 实际导出(' + retrieved + ')：去重不可能增加条目');
  }
  if (Number(assessed) > Number(afterDedupe)) {
    v.push('资格评估(' + assessed + ') > 去重后(' + afterDedupe + ')');
  }
  if (Number(includedIn) > Number(assessed)) {
    v.push('纳入(' + includedIn + ') > 资格评估(' + assessed + ')');
  }

  // 资格段明确「不做排除」，因此排除数与纳入数不得出现任何差池。
  const excluded = g(log && log.eligibility, 'excludedByTool');
  if (excluded !== 0 && excluded !== undefined && excluded !== null) {
    v.push('eligibility.excludedByTool 应为 0（本工具不做资格判断），实际 ' + excluded);
  }
  // 复核标记是「纳入了但需人看」，不得大于纳入数（大于即口径写错）。
  // null = 未启用 --evidence（未分级），不是 0，故不参与该比较。
  const flagged = g(log && log.included, 'flaggedForReview');
  if (flagged !== null && flagged !== undefined &&
      Number.isFinite(Number(flagged)) && Number(flagged) > Number(includedIn)) {
    v.push('需人工复核(' + flagged + ') > 纳入(' + includedIn + ')：标记应含在纳入数之内');
  }

  return { ok: v.length === 0, violations: v };
}

/** 一个段落的行定义：{ label, value, tone, note } */
function identificationRows(log, meta) {
  const id = log.identification || {};
  const unknown = id.reportedTotalUnknownKeywords || [];
  const known = id.reportedTotalKnown !== false;
  const rows = [
    {
      label: '数据库自报命中（合计）',
      value: fmtNum(id.reportedTotalBySite) + (known ? '' : ' ↑'),
      tone: known ? 'normal' : 'warn',
      note: known ? '站点实时统计口径' : '合计偏低：' + unknown.length + ' 个检索式未读到计数（不等于 0 命中）',
    },
    {
      label: '实际导出（受每条上限约束）',
      value: fmtNum(id.recordsRetrieved),
      tone: 'normal',
      note: meta.countOnlyProbe ? '计数探针：0 属预期结果' : '受 --limit 约束，与上一行不可互推',
    },
  ];
  return rows;
}

function screeningRows(log) {
  const sc = log.screening || {};
  const noDedupe = sc.duplicatesRemoved === null || sc.duplicatesRemoved === undefined;
  return [
    {
      label: '进入去重',
      value: fmtNum(sc.recordsAvailable),
      tone: 'normal',
      note: null,
    },
    {
      label: '去重移除',
      value: noDedupe ? '未执行' : fmtNum(sc.duplicatesRemoved),
      tone: noDedupe ? 'idle' : 'normal',
      note: noDedupe ? '未加 --dedupe ⇒ null ≠ 0' : null,
    },
    {
      label: '去重后剩余',
      value: fmtNum(sc.recordsAfterDuplicates),
      tone: 'normal',
      note: null,
    },
  ];
}

function eligibilityRows(log) {
  const el = log.eligibility || {};
  return [
    { label: '进入资格评估', value: fmtNum(el.recordsAssessed), tone: 'normal', note: null },
  ];
}

function includedRows(log) {
  const inc = log.included || {};
  const flagged = inc.flaggedForReview;
  return [
    { label: '最终纳入', value: fmtNum(inc.recordsIncluded), tone: 'ok', note: null },
    {
      label: '其中需人工复核标记',
      value: flagged === null || flagged === undefined ? '未分级' : fmtNum(flagged),
      tone: flagged === null || flagged === undefined ? 'idle' : 'normal',
      note: flagged === null || flagged === undefined ? '未启用 --evidence' : '含在纳入数之内，非排除',
    },
  ];
}

function stageDefs(log, meta) {
  return [
    {
      key: 'identification',
      title: '识别 · Identification',
      rows: identificationRows(log, meta),
      side: null,
    },
    {
      key: 'screening',
      title: '筛选 · Screening',
      rows: screeningRows(log),
      side: null,
    },
    {
      key: 'eligibility',
      title: '资格 · Eligibility',
      rows: eligibilityRows(log),
      side: { title: '工具自动排除', value: '0', note: '本工具不做资格判断' },
    },
    {
      key: 'included',
      title: '纳入 · Included',
      rows: includedRows(log),
      side: (() => {
        const f = (log.included || {}).flaggedForReview;
        if (f === null || f === undefined) return { title: '需人工复核', value: '—', note: '未启用 --evidence' };
        return { title: '需人工复核', value: fmtNum(f), note: '含在纳入内，非排除' };
      })(),
    },
  ];
}

/**
 * 渲染 SVG。宽度固定 900，高度随内容自适应。
 * @param {object} log buildLog() 的返回值
 * @returns {string} 完整 SVG 文档字符串
 */
function renderSvg(log) {
  const check = validateFunnel(log);
  if (!check.ok) {
    throw new Error('PRISMA 漏斗计数违反不变式，拒绝出图：' + check.violations.join('；'));
  }

  const meta = (log && log.meta) || {};
  const stages = stageDefs(log, meta);

  // ── 高度预算：先算块高，再定总高 ────────────────────────────
  const blockHeights = stages.map((s) => HEAD_H + s.rows.length * ROW_H + BLOCK_PAD_B);
  const footLines = footnoteLines(log, meta);
  const footH = footLines.length * FOOT_LINE_H + 14;
  const totalH =
    PAD + TITLE_H + blockHeights.reduce((a, b) => a + b, 0) + GAP * (stages.length - 1) + footH + PAD;

  const out = [];
  out.push(
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<svg xmlns="http://www.w3.org/2000/svg" width="' + W + '" height="' + Math.ceil(totalH) + '"' +
      ' viewBox="0 0 ' + W + ' ' + Math.ceil(totalH) + '" role="img"' +
      ' aria-label="PRISMA 流程计数图：识别 ' + esc(fmtNum((log.identification || {}).recordsRetrieved)) +
      ' 条导出，最终纳入 ' + esc(fmtNum((log.included || {}).recordsIncluded)) + ' 条">',
    '<title>PRISMA 2020 流程计数</title>',
    '<desc>由 prisma-diagram.cjs 依据 prisma.json 生成；图中数字与 JSON 逐字段一致，不重新计算。</desc>',
    '<defs>',
    '<marker id="pd-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">',
    '<path d="M 0 0 L 10 5 L 0 10 z" fill="' + COLOR.sub + '"/>',
    '</marker>',
    '<style>',
    'text{font-family:system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;}',
    '.pd-title{font-size:15px;font-weight:600;fill:' + COLOR.ink + ';}',
    '.pd-sub{font-size:11.5px;fill:' + COLOR.sub + ';}',
    '.pd-stage{font-size:12.5px;font-weight:600;fill:' + COLOR.ink + ';}',
    '.pd-label{font-size:12.5px;fill:' + COLOR.ink + ';}',
    '.pd-value{font-size:14px;font-weight:600;fill:' + COLOR.ink + ';font-variant-numeric:tabular-nums;}',
    '.pd-value-warn{fill:' + COLOR.warn + ';}',
    '.pd-value-ok{fill:' + COLOR.ok + ';}',
    '.pd-value-idle{fill:' + COLOR.idle + ';font-weight:500;}',
    '.pd-note{font-size:10.5px;fill:' + COLOR.sub + ';}',
    '.pd-side-title{font-size:11.5px;font-weight:600;fill:' + COLOR.sub + ';}',
    '.pd-side-value{font-size:13px;font-weight:600;fill:' + COLOR.ink + ';}',
    '.pd-foot{font-size:10.5px;fill:' + COLOR.sub + ';}',
    '</style>',
    '</defs>',
    '<rect x="0" y="0" width="' + W + '" height="' + Math.ceil(totalH) + '" fill="#ffffff"/>'
  );

  // ── 标题区 ────────────────────────────────────────────────
  const idInfo = log.identification || {};
  out.push(
    '<text class="pd-title" x="' + PAD + '" y="' + (PAD + 4) + '">PRISMA 流程计数</text>',
    '<text class="pd-sub" x="' + PAD + '" y="' + (PAD + 24) + '">数据源：' +
      esc(idInfo.database || '—') + '　·　检索式 ' + esc(fmtNum(idInfo.searchCount)) + ' 条　·　生成 ' +
      esc(String(log.generatedAt || '—').slice(0, 19).replace('T', ' ')) + ' UTC</text>',
    '<text class="pd-sub" x="' + (W - PAD) + '" y="' + (PAD + 4) + '" text-anchor="end">' +
      esc(SVG_VERSION) + '</text>'
  );

  // ── 各段 ──────────────────────────────────────────────────
  let y = PAD + TITLE_H;
  stages.forEach((stage, si) => {
    const bh = blockHeights[si];

    // 段框
    out.push(
      '<rect x="' + MAIN_X + '" y="' + y + '" width="' + MAIN_W + '" height="' + bh + '" rx="6"' +
        ' fill="#ffffff" stroke="' + COLOR.line + '"/>',
      // 左侧色条
      '<rect x="' + MAIN_X + '" y="' + y + '" width="4" height="' + bh + '" rx="2" fill="' +
        (stage.key === 'included' ? COLOR.ok : COLOR.sub) + '"/>',
      // 段头
      '<rect x="' + (MAIN_X + 4) + '" y="' + y + '" width="' + (MAIN_W - 4) + '" height="' + HEAD_H +
        '" rx="5" fill="' + COLOR.head + '"/>',
      '<rect x="' + (MAIN_X + 4) + '" y="' + (y + HEAD_H - 5) + '" width="' + (MAIN_W - 4) + '" height="5" fill="' + COLOR.head + '"/>',
      '<text class="pd-stage" x="' + (MAIN_X + 16) + '" y="' + (y + 19) + '">' + esc(stage.title) + '</text>'
    );

    // 行
    stage.rows.forEach((row, ri) => {
      const ry = y + HEAD_H + ri * ROW_H + 17;
      out.push('<text class="pd-label" x="' + (MAIN_X + 16) + '" y="' + ry + '">' + esc(row.label) + '</text>');
      const vCls =
        'pd-value' +
        (row.tone === 'warn' ? ' pd-value-warn' : row.tone === 'ok' ? ' pd-value-ok' : row.tone === 'idle' ? ' pd-value-idle' : '');
      out.push(
        '<text class="' + vCls + '" x="' + (MAIN_X + MAIN_W - 16) + '" y="' + ry + '" text-anchor="end">' +
          esc(row.value) + '</text>'
      );
      if (row.note && ri === stage.rows.length - 1) {
        // 注记只跟随最后一行，避免每行都堆小字
        out.push(
          '<text class="pd-note" x="' + (MAIN_X + 16) + '" y="' + (ry + 14) + '">' + esc(row.note) + '</text>'
        );
      } else if (row.note) {
        out.push(
          '<text class="pd-note" x="' + (MAIN_X + MAIN_W - 16) + '" y="' + (ry + 14) + '" text-anchor="end">' +
            esc(row.note) + '</text>'
        );
      }
    });

    // 旁注（PRISMA 的「右侧排除」位；恒 0 与「含在纳入内」都在这里说清）
    if (stage.side) {
      const sy = y + HEAD_H + 6;
      const isZero = stage.side.value === '0';
      out.push(
        '<rect x="' + SIDE_X + '" y="' + sy + '" width="' + SIDE_W + '" height="52" rx="6"' +
          ' fill="' + (isZero ? COLOR.idleBg : COLOR.warnBg) + '" stroke="' + COLOR.line +
          '" stroke-dasharray="4 3"/>',
        '<text class="pd-side-title" x="' + (SIDE_X + 12) + '" y="' + (sy + 19) + '">' +
          esc(stage.side.title) + '</text>',
        '<text class="pd-side-value" x="' + (SIDE_X + 12) + '" y="' + (sy + 38) + '">' +
          esc(stage.side.value) + '</text>',
        '<text class="pd-side-title" x="' + (SIDE_X + SIDE_W - 12) + '" y="' + (sy + 38) +
          '" text-anchor="end" style="font-weight:400;font-size:10.5px">' + esc(stage.side.note) + '</text>'
      );
      // 虚线连接：主段 → 旁注（表示「该段的一个读数在此说明」，不是流出的条目）
      out.push(
        '<line x1="' + (MAIN_X + MAIN_W) + '" y1="' + (sy + 26) + '" x2="' + (SIDE_X - 4) + '" y2="' + (sy + 26) +
          '" stroke="' + COLOR.line + '" stroke-dasharray="3 3"/>'
      );
    }

    y += bh;

    // 段间箭头
    if (si < stages.length - 1) {
      const cx = MAIN_X + MAIN_W / 2;
      out.push(
        '<line x1="' + cx + '" y1="' + (y + 8) + '" x2="' + cx + '" y2="' + (y + GAP - 10) + '" stroke="' +
          COLOR.sub + '" stroke-width="1.4" marker-end="url(#pd-arrow)"/>'
      );
      y += GAP;
    }
  });

  // ── 脚注 ──────────────────────────────────────────────────
  footnoteLines(log, meta).forEach((line, i) => {
    out.push(
      '<text class="pd-foot" x="' + PAD + '" y="' + (y + 18 + i * FOOT_LINE_H) + '">' + esc(line) + '</text>'
    );
  });

  out.push('</svg>', '');
  return out.join('\n');
}

/**
 * 「未读到」脚注：**必须按像素预算裁剪**。
 *
 * 实测教训：真实检索式长 90+ 字符（`TITLE_ABS:("urolithiasis" OR FLUTD OR …) AND …`），
 * 直接拼进脚注会把文字推到 x≈1251（画布只有 900）—— 在渲染器里表现为**整行被裁掉**，
 * 而「未读到的是哪几条」正是这行脚注存在的全部理由。故按预算收口：
 * 先尽量多放，放不下就截断，并始终保留「共 N 条」与「不等于 0 命中」这两个不可省的语义。
 */
function unknownClause(unknown) {
  const FS = 10.5;
  const BUDGET = W - 2 * PAD - 36;              // 留右侧余量，避免贴边
  // ★ 预算必须按**转义后**的文本估算：`"` → `&quot;` 会把 1 个字符变成 6 个，
  //   实测真实检索式里 4 个引号就能让宽度虚增 ~116px（按未转义长度算 ⇒ 仍然溢出）。
  const wOf = (s) => [...esc(s)].reduce((a, ch) => a + (ch.codePointAt(0) > 0x2e80 ? FS : FS * 0.55), 0);
  const HEAD = '↑ 未读到计数：';
  const TAIL = '（采集失败 ≠ 0 命中，不得据此排除该检索式）';
  const suffix = (shown) => (unknown.length > shown ? ' 等 ' + unknown.length + ' 条' : '') + TAIL;

  let body = '';
  let shown = 0;
  for (const kw of unknown) {
    const piece = (shown ? '、' : '') + '`' + kw + '`';
    if (wOf(HEAD + body + piece + suffix(shown + 1)) > BUDGET) {
      if (shown === 0) {
        // 一个词都放不下 ⇒ 截断该词本身（宁可显示半条，也不能整行消失）
        let cut = String(kw);
        while (cut.length > 8 && wOf(HEAD + '`' + cut + '…`' + suffix(1)) > BUDGET) cut = cut.slice(0, -1);
        body = '`' + cut + '…`';
        shown = 1;
      }
      break;
    }
    body += piece;
    shown++;
  }
  return HEAD + body + suffix(shown);
}

/** 脚注：把「未读到」「未去重」「探针模式」等必须在图上说明的状态逐条列出。 */
function footnoteLines(log, meta) {
  const lines = [];
  const id = log.identification || {};
  const sc = log.screening || {};
  const unknown = id.reportedTotalUnknownKeywords || [];

  if (id.reportedTotalKnown === false) {
    lines.push(unknownClause(unknown));
  }
  if (sc.duplicatesRemoved === null || sc.duplicatesRemoved === undefined) {
    lines.push('去重移除「未执行」表示本次未加 --dedupe，不是 0 条重复。');
  }
  if (meta.countOnlyProbe) {
    lines.push('计数探针模式（--limit 0）：本次只采站点自报命中，实际导出为 0 属预期。');
  }
  lines.push('数字均直接取自 prisma.json，未重新计算；站点自报命中与实际导出不可互推。');
  lines.push('本图为可复现性存档，非正式系统综述的 PRISMA flow diagram（未做人工资格评估）。');
  return lines;
}

/** 写入 PRISMA.svg，返回路径。 */
function writeSvg(outDir, log) {
  const fs = require('fs');
  const path = require('path');
  fs.mkdirSync(outDir, { recursive: true });
  const svgPath = path.join(outDir, 'PRISMA.svg');
  fs.writeFileSync(svgPath, renderSvg(log), 'utf8');
  return svgPath;
}

module.exports = { SVG_VERSION, renderSvg, validateFunnel, writeSvg, fmtNum, esc };
