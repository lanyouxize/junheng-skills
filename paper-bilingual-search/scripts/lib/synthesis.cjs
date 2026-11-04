#!/usr/bin/env node
/* eslint-disable */
/**
 * lib/synthesis.cjs — 综合归纳章节（大纲优先 · 每句挂行号 · 只陈述可回查事实）
 *
 * 定位：report.md 里的「证据分级候选一览」是一张 N 行表格，读者要自己数才能得出「A 只有 2 条」
 *      「A 里有 1 条其实是体外」这类判断。本节把表格**归纳成 6 条大纲**，每句末尾挂 `[#n]`，
 *      指向表格的第 n 行 —— 读完 6 句就知道这份检索结果的形状，要核对就点行号。
 *
 * ⚠ 四条纪律（本模块的存在意义，破一条就不该存在）:
 *   1. **只陈述表里已有的事实**：计数、分布、字段缺失。**不做「某原料有效/无效」的判断** ——
 *      那需要人工核对全文方法学章节后由人写，工具无权代笔。
 *   2. **每句必须挂行号**。没有行号的句子读者无法核对，等于要求他相信工具。
 *      某类为 0 时写「无」，**不得省略整句** —— 省略与「没检查」在读者眼里没有区别。
 *   3. **行号口径与表格严格同一排序**：`graded` 按（等级, 年份倒序）排完后 `index+1` 即表格 `#` 列。
 *      本模块自己再数一遍各档条数，并与 `evidence-charts.collect()` 的结论**逐值比对**，
 *      不一致就抛错 —— 两份独立统计都不可能对但彼此一致。
 *   4. **`needsReview` 恒 true 必须在归里说破**：A/B 档哪怕设计物种全达标，也只能写成
 *      「候选」，并明写「核对全文前不得引用」。否则这节会被当成结论页直接引到对外材料里。
 *
 * 用法：
 *   const { buildSynthesis } = require('./synthesis.cjs');
 *   const out = buildSynthesis(graded, { flagLabel, keywords });
 *   out.md     // string[]，直接 L.push(...out.md) 进报告
 *   out.stats  // 供调用方断言/回传
 *
 * 纯函数：零 IO、零网络、无时间戳（同输入两次输出逐字节一致）。
 */

'use strict';

const EC = require('./evidence-charts.cjs');

const VERSION = 'synthesis/v1';

const GRADE_ORDER = ['A', 'B', 'C', 'D'];
const GRADE_MEAN = {
  A: '靶动物 RCT/SR',
  B: '靶动物对照或设计良好',
  C: '间接物种/观察性/体外',
  D: '证据薄弱或信息不足',
};

/** 一行最多列几个行号，超过就折叠成区间（否则一句挂 54 个 [#] 比表格还长）。 */
const MAX_REFS = 5;

/**
 * 行号引用串。
 * @param {number[]} nums 1-based 行号（升序）
 * @returns {string} 例如 `[#1]、[#3]` 或 `[#6]–[#20] 等 15 条`
 */
function refs(nums) {
  const a = (nums || []).slice().sort((x, y) => x - y);
  if (!a.length) return '（无）';
  if (a.length <= MAX_REFS) return a.map((n) => '[#' + n + ']').join('、');
  return '[#' + a[0] + ']–[#' + a[a.length - 1] + '] 等 ' + a.length + ' 条';
}

const pct = (a, b) => (!b ? '—' : (a / b * 100).toFixed(0) + '%');

/**
 * 一组数的整数占比，**合计恒等于 100**（最大余数法）。
 *
 * 为什么需要：2/8、1/8、2/8、3/8 逐个四舍五入得 25+13+25+38 = **101%** —— 读者一加就发现
 * 对不上，整节的可信度跟着掉。四个数凑 100 是这类分配问题的标准解。
 * 平局按原序取，保证确定性。
 */
function pctAll(nums, total) {
  const n = nums.length;
  if (!total) return new Array(n).fill(0);
  const raw = nums.map((x) => (x * 100) / total);
  const out = raw.map(Math.floor);
  let rest = 100 - out.reduce((a, b) => a + b, 0);
  const order = raw
    .map((r, i) => ({ i: i, frac: r - Math.floor(r) }))
    .sort((a, b) => (b.frac - a.frac) || (a.i - b.i));
  for (let k = 0; k < rest && k < order.length; k++) out[order[k].i]++;
  return out;
}

/** 标题摘要：够长能认出来，够短不撑破一行。 */
function brief(title, n) {
  const s = String(title || '(无英文标题)').replace(/\s+/g, ' ').trim();
  const max = n || 54;
  return s.length > max ? s.slice(0, max) + '…' : s;
}

