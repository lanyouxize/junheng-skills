#!/usr/bin/env node
/**
 * junheng-cost —— 配方成本核算的命令行门面（通用 / 冻干 / 猫条）。
 *
 * 门面里不含任何成本公式：全部来自 `src/lib/costModes.js`
 * （其基础单表计算来自 `nutrition.js` 的 `computeCostSheet`）。
 *
 * ## ⚠ 入参形状说明（与 nutrition 门面不同，别想当然）
 * `costModes.js` **不直接吃 computeRecipe 的返回**。它要的是「成本行」：
 *   lines: [{ code, name, unit:'kg', ratio(占比 0~1), unitPrice(¥/kg), yieldRate }]
 * 加上各口径自己的参数（batchCount/gramPerBag、inputKg/outputKg、specId 等）。
 * 本门面的 `lines` 命令负责把配方条目换算成这种成本行，避免调用方各写一遍
 * （界面侧是 `FormulaPage.jsx` 的 costLines 逻辑，口径与此一致：
 *  unitPrice 取「覆盖价 > 库价 > 0」，ratio = 单项重量 / 总重）。
 *
 * ⚠ 价格口径：用户覆盖价 > 数据库价 > 未填（按 0 计入并列入 missingPrice）。
 *   本门面只做成本算术，**不含任何报价/税务/议价含义**。
 *
 * 调用形态（详见 `--help`）：
 *   node cli/cost.mjs lines '{"items":[{"name":"鸡大胸","weight":100}]}'
 *   node cli/cost.mjs sheet '{"productName":"X","batchCount":100,"gramPerBag":50,"lines":[...]}'
 *
 * 退出码：0 成功 / 1 内部错误 / 2 用法或输入错误 / 3 前置条件缺失。
 */
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { importFromVendor, isEntrypoint } from './lib/locate.mjs'
import { runCli } from './lib/runner.mjs'
import { emitError, makeIo } from './lib/output.mjs'

export const NAME = 'junheng-cost'
export const VERSION = '1.0.0'
export const SUMMARY = '配方成本核算：成本行换算、通用成本表、冻干、猫条三种口径（含费用与损耗）'
/**
 * 需要两个模块：`costModes.js`（成本公式）+ `nutrition.js`（原料查找，用于把配方
 * 换算成成本行）。`costModes.js` **不转出** `findIngredient*`（实测导出清单里没有），
 * 所以不能只加载它 —— 这是第 1 期实测踩到的第二处「以为能直接用」。
 */
export const PROBE = ['costModes.js', 'nutrition.js']
export const DISCLAIMER = '全部为按原料库价格与给定费用参数算出的理论成本，不是报价、不含税与议价因素。'
  + '价格口径为 ¥/kg：用户覆盖价 > 数据库价 > 未填（按 0 计入并列入 missingPrice）。'
  + '未填价原料会让总成本偏低，请务必先看 missingPrice 再采信数值。'
  + '损耗与收得率来自代码内的经验配置（FREEZE_DRY_CONFIG / WORKSHOP_LOSS_CONFIG），实际产线可能有差异。'
  + 'costModes 不直接吃配方结果，需先用 lines 命令把配方换算成成本行。'

const HERE = path.dirname(fileURLToPath(import.meta.url))

/** 成本行字段（与 FormulaPage.jsx 的 costLines 口径一致） */
const LINE_FIELDS = {
  code: { type: 'string', desc: '物料编号（可空）' },
  name: { type: 'string', desc: '原料名称' },
  unit: { type: 'string', default: 'kg', desc: '单位（固定 kg）' },
  ratio: { type: 'number', required: true, min: 0, max: 1, desc: '占比 0~1（= 单项重量 / 总重）' },
  unitPrice: { type: 'number', required: true, min: 0, desc: '单价 ¥/kg' },
  yieldRate: { type: 'number', min: 0, desc: '收得率（缺省 1）' },
  note: { type: 'string', desc: '备注' },
}

/**
 * 把 {name|code, weight} 配方换算成成本行（口径同 FormulaPage 的 costLines）。
 *
 * ⚠ **只接受正用量**：weight ≤ 0（或非数）的条目直接跳过，与
 *   `costModes.buildLines` / `computeRecipe` 的 `weight > 0` 保持同一口径。
 *   两类残留都由这里拦住：
 *     · weight = 0 → 会以「金额 0」留在成本表并被 Excel 导出带走，让使用者
 *       以为配方里真有这么一味；
 *     · weight < 0 → 占比与金额为负，**静默把总成本拉低**（更危险）。
 *   剔除保持**静默**：不新增字段、不打印日志（与 S-1 的处置一致）。
 */
