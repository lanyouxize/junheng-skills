/**
 * 原料数据质量层（M0 批次 1.2 + 1.3）。
 *
 * ## 为什么需要这一层
 *
 * 旧实现只用「是否为 null」判定数据缺失：
 *     _zero   = 任一字段 == null      → 是否报警
 *     _hasData= 任一字段 != null      → 界面是否显示「未录入」
 * 但现行原料库里 **「未录入」被大量写成 0**（289 条中 129 条 8 项全为 0，
 * 另有 81 条「无 null 但含 0」）。于是：
 *     · 0 被当成真值参与加权求和 → 结果系统性偏低；
 *     · `0 != null` → 系统认为"有数据" → **一条都不报警**。
 * 实测过一条真实配方：湿基水分 2.51%、钙磷比 14.12:1，界面却报「零数据 0 条」。
 *
 * ## 本层的口径（刻意不做营养判断）
 *
 * 只区分三种**可观测**状态，不对「0 究竟是真零还是没录」下结论：
 *     value   数值 > 0        —— 可直接用于计算
 *     zero    数值 == 0       —— 待复核：可能是真零（如纯油脂的粗纤维），
 *                                也可能是「未录入被写成 0」
 *     missing 空 / null / ''  —— 未录入（确定）
 *
 * 因此本模块**不引入任何营养学阈值**，只做「有没有可确认的数值」的统计。
 * 「零值到底是真零还是未录入」属于营养专业判断，留待人工在原料库里逐条确认
 * （M1 会提供「确认此 0 为真零」的动作），M0 只负责**把它显式暴露出来**。
 */

/** 营养字段的唯一出处（其他模块一律从这里 import；nutrition.js 会再转出一次） */
export const NUTRIENT_FIELDS = [
  ['crude_protein', '粗蛋白'],
  ['crude_fat', '粗脂肪'],
  ['crude_fiber', '粗纤维'],
  ['crude_ash', '粗灰分'],
  ['moisture', '水分'],
  ['calcium', '钙'],
  ['phosphorus', '磷'],
  ['chloride', '氯化物'],
]

export const FIELD_LABEL = Object.fromEntries(NUTRIENT_FIELDS)

/** 字段可计算性状态 */
export const FIELD_STATUS = { VALUE: 'value', ZERO: 'zero', MISSING: 'missing' }

/**
 * 覆盖率低于该值 → 该指标的结论标「数据不足」，仅作参考。
 * ⚠ 这是**数据质量阈值**（可调），不是营养标准限值，与任何法规要求无关。
 */
export const COVERAGE_LOW = 0.6

/* ---------------- 单字段 / 单条目 ---------------- */

/** 单个字段的数据状态：'value' | 'zero' | 'missing' */
export function fieldStatus(row, key) {
  const v = row?.[key]
  if (v === null || v === undefined || v === '') return FIELD_STATUS.MISSING
  const n = Number(v)
  if (!Number.isFinite(n)) return FIELD_STATUS.MISSING
  return n > 0 ? FIELD_STATUS.VALUE : FIELD_STATUS.ZERO
}

/**
 * 一条原料的营养数据状态。
 * @returns {{
 *   status:'complete'|'partial'|'none',
 *   fields:Object<string,string>, valueFields:string[], zeroFields:string[],
 *   missingFields:string[], suspectFields:string[], hasValue:boolean, suspect:boolean
 * }}
 *   · complete 8 项全部有 >0 数值
 *   · partial  有数值但缺项
 *   · none     一项数值都没有（即旧的「全 0 / 全 null」条目）
 */
export function ingredientDataStatus(row) {
  const fields = {}
  const valueFields = []
  const zeroFields = []
  const missingFields = []
  for (const [k] of NUTRIENT_FIELDS) {
    const s = fieldStatus(row, k)
    fields[k] = s
    if (s === FIELD_STATUS.VALUE) valueFields.push(k)
    else if (s === FIELD_STATUS.ZERO) zeroFields.push(k)
    else missingFields.push(k)
  }
  const suspectFields = [...zeroFields, ...missingFields]
  const status = valueFields.length === NUTRIENT_FIELDS.length ? 'complete'
    : valueFields.length === 0 ? 'none' : 'partial'
  return {
    status,
    fields,
    valueFields,
    zeroFields,
    missingFields,
    suspectFields,
    hasValue: valueFields.length > 0,
    suspect: suspectFields.length > 0,
  }
}

