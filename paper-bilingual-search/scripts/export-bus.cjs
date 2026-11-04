#!/usr/bin/env node
'use strict';
/**
 * 文献总线写入器（索隐为唯一写方）
 *
 * 输入：search-papers.cjs --out <目录> 产出的每关键词 JSON（{records:[...]}）
 * 输出：D:/petfood-platform/data/bus/literature/records.jsonl（一篇一行，按 id 排序）
 *
 * 契约依据：docs/bus/CONTRACTS.md §2
 *   - id = sha1(doi 小写) ，无 doi 时 sha1(规范化标题)
 *   - 必填：id title year sourceUrl ingestedBy verifiedAt
 *   - 幂等：同 id 只更新可变字段（title/year/journal/sourceUrl/doi/tags），
 *           verifiedAt 保留**首次入库时间**，不因重跑而刷新
 *   - 缺 sourceUrl 的记录跳过并计数（不得用空 URL 充数）
 *
 * 用法：
 *   node scripts/export-bus.cjs --dir <检索输出目录> [--out <records.jsonl>] [--dry-run]
 *   node scripts/export-bus.cjs --check [--out <records.jsonl>]
 *   node scripts/export-bus.cjs --selftest
 *
 * 退出码：0 成功/新鲜  1 校验失败  2 环境错误
 */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

const DEFAULT_OUT = process.env.LITERATURE_BUS ||
  'D:/petfood-platform/data/bus/literature/records.jsonl';
// 2010 年前逐条白名单（基石数据出口）：默认与总线同目录，可用 --whitelist 覆盖。
// 文件不存在 = 空白名单 = 行为与旧版一致（不因缺文件而放宽，也不因缺文件而报错）。
const DEFAULT_WHITELIST = path.join(path.dirname(DEFAULT_OUT), 'pre2010-whitelist.json');
const SKIP_FILES = new Set(['summary.json', 'dedupe.json', 'diagnostics.json', 'prisma.json']);
// 契约字段（白名单）。**输出只含这些字段**——这是防止来源脏字段污染总线的核心防御，不可放开。
// 2026-10-26 补 14 个：按「文献库真实 schema」枚举得出（26 字段），不是拍脑袋列的。
// 事故形态：schema 早已从 12 扩到 26，白名单没跟上 ⇒ 每跑一次就把多出来的字段**静默裁掉**，
// 而 --check 与 selftest 当时全绿（它们只查必填字段在不在，不查「该在的还在不在」）。
// 教训：**白名单必须与真实 schema 同步**，否则它就从"防线"变成"静默裁剪器"。
// 复核方法（防再次脱钩）：逐条统计 records.jsonl 出现过的键，与本数组取差集，差集必须为空。
const FIELDS = [
  'id', 'doi', 'title', 'year', 'journal', 'abstractHash', 'fulltextPath', 'sourceUrl', 'sourceHost', 'ingestedBy', 'verifiedAt', 'tags',
  // —— schema 扩展字段，**顺序刻意与现有 records.jsonl 的键序一致** ——
  // order() 按本数组定键序，顺序一变，130 条记录全部重排，git diff 变成 130 行噪音。
  // 值为 0 差异也照样产生 diff，所以顺序不是风格问题，是「改一次脏一次」的成本问题。
  'abstract', 'titleZh', 'titleZhStatus', 'pmid', 'pmcid', 'isOa', 'oaStatus', 'oaUrl', 'abstractClean',
  // 中文摘要（2026-10-31 加）：这两个字段在 159 条存量中各有 140 条有值，却不在白名单里——
  // 跑一次 export-bus 就把 140 条中文摘要静默裁光（DROPPED_KEYS 只警告、不阻止写盘）。
  // 与 2026-10-26 的 language 事故同一形态：**白名单与真实 schema 脱钩 ⇒ 防线变裁剪器**。
  // 复核方法：逐条统计 records.jsonl 出现过的键，与 FIELDS 取差集，差集必须为空。
  'abstractZh', 'abstractZhStatus',
  // 仅少数记录有（PDF 抽取来源），排在最后，避免影响主体键序
  'abstractLicense', 'abstractRawSha256', 'abstractSource', 'doiSource', 'oaSource',
  // 学位论文等非英文文献需要记语种（2026-10-26 加：入库两篇学位论文时该字段被静默裁掉）
  'language',
  // —— 第三次同一个事故：白名单又没跟上 schema（2026-11-03 补）——
  // 库里有 6 个字段不在上面任何一版白名单里，跑一次 export-bus 就会被 order() 裁掉：
  //   abstractHashStatus / abstractSha256   15 条（legacy_missing 标记 + 实际摘要哈希）
  //   abstractKind / abstractCompletedFrom   6 条（正文节选？补全来源 cnki_html_reader:xxx）
  //   idStatus / idAnchor                   15 / 6 条（** id 锚分级**：doi_only / cn_secondary_no_doi
  //                                         / thesis_handle / pre_doi_pmcid + 锚原文）
  // 前两次是 language（10-26）、abstractZh（10-31），这次是 id 锚。
  // 三次同一形态，说明「补白名单」这个动作本身不够——判据必须在闸门里跑（见 --check 的差集校验）。
  // 顺序按库内真实键序追加，避免 order() 重排产生无意义 diff。
  'abstractHashStatus', 'abstractSha256', 'abstractKind', 'abstractCompletedFrom', 'idStatus', 'idAnchor',
];

// 中间件的哪些键会被 mapRecord 真正消费。不在此表 = 会被静默忽略，
// 故 mapRecord 末尾会把它记进 DROPPED_KEYS 并在结尾点名（见 reportDroppedKeys）。
// 这张表与 FIELDS 是**两处**，必须同步：FIELDS 管「写出去什么」，这张管「读进来认什么」。
// 2026-10-26 只改 FIELDS 没改这里，language 照样丢 —— 双点同步漏一个点，等于没改。
const CONSUMED_IN = new Set([
  'id', 'doi', 'doiFromUrl', 'titleEn', 'titleZh', 'paperUrl', 'sourceUrl', 'year', 'source',
  'abstractHash', 'fulltextPath', 'domain', 'tags', 'isOa',
  'titleZhStatus', 'abstract', 'abstractClean', 'abstractZh', 'abstractZhStatus', 'oaStatus', 'oaUrl', 'pmcid', 'pmid',
  'abstractLicense', 'abstractRawSha256', 'abstractSource', 'doiSource', 'oaSource', 'language',
]);

