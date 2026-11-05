/**
 * 营养标准体系注册表 + 目标市场模式（任务 4）。
 *
 * ## 数据来源与可信度分级（逐项可追溯，这是本模块的第一原则）
 *
 *   · `CN-GB`  —— 中国国家标准，**条款已核**。来源：
 *       GB/T 31216-2014《全价宠物食品 犬粮》表 2（主要理化指标）、表 3（水分）；
 *       GB/T 31217-2014《全价宠物食品 猫粮》表 1（主要理化指标）、表 2（水分）。
 *       取自国家标准全文公开系统（openstd.samr.gov.cn）与标准原文。
 *   · `AAFCO`  —— 美国饲料管理协会 Nutrient Profiles。数值**沿用系统原有代码**，
 *       尚未与官方出版物逐项核对 → 全部条目带 `verify: true`，界面显示「待核对现行版本」。
 *   · `FEDIAF` —— 欧洲宠物食品工业协会 Nutritional Guidelines。**本轮不参与判定**：
 *       其主表以「每 MJ 代谢能」为基准表达，需先实现能量基准口径（计划批次 2.2），
 *       且 DM 基准的欧盟法定限值表需核对原文。故登记为 `valuesPending`，
 *       界面显示「已登记、数值待补（不参与判定）」——宁可不判，也不拿未核实的限值去判。
 *
 * ## 三种目标市场模式（用户可选，持久化在设置里）
 *
 *   cn       仅中国 GB 标签            → 只按 CN-GB 判定
 *   cn-intl  中国 GB + 国际（AAFCO）   → 同时满足，取最严
 *   intl     仅国际（AAFCO）           → 只按 AAFCO 判定
 *
 * ## 合并规则（多体系同时满足时）
 *
 *   下限取各体系的**最大值**（都要满足 ⇒ 取最严的那个下限）
 *   上限取各体系的**最小值**
 *   区间取**交集**（左端取 max、右端取 min），交集为空时显式报冲突
 *   项目取**并集**（某体系要求的项目，即使另一体系没要求也要判）
 *   每一项都保留 `sources`（各体系原值文案）与 `cites`（条款出处），便于追溯
 *
 * ## 不参与自动判定的项目
 *
 *   原料库没有氨基酸字段 → 赖氨酸（犬）、牛磺酸（猫）标为 `dataField: null`，
 *   判定为「系统无此原料数据，暂无法判定」，**不冒充「未达标」**。
 */

/**
 * 营养素元信息。
 *   dataField —— 取自原料库的哪个字段；null 表示系统没有这项数据
 *   unit      —— 展示单位（统一按干物质基础，与 GB 表 2/1 一致）
 *   kind      —— min 下限 / max 上限 / range 区间 / info 仅展示
 */
export const NUTRIENT_META = {
  crude_protein: { label: '粗蛋白质', unit: '%DM', dataField: 'crude_protein', kind: 'min' },
  crude_fat: { label: '粗脂肪', unit: '%DM', dataField: 'crude_fat', kind: 'min' },
  crude_fiber: { label: '粗纤维', unit: '%DM', dataField: 'crude_fiber', kind: 'max' },
  crude_ash: { label: '粗灰分', unit: '%DM', dataField: 'crude_ash', kind: 'max' },
  calcium: { label: '钙', unit: '%DM', dataField: 'calcium', kind: 'min' },
  phosphorus: { label: '总磷', unit: '%DM', dataField: 'phosphorus', kind: 'min' },
  chloride: { label: '水溶性氯化物', unit: '%DM', dataField: 'chloride', kind: 'min' },
  lysine: { label: '赖氨酸', unit: '%DM', dataField: null, kind: 'min' },
  taurine: { label: '牛磺酸', unit: '%DM', dataField: null, kind: 'min' },
  caP: { label: '钙磷比（干物质基）', unit: '', dataField: null, kind: 'range', computed: 'caP' },
  me: { label: '代谢能（干物质基）', unit: 'kcal/kg DM', dataField: null, kind: 'min', computed: 'me' },
  // —— 以下 6 项由任务 A1 从 pawcook AAFCO 数据吸收（批 A），dataField:null 表示
  //    原料库当前无氨基酸/脂肪酸分析字段，仅登记标准、系统暂无法自动判定（与 lysine/taurine 同机制）。
  //    出处：SirAllap/pawcook aafco.json / aafco-cat.json 转译；AAFCO 集整体 verified:false，待官核。
  linoleic_acid: { label: '亚油酸', unit: '%DM', dataField: null, kind: 'min' },
  ala: { label: 'α-亚麻酸', unit: '%DM', dataField: null, kind: 'min' },
  epa_dha: { label: 'EPA+DHA', unit: '%DM', dataField: null, kind: 'min' },
  arachidonic_acid: { label: '花生四烯酸', unit: '%DM', dataField: null, kind: 'min' },
  arginine: { label: '精氨酸', unit: '%DM', dataField: null, kind: 'min' },
  methionine: { label: '蛋氨酸', unit: '%DM', dataField: null, kind: 'min' },
}

