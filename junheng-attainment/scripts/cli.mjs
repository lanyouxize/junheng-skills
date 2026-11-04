#!/usr/bin/env node
/**
 * junheng-attainment —— **目标达成度评估**门面（决策视图）。
 *
 * ## 为什么需要它
 * 界面有「⑤ 达标评估」，命令行却拿不到 —— 想知道「这个配方达不达标、差在哪」
 * 必须开浏览器。配置人员与 AI 都需要一个**一次调用**就能拿到逐项结论的入口。
 *
 * ## 与 junheng-nutrition evaluate 的分工（★ 容易混，务必分清）
 *   · `junheng-nutrition evaluate`：要**两个上游大对象**（`recipe` + `req`），
 *     先跑 `recipe`、再跑 `requirements`、再手工把两个 JSON 搬过来 —— 它只做**原始对照**，
 *     且明说「不替用户下是否达标的结论」。
 *   · 本门面 `assess`：输入是**原料清单 + 目标画像**，上游两个对象由本命令自己构造。
 *     是前者的一步到位版，也是「⑤ 达标评估」的命令行等价物。
 *
 * ## 本门面做什么
 * **只做接线，不含任何公式**：判定完全复用 `src/lib/nutrition.js` 的 `evaluateRecipe`
 * —— 与界面「⑤ 达标评估」、配方体检（`audit`）、标签稿的合规段**同一口径**。
 * 本文件不新增一条业务规则，也不写任何一个限值数字。
 *
 * ## 四态口径（★ 不要简化成「达标 / 未达标」两态）
 *   ok      达标
 *   fail    未达标
 *   low     数值达标，但该指标覆盖的原料有数据缺口 → 结论仅供参考
 *   nodata  **无法判定**（原料库没这个字段，或本配方算不出）—— **不等于未达标**
 * 把 nodata 读成「未达标」是本项目最危险的误读方式：原料库没有氨基酸字段，
 * 赖氨酸 / 牛磺酸在绝大多数配方里都会是 nodata。
 *
 * 调用形态：
 *   node cli/attainment.mjs assess  '{"items":[...],"profile":{"species":"cat","weightKg":4}}'
 *   node cli/attainment.mjs targets '{}'      # 先看有哪些目标口径可选
 *
 * 退出码：0 成功 / 1 内部错误 / 2 用法或输入错误 / 3 前置条件缺失。
 * ⚠ 用 process.exitCode 而非 process.exit：避免管道下截断尚未冲刷的 stdout。
 */
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { importFromVendor, isEntrypoint } from './lib/locate.mjs'
import { runCli } from './lib/runner.mjs'
import { emitError, makeIo } from './lib/output.mjs'
import { speciesEnum, marketEnum, STAGES } from './lib/paramSchema.mjs'

export const NAME = 'junheng-attainment'
export const VERSION = '1.0.0'
export const SUMMARY = '目标达成度评估：给定配方与目标画像（物种/月龄/体况/目标市场），逐项对照法规限值，输出达标度、缺口清单与无法判定项'
/**
 * 探测文件必须**同目录**（pickVendorDir 的硬要求）。
 * 三者都在 junheng-core 的 vendor 闭包里：nutrition.js 自身 import standards.js，
 * 而 standards 又依赖 species.js —— 列全可让「core 镜像漏装」在启动时就报出来，
 * 而不是等到某个命令才炸（与 junheng-pipeline 的 PROBE 策略一致）。
 */
export const PROBE = ['nutrition.js', 'standards.js', 'species.js']
export const DISCLAIMER = '本命令是**评估层**，不含独立公式：判定与界面「达标评估」、配方体检、'
  + '标签稿合规段**同一口径**（全部来自 nutrition.js 的 evaluateRecipe）。'
  + '数值为按原料库加权的理论值，不是检测值。'
  + '四态：ok 达标 ／ fail 未达标 ／ low 达标但数据不足 ／ nodata **无法判定** —— '
  + '**nodata 不等于未达标**，请勿读成红叉。`gap` 是展示用的算术差，判定口径一律以 `status` 为准。'

const HERE = path.dirname(fileURLToPath(import.meta.url))

const r2 = (n) => Math.round(n * 100) / 100

