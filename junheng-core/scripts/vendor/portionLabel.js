/**
 * 分装排期 + 分装标签（批 8 · 节点 5 · N3-b）。
 *
 * ## 定位
 * **纯函数、零依赖、零新公式**。上游只喂一个数：某只宠物（或某个配方）的**每日用量**
 * （克/日，来自 `feedingGuide.computeFeedingPlan()` 或 `multiPetPlan.purchaseFromPets()`
 * 的 `gramsPerDay`）。本模块把它拆成「一袋能吃几天」的分装排期，并出可打印的分装标签。
 *
 * ## 为什么不是复用 labeling.js
 * `src/lib/labeling.js` 是**合规标签底稿**：保证值表、配料表、合规风险提示，
 * 受 `LABEL_FORMAT_VERSION` 约束，面向**监管与消费者**。
 * 分装标签是**厨房贴纸**：配方名 / 每份克数 / 分装日期 / 建议食用期限 / 解冻提示，
 * 面向**当天分装的人**。两者的字段几乎不相交 ⇒ 分装标签**新建**，不复用 labeling ——
 * 把「厨房贴纸」塞进合规底稿会稀释 labeling 的合规语义（原文「复用 labeling 模板」的假设已实测证伪）。
 *
 * ## 四条不静默红线
 * 1. **不猜保质期**。「建议食用期限 = 分装日期 + 保质期」里的**保质期必须由调用方给**；
 *    缺失时 `useByDate = null` 并标 `shelfLifeMissing` —— 拿「冷冻一般能放 90 天」这类
 *    经验值填数，就是把猜想印在贴纸上，而用户会照着它决定还吃不吃。
 * 2. **克数守恒**。Σ(每袋克数) 必须 == 总量。末袋吸收舍入余量；若各袋都独立四舍五入，
 *    「分装后总量少了几克」这件事没有任何人会察觉。
 * 3. **末袋天数不足必须显式**。总量 30 天 ÷ 每袋 7 天 = 4 袋零 2 天 ⇒ 末袋只覆盖 2 天，
 *    标 `partial:true`。假装每袋都是整周，会让「最后一袋吃到哪天」算错。
 * 4. **总量为 0/负 ⇒ 报错，不返回空排期**。空排期会被读成「已经分好了」，
 *    而事实是「没有任何东西可分」。
 *
 * ## 与 multiPetPlan.js 的口径耦合（不 import，靠守卫钉住）
 * `TOTAL_DAYS_DEFAULT` 与 `multiPetPlan.PURCHASE_DAYS_DEFAULT` 是**同一个口径**
 * （30 天 ≈ 一个月）。本模块保持零依赖，故不 import 而是各自常量 + 由守卫断言两者相等 ——
 * 将来任一侧改动，守卫立刻判红，不会静默分叉。
 */

/* ================= 1. 常量 ================= */

/** 分装标签格式版本（改字段口径/排版时必须同步递增，便于回溯历史贴纸） */
export const PORTION_LABEL_VERSION = 1

/** 每袋默认覆盖天数：**按周分装**（对齐 feedingGuide.js 既有文案「按一周用量分装小袋」） */
export const PORTION_DAYS_DEFAULT = 7
/** 每袋天数上限（超过一季没有实际意义，只会让袋数与贴纸数失控） */
export const PORTION_DAYS_MAX = 90

/** 总量覆盖天数默认：30 天 ≈ 一个月（与 multiPetPlan 采购口径同值，守卫钉住） */
export const TOTAL_DAYS_DEFAULT = 30
/** 总量覆盖天数上限（超过一年只会放大估算误差） */
export const TOTAL_DAYS_MAX = 365

/** 形态 → 解冻/保存提示。给不出形态时**不给默认值**，明说请按实际填写。 */
export const FORM_TIPS = {
  frozen_raw: '生食：全程冷链（-18℃ 冷冻）；解冻在冷藏层进行，解冻后 24 小时内吃完，不要反复冻融',
  frozen_cooked: '熟食（冷冻）：提前移到冷藏层解冻，回温至室温再喂；解冻后 24 小时内吃完',
  dry: '干粮：无需解冻；开封后密封、置于阴凉干燥处，避免受潮与阳光直射',
  wet: '湿粮：无需冷冻；开封后冷藏并在 24 小时内用完，常温放置不宜超过 1 小时',
  unknown: '保存与解冻方式请按本产品实际形态填写（未提供形态——本模块不代填）',
}

/** 形态 key → 中文名（进标签正文） */
export const FORM_LABELS = {
  frozen_raw: '生食（冷冻）',
  frozen_cooked: '熟食（冷冻）',
  dry: '干粮',
  wet: '湿粮',
  unknown: '未指定',
}

