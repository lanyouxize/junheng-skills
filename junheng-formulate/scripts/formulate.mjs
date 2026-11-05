// formulate.mjs — 零依赖纯 JS 两阶段单纯形 LP 求解器 + junheng 配方接线
//
// 设计约束（见 A2 评估文档「决策1 栈」）：
//   不引入任何 npm 第三方库（javascript-lp-solver / glpk.js 均拒绝），
//   纯 Node ESM 实现，保证「可在其他电脑直接运行」+ 可逐行验证。
//
// 求解能力：最小化 c·x，变量非负，约束支持 <= / >= / =。
//   原料最大添加量 x_i <= cap 直接作为 <= 约束接入（同一套约束机，无需额外处理）。
//   配方总占比 Σx_i = 1 作为 = 约束接入。

const EPS = 1e-9

/**
 * 两阶段单纯形法。
 * @param {object} prob
 *   nVars       {number}            决策变量个数
 *   objective   {number[]}          最小化 c·x，长度 nVars
 *   constraints {Array<{coeffs:number[], op:'<='|'>='|'=', rhs:number}>}
 * @returns {{status:'optimal'|'infeasible'|'unbounded', x:number[], objective:number, basis?:number[]}}
 */
export function solveLP(prob) {
  const n = prob.nVars
  const m = prob.constraints.length
  if (m === 0) return { status: 'infeasible', x: [], objective: NaN, note: '无约束' }

  // ---- 1. 构造辅助变量列 ----
  // 每约束追加：slack(+1, <=) / surplus(-1, >=) / artificial(+1, >= 或 =)
  // 用 per-constraint 的真实列号（slackIdx/surpIdx/artIdx）避免「约束索引」与「列索引」混淆。
  const colMeta = [] // 每列类型：'x' | 'slack' | 'surplus' | 'art'
  for (let j = 0; j < n; j++) colMeta.push('x')
  const slackIdx = new Array(m).fill(-1)
  const surpIdx = new Array(m).fill(-1)
  const artIdx = new Array(m).fill(-1)
  let col = n
  for (let i = 0; i < m; i++) {
    const op = prob.constraints[i].op
    if (op === '<=') { slackIdx[i] = col; colMeta.push('slack'); col++ }
    else if (op === '>=') { surpIdx[i] = col; colMeta.push('surplus'); col++; artIdx[i] = col; colMeta.push('art'); col++ }
    else { artIdx[i] = col; colMeta.push('art'); col++ }
  }
  const totalCols = col

  // ---- 2. 构造初始单纯形表 ----
  // tableau[i] = [a_{i,0}..a_{i,totalCols-1} | rhs]
  const tableau = []
  const basis = new Array(m).fill(-1)
  for (let i = 0; i < m; i++) {
    const c = prob.constraints[i]
    const row = new Array(totalCols + 1).fill(0)
    for (let j = 0; j < n; j++) row[j] = c.coeffs[j]
    if (c.op === '<=') { row[slackIdx[i]] = 1; basis[i] = slackIdx[i] }
    else if (c.op === '>=') { row[surpIdx[i]] = -1; row[artIdx[i]] = 1; basis[i] = artIdx[i] }
    else { row[artIdx[i]] = 1; basis[i] = artIdx[i] }
    row[totalCols] = c.rhs
    tableau.push(row)
  }

  // 工具：找主元并旋转
  const pivot = (ti, enter) => {
    const piv = tableau[ti][enter]
    for (let j = 0; j <= totalCols; j++) tableau[ti][j] /= piv
    for (let i = 0; i < m; i++) {
      if (i === ti) continue
      const f = tableau[i][enter]
      if (Math.abs(f) < EPS) continue
      for (let j = 0; j <= totalCols; j++) tableau[i][j] -= f * tableau[ti][j]
    }
  }

  // 单纯形核心（最小化目标）。costRow 长度 totalCols。
  // allowEnter(j)：是否允许该列进基（Phase2 必须排除人工变量列，否则会被误选）。
  const DEBUG = process.env.DEBUG === '1'
  const simplexCore = (costRow, allowEnter = () => true) => {
    if (DEBUG) console.error('[simplexCore] costRow=', costRow.map((v) => +v.toFixed(3)))
    for (;;) {
      // 计算检验数 rc_j = c_j - c_B·B^{-1}A_j（用当前表行）
      const rc = new Array(totalCols).fill(0)
      for (let j = 0; j < totalCols; j++) {
        let cj = costRow[j]
        for (let i = 0; i < m; i++) cj -= costRow[basis[i]] * tableau[i][j]
        rc[j] = cj
      }
      // 进基：检验数最负者（最小化问题）
      let enter = -1, best = -EPS
      for (let j = 0; j < totalCols; j++) if (allowEnter(j) && rc[j] < best) { best = rc[j]; enter = j }
      if (enter === -1) return { status: 'optimal' }
      // 比值检验（出基）
      let leave = -1, bestRatio = Infinity
      if (DEBUG) console.error('  rc=', rc.map((v) => +v.toFixed(3)), 'enter=', enter)
      for (let i = 0; i < m; i++) {
        const aij = tableau[i][enter]
        if (aij > EPS) {
          const ratio = tableau[i][totalCols] / aij
          if (ratio < bestRatio - 1e-12 || (Math.abs(ratio - bestRatio) < 1e-12 && leave === -1)) {
            bestRatio = ratio; leave = i
          }
        }
      }
      if (leave === -1) return { status: 'unbounded' }
      if (DEBUG) console.error('  leave=', leave, 'ratio=', bestRatio.toFixed(4))
      pivot(leave, enter)
      basis[leave] = enter
    }
  }

  // ---- 3. Phase 1：最小化人工变量之和（仅人工变量列成本=1）----
  const phase1Cost = new Array(totalCols).fill(0)
  for (let i = 0; i < m; i++) if (artIdx[i] >= 0) phase1Cost[artIdx[i]] = 1
  const p1 = simplexCore(phase1Cost)
  if (p1.status === 'unbounded') return { status: 'infeasible', x: [], objective: NaN }
  // 检查人工变量残留
  let artSum = 0
  for (let i = 0; i < m; i++) if (colMeta[basis[i]] === 'art') artSum += Math.abs(tableau[i][totalCols])
  if (artSum > 1e-6) return { status: 'infeasible', x: [], objective: NaN }

  // 把仍为基变量（值=0）的人工列换出，避免 Phase2 干扰
  for (let i = 0; i < m; i++) {
    if (colMeta[basis[i]] === 'art' && Math.abs(tableau[i][totalCols]) < EPS) {
      let swap = -1
      for (let j = 0; j < totalCols; j++) {
        if (colMeta[j] !== 'art' && Math.abs(tableau[i][j]) > EPS) { swap = j; break }
      }
      if (swap !== -1) pivot(i, swap), (basis[i] = swap)
    }
  }

  // ---- 4. Phase 2：最小化原目标（人工变量列禁止进基）----
  const phase2Cost = new Array(totalCols).fill(0)
  for (let j = 0; j < n; j++) phase2Cost[j] = prob.objective[j]
  const p2 = simplexCore(phase2Cost, (j) => colMeta[j] !== 'art')
  if (p2.status === 'unbounded') return { status: 'unbounded', x: [], objective: -Infinity }

  // 提取解
  const x = new Array(n).fill(0)
  for (let i = 0; i < m; i++) {
    const bv = basis[i]
    if (bv < n) x[bv] = Math.max(0, tableau[i][totalCols])
  }
  let obj = 0
  for (let j = 0; j < n; j++) obj += prob.objective[j] * x[j]
  // 清理数值噪声
  for (let j = 0; j < n; j++) if (Math.abs(x[j]) < 1e-9) x[j] = 0
  return { status: 'optimal', x, objective: obj, basis }
}