const sha1 = (s) => crypto.createHash('sha1').update(String(s), 'utf8').digest('hex');
const nowIso = () => new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
const normTitle = (t) => String(t || '')
  .replace(/[\uFF01-\uFF5E]/g, (c) => String.fromCharCode(c.charCodeAt(0) - 0xFEE0))
  .toLowerCase().replace(/\s+/g, ' ').trim();

// DOI 归一（2026-10-31）：中间件给的 doiFromUrl 常是 `https://doi.org/10.x`，
// 若直接 sha1 就会让「同一文献以 URL 入库 / 以纯 DOI 入库」得到两个 id（重复记录）。
// 归一 = 剥 URL 或 doi: 前缀（最多 3 层）、trim、小写、去尾斜杠。
const DOI_PREFIX = /^(?:https?:\/\/)?(?:dx\.)?doi\.org\/|^doi:\s*/i;
function normDoi(s) {
  let t = String(s || '').trim();
  for (let i = 0; i < 3 && t; i += 1) {
    const n = t.replace(DOI_PREFIX, '').trim();
    if (n === t) break;
    t = n;
  }
  return t.toLowerCase().replace(/\/+$/, '');
}

// 来源域名（无源 domain 时从 URL 兜底提取）；失败返回 null，不编造。
// 作用是让"这篇文章从哪个站来的"可查，同时把 tags 位让给主题标签。
function hostOf(url) {
  try {
    const h = new URL(String(url)).hostname.toLowerCase();
    return h || null;
  } catch {
    return null;
  }
}

function mapRecord(r) {
  const doi = normDoi(r.doiFromUrl || r.doi) || null;
  const title = (r.titleEn || r.titleZh || '').trim();
  if (!title) return { skip: 'no-title' };
  // 实测：镜像站记录的详情页链接在 paperUrl，sourceUrl 常为 null
  const sourceUrl = String(r.paperUrl || r.sourceUrl || '').trim();
  if (!/^https?:\/\//i.test(sourceUrl)) return { skip: 'no-url' };
  const year = Number(r.year);
  if (!Number.isInteger(year) || year < 1900 || year > 2100) return { skip: 'no-year' };

  const id = doi ? sha1(doi) : sha1(normTitle(title));
  const rec = {
    id,
    doi,
    title,
    year,
    journal: (r.source || '').trim() || null,
    // 2026-10-19 E1：此前硬编码 null，导致「摘要已取到但库里没有指针」——
    // 证据表只能停在 pending。改为透传，但仍按 schema 校验形态：
    // abstractHash 必须是 sha256(64 hex)，不合规一律落 null，不写入半截值。
    abstractHash: /^[a-f0-9]{64}$/.test(String(r.abstractHash || '')) ? String(r.abstractHash) : null,
    fulltextPath: typeof r.fulltextPath === 'string' && r.fulltextPath ? r.fulltextPath : null,
    sourceUrl,
    // 2026-10-18 P2-12：来源域名归位到独立字段，不再占用 tags。
    // tags 语义 = 主题标签（如 ["酶制剂","犬"]），导出器**不臆造**——源里没有就留空，
    // 由评审/人工在精读后填；填之前 evidence-link 的分类维度为空是预期行为。
    sourceHost: r.domain ? String(r.domain).trim().toLowerCase() : hostOf(sourceUrl),
    ingestedBy: 'suoyin',
    verifiedAt: null, // 由 merge 填充（首次入库时间）
    tags: Array.isArray(r.tags) ? r.tags.map((t) => String(t).trim()).filter(Boolean) : [],
  };
  // 扩展字段（2026-10-26）：显式映射，形态不合规一律 null，不写半截值。
  // 不再用"透传一切"的写法——那会让来源的任意脏字段混进总线，破坏"输出只含契约字段"。
  const str = (v) => (typeof v === 'string' && v.trim() ? v.trim() : null);
  for (const k of ['titleZh', 'titleZhStatus', 'abstract', 'abstractClean', 'abstractZh', 'abstractZhStatus',
    'oaStatus', 'oaUrl', 'pmcid', 'pmid',
    'abstractLicense', 'abstractRawSha256', 'abstractSource', 'doiSource', 'oaSource', 'language']) {
    rec[k] = str(r[k]);
  }
  rec.isOa = typeof r.isOa === 'boolean' ? r.isOa : null;
  // 读入阶段也必须点名「中间件里有、但没被上面任何映射消费」的键。
  // 只查 order() 不够：中间件的键若在这里就被漏掉，rec 里根本没有它，
  // order() 看不见、告警也不会响 —— 2026-10-26 的 language 就是这样丢的第二次。
  for (const k of Object.keys(r)) if (!CONSUMED_IN.has(k)) DROPPED_KEYS.add(`中间件未消费:${k}`);
  return { rec };
}

function readJsonl(p) {
  const rows = [];
  if (!fs.existsSync(p)) return rows;
  for (const [i, line] of fs.readFileSync(p, 'utf8').split('\n').entries()) {
    const t = line.trim();
    if (!t) continue;
    try {
      rows.push(JSON.parse(t));
    } catch {
      throw new Error(`第 ${i + 1} 行不是合法 JSON：${p}`);
    }
  }
  return rows;
}

function writeJsonl(p, rows) {
  const sorted = [...rows].sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  const body = sorted.map((r) => JSON.stringify(order(r))).join('\n');
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, body ? `${body}\n` : '', 'utf8');
  return sorted.length;
}

