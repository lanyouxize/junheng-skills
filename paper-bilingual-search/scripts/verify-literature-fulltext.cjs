#!/usr/bin/env node
/* eslint-disable */
/**
 * verify-literature-fulltext.cjs — M-A 全文通道门禁（落实设计文档「谁在守」）
 *
 * 判据：
 *   ① 一致性：isOA=true 但 pmcid=null 的每条记录，必须有 enrich-report 中的显式 reason
 *      （预印本 / 命中但无 PMC id / enrich 失败），不得出现「静默矛盾」。
 *   ② 覆盖：enrich-report.jsonl 必须覆盖总线全部记录（丢一条 = 漏检一条矛盾）。
 *   ③ 真实回填：带 pmcid 的记录数必须 == 报告中 enrichPmcid 非空的条数（防止「写了空值冒充回填」）。
 *   ④ 不静默降级：报告里 error:* 状态必须显式计数（门禁读出来，不假装成功）。
 *
 * 用法：node verify-literature-fulltext.cjs [--bus <path>] [--report <path>]
 * 退出码：0 = 通过；1 = 存在未解释矛盾 / 覆盖缺口 / 计数不一致。
 */
'use strict';

const fs = require('fs');
const path = require('path');

const DEFAULT_BUS = 'D:/petfood-platform/data/bus/literature/records.jsonl';
// fulltextPath 的基址 = D:/petfood-platform 仓库根（与 kb 仓库 tools/gates/verify-links.py:56 BUS_ROOT 同口径）
const BUS_ROOT = 'D:/petfood-platform';

function parseArgs(argv) {
  const a = { bus: DEFAULT_BUS, report: null };
  for (let i = 2; i < argv.length; i++) {
    if (argv[i] === '--bus') a.bus = argv[++i];
    else if (argv[i] === '--report') a.report = argv[++i];
  }
  return a;
}

function readJsonl(p) {
  if (!fs.existsSync(p)) return null;
  const out = [];
  for (const line of fs.readFileSync(p, 'utf8').split('\n')) {
    const t = line.trim();
    if (!t) continue;
    try { out.push(JSON.parse(t)); } catch { /* 坏行由调用方统计 */ }
  }
  return out;
}

