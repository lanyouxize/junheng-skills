/**
 * 输出与退出码契约（三个技能完全一致，便于 AI 与脚本统一处理）。
 *
 *   · 成功：stdout 一行 JSON；stderr 为空；退出码 0
 *   · 失败：stdout 为空；stderr 一行 JSON；退出码 ≥ 2
 *     错误也走 JSON，是为了让调用方不必解析自然语言；而 `error.message`
 *     本身就是人话，人直接看得懂。
 *   · 退出码：0 成功 / 1 内部错误 / 2 用法或输入错误 / 3 前置条件缺失
 *
 * ⚠ 刻意**不把「域内负结果」当失败**：例如能量计算因缺水分而无法出数，
 *   它是一个**有效回答**（`ok:false` + 原因说明），退出码仍是 0。
 *   把「算不出」混进错误码，会让调用方误以为是自己参数写错了而反复重试。
 */

export const EXIT = {
  OK: 0,
  INTERNAL: 1,
  USAGE: 2,
  PRECONDITION: 3,
}

/** 退出码说明（写进 help 与 describe，保证机器与人都能读到同一份口径） */
export const EXIT_DOC = {
  0: '成功：命令执行完毕，结果在 stdout 的 JSON 里（含「算不出」这类域内负结果）',
  1: '内部错误：命令抛出了未预期异常 —— 这是 bug，请保留 stderr 原文',
  2: '用法/输入错误：命令名、JSON 语法、参数名或参数值不合法，命令未执行',
  3: '前置条件缺失：源码目录不可读等环境问题，命令未执行',
}

/** 默认 IO：真实进程的 stdout / stderr / stdin */
export function makeIo() {
  return {
    out: (s) => process.stdout.write(s),
    err: (s) => process.stderr.write(s),
    readStdin: readAllStdin,
  }
}

export async function readAllStdin() {
  const chunks = []
  for await (const c of process.stdin) {
    chunks.push(Buffer.isBuffer(c) ? c : Buffer.from(String(c)))
  }
  return Buffer.concat(chunks).toString('utf8')
}

/**
 * 严格序列化：**不许静默丢键**。
 * JSON.stringify 默认会把函数值、undefined、Symbol 悄悄丢掉 —— 于是「返回了半个对象」
 * 却看不出错。这里改为：函数 / Symbol / BigInt 直接抛错（转成内部错误），
 * undefined 显式写成 null（保留键，明确表达「此字段无值」）。
 * 循环引用由 JSON.stringify 自身抛错，交给调用方兜。
 */
export function stringifyStrict(value, pretty = false) {
  const out = JSON.stringify(value, (key, val) => {
    if (typeof val === 'function') throw new Error(`输出含函数值，无法序列化 —— 位置 "${key || '(根)'}"`)
    if (typeof val === 'symbol') throw new Error(`输出含 Symbol，无法序列化 —— 位置 "${key || '(根)'}"`)
    if (typeof val === 'bigint') throw new Error(`输出含 BigInt，无法序列化 —— 位置 "${key || '(根)'}"`)
    return val === undefined ? null : val
  }, pretty ? 2 : 0)
  if (out === undefined) throw new Error('输出无法序列化（根值为 undefined）')
  return out
}

/**
 * 写成功信封。返回退出码（序列化失败时自动降级为内部错误）。
 * @returns {number} EXIT.OK 或 EXIT.INTERNAL
 */
export function emit(io, envelope, pretty = false) {
  let text
  try {
    text = stringifyStrict(envelope, pretty)
  } catch (e) {
    return emitError(io, {
      name: (envelope && envelope.skill) || 'unknown',
      command: (envelope && envelope.command) || null,
      kind: 'internal',
      message: `结果无法序列化为 JSON：${(e && e.message) || e}`,
    })
  }
  io.out(text + '\n')
  return EXIT.OK
}

/**
 * 写错误信封到 stderr。
 * @returns {number} 与 kind 对应的退出码
 */
export function emitError(io, { name = 'unknown', command = null, kind = 'usage', message = '', details = [] }) {
  const code = kind === 'precondition' ? EXIT.PRECONDITION : (kind === 'internal' ? EXIT.INTERNAL : EXIT.USAGE)
  const env = { ok: false, skill: name, command, error: { kind, message, details } }
  let text
  try {
    text = stringifyStrict(env, false)
  } catch {
    text = JSON.stringify({ ok: false, skill: name, command, error: { kind, message: String(message), details: [] } })
  }
  io.err(text + '\n')
  return code
}
