/**
 * 饲喂指导书（Feeding Guide）：把「配方 + 个体档案 + 体况评分」编成一份
 * 可以直接打印交给宠主（或随货附送）的饲喂方案。
 *
 * ## 为什么单独立一个模块
 * `nutrition.js` 已经能算 RER/MER 与「每日克数」（`dailyFeeding`），但那只是一行数字；
 * 一份能交付的指导书还要回答：**分几餐、每餐多少、怎么换粮、多久复查、什么时候该调整、
 * 怎么保存、什么情况下必须找兽医**。这些是**编排**而不是营养学公式，
 * 放在这里，好让 `nutrition.js` 保持「纯计算」的职责。
 *
 * ## 三件事刻意分开，不许互相冒充
 * | 类型 | 例子 | 处理方式 |
 * |---|---|---|
 * | **有出处可算的** | RER/MER、每餐克数、成本、钙磷摄入 | 直接给数值，附出处 |
 * | **经验规则的** | BCS→理想体重、BCS→能量调整幅度 | 给数值但**明标「经验估算」**，不作承诺 |
 * | **必须由人判断的** | 目标体重、是否减重、疾病状态下怎么喂 | **只给提示与条件，不替用户决定** |
 *
 * 依据与出处：
 * - RER `70 × BW^0.75`（犬）/ `70 × BW^0.67`（猫）—— NRC 2006（复用 `nutrition.js`）。
 * - 状态系数（生长/绝育/老年/妊娠/泌乳/减脂）—— NRC 2006 + AAFCO 犬猫营养学要点的通行用法。
 * - 9 分制体况评分（BCS）—— 犬猫通用（Laflamme 1997 的 9 分制），4~5 分为理想。
 * - **每 1 分 BCS 高于 5 分 ≈ 超过理想体重 10%** —— 临床经验规则，**非实验结论**，
 *   因此 `idealWeightFromBcs` 的返回值一律带 `empirical:true`，界面要照原样标出。
 * - 生长终点（犬按体型 12/15/18 月龄；猫 12 月龄）—— AAFCO 犬猫营养概要的通行划分。
 * - 换粮过渡 7 天（25%→50%→75%→100%）—— 临床与厂商标配做法。
 *
 * ## 与界面文案有关的硬约束
 * React **不解析 Markdown**，所以本文件产出的所有字符串里**不得出现 `**`**；
 * 需要强调时用普通中文表述（由 `jsx-text-markdown-test.mjs` 静态扫描守住）。
 *
 * ## 缺数据怎么办
 * 不静默兜底。缺的输入逐项记进 `missing`，缺到算不出克数时 `ok:false` 并说明原因，
 * 但**指导书其余部分照常给出**（体况、换粮、储存、观察这些不依赖配方能量）。
 */

import { parseAge, identifyBreed, sizeFromWeight, SIZE_LABELS, sexLabel } from './nutrition.js'
import { restingEnergy, DEFAULT_SPECIES } from './energy.js'
import { normSpecies } from './species.js'
import {
  bcsChartFor, bcsChartRow, inObesityScreeningZone, isIdealFor, idealScoresFor,
  BCS_SPECIES_NOTE, BCS_CHART_CAVEATS, BCS_OBESITY_SCREENING_ZONE, BCS_CHART_COLUMNS,
  bcsChartSourceText, normBcsSpecies,
} from './bcsChart.js'

const r0 = (n) => Math.round(n)
const r1 = (n) => Math.round(n * 10) / 10
const r2 = (n) => Math.round(n * 100) / 100
const num = (v) => (Number.isFinite(Number(v)) ? Number(v) : 0)

/* ================= 1. 体况评分 BCS（9 分制，犬猫通用） ================= */

/**
 * 9 分制体况评分。`group` 为四档归类，`energyAdjPercent` 为**建议的能量调整幅度**
 * （在 MER 基础上乘 `1 + adj/100`，即 +10 表示加 10%）。
 *
 * ⚠ `energyAdjPercent` 是**经验值、不是剂量**：真正执行前要由人（最好含兽医）
 *   确认目标体重。正数（偏瘦）用于增重、负数（偏胖）用于减重。
 */
export const BCS_SCALE = [
  {
    score: 1, label: '极度消瘦', group: 'thin',
    touch: '肋骨、腰椎、骨盆明显可见，无体脂，肌肉量显著下降',
    energyAdjPercent: 25, vetRequired: true,
  },
  {
    score: 2, label: '明显偏瘦', group: 'thin',
    touch: '肋骨易见、无体脂，腰椎与骨盆突出',
    energyAdjPercent: 20, vetRequired: true,
  },
  {
    score: 3, label: '偏瘦', group: 'thin',
    touch: '肋骨易触及、几乎无体脂覆盖，腰线明显凹陷',
    energyAdjPercent: 10, vetRequired: false,
  },
  {
    score: 4, label: '略瘦', group: 'ideal',
    touch: '肋骨易触及、有薄层体脂，俯视有明显腰线',
    energyAdjPercent: 0, vetRequired: false,
    /* ⚠ 这一行的 group / energyAdjPercent 是**犬口径**：犬 4 分是理想。
       猫的 4 分**不是**理想（猫理想只有 5 分），但本表的 label/group 无法按物种分叉
       —— 表是全局一份。要按物种取值，唯一入口是 `bcsGroupFor()` / `bcsPolicy()`；
       直接读本表判物种就会把猫 4 分判成「理想 + 维持量」。 */
  },
  {
    score: 5, label: '理想', group: 'ideal',
    touch: '肋骨可触及但不显见，腰线清晰，腹部上提',
    energyAdjPercent: 0, vetRequired: false,
  },
  {
    score: 6, label: '略胖', group: 'over',
    touch: '肋骨需轻压才触及，腰线不明显，腹部略有下坠',
    energyAdjPercent: -10, vetRequired: false,
  },
  {
    score: 7, label: '偏胖', group: 'over',
    touch: '肋骨需重压才触及，腰线几乎不可见，腹部圆',
    energyAdjPercent: -20, vetRequired: false,
    /* ⚠ 7 分落在「临床肥胖筛查区」（7~9）内：它不强制必须先就医（那还是 8 分起），
       但按 APOP/AAHA 口径应触发一次以肥胖为目标的兽医评估。以前漏了这一档。 */
    screeningZone: true,
  },
  {
    score: 8, label: '肥胖', group: 'obese',
    touch: '肋骨难以触及，腰线消失，腹部明显下垂、活动减少',
    energyAdjPercent: -30, vetRequired: true, screeningZone: true,
  },
  {
    score: 9, label: '严重肥胖', group: 'obese',
    touch: '肋骨不可触及，大量脂肪堆积，腹部膨大下垂',
    energyAdjPercent: -40, vetRequired: true, screeningZone: true,
  },
]

export const BCS_GROUPS = {
  thin: { label: '偏瘦', range: [1, 3] },
  /* ⚠ `range` 是**犬口径**（犬 4~5 分理想）。猫只有 5 分理想，所以
     「4 分属不属于理想」**不能**用本表的 range 判断，必须用
     `idealScoresFor(species)` / `bcsGroupFor(species, score)`。 */
  ideal: { label: '理想', range: [4, 5] },
  over: { label: '偏胖', range: [6, 7] },
  obese: { label: '肥胖', range: [8, 9] },
}

/**
 * 各档「怎么看」的一句话 —— 界面参考图与导出文档**共用同一份文案**。
 * 判据只有两条：侧视看腹部上提、俯视看腰线内收；写在这里避免两处各写一套而分叉。
 */
export const BCS_VIEW_HINT = {
  thin: '侧视：腹部明显上提，肋骨与腰椎、骨盆可见；俯视：腰部内收成明显沙漏形',
  ideal: '侧视：腹部轻度上提，肋骨能摸到但不突出；俯视：腰部在肋骨后轻微内收',
  over: '侧视：腹部无明显上提甚至下垂；俯视：腰部内收消失，躯干成直筒或向外鼓',
  obese: '侧视：腹部明显下垂、腰线完全消失；俯视：躯干整体外鼓呈椭圆形',
}

/** 体况自检的两步法（不看图也能做，长毛动物必须靠触摸） */
export const BCS_SELFTEST = [
  '第一步·触摸：双手拇指沿脊柱两侧、其余手指贴着肋骨滑动，判断肋骨上覆盖的脂肪厚度',
  '第二步·俯视：从正上方看，肋骨后方应有可见的腰部内收；看不到内收即为偏胖',
  '第三步·侧视：从侧面看，肋骨后方到后腿之间应有腹部上提；下垂平直即为偏胖',
  '长毛动物（长毛猫、萨摩耶、松狮等）腰线会被毛量掩盖，必须以触摸肋骨与腰椎为准',
]

