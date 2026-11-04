#!/usr/bin/env node
/**
 * junheng-labeling —— 配方 → 合规标签底稿的命令行门面。
 *
 * 门面里不含任何法规判定逻辑：全部来自 `src/lib/labeling.js`
 * （它又从 `standards.js` 取限值、从 `evaluateRecipe` 取合规结论）。
 *
 * ⚠ 产物是**标签底稿**，不是最终合规结论 —— 提交前需人工与法规原文逐条核对。
 *
 * 调用形态（详见 `--help`）：
 *   node cli/labeling.mjs draft '{"recipe":{...},"req":{...},"meta":{"productName":"..."}}'
 *   node cli/labeling.mjs render '{"draft":{...}}'
 *
 * 退出码：0 成功 / 1 内部错误 / 2 用法或输入错误 / 3 前置条件缺失。
 */
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { importFromVendor, isEntrypoint } from './lib/locate.mjs'
import { runCli } from './lib/runner.mjs'
import { emitError, makeIo } from './lib/output.mjs'

export const NAME = 'junheng-labeling'
export const VERSION = '1.0.0'
export const SUMMARY = '把配方与个体需求生成合规标签底稿：营养保证值表、配料表、逐项合规结论与风险提示'
export const PROBE = ['labeling.js']
export const DISCLAIMER = '产物是**标签底稿**，不是最终合规结论 —— 提交前必须人工与现行法规原文逐条核对。'
  + '限值为法规条文的理论引用值（不是检测值）；AAFCO 数值尚未与官方现行出版物核对（verified=false）。'
  + '原料库缺氨基酸等字段的项目会进入 nodata 段，既不算达标也不算未达标。'
  + '配方未计算成功或缺 req 时不会产出稿件，会明确报原因。'

const HERE = path.dirname(fileURLToPath(import.meta.url))

/**
 * draft / guaranteed / ingredients-list 共用的**上游产物形状校验**（L2 域内前置）。
 *
 * 为什么必须在门面层挡：内核 `buildLabelDraft` 只对 `recipe.ok !== true` 做短路
 * （返回 `{ok:false, reason}`）。一旦 `recipe.ok === true`，它就假定这是
 * `junheng-nutrition` 的 `recipe` 命令返回的**完整 data**，直接读
 * `recipe.dmPercent` / `recipe.asFed.crude_protein` / `recipe.energy.meModified` /
 * `recipe.lines`。传一个「ok:true 但缺这些字段」的瘦对象会在内核深处
 * 抛 `TypeError` → exit 1（internal），既不是可定位的参数错误，也违背
 * 「域内负结果不是错误」的约定。所以形状校验只能在这里做。
 *
 * 注意：`recipe.ok !== true` 时返回 null —— 那是**域内负结果**（配方没算成功），
 * 应交给内核短路并给出 reason（既有行为，见实测与测试 ⑥）。
 */
const RECIPE_REQUIRED = [
  ['dmPercent', (r) => typeof r.dmPercent === 'number'],
  ['asFed.crude_protein', (r) => !!r.asFed && typeof r.asFed.crude_protein === 'number'],
  ['energy.meModified', (r) => !!r.energy && typeof r.energy.meModified === 'number'],
  ['lines[]', (r) => Array.isArray(r.lines)],
]

function checkUpstream(a, cmd) {
  if (!a.recipe || !a.req) {
    return `${cmd} 需要 recipe 与 req 两个对象（先跑 junheng-nutrition 的 recipe / requirements 命令取结果）`
  }
  if (a.recipe.ok !== true) return null // 域内负结果：交给内核短路，附 reason
  const missing = RECIPE_REQUIRED.filter(([, ok]) => !ok(a.recipe)).map(([name]) => name)
  if (missing.length) {
    return `${cmd} 的 recipe 声明 ok:true，但不是 junheng-nutrition「recipe」命令返回的完整 data —— 缺少：${missing.join('、')}。请把 recipe 命令返回的 data 原样传入（不要手捏瘦对象）。`
  }
  return null
}

/**
 * render / coverage 共用的**入参形状校验**（与 `checkUpstream` 对称的那条路径）。
 *
 * 为什么同样必须挡在门面层：内核 `renderLabelText` / `labelCoverage` 都只对
 * `!draft?.ok` 做短路（降级成「标签稿生成失败：…」/ 全 0 覆盖率）。一旦
 * `draft.ok === true`，它们就假定这是 `draft` 命令返回的**完整 data**，直接读
 * `draft.product.productName`（renderLabelText）、`draft.guaranteed.rows`
 * （两者）、`draft.ingredients.items` / `draft.basis.*` / `draft.energy` /
 * `draft.risks`（renderLabelText）。传「ok:true 但缺这些字段」的瘦对象会在内核
 * 深处抛 `TypeError` → exit 1（internal）—— **与 checkUpstream 注释描述的是同一类
 * 缺陷，只是发生在另一条输入路径上**。上一版只在 recipe/req 那条路径设了守卫，
 * draft 这条漏了（实测 `render '{"draft":{"ok":true}}'` 与
 * `coverage '{"draft":{"ok":true}}'` 均 exit 1）。
 *
 * 注意：`draft.ok !== true` 时返回 null —— 那是**域内负结果**（底稿没生成成功），
 * 应交给内核优雅降级并给出原因，而不是报参数错误。
 */
