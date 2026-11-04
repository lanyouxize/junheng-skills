/**
 * 成本核算模式配置与计算：冻干 / 猫条（10g、14g、15g 三种规格）。
 *
 * 数据来源：逐张核对下列实际成本核算表，各表参数独立配置，禁止跨规格复用同一套数值。
 *   · 冻干：美毛功能性冻干零配方-成本核算表2026.9.21.xlsx（排毛 / 美毛 两个 sheet）
 *   · 猫条 10g：网易宠物零食肉满多猫条成本核算8.10.xlsx
 *   · 猫条 14g：外贸土PG猫条成本核算表-2026.6.25(1).xlsx（南瓜 / 石榴 等 sheet）
 *   · 猫条 15g：IPC低价猫条成本核算.xlsx（鸡肉龙虾尾 / 金枪鱼虾肉 sheet）
 *
 * 计算口径（与原表公式一致）：
 *   解冻后用料添加量 = 添加比例 × 投料基数(kg)
 *   解冻前用料添加量 = 解冻后用料 ÷ 原料出成率      ← 原表 H=G/63%（仅肉类等有出成损耗的原料）
 *   金额             = 采购单价 × 解冻前用料
 *   产品出成(解冻后) = 成品产量 ÷ Σ解冻后用料       ← 原表 F27
 *   产品出成(解冻前) = 成品产量 ÷ Σ解冻前用料       ← 原表 H27
 *   原辅料单位成本   = Σ金额 ÷ 成品产量             ← 冻干 ÷220kg、猫条 ÷950kg（按成品分摊）
 *   原辅料吨耗成本   = 原辅料单位成本 × 1000
 *   半成品成本合计   = 原辅料吨耗成本 + Σ各项加工费(元/吨)
 *   单位成本         = 半成品成本合计 ÷ 1000
 *   单位成本(含损耗) = 单位成本 × (1 + 损耗率)
 *   元/支（猫条）    = 单位成本(含损耗) ÷ 1000 × 克重
 */
import { computeCostSheet } from './nutrition.js'

const r2 = (n) => (Number.isFinite(n) ? Math.round(n * 100) / 100 : 0)
const r4 = (n) => (Number.isFinite(n) ? Math.round(n * 10000) / 10000 : 0)

/* ---------------- 模式清单 ---------------- */

export const COST_MODES = [
  { id: 'general', label: '通用（烘焙粮/产品成本明细表）', desc: '按原「产品成本明细表」格式，单一加工费（元/吨）' },
  { id: 'freeze_dry', label: '冻干', desc: '冻干专属：投料→冻干成品大幅缩减，五项加工费（元/吨）' },
  { id: 'cat_stick', label: '猫条', desc: '猫条专属：10g/14g/15g 各一张表；加工费已整合「1支猫条车间成本」（元/支 × 含损耗支数）' },
]

export const DEFAULT_COST_MODE = 'general'

/* ---------------- 冻干配置 ---------------- */

/**
 * 冻干加工费：单位「元/吨（成品）」，取自原表 I29:I33。
 * 与猫条不同——冻干为固定金额，不随克重/支数变化。
 */
export const FREEZE_DRY_FEE_FIELDS = [
  ['labor', '直接人工', '工资'],
  ['utility', '能耗及摊销', '水电气'],
  ['depreciation', '车间折旧摊销', ''],
  ['overhead', '车间管理费', ''],
  ['tooling', '辅助工具费用', 'PP模具'],
]

export const FREEZE_DRY_CONFIG = {
  /** 投料基数（原表 C3「数量/kg」=1000） */
  inputKg: 1000,
  /** 冻干成品产量（原表 C5「产量」/E9 =220kg，即投料 1000kg 出 220kg 成品） */
  outputKg: 220,
  /** 包装克重（原表 C4=100g），冻干表不折算「元/支」 */
  packageGram: 100,
  lossRate: 0.05,
  feesPerTon: {
    labor: 11357.63,
    utility: 11281.36,
    depreciation: 6779.66,
    overhead: 1016.95,
    tooling: 2743.05,
  },
  /** 冻干另设「辅助工具费用（PP模具）」，猫条则为「外加工费用」——两者不可互相套用 */
  note: '原表 H 列「失水率/复水率」为空：解冻前用料暂按等于解冻后用料计（待确认，需产线提供各原料冻干失水率后逐项补录）。',
}

