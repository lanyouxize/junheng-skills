#!/usr/bin/env node
/**
 * junheng-feeding —— 喂食指南的命令行门面（喂食计划 / 体况策略 / 换粮过渡 / 监测）。
 *
 * 门面里不含任何喂养规则：全部来自 `src/lib/feedingGuide.js`
 * （其 RER/MER 取自 `energy.js`，BCS 判据取自 `bcsChart.js`）。
 *
 * ⚠ 产物是**喂养建议**，不是处方。目标体重、减重速度必须由人（最好含兽医）确认。
 *
 * 调用形态（详见 `--help`）：
 *   node cli/feeding.mjs plan '{"profile":{"species":"cat","weightKg":4},"recipe":{...},"req":{...}}'
 *   node cli/feeding.mjs plan-multi '{"pets":[...],"days":30}'
 *   node cli/feeding.mjs portion-label '{"pets":[...],"portionDays":7,"shelfLifeDays":30,"form":"frozen_raw"}'
 *   node cli/feeding.mjs bcs-policy '{"species":"cat","score":7}'
 *
 * 退出码：0 成功 / 1 内部错误 / 2 用法或输入错误 / 3 前置条件缺失。
 */
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { importFromVendor, isEntrypoint } from './lib/locate.mjs'
import { runCli } from './lib/runner.mjs'
import { emitError, makeIo } from './lib/output.mjs'
import { speciesEnum } from './lib/paramSchema.mjs'

export const NAME = 'junheng-feeding'
export const VERSION = '1.2.0'
export const SUMMARY = '喂食指南：喂食计划（克/日、餐次、过渡、监测）、体况策略、换粮过渡与兽医信号、多宠合并采购清单、分装排期与分装标签'
export const PROBE = ['feedingGuide.js', 'species.js', 'multiPetPlan.js', 'portionLabel.js']
export const DISCLAIMER = '产物是喂养建议，不是处方。能量为理论计算值（非检测值）。'
  + '体况评分为筛查工具、不是兽医诊断；任何不在理想区（犬 4~5 分、猫 5 分）的评分都建议请兽医评估。'
  + '猫的减重速度必须比犬更慢（过快会诱发肝脂沉积症）。'
  + '目标体重与增减喂食量必须由人（最好含兽医）确认后再执行，请勿只凭本门面输出直接改变饲喂。'

const HERE = path.dirname(fileURLToPath(import.meta.url))

/**
 * 从上游配方对象里取出「送检名单」。
 *
 * feeding 的入口是 `recipe`（computeRecipe 的**返回对象**），不是 items ——
 * 所以名单只能从 `lines[].name` 取（那是库内规范名，比用户输入更可靠）。
 * 没有配方（`recipe` 可省略）时返回空数组 ⇒ 调用方必须显式说明「未做筛查」，
 * **绝不能**把「没查」当作「查过且安全」。
 */
function subjectsFromRecipe(recipe) {
  const lines = Array.isArray(recipe && recipe.lines) ? recipe.lines : []
  const fromLines = lines.map((l) => (typeof (l && l.name) === 'string' ? l.name.trim() : ''))
  // 上游若正是 junheng-nutrition 的 recipe 输出，它已带 `safety.checked`
  // （含「用户原样写的名字」—— 库外原料与别名都在里面）。串联时继承这份名单，
  // 否则「配方里写了洋葱粉、但库里查不到 ⇒ 没进 lines」会在喂食这关被静默放过。
  const up = recipe && recipe.safety && Array.isArray(recipe.safety.checked) ? recipe.safety.checked : []
  return [...new Set([...fromLines, ...up].filter(Boolean))]
}

/**
 * 按**已给定的名单**做安全筛查。
 *
 * 抽出这一步的原因：名单来源不止一处。`plan` 只能从 `recipe` 里取（lines + 上游
 * `safety.checked`），而多宠命令额外拿到了 `unmatched`（用户原样写的库外原料名）——
 * 后者恰恰是 `recipe.lines` 取不到的那一批。名单能换，筛查口径不能换。
 */
