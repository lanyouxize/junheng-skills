#!/usr/bin/env node
/**
 * junheng-pipeline —— **跨技能串联编排门面**（一次调用出全套结果）。
 *
 * ## 为什么需要它
 * 第 1 轮系统检查发现：单独调用各门面时，一个完整配方评估需要 6 次手工调用，
 * 且中间结果（recipe 5043 字符、req 5566 字符）必须**手工搬运**——
 * `labeling.draft` 需要两个上游对象，单管道天然满足不了。
 *
 * ## 本门面做什么
 * **只做编排，不含任何公式**：把「配方 → 营养 → 需求 → 标签 → 成本 → 喂食」
 * 串成一次调用。全部计算仍来自 `src/lib/` 的既有函数（`computeRecipe` /
 * `computeRequirements` / `buildLabelDraft` / `computeCostSheetByMode` /
 * `computeFeedingPlan`），本文件不新增一条业务规则。
 *
 * ## 与 `--as` 的分工
 *   · `--as <参数名>`（在各门面上）：解**单上游**的管道串联，轻量、通用
 *   · `pipeline`（本门面）：解**多上游**的编排，一次出全套
 *
 * 调用形态：
 *   node cli/pipeline.mjs run '{"items":[...],"profile":{...},"cost":{...}}'
 *   node cli/pipeline.mjs run-multi '{"pets":[{"profile":{...},"items":[...]}],"days":30}'
 *   node cli/pipeline.mjs steps   '{"items":[...],"profile":{...}}'   # 只列步骤，不算
 *
 * 退出码：0 成功 / 1 内部错误 / 2 用法或输入错误 / 3 前置条件缺失。
 */
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { importFromVendor, isEntrypoint } from './lib/locate.mjs'
import { runCli } from './lib/runner.mjs'
import { emitError, makeIo } from './lib/output.mjs'
import { speciesEnum } from './lib/paramSchema.mjs'

export const NAME = 'junheng-pipeline'
export const VERSION = '1.1.0'
export const SUMMARY = '跨技能串联编排：一次调用完成「配方→营养→需求→标签稿→成本→喂食计划」全套计算（多宠入口见 run-multi）'
export const PROBE = ['nutrition.js', 'labeling.js', 'costModes.js', 'feedingGuide.js', 'multiPetPlan.js', 'portionLabel.js']
export const DISCLAIMER = '本命令是**编排层**，不含独立公式：所有数值均来自 src/lib 的既有函数，'
  + '与分别调用 junheng-nutrition / -labeling / -cost / -feeding 的结果一致。'
  + '全部为理论计算值，不是检测值；标签部分是底稿不是最终合规结论；喂食部分是建议不是处方。'
  + '`run-multi` 的分装标签是**厨房贴纸**（配方名/每份克数/分装日期/建议食用期限），不是合规标签；'
  + '其中「建议食用期限」必须由调用方给出保质期天数，未给出时留空，本门面不猜保质期。'
  + '任何一步失败都会在该步的 status 里标出并附原因，不会静默跳过。'

const HERE = path.dirname(fileURLToPath(import.meta.url))

const str = (v) => (typeof v === 'string' ? v.trim() : '')

/** 配方条目：{ name 或 code, weight }，与 nutrition 门面同形 */
const ITEM_FIELDS = {
  name: { type: 'string', desc: '原料名称（与 code 二选一）' },
  code: { type: 'string', desc: '物料编号（与 name 二选一）' },
  weight: { type: 'number', required: true, min: 0, max: 100000, desc: '用量（克）' },
}

/**
 * 个体档案：pipeline 必需（喂食与需求都要）。
 * 物种枚举取自单一真源（见 lib/paramSchema.mjs），故必须**按 api 现算**，
 * 不能在模块级固化成常量 —— 那会让真源变更时此处静默过期。
 */
