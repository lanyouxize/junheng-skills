#!/usr/bin/env node
/* eslint-disable */
/**
 * lib/evidence.cjs — 证据分级结构化（启发式候选标记）
 *
 * ⚠ 设计红线（务必遵守，任何时候都不要「优化」掉）:
 *   本模块输出的全部字段都是「候选值 + 原文依据 + 置信度」，needsReview 恒为 true。
 *   它只做「把 200 条里最值得先看的那 20 条挑出来」这件事，
 *   绝不声称能自动判定研究类型与证据等级 —— 那需要读全文与方法学章节，是人的工作。
 *   凡 increase「看起来更准」而丢掉依据/置信度的改动，一律视为回归。
 *
 * 为什么用启发式而不是模型判定：
 *   检索结果只有 ~2 行摘要节选（站点即如此），信息量不足以支撑确定性判定；
 *   若用模型「补全」一个看起来专业的等级而不给依据，等于制造幻觉证据，
 *   对用于功效宣称支撑的文献来说，这比不做分级更危险。
 *
 * 四维候选标记：
 *   designLevel    研究设计等级 L1(SR/MA) → L5(叙述性综述) / U(信息不足)
 *   speciesRelevance 物种相关性（是否为犬猫靶动物 / 混杂畜禽·啮齿 / 体外）
 *   sampleSize     样本量候选（多个候选值 + 依据片段）
 *   dose           剂量/添加水平候选（含单位）
 *   evidenceGrade  A/B/C/D 综合候选（设计等级 × 物种相关性，见 GRADE_MATRIX）
 *   gradeBasis     ★v4.3 新增：D 档的**成因**区分（design_unrecognized / design_identified / text_too_short）
 *                  —— 让「因信息不足无法判定」与「已判定但证据薄弱」不再混在同一个 D 里
 *                     （真实数据集实测：50 条中 18 条因 design=U 直落 D，与真正的低质量证据无法区分）
 */
'use strict';

const VERSION = 'evidence-grading/v2';

