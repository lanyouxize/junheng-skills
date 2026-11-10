# 镜像漂移冲突项 · 全面扫描审核与差异对比（2026-11-07）

> 范围：人工定夺的 13 项（#19–#31）。源真身：SKILL.md→`cli/skills/<name>/`，core vendor→`src/lib/`。

> 列：镜像独有（mirror-only，应回写源） / 源独有（source-only，已在源中）/ 建议补充方式。


## [BOTH_CHANGED] junheng-bcs / SKILL.md

- 源：`C:/Users/Administrator/WorkBuddy/2026-10-09-19-00-38/nutrition-agent-work/cli/skills\junheng-bcs\SKILL.md` (5147B)
- 镜像：`C:/Users/Administrator/.workbuddy/skills\junheng-bcs\SKILL.md` (5024B)
- 镜像独有行数：85 ｜ 源独有行数：85 ｜ 源独有中被镜像包含的行数：59

### 镜像独有（应补充回源）— 预览前 60 行
```
---
name: junheng-bcs
description: 宠物体况评分 BCS 9 分制查询与参考图生成。按物种取逐分判定表，判断某分是否落在理想区（犬 4-5、猫仅 5）或肥胖区（7-9），给出易误判点与体脂率区间，生成侧视加俯视矢量参考图。当用户问猫狗胖不胖、算几分时使用。
description_en: 'Pet body condition score (BCS 9-point scale) lookup and reference figure generation for dogs and cats: per-score criteria (lateral/dorsal/palpation), ideal range and obesity screening zone, species-specific pitfalls, estimated body-fat ranges, and a self-drawn side/top SVG reference figure.'
author: Junheng NutriAgent
version: 1.0.0
---

# 体况评分参考（junheng-bcs）

## 目的与边界

**做什么**：给出「某个分数对应什么外观与触感」的判据原文、是否属于理想区/筛查区、以及该物种的易误判点。

**不做什么**：

- **不做诊断**。BCS 是筛查工具；临床肥胖确诊需兽医结合肌肉状况、体重趋势、饮食史、活动能力与体检。
- **不代替实际触摸**。所有判定都要求以触摸肋骨为准；只看轮廓会被毛量、原始袋、品种骨架误导。
- **不给减重方案**。能给出的是「该不该请兽医评估」以及「猫的减重速度必须比犬更慢」这类边界提示。
- **不使用受版权保护的现成图**。本技能生成的 SVG 是按公开发表判据自绘的原创矢量图（画面与配色均为原创），不是任何机构的原图。

## 诚实性红线

1. **筛查不等于诊断**。7~9 分只是进入临床肥胖筛查区（`inObesityScreeningZone: true`），输出里必须同时给 `caveats`，不得表述成「确诊肥胖」。
2. **体脂率是近似估算**。个体误差约正负 5 个百分点；体脂超过约 45% 时 BCS 区分度明显下降，此时应改用体脂指数（BFI）、体尺测量或 DXA。
3. **犬猫理想区不同**。犬是 4~5 分，**猫只有 5 分** —— 把猫按 4 分长期饲喂等于偏瘦。
4. **非理想分数要建议就医**。任何不在理想区的评分都建议请兽医团队评估一次，不要只凭本表大幅增减喂食量或运动量。
5. **档位标注写区间，不写单点**。参考图的三档分别覆盖 1–3 / 4–5 / 6–9 分，只标单点分数会与实际分数对不上。

## 用法

在技能根目录下执行：

```
node scripts/cli.mjs <命令> '<JSON 参数>'
node scripts/cli.mjs <命令> --stdin
node scripts/cli.mjs --help
node scripts/cli.mjs <命令> --help
```

## 命令一览

| 命令 | 用途 |
|------|------|
| `chart` | 查某物种的完整逐分判定表（9 行 × 侧视/俯视/触摸三列） |
| `row` | 查单一分数的判定行（含理想区 / 筛查区标记） |
| `assess` | 体况评估总装：判定行 + 标记 + 物种差异提示 + 误差与就医声明 |
| `figures` | 列出参考图可用的体型分类与档位（给 `figure-svg` 取值用） |
| `figure-svg` | 生成一张自包含的「侧视 + 俯视」参考图 SVG 字符串 |
| `caveats` | 查全部可靠性边界、物种差异与出处 |
| `describe` | 输出机器可读的接口说明 |

**参数详表、输出字段表、可运行示例** → [详细接口参考](references/interface-reference.md)。

## 失败处理（退出码）

| 退出码 | 含义 |
|--------|------|
| 0 | 成功，结果在 stdout 的 JSON 里 |
| 1 | 内部错误（未预期异常） |
... (截断)
```

### 源独有（已在源，供核对是否需保留）— 预览前 40 行
```
name: junheng-bcs
description: 宠物体况评分 BCS 9 分制查询与参考图生成。按物种取逐分判定表，判断某分是否落在理想区（犬 4-5、猫仅 5）或肥胖筛查区（7-9），给出易误判点与体脂率区间，并生成侧视加俯视矢量参考图。当用户问猫狗胖不胖、算几分时使用。
description_en: Pet body condition score (BCS 9-point scale) lookup and reference figure generation for dogs and cats: per-score criteria (lateral/dorsal/palpation), ideal range and obesity screening zone, species-specific pitfalls, estimated body-fat ranges, and a self-drawn side/top SVG reference figure.
metadata:
  author: Junheng NutriAgent
  version: "1.0.0"
compatibility: Requires Node.js 18+ (ESM) and a UTF-8 filesystem. No network access and no third-party dependencies. Self-contained CLI facade; no dependency on other junheng-* skills.

# 体况评分参考（junheng-bcs）

## 目的与边界

**做什么**：给出「某个分数对应什么外观与触感」的判据原文、是否属于理想区/筛查区、以及该物种的易误判点。

**不做什么**：

- **不做诊断**。BCS 是筛查工具；临床肥胖确诊需兽医结合肌肉状况、体重趋势、饮食史、活动能力与体检。
- **不代替实际触摸**。所有判定都要求以触摸肋骨为准；只看轮廓会被毛量、原始袋、品种骨架误导。
- **不给减重方案**。能给出的是「该不该请兽医评估」以及「猫的减重速度必须比犬更慢」这类边界提示。
- **不使用受版权保护的现成图**。本技能生成的 SVG 是按公开发表判据自绘的原创矢量图（画面与配色均为原创），不是任何机构的原图。

## 诚实性红线

1. **筛查不等于诊断**。7~9 分只是进入临床肥胖筛查区（`inObesityScreeningZone: true`），输出里必须同时给 `caveats`，不得表述成「确诊肥胖」。
2. **体脂率是近似估算**。个体误差约正负 5 个百分点；体脂超过约 45% 时 BCS 区分度明显下降，此时应改用体脂指数（BFI）、体尺测量或 DXA。
3. **犬猫理想区不同**。犬是 4~5 分，**猫只有 5 分** —— 把猫按 4 分长期饲喂等于偏瘦。
4. **非理想分数要建议就医**。任何不在理想区的评分都建议请兽医团队评估一次，不要只凭本表大幅增减喂食量或运动量。
5. **档位标注写区间，不写单点**。参考图的三档分别覆盖 1–3 / 4–5 / 6–9 分，只标单点分数会与实际分数对不上。

## 用法

在技能根目录下执行：

```
node scripts/cli.mjs <命令> '<JSON 参数>'
node scripts/cli.mjs <命令> --stdin
node scripts/cli.mjs --help
node scripts/cli.mjs <命令> --help
```

... (截断)
```

- 建议：BOTH_CHANGED → 需并集合并（保留源独有+补充镜像独有）


## [BOTH_CHANGED] junheng-core / SKILL.md

- 源：`C:/Users/Administrator/WorkBuddy/2026-10-09-19-00-38/nutrition-agent-work/cli/skills\junheng-core\SKILL.md` (6002B)
- 镜像：`C:/Users/Administrator/.workbuddy/skills\junheng-core\SKILL.md` (6053B)
- 镜像独有行数：91 ｜ 源独有行数：87 ｜ 源独有中被镜像包含的行数：58

