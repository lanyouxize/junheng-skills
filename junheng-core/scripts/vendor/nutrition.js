/**
 * 营养计算引擎（纯函数，不依赖 DOM，可被 node 直接 import 测试）。
 * 整合六大模块：
 *   1) 原料营养组成数据库（**应用种子库** `src/data/ingredient_db.js`，286 条，原样基础 % / 价格 ¥·kg⁻¹）
 *      ⚠ 本模块**只读种子库**。用户维护的**权威主库** `ingredient_db.json`（1617 条）放在**项目外**，
 *        由 `scripts/lib/master-db.mjs` 解析，**与种子库不是同一个东西**（只有数据核对脚本会读主库）。
 *        ——旧注释写成「ingredient_db.json，1625 项」，文件名与条数都错，且会让人把主库误当本模块的数据源。
 *   2) 配方营养组成计算（加权求和 → 原样基础 + 干物质基础）
 *   3) 成本核算（价格优先级：用户覆盖 > 数据库 > 未填）
 *   4) 钙磷比计算（原样 / 干物质基）
 *   5) 代谢能计算（FEDIAF 改良 Atwater 为主，经典 Atwater 参照）
 *   6) 个体营养需求评估（体重/年龄/性别/生理状态 → RER·MER + AAFCO/FEDIAF/NRC 指标对照）
 */
import RAW_DB from '../data/ingredient_db.js'
import {
  NUTRIENT_FIELDS, FIELD_LABEL, FIELD_STATUS, COVERAGE_LOW,
  fieldStatus, ingredientDataStatus, recipeCoverage, summarizeCoverage, renormalizedEstimate,
} from './dataQuality.js'
import { resolveStandard, stageOf, classifyMoisture, DEFAULT_MARKET } from './standards.js'
import { energyProfile, grossEnergy, GE_FACTORS, GE_FACTORS_KJ, MODIFIED_ATWATER, ATWATER, restingEnergy, felineNrcMer, modifiedAtwaterME, classicAtwaterME } from './energy.js'
/* 「成品水分」输入的解析口径只在 moistureProfiles.js 里定义一处，
   引擎 / 界面 / 标准分档三处共用 —— 避免空值被 Number() 静默当成 0%（见该函数注释）。
   ⚠ 镜像约束：新增 `../data/` 依赖必须同步登记到 scripts/lib/skills-manifest.mjs 的 data 列表。 */
import { parseMoisturePercent, MIN_FINISHED_MOISTURE } from '../data/moistureProfiles.js'

export { grossEnergy, energyProfile }
export { GE_FACTORS, GE_FACTORS_KJ, MODIFIED_ATWATER, ATWATER }

/* ---------------- 1. 原料数据库 ---------------- */

/**
 * 营养字段定义与数据质量判定统一放在 lib/dataQuality.js（唯一出处），
 * 这里只做转出，保证既有 `import { NUTRIENT_FIELDS } from './nutrition.js'` 不用改。
 */
export { NUTRIENT_FIELDS, FIELD_LABEL, FIELD_STATUS, COVERAGE_LOW }

function stripBrand(name) {
  return String(name || '').replace(/[（(][^（）()]*[)）]/g, '').trim()
}

/** 名称规范化（去空格/括号/标点、小写）——供仓储层按名称定位复用 */
export function normName(name) {
  return String(name || '')
    .replace(/[\s\u3000·，,、。;；:：!！?？]/g, '')
    .replace(/[（(][^（）()]*[)）]/g, '')
    .toLowerCase()
}

/**
 * 营养数据质量的派生字段（口径与理由见 lib/dataQuality.js）。
 *    _dataStatus   complete 8 项齐全 / partial 有值但缺项 / none 一项数值都没有
 *    _zeroFields   值为 0 的字段（待复核：真零 or 未录入）
 *    _missingFields 空值字段（确定未录入）
 *    _zero         （兼容旧名）是否存在「无可用数值」的字段 → 界面据此提示
 *    _hasData      （兼容旧名）是否至少有一项 >0 的数值
 *
 * ⚠ 旧实现 `_zero = 任一字段 == null`、`_hasData = 任一字段 != null`，
 *   于是「8 项全为 0」的 129 条原料被判定为**有数据且无缺失** —— 这正是
 *   实测中「算式明显失真、界面却报零数据 0 条」的根因（计划 A2）。
 */
function dataMarks(it) {
  const st = ingredientDataStatus(it)
  return {
    _dataStatus: st.status,
    _valueFields: st.valueFields,
    _zeroFields: st.zeroFields,
    _missingFields: st.missingFields,
    _zero: st.suspectFields.length > 0,
    _hasData: st.hasValue,
  }
}

/** 运行时派生字段全集（持久化/导出时必须剔除，见 toRows / stripMarks） */
export const RUNTIME_MARKS = [
  '_norm', '_bare', '_normBare',
  '_dataStatus', '_valueFields', '_zeroFields', '_missingFields', '_zero', '_hasData',
]

/** 就地刷新一条原料的全部派生字段（改名 / 改营养值之后必须调用） */
function refreshMarks(it) {
  Object.assign(it, {
    _norm: normName(it.name),
    _bare: stripBrand(it.name),
    _normBare: normName(stripBrand(it.name)),
    ...dataMarks(it),
  })
  return it
}

const DB = RAW_DB.map((it) => ({
  ...it,
  _norm: normName(it.name),
  _bare: stripBrand(it.name),
  _normBare: normName(stripBrand(it.name)),
  ...dataMarks(it),
}))

export const INGREDIENT_DB = DB

/**
 * 原料库当前真实条数（唯一口径）。
 * 必须用函数实时读取：DB 会被 hydrateDb 用「数据源回读结果」原地重建，
 * 任何在模块加载时算好的快照常量（如旧的 dbSize）都会永远停在种子的 457 条，
 * 增删改/识别入库之后显示的条数就是错的。
 */
export const dbCount = () => DB.length

const BY_NORM = new Map()
for (const it of DB) if (!BY_NORM.has(it._norm)) BY_NORM.set(it._norm, it)
const BY_NORM_BARE = new Map()
for (const it of DB) if (!BY_NORM_BARE.has(it._normBare)) BY_NORM_BARE.set(it._normBare, it)
const BY_CODE = new Map()
for (const it of DB) if (it.code && !BY_CODE.has(it.code)) BY_CODE.set(String(it.code).trim(), it)

/** 给条目补齐运行时派生字段（_norm / _bare / 数据质量标记等） */
function decorate(it) {
  return {
    ...it,
    _norm: normName(it.name),
    _bare: stripBrand(it.name),
    _normBare: normName(stripBrand(it.name)),
    ...dataMarks(it),
  }
}

function rebuildIndex() {
  BY_NORM.clear()
  BY_NORM_BARE.clear()
  BY_CODE.clear()
  for (const it of DB) {
    if (!BY_NORM.has(it._norm)) BY_NORM.set(it._norm, it)
    if (!BY_NORM_BARE.has(it._normBare)) BY_NORM_BARE.set(it._normBare, it)
    if (it.code && !BY_CODE.has(String(it.code).trim())) BY_CODE.set(String(it.code).trim(), it)
  }
}

/**
 * 用「数据源读回的行」重建内存库与索引（应用启动 / 每次写入后回读刷新）。
 * 这是唯一允许整体替换 DB 的入口，替换内容来自持久化数据源，而非种子常量。
 */
export function hydrateDb(rows = []) {
  DB.length = 0
  for (const raw of rows) DB.push(decorate(raw))
  rebuildIndex()
  return DB.length
}

/**
 * 剔除运行时派生字段（唯一实现在这里，别在别处手写解构 —— 漏掉新字段会把
 * 派生数据持久化进 IndexedDB / 导出文件 / 备份包）。
 */
export function stripMarks(row) {
  const out = {}
  for (const [k, v] of Object.entries(row || {})) {
    if (!RUNTIME_MARKS.includes(k)) out[k] = v
  }
  return out
}

/** 导出当前内存库为可持久化的纯数据行（剔除派生字段，保留 id） */
export function toRows() {
  return DB.map((it) => stripMarks(it))
}

/** 按 id / 编码 / 名称定位内存条目（id 优先） */
export function findRowByKey(key) {
  const k = String(key ?? '').trim()
  if (!k) return null
  const byId = DB.find((x) => x.id && x.id === k)
  if (byId) return byId
  const byCode = findIngredientByCode(k)
  if (byCode) return byCode
  const n = normName(k)
  return DB.find((x) => x._norm === n || x._normBare === n) || null
}

/** 按编码精确查找。返回数据库条目或 null */
export function findIngredientByCode(code) {
  const c = String(code ?? '').trim()
  if (!c) return null
  return BY_CODE.get(c) || null
}

/**
 * 按编码查出**全部**命中条目。
 * 库内存在「同一编码对应多条原料」的历史遗留情况（76 组重复编码），
 * 因此按编号替换时必须先看这里返回了几条，绝不能默认取第一条。
 */
export function findAllByCode(code) {
  const c = String(code ?? '').trim()
  if (!c) return []
  return DB.filter((x) => String(x.code || '').trim() === c)
}

/** 按规范化名称查出全部命中条目（同名多条时供人工选择） */
export function findAllByName(name) {
  const n = normName(name)
  if (!n) return []
  return DB.filter((x) => x._norm === n || x._normBare === n)
}

/* ---------------- 原料库编辑 / 导入 ---------------- */

/**
 * 应用原料营养覆盖：把用户编辑的营养值合并进 DB 条目（原地修改，幂等）。
 * map: { [code|name]: { crude_protein, calcium, price, ... } }
 */
export function applyIngredientOverrides(map = {}) {
  for (const [key, patch] of Object.entries(map)) {
    if (!patch) continue
    let target = BY_CODE.get(String(key).trim())
    if (!target) target = BY_NORM.get(normName(key)) || BY_NORM_BARE.get(normName(stripBrand(key)))
    if (!target) continue
    for (const [k, v] of Object.entries(patch)) {
      if (v === null || v === undefined) continue
      target[k] = v
    }
    // 刷新派生字段
    refreshMarks(target)
  }
}

/**
 * 批量导入/新增原料条目。items: [{ name, code, category, lifeStage, price, ...营养 }]
 * 已存在（同名或同编码）则覆盖，否则追加。返回 { added, updated }。
 */
export function importIngredients(items = []) {
  let added = 0
  let updated = 0
  for (const raw of items) {
    if (!raw || !raw.name) continue
    const existing = raw.code ? findIngredientByCode(raw.code) : findIngredient(raw.name)
    const base = existing || {}
    const merged = {
      // id 为持久化主键：已有条目沿用原 id，新条目留空由仓储层分配
      id: raw.id || base.id || undefined,
      ...base,
      category: raw.category || base.category || '其他/待定',
      name: raw.name || base.name,
      lifeStage: raw.lifeStage || base.lifeStage || null,
      code: raw.code || base.code || '',
      price: raw.price != null ? Number(raw.price) : (base.price != null ? base.price : 0),
    }
    for (const [k] of NUTRIENT_FIELDS) {
      merged[k] = raw[k] != null ? Number(raw[k]) : (base[k] != null ? base[k] : null)
    }
    if (existing) {
      Object.assign(existing, merged)
      refreshMarks(existing)
      if (existing.code && !BY_CODE.has(existing.code)) BY_CODE.set(existing.code, existing)
      updated++
    } else {
      const it = refreshMarks({ ...merged })
      DB.push(it)
      if (!BY_NORM.has(it._norm)) BY_NORM.set(it._norm, it)
      if (!BY_NORM_BARE.has(it._normBare)) BY_NORM_BARE.set(it._normBare, it)
      if (it.code && !BY_CODE.has(it.code)) BY_CODE.set(it.code, it)
      added++
    }
  }
  return { added, updated }
}

/**
 * 删除原料条目。按编码或名称定位（编码优先）。
 * 返回 { deleted: bool, name, data }，其中 data 为完整可恢复快照（用于撤销/回收站恢复）。
 */
export function deleteIngredient(key) {
  const c = String(key ?? '').trim()
  if (!c) return { deleted: false }
  let idx = -1
  let it = null
  // 唯一标识 id 优先（持久化后的主键），其次编码，最后名称
  it = DB.find((x) => x.id && x.id === c) || null
  if (it) idx = DB.indexOf(it)
  if (idx < 0) {
    it = findIngredientByCode(c)
    if (it) idx = DB.indexOf(it)
  }
  if (idx < 0) {
    const n = normName(c)
    it = DB.find((x) => x._norm === n || x._normBare === n)
    if (it) idx = DB.indexOf(it)
  }
  if (idx < 0) return { deleted: false }
  const [removed] = DB.splice(idx, 1)
  // 清理索引
  if (removed.code) BY_CODE.delete(String(removed.code).trim())
  if (BY_NORM.get(removed._norm) === removed) BY_NORM.delete(removed._norm)
  if (BY_NORM_BARE.get(removed._normBare) === removed) BY_NORM_BARE.delete(removed._normBare)
  // 返回可恢复快照（剔除运行时派生字段）
  return { deleted: true, name: removed.name, data: stripMarks(removed) }
}

/**
 * 恢复（重新插入）一条原料条目。data 为 deleteIngredient 返回的完整数据快照。
 * 已存在同编码/同名则跳过，避免重复。返回 { restored: bool }。
 */
export function restoreIngredient(data) {
  if (!data || !data.name) return { restored: false }
  const existing = (data.code && findIngredientByCode(data.code)) || findIngredient(data.name)
  if (existing) return { restored: false }
  const merged = {
    category: data.category || '其他/待定',
    name: data.name,
    lifeStage: data.lifeStage || null,
    code: data.code || '',
    price: data.price != null ? Number(data.price) : 0,
  }
  for (const [k] of NUTRIENT_FIELDS) {
    merged[k] = data[k] != null ? Number(data[k]) : null
  }
  const it = refreshMarks({ ...merged })
  DB.push(it)
  if (!BY_NORM.has(it._norm)) BY_NORM.set(it._norm, it)
  if (!BY_NORM_BARE.has(it._normBare)) BY_NORM_BARE.set(it._normBare, it)
  if (it.code && !BY_CODE.has(it.code)) BY_CODE.set(it.code, it)
  return { restored: true, name: it.name }
}