/**
 * 安全的体重变化速度（每周占当前体重的百分比）。
 * 依据：AAHA 2021《Nutrition and Weight Management Guidelines for Dogs and Cats》及减重共识
 *   · 犬减重 1%~2%/周；猫减重 0.5%~1%/周
 *   · 增重不超过 2%/周（更快的增量基本都是脂肪）
 * ⚠ 以前犬猫统一写「0.5%~1%」—— 那是**猫**的速度：对犬过于保守（拖长疗程、掉肌肉），
 *   对猫又漏掉了「更快会诱发肝脂肪沉积（hepatic lipidosis，可致命）」这个风险提示。
 */
export const WEIGHT_CHANGE_RATE = {
  dog: { lose: [1, 2], gain: [0.5, 2] },
  cat: { lose: [0.5, 1], gain: [0.5, 2] },
}

/** 把速度区间写成「1%~2%」这样的文案（界面/文档/测试共用一份） */
export function weightChangeText(species, kind = 'lose') {
  const r = (WEIGHT_CHANGE_RATE[normSpecies(species)] || WEIGHT_CHANGE_RATE[DEFAULT_SPECIES])[kind]
  return `${r[0]}%~${r[1]}%`
}

/**
 * 零食、加餐、人食与用于喂药的食物，合计**不应超过每日总能量的 10%**。
 * 依据：WSAVA《Nutritional Assessment Guidelines》(2011) 把「零食/人食 > 每日总热量 10%」
 * 明确列为营养风险因素（Nutritional Screening Risk Factor）；AAHA 2021 同口径
 * （全价粮应提供 ≥90% 热量）。
 * ⚠ 这一条以前只写在成年期的阶段提示里，且不给数字 —— 宠主拿不到「到底能喂多少」。
 */
export const TREAT_ENERGY_MAX_PERCENT = 10

/**
 * 肌肉状况评分（MCS）提示。
 * 依据：WSAVA 2011 指南 —— BCS 评的是**脂肪**，MCS 评的是**肌肉**，两者必须分开看：
 * 触摸颞骨、肩胛骨、腰椎、骨盆处；肌肉流失在多数急慢性病中比单纯饥饿更严重，
 * 且与死亡率独立相关。减重期与老年动物尤其容易「体重下降但掉的是肌肉」。
 */
export const MCS_HINT = [
  'BCS 评的是脂肪，肌肉要另外摸：双手手指分别贴住颞骨（太阳穴）、肩胛骨、腰椎两侧与骨盆，感受肌肉厚度',
  '颞骨、肩胛、腰椎、骨盆处能明显摸到骨头轮廓并凹陷，即为肌肉流失（轻度 → 明显 → 严重）',
  '减重期与老年动物最容易被忽略：体重在降，但如果掉的是肌肉，说明能量下调过猛或蛋白不足',
]

/** 取 BCS 条目；非法/缺失返回 null（**不替用户假定 5 分**） */
export function bcsEntry(score) {
  const n = Math.round(Number(score))
  if (!Number.isFinite(n) || n < 1 || n > 9) return null
  return BCS_SCALE[n - 1]
}

/** 归类：'thin' | 'ideal' | 'over' | 'obese' | null —— ⚠ **物种无关**（犬口径），
 *  要判「是不是理想」请用 `bcsGroupFor(species, score)`。 */
export function bcsGroup(score) {
  const e = bcsEntry(score)
  return e ? e.group : null
}

/**
 * 按物种校正后的归类 —— **判「理想档」的唯一入口**，不要直接用 `bcsGroup()`。
 *
 * 为什么需要：四档归类里只有「ideal」的成员资格是**物种相关**的（犬 4~5 分、猫仅 5 分）。
 * `BCS_SCALE` 与 `BCS_GROUPS.range` 都是全局一份、按犬口径写死，于是猫 4 分会落进 ideal 档
 * —— 而它其实是偏瘦。这里把「不属于该物种理想区的 ideal 分」统一降为 thin 档。
 *
 * 真源只有一处：`BCS_SPECIES_NOTE[species].idealScores`（经 `isIdealFor()` 读取）。
 */
export function bcsGroupFor(species, score) {
  const e = bcsEntry(score)
  if (!e) return null
  if (e.group !== 'ideal') return e.group
  return isIdealFor(species, e.score) ? 'ideal' : 'thin'
}

/**
 * 给界面用的完整体况策略（含建议与是否必须先看兽医）
 * @param {number|string} score    BCS 1~9
 * @param {'dog'|'cat'} species    物种 —— 减重速度按物种分档，**不能共用一套数值**
 */
export function bcsPolicy(score, species = DEFAULT_SPECIES) {
  const sp = normBcsSpecies(species)
  const lose = weightChangeText(sp, 'lose')
  const gain = weightChangeText(sp, 'gain')
  const e = bcsEntry(score)
  if (!e) {
    return {
      ok: false,
      score: null,
      species: sp,
      idealText: BCS_SPECIES_NOTE[sp].idealText,
      note: '未填写体况评分（BCS 1~9）：以下按「理想体况」给出维持量，请评估后重新生成',
    }
  }
  /* 分组必须按物种校正：猫 4 分在 `BCS_SCALE` 里归 ideal，但它其实偏瘦。
     `group` / `groupLabel` / `advice` / `energyAdjPercent` 全部由这一个值派生，
     所以只要这里是校正后的值，四者就不会再互相矛盾。 */
  const group = bcsGroupFor(sp, e.score)
  const g = BCS_GROUPS[group]
  const advice = {
    thin: `当前偏瘦：先排查寄生虫、消化吸收与潜在疾病，再考虑增加饲喂量；增重速度建议不超过每周体重的 ${gain}（更快的增量基本都是脂肪）`,
    ideal: '体况理想：按维持量饲喂，保持每周固定称重、每月复评体况',
    over: `当前偏胖：按建议幅度下调喂食量，同时增加运动；减重速度控制在每周体重的 ${lose}`
      + (sp === 'cat' ? '，不得更快 —— 猫减重过快会诱发肝脂沉积症（俗称猫脂肪肝），可危及生命' : ''),
    obese: '已达到肥胖：减重方案请先由兽医确认目标体重与减重速度，本表数值仅作参考'
      + (sp === 'cat' ? '；猫尤其要控速，过快的减重可诱发肝脂沉积症（俗称猫脂肪肝）' : ''),
  }[group]
  const row = bcsChartRow(sp, e.score)
  const screening = inObesityScreeningZone(e.score)
  const ideal = isIdealFor(sp, e.score)
  /* 分组被降级时（猫 4 分：ideal→thin），能量系数不能沿用原档的 0（=维持量），
     要取目标档里**最接近理想**那一档的幅度（thin 档 1/2/3 分 → 3 分的 +10%）。
     只改分组不改系数 = 一只偏瘦的猫仍按维持量喂，等于维持偏瘦。 */
  const energyAdjPercent = group === e.group
    ? e.energyAdjPercent
    : BCS_SCALE.filter((x) => x.group === group).pop().energyAdjPercent
  return {
    ok: true,
    species: sp,
    score: e.score,
    /* 名称按物种取：判定表（bcsChart.js）才是名称真源，`BCS_SCALE` 只提供能量参数 */
    label: row ? row.label : e.label,
    group,
    groupLabel: g.label,
    touch: e.touch,
    energyAdjPercent,
    vetRequired: e.vetRequired,
    /* 临床肥胖筛查区（BCS 7~9）：是筛查阈值、不是诊断 */
    screeningZone: screening,
    screeningNote: screening
      ? `当前评分落在${BCS_OBESITY_SCREENING_ZONE.label}（BCS ${BCS_OBESITY_SCREENING_ZONE.from}~${BCS_OBESITY_SCREENING_ZONE.to}）：建议请兽医做一次以肥胖为目标的评估（含体况、肌肉状况、体重趋势、饮食史、活动能力与体检）。这是一个筛查阈值，不等于确诊 —— BCS 本身不能诊断临床肥胖。`
      : null,
    /* 该物种是否处于理想区：犬 4~5 分，猫只有 5 分 */
    idealForSpecies: ideal,
    idealText: BCS_SPECIES_NOTE[sp].idealText,
    /* 出处口径：不在理想区就建议兽医评估一次（不等于必须先就医，那是 vetRequired） */
    vetAdvise: ideal
      ? null
      : `按 9 分制评分口径，任何不在理想区的评分（${BCS_SPECIES_NOTE[sp].idealText}）都建议请兽医团队评估一次`,
    /* 该物种、该分数对应的逐分判据（界面与文档的「体况特征」用这一份，比整档一句更准） */
    fatText: row ? row.fatText : null,
    criteria: row ? { lateral: row.lateral, dorsal: row.dorsal, palpation: row.palpation } : null,
    advice,
    /* 结构化速度区间：导出文档要单独成行显示，不靠解析 advice 里那句话 */
    weightRate: { lose, gain, unit: '%/周' },
  }
}

/**
 * 组装给界面与导出文档渲染用的 BCS 判定表。
 *
 * 界面、HTML 导出、纯文本导出**三处共用这一份**：列名、物种注意点、误差说明、出处
 * 只在这里写一次，避免三处各抄一套而行成难被发现的分叉。
 * ⚠ 行数据来自 `bcsChart.js`（唯一出处），本函数只做**装配**，不再重写判据文案。
 */
