#!/usr/bin/env node
/* eslint-disable */
/**
 * build-queries.cjs — 检索式组合生成器
 *
 * 输入: assets/petfood-keywords.json（由 build-keyword-lib.cjs 从源清单解析）
 * 输出: 可直接喂给 search-papers.cjs --keywords-file 的检索式文件 + 可追溯 plan.json
 *
 * 三种用法:
 *   node build-queries.cjs --list                                  列出全部章节/词组/预设式
 *   node build-queries.cjs --preset P1,P6 --print                  直接套用官方推荐检索式
 *   node build-queries.cjs --compose 关节,机体的 --print            按词组关键词自动组合
 *   node build-queries.cjs --compose S5.5,S2.2.2 --species cat --out queries.txt
 *
 * 语法白名单（2026-10-04 在本机检索通道实测）:
 *   ✅ AND / OR / 括号() / 中文词 / 英文词        —— 实测正常返回
 *   ❌ "短语" 精确匹配                            —— 实测返回 0 条
 *   ❌ -排除词                                    —— 实测返回 0 条
 * 生成结果一律经 validateQuery 校验，命中黑名单即显式告警（不静默产出无效检索式）。
 */
'use strict';

const fs = require('fs');
const path = require('path');

const LIB = path.resolve(__dirname, '..', 'assets', 'petfood-keywords.json');

// 物种限定块：源文档「十二」明确建议中文加"伴侣动物"、英文加 "companion animal" 以提升查全率
const SPECIES = {
  both: { zh: '(犬 OR 猫 OR 伴侣动物 OR 宠物)', en: '(dog OR cat OR canine OR feline OR companion animal OR pet)' },
  dog: { zh: '(犬 OR 犬类 OR 伴侣动物)', en: '(dog OR canine)' },
  cat: { zh: '(猫 OR 猫科 OR 伴侣动物)', en: '(cat OR feline)' },
  none: { zh: '', en: '' },
};

function loadLib() {
  if (!fs.existsSync(LIB)) {
    console.error('[FATAL] 未找到关键词库: ' + LIB);
    console.error('  请先运行: node scripts/build-keyword-lib.cjs --doc "<清单.doc>"');
    process.exit(1);
  }
  return JSON.parse(fs.readFileSync(LIB, 'utf8'));
}

/** 按 id / 分组名 / 具体术语 解析词组引用 */
function resolveGroups(lib, ref) {
  const all = lib.sections.flatMap(s => s.groups);
  const r = String(ref).trim();
  const byId = all.find(g => g.id.toLowerCase() === r.toLowerCase());
  if (byId) return [byId];
  const byLabel = all.filter(g => g.label === r || g.label.includes(r) || (g.subTitle || '').includes(r));
  if (byLabel.length) return byLabel;
  const byTerm = all.filter(g => g.zh.includes(r) || g.en.some(t => t.toLowerCase() === r.toLowerCase()));
  if (byTerm.length) return byTerm;
  return [];
}

/** 按 id / 主题关键字 解析预设式 */
function resolvePresets(lib, ref) {
  const r = String(ref).trim();
  const byId = lib.presets.find(p => p.id.toLowerCase() === r.toLowerCase());
  if (byId) return [byId];
  return lib.presets.filter(p => p.theme.includes(r));
}

function allGroups(lib) { return lib.sections.flatMap(s => s.groups); }