/**
 * 数字拼接误配检测：当 shorter 是 longer 的前缀，且「拼接处」两侧都是数字时，
 * 视为不同的编号条目（如 维生素b1 与 维生素b12），不应互相当作匹配。
 * 数字属于身份标识，不是描述性后缀——反例：碳酸钙→碳酸钙粉、鸡大胸→鸡大胸(冷冻) 合法。
 * 全库实测（2026-10-25，286 条）不存在库内数字拼接配对，本守卫只拦截「查询侧多一个尾随数字」的误配。
 */
function isDigitJoinMismatch(shorter, longer) {
  if (!longer.startsWith(shorter)) return false
  const rest = longer.slice(shorter.length)
  if (!rest) return false
  return /\d/.test(shorter.slice(-1)) && /\d/.test(rest.slice(0, 1))
}

/**
 * 子串型数字拼接误配：n 作为子串出现在 h 中（it._norm.includes(n) 分支），
 * 若拼接边界两侧都是数字则视为不同编号条目而拒配。
 */
function isDigitJoinSubstring(h, n) {
  const idx = h.indexOf(n)
  if (idx < 0) return false
  const before = idx > 0 ? h[idx - 1] : ''
  const after = idx + n.length < h.length ? h[idx + n.length] : ''
  const lastN = n.slice(-1)
  const firstN = n.slice(0, 1)
  return (/\d/.test(lastN) && /\d/.test(after)) || (/\d/.test(firstN) && /\d/.test(before))
}

/** 名称查找：精确 → 去品牌括号 → 前缀包含 → 编码。返回数据库条目或 null */
export function findIngredient(name) {
  const n = normName(name)
  if (!n) return null
  if (BY_NORM.has(n)) return BY_NORM.get(n)
  if (BY_NORM_BARE.has(n)) return BY_NORM_BARE.get(n)
  // 方向一：n 以 it._norm 开头（查询是条目的「名称+描述性后缀」），排除数字拼接误配
  let hit = DB.find((it) => n.startsWith(it._norm) && !isDigitJoinMismatch(it._norm, n))
  if (hit) return hit
  hit = DB.find((it) => it._normBare === n) || null
  if (hit) return hit
  // 方向二：it._norm 包含 n（条目以 n 开头，或 n 嵌于条目中部），排除数字拼接误配
  hit = DB.find((it) => it._norm.includes(n) && n.length >= 2 && !isDigitJoinSubstring(it._norm, n)) || null
  if (hit) return hit
  // 兜底：按编码查找（去掉前导零后）
  const byCode = findIngredientByCode(n.replace(/^0+/, ''))
  return byCode || null
}

/** 模糊搜索（打分排序），供原料选择器使用 */
export function searchIngredients(query, limit = 30) {
  const raw = String(query || '').trim()
  const n = normName(raw)
  if (!n) return DB.slice(0, limit)
  // 纯数字（≥3 位）按「原料编号」检索：编号即身份，命中优先级高于名称相似度。
  // 这样「01010001」能直接找到鸡大胸，也便于区分同名不同款（如「鸡大胸」与「熟鸡大胸」）。
  const asCode = /^\d{3,}$/.test(raw)
  const scored = []
  for (const it of DB) {
    let s = 0
    if (asCode) {
      const code = String(it.code || '').trim()
      if (code && code === raw) s = 130
      else if (code && code.startsWith(raw)) s = 105
      else if (code && code.includes(raw)) s = 85
    }
    if (!s) {
      if (it._norm === n) s = 100
      else if (it._normBare === n) s = 95
      else if (it._normBare.startsWith(n) || it._norm.startsWith(n)) s = 80
      else if (it._normBare.includes(n) || it._norm.includes(n)) s = 60
    }
    if (s > 0) scored.push({ it, s: s + (it._zero ? 0 : 2) }) // 有数据的略靠前
  }
  scored.sort((a, b) => b.s - a.s)
  return scored.slice(0, limit).map((x) => x.it)
}

/* ---------------- 2. 配方营养计算 ---------------- */

/**
 * 解析配方文本为 [{name, weight}]。
 * 支持三种原料引用格式（可混用）：
 *   1. "名称 + 用量"      ：鸡大胸 70 / 鸡肝 10%
 *   2. "编号 + 用量"      ：01010001 70 / 02010062 2%
 *   3. "编号 + 名称 + 用量"：01010001 鸡大胸 70
 * 数字单位：% / 克 / g / kg / 公斤 / 斤（缺省视为"份数"，按比例计）
 * 分隔：换行、分号、逗号、顿号均可；**空格亦可**（见 splitInlinePairs）。
 */
export function parseRecipeText(text = '') {
  const out = []
  const segs = String(text)
    .split(/[\n;；]+/)
    .flatMap((line) => line.split(/(?<=[%％克gG]|\d)\s*[，,、]\s*/))
    .flatMap((seg) => splitInlinePairs(seg))
    .map((s) => s.trim())
    .filter(Boolean)
  for (const seg of segs) {
    const parsed = parseOneSegment(seg)
    if (parsed) out.push(parsed)
  }
  return out
}

/**
 * 裸物种词：出现在「名 + 数」片段里时是动物档案（猫 4kg），不是原料引用。
 *
 * 判据来自实测（2026-10-25 探针）：findIngredient('猫') → 猫用预混料有机、
 * findIngredient('犬') → 犬用调味膏DL-7，二者都只经 `it._norm.startsWith(n)` 前缀规则命中，
 * 全等表（BY_NORM / BY_NORM_BARE）里并没有它们。不设防时「猫 4kg」会被解析成
 * 4000 份预混料的幽灵配方。狗当前解析为 null，一并纳入，防止库内新增狗用原料时复发。
 */
export const BARE_SPECIES_WORDS = new Set(['猫', '犬', '狗', '喵', '汪'])

/** 单个「数量 token」：数字 + 可选单位（% / 克 / g / kg / 公斤 / 斤），如 70、10%、2.5g、0.5斤 */
const QTY_TOKEN_RE = /^\d+(?:\.\d+)?\s*(?:%|％|克|g|G|kg|KG|公斤|斤)?$/

/**
 * 空格分隔的多段配方切分（2026-10-25，task #47）。
 *
 * 病灶（真浏览器走查实测）：`鸡大胸 70 鸡肝 10 碳酸钙 1` 整段被当成**一个原料名**，
 * 靠 findIngredient 的 `n.startsWith(it._norm)` 前缀规则命中「鸡大胸」、取**最后一个**数字
 * 当用量 ⇒ 静默算出「1 种原料、用量 1」的错配方，而界面照常输出 ME/钙磷比/成本。
 * 比「请把配方发给我」危险得多：用户以为算对了。
 *
 * 为什么不无脑按空格拆：中文语境里「名 + 数」也会出现在非配方句子里，
 * 而 findIngredient 的前缀匹配极其宽松（`findIngredient('猫')` 命中「猫用预混料」）。
 * 无脑拆会把「猫 4kg 每天吃多少」变成一条**幽灵配方**，需求评估轮凭空多出
 * 「按当前配方每日约喂 Xg」—— 用一个静默错误换另一个静默错误。
 *
 * 因此只认**高置信度配方行**，四条守卫全部满足才拆（全部来自实测负对照）：
 *   ① token ≥ 4（至少「名 数 名 数」）—— 两 token 的 `鸡大胸 70` 无需拆；
 *   ② 首 token 不是数量 —— 保护「编号+名称+用量」（01010001 鸡大胸 70）与
 *      「数量开头」（1000 鸡大胸 70）两种既有语法，拆了会改变它们的语义；
 *   ③ 末 token 是数量 —— 结尾带自然语言（「…钙磷比」「…每天吃多少」）说明这不是
 *      纯配方行，保持原行为（回「请把配方发给我」）而不是硬拆；
 *   ④ 数量 token ≥ 2 —— 只有一段「名+数」时没有可拆的边界。
 * 任一条不满足 ⇒ 原样返回，走 parseOneSegment 老路（行为与改动前逐字节一致）。
 */
function splitInlinePairs(seg) {
  const tokens = String(seg).trim().split(/\s+/).filter(Boolean)
  if (tokens.length < 4) return [seg]
  const isQty = (t) => QTY_TOKEN_RE.test(t)
  if (isQty(tokens[0])) return [seg]
  if (!isQty(tokens[tokens.length - 1])) return [seg]
  if (tokens.filter(isQty).length < 2) return [seg]
  const out = []
  let name = []
  for (const t of tokens) {
    if (isQty(t) && name.length) {
      out.push([...name, t].join(' '))
      name = []
    } else name.push(t)
  }
  // 理论上到不了：③④ 已保证末 token 是数量且前面有名称
  if (name.length) out.push(name.join(' '))
  return out.length >= 2 ? out : [seg]
}


/** 解析单个片段（一个原料引用）。支持 名称/编号/编号+名称 三种形式。 */
function parseOneSegment(seg) {
  let m = seg.match(/^(.+?)\s*[:：]?\s*(\d+(?:\.\d+)?)\s*(%|％|克|g|G|kg|KG|公斤|斤)?$/)
  let name = null
  let weight = null
  if (m) {
    name = m[1]
    weight = Number(m[2])
    weight = scaleWeight(weight, m[3])
  } else {
    m = seg.match(/^(\d+(?:\.\d+)?)\s*(%|％|克|g|G|kg|KG|公斤|斤)?\s*[:：]?\s*(.+)$/)
    if (m) {
      name = m[3]
      weight = Number(m[1])
      weight = scaleWeight(weight, m[2])
    }
  }
  if (!name || weight === null || !(weight > 0)) return null
  name = name.trim()

  // 三种引用解析：
  // (a) 编号+名称：形如 "01010001 鸡大胸" → 名称优先（更具体），名称匹配不到再按编号
  const codeName = name.match(/^(\d{4,})\s+([^\d].*)$/)
  if (codeName) {
    const byName = findIngredient(codeName[2])
    if (byName) return { rawName: name, weight, ingredient: byName }
    const byCode = findIngredientByCode(codeName[1])
    if (byCode) return { rawName: name, weight, ingredient: byCode }
    return { rawName: name, weight, ingredient: null }
  }
  // (b) 纯编号：形如 "01010001"
  if (/^\d{4,}$/.test(name)) {
    const byCode = findIngredientByCode(name)
    if (byCode) return { rawName: name, weight, ingredient: byCode }
    return { rawName: name, weight, ingredient: null }
  }
  // (c) 普通名称
  // 裸物种词不是原料引用：不设防时「猫 4kg」经前缀规则命中「猫用预混料有机」，
  // 被当成 4000 份预混料——实测需求评估追问物种时用户回「猫 4kg」，
  // 界面冒出「共 1 种原料、合计 4000、代谢能 3500」的配方报告。
  // 保留 ingredient:null（而非整项丢弃）⇒ 交给上层按「未匹配原料」显式处理，不静默。
  if (BARE_SPECIES_WORDS.has(normName(name))) {
    return { rawName: name.trim(), weight, ingredient: null }
  }
  const ing = findIngredient(name)
  return { rawName: name.trim(), weight, ingredient: ing }
}

function scaleWeight(w, unit) {
  if (unit === '斤') return w * 500
  if (unit === 'kg' || unit === 'KG' || unit === '公斤') return w * 1000
  return w
}

/**
 * 干物质基础换算：干基 = 湿基 ÷ DM% × 100。
 *
 * ⚠ **水分不参与换算**（2026-09-27 修正的换算错误）：
 *   干物质基础的定义就是「扣掉全部水分之后」的组成 —— DM% = 100% − 水分%，
 *   水分自己已经被扣没了。若照搬同一公式，会算出
 *      76.6 ÷ (23.4 / 100) = 327.32 %DM
 *   这种无意义的值（用户截图里红框标出的就是这个）。
 *   因此 **水分在干基恒为 0**，且是有意义的真零（这一点与「0 表示未录入」的数据
 *   质量口径不冲突：它是定义推导值，不是录入值）。
 *   副产品：湿基各项 ÷ DM% 之后，干基「粗蛋白+粗脂肪+粗纤维+粗灰分+水分+NFE」恰好 = 100%。
 *
 * @param {Object} asFed     原样基础各指标（百分比）
 * @param {number} dmPercent 干物质含量（100 − 水分）
 * @returns {Object} 干物质基础各指标
 */
export function toDryMatter(asFed, dmPercent) {
  const out = {}
  for (const k of Object.keys(asFed)) {
    out[k] = k === 'moisture' ? 0 : (dmPercent > 0.01 ? (asFed[k] / dmPercent) * 100 : 0)
  }
  return out
}

/** 干基水分的显示口径：0，且标注「定义值」而非「未录入」 */
export const DM_MOISTURE_NOTE = '干基定义为扣除全部水分，水分为 0%（定义值）'

/**
 * 风干基础（Air-Dry Basis, ADB）的**水分口径说明** —— 与 `DM_MOISTURE_NOTE` 成对，供界面 title 用。
 *
 * ⚠ 风干基础的水分项**不是 0**，而是「风干参照水分」本身（可配置）。
 *   干基的水分恒 0 是**定义值**；风干基础的水分是可读出的**设定值**。
 *   两者语义不同，**不可互相顶替**（见 `toAirDryBasis` 的 R1~R4）。
 */
export const ADB_MOISTURE_NOTE = '风干基础以「风干参照水分」为基准换算：水分项 = 该参照水分本身（可配置），不是干基那样的定义值 0'

/**
 * 风干参照水分 w_ad 的**默认值**（%）。
 *
 * ⚠ 这是**本厂指定的工艺口径**（2026-10-16 由需求方给定），**不是**行业惯例值 ——
 *   饲料行业的 air-dry basis 惯例按 **10%~12%** 水分归一（约 88%~90% 干物质）。
 *   本厂烘焙 / 风干线成品的实际水分多在 3%~5%，故默认取 3%。
 *
 * ⚠ 需要跨厂 / 跨产品对比（对齐行业口径）时，请通过 `opts.airDryMoisturePercent`
 *   （CLI 同名参数 / 界面「风干参照水分」入口）**显式覆盖**，
 *   而**不要**改这个常量 —— 改常量会静默改变全部既有对比口径。
 */