/* ================= 2. 小工具 ================= */

const num = (v) => (Number.isFinite(Number(v)) ? Number(v) : 0)
const str = (v) => (typeof v === 'string' ? v.trim() : '')
const r2 = (n) => Math.round(n * 100) / 100
const r0 = (n) => Math.round(n)

const ISO_RE = /^(\d{4})-(\d{2})-(\d{2})$/

/** 严格解析 `YYYY-MM-DD`；非法日期（如 2026-02-30）返回 null，不静默规范化 */
function parseIso(s) {
  const m = ISO_RE.exec(str(s))
  if (!m) return null
  const y = Number(m[1]); const mo = Number(m[2]); const d = Number(m[3])
  const dt = new Date(Date.UTC(y, mo - 1, d))
  // Date 会把 2026-02-30 规范化成 03-02 —— 回读比对才能挡住「不存在的日期」
  if (dt.getUTCFullYear() !== y || dt.getUTCMonth() !== mo - 1 || dt.getUTCDate() !== d) return null
  return dt
}

function fmtIso(dt) {
  const y = dt.getUTCFullYear()
  const m = String(dt.getUTCMonth() + 1).padStart(2, '0')
  const d = String(dt.getUTCDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

/** `YYYY-MM-DD` 合法则原样返回，否则 null */
export function validIso(v) {
  const dt = parseIso(v)
  return dt ? fmtIso(dt) : null
}

/**
 * 日期加减（**纯日期**口径，用 UTC 运算避开夏令时把某天变成 23/25 小时的坑）。
 * `2026-10-31 + 1` ⇒ `2026-11-01`（跨月）；`2026-12-31 + 1` ⇒ `2027-01-01`（跨年）。
 * 输入非法 ⇒ 返回 null（调用方须显式处理，不给「就当是今天」的隐形兜底）。
 */
export function addDaysIso(iso, n) {
  const dt = parseIso(iso)
  if (!dt) return null
  dt.setUTCDate(dt.getUTCDate() + r0(num(n)))
  return fmtIso(dt)
}

/**
 * 「今天」= **本地日期**。分装日期是用户认知里的当天；若服务器在 UTC，
 * 东八区清晨用 UTC 会算出「昨天」，贴纸日期就错了。
 * 参数 `now` 仅为可测性（守卫传入固定时刻）。
 */
export function todayIso(now = new Date()) {
  const y = now.getFullYear()
  const m = String(now.getMonth() + 1).padStart(2, '0')
  const d = String(now.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

function clampPortionDays(v) {
  const d = Number(v)
  if (!Number.isFinite(d) || d <= 0) return PORTION_DAYS_DEFAULT
  return Math.min(Math.max(1, r0(d)), PORTION_DAYS_MAX)
}

function clampTotalDays(v) {
  const d = Number(v)
  if (!Number.isFinite(d) || d <= 0) return TOTAL_DAYS_DEFAULT
  return Math.min(Math.max(1, r0(d)), TOTAL_DAYS_MAX)
}

function normForm(v) {
  const k = str(v)
  return Object.prototype.hasOwnProperty.call(FORM_TIPS, k) ? k : 'unknown'
}

/* ================= 3. 分装排期 ================= */

/**
 * 把总量按「每袋 N 天」拆成若干袋。
 *
 * @param {number} totalGrams 总量（克）
 * @param {{days?:number, portionDays?:number, startDate?:string}} [opts]
 *   days      总量覆盖天数（默认 30）
 *   portionDays 每袋覆盖天数（默认 7 = 按周）
 *   startDate  首袋起始日 `YYYY-MM-DD`（默认今天）
 * @returns {{ok:boolean, reason:string, days:number, portionDays:number, startDate:string,
 *            portionCount:number, totalGrams:number, portions:Array, note:string[], warnings:string[]}}
 */
export function portionSchedule(totalGrams, opts = {}) {
  const total = num(totalGrams)
  const days = clampTotalDays(opts.days)
  const portionDays = clampPortionDays(opts.portionDays)
  const startDate = validIso(opts.startDate) || todayIso(opts.now)
  const warnings = []
  const note = []

  if (opts.startDate && !validIso(opts.startDate)) {
    warnings.push(`起始日期「${str(opts.startDate)}」不是合法 YYYY-MM-DD，已按今天（${startDate}）处理`)
  }

  /* 红线 4：总量必须为正。返回空排期会被误读成「已分好」 */
  if (!(total > 0)) {
    return {
      ok: false,
      reason: '总量必须大于 0 克：0 克没有可分装的内容（返回空排期会被误读成「已经分好了」）',
      days, portionDays, startDate,
      portionCount: 0, totalGrams: 0,
      portions: [], note, warnings,
    }
  }

  /* 份数 = ceil(days / portionDays)；days ≤ portionDays 时只有 1 袋 */
  const count = Math.max(1, Math.ceil(days / portionDays))
  const portions = []
  let acc = 0
  for (let i = 0; i < count; i++) {
    const covered = Math.min(portionDays, days - i * portionDays)
    const isLast = i === count - 1
    // 红线 2：末袋吸收舍入余量 ⇒ Σ(grams) === total（其他袋按天数比例独立取整）
    const grams = isLast ? r2(total - acc) : r2((total * covered) / days)
    acc = r2(acc + grams)
    const segStart = addDaysIso(startDate, i * portionDays)
    portions.push({
      seq: i + 1,
      label: `第 ${i + 1} 袋`,
      daysCovered: covered,
      grams,
      startDate: segStart,
      endDate: addDaysIso(segStart, covered - 1), // 含首含尾
      // 红线 3：末袋覆盖天数不足时必须显式标出
      partial: covered < portionDays,
    })
  }

  const last = portions[portions.length - 1]
  note.push('先分装的先吃：请按「第 N 袋」顺序取用，避免来回翻找反复开合')
  if (last.partial) {
    note.push(`末袋只覆盖 ${last.daysCovered} 天（不足 ${portionDays} 天）—— 这是 ${days} 天 ÷ 每袋 ${portionDays} 天的余数，不是算错`)
  }

  return {
    ok: true,
    reason: '',
    days, portionDays, startDate,
    portionCount: count,
    totalGrams: r2(total),
    portions,
    note,
    warnings,
  }
}

/* ================= 4. 分装标签 ================= */

/**
 * 单个分装标签。
 *
 * @param {{recipeName?:string, name?:string, petLabel?:string, pet?:string,
 *          grams?:number, daysCovered?:number, seq?:number, portionCount?:number,
 *          filledDate?:string, now?:Date, shelfLifeDays?:number, form?:string}} input
 * @returns {{version:number, recipeName:string, petLabel:string, seq:number|null,
 *            portionCount:number|null, grams:number, daysCovered:number|null,
 *            filledDate:string, shelfLifeDays:number|null, useByDate:string|null,
 *            shelfLifeMissing:boolean, form:string, formLabel:string,
 *            thawNote:string, warnings:string[]}}
 */
export function buildPortionLabel(input = {}) {
  const recipeName = str(input.recipeName) || str(input.name)
  const petLabel = str(input.petLabel) || str(input.pet)
  const grams = r2(num(input.grams))
  const warnings = []

  /* 分装日期：给了但非法 ⇒ 用今天并告警（不静默） */
  const given = input.filledDate
  const parsed = validIso(given)
  if (given && !parsed) {
    warnings.push(`分装日期「${str(given)}」不是合法 YYYY-MM-DD，已按今天处理`)
  }
  const filledDate = parsed || todayIso(input.now)

  /* 红线 1：保质期只能由调用方给，缺失就留空 + 告警，绝不代填 */
  const shelfRaw = Number(input.shelfLifeDays)
  const hasShelf = Number.isFinite(shelfRaw) && shelfRaw > 0
  const shelfLifeDays = hasShelf ? r0(shelfRaw) : null
  const useByDate = hasShelf ? addDaysIso(filledDate, shelfLifeDays) : null
  if (!hasShelf) {
    warnings.push('未提供保质期天数 ⇒「建议食用期限」留空（本模块不猜保质期，请按产品实际保质期填写）')
  }

  const form = normForm(input.form)
  const daysCovered = Number.isFinite(Number(input.daysCovered)) && Number(input.daysCovered) > 0
    ? r0(Number(input.daysCovered)) : null

  return {
    version: PORTION_LABEL_VERSION,
    recipeName: recipeName || '（未填配方名）',
    petLabel,
    seq: Number.isFinite(Number(input.seq)) ? r0(Number(input.seq)) : null,
    portionCount: Number.isFinite(Number(input.portionCount)) ? r0(Number(input.portionCount)) : null,
    grams,
    daysCovered,
    filledDate,
    shelfLifeDays,
    useByDate,
    shelfLifeMissing: !hasShelf,
    form,
    formLabel: FORM_LABELS[form],
    thawNote: FORM_TIPS[form],
    warnings: [...warnings],
  }
}

/**
 * 渲染成可直接打印的纯文本贴纸。
 * 食用期限缺失时**不写日期**，写「待定 + 原因」—— 空着一个字段比印个假日期好。
 */
export function renderPortionLabelText(label) {
  const l = label || {}
  const seqTxt = l.seq != null ? `（第 ${l.seq}${l.portionCount != null ? `/${l.portionCount}` : ''} 袋）` : ''
  const perTxt = l.daysCovered != null
    ? `${l.grams} 克（${l.daysCovered} 天量）`
    : `${l.grams} 克`
  const useBy = l.useByDate
    ? `${l.useByDate}（分装后 ${l.shelfLifeDays} 天）`
    : '待定（未提供保质期，请按产品实际保质期填写）'
  const lines = [
    '································',
    `配方：${l.recipeName}${seqTxt}`,
    l.petLabel ? `宠物：${l.petLabel}` : null,
    `每份：${perTxt}`,
    `分装日期：${l.filledDate}`,
    `建议食用期限：${useBy}`,
    `保存/解冻：${l.thawNote}`,
    '································',
  ]
  return lines.filter((x) => x != null).join('\n')
}

/* ================= 5. 批量（同日分装） ================= */

/**
 * 同日分装：多条（多宠/多配方）**在同一天**完成分装 ⇒ 共用 `filledDate`。
 *
 * @param {Array<{recipeName?:string, petLabel?:string, gramsPerDay?:number, dailyGrams?:number}>} entries
 * @param {{days?:number, portionDays?:number, filledDate?:string, now?:Date,
 *          shelfLifeDays?:number, form?:string}} [opts]
 */
export function computePortionLabels(entries = [], opts = {}) {
  const days = clampTotalDays(opts.days)
  const portionDays = clampPortionDays(opts.portionDays)
  const filledDate = validIso(opts.filledDate) || todayIso(opts.now)
  const form = normForm(opts.form)
  const warnings = []
  const note = []
  const labels = []
  const schedules = []

  const list = Array.isArray(entries) ? entries : []
  if (!list.length) {
    return {
      computed: false,
      reason: '没有分装条目：至少给一只宠物的每日用量（克/日）才能排期与出标签',
      filledDate, days, portionDays, form,
      labels: [], schedules: [], warnings, note,
    }
  }

  if (opts.filledDate && !validIso(opts.filledDate)) {
    warnings.push(`分装日期「${str(opts.filledDate)}」不是合法 YYYY-MM-DD，已按今天（${filledDate}）处理`)
  }

  /* 红线 1 上浮：保质期缺失不能只藏在每张标签的 warnings 里 ——
     调用方（CLI / 界面）看的是本函数的 warnings，埋进 labels[i] 就等于没人看见。 */
  if (!(Number.isFinite(Number(opts.shelfLifeDays)) && Number(opts.shelfLifeDays) > 0)) {
    warnings.push('未提供保质期天数（shelfLifeDays）⇒ 全部标签的「建议食用期限」留空，请按产品实际保质期填写后再打印')
  }

  for (let i = 0; i < list.length; i++) {
    const e = list[i] || {}
    const recipeName = str(e.recipeName) || str(e.name)
    const petLabel = str(e.petLabel) || str(e.pet) || (recipeName ? '' : `条目 ${i + 1}`)
    const daily = num(e.gramsPerDay != null ? e.gramsPerDay : e.dailyGrams)
    const total = r2(daily * days)

    const sch = portionSchedule(total, { days, portionDays, startDate: filledDate })
    schedules.push({
      recipeName: recipeName || '（未填配方名）',
      petLabel,
      gramsPerDay: r2(daily),
      totalGrams: r2(total),
      portionCount: sch.ok ? sch.portionCount : 0,
      ok: sch.ok,
      reason: sch.reason,
    })

    if (!sch.ok) {
      warnings.push(`「${recipeName || petLabel || `条目 ${i + 1}`}」无法分装：${sch.reason}`)
      continue
    }

    for (const p of sch.portions) {
      labels.push(buildPortionLabel({
        recipeName,
        petLabel,
        grams: p.grams,
        daysCovered: p.daysCovered,
        seq: p.seq,
        portionCount: sch.portionCount,
        filledDate,
        shelfLifeDays: opts.shelfLifeDays,
        form,
      }))
    }
  }

  if (labels.length) {
    note.push(`同日分装：全部 ${labels.length} 张标签共用分装日期 ${filledDate}（食用期限均由此起算）`)
    note.push('每袋克数是「每日用量 × 覆盖天数」按比例折算，Σ 等于该宠总量（末袋吸收舍入余量）')
  }

  return {
    computed: labels.length > 0,
    reason: labels.length ? '' : '所有条目都未能分装（每日用量为 0 或缺失）',
    filledDate, days, portionDays, form,
    labels,
    schedules,
    warnings,
    note,
  }
}