/** 检索式合法性校验：命中黑名单语法必须显式告警 */
function validateQuery(q) {
  const w = [];
  if (/["“”『』]/.test(q)) w.push('含引号短语语法——本机检索通道实测返回 0 条，请改用无引号的自由词组合');
  if (/(^|\s)-\S/.test(q)) w.push('含 "-排除词" 语法——本机检索通道实测返回 0 条，请移除排减号');
  if (/[（(]/.test(q) && q.replace(/[^()（）]/g, '').length % 2 !== 0) w.push('括号不配对');
  const depthCheck = (() => { let d = 0; for (const c of q) { if (c === '(') d++; else if (c === ')') d--; if (d < 0) return false; } return d === 0; })();
  if (!depthCheck) w.push('括号嵌套不闭合');
  if (q.length > 500) w.push('检索式过长(' + q.length + ' 字符)，建议拆分为多条');
  if (/\b(NOT|AND NOT)\b/i.test(q)) w.push('含 NOT 运算——未在本机通道验证，结果可能不可预期');
  return w;
}

function orClause(terms, cap) {
  const used = terms.slice(0, cap);
  const dropped = terms.slice(cap);
  return { clause: used.length > 1 ? '(' + used.join(' OR ') + ')' : (used[0] || ''), used, dropped };
}

/**
 * 组合检索式: (物种限定) AND (词组1) AND (词组2) ...
 * lang: zh / en / both（both 为中英各出一条，召回互补）
 */
function compose(lib, refs, { species = 'both', lang = 'both', cap = 6, maxLen = 500 } = {}) {
  const resolved = [];
  for (const ref of refs) {
    const gs = resolveGroups(lib, ref);
    if (!gs.length) throw new Error('无法解析词组引用: ' + ref + '（用 --list 查看可用词组）');
    gs.forEach(g => resolved.push({ ref, group: g }));
  }
  const langs = lang === 'both' ? ['zh', 'en'] : [lang];
  const out = [];
  for (const lg of langs) {
    const parts = [];
    const trace = [];
    const sp = SPECIES[species];
    if (sp && sp[lg]) { parts.push(sp[lg]); trace.push({ kind: 'species', lang: lg, value: sp[lg] }); }
    const droppedAll = [];
    for (const { ref, group } of resolved) {
      const terms = group[lg] || [];
      if (!terms.length) { trace.push({ kind: 'group', id: group.id, lang: lg, skipped: '该语言无术语' }); continue; }
      const { clause, used, dropped } = orClause(terms, cap);
      if (clause) parts.push(clause);
      if (dropped.length) droppedAll.push({ id: group.id, label: group.label, dropped: dropped.length });
      trace.push({ kind: 'group', id: group.id, label: group.label, lang: lg, used: used.length, dropped: dropped.length, terms: used });
    }
    const q = parts.join(' AND ');
    if (!q) continue;
    const warnings = validateQuery(q).concat(q.length > maxLen ? ['超出 --max-len，建议减小 --cap 或拆分'] : []);
    if (droppedAll.length) warnings.push('部分术语超出 --cap 被截断: ' + droppedAll.map(d => d.id + '(' + d.dropped + '个)').join(', '));
    out.push({
      query: q, lang: lg, species,
      components: resolved.map(r => ({ id: r.group.id, label: r.group.label, ref: r.ref })),
      sourceRefs: resolved.map(r => r.group.sectionTitle + ' / ' + (r.group.subTitle || '') + ' / ' + r.group.label),
      trace, warnings,
    });
  }
  return out;
}

function cmdList(lib) {
  const out = [];
  out.push('## 章节与词组（共 ' + lib.sections.length + ' 章 / ' + allGroups(lib).length + ' 组）');
  out.push('');
  for (const s of lib.sections) {
    if (!s.groups.length) continue;
    out.push('### ' + s.no + '、' + s.title);
    for (const g of s.groups) {
      out.push('  ' + g.id.padEnd(8) + ' ' + g.label.padEnd(12) + ' 中' + String(g.zh.length).padStart(3) + ' / 英' + String(g.en.length).padStart(3)
        + '   例: ' + (g.zh.slice(0, 3).join('、') || g.en.slice(0, 3).join(', ')));
    }
    out.push('');
  }
  out.push('## 官方推荐跨维度检索式（' + lib.presets.length + ' 条）');
  out.push('');
  for (const p of lib.presets) out.push('  ' + p.id.padEnd(5) + ' ' + p.theme.padEnd(24) + ' ' + p.query);
  if (lib.notes && lib.notes.length) {
    out.push('');
    out.push('## 源文档检索策略建议');
    out.push('');
    lib.notes.forEach(n => out.push('  - ' + n));
  }
  return out.join('\n');
}

function main() {
  const argv = process.argv.slice(2);
  const get = (k, d) => { const i = argv.indexOf(k); return i >= 0 ? argv[i + 1] : d; };
  const has = k => argv.includes(k);
  if (!argv.length || has('--help')) {
    console.log('用法:\n  node build-queries.cjs --list\n  node build-queries.cjs --preset P1,P6 --print\n'
      + '  node build-queries.cjs --compose <词组引用,逗号分隔> [--species both|dog|cat|none] [--lang zh|en|both]\n'
      + '                          [--cap 6] [--out queries.txt] [--print] [--plan plan.json]');
    return;
  }
  const lib = loadLib();

  if (has('--list')) { console.log(cmdList(lib)); return; }

  const plans = [];
  if (has('--preset')) {
    for (const ref of get('--preset').split(',').map(s => s.trim()).filter(Boolean)) {
      const ps = resolvePresets(lib, ref);
      if (!ps.length) { console.error('[WARN] 未匹配到预设: ' + ref); continue; }
      for (const p of ps) {
        const warnings = validateQuery(p.query);
        plans.push({ query: p.query, lang: /[\u4e00-\u9fa5]/.test(p.query) ? 'zh' : 'en', species: 'preset', source: 'preset ' + p.id + ' ' + p.theme, components: [], trace: [], warnings });
      }
    }
  }
  if (has('--compose')) {
    const refs = get('--compose').split(',').map(s => s.trim()).filter(Boolean);
    let composed;
    try {
      composed = compose(lib, refs, {
        species: get('--species', 'both'), lang: get('--lang', 'both'),
        cap: parseInt(get('--cap', '6'), 10) || 6, maxLen: parseInt(get('--max-len', '500'), 10) || 500,
      });
    } catch (e) {
      console.error('[FATAL] ' + e.message);
      console.error('  可用词组可运行: node build-queries.cjs --list');
      process.exit(1);
    }
    composed.forEach(c => { c.source = 'compose: ' + refs.join(' + '); plans.push(c); });
  }
  if (!plans.length) { console.error('[FATAL] 未生成任何检索式。请用 --preset 或 --compose'); process.exit(1); }

  if (has('--print')) {
    plans.forEach((p, i) => {
      console.log('[' + (i + 1) + '] (' + p.lang + ') ' + p.query);
      if (p.source) console.log('    来源: ' + p.source);
      if (p.warnings.length) p.warnings.forEach(w => console.log('    ⚠ ' + w));
    });
  }
  if (has('--out')) {
    const f = get('--out');
    const lines = plans.map(p => p.query);
    const outDir = path.dirname(f);
    if (outDir && outDir !== '.' && !fs.existsSync(outDir)) fs.mkdirSync(outDir, { recursive: true });
    fs.writeFileSync(f, lines.join('\n') + '\n', 'utf8');
    console.log('已写入 ' + plans.length + " 条检索式 -> " + f);
  }
  const planFile = get('--plan', has('--out') ? path.join(path.dirname(get('--out') || '.'), 'plan.json') : null);
  if (planFile) {
    const planDir = path.dirname(planFile);
    if (planDir && planDir !== '.' && !fs.existsSync(planDir)) fs.mkdirSync(planDir, { recursive: true });
    fs.writeFileSync(planFile, JSON.stringify({ generatedAt: new Date().toISOString(), lib: lib.source, plans }, null, 2), 'utf8');
    console.log('检索式溯源计划 -> ' + planFile);
  }
  if (!has('--print') && !has('--out') && !has('--plan')) console.log(JSON.stringify(plans.map(p => p.query), null, 2));
  if (plans.some(p => p.warnings.length)) {
    console.error('[WARN] 有 ' + plans.filter(p => p.warnings.length).length + ' 条检索式存在告警，请在实跑前修正');
  }
}
// 仅在直接运行时执行 CLI；被 require 时导出纯函数供离线单测使用
if (require.main === module) main();
module.exports = { validateQuery, compose, resolveGroups, resolvePresets, orClause, SPECIES };
