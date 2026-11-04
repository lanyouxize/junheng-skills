#!/usr/bin/env node
/* eslint-disable */
/**
 * pack-site.cjs — 把一份检索产物打成「元典站点包」（自包含 · 可校验 · 幂等）
 *
 * 为什么要有这一步：`report.md` 是给**跑检索的人**看的（含大量过程信息与长表格），
 * 而站点页面是给**以后来查的人**看的 —— 它需要 frontmatter（标题/标签/状态）、
 * 需要图在同目录、需要一份机器可读的清单来校验「这包有没有被改过」。
 * 直接把 report.md 拷进 vault 会缺前两样，而手工补最容易漏的是第三样。
 *
 * ⚠ 三条纪律：
 *   1. **不猜站点路径**。本机没有 `vault/40_Maps`，所以本工具**只产出自包含目录 + 挂载片段**，
 *      绝不直接写 MOC。要不要收、收到哪，由人决定。
 *   2. **状态必须写在 frontmatter 里**（`status: 候选未确认`）。站点被全文检索时，
 *      frontmatter 会跟着一起被搜到；只把警告写在正文里，检索片段里就看不到了。
 *   3. **产物里不放当前时间**：一律取 `summary.json` 的 `startedAt`。否则同一份输入
 *      每次打包字节都不同，无法用 sha256 判断「内容有没有真的变」。
 *
 * 用法：
 *   node scripts/pack-site.cjs --dir <检索输出目录> --out <包目录> [--slug s] [--title t] [--dry-run]
 *   node scripts/pack-site.cjs --verify <包目录>          # 校验 manifest 与文件 sha256
 *
 * 退出码：0 成功/校验通过；1 校验失败或输入不全；2 用法错误
 */
'use strict';

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { CliError, fail, needVal } = require('./lib/cli.cjs');

const PACK_VERSION = 'site-pack/v1';
const CHART_FILES = ['evidence-grade-dist.svg', 'evidence-grade-species.svg', 'evidence-year-grade.svg'];

function parseArgs(argv) {
  const a = { dir: null, out: null, slug: null, title: null, verify: null, dryRun: false };
  for (let i = 2; i < argv.length; i++) {
    const t = argv[i];
    if (t === '--dir' || t === '--out-dir') { a.dir = needVal(argv, i, t, 'OUT_DIR'); i++; }
    else if (t === '--out') { a.out = needVal(argv, i, t, 'PACK_DIR'); i++; }
    else if (t === '--slug') { a.slug = needVal(argv, i, t, 'slug'); i++; }
    else if (t === '--title') { a.title = needVal(argv, i, t, '标题'); i++; }
    else if (t === '--verify') { a.verify = needVal(argv, i, t, 'PACK_DIR'); i++; }
    else if (t === '--dry-run') { a.dryRun = true; }
    else fail('未知参数: ' + t + '\n  支持: --dir, --out, --slug, --title, --dry-run, --verify');
  }
  if (a.verify) return a;
  if (!a.dir) fail('必须提供 --dir <检索输出目录>\n  示例: --dir OUT_DIR --out PACK_DIR');
  if (!a.out) fail('必须提供 --out <包目录>（站点包是新建目录，不复用检索输出目录）');
  if (path.resolve(a.out) === path.resolve(a.dir)) fail('--out 不能等于 --dir（会把报告目录写乱）');
  return a;
}

const sha256 = (buf) => crypto.createHash('sha256').update(buf).digest('hex');

/** 从目录名或 startedAt 生成稳定 slug（不含时间戳里的随机性）。 */
function makeSlug(dir, startedAt) {
  const m = /(\d{4})-?(\d{2})-?(\d{2})/.exec(String(startedAt || ''));
  const date = m ? m[1] + m[2] + m[3] : 'nodate';
  const base = path.basename(path.resolve(dir)).replace(/[^\w\u4e00-\u9fa5-]+/g, '-').replace(/^-+|-+$/g, '');
  return ('paper-search-' + date + (base ? '-' + base : '')).slice(0, 80);
}