/** 研究设计识别规则：按 priority 从高到低排列，取优先级最高的作为候选 */
const DESIGN_RULES = [
  { type: 'meta_analysis', level: 'L1', label: '系统综述/Meta 分析', priority: 100, re: /\b(meta-?analys[ei]s|systematic review|pooled analysis|umbrella review)\b/i },
  { type: 'rct', level: 'L2', label: '随机对照试验', priority: 90, re: /\b(randomi[sz]ed|randomly (?:assigned|allocated|divided)|random allocation|randomly allotted|double-?blind|triple-?blind|rct)\b/i },
  { type: 'controlled_trial', level: 'L3', label: '对照试验', priority: 72, re: /\b(controlled trial|placebo-?controlled|controlled study|comparative study|sham-?treated|positive control)\b/i },
  { type: 'crossover', level: 'L3', label: '交叉/拉丁方试验', priority: 70, re: /\b(cross-?over|latin[- ]square|washout period)\b/i },
  { type: 'feeding_trial', level: 'L3', label: '饲喂/消化试验', priority: 68, re: /\b(feeding trial|digestibility (?:trial|study)|palatability (?:trial|test|assessment)|aafco (?:protocol|trial)|balance trial|metabolic trial|growth (?:trial|performance) trial)\b/i },
  // v4.3 补「评价式/名词式」的消化·饲喂试验信号（实测漏判族，见 CHANGELOG v4.3）：
  //   旧规则只认 `digestibility (trial|study)` 这一种搭配，导致三类**真实饲喂/消化试验被漏判为 U**，
  //   再经 GRADE_MATRIX[...].U='D' 直落最低档（真实数据集 36% 记录落 D 的成因之一）：
  //     ① `nutrient digestibilities` / `apparent digestibility` 等**名词/复数**形态；
  //     ② `Evaluation of … diets/foods/meals` 等**评价式**；
  //     ③ `effect of X on … digestibility` 等**效应式**。
  //   ★ 关键设计：priority **10 = 全表最低**（低于 in_silico 16），故它只在**没有任何其他设计信号**命中
  //     （即原本被判为 U）时才成为 top ⇒ 结构上只能「救 U」，**不可能顶掉已识别的研究**。
  //     首版曾用 64，实测当场把「In vitro … digestibility」「Prediction of … digestibility」也顶成 L3
  //     （20 条变化含 5 条 L4→L3 退步）—— 反向用例拦下，改为兜底语义后 U→L3 且零退步。
  {
    type: 'digestibility_trial', level: 'L3', label: '消化/饲喂试验(弱信号·兜底)', priority: 10,
    re: /\b(?:apparent|ileal|faecal|fecal|total tract|nutrient|protein|amino acid|dry matter|organic matter|crude protein|energy)\s+digestibilit(?:y|ies)\b|\bdigestibilit(?:y|ies)\s+(?:trial|stud(?:y|ies)|experiment|assay|test|evaluation|determination|measurement|coefficient)s?\b|\bdigestible\s+(?:energy|protein|amino acid|nutrient)s?\b|\b(?:evaluation|assessment|comparison)\s+of\b[^.]{0,50}?\b(?:diets?|foods?|meals?|protein sources?|ingredients?)\b|\beffect\s+of\b[^.]{0,60}?\bon\b[^.]{0,40}?\b(?:digestib\w*|nutrient\w*|energy|protein|palatab\w*|growth|performance|faecal|fecal)\b/gi,
  },
  // 弱信号：只写「分为 N 个处理组」而未出现 trial 一词的早期文献，排在观察性研究之前
  { type: 'feeding_trial_weak', level: 'L3', label: '分组饲养试验(弱信号)', priority: 50, re: /\b(?:allocated|assigned|randomly assigned|divided)\s+(?:to|into)\s+(?:\d+\s+)?(?:dietary\s+|experimental\s+)?(?:treatments|diets|groups)\b/i },
  { type: 'cohort', level: 'L3', label: '前瞻队列/纵向研究', priority: 60, re: /\b(prospective (?:cohort|study|trial|follow)|longitudinal|follow-?up (?:study|period))\b/i },
  { type: 'observational', level: 'L4', label: '观察性研究', priority: 46, re: /\b(case-?control|cross-?sectional|retrospective|prevalence (?:study|survey)|observational study)\b/i },
  { type: 'case_report', level: 'L4', label: '病例报告/病例系列', priority: 44, re: /\b(case report|case series|clinical case)\b/i },
  { type: 'in_vitro', level: 'L4', label: '体外试验', priority: 42, re: /\b(in vitro|cell culture|cell line|caco-?2|hepatocyte|enterocyte|in vitro digestion|simulated gastrointestinal)\b/i },
  { type: 'review_narrative', level: 'L5', label: '叙述性综述/述评', priority: 22, re: /\b(this review|we review|narrative review|literature review|mini-?review|overview of|perspective article|commentary|expert opinion)\b/i },
  { type: 'in_silico', level: 'L5', label: '建模/机器学习', priority: 16, re: /\b(in silico|computational model|mathematical model|machine learning (?:model|approach))\b/i },
  // —— 中文文献规则：源清单以中文术语为主，缺了这一组，中文结果会大量落到 U（未识别）
  { type: 'meta_analysis', level: 'L1', label: '系统评价/荟萃分析', priority: 100, re: /(?:系统评价|系统综述|荟萃分析|meta\s*分析)/gi },
  { type: 'rct', level: 'L2', label: '随机对照试验', priority: 90, re: /(?:随机对照|随机分组|随机分为|随机分成|随机分配|双盲)/g },
  { type: 'controlled_trial', level: 'L3', label: '对照试验', priority: 72, re: /(?:对照组|试验组|空白对照|阴性对照|安慰剂对照)/g },
  { type: 'crossover', level: 'L3', label: '交叉/拉丁方试验', priority: 70, re: /(?:交叉试验|交叉设计|拉丁方)/g },
  { type: 'feeding_trial', level: 'L3', label: '饲养/消化试验', priority: 68, re: /(?:饲养试验|饲喂试验|喂养试验|消化试验|代谢试验|生长试验|适口性试验|消化率测定|表观消化率|全肠道消化率)/g },
  // v4.3 中文**对称补齐**：上一条只认「消化率测定 / 表观消化率」等完整搭配，
  //   而中文文献更常写「蛋白质消化率」「消化能/代谢能」等**裸名词**（实测英文侧同族漏判已证实，
  //   中文侧为对称推断补齐；未单独量化 —— 见 CHANGELOG v4.3 的诚实性声明）。
  { type: 'digestibility_trial', level: 'L3', label: '消化/代谢试验(弱信号·兜底)', priority: 10, re: /(?:蛋白质消化率|养分消化率|营养物质消化率|干物质消化率|消化率|消化能|代谢能|回肠消化率)/g },
  { type: 'cohort', level: 'L3', label: '前瞻性研究', priority: 60, re: /(?:前瞻性|纵向研究|随访)/g },
  { type: 'observational', level: 'L4', label: '观察性研究', priority: 46, re: /(?:回顾性|横断面|流行病学调查|问卷调查|现状调查)/g },
  { type: 'case_report', level: 'L4', label: '病例报告', priority: 44, re: /(?:病例报告|病例分析|个案报告)/g },
  { type: 'in_vitro', level: 'L4', label: '体外试验', priority: 42, re: /(?:体外试验|体外消化|细胞培养|细胞株|细胞系)/g },
  { type: 'review_narrative', level: 'L5', label: '综述/述评', priority: 22, re: /(?:研究进展|综述|述评|展望|综论|本文综述|本文就)/g },
];