/* ---------------- 猫条配置（三种规格各自独立） ---------------- */

export const CAT_STICK_FEE_FIELDS = [
  ['labor', '直接人工', '工资'],
  ['utility', '能耗及摊销', '水电气'],
  ['depreciation', '车间折旧摊销', ''],
  ['overhead', '车间管理费', ''],
  ['outsourcing', '外加工费用', ''],
]

/**
 * 三种规格逐表核对。注意：
 *  · 加工费已整合「1支猫条车间成本」口径：车间加工单价（元/支）由 workshopSpecId 映射的价格列决定
 *    （10g→10克列、14g/15g→15克列），不再按规格另存一套数值；ratesPerStick 仅作兜底/外加工项缺省值。
 *  · 支数（车间口径）= 投料基数 × 1000 ÷（标称克重 + 每支损耗），取整数位（小数舍去），
 *    故同为 0.033 元/支，10g 与 15g 的元/吨金额必然不同——不可统一数值。
 *  · 产品出成（解冻前口径）因配方构成不同而异：10g≈88.86%、14g≈83.67%、15g≈84.96%，为计算结果而非配置值。
 *  · extraFeePerKg：仅「外贸土PG猫条-核心粉料」表在含损耗成本上另加 3 元/kg 加工费，
 *    成品口味表（南瓜/石榴等）无此项，故默认 0，需要时单独开启。
 */
export const CAT_STICK_SPECS = [
  {
    id: 'g10',
    label: '10g/支',
    gramPerStick: 10,
    batchKg: 1000,
    outputKg: 950,
    lossRate: 0.05,
    /** 车间成本规格映射：10g → 图片 10克 列 */
    workshopSpecId: 'w10',
    ratesPerStick: { labor: 0.033, utility: 0.0138, depreciation: 0.0164, overhead: 0.0054, outsourcing: 0 },
    extraFeePerKg: 0,
    source: '网易宠物零食肉满多猫条成本核算8.10.xlsx',
  },
  {
    id: 'g14',
    label: '14g/支',
    gramPerStick: 14,
    batchKg: 1000,
    outputKg: 950,
    lossRate: 0.05,
    /** 14g 与 15g 规格同取图片 15克 列价格（业务规则） */
    workshopSpecId: 'w14',
    ratesPerStick: { labor: 0.033, utility: 0.0138, depreciation: 0.0164, overhead: 0.0054, outsourcing: 0 },
    extraFeePerKg: 0,
    source: '外贸土PG猫条成本核算表-2026.6.25(1).xlsx',
  },
  {
    id: 'g15',
    label: '15g/支',
    gramPerStick: 15,
    batchKg: 1000,
    outputKg: 950,
    lossRate: 0.05,
    workshopSpecId: 'w15',
    ratesPerStick: { labor: 0.033, utility: 0.0138, depreciation: 0.0164, overhead: 0.0054, outsourcing: 0 },
    extraFeePerKg: 0,
    source: 'IPC低价猫条成本核算.xlsx',
  },
]

export const DEFAULT_CAT_STICK_SPEC = 'g10'

export const getCatStickSpec = (id) => CAT_STICK_SPECS.find((s) => s.id === id) || CAT_STICK_SPECS[0]

/* ---------------- 猫条车间成本配置（口径：1支猫条车间成本.png） ---------------- */

/** 车间加工成本四项（对应图片行，全部为 元/支 单支加工成本单价） */
export const WORKSHOP_FEE_FIELDS = [
  ['labor', '人工'],
  ['utility', '水电气'],
  ['depreciation', '折旧摊销'],
  ['overhead', '管理费用'],
]

/**
 * 损耗系数（可配置）：支数换算时在标称规格基础上每支增加的克数。
 * 当前规则：标称 10g 按 11g/支、14g 按 15g/支、15g 按 16g/支计（即每支 +1g 损耗）。
 */
export const WORKSHOP_LOSS_CONFIG = {
  lossGramPerStick: 1,
  note: '支数换算规则：标称规格基础上每支增加 1g 损耗（10g按11g/支、14g按15g/支、15g按16g/支计）；支数 = 重量kg × 1000 ÷（标称克重 + 每支损耗），取整数位，小数点后直接舍去（不四舍五入）。',
}

