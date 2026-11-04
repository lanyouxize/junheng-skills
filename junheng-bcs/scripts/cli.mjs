#!/usr/bin/env node
/**
 * junheng-bcs —— 体况评分（BCS 9 分制）查询与参考图生成的门面。
 *
 * 数据与几何全部来自 `src/lib/bcsChart.js`（逐分判定表）与 `src/lib/bcsFigure.js`（矢量图）。
 * 门面不写一行判据文字、不画一条路径。
 *
 * 调用形态（详见 `--help`）：
 *   node cli/bcs.mjs row '{"species":"cat","score":7}'
 *   node cli/bcs.mjs figure-svg '{"typeId":"cat","levelKey":"over"}'
 *
 * 退出码：0 成功 / 1 内部错误 / 2 用法或输入错误 / 3 前置条件缺失。
 * ⚠ 用 process.exitCode 而非 process.exit：避免管道下截断 stdout。
 */
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { importFromVendor, isEntrypoint } from './lib/locate.mjs'
import { runCli } from './lib/runner.mjs'
import { emitError, makeIo } from './lib/output.mjs'

export const NAME = 'junheng-bcs'
export const VERSION = '1.0.0'
export const SUMMARY = '宠物体况评分（BCS 9 分制）：逐分判定表（侧视/俯视/触摸）、理想区与临床肥胖筛查区判定、物种差异提示、自绘矢量参考图'
export const PROBE = ['bcsChart.js', 'bcsFigure.js', 'species.js']
export const DISCLAIMER = 'BCS 是体况筛查工具，不是兽医诊断；7~9 分属临床肥胖筛查区，确诊需由兽医结合肌肉状况、'
  + '体重趋势、饮食史、活动能力与体检结果。体脂率为近似估算值，个体误差约正负 5 个百分点；'
  + '体脂超过约 45% 时 BCS 区分度明显下降。任何不在理想区的评分都建议请兽医团队评估一次，'
  + '请勿只凭本表大幅增减喂食量或运动量。'

const HERE = path.dirname(fileURLToPath(import.meta.url))

/** 由已加载的源码模块构造命令表。导出以便测试检视注册表。 */
export function buildCommands(api) {
  const speciesList = Object.keys(api.BCS_CHART)
  const typeIds = api.BCS_FIGURE_TYPES.map((t) => t.id)
  const levelKeys = api.BCS_FIGURE_LEVELS.map((l) => l.key)
  const speciesSpec = { type: 'string', enum: speciesList, default: api.DEFAULT_SPECIES, desc: '物种（犬的理想是 4~5 分，猫只有 5 分）' }

  /** 一次给全「这一分意味着什么」：判定行 + 是否理想 + 是否在筛查区 */
  const assessOf = (species, score) => {
    const sp = api.normBcsSpecies(species)
    return {
      species: sp,
      score,
      idealScores: api.idealScoresFor(sp),
      isIdeal: api.isIdealFor(sp, score),
      inObesityScreeningZone: api.inObesityScreeningZone(score),
      screeningZone: api.BCS_OBESITY_SCREENING_ZONE,
      row: api.bcsChartRow(sp, score),
      speciesNote: api.BCS_SPECIES_NOTE[sp],
    }
  }

  return {
    chart: {
      summary: '查某物种的完整逐分判定表（9 行：侧视 / 俯视 / 触摸三列）',
      params: { species: speciesSpec },
      run: (a) => ({
        species: api.normBcsSpecies(a.species),
        columns: api.BCS_CHART_COLUMNS,
        idealScores: api.idealScoresFor(a.species),
        screeningZone: api.BCS_OBESITY_SCREENING_ZONE,
        rows: api.bcsChartFor(a.species),
        speciesNote: api.BCS_SPECIES_NOTE[api.normBcsSpecies(a.species)],
      }),
    },

    row: {
      summary: '查单一分数的判定行（含理想区 / 筛查区标记）',
      params: {
        species: speciesSpec,
        score: { type: 'number', required: true, integer: true, min: 1, max: 9, desc: 'BCS 分数 1~9' },
      },
      run: (a) => assessOf(a.species, a.score),
    },

    assess: {
      summary: '体况评估总装：判定行 + 理想/筛查标记 + 物种差异提示 + 误差与就医声明',
      params: {
        species: speciesSpec,
        score: { type: 'number', required: true, integer: true, min: 1, max: 9, desc: 'BCS 分数 1~9' },
      },
      run: (a) => ({
        ...assessOf(a.species, a.score),
        caveats: api.BCS_CHART_CAVEATS,
        source: api.bcsChartSourceText(),
      }),
    },

    figures: {
      summary: '列出参考图可用的体型分类与档位（给 figure-svg 取值用）',
      params: {},
      run: () => ({
        types: api.BCS_FIGURE_TYPES,
        levels: api.BCS_FIGURE_LEVELS,
        view: api.FIGURE_VIEW,
        layers: api.FIGURE_LAYERS,
        note: '三档的卡片标注写的是覆盖区间（如 6–9），不是单点分数；只标单点会误导。',
      }),
    },

    'figure-svg': {
      summary: '生成一张自包含的「侧视 + 俯视」参考图 SVG 字符串（原创矢量，非版权图）',
      params: {
        typeId: { type: 'string', required: true, enum: typeIds, desc: '体型分类 id' },
        levelKey: { type: 'string', required: true, enum: levelKeys, desc: '档位 key' },
        aria: { type: 'string', desc: '无障碍描述（不填时用默认文案）' },
      },
      run: (a) => ({ svg: api.figureSvg(a.typeId, a.levelKey, a.aria ? { aria: a.aria } : {}) }),
    },

    caveats: {
      summary: '查全部可靠性边界、物种差异与出处（写报告时直接引用）',
      params: {},
      run: () => ({
        caveats: api.BCS_CHART_CAVEATS,
        speciesNote: api.BCS_SPECIES_NOTE,
        screeningZone: api.BCS_OBESITY_SCREENING_ZONE,
        source: api.bcsChartSourceText(),
      }),
    },
  }
}

/** 门面主流程。返回退出码（不退出进程，便于测试在进程内断言）。 */
export async function main(argv = process.argv.slice(2), io) {
  const out = io || makeIo()
  let api
  try {
    api = await importFromVendor(HERE, PROBE, 'bcsChart.js')
    const figure = await importFromVendor(HERE, PROBE, 'bcsFigure.js')
    // 两个模块不互相 import，但本门面要同时用它们的导出；合成一个命名空间传入命令表。
    api = { ...api, ...figure }
    // species.js 是全站物种缺省值的唯一真源；门面默认值必须取自它，不能写字面量（否则会与源码漂移）
    const sp = await importFromVendor(HERE, 'species.js', 'species.js')
    api = { ...api, DEFAULT_SPECIES: sp.DEFAULT_SPECIES }
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