/** 物种识别：target=true 表示犬猫靶动物（宠物食品功效的直接证据来源） */
const SPECIES_RULES = [
  { key: 'cat', label: '猫', target: true, re: /\b(cat|cats|feline|kitten|kittens)\b/gi },
  { key: 'dog', label: '犬', target: true, re: /\b(dog|dogs|canine|puppy|puppies|beagle|beagles)\b/gi },
  { key: 'companion_generic', label: '伴侣动物(泛称)', target: true, re: /\b(companion animal|companion animals|pet food|pet foods|pets)\b/gi },
  { key: 'rodent', label: '啮齿动物', target: false, re: /\b(rat|rats|mouse|mice|murine|rodent|gerbil|hamster)\b/gi },
  { key: 'livestock', label: '畜禽', target: false, re: /\b(pig|pigs|swine|porcine|piglet|piglets|broiler|broilers|chicken|chickens|hen|hens|rooster|roosters|cockerel|cockerels|poultry|turkey|cattle|bovine|calf|calves|sheep|ovine|lamb|goat|caprine|rabbit|horse|equine)\b/gi },
  { key: 'human', label: '人', target: false, re: /\b(human|humans|patient|patients|volunteers)\b/gi },
  { key: 'other_animal', label: '其他动物', target: false, re: /\b(fish|salmon|trout|shrimp|mink|fox|macaque|primate|zebrafish|nonhuman)\b/gi },
  // 中文文书式：中文题名/摘要不含英文物种词，缺了这一组会导致中文文献一律判为 unclear
  // ⚠ 必须用多字词组，禁止使用单字：例如「牛磺酸」含「牛」，若把单字「牛」列为畜禽，
  //    则每一篇中文牛磺酸文献都会被误判成畜禽文献（实测已踩此坑）。
  { key: 'cat', label: '猫', target: true, re: /猫/g },
  { key: 'dog', label: '犬', target: true, re: /(?:犬|狗|犬只)/g },
  { key: 'companion_generic', label: '伴侣动物(泛称)', target: true, re: /(?:宠物|伴侣动物)/g },
  { key: 'rodent', label: '啮齿动物', target: false, re: /(?:大鼠|小鼠|仓鼠|啮齿)/g },
  { key: 'livestock', label: '畜禽', target: false, re: /(?:仔猪|生猪|母猪|肉猪|肉鸡|蛋鸡|雏鸡|肉牛|奶牛|犊牛|绵羊|山羊|羔羊|肉羊|家兔|獭兔|家禽|家畜|水产品|肉鸽|乳鸽|鹌鹑|肉鸭|蛋鸭|北京鸭|樱桃谷鸭|肉鹅|狮头鹅|火鸡)/g },
  // ⚠ 高风险单字（鱼/虾/蟹/鹅/猴/鸭）**一律用具体种名或复合词**，禁止用单字：
  //    实测「青蟹素」（添加剂）、「鹅膏」（真菌）、「猴头菇」（真菌）、「鱼油/鱼粉」（原料）都会被单字误命中。
  { key: 'other_animal', label: '其他动物', target: false, re: /(?:水貂|雪貂|紫貂|貂|狐狸|银狐|蓝狐|北极狐|赤狐|貉|猕猴|食蟹猴|恒河猴|短尾猴|灵长类|斑马鱼|鲤鱼|草鱼|鲫鱼|罗非鱼|虹鳟|鲈鱼|鳜鱼|黄颡鱼|大黄鱼|对虾|南美白对虾|凡纳滨对虾|斑节对虾|小龙虾|克氏原螯虾|中华绒螯蟹|河蟹)/g },
  { key: 'human', label: '人', target: false, re: /(?:人类|病人|志愿者)/g },
];

