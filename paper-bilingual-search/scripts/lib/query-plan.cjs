'use strict';
/**
 * lib/query-plan.cjs — 残差维度 → **可复核的检索式方案**（纯函数，零网络、零文件系统）
 *
 * 解决什么：`diagnose.cjs` 答「残差缺的是哪个维度」，但人拿到「新维度 = `Kidney`」之后仍要
 *   自己想「那我该拿什么式子去检索」。本模块把新维度簇翻成**可直接粘贴的检索式**：
 *     `(犬 OR 猫 OR 伴侣动物 OR 宠物) AND (膀胱炎 OR 尿道结石)`
 *
 * ★ 铁律一：**只出方案，不执行**。`executed` 恒 false、`stationRequests` 恒 0；
 *   本模块不含任何网络、文件系统、子进程依赖，也无「自动跑」分支（单测 + 源码守卫双钉）。
 *   理由：检索是有成本的动作（积分/配额），且「值不值得照这个方向再搜一轮」是**人的判断**。
 * ★ 铁律二：每条式 `verified` 恒 false。站点语法白名单（`AND`/`OR`/括号/自由词）是 2026-10-04
 *   实测的，但**具体这一条式子从未跑过** —— 未实测的定性一律标未验证，不当结论用。
 * ★ 铁律三：不回流。方案里的术语不得并入词表（采纳唯一通道仍是 `rank-records --apply`）。
 * ★ 状态透传（v3）：簇被 `convergence` 贴上的 `status` 会随方案输出；`stalled` 追加告警
 *   （该维度补词治不了 ⇒ 式子才是唯一验证途径）；未追踪则恒 `null` —— 不臆造「已收敛」。
 * ★ 跨运行抑制（v4）：簇被 `converge-state` 贴上 `suppress` 时不重复出式，改记入 `suppressed`。
 *   判据只有一份（`converge-state.shouldSuppress`：persistent + stalled + 报过 ≥2 次），
 *   本模块**不重算**，只消费标记。抑制必须显式可见 —— 「没给建议」与「没有建议可给」不是一回事。
 *
 * 语法约束（来自 `build-queries.cjs` 的实测白名单，此处复用同一份 `validateQuery`）：
 *   引号短语、`-排除词` 在本机检索通道实测返回 0 条 ⇒ 多词短语只能裸写，并按「各词均出现」
 *   匹配（召回可能偏宽）—— 该副作用**显式告警**，不静默。
 *
 * 依赖：`build-queries`（SPECIES / validateQuery，语法规则只有一份）、`relevance`（compactKey）、
 *   `suggest`（stripSpeciesAffixes，物种词素判据只有一份）。
 */

const { SPECIES, validateQuery } = require('../build-queries.cjs');
const REL = require('./relevance.cjs');
const SG = require('./suggest.cjs');

const VERSION = 'query-plan/v4';
const DEFAULT_CAP = 4;
const CAP_LIMIT = 8;
const ANCHOR_MAX = 2;
const MAX_LEN = 500;
const SPECIES_MODES = ['auto', 'both', 'cat', 'dog', 'none'];

/**
 * 物种探测正则。★ 与 `suggest.SPECIES`（整词停用表）口径**不同**：
 *   停用表判「这个词本身没有信息量」，故列的是 `犬猫`/`宠物` 这类整词；
 *   这里判「这批文献研究的是什么动物」，故中文单字 `犬`/`猫` 也必须算
 *   （`犬慢性肾病` 里并没有「犬猫」这个整词）。
 */
const DETECT = {
  cat: /猫|貓|feline|\bcats?\b/i,
  dog: /犬|狗|canine|\bdogs?\b/i,
};

function clampInt(v, dflt, lo, hi) {
  const n = Number(v);
  if (!Number.isInteger(n)) return dflt;
  return Math.min(hi, Math.max(lo, n));
}

const HAN = /[\u4e00-\u9fa5]/;

/** 术语语言：含汉字 ⇒ zh，否则 en（决定配哪一侧的物种块）。 */
function langOf(s) {
  return HAN.test(String(s == null ? '' : s)) ? 'zh' : 'en';
}

