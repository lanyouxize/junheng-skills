'use strict';
/**
 * lib/suggest.cjs — 覆盖诊断：缺词候选（纯函数，零网络、零文件系统）
 *
 * 解决的问题：排序器给出分档后，实测暴露**真正的瓶颈是「词表覆盖」而非「词形形态」**。
 *   2026-10-16 一手实证：词形归一落地后，繁体猫 CKD 论文由 off 升到 near，
 *   **但题名仍 0 命中** —— 因为词表里根本没有「肾脏保健 / 乳酸杆菌」这类中文主题词。
 *   ⇒ 「形态」可以由代码兜住，「覆盖」原先只能靠人。本模块把覆盖也变成机检信号：
 *     扫**主题档**题名，提取「高频但不在词表」的领域词 ⇒ 人只需挑词，无需通读全量。
 *
 * 与 lib/relevance.cjs 的关系：本模块**复用其归一化**（`compactKey` / `toSimplified`），
 *   故「词表写简体、语料写繁体」不会被误报为缺词 —— 两条防线共用同一套字形等价规则。
 *
 * 中文没有内置分词器（**拒绝第三方依赖** ⇒ 不许引 jieba 之类），只能走 n-gram。
 * 为此设计四层降噪（全部来自「不做就会出假词」的一手推演）：
 *   ① **虚词切分**：在「的/与/之/于/在…」处断开 CJK 串，n-gram **只在段内**生成。
 *      否则 `慢性肾脏病的营养管理` 会产出 `肾脏病的` 这类跨虚词假词。
 *   ② **通用词拦截（三条互不重叠的判据）**：等值（`研究`）· 全拼接（`研究进展` = 研究+进展）·
 *      **边界残渣**（`究进`/`物犬` —— 词窗接缝处拼出来的碎片）。逐词加黑名单会「按下去又弹起来」，
 *      故第三条用**结构性判据**（见 `isStopResidue`）。
 *   ③ **极大剪枝**：候选 A ⊂ 候选 B 且 `df(B) ≥ df(A)` ⇒ 丢 A（`营养管` 让位于 `营养管理`）。
 *   ④ **已覆盖判定**：候选被任一主题词包含（压缩后子串）⇒ 丢（已有覆盖，不必再提示）。
 *
 * ★ 明确的边界（如实登记，不掩饰）：纯 n-gram **分不出**「`菌群失调`（真缺词）」
 *   与「`脏保健复`（分词错位）」—— 二者与词表词的关系同构（半重叠、互不包含）。
 *   ⇒ 本模块**不压制**半重叠候选，只标 `overlapsTopic: true` 并**降权排序**：
 *     信息零丢失，词边界判断交给人（与「形态由代码、覆盖靠人」一脉相承）。
 */

const REL = require('./relevance.cjs');
const { toSimplified, compactKey, isCJK } = REL;

const VERSION = 'suggest-terms/v1';

const DEFAULT_MIN_DF = 2;    // 至少出现在 2 条记录里才算「高频」（单条出现多为偶然切分）
const DEFAULT_MAX_N = 4;     // 中文 n-gram 上限（宠物营养主题词以 2~4 字为主）
const DEFAULT_TOP = 20;
const DEFAULT_SCOPE = 'near'; // 最低档位（单调包含）：主题档 + 相邻档（见 buildSuggestions 注释）
const EN_MIN_LEN = 4;        // 英文单 token 最短长度（滤掉 of/in/an 之类）
const CJK_MIN_N = 2;
const OVERLAP_MIN = 2;       // 与词表词的最长公共子串 ≥ 该值且互不包含 ⇒ overlapsTopic
const SAMPLE_MAX = 3;
const SAMPLE_LEN = 44;

/**
 * 中文虚词：**作切分点**（不参与 n-gram）。只收「几乎只作虚词」的字 ——
 * `用/时/间/过/上/下/内` 等虽常作虚词，但在 `应用/时间/过滤/上皮/细胞内` 里是实词成分，
 * 切掉会丢信息 ⇒ **一律不收**（宁可留噪音，不可砍真词）。
 */
const CJK_SPLIT = new Set('的了与和及或在中是为对由从以并而则者也 都更该这那此各每些把被之于'
  .replace(/\s/g, '').split(''));