/* ---------------- 配方级覆盖率 ---------------- */

/**
 * 逐字段统计本配方有多少条原料**确实带数值**。
 * items: [{ ingredient, weight }]
 * @returns {Object<string, {
 *   key, label, have, zero, missing, total,
 *   ratio, filledRatio, status, belowLow,
 *   zeroNames:string[], missingNames:string[], suspectNames:string[]
 * }>}
 * 口径（两个比值含义不同，界面必须分别说明）：
 *   ratio       有**正数值**的比例 = have / total —— 「数据可信度」用它，
 *               因为库里大量「未录入」被写成 0，0 必须按不可信处理
 *   filledRatio **已填写**比例 = (have + zero) / total —— 「填写完整度」用它，
 *               只反映"这个格子里有没有写过东西"，不表示写的东西可信
 *   status      'full' 全部有正数值 / 'partial' 部分有 / 'none' 一条都没有（结论不可用）
 *   belowLow    正数值比例低于 COVERAGE_LOW → 结论标「仅供参考」，且不给具体添加量
 */
export function recipeCoverage(items = []) {
  const valid = items.filter((x) => x.ingredient && x.weight > 0)
  const total = valid.length
  const out = {}
  for (const [k, label] of NUTRIENT_FIELDS) {
    let have = 0
    let zero = 0
    let missing = 0
    const zeroNames = []
    const missingNames = []
    for (const { ingredient } of valid) {
      const s = fieldStatus(ingredient, k)
      if (s === FIELD_STATUS.VALUE) have += 1
      else if (s === FIELD_STATUS.ZERO) { zero += 1; zeroNames.push(ingredient._bare || ingredient.name) }
      else { missing += 1; missingNames.push(ingredient._bare || ingredient.name) }
    }
    const ratio = total ? have / total : 0
    const filledRatio = total ? (have + zero) / total : 0
    out[k] = {
      key: k,
      label,
      have,
      zero,
      missing,
      total,
      ratio,
      filledRatio,
      status: ratio >= 1 ? 'full' : (ratio > 0 ? 'partial' : 'none'),
      belowLow: ratio > 0 && ratio < COVERAGE_LOW,
      zeroNames,
      missingNames,
      suspectNames: [...missingNames, ...zeroNames],
    }
  }
  return out
}

/**
 * 覆盖率汇总（给界面顶部一句话用）。
 * @returns {{fields:number, full:number, partial:number, none:number, avgRatio:number,
 *   blockedKeys:string[], lowKeys:string[], text:string}}
 *   blockedKeys 一条正数值都没有的指标 → 结论不可用
 */
export function summarizeCoverage(cov) {
  const keys = Object.keys(cov || {})
  const full = keys.filter((k) => cov[k].status === 'full').length
  const none = keys.filter((k) => cov[k].status === 'none').length
  const partial = keys.length - full - none
  const avgRatio = keys.length ? keys.reduce((s, k) => s + cov[k].ratio, 0) / keys.length : 0
  const blockedKeys = keys.filter((k) => cov[k].status === 'none')
  const lowKeys = keys.filter((k) => cov[k].belowLow)
  const unfilled = keys.filter((k) => cov[k].missing > 0)
  const zeroFilled = keys.filter((k) => cov[k].zero > 0)
  const bits = []
  if (none) bits.push(`${none} 项指标完全没有正数值（不足以判定：${blockedKeys.map((k) => cov[k].label).join('、')}）`)
  if (lowKeys.length) bits.push(`${lowKeys.length} 项指标正数值不足 ${Math.round(COVERAGE_LOW * 100)}%`)
  if (zeroFilled.length) bits.push(`${zeroFilled.length} 项指标存在填为 0 的原料（待复核是否真零）`)
  if (unfilled.length) bits.push(`${unfilled.length} 项指标存在空值原料（确定未录入）`)
  const text = bits.length ? `数据完整性：${bits.join('；')}` : '数据完整性：8 项指标均有正数值'
  return { fields: keys.length, full, partial, none, avgRatio, blockedKeys, lowKeys, unfilled, zeroFilled, text }
}

