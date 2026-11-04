---
name: intel-compliance
description: 文案宣称合规检查。扫描文案中的绝对化用语、疗效宣称、安全性断言、成分与特性声称等 20 类踩线措辞，逐条给出条款号、风险等级与抑制依据，并判定功能声称的可声称性四态。当用户问这句能不能这么写、有没有踩线时使用。
description_en: Marketing-claim compliance review checklist — scan copy for risky wording across 20 rule categories with exact clause numbers and severity, plus four-state assessability of a functional claim and legal wording tiers by ingredient ratio.
---

# 宣称合规待核对清单（intel-compliance）

## 目的与边界

**做什么**：把一句话里**可能踩线**的措辞挑出来，标明风险等级、**该去核对的条款**与「为什么值得看一眼」，让人带着问题回去核对现行标准原文。

**不做什么**：

- **不出「合规 / 不合规」的结论** —— 判定权在现行法规与标准原文，不在本工具。
- **不用命中数当合规证明** —— 词表有限，同义表达与新的营销话术一定漏。
- **不把规则表当判例库** —— 每条给出的是「这句话值得看一眼的程度」，不是「违反了哪一条」。

## 诚实性红线

1. **`basis` 恒为 `rule-review`** —— 这是一份**待核对清单**，不是合规判定。
2. **没有命中不代表合规**。识别是**启发式**的（按词表匹配），识别不到不代表没有该类声称。
3. **最终依据只能是现行法规与标准原文**，请带 `clause` 回到原文核对。
4. **未传库内证据时不做证据降档，且必须显式披露** —— `evidenceDowngrade.applied:false` 表示本次展示的 `severity` 是**未经降档的基准等级**（可能系统性偏高）。
5. **「允许」侧与「风险」侧必须分开读** —— `functionClaim` 给的是「条款号 + 可用字样 + 要备的材料」，不是判定；它与 `findings` 并列，不要混为一谈。
6. **风险等级可能已被下调** —— 看 `severity` 之前先看 `baseSeverity` 与 `suppressedBy`（语境抑制 / 证据降档的缘由）。

## 用法

在技能根目录下执行：

```
node scripts/cli.mjs <命令> '<JSON 参数>'
node scripts/cli.mjs <命令> --stdin          # 参数从标准输入读
node scripts/cli.mjs --help
node scripts/cli.mjs <命令> --help
```

## 命令一览

| 命令 | 用途 |
|------|------|
| `review` | 审查一段文本，输出 findings（含精确条款号）+ 第二十条（五）正向通道 |
| `claim` | 判定一条功能声称诉求的可声称性（四态） |
| `rules` | 输出规则表（严重度 / 条款号 / 降噪特征 / 正向通道参照数据） |
| `wording` | 由占比给出合法措辞档位 |
| `describe` | 输出机器可读的接口说明 |

## 参数

`review`

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `text` | string | 是 | — | 待审文本，长度 1..20000 |
| `articles` | array | 否 | — | 库内文章（≤500 条），字段不可穷举，**原样透传** |
| `maxFindings` | number | 否 | `200` | findings 条数上限，1..500 |

`claim`

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `appeal` | string | 是 | 要判断的诉求，如「排毛」「预防尿结石」 |
| `ingredient` | string | 否 | 要声称的原料（只用于回显） |
| `ratio` | number | 否 | 该原料在产品总重中的占比 %（0..100）；不给则不给措辞档位 |

`rules`：无参数。

`wording`

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `ratio` | number | 是 | 该原料在产品总重中的占比 %（0..100） |

## 输出字段

| 命令 | `data` 关键字段 |
|------|----------------|
| `review` | `findings[]`（含 `code/label/clause/severity/baseSeverity/term/sentence/reason/docRef/suppressedBy/evidence/basis`）、`summary`、`docRefs[]`、`clauses[]`、`functionClaim`、`evidenceDowngrade:{applied,matched,reason}`、`truncated`、`note` |
| `claim` | `verdict`（`red-line` / `prevention-allowed` / `check-appendix` / `no-input`）、`diseaseHit`、`allowsPreventWord`、`wording`、`wordingNote`、`materials[]`、`grants[]`、`appendixNote` |
| `rules` | `rules[]`（含 `patternSources[]`）、`severity`、`dampeners[]`、`functionClaimChannel` |
| `wording` | `tier` / `word` / `clause` / `note`（未落档时 `tier:null`） |

## 退出码

