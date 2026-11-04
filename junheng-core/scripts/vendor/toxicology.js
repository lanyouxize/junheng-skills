/**
 * 安全判定内核（四态）—— `junheng-safety` 安全闸的**纯函数层**。
 *
 * ## 四态语义（★ 与 `nutrition.js` 的 ok/fail/low/nodata 是不同体系，勿混）
 *   `banned`   命中禁用条目 ⇒ 该配方**不得给出**
 *   `caution`  命中慎用条目 ⇒ 可用，但必须先满足 `conditions`
 *   `ok`       **仅在显式安全声明命中时**才返回
 *   `unknown`  未收录 ⇒ **无法判定**（≠ 安全，也 ≠ 不安全）
 *
 * ## 铁律：未收录一律 `unknown`，绝不 `ok`
 * 这是本模块存在的全部理由。若把「查不到」兜底成 `ok`，安全闸会在
 * **它最该拦住的场景**（新原料、别名没覆盖、拼写变体）静默放行。
 * 守卫 `safety-recall-test.mjs` 会构造该变异并判红。
 *
 * ## 匹配口径（可复现，非「看着像」）
 *   · 中文别名 → 归一（小写 + 去空白）后**包含**匹配
 *   · 英文别名 → **词边界**匹配（`\b` 级），避免 `nut` 命中 `nutrition`、
 *     `tea` 命中 `steam` 这类子串误伤
 *   · 同一输入命中多条 ⇒ 取**最高危**（`banned` 优先于 `caution`）
 *
 * ## 归属
 * 纯函数、零依赖（只读同域数据）。可被测试独立调用，不触碰 DOM / 存储 / 网络。
 */
import { SOURCES, TOXIC_SUBSTANCES, TOXIC_LEVEL_VALUES, TOXIC_CATEGORIES } from '../data/toxicSubstances.js'

// 种子表对门面开放（`list-substances` / `list-sources` 直接要用）。
// 走 re-export 而不是让门面自己加载 data 模块：data 在技能镜像里落 `scripts/data/`，
// 而 `importFromVendor` 只探测 `scripts/vendor/`，门面自取会取不到（前置条件缺失）。
export { SOURCES, TOXIC_SUBSTANCES, TOXIC_LEVEL_VALUES, TOXIC_CATEGORIES }

/** 判定四态（顺序即严重度降序；`unknown` 恒在末位） */
export const TOXIC_LEVELS = ['banned', 'caution', 'ok', 'unknown']

/**
 * 显式安全声明。
 * ⚠ 本轮**为空数组是刻意的**：没有取得权威来源的安全结论，就不声明。
 * 调用方若要引入自有白名单，用 `opts.safeList` 传入，**不要**改这里来放行。
 */
export const SAFE_SUBSTANCES = []

const escapeRegex = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
const stripSpace = (s) => String(s ?? '').toLowerCase().replace(/[\s\u3000]+/g, '')

/** 纯 ASCII 词（可含空格/连字符），走词边界匹配；其余（含中日韩）走包含匹配 */
const isAsciiWord = (s) => /^[a-z0-9][a-z0-9 \-]*$/.test(s)

/** 单个别名是否命中输入 */
function hitAlias(input, alias) {
  const a = String(alias ?? '').trim().toLowerCase()
  if (!a) return false
  const raw = String(input ?? '').toLowerCase()
  if (isAsciiWord(a)) {
    const body = escapeRegex(a).replace(/\\?\s+/g, '\\s+')
    return new RegExp(`(^|[^a-z0-9])${body}(?![a-z0-9])`).test(raw)
  }
  return stripSpace(raw).includes(stripSpace(a))
}

/**
 * 索引：别名 → 条目。
 * 模块加载时构建一次；键是归一后的别名，值是条目数组（同一别名可能归属多条，
 * 例如「葱」既属 allium，但不同条目别名重复时按加入顺序全部保留，判定时取最高危）。
 */