export function bcsChartPayload(species) {
  const sp = normBcsSpecies(species)
  const note = BCS_SPECIES_NOTE[sp]
  return {
    species: sp,
    speciesLabel: sp === 'cat' ? '猫' : '犬',
    columns: BCS_CHART_COLUMNS,
    rows: bcsChartFor(sp),
    idealScores: idealScoresFor(sp),
    idealText: note.idealText,
    notes: note.notes,
    caveats: BCS_CHART_CAVEATS,
    screeningZone: BCS_OBESITY_SCREENING_ZONE,
    source: bcsChartSourceText(),
  }
}

/**
 * 由体况评分反推理想体重。
 *
 * 依据：**每 1 分 BCS 高于 5 分，约相当于超过理想体重 10%** —— 犬猫临床通行经验规则。
 * ⚠ 这是经验估算，不是实验结论，返回值带 `empirical:true`，界面上必须标出。
 * BCS ≤ 5（不超重）时返回 null：**偏瘦一侧不能这样反推**，理想体重应由品种标准/兽医给。
 *
 * @param {number} currentKg 当前体重 kg
 * @param {number} score     BCS 1~9
 * @returns {{kg:number, reducePercent:number, deltaKg:number, empirical:true, note:string}|null}
 */
export function idealWeightFromBcs(currentKg, score) {
  const w = Number(currentKg)
  const e = bcsEntry(score)
  if (!Number.isFinite(w) || w <= 0 || !e) return null
  if (e.score <= 5) return null
  const excess = 0.1 * (e.score - 5)
  const kg = w / (1 + excess)
  return {
    kg: r1(kg),
    reducePercent: r1((1 - kg / w) * 100),
    deltaKg: r1(w - kg),
    empirical: true,
    note: '按「每 1 分 BCS 高于 5 分 ≈ 超过理想体重 10%」估算，属经验规则；目标体重请由兽医确认',
  }
}

/* ================= 2. 生命阶段与分餐 ================= */

/** 生长终点（月龄）：超过即视为成年骨架已基本定型 */
export const GROWTH_END_MONTHS = {
  cat: 12,
  dog: { small: 12, medium: 15, large: 18 },
}

/** 老年起点（月龄）：犬按体型分档（体型越大越早），猫取 8 岁 */
export const SENIOR_FROM_MONTHS = {
  cat: 96,
  dog: { small: 96, medium: 84, large: 72 },
}

/** 离乳完成（月龄）：约 6~8 周，取 2 个月 */
export const WEANED_MONTHS = 2

export function growthEndMonths(species, size) {
  if (species === 'cat') return GROWTH_END_MONTHS.cat
  const s = size && GROWTH_END_MONTHS.dog[size] ? size : 'medium'
  return GROWTH_END_MONTHS.dog[s]
}

export function seniorFromMonths(species, size) {
  if (species === 'cat') return SENIOR_FROM_MONTHS.cat
  const s = size && SENIOR_FROM_MONTHS.dog[size] ? size : 'medium'
  return SENIOR_FROM_MONTHS.dog[s]
}

/**
 * 判定生命阶段。
 *
 * 优先级：显式生理状态（妊娠/泌乳）> 月龄推断 > 状态兜底。
 * ⚠ **不给年龄也不给状态时返回 `id:'unknown'`**（`assumed:true`），
 *   由调用方去提示补填 —— 不假装是成年期。
 *
 * @param {Object} profile { species, ageMonths, ageText, status, size, weightKg }
 */
export function lifeStage(profile = {}) {
  const species = profile.species === 'dog' ? 'dog' : 'cat'
  const status = profile.status || ''
  if (status === 'gestation') {
    return { id: 'gestation', label: '妊娠期', assumed: false, desc: '怀孕中后期，能量与蛋白需求上升' }
  }
  if (status === 'lactation') {
    return { id: 'lactation', label: '泌乳期', assumed: false, desc: '哺乳中，能量需求可达维持量的数倍' }
  }
  if (status === 'weight_loss') {
    return { id: 'weight_loss', label: '减脂期', assumed: false, desc: '按减重目标控制能量摄入' }
  }

  let size = profile.size
  if (!size && profile.breed) size = identifyBreed(profile.breed)?.size
  if (!size && species === 'dog') size = sizeFromWeight(species, profile.weightKg)

  const m = profile.ageMonths ?? parseAge(profile.ageText)
  if (m === null || m === undefined || !Number.isFinite(Number(m))) {
    return {
      id: 'unknown',
      label: '未判定（缺年龄）',
      assumed: true,
      desc: '未填写年龄，无法判定生命阶段；以下按成年维持量的常规做法给出，请补填年龄后重新生成',
      species, size: size || null,
    }
  }
  const age = Number(m)
  if (age < WEANED_MONTHS) {
    return { id: 'neonate', label: '哺乳/离乳期', assumed: false, desc: '尚未完全离乳，以母乳/代乳为主，固体食物需泡软少量尝试', species, size: size || null }
  }
  const gEnd = growthEndMonths(species, size)
  if (age < gEnd) {
    return {
      id: 'growth', label: '生长期', assumed: false,
      desc: `骨架仍在发育（本阶段按 ${gEnd} 月龄前为生长期），能量与钙磷需求高于成年`,
      species, size: size || null, growthEndMonths: gEnd,
    }
  }
  const sFrom = seniorFromMonths(species, size)
  if (age >= sFrom) {
    return {
      id: 'senior', label: '老年期', assumed: false,
      desc: `已进入老年期（本阶段起点 ${Math.round(sFrom / 12)} 岁），建议提高复查频率、关注肾功能与关节`,
      species, size: size || null, seniorFromMonths: sFrom,
    }
  }
  return { id: 'adult', label: '成年期', assumed: false, desc: '维持期，重点是保持理想体况', species, size: size || null }
}

/**
 * 每日餐数。依据：幼龄胃容量小、需少食多餐；成年 2 餐；
 * 妊娠/泌乳期胃容量被挤压或能量需求高、宜加餐。
 */
export function mealsPerDay(stage, ageMonths, species) {
  const id = stage?.id
  const m = Number(ageMonths)
  if (id === 'neonate') return 4
  if (id === 'growth') {
    if (Number.isFinite(m) && m <= 3) return 4
    if (Number.isFinite(m) && m <= 6) return 3
    return 3
  }
  if (id === 'gestation') return 3
  if (id === 'lactation') return 3
  if (id === 'senior') return species === 'cat' ? 3 : 2
  if (id === 'weight_loss') return 2
  return 2
}

/* ================= 3. 换粮过渡 / 观察 / 储存 ================= */

/**
 * 妊娠期按周能量增量（NRC 2006 参考）。
 *
 * ⚠ 系统里 `status='gestation'` 的 MER 系数是一个**整期平均值**（猫 2.0 / 犬 2.5），
 *   那是为了方便快速估值；真实需求是**逐周递增**的。这张表把曲线补出来，
 *   并明确写「整期平均值只是快速估值」—— 否则用户会拿整期系数当某一周的实际需求。
 */
export const GESTATION_WEEKLY = {
  cat: [
    { week: '第 1~4 周', adj: '维持量', percent: 0 },
    { week: '第 5~6 周', adj: '+25%', percent: 25 },
    { week: '第 7~8 周', adj: '+25%~50%', percent: 38 },
    { week: '第 9 周（临产）', adj: '+50%~60%', percent: 55 },
  ],
  dog: [
    { week: '第 1~4 周', adj: '维持量', percent: 0 },
    { week: '第 5~6 周', adj: '+10%~20%', percent: 15 },
    { week: '第 7~8 周', adj: '+20%~30%', percent: 25 },
    { week: '第 9 周（临产）', adj: '+30%~50%（窝仔数多时取上限）', percent: 40 },
  ],
}

/** 分物种饮水量建议（mL/kg 体重/日） */
export const WATER_GUIDE = {
  dog: { min: 50, max: 60, note: '约等于每 1 kcal 能量 1 mL' },
  cat: { min: 40, max: 50, note: '猫主动饮水少，干粮饲喂时下泌尿道风险升高，需特别注意' },
}

/**
 * 哪些生命阶段**允许**按体况调能量（返回 null 表示允许）。
 *
 * ⚠⚠ 这条闸门不是可有可无一 —— 少了它会给出**有害建议**：
 * - `growth` / `neonate`：幼龄动物**按需供给**，限饲会直接影响骨骼与器官发育；
 * - `gestation` / `lactation`：妊娠泌乳期能量需求本来就要往上加，扣减会伤母体与幼崽；
 * - `weight_loss`：`computeRequirements` 的 `weight_loss` 系数（猫 0.8 / 犬 1.0）
 *   **已经包含**减重扣减，再叠一层 BCS 调整就是**双重扣减**。
 * 只有在成年维持期与老年期，「体况偏离 → 微调喂食量」才是合适的做法。
 *
 * @returns {string|null} 不允许时返回原因说明
 */