/**
 * 语境排除（最佳档核心）：靶/非靶物种词被用作**疾病命名的一部分**时，它修饰的是「病」，不是研究对象。
 * 例：水貂论文里的「接种**犬**瘟热疫苗」、病毒学论文「**猫**杯状病毒的分离」。
 * 判据：命中片段之后 0–3 字内出现「病名核心词」⇒ 判为病名用法。
 * 误差方向：只会让等级**下调**（→ 更低档 + needsManualExclude 标记），不会上调 ⇒ 偏安全。
 */
const ZH_DISEASE_FIRST = /[瘟细冠腺副传狂钩布杯白免泛疱流鼻病毒支衣立真]/;
const EN_DISEASE_WORD = /^(?:distemper|parvo|parvovirus|corona|coronavirus|leukemia|leukaemia|immunodeficiency|herpes|calicivirus|calici|panleukopenia|adenovirus|influenza|infectious|enteritis|virus)/i;

function isDiseaseNameUse(text, hit) {
  if (/[\u4e00-\u9fa5]/.test(hit.raw)) {
    // 中文：要求**严格邻接**（病名词首字紧跟物种词，0 间隔）
    // 间隔放宽会把「水貂接种犬瘟热」里的「水貂」也误排除 —— 预演实测已踩。
    const c = text[hit.index + hit.raw.length];
    return !!c && ZH_DISEASE_FIRST.test(c);
  }
  // 英文：允许空白，窗口须足够长（≥16）—— 8 字窗口会把 distemper/leukemia 截断导致漏判。
  const after = text.slice(hit.index + hit.raw.length, hit.index + hit.raw.length + 24);
  const m = /^\s*([A-Za-z]+)/.exec(after);
  return !!m && EN_DISEASE_WORD.test(m[1]);
}

/** 综合证据分级矩阵：[designLevel][speciesRelevance] → grade */
const GRADE_MATRIX = {
  target_species: { L1: 'A', L2: 'A', L3: 'B', L4: 'C', L5: 'D', U: 'D' },
  mixed_species: { L1: 'A', L2: 'B', L3: 'B', L4: 'C', L5: 'D', U: 'D' },
  non_target_animal: { L1: 'B', L2: 'C', L3: 'C', L4: 'D', L5: 'D', U: 'D' },
  in_vitro_only: { L1: 'D', L2: 'D', L3: 'C', L4: 'D', L5: 'D', U: 'D' },
  unclear: { L1: 'B', L2: 'C', L3: 'C', L4: 'D', L5: 'D', U: 'D' },
};

const GRADE_LABEL = {
  A: '靶动物 RCT/SR —— 可直接支撑宣称（仍需全文确认）',
  B: '靶动物对照或设计良好 —— 有较强支持力',
  C: '间接物种/观察性/体外 —— 仅作机制线索',
  D: '证据薄弱或信息不足 —— 不建议用于宣称支撑',
};

/** 提取命中词的上下文片段（供人工核查依据） */
function snippet(text, index, len) {
  const pad = 55;
  const start = Math.max(0, index - pad);
  return (start > 0 ? '…' : '') + text.slice(start, index + len + pad).replace(/\s+/g, ' ').trim() + '…';
}

function matchAll(text, re) {
  const out = [];
  const rx = new RegExp(re.source, re.flags.includes('g') ? re.flags : re.flags + 'g');
  let m;
  while ((m = rx.exec(text)) !== null) {
    out.push({ index: m.index, raw: m[0], snippet: snippet(text, m.index, m[0].length) });
    if (m.index === rx.lastIndex) rx.lastIndex++; // 防零宽匹配死循环
    if (out.length > 40) break;
  }
  return out;
}

/** 依据位置估算置信度：设计声明通常出现在摘要开头 */
function confidenceOf(text, matches) {
  if (!matches.length) return 'none';
  const first = Math.min(...matches.map(m => m.index));
  const early = first < Math.max(120, text.length * 0.3);
  return matches.length >= 2 ? (early ? 'high' : 'medium') : (early ? 'medium' : 'low');
}