export const AIR_DRY_MOISTURE_DEFAULT = 3

/**
 * 风干基础换算：`a_i = d_i × (100 − w_ad) ÷ 100`。
 *
 * ## 与「干基」的区别（两者不可互换，四条理由）
 * 记号：`c_i` = 原样(湿基)值，`w_af` = 成品**实际**水分，`w_ad` = 风干**参照**水分（可配）。
 *   干基     d_i = c_i ÷ DM% × 100            参照水分 = 0%（全干）
 *   风干基础 a_i = d_i × (100 − w_ad) ÷ 100 = c_i × (100 − w_ad) ÷ (100 − w_af)
 *
 * - **R1 参照水分不同**：DMB 参照 0%，ADB 参照非零的 w_ad ⇒ 同一指标相差
 *   `(100 − w_ad)/100` 倍（w_ad=3% 时 ADB 比 DMB 小 3%）。
 * - **R2 用途与语境不同**：DMB 是国际通行的跨产品营养浓度比较与法规判定口径
 *   （GB/T 31216/31217 的 %DM、AAFCO 的 DM basis）；ADB 是饲料行业的报告口径 ——
 *   把**不同水分**的料**归一到统一风干水分**后按重量比较或配料。
 * - **R3 水分项语义不同**：DMB 的水分恒 0 是**定义值**；ADB 的水分 = w_ad，是可读出的设定值。
 * - **R4 用错即系统性误判**：拿 ADB 值当 DMB 值去比法规限值会偏小 `(100 − w_ad)/100`，
 *   可能把达标项判成不达标（反之亦然）。故界面必须两列**并列显式**、列头写明口径。
 *
 * ⚠ 水分项在这里**不是 0**，而是 `w_ad` 本身 —— 这也正是它合计仍为 100 的原因：
 *   Σ(除水分外各项) = 100 × (100 − w_ad)/100 = 100 − w_ad，再加 w_ad = 100.0000。
 *
 * ⚠ 参照水分解析**复用 `parseMoisturePercent`**（唯一口径），不直接用 `Number()`：
 *   `Number('')`、`Number(null)` 都是 0，会把「没给」静默当成「按 0% 归一」。
 *
 * @param {Object} dmItems     干基各指标（`toDryMatter` 的产出）
 * @param {number} refMoisture 风干参照水分 w_ad（%），须落在 [0, 100)
 * @returns {Object|null} 风干基础各指标；`refMoisture` 非法时返回 **null**（不猜、不兜底）
 */
export function toAirDryBasis(dmItems, refMoisture) {
  const w = parseMoisturePercent(refMoisture)
  if (!Number.isFinite(w) || !(w >= 0 && w < 100)) return null
  const k = (100 - w) / 100
  const out = {}
  for (const key of Object.keys(dmItems)) {
    out[key] = key === 'moisture' ? w : dmItems[key] * k
  }
  return out
}

/**
 * 原料占配方总量的百分比（%）。
 *
 * 计算器的用量列是「任意单位」（100 / 1.4 / 37.5 混用），配比只能看占比，
 * 所以原料表要直接给出这一列，避免用户心算。
 * 口径与 computeRecipe 内部的 share 完全一致（同一处公式，不要各写一套）。
 *
 * @param {number} weight 该原料用量
 * @param {number} total  配方总用量
 * @returns {number|null} null = 总量为 0，**无法计算**（不是 0%）
 */
export function sharePercent(weight, total) {
  const w = Number(weight)
  const t = Number(total)
  if (!Number.isFinite(w) || !Number.isFinite(t) || t <= 0) return null
  return (w / t) * 100
}

/**
 * 配方营养计算。items: [{ ingredient, weight }]（ingredient 为数据库条目）
 * priceOverrides: { [code|name]: number } 用户自定义价格（¥/kg）
 * opts:
 *   species          'cat' | 'dog'（决定 DE/ME 的消化率方程与尿能系数）
 *   moisturePercent  成品水分 %（可选）。给定时按**干物质守恒**把原料加权结果折算到成品水分：
 *                    湿基各项 × k、水分 = 目标值、**干基组成不变**。见函数内 `moistureAdjust`。
 *                    不给 / 空串 / 空白 / 非数 = 沿用原料加权水分（既有行为，不变）。
 *                    ⚠ 解析口径统一走 `parseMoisturePercent`（「没给」≠「给了 0」）。
 *                    ★ **硬下限**：低于 `MIN_FINISHED_MOISTURE`(1%) 视为无效输入 ⇒
 *                      不施加、标 `reason:'below_min_moisture'`、结果回退原料加权。
 *                      ⚠ 判序：先物理越界（<0 / ≥100 ⇒ `out_of_range`），再业务下限。
 *   airDryMoisturePercent  风干参照水分 w_ad %（可选，默认 `AIR_DRY_MOISTURE_DEFAULT`）。
 *                    用于 `recipe.airDry`（风干基础列）—— 与 `moisturePercent` **互不相干**：
 *                    前者是「按什么口径放齐了比」的参照，后者是「成品实际含多少水」。
 *                    取值规则：解析为 NaN（空/空白/布尔/数组/非数字符串）⇒ 用默认值；
 *                    解析出有限值但越出 [0,100) ⇒ `airDry.available = false`（**不兜底**）。
 * 返回统一结果对象（原样基础、干物质基础、**风干基础**、成本、钙磷比、代谢能）。
 */