function screenNames(api, names, species) {
  if (!names.length) return null
  if (typeof api.classifyRecipe !== 'function') {
    return { skipped: true, reason: '安全模块未加载（api.classifyRecipe 不可用）—— 本次未做安全筛查' }
  }
  const r = api.classifyRecipe(names.map((name) => ({ name })), { species })
  return {
    species: r.species,
    checked: names,
    summary: r.summary,
    hits: r.rows.filter((x) => x.level === 'banned' || x.level === 'caution').map((x) => ({
      name: x.name, level: x.level, substance: x.substance, conditions: x.conditions,
    })),
    notice: r.summary.blocked
      ? '配方命中【禁用】物质 —— 请勿按本计划饲喂。'
      : (r.summary.caution
        ? '配方含【慎用】物质，须先满足各自列明的适用条件（见 hits[].conditions）。'
        : (r.summary.unjudged
          ? `有 ${r.summary.unjudged} 项未被安全库收录 ⇒ 安全性【无法判定】（unknown 不等于安全），请人工确认。`
          : '安全库未命中禁用/慎用物质（注意：未被收录的原料不计入本结论）。')),
  }
}

/**
 * 安全闸（**前置**校验）：喂食计划是**建议** —— 给一份含禁用物质的配方配喂食量，
 * 等于把不该喂的东西变成了「每天喂多少」的可执行方案。所以这里**必须**先拦。
 *
 * 分工：`banned` ⇒ 由 check 钩子拒绝（退出码 2，不产出计划）；`caution`/`unknown`
 * ⇒ 不阻断，但结论一并进输出（让人看得见，而不是被一个「计划已生成」的信号盖过去）。
 */
function safetyScreen(api, recipe, species) {
  return screenNames(api, subjectsFromRecipe(recipe), species)
}

/**
 * 多宠条目的送检名单 = `recipe` 名单 ∪ `unmatched` 名单。
 *
 * 为什么不只取 recipe：`computeRecipe().lines` 只含**命中原料库**的条目，库外原料
 * （如「洋葱粉」若库内无此条）在 `parseRecipeText()` 里就是 `ingredient:null`，
 * 进不了 lines。多宠命令拿到了 `unmatched`，正好补上这一批 —— 否则一份「库里查不到
 * 的禁用原料」会在安全闸这一关被静默放过，而它恰恰是最该被拦下的那类。
 */
function multiSubjects(entry) {
  const fromRecipe = subjectsFromRecipe(entry && entry.recipe)
  const fromUnmatched = (Array.isArray(entry && entry.unmatched) ? entry.unmatched : [])
    .map((u) => (u && (u.rawName || u.name) ? String(u.rawName || u.name).trim() : ''))
    .filter(Boolean)
  return [...new Set([...fromRecipe, ...fromUnmatched])]
}

/**
 * 多宠安全闸：**逐宠**筛查，任一只命中禁用物质即整体拒绝（check 钩子返回字符串 ⇒ 退出码 2）。
 *
 * 为什么是整体拒绝，而不是「只跳过那一只」：多宠家庭往往共用同一批原料、同一份成品。
 * 一只的配方命中禁用物质，说明**这批料已经进了采购清单**——先出清单再在旁边标一句
 * 「其中一只的配方有问题」已经晚了，用户手里拿到的仍是一张可执行的采购单。
 */
function multiSafetyBlocked(api, pets) {
  if (typeof api.classifyRecipe !== 'function') return null
  const hits = []
  ;(pets || []).forEach((e, i) => {
    const s = screenNames(api, multiSubjects(e), (e && e.profile && e.profile.species) || api.DEFAULT_SPECIES)
    if (s && s.summary && s.summary.blocked) {
      const label = (e && (e.label || e.name)) || `宠物 ${i + 1}`
      const banned = s.hits.filter((h) => h.level === 'banned').map((h) => `${h.name}（${h.substance}）`)
      hits.push(`${label}：${banned.join('、')}`)
    }
  })
  if (!hits.length) return null
  return `安全闸阻断：以下宠物的配方命中禁用物质 —— ${hits.join('；')}。`
    + '已拒绝生成多宠计划与采购清单（多宠常共用同一批料，先出清单再标注就晚了）。'
    + '请先移除/更换这些原料（可查 junheng-safety 的 list-substances 命令），或咨询执业兽医。'
}