### 镜像独有（应补充回源）— 预览前 60 行
```
---
name: junheng-core
description: 钧衡 NutriAgent 共享内核（内部）。nutrition/-labeling/-cost/-feeding 四技能共同依赖的源码镜像与 286 条种子库，无业务命令。当出现「junheng-nutrition 报前置条件缺失」「技能找不到源码目录」或需更新法规/原料库并同步时使用。
description_en: Shared computation core for Junheng NutriAgent skills. Holds the single copy of the mirrored source closure (nutrition/standards/energy/bcsChart/labeling/costModes/feedingGuide) and the 286-ingredient seed database, consumed by junheng-nutrition, -labeling, -cost and -feeding. Not user-facing; no business commands of its own.
author: Junheng NutriAgent
version: 1.0.0
---

# 共享计算内核（junheng-core）

## 目的与边界

`junheng-core` 不是给用户提问用的技能，而是 **nutrition / labeling / cost / feeding / pipeline 五个技能共同的地基**：把项目源码单向镜像成技能可直接加载的形态。

| 目录 | 内容 | 唯一真源 |
|---|---|---|
| `scripts/vendor/*.js` | **12 个**模块：`nutrition` `dataQuality` `standards` `energy` `bcsChart` `labeling` `costModes` `feedingGuide` `species` `toxicology` `multiPetPlan` `portionLabel` | `src/lib/` |
| `scripts/data/ingredient_db.js` | 286 条原料种子库 | `src/data/` |
| `MANIFEST.json` | 每个条目的 sha256 指纹（引用方另记 `coreRef`） | 同步器生成 |

单独成层是为了「一份闭包，五个引用方」：换法规或换种子库**只改一处**，漂移只在这一处报，引用方经 `coreRef` 校验版本。

**边界**：本层**不含逻辑、不新增数值与判定** —— 全部计算能力都在 `src/lib/`，本层只是它的只读镜像。

### 目录布局与一处易踩的坑

数据放 `scripts/data/` 而**不是** `scripts/vendor/data/`：`nutrition.js` 写的是 `import RAW_DB from '../data/ingredient_db.js'`，从 `scripts/vendor/` 出发正好解析到 `scripts/data/`，两种布局都成立（零源码改动）；放错位置报 `ERR_MODULE_NOT_FOUND`（已实测）。

## 诚实性红线

1. 本层**不含任何逻辑**，只是 `src/lib/` 与 `src/data/` 的只读镜像。
2. **不得在技能侧改本层内容** —— 会被判 `MIRROR_TAMPERED`；应改源码再同步。
3. 本层**不新增数值、不新增判定** —— 有出入改项目源码，不是这里。
4. 引用方报告的数值都是**理论计算值**，不是检测值。

## 用法

> 以下命令均在**项目根**（`nutrition-agent-work`）运行。技能目录内**不含**该脚本：
> 技能侧是只读镜像，自造逻辑会被校验器判 `EXTRA_FILE` 错误（已实测），
> 所以同步器不能放进技能目录——放进去它会把技能目录误当项目根，全部条目报 `SOURCE_MISSING`。

```bash
node scripts/sync-skills.mjs          # 改完 src/ 后同步（写盘 + 自动校验）
node scripts/sync-skills.mjs --check  # 只校验：有漂移 exit 1，源文件缺失 exit 3
node scripts/sync-skills.mjs --dry    # 预览会同步什么，不写盘
```

## 命令一览

| 命令（前缀 `node scripts/` 省略） | 作用 |
|---|---|
| `sync-skills.mjs` | 同步门面 + 镜像 + MANIFEST（写盘），结束自动校验 |
| `sync-skills.mjs --check` | 只校验不写盘；有漂移 exit 1，源文件缺失 exit 3 |
| `sync-skills.mjs --dry` | 只打印同步计划，不写盘 |

**参数详表、输出字段表、可运行示例** → [详细接口参考](references/interface-reference.md)。

## 失败处理（退出码）

| 退出码 | 含义 |
... (截断)
```

### 源独有（已在源，供核对是否需保留）— 预览前 40 行
```
name: junheng-core
description: 钧衡 NutriAgent 的共享计算内核（不是面向用户的技能）。它是 junheng-nutrition / -labeling / -cost / -feeding 四个技能共同依赖的源码镜像与 286 条原料种子库的唯一持有者，本身不提供用户可调用的业务命令。当出现「junheng-nutrition 报前置条件缺失」「技能找不到源码目录」或需要更新法规/原料库并重新同步技能时使用。
description_en: Shared computation core for Junheng NutriAgent skills. Holds the single copy of the mirrored source closure (nutrition/standards/energy/bcsChart/labeling/costModes/feedingGuide) and the 286-ingredient seed database, consumed by junheng-nutrition, -labeling, -cost and -feeding. Not user-facing; no business commands of its own.
metadata:
  author: Junheng NutriAgent
  version: "1.0.0"
compatibility: Requires Node.js 18+ (ESM) and a UTF-8 filesystem. No network access and no third-party dependencies. Holds the mirrored source closure (vendor modules) and the ingredient seed database shared by the junheng-* skill family.

# 共享计算内核（junheng-core）

## 目的与边界

`junheng-core` 不是给用户提问用的技能，而是 **nutrition / labeling / cost / feeding / pipeline 五个技能共同的地基**：把项目源码单向镜像成技能可直接加载的形态。

| 目录 | 内容 | 唯一真源 |
|---|---|---|
| `scripts/vendor/*.js` | **12 个**模块：`nutrition` `dataQuality` `standards` `energy` `bcsChart` `labeling` `costModes` `feedingGuide` `species` `toxicology` `multiPetPlan` `portionLabel` | `src/lib/` |
| `scripts/data/ingredient_db.js` | 286 条原料种子库 | `src/data/` |
| `MANIFEST.json` | 每个条目的 sha256 指纹（引用方另记 `coreRef`） | 同步器生成 |

单独成层是为了「一份闭包，五个引用方」：换法规或换种子库**只改一处**，漂移只在这一处报，引用方经 `coreRef` 校验版本。

**边界**：本层**不含逻辑、不新增数值与判定** —— 全部计算能力都在 `src/lib/`，本层只是它的只读镜像。

### 目录布局与一处易踩的坑

数据放 `scripts/data/` 而**不是** `scripts/vendor/data/`：`nutrition.js` 写的是 `import RAW_DB from '../data/ingredient_db.js'`，从 `scripts/vendor/` 出发正好解析到 `scripts/data/`，两种布局都成立（零源码改动）；放错位置报 `ERR_MODULE_NOT_FOUND`（已实测）。

## 诚实性红线

1. 本层**不含任何逻辑**，只是 `src/lib/` 与 `src/data/` 的只读镜像。
2. **不得在技能侧改本层内容** —— 会被判 `MIRROR_TAMPERED`；应改源码再同步。
3. 本层**不新增数值、不新增判定** —— 有出入改项目源码，不是这里。
4. 引用方报告的数值都是**理论计算值**，不是检测值。

## 用法

```bash
node scripts/sync-skills.mjs          # 改完 src/ 后同步（写盘 + 自动校验）
node scripts/sync-skills.mjs --check  # 只校验：有漂移 exit 1，源文件缺失 exit 3
... (截断)
```

- 建议：BOTH_CHANGED → 需并集合并（保留源独有+补充镜像独有）


## [BOTH_CHANGED] junheng-nutrition / SKILL.md

- 源：`C:/Users/Administrator/WorkBuddy/2026-10-09-19-00-38/nutrition-agent-work/cli/skills\junheng-nutrition\SKILL.md` (5754B)
- 镜像：`C:/Users/Administrator/.workbuddy/skills\junheng-nutrition\SKILL.md` (5981B)
- 镜像独有行数：97 ｜ 源独有行数：96 ｜ 源独有中被镜像包含的行数：67

### 镜像独有（应补充回源）— 预览前 60 行
```
---
name: junheng-nutrition
description: 宠物食品原料库查询与配方营养计算。按名称或物料编号查 286 条原料（成分/价格/数据状态），或按配方加权算营养素组成、多口径能量、钙磷比与成本并给出数据覆盖率与缺口；也可算 RER/MER。问原料含量、配方营养时使用。
description_en: Pet food ingredient database lookup and recipe nutrient computation (Junheng NutriAgent). Look up any of 286 ingredients by name or code, or compute a recipe's nutrient profile, energy (GE/DE/ME with multiple methods), Ca:P ratio, cost, plus data coverage and gaps; also computes individual requirements (RER/MER).
author: Junheng NutriAgent
version: 1.1.0
---

# 原料库与配方计算（junheng-nutrition）

## 目的与边界

**做什么**：回答「某个原料有什么成分」与「某个配方算出来是多少」。

**不做什么**：

- **不做配方** —— 本技能算的是「给定原料与配比的营养结果」，不替你选原料、不当配方师。
- **不给合规结论** —— 限值判定请用 `junheng-labeling`；这里只出数值。
- **不做标签排版** —— 标签稿请用 `junheng-labeling`。
- **不猜测原料** —— 库里没有的原料会进 `unknown` 列表并明确报出，不会静默按 0 计。
- **单价不含税、不含议价** —— 价格口径为原料库 ¥/kg。

## 诚实性红线

1. **全部为理论计算值，不是检测值**。每次输出带 `basis: "theoretical"`。
2. **缺数据必须显式**。缺成分的原料进 `zeroData`，无价格的进 `cost.missingPrice`；覆盖率不足时结果会标低可靠度。**先看这几个字段再看数值**。
3. **未匹配的原料不静默丢弃**。`unknown` 列出所有没找到的原料名/编号。
4. **总重为 0 不出数**。返回 `data.computed:false` + `data.reason`（如 `zero_total_weight`），而不是给一堆 0。
   ⚠ **两层 ok 不同义**：外层 `ok:true` 只表示「命令执行成功」，不代表算出了数；**判断是否出数必须看 `data.computed`**。这个同名不同义是本项目最容易误读的一处，读结果时先看 `data.computed`。

## 用法

在技能根目录下执行：

```
node scripts/cli.mjs <命令> '<JSON 参数>'
node scripts/cli.mjs <命令> --stdin          # 参数从标准输入读
node scripts/cli.mjs --help
node scripts/cli.mjs <命令> --help
```

> ⚠ 依赖共享内核 `junheng-core`。报「找不到源码目录」时，到项目根 `packages/nutrition-agent-work` 跑 `node scripts/sync-skills.mjs`——技能目录是只读镜像，不含该脚本。

## 命令一览

| 命令 | 用途 |
|------|------|
| `ingredients` | 按关键词查原料（名称/编号片段），返回成分、价格与数据状态 |
| `recipe` | 按配方（原料+重量）算营养素、能量、钙磷比与成本 |
| `analyze-label` | 按标签上的原样基础营养值算干物质基/能量/钙磷比（不做 OCR） |
| `requirements` | 算个体营养需求（RER / MER + 生命阶段系数） |
| `dose2formula` | 把「每天该摄入多少 mg」换算成「配方添加比例%」（含纯度/存留率折减与反向达成度） |
| `evaluate` | 把配方结果与需求逐项对照（不替你下「达标」结论） |
| `parse-recipe-text` | 把自由文本配方解析成结构化条目 |
| `describe` | 输出机器可读的接口说明 |

**参数详表、输出字段表、可运行示例、传参注意** → [详细接口参考](references/interface-reference.md)。

> `dose2formula` **只做换算，不判断合规**：它把「每天该摄入多少」变成「配方加百分之几」，
> 本身不含任何 FEDIAF / AAFCO / GB 限值。要回答「是否达标 / 是否超限」，
... (截断)
```

### 源独有（已在源，供核对是否需保留）— 预览前 40 行
```
name: junheng-nutrition
description: 宠物食品原料库查询与配方营养计算。按名称或物料编号查 286 条原料（成分/价格/数据状态），或按配方加权算营养素组成、多口径能量、钙磷比与成本并给出数据覆盖率与缺口；也可算 RER/MER。问原料含量、配方营养时使用。
description_en: Pet food ingredient database lookup and recipe nutrient computation (Junheng NutriAgent). Look up any of 286 ingredients by name or code, or compute a recipe's nutrient profile, energy (GE/DE/ME with multiple methods), Ca:P ratio, cost, plus data coverage and gaps; also computes individual requirements (RER/MER).
metadata:
  author: Junheng NutriAgent
  version: "1.1.0"
compatibility: Requires Node.js 18+ (ESM) and a UTF-8 filesystem. No network access and no third-party dependencies. Loads its computation closure from the sibling shared-core skill junheng-core via the relative path ../../junheng-core/.

# 原料库与配方计算（junheng-nutrition）

## 目的与边界

**做什么**：回答「某个原料有什么成分」与「某个配方算出来是多少」。

**不做什么**：

- **不做配方** —— 本技能算的是「给定原料与配比的营养结果」，不替你选原料、不当配方师。
- **不给合规结论** —— 限值判定请用 `junheng-labeling`；这里只出数值。
- **不做标签排版** —— 标签稿请用 `junheng-labeling`。
- **不猜测原料** —— 库里没有的原料会进 `unknown` 列表并明确报出，不会静默按 0 计。
- **单价不含税、不含议价** —— 价格口径为原料库 ¥/kg。

## 诚实性红线

1. **全部为理论计算值，不是检测值**。每次输出带 `basis: "theoretical"`。
2. **缺数据必须显式**。缺成分的原料进 `zeroData`，无价格的进 `cost.missingPrice`；覆盖率不足时结果会标低可靠度。**先看这几个字段再看数值**。
3. **未匹配的原料不静默丢弃**。`unknown` 列出所有没找到的原料名/编号。
4. **总重为 0 不出数**。返回 `ok:false` + 原因，而不是给一堆 0。

## 用法

在技能根目录下执行：

```
node scripts/cli.mjs <命令> '<JSON 参数>'
node scripts/cli.mjs <命令> --stdin          # 参数从标准输入读
node scripts/cli.mjs --help
node scripts/cli.mjs <命令> --help
```

... (截断)
```

- 建议：BOTH_CHANGED → 需并集合并（保留源独有+补充镜像独有）


## [BOTH_CHANGED] junheng-labeling / SKILL.md

- 源：`C:/Users/Administrator/WorkBuddy/2026-10-09-19-00-38/nutrition-agent-work/cli/skills\junheng-labeling\SKILL.md` (13531B)
- 镜像：`C:/Users/Administrator/.workbuddy/skills\junheng-labeling\SKILL.md` (13487B)
- 镜像独有行数：221 ｜ 源独有行数：221 ｜ 源独有中被镜像包含的行数：156

### 镜像独有（应补充回源）— 预览前 60 行
```
---
name: junheng-labeling
description: 配方 → 合规标签底稿：营养保证值表（法规项目与顺序，带条款出处）、配料表（按重量递减）、合规结论与风险提示。当用户问「帮我做一份标签底稿」「营养保证值怎么写」「这个配方合不合规」时使用。
description_en: 'Generate a compliant pet food label draft from a recipe: guaranteed analysis table (regulated items in order, with clause citations), ingredient list (descending by weight), per-item compliance status, risk notes and mandatory disclaimers.'
author: Junheng NutriAgent
version: 1.0.0
---

# 标签底稿生成（junheng-labeling）

## 目的与边界

**做什么**：把「配方数值」排成一份**符合法规项目与顺序要求**的标签底稿，并给出逐项合规结论。

**不做什么**：

- **不是最终合规结论** —— 产物是**底稿**，提交前必须人工与现行法规原文逐条核对。
- **不自己发明数值** —— 限值全部来自 `standards.js`（条款已核对 GB/T 31216-2014 / 31217-2014）。
- **不给无数据项下结论** —— 库缺氨基酸等字段的项进 `nodata` 段，**既不算达标也不算未达标**。
- **不改配方** —— 本技能只呈现，不替你调整配方去满足限值。
- **不做 OCR** —— 读标签图片请用相应的视觉能力。

## 诚实性红线

1. **是底稿不是定稿**。每次输出都要连 `disclaimers` 一起转述，不得表述成「已合规」。
2. **未核对的体系必须显式标注**。AAFCO 数值尚未与官方出版物逐项核对（`verified: false`）。
3. **不可计算不等于通过**。`nodata` 项必须原样报出，不得省略、不得当作达标。
4. **风险提示必须转述**。`risks[]` 列出「不能直接印」的原因（如超限、缺数据），是使用者最容易漏看的部分。
5. **配料表排序可追溯**。按占比降序；并列重量时**保持用户录入顺序**（法规对并列无规定）。

## 工作流（三步，顺序不可颠倒）

| 步 | 命令 | 输入 → 输出 |
|---|------|------------|
| 1 | `junheng-nutrition recipe` | `items[]` → **recipe data** |
| 2 | `junheng-nutrition requirements` | `species` / `weightKg` → **req data** |
| 3 | **本技能 `draft`** | `{"recipe":…,"req":…}` → **draft data** |

第 3 步之后分两条支路：`render` / `coverage` 只吃第 3 步的 `draft`；`guaranteed` /
`ingredients-list` 只吃第 1、2 步的 `recipe` + `req`（不需要 `draft`）。两路都不必重跑前序。

**中间产物不能手捏**：第 1~3 步的 `data` 是**形状契约**的一部分 —— `draft` 校验 `recipe` 的
`dmPercent` / `asFed.crude_protein` / `energy.meModified` / `lines[]`；`render` / `coverage` 校验
`draft` 的 `product` / `basis` / `guaranteed.rows` / `ingredients.items` / `risks[]`。缺任一项会被
`exit 2` **点名拒绝**，而不是产出一份半截稿子。

> 想一步跑完 1~3 步（外加成本与喂食），用 `junheng-pipeline` 的 `run`。

## 用法

在技能根目录下执行 `node scripts/cli.mjs <命令> '<JSON 参数>'`（或 `--stdin` / 管道传参；
`--help` 与 `<命令> --help` 分别看全部命令与该命令的参数表）。

> ⚠ 依赖共享内核 `junheng-core`。报「找不到源码目录」时，到项目根 `packages/nutrition-agent-work` 跑 `node scripts/sync-skills.mjs`——技能目录是只读镜像，不含该脚本。

## 命令一览

| 命令 | 用途 |
|------|------|
| `draft` | 生成完整标签底稿（保证值 + 配料表 + 合规 + 风险 + 声明） |
... (截断)
```

### 源独有（已在源，供核对是否需保留）— 预览前 40 行
```
name: junheng-labeling
description: 配方 → 合规标签底稿生成（钧衡 NutriAgent 出品）。把配方与个体需求生成一份可提交的标签底稿：营养保证值表（按法规要求的项目与顺序，带条款出处）、配料表（按重量递减）、逐项合规结论与风险提示、以及必须随稿给出的声明。当用户问「帮我做一份标签底稿」「营养保证值怎么写」「配料表是什么顺序」「这个配方合不合规」「标签上要标哪些项目」「生成标签文本」时使用。
description_en: Generate a compliant pet food label draft from a recipe: guaranteed analysis table (regulated items in order, with clause citations), ingredient list (descending by weight), per-item compliance status, risk notes and mandatory disclaimers.
metadata:
  author: Junheng NutriAgent
  version: "1.0.0"
compatibility: Requires Node.js 18+ (ESM) and a UTF-8 filesystem. No network access and no third-party dependencies. Loads its computation closure from the sibling shared-core skill junheng-core via the relative path ../../junheng-core/.

# 标签底稿生成（junheng-labeling）

## 目的与边界

**做什么**：把「配方数值」排成一份**符合法规项目与顺序要求**的标签底稿，并给出逐项合规结论。

**不做什么**：

- **不是最终合规结论** —— 产物是**底稿**，提交前必须人工与现行法规原文逐条核对。
- **不自己发明数值** —— 限值全部来自 `standards.js`（条款已核对 GB/T 31216-2014 / 31217-2014）。
- **不给无数据项下结论** —— 库缺氨基酸等字段的项进 `nodata` 段，**既不算达标也不算未达标**。
- **不改配方** —— 本技能只呈现，不替你调整配方去满足限值。
- **不做 OCR** —— 读标签图片请用相应的视觉能力。

## 诚实性红线

1. **是底稿不是定稿**。每次输出都要连 `disclaimers` 一起转述，不得表述成「已合规」。
2. **未核对的体系必须显式标注**。AAFCO 数值尚未与官方出版物逐项核对（`verified: false`）。
3. **不可计算不等于通过**。`nodata` 项必须原样报出，不得省略、不得当作达标。
4. **风险提示必须转述**。`risks[]` 列出「不能直接印」的原因（如超限、缺数据），是使用者最容易漏看的部分。
5. **配料表排序可追溯**。按占比降序；并列重量时**保持用户录入顺序**（法规对并列无规定）。

## 工作流（三步，顺序不可颠倒）

| 步 | 命令 | 输入 → 输出 |
|---|------|------------|
| 1 | `junheng-nutrition recipe` | `items[]` → **recipe data** |
| 2 | `junheng-nutrition requirements` | `species` / `weightKg` → **req data** |
| 3 | **本技能 `draft`** | `{"recipe":…,"req":…}` → **draft data** |

第 3 步之后分两条支路：`render` / `coverage` 只吃第 3 步的 `draft`；`guaranteed` /
`ingredients-list` 只吃第 1、2 步的 `recipe` + `req`（不需要 `draft`）。两路都不必重跑前序。
... (截断)
```

- 建议：BOTH_CHANGED → 需并集合并（保留源独有+补充镜像独有）


## [BOTH_CHANGED] junheng-cost / SKILL.md

- 源：`C:/Users/Administrator/WorkBuddy/2026-10-09-19-00-38/nutrition-agent-work/cli/skills\junheng-cost\SKILL.md` (6151B)
- 镜像：`C:/Users/Administrator/.workbuddy/skills\junheng-cost\SKILL.md` (7701B)
- 镜像独有行数：136 ｜ 源独有行数：103 ｜ 源独有中被镜像包含的行数：72

### 镜像独有（应补充回源）— 预览前 60 行
```
---
name: junheng-cost
description: 宠物食品配方成本核算（钧衡 NutriAgent 出品）。把配方（原料+用量）换算成成本行，再按通用（烘焙粮/产品明细表）、冻干、猫条三种口径算成本，含各项加工费、损耗率、收得率与单位成本（元/kg、元/支）。当用户问「这个配方成本多少钱一公斤」「冻干出成率和成本怎么算」「猫条一支成本多少」「加工费怎么摊」「损耗算进去没」时使用。
description_en: Pet food recipe cost accounting (Junheng NutriAgent). Convert a recipe into cost lines, then compute cost under general / freeze-dry / cat-stick modes with processing fees, loss rate, yield rate and unit cost.
author: Junheng NutriAgent
version: 1.0.0
---

# 配方成本核算（junheng-cost）

## 目的与边界

**做什么**：算「某个配方在某加工口径下的成本是多少」，并把费用与损耗摊到单位成本。

**不做什么**：

- **不是报价** —— 不含税、不含议价、不含利润与渠道加价。只做成本算术。
- **不猜价格** —— 库里没价的原料按 0 计入并列入 `missingPrice`，**必须向用户提示**。
- **不替你选口径** —— 通用/冻干/猫条的成本结构不同，选哪个由你判断。
- **不吃配方结果** —— `costModes` 要的是「成本行」，需先用 `lines` 命令把配方转换（见下）。

## 诚实性红线

1. **是理论成本不是报价**。每次输出带 `basis: "theoretical"` 与免责声明。
2. **缺价必须显式**。`missingPrice[]` 列出所有无价格原料 —— 缺价会让总成本**偏低**，先看它再看数值。
3. **损耗与收得率是经验配置**。来自代码内的 `FREEZE_DRY_CONFIG` / `WORKSHOP_LOSS_CONFIG`，实际产线可能有差异，须一并说明。
4. **口径不同不可比**。通用 / 冻干 / 猫条的成本结构不同（如冻干按「解冻前用料」计、成品出成约 22%），不要把不同口径的数字直接横向比较。

## 成本可交付性判定（输出必带三字段）

> 光给数字不够。任何成本结论必须同时回答「这个数能不能拿去用」。三字段缺一即视为未完成。

| 字段 | 取值 | 说明 |
|------|------|------|
| `deliverable` | `usable` / `usable_with_caveat` / `not_usable` | 三档，判据见下表 |
| `confidence` | 0 ~ 1 | = 有价原料的重量占比；全有价时取 1.0 |
| `basis` | 对象 | 必含 `missingCount`（无价原料条数）、`missingWeightRatio`（无价原料重量占比）、`mode`（口径 id）、`feeSource`（费率来源） |

**三档判据（自上而下，命中即取）**：

| 档 | 触发条件 |
|----|----------|
| `not_usable` | `unknown[]` 非空，**或** `missingWeightRatio > 0.30` |
| `usable_with_caveat` | `missingPrice[]` 非空（占比 ≤ 0.30），**或** 用户未指定口径而由你代选 |
| `usable` | `missingPrice[]` 与 `unknown[]` 均空，且口径由用户明确指定 |

**禁止**：

1. 缺价时给 `usable`——缺价会让总成本偏低，等于给出乐观假数。
2. 只给数字不给 `basis`——对方无法判断这个数基于多少缺失数据。
3. 用 `confidence` 替代 `deliverable`——置信度低不等于不可用，两者不可互相顶替。
4. 把不同 `mode` 的 `deliverable` 直接放到一张表里比较。

**示例**（配方两原料，其一无价，占比 30%）：

```
deliverable: usable_with_caveat
confidence: 0.70
basis: { missingCount: 1, missingWeightRatio: 0.30, mode: "general", feeSource: "WORKSHOP_LOSS_CONFIG" }
```
... (截断)
```

### 源独有（已在源，供核对是否需保留）— 预览前 40 行
```
name: junheng-cost
description: 宠物食品配方成本核算（钧衡 NutriAgent 出品）。把配方（原料+用量）换算成成本行，再按通用（烘焙粮/产品明细表）、冻干、猫条三种口径算成本，含各项加工费、损耗率、收得率与单位成本（元/kg、元/支）。当用户问「这个配方成本多少钱一公斤」「冻干出成率和成本怎么算」「猫条一支成本多少」「加工费怎么摊」「损耗算进去没」时使用。
description_en: Pet food recipe cost accounting (Junheng NutriAgent). Convert a recipe into cost lines, then compute cost under general / freeze-dry / cat-stick modes with processing fees, loss rate, yield rate and unit cost.
metadata:
  author: Junheng NutriAgent
  version: "1.0.0"
compatibility: Requires Node.js 18+ (ESM) and a UTF-8 filesystem. No network access and no third-party dependencies. Loads its computation closure from the sibling shared-core skill junheng-core via the relative path ../../junheng-core/.

# 配方成本核算（junheng-cost）

## 目的与边界

**做什么**：算「某个配方在某加工口径下的成本是多少」，并把费用与损耗摊到单位成本。

**不做什么**：

- **不是报价** —— 不含税、不含议价、不含利润与渠道加价。只做成本算术。
- **不猜价格** —— 库里没价的原料按 0 计入并列入 `missingPrice`，**必须向用户提示**。
- **不替你选口径** —— 通用/冻干/猫条的成本结构不同，选哪个由你判断。
- **不吃配方结果** —— `costModes` 要的是「成本行」，需先用 `lines` 命令把配方转换（见下）。

## 诚实性红线

1. **是理论成本不是报价**。每次输出带 `basis: "theoretical"` 与免责声明。
2. **缺价必须显式**。`missingPrice[]` 列出所有无价格原料 —— 缺价会让总成本**偏低**，先看它再看数值。
3. **损耗与收得率是经验配置**。来自代码内的 `FREEZE_DRY_CONFIG` / `WORKSHOP_LOSS_CONFIG`，实际产线可能有差异，须一并说明。
4. **口径不同不可比**。通用 / 冻干 / 猫条的成本结构不同（如冻干按「解冻前用料」计、成品出成约 22%），不要把不同口径的数字直接横向比较。

## 工作流（两步，顺序不可颠倒）

| 步 | 命令 | 输入 → 输出 |
|----|------|-------------|
| **第 1 步** | `lines` | 配方 `items[{name 或 code, weight(克)}]` → **成本行 `data.lines[]`**（另含 `totalWeight` / `missingPrice[]` / `unknown[]`） |
| **第 2 步** | 成本命令**四选一** | 成本行 `lines[]` + 该口径的参数 → 单位成本（元/kg、元/支） |

第 2 步四选一：`sheet`（通用/烘焙粮，按批次数+克重）、`freeze-dry`（冻干，按投料→成品）、`cat-stick`（猫条，按规格）、`by-mode`（用 `mode` 切换的**统一入口**，参数是四者的并集）。

**中间产物形状契约** —— 成本行：
`{ code, name, unit:'kg', ratio(0~1), unitPrice(¥/kg), yieldRate }`。

... (截断)
```

- 建议：BOTH_CHANGED → 需并集合并（保留源独有+补充镜像独有）


## [BOTH_CHANGED] junheng-feeding / SKILL.md

- 源：`C:/Users/Administrator/WorkBuddy/2026-10-09-19-00-38/nutrition-agent-work/cli/skills\junheng-feeding\SKILL.md` (7036B)
- 镜像：`C:/Users/Administrator/.workbuddy/skills\junheng-feeding\SKILL.md` (6981B)
- 镜像独有行数：103 ｜ 源独有行数：103 ｜ 源独有中被镜像包含的行数：77

### 镜像独有（应补充回源）— 预览前 60 行
```
---
name: junheng-feeding
description: 宠物喂食指南与体况管理。按个体档案与配方算每日喂食计划（kcal、克/日、餐次）、体况策略、理想体重、换粮过渡与监测计划；支持多宠聚合产出合并采购清单与按每袋 N 天的分装排期标签。问猫每天吃多少克、BCS 7 分怎么喂时使用。
description_en: Pet feeding guide and body condition management (Junheng NutriAgent). Compute daily feeding plan (kcal, grams/day, meals), BCS-based energy adjustment, ideal weight estimate, diet transition schedule, monitoring plan and vet-visit signals. Also aggregates multiple pets' plans, produces a combined purchase list merged by material code, and splits daily amounts into labelled portion bags (recipe name, grams per portion, packaging date, use-by date, thawing note).
author: Junheng NutriAgent
version: 1.2.0
---

# 喂食指南与体况管理（junheng-feeding）

## 目的与边界

**做什么**：回答「这只宠物该吃多少、怎么喂、多久复评、什么情况要就医」。

**不做什么**：

- **不是处方** —— 产物是喂养**建议**；目标体重与增减喂食量必须由人（最好含兽医）确认。
- **不替代实际体况触摸** —— 所有 BCS 判定都以触摸肋骨为准；只看轮廓会被毛量、原始袋、品种骨架误导。
- **不做疾病诊断** —— 体况评分是筛查工具，不是兽医诊断。
- **不做配方** —— 需要配方营养结果时用 `junheng-nutrition`，本技能只消费它的输出。

## 诚实性红线

1. **分子分母都要说清**。能量为理论计算值（非检测值）；喂食量取决于所用配方的实际能量。
2. **体况评分是筛查不是诊断**。不在理想区（犬 4~5 分、猫 5 分）的评分都建议请兽医评估。
3. **猫的减重必须比犬更慢**。猫减重过快会诱发肝脂沉积症（脂肪肝），可危及生命 —— 这条必须转述。
4. **目标体重需兽医确认**。`energyAdjPercent` 是经验值不是剂量；不得只凭它大幅调整饲喂。
5. **禁止只凭输出改变饲喂**。任何调整都应在复评周期内逐步进行并观察。
6. **不替用户填保质期**。分装标签的「建议食用期限」必须由用户给出保质期天数；未给出时留空并提示「待定」。
   拿经验值（如「冷冻一般能放 90 天」）填进去，就是把猜想印在贴纸上，而用户会照着它决定还吃不吃。

## 用法

在技能根目录下执行：

```
node scripts/cli.mjs <命令> '<JSON 参数>'
node scripts/cli.mjs <命令> --stdin
node scripts/cli.mjs --help
node scripts/cli.mjs <命令> --help
```

> ⚠ 依赖共享内核 `junheng-core`。报「找不到源码目录」时，到项目根 `packages/nutrition-agent-work` 跑 `node scripts/sync-skills.mjs`——技能目录是只读镜像，不含该脚本。
> ⚠ `recipe` 与 `req` 来自 `junheng-nutrition`，给了 `recipe` 才能把能量换算成「克/日」。
> ⚠ 多宠命令（`plan-multi` / `purchase-list` / `portion-label`）：请把 `parseRecipeText` 里**未匹配**的原料一并传进
> `pets[].unmatched`（`{ rawName, weight }`）。不传的后果有两个 —— 采购清单**不会列出**它们（静默少买），
> 且这些库外原料**不会被安全闸筛到**（`recipe.lines` 里根本没有它们，库里查不到的禁用原料会因此漏网）。
> ⚠ `portion-label` 的「建议食用期限」= 分装日期 + `shelfLifeDays`。**不给 `shelfLifeDays` 就留空**，
> 本技能不猜保质期（贴纸会印「待定」）。缺保质期天数时请先向用户问明，不要把默认天数写进贴纸。

## 命令一览

| 命令 | 用途 |
|------|------|
| `plan` | 生成完整喂食计划（能量、克/日、餐次、过渡、监测、储存） |
| `plan-multi` | 多宠聚合：逐宠算喂食量并合计，同时给出按物料编号归并的合并采购清单 |
| `purchase-list` | 合并采购清单：只输出按物料编号归并的原料需求量（多宠合计，含未匹配原料） |
| `portion-label` | 同日分装排期 + 分装标签：把每宠每日用量按「每袋 N 天」拆袋，出可打印贴纸（配方名/每份克数/分装日期/建议食用期限/解冻提示） |
| `render` | 把喂食计划渲染成可直接粘贴的纯文本 |
| `bcs-policy` | 按体况评分取喂养策略（能量调整幅度、是否减重、限制原因） |
... (截断)
```

### 源独有（已在源，供核对是否需保留）— 预览前 40 行
```
name: junheng-feeding
description: 宠物喂食指南与体况管理。按个体档案与配方算每日喂食计划（kcal、克/日、餐次）、体况策略、理想体重、换粮过渡与监测计划；支持多宠聚合产出合并采购清单与按每袋 N 天的分装排期标签。问猫每天吃多少克、BCS 7 分怎么喂时使用。
description_en: Pet feeding guide and body condition management (Junheng NutriAgent). Compute daily feeding plan (kcal, grams/day, meals), BCS-based energy adjustment, ideal weight estimate, diet transition schedule, monitoring plan and vet-visit signals. Also aggregates multiple pets' plans, produces a combined purchase list merged by material code, and splits daily amounts into labelled portion bags (recipe name, grams per portion, packaging date, use-by date, thawing note).
metadata:
  author: Junheng NutriAgent
  version: "1.2.0"
compatibility: Requires Node.js 18+ (ESM) and a UTF-8 filesystem. No network access and no third-party dependencies. Loads its computation closure from the sibling shared-core skill junheng-core via the relative path ../../junheng-core/.

# 喂食指南与体况管理（junheng-feeding）

## 目的与边界

**做什么**：回答「这只宠物该吃多少、怎么喂、多久复评、什么情况要就医」。

**不做什么**：

- **不是处方** —— 产物是喂养**建议**；目标体重与增减喂食量必须由人（最好含兽医）确认。
- **不替代实际体况触摸** —— 所有 BCS 判定都以触摸肋骨为准；只看轮廓会被毛量、原始袋、品种骨架误导。
- **不做疾病诊断** —— 体况评分是筛查工具，不是兽医诊断。
- **不做配方** —— 需要配方营养结果时用 `junheng-nutrition`，本技能只消费它的输出。

## 诚实性红线

1. **分子分母都要说清**。能量为理论计算值（非检测值）；喂食量取决于所用配方的实际能量。
2. **体况评分是筛查不是诊断**。不在理想区（犬 4~5 分、猫 5 分）的评分都建议请兽医评估。
3. **猫的减重必须比犬更慢**。猫减重过快会诱发肝脂沉积症（脂肪肝），可危及生命 —— 这条必须转述。
4. **目标体重需兽医确认**。`energyAdjPercent` 是经验值不是剂量；不得只凭它大幅调整饲喂。
5. **禁止只凭输出改变饲喂**。任何调整都应在复评周期内逐步进行并观察。
6. **不替用户填保质期**。分装标签的「建议食用期限」必须由用户给出保质期天数；未给出时留空并提示「待定」。
   拿经验值（如「冷冻一般能放 90 天」）填进去，就是把猜想印在贴纸上，而用户会照着它决定还吃不吃。

## 用法

在技能根目录下执行：

```
node scripts/cli.mjs <命令> '<JSON 参数>'
node scripts/cli.mjs <命令> --stdin
node scripts/cli.mjs --help
node scripts/cli.mjs <命令> --help
... (截断)
```

- 建议：BOTH_CHANGED → 需并集合并（保留源独有+补充镜像独有）


## [BOTH_CHANGED] junheng-pipeline / SKILL.md

- 源：`C:/Users/Administrator/WorkBuddy/2026-10-09-19-00-38/nutrition-agent-work/cli/skills\junheng-pipeline\SKILL.md` (5923B)
- 镜像：`C:/Users/Administrator/.workbuddy/skills\junheng-pipeline\SKILL.md` (5861B)
- 镜像独有行数：96 ｜ 源独有行数：96 ｜ 源独有中被镜像包含的行数：69

### 镜像独有（应补充回源）— 预览前 60 行
```
---
name: junheng-pipeline
description: 跨技能串联编排。一次调用跑完配方营养、个体需求、标签底稿、成本与喂食计划全套计算，替代手工搬运中间结果；多宠入口一次产出逐宠喂食量、合计采购清单与分装排期标签。问把配方完整评估一遍、一条命令跑全套时使用。
description_en: Cross-skill orchestration. Computes recipe nutrition, individual requirements, label draft, cost sheet and feeding plan in a single call, replacing manual shuttling of 5-6 KB intermediate objects between skills. A multi-pet entry (run-multi) additionally goes from each pet's raw ingredients to per-pet feeding amounts, a combined purchase list, and same-day portioning schedules with printable labels.
author: Junheng NutriAgent
version: 1.1.0
---

# 跨技能串联编排（junheng-pipeline）

## 目的与边界

**做什么**：把分散在 4 个技能里的计算串成**一次调用**，消除手工搬运。

**不做什么**：

- **不含独立公式** —— 全部数值来自 `src/lib/` 的既有函数（`computeRecipe` / `computeRequirements` / `buildLabelDraft` / `computeCostSheetByMode` / `computeFeedingPlan`；多宠入口另用 `computeMultiPetPlan` / `computePortionLabels`）。结果与分别调用各技能**逐字段一致**。
- **不替代单技能调用** —— 只想算一个东西时用对应技能更快，不必走本门面。
- **不做配方决策** —— 不替用户选原料、不下合规结论。
- **不静默跳过** —— 每一步都有 `status`（`ok`/`skipped`/`failed`/`error`）与 `reason`。

## 诚实性红线

1. **是编排层不是新算法**。输出里的每个数字都能在对应单技能里复现。
2. **失败必须可见**。`ok:false` 时看 `summary.failed` 与每步的 `reason`，不要只看 `ok`。
3. **跳过也要可见**。`summary.skipped > 0` 表示有步骤因缺参数没跑 —— 例如没给 `profile` 就不会算喂食计划，**这不是"算出来是空"**。
4. **理论值 ≠ 检测值**；标签部分是**底稿不是定稿**；喂食部分是**建议不是处方**。
5. **分装标签是厨房贴纸，不是合规标签**。`run-multi` 的 `portions` 只回答「这袋多少克、贴什么字」；
   合规标签（保证值表 / 配料表）仍走 `junheng-labeling draft`。
6. **不替用户填保质期**。`run-multi` 的「建议食用期限」必须在给了 `shelfLifeDays` 时才有值；
   未给则留空并印「待定」—— 拿经验值填进去等于把猜想印在贴纸上。

## 用法

```
node scripts/cli.mjs run '<JSON 参数>'
node scripts/cli.mjs steps '{}'          # 只列步骤与所需参数，不计算
node scripts/cli.mjs --help
```

> ⚠ 依赖共享内核 `junheng-core`。报「找不到源码目录」时，到项目根 `packages/nutrition-agent-work` 跑 `node scripts/sync-skills.mjs`——技能目录是只读镜像，不含该脚本。

## 命令一览

| 命令 | 用途 |
|------|------|
| `run` | 一次调用完成全套 5 步 |
| `run-multi` | **多宠入口**：逐宠「原料→营养→需求→喂食量」→ 合计与合并采购清单 → 同日分装排期与分装标签 |
| `steps` | 只列出会执行哪些步骤、各需要什么（排错与自检用；含 `multi` 段列 `run-multi` 的四步） |
| `describe` | 输出机器可读的接口说明 |

**参数详表、输出字段表、可运行示例、单步管道 `--as`** → [详细接口参考](references/interface-reference.md)。

## 失败处理（退出码）

| 退出码 | 含义 |
|--------|------|
| 0 | 命令执行完毕。注意：**步骤失败/跳过也是 0** —— 请看 `summary` 与各步 `reason` |
| 1 | 内部错误（未预期异常） |
| 2 | 用法或输入错误，命令未执行 |
... (截断)
```

### 源独有（已在源，供核对是否需保留）— 预览前 40 行
```
name: junheng-pipeline
description: 跨技能串联编排。一次调用跑完配方营养、个体需求、标签底稿、成本与喂食计划全套计算，替代手工搬运中间结果；多宠入口一次产出逐宠喂食量、合计采购清单与分装排期标签。问把配方完整评估一遍、一条命令跑全套时使用。
description_en: Cross-skill orchestration. Computes recipe nutrition, individual requirements, label draft, cost sheet and feeding plan in a single call, replacing manual shuttling of 5-6 KB intermediate objects between skills. A multi-pet entry (run-multi) additionally goes from each pet's raw ingredients to per-pet feeding amounts, a combined purchase list, and same-day portioning schedules with printable labels.
metadata:
  author: Junheng NutriAgent
  version: "1.1.0"
compatibility: Requires Node.js 18+ (ESM) and a UTF-8 filesystem. No network access and no third-party dependencies. Loads its computation closure from the sibling shared-core skill junheng-core via the relative path ../../junheng-core/.

# 跨技能串联编排（junheng-pipeline）

## 目的与边界

**做什么**：把分散在 4 个技能里的计算串成**一次调用**，消除手工搬运。

**不做什么**：

- **不含独立公式** —— 全部数值来自 `src/lib/` 的既有函数（`computeRecipe` / `computeRequirements` / `buildLabelDraft` / `computeCostSheetByMode` / `computeFeedingPlan`；多宠入口另用 `computeMultiPetPlan` / `computePortionLabels`）。结果与分别调用各技能**逐字段一致**。
- **不替代单技能调用** —— 只想算一个东西时用对应技能更快，不必走本门面。
- **不做配方决策** —— 不替用户选原料、不下合规结论。
- **不静默跳过** —— 每一步都有 `status`（`ok`/`skipped`/`failed`/`error`）与 `reason`。

## 诚实性红线

1. **是编排层不是新算法**。输出里的每个数字都能在对应单技能里复现。
2. **失败必须可见**。`ok:false` 时看 `summary.failed` 与每步的 `reason`，不要只看 `ok`。
3. **跳过也要可见**。`summary.skipped > 0` 表示有步骤因缺参数没跑 —— 例如没给 `profile` 就不会算喂食计划，**这不是"算出来是空"**。
4. **理论值 ≠ 检测值**；标签部分是**底稿不是定稿**；喂食部分是**建议不是处方**。
5. **分装标签是厨房贴纸，不是合规标签**。`run-multi` 的 `portions` 只回答「这袋多少克、贴什么字」；
   合规标签（保证值表 / 配料表）仍走 `junheng-labeling draft`。
6. **不替用户填保质期**。`run-multi` 的「建议食用期限」必须在给了 `shelfLifeDays` 时才有值；
   未给则留空并印「待定」—— 拿经验值填进去等于把猜想印在贴纸上。

## 用法

```
node scripts/cli.mjs run '<JSON 参数>'
node scripts/cli.mjs steps '{}'          # 只列步骤与所需参数，不计算
node scripts/cli.mjs --help
```

... (截断)
```

- 建议：BOTH_CHANGED → 需并集合并（保留源独有+补充镜像独有）


## [BOTH_CHANGED] junheng-attainment / SKILL.md

- 源：`C:/Users/Administrator/WorkBuddy/2026-10-09-19-00-38/nutrition-agent-work/cli/skills\junheng-attainment\SKILL.md` (6199B)
- 镜像：`C:/Users/Administrator/.workbuddy/skills\junheng-attainment\SKILL.md` (6014B)
- 镜像独有行数：111 ｜ 源独有行数：111 ｜ 源独有中被镜像包含的行数：76

### 镜像独有（应补充回源）— 预览前 60 行
```
---
name: junheng-attainment
description: 配方达成度评估。给定配方与目标画像（物种/月龄/体况/目标市场）对照法规限值，输出达标/未达标/数据不足/无法判定四态、缺口与配比建议。当用户问「这个配方达不达标」「钙磷比够不够」「按国标能不能过」时使用。
description_en: Recipe attainment evaluation. Compares a formula against regulatory limits for a target profile (species / age / market) and reports per-nutrient status, the shortfall list and mixing suggestions.
author: Junheng NutriAgent
version: 1.0.0
---

# 目标达成度评估（junheng-attainment）

## 目的与边界

**做什么**：一次调用回答「**这个配方，对这个目标对象，达不达标、差在哪**」。

输入是**原料清单 + 目标画像**，输出是**逐项四态结论 + 缺口清单 + 配比建议**。

**不做什么**：

- **不含独立公式** —— 判定全部来自 `src/lib/nutrition.js` 的 `evaluateRecipe`，
  与界面「⑤ 达标评估」、配方体检、标签稿的合规段**同一口径**；本门面不写任何限值数字。
- **不替代 `junheng-nutrition recipe`** —— 那个只算**营养组成**（不判断达标与否）。
- **不替用户做配方决策** —— 给缺口与建议，不给「这个配方能卖」的结论。
- **不谎报未达标** —— 数据不足时如实标 `nodata` / `low`，算法见下。

## 诚实性红线（★ 最要紧的一节）

**四态，不是两态**。把 `nodata` 读成「未达标」是本项目最危险的误读：

| `status` | 含义 | 该怎么说 |
|---|---|---|
| `ok` | 达标 | 「已达标准」 |
| `fail` | 未达标 | 「低于下限 / 高于上限 X」 |
| `low` | 数值达标，但**该指标覆盖的原料有数据缺口** | 「达标，但结论仅供参考（覆盖率 N%）」 |
| `nodata` | **无法判定**（原料库无此字段，或本配方算不出） | 「**无法判定**，缺数据」—— **绝不能说成「未达标」** |

> 原料库没有氨基酸字段，所以**赖氨酸 / 牛磺酸几乎总是 `nodata`**。这是数据缺口，不是配方缺陷。

两个汇总标志**不可互相替代**：

- `summary.allPass` —— 「**没有明确未达标项**」，`nodata` 项**不计入**（原样取自 evaluateRecipe）。
- `summary.fullyVerified` —— 「**所有项都验过、且都达标**」。要下「全面达标」的结论**只能用它**。

其余：`gap` 是**展示用算术差**（判定口径以 `status` 为准）；理论值 ≠ 检测值。

## 用法

```
node scripts/cli.mjs assess  '<JSON 参数>'
node scripts/cli.mjs targets '{}'        # 先看有哪些目标口径可选，不计算
node scripts/cli.mjs --help
```

> ⚠ 依赖共享内核 `junheng-core`。报「找不到源码目录」时，到项目根 `packages/nutrition-agent-work` 跑 `node scripts/sync-skills.mjs`——技能目录是只读镜像，不含该脚本。

## 命令一览

| 命令 | 用途 |
|------|------|
| `assess` | 逐项达标度 + 缺口清单 + 配比建议 |
| `targets` | 列出可用目标口径（市场 × 物种 × 阶段） |
... (截断)
```

### 源独有（已在源，供核对是否需保留）— 预览前 40 行
```
name: junheng-attainment
description: 配方目标达成度评估（钧衡 NutriAgent 出品）。给定配方与目标画像（物种/月龄/体况/目标市场），逐项对照法规限值，输出四态结论（达标 / 未达标 / 数据不足 / 无法判定）、缺口清单与配比建议。当用户问「这个配方达不达标」「差在哪」「离标准还差多少」「按国标能不能过」「钙磷比够不够」「粗蛋白差几个点」时使用。
description_en: Recipe attainment evaluation. Compares a formula against regulatory limits for a target profile (species / age / market) and reports per-nutrient status, the shortfall list and mixing suggestions.
metadata:
  author: Junheng NutriAgent
  version: "1.0.0"
compatibility: Requires Node.js 18+ (ESM) and a UTF-8 filesystem. No network access and no third-party dependencies. Loads its computation closure from the sibling shared-core skill junheng-core via the relative path ../../junheng-core/.

# 目标达成度评估（junheng-attainment）

## 目的与边界

**做什么**：一次调用回答「**这个配方，对这个目标对象，达不达标、差在哪**」。

输入是**原料清单 + 目标画像**，输出是**逐项四态结论 + 缺口清单 + 配比建议**。

**不做什么**：

- **不含独立公式** —— 判定全部来自 `src/lib/nutrition.js` 的 `evaluateRecipe`，
  与界面「⑤ 达标评估」、配方体检、标签稿的合规段**同一口径**；本门面不写任何限值数字。
- **不替代 `junheng-nutrition recipe`** —— 那个只算**营养组成**（不判断达标与否）。
- **不替用户做配方决策** —— 给缺口与建议，不给「这个配方能卖」的结论。
- **不谎报未达标** —— 数据不足时如实标 `nodata` / `low`，算法见下。

## 诚实性红线（★ 最要紧的一节）

**四态，不是两态**。把 `nodata` 读成「未达标」是本项目最危险的误读：

| `status` | 含义 | 该怎么说 |
|---|---|---|
| `ok` | 达标 | 「已达标准」 |
| `fail` | 未达标 | 「低于下限 / 高于上限 X」 |
| `low` | 数值达标，但**该指标覆盖的原料有数据缺口** | 「达标，但结论仅供参考（覆盖率 N%）」 |
| `nodata` | **无法判定**（原料库无此字段，或本配方算不出） | 「**无法判定**，缺数据」—— **绝不能说成「未达标」** |

> 原料库没有氨基酸字段，所以**赖氨酸 / 牛磺酸几乎总是 `nodata`**。这是数据缺口，不是配方缺陷。

两个汇总标志**不可互相替代**：

- `summary.allPass` —— 「**没有明确未达标项**」，`nodata` 项**不计入**（原样取自 evaluateRecipe）。
... (截断)
```

- 建议：BOTH_CHANGED → 需并集合并（保留源独有+补充镜像独有）


## [MIRROR_TAMPERED] junheng-core / scripts/vendor/nutrition.js

- 源：`C:/Users/Administrator/WorkBuddy/2026-10-09-19-00-38/nutrition-agent-work/src/lib\nutrition.js` (99004B)
- 镜像：`C:/Users/Administrator/.workbuddy/skills\junheng-core\scripts/vendor\nutrition.js` (101115B)
- 镜像独有行数：2093 ｜ 源独有行数：2093 ｜ 源独有中被镜像包含的行数：1954

### 镜像独有（应补充回源）— 预览前 60 行
```
/**
 * 营养计算引擎（纯函数，不依赖 DOM，可被 node 直接 import 测试）。
 * 整合六大模块：
 *   1) 原料营养组成数据库（**应用种子库** `src/data/ingredient_db.js`，286 条，原样基础 % / 价格 ¥·kg⁻¹）
 *      ⚠ 本模块**只读种子库**。用户维护的**权威主库** `ingredient_db.json`（1617 条）放在**项目外**，
 *        由 `scripts/lib/master-db.mjs` 解析，**与种子库不是同一个东西**（只有数据核对脚本会读主库）。
 *        ——旧注释写成「ingredient_db.json，1625 项」，文件名与条数都错，且会让人把主库误当本模块的数据源。
 *   2) 配方营养组成计算（加权求和 → 原样基础 + 干物质基础）
 *   3) 成本核算（价格优先级：用户覆盖 > 数据库 > 未填）
 *   4) 钙磷比计算（原样 / 干物质基）
 *   5) 代谢能计算（FEDIAF 改良 Atwater 为主，经典 Atwater 参照）
 *   6) 个体营养需求评估（体重/年龄/性别/生理状态 → RER·MER + AAFCO/FEDIAF/NRC 指标对照）
 */