export function bcsAdjustBlockReason(stage) {
  switch (stage?.id) {
    case 'neonate':
    case 'growth':
      return '生长期按需供给，不做体况扣减 —— 幼龄限饲会影响发育；此处只提示关注体况'
    case 'gestation':
    case 'lactation':
      return '妊娠/泌乳期能量需求向上调整，不做体况扣减；母体体况由兽医跟踪'
    case 'weight_loss':
      return '减脂期已按体重管理系数下调能量，不再叠加体况系数（避免双重扣减）'
    default:
      return null
  }
}

/**
 * 7 天换粮过渡表（标准做法：新粮占比 25% → 50% → 75% → 100%）。
 * 每两天上一档，第 7 天完全换新；出现软便则**退回上一档**并延长 2~3 天。
 *
 * @param {number} [days=7]
 * @param {Object} [grams] 可选 { newG, oldG } —— 给出两种粮各自的**每日克数**
 *        （由 `currentFoodGrams` 折算而来）。给了就把百分比同时换算成克，
 *        否则单看百分比用户没法称重（这一步是方案里承诺的）。
 */
export function transitionPlan(days = 7, grams = null) {
  const n = Math.max(3, Math.round(days) || 7)
  const plan = []
  for (let d = 1; d <= n; d++) {
    let newPct
    if (d >= n) newPct = 100
    else newPct = Math.min(75, Math.round((d / n) * 100 / 25) * 25)
    if (newPct < 25) newPct = 25
    const row = {
      day: d,
      oldPercent: 100 - newPct,
      newPercent: newPct,
      note: d === 1
        ? '第 1~2 天：旧粮为主，先试新粮气味与适口性'
        : (d >= n ? '第 7 天起：完全换成新粮' : '无软便则按表推进'),
    }
    if (grams && Number.isFinite(grams.newG) && Number.isFinite(grams.oldG)) {
      row.newG = r0((grams.newG * newPct) / 100)
      row.oldG = r0((grams.oldG * (100 - newPct)) / 100)
    }
    plan.push(row)
  }
  return plan
}

/**
 * 现粮折算：把「同热量」换算成当前饲粮的克数。
 *
 * 用途是让 7 天过渡表的百分比能落成**两种粮各自的克数** ——
 * 否则用户拿 25%/75% 没法上秤。
 *
 * @param {number} mePerKg   当前饲粮代谢能 kcal/kg（原样基础）
 * @param {number} targetKcal 目标每日能量 kcal
 * @returns {{mePerKg:number, gramsPerDay:number, note:string}|null}
 */
export function currentFoodGrams(mePerKg, targetKcal) {
  const me = Number(mePerKg)
  const kcal = Number(targetKcal)
  if (!Number.isFinite(me) || me < 100 || !Number.isFinite(kcal) || kcal <= 0) return null
  return {
    mePerKg: r0(me),
    gramsPerDay: r0((kcal / me) * 1000),
    note: '按「与目标能量相同」折算，未考虑两种粮的消化率差异；换粮期请以体重变化为准微调',
  }
}

/** 观察与调整：给固定的复查节奏，避免「全凭感觉」 */
export function monitoringPlan(stage, policy) {
  const senior = stage?.id === 'senior'
  const growth = stage?.id === 'growth' || stage?.id === 'neonate'
  const out = [
    {
      item: '体重',
      frequency: growth ? '每周 1 次' : (senior ? '每 2 周 1 次' : '每 2 周 1 次'),
      howTo: '同一时间（建议晨起空腹）、同一台秤称重，记录成曲线',
      action: growth
        ? '幼龄期应稳定上升；连续两周不增或下降需排查'
        : '成年后体重波动超过 ±5% 需复核喂食量与体况',
    },
    {
      item: '体况评分 BCS',
      frequency: senior ? '每月 1 次' : '每 1~2 个月 1 次',
      howTo: '站立位双手触摸肋骨与腰椎，俯视看腰线、侧视看腹部上提',
      action: `目标是 4~5 分；当前评估为 ${policy?.ok ? `${policy.score} 分（${policy.label}）` : '未评估'}，如偏离超过 1 分即调整喂食量 10%`,
    },
    {
      item: '粪便',
      frequency: '换粮期每日、之后每周观察',
      howTo: '看成形度、颜色、气味与是否带黏液/血',
      action: '换粮期软便可退回上一档过渡比例；持续 >2 天或带血请就医',
    },
    {
      item: '食欲与饮水',
      frequency: '每日',
      howTo: '记录剩粮比例与饮水量的明显变化',
      action: '突然拒食超过 24 小时、或饮水量骤增，需就医排查',
    },
    {
      item: '精神与活动',
      frequency: '每日',
      howTo: '对照平时步态、互动意愿与休息时间',
      action: '老年动物出现活动减少、跛行、夜鸣需优先排查疼痛与关节问题',
    },
    {
      item: '喂食量调整',
      frequency: '确需调整时',
      howTo: '每次只动 10%；务必用电子秤称量（精度 ≥1 g），不要用量杯或目测 —— 颗粒密度差异可造成 ±20% 误差',
      action: '调整后观察 1~2 周再复评，连续两次同向偏离才继续同方向调整；不要按「它还想吃」加量',
    },
  ]
  if (growth) {
    out.push({
      item: '生长发育',
      frequency: '每月对照生长曲线',
      howTo: '记录体重与体长，与同品种标准曲线比对',
      action: '生长速度明显落后或超前，需复核能量与钙磷供给',
    })
  }
  if (senior) {
    out.push({
      item: '健康复查',
      frequency: '每 6 个月 1 次',
      howTo: '血常规、生化（含肾指标）、尿检与口腔检查',
      action: '老年动物建议每年至少一次完整体检，指标异常时提前调整配方',
    })
  }
  return out
}

/* ================= 储存口径：产品形态 → 保存方式（唯一映射） =================
 *
 * ⚠ 项目里「产品形态」曾有三处各说各话，这是实测到的真实缺陷：
 *   · `src/data/regulations.js` 的 `PRODUCT_FORMS`：baked / freeze-dried / cat-stick /
 *     extruded / snack / general（全局设置 `settings.productForm`）
 *   · 本模块的 `storageTips()`：原先只认 `wet` / `frozen` / `raw`，其余全落干粮档
 *   · `portionLabel.js` 的 `FORM_TIPS`：frozen_raw / frozen_cooked / dry / wet / unknown
 * 三套 id 互不重叠 ⇒ `storageTips(profile.productForm)` 永远走 `else`（干粮）分支，
 * 湿粮/生食的提示是**死代码**（实测已确认）。
 *
 * 这里把口径收敛成**一套 band**：band 取值 == `portionLabel.FORM_TIPS` 的键，
 * 两边集合相等由守卫断言（`portion-label-ui-test.mjs`）。
 * 新增产品形态**必须**在本表登记；未登记 ⇒ `'unknown'`（显式标出「未指定形态」并按
 * 干粮给通用要点），**不会静默**落到某个具体档。
 *
 * ⚠ 本模块**不 import** `data/regulations.js`（693 行纯数据）—— 那会把它整份拖进 CLI 的
 *   vendor 闭包。两边靠守卫钉住一一对应（同 `TOTAL_DAYS_DEFAULT` ↔ `PURCHASE_DAYS_DEFAULT`）。
 */
export const STORAGE_BANDS = ['dry', 'wet', 'frozen_raw', 'frozen_cooked', 'unknown']

/** `PRODUCT_FORMS.id` → band。键集合必须与 `data/regulations.js` 的 PRODUCT_FORMS 一致（守卫钉住）。 */
export const STORAGE_BAND_BY_FORM = Object.freeze({
  baked: 'dry',
  extruded: 'dry',
  'freeze-dried': 'dry',
  snack: 'dry',
  'cat-stick': 'wet',
  general: 'unknown',
})

/** 早期直传口径的别名（本模块曾直接收 `wet` / `frozen` / `raw`）：归一化到 band。 */
const STORAGE_BAND_ALIAS = Object.freeze({
  dry: 'dry', wet: 'wet', raw: 'frozen_raw', frozen: 'frozen_cooked',
})

/**
 * 产品形态（`PRODUCT_FORMS.id`，也兼容旧的 `dry`/`wet`/`raw`/`frozen`）→ 储存 band。
 * 空串 / 未登记 ⇒ `'unknown'` —— **不猜**，交给 `storageTips` 显式标注。
 */
export function storageBandOf(productForm) {
  const k = typeof productForm === 'string' ? productForm.trim() : ''
  if (!k) return 'unknown'
  // 本口径原值直通（frozen_raw / frozen_cooked / unknown 不在别名表里，漏了这一步会掉进 unknown）
  if (STORAGE_BANDS.includes(k)) return k
  const alias = STORAGE_BAND_ALIAS[k]
  if (alias) return alias
  const mapped = STORAGE_BAND_BY_FORM[k]
  return mapped && STORAGE_BANDS.includes(mapped) ? mapped : 'unknown'
}

/**
 * 储存与喂食安全。
 * @param {string} [band='dry'] band（见 `STORAGE_BANDS`），或旧的 `dry`/`wet`/`raw`/`frozen`
 */
