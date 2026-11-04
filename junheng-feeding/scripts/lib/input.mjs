/**
 * 输入获取：把「命令行参数 + 标准输入」统一成一份待校验的 JSON 对象。
 *
 * 第 0 期最核心的稳定性诉求就是「减少输入环节的 bug」，因此这里把已知的坑
 * 全部挡在门口，并且**每一类都有独立文案**（不合并成一句「参数错误」）：
 *   BOM、CRLF、首尾空白、空串、畸形 JSON、多余位置参数、未知选项、
 *   「JSON 位置参数 与 --stdin 同时给」的来源歧义。
 * 它们统一归到退出码 2（用法/输入错误），且不进入任何计算。
 *
 * 刻意**不做**的事：不隐式读标准输入。只有显式给 `--stdin` / `-` 才读 ——
 * 否则「交互式终端下忘了给参数」会挂死在等输入上，是同类工具最常见的事故形态。
 */

/** 允许的选项。未列出的 `-x` / `--xxx` 一律报错，防止拼错后被静默忽略 */
const FLAG_ALIASES = {
  '--help': 'help',
  '-h': 'help',
  '--pretty': 'pretty',
  '--stdin': 'stdin',
}

/** POSIX 惯例的管道标记 */
export const STDIN_TOKEN = '-'

/**
 * 需要取值（而非布尔）的选项：写成 `--as <参数名>`。
 *
 * ## 为什么需要它（跨技能串联）
 * 门面成功时输出**信封** `{ok, skill, command, basis, disclaimer, data}`，
 * 而下游命令要的往往只是**内层对象**（如 `labeling.draft` 的 `recipe` 参数）。
 * 于是直接 `A | B --stdin` 会让 B 把信封的 `ok`/`skill`/`data` 当成未知参数报错。
 *
 * `--as <参数名>` 的语义是：**把读到的整个 JSON 直接当作这个参数的值**。
 * 于是 `... | node cli/labeling.mjs guaranteed --stdin --as recipe` 就能通。
 * 不传 `--as` 时行为不变（仍要求参数本身是 `{参数名: 值}` 形状的对象）。
 */
export const VALUE_OPTIONS = {
  '--as': 'as',
}

/** 剥 BOM、去首尾空白。BOM 在 Windows 重定向与记事本产物里非常常见 */
export function normalizeText(s) {
  let t = String(s == null ? '' : s)
  if (t.charCodeAt(0) === 0xfeff) t = t.slice(1)
  return t.replace(/^\s+/, '').replace(/\s+$/, '')
}

/** 截断长文本用于报错上下文（保留头尾，中间省略） */
export function clip(text, max = 120) {
  const t = String(text == null ? '' : text)
  return t.length <= max ? t : `${t.slice(0, max - 20)}…（共 ${t.length} 字符）`
}

/**
 * 把 JSON.parse 的异常翻译成可操作文案。
 * V8 不同版本给的信息不一样：新旧两种格式分别是「… at position N …」与
 * 「Unexpected token 'x', "<片段>" is not valid JSON」。两种都要能读，
 * 否则调用方（尤其是 AI）拿到的是一句无从下手的英文。
 */
export function describeJsonError(text, err) {
  const msg = String((err && err.message) || err)
  const tail = `。收到的原文：${clip(text)}`
  const m = /position (\d+)/.exec(msg)
  if (!m) return `JSON 解析失败：${msg}${tail}`
  const i = Number(m[1])
  const before = text.slice(0, i)
  const line = before.split('\n').length
  const col = i - before.lastIndexOf('\n')
  const around = text.slice(Math.max(0, i - 16), i + 16)
  return `JSON 解析失败（第 ${line} 行第 ${col} 列附近：…${around}…）：${msg}${tail}`
}

/**
 * 解析 JSON 参数。
 * 空文本按「空对象」处理（无参命令的常见写法）；顶层不是对象/数组会被校验层拒绝。
 */
export function parseJson(text, { source = 'JSON 参数' } = {}) {
  const t = normalizeText(text)
  if (t === '') return { ok: true, value: {} }
  if (t[0] !== '{' && t[0] !== '[') {
    return {
      ok: false,
      message: `${source}不是合法 JSON：应以 { 开头，实际是 "${t.slice(0, 12)}"。`
        + '若内容含空格或中文，请把整个 JSON 用单引号包住（Windows cmd 下用双引号）。',
    }
  }
  try {
    return { ok: true, value: JSON.parse(t) }
  } catch (e) {
    return { ok: false, message: describeJsonError(t, e) }
  }
}

