/**
 * 产品水分档位（成品水分）—— 配方计算器「干基换算」的**唯一数据源**。
 *
 * ## 为什么需要这一层
 * 计算器原先只用「原料水分加权」当作成品水分。这对**湿粮**勉强成立，
 * 对烘焙粮 / 冻干 / 烘干（风干）这类**要脱水**的工艺完全不成立：
 * 原料里 70% 的水，成品可能只剩 4%。水分一旦取错，干物质含量（DM%）就错，
 * 而**所有干基指标、能量、达标判定**都挂在 DM% 上 —— 错一处、错一片。
 *
 * ## 口径
 *   min / max        可调区间（%）。这是**界面允许选择的范围**，
 *                    有专属标准上限的档位，max 必须 ≤ standardMax（见守卫测试）。
 *   typicalMin/Max   行业典型区间（有实测依据才给，没有就 null，**不编数**）
 *   default          默认值
 *   standardMax      本档适用的**法定/标准上限**（null = 该档由区间型标准约束，无单侧上限）
 *   standardMin      本档适用的**法定/标准下限**（null = 无单侧下限）
 *   standardMaxStrict  true = 标准原文是「**小于**」（如 GB/T「干性 水分 <14.0%」），
 *                    因此 14.0 本身即不合规；缺省/ false = 「不高于 / ≤」（等于上限仍合规）。
 *   standardMinStrict  同理，对应「大于」；缺省/ false = 「不低于 / ≥」。
 *   ⚠ 有了这两个标志，`max`/`min`（**可调区间**，允许探索）与标准红线才能各说各话：
 *     接口边界值 14.0 在 air-dried 档里「在可调区间内、但已越标准红线」，两个信号不冲突。
 *   standardNote     上限对应的条件（如「干性粮」「冻结类」），用于界面提示
 *   sources          逐条依据：标准名称 + 条款位置 + 原文口径
 *
 * ## 证据等级
 * 只写**已取得原文**或**公开可核**的条款。未取得全文的标准（如 T/CIQA 64-2023）
 * 明确标 `pending: true` 并写「限值未取得」，**不留空口数值**。
 */

/**
 * 档位定义。
 * ⚠ `productForms` 里引用的 id 必须存在于 `src/data/regulations.js` 的 PRODUCT_FORMS
 *   （守卫 `moisture-profile-test.mjs` 会逐条核对，防止两边漂移）。
 */