// ---------- ① 研究设计 ----------
function detectDesign(text) {
  // 同一 type 可能由中英两条规则命中 —— 必须归并，否则候选列表会出现重复项，
  // 且取 #-confidence 时只按第一条规则取候选会导致中文命中被算成 0 次（→ 置信度恒为 none）
  const byType = new Map();
  for (const rule of DESIGN_RULES) {
    const hits = matchAll(text, rule.re);
    if (!hits.length) continue;
    const prev = byType.get(rule.type);
    if (prev) {
      prev.hits += hits.length;
      prev.snippets = prev.snippets.concat(hits.slice(0, 1).map(h => h.snippet)).slice(0, 2);
    } else {
      byType.set(rule.type, {
        type: rule.type, label: rule.label, level: rule.level, priority: rule.priority,
        hits: hits.length, snippets: hits.slice(0, 2).map(h => h.snippet),
      });
    }
  }
  const candidates = [...byType.values()].sort((a, b) => b.priority - a.priority);
  if (!candidates.length) return { value: 'U', label: '无法判定（信息不足）', candidates: [], confidence: 'none' };
  const top = candidates[0];
  // 冲突判定：只有「相差 ≥2 级」或「综述类 vs 原始研究类」才算真冲突。
  // L2(RCT) + L3(交叉/对照) 属于同一试验的不同特征，是互补而非冲突（实测样例：双盲交叉 RCT）。
  const LV = { L1: 1, L2: 2, L3: 3, L4: 4, L5: 5, U: 9 };
  const isReviewish = t => ['review_narrative', 'meta_analysis'].includes(t);
  const conflicting = candidates.filter(c => {
    if (c.level === top.level) return false;
    const distant = Math.abs(LV[c.level] - LV[top.level]) >= 2;
    const mixedKind = isReviewish(c.type) !== isReviewish(top.type);
    if (!distant && !mixedKind) return false;
    // 例外：综述里列举「randomized controlled trials」是其纳研究对象的正常陈述，
    //      不构成设计冲突（否则几乎每条 SR 都会被误标）
    if (isReviewish(top.type) && ['rct', 'controlled_trial', 'crossover', 'feeding_trial', 'feeding_trial_weak', 'cohort', 'observational', 'case_report'].includes(c.type)) return false;
    return true;
  });
  const unionHits = DESIGN_RULES.filter(r => r.type === top.type).flatMap(r => matchAll(text, r.re));
  const confidence = conflicting.length ? 'low' : confidenceOf(text, unionHits);
  return {
    value: top.level, label: top.label, topType: top.type,
    candidates: candidates.map(c => ({ type: c.type, label: c.label, level: c.level, hits: c.hits, evidence: c.snippets })),
    confidence, conflictingTypes: conflicting.map(c => c.type),
  };
}