function buildLinesFromItems(api, items, priceOverrides = {}, yields = {}) {
  const resolved = []
  const unknown = []
  for (const it of items) {
    let ing = null
    if (it.code) ing = api.findIngredientByCode(it.code)
    if (!ing && it.name) ing = api.findIngredient(it.name)
    if (!ing) {
      unknown.push(it.code ? `code=${it.code}` : it.name)
      continue
    }
    const w = Number(it.weight)
    if (!Number.isFinite(w) || w <= 0) continue
    resolved.push({ ing, weight: w })
  }
  const totalW = resolved.reduce((s, x) => s + x.weight, 0)
  if (!totalW) return { lines: [], unknown, zero: true }

  const missingPrice = []
  const lines = resolved.map(({ ing, weight }) => {
    const ovr = priceOverrides[ing.code] ?? priceOverrides[ing.name]
    let unitPrice = 0
    if (Number.isFinite(Number(ovr)) && Number(ovr) >= 0) unitPrice = Number(ovr)
    else if (ing.price > 0) unitPrice = ing.price
    else missingPrice.push(ing.name)
    const yr = Number(yields[ing.code] ?? yields[ing.name])
    return {
      code: ing.code || '',
      name: ing.name,
      unit: 'kg',
      ratio: weight / totalW,
      unitPrice,
      yieldRate: Number.isFinite(yr) && yr > 0 ? yr : 1,
    }
  })
  return { lines, unknown, zero: false, totalWeight: totalW, missingPrice: [...new Set(missingPrice)] }
}