export function computeRecipe(items, priceOverrides = {}, opts = {}) {
  const valid = items.filter((x) => x.ingredient && x.weight > 0)
  const totalW = valid.reduce((s, x) => s + x.weight, 0)
  if (!totalW) return null

  const asFed = {}
  for (const [k] of NUTRIENT_FIELDS) asFed[k] = 0
  const lines = []
  let cost = 0
  let missingPrice = []
  let zeroData = []

  for (const { ingredient: it, weight } of valid) {
    const share = weight / totalW
    for (const [k] of NUTRIENT_FIELDS) asFed[k] += (it[k] || 0) * share
    let price = null
    const ovr = priceOverrides[it.code] ?? priceOverrides[it.name]
    if (Number.isFinite(Number(ovr)) && Number(ovr) >= 0) price = Number(ovr)
    else if (it.price > 0) price = it.price
    if (price === null) {
      missingPrice.push(it._bare || it.name)
      price = 0
    }
    cost += (weight / 1000) * price // price 为 ¥/kg
    if (it._zero) zeroData.push(it.name)
    lines.push({
      code: it.code,
      name: it.name,
      weight,
      share: share * 100,
      price,
      ...Object.fromEntries(NUTRIENT_FIELDS.map(([k]) => [k, it[k] || 0])),
    })
  }

  /* ---- 数据质量（M0 批次 1.2）：逐字段覆盖率 + 归一化估计值 ----
   * 口径见 lib/dataQuality.js：只统计「有 >0 数值」的原料，不对 0 是否真零下结论。
   * asFed 保持原口径（未录入按 0 计），**不静默改动数值**；缺数据只做「显式暴露」：
   *   coverage[k].status = full 全部有值 / partial 部分有值 / none 一条都没有
   *   estimate[k]        = 按有值原料重新归一化得到的**估计**（partial/none 时给出）
   * ⚠ 覆盖率必须**先算**：① 能量学里的水分覆盖率是它的一个字段；
   *   ② 下面的「成品水分覆盖」要靠它判断原料水分是否整列缺失。
   */
  const coverage = recipeCoverage(valid)
  const coverageSummary = summarizeCoverage(coverage)

  /* ---- 成品水分覆盖（可选，opts.moisturePercent）----
   * 原料加权水分 = **加工前物料**的水分；烘焙 / 冻干 / 烘干这些工序会脱水，
   * 成品的真实水分由**工艺**决定，而不是原料。取错水分 ⇒ DM% 错 ⇒
   * 干基、能量、达标判定全部跟着错（这是本项存在的唯一理由）。
   *
   * 折算口径 = **干物质守恒**：k = 成品DM% ÷ 原料DM%
   *   · 湿基各项 × k（水被抽走 ⇒ 单位质量的干物质浓度升高）
   *   · 水分 = 目标水分
   *   · **干基各项不变**（除水不改变干物质的组成，只改变其浓度）
   *
   * ⚠ 原料水分整列缺失时**不静默兜底**（项目铁律）：算不出 k 就不施加，
   *   在 `moistureAdjust.reason` 里说明原因，让界面显式提示。
   */
  /* 水分覆盖率有**两个口径，不可混用**：
   *   · coverage.moisture.ratio = 有水分数值的原料**条数**占比（逐字段覆盖率表用它）
   *   · moistureWeightRatio     = 有水分数值的原料**重量**占比（折算系数 k 的可信度用它）
   * 为什么 k 必须看重量口径：k 的分母是「原料加权水分」，而加权是**按重量**做的。
   * 一条占 80% 重量的大料缺水、九条微量原料有水分时，条数口径报 90%（看着无害），
   * 重量口径只有 11%（真实风险）—— 两个口径给出的结论完全相反。 */
  const covMoisture = coverage.moisture ? coverage.moisture.ratio : 0
  const moistureWeightRatio = (() => {
    if (!coverage.moisture || !coverage.moisture.have) return 0
    let w = 0
    for (const { ingredient: it, weight } of valid) {
      if (fieldStatus(it, 'moisture') === FIELD_STATUS.VALUE) w += weight
    }
    return totalW > 0 ? w / totalW : 0
  })()
  const dmPercentSource = 100 - asFed.moisture
  const sourceMoisture = asFed.moisture
  /* 「没给」与「给了 0」必须严格分开：空串 / 纯空白 / null / 布尔 / 数组一律＝未指定（NaN）。
     ⚠ 不能直接用 Number()：`Number('')`、`Number(' ')`、`Number(null)` 都是 0，
       而 0% 是合法水分值 ⇒ 空输入会被静默当成「0% 水分」并算出一份看似正常的配方。 */
  const mTarget = parseMoisturePercent(opts.moisturePercent)
  let moistureAdjust = null
  // 折算系数 k（仅 applied:true 时非 null）。hoist 出来是为了让下面的 `estimate`
  // 也按同一系数折算 —— 否则 asFed 已折、estimate 未折，两处口径自相矛盾。
  let moistureScale = null
  if (Number.isFinite(mTarget)) {
    if (!(mTarget >= 0 && mTarget < 100)) {
      moistureAdjust = {
        applied: false,
        reason: 'out_of_range',
        target: mTarget,
        note: `成品水分须在 ${MIN_FINISHED_MOISTURE}%（含）至 100%（不含）之间，本次未施加，结果仍按原料加权水分`,
      }
    } else if (mTarget < MIN_FINISHED_MOISTURE) {
      /* ★ 硬下限：成品水分 0% ⇒ DM% = 100% ⇒ 干基与湿基逐格重合、GE 虚高
         （见 moistureProfiles.js 的 MIN_FINISHED_MOISTURE 注释）。必须拦下，
         否则会算出一份「看起来正常」的配方。
         ⚠ **判序有意如此，不要调换**：先判**物理越界**（<0 / ≥100 ⇒ out_of_range），
            再判**业务下限**（[0, MIN) ⇒ below_min_moisture）。
            负数是「物理上不可能」，不是「低于工艺下限」，两者语义不同；
            既有守卫 `moisture-profile-test.mjs` 也钉着 -1 / -0.5 → out_of_range。 */
      moistureAdjust = {
        applied: false,
        reason: 'below_min_moisture',
        target: mTarget,
        min: MIN_FINISHED_MOISTURE,
        note: `成品水分 ${mTarget}% 低于硬下限 ${MIN_FINISHED_MOISTURE}%：成品不可能零水分（水分 0 ⇒ 干物质 100% ⇒ 干基与湿基重合、能量虚高）。本次未施加，结果仍按原料加权水分`,
      }
    } else if (!(moistureWeightRatio > 0)) {
      moistureAdjust = {
        applied: false,
        reason: 'no_ingredient_moisture',
        target: mTarget,
        note: '参与原料的水分数据整列为空（无一条给出 >0 的水分数值），无法由原料折算到成品水分 —— 请先补原料水分（不按 0 水分兜底）',
      }
    } else if (!(dmPercentSource > 0.01)) {
      moistureAdjust = {
        applied: false,
        reason: 'zero_dry_matter',
        target: mTarget,
        note: '原料加权水分约 100%（干物质为 0），无法折算到成品水分',
      }
    } else {
      const k = (100 - mTarget) / dmPercentSource
      for (const [key] of NUTRIENT_FIELDS) asFed[key] = asFed[key] * k
      asFed.moisture = mTarget
      moistureScale = k
      moistureAdjust = {
        applied: true,
        sourceMoisture: r2(sourceMoisture),
        targetMoisture: r2(mTarget),
        sourceDmPercent: r2(dmPercentSource),
        targetDmPercent: r2(100 - mTarget),
        /* 实际参与折算的系数，**不取整** —— 保证「记录 = 事实」（界面自己格式化显示）。
           取整后记录会让「用 scale 反推结果」对不上（相对偏差约 5e-5）。 */
        scale: k,
        /* k 的可信度用**重量**口径（与 k 的加权口径一致）；条数口径并列给出以便对照 */
        sourceCoverage: r2(moistureWeightRatio),
        sourceCoverageByCount: r2(covMoisture),
        lowConfidence: moistureWeightRatio < COVERAGE_LOW,
        note: '按干物质守恒折算：湿基各项 × k，水分 = 成品水分；干基组成不变（除水不改变干物质组成）',
      }
    }
  }

  const dmPercent = 100 - asFed.moisture // 干物质含量 %（成品口径）
  // 干物质基础：原样值 / 干物质含量；水分恒为 0（见 toDryMatter 注释）
  const dm = toDryMatter(asFed, dmPercent)

  // 无氮浸出物 NFE（原样基础）= 100 - 水分 - 粗蛋白 - 粗脂肪 - 粗纤维 - 粗灰分
  const nfe = Math.max(
    0,
    100 - asFed.moisture - asFed.crude_protein - asFed.crude_fat - asFed.crude_fiber - asFed.crude_ash,
  )

  /* ---- 风干基础（Air-Dry Basis）----
   * 与干基**并列的第三种口径**：干基参照水分恒为 0，风干基础参照的是「风干参照水分」w_ad。
   * 用途是**把不同水分的料归一到统一口径**，以便跨产品比较 / 按重量配料。
   * 四条「不可互换」的理由见 `toAirDryBasis` 的 R1~R4。
   *
   * ⚠ w_ad 与「成品实际水分」是**两个独立的量**：前者说「按什么口径放齐了比」，
   *   后者说「这袋粮实际含多少水」。若把 w_ad 取成成品水分，风干列会与湿基列**逐格完全相同**
   *   （a_i = c_i×(100−w_ad)÷(100−w_af)，w_ad = w_af 时是恒等式）—— 那这一列就白加了。
   *
   * 取值规则（只有两句，别再加分支）：
   *   · `parseMoisturePercent` 返回 **NaN ⇒ 视为「未指定」⇒ 用默认值**
   *     —— 与 `moisturePercent` 的既有约定同源（空串/纯空白/布尔/数组/对象/非数字符串皆属未指定）。
   *   · 解析出**有限值但越出 [0,100)** ⇒ `available:false`、显式「不出数」
   *     —— 这是「给了但非法」，**不静默顶成默认值**（否则 -1 会被悄悄当成 3%）。
   */
  const airDryParsed = parseMoisturePercent(opts.airDryMoisturePercent)
  const airDryRefMoisture = Number.isFinite(airDryParsed) ? airDryParsed : AIR_DRY_MOISTURE_DEFAULT
  const airDryItems = toAirDryBasis(dm, airDryRefMoisture)
  /* 干基 / 风干的 NFE 都在引擎侧现算（界面不重算，保持单一真源）：
     d_nfe = nfe ÷ DM% × 100，a_nfe = d_nfe × (100 − w_ad) ÷ 100。
     ⚠ 这也是「风干列合计仍 = 100」的一环 —— 漏乘/漏除会让列内和偏离 100。 */
  const dmNfe = dmPercent > 0.01 ? nfe / (dmPercent / 100) : null
  const airDry = {
    available: airDryItems != null,
    refMoisture: airDryItems != null ? r2(airDryRefMoisture) : null,
    basis: 'air-dry-basis',
    items: airDryItems,
    nfe: airDryItems != null && dmNfe != null ? dmNfe * ((100 - airDryRefMoisture) / 100) : null,
    note: airDryItems != null
      ? `风干基础：按风干参照水分 ${r2(airDryRefMoisture)}% 归一（a = 干基 × (100 − ${r2(airDryRefMoisture)}) ÷ 100）。水分项等于该参照水分，不是 0 —— 与干基口径不可互换`
      : `风干参照水分 ${airDryParsed}% 非法（须在 0%（含）至 100%（不含）之间），风干基础不出数`,
  }

  /* 5. 代谢能（kcal/kg，原样基础） */
  // FEDIAF 改良 Atwater：蛋白 3.5、脂肪 8.5、碳水 3.5 kcal/g（犬猫通用）
  // ⚠ 这两个数值口径与键名**保持不变** —— 全站判定（standards.js 的能量对照、
  //    requirements 的 MER 换算）都挂在 meModified 上，动它会静默改变既有判定。
  const meModified = modifiedAtwaterME(asFed)
  // 经典 Atwater：蛋白 4、脂肪 9、碳水 4 kcal/g（参照）
  const meAtwater = classicAtwaterME(asFed)

  /* ---- 能量学全谱（总能 GE → 消化能 DE → 代谢能 ME）----
   * 见 lib/energy.js：GE 用 NRC 2006 燃烧热，DE/ME 用 NRC 消化率方程 + 尿能扣减。
   * ⚠ 水分缺失时 GE 不出数（`geProfile.ok=false`），其余口径不受影响；
   *   此时 meModified/meAtwater 仍照算（它们不依赖水分），保持既有行为不变。 */
  const geProfile = energyProfile(asFed, dmPercent, opts.species || 'dog', {
    /* 传**重量**口径的水分覆盖率：能量「可靠性」描述的是加权水分的失真幅度，
       而加权是按重量做的 —— 用条数口径会在「大料缺水、微量料全有值」时给出虚假的乐观值。 */
    moistureCoverage: moistureWeightRatio,
    // 覆盖率不足时的失真方向取决于是否走过成品水分折算（见 energy.js 的 note）
    moistureOverridden: !!(moistureAdjust && moistureAdjust.applied),
  })

  const ca = asFed.calcium
  const p = asFed.phosphorus

  const estimate = {}
  for (const [k] of NUTRIENT_FIELDS) {
    if (coverage[k].ratio >= 1) continue
    const est = renormalizedEstimate(valid, k, coverage[k])
    if (!est) continue
    // 成品水分覆盖生效时，估计值与原样值同口径，须按同一系数折算（保持内部一致）
    estimate[k] = moistureScale == null
      ? est
      : { ...est, value: Math.round(est.value * moistureScale * 100) / 100 }
  }
  // ⚠ 用 ingredientDataStatus 现算，不依赖 _zeroFields/_missingFields 派生字段 ——
  //    这样 computeRecipe 对「未装饰的裸原料行」同样正确（仓储层/测试里常直接传裸行）。
  const dataGaps = valid
    .map((x) => {
      const ds = ingredientDataStatus(x.ingredient)
      return {
        name: x.ingredient._bare || x.ingredient.name,
        code: x.ingredient.code || '',
        status: ds.status,
        zeroFields: ds.zeroFields.map((k) => FIELD_LABEL[k] || k),
        missingFields: ds.missingFields.map((k) => FIELD_LABEL[k] || k),
      }
    })
    .filter((x) => x.zeroFields.length || x.missingFields.length)

  // 钙磷比；无法计算时若因某原料钙/磷为 0 或缺失（待补录）所致，给出显式告警，避免静默误算
  const caPRatio = (() => {
    const ratio = p > 0.0001 ? r2(ca / p) : null
    const ratioDM = dm.phosphorus > 0.0001 ? r2(dm.calcium / dm.phosphorus) : null
    const base = { ca: r2(ca), p: r2(p), ratio, ratioDM }
    if (ratio == null || ratioDM == null) {
      const blockers = dataGaps
        .filter((g) => g.zeroFields.some((f) => f === '钙' || f === '磷') || g.missingFields.some((f) => f === '钙' || f === '磷'))
        .map((g) => g.name)
      if (blockers.length) {
        base.warn = `钙磷比无法计算：以下原料的钙/磷为 0 或缺失（待补录）：${blockers.join('、')}`
      }
    }
    return base
  })()

  return {
    computed: true,
    lines,
    totalWeight: totalW,
    asFed,
    dmPercent,
    dm,
    /* 风干基础（Air-Dry Basis）：与 asFed / dm 并列的第三种口径。
       `items.moisture` = refMoisture（风干参照水分），**不是** 0 —— 与干基不可互换
       （见 toAirDryBasis 的 R1~R4）。`available:false` 时 items/nfe 为 null，界面须显示「不出数」。 */
    airDry,
    nfe,
    /**
     * 成品水分覆盖的执行记录（见上）。null = 本次未请求覆盖。
     * `applied:false` 时**结果未被改动**，`reason` 说明为什么没施加 —— 界面必须显式提示，
     * 不允许把「原料加权水分」当成成品水分静默顶上去。
     */
    moistureAdjust,
    /* 代谢能两口径保持原样（全站判定挂在 meModified 上）；
       ge/de/meNRC 为新增的能量学全谱，`profile` 是完整对象（供界面一次取全）。 */
    energy: {
      meModified: r1(meModified),
      meAtwater: r1(meAtwater),
      ge: geProfile.ge,
      geKJ: geProfile.geKJ,
      geDM: geProfile.geDM,
      de: geProfile.de,
      meNRC: geProfile.meNRC,
      /* 尿能备选口径（PLOS One 2019）：**仅并列展示**，不参与任何判定。
         同时把 NRC 口径的 ME:GE 一并提上来 —— 否则界面要显示「ME : GE（NRC）」
         得绕进 profile 取，容易写出两条取值路径。 */
      meNRCAlt: geProfile.meNRCAlt,
      meGeRatio: geProfile.meGeRatio,
      meNRCGeRatio: geProfile.meNRCGeRatio,
      meNRCAltGeRatio: geProfile.meNRCAltGeRatio,
      digestibility: geProfile.digestibility,
      digestibilityExtrapolated: geProfile.digestibilityExtrapolated,
      geOk: geProfile.ok,
      geNote: geProfile.note,
      species: geProfile.species,
      profile: geProfile,
    },
    caPRatio,
    cost: {
      total: r2(cost),
      perKg: r2(cost / (totalW / 1000)),
      missingPrice: [...new Set(missingPrice)],
    },
    zeroData: [...new Set(zeroData)],
    coverage,
    coverageSummary,
    estimate,
    dataGaps,
    perKgAsFed: {
      proteinG: r1(asFed.crude_protein * 10),
      fatG: r1(asFed.crude_fat * 10),
      caG: r2(ca * 10),
      pG: r2(p * 10),
    },
  }
}

const r1 = (n) => Math.round(n * 10) / 10
const r2 = (n) => Math.round(n * 100) / 100

/**
 * 标签 / 外包装「分析保证值」营养分析（供图片识别结果使用）。
 * 输入为原样基础（as-fed）百分比，输出干物质基础、能量与钙磷比。
 * @param {Object} input { crude_protein, crude_fat, crude_fiber, crude_ash, moisture, calcium, phosphorus, chloride }
 * @param {Object} [opts] { species: 'cat'|'dog' } —— 决定 DE/ME 的消化率与尿能系数
 * @returns {{asFed, dmPercent, dm, nfe, energy, caPRatio, perKgAsFed, missing, warnings}}
 */
export function analyzeLabel(input = {}, opts = {}) {
  const asFed = {}
  const missing = []
  for (const [k, label] of NUTRIENT_FIELDS) {
    const raw = input?.[k]
    const v = raw === '' || raw == null ? NaN : Number(raw)
    if (Number.isFinite(v)) asFed[k] = v
    else { asFed[k] = 0; missing.push(label) }
  }

  const warnings = []
  const hasMoisture = missing.indexOf('水分') < 0
  if (!hasMoisture) warnings.push('缺少水分值，干物质基础无法换算（干基按原样值输出）')

  const dmPercent = hasMoisture ? 100 - asFed.moisture : 100
  // 干物质基础：水分恒为 0（见 toDryMatter 注释）
  const dm = toDryMatter(asFed, dmPercent)

  const nfe = Math.max(
    0,
    100 - asFed.moisture - asFed.crude_protein - asFed.crude_fat - asFed.crude_fiber - asFed.crude_ash,
  )
  const meModified = modifiedAtwaterME(asFed)
  const meAtwater = classicAtwaterME(asFed)

  /* 能量学全谱：水分缺失时 GE/DE 不出数 —— 通过 `moistureCoverage:0` 告知
     （asFed.moisture 在缺项时被填成 0，光看数值分不出「真 0」和「没填」）。 */
  const geProfile = energyProfile(asFed, hasMoisture ? dmPercent : 0, opts.species || 'dog', {
    moistureCoverage: hasMoisture ? 1 : 0,
  })

  const ca = asFed.calcium
  const p = asFed.phosphorus
  const sum = asFed.crude_protein + asFed.crude_fat + asFed.crude_fiber + asFed.crude_ash + asFed.moisture
  if (hasMoisture && sum > 101) warnings.push(`常规成分合计 ${r1(sum)}% 超过 100%，请核对识别结果`)
  if (asFed.crude_protein > 0 && asFed.crude_protein < 5) warnings.push('粗蛋白数值异常偏低，疑似单位或小数点识别错误')

  return {
    asFed,
    dmPercent: r1(dmPercent),
    dm: Object.fromEntries(Object.entries(dm).map(([k, v]) => [k, r2(v)])),
    nfe: r1(nfe),
    energy: {
      meModified: r1(meModified),
      meAtwater: r1(meAtwater),
      meModifiedDM: dmPercent > 0.01 ? r1((meModified / dmPercent) * 100) : null,
      ge: geProfile.ge,
      geKJ: geProfile.geKJ,
      geDM: geProfile.geDM,
      de: geProfile.de,
      meNRC: geProfile.meNRC,
      /* 尿能备选口径（PLOS One 2019）：**仅并列展示**，不参与任何判定。
         同时把 NRC 口径的 ME:GE 一并提上来 —— 否则界面要显示「ME : GE（NRC）」
         得绕进 profile 取，容易写出两条取值路径。 */
      meNRCAlt: geProfile.meNRCAlt,
      meGeRatio: geProfile.meGeRatio,
      meNRCGeRatio: geProfile.meNRCGeRatio,
      meNRCAltGeRatio: geProfile.meNRCAltGeRatio,
      digestibility: geProfile.digestibility,
      digestibilityExtrapolated: geProfile.digestibilityExtrapolated,
      geOk: geProfile.ok,
      geNote: geProfile.note,
      species: geProfile.species,
      profile: geProfile,
    },
    caPRatio: {
      ca: r2(ca),
      p: r2(p),
      ratio: p > 0.0001 ? r2(ca / p) : null,
      ratioDM: dm.phosphorus > 0.0001 ? r2(dm.calcium / dm.phosphorus) : null,
    },
    perKgAsFed: {
      proteinG: r1(asFed.crude_protein * 10),
      fatG: r1(asFed.crude_fat * 10),
      caG: r2(ca * 10),
      pG: r2(p * 10),
    },
    missing,
    warnings,
  }
}

/* ---------------- 6. 个体营养需求评估 ---------------- */

export const SPECIES = [
  { id: 'cat', label: '猫' },
  { id: 'dog', label: '狗' },
]

/* ---------------- 品种体型识别（犬种 / 猫种 → 体型） ---------------- */

/**
 * 常见犬种体型映射（按成年标准体重/体格分类）。
 * 体型用于能量需求修正（大型犬单位体重能耗更低）与标准值选择。
 */