/**
 * 图片「1支猫条车间成本」价格表：所有价格均为 元/支（单支加工成本单价），
 * 禁止当作每克或每批价格使用。列：10克 / 12克 / 15克。
 * subtotal 为图片原表小计，用于校验单价配置是否与图片一致。
 */
export const WORKSHOP_PRICE_TABLE = {
  c10: { label: '10克', ratesPerStick: { labor: 0.0273, utility: 0.0124, depreciation: 0.0148, overhead: 0.0049 }, subtotal: 0.0594 },
  c12: { label: '12克', ratesPerStick: { labor: 0.03, utility: 0.013, depreciation: 0.0154, overhead: 0.0051 }, subtotal: 0.0635 },
  c15: { label: '15克', ratesPerStick: { labor: 0.033, utility: 0.0138, depreciation: 0.0164, overhead: 0.0054 }, subtotal: 0.0686 },
}

/**
 * 规格 → 价格列映射（可配置）。
 * 注意：14g 与 15g 规格的加工成本相同，均取图片 15克 列价格（业务规则，非笔误）。
 */
export const WORKSHOP_SPECS = [
  { id: 'w10', label: '10g（按11g/支计）', nominalGram: 10, priceCol: 'c10', source: '1支猫条车间成本.png（10克列）' },
  { id: 'w14', label: '14g（按15g/支计）', nominalGram: 14, priceCol: 'c15', source: '1支猫条车间成本.png（15克列，14g与15g规格同价）' },
  { id: 'w15', label: '15g（按16g/支计）', nominalGram: 15, priceCol: 'c15', source: '1支猫条车间成本.png（15克列）' },
]

export const getWorkshopSpec = (id) => WORKSHOP_SPECS.find((s) => s.id === id) || null

/* ---------------- 通用计算核心 ---------------- */

/**
 * 按模式核算。params:
 *   mode           'general' | 'freeze_dry' | 'cat_stick'
 *   productName    产品名称
 *   specId         猫条规格 id（mode=cat_stick 时必填）
 *   inputKg        投料基数 kg（冻干 1000 / 猫条 1000）
 *   outputKg       成品产量 kg（冻干 220 / 猫条 950）
 *   gramPerStick   猫条克重（由规格决定，可覆盖）
 *   lossRate       损耗率
 *   feesPerTon     冻干：各项加工费 元/吨
 *   ratesPerStick  猫条：各项加工费 元/支
 *   extraFeePerKg  额外加工费 元/kg（土PG核心粉料口径，默认 0）
 *   processingFeePerTon  通用模式：单一加工费 元/吨
 *   batchCount / gramPerBag  通用模式：袋数 / 克重
 *   lines          [{ code, name, unit, ratio, unitPrice, yieldRate, note }]
 *                  yieldRate 为原料出成率（如蒸熟鸡大胸 0.63），缺省 1
 * @returns 与 computeCostSheet() 结构一致的结果对象 + 模式专属字段
 */
export function computeCostSheetByMode(params = {}) {
  const mode = params.mode || DEFAULT_COST_MODE
  if (mode === 'general') {
    return computeCostSheet({
      productName: params.productName,
      batchCount: params.batchCount,
      gramPerBag: params.gramPerBag,
      lossRate: params.lossRate,
      processingFeePerTon: params.processingFeePerTon,
      lines: params.lines || [],
    })
  }
  if (mode === 'freeze_dry') return computeFreezeDrySheet(params)
  if (mode === 'cat_stick') return computeCatStickSheet(params)
  if (mode === 'cat_stick_workshop') return computeCatStickWorkshop(params)
  return null
}

/**
 * 冻干核算。
 * 与通用的差异：金额按「解冻前用料」计（含失水率折算）；成品产量远小于投料（出成≈22%）；
 * 加工费为五项固定「元/吨」；不输出「元/支」。
 */
