/**
 * 配方 → 合规标签 / 营养保证值 正向生成（缺口 3）。
 *
 * ## 为什么要有它
 * 系统此前只有**解析方向**：OCR 读标签 → 拆出营养值（`ocr.js` / `analyzeLabel`）。
 * 而研发真正每天要交的是**产出方向**：把配方算出来的数值，按法规要求的项目与
 * 顺序**写成一份可提交的标签底稿**。此前这一环全靠人手抄 Excel ——
 * 抄错一位、漏一个项目、配料表排序不合规，都要等审核退回才发现。
 *
 * ## 三条不可逾越的红线（本模块刻意「不做什么」）
 *
 *   1. **绝不硬编码法规限值**。判定用的限值全部来自 `standards.js` 的
 *      `resolveStandard()` —— 那里 `CN-GB` 条款已核对 GB/T 31216-2014 / 31217-2014
 *      原文并带 `cite`，`AAFCO` 未核实的条目带 `verify: true` 并被如实标注。
 *      本模块**只做「配方数值 → 标签文案」的搬运与排版**，一个数字都不自己发明。
 *      → 法规换版时只需改 `standards.js` 一处，标签自动跟随。
 *
 *   2. **绝不把「算不出」写成「达标」**。原料库没有氨基酸字段（赖氨酸/牛磺酸），
 *      覆盖率不足的项也不能给合规结论。这类项一律进 `nodata` 段并写明原因，
 *      **不冒充未达标、也不冒充达标**。
 *
 *   3. **配料表排序是「按重量递减」的法规要求，但排序依据必须可追溯**。
 *      本模块按配方占比降序排；等价重量（占比相同）时**保持用户录入顺序**
 *      （稳定排序），因为法规对并列项无规定，而擅自按名称排会与用户投料单不一致。
 *
 * ## 与 standards.js 的关系
 *   standards.js  →  「该判什么、限值多少、出自哪条」（**判定层**）
 *   labeling.js   →  「把判定结果与配方数值排成标签稿」（**呈现层**，本模块）
 *   两者不重叠：本模块不新增任何判定逻辑，`compliance` 段直接取
 *   `evaluateRecipe()` 的 `status` 字段。
 *
 * ## 用法
 *   const draft = buildLabelDraft({ recipe, req, meta })
 *   draft.guaranteed   // 营养保证值表（已按「法规要求的项目」过滤与排序）
 *   draft.ingredients  // 配料表（已按占比降序）
 *   draft.compliance   // 逐项合规结论（来自 evaluateRecipe）
 *   draft.disclaimers  // 必须随稿一起给使用者的声明
 */

import {
  evaluateRecipe, NUTRIENT_FIELDS, FIELD_LABEL,
} from './nutrition.js'
// ⚠ stageOf / classifyMoisture / getMarketMode / NUTRIENT_META 都住在 standards.js，
//   不在 nutrition.js —— 别凭印象 import（本模块初稿就写错过一次）。
import {
  classifyMoisture, getMarketMode, NUTRIENT_META, stageOf,
} from './standards.js'

/* ---------------- 常量 ---------------- */

/** 标签稿格式版本（改排版/改字段口径时必须同步递增，便于回溯历史稿件） */
export const LABEL_FORMAT_VERSION = 1

/**
 * 标签稿**必须**随附的声明。这些不是客套话，每一条都对应一个真实的合规风险：
 *   · 检测值 vs 计算值 —— 配方计算是「理论值」，标签上的保证值是「检测判定值」，
 *     两者口径不同，直接照抄计算值送检会出现「标示值低于检测值」的偏差问题。
 *   · 法规现行性 —— 限值可能已换版，本稿依据的是系统内已核条款。
 *   · 配料表名称 —— GB 要求标示原料的**具体名称**，配方里的内部简称/商品名不可直接上标签。
 *   · 排序依据 —— 法规按投料重量递减，系统用的是「配方用量」，若实际投料有损耗
 *     或复水/脱水工序，顺序可能需按工序后重量重排。
 */