/**
 * 从主题词表里挑「主题锚」—— 让处方不脱离主题。
 *
 * ★ 为什么必须有锚：诊断给的只是一条**维度**（`Kidney`）。式子若只写「物种 AND 维度」，
 *   取回的是「该物种的整个维度大类」，而不是「主题 × 维度」。
 *   一手证据（2026-10-18 处方实测，站点真实返回）：无锚式
 *   `(cat OR feline) AND (Kidney OR Kidney Disease OR Chronic Kidney OR Axis)` 取回 16 条猫 CKD，
 *   在全词表下 15 条只到 `near`（有 kidney、无任何肠侧词）—— 主题约束被式子自己丢掉了。
 *
 * 取用规则（三条都来自实测，不是偏好）：
 *   ① 只用**同语言**的词：中文式配中文锚、英文式配英文锚（与「中英分条」同源，混搭会互不命中）；
 *   ② 跳过与维度术语相同或互为子串的词：加进去不增加定向性（与「术语去冗余」同一判据）；
 *   ③ 按词表**原顺序**取前 `ANCHOR_MAX` 个：用户的词序即意图，不重排、不按长度挑选。
 *   单字锚（如 `肾`）一律不用 —— 它几乎等价于不加锚。
 *
 * @param {Object} topic `buildTopic()` 的结果（只用 `terms`）
 * @param {'zh'|'en'} lang 目标语言
 * @param {Set<string>} dimKeys 该簇全部术语的 `compactKey`
 * @returns {{anchors: string[], source: 'topic'|'none'}} `source='none'` 时调用方**必须**告警
 */
function pickAnchors(topic, lang, dimKeys) {
  const terms = (topic && Array.isArray(topic.terms)) ? topic.terms : [];
  const out = [];
  for (const t0 of terms) {
    const t = String(t0 == null ? '' : t0).trim();
    if (!t || langOf(t) !== lang) continue;
    const k = REL.compactKey(t);
    if (k.length < 2) continue;                       // ③ 单字锚 ≈ 不加锚
    // ② 与维度术语相同 / 互为子串：**一个判据即可** —— `d.includes(k)` 在 k === d 时也成立，
    //    再单列一条等值判断属冗余代码（冗余代码会让「变异打在它上面」变成假盲区）。
    let clash = false;
    for (const d of dimKeys) {
      if (d.length >= 2 && (d.includes(k) || k.includes(d))) { clash = true; break; }
    }
    if (clash) continue;
    if (out.some(x => REL.compactKey(x) === k)) continue;
    out.push(t);
    if (out.length >= ANCHOR_MAX) break;
  }
  return { anchors: out, source: out.length ? 'topic' : 'none' };
}

/**
 * 从题名探测物种（`cat` / `dog` / `both`）。
 * 两者都出现、或都不出现 ⇒ `both`：**宁宽勿窄** —— 漏掉物种块会大幅降召回，
 *   而多带物种词只是多召回几条异种文献（后段人工/排除词仍能挡）。
 */
function detectSpecies(rows) {
  let cat = 0;
  let dog = 0;
  for (const r of rows || []) {
    const rec = (r && r.rec) || {};
    const s = [rec.titleZh, rec.titleEn].filter(Boolean).join(' ');
    if (!s) continue;
    if (DETECT.cat.test(s)) cat++;
    if (DETECT.dog.test(s)) dog++;
  }
  if (cat && !dog) return 'cat';
  if (dog && !cat) return 'dog';
  return 'both';
}

/**
 * 由维度簇生成检索式方案。
 * @param {Array}  clusters `diagnoseResidual().clusters`
 * @param {Object} [opts]
 *   rows     `rankAll().ranked`（仅供 `species: 'auto'` 探测，缺省则退化为 both）
 *   species  `auto`（默认）| `both` | `cat` | `dog` | `none`
 *   cap      每条式的术语上限（默认 4，钳 1–8）—— 超出者进 `dropped` 并告警
 * @returns {Object} 见 `makePlan` 注释；**恒 `executed: false`、`stationRequests: 0`**
 */
