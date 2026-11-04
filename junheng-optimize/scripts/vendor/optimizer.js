/**
 * 零依赖线性规划（LP）求解器：**有界变量 · 两阶段单纯形**。
 *
 * ## 它解什么
 *   min  cᵀx
 *   s.t. lower_k ≤ a_k·x ≤ upper_k    （k = 1..m；上下界可只给其一；两者相等 ⇒ 等式）
 *        lb_j ≤ x_j ≤ ub_j            （lb 必须**有限**，缺省 0；ub 缺省 +∞）
 *
 * ## 为什么是「有界变量」单纯形
 * 成分优化是典型的 diet problem：**变量多（≈286）、通用约束少（≈15）**，而每个变量都带
 * `[lb, ub]`。若把变量上下界摊成约束行（`x_j ≤ ub_j`），行数会涨到几百，而稠密表每次
 * 主元的代价是 O(行数 × 列数) ⇒ 直接爆掉。本实现把上下界**留在变量上**：非基变量停在
 * 某一侧界上，必要时只「翻界」而不换基。表里只留通用约束的 m 行 —— 286×15 的规模下
 * 每次主元只做约 3000 次乘法。
 *
 * ## 步骤
 *   ① 变量平移 `y = x − lb`（y ≥ 0），让所有变量都有有限下界（单纯形的前提）；
 *   ② 每条通用约束配一个**松弛变量**，把区间约束化成等式行（见 §buildRows 的注释）；
 *   ③ **阶段 I**：每行加人工变量、最小化其和。和超过容差 ⇒ 原问题**不可行**；
 *   ④ 把仍是基变量的人工变量换出（同行找一个非基真实列做上主元）；某行找不到 ⇒ 该行是
 *      **冗余行**（恒为 0 = 0），连行带人工列一并删除 —— 不损失任何约束力；
 *   ⑤ **阶段 II**：用原目标函数在删剩的表上继续迭代；
 *   ⑥ 逆平移得 x，再按原约束逐条回算实际取值。
 *
 * ## 数值与终止
 *   · 主元/判据容差 `PIVOT_TOL = 1e-9`；可行性残差容差 `FEAS_TOL = 1e-7`；
 *   · 进基用 **Bland 规则**（取最小下标），比值并列时同样取基变量下标更小者 ——
 *     牺牲一点速度，换「不会循环、一定终止」的确定性；
 *   · 迭代上限 `maxIterations`（缺省 `max(2000, 40·(列数+行数))`）。超限返回
 *     `iteration_limit`，**绝不返回近似解** ——「没能验证」不等于「算出来了」；
 *   · 每轮迭代**重算**基变量取值（O(m·N)），不做增量维护：用一点算力换掉一整类
 *     累加漂移缺陷（本项目在别处已有「增量维护导致静默失真」的先例）。
 *
 * ## 对偶值 / 影子价格（F3）
 * 最优解同时给出两类边际量，二者都**不是**再解一遍，而是从最终单纯形表读出的：
 *   · `shadowPrices[k]` = ∂(最优目标值)/∂(第 k 条约束**绑定侧**右端)；
 *   · `variableMarginals[j]` = 变量 j 停在界上时 ∂(目标值)/∂(该侧界)，即 reduced cost。
 * 读完立刻做**双路径交叉自检**：同一条 reduced cost 分别走「表路径」（`c_B B⁻¹` 与最终表列）
 * 与「代数路径」（构造时冻结的行系数 `Aᵀy`）。两条路任何一条被污染（切片错位、行/列错位、
 * 人工列位置漂移）都会立刻分歧 ⇒ 判 `verify_failed`。**没能验证 ≠ 算出来了。**
 *
 * ⚠ 影子价格是**局部**敏感度：只在「起作用约束集合不变」的小邻域内有效（包络定理的前提）。
 *
 * ## 诚实边界（本版**不做**什么）
 *   · 无预处理、无尺度化：系数跨多个数量级时精度会退化（本项目的量纲差异不大）；
 *   · 不可行诊断（冲突约束清单 / 最小松弛量）在独立模块 `optimizerDiagnose.js`；
 *   · 稠密表：行数上百后主元代价线性上涨（本项目 m 远小于此，不受影响）。
 *
 * 退出语义由调用方（门面）映射：`optimal`→0，`infeasible`/`unbounded`→非 0，
 * `bad_input`→2，`iteration_limit`/`verify_failed`→3（前置条件不足 / 无法验证）。
 */

