/**
 * 多宠 / 多日组合层：多宠聚合 + 合并采购清单（批 8 · 节点 4 · N3-a）。
 *
 * ## 定位
 * **纯组合层** —— 不引入任何新公式。每只宠物的喂食量一律来自
 * `feedingGuide.computeFeedingPlan()`，原料构成一律来自 `recipe.lines`
 * （`computeRecipe()` 的输出）。因此本模块输出的任何数字都能在单宠路径里复现。
 *
 * ## 为什么需要它
 * `computeFeedingPlan()` 是**单宠单日**的：它回答「这只猫今天吃多少克」，
 * 但不回答「一家两只猫 + 一只狗，这个月要买多少鸡胸肉」。多宠家庭的实际动作是
 * **一次采购、按份分装**，而采购对象是**原料**（按物料编号），不是「成品粮」。
 * 本模块补的正是这一段：逐宠算量 → 按物料编号归并 → 出货清单。
 *
 * ## 三条不静默红线
 * 1. **算不出的宠物不进总量**。`ok:false` 的宠物（缺体重 / 缺能量）若按 0 参与合计，
 *    会得到一个「看着完整」的假总量 —— 而用户会照着这个数去买料。
 *    故 `totals` / `purchase` 只累加 `ok:true` 的宠物，`failedCount` 单独报出。
 * 2. **未匹配原料必须显式报出**。`computeRecipe()` 的 `lines` 只含**命中原料库**的条目，
 *    库外原料在 `parseRecipeText()` 里就是 `ingredient:null`、进不了 lines。若只按 lines
 *    聚合，采购清单会**静默少买**。故接受调用方传入 `unmatched`，原样进 `purchase.unmatched`。
 * 3. **单价冲突不静默取值**。同一物料编号在不同宠物的配方里单价不同时，取任何一边
 *    都是在替用户拍板；本模块标 `priceConflict` 并列出全部取值与金额区间。
 *
 * ## 与 feedingGuide.js 的关系
 * 同域内聚 import（与 `feedingDoc.js` → `feedingGuide.js` 同例）。舍入口径
 * （r0/r1/r2）逐字沿用 feedingGuide.js，避免两处输出在末位打架。
 */
import { computeFeedingPlan } from './feedingGuide.js'

/* ================= 1. 常量 ================= */

/** 采购口径默认天数（30 天 ≈ 一个月；喂食计划的克/日本就是日均值，直接乘天数即可） */
export const PURCHASE_DAYS_DEFAULT = 30
/** 采购口径天数上限（超过一年没有实际意义，只会放大估算误差） */
export const PURCHASE_DAYS_MAX = 365
/** 单次聚合的宠物数上限。多宠家庭极少超过这个数；超限直接报错而**不静默截断** —— 截断会把「少算了几只」变成看不见的事实 */
export const MAX_PETS = 20

/* ================= 2. 小工具（与 feedingGuide.js 同口径） ================= */

const r0 = (n) => Math.round(n)
const r1 = (n) => Math.round(n * 10) / 10
const r2 = (n) => Math.round(n * 100) / 100
const num = (v) => (Number.isFinite(Number(v)) ? Number(v) : 0)
const str = (v) => (typeof v === 'string' ? v.trim() : '')

/** 单价：只有正数才算「有价」；0 / 负数 / 非数字一律视为未填（缺价必须区别于「价格是 0」） */
function priceOf(line) {
  const p = Number(line && line.price)
  return Number.isFinite(p) && p > 0 ? r2(p) : null
}

function clampDays(v) {
  const d = Number(v)
  if (!Number.isFinite(d) || d <= 0) return PURCHASE_DAYS_DEFAULT
  return Math.min(Math.round(d), PURCHASE_DAYS_MAX)
}

/* ================= 3. 单宠每日原料用量 ================= */

/**
 * 单宠每日原料用量：`配方内占比 share% × 每日喂食量`。
 *
 * ⚠ 口径说明：`share` 是**配方内**占比（`computeRecipe` 已做同名合并与归一），
 * 故 Σ(每条 grams) === gramsPerDay，仅存末位舍入差（守卫按 ≤ 0.01×条数 断言）。
 *
 * ⚠ `gramsPerDay` 缺失（宠物未算出喂食量）时**不给 0 而给 null** ——
 * 「没算出来」与「需要 0 克」是两回事，采购清单据此决定是否计入。
 */