// ---------- ② 物种相关性 ----------
function detectSpecies(text, titleText) {
  // 同一物种可能由多条规则命中（英文规则 + 中文规则），需按键归并
  const byKey = new Map();
  const diseaseMentions = [];   // 被判为「病名用法」而排除的命中（供下游可见，不静默丢弃）
  for (const rule of SPECIES_RULES) {
    const rawHits = matchAll(text, rule.re);
    const hits = [];
    for (const h of rawHits) {
      if (isDiseaseNameUse(text, h)) diseaseMentions.push({ key: rule.key, label: rule.label, snippet: h.snippet });
      else hits.push(h);
    }
    const inTitle = matchAll(titleText, rule.re).filter(h => !isDiseaseNameUse(titleText, h)).length > 0;
    if (!hits.length && !inTitle) continue;
    const prev = byKey.get(rule.key);
    if (prev) {
      prev.hits += hits.length;
      prev.inTitle = prev.inTitle || inTitle;
    } else {
      byKey.set(rule.key, { key: rule.key, label: rule.label, target: rule.target, hits: hits.length, inTitle, evidence: hits.slice(0, 1).map(h => h.snippet) });
    }
  }
  const detected = [...byKey.values()].filter(d => d.hits > 0 || d.inTitle);
  detected.sort((a, b) => (b.inTitle - a.inTitle) || (b.hits - a.hits));
  const targetHits = detected.filter(d => d.target);
  const nonTargetHits = detected.filter(d => !d.target);
  const invitro = /in vitro|cell culture|cell line/i.test(text);

  let relevance, confidence;
  if (invitro && !targetHits.length && !nonTargetHits.filter(d => d.key !== 'human').length) {
    relevance = 'in_vitro_only'; confidence = 'medium';
  } else if (targetHits.length && nonTargetHits.length) {
    relevance = 'mixed_species'; confidence = 'medium';
  } else if (targetHits.length) {
    relevance = 'target_species'; confidence = targetHits[0].inTitle ? 'high' : 'medium';
  } else if (nonTargetHits.length) {
    relevance = 'non_target_animal'; confidence = nonTargetHits[0].inTitle ? 'high' : 'medium';
  } else {
    relevance = 'unclear'; confidence = 'none';
  }
  const speciesList = [...new Set(detected.filter(d => targetHits.includes(d)).map(d => d.label))];
  return {
    relevance,
    label: { target_species: '犬猫靶动物', mixed_species: '混杂多物种', non_target_animal: '非靶动物（畜禽/啮齿/人）', in_vitro_only: '仅体外', unclear: '未识别到物种' }[relevance],
    targetSpecies: speciesList, detected: detected.map(d => ({ key: d.key, label: d.label, hits: d.hits, inTitle: d.inTitle, evidence: d.evidence })),
    confidence,
    // 被「病名用法」语境排除的命中（可见性）：存在即说明摘要含物种词但系病名（如「犬瘟热疫苗」）
    diseaseNameMentions: diseaseMentions,
    // 源清单「十二」明确提醒：结果会混杂猪、鸡等畜禽饲料文献，需人工排除
    needsManualExclude: relevance === 'non_target_animal' || relevance === 'mixed_species' || relevance === 'unclear' || diseaseMentions.length > 0,
  };
}

// ---------- ③ 样本量 ----------
const WORD_NUM = { ten: 10, twelve: 12, fourteen: 14, fifteen: 15, sixteen: 16, eighteen: 18, twenty: 20, thirty: 30, forty: 40, fifty: 50, sixty: 60, eight: 8, six: 6, seven: 7, nine: 9, eleven: 11 };
function detectSampleSize(text) {
  const candidates = [];
  const push = (n, kind, m) => { if (n > 0 && n <= 5000) candidates.push({ n, kind, evidence: m.snippet }); };
  const patterns = [
    [/\bn\s*[=＝:]\s*(\d{1,4})/gi, 'n='],
    [/[（(]\s*n\s*[=＝:]\s*(\d{1,4})\s*[）)]/gi, 'n='],
    [/\b(\d{1,3})\s+(?:adult\s+|healthy\s+|client-?owned\s+|young\s+|aged\s+|senior\s+)?(?:dogs|cats|kittens|puppies|beagles|animals|pets)\b/gi, 'N+动物'],
    [/\b(?:total of|group of|cohort of|series of|sample of|population of)\s+(\d{1,4})\b/gi, 'total of N'],
    [/\b(?:enrolled|assigned|allocated|recruited|included|randomi[sz]ed)\s+(?:a total of\s+)?(\d{1,4})\b/gi, 'enrolled N'],
    [/\b(\d{1,3})\s+(?:animals|subjects|patients|participants|volunteers)\b/gi, 'N+受试'],
  ];
  for (const [re, kind] of patterns) for (const m of matchAll(text, re)) push(parseInt(m.raw.match(/\d+/)[0], 10), kind, m);
  for (const w of Object.keys(WORD_NUM)) {
    for (const m of matchAll(text, new RegExp('\\b' + w + '\\s+(?:dogs|cats|kittens|puppies|beagles|animals|subjects)\\b', 'gi'))) push(WORD_NUM[w], '英文数字', m);
  }
  // 去重保留次序
  const seen = new Set();
  const uniq = candidates.filter(c => { const k = c.n + '|' + c.kind; if (seen.has(k)) return false; seen.add(k); return true; });
  if (!uniq.length) return { value: null, candidates: [], confidence: 'none' };
  const animalKinds = uniq.filter(c => c.kind.includes('动物') || c.kind === 'enrolled N' || c.kind === '英文数字');
  const pool = animalKinds.length ? animalKinds : uniq;
  const uniqN = [...new Set(pool.map(c => c.n))];
  return {
    value: uniqN.length === 1 ? uniqN[0] : (animalKinds[0] ? animalKinds[0].n : uniq[0].n),
    candidates: uniq.slice(0, 5),
    confidence: uniqN.length === 1 ? 'medium' : 'low',
  };
}