/**
 * 把 junheng 营养约束 + 原料清单构建为 LP 并求解配方。
 *
 * @param {object} args
 *   ingredients  {Array<{id:string, name:string, price:number, nutrients:{[k]:number}}>}
 *                nutrients 为 %DM 基准的营养值
 *   constraints  {Array<{key:string, label:string, min?:number, max?:number, unit:string,
 *                         ratio?:{num:string,den:string}}>}
 *                来自 resolveStandard(...).items（已 available 过滤）；
 *                比值类（如钙磷比 caP）用 ratio:{num,den} 标记，其 min/max 作用于 num/den 之比。
 *   ingredientMax {Object<string|number, number>}  原料 id（或下标）=> 最大添加比例（0~1）
 *   strategy     {'least_cost'|'balanced'|'nutrient_max'}  默认 'least_cost'
 *   budget       {number}  nutrient_max 策略的预算上限（单位成本上限）；缺省取上限估算
 *   devWeight    {number}  balanced 策略的偏差惩罚权重（默认 1.0）
 * @returns 求解结果 + 可读性报告 + 质量门禁 diagnostics
 */
export function formulateLeastCost(args) {
  const {
    ingredients,
    constraints,
    ingredientMax = {},
    strategy = 'least_cost',
    budget = null,
    devWeight = 1.0,
  } = args
  const n = ingredients.length
  const used = constraints.filter((c) => c.min != null || c.max != null)
  const price = ingredients.map((g) => g.price)

  // 基础营养约束（min/max/比值）统一为 coeffs/op/rhs 三元组
  const nutrientConstrs = []
  for (const c of used) {
    if (c.ratio) {
      const { num, den } = c.ratio
      if (c.min != null) {
        const coeffs = ingredients.map((g) => (g.nutrients[num] ?? 0) - c.min * (g.nutrients[den] ?? 0))
        nutrientConstrs.push({ coeffs, op: '>=', rhs: 0, key: c.key, label: c.label, kind: 'ratio-min' })
      }
      if (c.max != null) {
        const coeffs = ingredients.map((g) => (g.nutrients[num] ?? 0) - c.max * (g.nutrients[den] ?? 0))
        nutrientConstrs.push({ coeffs, op: '<=', rhs: 0, key: c.key, label: c.label, kind: 'ratio-max' })
      }
      continue
    }
    const coeffs = ingredients.map((g) => +(g.nutrients[c.key] ?? 0))
    if (c.min != null) nutrientConstrs.push({ coeffs, op: '>=', rhs: c.min, key: c.key, label: c.label, kind: 'min' })
    if (c.max != null) nutrientConstrs.push({ coeffs, op: '<=', rhs: c.max, key: c.key, label: c.label, kind: 'max' })
  }

  const ones = (len) => new Array(len).fill(1)
  const oneHot = (len, i) => { const a = new Array(len).fill(0); a[i] = 1; return a }

  // ---- least_cost / nutrient_max：纯营养硬约束 + Σ=1 + 可选预算上限 ----
  if (strategy === 'least_cost' || strategy === 'nutrient_max') {
    const lp = nutrientConstrs.map((nc) => ({ coeffs: nc.coeffs, op: nc.op, rhs: nc.rhs }))
    for (let i = 0; i < n; i++) {
      const cap = ingredientMax[ingredients[i].id] ?? ingredientMax[i]
      if (cap != null) lp.push({ coeffs: oneHot(n, i), op: '<=', rhs: cap })
    }
    lp.push({ coeffs: ones(n), op: '=', rhs: 1 })
    if (strategy === 'nutrient_max') {
      const b = budget != null ? budget : Math.ceil(Math.max(...price) * 100) / 100
      lp.push({ coeffs: price.slice(), op: '<=', rhs: b })
    }
    const res = solveLP({ nVars: n, objective: price, constraints: lp })
    return finalize(res, { ingredients, used, strategy, n, deviationVars: null })
  }

  // ---- balanced：硬安全下限/上限 + 软偏差（向目标剖面收敛） ----
  if (strategy === 'balanced') {
    const K = used.length
    const N = n + 2 * K
    const objective = new Array(N).fill(0)
    for (let i = 0; i < n; i++) objective[i] = price[i]
    for (let k = 0; k < K; k++) { objective[n + 2 * k] = devWeight; objective[n + 2 * k + 1] = devWeight }
    const lp = []
    const deviationVars = []
    for (let k = 0; k < K; k++) {
      const c = used[k]
      const a = ingredients.map((g) => +(g.nutrients[c.key] ?? 0))
      const dUp = n + 2 * k
      const dDn = n + 2 * k + 1
      const target = c.min != null && c.max != null ? (c.min + c.max) / 2 : (c.min != null ? c.min : c.max)
      const coeffs = a.concat(new Array(2 * K).fill(0))
      coeffs[dUp] = -1; coeffs[dDn] = 1
      lp.push({ coeffs, op: '=', rhs: target }) // 软等式：Σa_jx_j - d_up + d_dn = target
      if (c.min != null) lp.push({ coeffs: a.slice(), op: '>=', rhs: c.min }) // 硬安全下限
      if (c.max != null) lp.push({ coeffs: a.slice(), op: '<=', rhs: c.max }) // 硬安全上限
      deviationVars.push({ k, dUp, dDn, target })
    }
    for (let i = 0; i < n; i++) {
      const cap = ingredientMax[ingredients[i].id] ?? ingredientMax[i]
      if (cap != null) lp.push({ coeffs: oneHot(N, i), op: '<=', rhs: cap })
    }
    lp.push({ coeffs: ones(N), op: '=', rhs: 1 })
    const res = solveLP({ nVars: N, objective, constraints: lp })
    return finalize(res, { ingredients, used, strategy, n, deviationVars })
  }

  throw new Error('未知 strategy: ' + strategy)
}

