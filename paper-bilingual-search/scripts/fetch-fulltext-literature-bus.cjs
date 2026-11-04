#!/usr/bin/env node
/* eslint-disable */
/**
 * fetch-fulltext-literature-bus.cjs — 对「存量文献总线」抓全文（M-A 第 1 步：通道打通后落盘全文）
 *
 * 前置：先跑 re-enrich-literature-bus.cjs --apply 回填 pmcid（否则多数记录没有 T1 入口）。
 * 作用：调用 fulltext-chain.cjs 的四级回退链（T1 EPMC XML → T2 PMC HTML → T3 Unpaywall → T4 出版商页），
 *       把全文文本化落盘 `literature/fulltext/<pmcid|doi_x>.txt` + `<...>.json`（含方法学信号 + 偏移量），
 *       让评审可读全文后把 evidence-link 从 B 升 A。
 *
 * 纪律：
 *   1. **默认不写总线**：抓到的文件落 fulltext/（这是产品），但 records.jsonl 的 fulltextPath 只在 --apply 时回填。
 *   2. **可缓存断点续跑**：txt+json 同时存在即复用，不重复下载（中断后重跑只补未完成）。
 *   3. **不静默降级**：失败（not_available / no_entry）逐条计入 stat.byStatus，显式点名。
 *   4. **不自动改 evidenceLevel**：本脚本只落素材，分级仍由人工读全文裁决（M-A/M-B 红线）。
 *   5. **记录数守恒**：写回时 141 进 141 出。
 */
'use strict';

const fs = require('fs');
const path = require('path');
const { runFulltextChain } = require('./lib/fulltext-chain.cjs');

const DEFAULT_BUS = 'D:/petfood-platform/data/bus/literature/records.jsonl';

function parseArgs(argv) {
  // relBase：fulltextPath 的基址。项目约定是**相对 D:/petfood-platform 仓库根**
  //   （见 kb 仓库 tools/gates/verify-links.py:56 `BUS_ROOT = D:/petfood-platform # fulltextPath 是相对该根的路径`）。
  //   写错基址会让 verify-links.py 找不到文件 ⇒ 必须显式声明，不靠猜。
  const a = { bus: DEFAULT_BUS, apply: false, concurrency: 2, limit: null, allowBrowser: false, relBase: 'D:/petfood-platform' };
  for (let i = 2; i < argv.length; i++) {
    const x = argv[i];
    if (x === '--apply') a.apply = true;
    else if (x === '--allow-browser') a.allowBrowser = true;
    else if (x === '--bus') a.bus = argv[++i];
    else if (x === '--rel-base') a.relBase = argv[++i];
    else if (x === '--concurrency') a.concurrency = Math.max(1, Math.min(4, Number(argv[++i]) || 2));
    else if (x === '--limit') a.limit = Number(argv[++i]) || null;
  }
  return a;
}

function readJsonl(p) {
  if (!fs.existsSync(p)) throw new Error('总线文件不存在: ' + p);
  const out = [];
  for (const [i, line] of fs.readFileSync(p, 'utf8').split('\n').entries()) {
    const t = line.trim();
    if (!t) continue;
    try { out.push(JSON.parse(t)); } catch { throw new Error('第 ' + (i + 1) + ' 行非法 JSON: ' + p); }
  }
  return out;
}

async function run() {
  const a = parseArgs(process.argv);
  const recs = readJsonl(a.bus);
  const total = recs.length;
  const outDir = path.dirname(a.bus);
  console.error('[fulltext] 读取总线 ' + total + ' 条 → outDir=' + outDir + (a.apply ? ' (--apply 回填 fulltextPath)' : ' (不写总线)'));

  // 年度下限（2026-10-30 用户规则：论文只检索 2010 年后）：
  // pre-2010 记录**不再抓全文** —— 它们已不可能成为新证据，抓了只是白耗网络与风控额度。
  // 但**不删不改**：存量原样留在总线（历史存档），只跳过抓取，并显式报跳过条数。
  const MIN_YEAR = 2010;
  const pre = recs.filter((r) => Number.isInteger(r.year) && r.year < MIN_YEAR);
  if (pre.length && !process.argv.includes('--allow-pre-2010')) {
    console.error(`[fulltext] 跳过 ${pre.length} 条 pre-${MIN_YEAR} 记录（不抓全文；--allow-pre-2010 可覆盖）`);
  }
  const eligible = process.argv.includes('--allow-pre-2010')
    ? recs
    : recs.filter((r) => !(Number.isInteger(r.year) && r.year < MIN_YEAR));

  const list = a.limit ? eligible.slice(0, a.limit) : eligible;
  const { stat } = await runFulltextChain(list, {
    outDir,
    concurrency: a.concurrency,
    allowBrowser: a.allowBrowser,
    cache: true,
  });

  // 回填 fulltextPath（仅 --apply）+ 记录数守恒校验
  let backfilled = 0;
  if (a.apply) {
    for (const r of recs) {
      const ft = r.fulltext;
      if (ft && ft.status === 'ok' && ft.textFile) {
        // 基址 = 仓库根（relBase），与既有 4 条旧值 `data/bus/literature/fulltext/...` 及
        // verify-links.py 的 BUS_ROOT 口径一致。
        const absFile = path.join(outDir, 'fulltext', ft.textFile);
        const rel = path.relative(a.relBase, absFile).split(path.sep).join('/');
        if (r.fulltextPath !== rel) { r.fulltextPath = rel; backfilled++; }
      }
    }
    const sorted = [...recs].sort((x, y) => (x.id < y.id ? -1 : x.id > y.id ? 1 : 0));
    const body = sorted.map((r) => {
      // 剔除内部字段（fulltext 是链在内存里挂的，不属于总线契约 FIELDS）
      const { fulltext, enrich, titleEn, _enrich, ...clean } = r;
      return JSON.stringify(clean);
    }).join('\n');
    fs.writeFileSync(a.bus, body ? body + '\n' : '', 'utf8');
    console.error('[fulltext] 已回填 fulltextPath ' + backfilled + ' 条并写回总线 ' + sorted.length + ' 条');
  } else {
    console.error('[fulltext] 未写总线（仅落 fulltext/ 文件）。如需回填 fulltextPath 加 --apply。');
  }

  const summary = {
    busTotal: total,
    processed: list.length,
    stat: {
      records: stat.records, withEntry: stat.withEntry, noEntry: stat.noEntry,
      byEntry: stat.byEntry, ok: stat.ok, cached: stat.cached, failed: stat.failed,
      byTier: stat.byTier, byStatus: stat.byStatus, bytes: stat.bytes,
    },
    fulltextBackfilled: a.apply ? backfilled : null,
  };
  console.log(JSON.stringify(summary, null, 2));

  if (recs.length !== total) { console.error('[FAIL] 记录数不守恒'); process.exit(1); }
}

run().catch((e) => { console.error('[FAIL] ' + (e && e.stack || e)); process.exit(1); });