const profileFields = (api) => ({
  species: { type: 'string', enum: speciesEnum(api), desc: '物种（不传则按全站默认，见 species.js）' },
  weightKg: { type: 'number', min: 0.2, max: 200, desc: '体重 kg' },
  ageMonths: { type: 'number', min: 0, max: 400, desc: '月龄' },
  ageText: { type: 'string', desc: '年龄文本' },
  status: { type: 'string', desc: '生理状态' },
  bcs: { type: 'number', min: 1, max: 9, desc: '体况评分 1~9' },
  activity: { type: 'string', desc: '活动量档位' },
  breed: { type: 'string', desc: '品种' },
})

/** 把 {name|code, weight} 解析成 computeRecipe 需要的形状 */
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
 * 送检名单：库内规范名 ∪ 用户原样写的名字。
 * 与 `junheng-nutrition` 的 recipe 口径一致 —— 只送规范名会漏掉「用户写别名/库外名」
 * 这条最常见的命中路径。
 */
function safetySubjects(api, items) {
  const { resolved } = resolveItems(api, items)
  return [...new Set([
    ...resolved.map((r) => r.ingredient.name),
    ...items.map((it) => (typeof it.name === 'string' ? it.name.trim() : '')).filter(Boolean),
  ])]
}

/**
 * 安全闸结论（**第 0 步**）。
 *
 * 为什么它是第 0 步而不是「某一步」：一份含禁用物质的配方，算出再漂亮的营养值、
 * 再精确的成本，也是在为一件不该做的事提供依据。安全必须先于一切计算。
 *
 * 返回 null = **没查**（安全模块未接入 / 无原料）—— 调用方必须显式说明，
 * 不能把 null 渲染成「通过」。
 */
function safetyVerdict(api, items, species) {
  if (typeof api.classifyRecipe !== 'function') return null
  const names = safetySubjects(api, items)
  if (!names.length) return null
  const r = api.classifyRecipe(names.map((name) => ({ name })), { species })
  return {
    species: r.species,
    checked: names,
    summary: r.summary,
    hits: r.rows.filter((x) => x.level === 'banned' || x.level === 'caution').map((x) => ({
      name: x.name, level: x.level, substance: x.substance, conditions: x.conditions,
    })),
    notice: r.summary.blocked
      ? '配方命中【禁用】物质 —— 该配方不应给出。'
      : (r.summary.caution
        ? '配方含【慎用】物质，须先满足各自列明的适用条件（见 hits[].conditions）。'
        : (r.summary.unjudged
          ? `有 ${r.summary.unjudged} 项未被安全库收录 ⇒ 安全性【无法判定】（unknown 不等于安全），请人工确认。`
          : '安全库未命中禁用/慎用物质（注意：未被收录的原料不计入本结论）。')),
  }
}

/**
 * 多宠条目字段（`run-multi` 用）：**每只宠物带自己的配方原料**。
 *
 * 为什么不复用 feeding 的 `pets`（那里 `recipe` 是上游算好的对象）：
 * pipeline 的立身之本是「从原料出发一次跑完」，多宠入口若也要求先算好 recipe，
 * 就等于把串联工作推回给调用方 —— 那正是 pipeline 要消除的搬运。
 */
const petFields = (api) => ({
  label: { type: 'string', desc: '宠物标签（缺省取 name 或「宠物 N」）' },
  name: { type: 'string', desc: '宠物名（label 的备选来源）' },
  profile: { type: 'object', required: true, desc: '个体档案（字段同 run 的 profile）', fields: profileFields(api) },
  items: {
    type: 'array',
    required: true,
    minItems: 1,
    desc: '该宠物的配方原料 { name 或 code, weight(克) }',
    fields: ITEM_FIELDS,
  },
})

/**
 * 逐宠安全结论（多宠入口用）。返回 null = **没查**（安全模块未接入 / 全无原料）。
 * 与单宠的 `safetyVerdict` 同一套筛查，只是按宠物分别跑 —— 多宠常共用一批料，
 * 任一只命中禁用物质都要看得见。
 */