export const MOISTURE_PROFILES = [
  {
    id: 'baked',
    label: '烘焙粮（干性）',
    min: 1,
    max: 10,
    typicalMin: 1,
    typicalMax: 5,
    default: 4,
    standardMax: 10,
    standardNote: '干性粮',
    productForms: ['baked'],
    defaultBasis: '工艺常见水平（实测多数 3%~6%，取下沿 4%）',
    sources: [
      {
        name: 'T/SDPIA 08-2022《烘焙全价宠物食品》',
        clause: '4.2.4 加工质量指标',
        value: '水分：干性粮不高于 10%，半干性粮不高于 40%',
      },
      {
        name: 'GB/T 31216-2014《全价宠物食品 犬粮》/ GB/T 31217-2014《全价宠物食品 猫粮》',
        clause: '表 3 / 表 2（水分分档）',
        value: '干性宠物食品 水分 <14.0%；半湿性 14.0%~60.0%；湿性 ≥60.0%',
      },
      {
        name: '《全价宠物食品 烘焙加工技术规范》农业行业标准编制说明（2024-07 公开征求意见稿）',
        clause: '表 15（51 份市售烘焙粮样品检测结果）',
        value: '实测水分 2.8%~7.2%，多数落在 3%~6%',
      },
    ],
  },

  {
    id: 'freeze-dried',
    label: '冻干',
    min: 1,
    max: 6,
    typicalMin: 1,
    typicalMax: 5,
    default: 4,
    standardMax: 6,
    standardNote: '冻干宠物食品',
    productForms: ['freeze-dried'],
    defaultBasis: '标准上限内取常见值',
    sources: [
      {
        name: 'NY/T 4839-2025《冻干宠物食品通用要求》',
        clause: '4.2.2 表 2 理化指标',
        value: '水分 ≤6%（2025-12-09 发布，2026-05-01 实施）',
      },
      {
        name: 'T/SDPIA 01-2024《冻干全价宠物食品》',
        clause: '4.2.2 水分 / 4.2.3 水分活度',
        value: '水分不高于 8%；水分活度（aw）不高于 0.6',
      },
    ],
  },

  {
    id: 'air-dried',
    label: '烘干 / 风干',
    min: 1,
    max: 14,
    typicalMin: null,
    typicalMax: null,
    default: 12,
    standardMax: 14,
    standardMaxStrict: true, // GB/T 原文「干性 水分 <14.0%」⇒ 14.0 本身即不合规
    standardNote: '干性（<14%）',
    productForms: [],
    defaultBasis: '按合规上限（干性 <14%）下沿取值，「无实测依据」，请按本厂工艺实测调整',
    sources: [
      {
        name: 'GB/T 31216-2014《全价宠物食品 犬粮》/ GB/T 31217-2014《全价宠物食品 猫粮》',
        clause: '表 3 / 表 2（水分分档）',
        value: '干性宠物食品 水分 <14.0%（烘干/风干全价粮按干性档执行）',
      },
      {
        name: 'T/CIQA 64-2023《热风干燥宠物食品规范》（中国出入境检验检疫协会团体标准）',
        clause: '—',
        value: '标准 2023-06-29 发布并实施；全文未公开，「水分限值未取得」，待补',
        pending: true,
      },
    ],
  },

  {
    id: 'extruded',
    label: '膨化粮（干性）',
    min: 1,
    max: 14,
    typicalMin: null,
    typicalMax: null,
    default: 10,
    standardMax: 14,
    standardMaxStrict: true, // GB/T 原文「干性 水分 <14.0%」⇒ 14.0 本身即不合规
    standardNote: '干性（<14%）',
    productForms: ['extruded'],
    defaultBasis: '按合规上限（干性 <14%）内常见值取值，请按本厂工艺实测调整',
    sources: [
      {
        name: 'GB/T 31216-2014《全价宠物食品 犬粮》/ GB/T 31217-2014《全价宠物食品 猫粮》',
        clause: '表 3 / 表 2（水分分档）',
        value: '干性宠物食品 水分 <14.0%',
      },
    ],
  },

  {
    id: 'semi-moist',
    label: '半湿粮',
    min: 14,
    max: 60,
    typicalMin: null,
    typicalMax: null,
    default: 25,
    standardMin: 14,
    standardMax: 60,
    standardMaxStrict: true, // GB/T「半湿性 14.0% ≤ 水分 < 60.0%」⇒ 下限含 14.0、上限不含 60.0
    standardNote: '半湿性（14%~60%）',
    productForms: [],
    defaultBasis: '区间内取常见值，请按本厂工艺实测调整',
    sources: [
      {
        name: 'GB/T 31216-2014《全价宠物食品 犬粮》/ GB/T 31217-2014《全价宠物食品 猫粮》',
        clause: '表 3 / 表 2（水分分档）',
        value: '半湿性宠物食品 14.0% ≤ 水分 < 60.0%',
      },
    ],
  },

  {
    id: 'wet',
    label: '湿粮 / 猫条',
    min: 60,
    max: 85,
    typicalMin: null,
    typicalMax: null,
    default: 75,
    standardMax: null,
    standardMin: 60,
    standardNote: '湿性（≥60%）',
    productForms: ['cat-stick'],
    defaultBasis: '区间内取常见值，请按本厂工艺实测调整',
    sources: [
      {
        name: 'GB/T 31216-2014《全价宠物食品 犬粮》/ GB/T 31217-2014《全价宠物食品 猫粮》',
        clause: '表 3 / 表 2（水分分档）',
        value: '湿性宠物食品 水分 ≥60.0%',
      },
    ],
  },
]