import RAW_DB from '../data/ingredient_db.js'
import {
  NUTRIENT_FIELDS, FIELD_LABEL, FIELD_STATUS, COVERAGE_LOW,
  fieldStatus, ingredientDataStatus, recipeCoverage, summarizeCoverage, renormalizedEstimate,
} from './dataQuality.js'
import { resolveStandard, stageOf, classifyMoisture, DEFAULT_MARKET } from './standards.js'
import { energyProfile, grossEnergy, GE_FACTORS, GE_FACTORS_KJ, MODIFIED_ATWATER, ATWATER, restingEnergy, felineNrcMer, modifiedAtwaterME, classicAtwaterME } from './energy.js'
/* 「成品水分」输入的解析口径只在 moistureProfiles.js 里定义一处，
   引擎 / 界面 / 标准分档三处共用 —— 避免空值被 Number() 静默当成 0%（见该函数注释）。
   ⚠ 镜像约束：新增 `../data/` 依赖必须同步登记到 scripts/lib/skills-manifest.mjs 的 data 列表。 */
import { parseMoisturePercent, MIN_FINISHED_MOISTURE } from '../data/moistureProfiles.js'

export { grossEnergy, energyProfile }
export { GE_FACTORS, GE_FACTORS_KJ, MODIFIED_ATWATER, ATWATER }