function multiSafetyVerdict(api, pets) {
  if (typeof api.classifyRecipe !== 'function') return null
  const list = Array.isArray(pets) ? pets : []
  const rows = list.map((e, i) => {
    const v = safetyVerdict(api, (e && e.items) || [], (e && e.profile && e.profile.species) || api.DEFAULT_SPECIES)
    return {
      index: i + 1,
      label: (e && (e.label || e.name)) || `宠物 ${i + 1}`,
      checked: v ? v.checked : null,
      summary: v ? v.summary : null,
      hits: v ? v.hits : [],
      notice: v ? v.notice : '未提供 items（配方原料），本次【未做】安全筛查',
    }
  })
  return { blocked: rows.some((r) => r.summary && r.summary.blocked), pets: rows }
}

/** 由已加载的源码模块构造命令表。导出以便测试检视注册表。 */
export function buildCommands(api) {
  /** 一步执行器：把 fn 的失败也结构化，不静默跳过 */
  const step = (name, fn) => {
    try {
      const data = fn()
      const failed = data && data.ok === false
      return { step: name, status: failed ? 'failed' : 'ok', reason: failed ? (data.reason || data.note || '') : '', data }
    } catch (e) {
      return { step: name, status: 'error', reason: (e && e.message) || String(e), data: null }
    }
  }

  return {
    run: {
      summary: '一次调用完成全套：配方营养 → 个体需求 → 标签底稿 → 成本 → 喂食计划',
      params: {
        items: {
          type: 'array',
          required: true,
          minItems: 1,
          desc: '配方条目 { name 或 code, weight(克) }',
          fields: ITEM_FIELDS,
        },
        profile: {
          type: 'object',
          desc: '个体档案；给了才能算需求与喂食计划',
          fields: profileFields(api),
        },
        meta: {
          type: 'object',
          desc: '产品元信息（进标签稿）',
          fields: {
            productName: { type: 'string', desc: '产品名称' },
            brand: { type: 'string', desc: '品牌' },
            netWeight: { type: 'string', desc: '净含量' },
            batchNo: { type: 'string', desc: '批号' },
            manufacturer: { type: 'string', desc: '生产商' },
            date: { type: 'string', desc: '日期' },
          },
        },
        cost: {
          type: 'object',
          desc: '成本口径参数（喂食与成本计算需要）',
          fields: {
            mode: { type: 'string', enum: ['general', 'freeze_dry', 'cat_stick'], desc: '成本口径' },
            batchCount: { type: 'number', min: 0, desc: '通用口径：袋数' },
            gramPerBag: { type: 'number', min: 0, desc: '通用口径：每袋克重' },
            yieldKg: { type: 'number', min: 0, desc: '通用口径：产量 kg' },
            inputKg: { type: 'number', min: 0, desc: '冻干/猫条：投料 kg' },
            outputKg: { type: 'number', min: 0, desc: '冻干/猫条：成品产量 kg' },
            lossRate: { type: 'number', min: 0, max: 1, desc: '损耗率' },
            processingFeePerTon: { type: 'number', min: 0, desc: '通用口径：加工费 元/吨' },
            specId: { type: 'string', desc: '猫条：规格 id' },
            packageGram: { type: 'number', min: 0, desc: '冻干：包装克重' },
          },
        },
      },
      check: (a) => {
        if (!a.items || !a.items.length) return 'items 至少要给一项原料'
        // 第 0 步（安全闸）的**阻断**判定放在 check 里，而不是 run 里：
        // runner 只有这一条「不执行 run 就返回非 0」的通道（退出码 2）。放进 run 里
        // 就只能靠 JSON 里的 ok:false 表达 —— 而调用方脚本/`&&` 链看到退出码 0
        // 会继续往下跑，那正是「链路早停」失效的时刻。
        if (typeof api.classifyRecipe !== 'function') return null
        const v = safetyVerdict(api, a.items, (a.profile && a.profile.species) || api.DEFAULT_SPECIES)
        if (v && v.summary.blocked) {
          const hit = v.hits.filter((h) => h.level === 'banned').map((h) => `${h.name}（${h.substance}）`)
          return `安全闸阻断（第 0 步）：配方命中禁用物质 ${hit.join('、')} ⇒ 链路早停，不进入营养计算。`
            + '请先移除/更换这些原料（可查 junheng-safety 的 list-substances 命令），或咨询执业兽医。'
        }
        return null
      },
      run: (a) => {
        const steps = []
        const profile = a.profile || null
        const species = (profile && profile.species) || null

        // ⓪ 安全闸（第 0 步）：banned 已由 check 拦截（链路根本不会走到这里）；
        //    这里记录已通过的筛查结论 —— caution / unknown 也留在链路输出里，不静默。
        {
          const verdict = safetyVerdict(api, a.items, species || api.DEFAULT_SPECIES)
          steps.push(verdict
            ? { step: 'safety', status: 'ok', reason: '', data: verdict }
            : { step: 'safety', status: 'skipped', reason: '安全模块未接入（api.classifyRecipe 不可用）—— 本次未做安全筛查', data: null })
        }

        // ① 配方营养
        const { resolved, unknown } = resolveItems(api, a.items)
        let recipe = null
        if (!resolved.length) {
          steps.push({ step: 'recipe', status: 'failed', reason: 'no_ingredient_matched', data: { unknown } })
        } else {
          const r = step('recipe', () => api.computeRecipe(resolved, {}, { species }))
          steps.push(r)
          recipe = r.data && r.data.ok ? r.data : null
        }

        // ② 个体需求
        let req = null
        if (profile && Number.isFinite(Number(profile.weightKg))) {
          const r = step('requirements', () => api.computeRequirements(profile))
          steps.push(r)
          req = r.data && r.data.ok !== false ? r.data : r.data
        } else {
          steps.push({ step: 'requirements', status: 'skipped', reason: '未提供 profile.weightKg', data: null })
        }

        // ③ 标签底稿（需要 recipe + req 两者 —— 这正是单管道做不到的地方）
        if (recipe && req) {
          steps.push(step('labeling', () => api.buildLabelDraft({ recipe, req, meta: a.meta || {} })))
        } else {
          steps.push({
            step: 'labeling',
            status: 'skipped',
            reason: recipe ? '未提供个体档案（req 缺失）' : '配方未计算成功',
            data: null,
          })
        }

        // ④ 成本（按配方换算成本行后交给 costModes）
        if (recipe && a.cost) {
          const lines = recipe.lines.map((l) => ({
            code: l.code || '', name: l.name, unit: 'kg', ratio: l.share / 100, unitPrice: l.price,
          }))
          steps.push(step('cost', () => {
            const s = api.computeCostSheetByMode({ ...a.cost, lines })
            return s || { ok: false, reason: 'no_result', note: '该成本口径在给定参数下算不出结果。' }
          }))
        } else {
          steps.push({ step: 'cost', status: 'skipped', reason: recipe ? '未提供 cost 参数' : '配方未计算成功', data: null })
        }

        // ⑤ 喂食计划
        if (profile && Number.isFinite(Number(profile.weightKg)) && recipe) {
          steps.push(step('feeding', () => api.computeFeedingPlan(profile, recipe, req, {})))
        } else {
          steps.push({ step: 'feeding', status: 'skipped', reason: profile ? '配方未计算成功' : '未提供 profile', data: null })
        }

        const failed = steps.filter((s) => s.status === 'failed' || s.status === 'error')
        return {
          ok: failed.length === 0,
          unknown,
          summary: {
            total: steps.length,
            ok: steps.filter((s) => s.status === 'ok').length,
            skipped: steps.filter((s) => s.status === 'skipped').length,
            failed: failed.length,
          },
          steps,
          note: failed.length
            ? '有步骤失败，请看对应 step 的 reason —— 本命令不会静默跳过失败步骤。'
            : (steps.some((s) => s.status === 'skipped') ? '部分步骤被跳过（通常是缺少可选参数），请看各 step 的 reason。' : ''),
        }
      },
    },

    'run-multi': {
      summary: '多宠编排入口：逐宠「原料→营养→需求→喂食量」→ 多宠合计与合并采购清单 → 同日分装排期与分装标签',
      params: {
        pets: {
          type: 'array',
          required: true,
          minItems: 1,
          maxItems: 20,
          desc: '宠物条目（每只一条，自带原料）',
          fields: petFields(api),
        },
        days: { type: 'number', min: 1, max: 365, default: 30, desc: '总量/采购覆盖天数（默认 30 天 ≈ 一个月）' },
        portionDays: { type: 'number', min: 1, max: 90, default: 7, desc: '每袋覆盖天数（默认 7 = 按周分装）' },
        filledDate: { type: 'string', desc: '分装日期 YYYY-MM-DD（缺省按今天；同日分装共用）' },
        shelfLifeDays: { type: 'number', min: 1, max: 3650, desc: '保质期天数（不传 ⇒ 建议食用期限留空，不猜）' },
        form: { type: 'string', enum: Object.keys(api.FORM_TIPS || {}), desc: '产品形态（决定解冻/保存提示）' },
      },
      check: (a) => {
        if (!a.pets || !a.pets.length) return 'pets 至少要给一只宠物'
        const bad = (a.pets || []).findIndex((p) => !(p && p.items && p.items.length))
        if (bad >= 0) return `pets[${bad}].items 必填（没有原料就无法算该宠的配方）`
        const m = multiSafetyVerdict(api, a.pets)
        if (m && m.blocked) {
          const who = m.pets.filter((r) => r.summary && r.summary.blocked).map((r) => {
            const hit = (r.hits || []).filter((h) => h.level === 'banned').map((h) => `${h.name}（${h.substance}）`)
            return `${r.label}：${hit.join('、')}`
          })
          return `安全闸阻断（第 0 步）：${who.join('；')} ⇒ 链路早停，不进入营养/喂食/分装计算。`
            + '多宠常共用同一批料，先出采购单与分装贴纸再标注就晚了。请先移除/更换这些原料，或咨询执业兽医。'
        }
        return null
      },
      run: (a) => {
        const steps = []
        const days = Number.isFinite(Number(a.days)) ? Number(a.days) : 30
        const pets = a.pets || []

        // ⓪ 安全闸（逐宠）：banned 已由 check 拦截，这里记录已过筛的结论（caution/unknown 不静默）
        {
          const m = multiSafetyVerdict(api, pets)
          steps.push(m
            ? { step: 'safety', status: 'ok', reason: '', data: m }
            : { step: 'safety', status: 'skipped', reason: '安全模块未接入（api.classifyRecipe 不可用）—— 本次未做安全筛查', data: null })
        }

        // ① 逐宠：原料 → 配方 →（有体重则）需求
        const entries = []
        const petRows = []
        pets.forEach((p, i) => {
          const label = str(p && p.label) || str(p && p.name) || `宠物 ${i + 1}`
          const profile = (p && p.profile) || null
          const species = (profile && profile.species) || null
          const { resolved, unknown } = resolveItems(api, (p && p.items) || [])
          let recipe = null
          let req = null
          const row = { index: i + 1, label, unknown, recipeOk: false, reqStatus: 'skipped' }
          if (!resolved.length) {
            row.recipeReason = 'no_ingredient_matched'
          } else {
            const r = step('recipe', () => api.computeRecipe(resolved, {}, { species }))
            recipe = r.data && r.data.ok ? r.data : null
            row.recipeOk = Boolean(recipe)
            if (!recipe) row.recipeReason = r.reason || 'compute_failed'
          }
          if (profile && Number.isFinite(Number(profile.weightKg))) {
            const r = step('requirements', () => api.computeRequirements(profile))
            req = r.data || null
            row.reqStatus = r.status
          }
          entries.push({ label, name: str(profile && profile.name), profile, recipe, req })
          petRows.push(row)
        })
        steps.push({
          step: 'recipes',
          status: petRows.some((r) => !r.recipeOk) ? 'failed' : 'ok',
          reason: petRows.some((r) => !r.recipeOk) ? '有宠物的配方未能计算（见各条 recipeReason / unknown）' : '',
          data: petRows,
        })

        // ② 多宠合计 + 合并采购清单（喂食量在此步逐宠算出）
        const plan = api.computeMultiPetPlan(entries, { days })
        steps.push({
          step: 'multiPlan',
          status: plan.ok ? 'ok' : 'failed',
          reason: plan.ok ? '' : plan.reason,
          data: plan,
        })

        // ③ 同日分装排期 + 分装标签（只送算得出喂食量的宠物）
        const okPets = (plan.pets || []).filter((x) => x.ok)
        const portions = api.computePortionLabels(
          okPets.map((x) => ({ recipeName: x.label, petLabel: x.label, gramsPerDay: x.gramsPerDay })),
          {
            days,
            portionDays: a.portionDays,
            filledDate: a.filledDate,
            shelfLifeDays: a.shelfLifeDays,
            form: a.form,
          },
        )
        const failedPets = (plan.pets || []).filter((x) => !x.ok).map((x) => ({ label: x.label, failReason: x.failReason }))
        steps.push({
          step: 'portions',
          status: okPets.length ? (portions.ok ? 'ok' : 'failed') : 'skipped',
          reason: okPets.length ? portions.reason : '没有宠物算出喂食量，无可分装内容',
          data: { ...portions, failedPets },
        })

        const failed = steps.filter((s) => s.status === 'failed' || s.status === 'error')
        return {
          ok: failed.length === 0,
          days,
          summary: {
            total: steps.length,
            ok: steps.filter((s) => s.status === 'ok').length,
            skipped: steps.filter((s) => s.status === 'skipped').length,
            failed: failed.length,
            petCount: plan.petCount,
            petOkCount: plan.okCount,
            petFailedCount: plan.failedCount,
            labelCount: (portions.labels || []).length,
          },
          steps,
          note: failedPets.length
            ? `有 ${failedPets.length} 只宠物未算出喂食量（${failedPets.map((x) => x.label).join('、')}）：它们【未计入】总量、采购清单与分装，补齐数据后请重跑。`
            : (failed.length
              ? '有步骤失败，请看对应 step 的 reason —— 本命令不会静默跳过失败步骤。'
              : (steps.some((s) => s.status === 'skipped') ? '部分步骤被跳过（通常是缺少可选参数），请看各 step 的 reason。' : '')),
        }
      },
    },

    steps: {
      summary: '只列出串联会执行哪些步骤与各自需要什么参数（不计算，排错与自检用）',
      params: {
        items: { type: 'array', desc: '配方条目（可省略，仅用于说明）', fields: ITEM_FIELDS },
        profile: { type: 'object', desc: '个体档案（可省略）', fields: profileFields(api) },
        meta: { type: 'object', desc: '产品元信息（可省略）' },
        cost: { type: 'object', desc: '成本参数（可省略）' },
      },
      run: (a) => ({
        ok: true,
        steps: [
          { n: 0, step: 'safety', needs: 'items (+ profile.species)', source: 'toxicology.js classifyRecipe', output: '四态结论（banned 则链路早停、退出码 2）', blocking: true },
          { n: 1, step: 'recipe', needs: 'items', source: 'nutrition.js computeRecipe', output: '营养素/能量/钙磷比/成本行' },
          { n: 2, step: 'requirements', needs: 'profile.weightKg', source: 'nutrition.js computeRequirements', output: 'RER/MER 与指标' },
          { n: 3, step: 'labeling', needs: 'recipe + req + meta', source: 'labeling.js buildLabelDraft', output: '保证值表/配料表/合规/风险' },
          { n: 4, step: 'cost', needs: 'recipe + cost', source: 'costModes.js computeCostSheetByMode', output: '成本表' },
          { n: 5, step: 'feeding', needs: 'profile + recipe', source: 'feedingGuide.js computeFeedingPlan', output: '喂食计划/体况/过渡/监测' },
        ],
        multi: {
          command: 'run-multi',
          steps: [
            { n: 0, step: 'safety', needs: 'pets[].items (+ profile.species)', source: 'toxicology.js classifyRecipe（逐宠）', blocking: true },
            { n: 1, step: 'recipes', needs: 'pets[].items + pets[].profile', source: 'nutrition.js computeRecipe/computeRequirements', output: '逐宠配方与需求' },
            { n: 2, step: 'multiPlan', needs: 'pets + days', source: 'multiPetPlan.js computeMultiPetPlan', output: '逐宠喂食量 + 合计 + 合并采购清单' },
            { n: 3, step: 'portions', needs: 'pets + portionDays/shelfLifeDays/form', source: 'portionLabel.js computePortionLabels', output: '同日分装排期 + 分装标签' },
          ],
        },
        provided: {
          items: !!(a.items && a.items.length),
          profile: !!a.profile,
          weightKg: !!(a.profile && Number.isFinite(Number(a.profile.weightKg))),
          meta: !!a.meta,
          cost: !!a.cost,
        },
      }),
    },

    describe: undefined, // 占位：describe 由 runner 作为内置命令提供
  }
}

