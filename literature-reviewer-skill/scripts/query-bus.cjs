#!/usr/bin/env node
/**
 * query-bus.cjs —— 文献总线只读查询（批 15 N19/P1-6 知识链中段）
 *
 * 为什么需要它：文献评审技能是独立的 8 阶段流程（自己检索、自己导出去重），
 * 全目录搜不到 `records.jsonl` —— 它不知道文献总线存在，于是同一主题被检索两遍，
 * 且评审结论无法回溯到总线记录。本脚本给评审技能一个**只读入口**：
 * 检索前先查总线，命中就复用（跳过检索）；未命中再走原流程，结果仍由 export-bus 回写。
 *
 * 铁律：
 *   - **只读**。本脚本不写任何文件（文献库唯一写方仍是 export-bus.cjs）。
 *   - 无命中时明确返回空 + 提示，**不编造、不兜底猜**。
 *
 * 用法：
 *   node query-bus.cjs --kw 酶制剂              # 关键词（标题/期刊/标签，不区分大小写）
 *   node query-bus.cjs --kw 膳食纤维 --year-from 2020
 *   node query-bus.cjs --id 989f11bc           # 按 id 前缀
 *   node query-bus.cjs --tag 猫                 # 按标签精确匹配
 *   node query-bus.cjs --all                   # 全部（只给摘要）
 *   node query-bus.cjs --kw x --json           # 机读
 *   node query-bus.cjs --selftest              # 证伪
 *
 * 退出码：0 找到 / 1 未找到 / 2 环境错误
 */
'use strict';

const fs = require('node:fs');
const path = require('node:path');

const DEFAULT_BUS =
  process.env.LITERATURE_BUS ||
  'D:/petfood-platform/data/bus/literature/records.jsonl';

/** 读 jsonl，跳过空行与坏行（坏行计数返回，不静默） */
function loadRecords(file) {
  const raw = fs.readFileSync(file, 'utf8');
  const rows = [];
  let bad = 0;
  for (const line of raw.split('\n')) {
    const t = line.trim();
    if (!t) continue;
    try {
      const r = JSON.parse(t);
      if (r && typeof r === 'object') rows.push(r);
      else bad += 1;
    } catch {
      bad += 1;
    }
  }
  return { rows, bad };
}

const norm = (s) => String(s ?? '').toLowerCase();

/**
 * 过滤。所有条件为 AND。
 * @returns {Array} 命中的记录（不排序改变输入顺序）
 */
function match(rows, q) {
  const kw = q.kw ? norm(q.kw) : null;
  const idPrefix = q.id ? norm(q.id) : null;
  const tag = q.tag ? norm(q.tag) : null;
  return rows.filter((r) => {
    if (idPrefix && !norm(r.id).startsWith(idPrefix)) return false;
    if (q.yearFrom != null && !(Number(r.year) >= Number(q.yearFrom))) return false;
    if (tag) {
      const tags = Array.isArray(r.tags) ? r.tags : [];
      if (!tags.some((t) => norm(t) === tag)) return false;
    }
    if (kw) {
      const hay = [r.title, r.journal, r.sourceUrl, ...(Array.isArray(r.tags) ? r.tags : [])]
        .map(norm)
        .join(' ');
      if (!hay.includes(kw)) return false;
    }
    return true;
  });
}

function brief(r) {
  return {
    id: String(r.id || '').slice(0, 8),
    idFull: r.id,
    title: r.title || '',
    journal: r.journal || '',
    year: r.year ?? null,
    url: r.sourceUrl || '',
  };
}

