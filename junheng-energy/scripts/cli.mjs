#!/usr/bin/env node
/**
 * junheng-energy —— 能量代谢计算的命令行门面（GE / DE / ME 多口径 + RER）。
 *
 * 门面里不含任何公式或系数：全部来自 `src/lib/energy.js`（每条系数带 NRC 出处）。
 *
 * 调用形态（详见 `--help`）：
 *   node cli/energy.mjs profile '{"asFed":{"crude_protein":30,"crude_fat":15,"moisture":10},"species":"cat"}'
 *   node cli/energy.mjs rer '{"species":"cat","kg":4}'
 *
 * 退出码：0 成功 / 1 内部错误 / 2 用法或输入错误 / 3 前置条件缺失。
 * ⚠ 用 process.exitCode 而非 process.exit：避免管道下截断 stdout。
 */
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { importFromVendor, isEntrypoint } from './lib/locate.mjs'
import { runCli } from './lib/runner.mjs'
import { emitError, makeIo } from './lib/output.mjs'
import { speciesEnum } from './lib/paramSchema.mjs'

export const NAME = 'junheng-energy'
export const VERSION = '1.0.0'
export const SUMMARY = '宠物食品能量计算：总能 GE、消化能 DE、代谢能 ME（改良/经典 Atwater 与 NRC 三步法）、供能比、静息能量需求 RER'
export const PROBE = ['energy.js']
export const DISCLAIMER = '全部为理论计算值，不是检测值（实测值与计算值通常存在差异）。'
  + '消化率方程是线性回归式：干物质基粗纤维 > 10% 时属于外推，结果里带 digestibilityExtrapolated=true。'
  + '水分缺失时 GE / DE / NRC 代谢能不出数（值为 null，不是 0）—— 请勿把 null 当作 0 参与后续计算。'

const HERE = path.dirname(fileURLToPath(import.meta.url))

/** 原样基础常规成分（%）。全部可选，但至少要给一项 —— 见 check 钩子。 */
const AS_FED_FIELDS = {
  crude_protein: { type: 'number', min: 0, max: 100, desc: '粗蛋白 %' },
  crude_fat: { type: 'number', min: 0, max: 100, desc: '粗脂肪 %' },
  crude_fiber: { type: 'number', min: 0, max: 100, desc: '粗纤维 %' },
  crude_ash: { type: 'number', min: 0, max: 100, desc: '粗灰分 %' },
  moisture: { type: 'number', min: 0, max: 100, desc: '水分 %（缺它则 GE/DE/NRC 代谢能不出数）' },
}

const r1 = (n) => Math.round(n * 10) / 10

/** 干物质含量：显式给了就用它，否则由水分反推；两者都无 → 0（干基项不出数） */
function dmOf(a) {
  if (a.dmPercent != null) return a.dmPercent
  const m = a.asFed && a.asFed.moisture
  return Number.isFinite(m) ? 100 - m : 0
}

const hasAnyNutrient = (asFed) => !!asFed && Object.keys(asFed).length > 0