function run() {
  const a = parseArgs(process.argv);
  const reportPath = a.report || path.join(path.dirname(a.bus), '_extract', 'enrich-report.jsonl');

  const recs = readJsonl(a.bus);
  if (!recs) { console.error('[FAIL] 总线不存在: ' + a.bus); process.exit(1); }

  // 坏行检测（fail-closed：有任何坏行即失败，不假装总数）
  let badLines = 0;
  for (const line of fs.readFileSync(a.bus, 'utf8').split('\n')) {
    const t = line.trim();
    if (!t) continue;
    try { JSON.parse(t); } catch { badLines++; }
  }
  if (badLines) { console.error('[FAIL] 总线有 ' + badLines + ' 行非法 JSON'); process.exit(1); }

  const rep = readJsonl(reportPath);
  const repById = new Map();
  if (rep) for (const r of rep) repById.set(r.id, r);

  const n = recs.length;
  const withPmcid = recs.filter((r) => (r.pmcid || '').trim()).length;
  const oaTrue = recs.filter((r) => r.isOa === true).length;
  const oaNoPmcid = recs.filter((r) => r.isOa === true && !(r.pmcid || '').trim());

  const problems = [];
  // 判据 ① + ②
  if (!rep) {
    problems.push('enrich-report.jsonl 缺失 ⇒ 无法解释 ' + oaNoPmcid.length + ' 条 isOA=true 却无 pmcid 的矛盾态（静默矛盾）');
  } else {
    if (repById.size !== n) {
      problems.push('报告覆盖缺口：报告 ' + repById.size + ' 条 vs 总线 ' + n + ' 条（漏检 ' + (n - repById.size) + ' 条矛盾）');
    }
    for (const r of oaNoPmcid) {
      const rr = repById.get(r.id);
      if (!rr || !rr.reason) {
        problems.push('矛盾态未解释: id=' + r.id + ' (isOA=true, pmcid=null, 无 reason)');
      }
    }
  }

  // 判据 ③
  const repWithPmcid = rep ? rep.filter((r) => (r.enrichPmcid || '').trim()).length : 0;
  if (rep && withPmcid !== repWithPmcid) {
    problems.push('回填不一致：总线带 pmcid ' + withPmcid + ' 条 ≠ 报告 enrichPmcid 非空 ' + repWithPmcid + ' 条');
  }

  // 判据 ④：error 状态显式计数
  const errStat = {};
  if (rep) for (const r of rep) if (String(r.status || '').startsWith('error:')) errStat[r.status] = (errStat[r.status] || 0) + 1;

  // 判据 ⑤（全文落盘）：fulltextPath 必须解析到真实文件（防「回填了路径但文件没落盘」的假状态）
  const withFulltext = recs.filter((r) => (r.fulltextPath || '').trim());
  const ftMissing = [];
  for (const r of withFulltext) {
    const abs = path.isAbsolute(r.fulltextPath) ? r.fulltextPath : path.join(BUS_ROOT, r.fulltextPath);
    if (!fs.existsSync(abs)) ftMissing.push({ id: r.id, path: r.fulltextPath });
  }
  if (ftMissing.length) {
    for (const m of ftMissing.slice(0, 10)) problems.push('fulltextPath 指向文件缺失: id=' + m.id + ' path=' + m.path);
    if (ftMissing.length > 10) problems.push('…另有 ' + (ftMissing.length - 10) + ' 条 fulltextPath 文件缺失');
  }

  // 判据 ⑥（年度下限，2026-10-30 用户规则「论文只检索 2010 年之后的文章」）
  //   分两层，刻意**只把 support 判红**：
  //     · 存量 pre-2010 记录：允许存在（历史存档），只报计数，不判红；
  //     · 若某条 **support 边**的依据文献年份 < 2010 ⇒ 判红。
  //   理由：规则管的是「拿什么去支撑对外宣称」，不是「库里能不能有旧文献」。
  //   把存量判红会让这条判据天天红，人就会习惯性忽略它（比没有判据更坏）。
  const MIN_YEAR = 2010;
  const pre2010 = recs.filter((r) => Number.isInteger(r.year) && r.year < MIN_YEAR);
  const preEdge = [];
  // 允许用 KB_EVIDENCE_LINK 指向副本，以便「注入违规数据」证伪本判据
  // （不先在活数据上制造违规，也不为测试另写一份判定逻辑——那等于测了个赝品）。
  const evidencePath = process.env.KB_EVIDENCE_LINK || path.join(BUS_ROOT, 'data/bus/evidence-link.jsonl');
  const supportNoFt = [];
  const refuteNoFt = [];
  if (fs.existsSync(evidencePath)) {
    const byId = new Map(recs.map((r) => [r.id, r]));
    for (const line of fs.readFileSync(evidencePath, 'utf8').split('\n')) {
      if (!line.trim()) continue;
      let e;
      try { e = JSON.parse(line); } catch { continue; }
      const rec = byId.get(e.literatureId);
      const y = rec && rec.year;
      const lvl = String(e.evidenceLevel || '').toUpperCase();
      const hasFt = !!(rec && rec.fulltextPath);
      if (e.direction === 'support') {
        if (Number.isInteger(y) && y < MIN_YEAR) {
          preEdge.push({ id8: String(e.literatureId).slice(0, 8), y, claim: e.claim, code: e.ingredientCode });
        }
        // 判据 ⑦（支撑边必须有全文，2026-10-30）
        //   A/B 级 support 边直接支撑对外宣称，必须能追到全文。
        //   凭摘要定级在证据治理上不可核查 —— 实测：3 条 A 级 refute 都只有摘要，
        //   而 note 里各用**不同措辞**声明「全文未取得 / 尝试取得失败 / closed」
        //   ⇒ 自然语言当判据必然漏，只有「有没有 fulltextPath」是硬的。
        //   refute 只报计数不判红：它不支撑宣称，无全文只削弱反向证据强度。
        //   pending / C 级不判：C 本身就是「证据不足」的标记。
        if ((lvl === 'A' || lvl === 'B') && !hasFt) {
          supportNoFt.push({ code: e.ingredientCode, claim: e.claim, lvl, id8: String(e.literatureId).slice(0, 8) });
        }
      } else if (e.direction === 'refute' && !hasFt) {
        refuteNoFt.push({ code: e.ingredientCode, claim: e.claim, lvl, id8: String(e.literatureId).slice(0, 8) });
      }
    }
    for (const p of preEdge.slice(0, 10)) problems.push(`support 边依据 ${p.y} 年文献（<${MIN_YEAR}）: ${p.code} × ${p.claim} · lit=${p.id8}`);
    if (preEdge.length > 10) problems.push(`…另有 ${preEdge.length - 10} 条 pre-${MIN_YEAR} support 边`);

    for (const p of supportNoFt.slice(0, 10)) problems.push(`support 边 ${p.lvl} 级但依据文献无全文（不可核查）: ${p.code} × ${p.claim} · lit=${p.id8}`);
    if (supportNoFt.length > 10) problems.push(`…另有 ${supportNoFt.length - 10} 条 A/B 级 support 边无全文`);
  }

  const summary = {
    bus: n,
    withPmcid,
    isOA_true: oaTrue,
    oaWithoutPmcid: oaNoPmcid.length,
    reportCoverage: rep ? repById.size : 0,
    enrichErrors: errStat,
    fulltextPath: withFulltext.length,
    fulltextMissing: ftMissing.length,
    pre2010Records: pre2010.length,
    pre2010SupportEdges: preEdge.length,
    supportEdgesWithoutFulltext: supportNoFt.length,
    refuteEdgesWithoutFulltext: refuteNoFt.length,
    pass: problems.length === 0,
  };
  console.log(JSON.stringify(summary, null, 2));
  if (problems.length) {
    console.error('\n[FAIL] ' + problems.length + ' 项问题:');
    for (const p of problems) console.error('  - ' + p);
    process.exit(1);
  }
  console.error('[PASS] 全文通道门禁通过：无静默矛盾、覆盖完整、回填一致、失败显式计数。');
}

run();