/* ---------------- 1. 原料数据库 ---------------- */

/**
 * 营养字段定义与数据质量判定统一放在 lib/dataQuality.js（唯一出处），
 * 这里只做转出，保证既有 `import { NUTRIENT_FIELDS } from './nutrition.js'` 不用改。
 */
export { NUTRIENT_FIELDS, FIELD_LABEL, FIELD_STATUS, COVERAGE_LOW }

function stripBrand(name) {
  return String(name || '').replace(/[（(][^（）()]*[)）]/g, '').trim()
}

/** 名称规范化（去空格/括号/标点、小写）——供仓储层按名称定位复用 */
export function normName(name) {
  return String(name || '')
    .replace(/[\s\u3000·，,、。;；:：!！?？]/g, '')
    .replace(/[（(][^（）()]*[)）]/g, '')
    .toLowerCase()
}

/**
 * 营养数据质量的派生字段（口径与理由见 lib/dataQuality.js）。
 *    _dataStatus   complete 8 项齐全 / partial 有值但缺项 / none 一项数值都没有
 *    _zeroFields   值为 0 的字段（待复核：真零 or 未录入）
 *    _missingFields 空值字段（确定未录入）
 *    _zero         （兼容旧名）是否存在「无可用数值」的字段 → 界面据此提示
 *    _hasData      （兼容旧名）是否至少有一项 >0 的数值
 *
 * ⚠ 旧实现 `_zero = 任一字段 == null`、`_hasData = 任一字段 != null`，
 *   于是「8 项全为 0」的 129 条原料被判定为**有数据且无缺失** —— 这正是
 *   实测中「算式明显失真、界面却报零数据 0 条」的根因（计划 A2）。
 */
