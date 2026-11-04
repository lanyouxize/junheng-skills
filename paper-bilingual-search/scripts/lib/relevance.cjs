'use strict';
/**
 * lib/relevance.cjs — 主题相关性打分与排序（纯函数，零网络）
 *
 * 解决的问题：站点检索引擎为**宽匹配** —— 布尔约束力弱，连 AND 都被稀释。
 *   实测（2026-10-16）`(犬 OR 猫 OR 伴侣动物) AND (毛球 OR 毛球症 OR 化毛)` 自报 7 条，
 *   取回的首条却是「哺乳动物**毛球**（毛囊球部）生长调控」⇒ 字符串命中等同歧义命中。
 *   ⇒ 检索后**必须**做一次本地相关性过滤，人才能只看前 N 条。
 *
 * 与 lib/evidence.cjs 的分工（正交，互不替代）：
 *   evidence.cjs  = 「这条研究的**设计**值几分证据」（A–D 分级）
 *   relevance.cjs = 「这条**是不是我要的主题**」（exact / near / off 分档）
 *   一条记录可以「设计很好但跑题」，也可以「完全切题但只是综述」——两个维度必须分开表达。
 *
 * 设计约束（均来自实测教训）：
 *   1. 零站点请求：只做字符串匹配，不联网、不读站点；
 *   2. **字段名不可信**：站点是中英双语库，`titleEn` 实际可能装的是中文标题
 *      ⇒ 题名一律取 `titleEn + titleZh` 合并文本，**不按字段名分语言**；
 *   3. 不静默降级：排除词命中 ⇒ **显式**标记 `excluded: true` 并降到 off 档，
 *      命中上下文仍留在产物里供人工复核（绝不能悄悄丢掉一条记录）。
 */

const VERSION = 'relevance-ranking/v2';   // v2：词形边界自动归一（破折号族 / 繁简 / 连写分写）

/**
 * 权重。题名的判别力远高于站点摘要片段（站点常只给 100~200 字 snippet），
 * 因此题名权重为主题词的 3 倍；相邻词只做「弱信号」，不足以单独判定主题命中。
 */
const W = Object.freeze({
  title: 3,          // 主题词命中题名
  abstract: 1,       // 主题词命中摘要
  titleNear: 1,      // 相邻词命中题名
  abstractNear: 0.5, // 相邻词命中摘要
  exclude: -6,       // 排除词命中（每处），并触发一票否决
});

const LEVEL_LABEL = Object.freeze({
  exact: '主题命中',
  near: '相邻主题',
  off: '跑题/待人工',
});

const LEVEL_RANK = Object.freeze({ exact: 2, near: 1, off: 0 });

const SPLIT_RE = /[,，;；|、]/;

/**
 * ── v4.7 挂账 · 词形边界自动归一（2026-10-16 一手实测三类漏判）──
 * 三类「同义异形」曾让真相关记录被判「跑题」，本层机械消除：
 *   ① 破折号族 ↔ 空格：`gut–kidney`（en-dash）与词表 `gut kidney` 不同形 ⇒ 漏判；
 *   ② 繁 ↔ 简：`腎臟` 与词表 `肾脏` 不同形 ⇒ **整条猫 CKD 干预研究被判跑题**（后果最重）；
 *   ③ 连写 ↔ 分写：`hair ball` 与词表 `hairball` 不同形 ⇒ 漏判。
 * 判据（可证伪）：归一化后**两侧同时**剥掉「空白 + 破折号族」再匹配 ⇒ 三类差异自然等价。
 * 已知边界（如实登记，不掩饰）：压缩匹配会让「跨词边界的偶然拼接」也命中（如词表
 * `cat dog` 命中 `concatdog`）。代价可接受 —— 只新增「形态差异」类命中，不发散到无关
 * 主题；且排除词与人工核读（snippet 保留**原文**）是最后一道闸。
 */
// 破折号族（十进制码点，避免源码里出现不可见字符）：hyphen / soft hyphen /
// U+2010..U+2015（hyphen…horizontal bar）/ minus / hyphen bullet / 小型与全角形。
const DASH_SET = new Set([45, 173, 8208, 8209, 8210, 8211, 8212, 8213, 8722, 8259, 65112, 65123, 65293]
  .map(n => String.fromCharCode(n)));