/** 主元与判据容差 */
const PIVOT_TOL = 1e-9
/** 可行性残差容差（阶段 I 人工变量之和超过它即判不可行） */
const FEAS_TOL = 1e-7

export const LP_STATUS = Object.freeze({
  OPTIMAL: 'optimal',
  INFEASIBLE: 'infeasible',
  UNBOUNDED: 'unbounded',
  ITERATION_LIMIT: 'iteration_limit',
  BAD_INPUT: 'bad_input',
  // 解出来了，但**对偶性自检没通过** ⇒ 这个「最优解」不可信。它是独立出口而不是
  // 塞回 optimal + 一个 ok:false 标志：调用方（`&&` 链、门面）看的是状态，标志会被漏看。
  VERIFY_FAILED: 'verify_failed',
})

const isFiniteNum = (v) => typeof v === 'number' && Number.isFinite(v)

/** 所有非最优出口的公共外壳：对偶面一律为 null，绝不返回「半个」敏感度 */
function nonOptimal(status, message, iterations = 0) {
  return {
    status,
    message,
    x: null,
    objective: null,
    constraintValues: null,
    iterations,
    shadowPrices: null,
    variableMarginals: null,
  }
}

const badInput = (message) => nonOptimal(LP_STATUS.BAD_INPUT, message, 0)

/* ───────────────────────── 内部：表与基变量取值 ───────────────────────── */

/**
 * 重算每个基变量的**实际取值**。
 *
 * 表的语义是代数等式 `Σ_j T[i][j]·x_j = T[i][ncol]`（第 i 行、基列为单位列），
 * 所以基变量值 = 右端 − Σ_{非基 j} T[i][j]·x_j。非基变量的值来自它当前所在的界。
 * ★ 每轮重算而非增量维护：增量式在「翻界 / 主元 / 删行」三处都要各改一遍，
 *   漏一处就是**静默失真**（数值看着合理、其实偏了）。
 */
function basicValues(state) {
  const { T, basis, m, ncol, lo, hi, at } = state
  const xB = new Array(m)
  for (let i = 0; i < m; i++) {
    let v = T[i][ncol]
    for (let j = 0; j < ncol; j++) {
      if (at[j] === 'B') continue
      const xj = at[j] === 'L' ? lo[j] : hi[j]
      if (xj !== 0) v -= T[i][j] * xj
    }
    xB[i] = v
  }
  return xB
}

/** 某个变量的当前取值（基变量查基，非基变量取其所在界） */
function valueOf(state, xB, j) {
  if (state.at[j] === 'B') {
    for (let i = 0; i < state.m; i++) if (state.basis[i] === j) return xB[i]
    // 不变量守卫：`at[j]==='B'` 与 `j ∈ basis` 由构造保证成对出现。
    // 若真被破坏，返回 NaN 让它在下游**大声失败**，而不是静默兜底成 0
    // （一个「看起来合理的 0」正是本项目最怕的静默失真）。
    return NaN
  }
  return state.at[j] === 'L' ? state.lo[j] : state.hi[j]
}

/**
 * 有界变量单纯形主循环（阶段 I / 阶段 II 共用）。
 * @param state  { T, basis, m, ncol, lo, hi, cost, at }
 * @param colFrom 允许进基的列区间（含）
 * @param colTo   允许进基的列区间（含）—— 阶段 II 用它把人工变量列排除在外
 * @returns {{status, iterations}}
 */