export const LABEL_DISCLAIMERS = [
  '本稿数值为「配方理论计算值」（依据原料库营养数据加权），与送检检测值口径不同；标示值须以第三方检测结果为准，并留出法规允许的允许偏差（≤20% 规则等请按现行法规执行）。',
  '限值依据系统内「已核对条款」（中国 GB/T 31216-2014 犬粮、GB/T 31217-2014 猫粮；AAFCO 条目带「待核对现行版本」标记）。提交前请复核法规现行版本与最新适用条款。',
  '配料表原料名称须使用法规许可的「标准名称」；本稿按原料库名称生成，若为内部简称/商品名（如「宠贝冠鸡肉粉（72型）」），须替换为标签可用名称。',
  '配料表顺序按「配方用量占比递减」生成；若实际工序存在投料损耗、复水或脱水，应按工序后实际重量重新确认顺序。',
  '本稿为研发内部底稿，「不构成合规认证」；正式标签须经法规/品控审核。',
]

/* ---------------- 干物质基础换算（本模块自用，与 nutrition.js 口径一致） ---------------- */

/**
 * 原样基础值 → 干物质基础值。
 * ⚠ 与 `nutrition.js` 的 `toDryMatter()` **同公式**，此处不 import 是为了避免
 *   循环依赖（nutrition.js 已 import standards.js，本模块也 import standards.js）；
 *    两者必须保持一致 —— 若 nutrition.js 的口径改了，这里要同步。
 *    由 `scripts/labeling-test.mjs` 用同一组数值交叉比对两处结果来锁死。
 *
 * ⚠ `key === 'moisture'` 时**恒返回 0**：干基定义为扣除全部水分，水分在干基上是
 *   **定义值 0**，不是「算出来的 0」。这一条最初漏了（只按比例折算），
 *   被测试的逐字段交叉比对抓出来 —— 折叠水分会得出非 0 的假值。
 * @param {string} key        字段名（'moisture' 特判）
 * @param {number} dmPercent  干物质含量（100 − 水分）
 */
export function toDmValue(asFedValue, dmPercent, key = '') {
  if (key === 'moisture') return 0
  const v = Number(asFedValue)
  if (!Number.isFinite(v)) return null
  if (!(dmPercent > 0.01)) return null
  return (v / dmPercent) * 100
}

/* ---------------- 营养保证值表 ---------------- */

/**
 * 生成营养保证值表。
 *
 * ## 项目从哪来
 * **不自行挑选项目**，而是取 `standards.js` 解析出的合并标准项目集（`std.items`）——
 * 即「本市场模式下法规要求标注的全部项目」。这样各国的必标项差异由标准层决定。
 *
 * ## 每项包含
 *   label/unit    —— 项目名与单位（GB 为 %DM 干物质基础）
 *   value         —— 配方计算值（干物质基础，保留 2 位）
 *   target        —— 法规限值文案（如 "≥25.0"）
 *   status        —— 来自 evaluateRecipe：ok / fail / low / nodata
 *   printable     —— 是否可印上标签（只有 status === 'ok' 或 'fail' 才有数）
 *   note          —— 取不到值时说明原因（不是空字符串，必须写明）
 *
 * @param {object} recipe computeRecipe() 的返回
 * @param {object} req    computeRequirements() 的返回（含 species/stage/status/marketId）
 * @returns {{ rows:Array, printableCount:number, blockedCount:number, standard:object }}
 */
export function buildGuaranteedTable(recipe, req) {
  const ev = evaluateRecipe(recipe, req)
  if (!ev) return { rows: [], printableCount: 0, blockedCount: 0, standard: null }

  const rows = ev.rows.map((r) => {
    // value 已是干物质基础（evaluateRecipe 内部取的是 recipe.dm）。
    // GB 标签标示的是干物质基础值，故直接沿用，不做二次换算（避免重复换算放大误差）。
    const fine = r.value == null ? null : Math.round(r.value * 100) / 100
    const printable = fine != null && (r.status === 'ok' || r.status === 'fail' || r.status === 'low')
    return {
      key: r.key,
      nutrient: r.nutrient,
      label: r.label,
      unit: r.unit,
      value: fine,
      valueText: fine == null ? '—' : fine.toFixed(2),
      target: r.target,
      status: r.status,
      ok: r.ok,
      printable,
      // 不可印时必须写明原因 —— 空 note 会让使用者以为「只是没排到」
      note: printable
        ? (r.status === 'fail' ? '低于/高于法规限值，标示前须调整配方' : (r.status === 'low' ? r.note : ''))
        : (r.note || '取不到数值'),
      cites: r.cites || [],
      sources: r.sources || {},
      coverage: r.coverage,
    }
  })

  return {
    rows,
    printableCount: rows.filter((r) => r.printable && r.status !== 'fail').length,
    blockedCount: rows.filter((r) => !r.printable || r.status === 'fail').length,
    standard: ev.standard,
    evaluated: ev,
  }
}

