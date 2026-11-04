#!/usr/bin/env node
/**
 * junheng-optimize —— 宠物食品配方「最低成本逆解」的命令行门面。
 *
 * 唯一的实质工作是「参数装配 → 调用 src/lib/optimizer.js / optimizerDiagnose.js → 输出 JSON」。
 * 门面内**不含任何业务公式**：营养折算、单位换算、法规限值一律不做 ——
 * 它只把调用方写下的线性模型原样交给求解器。系数写错，错在模型，不在这里。
 *
 * ## 它回答的问题
 * 「按这些原料、这个成本、这些约束，最省的配比是多少」以及「若无解，是哪几条约束打架」。
 *
 * ## 与邻居的分工（别混用）
 *   · junheng-nutrition / -attainment：算**给定配比**的营养与达标度（正向）。
 *   · 本技能：算**成本最优配比**（反向）—— 目标函数是最小化成本。
 *     两者可以串联：本技能出配比 → 交给营养能力验收。
 *
 * ## 不可行 ≠ 无解于现实
 * `infeasible` 只说明「在当前这套系数与约束下没有可行点」。它几乎总是建模问题
 * （约束互相矛盾、量纲混乱、遗漏了某条松弛），而不是配方本身不可行。
 * 因此配套 `diagnose`：给出**极小冲突集**（删掉其中任意一条即可行）与**最小松弛量**。
 *
 * ## 影子价格只在本点附近成立
 * `shadowPrices` 是约束右端在当前最优解处的**局部**灵敏度（对偶值）。它只对绑定约束
 * 有意义，且只在该解的邻域内成立 —— 不要外推成大范围结论，更不要当报价依据。
 *
 * 调用形态（详见 `--help`）：
 *   node cli/optimize.mjs solve '{"variables":[{"name":"鸡肉粉","cost":12.5,"coefficients":[{"constraint":"蛋白","value":65}]}],"constraints":[{"name":"蛋白","lower":2800}]}'
 *   node cli/optimize.mjs diagnose '{...同上...}'
 *   node cli/optimize.mjs --help
 *
 * 退出码：0 成功（**含** infeasible / unbounded —— 它们是业务结论，不是程序错误）/
 *         1 内部错误 / 2 用法或输入错误 / 3 前置条件缺失（源码镜像未同步）。
 *         ⚠ 业务结论一律读 `data.status`，**不要**用退出码判断是否求得最优解。
 *
 * ⚠ 输出只走 `process.exitCode`（不调 process.exit）：后者在管道下会截断尚未冲刷的
 *   stdout，导致调用方拿到半截 JSON。
 */
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { importFromVendor, isEntrypoint } from './lib/locate.mjs'
import { runCli } from './lib/runner.mjs'
import { emitError, makeIo } from './lib/output.mjs'

export const NAME = 'junheng-optimize'
export const VERSION = '1.0.0'
export const SUMMARY = '宠物食品配方最低成本逆解：给定原料成本与线性约束求最省配比；不可行时给出极小冲突集与最小松弛量'
export const PROBE = ['optimizer.js', 'optimizerDiagnose.js']
export const DISCLAIMER = '本结果是**线性模型**的最优解 —— 系数、单位与约束是否如实表达业务，由调用方负责：'
  + '本门面只做装配与求解，**不做**营养折算、**不做**单位换算、**不做**法规校验。'
  + '`infeasible` 只说明「在这套模型下无可行解」，不等于现实中配不出来，请用 `diagnose` 看是哪几条约束冲突。'
  + '`shadowPrices` 是约束右端在当前最优解处的**局部**灵敏度，只对绑定约束有意义、只在该点邻域成立，不可外推。'

const HERE = path.dirname(fileURLToPath(import.meta.url))

const COEF_FIELDS = {
  constraint: { type: 'string', required: true, desc: '约束名（必须已在 constraints[].name 里声明）' },
  value: { type: 'number', required: true, desc: '本变量在该约束里的系数' },
}

const VARIABLE_FIELDS = {
  name: { type: 'string', required: true, desc: '变量名（即原料名，必须唯一）' },
  cost: { type: 'number', required: true, desc: '单位成本（目标系数，最小化）' },
  lower: { type: 'number', desc: '用量下界（缺省 0）' },
  upper: { type: 'number', desc: '用量上界（缺省不限）' },
  coefficients: { type: 'array', fields: COEF_FIELDS, desc: '本变量在各约束里的系数（未列出的约束按 0 计）' },
}