/** 把 {name|code, weight} 解析成 computeRecipe 需要的 {ingredient, weight} */
function resolveItems(api, items) {
  const resolved = []
  const unknown = []
  for (const it of items) {
    let ing = null
    if (it.code) ing = api.findIngredientByCode(it.code)
    if (!ing && it.name) ing = api.findIngredient(it.name)
    if (!ing) {
      unknown.push(it.code ? `code=${it.code}` : it.name)
      continue
    }
    resolved.push({ ingredient: ing, weight: it.weight })
  }
  return { resolved, unknown }
}

/**
 * 缺口量：未达标项距**最近限值**的超标量。
 * ⚠ 这是纯算术差（减一下），**不是业务规则**；判定口径以 evaluateRecipe 的 `status` 为准。
 * 达标项返回 null —— 刻意**不**给「负缺口」，避免调用方把「还有余量」误读成可支配配额。
 */
function gapOf(row) {
  if (row.value == null) return null
  const { value, min, max } = row
  if (min != null && value < min) return { direction: 'below_min', amount: r2(min - value) }
  if (max != null && value > max) return { direction: 'above_max', amount: r2(value - max) }
  return null
}

/** 单行精简：凡调用方要据以判断的字段都保留（含 target 原文，合规引用需要） */
function briefRow(row) {
  return {
    nutrient: row.nutrient,
    label: row.label,
    value: row.value,
    unit: row.unit,
    min: row.min,
    max: row.max,
    target: row.target,
    coverage: row.coverage,
  }
}

