#!/usr/bin/env node
/* eslint-disable */
/**
 * build-keyword-lib.cjs — 把「宠物食品行业专业文章检索关键词组合清单」解析为机器可读数据层
 *
 * 输入：Word「另存为网页」导出的 .doc（实为 UTF-8 HTML，带 BOM）
 * 输出：
 *   assets/petfood-keywords.json      —— 机器可读（章节 / 分组 / 中英术语 / 官方推荐检索式）
 *   references/petfood-keywords.md    —— 人工可读目录（带章节溯源）
 *
 * 解析规则（与源文档约定强绑定，文档改版时按下面 5 条对齐即可）:
 *   ① 一级标题: `二、营养成分类关键词`        (中文数字 + 、)
 *   ② 二级标题: `2.1 宏量营养素`              (N.N + 空格)
 *   ③ 三级分组: `【蛋白质与氨基酸】`          (方头括号独占一行)
 *   ④ 术语行  : `中文：a、b、c` / `英文：a, b, c`
 *   ⑤ 检索式  : `推荐检索式示例` 之后紧跟 中文：/英文： 两行
 *   ⑥ 十一章节: 表格形式，表头 `研究主题` / `推荐检索式`，之后「主题行 / 表达式行」交替
 *
 * 用法:
 *   node build-keyword-lib.cjs --doc "<清单.doc>" [--out <技能根目录>] [--json-only]
 */
'use strict';

const fs = require('fs');
const path = require('path');

const CN = { 一: 1, 二: 2, 三: 3, 四: 4, 五: 5, 六: 6, 七: 7, 八: 8, 九: 9 };
function cnNum(s) {
  if (!s) return 0;
  if (s === '十') return 10;
  if (s.startsWith('十')) return 10 + (CN[s[1]] || 0);
  if (s.includes('十')) { const [p, q] = s.split('十'); return (CN[p] || 0) * 10 + (q ? CN[q] : 0); }
  return CN[s] || 0;
}