const DOG_BREED_SIZE = {
  // —— 小型犬（成年体重 ≤10kg）——
  '博美': 'small', '吉娃娃': 'small', '贵宾犬': 'small', '玩具贵宾': 'small', '泰迪': 'small',
  '约克夏': 'small', '约克夏梗': 'small', '比熊': 'small', '比熊犬': 'small', '马尔济斯': 'small',
  '马尔济斯犬': 'small', '蝴蝶犬': 'small', '巴哥': 'small', '巴哥犬': 'small', '西施犬': 'small',
  '北京犬': 'small', '腊肠犬': 'small', '迷你雪纳瑞': 'small', '杰克罗素': 'small', '杰克罗素梗': 'small',
  '法斗': 'small', '法国斗牛犬': 'small', '波士顿梗': 'small', '博美犬': 'small', '鹿犬': 'small',
  '小鹿犬': 'small', '柯基': 'small', '柯基犬': 'small', '威尔士柯基': 'small',
  // ⚠ 数据冲突（由 lint 的 no-dupe-keys 报出，勿轻易"消警告"了事）：
  //   '柯基' 在上面「小型犬」区被定为 small，下面「中型犬」区又出现一次 medium。
  //   JS 对象字面量是后者覆盖前者，所以**当前实际生效值是 medium**；
  //   而 DOG_SIZE_HINTS 里柯基落在 small 档 —— 两处口径不一致。
  //   柯基成年体重约 10~14kg，正处 small(≤10kg) / medium(10~25kg) 的边界，取哪档会改变
  //   体型修正后的 MER（能量需求）与建议饲喂量，属营养专业判断，未擅自改动，待确认后统一。
  // —— 中型犬（10~25kg）——
  // eslint-disable-next-line no-dupe-keys -- 与上方 '柯基': 'small' 冲突，取值待确认（见上方说明）
  '柴犬': 'medium', '柯基': 'medium', '比格犬': 'medium', '比格': 'medium', '斗牛犬': 'medium',
  '英国斗牛犬': 'medium', '牛头梗': 'medium', '边境牧羊犬': 'medium', '边牧': 'medium',
  '喜乐蒂': 'medium', '喜乐蒂牧羊犬': 'medium', '哈士奇': 'medium', '萨摩耶': 'medium',
  '萨摩耶犬': 'medium', '澳洲牧羊犬': 'medium', '澳牧': 'medium', '松狮犬': 'medium', '松狮': 'medium',
  '雪纳瑞': 'medium', '标准雪纳瑞': 'medium', '大麦町': 'medium', '斑点狗': 'medium',
  '沙皮犬': 'medium', '沙皮': 'medium', '秋田': 'medium', '秋田犬': 'medium', '日本柴犬': 'medium',
  '中国沙皮犬': 'medium',
  // —— 大型犬（>25kg）——
  '金毛': 'large', '金毛寻回犬': 'large', '拉布拉多': 'large', '拉布拉多犬': 'large',
  '拉布拉多寻回犬': 'large', '德国牧羊犬': 'large', '德牧': 'large', '阿拉斯加': 'large',
  '阿拉斯加雪橇犬': 'large', '罗威纳': 'large', '罗威纳犬': 'large', '杜宾': 'large',
  '杜宾犬': 'large', '大丹犬': 'large', '藏獒': 'large', '圣伯纳': 'large', '圣伯纳犬': 'large',
  '伯恩山犬': 'large', '比利时牧羊犬': 'large', '马犬': 'large', '马里努阿犬': 'large',
  '阿富汗猎犬': 'large', '高加索犬': 'large', '纽芬兰犬': 'large', '大白熊': 'large',
  '大白熊犬': 'large', '古代牧羊犬': 'large', '古牧': 'large', '雪橇犬': 'large',
}

/** 犬种体型关键词推断（未在映射表中时按名称关键词匹配） */
const DOG_SIZE_HINTS = [
  [/阿拉斯加|藏獒|大丹|圣伯纳|纽芬兰|高加索|大白熊|罗威纳|德牧|德国牧羊|金毛|拉布拉多|杜宾|雪橇|伯恩山/, 'large'],
  [/中型|柴犬|边牧|边境牧羊|哈士奇|萨摩耶|松狮|秋田|比格|沙皮|牛头梗|澳洲牧羊/, 'medium'],
  [/小型|迷你|玩具|泰迪|吉娃娃|博美|贵宾|比熊|约克夏|马尔济斯|蝴蝶|巴哥|西施|北京|腊肠|柯基|法斗/, 'small'],
]

/**
 * 猫种体型映射（猫体型差异小，但布偶、缅因等偏大型，代谢略有差异）。
 */
const CAT_BREED_SIZE = {
  '缅因': 'large', '缅因猫': 'large', '挪威森林猫': 'large', '布偶猫': 'large', '布偶': 'large',
  '西伯利亚森林猫': 'large', '豹猫': 'large', '孟加拉豹猫': 'large', '埃及猫': 'medium',
  '英短': 'medium', '英国短毛猫': 'medium', '美短': 'medium', '美国短毛猫': 'medium',
  '波斯猫': 'medium', '异国短毛猫': 'medium', '加菲猫': 'medium', '暹罗猫': 'medium',
  '银渐层': 'small', '金渐层': 'small', '蓝猫': 'medium', '中华田园猫': 'medium',
  '狸花猫': 'medium', '橘猫': 'medium', '奶牛猫': 'medium', '三花猫': 'medium', '无毛猫': 'small',
  '斯芬克斯猫': 'small', '德文卷毛猫': 'small', '阿比西尼亚猫': 'medium', '俄罗斯蓝猫': 'medium',
}

const CAT_SIZE_HINTS = [
  [/缅因|挪威森林|西伯利亚森林|孟加拉豹/, 'large'],
  [/布偶|大型/, 'large'],
  [/小型|无毛|斯芬克斯|德文卷毛/, 'small'],
  [/中型|英短|美短|波斯|暹罗|加菲|狸花|橘猫|蓝猫/, 'medium'],
]

export const SIZE_LABELS = { small: '小型', medium: '中型', large: '大型' }

/**
 * 识别品种的物种与体型。
 * 返回 { species: 'cat'|'dog'|null, size: 'small'|'medium'|'large'|null, sizeLabel, breed } 或 null。
 * 未识别出体型时，若给出体重可据体重推断。
 */
export function identifyBreed(text = '') {
  const s = String(text || '').trim()
  if (!s) return null
  const norm = s.replace(/[犬猫狗\s·，,、。]/g, '')
  let species = null
  let size = null
  let matched = null

  // 先精确匹配猫种表
  for (const [k, v] of Object.entries(CAT_BREED_SIZE)) {
    if (s.includes(k)) { species = 'cat'; size = v; matched = k; break }
  }
  if (!species) {
    for (const [re, v] of CAT_SIZE_HINTS) {
      if (re.test(s)) { species = 'cat'; size = v; matched = s.match(re)[0]; break }
    }
  }
  // 再匹配犬种表
  if (!species) {
    for (const [k, v] of Object.entries(DOG_BREED_SIZE)) {
      if (s.includes(k)) { species = 'dog'; size = v; matched = k; break }
    }
  }
  if (!species) {
    for (const [re, v] of DOG_SIZE_HINTS) {
      if (re.test(s)) { species = 'dog'; size = v; matched = s.match(re)[0]; break }
    }
  }
  // 兜底：名称含"猫"则猫、含"犬"则狗，但体型未知
  if (!species) {
    if (/猫/.test(s)) species = 'cat'
    else if (/犬|狗/.test(s)) species = 'dog'
  }
  if (!species && !size) return null
  return {
    species,
    size,
    sizeLabel: size ? SIZE_LABELS[size] : null,
    breed: matched || null,
    raw: text,
  }
}

/** 依据体重推断体型（犬）：<10kg 小型，10~25kg 中型，>25kg 大型。猫不适用则返回 null */
export function sizeFromWeight(species, weightKg) {
  if (species !== 'dog') return null
  const w = Number(weightKg)
  if (!(w > 0)) return null
  if (w < 10) return 'small'
  if (w <= 25) return 'medium'
  return 'large'
}

export const STATUS_OPTIONS = [
  { id: 'growth', label: '生长期', desc: '幼年，骨骼发育中' },
  { id: 'adult_neutered', label: '成年已绝育', desc: '代谢略低，需控制体重' },
  { id: 'adult_intact', label: '成年未绝育', desc: '正常活动量' },
  { id: 'senior', label: '老年', desc: '代谢放缓' },
  { id: 'gestation', label: '妊娠期', desc: '怀孕中后期' },
  { id: 'lactation', label: '泌乳期', desc: '哺乳中' },
  { id: 'weight_loss', label: '减脂期', desc: '体重管理' },
]

/**
 * 运动频率选项。
 *
 * ⚠ 2026-10-25 结构纠正：活动水平**不再是独立乘数**。
 *   在 AAHA 2010 与 WSAVA 的 MER 系数表里，「低活动 / 适度 / 活跃 / 工作」
 *   与「绝育 / 未绝育 / 老年」是**同一张表的不同行**，选一个值 —— 不是相乘。
 *   此前把它做成独立乘数再与状态系数连乘，等于把活动量计了两遍：
 *   10kg 绝育成犬选「高强度」得 1.6 × 1.6 = 2.56 × RER，超出文献给出的犬 MER 上沿
 *   （NRC 口径 94–250 kcal/kg^0.75 ⇒ 0.94–2.5 倍），而默认档「适度」本就是 1.6。
 *   现改为在 `ADULT_MER_GRID` 里查表选值。
 *   `factor` 字段已移除 —— 留着它只会诱使某个渲染层再乘一次。
 */
export const ACTIVITY_OPTIONS = [
  { id: 'sedentary', label: '低活动', desc: '久坐/老年/室内为主' },
  { id: 'moderate', label: '适度活动', desc: '日常散步、室内玩耍' },
  { id: 'active', label: '活跃', desc: '每日运动、奔跑较多' },
  { id: 'high', label: '高强度', desc: '工作犬/狩猎/大量运动' },
]

/**
 * 性别选项（2026-10-25 重构）。
 *
 * ## 为什么改
 * 原取值是 `male / female / neutered` 三档 —— **选了「已绝育」就丢掉了公母信息**，
 * 而绝育状态本来已经由 `status`（成年已绝育 / 成年未绝育）表达，属重复录入且会互相矛盾
 * （出现「已绝育 + 成年未绝育」这种组合）。
 *
 * ## 绝育后公母的能量需求是否不同？—— 查证结论（诚实说明）
 * · **主流标准表不分性别**：Merck/MSD Veterinary Manual「Daily Maintenance Energy
 *   Requirements for Dogs and Cats」与 AAHA 2021 营养与体重管理指南的生命阶段系数，
 *   均只分 `Intact / Neutered / Obesity prone`（犬 1.8/1.6/1.4，猫 1.4/1.2/1.0 × RER），
 *   本项目的 `ADULT_MER_GRID` 就取自该表 ⇒ **系数不按公母分档**。
 * · **但研究确实显示差异**：Growth Curve and Energy Intake in Male and Female Cats
 *   （PubMed 33549804）指出猫的公母能量需求自幼年期即不同，且**该差异在青年绝育后依然存在**；
 *   Effect of neutering on hormonal concentrations and energy requirements in male and
 *   female cats 亦做了两性对照。但目前**没有可落地的标准系数**（无官方表值），
 *   若自造一个「母 ×0.95」之类的乘数，就是拿研究结论冒充标准表值。
 *
 * ## 因此本项目采取的做法
 * · 性别**如实区分**四档（公/母 × 绝育），信息不再丢失，供档案、报告与 BCS 复评使用；
 * · 能量系数**不按公母分档**（保持 AAHA/MSD 表值），绝不虚构；
 * · 结果里回传 `sexNote` 提示，把「标准不分公母、个体差异按 BCS 复评」讲清楚。
 *
 * `neutered` 是**历史值**（旧档案「已绝育但未记公母」），保留以兼容已有存储。
 */
export const SEX_OPTIONS = [
  { id: '', label: '未知' },
  { id: 'male', label: '公（未绝育）' },
  { id: 'female', label: '母（未绝育）' },
  { id: 'neutered_male', label: '公（已绝育）', neutered: true, sex: 'male' },
  { id: 'neutered_female', label: '母（已绝育）', neutered: true, sex: 'female' },
  { id: 'neutered', label: '已绝育（公母未记）', neutered: true, legacy: true },
]

/** 合法性别取值集合（含历史值），供档案归一化校验 */
export const SEX_IDS = SEX_OPTIONS.map((o) => o.id)

/** 该性别取值是否代表「已绝育」 */
export function isNeuteredSex(sex) {
  return !!SEX_OPTIONS.find((o) => o.id === sex)?.neutered
}

/** 只取生理性别（male / female / null）—— 从四档剥出性别维度 */
export function sexOnly(sex) {
  const o = SEX_OPTIONS.find((x) => x.id === sex)
  if (!o || !o.id) return null
  if (o.sex) return o.sex
  if (o.id === 'male' || o.id === 'female') return o.id
  return null // 历史值 'neutered'：绝育已知、公母未知
}

/** 统一性别显示文案（取代各文件自建 SEX_LABEL，避免同值不同字） */
export function sexLabel(sex) {
  return SEX_OPTIONS.find((o) => o.id === sex)?.label || '未知'
}

/**
 * 查询「物种 × 生理状态 × 活动档」的 MER 系数；组合不在表内时返回 null。
 *
 * 用途：运动频率下拉要在每个选项后显示**真实**系数。系数是二维查表结果
 * （同一档活动在不同状态下系数不同：犬绝育低活动 1.3 / 未绝育低活动 1.5），
 * 所以不能把系数写进 ACTIVITY_OPTIONS 常量 —— 那会让 UI 显示一个与实际计算不符的数字。
 * 生长/妊娠/泌乳/减重不查活动表 ⇒ 返回 null，UI 显示「按状态定」而不是硬凑值。
 */