/**
 * @param {Array<{g:object, r:object}>} graded 已按（等级, 年份倒序）排序，index+1 = 表格行号
 * @param {object} [opts]
 * @param {object} [opts.flagLabel] 复核标记 → 中文说明
 * @param {string[]} [opts.keywords] 本次关键词（用于说清覆盖范围）
 * @returns {{md: string[], stats: object}}
 */
function buildSynthesis(graded, opts) {
  const list = Array.isArray(graded) ? graded : [];
  const o = opts || {};
  const FL = o.flagLabel || {};
  if (!list.length) return { md: [], stats: { total: 0, sections: 0 } };

  const total = list.length;

  // ── 逐行归类（行号 = 索引 + 1，与表格同一排序）──────────────
  const rowsOf = { A: [], B: [], C: [], D: [] };
  const speciesRisk = [];        // 等级 A/B 但物种不达标的行（最该被看见的那批）
  const flagsOf = {};            // 标记 → 行号
  const basisRows = {};          // D 档成因 → 行号（成因句也必须能点开核对）
  const missingSampleRows = [];
  const missingDoiRows = [];
  let missingYear = 0;
  let reviewed = 0;

  list.forEach((x, i) => {
    const n = i + 1;
    const ev = (x && x.r && x.r.evidence) || {};
    const g = ev.evidenceGrade;
    if (rowsOf[g]) rowsOf[g].push(n);
    if (ev.reviewed === true) reviewed++;

    const rel = (ev.speciesRelevance && ev.speciesRelevance.relevance) || 'unclear';
    if ((g === 'A' || g === 'B') && rel !== 'target_species') {
      speciesRisk.push({ n, g, rel, title: x.r.titleEn });
    }
    for (const f of (ev.flags || [])) {
      if (!flagsOf[f]) flagsOf[f] = [];
      flagsOf[f].push(n);
    }
    if (!ev.sampleSize || ev.sampleSize.value == null) missingSampleRows.push(n);
    if (!x.r || x.r.year === null || x.r.year === undefined || x.r.year === '') missingYear++;
    if (!(x.r && (x.r.doi || (x.r.enrich && x.r.enrich.doi) || x.r.doiFromUrl))) missingDoiRows.push(n);
    if (g === 'D') {
      const b = ev.gradeBasis || 'unknown';
      if (!basisRows[b]) basisRows[b] = [];
      basisRows[b].push(n);
    }
  });
  const missingSample = missingSampleRows.length;
  const missingDoi = missingDoiRows.length;

  // ── 与 evidence-charts 的独立统计交叉比对（两份统计不许各说各话）──
  const ec = EC.collect(list.map((x) => x.r));
  const mine = {};
  for (const g of GRADE_ORDER) mine[g] = rowsOf[g].length;
  const drift = GRADE_ORDER.filter((g) => mine[g] !== ec.gradeStat[g]);
  if (drift.length) {
    throw new Error('综合归纳与证据分布图的等级计数不一致：' +
      drift.map((g) => g + ' 归纳 ' + mine[g] + ' / 分布图 ' + ec.gradeStat[g]).join('；') +
      '（行号口径已漂移，拒绝生成会指错行的归纳）');
  }
  if (ec.total !== total) {
    throw new Error('归纳输入 ' + total + ' 条，但分级统计只认到 ' + ec.total + ' 条（含未分级记录？）');
  }

  const A = rowsOf.A.length;
  const B = rowsOf.B.length;
  const hasClaimable = A + B > 0;
  const allCandidate = reviewed === 0;
  // A 档中物种达标的条数：第二节要用，stats 也要回传 ⇒ 提到函数体作用域，
  // 初版写在 if 分支里，stats 引用时炸「aTarget is not defined」（报告里只留下一行警告）。
  const aTarget = list.filter((x) => x.r.evidence.evidenceGrade === 'A' &&
    ((x.r.evidence.speciesRelevance || {}).relevance === 'target_species')).length;

  const L = [];
  const md = L;
  L.push('## 综合归纳（自动生成 · 只陈述可回查事实）');
  L.push('');
  L.push('> 本节由 `lib/synthesis.cjs` 依**同一份**证据数据生成。每句末尾的 `[#n]` 指向下方' +
    '「证据分级候选一览」的第 n 行（点开可核对标题、设计、物种、样本量）。' +
    '**本节不做「某原料有效/无效」这类判断** —— 那必须人工读完全文方法学章节后才可写。' +
    '某类为 **0 条时写「无」**，而不是省略整句。');
  L.push('>');
  L.push('> 覆盖：' + total + ' 条分级记录' +
    ((o.keywords && o.keywords.length) ? '，来自 ' + o.keywords.length + ' 组关键词（' + o.keywords.join(' / ') + '）' : '') +
    '；已人工确认 **' + reviewed + '** 条。');
  L.push('');

  // ── 一、证据强度 ─────────────────────────────────────────
  L.push('### 一、证据强度');
  L.push('');
  // 四档占比用最大余数法凑满 100（逐个 toFixed 会得到 101%，读者一加就能发现）
  const shares = pctAll(GRADE_ORDER.map((g) => rowsOf[g].length), total);
  GRADE_ORDER.forEach((g, k) => {
    const nums = rowsOf[g];
    if (!nums.length) {
      L.push('- **' + g + ' 档**（' + GRADE_MEAN[g] + '）：0 条 —— 本次检索未产出该档记录');
    } else {
      L.push('- **' + g + ' 档**（' + GRADE_MEAN[g] + '）：' + nums.length + ' 条（' + shares[k] + '%）· ' + refs(nums));
    }
  });
  const dBasis = ec.dBasis || {};
  if (rowsOf.D.length) {
    const BASIS_LABEL = {
      design_unrecognized: '设计未识别（信息不足）',
      design_identified: '已判定但薄弱',
      text_too_short: '文本过短',
      unknown: '成因未知',
    };
    for (const k of Object.keys(basisRows).sort()) {
      L.push('- D 档「' + (BASIS_LABEL[k] || k) + '」：' + basisRows[k].length + ' 条 · ' + refs(basisRows[k]));
    }
    L.push('- ⇒ 「设计未识别」是**信息不足**，不等于证据薄弱（补全文后可能升档）；' +
      '这两类不可合并汇报，也不可当作「该方向无效」的依据。');
  }
  L.push('');

  // ── 二、宣称可用性 ───────────────────────────────────────
  L.push('### 二、宣称可用性（A/B 档 = 有支持力的候选）');
  L.push('');
  if (!hasClaimable) {
    L.push('- **A/B 档合计 0 条** ⇒ 本次结果中**没有任何一条**具备支撑宣称的候选资格；' +
      'C/D 档只能作机制线索或排除项，不得用于对外表述。');
  } else {
    L.push('- A/B 档合计 ' + (A + B) + ' 条（' + pct(A + B, total) + '）：' + refs(rowsOf.A.concat(rowsOf.B)));
    L.push('- 其中 A 档 ' + A + ' 条（' + refs(rowsOf.A) + '）；物种为犬猫靶动物的 **' + aTarget + ' 条**' +
      (aTarget < A
        ? '，其余 ' + (A - aTarget) + ' 条（' + refs(speciesRisk.filter((x) => x.g === 'A').map((x) => x.n)) +
          '）物种不达标，**不能按 A 档对待**（见第三节）'
        : '（全部达标）') + '。');
  }
  if (allCandidate) {
    L.push('- ⚠ **上述 ' + (A + B) + ' 条全部未经人工确认**（`needsReview=true`，已确认 0 条）：' +
      refs(rowsOf.A.concat(rowsOf.B)) + '；在设计判定、物种识别、样本量三处都可能被摘要误导，' +
      '**核对全文方法学章节前不得引用**。');
  } else {
    L.push('- 已人工确认 ' + reviewed + ' 条' +
      (reviewed < total ? '，其余 ' + (total - reviewed) + ' 条（' + refs(list.map((x, i) => i + 1).filter((n) => {
        const ev = list[n - 1].r.evidence || {};
        return ev.reviewed !== true;
      })) + '）仍为候选，同样不得引用。' : '（全部已确认）。'));
  }
  L.push('');

  // ── 三、物种与设计风险 ──────────────────────────────────
  L.push('### 三、物种与设计风险（A/B 档里站不住的那些）');
  L.push('');
  if (!speciesRisk.length) {
    L.push('- 无：A/B 档中**没有**来自体外、非靶动物、混杂多物种或物种未识别的记录。' +
      '（这一句是「检查过且为空」，不是省略。）');
  } else {
    for (const x of speciesRisk) {
      L.push('- **' + x.g + ' 档但物种为「' + x.rel + '」**：' + brief(x.title) + ' [#' + x.n + ']');
    }
    L.push('- ⇒ 这 ' + speciesRisk.length + ' 条**不能按 A/B 档对待**，需人工判定可否外推（跨物种迁移本身要单独论证）。');
  }
  L.push('');

  // ── 四、时间分布 ─────────────────────────────────────────
  L.push('### 四、时间分布');
  L.push('');
  // ★ 基准年必须可注入：用 `new Date()` 会让同一份数据在不同年份产出不同文字，
  //   产物 diff 出现无法解释的噪声。调用方传 summary.startedAt 的年份即可保证确定性。
  const nowYear = Number.isFinite(Number(o.nowYear)) ? Number(o.nowYear) : new Date().getUTCFullYear();
  const bucket = { recent: [], mid: [], old: [], unknown: [] };
  list.forEach((x, i) => {
    const y = x.r && x.r.year;
    const n = i + 1;
    if (y === null || y === undefined || y === '' || !Number.isFinite(Number(y))) { bucket.unknown.push(n); return; }
    const age = nowYear - Number(y);
    if (age <= 5) bucket.recent.push(n);
    else if (age <= 10) bucket.mid.push(n);
    else bucket.old.push(n);
  });
  L.push('- 近 5 年（' + (nowYear - 5) + '–' + nowYear + '）：' + bucket.recent.length + ' 条 · ' + refs(bucket.recent));
  L.push('- 6–10 年：' + bucket.mid.length + ' 条 · ' + refs(bucket.mid));
  L.push('- 10 年以上：' + bucket.old.length + ' 条 · ' + refs(bucket.old));
  if (bucket.unknown.length) {
    L.push('- **年份缺失：' + bucket.unknown.length + ' 条** · ' + refs(bucket.unknown) +
      ' —— 缺失不等于「旧」，也不等于任何具体年份，无法据此判断时效性。');
  } else {
    L.push('- 年份缺失：0 条（全部记录都有可解析的发表年）。');
  }
  L.push('');

  // ── 五、需人工优先处理 ──────────────────────────────────
  L.push('### 五、需人工优先处理');
  L.push('');
  const flagKeys = Object.keys(flagsOf).sort();
  if (!flagKeys.length) {
    L.push('- 无复核标记（`flags` 全为空）。注意：**没有标记不等于没有问题**，' +
      '只是启发式规则没触发，逐条核对仍需进行。');
  } else {
    for (const f of flagKeys) {
      L.push('- **' + (FL[f] || f) + '**：' + flagsOf[f].length + ' 条 · ' + refs(flagsOf[f]));
    }
  }
  L.push('');

  // ── 六、证据缺口 ─────────────────────────────────────────
  L.push('### 六、证据缺口（工具能如实说出的「不知道」）');
  L.push('');
  const gaps = [];
  if (!A) gaps.push('**无任何 A 档记录** ⇒ 目前不具备「直接支撑宣称」的候选');
  if (!hasClaimable) gaps.push('**无 A/B 档记录** ⇒ 连「有较强支持力」的候选也没有');
  if (missingSample) gaps.push('样本量未识别 ' + missingSample + ' 条 · ' + refs(missingSampleRows) +
    '（分级里的样本量一项为空，**不是「小样本」**）');
  if (missingDoi) gaps.push('无 DOI ' + missingDoi + ' 条 · ' + refs(missingDoiRows) +
    '（难以定位原文，也难以在总线里稳定去重）');
  if (bucket.unknown.length) gaps.push('年份缺失 ' + bucket.unknown.length + ' 条 · ' + refs(bucket.unknown) +
    '（时序维度不可用）');
  if (speciesRisk.length) gaps.push('A/B 档中物种不达标 ' + speciesRisk.length + ' 条 · ' +
    refs(speciesRisk.map((x) => x.n)) + '（见第三节）');
  if (!gaps.length) {
    L.push('- 未发现结构性缺口（各档齐全、字段完整）。仍须人工逐条核对全文。');
  } else {
    for (const s of gaps) L.push('- ' + s);
  }
  L.push('');
  L.push('> 本节的所有数字均由脚本从证据数据算出；如需改动结论，请改数据后重跑，' +
    '**不要手改本节文字** —— 否则行号与表格将不再对应。');
  L.push('');
  L.push('---');
  L.push('');

  return {
    md: L,
    stats: {
      total, reviewed, allCandidate, nowYear,
      gradeStat: mine, aTarget,
      speciesRisk: speciesRisk.length,
      flags: flagsOf,
      gaps: gaps.length,
      sections: 6,
    },
  };
}

module.exports = { VERSION, buildSynthesis, refs, brief, pctAll, MAX_REFS };