function order(r) {
  const o = {};
  // ⚠ 严格白名单：只输出契约字段，非契约字段一律不写（防止来源脏字段污染总线）。
  // 2026-10-26 的事故与这条**不矛盾**：那次丢数据不是"白名单太严"，
  // 而是**白名单没跟上 schema 扩展**（9 个合法字段不在名单里）。
  // 所以修法是补 FIELDS，不是放开透传 —— 别把防线拆了当补丁。
  for (const k of FIELDS) if (k in r) o[k] = r[k];
  // 但"丢弃"必须**说出来**：以前这里静默丢，丢了连日志都没有，只能靠事后逐条比对才发现。
  // 2026-10-26 第二次踩：新加 language / researchNote 两个键又被无声吞掉，
  // 而当时那条「真实库所有键都被 FIELDS 覆盖」的防线仍然全绿 —— 因为被丢的键
  // **从没进过库**，库里当然查不到它。防线的判据边界（查库）就是它的盲区。
  for (const k of Object.keys(r)) if (!(k in o)) DROPPED_KEYS.add(k);
  if (!o.verifiedAt) o.verifiedAt = nowIso();
  return o;
}

/** 本次运行中被白名单丢弃的键名。用 Set 汇总，末尾一次性点名，不逐条刷屏。 */
const DROPPED_KEYS = new Set();
function reportDroppedKeys() {
  if (!DROPPED_KEYS.size) return;
  const names = [...DROPPED_KEYS].sort();
  console.warn(
    `[警告] 以下 ${names.length} 个键不在契约白名单，**已被丢弃**：${names.join(', ')}\n` +
      '         若属合法字段，请补进 FIELDS（不是放开透传）——静默丢弃会让数据悄悄变少。',
  );
}

/** 汇总一次检索的元信息（供 search-log 留痕：换机器也查得到这次怎么检的） */
function buildSearchLog(dir) {
  const keywords = new Set();
  let retrieved = 0;
  for (const d of [dir, path.join(dir, 'raw')]) {
    if (!fs.existsSync(d) || !fs.statSync(d).isDirectory()) continue;
    for (const f of fs.readdirSync(d).sort()) {
      if (!f.endsWith('.json') || SKIP_FILES.has(f)) continue;
      const p = path.join(d, f);
      if (!fs.statSync(p).isFile()) continue;
      const data = JSON.parse(fs.readFileSync(p, 'utf8'));
      if (data.keyword) keywords.add(String(data.keyword));
      if (Array.isArray(data.records)) retrieved += data.records.length;
    }
  }
  let runId = null;
  let limit = null;
  try {
    const s = JSON.parse(fs.readFileSync(path.join(dir, 'summary.json'), 'utf8'));
    runId = s.runId || null;
    limit = s.limit ?? null;
  } catch { /* summary 可选 */ }
  return { runId, at: nowIso(), keywords: [...keywords].sort(), limit, retrieved, sourceDir: dir.replace(/\\/g, '/') };
}

function collect(dir) {
  const out = [];
  const skipped = { 'no-title': 0, 'no-url': 0, 'no-year': 0 };
  // 每关键词记录在 <out>/raw/ 下（实测），同时兼容直接放在 <out>/ 的旧布局
  for (const d of [dir, path.join(dir, 'raw')]) {
    if (!fs.existsSync(d) || !fs.statSync(d).isDirectory()) continue;
    for (const f of fs.readdirSync(d).sort()) {
      if (!f.endsWith('.json') || SKIP_FILES.has(f)) continue;
      const p = path.join(d, f);
      if (!fs.statSync(p).isFile()) continue;
      const data = JSON.parse(fs.readFileSync(p, 'utf8'));
      for (const raw of data.records || []) {
        const m = mapRecord(raw);
        if (m.skip) skipped[m.skip] += 1;
        else out.push(m.rec);
      }
    }
  }
  return { records: out, skipped };
}

// 检索年度下限（2026-10-30 用户规则：论文只检索 2010 年之后的文章）。
// 边界刻意设成「只拦新增、不追改存量」：历史存档不能因为一条新规则被静默抹掉，
// 但 2010 年前的东西**不得再进入**总线成为新证据。
const MIN_YEAR = 2010;

/**
 * 年度闸门。
 * @returns {{kept:Array, rejected:Array, allowed:Array}}
 *
 * 语义（四条，缺一即错）：
 *  ① 只判**新增**（id 不在 existingIds 里）；已在库的老记录原样透传。
 *  ② 只在「年份是整数且 < minYear」时拒；年份缺失/非整数不在本闸门处理
 *     （那是 mapRecord 的 `no-year` 职责，两处都判会double-drop且原因说不清）。
 *  ③ 逃生阀 `allow` 为真时全部放行，但**调用方必须打印放行条数** —— 静默放行
 *     等于没有闸门（同 write 守卫的口径）。
 *  ④ 逐条白名单 `whitelist`（规范 doi 的 Set）：命中即放行，并单独记账。
 *     2026-10-31 加：基石数据（如 1998 猫毛氨基酸组成）无 2010 年后等效替代，
 *     整批 `--allow-pre-2010` 会连带灌入同批无价值旧文 ⇒ 用逐条出口替代整批开关。
 */
/**
 * 读 2010 年前逐条白名单。返回 {set: Set<规范doi>, file}。
 * 解析失败/文件缺失 ⇒ 空白名单（fail-closed：宁可不放行，也不因坏文件整批放开）。
 */
function loadWhitelist(p) {
  if (!p || !fs.existsSync(p)) return { set: new Set(), file: null };
  try {
    const j = JSON.parse(fs.readFileSync(p, 'utf8'));
    const arr = Array.isArray(j) ? j : (j.allow || []);
    const set = new Set(arr.map((x) => normDoi(typeof x === 'string' ? x : x.doi)).filter(Boolean));
    return { set, file: p };
  } catch (e) {
    console.error(`[白名单] 解析失败，按空白名单处理（不放行）：${e.message}`);
    return { set: new Set(), file: null };
  }
}