/** 中文通用词：作为**整体候选**时丢弃（不是切分点，只在结果层过滤）。 */
const CJK_STOP = new Set([
  '研究', '进展', '分析', '探讨', '影响', '作用', '效果', '方法', '结果', '应用', '评价', '综述',
  '现状', '关系', '机制', '临床', '治疗', '诊断', '检测', '测定', '含量', '变化', '意义', '价值',
  '问题', '对策', '报告', '病例', '观察', '试验', '实验', '比较', '初探', '概述', '简介', '报道',
  '体会', '经验', '特点', '特征', '基础', '理论', '情况', '初步', '不同', '两种', '三种', '水平',
  '能力', '功能', '系统', '技术', '开发', '设计', '控制', '指标', '参数', '条件', '环境', '过程',
  '阶段', '方面', '部分', '趋势',
]);

/** 英文停用词与通用科研词（**等值**判定；不扫 bigram 内部，故 `dietary fiber` 不受影响）。 */
const EN_STOP = new Set([
  'the', 'and', 'for', 'with', 'from', 'that', 'this', 'these', 'those', 'were', 'was', 'are',
  'is', 'its', 'into', 'than', 'then', 'also', 'such', 'using', 'used', 'use', 'uses', 'study',
  'studies', 'effect', 'effects', 'role', 'review', 'analysis', 'result', 'results', 'method',
  'methods', 'based', 'between', 'among', 'during', 'after', 'before', 'can', 'may', 'but',
  'not', 'all', 'has', 'have', 'had', 'their', 'which', 'when', 'where', 'will', 'would',
  'could', 'should', 'more', 'most', 'less', 'least', 'other', 'others', 'been', 'being',
  'both', 'each', 'only', 'some', 'any', 'our', 'out', 'over', 'under', 'about', 'however',
  'there', 'they', 'them', 'his', 'her', 'who', 'what', 'how', 'why', 'does', 'did', 'done',
  'via', 'per', 'two', 'three', 'one', 'first', 'second', 'third', 'new', 'novel', 'total',
  'high', 'low', 'way', 'ways', 'else',
  // 实测（2026-10-16 gutkidney 40 条）挤进候选的泛词
  'influence', 'nutritional', 'influences', 'impact', 'impacts', 'assessment', 'evaluation',
  'associated',
]);

/** 物种 / 泛称词：到处都出现，不构成「主题词表缺口」。 */
const SPECIES = new Set([
  'cat', 'cats', 'dog', 'dogs', 'canine', 'canines', 'feline', 'felines', 'pet', 'pets',
  'animal', 'animals', 'mouse', 'mice', 'rat', 'rats', 'pig', 'pigs', 'chicken', 'chickens',
  'cow', 'cows', 'sheep', 'horse', 'horses', 'rabbit', 'rabbits',
  '宠物', '寵物', '动物', '動物', '伴侣动物', '伴侶動物', '犬猫', '犬貓', '家犬', '家猫', '家貓',
  '宠物犬', '宠物猫', '宠物貓',
  '小鼠', '大鼠', '哺乳动物', '哺乳動物',
]);

// ------------------------------------------------------------------ 内部工具

function clip(s, n) {
  const t = String(s == null ? '' : s).replace(/\s+/g, ' ').trim();
  return t.length > n ? t.slice(0, n) + '…' : t;
}

/** 通用词 / 物种词的**用字集合**（供 `isStopResidue` 判定「窗口错位残渣」）。 */
const GENERIC_CHARS = (() => {
  const set = new Set();
  for (const w of CJK_STOP) for (const c of w) set.add(c);
  for (const w of SPECIES) if (/^[\u4e00-\u9fff]+$/.test(w)) for (const c of w) set.add(c);
  return set;
})();

/**
 * 是否「通用词窗口的**错位切分残渣**」—— 候选的**每一个字**都出现在某通用词/物种词里。
 * 三条判据逐级更一般：等值（`研究`）→ `CJK_STOP.has`；**本函数**（`研究进展` 全拼接、
 * `究进` = 研究&#124;进展 接缝、`物犬` = 宠物犬 尾巴，皆真）。
 *   （**全拼接是「用字全来自通用词」的特例**，故原先单独的 `isStopComposed` 贪心剥离已删除 ——
 *     变异自证证明它对行为零贡献（M7 盲区），留着即死代码。）
 * 为何必须用结构性判据：n-gram 在词窗接缝处必然产出残渣，**逐词加黑名单是按下去又弹起来**
 *   （2026-10-16 实测：把 `宠物犬` 补进物种词表后，其尾巴 `物犬` 立刻冒出来，df=2）。
 * 反向约束（宁可留噪音，不可砍真词）：只要候选含**一个**不在通用词用字里的字
 *   （如 `肾`/`营`/`尿`/`谢`），就判为真词并保留 —— 故 `肾衰竭`/`营养管理`/`猫尿石症`/
 *   `代谢`/`犬肠道菌`/`免疫功能` 均不受影响。
 * 已知边界：若某真词恰好全部由通用词用字组成（如 `病理` = 病+理），会被一并丢弃；
 *   此类词在本领域属通用学术用语，丢之无损；该取舍已登记在 CHANGELOG。
 */