/**
 * 按「已录入原料」重新归一化，给出该字段的**估计值**（原样基础 %）。
 *
 * 口径：只拿确实有数值（>0）的原料，按其重量重新归一化。
 * ⚠ 这是**估计**，不是真值：它隐含假设「缺数据的原料对该指标的贡献与同类相当」，
 *   真实值应当由补全原料数据后重算得到。因此调用方必须把它标为估计值。
 *
 * @returns {{ value:number|null, basis:number, total:number, coverage:number }|null}
 *   basis = 参与估计的重量合计；coverage = have/total；一条可用原料都没有时返回 null
 */
export function renormalizedEstimate(items = [], key, cov = null) {
  const valid = items.filter((x) => x.ingredient && x.weight > 0)
  const total = valid.reduce((s, x) => s + x.weight, 0)
  if (!total) return null
  const usable = valid.filter((x) => fieldStatus(x.ingredient, key) === FIELD_STATUS.VALUE)
  const basis = usable.reduce((s, x) => s + x.weight, 0)
  if (!basis) return null
  const value = usable.reduce((s, x) => s + Number(x.ingredient[key]) * x.weight, 0) / basis
  return {
    value: Math.round(value * 100) / 100,
    basis,
    total,
    coverage: cov ? cov.ratio : usable.length / valid.length,
  }
}

/* ---------------- 数据体检规则（1.3 哨兵） ---------------- */

/**
 * 筛查阈值。⚠ 这些是**发现明显不可能值的经验阈值**（可调），
 *   用于把可疑条目挑出来交人工复核，**不是营养标准限值**，也不作为判定依据。
 */
export const SANITY_THRESHOLDS = {
  fatMinForOil: 50,        // 名称含「油」「脂」的原料，粗脂肪低于此值 → 疑似异常
  proteinMaxForStarch: 20, // 名称含「淀粉」的原料，粗蛋白高于此值 → 疑似异常
  sumMax: 105,             // 常规成分（蛋白+脂肪+纤维+灰分+水分）合计上限
  caPRatioMax: 10,         // 单条原料钙磷比上限
  caPRatioMin: 0.1,        // 单条原料钙磷比下限
}

const OIL_RE = /油|脂/
/**
 * 名称含「油/脂」但**显然不是「油脂类原料」**的写法，用于压掉规则误报（否则清单里一半是噪声，没人愿意看）：
 *   甘油（丙三醇，不是油）、琼脂（多糖）、抗氧化剂/植脂末（含「脂」字的商品名）、
 *   各类淀粉磷酸酯（「磷酸酯」含脂字）、「全脂XX」（表示保留天然脂肪，脂肪值本就不该接近 100%）。
 */
export const SANITY_OIL_EXCLUDE_RE = /甘油|琼脂|抗氧化剂|植脂末|磷酸脂|磷酸酯|全脂/
const OIL_FALSE_POSITIVE_RE = SANITY_OIL_EXCLUDE_RE
const STARCH_RE = /淀粉/
const CA_SOURCE_RE = /碳酸钙|磷酸三钙|蛋壳粉|骨粉|贝壳粉/
const WATER_RE = /^水$|^饮用水$|^纯净水$|^纯水$/

/**
 * 对原料行做体检，返回待复核清单。
 * @param {Array} rows 原料行（含 name / code / 8 项营养 / price）
 * @returns {{ issues:Array<{rule,level,name,code,field,value,detail}>, byRule:Object<string,number>, counts:Object }}
 */