/**
 * 标准体系注册表。
 * 每个体系按 物种(species) → 生命阶段档(stage: growth|adult) → { 项目: 条款 }。
 * 条款形式：
 *   { min }        下限
 *   { max }        上限
 *   { min, max }   区间
 *   { min, wetMin }  湿粮适用另一下限（牛磺酸）
 */
export const STANDARD_SETS = {
  'CN-GB': {
    id: 'CN-GB',
    label: '中国 GB',
    fullLabel: '中国国家标准（GB/T 31216-2014 犬粮 · GB/T 31217-2014 猫粮）',
    verified: true,
    // 水分形态分级（两个标准完全一致，放在体系级）
    moistureGrades: [
      { id: 'dry', label: '干性', test: (x) => x < 14.0, cite: 'GB/T 31216 表3 / GB/T 31217 表2' },
      { id: 'semi-moist', label: '半湿性', test: (x) => x >= 14.0 && x < 60.0, cite: '同上' },
      { id: 'wet', label: '湿性', test: (x) => x >= 60.0, cite: '同上' },
    ],
    stages: {
      dog: {
        growth: {
          crude_protein: { min: 22.0, cite: 'GB/T 31216-2014 表2 · 幼犬粮/妊娠期/哺乳期犬粮' },
          crude_fat: { min: 8.0, cite: 'GB/T 31216-2014 表2' },
          crude_ash: { max: 10.0, cite: 'GB/T 31216-2014 表2' },
          crude_fiber: { max: 9.0, cite: 'GB/T 31216-2014 表2' },
          calcium: { min: 1.0, cite: 'GB/T 31216-2014 表2' },
          phosphorus: { min: 0.8, cite: 'GB/T 31216-2014 表2' },
          caP: { min: 1.0, max: 1.8, cite: '通用营养学参考区间（非 GB 强制条款）' },
          chloride: { min: 0.45, cite: 'GB/T 31216-2014 表2' },
          lysine: { min: 0.77, cite: 'GB/T 31216-2014 表2' },
        },
        adult: {
          crude_protein: { min: 18.0, cite: 'GB/T 31216-2014 表2 · 成年犬粮' },
          crude_fat: { min: 5.0, cite: 'GB/T 31216-2014 表2' },
          crude_ash: { max: 10.0, cite: 'GB/T 31216-2014 表2' },
          crude_fiber: { max: 9.0, cite: 'GB/T 31216-2014 表2' },
          calcium: { min: 0.6, cite: 'GB/T 31216-2014 表2' },
          phosphorus: { min: 0.5, cite: 'GB/T 31216-2014 表2' },
          caP: { min: 1.0, max: 2.0, cite: '通用营养学参考区间（非 GB 强制条款）' },
          chloride: { min: 0.09, cite: 'GB/T 31216-2014 表2' },
          lysine: { min: 0.63, cite: 'GB/T 31216-2014 表2' },
        },
      },
      cat: {
        growth: {
          crude_protein: { min: 28.0, cite: 'GB/T 31217-2014 表1 · 幼猫粮/妊娠期/哺乳期猫粮' },
          crude_fat: { min: 9.0, cite: 'GB/T 31217-2014 表1' },
          crude_ash: { max: 10.0, cite: 'GB/T 31217-2014 表1' },
          crude_fiber: { max: 9.0, cite: 'GB/T 31217-2014 表1' },
          calcium: { min: 1.0, cite: 'GB/T 31217-2014 表1' },
          phosphorus: { min: 0.8, cite: 'GB/T 31217-2014 表1' },
          caP: { min: 1.0, max: 1.8, cite: '通用营养学参考区间（非 GB 强制条款）' },
          chloride: { min: 0.3, cite: 'GB/T 31217-2014 表1' },
          taurine: { min: 0.1, wetMin: 0.2, cite: 'GB/T 31217-2014 表1（湿粮 ≥0.2）' },
        },
        adult: {
          crude_protein: { min: 25.0, cite: 'GB/T 31217-2014 表1 · 成年猫粮' },
          crude_fat: { min: 9.0, cite: 'GB/T 31217-2014 表1' },
          crude_ash: { max: 10.0, cite: 'GB/T 31217-2014 表1' },
          crude_fiber: { max: 9.0, cite: 'GB/T 31217-2014 表1' },
          calcium: { min: 0.6, cite: 'GB/T 31217-2014 表1' },
          phosphorus: { min: 0.5, cite: 'GB/T 31217-2014 表1' },
          caP: { min: 1.0, max: 2.0, cite: '通用营养学参考区间（非 GB 强制条款）' },
          chloride: { min: 0.3, cite: 'GB/T 31217-2014 表1' },
          taurine: { min: 0.1, wetMin: 0.2, cite: 'GB/T 31217-2014 表1（湿粮 ≥0.2）' },
        },
      },
    },
  },

  AAFCO: {
    id: 'AAFCO',
    label: 'AAFCO',
    fullLabel: 'AAFCO Dog and Cat Food Nutrient Profiles',
    verified: false,
    verifyNote: '数值沿用系统原有实现，尚未与 AAFCO 官方出版物逐项核对现行版本年份，结论仅供参考。',
    stages: {
      dog: {
        growth: {
          crude_protein: { min: 22.5 },
          crude_fat: { min: 8.5 },
          linoleic_acid: { min: 1.3, cite: 'AAFCO 2014（参考 SirAllap/pawcook aafco.json 转译，verified:false）' },
          ala: { min: 0.08, cite: 'AAFCO 2014（参考 SirAllap/pawcook aafco.json 转译，verified:false）' },
          epa_dha: { min: 0.05, cite: 'AAFCO 2014（参考 SirAllap/pawcook aafco.json 转译，verified:false）' },
          calcium: { min: 1.2 },
          phosphorus: { min: 1.0 },
          chloride: { min: 0.3 },
          caP: { min: 1.0, max: 1.8 },
          me: { min: 3500 },
        },
        adult: {
          crude_protein: { min: 18.0 },
          crude_fat: { min: 5.5 },
          linoleic_acid: { min: 1.1, cite: 'AAFCO 2014（参考 SirAllap/pawcook aafco.json 转译，verified:false）' },
          calcium: { min: 0.5 },
          phosphorus: { min: 0.4 },
          chloride: { min: 0.3 },
          caP: { min: 1.0, max: 2.0 },
          me: { min: 3250 },
        },
      },
      cat: {
        growth: {
          crude_protein: { min: 30.0 },
          crude_fat: { min: 9.0 },
          linoleic_acid: { min: 0.55, cite: 'AAFCO 2014（参考 SirAllap/pawcook aafco-cat.json 转译，verified:false）' },
          arachidonic_acid: { min: 0.02, cite: 'AAFCO 2014（参考 SirAllap/pawcook aafco-cat.json 转译，verified:false）' },
          epa_dha: { min: 0.012, cite: 'AAFCO 2014（参考 SirAllap/pawcook aafco-cat.json 转译，verified:false）' },
          arginine: { min: 1.24, cite: 'AAFCO 2014（参考 SirAllap/pawcook aafco-cat.json 转译，verified:false）' },
          methionine: { min: 0.20, max: 1.50, cite: 'AAFCO 2014（参考 SirAllap/pawcook aafco-cat.json 转译，verified:false）' },
          lysine: { min: 1.20, cite: 'AAFCO 2014（参考 SirAllap/pawcook aafco-cat.json 转译，verified:false）' },
          taurine: { min: 0.10, wetMin: 0.20, cite: 'AAFCO 2014 猫（干粮≥0.10%/湿粮≥0.20% DM；参考 SirAllap/pawcook aafco-cat.json 转译，verified:false）' },
          calcium: { min: 1.2 },
          phosphorus: { min: 1.0 },
          chloride: { min: 0.3 },
          caP: { min: 1.0, max: 1.8 },
          me: { min: 3500 },
        },
        adult: {
          crude_protein: { min: 26.0 },
          crude_fat: { min: 9.0 },
          linoleic_acid: { min: 0.55, cite: 'AAFCO 2014（参考 SirAllap/pawcook aafco-cat.json 转译，verified:false）' },
          arachidonic_acid: { min: 0.02, cite: 'AAFCO 2014（参考 SirAllap/pawcook aafco-cat.json 转译，verified:false）' },
          arginine: { min: 1.04, cite: 'AAFCO 2014（参考 SirAllap/pawcook aafco-cat.json 转译，verified:false）' },
          methionine: { min: 0.20, max: 1.50, cite: 'AAFCO 2014（参考 SirAllap/pawcook aafco-cat.json 转译，verified:false）' },
          lysine: { min: 0.34, cite: 'AAFCO 2014（参考 SirAllap/pawcook aafco-cat.json 转译，verified:false）' },
          taurine: { min: 0.10, wetMin: 0.20, cite: 'AAFCO 2014 猫（干粮≥0.10%/湿粮≥0.20% DM；参考 SirAllap/pawcook aafco-cat.json 转译，verified:false）' },
          calcium: { min: 0.6 },
          phosphorus: { min: 0.5 },
          chloride: { min: 0.3 },
          caP: { min: 1.0, max: 2.0 },
          me: { min: 4000 },
        },
      },
    },
  },

  FEDIAF: {
    id: 'FEDIAF',
    label: 'FEDIAF',
    fullLabel: 'FEDIAF Nutritional Guidelines for Complete and Complementary Pet Food for Cats and Dogs',
    verified: false,
    valuesPending: true,
    pendingNote: 'FEDIAF 主表以「每 MJ 代谢能」为基准表达，需先实现能量基准口径（计划批次 2.2）；'
      + 'DM 基准的欧盟法定限值表亦需核对原文。故本轮登记但不参与判定。',
    stages: {},
  },
}