const INDEX = (() => {
  const map = new Map()
  for (const entry of TOXIC_SUBSTANCES) {
    const keys = new Set()
    for (const alias of [entry.substance, entry.latin, ...(entry.aliases ?? [])]) {
      if (!alias) continue
      for (const piece of String(alias).split(/[（(]/)[0].split('/')) {
        const k = piece.trim()
        if (k) keys.add(k)
      }
    }
    for (const k of keys) {
      if (!map.has(k)) map.set(k, [])
      map.get(k).push(entry)
    }
  }
  return map
})()

/** 归一后的候选键 → 供 O(1) 精确命中（包含匹配仍需遍历，但先做精确可省大量比较） */
const EXACT = (() => {
  const m = new Map()
  for (const [k, list] of INDEX) {
    const key = isAsciiWord(k.toLowerCase()) ? k.toLowerCase() : stripSpace(k)
    if (!m.has(key)) m.set(key, [])
    for (const e of list) if (!m.get(key).includes(e)) m.get(key).push(e)
  }
  return m
})()

const speciesOf = (entry, species) => !species || (entry.species ?? []).includes(species)

/** 严重度排序权重（小的更危） */
const sev = (level) => TOXIC_LEVELS.indexOf(level)

/**
 * 在种子表中查找某物质（按物种过滤）。
 * @returns {Array} 命中的条目（可能多条），按严重度升序
 */
export function lookup(name, species = 'cat') {
  if (!name) return []
  const out = []
  const seen = new Set()

  // ① 精确命中优先
  const raw = String(name).trim()
  const exactKey = isAsciiWord(raw.toLowerCase()) ? raw.toLowerCase() : stripSpace(raw)
  for (const e of EXACT.get(exactKey) ?? []) {
    if (speciesOf(e, species) && !seen.has(e.id)) { seen.add(e.id); out.push(e) }
  }

  // ② 包含 / 词边界匹配
  for (const [alias, list] of INDEX) {
    if (!hitAlias(name, alias)) continue
    for (const e of list) {
      if (speciesOf(e, species) && !seen.has(e.id)) { seen.add(e.id); out.push(e) }
    }
  }

  return out.sort((a, b) => sev(a.level) - sev(b.level))
}

/** 组装来源四元组（把 `sourceIds` 解成可直接写进输出的对象） */
export function sourcesOf(entry) {
  return (entry?.sourceIds ?? []).map((k) => (SOURCES[k] ? { key: k, ...SOURCES[k] } : { key: k, missing: true }))
}

/**
 * 单物质判定。
 * @param {string} name 物质 / 原料名
 * @param {{species?: string, safeList?: string[]}} [opts]
 * @returns {{level: string, id: string|null, substance: string|null, conditions: string|null,
 *            basis: string|null, category: string|null, species: string, sources: Array}}
 */
export function classifySubstance(name, opts = {}) {
  const species = opts.species ?? 'cat'
  const matched = lookup(name, species)

  if (matched.length) {
    const best = matched[0]
    return {
      level: best.level,
      id: best.id,
      substance: best.substance,
      conditions: best.conditions ?? null,
      basis: best.basis ?? null,
      category: best.category ?? null,
      species,
      sources: sourcesOf(best),
    }
  }

  // 只有在**显式**安全声明命中时才给 ok
  const safeList = [...SAFE_SUBSTANCES, ...(opts.safeList ?? [])]
  const safeHit = safeList.find((s) => hitAlias(name, s))
  if (safeHit) {
    return { level: 'ok', id: null, substance: String(safeHit), conditions: null, basis: null, category: null, species, sources: [] }
  }

  // 未收录：无法判定。**这不是「安全」**。
  return { level: 'unknown', id: null, substance: name ? String(name) : null, conditions: null, basis: null, category: null, species, sources: [] }
}

/**
 * 配方批量判定。
 * @param {Array<{name?: string, weight?: number}|string>} items
 * @param {{species?: string, safeList?: string[]}} [opts]
 */
export function classifyRecipe(items, opts = {}) {
  const rows = (items ?? []).map((it) => {
    const name = typeof it === 'string' ? it : (it?.name ?? it?.code ?? '')
    const weight = typeof it === 'string' ? null : (it?.weight ?? null)
    return { name, weight, ...classifySubstance(name, opts) }
  })

  const count = (lv) => rows.filter((r) => r.level === lv).length
  const banned = count('banned')
  const caution = count('caution')
  const ok = count('ok')
  const unknown = count('unknown')

  return {
    species: opts.species ?? 'cat',
    rows,
    summary: {
      total: rows.length,
      banned,
      caution,
      ok,
      unknown,
      /** 是否阻断：命中任一禁用条目即阻断（`unknown` **不**阻断，但必须显式提示） */
      blocked: banned > 0,
      /** 需要人工确认的余量：未收录条目数（提示「这些还没判过」） */
      unjudged: unknown,
    },
  }
}

/**
 * 种子表自检（供守卫调用）。
 * 校验的是**数据**而不是判定逻辑 —— 数据腐化是这类表最现实的失效模式。
 * @returns {{ok: boolean, errors: string[]}}
 */
export function validateSubstanceTable() {
  const errors = []
  const ids = new Set()

  for (const e of TOXIC_SUBSTANCES) {
    const tag = e?.id ?? '(无 id)'
    if (!e?.id) errors.push('条目缺少 id')
    else if (ids.has(e.id)) errors.push(`id 重复：${e.id}`)
    else ids.add(e.id)

    if (!e?.substance) errors.push(`${tag}：缺少 substance`)
    if (!Array.isArray(e?.species) || e.species.length === 0) errors.push(`${tag}：species 不能为空`)
    if (!TOXIC_LEVEL_VALUES.includes(e?.level)) errors.push(`${tag}：level 非法（${e?.level}）`)
    if (e?.category && !TOXIC_CATEGORIES.includes(e.category)) errors.push(`${tag}：category 非法（${e.category}）`)
    if (!Array.isArray(e?.sourceIds) || e.sourceIds.length === 0) errors.push(`${tag}：无来源，不得收录`)
    for (const k of e?.sourceIds ?? []) {
      if (!SOURCES[k]) errors.push(`${tag}：来源键不存在（${k}）`)
    }
    // caution 必带条件说明；banned 不得带条件（条件会暗示「有条件的可用性」）
    if (e?.level === 'caution' && !String(e?.conditions ?? '').trim()) errors.push(`${tag}：caution 必须写明 conditions`)
    if (e?.level === 'banned' && e?.conditions != null) errors.push(`${tag}：banned 不应带 conditions`)
    if (!String(e?.basis ?? '').trim()) errors.push(`${tag}：缺少 basis（事实陈述）`)
  }

  return { ok: errors.length === 0, errors }
}