export function activityFactorFor(species, status, activityId) {
  /* 严格校验物种：**不要**像 computeRequirements 那样把未知物种降级成 cat ——
     那里降级是为了「至少有数可算」，而这里是给 UI 显示系数，降级等于把猫的系数
     标在别的动物身上（实测过：传 'fish' 会静默返回猫的 1.2）。宁可不显示。 */
  if (species !== 'dog' && species !== 'cat') return null
  const grid = ADULT_MER_GRID[species]?.[status]
  if (!grid) return null
  const v = grid[activityId]
  return typeof v === 'number' ? v : null
}

/**
 * 绝育性别的提示文案（**不改变系数**，只解释为什么没有单独分档）。
 * 返回空串表示无需提示。
 */
export function neuterSexNote(sex) {
  if (!isNeuteredSex(sex)) return ''
  const s = sexOnly(sex)
  const base = '绝育后基础代谢下降、食欲上升，能量需求较未绝育低约 10%~20%，'
    + '已由「成年已绝育」系数体现；现行标准（Merck/MSD、AAHA 2021、WSAVA）对绝育公母采用同一系数，本系统不另设性别乘数。'
  const extra = s === 'female'
    ? '猫的对照研究（PubMed 33549804）显示公母能量需求存在差异且绝育后仍在，个体化调整请以体重与 BCS 为准。'
    : s === 'male'
      ? '猫的对照研究（PubMed 33549804）显示公母能量需求存在差异且绝育后仍在，公猫增重风险同样需监测。'
      : '旧档案只记了「已绝育」而未记公母，如需按性别给建议请补全。'
  return base + extra
}

/**
 * 成体维持期 MER 系数：status × activity **查表选值**（不是相乘）。
 *
 * 出处：AAHA 2010 Nutritional Assessment Guidelines 与 WSAVA Global Nutrition Toolkit
 * 的生命阶段/活动表（两家取值一致，本节按该表逐格落地）：
 *
 *   犬：绝育成体 1.6｜未绝育 1.8｜老年 1.4
 *       低活动 1.2–1.4（取 1.3）｜活跃 2.0｜工作犬 2.0–3.0（取中段）
 *   猫：绝育成体 1.2｜未绝育 1.4｜老年 1.1
 *       低活动 1.0｜活跃 1.6｜猫无公认「工作犬」档，高强度按 1.6 封顶
 *
 * ⚠ 交叉格（如「未绝育 + 高强度」「老年 + 活跃」）标准表未直接给出，
 *   按同表相邻值外推，**上限封在 2.6（犬）/ 1.8（猫）**：再高就不是"维持"，
 *   而是工作犬极端工况，应由兽医按个体定，不该由默认表给。
 */
const ADULT_MER_GRID = {
  dog: {
    adult_neutered: { sedentary: 1.3, moderate: 1.6, active: 2.0, high: 2.4 },
    adult_intact: { sedentary: 1.5, moderate: 1.8, active: 2.2, high: 2.6 },
    senior: { sedentary: 1.2, moderate: 1.4, active: 1.6, high: 1.8 },
  },
  cat: {
    adult_neutered: { sedentary: 1.0, moderate: 1.2, active: 1.4, high: 1.6 },
    adult_intact: { sedentary: 1.2, moderate: 1.4, active: 1.6, high: 1.8 },
    senior: { sedentary: 0.9, moderate: 1.1, active: 1.3, high: 1.5 },
  },
}

/**
 * 非成体状态系数：这些状态下**活动水平不参与**。
 * 理由：生长、妊娠、泌乳、减重的能量需求由生理过程主导，标准表给的是单值；
 * 再按活动量调整会造出「生长 2.0 × 活动 1.2」这类标准里不存在的组合。
 * 减重尤其：0.8（猫）/ 1.0（犬）就是目标值，再打折会跌破代谢安全线。
 */
const STATUS_FACTORS = {
  cat: { weight_loss: 0.8 },
  dog: { weight_loss: 1.0 },
}

/**
 * 妊娠 / 泌乳：**区间**而非单值（2026-10-25 依 FEDIAF 2025 原表重算）。
 *
 * ## 一手依据
 * FEDIAF Nutritional Guidelines 2025（Publication September 2025）：
 *   · Table VII-8b（犬 · growth and reproduction，原文引 NRC 2006b/2006h）
 *   · Table VII-10（猫 · growth and reproduction）
 * 这是欧盟宠物食品行业标准原文，比任何二手转述都硬；本项目此前只有「NRC 2006 转述」，
 * 本次把公式逐条落成断言（`energy-coef-test.mjs` ⑨ 组直接复算原文公式）。
 *
 * ## 原文公式
 *   犬妊娠  前 4 周  132 × BW^0.75
 *           后 5 周  132 × BW^0.75 + 26 × BW
 *   犬泌乳  1~4 崽  145 × BW^0.75 + 24n × BW × L
 *           5~8 崽  145 × BW^0.75 + [96 + 12(n−4)] × BW × L
 *           L = 0.75(第1周) / 0.95(第2周) / 1.1(第3周) / 1.2(第4周)
 *   猫妊娠  140 × BW^0.67
 *   猫泌乳  <3 崽   100 × BW^0.67 + 18 × BW × L
 *           3~4 崽  100 × BW^0.67 + 60 × BW × L
 *           >4 崽   100 × BW^0.67 + 70 × BW × L
 *           L = 0.9(第1-2周) / 1.2(第3-4周) / 1.1(第5周) / 1.0(第6周) / 0.8(第7周)
 *
 * ## 区间是怎么来的（不是估的）
 * 把上述公式在「物种合理体重 × 窝仔数 1~8 × 各周 L」上全域扫描，取 min/max 后除以
 * RER（70×BW^0.75）。扫描脚本结果：
 *   犬妊娠 1.89 ~ 2.92 ｜ 犬泌乳 2.44 ~ 8.94 ｜ 猫妊娠 1.66 ~ 1.89 ｜ 猫泌乳 1.55 ~ 3.32
 *
 * ## ⚠ 为什么之前差点改错（记录下来防止再犯）
 * 先前依据知识库里的二手表述（「产奶量 10/20/25 g/kgBW^0.75 × 2.42」）推出犬泌乳只有
 * 2.42~2.94，于是判「现状 4.0 高估 36%~65%」。查原文后**该结论不成立**：FEDIAF 的
 * 产奶项是 `系数 × BW × L`（正比于**体重**而非代谢体重，且带周因子 L），
 * 跨度达 3.7 倍。现状 4.0 落在区间内，真正的问题是「用单值掩盖了跨度」——
 * 8 崽第 4 周需要 8.94×RER，按 4.0 喂会**严重欠喂**，母犬掉膘、泌乳量下降。
 * 教训：二手转述可以指路，**定值必须回原文复算**。
 */
const STATUS_RANGES = {
  cat: {
    gestation: {
      low: 1.66, mid: 1.80, high: 1.89,
      basis: 'FEDIAF 2025 Table VII-10：妊娠期 140 kcal/kg BW^0.67（不分段，随体重折算 1.66~1.89 RER）',
      dependentOn: '体重（0.67 与 RER 的 0.75 指数不同，比值随体重微动）',
    },
    lactation: {
      low: 1.55, mid: 2.90, high: 3.32,
      basis: 'FEDIAF 2025 Table VII-10：100×BW^0.67 + 18/60/70×BW×L（按 <3 / 3~4 / >4 崽分档）',
      dependentOn: '窝仔数（三档）与泌乳周数（L 从 0.9 升至 1.2，第 7 周回落 0.8）',
    },
  },
  dog: {
    gestation: {
      low: 1.89, mid: 2.50, high: 2.92,
      basis: 'FEDIAF 2025 Table VII-8b：前 4 周 132×BW^0.75，后 5 周再加 26×BW',
      dependentOn: '妊娠阶段（前 4 周即维持量 =1.89 RER；后 5 周随体重升至 2.41~2.92）',
    },
    lactation: {
      low: 2.44, mid: 4.00, high: 8.94,
      basis: 'FEDIAF 2025 Table VII-8b：145×BW^0.75 + [24n 或 96+12(n−4)]×BW×L',
      dependentOn: '窝仔数（1~8 崽）与泌乳周数（L 0.75→1.2）；跨度可达 3.7 倍，大窝仔务必取上限',
    },
  },
}

/**
 * 生长系数按 <4 月 / ≥4 月分档（犬猫都要分）。
 * AAHA/WSAVA：犬 3.0 / 2.0；猫 2.5 / 2.0。
 * ⚠ 此前猫只给 2.5、不分月龄，5 月龄猫 MER 因此高估 18%、8 月龄高估 15%；
 *   幼猫期持续超喂是后期肥胖的已知起点。
 */
function growthFactor(species, ageM) {
  const young = ageM !== null && Number.isFinite(ageM) && ageM <= 4
  if (species === 'cat') return young ? 2.5 : 2.0
  return young ? 3.0 : 2.0
}

/**
 * MER 下限：不得低于 RER 的 80%。
 * 出处：ISFM 猫科营养指南「减重期不得低于 80% RER」（更低增加营养缺乏与
 * 肝脂肪变性风险）；对维持期同样适用 —— 低于 RER 的"维持"在生理上讲不通。
 * 这是**兜底闸门**：正常组合不应触发（减重猫 0.8 恰好等于下限）。
 */
export const MER_FLOOR_RATIO = 0.8

/**
 * 依据体重、年龄、性别、生理状态、品种体型、运动频率计算能量需求。
 *
 * 口径（2026-10-25 全面对齐 AAHA 2010 / WSAVA / NRC 2006）：
 *   RER = 70 × BW^0.75（**犬猫同式**，见 energy.js 的 RER_EXPONENT）
 *   MER = RER × 系数
 *   系数 = 成体查 ADULT_MER_GRID（status × activity 选值）
 *         / 生长按 4 月分档 / 妊娠·泌乳·减重取 STATUS_FACTORS 单值
 *   体型**不再作为乘数**：BW^0.75 异速指数本身已表达「大型犬单位体重代谢率更低」，
 *   再乘 0.9/1.1 属重复修正（会让 5kg 与 40kg 的犬相对标准值各偏 ±10%）。
 *   体型信息改为 `sizeHint` 提示文本，不参与算术。
 */
export function computeRequirements(profile, opts = {}) {
  const species = profile.species === 'dog' ? 'dog' : 'cat'
  const w = Math.max(0.2, Number(profile.weightKg) || 0)
  // RER：犬猫均 70×BW^0.75（NRC 2006 / AAHA 2010）—— 定义在 energy.js，全站唯一一处
  const rer = restingEnergy(species, w)

  const ageM = profile.ageMonths ?? parseAge(profile.ageText)
  // 状态缺省时由年龄推断。
  // 老年阈值：犬 84 月（7 岁，大型犬可早至 6 岁）；猫 120 月（10 岁）。
  // AAFP/AAHA 猫生命周期把 7–10 岁归「成熟」、>10 岁才归「老年」；
  // 此前两者都用 84 月，会让 7 岁的猫被按老年系数供能。
  let status = profile.status
  if (!status) {
    if (ageM !== null && ageM < 12) status = 'growth'
    else if (ageM !== null && ageM > (species === 'cat' ? 120 : 84)) status = 'senior'
    else status = 'adult_neutered'
  }

  /* —— MER 系数：成体查表、生长分档、其余取单值 —— */
  const activity = profile.activity || 'moderate'
  const actObj = ACTIVITY_OPTIONS.find((a) => a.id === activity)
  const actId = actObj ? actObj.id : 'moderate'

  let factor
  /** 妊娠/泌乳：区间口径（含 kcal 换算）；其他状态为 null */
  let merRange = null
  const grid = ADULT_MER_GRID[species][status]
  if (grid) {
    factor = grid[actId]
  } else if (status === 'growth') {
    factor = growthFactor(species, ageM)
  } else if (STATUS_RANGES[species] && STATUS_RANGES[species][status]) {
    /* 妊娠 / 泌乳：取区间中值算 MER（保证既有字段语义与既有调用方不变），
       同时把上下限一并回传 —— 真实需求落在区间内的哪一点，取决于窝仔数与周数。 */
    const rg = STATUS_RANGES[species][status]
    merRange = {
      ...rg,
      lowKcal: r1(rer * rg.low),
      midKcal: r1(rer * rg.mid),
      highKcal: r1(rer * rg.high),
    }
    factor = rg.mid
  } else {
    factor = STATUS_FACTORS[species][status] ?? 1.4
  }

  /* —— 体型：只出提示，不参与算术（BW^0.75 已表达体型差异） —— */
  let size = profile.size
  if (!size && profile.breed) {
    const info = identifyBreed(profile.breed)
    if (info && info.size) size = info.size
  }
  if (!size && species === 'dog') size = sizeFromWeight(species, w)
  const sizeFactor = 1
  let sizeHint = ''
  if (species === 'dog' && size === 'large') {
    sizeHint = '大型犬单位体重能量需求偏低，已由 BW^0.75 异速指数体现；生长期需控速以防骨科疾病'
  } else if (species === 'dog' && size === 'small') {
    sizeHint = '小型犬单位体重能量需求偏高，已由 BW^0.75 异速指数体现；建议少食多餐防低血糖'
  }

  /* —— MER 与下限兜底 —— */
  // 活动水平已并入 factor，不再单独相乘；此处仅保留兼容字段（恒为 1）
  const activityFactor = 1
  const merFloor = MER_FLOOR_RATIO * rer
  const merRaw = rer * factor
  const mer = Math.max(merRaw, merFloor)
  const merFloorApplied = merRaw < merFloor

  /* ---- 达标标准：由「目标市场」决定要同时满足哪些体系 ----
   * 标准条款与合并规则全部放在 lib/standards.js，这里只做解析与派生兼容视图。
   * marketId 优先取 opts.market → profile.market → 默认 'cn'（仅中国 GB）。
   */
  const stage = stageOf(status)
  const marketId = opts.market || profile.market || DEFAULT_MARKET
  const stdResolved = resolveStandard({ marketId, species, stage })

  /**
   * 兼容视图：agent.js / viz.jsx 等仍按 cp / fat / ca / p / cl / caP / meDmMin 读取。
   * 值取自已解析的合并标准（因此会随目标市场变化），缺失项目为 null。
   */
  const itemOf = (k) => stdResolved.items.find((it) => it.key === k)
  const legacyStandard = {
    cp: itemOf('crude_protein')?.min ?? null,
    fat: itemOf('crude_fat')?.min ?? null,
    ca: itemOf('calcium')?.min ?? null,
    p: itemOf('phosphorus')?.min ?? null,
    cl: itemOf('chloride')?.min ?? null,
    fiberMax: itemOf('crude_fiber')?.max ?? null,
    ashMax: itemOf('crude_ash')?.max ?? null,
    caP: itemOf('caP') ? [itemOf('caP').min, itemOf('caP').max] : null,
    meDmMin: itemOf('me')?.min ?? null,
    lysine: itemOf('lysine')?.min ?? null,
    taurine: itemOf('taurine')?.min ?? null,
  }

  return {
    species,
    speciesLabel: species === 'cat' ? '猫' : '犬',
    weightKg: w,
    ageMonths: ageM,
    ageText: profile.ageText || '',
    sex: profile.sex || '',
    /** 统一性别文案（公（已绝育）这类），渲染层直接用它，不要各自拼 */
    sexLabel: sexLabel(profile.sex),
    /** 绝育性别的说明（不改变系数）；未绝育/未知时为空串 */
    sexNote: neuterSexNote(profile.sex),
    breed: profile.breed || '',
    status,
    statusLabel: STATUS_OPTIONS.find((s) => s.id === status)?.label || status,
    size,
    sizeLabel: size ? SIZE_LABELS[size] : null,
    activity,
    activityLabel: actObj ? actObj.label : '适度活动',
    rer: r1(rer),
    /** 猫的 NRC 维持能量参照（100×BW^0.67，kcal/日）；犬为 null。仅并列展示，不参与计算 */
    rerNrcCat: species === 'cat' ? r1(felineNrcMer(w) ?? 0) : null,
    /** 最终采用的 MER 系数（成体 = status×activity 查表选值；生长按 4 月分档；
        妊娠/泌乳取区间中值；减重为单值） */
    merFactor: factor,
    /**
     * 妊娠/泌乳的能量**区间**（其他状态为 null）。
     * { low, mid, high, lowKcal, midKcal, highKcal, basis, dependentOn }
     * 用法：界面必须把 `low~high` 与 `dependentOn` 一起展示，只显示中值等于丢掉
     * 「真实需求取决于窝仔数/周数」这一关键信息。`mid` 即 `merFactor`。
     */
    merRange,
    /**
     * 能量系数的一句话说明 —— **渲染层统一引用本字段**，不要各处自写文案。
     * 妊娠/泌乳不是「按活动量查表」，若沿用旧话术会向用户传达错误的取值依据。
     */
    merFactorNote: merRange
      ? `区间 ${merRange.low}~${merRange.high}×，此处取中值；实际值取决于${merRange.dependentOn}`
      : '状态与活动查表选值',
    /** 兼容字段：体型已不参与算术，恒为 1（渲染层用 `!== 1` 判断即自动隐去） */
    sizeFactor,
    /** 兼容字段：活动已并入 merFactor，恒为 1 */
    activityFactor,
    /** 体型提示（不参与算术；无提示时为空串） */
    sizeHint,
    mer: r1(mer),
    /** 代谢安全下限 = 0.8 × RER（ISFM 猫科指南红线） */
    merFloor: r1(merFloor),
    /** true = 计算值低于下限、已钳制到 merFloor（正常组合不应为 true） */
    merFloorApplied,
    marketId: stdResolved.marketId,
    marketLabel: stdResolved.marketLabel,
    stage,
    /** 完整标准（含逐项来源、条款出处、不可判定项）——界面与报告用它 */
    standardResolved: stdResolved,
    standardItems: stdResolved.items,
    /** 兼容视图（旧字段名） */
    standard: legacyStandard,
    standardSource: `${stdResolved.sourceLabel} · ${stage === 'growth' ? '生长/繁殖/泌乳期' : '成年维持期'}`,
  }
}

