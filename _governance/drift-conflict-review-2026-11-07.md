# 镜像漂移冲突项 · 镜像侧独有编辑审阅稿

> 用途：下列 13 项漂移，镜像侧含有「源中没有的独有编辑」。若直接重同步（以源覆盖镜像），这些编辑将丢失。

> 请逐处决定：**回写源码**（保留镜像编辑）或 **丢弃**（以源覆盖镜像）。`+` 行为镜像独有行。


## [BOTH_CHANGED] junheng-bcs / SKILL.md
- 源：C:/Users/Administrator/WorkBuddy/2026-10-09-19-00-38/nutrition-agent-work/cli/skills\junheng-bcs\SKILL.md
- 镜像：C:/Users/Administrator/.workbuddy/skills\junheng-bcs\SKILL.md
- 镜像独有行数：85

```diff
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
| 2 | 用法或输入错误，命令未执行（如 `score` 给了 0 或 12） |
| 3 | 前置条件缺失（技能镜像未同步） |

## 拒答与替代路径

> 本节是**可机检**的边界契约（规范与判据见 `docs/技能边界与拒答契约_2026-10-13.md`）。
> 命中某一类时，按该类「话术」回复并给出「替代」路径；标「不适用」的类必须写明本技能层面的理由。

### R1 非犬猫物种
- **触发**：查询非犬猫物种的体况评分表。
- **话术**：本技能的 9 分制判据表只覆盖犬与猫，对其它物种不适用。
- **替代**：请咨询该物种的兽医；犬猫的逐分判定行与参考图本技能可照常给。

### R2 医疗诊断
- **触发**：要求确诊肥胖或给出减重方案。
- **话术**：体况评分是筛查工具，不是诊断；我不做确诊也不开减重方案。
- **替代**：临床肥胖确诊需兽医结合肌肉状况、体重趋势与体检；本技能负责列清复评周期与就医信号。

### R3 超出已收录法规体系
- **触发**：要求按未收录的评分制式（非 9 分制）出判定。
- **话术**：本技能只收录 9 分制判据，其它制式我无法换算给结论。
- **替代**：可用 9 分制判定行做参照；跨制式换算需另行确认口径。

### R4 数据缺口（`nodata`）
- **不适用**：本技能不消费配方数据，判据表为固定 9 行，不存在「缺数据无法判定」的情形。
```


## [BOTH_CHANGED] junheng-core / SKILL.md
- 源：C:/Users/Administrator/WorkBuddy/2026-10-09-19-00-38/nutrition-agent-work/cli/skills\junheng-core\SKILL.md
- 镜像：C:/Users/Administrator/.workbuddy/skills\junheng-core\SKILL.md
- 镜像独有行数：91

```diff
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
|---|---|
| 0 | 校验一致，或同步成功 |
| 1 | 检出**漂移**（跑一次同步即可修复），或同步后仍有漂移 |
| 2 | 用法 / 输入错误（未知选项、`--skills-dir` 缺参数） |
| 3 | **前置条件缺失**：计划里声明的**源文件**不在磁盘上（`SOURCE_MISSING`）—— 同步**也修不了**，须先补源 |

> **为什么 3 不并进 1**：漂移的下一步动作是「跑同步」，源缺的下一步动作是「去补仓库里的文件」。
> 两者混成一个码，调用方就只能靠 grep 日志分辨该重试还是该报缺件。

`--check` 给每条问题打 `code`，对症处理：`SOURCE_DRIFTED`（源变了 → 跑同步）、`MIRROR_TAMPERED`（镜像被改 → 改回源）、`BOTH_CHANGED`（两边都变 → 先定夺回写谁）、`CORE_REF_MISMATCH` / `CORE_MISSING`（核心版本不符 / 缺失 → 跑同步）、**`SOURCE_MISSING`（源文件不存在 → 退出码 **3**，先补源，同步救不了）**、其余 `MISSING_MANIFEST` / `BAD_MANIFEST` / `MISSING_ENTRY` / `MISSING_FILE` / `EXTRA_FILE`（目录未同步或清单不一致 → 修正后跑同步）。

## 拒答与替代路径

> 本节是**可机检**的边界契约（规范与判据见 `docs/技能边界与拒答契约_2026-10-13.md`）。
> 命中某一类时，按该类「话术」回复并给出「替代」路径；标「不适用」的类必须写明本技能层面的理由。

### R1 非犬猫物种
- **不适用**：本层不接收物种参数，物种适用性由调用方门面判定；本层只做源码只读镜像。

### R2 医疗诊断
- **不适用**：本层不产出面向用户的文本，诊断与拒答边界由各门面技能声明，本层不含判定逻辑。

### R3 超出已收录法规体系
- **触发**：要求本层提供未收录体系的限值条目。
- **话术**：本层只镜像 `src/lib/` 的既有条目，未收录的体系我这里也没有。
- **替代**：请查 `junheng-standards` 的收录清单；待 `src/lib/` 补录后重新同步即可。

### R4 数据缺口（`nodata`）
- **触发**：某模块或原料条目缺失，引用方报 `ERR_MODULE_NOT_FOUND`。
- **话术**：本层是只读镜像，缺条目时我不兜底，直接报错。
- **替代**：请跑 `sync-skills.mjs --check` 定位漂移并重新同步；不要手改镜像（会被判 `MIRROR_TAMPERED`）。
```


## [BOTH_CHANGED] junheng-nutrition / SKILL.md
- 源：C:/Users/Administrator/WorkBuddy/2026-10-09-19-00-38/nutrition-agent-work/cli/skills\junheng-nutrition\SKILL.md
- 镜像：C:/Users/Administrator/.workbuddy/skills\junheng-nutrition\SKILL.md
- 镜像独有行数：97

```diff
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
> 须由调用方提供现行标准的限值与依据 —— 不得由本技能代填（见 R3）。

## 失败处理（退出码）

| 退出码 | 含义 |
|--------|------|
| 0 | 成功。注意：**「算不出」也是 0** —— 请看 `ok` 与 `reason` |
| 1 | 内部错误（未预期异常） |
| 2 | 用法或输入错误，命令未执行 |
| 3 | 前置条件缺失（共享内核未同步） |

失败时 stdout 为空，stderr 是一行 JSON：`{"ok":false,...}`。`error.details[]` 逐条给出出错参数路径（数组错误定位到 `items[2].weight` 这一级）。

## 拒答与替代路径

> 本节是**可机检**的边界契约（规范与判据见 `docs/技能边界与拒答契约_2026-10-13.md`）。
> 命中某一类时，按该类「话术」回复并给出「替代」路径；标「不适用」的类必须写明本技能层面的理由。

### R1 非犬猫物种
- **触发**：询问非犬猫物种的配方营养结果或个体需求对照。
- **话术**：本技能的需求口径只覆盖犬与猫，对其它物种无法给出需求对照。
- **替代**：成分与配方数值仍可照算；需求对照请改用该物种的标准并咨询兽医营养师。

### R2 医疗诊断
- **触发**：要求判断疾病，或按治疗性饮食给出配方结论。
- **话术**：本技能只出营养数值，不做诊断也不开处方。
- **替代**：请咨询执业兽医；配方数值与干物质基换算本技能可直接给。

### R3 超出已收录法规体系
- **触发**：要求按未收录体系的需求标准做对照。
- **话术**：该体系的需求条目未收录，我不能给出它的对照结论。
- **替代**：已核对体系（如 GB 系列）可照常对照；待补录后重查即可。

### R4 数据缺口（`nodata`）
- **触发**：库缺该营养项（如赖氨酸、牛磺酸），或原料未收录。
- **话术**：该项进 `unknown` / `nodata` —— 无法判定，不等于达标也不等于未达标。
- **替代**：请补充原料实测值或换用有数据的原料；本技能会把缺项原样报出，不按 0 计。
```


## [BOTH_CHANGED] junheng-labeling / SKILL.md
- 源：C:/Users/Administrator/WorkBuddy/2026-10-09-19-00-38/nutrition-agent-work/cli/skills\junheng-labeling\SKILL.md
- 镜像：C:/Users/Administrator/.workbuddy/skills\junheng-labeling\SKILL.md
- 镜像独有行数：221