/**
 * 繁 → 简 单字映射（**限域**：仅覆盖宠物营养 / 兽医临床 / 科研文献高频字）。
 * 三条硬约束：① **1:1 且等长** —— `compactWithMap` 的索引映射依赖「归一后字符数不变」；
 * ② 键与值必须互异（恒等映射一律省略，由单测守卫）；③ 表外字仍可能漏 ⇒ SKILL.md 的
 * 「词表人工列多形态」保留为兜底，二者**叠加而非替代**。
 */
const SIMPLIFY_MAP = Object.freeze({
  // 器官 / 解剖
  '腎': '肾', '臟': '脏', '腸': '肠', '腦': '脑', '膽': '胆', '膚': '肤', '髮': '发', '頸': '颈',
  // 泌尿 / 肾 / 循环
  '濾': '滤', '濃': '浓', '縮': '缩', '壓': '压', '張': '张', '過': '过', '穩': '稳',
  // 疾病 / 临床
  '腫': '肿', '癥': '症', '診': '诊', '斷': '断', '療': '疗', '藥': '药', '劑': '剂',
  '緩': '缓', '減': '减', '輕': '轻', '顯': '显', '癒': '愈', '敗': '败', '徵': '征',
  '瀉': '泻', '嘔': '呕', '慾': '欲', '飲': '饮', '餵': '喂',
  // 营养 / 成分
  '營': '营', '養': '养', '飼': '饲', '糧': '粮', '維': '维', '礦': '矿', '質': '质',
  '醣': '糖', '澱': '淀', '纖': '纤', '熱': '热', '謝': '谢', '發': '发', '複': '复',
  '飽': '饱', '鹽': '盐', '鹼': '碱', '鑑': '鉴', '攝': '摄',
  // 研究 / 方法 / 统计
  '實': '实', '檢': '检', '驗': '验', '測': '测', '試': '试', '觀': '观', '數': '数',
  '據': '据', '樣': '样', '組': '组', '計': '计', '統': '统', '學': '学', '應': '应',
  '綜': '综', '論': '论', '結': '结', '證': '证', '獻': '献', '報': '报', '評': '评',
  '價': '价', '標': '标', '準': '准', '規': '规', '範': '范', '異': '异', '較': '较',
  '機': '机', '關': '关', '係': '系', '繫': '系', '響': '响', '監': '监', '護': '护',
  '臨': '临', '預': '预', '併': '并', '誘': '诱', '導': '导', '趨': '趋', '勢': '势',
  '態': '态', '調': '调', '節': '节', '參': '参', '議': '议',
  // 关联 / 数量 / 形态
  '與': '与', '為': '为', '並': '并', '該': '该', '這': '这', '個': '个', '們': '们',
  '時': '时', '間': '间', '週': '周', '隻': '只', '條': '条', '種': '种', '類': '类',
  '級': '级', '階': '阶', '層': '层', '內': '内', '後': '后', '終': '终', '開': '开',
  '變': '变', '長': '长', '歲': '岁', '齡': '龄', '體': '体', '陽': '阳', '陰': '阴',
  '續': '续',
  // 微生物 / 物种 / 骨架
  '桿': '杆', '於': '于', '動': '动', '簡': '简', '貓': '猫', '豬': '猪', '雞': '鸡',
  '鴨': '鸭', '馬': '马', '餘': '余', '輔': '辅',
  // 器械 / 专业高频
  '鏈': '链', '軸': '轴', '鈣': '钙', '鉀': '钾', '鈉': '钠', '鎂': '镁', '鋅': '锌',
  '鐵': '铁', '銅': '铜', '細': '细', '狀': '状',
});

/** CJK 统一表意文字（U+4E00–U+9FFF）判定 —— 避免在源码里写易错的范围字面量。 */
function isCJK(ch) {
  const c = ch.charCodeAt(0);
  return c >= 0x4E00 && c <= 0x9FFF;
}

