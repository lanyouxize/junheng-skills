#!/usr/bin/env node
/**
 * intel-compliance —— 宣称合规待核对清单的命令行门面。
 *
 * 门面里不含任何词表、正则、条款号或降噪规则：全部来自
 * `src/lib/compliance.js`（+ `schema.js` 的证据分级 + `evidence.js`）。
 *
 * ## 本门面唯一「必须自己动手」的地方：`rules` 的 RegExp 预序列化
 * `output.mjs` 的 `stringifyStrict` 只拦 function / symbol / bigint，**不拦 RegExp** ——
 * 而 `JSON.stringify(/ab/g)` 静默得到 `"{}"`。若把 `patterns` 原样透出，调用方会收到
 * 一堆 `"patterns":[{}]` 且**看不出哪里错了**。所以 `rules` 必须把每条正则取 `.source`
 * 另存为 `patternSources`（字符串数组）。这是本批最容易「静默出错」的一处，刻意显式处理。
 *
 * 退出码：0 成功（含域内负结果）/ 1 内部错误 / 2 用法或输入错误 / 3 前置条件缺失。
 */
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { importFromVendor, isEntrypoint } from './lib/locate.mjs'
import { runCli } from './lib/runner.mjs'
import { emitError, makeIo } from './lib/output.mjs'

export const NAME = 'intel-compliance'
export const VERSION = '1.0.0'
export const SUMMARY = '宣称合规待核对清单：扫描文本中的踩线措辞、给出精确条款号、四态功能声称可声称性判定、措辞档位、规则表'
/** 结果口径：待核对清单 —— 不是合规判定。必须是具名常量。 */
export const BASIS = 'rule-review'
export const PROBE = ['compliance.js', 'schema.js', 'evidence.js']
export const DISCLAIMER = '这是一份待核对清单，不是合规判定。没有命中不代表合规 —— 词表有限，同义表达与新的营销话术一定漏。'
  + '最终依据只能是现行法规与标准原文，请带条款号回到原文核对。'
  + '未传入库内证据时，本次不做证据降档：展示的 severity 是未经降档的基准等级。'

const HERE = path.dirname(fileURLToPath(import.meta.url))

/** 单次审查的文本上限（域定上限，超限报错不截断） */
const TEXT_MAX = 20000
/** 库内证据条数上限（V6） */
const ARTICLES_MAX = 500
/** 元素级错误提示后缀（域内文案留在门面，不进通用校验器） */
const ARTICLE_HINT = '每条可为库内文章对象（如 {id?, title?, analysis?, evidenceLevel?}），字段不穷举'

/** 未传证据时的披露文案（V3：必须显式，不能让人误以为已降档） */
const NO_EVIDENCE_REASON = '未提供库内证据，本次未做证据降档；展示的 severity 是未经降档的基准等级'

/** 由已加载的内核模块构造命令表。导出以便测试检视注册表。 */
export function buildCommands(api) {
  return {
    review: {
      summary: '审查一段文本，输出 findings（含精确条款号）+ 第二十条（五）正向通道',
      params: {
        text: { type: 'string', required: true, desc: '待审文本（标签文案 / 宣传语 / 文章段落）' },
        articles: { type: 'array', maxItems: ARTICLES_MAX, itemOpen: true, itemHint: ARTICLE_HINT, desc: '库内文章，用于给每条声称找证据等级（可选）' },
        maxFindings: { type: 'number', integer: true, min: 1, max: 500, default: 200, desc: 'findings 条数上限' },
      },
      check: (a) => {
        const text = String(a.text)
        if (text.trim().length < 1) return 'text 只含空白字符，没有可审查的内容 —— 请给一段真实文案'
        if (text.length > TEXT_MAX) {
          return `text 超出单次审查上限 ${TEXT_MAX} 字符（收到 ${text.length}）—— 请按文档/段落切分后分批调用`
        }
        return null
      },
      run: (a) => {
        const hasArticles = Array.isArray(a.articles) && a.articles.length > 0
        const res = api.reviewClaims(a.text, { articles: a.articles, maxFindings: a.maxFindings })
        const matched = res.findings.filter((f) => f.evidence).length
        return {
          ...res,
          // 注意：证据降档**必须显式披露**（V3）：不传 articles 时内核不会做证据降档，
          //   而「没做」与「做了但没匹配上」在下游长得一样 —— 不说就等于骗人。
          evidenceDowngrade: {
            applied: hasArticles,
            matched,
            reason: hasArticles
              ? `已提供 ${a.articles.length} 条库内证据；其中 ${matched} 条 finding 匹配到 L1/L2 证据并下调一档`
              : NO_EVIDENCE_REASON,
          },
          // findings 触到上限时**显式**说明被截断（显式的截断不是静默的截断）
          truncated: res.findings.length >= a.maxFindings,
        }
      },
    },

    claim: {
      summary: '判定一条功能声称诉求的可声称性（四态：red-line / prevention-allowed / check-appendix / no-input）',
      params: {
        appeal: { type: 'string', required: true, desc: '要判断的诉求，如「排毛」「预防尿结石」' },
        ingredient: { type: 'string', desc: '要声称的原料（可选，只用于回显）' },
        ratio: { type: 'number', min: 0, max: 100, desc: '该原料在产品总重中的占比 %（不给则不给措辞档位）' },
      },
      run: (a) => api.assessFunctionClaim({ appeal: a.appeal, ingredient: a.ingredient, ratio: a.ratio }),
    },

    rules: {
      summary: '输出规则表（严重度 / 条款号 / 降噪特征 / 正向通道参照数据）',
      params: {},
      run: () => ({
        rules: api.COMPLIANCE_RULES.map((r) => ({
          code: r.code,
          label: r.label,
          severity: r.severity,
          clause: r.clause || '',
          docRef: r.docRef || '',
          reason: r.reason || '',
          // 注意：RegExp 预序列化为 `.source`（字符串）。直接输出 RegExp 实例会被
          //   stringifyStrict 静默变成 `{}` —— 调用方看不出错，只看到一堆空对象。
          patternSources: (r.patterns || []).map((p) => p.source),
          hasGuard: typeof r.guard === 'function',
          ignoreDampeners: r.ignoreDampeners || [],
        })),
        severity: api.COMPLIANCE_SEVERITY,
        dampeners: api.CONTEXT_DAMPENER_LABELS,
        functionClaimChannel: api.FUNCTION_CLAIM_CHANNEL,
      }),
    },

    wording: {
      summary: '由占比给出合法措辞档位（不给占比就不给档位，不猜）',
      params: {
        ratio: { type: 'number', required: true, min: 0, max: 100, desc: '该原料在产品总重中的占比 %' },
      },
      run: (a) => {
        const w = api.wordingFor(a.ratio)
        if (w) return w
        return {
          ratio: a.ratio,
          tier: null,
          word: '',
          clause: '',
          note: `占比 ${a.ratio}% 未落入任何措辞档位 —— 措辞档位由占比决定（26% / 14% / 4% / 添加××），`
            + '给一个正的 ratio 才能落到具体写法；占比为 0 时不猜写法',
        }
      },
    },
  }
}

/** 门面主流程。返回退出码（不退出进程，便于测试在进程内断言）。 */
export async function main(argv = process.argv.slice(2), io) {
  const out = io || makeIo()
  let api
  try {
    api = await importFromVendor(HERE, PROBE, 'compliance.js')
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