function isStopResidue(k) {
  if (!k || k.length < 2) return false;
  for (const c of k) if (!GENERIC_CHARS.has(c)) return false;
  return true;
}

/**
 * 「物种粘连」的可剥离词素表。
 * ★ 与 `SPECIES`（整词停用表）**不是一回事**：`猫膀胱炎`、`Canine chronic` 都不是停用词
 *   （剥掉物种词后仍有实义），但它们作为**术语**是错的 —— 检索式自身已含物种块
 *   （`(cat OR feline) AND …`），术语里再带物种就会得到「(cat OR feline) AND (Canine chronic)」
 *   这种自相矛盾的式子；作为簇标签也会退化成「物种字 + 半个词」。
 * ★ 只「提出候选剩余串」，**不做判定**：调用方须确认剩余串本身已入册（见 diagnose 的
 *   `species-glue` 剪枝）—— 否则 `catheter` 会被误剥成 `heter`。
 */
const SPECIES_AFFIX_ZH = ['伴侣动物', '伴侶動物', '宠物犬', '宠物猫', '宠物貓', '宠物', '寵物',
  '动物', '動物', '猫科', '貓科', '犬科', '犬猫', '犬貓', '家猫', '家貓', '家犬',
  '小鼠', '大鼠', '犬', '狗', '猫', '貓'];
const SPECIES_AFFIX_EN = ['companion', 'animal', 'canine', 'feline', 'cat', 'dog', 'pet'];

/**
 * 列出「剥掉前导/后随物种词后」的候选剩余串（可能为空数组 = 无物种词素）。
 * ★ 只做**机械剥离**，不设长度门槛、也不判断是否粘连：门槛属判定（如「剩余须 ≥2 汉字」
 *   会漏掉 `猫膳`→`膳` 这类半词残渣，而它正是要剪的），判定权一律留给调用方
 *   —— 调用方的判据是「剩余串本身已入册 / 是某入册指纹的真子串」，故 `catheter`→`heter` 不会被误剪。
 * @param {string} key 压缩后的指纹/术语（`compactKey` 产物）
 * @returns {string[]} 去重后的剩余串，**尚未判定是否粘连**
 */
function stripSpeciesAffixes(key) {
  const k = String(key == null ? '' : key);
  if (!k) return [];
  const out = [];
  const toks = /[\u4e00-\u9fff]/.test(k) ? SPECIES_AFFIX_ZH : SPECIES_AFFIX_EN;
  for (const tok of toks) {
    if (k.length <= tok.length) continue;
    if (k.startsWith(tok)) out.push(k.slice(tok.length));
    if (k.endsWith(tok)) out.push(k.slice(0, k.length - tok.length));
  }
  return Array.from(new Set(out));
}

/** 停用判定三支：整词命中 / 通用词窗口残渣（`研究进展` 全拼接、`究进` 接缝 —— 同一判据）/
 *  英文 bigram 各部件皆停用（`dogs cats`）。**提到模块级**：诊断模块必须共用同一套判据，
 *  否则「建议补词」与「残差诊断」会对同一个串给出相反结论（两份语义分叉是无声缺陷）。 */
function isStop(k) {
  return CJK_STOP.has(k) || EN_STOP.has(k) || SPECIES.has(k);
}

/** 候选级停用：整词 / 残渣 / 英文 bigram 全拼接（见 `isStop`）。 */
function isStopCandidate(c) {
  if (!c) return true;
  return isStop(c.key) || isStopResidue(c.key)
    || (c.parts && c.parts.length > 1 && c.parts.every(p => isStop(p)));
}

/** 最长公共子串长度（两侧都很短，O(m·n) 足够；不引入第三方库）。 */
function lcsLen(a, b) {
  const m = a.length, n = b.length;
  if (!m || !n) return 0;
  let prev = new Array(n + 1).fill(0);
  let best = 0;
  for (let i = 1; i <= m; i++) {
    const cur = new Array(n + 1).fill(0);
    for (let j = 1; j <= n; j++) {
      if (a[i - 1] === b[j - 1]) {
        cur[j] = prev[j - 1] + 1;
        if (cur[j] > best) best = cur[j];
      }
    }
    prev = cur;
  }
  return best;
}

/**
 * 候选提取：CJK 段内 n-gram（虚词作切分点）+ 英文 token 与相邻 bigram。
 * `key` 一律走 `compactKey`（与词表同空间）；`text` 保留**原文形态**（繁体/大小写/连字符）
 * 供人工判读 —— 与 relevance 的 snippet 策略一致。索引在「等长归一」上对齐，故可回映。
 */
