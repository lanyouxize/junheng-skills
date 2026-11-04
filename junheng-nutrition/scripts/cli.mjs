#!/usr/bin/env node
/**
 * junheng-nutrition —— 原料库与配方营养计算的命令行门面。
 *
 * 门面里不含任何营养学逻辑：全部来自 `src/lib/nutrition.js`（286 条种子库 + 加权求和引擎）。
 *
 * 调用形态（详见 `--help`）：
 *   node cli/nutrition.mjs ingredients '{"query":"鸡"}'
 *   node cli/nutrition.mjs recipe '{"items":[{"name":"鸡大胸","weight":100},{"name":"鸡脂油","weight":10}]}'
 *   node cli/nutrition.mjs requirements '{"species":"cat","weightKg":4}'
 *
 * 退出码：0 成功 / 1 内部错误 / 2 用法或输入错误 / 3 前置条件缺失。
 * ⚠ 用 process.exitCode 而非 process.exit：避免管道下截断 stdout。
 */
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { importFromVendor, isEntrypoint } from './lib/locate.mjs'
import { runCli } from './lib/runner.mjs'
import { emitError, makeIo } from './lib/output.mjs'
import { speciesEnum, doseBases, doseUnits } from './lib/paramSchema.mjs'

export const NAME = 'junheng-nutrition'
export const VERSION = '1.1.0'
export const SUMMARY = '宠物食品原料库查询与配方营养计算：按原料名称与配比算出营养素组成、能量、钙磷比与成本'
/**
 * 探测文件**只列 vendor 内的模块**，不要列 `ingredient_db.js` —— 它在两种布局下
 * 都不与模块同目录（项目里是 `src/data/`、技能里是 `scripts/data/`），
 * 而 `nutrition.js` 自己用 `../data/ingredient_db.js` 解析它。
 * 放进 PROBE 会让「所有探测文件必须同目录」的判定必然失败（第 1 期实测踩到）。
 */
export const PROBE = ['nutrition.js', 'species.js']
export const DISCLAIMER = '全部为按原料库数据加权计算的理论值，不是检测值。'
  + '原料库共 286 条，其常规成分来自数据库记录，可能与你的实际批次存在差异；'
  + '缺数据的原料会进入 zeroData / dataGaps，覆盖率不足时结果标 reliable 相关字段为假 —— '
  + '请先看覆盖率和缺口清单，再采信数值。价格口径为数据库 ¥/kg，未填价的原料按 0 计入并列入 missingPrice。'

const HERE = path.dirname(fileURLToPath(import.meta.url))

/**
 * 配方条目：{ name, weight } 或 { code, weight }。
 * ⚠ name 与 code **都不设 required** —— 「给编号」与「给名称」是二选一，
 *   若把 name 标为 required，按编号查的调用会被误拒（第 1 期实测踩到：
 *   `{code:'01020271', weight:300}` 被报「缺少 items[0].name」）。
 *   二选一的约束交由 check 钩子在数组层面校验（能给出更准确的整体提示）。
 */
const RECIPE_ITEM_FIELDS = {
  name: { type: 'string', desc: '原料名称（支持不带括号品牌名，如「鸡大胸」）；与 code 二选一' },
  code: { type: 'string', desc: '物料编号；与 name 二选一，给了它优先按编号查' },
  weight: { type: 'number', required: true, min: 0, max: 100000, desc: '用量（克）' },
}

/** 校验每个条目至少给了 name 或 code */
function checkItemsHaveIdentifier(items) {
  const bad = []
  items.forEach((it, i) => {
    const hasName = typeof it.name === 'string' && it.name.trim() !== ''
    const hasCode = typeof it.code === 'string' && it.code.trim() !== ''
    if (!hasName && !hasCode) bad.push(i)
  })
  if (bad.length) {
    return `配方条目缺少识别信息：第 ${bad.map((i) => i + 1).join('、')} 项既没给 name 也没给 code（每项至少要有一个）`
  }
  return null
}

/** 把用户给的 {name|code, weight} 解析成 computeRecipe 需要的 {ingredient, weight} */
function resolveItems(api, items) {
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
    resolved.push({ ingredient: ing, weight: it.weight })
  }
  return { resolved, unknown }
}