/** 解析年龄文本：'3个月'/'六个月'/'2岁'/'成年'/'幼年' → 月龄（或 null） */
export function parseAge(text = '') {
  const s = String(text || '').replace(/\s/g, '')
  let m = s.match(/(\d+(?:\.\d+)?)\s*(个?月|个月)/)
  if (m) return Number(m[1])
  m = s.match(/([一二两三四五六七八九十半]+)\s*(个?月|月龄)/)
  if (m) return cnToNumber(m[1])
  m = s.match(/(\d+(?:\.\d+)?)\s*岁/)
  if (m) return Number(m[1]) * 12
  m = s.match(/([一二两三四五六七八九十]+)\s*(岁|周岁)/)
  if (m) return (cnToNumber(m[1]) || 0) * 12
  if (/幼| kitten|puppy/i.test(s)) return 6
  if (/成年|成体|adult/i.test(s)) return 36
  if (/老年|senior/i.test(s)) return 108
  return null
}

/** 中文数字 → 数值（支持 一~一百二 风格与"半"） */
export function cnToNumber(str = '') {
  const s = String(str)
  if (s === '半') return 0.5
  const D = { 零: 0, 一: 1, 二: 2, 两: 2, 三: 3, 四: 4, 五: 5, 六: 6, 七: 7, 八: 8, 九: 9 }
  if (/^\d+(\.\d+)?$/.test(s)) return Number(s)
  if (/^[零一二两三四五六七八九]+$/.test(s)) {
    return s.split('').reduce((acc, c) => acc * 10 + D[c], 0)
  }
  // 十/百组合
  let m = s.match(/^(?:([一二两三四五六七八九])?百)?(?:([零一二两三四五六七八九]?))?十([零一二两三四五六七八九])?$/)
  if (m) {
    const bai = m[1] ? D[m[1]] : s.includes('百') ? 1 : 0
    const shi = m[2] !== undefined && m[2] !== '' ? D[m[2]] : 1
    const ge = m[3] ? D[m[3]] : 0
    return (s.includes('百') ? bai * 100 : 0) + shi * 10 + ge
  }
  if (s === '十') return 10
  return null
}

/**
 * 综合评估：配方 × 个体档案 → 逐项达标结论 + 配比建议 + 数据质量提示。
 * recipe: computeRecipe() 的结果；req: computeRequirements() 的结果。
 *
 * M0 变化（计划批次 1.1 / 1.2）：
 *   · 判定项改为遍历「已解析的合并标准」items —— 支持**下限 / 上限 / 区间**，
 *     项目随目标市场变化（GB 的粗灰分·粗纤维上限、犬粮赖氨酸、猫粮牛磺酸都会出现）；
 *   · **数据不足的项目不再冒充「未达标」**：ok=null、status='nodata'，
 *     界面显示「无法判定（缺原料数据）」而不是红叉；
 *   · 每行带 `coverage`，数据不全时标 `status:'low'`，界面显示覆盖率；
 *   · 配比建议在覆盖率过低时**不给出具体添加量**（避免在数据不可靠时给出精确数字）。
 */
export function evaluateRecipe(recipe, req) {
  if (!recipe?.computed || !req) return null
  const dm = recipe.dm
  const cov = recipe.coverage || {}
  const moistureClass = classifyMoisture(100 - recipe.dmPercent)
  // 按本配方实测水分重新解析一次：湿粮型产品适用更严的牛磺酸档位
  const std = resolveStandard({
    marketId: req.marketId,
    species: req.species,
    stage: req.stage || stageOf(req.status),
    moistureClass: moistureClass.id,
  })

  const meDm = dmPercentToMeDm(recipe)
  const ALIAS = {
    crude_protein: 'cp', crude_fat: 'fat', calcium: 'ca', phosphorus: 'p',
    chloride: 'cl', caP: 'cap', me: 'me',
  }

  /** 计算类指标（钙磷比 / 代谢能）本身没有原料字段，用其依赖项的覆盖率取最保守值 */
  const coverageOf = (item) => {
    if (item.computed === 'caP') {
      const a = cov.calcium
      const b = cov.phosphorus
      if (!a || !b) return null
      const ratio = Math.min(a.ratio, b.ratio)
      return { ...a, ratio, label: item.label, status: ratio >= 1 ? 'full' : (ratio > 0 ? 'partial' : 'none'), belowLow: ratio > 0 && ratio < COVERAGE_LOW }
    }
    if (item.computed === 'me') {
      const list = ['crude_protein', 'crude_fat', 'moisture', 'crude_fiber', 'crude_ash'].map((k) => cov[k]).filter(Boolean)
      if (!list.length) return null
      const ratio = Math.min(...list.map((x) => x.ratio))
      return { ...list[0], ratio, label: item.label, status: ratio >= 1 ? 'full' : (ratio > 0 ? 'partial' : 'none'), belowLow: ratio > 0 && ratio < COVERAGE_LOW }
    }
    return item.dataField ? cov[item.dataField] : null
  }

  const rows = []
  for (const item of std.items) {
    const key = ALIAS[item.key] || item.key
    const c = coverageOf(item)
    let value = null
    if (item.computed === 'me') value = meDm
    else if (item.computed === 'caP') value = recipe.caPRatio.ratioDM
    else if (item.dataField) value = r2(dm[item.dataField])

    const base = {
      key,
      nutrient: item.key,
      label: item.label,
      unit: item.unit,
      target: item.text,
      sources: item.sources,
      cites: item.cites,
      coverage: c ? r2(c.ratio * 100) : null,
      coverageHave: c ? c.have : null,
      coverageTotal: c ? c.total : null,
      wetApplied: !!item.wetApplied,
    }

    // ① 系统没有这项原料数据（如氨基酸）——不冒充未达标
    if (!item.available) {
      rows.push({ ...base, value: null, ok: null, status: 'nodata', note: '原料库无该指标字段，暂无法判定（需先补检测数据）' })
      continue
    }
    // ② 算不出值（如磷为 0 时钙磷比无意义）
    if (value == null) {
      rows.push({ ...base, value: null, ok: null, status: 'nodata', note: '本配方算不出该指标（依赖项为 0 或缺失）' })
      continue
    }
    // ③ 一条原料数据都没有 —— 数值不可信，不判定
    if (c && c.status === 'none') {
      rows.push({ ...base, value, ok: null, status: 'nodata', note: `全部 ${c.total} 条参与原料都无${item.label}数据，该数值不可用` })
      continue
    }

    const isRange = item.kind === 'range'
    const okMin = item.min == null ? true : (isRange ? value >= item.min - 0.02 : value >= item.min * 0.98)
    const okMax = item.max == null ? true : (isRange ? value <= item.max + 0.02 : value <= item.max * 1.02)
    const ok = okMin && okMax
    const dataLow = !!(c && c.belowLow)
    rows.push({
      ...base,
      value,
      min: item.min,
      max: item.max,
      ok,
      status: !ok ? 'fail' : (dataLow ? 'low' : 'ok'),
      note: dataLow
        ? `数据不足：本项仅 ${c.have}/${c.total} 条原料有数值（覆盖率 ${Math.round(c.ratio * 100)}%），结论仅供参考`
        : '',
    })
  }

  /* ---- 配比建议 ---- */
  const suggestions = []
  const rowOf = (k) => rows.find((x) => x.nutrient === k)
  const reliable = (k) => {
    const c = cov[k]
    return !!c && c.status !== 'none' && !c.belowLow
  }

  // 钙：绝对量不足或比值偏低，且钙数据可靠时才给具体添加量
  const caRow = rowOf('calcium')
  const caPItem = std.items.find((it) => it.key === 'caP')
  const caSource = findIngredient('碳酸钙') || findIngredient('磷酸三钙')
  if (caSource && caRow && reliable('calcium') && caRow.status === 'fail') {
    const targetCa = caRow.min
    const needCaDM = Math.max(0, targetCa - dm.calcium)
    const caPctAsFed = caSource.calcium || 38.3 // 原样 Ca %
    const addG = (needCaDM / 100) * (recipe.dmPercent / 100) / (caPctAsFed / 100) * 1000
    if (addG > 0.5 && addG < 100) {
      suggestions.push({
        type: 'ca',
        text: `钙 ${r2(dm.calcium)}%DM 低于标准下限 ${caRow.min}%DM。建议每 1kg 配方添加约 ${r1(addG)}g「${caSource.name}」（钙 ${caPctAsFed}%）。添加后请重新计算复核。`,
      })
    }
  }
  const capRow = rowOf('caP')
  if (capRow && capRow.status === 'fail' && caPItem && reliable('calcium') && reliable('phosphorus')) {
    const higher = capRow.value > (caPItem.max ?? Infinity)
    suggestions.push({
      type: 'cap',
      text: higher
        ? `钙磷比 ${capRow.value}:1 偏高（目标 ${caPItem.text}）。可降低高钙原料（碳酸钙/蛋壳粉等）比例，或适当提高含磷原料（肉类/内脏）占比。`
        : `钙磷比 ${capRow.value}:1 偏低（目标 ${caPItem.text}）。可提高高钙原料比例，或降低含磷原料占比。`,
    })
  }
  const cpRow = rowOf('crude_protein')
  if (cpRow && cpRow.status === 'fail' && cpRow.min != null) {
    const need = r1(((cpRow.min - dm.crude_protein) / 100) * (recipe.dmPercent / 100) * 1000)
    suggestions.push({
      type: 'cp',
      text: `粗蛋白 ${r2(dm.crude_protein)}%DM 低于 ${req.standardSource} 的下限 ${cpRow.min}%DM。每 1kg 配方约需再补充 ${need}g 蛋白质：可提高肉类/肉粉比例，或选用高蛋白原料（如谷朊粉、大豆分离蛋白、鸡肉粉等）。`,
    })
  }
  const fatRow = rowOf('crude_fat')
  if (fatRow && fatRow.status === 'fail' && fatRow.min != null) {
    const needG = ((fatRow.min - dm.crude_fat) / 100) * (recipe.dmPercent / 100) * 1000 / 0.99
    suggestions.push({
      type: 'fat',
      text: `粗脂肪 ${r2(dm.crude_fat)}%DM 低于下限 ${fatRow.min}%DM。可添加鸡脂油/鱼油等脂肪源（约 ${r1(needG)}g 每千克配方，按脂肪含量折算）。`,
    })
  }
  const ashRow = rowOf('crude_ash')
  if (ashRow && ashRow.status === 'fail' && ashRow.max != null) {
    suggestions.push({
      type: 'ash',
      text: `粗灰分 ${r2(dm.crude_ash)}%DM 高于上限 ${ashRow.max}%DM，矿物质添加过多或原料骨含量偏高，可检查肉粉/骨源原料用量。`,
    })
  }

  /* ---- 数据质量提示（M0 的核心产出：把缺失显式说出来，而不是藏起来） ---- */
  const noValueRows = rows.filter((x) => x.status === 'nodata')
  const lowRows = rows.filter((x) => x.status === 'low')
  if (noValueRows.length) {
    suggestions.push({
      type: 'data-nodata',
      text: `无法判定 ${noValueRows.length} 项：${noValueRows.map((x) => x.label).join('、')}。`
        + '原料库里这些指标没有可用数值，或本配方算不出该指标。'
        + '在数据补齐之前，本系统不会给出这几项「达标/未达标」的结论。',
    })
  }
  if (recipe.dataGaps?.length) {
    const missN = recipe.dataGaps.filter((g) => g.missingFields.length).length
    const zeroN = recipe.dataGaps.filter((g) => g.zeroFields.length).length
    const show = recipe.dataGaps.slice(0, 6).map((g) => g.name).join('、')
    const more = recipe.dataGaps.length > 6 ? ` 等 ${recipe.dataGaps.length} 条` : ''
    suggestions.push({
      type: 'data-gaps',
      text: `本配方有 ${recipe.dataGaps.length} 条原料存在数据问题（${show}${more}）：`
        + `${missN} 条有空值（确定未录入，这些字段按 0 参与加权，会使对应指标系统性偏低）；`
        + `${zeroN} 条有填为 0 的字段（无法区分真零与"未录入写成 0"，需逐条复核）。`
        + '明细见「①-2 营养组成数据」下方的数据完整性清单。',
    })
  }
  if (lowRows.length) {
    suggestions.push({
      type: 'data-low',
      text: `以下指标正数值不足、结论仅供参考（未给出具体添加量）：`
        + `${lowRows.map((x) => `${x.label}（${x.coverageHave}/${x.coverageTotal} 条原料有正数值）`).join('；')}。`,
    })
  }

  const allPass = rows.every((r) => r.ok !== false)
  const judged = rows.filter((r) => r.ok !== null).length
  return {
    rows,
    suggestions,
    allPass,
    judged,
    totalRows: rows.length,
    noDataCount: noValueRows.length,
    lowCount: lowRows.length,
    wetFood: recipe.dmPercent < 40,
    standard: std,
    sourceLabel: `${std.sourceLabel} · ${std.items.length} 项`,
  }
}