... (截断)
```

### 源独有（已在源，供核对是否需保留）— 预览前 40 行
```
/**
 * 营养计算引擎（纯函数，不依赖 DOM，可被 node 直接 import 测试）。
 * 整合六大模块：
 *   1) 原料营养组成数据库（**应用种子库** `src/data/ingredient_db.js`，286 条，原样基础 % / 价格 ¥·kg⁻¹）
 *      ⚠ 本模块**只读种子库**。用户维护的**权威主库** `ingredient_db.json`（1617 条）放在**项目外**，
 *        由 `scripts/lib/master-db.mjs` 解析，**与种子库不是同一个东西**（只有数据核对脚本会读主库）。
 *        ——旧注释写成「ingredient_db.json，1625 项」，文件名与条数都错，且会让人把主库误当本模块的数据源。
 *   2) 配方营养组成计算（加权求和 → 原样基础 + 干物质基础）
 *   3) 成本核算（价格优先级：用户覆盖 > 数据库 > 未填）
 *   4) 钙磷比计算（原样 / 干物质基）
 *   5) 代谢能计算（FEDIAF 改良 Atwater 为主，经典 Atwater 参照）
 *   6) 个体营养需求评估（体重/年龄/性别/生理状态 → RER·MER + AAFCO/FEDIAF/NRC 指标对照）
 */