export function storageTips(band = 'dry') {
  const b = storageBandOf(band)
  const base = [
    '开封后密封保存，置于阴凉干燥处（建议 25 摄氏度以下），避免阳光直射与灶台旁高温',
    '干粮开封后建议 4~6 周内用完，避免油脂氧化与维生素衰减',
    '取粮用干燥的勺子，避免手抓或让水汽进入包装',
    '不与清洁剂、农药等化学品同柜存放',
    '出现霉味、结块、虫蛀或有哈喇味（油脂氧化）时整批停用',
  ]
  if (b === 'wet') {
    base.unshift('湿粮/冻干复水后常温放置不宜超过 1 小时，未吃完的及时冷藏并在 24 小时内用完')
    base.push('冷藏取出后回温至室温再喂，避免直接喂冰食刺激肠胃')
  } else if (b === 'frozen_raw') {
    base.unshift('生食需全程冷链（-18 摄氏度冷冻保存），解冻后在冷藏层进行并在 24 小时内喂完')
    base.push('处理生食的器具与台面需单独用热水与洗涤剂清洗，避免交叉污染')
    base.push('生食不得反复冻融：按一次吃完的量分装，解冻后不再回冻')
  } else if (b === 'frozen_cooked') {
    base.unshift('熟食（冷冻）需 -18 摄氏度保存；提前移到冷藏层解冻，回温后再喂')
    base.push('解冻后 24 小时内吃完，剩余部分不要回冻')
  } else if (b === 'unknown') {
    base.unshift('未指定产品形态：以下为通用保存要点，请按实际形态（干粮 / 湿粮 / 生食）核对保存与解冻方式')
    base.push('按一周用量分装小袋、随取随开封，可减少大包装反复开启造成的氧化')
  } else {
    base.unshift('按一周用量分装小袋、随取随开封，可减少大包装反复开启造成的氧化')
  }
  base.push('每日固定时间、固定地点喂食，喂完 15 分钟内未吃完的剩余食物及时收走')
  return base
}

/** 必须就医的警戒信号（与饲喂量无关的硬提示） */
export function vetSignals() {
  return [
    '连续 24 小时以上完全拒食，或幼龄动物 12 小时未进食',
    '呕吐或腹泻超过 2 天，或呕吐物/粪便带血、呈黑色柏油状',
    '饮水与排尿量突然明显增加，或超过 24 小时无排尿',
    '体重在 1~2 周内下降超过 5%，且未主动减重',
    '出现抽搐、持续发抖、呼吸急促、无法站立或明显疼痛表现',
    '妊娠期出现阴道异常分泌物、体温下降或行为焦躁（临近生产）',
  ]
}

/* ================= 4. 主计算 ================= */

/** 性别文案统一取自 nutrition.js 的 sexLabel —— 四档性别（公/母 × 绝育）后
 *  自建映射会漏掉新取值，同一个「neutered_female」在不同文件显示成不同文字。 */

/**
 * 生成饲喂指导书的数据结构（纯函数，无 DOM）。
 *
 * @param {Object} profile 动物档案（可含 bcs / targetWeightKg / mealsPerDay / productForm）
 * @param {Object|null} recipe computeRecipe() 结果（可为 null：能量段随之留空）
 * @param {Object|null} req    computeRequirements() 结果（可为 null：内部会按 profile 现算）
 * @param {Object} [opts]
 * @param {'modified'|'nrc'} [opts.meBasis='modified'] 取哪个代谢能口径算喂食量
 *        —— 默认 `modified` 与站点既有「每日饲喂量」保持一致，避免同一份配方出现两个数
 * @param {Function} [opts.computeRequirements] 注入用（便于测试隔离与避免硬依赖）
 * @returns {Object} 见文件头「三件事刻意分开」的字段约定
 */
