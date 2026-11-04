#!/usr/bin/env node
/* eslint-disable */
/**
 * build-sample.cjs — 生成证据分布三图的交付样本（可复现）
 *
 * ⚠ 数据性质：**拟真夹具**，不是真实检索产物。
 *   分布形状、年份跨度、物种构成按 2026-10-21 实测的形状复刻（A 极少、D 过半、年份跨 1998-2026），
 *   目的是把三条边界情形一次性摆出来：
 *     ① 全候选（needsReview 恒 true）—— 斜纹 + 警示带；
 *     ② 年份缺失（null 与 'n.d.' 同时存在）—— 「未标注」列 + 非法年份单列；
 *     ③ 跨度 29 年 —— 触发「>14 年按 5 年分段」路径。
 *   文件名与真实运行一致（evidence-grade-dist.svg 等），因此可直接替换比对。
 *
 * 用法：node build-sample.cjs
 */
'use strict';
const fs = require('fs');
const path = require('path');
const EC = require('../../../scripts/lib/evidence-charts.cjs');
const { execFileSync } = require('child_process');

const OUT = __dirname;

/** 一条记录，字段形状与 gradeAll() 的产出一致 */
function rec(g, rel, year, opts) {
  const o = opts || {};
  return {
    idx: o.idx || 0,
    titleEn: o.title || '',
    year: year,
    evidence: {
      evidenceGrade: g,
      evidenceGradeLabel: { A: '靶动物 RCT/SR', B: '靶动物对照或设计良好', C: '间接物种/观察性/体外', D: '证据薄弱或信息不足' }[g],
      designLevel: { value: o.design || 'L2', label: '对照试验', confidence: 'medium', candidates: [] },
      speciesRelevance: { relevance: rel, label: rel, confidence: 'medium', targetSpecies: [] },
      sampleSize: { value: o.n || 24, confidence: 'medium', candidates: [] },
      dose: { candidates: [] },
      gradeBasis: o.basis || 'design_identified',
      flags: [],
      needsReview: true,
      reviewed: o.reviewed === true,
      inputs: { abstractSource: o.src || 'epmc_full' },
      publicationYear: year,
    },
  };
}

const rows = [];
const push = (n, g, rel, years, opts) => {
  for (let i = 0; i < n; i++) rows.push(rec(g, rel, years[i % years.length], Object.assign({ idx: rows.length + 1 }, opts || {})));
};

// —— 等级 × 物种：形状按实测（A 2 条、B 5 条、C 8 条、D 52 条）
push(2, 'A', 'target_species', [2026, 2024], { design: 'L1', n: 48 });
push(5, 'B', 'target_species', [2023, 2022, 2021, 2020, 2019], { n: 32 });
push(3, 'C', 'mixed_species', [2020, 2019, 2018], { design: 'L3' });
push(3, 'C', 'in_vitro_only', [2020, 2017, 2015], { design: 'L4' });
push(2, 'C', 'non_target_animal', [2016, 2012], { design: 'L3' });
push(24, 'D', 'unclear', [2014, 2011, 2008, 2005, 2001, 1998], { design: 'U', basis: 'design_unrecognized' });
push(20, 'D', 'target_species', [2013, 2019, 2006, 2010], { design: 'U', basis: 'design_unrecognized' });
push(8, 'D', 'mixed_species', [2014, 2012, 2010], { design: 'L5', basis: 'design_identified' });

// —— 年份边界：1 条 null（进「未标注」）、1 条 'n.d.'（进「非法」）
rows.push(rec('D', 'unclear', null, { idx: rows.length + 1, design: 'U', basis: 'design_unrecognized' }));
rows.push(rec('D', 'unclear', 'n.d.', { idx: rows.length + 1, design: 'U', basis: 'design_unrecognized' }));

// —— 人工确认态：全候选版 + 部分确认版（各出一套，用来看警示带/斜纹的差别）
const allCand = rows.map((r) => r);
const partly = rows.map((r, i) => {
  const c = JSON.parse(JSON.stringify(r));
  c.evidence.reviewed = i < 3;              // 前 3 条人工核过（2 条 A + 1 条 B）
  return c;
});

function buildAndWrite(tag, data) {
  const st = EC.collect(data);
  const vr = EC.validate(st);
  const built = EC.buildCharts(data);
  const report = { tag, total: st.total, gradeStat: st.gradeStat, candidate: st.candidateCount, confirmed: st.confirmedCount, yearMissing: st.yearMissing, yearInvalid: st.yearInvalid, violations: vr.violations, files: [] };
  for (const c of built.charts) {
    const name = tag === 'all-candidate' ? c.file : c.file.replace('.svg', '--partly-reviewed.svg');
    fs.writeFileSync(path.join(OUT, name), c.svg, 'utf8');
    report.files.push({ file: name, bytes: Buffer.byteLength(c.svg), lines: c.svg.split('\n').length, geom: EC.geomCheck(c.svg) });
  }
  return report;
}

const r1 = buildAndWrite('all-candidate', allCand);
const r2 = buildAndWrite('partly-reviewed', partly);

fs.writeFileSync(path.join(OUT, 'sample-stats.json'), JSON.stringify({ allCandidate: r1, partlyReviewed: r2 }, null, 2), 'utf8');

console.log('=== 全候选 ===');
console.log('  total=' + r1.total + '  A' + r1.gradeStat.A + '/B' + r1.gradeStat.B + '/C' + r1.gradeStat.C + '/D' + r1.gradeStat.D +
  '  候选' + r1.candidate + '/确认' + r1.confirmed + '  年份缺失' + r1.yearMissing + '/非法' + r1.yearInvalid);
console.log('  不变式违规: ' + (r1.violations.length ? r1.violations.join('；') : '0'));
for (const f of r1.files) console.log('  ' + f.file + '  ' + f.bytes + 'B  ' + f.lines + '行  几何' + (f.geom.length ? 'FAIL ' + f.geom[0] : 'OK'));
console.log('=== 部分确认 ===');
console.log('  候选' + r2.candidate + '/确认' + r2.confirmed + '  不变式违规: ' + (r2.violations.length ? r2.violations.join('；') : '0'));
for (const f of r2.files) console.log('  ' + f.file + '  ' + f.bytes + 'B  几何' + (f.geom.length ? 'FAIL ' + f.geom[0] : 'OK'));