export function computeFreezeDrySheet(params = {}) {
  const cfg = FREEZE_DRY_CONFIG
  const inputKg = num(params.inputKg, cfg.inputKg)
  const outputKg = num(params.outputKg, cfg.outputKg)
  const lossRate = num(params.lossRate, cfg.lossRate)
  const feesPerTon = { ...cfg.feesPerTon, ...(params.feesPerTon || {}) }

  const base = buildLines(params.lines || [], inputKg)
  if (!base) return null

  const fees = buildFees(FREEZE_DRY_FEE_FIELDS, feesPerTon, null)
  return finalize({
    mode: 'freeze_dry',
    modeLabel: '冻干',
    productName: params.productName || '',
    inputKg,
    outputKg,
    lossRate,
    packageGram: num(params.packageGram, cfg.packageGram),
    ...base,
    fees,
    extraFeePerKg: 0,
    sticks: null,
    feeBasisNote: '加工费为固定「元/吨（成品）」，不随克重变化',
  })
}

/**
 * 猫条核算（已整合车间成本：加工费即车间加工成本，不再单独另算）。
 * 计算链：投料基数 → 支数（车间口径，含每支损耗，取整舍去小数）→ 车间加工单价(元/支) × 支数 = 加工费(元/吨)
 *        → 原辅料成本 + 加工费 = 半成品合计 → 单位成本 → 含损耗 → 元/支。
 * 车间单价由 WORKSHOP_SPECS 的规格→价格列映射决定（10g 取 10克列；14g/15g 取 15克列）。
 * 额外输出 workshop 明细块，便于核对单支车间成本与金额。
 */
export function computeCatStickSheet(params = {}) {
  const spec = getCatStickSpec(params.specId)
  const inputKg = num(params.inputKg, spec.batchKg)
  const outputKg = num(params.outputKg, spec.outputKg)
  const lossRate = num(params.lossRate, spec.lossRate)
  const gramPerStick = num(params.gramPerStick, spec.gramPerStick)
  const extraFeePerKg = num(params.extraFeePerKg, spec.extraFeePerKg)

  // ---- 车间成本（内含）：规格映射 + 每支损耗 ----
  const wsSpec = WORKSHOP_SPECS.find((s) => s.id === (params.workshopSpecId || spec.workshopSpecId)) || null
  const col = wsSpec ? WORKSHOP_PRICE_TABLE[wsSpec.priceCol] : null
  const lossGram = num(params.lossGramPerStick, WORKSHOP_LOSS_CONFIG.lossGramPerStick)
  const gramWithLoss = gramPerStick + lossGram

  // 支数：车间口径（含损耗）用于加工费；标称口径仅作参考
  const sticks = Math.floor((inputKg * 1000) / gramWithLoss)
  const sticksNominal = Math.floor((inputKg * 1000) / gramPerStick)

  // 单价优先级：用户覆盖 > 车间图片价格表 > 规格兜底值（含外加工项缺省 0）
  const ratesPerStick = {
    ...spec.ratesPerStick,
    ...(col ? col.ratesPerStick : {}),
    ...(params.ratesPerStick || {}),
  }

  const base = buildLines(params.lines || [], inputKg)
  if (!base) return null

  const fees = buildFees(CAT_STICK_FEE_FIELDS, null, ratesPerStick, sticks)

  // 车间成本明细块（与加工费同源：单价 × 同一支数）
  const ws = buildWorkshopItems(ratesPerStick, sticks, wsSpec ? wsSpec.label : '')
  const workshop = wsSpec && col ? {
    specId: wsSpec.id,
    specLabel: wsSpec.label,
    priceCol: wsSpec.priceCol,
    priceColLabel: col.label,
    expectedSubtotal: col.subtotal,
    nominalGram: gramPerStick,
    lossGramPerStick: lossGram,
    gramWithLoss,
    sticks,
    items: ws.items,
    perStickTotal: ws.perStickTotal,
    total: ws.total,
  } : null

  const sheet = finalize({
    mode: 'cat_stick',
    modeLabel: '猫条',
    specId: spec.id,
    specLabel: spec.label,
    productName: params.productName || '',
    inputKg,
    outputKg,
    lossRate,
    gramPerStick,
    ...base,
    fees: { list: fees.list, total: fees.total, warnings: [...(fees.warnings || []), ...ws.warnings.filter((w) => !fees.warnings.some((x) => x.startsWith(w.split('：')[0])))] },
    extraFeePerKg,
    sticks,
    sticksNominal,
    lossGramPerStick: lossGram,
    gramWithLoss,
    workshop,
    feeBasisNote: `加工费 = 车间成本单价（元/支，${col ? col.label : '未配置'}列）× 支数 ${sticks.toLocaleString()} 支；支数 = ${inputKg}kg × 1000 ÷ ${gramWithLoss}g（标称 ${gramPerStick}g + 每支损耗 ${lossGram}g），取整数位（小数舍去）`,
  })
  return sheet
}