/** 由已加载的源码模块构造命令表。导出以便测试检视注册表。 */
export function buildCommands(api) {
  // 参数面枚举取自单一真源（见 lib/paramSchema.mjs），门面内不再写枚举字面量。
  const SPECIES = speciesEnum(api)
  return {
    profile: {
      summary: '算一整套能量学结果（GE / DE / ME 多口径 / ME:GE / 供能比）',
      params: {
        asFed: { type: 'object', required: true, desc: '原样基础常规成分 %（至少给一项）', fields: AS_FED_FIELDS },
        species: { type: 'string', enum: SPECIES, default: api.DEFAULT_SPECIES, desc: '物种（决定消化率方程与尿能扣减系数）' },
        dmPercent: { type: 'number', min: 0, max: 100, desc: '干物质含量 %；缺省时取 100 − 水分' },
        moistureCoverage: { type: 'number', min: 0, max: 1, default: 1, desc: '水分覆盖率 0~1；<1 时结果标 reliable=false' },
      },
      check: (a) => (hasAnyNutrient(a.asFed) ? null : 'asFed 至少要给一项成分（crude_protein / crude_fat / moisture 等），否则各项系数都乘 0，得到的是假结果'),
      run: (a) => api.energyProfile(a.asFed, dmOf(a), a.species, { moistureCoverage: a.moistureCoverage }),
    },

    rer: {
      summary: '算静息能量需求 RER（kcal/日）',
      params: {
        species: { type: 'string', enum: SPECIES, default: api.DEFAULT_SPECIES, desc: '物种（指数：犬 0.75 / 猫 0.67）' },
        kg: { type: 'number', required: true, min: 0.1, max: 200, desc: '体重 kg' },
      },
      run: (a) => {
        const sp = a.species === 'cat' ? 'cat' : 'dog'
        return {
          species: sp,
          kg: a.kg,
          rer: r1(api.restingEnergy(sp, a.kg)),
          exponent: api.RER_EXPONENT[sp],
          formula: `RER = 70 × 体重^${api.RER_EXPONENT[sp]}`,
          cite: 'NRC 2006；全站唯一的 RER 定义处（energy.js）',
          note: '这是静息需求，不是每日喂食能量（MER 需再乘生命阶段/活动系数）。',
        }
      },
    },

    ge: {
      summary: '只算总能 GE（NRC 2006 表 VII-5 燃烧热系数）',
      params: {
        asFed: { type: 'object', required: true, desc: '原样基础常规成分 %（至少给一项）', fields: AS_FED_FIELDS },
        dmPercent: { type: 'number', min: 0, max: 100, desc: '干物质含量 %；缺省时取 100 − 水分' },
      },
      check: (a) => (hasAnyNutrient(a.asFed) ? null : 'asFed 至少要给一项成分，否则得到的是假结果'),
      run: (a) => api.grossEnergy(a.asFed, dmOf(a)),
    },

    digestibility: {
      summary: '算 NRC 2006 能量消化率（%，并标出是否已进入外推区）',
      params: {
        species: { type: 'string', enum: SPECIES, default: api.DEFAULT_SPECIES, desc: '物种（犬 −1.43 / 猫 −0.88 斜率）' },
        cfPercentDM: { type: 'number', required: true, min: 0, max: 100, desc: '粗纤维（干物质基）%' },
      },
      run: (a) => {
        const sp = a.species === 'cat' ? 'cat' : 'dog'
        return { species: sp, cfPercentDM: a.cfPercentDM, ...api.energyDigestibility(sp, a.cfPercentDM) }
      },
    },

    factors: {
      summary: '查全部能量系数与适用边界（含外推阈值、RER 指数、尿能双口径）',
      params: {},
      run: () => ({
        geFactorsKcalPerG: api.GE_FACTORS,
        geFactorsKjPerG: api.GE_FACTORS_KJ,
        modifiedAtwater: api.MODIFIED_ATWATER,
        atwater: api.ATWATER,
        /* 尿能扣减有**两套报道值**：主口径参与计算，备选口径仅并列展示。
           此处两个键都给出，调用方按 urinePrimary 判断哪个算进了 meNRC。 */
        urineFactors: api.URINE_FACTORS,
        urinePrimary: api.URINE_PRIMARY,
        urineAlternative: api.URINE_ALTERNATIVE,
        kcalToKj: api.KCAL_TO_KJ,
        fiberExtrapolationDm: api.FIBER_EXTRAPOLATION_DM,
        rerExponent: api.RER_EXPONENT,
      }),
    },

    cites: {
      summary: '查各口径的出处原文（写报告/说明书时直接引用）',
      params: {},
      run: () => ({ cites: api.ENERGY_CITES }),
    },
  }
}

/** 门面主流程。返回退出码（不退出进程，便于测试在进程内断言）。 */
export async function main(argv = process.argv.slice(2), io) {
  const out = io || makeIo()
  let api
  try {
    api = {
      ...(await importFromVendor(HERE, PROBE, 'energy.js')),
      // species.js 与 energy.js 同目录（项目布局 src/lib、技能布局 scripts/vendor）——
      // 参数面物种枚举的真源就是它，必须并入 api（见 lib/paramSchema.mjs）。
      ...(await importFromVendor(HERE, PROBE, 'species.js')),
    }
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