export function ingredientDailyUse(lines, gramsPerDay) {
  const list = Array.isArray(lines) ? lines : []
  const g = num(gramsPerDay)
  return list.map((l) => ({
    code: str(l && l.code),
    name: str(l && l.name),
    share: r2(num(l && l.share)),
    grams: g > 0 ? r2((num(l && l.share) / 100) * g) : null,
    pricePerKg: priceOf(l),
  }))
}

/** 归一化「未匹配原料」入参：`[{ rawName|name, weight }]` → 稳定形状 */
function normUnmatched(raw) {
  const list = Array.isArray(raw) ? raw : []
  return list
    .map((u) => ({
      rawName: str(u && (u.rawName || u.name)),
      weight: num(u && u.weight),
    }))
    .filter((u) => u.rawName && u.weight > 0)
}

/* ================= 4. 合并采购清单（按物料编号归并） ================= */

/**
 * 把「多宠每日原料用量」归并成一张采购清单。
 *
 * 归并键 = **物料编号 code**（唯一 ID）。无 code 时退回按名称归并，但标 `codeMissing`
 * 并把该风险写进 note —— 按名字归并可能把名称相同、实际不同的原料合并。
 *
 * @returns {{ days:number, items:Array, unmatched:Array, note:string[] }}
 */
export function purchaseFromPets(pets, days = PURCHASE_DAYS_DEFAULT) {
  const d = clampDays(days)
  const map = new Map()
  const umMap = new Map()

  for (const pet of Array.isArray(pets) ? pets : []) {
    if (!pet || !pet.ok) continue // 红线 1：算不出的宠物不进采购
    for (const ing of pet.ingredients || []) {
      if (ing.grams == null || ing.grams <= 0) continue
      const key = ing.code ? `code:${ing.code}` : `name:${ing.name}`
      let it = map.get(key)
      if (!it) {
        it = {
          code: ing.code,
          name: ing.name,
          codeMissing: !ing.code,
          gramsPerDay: 0,
          pets: [],
          prices: new Set(),
        }
        map.set(key, it)
      }
      it.gramsPerDay += ing.grams
      it.pets.push(pet.label)
      if (ing.pricePerKg != null) it.prices.add(ing.pricePerKg)
    }

    /* 未匹配原料：无 code、无 share 可直接用，只能按**输入占比反推**估算。
       ⚠ 必须明标 estimated —— 这项份额没有经过营养验算，与已匹配项不是同一可信度。 */
    const recTotal = num(pet.recipeTotalWeight)
    const umList = pet.unmatched || []
    const umTotal = umList.reduce((s, u) => s + num(u.weight), 0)
    const denom = recTotal + umTotal
    for (const u of umList) {
      let it = umMap.get(u.rawName)
      if (!it) {
        it = { rawName: u.rawName, inputWeight: 0, pets: [], estimatedGramsPerDay: 0, estimated: true }
        umMap.set(u.rawName, it)
      }
      it.inputWeight = r2(it.inputWeight + u.weight)
      it.pets.push(pet.label)
      if (denom > 0) it.estimatedGramsPerDay = r2(it.estimatedGramsPerDay + (u.weight / denom) * num(pet.gramsPerDay))
    }
  }

  const items = [...map.values()].map((it) => {
    const prices = [...it.prices].sort((a, b) => a - b)
    const conflict = prices.length > 1
    const kg = r2((it.gramsPerDay * d) / 1000)
    const one = prices.length === 1 ? prices[0] : null
    return {
      code: it.code,
      name: it.name,
      codeMissing: it.codeMissing,
      gramsPerDay: r2(it.gramsPerDay),
      grams: r2(it.gramsPerDay * d),
      kg,
      pets: [...new Set(it.pets)],
      pricePerKg: one,
      priceConflict: conflict,
      /** 冲突时列出全部取值，让人自己选；不冲突时为空数组 */
      prices: conflict ? prices : [],
      /** 有唯一单价时才给金额；冲突时给区间（取任一边都是替用户拍板） */
      cost: one != null ? r2((it.gramsPerDay * d / 1000) * one) : null,
      costRange: (conflict && prices.length) ? {
        min: r2((it.gramsPerDay * d / 1000) * prices[0]),
        max: r2((it.gramsPerDay * d / 1000) * prices[prices.length - 1]),
      } : null,
    }
  }).sort((a, b) => b.kg - a.kg) // 按需求量降序：先买大头，便于核对

  const unmatched = [...umMap.values()].sort((a, b) => b.estimatedGramsPerDay - a.estimatedGramsPerDay)
    .map((u) => ({ ...u, pets: [...new Set(u.pets)] }))

  const note = []
  if (items.some((x) => x.codeMissing)) {
    note.push('有原料没有物料编号，已按名称归并 —— 名称相同但实际不同的原料会被合并，请人工核对')
  }
  if (items.some((x) => x.priceConflict)) {
    note.push('有原料在不同配方里单价不一致：未给出金额，只给区间（取哪一边都是替你做决定）')
  }
  if (unmatched.length) {
    note.push('未匹配原料的每日用量是按输入占比反推的估算值（不是验算值），与已匹配项不是同一可信度；请补齐原料库后重算')
  }
  note.push(`需求量按 ${d} 天口径折算；实买请考虑损耗、分装余量与最小起订量`)

  return { days: d, items, unmatched, note }
}