/* ---------------- 内部：明细行 / 加工费 / 汇总 ---------------- */

/**
 * 猫条车间成本核算（口径：1支猫条车间成本.png，仅加工成本，不依赖配方原料）。
 * params:
 *   specId           规格 id（w10/w14/w15，必填；未匹配时返回 error，不做默认计算）
 *   qtyMode          'sticks'（按支数）| 'weight'（按重量 kg）
 *   qty              生产/采购量（支数或 kg，由 qtyMode 决定）
 *   lossGramPerStick 每支损耗 g（默认取 WORKSHOP_LOSS_CONFIG.lossGramPerStick = 1，可配置）
 *   ratesPerStick    单价覆盖（覆盖图片价格表中对应项；缺项按 0 并写入 warnings）
 * @returns 车间成本结果；无法匹配规格/价格缺失时通过 error / warnings 明确提示
 */
export function computeCatStickWorkshop(params = {}) {
  const spec = params.specId ? WORKSHOP_SPECS.find((s) => s.id === params.specId) : null
  if (!spec) {
    return { mode: 'cat_stick_workshop', error: `未匹配到猫条规格：${params.specId ?? '（未选择）'}。请选择 10g / 14g / 15g 之一，系统不做默认计算。` }
  }
  const lossGram = num(params.lossGramPerStick, WORKSHOP_LOSS_CONFIG.lossGramPerStick)
  if (!(lossGram >= 0)) {
    return { mode: 'cat_stick_workshop', error: `每支损耗系数无效：${params.lossGramPerStick}，请填写 ≥ 0 的数值。` }
  }
  const gramWithLoss = spec.nominalGram + lossGram
  const col = WORKSHOP_PRICE_TABLE[spec.priceCol]
  if (!col) {
    return { mode: 'cat_stick_workshop', error: `规格「${spec.label}」未配置价格列映射（priceCol 待确认），不做默认计算。` }
  }

  const qtyMode = params.qtyMode === 'weight' ? 'weight' : 'sticks'
  const qty = Number(params.qty)
  if (!Number.isFinite(qty) || qty <= 0) {
    return { mode: 'cat_stick_workshop', error: `请输入有效的生产/采购量（${qtyMode === 'weight' ? '重量 kg' : '支数'}），当前值：${params.qty ?? '（空）'}。` }
  }

  // 支数换算：按支数直接取输入值；按重量 = kg × 1000 ÷（标称克重 + 每支损耗）。
  // 支数一律取整数位，小数点后直接舍去（不四舍五入）。
  const rawSticks = qtyMode === 'sticks' ? qty : (qty * 1000) / gramWithLoss
  const sticks = Math.floor(rawSticks)
  const sticksTruncated = rawSticks !== sticks
  // 用量（含损耗口径）
  const usageKg = (sticks * gramWithLoss) / 1000
  const nominalUsageKg = (sticks * spec.nominalGram) / 1000
  const lossKg = usageKg - nominalUsageKg

  const warnings = []
  const rates = { ...col.ratesPerStick, ...(params.ratesPerStick || {}) }
  const built = buildWorkshopItems(rates, sticks)
  warnings.push(...built.warnings)
  const perStickTotal = built.perStickTotal
  const total = built.total

  return {
    mode: 'cat_stick_workshop',
    modeLabel: '猫条车间成本',
    specId: spec.id,
    specLabel: spec.label,
    nominalGram: spec.nominalGram,
    lossGramPerStick: lossGram,
    gramWithLoss,
    priceCol: spec.priceCol,
    priceColLabel: col.label,
    expectedSubtotal: col.subtotal,
    qtyMode,
    qty,
    sticks: r4(sticks),
    usageKg: r4(usageKg),
    nominalUsageKg: r4(nominalUsageKg),
    lossKg: r4(lossKg),
    feeItems: built.items,
    perStickTotal,
    total,
    feeBasisNote: `单支加工成本 = ${col.label}列四项单价合计 ${perStickTotal} 元/支；支数 = ${qtyMode === 'sticks' ? `${qty} 支（直接输入）` : `${qty}kg × 1000 ÷ ${gramWithLoss}g${sticksTruncated ? `（原始值 ${r4(rawSticks)}，舍去小数）` : ''}`}，取整数位（小数直接舍去，不四舍五入）；用量 = 支数 × ${gramWithLoss}g/支（标称 ${spec.nominalGram}g + 损耗 ${lossGram}g）`,
    warnings,
  }
}