/**
 * 安全闸（**后置**校验）：营养算完之后，把配方送去过一遍安全库，把四态结论并进输出。
 *
 * ## 为什么是「后置」且**不阻断**
 * `recipe` 是**计算**命令，它的职责是把「这份配方含什么」算清楚 —— 而禁用物质往往
 * 正是算完之后才看得见的东西（可可粉、木糖醇在配方表里都只是一行原料名）。
 * 在这里拒绝返回，等于把「想看看到底含了什么」这个正当诉求也一并拒了。
 * **阻断**放在真正会产出**建议**的地方（feeding 的喂食计划、pipeline 的整链编排）——
 * 那里放过一份含禁用物质的配方，就是给出了一份不该给的方案。
 *
 * ## 送检名单 = 库内规范名 ∪ 用户原样写的名字
 * 两者都要送：只送规范名会漏掉「用户写的是别名/简写」这条最常见的命中路径；
 * 只送用户输入则漏掉「库里叫 A、用户写 B」的情形。取并集后由内核统一去重判定。
 *
 * 未加载安全模块时返回 null 并**显式**告知（不静默当作已筛查）。
 */
function safetyOf(api, items, resolved, species) {
  if (typeof api.classifyRecipe !== 'function') {
    return { skipped: true, reason: '安全模块未加载（api.classifyRecipe 不可用）—— 本次未做安全筛查' }
  }
  const names = [...new Set([
    ...resolved.map((r) => r.ingredient.name),
    ...items.map((it) => (typeof it.name === 'string' ? it.name.trim() : '')).filter(Boolean),
  ])]
  if (!names.length) return null
  const r = api.classifyRecipe(names.map((name) => ({ name })), { species })
  const ranked = r.rows.filter((x) => x.level === 'banned' || x.level === 'caution')
  return {
    species: r.species,
    checked: names,
    summary: r.summary,
    hits: ranked.map((x) => ({
      name: x.name, level: x.level, substance: x.substance, conditions: x.conditions, sources: x.sources,
    })),
    notice: r.summary.blocked
      ? '配方命中【禁用】物质 —— 该配方不应给出。营养数值仍照算，用于定位问题所在。'
      : (r.summary.caution
        ? '配方含【慎用】物质，须先满足各自列明的适用条件（见 hits[].conditions）。'
        : (r.summary.unjudged
          ? `有 ${r.summary.unjudged} 项未被安全库收录 ⇒ 安全性【无法判定】（unknown 不等于安全），请人工确认。`
          : '安全库未命中禁用/慎用物质（注意：未被收录的原料不计入本结论）。')),
  }
}