/** 由已加载的源码模块构造命令表。导出以便测试检视注册表。 */
export function buildCommands(api) {
  return {
    modes: {
      summary: '列出可用成本口径（id 用下划线，如 freeze_dry）与默认口径',
      params: {},
      run: () => ({
        modes: api.COST_MODES,
        default: api.DEFAULT_COST_MODE,
        freezeDryConfig: api.FREEZE_DRY_CONFIG,
        workshopLossConfig: api.WORKSHOP_LOSS_CONFIG,
        catStickSpecs: api.CAT_STICK_SPECS,
        defaultCatStickSpec: api.DEFAULT_CAT_STICK_SPEC,
        note: 'mode 取值：' + api.COST_MODES.map((m) => m.id).join(' | '),
      }),
    },

    lines: {
      summary: '把配方（原料 + 重量）换算成成本行（供 sheet / by-mode 使用）',
      params: {
        items: {
          type: 'array',
          required: true,
          minItems: 1,
          desc: '配方条目 { name 或 code, weight(克) }',
          fields: {
            name: { type: 'string', desc: '原料名称（与 code 二选一）' },
            code: { type: 'string', desc: '物料编号（与 name 二选一）' },
            weight: { type: 'number', required: true, min: 0, desc: '用量（克）。用量 ≤ 0 的条目会被剔除，不出现在成本行里（静默，与配方主计算同口径）' },
          },
        },
        priceOverrides: { type: 'object', open: true, desc: '价格覆盖表（键为编号或名称，值 ¥/kg）' },
        yields: { type: 'object', open: true, desc: '收得率表（键为编号或名称，值 0~1）' },
      },
      run: (a) => {
        const r = buildLinesFromItems(api, a.items, a.priceOverrides || {}, a.yields || {})
        if (r.zero) return { ok: false, reason: 'zero_total_weight', unknown: r.unknown, note: '总重量为 0，无法换算占比。' }
        return { ok: true, lines: r.lines, totalWeight: r.totalWeight, unknown: r.unknown, missingPrice: r.missingPrice }
      },
    },

    sheet: {
      summary: '通用成本表（需 batchCount + gramPerBag 或 yieldKg 才能出数）',
      params: {
        productName: { type: 'string', desc: '产品名' },
        lines: { type: 'array', required: true, minItems: 1, desc: '成本行（用 lines 命令生成）', fields: LINE_FIELDS },
        batchCount: { type: 'number', min: 0, desc: '袋数' },
        gramPerBag: { type: 'number', min: 0, desc: '每袋克重' },
        yieldKg: { type: 'number', min: 0, desc: '产量 kg（优先于 袋数×克重）' },
        lossRate: { type: 'number', min: 0, max: 1, desc: '损耗率' },
        processingFeePerTon: { type: 'number', min: 0, desc: '加工费 元/吨' },
      },
      check: (a) => {
        const totalKg = Number(a.yieldKg) > 0 ? Number(a.yieldKg) : (Number(a.batchCount) || 0) * (Number(a.gramPerBag) || 0) / 1000
        return totalKg > 0 ? null : '通用口径需要产量：给 yieldKg，或给 batchCount + gramPerBag（否则成本表算不出数）'
      },
      run: (a) => {
        const sheet = api.computeCostSheetByMode({ ...a, mode: 'general' })
        return sheet || { ok: false, reason: 'no_result', note: '参数不全，算不出通用成本表。' }
      },
    },

    'by-mode': {
      summary: '按指定口径算成本（general / freeze_dry / cat_stick）',
      params: {
        mode: { type: 'string', required: true, enum: api.COST_MODES.map((m) => m.id), desc: '成本口径' },
        productName: { type: 'string', desc: '产品名' },
        lines: { type: 'array', required: true, minItems: 1, desc: '成本行（用 lines 命令生成）', fields: LINE_FIELDS },
        batchCount: { type: 'number', min: 0, desc: '通用口径：袋数' },
        gramPerBag: { type: 'number', min: 0, desc: '通用口径：每袋克重' },
        yieldKg: { type: 'number', min: 0, desc: '通用口径：产量 kg' },
        inputKg: { type: 'number', min: 0, desc: '冻干/猫条：投料 kg' },
        outputKg: { type: 'number', min: 0, desc: '冻干/猫条：成品产量 kg' },
        lossRate: { type: 'number', min: 0, max: 1, desc: '损耗率' },
        processingFeePerTon: { type: 'number', min: 0, desc: '通用口径：加工费 元/吨' },
        specId: { type: 'string', desc: '猫条：规格 id（见 modes 的 catStickSpecs）' },
        extraFeePerKg: { type: 'number', min: 0, desc: '猫条：额外费用 元/kg' },
        packageGram: { type: 'number', min: 0, desc: '冻干：包装克重' },
        feesPerTon: { type: 'object', open: true, desc: '冻干：五项加工费覆盖' },
        lossGramPerStick: { type: 'number', min: 0, desc: '猫条：每支损耗克数' },
        ratesPerStick: { type: 'object', open: true, desc: '猫条：车间单价覆盖（元/支）' },
      },
      run: (a) => {
        const sheet = api.computeCostSheetByMode(a)
        return sheet || { ok: false, reason: 'no_result', note: '该口径在给定参数下算不出结果（检查产量/投料/规格是否齐全）。' }
      },
    },

    'freeze-dry': {
      summary: '冻干成本（投料 → 冻干成品，五项加工费 元/吨）',
      params: {
        productName: { type: 'string', desc: '产品名' },
        lines: { type: 'array', required: true, minItems: 1, desc: '成本行（用 lines 命令生成）', fields: LINE_FIELDS },
        inputKg: { type: 'number', min: 0, desc: '投料 kg（缺省取配置默认）' },
        outputKg: { type: 'number', min: 0, desc: '成品产量 kg（缺省取配置默认）' },
        lossRate: { type: 'number', min: 0, max: 1, desc: '损耗率' },
        packageGram: { type: 'number', min: 0, desc: '包装克重' },
        feesPerTon: { type: 'object', open: true, desc: '五项加工费覆盖（键见 modes 的 freezeDryConfig.feesPerTon）' },
      },
      run: (a) => {
        const sheet = api.computeFreezeDrySheet(a)
        return sheet || { ok: false, reason: 'no_result', note: '投料为空或参数不全，算不出冻干成本。' }
      },
    },

    'cat-stick': {
      summary: '猫条成本（按规格，含车间加工单价与损耗）',
      params: {
        productName: { type: 'string', desc: '产品名' },
        lines: { type: 'array', required: true, minItems: 1, desc: '成本行（用 lines 命令生成）', fields: LINE_FIELDS },
        specId: { type: 'string', desc: '规格 id（见 modes 的 catStickSpecs）' },
        inputKg: { type: 'number', min: 0, desc: '投料 kg（缺省取规格默认）' },
        outputKg: { type: 'number', min: 0, desc: '成品 kg' },
        lossRate: { type: 'number', min: 0, max: 1, desc: '损耗率' },
        extraFeePerKg: { type: 'number', min: 0, desc: '额外费用 元/kg' },
        lossGramPerStick: { type: 'number', min: 0, desc: '每支损耗克数' },
        ratesPerStick: { type: 'object', open: true, desc: '车间单价覆盖（元/支）' },
      },
      run: (a) => {
        const sheet = api.computeCatStickSheet(a)
        return sheet || { ok: false, reason: 'no_result', note: '参数不全，算不出猫条成本。' }
      },
    },

    format: {
      summary: '成本数值的展示格式工具（与界面口径一致）',
      params: {
        value: { type: 'number', required: true, desc: '待格式化的数值' },
        digits: { type: 'number', min: 0, max: 6, default: 2, desc: '小数位' },
      },
      run: (a) => ({ cost: api.fmtCost(a.value, a.digits), percent: api.fmtPercent(a.value) }),
    },
  }
}

/** 门面主流程。返回退出码（不退出进程，便于测试在进程内断言）。 */
export async function main(argv = process.argv.slice(2), io) {
  const out = io || makeIo()
  let api
  try {
    // 合并两个模块：成本公式来自 costModes.js，原料查找来自 nutrition.js
    const costs = await importFromVendor(HERE, 'costModes.js', 'costModes.js')
    const nut = await importFromVendor(HERE, 'nutrition.js', 'nutrition.js')
    api = { ...costs, findIngredient: nut.findIngredient, findIngredientByCode: nut.findIngredientByCode, searchIngredients: nut.searchIngredients }
  } catch (e) {
    return emitError(out, { name: NAME, kind: 'precondition', message: `无法加载源码模块：${(e && e.message) || e}` })
  }
  return runCli({
    name: NAME,
    version: VERSION,
    summary: SUMMARY,
    disclaimer: DISCLAIMER,
    commands: buildCommands(api),
    argv,
    io: out,
  })
}

if (isEntrypoint(import.meta.url)) {
  process.exitCode = await main(process.argv.slice(2))
}