/** 由已加载的源码模块构造命令表。导出以便测试检视注册表。 */
export function buildCommands(api) {
  // 参数面枚举取自单一真源（见 lib/paramSchema.mjs），门面内不再写枚举字面量。
  const SPECIES = speciesEnum(api)
  const marketIds = marketEnum(api)

  const ITEM_FIELDS = {
    name: { type: 'string', desc: '原料名称（与 code 二选一，如「鸡大胸」）' },
    code: { type: 'string', desc: '物料编号（与 name 二选一，给了它优先）' },
    weight: { type: 'number', required: true, min: 0, max: 100000, desc: '用量（克）' },
  }

  /** 目标画像：决定「按哪套标准、哪个生命阶段档」判定 */
  const PROFILE_FIELDS = {
    species: { type: 'string', enum: SPECIES, desc: `物种（缺省 ${api.DEFAULT_SPECIES}，取自 species.js）` },
    market: { type: 'string', enum: marketIds, desc: `目标市场模式（缺省 ${api.DEFAULT_MARKET}）—— 决定要同时满足哪些体系（取最严）` },
    status: { type: 'string', desc: '生理状态（缺省由年龄推断：月龄<12 → 生长档，限值更严）' },
    ageMonths: { type: 'number', min: 0, max: 400, desc: '月龄' },
    ageText: { type: 'string', desc: '年龄文本（月龄未给时用于推断，如「6个月」）' },
    weightKg: { type: 'number', min: 0.2, max: 200, desc: '体重 kg（只影响 MER 需求，**不影响限值档位**）' },
    bcs: { type: 'number', min: 1, max: 9, desc: '体况评分 1~9' },
    activity: { type: 'string', desc: '活动量档位' },
    breed: { type: 'string', desc: '品种' },
  }

  /** 组合校验：每条原料至少要有一个标识（与 junheng-nutrition 同口径） */
  const checkItems = (items) => {
    const bad = []
    items.forEach((it, i) => {
      const hasName = typeof it.name === 'string' && it.name.trim() !== ''
      const hasCode = typeof it.code === 'string' && it.code.trim() !== ''
      if (!hasName && !hasCode) bad.push(i + 1)
    })
    return bad.length ? `配方条目缺少识别信息：第 ${bad.join('、')} 项既没给 name 也没给 code（每项至少要有一个）` : null
  }

  return {
    assess: {
      summary: '给定配方与目标画像，逐项对照法规限值：四态结论 + 缺口清单 + 配比建议（一步到位，无需手工搬运上游对象）',
      params: {
        items: { type: 'array', required: true, minItems: 1, desc: '配方条目 { name 或 code, weight(克) }', fields: ITEM_FIELDS },
        profile: { type: 'object', desc: '目标画像（缺省按全站默认：物种缺省值 + 中国 GB + 成年维持档）', fields: PROFILE_FIELDS },
      },
      check: (a) => (a.items && a.items.length ? checkItems(a.items) : 'items 至少要给一项原料'),
      run: (a) => {
        const { resolved, unknown } = resolveItems(api, a.items)
        if (!resolved.length) {
          return { ok: false, reason: 'no_ingredient_matched', unknown, note: '没有任何原料匹配上，无法计算。' }
        }
        const profile = { species: api.DEFAULT_SPECIES, ...(a.profile || {}) }
        const recipe = api.computeRecipe(resolved, {}, { species: profile.species })
        if (!recipe || recipe.ok === false) {
          return { ok: false, reason: 'recipe_failed', unknown, note: '配方营养计算失败（通常是总用量为 0）。' }
        }
        // market 从 profile.market 读取（computeRequirements 的 opts.market 是可选覆盖；
        // 这里统一走 profile，避免出现「画像里一个市场、opts 里另一个」的双入口）。
        const req = api.computeRequirements(profile, {})
        const ev = api.evaluateRecipe(recipe, req)
        if (!ev) {
          return { ok: false, reason: 'evaluate_failed', unknown, note: '达标判定无法执行（配方或需求对象缺失）。' }
        }

        const by = (s) => ev.rows.filter((r) => r.status === s)
        const failed = by('fail')
        const low = by('low')
        const undecided = by('nodata')

        return {
          ok: true,
          target: {
            species: req.species,
            speciesLabel: req.speciesLabel,
            stage: req.stage,
            status: req.status,
            statusLabel: req.statusLabel,
            marketId: req.marketId,
            marketLabel: ev.standard.marketLabel,
            sourceLabel: ev.standard.sourceLabel,
            stageLabel: req.standardSource,
            itemCount: ev.standard.items.length,
            wetFood: ev.wetFood,
          },
          summary: {
            total: ev.totalRows,
            ok: by('ok').length,
            low: low.length,
            fail: failed.length,
            nodata: undecided.length,
            judged: ev.judged,
            /** ⚠ `allPass` = 「没有明确未达标项」，**nodata 项不计入**（原样取自 evaluateRecipe）。
             *  要看「所有项都验过、且都达标」请用 `fullyVerified` —— 两者不可互相替代。 */
            allPass: ev.allPass,
            fullyVerified: ev.judged === ev.totalRows && failed.length === 0,
          },
          attained: by('ok').map(briefRow),
          gaps: failed.map((r) => ({ ...briefRow(r), gap: gapOf(r), note: r.note || '' })),
          lowCoverage: low.map((r) => ({ ...briefRow(r), note: r.note || '' })),
          undecided: undecided.map((r) => ({ nutrient: r.nutrient, label: r.label, note: r.note || '' })),
          suggestions: ev.suggestions,
          unknown,
          warnings: ev.standard.warnings,
          note: failed.length
            ? `有 ${failed.length} 项未达标，见 gaps（含展示用缺口量 gap）。`
            : (undecided.length ? `没有未达标项；但有 ${undecided.length} 项无法判定（nodata，不是未达标）。` : ''),
        }
      },
    },

    targets: {
      summary: '列出可用的目标口径（市场 × 物种 × 阶段），评估前先看这里有哪些可选',
      params: {},
      run: () => ({
        defaultMarket: api.DEFAULT_MARKET,
        defaultSpecies: api.DEFAULT_SPECIES,
        markets: api.MARKET_MODES.map((m) => ({ id: m.id, label: m.label, desc: m.desc, sets: m.sets })),
        species: SPECIES,
        stages: STAGES,
        note: '阶段由 profile.status 或年龄推断：月龄 <12 → growth（限值更严）。'
          + '水分形态**不入参** —— 由本配方实测水分自动判定（湿性产品适用更严的牛磺酸下限）。',
      }),
    },
  }
}

/** 门面主流程。返回退出码（不退出进程，便于测试在进程内断言）。 */
export async function main(argv = process.argv.slice(2), io) {
  const out = io || makeIo()
  let api
  try {
    api = {
      ...(await importFromVendor(HERE, PROBE, 'nutrition.js')),
      ...(await importFromVendor(HERE, PROBE, 'standards.js')),
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
