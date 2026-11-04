#!/usr/bin/env node
/**
 * junheng-safety —— 宠物食品「有毒有害物质」安全闸的命令行门面。
 *
 * 唯一的实质工作是「参数接入 → 调用 src/lib/toxicology.js → 输出 JSON」。
 * 不含任何业务逻辑：种子表与判定规则全部来自源码模块，门面里**一条物质都不写**。
 *
 * ## 为什么它必须**先于**营养结论
 * 营养达标只说明「配比够」，不说明「能不能吃」。可可粉、木糖醇、百合属在配方表里
 * 都只是一行原料名，单看营养计算完全看不出问题。安全闸的作用就是在这条路径上先拦一道。
 *
 * ## 四态与「宁 unknown 不猜」
 *   banned / caution / ok / unknown —— **未收录一律 unknown，绝不 ok**。
 *   「查不到」不等于「安全」；把它兜底成 ok，安全闸会在最该拦的场景（新原料、别名
 *   没覆盖、拼写变体）静默放行 —— 那正是它存在的全部理由被抹掉的时刻。
 *
 * 调用形态（详见 `--help`）：
 *   node cli/safety.mjs check '{"name":"木糖醇","species":"dog"}'
 *   node cli/safety.mjs screen '{"species":"cat","items":[{"name":"洋葱"}]}'
 *   node cli/safety.mjs --help
 *
 * 退出码：0 成功 / 1 内部错误 / 2 用法或输入错误 / 3 前置条件缺失。
 *
 * ⚠ 输出只走 `process.exitCode`（不调 process.exit）：后者在管道下会截断尚未冲刷的
 *   stdout，导致调用方拿到半截 JSON —— 这是同类工具在 Windows 上的经典事故。
 */
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { importFromVendor, isEntrypoint } from './lib/locate.mjs'
import { runCli } from './lib/runner.mjs'
import { emitError, makeIo } from './lib/output.mjs'
import { speciesEnum } from './lib/paramSchema.mjs'

export const NAME = 'junheng-safety'
export const VERSION = '1.0.0'
export const SUMMARY = '宠物食品有毒有害物质安全闸：按犬 / 猫筛查配方中的禁用与慎用物质（未收录一律判「无法判定」，绝不当作安全）'
export const PROBE = ['toxicology.js', 'species.js']
export const DISCLAIMER = '本结果是**筛查提示**，不是毒理学结论，也不构成诊断或治疗建议：'
  + '命中 banned 表示该配方不应给出；命中 caution 须先满足列明条件；'
  + '返回 unknown 表示「本库未收录、无法判定」——**不等于安全**。'
  + '宠物已出现中毒症状时请立即停止喂食并联系执业兽医。'

const HERE = path.dirname(fileURLToPath(import.meta.url))

/** 就医指引（含判定的输出一律带上，避免被摘出来单独传播时丢失上下文） */
const MEDICAL_NOTICE = '宠物若已出现呕吐、流涎、抽搐、精神沉郁、呼吸困难等症状，请立即停止喂食并就近就医（可致电宠物中毒咨询热线）；本技能不提供诊断、用药或剂量。'

/** 配方条目字段（与其它技能保持一致，便于串联） */
const ITEM_FIELDS = {
  name: { type: 'string', required: true, desc: '原料 / 物质名（中英文均可，支持别名）' },
  weight: { type: 'number', min: 0, desc: '用量（克，可选；仅随行展示，不参与安全判定）' },
}

