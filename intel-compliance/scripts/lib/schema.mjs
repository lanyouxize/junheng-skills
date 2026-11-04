/**
 * 声明式参数校验器。
 *
 * 设计取向：**宁可拒绝，也不静默兜底**。
 * 参数名写错却静默走默认值，会得到一个「看着对、其实按另一个参数算的」结果 ——
 * 在营养/法规场景里这是最危险的失败模式（结论错但看不出错）。因此：
 *   · 未知参数名 → 报错 + 拼写建议，不忽略；
 *   · 类型不符 → 报错。仅接受「数值型字符串」这一种宽松形式（AI 生成 JSON 时常给加引号的数字），
 *     其余一律拒绝，不做「看着像就转」的猜测；
 *   · 枚举越界 → 报错并列出允许值；
 *   · 全部错误一次报出（不是遇到第一个就停），减少来回试错轮次；
 *   · 空字符串 / null 一律按「未提供」处理 —— 否则 Number('') === 0 会让水分缺失悄悄变成 0 水分。
 *
 * 本期**支持**数组类型（第 1 期新增，P1 的配方入参需要）。
 * 数组是「错误会被稀释」的地方 —— 10 项里错 1 项，结果只是「略微不对」，肉眼极难发现，
 * 所以这里对数组做**元素级校验 + 元素级路径前缀**（如 `items[2].weight`），让定位无歧义。
 * 数组的 `spec.fields` 描述元素结构（若元素是对象），`spec.itemType` 描述标量元素类型。
 */

