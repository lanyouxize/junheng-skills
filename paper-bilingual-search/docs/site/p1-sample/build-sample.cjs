#!/usr/bin/env node
/* eslint-disable */
/**
 * build-sample.cjs — 生成 P1 交付样本（报告 + 元典站点包），可复现
 *
 * 跑法：node build-sample.cjs
 *
 * 产出：
 *   report-sample.md     assemble 的完整报告（综合归纳 → 图 → 表 → 逐条明细）
 *   pack/                站点包（index / README / moc-entry / charts / manifest）
 *
 * ⚠ 数据性质：**拟真夹具**，不是真实检索产物。形状按 2026-10-21 实测复刻，
 *   目的是把 P1 的两条边界一次摆出来：
 *     ① 归纳里 `[#n]` 必须能指回表格——夹具刻意含「A 档但物种是体外」「年份缺失」
 *        「D 档两种成因」三类情形，归纳每一句都要落到具体行号上；
 *     ② 站点包必须自包含且可校验——包里 index.md 的图全在 charts/ 下，manifest 记 sha256。
 */
'use strict';
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

const OUT = __dirname;
const WORK = path.join(OUT, '.work');

function rec(g, rel, year, o) {
  const opt = o || {};
  return {
    idx: opt.idx || 0,
    titleEn: opt.title || '',
    year: year,
    doi: opt.doi === null ? undefined : (opt.doi || ('10.9999/sample.' + (opt.idx || 0))),
    evidence: {
      evidenceGrade: g,
      evidenceGradeLabel: { A: '靶动物 RCT/SR', B: '靶动物对照或设计良好', C: '间接物种/观察性/体外', D: '证据薄弱或信息不足' }[g],
      designLevel: { value: opt.design || 'L2', label: '对照试验', confidence: 'medium', candidates: [] },
      speciesRelevance: { relevance: rel, label: rel, confidence: 'medium', targetSpecies: [] },
      sampleSize: { value: opt.n === null ? null : (opt.n === undefined ? 24 : opt.n), confidence: 'medium', candidates: [] },
      dose: { candidates: [] },
      gradeBasis: opt.basis || 'design_identified',
      flags: opt.flags || [],
      needsReview: true,
      inputs: { abstractSource: 'epmc_full' },
      publicationYear: year,
    },
  };
}

const rows = [
  rec('A', 'target_species', 2026, { idx: 1, design: 'L1', n: 48, title: 'Dietary potassium increases urine volume in senior cats: a randomised crossover trial' }),
  rec('A', 'in_vitro_only', 2024, { idx: 2, design: 'L1', title: 'Renal epithelial cell line response to potassium chloride in vitro', flags: ['in_vitro_target_species_cells'] }),
  rec('B', 'target_species', 2023, { idx: 3, title: 'Psyllium husk supplementation and hairball excretion in long-haired cats', flags: ['non_target_species_verify'] }),
  rec('C', 'mixed_species', 2021, { idx: 4, design: 'L3', title: 'Fibre blends and faecal quality across multiple species' }),
  rec('C', 'non_target_animal', 2019, { idx: 5, design: 'L3', title: 'Fibre digestibility in growing pigs fed psyllium' }),
  rec('D', 'target_species', 2014, { idx: 6, design: 'U', basis: 'design_unrecognized', title: 'Clinical observations on urolithiasis management (abstract only)', n: null }),
  rec('D', 'unclear', 2008, { idx: 7, design: 'U', basis: 'design_unrecognized', title: 'Survey of cat owners on hairball frequency', n: null, doi: null }),
  rec('D', 'mixed_species', 1998, { idx: 8, design: 'L5', basis: 'design_identified', title: 'Cystine urolithiasis in dogs and cats: a case series' }),
  rec('D', 'unclear', null, { idx: 9, design: 'U', basis: 'design_unrecognized', title: 'Unindexed conference abstract', n: null }),
  rec('D', 'unclear', 'n.d.', { idx: 10, design: 'U', basis: 'text_too_short', title: 'Short note', n: null, doi: null }),
];

function ensure(dir) { fs.mkdirSync(dir, { recursive: true }); }

function main() {
  fs.rmSync(WORK, { recursive: true, force: true });
  ensure(path.join(WORK, 'raw'));
  fs.writeFileSync(path.join(WORK, 'raw', '01-k.json'), JSON.stringify({ runId: 'SAMPLE', keyword: '猫 排毛 / 泌尿', records: rows }), 'utf8');
  fs.writeFileSync(path.join(WORK, 'summary.json'), JSON.stringify({
    runId: 'SAMPLE',
    startedAt: '2026-10-21T02:00:00Z',
    site: 'kuluer',
    keywords: { '猫 排毛 / 泌尿': { count: rows.length } },
    dedupe: { total: rows.length, unique: rows.length, duplicates: 0 },
  }), 'utf8');

  const root = path.resolve(OUT, '../../..', 'scripts');
  const assemble = path.join(root, 'assemble-report.cjs');
  const packSite = path.join(root, 'pack-site.cjs');

  // 1) 报告
  const r1 = execFileSync(process.execPath, [assemble, '--dir', WORK, '--format', 'md'], { encoding: 'utf8' });
  const reportPath = JSON.parse(r1).md;
  fs.copyFileSync(reportPath, path.join(OUT, 'report-sample.md'));

  // 2) 站点包
  const packOut = path.join(OUT, 'pack');
  fs.rmSync(packOut, { recursive: true, force: true });
  const r2 = execFileSync(process.execPath, [packSite, '--dir', WORK, '--out', packOut,
    '--slug', 'paper-search-20261021-sample'], { encoding: 'utf8' });
  const manifest = JSON.parse(r2);

  // 3) 自校验（样本必须自己先过 verify，否则交付样本本身就是坏的）
  const r3 = execFileSync(process.execPath, [packSite, '--verify', packOut], { encoding: 'utf8' });
  const ver = JSON.parse(r3);

  // 4) 清理中间目录，只留交付物
  fs.rmSync(WORK, { recursive: true, force: true });

  console.log('=== 报告 ===');
  const md = fs.readFileSync(path.join(OUT, 'report-sample.md'), 'utf8');
  console.log('  report-sample.md  ' + Buffer.byteLength(md) + 'B  ' + md.split('\n').length + ' 行');
  console.log('  小节：' + ['## 综合归纳', '## 证据分布图', '## 证据分级候选一览'].filter((h) => md.includes(h)).join(' → '));
  const refs = [...md.matchAll(/\[#\d+\]/g)].length;
  console.log('  归纳行号引用：' + refs + ' 处');

  console.log('=== 站点包 ===');
  console.log('  slug     ' + manifest.slug);
  console.log('  status   ' + manifest.status);
  console.log('  files    ' + manifest.files.join(', '));
  console.log('  verify   ' + (ver.ok ? 'OK（sha256 全部匹配）' : 'FAIL ' + ver.errors.join(' | ')));
  if (!ver.ok) process.exitCode = 1;
}

main();