export const STANDARD_SET_IDS = Object.keys(STANDARD_SETS)

/**
 * 目标市场模式：决定要**同时满足**哪些标准体系。
 * 默认 `cn`（在中国境内生产销售，GB 是法定依据）。
 */
export const MARKET_MODES = [
  {
    id: 'cn',
    label: '仅中国 GB 标签',
    desc: '按 GB/T 31216-2014（犬粮）、GB/T 31217-2014（猫粮）判定，适用于国内生产销售。',
    sets: ['CN-GB'],
  },
  {
    id: 'cn-intl',
    label: '中国 GB + 国际（AAFCO/FEDIAF）',
    desc: '同时满足国标与出口市场的营养要求，逐项取最严值。',
    sets: ['CN-GB', 'AAFCO', 'FEDIAF'],
  },
  {
    id: 'intl',
    label: '仅国际（AAFCO/FEDIAF）',
    desc: '按 AAFCO / FEDIAF 判定，适用于出口或不以国标为验收依据的场景。',
    sets: ['AAFCO', 'FEDIAF'],
  },
]

export const DEFAULT_MARKET = 'cn'

export function getMarketMode(id) {
  return MARKET_MODES.find((m) => m.id === id) || MARKET_MODES.find((m) => m.id === DEFAULT_MARKET)
}

