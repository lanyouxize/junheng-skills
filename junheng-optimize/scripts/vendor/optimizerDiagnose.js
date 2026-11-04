/**
 * 不可行诊断（批 6 · N2 · F4）：**当求解器说「无解」时，把「为什么无解」讲清楚**。
 *
 * 只用 `solveLP` 的公开接口（黑盒调用），不碰任何内部状态 —— 这样它天然不会与求解器
 * 「错得一致」，也让它的每一条结论都能被独立验证（守卫用「注入已知冲突」来对答案）。
 *
 * ## 两件事，分开给
 *   ① `conflicts`：**极小冲突集（IIS）** —— 一组约束，删掉其中任意一条问题就变可行。
 *      算法 = 删除过滤法：从全集出发逐条试删，删掉后仍不可行就永久剔除，否则保留。
 *      代价 O(m) 次求解（m = 约束条数，本项目 ≈15，可忽略）。
 *   ② `relaxation`：**最小松弛量** —— 给每条约束的每个方向配一个 ≥0 的松弛变量
 *      （`a·x + δ ≥ L` 补下界缺口、`a·x − δ ≤ U` 让出上界余量），最小化 Σw·δ。这个弹性问题
 *      **必有最优解**（δ 可以任意大，目标有下界 0），所以它绝不会再抛一次「不可行」。
 *
 * ## 诚实边界
 *   · **只给一个** IIS。不可行集往往有多个 IIS，删除过滤法给出的是「按给定遍历顺序
 *     得到的那个」—— 换顺序可能换结果。全部穷举是组合爆炸，不做。
 *   · **松弛量受权重影响**：缺省 w=1 时是「各约束自量纲下绝对偏差之和」。量纲不一致
 *     （% 与 mg/kg 混在一条目标里）时这个合计数**只能当相对参考**，要严谨就传 `weights`。
 *   · 弹性问题在退化时**最优解不唯一**（两条约束各让一半也能是同一目标值），
 *     给出的分摊是一种可行分摊，不是唯一答案。
 *   · 变量界导致不可行（下界 > 上界）由求解器的 `bad_input` 拦下，不在这里诊断。
 *
 * 退出语义由调用方映射（**状态真源 = 本模块导出的 `DIAG_STATUS`**）：`infeasible` → 非 0，
 * `feasible` → 0，`bad_input` → 2，`unknown` → 3（**没能判定 ≠ 判定通过**）。
 */
import { solveLP, LP_STATUS } from './optimizer.js'

/**
 * 诊断层状态 —— **对外契约，值不可改**（门面按它映射退出码，守卫按它断言）。
 *
 * 与 `LP_STATUS` 是**两个枚举**，不要合并：
 *   · `BAD_INPUT` / `INFEASIBLE` 与 `LP_STATUS` 的同名成员**值相同**（由守卫钉住）——
 *     语义是「求解器状态直接透传」，不是把 LP 状态重新定义一遍。
 *   · `FEASIBLE` / `UNKNOWN` 是诊断层**独有的聚合态**：LP 求解器没有「可行」这个出口
 *     （可行由 `optimal` / `unbounded` 隐含），也没有把 `iteration_limit` 与
 *     `verify_failed` 合并成「未能判定」的出口。把这二者塞进 `LP_STATUS` 会污染
 *     求解器语义，所以宁可让两个枚举并存、并把「交集值一致」显式钉住。
 *
 * ⚠ 此前这四处是**裸字面量**、而比较处用的是 `LP_STATUS.*` —— 同一模块里两种写法并存，
 *   一旦 `LP_STATUS` 的值被改动，字面量处不会跟着变，判定会**静默失效**。
 */
export const DIAG_STATUS = Object.freeze({
  INFEASIBLE: 'infeasible',
  FEASIBLE: 'feasible',
  BAD_INPUT: 'bad_input',
  UNKNOWN: 'unknown',
})

const FEAS_TOL = 1e-7

const hasLo = (cn) => cn.lower !== undefined && cn.lower !== null && cn.lower !== -Infinity
const hasHi = (cn) => cn.upper !== undefined && cn.upper !== null && cn.upper !== Infinity

/** 把约束集合（按原始下标）打包成一个只含这些约束的新问题 */
function withConstraints(problem, indices) {
  return {
    c: problem.c,
    constraints: indices.map((k) => problem.constraints[k]),
    bounds: problem.bounds,
    maxIterations: problem.maxIterations,
  }
}

/** 删除过滤法：返回一个极小不可行子集（原始下标，升序） */
function findIis(problem, maxIterations) {
  const all = problem.constraints.map((_, k) => k)
  let keep = all.slice()
  for (const k of all) {
    if (!keep.includes(k)) continue
    const trial = keep.filter((x) => x !== k)
    const r = solveLP(withConstraints({ ...problem, maxIterations }, trial))
    // 只有**明确**仍不可行才剔除；「没能判定」（迭代上限/自检失败）一律保守保留 ——
    // 把不确定当成「可剔除」会悄悄缩小冲突集，给出一个假的极小集。
    if (r.status === LP_STATUS.INFEASIBLE) keep = trial
  }
  return keep
}

