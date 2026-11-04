#!/usr/bin/env node
/**
 * intel-evidence —— 证据颗粒度抽取的命令行门面（六字段 + 未识别清单 + 展示排序）。
 *
 * 门面里不含任何正则、阈值或档位：全部来自 `src/lib/evidence.js`。
 * 这里只做三件事：命令注册表（命令名 / 参数 spec / check() / run()）、常量声明、
 * 以及被直接执行时把 main() 的退出码写进 process.exitCode。
 *
 * 调用形态（详见 `--help`）：
 *   node cli/evidence.mjs meta  '{"text":"32只猫的梯度剂量对照试验，结果显示吐毛减少"}'
 *   node cli/evidence.mjs gaps  '{"meta":{"species":"宠物"}}'
 *
 * 退出码：0 成功（含域内负结果）/ 1 内部错误 / 2 用法或输入错误 / 3 前置条件缺失。
 * 注意：用 process.exitCode 而非 process.exit：避免管道下截断 stdout。
 */
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { importFromVendor, isEntrypoint } from './lib/locate.mjs'
import { runCli } from './lib/runner.mjs'
import { emitError, makeIo } from './lib/output.mjs'

export const NAME = 'intel-evidence'
export const VERSION = '1.0.0'
export const SUMMARY = '证据颗粒度：从原文抽取研究设计/样本量/试验动物/终点类型/亚组/利益相关六字段，并给出未识别清单与展示排序'
/** 结果口径：规则通道抽取 —— 不是对研究质量的评价。必须是具名常量（describe 与信封同源）。 */
export const BASIS = 'rule-channel'
export const PROBE = ['evidence.js']
export const DISCLAIMER = '这六个字段记录的是原文写了什么，不是对研究质量的评价 ——「样本量 32」不等于「结论可靠」。'
  + '留空 = 没识别出来，不是「没有」：界面上不会把空字段藏起来，而是显式标「未识别」。'
  + '终点类型规则通道一律留空 —— 判定它需要领域判断，猜错会把替代终点悄悄升级成临床终点。'
  + '猫与犬不合并成「宠物」：合并后就无法回答「这条结论能不能用在只做猫的配方上」。'

const HERE = path.dirname(fileURLToPath(import.meta.url))

/** 单次抽取的文本上限（域定上限，超限报错不截断） */
const TEXT_MAX = 2000
/** 批量条目的上限（V6：超限报错并给出上限，不做静默截断） */
const ITEMS_MAX = 200

/** 元素级错误提示后缀 —— 让「该写成什么样」跟错误一起给出（域内文案留在门面，不进通用校验器） */
const ITEM_HINT = '每条可为 {id?, text?, meta?}'

/**
 * 把「物种不可控值」显式化（V5）。
 *
 * 内核 `normalizeEvidenceMeta` 已按「未识别」处理（留空）；但它**不留下痕迹** ——
 * 调用方看不出「原文写了 宠物、系统没认」与「原文根本没写物种」的区别。
 * 这里补一层：只对**抽得到、却不在受控词表且不被别名表认**的原始输入做披露。
 * 不猜、不改内核行为，只在结果里把这件事说出来。
 */
function rejectedValuesOf(rawMeta, normalized) {
  const out = []
  const raw = rawMeta && typeof rawMeta === 'object' ? rawMeta : {}
  const rawSpecies = String((raw.species ?? raw.animal) ?? '').trim()
  if (rawSpecies && !normalized.species) {
    out.push({
      field: 'species',
      input: rawSpecies,
      reason: '不在受控值集合内（猫与犬不合并成「宠物」），按未识别处理',
    })
  }
  return out
}