function filterByYear(incoming, existingIds, minYear, allow, whitelist) {
  const kept = [];
  const rejected = [];
  const allowed = [];
  const wl = whitelist instanceof Set ? whitelist : new Set();
  for (const rec of incoming) {
    const isNew = !existingIds.has(rec.id);
    const y = rec.year;
    if (isNew && Number.isInteger(y) && y < minYear && !allow) {
      const key = normDoi(rec.doi || '');
      if (key && wl.has(key)) { allowed.push(rec); kept.push(rec); continue; }
      rejected.push(rec);
      continue;
    }
    kept.push(rec);
  }
  return { kept, rejected, allowed };
}

function merge(existing, incoming, dryRun) {
  const byId = new Map(existing.map((r) => [r.id, r]));
  // 内容锚索引（2026-11-03 加）：**id 不是内容标识**——同一篇重录会得到新 id，
  // 而 byId.get(新 id) 返回 undefined ⇒ 判成新增 ⇒ 同一篇在库里躺两条。
  // 实测案例：两篇 hjfns 中文综述换 id 重新入库（doi 一字未变），旧 id 记录仍在；
  // 只因后续做过一次全量重建才没变成重复记录。根因就在这一行。
  // 故加二级索引：doi 归一后为主锚；标题归一只在「双方都无 doi」时兜底，
  // 有 doi 的一律只认 doi，避免同名不同文被误并。
  const byDoi = new Map();
  const byTitle = new Map();
  for (const r of existing) {
    const d = normDoi(r.doi);
    if (d && !byDoi.has(d)) byDoi.set(d, r.id);
    const t = normTitle(r.title || '');
    if (t && !byTitle.has(t)) byTitle.set(t, r.id);
  }
  let added = 0;
  let updated = 0;
  let reinduce = 0;
  for (const rec of incoming) {
    let anchor = rec.id;
    if (!byId.has(anchor)) {
      const d = normDoi(rec.doi);
      const t = normTitle(rec.title || '');
      if (d && byDoi.has(d)) {
        anchor = byDoi.get(d); // 同一篇：doi 相同而 id 不同 ⇒ 复用存量 id
        reinduce += 1;
      } else if (!d && t && byTitle.has(t)) {
        anchor = byTitle.get(t); // 双方都无 doi 才按标题兜底
        reinduce += 1;
      }
    }
    const old = byId.get(anchor);
    if (!old) {
      byId.set(anchor, { ...rec, id: anchor, verifiedAt: rec.verifiedAt || nowIso() });
      const d0 = normDoi(rec.doi);
      if (d0) byDoi.set(d0, anchor);
      const t0 = normTitle(rec.title || '');
      if (t0) byTitle.set(t0, anchor);
      added += 1;
      continue;
    }
    const next = { ...old };
    for (const k of ['doi', 'title', 'year', 'sourceUrl', 'sourceHost', 'abstractHash', 'fulltextPath']) {
      if (rec[k] !== undefined && JSON.stringify(rec[k]) !== JSON.stringify(old[k])) next[k] = rec[k];
    }
    // journal 单独处理（2026-10-31）：候选件里 `source` 常常为空（如白名单手工注入件），
    // 若按上面的「不同就覆盖」规则，会把总线侧已回填的规范期刊名**擦成 null**。
    // 实测踩到：de98966c / 8486881b 回填的 Journal of Heredity / JSAP 会被清空，
    // 重推 vault 后笔记又变空壳。语义与 tags 一致：源里没有就保留已有，不臆造也不擦除。
    if (typeof rec.journal === 'string' && rec.journal.trim()) next.journal = rec.journal.trim();
    // tags 特殊处理（2026-10-18 P2-12）：源里没有主题标签时**不得清空**已有标签。
    // 否则每次重跑导出都会把人工/评审填的主题标签洗掉——这是幂等性陷阱。
    if (Array.isArray(rec.tags) && rec.tags.length > 0) next.tags = rec.tags;
    next.verifiedAt = old.verifiedAt || nowIso();
    byId.set(anchor, next);
    updated += 1;
  }
  return { rows: [...byId.values()], added, updated, reinduce };
}