```diff
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
| `guaranteed` | 只取营养保证值表 |
| `ingredients-list` | 只取配料表 |
| `render` | 把底稿渲染成可直接粘贴的纯文本 |
| `coverage` | 查底稿覆盖率（哪些项有据可依、哪些缺数据） |
| `disclaimers` | 查必须随稿给出的声明清单 |
| `describe` | 输出机器可读的接口说明 |

**参数详表、输出字段表、可运行示例** → [详细接口参考](references/interface-reference.md)。

## 失败处理（退出码）

| 退出码 | 含义 |
|--------|------|
| 0 | 成功，结果在 stdout 的 JSON 里 |
| 1 | 内部错误（未预期异常） |
| 2 | 用法或输入错误，命令未执行 |
| 3 | 前置条件缺失（共享内核未同步） |

**形状校验（`exit 2` 的常见来源）**：`draft` / `guaranteed` / `ingredients-list` 会校验 `recipe`
是否为 `junheng-nutrition` 的**完整 data**；`render` / `coverage` 会校验 `draft` 是否为 `draft`
命令的**完整 data**。传「`ok:true` 但字段不全」的**瘦对象**会被就地拒绝并**点名缺失字段**，
不会崩进内核（2026-10-11 之前 `render` / `coverage` 缺这条守卫，会 `exit 1` 且只报
`Cannot read properties of undefined`，已修）。

**域内负结果不是错误**：配方没算成功（`recipe.ok === false`）或底稿没生成成功
（`draft.ok === false`）都返回 `exit 0`，由内核给出原因（`reason` / 「标签稿生成失败：…」），
**不要**当成参数错误反复重试。

## 拒答与替代路径

> 本节是**可机检**的边界契约（规范与判据见 `docs/技能边界与拒答契约_2026-10-13.md`）。
> 命中某一类时，按该类「话术」回复并给出「替代」路径；标「不适用」的类必须写明本技能层面的理由。

### R1 非犬猫物种
- **触发**：为犬猫以外的物种生成标签底稿。
- **话术**：本技能的标签项目与顺序按犬猫食品法规组织，对非犬猫物种不适用。
- **替代**：请改用该物种适用的标签法规；本技能对已收录原料的占比排序逻辑仍可参考。

### R2 医疗诊断
- **触发**：要求声明产品具有疗效、诊断或治疗作用。
- **话术**：标签底稿不承载任何诊断或治疗声明，我也不会为其生成这类表述。
- **替代**：请咨询兽医与法规人员；成分与限值部分本技能可以照常出稿。

### R3 超出已收录法规体系
- **触发**：要求按未收录的标签法规出稿。
- **话术**：该法规体系未收录在案，我不能生成它的项目与顺序。
- **替代**：可先出已收录体系（GB/T 31216-2014 / 31217-2014）的底稿作为参照骨架。

### R4 数据缺口（`nodata`）
- **触发**：库缺氨基酸等字段，无法判定该项是否合规。
- **话术**：该项进 `nodata` 段 —— 既不算达标也不算未达标。
- **替代**：请补充该原料的实测值；本技能会把 `nodata` 与 `risks[]` 一并报出，不省略。

<!-- i18n:en:begin -->

# Label Draft Generation (junheng-labeling)

## Purpose and scope

**What it does**: lay out recipe values as a label draft that follows the **regulated item order**, and give a per-item compliance conclusion.

**What it does not do**:

- **Not a final compliance verdict** — the output is a **draft**; reconcile every item against the current regulation text before submission.
- **Does not invent values** — all limits come from `standards.js` (clauses reconciled against GB/T 31216-2014 / 31217-2014).
- **Does not conclude on items without data** — items lacking library fields such as amino acids go into `nodata`, counted as **neither compliant nor non-compliant**.
- **Does not change the recipe** — this skill presents only; it will not adjust the recipe to meet limits.
- **Does not do OCR** — read label images with the appropriate vision capability.

## Honesty red lines

1. **A draft, not a final document.** Always relay `disclaimers`; never phrase the output as "already compliant".
2. **Unverified systems must be marked explicitly.** AAFCO values are not yet reconciled item by item against the official publication (`verified: false`).
3. **Not computable is not a pass.** `nodata` items must be reported verbatim, never omitted or treated as passing.
4. **Risk notes must be relayed.** `risks[]` lists why the draft "cannot be printed directly" (over-limit, missing data) — the part users most often overlook.
5. **Ingredient ordering is traceable.** Descending by share; for equal weights **keep the user's input order** (regulations say nothing about ties).

## Workflow (three steps, order is fixed)

| Step | Command | Input → output |
|---|------|------------|
| 1 | `junheng-nutrition recipe` | `items[]` → **recipe data** |
| 2 | `junheng-nutrition requirements` | `species` / `weightKg` → **req data** |
| 3 | **this skill's `draft`** | `{"recipe":…,"req":…}` → **draft data** |

After step 3 there are two branches: `render` / `coverage` take only step 3's `draft`; `guaranteed` /
`ingredients-list` take only steps 1-2's `recipe` + `req` (no `draft` needed). Neither branch re-runs the earlier steps.

**Intermediate data cannot be hand-made**: the `data` of steps 1-3 is part of the **shape contract** — `draft` validates
`recipe`'s `dmPercent` / `asFed.crude_protein` / `energy.meModified` / `lines[]`; `render` / `coverage` validate
`draft`'s `product` / `basis` / `guaranteed.rows` / `ingredients.items` / `risks[]`. A missing field is rejected
by name with `exit 2`, rather than producing a half draft.

> To run steps 1-3 (plus cost and feeding) in one go, use `run` from `junheng-pipeline`.

## Usage

Run `node scripts/cli.mjs <command> '<JSON args>'` in the skill root (or pass args via `--stdin` / a pipe;
`--help` and `<command> --help` show all commands and that command's parameter table).

> ⚠ Depends on the shared core `junheng-core`. If "source directory not found" appears, run `node scripts/sync-skills.mjs` **from the project root** `packages/nutrition-agent-work` — the skill directory is a read-only mirror and does not contain that script.

## Commands

| Command | Purpose |
|------|------|
| `draft` | Generate the full label draft (guaranteed analysis + ingredients + compliance + risks + disclaimers) |
| `guaranteed` | Return the guaranteed analysis table only |
| `ingredients-list` | Return the ingredient list only |
| `render` | Render the draft as paste-ready plain text |
| `coverage` | Report draft coverage (which items are sourced, which lack data) |
| `disclaimers` | Return the mandatory disclaimer list |
| `describe` | Emit the machine-readable interface description |

Parameter tables, output field tables and runnable examples → [interface reference](references/interface-reference.md).

## Failure handling (exit codes)

| Exit code | Meaning |
|--------|------|
| 0 | Success; the result is JSON on stdout |
| 1 | Internal error (unexpected exception) |
| 2 | Usage or input error; command not executed |
| 3 | Missing precondition (shared core not synced) |

**Shape validation (the usual source of `exit 2`)**: `draft` / `guaranteed` / `ingredients-list` check whether
`recipe` is the **complete data** of `junheng-nutrition`; `render` / `coverage` check whether `draft` is the
**complete data** of the `draft` command. A "skinny object" that is `ok:true` but missing fields is rejected
in place with the missing fields named, and never crashes into the core (before 2026-10-11 `render` / `coverage`
lacked this guard and would `exit 1` with only `Cannot read properties of undefined`, now fixed).

**In-domain negative results are not errors**: a recipe that did not compute (`recipe.ok === false`) or a draft
that was not produced (`draft.ok === false`) still returns `exit 0`, with the reason given by the core
(`reason` / "label draft generation failed: …"); do **not** treat them as input errors and retry.

## Refusal and alternatives

> This section is a machine-checkable boundary contract (spec and checks in `docs/技能边界与拒答契约_2026-10-13.md`).
> When a class is hit, reply with that class's response and give the alternative path.

### R1 Non-dog/cat species
- **Trigger**: generating a label draft for a species other than dog or cat.
- **Response**: this skill's label items and order follow dog and cat food regulations, and do not apply to non-dog/cat species.
- **Alternative**: switch to the label regulation applicable to that species; the descending-by-weight ordering logic still works for collected ingredients.

### R2 Medical diagnosis
- **Trigger**: asking the label to state efficacy, diagnosis or treatment.
- **Response**: a label draft carries no diagnostic or therapeutic claim, and I will not generate such wording.
- **Alternative**: consult a veterinarian and a regulatory specialist; the ingredient and limit sections can still be drafted here.

### R3 Beyond the collected regulatory systems
- **Trigger**: asking for a draft under a label regulation that is not collected.
- **Response**: that regulatory system is not collected, so I cannot generate its items and order.
- **Alternative**: a draft under a collected system (GB/T 31216-2014 / 31217-2014) can serve as a reference skeleton.

### R4 Data gap (`nodata`)
- **Trigger**: the library lacks fields such as amino acids, so compliance of that item cannot be judged.
- **Response**: that item goes into the `nodata` section — neither compliant nor non-compliant.
- **Alternative**: supply the measured value for that ingredient; `nodata` and `risks[]` are reported together and never omitted.

<!-- i18n:en:end -->
```


## [BOTH_CHANGED] junheng-cost / SKILL.md
- 源：C:/Users/Administrator/WorkBuddy/2026-10-09-19-00-38/nutrition-agent-work/cli/skills\junheng-cost\SKILL.md
- 镜像：C:/Users/Administrator/.workbuddy/skills\junheng-cost\SKILL.md
- 镜像独有行数：136

```diff
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

## 工作流（两步，顺序不可颠倒）

| 步 | 命令 | 输入 → 输出 |
|----|------|-------------|
| **第 1 步** | `lines` | 配方 `items[{name 或 code, weight(克)}]` → **成本行 `data.lines[]`**（另含 `totalWeight` / `missingPrice[]` / `unknown[]`） |
| **第 2 步** | 成本命令**四选一** | 成本行 `lines[]` + 该口径的参数 → 单位成本（元/kg、元/支） |

第 2 步四选一：`sheet`（通用/烘焙粮，按批次数+克重）、`freeze-dry`（冻干，按投料→成品）、`cat-stick`（猫条，按规格）、`by-mode`（用 `mode` 切换的**统一入口**，参数是四者的并集）。

**中间产物形状契约** —— 成本行：
`{ code, name, unit:'kg', ratio(0~1), unitPrice(¥/kg), yieldRate }`。

第 2 步的 `lines` 必须**原样传第 1 步返回的 `data.lines`**（不要手捏；缺 `ratio`/`unitPrice` 会算错且不报错）。串联写法与坑见详参。

## 用法

在技能根目录下执行：

```
node scripts/cli.mjs <命令> '<JSON 参数>'
node scripts/cli.mjs <命令> --stdin
node scripts/cli.mjs --help
node scripts/cli.mjs <命令> --help
```

> ⚠ 依赖共享内核 `junheng-core`。报「找不到源码目录」时，到项目根 `packages/nutrition-agent-work` 跑 `node scripts/sync-skills.mjs`——技能目录是只读镜像，不含该脚本。

## 命令一览

| 命令 | 用途 |
|------|------|
| `lines` | 把配方（原料+重量）换算成成本行（**其它成本命令的前置**） |
| `modes` | 列出可用口径（id 用下划线，如 `freeze_dry`）与各类配置 |
| `sheet` | 通用成本表（需 `batchCount` + `gramPerBag`，或 `yieldKg`） |
| `by-mode` | 按口径 id 算成本（`general` / `freeze_dry` / `cat_stick`） |
| `freeze-dry` | 冻干成本（投料 → 成品，五项加工费 元/吨） |
| `cat-stick` | 猫条成本（按规格，含车间加工单价与损耗） |
| `format` | 成本数值格式化工具（与界面口径一致） |
| `describe` | 输出机器可读的接口说明 |

**参数详表、输出字段表、可运行示例、传参与串联注意** → [详细接口参考](references/interface-reference.md)。

## 失败处理（退出码）

| 退出码 | 含义 |
|--------|------|
| 0 | 成功。注意：**「算不出」也是 0** —— 请看返回里的 `ok:false` 与 `reason` |
| 1 | 内部错误（未预期异常） |
| 2 | 用法或输入错误，命令未执行 |
| 3 | 前置条件缺失（共享内核未同步） |

## 拒答与替代路径

> 本节是**可机检**的边界契约（规范与判据见 `docs/技能边界与拒答契约_2026-10-13.md`）。
> 命中某一类时，按该类「话术」回复并给出「替代」路径；标「不适用」的类必须写明本技能层面的理由。

### R1 非犬猫物种
- **触发**：为非犬猫产品线计算成本或套用其它物种口径。
- **话术**：本技能的成本口径按本项目犬猫产品线定义，对其它物种不做适配判断。
- **替代**：成本算术（费项摊到单位）本身通用；物种适配请另行确认后再套用。

### R2 医疗诊断
- **触发**：要求以成本结果做医疗、疗效或安全性判断。
- **话术**：本技能只做成本算术，不含诊断也不含疗效结论。
- **替代**：请咨询兽医或产品负责人；成本表与口径配置本技能可直接出。

### R3 超出已收录法规体系
- **触发**：要求按未收录的加工口径或税费体系摊费。
- **话术**：该口径未收录，我不能按它摊费。
- **替代**：可用已收录口径（`general` / `freeze_dry` / `cat_stick`）；新口径需先登记再算。

### R4 数据缺口（`nodata`）
- **触发**：原料库中该原料没有价格。
- **话术**：无价原料按 0 计入并列入 `missingPrice`，这个 0 不是真实成本。
- **替代**：请补录该原料价格；本技能会把缺价清单原样报出并提示。
```


## [BOTH_CHANGED] junheng-feeding / SKILL.md
- 源：C:/Users/Administrator/WorkBuddy/2026-10-09-19-00-38/nutrition-agent-work/cli/skills\junheng-feeding\SKILL.md
- 镜像：C:/Users/Administrator/.workbuddy/skills\junheng-feeding\SKILL.md
- 镜像独有行数：103