/** 由已加载的内核模块构造命令表。导出以便测试检视注册表。 */
export function buildCommands(api) {
  /** 从原始 meta 对象与内核归一结果拼出统一的抽取结果（meta / 问题清单 / 计数 / 徽章 / 披露） */
  function metaResult(rawMeta) {
    const meta = api.normalizeEvidenceMeta(rawMeta)
    const gaps = api.evidenceMetaGaps(meta)
    return {
      meta,
      gaps,
      mustShowEmpty: api.MUST_SHOW_WHEN_EMPTY.slice(),
      identified: api.EVIDENCE_META_FIELDS.length - gaps.length,
      hasAny: api.hasAnyEvidenceMeta(meta),
      chips: api.evidenceMetaChips(meta),
      rejectedValues: rejectedValuesOf(rawMeta, meta),
    }
  }

  return {
    meta: {
      summary: '从一段原文抽取六字段（研究设计 / 样本量 / 试验动物 / 终点类型 / 亚组限定 / 利益相关）',
      params: {
        text: { type: 'string', required: true, desc: '待抽取的原文（一句或一段）' },
      },
      // 两项域内前置校验都放在 check（→ 用法错误，退出码 2）：
      //   ① 纯空白：必然抽不出任何字段，与其返回一份全空「未识别」，不如直说输入为空；
      //   ② 超上限：报错并给出上限与改法（不静默截断，V6）。
      check: (a) => {
        const text = String(a.text)
        if (text.trim().length < 1) return 'text 只含空白字符，没有可抽取的内容 —— 请给一段真实原文'
        if (text.length > TEXT_MAX) {
          return `text 超出单次抽取上限 ${TEXT_MAX} 字符（收到 ${text.length}）—— 请按句/段切分后分批调用`
        }
        return null
      },
      run: (a) => {
        const text = String(a.text)
        const extracted = api.extractStudyMeta(text)
        return { ...metaResult(extracted), text }
      },
    },

    sort: {
      summary: '按 evidenceSortKey 排序一批条目（识别字段多者先，其次样本量大者先）',
      params: {
        items: { type: 'array', required: true, minItems: 1, maxItems: ITEMS_MAX, itemOpen: true, itemHint: ITEM_HINT, desc: '待排序的条目数组' },
        by: { type: 'string', enum: ['identified', 'sampleSize'], default: 'identified', desc: '排序主键' },
      },
      run: (a) => {
        const decorated = a.items.map((it, i) => {
          const id = it && it.id != null ? String(it.id) : `#${i}`
          // 元素若是 {meta:{...}} 就取 meta，否则把元素本身当 meta（两种写法都接）。
          const rawMeta = it && typeof it.meta === 'object' && it.meta ? it.meta : (it || {})
          const meta = api.normalizeEvidenceMeta(rawMeta)
          return { id, meta, sortKey: api.evidenceSortKey(meta), gaps: api.evidenceMetaGaps(meta) }
        })
        // 排序只回答「先看哪一条」：主键由 `by` 决定，次键一律沿用内核口径，
        // 避免造出第二套排序语义。同分保持原序（不做二次猜测）。
        const sorted = a.by === 'sampleSize'
          ? decorated.slice().sort((x, y) => (y.sortKey.sampleSize - x.sortKey.sampleSize) || (y.sortKey.identified - x.sortKey.identified))
          : decorated.slice().sort((x, y) => (y.sortKey.identified - x.sortKey.identified) || (y.sortKey.sampleSize - x.sortKey.sampleSize))
        return { items: sorted, order: sorted.map((x) => x.id) }
      },
    },

    gaps: {
      summary: '列出未识别字段，并标出「空着也必须说出来」的两个（试验动物 / 终点类型）',
      params: {
        meta: { type: 'object', required: true, open: true, desc: '上游产出的结果对象（字段不可穷举，透传）' },
      },
      run: (a) => {
        const meta = api.normalizeEvidenceMeta(a.meta)
        const gaps = api.evidenceMetaGaps(meta)
        return {
          gaps,
          mustShowEmpty: api.MUST_SHOW_WHEN_EMPTY.slice(),
          identified: api.EVIDENCE_META_FIELDS.length - gaps.length,
          total: api.EVIDENCE_META_FIELDS.length,
          rejectedValues: rejectedValuesOf(a.meta, meta),
          note: api.UNIDENTIFIED_NOTE,
        }
      },
    },

    designs: {
      summary: '输出 8 档设计梯度 + 5 个设计大类 + 2 个终点类型 + 受控物种与各自上限',
      params: {},
      run: () => ({
        designs: api.STUDY_DESIGNS,
        groups: api.STUDY_DESIGN_GROUPS,
        endpointTypes: api.ENDPOINT_TYPES,
        speciesValues: api.SPECIES_VALUES,
        fields: api.EVIDENCE_META_FIELDS,
        limits: { sampleSizeMax: api.SAMPLE_SIZE_MAX, metaTextMax: api.META_TEXT_MAX },
      }),
    },
  }
}

/** 门面主流程。返回退出码（不退出进程，便于测试在进程内断言）。 */
export async function main(argv = process.argv.slice(2), io) {
  const out = io || makeIo()
  let api
  try {
    api = await importFromVendor(HERE, PROBE, 'evidence.js')
  } catch (e) {
    return emitError(out, { name: NAME, kind: 'precondition', message: `无法加载源码模块：${(e && e.message) || e}` })
  }
  return runCli({
    name: NAME,
    version: VERSION,
    summary: SUMMARY,
    basis: BASIS,
    disclaimer: DISCLAIMER,
    commands: buildCommands(api),
    argv,
    io: out,
  })
}

if (isEntrypoint(import.meta.url)) {
  process.exitCode = await main(process.argv.slice(2))
}