/* ---------------- 配料表 ---------------- */

/**
 * 生成配料表（按占比降序）。
 *
 * 法规要求配料按投料重量递减排列。本函数按配方占比降序；
 * 占比相同者**保持录入顺序**（`Array.prototype.sort` 在 V8 上稳定，
 * 但此处仍显式带上原始下标做次关键字，避免换引擎后行为漂移）。
 *
 * ⚠ 原料名净化：原料库里的名称可能带内部标记（如尾部「（检样1）」这类）。
 *   本模块**不自动删括号** —— 括号内容也是身份的一部分（见 listSync.js 注释），
 *   擅自删会改错名称。改为：把可能不适合上标签的名称**显式标出来**供人工确认。
 *
 * @param {object} recipe computeRecipe() 的返回
 * @returns {{ items:Array, totalShare:number, needsReview:Array }}
 */
export function buildIngredientList(recipe) {
  if (!recipe?.ok) return { items: [], totalShare: 0, needsReview: [] }

  const rows = recipe.lines.map((l, i) => ({
    index: i,
    code: l.code || '',
    name: l.name,
    share: l.share,
    shareText: `${l.share.toFixed(2)}%`,
    weight: l.weight,
    // 需人工确认的名称：含括号内容（供应商/规格/检样标记）或全角字符混排
    needsReview: /[（(]/.test(l.name),
  }))

  const sorted = [...rows].sort((a, b) => (b.share - a.share) || (a.index - b.index))

  return {
    items: sorted,
    totalShare: rows.reduce((s, x) => s + x.share, 0),
    needsReview: sorted.filter((x) => x.needsReview),
  }
}

/* ---------------- 标签稿总装 ---------------- */

/**
 * 组装完整的标签底稿。
 *
 * @param {object} p
 *   recipe   computeRecipe() 的返回（必需）
 *   req      computeRequirements() 的返回（必需，决定判定标准）
 *   meta     产品元信息（可选）：{ productName, brand, netWeight, batchNo, manufacturer, date }
 * @returns {object} 标签稿（纯数据，可 JSON 序列化 / 渲染 / 导出）
 */
export function buildLabelDraft({ recipe, req, meta = {} } = {}) {
  if (!recipe?.ok || !req) {
    return {
      ok: false,
      reason: !recipe?.ok ? '配方未计算成功（computeRecipe 返回空）' : '缺少营养需求对象（req）',
      formatVersion: LABEL_FORMAT_VERSION,
    }
  }

  const guaranteed = buildGuaranteedTable(recipe, req)
  const ingredients = buildIngredientList(recipe)
  const moisturePercent = 100 - recipe.dmPercent
  const moistureClass = classifyMoisture(moisturePercent)
  const market = getMarketMode(req.marketId)
  const species = req.species === 'dog' ? 'dog' : 'cat'
  const stage = req.stage || stageOf(req.status)

  const ev = guaranteed.evaluated
  const blocked = guaranteed.rows.filter((r) => r.status === 'fail')
  const nodata = guaranteed.rows.filter((r) => r.status === 'nodata')

  /* 风险提示：把「不能直接印」的原因逐条列出。这些是使用者最容易漏看的。 */
  const risks = []
  if (blocked.length) {
    risks.push(`${blocked.length} 项超出法规限值（${blocked.map((r) => r.label).join('、')}），须先调整配方`)
  }
  if (nodata.length) {
    risks.push(`${nodata.length} 项无数据无法标示（${nodata.map((r) => r.label).join('、')}）—— 需补检测数据后方可出标签`)
  }
  if (ingredients.needsReview.length) {
    risks.push(`${ingredients.needsReview.length} 个原料名称需替换为标签可用名称：${ingredients.needsReview.map((x) => x.name).join('、')}`)
  }
  if (!moistureClass.available) {
    risks.push('水分形态未能判定（水分数据缺失），牛磺酸等随水分形态变化的档位可能取错，请先补水分数据')
  }
  const lowCov = guaranteed.rows.filter((r) => r.status === 'low')
  if (lowCov.length) {
    risks.push(`${lowCov.length} 项原料数据覆盖率偏低（${lowCov.map((r) => `${r.label} ${r.coverage}%`).join('、')}），数值仅作参考`)
  }

  return {
    ok: true,
    formatVersion: LABEL_FORMAT_VERSION,
    generatedAt: new Date().toISOString(),

    /* 产品信息（用户填，本模块不编造） */
    product: {
      productName: meta.productName || '',
      brand: meta.brand || '',
      netWeight: meta.netWeight || '',
      batchNo: meta.batchNo || '',
      manufacturer: meta.manufacturer || '',
      date: meta.date || '',
    },

    /* 判定依据（可追溯） */
    basis: {
      marketId: market.id,
      marketLabel: market.label,
      marketDesc: market.desc,
      species,
      speciesLabel: species === 'dog' ? '犬' : '猫',
      stage,
      stageLabel: stage === 'growth' ? '生长期' : stage === 'reproduction' ? '繁殖期' : '成年期',
      moistureClass: moistureClass.id,
      moistureClassLabel: moistureClass.label,
      moisturePercent: Math.round(moisturePercent * 100) / 100,
      dmPercent: Math.round(recipe.dmPercent * 100) / 100,
      standardSource: ev?.sourceLabel || '',
      setIds: guaranteed.standard?.setIds || [],
      setLabels: guaranteed.standard?.setLabels || [],
    },

    /* 营养保证值 */
    guaranteed: {
      rows: guaranteed.rows,
      printableCount: guaranteed.printableCount,
      blockedCount: guaranteed.blockedCount,
    },

    /* 配料表 */
    ingredients: {
      items: ingredients.items,
      totalShare: Math.round(ingredients.totalShare * 100) / 100,
      needsReview: ingredients.needsReview,
    },

    /* 合规结论（直接取 evaluateRecipe 的口径，不另立一套） */
    compliance: {
      allPass: !!ev?.allPass,
      judged: ev?.judged ?? 0,
      totalRows: ev?.totalRows ?? 0,
      noDataCount: ev?.noDataCount ?? 0,
      lowCount: ev?.lowCount ?? 0,
      failCount: blocked.length,
    },

    /* 其他标签常见要素（能量按原样基础，与商品标签口径一致） */
    energy: {
      meModifiedAsFed: recipe.energy?.meModified ?? null,
      meAtwaterAsFed: recipe.energy?.meAtwater ?? null,
      unit: 'kcal/kg',
    },

    /* 面积/成本等由配方直接带来的数（供研发内部核对，不属于标签内容） */
    internal: {
      totalWeight: recipe.totalWeight,
      costPerKg: recipe.cost?.perKg ?? null,
      lineCount: recipe.lines?.length ?? 0,
    },

    risks,
    disclaimers: LABEL_DISCLAIMERS,
  }
}

/* ---------------- 纯文本渲染（便于复制进 Word / 邮件 / 审核单） ---------------- */

/**
 * 把标签稿渲染成可直接粘贴的纯文本。
 * ⚠ 不可标示的项**不出现在正文表格里**，但会在末尾「未能标示」段落列明 ——
 *   若悄悄省略，使用者会误以为「法规只要求这几项」。
 */
export function renderLabelText(draft) {
  if (!draft?.ok) return `标签稿生成失败：${draft?.reason || '未知原因'}`
  const L = []
  const p = draft.product
  const b = draft.basis

  L.push('════════ 宠物食品标签底稿（研发内部）════════')
  L.push(`格式版本 v${draft.formatVersion}    生成时间：${new Date(draft.generatedAt).toLocaleString('zh-CN', { hour12: false })}`)
  L.push('')
  L.push('【产品信息】')
  L.push(`  产品名称：${p.productName || '（待填）'}`)
  if (p.brand) L.push(`  品牌：${p.brand}`)
  if (p.netWeight) L.push(`  净含量：${p.netWeight}`)
  if (p.batchNo) L.push(`  批号：${p.batchNo}`)
  if (p.manufacturer) L.push(`  生产商：${p.manufacturer}`)
  if (p.date) L.push(`  日期：${p.date}`)
  L.push('')
  L.push('【判定依据】')
  L.push(`  市场模式：${b.marketLabel}（${b.marketDesc}）`)
  L.push(`  适用对象：${b.speciesLabel} · ${b.stageLabel}`)
  L.push(`  水分形态：${b.moistureClassLabel}（水分 ${b.moisturePercent}%，干物质 ${b.dmPercent}%）`)
  L.push(`  标准来源：${b.standardSource}`)
  L.push('')
  L.push('【配料表】（按占比递减）')
  draft.ingredients.items.forEach((it, i) => {
    L.push(`  ${String(i + 1).padStart(2, ' ')}. ${it.name}${it.code ? `（${it.code}）` : ''}  ${it.shareText}${it.needsReview ? '  ⚠名称待确认' : ''}`)
  })
  L.push(`  合计 ${draft.ingredients.totalShare}%`)
  L.push('')
  L.push('【营养保证值】（干物质基础）')
  const shown = draft.guaranteed.rows.filter((r) => r.printable)
  if (shown.length) {
    L.push('  项目                     计算值        法规限值')
    L.push('  ' + '─'.repeat(46))
    for (const r of shown) {
      const mark = r.status === 'fail' ? ' ✗超限' : (r.status === 'low' ? ' △数据不足' : '')
      L.push(`  ${r.label.padEnd(22, '　')} ${String(r.valueText).padStart(8)}  ${String(r.target).padEnd(12)}${mark}`)
    }
  } else {
    L.push('  （无任何项可取到数值）')
  }
  L.push('')
  const notShown = draft.guaranteed.rows.filter((r) => !r.printable)
  if (notShown.length) {
    L.push('【未能标示的法规必标项】')
    for (const r of notShown) L.push(`  · ${r.label}（${r.target}）：${r.note}`)
    L.push('')
  }
  if (draft.energy.meModifiedAsFed != null) {
    L.push(`【代谢能】${draft.energy.meModifiedAsFed} ${draft.energy.unit}（原样基础，FEDIAF 改良 Atwater）`)
    L.push('')
  }
  if (draft.risks.length) {
    L.push('【⚠ 提交前必须处理】')
    draft.risks.forEach((r) => L.push(`  · ${r}`))
    L.push('')
  }
  L.push('【声明】')
  draft.disclaimers.forEach((d, i) => L.push(`  ${i + 1}. ${d}`))
  L.push('')
  L.push('════════════════════════════════════════════')
  return L.join('\n')
}

/** 标签稿文件名（带产品名与日期，避免多次导出互相覆盖） */
export function labelFileName(draft, d = new Date()) {
  const pad = (n) => String(n).padStart(2, '0')
  const stamp = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}_${pad(d.getHours())}${pad(d.getMinutes())}`
  const name = (draft?.product?.productName || '未命名').replace(/[\\/:*?"<>|]/g, '_').slice(0, 40)
  return `标签底稿_${name}_${stamp}.txt`
}

/** 触发浏览器下载（纯文本，UTF-8 BOM 保证 Excel/记事本打开不乱码） */
export function downloadLabelText(text, filename) {
  const blob = new Blob(['\uFEFF' + text], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/* ---------------- 供界面/测试用的元信息透出 ---------------- */

/**
 * 本次可打印项 vs 法规必标项 的对照，用于界面直接显示「哪些还缺」。
 * @returns {{ required:number, printable:number, missing:Array<{label,target,note}> }}
 */
export function labelCoverage(draft) {
  if (!draft?.ok) return { required: 0, printable: 0, missing: [] }
  const rows = draft.guaranteed.rows
  return {
    required: rows.length,
    printable: rows.filter((r) => r.printable).length,
    missing: rows.filter((r) => !r.printable).map((r) => ({ label: r.label, target: r.target, note: r.note })),
  }
}

/** 透出底层字段清单，便于 UI 说明「这些是标签要标的项目」 */
export { NUTRIENT_FIELDS, FIELD_LABEL, NUTRIENT_META }
