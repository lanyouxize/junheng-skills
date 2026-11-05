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
 * 把 junheng 营养约束 + 原料清单构建为 LP 并求解最低成本配方。
 *
 * @param {object} args
 *   ingredients  {Array<{id:string, name:string, price:number, nutrients:{[k]:number}}>}
 *                nutrients 为 %DM 基准的营养值
 *   constraints  {Array<{key:string, label:string, min?:number, max?:number, unit:string}>}
 *                来自 resolveStandard(...).items（已 available 过滤）
 *   species/stage/moistureClass 仅用于报告
 * @returns 求解结果 + 可读性报告
 */
export function formulateLeastCost(args) {
  const { ingredients, constraints } = args
  const n = ingredients.length
  const used = constraints.filter((c) => c.min != null || c.max != null)

  // 目标：最小成本
  const objective = ingredients.map((g) => g.price)

  // 约束：营养 min/max（用 %DM 营养矩阵）+ Σ=1
  const lpConstraints = []
  const binding = []
  for (const c of used) {
    const coeffs = ingredients.map((g) => +(g.nutrients[c.key] ?? 0))
    if (c.min != null) {
      lpConstraints.push({ coeffs, op: '>=', rhs: c.min })
      binding.push({ key: c.key, op: '>=', rhs: c.min, label: c.label })
    }
    if (c.max != null) {
      lpConstraints.push({ coeffs, op: '<=', rhs: c.max })
      binding.push({ key: c.key, op: '<=', rhs: c.max, label: c.label })
    }
  }
  lpConstraints.push({ coeffs: ingredients.map(() => 1), op: '=', rhs: 1 })
  binding.push({ key: '__sum', op: '=', rhs: 1, label: '配方总占比' })

  const res = solveLP({ nVars: n, objective, constraints: lpConstraints })

  // 解后校验：实际营养达成度
  const achieved = {}
  for (const c of used) {
    let v = 0
    for (let i = 0; i < n; i++) v += (ingredients[i].nutrients[c.key] ?? 0) * (res.x[i] ?? 0)
    achieved[c.key] = { label: c.label, value: +v.toFixed(4), min: c.min ?? null, max: c.max ?? null, unit: c.unit }
  }

  return {
    status: res.status,
    recipe: ingredients.map((g, i) => ({
      id: g.id, name: g.name, share: +(res.x[i] ?? 0).toFixed(4), price: g.price,
    })),
    unitCost: res.status === 'optimal' ? +res.objective.toFixed(4) : null,
    constraints: binding,
    achieved,
  }
}