/** 档位 id → 档位（唯一查找入口） */
export function getMoistureProfile(id) {
  const k = String(id ?? '').trim()
  if (!k) return null
  return MOISTURE_PROFILES.find((p) => p.id === k) || null
}

/**
 * 产品形态（PRODUCT_FORMS.id）→ 推荐水分档位 id。
 * 形态与水分不是一一对应（如「零食」跨多个水分档），**猜不出来的返回空串**。
 */
export function moistureProfileIdForForm(formId) {
  const f = String(formId ?? '').trim()
  if (!f) return ''
  const hit = MOISTURE_PROFILES.find((p) => p.productForms.includes(f))
  return hit ? hit.id : ''
}

/**
 * 成品水分的**硬下限**（%）。低于此值的输入一律判「无效」，不施加折算。
 *
 * ## 为什么必须有下限
 * 成品水分 0% ⇒ DM% = 100% ⇒ 干基与湿基**逐格重合**，且折算系数
 * k = 100 ÷ 原料DM% 会把湿基各项放大数倍、GE 虚高（实测 5108 kcal/kg，
 * 比 3% 的 4954 还高 —— 因为分母被人为撑到了 100）。
 * 而 0% 在真实工艺里**不存在**：再干的烘焙粮也含 1%~2% 的平衡水分。
 * 所以 0 不是「一个激进但有效的输入」，而是**漏填 / 误填**的信号，必须显式拦下，
 * 而不是算出一份「看起来正常」的配方。
 *
 * ## 为什么常量放在这个文件
 * 本文件是「成品水分」的**唯一数据源**（6 档定义 + 解析口径都在这里）。
 * 下限与各档 `min` 同住一处才守得住「唯一真源」，引擎 / 界面 / CLI 同源 import。
 * 现有 6 档的 `min` 全部 ≥1，故本下限与档位可调区间**天然自洽**，
 * 不产生「档位允许、引擎拒绝」的矛盾。
 *
 * ## 为什么**不**放进 parseMoisturePercent（重要，别改错地方）
 * 那个函数的职责是「**解析**」不是「**校验**」，其契约明确写着
 * 「没给 ⇒ NaN，给了 0 ⇒ 0」，且被 `standards.js` 的 `classifyMoisture` 同口径复用。
 * 把业务下限塞进去会连带打破三处既有约定：
 * `parseMoisturePercent(0) === 0`、`checkMoistureAgainst(baked, 0).available === true`、
 * `checkMoistureAgainst(baked, 0.5)` 仍须给出「超出本档可调区间」。
 * 硬闸门归属**引擎层** —— 见 `lib/nutrition.js` 的 `computeRecipe` 的 `below_min_moisture` 分支。
 * 同理也不放进 `checkMoistureAgainst`：那是**档位可调区间**的提示层，不是硬闸门。
 */
export const MIN_FINISHED_MOISTURE = 1

/**
 * 「成品水分」输入的**唯一解析口径**（引擎、界面、标准分档三处共用，不要各写一套）。
 *
 * ## 为什么必须集中一处
 * `Number('')`、`Number(' ')`、`Number(null)` 全都等于 **0**，`Number(true)` 等于 1，
 * `Number([])` 等于 0、`Number([4])` 等于 4 —— 而 **0% 在本引擎里是合法输入**
 * （k = 成品DM% ÷ 原料DM%，会以约 2.2 倍把湿基各项放大）。也就是说，
 * 空输入 / 空白串 / 布尔 / 数组会被**静默地**当成「0% 水分」并算出一份看起来正常的配方。
 * 因此本函数的唯一职责是把「**没给**」与「**给了 0**」严格分开：
 * 前者返回 `NaN`（＝不施加覆盖），后者返回 `0`（＝按 0% 折算，并由档位校验去报警）。
 *
 * ⚠ 同一口径也被 `standards.js` 的 `classifyMoisture` 用于挡空值 ——
 *   那边源码里已有注释写明「`Number(null) === 0` 会被误判成水分 0% → 干性」这一同类坑。
 *
 * @param {*} v 原始输入（string / number / null / undefined / 其它类型）
 * @returns {number} 合法数值；`NaN` 表示「未指定 / 无法解析」
 */