| 退出码 | 含义 |
|--------|------|
| 0 | 成功。注意：**「没命中」「未落档」也是 0** —— 请看 `data.note` 与各 `note` 字段 |
| 1 | 内部错误（未预期异常） |
| 2 | 用法或输入错误，命令未执行（未知参数名会附拼写建议；超上限会给出上限值） |
| 3 | 前置条件缺失（源码镜像未同步） |

**域内负结果不是错误**：`findings` 为空、未传证据导致未降档、`wording` 未落档 —— 一律 `ok:true` + 退出码 0，并在 `data` 里说清原因。

## 示例

```bash
# 审查一段踩线密集的文案：会给出多条带条款号的 findings
node scripts/cli.mjs review '{"text":"本品能治疗猫肾衰，完全无害，全国第一"}'

# 未传 articles：evidenceDowngrade.applied=false，severity 是未经降档的基准等级
node scripts/cli.mjs review '{"text":"本品有助于美毛"}'

# 传入库内证据：本次做了证据降档（matched 给出匹配到几条）
node scripts/cli.mjs review '{"text":"本品有助于美毛","articles":[{"id":"a1","title":"某研究","analysis":{"evidenceLevel":"L2","tldr":"有助于美毛"}}]}'

# 功能声称可声称性四态
node scripts/cli.mjs claim '{"appeal":"预防毛球产生","ingredient":"菊粉","ratio":5}'
node scripts/cli.mjs claim '{"appeal":"治疗猫肾衰"}'

# 规则表（含精确条款号与降噪特征）
node scripts/cli.mjs rules

# 由占比给出措辞档位
node scripts/cli.mjs wording '{"ratio":26}'

# 管道写法
echo '{"text":"国家级品质"}' | node scripts/cli.mjs review --stdin
```

## 维护

- 本技能目录下的 `scripts/vendor/{compliance.js,schema.js,evidence.js}` 是 `src/lib/` 对应文件的
  **只读镜像**（逐字节复制）。**禁止**直接改镜像 —— 改逻辑一律改源文件再重新同步；
  否则 `--check` 会报 `MIRROR_TAMPERED`。
- **改了 `src/lib/**`（含 `compliance.js` / `schema.js` / `evidence.js`）就必须跑 `npm run skills:check`**，
  确认镜像与源一致；不一致时跑 `npm run skills:sync` 重新同步。该脚本**只读**，可随时运行。
- `scripts/cli.mjs` 由 `cli/compliance.mjs` 生成；`SKILL.md` 由 `cli/skills/intel-compliance/SKILL.md` 生成。
  改逻辑改源文件，不要改技能目录里的副本。
- 注意：**`rules` 必须输出 `patternSources`（`.source` 字符串），不得直接输出 `patterns`** ——
  `JSON.stringify(/ab/g)` 静默得到 `"{}"`，透传 RegExp 会让调用方收到一堆空对象却看不出错。
- 注意：**法定门槛 26% / 14% / 4% 在内核有两份独立副本**（`reference-values.js` 与 `compliance.js`）。
  本技能**不改内核**，一致性由守卫断言（A16）看住；内核将来只改一处时该断言会变红。
- 新增/删除命令后，`SKILL.md` 的命令表必须与 `describe` 返回的命令集**双向相等**。

## 拒答与替代路径

> 本节是**可机检**的边界契约（规范与判据见 `docs/contracts/boundary-contract.md`）。
> 命中某一类时，按该类「话术」回复并给出「替代」路径；标「不适用」的类必须写明本技能层面的理由。

### R1 非犬猫物种
- **触发**：为犬猫以外的物种审查措辞。
- **话术**：本技能的规则表按犬猫食品标签与声称组织，对其它物种不适用。
- **替代**：请改用该物种适用的法规；本技能给出的条款号仅对已收录的犬猫法规有效。

### R2 医疗诊断
- **触发**：要求给出「这句表述是否违规」的最终结论。
- **话术**：本技能只标风险等级与待核对条款，不出合规结论。
- **替代**：请带条款号回现行标准原文核对；`claim` 的可声称性四态可先作参照。

### R3 超出已收录法规体系
- **触发**：审查对象不在已收录的法规体系内。
- **话术**：该体系未收录，我给不出它的条款号，也不能替你判断。
- **替代**：可先按已收录体系出风险提示；待该体系补录后再核。

### R4 数据缺口（`nodata`）
- **触发**：措辞里没有可供定位的占比或特征。
- **话术**：缺占比时我给不出措辞档位，也不会用命中数当合规证明。
- **替代**：请补充该成分的占比；本技能会如实报出未能定位的项，不省略。