function buildQueryPlans(clusters, opts) {
  const o = opts || {};
  const cap = clampInt(o.cap, DEFAULT_CAP, 1, CAP_LIMIT);
  const speciesSource = SPECIES_MODES.indexOf(o.species) >= 0 ? o.species : 'auto';
  const species = speciesSource === 'auto' ? detectSpecies(o.rows) : speciesSource;
  const sp = SPECIES[species] || {};
  const plans = [];
  const skipped = [];
  const suppressed = [];
  let droppedSpeciesGlue = 0;
  let droppedRedundant = 0;

  for (const c of clusters || []) {
    if (!c) continue;
    // 只有「新维度」值得新开一个检索方向；同轴簇用 --apply 补词即可（补词比换式子便宜）
    if (c.kind !== 'new-dimension') {
      skipped.push({ cluster: c.label == null ? '' : String(c.label), kind: c.kind || null, reason: 'axis-extend' });
      continue;
    }
    // ★ 跨运行抑制：同一维度、同一结论（persistent + stalled）且已经报过 ⇒ 不再重复出式子。
    //   判据**唯一一份**在 `converge-state.shouldSuppress`（这里只读标记，不重算），
    //   且必须显式记入 `suppressed` —— 「这次没给建议」与「没有可给的建议」是两件事。
    if (c.suppress === true) {
      suppressed.push({
        cluster: c.label == null ? '' : String(c.label),
        kind: c.kind,
        status: c.status == null ? null : String(c.status),
        support: c.support == null ? null : c.support,
        reportCount: c.reportCount == null ? null : c.reportCount,
        reason: 'repeated-stalled',
      });
      continue;
    }
    const raw = Array.isArray(c.terms) ? c.terms : [];
    const keySet = new Set(raw.map(x => REL.compactKey(String((x && x.term) || '').trim())).filter(Boolean));
    const byLang = { zh: [], en: [] };
    const seen = new Set();
    for (const x of raw) {
      const term = String((x && x.term) || '').trim();
      if (!term) continue;
      const k = REL.compactKey(term);
      if (!k || seen.has(k)) continue;
      // 防御：剥离物种词素后的串也是本簇术语 ⇒ 这个 term 是物种粘连片段
      //   （diagnose 已在指纹层剪掉，这里再挡一次：clusters 也可能由外部构造）。
      //   判据依赖「剩余串确实存在」，故 `catheter` → `heter` 不会被误剔。
      if (SG.stripSpeciesAffixes(k).some(r => keySet.has(r))) { droppedSpeciesGlue++; continue; }
      seen.add(k);
      byLang[langOf(term)].push(term);
    }

    // 中英各出一条：站点是中英双语库，一条式子无法同时覆盖两侧索引
    //   ★ 去冗余：若某术语是**另一术语的真子串**且不是簇标签，则不写进 OR。
    //     理由：OR 是并集，加子串**只会放宽召回、不增加定向性**（一手证据 2026-10-18 gutkidney：
    //     簇术语含 `Chronic` —— 它是 `Chronic Kidney` 的子串，且全局 df 更高 ⇒ 极大剪枝按设计保留它，
    //     但一旦进式子就变成「题名含 Chronic 即命中」，把式子直接稀释掉）。
    //     簇标签必留：它是该维度的最核心词（`Kidney` 虽是 `Kidney Disease` 的子串，剔掉就丢靶心）。
    for (const lg of ['zh', 'en']) {
      const arr = byLang[lg];
      if (!arr.length) continue;
      const labelKey = REL.compactKey(String(c.label == null ? '' : c.label));
      const cand = arr.filter((term, i) => {
        const k = REL.compactKey(term);
        if (k === labelKey) return true;
        return !arr.some((o, j) => {
          if (j === i) return false;
          const ko = REL.compactKey(o);
          return ko.length > k.length && ko.includes(k);
        });
      });
      const redundant = arr.filter(x => cand.indexOf(x) < 0);
      if (redundant.length) droppedRedundant += redundant.length;
      const used = cand.slice(0, cap);
      const dropped = cand.slice(cap);
      const spClause = sp[lg] || '';
      const body = used.length > 1 ? '(' + used.join(' OR ') + ')' : used[0];
      // ★ 主题锚：把「主题」重新写回式子（详见 pickAnchors 注释里的实测反例）
      const anchor = pickAnchors(o.topic, lg, keySet);
      const anchorClause = anchor.anchors.length
        ? '(' + anchor.anchors.join(' OR ') + ')' : '';
      const query = [spClause, body, anchorClause].filter(Boolean).join(' AND ');
      const warnings = validateQuery(query).slice();
      if (anchor.source === 'none') {
        warnings.push('无主题锚（该语言下词表没有可用作锚的术语）⇒ 该式只限定「物种 × 维度」，'
          + '召回会扩散到该维度的大类文献；实测时须逐条核读，勿直接当主题结果用');
      }
      if (used.some(x => /\s/.test(x))) {
        warnings.push('术语含空格且未加引号：站点引号语法实测返回 0 条 ⇒ 该短语按「各词均出现」匹配，'
          + '召回可能偏宽，实测后须按命中上下文收窄');
      }
      if (dropped.length) {
        warnings.push('超出术语上限 ' + cap + ' 被截断 ' + dropped.length + ' 个（不静默丢弃）：'
          + dropped.join('、'));
      }
      if (redundant.length) {
        warnings.push('已剔除 ' + redundant.length + ' 个「是其它术语子串」的冗余项（OR 里只会放宽召回）：'
          + redundant.join('、'));
      }
      if (query.length > MAX_LEN) {
        warnings.push('检索式过长（' + query.length + ' 字符），建议拆条');
      }
      // ★ 收敛状态透传：`stalled` 的维度是**唯一值得开式子**的那类 —— 补词治不了它
      //   （support 连续多轮未降），只能去站点侧验证。缺省不臆造：未追踪到则 null。
      const clusterStatus = c.status == null ? null : String(c.status);
      if (clusterStatus === 'stalled') {
        warnings.push('该维度已连续 ' + (c.stallRounds || 1) + ' 轮 support 未降'
          + '（补词治不了）⇒ 本条式是唯一验证途径；命中结果须人工核读后再决定是否补进词表');
      }
      plans.push({
        cluster: c.label == null ? '' : String(c.label),
        kind: c.kind,
        clusterStatus,                                                // resolved/stalled/…（null = 未追踪）
        clusterPersistRounds: c.persistRounds == null ? null : c.persistRounds,
        lang: lg,
        species,
        query,
        terms: used.slice(),
        anchors: anchor.anchors.slice(),   // 主题锚：检索用，**不是**词表扩展
        anchorSource: anchor.source,
        dropped: dropped.slice(),
        warnings,
        verified: false,          // ★ 未实测：本模块零站点请求
        support: c.support == null ? null : c.support,
        confidence: c.confidence == null ? null : c.confidence,
      });
    }
  }

  return {
    version: VERSION,
    stationRequests: 0,           // 声明式：只读已排序结果
    executed: false,              // ★ 恒 false：不得基于诊断自动发起检索
    species,
    speciesSource,
    cap,
    anchorMax: ANCHOR_MAX,
    plans,
    skipped,
    suppressed,                   // 跨运行抑制掉的维度（非空时报告必须显式说明，否则像「没建议」）
    droppedSpeciesGlue,
    droppedRedundant,
    note: '仅方案：逐条人工复核后再自行执行；本模块不发起任何检索，也不改动词表。'
      + '式子结构 = 物种 AND 维度 AND 主题锚；缺锚时已显式告警（召回会扩散到维度大类）。',
  };
}

module.exports = {
  VERSION, DEFAULT_CAP, CAP_LIMIT, MAX_LEN, SPECIES_MODES, DETECT,
  detectSpecies, buildQueryPlans, langOf,
};