function extractCandidates(raw, maxN) {
  const src = String(raw == null ? '' : raw);
  const norm = toSimplified(src.toLowerCase());
  const out = [];
  const toks = [];
  const isLetter = c => c >= 'a' && c <= 'z';
  const isDigit = c => c >= '0' && c <= '9';

  let i = 0;
  while (i < norm.length) {
    const ch = norm[i];
    if (isCJK(ch)) {
      let j = i;
      while (j < norm.length && isCJK(norm[j])) j++;
      let s = i;
      for (let k = i; k <= j; k++) {
        const isCut = (k === j) || CJK_SPLIT.has(norm[k]);
        if (!isCut) continue;
        const len = k - s;
        if (len >= CJK_MIN_N) {
          const top = Math.min(maxN, len);
          for (let n = CJK_MIN_N; n <= top; n++) {
            for (let p = s; p + n <= k; p++) {
              const text = src.slice(p, p + n);
              out.push({ key: compactKey(text), text, kind: 'cjk' });
            }
          }
        }
        s = k + 1;
      }
      i = j;
      continue;
    }
    if (isLetter(ch)) {
      let j = i;
      while (j < norm.length && (isLetter(norm[j]) || isDigit(norm[j]))) j++;
      const tok = norm.slice(i, j);
      if (tok.length >= EN_MIN_LEN) toks.push({ key: tok, text: src.slice(i, j) });
      i = j;
      continue;
    }
    i++;
  }
  for (let t = 0; t < toks.length; t++) {
    out.push({ key: toks[t].key, text: toks[t].text, kind: 'en', parts: [toks[t].key] });
    if (t + 1 < toks.length) {
      const a = toks[t], b = toks[t + 1];
      const text = a.text + ' ' + b.text;
      // parts 供统计层判「整串都由停用/物种词拼成」（如 `dogs cats` ⇒ `dogscats`）
      out.push({ key: compactKey(text), text, kind: 'en', parts: [a.key, b.key] });
    }
  }
  return out;
}

// ------------------------------------------------------------------ 主入口

/**
 * 生成缺词候选。
 * @param {Array} rows    `rank-records` 的 `result.ranked`（`{rec, rel:{level}}`）
 * @param {Object} topic  `relevance.buildTopic` 的产物（terms / near / exclude）
 * @param {Object} [opts] `{scope, minDf, maxN, suggestTop}`
 *   scope: 最低档位（**单调包含**）—— 'exact'（只扫主题档）| 'near'（默认：主题档 + 相邻档）| 'all'
 */