/** 门面主流程。返回退出码（不退出进程，便于测试在进程内断言）。 */
export async function main(argv = process.argv.slice(2), io) {
  const out = io || makeIo()
  let api
  try {
    api = {
      ...(await importFromVendor(HERE, 'nutrition.js', 'nutrition.js')),
      ...(await importFromVendor(HERE, 'labeling.js', 'labeling.js')),
      ...(await importFromVendor(HERE, 'costModes.js', 'costModes.js')),
      ...(await importFromVendor(HERE, 'feedingGuide.js', 'feedingGuide.js')),
      // species.js 是参数面物种枚举的真源（见 lib/paramSchema.mjs），必须并入 api ——
      // 它与上面四个模块同目录（项目布局 src/lib、技能布局 core/scripts/vendor）。
      ...(await importFromVendor(HERE, 'species.js', 'species.js')),
    }
    // 安全闸（N1 接线 · E3）：第 0 步先过安全库，再谈营养。
    // 只取 classifyRecipe —— 不整包展开 toxicology（`lookup` / `SOURCES` 这类泛名
    // 平铺进 api 会污染命名空间，也会让 api 的来由变得不可追溯）。
    const tox = await importFromVendor(HERE, 'nutrition.js', 'toxicology.js')
    api.classifyRecipe = tox.classifyRecipe
    // 多宠入口（N3-b）：多宠组合层 + 分装排期/标签。两者都是纯组合/纯函数，
    // 不含新公式 —— 只取需要的成员，不整包展开（避免泛名平铺污染 api 命名空间）。
    const mp = await importFromVendor(HERE, 'feedingGuide.js', 'multiPetPlan.js')
    const pl = await importFromVendor(HERE, 'portionLabel.js', 'portionLabel.js')
    api.computeMultiPetPlan = mp.computeMultiPetPlan
    api.computePortionLabels = pl.computePortionLabels
    api.FORM_TIPS = pl.FORM_TIPS
  } catch (e) {
    return emitError(out, { name: NAME, kind: 'precondition', message: `无法加载源码模块：${(e && e.message) || e}` })
  }
  const commands = buildCommands(api)
  delete commands.describe // 内置命令，不占业务命名空间
  return runCli({
    name: NAME,
    version: VERSION,
    summary: SUMMARY,
    disclaimer: DISCLAIMER,
    commands,
    argv,
    io: out,
  })
}

if (isEntrypoint(import.meta.url)) {
  process.exitCode = await main(process.argv.slice(2))
}