/** 由已加载的源码模块构造命令表。导出以便测试检视注册表。 */
export function buildCommands(api) {
  // 参数面枚举取自单一真源（见 lib/paramSchema.mjs），门面内不再写枚举字面量。
  const SPECIES = speciesEnum(api)
  return {
    ingredients: {
      summary: '按关键词查原料（返回常规成分与价格，带数据状态标记）',
      params: {
        query: { type: 'string', desc: '关键词（名称或编号片段）。省略则返回前 N 条' },
        limit: { type: 'number', min: 1, max: 286, default: 20, desc: '最多返回条数' },
      },
      run: (a) => {
        const rows = a.query ? api.searchIngredients(a.query, a.limit) : api.INGREDIENT_DB.slice(0, a.limit)
        return {
          total: api.dbCount(),
          matched: rows.length,
          items: rows.map((r) => ({
            code: r.code || null,
            name: r.name,
            category: r.category || null,
            lifeStage: r.lifeStage || null,
            crude_protein: r.crude_protein ?? null,
            crude_fat: r.crude_fat ?? null,
            crude_fiber: r.crude_fiber ?? null,
            crude_ash: r.crude_ash ?? null,
            moisture: r.moisture ?? null,
            calcium: r.calcium ?? null,
            phosphorus: r.phosphorus ?? null,
            price: r.price ?? null,
            dataStatus: r._dataStatus || null,
          })),
        }
      },
    },

    recipe: {
      summary: '按配方（原料 + 用量）算营养素组成、能量、钙磷比与成本',
      params: {
        items: {
          type: 'array',
          required: true,
          minItems: 1,
          maxItems: 200,
          desc: '配方条目；每项 { name 或 code, weight(克) }',
          fields: RECIPE_ITEM_FIELDS,
        },
        species: { type: 'string', enum: SPECIES, default: api.DEFAULT_SPECIES, desc: '物种（决定能量口径的消化率与尿能系数）' },
        moisturePercent: {
          type: 'number',
          // ★ 硬下限 1%（唯一真源：src/data/moistureProfiles.js 的 MIN_FINISHED_MOISTURE）。
          //   成品不可能零水分；<1 会被引擎判 below_min_moisture、不施加并回退原料加权。
          //   此处把 min 对齐为 1，让 CLI 在**入参校验阶段**就大声报错，而不是静默回退。
          min: 1,
          max: 99.9,
          desc: '成品水分 %（可选，**硬下限 1%**）。给定时按**干物质守恒**把原料加权结果折算到成品水分：'
            + '湿基各项 × k、水分 = 目标值、干基组成不变。省略 = 沿用原料加权水分（既有行为）。'
            + '<1 视为无效（成品不可能零水分）⇒ 引擎不施加并回退原料加权，结果里标 reason=below_min_moisture',
        },
        airDryMoisturePercent: {
          type: 'number',
          min: 0,
          max: 99.9,
          desc: '风干参照水分 %（可选，省略时用引擎默认 3%）。用于结果里的 airDry（风干基础）：'
            + 'a = 干基 × (100 − w_ad) ÷ 100，把干基值归一到统一口径以便跨产品比较。'
            + '⚠ 与 moisturePercent 互不相干（前者是「按什么口径比」的参照，后者是「成品实际含水」）；'
            + '⚠ 越出 [0,100) 时 airDry.available=false、不出数（不兜底）',
        },
        priceOverrides: { type: 'object', desc: '价格覆盖表（键为物料编号或名称，值为 ¥/kg）' },
      },
      check: (a) => {
        if (!a.items || !a.items.length) return 'items 至少要给一项原料（否则没有可计算的配方）'
        return checkItemsHaveIdentifier(a.items)
      },
      run: (a) => {
        const { resolved, unknown } = resolveItems(api, a.items)
        if (!resolved.length) {
          return {
            ok: false,
            reason: 'no_ingredient_matched',
            unknown,
            note: '所有原料都没在库里找到 —— 请用 ingredients 命令按关键词查正确名称或编号。',
          }
        }
        const r = api.computeRecipe(resolved, a.priceOverrides || {}, {
          species: a.species,
          // 显式区分「未给」与「给了 0」：undefined 才算未给。
          // ⚠ 0% 自 2026-10-16 起**不再是合法成品水分**（硬下限 1%），但参数面仍保留
          //   「undefined = 未给」的语义 —— 给 0 会走到引擎的 below_min_moisture 分支
          //   并回退原料加权（CLI 的 min:1 会在入参校验阶段先拦一道）。
          ...(a.moisturePercent == null ? {} : { moisturePercent: a.moisturePercent }),
          // 风干参照水分：与 moisturePercent 独立，省略即用引擎默认值
          ...(a.airDryMoisturePercent == null ? {} : { airDryMoisturePercent: a.airDryMoisturePercent }),
        })
        // 零总重必须在 CLI 层拦下：computeRecipe 对空配方仍返回对象（ok:true / lines:[] / 无 totalWeight），
        // 只看 !r 会让「总重 0」被当成合法结果输出，违反 SKILL.md 诚实性红线 4（应返回 ok:false）。
        if (!r || !(r.totalWeight > 0)) {
          return { ok: false, reason: 'zero_total_weight', note: '配方总重量为 0，无法计算。' }
        }
        // 后置安全校验：并进结果，不改变营养数值本身
        const safety = safetyOf(api, a.items, resolved, a.species || api.DEFAULT_SPECIES)
        return { ...r, unknown, species: a.species, safety }
      },
    },

    'analyze-label': {
      summary: '按标签上的原样基础营养值算干物质基/能量/钙磷比（不做 OCR）',
      params: {
        asFed: {
          type: 'object',
          required: true,
          desc: '原样基础营养值 %',
          fields: {
            crude_protein: { type: 'number', min: 0, max: 100, desc: '粗蛋白 %' },
            crude_fat: { type: 'number', min: 0, max: 100, desc: '粗脂肪 %' },
            crude_fiber: { type: 'number', min: 0, max: 100, desc: '粗纤维 %' },
            crude_ash: { type: 'number', min: 0, max: 100, desc: '粗灰分 %' },
            moisture: { type: 'number', min: 0, max: 100, desc: '水分 %' },
            calcium: { type: 'number', min: 0, max: 100, desc: '钙 %' },
            phosphorus: { type: 'number', min: 0, max: 100, desc: '磷 %' },
            chloride: { type: 'number', min: 0, max: 100, desc: '水溶性氯化物 %' },
          },
        },
        species: { type: 'string', enum: SPECIES, default: api.DEFAULT_SPECIES, desc: '物种' },
      },
      run: (a) => api.analyzeLabel(a.asFed, { species: a.species }),
    },

    requirements: {
      summary: '算个体营养需求（RER / MER + 生命阶段系数）',
      params: {
        species: { type: 'string', enum: SPECIES, default: api.DEFAULT_SPECIES, desc: '物种' },
        weightKg: { type: 'number', required: true, min: 0.2, max: 200, desc: '体重 kg' },
        ageMonths: { type: 'number', min: 0, max: 400, desc: '月龄（缺省时用 ageText 解析）' },
        ageText: { type: 'string', desc: '年龄文本，如「2 岁」「8 个月」' },
        status: { type: 'string', desc: '生理状态（不填则由年龄推断）' },
        activity: { type: 'string', desc: '活动量档位' },
        breed: { type: 'string', desc: '品种' },
      },
      run: (a) => api.computeRequirements(a),
    },

    'dose2formula': {
      summary: '把「每天该摄入多少」换算成「配方添加比例%」—— 补上需求侧与配方侧之间缺失的一跳',
      params: {
        dose: { type: 'number', required: true, min: 0, desc: '剂量数值（单位见 unit；表示「每基准单位含多少」）' },
        basis: {
          type: 'string',
          enum: doseBases(api),
          default: 'per_day_flat',
          desc: '剂量基准：per_day_flat 每天定量 / per_kg_bw 每kg体重 / per_1000kcal 每1000kcal ME / '
            + 'per_kg_dm 每kg干物质（FEDIAF、AAFCO 限值主用基准）',
        },
        unit: { type: 'string', enum: doseUnits(api), default: 'mg', desc: '质量单位（不含 IU：生物学单位无质量当量，应先自行折算）' },
        species: { type: 'string', enum: SPECIES, default: api.DEFAULT_SPECIES, desc: '物种（weightKg 推导 MER 时用）' },
        weightKg: { type: 'number', min: 0.2, max: 200, desc: '体重 kg；给定则由 computeRequirements 推导 mer（basis=per_kg_bw 时必需）' },
        merKcal: { type: 'number', min: 0, desc: '直接给 MER kcal/天（优先于 weightKg 推导）' },
        meKcalPerKg: { type: 'number', min: 0, desc: '日粮代谢能 kcal/kg（原样基础）；与 mer 联立可推导每日饲喂量' },
        gramsPerDay: { type: 'number', min: 0, desc: '每日饲喂量 g（原样基础）；给了就不再推导，优先级最高' },
        dmPercent: { type: 'number', min: 1, max: 100, desc: '成品干物质 %（basis=per_kg_dm 时必需）' },
        purity: { type: 'number', min: 0, max: 1, desc: '原料中有效物分数，如 50% 纯度填 0.5（默认 1）' },
        retention: { type: 'number', min: 0, max: 1, desc: '加工存留率，热敏物必填（默认 1）' },
        inclusionPct: { type: 'number', min: 0, desc: '可选：给定添加比例 %，反算实际送达量与达成度' },
        ageMonths: { type: 'number', min: 0, max: 400, desc: '月龄（仅在由 weightKg 推导 MER 时参与）' },
        status: { type: 'string', desc: '生理状态（不填则由年龄推断）' },
        activity: { type: 'string', desc: '活动量档位' },
      },
      check: (a) => {
        if (a.purity != null && !(a.purity > 0 && a.purity <= 1)) return 'purity 必须落在 (0,1]（0 会让需要量除成无穷大）'
        if (a.retention != null && !(a.retention > 0 && a.retention <= 1)) return 'retention 必须落在 (0,1]'
        const hasGpd = a.gramsPerDay > 0
        const canMer = a.merKcal > 0 || a.weightKg > 0
        if (!hasGpd && !(canMer && a.meKcalPerKg > 0)) {
          return '缺每日饲喂量：直接给 gramsPerDay，或给 meKcalPerKg 并配合 merKcal / weightKg 由系统推导'
        }
        if (a.basis === 'per_1000kcal' && !canMer) return 'basis=per_1000kcal 需要 MER：给 merKcal 或 weightKg'
        if (a.basis === 'per_kg_bw' && !(a.weightKg > 0)) return 'basis=per_kg_bw 需要 weightKg'
        if (a.basis === 'per_kg_dm' && !(a.dmPercent > 0)) return 'basis=per_kg_dm 需要 dmPercent（成品干物质 %）'
        return null
      },
      run: (a) => {
        const sp = a.species || api.DEFAULT_SPECIES
        // 每个推导出来的中间量都登记来源，让调用方知道哪个数是"算的"、哪个是"给的"
        const assumptions = {}

        let mer = a.merKcal
        if (mer == null && a.weightKg != null) {
          const req = api.computeRequirements({
            species: sp,
            weightKg: a.weightKg,
            ...(a.ageMonths == null ? {} : { ageMonths: a.ageMonths }),
            ...(a.status == null ? {} : { status: a.status }),
            ...(a.activity == null ? {} : { activity: a.activity }),
          })
          mer = req.mer
          assumptions.merFrom = 'computeRequirements（RER×生命阶段/活动系数）'
        } else if (mer != null) {
          assumptions.merFrom = 'input'
        }

        let gpd = a.gramsPerDay
        if (gpd == null && mer != null && a.meKcalPerKg != null) {
          gpd = (mer / a.meKcalPerKg) * 1000
          assumptions.gramsPerDayFrom = 'mer ÷ meKcalPerKg × 1000（同 dailyFeeding 口径）'
        } else if (gpd != null) {
          assumptions.gramsPerDayFrom = 'input'
        }

        const r = api.doseToFormula({
          basis: a.basis,
          dose: a.dose,
          unit: a.unit,
          mer,
          gramsPerDay: gpd,
          dmPercent: a.dmPercent,
          weightKg: a.weightKg,
          purity: a.purity == null ? 1 : a.purity,
          retention: a.retention == null ? 1 : a.retention,
          inclusionPct: a.inclusionPct,
        })
        return {
          ...r,
          species: sp,
          merKcal: mer == null ? null : mer,
          assumptions,
          note: '限值请以现行 FEDIAF / AAFCO 原文为准；本命令只做换算，不内置标准限值库。',
        }
      },
    },

    evaluate: {
      summary: '把配方结果与个体需求逐项对照（不替用户下「是否达标」的结论）',
      params: {
        recipe: { type: 'object', required: true, open: true, desc: 'computeRecipe 的返回对象（先跑 recipe 命令取 data）' },
        req: { type: 'object', required: true, open: true, desc: 'computeRequirements 的返回对象' },
      },
      run: (a) => api.evaluateRecipe(a.recipe, a.req),
    },

    'parse-recipe-text': {
      summary: '把自由文本配方（如「鸡大胸 100g，鸡脂油 10g」）解析成结构化条目',
      params: {
        text: { type: 'string', required: true, desc: '配方文本' },
      },
      run: (a) => ({ items: api.parseRecipeText(a.text) }),
    },
  }
}

/** 门面主流程。返回退出码（不退出进程，便于测试在进程内断言）。 */
export async function main(argv = process.argv.slice(2), io) {
  const out = io || makeIo()
  let api
  try {
    api = await importFromVendor(HERE, PROBE, 'nutrition.js')
    // species.js 是全站物种缺省值的唯一真源；门面默认值必须取自它，不能写字面量（否则会与源码漂移）
    const sp = await importFromVendor(HERE, 'species.js', 'species.js')
    // 安全闸（N1 接线 · E1）：配方算完后过一遍安全库。只并入 classifyRecipe ——
    // 不整包展开 toxicology 的导出（TOXIC_* / lookup 等泛名会污染 api 命名空间）。
    const tox = await importFromVendor(HERE, 'nutrition.js', 'toxicology.js')
    api = { ...api, DEFAULT_SPECIES: sp.DEFAULT_SPECIES, SPECIES_IDS: sp.SPECIES_IDS, classifyRecipe: tox.classifyRecipe }
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