/** 代谢能换算到干物质基础 kcal/kg DM */
function dmPercentToMeDm(recipe) {
  if (recipe.dmPercent <= 0.01) return 0
  return r0(recipe.energy.meModified / (recipe.dmPercent / 100))
}
const r0 = (n) => Math.round(n)

/** 由代谢能与 MER 计算每日饲喂量（g/天） */
export function dailyFeeding(recipe, req) {
  if (!recipe?.computed || !req?.mer) return null
  const me = recipe.energy.meModified // kcal/kg 原样
  if (me < 100) return null
  const gramsPerDay = (req.mer / me) * 1000
  return {
    gramsPerDay: r0(gramsPerDay),
    costPerDay: r2((recipe.cost.perKg * gramsPerDay) / 1000),
    proteinPerDay: r1((recipe.asFed.crude_protein / 100) * gramsPerDay),
    caPerDay: r2((recipe.asFed.calcium / 100) * gramsPerDay),
    pPerDay: r2((recipe.asFed.phosphorus / 100) * gramsPerDay),
  }
}

/* ------- 6.5 剂量 → 配方添加比例（补充「参考值查询」与「配方计算」之间缺失的一跳） ------- */

/**
 * 剂量单位 → 毫克。只收质量单位：IU 等生物学单位**无质量当量**，
 * 强行换算会造出假精度，故不支持（调用方应先自行折算成 mg 当量）。
 */
const DOSE_UNIT_TO_MG = { ug: 0.001, mcg: 0.001, mg: 1, g: 1000 }

/** 剂量口径。四种基准不可互相"默认"，因为文献/标准的原文基准不同。 */
export const DOSE_BASES = ['per_day_flat', 'per_kg_bw', 'per_1000kcal', 'per_kg_dm']
export const DOSE_UNITS = Object.keys(DOSE_UNIT_TO_MG)

/**
 * 每日目标活性物 → 配方添加比例。
 *
 * ## 为什么需要
 * 系统原本两侧都有、中间断着：
 *   · 左侧 `computeRequirements` 给 MER；`dailyFeeding` 给每日克数；
 *   · 右侧 `evaluateRecipe` 能比对"配方实际提供了多少"；
 *   · 但**「每天该摄入 X mg」→「配方该加百分之几」这一步没人算**，
 *     于是功能物添加量只能靠经验拍——这是最容易被夸大宣称的地方。
 *
 * ## 口径来源（★ 不重写公式）
 * `mer` 与 `gramsPerDay` 均由既有函数产出（`computeRequirements` / `dailyFeeding`）。
 * 本函数**只做换算**，不自行推导能量，避免系统内出现第二套 MER 口径。
 *
 * ## 参数
 *   basis        剂量基准，见 DOSE_BASES
 *   dose         剂量数值（按 unit 计）
 *   unit         mg|g|ug|mcg
 *   mer          MER kcal/天（basis=per_1000kcal 时必需）
 *   gramsPerDay  每日饲喂量 g（原样基础）；basis=per_kg_dm 时必需
 *   dmPercent    成品干物质 %（basis=per_kg_dm 时必需）
 *   weightKg     basis=per_kg_bw 时必需
 *   purity       原料中有效物分数 (0,1]，如 50% 纯度填 0.5
 *   retention    加工存留率 (0,1]，热敏物必填
 *   inclusionPct 可选：给定添加比例做**反向达成度**校验
 *
 * ## 返回
 *   targetMg        每日目标活性物 mg
 *   rawMaterialMg   需投入的原料量 mg（已按 purity×retention 折减）
 *   inclusionPct    添加比例 %（原样基础）
 *   inclusionGPerKg 每 kg 成品添加克数
 *   以及 delivered / achievement 反向校验字段（给了 inclusionPct 时）
 *
 * ## 不静默兜底
 * 缺必需入参时**抛错**（由门面 check 钩子转成 usage 错误），不假设默认值——
 * 剂量类计算的默认值一旦猜错，结果是"看起来合理的错数"。
 */
export function doseToFormula(opts = {}) {
  const {
    basis = 'per_day_flat', dose, unit = 'mg',
    mer, gramsPerDay, dmPercent, weightKg,
    purity = 1, retention = 1, inclusionPct,
  } = opts

  const num = (v, name) => {
    const n = Number(v)
    if (!Number.isFinite(n)) throw new Error(`${name} 必须是有限数字，收到 ${v}`)
    return n
  }
  const frac = (v, name) => {
    const n = Number(v)
    if (!(n > 0 && n <= 1)) throw new Error(`${name} 必须落在 (0,1]，收到 ${v}`)
    return n
  }

  if (!DOSE_BASES.includes(basis)) throw new Error(`未知剂量口径 ${basis}`)
  const k = DOSE_UNIT_TO_MG[unit]
  if (!k) throw new Error(`未知剂量单位 ${unit}`)

  const doseMg = num(dose, 'dose') * k
  if (doseMg < 0) throw new Error('dose 不能为负')
  const p = frac(purity, 'purity')
  const rt = frac(retention, 'retention')

  // 各口径所需的额外输入，缺就报错，不猜
  let targetMg
  if (basis === 'per_day_flat') {
    targetMg = doseMg
  } else if (basis === 'per_kg_bw') {
    const w = num(weightKg, 'weightKg')
    if (w <= 0) throw new Error('weightKg 必须 > 0')
    targetMg = doseMg * w
  } else if (basis === 'per_1000kcal') {
    const m = num(mer, 'mer')
    if (m <= 0) throw new Error('mer 必须 > 0')
    targetMg = (doseMg * m) / 1000
  } else {
    const g = num(gramsPerDay, 'gramsPerDay')
    const dm = num(dmPercent, 'dmPercent')
    if (g <= 0) throw new Error('gramsPerDay 必须 > 0')
    if (!(dm > 0 && dm <= 100)) throw new Error('dmPercent 必须落在 (0,100]')
    const dmKg = (g * dm) / 100 / 1000
    targetMg = doseMg * dmKg
  }

  const gpd = num(gramsPerDay, 'gramsPerDay')
  if (gpd <= 0) throw new Error('gramsPerDay 必须 > 0（每日饲喂量，原样基础）')

  const rawMaterialMg = targetMg / (p * rt)
  const inclusionPctVal = rawMaterialMg / (gpd * 10)

  const out = {
    basis,
    dose: num(dose, 'dose'),
    unit,
    targetMg: r2(targetMg),
    purity: p,
    retention: rt,
    rawMaterialMg: r2(rawMaterialMg),
    // ★ 这里是 r4 而不是 r2：添加比例常在 0.01%~1% 区间，r2 会把 0.092% 抹成 0.09%
    //   （相对误差 2.17%，在配方上不是噪音而是错数）。2026-10-25 由 Python↔JS 对拍抓出，
    //   当时判据容差 5e-3 恰好掩盖了它 —— 放宽容差等于放弃对拍的意义。
    inclusionPct: r4(inclusionPctVal),
    inclusionGPerKg: r4(inclusionPctVal * 10),
    gramsPerDay: r2(gpd),
  }

  if (inclusionPct != null) {
    const inc = num(inclusionPct, 'inclusionPct')
    if (inc < 0) throw new Error('inclusionPct 不能为负')
    const delivered = ((inc / 100) * gpd * 1000) * p * rt
    out.reverse = {
      inclusionPct: inc,
      deliveredMg: r1(delivered),
      achievementPct: targetMg > 0 ? r2((delivered / targetMg) * 100) : null,
      // 达成的另一面是过量：>110% 时提示，避免"多加更保险"的直觉
      verdict: delivered / targetMg > 1.1 ? 'over'
        : delivered / targetMg < 0.9 ? 'under' : 'ok',
    }
  }
  return out
}

/* ---------------- 7. 成本核算表（对齐「闪闪亮猫粮」成本明细表格式） ---------------- */

/**
 * 成本核算表引擎。按「产品成本明细表」逻辑计算：
 *   添加量 = 添加比例 × 产量KG
 *   金额   = 采购单价 × 添加量（解冻前用料 = 添加量 × 失水系数，默认 1）
 *   出成率 = Σ添加比例
 *   原辅料单位成本 = Σ金额 / 产量
 *   原辅料吨耗成本 = 单位成本 × 1000
 *   半成品成本合计 = 吨耗成本 + 加工费（直接人工/能耗摊销等）
 *   单位成本 = 半成品合计 / 产量KG
 *   单位成本(含损耗) = 单位成本 × (1 + 损耗率)
 *
 * 参数 costSheet：
 *   { productName, batchCount(袋数), gramPerBag(克重), lossRate(损耗率),
 *     processingFeePerTon(加工费 元/吨),
 *     lines: [{ code, name, ratio(添加比例), unitPrice(采购单价 元/kg), note }] }
 */
export function computeCostSheet(costSheet) {
  const batchCount = Number(costSheet.batchCount) || 0
  const gramPerBag = Number(costSheet.gramPerBag) || 0
  const yieldKg = Number(costSheet.yieldKg)
  // 产量KG：优先显式给出，否则 = 袋数 × 克重 / 1000
  const totalKg = yieldKg > 0 ? yieldKg : (batchCount * gramPerBag) / 1000
  if (!(totalKg > 0)) return null

  const lossRate = Number(costSheet.lossRate) || 0
  const feePerTon = Number(costSheet.processingFeePerTon) || 0

  const lines = (costSheet.lines || [])
    // ⚠ 过滤只认「有效占比」，不再用 `|| l.name` 兜底 ——
    //   旧写法的 `|| l.name` 会让 **ratio=0 的行**（用量为 0 的原料）留在明细里：
    //   金额算出来是 0（不进加权，数值上无害），但它会出现在成本表与 Excel 导出中，
    //   让使用者以为配方里真有这么一味用量为 0 的原料。零用量项应与
    //   `computeRecipe` 的 `filter(x => x.weight > 0)` 保持同一口径：**彻底剔除**。
    .filter((l) => l && Number(l.ratio) > 0)
    .map((l) => {
      const ratio = Number(l.ratio) || 0
      const unitPrice = Number(l.unitPrice) || 0
      const addAmount = ratio * totalKg // 添加量 kg
      const amount = unitPrice * addAmount // 金额 元
      return {
        code: l.code || '',
        name: l.name || '',
        unit: l.unit || 'kg',
        ratio,
        addAmount: r4(addAmount),
        unitPrice,
        amount: r4(amount),
        note: l.note || '',
      }
    })

  const totalAmount = lines.reduce((s, l) => s + l.amount, 0) // Σ金额
  const totalRatio = lines.reduce((s, l) => s + l.ratio, 0) // 出成率（Σ添加比例）

  const materialUnitCost = totalAmount / totalKg // 原辅料单位成本 元/kg
  const materialTonCost = materialUnitCost * 1000 // 原辅料吨耗成本
  const semiTotal = materialTonCost + feePerTon // 半成品成本合计 元/吨
  const unitCost = semiTotal / 1000 // 单位成本 元/kg
  const unitCostWithLoss = unitCost * (1 + lossRate) // 单位成本(含损耗)

  return {
    productName: costSheet.productName || '',
    batchCount,
    gramPerBag,
    totalKg: r4(totalKg),
    lossRate,
    feePerTon,
    lines,
    totalAmount: r4(totalAmount),
    totalRatio: r4(totalRatio), // 出成率
    materialUnitCost: r4(materialUnitCost),
    materialTonCost: r4(materialTonCost),
    semiTotal: r4(semiTotal),
    unitCost: r4(unitCost),
    unitCostWithLoss: r4(unitCostWithLoss),
  }
}

const r4 = (n) => Math.round(n * 10000) / 10000