```diff
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
| `bcs-scale` | 查 9 分制判据表与分组（**须指定 species**：犬 4~5 分为理想、猫仅 5 分） |
| `ideal-weight` | 由当前体重与体况评分估算理想体重 |
| `life-stage` | 判定生命阶段与餐次建议 |
| `transition` | 换粮过渡计划（默认 7 天） |
| `monitoring` | 监测计划（按生命阶段与体况策略） |
| `vet-signals` | 查需要就医的信号清单 |
| `describe` | 输出机器可读的接口说明 |

**参数详表、输出字段表、可运行示例** → [详细接口参考](references/interface-reference.md)。

## 失败处理（退出码）

| 退出码 | 含义 |
|--------|------|
| 0 | 成功。注意：**「算不出」也是 0** —— 请看 `ok` 与原因字段 |
| 1 | 内部错误（未预期异常） |
| 2 | 用法或输入错误，命令未执行（如 `score` 给了 0 或 12） |
| 3 | 前置条件缺失（共享内核未同步） |

## 拒答与替代路径

> 本节是**可机检**的边界契约（规范与判据见 `docs/技能边界与拒答契约_2026-10-13.md`）。
> 命中某一类时，按该类「话术」回复并给出「替代」路径；标「不适用」的类必须写明本技能层面的理由。

### R1 非犬猫物种
- **触发**：为非犬猫物种制定喂食计划。
- **话术**：本技能的 BCS 判定表与能量口径仅覆盖犬与猫。
- **替代**：请咨询该物种的兽医；猫犬的喂食量计算本技能可照常给。

### R2 医疗诊断
- **触发**：询问疾病、要不要就医以外的临床判断（如"是不是肾衰"）。
- **话术**：体况评分是筛查工具，不是诊断；我不能给出疾病判断。
- **替代**：出现异常体况或食欲变化时请就医；本技能负责把复评周期与预警信号列清。

### R3 超出已收录法规体系
- **触发**：要求按未收录体系的能量或体况标准出结果。
- **话术**：该体系未收录，我不能按它给出判定。
- **替代**：本技能的能量计算走本项目已核对的能量口径，可先出这一版。

### R4 数据缺口（`nodata`）
- **触发**：配方缺少实测能量或原料成分，无法算出喂食量。
- **话术**：能量为理论计算值，缺少配方实测能量时我无法给出可靠的喂食克数。
- **替代**：请先用配方营养计算补齐该配方的能量；本技能拿到结果后会给出喂食区间。
```


## [BOTH_CHANGED] junheng-pipeline / SKILL.md
- 源：C:/Users/Administrator/WorkBuddy/2026-10-09-19-00-38/nutrition-agent-work/cli/skills\junheng-pipeline\SKILL.md
- 镜像：C:/Users/Administrator/.workbuddy/skills\junheng-pipeline\SKILL.md
- 镜像独有行数：96

```diff
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
| 3 | 前置条件缺失（共享内核未同步） |

## 与单技能的关系（该用哪个）

| 场景 | 用什么 |
|---|---|
| 只算配方营养 | `junheng-nutrition recipe` |
| 只出标签稿 | `junheng-labeling draft` |
| 完整评估（多步） | **本门面 `run`** |
| 多宠 + 采购清单 + 分装标签 | **本门面 `run-multi`**（只想单独做一段时用 `junheng-feeding` 的 `plan-multi` / `portion-label`） |
| 想在 shell 里把某一步的结果接到下一步 | 任一技能 + `--as <参数名>`（见详参） |

## 拒答与替代路径

> 本节是**可机检**的边界契约（规范与判据见 `docs/技能边界与拒答契约_2026-10-13.md`）。
> 命中某一类时，按该类「话术」回复并给出「替代」路径；标「不适用」的类必须写明本技能层面的理由。

### R1 非犬猫物种
- **触发**：为非犬猫物种跑全套管道。
- **话术**：管道内的需求与达标口径只覆盖犬与猫，对其它物种不给结论。
- **替代**：请分步调用该物种的对应能力；犬猫配方可照常跑全套步骤。

### R2 医疗诊断
- **触发**：要求管道给出诊断或治疗性配方结论。
- **话术**：管道只搬运既有计算，不含诊断，也不下「这个配方能卖」的结论。
- **替代**：请咨询执业兽医；各步数值与合规段本管道会照常串联输出。

### R3 超出已收录法规体系
- **触发**：要求按未收录体系跑达标或标签步骤。
- **话术**：该体系未收录时对应步骤会标 `skipped` 并给出 `reason`，不会编造结论。
- **替代**：可用已收录体系跑到哪算哪；该体系补录后重跑即可。

### R4 数据缺口（`nodata`）
- **触发**：上游数据缺口导致某一步无法完成。
- **话术**：缺数据时该步标 `error` / `skipped` 并给出 `reason`，我不静默跳过。
- **替代**：请先补齐该步所需输入；补齐后重跑单步即可。
```


## [BOTH_CHANGED] junheng-attainment / SKILL.md
- 源：C:/Users/Administrator/WorkBuddy/2026-10-09-19-00-38/nutrition-agent-work/cli/skills\junheng-attainment\SKILL.md
- 镜像：C:/Users/Administrator/.workbuddy/skills\junheng-attainment\SKILL.md
- 镜像独有行数：111

```diff
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
| `describe` | 输出机器可读的接口说明 |

**参数详表、输出字段表、可运行示例** → [详细接口参考](references/interface-reference.md)。

## 失败处理（退出码）

| 退出码 | 含义 |
|--------|------|
| 0 | 评估执行完毕。**配方未达标也是 0** —— 请看 `summary` 与 `gaps` |
| 1 | 内部错误（未预期异常） |
| 2 | 用法或输入错误，命令未执行 |
| 3 | 前置条件缺失（共享内核未同步） |

## 与相关技能的分工（该用哪个）

| 场景 | 用什么 |
|---|---|
| 只想知道**营养组成**（蛋白/脂肪/钙磷比/能量） | `junheng-nutrition recipe` |
| 想知道**有哪些限值**、条款原文 | `junheng-standards resolve` / `clause` |
| **想知道达不达标、差在哪** | **本技能 `assess`** |
| 手里**已有** `recipe` 与 `req` 两个对象，只要原始对照表 | `junheng-nutrition evaluate` |
| 想要**全套**（营养 + 目标 + 标签 + 成本 + 喂食） | `junheng-pipeline run` |

> ★ 易混点：`junheng-nutrition evaluate` 需要**两个上游大对象**（`recipe` + `req`），
> 且明说「不替用户下是否达标的结论」；本技能 `assess` 只要**配方 + 画像**，
> 上游对象由它自己构造 —— 这是**一步到位版**，也是界面「⑤ 达标评估」的命令行等价物。

## 拒答与替代路径

> 本节是**可机检**的边界契约（规范与判据见 `docs/技能边界与拒答契约_2026-10-13.md`）。
> 命中某一类时，按该类「话术」回复并给出「替代」路径；标「不适用」的类必须写明本技能层面的理由。

### R1 非犬猫物种
- **触发**：目标对象不是犬或猫。
- **话术**：本技能的达标口径按犬猫目标画像定义，对其它物种无法给出结论。
- **替代**：请改用该物种的标准；犬猫的缺口清单与配比建议本技能可照常出。

### R2 医疗诊断
- **触发**：要求判断疾病，或据结果给出治疗性配方结论。
- **话术**：本技能只给逐项达标结论与缺口，不做诊断。
- **替代**：请咨询执业兽医；配方是否达标的逐项对照本技能可照常给。

### R3 超出已收录法规体系
- **触发**：要求按未收录体系的目标口径判定。
- **话术**：该口径未收录，我不能按它给出达标结论。
- **替代**：可用已收录口径先出这一版（市场 × 物种 × 阶段，见 `targets`）。

### R4 数据缺口（`nodata`）
- **触发**：库缺数据导致该项无法判定。
- **话术**：该项判为 `nodata` / `low` —— 无法判定，不等于未达标。
- **替代**：请补齐缺失数据；本技能会原样报 `nodata`，不谎报未达标。
```


## [MIRROR_TAMPERED] junheng-core / scripts/vendor/nutrition.js
- 源：C:/Users/Administrator/WorkBuddy/2026-10-09-19-00-38/nutrition-agent-work/src/lib\nutrition.js
- 镜像：C:/Users/Administrator/.workbuddy/skills\junheng-core\scripts/vendor\nutrition.js
- 镜像独有行数：2093