/** 抽取 HTML 中的可见文本，保留段落/表格的换行与制表结构 */
function htmlToText(html) {
  let s = String(html).replace(/^\uFEFF/, '');
  s = s.replace(/<style[\s\S]*?<\/style>/gi, '')
    .replace(/<script[\s\S]*?<\/script>/gi, '')
    .replace(/<!--[\s\S]*?-->/g, '');
  s = s.replace(/<\/(p|div|tr|h1|h2|h3|h4|li|table)>/gi, '\n')
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/t[dh]>/gi, '\t')
    .replace(/<[^>]+>/g, '');
  const ENT = { '&nbsp;': ' ', '&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"', '&#39;': "'", '&ldquo;': '“', '&rdquo;': '”', '&mdash;': '—', '&hellip;': '…', '&times;': '×', '&alpha;': 'α', '&beta;': 'β', '&gamma;': 'γ' };
  s = s.replace(/&[a-zA-Z#0-9]+;/g, m => (ENT[m] !== undefined ? ENT[m] : ' '));
  return s.split(/\r?\n/).map(l => l.replace(/[ \t\u00a0]+/g, ' ').trim()).filter(Boolean);
}

/** 术语行切分：源文档混用中英文逗号与顿号 */
function splitTerms(s) {
  return String(s).split(/[,，、;；]/).map(x => x.trim()).filter(Boolean);
}

function parseDoc(lines) {
  const sections = [];
  const presets = [];
  const notes = [];
  let sec = null, sub = null, grp = null, inExamples = false, subSeq = 0, grpSeq = 0;

  const ensureGrp = (fallbackLabel) => {
    if (grp) return grp;
    grpSeq++;
    grp = {
      id: 'S' + sec.key + '.' + subSeq + '.' + grpSeq,
      label: fallbackLabel || (sub ? sub.title : sec.title),
      sectionTitle: sec.title, subNo: sub ? sub.no : null, subTitle: sub ? sub.title : null,
      zh: [], en: [],
    };
    sec.groups.push(grp);
    return grp;
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    let m;

    // ① 一级标题
    if ((m = line.match(/^([一二三四五六七八九十]+)、\s*(.+?)(?:关键词)?$/))) {
      const key = cnNum(m[1]);
      sec = { key, no: m[1], title: m[2].trim(), groups: [], examples: [] };
      sections.push(sec); sub = null; grp = null; inExamples = false; subSeq = 0; grpSeq = 0;
      continue;
    }
    if (!sec) continue;

    // ⑥ 十一章节表格（必须在二级标题之前判断，其行形如「功能性成分与肠道健康」）
    if (sec.key === 11) {
      if (line === '研究主题' || line === '推荐检索式') continue;
      if (/\(.+(OR|AND).+\)/i.test(line)) {
        const last = presets[presets.length - 1];
        if (last && !last.query) last.query = line;
        else presets.push({ id: 'P' + (presets.length + 1), theme: '(未配对)', query: line });
        continue;
      }
      presets.push({ id: 'P' + (presets.length + 1), theme: line, query: null });
      continue;
    }

    // ⑦ 十二章节：数据库检索策略建议（散文条目）——含证据分级要用的人工规则，必须保留
    if (sec.key === 12 || line.startsWith('使用提示：')) {
      const t = line.replace(/^使用提示：/, '使用提示: ');
      // 过滤页脚装饰行（「—— 清单 · 完 ——」之类），只保留有信息量的建议
      if (!/^十二、/.test(t) && !/^——/.test(t) && t.length > 6) notes.push(t);
      continue;
    }

    // ② 二级标题
    if ((m = line.match(/^(\d+\.\d+)\s+(.+)$/))) {
      sub = { no: m[1], title: m[2].trim() };
      subSeq++; grpSeq = 0; grp = null; inExamples = false;
      continue;
    }
    // ③ 三级分组
    if ((m = line.match(/^【(.+)】$/))) {
      grp = null; inExamples = false;
      ensureGrp(m[1].trim());
      continue;
    }
    // ⑤ 示例标记
    if (line === '推荐检索式示例') { inExamples = true; grp = null; continue; }

    // ④ 术语行 / 示例检索式行
    if ((m = line.match(/^(中文|英文)[:：](.+)$/))) {
      const isZh = m[1] === '中文';
      if (inExamples) {
        const last = sec.examples[sec.examples.length - 1];
        if (last && (isZh ? !last.zh : !last.en)) { if (isZh) last.zh = m[2].trim(); else last.en = m[2].trim(); }
        else sec.examples.push({ zh: isZh ? m[2].trim() : null, en: isZh ? null : m[2].trim(), scope: sub ? sub.no + ' ' + sub.title : sec.title });
        continue;
      }
      const g = ensureGrp(null);
      if (isZh) g.zh.push(...splitTerms(m[2])); else g.en.push(...splitTerms(m[2]));
      continue;
    }

    // 无子标题章节（八/九/十）的首行可能是散文说明，忽略
  }

  // 清洗：没有术语的分组丢弃（多为说明性占位）
  for (const s of sections) s.groups = s.groups.filter(g => g.zh.length || g.en.length);
  return { sections, presets: presets.filter(p => p.query), notes };
}

function buildMarkdown(lib) {
  const L = [];
  L.push('# 宠物食品行业检索关键词库（机器可读版）');
  L.push('');
  L.push('> 由 `scripts/build-keyword-lib.cjs` 从源清单自动解析生成，**请勿手工编辑本文件**，改源清单后重跑即可。');
  L.push('');
  L.push('- 源文件：`' + lib.source.file + '`');
  L.push('- 解析时间：' + lib.source.parsedAt);
  L.push('- 一级章节：' + lib.sections.length + '；术语分组：' + lib.sections.reduce((a, s) => a + s.groups.length, 0) + '；官方推荐检索式：' + lib.presets.length);
  L.push('');
  L.push('## 章节索引');
  L.push('');
  L.push('| 组 ID | 章节 | 分组 | 中文术语数 | 英文术语数 |');
  L.push('|---|---|---|---:|---:|');
  for (const s of lib.sections) {
    if (!s.groups.length) continue;
    for (const g of s.groups) {
      L.push('| `' + g.id + '` | ' + s.no + '、' + s.title + ' | ' + g.label + ' | ' + g.zh.length + ' | ' + g.en.length + ' |');
    }
  }
  L.push('');
  L.push('## 官方推荐跨维度检索式');
  L.push('');
  L.push('| 预设 ID | 研究主题 | 检索式 |');
  L.push('|---|---|---|');
  for (const p of lib.presets) L.push('| `' + p.id + '` | ' + p.theme + ' | `' + p.query.replace(/\|/g, '\\|') + '` |');
  L.push('');
  L.push('## 用法');
  L.push('');
  L.push('```bash');
  L.push('node scripts/build-queries.cjs --list                       # 列出全部词组');
  L.push('node scripts/build-queries.cjs --preset P1 --print          # 直接套用官方推荐式');
  L.push('node scripts/build-queries.cjs --compose S2.1.1,S5.1 --out q.txt  # 物种×成分×功效自动组合');
  L.push('```');
  L.push('');
  return L.join('\n');
}

function main() {
  const argv = process.argv.slice(2);
  const get = (k, d) => { const i = argv.indexOf(k); return i >= 0 ? argv[i + 1] : d; };
  const docPath = get('--doc');
  if (!docPath) { console.error('用法: node build-keyword-lib.cjs --doc "<清单.doc>" [--out <技能根目录>]'); process.exit(1); }
  const root = get('--out') || path.resolve(__dirname, '..');

  if (!fs.existsSync(docPath)) { console.error('[FATAL] 源文件不存在: ' + docPath); process.exit(1); }
  const raw = fs.readFileSync(docPath, 'utf8');
  const lines = htmlToText(raw);
  if (lines.length < 30) { console.error('[FATAL] 解析出的行数过少(' + lines.length + ')，源文件格式可能已变化'); process.exit(1); }

  const { sections, presets, notes } = parseDoc(lines);
  const lib = {
    $schema: 'petfood-keywords/v1',
    source: { file: path.basename(docPath), title: lines[0] || '(未命名)', parsedAt: new Date().toISOString(), lines: lines.length },
    sections: sections.filter(s => s.groups.length || s.examples.length),
    presets,
    notes,
  };

  const nGroups = lib.sections.reduce((a, s) => a + s.groups.length, 0);
  const nTerms = lib.sections.reduce((a, s) => a + s.groups.reduce((b, g) => b + g.zh.length + g.en.length, 0), 0);
  if (nGroups < 5 || presets.length < 3) {
    console.error('[FATAL] 解析结果异常：分组 ' + nGroups + '、检索式 ' + presets.length + ' —— 疑似文档结构变化，请人工核对');
    process.exit(1);
  }

  const assetsDir = path.join(root, 'assets');
  fs.mkdirSync(assetsDir, { recursive: true });
  const jp = path.join(assetsDir, 'petfood-keywords.json');
  fs.writeFileSync(jp, JSON.stringify(lib, null, 2), 'utf8');

  let wroteMd = false;
  if (!argv.includes('--json-only')) {
    fs.mkdirSync(path.join(root, 'references'), { recursive: true });
    fs.writeFileSync(path.join(root, 'references', 'petfood-keywords.md'), buildMarkdown(lib), 'utf8');
    wroteMd = true;
  }

  console.log(JSON.stringify({
    event: 'keyword_lib_built',
    sections: lib.sections.length, groups: nGroups, terms: nTerms, presets: presets.length,
    json: jp, md: wroteMd ? path.join(root, 'references', 'petfood-keywords.md') : null,
  }, null, 2));
}
main();