/** 最小松弛量：弹性 LP（一次求解） */
function minimalRelaxation(problem, weights, maxIterations) {
  const n = problem.c.length
  // 先把 δ 的**位置**定下来：每个有下界的约束一个（补下界缺口）、有上界的再一个（让上界）。
  // ⚠ 方向不能反：`a·x + δ ≥ L`（δ 补足缺口）与 `a·x − δ ≤ U`（δ 让出余量）。
  //   写成 `a·x − δ ≥ L` 是把约束**越放松越难满足**，弹性问题会立刻变成另一个不可行问题。
  // ⚠ 每条约束的 δ 分散在 `a` 的末尾几个**不同**列上（下标 n + 序号），所以 a 必须先按
  //   总宽 n + owner.length 铺满 0，再逐格填 —— 直接往 a 后面 append 会让各行的列数不等，
  //   校验层直接判 bad_input。
  const owner = []
  for (let k = 0; k < problem.constraints.length; k++) {
    const cn = problem.constraints[k]
    if (hasLo(cn)) owner.push({ index: k, side: 'lower' })
    if (hasHi(cn)) owner.push({ index: k, side: 'upper' })
  }
  if (owner.length === 0) return { status: LP_STATUS.OPTIMAL, total: 0, items: [], iterations: 0 }

  const width = n + owner.length
  const rows = owner.map((o, j) => {
    const cn = problem.constraints[o.index]
    const a = new Array(width).fill(0)
    for (let i = 0; i < n; i++) a[i] = cn.a[i]
    a[n + j] = o.side === 'lower' ? 1 : -1
    return o.side === 'lower' ? { a, lower: cn.lower } : { a, upper: cn.upper }
  })

  const w = (k) => {
    const v = weights ? weights[k] : 1
    return Number.isFinite(v) && v >= 0 ? v : 1      // 权重缺失/非法一律退回 1，不让 NaN 漏进目标
  }
  const c2 = [...new Array(n).fill(0), ...owner.map((o) => w(o.index))]
  const bounds = []
  for (let j = 0; j < n; j++) bounds.push((problem.bounds || [])[j] || { lower: 0 })
  for (let j = 0; j < owner.length; j++) bounds.push({ lower: 0 })   // δ ≥ 0，上界缺省 ∞

  const r = solveLP({ c: c2, constraints: rows, bounds, maxIterations })
  if (r.status !== LP_STATUS.OPTIMAL) {
    return { status: r.status, total: null, items: [], iterations: r.iterations }
  }
  const items = []
  for (let j = 0; j < owner.length; j++) {
    const amt = r.x[n + j]
    if (amt > FEAS_TOL) items.push({ index: owner[j].index, side: owner[j].side, amount: amt })
  }
  return { status: r.status, total: r.objective, items, iterations: r.iterations }
}

/**
 * 诊断不可行。**一切合法输入都返回一个结构化结论**，不抛异常。
 * @param {object} problem  与 `solveLP` 同形
 * @param {object} [options]
 * @param {number[]} [options.weights]  各约束在松弛目标里的权重（长度 = 约束数，缺省全 1）
 * @returns {{status:string, message:string,   // 取值 ∈ `DIAG_STATUS`：infeasible / feasible / bad_input / unknown
 *            conflicts:Array<{indices:number[], constraints:Array<{lower:number|null,upper:number|null}>}>,
 *            relaxation:{status:string,total:number|null,items:Array,iterations:number}|null,
 *            iterations:number}}
 */
export function diagnoseInfeasible(problem, options = {}) {
  const probe = solveLP(problem)
  if (probe.status === LP_STATUS.BAD_INPUT) {
    return { status: DIAG_STATUS.BAD_INPUT, message: probe.message, conflicts: [], relaxation: null, iterations: 0 }
  }
  if (probe.status !== LP_STATUS.INFEASIBLE) {
    // OPTIMAL / UNBOUNDED 都说明**可行**（无界 ≠ 不可行，它有可行点只是没有最优）；
    // 其余状态（迭代上限 / 自检失败）是「没能判定」——不能冒充「可行」。
    if (probe.status === LP_STATUS.OPTIMAL || probe.status === LP_STATUS.UNBOUNDED) {
      return {
        status: DIAG_STATUS.FEASIBLE,
        message: `原问题可行（求解器状态 ${probe.status}），无需诊断`,
        conflicts: [], relaxation: null, iterations: probe.iterations,
      }
    }
    return {
      status: DIAG_STATUS.UNKNOWN,
      message: `无法诊断：求解器未能判定可行性（状态 ${probe.status}）—— 没能判定 ≠ 判定通过`,
      conflicts: [], relaxation: null, iterations: probe.iterations,
    }
  }

  const weights = options.weights
  const maxIterations = options.maxIterations
  const indices = findIis({ ...problem, maxIterations }, maxIterations)
  const conflicts = [{
    indices,
    constraints: indices.map((k) => ({
      lower: hasLo(problem.constraints[k]) ? problem.constraints[k].lower : null,
      upper: hasHi(problem.constraints[k]) ? problem.constraints[k].upper : null,
    })),
  }]
  const relaxation = minimalRelaxation({ ...problem, maxIterations }, weights, maxIterations)
  return {
    status: DIAG_STATUS.INFEASIBLE,
    message: `原问题不可行：极小冲突集含 ${indices.length} 条约束（删除其中任意一条即可行）`,
    conflicts,
    relaxation,
    iterations: probe.iterations,
  }
}