```diff
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
function dataMarks(it) {
  const st = ingredientDataStatus(it)
  return {
    _dataStatus: st.status,
    _valueFields: st.valueFields,
    _zeroFields: st.zeroFields,
    _missingFields: st.missingFields,
    _zero: st.suspectFields.length > 0,
    _hasData: st.hasValue,
  }
}

/** 运行时派生字段全集（持久化/导出时必须剔除，见 toRows / stripMarks） */
export const RUNTIME_MARKS = [
  '_norm', '_bare', '_normBare',
  '_dataStatus', '_valueFields', '_zeroFields', '_missingFields', '_zero', '_hasData',
]

/** 就地刷新一条原料的全部派生字段（改名 / 改营养值之后必须调用） */
function refreshMarks(it) {
  Object.assign(it, {
    _norm: normName(it.name),
    _bare: stripBrand(it.name),
    _normBare: normName(stripBrand(it.name)),
    ...dataMarks(it),
  })
  return it
}

const DB = RAW_DB.map((it) => ({
  ...it,
  _norm: normName(it.name),
  _bare: stripBrand(it.name),
  _normBare: normName(stripBrand(it.name)),
  ...dataMarks(it),
}))

export const INGREDIENT_DB = DB

/**
 * 原料库当前真实条数（唯一口径）。
 * 必须用函数实时读取：DB 会被 hydrateDb 用「数据源回读结果」原地重建，
 * 任何在模块加载时算好的快照常量（如旧的 dbSize）都会永远停在种子的 457 条，
 * 增删改/识别入库之后显示的条数就是错的。
 */
export const dbCount = () => DB.length

const BY_NORM = new Map()
for (const it of DB) if (!BY_NORM.has(it._norm)) BY_NORM.set(it._norm, it)
const BY_NORM_BARE = new Map()
for (const it of DB) if (!BY_NORM_BARE.has(it._normBare)) BY_NORM_BARE.set(it._normBare, it)
const BY_CODE = new Map()
for (const it of DB) if (it.code && !BY_CODE.has(it.code)) BY_CODE.set(String(it.code).trim(), it)

/** 给条目补齐运行时派生字段（_norm / _bare / 数据质量标记等） */
function decorate(it) {
  return {
    ...it,
    _norm: normName(it.name),
    _bare: stripBrand(it.name),
    _normBare: normName(stripBrand(it.name)),
    ...dataMarks(it),
  }
}

function rebuildIndex() {
  BY_NORM.clear()
  BY_NORM_BARE.clear()
  BY_CODE.clear()
  for (const it of DB) {
    if (!BY_NORM.has(it._norm)) BY_NORM.set(it._norm, it)
    if (!BY_NORM_BARE.has(it._normBare)) BY_NORM_BARE.set(it._normBare, it)
    if (it.code && !BY_CODE.has(String(it.code).trim())) BY_CODE.set(String(it.code).trim(), it)
  }
}

/**
 * 用「数据源读回的行」重建内存库与索引（应用启动 / 每次写入后回读刷新）。
 * 这是唯一允许整体替换 DB 的入口，替换内容来自持久化数据源，而非种子常量。
 */
export function hydrateDb(rows = []) {
  DB.length = 0
  for (const raw of rows) DB.push(decorate(raw))
  rebuildIndex()
  return DB.length
}

/**
 * 剔除运行时派生字段（唯一实现在这里，别在别处手写解构 —— 漏掉新字段会把
 * 派生数据持久化进 IndexedDB / 导出文件 / 备份包）。
 */
export function stripMarks(row) {
  const out = {}
  for (const [k, v] of Object.entries(row || {})) {
    if (!RUNTIME_MARKS.includes(k)) out[k] = v
  }
  return out
}

/** 导出当前内存库为可持久化的纯数据行（剔除派生字段，保留 id） */
export function toRows() {
  return DB.map((it) => stripMarks(it))
}

/** 按 id / 编码 / 名称定位内存条目（id 优先） */
export function findRowByKey(key) {
  const k = String(key ?? '').trim()
  if (!k) return null
  const byId = DB.find((x) => x.id && x.id === k)
  if (byId) return byId
  const byCode = findIngredientByCode(k)
  if (byCode) return byCode
  const n = normName(k)
  return DB.find((x) => x._norm === n || x._normBare === n) || null
}

/** 按编码精确查找。返回数据库条目或 null */
export function findIngredientByCode(code) {
  const c = String(code ?? '').trim()
  if (!c) return null
  return BY_CODE.get(c) || null
}

/**
 * 按编码查出**全部**命中条目。
 * 库内存在「同一编码对应多条原料」的历史遗留情况（76 组重复编码），
 * 因此按编号替换时必须先看这里返回了几条，绝不能默认取第一条。
 */
export function findAllByCode(code) {
  const c = String(code ?? '').trim()
  if (!c) return []
  return DB.filter((x) => String(x.code || '').trim() === c)
}

/** 按规范化名称查出全部命中条目（同名多条时供人工选择） */
export function findAllByName(name) {
  const n = normName(name)
  if (!n) return []
  return DB.filter((x) => x._norm === n || x._normBare === n)
}

/* ---------------- 原料库编辑 / 导入 ---------------- */

/**
 * 应用原料营养覆盖：把用户编辑的营养值合并进 DB 条目（原地修改，幂等）。
 * map: { [code|name]: { crude_protein, calcium, price, ... } }
 */
export function applyIngredientOverrides(map = {}) {
  for (const [key, patch] of Object.entries(map)) {
    if (!patch) continue
    let target = BY_CODE.get(String(key).trim())
    if (!target) target = BY_NORM.get(normName(key)) || BY_NORM_BARE.get(normName(stripBrand(key)))
    if (!target) continue
    for (const [k, v] of Object.entries(patch)) {
      if (v === null || v === undefined) continue
      target[k] = v
    }
    // 刷新派生字段
    refreshMarks(target)
  }
}

/**
 * 批量导入/新增原料条目。items: [{ name, code, category, lifeStage, price, ...营养 }]
 * 已存在（同名或同编码）则覆盖，否则追加。返回 { added, updated }。
 */
export function importIngredients(items = []) {
  let added = 0
  let updated = 0
  for (const raw of items) {
    if (!raw || !raw.name) continue
    const existing = raw.code ? findIngredientByCode(raw.code) : findIngredient(raw.name)
    const base = existing || {}
    const merged = {
      // id 为持久化主键：已有条目沿用原 id，新条目留空由仓储层分配
      id: raw.id || base.id || undefined,
      ...base,
      category: raw.category || base.category || '其他/待定',
      name: raw.name || base.name,
      lifeStage: raw.lifeStage || base.lifeStage || null,
      code: raw.code || base.code || '',
      price: raw.price != null ? Number(raw.price) : (base.price != null ? base.price : 0),
    }
    for (const [k] of NUTRIENT_FIELDS) {
      merged[k] = raw[k] != null ? Number(raw[k]) : (base[k] != null ? base[k] : null)
    }
    if (existing) {
      Object.assign(existing, merged)
      refreshMarks(existing)
      if (existing.code && !BY_CODE.has(existing.code)) BY_CODE.set(existing.code, existing)
      updated++
    } else {
      const it = refreshMarks({ ...merged })
      DB.push(it)
      if (!BY_NORM.has(it._norm)) BY_NORM.set(it._norm, it)
      if (!BY_NORM_BARE.has(it._normBare)) BY_NORM_BARE.set(it._normBare, it)
      if (it.code && !BY_CODE.has(it.code)) BY_CODE.set(it.code, it)
      added++
    }
  }
  return { added, updated }
}

/**
 * 删除原料条目。按编码或名称定位（编码优先）。
 * 返回 { deleted: bool, name, data }，其中 data 为完整可恢复快照（用于撤销/回收站恢复）。
 */
export function deleteIngredient(key) {
  const c = String(key ?? '').trim()
  if (!c) return { deleted: false }
  let idx = -1
  let it = null
  // 唯一标识 id 优先（持久化后的主键），其次编码，最后名称
  it = DB.find((x) => x.id && x.id === c) || null
  if (it) idx = DB.indexOf(it)
  if (idx < 0) {
    it = findIngredientByCode(c)
    if (it) idx = DB.indexOf(it)
  }
  if (idx < 0) {
    const n = normName(c)
    it = DB.find((x) => x._norm === n || x._normBare === n)
    if (it) idx = DB.indexOf(it)
  }
  if (idx < 0) return { deleted: false }
  const [removed] = DB.splice(idx, 1)
  // 清理索引
  if (removed.code) BY_CODE.delete(String(removed.code).trim())
  if (BY_NORM.get(removed._norm) === removed) BY_NORM.delete(removed._norm)
  if (BY_NORM_BARE.get(removed._normBare) === removed) BY_NORM_BARE.delete(removed._normBare)
  // 返回可恢复快照（剔除运行时派生字段）
  return { deleted: true, name: removed.name, data: stripMarks(removed) }
}

/**
 * 恢复（重新插入）一条原料条目。data 为 deleteIngredient 返回的完整数据快照。
 * 已存在同编码/同名则跳过，避免重复。返回 { restored: bool }。
 */
export function restoreIngredient(data) {
  if (!data || !data.name) return { restored: false }
  const existing = (data.code && findIngredientByCode(data.code)) || findIngredient(data.name)
  if (existing) return { restored: false }
  const merged = {
    category: data.category || '其他/待定',
    name: data.name,
    lifeStage: data.lifeStage || null,
    code: data.code || '',
    price: data.price != null ? Number(data.price) : 0,
  }
  for (const [k] of NUTRIENT_FIELDS) {
    merged[k] = data[k] != null ? Number(data[k]) : null
  }
  const it = refreshMarks({ ...merged })
  DB.push(it)
  if (!BY_NORM.has(it._norm)) BY_NORM.set(it._norm, it)
  if (!BY_NORM_BARE.has(it._normBare)) BY_NORM_BARE.set(it._normBare, it)
  if (it.code && !BY_CODE.has(it.code)) BY_CODE.set(it.code, it)
  return { restored: true, name: it.name }
}

/**
 * 数字拼接误配检测：当 shorter 是 longer 的前缀，且「拼接处」两侧都是数字时，
 * 视为不同的编号条目（如 维生素b1 与 维生素b12），不应互相当作匹配。
 * 数字属于身份标识，不是描述性后缀——反例：碳酸钙→碳酸钙粉、鸡大胸→鸡大胸(冷冻) 合法。
 * 全库实测（2026-10-25，286 条）不存在库内数字拼接配对，本守卫只拦截「查询侧多一个尾随数字」的误配。
 */
function isDigitJoinMismatch(shorter, longer) {
  if (!longer.startsWith(shorter)) return false
  const rest = longer.slice(shorter.length)
  if (!rest) return false
  return /\d/.test(shorter.slice(-1)) && /\d/.test(rest.slice(0, 1))
}

/**
 * 子串型数字拼接误配：n 作为子串出现在 h 中（it._norm.includes(n) 分支），
 * 若拼接边界两侧都是数字则视为不同编号条目而拒配。
 */
function isDigitJoinSubstring(h, n) {
  const idx = h.indexOf(n)
  if (idx < 0) return false
  const before = idx > 0 ? h[idx - 1] : ''
  const after = idx + n.length < h.length ? h[idx + n.length] : ''
  const lastN = n.slice(-1)
  const firstN = n.slice(0, 1)
  return (/\d/.test(lastN) && /\d/.test(after)) || (/\d/.test(firstN) && /\d/.test(before))
}

/** 名称查找：精确 → 去品牌括号 → 前缀包含 → 编码。返回数据库条目或 null */
export function findIngredient(name) {
  const n = normName(name)
  if (!n) return null
  if (BY_NORM.has(n)) return BY_NORM.get(n)
  if (BY_NORM_BARE.has(n)) return BY_NORM_BARE.get(n)
  // 方向一：n 以 it._norm 开头（查询是条目的「名称+描述性后缀」），排除数字拼接误配
  let hit = DB.find((it) => n.startsWith(it._norm) && !isDigitJoinMismatch(it._norm, n))
  if (hit) return hit
  hit = DB.find((it) => it._normBare === n) || null
  if (hit) return hit
  // 方向二：it._norm 包含 n（条目以 n 开头，或 n 嵌于条目中部），排除数字拼接误配
  hit = DB.find((it) => it._norm.includes(n) && n.length >= 2 && !isDigitJoinSubstring(it._norm, n)) || null
  if (hit) return hit
  // 兜底：按编码查找（去掉前导零后）
  const byCode = findIngredientByCode(n.replace(/^0+/, ''))
  return byCode || null
}

/** 模糊搜索（打分排序），供原料选择器使用 */
export function searchIngredients(query, limit = 30) {
  const raw = String(query || '').trim()
  const n = normName(raw)
  if (!n) return DB.slice(0, limit)
  // 纯数字（≥3 位）按「原料编号」检索：编号即身份，命中优先级高于名称相似度。
  // 这样「01010001」能直接找到鸡大胸，也便于区分同名不同款（如「鸡大胸」与「熟鸡大胸」）。
  const asCode = /^\d{3,}$/.test(raw)
  const scored = []
  for (const it of DB) {
    let s = 0
    if (asCode) {
      const code = String(it.code || '').trim()
      if (code && code === raw) s = 130
      else if (code && code.startsWith(raw)) s = 105
      else if (code && code.includes(raw)) s = 85
    }
    if (!s) {
      if (it._norm === n) s = 100
      else if (it._normBare === n) s = 95
      else if (it._normBare.startsWith(n) || it._norm.startsWith(n)) s = 80
      else if (it._normBare.includes(n) || it._norm.includes(n)) s = 60
    }
    if (s > 0) scored.push({ it, s: s + (it._zero ? 0 : 2) }) // 有数据的略靠前
  }
  scored.sort((a, b) => b.s - a.s)
  return scored.slice(0, limit).map((x) => x.it)
}

/* ---------------- 2. 配方营养计算 ---------------- */

/**
 * 解析配方文本为 [{name, weight}]。
 * 支持三种原料引用格式（可混用）：
... (截断，完整见本地 diff)
```


## [MIRROR_TAMPERED] junheng-core / scripts/vendor/labeling.js
- 源：C:/Users/Administrator/WorkBuddy/2026-10-09-19-00-38/nutrition-agent-work/src/lib\labeling.js
- 镜像：C:/Users/Administrator/.workbuddy/skills\junheng-core\scripts/vendor\labeling.js
- 镜像独有行数：429

```diff
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
  if (!recipe?.computed) return { items: [], totalShare: 0, needsReview: [] }

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
  if (!recipe?.computed || !req) {
    return {
      computed: false,
      reason: !recipe?.computed ? '配方未计算成功（computeRecipe 返回空）' : '缺少营养需求对象（req）',
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
    computed: true,
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
      stageLabel: stage === 'growth' ? '生长期' : '成年期',
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
  if (!draft?.computed) return `标签稿生成失败：${draft?.reason || '未知原因'}`
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
... (截断，完整见本地 diff)
```