import RAW_DB from '../data/ingredient_db.js'
import {
  NUTRIENT_FIELDS, FIELD_LABEL, FIELD_STATUS, COVERAGE_LOW,
  fieldStatus, ingredientDataStatus, recipeCoverage, summarizeCoverage, renormalizedEstimate,
} from './dataQuality.js'
import { resolveStandard, stageOf, classifyMoisture, DEFAULT_MARKET } from './standards.js'
import { energyProfile, grossEnergy, GE_FACTORS, GE_FACTORS_KJ, MODIFIED_ATWATER, ATWATER, restingEnergy, felineNrcMer, modifiedAtwaterME, classicAtwaterME } from './energy.js'
/* 「成品水分」输入的解析口径只在 moistureProfiles.js 里定义一处，
   引擎 / 界面 / 标准分档三处共用 —— 避免空值被 Number() 静默当成 0%（见该函数注释）。
   ⚠ 镜像约束：新增 `../data/` 依赖必须同步登记到 scripts/lib/skills-manifest.mjs 的 data 列表。 */
import { parseMoisturePercent, MIN_FINISHED_MOISTURE } from '../data/moistureProfiles.js'

export { grossEnergy, energyProfile }
export { GE_FACTORS, GE_FACTORS_KJ, MODIFIED_ATWATER, ATWATER }

/* ---------------- 1. 原料数据库 ---------------- */

/**
 * 营养字段定义与数据质量判定统一放在 lib/dataQuality.js（唯一出处），
 * 这里只做转出，保证既有 `import { NUTRIENT_FIELDS } from './nutrition.js'` 不用改。
 */
export { NUTRIENT_FIELDS, FIELD_LABEL, FIELD_STATUS, COVERAGE_LOW }

function stripBrand(name) {
  return String(name || '').replace(/[（(][^（）()]*[)）]/g, '').trim()
}

... (截断)
```

- 建议：MIRROR_TAMPERED → 可直接镜像覆盖源（源=基线）


## [MIRROR_TAMPERED] junheng-core / scripts/vendor/labeling.js

- 源：`C:/Users/Administrator/WorkBuddy/2026-10-09-19-00-38/nutrition-agent-work/src/lib\labeling.js` (19809B)
- 镜像：`C:/Users/Administrator/.workbuddy/skills\junheng-core\scripts/vendor\labeling.js` (20280B)
- 镜像独有行数：429 ｜ 源独有行数：429 ｜ 源独有中被镜像包含的行数：385

### 镜像独有（应补充回源）— 预览前 60 行
```
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
... (截断)
```

### 源独有（已在源，供核对是否需保留）— 预览前 40 行
```
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
... (截断)
```

- 建议：MIRROR_TAMPERED → 可直接镜像覆盖源（源=基线）


## [MIRROR_TAMPERED] junheng-core / scripts/vendor/feedingGuide.js

- 源：`C:/Users/Administrator/WorkBuddy/2026-10-09-19-00-38/nutrition-agent-work/src/lib\feedingGuide.js` (63513B)
- 镜像：`C:/Users/Administrator/.workbuddy/skills\junheng-core\scripts/vendor\feedingGuide.js` (64815B)
- 镜像独有行数：1292 ｜ 源独有行数：1292 ｜ 源独有中被镜像包含的行数：1212

### 镜像独有（应补充回源）— 预览前 60 行
```
/**
 * 饲喂指导书（Feeding Guide）：把「配方 + 个体档案 + 体况评分」编成一份
 * 可以直接打印交给宠主（或随货附送）的饲喂方案。
 *
 * ## 为什么单独立一个模块
 * `nutrition.js` 已经能算 RER/MER 与「每日克数」（`dailyFeeding`），但那只是一行数字；
 * 一份能交付的指导书还要回答：**分几餐、每餐多少、怎么换粮、多久复查、什么时候该调整、
 * 怎么保存、什么情况下必须找兽医**。这些是**编排**而不是营养学公式，
 * 放在这里，好让 `nutrition.js` 保持「纯计算」的职责。
 *
 * ## 三件事刻意分开，不许互相冒充
 * | 类型 | 例子 | 处理方式 |
 * |---|---|---|
 * | **有出处可算的** | RER/MER、每餐克数、成本、钙磷摄入 | 直接给数值，附出处 |
 * | **经验规则的** | BCS→理想体重、BCS→能量调整幅度 | 给数值但**明标「经验估算」**，不作承诺 |
 * | **必须由人判断的** | 目标体重、是否减重、疾病状态下怎么喂 | **只给提示与条件，不替用户决定** |
 *
 * 依据与出处：
 * - RER `70 × BW^0.75`（犬）/ `70 × BW^0.67`（猫）—— NRC 2006（复用 `nutrition.js`）。
 * - 状态系数（生长/绝育/老年/妊娠/泌乳/减脂）—— NRC 2006 + AAFCO 犬猫营养学要点的通行用法。
 * - 9 分制体况评分（BCS）—— 犬猫通用（Laflamme 1997 的 9 分制），4~5 分为理想。
 * - **每 1 分 BCS 高于 5 分 ≈ 超过理想体重 10%** —— 临床经验规则，**非实验结论**，
 *   因此 `idealWeightFromBcs` 的返回值一律带 `empirical:true`，界面要照原样标出。
 * - 生长终点（犬按体型 12/15/18 月龄；猫 12 月龄）—— AAFCO 犬猫营养概要的通行划分。
 * - 换粮过渡 7 天（25%→50%→75%→100%）—— 临床与厂商标配做法。
 *
 * ## 与界面文案有关的硬约束
 * React **不解析 Markdown**，所以本文件产出的所有字符串里**不得出现 `**`**；
 * 需要强调时用普通中文表述（由 `jsx-text-markdown-test.mjs` 静态扫描守住）。
 *
 * ## 缺数据怎么办
 * 不静默兜底。缺的输入逐项记进 `missing`，缺到算不出克数时 `ok:false` 并说明原因，
 * 但**指导书其余部分照常给出**（体况、换粮、储存、观察这些不依赖配方能量）。
 */

