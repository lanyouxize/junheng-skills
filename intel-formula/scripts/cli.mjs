#!/usr/bin/env node
/**
 * intel-formula —— 配方剂量核对的命令行门面（剂量归一 / 参照值定位 / 整表批量核对）。
 *
 * 门面里不含任何换算系数、阈值、档位或正则：全部来自
 * `src/lib/formula.js` + `src/lib/reference-values.js`。
 *
 * ## 枚举来源纪律（本文件最重要的一条约束）
 * 本门面的枚举分两类，处置**刻意不同**：
 *   ① **运行时从内核派生**：`refId`（REFERENCE_VALUES）、参照组（REFERENCE_GROUP_MAP）、
 *     `metric`（specsOf）。这三处的源头确实已 export —— 手抄一份会在内核新增 refId 时
 *     静默失配，而那正是内核自身「两份数字迟早对不上」的教训。
 *   ② **固定 9 键数组**：单位枚举。`UNIT_SUFFIX` 在内核是 `const` 且**未导出**，
 *     在「不改内核」（H1）前提下无法派生。故走「固定数组 + 守卫断言」：
 *     守卫对每个单位跑 `parseDose('1 '+u)` 与 `convertDose(1,u,'%')`，
 *     **内核改单位集合即守卫变红**。这把「运行时派生」降级为「带守卫的镜像」，
 *     保住「内核是唯一真源」的意图，且不违反 H1。
 *
 * 退出码：0 成功（含域内负结果）/ 1 内部错误 / 2 用法或输入错误 / 3 前置条件缺失。
 */
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { importFromVendor, isEntrypoint } from './lib/locate.mjs'
import { runCli } from './lib/runner.mjs'
import { emitError, makeIo } from './lib/output.mjs'

export const NAME = 'intel-formula'
export const VERSION = '1.0.0'
export const SUMMARY = '配方剂量核对：剂量单位归一（%/‰/ppm/mg-kg/g-kg 互算）、口径（DM/产品总重）显式化、参照区间定位、整张配方表批量核对'
/** 结果口径：参照值方向核对 —— 不给达标/不达标结论。必须是具名常量。 */
export const BASIS = 'reference-direction'
/** 两个文件必须同目录（formula.js 相对 import reference-values.js），故探测强制两个。 */
export const PROBE = ['formula.js', 'reference-values.js']

const HERE = path.dirname(fileURLToPath(import.meta.url))

/**
 * 单位枚举 —— 内核 `UNIT_SUFFIX` 的**带守卫镜像**（该常量未导出，见文件头 ②）。
 *
 * 注意：这是一份**手抄副本**，因此它的正确性由守卫断言保证（A15），不是靠这份数组本身。
 * 增删单位**必须先改内核**，再同步本数组 —— 只改本数组会让守卫变红（这是有意的）。
 */
export const UNIT_VALUES = ['%', '％', '‰', 'ppm', 'ppmw', 'mg/kg', 'ug/kg', 'g/kg', 'kg/t']

/** 口径枚举。与内核 `compareBasis` 认的两个值一致（productWeight / dryMatter）。 */
const BASIS_VALUES = ['productWeight', 'dryMatter']

/** `table` 的批量上限（V6：超限报错并给出上限，不做静默截断） */
const ROWS_MAX = 200

/** 元素级错误提示后缀（域内文案留在门面，不进通用校验器） */
const ROW_HINT = '每行可为 {name?, mine?, refId?, metric?, myBasis?}'

/** 无单位时的域内负结果说明。裸数不是 0，也不是猜出来的量。 */
const NO_UNIT_NOTE = '未解析出剂量：裸数或无单位/不认识的单位一律不猜（剂量必须带单位才算数）。'
  + '请写成 "0.3%" 或 "3000 ppm" 这类形态'