/** 逐宠安全筛查结论（不阻断的 caution/unknown 也要看得见，不由「计划已生成」盖过去） */
function multiSafety(api, pets) {
  return (pets || []).map((e, i) => {
    const s = screenNames(api, multiSubjects(e), (e && e.profile && e.profile.species) || api.DEFAULT_SPECIES)
    return {
      index: i + 1,
      label: (e && (e.label || e.name)) || `宠物 ${i + 1}`,
      checked: s ? s.checked : null,
      summary: s ? s.summary : null,
      skipped: s ? Boolean(s.skipped) : true,
      notice: s
        ? (s.notice || s.reason)
        : '未提供配方（recipe），本次【未做】安全筛查；喂食量只与能量有关，原料安全性请另行确认',
    }
  })
}

/** 由已加载的源码模块构造命令表。导出以便测试检视注册表。 */
export function buildCommands(api) {
  // 参数面枚举取自单一真源（见 lib/paramSchema.mjs），门面内不再写枚举字面量。
  const SPECIES = speciesEnum(api)

  /** 个体档案字段表：plan 与 plan-multi 共用同一份 —— 同一份 profile 不该在两个命令里合法字段不同 */
  const PROFILE_FIELDS = {
    species: { type: 'string', enum: SPECIES, default: api.DEFAULT_SPECIES, desc: '物种' },
    weightKg: { type: 'number', min: 0.2, max: 200, desc: '体重 kg' },
    ageMonths: { type: 'number', min: 0, max: 400, desc: '月龄' },
    ageText: { type: 'string', desc: '年龄文本' },
    status: { type: 'string', desc: '生理状态' },
    bcs: { type: 'number', min: 1, max: 9, desc: '体况评分 1~9（决定能量调整与是否进入减重策略）' },
    activity: { type: 'string', desc: '活动量档位' },
  }

  /** 多宠条目字段表（plan-multi / purchase-list 共用） */
  const PET_FIELDS = {
    label: { type: 'string', desc: '宠物标签（采购清单按它追溯「哪只用了哪个物料」；缺省取 name 或「宠物 N」）' },
    name: { type: 'string', desc: '宠物名（label 的备选来源）' },
    profile: { type: 'object', required: true, desc: '个体档案（字段同 plan 命令）', fields: PROFILE_FIELDS },
    recipe: { type: 'object', open: true, desc: 'computeRecipe 的返回对象（含能量时才能出克/日）' },
    req: { type: 'object', open: true, desc: 'computeRequirements 的返回对象' },
    unmatched: {
      type: 'array',
      desc: '未匹配原料（parseRecipeText 里 ingredient 为 null 的条目）。不传 ⇒ 采购清单不会列出它们，会静默少买',
      fields: {
        rawName: { type: 'string', required: true, desc: '用户原样写的原料名' },
        weight: { type: 'number', min: 0, desc: '配方中该原料的份量（与 recipe 同一口径）' },
      },
    },
  }

  /**
   * 分装条目字段表 = 多宠条目 + `recipeName`。
   * 单独一份而不是改 PET_FIELDS：`recipeName` 只有分装标签用得上
   * （贴纸上要印配方名），不该顺手扩大 plan-multi / purchase-list 的合法字段面。
   */
  const PORTION_PET_FIELDS = {
    ...PET_FIELDS,
    recipeName: { type: 'string', desc: '配方名（分装贴纸用；缺省取宠物 label）' },
  }

  /** 多宠命令共用参数面 */
  const MULTI_PARAMS = {
    pets: {
      type: 'array',
      required: true,
      minItems: 1,
      maxItems: 20,
      desc: '宠物条目（每只一条）',
      fields: PET_FIELDS,
    },
    days: {
      type: 'number',
      min: 1,
      max: 365,
      default: 30,
      desc: '采购口径天数（默认 30 天 ≈ 一个月）',
    },
  }

  return {
    plan: {
      summary: '生成完整喂食计划（能量、克/日、餐次、过渡、监测、储存提示）',
      params: {
        profile: { type: 'object', required: true, desc: '个体档案', fields: PROFILE_FIELDS },
        recipe: { type: 'object', open: true, desc: 'computeRecipe 的返回对象（含能量时才能出克/日）' },
        req: { type: 'object', open: true, desc: 'computeRequirements 的返回对象' },
      },
      check: (a) => {
        if (!(a.profile && Number.isFinite(Number(a.profile.weightKg)))) return 'profile.weightKg 必填（没有体重无法算能量与喂食量）'
        // 前置安全拦截：命中禁用物质 ⇒ 不生成喂食计划（退回用法错误，退出码 2）。
        // 放在 check 而不是 run 里，是为了「run 根本不执行」—— 只要执行了，就一定有
        // 一份看着可用的计划泄出去（后续哪怕再标一句「含禁用」也晚了）。
        const s = safetyScreen(api, a.recipe, a.profile.species || api.DEFAULT_SPECIES)
        if (s && s.summary && s.summary.blocked) {
          const hit = s.hits.filter((h) => h.level === 'banned').map((h) => `${h.name}（${h.substance}）`)
          return `安全闸阻断：配方命中禁用物质 ${hit.join('、')} ⇒ 已拒绝生成喂食计划。`
            + '请先移除/更换这些原料（可查 junheng-safety 的 list-substances 命令），或咨询执业兽医。'
        }
        return null
      },
      run: (a) => {
        const plan = api.computeFeedingPlan(a.profile, a.recipe || null, a.req || null, {})
        const safety = safetyScreen(api, a.recipe, a.profile.species || api.DEFAULT_SPECIES)
        // 没有配方就没法筛查 —— 必须明说，不能让人以为「计划出来了 = 也查过安全了」
        if (!safety) {
          return { ...plan, safety: null, safetyNote: '未提供配方（recipe），本次【未做】安全筛查；喂食量只与能量有关，原料安全性请另行确认。' }
        }
        return { ...plan, safety }
      },
    },

    'plan-multi': {
      summary: '多宠聚合：逐宠算喂食量并合计，同时给出按物料编号归并的合并采购清单',
      params: MULTI_PARAMS,
      check: (a) => multiSafetyBlocked(api, a.pets),
      run: (a) => {
        const plan = api.computeMultiPetPlan(a.pets, { days: a.days })
        // 逐宠安全结论一并带出：caution/unknown 不能被「计划已生成」这个信号盖过去
        return { ...plan, safety: multiSafety(api, a.pets) }
      },
    },

    'purchase-list': {
      summary: '合并采购清单：只输出按物料编号归并的原料需求量（多宠合计，含未匹配原料）',
      params: MULTI_PARAMS,
      check: (a) => multiSafetyBlocked(api, a.pets),
      run: (a) => {
        const plan = api.computeMultiPetPlan(a.pets, { days: a.days })
        return {
          ok: plan.ok,
          days: plan.days,
          petCount: plan.petCount,
          okCount: plan.okCount,
          failedCount: plan.failedCount,
          reason: plan.reason,
          purchase: plan.purchase,
          warnings: plan.warnings,
        }
      },
    },

    'portion-label': {
      summary: '同日分装排期 + 分装标签：把每宠每日用量按「每袋 N 天」拆袋，并出可打印贴纸（配方名/每份克数/分装日期/建议食用期限/解冻提示）',
      params: {
        pets: {
          type: 'array',
          required: true,
          minItems: 1,
          maxItems: 20,
          desc: '宠物条目（每只一条，形状同 plan-multi）',
          fields: PORTION_PET_FIELDS,
        },
        days: {
          type: 'number',
          min: 1,
          max: 365,
          default: 30,
          desc: '总量覆盖天数（默认 30 天 ≈ 一个月，与采购口径一致）',
        },
        portionDays: {
          type: 'number',
          min: 1,
          max: 90,
          default: 7,
          desc: '每袋覆盖天数（默认 7 = 按周分装，对齐喂食指南既有文案「按一周用量分装小袋」）',
        },
        filledDate: { type: 'string', desc: '分装日期 YYYY-MM-DD（缺省按今天；同日分装的每张标签共用此日期）' },
        shelfLifeDays: {
          type: 'number',
          min: 1,
          max: 3650,
          desc: '保质期天数。建议食用期限 = 分装日期 + 本值；**不传就留空**（本命令不猜保质期）',
        },
        form: {
          type: 'string',
          enum: Object.keys(api.FORM_TIPS || {}),
          desc: '产品形态（决定解冻/保存提示）。不传则提示语明说「请按实际形态填写」，不代填',
        },
      },
      // 安全闸同样是前置：分装的是**食物**，含禁用物质的配方不该被分装成一份份可执行的贴纸
      check: (a) => multiSafetyBlocked(api, a.pets),
      run: (a) => {
        const plan = api.computeMultiPetPlan(a.pets, { days: a.days })
        const okPets = (plan.pets || []).filter((p) => p.ok)
        const failedPets = (plan.pets || []).filter((p) => !p.ok).map((p) => ({
          label: p.label, failReason: p.failReason,
        }))

        /* 只把**算得出喂食量**的宠物送进分装：算不出的若按 0 参与，
           会生成一张 0 克的贴纸 —— 那既是废话，也会让人以为「这只也排进去了」。 */
        const entries = okPets.map((p, i) => {
          const raw = (a.pets || [])[plan.pets.indexOf(p)] || {}
          const rn = raw && typeof raw.recipeName === 'string' ? raw.recipeName.trim() : ''
          return { recipeName: rn || p.label, petLabel: p.label, gramsPerDay: p.gramsPerDay }
        })

        const portions = api.computePortionLabels(entries, {
          days: a.days,
          portionDays: a.portionDays,
          filledDate: a.filledDate,
          shelfLifeDays: a.shelfLifeDays,
          form: a.form,
        })

        const text = (portions.labels || []).map((l) => api.renderPortionLabelText(l)).join('\n\n')

        return {
          ok: portions.ok,
          days: plan.days,
          petCount: plan.petCount,
          okCount: plan.okCount,
          failedCount: plan.failedCount,
          filledDate: portions.filledDate,
          portionDays: portions.portionDays,
          schedules: portions.schedules,
          labels: portions.labels,
          text,
          labelCount: (portions.labels || []).length,
          failedPets,
          warnings: [...(plan.warnings || []), ...(portions.warnings || [])],
          note: portions.note,
          reason: portions.reason || (failedPets.length
            ? `有 ${failedPets.length} 只宠物未算出喂食量，未参与分装：${failedPets.map((p) => p.label).join('、')}`
            : ''),
          safety: multiSafety(api, a.pets),
        }
      },
    },

    render: {
      summary: '把喂食计划渲染成可直接粘贴的纯文本',
      params: {
        plan: { type: 'object', required: true, open: true, desc: 'plan 命令的返回 data' },
      },
      run: (a) => ({ text: api.renderFeedingGuideText(a.plan, {}) }),
    },

    'bcs-policy': {
      summary: '按体况评分取喂养策略（能量调整幅度、是否进入减重、限制原因）',
      params: {
        score: { type: 'number', required: true, min: 1, max: 9, integer: true, desc: '体况评分 1~9' },
        species: { type: 'string', enum: SPECIES, default: api.DEFAULT_SPECIES, desc: '物种（犬猫理想区不同）' },
      },
      run: (a) => {
        const sp = a.species === 'cat' ? 'cat' : 'dog'
        return {
          species: sp,
          score: a.score,
          entry: api.bcsEntry(a.score),
          group: api.bcsGroup(a.score),
          policy: api.bcsPolicy(a.score, sp),
          blockReason: api.bcsAdjustBlockReason(api.bcsGroup(a.score)),
          weightChange: api.weightChangeText(sp, 'lose'),
          treatEnergyMaxPercent: api.TREAT_ENERGY_MAX_PERCENT,
          mcsHint: api.MCS_HINT,
        }
      },
    },

    'bcs-scale': {
      /* ⚠ 以前写「犬猫通用」并返回全局 `BCS_SCALE` —— 那张表按**犬口径**写死
         （4 分归 ideal），猫 4 分会被读成「理想」。现在必须指定物种，返回按物种校正后的表。 */
      summary: '查 9 分制判据表与分组（须指定物种：犬 4~5 分为理想、猫仅 5 分）',
      params: {
        species: { type: 'string', enum: SPECIES, default: api.DEFAULT_SPECIES, desc: '物种（决定 4 分算不算理想）' },
      },
      run: (a) => {
        const sp = a.species === 'cat' ? 'cat' : 'dog'
        return {
          species: sp,
          /* 物种化后的逐分表：名称与分组都已按该物种校正，展示与判定都用这份 */
          rows: api.bcsChartPayload(sp).rows,
          groups: api.BCS_GROUPS,
          viewHint: api.BCS_VIEW_HINT,
          selfTest: api.BCS_SELFTEST,
          /* ⚠ 原始引擎表是犬口径（4 分归 ideal）。保留仅为兼容旧调用方，**不要**拿它判物种。 */
          scale: api.BCS_SCALE,
        }
      },
    },

    'ideal-weight': {
      summary: '由当前体重与体况评分估算理想体重',
      params: {
        currentKg: { type: 'number', required: true, min: 0.2, max: 200, desc: '当前体重 kg' },
        score: { type: 'number', required: true, min: 1, max: 9, integer: true, desc: '体况评分' },
      },
      run: (a) => ({ currentKg: a.currentKg, score: a.score, idealKg: api.idealWeightFromBcs(a.currentKg, a.score) }),
    },

    'life-stage': {
      summary: '判定生命阶段（幼/成/老）与餐次建议',
      params: {
        profile: { type: 'object', required: true, desc: '个体档案（species/weightKg/ageMonths 或 ageText）' },
      },
      run: (a) => {
        const stage = api.lifeStage(a.profile)
        return {
          stage,
          mealsPerDay: api.mealsPerDay(stage, a.profile.ageMonths ?? null, a.profile.species === 'dog' ? 'dog' : 'cat'),
          growthEndMonths: api.GROWTH_END_MONTHS,
          seniorFromMonths: api.SENIOR_FROM_MONTHS,
        }
      },
    },

    transition: {
      summary: '换粮过渡计划（默认 7 天）',
      params: {
        days: { type: 'number', min: 1, max: 30, default: 7, desc: '过渡天数' },
        grams: { type: 'number', min: 0, desc: '每日总克数（给了才换算成具体克数）' },
      },
      run: (a) => ({ plan: api.transitionPlan(a.days, a.grams) }),
    },

    monitoring: {
      summary: '监测计划（按生命阶段与体况策略）',
      params: {
        score: { type: 'number', required: true, min: 1, max: 9, integer: true, desc: '体况评分' },
        species: { type: 'string', enum: SPECIES, default: api.DEFAULT_SPECIES, desc: '物种' },
        stage: { type: 'string', desc: '生命阶段（缺省由 score 推）' },
      },
      run: (a) => {
        const policy = api.bcsPolicy(a.score, a.species === 'cat' ? 'cat' : 'dog')
        return { plan: api.monitoringPlan(a.stage || 'adult', policy) }
      },
    },

    'vet-signals': {
      summary: '查需要就医的信号清单',
      params: {},
      run: () => ({ signals: api.vetSignals(), waterGuide: api.WATER_GUIDE, storageDry: api.storageTips('dry') }),
    },
  }
}