function selftest() {
  const cases = [];
  const t = (label, cond) => cases.push([label, cond]);

  const a = mapRecord({ titleEn: 'Effect of X on dogs', year: 2024, sourceUrl: 'https://doi.org/10.1/abc', doiFromUrl: '10.1/ABC', source: 'J Anim Sci', domain: 'nutrition' });
  t('合法记录应映射成功', !a.skip && /^[a-f0-9]{40}$/.test(a.rec.id));
  // 2026-10-19 E1：abstractHash 透传的两条判据（此前恒为 null，没有牙齿）
  const H = 'a'.repeat(64);
  const withHash = mapRecord({ titleEn: 'Hairball in cats', year: 2025, sourceUrl: 'https://doi.org/10.1/x', doi: '10.1/x', abstractHash: H });
  t('abstractHash 合法时应透传', !withHash.skip && withHash.rec.abstractHash === H);
  const badHash = mapRecord({ titleEn: 'Hairball in cats', year: 2025, sourceUrl: 'https://doi.org/10.1/x', doi: '10.1/x', abstractHash: 'abc' });
  t('abstractHash 非法时应落 null（不写半截值）', !badHash.skip && badHash.rec.abstractHash === null);
  t('doi 大小写归一同 id', a.rec.id === sha1('10.1/abc'));
  // 2026-10-31：URL 形态与纯 DOI 形态必须收敛到同一 id，否则同一文献会入两条。
  const urlDoi = mapRecord({ titleEn: 'Effect of X on dogs', year: 2024, sourceUrl: 'https://doi.org/10.1/abc', doiFromUrl: 'https://doi.org/10.1/ABC', source: 'J' });
  t('doi 带 URL 前缀与纯 DOI 同 id', urlDoi.rec.id === a.rec.id);
  t('doi 去前缀后字段干净', urlDoi.rec.doi === '10.1/abc');
  t('doi 双重前缀也能剥净', normDoi('doi:https://dx.doi.org/10.1/ABC/') === '10.1/abc');
  t('无 doi 用规范化标题', mapRecord({ titleZh: '酶制剂对犬消化的影响', year: 2024, sourceUrl: 'https://x.org/a' }).rec.id === sha1(normTitle('酶制剂对犬消化的影响')));
  t('全角/空格归一后同 id', mapRecord({ titleEn: 'Ａ  B', year: 2024, sourceUrl: 'https://x.org/a' }).rec.id === mapRecord({ titleEn: 'a b', year: 2024, sourceUrl: 'https://x.org/b' }).rec.id);
  t('缺 URL 必须跳过', mapRecord({ titleEn: 'x', year: 2024 }).skip === 'no-url');
  t('paperUrl 可作 sourceUrl 兜底（实测布局）',
    mapRecord({ titleEn: 'x', year: 2024, paperUrl: 'https://kuluer.com/paper/abc' }).rec.sourceUrl === 'https://kuluer.com/paper/abc');
  t('缺年份必须跳过', mapRecord({ titleEn: 'x', sourceUrl: 'https://x.org' }).skip === 'no-year');
  t('缺标题必须跳过', mapRecord({ year: 2024, sourceUrl: 'https://x.org' }).skip === 'no-title');

  const base = { ...a.rec, verifiedAt: '2020-01-01T00:00:00Z' };
  const m1 = merge([base], [{ ...a.rec, title: 'New title' }], true);
  t('同 id 视为更新而非新增', m1.added === 0 && m1.updated === 1);
  t('更新保留首次 verifiedAt', m1.rows[0].verifiedAt === '2020-01-01T00:00:00Z');
  t('可变字段被更新', m1.rows[0].title === 'New title');
  // 2026-11-03 改：原断言是「新 id 计为新增」，它把「id 变了就是新文献」当成了公理——
  // 而那正是重复入库的根因。现在按内容锚判定，拆成三条：
  const sameDoi = merge([base], [{ ...a.rec, id: sha1('other') }], true);
  t('同 doi 换 id 复用存量 id（不新增）',
    sameDoi.added === 0 && sameDoi.reinduce === 1 && sameDoi.rows.length === 1 && sameDoi.rows[0].id === base.id);
  const otherDoi = merge([base], [{ ...a.rec, id: sha1('other2'), doi: '10.9/zzz', title: 'zzz' }], true);
  t('doi 与标题都不同才计新增', otherDoi.added === 1 && otherDoi.reinduce === 0 && otherDoi.rows.length === 2);
  const noTitle = '酶制剂对犬消化的影响';
  const noDoiBase = { ...base, doi: null, title: noTitle, id: sha1(normTitle(noTitle)) };
  const noDoiRec = { ...a.rec, doi: null, id: sha1('another'), title: noTitle };
  const noDoiM = merge([noDoiBase], [noDoiRec], true);
  t('双方无 doi 时按标题兜底复用', noDoiM.added === 0 && noDoiM.reinduce === 1 && noDoiM.rows.length === 1);
  const mixedM = merge([noDoiBase], [{ ...a.rec, id: sha1('mixed'), doi: '10.9/mixed', title: noTitle }], true);
  t('一方有 doi 时不按标题误并', mixedM.added === 1 && mixedM.reinduce === 0 && mixedM.rows.length === 2);

  // ── 2026-10-30 用户规则：论文只收 2010 年及以后 ──
  // 四条判据互相咬合：只拦新增 / 边界含等号 / 存量透传 / 逃生阀有效。
  // 缺任一条都会出事：只判年份不看新增 ⇒ 每次全量重导都把 7 条历史记录判成违规；
  // 边界写成 `<` 或 `<=` 差一 ⇒ 2010 年的文献被误拒（那是本规则的起点年）。
  const yNew = (y) => ({ ...a.rec, id: sha1('y' + y), year: y });
  const roomEmpty = new Set();
  t('新增 2009 年必须被拒', filterByYear([yNew(2009)], roomEmpty, MIN_YEAR, false).rejected.length === 1);
  // 2026-10-31 逐条白名单：命中放行、未命中仍拒（并按 doi 匹配，不看 id）
  const wlSet = new Set(['10.1/wl']);
  t('白名单命中放行 pre-2010', filterByYear([{ ...yNew(2009), doi: '10.1/wl' }], roomEmpty, MIN_YEAR, false, wlSet).allowed.length === 1);
  t('白名单外仍拒', filterByYear([{ ...yNew(2009), doi: '10.1/other' }], roomEmpty, MIN_YEAR, false, wlSet).rejected.length === 1);
  t('白名单缺文件不影响常规放行', filterByYear([yNew(2024)], roomEmpty, MIN_YEAR, false, new Set()).kept.length === 1);
  t('新增 2010 年（边界年）必须放行', filterByYear([yNew(2010)], roomEmpty, MIN_YEAR, false).kept.length === 1);
  t('新增 2024 年放行', filterByYear([yNew(2024)], roomEmpty, MIN_YEAR, false).kept.length === 1);
  const legacy = yNew(2005);
  t('存量记录（id 已在库）即使 2005 年也透传，不被新规则追溯删除',
    filterByYear([legacy], new Set([legacy.id]), MIN_YEAR, false).kept.length === 1);
  t('逃生阀 allow=true 时 2009 年放行（由调用方打印放行条数）',
    filterByYear([yNew(2009)], roomEmpty, MIN_YEAR, true).kept.length === 1);
  t('年份非整数不在本闸门处理（交给 mapRecord 的 no-year）',
    filterByYear([{ ...a.rec, id: sha1('yx'), year: null }], roomEmpty, MIN_YEAR, false).rejected.length === 0);

  t('输出只含契约字段', Object.keys(order(a.rec)).every((k) => FIELDS.includes(k)));

  // ── 2026-10-18 P2-12：tags 语义从"域名"改为"主题标签" ──
  t('域名不再写进 tags（旧行为已废止）', Array.isArray(a.rec.tags) && a.rec.tags.length === 0);
  t('域名归位到 sourceHost', a.rec.sourceHost === 'nutrition');
  t('无 domain 时从 URL 兜底取 host 且小写',
    mapRecord({ titleEn: 'x', year: 2024, sourceUrl: 'https://Kuluer.com/p/1' }).rec.sourceHost === 'kuluer.com');
  t('URL 残缺（https://，正则能过但 new URL 抛错）时 sourceHost 为 null（不编造）',
    mapRecord({ titleEn: 'x', year: 2024, sourceUrl: 'https://' }).rec.sourceHost === null);
  t('源里带主题标签时原样保留',
    mapRecord({ titleEn: 'x', year: 2024, sourceUrl: 'https://x.org/a', tags: [' 酶制剂 ', '犬'] }).rec.tags.join('|') === '酶制剂|犬');

  // 幂等性陷阱：重跑导出不得洗掉人工/评审填的主题标签
  const tagged = { ...base, tags: ['酶制剂', '犬'], sourceHost: 'old.host' };
  const m2 = merge([tagged], [{ ...a.rec, tags: [], sourceHost: 'new.host' }], true);
  t('重跑导出不清空已有主题标签', JSON.stringify(m2.rows[0].tags) === JSON.stringify(['酶制剂', '犬']));
  t('sourceHost 仍可被更新', m2.rows[0].sourceHost === 'new.host');
  const m3 = merge([tagged], [{ ...a.rec, tags: ['益生菌'] }], true);
  t('源提供新标签时覆盖', JSON.stringify(m3.rows[0].tags) === JSON.stringify(['益生菌']));

  // 同类幂等性陷阱（2026-10-31 实测踩到）：候选件 source 为空 ⇒ journal 为 null，
  // 旧规则会把总线已回填的规范期刊名擦掉（de98966c / 8486881b 实证）。
  const jrOld = { ...base, journal: 'Journal of Heredity' };
  const m4 = merge([jrOld], [{ ...a.rec, journal: null }], true);
  t('候选件 journal 为空时不清空已有期刊名', m4.rows[0].journal === 'Journal of Heredity');
  const m5 = merge([jrOld], [{ ...a.rec, journal: 'J Hered' }], true);
  t('候选件提供新期刊名时覆盖', m5.rows[0].journal === 'J Hered');
  const m6 = merge([{ ...base, journal: null }], [{ ...a.rec, journal: 'J Hered' }], true);
  t('总线为空时可被候选件补上期刊名', m6.rows[0].journal === 'J Hered');

  const dir = fs.mkdtempSync(path.join(process.env.TEMP || '/tmp', 'bus-exp-'));
  const rawA = { titleEn: 'Effect of X on dogs', year: 2024, sourceUrl: 'https://doi.org/10.1/abc', doiFromUrl: '10.1/ABC', source: 'J Anim Sci' };
  fs.writeFileSync(path.join(dir, 'kw1.json'), JSON.stringify({ records: [rawA, { titleEn: 'bad', year: 2024 }] }));
  fs.writeFileSync(path.join(dir, 'summary.json'), JSON.stringify({ records: [rawA] }));
  fs.writeFileSync(path.join(dir, 'prisma.json'), JSON.stringify({ records: [rawA] }));
  const col = collect(dir);
  t('只读检索文件、跳过 summary/prisma', col.records.length === 1 && col.skipped['no-url'] === 1);

  // 实测布局：每关键词记录在 <out>/raw/ 下
  const d2 = fs.mkdtempSync(path.join(process.env.TEMP || '/tmp', 'bus-exp-raw-'));
  fs.mkdirSync(path.join(d2, 'raw'));
  fs.writeFileSync(path.join(d2, 'raw', '01-kw.json'), JSON.stringify({ keyword: 'kw-test', records: [rawA] }));
  fs.writeFileSync(path.join(d2, 'summary.json'), JSON.stringify({ count: 1 }));
  const col2 = collect(d2);
  t('raw/ 子目录下的记录必须被读到', col2.records.length === 1 && col2.skipped['no-url'] === 0);

  const lg = buildSearchLog(d2);
  t('检索日志取到关键词与检索条数', lg.keywords.length === 1 && lg.retrieved === 1);
  t('检索日志路径统一正斜杠', !lg.sourceDir.includes('\\'));

  // —— 扩展字段必须在契约白名单内（2026-10-26 事故的回归防线）——
  // 事故形态：文献库 schema 扩到 26 字段，FIELDS 还停在 12 ⇒ 每跑一次静默裁掉 14 字段，
  // 而 --check 与 selftest 全绿（它们只查必填字段在不在，不查"该在的还在不在"）。
  const EXT = ['titleZh', 'titleZhStatus', 'abstract', 'abstractClean', 'isOa', 'oaStatus', 'oaUrl', 'pmcid', 'pmid',
    'abstractLicense', 'abstractRawSha256', 'abstractSource', 'doiSource', 'oaSource'];
  t('FIELDS 覆盖全部扩展字段', EXT.every((k) => FIELDS.includes(k)));
  // 硬防线：直接拿真实库的键与 FIELDS 取差集。**不依赖我手抄的 EXT 列表**——
  // 手抄列表本身就会过期，这正是事故的成因。库不在（换机器）时跳过，不误报。
  const realOut = DEFAULT_OUT;
  if (fs.existsSync(realOut)) {
    const keys = new Set();
    for (const line of fs.readFileSync(realOut, 'utf8').split('\n')) {
      if (!line.trim()) continue;
      try { for (const k of Object.keys(JSON.parse(line))) keys.add(k); } catch { /* 坏行忽略 */ }
    }
    const uncovered = [...keys].filter((k) => !FIELDS.includes(k));
    t(`真实库的所有键都被 FIELDS 覆盖（差集：${uncovered.join(',') || '空'}）`, uncovered.length === 0);
  }
  const richOld = { id: 'x1', doi: '10.1/x', title: 'T', year: 2020, sourceUrl: 'https://doi.org/10.1/x',
    verifiedAt: '2020-01-01T00:00:00.000Z', tags: ['排毛'],
    abstract: '摘要正文不该被丢弃', titleZh: '中文题名', pmid: '123', oaStatus: 'green' };
  const ordered = order(richOld);
  t('order 保留扩展字段', ordered.abstract === '摘要正文不该被丢弃' && ordered.titleZh === '中文题名');
  t('order 保留 pmid 与 oaStatus', ordered.pmid === '123' && ordered.oaStatus === 'green');
  t('order 仍把 id 排在首位', Object.keys(ordered)[0] === 'id');
  // 反向：非契约字段必须被拦住（"输出只含契约字段"这条红线不能被本次修复顺手拆掉）
  t('order 拒写非契约字段', !('journalInfo' in order({ ...richOld, journalInfo: { x: 1 } })));
  // 但"拦住"必须留下痕迹：丢弃的键名要能查出来，否则就是静默丢数据。
  // 这一条是 2026-10-26 第二次踩坑后加的：当时「真实库所有键都被 FIELDS 覆盖」全绿，
  // 而 language / researchNote 正被动静悄悄地裁掉 —— 因为被裁的键从没进过库，库里查不到。
  // ⇒ 判据必须放在「进库之前」的路径上，不能只查「库里现在有什么」。
  DROPPED_KEYS.clear();
  order({ ...richOld, 未登记字段A: 1, 未登记字段B: 2 });
  t('order 记录被丢弃的未知键（不静默）', DROPPED_KEYS.has('未登记字段A') && DROPPED_KEYS.has('未登记字段B'));
  t('order 已知字段不误报为丢弃', !DROPPED_KEYS.has('abstract') && !DROPPED_KEYS.has('verifiedAt'));
  // 读入侧的同类断言：中间件里有、但 mapRecord 没消费的键，同样必须点名。
  // 这是第二次踩坑的那一层 —— 只查 order() 查不到它，因为 rec 里根本没这个键。
  DROPPED_KEYS.clear();
  mapRecord({ doi: '10.1/x', titleEn: 'T', year: 2020, sourceUrl: 'https://doi.org/10.1/x', 中间件独有字段: 'z' });
  t('mapRecord 记录未消费的中间件键', DROPPED_KEYS.has('中间件未消费:中间件独有字段'));
  t('mapRecord 不误报已消费键', !DROPPED_KEYS.has('中间件未消费:doi') && !DROPPED_KEYS.has('中间件未消费:titleEn'));
  DROPPED_KEYS.clear();

  // —— 读入阶段：扩展字段必须被 mapRecord 显式映射（否则修了 order 也没用）——
  const richIn = { doi: '10.1/x', title: 'T', year: 2020, sourceUrl: 'https://doi.org/10.1/x',
    abstractHash: 'a'.repeat(64), abstract: '摘要正文', titleZh: '中文题名', pmid: '999', oaStatus: 'green',
    isOa: true, journalInfo: { journal: { title: '嵌套不该透传' } } };
  const richRec = mapRecord(richIn).rec;
  t('mapRecord 映射 abstract 与 titleZh', richRec.abstract === '摘要正文' && richRec.titleZh === '中文题名');
  t('mapRecord 映射 pmid/oaStatus/isOa', richRec.pmid === '999' && richRec.oaStatus === 'green' && richRec.isOa === true);
  t('mapRecord 不透传嵌套对象', richRec.journalInfo === undefined);
  t('mapRecord 形态不合规落 null', mapRecord({ ...richIn, isOa: 'yes' }).rec.isOa === null);

  fs.rmSync(d2, { recursive: true, force: true });
  fs.rmSync(dir, { recursive: true, force: true });

  const bad = cases.filter(([, c]) => !c);
  for (const [label] of bad) console.error(`  FAIL ${label}`);
  console.log(`selftest: ${bad.length ? 'FAIL' : 'PASS'}（${cases.length - bad.length}/${cases.length}）`);
  return bad.length ? 1 : 0;
}