/** 由已加载的内核模块构造命令表。导出以便测试检视注册表。 */
export function buildCommands(api) {
  // —— ① 运行时派生的三处枚举 ——
  const REF_IDS = api.REFERENCE_VALUES.map((r) => r.id)
  const GROUP_IDS = Object.keys(api.REFERENCE_GROUP_MAP)
  /** 某条参照值下的可比子指标标签（`metric` 校验的唯一依据） */
  const metricLabelsOf = (refId) => {
    const ref = api.REFERENCE_VALUES.find((r) => r.id === refId)
    return ref ? api.specsOf(ref).map((s) => s.label) : []
  }

  /** `locate` 与 `check` 共用的参数表。`myBasis` 必填且**无默认**（V2）。 */
  const locateParams = () => ({
    mine: { type: 'string', required: true, desc: '实际用量（必须带单位，如 "0.3%" / "3000 ppm"）' },
    myBasis: { type: 'string', required: true, enum: BASIS_VALUES, desc: '口径：productWeight=占产品总重 / dryMatter=占干物质。口径不给就不能比较 —— 猜错会得出系统性偏差结论' },
    refId: { type: 'string', required: true, enum: REF_IDS, desc: '参照值 id（来自内核运行时派生）' },
    metric: { type: 'string', desc: '子指标标签原文（一条参照值有多个子指标时必须指名）' },
  })

  /**
   * 子指标校验（A13）。
   *
   * 内核 `checkAgainstReference` 也会拒绝压区间，但**在 CLI 前置拦截能给出更精确的候选清单** ——
   * 调用方要的是「该写成什么」，不是一句「参数不合法」。
   */
  const metricGuard = (refId, metric) => {
    const labels = metricLabelsOf(refId)
    if (!labels.length) return null
    const named = metric != null && String(metric).trim() !== ''
    if (!named && labels.length > 1) {
      return `参照值 ${refId} 有 ${labels.length} 个子指标，必须用 metric 指明比哪一个（候选：${labels.join(' | ')}）`
        + ' —— 把它们压成一个区间会造出「不存在的上下限」'
    }
    if (named && !labels.includes(String(metric))) {
      return `参照值 ${refId} 里没有名为 "${metric}" 的子指标（候选：${labels.join(' | ')}）`
    }
    return null
  }

  /** 单条核对的输出整形（`locate` / `check` 共用；失败形态原样透出，不改写、不吞掉） */
  const locateResult = (res) => {
    if (!res.ok) {
      return {
        ok: false,
        reason: res.reason,
        band: res.band,
        label: res.label,
        advice: res.advice || '',
        refId: res.refId || '',
        candidates: res.candidates || null,
      }
    }
    return {
      ok: true,
      reason: '',
      band: res.band,
      label: res.label,
      advice: res.advice,
      hasUpper: Boolean(res.hasUpper),
      hasLower: Boolean(res.hasLower),
      refId: res.refId,
      refSource: res.refSource,
      refTier: res.refTier,
      refUpdatedAt: res.refUpdatedAt,
      caveat: res.caveat || '',
      needsMoisture: Boolean(res.needsMoisture),
      mine: res.mine,
      ref: res.ref,
      metric: res.metric,
    }
  }

  return {
    dose: {
      summary: '解析一条带单位剂量文本，归一到质量分数（无单位不猜）',
      params: {
        text: { type: 'string', required: true, desc: '带单位的剂量文本，如 "0.3%" / "3000 ppm"' },
        basis: { type: 'string', enum: BASIS_VALUES, default: 'productWeight', desc: '口径（只影响 basisHint 文案，不影响比较结果）' },
      },
      run: (a) => {
        const parsed = api.parseDose(a.text, { basis: a.basis })
        return {
          parsed: parsed || null,
          found: parsed !== null,
          basisHint: a.basis === 'dryMatter' ? '占干物质' : '占产品总重',
          note: parsed ? '' : NO_UNIT_NOTE,
        }
      },
    },

    convert: {
      summary: '剂量单位互算（同一量纲内，如 500 ppm → 0.05%）',
      params: {
        value: { type: 'number', required: true, min: 0, desc: '数值' },
        from: { type: 'string', required: true, enum: UNIT_VALUES, desc: '源单位' },
        to: { type: 'string', required: true, enum: UNIT_VALUES, desc: '目标单位' },
      },
      run: (a) => {
        const result = api.convertDose(a.value, a.from, a.to)
        return {
          value: a.value,
          from: a.from,
          to: a.to,
          result: result == null ? null : result,
          note: result == null ? `无法在 "${a.from}" 与 "${a.to}" 之间换算 —— 请确认两者都是质量分数单位` : '',
        }
      },
    },

    locate: {
      summary: '把用量放进某参照值的某个子指标，给出区间档位（不给达标结论）',
      params: locateParams(),
      check: (a) => metricGuard(a.refId, a.metric),
      run: (a) => locateResult(api.checkAgainstReference({
        mine: a.mine, myBasis: a.myBasis, refId: a.refId, metric: a.metric,
      })),
    },

    check: {
      summary: '与参照值完整比对（与 locate 同参数，额外回显参照值本体的口径与来源）',
      params: locateParams(),
      check: (a) => metricGuard(a.refId, a.metric),
      run: (a) => locateResult(api.checkAgainstReference({
        mine: a.mine, myBasis: a.myBasis, refId: a.refId, metric: a.metric,
      })),
    },

    table: {
      // 「补充能力」标注必须出现在 summary 里 —— renderHelp 直接渲染它，
      // 于是 `--help` 与全局帮助都会带上（Spec §5.1① 透明性硬要求）。
      summary: '整张配方表逐行核对（补充能力：由 OD-04 裁决纳入，方案书原始清单未含）',
      params: {
        rows: {
          type: 'array',
          required: true,
          minItems: 1,
          maxItems: ROWS_MAX,
          itemOpen: true,
          itemHint: ROW_HINT,
          desc: `补充能力：配方表行数组，最多 ${ROWS_MAX} 行。mine 与 refId 刻意可选 —— 空行/未选参照值是「还没做」，不是错误`,
        },
      },
      run: (a) => {
        // 注意：整表**不得因单行出错而整体失败**：内核逐行独立，把 empty/unpicked/refused
        //   三态原样透出。CLI 不重复扫描 rows，summary 直接用内核那一次遍历的结果。
        const res = api.checkFormulaTable(a.rows)
        const s = res.summary
        return {
          rows: res.rows,
          summary: {
            total: s.total,
            ok: s.ok,
            empty: s.empty,
            unpicked: s.unpicked,
            refused: s.refused,
            // pending 只含「还没做」（empty + unpicked）。把 refused 算进待办会让
            // 人去「修」一个其实已给出拒绝理由的行；把它排除在 pending 外才不会
            // 让已核过的行替没做的行背锅。
            pending: s.pending,
            done: s.done,
          },
          statusHelp: api.TABLE_STATUS_HELP,
        }
      },
    },

    refs: {
      summary: '列出可核对的子指标 + 被跳过项的原因',
      params: {
        group: { type: 'string', enum: GROUP_IDS, desc: '按参照组过滤（来自内核运行时派生）' },
        myBasis: { type: 'string', enum: BASIS_VALUES, default: 'productWeight', desc: '口径（决定哪些参照值可比）' },
      },
      run: (a) => {
        const all = api.comparableReferences(a.myBasis)
        const ok = a.group ? all.ok.filter((x) => x.group === a.group) : all.ok
        const skipped = a.group ? all.skipped.filter((x) => x.group === a.group) : all.skipped
        return { ok, skipped, groups: all.groups, disclaimer: api.FORMULA_DISCLAIMER }
      },
    },
  }
}