import { parseAge, identifyBreed, sizeFromWeight, SIZE_LABELS, sexLabel } from './nutrition.js'
import { restingEnergy, DEFAULT_SPECIES } from './energy.js'
import { normSpecies } from './species.js'
import {
  bcsChartFor, bcsChartRow, inObesityScreeningZone, isIdealFor, idealScoresFor,
  BCS_SPECIES_NOTE, BCS_CHART_CAVEATS, BCS_OBESITY_SCREENING_ZONE, BCS_CHART_COLUMNS,
  bcsChartSourceText, normBcsSpecies,
} from './bcsChart.js'

const r0 = (n) => Math.round(n)
const r1 = (n) => Math.round(n * 10) / 10
const r2 = (n) => Math.round(n * 100) / 100
const num = (v) => (Number.isFinite(Number(v)) ? Number(v) : 0)

/* ================= 1. 体况评分 BCS（9 分制，犬猫通用） ================= */

/**
 * 9 分制体况评分。`group` 为四档归类，`energyAdjPercent` 为**建议的能量调整幅度**
 * （在 MER 基础上乘 `1 + adj/100`，即 +10 表示加 10%）。
 *
 * ⚠ `energyAdjPercent` 是**经验值、不是剂量**：真正执行前要由人（最好含兽医）
 *   确认目标体重。正数（偏瘦）用于增重、负数（偏胖）用于减重。
 */