export function computeFeedingPlan(profile = {}, recipe = null, req = null, opts = {}) {
  const species = profile.species === 'dog' ? 'dog' : 'cat'
  const sLabel = species === 'cat' ? '猫' : '犬'
  const weightKg = Number(profile.weightKg) > 0 ? Number(profile.weightKg) : null
  const missing = []
  const warnings = []

  const stage = lifeStage(profile)
  if (stage.id === 'unknown') missing.push('年龄（用于判定生命阶段）')
  const policy = bcsPolicy(profile.bcs, species)
  if (!policy.ok) missing.push('体况评分 BCS（1~9）')

  /* ---- 体重缺失：没有体重就没有任何能量计算，直接给出「待补」而不是假数 ---- */
  if (!weightKg) {
    missing.push('体重（kg）')
    warnings.push('缺少体重：每日能量需求与喂食量无法计算，请补填体重后重新生成')
  }

  /* ---- 派生：理想体重（仅超重时给，且明标经验估算） ---- */
  const ideal = policy.ok ? idealWeightFromBcs(weightKg, policy.score) : null
  const targetWeightKg = Number(profile.targetWeightKg) > 0 ? Number(profile.targetWeightKg) : null
  if (policy.ok && policy.group !== 'ideal' && !targetWeightKg && !ideal && policy.group === 'thin') {
    warnings.push('当前偏瘦：理想体重无法由体况评分反推（该规则只适用于超重侧），请由兽医或品种标准给出目标体重')
  }

  /* ---- 能量：优先用传入的 req；否则由调用方注入 computeRequirements 现算 ----
   * 不在这里直接 import `computeRequirements`，是为了让本模块能被单独测试
   * （注入桩函数即可断言「BCS 调整发生在 MER 之后、喂食量之前」）。 */
  let requirements = req
  if (!requirements && weightKg && typeof opts.computeRequirements === 'function') {
    requirements = opts.computeRequirements(profile, {})
  }

  const merBase = requirements?.mer ?? null
  /* ⚠ 体况调整有阶段闸门（见 bcsAdjustBlockReason）：生长期不该限饲、
     妊娠泌乳期不该扣减、weight_loss 系数里已含扣减（叠加即双重扣减）。 */
  const blockReason = bcsAdjustBlockReason(stage)
  const rawAdjPercent = policy.ok ? policy.energyAdjPercent : 0
  const adjPercent = blockReason ? 0 : rawAdjPercent
  const merAdjusted = merBase == null ? null : r0(merBase * (1 + adjPercent / 100))
  if (blockReason && policy.ok && rawAdjPercent) {
    warnings.push(`体况能量调整未启用：${blockReason}（本次按不调整计算）`)
  }

  /* ---- 代谢能：配方侧可能没有（缺水分时 GE/DE 不出数，但 Atwater 两口径仍在） ---- */
  const meModified = recipe?.energy?.meModified ?? null
  const meNRC = recipe?.energy?.meNRC ?? null
  const basis = opts.meBasis === 'nrc' ? 'nrc' : 'modified'
  const meChosen = basis === 'nrc' ? (meNRC ?? meModified) : meModified
  const basisLabel = basis === 'nrc' ? 'NRC 2006 三步法（GE → 消化率 → 扣尿能）' : '改良 Atwater（AAFCO 标签算法）'

  let gramsPerDay = null
  let energyNote = ''
  if (meChosen == null || meChosen < 100) {
    warnings.push('配方缺少可用的代谢能数据（原样基础）—— 多为原料水分未填；请先补齐水分后再生成喂食量')
  } else if (merAdjusted == null) {
    warnings.push('缺少体重或能量需求，无法换算每日喂食量')
  } else {
    gramsPerDay = r0((merAdjusted / meChosen) * 1000)
  }
  /* 两口径差异过大要明说：同一份配方换口径能差 10% 以上，用户有权知道 */
  if (meModified != null && meNRC != null && meModified > 0) {
    const diff = Math.abs(meNRC - meModified) / meModified
    if (diff >= 0.1) {
      energyNote = `两种代谢能口径差异 ${r0(diff * 100)}%（改良 Atwater ${r0(meModified)} kcal/kg vs NRC ${r0(meNRC)} kcal/kg）；`
        + '高纤维或高蛋白配方上差异会被放大，实际喂食量请以体重与体况变化为准'
    }
  }

  /* ---- 分餐 ---- */
  const perDay = Number(profile.mealsPerDay) >= 1
    ? Math.round(Number(profile.mealsPerDay))
    : mealsPerDay(stage, profile.ageMonths ?? parseAge(profile.ageText), species)
  const perMeal = gramsPerDay == null ? null : r0(gramsPerDay / perDay)
  const mealSchedule = []
  if (gramsPerDay != null) {
    /* 分餐克数必须**守恒**：不能各餐都四舍五入成同一个数而合计对不上。
       前 n−1 餐取整、最后一餐用总数减掉，保证 Σ = 每日总量。 */
    let rest = gramsPerDay
    for (let i = 1; i <= perDay; i++) {
      const g = i === perDay ? rest : r0(gramsPerDay / perDay)
      rest -= g
      mealSchedule.push({
        index: i,
        label: `第 ${i} 餐`,
        grams: g,
        hint: i === 1 ? '早晨' : (i === perDay ? '傍晚/睡前' : '日间加餐'),
      })
    }
  }

  /* ---- 零食额度：≤ 每日总能量的 10%（WSAVA 2011 风险因素 / AAHA 2021 同口径） ----
     ⚠ 只写「不超过 10%」等于没写：宠主要的是「到底能喂几克」。换算必须用**同一配方 ME**，
     与主食同一把尺，否则两套数打架。
     ⚠ 这是**上限**而不是配额：喂了零食就要从主食里等量扣掉，否则一天总能量直接超标 ——
     实测宠主普遍超 1 倍以上。 */
  const treats = (merAdjusted == null || meChosen == null || meChosen < 100) ? null : {
    maxPercent: TREAT_ENERGY_MAX_PERCENT,
    maxKcal: r0(merAdjusted * TREAT_ENERGY_MAX_PERCENT / 100),
    maxGrams: r0(((merAdjusted * TREAT_ENERGY_MAX_PERCENT / 100) / meChosen) * 1000),
    note: '零食、加餐、人食以及为了喂药给的食物，合计不得超过这个上限',
    howTo: '喂了零食就从主食里等量扣掉：把主食减少相同克数，当天总能量才不会超标',
  }

  /* ---- 每日营养素摄入（按原样基础换算，用于回答「够不够」） ---- */
  const a = recipe?.asFed || {}
  const intake = gramsPerDay == null ? null : {
    proteinG: r1((num(a.crude_protein) / 100) * gramsPerDay),
    fatG: r1((num(a.crude_fat) / 100) * gramsPerDay),
    fiberG: r1((num(a.crude_fiber) / 100) * gramsPerDay),
    ashG: r1((num(a.crude_ash) / 100) * gramsPerDay),
    caG: r2((num(a.calcium) / 100) * gramsPerDay),
    pG: r2((num(a.phosphorus) / 100) * gramsPerDay),
    kcal: merAdjusted,
    waterFromFoodMl: r0((num(a.moisture) / 100) * gramsPerDay),
  }

  /* ---- 成本 ---- */
  const perKgPrice = recipe?.cost?.perKg ?? null
  const cost = gramsPerDay == null || perKgPrice == null ? null : {
    perDay: r2((perKgPrice * gramsPerDay) / 1000),
    perMonth: r2((perKgPrice * gramsPerDay * 30) / 1000),
    perYear: r2((perKgPrice * gramsPerDay * 365) / 1000),
    pricePerKg: r2(perKgPrice),
  }

  /* ---- 每日喂食量速查：同一只动物、只改「体重」与「体况」两个变量 ---- */
  const gramsOf = (mer) => (mer == null || meChosen == null || meChosen < 100
    ? null
    : r0((mer / meChosen) * 1000))
  /* ⚠ MER 随体重按 RER 等比缩放（RER ∝ W^0.75 犬 / W^0.67 猫，定义在 energy.js），
     状态·体型·活动系数**保持不变** —— 语义是「同一只动物体重变了」，
     不是「换了一只动物」。若重跑 computeRequirements 会连带重算体型系数，那是错的。 */
  const rerNow = restingEnergy(species, weightKg)
  const merAt = (kg) => {
    if (merBase == null || !rerNow || !(Number(kg) > 0)) return null
    return r1(merBase * (restingEnergy(species, Number(kg)) / rerNow))
  }
  const ladder = []
  if (merAdjusted != null) {
    ladder.push({
      key: 'now',
      tag: '当前方案',
      label: `当前体重 ${weightKg} kg · 体况 ${policy.ok ? policy.score : '—'} 分`,
      kg: weightKg,
      mer: merAdjusted,
      grams: gramsPerDay,
      note: policy.ok
        ? `${policy.label}${adjPercent ? `，已按体况调整 ${adjPercent > 0 ? '+' : ''}${adjPercent}%` : ''}${blockReason ? `（本阶段不按体况调整：${blockReason}）` : ''}`
        : '未评估体况，按维持量给出',
    })
  }
  if (adjPercent !== 0 && merBase != null) {
    ladder.push({
      key: 'nowIdeal',
      tag: '仅体况差异',
      label: `当前体重 ${weightKg} kg · 体况 4~5 分`,
      kg: weightKg,
      mer: merBase,
      grams: gramsOf(merBase),
      note: '体重不变、只把体况调到理想时的喂食量；两行的差就是体况调整带来的量',
    })
  }
  if (ideal && ideal.kg > 0) {
    const m = merAt(ideal.kg)
    ladder.push({
      key: 'ideal',
      tag: '理想体重',
      label: `理想体重 ${ideal.kg} kg · 体况 4~5 分`,
      kg: ideal.kg,
      mer: m,
      grams: gramsOf(m),
      note: '按「每高 1 分 BCS 约超重 10%」反推，属经验估算，需兽医确认后再执行',
    })
  }
  const targetDistinct = targetWeightKg && targetWeightKg !== weightKg
    && (!ideal || Math.abs(targetWeightKg - ideal.kg) > 0.05)
  if (targetDistinct) {
    const m = merAt(targetWeightKg)
    ladder.push({
      key: 'target',
      tag: '自定目标',
      label: `目标体重 ${targetWeightKg} kg · 体况 4~5 分`,
      kg: targetWeightKg,
      mer: m,
      grams: gramsOf(m),
      note: '按你在档案里填写的目标体重换算',
    })
  }

  /* ---- 现粮折算：让过渡表的百分比能落成两种粮各自的克数 ---- */
  const curFood = currentFoodGrams(profile.currentFoodMe, merAdjusted)
  if (Number(profile.currentFoodMe) > 0 && !curFood) {
    warnings.push('当前饲粮能量值看起来不是有效的 kcal/kg（应大于 100），现粮折算已跳过')
  }
  const transitionGrams = (curFood && gramsPerDay != null)
    ? { newG: gramsPerDay, oldG: curFood.gramsPerDay }
    : null

  /* ---- 饮水提示：分物种给区间（猫主动饮水少，干粮风险更高）---- */
  const moisture = num(a.moisture)
  const wg = WATER_GUIDE[species]
  const waterRange = weightKg ? `约 ${r0(weightKg * wg.min)}~${r0(weightKg * wg.max)} mL/日` : '按体重 40~60 mL/kg 估算'
  const waterTip = [
    `建议饮水量：${waterRange}（${wg.note}）`,
    moisture > 0 && moisture < 20
      ? `本配方水分仅 ${r1(moisture)}%（干性），食物带入的水${intake ? `约 ${intake.waterFromFoodMl} mL` : '很少'}，必须额外提供充足清水`
      : (moisture >= 20
        ? `本配方水分 ${r1(moisture)}%（湿性），食物已带入${intake ? `约 ${intake.waterFromFoodMl} mL` : '部分'}水，仍建议另备清水自由饮用`
        : '配方水分未填，无法折算食物带入的水量；请按上表额外提供清水'),
    '水碗每日清洗换水；多猫/多犬家庭建议分散放置多个水点',
  ].join('；')

  /* ---- 阶段要点 ---- */
  const stageNotes = stageNotesOf(stage, policy, species)
  if (policy.ok && policy.advice) stageNotes.push(policy.advice)
  if (policy.ok && policy.vetRequired) {
    warnings.push('当前体况为「需兽医评估」档位（BCS ≤ 2 或 ≥ 8）：喂食量调整请先经兽医确认目标体重')
  }

  const ok = weightKg != null && gramsPerDay != null

  return {
    computed: ok,
    species,
    speciesLabel: sLabel,
    pet: {
      name: profile.name || '',
      species,
      speciesLabel: sLabel,
      breed: profile.breed || '',
      size: stage.size || null,
      sizeLabel: stage.size ? SIZE_LABELS[stage.size] : null,
      weightKg,
      ageMonths: profile.ageMonths ?? parseAge(profile.ageText),
      ageText: profile.ageText || '',
      sex: profile.sex || '',
      sexLabel: sexLabel(profile.sex),
      activity: requirements?.activity || profile.activity || '',
      activityLabel: requirements?.activityLabel || '',
      status: requirements?.status || profile.status || '',
      statusLabel: requirements?.statusLabel || '',
      bcs: policy.ok ? policy.score : null,
      bcsLabel: policy.ok ? policy.label : '',
      bcsGroup: policy.group || null,
      bcsGroupLabel: policy.groupLabel || '',
      bcsTouch: policy.ok ? policy.touch : '',
      bcsFatText: policy.ok ? policy.fatText : null,
      bcsScreeningZone: Boolean(policy.ok && policy.screeningZone),
      bcsVetAdvise: policy.ok ? policy.vetAdvise : null,
      idealWeightKg: ideal ? ideal.kg : null,
      idealWeightReducePercent: ideal ? ideal.reducePercent : null,
      targetWeightKg,
      vetRequired: Boolean(policy.ok && policy.vetRequired),
    },
    stage,
    bodyCondition: policy,
    bcsChart: bcsChartPayload(species),
    idealWeight: ideal,
    energy: {
      basis,
      basisLabel,
      mePerKg: meChosen == null ? null : r0(meChosen),
      meModified: meModified == null ? null : r0(meModified),
      meNRC: meNRC == null ? null : r0(meNRC),
      rer: requirements?.rer ?? null,
      merFactor: requirements?.merFactor ?? null,
      /** 妊娠/泌乳的区间与取值依据（渲染层据此改写文案，不再是「查活动表」） */
      merRange: requirements?.merRange ?? null,
      merFactorNote: requirements?.merFactorNote || '',
      sizeFactor: requirements?.sizeFactor ?? null,
      activityFactor: requirements?.activityFactor ?? null,
      merBase,
      bcsAdjPercent: adjPercent,
      /** 体况本会给出的调整幅度（被闸门拦下时能看到「本来会调多少」） */
      bcsAdjPercentRaw: rawAdjPercent,
      /** 被阶段闸门拦住时的原因说明；未拦下为 null */
      bcsAdjBlockReason: blockReason,
      mer: merAdjusted,
      gramsPerDay,
      perMeal,
      note: energyNote,
    },
    meals: { perDay, schedule: mealSchedule },
    /** 每日喂食量速查：当前方案 / 仅体况差异 / 理想体重 / 自定目标（缺数据时行数自动减少） */
    ladder,
    intake,
    cost,
    /** 现粮折算（用户填了当前饲粮能量时才有）：同热量下的现粮克数 */
    currentFood: curFood,
    waterTip,
    /** 零食额度（≤10% 每日能量）：只给百分比等于没给，这里直接换算成 kcal 与克数 */
    treats,
    /** 肌肉状况评分提示：BCS 评脂肪、MCS 评肌肉，两者必须分开看 */
    mcsHint: MCS_HINT,
    transition: transitionPlan(7, transitionGrams),
    /** 妊娠期按周曲线（仅妊娠阶段给；系统 MER 系数是整期平均，这里补曲线） */
    gestationWeekly: stage.id === 'gestation' ? GESTATION_WEEKLY[species] : null,
    monitoring: monitoringPlan(stage, policy),
    storage: storageTips(profile.productForm || 'dry'),
    vetSignals: vetSignals(),
    stageNotes,
    cautions: [
      '本指导书由配方与档案数据自动生成，属饲喂建议，不构成诊断或治疗意见',
      '更换配方、加减喂食量后请观察 1~2 周并按体重与体况复评',
      '已确诊疾病（慢性肾病、胰腺炎、糖尿病、心脏疾病等）的动物，请以主治兽医的处方为准',
      '妊娠期、泌乳期与 2 月龄以下幼龄动物，喂食量需更密切跟踪，必要时请兽医介入',
      `体况评分判定标准出处：${bcsChartSourceText()}`,
    ],
    missing: [...new Set(missing)],
    warnings: [...new Set(warnings)],
  }
}