function buildSuggestions(rows, topic, opts) {
  const o = opts || {};
  const scope = o.scope || DEFAULT_SCOPE;
  const minDf = Number.isInteger(o.minDf) && o.minDf > 0 ? o.minDf : DEFAULT_MIN_DF;
  const maxN = Number.isInteger(o.maxN) && o.maxN >= CJK_MIN_N ? o.maxN : DEFAULT_MAX_N;
  const top = Number.isInteger(o.suggestTop) && o.suggestTop > 0 ? o.suggestTop : DEFAULT_TOP;

  const t = topic || {};
  const topicKeys = (t.terms || []).map(compactKey).filter(Boolean);
  const nearKeys = (t.near || []).map(compactKey).filter(Boolean);
  const excludeKeys = (t.exclude || []).map(compactKey).filter(Boolean);

  // 候选 ⊂ 词表词 ⇒ 已有覆盖（含等值）
  const isCovered = k => topicKeys.some(x => x === k || x.includes(k));
  // 词表词 ⊂ 候选 ⇒ 「词表词 + 修饰」形态，是高价值补词方向
  const extendsTopic = k => topicKeys.some(x => x !== k && k.includes(x));
  // 半重叠（互不包含但有 ≥ OVERLAP_MIN 字公共子串）⇒ 既不覆盖也不延伸，只降权。
  // 判定范围 = 主题词 + **相邻词**：`性肾衰竭`（`肾衰竭` 的分词错位）只有靠相邻词才认得出。
  const overlapsTopic = k => !isCovered(k) && !extendsTopic(k)
    && topicKeys.concat(nearKeys).some(x => lcsLen(k, x) >= OVERLAP_MIN);
  // 停用判定统一走模块级 `isStopCandidate`（与残差诊断共用一套判据）
  const isStopCand = c => isStopCandidate(c);

  // 语料范围：**单调包含**语义 —— 以 `scope` 为最低档位（off < near < exact）。
  // `exact` 只扫主题档；`near` = 主题档 + 相邻档；`all` = 全部。
  // 为何 `near` 必须是并集：最需要补词的场景正是「主题档为空」，而缺词证据留在相邻档
  //   （2026-10-16 一手：繁体猫 CKD 论文落在 near 档，其题名的缺词正是最该补的）。
  //   若 `near` 只取 near 档，该场景下候选为空 ⇒ 功能在最需要时失效。
  const LV_RANK = { off: 0, near: 1, exact: 2 };
  const minRank = scope === 'all' ? -1 : (scope === 'exact' ? 2 : 1);
  const corpusRows = (rows || []).filter(r => {
    if (minRank < 0) return true;
    const lv = r && r.rel && r.rel.level;
    return (LV_RANK[lv] || 0) >= minRank;
  });

  const dropped = { total: 0, tooShort: 0, stopword: 0, inTopic: 0, lowDf: 0, subsumed: 0 };
  const stats = new Map();

  for (const row of corpusRows) {
    const rec = (row && row.rec) || {};
    // 字段名不可信（与 relevance 同规则）：站点的 titleEn 里可能装中文标题
    const raw = [rec.titleEn, rec.titleZh].filter(Boolean).join(' ');
    if (!raw.trim()) continue;
    const seen = new Set();
    for (const cand of extractCandidates(raw, maxN)) {
      dropped.total++;
      const k = cand.key;
      if (!k || seen.has(k)) continue;   // 同一条记录内同 key 只计一次（不影响 df）
      seen.add(k);
      if (k.length < CJK_MIN_N) { dropped.tooShort++; continue; }
      if (isStopCand(cand)) { dropped.stopword++; continue; }
      if (isCovered(k)) { dropped.inTopic++; continue; }
      let e = stats.get(k);
      if (!e) {
        e = { key: k, term: cand.text, kind: cand.kind, df: 0, samples: [] };
        stats.set(k, e);
      }
      e.df++;
      if (e.samples.length < SAMPLE_MAX) e.samples.push(clip(raw, SAMPLE_LEN));
    }
  }

  const all = [...stats.values()];
  const hit = all.filter(e => e.df >= minDf);
  dropped.lowDf = all.length - hit.length;

  // 极大剪枝：长串优先入册；被已入册的长串包含且 df 不小于它 ⇒ 丢弃
  hit.sort((a, b) => (b.key.length - a.key.length) || (a.key < b.key ? -1 : 1));
  const keep = [];
  for (const e of hit) {
    if (keep.some(b => b.key.includes(e.key) && b.df >= e.df)) { dropped.subsumed++; continue; }
    keep.push(e);
  }

  for (const e of keep) {
    e.term = e.term || e.key;
    e.len = e.key.length;
    e.extendsTopic = extendsTopic(e.key);
    e.overlapsTopic = overlapsTopic(e.key);
    e.inNear = nearKeys.some(x => x.includes(e.key) || e.key.includes(x));
    e.inExclude = excludeKeys.some(x => x.includes(e.key) || e.key.includes(x));
    e.penalty = e.overlapsTopic ? 1 : 0;
  }

  // 排序：df 降 → 降权 → 长度降 → key 升（末项保证同分不打乱，便于 diff）
  keep.sort((a, b) => (b.df - a.df) || (a.penalty - b.penalty) || (b.len - a.len)
    || (a.key < b.key ? -1 : a.key > b.key ? 1 : 0));

  const candidates = keep.slice(0, top).map(e => ({
    term: e.term, key: e.key, kind: e.kind, df: e.df, len: e.len,
    extendsTopic: e.extendsTopic, overlapsTopic: e.overlapsTopic,
    inNear: e.inNear, inExclude: e.inExclude, penalty: e.penalty,
    samples: e.samples.slice(),
  }));

  return {
    version: VERSION,
    stationRequests: 0,          // 声明式：本模块不产生任何站点请求（单测直接核对）
    scope, minDf, maxN,
    corpus: corpusRows.length,
    candidates,
    dropped,
    suggestedTopicSuffix: candidates.map(c => c.term).join(','),
  };
}

module.exports = {
  VERSION, DEFAULT_MIN_DF, DEFAULT_MAX_N, DEFAULT_TOP, EN_MIN_LEN, DEFAULT_SCOPE,
  CJK_SPLIT, CJK_STOP, EN_STOP, SPECIES, GENERIC_CHARS,
  SPECIES_AFFIX_ZH, SPECIES_AFFIX_EN, stripSpeciesAffixes,
  buildSuggestions, extractCandidates, lcsLen, isStopResidue, isStopCandidate,
};