/** 繁 → 简（单字 1:1，长度不变；表外字原样返回）。 */
function toSimplified(s) {
  let out = '';
  for (const ch of String(s == null ? '' : s)) out += isCJK(ch) ? (SIMPLIFY_MAP[ch] || ch) : ch;
  return out;
}

/** 装饰性字符：空白（含 Unicode 全角空格）+ 破折号族 —— 归一化时一律剥离。 */
function isDecor(ch) {
  return ch.trim() === '' || DASH_SET.has(ch);
}

/** 匹配键：归一化 → 剥装饰 ⇒ 三类形态差异在此塌成同一形态。 */
function compactKey(s) {
  let out = '';
  for (const ch of toSimplified(normalizeTerm(s))) if (!isDecor(ch)) out += ch;
  return out;
}

/**
 * 压缩文本 + **索引映射**（`map[i]` = 压缩后第 i 字符在原文中的下标）。
 * 等长归一化（小写 + 1:1 繁简）保证映射有效 ⇒ snippet 可回映**原文形态**。
 */
function compactWithMap(text) {
  const raw = String(text == null ? '' : text);
  const norm = toSimplified(raw.toLowerCase());
  let out = '';
  const map = [];
  for (let i = 0; i < norm.length; i++) {
    const ch = norm[i];
    if (isDecor(ch)) continue;
    out += ch;
    map.push(i);
  }
  return { text: out, map, src: raw };
}

/** 命中上下文：压缩坐标回映原文，展示**原文**（保留 dash / 大写 / 繁体原貌）。 */
function snippetFromCompact(c, key, len) {
  const L = len || 40;
  const p = c.text.indexOf(key);
  if (p < 0) return '';
  const s = c.map[p];
  const e = c.map[p + key.length - 1] + 1;
  const pad = Math.max(0, Math.floor((L - (e - s)) / 2));
  const start = Math.max(0, s - pad);
  const end = Math.min(c.src.length, e + pad);
  return (start > 0 ? '…' : '') + c.src.slice(start, end) + (end < c.src.length ? '…' : '');
}

/** 术语归一化：小写 + 折叠空白（中文不受影响）。英文大小写差异在题名里很常见。 */
function normalizeTerm(s) {
  return String(s == null ? '' : s).toLowerCase().replace(/\s+/g, ' ').trim();
}

/** 词表解析：接受数组或分隔字符串（中英文分隔符均可）。 */
function splitList(v) {
  const arr = Array.isArray(v) ? v : String(v == null ? '' : v).split(SPLIT_RE);
  return arr.map(normalizeTerm).filter(Boolean);
}

/**
 * 解析主题定义。`terms` 必填 —— 空词表直接抛错，
 * 避免「什么都没配」被当成「全部跑题」而静默产出空结论。
 */
function buildTopic(spec) {
  const s = spec || {};
  const terms = splitList(s.terms != null ? s.terms : s.topic);
  const near = splitList(s.near);
  const exclude = splitList(s.exclude);
  if (!terms.length) {
    throw new Error('主题词表为空：至少给出一个主题术语（例：--topic "毛球,化毛,hairball"）');
  }
  const dup = [...new Set(terms.filter((t, i) => terms.indexOf(t) !== i))];
  const overlap = [...new Set(terms.filter(t => near.includes(t)))];
  const warnings = [];
  if (dup.length) warnings.push('主题词表含重复项（已去重）: ' + dup.join(' / '));
  if (overlap.length) warnings.push('以下词同时出现在主题与相邻词表: ' + overlap.join(' / '));
  return { version: VERSION, terms, near, exclude, warnings };
}

/** 非重叠计数（`term` 为空时必须返回 0，否则 indexOf('') 会死循环）。 */
function countOccurrences(text, term) {
  if (!text || !term) return 0;
  let n = 0, i = 0;
  while ((i = text.indexOf(term, i)) !== -1) { n++; i += term.length; }
  return n;
}

