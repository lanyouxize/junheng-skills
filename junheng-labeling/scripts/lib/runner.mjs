/**
 * 命令注册表 + 主入口。
 *
 * 设计要点：
 *   1. `runCli` **返回**退出码而不是调用 process.exit —— 于是测试可以在进程内直接断言，
 *      不依赖 spawn 子进程（本沙箱禁止 node 再派生子进程，spawn 方案会导致测试「跑不动」）。
 *      真正的 process.exit 只发生在门面文件的主入口分支里。
 *   2. IO 可注入（`io.out` / `io.err` / `io.readStdin`）—— 测试据此捕获 stdout/stderr。
 *   3. `describe` 是内置命令，从**注册表本身**生成机器可读接口说明，
 *      于是「命令表」只有一处真源，SKILL.md 与它的一致性可以被守卫校验。
 */
import { EXIT, EXIT_DOC, emit, emitError, makeIo } from './output.mjs'
import { acquireArgs } from './input.mjs'
import { validate, closestKey } from './schema.mjs'

/** 内置命令（不占用各技能自己的命令命名空间） */
export const BUILTIN_COMMANDS = ['describe']

/** 机器可读接口说明（供 AI / 脚本消费，也是 SKILL.md 一致性的比对基准） */
export function describePayload({ name, version, summary, basis, disclaimer, commands }) {
  return {
    name,
    version,
    summary,
    basis,
    disclaimer,
    exitCodes: EXIT_DOC,
    inputForms: [
      "node scripts/cli.mjs <命令> '<JSON 参数>'",
      'node scripts/cli.mjs <命令> --stdin     # 从标准输入读 JSON',
      'node scripts/cli.mjs --help',
      'node scripts/cli.mjs <命令> --help',
    ],
    outputSuccess: '{ ok:true, skill, command, basis, disclaimer, data } （写 stdout）',
    outputError: '{ ok:false, skill, command, error:{ kind, message, details[] } } （写 stderr）',
    commands: Object.entries(commands).map(([n, c]) => ({ name: n, summary: c.summary || '', params: c.params || {} })),
  }
}

/** 参数名列宽（顶层与嵌套共用，保证缩进基线一致） */
const PARAM_COL = 18

/** 单个参数的属性摘要（顶层与嵌套字段共用同一口径，避免两套渲染规则漂移） */
function paramBits(s) {
  const bits = [s.type || 'string', s.required ? '必填' : '可选']
  if (s.enum) bits.push(`允许：${s.enum.join(' | ')}`)
  if (s.default !== undefined) bits.push(`默认：${s.default}`)
  if (s.min != null) bits.push(`最小：${s.min}`)
  if (s.max != null) bits.push(`最大：${s.max}`)
  if (s.minItems != null) bits.push(`至少 ${s.minItems} 项`)
  if (s.maxItems != null) bits.push(`最多 ${s.maxItems} 项`)
  return bits.join('  ')
}

/**
 * 渲染一层参数（object.fields / array.fields **递归展开**）。
 *
 * 为什么必须递归：只渲染顶层时，`profile.market` 这类**嵌套枚举**在 `--help` 里完全看不见，
 * 调用方（尤其 AI）只能靠试错去撞「允许值」—— 而这恰恰是本工具最想避免的失败模式
 * （猜错枚举 → 命令按另一个口径算出一个「看着对」的结果）。
 * 校验层早已报出完整枚举，`--help` 不该比它更少。
 */
function renderParams(params, lines, indent) {
  for (const k of Object.keys(params || {})) {
    const s = params[k]
    lines.push(`${indent}${String(k).padEnd(PARAM_COL)} ${paramBits(s)}`)
    if (s.desc) lines.push(`${indent}${' '.repeat(PARAM_COL)} ${s.desc}`)
    if ((s.type === 'object' || s.type === 'array') && s.fields) {
      lines.push(`${indent}${' '.repeat(PARAM_COL)} └ ${s.type === 'array' ? '元素' : '字段'}：`)
      renderParams(s.fields, lines, `${indent}  `)
    } else if (s.type === 'array' && s.itemType) {
      lines.push(`${indent}${' '.repeat(PARAM_COL)} └ 元素类型：${s.itemType}`)
    }
  }
}

/** 单个参数的示例取值：优先文档默认值；无默认则枚举取首值、数值取下限（无下限取 0）、数组给 1 个元素 */
function sampleValue(s) {
  const t = s.type || 'string'
  // ★ 优先取**文档默认值** —— 否则会出现「骨架里的值 ≠ 文档写的默认值」这种自相矛盾
  //   （实测：`stage` 默认 adult、枚举首值 growth，不取默认就会给出与说明不一致的骨架）。
  if (t === 'number') return s.default !== undefined ? s.default : (s.min != null ? s.min : 0)
  if (t === 'boolean') return s.default !== undefined ? s.default : false
  if (t === 'object') return s.fields ? sampleObject(s.fields) : {}
  if (t === 'array') {
    if (s.fields) return [sampleObject(s.fields)]
    if (s.itemType) return [sampleValue({ type: s.itemType })]
    return []
  }
  if (s.default !== undefined) return s.default
  if (Array.isArray(s.enum) && s.enum.length) return s.enum[0]
  // 必填的自由文本不能给空串 —— 校验层把空串当「未提供」，骨架会当场被判缺必填。
  return s.required ? '<必填>' : ''
}

function sampleObject(params) {
  const out = {}
  for (const k of Object.keys(params || {})) out[k] = sampleValue(params[k])
  return out
}