export function parseMoisturePercent(v) {
  if (v === null || v === undefined) return NaN
  const n = typeof v === 'number'
    ? v
    : typeof v === 'string'
      ? (v.trim() === '' ? NaN : Number(v.trim()))
      : NaN // boolean / array / object / function … 一律按「未指定」，**不做隐式类型强转**
  if (!Number.isFinite(n)) return NaN
  return n === 0 ? 0 : n // 归一化 -0 → 0（JSON 里虽写作 0，但 -0 !== 0 会漏进比较与展示）
}

/**
 * 目标水分是否落在「可调区间」内、是否越过标准上限/下限。
 *
 * ⚠ **未指定时不做任何判定**（`available: false` 且 `messages` 为空）—— 这一点是硬约束：
 *   `Number('')` 是 0，若不做空值守卫，用户只要**选中档位而还没填数值**，
 *   就会立刻看到「超出本档可调区间」甚至「低于下限、不符合该标准」的假警报。
 *
 * @returns {{available:boolean, inRange:boolean, overStandard:boolean, belowStandard:boolean, messages:string[]}}
 */
export function checkMoistureAgainst(profile, percent) {
  const out = { available: false, inRange: false, overStandard: false, belowStandard: false, messages: [] }
  if (!profile) return out
  const x = parseMoisturePercent(percent)
  if (!Number.isFinite(x)) return out
  out.available = true
  out.inRange = x >= profile.min && x <= profile.max
  if (!out.inRange) {
    out.messages.push(`超出本档可调区间 ${profile.min}%~${profile.max}%`)
  }
  /* 上限：standardMaxStrict 时原文是「小于」⇒ 等于上限即越线（如干性 <14.0%，14.0 不合规） */
  if (profile.standardMax != null) {
    const over = profile.standardMaxStrict ? x >= profile.standardMax : x > profile.standardMax
    if (over) {
      out.overStandard = true
      out.messages.push(
        `${profile.standardMaxStrict ? '达到或超过' : '超过'}${profile.standardNote || ''}上限 ${profile.standardMax}%（${profile.sources[0]?.name || ''}），该水分下的产品不符合该标准`,
      )
    }
  }
  /* 下限：standardMinStrict 时原文是「大于」⇒ 等于下限即越线 */
  if (profile.standardMin != null) {
    const under = profile.standardMinStrict ? x <= profile.standardMin : x < profile.standardMin
    if (under) {
      out.belowStandard = true
      out.messages.push(
        `${profile.standardMinStrict ? '达到或低于' : '低于'}${profile.standardNote || ''}下限 ${profile.standardMin}%（${profile.sources[0]?.name || ''}），该水分下的产品不符合该标准`,
      )
    }
  }
  return out
}

/** 档位依据压成一行（界面 title / 说明用） */
export function moistureSourcesLine(profile) {
  if (!profile) return ''
  return profile.sources
    .map((s) => `${s.name}${s.clause ? ' ' + s.clause : ''}：${s.value}`)
    .join(' ｜ ')
}

/** 档位典型区间文案（无实测依据时明确写「未取得」，不编数） */
export function typicalRangeText(profile) {
  if (!profile) return '—'
  if (profile.typicalMin == null || profile.typicalMax == null) return '未取得实测典型区间'
  return `典型 ${profile.typicalMin}%~${profile.typicalMax}%`
}