export function isPlainObject(v) {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

export function typeName(v) {
  if (v === null) return 'null'
  if (Array.isArray(v)) return 'array'
  return typeof v
}

const NUM_RE = /^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$/

/** 严格数值化：只接受有限数 / 数值型字符串；拒绝 NaN、Infinity、纯空白、布尔 */
export function toNumber(v) {
  if (typeof v === 'number') return Number.isFinite(v) ? v : null
  if (typeof v === 'string') {
    const s = v.trim()
    if (!NUM_RE.test(s)) return null
    const n = Number(s)
    return Number.isFinite(n) ? n : null
  }
  return null
}

/** 布尔化：只接受 true/false 与 "true"/"false"（不接受 1/0、yes/no，避免口径含糊） */
export function toBoolean(v) {
  if (typeof v === 'boolean') return v
  if (typeof v === 'string') {
    const s = v.trim().toLowerCase()
    if (s === 'true') return true
    if (s === 'false') return false
  }
  return null
}

/** 编辑距离（带上限提前返回），用于「参数名拼错」时给建议 */
export function editDistance(a, b, max = 3) {
  if (Math.abs(a.length - b.length) > max) return max + 1
  let prev = new Array(b.length + 1)
  let cur = new Array(b.length + 1)
  for (let j = 0; j <= b.length; j++) prev[j] = j
  for (let i = 1; i <= a.length; i++) {
    cur[0] = i
    let best = cur[0]
    for (let j = 1; j <= b.length; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1
      cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
      if (cur[j] < best) best = cur[j]
    }
    if (best > max) return max + 1
    const t = prev
    prev = cur
    cur = t
  }
  return prev[b.length]
}

/** 找最接近的候选名（拼写建议）；无足够接近者返回 null */
export function closestKey(name, candidates, max = 2) {
  let best = null
  let bestD = max + 1
  for (const c of candidates) {
    const d = editDistance(String(name).toLowerCase(), String(c).toLowerCase(), max)
    if (d < bestD) { bestD = d; best = c }
  }
  return bestD <= max ? best : null
}

/** 校验单个字段；返回 { value } 或 { errors } */
function coerceOne(raw, spec, label) {
  const type = spec.type || 'string'

  if (type === 'number') {
    const n = toNumber(raw)
    if (n === null) {
      return { errors: [{ path: label, code: 'not_number', message: `"${label}" 需要一个数字，收到 ${typeName(raw)}（${JSON.stringify(raw)}）` }] }
    }
    if (spec.integer && !Number.isInteger(n)) {
      return { errors: [{ path: label, code: 'not_integer', message: `"${label}" 需要整数，收到 ${n}` }] }
    }
    if (spec.min != null && n < spec.min) {
      return { errors: [{ path: label, code: 'below_min', message: `"${label}" 不能小于 ${spec.min}，收到 ${n}` }] }
    }
    if (spec.max != null && n > spec.max) {
      return { errors: [{ path: label, code: 'above_max', message: `"${label}" 不能大于 ${spec.max}，收到 ${n}` }] }
    }
    return { value: n }
  }

  if (type === 'boolean') {
    const b = toBoolean(raw)
    if (b === null) {
      return { errors: [{ path: label, code: 'not_boolean', message: `"${label}" 需要 true 或 false，收到 ${typeName(raw)}（${JSON.stringify(raw)}）` }] }
    }
    return { value: b }
  }

  if (type === 'object') {
    // `open: true` 表示「透传对象」：接受任意键，不校验子字段。
    // 用途：上游门面产出的结果对象（如 computeRecipe 的返回）在本命令只做搬运，
    // 门面无法也不该枚举它的字段。若强制校验，串联调用会被误拒 ——
    // 第 1 期实测踩到：labeling.draft 的 recipe 参数报了 43 条 unknown_key。
    if (spec.open) {
      if (!isPlainObject(raw)) {
        return { errors: [{ path: label, code: 'not_object', message: `"${label}" 需要一个 JSON 对象，收到 ${typeName(raw)}` }] }
      }
      return { value: raw }
    }
    const r = validate(raw, spec.fields || {}, { path: label })
    return r.ok ? { value: r.value } : { errors: r.errors }
  }

  if (type === 'array') {
    if (!Array.isArray(raw)) {
      return { errors: [{ path: label, code: 'not_array', message: `"${label}" 需要一个数组，收到 ${typeName(raw)}（${JSON.stringify(raw)}）` }] }
    }
    if (spec.minItems != null && raw.length < spec.minItems) {
      return { errors: [{ path: label, code: 'too_few', message: `"${label}" 至少需要 ${spec.minItems} 项，收到 ${raw.length} 项` }] }
    }
    if (spec.maxItems != null && raw.length > spec.maxItems) {
      return { errors: [{ path: label, code: 'too_many', message: `"${label}" 最多 ${spec.maxItems} 项，收到 ${raw.length} 项` }] }
    }
    const out = []
    const errors = []
    raw.forEach((item, i) => {
      // 元素级路径：让「第 3 项写错」能被直接定位，而不是笼统说「数组有问题」
      const itemLabel = `${label}[${i}]`
      if (spec.fields) {
        const r = validate(item, spec.fields, { path: itemLabel })
        if (r.ok) out.push(r.value)
        else errors.push(...r.errors)
      } else if (spec.itemOpen) {
        // `itemOpen: true` 表示「数组元素是透传对象」：接受任意键，不校验子字段。
        // 用途：上游产出的记录对象（如库内文章、配方表行）在本命令只做搬运，
        // 门面无法也不该枚举它们的字段；强制校验会误拒合法输入。
        // 这是对象级 `spec.open`（见上方 type==='object' 分支）在数组元素上的下一层 ——
        // 同一问题的两种写法必须同时支持，否则「串联调用」在数组入参处仍会被误拒。
        // 元素级路径与 not_object 文案沿用 object 分支口径，保证定位一致。
        // `itemHint` 是**可选**的域内提示后缀（由门面提供，如「每条可为 {id?, text?, meta?}」）：
        // 它让「该写成什么样」跟错误一起给出，避免把域内文案硬编码进通用校验器。
        if (!isPlainObject(item)) {
          const hint = spec.itemHint ? ` —— ${spec.itemHint}` : ''
          errors.push({ path: itemLabel, code: 'not_object', message: `"${itemLabel}" 需要一个 JSON 对象，收到 ${typeName(item)}（${JSON.stringify(item)}）${hint}` })
        } else {
          out.push(item)
        }
      } else {
        const r = coerceOne(item, { type: spec.itemType || 'string' }, itemLabel)
        if (r.errors) errors.push(...r.errors)
        else out.push(r.value)
      }
    })
    return errors.length ? { errors } : { value: out }
  }

  // string
  if (typeof raw !== 'string') {
    return { errors: [{ path: label, code: 'not_string', message: `"${label}" 需要字符串，收到 ${typeName(raw)}（${JSON.stringify(raw)}）` }] }
  }
  if (spec.enum && !spec.enum.includes(raw)) {
    return { errors: [{ path: label, code: 'not_in_enum', message: `"${label}" 取值 "${raw}" 不在允许集合内（允许：${spec.enum.join(' | ')}）` }] }
  }
  return { value: raw }
}

/**
 * 校验参数字典。
 * @param {*} input 解析后的 JSON（应为普通对象）
 * @param {object} params 字段表 { 字段名: { type, required, default, enum, min, max, integer, desc, fields } }
 * @param {{path?: string}} [opts] path 用于嵌套字段的错误定位（如 asFed.crude_protein）
 * @returns {{ ok: boolean, value: object, errors: Array<{path:string,code:string,message:string}> }}
 */
export function validate(input, params = {}, { path = '' } = {}) {
  const errors = []
  const value = {}
  const keys = Object.keys(params || {})
  const label = (k) => (path ? `${path}.${k}` : k)

  let src = input
  if (src == null) src = {}
  if (!isPlainObject(src)) {
    return { ok: false, value, errors: [{ path: path || '(根)', code: 'not_object', message: `参数必须是 JSON 对象，收到 ${typeName(src)}` }] }
  }

  for (const k of Object.keys(src)) {
    if (!keys.includes(k)) {
      const near = closestKey(k, keys)
      errors.push({
        path: label(k),
        code: 'unknown_key',
        message: `未知参数 "${label(k)}"${near ? `，是否想写 "${near}"？` : ''}`
          + (keys.length ? `（本层允许：${keys.join(' | ')}）` : '（本命令不接受任何参数）'),
      })
    }
  }

  for (const k of keys) {
    const spec = params[k]
    const has = Object.prototype.hasOwnProperty.call(src, k)
    const raw = src[k]
    // 关键：空串与 null 视同「未提供」。否则 Number('') === 0 会把缺失值伪装成 0。
    const absent = !has || raw === null || (typeof raw === 'string' && raw.trim() === '')
    if (absent) {
      if (spec.required) {
        errors.push({ path: label(k), code: 'required', message: `缺少必填参数 "${label(k)}"${spec.desc ? `（${spec.desc}）` : ''}` })
      } else if (spec.default !== undefined) {
        value[k] = spec.default
      }
      continue
    }
    const r = coerceOne(raw, spec, label(k))
    if (r.errors) errors.push(...r.errors)
    else value[k] = r.value
  }

  return { ok: errors.length === 0, value, errors }
}