export const BCS_SCALE = [
  {
... (截断)
```

### 源独有（已在源，供核对是否需保留）— 预览前 40 行
```
/**
 * 饲喂指导书（Feeding Guide）：把「配方 + 个体档案 + 体况评分」编成一份
 * 可以直接打印交给宠主（或随货附送）的饲喂方案。
 *
 * ## 为什么单独立一个模块
 * `nutrition.js` 已经能算 RER/MER 与「每日克数」（`dailyFeeding`），但那只是一行数字；
 * 一份能交付的指导书还要回答：**分几餐、每餐多少、怎么换粮、多久复查、什么时候该调整、
 * 怎么保存、什么情况下必须找兽医**。这些是**编排**而不是营养学公式，
 * 放在这里，好让 `nutrition.js` 保持「纯计算」的职责。
 *
 * ## 三件事刻意分开，不许互相冒充
 * | 类型 | 例子 | 处理方式 |
 * |---|---|---|
 * | **有出处可算的** | RER/MER、每餐克数、成本、钙磷摄入 | 直接给数值，附出处 |
 * | **经验规则的** | BCS→理想体重、BCS→能量调整幅度 | 给数值但**明标「经验估算」**，不作承诺 |
 * | **必须由人判断的** | 目标体重、是否减重、疾病状态下怎么喂 | **只给提示与条件，不替用户决定** |
 *
 * 依据与出处：
 * - RER `70 × BW^0.75`（犬）/ `70 × BW^0.67`（猫）—— NRC 2006（复用 `nutrition.js`）。
 * - 状态系数（生长/绝育/老年/妊娠/泌乳/减脂）—— NRC 2006 + AAFCO 犬猫营养学要点的通行用法。
 * - 9 分制体况评分（BCS）—— 犬猫通用（Laflamme 1997 的 9 分制），4~5 分为理想。
 * - **每 1 分 BCS 高于 5 分 ≈ 超过理想体重 10%** —— 临床经验规则，**非实验结论**，
 *   因此 `idealWeightFromBcs` 的返回值一律带 `empirical:true`，界面要照原样标出。
 * - 生长终点（犬按体型 12/15/18 月龄；猫 12 月龄）—— AAFCO 犬猫营养概要的通行划分。
 * - 换粮过渡 7 天（25%→50%→75%→100%）—— 临床与厂商标配做法。
 *
 * ## 与界面文案有关的硬约束
 * React **不解析 Markdown**，所以本文件产出的所有字符串里**不得出现 `**`**；
 * 需要强调时用普通中文表述（由 `jsx-text-markdown-test.mjs` 静态扫描守住）。
 *
 * ## 缺数据怎么办
 * 不静默兜底。缺的输入逐项记进 `missing`，缺到算不出克数时 `ok:false` 并说明原因，
 * 但**指导书其余部分照常给出**（体况、换粮、储存、观察这些不依赖配方能量）。
 */

import { parseAge, identifyBreed, sizeFromWeight, SIZE_LABELS, sexLabel } from './nutrition.js'
import { restingEnergy, DEFAULT_SPECIES } from './energy.js'
import { normSpecies } from './species.js'
import {
  bcsChartFor, bcsChartRow, inObesityScreeningZone, isIdealFor, idealScoresFor,
... (截断)
```

- 建议：MIRROR_TAMPERED → 可直接镜像覆盖源（源=基线）


## [MIRROR_TAMPERED] junheng-core / scripts/vendor/multiPetPlan.js

- 源：`C:/Users/Administrator/WorkBuddy/2026-10-09-19-00-38/nutrition-agent-work/src/lib\multiPetPlan.js` (14768B)
- 镜像：`C:/Users/Administrator/.workbuddy/skills\junheng-core\scripts/vendor\multiPetPlan.js` (15128B)
- 镜像独有行数：348 ｜ 源独有行数：348 ｜ 源独有中被镜像包含的行数：316

### 镜像独有（应补充回源）— 预览前 60 行
```
/**
 * 多宠 / 多日组合层：多宠聚合 + 合并采购清单（批 8 · 节点 4 · N3-a）。
 *
 * ## 定位
 * **纯组合层** —— 不引入任何新公式。每只宠物的喂食量一律来自
 * `feedingGuide.computeFeedingPlan()`，原料构成一律来自 `recipe.lines`
 * （`computeRecipe()` 的输出）。因此本模块输出的任何数字都能在单宠路径里复现。
 *
 * ## 为什么需要它
 * `computeFeedingPlan()` 是**单宠单日**的：它回答「这只猫今天吃多少克」，
 * 但不回答「一家两只猫 + 一只狗，这个月要买多少鸡胸肉」。多宠家庭的实际动作是
 * **一次采购、按份分装**，而采购对象是**原料**（按物料编号），不是「成品粮」。
 * 本模块补的正是这一段：逐宠算量 → 按物料编号归并 → 出货清单。
 *
 * ## 三条不静默红线
 * 1. **算不出的宠物不进总量**。`ok:false` 的宠物（缺体重 / 缺能量）若按 0 参与合计，
 *    会得到一个「看着完整」的假总量 —— 而用户会照着这个数去买料。
 *    故 `totals` / `purchase` 只累加 `ok:true` 的宠物，`failedCount` 单独报出。
 * 2. **未匹配原料必须显式报出**。`computeRecipe()` 的 `lines` 只含**命中原料库**的条目，
 *    库外原料在 `parseRecipeText()` 里就是 `ingredient:null`、进不了 lines。若只按 lines
 *    聚合，采购清单会**静默少买**。故接受调用方传入 `unmatched`，原样进 `purchase.unmatched`。
 * 3. **单价冲突不静默取值**。同一物料编号在不同宠物的配方里单价不同时，取任何一边
 *    都是在替用户拍板；本模块标 `priceConflict` 并列出全部取值与金额区间。
 *
 * ## 与 feedingGuide.js 的关系
 * 同域内聚 import（与 `feedingDoc.js` → `feedingGuide.js` 同例）。舍入口径
 * （r0/r1/r2）逐字沿用 feedingGuide.js，避免两处输出在末位打架。
 */
import { computeFeedingPlan } from './feedingGuide.js'

/* ================= 1. 常量 ================= */

/** 采购口径默认天数（30 天 ≈ 一个月；喂食计划的克/日本就是日均值，直接乘天数即可） */
export const PURCHASE_DAYS_DEFAULT = 30
/** 采购口径天数上限（超过一年没有实际意义，只会放大估算误差） */
export const PURCHASE_DAYS_MAX = 365
/** 单次聚合的宠物数上限。多宠家庭极少超过这个数；超限直接报错而**不静默截断** —— 截断会把「少算了几只」变成看不见的事实 */
export const MAX_PETS = 20

/* ================= 2. 小工具（与 feedingGuide.js 同口径） ================= */

const r0 = (n) => Math.round(n)
const r1 = (n) => Math.round(n * 10) / 10
const r2 = (n) => Math.round(n * 100) / 100
const num = (v) => (Number.isFinite(Number(v)) ? Number(v) : 0)
const str = (v) => (typeof v === 'string' ? v.trim() : '')

/** 单价：只有正数才算「有价」；0 / 负数 / 非数字一律视为未填（缺价必须区别于「价格是 0」） */
function priceOf(line) {
  const p = Number(line && line.price)
  return Number.isFinite(p) && p > 0 ? r2(p) : null
}

function clampDays(v) {
  const d = Number(v)
  if (!Number.isFinite(d) || d <= 0) return PURCHASE_DAYS_DEFAULT
  return Math.min(Math.round(d), PURCHASE_DAYS_MAX)
}

/* ================= 3. 单宠每日原料用量 ================= */
... (截断)
```

### 源独有（已在源，供核对是否需保留）— 预览前 40 行
```
/**
 * 多宠 / 多日组合层：多宠聚合 + 合并采购清单（批 8 · 节点 4 · N3-a）。
 *
 * ## 定位
 * **纯组合层** —— 不引入任何新公式。每只宠物的喂食量一律来自
 * `feedingGuide.computeFeedingPlan()`，原料构成一律来自 `recipe.lines`
 * （`computeRecipe()` 的输出）。因此本模块输出的任何数字都能在单宠路径里复现。
 *
 * ## 为什么需要它
 * `computeFeedingPlan()` 是**单宠单日**的：它回答「这只猫今天吃多少克」，
 * 但不回答「一家两只猫 + 一只狗，这个月要买多少鸡胸肉」。多宠家庭的实际动作是
 * **一次采购、按份分装**，而采购对象是**原料**（按物料编号），不是「成品粮」。
 * 本模块补的正是这一段：逐宠算量 → 按物料编号归并 → 出货清单。
 *
 * ## 三条不静默红线
 * 1. **算不出的宠物不进总量**。`ok:false` 的宠物（缺体重 / 缺能量）若按 0 参与合计，
 *    会得到一个「看着完整」的假总量 —— 而用户会照着这个数去买料。
 *    故 `totals` / `purchase` 只累加 `ok:true` 的宠物，`failedCount` 单独报出。
 * 2. **未匹配原料必须显式报出**。`computeRecipe()` 的 `lines` 只含**命中原料库**的条目，
 *    库外原料在 `parseRecipeText()` 里就是 `ingredient:null`、进不了 lines。若只按 lines
 *    聚合，采购清单会**静默少买**。故接受调用方传入 `unmatched`，原样进 `purchase.unmatched`。
 * 3. **单价冲突不静默取值**。同一物料编号在不同宠物的配方里单价不同时，取任何一边
 *    都是在替用户拍板；本模块标 `priceConflict` 并列出全部取值与金额区间。
 *
 * ## 与 feedingGuide.js 的关系
 * 同域内聚 import（与 `feedingDoc.js` → `feedingGuide.js` 同例）。舍入口径
 * （r0/r1/r2）逐字沿用 feedingGuide.js，避免两处输出在末位打架。
 */
import { computeFeedingPlan } from './feedingGuide.js'

/* ================= 1. 常量 ================= */

/** 采购口径默认天数（30 天 ≈ 一个月；喂食计划的克/日本就是日均值，直接乘天数即可） */
export const PURCHASE_DAYS_DEFAULT = 30
/** 采购口径天数上限（超过一年没有实际意义，只会放大估算误差） */
export const PURCHASE_DAYS_MAX = 365
/** 单次聚合的宠物数上限。多宠家庭极少超过这个数；超限直接报错而**不静默截断** —— 截断会把「少算了几只」变成看不见的事实 */
export const MAX_PETS = 20

/* ================= 2. 小工具（与 feedingGuide.js 同口径） ================= */
... (截断)
```

- 建议：MIRROR_TAMPERED → 可直接镜像覆盖源（源=基线）


## [MIRROR_TAMPERED] junheng-core / scripts/vendor/portionLabel.js

- 源：`C:/Users/Administrator/WorkBuddy/2026-10-09-19-00-38/nutrition-agent-work/src/lib\portionLabel.js` (16451B)
- 镜像：`C:/Users/Administrator/.workbuddy/skills\junheng-core\scripts/vendor\portionLabel.js` (16857B)
- 镜像独有行数：394 ｜ 源独有行数：394 ｜ 源独有中被镜像包含的行数：351

### 镜像独有（应补充回源）— 预览前 60 行
```
/**
 * 分装排期 + 分装标签（批 8 · 节点 5 · N3-b）。
 *
 * ## 定位
 * **纯函数、零依赖、零新公式**。上游只喂一个数：某只宠物（或某个配方）的**每日用量**
 * （克/日，来自 `feedingGuide.computeFeedingPlan()` 或 `multiPetPlan.purchaseFromPets()`
 * 的 `gramsPerDay`）。本模块把它拆成「一袋能吃几天」的分装排期，并出可打印的分装标签。
 *
 * ## 为什么不是复用 labeling.js
 * `src/lib/labeling.js` 是**合规标签底稿**：保证值表、配料表、合规风险提示，
 * 受 `LABEL_FORMAT_VERSION` 约束，面向**监管与消费者**。
 * 分装标签是**厨房贴纸**：配方名 / 每份克数 / 分装日期 / 建议食用期限 / 解冻提示，
 * 面向**当天分装的人**。两者的字段几乎不相交 ⇒ 分装标签**新建**，不复用 labeling ——
 * 把「厨房贴纸」塞进合规底稿会稀释 labeling 的合规语义（原文「复用 labeling 模板」的假设已实测证伪）。
 *
 * ## 四条不静默红线
 * 1. **不猜保质期**。「建议食用期限 = 分装日期 + 保质期」里的**保质期必须由调用方给**；
 *    缺失时 `useByDate = null` 并标 `shelfLifeMissing` —— 拿「冷冻一般能放 90 天」这类
 *    经验值填数，就是把猜想印在贴纸上，而用户会照着它决定还吃不吃。
 * 2. **克数守恒**。Σ(每袋克数) 必须 == 总量。末袋吸收舍入余量；若各袋都独立四舍五入，
 *    「分装后总量少了几克」这件事没有任何人会察觉。
 * 3. **末袋天数不足必须显式**。总量 30 天 ÷ 每袋 7 天 = 4 袋零 2 天 ⇒ 末袋只覆盖 2 天，
 *    标 `partial:true`。假装每袋都是整周，会让「最后一袋吃到哪天」算错。
 * 4. **总量为 0/负 ⇒ 报错，不返回空排期**。空排期会被读成「已经分好了」，
 *    而事实是「没有任何东西可分」。
 *
 * ## 与 multiPetPlan.js 的口径耦合（不 import，靠守卫钉住）
 * `TOTAL_DAYS_DEFAULT` 与 `multiPetPlan.PURCHASE_DAYS_DEFAULT` 是**同一个口径**
 * （30 天 ≈ 一个月）。本模块保持零依赖，故不 import 而是各自常量 + 由守卫断言两者相等 ——
 * 将来任一侧改动，守卫立刻判红，不会静默分叉。
 */

/* ================= 1. 常量 ================= */

/** 分装标签格式版本（改字段口径/排版时必须同步递增，便于回溯历史贴纸） */
export const PORTION_LABEL_VERSION = 1

/** 每袋默认覆盖天数：**按周分装**（对齐 feedingGuide.js 既有文案「按一周用量分装小袋」） */
export const PORTION_DAYS_DEFAULT = 7
/** 每袋天数上限（超过一季没有实际意义，只会让袋数与贴纸数失控） */
export const PORTION_DAYS_MAX = 90

/** 总量覆盖天数默认：30 天 ≈ 一个月（与 multiPetPlan 采购口径同值，守卫钉住） */
export const TOTAL_DAYS_DEFAULT = 30
/** 总量覆盖天数上限（超过一年只会放大估算误差） */
export const TOTAL_DAYS_MAX = 365

/** 形态 → 解冻/保存提示。给不出形态时**不给默认值**，明说请按实际填写。 */
export const FORM_TIPS = {
  frozen_raw: '生食：全程冷链（-18℃ 冷冻）；解冻在冷藏层进行，解冻后 24 小时内吃完，不要反复冻融',
  frozen_cooked: '熟食（冷冻）：提前移到冷藏层解冻，回温至室温再喂；解冻后 24 小时内吃完',
  dry: '干粮：无需解冻；开封后密封、置于阴凉干燥处，避免受潮与阳光直射',
  wet: '湿粮：无需冷冻；开封后冷藏并在 24 小时内用完，常温放置不宜超过 1 小时',
  unknown: '保存与解冻方式请按本产品实际形态填写（未提供形态——本模块不代填）',
}

/** 形态 key → 中文名（进标签正文） */
export const FORM_LABELS = {
  frozen_raw: '生食（冷冻）',
  frozen_cooked: '熟食（冷冻）',
... (截断)
```

### 源独有（已在源，供核对是否需保留）— 预览前 40 行
```
/**
 * 分装排期 + 分装标签（批 8 · 节点 5 · N3-b）。
 *
 * ## 定位
 * **纯函数、零依赖、零新公式**。上游只喂一个数：某只宠物（或某个配方）的**每日用量**
 * （克/日，来自 `feedingGuide.computeFeedingPlan()` 或 `multiPetPlan.purchaseFromPets()`
 * 的 `gramsPerDay`）。本模块把它拆成「一袋能吃几天」的分装排期，并出可打印的分装标签。
 *
 * ## 为什么不是复用 labeling.js
 * `src/lib/labeling.js` 是**合规标签底稿**：保证值表、配料表、合规风险提示，
 * 受 `LABEL_FORMAT_VERSION` 约束，面向**监管与消费者**。
 * 分装标签是**厨房贴纸**：配方名 / 每份克数 / 分装日期 / 建议食用期限 / 解冻提示，
 * 面向**当天分装的人**。两者的字段几乎不相交 ⇒ 分装标签**新建**，不复用 labeling ——
 * 把「厨房贴纸」塞进合规底稿会稀释 labeling 的合规语义（原文「复用 labeling 模板」的假设已实测证伪）。
 *
 * ## 四条不静默红线
 * 1. **不猜保质期**。「建议食用期限 = 分装日期 + 保质期」里的**保质期必须由调用方给**；
 *    缺失时 `useByDate = null` 并标 `shelfLifeMissing` —— 拿「冷冻一般能放 90 天」这类
 *    经验值填数，就是把猜想印在贴纸上，而用户会照着它决定还吃不吃。
 * 2. **克数守恒**。Σ(每袋克数) 必须 == 总量。末袋吸收舍入余量；若各袋都独立四舍五入，
 *    「分装后总量少了几克」这件事没有任何人会察觉。
 * 3. **末袋天数不足必须显式**。总量 30 天 ÷ 每袋 7 天 = 4 袋零 2 天 ⇒ 末袋只覆盖 2 天，
 *    标 `partial:true`。假装每袋都是整周，会让「最后一袋吃到哪天」算错。
 * 4. **总量为 0/负 ⇒ 报错，不返回空排期**。空排期会被读成「已经分好了」，
 *    而事实是「没有任何东西可分」。
 *
 * ## 与 multiPetPlan.js 的口径耦合（不 import，靠守卫钉住）
 * `TOTAL_DAYS_DEFAULT` 与 `multiPetPlan.PURCHASE_DAYS_DEFAULT` 是**同一个口径**
 * （30 天 ≈ 一个月）。本模块保持零依赖，故不 import 而是各自常量 + 由守卫断言两者相等 ——
 * 将来任一侧改动，守卫立刻判红，不会静默分叉。
 */

/* ================= 1. 常量 ================= */

/** 分装标签格式版本（改字段口径/排版时必须同步递增，便于回溯历史贴纸） */
export const PORTION_LABEL_VERSION = 1

/** 每袋默认覆盖天数：**按周分装**（对齐 feedingGuide.js 既有文案「按一周用量分装小袋」） */
export const PORTION_DAYS_DEFAULT = 7
/** 每袋天数上限（超过一季没有实际意义，只会让袋数与贴纸数失控） */
... (截断)
```

- 建议：MIRROR_TAMPERED → 可直接镜像覆盖源（源=基线）



---
## 汇总

| 技能 | 文件 | 类型 | 镜像独有 | 源独有 | 源独有被镜像包含 |
|---|---|---|---|---|---|
| junheng-bcs | SKILL.md | BOTH_CHANGED | 85 | 85 | 59 |
| junheng-core | SKILL.md | BOTH_CHANGED | 91 | 87 | 58 |
| junheng-nutrition | SKILL.md | BOTH_CHANGED | 97 | 96 | 67 |
| junheng-labeling | SKILL.md | BOTH_CHANGED | 221 | 221 | 156 |
| junheng-cost | SKILL.md | BOTH_CHANGED | 136 | 103 | 72 |
| junheng-feeding | SKILL.md | BOTH_CHANGED | 103 | 103 | 77 |
| junheng-pipeline | SKILL.md | BOTH_CHANGED | 96 | 96 | 69 |
| junheng-attainment | SKILL.md | BOTH_CHANGED | 111 | 111 | 76 |
| junheng-core | scripts/vendor/nutrition.js | MIRROR_TAMPERED | 2093 | 2093 | 1954 |
| junheng-core | scripts/vendor/labeling.js | MIRROR_TAMPERED | 429 | 429 | 385 |
| junheng-core | scripts/vendor/feedingGuide.js | MIRROR_TAMPERED | 1292 | 1292 | 1212 |
| junheng-core | scripts/vendor/multiPetPlan.js | MIRROR_TAMPERED | 348 | 348 | 316 |
| junheng-core | scripts/vendor/portionLabel.js | MIRROR_TAMPERED | 394 | 394 | 351 |