// ---------- ④ 剂量 / 添加水平 ----------
const DOSE_RE = /(\d+(?:[.,]\d+)?)\s*(%|percent|mg\s*\/\s*kg|g\s*\/\s*kg|mg\s*\/\s*day|mg\s*\/\s*d\b|g\s*\/\s*day|mg\s*\/kg\s*BW|iu\s*\/\s*kg|iu|ui|ppm|ppb|mg\s*\/\s*100\s*g|mg\s*\/\s*dL|g\s*\/\s*100\s*g|g\s*\/\s*kg\s*BW|mg\s*\/\s*mL)/gi;
function detectDose(text) {
  const seen = new Set();
  const out = [];
  for (const m of matchAll(text, DOSE_RE)) {
    const key = m.raw.toLowerCase().replace(/\s+/g, '');
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ raw: m.raw.replace(/\s+/g, ' ').trim(), evidence: m.snippet });
    if (out.length >= 6) break;
  }
  return { candidates: out, confidence: out.length ? 'low' : 'none' };
}

// ---------- ⑤ 系统综述纳入研究数（豆瓣 Reviewer 判读 SR 质量的关键变量）----------
function detectIncludedStudies(text) {
  const cands = [];
  const re = /\b(\d{1,3})\s+(?:randomi[sz]ed controlled\s+|controlled\s+|clinical\s+|original\s+)?(?:studies|trials|articles|papers|publications)\b/gi;
  for (const m of matchAll(text, re)) cands.push({ value: parseInt(m.raw.match(/\d+/)[0], 10), evidence: m.snippet });
  return { value: cands.length ? Math.max(...cands.map(c => c.value)) : null, candidates: cands.slice(0, 3) };
}

// ---------- 主入口：单条分级 ----------
const isReviewishGlobal = t => ['review_narrative', 'meta_analysis'].includes(t);
function gradeRecord(rec, opts = {}) {
  const nowYear = (opts.asOfYear || new Date().getFullYear());
  const full = rec.enrich && rec.enrich.abstractFull;
  const abs = full || rec.abstractEn || '';
  const title = rec.titleEn || '';
  const text = [title, abs].filter(Boolean).join(' — ').replace(/\s+/g, ' ').trim();

  const inputs = {
    abstractSource: full ? 'epmc_full' : (rec.abstractEn ? 'site_snippet' : 'title_only'),
    textLength: text.length,
  };

  // 短文本守卫阈值需按语言分档：单个汉字的信息量远高于一个 ASCII 字符，
  // 若用统一的长度阈值，中文题名（常仅 15~25 字）会被误判为「信息不足」而完全不分级。
  const cjkCount = (text.match(/[\u4e00-\u9fa5]/g) || []).length;
  const minLen = cjkCount > text.length * 0.3 ? 18 : 40;
  if (Array.from(text).length < minLen) {
    return {
      version: VERSION, needsReview: true, inputs, minLengthApplied: minLen,
      // ⚠ 早退桩必须与正常返回**完全同构**：下游报告层直接读这些字段，
      //    少一个字段就会在渲染时崩（2026-10-04 实测因缺 targetSpecies 崩溃）。
      designLevel: { value: 'U', label: '文本过短，未分级', confidence: 'none', candidates: [], conflictingTypes: [], topType: null },
      speciesRelevance: { relevance: 'unclear', label: '未识别到物种', confidence: 'none', detected: [], targetSpecies: [], diseaseNameMentions: [], needsManualExclude: true },
      sampleSize: { value: null, candidates: [], confidence: 'none' },
      dose: { candidates: [], confidence: 'none' },
      evidenceGrade: 'D', evidenceGradeLabel: GRADE_LABEL.D,
      publicationYear: rec.year || null, yearsSincePublication: null, recency: null,
      minLengthApplied: minLen, gradeSkipped: true,
      gradeBasis: 'text_too_short',
      includedStudies: { value: null, candidates: [] },
      gradedAt: null,
      flags: ['text_too_short', 'no_engine_run'], confidence: 'none',
    };
  }

  const design = detectDesign(text);
  const species = detectSpecies(text, title);
  const sample = detectSampleSize(text);
  const dose = detectDose(text);
  const studies = detectIncludedStudies(text);

  const grade = (GRADE_MATRIX[species.relevance] || GRADE_MATRIX.unclear)[design.value] || 'D';

  const flags = [];
  if (species.needsManualExclude) flags.push('non_target_species_verify');
  if (design.conflictingTypes && design.conflictingTypes.length) flags.push('design_conflict');
  if (inputs.abstractSource === 'site_snippet') flags.push('grading_from_snippet_only');
  if (inputs.abstractSource === 'title_only') flags.push('grading_from_title_only');
  if (design.value === 'U') flags.push('design_unknown');
  if (sample.value !== null && sample.value < 8) flags.push('small_sample_check');
  if (isReviewishGlobal(design.topType) || design.candidates.some(c => ['review_narrative', 'meta_analysis'].includes(c.type))) flags.push('review_not_primary');
  // 体外试验但物种词来自靶动物 → 是「犬猫细胞」，与「活体犬猫」不能等同对待，必须标记
  if (design.topType === 'in_vitro' && species.relevance === 'target_species') flags.push('in_vitro_target_species_cells');

  const years = rec.year ? nowYear - Number(rec.year) : null;
  const confidences = [design.confidence, species.confidence];
  const overall = confidences.includes('none') ? 'low' : (confidences.every(c => c === 'high') ? 'high' : (confidences.includes('low') ? 'low' : 'medium'));
  if (inputs.abstractSource !== 'epmc_full' && overall !== 'low') { /* 摘要不足时不抬高 */ }

  return {
    version: VERSION,
    needsReview: true,                 // 恒为 true：候选值必须经人工确认后才可用于宣称支撑
    gradedAt: new Date().toISOString(),
    inputs,
    designLevel: design,
    speciesRelevance: species,
    sampleSize: sample,
    dose: dose,
    includedStudies: design.value === 'L1' || isReviewishGlobal(design.topType) ? studies : { value: null, candidates: [] },
    evidenceGrade: grade,
    evidenceGradeLabel: GRADE_LABEL[grade],
    publicationYear: rec.year || null,
    yearsSincePublication: years,
    minLengthApplied: minLen,
    gradeSkipped: false,
    recency: years === null ? null : (years <= 5 ? '≤5年' : years <= 10 ? '6-10年' : years <= 20 ? '11-20年' : '>20年'),
    // ★v4.3：D 档成因区分 —— 下游据此把「因信息不足未判定」与「已判定但证据薄弱」分开呈现，
    //          避免真实试验被 U→D 的静默传导埋没（实测 36% 记录落 D 的主因即 design=U）。
    gradeBasis: design.value === 'U' ? 'design_unrecognized' : 'design_identified',
    flags,
    confidence: inputs.abstractSource === 'epmc_full' ? overall : 'low',
  };
}