const DRAFT_REQUIRED = [
  ['formatVersion', (d) => typeof d.formatVersion === 'number'],
  ['product', (d) => !!d.product],
  ['basis', (d) => !!d.basis],
  ['ingredients.items[]', (d) => !!d.ingredients && Array.isArray(d.ingredients.items)],
  ['guaranteed.rows[]', (d) => !!d.guaranteed && Array.isArray(d.guaranteed.rows)],
  ['energy', (d) => !!d.energy],
  ['risks[]', (d) => Array.isArray(d.risks)],
]

function checkDraftShape(a, cmd) {
  if (!a.draft) return `${cmd} 需要 draft 对象（先跑 draft 命令，把它的 data 传进来）`
  if (a.draft.ok !== true) return null // 域内负结果：交给内核优雅降级
  const missing = DRAFT_REQUIRED.filter(([, ok]) => !ok(a.draft)).map(([name]) => name)
  if (missing.length) {
    return `${cmd} 的 draft 声明 ok:true，但不是 junheng-labeling「draft」命令返回的完整 data —— 缺少：${missing.join('、')}。请把 draft 命令返回的 data 原样传入（不要手捏瘦对象）。`
  }
  return null
}

/** 由已加载的源码模块构造命令表。导出以便测试检视注册表。 */
export function buildCommands(api) {
  return {
    draft: {
      summary: '生成完整标签底稿（保证值 + 配料表 + 合规 + 风险）',
      params: {
        recipe: { type: 'object', required: true, open: true, desc: 'computeRecipe 的返回对象（junheng-nutrition 的 recipe 命令）' },
        req: { type: 'object', required: true, open: true, desc: 'computeRequirements 的返回对象' },
        meta: {
          type: 'object',
          desc: '产品元信息',
          fields: {
            productName: { type: 'string', desc: '产品名称' },
            brand: { type: 'string', desc: '品牌' },
            netWeight: { type: 'string', desc: '净含量' },
            batchNo: { type: 'string', desc: '批号' },
            manufacturer: { type: 'string', desc: '生产商' },
            date: { type: 'string', desc: '日期' },
          },
        },
      },
      check: (a) => checkUpstream(a, 'draft'),
      run: (a) => api.buildLabelDraft({ recipe: a.recipe, req: a.req, meta: a.meta || {} }),
    },

    guaranteed: {
      summary: '只取营养保证值表（已按法规要求的项目过滤与排序）',
      params: {
        recipe: { type: 'object', required: true, open: true, desc: 'computeRecipe 的返回对象' },
        req: { type: 'object', required: true, open: true, desc: 'computeRequirements 的返回对象' },
      },
      check: (a) => checkUpstream(a, 'guaranteed'),
      run: (a) => {
        const d = api.buildLabelDraft({ recipe: a.recipe, req: a.req })
        if (!d.ok) return { ok: false, reason: d.reason }
        return { ok: true, rows: d.guaranteed, formatVersion: d.formatVersion }
      },
    },

    'ingredients-list': {
      summary: '只取配料表（按占比降序，等价重量保持录入顺序）',
      params: {
        recipe: { type: 'object', required: true, open: true, desc: 'computeRecipe 的返回对象' },
        req: { type: 'object', required: true, open: true, desc: 'computeRequirements 的返回对象' },
      },
      check: (a) => checkUpstream(a, 'ingredients-list'),
      run: (a) => {
        const d = api.buildLabelDraft({ recipe: a.recipe, req: a.req })
        if (!d.ok) return { ok: false, reason: d.reason }
        return { ok: true, ingredients: d.ingredients }
      },
    },

    render: {
      summary: '把标签稿渲染成可直接粘贴的纯文本',
      params: {
        draft: { type: 'object', required: true, open: true, desc: 'draft 命令的返回 data' },
      },
      check: (a) => checkDraftShape(a, 'render'),
      run: (a) => ({ text: api.renderLabelText(a.draft) }),
    },

    coverage: {
      summary: '查标签稿的覆盖率（哪些项有据可依、哪些缺数据）',
      params: {
        draft: { type: 'object', required: true, open: true, desc: 'draft 命令的返回 data' },
      },
      check: (a) => checkDraftShape(a, 'coverage'),
      run: (a) => api.labelCoverage(a.draft),
    },

    disclaimers: {
      summary: '查必须随稿件一起给出的声明清单',
      params: {},
      run: () => ({ disclaimers: api.LABEL_DISCLAIMERS, formatVersion: api.LABEL_FORMAT_VERSION }),
    },
  }
}

/** 门面主流程。返回退出码（不退出进程，便于测试在进程内断言）。 */
export async function main(argv = process.argv.slice(2), io) {
  const out = io || makeIo()
  let api
  try {
    api = await importFromVendor(HERE, PROBE, 'labeling.js')
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