const CONSTRAINT_FIELDS = {
  name: { type: 'string', required: true, desc: '约束名（必须唯一）' },
  lower: { type: 'number', desc: '下界（与 upper 至少给一个）' },
  upper: { type: 'number', desc: '上界（与 lower 至少给一个）' },
  weight: { type: 'number', desc: '松弛权重（仅 diagnose 用；缺省 1，越大越不愿松这条）' },
}

const LP_PARAMS = {
  variables: { type: 'array', required: true, minItems: 1, fields: VARIABLE_FIELDS, desc: '决策变量（每种原料一个）' },
  constraints: { type: 'array', required: true, minItems: 1, fields: CONSTRAINT_FIELDS, desc: '线性约束' },
  maxIterations: { type: 'number', desc: '迭代上限（缺省由求解器决定；一般不用给）' },
}

const isFin = (v) => typeof v === 'number' && Number.isFinite(v)

/**
 * 把「带名字的模型」摊成求解器要的系数矩阵。
 * 这里只做**搬运与铺零**，没有任何业务计算（这是「门面零公式」的具体含义）。
 */
function buildLp(input) {
  const variables = input.variables
  const constraints = input.constraints
  const colOf = new Map()
  variables.forEach((v, j) => colOf.set(v.name, j))

  const c = variables.map((v) => v.cost)
  const bounds = variables.map((v) => {
    const b = { lower: isFin(v.lower) ? v.lower : 0 }
    if (isFin(v.upper)) b.upper = v.upper
    return b
  })

  const rows = constraints.map((cn) => {
    const a = new Array(variables.length).fill(0)
    for (const v of variables) {
      for (const co of v.coefficients || []) {
        if (co.constraint === cn.name) a[colOf.get(v.name)] += co.value
      }
    }
    const row = { a }
    if (isFin(cn.lower)) row.lower = cn.lower
    if (isFin(cn.upper)) row.upper = cn.upper
    return row
  })

  const lp = { c, constraints: rows, bounds }
  if (isFin(input.maxIterations)) lp.maxIterations = input.maxIterations
  return lp
}

/**
 * 参数**组合**校验（runner 的 `check` 钩子：返回非空字符串 ⇒ 按用法错误早停，run 不执行）。
 * 单字段合法但组合起来没有意义的调用必须在这里拦下 —— 否则会跑出一个看似正常的假解。
 */
function checkModel(a) {
  const variables = a.variables
  const constraints = a.constraints
  const seenVar = new Set()
  for (const v of variables) {
    if (seenVar.has(v.name)) return `变量名重复：「${v.name}」—— 变量名必须唯一，否则系数会张冠李戴`
    seenVar.add(v.name)
    if (isFin(v.upper) && isFin(v.lower) && v.lower > v.upper) {
      return `变量「${v.name}」的下界 ${v.lower} 大于上界 ${v.upper}，该变量永远取不到值`
    }
  }
  const seenCn = new Set()
  for (const cn of constraints) {
    if (seenCn.has(cn.name)) return `约束名重复：「${cn.name}」—— 约束名必须唯一`
    seenCn.add(cn.name)
    const hasLo = isFin(cn.lower)
    const hasHi = isFin(cn.upper)
    if (!hasLo && !hasHi) {
      return `约束「${cn.name}」既没有 lower 也没有 upper —— 这样的约束没有任何限制力，请补边界或删掉它`
    }
    if (hasLo && hasHi && cn.lower > cn.upper) {
      return `约束「${cn.name}」的下界 ${cn.lower} 大于上界 ${cn.upper}，必然不可行`
    }
  }
  for (const v of variables) {
    const hit = new Set()
    for (const co of v.coefficients || []) {
      if (!seenCn.has(co.constraint)) {
        return `变量「${v.name}」引用了未声明的约束「${co.constraint}」—— 请先在 constraints 里声明它`
      }
      if (hit.has(co.constraint)) {
        return `变量「${v.name}」对约束「${co.constraint}」给了不止一个系数 —— 请合并成一个，避免歧义`
      }
      hit.add(co.constraint)
    }
  }
  return ''
}

/** 把求解结果映射回「带名字」的形态。非最优时**不给**任何数值字段（避免调用方误读残值）。
 *
 *  ★ `LP` = `api.LP_STATUS`（`src/lib/optimizer.js` 导出的状态枚举），由调用方传入。
 *    这里**不再写字面量** `'optimal'` —— 门面已 import 该枚举，再抄一份字面量就是第二处判据，
 *    枚举一旦改名，本处会**静默**退化成「永远非最优」（`ok:false`、数值全 `null`），
 *    而没有任何守卫会红。同一分类只许一处判据。
 */