function selftest() {
  const cases = [];
  const t = (label, cond) => cases.push([label, cond]);

  const rows = [
    { id: 'a'.repeat(40), title: '酶制剂在动物营养中的研究进展', journal: '中国畜牧兽医文摘', year: 2007, tags: ['酶'], sourceUrl: 'https://x/1' },
    { id: 'b'.repeat(40), title: '犬猫碳水化合物营养', journal: '宠物食品', year: 2023, tags: [], sourceUrl: 'https://x/2' },
    { id: 'c'.repeat(40), title: '非淀粉多糖酶制剂在犬粮中的应用', journal: '饲料工业', year: 2021, tags: ['猫'], sourceUrl: 'https://x/3' },
  ];

  t('关键词命中 2 条', match(rows, { kw: '酶制剂' }).length === 2);
  t('关键词命中 0 条时返回空（不兜底）', match(rows, { kw: '不存在的词' }).length === 0);
  t('大小写不敏感', match(rows, { kw: 'ABCD' }).length === 0 && match([{ id: 'x', title: 'ABCD' }], { kw: 'abcd' }).length === 1);
  t('id 前缀命中 1 条', match(rows, { id: 'bbb' }).length === 1);
  t('yearFrom 过滤生效', match(rows, { kw: '酶', yearFrom: 2020 }).length === 1);
  t('tag 精确匹配', match(rows, { tag: '猫' }).length === 1);
  t('tag 不做子串匹配', match(rows, { tag: '猫粮' }).length === 0);
  t('多条件为 AND', match(rows, { kw: '酶制剂', yearFrom: 2020 }).length === 1);
  t('brief 截断 id 为 8 位且保留全 id', brief(rows[0]).id === 'aaaaaaaa' && brief(rows[0]).idFull.length === 40);

  // 坏行必须被计数而非静默丢弃
  const dir = fs.mkdtempSync(path.join(process.env.TEMP || process.env.TMPDIR || '.', 'qb-'));
  const f = path.join(dir, 'records.jsonl');
  fs.writeFileSync(f, `${JSON.stringify(rows[0])}\n{坏行}\n\n${JSON.stringify(rows[1])}\n`);
  const loaded = loadRecords(f);
  t('坏行被计数（不静默）', loaded.bad === 1 && loaded.rows.length === 2);
  fs.rmSync(dir, { recursive: true, force: true });

  const bad = cases.filter(([, c]) => !c);
  for (const [label] of bad) console.error(`  FAIL ${label}`);
  console.log(`selftest: ${bad.length ? 'FAIL' : 'PASS'}（${cases.length - bad.length}/${cases.length}）`);
  return bad.length ? 1 : 0;
}

function main() {
  const argv = process.argv.slice(2);
  if (argv.includes('--selftest')) return selftest();

  const arg = (name) => {
    const i = argv.indexOf(name);
    return i >= 0 && argv[i + 1] ? argv[i + 1] : null;
  };
  const file = arg('--bus') || DEFAULT_BUS;
  if (!fs.existsSync(file)) {
    console.error(`[环境错误] 文献总线不存在：${file}`);
    return 2;
  }

  const q = {
    kw: arg('--kw'),
    id: arg('--id'),
    tag: arg('--tag'),
    yearFrom: arg('--year-from') == null ? null : Number(arg('--year-from')),
  };
  const all = argv.includes('--all');
  if (!all && !q.kw && !q.id && !q.tag) {
    console.error('用法：--kw <词> | --id <前缀> | --tag <标签> | --all｜加 --json 机读｜--selftest');
    return 2;
  }

  const { rows, bad } = loadRecords(file);
  const hits = (all ? rows : match(rows, q)).map(brief);

  if (argv.includes('--json')) {
    console.log(JSON.stringify({ total: rows.length, badLines: bad, hits }, null, 2));
  } else {
    console.log(`[${hits.length ? 'HIT' : 'EMPTY'}] 文献总线 ${file}（共 ${rows.length} 条${bad ? `，坏行 ${bad}` : ''}）`);
    for (const h of hits) {
      console.log(`  - ${h.id}  ${String(h.title).slice(0, 40)} ｜ ${h.journal || '—'} ｜ ${h.year ?? '—'}`);
      if (h.url) console.log(`    ${h.url}`);
    }
    if (!hits.length) {
      console.log('  未命中：总线里没有匹配记录。可走原检索流程，结果由 export-bus.cjs 回写（保持单写方）。');
    }
  }
  return hits.length ? 0 : 1;
}

if (require.main === module) process.exit(main());

module.exports = { loadRecords, match, brief };