function simplexLoop(state, colFrom, colTo, maxIter) {
  const { T, basis, m, ncol, lo, hi, cost, at } = state
  let it = 0
  for (it = 0; it < maxIter; it++) {
    const xB = basicValues(state)

    /* ── 定价：Bland 规则取**最小下标**的可改善非基变量 ── */
    const cb = new Array(m)
    for (let i = 0; i < m; i++) cb[i] = cost[basis[i]]
    let enter = -1
    let dir = 0
    for (let j = colFrom; j <= colTo; j++) {
      if (at[j] === 'B') continue
      if (hi[j] - lo[j] <= PIVOT_TOL) continue   // 定值变量无法移动，进基只会空转
      let rc = cost[j]
      for (let i = 0; i < m; i++) rc -= cb[i] * T[i][j]
      // 在「下界」上只能往上走（rc<0 才改善）；在「上界」上只能往下走（rc>0 才改善）
      if (at[j] === 'L' ? rc < -PIVOT_TOL : rc > PIVOT_TOL) {
        enter = j
        dir = at[j] === 'L' ? 1 : -1
        break
      }
    }
    if (enter < 0) return { status: LP_STATUS.OPTIMAL, iterations: it }

    /* ── 比值检验：θ 的上限来自「基变量撞界」与「进基变量自身走完行程」两处 ── */
    let leaveRow = -1
    let leaveRate = 0
    let ratio = Infinity
    for (let i = 0; i < m; i++) {
      const t = T[i][enter]
      if (Math.abs(t) <= PIVOT_TOL) continue
      const rate = -dir * t                 // 基变量随 θ 的变化率
      let ti
      if (rate < 0) {
        ti = (xB[i] - lo[basis[i]]) / -rate // 下降 ⇒ 撞下界（下界恒有限）
      } else {
        if (!Number.isFinite(hi[basis[i]])) continue // 上升且无上界 ⇒ 不构成限制
        ti = (hi[basis[i]] - xB[i]) / rate
      }
      if (ti < ratio - PIVOT_TOL) {
        ratio = ti
        leaveRow = i
        leaveRate = rate
      } else if (ti <= ratio + PIVOT_TOL && leaveRow >= 0 && basis[i] < basis[leaveRow]) {
        // 并列：Bland 取**基变量下标更小**者（保证不循环）
        leaveRow = i
        leaveRate = rate
      }
    }

    const room = hi[enter] - lo[enter]      // 进基变量自身从一侧界走到另一侧界的行程
    if (leaveRow < 0 || room <= ratio + PIVOT_TOL) {
      // 进基变量先走完自己的行程 ⇒ 只翻界、不换基（基不变 ⇒ 表的代数部分完全不动）
      if (!Number.isFinite(room)) return { status: LP_STATUS.UNBOUNDED, iterations: it }
      at[enter] = dir > 0 ? 'U' : 'L'
      continue
    }

    /* ── 主元：Gauss-Jordan，把 enter 列化为单位列 ── */
    const p = T[leaveRow][enter]
    for (let j = 0; j <= ncol; j++) T[leaveRow][j] /= p
    for (let i = 0; i < m; i++) {
      if (i === leaveRow) continue
      const f = T[i][enter]
      if (f === 0) continue
      const row = T[leaveRow]
      for (let j = 0; j <= ncol; j++) T[i][j] -= f * row[j]
    }
    const leaving = basis[leaveRow]
    at[leaving] = leaveRate < 0 ? 'L' : 'U' // 撞哪侧的界就停在哪侧
    at[enter] = 'B'
    basis[leaveRow] = enter
  }
  return { status: LP_STATUS.ITERATION_LIMIT, iterations: it }
}

/* ───────────────────────── 对外：solveLP ───────────────────────── */

