#!/usr/bin/env node
/**
 * junheng-standards —— 法规限值查询的命令行门面。
 *
 * 唯一的实质工作是「参数接入 → 调用 src/lib/standards.js → 输出 JSON」。
 * 不含任何业务逻辑：限值全部来自源码模块，门面里**一个数字都不写**。
 *
 * 调用形态（详见 `--help`）：
 *   node cli/standards.mjs resolve '{"species":"cat","stage":"adult"}'
 *   node cli/standards.mjs classify-moisture '{"moisture":32.04}'
 *   node cli/standards.mjs --help
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
import { speciesEnum, marketEnum, STAGES, MOISTURE_CLASSES } from './lib/paramSchema.mjs'

export const NAME = 'junheng-standards'
export const VERSION = '1.0.0'
export const SUMMARY = '宠物营养法规限值查询：按目标市场 / 物种 / 生命阶段 / 水分形态，解析应同时满足的合并限值（每项带条款出处）'
export const PROBE = ['standards.js', 'species.js']
export const DISCLAIMER = '限值是法规条文的理论引用值，不是检测值；CN-GB 条款已逐条核对，'
  + 'FEDIAF 2025 数值已按官方 PDF（Table III-3/III-4, per 100 g DM）逐项抽取并核验（证据见 docs/evidence/fediaf-2025-verify-2026-11-02.md），'
  + 'NRC 2006 六档数值取自官方中文版并已核验；'
  + 'AAFCO 数值沿用系统原有实现、尚未与官方现行出版物核对（verified=false）—— 引用前请自行核对现行标准原文。'

const HERE = path.dirname(fileURLToPath(import.meta.url))

/** 由已加载的源码模块构造命令表。导出以便测试直接检视注册表，无需起进程。 */
export function buildCommands(api) {
  // 参数面枚举一律取自单一真源（species.js / standards.js 与 paramSchema.mjs），
  // 门面内**不得**再写枚举字面量 —— 否则 `--help` 与校验会各自漂移。
  const SPECIES = speciesEnum(api)
  const marketIds = marketEnum(api)
  const nutrientKeys = Object.keys(api.NUTRIENT_META)

  /** 取单条条款原文 + 出处；未登记时给出可用清单而不是抛错 */
  const clauseOf = ({ setId, species, stage, key }) => {
    const set = api.STANDARD_SETS[setId]
    if (!set) return { found: false, reason: `未登记的标准体系 "${setId}"`, available: api.STANDARD_SET_IDS }
    const table = (set.stages && set.stages[species] && set.stages[species][stage]) || {}
    const clause = table[key]
    if (!clause) {
      return {
        found: false,
        reason: `${setId} 在 ${species}/${stage} 下没有 "${key}" 条款`,
        available: Object.keys(table),
      }
    }
    const meta = api.NUTRIENT_META[key] || {}
    return {
      found: true,
      setId,
      species,
      stage,
      key,
      label: meta.label || key,
      unit: meta.unit || '',
      kind: meta.kind || null,
      dataField: meta.dataField === undefined ? null : meta.dataField,
      verified: set.verified !== false,
      min: clause.min === undefined ? null : clause.min,
      max: clause.max === undefined ? null : clause.max,
      wetMin: clause.wetMin === undefined ? null : clause.wetMin,
      cite: clause.cite || null,
      text: api.clauseText(clause, { unit: meta.unit || '', key }),
    }
  }

  return {
    'list-markets': {
      summary: '列出目标市场模式（决定要同时满足哪些标准体系）',
      params: {},
      run: () => ({
        default: api.DEFAULT_MARKET,
        markets: api.MARKET_MODES.map((m) => ({ id: m.id, label: m.label, desc: m.desc, sets: m.sets })),
        note: '不同市场模式会改变判定体系，进而改变限值（取最严）。默认 cn。',
      }),
    },

    'list-sets': {
      summary: '列出已登记的标准体系及其可信度状态',
      params: {},
      run: () => ({
        sets: api.STANDARD_SET_IDS.map((id) => {
          const s = api.STANDARD_SETS[id]
          return {
            id,
            label: s.label,
            fullLabel: s.fullLabel,
            verified: s.verified !== false,
            valuesPending: !!s.valuesPending,
            species: Object.keys(s.stages || {}),
            note: s.verifyNote || s.pendingNote || '',
          }
        }),
      }),
    },

    resolve: {
      summary: '解析合并后的营养限值表（多体系取最严，逐项带出处）',
      params: {
        marketId: { type: 'string', enum: marketIds, default: api.DEFAULT_MARKET, desc: '目标市场模式' },
        species: { type: 'string', enum: SPECIES, default: api.DEFAULT_SPECIES, desc: '物种' },
        stage: { type: 'string', enum: STAGES, default: 'adult', desc: '生命阶段档（生长/繁殖/泌乳合并为 growth）' },
        moistureClass: { type: 'string', enum: MOISTURE_CLASSES, default: 'unknown', desc: '水分形态（wet 会启用湿粮档更严下限，如牛磺酸）' },
      },
      run: (a) => api.resolveStandard(a),
    },

    clause: {
      summary: '查单一营养项的条款原文与出处（不参与合并，原样返回单体系口径）',
      params: {
        setId: { type: 'string', required: true, enum: api.STANDARD_SET_IDS, desc: '标准体系 id' },
        species: { type: 'string', enum: SPECIES, default: api.DEFAULT_SPECIES, desc: '物种' },
        stage: { type: 'string', enum: STAGES, default: 'adult', desc: '生命阶段档' },
        key: { type: 'string', required: true, enum: nutrientKeys, desc: '营养项 key' },
      },
      run: (a) => clauseOf(a),
    },

    'classify-moisture': {
      summary: '按水分百分比判定形态分级（干性 / 半湿性 / 湿性）',
      params: {
        moisture: { type: 'number', required: true, min: 0, max: 100, desc: '水分百分比（0~100）' },
      },
      run: (a) => ({ moisture: a.moisture, ...api.classifyMoisture(a.moisture) }),
    },
  }
}

/** 门面主流程。返回退出码（不退出进程，便于测试在进程内断言）。 */
export async function main(argv = process.argv.slice(2), io) {
  const out = io || makeIo()
  let api
  try {
    api = await importFromVendor(HERE, PROBE, 'standards.js')
    // species.js 是全站物种缺省值的唯一真源；门面默认值必须取自它，不能写字面量（否则会与源码漂移）
    const sp = await importFromVendor(HERE, 'species.js', 'species.js')
    api = { ...api, DEFAULT_SPECIES: sp.DEFAULT_SPECIES, SPECIES_IDS: sp.SPECIES_IDS }
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