/** 构建直接材料明细：解冻后用料 → 解冻前用料（按原料出成率折算）→ 金额 */
function buildLines(rawLines, inputKg) {
  if (!inputKg || inputKg <= 0) return null
  const lines = (rawLines || [])
    // ⚠ 只认有效占比，不用 `|| l.name` 兜底 —— 用量/占比为 0 的行应彻底剔除，
    //   否则它会以「金额 0」的形态留在成本表并被 Excel 导出带走，
    //   让使用者误以为配方里真有这么一味。与 `computeRecipe` 的
    //   `filter(x => x.weight > 0)` 保持同一口径。
    .filter((l) => l && Number(l.ratio) > 0)
    .map((l) => {
      const ratio = Number(l.ratio) || 0
      const unitPrice = Number(l.unitPrice) || 0
      // 原料出成率：默认 1（无损耗）；肉类等按实际填写，如蒸熟鸡大胸 0.63
      const yr = Number(l.yieldRate) > 0 && Number(l.yieldRate) <= 1 ? Number(l.yieldRate) : 1
      const thawedAmount = ratio * inputKg // 解冻后用料添加量
      const beforeAmount = yr > 0 ? thawedAmount / yr : thawedAmount // 解冻前用料添加量
      return {
        code: l.code || '',
        name: l.name || '',
        unit: l.unit || 'kg',
        ratio: r4(ratio),
        yieldRate: yr,
        thawedAmount: r4(thawedAmount),
        beforeAmount: r4(beforeAmount),
        unitPrice,
        amount: r4(unitPrice * beforeAmount),
        note: l.note || '',
      }
    })
  if (!lines.length) return null
  const totalRatio = lines.reduce((s, l) => s + l.ratio, 0)
  const totalThawed = lines.reduce((s, l) => s + l.thawedAmount, 0)
  const totalBefore = lines.reduce((s, l) => s + l.beforeAmount, 0)
  const totalAmount = lines.reduce((s, l) => s + l.amount, 0)
  return { lines, totalRatio, totalThawed, totalBefore, totalAmount }
}

/**
 * 车间成本明细公共构建：单价（元/支）× 支数 = 金额（猫条加工费与独立车间核算共用）。
 * 缺项写入 warnings「待确认」并按 0 计，不臆造数值。
 */
function buildWorkshopItems(rates, sticks, specLabel = '') {
  const warnings = []
  const items = WORKSHOP_FEE_FIELDS.map(([key, label]) => {
    const v = rates ? rates[key] : null
    const missing = v == null || v === '' || !Number.isFinite(Number(v))
    if (missing) warnings.push(`${label}${specLabel ? `（规格 ${specLabel}）` : ''}：车间单价缺失，暂按 0 计（待确认，请补录或检查 WORKSHOP_PRICE_TABLE 配置）`)
    const perStick = missing ? 0 : Number(v)
    return { key, label, perStick, amount: r4(perStick * sticks) }
  })
  return {
    items,
    perStickTotal: r4(items.reduce((s, f) => s + f.perStick, 0)),
    total: r4(items.reduce((s, f) => s + f.amount, 0)),
    warnings,
  }
}

/**
 * 构建加工费明细（元/吨）。
 * 冻干传 feesPerTon（固定金额）；猫条传 ratesPerStick + sticks（元/支 × 支数）。
 * 缺项按 0 计并写入 warnings 标注「待确认」，不臆造数值。
 */