/** 门面主流程。返回退出码（不退出进程，便于测试在进程内断言）。 */
export async function main(argv = process.argv.slice(2), io) {
  const out = io || makeIo()
  let api
  try {
    api = await importFromVendor(HERE, PROBE, 'formula.js')
  } catch (e) {
    return emitError(out, { name: NAME, kind: 'precondition', message: `无法加载源码模块：${(e && e.message) || e}` })
  }
  // 参照值表与合规口径来自第二个模块（PROBE 已保证两者同目录）
  let refsApi
  try {
    refsApi = await importFromVendor(HERE, PROBE, 'reference-values.js')
  } catch (e) {
    return emitError(out, { name: NAME, kind: 'precondition', message: `无法加载参照值模块：${(e && e.message) || e}` })
  }
  const merged = { ...refsApi, ...api }
  // 诚实性红线**逐字复用内核原文**，不另立口径（Spec §5.1③ 硬要求）
  const disclaimer = `${api.FORMULA_NOTE}${api.FORMULA_DISCLAIMER}`
    + '本模块只做方向核对，不给达标/不达标结论；参照值会随标准修订过期，正式引用前请回来源原文核对版本。'
  const commands = buildCommands(merged)
  return runCli({
    name: NAME,
    version: VERSION,
    summary: SUMMARY,
    basis: BASIS,
    disclaimer,
    commands,
    argv,
    io: out,
  })
}

if (isEntrypoint(import.meta.url)) {
  process.exitCode = await main(process.argv.slice(2))
}