/** 批量分级（纯函数，无网络） */
function gradeAll(groups) {
  let n = 0;
  const gradeStat = {};
  const designStat = {};
  const speciesStat = {};
  const flagStat = {};
  const gradeBasisStat = {};          // ★v4.3：D 档成因分布（design_unrecognized / identified / text_too_short）
  for (const g of groups) {
    for (const r of g.records) {
      r.evidence = gradeRecord(r);
      n++;
      gradeStat[r.evidence.evidenceGrade] = (gradeStat[r.evidence.evidenceGrade] || 0) + 1;
      const b = r.evidence.gradeBasis || 'unknown';
      gradeBasisStat[b] = (gradeBasisStat[b] || 0) + 1;
      const d = r.evidence.designLevel.value;
      designStat[d] = (designStat[d] || 0) + 1;
      const s = r.evidence.speciesRelevance.relevance;
      speciesStat[s] = (speciesStat[s] || 0) + 1;
      for (const f of r.evidence.flags) flagStat[f] = (flagStat[f] || 0) + 1;
    }
  }
  return {
    graded: n, gradeStat, designStat, speciesStat, flagStat, gradeBasisStat,
    needsManualExcludeCount: groups.reduce((a, g) => a + g.records.filter(r => r.evidence.speciesRelevance.needsManualExclude).length, 0),
    lowConfidenceCount: groups.reduce((a, g) => a + g.records.filter(r => r.evidence.confidence === 'low').length, 0),
  };
}

module.exports = {
  VERSION, GRADE_MATRIX, GRADE_LABEL, DESIGN_RULES, SPECIES_RULES,
  gradeRecord, gradeAll, detectDesign, detectSpecies, detectSampleSize, detectDose, matchAll, snippet,
};