/* ================= 5. 主入口 ================= */

/** 失败原因：优先说清缺什么，而不是笼统说「算不出」 */
function failReasonOf(plan) {
  const miss = Array.isArray(plan && plan.missing) ? plan.missing : []
  if (miss.length) return `缺少：${miss.join('、')}`
  return '未能算出每日喂食量（请检查体重与配方代谢能数据）'
}

/**
 * 多宠聚合。
 *
 * @param {Array<{label?:string,name?:string,profile:object,recipe?:object,req?:object,unmatched?:Array}>} entries
 *        每只宠物一条；`profile` 必填（至少含 weightKg），`recipe` 为 `computeRecipe` 的返回对象
 * @param {{days?:number}} [opts]
 */
export function computeMultiPetPlan(entries = [], opts = {}) {
  const days = clampDays(opts && opts.days)
  const list = Array.isArray(entries) ? entries : []
  const warnings = []
  const notes = []

  /* ---- 空输入 / 超限：给可操作的错误，不抛栈、不静默 ---- */
  if (list.length === 0) {
    return {
      ok: false,
      days,
      petCount: 0,
      okCount: 0,
      failedCount: 0,
      reason: '没有宠物条目：至少给一只宠物的 profile 才能聚合',
      pets: [],
      totals: null,
      purchase: null,
      warnings,
      notes,
    }
  }
  if (list.length > MAX_PETS) {
    return {
      ok: false,
      days,
      petCount: list.length,
      okCount: 0,
      failedCount: list.length,
      reason: `宠物条目 ${list.length} 只，超过上限 ${MAX_PETS}：请分批聚合（静默截断会得到一个偏低的总量与采购清单）`,
      pets: [],
      totals: null,
      purchase: null,
      warnings,
      notes,
    }
  }

  /* ---- 标签：空标签兜底 + 重名去重。重名会让「哪只用了哪个物料」失去追溯力 ---- */
  const base = list.map((e, i) => str(e && e.label) || str(e && e.name)
    || str(e && e.profile && e.profile.name) || `宠物 ${i + 1}`)
  const counter = new Map()
  const labels = base.map((lb) => {
    const n = (counter.get(lb) || 0) + 1
    counter.set(lb, n)
    return n === 1 ? lb : `${lb}（第 ${n} 只）`
  })
  if (labels.some((lb, i) => lb !== base[i])) {
    warnings.push('存在重名宠物，已在标签后追加序号以便区分 —— 请核对「哪些宠物用到某原料」是否指对了对象')
  }

  /* ---- 逐宠计算 ---- */
  const pets = list.map((e, i) => {
    const profile = (e && e.profile) || {}
    const recipe = (e && e.recipe) || null
    const plan = computeFeedingPlan(profile, recipe, (e && e.req) || null, {}) || {}
    const ok = Boolean(plan.computed)
    const gp = num(plan.energy && plan.energy.gramsPerDay)
    const kcal = num(plan.energy && plan.energy.mer)
    const costDay = plan.cost && plan.cost.perDay != null ? num(plan.cost.perDay) : null

    return {
      index: i + 1,
      label: labels[i],
      name: str(profile.name),
      species: plan.species || '',
      speciesLabel: plan.speciesLabel || '',
      weightKg: num(plan.pet && plan.pet.weightKg) || null,
      bcs: (plan.pet && plan.pet.bcs != null) ? plan.pet.bcs : null,
      bcsLabel: (plan.pet && plan.pet.bcsLabel) || '',
      ok,
      failReason: ok ? '' : failReasonOf(plan),
      gramsPerDay: ok ? r0(gp) : null,
      perMeal: ok ? r0(num(plan.energy && plan.energy.perMeal)) : null,
      mealsPerDay: num(plan.meals && plan.meals.perDay) || null,
      kcalPerDay: ok ? r0(kcal) : null,
      costPerDay: ok && costDay != null ? r2(costDay) : null,
      costPerDays: ok && costDay != null ? r2(costDay * days) : null,
      pricePerKg: (plan.cost && plan.cost.pricePerKg != null) ? r2(num(plan.cost.pricePerKg)) : null,
      ingredients: ingredientDailyUse(recipe && recipe.lines, ok ? gp : 0),
      recipeTotalWeight: num(recipe && recipe.totalWeight),
      unmatched: normUnmatched(e && e.unmatched),
      missing: [...((plan.missing) || [])],
      warnings: [...((plan.warnings) || [])],
    }
  })

  const okPets = pets.filter((p) => p.ok)
  const failedPets = pets.filter((p) => !p.ok)
  if (failedPets.length) {
    warnings.push(`有 ${failedPets.length} 只宠物未算出喂食量（${failedPets.map((p) => p.label).join('、')}）`
      + '：它们【未计入】总量与采购清单，补齐数据后请重算')
  }

  /* ---- 合计（仅 ok 宠物）---- */
  const sumGrams = okPets.reduce((s, p) => s + num(p.gramsPerDay), 0)
  const sumKcal = okPets.reduce((s, p) => s + num(p.kcalPerDay), 0)
  const priced = okPets.filter((p) => p.costPerDay != null)
  const sumCost = priced.reduce((s, p) => s + num(p.costPerDay), 0)

  const totals = {
    petCount: pets.length,
    okCount: okPets.length,
    failedCount: failedPets.length,
    gramsPerDay: r0(sumGrams),
    grams: r0(sumGrams * days),
    kg: r2((sumGrams * days) / 1000),
    kcalPerDay: r0(sumKcal),
    costPerDay: priced.length ? r2(sumCost) : null,
    cost: priced.length ? r2(sumCost * days) : null,
    pricedCount: priced.length,
    unpricedCount: okPets.length - priced.length,
  }
  if (priced.length && priced.length < okPets.length) {
    totals.costNote = `只有 ${priced.length}/${okPets.length} 只宠物有单价资料，合计金额是【低估值】，不代表全部开销`
  } else if (!priced.length && okPets.length) {
    totals.costNote = '没有任何宠物有单价资料，未给出合计金额'
  }

  const purchase = purchaseFromPets(pets, days)

  if (okPets.length) {
    notes.push('采购清单是按「喂食量 × 配方内占比」折算的原料需求量，不含损耗与分装余量')
    notes.push('每日喂食量来自各宠的喂食计划：任何一只的体重或体况变了，本清单都要重算')
  }

  return {
    computed: okPets.length > 0,
    days,
    petCount: pets.length,
    okCount: okPets.length,
    failedCount: failedPets.length,
    reason: okPets.length ? '' : '所有宠物都未算出喂食量，无法生成总量与采购清单',
    totals,
    purchase,
    pets,
    warnings,
    notes,
  }
}