/** 拆参数：返回 { command, jsonArg, flags } 或 { error } */
export function parseArgv(argv = []) {
  const flags = {}
  const positional = []
  for (let i = 0; i < argv.length; i += 1) {
    const a = String(argv[i])
    if (a === STDIN_TOKEN) {
      if (flags.stdin) return { error: '管道标记 "-" 重复出现' }
      flags.stdin = true
      continue
    }
    if (a.startsWith('-') && a.length > 1) {
      // 取值型选项：--as <值>（用于跨技能管道串联，见 VALUE_OPTIONS 注释）
      if (VALUE_OPTIONS[a]) {
        const key = VALUE_OPTIONS[a]
        const next = argv[i + 1]
        if (next == null || (String(next).startsWith('-') && String(next).length > 1)) {
          return { error: `选项 "${a}" 需要一个值（示例：${a} recipe）` }
        }
        if (flags[key] != null) return { error: `选项 "${a}" 重复出现` }
        flags[key] = String(next)
        i += 1
        continue
      }
      const key = FLAG_ALIASES[a]
      if (!key) return { error: `未知选项 "${a}"（可用：--help | -h | --pretty | --stdin | --as <参数名> | -）` }
      flags[key] = true
      continue
    }
    positional.push(a)
  }
  if (positional.length > 2) {
    return {
      error: `多余的位置参数：${positional.slice(2).join(' ')}。`
        + 'JSON 参数只允许一个（记得用单引号包住整个 JSON），或改用 --stdin 从标准输入读取。',
    }
  }
  return { command: positional[0] == null ? null : positional[0], jsonArg: positional[1] == null ? null : positional[1], flags }
}

/**
 * 汇总入口：argv → { ok:true, command, args, flags, source } | { ok:false, kind:'usage', message }
 * 所有输入类问题都在此收敛，调用方只需把它翻成退出码 2。
 */
export async function acquireArgs({ argv = [], readStdin } = {}) {
  const p = parseArgv(argv)
  if (p.error) return { ok: false, kind: 'usage', message: p.error }
  const { command, jsonArg, flags } = p

  if (jsonArg != null && flags.stdin) {
    return { ok: false, kind: 'usage', message: '不能同时提供 JSON 位置参数与 --stdin（参数来源有歧义）；两者二选一。' }
  }
  if (jsonArg == null && !flags.stdin) {
    return { ok: true, command, args: {}, flags, source: '(未提供参数)' }
  }

  let text = ''
  let source = 'JSON 参数'
  if (flags.stdin) {
    if (typeof readStdin !== 'function') return { ok: false, kind: 'usage', message: '当前环境不支持 --stdin。' }
    try {
      text = await readStdin()
    } catch (e) {
      return { ok: false, kind: 'usage', message: `读取标准输入失败：${(e && e.message) || e}` }
    }
    source = '标准输入'
  } else {
    text = jsonArg
  }

  const parsed = parseJson(text, { source })
  if (!parsed.ok) return { ok: false, kind: 'usage', message: parsed.message }

  // `--as <参数名>`：把读到的整个 JSON 直接当作该参数的值。
  // 这是跨技能串联的关键 —— 上游输出的是信封，下游要的是内层对象。
  // 若读到的正好是信封（含 data 字段），自动剥到 data，避免调用方还得再写一层提取。
  if (flags.as) {
    let value = parsed.value
    // 自动剥信封：只在「看起来是信封」时才剥（必须有 data 且带 ok/skill 特征），
    // 否则会误伤本来就叫 data 的合法业务对象。
    const looksLikeEnvelope = value && typeof value === 'object' && !Array.isArray(value)
      && Object.prototype.hasOwnProperty.call(value, 'data')
      && (Object.prototype.hasOwnProperty.call(value, 'ok') || Object.prototype.hasOwnProperty.call(value, 'skill'))
    const unwrapped = looksLikeEnvelope ? value.data : value
    return {
      ok: true,
      command,
      args: { [flags.as]: unwrapped },
      flags,
      source: looksLikeEnvelope ? `${source}（已剥信封层，取 data）` : source,
      unwrappedEnvelope: looksLikeEnvelope,
    }
  }

  return { ok: true, command, args: parsed.value, flags, source }
}