/** 阶段专属要点（与体况建议分开，便于界面分段渲染） */
function stageNotesOf(stage, policy, species = DEFAULT_SPECIES) {
  const sp = normSpecies(species)
  const out = []
  switch (stage?.id) {
    case 'neonate':
      out.push('尚未完全离乳：以母乳或代乳为主，固体食物用温水或代乳泡软后少量多次尝试')
      out.push('4 周龄后逐步增加固体食物比例，注意观察腹泻与呕吐')
      break
    case 'growth':
      out.push('生长期需保证蛋白质与钙磷充足且比例合适，不要用成年维持量限制幼龄动物进食')
      out.push('幼龄胃容量小，请按每日餐数分成多次喂食，避免一次过量引起软便')
      out.push('不要额外补充钙片或维生素，除非兽医明确要求 —— 过量补钙会干扰骨骼发育')
      break
    case 'adult':
      out.push('维持期以保持理想体况为核心：按建议量饲喂，避免随手喂人食与零食叠加能量')
      out.push('零食热量建议不超过每日总能量的 10%')
      break
    case 'senior':
      out.push('老年动物代谢与消化能力下降，宜少量多餐、选择易消化的蛋白质来源')
      out.push('关注肾功能、牙齿与关节状况；咀嚼困难时可适当泡软')
      out.push('老年动物体重下降往往先于症状出现，定期称重比观感更可靠')
      break
    case 'gestation':
      out.push('妊娠前 2/3 期按维持量饲喂即可，最后 1/3 期逐步增加（约 25%~50%），避免母体过肥')
      out.push('胎儿占据腹腔空间，宜少量多餐')
      break
    case 'lactation':
      out.push('泌乳期能量需求显著上升，建议自由采食或每日 3 餐以上，并保证充足饮水')
      out.push('同时关注母体体况与幼崽增重，奶水不足时及时就医评估')
      break
    case 'weight_loss':
      out.push(`减重期间请按目标体重设定能量，并用体重曲线验证进度；每周减重 ${weightChangeText(sp, 'lose')} 较为安全`)
      out.push('减重过快会损失肌肉，出现精神变差或持续饥饿表现请复核方案')
      if (sp === 'cat') out.push('猫尤其不能快：每周超过 1% 的减重可能诱发肝脂沉积症（俗称猫脂肪肝），出现食欲不振、黄疸、精神沉郁请立即就医')
      break
    default:
      out.push('未判定生命阶段：以下按成年维持量的常规做法给出，补填年龄后请重新生成')
  }
  if (policy?.ok && policy.group === 'thin') {
    out.push('当前偏瘦，如排除疾病原因后仍不长肉，可考虑提高能量密度并复查驱虫与消化吸收')
  }
  return out
}

/* ================= 5. 纯文本渲染（.txt / 复制到剪贴板 / 大模型上下文） ================= */

/**
 * 渲染成纯文本指导书。
 * ⚠ 文本里**不得出现 Markdown 星号**（React 不解析）；分隔线用全角横线。
 */