/**
 * 求解 LP。纯函数：不读全局、不写入参、无隐藏状态；同输入必得同输出。
 * @param {object} problem
 * @param {number[]} problem.c                 目标系数（最小化），长度 = 变量数 n
 * @param {Array<{a:number[],lower?:number,upper?:number}>} [problem.constraints]
 *        线性约束：a 长度必须等于 n；lower/upper 至少给一个（都给且相等 ⇒ 等式）
 * @param {Array<{lower?:number,upper?:number}>} [problem.bounds]
 *        变量界：缺省 lower=0、upper=+∞；长度给定时必须等于 n
 * @param {number} [problem.maxIterations]     迭代上限
 * @returns {{status:string, message:string, x:number[]|null, objective:number|null,
 *            constraintValues:Array|null, iterations:number,
 *            shadowPrices:Array|null, variableMarginals:Array|null}}
 *          `shadowPrices` / `variableMarginals` **只在 optimal 时非 null**；
 *          其余出口一律为 null（不给「半个」敏感度）。
 */
export function solveLP(problem) {
  /* ---------- ① 输入校验（一切不合法输入都返回 bad_input，由门面映射为 exit 2） ---------- */
  if (!problem || typeof problem !== 'object') return badInput('求解输入必须是对象')
  const c = problem.c
  if (!Array.isArray(c) || c.length === 0) return badInput('目标系数 c 必须是非空数组')
  const n = c.length
  for (let j = 0; j < n; j++) if (!isFiniteNum(c[j])) return badInput(`目标系数 c[${j}] 不是有限数`)

  const rawConstraints = problem.constraints === undefined ? [] : problem.constraints
  if (!Array.isArray(rawConstraints)) return badInput('constraints 必须是数组')
  const rawBounds = problem.bounds === undefined ? [] : problem.bounds
  if (!Array.isArray(rawBounds)) return badInput('bounds 必须是数组')
  if (rawBounds.length > 0 && rawBounds.length !== n) {
    return badInput(`bounds 长度 ${rawBounds.length} 与变量数 ${n} 不符`)
  }

  // 变量界：下界必须有限（单纯形只接受有限下界），上界可缺省为 +∞
  const lb = new Array(n).fill(0)
  const room = new Array(n).fill(Infinity)   // 平移后的行程 ub − lb
  for (let j = 0; j < n; j++) {
    const b = rawBounds[j] || {}
    if (b.lower !== undefined && b.lower !== null) {
      if (!isFiniteNum(b.lower)) return badInput(`bounds[${j}].lower 必须是有限数（不支持 −∞ 下界）`)
      lb[j] = b.lower
    }
    if (b.upper !== undefined && b.upper !== null) {
      if (b.upper !== Infinity && !isFiniteNum(b.upper)) return badInput(`bounds[${j}].upper 必须有限或 +∞`)
      room[j] = b.upper === Infinity ? Infinity : b.upper - lb[j]
    }
    if (room[j] < -PIVOT_TOL) {
      return badInput(`变量 ${j} 的下界 ${lb[j]} 大于上界 ${lb[j] + room[j]}`)
    }
    if (room[j] < 0) room[j] = 0
  }

  /* ---------- ② 构造行：区间约束 → 等式行（+ 一条松弛列） ---------- */
  //   双边 L ≤ a·x ≤ U ：a·x − s = L，s ∈ [0, U−L]
  //   仅上界 a·x ≤ U  ：a·x + s = U，s ∈ [0, +∞)
  //   仅下界 a·x ≥ L  ：a·x − s = L，s ∈ [0, +∞)
  //   等式   a·x = L  ：不加松弛
  // 最后统一平移：把 x = lb + y 代入，右端变成 rhs − Σ a_j·lb_j；右端为负则整行取反。
  const rows = []
  // rawConstraints[k] → rows 的下标（空约束不进表 ⇒ −1）。影子价格要按**原始下标**对齐，
  // 不能用 rows 的下标直接当约束编号（跳过空约束会让二者错位）。
  const rowOf = new Array(rawConstraints.length).fill(-1)
  for (let k = 0; k < rawConstraints.length; k++) {
    const cn = rawConstraints[k]
    if (!cn || typeof cn !== 'object') return badInput(`constraints[${k}] 必须是对象`)
    const a = cn.a
    if (!Array.isArray(a) || a.length !== n) return badInput(`constraints[${k}].a 长度必须等于变量数 ${n}`)
    for (let j = 0; j < n; j++) if (!isFiniteNum(a[j])) return badInput(`constraints[${k}].a[${j}] 不是有限数`)
    const hasLo = cn.lower !== undefined && cn.lower !== null && cn.lower !== -Infinity
    const hasHi = cn.upper !== undefined && cn.upper !== null && cn.upper !== Infinity
    if (!hasLo && !hasHi) continue                                   // 空约束，忽略
    if (hasLo && !isFiniteNum(cn.lower)) return badInput(`constraints[${k}].lower 不是有限数`)
    if (hasHi && !isFiniteNum(cn.upper)) return badInput(`constraints[${k}].upper 不是有限数`)
    const lower = hasLo ? cn.lower : -Infinity
    const upper = hasHi ? cn.upper : Infinity
    if (hasLo && hasHi && lower > upper + PIVOT_TOL) {
      return badInput(`constraints[${k}] 的下界 ${lower} 大于上界 ${upper}`)
    }

    let slackSign = 0        // 0 = 不加松弛
    let slackRoom = Infinity
    let rhs = 0
    // side = 上式的右端取自哪一侧 —— 影子价格的语义是 ∂obj/∂(这一侧)，必须记下来，
    // 否则调用方无从知道「每单位」加在哪边。
    let side = 'lower'
    if (hasLo && hasHi && lower === upper) {
      rhs = lower
      side = 'equality'
    } else if (hasLo && hasHi) {
      slackSign = -1; slackRoom = upper - lower; rhs = lower
      side = 'lower'
    } else if (hasHi) {
      slackSign = 1; slackRoom = Infinity; rhs = upper
      side = 'upper'
    } else {
      slackSign = -1; slackRoom = Infinity; rhs = lower
      side = 'lower'
    }
    rowOf[k] = rows.length
    rows.push({ a, slackSign, slackRoom, rhs, side, slackIdx: -1 })
  }

  const m = rows.length
  const nSlack = rows.reduce((s, r) => s + (r.slackSign === 0 ? 0 : 1), 0)
  const N = n + nSlack             // 真实列数（结构变量 + 松弛）
  const ncol = N + m               // 阶段 I 的列数（含人工列）
  const rhsCol = ncol              // 右端所在列下标

  // 列布局：0..n−1 = 结构变量；n..N−1 = 松弛；N..ncol−1 = 人工
  const T = []
  const lo = new Array(ncol)
  const hi = new Array(ncol)
  const at = new Array(ncol)
  const basis = new Array(m)
  for (let j = 0; j < n; j++) { lo[j] = 0; hi[j] = room[j] }
  // 两套目标：阶段 I 只最小化人工变量之和（真实列系数必须为 0，否则阶段 I 会
  // 提前「没有可改善方向」而停在一个残差不为 0 的点 ⇒ 把可行问题误判成不可行）；
  // 阶段 II 才用原始 c。两者分开构造，不复用同一个数组。
  const costI = new Array(ncol).fill(0)
  const costII = new Array(N).fill(0)
  for (let j = 0; j < n; j++) costII[j] = c[j]
  // 冻结两份对偶自检要用的量（见 §对偶值）：
  //   Aprime[i] = 表坐标系下第 i 行的**真实列**系数（平移 + 可能的整行取反之后），长度 N；
  //   sign[i]   = 该行是否被取反，影子价格要由表坐标系换回原始约束右端，靠它定符号。
  const Aprime = []
  const sign = new Array(m).fill(1)

  let slackCol = n
  for (let i = 0; i < m; i++) {
    const r = rows[i]
    const row = new Array(ncol + 1).fill(0)
    let shift = 0
    for (let j = 0; j < n; j++) {
      row[j] = r.a[j]
      shift += r.a[j] * lb[j]
    }
    if (r.slackSign !== 0) {
      row[slackCol] = r.slackSign
      lo[slackCol] = 0
      hi[slackCol] = r.slackRoom
      r.slackIdx = slackCol                        // 记下来：双边约束靠它判断最终绑在哪一侧
      slackCol += 1
    }
    let rhs = r.rhs - shift
    if (rhs < 0) {                                   // 整行取反，保证人工变量初值 ≥ 0
      for (let j = 0; j <= ncol; j++) row[j] = -row[j]
      rhs = -rhs
      sign[i] = -1
    }
    row[rhsCol] = rhs
    row[N + i] = 1                                   // 人工列
    lo[N + i] = 0
    hi[N + i] = Infinity
    costI[N + i] = 1                                 // 阶段 I 目标 = 人工变量之和
    T.push(row)
    Aprime.push(row.slice(0, N))                     // 必须在取反**之后**冻结
    basis[i] = N + i
  }
  for (let j = 0; j < ncol; j++) at[j] = j >= N ? 'B' : 'L'

  const maxIter = isFiniteNum(problem.maxIterations) && problem.maxIterations > 0
    ? Math.floor(problem.maxIterations)
    : Math.max(2000, 40 * (ncol + m))

  /* ---------- ③ 阶段 I ---------- */
  const state = { T, basis, m, ncol, lo, hi, cost: costI, at }
  const phase1 = simplexLoop(state, 0, ncol - 1, maxIter)
  let iterations = phase1.iterations
  if (phase1.status === LP_STATUS.ITERATION_LIMIT) {
    return nonOptimal(LP_STATUS.ITERATION_LIMIT,
      `阶段 I 达到迭代上限 ${maxIter}，未能判定可行性（不予近似解）`, iterations)
  }
  {
    const xB = basicValues(state)
    let infeas = 0
    for (let i = 0; i < m; i++) if (basis[i] >= N) infeas += xB[i]
    if (infeas > FEAS_TOL) {
      return nonOptimal(LP_STATUS.INFEASIBLE,
        `原问题不可行：阶段 I 最小残差 ${infeas.toExponential(3)} > 容差 ${FEAS_TOL}`, iterations)
    }
  }

  /* ---------- ④ 人工变量出基；找不到主元 ⇒ 该行冗余，连行删掉 ---------- */
  const keep = []
  for (let i = 0; i < m; i++) {
    if (basis[i] < N) { keep.push(i); continue }
    let pj = -1
    for (let j = 0; j < N; j++) {
      if (at[j] === 'B') continue
      if (Math.abs(T[i][j]) > PIVOT_TOL) { pj = j; break }
    }
    if (pj < 0) continue                             // 冗余行：恒为 0 = 0，删除不损失约束力
    const p = T[i][pj]
    for (let j = 0; j <= ncol; j++) T[i][j] /= p
    for (let r = 0; r < m; r++) {
      if (r === i) continue
      const f = T[r][pj]
      if (f === 0) continue
      const src = T[i]
      for (let j = 0; j <= ncol; j++) T[r][j] -= f * src[j]
    }
    at[basis[i]] = 'L'                               // 人工变量退为非基，停在 0
    at[pj] = 'B'
    basis[i] = pj
    keep.push(i)
  }
  // 阶段 II 的表：只留保留下来的行，但**保留全部列（含人工列）**。
  //   人工列在初始表里就是单位向量 e_i；最终表里它变成 `B₂⁻¹e_i`，于是对偶乘子
  //   `y = c_{B₂}ᵀ B₂⁻¹` 可以直接读：`y_i = Σ_r c_{B₂[r]} · T2[r][N+i]`。
  //   保留人工列**不影响迭代**：阶段 II 的进基列区间是 [0, N−1]，人工列永不进基
  //   （它停在界 0 上，只在主元时被动更新）。
  // ⚠ 右端**不在**第 N 列 —— 它在第 ncol 列（= N + m，人工列之后）。上一版按
  //   `slice(0, N+1)` 取「真实列 + 右端」，实际取到的是「真实列 + 第 0 个人工列」，
  //   阶段 II 于是拿着一张自相矛盾的表继续迭代（症状：可行但次优 / 286 规模迭代打满）。
  //   现在整行拷贝，右端列下标天然对得上（state2.ncol = ncol）。这条注释是防回归的锚。
  const T2 = keep.map((i) => T[i].slice())
  const basis2 = keep.map((i) => basis[i])
  const m2 = keep.length

  /* ---------- ⑤ 阶段 II ---------- */
  const state2 = { T: T2, basis: basis2, m: m2, ncol, lo, hi, cost: costII, at }
  const phase2 = m2 === 0
    ? { status: LP_STATUS.OPTIMAL, iterations: 0 }
    : simplexLoop(state2, 0, N - 1, maxIter)
  iterations += phase2.iterations
  if (phase2.status !== LP_STATUS.OPTIMAL) {
    const msg = phase2.status === LP_STATUS.UNBOUNDED
      ? '原问题无界：目标可无限下降（请检查变量上界或约束是否缺失）'
      : `阶段 II 达到迭代上限 ${maxIter}，未能求得最优（不予近似解）`
    return nonOptimal(phase2.status, msg, iterations)
  }

  /* ---------- ⑥ 逆平移取解 + 按原约束回算 ---------- */
  const xB2 = basicValues(state2)
  const x = new Array(n)
  for (let j = 0; j < n; j++) x[j] = valueOf(state2, xB2, j) + lb[j]
  let objective = 0
  for (let j = 0; j < n; j++) objective += c[j] * x[j]

  const constraintValues = rawConstraints.map((cn) => {
    const a = cn.a
    const v = a.reduce((s, av, j) => s + av * x[j], 0)
    const hasLo = cn.lower !== undefined && cn.lower !== null && cn.lower !== -Infinity
    const hasHi = cn.upper !== undefined && cn.upper !== null && cn.upper !== Infinity
    return {
      lower: hasLo ? cn.lower : null,
      upper: hasHi ? cn.upper : null,
      value: v,
      feasible: (!hasLo || v >= cn.lower - FEAS_TOL) && (!hasHi || v <= cn.upper + FEAS_TOL),
    }
  })

  /* ---------- ⑦ 对偶值 / 影子价格 + 双路径交叉自检 ---------- */
  // ① 对偶乘子 y：`y_i = Σ_r c_{B₂[r]}·(B₂⁻¹)_{r,i}`，而 `(B₂⁻¹)_{r,i} = T2[r][N+i]`
  //    （因为初始人工列 N+i 就是单位向量 e_i）。被剔除的冗余行不参与求和，且它在
  //    保留行上的人工列恒为 0（阶段 I 结束时它是第 i 行的基列 ⇒ 别的行上为 0；阶段 II
  //    的行操作只在保留行之间做，保留下来的也是 0）⇒ 该行 y_i = 0，与「冗余约束不限制
  //    任何可行点、影价就是 0」相符。
  const y = new Array(m).fill(0)
  for (let r = 0; r < m2; r++) {
    const cbr = costII[basis2[r]]
    if (cbr === 0) continue
    const row = T2[r]
    for (let i = 0; i < m; i++) y[i] += cbr * row[N + i]
  }

  // ② 变量边际（reduced cost）：基变量恒为 0；非基变量停在下界 ⇒ rc ≥ 0 且
  //    rc = ∂obj/∂该下界；停在上界 ⇒ rc ≤ 0 且 rc = ∂obj/∂该上界。
  const reducedCost = new Array(N).fill(0)
  for (let j = 0; j < N; j++) {
    let s = costII[j]
    for (let r = 0; r < m2; r++) s -= costII[basis2[r]] * T2[r][j]
    reducedCost[j] = s
  }

  // ③ **对偶性自检**：同一条 reduced cost 走两条互不相干的路径 ——
  //    表路径（上式，读最终表的列）与代数路径（`c_j − Σ_i y_i·A_ij`，用构造时冻结、
  //    已含取反的行系数）。任何一处错位（切片、行列、人工列位置漂移）都会让二者分歧。
  //    分歧 ⇒ 判「无法验证」，绝不把可能错的对偶量交给调用方。
  //    ⚠ 它的**盲区**必须说清：两条路径共用同一个 y，所以「y 本身算错」它抓不到 ——
  //      验证 y 的判据只能来自外部（守卫用有限差分扰动右端重解来对斜率）。
  {
    let bad = -1
    let badDiff = 0
    for (let j = 0; j < N; j++) {
      let s = costII[j]
      for (let i = 0; i < m; i++) s -= y[i] * Aprime[i][j]
      const scale = Math.max(1, Math.abs(s), Math.abs(reducedCost[j]))
      const d = Math.abs(s - reducedCost[j])
      // ⚠ 必须显式查 isFinite：`NaN > tol` 恒为 **false** ⇒ 一旦某条路径产出 NaN
      //   （列数错位、系数缺失），只写 `d > tol` 的判据会**静默放行**，把自检变成摆设。
      if (!Number.isFinite(s) || !Number.isFinite(d) || d > 1e-7 * scale) { bad = j; badDiff = d; break }
    }
    if (bad >= 0) {
      return nonOptimal(LP_STATUS.VERIFY_FAILED,
        `对偶性自检未通过：第 ${bad} 列的 reduced cost 在「最终表」与「冻结行系数」`
        + `两条路径上不一致（偏差 ${Number.isFinite(badDiff) ? badDiff.toExponential(3) : 'NaN'}）`
        + '—— 最优解不予采信（没能验证 ≠ 算出来了）',
        iterations)
    }
  }

  // ④ 影子价格：按**原始约束下标**对齐（空约束 / 已剔除的冗余行 ⇒ 0）。
  //    只对「绑定侧」有意义：不绑定的约束由互补松弛给出 0（退化时可能非唯一，此处取表给出的值）。
  const shadowPrices = rawConstraints.map((cn, k) => {
    const i = rowOf[k]
    if (i < 0) return { index: k, side: null, value: 0, binding: false, activity: null }
    const cv = constraintValues[k]
    const row = rows[i]
    let side = row.side
    // ⚠ 双边约束的 rhs 记的是**下界** L，但最优可能顶在**上界** U 上。这时把敏感度
    //   归到 L 是错的：L 一侧完全不起作用，动 L 只会连带动 s 的上界 U−L，对最优解毫无
    //   影响（有限差分 = 0），而形式上算出的 y 其实是「U 侧」的乘子（符号也对得上）。
    //   所以看松弛变量最终停在哪一侧：停在上界 ⇒ 被顶住的是 U ⇒ 敏感度归 U。
    if (side === 'lower' && cn.upper !== undefined && cn.upper !== null
      && row.slackIdx >= 0 && at[row.slackIdx] === 'U') {
      side = 'upper'
    }
    let activity
    if (side === 'equality') activity = 0
    else if (side === 'lower') activity = cv.value - cv.lower
    else activity = cv.upper - cv.value
    const ref = Math.max(1, Math.abs(side === 'upper' ? cv.upper : cv.lower))
    return {
      index: k,
      side,
      // 表坐标系 → 原始约束右端：行被取反过则乘 −1（否则敏感度符号会整体反掉）。
      value: sign[i] * y[i],
      binding: Math.abs(activity) <= 1e-7 * ref,
      activity,
    }
  })

  const variableMarginals = new Array(n)
  for (let j = 0; j < n; j++) {
    variableMarginals[j] = {
      index: j,
      at: at[j] === 'B' ? 'basic' : (at[j] === 'L' ? 'lower' : 'upper'),
      value: x[j],
      reducedCost: reducedCost[j],
    }
  }

  return {
    status: LP_STATUS.OPTIMAL,
    message: '已求得最优解',
    x,
    objective,
    constraintValues,
    iterations,
    shadowPrices,
    variableMarginals,
  }
}