export function buildSanityIssues(rows = []) {
  const issues = []
  const add = (rule, level, row, field, value, detail) =>
    issues.push({ rule, level, name: row.name, code: row.code || '', field, value, detail })

  for (const r of rows) {
    if (!r || !r.name) continue
    const name = String(r.name)
    const st = ingredientDataStatus(r)

    // R1 全无数据（全 null / 全 0）——「未录入被写成 0」的主要形态
    if (st.status === 'none') {
      add('no-data', 'error', r, '', null,
        st.missingFields.length === NUTRIENT_FIELDS.length
          ? '8 项营养全为空值（未录入）'
          : '8 项营养全为 0（未录入被写成 0，或确为全零原料，待复核）')
    }

    // R2 油脂类脂肪异常
    if (OIL_RE.test(name) && !OIL_FALSE_POSITIVE_RE.test(name) && !/油炸|油条/.test(name)) {
      const fat = r.crude_fat
      if (fat == null) add('oil-fat', 'error', r, 'crude_fat', fat, '油脂类原料的粗脂肪为空')
      else if (Number(fat) === 0) add('oil-fat', 'error', r, 'crude_fat', fat, '油脂类原料的粗脂肪为 0（不可能）')
      else if (Number(fat) < SANITY_THRESHOLDS.fatMinForOil) add('oil-fat', 'warn', r, 'crude_fat', fat, `油脂类原料的粗脂肪仅 ${fat}%，疑似异常偏低`)
    }

    // R3 原料「水」的水分
    if (WATER_RE.test(name)) {
      const m = r.moisture
      if (m == null || Number(m) !== 100) add('water-moisture', 'error', r, 'moisture', m, `原料「${name}」的水分应为 100%，当前为 ${m == null ? '空' : m}%`)
    }

    // R4 钙源原料的钙
    if (CA_SOURCE_RE.test(name)) {
      const ca = r.calcium
      if (ca == null || Number(ca) === 0) add('ca-source', 'error', r, 'calcium', ca, `钙源原料的钙为空或 0，无法用于补钙计算`)
    }

    // R5 淀粉类原料的粗蛋白
    if (STARCH_RE.test(name) && r.crude_protein != null && Number(r.crude_protein) > SANITY_THRESHOLDS.proteinMaxForStarch) {
      add('starch-protein', 'warn', r, 'crude_protein', r.crude_protein, `淀粉类原料粗蛋白 ${r.crude_protein}% 异常偏高，疑似与其它原料数据串行`)
    }

    // R6 常规成分合计
    const sum = ['crude_protein', 'crude_fat', 'crude_fiber', 'crude_ash', 'moisture']
      .reduce((s, k) => s + (Number(r[k]) > 0 ? Number(r[k]) : 0), 0)
    if (sum > SANITY_THRESHOLDS.sumMax) {
      add('sum-over', 'error', r, '', Math.round(sum * 100) / 100, `蛋白+脂肪+纤维+灰分+水分 合计 ${Math.round(sum * 100) / 100}% 超过 105%`)
    }

    // R7 单条原料钙磷比
    if (Number(r.calcium) > 0 && Number(r.phosphorus) > 0) {
      const x = Number(r.calcium) / Number(r.phosphorus)
      if (x > SANITY_THRESHOLDS.caPRatioMax || x < SANITY_THRESHOLDS.caPRatioMin) {
        add('ing-ca-p', 'warn', r, '', Math.round(x * 100) / 100, `单条原料钙磷比 ${(Math.round(x * 100) / 100)}:1 超出常规范围`)
      }
    }

    // R8 覆盖率类提示（非错误）：关键字段全库覆盖极低属结构性问题，逐条不报，由哨兵汇总
    if (Number(r.price) === 0 || r.price == null) {
      add('no-price', 'info', r, 'price', r.price, '无单价，成本核算按 0 计')
    }
  }

  const byRule = {}
  for (const i of issues) byRule[i.rule] = (byRule[i.rule] || 0) + 1
  return {
    issues,
    byRule,
    counts: {
      total: issues.length,
      error: issues.filter((i) => i.level === 'error').length,
      warn: issues.filter((i) => i.level === 'warn').length,
      info: issues.filter((i) => i.level === 'info').length,
      rules: Object.keys(byRule).length,
    },
  }
}

/** 规则说明（报告与界面共用同一份文案，避免两处口径不一致） */
export const SANITY_RULE_LABEL = {
  'no-data': '8 项营养全无数据（全空或全 0）',
  'oil-fat': '油脂类原料粗脂肪为空 / 0 / 异常偏低',
  'water-moisture': '原料「水」的水分不为 100%',
  'ca-source': '钙源原料的钙为空或 0',
  'starch-protein': '淀粉类原料粗蛋白异常偏高',
  'sum-over': '常规成分合计超过 105%',
  'ing-ca-p': '单条原料钙磷比超出常规范围',
  'no-price': '无单价（成本按 0 计）',
}