/** 取命中上下文（供人工判断「精确命中」还是「歧义命中」）。 */
function snippetAround(text, term, len) {
  const i = text.indexOf(term);
  if (i < 0) return '';
  const L = len || 40;
  const start = Math.max(0, i - Math.floor(L / 2));
  return (start > 0 ? '…' : '') + text.slice(start, start + L) + (start + L < text.length ? '…' : '');
}

/**
 * 收集命中（v2：在**压缩文本**上匹配 ⇒ 三类形态差异自动等价）。
 * `term` 保留**原始写法**供人工对照；`snippet` 回映原文。
 * ⚠ 纯符号/空白词压缩后为空 ⇒ **必须跳过**（`indexOf('')` 会死循环）。
 */
function collectC(compact, terms, field, weight, kind, out) {
  let score = 0;
  for (const term of terms) {
    const key = compactKey(term);
    if (!key) continue;
    const n = countOccurrences(compact.text, key);
    if (!n) continue;
    score += n * weight;
    out.push({ term, field, kind, n, weight, snippet: snippetFromCompact(compact, key) });
  }
  return score;
}

/** 单条打分。缺字段按空串处理（不臆造）。v2：匹配走压缩文本，形态差异不再影响判定。 */
function scoreRecord(rec, topic) {
  const r = rec || {};
  const titleC = compactWithMap([r.titleEn, r.titleZh].filter(Boolean).join(' '));
  const absC = compactWithMap([r.abstractEn, r.abstractZh].filter(Boolean).join(' '));

  const hits = [];
  let score = 0;
  score += collectC(titleC, topic.terms, 'title', W.title, 'exact', hits);
  score += collectC(absC, topic.terms, 'abstract', W.abstract, 'exact', hits);
  score += collectC(titleC, topic.near, 'title', W.titleNear, 'near', hits);
  score += collectC(absC, topic.near, 'abstract', W.abstractNear, 'near', hits);

  const excludeHits = [];
  score += collectC(titleC, topic.exclude, 'title', W.exclude, 'exclude', excludeHits);
  score += collectC(absC, topic.exclude, 'abstract', W.exclude, 'exclude', excludeHits);

  const titleExact = hits.filter(h => h.kind === 'exact' && h.field === 'title').length;
  const absExact = hits.filter(h => h.kind === 'exact' && h.field === 'abstract').length;
  const titleNear = hits.filter(h => h.kind === 'near' && h.field === 'title').length;

  let level;
  if (excludeHits.length) level = 'off';                 // 排除词一票否决（但记录仍保留）
  else if (titleExact > 0 || absExact >= 2) level = 'exact';
  else if (absExact === 1 || titleNear > 0) level = 'near';
  else level = 'off';

  const exactHits = hits.filter(h => h.kind === 'exact');

  return {
    version: VERSION,
    level,
    levelLabel: LEVEL_LABEL[level],
    score: Math.round(score * 100) / 100,
    excluded: excludeHits.length > 0,
    hits,                                        // 全部精确 + 相邻命中（相邻命中亦含 kind 标记）
    titleHits: exactHits.filter(h => h.field === 'title'),    // 仅主题词命中题名
    abstractHits: exactHits.filter(h => h.field === 'abstract'), // 仅主题词命中摘要
    nearHits: hits.filter(h => h.kind === 'near'),
    excludeHits,
    stationRequests: 0,   // 声明式：本模块不产生任何站点请求（单测直接核对）
  };
}

/**
 * 批量排序。稳定序：level 降 → score 降 → 年份降 → 原始 idx 升（末项保证同分不打乱）。
 * groups 接受 search-papers 落盘的 `raw/*.json` 结构（`{keyword, records[]}`）。
 */