function parseArg(name, dflt) {
  const i = process.argv.indexOf(name);
  return i > 0 && process.argv[i + 1] ? process.argv[i + 1] : dflt;
}

/** `--min-year` 解析：非法/缺失一律回落到 MIN_YEAR（宁可严，不静默放宽）。 */
function clampMinYear(raw) {
  const n = Number(raw);
  return Number.isInteger(n) && n > 1900 && n < 2100 ? n : MIN_YEAR;
}

function main() {
  if (process.argv.includes('--selftest')) return selftest();
  const out = parseArg('--out', DEFAULT_OUT);

  if (process.argv.includes('--check')) {
    let rows;
    try {
      rows = readJsonl(out);
    } catch (e) {
      console.error(`[不合格] ${e.message}`);
      return 1;
    }
    const bad = rows.filter((r) => !/^[a-f0-9]{40}$/.test(r.id) || !r.title || !r.sourceUrl || !r.verifiedAt);
    if (bad.length) {
      console.error(`[不合格] ${bad.length} 条缺必填或 id 非 sha1`);
      return 1;
    }

    // 白名单差集（2026-11-03 加）：库里出现过的键必须全在 FIELDS 里。
    // 这条与 selftest 里那条同名判据的区别：selftest 要人手动跑，--check 是闸门在跑。
    // 同一个事故已发生三次（10-26 language / 10-31 abstractZh / 11-03 id 锚），
    // 前两次都只补了白名单、没把判据挪进闸门，于是第三次照旧。
    const unknownKeys = new Set();
    for (const r of rows) for (const k of Object.keys(r)) if (!FIELDS.includes(k)) unknownKeys.add(k);
    if (unknownKeys.size) {
      console.error(`[不合格] ${unknownKeys.size} 个字段不在 FIELDS 白名单，跑一次导出就会被 order() 裁掉：`);
      for (const k of [...unknownKeys].sort()) {
        const n = rows.filter((r) => k in r).length;
        console.error(`  - ${k}（${n} 条有值）`);
      }
      return 1;
    }

    // id 唯一（2026-11-03：从「只打印」改为判红）。重复入库是本域最贵的错误：
    // 同一篇文献两条记录，下游按 id 取数会拿到两份互相矛盾的判定。
    const idCount = new Map();
    for (const r of rows) idCount.set(r.id, (idCount.get(r.id) || 0) + 1);
    const dupIds = [...idCount].filter(([, n]) => n > 1);
    if (dupIds.length) {
      console.error(`[不合格] ${dupIds.length} 个 id 重复（同一篇文献入库两次）：`);
      for (const [id, n] of dupIds.slice(0, 5)) console.error(`  - ${id} × ${n}`);
      return 1;
    }

    // 锚一致性探针（2026-10-31 加；2026-11-03 修两处 bug）。
    // bug 1：原判据用 sha1(r.doi) 而非 sha1(normDoi(r.doi))，而 id 是用 normDoi 算的
    //        ⇒ 大写 DOI（如 10.1177/1098612X251314769）被误报失配。实测 3 条红里有 1 条是假红。
    //        判据与被判对象必须用同一个归一化，否则「报红」本身就是脏数据。
    // bug 2：原判据对所有有 doi 的记录一律要求 id === sha1(doi)，但库里有 2 条中文期刊记录
    //        是「先按标题建锚、事后补 doi」，属历史遗留，重算 id 会打断所有下游引用。
    //        故给它们一个显式状态 legacy_unresolved_anchor：可见、可计数、不可新增。
    const LEGACY_ANCHOR = 'legacy_unresolved_anchor';
    const legacyRows = rows.filter((r) => r.idStatus === LEGACY_ANCHOR);
    const misanchored = rows.filter((r) => {
      if (r.idStatus === LEGACY_ANCHOR) return false;
      if (!r.doi) return false;
      return r.id !== sha1(normDoi(r.doi));
    });
    if (misanchored.length) {
      console.error(`[不合格] ${misanchored.length} 条 id 与 doi 不对应（锚失配）：`);
      for (const r of misanchored.slice(0, 5)) {
        console.error(`  - ${r.id}  doi=${r.doi}  应为 ${sha1(normDoi(r.doi)).slice(0, 12)}  ${String(r.title).slice(0, 50)}`);
      }
      console.error(`  修复：重算 id（会断下游引用，需先审计引用面）或标 idStatus=${LEGACY_ANCHOR}（存量豁免，仅限历史记录）`);
      return 1;
    }
    if (legacyRows.length) {
      console.log(`[提示] ${legacyRows.length} 条标 ${LEGACY_ANCHOR}：id 锚在标题上、doi 为后补，id 与 doi 不互证。`);
      console.log(`       这些条目的 id 不可用于跨库交叉引用，只能在本库内使用。`);
    }
    console.log(`[合格] ${rows.length} 条，id 唯一 ${new Set(rows.map((r) => r.id)).size === rows.length}`);
    // 存量体检（不判红）：2010 年前记录属历史存档，允许存在，但要能一眼看到有多少。
    const pre = rows.filter((r) => Number.isInteger(r.year) && r.year < MIN_YEAR);
    if (pre.length) console.log(`[提示] 其中 ${pre.length} 条为 ${MIN_YEAR} 年前的历史记录（不再新增，存量保留）：${pre.map((r) => r.year).sort().join('/')}`);
    return 0;
  }

  const dir = parseArg('--dir', '');
  if (!dir || !fs.existsSync(dir)) {
    console.error(`[不可用] 检索输出目录不存在：${dir || '(未提供 --dir)'}`);
    return 2;
  }
  const { records, skipped } = collect(dir);
  const existing = readJsonl(out);

  // —— 年度闸门（2026-10-30）：新记录年份必须 ≥ minYear ——
  const minYear = clampMinYear(parseArg('--min-year', String(MIN_YEAR)));
  const allowPre = process.argv.includes('--allow-pre-2010');
  const wl = loadWhitelist(parseArg('--whitelist', DEFAULT_WHITELIST));
  const { kept, rejected, allowed } = filterByYear(records, new Set(existing.map((r) => r.id)), minYear, allowPre, wl.set);
  // 放行必须记账（静默放行 = 没有闸门）：命中白名单的 pre-2010 记录逐条打印。
  if (allowed.length) {
    console.log(`[白名单] 放行 ${allowed.length} 条 2010 年前记录（来源 ${wl.file}）：`);
    for (const r of allowed) console.log(`    ${r.year} ${r.doi} ${String(r.title || '').slice(0, 56)}`);
  }
  if (rejected.length) {
    const head = rejected.slice(0, 10).map((r) => `    ${r.year} ${r.id.slice(0, 10)} ${String(r.title || '').slice(0, 60)}`);
    console.error(`[年度闸门] 拒绝 ${rejected.length} 条新增记录（year < ${minYear}）：`);
    for (const line of head) console.error(line);
    if (rejected.length > head.length) console.error(`    …另有 ${rejected.length - head.length} 条`);
    console.error('  依据：用户规则「论文只检索 2010 年之后的文章」。确需收录请加 --allow-pre-2010（会显式记账）。');
  }

  const { rows, added, updated } = merge(existing, kept, process.argv.includes('--dry-run'));

  if (process.argv.includes('--dry-run')) {
    console.log(`[dry-run] 现有 ${existing.length} → 合并后 ${rows.length}（新增 ${added}，更新 ${updated}），跳过 ${JSON.stringify(skipped)}${rejected.length ? `，年度闸门拒绝 ${rejected.length}` : ''}`);
    return rejected.length ? 4 : 0;
  }
  if (rejected.length) return 4; // fail-closed：有被拒记录时**不写盘**，避免「写一半」状态
  const n = writeJsonl(out, rows);
  let logNote = '';
  if (!process.argv.includes('--no-log')) {
    const entry = { ...buildSearchLog(dir), added, updated, total: n };
    fs.appendFileSync(path.join(path.dirname(out), 'search-log.jsonl'), `${JSON.stringify(entry)}\n`, 'utf8');
    logNote = '｜检索日志已记入 search-log.jsonl';
  }
  console.log(`[已写入] ${out}：${n} 条（新增 ${added}，更新 ${updated}），跳过 ${JSON.stringify(skipped)}${logNote}`);
  reportDroppedKeys();
  return 0;
}

process.exitCode = main();