// 解后整理：配方、单位成本、实际营养达成度、质量门禁诊断
function finalize(res, ctx) {
  const { ingredients, used, strategy, n, deviationVars } = ctx
  if (res.status !== 'optimal') {
    return {
      status: res.status,
      recipe: [],
      unitCost: null,
      strategy,
      diagnostics: { status: res.status, note: '不可行或无界：请核查营养约束、原料上限或预算是否冲突' },
    }
  }
  const x = res.x.slice(0, n)
  const recipe = ingredients.map((g, i) => ({ id: g.id, name: g.name, share: +x[i].toFixed(4), price: g.price }))
  const unitCost = +res.objective.toFixed(4)
  const achieved = {}
  let deficit = 0, overshoot = 0
  for (const c of used) {
    let v = 0
    for (let i = 0; i < n; i++) v += (ingredients[i].nutrients[c.key] ?? 0) * (x[i] ?? 0)
    const a = +v.toFixed(4)
    achieved[c.key] = { label: c.label, value: a, min: c.min ?? null, max: c.max ?? null, unit: c.unit }
    if (c.min != null && a < c.min - 1e-3) deficit++
    if (c.max != null && a > c.max + 1e-3) overshoot++
  }
  let devSum = 0
  if (deviationVars) for (const dv of deviationVars) devSum += (x[dv.dUp] ?? 0) + (x[dv.dDn] ?? 0)
  return {
    status: 'optimal',
    strategy,
    recipe,
    unitCost,
    achieved,
    deviationSum: deviationVars ? +devSum.toFixed(4) : null,
    diagnostics: {
      status: 'optimal',
      constraintCount: used.length,
      minCount: used.filter((c) => c.min != null).length,
      maxCount: used.filter((c) => c.max != null).length,
      deficitCount: deficit,
      overshootCount: overshoot,
    },
  }
}
