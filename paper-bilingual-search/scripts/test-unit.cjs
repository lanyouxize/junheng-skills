#!/usr/bin/env node
/* eslint-disable */
/**
 * test-unit.cjs — 纯逻辑离线单测（无需网络/浏览器）
 * 运行: node scripts/test-unit.cjs  → 全部通过则退出码 0
 * 覆盖: byline 解析 / DOI 抽取 / 填充率 / 去重 / 标题相似度 / CSV 转义 / 引用块
 *       / 证据分级（设计·物种·样本量·剂量·等级）/ 检索式语法校验 / PRISMA 计数
 */
'use strict';
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { parseByline, extractDoi, fillRate } = require('./lib/extract.cjs');
const EX = require('./lib/extract.cjs');       // v4.7：翻译面板失败态分类 + 记录级译文真值（纯函数）
const REL = require('./lib/relevance.cjs');    // v4.7 挂账：主题相关性打分/排序（纯函数，零站点请求）
const RK = require('./rank-records.cjs');      // v4.7 挂账：本地排序 CLI（渲染层可离线直测）
const ENR = require('./lib/enrich.cjs');
const { dedupe, titleSimilarity, normalizeDoi, dedupeTag } = ENR;
const EV = require('./lib/evidence.cjs');
const P = require('./lib/prisma.cjs');
const Q = require('./build-queries.cjs');
const CL = require('./lib/cli.cjs');          // v4 输入层（纯函数，可离线直测）
const AR = require('./assemble-report.cjs');  // v4 汇总层（readRawGroups / assemble 可直接调用）
const PR = require('./lib/probe.cjs');        // 2026-10-19：计数探针三态（采集失败 ≠ 真 0，纯函数）
// v4.15（A/P0 批）：多源层 —— 归一化 / 注册表 / 调度器。三者均为纯逻辑或可注入 IO，可离线直测。
const NRM = require('./lib/sources/normalize.cjs');
const SRC = require('./lib/sources/index.cjs');
const SCH = require('./lib/scheduler.cjs');
const FTC = require('./lib/fulltext-chain.cjs');   // 2026-10-26（B 批）：全文四级回退链（判据纯函数在离线测）
// v4.15（A-2 批）：多源结果 → CLI 记录组的聚合层（纯函数，可离线直测）
const MR = require('./lib/multi-run.cjs');
const EPMC_SRC = require('./lib/sources/europepmc.cjs');
const CR_SRC = require('./lib/sources/crossref.cjs');

let pass = 0, fail = 0;
function t(name, fn) {
  try { fn(); pass++; console.log('  ✓ ' + name); }
  catch (e) { fail++; console.log('  ✗ ' + name + ' → ' + String(e.message).slice(0, 160)); }
}

console.log('parseByline:');
t('三段式（作者 - 来源, 年份 - 域名）', () => {
  const r = parseByline('JA Sturman\xa0- Physiological reviews, 1993 - journals.physiology.org');
  assert.strictEqual(r.authors, 'JA Sturman');
  assert.strictEqual(r.source, 'Physiological reviews');
  assert.strictEqual(r.year, 1993);
  assert.strictEqual(r.domain, 'journals.physiology.org');
});
t('两段式（中文文献常无域名）', () => {
  const r = parseByline('罗发洪\xa0- 饲料广角, 2006');
  assert.strictEqual(r.authors, '罗发洪');
  assert.strictEqual(r.source, '饲料广角');
  assert.strictEqual(r.year, 2006);
  assert.strictEqual(r.domain, null);
});
t('来源内含连字符（Journal of Animal - Science）', () => {
  const r = parseByline('A B - Journal of Animal - Science, 2010 - x.com');
  assert.strictEqual(r.source, 'Journal of Animal - Science');
  assert.strictEqual(r.year, 2010);
});
t('无年份时不臆造', () => {
  const r = parseByline('Some Author - Some Venue');
  assert.strictEqual(r.year, null);
  assert.strictEqual(r.source, 'Some Venue');
});
t('空值安全', () => {
  const r = parseByline(null);
  assert.deepStrictEqual(r, { authors: null, source: null, year: null, domain: null });
});

console.log('extractDoi:');
t('从 /doi/pdf/ 直链抽 DOI', () => {
  assert.strictEqual(extractDoi('https://journals.physiology.org/doi/pdf/10.1152/physrev.1993.73.1.119'), '10.1152/physrev.1993.73.1.119');
});
t('去掉尾部句点', () => {
  assert.strictEqual(extractDoi('http://x/doi/10.1016/s0014-4835(05)80024-7.'), '10.1016/s0014-4835(05)80024-7');
});
t('非 DOI 链接返回 null（实测多数直链即如此）', () => {
  assert.strictEqual(extractDoi('https://www.ncbi.nlm.nih.gov/pmc/articles/PMC123/'), null);
  assert.strictEqual(extractDoi(null), null);
});

console.log('fillRate（静默降级防护）:');
t('全空 → 0', () => {
  const f = fillRate([{ titleEn: null }, { titleEn: '' }]);
  assert.strictEqual(f.title, 0);
});
t('部分缺失 → 按比例', () => {
  const f = fillRate([{ titleEn: 'a', byline: 'b' }, { titleEn: null, byline: 'b' }]);
  assert.strictEqual(f.title, 0.5);
  assert.strictEqual(f.byline, 1);
});

console.log('dedupe（跨关键词去重）:');
t('同标题同年份判重，保留首次出现', () => {
  const groups = [
    { keyword: 'k1', records: [{ idx: 1, titleEn: 'Taurine in development', year: 1993 }] },
    { keyword: 'k2', records: [{ idx: 1, titleEn: 'Taurine in development.', year: 1993 }, { idx: 2, titleEn: 'Other paper', year: 2020 }] },
  ];
  const d = dedupe(groups);
  assert.strictEqual(d.unique.length, 2, '唯一数应为 2');
  assert.strictEqual(d.duplicates.length, 1);
  assert.strictEqual(d.duplicates[0].firstSeenIn, 'k1');
});
t('DOI 优先作为唯一键', () => {
  const groups = [
    { keyword: 'k1', records: [{ idx: 1, enrich: { doi: '10.1/a' }, titleEn: 'A', year: 2000 }] },
    { keyword: 'k2', records: [{ idx: 1, enrich: { doi: '10.1/a' }, titleEn: 'A (different casing)', year: 2000 }] },
  ];
  assert.strictEqual(dedupe(groups).duplicates.length, 1);
});
t('不同文献不误判重', () => {
  const groups = [{ keyword: 'k1', records: [{ idx: 1, titleEn: 'Taurine and cats', year: 1993 }, { idx: 2, titleEn: 'Taurine and dogs', year: 1995 }] }];
  assert.strictEqual(dedupe(groups).duplicates.length, 0);
});

console.log('dedupe v4.2（并查集连通 + DOI 归一化 + 空值不参与 + 年份冲突保护）:');
const one = (o) => Object.assign({ idx: 1, titleEn: '', year: null }, o);
const grp = (kw, records) => ({ keyword: kw, records });

t('① 年份单侧缺失仍判重（v4.1 漏去重）', () => {
  const d = dedupe([grp('k1', [one({ titleEn: 'Taurine in development', year: 1993 })]),
                    grp('k2', [one({ titleEn: 'Taurine in development', year: null })])]);
  assert.strictEqual(d.duplicates.length, 1, '一侧无年份也应判为同一篇');
  assert.strictEqual(d.duplicates[0].firstSeenIn, 'k1');
});

t('② DOI 大小写差异判重', () => {
  const d = dedupe([grp('k1', [one({ enrich: { doi: '10.1007/A-1' }, titleEn: 'P', year: 2020 })]),
                    grp('k2', [one({ enrich: { doi: '10.1007/a-1' }, titleEn: 'P', year: 2020 })])]);
  assert.strictEqual(d.duplicates.length, 1);
});

t('③ DOI 带 doi.org 前缀判重', () => {
  const d = dedupe([grp('k1', [one({ enrich: { doi: '10.1007/x' }, titleEn: 'P', year: 2020 })]),
                    grp('k2', [one({ enrich: { doi: 'https://doi.org/10.1007/x' }, titleEn: 'P', year: 2020 })])]);
  assert.strictEqual(d.duplicates.length, 1);
});

t('④ DOI 末点差异判重', () => {
  const d = dedupe([grp('k1', [one({ enrich: { doi: '10.1007/x.' }, titleEn: 'P', year: 2020 })]),
                    grp('k2', [one({ enrich: { doi: '10.1007/x' }, titleEn: 'P', year: 2020 })])]);
  assert.strictEqual(d.duplicates.length, 1);
});

t('⑤ 空标题 + 空年份：不塌成一条（★ v4.1 会丢失数据）', () => {
  const d = dedupe([grp('k1', [one({ titleEn: '', year: null, source: 'J1' })]),
                    grp('k2', [one({ titleEn: '', year: null, source: 'J2' })]),
                    grp('k3', [one({ titleEn: '', year: null, source: 'J3' })])]);
  assert.strictEqual(d.unique.length, 3, '3 篇真实论文必须全部保留，不得塌成 1 篇');
  assert.strictEqual(d.duplicates.length, 0);
  assert.strictEqual(d.skipped, 3, '应被记为「不参与去重」');
});

t('⑥ 空标题但 DOI 相同 → 仍按 DOI 判重', () => {
  const d = dedupe([grp('k1', [one({ enrich: { doi: '10.1/z' }, titleEn: '' })]),
                    grp('k2', [one({ enrich: { doi: '10.1/z' }, titleEn: '' })])]);
  assert.strictEqual(d.duplicates.length, 1, '有 DOI 时即便标题为空也应判重');
});

t('⑦ 同标题但年份已知且不同 → 不误删（年份冲突保护）', () => {
  const d = dedupe([grp('k1', [one({ titleEn: 'Same Title', year: 1993 })]),
                    grp('k2', [one({ titleEn: 'Same Title', year: 2020 })])]);
  assert.strictEqual(d.duplicates.length, 0, '同名不同年应视为不同文献');
  assert.strictEqual(d.unique.length, 2);
});

t('⑧ 同标题不同年份时，无年份那条归入已知年份簇', () => {
  const d = dedupe([grp('k1', [one({ titleEn: 'Same Title', year: 1993 })]),
                    grp('k2', [one({ titleEn: 'Same Title', year: null })]),
                    grp('k3', [one({ titleEn: 'Same Title', year: 2020 })])]);
  assert.strictEqual(d.unique.length, 2, '1993 与 2020 两簇；无年份者归入首簇');
  assert.strictEqual(d.duplicates.length, 1);
});

t('⑨ 跨键连通：一条有 DOI、另一条无 DOI 但同标题', () => {
  const d = dedupe([grp('k1', [one({ enrich: { doi: '10.1/c' }, titleEn: 'Cross Paper', year: 2019 })]),
                    grp('k2', [one({ titleEn: 'Cross Paper', year: 2019 })])]);
  assert.strictEqual(d.duplicates.length, 1, 'DOI 与标题应互链为同一簇');
});

t('⑩ normalizeDoi 各形态归一', () => {
  assert.strictEqual(normalizeDoi('10.1007/ABC'), '10.1007/abc');
  assert.strictEqual(normalizeDoi('https://doi.org/10.1007/x'), '10.1007/x');
  assert.strictEqual(normalizeDoi('http://dx.doi.org/10.1007/x'), '10.1007/x');
  assert.strictEqual(normalizeDoi('doi:10.1007/x'), '10.1007/x');
  assert.strictEqual(normalizeDoi('10.1007/x.'), '10.1007/x');
  assert.strictEqual(normalizeDoi('  10.1007/x  '), '10.1007/x');
  assert.strictEqual(normalizeDoi(''), '');
  assert.strictEqual(normalizeDoi(null), '');
});

t('⑪ dedupeTag：无可判定标识时返回 null', () => {
  assert.strictEqual(dedupeTag(one({ titleEn: '', year: null })), null);
  assert.strictEqual(dedupeTag(one({ titleEn: 'A Title' })), 't:a title');
  assert.strictEqual(dedupeTag(one({ enrich: { doi: '10.1/A' } })), 'doi:10.1/a');
});

t('⑫ 并查集结果稳定：重复两次调用一致', () => {
  const gs = [grp('k1', [one({ titleEn: 'X', year: 2000 }), one({ idx: 2, titleEn: 'Y', year: 2001 })]),
              grp('k2', [one({ titleEn: 'X', year: 2000 }), one({ idx: 2, titleEn: 'Y.', year: 2001 })])];
  const a = dedupe(gs), b = dedupe(gs);
  assert.strictEqual(a.unique.length, b.unique.length);
  assert.strictEqual(a.duplicates.length, 2);
  assert.deepStrictEqual(a.unique.map(x => x.titleEn), b.unique.map(x => x.titleEn));
});

console.log('titleSimilarity（防误配）:');
t('同一文献（含标点差异）相似度 > 0.6', () => {
  assert.ok(titleSimilarity('Taurine in development', 'Taurine in development.') > 0.6);
});
t('不同文献相似度低', () => {
  assert.ok(titleSimilarity('Taurine in development', 'Retinal degeneration in cats') < 0.6);
});

console.log('CSV 转义 / 引用块:');
t('含逗号与引号需转义', () => {
  const esc = v => (/[",\r\n]/.test(String(v)) ? '"' + String(v).replace(/"/g, '""') + '"' : String(v));
  assert.strictEqual(esc('a,b'), '"a,b"');
  assert.strictEqual(esc('say "hi"'), '"say ""hi"""');
});
t('多行文本每行加 >', () => {
  const quote = t => String(t).split(/\r?\n/).map(l => '> ' + l.trim()).join('\n');
  assert.strictEqual(quote('line1\nline2'), '> line1\n> line2');
});

// ---------- 证据分级 ----------
console.log('证据分级 · 研究设计:');
const mk = o => Object.assign({ titleEn: '', abstractEn: '', enrich: null, year: null }, o);
t('随机双盲交叉试验 → L2', () => {
  const e = EV.gradeRecord(mk({
    titleEn: 'Effects of a diet on skin barrier in dogs',
    abstractEn: 'In a randomized, double-blind, placebo-controlled crossover trial, twenty-four adult beagle dogs were assigned (n=24) to receive 0.5% hyaluronic acid.',
  }));
  assert.strictEqual(e.designLevel.value, 'L2');
  assert.strictEqual(e.sampleSize.value, 24);
  assert.strictEqual(e.speciesRelevance.relevance, 'target_species');
  assert.strictEqual(e.evidenceGrade, 'A');
  assert.ok(e.dose.candidates.some(d => d.raw.includes('%')));
});
t('系统综述 → L1 且计入纳入研究数', () => {
  const e = EV.gradeRecord(mk({
    titleEn: 'Omega-3 in feline dermatology: a systematic review',
    abstractEn: 'This systematic review pooled data from 7 randomized controlled trials in cats.',
  }));
  assert.strictEqual(e.designLevel.value, 'L1');
  assert.strictEqual(e.includedStudies.value, 7);
  assert.ok(!e.flags.includes('design_conflict'), '综述提及 RCT 不应判为设计冲突');
});
t('猪分组饲养 → 非靶动物且需人工排除', () => {
  const e = EV.gradeRecord(mk({
    titleEn: 'Dietary taurine and growth performance in weaned piglets',
    abstractEn: 'A total of 180 piglets were allocated to 3 dietary treatments.',
  }));
  assert.strictEqual(e.speciesRelevance.relevance, 'non_target_animal');
  assert.ok(e.speciesRelevance.needsManualExclude);
  assert.ok(e.flags.includes('non_target_species_verify'));
  assert.strictEqual(e.evidenceGrade, 'C', '猪 L3 试验应为 C 而非 A');
});
t('体外犬细胞 → 标记 in_vitro_target_species_cells', () => {
  const e = EV.gradeRecord(mk({
    titleEn: 'In vitro effects of green tea polyphenols on canine keratinocytes',
    abstractEn: 'Canine keratinocyte cell culture was exposed to 10 mg/kg EGCG.',
  }));
  assert.strictEqual(e.designLevel.value, 'L4');
  assert.ok(e.flags.includes('in_vitro_target_species_cells'));
});
t('无任何信号 → U 且标记 design_unknown，等级 D', () => {
  const e = EV.gradeRecord(mk({ titleEn: 'Serum chemistry values in cats', abstractEn: 'Values were summarized.' }));
  assert.strictEqual(e.designLevel.value, 'U');
  assert.ok(e.flags.includes('design_unknown'));
  assert.strictEqual(e.evidenceGrade, 'D');
  assert.ok(!e.flags.includes('non_target_species_verify'), '猫应识别为靶动物');
});
t('needsReview 恒为 true（红线：不得自动判定）', () => {
  [mk({ titleEn: 'a randomized controlled trial in dogs', abstractEn: 'Twenty dogs.' }), mk({ titleEn: 'X', abstractEn: '' })]
    .forEach(r => assert.strictEqual(EV.gradeRecord(r).needsReview, true));
});
t('每个候选值都必须带原文依据或置信度 none', () => {
  const e = EV.gradeRecord(mk({ titleEn: 'A feeding trial in cats', abstractEn: 'Ten cats were enrolled in a feeding trial.' }));
  const c0 = e.designLevel.candidates[0];
  assert.ok(c0.evidence && c0.evidence.length > 0, '设计候选必须携带依据片段');
  assert.ok(['high', 'medium', 'low', 'none'].includes(e.designLevel.confidence));
});
t('优先采用完整摘要而非节选（enrich.abstractFull）', () => {
  const r = mk({ titleEn: 'Dose response of vitamin E in dogs', abstractEn: 'snippet only.', enrich: { abstractFull: 'In a randomized controlled trial, 30 dogs received 400 IU/kg vitamin E daily.' } });
  const e = EV.gradeRecord(r);
  assert.strictEqual(e.inputs.abstractSource, 'epmc_full');
  assert.strictEqual(e.designLevel.value, 'L2');
  assert.strictEqual(e.sampleSize.value, 30);
});
t('中文犬猫题名必须识别为靶动物（否则中文文献一律 unclear）', () => {
  const e = EV.gradeRecord(mk({ titleEn: '牛磺酸在犬猫日粮中的应用', abstractEn: '综述了牛磺酸在宠物食品中的研究进展。' }));
  assert.strictEqual(e.speciesRelevance.relevance, 'target_species');
  assert.ok(!e.flags.includes('non_target_species_verify'));
});
t('「牛磺酸」不得被误判为畜禽（单字 牛 陷阱）', () => {
  const e = EV.gradeRecord(mk({ titleEn: '牛磺酸对猫心肌的影响', abstractEn: '牛磺酸是猫的必需氨基酸。' }));
  assert.ok(e.speciesRelevance.detected.every(d => d.key !== 'livestock'), '不得出现 livestock');
  assert.strictEqual(e.speciesRelevance.relevance, 'target_species');
});
t('中文哺乳仔猪试验必须识别为畜禽并标记排除', () => {
  const e = EV.gradeRecord(mk({ titleEn: '日粮牛磺酸对仔猪生长性能的影响', abstractEn: '选取 180 头仔猪进行试验。' }));
  assert.strictEqual(e.speciesRelevance.relevance, 'non_target_animal');
  assert.ok(e.speciesRelevance.needsManualExclude);
});
t('同一物种中英双规则命中须归并而非重复', () => {
  const e = EV.gradeRecord(mk({ titleEn: 'cats and 猫 comparison', abstractEn: 'Cats (猫) were compared with dogs (犬).' }));
  const keys = e.speciesRelevance.detected.map(d => d.key);
  assert.strictEqual(new Set(keys).size, keys.length, '检测到的物种不应出现重复键');
});

// ---------- 证据分级 · v4.5 物种语境排除（A/B/C 三类缺陷修复） ----------
// 背景：D7/D5 —— 靶物种词撞病名（犬瘟热）、中文非靶词缺失、英文缺词。
// ★ 先红后绿：对应断言在 v4.4 代码上 6/8 失败（见 .verify/r3-red.cjs）。
console.log('证据分级 v4.5 · 物种语境排除:');
t('中文：病名中的靶物种词不得计入物种识别（犬瘟热/犬细小/猫瘟/猫白血病）', () => {
  const cases = [
    ['试验开始前对水貂接种犬瘟热和细小病毒疫苗。测定饲粮蛋白质消化率。', 'non_target_animal'],
    ['犬细小病毒的分子流行病学与病原生物学特性分析。', 'unclear'],
    ['猫瘟病毒的分离鉴定与致病性研究。', 'unclear'],
    ['猫白血病病毒的检测与流行病学调查。', 'unclear'],
  ];
  for (const [text, exp] of cases) assert.strictEqual(EV.detectSpecies(text, text).relevance, exp, '[' + text.slice(0, 14) + ']');
});
t('被语境排除的病名命中须在 diseaseNameMentions 可见（不静默丢弃）', () => {
  const s = EV.detectSpecies('试验开始前对水貂接种犬瘟热和细小病毒疫苗。', '试验开始前对水貂接种犬瘟热和细小病毒疫苗。');
  assert.ok((s.diseaseNameMentions || []).length >= 1, '应有病名用法记录');
  assert.ok(s.diseaseNameMentions.some(m => m.key === 'dog'), '犬瘟热中的「犬」应记为病名用法');
  assert.ok(s.needsManualExclude);
});
t('英文：canine/feline + 病名词不得计入物种识别', () => {
  const cases = [
    ['Mink were vaccinated against canine distemper and parvovirus. Dietary protein digestibility was measured.', 'non_target_animal'],
    ['Feline leukemia virus detection in a shelter population.', 'unclear'],
    ['Canine parvovirus molecular epidemiology study.', 'unclear'],
    ['Feline coronavirus genomic sequence analysis and phylogenetic study.', 'unclear'],
  ];
  for (const [text, exp] of cases) assert.strictEqual(EV.detectSpecies(text, text).relevance, exp, '[' + text.slice(0, 22) + ']');
});
t('中文非靶物种词补齐（水貂/雪貂/狐/对虾/鸽/鸭/猴 → 非靶动物）', () => {
  const cases = [
    ['育成期雌性水貂的生长性能与营养物质消化率。', 'non_target_animal'],
    ['雪貂的营养需要与消化生理研究。', 'non_target_animal'],
    ['蓝狐的饲料转化效率研究。', 'non_target_animal'],
    ['凡纳滨对虾的生长性能研究。', 'non_target_animal'],
    ['肉鸽的氨基酸需要量研究。', 'non_target_animal'],
    ['樱桃谷鸭的营养代谢试验。', 'non_target_animal'],
    ['食蟹猴的消化生理研究。', 'non_target_animal'],
  ];
  for (const [text, exp] of cases) assert.strictEqual(EV.detectSpecies(text, text).relevance, exp, '[' + text.slice(0, 12) + ']');
});
t('英文畜禽缺词补齐（rooster/cockerel → 非靶动物）', () => {
  assert.strictEqual(EV.detectSpecies('The rooster was fed a corn-soybean diet.', 'The rooster was fed a corn-soybean diet.').relevance, 'non_target_animal');
  assert.strictEqual(EV.detectSpecies('Cockerels were used in the feeding trial.', 'Cockerels were used in the feeding trial.').relevance, 'non_target_animal');
});
t('高风险单字保护：青蟹素/鹅膏/猴头菇/鱼油 不得误命中非靶物种', () => {
  for (const text of ['日粮中添加青蟹素对仔猪生长的影响。', '鹅膏毒素的检测方法研究。', '猴头菇多糖的提取工艺优化。', '鱼油对犬皮肤屏障的影响。'])
    assert.ok(!EV.detectSpecies(text, text).detected.some(d => d.key === 'other_animal'), '误命中 other_animal: ' + text.slice(0, 12));
});
t('语境排除不得误伤真·靶动物研究与英文词边界', () => {
  const cases = [
    ['本试验选用12只健康成年比格犬，测定其粗蛋白消化率。', 'target_species'],
    ['选用10只成年猫，评估不同蛋白源的表观消化率。', 'target_species'],
    ['Twelve healthy adult dogs were used to determine apparent protein digestibility.', 'target_species'],
    ['Ten adult cats were fed the test diet; digestibility was measured.', 'target_species'],
    ['The catalyst improved the reaction rate.', 'unclear'],
    ['Horseradish peroxidase was used as a marker.', 'unclear'],
    ['Henna extract was added to the diet.', 'unclear'],
    ['Pigeons were fed a control diet.', 'unclear'],
  ];
  for (const [text, exp] of cases) assert.strictEqual(EV.detectSpecies(text, text).relevance, exp, '[' + text.slice(0, 24) + ']');
});
t('端到端：水貂论文（含犬瘟热疫苗）应判非靶动物且等级 C', () => {
  const e = EV.gradeRecord(mk({ titleEn: '水貂蛋白质消化率', abstractEn: '试验开始前对水貂接种犬瘟热和细小病毒疫苗。测定饲粮蛋白质消化率。' }));
  assert.strictEqual(e.speciesRelevance.relevance, 'non_target_animal');
  assert.strictEqual(e.evidenceGrade, 'C');
});
t('两条返回路径（正常 / 文本过短）必须完全同构', () => {
  const shape = o => JSON.stringify(Object.keys(o).sort())
    + '|' + JSON.stringify(Object.keys(o.designLevel).sort())
    + '|' + JSON.stringify(Object.keys(o.speciesRelevance).sort());
  const normal = EV.gradeRecord(mk({ titleEn: 'A randomized controlled trial in dogs with detailed methods', abstractEn: 'Twenty dogs were enrolled and received 0.5% supplement twice daily.' }));
  const stub = EV.gradeRecord(mk({ titleEn: '短标题', abstractEn: '' }));
  assert.strictEqual(shape(normal), shape(stub), '早退桩与正常返回结构不一致会导致下游渲染崩溃');
});
t('gradeAll 汇总计数自洽', () => {
  const groups = [{ keyword: 'k', records: [
    mk({ titleEn: 'a randomized controlled trial in dogs', abstractEn: 'Twenty dogs were enrolled.', year: 2020 }),
    mk({ titleEn: 'growth performance in piglets', abstractEn: 'Pigs were fed diets.', year: 2019 }),
  ] }];
  const s = EV.gradeAll(groups);
  assert.strictEqual(s.graded, 2);
  assert.strictEqual(Object.values(s.gradeStat).reduce((a, b) => a + b, 0), 2);
  assert.ok(s.needsManualExcludeCount >= 1);
});

// ---------- 证据分级 · v4.3 兜底规则与 D 档成因 ----------
console.log('证据分级 v4.3:');
t('兜底规则：名词/复数形态 digestibility 不再漏判为 U（实测漏判族）', () => {
  const e = EV.gradeRecord(mk({
    titleEn: 'Ileal and total tract nutrient digestibilities in dogs',
    abstractEn: 'Apparent total tract digestibility of crude protein was determined in adult dogs.',
  }));
  assert.strictEqual(e.designLevel.value, 'L3', '应识别为 L3 消化试验，而非 U');
  assert.strictEqual(e.designLevel.topType, 'digestibility_trial');
  assert.strictEqual(e.gradeBasis, 'design_identified');
});
t('兜底规则：评价式「Evaluation of … diets」不再漏判', () => {
  const e = EV.gradeRecord(mk({ titleEn: 'Evaluation of eight commercial dog diets', abstractEn: 'Eight extruded dog diets were compared.' }));
  assert.strictEqual(e.designLevel.value, 'L3');
});
t('★ 兜底规则不得顶掉 in vitro（否则是退步：体外试验被判成活体饲喂试验）', () => {
  const e = EV.gradeRecord(mk({
    titleEn: 'In vitro protein digestibility of dog foods',
    abstractEn: 'An in vitro digestion assay was used to measure protein digestibility.',
  }));
  assert.strictEqual(e.designLevel.value, 'L4', 'in vitro 必须胜出');
  assert.strictEqual(e.designLevel.topType, 'in_vitro');
});
t('★ 兜底规则不得顶掉综述（叙述性综述仍应为 L5）', () => {
  const e = EV.gradeRecord(mk({
    titleEn: 'Protein digestibility in dogs: a review',
    abstractEn: 'This review summarizes studies on nutrient digestibility.',
  }));
  assert.strictEqual(e.designLevel.value, 'L5');
  assert.strictEqual(e.designLevel.topType, 'review_narrative');
});
t('★ 兜底规则优先级必须低于所有既有规则（结构守卫：防止再次被调高而顶掉已识别研究）', () => {
  const dig = EV.DESIGN_RULES.filter(r => r.type === 'digestibility_trial');
  assert.ok(dig.length >= 2, '应含中英两条兜底规则');
  const minOther = Math.min(...EV.DESIGN_RULES.filter(r => r.type !== 'digestibility_trial').map(r => r.priority));
  dig.forEach(r => assert.ok(r.priority < minOther,
    '兜底规则 ' + r.label + ' priority=' + r.priority + ' 未低于全表最低 ' + minOther + '，会顶掉已识别的研究'));
});
t('gradeBasis 三态：未识别 / 已判定 / 文本过短', () => {
  assert.strictEqual(EV.gradeRecord(mk({ titleEn: 'Serum chemistry values in cats', abstractEn: 'Values were summarized.' })).gradeBasis, 'design_unrecognized');
  assert.strictEqual(EV.gradeRecord(mk({ titleEn: 'A feeding trial in cats', abstractEn: 'Ten cats were enrolled in a feeding trial.' })).gradeBasis, 'design_identified');
  assert.strictEqual(EV.gradeRecord(mk({ titleEn: '短标题', abstractEn: '' })).gradeBasis, 'text_too_short');
});
t('gradeAll 输出 gradeBasisStat 且与记录数自洽', () => {
  const groups = [{ keyword: 'k', records: [
    mk({ titleEn: 'a randomized controlled trial in dogs', abstractEn: 'Twenty dogs were enrolled.', year: 2020 }),
    mk({ titleEn: 'Serum chemistry values in cats', abstractEn: 'Values were summarized.' }),
  ] }];
  const s = EV.gradeAll(groups);
  assert.strictEqual(s.gradeBasisStat.design_identified, 1);
  assert.strictEqual(Object.values(s.gradeBasisStat).reduce((a, b) => a + b, 0), 2);
});

// ---------- 检索式组合与语法校验 ----------
console.log('检索式:');
t('黑名单语法必须告警: 引号短语', () => {
  assert.ok(Q.validateQuery('"companion animal" AND dogs').some(w => w.includes('引号')));
});
t('黑名单语法必须告警: 排除词', () => {
  assert.ok(Q.validateQuery('cats -mice').some(w => w.includes('排除词')));
});
t('合法 AND/OR/括号不告警', () => {
  assert.strictEqual(Q.validateQuery('(dog OR cat) AND (taurine)').length, 0);
});
t('括号不配对必须告警', () => {
  assert.ok(Q.validateQuery('(dog OR cat AND taurine').some(w => w.includes('括号')));
});
t('orClause 截断后返回剩余项数量', () => {
  const r = Q.orClause(['a', 'b', 'c', 'd'], 2);
  assert.strictEqual(r.clause, '(a OR b)');
  assert.strictEqual(r.dropped.length, 2);
});

// ---------- PRISMA 计数 ----------
console.log('PRISMA:');
const ds = () => ({
  runs: [
    { keyword: 'k1', reportedTotal: 100, retrieved: 5, pages: 1, duplicates: 0, aborted: null },
    { keyword: 'k2', reportedTotal: 40, retrieved: 4, pages: 1, aborted: null },
    { keyword: 'k3', reportedTotal: null, retrieved: 0, pages: 0, aborted: 'no_results_unconfirmed' },
  ],
});
t('计数自洽: 命中合计 / 抓取 / 去重后纳入', () => {
  const l = P.buildLog({ runs: ds().runs, dedupe: { total: 9, unique: 8, duplicates: 1 }, evidence: null, meta: {} });
  assert.strictEqual(l.identification.reportedTotalBySite, 140);
  assert.strictEqual(l.identification.recordsRetrieved, 9);
  assert.strictEqual(l.screening.duplicatesRemoved, 1);
  assert.strictEqual(l.included.recordsIncluded, 8);
  assert.strictEqual(l.identification.reportedTotalKnown, false, '有关键词未读得计数时应标记不完全');
});
t('工具恒定不自动排除任何文献', () => {
  const l = P.buildLog({ runs: ds().runs, dedupe: null, evidence: null, meta: {} });
  assert.strictEqual(l.eligibility.excludedByTool, 0);
  assert.strictEqual(l.screening.dedupePerformed, false);
  assert.strictEqual(l.included.recordsIncluded, 9, '未去重时纳入数 = 抓取数');
});
t('异常与无结果关键词必须登记', () => {
  const l = P.buildLog({ runs: ds().runs, dedupe: null, evidence: null, meta: {} });
  assert.deepStrictEqual(l.abnormalKeywords, [{ keyword: 'k3', reason: 'no_results_unconfirmed' }]);
});
t('需人工复核条数计入纳入数而非排除数', () => {
  const ev = { graded: 9, gradeStat: { A: 1, C: 8 }, designStat: {}, speciesStat: {}, flagStat: {}, needsManualExcludeCount: 4, lowConfidenceCount: 9 };
  const l = P.buildLog({ runs: ds().runs, dedupe: { total: 9, unique: 9, duplicates: 0 }, evidence: ev, meta: {} });
  assert.strictEqual(l.included.recordsIncluded, 9);
  assert.strictEqual(l.included.flaggedForReview, 4);
  assert.strictEqual(l.eligibility.excludedByTool, 0);
});
t('Markdown 渲染包含四个流程分段', () => {
  const md = P.renderMarkdown(P.buildLog({ runs: ds().runs, dedupe: null, evidence: null, meta: {} }));
  ['Identification', 'Screening', 'Eligibility', 'Included'].forEach(s => assert.ok(md.includes(s), '缺少分段 ' + s));
});

// ---------- 站点 AI 翻译 · 失败态识别（v4.7） ----------
// 背景（2026-10-16 一手实测）：站点 /api/ai/translate 返回 429 时，面板自渲染「翻译失败 / 重试」；
// 旧实现只等 [class*="wl-ai-surface"] **出现**即返回 true ⇒ 记为「站点译文=是」，
// 与报告头「中文填充率 0%」并存 —— 属**动作级假阳性**。本段锁死修正后的两侧语义：
// ① 面板失败态可辨（诊断）② 记录级真值不依赖站点文案（权威）。
console.log('站点 AI 翻译失败态（v4.7）:');
// ★ 真实样本：2026-10-16 probe-panel 实跑 dump 的面板原文（判据锚点，勿改写；原 dump 为三行）
const PANEL_FAIL_REAL = '✦ AI 翻译 · 中文\n翻译失败\n重试';
const PANEL_OK_REAL = '标题\n猫牛磺酸的营养需求\n摘要节选：\n本研究评估了猫对牛磺酸的需求量…';

t('★ 真实失败面板（站点自渲染）→ all_failed，n/failed 自洽', () => {
  const c = EX.classifyTranslatePanel([PANEL_FAIL_REAL]);
  assert.strictEqual(c.status, 'all_failed');
  assert.strictEqual(c.n, 1);
  assert.strictEqual(c.failed, 1);
});
t('真实成功面板（含「摘要节选」）→ ok（守卫不得把成功判成失败）', () => {
  const c = EX.classifyTranslatePanel([PANEL_OK_REAL]);
  assert.strictEqual(c.status, 'ok');
  assert.strictEqual(c.failed, 0);
});
t('部分失败 → partial_failed（不得因一条失败否定整批）', () => {
  const c = EX.classifyTranslatePanel([PANEL_FAIL_REAL, PANEL_OK_REAL]);
  assert.strictEqual(c.status, 'partial_failed');
  assert.strictEqual(c.n, 2);
  assert.strictEqual(c.failed, 1);
});
t('无面板元素（空数组 / 纯空白 / null）→ no_panel', () => {
  assert.strictEqual(EX.classifyTranslatePanel([]).status, 'no_panel');
  assert.strictEqual(EX.classifyTranslatePanel(['', '   ']).status, 'no_panel');
  assert.strictEqual(EX.classifyTranslatePanel(null).status, 'no_panel');
});
t('站点改写失败文案（仅含「重试」）仍判失败（防文案漂移）', () => {
  assert.strictEqual(EX.classifyTranslatePanel(['AI 翻译\n翻译服务暂不可用，请稍后重试']).status, 'all_failed');
});
t('记录级真值：真实失败样本（titleZh=null / abstractZh 空串）→ false', () => {
  assert.strictEqual(EX.hasSiteTranslation({ titleZh: null, abstractZh: '' }), false,
    '没有任何译文不得算「站点译文=是」');
});
t('记录级真值：有标题 → true；仅摘要 → true；null → false', () => {
  assert.strictEqual(EX.hasSiteTranslation({ titleZh: '猫牛磺酸', abstractZh: null }), true);
  assert.strictEqual(EX.hasSiteTranslation({ titleZh: null, abstractZh: '译文摘要' }), true);
  assert.strictEqual(EX.hasSiteTranslation(null), false);
});
t('★ 源码守卫：站点译文必须取记录级真值，不得回退为动作级布尔', () => {
  const sp = fs.readFileSync(path.join(__dirname, 'search-papers.cjs'), 'utf8');
  assert.ok(/translatedBySite:\s*hasSiteTranslation\(/.test(sp), '未使用记录级判据 hasSiteTranslation');
  assert.ok(/translatedBySite:\s*records\.some\(hasSiteTranslation\)/.test(sp), 'summary 未按整批聚合');
  assert.ok(/translatedBySite:\s*g\.records\.some\(hasSiteTranslation\)/.test(sp), 'runs 未按整批聚合');
  assert.ok(!/translatedBySite:\s*translated\b/.test(sp), '仍存在动作级布尔直传（假阳性回归）');
  assert.ok(!/=>\s*!![a-z]?\.?records\[0\]\.translatedBySite/.test(sp), '聚合仍以 records[0] 单条代表整批');
});
t('PRISMA：翻译失败态在异常列可见（不得静默）', () => {
  const runs = [{ keyword: 'k1', reportedTotal: 10, retrieved: 3, pages: 1, translatedBySite: false, translateStatus: 'all_failed', aborted: null }];
  const md = P.renderMarkdown(P.buildLog({ runs, dedupe: null, evidence: null, meta: {} }));
  assert.ok(md.includes('translate:all_failed'), '异常列未显示翻译失败态');
});

// ---------- 检索后过滤 · 主题相关性排序（v4.7 挂账） ----------
// 背景（2026-10-16 一手实测）：站点检索引擎为**宽匹配**（布尔约束力弱，连 AND 都被稀释）——
// `(犬 OR 猫) AND (毛球 OR 化毛)` 自报 7 条，首条却是「哺乳动物毛球（毛囊球部）生长调控」。
// 本段锁死「本地零站点请求打分」的三条硬约束：
// ① 分档可辨（主题命中 / 相邻主题 / 跑题）② 排除词一票否决但**不丢记录**
// ③ 字段名不可信（站点是中英双语库，titleEn 实际可能装中文）
console.log('主题相关性排序（v4.7 挂账）:');

t('buildTopic：词表为空必须报错（否则「没配词表」被静默当成「全部跑题」）', () => {
  assert.throws(() => REL.buildTopic({ terms: '' }), /主题词表为空/);
  assert.throws(() => REL.buildTopic({}), /主题词表为空/);
});
t('buildTopic：中英文分隔符均可，重复项与「主题∩相邻」重叠须显式记 warnings', () => {
  const tp = REL.buildTopic({ terms: '毛球, 化毛；hairball、bezoar', near: '毛发, 毛球', exclude: '毛囊' });
  assert.deepStrictEqual(tp.terms, ['毛球', '化毛', 'hairball', 'bezoar']);
  assert.deepStrictEqual(tp.near, ['毛发', '毛球']);
  assert.ok(tp.warnings.some(w => w.includes('主题与相邻词表')), '重叠未提示');
  assert.ok(REL.buildTopic({ terms: '毛球,毛球' }).warnings.some(w => w.includes('重复')), '重复项未提示');
});
t('★ 分档：主题词命中题名 → exact；仅摘要命 1 词 → near；摘要命 2 词 → exact', () => {
  const tp = REL.buildTopic({ terms: 'hairball' });
  assert.strictEqual(REL.scoreRecord({ titleZh: 'Cat hairball review' }, tp).level, 'exact');
  assert.strictEqual(REL.scoreRecord({ abstractEn: 'occasional hairball in cats' }, tp).level, 'near');
  const tp2 = REL.buildTopic({ terms: 'hairball,bezoar' });
  assert.strictEqual(REL.scoreRecord({ abstractEn: 'hairball and bezoar in cats' }, tp2).level, 'exact');
});
t('★ 字段名不可信：中文标题装在 titleEn 里仍须按「题名」权重识别（站点实测即如此）', () => {
  const r = REL.scoreRecord({ titleEn: '猫毛球的营养调控', titleZh: null }, REL.buildTopic({ terms: '毛球' }));
  assert.strictEqual(r.level, 'exact');
  assert.strictEqual(r.titleHits.length, 1);
  assert.strictEqual(r.titleHits[0].field, 'title');
  assert.strictEqual(r.score, REL.W.title, '题名权重应为 ' + REL.W.title);
});
t('★ 排除词一票否决降为 off，但记录与命中上下文必须保留（不得静默丢弃）', () => {
  const r = REL.scoreRecord({ titleEn: '哺乳动物毛球（毛囊球部）生长调控' }, REL.buildTopic({ terms: '毛球', exclude: '毛囊,球部' }));
  assert.strictEqual(r.level, 'off', '含排除词不得判为主题命中');
  assert.strictEqual(r.excluded, true);
  assert.strictEqual(r.excludeHits.length, 2, '排除命中须逐条留痕');
  assert.ok(r.titleHits.length >= 1, '主题词命中仍须保留供人工判断');
});
t('★ 返回结构完整：五个命中数组齐备（渲染层直接依赖，缺失即 TypeError）+ stationRequests=0', () => {
  const r = REL.scoreRecord({ titleEn: 'a b c' }, REL.buildTopic({ terms: 'a', near: 'b', exclude: 'c' }));
  for (const k of ['hits', 'titleHits', 'abstractHits', 'nearHits', 'excludeHits']) {
    assert.ok(Array.isArray(r[k]), k + ' 必须为数组');
  }
  assert.strictEqual(r.stationRequests, 0);
  assert.ok(r.titleHits.every(h => h.kind === 'exact'), 'titleHits 只应含主题词命中（相邻词另列）');
  assert.ok(r.nearHits.every(h => h.kind === 'near'), 'nearHits 只应含相邻词命中');
});
t('countOccurrences：非重叠计数；空 term 返回 0（否则 indexOf("") 死循环）', () => {
  assert.strictEqual(REL.countOccurrences('aaaa', 'aa'), 2);
  assert.strictEqual(REL.countOccurrences('abc', ''), 0);
  assert.strictEqual(REL.countOccurrences(null, 'a'), 0);
});
t('★ rankAll：分层稳定序（level→score→year→idx）+ rank 连续 + stat 自洽 + 同输入两次深等', () => {
  const tp = REL.buildTopic({ terms: 'hairball' });
  const groups = [{ keyword: 'k', records: [
    { idx: 1, titleZh: '跑题一条', year: 2020 },
    { idx: 2, titleZh: 'hairball in dogs', year: 2019 },
    { idx: 3, abstractEn: 'hairball signs', year: 2021 },
    { idx: 4, titleZh: 'hairball again', year: 2018 },
  ] }];
  const a = REL.rankAll(groups, tp);
  const b = REL.rankAll(groups, tp);
  assert.deepStrictEqual(a.ranked.map(r => r.rec.idx), b.ranked.map(r => r.rec.idx), '同输入两次排序不一致');
  assert.deepStrictEqual(a.ranked.map(r => r.rec.idx), [2, 4, 3, 1], 'exact(年份降序) → near → 跑题');
  assert.deepStrictEqual(a.ranked.map(r => r.rank), [1, 2, 3, 4]);
  assert.deepStrictEqual(a.stat, { exact: 2, near: 1, off: 1 });
  assert.strictEqual(a.total, 4);
  assert.strictEqual(a.exactRate, 50);
  assert.strictEqual(a.stationRequests, 0);
});
t('rankAll：空输入不崩（total=0 / exactRate=0 / ranked=[]）', () => {
  const r = REL.rankAll([], REL.buildTopic({ terms: 'x' }));
  assert.strictEqual(r.total, 0);
  assert.strictEqual(r.exactRate, 0);
  assert.deepStrictEqual(r.ranked, []);
});
t('scoreRecord：缺字段 / null 记录不崩（按空串处理，不臆造命中）', () => {
  const tp = REL.buildTopic({ terms: 'x' });
  assert.strictEqual(REL.scoreRecord({}, tp).level, 'off');
  assert.strictEqual(REL.scoreRecord(null, tp).score, 0);
});
t('★ 源码守卫：本步骤必须零站点请求（显式声明 + 源码内不得出现任何网络调用）', () => {
  const src = fs.readFileSync(path.join(__dirname, 'lib', 'relevance.cjs'), 'utf8')
    + fs.readFileSync(path.join(__dirname, 'rank-records.cjs'), 'utf8');
  assert.ok(/stationRequests:\s*0/.test(src), '未声明 stationRequests=0');
  for (const bad of [/\bfetch\s*\(/, /require\(\s*['"]https?['"]/, /\baxios\b/, /\bplaywright\b/]) {
    assert.ok(!bad.test(src), '排序步骤出现网络调用（违反零站点请求）：' + bad);
  }
  const cli = fs.readFileSync(path.join(__dirname, 'rank-records.cjs'), 'utf8');
  assert.ok(/require\(['"]\.\/assemble-report\.cjs['"]\)/.test(cli) && /readRawGroups/.test(cli),
    '未复用 readRawGroups —— 自建读法会与 assemble-report 漂移');
});
t('★ 渲染守卫：相邻词命中须标「相邻」，不得标成「主题」（正文与表格口径一致）', () => {
  const res = REL.rankAll([{ keyword: 'k', records: [{ idx: 1, abstractEn: 'dog skin and hairball', year: 2020 }] }],
    REL.buildTopic({ terms: 'hairball', near: 'skin' }));
  const md = RK.renderMarkdown(res, { top: 5 });
  assert.ok(md.includes('[相邻]「skin」'), '相邻命中未标为「相邻」');
  assert.ok(!/\[主题\]「skin」/.test(md), '相邻词被误标为主题的回归');
  assert.ok(md.includes('站点请求: **0**'), '未在报告中显式声明零站点请求');
});
t('renderCsv：含逗号/引号的字段必须转义（否则列错位）+ 表头 14 列', () => {
  const res = REL.rankAll([{ keyword: 'k', records: [
    { idx: 1, titleZh: 'hairball, "quoted"', authors: 'A, B', year: 2020 },
  ] }], REL.buildTopic({ terms: 'hairball' }));
  const csv = RK.renderCsv(res, { top: 5 });
  assert.ok(csv.includes('"hairball, ""quoted"""'), '标题未按 CSV 规则转义: ' + csv);
  assert.ok(csv.includes('"A, B"'), '作者字段未转义');
  assert.strictEqual(csv.split('\r\n')[0].split(',').length, 14, '表头列数应为 14');
});
t('CLI 解析：非法 --format/--top 与未知参数均须报错（不得静默继续）', () => {
  const throwsCli = (a, needle) => {
    try { RK.parseArgs(['node', 's', ...a]); }
    catch (e) { return assert.ok(String(e.message).includes(needle), '信息应含 ' + needle + '，实际 ' + e.message); }
    throw new Error('应当抛错但未抛: ' + JSON.stringify(a));
  };
  throwsCli(['--format', 'xml'], '--format');
  throwsCli(['--top', '0'], '--top');
  throwsCli(['--top', 'abc'], '--top');
  throwsCli(['--nope'], '未知参数');
  assert.strictEqual(RK.parseArgs(['node', 's', '--dir', './run', '--topic', 'a']).top, 10, '默认 top 应为 10');
});

// ---------- v4.7 挂账·词形边界自动归一（2026-10-16 实测三类漏判） ----------
// 背景（一手实证）：`gut–kidney` 因 en-dash 与词表空格不同形而漏判；`腎臟` 因繁体未归一
// 致「猫 CKD 干预研究」整条被判跑题；`hair ball` 因连写/分写差异漏判。
// 三条都属「同义异形」，必须由代码自动等价，不能指望人肉把每种形态都写进词表。
console.log('词形边界自动归一（v4.7 挂账）:');

t('★ 归一·破折号族：`gut–kidney`(en-dash) 须命中词表 `gut kidney`（实测漏判 1）', () => {
  const tp = REL.buildTopic({ terms: 'gut kidney axis' });
  assert.strictEqual(REL.scoreRecord({ titleEn: 'The Gut–Kidney Axis in Feline CKD', year: 2026 }, tp).level, 'exact',
    'en-dash 未与空格等价');
  for (const d of ['—', '-', '−', '‐', '‒', '－']) {
    assert.strictEqual(REL.scoreRecord({ titleEn: 'gut' + d + 'kidney axis' }, tp).level, 'exact', 'dash=' + JSON.stringify(d));
  }
  assert.strictEqual(REL.scoreRecord({ titleEn: 'gut kidney axis' }, REL.buildTopic({ terms: 'gut-kidney-axis' })).level, 'exact',
    '词表写连字符 ↔ 文本写空格 未等价');
});

t('★ 归一·繁简：`腎臟` 须命中词表 `肾脏`（实测漏判 2 —— 猫 CKD 干预研究整条被判跑题）', () => {
  const r = REL.scoreRecord({ titleZh: '腎臟保健複合乳酸桿菌應用於慢性腎臟病貓之功效性' },
    REL.buildTopic({ terms: '肾脏保健,乳酸杆菌,肾脏病' }));
  assert.strictEqual(r.level, 'exact', '繁体未被归一');
  assert.strictEqual(r.titleHits.length, 3, '三个繁体主题词（词表写简体）都应命中，实际 ' + r.titleHits.length);
  assert.strictEqual(REL.toSimplified('腎臟腸纖維營飼糧貓'), '肾脏肠纤维营饲粮猫');
});

t('★ 归一·连写/分写：`hair ball` 与 `hairball` 必须互为等价（双向）', () => {
  assert.strictEqual(REL.scoreRecord({ titleEn: 'hair ball in cats' }, REL.buildTopic({ terms: 'hairball' })).level, 'exact');
  assert.strictEqual(REL.scoreRecord({ titleEn: 'hairball in cats' }, REL.buildTopic({ terms: 'hair ball' })).level, 'exact');
  assert.strictEqual(REL.scoreRecord({ titleEn: 'uric acid stones in dogs' }, REL.buildTopic({ terms: 'uricacid' })).level, 'exact');
});

t('★ 归一不制造假阳性：形态无关的不相关记录仍 off；排除词亦走归一（连写可被多词排除词拦下）', () => {
  assert.strictEqual(REL.scoreRecord({ titleZh: '犬髋关节发育不良的外科治疗' }, REL.buildTopic({ terms: 'hairball' })).level, 'off');
  const ex = REL.scoreRecord({ titleEn: 'Feline trichobezoar and hairball management' },
    REL.buildTopic({ terms: 'trichobezoar', exclude: 'hair ball' }));
  assert.strictEqual(ex.level, 'off', '排除词未随归一化生效');
  assert.strictEqual(ex.excluded, true);
  const ex2 = REL.scoreRecord({ titleEn: '哺乳動物毛球（毛囊球部）生長調控' }, REL.buildTopic({ terms: '毛球', exclude: '毛囊,球部' }));
  assert.strictEqual(ex2.level, 'off');
  assert.strictEqual(ex2.excludeHits.length, 2, '排除命中须逐条留痕');
});

t('★ 归一命中必须可人工复核：snippet 锚定命中处（保留原文 dash / 大写 / 繁体）+ n 为非重叠计数', () => {
  // 命中位置**远离文本开头** —— 否则「索引映射失效（map 全 0）」的切片恰好仍含 dash，
  // 判据会退化为装饰（实测：2026-10-16 首版夹具即因此漏掉 map-index 变异）。
  const long = 'Feline nutrition review covering many unrelated topics plus the Gut–Kidney Axis in cats';
  const r = REL.scoreRecord({ titleEn: long }, REL.buildTopic({ terms: 'gut kidney axis' }));
  assert.strictEqual(r.level, 'exact');
  const h = r.titleHits.find(x => x.field === 'title');
  assert.ok(h, '未产生题名命中');
  assert.ok(/–/.test(h.snippet), 'snippet 须保留原文 en-dash：' + h.snippet);
  assert.ok(/gut/i.test(h.snippet) && /kidney/i.test(h.snippet), 'snippet 未锚定命中片段：' + h.snippet);
  assert.ok(!/^Feline nutrition/.test(h.snippet), 'snippet 退化为「取文本开头」⇒ 索引映射失效：' + h.snippet);

  const two = REL.scoreRecord({ titleEn: 'The Gut–Kidney Axis and gut-kidney crosstalk' }, REL.buildTopic({ terms: 'gut kidney' }));
  const h2 = two.titleHits.find(x => x.field === 'title');
  assert.strictEqual(h2.n, 2, '应命中 2 处（en-dash 与 hyphen 各一），实际 ' + h2.n);
});

t('★ 归一化边界：dash/空白被完全剥离 ⇒ 纯符号 term 压缩为空必须跳过（不得 indexOf("") 死循环）', () => {
  assert.strictEqual(REL.compactKey('  –  '), '');
  assert.strictEqual(REL.compactKey('Gut–Kidney Axis'), 'gutkidneyaxis');
  const r = REL.scoreRecord({ titleEn: 'plain text' }, REL.buildTopic({ terms: 'hairball,-,  ' }));
  assert.strictEqual(r.level, 'off');
  assert.strictEqual(r.score, 0);
});

t('★ 繁简表值域守卫：单字 1:1 映射（保证索引映射不漂移）+ 关键高频字齐备 + 不得反向污染', () => {
  const M = REL.SIMPLIFY_MAP;
  for (const [k, v] of Object.entries(M)) {
    assert.strictEqual(k.length, 1, '键必须单字: ' + k);
    assert.strictEqual(v.length, 1, '值必须单字: ' + k + '→' + v);
    assert.notStrictEqual(k, v, '恒等映射应省略: ' + k);
  }
  for (const ch of '腎臟腸纖維營養飼糧貓體檢驗劑質學應標療藥實結論數據機關係組鏈軸導礦鈣鉀鈉鎂鋅鐵銅過濾濃縮壓張細長飽異監護狀態調節響顯統計報獻證陽陰歲齡評價斷緩穩準規範簡複桿於動') {
    assert.ok(M[ch], '高频繁体字缺失: ' + ch);
  }
  assert.strictEqual(REL.toSimplified('簡體字'), '简体字', '反向污染（简→繁）');
});

t('★ 归一化不改变原有分档语义：题名权重 ×3 / 空词表抛错 / 缺字段不崩 均不受影响', () => {
  const tp = REL.buildTopic({ terms: 'hairball' });
  const r = REL.scoreRecord({ titleZh: 'Cat hairball review' }, tp);
  assert.strictEqual(r.score, REL.W.title);
  assert.strictEqual(r.level, 'exact');
  assert.throws(() => REL.buildTopic({ terms: '  ' }), /主题词表为空/);
  assert.strictEqual(REL.scoreRecord({}, tp).level, 'off');
});

// ---------- v4.7 挂账·覆盖诊断：缺词候选（2026-10-16） ----------
// 背景（一手实证）：上一轮把「词形边界」落地后量化发现 —— **真正的瓶颈是覆盖而非形态**。
//   繁体猫 CKD 论文虽由 off 升到 near，题名仍 0 命中，因为词表里根本没有
//   「肾脏保健 / 乳酸杆菌」这类中文主题词。本模块把「缺词」也变成机检信号：
//   扫主题档题名，提取**高频但不在词表**的领域词，人只需挑词、无需通读全量。
// 关键设计（无第三方依赖 ⇒ 中文无分词器，只能走 n-gram）：
//   ① 虚词切分：在「的/与/之/於…」处断开 CJK 串，n-gram 只在段内生成
//      ⇒ `慢性肾脏病的营养管理` 切成 `慢性肾脏病` + `营养管理`，不产生 `肾脏病的`；
//   ② 极大剪枝：候选 A ⊂ 候选 B 且 df(B) ≥ df(A) ⇒ 丢 A（`营养管` 让位于 `营养管理`）；
//   ③ 已覆盖判定**复用 v2 归一**（compactKey）⇒ 词表写简体、语料写繁体不算「缺词」；
//   ④ 半重叠（与词表词交叉但互不包含）**不压制、只降权并留痕** —— 纯 n-gram 分不出
//      「菌群失调(真缺词)」与「脏保健复(分词错位)」，故**边界判断交给人**，信息零丢失。
console.log('覆盖诊断 · 缺词候选（v4.7 挂账）:');

let SG = null;
try { SG = require('./lib/suggest.cjs'); } catch (e) { SG = null; }

function mkRows(txts, level) {
  return txts.map((t, i) => ({ idx: i + 1, keyword: 'k', rec: { titleZh: t }, rel: { level: level || 'exact' } }));
}
const tK = (terms, near, exclude) => REL.buildTopic({ terms, near, exclude });
const SG_TXT = (() => { try { return fs.readFileSync(path.join(__dirname, 'lib', 'suggest.cjs'), 'utf8'); } catch (e) { return ''; } })();

t('★ 覆盖诊断：模块可加载 + 声明零站点请求（先红 → 实现后转绿）', () => {
  assert.ok(SG, 'lib/suggest.cjs 未实现（缺词候选能力缺失）');
  assert.strictEqual(typeof SG.buildSuggestions, 'function');
  assert.ok(/^suggest-terms\//.test(SG.VERSION || ''), 'VERSION 命名空间应为 suggest-terms/*');
});

t('★ 只报「词表未覆盖」者：候选 ⊂ 词表词 ⇒ 丢弃；词表不含的领域词必须提示', () => {
  const r = SG.buildSuggestions(mkRows([
    '慢性肾脏病的营养管理与膳食纤维干预',
    '慢性肾脏病猫的营养管理研究',
  ]), tK('膳食纤维,慢性肾脏病'), { minDf: 2 });
  const keys = r.candidates.map(c => c.key);
  assert.ok(!keys.includes('膳食纤维'), '词表已有 ⇒ 不得提示');
  assert.ok(!keys.includes('慢性肾脏'), '词表词 `慢性肾脏病` 的子串 ⇒ 不得提示');
  assert.ok(!keys.includes('肾脏病'), '同上');
  assert.ok(keys.includes('营养管理'), '缺词 `营养管理` 未提示，实际 ' + keys.join('/'));
});

t('★ 虚词切分 + 极大剪枝：候选不得跨虚词生成（不出现 `肾脏病的`），短子串让位于长串', () => {
  const r = SG.buildSuggestions(mkRows([
    '慢性肾脏病的营养管理与膳食纤维干预',
    '慢性肾脏病猫的营养管理研究',
  ]), tK('膳食纤维,慢性肾脏病'), { minDf: 2 });
  const keys = r.candidates.map(c => c.key);
  assert.ok(!keys.some(k => /[的了与和及或在中是为由从以并而则者也都更该这那此]/.test(k)),
    '候选不应含虚词（虚词须作切分点，而非入 n-gram）：' + keys.join('/'));
  assert.ok(!keys.includes('营养管'), '`营养管` 是 `营养管理` 的子串且 df 相同 ⇒ 应被极大剪枝');
  assert.ok(!keys.includes('营养'), '同上（更短）');
});

t('★ 已覆盖判定必须复用 v2 归一：词表写简体、语料写繁体 ⇒ **不得**误报为缺词', () => {
  // 两条都含繁体虚词 `於` —— 若提取层不归一，`於` 会失去切分点并产出 `應用於慢` 这类
  // **跨虚词假词**（df=2 ⇒ 会真的进入产物）。故本夹具既是「覆盖判定」用例，
  // 也是「归一必须在提取层生效」用例（不能再靠 compactKey 兜底蒙过去）。
  const r = SG.buildSuggestions(mkRows([
    '腎臟保健複合乳酸桿菌應用於慢性腎臟病貓之功效性',
    '腎臟保健複合乳酸桿菌應用於慢性腎衰竭犬之評估',
  ]), tK('肾脏保健,乳酸杆菌'), { minDf: 2 });
  const keys = r.candidates.map(c => c.key);
  assert.ok(!keys.includes('肾脏保健'), '词表已含该词（繁体形态）⇒ 不得提示：' + keys.join('/'));
  assert.ok(!keys.includes('乳酸杆菌'), '同上');
  assert.ok(!r.candidates.some(c => /[的了与和及或在中是为对由从以并而则者也都更该这那此各每些把被之于]/
    .test(REL.toSimplified(c.term))), '候选含虚词（繁体虚词同样须作切分点）：'
    + r.candidates.map(c => c.term).join('/'));
});

t('★ 高价值候选：**词表词的超串**（词表 `肾脏` ⇒ 候选 `肾脏保健`）必须保留并标 extendsTopic', () => {
  const r = SG.buildSuggestions(mkRows([
    '犬慢性肾衰竭的营养干预与肾脏保健研究',
    '猫肾脏保健功能性零食的开发与评价',
  ]), tK('肾脏'), { minDf: 2 });
  const hit = r.candidates.find(c => c.key === '肾脏保健');
  assert.ok(hit, '词表词的超串应作为缺词候选：' + r.candidates.map(c => c.key).join('/'));
  assert.strictEqual(hit.extendsTopic, true, '应标注 extendsTopic（词表词 + 修饰）');
  assert.strictEqual(hit.df, 2);
  // df 语义 = **出现在多少条记录里**；同一条记录内重复出现（这里首条出现 2 次）不得虚增
  const dup = SG.buildSuggestions(mkRows([
    '犬肾脏保健与肾脏保健功能研究',
    '猫肾脏保健评价',
  ]), tK('无关词'), { minDf: 1 });
  const d = dup.candidates.find(c => c.key === '肾脏保健');
  assert.ok(d, '重复词候选缺失');
  assert.strictEqual(d.df, 2, '同一记录内重复出现不得虚增 df（应为 2 条记录），实际 ' + d.df);
});

t('★ 半重叠不压制：与词表词交叉的候选**保留 + 标 overlapsTopic + 排序降权**（信息零丢失）', () => {
  const r = SG.buildSuggestions(mkRows([
    '犬慢性肾衰竭肠道菌群失调的研究进展',
    '猫慢性肾脏病肠道菌群失调与肾功能',
  ]), tK('肠道菌群'), { minDf: 2 });
  const cross = r.candidates.find(c => c.key === '菌群失调');
  assert.ok(cross, '交叉候选不得被静默丢弃：' + r.candidates.map(c => c.key).join('/'));
  assert.strictEqual(cross.overlapsTopic, true);
  const clean = r.candidates.filter(c => !c.overlapsTopic && !c.extendsTopic);
  if (clean.length) {
    assert.ok(r.candidates.indexOf(cross) > r.candidates.indexOf(clean[0]), '交叉候选应排在无重叠候选之后');
  }
});

t('★ 通用词与低频词必须过滤，且**过滤数量留痕**（不静默丢弃）', () => {
  const r = SG.buildSuggestions(mkRows([
    '犬肠道菌群失调的研究进展分析',
    '猫肠道菌群失调的研究进展探讨',
  ]), tK('无关词'), { minDf: 2 });
  const keys = r.candidates.map(c => c.key);
  assert.ok(!keys.includes('研究'), '通用词 `研究` 应被停用词表拦下：' + keys.join('/'));
  // 实测（2026-10-16 gutkidney 真实数据）`研究进展` 曾以 df=3 挤进候选第 3 位
  assert.ok(!keys.includes('研究进展'), '全由通用词拼成的串应被拦下：' + keys.join('/'));
  assert.ok(r.dropped.stopword > 0, '停用词丢弃数须留痕');
  assert.ok(r.dropped.total > 0, '原始 n-gram 总数须留痕');
  const r2 = SG.buildSuggestions(mkRows(['犬肠道菌群失调与肾功能的独家观察']), tK('无关词'), { minDf: 2 });
  assert.ok(r2.candidates.every(c => c.df >= 2), '低于 minDf 的候选不得出现');
  assert.ok(r2.dropped.lowDf > 0, '低频丢弃数须留痕');
});

t('★ 英文侧：多词术语须以 bigram 形态候选（`indoxyl sulfate`），停用词与短 token 不得入选', () => {
  const r = SG.buildSuggestions(mkRows([
    'Serum indoxyl sulfate and p-cresyl sulfate in dogs with CKD',
    'Indoxyl sulfate as a uremic toxin in feline chronic kidney disease',
  ]), tK('uremic toxin'), { minDf: 2 });
  const keys = r.candidates.map(c => c.key);
  assert.ok(keys.includes('indoxylsulfate'), 'bigram 候选缺失：' + keys.join('/'));
  assert.ok(!keys.some(k => k === 'and' || k === 'the' || k === 'with'), '英文停用词不得入选：' + keys.join('/'));
  // 实测（gutkidney 真实数据）`DOGS CATS` 曾以 df=2 挤进候选：bigram 各部件皆物种词 ⇒ 须拦下。
  // ★ 夹具必须用「逗号分隔」（token 相邻）—— 写成 `dogs and cats` 时中间隔着停用词 `and`，
  //   **根本产不出 `dogscats`**，否定断言会退化为装饰（变异永不转红）。故先加**正向对照**：
  //   证明夹具确实会产出该 bigram，再断言它被拦下。
  const sp = SG.buildSuggestions(mkRows([
    'Gut microbiome of dogs, cats with CKD',
    'Gut microbiome in dogs, cats with renal disease',
  ]), tK('无关词'), { minDf: 2 });
  const rawC = SG.extractCandidates('Gut microbiome of dogs, cats with CKD', 4).map(c => c.key);
  assert.ok(rawC.includes('dogscats'), '夹具未产出 bigram ⇒ 下面的否定断言无效：' + rawC.join('/'));
  const sk = sp.candidates.map(c => c.key);
  assert.ok(!sk.includes('dogscats'), '由两个物种词拼成的 bigram 应被拦下：' + sk.join('/'));
});

t('★ 半重叠判定须覆盖相邻词：分词错位候选（`性肾衰竭` = `肾衰竭` 错位）须标 overlapsTopic 并降权', () => {
  // 真实数据（gutkidney 40 条）实测：词表把 `肾衰竭` 放在**相邻词**而非主题词。
  //   若判定域只有主题词，`性肾衰竭` 这类错位候选会冒充「缺词」被推荐给用户。
  //   ⇒ 判定域必须 = 主题词 + 相邻词；本断言为该设计提供真实覆盖（去掉 nearKeys 即转红）。
  //   注：更短的 `性肾衰` 会被 4-gram `性肾衰竭` 极大剪枝掉（df 相同且包含），故以 4-gram 为断言对象。
  const r = SG.buildSuggestions(mkRows([
    '犬慢性肾衰竭的营养干预',
    '猫慢性肾衰竭的膳食管理',
  ]), tK('膳食纤维', '肾衰竭'), { minDf: 2 });
  const keys = r.candidates.map(c => c.key);
  const mis = r.candidates.find(c => c.key === '性肾衰竭');
  assert.ok(mis, '错位候选 `性肾衰竭` 应在候选中（下游才能给它降权）：' + keys.join('/'));
  assert.strictEqual(mis.overlapsTopic, true, '`性肾衰竭` 与**相邻词** `肾衰竭` 交叉 ⇒ 须标 overlapsTopic');
  // 鉴别对照：相邻词为空时同一候选**不得**被判半重叠 ⇒ 证明判据真的在读相邻词（否则变异不红）
  const r3 = SG.buildSuggestions(mkRows([
    '犬慢性肾衰竭的营养干预',
    '猫慢性肾衰竭的膳食管理',
  ]), tK('膳食纤维'), { minDf: 2 });
  const mis3 = r3.candidates.find(c => c.key === '性肾衰竭');
  assert.ok(mis3, '相邻词为空时 `性肾衰竭` 仍应作为**缺词**候选出现');
  assert.strictEqual(mis3.overlapsTopic, false, '相邻词为空 ⇒ 不得判半重叠（判据须真读相邻词）');
});

t('★ 泛词的**边界残渣**不得成为候选（`究进`/`物犬`/`研究进` 全由通用词用字拼成 ⇒ 丢）', () => {
  // 实测（gutkidney 40 条）：只拦「等值」和「全拼接」两种形态时，通用词窗口的**错位切分残渣**
  //   （`研究进`/`究进展` 各 df=9；`究进` 是 研究|进展 的**接缝**，df=9）会挤进候选前三位。
  //   ⇒ 逐词加黑名单是按下去又弹起来（补 `宠物犬` 到物种词表后，其尾巴 `物犬` 又冒出来）。
  //   改用**结构性判据**：候选的每个字都出现在某通用词/物种词里 ⇒ 它是通用词窗口拼出的残渣。
  //   三条判据逐级更一般：等值（`研究`）→ isStop；通用词窗口残渣（含**全拼接** `研究进展` 为其特例）
  //   → isStopResidue。原先单独的 `isStopComposed` 因被严格覆盖已删（变异自证抓出它对行为零贡献）。
  assert.strictEqual(SG.isStopResidue('究进'), true, '接缝残渣（研究|进展）');
  assert.strictEqual(SG.isStopResidue('物犬'), true, '物种词尾巴（宠物犬）');
  assert.strictEqual(SG.isStopResidue('研究进'), true);
  assert.strictEqual(SG.isStopResidue('究进展'), true);
  assert.strictEqual(SG.isStopResidue('用研究进'), true, '更远的错位同样由结构判据覆盖（非逐词黑名单）');
  // 反向：含**领域字**的真词一律不得误砍（宁可留噪音，不可砍真词）
  for (const w of ['营养管理', '免疫功能', '肾衰竭', '猫尿石症', '代谢', '调控', '犬肠道菌', '消化']) {
    assert.strictEqual(SG.isStopResidue(w), false, '真词被误砍：' + w);
  }
  const r = SG.buildSuggestions(mkRows([
    '犬肠道菌群失调的研究进展分析',
    '猫肠道菌群失调的研究进展探讨',
  ]), tK('无关词'), { minDf: 2 });
  const keys = r.candidates.map(c => c.key);
  assert.ok(!keys.includes('研究进') && !keys.includes('究进展') && !keys.includes('究进'),
    '通用词边界残渣不得入选：' + keys.join('/'));
  // ★ 父子遮蔽检查：极大剪枝会把「片段」吸收进「父串」⇒ 若父串也在池中，残渣判据即使失效，
  //   片段照样被吸收，断言**照绿**（变异不红 ⇒ 无真实覆盖）。故另用一个**父串进不了池**的夹具
  //   （`含量测定` 只出现 1 次 < minDf，而接缝片段 `含量测` 出现 2 次）：
  const r2 = SG.buildSuggestions(mkRows(['犬含量测定方法', '猫含量测']), tK('无关词'), { minDf: 2 });
  const k2 = r2.candidates.map(c => c.key);
  assert.ok(!k2.includes('含量测'), '通用词接缝残渣（含量｜测定）不得入选：' + k2.join('/'));
});

t('★ 排序确定性 + df 降序：同输入两次深等（无非确定性来源，便于 diff 比对）', () => {
  const rows = mkRows([
    '犬肠道菌群失调与吲哚硫酸盐的关系',
    '猫肠道菌群失调与尿毒症毒素研究',
    '犬吲哚硫酸盐的检测方法',
  ]);
  const tp = tK('无关节食');
  const a = SG.buildSuggestions(rows, tp, { minDf: 2 });
  const b = SG.buildSuggestions(rows, tp, { minDf: 2 });
  assert.deepStrictEqual(a, b, '同输入两次结果必须深等');
  for (let i = 1; i < a.candidates.length; i++) {
    const p = a.candidates[i - 1], q = a.candidates[i];
    assert.ok(p.df >= q.df, 'df 必须降序：' + p.key + '(' + p.df + ') → ' + q.key + '(' + q.df + ')');
  }
});

t('★ 语料范围：**单调包含**（near = 主题档 + 相邻档）；空输入与非主题档不得进语料、不得崩', () => {
  const mixed = mkRows(['犬肠道菌群失调研究'], 'off')
    .concat(mkRows(['猫肠道菌群失调研究'], 'near'))
    .concat(mkRows(['犬慢性肾病与乳酸杆菌干预'], 'exact'));
  const ex = SG.buildSuggestions(mixed, tK('无关'), { minDf: 1, scope: 'exact' });
  assert.strictEqual(ex.corpus, 1, '默认范围应只含 exact 档，实际 ' + ex.corpus);
  assert.strictEqual(ex.scope, 'exact');
  // ★ 单调包含语义：`near` = 主题档 + 相邻档（不是「只要 near 档」）。
  //   理由（一手实证）：最需要补词的场景是**主题档为空**，而缺词证据恰恰留在相邻档
  //   （繁体猫 CKD 论文就落在 near 档）⇒ 若 near 只取 near 档，功能在该场景下会返回空。
  const nr = SG.buildSuggestions(mixed, tK('无关'), { minDf: 1, scope: 'near' });
  assert.strictEqual(nr.corpus, 2, 'scope=near 应含「主题 + 相邻」两档（单调包含），实际 ' + nr.corpus);
  const all = SG.buildSuggestions(mixed, tK('无关'), { minDf: 1, scope: 'all' });
  assert.strictEqual(all.corpus, 3, 'scope=all 应含全部档');
  const empty = SG.buildSuggestions([], tK('无关'));
  assert.deepStrictEqual(empty.candidates, []);
  assert.strictEqual(empty.corpus, 0);
});

t('★ 渲染集成：ranked.md 末节给出可粘贴的补词串；CLI 默认开启且可 --no-suggest 关闭', () => {
  const res = REL.rankAll([{ keyword: 'k', records: [
    { idx: 1, titleZh: '犬慢性肾衰竭的营养干预与肾脏保健' },
    { idx: 2, titleZh: '猫慢性肾衰竭的肾脏保健研究' },
  ] }], tK('肾衰竭'));
  const sg = SG.buildSuggestions(res.ranked, res.topic, { minDf: 2 });
  const md = RK.renderMarkdown(res, { top: 5, suggest: sg });
  assert.ok(/建议补词|覆盖诊断/.test(md), 'md 未输出覆盖诊断小节');
  assert.ok(md.includes('肾脏保健'), 'md 未列出候选词');

  const a = RK.parseArgs(['node', 's', '--dir', './run', '--topic', 'x']);
  assert.strictEqual(a.suggest, true, '覆盖诊断应默认开启');
  assert.strictEqual(a.suggestTop, 20, '默认 --suggest-top 应为 20');
  assert.strictEqual(a.suggestScope, 'near', '默认范围应含相邻档（主题档为空时仍能给出候选）');
  assert.strictEqual(a.minDf, 2, '默认 minDf 应为 2');
  assert.strictEqual(RK.parseArgs(['node', 's', '--no-suggest']).suggest, false, '--no-suggest 应可关闭');
  const bad = (arr, needle) => {
    try { RK.parseArgs(['node', 's', ...arr]); }
    catch (e) { return assert.ok(String(e.message).includes(needle), '错误信息应含 ' + needle + '，实际 ' + e.message); }
    throw new Error('应当抛错但未抛: ' + JSON.stringify(arr));
  };
  bad(['--suggest-scope', 'foo'], '--suggest-scope');
  bad(['--suggest-top', '0'], '--suggest-top');
  bad(['--min-df', 'x'], '--min-df');
});

t('★ 源码守卫：suggest.cjs 必为纯函数（零网络、零文件系统）—— 与 rank-records 同源', () => {
  assert.ok(SG_TXT, '未能读取 suggest.cjs 源码');
  for (const bad of ['fetch(', 'require(\'https\')', 'require("https")', 'require(\'node:https\')',
    'require(\'http\')', 'require("http")', 'require(\'node:http\')', 'XMLHttpRequest', 'require(\'fs\')', 'require("fs")']) {
    assert.ok(!SG_TXT.includes(bad), 'suggest.cjs 不得含 ' + bad + '（纯函数模块）');
  }
  assert.ok(SG_TXT.includes('stationRequests: 0'), 'suggest.cjs 须显式声明 stationRequests: 0');
});

// ---------- v4.7 挂账·补词闭环：mergeTerms + diffRanks + --apply（2026-10-16） ----------
// 动因：上轮把「缺词」变成可勾选清单，但「补进去到底有没有用」仍要手工再跑一次。
//   本区块为「补词 → 重排 → 对比」闭环提供**离线可测**的判据。
// ★ 纪律：补词**必须显式传入**（--apply），模块与 CLI 都不得自动改词表。
console.log('补词闭环 · 词表合并与重排对比（v4.7 挂账）:');

const rankOne = (recs, spec) => REL.rankAll([{ keyword: 'k', records: recs }], REL.buildTopic(spec));

t('★ 补词闭环：mergeTerms / diffRanks 存在且为纯函数（零站点请求）', () => {
  assert.strictEqual(typeof REL.mergeTerms, 'function', '缺 mergeTerms');
  assert.strictEqual(typeof REL.diffRanks, 'function', '缺 diffRanks');
  const src = fs.readFileSync(path.join(__dirname, 'lib', 'relevance.cjs'), 'utf8');
  for (const bad of ["require('https')", 'require("https")', "require('node:https')",
    "require('http')", 'XMLHttpRequest']) {
    assert.ok(!src.includes(bad), 'relevance.cjs 不得含 ' + bad + '（纯函数模块）');
  }
});

t('mergeTerms：原词**保序在前**、新增按传入序在后（词表 v2 可与原值逐项比对）', () => {
  const r = REL.mergeTerms('肾脏保健,乳酸杆菌', '猫尿石症,肠道保健');
  assert.deepStrictEqual(r.terms, ['肾脏保健', '乳酸杆菌', '猫尿石症', '肠道保健']);
  assert.deepStrictEqual(r.appended, ['猫尿石症', '肠道保健']);
});

t('mergeTerms：等值去重 —— 含**简繁等价**（词表 `肾脏` 与新增 `腎臟` 是同一词，不得重复追加）', () => {
  const r = REL.mergeTerms('肾脏,肠道菌群', '腎臟,毛球');
  assert.deepStrictEqual(r.appended, ['毛球'], '简繁同词不得重复追加：' + JSON.stringify(r.appended));
  assert.strictEqual(r.terms.length, 3, '实际 ' + r.terms.length);
});

t('mergeTerms：空新增 ⇒ appended 为空；不得**就地改写**入参（词表是不可变输入）', () => {
  const base = ['肾脏', '毛球'];
  const r = REL.mergeTerms(base, '');
  assert.deepStrictEqual(r.appended, []);
  assert.deepStrictEqual(r.terms, ['肾脏', '毛球']);
  assert.deepStrictEqual(base, ['肾脏', '毛球'], '入参数组被就地改写（应返回新数组）');
});

t('mergeTerms：**保原文形态**（大小写等写法不得被改写）—— 否则词表 v2 无法直接替换原值', () => {
  // 真实数据实测（gutkidney 40 条 · 2026-10-16）：初版经 normalizeTerm ⇒ 输出串把小写化结果写回，
  //   用户的 `SCFA` 变成 `scfa`。匹配层本就不分大小写 ⇒ 功能等价，但**可追溯性受损**
  //   （用户比对原值时会以为词表被改）。故本函数只 trim，不做任何形态归一。
  const r = REL.mergeTerms('SCFA,Dietary Fiber,肾脏', '毛球');
  assert.deepStrictEqual(r.terms, ['SCFA', 'Dietary Fiber', '肾脏', '毛球'],
    '词表 v2 必须忠实原写法，实际 ' + JSON.stringify(r.terms));
});

t('diffRanks：升级识别 + newHits 指出**是哪个补词起了作用**（人工复核的唯一依据）', () => {
  const recs = [
    { idx: 1, titleZh: '犬慢性肾衰竭的营养干预与肾脏保健', year: 2020 },
    { idx: 2, titleZh: '猫肠道菌群失调研究', year: 2021 },
  ];
  const before = rankOne(recs, { terms: '膳食纤维', near: '肾衰竭' });
  const after = rankOne(recs, { terms: '膳食纤维,肾脏保健', near: '肾衰竭' });
  const d = REL.diffRanks(before, after, { addedTerms: ['肾脏保健'] });
  assert.strictEqual(d.upgraded.length, 1, '应识别 1 条升级，实际 ' + d.upgraded.length);
  const u = d.upgraded[0];
  assert.strictEqual(u.levelFrom, 'near');
  assert.strictEqual(u.levelTo, 'exact');
  assert.ok(u.newHits.includes('肾脏保健'), 'newHits 应含补入词：' + JSON.stringify(u.newHits));
});

t('diffRanks：降级识别 —— 升级与降级**不得混淆**（方向性判据）', () => {
  const recs = [{ idx: 1, titleZh: '犬慢性肾衰竭与肾脏保健', year: 2020 }];
  const before = rankOne(recs, { terms: '肾脏保健' });
  const after = rankOne(recs, { terms: '膳食纤维' });
  const d = REL.diffRanks(before, after);
  assert.strictEqual(d.upgraded.length, 0, '不该有升级');
  assert.strictEqual(d.downgraded.length, 1, '应识别 1 条降级');
  assert.strictEqual(d.downgraded[0].levelFrom, 'exact');
  assert.ok(d.downgraded[0].lostHits.includes('肾脏保健'), 'lostHits 应含丢失的命中词');
});

t('diffRanks：配对键须含 keyword/idx/题名/**年份**（源码守卫）—— 缺失即错配', () => {
  // 为何是源码守卫而非纯行为断言：同题名记录的**行为必然相同**（同一记录同一词表），
  //   故「键缺 year」在可构造的夹具上不产生可观测差异 ⇒ 行为断言会退化为装饰。
  //   能真正暴露它的是「两次排序相对顺序被打乱」的场景，而那需要两条记录行为不同 —— 不可能。
  //   ⇒ 用**结构性守卫**把「键必须含这三项」钉死（与 suggest 的 `stationRequests: 0` 守卫同族）。
  const src = fs.readFileSync(path.join(__dirname, 'lib', 'relevance.cjs'), 'utf8');
  assert.ok(/r\.keyword == null \? '' : String\(r\.keyword\)/.test(src),
    '配对键须含 keyword（同文献跨检索式须各自配对）');
  assert.ok(/rec\.idx == null \? '' : String\(rec\.idx\)/.test(src), '配对键须含 idx');
  assert.ok(/rec\.year == null \? '' : String\(rec\.year\)/.test(src),
    '配对键须含年份（同题名不同年不得错配）');
  // 行为面：两条同题名记录须**各自**配对，不得被折叠成一条
  const mk = () => [{ keyword: 'k1', records: [
    { idx: 1, titleZh: '犬肾脏保健研究', year: 2019 },
    { idx: 2, titleZh: '犬肾脏保健研究', year: 2024 },
  ] }];
  const before = REL.rankAll(mk(), REL.buildTopic({ terms: '膳食纤维' }));
  const after = REL.rankAll(mk(), REL.buildTopic({ terms: '膳食纤维,肾脏保健' }));
  const d = REL.diffRanks(before, after);
  assert.strictEqual(d.pairs, 2, '两条记录都须配对，实际 ' + d.pairs);
  assert.strictEqual(d.upgraded.length, 2, '两条同题名记录须各自升级，实际 ' + d.upgraded.length);
  assert.strictEqual(d.unmatched.onlyBefore + d.unmatched.onlyAfter, 0, '同批数据不得有未配对项');
});

t('★ 不变量：补词只会加权 ⇒ **降级必须为 0**（出现降级即缺陷，须大声报错）', () => {
  const recs = [
    { idx: 1, titleZh: '犬慢性肾衰竭与肠道菌群失调', year: 2020 },
    { idx: 2, titleZh: '猫慢性肾病与膳食纤维干预', year: 2021 },
    { idx: 3, titleZh: '犬尿毒症毒素的检测方法', year: 2019 },
  ];
  const before = rankOne(recs, { terms: '膳食纤维', near: '肾衰竭,菌群' });
  const after = rankOne(recs, { terms: '膳食纤维,肾脏保健,乳酸杆菌', near: '肾衰竭,菌群' });
  const d = REL.diffRanks(before, after, { addedTerms: ['肾脏保健', '乳酸杆菌'] });
  assert.strictEqual(d.downgraded.length, 0,
    '补词产生降级：' + JSON.stringify(d.downgraded.map(x => x.title)));
  assert.ok(d.after.stat.exact >= d.before.stat.exact, '主题命中数不得下降');
});

t('diffRanks：字段完备（before/after/delta/upgraded/downgraded/unmatched/pairs）+ 零站点请求', () => {
  const recs = [{ idx: 1, titleZh: '犬肾脏保健', year: 2020 }];
  const d = REL.diffRanks(rankOne(recs, { terms: '膳食纤维' }),
    rankOne(recs, { terms: '膳食纤维,肾脏保健' }));
  assert.strictEqual(d.stationRequests, 0);
  for (const k of ['before', 'after', 'delta', 'upgraded', 'downgraded', 'unmatched', 'pairs']) {
    assert.ok(k in d, '缺字段 ' + k);
  }
  assert.deepStrictEqual(d.delta, { exact: 1, near: 0, off: -1, exactRate: 100 });
});

t('CLI：--apply 解析；**缺值必须报错**（静默忽略会让「补词」退化为空操作）', () => {
  const a = RK.parseArgs(['node', 's', '--dir', './run', '--topic', 'x', '--apply', '肾脏保健,乳酸杆菌']);
  assert.strictEqual(a.apply, '肾脏保健,乳酸杆菌');
  assert.strictEqual(RK.parseArgs(['node', 's']).apply, null, '默认不得补词（词表改动必须显式触发）');
  try { RK.parseArgs(['node', 's', '--apply']); }
  catch (e) {
    assert.ok(String(e.message).includes('--apply'), '错误信息应含 --apply，实际 ' + e.message);
    return;
  }
  throw new Error('--apply 缺值应抛错但未抛');
});

t('★ 渲染：对比小节须含「补词前/后」与完整词表 v2；升级条目**不得出现在降级小节**', () => {
  const recs = [{ idx: 1, titleZh: '犬慢性肾衰竭与肾脏保健', year: 2020 }];
  const before = rankOne(recs, { terms: '膳食纤维', near: '肾衰竭' });
  const after = rankOne(recs, { terms: '膳食纤维,肾脏保健', near: '肾衰竭' });
  const d = REL.diffRanks(before, after, { addedTerms: ['肾脏保健'] });
  const md = RK.renderApplyDiff(d, { topicTextV2: '膳食纤维,肾脏保健' });
  assert.ok(/补词效果对比|补词前/.test(md), 'md 未输出对比小节');
  assert.ok(md.includes('肾脏保健'), 'md 未显示补入词');
  assert.ok(/升级/.test(md) && md.includes('犬慢性肾衰竭与肾脏保健'), 'md 未列出升级条目');
  assert.ok(md.includes('膳食纤维,肾脏保健'), 'md 未给出完整词表 v2（可直接替换 --topic）');
  const tail = md.split('#### 降级')[1] || '';
  assert.ok(!tail.includes('犬慢性肾衰竭与肾脏保健'), '升级条目被误列入降级小节');
});

t('渲染集成：--apply 时 ranked.md 内嵌对比小节，站点请求仍为 0', () => {
  const recs = [{ idx: 1, titleZh: '犬慢性肾衰竭与肾脏保健', year: 2020 }];
  const before = rankOne(recs, { terms: '膳食纤维', near: '肾衰竭' });
  const after = rankOne(recs, { terms: '膳食纤维,肾脏保健', near: '肾衰竭' });
  const d = REL.diffRanks(before, after, { addedTerms: ['肾脏保健'] });
  const md = RK.renderMarkdown(after, { top: 5, applyDiff: d, topicTextV2: '膳食纤维,肾脏保健' });
  assert.ok(/补词效果对比/.test(md), '未内嵌对比小节');
  assert.ok(md.includes('站点请求: **0**'), '补词重排不得引入站点请求');
});

t('★ 源码守卫：--apply 是词表扩展的**唯一**入口（无 --apply 则主题词不变）', () => {
  const src = fs.readFileSync(path.join(__dirname, 'rank-records.cjs'), 'utf8');
  assert.ok(src.includes('--apply'), 'rank-records.cjs 未提供 --apply 入口');
  assert.ok(src.includes('mergeTerms'), 'rank-records.cjs 未调用 mergeTerms（去重逻辑不得被旁路）');
  // ★ 守卫必须限定在**语义位置**：初版只查「已全部在」四字，而 HELP 文本里也有这四个字
  //   ⇒ 单点变异（改 fail 消息）打不红 —— 「判据读到的东西不是它以为的那个」（与父子遮蔽同族）。
  //   故要求「appended 为空 ⇒ fail(...) 且消息含该提示」这一**结构 + 内容**组合。
  assert.ok(/if \(!applied\.appended\.length\) \{[\s\S]{0,220}?fail\('\[输入错误\][^']*已全部在/.test(src),
    '勾选词全为已知词时必须**显式报错**（不得静默空操作 → 用户误以为补词生效）');
  assert.strictEqual(RK.parseArgs(['node', 's']).apply, null);
});

// ---------- v4.7 挂账·多轮迭代闭环（2026-10-17） ----------
// 动因：单轮 --apply 只答「补这几个词有没有用」，答不了「这个词表还能挖到多少」。
//   本区块把「补词 → 重排 → 再诊断」串成迭代收敛，产出**上限估计** + 每轮增益曲线。
// ★ 纪律：迭代是**模拟**（自动批量取词），产物必须显式声明「不代表建议词表」；
//   真正的词表采纳仍只走 --apply（唯一通道）。
console.log('多轮迭代闭环（v4.7 挂账）:');

// 惰性 require：模块未实现时**先红可跑**（否则整个单测在 require 处崩溃，看不到红在哪）
const IT = (() => { try { return require('./lib/iterate.cjs'); } catch (e) { return null; } })();
const needIT = () => assert.ok(IT && typeof IT.iterateRounds === 'function',
  '缺 lib/iterate.cjs 的 iterateRounds');
const mkG = titles => [{ keyword: 'k', records: titles.map((t, i) => ({ idx: i + 1, titleZh: t, year: 2020 + i })) }];
const STOP_REASONS = ['no-candidates', 'all-covered', 'no-gain', 'max-rounds'];

t('★ 多轮迭代：iterateRounds 存在且为纯函数（零站点请求、零文件系统）', () => {
  needIT();
  const src = fs.readFileSync(path.join(__dirname, 'lib', 'iterate.cjs'), 'utf8');
  for (const bad of ["require('https')", 'require("https")', "require('node:https')",
    "require('http')", 'XMLHttpRequest', "require('fs')", 'require("fs")']) {
    assert.ok(!src.includes(bad), 'iterate.cjs 不得含 ' + bad + '（纯函数模块）');
  }
  assert.ok(src.includes('stationRequests: 0'), 'iterate.cjs 须显式声明零站点请求');
});

t('★ 停止原因 `no-candidates`：语料里没有词表外的高频词 ⇒ 只跑 1 轮就停', () => {
  needIT();
  const r = IT.iterateRounds({
    groups: mkG(['肾脏疾病诊断', '肾脏疾病治疗']),
    topicSpec: { terms: '肾脏疾病' },
    minDf: 2,
  });
  assert.strictEqual(r.stopReason, 'no-candidates', '实际 ' + r.stopReason);
  assert.strictEqual(r.rounds.length, 1, '应只跑 1 轮（先排序再判候选），实际 ' + r.rounds.length);
  assert.strictEqual(r.rounds[0].appended.length, 0, '无候选时不得补词');
});

t('★ 停止原因 `no-gain`：补入后主题命中数不增 ⇒ 立即停（不空转）', () => {
  needIT();
  // 两条题名**本来**已靠 `慢性肾病` 命中主题档 ⇒ 补 `营养管理` 只加分数、不加档位数
  const r = IT.iterateRounds({
    groups: mkG(['犬慢性肾病营养管理', '猫慢性肾病营养管理']),
    topicSpec: { terms: '慢性肾病' },
    minDf: 2,
  });
  assert.strictEqual(r.stopReason, 'no-gain', '实际 ' + r.stopReason);
  assert.strictEqual(r.rounds.length, 1);
  assert.ok(r.rounds[0].appended.length > 0, '本轮应有候选被补入（否则不是 no-gain 而是 no-candidates）');
  assert.strictEqual(r.totalGain, 0, 'totalGain 应为 0');
});

t('★ 每轮批量上限 `batch`：单轮补入数 ≤ K（模拟人工一次挑 K 个，而非一次全取）', () => {
  needIT();
  // ★ 必须有候选才会被执行到：这些记录初始全为 off，而 near 档语料不含 off
  //   ⇒ 必须 scope=all，否则 rounds[0].appended 为空、`every` 空真值让断言退化为装饰（实测踩过）。
  const r = IT.iterateRounds({
    groups: mkG(['A 肠道菌群', 'B 肠道菌群', 'A 膳食纤维', 'B 膳食纤维', 'A 益生菌', 'B 益生菌']),
    topicSpec: { terms: '无关词' },
    maxRounds: 2, batch: 2, minDf: 2, scope: 'all',
  });
  assert.ok(r.rounds.some(x => x.appended.length > 0), '夹具须真产生补入（否则本断言是装饰）');
  assert.ok(r.rounds.every(x => x.appended.length <= 2),
    '单轮补入超出 batch：' + r.rounds.map(x => x.appended.length).join('/'));
});

t('★ 停止原因 `max-rounds`：每轮都有增益时跑满上限（不无限迭代）', () => {
  needIT();
  // 夹具要点：三组记录**各自**共享一个候选词，且中文段恰好只产出一个 n-gram（避免残渣抢位），
  //   ⇒ batch=1 时每轮补 1 词、恰好升 2 条记录 ⇒ 每轮都有增益 ⇒ 必然跑满上限。
  //   必须 scope=all：这些记录初始全为 off，而 near 档语料不含 off ⇒ 否则第 1 轮就 no-candidates。
  const r = IT.iterateRounds({
    groups: mkG(['A 肠道菌群', 'B 肠道菌群', 'A 膳食纤维', 'B 膳食纤维', 'A 益生菌', 'B 益生菌']),
    topicSpec: { terms: '无关词' },
    maxRounds: 3, batch: 1, minDf: 2, scope: 'all',
  });
  assert.strictEqual(r.rounds.length, 3, '应跑满 3 轮，实际 ' + r.rounds.length);
  assert.strictEqual(r.stopReason, 'max-rounds', '实际 ' + r.stopReason);
  assert.deepStrictEqual(r.rounds.map(x => x.deltaExact), [2, 2, 2],
    '每轮应各升 2 条记录，实际 ' + JSON.stringify(r.rounds.map(x => x.deltaExact)));
});

t('★ 不变量①：主题命中数**单调不减**；②每轮**降级必为 0**；③词表**单调增长**', () => {
  needIT();
  const initTerms = ['无关词'];
  const r = IT.iterateRounds({
    groups: mkG(['A 肠道菌群', 'B 肠道菌群', 'A 膳食纤维', 'B 膳食纤维']),
    topicSpec: { terms: initTerms.join(',') },
    maxRounds: 3, batch: 1, minDf: 2, scope: 'all',
  });
  let prevExact = r.baseline.stat.exact;
  let prevTerms = initTerms.slice();
  for (const rd of r.rounds) {
    assert.ok(rd.stat.exact >= prevExact,
      '第 ' + rd.n + ' 轮主题命中下降：' + prevExact + ' → ' + rd.stat.exact);
    assert.strictEqual(rd.downgraded, 0, '第 ' + rd.n + ' 轮出现降级（应为 0）');
    assert.ok(prevTerms.every(t => rd.terms.includes(t)),
      '第 ' + rd.n + ' 轮词表丢词（必须单调增长）');
    prevExact = rd.stat.exact;
    prevTerms = rd.terms;
  }
  assert.strictEqual(r.totalGain, r.final.stat.exact - r.baseline.stat.exact, 'totalGain 须等于首尾差');
});

t('★ 停止原因必须**穷举**四种之一（不得静默返回一个说不清的状态）', () => {
  needIT();
  const cases = [
    { groups: mkG(['肾脏疾病诊断', '肾脏疾病治疗']), topicSpec: { terms: '肾脏疾病' }, minDf: 2 },
    { groups: mkG(['犬慢性肾病营养管理', '猫慢性肾病营养管理']), topicSpec: { terms: '慢性肾病' }, minDf: 2 },
    // 这个 case 必须能跑到「循环自然结束」的路径 —— 否则 max-rounds 分支根本没被穷举判据覆盖
    { groups: mkG(['A 肠道菌群', 'B 肠道菌群', 'A 膳食纤维', 'B 膳食纤维', 'A 益生菌', 'B 益生菌']),
      topicSpec: { terms: '无关词' }, maxRounds: 3, batch: 1, minDf: 2, scope: 'all' },
  ];
  const reasons = cases.map(c => IT.iterateRounds(c).stopReason);
  for (const r of reasons) {
    assert.ok(STOP_REASONS.includes(r), '未穷举的停止原因：' + r);
  }
  assert.ok(reasons.includes('max-rounds'),
    '用例须覆盖 max-rounds 分支，否则穷举判据不完整：' + reasons.join(' / '));
});

t('★ `pick=extends`：只自动补「词表词+修饰」，**半重叠类一律不自动补**（进 deferred）', () => {
  needIT();
  // 夹具要点：半重叠类必须**不含**词表词才有可能（与 `肾脏` 有 ≥2 字公共子串的串必然含 `肾脏`
  //   ⇒ 那类全是 extends）。故词表放两个词，用 `菌群多样性`（LCS 2，不含 `肠道菌群`）充当半重叠。
  const r = IT.iterateRounds({
    groups: mkG(['犬肾脏保健研究', '猫肾脏保健探索', '犬菌群多样性分析', '猫菌群多样性探讨']),
    topicSpec: { terms: '肾脏,肠道菌群' },
    pick: 'extends', maxRounds: 1, batch: 10, minDf: 2, scope: 'all',
  });
  const rd = r.rounds[0];
  assert.ok(rd.appended.length > 0, 'extends 档应有可补项（`肾脏保健` ⊃ `肾脏`）');
  assert.ok(rd.appended.every(t => t.includes('肾脏') || t.includes('腎臟')),
    'extends 档只允许补「含词表词」的串：' + JSON.stringify(rd.appended));
  assert.ok(rd.deferred.length > 0, '半重叠类（`菌群多样性` vs `肠道菌群`）须进 deferred 而非被静默丢弃');
});

t('★ 空输入不崩：空 groups / 空题名 ⇒ 明确停止原因，绝不抛异常', () => {
  needIT();
  const a = IT.iterateRounds({ groups: [], topicSpec: { terms: '肾脏' } });
  assert.strictEqual(a.stopReason, 'no-candidates');
  assert.deepStrictEqual(a.rounds[0].appended, []);
  const b = IT.iterateRounds({ groups: mkG(['']), topicSpec: { terms: '肾脏' } });
  assert.ok(STOP_REASONS.includes(b.stopReason));
});

t('CLI：--iterate / --iterate-batch / --iterate-pick 解析；**越界与缺值必须报错**', () => {
  assert.strictEqual(RK.parseArgs(['node', 's']).iterate, null, '默认不得迭代');
  assert.strictEqual(RK.parseArgs(['node', 's', '--iterate', '3']).iterate, 3);
  assert.strictEqual(RK.parseArgs(['node', 's', '--iterate-batch', '5']).iterateBatch, 5);
  assert.strictEqual(RK.parseArgs(['node', 's', '--iterate-pick', 'extends']).iteratePick, 'extends');
  assert.strictEqual(RK.parseArgs(['node', 's']).iterateBatch, 5, '默认 batch 应为 5');
  assert.strictEqual(RK.parseArgs(['node', 's']).iteratePick, 'all', '默认 pick 应为 all（上限探测）');
  const bad = (arr, needle) => {
    try { RK.parseArgs(['node', 's', ...arr]); }
    catch (e) {
      assert.ok(String(e.message).includes(needle), '错误信息应含 ' + needle + '，实际 ' + e.message);
      return;
    }
    throw new Error('应当抛错但未抛: ' + JSON.stringify(arr));
  };
  bad(['--iterate', '0'], '--iterate');
  bad(['--iterate', 'x'], '--iterate');
  bad(['--iterate', '9'], '--iterate');          // 上限 8
  bad(['--iterate'], '--iterate');               // 缺值
  bad(['--iterate-batch', '0'], '--iterate-batch');
  bad(['--iterate-pick', 'foo'], '--iterate-pick');
});

t('★ 渲染：收敛曲线 + 停止原因 + **免责声明**（模拟档必须声明不代表建议词表）', () => {
  needIT();
  const r = IT.iterateRounds({
    groups: mkG(['A 肠道菌群', 'B 肠道菌群', 'A 膳食纤维', 'B 膳食纤维']),
    topicSpec: { terms: '无关词' },
    maxRounds: 2, batch: 1, minDf: 2, scope: 'all',
  });
  const md = RK.renderIterateReport(r, { pick: 'all' });
  assert.ok(/迭代|收敛/.test(md), 'md 未输出迭代小节');
  assert.ok(md.includes('停止') || md.includes('终止'), 'md 未说明停止原因');
  assert.ok(/不代表建议词表|待人工确认/.test(md), '模拟档必须显式声明不代表性');
  assert.ok(md.includes(String(r.stopReason)) || /无候选|无增益|达上限/.test(md),
    'md 未把停止原因写清（须人类可读 + 原值可查）');
  // 方向性：词表 vN 必须标注「待人工确认」，不得直接写成「可直接粘贴」
  assert.ok(/待人工确认/.test(md), '迭代产出的词表不得被标成可直接采纳');
});

t('★ 源码守卫：迭代的词表合并必须复用 `mergeTerms`（不得另写一套去重逻辑）', () => {
  needIT();
  const src = fs.readFileSync(path.join(__dirname, 'lib', 'iterate.cjs'), 'utf8');
  // ★ 限定到**语义位置**（教训：孤立字符串会命中注释/别的分支，单点变异就打不红 —— 上轮 M13 盲区）
  assert.ok(/const merged = REL\.mergeTerms\(termsText, picked\)/.test(src),
    '每轮合并须直接调用 mergeTerms（否则会出现第二套去重语义）');
  assert.ok(!/new Set\(.*compactKey/.test(src), 'iterate.cjs 不得自行实现去重（须委托 mergeTerms）');
  const rkSrc = fs.readFileSync(path.join(__dirname, 'rank-records.cjs'), 'utf8');
  // 同样限定到语义位置：只查消息文本会被「条件改成 false 但消息保留」的变异逃过（M13 实测）
  assert.ok(/if \(o\.apply\) \{[\s\S]{0,220}?--iterate 与 --apply 不可同时使用/.test(rkSrc),
    '必须拒绝 iterate + apply 同时使用（探测与采纳的语义相反）');
});

t('★ 边界一致性：maxRounds=1 时等价于「单轮补词」—— 最终词表 = 初始 + 本轮 appended', () => {
  needIT();
  const r = IT.iterateRounds({
    groups: mkG(['犬肾脏保健与肠道菌群研究', '猫肾脏保健与肠道菌群研究']),
    topicSpec: { terms: '肾脏' },
    maxRounds: 1, batch: 10, minDf: 2,
  });
  assert.strictEqual(r.rounds.length, 1);
  const rd = r.rounds[0];
  assert.deepStrictEqual(rd.terms, ['肾脏'].concat(rd.appended), '单轮结果须等于「原词 + 本轮补入」');
  assert.deepStrictEqual(r.terms, rd.terms, '最终词表须等于最后一轮词表');
});

t('★ 收敛后残留清单 `residual`：等于「非主题命中」的记录 —— 补词治不了的**结构性缺口**', () => {
  needIT();
  const r = IT.iterateRounds({
    groups: mkG(['A 肠道菌群', 'B 肠道菌群', '犬完全无关的骨肿瘤研究']),
    topicSpec: { terms: '肠道菌群' },
    maxRounds: 2, batch: 2, minDf: 2, scope: 'all',
  });
  assert.strictEqual(r.residual.length, r.final.total - r.final.stat.exact,
    'residual 长度须等于「总数 − 主题命中」：' + r.residual.length + ' vs '
    + (r.final.total - r.final.stat.exact));
  assert.ok(r.residual.every(x => x.level !== 'exact'), '不得把主题命中列进残留');
  assert.ok(r.residual.some(x => /骨肿瘤/.test(x.title)),
    '未被主题命中的记录须出现在残留清单：' + JSON.stringify(r.residual.map(x => x.title)));
  const md = RK.renderIterateReport(r, { pick: 'all' });
  assert.ok(/结构性|补词治不了|缺主题维度/.test(md),
    'md 未说明残留清单的性质（否则会被误读成又一份补词建议）');
});

// ---------- v4.7 挂账·残差主题维度诊断（2026-10-18） ----------
// 动因：`residual` 只答「哪些记录补词治不了」，答不了「**缺的是哪个维度**」。
//   本区块把残留清单按「共现指纹」聚成维度候选：新维度（与现有轴零重叠）/ 同轴（可补词解决）。
// ★ 铁律：**只提示，不自动建** —— 提案永不回流词表，采纳仍只走 --apply。
// ★ 为何 diagnose 里没有 covered / exclude 过滤（不是漏写，是**不可达**）：
//   rankAll 的档位规则为「题名含主题词 ⇒ exact」，而排除词记录直接进 excluded 档且被本模块跳过
//   ⇒ 「残差题名含词表词」与「残差含排除词」在语义上都不存在。
//   该前提由下面「不变量守卫」用例显式钉住：一旦 rankAll 改档位规则，先红的是它，不是诊断结论。
console.log('残差主题维度诊断（v4.7 挂账）:');

const DG = (() => { try { return require('./lib/diagnose.cjs'); } catch (e) { return null; } })();
const needDG = () => assert.ok(DG && typeof DG.diagnoseResidual === 'function',
  '缺 lib/diagnose.cjs 的 diagnoseResidual');
/** 题名 → ranked → 诊断（与 CLI 同路径：rankAll 先行，诊断只看已排序结果） */
const dgRun = (titles, spec, opts) => {
  const r = REL.rankAll(mkG(titles), REL.buildTopic(spec));
  return DG.diagnoseResidual(r.ranked, r.topic, opts || {});
};

t('★ 残差维度诊断：纯函数（零站点请求 / 无 fs·http）+ autoApply 恒 false', () => {
  needDG();
  const src = fs.readFileSync(path.join(__dirname, 'lib', 'diagnose.cjs'), 'utf8');
  for (const bad of ["require('https')", 'require("https")', "require('http')", 'require("http")',
    "require('fs')", 'require("fs")', 'XMLHttpRequest']) {
    assert.ok(!src.includes(bad), 'diagnose.cjs 不得含 ' + bad + '（纯函数模块）');
  }
  assert.ok(/stationRequests: 0/.test(src), 'diagnose.cjs 须显式声明零站点请求');
  const d = dgRun(['猫膀胱炎与尿道结石', '犬膀胱炎与尿道结石'], { terms: '肠道菌群' });
  assert.strictEqual(d.stationRequests, 0);
  assert.strictEqual(d.autoApply, false, '诊断**不得**声明自动应用');
  assert.strictEqual(d.proposal.autoApply, false, '提案同样不得自动应用');
});

t('★ 新维度：残差共享词表外的领域词 ⇒ 归纳出 new-dimension 簇（支持数 = 簇内记录数）', () => {
  needDG();
  const d = dgRun(['猫膀胱炎与尿道结石', '犬膀胱炎与尿道结石', '猫下泌尿道疾病', '犬肠道菌群失调'],
    { terms: '肠道菌群' });
  assert.strictEqual(d.residual.total, 3, '主题档那条不得进残差，实际 ' + d.residual.total);
  assert.strictEqual(d.verdict, 'new-dimension', '实际 ' + d.verdict);
  const c = d.clusters.filter(x => x.kind === 'new-dimension');
  assert.strictEqual(c.length, 1, '应恰有 1 个新维度簇，实际 ' + c.length);
  assert.strictEqual(c[0].support, 3, '支持数须等于簇内记录数，实际 ' + c[0].support);
  assert.strictEqual(c[0].idxs.length, c[0].support, 'idxs 长度须与 support 一致');
  assert.ok(c[0].terms.some(x => x.term === '膀胱炎'),
    '簇术语须含 膀胱炎：' + JSON.stringify(c[0].terms.map(x => x.term)));
  assert.ok(d.proposal.keywords.length > 0, '新维度须给出待人工确认的候选词');
});

t('★ 新维度不得被同轴高频词吞掉（novel 优先于 axis）', () => {
  needDG();
  // 夹具几何：`膳食纤维` 是相邻词（axis）且 df=3 > `膀胱炎`（novel）df=2。
  //   若按 df 全局排序做贪心，axis 会先占满三条记录 ⇒ 新维度整簇消失（这正是要防的漏判）。
  const d = dgRun(['猫膳食纤维与膀胱炎', '犬膳食纤维与膀胱炎', '猫膳食纤维与肠道'],
    { terms: '肠道菌群', near: '膳食纤维' });
  assert.strictEqual(d.residual.total, 3, '三条都须为残差（否则夹具无效）');
  const novel = d.clusters.filter(x => x.kind === 'new-dimension');
  assert.strictEqual(novel.length, 1, '新维度簇被同轴词吞掉了，实际簇：'
    + JSON.stringify(d.clusters.map(x => x.kind + ':' + x.label)));
  assert.ok(novel[0].terms.some(x => x.term === '膀胱炎'), '新维度簇须含 膀胱炎');
  assert.ok(d.proposal.keywords.some(k => k.includes('膀胱') || k.includes('胱')),
    '提案须指向新维度词，实际 ' + JSON.stringify(d.proposal.keywords));
});

t('★ 同轴不冒充新维度：与相邻词半重叠/命中 ⇒ axis-extend，提案必须为空', () => {
  needDG();
  const d = dgRun(['猫膳食纤维与营养', '犬膳食纤维与代谢', '猫膳食纤维与肠道'],
    { terms: '肠道菌群', near: '膳食纤维' });
  assert.ok(d.clusters.length > 0, '夹具须真产生簇（否则断言是装饰）');
  assert.strictEqual(d.verdict, 'axis-only', '实际 ' + d.verdict);
  assert.ok(d.clusters.every(x => x.kind === 'axis-extend'),
    '同轴词不得被标成新维度：' + JSON.stringify(d.clusters.map(x => x.kind)));
  assert.deepStrictEqual(d.proposal.keywords, [],
    '同轴残差用 --apply 补词即可 ⇒ 提案必须为空（不得把已知轴的词当新维度）');
});

t('★ 证据不足不臆造：无共享词 / 单条残差 ⇒ no-shared-terms（逐条交人读）', () => {
  needDG();
  const a = dgRun(['猫膀胱炎', '犬骨肿瘤'], { terms: '肠道菌群' });
  assert.strictEqual(a.residual.total, 2, '夹具须真产生残差（空真值会让下面断言退化）');
  assert.strictEqual(a.verdict, 'no-shared-terms', '实际 ' + a.verdict);
  assert.strictEqual(a.clusters.length, 0, '无共享词时不得凭空造簇');
  assert.strictEqual(a.unclustered.length, 2, '两条都须逐条列出，不得静默丢弃');
  const b = dgRun(['猫膀胱炎'], { terms: '肠道菌群' });
  assert.strictEqual(b.residual.total, 1);
  assert.strictEqual(b.verdict, 'no-shared-terms', '单条记录凑不成「维度」，实际 ' + b.verdict);
  assert.deepStrictEqual(b.proposal.keywords, []);
});

t('★ 簇间互斥：每条残差至多属一簇，support 之和 ≤ 残差数（不得重复计数）', () => {
  needDG();
  // 两簇各自**至少两个共享词**（否则会被「无凝聚度」剪枝，夹具就产不出簇 —— 见上一条用例）：
  //   簇 A = 膀胱炎 + 尿道结石；簇 B = 肠道寄生虫 + 腹泻
  const d = dgRun(['猫膀胱炎与尿道结石', '犬膀胱炎与尿道结石', '猫肠道寄生虫与腹泻', '犬肠道寄生虫与腹泻'],
    { terms: '毛球' });
  assert.ok(d.clusters.length >= 2, '夹具须真产生 ≥2 簇（否则互斥断言是装饰），实际 '
    + d.clusters.length);
  const sum = d.clusters.reduce((s, c) => s + c.support, 0);
  assert.ok(sum <= d.residual.total, '支持数之和 ' + sum + ' 超过残差数 ' + d.residual.total);
  const seen = new Set();
  for (const c of d.clusters) for (const x of c.idxs) {
    assert.ok(!seen.has(x), '记录 idx=' + x + ' 同时落在多个簇（重复计数）');
    seen.add(x);
  }
});

t('★ 泛词不足以成簇：只共享 1 个词（`生物` 类）⇒ no-cohesion 剪除，不当作新维度', () => {
  needDG();
  // 一手证据反演（2026-10-18 猫毛球真实回放）：合成生物学／生物安全／生物风险 共享 `生物` 但
  //   彼此主题无关 ⇒ 若仅凭「一个共享词」就成簇，会得出一条假的新维度提案。
  const d = dgRun(['合成生物学展望', '动物生物安全', '犬猫膀胱炎与尿道结石', '猫膀胱炎与尿道结石'],
    { terms: '毛球' });
  assert.ok(d.clusters.length > 0, '夹具须真产生簇（膀胱炎簇），否则断言是装饰');
  assert.ok(!d.clusters.some(c => c.label === '生物'), '`生物` 这类泛词不得成为维度标签：'
    + JSON.stringify(d.clusters.map(c => c.label)));
  assert.ok(d.unclustered.some(x => x.reason === 'no-cohesion'),
    '单共享词的簇须以 no-cohesion 剪除并逐条列出：'
    + JSON.stringify(d.unclustered.map(x => x.reason)));
  assert.ok(!d.proposal.keywords.includes('生物'), '提案不得混入泛词');
});

t('★ 低支持簇必剪：被高优先种子抢占后不足 minSupport ⇒ 剪除并逐条列出（个案不是维度）', () => {
  needDG();
  // 几何：膀胱炎 ⊆ {R1,R2}、结石 ⊆ {R1,R3} —— 膀胱炎先认领 R1,R2，结石只剩 R3 ⇒ support=1 必被剪。
  //   （M4 变异实测：不剪枝时本用例**不**转红，因为「无指纹」的夹具根本走不到剪枝分支 ⇒ 必须补此夹具）
  const d = dgRun(['猫膀胱炎与结石', '犬膀胱炎', '猫结石'], { terms: '肠道菌群' });
  assert.ok(d.clusters.every(c => c.support >= d.minSupport),
    '出现支持数 < minSupport 的簇（个案被当成维度）：'
    + JSON.stringify(d.clusters.map(c => c.support)));
  assert.ok(d.unclustered.some(x => x.reason === 'spun-off'),
    '被剪簇的记录须以 spun-off 逐条列出，不得静默丢弃：'
    + JSON.stringify(d.unclustered.map(x => x.reason)));
});

t('★ 排除词记录不参与诊断（用户已否决的文献不得驱动新增维度提案）', () => {
  needDG();
  const withExc = dgRun(['犬膀胱炎', '猫膀胱炎与结石'], { terms: '肠道菌群', exclude: '犬' });
  const noExc = dgRun(['犬膀胱炎', '猫膀胱炎与结石'], { terms: '肠道菌群' });
  assert.strictEqual(noExc.residual.total, 2, '对照组须两条都进残差（否则区分不出排除是否生效）');
  assert.strictEqual(withExc.dropped.excludedRecords, 1,
    '应跳过 1 条排除记录，实际 ' + withExc.dropped.excludedRecords);
  assert.strictEqual(withExc.residual.total, 1, '残差只应含未排除的那条，实际 ' + withExc.residual.total);
  assert.strictEqual(withExc.unclustered.length, 1, '被跳过的记录不得进簇，剩下的须逐条列出');
});

t('★ 不变量守卫：题名含主题词 ⇒ exact（诊断「不做 covered/exclude 过滤」的前提）', () => {
  needDG();
  const r = REL.rankAll(mkG(['犬肠道菌群失调', '猫肠道菌群', '肠道菌群与肾病']),
    REL.buildTopic({ terms: '肠道菌群' }));
  assert.strictEqual(r.stat.exact, 3, 'rankAll 规则变更 ⇒ 诊断的「不可达」前提失效，须重估');
  const dg = dgRun(['犬肠道菌群失调'], { terms: '肠道菌群' });
  assert.strictEqual(dg.residual.total, 0);
  assert.strictEqual(dg.verdict, 'no-residual', '实际 ' + dg.verdict);
  assert.deepStrictEqual(dg.clusters, [], '无残差时不得产出簇');
});

t('★ 提案只提示不自动建：diagnosis 的词不得出现在 iterate 的最终词表里', () => {
  needIT(); needDG();
  // 用 scope=near（默认）：off 档记录不在补词语料里 ⇒ 迭代不补词，残差保留，
  //   才能验证「提案有词、词表没词」这一**真实**状态（否则断言会因提案为空而空转）。
  const r = IT.iterateRounds({
    groups: mkG(['A 肠道菌群', 'B 肠道菌群', 'A 膀胱炎与结石', 'B 膀胱炎与结石']),
    topicSpec: { terms: '肠道菌群' }, maxRounds: 2, batch: 3, minDf: 2,
  });
  assert.ok(r.diagnosis, 'iterateRounds 须挂 diagnosis');
  assert.ok(r.diagnosis.proposal.keywords.length > 0,
    '夹具须真产出提案（否则下面的「不得并入」是空断言）');
  const joined = r.terms.join(',');
  for (const k of r.diagnosis.proposal.keywords) {
    assert.ok(!joined.includes(k), '提案词 ' + k + ' 不得自行并入词表：' + joined);
  }
  assert.strictEqual(r.diagnosis.autoApply, false);
});

t('★ 集成一致性：diagnosis 的残差数 = iterate 残留清单中「非排除」条数', () => {
  needIT(); needDG();
  const r = IT.iterateRounds({
    groups: mkG(['A 肠道菌群', 'B 肠道菌群', 'A 膀胱炎与结石', 'B 膀胱炎与结石']),
    topicSpec: { terms: '肠道菌群' }, maxRounds: 2, batch: 3, minDf: 2,
  });
  assert.ok(r.residual.every(x => typeof x.excluded === 'boolean'),
    '残留项须带 excluded 标记（否则两边口径无法对账）');
  assert.strictEqual(r.diagnosis.residual.total, r.residual.filter(x => !x.excluded).length,
    '诊断残差数与残留清单口径不一致：' + r.diagnosis.residual.total + ' vs '
    + r.residual.filter(x => !x.excluded).length);
});

t('★ 确定性：同输入两次调用结果深等（键序固定，可作 sha256 基线）', () => {
  needDG();
  const a = dgRun(['猫膀胱炎与结石', '犬膀胱炎与结石', '猫下泌尿道疾病'], { terms: '肠道菌群' });
  const b = dgRun(['猫膀胱炎与结石', '犬膀胱炎与结石', '猫下泌尿道疾病'], { terms: '肠道菌群' });
  assert.deepStrictEqual(a, b);
  assert.strictEqual(JSON.stringify(a), JSON.stringify(b), '键序须稳定（禁依赖插入顺序）');
});

t('★ 渲染：诊断小节须含「仅提示 / 需人工确认 / 不自动建」三重免责', () => {
  needIT(); needDG();
  const r = IT.iterateRounds({
    groups: mkG(['A 肠道菌群', 'B 肠道菌群', 'A 膀胱炎与结石', 'B 膀胱炎与结石']),
    topicSpec: { terms: '肠道菌群' }, maxRounds: 2, batch: 3, minDf: 2,
  });
  const md = RK.renderIterateReport(r, {});
  assert.ok(md.includes('残差维度诊断'), 'md 未输出维度诊断小节');
  assert.ok(/仅提示|不自动建/.test(md), 'md 未声明「只提示不自动建」');
  assert.ok(/需人工确认|待人工确认/.test(md), 'md 未标人工确认');
  // JSON 通道同样必须携带（供上游程序读取；不得只留在人读视图里）
  const j = JSON.parse(RK.renderJson(REL.rankAll(mkG(['A 肠道菌群']), REL.buildTopic({ terms: '肠道菌群' })),
    { iterateReport: r }));
  assert.ok(j.iterate && j.iterate.diagnosis, 'JSON 缺 iterate.diagnosis');
  assert.strictEqual(j.iterate.diagnosis.verdict, r.diagnosis.verdict);
});

// ---------- 残差维度 → 建议检索式（处方层） ----------
//   诊断答「缺哪个维度」，本层答「**用什么检索式去验证这个维度**」。
// ★ 铁律：只出方案、不执行（`executed` 恒 false）；每条式 `verified` 恒 false（未实测 ⇒ 待证伪）。
// ★ 为何要做「物种粘连」剪枝：n-gram 会把 `Canine chronic` / `猫膀胱` 这类「物种 + 半个词」当术语，
//   而检索式本身已经有物种块 ⇒ 两者并存会得到「(cat OR feline) AND (Canine chronic)」这种自相矛盾的式子。
console.log('残差维度 → 建议检索式（v4.7 挂账）:');

const QP = (() => { try { return require('./lib/query-plan.cjs'); } catch (e) { return null; } })();
const needQP = () => assert.ok(QP && typeof QP.buildQueryPlans === 'function',
  '缺 lib/query-plan.cjs 的 buildQueryPlans');
/** 中文新维度簇夹具（膀胱炎 + 尿道结石，簇内两个共享词） */
const QP_CN = ['猫膀胱炎与尿道结石', '犬膀胱炎与尿道结石'];
/** 英文新维度簇夹具（chronic kidney，术语天然是多词短语 ⇒ 触发「未加引号」提示） */
const QP_EN = ['Feline chronic kidney disease', 'Canine chronic kidney disease',
  'Feline chronic kidney injury', 'Canine chronic kidney injury'];
const qpRun = (titles, spec, opts) => {
  const r = REL.rankAll(mkG(titles), REL.buildTopic(spec));
  const d = DG.diagnoseResidual(r.ranked, r.topic, {});
  // ★ 与生产路径一致：必须把真实 topic 传进去（主题锚就取自它）。
  //   夹具若不传 topic，锚相关断言会退化成「恒无锚」的空真值。
  return {
    d,
    p: QP.buildQueryPlans(d.clusters, Object.assign({ rows: r.ranked, topic: r.topic }, opts || {})),
  };
};

t('★ 建议检索式：纯函数（零站点请求）+ executed 恒 false（不得自动跑）', () => {
  needQP();
  const src = fs.readFileSync(path.join(__dirname, 'lib', 'query-plan.cjs'), 'utf8');
  for (const bad of ["require('https')", 'require("https")', "require('http')", 'require("http")',
    "require('fs')", 'require("fs")', 'XMLHttpRequest', 'child_process']) {
    assert.ok(!src.includes(bad), 'query-plan.cjs 不得含 ' + bad + '（纯函数模块，不自行执行）');
  }
  assert.ok(/executed: false/.test(src), 'query-plan.cjs 须显式声明「不执行」');
  const { p } = qpRun(QP_CN, { terms: '肠道菌群' });
  assert.ok(p.plans.length > 0, '夹具须真产出检索式（否则下面的恒 false 是空断言）');
  assert.strictEqual(p.executed, false, '**不得**基于诊断自动执行检索');
  assert.strictEqual(p.stationRequests, 0);
  assert.ok(p.plans.every(x => x.verified === false),
    '每条式都须标未实测（verified=false），不得暗示已验证');
});

t('★ 建议检索式语法合法：无引号短语 / 无减号排除 / 括号配对，validateQuery 零告警', () => {
  needQP();
  const { p } = qpRun(QP_CN.concat(QP_EN), { terms: '肠道菌群' });
  assert.ok(p.plans.length >= 2, '夹具须产出多条式（含中英两侧），实际 ' + p.plans.length);
  for (const x of p.plans) {
    assert.ok(!/["“”『』]/.test(x.query), '不得含引号短语语法（站点实测返回 0 条）：' + x.query);
    assert.ok(!/(^|\s)-\S/.test(x.query), '不得含 -排除词 语法（站点实测返回 0 条）：' + x.query);
    assert.deepStrictEqual(Q.validateQuery(x.query), [],
      'validateQuery 告警：' + JSON.stringify(Q.validateQuery(x.query)) + ' | ' + x.query);
  }
});

t('★ 主题锚：新维度处方必须保留主题约束（否则取回的是「维度通用文献」而非「主题×维度」）', () => {
  needQP();
  // 一手证据（2026-10-18 处方实测）：无锚式 `(cat OR feline) AND (Kidney OR …)` 取回 16 条猫 CKD，
  //   全词表下 15 条只到 near（有 kidney、无肠侧词）⇒ 式子把主题约束丢了，取回的是「猫肾病」整个大类。
  const { p } = qpRun(QP_EN, { terms: 'gut microbiota,gut microbiome' });
  const en = p.plans.filter(x => x.lang === 'en');
  assert.ok(en.length > 0, '夹具须产出英文式（否则本用例是空断言）');
  for (const x of en) {
    assert.strictEqual(x.anchorSource, 'topic', '有可用主题词却未加锚：' + x.query);
    assert.ok(x.anchors.length >= 1, 'anchors 为空：' + x.query);
    assert.ok(/AND \(/.test(x.query), '锚块须以 AND (…) 形式出现：' + x.query);
    // 锚块必须**在末尾**且与 anchors 一致（只看「以 ) 结尾」会被维度块末尾的 ) 蒙过去）
    assert.ok(x.query.endsWith('(' + x.anchors.join(' OR ') + ')'),
      '锚块未落在式子末尾或与 anchors 不一致：' + x.query + ' | anchors=' + JSON.stringify(x.anchors));
    assert.ok(x.query.indexOf('AND') < x.query.lastIndexOf('AND'), '结构须为「物种 AND 维度 AND 锚」：' + x.query);
  }
});

t('★ 无可用主题锚时必须显式告警（不得静默放宽召回）', () => {
  needQP();
  // 词表只有中文词 ⇒ 英文式配不到锚。此时不能假装「式子够用」，必须写明召回会扩散到维度大类。
  const { p } = qpRun(QP_EN, { terms: '肠道菌群,膳食纤维' });
  const en = p.plans.filter(x => x.lang === 'en');
  assert.ok(en.length > 0, '夹具须产出英文式（否则本用例是空断言）');
  for (const x of en) {
    assert.strictEqual(x.anchorSource, 'none', '无锚却声称有锚：' + x.query);
    assert.deepStrictEqual(x.anchors, [], '无锚时 anchors 须为空');
    assert.ok(x.warnings.some(w => /主题锚/.test(w)), '缺锚未告警：' + JSON.stringify(x.warnings));
  }
});

t('★ 锚不与维度术语重复，且不得混入 terms（锚是检索用的，不是词表扩展）', () => {
  needQP();
  // 直接构造簇（不经排序）：避免夹具被「题名含主题词即 exact」的规则吃掉 —— 那样就没有残差了。
  // ★ 词表用 `kidney` 而簇术语是 `Kidney Disease`：**真子串、非等值** —— 只有子串判据能挡住它。
  const cluster = {
    kind: 'new-dimension', label: 'Kidney Disease', support: 3, confidence: 'strong',
    terms: [{ term: 'Kidney Disease', df: 3 }, { term: 'Kidney Injury', df: 2 }],
  };
  const p = QP.buildQueryPlans([cluster], { species: 'both', topic: { terms: ['kidney', 'renal'], near: [] } });
  const en = p.plans.filter(x => x.lang === 'en');
  assert.ok(en.length > 0, '夹具须产出英文式');
  for (const x of en) {
    assert.ok(!x.anchors.some(a => /^kidney$/i.test(a)), '锚重复了维度术语：' + x.anchors.join('、'));
    assert.ok(x.anchors.includes('renal'), '可用锚 renal 被漏掉：' + JSON.stringify(x.anchors));
    assert.ok(!x.terms.some(t => /^renal$/i.test(t)), '锚混进了 terms（会被误当成词表扩展）：'
      + JSON.stringify(x.terms));
  }
});

t('★ 只给新维度出处方：axis-extend 簇进 skipped（同轴补词即可，不该另开检索方向）', () => {
  needQP();
  const { p } = qpRun(['猫膳食纤维与营养', '犬膳食纤维与代谢', '猫膳食纤维与肠道'],
    { terms: '肠道菌群', near: '膳食纤维' });
  assert.ok(p.skipped.length > 0, '夹具须产出 axis-extend 簇（否则 skipped 断言是装饰）');
  assert.ok(p.skipped.every(s => s.reason === 'axis-extend'), '原因须为 axis-extend');
  assert.deepStrictEqual(p.plans, [], '同轴残差不得产出新检索方向：'
    + JSON.stringify(p.plans.map(x => x.query)));
});

t('★ 术语保原文形态：`Kidney` 不得被改写成 `kidney`（归一只用于比较，不用于输出）', () => {
  needQP();
  const { p } = qpRun(['Feline Kidney Disease alpha', 'Canine Kidney Disease beta',
    'Feline Kidney Injury gamma', 'Canine Kidney Injury delta'], { terms: '膳食纤维' });
  assert.ok(p.plans.length > 0, '夹具须真产出检索式');
  const all = p.plans.map(x => x.query).join(' | ');
  assert.ok(/Kidney/.test(all), '原大写形态丢失（被静默小写化）：' + all);
  assert.ok(/chronic kidney/.test(qpRun(QP_EN, { terms: '膳食纤维' }).p.plans.map(x => x.query).join(' ')),
    '原小写形态同样须保留');
});

t('★ 中英分条：中文术语配中文物种块，英文术语配英文物种块（不得混搭）', () => {
  needQP();
  const { p } = qpRun(QP_CN.concat(QP_EN), { terms: '肠道菌群' });
  const zh = p.plans.filter(x => x.lang === 'zh');
  const en = p.plans.filter(x => x.lang === 'en');
  assert.ok(zh.length > 0, '中文簇须出中文式');
  assert.ok(en.length > 0, '英文簇须出英文式');
  for (const x of zh) {
    assert.ok(/犬|猫|伴侣动物/.test(x.query), '中文式缺中文物种块：' + x.query);
    assert.ok(!/\bor\b/.test(x.query), '中文式混入英文 OR：' + x.query);
  }
  for (const x of en) {
    assert.ok(/dog|cat|canine|feline/i.test(x.query), '英文式缺英文物种块：' + x.query);
    assert.ok(!/[犬猫]/.test(x.query), '英文式混入中文词：' + x.query);
  }
});

t('★ 物种块可自动探测（cat/dog/both），且 --species none 时不加物种限定', () => {
  needQP();
  const cat = qpRun(['Feline chronic kidney disease', 'Feline chronic kidney injury',
    'Feline chronic kidney markers', 'Feline chronic kidney outcomes'], { terms: '膳食纤维' });
  assert.strictEqual(cat.p.species, 'cat', '全猫语料须判 cat，实际 ' + cat.p.species);
  const dog = qpRun(['犬慢性肾病综述', '犬慢性肾病机制', '犬慢性肾病营养', '犬慢性肾病分期'],
    { terms: '膳食纤维' });
  assert.strictEqual(dog.p.species, 'dog', '全犬语料须判 dog，实际 ' + dog.p.species);
  const both = qpRun(QP_EN, { terms: '膳食纤维' });
  assert.strictEqual(both.p.species, 'both', '犬猫混合须判 both，实际 ' + both.p.species);
  const none = qpRun(QP_CN, { terms: '肠道菌群' }, { species: 'none' });
  assert.strictEqual(none.p.species, 'none');
  assert.ok(none.p.plans.length > 0, 'none 仍须产出式（只是不带物种块）');
  for (const x of none.p.plans) {
    assert.ok(!/伴侣动物|宠物/.test(x.query), 'none 不得带物种块：' + x.query);
  }
});

t('★ 术语上限：超出 cap 的术语进 dropped 并告警（不静默截断）', () => {
  needQP();
  const { p } = qpRun(QP_EN, { terms: '膳食纤维' }, { cap: 2 });
  assert.ok(p.plans.length > 0, '夹具须真产出式');
  const x = p.plans[0];
  assert.ok(x.terms.length <= 2, '术语数超 cap：' + JSON.stringify(x.terms));
  if (x.dropped.length) {
    assert.ok(x.warnings.some(w => /cap|截断|丢弃/.test(w)), '截断须显式告警：' + JSON.stringify(x.warnings));
  } else {
    assert.ok(x.terms.length === 2, 'dropped 为空时须真达到 cap（否则该断言无鉴别力）');
  }
});

t('★ 多词短语须显式告警：不加引号 ⇒ 站点按词包含匹配，召回可能过宽', () => {
  needQP();
  const { p } = qpRun(QP_EN, { terms: '膳食纤维' });
  assert.ok(p.plans.length > 0, '夹具须真产出式');
  assert.ok(p.plans.some(x => x.warnings.some(w => /引号/.test(w) && /宽|包含/.test(w))),
    '含空格短语却无「未加引号」告警：' + JSON.stringify(p.plans.map(x => [x.query, x.warnings])));
});

t('★ 空簇不臆造：clusters 为空 ⇒ 方案为空数组且不抛错', () => {
  needQP();
  const p = QP.buildQueryPlans([], { rows: [] });
  assert.deepStrictEqual(p.plans, []);
  assert.strictEqual(p.executed, false);
  assert.strictEqual(p.stationRequests, 0);
  const p2 = QP.buildQueryPlans(undefined, undefined);
  assert.deepStrictEqual(p2.plans, [], '缺参不得抛错，须返回空方案');
});

t('★ 物种粘连指纹必剪：`Canine chronic` / `猫膀胱` 不得进簇术语（否则式内自相矛盾）', () => {
  needDG();
  const en = dgRun(QP_EN, { terms: '膳食纤维' });
  assert.ok(en.clusters.length > 0, '夹具须真产生簇（否则剪枝断言是装饰）');
  const enTerms = en.clusters.reduce((a, c) => a.concat(c.terms.map(x => x.term)), []);
  assert.ok(!enTerms.some(x => /^(canine|feline)/i.test(x)),
    '物种前缀粘连未剪：' + JSON.stringify(enTerms));
  assert.ok(en.dropped.speciesGlue >= 1, '剪枝须留痕 dropped.speciesGlue，实际 '
    + JSON.stringify(en.dropped));
  const cn = dgRun(QP_CN, { terms: '肠道菌群' });
  const cnTerms = cn.clusters.reduce((a, c) => a.concat(c.terms.map(x => x.term)), []);
  assert.ok(cnTerms.length > 0, '中文夹具须真产生术语');
  assert.ok(!cnTerms.some(x => /^[猫犬狗]/.test(x)),
    '中文物种前缀粘连未剪：' + JSON.stringify(cnTerms) + '（应保留 `膀胱炎` 等纯主题词）');
});

t('★ 处方不得回流词表：iterate 的 terms 不受建议检索式影响（只在 --apply 通道改词表）', () => {
  needIT(); needQP();
  const r = IT.iterateRounds({
    groups: mkG(['A 肠道菌群', 'B 肠道菌群', 'A 膀胱炎与结石', 'B 膀胱炎与结石']),
    topicSpec: { terms: '肠道菌群' }, maxRounds: 2, batch: 3, minDf: 2,
  });
  assert.ok(r.diagnosis.queries, 'iterate 须挂 diagnosis.queries');
  assert.ok(r.diagnosis.queries.plans.length > 0,
    '夹具须真产出建议式（否则「不回流」是空断言）');
  const joined = r.terms.join(',');
  for (const x of r.diagnosis.queries.plans) {
    for (const t0 of x.terms) {
      assert.ok(!joined.includes(t0), '建议式的术语 ' + t0 + ' 不得自行并入词表：' + joined);
    }
    // ★ 同时钉住「iterate 必须把 topic 传给处方」：漏传时锚恒为空而式子照样产出 ⇒ 静默退化
    assert.strictEqual(x.anchorSource, 'topic',
      'iterate 未把主题词表传给处方（锚缺失 ⇒ 式子退化成「物种 × 维度大类」）：' + x.query);
    assert.ok(x.anchors.some(a => a === '肠道菌群'), '锚未取自词表：' + JSON.stringify(x.anchors));
  }
});

t('CLI：--species / --query-cap 解析；越界与缺值必须报错，且只换物种块、不动簇与术语', () => {
  assert.strictEqual(RK.parseArgs(['node', 's']).species, 'auto', '默认自动探测');
  assert.strictEqual(RK.parseArgs(['node', 's', '--species', 'cat']).species, 'cat');
  assert.strictEqual(RK.parseArgs(['node', 's', '--species', 'none']).species, 'none');
  assert.strictEqual(RK.parseArgs(['node', 's']).queryCap, 4, '默认术语上限 4');
  assert.strictEqual(RK.parseArgs(['node', 's', '--query-cap', '2']).queryCap, 2);
  const bad = (arr, needle) => {
    try { RK.parseArgs(['node', 's', ...arr]); }
    catch (e) {
      assert.ok(String(e.message).includes(needle), '错误信息应含 ' + needle + '，实际 ' + e.message);
      return;
    }
    throw new Error('应当抛错但未抛: ' + JSON.stringify(arr));
  };
  bad(['--species', 'rabbit'], '--species');
  bad(['--query-cap', '0'], '--query-cap');
  bad(['--query-cap', '9'], '--query-cap');       // 上限 8
  bad(['--species'], '--species');                // 缺值
  // 该参数只作用于「建议检索式」：换 species 必须换物种块，但**不得**改动簇与术语
  //   （否则会被当成主题参数误用 —— 它与 --topic 完全不同的东西）
  const a = qpRun(QP_CN, { terms: '肠道菌群' }, { species: 'cat' }).p;
  const b = qpRun(QP_CN, { terms: '肠道菌群' }, { species: 'dog' }).p;
  assert.notStrictEqual(a.plans.map(x => x.query).join('|'), b.plans.map(x => x.query).join('|'),
    'species 必须真的改变物种块（否则本用例区分不出「影响排序」与「影响式子」）');
  assert.deepStrictEqual(a.plans.map(x => [x.cluster, x.terms]),
    b.plans.map(x => [x.cluster, x.terms]), 'species 不得改变簇与术语（只换物种块）');
});

t('★ 术语去冗余：是另一术语真子串且非簇标签者剔除（OR 子串只会放宽召回）', () => {
  needQP();
  // 一手证据反演（2026-10-18 gutkidney 真实回放）：簇术语含 `Chronic` —— 它是 `Chronic Kidney`
  //   的子串，全局 df 却更高 ⇒ 极大剪枝按设计会**保留**短而通用的串；但写进 OR 后
  //   「题名含 Chronic 即命中」，把式子直接稀释掉。故在处方层剔除。
  const p = QP.buildQueryPlans([{
    kind: 'new-dimension', label: 'Kidney', support: 5, confidence: 'strong',
    terms: [{ term: 'Kidney' }, { term: 'Chronic Kidney' }, { term: 'Chronic' }, { term: 'Axis' }],
  }], { species: 'both' });
  const x = p.plans.filter(z => z.lang === 'en')[0];
  assert.ok(x, '夹具须产出英文式');
  assert.ok(x.terms.indexOf('Chronic') < 0, '子串冗余未剔除：' + JSON.stringify(x.terms));
  assert.ok(x.terms.indexOf('Kidney') >= 0,
    '簇标签虽是子串也必须保留（剔掉就丢靶心）：' + JSON.stringify(x.terms));
  assert.ok(x.terms.indexOf('Chronic Kidney') >= 0, '父串不得被误剔：' + JSON.stringify(x.terms));
  assert.ok(x.terms.indexOf('Axis') >= 0, '与其它术语无包含关系者不得被剔：' + JSON.stringify(x.terms));
  assert.strictEqual(p.droppedRedundant, 1, '须留痕 droppedRedundant，实际 ' + p.droppedRedundant);
});

t('★ 确定性：同输入两次调用深等（键序稳定，可作基线）', () => {
  needQP();
  const a = qpRun(QP_CN.concat(QP_EN), { terms: '肠道菌群' }).p;
  const b = qpRun(QP_CN.concat(QP_EN), { terms: '肠道菌群' }).p;
  assert.strictEqual(JSON.stringify(a), JSON.stringify(b), '方案须确定（禁依赖 Map 插入顺序）');
});

t('★ 渲染与 JSON：方案须同时进 md 与 JSON，且显式标注「未执行 / 待人工复核」', () => {
  needIT(); needQP();
  const r = IT.iterateRounds({
    groups: mkG(['A 肠道菌群', 'B 肠道菌群', 'A 膀胱炎与结石', 'B 膀胱炎与结石']),
    topicSpec: { terms: '肠道菌群' }, maxRounds: 2, batch: 3, minDf: 2,
  });
  const md = RK.renderIterateReport(r, {});
  assert.ok(/建议检索式/.test(md), 'md 未输出建议检索式小节');
  assert.ok(/未执行|未实测/.test(md), 'md 未声明「未执行」');
  assert.ok(/复核|人工确认/.test(md), 'md 未要求人工复核');
  // ★ 必须走 `compactIterate`（CLI 的真实序列化路径）：它逐字段白名单挑选，
  //   直接喂原始对象会绕过白名单 ⇒ 线上缺字段而用例全绿（2026-10-18 实测踩过）。
  const j = JSON.parse(RK.renderJson(REL.rankAll(mkG(['A 肠道菌群']), REL.buildTopic({ terms: '肠道菌群' })),
    { iterateReport: RK.compactIterate(r) }));
  assert.ok(j.iterate && j.iterate.diagnosis && j.iterate.diagnosis.queries,
    'JSON 缺 iterate.diagnosis.queries');
  assert.strictEqual(j.iterate.diagnosis.queries.executed, false);
  assert.ok(j.iterate.diagnosis.queries.plans.length > 0, 'JSON 方案为空');
});

// ---------- 维度收敛判据（2026-10-18） ----------
// 动因：`diagnose` 只答「**这一轮**缺哪个维度」，于是同一维度会在每份报告里像**新发现**一样
//   再出现一次，support 每次都是新的绝对值 —— 人看不出它是「还在」「在缩」还是「卡死」。
//   缺的判据：**簇消失**（support 落到最小支持数以下 / 记录已升档）才算该维度收敛。
console.log('维度收敛判据（收敛 = 簇消失 或 support 低于阈值）:');

const CV = (() => { try { return require('./lib/convergence.cjs'); } catch (e) { return null; } })();
const needCV = () => assert.ok(CV && typeof CV.trackClusters === 'function',
  '缺 lib/convergence.cjs 的 trackClusters');
const cvCl = (key, support, kind) => ({ key, label: key, kind: kind || 'new-dimension', support });
const cvObs = (round, clusters, extra) => Object.assign({
  round, clusters, clustersTotal: clusters.length, residualTotal: null,
}, extra || {});
/** 夹具 A：五态齐活（stalled / grew / shrinking / resolved×2 / emerged），无簇上限风险 */
const CV_A = [
  cvObs(0, [cvCl('A1', 5), cvCl('A2', 4), cvCl('A3', 6), cvCl('A4', 4)], { residualTotal: 19 }),
  cvObs(1, [cvCl('A1', 5), cvCl('A2', 4), cvCl('A3', 3), cvCl('A4', 4), cvCl('A5', 2)],
    { residualTotal: 18 }),
  cvObs(2, [cvCl('A1', 5), cvCl('A2', 6), cvCl('A3', 2), cvCl('A6', 2)], { residualTotal: 15 }),
];
/** 夹具 B：末轮簇数 > 上报簇数（有簇被上限截掉）⇒ 消失不可信 */
const CV_B = [
  cvObs(0, [cvCl('B1', 3), cvCl('B2', 3)], { residualTotal: 6 }),
  cvObs(1, [cvCl('B1', 3)], { clustersTotal: 2, residualTotal: 4 }),
];
/** 夹具 C：全 stalled（唯一可判「已收敛」的形态） */
const CV_C = [
  cvObs(0, [cvCl('C1', 4)], { residualTotal: 6 }),
  cvObs(1, [cvCl('C1', 4)], { residualTotal: 4 }),
];

t('★ 收敛判据是纯函数：零网络/零文件/零子进程，判据标识落成常量（不靠注释口头约定）', () => {
  needCV();
  const src = fs.readFileSync(path.join(__dirname, 'lib', 'convergence.cjs'), 'utf8');
  for (const bad of ["require('https')", 'require("https")', "require('http')", 'require("http")',
    "require('fs')", 'require("fs")', 'child_process', 'XMLHttpRequest', 'fetch(']) {
    assert.ok(!src.includes(bad), 'convergence.cjs 不得含 ' + bad + '（纯函数模块）');
  }
  assert.ok(/const CRITERION = 'cluster-absent-or-below-min-support'/.test(src),
    '判据标识必须是模块常量（报告与 JSON 都要能读出「用的是哪条判据」）');
  const r = CV.trackClusters(CV_C);
  assert.strictEqual(r.criterion, 'cluster-absent-or-below-min-support');
  assert.strictEqual(r.version, 'dim-convergence/v1');
});

t('★ 六态穷举自证：两份夹具合起来必须产出全部六种状态，且落对键（少一种即分支不可达）', () => {
  needCV();
  const stOf = fx => {
    const m = {};
    CV.trackClusters(fx).clusters.forEach(c => { m[c.key] = c.status; });
    return m;
  };
  const sa = stOf(CV_A);
  const sb = stOf(CV_B);
  assert.strictEqual(sa.A1, 'stalled', 'A1 support 5→5→5 应 stalled，实际 ' + sa.A1);
  assert.strictEqual(sa.A2, 'grew', 'A2 4→4→6 应 grew，实际 ' + sa.A2);
  assert.strictEqual(sa.A3, 'shrinking', 'A3 6→3→2 应 shrinking，实际 ' + sa.A3);
  assert.strictEqual(sa.A4, 'resolved', 'A4 末轮缺席应 resolved，实际 ' + sa.A4);
  assert.strictEqual(sa.A5, 'resolved', 'A5 只出现 1 轮后缺席应 resolved，实际 ' + sa.A5);
  assert.strictEqual(sa.A6, 'emerged', 'A6 仅末轮出现应 emerged，实际 ' + sa.A6);
  assert.strictEqual(sb.B2, 'capped', 'B2 在簇上限截断后缺席应 capped，实际 ' + sb.B2);
  const got = new Set(Object.values(sa).concat(Object.values(sb)));
  const all = Object.keys(CV.STATUS).map(k => CV.STATUS[k]);
  assert.strictEqual(got.size, all.length, '夹具未覆盖全部 ' + all.length + ' 态，实际 ' + got.size);
  all.forEach(s => assert.ok(got.has(s), '状态 ' + s + ' 无夹具覆盖 ⇒ 该分支从未被验证'));
});

t('★ 诊断须暴露簇总数：`clustersTotal` / `droppedByCap` 是「被上限挤出」的唯一线索（缺了它 capped 判不出来）', () => {
  // 一手动因：诊断层 `shown = clusters.slice(0, maxClusters)`，被截掉的簇**既不进 clusters
  //   也不进 unclustered**（记录已 assigned）⇒ 外部无法区分「真消失」与「被挤出」。
  const titles = ['Feline bladder inflammation stone alpha', 'Canine bladder inflammation stone beta',
    'Feline thyroid hormone excess gamma', 'Canine thyroid hormone excess delta',
    'Feline pancreas enzyme deficiency epsilon', 'Canine pancreas enzyme deficiency zeta',
    'Feline joint cartilage supplement eta', 'Canine joint cartilage supplement theta'];
  const r = REL.rankAll(mkG(titles), REL.buildTopic({ terms: 'gut microbiota' }));
  const a = DG.diagnoseResidual(r.ranked, r.topic, { maxClusters: 1 });
  const b = DG.diagnoseResidual(r.ranked, r.topic, { maxClusters: 10 });
  assert.ok(b.clustersTotal >= 2, '夹具须真产出 ≥2 簇，实际 ' + b.clustersTotal);
  assert.strictEqual(a.clustersTotal, b.clustersTotal, '簇总数不得随上报上限变化（否则 capped 判据失真）');
  assert.strictEqual(a.clusters.length, 1, 'maxClusters=1 时只应上报 1 簇');
  assert.strictEqual(a.droppedByCap, a.clustersTotal - 1, 'droppedByCap 与实际截断数不符');
  assert.strictEqual(b.droppedByCap, 0);
});

t('★ 收敛判定：`converged` 等价于「无 capped 且存活簇全 stalled」（有任一维度还在变就不算收敛）', () => {
  needCV();
  const c = CV.trackClusters(CV_C);
  assert.strictEqual(c.state, 'converged');
  assert.strictEqual(c.converged, true);
  assert.strictEqual(c.live, 1);
  assert.strictEqual(CV.trackClusters(CV_A).state, 'active', '有 grew/emerged 不得判收敛');
  assert.strictEqual(CV.trackClusters(CV_B).state, 'inconclusive');
  // 等价式逐夹具核对（判据只写一次，防止注释与实现漂移）
  for (const fx of [CV_A, CV_B, CV_C]) {
    const r = CV.trackClusters(fx);
    const eq = r.cappedCount === 0
      && r.clusters.filter(x => x.status !== 'resolved').every(x => x.status === 'stalled');
    assert.strictEqual(r.converged, r.observations >= 2 && eq,
      'converged 与等价式不符（state=' + r.state + '）');
    assert.strictEqual(r.converged, r.state === 'converged', 'converged 布尔与 state 不一致');
  }
});

t('★ 观测不足 2 轮 ⇒ `insufficient`：不得把「看不出趋势」报成收敛', () => {
  needCV();
  const r = CV.trackClusters([cvObs(0, [cvCl('X', 3)], { residualTotal: 3 })]);
  assert.strictEqual(r.state, 'insufficient');
  assert.strictEqual(r.converged, false);
  assert.strictEqual(r.observations, 1);
  assert.ok(/看不出|不足/.test(r.note), 'note 未说明「看不出趋势」：' + r.note);
  const z = CV.trackClusters([]);
  assert.strictEqual(z.state, 'insufficient', '空输入不得报收敛');
  assert.deepStrictEqual(z.clusters, []);
  assert.strictEqual(z.converged, false);
});

t('★ `capped` 不得计入收敛：簇数超上报上限时，「真消失」与「被挤出」不可区分', () => {
  needCV();
  const r = CV.trackClusters(CV_B);
  assert.strictEqual(r.cappedCount, 1);
  assert.strictEqual(r.state, 'inconclusive');
  assert.strictEqual(r.converged, false);
  assert.ok(/上限/.test(r.note), 'note 未点明上限截断：' + r.note);
  // ★ 反证（同一数据、只放开簇上限）：B2 必须从 capped 变 resolved ⇒ 证明该闸真在起作用
  const fixed = CV_B.map(x => Object.assign({}, x, { clustersTotal: x.clusters.length }));
  const r2 = CV.trackClusters(fixed);
  assert.strictEqual(r2.clusters.find(c => c.key === 'B2').status, 'resolved');
  assert.notStrictEqual(r2.state, 'inconclusive');
});

t('★ 残差为 0 判收敛（没有维度需要收敛），不得因「追踪键 0 个」报无法判定', () => {
  needCV();
  const r = CV.trackClusters([cvObs(0, [], { residualTotal: 0 }), cvObs(1, [], { residualTotal: 0 })]);
  assert.strictEqual(r.state, 'converged');
  assert.strictEqual(r.converged, true);
  assert.strictEqual(r.live, 0);
  assert.strictEqual(r.clusters.length, 0);
  // ★ 「没有维度」≠「残差为 0」：10 条残差归不出维度时，结论必须指向「逐条判读」，
  //   不得让 state=converged 被读成「残差已覆盖」（no-shared-terms 的真实语义）。
  const nr = CV.trackClusters([cvObs(0, [], { residualTotal: 10 }),
    cvObs(1, [], { residualTotal: 10 })]);
  assert.strictEqual(nr.state, 'converged');
  assert.ok(/逐条人工判读/.test(nr.note), '残差非 0 却无维度时，note 未要求逐条判读：' + nr.note);
});

t('★ 残差规模不变量：正常序列为真；构造上升必须报 false（判据不得恒真）；null 不得当 0', () => {
  needCV();
  assert.strictEqual(CV.trackClusters(CV_A).residualMonotonic, true);
  const bad = [cvObs(0, [], { residualTotal: 5 }), cvObs(1, [], { residualTotal: 7 })];
  assert.strictEqual(CV.trackClusters(bad).residualMonotonic, false,
    '上升序列未被识别 ⇒ 不变量判据失效');
  // null 若被当成 0，则 5 → 0 → 3 会误报「上升」；正确行为是跳过缺失项
  const mixed = [cvObs(0, [], { residualTotal: 5 }), cvObs(1, [], { residualTotal: null }),
    cvObs(2, [], { residualTotal: 3 })];
  assert.strictEqual(CV.trackClusters(mixed).residualMonotonic, true, 'null 被当成 0 参与了比较');
});

t('★ 无键簇不臆造：既缺 key 又缺 label 的簇被跳过（不得生成空键把无关簇并成一簇）', () => {
  needCV();
  const r = CV.trackClusters([
    cvObs(0, [{ kind: 'new-dimension', support: 3 }, cvCl('OK', 3)]),
    cvObs(1, [{ kind: 'new-dimension', support: 3 }, cvCl('OK', 3)]),
  ]);
  assert.strictEqual(r.clusters.length, 1);
  assert.strictEqual(r.clusters[0].key, 'OK');
});

t('★ 类型变化留痕：同键 axis-extend → new-dimension 必须标 kindChanged（语义不同，不得静默合并）', () => {
  needCV();
  const a = CV.trackClusters([cvObs(0, [cvCl('K', 3, 'axis-extend')]),
    cvObs(1, [cvCl('K', 3, 'new-dimension')])]);
  assert.strictEqual(a.clusters[0].kindChanged, true);
  assert.strictEqual(a.clusters[0].kind, 'new-dimension', '类型须以最新观测为准');
  const b = CV.trackClusters([cvObs(0, [cvCl('K', 3)]), cvObs(1, [cvCl('K', 3)])]);
  assert.strictEqual(b.clusters[0].kindChanged, false, '类型未变却标了 kindChanged');
});

t('★ annotateClusters：只贴状态、不改入参；未追踪到 ⇒ status=null（不臆造「已收敛」）', () => {
  needCV();
  const conv = CV.trackClusters(CV_A);
  const src = [{ key: 'A1', label: 'A1', kind: 'new-dimension', support: 5 },
    { key: 'ZZ', label: 'ZZ', kind: 'new-dimension', support: 2 }];
  const out = CV.annotateClusters(src, conv);
  assert.strictEqual(out[0].status, 'stalled');
  assert.ok(out[0].supportSeries.length >= 3, 'supportSeries 未贴上');
  assert.strictEqual(out[0].stallRounds, 2, '连续未降跨度应为 2');
  assert.strictEqual(out[1].status, null);
  assert.strictEqual(src[0].status, undefined, 'annotateClusters 改了入参（须为纯映射）');
});

t('★ iterate 集成：观测数 = 1 + 真补过词的轮数（空转轮不得计观测），且轮次连续', () => {
  needIT(); needCV();
  // ★ 夹具必须**真补词**：初版用「主题词 + 跑题词」的语料，候选为 0 ⇒ appended 为空、
  //   观测数恒为 1 ⇒ 「观测数 = 1 + 补词轮数」两边都等于 1，断言退化为装饰（实测踩到，M11 假盲区）。
  const r = IT.iterateRounds({
    groups: mkG(['A 肠道菌群紊乱', 'B 肠道菌群紊乱', 'C 膀胱炎结石', 'D 膀胱炎结石']),
    topicSpec: { terms: '肠道菌群' }, maxRounds: 3, batch: 3, minDf: 2,
  });
  const appended = r.rounds.filter(x => x.appended.length > 0).length;
  assert.ok(appended > 0, '夹具未真正补词（否则本用例是空断言）');
  assert.ok(r.convergence, 'iterateRounds 须挂 convergence');
  assert.strictEqual(r.convergence.observations, appended + 1,
    '观测数须 = 起始轮 1 + 真补词轮 ' + appended);
  const wantRounds = [0].concat(r.rounds.filter(x => x.appended.length > 0).map(x => x.n));
  assert.deepStrictEqual(r.convergence.rounds, wantRounds, '观测轮次不连续或有空转轮混入');
  // 追踪到的键必须真出自某一轮诊断（不得凭空造维度）
  const seen = new Set();
  r.convergence.clusters.forEach(c => {
    assert.ok(c.supportSeries.length <= r.convergence.observations, 'supportSeries 长于观测数');
    assert.ok(!seen.has(c.key), '同一键被重复追踪：' + c.key);
    seen.add(c.key);
  });
  // ★ 核心用途：残差里的「膀胱炎结石」簇两轮 support 不变 ⇒ stalled（不是「新发现」）
  const st = r.convergence.clusters.filter(c => c.status === 'stalled');
  assert.strictEqual(st.length, 1, '应恰有 1 个 stalled 簇，实际 ' + JSON.stringify(r.convergence.clusters.map(c => c.status)));
  assert.deepStrictEqual(st[0].supportSeries, [2, 2], 'stalled 簇 support 序列不符');
  assert.strictEqual(st[0].stallRounds, 1);
  assert.strictEqual(r.convergence.state, 'converged', '全 stalled ⇒ 已收敛');
  // 诊断簇的状态必须与 convergence 一致（annotate 贴回路径）
  r.diagnosis.clusters.forEach(c => {
    const t0 = r.convergence.clusters.find(x => x.key === c.key);
    assert.strictEqual(c.status, t0 ? t0.status : null, '诊断簇状态未按 convergence 贴回：' + c.key);
  });
});

t('★ 单轮即停 ⇒ `insufficient`：不得因「没变化」在报告里暗示已收敛', () => {
  needIT(); needCV();
  const r = IT.iterateRounds({
    groups: mkG(['肾脏疾病诊断', '肾脏疾病治疗']),
    topicSpec: { terms: '肾脏疾病' }, minDf: 2,
  });
  assert.strictEqual(r.stopReason, 'no-candidates');
  assert.strictEqual(r.convergence.observations, 1);
  assert.strictEqual(r.convergence.state, 'insufficient');
  assert.strictEqual(r.convergence.converged, false);
  const md = RK.renderIterateReport(r, {});
  assert.ok(/观测不足/.test(md), 'md 未声明「观测不足」⇒ 读者会误当已收敛');
  assert.ok(!/\*\*已收敛\*\*（`converged`）/.test(md), 'md 在观测不足时不得出现「已收敛」结论');
});

t('★ JSON 通道（走 compactIterate 白名单）：必须含 convergence 与诊断簇的 status 字段', () => {
  needIT(); needCV();
  // 夹具同上游成用例：必须真补过词，收敛簇才非空
  const r = IT.iterateRounds({
    groups: mkG(['A 肠道菌群紊乱', 'B 肠道菌群紊乱', 'C 膀胱炎结石', 'D 膀胱炎结石']),
    topicSpec: { terms: '肠道菌群' }, maxRounds: 2, batch: 3, minDf: 2,
  });
  assert.ok(r.convergence.clusters.length > 0, '夹具须真产出收敛簇（否则 clusters 断言是空真值）');
  const j = JSON.parse(RK.renderJson(
    REL.rankAll(mkG(['A 肠道菌群']), REL.buildTopic({ terms: '肠道菌群' })),
    { iterateReport: RK.compactIterate(r) }));
  const cv = j.iterate.convergence;
  assert.ok(cv, 'JSON 缺 iterate.convergence（白名单漏字段）');
  assert.strictEqual(cv.criterion, 'cluster-absent-or-below-min-support');
  assert.strictEqual(typeof cv.converged, 'boolean');
  assert.strictEqual(typeof cv.state, 'string');
  assert.ok(Array.isArray(cv.clusters), 'JSON convergence.clusters 非数组');
  assert.ok(cv.clusters.length > 0, 'JSON 收敛簇为空（夹具须真产出维度）');
  assert.ok(cv.clusters.every(c => Object.values(CV.STATUS).indexOf(c.status) >= 0),
    'JSON 收敛簇状态不在六态之内：' + JSON.stringify(cv.clusters.map(c => c.status)));
  assert.ok(j.iterate.diagnosis.clusters.every(c => 'status' in c), '诊断簇缺 status 字段');
  assert.ok(j.iterate.diagnosis.clusters.every(c => 'stallRounds' in c), '诊断簇缺 stallRounds 字段');
});

t('★ 处方透传维度状态：stalled 追加「补词治不了」告警；未追踪 ⇒ null（不臆造）', () => {
  needQP(); needCV();
  const rows = REL.rankAll(mkG(QP_EN), REL.buildTopic({ terms: 'gut microbiota' }));
  const d = DG.diagnoseResidual(rows.ranked, rows.topic, {});
  assert.ok(d.clusters.length > 0, '夹具须真聚出维度（否则本用例是空断言）');
  const stalled = d.clusters.map(c => Object.assign({}, c,
    { status: 'stalled', stallRounds: 2, persistRounds: 3 }));
  const p1 = QP.buildQueryPlans(stalled, { rows: rows.ranked, topic: rows.topic });
  assert.ok(p1.plans.length > 0, '夹具须产出检索式');
  assert.ok(p1.plans.every(x => x.clusterStatus === 'stalled'), '状态未透传到方案');
  assert.ok(p1.plans.every(x => x.warnings.some(w => /补词治不了/.test(w))),
    'stalled 维度未追加「补词治不了」告警');
  const p2 = QP.buildQueryPlans(d.clusters, { rows: rows.ranked, topic: rows.topic });
  assert.ok(p2.plans.every(x => x.clusterStatus === null), '未追踪却给了状态（臆造）');
  assert.ok(p2.plans.every(x => !x.warnings.some(w => /补词治不了/.test(w))));
});

t('★ 报告渲染：收敛追踪小节须含判据标识 + stalled 文案 + support 序列', () => {
  needCV();
  const fake = {
    pick: 'all', batch: 5, maxRounds: 2, stationRequests: 0,
    baseline: { stat: { exact: 0 }, total: 10, exactRate: 0 },
    stopReason: 'no-gain', stopDetail: '第 1 轮补入 1 词，主题命中数未增加（仍 0）',
    saturationRound: 1, totalAppended: 1, totalGain: 0,
    final: { stat: { exact: 0 }, total: 10, exactRate: 0 },
    terms: ['肠道菌群'],
    rounds: [{ n: 1, appended: ['x'], deferred: [], stat: { exact: 0 }, exactRate: 0,
      deltaExact: 0, downgraded: 0, candidatesSeen: 3 }],
    residual: [], diagnosis: null,
    convergence: CV.trackClusters(CV_C),
  };
  const md = RK.renderIterateReport(fake, {});
  assert.ok(/维度收敛追踪/.test(md), 'md 未输出收敛追踪小节');
  assert.ok(md.includes('cluster-absent-or-below-min-support'), 'md 未写判据标识');
  assert.ok(/已收敛/.test(md), 'md 未给收敛结论');
  assert.ok(/卡住（`stalled`）/.test(md), 'md 未标注 stalled 状态');
  assert.ok(/补词治不了/.test(md), 'md 未说明 stalled 维度补词治不了');
  assert.ok(/4 → 4/.test(md), 'md 未展示 support 序列');
});

// ---------- 跨运行收敛记忆（2026-10-18） ----------
// 动因：`convergence` 的追踪只活在**单次运行内**。跨运行它就失明了 —— 同一个维度今天 `stalled`、
//   明天还是 `stalled`，每份报告都重写一遍、建议检索式也重给一遍 ⇒ 读到第三遍就没人读了。
//   需要跨运行区分的是：这次才发现 / 上次报过结论没变 / 上次判过收敛又回来 / 真的消失了。
// ★ 唯一不可让步的闸门：主题词表变了 ⇒ **拒绝合并**（不同词表 = 不同问题定义，
//   沿用旧结论会造出「这个方向已经查过」的假记忆）。
console.log('跨运行收敛记忆（同一维度只正经报一次）:');

const CSG = (() => { try { return require('./lib/converge-state.cjs'); } catch (e) { return null; } })();
const AW = (() => { try { return require('./lib/atomic-write.cjs'); } catch (e) { return null; } })();
const needCSG = () => assert.ok(CSG && typeof CSG.mergePrior === 'function',
  '缺 lib/converge-state.cjs 的 mergePrior');
const csIn = data => ({ exists: true, data, error: null });
const csCl = (key, status, support) => ({
  key, label: key, kind: 'new-dimension', status, support, supportSeries: [support],
});
/**
 * v1 历史状态文件（**单主题**平铺格式）。
 * ★ 版本必须写**字面量**，不能用 `CSG.VERSION` —— 否则升版那一刻，所有「v1 夹具」会
 *   悄悄变成「v2 但平铺」的非法数据，旧用例全体红且红得莫名其妙（2026-10-19 实测踩到）。
 */
const V1FS = 'dim-converge-state/v1';
const csFile = (topic, clusters, extra) => Object.assign({
  version: V1FS, savedAt: '2026-10-17T00:00:00Z', runs: 1,
  criterion: CSG.CRITERION, state: 'converged',
  fingerprint: { topic: CSG.canonTopic(topic), hash: CSG.fingerprintOf({ topic }).hash, corpus: 10, pick: 'all' },
  clusters,
}, extra || {});

t('首次运行（状态文件不存在）⇒ status=none，不报错、不合并（不是「拒绝」）', () => {
  needCSG();
  const p = CSG.readPrior({ exists: false, data: null, error: null }, CSG.fingerprintOf({ topic: 'a,b' }));
  assert.strictEqual(p.status, CSG.PRIOR.NONE);
  assert.strictEqual(p.clusters.length, 0);
  assert.ok(/首次运行/.test(p.reason), '首次运行的说明缺失');
});

t('★ 换词表 ⇒ 不得复用旧结论（按首次处理），且**旧槽写回后仍保留**（记忆不互删）', () => {
  needCSG();
  const old = csFile('肠肾轴,肠道菌群', [csCl('Kidney', 'stalled', 5)]);
  const fp = CSG.fingerprintOf({ topic: '毛球,化毛', corpus: 10 });
  const p = CSG.readPrior(csIn(old), fp);
  assert.strictEqual(p.status, CSG.PRIOR.NONE, '换词表却复用了旧结论（会造「查过」的假记忆）');
  assert.strictEqual(p.clusters.length, 0, '不得带出任何其他主题的历史簇');
  assert.strictEqual(p.otherSlots, 1, '未标明文件里还有别的主题');
  // ★ 写回：旧槽必须仍在 —— v1 时代这里会被整体覆盖，等于换一次词表就啃掉一段记忆
  const built = CSG.buildState({
    cross: { clusters: [], runs: 1 },
    convergence: { state: 'converged', observations: 2 },
    fingerprint: fp, now: new Date('2026-10-19T00:00:00Z'), prevFile: old,
  });
  assert.strictEqual(built.state.slots.length, 2, '换主题后旧槽被覆盖（记忆互删）');
  assert.ok(built.state.slots.some(s => (s.clusters || []).some(c => c.key === 'Kidney')),
    '旧主题的 Kidney 结论丢失');
});

t('词表**顺序**不同不算换主题（规范化后比对）；语料规模变化只告警、不拒绝', () => {
  needCSG();
  // 顺序不同：同一组词换个写法 ⇒ 必须合并
  const same = csFile('肠道菌群,肠肾轴', [csCl('Kidney', 'stalled', 5)]);
  const p1 = CSG.readPrior(csIn(same), CSG.fingerprintOf({ topic: '肠肾轴,肠道菌群', corpus: 10 }));
  assert.strictEqual(p1.status, CSG.PRIOR.OK, '只是词序不同却被判成换主题');
  // 语料变了：新增文献是正常演进 ⇒ 合并且标记
  const p2 = CSG.readPrior(csIn(same), CSG.fingerprintOf({ topic: '肠肾轴,肠道菌群', corpus: 48 }));
  assert.strictEqual(p2.status, CSG.PRIOR.OK, '语料规模变化不该拒绝合并');
  assert.strictEqual(p2.corpusChanged, true, '语料变化未标记（support 变动会被误读成补词效果）');
});

t('版本不符 / 文件损坏 ⇒ 拒绝或按损坏处理，且**一律不合并**、不崩', () => {
  needCSG();
  const fp = CSG.fingerprintOf({ topic: 'a,b' });
  const bad = CSG.readPrior(csIn(csFile('a,b', [csCl('X', 'stalled', 2)], { version: 'nope/v0' })), fp);
  assert.strictEqual(bad.status, CSG.PRIOR.REJECTED);
  assert.strictEqual(bad.clusters.length, 0);
  const broken = CSG.readPrior({ exists: true, data: null, error: 'Unexpected token <' }, fp);
  assert.strictEqual(broken.status, CSG.PRIOR.CORRUPT);
  assert.strictEqual(broken.clusters.length, 0);
  assert.ok(/无法解析/.test(broken.reason));
});

t('★ 五态穷举且互斥：new / persistent / resolved / cleared / recurred 各归各位', () => {
  needCSG();
  const prior = CSG.readPrior(csIn(csFile('t', [
    csCl('K1', 'stalled', 5),      // 上次活着 → 本次还活着且 support 未变
    csCl('K2', 'stalled', 3),      // 上次活着 → 本次末轮缺席（本次出现过）
    csCl('K3', 'stalled', 4),      // 上次活着 → 本次连出现都没有
    csCl('K4', 'resolved', 2),     // 上次已收敛 → 本次又活着（真回归）
    csCl('K6', 'resolved', 3),     // ★ 上次已收敛 → 本次**也判 resolved**（仍收敛，不是回归）
  ])), CSG.fingerprintOf({ topic: 't' }));
  const now = [csCl('K1', 'stalled', 5), csCl('K2', 'resolved', 3),
    csCl('K4', 'stalled', 2), csCl('K5', 'stalled', 3), csCl('K6', 'resolved', 3)];
  const cr = CSG.mergePrior(now, prior);
  const tr = {};
  cr.clusters.forEach(c => { tr[c.key] = c.trend; });
  assert.strictEqual(tr.K1, CSG.TREND.PERSISTENT, 'K1 应为沿续');
  assert.strictEqual(tr.K2, CSG.TREND.RESOLVED, 'K2 应为刚收敛');
  assert.strictEqual(tr.K3, CSG.TREND.CLEARED, 'K3 应为消失（历史有、本次没有）');
  assert.strictEqual(tr.K4, CSG.TREND.RECURRED, 'K4 应为回归（上次判过收敛又出现）');
  assert.strictEqual(tr.K5, CSG.TREND.NEW, 'K5 应为首次');
  // ★ 本次**也**判 resolved ⇒ 仍然是收敛，不是回归（真实语料 2026-10-18 打出的假阳性：
  //   「本次末轮缺席」被当成了「又出现」，报告里凭空多出 2 条「回归」警示）
  assert.strictEqual(tr.K6, CSG.TREND.CLEARED, 'K6 两次都 resolved 却被判成回归');
  // 穷举：五态合计必须等于条目总数（不得有「说不清」的簇）
  const sum = Object.values(cr.summary).reduce((a, b) => a + b, 0) - cr.summary.suppressed;
  assert.strictEqual(sum, cr.clusters.length, '五态合计 ≠ 条目数（有簇未归位）');
});

t('★ 历史有、本次没有的维度**必须出现在结果里**（否则「上次报的没了」静默消失）', () => {
  needCSG();
  const prior = CSG.readPrior(csIn(csFile('t', [csCl('Gone', 'stalled', 4)])),
    CSG.fingerprintOf({ topic: 't' }));
  const cr = CSG.mergePrior([], prior);
  assert.strictEqual(cr.clusters.length, 1, '本次零簇时历史簇被整批丢掉');
  assert.strictEqual(cr.clusters[0].key, 'Gone');
  assert.strictEqual(cr.clusters[0].trend, CSG.TREND.CLEARED);
  assert.strictEqual(cr.clusters[0].status, null, '本次未出现的维度不得臆造 status');
});

t('reportCount / runs 跨运行累加（抑制判据依赖它，不能每轮从 1 重数）', () => {
  needCSG();
  const fp = CSG.fingerprintOf({ topic: 't' });
  const f1 = csFile('t', [csCl('K', 'stalled', 5)], { runs: 1,
    clusters: [{ key: 'K', label: 'K', kind: 'new-dimension', status: 'stalled',
      support: 5, reportCount: 1, supportSeries: [5, 5] }] });
  const p1 = CSG.readPrior(csIn(f1), fp);
  assert.strictEqual(p1.runs, 1);
  const c1 = CSG.mergePrior([csCl('K', 'stalled', 5)], p1);
  assert.strictEqual(c1.runs, 2, 'runs 未累加');
  assert.strictEqual(c1.clusters[0].reportCount, 2, 'reportCount 未累加');
  // 第二轮：把上一轮写回的状态再读一次 ⇒ 继续累加（不是回到 1）
  const f2 = csFile('t', [], { runs: c1.runs, clusters: [{
    key: 'K', label: 'K', kind: 'new-dimension', status: 'stalled',
    support: 5, reportCount: c1.clusters[0].reportCount, supportSeries: [5, 5, 5] }] });
  const c2 = CSG.mergePrior([csCl('K', 'stalled', 5)], CSG.readPrior(csIn(f2), fp));
  assert.strictEqual(c2.runs, 3);
  assert.strictEqual(c2.clusters[0].reportCount, 3);
});

t('★ 抑制判据三条缺一不可：persistent + stalled + 报过 ≥2 次（结论变了要重报）', () => {
  needCSG();
  const base = { trend: CSG.TREND.PERSISTENT, status: 'stalled', reportCount: 2 };
  assert.strictEqual(CSG.shouldSuppress(base), true, '三条齐全却不抑制');
  assert.strictEqual(CSG.shouldSuppress(Object.assign({}, base, { reportCount: 1 })), false,
    '首次就抑制 ⇒ 用户拿不到式子');
  assert.strictEqual(CSG.shouldSuppress(Object.assign({}, base, { status: 'shrinking' })), false,
    'support 在降（结论在变）却抑制');
  assert.strictEqual(CSG.shouldSuppress(Object.assign({}, base, { trend: CSG.TREND.RECURRED })), false,
    '回归维度被抑制 ⇒ 警示被吞掉');
  assert.strictEqual(CSG.shouldSuppress(Object.assign({}, base, { trend: CSG.TREND.NEW })), false,
    '首次维度被抑制');
  assert.strictEqual(CSG.shouldSuppress(null), false, '空输入不得判为抑制');
});

t('★ 抑制真落到建议检索式：不出式，但必须显式记入 suppressed（不静默）', () => {
  needCSG(); needQP();
  const cl = {
    key: 'kidney', label: 'Kidney', kind: 'new-dimension',
    terms: [{ term: 'Kidney' }, { term: 'Kidney Disease' }],
    support: 5, status: 'stalled', suppress: true, reportCount: 2,
  };
  const qp1 = QP.buildQueryPlans([cl], { topic: { terms: ['肠肾轴', '肠道菌群'] }, species: 'none' });
  assert.strictEqual(qp1.plans.length, 0, '抑制的维度仍出了式子');
  assert.strictEqual(qp1.suppressed.length, 1, '抑制未记入 suppressed（等于静默丢弃）');
  assert.strictEqual(qp1.suppressed[0].reason, 'repeated-stalled');
  // 对照：不抑制时同一簇必须出式（证明抑制是唯一差异，不是簇本身不可用）
  const qp2 = QP.buildQueryPlans([Object.assign({}, cl, { suppress: false })],
    { topic: { terms: ['肠肾轴', '肠道菌群'] }, species: 'none' });
  assert.ok(qp2.plans.length > 0, '对照组也不出式 ⇒ 夹具本身有问题');
  assert.strictEqual(qp2.suppressed.length, 0);
});

t('★ 跨运行只在显式传 priorFile 时生效：不传 ⇒ crossRun/stateNext 均为 null（零回归）', () => {
  needIT(); needCSG();
  const r = IT.iterateRounds({
    groups: mkG(['A 肠道菌群紊乱', 'B 肠道菌群紊乱', 'C 膀胱炎结石', 'D 膀胱炎结石']),
    topicSpec: { terms: '肠道菌群' }, maxRounds: 2, batch: 3, minDf: 2,
  });
  assert.strictEqual(r.crossRun, null, '未传 priorFile 却产出了跨运行结论');
  assert.strictEqual(r.stateNext, null, '未传 priorFile 却产出了待写状态');
  assert.ok(r.convergence, '单次运行内追踪不得因此消失');
});

t('★ 端到端：传 priorFile ⇒ 簇被贴 trend/suppress，且 JSON 通道（compactIterate）字段齐全', () => {
  needIT(); needCSG();
  const groups = mkG(['A 肠道菌群紊乱', 'B 肠道菌群紊乱', 'C 膀胱炎结石', 'D 膀胱炎结石']);
  const first = IT.iterateRounds({
    groups, topicSpec: { terms: '肠道菌群' }, maxRounds: 2, batch: 3, minDf: 2,
    priorFile: { exists: false, data: null, error: null },
    now: new Date('2026-10-18T00:00:00Z'),
  });
  assert.ok(first.stateNext, '首次运行未产出待写状态');
  assert.strictEqual(first.stateNext.slots.length, 1);
  assert.strictEqual(first.stateNext.slots[0].runs, 1);
  assert.strictEqual(first.crossRun.status, CSG.PRIOR.NONE);
  assert.ok(first.crossRun.clusters.length > 0, '夹具须真聚出维度（否则下面的断言是空真值）');
  assert.ok(first.crossRun.clusters.every(c => c.trend === CSG.TREND.NEW), '首次运行须全部 new');
  assert.ok(first.crossRun.clusters.every(c => c.reportCount === 1), '首次运行 reportCount 须为 1');
  // 第二次：把上次写回的状态喂回去
  const second = IT.iterateRounds({
    groups, topicSpec: { terms: '肠道菌群' }, maxRounds: 2, batch: 3, minDf: 2,
    priorFile: { exists: true, data: first.stateNext, error: null },
    now: new Date('2026-10-18T01:00:00Z'),
  });
  assert.strictEqual(second.crossRun.status, CSG.PRIOR.OK, '同词表同语料的第二次运行未合并');
  assert.strictEqual(second.crossRun.runs, 2);
  assert.ok(second.crossRun.clusters.some(c => c.trend === CSG.TREND.PERSISTENT),
    '第二次运行没有任何 persistent 维度（夹具或判据有问题）');
  // 诊断簇必须能读到贴回的跨运行字段（否则报告与建议式都看不见）
  assert.ok(second.diagnosis.clusters.every(c => 'trend' in c && 'reportCount' in c),
    '跨运行结论未贴回诊断簇');
  const j = JSON.parse(RK.renderJson(
    REL.rankAll(groups, REL.buildTopic({ terms: '肠道菌群' })),
    { iterateReport: RK.compactIterate(second) }));
  const cr = j.iterate.crossRun;
  assert.ok(cr, 'JSON 缺 iterate.crossRun（白名单漏字段）');
  assert.strictEqual(cr.status, 'ok');
  assert.strictEqual(cr.runs, 2);
  assert.ok(Array.isArray(cr.clusters) && cr.clusters.length > 0);
  assert.ok(cr.clusters.every(c => 'trend' in c && 'reportCount' in c && 'suppress' in c),
    'JSON 跨运行簇字段不全');
  assert.ok(cr.summary && typeof cr.summary.persistent === 'number', 'JSON 缺 summary');
  // registry 元信息（JSON 通道是逐字段白名单：漏一个既不报错也不影响 md）
  assert.strictEqual(cr.format, 'v2', 'JSON 缺 crossRun.format（v1 迁移提示依赖它）');
  assert.strictEqual(cr.slotCount, 1, 'JSON 缺 crossRun.slotCount');
  assert.deepStrictEqual(cr.evicted, [], 'JSON 缺 crossRun.evicted（淘汰不暴露＝静默丢记忆）');
  assert.strictEqual(second.crossRun.slotCount, 1);
  assert.strictEqual(second.crossRun.format, 'v2');
  // ★ 淘汰必须能从 JSON 读到（compactIterate 逐字段白名单，漏了就是静默丢记忆）。
  //   直接注入一个淘汰项——本用例测的是「通道是否透传该字段」，不是淘汰算法本身。
  second.crossRun.evicted = [{ hash: 'h-dead', topic: 'x|y', savedAt: '2026-10-01T00:00:00Z' }];
  const j2 = JSON.parse(RK.renderJson(
    REL.rankAll(groups, REL.buildTopic({ terms: '肠道菌群' })),
    { iterateReport: RK.compactIterate(second) }));
  assert.strictEqual(j2.iterate.crossRun.evicted.length, 1, 'JSON 未透出 evicted');
  assert.strictEqual(j2.iterate.crossRun.evicted[0].hash, 'h-dead');
  // md 通道：跨运行小节必须真出现在报告里（否则字段对了但人看不到）
  const md = RK.renderIterateReport(second, {});
  assert.ok(/跨运行记忆/.test(md), 'md 未输出「跨运行记忆」小节');
  assert.ok(/沿续（`persistent`）/.test(md), 'md 未标注沿续维度');
  assert.ok(/第 \*\*2\*\* 次运行/.test(md), 'md 未说明这是第几次运行');
});

t('★ `--converge-state` 缺 `--iterate` ⇒ 参数层就报错（静默忽略会让人以为状态已记下）', () => {
  needCSG();
  assert.throws(() => RK.parseArgs(['node', 's', '--dir', './run', '--topic', 'a,b',
    '--converge-state', './s.json']), /--converge-state 需与 --iterate 同用/);
  // 正例：两参数同时给出必须能解析（否则上一条断言可能只是「任何输入都报错」）
  const a = RK.parseArgs(['node', 's', '--dir', './run', '--topic', 'a,b',
    '--iterate', '3', '--converge-state', './s.json']);
  assert.strictEqual(a.convergeState, './s.json');
  assert.strictEqual(a.iterate, 3);
});

// ---------- 项目级状态登记：默认路径 + 多主题 registry（2026-10-19） ----------
// 动因：v1 状态文件是**单主题**的 —— 换个词表就把上一个主题的记忆覆盖掉（实测 `fix4-changed`
//   直接把 gutkidney 的 3 次历史清成 runs=1）。一个项目本来就该有多个主题，记忆不能互删。
//   同时 `--converge-state` 每次都要手打路径，实际使用中必然忘。
console.log('项目级状态登记（默认路径 + 多主题 registry）:');

const V2 = 'dim-converge-state/v2';
const v2File = slots => ({ version: V2, savedAt: '2026-10-18T00:00:00Z', slots });
const v2Slot = (topic, clusters, extra) => Object.assign({
  hash: CSG.fingerprintOf({ topic }).hash,
  topic: CSG.canonTopic(topic),
  savedAt: '2026-10-18T00:00:00Z',
  runs: 1, criterion: CSG.CRITERION, state: 'converged', iterations: 2,
  fingerprint: { topic: CSG.canonTopic(topic), hash: CSG.fingerprintOf({ topic }).hash, corpus: 10, pick: 'all' },
  clusters,
}, extra || {});

t('★ 默认路径：裸 `--converge-state` ⇒ `<dir>/converge-state.json`（不必每次手带）', () => {
  needCSG();
  const base = ['node', 's', '--dir', './run', '--topic', 'a,b'];
  const a = RK.parseArgs(base.concat(['--iterate', '3', '--converge-state']));
  assert.strictEqual(a.convergeState, RK.CONVERGE_DEFAULT, '裸参数未使用默认哨兵');
  assert.strictEqual(RK.resolveConvergePath(a), path.join('./run', 'converge-state.json'));
  // 带值 ⇒ 用给定值（不被默认覆盖）
  const b = RK.parseArgs(base.concat(['--iterate', '3', '--converge-state', './x.json']));
  assert.strictEqual(RK.resolveConvergePath(b), './x.json');
  // ★ 紧跟另一个参数 ⇒ 不得把它吞成路径（否则 `--converge-state --iterate 3` 会静默丢轮数）
  const c = RK.parseArgs(base.concat(['--converge-state', '--iterate', '3']));
  assert.strictEqual(c.convergeState, RK.CONVERGE_DEFAULT);
  assert.strictEqual(c.iterate, 3, '--iterate 被吞成 --converge-state 的值');
});

t('★ registry：一个文件装多主题，各槽 runs 独立累加（换主题不再覆盖别人的记忆）', () => {
  needCSG();
  const f = v2File([
    v2Slot('肠肾轴,肠道菌群', [csCl('Kidney', 'stalled', 5)], { runs: 3 }),
    v2Slot('毛球,化毛', [csCl('Hairball', 'stalled', 2)]),
  ]);
  const fpA = CSG.fingerprintOf({ topic: '肠肾轴,肠道菌群', corpus: 10 });
  const fpB = CSG.fingerprintOf({ topic: '毛球,化毛', corpus: 10 });
  const pA = CSG.readPrior(csIn(f), fpA);
  assert.strictEqual(pA.status, CSG.PRIOR.OK, '同主题槽未命中');
  assert.strictEqual(pA.runs, 3);
  assert.strictEqual(pA.otherSlots, 1, 'otherSlots 未统计（报告里看不到「还有别的主题」）');
  assert.strictEqual(pA.clusters[0].key, 'Kidney');
  const pB = CSG.readPrior(csIn(f), fpB);
  assert.strictEqual(pB.status, CSG.PRIOR.OK);
  assert.strictEqual(pB.clusters[0].key, 'Hairball', '取到了别的主题的槽（串槽）');
});

t('★ registry 里没有本主题 ⇒ `none`（首次），**不是**拒绝（旧槽原样保留）', () => {
  needCSG();
  const f = v2File([v2Slot('毛球,化毛', [csCl('Hairball', 'stalled', 2)])]);
  const p = CSG.readPrior(csIn(f), CSG.fingerprintOf({ topic: '肠肾轴,肠道菌群', corpus: 10 }));
  assert.strictEqual(p.status, CSG.PRIOR.NONE);
  assert.strictEqual(p.clusters.length, 0);
  assert.strictEqual(p.otherSlots, 1);
  assert.ok(/其他主题/.test(p.reason), '未说明文件里还有别的主题（会让人以为文件是空的）');
});

t('★ 双键匹配：hash 相同但 topic 不同 ⇒ 视为不同主题（hash 只作标识，不参与判定）', () => {
  needCSG();
  const fp = CSG.fingerprintOf({ topic: '肠肾轴,肠道菌群' });
  const forged = v2Slot('肠肾轴,肠道菌群', [csCl('Kidney', 'stalled', 5)]);
  forged.hash = fp.hash;                 // hash 对得上
  forged.topic = CSG.canonTopic('毛球,化毛');  // 但 topic 不是同一个
  const p = CSG.readPrior(csIn(v2File([forged])), fp);
  assert.strictEqual(p.status, CSG.PRIOR.NONE, '仅凭 hash 就合并了（碰撞会串主题）');
});

t('★ v1 文件自动迁移：读得进（格式标识 v1）、数据零丢失，写回后变 v2 单槽', () => {
  needCSG();
  const old = csFile('t', [csCl('K', 'stalled', 5)], { runs: 4 });
  const fp = CSG.fingerprintOf({ topic: 't', corpus: 10 });
  const p = CSG.readPrior(csIn(old), fp);
  assert.strictEqual(p.status, CSG.PRIOR.OK, 'v1 文件读不进（升级即失忆）');
  assert.strictEqual(p.format, 'v1');
  assert.strictEqual(p.runs, 4, '迁移后 runs 丢失');
  assert.strictEqual(p.clusters[0].key, 'K');
  // 写回：变成 v2，且该槽内容完整
  const built = CSG.buildState({
    cross: { clusters: [{ key: 'K', label: 'K', kind: 'new-dimension', status: 'stalled',
      trend: 'persistent', support: 5, reportCount: 5, supportSeries: [5, 5] }], runs: 5 },
    convergence: { state: 'converged', observations: 3 },
    fingerprint: fp, now: new Date('2026-10-19T00:00:00Z'), prevFile: old,
  });
  assert.strictEqual(built.state.version, V2, '写回未升到 v2');
  assert.strictEqual(built.state.slots.length, 1);
  assert.strictEqual(built.state.slots[0].runs, 5);
  assert.deepStrictEqual(built.evicted, []);
});

t('★ v1 迁移兜底：旧槽 hash 缺失时只按 topic 取代（不产生重复槽）', () => {
  needCSG();
  const old = csFile('t', [csCl('K', 'stalled', 5)], { runs: 2 });
  old.fingerprint.hash = '';          // v1 早期文件 / 手改文件可能没有 hash
  const built = CSG.buildState({
    cross: { clusters: [{ key: 'K', label: 'K', kind: 'new-dimension', status: 'stalled',
      trend: 'persistent', support: 5, reportCount: 3, supportSeries: [5, 5] }], runs: 3 },
    convergence: { state: 'converged', observations: 2 },
    fingerprint: CSG.fingerprintOf({ topic: 't', corpus: 10 }),
    now: new Date('2026-10-19T00:00:00Z'), prevFile: old,
  });
  assert.strictEqual(built.state.slots.length, 1, 'v1 旧槽 hash 不符时产生了重复槽（一题两槽）');
  assert.strictEqual(built.state.slots[0].runs, 3);
});

t('★ 不变量：运行 B 主题**不得改动** A 主题的槽（逐字段深等）', () => {
  needCSG();
  const slotA = v2Slot('肠肾轴,肠道菌群', [csCl('Kidney', 'stalled', 5)], { runs: 3 });
  const slotB = v2Slot('毛球,化毛', [csCl('Hairball', 'stalled', 2)]);
  const prev = v2File([slotA, slotB]);
  const before = JSON.parse(JSON.stringify(slotA));
  const fpB = CSG.fingerprintOf({ topic: '毛球,化毛', corpus: 10 });
  const built = CSG.buildState({
    cross: { clusters: [{ key: 'Hairball', label: 'Hairball', kind: 'new-dimension',
      status: 'stalled', trend: 'persistent', support: 2, reportCount: 2, supportSeries: [2, 2] }], runs: 2 },
    convergence: { state: 'converged', observations: 2 },
    fingerprint: fpB, now: new Date('2026-10-19T00:00:00Z'), prevFile: prev,
  });
  const after = built.state.slots.find(s => s.topic === CSG.canonTopic('肠肾轴,肠道菌群'));
  assert.ok(after, 'A 主题的槽被删了（记忆互删）');
  assert.deepStrictEqual(after, before, 'A 主题的槽被改动');
  const b2 = built.state.slots.find(s => s.topic === CSG.canonTopic('毛球,化毛'));
  assert.strictEqual(b2.runs, 2, 'B 主题未累加');
});

t('同主题再跑 ⇒ 更新原槽、不新增；槽数不变', () => {
  needCSG();
  const prev = v2File([v2Slot('t', [csCl('K', 'stalled', 5)], { runs: 1 })]);
  const built = CSG.buildState({
    cross: { clusters: [{ key: 'K', label: 'K', kind: 'new-dimension', status: 'stalled',
      trend: 'persistent', support: 5, reportCount: 2, supportSeries: [5, 5] }], runs: 2 },
    convergence: { state: 'converged', observations: 2 },
    fingerprint: CSG.fingerprintOf({ topic: 't', corpus: 10 }),
    now: new Date('2026-10-19T00:00:00Z'), prevFile: prev,
  });
  assert.strictEqual(built.state.slots.length, 1, '同主题被写成了新槽');
  assert.strictEqual(built.state.slots[0].runs, 2);
});

t('★ 槽上限：超出 MAX_SLOTS 淘汰最旧槽，且**留痕**（不静默丢记忆）', () => {
  needCSG();
  assert.strictEqual(CSG.MAX_SLOTS, 20);
  const slots = [];
  for (let i = 0; i < CSG.MAX_SLOTS; i++) {
    // savedAt 递增 ⇒ 第 0 个最旧
    const ts = '2026-10-' + String(10 + (i % 9)).padStart(2, '0') + 'T0' + (i % 10) + ':00:00Z';
    slots.push(v2Slot('t' + i, [csCl('C' + i, 'stalled', 2)], { savedAt: ts }));
  }
  const oldest = slots[0].topic;
  const built = CSG.buildState({
    cross: { clusters: [{ key: 'N', label: 'N', kind: 'new-dimension', status: 'stalled',
      trend: 'new', support: 2, reportCount: 1, supportSeries: [2] }], runs: 1 },
    convergence: { state: 'converged', observations: 2 },
    fingerprint: CSG.fingerprintOf({ topic: 'brand-new', corpus: 10 }),
    now: new Date('2026-10-19T23:00:00Z'), prevFile: v2File(slots),
  });
  assert.strictEqual(built.state.slots.length, CSG.MAX_SLOTS, '槽数未收敛到上限');
  assert.strictEqual(built.evicted.length, 1, '淘汰未留痕');
  assert.strictEqual(built.evicted[0].topic, oldest, '淘汰的不是最旧槽');
  assert.ok(!built.state.slots.some(s => s.topic === oldest), '被淘汰的槽仍在文件里');
});

t('★ registry 序列化确定性：同输入两次逐字节相同，槽按 savedAt 降序', () => {
  needCSG();
  const prev = v2File([
    v2Slot('a', [csCl('X', 'stalled', 2)], { savedAt: '2026-10-10T00:00:00Z' }),
    v2Slot('b', [csCl('Y', 'stalled', 3)], { savedAt: '2026-10-18T00:00:00Z' }),
  ]);
  const args = {
    cross: { clusters: [{ key: 'Z', label: 'Z', kind: 'new-dimension', status: 'stalled',
      trend: 'new', support: 4, reportCount: 1, supportSeries: [4] }], runs: 1 },
    convergence: { state: 'converged', observations: 2 },
    fingerprint: CSG.fingerprintOf({ topic: 'c', corpus: 10 }),
    now: new Date('2026-10-19T01:02:03Z'), prevFile: prev,
  };
  const s1 = CSG.serialise(CSG.buildState(args).state);
  const s2 = CSG.serialise(CSG.buildState(args).state);
  assert.strictEqual(s1, s2, '同一输入两次序列化不同（无法 diff）');
  const j = JSON.parse(s1);
  assert.strictEqual(j.slots[0].topic, CSG.canonTopic('c'), '最新槽未排在最前');
  // ★ 必须断言**完整顺序**：只比首尾的话，「输入本来就有序」时即使不排序也会通过
  const tss = j.slots.map(s => s.savedAt);
  assert.deepStrictEqual(tss, tss.slice().sort().reverse(), '槽未按 savedAt 严格降序：' + tss.join(' , '));
});

t('★ CLI 集成：裸参数两次运行 ⇒ 默认文件生成在 --dir 下、runs 累加、报告显示槽数', () => {
  needCSG();
  const { spawnSync } = require('child_process');
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pbs-reg-'));
  fs.mkdirSync(path.join(dir, 'raw'), { recursive: true });
  const titles = ['A 肠道菌群紊乱', 'B 肠道菌群紊乱', 'C 膀胱炎结石', 'D 膀胱炎结石'];
  fs.writeFileSync(path.join(dir, 'raw', '01-a.json'), JSON.stringify({
    runId: 'R1', keyword: 'k',
    records: titles.map((x, i) => ({ idx: i + 1, titleZh: x, year: 2020 })),
  }), 'utf8');
  const run = topic => spawnSync(process.execPath, [path.join(__dirname, 'rank-records.cjs'),
    '--dir', dir, '--topic', topic, '--iterate', '2', '--iterate-pick', 'all', '--min-df', '2',
    '--converge-state', '--format', 'md', '--out', path.join(dir, 'r')], { encoding: 'utf8' });
  const r1 = run('肠道菌群');
  assert.strictEqual(r1.status, 0, '第一次运行失败：' + String(r1.stderr).slice(0, 240));
  const defPath = path.join(dir, 'converge-state.json');
  assert.ok(fs.existsSync(defPath), '裸参数未在 --dir 下生成状态文件');
  const s1 = JSON.parse(fs.readFileSync(defPath, 'utf8'));
  assert.strictEqual(s1.version, V2);
  assert.strictEqual(s1.slots.length, 1);
  assert.strictEqual(s1.slots[0].runs, 1);
  const r2 = run('肠道菌群');
  assert.strictEqual(r2.status, 0, '第二次运行失败：' + String(r2.stderr).slice(0, 240));
  assert.strictEqual(JSON.parse(fs.readFileSync(defPath, 'utf8')).slots[0].runs, 2, 'runs 未累加');
  // ★ 换主题 ⇒ 新增一个槽，原槽必须还在（v1 时代这里会被覆盖）
  const r3 = run('膀胱炎结石');
  assert.strictEqual(r3.status, 0, '第三次运行失败：' + String(r3.stderr).slice(0, 240));
  const s3 = JSON.parse(fs.readFileSync(defPath, 'utf8'));
  assert.strictEqual(s3.slots.length, 2, '换主题后槽数不是 2（记忆互删）');
  assert.ok(s3.slots.some(s => s.runs === 2), '原主题的 runs=2 历史被覆盖');
  const md3 = fs.readFileSync(path.join(dir, 'r.md'), 'utf8');
  assert.ok(/还有 \*\*1\*\* 个其他主题/.test(md3), '报告未说明文件里还有其他主题槽');
  assert.ok(/文件内主题槽 \*\*2\*\*/.test(md3), '报告未显示文件内的主题槽数');
  // JSON 通道：otherSlots / slotCount 必须透出（md 里的「其他主题 1」来自 reason，掩盖不了漏字段）
  const out3 = JSON.parse(String(r3.stdout).trim());
  assert.strictEqual(out3.iterate.crossRun.otherSlots, 1, 'JSON 未透出「其他主题槽数」');
  assert.strictEqual(out3.iterate.crossRun.slotCount, 2, 'JSON 未透出「文件内槽数」');
});

t('★ CLI 集成（真读盘/真写盘）：两次运行同一状态文件，第二次必须读回并累加 runs', () => {
  needCSG();
  const { spawnSync } = require('child_process');
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pbs-cs-'));
  fs.mkdirSync(path.join(dir, 'raw'), { recursive: true });
  // 与「端到端」用例同一批语料：已验证能真聚出残差维度（否则下面的非空断言是空真值）
  const titles = ['A 肠道菌群紊乱', 'B 肠道菌群紊乱', 'C 膀胱炎结石', 'D 膀胱炎结石'];
  fs.writeFileSync(path.join(dir, 'raw', '01-a.json'), JSON.stringify({
    runId: 'R1', keyword: 'k',
    records: titles.map((x, i) => ({ idx: i + 1, titleZh: x, year: 2020 })),
  }), 'utf8');
  const statePath = path.join(dir, 'nested', 'state.json');   // ★ 父目录不存在：必须自建
  const outPrefix = path.join(dir, 'r');
  const run = () => spawnSync(process.execPath, [path.join(__dirname, 'rank-records.cjs'),
    '--dir', dir, '--topic', '肠道菌群', '--iterate', '2', '--iterate-pick', 'all',
    '--min-df', '2', '--converge-state', statePath, '--format', 'md', '--out', outPrefix],
  { encoding: 'utf8' });
  const r1 = run();
  assert.strictEqual(r1.status, 0, '第一次运行失败：' + String(r1.stderr).slice(0, 240));
  assert.ok(fs.existsSync(statePath), '第一次运行未写状态文件（或未自建父目录）');
  const s1 = JSON.parse(fs.readFileSync(statePath, 'utf8'));
  assert.strictEqual(s1.version, CSG.VERSION);
  assert.strictEqual(s1.slots.length, 1);
  assert.strictEqual(s1.slots[0].runs, 1);
  assert.ok(s1.slots[0].clusters.length > 0, '夹具未产出维度 ⇒ 跨运行记忆无从验证');
  const r2 = run();
  assert.strictEqual(r2.status, 0, '第二次运行失败：' + String(r2.stderr).slice(0, 240));
  const s2 = JSON.parse(fs.readFileSync(statePath, 'utf8'));
  assert.strictEqual(s2.slots[0].runs, 2, '第二次运行未累加 runs（状态没被读回）');
  const md2 = fs.readFileSync(outPrefix + '.md', 'utf8');
  assert.ok(/跨运行记忆/.test(md2), '第二次 md 报告缺跨运行小节');
  assert.ok(/第 \*\*2\*\* 次运行/.test(md2), '第二次 md 未显示「第 2 次运行」');
  // 写回顺序：报告存在且非空（状态在报告之后写，不该出现「状态有、报告无」）
  assert.ok(md2.length > 500, '报告异常短，写盘顺序可疑');
});

t('★ 状态文件确定性：同一输入两次序列化逐字节相同，且 clusters 按 key 升序', () => {
  needCSG();
  const cross = {
    status: 'ok', reason: '', runs: 2, corpusChanged: false, savedAt: null,
    clusters: [
      { key: 'zeta', label: 'Zeta', kind: 'new-dimension', status: 'stalled', trend: 'persistent',
        support: 3, reportCount: 2, supportSeries: [3, 3] },
      { key: 'alpha', label: 'Alpha', kind: 'new-dimension', status: 'stalled', trend: 'persistent',
        support: 5, reportCount: 2, supportSeries: [5, 5] },
    ],
    summary: {}, suppressedKeys: [],
  };
  const fp = CSG.fingerprintOf({ topic: 'b,a', corpus: 48, pick: 'all' });
  const now = new Date('2026-10-18T03:04:05Z');
  const s1 = CSG.serialise(CSG.buildState({ cross, convergence: { state: 'converged', observations: 3 }, fingerprint: fp, now }).state);
  const s2 = CSG.serialise(CSG.buildState({ cross, convergence: { state: 'converged', observations: 3 }, fingerprint: fp, now }).state);
  assert.strictEqual(s1, s2, '同一输入两次序列化结果不同（无法 diff）');
  assert.ok(/^\{\n {2}"version"/.test(s1), '序列化格式不稳定');
  assert.ok(/\n$/.test(s1), '序列化未以换行结尾');
  assert.ok(s1.indexOf('"alpha"') < s1.indexOf('"zeta"'), 'clusters 未按 key 升序');
  assert.ok(/"savedAt": "2026-10-18T03:04:05Z"/.test(s1), 'savedAt 非秒级 UTC');
});

t('★ 源码守卫：跨运行模块是纯函数（不得出现 fs / net / 子进程 / 文件读写在 lib 层）', () => {
  needCSG();
  const src = fs.readFileSync(path.join(__dirname, 'lib', 'converge-state.cjs'), 'utf8');
  const banned = [
    [/require\(\s*['"](fs|path|http|https|net|child_process)['"]\s*\)/, '引入了 IO 模块'],
    [/\b(readFileSync|writeFileSync|existsSync|mkdirSync|createReadStream)\b/, '在 lib 层做文件读写'],
    [/\bprocess\.env\b/, '读了环境变量（输出不再确定）'],
  ];
  banned.forEach(([re, msg]) => assert.ok(!re.test(src), 'converge-state.cjs 违反纯函数纪律：' + msg));
  // 反向确认守卫本身有效（否则「没匹配到」也可能只是正则写错）
  assert.ok(/require\(\s*['"]crypto['"]\s*\)/.test(src), '守卫失效：连已存在的 require 都没匹配到');
});

// ---------- 原子写（状态文件不得出现半截/空文件） ----------
// 背景（实测，见 lib/atomic-write.cjs 头注释）：writeFileSync 期间并发读者读到空文件 128/200、
// JSON.parse 失败 67/200 ⇒ readPrior 判 CORRUPT ⇒ 覆盖写回 ⇒ 全部主题槽被一次性清空。
console.log('原子写:');
const needAW = () => { assert.ok(AW, '缺 lib/atomic-write.cjs 的 writeAtomicSync'); };

t('原子写·基本：覆盖写入生效、父目录自建、改名后不留临时文件', () => {
  needAW();
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pbs-aw-'));
  const p = path.join(dir, 'deep', 'sub', 'state.json');   // 父目录两层都不存在
  AW.writeAtomicSync(p, '{"a":1}', 'utf8');
  assert.strictEqual(fs.readFileSync(p, 'utf8'), '{"a":1}', '首次写入内容不符');
  AW.writeAtomicSync(p, '{"a":2}', 'utf8');
  assert.strictEqual(fs.readFileSync(p, 'utf8'), '{"a":2}', '覆盖写入未生效');
  const left = fs.readdirSync(path.dirname(p)).filter(n => n.includes(AW.TMP_MARK));
  assert.deepStrictEqual(left, [], '改名后残留临时文件');
  // 临时名必须在目标同目录：跨文件系统 rename 会退化为 copy，原子性直接消失
  const tmp = AW.tempPathFor(p);
  assert.strictEqual(path.dirname(tmp), path.dirname(p), '临时文件不在目标同目录 ⇒ 原子性不成立');
  assert.ok(path.basename(tmp).startsWith(path.basename(p) + AW.TMP_MARK), '临时名缺少可识别标记');
});

t('★ 原子写·核心：rename 之前主文件必须仍是**完整旧内容**（钩子确定性证明，不靠 sleep 拼竞态）', () => {
  needAW();
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pbs-aw-hook-'));
  const p = path.join(dir, 'state.json');
  const OLD = JSON.stringify({ version: 'dim-converge-state/v2', slots: [{ topic: 'a' }, { topic: 'b' }] });
  const NEW = JSON.stringify({ version: 'dim-converge-state/v2', slots: [] });
  fs.writeFileSync(p, OLD, 'utf8');
  let seenMain = null, seenTmp = null, mainParseErr = null;
  AW.writeAtomicSync(p, NEW, 'utf8', {
    hooks: {
      afterTemp(tmp) {
        seenTmp = fs.readFileSync(tmp, 'utf8');      // 新内容已完整落在临时文件
        seenMain = fs.readFileSync(p, 'utf8');       // ← 此刻主文件必须还是旧内容
        try { JSON.parse(seenMain); } catch (e) { mainParseErr = e.message; }
      },
    },
  });
  assert.strictEqual(mainParseErr, null, 'rename 之前读者读到无法解析的内容（半截/空）⇒ 原子性不成立');
  assert.strictEqual(seenMain, OLD, 'rename 之前主文件已被改写 ⇒ 读者会看到中间态');
  assert.ok(seenTmp === NEW, '临时文件未包含完整新内容');
  // 反向确认：改名之后新内容确实生效（否则「什么都不做」也能让上面的断言通过）
  assert.strictEqual(fs.readFileSync(p, 'utf8'), NEW, '改名后新内容未生效');
});

t('原子写·失败路径：不留垃圾、不破坏旧文件、不可重试的错误不被退避吞掉', () => {
  needAW();
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pbs-aw-fail-'));
  const p = path.join(dir, 'state.json');
  fs.writeFileSync(p, '{"old":true}', 'utf8');

  // ① 钩子抛错（模拟写到一半进程出事）⇒ 异常必须向上传播，旧文件完好，临时文件被清
  let threw = false;
  try {
    AW.writeAtomicSync(p, '{"new":true}', 'utf8', { hooks: { beforeRename() { throw new Error('boom'); } } });
  } catch (e) { threw = true; }
  assert.ok(threw, '钩子抛错被静默吞掉（调用方会以为写成功）');
  assert.strictEqual(fs.readFileSync(p, 'utf8'), '{"old":true}', '失败后旧文件被破坏');
  assert.deepStrictEqual(fs.readdirSync(dir).filter(n => n.includes(AW.TMP_MARK)), [], '失败后残留临时文件');

  // ② 临时文件被删 ⇒ rename 报 ENOENT。ENOENT 不在重试名单里，必须**立刻**抛，
  //    否则会静默退避到 ~600ms 才报，看起来像卡住（误报比漏报更糟的同类问题：把失败拖成卡顿）。
  const t0 = Date.now();
  let err = null;
  try {
    AW.writeAtomicSync(p, '{"new":true}', 'utf8', { hooks: { beforeRename(tmp) { fs.unlinkSync(tmp); } } });
  } catch (e) { err = e; }
  const ms = Date.now() - t0;
  assert.ok(err, '临时文件被删后 rename 应失败');
  assert.strictEqual(err.code, 'ENOENT', '预期 ENOENT，实际 ' + (err && err.code));
  assert.ok(ms < 500, '不可重试的错误被当成可重试（耗时 ' + ms + 'ms）⇒ 失败被拖成卡顿');
});

t('★ 源码守卫：状态文件写入不得回退到 fs.writeFileSync（M2 会原样回归）', () => {
  needAW();
  const src = fs.readFileSync(path.join(__dirname, 'rank-records.cjs'), 'utf8');
  assert.ok(/AW\.writeAtomicSync\(\s*convergePath\s*,/.test(src),
    '状态文件写入未走原子写');
  assert.ok(!/fs\.writeFileSync\(\s*convergePath\s*,/.test(src),
    '状态文件仍在直接 writeFileSync ⇒ 并发读者读到空/半截 ⇒ 判 CORRUPT ⇒ 清空全部槽');
  // 反向确认守卫有效：同一正则在报告写入处必须能匹配到（否则「没匹配到」可能只是正则写错）
  assert.ok(/fs\.writeFileSync\(\s*p\s*,/.test(src), '守卫失效：连报告文件的 writeFileSync 都没匹配到');
});

t('原子写·清理：只删本模块命名的残留临时文件，其他文件一律不动', () => {
  needAW();
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pbs-aw-sweep-'));
  const p = path.join(dir, 'state.json');
  fs.writeFileSync(p, '{}', 'utf8');
  const base = path.basename(p);
  const stale = path.join(dir, base + AW.TMP_MARK + '999999-abcdef012345');        // 别的进程崩溃遗留
  const normal = path.join(dir, 'notes.txt');
  const decoy = path.join(dir, base + '.bak-20261024');                            // 名字像但非本模块命名
  const live = path.join(dir, base + AW.TMP_MARK + process.pid + '-0123456789ab'); // 本进程（可能正在写）
  [stale, normal, decoy, live].forEach(x => fs.writeFileSync(x, 'x', 'utf8'));
  const gone = AW.sweepTempFiles(p);
  assert.deepStrictEqual(gone, [stale], '清理范围不对（多删或漏删）');
  assert.ok(fs.existsSync(normal), '普通文件被误删');
  assert.ok(fs.existsSync(decoy), '非本模块命名的备份被误删（删除即永久，绝不能碰）');
  assert.ok(fs.existsSync(live), '本进程正在写的临时文件被删（可能撞上未完成的写）');
  assert.ok(AW.RENAME_RETRY.attempts >= 1, 'Windows 占用重试被关掉 ⇒ 并发下会直接 EPERM 写失败');
});

// ---------- 批 2：写前重读合并（压缩 M1 丢更新） ----------
// 背景：buildState 的 `prevFile` 决定「保留其他主题的槽」。若用的是 run 开始时的快照，
//   整次运行（分钟级）里别的进程新建的槽会被覆盖 —— 实测并发 3 轮 3/3 只存活 1 个槽。
console.log('批 2·重读合并:');
const needRK = () => assert.ok(RK && typeof RK.readStateFile === 'function',
  '缺 rank-records.cjs 的 readStateFile');

t('批2·入参回传：iterateRounds 必须回传 stateInput（含 cross/convergence/fingerprint，且**不含** prevFile）', () => {
  needIT();
  const r = IT.iterateRounds({
    groups: mkG(['A 肠道菌群紊乱', 'B 肠道菌群紊乱']),
    topicSpec: { terms: '肠道菌群' },
    maxRounds: 2, minDf: 2,
    priorFile: { exists: false, data: null, error: null },
  });
  assert.ok(r.stateInput && typeof r.stateInput === 'object', '未回传 stateInput ⇒ CLI 无法在写盘前重建');
  assert.strictEqual(r.stateInput.cross, r.crossRun, 'stateInput.cross 必须就是 crossRun（否则重建后报告与实际脱节）');
  assert.ok(r.stateInput.convergence && r.stateInput.fingerprint, 'stateInput 缺 convergence / fingerprint');
  assert.strictEqual('prevFile' in r.stateInput, false,
    'stateInput 里不得带 prevFile —— 那会诱导调用方沿用陈旧快照（正是批 2 要修的病）');
  assert.ok(r.stateNext && Array.isArray(r.stateNext.slots), '兼容用的 stateNext 仍须产出');
  // 零回归：不传 priorFile ⇒ 两个字段都为 null
  const plain = IT.iterateRounds({ groups: mkG(['A 肠道菌群']), topicSpec: { terms: '肠道菌群' }, minDf: 2 });
  assert.strictEqual(plain.stateInput, null, '不记忆时 stateInput 必须为 null');
  assert.strictEqual(plain.stateNext, null, '不记忆时 stateNext 必须为 null');
});

t('★ 批2·核心：用**更新的**快照重建 ⇒ 别人新建的槽必须保留，且本主题槽不变', () => {
  needCSG();
  const fp = CSG.fingerprintOf({ topic: 'a', corpus: 4, pick: 'all' });
  const cross = {
    status: 'ok', runs: 2,
    clusters: [{ key: 'dim-1', label: 'x', kind: 'new-dimension', status: 'stalled',
      trend: 'persistent', support: 2, reportCount: 2 }],
  };
  const input = { cross, convergence: { state: 'stalled', observations: 2 }, fingerprint: fp,
    now: new Date('2026-10-24T00:00:00Z') };

  const stale = { version: 'dim-converge-state/v2', savedAt: '2026-10-23T00:00:00Z',
    slots: [{ hash: 'h-old', topic: 'old', savedAt: '2026-10-23T00:00:00Z', clusters: [] }] };
  const fresh = { version: 'dim-converge-state/v2', savedAt: '2026-10-24T00:00:00Z',
    slots: [
      { hash: 'h-other', topic: 'other', savedAt: '2026-10-24T00:00:01Z', clusters: [] },
      { hash: 'h-old', topic: 'old', savedAt: '2026-10-23T00:00:00Z', clusters: [] },
    ] };

  const withStale = CSG.buildState(Object.assign({}, input, { prevFile: stale })).state;
  const withFresh = CSG.buildState(Object.assign({}, input, { prevFile: fresh })).state;
  assert.deepStrictEqual(withStale.slots.map(s => s.topic).sort(), ['a', 'old'], '陈旧快照的基线不符');
  assert.deepStrictEqual(withFresh.slots.map(s => s.topic).sort(), ['a', 'old', 'other'],
    '用新鲜快照重建后别人新建的槽没保留 ⇒ 写前重读等于没做');
  // 关键反向断言：重建**只**替换别人的槽，绝不能改动本主题要写入的内容
  assert.deepStrictEqual(withFresh.slots.find(s => s.topic === 'a'), withStale.slots.find(s => s.topic === 'a'),
    'prevFile 影响了本主题槽 ⇒ 重建会改掉本该写入的内容');
});

t('批2·指纹：stateFingerprint 必须区分「文件不存在」与「空对象」（否则「刚被创建」会被当成没变）', () => {
  needRK();
  assert.notStrictEqual(RK.stateFingerprint(null), RK.stateFingerprint({}), 'null 与 {} 指纹相同');
  assert.notStrictEqual(RK.stateFingerprint(undefined), RK.stateFingerprint({}), 'undefined 与 {} 指纹相同');
  assert.strictEqual(RK.stateFingerprint({ a: 1 }), RK.stateFingerprint({ a: 1 }), '同内容指纹应相同');
  assert.notStrictEqual(RK.stateFingerprint({ a: 1 }), RK.stateFingerprint({ a: 2 }), '内容变了指纹没变');
});

t('★ 批2·源码守卫：写状态前必须重读磁盘 + 二次确认（否则重读重建形同虚设）', () => {
  needRK();
  const src = fs.readFileSync(path.join(__dirname, 'rank-records.cjs'), 'utf8');
  assert.ok(/writeStateWithMerge\(convergePath,\s*iterateReport\.stateInput\)/.test(src),
    '主路径没有走 writeStateWithMerge（拿不到新鲜快照）');
  assert.ok(/stateFingerprint\(before\.data\)\s*!==\s*stateFingerprint\(check\.data\)/.test(src),
    '缺少「写前二次确认」—— CAS 失效就退化成普通覆盖写');
  assert.ok(/else if \(convergePath && iterateReport && iterateReport\.stateNext\)/.test(src),
    'stateNext 只能作为 else 兜底（stateInput 缺失时），必须显式写在 else 分支里');
  assert.ok(/STATE_WRITE_TRIES/.test(src), '缺少重试上限常量（竞争时应有限次重试而非无限循环）');
  assert.ok(/forced/.test(src), '重试耗尽必须可被调用方看见（不得静默当作成功）');
  // 反向确认守卫有效：兼容分支的写调用必须能被匹配到，否则「没匹配到」可能只是正则写错
  assert.ok(/CSG\.serialise\(iterateReport\.stateNext\)/.test(src), '守卫失效：连兼容分支的写入都没匹配到');
});

t('★ 批2·行为：期间被别人改写 ⇒ 必须重试，且对方新建的槽要保留（确定性，钩子注入而非拼时序）', () => {
  needRK();
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pbs-cas-'));
  const p = path.join(dir, 'state.json');
  const v2 = slots => ({ version: 'dim-converge-state/v2', savedAt: '2026-10-24T00:00:00Z', slots });
  fs.writeFileSync(p, JSON.stringify(v2([
    { hash: 'h-old', topic: 'old', savedAt: '2026-10-23T00:00:00Z', clusters: [] },
  ])), 'utf8');

  const fp = CSG.fingerprintOf({ topic: 'a', corpus: 4, pick: 'all' });
  const stateInput = {
    cross: { status: 'ok', runs: 1,
      clusters: [{ key: 'd1', label: 'D', kind: 'new-dimension', status: 'stalled', trend: 'new',
        support: 2, reportCount: 1 }] },
    convergence: { state: 'stalled', observations: 2 },
    fingerprint: fp,
  };

  let injected = 0;
  const res = RK.writeStateWithMerge(p, stateInput, {
    beforeWrite({ attempt }) {
      if (attempt === 0 && injected === 0) {
        injected = 1;
        // 模拟「另一个进程在我们读完之后、写之前」新建了 other 槽
        fs.writeFileSync(p, JSON.stringify(v2([
          { hash: 'h-other', topic: 'other', savedAt: '2026-10-24T00:00:01Z', clusters: [] },
          { hash: 'h-old', topic: 'old', savedAt: '2026-10-23T00:00:00Z', clusters: [] },
        ])), 'utf8');
      }
    },
  });

  assert.strictEqual(res.attempts, 2, '应重试一次（第 1 次的二次确认发现被改），实际 ' + res.attempts);
  assert.strictEqual(res.forced, false, '不应走到强制写');
  const final = JSON.parse(fs.readFileSync(p, 'utf8'));
  const topics = final.slots.map(s => s.topic).sort();
  assert.deepStrictEqual(topics, ['a', 'old', 'other'],
    '重试后仍未保留对方新建的槽：' + topics.join(','));
  // 对方的槽必须原样深拷贝（不得被重建 ⇒ 重建会啃掉本模块还不认识的字段）
  assert.deepStrictEqual(final.slots.find(s => s.topic === 'other').clusters, [], 'other 槽被重建');
});

t('批2·行为：竞争持续 ⇒ 有限次后强制写，且 forced 必须为 true（不得静默当作成功）', () => {
  needRK();
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pbs-cas-force-'));
  const p = path.join(dir, 'state.json');
  const v2 = slots => ({ version: 'dim-converge-state/v2', savedAt: '2026-10-24T00:00:00Z', slots });
  fs.writeFileSync(p, JSON.stringify(v2([
    { hash: 'h-old', topic: 'old', savedAt: '2026-10-23T00:00:00Z', clusters: [] },
  ])), 'utf8');
  const fp = CSG.fingerprintOf({ topic: 'a', corpus: 4, pick: 'all' });
  const stateInput = {
    cross: { status: 'ok', runs: 1, clusters: [] },
    convergence: { state: 'stalled', observations: 2 }, fingerprint: fp,
  };
  let n = 0;
  const res = RK.writeStateWithMerge(p, stateInput, {
    beforeWrite() {
      n += 1;   // 每次都制造一次改动 ⇒ 二次确认必失败
      fs.writeFileSync(p, JSON.stringify(v2([
        { hash: 'h-x' + n, topic: 'x' + n, savedAt: '2026-10-24T00:00:0' + (n % 10) + 'Z', clusters: [] },
      ])), 'utf8');
    },
  });
  assert.strictEqual(res.forced, true, '重试耗尽必须标记 forced（否则失败被伪装成成功）');
  assert.strictEqual(res.attempts, RK.STATE_WRITE_TRIES, '重试次数应等于上限');
  assert.ok(fs.existsSync(p), '强制写后文件应存在');
  assert.doesNotThrow(() => JSON.parse(fs.readFileSync(p, 'utf8')), '强制写后文件必须是合法 JSON');
});

// ---------- 批 3：互斥锁（根治 M1 丢更新） ----------
// 背景：批 2 的 CAS 只能发现「自己读之后」的变更。两进程几乎同时读、同时确认、同时写 ⇒ 双双通过。
//   文件系统没有比较并交换原语 ⇒ 无锁的读-改-写做不到零丢失（实测 20 轮丢 4）。只能加锁。
// ★ 锁的粒度：状态每次 run 只在最后写一次、读可重复 ⇒ 临界区只有毫秒级，不需要覆盖整次 run。
console.log('批 3·互斥锁:');
const FL = (() => { try { return require('./lib/file-lock.cjs'); } catch (e) { return null; } })();
const needFL = () => assert.ok(FL && typeof FL.acquireLock === 'function', '缺 lib/file-lock.cjs 的 acquireLock');
const lockTmp = tag => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pbs-lock-' + tag + '-'));
  return { dir, p: path.join(dir, 'state.json') };
};

t('★ 批3·互斥：锁被占用时第二个取锁者必须拿不到（超时返回 ok:false，不得静默成功）', () => {
  needFL();
  const { p } = lockTmp('mutex');
  const a = FL.acquireLock(p, { waitMs: 200 });
  assert.strictEqual(a.ok, true, '首次取锁应成功');
  const b = FL.acquireLock(p, { waitMs: 60, pollMs: 5 });
  assert.strictEqual(b.ok, false, '两个取锁者同时成功 ⇒ 互斥根本没生效');
  assert.strictEqual(b.reason, 'timeout', '失败原因必须是 timeout（其他原因说明路径/权限有问题）');
  assert.ok(b.waitedMs >= 50, '应真的等过再放弃，而不是立刻返回：' + b.waitedMs);
  assert.ok(b.holder && b.holder.pid === process.pid, '超时信息应带持有者 pid（排查残留锁必需）');
  FL.releaseLock(a.handle);
  const c = FL.acquireLock(p, { waitMs: 60 });
  assert.strictEqual(c.ok, true, '释放后仍拿不到 ⇒ 锁泄漏');
  FL.releaseLock(c.handle);
  assert.ok(!fs.existsSync(FL.lockPathFor(p)), '放锁后锁文件必须消失');
});

t('★ 批3·TTL：崩溃遗留的陈旧锁必须可被抢占；**未过期**的锁绝不许抢', () => {
  needFL();
  const { p } = lockTmp('ttl');
  const lp = FL.lockPathFor(p);
  const a = FL.acquireLock(p);
  const b = FL.acquireLock(p, { waitMs: 50, pollMs: 5 });
  assert.strictEqual(b.ok, false, '未过期的锁被抢 ⇒ TTL 判据把「存在」误当成了「崩溃」');
  FL.releaseLock(a.handle);

  // 造一个「持有者已崩」的陈旧锁：内容像模像样，但 mtime 回拨到超过 STALE_MS
  fs.writeFileSync(lp, JSON.stringify({ token: 'dead-1', pid: 999999, at: '2000-01-01T00:00:00Z' }), 'utf8');
  const old = (Date.now() - (FL.STALE_MS + 5000)) / 1000;
  fs.utimesSync(lp, old, old);
  const got = FL.acquireLock(p, { waitMs: 100 });
  assert.strictEqual(got.ok, true, '陈旧锁没被抢占 ⇒ 崩溃一次就永久卡死所有后续进程');
  assert.strictEqual(got.handle.steals, 1, '抢占次数必须留痕（静默抢占等于看不见的并发）');
  const meta = JSON.parse(fs.readFileSync(lp, 'utf8'));
  assert.notStrictEqual(meta.token, 'dead-1', '抢占后锁内容必须换成新 token，否则放锁会误删');
  FL.releaseLock(got.handle);
});

t('★ 批3·放锁：token 不匹配时不得删除（否则会删掉抢占者的锁，互斥彻底失效）', () => {
  needFL();
  const { p } = lockTmp('owner');
  const lp = FL.lockPathFor(p);
  const a = FL.acquireLock(p);
  // 模拟 A 的锁已被 TTL 抢占：文件内容换成别人的 token
  fs.writeFileSync(lp, JSON.stringify({ token: 'other-owner', pid: 1 }), 'utf8');
  const r = FL.releaseLock(a.handle);
  assert.strictEqual(r.released, false, '不是自己的锁却删了 ⇒ 抢占者会在无锁状态下写盘');
  assert.strictEqual(r.reason, 'not_owner', '应明确报 not_owner');
  assert.ok(fs.existsSync(lp), '别人的锁被删了');

  // 正常路径：自己取、自己放，必须删掉
  fs.unlinkSync(lp);
  const b = FL.acquireLock(p, { waitMs: 100 });
  assert.strictEqual(b.ok, true);
  assert.deepStrictEqual(FL.releaseLock(b.handle), { released: true }, '自己的锁必须能正常释放');
  assert.ok(!fs.existsSync(lp));
});

t('★ 批3·异常：临界区抛错也必须放锁（否则一次异常 = 永久卡死所有后续进程）', () => {
  needFL();
  const { p } = lockTmp('throw');
  const lp = FL.lockPathFor(p);
  let threw = false;
  try {
    FL.withLock(p, () => { throw new Error('boom'); });
  } catch (e) {
    threw = true;
  }
  assert.strictEqual(threw, true, '异常必须向上传播（不得被吞成「本次没写」）');
  assert.ok(!fs.existsSync(lp), '抛错后锁文件残留 ⇒ 后续进程全部等超时');
  const r = FL.withLock(p, () => 'ok');
  assert.strictEqual(r.locked, true, '异常之后必须还能取锁');
  assert.strictEqual(r.value, 'ok');
  assert.ok(!fs.existsSync(lp), 'withLock 正常返回后不应残留锁');
});

t('★ 批3·fail-closed：拿不到锁时不写状态（丢一轮记忆可重算，覆盖别人的槽不可逆）', () => {
  needRK();
  needFL();
  const { p } = lockTmp('skip');
  const v2 = slots => ({ version: 'dim-converge-state/v2', savedAt: '2026-10-24T00:00:00Z', slots });
  fs.writeFileSync(p, JSON.stringify(v2([
    { hash: 'h-old', topic: 'old', savedAt: '2026-10-23T00:00:00Z', clusters: [] },
  ])), 'utf8');
  const snapshot = fs.readFileSync(p, 'utf8');
  const stateInput = {
    cross: { status: 'ok', runs: 1, clusters: [] },
    convergence: { state: 'stalled', observations: 2 },
    fingerprint: CSG.fingerprintOf({ topic: 'a', corpus: 4, pick: 'all' }),
  };

  const held = FL.acquireLock(p);   // 模拟另一个进程正持锁
  const res = RK.writeStateWithMerge(p, stateInput, { lockWaitMs: 50 });
  assert.strictEqual(res.skipped, true, '拿不到锁却报告写成功 ⇒ 「状态已保存」是假象');
  assert.strictEqual(res.built, null, '跳过时不得返回 built（调用方会 deref 崩掉）');
  assert.strictEqual(res.reason, 'timeout');
  assert.strictEqual(fs.readFileSync(p, 'utf8'), snapshot, '★ 拿不到锁却仍然写了 —— fail-closed 失效');
  FL.releaseLock(held.handle);

  // 锁释放后同一次调用必须写成功，证明 skipped 不是常态
  const ok = RK.writeStateWithMerge(p, stateInput, { lockWaitMs: 500 });
  assert.strictEqual(ok.skipped, false, '锁空闲时仍跳过 ⇒ 判据过严，等于永远不写');
  const after = JSON.parse(fs.readFileSync(p, 'utf8'));
  assert.deepStrictEqual(after.slots.map(x => x.topic).sort(), ['a', 'old'], '写成功了但槽不对');
  assert.ok(!fs.existsSync(FL.lockPathFor(p)), '写完必须放锁');
});

t('★ 批3·源码守卫：必须在锁内写且 finally 放锁；探活不得用 process.kill（Windows 会杀掉目标）', () => {
  needFL();
  // ★ 只匹配**代码**，先剔注释：本文件头注释里为了说明禁忌就写着那串字面量 ——
  //   不剔的话守卫会被自己的注释打红（自指陷阱，本项目已踩第三次）。
  const codeOnly = src => src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
  const rk = codeOnly(fs.readFileSync(path.join(__dirname, 'rank-records.cjs'), 'utf8'));
  const fl = codeOnly(fs.readFileSync(path.join(__dirname, 'lib', 'file-lock.cjs'), 'utf8'));
  assert.ok(/FL\.acquireLock\(convergePath/.test(rk), 'writeStateWithMerge 没有取锁');
  assert.ok(/finally\s*\{[^}]*FL\.releaseLock\(got\.handle\)/.test(rk), '没有在 finally 里放锁（抛错会残留）');
  assert.ok(/openSync\(lp, 'wx'\)/.test(fl), '互斥的唯一来源必须是 O_EXCL 独占创建');
  assert.ok(!/process\.kill\s*\(/.test(fl),
    '★ 用 process.kill(pid, 0) 判活在 Windows 上会 TerminateProcess 把目标杀掉 —— 只能 mtime + TTL');
  assert.ok(/Atomics\.wait/.test(fl), '同步等待须用 Atomics.wait（busy loop 烧 CPU，setTimeout 拿不到同步语义）');
  assert.ok(FL.WAIT_MS >= 1000, '等锁上限太短 ⇒ 正常竞争也会被误判为拿不到');
  assert.ok(FL.STALE_MS >= 5000, '陈旧阈值 < 5s ⇒ 正常持锁（毫秒级）也可能被误判为崩溃');
  assert.ok(FL.STALE_MS >= 2 * FL.WAIT_MS,
    '陈旧阈值与等锁上限量级太接近：慢一点就会被抢占，等于没有互斥');
});

/** 批 4 用的最小 stateInput（与批 2 同形；buildState 只依赖这三项 + prevFile） */
function m3StateInput() {
  return {
    cross: { status: 'ok', runs: 1,
      clusters: [{ key: 'd1', label: 'D', kind: 'new-dimension', status: 'stalled', trend: 'new',
        support: 2, reportCount: 1 }] },
    convergence: { state: 'stalled', observations: 2 },
    fingerprint: CSG.fingerprintOf({ topic: 'a', corpus: 4, pick: 'all' }),
  };
}

t('★ 批4·M3：backupNameFor 只对 corrupt/rejected 命名，时间戳为 Windows 合法 UTC', () => {
  needCSG();
  const fixed = new Date('2026-10-24T15:40:12.345Z');
  assert.strictEqual(CSG.backupNameFor('a/state.json', CSG.PRIOR.CORRUPT, fixed),
    'a/state.json.corrupt-20261024T154012345Z');
  assert.strictEqual(CSG.backupNameFor('a/state.json', CSG.PRIOR.REJECTED, fixed),
    'a/state.json.legacy-20261024T154012345Z');
  assert.strictEqual(CSG.backupNameFor('a/state.json', CSG.PRIOR.OK, fixed), null,
    'OK 不需要备份（会变成每轮都备份，毫无意义地堆积文件）');
  assert.strictEqual(CSG.backupNameFor('a/state.json', CSG.PRIOR.NONE, fixed), null,
    'NONE 是首次运行，没有可备份的内容');
  // 时间戳不能带 Windows 非法字符（':' 会让 openSync 直接 EINVAL）
  const name = CSG.backupNameFor('s.json', CSG.PRIOR.CORRUPT, fixed);
  assert.ok(!/[:*?"<>|]/.test(name.slice('s.json'.length)), '备份名含 Windows 非法字符：' + name);
});

t('★ 批4·M3：backupUnusableState 写原始字节（不解析）、且绝不覆盖已有备份', () => {
  needRK();
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pbs-m3b-'));
  const p = path.join(dir, 'state.json');
  const original = Buffer.from('{"version":2,"slots":[{"topic":"x"', 'utf8');   // 故意截断
  fs.writeFileSync(p, original);
  const now = new Date('2026-10-24T15:40:12.345Z');

  const b1 = RK.backupUnusableState(p, 'corrupt', { now });
  assert.strictEqual(b1.bytes, original.length, '备份字节数必须等于原文件字节数');
  assert.ok(fs.readFileSync(b1.path).equals(original),
    '备份必须与原文件**逐字节**相同（解析后重新序列化会把截断部分抹平，等于没救）');
  assert.ok(b1.path.endsWith('.corrupt-20261024T154012345Z'), '备份命名不符：' + b1.path);

  // 同毫秒再来一次 ⇒ 必须另开一份，而不是覆盖上一份
  const b2 = RK.backupUnusableState(p, 'corrupt', { now });
  assert.notStrictEqual(b2.path, b1.path, '撞名时必须退让到新名字，不能覆盖已有备份');
  assert.ok(fs.existsSync(b1.path) && fs.existsSync(b2.path), '两份备份都必须还在');

  // 非法 status 必须大声拒绝（否则会写出语义不明的备份名）
  assert.throws(() => RK.backupUnusableState(p, 'ok', { now }), /只接受 corrupt \/ rejected/,
    'status=ok 不该被允许备份（说明调用方判据写错，应立刻暴露）');
  assert.strictEqual(fs.readFileSync(p).equals(original), true, '备份不能改动原文件');
});

t('★ 批4·M3 行为：CORRUPT 状态被覆盖前必须留档，且留档内容=原文件（不丢一字节）', () => {
  needRK(); needCSG(); needFL();
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pbs-m3c-'));
  const p = path.join(dir, 'state.json');
  const original = Buffer.from('{"version":"dim-converge-state/v2","slots":[{"topic":"old"', 'utf8');
  fs.writeFileSync(p, original);

  const res = RK.writeStateWithMerge(p, m3StateInput(), { lockWaitMs: 2000 });
  assert.strictEqual(res.skipped, false, '有锁 + 能备份 ⇒ 必须正常写，不得跳过');
  assert.ok(res.backup, 'CORRUPT 覆盖前必须产生备份');
  assert.strictEqual(res.backup.bytes, original.length);
  assert.ok(fs.readFileSync(res.backup.path).equals(original),
    '备份内容必须与被覆盖的原文件逐字节相同');
  assert.ok(res.backup.path.indexOf('.corrupt-') > 0, 'CORRUPT 分支必须用 .corrupt 标记');

  // 新文件必须可解析（说明覆盖确实发生了，备份不是「跳过写」的副产品）
  const after = JSON.parse(fs.readFileSync(p, 'utf8'));
  assert.ok(Array.isArray(after.slots) && after.slots.length >= 1, '覆盖后应是合法的新状态');
  assert.ok(!fs.existsSync(FL.lockPathFor(p)), '写完后不得残留锁');
});

t('★ 批4·M3 行为：备份失败必须 fail-closed（不写状态、原文件一个字节都不动）', () => {
  needRK(); needFL();
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pbs-m3d-'));
  const p = path.join(dir, 'state.json');
  const original = Buffer.from('{"version":"dim-converge-state/v2","slots":[{"topic":"old"', 'utf8');
  fs.writeFileSync(p, original);

  // 注入非法时间 ⇒ backupNameFor 的 toISOString() 抛 RangeError ⇒ 备份必失败
  // （不靠「把目录设成只读」这种依赖权限/OS 的手段，确定性更高）
  const res = RK.writeStateWithMerge(p, m3StateInput(), { lockWaitMs: 2000, now: new Date(NaN) });
  assert.strictEqual(res.skipped, true, '备份失败却继续写 ⇒ 唯一能救的那份文件被覆盖');
  assert.strictEqual(res.backupFailed, true, '必须把「失败原因是备份」单独标出来（与锁超时区分）');
  assert.ok(/^backup_failed: /.test(res.reason), '失败原因必须可读：' + res.reason);
  assert.ok(fs.readFileSync(p).equals(original), 'fail-closed 的定义就是原文件一个字节都不变');
  assert.ok(!fs.existsSync(FL.lockPathFor(p)), '提前 return 也必须走 finally 放锁');
});

t('★ 批4·源码守卫：备份必须在第一次写之前，且 backup_failed 分支不得写盘', () => {
  needRK();
  const src = fs.readFileSync(path.join(__dirname, 'rank-records.cjs'), 'utf8');
  const iCall = src.indexOf('backup = backupUnusableState(');
  const iWrite = src.indexOf('AW.writeAtomicSync(convergePath, CSG.serialise(built.state)');
  assert.ok(iCall > 0, 'writeStateWithMerge 里没有调用 backupUnusableState');
  assert.ok(iWrite > 0, '守卫失效：连主写入点都没匹配到（可能是正则/锚点写错，不是代码错）');
  assert.ok(iCall < iWrite, '备份必须发生在**第一次写之前** —— 写在后面等于没备份');
  assert.ok(/preStatus === CSG\.PRIOR\.CORRUPT \|\| preStatus === CSG\.PRIOR\.REJECTED/.test(src),
    '只对 CORRUPT/REJECTED 备份；对 OK/NONE 也备份会堆积无用文件');
  assert.ok(/skipped: true, backupFailed: true/.test(src),
    '备份失败必须返回 skipped（fail-closed），不得降级为「无备份照写」');
});

// ---------- 输入层 · 参数解析（cli.cjs 纯函数） ----------
console.log('CLI 参数解析:');
const PA = a => CL.parseArgs(['node', 's', ...a]);
const RI = a => CL.resolveInputs(['node', 's', ...a]);
const throws = (fn, needle) => {
  try { fn(); }
  catch (e) {
    assert.ok(e instanceof CL.CliError, '应抛 CliError，实际抛 ' + (e && e.name));
    if (needle) assert.ok(String(e.message).includes(needle), '错误信息应含「' + needle + '」，实际首行: ' + String(e.message).split('\n')[0]);
    return;
  }
  throw new Error('应当抛错但未抛');
};
t('默认值全表（C2 冻结对象）', () => {
  const o = PA([]);
  assert.strictEqual(o.site, 'kuluer');
  assert.strictEqual(o.limit, 10);
  assert.strictEqual(o.fillMin, 0.9);
  assert.strictEqual(o.readyTimeoutSec, 45);
  assert.strictEqual(o.keywordTimeoutSec, 300);
  assert.strictEqual(o.gateTimeoutSec, 300);
  assert.deepStrictEqual(o.interval, [2500, 4500]);
  assert.strictEqual(o.headless, false);
  assert.strictEqual(o.enrichConcurrency, 4);   // v4.3 新增默认（取证：并发 4 零 429、提速 6.85×）
  assert.deepStrictEqual(o.keywords, []);
});
t('--limit 0 生效为 0（v3 缺陷：实得 10）', () => {
  assert.strictEqual(PA(['--limit', '0']).limit, 0);
});
t('--fill-min 0 生效为 0（v3 缺陷：实得 0.9）', () => {
  assert.strictEqual(PA(['--fill-min', '0']).fillMin, 0);
});
t('--fill-min 1（上界）合法', () => {
  assert.strictEqual(PA(['--fill-min', '1']).fillMin, 1);
});
t('--limit abc 报错（不再静默回落）', () => {
  throws(() => PA(['--limit', 'abc']), '需要整数');
});
t('--limit -1 报错（越下界）', () => {
  throws(() => PA(['--limit', '-1']), '超出允许范围');
});
t('--limit 1.5 报错（整数参数拒绝小数）', () => {
  throws(() => PA(['--limit', '1.5']), '需要整数');
});
t('--fill-min 1.5 报错（越上界）', () => {
  throws(() => PA(['--fill-min', '1.5']), '超出允许范围');
});
t('--interval abc 报错（提示需「下限,上限」格式）', () => {
  throws(() => PA(['--interval', 'abc']), '--interval');
});
t('--interval 2500,abc 报错（第二个值需整数）', () => {
  throws(() => PA(['--interval', '2500,abc']), '需要整数');
});
t('--interval 5,3 报错（下限 > 上限）', () => {
  throws(() => PA(['--interval', '5,3']), '下限 ≤ 上限');
});
t('--interval 0,0 合法（0 不被吞）', () => {
  assert.deepStrictEqual(PA(['--interval', '0,0']).interval, [0, 0]);
});
t('--interval 单值报错（需两个逗号分隔）', () => {
  throws(() => PA(['--interval', '2500']), '两个逗号分隔');
});
t('v4.3 --enrich-concurrency：默认 4 / 可设 1（回退串行）/ 越界与非法值报错', () => {
  assert.strictEqual(CL.TOOL_DEFAULTS.enrichConcurrency, 4);
  assert.strictEqual(PA([]).enrichConcurrency, 4);
  assert.strictEqual(PA(['--enrich-concurrency', '1']).enrichConcurrency, 1);
  assert.strictEqual(PA(['--enrich-concurrency', '16']).enrichConcurrency, 16);
  throws(() => PA(['--enrich-concurrency', '0']), '超出允许范围');
  throws(() => PA(['--enrich-concurrency', '99']), '超出允许范围');
  throws(() => PA(['--enrich-concurrency', 'abc']), '需要整数');
});
t('--keywords-file 缺值报错（不再静默 undefined）', () => {
  throws(() => PA(['--keywords-file']), '缺少取值');
});
t('--limit 缺值时撞上下一个 --flag → 报错而非吞掉', () => {
  throws(() => PA(['--limit', '--enrich']), '缺少取值');
});
t('--keywords 后跟未知长选项 → 报「未知参数」（v3 缺陷：静默吞掉）', () => {
  throws(() => PA(['--keywords', 'taurine', '--limt', '5']), '未知参数');
});
t('--keywords 无任何取值 → 报错', () => {
  throws(() => PA(['--keywords']), '缺少取值');
});
t('未知参数 --bogus → 报错并给指引', () => {
  throws(() => PA(['--bogus']), '未知参数');
});
t('重复布尔标志产生 notice（不静默）', () => {
  const o = PA(['--headless', '--headless']);
  assert.strictEqual(o.headless, true);
  assert.ok(o.notices.some(n => n.includes('重复')), '应提示重复');
});
t('单次布尔标志不产生重复 notice', () => {
  assert.strictEqual(PA(['--headless']).notices.length, 0);
});
t('--out 与 --dir 等价（同一个 out 字段）', () => {
  assert.strictEqual(PA(['--out', 'X']).out, 'X');
  assert.strictEqual(PA(['--dir', 'X']).out, 'X');
});

// ---------- 输入层 · 关键词归一与命名 ----------
console.log('关键词归一与命名:');
t('normKw 归一 BOM / CR / 全角空格 / NBSP', () => {
  assert.strictEqual(CL.normKw('\uFEFF牛磺酸\u3000猫\r\n'), '牛磺酸 猫');
  assert.strictEqual(CL.normKw('a\u00A0b'), 'a b');
});
t('normKw 剔除零宽字符（否则编进 URL 变另一条检索式）', () => {
  assert.strictEqual(CL.normKw('tau\u200Bri\u200Dne'), 'taurine');
});
t('normKw null 安全', () => {
  assert.strictEqual(CL.normKw(null), '');
  assert.strictEqual(CL.normKw(undefined), '');
});
t('kwIndexName 序号补零 + slug', () => {
  assert.strictEqual(CL.kwIndexName(1, 'protein digestibility dog'), '01-protein_digestibility_dog');
  assert.strictEqual(CL.kwIndexName(12, 'x'), '12-x');
});
t('三条「slug 相同」的检索式文件名必须互不相同（v3 磁盘层覆写缺陷）', () => {
  const names = [CL.kwIndexName(1, 'protein digestibility dog'), CL.kwIndexName(2, 'protein-digestibility dog'), CL.kwIndexName(3, 'protein.digestibility.dog')];
  assert.strictEqual(new Set(names).size, 3, '实际: ' + JSON.stringify(names));
});
t('slug 空串保底为 kw', () => {
  assert.strictEqual(CL.slug(''), 'kw');
  assert.strictEqual(CL.slug(null), 'kw');
});

// ---------- 输入层 · 文件通道 ----------
console.log('文件通道（keywords / plan / ensureDir）:');
const TMP = fs.mkdtempSync(path.join(os.tmpdir(), 'pbs-ut-'));
const tmpWrite = (name, body) => { const p = path.join(TMP, name); fs.writeFileSync(p, body, 'utf8'); return p; };
t('readKeywordsFile 支持 # 注释 / CRLF / BOM / 全角空格', () => {
  const p = tmpWrite('kw.txt', '\uFEFF# 注释行\r\ntaurine cat \r\n\u3000protein dog\u3000\n');
  assert.deepStrictEqual(CL.readKeywordsFile(p), ['taurine cat', 'protein dog']);
});
t('readKeywordsFile 文件不存在 → CliError（可执行提示）', () => {
  throws(() => CL.readKeywordsFile(path.join(TMP, 'no-such-file.txt')), '不存在');
});
t('readKeywordsFile 指向目录 → CliError', () => {
  throws(() => CL.readKeywordsFile(TMP), '目录');
});
t('mergeKeywords：命令行在前、去重保留首次（命令行优先）', () => {
  assert.deepStrictEqual(CL.mergeKeywords(['a', 'b'], ['b', 'c']), ['a', 'b', 'c']);
});
t('resolveInputs：命令行 + 文件合并并可回显来源', () => {
  const p = tmpWrite('kw2.txt', 'b\nc\n');
  const o = RI(['--keywords', 'a', '--keywords-file', p]);
  assert.deepStrictEqual(o.keywords, ['a', 'b', 'c']);
  assert.strictEqual(o.cliKeywords.length, 1);
  assert.strictEqual(o.fileKeywords.length, 2);
  assert.ok(CL.describeKeywordSources(o).includes('来源: 命令行 1 + 文件 2'));
});
t('resolveInputs：多条不含空格的关键词 → 提示疑似拆分（v3 静默缺陷）', () => {
  const o = RI(['--keywords', 'a', 'b', 'c']);
  assert.strictEqual(o.cliKeywords.length, 3);
  assert.ok(o.notices.some(n => n.includes('条独立关键词')), '应提示疑似拆分');
});
t('resolveInputs：一条含空格的检索式 → 不提示拆分', () => {
  const o = RI(['--keywords', 'a b c']);
  assert.strictEqual(o.cliKeywords.length, 1);
  assert.strictEqual(o.notices.length, 0);
});
t('loadPlan：解析失败只告警不抛错（旧设计保留）', () => {
  const p = tmpWrite('bad-plan.json', '{ not json');
  const r = CL.loadPlan(p);
  assert.deepStrictEqual(r.refs, {});
  assert.ok(r.warning && r.warning.includes('plan.json 解析失败'));
});
t('loadPlan：正常映射 query → 章节来源', () => {
  const p = tmpWrite('plan.json', JSON.stringify({ plans: [{ query: 'taurine cat', source: 'S3.1', sourceRefs: ['A', 'B'] }] }));
  const r = CL.loadPlan(p);
  assert.strictEqual(r.mapped, 1);
  assert.strictEqual(r.refs['taurine cat'], 'S3.1 | A / B');
});
t('ensureDir：缺失即创建', () => {
  const d = path.join(TMP, 'made-up-dir');
  assert.strictEqual(CL.ensureDir(d), d);
  assert.ok(fs.statSync(d).isDirectory());
});
t('ensureDir：指向已存在的普通文件 → CliError（不删用户文件）', () => {
  const f = tmpWrite('plain.txt', 'x');
  throws(() => CL.ensureDir(f), '需要目录');
});
t('ensureDir：空路径 → CliError', () => {
  throws(() => CL.ensureDir(''), '输出目录为空');
});

// ---------- 汇总层 · 陈旧 / 损坏 raw 隔离 ----------
console.log('汇总层：陈旧 / 损坏 raw 隔离:');
const mkDir = name => { const d = path.join(TMP, name); fs.mkdirSync(path.join(d, 'raw'), { recursive: true }); return d; };
const putRaw = (d, file, obj) => fs.writeFileSync(path.join(d, 'raw', file), obj === null ? '{ broken' : JSON.stringify(obj), 'utf8');
const R1 = (kw, title) => ({ runId: 'R1', keyword: kw, records: [{ idx: 1, titleEn: title }] });
const R0 = (kw, title) => ({ runId: 'R0', keyword: kw, records: [{ idx: 1, titleEn: title }] });

t('readRawGroups：runId 不匹配 → 判陈旧并单列', () => {
  const d = mkDir('rg-stale');
  putRaw(d, '01-n.json', R1('new_kw', 'NEW'));
  putRaw(d, '00-o.json', R0('old_kw', 'STALE'));
  const r = AR.readRawGroups(path.join(d, 'raw'), 'R1');
  assert.strictEqual(r.groups.length, 1);
  assert.strictEqual(r.groups[0].keyword, 'new_kw');
  assert.deepStrictEqual(r.skippedStale.map(s => s.file), ['00-o.json']);
});
t('readRawGroups：summaryRunId=null → 一律不过滤（旧产物可复现）', () => {
  const d = mkDir('rg-nofilter');
  putRaw(d, '01-n.json', R1('new_kw', 'NEW'));
  putRaw(d, '00-o.json', R0('old_kw', 'STALE'));
  const r = AR.readRawGroups(path.join(d, 'raw'), null);
  assert.strictEqual(r.groups.length, 2);
  assert.strictEqual(r.skippedStale.length, 0);
});
t('readRawGroups：损坏 JSON → 跳过并登记，不中断读取', () => {
  const d = mkDir('rg-corrupt');
  putRaw(d, '01-n.json', R1('new_kw', 'NEW'));
  putRaw(d, '02-broken.json', null);
  const r = AR.readRawGroups(path.join(d, 'raw'), 'R1');
  assert.strictEqual(r.groups.length, 1);
  assert.strictEqual(r.skippedCorrupt.length, 1);
  assert.strictEqual(r.skippedCorrupt[0].file, '02-broken.json');
});
t('readRawGroups：本次有 runId 但文件无 → legacy 兼容纳入并登记', () => {
  const d = mkDir('rg-legacy');
  putRaw(d, 'leg.json', { keyword: 'leg_kw', records: [{ idx: 1, titleEn: 'LEG' }] });
  const r = AR.readRawGroups(path.join(d, 'raw'), 'R1');
  assert.strictEqual(r.groups.length, 1);
  assert.deepStrictEqual(r.legacyNoRunId, ['leg.json']);
});
t('readRawGroups：raw 目录缺失 → 空结果不崩', () => {
  // 故意指向一个从未创建的目录（不做删除，避免依赖文件系统删除语义）
  const r = AR.readRawGroups(path.join(TMP, 'rg-noraw-never-exists', 'raw'), 'R1');
  assert.deepStrictEqual(r.groups, []);
  assert.deepStrictEqual(r.skippedCorrupt, []);
});
t('assemble：陈旧 raw 不得进入报告，且报告头显式登记「已忽略」', () => {
  const d = mkDir('as-stale');
  putRaw(d, '01-n.json', R1('new_kw', 'THIS_RUN_PAPER'));
  putRaw(d, '00-o.json', R0('old_kw', 'STALE_PAPER_FROM_PREVIOUS_RUN'));
  fs.writeFileSync(path.join(d, 'summary.json'), JSON.stringify({ runId: 'R1', startedAt: 'now', site: 'kuluer', keywords: { new_kw: { count: 1 } } }), 'utf8');
  const out = AR.assemble({ dir: d, format: 'both' });
  const md = fs.readFileSync(out.md, 'utf8');
  assert.ok(md.includes('THIS_RUN_PAPER'), '本轮文献应在报告中');
  assert.strictEqual(md.includes('STALE_PAPER_FROM_PREVIOUS_RUN'), false, '陈旧文献不得出现');
  assert.ok(md.includes('已忽略 1 个'), '报告头应显式登记已忽略数');
  assert.strictEqual(out.skippedStale, 1);
  assert.strictEqual(out.total, 1);
});
t('assemble：损坏 JSON 不毁整份报告，且显式登记「已跳过」', () => {
  const d = mkDir('as-corrupt');
  putRaw(d, '01-n.json', R1('new_kw', 'THIS_RUN_PAPER'));
  putRaw(d, '02-broken.json', null);
  fs.writeFileSync(path.join(d, 'summary.json'), JSON.stringify({ runId: 'R1', startedAt: 'now', site: 'kuluer', keywords: { new_kw: { count: 1 } } }), 'utf8');
  const out = AR.assemble({ dir: d, format: 'both' });
  const md = fs.readFileSync(out.md, 'utf8');
  assert.ok(md.includes('THIS_RUN_PAPER'));
  assert.ok(md.includes('已跳过 1 个'));
  assert.strictEqual(out.skippedCorrupt, 1);
});
t('assemble：summary 中记录过但 raw 缺失的关键词必须显式列出（非静默丢失）', () => {
  const d = mkDir('as-missing');
  putRaw(d, '01-n.json', R1('new_kw', 'A'));
  fs.writeFileSync(path.join(d, 'summary.json'), JSON.stringify({ runId: 'R1', startedAt: 'now', site: 'kuluer', keywords: { new_kw: { count: 1 }, gone_kw: { count: 0, aborted: 'no_results_unconfirmed' } } }), 'utf8');
  const out = AR.assemble({ dir: d, format: 'md' });
  const md = fs.readFileSync(out.md, 'utf8');
  assert.ok(md.includes('关键词：gone_kw'), '缺失关键词应成段列出');
  assert.ok(md.includes('no_results_unconfirmed'));
});
t('assemble：无异常时报告头不得出现「已忽略/已跳过」段（零回归前提）', () => {
  const d = mkDir('as-clean');
  putRaw(d, '01-n.json', R1('new_kw', 'CLEAN'));
  fs.writeFileSync(path.join(d, 'summary.json'), JSON.stringify({ runId: 'R1', startedAt: 'now', site: 'kuluer', keywords: { new_kw: { count: 1 } } }), 'utf8');
  const out = AR.assemble({ dir: d, format: 'md' });
  const md = fs.readFileSync(out.md, 'utf8');
  assert.strictEqual(/已忽略 \d+ 个/.test(md), false);
  assert.strictEqual(/已跳过 \d+ 个/.test(md), false);
  assert.strictEqual(/未标记 runId/.test(md), false);
});
t('assemble.parseArgs：--out 与 --dir 等价', () => {
  assert.strictEqual(AR.parseArgs(['node', 's', '--out', 'X']).dir, 'X');
  assert.strictEqual(AR.parseArgs(['node', 's', '--dir', 'X']).dir, 'X');
});
t('assemble.parseArgs：--md 缺值 → CliError', () => {
  throws(() => AR.parseArgs(['node', 's', '--dir', 'X', '--md']), '缺少取值');
});
t('assemble.parseArgs：缺 --dir → CliError', () => {
  throws(() => AR.parseArgs(['node', 's']), '必须提供 --dir');
});
t('assemble.parseArgs：未知参数 → CliError', () => {
  throws(() => AR.parseArgs(['node', 's', '--dir', 'X', '--bogus']), '未知参数');
});
t('assemble.csvEsc：逗号 / 引号 / 换行转义', () => {
  assert.strictEqual(AR.csvEsc('a,b'), '"a,b"');
  assert.strictEqual(AR.csvEsc('say "hi"'), '"say ""hi"""');
  assert.strictEqual(AR.csvEsc('l1\nl2'), '"l1\nl2"');
  assert.strictEqual(AR.csvEsc(null), '');
});

// ---------- 汇总层 · v4.3 D 档成因分开呈现 ----------
console.log('汇总层 v4.3（D 档成因）:');
const evBase = () => ({
  inputs: { abstractSource: 'epmc_full' }, evidenceGrade: 'D', evidenceGradeLabel: '证据薄弱或信息不足',
  designLevel: { value: 'U', label: '无法判定（信息不足）', confidence: 'none', candidates: [], conflictingTypes: [], topType: null },
  speciesRelevance: { label: '犬猫靶动物', confidence: 'medium', targetSpecies: ['犬'], detected: [], needsManualExclude: false },
  sampleSize: { value: null, candidates: [], confidence: 'none' },
  dose: { candidates: [], confidence: 'none' },
  includedStudies: { value: null, candidates: [] },
  flags: ['design_unknown'], needsReview: true,
});
t('★ 报告层：D 档「设计未识别」与「确证薄弱」必须区分呈现', () => {
  const unrec = AR.evidenceLines(Object.assign(evBase(), { gradeBasis: 'design_unrecognized' })).join('\n');
  const weak = AR.evidenceLines(Object.assign(evBase(), { gradeBasis: 'design_identified' })).join('\n');
  assert.ok(unrec.includes('设计未识别所致'), '未识别成因应显式标注');
  assert.strictEqual(weak.includes('设计未识别所致'), false, '确证薄弱不得标注为未识别');
});
t('★ 零回归：旧数据（无 gradeBasis 字段）渲染必须与「已判定」逐字节一致', () => {
  const old = AR.evidenceLines(evBase()).join('\n');                                   // 旧 raw：无该字段
  const weak = AR.evidenceLines(Object.assign(evBase(), { gradeBasis: 'design_identified' })).join('\n');
  assert.strictEqual(old, weak, '新增字段不得改变旧数据的渲染结果');
});
t('报告层：summary 证据分级行附 D 档成因分解（仅在 gradeBasisStat 存在时）', () => {
  const d = mkDir('v43-basis');
  putRaw(d, '01-k.json', {
    runId: 'R1', keyword: 'k', records: [{
      idx: 1, titleEn: 'T',
      evidence: Object.assign(evBase(), { gradeBasis: 'design_unrecognized' }),
    }],
  });
  fs.writeFileSync(path.join(d, 'summary.json'), JSON.stringify({
    runId: 'R1', startedAt: 'now', site: 'kuluer', keywords: { k: { count: 1 } },
    qc: { fill: { title: 1, authors: 1, source: 1, year: 1, abstract: 1, zh: 0 } },
    evidence: { graded: 1, gradeStat: { D: 1 }, designStat: { U: 1 }, speciesStat: {}, flagStat: {}, gradeBasisStat: { design_unrecognized: 1, design_identified: 0 }, needsManualExcludeCount: 0, lowConfidenceCount: 1 },
  }), 'utf8');
  const md = fs.readFileSync(AR.assemble({ dir: d, format: 'md' }).md, 'utf8');
  assert.ok(md.includes('**D 档成因**：设计未识别 1 条'), 'summary 行应含 D 档成因分解');
  assert.ok(md.includes('设计未识别所致'), '逐条证据行应标注未识别成因');
});
t('★ 零回归：summary 无 gradeBasisStat（旧产物）时该行不得改变', () => {
  const d = mkDir('v43-basis-old');
  putRaw(d, '01-k.json', { runId: 'R1', keyword: 'k', records: [{ idx: 1, titleEn: 'T', evidence: evBase() }] });
  fs.writeFileSync(path.join(d, 'summary.json'), JSON.stringify({
    runId: 'R1', startedAt: 'now', site: 'kuluer', keywords: { k: { count: 1 } },
    evidence: { graded: 1, gradeStat: { D: 1 }, designStat: {}, speciesStat: {}, flagStat: {}, needsManualExcludeCount: 0, lowConfidenceCount: 1 },
  }), 'utf8');
  const md = fs.readFileSync(AR.assemble({ dir: d, format: 'md' }).md, 'utf8');
  assert.strictEqual(md.includes('D 档成因'), false, '旧产物不得出现新增字段');
});

// ---------- QC 与计数探针（v4.6：--limit 0 的「0 条」是预期结果，不是静默降级） ----------
console.log('QC 与计数探针（v4.6）:');

t('★ --limit 0 计数探针：QC 必须豁免（旧行为 ⇒ 0 条必判失败 +「疑似选择器失效」假诊断 ⇒ exit 4）', () => {
  const r = ENR.qcCheck([{ keyword: 'x', records: [] }], { titleMin: 0.9, limit: 0 });
  assert.strictEqual(r.ok, true, '计数探针仍被判 QC 失败 ⇒ 会产生 exit 4 假诊断');
  assert.strictEqual(r.skipped, 'limit_0_count_only_probe', '未标记豁免原因（豁免必须可见，不得静默跳过）');
  assert.strictEqual(r.fill, null, '探针模式下不得给出误导性填充率');
});
t('★ 回归：--limit > 0 时 0 条记录仍必须判 QC 失败（豁免不得外溢）', () => {
  const r = ENR.qcCheck([{ keyword: 'x', records: [] }], { titleMin: 0.9, limit: 10 });
  assert.strictEqual(r.ok, false, '正常模式下 0 条必须仍判失败 ⇒ 否则「静默降级」防线失效');
  assert.ok(r.issues.some(s => /标题填充率/.test(s)), '失败原因必须仍指向填充率');
});
t('★ 回归：不传 limit（默认模式）与传 limit=10 判据必须完全一致', () => {
  const a = ENR.qcCheck([{ keyword: 'x', records: [] }], { titleMin: 0.9 });
  const b = ENR.qcCheck([{ keyword: 'x', records: [] }], { titleMin: 0.9, limit: 10 });
  assert.strictEqual(a.ok, b.ok, '未传 limit 不得改变判据');
  assert.deepStrictEqual(a.issues, b.issues, '未传 limit 不得改变失败原因');
});

// ---------- 站点白名单（v4.1：未接通站点不得静默回落） ----------
console.log('站点白名单:');
const capture = fn => { try { fn(); } catch (e) { return e; } throw new Error('应当抛错但未抛'); };

t('--site kuluer 正常通过', () => {
  assert.strictEqual(PA(['--site', 'kuluer']).site, 'kuluer');
});
t('--site 省略时默认 kuluer', () => {
  assert.strictEqual(PA([]).site, 'kuluer');
});
t('--site panda985 显式报错（禁止静默回落）', () => {
  const e = capture(() => PA(['--site', 'panda985']));
  assert.ok(e instanceof CL.CliError, '应抛 CliError，实际 ' + (e && e.name));
  const msg = String(e.message);
  assert.ok(msg.includes('尚未接通'), '错误信息应含「尚未接通」，实际首行: ' + msg.split('\n')[0]);
  assert.ok(/当前可用站点:\s*kuluer/.test(msg), '未给出可用站点清单');
});
t('--site 未知取值报错并列出白名单', () => {
  const e = capture(() => PA(['--site', 'example.com']));
  assert.ok(e instanceof CL.CliError, '应抛 CliError');
  const msg = String(e.message);
  assert.ok(msg.includes('取值不识别'), '应提示取值不识别');
  assert.ok(/当前可用站点:\s*kuluer/.test(msg), '未列出可用站点');
});
t('站点白名单与抓取实现一致（防「只放白名单不接通」）', () => {
  assert.deepStrictEqual(CL.SUPPORTED_SITES.slice(), ['kuluer'],
    '白名单已变更但未同步本判据与 SKILL.md 参数表');
  const spTxt = fs.readFileSync(path.join(__dirname, 'search-papers.cjs'), 'utf8');
  assert.ok(/kuluer\.com\/scholar/.test(spTxt), '未检出 kuluer 抓取 URL（实现已变？）');
  // 将来若接通 panda985，此断言会红 —— 提示必须同步 SUPPORTED_SITES，避免元数据说谎
  assert.strictEqual(
    /function\s+searchPanda985|opts\.site\s*===\s*'panda985'|site\s*===\s*'panda985'\s*\)/.test(spTxt),
    false,
    '检出 panda985 抓取实现已接通，但白名单未放开 —— 请同步 SUPPORTED_SITES 后再改本判据');
});

// ---------- 多源层（v4.15 A 批）：归一化 / 注册表 / 调度器 ----------
// 这批用例的编写原则：**每条断言背后的取值都来自 2026-10-26 的一手实测**，
// 而不是从文档抄来的期望。凡属「实测才知道」的（Crossref 忽略布尔、OpenAlex mailto 不提升限额、
// fibre/fiber 折叠），都在用例名里写明实测事实，避免后人以为是我拍的。
console.log('多源归一化（normalize）:');
t('booleanToBag 剥布尔运算符与括号（实测：Crossref 布尔式与词袋结果逐字相同）', () => {
  assert.strictEqual(NRM.booleanToBag('(cat OR feline) AND (hairball OR trichobezoar)'),
    'cat feline hairball trichobezoar');
});
t('booleanToBag 去重且保留首次出现顺序', () => {
  assert.strictEqual(NRM.booleanToBag('cat AND cat OR Feline AND cat'), 'cat Feline');
});
t('booleanToBag 剥掉字段前缀（EPMC 语法的 TITLE_ABS: 等不能进词袋）', () => {
  assert.strictEqual(NRM.booleanToBag('TITLE_ABS:"hairball" AND TITLE_ABS:"cat"'), 'hairball cat');
});
t('normDoi 归一 URL / 大写 / doi: 前缀 / 尾部标点', () => {
  assert.strictEqual(NRM.normDoi('https://doi.org/10.1017/JNS.2014.27'), '10.1017/jns.2014.27');
  assert.strictEqual(NRM.normDoi('doi: 10.1016/S0372-5545(17)44666-9.'), '10.1016/s0372-5545(17)44666-9');
  assert.strictEqual(NRM.normDoi('10.3390/ani11071853'), '10.3390/ani11071853');
});
t('normDoi 非 DOI 一律 null（不臆造）', () => {
  assert.strictEqual(NRM.normDoi('not-a-doi'), null);
  assert.strictEqual(NRM.normDoi(''), null);
  assert.strictEqual(NRM.normDoi(null), null);
  assert.strictEqual(NRM.normDoi('10.1'), null);
});
t('stemWord 英式/美式拼写折叠到同一键（跨源去重的关键，实测踩过 fibre/fiber）', () => {
  const pairs = [['fibre', 'fiber'], ['faecal', 'fecal'], ['oesophageal', 'esophageal'],
    ['colour', 'color'], ['tumours', 'tumor'], ['diarrhoea', 'diarrhea']];
  for (const [a, b] of pairs) assert.strictEqual(NRM.stemWord(a), NRM.stemWord(b), a + ' vs ' + b);
});
t('★ 反向断言：stemWord 不做通用折叠（there/where/store/sphere 必须互异）', () => {
  // 若有人把白名单换成 our→or / re→er 通用规则，本用例会红：那是「误合并两条不同文献」的入口。
  const ws = ['there', 'where', 'store', 'sphere'];
  const got = ws.map(w => NRM.stemWord(w));
  assert.strictEqual(new Set(got).size, ws.length, '出现通用折叠导致的键碰撞: ' + got.join(','));
});
t('normTitleKey 英式/美式标题撞同一键（这是 no-DOI 合并的前提）', () => {
  assert.strictEqual(
    NRM.normTitleKey('Effects of dietary fibre on hairball excretion'),
    NRM.normTitleKey('Effects of Dietary Fiber on Hairball Excretion'));
});
t('normTitleKey 单复数归一（effects / effect 不分家）', () => {
  assert.strictEqual(NRM.normTitleKey('Effect of fiber'), NRM.normTitleKey('Effects of fibers'));
});
t('abstractFromInvertedIndex 按位置还原语序（乱序输入）', () => {
  assert.strictEqual(NRM.abstractFromInvertedIndex({ world: [1], hello: [0], again: [2] }), 'hello world again');
});
t('abstractFromInvertedIndex 空 / 异常输入 → null（不返回空串冒充摘要）', () => {
  assert.strictEqual(NRM.abstractFromInvertedIndex(null), null);
  assert.strictEqual(NRM.abstractFromInvertedIndex({}), null);
  assert.strictEqual(NRM.abstractFromInvertedIndex({ a: 'not-array' }), null);
});
t('stripJats 剥标签并解实体（Crossref 摘要自带 jats: 标签，不剥会直接印进报告）', () => {
  const s = NRM.stripJats('<jats:p>Effects of <jats:italic>fibre</jats:italic> on &lt;cats&gt; &amp; dogs.</jats:p>');
  assert.strictEqual(/<jats/i.test(s), false, '仍残留标签: ' + s);
  assert.strictEqual(/&lt;|&amp;/.test(s), false, '实体未解码: ' + s);
  assert.ok(s.includes('<cats>'), '实体解码结果不对: ' + s);
});
t('canonicalRecord 保证 RECORD_KEYS 全部存在（空输入也不缺 key）', () => {
  const r = NRM.canonicalRecord({}, { keyword: 'k' });
  for (const k of NRM.RECORD_KEYS) assert.ok(Object.prototype.hasOwnProperty.call(r, k), '缺 key: ' + k);
  assert.strictEqual(r.keyword, 'k');
  assert.strictEqual(r.page, 1);
});
t('canonicalRecord 对 HTTP 源 translateStatus 必须为 null（否则 prisma:176 误记异常行）', () => {
  const r = NRM.canonicalRecord({ titleEn: 'X' }, { sourceId: 'europepmc' });
  assert.strictEqual(r.translateStatus, null);
  assert.strictEqual(r.translatedBySite, false);
  // 反证：prisma 的判据是 `if (r.translateStatus && r.translateStatus !== 'ok')`，null 必须被跳过
  assert.strictEqual(Boolean(r.translateStatus && r.translateStatus !== 'ok'), false);
});
t('canonicalRecord 从 doiFromUrl 反推 doi 并回填 sourceUrl', () => {
  const r = NRM.canonicalRecord({ titleEn: 'X', doiFromUrl: 'https://doi.org/10.1000/ABC' }, {});
  assert.strictEqual(r.doi, '10.1000/abc');
  assert.strictEqual(r.sourceUrl, 'https://doi.org/10.1000/abc');
});
t('canonicalRecord 年份非法 → null（不臆造）、合法带日期 → 取年份', () => {
  assert.strictEqual(NRM.canonicalRecord({ titleEn: 'X', year: 'n.d.' }, {}).year, null);
  assert.strictEqual(NRM.canonicalRecord({ titleEn: 'X', year: '2020-05-01' }, {}).year, 2020);
});
t('mergeInto 只填空不覆盖（注册表顺序 = 优先级）', () => {
  const a = { titleEn: 'T', doi: '10.1/x', source: 'Nature', year: 2020, provenance: { sourceId: 'europepmc' } };
  NRM.mergeInto(a, { titleEn: 'Other', doi: '10.1/x', source: 'Other Journal', year: 1999, provenance: { sourceId: 'crossref' } });
  assert.strictEqual(a.source, 'Nature', '高优先级源的字段被低优先级源改掉了');
  assert.strictEqual(a.year, 2020);
  assert.deepStrictEqual(a.provenance.alsoFoundIn, ['crossref']);
});
t('mergeInto 摘要取更长的那份（「有摘要」与「只有一句」的差别）', () => {
  const a = { titleEn: 'T', abstractEn: 'short', provenance: { sourceId: 'a' } };
  NRM.mergeInto(a, { titleEn: 'T', abstractEn: 'x'.repeat(100), provenance: { sourceId: 'b' } });
  assert.strictEqual(a.abstractEn.length, 100);
});

console.log('源注册表（sources/index）:');
t('validateAll 全部已注册源均满足契约（新增源忘实现 search 会在这里红）', () => {
  const all = SRC.validateAll();
  assert.ok(all.length >= 2, '注册源少于 2 个，多源降级无从谈起');
  for (const v of all) assert.ok(v.ok, v.key + ': ' + v.errors.join('; '));
});
t('validateConnector 缺 search 方法时报错并点名', () => {
  const bad = { id: 'x', label: 'X', kind: 'http', queryDialect: 'boolean', countSemantics: 'exact', capabilities: { abstract: true, doi: true, oa: true, translate: false } };
  const v = SRC.validateConnector(bad);
  assert.strictEqual(v.ok, false);
  assert.ok(v.errors.some(e => e.includes('search')), '未点名 search: ' + v.errors.join('; '));
});
t('validateConnector 拒绝非法枚举（kind / queryDialect / countSemantics）', () => {
  const bad = { id: 'x', label: 'X', kind: 'ftp', queryDialect: 'sql', countSemantics: 'maybe', capabilities: { abstract: true, doi: true, oa: true, translate: false }, search() {} };
  const v = SRC.validateConnector(bad);
  assert.strictEqual(v.ok, false);
  assert.strictEqual(v.errors.filter(e => e.startsWith('取值非法')).length, 3);
});
t('capabilities 必须显式声明四项能力（不得省略后由下游猜）', () => {
  const bad = { id: 'x', label: 'X', kind: 'http', queryDialect: 'boolean', countSemantics: 'exact', capabilities: {}, search() {} };
  const v = SRC.validateConnector(bad);
  assert.strictEqual(v.ok, false);
  assert.ok(v.errors.filter(e => e.includes('capabilities.')).length >= 4);
});
t('resolveSources 未知源必须报错（不静默回落默认源）', () => {
  assert.throws(() => SRC.resolveSources('scihub'), /未知源/);
  assert.throws(() => SRC.resolveSources('all,-nosuch'), /未知源/);
});
t('resolveSources 支持预设与排除语法', () => {
  assert.deepStrictEqual(SRC.resolveSources('europepmc'), ['europepmc']);
  assert.deepStrictEqual(SRC.resolveSources('europepmc,crossref'), ['europepmc', 'crossref']);
  assert.deepStrictEqual(SRC.resolveSources('all,-crossref').includes('crossref'), false);
  assert.deepStrictEqual(SRC.resolveSources('http').length >= 1, true);
});
t('resolveSources 排除后为空 → 报错（不得静默返回空源列表）', () => {
  assert.throws(() => SRC.resolveSources('europepmc,-europepmc'), /源列表为空/);
});
t('★ 注册表声明与实测一致（crossref 计数不可用 / 只认词袋；europepmc 计数可用 / 认布尔）', () => {
  const cr = SRC.getSource('crossref');
  const ep = SRC.getSource('europepmc');
  assert.strictEqual(cr.countSemantics, 'none', 'Crossref 的 total-results 是全库软匹配规模，禁止当计数');
  assert.strictEqual(cr.queryDialect, 'bag', 'Crossref 实测不解析布尔运算符，必须转译');
  assert.strictEqual(ep.countSemantics, 'exact');
  assert.strictEqual(ep.queryDialect, 'boolean', 'EPMC 实测直吃布尔式');
});

console.log('多源调度（scheduler）:');
t('dedupeCrossSource DOI 合并：URL 形态与裸 DOI 视为同一篇', () => {
  const d = SCH.dedupeCrossSource([
    { titleEn: 'T1 on cats', doi: '10.1017/jns.2014.27', provenance: { sourceId: 'europepmc' } },
    { titleEn: 'T1 on cats', doi: 'https://doi.org/10.1017/JNS.2014.27', provenance: { sourceId: 'crossref' } },
  ]);
  assert.strictEqual(d.stat.before, 2);
  assert.strictEqual(d.stat.after, 1);
  assert.strictEqual(d.stat.mergedByDoi, 1);
  assert.strictEqual(d.stat.mergedCrossSource, 1, '跨源合并未计数，降级报告会低估重复率');
});
t('dedupeCrossSource 无 DOI 时按标题 + 年份容差 ±1 合并（epub 与正式发表常差 1 年）', () => {
  const d = SCH.dedupeCrossSource([
    { titleEn: 'Effects of dietary fibre on hairball excretion', doi: null, year: 2019, provenance: { sourceId: 'europepmc' } },
    { titleEn: 'Effects of Dietary Fiber on Hairball Excretion', doi: null, year: 2020, pmid: '999', provenance: { sourceId: 'crossref' } },
  ]);
  assert.strictEqual(d.stat.after, 1, '英式/美式拼写导致同一篇被算两条');
  assert.strictEqual(d.stat.mergedByTitle, 1);
  assert.strictEqual(d.records[0].pmid, '999', '合并后未补上新源的字段');
});
t('dedupeCrossSource 年份超容差（差 3 年）不合并 —— 宁可漏合并，不可误合并', () => {
  const d = SCH.dedupeCrossSource([
    { titleEn: 'Effects of dietary fibre on hairball excretion', doi: null, year: 2016, provenance: { sourceId: 'europepmc' } },
    { titleEn: 'Effects of dietary fibre on hairball excretion', doi: null, year: 2019, provenance: { sourceId: 'crossref' } },
  ]);
  assert.strictEqual(d.stat.after, 2);
});
t('dedupeCrossSource 无标题记录被丢弃（对证据表无价值）', () => {
  const d = SCH.dedupeCrossSource([
    { titleEn: null, doi: '10.1/a', provenance: { sourceId: 'europepmc' } },
    { titleEn: 'Real title', doi: '10.1/b', provenance: { sourceId: 'europepmc' } },
  ]);
  assert.strictEqual(d.stat.after, 1);
});
t('degradeWarnings 对「全部源皆挂」给出「勿据此排除检索式」', () => {
  const w = SCH.degradeWarnings({
    failures: [{ id: 'a', label: 'A', reason: 'x' }],
    perSource: [{ id: 'a', label: 'A', ok: false, count: 0, countState: 'collect_failed' }],
    siteDegraded: true,
  });
  assert.ok(w.some(s => s.includes('勿据此排除')), '缺少不可误排除的提示: ' + w.join(' | '));
});
t('degradeWarnings 对 countSemantics=none 的源明写「不是采集失败」', () => {
  const w = SCH.degradeWarnings({
    failures: [],
    perSource: [{ id: 'crossref', label: 'Crossref', ok: true, count: 5, countState: SCH.COUNT_NA }],
    siteDegraded: false,
  });
  assert.ok(w.some(s => s.includes('不是采集失败')), '缺少免责说明: ' + w.join(' | '));
});

// ---------- v4.15（A-2 批）：CLI 接线 / 多源聚合 / PRISMA 多源章节 ----------
console.log('CLI 多源接线（--sources）:');
{
  t('--sources all 解析为注册表全部源；默认（不给）仍是站点通道', () => {
    const a = CL.parseArgs(['node', 's', '--keywords', 'q', '--sources', 'all']);
    assert.deepStrictEqual(a.sourceIds, SRC.sourceIds(), 'all 未解析为全部已注册源');
    assert.deepStrictEqual(a.sourceIds, ['europepmc', 'crossref']);
    assert.strictEqual(a.sourceTimeoutSec, 120);
    assert.strictEqual(a.sourceConcurrency, 2);
    // 默认必须逐字保持 v4.14 行为：sources 为 null ⇒ 主脚本走浏览器站点通道
    const d = CL.parseArgs(['node', 's', '--keywords', 'q']);
    assert.strictEqual(d.sources, null);
    assert.strictEqual(d.sourceIds, null);
    // 排除式：all,-crossref 只留 EPMC
    assert.deepStrictEqual(CL.parseArgs(['node', 's', '--keywords', 'q', '--sources', 'all,-crossref']).sourceIds, ['europepmc']);
  });

  t('--sources kuluer 给「尚未接通 + 改法」而非「未知源」（用户必然先试这个值）', () => {
    assert.throws(() => CL.parseArgs(['node', 's', '--keywords', 'q', '--sources', 'kuluer']),
      (e) => /尚未接通/.test(e.message) && /去掉 --sources/.test(e.message), '缺少可执行的改法');
    // 混在列表里也要拦（否则会静默只跑一半源）
    assert.throws(() => CL.parseArgs(['node', 's', '--keywords', 'q', '--sources', 'all,kuluer']), /尚未接通/);
    assert.throws(() => CL.parseArgs(['node', 's', '--keywords', 'q', '--sources', 'scihub']), /--sources 取值无法解析/);
    assert.throws(() => CL.parseArgs(['node', 's', '--keywords', 'q', '--sources', '']), /不能为空/);
  });

  t('--sources 与 --site 互斥（两条通道不能混在一次运行里）', () => {
    assert.throws(() => CL.parseArgs(['node', 's', '--keywords', 'q', '--sources', 'all', '--site', 'kuluer']), /互斥/);
    // 单独给任一参数都必须正常
    assert.doesNotThrow(() => CL.parseArgs(['node', 's', '--keywords', 'q', '--site', 'kuluer']));
  });

  t('--mailto 格式错必须报错（错格式会被 Crossref 静默忽略，礼貌池不生效）', () => {
    assert.throws(() => CL.parseArgs(['node', 's', '--keywords', 'q', '--sources', 'all', '--mailto', 'not-an-email']), /邮箱格式/);
    assert.throws(() => CL.parseArgs(['node', 's', '--keywords', 'q', '--sources', 'all', '--mailto', 'a@b']), /邮箱格式/);
    assert.strictEqual(CL.parseArgs(['node', 's', '--keywords', 'q', '--sources', 'all', '--mailto', ' a@b.co ']).mailto, 'a@b.co');
  });

  t('★ --fulltext 的 --enrich 依赖在 --sources 下放宽（多源自带 pmcid），站点通道仍强制', () => {
    assert.doesNotThrow(() => CL.parseArgs(['node', 's', '--keywords', 'q', '--sources', 'all', '--fulltext']),
      '多源通道自带 pmcid，不应再强制 --enrich');
    // 断言「行为 + 两条改法」，不锁固定措辞：文案会随版本更新，
    // 但「必须报错」「必须指向 --enrich」「必须给出 --sources 这条出路」是不变要求。
    const msg = (() => { try { CL.parseArgs(['node', 's', '--keywords', 'q', '--fulltext']); return null; } catch (e) { return e.message; } })();
    assert.ok(msg, '站点通道缺 --enrich 时必须报错，不得静默空操作');
    assert.ok(/--enrich/.test(msg), '报错须指向 --enrich，实际：' + msg);
    assert.ok(/--sources/.test(msg), '报错须给出 --sources 这条改法，实际：' + msg);
  });

  t('describeSources：两条通道的通道名与参数可见（通道选择不可见时元数据会说谎）', () => {
    const m = CL.describeSources({ sourceIds: ['europepmc', 'crossref'], sourceTimeoutSec: 60, sourceConcurrency: 3, mailto: 'a@b.co', site: 'kuluer' });
    assert.ok(/HTTP 多源/.test(m) && /europepmc, crossref/.test(m), m);
    assert.ok(/不启动浏览器/.test(m) && /60s/.test(m) && /并发 3/.test(m) && /a@b\.co/.test(m), m);
    const s = CL.describeSources({ sourceIds: null, site: 'kuluer' });
    assert.ok(/站点 kuluer/.test(s) && !/多源/.test(s), s);
  });

  t('★ 源码守卫：多源通道不得启动浏览器（含 playwright 惰性加载、收尾判空）', () => {
    const sp = fs.readFileSync(path.join(__dirname, 'search-papers.cjs'), 'utf8');
    // 惰性加载：否则无 Edge/Chrome 的 CI 环境在 require 阶段就 exit(1)，多源通道根本起不来
    assert.ok(/let _chromium = null;/.test(sp) && /function chromium\(\)/.test(sp), 'playwright 未改惰性加载');
    assert.ok(!/^const \{ chromium \} = loadPlaywright\(\);/m.test(sp), '仍有顶层 chromium 解构（会在模块加载时退出）');
    // 三处必须同时成立：探测/启动/关闭都按 useMulti 分流
    assert.ok(/const exe = useMulti \? null : findBrowser\(\);/.test(sp), '多源下仍探测浏览器');
    assert.ok(/const browser = useMulti \? null : await chromium\(\)\.launch/.test(sp), '多源下仍启动浏览器');
    assert.ok(/if \(browser\) await browser\.close\(\)/.test(sp), '收尾未判空 browser（多源下会 TypeError 并吞掉退出码）');
  });
}
console.log('多源聚合层（lib/multi-run.cjs）:');
{
  const mkRes = (per, records) => ({
    records: records || [], perSource: per,
    dedupe: { before: (records || []).length, after: (records || []).length, removed: 0, mergedByDoi: 0, mergedByTitle: 0, mergedCrossSource: 0 },
    failures: per.filter(s => !s.ok).map(s => ({ id: s.id, label: s.label, reason: s.aborted })),
    degraded: [], anyEvidence: true, allFailed: per.length > 0 && per.every(s => !s.ok),
    siteDegraded: per.length > 0 && per.every(s => !s.ok), durationMs: 10,
  });
  const E = over => Object.assign({ id: 'europepmc', label: 'Europe PMC', kind: 'http', queryDialect: 'boolean', countSemantics: 'exact', ok: true, count: 5, reportedTotal: 219, countState: 'counted', aborted: null }, over);
  const C = over => Object.assign({ id: 'crossref', label: 'Crossref', kind: 'http', queryDialect: 'bag', countSemantics: 'none', ok: true, count: 5, reportedTotal: null, countState: 'not_applicable', aborted: null }, over);

  t('★ 计数只累加 exact 源：Crossref 的 775136 进不了合计（否则凭空放大四个数量级）', () => {
    const r = MR.buildKeywordResult({ res: mkRes([E(), C({ reportedTotal: 775136 })]), keyword: 'q', limit: 10 });
    assert.strictEqual(r.diagnostics.reportedTotal, 219, '合计被 none 型源污染');
    assert.strictEqual(r.diagnostics.countState, 'counted');
    assert.ok(r.diagnostics.sources.some(s => s.id === 'crossref' && s.reportedTotal === null), '逐源明细必须保留 none 源的 null');
  });

  t('★ 只跑 none 型源 ⇒ not_applicable（不是 collect_failed 假故障，也不是 0 命中）', () => {
    const r = MR.buildKeywordResult({ res: mkRes([C()]), keyword: 'q', limit: 10 });
    assert.strictEqual(r.diagnostics.reportedTotal, null);
    assert.strictEqual(r.diagnostics.countState, 'not_applicable');
    assert.strictEqual(r.diagnostics.noResultsSignal, false, '无读数不得被当成「明确 0 条」');
    // 反例：exact 源自己挂了（有能计数的源但没读到）才是 collect_failed
    const r2 = MR.buildKeywordResult({ res: mkRes([E({ ok: false, count: 0, reportedTotal: null, countState: 'collect_failed', aborted: 'rate_limited:429' })]), keyword: 'q', limit: 10 });
    assert.strictEqual(r2.diagnostics.countState, 'collect_failed');
  });

  t('★ idx 必须全局连续唯一（连接器给的是源内排名 ⇒ 直接用会得到 1..5,1..5）', () => {
    // ★ 夹具必须**带 idx**：真实连接器会写 idx=源内排名。首版夹具漏了 idx，
    //   结果「回退成 idx ?? i+1」这个变异打不红任何断言（变异自证实测 MISS）——
    //   夹具少了问题发生的前提，等于用例在测一个不会发生的情况。
    const mk = (sid, n) => Array.from({ length: n }, (_, i) => ({ titleEn: sid + i, idx: i + 1, provenance: { sourceId: sid, rank: i + 1 } }));
    const r = MR.buildKeywordResult({ res: mkRes([E(), C()], mk('europepmc', 3).concat(mk('crossref', 2))), keyword: 'q', limit: 10 });
    assert.deepStrictEqual(r.records.map(x => x.idx), [1, 2, 3, 4, 5], 'idx 不连续/重复');
    assert.strictEqual(new Set(r.records.map(x => x.idx)).size, 5);
    // 源内排名不丢：留在 provenance.rank
    assert.deepStrictEqual(r.records.map(x => x.provenance.rank), [1, 2, 3, 1, 2]);
    assert.ok(r.records.every(x => x.keyword === 'q'), '记录未补 keyword');
  });

  t('计数探针（limit 0）不保留任何记录：探针语义是「只读计数」', () => {
    const r = MR.buildKeywordResult({ res: mkRes([E()], [{ titleEn: 'x' }]), keyword: 'q', limit: 0 });
    assert.strictEqual(r.records.length, 0);
    assert.strictEqual(r.diagnostics.reportedTotal, 219, '探针模式仍必须拿到读数');
  });

  t('全部源不可用 ⇒ aborted=all_sources_failed（通道级故障，与「检索式无效」分开）', () => {
    const r = MR.buildKeywordResult({
      res: mkRes([E({ ok: false, reportedTotal: null, countState: 'collect_failed', aborted: 'scheduler_timeout:5000ms' })]),
      keyword: 'q', limit: 10,
    });
    assert.strictEqual(r.aborted, 'all_sources_failed');
    assert.ok(/none_available/.test(r.diagnostics.strategies[0].strategy));
  });

  t('★ 多源探针判定：not_applicable 既不是「读到」也不是「失败」，不得污染 siteDegraded', () => {
    const g1 = { keyword: 'q1', records: [], aborted: null, diagnostics: { countState: 'not_applicable', reportedTotal: null, durationMs: 5 } };
    const v1 = MR.multiProbeVerdict([g1], { limit: 10 });
    assert.deepStrictEqual(v1.failed, [], 'not_applicable 被误判成采集失败');
    assert.deepStrictEqual(v1.notApplicable, ['q1']);
    assert.strictEqual(v1.anyEvidence, false);
    // 一条都没抓到、也没有任何读数 ⇒ 这才算通道级降级
    assert.strictEqual(v1.siteDegraded, true);
    // 有读数（含明确 0）⇒ 不是降级
    const g2 = { keyword: 'q2', records: [], aborted: null, diagnostics: { countState: 'zero_confirmed', reportedTotal: 0, durationMs: 5 } };
    const v2 = MR.multiProbeVerdict([g2], { limit: 10 });
    assert.strictEqual(v2.siteDegraded, false);
    assert.deepStrictEqual(v2.zeroConfirmed, ['q2']);
    assert.strictEqual(v2.probe, false);
  });

  t('按源聚合：exact 源累加自报命中，none 源恒为 null（不可相加）', () => {
    const rows = MR.prismaRows('q1', [E(), C()]).concat(MR.prismaRows('q2', [E({ count: 3, reportedTotal: 141 }), C({ count: 2 })]));
    assert.strictEqual(rows.length, 4);
    const agg = MR.aggregateBySource(rows);
    const ep = agg.find(a => a.id === 'europepmc');
    const cr = agg.find(a => a.id === 'crossref');
    assert.strictEqual(ep.searches, 2);
    assert.strictEqual(ep.records, 8);
    assert.strictEqual(ep.reportedTotal, 360);
    assert.strictEqual(cr.reportedTotal, null, 'none 型源不得有合计');
    assert.strictEqual(cr.countKnown, false);
    assert.strictEqual(cr.records, 7);
  });

  t('源级告警按源聚合：同一源挂多条只报一次，但必须写清挂了几条', () => {
    const res1 = { perSource: [E({ ok: false, count: 0, reportedTotal: null, countState: 'collect_failed', aborted: 'rate_limited:429' }), C()] };
    const res2 = { perSource: [E({ ok: false, count: 0, reportedTotal: null, countState: 'collect_failed', aborted: 'rate_limited:429' }), C()] };
    const ws = MR.sourceWarnings([{ keyword: 'q1', res: res1 }, { keyword: 'q2', res: res2 }]);
    assert.strictEqual(ws.filter(w => w.startsWith('源 Europe PMC')).length, 1, '同一源重复告警');
    assert.ok(/2\/2 条检索式/.test(ws[0]), ws[0]);
    assert.ok(/其余源结果不受影响/.test(ws[0]));
    assert.ok(ws.some(w => /降级运行/.test(w)), '缺少降级运行结论');
    // 全挂时措辞必须变成「网络/服务级故障，勿据此排除检索式」
    const all = MR.sourceWarnings([{ keyword: 'q1', res: { perSource: [{ id: 'x', label: 'X', ok: false, aborted: 'boom', count: 0 }] } }]);
    assert.ok(all.some(w => /网络\/服务级故障/.test(w) && /勿据此排除/.test(w)), all.join('|'));
  });

  t('源读数行：探针模式必须写「未保留记录」，否则与 summary 的 0 条自相矛盾', () => {
    const rs = [{ keyword: 'q', res: { perSource: [E(), C()] } }];
    assert.ok(/取得 5 条/.test(MR.sourceSummaryLine(rs, { probe: false })));
    const p = MR.sourceSummaryLine(rs, { probe: true });
    assert.ok(/未保留记录/.test(p) && !/取得 5 条/.test(p), p);
    assert.strictEqual(MR.sourceSummaryLine([]), null);
  });
}

console.log('PRISMA 多源章节:');
{
  const srcRows = [
    { keyword: 'q1', id: 'europepmc', label: 'Europe PMC', kind: 'http', queryDialect: 'boolean', countSemantics: 'exact', count: 5, reportedTotal: 219, countState: 'counted', ok: true, aborted: null, durationMs: 800, queryUsed: null },
    { keyword: 'q1', id: 'crossref', label: 'Crossref', kind: 'http', queryDialect: 'bag', countSemantics: 'none', count: 5, reportedTotal: null, countState: 'not_applicable', ok: true, aborted: null, durationMs: 900, queryUsed: 'cat feline hairball' },
  ];
  const mkLog = () => P.buildLog({
    runs: [{ keyword: 'q1', reportedTotal: 219, countState: 'counted', retrieved: 10, translatedBySite: false, translateStatus: null, aborted: null, durationMs: 900 }],
    sources: srcRows,
    meta: { site: null, channel: 'http', sources: ['europepmc', 'crossref'], limit: 5, countOnlyProbe: false, toolVersion: 'x' },
  });

  t('多源：数据源名为源名拼接 + baseUrl 置 null + channel=http_multi_source（元数据不得说谎）', () => {
    const log = mkLog();
    assert.strictEqual(log.identification.database, 'Europe PMC + Crossref');
    assert.strictEqual(log.identification.baseUrl, null);
    assert.strictEqual(log.identification.channel, 'http_multi_source');
    assert.strictEqual(log.identification.dataSourceCount, 2);
    assert.ok(/countSemantics=exact/.test(log.identification.countSemanticsNote));
  });

  t('多源：Markdown 出现 2.1 各源读数，且 Crossref 计数列渲染为「不适用」而非 0/未读到', () => {
    const md = P.renderMarkdown(mkLog(), {});
    assert.ok(md.includes('## 2.1 各源读数（多源通道）'), '缺 2.1 节');
    assert.ok(md.includes('## 2. 各检索式明细'), '2 节被改名');
    assert.ok(md.includes('## 3. PRISMA 流程计数'), '章节号被重排（外部引用会集体失效）');
    assert.ok(md.includes('不适用'), 'Crossref 的 not_applicable 未渲染');
    assert.ok(md.includes('cat feline hairball'), '未记录实际发出的转译检索式');
    assert.ok(md.includes('（多源 HTTP 并行，未使用浏览器）'), '概要未标明通道');
    assert.ok(!md.includes('站点报告命中'), '多源下仍写「站点报告命中」（本次没有站点）');
  });

  t('多源：方法学限制新增「命中数不可相加」与「none 源不计数」两条', () => {
    const log = mkLog();
    assert.strictEqual(log.limitations.length, 7);
    assert.ok(log.limitations.some(x => /不可相加比较/.test(x)));
    assert.ok(log.limitations.some(x => /全库软匹配规模/.test(x)));
    assert.ok(!/单一学术镜像站/.test(log.limitations[0]), '多源下仍写「单一镜像站」');
  });

  t('★ not_applicable 不得被算成「计数已知」：否则报告会写出「合计 0 条」的假读数', () => {
    const log = P.buildLog({
      runs: [{ keyword: 'q1', reportedTotal: null, countState: 'not_applicable', retrieved: 3, translatedBySite: false, aborted: null }],
      sources: [{ keyword: 'q1', id: 'crossref', label: 'Crossref', kind: 'http', queryDialect: 'bag', countSemantics: 'none', count: 3, reportedTotal: null, countState: 'not_applicable', ok: true, aborted: null }],
      meta: { site: null, limit: 5, toolVersion: 'x' },
    });
    assert.strictEqual(log.identification.reportedTotalKnown, false, 'not_applicable 被当成了已知计数');
    assert.deepStrictEqual(log.identification.reportedTotalNotApplicableKeywords, ['q1']);
    assert.deepStrictEqual(log.identification.reportedTotalUnknownKeywords, ['q1']);
  });

  t('★ 向后兼容：不给 sources 时输出与 v4.14 一致（无 dataSources / 无 2.1 / 无 sourceRows，限制仍 5 条）', () => {
    const log = P.buildLog({
      runs: [{ keyword: 'q1', reportedTotal: 10, retrieved: 3, translatedBySite: false, aborted: null }],
      meta: { site: 'kuluer', limit: 10, toolVersion: 'x' },
    });
    assert.strictEqual(log.identification.dataSources, undefined);
    assert.strictEqual(log.identification.database, 'kuluer');
    assert.strictEqual(log.identification.baseUrl, 'https://kuluer.com/scholar');
    assert.strictEqual(log.identification.channel, 'site_browser');
    assert.ok(!('sourceRows' in log), '单源 JSON 多出了新键（外部 git diff 比对会误判「结果变了」）');
    assert.strictEqual(log.limitations.length, 5);
    const md = P.renderMarkdown(log, {});
    assert.ok(!md.includes('## 2.1'), '单源不应出现 2.1 节');
    assert.ok(md.includes('站点报告命中') && md.includes('（https://kuluer.com/scholar）'), '单源概要格式被改');
  });
}


// ==================== v4.15（B 批）：全文四级回退链 ====================
// 这一块只测**判据**，不跑网络。每条都对应一个真实踩过的坑（注释里写明）。
console.log('全文四级回退链（T1 XML / T2 正文HTML / T3 Unpaywall / T4 出版商页）:');
{
  t('planTiers：enrich.pmcid + 顶层 doi ⇒ 六步计划，顺序为 XML→HTML(http)→HTML(browser)→PMC PDF→Unpaywall→出版商', () => {
    const p = FTC.planTiers({ titleEn: 'x', enrich: { pmcid: 'PMC4473147' }, doi: '10.1017/jns.2014.27' });
    const seq = p.map(s => s.tier + '/' + s.transport);
    assert.deepStrictEqual(seq, [
      'T1_epmc_xml/http', 'T2_pmc_html/http', 'T2_pmc_html/browser', 'T2b_pmc_pdf/browser',
      'T3_unpaywall/http', 'T4_publisher/browser',
    ]);
    assert.ok(/PMC4473147\/fullTextXML$/.test(p[0].url), p[0].url);
    assert.ok(/email=%EMAIL%$/.test(p[4].url), 'Unpaywall 的邮箱占位必须留到运行时替换：' + p[4].url);
  });

  t('★ planTiers：只有**顶层** doi（多源记录的形态）也必须给出 T3 —— 初版漏了这个兜底', () => {
    // 曾经的 bug：entryOf 里 doi 只写了 pick(e.doi)，漏了 rec.doi。
    // 多源通道的记录 doi 就在顶层，于是计划恒为空 ⇒ 「只有 DOI 进不了全文通道」原样复发。
    for (const rec of [
      { titleEn: 'x', doi: '10.1111/jpn.13177' },
      { titleEn: 'x', doi: 'https://doi.org/10.1111/jpn.13177' },
      { titleEn: 'x', enrich: { doi: '10.1111/jpn.13177' } },
    ]) {
      const p = FTC.planTiers(rec);
      assert.ok(p.some(s => s.tier === 'T3_unpaywall'), '必须包含 T3，实际 ' + JSON.stringify(p.map(s => s.tier)) + ' for ' + JSON.stringify(rec));
    }
  });

  t('planTiers：无任何入口 / 只有 PMID ⇒ 空计划（不得伪造层级）', () => {
    assert.strictEqual(FTC.planTiers({ titleEn: 'x' }).length, 0);
    assert.strictEqual(FTC.planTiers({ titleEn: 'x', pmid: '12345' }).length, 0, 'PMID 不是全文入口');
  });

  t('entryOf：enrich 优先于顶层；doi 前缀被剥掉', () => {
    const e = FTC.entryOf({ enrich: { pmcid: 'PMC1', doi: '10.1/A' }, pmcid: 'PMC2', doi: '10.9/B' });
    assert.strictEqual(e.pmcid, 'PMC1');
    assert.strictEqual(e.doi, '10.1/A');
    assert.strictEqual(FTC.entryOf({ doi: 'https://dx.doi.org/10.2/C' }).doi, '10.2/C');
  });

  t('normPmcid：归一 PMC 前缀与大小写；非法值返回 null', () => {
    assert.strictEqual(FTC.normPmcid('pmc4473147'), 'PMC4473147');
    assert.strictEqual(FTC.normPmcid('4473147'), 'PMC4473147');
    assert.strictEqual(FTC.normPmcid('PMC-4473147'), 'PMC4473147');
    assert.strictEqual(FTC.normPmcid('PMID123'), null);
    assert.strictEqual(FTC.normPmcid(''), null);
  });

  t('★ assessText 必须拒掉 Cloudflare 挑战页（抓到的内容不是这篇的内容）', () => {
    // 实测：挑战页有几千词，只看字数会全判成功 ⇒ 污染证据表。这是本批最关键的闸门。
    const body = 'Just a moment... Enable JavaScript and cookies to continue '
      + 'checking browser please wait '.repeat(120);
    const g = FTC.assessText(body, { titleEn: 'Effects of coat length on hairballs in cats' });
    assert.strictEqual(g.ok, false, '挑战页绝不能被判为全文');
    assert.ok(/challenge_text/.test(g.reason), '原因须标明是挑战页，实际：' + g.reason);
  });

  t('★ assessText 必须拒掉导航/相关文章页（词数够但标题不命中）', () => {
    const nav = Array.from({ length: 90 }, (_, i) => 'Related article ' + i + ' about dietary fibre and animal nutrition').join(' ');
    const g = FTC.assessText(nav, { titleEn: 'Nasopharyngeal Trichobezoar Foreign Body in a Cat' });
    assert.strictEqual(g.ok, false);
    assert.ok(/title_mismatch/.test(g.reason), g.reason);
    assert.ok(g.titleHits < g.titleNeed, '命中数须低于阈值：' + JSON.stringify(g));
  });

  t('assessText：真全文通过，并报出命中数（供人工复核）', () => {
    const real = 'Nasopharyngeal trichobezoar is a rare foreign body in cats. '
      + 'A trichobezoar was removed from the nasopharynx of a cat. '.repeat(16);
    const g = FTC.assessText(real, { titleEn: 'Nasopharyngeal Trichobezoar Foreign Body in a Cat' });
    assert.strictEqual(g.ok, true, JSON.stringify(g));
    assert.ok(g.titleHits >= 2, '应至少命中 2 个标题实词：' + g.titleHits);
    assert.strictEqual(g.titleCheck, 'ok');
  });

  t('★ assessText：标题缺失时不得假装验过归属 —— 短文本拒、长文本放行但显式标 unavailable', () => {
    const short = 'some unrelated text about weather and traffic '.repeat(10);
    const g1 = FTC.assessText(short, {});
    assert.strictEqual(g1.ok, false);
    assert.ok(/no_title_check_below_800/.test(g1.reason), g1.reason);
    const long = 'some unrelated text about weather and traffic '.repeat(200);
    const g2 = FTC.assessText(long, {});
    assert.strictEqual(g2.ok, true);
    assert.strictEqual(g2.titleCheck, 'unavailable', '必须显式登记「未校验归属」，不能写成 ok');
  });

  t('★ detectChallenge 只看 title 与前 4KB —— 正文深处的挑战特征不算拦截页', () => {
    // ★ 这条断言的第一版是假的：我用了 'captcha'，但它**不在** CHALLENGE_PATTERNS 里，
    //   于是无论是否保留 slice 都恒真 —— 变异自证（M9）打出 MISS 才暴露。
    //   现在改用确实在列表里的 'unusual traffic'，并放在第 4096 字符之后。
    assert.strictEqual(FTC.detectChallenge('Just a moment...', '<html></html>'), 'just a moment');
    assert.strictEqual(FTC.detectChallenge('', 'x'.repeat(5000) + ' unusual traffic'), null,
      '第 5000 字符处的挑战特征不应命中（说明 4KB 窗口生效）');
    assert.ok(FTC.detectChallenge('', 'unusual traffic detected'), '前 4KB 内命中应当返回模式');
  });

  t('detectChallengeStrong：弱特征（captcha / unusual traffic）不算正文级拦截', () => {
    assert.strictEqual(FTC.detectChallengeStrong('we used a captcha to filter bots'), null);
    assert.strictEqual(FTC.detectChallengeStrong('unusual traffic patterns were observed'), null);
    assert.ok(FTC.detectChallengeStrong('Enable JavaScript and cookies to continue'));
  });

  t('★ dropBlocks 必须整段剔除 ref-list（否则参考文献把词数灌到几千，「太短」判据失效）', () => {
    const html = '<html><body><main><section class="main-article-body"><h2>Abstract</h2><p>'
      + 'This study measured hairballs in cats with different coat lengths. '.repeat(8)
      + '</p></section><section class="ref-list"><h2>References</h2><p>' + 'Ref author journal year. '.repeat(300) + '</p></section></main></body></html>';
    const conv = FTC.htmlToText(html);
    assert.ok(!/Ref author/.test(conv.text), '参考文献必须被剔除');
    assert.ok(conv.text.length > 200, '正文必须保留');
  });

  t('★ extractMainHtml 用词数选容器，不用 HTML 字节数 —— 骨架容器（标签够长、正文为空）要跳过', () => {
    // B2 的真实退化：section.main-article-body 只有 21 字符正文，但标签长度 >400，
    // 初版按字节判断就直接停在这一层，抽出 4 个词。
    const skeleton = '<section class="main-article-body"><div class="x"><span>' + 'a'.repeat(600) + '</span></div></section>';
    const realBody = '<article><h1>Trichobezoar or Hair Ball in a Cat</h1><p>'
      + 'A trichobezoar was found in the stomach of a cat and removed surgically. '.repeat(14) + '</p></article>';
    const got = FTC.extractMainHtml('<html><body>' + skeleton + realBody + '</body></html>');
    assert.ok(/^article/.test(got.container), '应跳过空骨架，选有正文的 article，实际 ' + got.container);
    assert.ok(FTC.roughWords(got.html) >= 120, '选中的容器正文词数应足够：' + FTC.roughWords(got.html));
  });

  t('extractBalanced：嵌套同名标签不能提前截断', () => {
    const html = '<section id="outer"><section>inner</section>tail</section><section>after</section>';
    const got = FTC.extractBalanced(html, 0, 'section');
    assert.ok(/tail/.test(got.html), '外层块必须包含 tail，说明没在内层 </section> 处截断');
    assert.ok(!/after/.test(got.html), '不得吞掉后面的兄弟节点');
  });

  t('htmlToText：块级标签转成换行（findMethodsSpan 依赖行结构定位章节）', () => {
    const conv = FTC.htmlToText('<html><body><main><p>First line</p><p>Second line</p></main></body></html>');
    assert.ok(/First line\nSecond line/.test(conv.text), JSON.stringify(conv.text));
  });

  t('★ stripBoilerplate：剔除 PMC 样板行，但只做整行精确匹配（不得误伤正文句）', () => {
    // 实测来源：1939 年那篇的旧版 PMC 页面落到 whole_document，226 词里约 80 词是导航。
    const withBoiler = [
      'Skip to main content',
      'Official websites use .gov',
      'A .gov website belongs to an official government organization in the United States.',
      'Trichobezoar causing acute intestinal obstruction in a child',
      'The patient recovered after surgical removal of the hairball.',
    ].join('\n');
    const out = FTC.stripBoilerplate(withBoiler);
    assert.ok(!/Skip to main content/.test(out), 'Skip to main content 必须剔除');
    assert.ok(!/Official websites use \.gov/.test(out), '.gov 标语必须剔除');
    assert.ok(/Trichobezoar causing acute intestinal obstruction/.test(out), '正文标题行必须保留');
    assert.ok(/surgical removal of the hairball/.test(out), '正文句必须保留');
    // 反面用例：正文句**包含**样板短语但整行不等 ⇒ 不得剔除。
    // 若改成包含匹配，这一条会红 —— 这是整行匹配的边界，必须有用例守着。
    const body = 'We searched in PMC and found that official websites use .gov domains in this study.';
    assert.strictEqual(FTC.stripBoilerplate(body), body, '包含匹配会误删正文，必须只做整行匹配');
  });

  t('stripRefs：正文过半后出现的 References 标题处截断', () => {
    const body = 'Body text here. '.repeat(40) + '\nReferences\n1. Someone 2020.';
    const out = FTC.stripRefs(body);
    assert.ok(!/Someone 2020/.test(out), '参考文献条目应被截掉');
    assert.ok(/Body text/.test(out));
    const short = 'References\nshort abstract';
    assert.strictEqual(FTC.stripRefs(short), short, '出现在前 35% 的 References 不动（可能是摘要里提到的）');
  });

  t('★ classifyUnpaywallError：占位邮箱 422 必须与「没有 OA」区分开', () => {
    // 实测：example.com 被官方黑名单，返回 422 "Please use your own email address"。
    // 若不区分，整条 T3 会静默失效且看起来像端点挂了。
    assert.strictEqual(FTC.classifyUnpaywallError(422, '{"message":"Please use your own email address in API calls."}'), 'placeholder_email');
    assert.strictEqual(FTC.classifyUnpaywallError(422, '{"message":"Email address required in API call"}'), 'email_required');
    assert.strictEqual(FTC.classifyUnpaywallError(404, 'x'), 'doi_not_found');
    assert.strictEqual(FTC.classifyUnpaywallError(429, 'x'), 'rate_limited');
    assert.strictEqual(FTC.classifyUnpaywallError(200, 'x'), 'ok');
    assert.strictEqual(FTC.classifyUnpaywallError(500, 'x'), 'http_500');
  });

  t('pickOaTarget：机构库优先于出版商（机构库一般不做反爬）', () => {
    const tgt = FTC.pickOaTarget({
      oa_locations: [
        { host_type: 'publisher', url_for_pdf: 'https://pub/x.pdf', url: 'https://pub/x' },
        { host_type: 'repository', url_for_pdf: 'https://repo/x.pdf', url: 'https://repo/x' },
      ],
    });
    assert.strictEqual(tgt.url, 'https://repo/x.pdf');
    assert.strictEqual(tgt.host, 'repository');
    assert.strictEqual(FTC.pickOaTarget({ oa_locations: [] }), null);
    assert.strictEqual(FTC.pickOaTarget(null), null);
  });

  t('★ pickFailureReason：取最后一个实质尝试，不能被 skipped 的浏览器级盖掉', () => {
    // 实测 15 篇里 6 篇的失败原因被写成 browser_disabled，真实原因是 no_oa / blocked。
    const r = FTC.pickFailureReason([
      { tier: 'T3_unpaywall', result: 'no_oa', reason: 'is_oa=false,status=closed' },
      { tier: 'T4_publisher', result: 'skipped', reason: 'browser_disabled' },
    ]);
    assert.strictEqual(r, 'is_oa=false,status=closed');
    assert.strictEqual(FTC.pickFailureReason([{ result: 'skipped', reason: 'browser_disabled' }]), 'browser_disabled',
      '全是 skipped 时才退化成它');
    assert.strictEqual(FTC.pickFailureReason([]), 'all_tiers_failed');
  });

  t('shouldSkipTier：T3 判定无 OA 后跳过 T4；其它级不受影响', () => {
    assert.strictEqual(FTC.shouldSkipTier({ tier: 'T4_publisher' }, { oaUnavailable: true }), 'oa_not_available');
    assert.strictEqual(FTC.shouldSkipTier({ tier: 'T4_publisher' }, { oaUnavailable: false }), null);
    assert.strictEqual(FTC.shouldSkipTier({ tier: 'T2_pmc_html' }, { oaUnavailable: true }), null);
    assert.strictEqual(FTC.shouldSkipTier({ tier: 'T3_unpaywall' }, { oaUnavailable: true }), null);
  });

  t('textFileNameFor：有 PMCID 用 PMCID（与 v4.14 产物同名），否则 DOI 派生，再无则 idx', () => {
    assert.strictEqual(FTC.textFileNameFor({ idx: 1 }, { pmcid: 'PMC4473147', doi: '10.1/a' }), 'PMC4473147.txt');
    assert.strictEqual(FTC.textFileNameFor({ idx: 2 }, { pmcid: null, doi: '10.1111/jpn.13177' }), 'doi_10.1111_jpn.13177.txt');
    assert.strictEqual(FTC.textFileNameFor({ idx: 3 }, { pmcid: null, doi: null }), 'idx_3.txt');
  });

  t('summarizeAttempts：把尝试链压成可读一行（报告与 summary 共用同一口径）', () => {
    const s = FTC.summarizeAttempts([
      { tier: 'T1_epmc_xml', transport: 'http', result: 'no_fulltext', reason: 'upstream_500' },
      { tier: 'T2_pmc_html', transport: 'http', result: 'ok' },
    ]);
    assert.ok(/T1_epmc_xml@http=no_fulltext\(upstream_500\)/.test(s), s);
    assert.ok(/T2_pmc_html@http=ok/.test(s), s);
  });

  t('★ 源码守卫：主流程必须走 runFulltextChain，不得退回单通道 runFulltextBatch', () => {
    const sp = fs.readFileSync(path.join(__dirname, 'search-papers.cjs'), 'utf8');
    const codeOnly = sp.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
    assert.ok(/runFulltextChain\(/.test(codeOnly), '主流程必须调用四级回退链');
    assert.ok(!/runFulltextBatch\(/.test(codeOnly), '不得再调用单通道 runFulltextBatch（那是 6/15 的来源）');
  });

  t('★ 源码守卫：浏览器兜底必须默认关闭（实测开与不开都是 9/15，A1/A5/A6/A8 卡 Cloudflare）', () => {
    assert.strictEqual(CL.parseArgs(['node', 's', '--keywords', 'q']).fulltextBrowser, false, '默认必须为 false');
    const on = CL.parseArgs(['node', 's', '--keywords', 'q', '--sources', 'all', '--fulltext', '--fulltext-browser']);
    assert.strictEqual(on.fulltextBrowser, true, '显式给 --fulltext-browser 才开启');
  });
}

// ---------- 文档一致性守卫（frontmatter / 版本号） ----------
console.log('文档一致性守卫:');
const SKILL_TXT = fs.readFileSync(path.join(__dirname, '..', 'SKILL.md'), 'utf8');
const fm = (() => {
  const m = /^---\r?\n([\s\S]*?)\r?\n---/.exec(SKILL_TXT);
  const o = {};
  if (m) for (const line of m[1].split(/\r?\n/)) {
    const i = line.indexOf(':');
    if (i > 0) o[line.slice(0, i).trim()] = line.slice(i + 1).trim();
  }
  return o;
})();
t('SKILL.md frontmatter 四个上架字段均非空', () => {
  ['name', 'display_name', 'display_name_en', 'description_zh', 'description_en']
    .forEach(k => assert.ok(fm[k] && fm[k].length > 0, '字段缺失或为空: ' + k));
});
t('description_en 不得含中文', () => {
  assert.strictEqual(/[\u4e00-\u9fff]/.test(fm.description_en), false, '含中文: ' + String(fm.description_en).slice(0, 80));
});
t('description_zh 必须含中文', () => {
  assert.ok(/[\u4e00-\u9fff]/.test(fm.description_zh), 'description_zh 未含中文');
});
// v4.4：改为**以 TOOL_VERSION 为准的派生校验** —— 旧写法把「当前版本号」硬编码进断言，
// 升版时必须手改断言，否则守卫自己误报 FAIL（把「一致性校验」退化成「版本号复读」）。
// ---------- v4.10 全文通道（fulltext.cjs 纯函数部分） ----------
const FTX = require('./lib/fulltext.cjs');
const SAMPLE_XML = [
  '<article><front><article-meta><abstract><p>Prior work used a crossover design (p = 0.3).</p></abstract></article-meta></front>',
  '<body>',
  '<sec><title>1. Introduction</title><p>Background text only.</p></sec>',
  '<sec><title>2. Materials and Methods</title>',
  '<p>Animals were randomly divided into three groups. The crossover design used three periods; the first week was a washout period.</p>',
  '<p>Statistical analyses used a linear mixed model.</p>',
  '</sec>',
  '<sec><title>3. Results</title><p>Urine output rose (p = 0.037).</p></sec>',
  '</body></article>',
].join('');

console.log('fulltext（全文通道）:');

t('xmlToText：去标签且保留段落边界（方法与结果各自成行）', () => {
  const txt = FTX.xmlToText(SAMPLE_XML);
  assert.ok(!/<[a-z/]/i.test(txt), '仍残留标签：' + txt.slice(0, 60));
  assert.ok(txt.includes('2. Materials and Methods'), '方法学节标题丢失');
  assert.ok(txt.includes('3. Results'), '结果节标题丢失');
  assert.ok(/\n\s*2\. Materials and Methods/.test(txt), '标题未独立成行 ⇒ 无法据「短行」判节边界');
});

t('xmlToText：实体解码且 &amp;lt; 不被二次解码', () => {
  assert.strictEqual(FTX.xmlToText('<p>a &amp;lt; b</p>'), 'a &lt; b');
  assert.strictEqual(FTX.xmlToText('<p>x &lt; y &amp; z</p>'), 'x < y & z');
  assert.strictEqual(FTX.xmlToText('<p>&#65;&#x42;</p>'), 'AB');
});

t('xmlToText 确定性：同一输入两次结果逐字节一致（offset 才可复用）', () => {
  assert.strictEqual(FTX.xmlToText(SAMPLE_XML), FTX.xmlToText(SAMPLE_XML));
});

t('findMethodsSpan：定位方法学节，且不越过 Results', () => {
  const txt = FTX.xmlToText(SAMPLE_XML);
  const span = FTX.findMethodsSpan(txt);
  assert.ok(span, '未定位到方法学节');
  assert.ok(/Materials and Methods/.test(span.title), '标题不符：' + span.title);
  const sub = txt.slice(span.start, span.end);
  assert.ok(sub.includes('washout'), '方法学节未包含其正文');
  assert.ok(!sub.includes('Urine output rose'), '方法学节越界吞掉了 Results');
});

t('findMethodsSpan：无方法学节时返回 null（不猜）', () => {
  assert.strictEqual(FTX.findMethodsSpan('only a discussion here'), null);
});

t('★ extractSignals：方法学节内优先于摘要（摘要先出现也不取它）', () => {
  const txt = FTX.xmlToText(SAMPLE_XML);
  const span = FTX.findMethodsSpan(txt);
  const sigs = FTX.extractSignals(txt, span);
  const co = sigs.find(s => s.key === 'crossover');
  assert.ok(co, '未命中 crossover');
  assert.strictEqual(co.scope, 'methods', 'crossover 取到了摘要那处（off=' + co.offset + '）而非方法学节内');
  assert.ok(co.offset >= span.start && co.offset < span.end, 'offset 不在方法学节区间内');
});

t('★ extractSignals：方法学节内没有时如实标 body（不冒充方法学）', () => {
  // 只有一个 Methods 空节，关键词只出现在 Results 里
  const xml = '<article><body><sec><title>Methods</title><p>Nothing here.</p></sec>'
    + '<sec><title>Results</title><p>We found a crossover effect.</p></sec></body></article>';
  const txt = FTX.xmlToText(xml);
  const sigs = FTX.extractSignals(txt, FTX.findMethodsSpan(txt));
  const co = sigs.find(s => s.key === 'crossover');
  assert.ok(co, '未命中');
  assert.strictEqual(co.scope, 'body');
});

t('★ 偏移量可回查：每个信号都满足 text.slice(offset, offset+length) === matched', () => {
  const txt = FTX.xmlToText(SAMPLE_XML);
  const sigs = FTX.extractSignals(txt, FTX.findMethodsSpan(txt));
  assert.ok(sigs.length >= 3, '信号太少，判据覆盖不足：' + sigs.length);
  for (const s of sigs) {
    assert.strictEqual(txt.slice(s.offset, s.offset + s.length), s.matched,
      '偏移不可回查：' + s.key + ' @' + s.offset);
  }
});

t('★ statistics 不得命中 p 值（p 属结果，不是统计方法）', () => {
  const txt = FTX.xmlToText(SAMPLE_XML);
  const sigs = FTX.extractSignals(txt, FTX.findMethodsSpan(txt));
  const st = sigs.find(s => s.key === 'statistics');
  assert.ok(st, '未命中统计方法');
  assert.ok(!/^p\s*[<=]/i.test(st.matched), '命中了 p 值：' + st.matched);
  assert.ok(/statistic/i.test(st.matched), '应为 Statistical analyses，实际 ' + st.matched);
});

t('★ CLI：--fulltext 缺少 --enrich 时必须报错（不得静默空操作）', () => {
  const msg = (() => { try { CL.parseArgs(['node', 's', '--fulltext', '--keywords', 'a']); return null; } catch (e) { return e.message; } })();
  assert.ok(msg, '必须报错，不得静默空操作');
  assert.ok(/--enrich/.test(msg) && /--sources/.test(msg), '报错须同时给出 --enrich 与 --sources 两种改法，实际：' + msg);
});

t('CLI：--fulltext 与 --enrich 同给可解析；并发度越界报错', () => {
  const a = CL.parseArgs(['node', 's', '--enrich', '--fulltext', '--keywords', 'a']);
  assert.strictEqual(a.fulltext, true);
  assert.strictEqual(a.fulltextConcurrency, 2);
  assert.throws(() => CL.parseArgs(['node', 's', '--enrich', '--fulltext', '--fulltext-concurrency', '9', '--keywords', 'a']), /fulltext-concurrency/);
});

t('三处版本号一致（以 TOOL_VERSION 为准派生校验）', () => {
  const spTxt = fs.readFileSync(path.join(__dirname, 'search-papers.cjs'), 'utf8');
  const m = /TOOL_VERSION\s*=\s*'paper-bilingual-search\/v(\d+\.\d+)'/.exec(spTxt);
  assert.ok(m, '未能在 search-papers.cjs 中解析出 TOOL_VERSION');
  const ver = m[1];                       // 形如 4.4（不含前导 v）
  const esc = ver.replace(/\./g, '\\.');
  assert.ok(new RegExp('主脚本（v' + esc + '）').test(spTxt.split('\n').slice(0, 12).join('\n')),
    '头注释未同步为 v' + ver);
  assert.ok(SKILL_TXT.includes('v' + ver), 'SKILL.md 未提及当前版本 v' + ver);
});
// ---------- v4.3 · B2 Europe PMC 有界并发（异步 · mock fetch，离线可测） ----------
// 为什么必须异步：enrichAll 是真 async；且必须验证「在飞峰值」这一并发语义，
// 只能靠 mock fetch 计数，不能靠「跑得快」来推断。
(async () => {
  async function ta(name, fn) {
    try { await fn(); pass++; console.log('  ✓ ' + name); }
    catch (e) { fail++; console.log('  ✗ ' + name + ' → ' + String(e.message).slice(0, 160)); }
  }
  const withFetch = async (impl, fn) => {
    const orig = global.fetch;
    global.fetch = impl;
    try { return await fn(); } finally { global.fetch = orig; }
  };
  const titleFromUrl = url => { const m = decodeURIComponent(String(url)).match(/TITLE:"(.*?)"/); return m ? m[1] : ''; };
  const mkRecs = n => Array.from({ length: n }, (_, i) => ({ idx: i + 1, titleEn: 'Study number ' + i + ' on dogs', year: 2020 }));
  const okResp = (url, delay) => new Promise(res => setTimeout(() => res({
    status: 200,
    ok: true,
    json: async () => ({ resultList: { result: [{ title: titleFromUrl(url), pubYear: '2020', abstractText: 'Adequate abstract text for grading.' }] } }),
  }), delay));
  const spyFetch = (delay, hooks) => async url => {
    if (hooks && hooks.on) hooks.on();
    try { return await okResp(url, delay); } finally { if (hooks && hooks.off) hooks.off(); }
  };

  console.log('enrichAll 有界并发（v4.3）:');
  await ta('并发结果按输入顺序一一对应，不漏条不乱序', async () => {
    const recs = mkRecs(8);
    const r = await withFetch(spyFetch(0), () => ENR.enrichAll(recs, { concurrency: 4, intervalMs: 0 }));
    assert.strictEqual(r.results.length, 8);
    assert.ok(r.results.every(x => x && x.status === 'matched_with_abstract'), '每条都应补全成功');
    assert.strictEqual(r.stat.matched_with_abstract, 8);
    assert.strictEqual(recs[7].enrich.status, 'matched_with_abstract', 'onItem 应逐条回填到原记录');
  });
  await ta('在飞请求峰值不得超过 concurrency 上限（且确实发生并发）', async () => {
    let inflight = 0, peak = 0;
    await withFetch(spyFetch(12, { on: () => { inflight++; peak = Math.max(peak, inflight); }, off: () => { inflight--; } }),
      () => ENR.enrichAll(mkRecs(12), { concurrency: 3, intervalMs: 0 }));
    assert.ok(peak <= 3, '峰值在飞 ' + peak + ' 超过上限 3');
    assert.ok(peak >= 2, '未真正并发（peak=' + peak + '）');
  });
  await ta('concurrency=1 严格串行（峰值在飞 = 1，即 v4.2 回退路径）', async () => {
    let inflight = 0, peak = 0;
    await withFetch(spyFetch(5, { on: () => { inflight++; peak = Math.max(peak, inflight); }, off: () => { inflight--; } }),
      () => ENR.enrichAll(mkRecs(6), { concurrency: 1, intervalMs: 0 }));
    assert.strictEqual(peak, 1);
  });
  await ta('★ 连续 429 → 自动降级串行，并在返回值中显式标记（安全阀）', async () => {
    const recs = mkRecs(4);
    const r = await withFetch(async () => ({ status: 429, ok: false, json: async () => ({}) }),
      () => ENR.enrichAll(recs, { concurrency: 4, intervalMs: 0, retries: 0, degradeAfter429: 2 }));
    assert.strictEqual(r.degraded, true, '应标记已降级');
    assert.strictEqual(r.concurrency, 1, '降级后有效并发应为 1');
    assert.strictEqual(r.results.length, 4, '降级后剩余条目仍须全部处理（不丢条）');
    assert.ok(r.results.every(x => x && String(x.status).startsWith('error:')), '全部应为错误状态而非静默丢弃');
  });
  await ta('enrichOne 把 429 单列为 error:429（旧实现误报 no_response ⇒ 安全阀无法识别限流）', async () => {
    const e = await withFetch(async () => ({ status: 429, ok: false, json: async () => ({}) }),
      () => ENR.enrichOne({ idx: 1, titleEn: 'X', year: 2020 }, { retries: 0 }));
    assert.strictEqual(e.status, 'error:429');
  });
  await ta('空输入不发起任何请求且不崩', async () => {
    const r = await withFetch(async () => { throw new Error('不应发起请求'); }, () => ENR.enrichAll([], { concurrency: 4 }));
    assert.deepStrictEqual(r.stat, {});
    assert.strictEqual(r.results.length, 0);
  });

  // ---------- 残差诊断的跨运行标注（2026-10-19） ----------
  // 动因：抑制原先只作用于「建议检索式」（不出式 + 记入 suppressed），但**残差维度诊断表照旧把该维度
  //   当成本轮新发现列出来** ⇒ 同一维度在人读视图里仍被重复呈现一次。本段锁死三件事：
  //   ① 有跨运行记忆时才加列（无则旧报告形状完全不变）② 抑制标记必须逐簇、且点名到具体维度
  //   ③ 标注**不得**改变「只提示不自动建」的语义（提案词不按抑制剔除，删不删由人判断）
  console.log('残差诊断的跨运行标注:');

  const dgFixture = (clusters, extra) => Object.assign({
    residual: { total: 9, byLevel: { near: 5, off: 4 } },
    fingerprints: 3, minSupport: 2, dropped: { excludedRecords: 0 },
    verdict: 'new-dimension', verdictNote: '簇内 ≥2 条且共享 ≥2 个指纹',
    autoApply: false, clusters,
    proposal: { keywords: [], note: '' }, unclustered: [],
  }, extra || {});
  const clFixture = (label, extra) => Object.assign({
    kind: 'new-dimension', label, support: 4, confidence: 'strong',
    terms: [{ term: label.toLowerCase() }], idxs: [1, 2, 3, 4],
    titles: [{ title: label + ' 的代表文献题名' }],
  }, extra || {});

  t('★ 无跨运行记忆 ⇒ 诊断表不加「跨运行」列（旧报告形状零变化）', () => {
    const md = RK.renderDiagnosis(dgFixture([clFixture('Kidney')]));
    assert.ok(md.includes('| 维度类型 | 簇标签 | 支持 | 置信 | 簇内术语 | 代表题名 |'), '表头形状变了');
    assert.ok(!md.includes('跨运行'), '未传跨运行记忆却出现了「跨运行」字样');
    assert.ok(!md.includes('抑制'), '未传跨运行记忆却出现「抑制」');
  });

  t('★ 抑制必须落到诊断表：该维度标「已报过 N 次 · 抑制」，且汇总行点名', () => {
    const md = RK.renderDiagnosis(dgFixture([
      clFixture('Kidney', { trend: 'persistent', reportCount: 2, suppress: true }),
      clFixture('Fiber', { trend: 'new', reportCount: 0, suppress: false }),
    ], { crossActive: true }));
    assert.ok(/^\| 维度类型 \| 簇标签 \| 支持 \| 置信 \| 跨运行 \|/m.test(md), '未加「跨运行」列');
    assert.ok(md.includes('已报过 2 次 · 抑制'), '抑制簇未标注');
    assert.ok(md.includes('已抑制 **1** 个维度（`Kidney`）'), '汇总行未点名被抑制维度');
    // 同一张表里必须能读出差异：另一簇是「首次」，不得被整表统一标成抑制/正常
    assert.ok(/\| 首次 \|/.test(md), '首次出现的维度未被标为「首次」');
  });

  t('跨运行在场但无抑制 ⇒ 汇总行须明说「无维度被抑制」（不是留空）', () => {
    const md = RK.renderDiagnosis(dgFixture([
      clFixture('Kidney', { trend: 'new', reportCount: 0, suppress: false }),
    ], { crossActive: true }));
    assert.ok(md.includes('本次无维度被抑制'), '无抑制时未明说，读者会以为漏了标注');
    assert.ok(!md.includes('已抑制 **'), '无抑制却写了抑制计数');
  });

  t('★ 标注不改变语义：autoApply 仍 false，且明示「提案词未按抑制剔除」', () => {
    const dg = dgFixture([
      clFixture('Kidney', { trend: 'persistent', reportCount: 3, suppress: true }),
    ], { proposal: { keywords: ['kidney'], note: '' }, crossActive: true });
    const md = RK.renderDiagnosis(dg);
    assert.strictEqual(dg.autoApply, false, '标注过程改了 autoApply');
    assert.ok(md.includes('提案') && md.includes('未按抑制剔除'), '未声明提案词未剔除（会被读成「已去重」）');
    assert.ok(md.includes('仍是本轮残差'), '未说明被抑制的维度仍是本轮残差');
  });

  t('★ JSON 通道：compactIterate 保留 trend / reportCount / suppress 与 crossActive', () => {
    const it = {
      pick: 'all', batch: 3, maxRounds: 2, stopReason: 'no-gain', stopDetail: null,
      rounds: [], totalGain: 0, totalAppended: 0, terms: ['a'],
      diagnosis: dgFixture([
        clFixture('Kidney', { trend: 'persistent', reportCount: 2, suppress: true }),
        clFixture('Fiber', { trend: 'new', reportCount: 0, suppress: false }),
      ], { crossActive: true }),
      convergence: null, crossRun: null,
    };
    const j = RK.compactIterate(it);
    assert.strictEqual(j.diagnosis.crossActive, true, 'crossActive 未登记（下游无法区分「没有抑制」与「没开跨运行」）');
    const k = j.diagnosis.clusters.find(c => c.label === 'Kidney');
    assert.strictEqual(k.suppress, true);
    assert.strictEqual(k.reportCount, 2);
    assert.strictEqual(k.trend, 'persistent');
    const f = j.diagnosis.clusters.find(c => c.label === 'Fiber');
    assert.strictEqual(f.suppress, false, '未抑制的簇被标成抑制');
    // 未传跨运行 ⇒ 三字段取中性值，不得凭空造出「首次」
    const j2 = RK.compactIterate(Object.assign({}, it, {
      diagnosis: dgFixture([clFixture('Kidney')]),
    }));
    assert.strictEqual(j2.diagnosis.crossActive, false);
    assert.strictEqual(j2.diagnosis.clusters[0].trend, null);
    assert.strictEqual(j2.diagnosis.clusters[0].reportCount, 0);
    assert.strictEqual(j2.diagnosis.clusters[0].suppress, false);
  });

  t('★ 实路径：crossActive 由 iterate 写在 diagnosis 上（文件 JSON 走原始对象，不走 compactIterate）', () => {
    needIT();
    const groups = mkG(['A 肠道菌群紊乱', 'B 肠道菌群紊乱', 'C 膀胱炎结石', 'D 膀胱炎结石']);
    const noPrior = IT.iterateRounds({
      groups, topicSpec: { terms: '肠道菌群' }, maxRounds: 2, batch: 3, minDf: 2,
    });
    assert.strictEqual(noPrior.diagnosis.crossActive, false, '未传 priorFile 却标了跨运行');
    assert.strictEqual(noPrior.diagnosis.clusters.length > 0, true, '夹具须真聚出维度（否则列断言是空真值）');
    const withPrior = IT.iterateRounds({
      groups, topicSpec: { terms: '肠道菌群' }, maxRounds: 2, batch: 3, minDf: 2,
      priorFile: { exists: false, data: null, error: null },
      now: new Date('2026-10-19T00:00:00Z'),
    });
    assert.strictEqual(withPrior.diagnosis.crossActive, true,
      '传了 priorFile 却未登记 crossActive ⇒ 文件 JSON 缺字段（两条 JSON 通道不一致）');
    // 三通道一致：原始对象（文件 JSON）/ 精简对象（stdout JSON）/ md 表头
    assert.strictEqual(withPrior.diagnosis.crossActive, true);
    assert.strictEqual(RK.compactIterate(withPrior).diagnosis.crossActive, true);
    assert.ok(RK.renderIterateReport(withPrior, {}).includes('| 跨运行 |'),
      'md 诊断表未因 crossActive 加列（三通道不一致）');
  });

  // ---------- 计数探针三态：采集失败 vs 真 0（2026-10-19） ----------
  // 动因（2026-10-16 一手实测）：10 条检索式探针里 4 条 reportedTotal 为 null、单条 30–66s，
  //   而 summary.warnings 为空、exit 0 ⇒「采集失败」与「真的 0 命中」在产物里无法区分；
  //   而探针的用途正是「先比命中量、再决定跑哪条」⇒ 可能**误排除一条本来有效的检索式**。
  // 关键事实：站点真 0 条时给的是「约 0 条结果」（正则能取到整数 0）⇒ null 从来不等于 0，只等于「没读到」。
  // 故修法不是「null 就报警」，而是先把 null 拆成两义；三态穷举互斥，且必须**反向安全**：
  //   疑似歧义时宁可报「采集失败」（促使人重跑），绝不可把失败说成 0（会让人删掉一条好式子）。
  console.log('计数探针三态（采集失败 vs 真 0）:');

  const probeRows10 = () => Array.from({ length: 10 }, (_, i) => ({
    keyword: 'k' + (i + 1),
    reportedTotal: i < 6 ? (i + 1) * 100 : null,   // 前 6 条读得计数，后 4 条为本轮实测的「静默失败」形态
    retrieved: 0,
    durationMs: i < 6 ? 8000 : 30000 + i * 1000,
  }));

  t('★ null 且无「无结果」提示 ⇒ collect_failed（不是 0 命中）', () => {
    const c = PR.classifyCount({ reportedTotal: null, noResultsSignal: false });
    assert.strictEqual(c.state, PR.COUNT_STATE.COLLECT_FAILED);
    assert.strictEqual(c.count, null, '采集失败不得被折算成数字 0');
  });

  t('整数 0 ⇒ counted（站点明确说 0 条，属有效证据）', () => {
    const c = PR.classifyCount({ reportedTotal: 0 });
    assert.strictEqual(c.state, PR.COUNT_STATE.COUNTED);
    assert.strictEqual(c.count, 0);
  });

  t('null 但有「无结果」信号 ⇒ zero_confirmed（真 0，可用于排除检索式）', () => {
    const c = PR.classifyCount({ reportedTotal: null, noResultsSignal: true });
    assert.strictEqual(c.state, PR.COUNT_STATE.ZERO_CONFIRMED);
    assert.strictEqual(c.count, 0);
  });

  t('缺字段 / 传入 null 不抛，一律按 collect_failed（宁可误报，不可误排除）', () => {
    assert.strictEqual(PR.classifyCount({}).state, PR.COUNT_STATE.COLLECT_FAILED);
    assert.strictEqual(PR.classifyCount(null).state, PR.COUNT_STATE.COLLECT_FAILED);
    assert.strictEqual(PR.classifyCount(undefined).state, PR.COUNT_STATE.COLLECT_FAILED);
  });

  t('★ 部分失败必须点名（旧实现 4/10 失败完全静默）', () => {
    const v = PR.probeVerdict(probeRows10(), { limit: 0 });
    assert.strictEqual(v.probe, true);
    assert.strictEqual(v.counted.length, 6);
    assert.deepStrictEqual(v.failed, ['k7', 'k8', 'k9', 'k10'], '失败条目未被逐一点名');
    assert.strictEqual(v.anyEvidence, true);
    assert.strictEqual(v.siteDegraded, false, '部分失败被误判成「站点整体不可用」');
  });

  t('全部失败 ⇒ allFailed 且 siteDegraded（沿用既有 exit 5 语义）', () => {
    const v = PR.probeVerdict([
      { keyword: 'a', reportedTotal: null, retrieved: 0 },
      { keyword: 'b', reportedTotal: null, retrieved: 0 },
    ], { limit: 0 });
    assert.strictEqual(v.allFailed, true);
    assert.strictEqual(v.anyEvidence, false);
    assert.strictEqual(v.siteDegraded, true);
  });

  t('★ 全部「站点确认 0 条」不得判成站点不可用（exit 5 假阳性回归）', () => {
    const v = PR.probeVerdict([
      { keyword: 'a', reportedTotal: null, noResultsSignal: true, retrieved: 0 },
      { keyword: 'b', reportedTotal: null, noResultsSignal: true, retrieved: 0 },
    ], { limit: 0 });
    assert.strictEqual(v.zeroConfirmed.length, 2);
    assert.strictEqual(v.failed.length, 0);
    assert.strictEqual(v.anyEvidence, true, '站点明确说 0 条也算「给了证据」');
    assert.strictEqual(v.siteDegraded, false, '真 0 被误报为站点不可用（旧判据 reportedTotal!=null 的假阳性）');
  });

  t('非探针模式（limit>0）不产生探针告警；站点评级仍按「全 0 且无证据」判', () => {
    const rows = probeRows10().map(r => Object.assign({}, r, { retrieved: 5 }));
    const v = PR.probeVerdict(rows, { limit: 10 });
    assert.strictEqual(v.probe, false);
    assert.deepStrictEqual(PR.probeWarnings(v, { readyTimeoutSec: 45 }), [], '非探针模式不应刷探针告警');
    assert.strictEqual(v.siteDegraded, false, '有记录却判成站点不可用');
  });

  t('★ 告警文案必须可执行：点名关键词 + 「不是 0 命中」+ 不得据此排除 + 当前超时与耗时', () => {
    const v = PR.probeVerdict(probeRows10(), { limit: 0 });
    const ws = PR.probeWarnings(v, { readyTimeoutSec: 45 });
    assert.strictEqual(ws.length, 4, '每个失败条目都应有独立告警');
    assert.ok(ws[0].includes('k7'), '未点名关键词');
    assert.ok(ws[0].includes('判为采集失败（不是 0 命中）'), '未写明「不是 0 命中」');
    assert.ok(ws[0].includes('不得据此排除该检索式'), '未写明「不得据此排除」');
    assert.ok(ws[0].includes('--ready-timeout（当前 45s）'), '未给出可执行的超时建议');
    assert.ok(ws[0].includes('耗时 36s'), '未带上实测耗时（k7 的 durationMs=36000 ⇒ 36s）');
  });

  t('probeSummaryLine：非探针返回 null，探针给出一行三类计数', () => {
    const v = PR.probeVerdict(probeRows10(), { limit: 0 });
    const line = PR.probeSummaryLine(v);
    assert.ok(line.includes('读得计数 6'), line);
    assert.ok(line.includes('采集失败 4'), line);
    assert.ok(line.includes('k10'), '汇总行未点名失败条目');
    assert.strictEqual(PR.probeSummaryLine({ probe: false, total: 0, counted: [], zeroConfirmed: [], failed: [] }), null);
  });

  t('空输入不崩（无关键词时不得抛，也不得判站点不可用）', () => {
    const v = PR.probeVerdict([], { limit: 0 });
    assert.strictEqual(v.total, 0);
    assert.strictEqual(v.allFailed, false);
    assert.strictEqual(v.siteDegraded, false);
    assert.deepStrictEqual(PR.probeWarnings(v, {}), []);
  });

  t('buildLog：采集失败进 unknownKeywords，真 0 视为「已知」（不被真 0 拉红）', () => {
    const runs = [
      { keyword: 'a', reportedTotal: 100, retrieved: 0 },
      { keyword: 'b', reportedTotal: null, retrieved: 0, noResultsSignal: true },
      { keyword: 'c', reportedTotal: null, retrieved: 0 },
    ];
    const l = P.buildLog({ runs, dedupe: null, evidence: null, meta: {} });
    assert.strictEqual(l.identification.reportedTotalBySite, 100, '真 0 与失败都不应虚增合计');
    assert.deepStrictEqual(l.identification.reportedTotalUnknownKeywords, ['c']);
    assert.strictEqual(l.identification.reportedTotalKnown, false, '有采集失败时必须标为不完全');
    const l2 = P.buildLog({ runs: runs.slice(0, 2), dedupe: null, evidence: null, meta: {} });
    assert.strictEqual(l2.identification.reportedTotalKnown, true, '站点明确说 0 条被误判为「计数未读到」');
  });

  t('★ PRISMA 渲染：「未读到」与「0」不可互换（旧版两者都渲染为「—」）', () => {
    const runs = [
      { keyword: 'b', reportedTotal: null, retrieved: 0, noResultsSignal: true },
      { keyword: 'c', reportedTotal: null, retrieved: 0 },
    ];
    const md = P.renderMarkdown(P.buildLog({ runs, dedupe: null, evidence: null, meta: {} }));
    const row = kw => md.split('\n').find(x => x.includes('`' + kw + '`')) || '';
    assert.ok(row('b').startsWith('| 1 | `b` | — | 0 |'), '真 0 未渲染为 0 ⇒ ' + row('b'));
    assert.ok(row('c').startsWith('| 2 | `c` | — | 未读到 |'), '采集失败未渲染为「未读到」⇒ ' + row('c'));
    assert.ok(md.includes('不等于 0 命中'), '缺少「未读到 ≠ 0 命中」的图例');
  });

  t('★ 接线：attachProbe 把告警落进 summary.warnings 并登记 probe 字段（真实对象，不靠正则猜）', () => {
    const summary = { warnings: [], errors: [] };
    const groups = probeRows10().map(r => ({ keyword: r.keyword, records: [], aborted: null, diagnostics: r }));
    const v = PR.attachProbe(summary, groups, { limit: 0, readyTimeoutSec: 45 });
    assert.strictEqual(v.failed.length, 4);
    assert.strictEqual(summary.warnings.length, 4, '失败条目未落到 summary.warnings');
    assert.ok(summary.warnings[0].includes('k7'), '落地的告警未点名关键词');
    assert.deepStrictEqual(summary.probe.failed, ['k7', 'k8', 'k9', 'k10']);
    assert.strictEqual(summary.probe.total, 10);
    assert.strictEqual(summary.probe.siteDegraded, false);
    assert.deepStrictEqual(summary.errors, [], '部分失败不应写进 errors（它不是错误，是需要重跑的未知量）');
    // 非探针：不刷告警，但 probe 字段仍登记（保留可追溯性，便于事后判读）
    const s2 = { warnings: [], errors: [] };
    PR.attachProbe(s2, groups.map(g => Object.assign({}, g, { records: [{}] })), { limit: 10 });
    assert.deepStrictEqual(s2.warnings, []);
    assert.strictEqual(s2.probe.countOnlyProbe, false);
    assert.strictEqual(s2.probe.failed.length, 4, '非探针也要记录未读到计数的条目');
    // 反例：全部未读到计数、但确实抓到了记录 ⇒ 不是站点不可用（retrieved 必须取 records.length，不能取汇总量）
    const s3 = { warnings: [], errors: [] };
    PR.attachProbe(s3, [{ keyword: 'x', records: [{}], aborted: null, diagnostics: { reportedTotal: null } }], { limit: 10 });
    assert.strictEqual(s3.probe.siteDegraded, false, '有记录却判成站点不可用（retrieved 取值源错了）');
    assert.strictEqual(s3.probe.failed.length, 1, '这条例外也必须如实登记「未读到计数」');
  });

  t('★ 源码守卫：主脚本必须走 attachProbe，且不得残留 anyCount 旧判据 / 不得静默', () => {
    const sp = fs.readFileSync(path.join(__dirname, 'search-papers.cjs'), 'utf8');
    const pc = fs.readFileSync(path.join(__dirname, 'lib', 'probe.cjs'), 'utf8');
    // v4.15（A-2）：调用点变成三元式（多源 / 站点两条通道），但**站点通道那支**必须仍是
    // 「attachProbe + readyTimeoutSec」原样；多源那支必须走 multiProbeVerdict（不能用单源三态，
    // 否则 not_applicable 会被判成采集失败）。两条一起钉，防止「改一支顺手把另一支写坏」。
    assert.ok(/attachProbe\(summary, groups, \{ limit: opts\.limit, readyTimeoutSec: opts\.readyTimeoutSec \}\)/.test(sp),
      '未接线 attachProbe（站点通道）');
    assert.ok(/MR\.multiProbeVerdict\(groups, \{ limit: opts\.limit \}\)/.test(sp),
      '多源通道未走 multiProbeVerdict（照搬单源三态会把 not_applicable 判成假故障）');
    assert.ok(/summary\.probe = \{/.test(pc), 'attachProbe 未登记探针结论');
    assert.ok(/probeWarnings\(v, \{ readyTimeoutSec: o\.readyTimeoutSec \}\)\.forEach\(w => summary\.warnings\.push\(w\)\)/.test(pc),
      '未把探针告警写入 summary.warnings');
    assert.ok(/log\('probe_collect_failed'/.test(sp), '采集失败未打事件日志');
    assert.ok(!/const anyCount = /.test(sp), '仍残留 anyCount 旧判据（真 0 会被误报为站点不可用）');
    // ★ 语义位置而非孤立字符串：两处都要记信号 —— 抓取循环（非探针 0 结果页）与探针读数（探针模式不进循环）。
    //   只查一处会让「删掉另一处」的变异保持全绿（本轮变异实测踩到，故按位置分别钉死）。
    assert.ok(/if \(NO_RESULT_RE\.test\(bodyText\)\) \{[\s\S]{0,160}?diagnostics\.noResultsSignal = true;/.test(sp),
      '抓取循环未记「无结果」信号 ⇒ 非探针的真 0 会退化成采集失败');
    assert.ok(/new RegExp\(noResultSrc\)\.test\(t\)/.test(sp), '探针读数未同时采集「无结果」信号 ⇒ 探针模式的真 0 不可辨');
    assert.ok(/readReportedTotal = \(\) => page\.evaluate\(noResultSrc =>/.test(sp), '读数未把无结果判据传进页面上下文');
    // probe.cjs 必须是纯函数模块：一旦 require 网络/文件系统，判据就不可离线复现
    assert.ok(!/require\(['"](fs|path|http|https|net|child_process)['"]\)/.test(pc), 'probe.cjs 引入了 IO/网络依赖');
  });

  // ─────────────── v4.9：PRISMA 流程图（prisma-diagram.cjs）───────────────
  // 判据分两类：① 图上的数字必须**等于** prisma.json（不是重算的近似值）；
  //             ② 三条诚实约束（未读到≠0 / 未去重≠0 / 排除恒 0）必须在图上可见。
  const PD = require('./lib/prisma-diagram.cjs');
  const mkLog = (over) => P.buildLog(Object.assign({
    runs: [
      { keyword: '膳食纤维', sourceRef: 'k1', reportedTotal: 100, retrieved: 40, pages: 1, strategy: 's', translatedBySite: true, translateStatus: 'ok', durationMs: 1000 },
      { keyword: 'hairball', sourceRef: 'k2', reportedTotal: 50, retrieved: 27, pages: 1, strategy: 's', translatedBySite: true, translateStatus: 'ok', durationMs: 900 },
    ],
    dedupe: { total: 67, unique: 60, duplicates: 7, removedList: [] },
    evidence: { graded: 60, gradeStat: { A: 2, B: 5, C: 8, D: 25 }, needsManualExcludeCount: 12, lowConfidenceCount: 9, designStat: {}, speciesStat: {}, flagStat: {} },
    meta: { site: 'kuluer', limit: 40, countOnlyProbe: false, toolVersion: 'test' },
  }, over || {}));

  console.log('prisma-diagram（PRISMA 流程图）:');
  t('SVG 基本形状：xml 声明 + 根元素 + 四段标题', () => {
    const svg = PD.renderSvg(mkLog());
    assert.ok(svg.startsWith('<?xml'), '缺 XML 声明 ⇒ 非独立文件，部分渲染器会拒绝');
    assert.ok(/<svg[^>]+viewBox="0 0 \d+ \d+"/.test(svg), '缺 viewBox ⇒ 缩放时版式会崩');
    ['识别 · Identification', '筛选 · Screening', '资格 · Eligibility', '纳入 · Included'].forEach((s) => {
      assert.ok(svg.includes(s), '缺段标题：' + s);
    });
    assert.ok(svg.trim().endsWith('</svg>'), 'SVG 未闭合');
  });

  t('★ 图上四个计数逐字段等于 prisma.json（不重算）', () => {
    const log = mkLog();
    const svg = PD.renderSvg(log);
    // 取值必须用 value 槽（text-anchor="end"）比对，避免与标题/注记里的同名数字混淆
    const valOf = (n) => 'text-anchor="end">' + PD.fmtNum(n) + '</text>';
    assert.ok(svg.includes(valOf(log.identification.recordsRetrieved)), '实际导出数未上图');
    assert.ok(svg.includes(valOf(log.screening.recordsAfterDuplicates)), '去重后剩余未上图');
    assert.ok(svg.includes(valOf(log.eligibility.recordsAssessed)), '资格评估数未上图');
    assert.ok(svg.includes(valOf(log.included.recordsIncluded)), '最终纳入数未上图');
    assert.ok(svg.includes(valOf(log.screening.duplicatesRemoved)), '去重移除数未上图');
  });

  t('★ 不变式：纳入 > 资格评估 ⇒ 抛错（篡改必红）', () => {
    const log = mkLog();
    log.included.recordsIncluded = log.eligibility.recordsAssessed + 1;
    assert.throws(() => PD.renderSvg(log), /纳入.*>.*资格评估/);
    assert.strictEqual(PD.validateFunnel(log).ok, false);
  });

  t('★ 不变式：去重后 > 实际导出 ⇒ 抛错', () => {
    const log = mkLog();
    log.screening.recordsAfterDuplicates = log.identification.recordsRetrieved + 5;
    assert.throws(() => PD.renderSvg(log), /去重不可能增加条目/);
  });

  t('★ 不变式：excludedByTool ≠ 0 ⇒ 抛错（本工具不做资格判断）', () => {
    const log = mkLog();
    log.eligibility.excludedByTool = 3;
    assert.throws(() => PD.renderSvg(log), /excludedByTool 应为 0/);
  });

  t('★ 不变式：复核标记 > 纳入 ⇒ 抛错（标记应含在纳入内）', () => {
    const log = mkLog();
    log.included.flaggedForReview = log.included.recordsIncluded + 1;
    assert.throws(() => PD.renderSvg(log), /标记应含在纳入数之内/);
  });

  t('非数字计数（null）⇒ 抛错而不是画成 0', () => {
    const log = mkLog();
    log.identification.recordsRetrieved = null;
    assert.throws(() => PD.renderSvg(log), /null 不得当作 0/);
  });

  t('★ 「未读到」：合计换警示样式 + 明写不等于 0 命中', () => {
    const log = mkLog({
      runs: [
        { keyword: 'a', reportedTotal: 100, retrieved: 10, pages: 1, durationMs: 1, countState: 'counted' },
        { keyword: 'b', reportedTotal: null, retrieved: 5, pages: 1, durationMs: 1, countState: 'collect_failed' },
      ],
      dedupe: null,      // 本用例只测「未读到」，去重口径另有用例 ⇒ 必须置 null 以免与不变式打架
      evidence: null,
    });
    assert.strictEqual(log.identification.reportedTotalKnown, false);
    const svg = PD.renderSvg(log);
    assert.ok(svg.includes('不等于 0 命中'), '未写明「不等于 0 命中」⇒ 读者会当成 0');
    assert.ok(svg.includes('pd-value-warn'), '合计未用警示样式 ⇒ 与正常读数不可辨');
    assert.ok(svg.includes('未读到计数：'), '脚注未列出未读到的检索式');
  });

  t('★ 真 0（zero_confirmed）不得写成「未读到」', () => {
    const log = mkLog({
      runs: [
        { keyword: 'a', reportedTotal: null, noResultsSignal: true, retrieved: 0, pages: 1, durationMs: 1 },
      ],
      dedupe: null,
      evidence: null,
    });
    assert.strictEqual(log.identification.reportedTotalKnown, true, '站点明确说 0 条应算「已知」');
    const svg = PD.renderSvg(log);
    assert.ok(!svg.includes('不等于 0 命中'), '真 0 场景误标了「未读到」');
    assert.ok(!svg.includes('未读到计数：'), '真 0 场景误列了未读到清单');
  });

  t('★ 未去重（duplicatesRemoved=null）显示「未执行」，不是 0', () => {
    const log = mkLog({ dedupe: null });
    assert.strictEqual(log.screening.duplicatesRemoved, null);
    const svg = PD.renderSvg(log);
    assert.ok(svg.includes('未执行'), '未去重未标「未执行」⇒ 会被读成 0 条重复');
    assert.ok(svg.includes('null ≠ 0'), '未解释 null 与 0 的区别');
    assert.ok(!svg.includes('text-anchor="end">0</text>'), '未去重场景出现了 0 值 ⇒ 与「去重 0 条」混淆');
  });

  t('正常去重：7 条显示为 7', () => {
    const svg = PD.renderSvg(mkLog());
    assert.ok(svg.includes('text-anchor="end">7</text>'), '去重移除数未显示');
  });

  t('★ 资格段必须写明「本工具不做资格判断」且排除数为 0', () => {
    const svg = PD.renderSvg(mkLog());
    assert.ok(svg.includes('工具自动排除'), '缺「工具自动排除」旁注');
    assert.ok(svg.includes('本工具不做资格判断'), '缺「不做资格判断」说明 ⇒ 读者以为筛掉了东西');
    assert.ok(/pd-side-value[^>]*>0</.test(svg), '排除数未显示为 0');
  });

  t('★ 纳入段：复核标记写明「含在纳入内，非排除」', () => {
    const svg = PD.renderSvg(mkLog());
    assert.ok(svg.includes('需人工复核'), '缺复核旁注');
    assert.ok(svg.includes('含在纳入内'), '未写明标记属于纳入口径内');
    // 「排除」二字在资格段旁注里合法存在（工具自动排除/不做资格判断），
    // 所以只能在**复核旁注自己的片段内**断言 —— 全局搜会把合法文案判成违规。
    const iFlag = svg.indexOf('需人工复核');
    assert.ok(iFlag > 0, '缺复核旁注');
    const flagSeg = svg.slice(iFlag, iFlag + 420);
    // 旁注文案必须是「含在纳入内，非排除」——「非排除」三个字本身就是判据：
    // 少了它，读者看到「需人工复核 12」会默认理解成「筛掉了 12 条」。
    assert.ok(flagSeg.includes('非排除'), '未写明「非排除」⇒ 会被读成排除项');
    assert.ok(!/排除\s*\d/.test(flagSeg), '复核数被画成了排除条数');
  });

  t('★ 站点自报命中与实际导出不画成漏斗步进', () => {
    const svg = PD.renderSvg(mkLog());
    assert.ok(svg.includes('不可互推'), '缺「不可互推」提示 ⇒ 读者会做减法以为筛掉了 133 条');
    // 两行必须都在 Identification 段内并列：段内行序应为「自报命中」在「实际导出」之前
    const iSelf = svg.indexOf('数据库自报命中');
    const iExport = svg.indexOf('实际导出');
    assert.ok(iSelf > 0 && iExport > iSelf, '两读数顺序异常（应并列：自报命中在前）');
  });

  t('探针模式（--limit 0）在图上标注「0 属预期」', () => {
    const log = mkLog({
      runs: [{ keyword: 'a', reportedTotal: 100, retrieved: 0, pages: 0, durationMs: 1 }],
      dedupe: null,
      evidence: null,
      meta: { site: 'kuluer', limit: 0, countOnlyProbe: true, toolVersion: 'test' },
    });
    const svg = PD.renderSvg(log);
    assert.ok(svg.includes('计数探针'), '探针模式未标注 ⇒ 0 条会被当成检索失败');
  });

  t('XML 转义：关键词含 < & " 不得破坏 SVG', () => {
    const log = mkLog({
      runs: [
        { keyword: 'a<b&c"d\'e', reportedTotal: null, retrieved: 1, pages: 1, durationMs: 1, countState: 'collect_failed' },
      ],
      dedupe: null,
      evidence: null,
    });
    const svg = PD.renderSvg(log);
    assert.ok(svg.includes('&lt;b&amp;c'), '特殊字符未转义 ⇒ SVG 解析会失败');
    assert.ok(!/<b&/.test(svg), '出现未转义的裸 <b&');
    // 转义后仍必须是「一段合法 XML 形状」：标签开合计数一致
    const open = (svg.match(/<(?!\?|\/|!)[a-zA-Z]/g) || []).length;
    const close = (svg.match(/<\/[a-zA-Z]/g) || []).length;
    const selfClose = (svg.match(/\/>/g) || []).length;
    assert.strictEqual(open, close + selfClose, '标签开合不匹配（open=' + open + ' close=' + close + ' self=' + selfClose + '）');
  });

  t('确定性：同一 log 两次渲染逐字节一致', () => {
    const log = mkLog();
    assert.strictEqual(PD.renderSvg(log), PD.renderSvg(log));
  });

  t('fmtNum：千分位且不受 locale 影响', () => {
    assert.strictEqual(PD.fmtNum(1943), '1,943');
    assert.strictEqual(PD.fmtNum(0), '0');
    assert.strictEqual(PD.fmtNum(null), '—');
    assert.strictEqual(PD.fmtNum(1234567), '1,234,567');
  });

  t('★ 超长检索式：脚注按预算收口，不得溢出画布', () => {
    // 真实检索式长 90+ 字符；不裁剪会把文字推到 x≈1251（画布仅 900），渲染时整行被裁掉，
    // 而「未读到的是哪几条」正是这条脚注存在的全部理由。
    const longKw = 'TITLE_ABS:("urolithiasis" OR FLUTD OR struvite OR oxalate OR "urine pH") AND TITLE_ABS:(cat OR dogs) AND SRC:MED';
    const log = mkLog({
      runs: [{ keyword: longKw, reportedTotal: null, retrieved: 9, pages: 1, durationMs: 1, countState: 'collect_failed' }],
      dedupe: null, evidence: null,
    });
    const svg = PD.renderSvg(log);
    const line = svg.split('\n').find((l) => l.includes('pd-foot') && l.includes('未读到计数'));
    assert.ok(line, '未读到脚注缺失');
    const body = line.slice(line.indexOf('>') + 1, line.indexOf('</text>'));
    const wOf = (s) => [...s].reduce((a, ch) => a + (ch.codePointAt(0) > 0x2e80 ? 10.5 : 10.5 * 0.55), 0);
    // 画布 900 - 左右 padding 48 - 右侧余量 36
    assert.ok(wOf(body) <= 900 - 48 - 36, '脚注估算宽 ' + wOf(body).toFixed(0) + ' 超出预算 816');
    assert.ok(body.includes('≠ 0 命中'), '裁剪时丢了「≠ 0 命中」这一不可省语义');
    assert.ok(/等 1 条|…/.test(body), '裁剪后未标注被省略的条目数');
  });

  t('★ writeLog(svg:true) 落盘 PRISMA.svg 且 md 内联引用', () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pd-'));
    const w = P.writeLog(dir, mkLog(), { svg: true });
    assert.ok(w.svgPath && fs.existsSync(w.svgPath), 'PRISMA.svg 未生成');
    assert.strictEqual(w.svgError, null);
    const md = fs.readFileSync(w.mdPath, 'utf8');
    assert.ok(md.includes('![PRISMA 流程计数图](PRISMA.svg)'), 'md 未引用图');
    assert.ok(md.includes('ASCII 版为纯文本兜底'), 'md 未说明 ASCII 兜底关系');
    fs.rmSync(dir, { recursive: true, force: true });
  });

  t('★ writeLog 缺省（不出图）时零 svg 且 md 无引用（旧调用方零回归）', () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pd-'));
    const w = P.writeLog(dir, mkLog());
    assert.strictEqual(w.svgPath, null);
    assert.ok(!fs.existsSync(path.join(dir, 'PRISMA.svg')), '缺省不该出图');
    const md = fs.readFileSync(w.mdPath, 'utf8');
    assert.ok(!md.includes('PRISMA.svg'), '缺省时 md 不该出现图引用（断链）');
    assert.ok(md.includes('识别 Identification'), 'ASCII 兜底段丢失');
    fs.rmSync(dir, { recursive: true, force: true });
  });

  t('★ writeLog 出图失败：md 仍落盘且写明原因，不留断链引用', () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pd-'));
    const bad = mkLog();
    bad.included.recordsIncluded = bad.eligibility.recordsAssessed + 9;  // 违反不变式
    const w = P.writeLog(dir, bad, { svg: true });
    assert.ok(w.svgError, '违反不变式却未报错');
    assert.strictEqual(w.svgPath, null);
    assert.ok(fs.existsSync(w.mdPath), '图失败连 md 都没写 ⇒ 存档丢失');
    const md = fs.readFileSync(w.mdPath, 'utf8');
    assert.ok(md.includes('流程图未生成'), 'md 未写明失败');
    assert.ok(!md.includes('![PRISMA 流程计数图]'), 'md 留有断链引用');
    fs.rmSync(dir, { recursive: true, force: true });
  });

  t('源码守卫：prisma-diagram.cjs 顶层零 IO / 零网络', () => {
    const src = fs.readFileSync(path.join(__dirname, 'lib', 'prisma-diagram.cjs'), 'utf8');
    assert.ok(!/^const\s+fs\s*=\s*require/m.test(src), '模块顶层 require 了 fs ⇒ 渲染不再是纯函数');
    assert.ok(!/^const\s+path\s*=\s*require/m.test(src), '模块顶层 require 了 path');
    assert.ok(!/fetch\(/.test(src), '出现 fetch ⇒ 渲染过程可能有网络副作用');
    // xmlns 是 SVG 规范要求（不是网络引用）；除它以外出现任何 URL 都算越界
    const urls = (src.match(/https?:\/\/[^\s"'<)]*/g) || []).filter((u) => !/w3\.org/.test(u));
    assert.strictEqual(urls.length, 0, '出现外部网络引用：' + urls.join('、'));
  });

  // ── v4.10 全文通道（异步：mock fetch，离线可测）───────────────
  const FT2 = require('./lib/fulltext.cjs');
  const REC_TITLE = 'Increasing Dietary Potassium Enhances Urine Production in Senior Cats';
  // 结构与实测 2026-10-21 的 EPMC core 响应逐字段一致（含 fullTextIdList 的**嵌套对象**形态）
  const mkCore = (over) => ({
    resultList: {
      result: [Object.assign({
        id: '42278121', source: 'MED', pmid: '42278121', pmcid: 'PMC13255985',
        doi: '10.3390/ani16111689', title: REC_TITLE,
        pubYear: '2026', isOpenAccess: 'Y', inPMC: 'Y', hasPDF: 'Y', license: 'cc by',
        citedByCount: '3', abstractText: 'Study one was a crossover trial.',
        journalInfo: { journal: { title: 'Animals' } },
        pubTypeList: { pubType: ['research-article', 'Journal Article'] },
        grantsList: { grant: [{ agency: "Hill's Pet Nutrition (United States)" }] },
        fullTextIdList: { fullTextId: ['PMC13255985'] },
        fullTextUrlList: {
          fullTextUrl: [
            { availabilityCode: 'S', documentStyle: 'doi', url: 'https://doi.org/10.3390/ani16111689' },
            { availabilityCode: 'OA', documentStyle: 'html', url: 'https://europepmc.org/articles/PMC13255985' },
            { availabilityCode: 'OA', documentStyle: 'pdf', url: 'https://europepmc.org/articles/PMC13255985?pdf=render' },
          ],
        },
      }, over || {})],
    },
  });

  await withFetch(async () => ({ ok: true, status: 200, json: async () => mkCore() }), async () => {
    await ta('★ enrich 补全 pmcid/hasPDF/license/资助方（与摘要同一响应，零新增请求）', async () => {
      const r = await ENR.enrichOne({ titleEn: REC_TITLE, year: 2026 });
      assert.strictEqual(r.pmcid, 'PMC13255985');
      assert.strictEqual(r.hasPDF, true);
      assert.strictEqual(r.license, 'cc by');
      assert.strictEqual(r.inPMC, true);
      assert.deepStrictEqual(r.funders, ["Hill's Pet Nutrition (United States)"]);
      assert.ok(Array.isArray(r.pubTypes) && r.pubTypes.indexOf('research-article') >= 0);
      assert.strictEqual(r.citedByCount, 3);
    });
    await ta('fullTextUrl 优先取 OA 的 html，而不是 DOI 订阅页', async () => {
      const r = await ENR.enrichOne({ titleEn: REC_TITLE, year: 2026 });
      assert.ok(/europepmc\.org\/articles\/PMC13255985$/.test(String(r.fullTextUrl)), '实际 ' + r.fullTextUrl);
    });
  });

  await withFetch(async () => {
    const c = mkCore();
    const one = c.resultList.result[0];
    delete one.hasPDF; delete one.inPMC; delete one.license; delete one.citedByCount;
    return { ok: true, status: 200, json: async () => c };
  }, async () => {
    await ta('★ hasPDF/license/inPMC 字段缺失 ⇒ null（不得当成 false / 空串）', async () => {
      const r = await ENR.enrichOne({ titleEn: REC_TITLE, year: 2026 });
      assert.strictEqual(r.hasPDF, null, 'hasPDF 缺失被写成了 ' + r.hasPDF);
      assert.strictEqual(r.inPMC, null);
      assert.strictEqual(r.license, null);
      assert.strictEqual(r.citedByCount, null);
    });
  });

  await ta('fetchFullText：非法 pmcid 不发请求，直接 error:bad_pmcid', async () => {
    const r = await FT2.fetchFullText('13255985');
    assert.strictEqual(r.status, 'error:bad_pmcid');
  });

  await withFetch(async () => ({ ok: false, status: 404, text: async () => '' }), async () => {
    await ta('fetchFullText：404 ⇒ error:404（不是笼统的「未知错误」）', async () => {
      const r = await FT2.fetchFullText('PMC99999999');
      assert.strictEqual(r.status, 'error:404');
    });
  });

  await withFetch(async () => ({ ok: true, status: 200, text: async () => '<!doctype html><html>Access denied</html>' }), async () => {
    await ta('★ fetchFullText：200 却返回 HTML ⇒ error:not_xml（不得当成功）', async () => {
      const r = await FT2.fetchFullText('PMC13255985');
      assert.strictEqual(r.status, 'error:not_xml');
    });
  });

  await withFetch(async () => ({ ok: true, status: 200, text: async () => SAMPLE_XML }), async () => {
    await ta('★ runFulltextBatch 成功路径：必须写 status=ok 且 txt 偏移可回查', async () => {
      // 初版只在**缓存路径**写了 status，成功路径漏了 ⇒ 报告层判 `status === 'ok'` 失败、
      // 方法学信号整段不显示。只测失败路径的夹具抓不到这个洞（靠真实端到端才暴露）。
      const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ft-ok-'));
      const records = [{ titleEn: 'A', enrich: { pmcid: 'PMC123' } }];
      const { stat } = await FT2.runFulltextBatch(records, { outDir: dir, concurrency: 1, intervalMs: 0 });
      assert.strictEqual(stat.ok, 1, '应成功 1 条，实际 ' + JSON.stringify(stat));
      assert.strictEqual(records[0].fulltext.status, 'ok', '成功路径未写 status ⇒ 报告不显示方法学信号');
      assert.ok(records[0].fulltext.signals.length > 0, '未抽出信号');
      assert.ok(records[0].fulltext.methods, '未定位方法学节');
      const txt = fs.readFileSync(path.join(dir, 'fulltext', 'PMC123.txt'), 'utf8');
      for (const s of records[0].fulltext.signals) {
        assert.strictEqual(txt.slice(s.offset, s.offset + s.length), s.matched,
          '落盘 txt 与 offset 不匹配：' + s.key);
      }
      const again = [{ titleEn: 'A', enrich: { pmcid: 'PMC123' } }];
      const s2 = await FT2.runFulltextBatch(again, { outDir: dir, concurrency: 1, intervalMs: 0 });
      assert.strictEqual(s2.stat.cached, 1, '第二次应走缓存');
      assert.strictEqual(again[0].fulltext.signals.length, records[0].fulltext.signals.length);
      fs.rmSync(dir, { recursive: true, force: true });
    });
  });

  await withFetch(async () => ({ ok: false, status: 404, text: async () => '' }), async () => {
    await ta('★ runFulltextBatch：失败只记状态，不写任何等级字段；OA 无 pmcid 单列', async () => {
      const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ft-'));
      const records = [
        { titleEn: 'A', enrich: { pmcid: 'PMC99999999', isOA: true } },   // 会 404
        { titleEn: 'B', enrich: { pmcid: null, isOA: true } },            // OA 但无 pmcid（矛盾态）
        { titleEn: 'C', enrich: { pmcid: null, isOA: false } },           // 非 OA
      ];
      const { stat } = await FT2.runFulltextBatch(records, { outDir: dir, concurrency: 1, intervalMs: 0 });
      assert.strictEqual(stat.withPmcid, 1);
      assert.strictEqual(stat.failed, 1);
      assert.strictEqual(records[0].fulltext.status, 'error:404');
      assert.strictEqual(stat.oaWithoutPmcid, 1, 'OA 但无 pmcid 必须单列计数');
      assert.strictEqual(stat.noPmcid, 2);
      for (const r of records) {
        assert.ok(!('evidenceLevel' in r) && !('grade' in r) && !('evidence' in r),
          '全文步骤写入了分级相关字段 ⇒ 违反「只补信息不改等级」');
      }
      assert.ok(!fs.existsSync(path.join(dir, 'fulltext', 'PMC99999999.txt')), '失败时不该留下 txt');
      fs.rmSync(dir, { recursive: true, force: true });
    });
  });

  // ─────────────── v4.11：证据分布三张图（evidence-charts.cjs）───────────────
  // 判据三条主线：
  //   ① 计数守恒（各档之和 = 总数、行列投影互相自洽）—— 不守恒就不许出图；
  //   ② needsReview 恒 true ⇒ 图上任何一档都不许画成「确定等级」（斜纹 + 警示带）；
  //   ③ 年份缺失 ≠ 0 年（null 进「未标注」列，与时间轴断开）。
  const EC = require('./lib/evidence-charts.cjs');
  // 记录形状必须与 gradeAll() 的产出**逐字段一致** —— assemble 的证据表会读
  // designLevel.value / speciesRelevance.label / sampleSize.value，缺一个整份报告就崩。
  const evRec = (g, rel, year, extra) => Object.assign({
    idx: 1, titleEn: 'T', year: year,
    evidence: {
      evidenceGrade: g,
      evidenceGradeLabel: '候选等级',
      designLevel: { value: 'L2', label: '对照试验', confidence: 'medium', candidates: [] },
      speciesRelevance: { relevance: rel, label: rel, confidence: 'medium', targetSpecies: [] },
      sampleSize: { value: 24, confidence: 'medium', candidates: [] },
      dose: { candidates: [] },
      gradeBasis: 'design_identified',
      flags: [],
      needsReview: true,
      inputs: { abstractSource: 'epmc_full' },
      publicationYear: year,
    },
  }, extra || {});
  // 真实分布形状：67 条，A 少 D 多（实测 D 档占比高）
  const mkCohort = () => {
    const out = [];
    const add = (n, g, rel, years) => { for (let i = 0; i < n; i++) out.push(evRec(g, rel, years[i % years.length])); };
    add(2, 'A', 'target_species', [2026, 2024]);
    add(5, 'B', 'target_species', [2023, 2022, 2021]);
    add(3, 'C', 'mixed_species', [2020, 2019, 2018]);
    add(3, 'C', 'in_vitro_only', [2020, 2017, 2015]);
    add(2, 'C', 'non_target_animal', [2016, 2012]);
    add(30, 'D', 'unclear', [2014, 2011, 2008]);
    add(22, 'D', 'target_species', [2013, 2019, 2006, 2010]);
    return out;
  };

  console.log('evidence-charts（证据分布三图）:');

  t('collect：各档之和 = 总数，候选 + 已确认 = 总数', () => {
    const co = mkCohort();
    const st = EC.collect(co);
    assert.strictEqual(st.total, co.length);
    assert.strictEqual(st.gradeStat.A + st.gradeStat.B + st.gradeStat.C + st.gradeStat.D, co.length);
    assert.strictEqual(st.candidateCount + st.confirmedCount, co.length);
    assert.deepStrictEqual(EC.validate(st).violations, []);
    assert.strictEqual(st.allCandidate, true, '默认全部 needsReview ⇒ allCandidate 应为 true');
  });

  t('collect：needsReview 恒 true 不得被当成「已确认 0 条所以不用管」', () => {
    const st = EC.collect([evRec('A', 'target_species', 2024)]);
    assert.strictEqual(st.confirmedCount, 0);
    assert.strictEqual(st.candidateCount, 1);
    assert.strictEqual(EC.validate(st).ok, true);
  });

  t('collect：显式 reviewed:true 才算人工确认（needsReview 字段本身不算）', () => {
    const r1 = evRec('A', 'target_species', 2024);
    const r2 = evRec('A', 'target_species', 2024);
    r2.evidence.reviewed = true;
    r2.evidence.needsReview = false;                 // 只有 needsReview:false 不算数
    const r3 = evRec('B', 'target_species', 2024);
    r3.evidence.reviewed = false;
    const st = EC.collect([r1, r3]);
    assert.strictEqual(st.confirmedCount, 0, 'needsReview:false 不应被当成已确认');
    assert.strictEqual(EC.isConfirmed(r3), false, 'reviewed:false 不是确认');
    const st2 = EC.collect([r1, r2, r3]);
    assert.strictEqual(st2.confirmedCount, 1);
    assert.strictEqual(st2.confirmedStat.A, 1);
    assert.strictEqual(st2.allCandidate, false);
  });

  t('collect：非 A-D 等级 → validate 失败并点名（不静默丢弃）', () => {
    const st = EC.collect([evRec('A', 'target_species', 2024), evRec('E', 'target_species', 2024)]);
    const vr = EC.validate(st);
    assert.strictEqual(vr.ok, false);
    assert.ok(vr.violations.join('|').includes('非 A/B/C/D'), '未点名非法等级：' + vr.violations.join('|'));
    assert.throws(() => EC.buildCharts([evRec('E', 'target_species', 2024)]), /非 A\/B\/C\/D/);
  });

  t('collect：无 evidence 的记录单列 noEvidence，不计入 total（守恒仍成立）', () => {
    const st = EC.collect([evRec('A', 'target_species', 2024), { idx: 2, titleEn: 'X' }]);
    assert.strictEqual(st.noEvidence, 1);
    assert.strictEqual(st.total, 1);
    assert.strictEqual(EC.validate(st).ok, true);
    const svg = EC.buildCharts([evRec('A', 'target_species', 2024), { idx: 2 }]).charts[0].svg;
    assert.ok(svg.includes('无 evidence 字段'), '未在图上说明还有未分级记录');
  });

  t('collect：year=null 进「未标注」，绝不当成 0 年或某一年', () => {
    const st = EC.collect([evRec('A', 'target_species', null), evRec('B', 'target_species', 2024)]);
    assert.strictEqual(st.yearMissing, 1);
    assert.strictEqual(st.yearInvalid, 0);
    assert.deepStrictEqual(Object.keys(st.yearTotals), ['2024'], 'null 年份不得进入时间轴');
    assert.strictEqual(EC.pickYear({ year: null }, { publicationYear: null }).state, 'missing');
    assert.strictEqual(EC.pickYear({ year: 0 }, {}).state, 'invalid', 'year=0 必须判非法，不能当公元 0 年');
    assert.strictEqual(EC.pickYear({ year: 'n.d.' }, {}).state, 'invalid');
    assert.strictEqual(EC.pickYear({ year: undefined }, { publicationYear: 2019 }).year, 2019, '回退 publicationYear');
  });

  t('collect：年份三态之和 = 总数（合法 + 未标注 + 非法，一条都不许丢）', () => {
    const st = EC.collect([
      evRec('A', 'target_species', 2024), evRec('B', 'target_species', null),
      evRec('C', 'target_species', 'n.d.'), evRec('D', 'target_species', 2011),
    ]);
    assert.strictEqual(st.yearMissing, 1);
    assert.strictEqual(st.yearInvalid, 1);
    const dated = Object.values(st.yearTotals).reduce((a, o) => a + o.A + o.B + o.C + o.D, 0);
    assert.strictEqual(dated + st.yearMissing + st.yearInvalid, st.total);
  });

  t('collect：未登记的物种相关性取值单列保留，行和仍等于该档计数', () => {
    const st = EC.collect([evRec('B', 'brand_new_category', 2024), evRec('B', 'target_species', 2024)]);
    assert.deepStrictEqual(st.extraSpecies, ['brand_new_category']);
    assert.strictEqual(EC.validate(st).ok, true, '未登记取值不得破坏行和守恒');
    const svg = EC.buildCharts([evRec('B', 'brand_new_category', 2024)]).charts[1].svg;
    assert.ok(svg.includes('brand_new_category'), '未登记列未在图上出现');
  });

  t('buildCharts：三张图齐出，文件名固定（下游引用不漂移）', () => {
    const b = EC.buildCharts(mkCohort());
    assert.deepStrictEqual(b.charts.map(c => c.file),
      ['evidence-grade-dist.svg', 'evidence-grade-species.svg', 'evidence-year-grade.svg']);
    for (const c of b.charts) {
      assert.ok(/^<\?xml/.test(c.svg), c.file + ' 缺 xml 声明');
      assert.ok(c.svg.includes('viewBox="0 0 900 '), c.file + ' viewBox 宽度不是 900');
      assert.ok(c.svg.includes('role="img"') && c.svg.includes('<title>'), c.file + ' 缺可访问性要素');
    }
  });

  t('buildCharts：空输入返回 null（不画空图，也不假装有数据）', () => {
    assert.strictEqual(EC.buildCharts([]), null);
    assert.strictEqual(EC.buildCharts([{ idx: 1 }]), null, '全是未分级记录时同样不出图');
  });

  t('图①：全候选时必挂警示带，且明写「不是结论」', () => {
    const svg = EC.buildCharts(mkCohort()).charts[0].svg;
    assert.ok(svg.includes('不是结论'), '全候选却没写「不是结论」——needsReview 被当成样板字了');
    assert.ok(svg.includes('斜纹 = 候选待人工确认'), '图例未解释斜纹');
    assert.ok(svg.includes('url(#ec-cand-1)'), '候选段未使用斜纹 pattern');
  });

  t('图①：出现已确认记录后，警示带消失（证伪方向必须也测）', () => {
    const co = mkCohort();
    co[0].evidence.reviewed = true;
    const svg = EC.buildCharts(co).charts[0].svg;
    assert.strictEqual(svg.includes('不是结论'), false, '有 1 条已确认仍挂「全部为候选」警示带 ⇒ 文案与数据不符');
    assert.ok(svg.includes('已确认 1'), '未更新已确认计数');
  });

  t('图①：候选的记号是斜纹而非淡化颜色（降透明度会把 A/B 压成同色）', () => {
    const all = EC.buildCharts(mkCohort()).charts[0].svg;
    // 数据段的斜纹层用 stroke-dasharray="3 2"（图例方块用 2 1.5，不计入）
    assert.strictEqual((all.match(/stroke-dasharray="3 2"/g) || []).length, 4, '四档数据段各应有一层斜纹覆盖');
    assert.strictEqual(/fill-opacity="0\.35"/.test(all), false,
      '仍在用降低透明度表示候选 ⇒ #0f5132(A) 与 #7cc47f(B) 会压成几乎同色');
    // 证伪方向：部分确认后，A 档必须出现「无斜纹的纯色段」
    const co = mkCohort();
    co[0].evidence.reviewed = true;
    const part = EC.buildCharts(co).charts[0].svg;
    const solidA = [...part.matchAll(/<rect[^>]*fill="#0f5132"[^>]*\/>/g)].map(m => m[0])
      .filter(r => !/width="9"/.test(r));
    assert.ok(solidA.length >= 1, '确认段未画成纯色');
    assert.strictEqual(solidA.some(r => r.includes('url(')), false, '确认段也被斜纹覆盖了');
  });

  t('图①：0 条的档要显式写「0 条」，不能留空轨道当缺失', () => {
    const svg = EC.buildCharts([evRec('A', 'target_species', 2024)]).charts[0].svg;
    const trackZero = (svg.match(/class="ec-note"[^>]*>0 条</g) || []).length;
    assert.strictEqual(trackZero, 3, 'B/C/D 三档的轨道内应各写一次「0 条」（实际 ' + trackZero + '）');
  });

  t('图①：D 档成因之和必须等于 D 档计数（不得拿全体记录的成因充数）', () => {
    const st = EC.collect(mkCohort());
    const bsum = Object.values(st.dBasis).reduce((a, n) => a + n, 0);
    assert.strictEqual(bsum, st.gradeStat.D, 'D 档成因之和与 D 档计数不符');
    assert.ok(st.gradeStat.D < st.total, '夹具里 D 档应少于总数，否则本用例失去意义');
    const svg = EC.buildCharts(mkCohort()).charts[0].svg;
    assert.ok(svg.includes('D 档成因分解（合计 ' + st.gradeStat.D + ' 条）'), '脚注未给合计，读者无法自行核对');
    // 证伪方向：把全体成因当成 D 档成因时，validate 必须报
    const bad = EC.collect(mkCohort());
    bad.dBasis = JSON.parse(JSON.stringify(bad.gradeBasis));
    assert.strictEqual(EC.validate(bad).ok, false, '全体成因冒充 D 档成因时未报错');
  });


  t('图②：矩阵行列自洽（行和 = 该档计数，列合计 = 该物种计数）', () => {
    const b = EC.buildCharts(mkCohort());
    const st = b.stats;
    for (const g of EC.GRADE_ORDER) {
      const row = Object.values(st.matrix[g] || {}).reduce((a, n) => a + n, 0);
      assert.strictEqual(row, st.gradeStat[g], g + ' 行和与档计数不一致');
    }
    const colSum = Object.values(st.speciesTotals).reduce((a, n) => a + n, 0);
    assert.strictEqual(colSum, st.total, '列合计不等于总数');
    assert.ok(b.charts[1].svg.includes('列合计'), '图上缺列合计行');
  });

  t('图③：年份缺失 → 「未标注」列 + 与时间轴断开标记', () => {
    const co = mkCohort().concat([evRec('D', 'unclear', null), evRec('D', 'unclear', null)]);
    const svg = EC.buildCharts(co).charts[2].svg;
    assert.ok(/text-anchor="middle">未标注</.test(svg), '缺「未标注」列标签');
    assert.ok(svg.includes('stroke-dasharray="3 3"'), '未标注列与时间轴之间缺断开标记');
    assert.ok(svg.includes('不得当作 0 或某一年'), '脚注未说明未标注的口径');
  });

  t('图③：无年份缺失时不得出现「未标注」列（避免无中生有）', () => {
    const svg = EC.buildCharts(mkCohort()).charts[2].svg;
    assert.strictEqual(/text-anchor="middle">未标注</.test(svg), false, '没有缺失却画了「未标注」列');
    assert.ok(svg.includes('无「未标注」列'), 'desc 未随数据更新（仍是「含未标注列」的旧文案）');
  });

  t('yearBuckets：跨度 ≤ 上限时逐年，且缺年份补空柱（不压缩时间轴）', () => {
    const bk = EC.yearBuckets({ 2020: { A: 1, B: 0, C: 0, D: 0, cA: 0 }, 2024: { A: 1, B: 0, C: 0, D: 0, cA: 0 } }, 14);
    assert.deepStrictEqual(bk.map(b => b.label), ['2020', '2021', '2022', '2023', '2024']);
    assert.strictEqual(bk[2].counts.A, 0, '中间空年份必须是 0 的桶，不能跳过');
  });

  t('yearBuckets：跨度过大按段合并，标签带区间、脚注声明「段内合计」', () => {
    const bk = EC.yearBuckets({ 1998: { A: 1, B: 0, C: 0, D: 0, cA: 0 }, 2026: { A: 0, B: 1, C: 0, D: 0, cA: 0 } }, 14);
    assert.ok(bk.length < 10, '分段后桶数应明显少于逐年');
    assert.ok(bk.every(b => b.label.includes('-')), '分段标签应带区间');
    const svg = EC.buildCharts([evRec('A', 'target_species', 1998), evRec('B', 'target_species', 2026)]).charts[2].svg;
    assert.ok(svg.includes('段内合计'), '分段却未在图上声明口径');
  });

  t('刻度尺：step 必为 1/2/5×10ⁿ 且档数 ≤4（不得出现 0/7/14/21/28 这种读数困难的轴）', () => {
    for (const v of [1, 3, 7, 13, 27, 54, 67, 100, 101, 999]) {
      const s = EC.niceScale(v);
      assert.ok(s.max >= v, 'max ' + s.max + ' < 数据最大值 ' + v + ' ⇒ 柱子会溢出');
      assert.ok(s.max / s.step <= 4, 'v=' + v + ' 时档数 ' + (s.max / s.step) + ' > 4');
      assert.ok(/^[125]0*$/.test(String(s.step)), 'v=' + v + ' 的 step=' + s.step + ' 不是 1/2/5×10ⁿ');
    }
    assert.deepStrictEqual(EC.niceScale(27), { max: 30, step: 10 }, '27 条应画成 0/10/20/30');
    assert.deepStrictEqual(EC.niceScale(7), { max: 8, step: 2 }, '7 条应画成 0/2/4/6/8');
    // 回归：旧实现 ceil(v/4)*4 在 v=27 时给出 28，刻度是 7/14/21
    assert.notStrictEqual(EC.niceMax(27), EC.niceScale(27).max, '旧的 niceMax 仍在被使用');
  });


  t('几何校验：三张图 0 越界（rect 四边 + 文字宽度 + y）', () => {
    const b = EC.buildCharts(mkCohort());
    for (const c of b.charts) {
      const v = EC.geomCheck(c.svg);
      assert.deepStrictEqual(v, [], c.file + ' 几何违规：' + v.slice(0, 2).join(' / '));
    }
  });

  t('几何校验器能被证伪：注入超长文字必须报 G2（否则等于没有检查器）', () => {
    const svg = EC.buildCharts([evRec('A', 'target_species', 2024)]).charts[0].svg;
    const injected = svg.replace('共 1 条分级记录', '共 1 条分级记录' + '撑破右边界的冗长说明'.repeat(10));
    const v = EC.geomCheck(injected);
    assert.ok(v.some(s => s.startsWith('G2')), '注入超长文字后未报 G2 ⇒ 检查器恒绿');
    assert.ok(v.some(s => /画布 900/.test(s)), '违规信息未给出画布宽度');
  });

  t('几何校验器误报守卫：rect 省略 x/y（pattern 内）不得判越界', () => {
    const svg = EC.buildCharts([evRec('A', 'target_species', 2024)]).charts[0].svg;
    assert.ok(/<rect width="7" height="7"/.test(svg), '样本里没有省略 x/y 的 rect，本用例失去意义');
    assert.deepStrictEqual(EC.geomCheck(svg).filter(s => s.startsWith('G1')), []);
  });

  t('三张图的可见文字里不得出现 Markdown 标记（SVG 不解析 ** 与反引号，会原样显示）', () => {
    for (const c of EC.buildCharts(mkCohort()).charts) {
      for (const m of c.svg.matchAll(/<text[^>]*>([^<]*)<\/text>/g)) {
        const s = m[1];
        assert.ok(!s.includes('**'), c.file + ' 文字含 **：' + s.slice(0, 40));
        assert.ok(!s.includes('`'), c.file + ' 文字含反引号：' + s.slice(0, 40));
      }
    }
  });

  t('确定性：同一输入两次生成逐字节一致', () => {
    const a = EC.buildCharts(mkCohort()).charts.map(c => c.svg);
    const b = EC.buildCharts(mkCohort()).charts.map(c => c.svg);
    assert.deepStrictEqual(a, b, '两次生成结果不同 ⇒ 排序/时间戳/locale 未固定');
    for (const s of a) assert.strictEqual(/generatedAt|Date\(|toLocaleString/.test(s), false, '产物含时间戳/locale 用法');
  });

  t('落盘：charts/ 目录三文件 + 返回 charts 明细；失败不影响其余', () => {
    const dir = mkDir('ec-write');
    const r = EC.writeCharts(dir, mkCohort());
    assert.strictEqual(r.files.length, 3);
    assert.strictEqual(r.errors.length, 0);
    for (const c of r.charts) assert.ok(fs.existsSync(c.path), c.file + ' 未落盘');
    const bad = EC.writeCharts(dir, [evRec('Z', 'target_species', 2024)]);
    assert.strictEqual(bad.files.length, 0);
    assert.strictEqual(bad.charts.length, 0);
    assert.strictEqual(bad.errors.length, 1, '不变式违反必须以 errors 返回，不能静默');
  });

  t('接入：assemble 默认出图，报告含图表节与 charts/ 引用', () => {
    const d = mkDir('as-charts');
    putRaw(d, '01-k.json', { runId: 'R1', keyword: 'k', records: [
      evRec('A', 'target_species', 2024), evRec('C', 'in_vitro_only', 2020), evRec('D', 'unclear', null),
    ] });
    fs.writeFileSync(path.join(d, 'summary.json'), JSON.stringify({ runId: 'R1', startedAt: 'now', site: 'kuluer', keywords: { k: { count: 3 } } }), 'utf8');
    const out = AR.assemble({ dir: d, format: 'md' });
    const md = fs.readFileSync(out.md, 'utf8');
    assert.ok(md.includes('## 证据分布图'), '报告缺图表节');
    assert.ok(md.includes('](charts/evidence-grade-dist.svg)'), '缺图①引用');
    assert.ok(md.includes('](charts/evidence-year-grade.svg)'), '缺图③引用');
    assert.strictEqual(out.charts.length, 3);
    assert.deepStrictEqual(out.chartErrors, []);
    assert.strictEqual(out.chartsStat.confirmed, 0);
    // 图必须在表格之前（先看形状再逐条核）
    assert.ok(md.indexOf('## 证据分布图') < md.indexOf('## 证据分级候选一览'), '图表节应在表格之前');
    assert.ok(md.includes('不是结论'), '报告未转述「候选不是结论」');
  });

  t('接入：--no-charts 关闭时不出图、不加节（保持旧产物形状）', () => {
    const d = mkDir('as-charts-off');
    putRaw(d, '01-k.json', { runId: 'R1', keyword: 'k', records: [evRec('A', 'target_species', 2024)] });
    fs.writeFileSync(path.join(d, 'summary.json'), JSON.stringify({ runId: 'R1', keywords: { k: { count: 1 } } }), 'utf8');
    const out = AR.assemble({ dir: d, format: 'md', charts: false });
    const md = fs.readFileSync(out.md, 'utf8');
    assert.strictEqual(md.includes('## 证据分布图'), false);
    assert.strictEqual(out.charts.length, 0);
    assert.strictEqual(fs.existsSync(path.join(d, 'charts')), false, '关闭时不得留下空 charts 目录');
    assert.strictEqual(AR.parseArgs(['node', 'x', '--dir', d, '--no-charts']).charts, false);
    assert.strictEqual(AR.parseArgs(['node', 'x', '--dir', d]).charts, true);
  });

  t('接入：无 evidence 的旧产物零回归（不出图、不加节、报告仍完整）', () => {
    const d = mkDir('as-charts-none');
    putRaw(d, '01-k.json', { runId: 'R1', keyword: 'k', records: [{ idx: 1, titleEn: 'NO_EVIDENCE_PAPER' }] });
    fs.writeFileSync(path.join(d, 'summary.json'), JSON.stringify({ runId: 'R1', keywords: { k: { count: 1 } } }), 'utf8');
    const out = AR.assemble({ dir: d, format: 'md' });
    const md = fs.readFileSync(out.md, 'utf8');
    assert.ok(md.includes('NO_EVIDENCE_PAPER'));
    assert.strictEqual(md.includes('## 证据分布图'), false);
    assert.strictEqual(out.charts.length, 0);
  });

  t('接入：不变式被破坏 → 报告仍生成，且明写「图未生成」与原因', () => {
    const d = mkDir('as-charts-bad');
    putRaw(d, '01-k.json', { runId: 'R1', keyword: 'k', records: [evRec('A', 'target_species', 2024), evRec('Q', 'target_species', 2024)] });
    fs.writeFileSync(path.join(d, 'summary.json'), JSON.stringify({ runId: 'R1', keywords: { k: { count: 2 } } }), 'utf8');
    const out = AR.assemble({ dir: d, format: 'md' });
    const md = fs.readFileSync(out.md, 'utf8');
    assert.ok(md.includes('证据分级候选一览'), '表也不该被图拖垮');
    assert.ok(md.includes('证据分布图未生成'), '未在报告里大声报错');
    assert.ok(out.chartErrors.length >= 1);
    assert.ok(out.chartErrors.join(' ').includes('非 A/B/C/D'), '未给出可定位的原因');
  });

  t('源码守卫：evidence-charts.cjs 顶层零 IO / 零网络 / 不写 evidenceLevel', () => {
    const src = fs.readFileSync(path.join(__dirname, 'lib', 'evidence-charts.cjs'), 'utf8');
    assert.ok(!/^const\s+fs\s*=\s*require/m.test(src), '顶层 require fs ⇒ 渲染不再是纯函数（落在 writeCharts 内才允许）');
    assert.ok(!/^const\s+path\s*=\s*require/m.test(src), '顶层 require path');
    assert.ok(!/fetch\(/.test(src), '出现 fetch');
    assert.ok(!/evidenceLevel\s*[:=]/.test(src), '模块写了 evidenceLevel ⇒ 越界改等级');
    // 唯一的 fs/path 只能在 writeCharts 内出现
    const body = src.split('function writeCharts')[0];
    assert.strictEqual(/require\('(fs|path)'\)/.test(body), false, 'writeCharts 之外出现 IO 依赖');
    const urls = (src.match(/https?:\/\/[^\s"'<)]*/g) || []).filter(u => !/w3\.org/.test(u));
    assert.strictEqual(urls.length, 0, '出现外部网络引用：' + urls.join('、'));
  });

  // ─────────────── v4.12：综合归纳（synthesis.cjs）───────────────
  // 判据主线：① 每句挂行号（含「N 条」就必须能点开核对）；② 行号与表格同序；
  //           ③ 不做有效性判断；④ needsReview 必须说破；⑤ 空集必须显式写「无」而不是省略。
  const SY = require('./lib/synthesis.cjs');
  const mkGraded = (arr) => arr.map((r) => ({ g: { keyword: 'k', records: [r] }, r }));
  // 已排序的 6 条：A(2024) / A(2022) / B(2023) / C(2019) / D(1998) / D(null)
  const G6 = () => mkGraded([
    evRec('A', 'target_species', 2024),
    evRec('A', 'target_species', 2022),
    evRec('B', 'target_species', 2023),
    evRec('C', 'in_vitro_only', 2019),
    evRec('D', 'target_species', 1998),
    evRec('D', 'unclear', null),
  ]);

  console.log('synthesis（综合归纳）:');

  t('六节齐全（大纲优先：先给结构，再逐条陈述）', () => {
    const { md } = SY.buildSynthesis(G6(), { nowYear: 2026 });
    const want = ['### 一、证据强度', '### 二、宣称可用性', '### 三、物种与设计风险', '### 四、时间分布', '### 五、需人工优先处理', '### 六、证据缺口'];
    for (const h of want) assert.ok(md.some((l) => l.includes(h)), '缺小节：' + h);
    assert.ok(md[0].startsWith('## 综合归纳'), '首行不是章节标题');
  });

  t('每句挂行号：凡含「N 条」的条目必须带 [#n]（否则读者无法核对）', () => {
    const { md } = SY.buildSynthesis(G6(), { nowYear: 2026 });
    const items = md.filter((l) => l.startsWith('- '));
    assert.ok(items.length >= 8, '条目太少，本用例失去意义');
    for (const it of items) {
      if (it.startsWith('- ⇒')) continue;                 // 推论句，不含新事实
      if (!/[1-9][0-9]* 条/.test(it)) continue;            // 不含条数的不要求
      assert.ok(it.includes('[#'), '含条数却没挂行号：' + it.slice(0, 60));
    }
  });

  t('行号与表格同序：A 档两条必须落在 [#1]、[#2]', () => {
    const { md, stats } = SY.buildSynthesis(G6(), { nowYear: 2026 });
    assert.deepStrictEqual(stats.gradeStat, { A: 2, B: 1, C: 1, D: 2 });
    const aLine = md.find((l) => l.includes('**A 档**'));
    assert.ok(/\[#1\]、\[#2\]/.test(aLine), 'A 档行号不对：' + aLine);
    const dLine = md.find((l) => l.includes('**D 档**'));
    assert.ok(/\[#5\]、\[#6\]/.test(dLine), 'D 档行号不对：' + dLine);
  });

  t('行号折叠：超过 5 个引用时折成区间（否则一句比表格还长）', () => {
    assert.strictEqual(SY.refs([1, 2, 3, 4, 5]), '[#1]、[#2]、[#3]、[#4]、[#5]');
    assert.strictEqual(SY.refs([6, 7, 8, 9, 10, 11]), '[#6]–[#11] 等 6 条');
    assert.strictEqual(SY.refs([]), '（无）');
    assert.strictEqual(SY.refs([9, 3, 5]), '[#3]、[#5]、[#9]', 'refs 必须先排序');
  });

  t('四档占比合计恒为 100（逐个四舍五入会得到 101%）', () => {
    assert.deepStrictEqual(SY.pctAll([2, 1, 2, 3], 8), [25, 13, 25, 37], '2/1/2/3 之和必须 = 100');
    for (const nums of [[1, 1, 1, 1], [1, 1, 1, 0], [7, 1, 1, 1], [1, 0, 0, 0], [0, 0, 0, 1]]) {
      const s = nums.reduce((a, b) => a + b, 0);
      const p = SY.pctAll(nums, s);
      assert.strictEqual(p.reduce((a, b) => a + b, 0), 100, 'nums=' + nums + ' 占比合计 ' + p.reduce((a, b) => a + b, 0));
    }
    assert.deepStrictEqual(SY.pctAll([0, 0, 0, 0], 0), [0, 0, 0, 0], 'total=0 时不得除零');
  });

  t('needsReview 恒 true 必须说破：写「未经人工确认」+「不得引用」', () => {
    const { md, stats } = SY.buildSynthesis(G6(), { nowYear: 2026 });
    assert.strictEqual(stats.allCandidate, true);
    const s = md.join('\n');
    assert.ok(s.includes('全部未经人工确认'), '未说破 needsReview');
    assert.ok(s.includes('核对全文方法学章节前不得引用'), '缺「不得引用」警告');
  });

  t('部分已确认时不得再写「全部未经人工确认」（证伪方向）', () => {
    const g = G6();
    g[0].r.evidence.reviewed = true;
    const { md, stats } = SY.buildSynthesis(g, { nowYear: 2026 });
    assert.strictEqual(stats.reviewed, 1);
    assert.strictEqual(md.join('\n').includes('全部未经人工确认'), false, '有 1 条已确认仍写「全部」');
    assert.ok(md.join('\n').includes('已人工确认 1 条'), '未报已确认条数');
  });

  t('A/B 档为空时第三节写「无」，且明说这是「检查过且为空」', () => {
    const g = mkGraded([evRec('C', 'in_vitro_only', 2020), evRec('D', 'unclear', null)]);
    const { md } = SY.buildSynthesis(g, { nowYear: 2026 });
    const i = md.indexOf('### 三、物种与设计风险（A/B 档里站不住的那些）');
    assert.ok(i >= 0);
    assert.ok(md.slice(i, i + 4).join('\n').includes('- 无：'), '空集未显式写「无」');
    assert.ok(md.join('\n').includes('检查过且为空'), '未说明「无」是检查结果而非省略');
  });

  t('A/B 档但没有物种不达标时也要写「无」（不省略整节）', () => {
    const g = mkGraded([evRec('A', 'target_species', 2024), evRec('B', 'target_species', 2023)]);
    const { md, stats } = SY.buildSynthesis(g, { nowYear: 2026 });
    assert.strictEqual(stats.speciesRisk, 0);
    const i = md.indexOf('### 三、物种与设计风险（A/B 档里站不住的那些）');
    assert.ok(md.slice(i, i + 4).join('\n').includes('- 无：'), '无风险时第三节被省略成空节');
  });

  t('时间分桶：null 与 n.d. 都进「年份缺失」，且不落入任何年份段', () => {
    const g = mkGraded([
      evRec('A', 'target_species', 2026), evRec('B', 'target_species', 2019),
      evRec('C', 'target_species', 2010), evRec('D', 'unclear', null), evRec('D', 'unclear', 'n.d.'),
    ]);
    const { md } = SY.buildSynthesis(g, { nowYear: 2026 });
    const s = md.join('\n');
    assert.ok(/年份缺失：2 条\*\* · \[#4\]、\[#5\]/.test(s), '缺失年份行号不对：' + s.match(/年份缺失[^\n]*/));
    assert.ok(s.includes('缺失不等于「旧」'), '缺口径说明');
    assert.ok(/近 5 年（2021–2026）：1 条 · \[#1\]/.test(s), '近 5 年分桶不对');
  });

  t('D 档成因分组挂行号（成因句也必须能点开核对）', () => {
    const g = mkGraded([
      evRec('A', 'target_species', 2024),
      evRec('D', 'unclear', 2020, { evidence: { evidenceGrade: 'D', gradeBasis: 'design_unrecognized', designLevel: { value: 'U', label: '未识别', confidence: 'low', candidates: [] }, speciesRelevance: { relevance: 'unclear', label: 'unclear', confidence: 'none', targetSpecies: [] }, sampleSize: { value: null, confidence: 'none', candidates: [] }, dose: { candidates: [] }, flags: [], needsReview: true, inputs: { abstractSource: 'epmc_full' } } }),
      evRec('D', 'target_species', 2015, { evidence: { evidenceGrade: 'D', gradeBasis: 'design_identified', designLevel: { value: 'L5', label: '薄弱', confidence: 'low', candidates: [] }, speciesRelevance: { relevance: 'target_species', label: 'target_species', confidence: 'medium', targetSpecies: [] }, sampleSize: { value: 8, confidence: 'low', candidates: [] }, dose: { candidates: [] }, flags: [], needsReview: true, inputs: { abstractSource: 'epmc_full' } } }),
    ]);
    const { md } = SY.buildSynthesis(g, { nowYear: 2026 });
    const s = md.join('\n');
    assert.ok(/D 档「设计未识别（信息不足）」：1 条 · \[#2\]/.test(s), '成因未分组挂行号');
    assert.ok(/D 档「已判定但薄弱」：1 条 · \[#3\]/.test(s), '第二种成因未挂行号');
  });

  t('计数漂移必须抛错（行号口径变了就不许生成会指错行的归纳）', () => {
    const g = G6();
    g.push({ g: { keyword: 'k', records: [] }, r: { idx: 9, titleEn: 'no evidence' } });
    assert.throws(() => SY.buildSynthesis(g, { nowYear: 2026 }), /不一致|只认到/, '未分级记录混入时未报错');
  });

  t('空输入返回空章节（不生成一个只有标题的空壳）', () => {
    const r = SY.buildSynthesis([], {});
    assert.deepStrictEqual(r.md, []);
    assert.strictEqual(r.stats.total, 0);
    assert.deepStrictEqual(SY.buildSynthesis(null).md, []);
  });

  t('不做有效性判断：正文里不得出现「有效 / 无效 / 证明 / 表明」这类结论动词', () => {
    const { md } = SY.buildSynthesis(G6(), { nowYear: 2026 });
    const s = md.join('\n');
    for (const bad of ['有显著效果', '证明该原料', '表明可改善', '可以宣称']) {
      assert.strictEqual(s.includes(bad), false, '越界写了效果判断：' + bad);
    }
    assert.ok(s.includes('不做「某原料有效/无效」这类判断'), '缺免责声明');
  });

  t('确定性：同输入两次生成逐字节一致（nowYear 必须可注入）', () => {
    const a = SY.buildSynthesis(G6(), { nowYear: 2026 }).md.join('\n');
    const b = SY.buildSynthesis(G6(), { nowYear: 2026 }).md.join('\n');
    assert.strictEqual(a, b);
    // 不同基准年会改变分桶，说明它确实用了注入值而不是 new Date()
    const c = SY.buildSynthesis(G6(), { nowYear: 2016 }).md.join('\n');
    assert.notStrictEqual(a, c, 'nowYear 未生效，仍依赖当前时间');
  });

  t('接入：报告含综合归纳，且排在证据分布图与表格之前', () => {
    const d = mkDir('as-synth');
    putRaw(d, '01-k.json', { runId: 'R1', keyword: 'k', records: [
      evRec('A', 'target_species', 2024), evRec('B', 'target_species', 2023), evRec('D', 'unclear', null),
    ] });
    fs.writeFileSync(path.join(d, 'summary.json'), JSON.stringify({ runId: 'R1', startedAt: '2026-10-21T00:00:00Z', keywords: { k: { count: 3 } } }), 'utf8');
    const out = AR.assemble({ dir: d, format: 'md' });
    const md = fs.readFileSync(out.md, 'utf8');
    assert.ok(md.includes('## 综合归纳'), '报告缺综合归纳节');
    assert.ok(md.indexOf('## 综合归纳') < md.indexOf('## 证据分布图'), '归纳应在图之前');
    assert.ok(md.indexOf('## 综合归纳') < md.indexOf('## 证据分级候选一览'), '归纳应在表之前');
    assert.deepStrictEqual(out.synthesisErrors, []);
    assert.strictEqual(out.synthesisStat.total, 3);
    assert.strictEqual(out.synthesisStat.nowYear, 2026, 'nowYear 未取自 summary.startedAt');
    // 行号能对上表格：归纳里的 [#1] 必须指向 A 档那行
    const tableFirst = /\| 1 \| \*\*A\*\*/.test(md);
    assert.ok(tableFirst, '表格首行不是 A 档，行号会对不上');
  });

  t('接入：--no-synthesis 关闭时无该节（保持旧产物形状）', () => {
    const d = mkDir('as-synth-off');
    putRaw(d, '01-k.json', { runId: 'R1', keyword: 'k', records: [evRec('A', 'target_species', 2024)] });
    fs.writeFileSync(path.join(d, 'summary.json'), JSON.stringify({ runId: 'R1', keywords: { k: { count: 1 } } }), 'utf8');
    const out = AR.assemble({ dir: d, format: 'md', synthesis: false });
    const md = fs.readFileSync(out.md, 'utf8');
    assert.strictEqual(md.includes('## 综合归纳'), false);
    assert.strictEqual(out.synthesisStat, null);
    assert.strictEqual(AR.parseArgs(['node', 'x', '--dir', d, '--no-synthesis']).synthesis, false);
    assert.strictEqual(AR.parseArgs(['node', 'x', '--dir', d]).synthesis, true);
  });

  t('接入：归纳失败不拖垮报告，且在正文里明写原因', () => {
    const d = mkDir('as-synth-bad');
    putRaw(d, '01-k.json', { runId: 'R1', keyword: 'k', records: [
      evRec('A', 'target_species', 2024), evRec('Z', 'target_species', 2023),
    ] });
    fs.writeFileSync(path.join(d, 'summary.json'), JSON.stringify({ runId: 'R1', keywords: { k: { count: 2 } } }), 'utf8');
    const out = AR.assemble({ dir: d, format: 'md' });
    const md = fs.readFileSync(out.md, 'utf8');
    assert.ok(md.includes('证据分级候选一览'), '表格也应完整');
    assert.ok(md.includes('综合归纳未生成'), '未在正文里报错');
    assert.ok(out.synthesisErrors.length >= 1);
  });

  t('排序守卫：n.d. 不得把 2019 挤到 1998 之后（比较器返回 NaN 会静默失效）', () => {
    const d = mkDir('as-sort-year');
    putRaw(d, '01-k.json', { runId: 'R1', keyword: 'k', records: [
      evRec('D', 'unclear', 1998), evRec('D', 'unclear', 'n.d.'), evRec('D', 'unclear', 2019), evRec('D', 'unclear', null),
    ] });
    fs.writeFileSync(path.join(d, 'summary.json'), JSON.stringify({ runId: 'R1', keywords: { k: { count: 4 } } }), 'utf8');
    const md = fs.readFileSync(AR.assemble({ dir: d, format: 'md' }).md, 'utf8');
    const years = [...md.matchAll(/\| \d+ \| \*\*D\*\* \|[^|]*\|[^|]*\|[^|]*\| ([^|]*) \|/g)].map(m => m[1].trim());
    assert.deepStrictEqual(years, ['2019', '1998', '—', 'n.d.'], 'D 档年份排序不对（应为 2019 → 1998 → 缺失沉底）：' + years.join(','));
  });

  t('源码守卫：synthesis.cjs 顶层零 IO / 零网络 / 不改等级', () => {
    const src = fs.readFileSync(path.join(__dirname, 'lib', 'synthesis.cjs'), 'utf8');
    assert.ok(!/^const\s+fs\s*=\s*require/m.test(src), '顶层 require fs');
    assert.ok(!/^const\s+path\s*=\s*require/m.test(src), '顶层 require path');
    assert.ok(!/fetch\(/.test(src), '出现 fetch');
    assert.ok(!/evidenceLevel\s*[:=]/.test(src), '写了 evidenceLevel');
    assert.ok(!/evidenceGrade\s*=\s*['"]/.test(src), '给 evidenceGrade 赋值了 —— 归纳无权改等级');
    const urls = (src.match(/https?:\/\/[^\s"'<)]*/g) || []).filter(u => !/w3\.org/.test(u));
    assert.strictEqual(urls.length, 0, '出现外部网络引用：' + urls.join('、'));
  });

  // ─────────────── v4.12：元典站点包（pack-site.cjs）───────────────
  // 判据主线：① 自包含（图在包内）；② 幂等（不含 now()）；③ sha256 能挡住任何改动；
  //           ④ 状态写进 frontmatter（站点全文检索会索引它）；⑤ 不猜站点路径（只给挂载片段）。
  const PS = require('./pack-site.cjs');

  console.log('pack-site（元典站点包）:');

  /** 造一个含 report.md 的目录（走真实 assemble，保证包里的内容与真实产物一致） */
  const mkReport = (name, records, summaryExtra) => {
    const d = mkDir(name);
    putRaw(d, '01-k.json', { runId: 'R1', keyword: 'k', records });
    fs.writeFileSync(path.join(d, 'summary.json'), JSON.stringify(Object.assign(
      { runId: 'R1', startedAt: '2026-10-21T02:00:00Z', site: 'kuluer', keywords: { k: { count: records.length } } },
      summaryExtra || {})), 'utf8');
    AR.assemble({ dir: d, format: 'md' });
    return d;
  };

  t('打包：index/README/moc-entry/manifest + 三张图，全部在包内', () => {
    const d = mkReport('pk-basic', [evRec('A', 'target_species', 2024), evRec('D', 'unclear', null)]);
    const out = path.join(TMP, 'pk-basic-out');
    const pk = PS.buildPack({ dir: d, out: out });
    const m = PS.writePack(pk, false);
    const got = m.files.map((f) => f.path).sort();
    assert.deepStrictEqual(got, ['README.md', 'charts/evidence-grade-dist.svg', 'charts/evidence-grade-species.svg',
      'charts/evidence-year-grade.svg', 'index.md', 'moc-entry.md']);
    assert.ok(fs.existsSync(path.join(out, 'manifest.json')), 'manifest 未落盘');
    // 自包含：index 引用的图必须都能在包内找到
    for (const mm of fs.readFileSync(path.join(out, 'index.md'), 'utf8').matchAll(/\]\((charts\/[^)]+)\)/g)) {
      assert.ok(fs.existsSync(path.join(out, mm[1])), '图引用指向包外：' + mm[1]);
    }
  });

  t('frontmatter：必填键齐全，且与正文之间有空行', () => {
    const d = mkReport('pk-fm', [evRec('A', 'target_species', 2024)]);
    const out = path.join(TMP, 'pk-fm-out');
    PS.writePack(PS.buildPack({ dir: d, out: out }), false);
    const txt = fs.readFileSync(path.join(out, 'index.md'), 'utf8');
    assert.ok(txt.startsWith('---\n'), 'index.md 未以 frontmatter 开头');
    const end = txt.indexOf('\n---\n', 4);
    assert.ok(end > 0, 'frontmatter 未闭合');
    const fm = txt.slice(4, end);
    for (const k of ['title', 'slug', 'tags', 'status', 'source', 'run_id', 'started_at']) {
      assert.ok(new RegExp('^' + k + ': ', 'm').test(fm), 'frontmatter 缺 ' + k);
    }
    assert.ok(txt.slice(end).startsWith('\n---\n\n'), 'frontmatter 后缺空行');
    // ★ 状态必须进 frontmatter：站点全文检索索引到的是这一段
    assert.ok(/^status: "候选未确认"$/m.test(fm), '状态未写进 frontmatter');
  });

  t('幂等：同一输入两次打包逐字节一致（不得含 now()）', () => {
    const d = mkReport('pk-idem', [evRec('B', 'target_species', 2023)]);
    const o1 = path.join(TMP, 'pk-idem-a');
    const o2 = path.join(TMP, 'pk-idem-b');
    const m1 = PS.writePack(PS.buildPack({ dir: d, out: o1 }), false);
    const m2 = PS.writePack(PS.buildPack({ dir: d, out: o2 }), false);
    assert.deepStrictEqual(m1.files.map((f) => f.sha256), m2.files.map((f) => f.sha256), '两次打包指纹不同');
    assert.strictEqual(fs.readFileSync(path.join(o1, 'manifest.json'), 'utf8'),
      fs.readFileSync(path.join(o2, 'manifest.json'), 'utf8'), 'manifest 含时间戳等易变字段');
  });

  t('verify：刚打好的包必须通过', () => {
    const d = mkReport('pk-ok', [evRec('A', 'target_species', 2024)]);
    const out = path.join(TMP, 'pk-ok-out');
    PS.writePack(PS.buildPack({ dir: d, out: out }), false);
    const r = PS.verify(out);
    assert.deepStrictEqual(r.errors, []);
    assert.strictEqual(r.ok, true);
  });

  t('verify：正文被改一个字符即失败（sha256 是唯一防线）', () => {
    const d = mkReport('pk-tamper', [evRec('A', 'target_species', 2024)]);
    const out = path.join(TMP, 'pk-tamper-out');
    PS.writePack(PS.buildPack({ dir: d, out: out }), false);
    const p = path.join(out, 'index.md');
    fs.writeFileSync(p, fs.readFileSync(p, 'utf8').replace('候选', '已确认'), 'utf8');
    const r = PS.verify(out);
    assert.strictEqual(r.ok, false);
    assert.ok(r.errors.some((e) => e.includes('sha256')), '未报 sha256 不符：' + r.errors.join('|'));
  });

  t('verify：清单外多出的文件也要报（混进历不明的文件比缺文件更危险）', () => {
    const d = mkReport('pk-extra', [evRec('A', 'target_species', 2024)]);
    const out = path.join(TMP, 'pk-extra-out');
    PS.writePack(PS.buildPack({ dir: d, out: out }), false);
    fs.writeFileSync(path.join(out, 'charts', 'leak.svg'), '<svg/>', 'utf8');
    const r = PS.verify(out);
    assert.strictEqual(r.ok, false);
    assert.ok(r.errors.some((e) => e.includes('清单外多出文件')), '未报清单外文件');
  });

  t('verify：缺 manifest / packVersion 不符都要明确报错', () => {
    const empty = path.join(TMP, 'pk-nomanifest');
    fs.mkdirSync(empty, { recursive: true });
    assert.strictEqual(PS.verify(empty).ok, false);
    assert.ok(PS.verify(empty).errors[0].includes('manifest.json'));

    const d = mkReport('pk-ver', [evRec('A', 'target_species', 2024)]);
    const out = path.join(TMP, 'pk-ver-out');
    PS.writePack(PS.buildPack({ dir: d, out: out }), false);
    const mp = path.join(out, 'manifest.json');
    const m = JSON.parse(fs.readFileSync(mp, 'utf8'));
    m.packVersion = 'site-pack/v0';
    fs.writeFileSync(mp, JSON.stringify(m, null, 2), 'utf8');
    const r = PS.verify(out);
    assert.strictEqual(r.ok, false);
    assert.ok(r.errors[0].includes('packVersion'), '未报版本不符');
  });

  t('参数守卫：--out 不得等于 --dir；缺 --dir/--out 直接报错', () => {
    assert.throws(() => PS.parseArgs(['node', 'x', '--dir', 'a', '--out', 'a']), /不能等于/);
    assert.throws(() => PS.parseArgs(['node', 'x', '--dir', 'a']), /--out/);
    assert.throws(() => PS.parseArgs(['node', 'x', '--out', 'b']), /--dir/);
    assert.throws(() => PS.parseArgs(['node', 'x', '--wat']), /未知参数/);
  });

  t('缺 report.md 时明确要求先跑 assemble-report（不空打包）', () => {
    const d = mkDir('pk-noreport');
    assert.throws(() => PS.buildPack({ dir: d, out: path.join(TMP, 'pk-noreport-out') }),
      /缺少.*report\.md|先跑/);
  });

  t('无图产物也能打包（--no-charts 的场景），charts 计数为 0', () => {
    const d = mkDir('pk-nocharts');
    putRaw(d, '01-k.json', { runId: 'R1', keyword: 'k', records: [evRec('A', 'target_species', 2024)] });
    fs.writeFileSync(path.join(d, 'summary.json'), JSON.stringify({ runId: 'R1', keywords: { k: { count: 1 } } }), 'utf8');
    AR.assemble({ dir: d, format: 'md', charts: false });
    const out = path.join(TMP, 'pk-nocharts-out');
    const m = PS.writePack(PS.buildPack({ dir: d, out: out }), false);
    assert.strictEqual(m.stats.charts, 0);
    assert.strictEqual(m.files.some((f) => f.path.startsWith('charts/')), false);
    assert.strictEqual(PS.verify(out).ok, true);
  });

  t('slug：由日期 + 目录名派生，不含随机与时间戳秒', () => {
    const s1 = PS.makeSlug('/x/out-2026-10-21', '2026-10-21T02:00:00Z');
    const s2 = PS.makeSlug('/x/out-2026-10-21', '2026-10-21T23:59:59Z');
    assert.strictEqual(s1, s2, 'slug 不应该随一天内的时间变化');
    assert.ok(/^paper-search-\d{8}/.test(s1), 'slug 未带日期：' + s1);
    assert.ok(!/[\s:]/.test(s1), 'slug 含空白或冒号');
    assert.strictEqual(PS.makeSlug('/x/y', null), 'paper-search-nodate-y', '无 startedAt 时应写 nodate 而不是编一个');
  });

  t('yamlStr：标题含引号/反斜杠/冒号时仍可解析（不裸拼 YAML）', () => {
    assert.strictEqual(PS.yamlStr('a"b'), '"a\\"b"');
    assert.strictEqual(PS.yamlStr('a\\b'), '"a\\\\b"');
    assert.strictEqual(PS.yamlStr('标题: 含冒号'), '"标题: 含冒号"');
    const d = mkReport('pk-yaml', [evRec('A', 'target_species', 2024)]);
    const out = path.join(TMP, 'pk-yaml-out');
    PS.writePack(PS.buildPack({ dir: d, out: out, title: '他说"这是结论"：并不可信' }), false);
    const fm = fs.readFileSync(path.join(out, 'index.md'), 'utf8').split('\n---\n')[0];
    assert.ok(/^title: "他说\\"这是结论\\"：并不可信"$/m.test(fm), '标题未正确转义：' + fm.match(/^title:.*/m));
  });

  t('状态两态：全候选 → candidate-unconfirmed；有已确认 → partly-confirmed', () => {
    const d1 = mkReport('pk-st1', [evRec('A', 'target_species', 2024)]);
    const m1 = PS.writePack(PS.buildPack({ dir: d1, out: path.join(TMP, 'pk-st1-out') }), false);
    assert.strictEqual(m1.status, 'candidate-unconfirmed');

    const r2 = evRec('A', 'target_species', 2024);
    r2.evidence.reviewed = true;
    const d2 = mkReport('pk-st2', [r2]);
    const m2 = PS.writePack(PS.buildPack({ dir: d2, out: path.join(TMP, 'pk-st2-out') }), false);
    assert.strictEqual(m2.status, 'partly-confirmed');
  });

  t('包内图与源图字节一致（复制而非重绘，避免两处样式漂移）', () => {
    const d = mkReport('pk-bytes', [evRec('A', 'target_species', 2024), evRec('C', 'in_vitro_only', 2020)]);
    const out = path.join(TMP, 'pk-bytes-out');
    PS.writePack(PS.buildPack({ dir: d, out: out }), false);
    const cr = require('crypto');
    const a = cr.createHash('sha256').update(fs.readFileSync(path.join(d, 'charts', 'evidence-grade-dist.svg'))).digest('hex');
    const b = cr.createHash('sha256').update(fs.readFileSync(path.join(out, 'charts', 'evidence-grade-dist.svg'))).digest('hex');
    assert.strictEqual(a, b, '包内图与源图不一致');
  });

  t('清单项（checklist）非空且能指导人工收尾', () => {
    const d = mkReport('pk-chk', [evRec('A', 'target_species', 2024)]);
    const out = path.join(TMP, 'pk-chk-out');
    const m = PS.writePack(PS.buildPack({ dir: d, out: out }), false);
    assert.ok(Array.isArray(m.checklist) && m.checklist.length >= 3, 'checklist 太薄');
    assert.ok(m.checklist.some((s) => s.includes('全文')), '清单未要求核对全文');
    assert.ok(m.checklist.some((s) => s.includes('重跑')), '清单未要求回写后重跑');
  });

  t('挂载片段：给 MOC 用的一行，指向 slug（不直接改 MOC）', () => {
    const d = mkReport('pk-moc', [evRec('A', 'target_species', 2024)]);
    const out = path.join(TMP, 'pk-moc-out');
    PS.writePack(PS.buildPack({ dir: d, out: out }), false);
    const moc = fs.readFileSync(path.join(out, 'moc-entry.md'), 'utf8');
    const slug = JSON.parse(fs.readFileSync(path.join(out, 'manifest.json'), 'utf8')).slug;
    assert.ok(moc.includes('[[' + slug + ']]'), '挂载片段未指向 slug');
    assert.ok(moc.trim().split('\n').length === 1, '挂载片段应只有一行，便于粘贴');
  });

  // ── 资料库 direct-edit 预检（v4.13 挂账）：同锚点多动作会倒序落位 ──
  // 实测 2026-10-21：61 条同锚 insert_after 落成「十八…十四」。正解 = 一条 action + content 空行串联。
  // 这条此前只在项目记忆里 —— 记忆不会让机器拒绝错误输入，所以把判据写成可执行函数。
  const DA = require('./lib/doc-actions.cjs');

  t('预检·负向：同锚点 2 条 insert_after 必须被拒，且点名锚点与条数', () => {
    const bad = [
      { type: 'insert_after', id: 'A1', content: '<Paragraph>十四</Paragraph>' },
      { type: 'insert_after', id: 'A1', content: '<Paragraph>十五</Paragraph>' },
    ];
    assert.throws(() => DA.assertNoAnchorCollision(bad), (e) =>
      e.message.includes('A1') && e.message.includes('2 次') && e.message.includes('倒序'));
  });

  t('预检·负向：3 条时报条数而非「有/无」，序号指向真实数组下标', () => {
    const bad = [
      { type: 'insert_after', id: 'X', content: '<Paragraph>a</Paragraph>' },
      { type: 'delete', id: 'D1' },
      { type: 'insert_after', id: 'X', content: '<Paragraph>b</Paragraph>' },
      { type: 'insert_after', id: 'X', content: '<Paragraph>c</Paragraph>' },
    ];
    const cols = DA.findAnchorCollisions(bad);
    assert.strictEqual(cols.length, 1);
    assert.strictEqual(cols[0].count, 3);
    assert.deepStrictEqual(cols[0].indexes, [0, 2, 3], '序号必须含 delete 造成的空档');
  });

  // 2026-10-24 临时页 dGLW5PdQigMjD3PHsKuyxf 实测：after×2 倒序、before×2 与 before×3 均严格正序。
  // 首版把 before 也纳入判据 ⇒ 误拒合法写法。误报比漏报更糟，故反转此用例。
  t('预检·正向：insert_before 同锚多条目必须放行（实测为正序，不得沿用 after 判据）', () => {
    const ok = [
      { type: 'insert_before', id: 'B9', content: '<Paragraph>a</Paragraph>' },
      { type: 'insert_before', id: 'B9', content: '<Paragraph>b</Paragraph>' },
      { type: 'insert_before', id: 'B9', content: '<Paragraph>c</Paragraph>' },
    ];
    assert.strictEqual(DA.findAnchorCollisions(ok).length, 0, 'before 多条为正序，误报会让调用方绕过预检');
    assert.strictEqual(DA.assertNoAnchorCollision(ok), true);
    assert.deepStrictEqual(DA.ORDER_REVERSING_TYPES, ['insert_after'], '只有 after 会倒序，判据边界须显式');
  });

  t('预检·负向：after×2 + before×2 同锚时只报 after，两个方向不得互相抵消', () => {
    const mixed = [
      { type: 'insert_before', id: 'C7', content: '<Paragraph>p</Paragraph>' },
      { type: 'insert_before', id: 'C7', content: '<Paragraph>q</Paragraph>' },
      { type: 'insert_after', id: 'C7', content: '<Paragraph>r</Paragraph>' },
      { type: 'insert_after', id: 'C7', content: '<Paragraph>s</Paragraph>' },
    ];
    const cols = DA.findAnchorCollisions(mixed);
    assert.strictEqual(cols.length, 1, '只应有 1 项（insert_after）');
    assert.strictEqual(cols[0].type, 'insert_after');
    assert.strictEqual(cols[0].count, 2);
    assert.deepStrictEqual(cols[0].indexes, [2, 3], '序号须指向真实数组下标，不能被 before 挤歪');
  });

  t('预检·正向：不同锚点各 1 条不得误报（真实 actions_readme.json 即 4 条零冲突）', () => {
    const ok = [
      { type: 'insert_after', id: 'A1', content: '<Paragraph>a</Paragraph>' },
      { type: 'insert_after', id: 'A2', content: '<Paragraph>b</Paragraph>' },
      { type: 'insert_after', id: 'A3', content: '<Paragraph>c</Paragraph>' },
      { type: 'insert_after', id: 'A4', content: '<Paragraph>d</Paragraph>' },
    ];
    assert.strictEqual(DA.findAnchorCollisions(ok).length, 0);
  });

  t('预检·正向：同 id 的 insert_after + insert_before + delete 三者并存不算冲突', () => {
    const ok = [
      { type: 'insert_after', id: 'B1', content: '<Paragraph>after</Paragraph>' },
      { type: 'insert_before', id: 'B1', content: '<Paragraph>before</Paragraph>' },
      { type: 'delete', id: 'B1' },
    ];
    assert.strictEqual(DA.findAnchorCollisions(ok).length, 0, '方向不同 / delete 语义不同，均不得判冲突');
  });

  t('预检·负向：未知 type 显式报错（新 type 不得静默逃过判据）', () => {
    assert.throws(() => DA.assertNoAnchorCollision([{ type: 'replace', id: 'A1', content: 'x' }]), /type 未知/);
  });

  t('预检·正向：planInsert 产出的单条 action 能过预检，且保序、块数守恒', () => {
    const blocks = ['<Paragraph>一</Paragraph>', '<Paragraph>二</Paragraph>', '<BulletedList>\n    <Mark bold>x</Mark>\n</BulletedList>'];
    const a = DA.planInsert('ANCHOR', blocks);
    assert.strictEqual(a.type, 'insert_after');
    assert.strictEqual(a.id, 'ANCHOR');
    DA.assertNoAnchorCollision([a]);
    assert.strictEqual(DA.countTopBlocks(a.content), 3, '块数不守恒');
    const pos = blocks.map((b) => a.content.indexOf(b));
    assert.ok(pos[0] >= 0 && pos[0] < pos[1] && pos[1] < pos[2], '块序被打乱：' + pos.join('/'));
  });

  t('预检·计数：单行块 / 跨行块 / 嵌套块与行内 Mark 均只算 1 块', () => {
    assert.strictEqual(DA.countTopBlocks('<Paragraph>一</Paragraph>'), 1, '单行块被数成 0');
    assert.strictEqual(DA.countTopBlocks('<Paragraph>\n文本\n</Paragraph>'), 1);
    assert.strictEqual(
      DA.countTopBlocks('<BlockQuote>\n<Paragraph>\n        <Mark bold>X</Mark>：说明\n</Paragraph>\n</BlockQuote>'), 1,
      '嵌套内的 Paragraph 不得单独计数');
    assert.strictEqual(DA.countTopBlocks('<Heading level="2">\n    标题\n</Heading>\n\n<Paragraph>正文</Paragraph>'), 2);
    // 连续单行块：若单行块被当成跨行块，深度会卡在 1 而不回落 ⇒ 3 块被数成 1 块
    assert.strictEqual(
      DA.countTopBlocks('<Paragraph>a</Paragraph>\n\n<Paragraph>b</Paragraph>\n\n<Paragraph>c</Paragraph>'), 3,
      '连续单行块必须各算 1 块（深度卡住会数成 1）');
  });

  t('预检·负向：planInsert 空锚点 / 空数组 / 空白块均须显式报错', () => {
    assert.throws(() => DA.planInsert('', ['<Paragraph>a</Paragraph>']), /锚点/);
    assert.throws(() => DA.planInsert('A1', []), /非空数组/);
    assert.throws(() => DA.planInsert('A1', ['   ']), /第 0 块为空/);
  });

  t('预检·源码守卫：lib/doc-actions.cjs 零 IO / 零网络', () => {
    const src = fs.readFileSync(path.join(__dirname, 'lib', 'doc-actions.cjs'), 'utf8');
    for (const bad of ["require('fs')", 'require("fs")', "require('http')", "require('https')",
      "require('child_process')", 'XMLHttpRequest', 'fetch(']) {
      assert.ok(!src.includes(bad), 'doc-actions.cjs 不得出现 ' + bad);
    }
  });

  t('预检·CLI：违规退出 1 且点名锚点、合规退出 0（CLI 与闸门判据同源）', () => {
    const { spawnSync } = require('child_process');
    const dir = path.join(TMP, 'doc-actions-cli');
    fs.mkdirSync(dir, { recursive: true });
    const badF = path.join(dir, 'bad.json');
    const okF = path.join(dir, 'ok.json');
    fs.writeFileSync(badF, JSON.stringify([
      { type: 'insert_after', id: 'A1', content: '<Paragraph>十四</Paragraph>' },
      { type: 'insert_after', id: 'A1', content: '<Paragraph>十五</Paragraph>' },
    ]), 'utf8');
    fs.writeFileSync(okF, JSON.stringify([
      DA.planInsert('A1', ['<Paragraph>十四</Paragraph>', '<Paragraph>十五</Paragraph>']),
    ]), 'utf8');
    const bad = spawnSync(process.execPath, [path.join(__dirname, 'doc-actions.cjs'), 'check', badF], { encoding: 'utf8' });
    assert.strictEqual(bad.status, 1, '违规文件应退出 1，实际 ' + bad.status);
    assert.ok(String(bad.stderr).includes('A1'), 'CLI 未点名违规锚点');
    const ok = spawnSync(process.execPath, [path.join(__dirname, 'doc-actions.cjs'), 'check', okF], { encoding: 'utf8' });
    assert.strictEqual(ok.status, 0, '合规文件应退出 0，实际 ' + ok.status);
  });

  // ── 输出层：--out 父目录不存在时必须自建（原为 ENOENT，长期挂在「暂不修」） ──
  t('输出层·回归：build-queries --out 父目录不存在时自建（--plan 默认同目录亦须落盘）', () => {
    const { spawnSync } = require('child_process');
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pbs-bq-out-'));
    const out = path.join(dir, 'deep', 'a', 'q.txt');   // deep/a 均不存在
    const r = spawnSync(process.execPath, [path.join(__dirname, 'build-queries.cjs'),
      '--compose', 'S3.2.1', '--species', 'cat', '--out', out], { encoding: 'utf8' });
    assert.strictEqual(r.status, 0,
      '父目录不存在时应自建，实际退出 ' + r.status + '：' + String(r.stderr).slice(0, 200));
    assert.ok(fs.existsSync(out), '未生成 ' + out);
    assert.ok(fs.readFileSync(out, 'utf8').trim().length > 0, '检索式文件为空');
    assert.ok(fs.existsSync(path.join(dir, 'deep', 'a', 'plan.json')), '--plan 未随 --out 落盘');
  });

  t('输出层·回归：rank-records --out 父目录不存在时自建（与状态文件目录是两件事）', () => {
    const { spawnSync } = require('child_process');
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pbs-rk-out-'));
    fs.mkdirSync(path.join(dir, 'raw'), { recursive: true });
    const titles = ['A 肠道菌群紊乱', 'B 肠道菌群紊乱', 'C 膀胱炎结石', 'D 膀胱炎结石'];
    fs.writeFileSync(path.join(dir, 'raw', '01-a.json'), JSON.stringify({
      runId: 'R1', keyword: 'k',
      records: titles.map((x, i) => ({ idx: i + 1, titleZh: x, year: 2020 })),
    }), 'utf8');
    const out = path.join(dir, 'deep', 'x', 'r');   // deep/x 不存在
    const r = spawnSync(process.execPath, [path.join(__dirname, 'rank-records.cjs'),
      '--dir', dir, '--topic', '肠道菌群', '--iterate', '2', '--iterate-pick', 'all',
      '--min-df', '2', '--format', 'md', '--out', out], { encoding: 'utf8' });
    assert.strictEqual(r.status, 0,
      '父目录不存在时应自建，实际退出 ' + r.status + '：' + String(r.stderr).slice(0, 200));
    assert.ok(fs.existsSync(out + '.md'), '未生成 ' + out + '.md');
  });

  // ---------- 多源层接线（v4.15 A 批）：用假 fetch 测连接器解析，用假连接器测调度器 ----------
  // 设计理由：连接器的价值全在「把各家方言映射成 canonical record」，这件事**不需要真联网**就能证伪；
  // 调度器的价值全在「单源失败时其它源不受影响」，这件事**必须**用可控假源测，靠真站点测不出来。
  console.log('多源连接器解析（假 fetch，离线）:');
  // 假 fetch：http.cjs 先 r.text() 再 JSON.parse，故必须提供 text()
  const fakeFetch = (payload, opt) => async () => {
    const o = opt || {};
    return {
      status: o.status || 200,
      ok: (o.status || 200) < 400,
      headers: { get: k => (String(k).toLowerCase() === 'retry-after' ? (o.retryAfter == null ? null : String(o.retryAfter)) : null) },
      text: async () => (typeof payload === 'string' ? payload : JSON.stringify(payload)),
    };
  };
  const epmcPayload = {
    hitCount: 2,
    nextCursorMark: undefined,
    resultList: { result: [
      { id: '31880029', source: 'MED', pmid: '31880029', pmcid: 'PMC7079073', doi: '10.1111/jpn.13289',
        title: 'The effects of diets varying in fibre sources on nutrient utilization in cats',
        authorString: 'Donadelli RA, Aldrich CG.', pubYear: '2020', journalTitle: 'J Anim Physiol Anim Nutr',
        abstractText: '<h4>Abstract</h4>Fibre sources were tested.', isOpenAccess: 'Y', hasPDF: 'Y', citedByCount: 12,
        pubTypeList: { pubType: ['Journal Article', 'research-article'] } },
      { id: '999', source: 'MED', title: '', pubYear: '2021' },   // 无标题 ⇒ 必须被丢弃
    ] },
  };

  await ta('europepmc 连接器：解析 core 字段、丢弃无标题记录、translateStatus=null', async () => {
    const r = await withFetch(fakeFetch(epmcPayload), () => EPMC_SRC.search({ query: '(cat OR feline) AND hairball', limit: 5, keyword: 'K' }));
    assert.strictEqual(r.records.length, 1, '无标题记录未被丢弃');
    const rec = r.records[0];
    assert.strictEqual(rec.doi, '10.1111/jpn.13289');
    assert.strictEqual(rec.pmcid, 'PMC7079073');
    assert.strictEqual(rec.year, 2020);
    assert.strictEqual(rec.oaStatus, true, 'isOpenAccess=Y 未映射为 true');
    assert.strictEqual(rec.citedBy, 12);
    assert.strictEqual(rec.translateStatus, null, 'HTTP 源不得带 translateStatus 非 null 值');
    assert.strictEqual(/<h4>/.test(rec.abstractEn), false, '摘要里的 HTML 标签未剥');
    assert.strictEqual(rec.provenance.sourceId, 'europepmc');
    assert.strictEqual(r.diagnostics.reportedTotal, 2, 'hitCount 未进 reportedTotal，PRISMA 会缺计数');
  });

  await ta('europepmc 连接器：hitCount=0 → noResultsSignal=true（真 0 是有效证据，不是采集失败）', async () => {
    const r = await withFetch(fakeFetch({ hitCount: 0, resultList: { result: [] } }), () => EPMC_SRC.search({ query: 'nohit', limit: 5, keyword: 'K' }));
    assert.strictEqual(r.records.length, 0);
    assert.strictEqual(r.diagnostics.noResultsSignal, true);
    assert.strictEqual(r.diagnostics.reportedTotal, 0);
    assert.strictEqual(PR.classifyCount(r.diagnostics).state, 'counted');
  });

  await ta('europepmc 连接器：HTTP 429 时 aborted 且 reportedTotal 保持 null（不冒充 0 命中）', async () => {
    const r = await withFetch(fakeFetch({ error: 'rate limited' }, { status: 429, retryAfter: 0.02 }),
      () => EPMC_SRC.search({ query: 'x', limit: 5, keyword: 'K', timeoutMs: 4000 }));
    assert.strictEqual(r.records.length, 0);
    assert.strictEqual(r.diagnostics.reportedTotal, null, '429 被写成了计数');
    assert.ok(/source_error:rate_limited/.test(r.diagnostics.aborted), '未标记为限流: ' + r.diagnostics.aborted);
    assert.strictEqual(PR.classifyCount(r.diagnostics).state, 'collect_failed');
  });

  await ta('crossref 连接器：布尔式被转译为词袋、reportedTotal 恒 null、JATS 摘要被剥', async () => {
    let seenUrl = null;
    const crPayload = { message: { 'total-results': 358659, items: [
      { DOI: '10.1017/jns.2014.27', title: ['Sugarcane fibre may prevents hairball formation in cats'],
        abstract: '<jats:p>Fibre <jats:italic>in vitro</jats:italic> fermentation.</jats:p>',
        author: [{ family: 'Loureiro', given: 'Bruna Agy' }], 'container-title': ['J Nutr Sci'],
        issued: { 'date-parts': [[2014]] }, type: 'journal-article', 'is-referenced-by-count': 30, score: 22.4 },
    ] } };
    const r = await withFetch(async url => { seenUrl = String(url); return fakeFetch(crPayload)(); },
      () => CR_SRC.search({ query: '(cat OR feline) AND hairball', limit: 5, keyword: 'K' }));
    assert.ok(/query\.bibliographic=cat\+feline\+hairball|query\.bibliographic=cat%20feline%20hairball/.test(seenUrl),
      '布尔运算符未从查询串中剥离: ' + seenUrl);
    assert.strictEqual(r.diagnostics.reportedTotal, null, '总命中数（全库软匹配规模）被写进了计数');
    assert.strictEqual(r.records.length, 1);
    const rec = r.records[0];
    assert.strictEqual(rec.doi, '10.1017/jns.2014.27');
    assert.strictEqual(rec.authors, 'Loureiro BA', '作者未按「姓 + 名首字母」拼接');
    assert.strictEqual(/<jats/i.test(rec.abstractEn), false, 'JATS 标签未剥: ' + rec.abstractEn);
    assert.strictEqual(rec.oaStatus, null, 'Crossref 不提供 OA 状态，必须为 null 而非 false');
    assert.strictEqual(rec.provenance.countSemantics, 'none');
  });

  console.log('多源调度（假连接器，离线）:');
  const fakeCaps = { abstract: true, doi: true, oa: true, translate: false };
  const mkFake = (id, extra) => Object.assign({
    id, label: '假源-' + id, kind: 'http', queryDialect: 'boolean', countSemantics: 'exact', capabilities: fakeCaps,
  }, extra);
  const fakes = {
    good: mkFake('good', { async search() { return { records: [{ titleEn: 'A real paper on cats', doi: '10.1/x', year: 2020, provenance: { sourceId: 'good' } }], diagnostics: { reportedTotal: 42, noResultsSignal: false, aborted: null } }; } }),
    boom: mkFake('boom', { async search() { throw new Error('kaboom'); } }),
    hang: mkFake('hang', { async search() { return new Promise(() => {}); } }),   // 永不返回（模拟连接器内部卡死）
    nocount: mkFake('nocount', { queryDialect: 'bag', countSemantics: 'none', async search() { return { records: [{ titleEn: 'Another paper', doi: '10.2/y', year: 2021, provenance: { sourceId: 'nocount' } }], diagnostics: { reportedTotal: null, noResultsSignal: false, aborted: null } }; } }),
  };
  const runFake = (ids, extra) => SCH.runSources(Object.assign({ sources: ids, resolve: id => fakes[id], query: 'x', limit: 5 }, extra || {}));

  await ta('runSources 失败隔离：一源抛异常只记 failure，其它源记录完整保留', async () => {
    const r = await runFake(['good', 'boom'], { perSourceTimeoutMs: 5000 });
    assert.strictEqual(r.records.length, 1, '正常源的记录被异常源带走了');
    assert.strictEqual(r.failures.length, 1);
    assert.strictEqual(r.failures[0].id, 'boom');
    assert.strictEqual(r.failures[0].reason.startsWith('threw:'), true);
    assert.strictEqual(r.siteDegraded, false, '有一源存活就不该判站点不可用');
  });

  await ta('★ runSources 超时判定尊重 perSourceTimeoutMs（不得静默抬高，否则超时永远不触发）', async () => {
    const t0 = Date.now();
    const r = await runFake(['good', 'hang'], { perSourceTimeoutMs: 300 });
    const ms = Date.now() - t0;
    assert.ok(ms < 2000, 'perSourceTimeoutMs=300 却耗时 ' + ms + 'ms ⇒ 超时被静默抬高');
    const hang = r.perSource.find(s => s.id === 'hang');
    assert.strictEqual(hang.ok, false, '卡死源被判成可用');
    assert.ok(/scheduler_timeout/.test(hang.aborted), '未标记为调度器超时: ' + hang.aborted);
    assert.strictEqual(r.records.length, 1, '正常源记录受影响');
  });

  await ta('runSources countSemantics=none → not_applicable，且不进 anyEvidence（否则制造假故障）', async () => {
    const r = await runFake(['nocount'], { perSourceTimeoutMs: 2000 });
    const s = r.perSource[0];
    assert.strictEqual(s.countState, SCH.COUNT_NA);
    assert.strictEqual(s.countState === 'collect_failed', false, '无计数源被误判为采集失败');
    assert.strictEqual(s.reportedTotal, null);
    assert.strictEqual(r.anyEvidence, false, '无计数源不该被算作「给出了读数证据」');
    assert.strictEqual(s.ok, true);
  });

  await ta('runSources 全源皆挂 → siteDegraded=true 且 anyEvidence=false', async () => {
    const r = await runFake(['boom', 'hang'], { perSourceTimeoutMs: 300 });
    assert.strictEqual(r.allFailed, true);
    assert.strictEqual(r.siteDegraded, true);
    assert.strictEqual(r.anyEvidence, false);
    assert.strictEqual(r.records.length, 0);
  });

  await ta('runSources 跨源同篇被合并，且 provenance 记录双源见证', async () => {
    const dup = {
      a: mkFake('a', { async search() { return { records: [NRM.canonicalRecord({ titleEn: 'Same title on dogs', doi: '10.9/dup', year: 2020 }, { sourceId: 'a' })], diagnostics: { reportedTotal: 1, aborted: null } }; } }),
      b: mkFake('b', { async search() { return { records: [NRM.canonicalRecord({ titleEn: 'Same title on dogs', doi: '10.9/dup', year: 2020, pmid: '777' }, { sourceId: 'b' })], diagnostics: { reportedTotal: 1, aborted: null } }; } }),
    };
    const r = await SCH.runSources({ sources: ['a', 'b'], resolve: id => dup[id], query: 'x', limit: 5, perSourceTimeoutMs: 2000 });
    assert.strictEqual(r.records.length, 1, '跨源同篇未被合并');
    assert.strictEqual(r.dedupe.before, 2);
    assert.strictEqual(r.dedupe.mergedCrossSource, 1);
    assert.strictEqual(r.records[0].pmid, '777', '合并未补上新源字段');
    assert.deepStrictEqual(r.records[0].provenance.alsoFoundIn, ['b']);
  });

  // ---------- v4.15（C 批）：零依赖 PDF 文本抽取 ----------
  const PX = require('./lib/pdf-extract.cjs');
  const ZLIB = require('zlib');

  // 造「能被暴力流扫描捞到」的最小 PDF：测试关心抽取正确性，不关心规范完整性
  const mkPdf = (contents, opt) => {
    const o = opt || {};
    const bufs = [Buffer.from('%PDF-1.4\n', 'latin1')];
    contents.forEach((c, i) => {
      const z = ZLIB.deflateSync(Buffer.from(c, 'latin1'));
      bufs.push(Buffer.from((i + 1) + ' 0 obj\n<< /Length ' + z.length + ' /Filter /FlateDecode >>\nstream\n', 'latin1'));
      bufs.push(z);
      bufs.push(Buffer.from('\nendstream\nendobj\n', 'latin1'));
    });
    if (o.encrypt) bufs.push(Buffer.from('trailer\n<< /Encrypt 9 0 R >>\n%%EOF\n', 'latin1'));
    return Buffer.concat(bufs);
  };
  const oneLine = 'This study evaluated sugarcane fibre in cats with hairball formation. ';

  t('pdf: isPdf 认 %PDF- 魔数，非 PDF 一律 false', () => {
    assert.strictEqual(PX.isPdf(Buffer.from('%PDF-1.4\n...', 'latin1')), true);
    assert.strictEqual(PX.isPdf(Buffer.from('\n\n\n<html><body>Preparing to download', 'latin1')), false);
    assert.strictEqual(PX.isPdf(Buffer.alloc(0)), false);
  });

  t('pdf: 声明 /Encrypt 直接判 pdf_encrypted（不抽乱码）', () => {
    const buf = mkPdf(['BT 12 Tf 72 700 Td (' + oneLine + ') Tj ET'], { encrypt: true });
    assert.strictEqual(PX.isEncrypted(buf), true);
    const r = PX.extractPdfText(buf);
    assert.strictEqual(r.ok, false);
    assert.strictEqual(r.reason, 'pdf_encrypted');
  });

  t('pdf: 从 Flate 内容流抽回正文（字面串 Tj）', () => {
    const buf = mkPdf(['BT /F1 12 Tf 72 700 Td (' + oneLine.repeat(6) + ') Tj ET']);
    const r = PX.extractPdfText(buf, { minWords: 1 });  // 这里测抽取，不测词数下限
    assert.strictEqual(r.ok, true, '未抽到正文：' + r.reason);
    assert.ok(r.text.indexOf('sugarcane fibre in cats') >= 0, '正文关键词缺失');
    assert.ok(r.stats.inflated >= 1 && r.stats.contentStreams === 1, '流统计异常');
  });

  t('pdf: Td 垂直位移产生换行（不靠标点猜段落）', () => {
    const buf = mkPdf(['BT 72 700 Td 12 Tf (First line of the body text) Tj 0 -14 Td (Second line of the body text) Tj ET']);
    const r = PX.extractPdfText(buf, { minWords: 1 });
    assert.strictEqual(r.ok, true, r.reason);
    const lines = r.text.split('\n');
    assert.strictEqual(lines.length, 2, '应切成 2 行，实际 ' + lines.length);
    assert.ok(/^First line/.test(lines[0]) && /^Second line/.test(lines[1]));
  });

  t('pdf: TJ 负数间距 = 词间空格，正数 = 字间调距（不插空格）', () => {
    const buf = mkPdf(['BT 1 0 0 1 72 700 Tm 12 Tf [(Waltham)40.5(Supplement)]TJ [(fibre)-335.3(may)]TJ ET']);
    const r = PX.extractPdfText(buf, { minWords: 1 });
    assert.strictEqual(r.ok, true, r.reason);
    assert.ok(r.text.indexOf('WalthamSupplement') >= 0, '正数调距被误加空格：' + JSON.stringify(r.text));
    assert.ok(r.text.indexOf('fibre may') >= 0, '负数间距未还原成空格：' + JSON.stringify(r.text));
  });

  t('pdf: Td 水平大跳还原词间空格（PMC 的 OCR 文字层不写空格字符）', () => {
    // 取证自 B2（1960 Can Vet J 扫描件）：0.00 0 Td、33.36 0 Td、88.44 0 Td
    const buf = mkPdf(['BT 12 Tf 178 617 Td (TRICHOBEZOAR) Tj 88.44 0 Td (OR) Tj 33.36 0 Td (HAIR) Tj 88.44 0 Td (BALL) Tj ET']);
    const r = PX.extractPdfText(buf, { minWords: 1 });
    assert.strictEqual(r.ok, true, r.reason);
    assert.ok(r.text.indexOf('TRICHOBEZOAR OR HAIR BALL') >= 0, '词被粘住：' + JSON.stringify(r.text));
  });

  t('pdf: Td 水平小跳不插空格（否则逐字定位的 PDF 会被拆成单个字母）', () => {
    // 5 单位 < 0.6 em(7.2) ⇒ 是字符推进，不是词间空格
    const buf = mkPdf(['BT 12 Tf 72 700 Td (fibr) Tj 5 0 Td (e) Tj 5 0 Td (r) Tj ET']);
    const r = PX.extractPdfText(buf, { minWords: 1 });
    assert.ok(r.text.indexOf('fibre') >= 0, '字符被误拆：' + JSON.stringify(r.text));
  });

  t('pdf: 十六进制串主导 ⇒ pdf_cid_encoding_unsupported（不产乱码）', () => {
    const inner = Array.from({ length: 120 }, () => '<48656c6c6f576f726c64> Tj').join(' ');
    const buf = mkPdf(['BT 12 Tf 72 700 Tm ' + inner + ' ET']);
    const r = PX.extractPdfText(buf);
    assert.strictEqual(r.ok, false);
    assert.strictEqual(r.reason, 'pdf_cid_encoding_unsupported');
    assert.ok(r.stats.hexRatio > 0.3, 'hexRatio 统计不对: ' + r.stats.hexRatio);
  });

  t('pdf: 控制字符占比高 ⇒ pdf_garbled（编码没对上就别装）', () => {
    const inner = Array.from({ length: 200 }, () => '<00> Tj').join(' ');
    const buf = mkPdf(['BT 12 Tf 72 700 Tm ' + inner + ' ET']);
    const r = PX.extractPdfText(buf);
    assert.strictEqual(r.ok, false);
    assert.ok(/^pdf_garbled_/.test(r.reason), '实际：' + r.reason);
  });

  t('pdf: 无文字层（纯扫描件）⇒ pdf_no_text_layer', () => {
    const buf = mkPdf(['q 612 0 0 792 0 0 cm /Im1 Do Q']);
    const r = PX.extractPdfText(buf);
    assert.strictEqual(r.ok, false);
    assert.strictEqual(r.reason, 'pdf_no_text_layer');
  });

  t('pdf: 词数不足 ⇒ pdf_too_few_words_N（带实际词数）', () => {
    const buf = mkPdf(['BT 12 Tf 72 700 Td (short text) Tj ET']);
    const r = PX.extractPdfText(buf);
    assert.strictEqual(r.ok, false);
    assert.ok(/^pdf_too_few_words_\d+$/.test(r.reason), '实际：' + r.reason);
  });

  t('pdf: 空格比过低 ⇒ pdf_word_spacing_lost（粘成一串的文字不可用）', () => {
    const glued = Array.from({ length: 60 }, () => '(abcdefghij) Tj').join(' ');
    const buf = mkPdf(['BT 12 Tf 72 700 Tm ' + glued + ' ET']);
    const r = PX.extractPdfText(buf);
    assert.strictEqual(r.ok, false);
    assert.strictEqual(r.reason, 'pdf_word_spacing_lost');
  });

  t('pdf: 非 PDF 输入（挑战页 HTML）⇒ not_pdf', () => {
    const r = PX.extractPdfText(Buffer.from('<html><body>Preparing to download ...</body></html>', 'latin1'));
    assert.strictEqual(r.ok, false);
    assert.strictEqual(r.reason, 'not_pdf');
  });

  t('★ assessText: PMC 样板页（标题在页内、正文 0 词）必须判 page_is_chrome', () => {
    // 取证自真实产物 PMC1585353.txt：207 词、散文行占比 0.04、正文 0 词
    const navBits = ['Skip to main content', 'Official websites use .gov', 'Journal List',
      'User Guide', 'PERMALINK', 'Copy', 'Search in PMC', 'PMC Disclaimer',
      'Learn more:', 'Follow NLM', 'PMC Copyright Notice'];
    const chrome = ['Trichobezoar or Hair Ball in a Cat - PMC'];
    for (let i = 0; i < 60; i += 1) chrome.push(navBits[i % navBits.length]);
    const chromeTxt = chrome.join('\n');
    const g = FTC.assessText(chromeTxt, { titleEn: 'Trichobezoar or Hair Ball in a Cat' }, { chromeCheck: true });
    assert.ok(g.words >= 120, '夹具太小，测不到样板判据：' + g.words);
    assert.strictEqual(g.ok, false, '样板页被判成全文了');
    assert.ok(/^page_is_chrome_/.test(g.reason), '实际原因：' + g.reason);
    // 关掉样板检查时同一段文字会通过 ⇒ 证明这条闸门是本批新增的那道，不是原有逻辑
    const g2 = FTC.assessText(chromeTxt, { titleEn: 'Trichobezoar or Hair Ball in a Cat' }, {});
    assert.strictEqual(g2.ok, true, '对照组应当通过（旧逻辑确实漏了这类页面）');
  });

  t('★ assessText: 真正文不被样板判据误伤（散文行多即放行）', () => {
    const body = [
      'Abstract',
      'Case summary ' + oneLine.repeat(3),
      'Clinical significance ' + oneLine.repeat(3),
      'Introduction ' + oneLine.repeat(4),
      'Discussion ' + oneLine.repeat(4),
    ].join('\n');
    const g = FTC.assessText(body, { titleEn: 'Sugarcane fibre may prevents hairball formation in cats' },
      { chromeCheck: true });
    assert.strictEqual(g.ok, true, '真正文被误判：' + g.reason);
    assert.ok(g.words >= 120, '词数不足: ' + g.words);
  });

  t('planTiers: 有 PMCID 时最后一跳是 PMC PDF 兜底（browser）', () => {
    const plan = FTC.planTiers({ enrich: { pmcid: 'PMC1585353' } });
    const tiers = plan.map(s => s.tier);
    assert.deepStrictEqual(tiers, [
      FTC.TIER.EPMC_XML, FTC.TIER.PMC_HTML, FTC.TIER.PMC_HTML, FTC.TIER.PMC_PDF,
    ], '计划顺序变了：' + tiers.join(' > '));
    assert.strictEqual(plan[3].transport, 'browser', 'PDF 路由带 PoW，必须走浏览器');
    assert.strictEqual(plan[3].url, 'https://pmc.ncbi.nlm.nih.gov/articles/PMC1585353/pdf/');
  });

  t('planTiers: 只有 DOI 的记录不产生 PMC PDF 级（无 PMCID 就没有这条路由）', () => {
    const plan = FTC.planTiers({ doi: '10.1111/jpn.12745' });
    assert.strictEqual(plan.some(s => s.tier === FTC.TIER.PMC_PDF), false);
    assert.deepStrictEqual(plan.map(s => s.tier), [FTC.TIER.UNPAYWALL, FTC.TIER.PUBLISHER]);
  });

  t('TIER 级标识不得改名（历史产物与报告按此比对）', () => {
    assert.strictEqual(FTC.TIER.PMC_PDF, 'T2b_pmc_pdf');
    assert.strictEqual(FTC.TIER.OA_PDF, 'T3b_unpaywall_pdf');
    assert.strictEqual(FTC.TIER.EPMC_XML, 'T1_epmc_xml');
    assert.strictEqual(FTC.TIER.PMC_HTML, 'T2_pmc_html');
  });

  t('报告层：每个 TIER 都必须有中文展示名（新层级不得裸键落到报告里）', () => {
    const src = fs.readFileSync(path.join(__dirname, 'assemble-report.cjs'), 'utf8');
    const missing = Object.keys(FTC.TIER).filter(k => src.indexOf(FTC.TIER[k] + ':') < 0);
    assert.deepStrictEqual(missing, [], '以下层级在报告层没有展示名：' + missing.join(', '));
  });

console.log('F 批：多源通道 × 全文层浏览器开关（2026-10-26）:');
{
  // 起因：C 批在 CHANGELOG 写了「`--sources` 通道不开浏览器 ⇒ 走不到 T2b，这是有意为之」。
  // 2026-10-26 实测证伪该判断 —— `--sources europepmc --fulltext --fulltext-browser` 得到
  // byTier {T2b_pmc_pdf:1} / bytes 72998 / browserUsed true。真相是「默认关」而非「硬禁止」。
  // 这组守卫把「两套浏览器」这个区分固定下来：检索层的 exe/browser 与全文层的 openBrowser()。

  const SP = fs.readFileSync(path.join(__dirname, 'search-papers.cjs'), 'utf8');
  const CH = fs.readFileSync(path.join(__dirname, 'lib', 'fulltext-chain.cjs'), 'utf8');

  t('★ 文档口径守卫：`--sources` 行必须区分「检索层不启浏览器」与「全文层可显式开」', () => {
    // 旧文案「**给此参数即不启动浏览器**」把「默认关」写成了「一律不启」，
    // 读者会以为多源通道永远拿不到 T2b —— 而实测是可以的。
    const line = (SKILL_TXT.split(/\r?\n/).find(l => /^\|\s*`--sources SPEC`\s*\|/.test(l)) || '');
    assert.ok(line, 'SKILL.md 里找不到 --sources 参数行');
    assert.ok(/检索层/.test(line), '--sources 行未说明「检索层不启浏览器」，实际：' + line.slice(0, 120));
    assert.ok(/--fulltext-browser/.test(line), '--sources 行未点名全文层的显式开关 --fulltext-browser');
    assert.ok(!/给此参数即\*\*?不启动浏览器/.test(line), '--sources 行仍有无限定的「即不启动浏览器」表述');
  });

  t('★ 源码守卫：全文层的 allowBrowser 只认 --fulltext-browser，不得被 useMulti 二次收紧', () => {
    // 若有人照抄检索层写法写成 `useMulti ? false : ...`，多源通道将永远拿不到 T2b，
    // 且**不会报错** —— 只会静默少 1 篇，最难发现的那种退化。
    const i = SP.indexOf('runFulltextChain(');
    assert.ok(i > 0, '找不到 runFulltextChain 调用');
    const seg = SP.slice(i, SP.indexOf('});', i));
    assert.ok(/allowBrowser:\s*opts\.fulltextBrowser === true/.test(seg),
      '全文层未直连 opts.fulltextBrowser，实际：' + seg.slice(0, 200));
    assert.ok(!/useMulti/.test(seg), '全文层的浏览器开关被 useMulti 干扰了（多源通道将永远走不到 T2b）');
  });

  t('★ 源码守卫：检索层仍按 useMulti 分流（与全文层是两套，不可合并）', () => {
    // 反向守卫：修 F 批时**不能**为了让全文层开浏览器，顺手把检索层也放开 ——
    // 多源通道的检索全程走 HTTP，再启浏览器纯属浪费且会破坏无浏览器 CI 的可运行性。
    assert.ok(/const exe = useMulti \? null : findBrowser\(\);/.test(SP),
      '检索层的 exe 不再按 useMulti 分流');
    assert.ok(/const browser = useMulti \? null : await chromium\(\)\.launch/.test(SP),
      '检索层的 browser 不再按 useMulti 分流');
  });

  t('★ skipped 的 reason 必须区分「你没开」与「开了但不可用」', () => {
    // `browser_disabled` 会让读者以为自己该加参数；`browser_unavailable` 则是环境问题（缺 playwright / 缺浏览器）。
    // 实测教训：B 批曾把 6 篇失败原因写成 browser_disabled，真实原因是 no_oa / blocked（误导性诊断）。
    assert.ok(/opts\.allowBrowser \? 'browser_unavailable' : 'browser_disabled'/.test(CH),
      'browser 级的 skipped reason 未按 allowBrowser 区分');
    // 两阶段调度：Phase A 必须强制 http-only，否则「HTTP 能拿到也照样启浏览器」（A-2 承诺失效）
    assert.ok(/allowBrowser: false \}/.test(CH), 'Phase A 未强制 allowBrowser:false');
  });
}

  // ⚠ 用例数守卫必须排在**全部**（含异步）用例之后，否则计数不准 —— 这正是它该拦下的
  t('用例总数与 SKILL.md 声明值强一致', () => {
    const total = pass + fail + 1; // 本用例尚未计入
    const m = /——\s*\*\*(\d+) 项\*\*纯逻辑离线自测/.exec(SKILL_TXT);
    assert.ok(m, 'SKILL.md 未声明用例数');
    assert.strictEqual(Number(m[1]), total, 'SKILL.md 声明 ' + m[1] + ' 项，实际 ' + total + ' 项');
    assert.ok(total >= 78, '低于施工前设定的 78 项下限');
  });

  console.log('\n通过 ' + pass + ' / 失败 ' + fail);
  process.exit(fail ? 1 : 0);
})();