export function renderFeedingGuideText(plan, opts = {}) {
  if (!plan) return ''
  const L = []
  const hr = '——————————————'
  const p = plan.pet
  const e = plan.energy
  const title = opts.title || `${p.name ? `${p.name} 的 ` : ''}饲喂指导书`

  /* ⚠ 章节号必须**动态生成**：`intake` / `cost` / `stageNotes` 都可能缺，
     写死「一~十」会在缺数据时跳号（客户拿到「三」直接跳到「五」的文档会以为漏页）。
     ⚠ 声明必须在**首次调用之前**（`const` 有暂时性死区，放后面会直接抛错）。 */
  let secNo = 0
  /* ⚠ 表比数组长时会退化成阿拉伯数字（`13、`），正文里就出现「十二、」接「13、」的混排。
     加了「体况评分判定表」之后满配已经到 13 节（含待确认事项），所以这里留到二十。 */
  const CN_NUM = ['一', '二', '三', '四', '五', '六', '七', '八', '九', '十',
    '十一', '十二', '十三', '十四', '十五', '十六', '十七', '十八', '十九', '二十']
  const sec = (t) => `${CN_NUM[secNo++] || secNo}、${t}`

  L.push(title)
  L.push(hr)
  L.push(`生成日期：${opts.date || todayStr()}`)
  if (opts.productName) L.push(`适用配方：${opts.productName}`)
  L.push('')

  L.push(sec('动物概况'))
  L.push(`物种：${p.speciesLabel}${p.breed ? `（${p.breed}${p.sizeLabel ? ` · ${p.sizeLabel}` : ''}）` : ''}`)
  L.push(`体重：${p.weightKg == null ? '未填写' : `${p.weightKg} kg`}`)
  L.push(`年龄：${p.ageText || (p.ageMonths != null ? `${p.ageMonths} 月龄` : '未填写')}`)
  L.push(`性别：${p.sexLabel}`)
  if (p.activityLabel) L.push(`活动水平：${p.activityLabel}`)
  if (p.statusLabel) L.push(`生理状态：${p.statusLabel}`)
  L.push(`生命阶段：${plan.stage.label}${plan.stage.assumed ? '（缺年龄，未判定）' : ''}`)
  /* 体况一行：`偏胖（10 分制 7 分）`。⚠ 标签与归类经常同义（7 分既是「偏胖」也归「偏胖」档），
     直接拼会写出「偏胖，属偏胖」这种废话，所以只在两者不同时才补归类。 */
  const bcsLine = p.bcs == null
    ? '未评估'
    : `${p.bcsLabel}${p.bcsLabel === p.bcsGroupLabel ? '' : `（${p.bcsGroupLabel}档）`} · ${p.bcs} / 9`
      + (p.bcsFatText ? ` ｜ 体脂约 ${p.bcsFatText}` : '')
  L.push(`体况评分：${bcsLine}`)
  if (p.bcsTouch) L.push(`  体况特征：${p.bcsTouch}`)
  if (p.bcsGroup && BCS_VIEW_HINT[p.bcsGroup]) L.push(`  对照要点：${BCS_VIEW_HINT[p.bcsGroup]}`)
  /* 肌肉状况（MCS）：WSAVA 把 MCS 与 BCS 并列 —— BCS 评脂肪、MCS 评肌肉。
     只报 BCS 会漏掉「体重在降但掉的是肌肉」（减重期、老年动物最常见）。 */
  L.push('  肌肉状况（BCS 评的是脂肪，肌肉要另外摸）：')
  for (const m of MCS_HINT) L.push(`    · ${m}`)
  if (p.idealWeightKg != null) {
    L.push(`  理想体重估算：${p.idealWeightKg} kg（较当前减少 ${p.idealWeightReducePercent}%，经验估算，需兽医确认）`)
  }
  if (p.targetWeightKg != null) L.push(`  目标体重：${p.targetWeightKg} kg`)
  L.push('')

  /* ---- BCS 逐分判定表：宠主自己对照打分时要用的标准 ----
     ⚠ 必须与界面、HTML 导出**同构**（三处都取同一份 `plan.bcsChart`）：
     客户手里的打印件与网页版给出两套判据，是最难被发现也最伤信誉的分叉。 */
  if (plan.bcsChart) {
    const ch = plan.bcsChart
    L.push(sec(`体况评分判定表（${ch.speciesLabel}，9 分制）`))
    L.push(`判据只有三条：侧视看腹部上提、俯视看腰线内收、触摸摸肋骨与脂肪层。${ch.idealText}；BCS ${ch.screeningZone.from}~${ch.screeningZone.to} 分为${ch.screeningZone.label}（筛查阈值，不是诊断）。`)
    for (const row of ch.rows) {
      const marks = []
      if (row.score === p.bcs) marks.push('当前评分')
      if (row.score >= ch.screeningZone.from) marks.push(ch.screeningZone.label)
      L.push(`${row.score} 分 · ${row.label} · 体脂约 ${row.fatText}${marks.length ? `（${marks.join('、')}）` : ''}`)
      L.push(`    侧视：${row.lateral} ｜ 俯视：${row.dorsal} ｜ 触摸：${row.palpation}`)
    }
    L.push('')
    for (const n of ch.notes) L.push(`· ${n}`)
    L.push('')
    for (const c of ch.caveats) L.push(`· 注意：${c}`)
    L.push('')
  }

  L.push(sec('每日能量与喂食量'))
  if (e.rer != null) L.push(`静息能量需求 RER：${e.rer} kcal/日`)
  if (e.merBase != null) {
    // 2026-10-25：活动并入 merFactor，体型不参与算术 ⇒ 只报合成系数
    const f = e.merFactor != null
      ? `能量系数 ${e.merFactor}（${e.merFactorNote || '状态与活动查表选值'}；体型差异由 BW^0.75 体现）`
      : ''
    L.push(`维持能量需求 MER：${e.merBase} kcal/日${f ? `（${f}）` : ''}`)
  }
  if (e.bcsAdjPercent) {
    L.push(`体况调整：${e.bcsAdjPercent > 0 ? '+' : ''}${e.bcsAdjPercent}% → 目标能量 ${e.mer} kcal/日`)
  } else if (e.mer != null) {
    L.push(`目标能量：${e.mer} kcal/日`)
  }
  if (e.bcsAdjBlockReason) {
    L.push(`体况调整未启用：${e.bcsAdjBlockReason}`)
    if (e.bcsAdjPercentRaw) L.push(`  （如按体况本会调整 ${e.bcsAdjPercentRaw > 0 ? '+' : ''}${e.bcsAdjPercentRaw}%，当前阶段不适用）`)
  }
  L.push(`本配方代谢能：${e.mePerKg == null ? '缺数据' : `${e.mePerKg} kcal/kg（${e.basisLabel}）`}`)
  if (e.meNRC != null && e.meModified != null && e.meNRC !== e.meModified) {
    L.push(`  另一口径参考：改良 Atwater ${e.meModified} / NRC ${e.meNRC} kcal/kg`)
  }
  L.push(`每日喂食量：${e.gramsPerDay == null ? '无法计算（见下方提示）' : `${e.gramsPerDay} g/日`}`)
  if (e.note) L.push(`  注意：${e.note}`)
  L.push(`分餐：每日 ${plan.meals.perDay} 餐${e.perMeal != null ? `，每餐约 ${e.perMeal} g` : ''}`)
  for (const m of plan.meals.schedule) L.push(`  · ${m.label}（${m.hint}）：${m.grams} g`)
  /* 零食额度：给克数，不给百分比 —— 宠主拿「10%」没法执行，拿「能喂几克」才行 */
  if (plan.treats) {
    L.push(`零食额度：每日不超过 ${plan.treats.maxKcal} kcal，约等于本配方 ${plan.treats.maxGrams} g（占每日总能量 ${plan.treats.maxPercent}%）`)
    L.push(`  ${plan.treats.note}；${plan.treats.howTo}`)
  }
  L.push('')

  /* 喂食量速查：只有一行时不单列章节（否则「速查」里只有一个数，没有可比对象） */
  if (plan.ladder && plan.ladder.length > 1) {
    L.push(sec('按体重速查每日喂食量'))
    for (const r of plan.ladder) {
      L.push(`· ${r.tag}｜${r.label} → ${r.mer == null ? '缺能量数据' : `${r.mer} kcal/日`}，${r.grams == null ? '无法换算克数' : `${r.grams} g/日`}`)
    }
    L.push('（同一只动物，只改变体重与体况；均按本配方的代谢能换算，体重变化时状态与活动系数假定不变）')
    L.push('')
  }

  if (plan.intake) {
    const i = plan.intake
    L.push(sec('每日营养素摄入（按建议喂食量折算）'))
    L.push(`粗蛋白 ${i.proteinG} g ｜ 粗脂肪 ${i.fatG} g ｜ 粗纤维 ${i.fiberG} g ｜ 粗灰分 ${i.ashG} g`)
    L.push(`钙 ${i.caG} g ｜ 磷 ${i.pG} g`)
    L.push(`配方带入水分约 ${i.waterFromFoodMl} mL`)
    L.push('')
  }

  if (plan.cost) {
    L.push(sec('饲喂成本'))
    L.push(`原料单价 ${plan.cost.pricePerKg} 元/kg`)
    L.push(`每日约 ${plan.cost.perDay} 元 ｜ 每月约 ${plan.cost.perMonth} 元 ｜ 每年约 ${plan.cost.perYear} 元`)
    L.push('')
  }

  L.push(sec('换粮过渡（7 天）'))
  if (plan.currentFood) {
    L.push(`当前饲粮代谢能 ${plan.currentFood.mePerKg} kcal/kg → 同热量下现粮约 ${plan.currentFood.gramsPerDay} g/日`)
    L.push(`（${plan.currentFood.note}）`)
  } else {
    L.push('（未填当前饲粮能量值：下表只给比例。补填后可同时换算出两种粮各自的克数，便于上秤）')
  }
  for (const t of plan.transition) {
    const g = (t.newG != null && t.oldG != null) ? `（新粮 ${t.newG} g + 旧粮 ${t.oldG} g）` : ''
    L.push(`第 ${t.day} 天：新粮 ${t.newPercent}% / 旧粮 ${t.oldPercent}%${g}`)
  }
  L.push('出现软便时退回上一档，并延长 2~3 天再继续推进。')
  L.push('')

  if (plan.gestationWeekly) {
    L.push('附：妊娠期按周能量增量（本表为逐周曲线，系统给出的整期平均系数仅供快速估值）')
    for (const w of plan.gestationWeekly) L.push(`· ${w.week}：${w.adj}`)
    L.push('')
  }

  if (plan.stageNotes.length) {
    L.push(sec(`${plan.stage.label}饲喂要点`))
    for (const n of plan.stageNotes) L.push(`· ${n}`)
    L.push('')
  }

  L.push(sec('观察与调整'))
  for (const m of plan.monitoring) {
    L.push(`· ${m.item}（${m.frequency}）：${m.howTo}；${m.action}`)
  }
  L.push('')

  /* ⚠ 「需立即就医」必须与「观察与调整」**同级独立成节**（走 `sec()` 吃章节号）：
     它是安全关键信息，降级成「【…】」内联标签既不出现在目录里、也与 HTML 侧的
     标题层级对不上（客户拿到 Word 版与网页版结构不一致）。 */
  L.push(sec('需立即就医的情况'))
  for (const v of plan.vetSignals) L.push(`· ${v}`)
  L.push('')

  L.push(sec('饮水与储存'))
  L.push(`饮水：${plan.waterTip}`)
  L.push('储存与喂食安全：')
  for (const s of plan.storage) L.push(`· ${s}`)
  L.push('')

  if (plan.warnings.length) {
    L.push(sec('待确认事项'))
    for (const w of plan.warnings) L.push(`· ${w}`)
    L.push('')
  }
  if (plan.missing.length) {
    L.push(`缺失输入（补填后建议重新生成）：${plan.missing.join('、')}`)
    L.push('')
  }

  L.push(sec('说明'))
  for (const c of plan.cautions) L.push(`· ${c}`)
  return L.join('\n')
}

/** 本地日期字符串 YYYY-MM-DD（不用 toISOString，避免时区偏移一天） */
export function todayStr(d = new Date()) {
  const p2 = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())}`
}