## [MIRROR_TAMPERED] junheng-core / scripts/vendor/feedingGuide.js
- 源：C:/Users/Administrator/WorkBuddy/2026-10-09-19-00-38/nutrition-agent-work/src/lib\feedingGuide.js
- 镜像：C:/Users/Administrator/.workbuddy/skills\junheng-core\scripts/vendor\feedingGuide.js
- 镜像独有行数：1292

```diff
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
    score: 1, label: '极度消瘦', group: 'thin',
    touch: '肋骨、腰椎、骨盆明显可见，无体脂，肌肉量显著下降',
    energyAdjPercent: 25, vetRequired: true,
  },
  {
    score: 2, label: '明显偏瘦', group: 'thin',
    touch: '肋骨易见、无体脂，腰椎与骨盆突出',
    energyAdjPercent: 20, vetRequired: true,
  },
  {
    score: 3, label: '偏瘦', group: 'thin',
    touch: '肋骨易触及、几乎无体脂覆盖，腰线明显凹陷',
    energyAdjPercent: 10, vetRequired: false,
  },
  {
    score: 4, label: '略瘦', group: 'ideal',
    touch: '肋骨易触及、有薄层体脂，俯视有明显腰线',
    energyAdjPercent: 0, vetRequired: false,
    /* ⚠ 这一行的 group / energyAdjPercent 是**犬口径**：犬 4 分是理想。
       猫的 4 分**不是**理想（猫理想只有 5 分），但本表的 label/group 无法按物种分叉
       —— 表是全局一份。要按物种取值，唯一入口是 `bcsGroupFor()` / `bcsPolicy()`；
       直接读本表判物种就会把猫 4 分判成「理想 + 维持量」。 */
  },
  {
    score: 5, label: '理想', group: 'ideal',
    touch: '肋骨可触及但不显见，腰线清晰，腹部上提',
    energyAdjPercent: 0, vetRequired: false,
  },
  {
    score: 6, label: '略胖', group: 'over',
    touch: '肋骨需轻压才触及，腰线不明显，腹部略有下坠',
    energyAdjPercent: -10, vetRequired: false,
  },
  {
    score: 7, label: '偏胖', group: 'over',
    touch: '肋骨需重压才触及，腰线几乎不可见，腹部圆',
    energyAdjPercent: -20, vetRequired: false,
    /* ⚠ 7 分落在「临床肥胖筛查区」（7~9）内：它不强制必须先就医（那还是 8 分起），
       但按 APOP/AAHA 口径应触发一次以肥胖为目标的兽医评估。以前漏了这一档。 */
    screeningZone: true,
  },
  {
    score: 8, label: '肥胖', group: 'obese',
    touch: '肋骨难以触及，腰线消失，腹部明显下垂、活动减少',
    energyAdjPercent: -30, vetRequired: true, screeningZone: true,
  },
  {
    score: 9, label: '严重肥胖', group: 'obese',
    touch: '肋骨不可触及，大量脂肪堆积，腹部膨大下垂',
    energyAdjPercent: -40, vetRequired: true, screeningZone: true,
  },
]

export const BCS_GROUPS = {
  thin: { label: '偏瘦', range: [1, 3] },
  /* ⚠ `range` 是**犬口径**（犬 4~5 分理想）。猫只有 5 分理想，所以
     「4 分属不属于理想」**不能**用本表的 range 判断，必须用
     `idealScoresFor(species)` / `bcsGroupFor(species, score)`。 */
  ideal: { label: '理想', range: [4, 5] },
  over: { label: '偏胖', range: [6, 7] },
  obese: { label: '肥胖', range: [8, 9] },
}

/**
 * 各档「怎么看」的一句话 —— 界面参考图与导出文档**共用同一份文案**。
 * 判据只有两条：侧视看腹部上提、俯视看腰线内收；写在这里避免两处各写一套而分叉。
 */
export const BCS_VIEW_HINT = {
  thin: '侧视：腹部明显上提，肋骨与腰椎、骨盆可见；俯视：腰部内收成明显沙漏形',
  ideal: '侧视：腹部轻度上提，肋骨能摸到但不突出；俯视：腰部在肋骨后轻微内收',
  over: '侧视：腹部无明显上提甚至下垂；俯视：腰部内收消失，躯干成直筒或向外鼓',
  obese: '侧视：腹部明显下垂、腰线完全消失；俯视：躯干整体外鼓呈椭圆形',
}

/** 体况自检的两步法（不看图也能做，长毛动物必须靠触摸） */
export const BCS_SELFTEST = [
  '第一步·触摸：双手拇指沿脊柱两侧、其余手指贴着肋骨滑动，判断肋骨上覆盖的脂肪厚度',
  '第二步·俯视：从正上方看，肋骨后方应有可见的腰部内收；看不到内收即为偏胖',
  '第三步·侧视：从侧面看，肋骨后方到后腿之间应有腹部上提；下垂平直即为偏胖',
  '长毛动物（长毛猫、萨摩耶、松狮等）腰线会被毛量掩盖，必须以触摸肋骨与腰椎为准',
]

/**
 * 安全的体重变化速度（每周占当前体重的百分比）。
 * 依据：AAHA 2021《Nutrition and Weight Management Guidelines for Dogs and Cats》及减重共识
 *   · 犬减重 1%~2%/周；猫减重 0.5%~1%/周
 *   · 增重不超过 2%/周（更快的增量基本都是脂肪）
 * ⚠ 以前犬猫统一写「0.5%~1%」—— 那是**猫**的速度：对犬过于保守（拖长疗程、掉肌肉），
 *   对猫又漏掉了「更快会诱发肝脂肪沉积（hepatic lipidosis，可致命）」这个风险提示。
 */
export const WEIGHT_CHANGE_RATE = {
  dog: { lose: [1, 2], gain: [0.5, 2] },
  cat: { lose: [0.5, 1], gain: [0.5, 2] },
}

/** 把速度区间写成「1%~2%」这样的文案（界面/文档/测试共用一份） */
export function weightChangeText(species, kind = 'lose') {
  const r = (WEIGHT_CHANGE_RATE[normSpecies(species)] || WEIGHT_CHANGE_RATE[DEFAULT_SPECIES])[kind]
  return `${r[0]}%~${r[1]}%`
}

/**
 * 零食、加餐、人食与用于喂药的食物，合计**不应超过每日总能量的 10%**。
 * 依据：WSAVA《Nutritional Assessment Guidelines》(2011) 把「零食/人食 > 每日总热量 10%」
 * 明确列为营养风险因素（Nutritional Screening Risk Factor）；AAHA 2021 同口径
 * （全价粮应提供 ≥90% 热量）。
 * ⚠ 这一条以前只写在成年期的阶段提示里，且不给数字 —— 宠主拿不到「到底能喂多少」。
 */
export const TREAT_ENERGY_MAX_PERCENT = 10

/**
 * 肌肉状况评分（MCS）提示。
 * 依据：WSAVA 2011 指南 —— BCS 评的是**脂肪**，MCS 评的是**肌肉**，两者必须分开看：
 * 触摸颞骨、肩胛骨、腰椎、骨盆处；肌肉流失在多数急慢性病中比单纯饥饿更严重，
 * 且与死亡率独立相关。减重期与老年动物尤其容易「体重下降但掉的是肌肉」。
 */
export const MCS_HINT = [
  'BCS 评的是脂肪，肌肉要另外摸：双手手指分别贴住颞骨（太阳穴）、肩胛骨、腰椎两侧与骨盆，感受肌肉厚度',
  '颞骨、肩胛、腰椎、骨盆处能明显摸到骨头轮廓并凹陷，即为肌肉流失（轻度 → 明显 → 严重）',
  '减重期与老年动物最容易被忽略：体重在降，但如果掉的是肌肉，说明能量下调过猛或蛋白不足',
]

/** 取 BCS 条目；非法/缺失返回 null（**不替用户假定 5 分**） */
export function bcsEntry(score) {
  const n = Math.round(Number(score))
  if (!Number.isFinite(n) || n < 1 || n > 9) return null
  return BCS_SCALE[n - 1]
}

/** 归类：'thin' | 'ideal' | 'over' | 'obese' | null —— ⚠ **物种无关**（犬口径），
 *  要判「是不是理想」请用 `bcsGroupFor(species, score)`。 */
export function bcsGroup(score) {
  const e = bcsEntry(score)
  return e ? e.group : null
}

/**
 * 按物种校正后的归类 —— **判「理想档」的唯一入口**，不要直接用 `bcsGroup()`。
 *
 * 为什么需要：四档归类里只有「ideal」的成员资格是**物种相关**的（犬 4~5 分、猫仅 5 分）。
 * `BCS_SCALE` 与 `BCS_GROUPS.range` 都是全局一份、按犬口径写死，于是猫 4 分会落进 ideal 档
 * —— 而它其实是偏瘦。这里把「不属于该物种理想区的 ideal 分」统一降为 thin 档。
 *
 * 真源只有一处：`BCS_SPECIES_NOTE[species].idealScores`（经 `isIdealFor()` 读取）。
 */
export function bcsGroupFor(species, score) {
  const e = bcsEntry(score)
  if (!e) return null
  if (e.group !== 'ideal') return e.group
  return isIdealFor(species, e.score) ? 'ideal' : 'thin'
}

/**
 * 给界面用的完整体况策略（含建议与是否必须先看兽医）
 * @param {number|string} score    BCS 1~9
 * @param {'dog'|'cat'} species    物种 —— 减重速度按物种分档，**不能共用一套数值**
 */
export function bcsPolicy(score, species = DEFAULT_SPECIES) {
  const sp = normBcsSpecies(species)
  const lose = weightChangeText(sp, 'lose')
  const gain = weightChangeText(sp, 'gain')
  const e = bcsEntry(score)
  if (!e) {
    return {
      ok: false,
      score: null,
      species: sp,
      idealText: BCS_SPECIES_NOTE[sp].idealText,
      note: '未填写体况评分（BCS 1~9）：以下按「理想体况」给出维持量，请评估后重新生成',
    }
  }
  /* 分组必须按物种校正：猫 4 分在 `BCS_SCALE` 里归 ideal，但它其实偏瘦。
     `group` / `groupLabel` / `advice` / `energyAdjPercent` 全部由这一个值派生，
     所以只要这里是校正后的值，四者就不会再互相矛盾。 */
  const group = bcsGroupFor(sp, e.score)
  const g = BCS_GROUPS[group]
  const advice = {
    thin: `当前偏瘦：先排查寄生虫、消化吸收与潜在疾病，再考虑增加饲喂量；增重速度建议不超过每周体重的 ${gain}（更快的增量基本都是脂肪）`,
    ideal: '体况理想：按维持量饲喂，保持每周固定称重、每月复评体况',
    over: `当前偏胖：按建议幅度下调喂食量，同时增加运动；减重速度控制在每周体重的 ${lose}`
      + (sp === 'cat' ? '，不得更快 —— 猫减重过快会诱发肝脂沉积症（俗称猫脂肪肝），可危及生命' : ''),
    obese: '已达到肥胖：减重方案请先由兽医确认目标体重与减重速度，本表数值仅作参考'
      + (sp === 'cat' ? '；猫尤其要控速，过快的减重可诱发肝脂沉积症（俗称猫脂肪肝）' : ''),
  }[group]
  const row = bcsChartRow(sp, e.score)
  const screening = inObesityScreeningZone(e.score)
  const ideal = isIdealFor(sp, e.score)
  /* 分组被降级时（猫 4 分：ideal→thin），能量系数不能沿用原档的 0（=维持量），
     要取目标档里**最接近理想**那一档的幅度（thin 档 1/2/3 分 → 3 分的 +10%）。
     只改分组不改系数 = 一只偏瘦的猫仍按维持量喂，等于维持偏瘦。 */
  const energyAdjPercent = group === e.group
    ? e.energyAdjPercent
    : BCS_SCALE.filter((x) => x.group === group).pop().energyAdjPercent
  return {
    ok: true,
    species: sp,
    score: e.score,
    /* 名称按物种取：判定表（bcsChart.js）才是名称真源，`BCS_SCALE` 只提供能量参数 */
    label: row ? row.label : e.label,
    group,
    groupLabel: g.label,
    touch: e.touch,
    energyAdjPercent,
    vetRequired: e.vetRequired,
    /* 临床肥胖筛查区（BCS 7~9）：是筛查阈值、不是诊断 */
    screeningZone: screening,
    screeningNote: screening
      ? `当前评分落在${BCS_OBESITY_SCREENING_ZONE.label}（BCS ${BCS_OBESITY_SCREENING_ZONE.from}~${BCS_OBESITY_SCREENING_ZONE.to}）：建议请兽医做一次以肥胖为目标的评估（含体况、肌肉状况、体重趋势、饮食史、活动能力与体检）。这是一个筛查阈值，不等于确诊 —— BCS 本身不能诊断临床肥胖。`
      : null,
    /* 该物种是否处于理想区：犬 4~5 分，猫只有 5 分 */
    idealForSpecies: ideal,
    idealText: BCS_SPECIES_NOTE[sp].idealText,
    /* 出处口径：不在理想区就建议兽医评估一次（不等于必须先就医，那是 vetRequired） */
    vetAdvise: ideal
      ? null
      : `按 9 分制评分口径，任何不在理想区的评分（${BCS_SPECIES_NOTE[sp].idealText}）都建议请兽医团队评估一次`,
    /* 该物种、该分数对应的逐分判据（界面与文档的「体况特征」用这一份，比整档一句更准） */
    fatText: row ? row.fatText : null,
    criteria: row ? { lateral: row.lateral, dorsal: row.dorsal, palpation: row.palpation } : null,
    advice,
    /* 结构化速度区间：导出文档要单独成行显示，不靠解析 advice 里那句话 */
    weightRate: { lose, gain, unit: '%/周' },
  }
}

/**
 * 组装给界面与导出文档渲染用的 BCS 判定表。
 *
 * 界面、HTML 导出、纯文本导出**三处共用这一份**：列名、物种注意点、误差说明、出处
 * 只在这里写一次，避免三处各抄一套而行成难被发现的分叉。
 * ⚠ 行数据来自 `bcsChart.js`（唯一出处），本函数只做**装配**，不再重写判据文案。
 */
export function bcsChartPayload(species) {
  const sp = normBcsSpecies(species)
  const note = BCS_SPECIES_NOTE[sp]
  return {
    species: sp,
    speciesLabel: sp === 'cat' ? '猫' : '犬',
    columns: BCS_CHART_COLUMNS,
    rows: bcsChartFor(sp),
    idealScores: idealScoresFor(sp),
    idealText: note.idealText,
    notes: note.notes,
    caveats: BCS_CHART_CAVEATS,
    screeningZone: BCS_OBESITY_SCREENING_ZONE,
    source: bcsChartSourceText(),
  }
}

/**
 * 由体况评分反推理想体重。
 *
 * 依据：**每 1 分 BCS 高于 5 分，约相当于超过理想体重 10%** —— 犬猫临床通行经验规则。
 * ⚠ 这是经验估算，不是实验结论，返回值带 `empirical:true`，界面上必须标出。
 * BCS ≤ 5（不超重）时返回 null：**偏瘦一侧不能这样反推**，理想体重应由品种标准/兽医给。
 *
 * @param {number} currentKg 当前体重 kg
 * @param {number} score     BCS 1~9
 * @returns {{kg:number, reducePercent:number, deltaKg:number, empirical:true, note:string}|null}
 */
export function idealWeightFromBcs(currentKg, score) {
  const w = Number(currentKg)
  const e = bcsEntry(score)
  if (!Number.isFinite(w) || w <= 0 || !e) return null
  if (e.score <= 5) return null
  const excess = 0.1 * (e.score - 5)
  const kg = w / (1 + excess)
  return {
    kg: r1(kg),
    reducePercent: r1((1 - kg / w) * 100),
    deltaKg: r1(w - kg),
    empirical: true,
    note: '按「每 1 分 BCS 高于 5 分 ≈ 超过理想体重 10%」估算，属经验规则；目标体重请由兽医确认',
  }
}

/* ================= 2. 生命阶段与分餐 ================= */

/** 生长终点（月龄）：超过即视为成年骨架已基本定型 */
export const GROWTH_END_MONTHS = {
  cat: 12,
  dog: { small: 12, medium: 15, large: 18 },
}

/** 老年起点（月龄）：犬按体型分档（体型越大越早），猫取 8 岁 */
export const SENIOR_FROM_MONTHS = {
  cat: 96,
  dog: { small: 96, medium: 84, large: 72 },
}

/** 离乳完成（月龄）：约 6~8 周，取 2 个月 */
export const WEANED_MONTHS = 2

export function growthEndMonths(species, size) {
  if (species === 'cat') return GROWTH_END_MONTHS.cat
  const s = size && GROWTH_END_MONTHS.dog[size] ? size : 'medium'
  return GROWTH_END_MONTHS.dog[s]
}

export function seniorFromMonths(species, size) {
  if (species === 'cat') return SENIOR_FROM_MONTHS.cat
  const s = size && SENIOR_FROM_MONTHS.dog[size] ? size : 'medium'
  return SENIOR_FROM_MONTHS.dog[s]
}

/**
 * 判定生命阶段。
 *
 * 优先级：显式生理状态（妊娠/泌乳）> 月龄推断 > 状态兜底。
 * ⚠ **不给年龄也不给状态时返回 `id:'unknown'`**（`assumed:true`），
 *   由调用方去提示补填 —— 不假装是成年期。
 *
 * @param {Object} profile { species, ageMonths, ageText, status, size, weightKg }
 */
export function lifeStage(profile = {}) {
  const species = profile.species === 'dog' ? 'dog' : 'cat'
  const status = profile.status || ''
  if (status === 'gestation') {
    return { id: 'gestation', label: '妊娠期', assumed: false, desc: '怀孕中后期，能量与蛋白需求上升' }
  }
  if (status === 'lactation') {
    return { id: 'lactation', label: '泌乳期', assumed: false, desc: '哺乳中，能量需求可达维持量的数倍' }
  }
  if (status === 'weight_loss') {
    return { id: 'weight_loss', label: '减脂期', assumed: false, desc: '按减重目标控制能量摄入' }
  }

  let size = profile.size
  if (!size && profile.breed) size = identifyBreed(profile.breed)?.size
  if (!size && species === 'dog') size = sizeFromWeight(species, profile.weightKg)

  const m = profile.ageMonths ?? parseAge(profile.ageText)
  if (m === null || m === undefined || !Number.isFinite(Number(m))) {
    return {
      id: 'unknown',
      label: '未判定（缺年龄）',
      assumed: true,
      desc: '未填写年龄，无法判定生命阶段；以下按成年维持量的常规做法给出，请补填年龄后重新生成',
      species, size: size || null,
    }
... (截断，完整见本地 diff)
```