/** 由已加载的源码模块构造命令表。导出以便测试直接检视注册表，无需起进程。 */
export function buildCommands(api) {
  // 参数面枚举一律取自单一真源（species.js 与 paramSchema.mjs），
  // 门面内**不得**再写枚举字面量 —— 否则 `--help` 与校验会各自漂移。
  const SPECIES = speciesEnum(api)
  const LEVELS = api.TOXIC_LEVELS
  const CATEGORIES = api.TOXIC_CATEGORIES ?? []

  return {
    'list-substances': {
      summary: '列出已收录的有毒有害物质（可按物种 / 类别 / 严重度筛选，每条带来源与判定依据）',
      params: {
        species: { type: 'string', enum: SPECIES, desc: '只看对该物种适用的条目（不传则两个物种都列）' },
        category: { type: 'string', enum: CATEGORIES, desc: '按类别筛选（输出 categories 字段给出全部可选值）' },
        level: { type: 'string', enum: api.TOXIC_LEVEL_VALUES, desc: '按严重度筛选（种子表只收 banned / caution）' },
      },
      run: (a) => {
        const rows = api.TOXIC_SUBSTANCES
          .filter((e) => !a.species || (e.species ?? []).includes(a.species))
          .filter((e) => !a.category || e.category === a.category)
          .filter((e) => !a.level || e.level === a.level)
          .map((e) => ({
            id: e.id,
            substance: e.substance,
            latin: e.latin ?? null,
            level: e.level,
            species: e.species,
            category: e.category ?? null,
            conditions: e.conditions ?? null,
            basis: e.basis,
            aliases: e.aliases ?? [],
            sources: api.sourcesOf(e),
          }))
        return {
          count: rows.length,
          total: api.TOXIC_SUBSTANCES.length,
          levels: LEVELS,
          categories: CATEGORIES,
          substances: rows,
        }
      },
    },

    check: {
      summary: '判定单一物质 / 原料：banned（禁用）/ caution（慎用）/ ok（显式安全）/ unknown（未收录，无法判定）',
      params: {
        name: { type: 'string', required: true, desc: '物质或原料名（中英文均可，支持别名）' },
        species: { type: 'string', enum: SPECIES, default: api.DEFAULT_SPECIES, desc: '物种（同一条目对不同物种的结论可能不同）' },
      },
      run: (a) => ({
        query: a.name,
        ...api.classifySubstance(a.name, { species: a.species }),
        medicalNotice: MEDICAL_NOTICE,
      }),
    },

    screen: {
      summary: '批量筛查配方全部原料：命中禁用即阻断（blocked），未收录计入「待人工确认」（unjudged）',
      params: {
        species: { type: 'string', enum: SPECIES, default: api.DEFAULT_SPECIES, desc: '物种' },
        items: { type: 'array', required: true, minItems: 1, desc: '配方条目', fields: ITEM_FIELDS },
      },
      run: (a) => ({
        ...api.classifyRecipe(a.items, { species: a.species }),
        medicalNotice: MEDICAL_NOTICE,
      }),
    },

    'list-sources': {
      summary: '列出来源清单（机构 / 条目 / 链接 / 抓取日期）——每条收录都能回溯到它',
      params: {},
      run: () => ({
        count: Object.keys(api.SOURCES).length,
        sources: Object.entries(api.SOURCES).map(([key, v]) => ({ key, ...v })),
      }),
    },
  }
}

/** 门面主流程。返回退出码（不退出进程，便于测试在进程内断言）。 */
export async function main(argv = process.argv.slice(2), io) {
  const out = io || makeIo()
  let api
  try {
    const tox = await importFromVendor(HERE, PROBE, 'toxicology.js')
    // species.js 是全站物种缺省值的唯一真源；门面默认值必须取自它，不能写字面量（否则会与源码漂移）
    const sp = await importFromVendor(HERE, PROBE, 'species.js')
    api = { ...tox, DEFAULT_SPECIES: sp.DEFAULT_SPECIES, SPECIES_IDS: sp.SPECIES_IDS }
  } catch (e) {
    return emitError(out, { name: NAME, kind: 'precondition', message: `无法加载源码模块：${(e && e.message) || e}` })
  }
  return runCli({
    name: NAME,
    version: VERSION,
    summary: SUMMARY,
    disclaimer: DISCLAIMER,
    commands: buildCommands(api),
    argv,
    io: out,
  })
}

if (isEntrypoint(import.meta.url)) {
  process.exitCode = await main(process.argv.slice(2))
}