/** 生命阶段档位：生长/繁殖/泌乳合并为 growth（与 GB 表的分组方式一致） */
export function stageOf(status) {
  return (status === 'growth' || status === 'gestation' || status === 'lactation') ? 'growth' : 'adult'
}

/**
 * 水分形态分级（GB 表 3 / 表 2）。返回 { id, label, cite, available }
 * 水分不足 14% 为干性，14~60% 半湿性，≥60% 湿性。
 */
export function classifyMoisture(moisturePercent) {
  const UNKNOWN = { id: 'unknown', label: '未判定', cite: '', available: false }
  // 注意：Number(null) === 0 且有限，会被误判成「水分 0% → 干性」。空值必须先挡掉。
  // ⚠ 空白串（' '）与布尔/数组同样会被 Number() 变成 0/1，一并按「未判定」处理
  //   —— 与 data/moistureProfiles.js 的 parseMoisturePercent 保持同一口径。
  // ★ 本函数只管「**标准分档**」：x 是**检测/标示**水分，用来查 GB 表 3 的干性/半湿/湿性。
  //   引擎侧另有一道 ≥1% 硬下限（nutrition.js 的 below_min_moisture，常量在
  //   moistureProfiles.MIN_FINISHED_MOISTURE），那是「**成品水分折算**」的业务闸门。
  //   两者职责不同，别把硬下限搬到这里 —— 否则 0% 会连标准分档都判不出来。
  if (moisturePercent == null) return UNKNOWN
  if (typeof moisturePercent === 'string' && moisturePercent.trim() === '') return UNKNOWN
  if (typeof moisturePercent !== 'number' && typeof moisturePercent !== 'string') return UNKNOWN
  const x = Number(moisturePercent)
  if (!Number.isFinite(x)) return UNKNOWN
  const g = STANDARD_SETS['CN-GB'].moistureGrades.find((it) => it.test(x))
  return g ? { id: g.id, label: g.label, cite: g.cite, available: true } : { id: 'unknown', label: '未判定', cite: '', available: false }
}