## [MIRROR_TAMPERED] junheng-core / scripts/vendor/multiPetPlan.js
- 源：C:/Users/Administrator/WorkBuddy/2026-10-09-19-00-38/nutrition-agent-work/src/lib\multiPetPlan.js
- 镜像：C:/Users/Administrator/.workbuddy/skills\junheng-core\scripts/vendor\multiPetPlan.js
- 镜像独有行数：348

```diff
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

/**
 * 单宠每日原料用量：`配方内占比 share% × 每日喂食量`。
 *
 * ⚠ 口径说明：`share` 是**配方内**占比（`computeRecipe` 已做同名合并与归一），
 * 故 Σ(每条 grams) === gramsPerDay，仅存末位舍入差（守卫按 ≤ 0.01×条数 断言）。
 *
 * ⚠ `gramsPerDay` 缺失（宠物未算出喂食量）时**不给 0 而给 null** ——
 * 「没算出来」与「需要 0 克」是两回事，采购清单据此决定是否计入。
 */
export function ingredientDailyUse(lines, gramsPerDay) {
  const list = Array.isArray(lines) ? lines : []
  const g = num(gramsPerDay)
  return list.map((l) => ({
    code: str(l && l.code),
    name: str(l && l.name),
    share: r2(num(l && l.share)),
    grams: g > 0 ? r2((num(l && l.share) / 100) * g) : null,
    pricePerKg: priceOf(l),
  }))
}

/** 归一化「未匹配原料」入参：`[{ rawName|name, weight }]` → 稳定形状 */
function normUnmatched(raw) {
  const list = Array.isArray(raw) ? raw : []
  return list
    .map((u) => ({
      rawName: str(u && (u.rawName || u.name)),
      weight: num(u && u.weight),
    }))
    .filter((u) => u.rawName && u.weight > 0)
}

/* ================= 4. 合并采购清单（按物料编号归并） ================= */

/**
 * 把「多宠每日原料用量」归并成一张采购清单。
 *
 * 归并键 = **物料编号 code**（唯一 ID）。无 code 时退回按名称归并，但标 `codeMissing`
 * 并把该风险写进 note —— 按名字归并可能把名称相同、实际不同的原料合并。
 *
 * @returns {{ days:number, items:Array, unmatched:Array, note:string[] }}
 */
export function purchaseFromPets(pets, days = PURCHASE_DAYS_DEFAULT) {
  const d = clampDays(days)
  const map = new Map()
  const umMap = new Map()

  for (const pet of Array.isArray(pets) ? pets : []) {
    if (!pet || !pet.ok) continue // 红线 1：算不出的宠物不进采购
    for (const ing of pet.ingredients || []) {
      if (ing.grams == null || ing.grams <= 0) continue
      const key = ing.code ? `code:${ing.code}` : `name:${ing.name}`
      let it = map.get(key)
      if (!it) {
        it = {
          code: ing.code,
          name: ing.name,
          codeMissing: !ing.code,
          gramsPerDay: 0,
          pets: [],
          prices: new Set(),
        }
        map.set(key, it)
      }
      it.gramsPerDay += ing.grams
      it.pets.push(pet.label)
      if (ing.pricePerKg != null) it.prices.add(ing.pricePerKg)
    }

    /* 未匹配原料：无 code、无 share 可直接用，只能按**输入占比反推**估算。
       ⚠ 必须明标 estimated —— 这项份额没有经过营养验算，与已匹配项不是同一可信度。 */
    const recTotal = num(pet.recipeTotalWeight)
    const umList = pet.unmatched || []
    const umTotal = umList.reduce((s, u) => s + num(u.weight), 0)
    const denom = recTotal + umTotal
    for (const u of umList) {
      let it = umMap.get(u.rawName)
      if (!it) {
        it = { rawName: u.rawName, inputWeight: 0, pets: [], estimatedGramsPerDay: 0, estimated: true }
        umMap.set(u.rawName, it)
      }
      it.inputWeight = r2(it.inputWeight + u.weight)
      it.pets.push(pet.label)
      if (denom > 0) it.estimatedGramsPerDay = r2(it.estimatedGramsPerDay + (u.weight / denom) * num(pet.gramsPerDay))
    }
  }

  const items = [...map.values()].map((it) => {
    const prices = [...it.prices].sort((a, b) => a - b)
    const conflict = prices.length > 1
    const kg = r2((it.gramsPerDay * d) / 1000)
    const one = prices.length === 1 ? prices[0] : null
    return {
      code: it.code,
      name: it.name,
      codeMissing: it.codeMissing,
      gramsPerDay: r2(it.gramsPerDay),
      grams: r2(it.gramsPerDay * d),
      kg,
      pets: [...new Set(it.pets)],
      pricePerKg: one,
      priceConflict: conflict,
      /** 冲突时列出全部取值，让人自己选；不冲突时为空数组 */
      prices: conflict ? prices : [],
      /** 有唯一单价时才给金额；冲突时给区间（取任一边都是替用户拍板） */
      cost: one != null ? r2((it.gramsPerDay * d / 1000) * one) : null,
      costRange: (conflict && prices.length) ? {
        min: r2((it.gramsPerDay * d / 1000) * prices[0]),
        max: r2((it.gramsPerDay * d / 1000) * prices[prices.length - 1]),
      } : null,
    }
  }).sort((a, b) => b.kg - a.kg) // 按需求量降序：先买大头，便于核对

  const unmatched = [...umMap.values()].sort((a, b) => b.estimatedGramsPerDay - a.estimatedGramsPerDay)
    .map((u) => ({ ...u, pets: [...new Set(u.pets)] }))

  const note = []
  if (items.some((x) => x.codeMissing)) {
    note.push('有原料没有物料编号，已按名称归并 —— 名称相同但实际不同的原料会被合并，请人工核对')
  }
  if (items.some((x) => x.priceConflict)) {
    note.push('有原料在不同配方里单价不一致：未给出金额，只给区间（取哪一边都是替你做决定）')
  }
  if (unmatched.length) {
    note.push('未匹配原料的每日用量是按输入占比反推的估算值（不是验算值），与已匹配项不是同一可信度；请补齐原料库后重算')
  }
  note.push(`需求量按 ${d} 天口径折算；实买请考虑损耗、分装余量与最小起订量`)

  return { days: d, items, unmatched, note }
}

/* ================= 5. 主入口 ================= */

/** 失败原因：优先说清缺什么，而不是笼统说「算不出」 */
function failReasonOf(plan) {
  const miss = Array.isArray(plan && plan.missing) ? plan.missing : []
  if (miss.length) return `缺少：${miss.join('、')}`
  return '未能算出每日喂食量（请检查体重与配方代谢能数据）'
}

/**
 * 多宠聚合。
 *
 * @param {Array<{label?:string,name?:string,profile:object,recipe?:object,req?:object,unmatched?:Array}>} entries
 *        每只宠物一条；`profile` 必填（至少含 weightKg），`recipe` 为 `computeRecipe` 的返回对象
 * @param {{days?:number}} [opts]
 */
export function computeMultiPetPlan(entries = [], opts = {}) {
  const days = clampDays(opts && opts.days)
  const list = Array.isArray(entries) ? entries : []
  const warnings = []
  const notes = []

  /* ---- 空输入 / 超限：给可操作的错误，不抛栈、不静默 ---- */
  if (list.length === 0) {
    return {
      ok: false,
      days,
      petCount: 0,
      okCount: 0,
      failedCount: 0,
      reason: '没有宠物条目：至少给一只宠物的 profile 才能聚合',
      pets: [],
      totals: null,
      purchase: null,
      warnings,
      notes,
    }
  }
  if (list.length > MAX_PETS) {
    return {
      ok: false,
      days,
      petCount: list.length,
      okCount: 0,
      failedCount: list.length,
      reason: `宠物条目 ${list.length} 只，超过上限 ${MAX_PETS}：请分批聚合（静默截断会得到一个偏低的总量与采购清单）`,
      pets: [],
      totals: null,
      purchase: null,
      warnings,
      notes,
    }
  }

  /* ---- 标签：空标签兜底 + 重名去重。重名会让「哪只用了哪个物料」失去追溯力 ---- */
  const base = list.map((e, i) => str(e && e.label) || str(e && e.name)
    || str(e && e.profile && e.profile.name) || `宠物 ${i + 1}`)
  const counter = new Map()
  const labels = base.map((lb) => {
    const n = (counter.get(lb) || 0) + 1
    counter.set(lb, n)
    return n === 1 ? lb : `${lb}（第 ${n} 只）`
  })
  if (labels.some((lb, i) => lb !== base[i])) {
    warnings.push('存在重名宠物，已在标签后追加序号以便区分 —— 请核对「哪些宠物用到某原料」是否指对了对象')
  }

  /* ---- 逐宠计算 ---- */
  const pets = list.map((e, i) => {
    const profile = (e && e.profile) || {}
    const recipe = (e && e.recipe) || null
    const plan = computeFeedingPlan(profile, recipe, (e && e.req) || null, {}) || {}
    const ok = Boolean(plan.computed)
    const gp = num(plan.energy && plan.energy.gramsPerDay)
    const kcal = num(plan.energy && plan.energy.mer)
    const costDay = plan.cost && plan.cost.perDay != null ? num(plan.cost.perDay) : null

    return {
      index: i + 1,
      label: labels[i],
      name: str(profile.name),
      species: plan.species || '',
      speciesLabel: plan.speciesLabel || '',
      weightKg: num(plan.pet && plan.pet.weightKg) || null,
      bcs: (plan.pet && plan.pet.bcs != null) ? plan.pet.bcs : null,
      bcsLabel: (plan.pet && plan.pet.bcsLabel) || '',
      ok,
      failReason: ok ? '' : failReasonOf(plan),
      gramsPerDay: ok ? r0(gp) : null,
      perMeal: ok ? r0(num(plan.energy && plan.energy.perMeal)) : null,
      mealsPerDay: num(plan.meals && plan.meals.perDay) || null,
      kcalPerDay: ok ? r0(kcal) : null,
      costPerDay: ok && costDay != null ? r2(costDay) : null,
      costPerDays: ok && costDay != null ? r2(costDay * days) : null,
      pricePerKg: (plan.cost && plan.cost.pricePerKg != null) ? r2(num(plan.cost.pricePerKg)) : null,
      ingredients: ingredientDailyUse(recipe && recipe.lines, ok ? gp : 0),
      recipeTotalWeight: num(recipe && recipe.totalWeight),
      unmatched: normUnmatched(e && e.unmatched),
      missing: [...((plan.missing) || [])],
      warnings: [...((plan.warnings) || [])],
    }
  })

  const okPets = pets.filter((p) => p.ok)
  const failedPets = pets.filter((p) => !p.ok)
  if (failedPets.length) {
    warnings.push(`有 ${failedPets.length} 只宠物未算出喂食量（${failedPets.map((p) => p.label).join('、')}）`
      + '：它们【未计入】总量与采购清单，补齐数据后请重算')
  }

  /* ---- 合计（仅 ok 宠物）---- */
  const sumGrams = okPets.reduce((s, p) => s + num(p.gramsPerDay), 0)
  const sumKcal = okPets.reduce((s, p) => s + num(p.kcalPerDay), 0)
  const priced = okPets.filter((p) => p.costPerDay != null)
  const sumCost = priced.reduce((s, p) => s + num(p.costPerDay), 0)

  const totals = {
    petCount: pets.length,
    okCount: okPets.length,
    failedCount: failedPets.length,
    gramsPerDay: r0(sumGrams),
    grams: r0(sumGrams * days),
    kg: r2((sumGrams * days) / 1000),
    kcalPerDay: r0(sumKcal),
    costPerDay: priced.length ? r2(sumCost) : null,
    cost: priced.length ? r2(sumCost * days) : null,
    pricedCount: priced.length,
    unpricedCount: okPets.length - priced.length,
  }
  if (priced.length && priced.length < okPets.length) {
    totals.costNote = `只有 ${priced.length}/${okPets.length} 只宠物有单价资料，合计金额是【低估值】，不代表全部开销`
  } else if (!priced.length && okPets.length) {
    totals.costNote = '没有任何宠物有单价资料，未给出合计金额'
  }

  const purchase = purchaseFromPets(pets, days)

  if (okPets.length) {
    notes.push('采购清单是按「喂食量 × 配方内占比」折算的原料需求量，不含损耗与分装余量')
    notes.push('每日喂食量来自各宠的喂食计划：任何一只的体重或体况变了，本清单都要重算')
  }

  return {
    computed: okPets.length > 0,
    days,
    petCount: pets.length,
    okCount: okPets.length,
    failedCount: failedPets.length,
    reason: okPets.length ? '' : '所有宠物都未算出喂食量，无法生成总量与采购清单',
    totals,
    purchase,
    pets,
    warnings,
    notes,
  }
}
```