function rankAll(groups, topic) {
  const rows = [];
  for (const g of groups || []) {
    const keyword = (g && g.keyword) || null;
    for (const rec of (g && g.records) || []) {
      rows.push({ keyword, rec: rec || {}, rel: scoreRecord(rec, topic) });
    }
  }
  rows.sort((a, b) =>
    (LEVEL_RANK[b.rel.level] - LEVEL_RANK[a.rel.level]) ||
    (b.rel.score - a.rel.score) ||
    ((Number(b.rec.year) || 0) - (Number(a.rec.year) || 0)) ||
    ((Number(a.rec.idx) || 0) - (Number(b.rec.idx) || 0)));
  rows.forEach((r, i) => { r.rank = i + 1; });

  const stat = { exact: 0, near: 0, off: 0 };
  let excluded = 0;
  for (const r of rows) {
    stat[r.rel.level]++;
    if (r.rel.excluded) excluded++;
  }

  return {
    version: VERSION,
    topic,
    total: rows.length,
    stat,
    excluded,
    exactRate: rows.length ? Math.round(stat.exact / rows.length * 1000) / 10 : 0,
    stationRequests: 0,
    ranked: rows,
  };
}

/** 人类可读摘要（供 CLI stdout；不含渲染细节）。 */
function summarize(result, top) {
  const n = top || 10;
  const head = result.ranked.slice(0, n);
  return {
    total: result.total,
    stat: result.stat,
    excluded: result.excluded,
    exactRate: result.exactRate,
    topN: head.map(r => ({
      rank: r.rank, level: r.rel.level, score: r.rel.score,
      year: r.rec.year || null, excluded: r.rel.excluded,
      title: r.rec.titleZh || r.rec.titleEn || '',
    })),
  };
}

/**
 * 词表合并：把**人工勾选**的候选追加到主题词表。
 * ★ 纪律：只被显式调用（CLI 的 `--apply`）—— 任何「自动补词」都会让「覆盖靠人」失守。
 * 去重判据 = `compactKey` 等值 ⇒ `肾脏` 与 `腎臟` 视为同一词（不重复追加，避免无意义的重复项）。
 * 保序：原词按原序在前、新增按传入序在后 ⇒ 词表 v2 可与原值**逐项比对**（diff 友好）。
 * @returns `{terms: string[], appended: string[]}` —— 均为**新数组**，不改写入参。
 */
function mergeTerms(base, add) {
  // ★ 保**原文形态**：刻意不走 `splitList`（它做 normalizeTerm ⇒ 小写化），
  //   否则用户拿词表 v2 替换 `--topic` 时会丢掉原写法（实测：`SCFA` → `scfa`）。
  //   匹配层本就不分大小写（`compactKey` 归一）⇒ 保原文只增可追溯性、不减功能。
  const splitRaw = v => (Array.isArray(v) ? v : String(v == null ? '' : v).split(SPLIT_RE))
    .map(s => String(s == null ? '' : s).trim()).filter(Boolean);
  const b = splitRaw(base);
  const a = splitRaw(add);
  const seen = new Set(b.map(compactKey).filter(Boolean));
  const appended = [];
  for (const t of a) {
    const k = compactKey(t);
    if (!k || seen.has(k)) continue;
    seen.add(k);
    appended.push(t);
  }
  return { terms: b.concat(appended), appended };
}

/**
 * 排序对比：`before` / `after` 为**同一批数据**在两套词表下的 `rankAll` 产物。
 * 用途 = 补词闭环的量化答案（主题命中率变化 / 哪些条目升档 / **是哪个补词起了作用**）。
 * ★ 纯本地：不读文件、不联网 —— 复用同一批 `ranked` 行。
 * 配对键 = keyword + idx + 题名 + 年份（**不含 rank**：rank 会因词表变化而整体重排）。
 *   为何含 keyword/idx：未去重时同一文献会出现在多条检索式下，仅凭题名+年份会错配。
 *   `unmatched` 同批数据必须为 0；非 0 说明两次输入不是同一批 ⇒ **照实报出**而非静默。
 * ★ 不变量：补词只会增加命中 ⇒ `score` 单调不减 ⇒ `downgraded` 必为空。
 *   为空才正常；非空即为缺陷（或词表语义冲突），故本函数照实报出、绝不掩盖。
 */