/** 条款 → 展示文案（如 '≥22.0' / '≤10.0' / '1.0:1 ~ 1.8:1'） */
export function clauseText(clause, { unit = '%DM', key = '' } = {}) {
  if (!clause) return '—'
  const fmt = (n) => (Number.isInteger(n) ? n.toFixed(1) : String(n))
  const isRatio = key === 'caP'
  const hasMin = clause.min != null
  const hasMax = clause.max != null
  if (hasMin && hasMax) return isRatio ? `${fmt(clause.min)}:1 ~ ${fmt(clause.max)}:1` : `${fmt(clause.min)} ~ ${fmt(clause.unit || unit)}`
  if (hasMin) return isRatio ? `≥${fmt(clause.min)}:1` : `≥${fmt(clause.min)}`
  if (hasMax) return isRatio ? `≤${fmt(clause.max)}:1` : `≤${fmt(clause.max)}`
  return '—'
}

/**
 * 解析出「本配方应同时满足的合并标准」。
 *
 * @param {object} opts
 *   marketId      目标市场模式 id（缺省 DEFAULT_MARKET）
 *   species       'cat' | 'dog'
 *   stage         'growth' | 'adult'
 *   moistureClass 'dry' | 'semi-moist' | 'wet' | 'unknown'（用于牛磺酸湿粮档）
 * @returns {{
 *   marketId, marketLabel, marketDesc, setIds, setLabels,
 *   items: Array<{
 *     key, label, unit, kind, dataField, available, computed,
 *     min, max, sources: Object<string,string>, cites: string[],
 *     text: string, active: boolean, warn: string
 *   }>,
 *   warnings: string[], setNotes: Array<{id,label,note}>,
 *   moistureClass, sourceLabel
 * }}
 */