function buildFees(fields, feesPerTon, ratesPerStick, sticks) {
  const warnings = []
  const fees = fields.map(([key, group, sub]) => {
    let perTon = 0
    let basis = ''
    if (feesPerTon) {
      const v = feesPerTon[key]
      if (v == null || !Number.isFinite(Number(v))) {
        warnings.push(`${group}${sub ? '·' + sub : ''}：未提供，暂按 0 计（待确认）`)
        perTon = 0
      } else {
        perTon = Number(v)
        basis = '元/吨'
      }
    } else if (ratesPerStick) {
      const v = ratesPerStick[key]
      if (v == null || !Number.isFinite(Number(v))) {
        warnings.push(`${group}${sub ? '·' + sub : ''}：未提供单价，暂按 0 计（待确认）`)
        perTon = 0
      } else {
        perTon = Number(v) * (sticks || 0)
        basis = `元/支 × ${Math.round(sticks || 0)}支`
      }
    }
    return { key, group, sub, perTon: r4(perTon), basis }
  })
  return { list: fees, total: r4(fees.reduce((s, f) => s + f.perTon, 0)), warnings }
}

/** 汇总：出成率（双口径）→ 原辅料成本 → 半成品合计 → 单位成本 → 含损耗 → 元/支 */
function finalize(ctx) {
  const { lines, totalRatio, totalThawed, totalBefore, totalAmount, outputKg, lossRate, fees } = ctx
  const yieldAfter = totalThawed > 0 ? outputKg / totalThawed : 0
  const yieldBefore = totalBefore > 0 ? outputKg / totalBefore : 0
  const materialUnitCost = outputKg > 0 ? totalAmount / outputKg : 0
  const materialTonCost = materialUnitCost * 1000
  const semiTotal = materialTonCost + fees.total
  const unitCost = semiTotal / 1000
  const unitCostWithLoss = unitCost * (1 + lossRate)
  // 元/支：仅猫条（有克重口径）
  const perStick = ctx.gramPerStick ? (unitCostWithLoss / 1000) * ctx.gramPerStick : null
  // 额外加工费（元/kg）：土PG核心粉料口径，叠加在含损耗成本之上
  const finalUnitCost = ctx.extraFeePerKg > 0 ? unitCostWithLoss + ctx.extraFeePerKg : null

  return {
    mode: ctx.mode,
    modeLabel: ctx.modeLabel,
    specId: ctx.specId || null,
    specLabel: ctx.specLabel || null,
    productName: ctx.productName || '',
    inputKg: r4(ctx.inputKg),
    outputKg: r4(outputKg),
    lossRate,
    packageGram: ctx.packageGram ?? null,
    gramPerStick: ctx.gramPerStick ?? null,
    sticks: ctx.sticks != null ? Math.round(ctx.sticks) : null,
    sticksNominal: ctx.sticksNominal != null ? Math.round(ctx.sticksNominal) : null,
    lossGramPerStick: ctx.lossGramPerStick ?? null,
    gramWithLoss: ctx.gramWithLoss ?? null,
    /** 车间成本明细（猫条模式：加工费即车间成本，两者同源，非并列两套） */
    workshop: ctx.workshop || null,
    lines,
    totalRatio: r4(totalRatio),
    totalThawed: r4(totalThawed),
    totalBefore: r4(totalBefore),
    totalAmount: r4(totalAmount),
    yieldAfter: r4(yieldAfter),
    yieldBefore: r4(yieldBefore),
    materialUnitCost: r4(materialUnitCost),
    materialTonCost: r4(materialTonCost),
    fees: fees.list,
    feeTotal: fees.total,
    semiTotal: r4(semiTotal),
    unitCost: r4(unitCost),
    unitCostWithLoss: r4(unitCostWithLoss),
    perStick: perStick != null ? r4(perStick) : null,
    extraFeePerKg: ctx.extraFeePerKg || 0,
    finalUnitCost: finalUnitCost != null ? r4(finalUnitCost) : null,
    feeBasisNote: ctx.feeBasisNote || '',
    warnings: fees.warnings || [],
    // 兼容既有展示层字段（通用口径）
    totalKg: r4(ctx.inputKg),
    batchCount: null,
    gramPerBag: ctx.packageGram ?? ctx.gramPerStick ?? null,
  }
}

const num = (v, d) => (v == null || v === '' || !Number.isFinite(Number(v)) ? d : Number(v))

/* ---------------- 供展示层使用的取整 ---------------- */
export const fmtCost = (n, d = 2) => (Number.isFinite(n) ? (Math.round(n * 10 ** d) / 10 ** d).toFixed(d) : '—')
export const fmtPercent = (n) => (Number.isFinite(n) ? (n * 100).toFixed(2) + '%' : '—')
export { r2, r4 }