function diffRanks(before, after, opts) {
  const b = (before && before.ranked) || [];
  const a = (after && after.ranked) || [];
  const keyOf = r => {
    const rec = r.rec || {};
    return [
      r.keyword == null ? '' : String(r.keyword),
      rec.idx == null ? '' : String(rec.idx),
      rec.titleEn || rec.titleZh || '',
      rec.year == null ? '' : String(rec.year),
    ].join('\u0001');
  };
  const indexByKey = list => {
    const m = new Map();
    for (const r of list) {
      const k = keyOf(r);
      if (!m.has(k)) m.set(k, []);
      m.get(k).push(r);
    }
    return m;
  };
  const mb = indexByKey(b);
  const ma = indexByKey(a);

  const upgraded = [];
  const downgraded = [];
  let pairs = 0, onlyBefore = 0, onlyAfter = 0;

  const hitsOf = r => ((r.rel || {}).titleHits || []).concat((r.rel || {}).abstractHits || []);
  for (const [k, rows] of mb) {
    const other = ma.get(k);
    if (!other) { onlyBefore += rows.length; continue; }
    const n = Math.min(rows.length, other.length);
    for (let i = 0; i < n; i++) {
      const x = rows[i], y = other[i];
      pairs++;
      const lf = x.rel.level, lt = y.rel.level;
      if (lf === lt) continue;
      const from = new Set(hitsOf(x).map(h => h.term));
      const to = new Set(hitsOf(y).map(h => h.term));
      const rec = x.rec || {};
      const item = {
        keyword: x.keyword == null ? null : x.keyword,
        idx: rec.idx == null ? null : rec.idx,
        title: rec.titleZh || rec.titleEn || '',
        year: rec.year == null ? null : rec.year,
        levelFrom: lf, levelTo: lt, rankFrom: x.rank, rankTo: y.rank,
        scoreFrom: x.rel.score, scoreTo: y.rel.score,
        newHits: [...to].filter(t => !from.has(t)),
        lostHits: [...from].filter(t => !to.has(t)),
      };
      if ((LEVEL_RANK[lt] || 0) > (LEVEL_RANK[lf] || 0)) upgraded.push(item);
      else downgraded.push(item);
    }
    if (other.length > n) onlyAfter += other.length - n;
  }
  for (const [k, rows] of ma) if (!mb.has(k)) onlyAfter += rows.length;

  const byRankTo = (p, q) => p.rankTo - q.rankTo;
  upgraded.sort(byRankTo);
  downgraded.sort(byRankTo);

  const snap = r => {
    const x = r || {};
    return {
      total: x.total || 0,
      stat: x.stat || { exact: 0, near: 0, off: 0 },
      exactRate: x.exactRate || 0,
    };
  };
  const sb = snap(before), sa = snap(after);
  const delta = {
    exact: sa.stat.exact - sb.stat.exact,
    near: sa.stat.near - sb.stat.near,
    off: sa.stat.off - sb.stat.off,
    exactRate: Math.round((sa.exactRate - sb.exactRate) * 10) / 10,
  };

  return {
    version: VERSION,
    stationRequests: 0,                                   // 声明式：对比不产生任何站点请求
    addedTerms: (opts && opts.addedTerms) || [],
    before: { total: sb.total, stat: sb.stat, exactRate: sb.exactRate },
    after: { total: sa.total, stat: sa.stat, exactRate: sa.exactRate },
    delta,
    pairs,
    unmatched: { onlyBefore, onlyAfter },
    upgraded,
    downgraded,
  };
}

module.exports = {
  VERSION, W, LEVEL_LABEL, LEVEL_RANK,
  buildTopic, scoreRecord, rankAll, summarize,
  normalizeTerm, splitList, countOccurrences, snippetAround,
  // v4.7 挂账 · 词形边界归一（2026-10-16）：破折号族 ↔ 空格 / 繁 ↔ 简 / 连写 ↔ 分写
  DASH_SET, SIMPLIFY_MAP, toSimplified, compactKey, compactWithMap, snippetFromCompact,
  // 供 lib/suggest.cjs（覆盖诊断）复用同一套 CJK 判定，避免两处各写一份范围字面量
  isCJK,
  // v4.7 挂账 · 补词闭环（2026-10-16）：词表合并 + 重排对比（纯函数，零站点请求）
  mergeTerms, diffRanks,
};