/** frontmatter 的值一律双引号包裹并转义 —— 标题里有冒号/引号时裸写会让 YAML 解析失败。 */
function yamlStr(s) {
  return '"' + String(s === null || s === undefined ? '' : s).replace(/\\/g, '\\\\').replace(/"/g, '\\"') + '"';
}

/**
 * 从 report.md 里摘出统计口（避免站点页与报告两处数字各写各的）。
 * 摘不到就返回 null —— 不猜。
 */
function readStats(dir) {
  const p = path.join(dir, 'summary.json');
  try {
    const s = JSON.parse(fs.readFileSync(p, 'utf8'));
    return {
      startedAt: s.startedAt || null,
      site: s.site || null,
      runId: s.runId || null,
      keywords: Object.keys(s.keywords || {}),
    };
  } catch (e) {
    return null;
  }
}

/** 从 report.md 的「证据分级」汇总行里取分级计数（报告已经算过，站点页不重算）。 */
function readGradeLine(reportMd) {
  const m = /^\| 证据分级 \| (.+?) \|$/m.exec(reportMd);
  return m ? m[1] : null;
}

function buildPack(opts) {
  const dir = path.resolve(opts.dir);
  const out = path.resolve(opts.out);
  const reportPath = path.join(dir, 'report.md');
  if (!fs.existsSync(reportPath)) {
    throw new CliError('缺少 ' + reportPath + '\n  先跑: node scripts/assemble-report.cjs --dir ' + opts.dir + ' --format md', 1);
  }
  const reportMd = fs.readFileSync(reportPath, 'utf8');
  const meta = readStats(dir);
  const startedAt = (meta && meta.startedAt) || null;
  const slug = opts.slug || makeSlug(dir, startedAt);
  const title = opts.title || ('论文检索·中英对照报告（' + (startedAt ? String(startedAt).slice(0, 10) : '日期未知') + '）');

  const charts = [];
  const chartDir = path.join(dir, 'charts');
  if (fs.existsSync(chartDir)) {
    for (const f of CHART_FILES) {
      const p = path.join(chartDir, f);
      if (fs.existsSync(p)) charts.push({ name: f, buf: fs.readFileSync(p) });
    }
  }

  const gradeLine = readGradeLine(reportMd);
  const hasSynth = reportMd.includes('## 综合归纳');
  const allCandidate = !/已人工确认 \d+ 条（纯色）/.test(reportMd);

  // ── index.md：frontmatter + 醒目警示 + 报告正文 ──────────────
  const fm = [
    '---',
    'title: ' + yamlStr(title),
    'slug: ' + yamlStr(slug),
    // 标签用 YAML 流式数组；中文标签不加引号也能解析，但统一加引号更稳
    'tags: ["论文检索", "证据分级", "候选未确认"]',
    // ★ 状态写进 frontmatter：站点全文检索会把这里一起索引，只写在正文里则检索片段看不到
    'status: ' + yamlStr(allCandidate ? '候选未确认' : '部分已确认'),
    'source: ' + yamlStr('paper-bilingual-search · site-pack/v1'),
    'run_id: ' + yamlStr((meta && meta.runId) || ''),
    'started_at: ' + yamlStr(startedAt || ''),
    '---',
    '',   // frontmatter 与正文之间必须留空行：Obsidian 对 `---` 后紧贴内容容错不一
    '',
  ].join('\n');

  const banner = [
    '> ⚠ **本页所有证据等级均为启发式候选（`needsReview=true`）**，由脚本从摘要与标题自动判定，',
    '> 未经人工核对原文方法学章节。**在逐条核对并升级之前，任何一档都不得用于配方决策或对外宣称。**',
    '>',
    '> 本页由 `pack-site.cjs` 从检索产物打包；所有数字取自同一次运行的 `report.md`，不重算。',
    '',
  ].join('\n');

  const indexMd = fm + banner + reportMd;

  // ── README.md：怎么收录（给以后接手的人）──────────────────
  const readme = [
    '# 元典站点包 · ' + title,
    '',
    '本目录是**自包含**的：`index.md` 引用的图都在 `charts/` 下，没有外部依赖。',
    '',
    '## 怎么收录',
    '',
    '1. 整目录拷到 vault 的目标位置（如 `docs/site/` 或某个专题目录）。',
    '2. 把 `moc-entry.md` 里那一行加进对应的 MOC（`40_Maps/MOC--*.md`）—— **本工具不直接改 MOC**，',
    '   因为 MOC 的归属是人工判断，脚本猜错会把页面挂到不相干的主题下。',
    '3. 收录后跑一次 `node scripts/pack-site.cjs --verify <本目录>` 确认包未被改动。',
    '',
    '## 文件',
    '',
    '| 文件 | 说明 |',
    '|---|---|',
    '| `index.md` | 站点页正文（frontmatter + 警示 + 完整报告） |',
    '| `charts/*.svg` | 三张分布图（除非原目录没出图） |',
    '| `moc-entry.md` | 挂载片段 |',
    '| `manifest.json` | 机器可读清单（sha256 / 统计 / 清单项） |',
    '',
    '## 校验',
    '',
    '```bash',
    'node scripts/pack-site.cjs --verify <本目录>',
    '```',
    '',
    '`manifest.json` 里的 sha256 是**打包当时**的内容指纹。校验失败说明包被改过 —— ' +
      '要么是有人手改了正文（那行号可能已经与表格不对应），要么是文件拷坏了。两种都不该静默通过。',
    '',
  ].join('\n');

  const mocEntry = [
    '- [[' + slug + ']] — ' + title + (gradeLine ? '（' + gradeLine.split('｜')[0].trim() + '）' : ''),
    '',
  ].join('\n');

  return { out, slug, title, indexMd, readme, mocEntry, charts, meta, gradeLine, hasSynth, allCandidate };
}

function writePack(pack, dryRun) {
  const files = [];
  const plan = [
    { rel: 'index.md', buf: Buffer.from(pack.indexMd, 'utf8') },
    { rel: 'README.md', buf: Buffer.from(pack.readme, 'utf8') },
    { rel: 'moc-entry.md', buf: Buffer.from(pack.mocEntry, 'utf8') },
  ];
  for (const c of pack.charts) plan.push({ rel: 'charts/' + c.name, buf: c.buf });

  if (!dryRun) {
    for (const f of plan) {
      const p = path.join(pack.out, f.rel);
      fs.mkdirSync(path.dirname(p), { recursive: true });
      fs.writeFileSync(p, f.buf);
    }
  }
  for (const f of plan) files.push({ path: f.rel, bytes: f.buf.length, sha256: sha256(f.buf) });

  const manifest = {
    packVersion: PACK_VERSION,
    slug: pack.slug,
    title: pack.title,
    // 只用输入里的时间，不用 now() —— 否则每次打包指纹都变
    source: {
      tool: 'paper-bilingual-search',
      runId: (pack.meta && pack.meta.runId) || null,
      site: (pack.meta && pack.meta.site) || null,
      startedAt: (pack.meta && pack.meta.startedAt) || null,
    },
    status: pack.allCandidate ? 'candidate-unconfirmed' : 'partly-confirmed',
    stats: {
      keywords: (pack.meta && pack.meta.keywords) || [],
      gradeLine: pack.gradeLine,
      charts: pack.charts.length,
      hasSynthesis: pack.hasSynth,
    },
    files,
    // 收录前必须人做的事：写成机器可读的清单项，便于站点侧做「未完成」标记
    checklist: [
      '逐条核对 A/B 档原文方法学章节（对照全文，而不是摘要）',
      '确认物种与目标动物一致（体外/非靶动物的不能按 A/B 档引用）',
      '确认样本量足以支撑结论（"样本量未识别" 不等于 "小样本"）',
      '核对完成后把证据等级与 reviewed 标记回写，再重跑 assemble-report 与 pack-site',
    ],
  };

  if (!dryRun) {
    const mp = path.join(pack.out, 'manifest.json');
    fs.writeFileSync(mp, JSON.stringify(manifest, null, 2) + '\n', 'utf8');
  }
  return manifest;
}

function verify(packDir) {
  const dir = path.resolve(packDir);
  const mp = path.join(dir, 'manifest.json');
  if (!fs.existsSync(mp)) return { ok: false, errors: ['缺少 manifest.json：' + mp] };
  let m;
  try {
    m = JSON.parse(fs.readFileSync(mp, 'utf8'));
  } catch (e) {
    return { ok: false, errors: ['manifest.json 解析失败：' + String(e.message).slice(0, 160)] };
  }
  if (m.packVersion !== PACK_VERSION) {
    return { ok: false, errors: ['packVersion 不匹配：' + JSON.stringify(m.packVersion) + '（期望 ' + PACK_VERSION + '）'] };
  }
  const errors = [];
  const seen = new Set();
  for (const f of (m.files || [])) {
    seen.add(f.path);
    const p = path.join(dir, f.path);
    if (!fs.existsSync(p)) { errors.push('缺文件：' + f.path); continue; }
    const buf = fs.readFileSync(p);
    if (buf.length !== f.bytes) errors.push(f.path + ' 字节数不符：manifest ' + f.bytes + ' / 实际 ' + buf.length);
    const h = sha256(buf);
    if (h !== f.sha256) errors.push(f.path + ' sha256 不符（内容被改过或被拷坏）');
  }
  // manifest 之外多出来的文件也要报：站点包里混进来历不明的文件比缺文件更危险
  const walk = (d, base) => {
    for (const e of fs.readdirSync(d, { withFileTypes: true })) {
      const rel = base ? base + '/' + e.name : e.name;
      if (e.isDirectory()) walk(path.join(d, e.name), rel);
      else if (rel !== 'manifest.json' && !seen.has(rel)) errors.push('清单外多出文件：' + rel);
    }
  };
  walk(dir, '');
  return { ok: errors.length === 0, errors, manifest: m };
}

function main(argv) {
  const a = parseArgs(argv);
  if (a.verify) {
    const r = verify(a.verify);
    console.log(JSON.stringify({ ok: r.ok, errors: r.errors, slug: r.manifest && r.manifest.slug }, null, 2));
    return r.ok ? 0 : 1;
  }
  const pack = buildPack(a);
  const manifest = writePack(pack, a.dryRun);
  console.log(JSON.stringify({
    dryRun: !!a.dryRun,
    out: pack.out,
    slug: pack.slug,
    status: manifest.status,
    files: manifest.files.map((f) => f.path),
    charts: pack.charts.length,
    hasSynthesis: pack.hasSynth,
  }, null, 2));
  return 0;
}

module.exports = { PACK_VERSION, parseArgs, buildPack, writePack, verify, makeSlug, yamlStr };

if (require.main === module) {
  try {
    process.exit(main(process.argv));
  } catch (e) {
    if (e instanceof CliError) { console.error(e.message); process.exit(e.code); }
    console.error(e && e.stack ? e.stack : e);
    process.exit(2);
  }
}