/** 人类可读帮助（全局 / 单命令两种形态） */
export function renderHelp({ name, version, summary, disclaimer, commands, command = null }) {
  const lines = []
  lines.push(`${name} v${version}`)
  if (summary) lines.push(summary)
  lines.push('')

  if (command && commands[command]) {
    const c = commands[command]
    lines.push(`命令：${command}`)
    if (c.summary) lines.push(`  ${c.summary}`)
    lines.push('')
    const keys = Object.keys(c.params || {})
    if (keys.length === 0) {
      lines.push('参数：无')
    } else {
      lines.push('参数：')
      renderParams(c.params, lines, '  ')
    }
    lines.push('')
    lines.push(`示例（JSON 可直接粘贴；优先取文档默认值，无默认则枚举取首值 / 数值取下限）：`)
    lines.push(`  node scripts/cli.mjs ${command} '${JSON.stringify(sampleObject(c.params))}'`)
  } else {
    lines.push('用法：')
    lines.push("  node scripts/cli.mjs <命令> '<JSON 参数>' [--pretty]")
    lines.push('  node scripts/cli.mjs <命令> --stdin [--pretty]')
    lines.push('  node scripts/cli.mjs --help')
    lines.push('  node scripts/cli.mjs <命令> --help')
    lines.push('')
    lines.push('退出码：')
    for (const k of ['0', '1', '2', '3']) lines.push(`  ${k}  ${EXIT_DOC[k]}`)
    lines.push('')
    lines.push('命令：')
    lines.push(`  ${'describe'.padEnd(18)} 输出机器可读的接口说明（命令、参数、退出码）`)
    for (const [n, c] of Object.entries(commands)) lines.push(`  ${n.padEnd(18)} ${c.summary || ''}`)
    if (disclaimer) {
      lines.push('')
      lines.push('诚实性红线：')
      lines.push(`  ${disclaimer}`)
    }
  }
  lines.push('')
  return lines.join('\n')
}

/**
 * 跑一次调用。
 * @param {object} cfg
 * @param {string} cfg.name       技能名（进信封的 skill 字段）
 * @param {string} [cfg.version]
 * @param {string} [cfg.summary]
 * @param {string} [cfg.basis]    结果口径，默认 'theoretical'（理论计算值）
 * @param {string} [cfg.disclaimer] 诚实性红线原文，随每次成功响应一起返回
 * @param {object} cfg.commands   { 命令名: { summary, params, run(value, ctx) } }
 * @param {string[]} [cfg.argv]
 * @param {object} [cfg.io]
 * @returns {Promise<number>} 退出码
 */
export async function runCli({
  name,
  version = '1.0.0',
  summary = '',
  basis = 'theoretical',
  disclaimer = '',
  commands = {},
  argv = [],
  io = makeIo(),
}) {
  const acquired = await acquireArgs({ argv, readStdin: io.readStdin })
  if (!acquired.ok) {
    return emitError(io, { name, command: null, kind: acquired.kind || 'usage', message: acquired.message })
  }

  const { command, args, flags } = acquired
  const pretty = !!flags.pretty
  const allNames = [...Object.keys(commands), ...BUILTIN_COMMANDS]

  if (!command) {
    io.out(renderHelp({ name, version, summary, disclaimer, commands }))
    return EXIT.OK
  }

  if (command === 'describe') {
    return emit(io, {
      ok: true,
      skill: name,
      command,
      basis,
      disclaimer,
      data: describePayload({ name, version, summary, basis, disclaimer, commands }),
    }, pretty)
  }

  if (flags.help) {
    if (!commands[command]) {
      return emitError(io, {
        name,
        command,
        kind: 'usage',
        message: `未知命令 "${command}"，无法显示其帮助（可用：${allNames.join(' | ')}）`,
      })
    }
    io.out(renderHelp({ name, version, summary, disclaimer, commands, command }))
    return EXIT.OK
  }

  const cmd = commands[command]
  if (!cmd) {
    const near = closestKey(command, allNames)
    return emitError(io, {
      name,
      command,
      kind: 'usage',
      message: `未知命令 "${command}"${near ? `，是否想写 "${near}"？` : ''}（可用：${allNames.join(' | ')}）`,
      details: [{ path: '(命令)', code: 'unknown_command', message: '运行 --help 查看全部命令与参数' }],
    })
  }

  const v = validate(args, cmd.params || {})
  if (!v.ok) {
    return emitError(io, {
      name,
      command,
      kind: 'usage',
      message: `参数校验未通过（${v.errors.length} 项），命令未执行`,
      details: v.errors,
    })
  }

  // 参数组合校验：单字段都合法、但组合起来没有意义的调用（如 profile 一个成分都没给）
  // 也必须归到「用法错误」，而不是让它跑出一个全是 0 的假结果。
  if (typeof cmd.check === 'function') {
    const msg = cmd.check(v.value)
    if (msg) {
      return emitError(io, {
        name,
        command,
        kind: 'usage',
        message: msg,
        details: [{ path: '(参数组合)', code: 'invalid_combination', message: '命令未执行' }],
      })
    }
  }

  let data
  try {
    data = await cmd.run(v.value, { name, version })
  } catch (e) {
    return emitError(io, {
      name,
      command,
      kind: 'internal',
      message: `命令执行时抛出异常：${(e && e.message) || e}`,
      details: [{
        path: '(运行时)',
        code: 'exception',
        message: String((e && e.stack) || e).split('\n').slice(0, 4).join(' | '),
      }],
    })
  }

  return emit(io, { ok: true, skill: name, command, basis, disclaimer, data }, pretty)
}