export function resolveStandard({ marketId, species = 'cat', stage = 'adult', moistureClass = 'unknown' } = {}) {
  const market = getMarketMode(marketId)
  const activeSets = market.sets.map((id) => STANDARD_SETS[id]).filter(Boolean)
  const sp = species === 'dog' ? 'dog' : 'cat'

  const warnings = []
  const setNotes = []
  for (const s of activeSets) {
    if (s.valuesPending) {
      setNotes.push({ id: s.id, label: s.label, note: s.pendingNote })
      warnings.push(`${s.label} 已登记但数值待补，本轮不参与判定（${s.pendingNote}）`)
    } else if (s.verified === false && s.verifyNote) {
      setNotes.push({ id: s.id, label: s.label, note: s.verifyNote })
      warnings.push(`${s.label}：${s.verifyNote}`)
    }
  }

  // 汇总所有体系的条款：项目取并集
  const keys = []
  for (const s of activeSets) {
    const tbl = s.stages?.[sp]?.[stage]
    if (!tbl) continue
    for (const k of Object.keys(tbl)) if (!keys.includes(k)) keys.push(k)
  }

  const items = keys.map((k) => {
    const meta = NUTRIENT_META[k] || { label: k, unit: '', dataField: null, kind: 'min' }
    const sources = {}
    const cites = []
    let min = null
    let max = null
    let wetMin = null
    let conflict = ''

    for (const s of activeSets) {
      const clause = s.stages?.[sp]?.[stage]?.[k]
      if (!clause) continue
      sources[s.id] = clauseText(clause, { unit: meta.unit, key: k })
      if (clause.cite) cites.push(`${s.label} ${clause.cite}`)
      if (clause.min != null) {
        if (min == null || clause.min > min) min = clause.min
      }
      if (clause.max != null) {
        if (max == null || clause.max < max) max = clause.max
      }
      if (clause.wetMin != null) {
        if (wetMin == null || clause.wetMin > wetMin) wetMin = clause.wetMin
      }
    }

    // 湿粮档：牛磺酸等在湿性产品上适用更严的下限
    let appliedMin = min
    let wetApplied = false
    if (wetMin != null && moistureClass === 'wet' && (min == null || wetMin > min)) {
      appliedMin = wetMin
      wetApplied = true
    }

    if (appliedMin != null && max != null && appliedMin > max) {
      conflict = `各体系条款区间无交集（下限 ${appliedMin} > 上限 ${max}），请人工核对标准原文`
      warnings.push(`${meta.label}：${conflict}`)
    }

    const text = clauseText({ min: appliedMin, max }, { unit: meta.unit, key: k })

    return {
      key: k,
      label: meta.label,
      unit: meta.unit,
      kind: meta.kind,
      dataField: meta.dataField,
      computed: meta.computed || null,
      available: !!meta.dataField || !!meta.computed,
      min: appliedMin,
      max,
      sources,
      cites,
      text,
      wetApplied,
      warn: conflict,
      // 仅展示、不参与达标判定的条目（系统无数据支撑的氨基酸类）
      active: (!!meta.dataField || !!meta.computed) && !conflict && (appliedMin != null || max != null),
    }
  })

  // 标记系统无数据支撑的项目（不冒充未达标）
  const unavailable = items.filter((it) => !it.available).map((it) => it.label)
  if (unavailable.length) {
    warnings.push(`原料库无${unavailable.join('、')}数据，这些项目无法自动判定（需先补氨基酸/相关检测数据）`)
  }

  const setLabels = activeSets.filter((s) => !s.valuesPending).map((s) => s.label)
  const sourceLabel = setLabels.length
    ? `${market.label}（${setLabels.join(' + ')}）`
    : market.label

  return {
    marketId: market.id,
    marketLabel: market.label,
    marketDesc: market.desc,
    setIds: activeSets.map((s) => s.id),
    setLabels,
    items,
    warnings,
    setNotes,
    moistureClass,
    sourceLabel,
  }
}