function renderSolve(r, input, LP) {
  const vNames = input.variables.map((v) => v.name)
  const cNames = input.constraints.map((c) => c.name)
  const base = {
    status: r.status,
    ok: r.status === LP.OPTIMAL,
    message: r.message,
    scale: { variables: vNames.length, constraints: cNames.length },
    iterations: r.iterations,
  }
  if (r.status !== LP.OPTIMAL) {
    return {
      ...base,
      objective: null,
      values: null,
      constraintValues: null,
      shadowPrices: null,
      variableMarginals: null,
      hint: r.status === LP.INFEASIBLE
        ? '约束互相冲突：改用 diagnose 命令可得到极小冲突集与最小松弛量'
        : null,
    }
  }
  return {
    ...base,
    objective: r.objective,
    values: vNames.map((name, j) => ({
      variable: name,
      amount: r.x[j],
      at: r.variableMarginals[j] ? r.variableMarginals[j].at : null,
      reducedCost: r.variableMarginals[j] ? r.variableMarginals[j].reducedCost : null,
    })),
    constraintValues: cNames.map((name, k) => ({ constraint: name, ...r.constraintValues[k] })),
    shadowPrices: r.shadowPrices.map((s) => ({ constraint: cNames[s.index], ...s })),
    variableMarginals: r.variableMarginals.map((m) => ({ variable: vNames[m.index], ...m })),
    hint: null,
  }
}

/** 把诊断结果映射回「带名字」的形态。`DS` = `optimizerDiagnose.js` 的 `DIAG_STATUS` 真源。 */
function renderDiagnose(d, input, DS) {
  const cNames = input.constraints.map((c) => c.name)
  const base = { status: d.status, message: d.message, iterations: d.iterations }
  if (d.status !== DS.INFEASIBLE) return { ...base, conflicts: [], relaxation: null }
  return {
    ...base,
    conflicts: d.conflicts.map((c) => ({
      indices: c.indices,
      constraints: c.indices.map((k) => ({ index: k, constraint: cNames[k], ...c.constraints[c.indices.indexOf(k)] })),
    })),
    relaxation: d.relaxation === null ? null : {
      status: d.relaxation.status,
      total: d.relaxation.total,
      iterations: d.relaxation.iterations,
      items: d.relaxation.items.map((it) => ({ constraint: cNames[it.index], ...it })),
    },
  }
}

/** 由已加载的源码模块构造命令表。导出以便测试直接检视注册表，无需起进程。 */
export function buildCommands(api) {
  return {
    solve: {
      summary: '求最低成本配比：给变量（原料）成本与线性约束，返回最优配比、影子价格与变量边际',
      params: LP_PARAMS,
      check: checkModel,
      run: (a) => {
        const input = { variables: a.variables, constraints: a.constraints, maxIterations: a.maxIterations }
        return renderSolve(api.solveLP(buildLp(input)), input, api.LP_STATUS)
      },
    },

    diagnose: {
      summary: '诊断不可行：返回极小冲突集（删任一条即可行）与最小松弛量（要松多少才可行）',
      params: LP_PARAMS,
      check: checkModel,
      run: (a) => {
        const input = { variables: a.variables, constraints: a.constraints, maxIterations: a.maxIterations }
        const weights = a.constraints.map((c) => (isFin(c.weight) ? c.weight : 1))
        const opt = {}
        if (isFin(a.maxIterations)) opt.maxIterations = a.maxIterations
        opt.weights = weights
        return renderDiagnose(api.diagnoseInfeasible(buildLp(input), opt), input, api.DIAG_STATUS)
      },
    },
  }
}

/** 门面主流程。返回退出码（不退出进程，便于测试在进程内断言）。 */
export async function main(argv = process.argv.slice(2), io) {
  const out = io || makeIo()
  let api
  try {
    const opt = await importFromVendor(HERE, PROBE, 'optimizer.js')
    const dg = await importFromVendor(HERE, PROBE, 'optimizerDiagnose.js')
    api = { solveLP: opt.solveLP, LP_STATUS: opt.LP_STATUS, diagnoseInfeasible: dg.diagnoseInfeasible, DIAG_STATUS: dg.DIAG_STATUS }
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