## [MIRROR_TAMPERED] junheng-core / scripts/vendor/portionLabel.js
- 源：C:/Users/Administrator/WorkBuddy/2026-10-09-19-00-38/nutrition-agent-work/src/lib\portionLabel.js
- 镜像：C:/Users/Administrator/.workbuddy/skills\junheng-core\scripts/vendor\portionLabel.js
- 镜像独有行数：394

```diff
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
  dry: '干粮',
  wet: '湿粮',
  unknown: '未指定',
}

/* ================= 2. 小工具 ================= */

const num = (v) => (Number.isFinite(Number(v)) ? Number(v) : 0)
const str = (v) => (typeof v === 'string' ? v.trim() : '')
const r2 = (n) => Math.round(n * 100) / 100
const r0 = (n) => Math.round(n)

const ISO_RE = /^(\d{4})-(\d{2})-(\d{2})$/

/** 严格解析 `YYYY-MM-DD`；非法日期（如 2026-02-30）返回 null，不静默规范化 */
function parseIso(s) {
  const m = ISO_RE.exec(str(s))
  if (!m) return null
  const y = Number(m[1]); const mo = Number(m[2]); const d = Number(m[3])
  const dt = new Date(Date.UTC(y, mo - 1, d))
  // Date 会把 2026-02-30 规范化成 03-02 —— 回读比对才能挡住「不存在的日期」
  if (dt.getUTCFullYear() !== y || dt.getUTCMonth() !== mo - 1 || dt.getUTCDate() !== d) return null
  return dt
}

function fmtIso(dt) {
  const y = dt.getUTCFullYear()
  const m = String(dt.getUTCMonth() + 1).padStart(2, '0')
  const d = String(dt.getUTCDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

/** `YYYY-MM-DD` 合法则原样返回，否则 null */
export function validIso(v) {
  const dt = parseIso(v)
  return dt ? fmtIso(dt) : null
}

/**
 * 日期加减（**纯日期**口径，用 UTC 运算避开夏令时把某天变成 23/25 小时的坑）。
 * `2026-10-31 + 1` ⇒ `2026-11-01`（跨月）；`2026-12-31 + 1` ⇒ `2027-01-01`（跨年）。
 * 输入非法 ⇒ 返回 null（调用方须显式处理，不给「就当是今天」的隐形兜底）。
 */
export function addDaysIso(iso, n) {
  const dt = parseIso(iso)
  if (!dt) return null
  dt.setUTCDate(dt.getUTCDate() + r0(num(n)))
  return fmtIso(dt)
}

/**
 * 「今天」= **本地日期**。分装日期是用户认知里的当天；若服务器在 UTC，
 * 东八区清晨用 UTC 会算出「昨天」，贴纸日期就错了。
 * 参数 `now` 仅为可测性（守卫传入固定时刻）。
 */
export function todayIso(now = new Date()) {
  const y = now.getFullYear()
  const m = String(now.getMonth() + 1).padStart(2, '0')
  const d = String(now.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

function clampPortionDays(v) {
  const d = Number(v)
  if (!Number.isFinite(d) || d <= 0) return PORTION_DAYS_DEFAULT
  return Math.min(Math.max(1, r0(d)), PORTION_DAYS_MAX)
}

function clampTotalDays(v) {
  const d = Number(v)
  if (!Number.isFinite(d) || d <= 0) return TOTAL_DAYS_DEFAULT
  return Math.min(Math.max(1, r0(d)), TOTAL_DAYS_MAX)
}

function normForm(v) {
  const k = str(v)
  return Object.prototype.hasOwnProperty.call(FORM_TIPS, k) ? k : 'unknown'
}

/* ================= 3. 分装排期 ================= */

/**
 * 把总量按「每袋 N 天」拆成若干袋。
 *
 * @param {number} totalGrams 总量（克）
 * @param {{days?:number, portionDays?:number, startDate?:string}} [opts]
 *   days      总量覆盖天数（默认 30）
 *   portionDays 每袋覆盖天数（默认 7 = 按周）
 *   startDate  首袋起始日 `YYYY-MM-DD`（默认今天）
 * @returns {{ok:boolean, reason:string, days:number, portionDays:number, startDate:string,
 *            portionCount:number, totalGrams:number, portions:Array, note:string[], warnings:string[]}}
 */
export function portionSchedule(totalGrams, opts = {}) {
  const total = num(totalGrams)
  const days = clampTotalDays(opts.days)
  const portionDays = clampPortionDays(opts.portionDays)
  const startDate = validIso(opts.startDate) || todayIso(opts.now)
  const warnings = []
  const note = []

  if (opts.startDate && !validIso(opts.startDate)) {
    warnings.push(`起始日期「${str(opts.startDate)}」不是合法 YYYY-MM-DD，已按今天（${startDate}）处理`)
  }

  /* 红线 4：总量必须为正。返回空排期会被误读成「已分好」 */
  if (!(total > 0)) {
    return {
      ok: false,
      reason: '总量必须大于 0 克：0 克没有可分装的内容（返回空排期会被误读成「已经分好了」）',
      days, portionDays, startDate,
      portionCount: 0, totalGrams: 0,
      portions: [], note, warnings,
    }
  }

  /* 份数 = ceil(days / portionDays)；days ≤ portionDays 时只有 1 袋 */
  const count = Math.max(1, Math.ceil(days / portionDays))
  const portions = []
  let acc = 0
  for (let i = 0; i < count; i++) {
    const covered = Math.min(portionDays, days - i * portionDays)
    const isLast = i === count - 1
    // 红线 2：末袋吸收舍入余量 ⇒ Σ(grams) === total（其他袋按天数比例独立取整）
    const grams = isLast ? r2(total - acc) : r2((total * covered) / days)
    acc = r2(acc + grams)
    const segStart = addDaysIso(startDate, i * portionDays)
    portions.push({
      seq: i + 1,
      label: `第 ${i + 1} 袋`,
      daysCovered: covered,
      grams,
      startDate: segStart,
      endDate: addDaysIso(segStart, covered - 1), // 含首含尾
      // 红线 3：末袋覆盖天数不足时必须显式标出
      partial: covered < portionDays,
    })
  }

  const last = portions[portions.length - 1]
  note.push('先分装的先吃：请按「第 N 袋」顺序取用，避免来回翻找反复开合')
  if (last.partial) {
    note.push(`末袋只覆盖 ${last.daysCovered} 天（不足 ${portionDays} 天）—— 这是 ${days} 天 ÷ 每袋 ${portionDays} 天的余数，不是算错`)
  }

  return {
    ok: true,
    reason: '',
    days, portionDays, startDate,
    portionCount: count,
    totalGrams: r2(total),
    portions,
    note,
    warnings,
  }
}

/* ================= 4. 分装标签 ================= */

/**
 * 单个分装标签。
 *
 * @param {{recipeName?:string, name?:string, petLabel?:string, pet?:string,
 *          grams?:number, daysCovered?:number, seq?:number, portionCount?:number,
 *          filledDate?:string, now?:Date, shelfLifeDays?:number, form?:string}} input
 * @returns {{version:number, recipeName:string, petLabel:string, seq:number|null,
 *            portionCount:number|null, grams:number, daysCovered:number|null,
 *            filledDate:string, shelfLifeDays:number|null, useByDate:string|null,
 *            shelfLifeMissing:boolean, form:string, formLabel:string,
 *            thawNote:string, warnings:string[]}}
 */
export function buildPortionLabel(input = {}) {
  const recipeName = str(input.recipeName) || str(input.name)
  const petLabel = str(input.petLabel) || str(input.pet)
  const grams = r2(num(input.grams))
  const warnings = []

  /* 分装日期：给了但非法 ⇒ 用今天并告警（不静默） */
  const given = input.filledDate
  const parsed = validIso(given)
  if (given && !parsed) {
    warnings.push(`分装日期「${str(given)}」不是合法 YYYY-MM-DD，已按今天处理`)
  }
  const filledDate = parsed || todayIso(input.now)

  /* 红线 1：保质期只能由调用方给，缺失就留空 + 告警，绝不代填 */
  const shelfRaw = Number(input.shelfLifeDays)
  const hasShelf = Number.isFinite(shelfRaw) && shelfRaw > 0
  const shelfLifeDays = hasShelf ? r0(shelfRaw) : null
  const useByDate = hasShelf ? addDaysIso(filledDate, shelfLifeDays) : null
  if (!hasShelf) {
    warnings.push('未提供保质期天数 ⇒「建议食用期限」留空（本模块不猜保质期，请按产品实际保质期填写）')
  }

  const form = normForm(input.form)
  const daysCovered = Number.isFinite(Number(input.daysCovered)) && Number(input.daysCovered) > 0
    ? r0(Number(input.daysCovered)) : null

  return {
    version: PORTION_LABEL_VERSION,
    recipeName: recipeName || '（未填配方名）',
    petLabel,
    seq: Number.isFinite(Number(input.seq)) ? r0(Number(input.seq)) : null,
    portionCount: Number.isFinite(Number(input.portionCount)) ? r0(Number(input.portionCount)) : null,
    grams,
    daysCovered,
    filledDate,
    shelfLifeDays,
    useByDate,
    shelfLifeMissing: !hasShelf,
    form,
    formLabel: FORM_LABELS[form],
    thawNote: FORM_TIPS[form],
    warnings: [...warnings],
  }
}

/**
 * 渲染成可直接打印的纯文本贴纸。
 * 食用期限缺失时**不写日期**，写「待定 + 原因」—— 空着一个字段比印个假日期好。
 */
export function renderPortionLabelText(label) {
  const l = label || {}
  const seqTxt = l.seq != null ? `（第 ${l.seq}${l.portionCount != null ? `/${l.portionCount}` : ''} 袋）` : ''
  const perTxt = l.daysCovered != null
    ? `${l.grams} 克（${l.daysCovered} 天量）`
    : `${l.grams} 克`
  const useBy = l.useByDate
    ? `${l.useByDate}（分装后 ${l.shelfLifeDays} 天）`
    : '待定（未提供保质期，请按产品实际保质期填写）'
  const lines = [
    '································',
    `配方：${l.recipeName}${seqTxt}`,
    l.petLabel ? `宠物：${l.petLabel}` : null,
    `每份：${perTxt}`,
    `分装日期：${l.filledDate}`,
    `建议食用期限：${useBy}`,
    `保存/解冻：${l.thawNote}`,
    '································',
  ]
  return lines.filter((x) => x != null).join('\n')
}

/* ================= 5. 批量（同日分装） ================= */

/**
 * 同日分装：多条（多宠/多配方）**在同一天**完成分装 ⇒ 共用 `filledDate`。
 *
 * @param {Array<{recipeName?:string, petLabel?:string, gramsPerDay?:number, dailyGrams?:number}>} entries
 * @param {{days?:number, portionDays?:number, filledDate?:string, now?:Date,
 *          shelfLifeDays?:number, form?:string}} [opts]
 */
export function computePortionLabels(entries = [], opts = {}) {
  const days = clampTotalDays(opts.days)
  const portionDays = clampPortionDays(opts.portionDays)
  const filledDate = validIso(opts.filledDate) || todayIso(opts.now)
  const form = normForm(opts.form)
  const warnings = []
  const note = []
  const labels = []
  const schedules = []

  const list = Array.isArray(entries) ? entries : []
  if (!list.length) {
    return {
      computed: false,
      reason: '没有分装条目：至少给一只宠物的每日用量（克/日）才能排期与出标签',
      filledDate, days, portionDays, form,
      labels: [], schedules: [], warnings, note,
    }
  }

  if (opts.filledDate && !validIso(opts.filledDate)) {
    warnings.push(`分装日期「${str(opts.filledDate)}」不是合法 YYYY-MM-DD，已按今天（${filledDate}）处理`)
  }

  /* 红线 1 上浮：保质期缺失不能只藏在每张标签的 warnings 里 ——
     调用方（CLI / 界面）看的是本函数的 warnings，埋进 labels[i] 就等于没人看见。 */
  if (!(Number.isFinite(Number(opts.shelfLifeDays)) && Number(opts.shelfLifeDays) > 0)) {
    warnings.push('未提供保质期天数（shelfLifeDays）⇒ 全部标签的「建议食用期限」留空，请按产品实际保质期填写后再打印')
  }

  for (let i = 0; i < list.length; i++) {
    const e = list[i] || {}
    const recipeName = str(e.recipeName) || str(e.name)
    const petLabel = str(e.petLabel) || str(e.pet) || (recipeName ? '' : `条目 ${i + 1}`)
    const daily = num(e.gramsPerDay != null ? e.gramsPerDay : e.dailyGrams)
    const total = r2(daily * days)

    const sch = portionSchedule(total, { days, portionDays, startDate: filledDate })
    schedules.push({
      recipeName: recipeName || '（未填配方名）',
      petLabel,
      gramsPerDay: r2(daily),
      totalGrams: r2(total),
      portionCount: sch.ok ? sch.portionCount : 0,
      ok: sch.ok,
      reason: sch.reason,
    })

    if (!sch.ok) {
      warnings.push(`「${recipeName || petLabel || `条目 ${i + 1}`}」无法分装：${sch.reason}`)
      continue
    }

    for (const p of sch.portions) {
      labels.push(buildPortionLabel({
        recipeName,
        petLabel,
        grams: p.grams,
        daysCovered: p.daysCovered,
        seq: p.seq,
        portionCount: sch.portionCount,
        filledDate,
        shelfLifeDays: opts.shelfLifeDays,
        form,
      }))
    }
  }

  if (labels.length) {
    note.push(`同日分装：全部 ${labels.length} 张标签共用分装日期 ${filledDate}（食用期限均由此起算）`)
    note.push('每袋克数是「每日用量 × 覆盖天数」按比例折算，Σ 等于该宠总量（末袋吸收舍入余量）')
  }

  return {
    computed: labels.length > 0,
    reason: labels.length ? '' : '所有条目都未能分装（每日用量为 0 或缺失）',
    filledDate, days, portionDays, form,
    labels,
    schedules,
    warnings,
    note,
  }
}
```