/** 门面主流程。返回退出码（不退出进程，便于测试在进程内断言）。 */
export async function main(argv = process.argv.slice(2), io) {
  const out = io || makeIo()
  let api
  try {
    api = await importFromVendor(HERE, PROBE, 'feedingGuide.js')
    // species.js 是全站物种缺省值的唯一真源；门面默认值必须取自它，不能写字面量（否则会与源码漂移）
    const sp = await importFromVendor(HERE, 'species.js', 'species.js')
    // 安全闸（N1 接线 · E2）：喂食计划前先拦禁用物质。只并入 classifyRecipe。
    const tox = await importFromVendor(HERE, PROBE, 'toxicology.js')
    // 多宠组合层（N3-a）：逐宠算量 → 按物料编号归并采购清单。纯组合层，无新公式。
    const mp = await importFromVendor(HERE, PROBE, 'multiPetPlan.js')
    // 分装排期与分装标签（N3-b）：纯函数、零依赖，只吃「克/日」一个上游数。
    const pl = await importFromVendor(HERE, PROBE, 'portionLabel.js')
    api = {
      ...api,
      DEFAULT_SPECIES: sp.DEFAULT_SPECIES,
      SPECIES_IDS: sp.SPECIES_IDS,
      classifyRecipe: tox.classifyRecipe,
      computeMultiPetPlan: mp.computeMultiPetPlan,
      computePortionLabels: pl.computePortionLabels,
      renderPortionLabelText: pl.renderPortionLabelText,
      FORM_TIPS: pl.FORM_TIPS,
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
