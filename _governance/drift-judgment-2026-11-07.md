# BOTH_CHANGED SKILL.md (true conflicts)

### junheng-bcs / SKILL.md
  diff_lines=175  src_sz=5147 mir_sz=5024
--- C:/Users/Administrator/WorkBuddy/2026-10-09-19-00-38/nutrition-agent-work/cli/skills\junheng-bcs\SKILL.md	2026-10-30 21:22:14.161938400 +0800
+++ C:/Users/Administrator/.workbuddy/skills\junheng-bcs\SKILL.md	2026-11-05 16:31:49.839382900 +0800
@@ -1,87 +1,85 @@
----
-name: junheng-bcs
-description: 宠物体况评分 BCS 9 分制查询与参考图生成。按物种取逐分判定表，判断某分是否落在理想区（犬 4-5、猫仅 5）或肥胖筛查区（7-9），给出易误判点与体脂率区间，并生成侧视加俯视矢量参考图。当用户问猫狗胖不胖、算几分时使用。
-description_en: Pet body condition score (BCS 9-point scale) lookup and reference figure generation for dogs and cats: per-score criteria (lateral/dorsal/palpation), ideal range and obesity screening zone, species-specific pitfalls, estimated body-fat ranges, and a self-drawn side/top SVG reference figure.
-metadata:
-  author: Junheng NutriAgent
-  version: "1.0.0"
-compatibility: Requires Node.js 18+ (ESM) and a UTF-8 filesystem. No network access and no third-party dependencies. Self-contained CLI facade; no dependency on other junheng-* skills.
----
-
-# 体况评分参考（junheng-bcs）
-
-## 目的与边界
-
-**做什么**：给出「某个分数对应什么外观与触感」的判据原文、是否属于理想区/筛查区、以及该物种的易误判点。
-
-**不做什么**：
-
-- **不做诊断**。BCS 是筛查工具；临床肥胖确诊需兽医结合肌肉状况、体重趋势、饮食史、活动能力与体检。
-- **不代替实际触摸**。所有判定都要求以触摸肋骨为准；只看轮廓会被毛量、原始袋、品种骨架误导。
-- **不给减重方案**。能给出的是「该不该请兽医评估」以及「猫的减重速度必须比犬更慢」这类边界提示。
-- **不使用受版权保护的现成图**。本技能生成的 SVG 是按公开发表判据自绘的原创矢量图（画面与配色均为原创），不是任何机构的原图。
-
-## 诚实性红线
-
-1. **筛查不等于诊断**。7~9 分只是进入临床肥胖筛查区（`inObesityScreeningZone: true`），输出里必须同时给 `caveats`，不得表述成「确诊肥胖」。
-2. **体脂率是近似估算**。个体误差约正负 5 个百分点；体脂超过约 45% 时 BCS 区分度明显下降，此时应改用体脂指数（BFI）、体尺测量或 DXA。
-3. **犬猫理想区不同**。犬是 4~5 分，**猫只有 5 分** —— 把猫按 4 分长期饲喂等于偏瘦。
-4. **非理想分数要建议就医**。任何不在理想区的评分都建议请兽医团队评估一次，不要只凭本表大幅增减喂食量或运动量。
-5. **档位标注写区间，不写单点**。参考图的三档分别覆盖 1–3 / 4–5 / 6–9 分，只标单点分数会与实际分数对不上。
-
-## 用法
-
-在技能根目录下执行：
-
-```
-node scripts/cli.mjs <命令> '<JSON 参数>'
-node scripts/cli.mjs <命令> --stdin
-node scripts/cli.mjs --help
-node scripts/cli.mjs <命令> --help
-```
-
-## 命令一览
-
-| 命令 | 用途 |
-|------|------|
-| `chart` | 查某物种的完整逐分判定表（9 行 × 侧视/俯视/触摸三列） |
-| `row` | 查单一分数的判定行（含理想区 / 筛查区标记） |
-| `assess` | 体况评估总装：判定行 + 标记 + 物种差异提示 + 误差与就医声明 |
-| `figures` | 列出参考图可用的体型分类与档位（给 `figure-svg` 取值用） |
-| `figure-svg` | 生成一张自包含的「侧视 + 俯视」参考图 SVG 字符串 |
-| `caveats` | 查全部可靠性边界、物种差异与出处 |
-| `describe` | 输出机器可读的接口说明 |
-
-**参数详表、输出字段表、可运行示例** → [详细接口参考](references/interface-reference.md)。
-
-## 失败处理（退出码）
-
-| 退出码 | 含义 |
-|--------|------|
-| 0 | 成功，结果在 stdout 的 JSON 里 |
-| 1 | 内部错误（未预期异常） |
-| 2 | 用法或输入错误，命令未执行（如 `score` 给了 0 或 12） |
-| 3 | 前置条件缺失（技能镜像未同步） |
-
-## 拒答与替代路径
-
-> 本节是**可机检**的边界契约（规范与判据见 `docs/技能边界与拒答契约_2026-10-13.md`）。
-> 命中某一类时，按该类「话术」回复并给出「替代」路径；标「不适用」的类必须写明本技能层面的理由。
-
-### R1 非犬猫物种
-- **触发**：查询非犬猫物种的体况评分表。
-- **话术**：本技能的 9 分制判据表只覆盖犬与猫，对其它物种不适用。
-- **替代**：请咨询该物种的兽医；犬猫的逐分判定行与参考图本技能可照常给。
-
-### R2 医疗诊断
-- **触发**：要求确诊肥胖或给出减重方案。
  ...(+95 more diff lines)

### junheng-core / SKILL.md
  diff_lines=183  src_sz=6002 mir_sz=6053
--- C:/Users/Administrator/WorkBuddy/2026-10-09-19-00-38/nutrition-agent-work/cli/skills\junheng-core\SKILL.md	2026-10-30 21:22:14.187762300 +0800
+++ C:/Users/Administrator/.workbuddy/skills\junheng-core\SKILL.md	2026-11-05 16:31:49.842093500 +0800
@@ -1,89 +1,91 @@
----
-name: junheng-core
-description: 钧衡 NutriAgent 的共享计算内核（不是面向用户的技能）。它是 junheng-nutrition / -labeling / -cost / -feeding 四个技能共同依赖的源码镜像与 286 条原料种子库的唯一持有者，本身不提供用户可调用的业务命令。当出现「junheng-nutrition 报前置条件缺失」「技能找不到源码目录」或需要更新法规/原料库并重新同步技能时使用。
-description_en: Shared computation core for Junheng NutriAgent skills. Holds the single copy of the mirrored source closure (nutrition/standards/energy/bcsChart/labeling/costModes/feedingGuide) and the 286-ingredient seed database, consumed by junheng-nutrition, -labeling, -cost and -feeding. Not user-facing; no business commands of its own.
-metadata:
-  author: Junheng NutriAgent
-  version: "1.0.0"
-compatibility: Requires Node.js 18+ (ESM) and a UTF-8 filesystem. No network access and no third-party dependencies. Holds the mirrored source closure (vendor modules) and the ingredient seed database shared by the junheng-* skill family.
----
-
-# 共享计算内核（junheng-core）
-
-## 目的与边界
-
-`junheng-core` 不是给用户提问用的技能，而是 **nutrition / labeling / cost / feeding / pipeline 五个技能共同的地基**：把项目源码单向镜像成技能可直接加载的形态。
-
-| 目录 | 内容 | 唯一真源 |
-|---|---|---|
-| `scripts/vendor/*.js` | **12 个**模块：`nutrition` `dataQuality` `standards` `energy` `bcsChart` `labeling` `costModes` `feedingGuide` `species` `toxicology` `multiPetPlan` `portionLabel` | `src/lib/` |
-| `scripts/data/ingredient_db.js` | 286 条原料种子库 | `src/data/` |
-| `MANIFEST.json` | 每个条目的 sha256 指纹（引用方另记 `coreRef`） | 同步器生成 |
-
-单独成层是为了「一份闭包，五个引用方」：换法规或换种子库**只改一处**，漂移只在这一处报，引用方经 `coreRef` 校验版本。
-
-**边界**：本层**不含逻辑、不新增数值与判定** —— 全部计算能力都在 `src/lib/`，本层只是它的只读镜像。
-
-### 目录布局与一处易踩的坑
-
-数据放 `scripts/data/` 而**不是** `scripts/vendor/data/`：`nutrition.js` 写的是 `import RAW_DB from '../data/ingredient_db.js'`，从 `scripts/vendor/` 出发正好解析到 `scripts/data/`，两种布局都成立（零源码改动）；放错位置报 `ERR_MODULE_NOT_FOUND`（已实测）。
-
-## 诚实性红线
-
-1. 本层**不含任何逻辑**，只是 `src/lib/` 与 `src/data/` 的只读镜像。
-2. **不得在技能侧改本层内容** —— 会被判 `MIRROR_TAMPERED`；应改源码再同步。
-3. 本层**不新增数值、不新增判定** —— 有出入改项目源码，不是这里。
-4. 引用方报告的数值都是**理论计算值**，不是检测值。
-
-## 用法
-
-```bash
-node scripts/sync-skills.mjs          # 改完 src/ 后同步（写盘 + 自动校验）
-node scripts/sync-skills.mjs --check  # 只校验：有漂移 exit 1，源文件缺失 exit 3
-node scripts/sync-skills.mjs --dry    # 预览会同步什么，不写盘
-```
-
-## 命令一览
-
-| 命令（前缀 `node scripts/` 省略） | 作用 |
-|---|---|
-| `sync-skills.mjs` | 同步门面 + 镜像 + MANIFEST（写盘），结束自动校验 |
-| `sync-skills.mjs --check` | 只校验不写盘；有漂移 exit 1，源文件缺失 exit 3 |
-| `sync-skills.mjs --dry` | 只打印同步计划，不写盘 |
-
-**参数详表、输出字段表、可运行示例** → [详细接口参考](references/interface-reference.md)。
-
-## 失败处理（退出码）
-
-| 退出码 | 含义 |
-|---|---|
-| 0 | 校验一致，或同步成功 |
-| 1 | 检出**漂移**（跑一次同步即可修复），或同步后仍有漂移 |
-| 2 | 用法 / 输入错误（未知选项、`--skills-dir` 缺参数） |
-| 3 | **前置条件缺失**：计划里声明的**源文件**不在磁盘上（`SOURCE_MISSING`）—— 同步**也修不了**，须先补源 |
-
-> **为什么 3 不并进 1**：漂移的下一步动作是「跑同步」，源缺的下一步动作是「去补仓库里的文件」。
-> 两者混成一个码，调用方就只能靠 grep 日志分辨该重试还是该报缺件。
-
-`--check` 给每条问题打 `code`，对症处理：`SOURCE_DRIFTED`（源变了 → 跑同步）、`MIRROR_TAMPERED`（镜像被改 → 改回源）、`BOTH_CHANGED`（两边都变 → 先定夺回写谁）、`CORE_REF_MISMATCH` / `CORE_MISSING`（核心版本不符 / 缺失 → 跑同步）、**`SOURCE_MISSING`（源文件不存在 → 退出码 **3**，先补源，同步救不了）**、其余 `MISSING_MANIFEST` / `BAD_MANIFEST` / `MISSING_ENTRY` / `MISSING_FILE` / `EXTRA_FILE`（目录未同步或清单不一致 → 修正后跑同步）。
-
-## 拒答与替代路径
-
-> 本节是**可机检**的边界契约（规范与判据见 `docs/技能边界与拒答契约_2026-10-13.md`）。
-> 命中某一类时，按该类「话术」回复并给出「替代」路径；标「不适用」的类必须写明本技能层面的理由。
-
-### R1 非犬猫物种
-- **不适用**：本层不接收物种参数，物种适用性由调用方门面判定；本层只做源码只读镜像。
-
  ...(+103 more diff lines)

### junheng-nutrition / SKILL.md
  diff_lines=198  src_sz=5754 mir_sz=5981
--- C:/Users/Administrator/WorkBuddy/2026-10-09-19-00-38/nutrition-agent-work/cli/skills\junheng-nutrition\SKILL.md	2026-10-30 21:22:14.312685400 +0800
+++ C:/Users/Administrator/.workbuddy/skills\junheng-nutrition\SKILL.md	2026-11-05 17:20:16.732532600 +0800
@@ -1,98 +1,97 @@
----
-name: junheng-nutrition
-description: 宠物食品原料库查询与配方营养计算。按名称或物料编号查 286 条原料（成分/价格/数据状态），或按配方加权算营养素组成、多口径能量、钙磷比与成本并给出数据覆盖率与缺口；也可算 RER/MER。问原料含量、配方营养时使用。
-description_en: Pet food ingredient database lookup and recipe nutrient computation (Junheng NutriAgent). Look up any of 286 ingredients by name or code, or compute a recipe's nutrient profile, energy (GE/DE/ME with multiple methods), Ca:P ratio, cost, plus data coverage and gaps; also computes individual requirements (RER/MER).
-metadata:
-  author: Junheng NutriAgent
-  version: "1.1.0"
-compatibility: Requires Node.js 18+ (ESM) and a UTF-8 filesystem. No network access and no third-party dependencies. Loads its computation closure from the sibling shared-core skill junheng-core via the relative path ../../junheng-core/.
----
-
-# 原料库与配方计算（junheng-nutrition）
-
-## 目的与边界
-
-**做什么**：回答「某个原料有什么成分」与「某个配方算出来是多少」。
-
-**不做什么**：
-
-- **不做配方** —— 本技能算的是「给定原料与配比的营养结果」，不替你选原料、不当配方师。
-- **不给合规结论** —— 限值判定请用 `junheng-labeling`；这里只出数值。
-- **不做标签排版** —— 标签稿请用 `junheng-labeling`。
-- **不猜测原料** —— 库里没有的原料会进 `unknown` 列表并明确报出，不会静默按 0 计。
-- **单价不含税、不含议价** —— 价格口径为原料库 ¥/kg。
-
-## 诚实性红线
-
-1. **全部为理论计算值，不是检测值**。每次输出带 `basis: "theoretical"`。
-2. **缺数据必须显式**。缺成分的原料进 `zeroData`，无价格的进 `cost.missingPrice`；覆盖率不足时结果会标低可靠度。**先看这几个字段再看数值**。
-3. **未匹配的原料不静默丢弃**。`unknown` 列出所有没找到的原料名/编号。
-4. **总重为 0 不出数**。返回 `ok:false` + 原因，而不是给一堆 0。
-
-## 用法
-
-在技能根目录下执行：
-
-```
-node scripts/cli.mjs <命令> '<JSON 参数>'
-node scripts/cli.mjs <命令> --stdin          # 参数从标准输入读
-node scripts/cli.mjs --help
-node scripts/cli.mjs <命令> --help
-```
-
-> ⚠ 本技能依赖共享内核 `junheng-core`。若报「找不到源码目录」，先同步：`node scripts/sync-skills.mjs`。
-
-## 命令一览
-
-| 命令 | 用途 |
-|------|------|
-| `ingredients` | 按关键词查原料（名称/编号片段），返回成分、价格与数据状态 |
-| `recipe` | 按配方（原料+重量）算营养素、能量、钙磷比与成本 |
-| `analyze-label` | 按标签上的原样基础营养值算干物质基/能量/钙磷比（不做 OCR） |
-| `requirements` | 算个体营养需求（RER / MER + 生命阶段系数） |
-| `dose2formula` | 把「每天该摄入多少 mg」换算成「配方添加比例%」（含纯度/存留率折减与反向达成度） |
-| `evaluate` | 把配方结果与需求逐项对照（不替你下「达标」结论） |
-| `parse-recipe-text` | 把自由文本配方解析成结构化条目 |
-| `describe` | 输出机器可读的接口说明 |
-
-**参数详表、输出字段表、可运行示例、传参注意** → [详细接口参考](references/interface-reference.md)。
-
-> `dose2formula` **只做换算，不判断合规**：它把「每天该摄入多少」变成「配方加百分之几」，
-> 本身不含任何 FEDIAF / AAFCO / GB 限值。要回答「是否达标 / 是否超限」，
-> 须由调用方提供现行标准的限值与依据 —— 不得由本技能代填（见 R3）。
-
-## 失败处理（退出码）
-
-| 退出码 | 含义 |
-|--------|------|
-| 0 | 成功。注意：**「算不出」也是 0** —— 请看 `ok` 与 `reason` |
-| 1 | 内部错误（未预期异常） |
-| 2 | 用法或输入错误，命令未执行 |
-| 3 | 前置条件缺失（共享内核未同步） |
-
-失败时 stdout 为空，stderr 是一行 JSON：`{"ok":false,...}`。`error.details[]` 逐条给出出错参数路径（数组错误定位到 `items[2].weight` 这一级）。
-
-## 拒答与替代路径
-
-> 本节是**可机检**的边界契约（规范与判据见 `docs/技能边界与拒答契约_2026-10-13.md`）。
  ...(+118 more diff lines)

### junheng-labeling / SKILL.md
  diff_lines=447  src_sz=13531 mir_sz=13487
--- C:/Users/Administrator/WorkBuddy/2026-10-09-19-00-38/nutrition-agent-work/cli/skills\junheng-labeling\SKILL.md	2026-10-30 21:22:14.286027900 +0800
+++ C:/Users/Administrator/.workbuddy/skills\junheng-labeling\SKILL.md	2026-11-05 16:31:49.871451500 +0800
@@ -1,223 +1,221 @@
----
-name: junheng-labeling
-description: 配方 → 合规标签底稿生成（钧衡 NutriAgent 出品）。把配方与个体需求生成一份可提交的标签底稿：营养保证值表（按法规要求的项目与顺序，带条款出处）、配料表（按重量递减）、逐项合规结论与风险提示、以及必须随稿给出的声明。当用户问「帮我做一份标签底稿」「营养保证值怎么写」「配料表是什么顺序」「这个配方合不合规」「标签上要标哪些项目」「生成标签文本」时使用。
-description_en: Generate a compliant pet food label draft from a recipe: guaranteed analysis table (regulated items in order, with clause citations), ingredient list (descending by weight), per-item compliance status, risk notes and mandatory disclaimers.
-metadata:
-  author: Junheng NutriAgent
-  version: "1.0.0"
-compatibility: Requires Node.js 18+ (ESM) and a UTF-8 filesystem. No network access and no third-party dependencies. Loads its computation closure from the sibling shared-core skill junheng-core via the relative path ../../junheng-core/.
----
-
-# 标签底稿生成（junheng-labeling）
-
-## 目的与边界
-
-**做什么**：把「配方数值」排成一份**符合法规项目与顺序要求**的标签底稿，并给出逐项合规结论。
-
-**不做什么**：
-
-- **不是最终合规结论** —— 产物是**底稿**，提交前必须人工与现行法规原文逐条核对。
-- **不自己发明数值** —— 限值全部来自 `standards.js`（条款已核对 GB/T 31216-2014 / 31217-2014）。
-- **不给无数据项下结论** —— 库缺氨基酸等字段的项进 `nodata` 段，**既不算达标也不算未达标**。
-- **不改配方** —— 本技能只呈现，不替你调整配方去满足限值。
-- **不做 OCR** —— 读标签图片请用相应的视觉能力。
-
-## 诚实性红线
-
-1. **是底稿不是定稿**。每次输出都要连 `disclaimers` 一起转述，不得表述成「已合规」。
-2. **未核对的体系必须显式标注**。AAFCO 数值尚未与官方出版物逐项核对（`verified: false`）。
-3. **不可计算不等于通过**。`nodata` 项必须原样报出，不得省略、不得当作达标。
-4. **风险提示必须转述**。`risks[]` 列出「不能直接印」的原因（如超限、缺数据），是使用者最容易漏看的部分。
-5. **配料表排序可追溯**。按占比降序；并列重量时**保持用户录入顺序**（法规对并列无规定）。
-
-## 工作流（三步，顺序不可颠倒）
-
-| 步 | 命令 | 输入 → 输出 |
-|---|------|------------|
-| 1 | `junheng-nutrition recipe` | `items[]` → **recipe data** |
-| 2 | `junheng-nutrition requirements` | `species` / `weightKg` → **req data** |
-| 3 | **本技能 `draft`** | `{"recipe":…,"req":…}` → **draft data** |
-
-第 3 步之后分两条支路：`render` / `coverage` 只吃第 3 步的 `draft`；`guaranteed` /
-`ingredients-list` 只吃第 1、2 步的 `recipe` + `req`（不需要 `draft`）。两路都不必重跑前序。
-
-**中间产物不能手捏**：第 1~3 步的 `data` 是**形状契约**的一部分 —— `draft` 校验 `recipe` 的
-`dmPercent` / `asFed.crude_protein` / `energy.meModified` / `lines[]`；`render` / `coverage` 校验
-`draft` 的 `product` / `basis` / `guaranteed.rows` / `ingredients.items` / `risks[]`。缺任一项会被
-`exit 2` **点名拒绝**，而不是产出一份半截稿子。
-
-> 想一步跑完 1~3 步（外加成本与喂食），用 `junheng-pipeline` 的 `run`。
-
-## 用法
-
-在技能根目录下执行 `node scripts/cli.mjs <命令> '<JSON 参数>'`（或 `--stdin` / 管道传参；
-`--help` 与 `<命令> --help` 分别看全部命令与该命令的参数表）。
-
-> ⚠ 依赖共享内核 `junheng-core`。报「找不到源码目录」时先跑 `node scripts/sync-skills.mjs`。
-
-## 命令一览
-
-| 命令 | 用途 |
-|------|------|
-| `draft` | 生成完整标签底稿（保证值 + 配料表 + 合规 + 风险 + 声明） |
-| `guaranteed` | 只取营养保证值表 |
-| `ingredients-list` | 只取配料表 |
-| `render` | 把底稿渲染成可直接粘贴的纯文本 |
-| `coverage` | 查底稿覆盖率（哪些项有据可依、哪些缺数据） |
-| `disclaimers` | 查必须随稿给出的声明清单 |
-| `describe` | 输出机器可读的接口说明 |
-
-**参数详表、输出字段表、可运行示例** → [详细接口参考](references/interface-reference.md)。
-
-## 失败处理（退出码）
-
-| 退出码 | 含义 |
-|--------|------|
-| 0 | 成功，结果在 stdout 的 JSON 里 |
-| 1 | 内部错误（未预期异常） |
  ...(+367 more diff lines)

### junheng-cost / SKILL.md
  diff_lines=244  src_sz=6151 mir_sz=7701
--- C:/Users/Administrator/WorkBuddy/2026-10-09-19-00-38/nutrition-agent-work/cli/skills\junheng-cost\SKILL.md	2026-10-30 21:22:14.210825300 +0800
+++ C:/Users/Administrator/.workbuddy/skills\junheng-cost\SKILL.md	2026-11-05 16:31:49.855431900 +0800
@@ -1,105 +1,136 @@
----
-name: junheng-cost
-description: 宠物食品配方成本核算（钧衡 NutriAgent 出品）。把配方（原料+用量）换算成成本行，再按通用（烘焙粮/产品明细表）、冻干、猫条三种口径算成本，含各项加工费、损耗率、收得率与单位成本（元/kg、元/支）。当用户问「这个配方成本多少钱一公斤」「冻干出成率和成本怎么算」「猫条一支成本多少」「加工费怎么摊」「损耗算进去没」时使用。
-description_en: Pet food recipe cost accounting (Junheng NutriAgent). Convert a recipe into cost lines, then compute cost under general / freeze-dry / cat-stick modes with processing fees, loss rate, yield rate and unit cost.
-metadata:
-  author: Junheng NutriAgent
-  version: "1.0.0"
-compatibility: Requires Node.js 18+ (ESM) and a UTF-8 filesystem. No network access and no third-party dependencies. Loads its computation closure from the sibling shared-core skill junheng-core via the relative path ../../junheng-core/.
----
-
-# 配方成本核算（junheng-cost）
-
-## 目的与边界
-
-**做什么**：算「某个配方在某加工口径下的成本是多少」，并把费用与损耗摊到单位成本。
-
-**不做什么**：
-
-- **不是报价** —— 不含税、不含议价、不含利润与渠道加价。只做成本算术。
-- **不猜价格** —— 库里没价的原料按 0 计入并列入 `missingPrice`，**必须向用户提示**。
-- **不替你选口径** —— 通用/冻干/猫条的成本结构不同，选哪个由你判断。
-- **不吃配方结果** —— `costModes` 要的是「成本行」，需先用 `lines` 命令把配方转换（见下）。
-
-## 诚实性红线
-
-1. **是理论成本不是报价**。每次输出带 `basis: "theoretical"` 与免责声明。
-2. **缺价必须显式**。`missingPrice[]` 列出所有无价格原料 —— 缺价会让总成本**偏低**，先看它再看数值。
-3. **损耗与收得率是经验配置**。来自代码内的 `FREEZE_DRY_CONFIG` / `WORKSHOP_LOSS_CONFIG`，实际产线可能有差异，须一并说明。
-4. **口径不同不可比**。通用 / 冻干 / 猫条的成本结构不同（如冻干按「解冻前用料」计、成品出成约 22%），不要把不同口径的数字直接横向比较。
-
-## 工作流（两步，顺序不可颠倒）
-
-| 步 | 命令 | 输入 → 输出 |
-|----|------|-------------|
-| **第 1 步** | `lines` | 配方 `items[{name 或 code, weight(克)}]` → **成本行 `data.lines[]`**（另含 `totalWeight` / `missingPrice[]` / `unknown[]`） |
-| **第 2 步** | 成本命令**四选一** | 成本行 `lines[]` + 该口径的参数 → 单位成本（元/kg、元/支） |
-
-第 2 步四选一：`sheet`（通用/烘焙粮，按批次数+克重）、`freeze-dry`（冻干，按投料→成品）、`cat-stick`（猫条，按规格）、`by-mode`（用 `mode` 切换的**统一入口**，参数是四者的并集）。
-
-**中间产物形状契约** —— 成本行：
-`{ code, name, unit:'kg', ratio(0~1), unitPrice(¥/kg), yieldRate }`。
-
-第 2 步的 `lines` 必须**原样传第 1 步返回的 `data.lines`**（不要手捏；缺 `ratio`/`unitPrice` 会算错且不报错）。串联写法与坑见详参。
-
-## 用法
-
-在技能根目录下执行：
-
-```
-node scripts/cli.mjs <命令> '<JSON 参数>'
-node scripts/cli.mjs <命令> --stdin
-node scripts/cli.mjs --help
-node scripts/cli.mjs <命令> --help
-```
-
-> ⚠ 依赖共享内核 `junheng-core`。报「找不到源码目录」时先跑 `node scripts/sync-skills.mjs`。
-
-## 命令一览
-
-| 命令 | 用途 |
-|------|------|
-| `lines` | 把配方（原料+重量）换算成成本行（**其它成本命令的前置**） |
-| `modes` | 列出可用口径（id 用下划线，如 `freeze_dry`）与各类配置 |
-| `sheet` | 通用成本表（需 `batchCount` + `gramPerBag`，或 `yieldKg`） |
-| `by-mode` | 按口径 id 算成本（`general` / `freeze_dry` / `cat_stick`） |
-| `freeze-dry` | 冻干成本（投料 → 成品，五项加工费 元/吨） |
-| `cat-stick` | 猫条成本（按规格，含车间加工单价与损耗） |
-| `format` | 成本数值格式化工具（与界面口径一致） |
-| `describe` | 输出机器可读的接口说明 |
-
-**参数详表、输出字段表、可运行示例、传参与串联注意** → [详细接口参考](references/interface-reference.md)。
-
-## 失败处理（退出码）
-
-| 退出码 | 含义 |
-|--------|------|
-| 0 | 成功。注意：**「算不出」也是 0** —— 请看返回里的 `ok:false` 与 `reason` |
  ...(+164 more diff lines)

### junheng-feeding / SKILL.md
  diff_lines=211  src_sz=7036 mir_sz=6981
--- C:/Users/Administrator/WorkBuddy/2026-10-09-19-00-38/nutrition-agent-work/cli/skills\junheng-feeding\SKILL.md	2026-10-30 21:22:14.262835500 +0800
+++ C:/Users/Administrator/.workbuddy/skills\junheng-feeding\SKILL.md	2026-11-05 16:31:49.861725000 +0800
@@ -1,105 +1,103 @@
----
-name: junheng-feeding
-description: 宠物喂食指南与体况管理。按个体档案与配方算每日喂食计划（kcal、克/日、餐次）、体况策略、理想体重、换粮过渡与监测计划；支持多宠聚合产出合并采购清单与按每袋 N 天的分装排期标签。问猫每天吃多少克、BCS 7 分怎么喂时使用。
-description_en: Pet feeding guide and body condition management (Junheng NutriAgent). Compute daily feeding plan (kcal, grams/day, meals), BCS-based energy adjustment, ideal weight estimate, diet transition schedule, monitoring plan and vet-visit signals. Also aggregates multiple pets' plans, produces a combined purchase list merged by material code, and splits daily amounts into labelled portion bags (recipe name, grams per portion, packaging date, use-by date, thawing note).
-metadata:
-  author: Junheng NutriAgent
-  version: "1.2.0"
-compatibility: Requires Node.js 18+ (ESM) and a UTF-8 filesystem. No network access and no third-party dependencies. Loads its computation closure from the sibling shared-core skill junheng-core via the relative path ../../junheng-core/.
----
-
-# 喂食指南与体况管理（junheng-feeding）
-
-## 目的与边界
-
-**做什么**：回答「这只宠物该吃多少、怎么喂、多久复评、什么情况要就医」。
-
-**不做什么**：
-
-- **不是处方** —— 产物是喂养**建议**；目标体重与增减喂食量必须由人（最好含兽医）确认。
-- **不替代实际体况触摸** —— 所有 BCS 判定都以触摸肋骨为准；只看轮廓会被毛量、原始袋、品种骨架误导。
-- **不做疾病诊断** —— 体况评分是筛查工具，不是兽医诊断。
-- **不做配方** —— 需要配方营养结果时用 `junheng-nutrition`，本技能只消费它的输出。
-
-## 诚实性红线
-
-1. **分子分母都要说清**。能量为理论计算值（非检测值）；喂食量取决于所用配方的实际能量。
-2. **体况评分是筛查不是诊断**。不在理想区（犬 4~5 分、猫 5 分）的评分都建议请兽医评估。
-3. **猫的减重必须比犬更慢**。猫减重过快会诱发肝脂沉积症（脂肪肝），可危及生命 —— 这条必须转述。
-4. **目标体重需兽医确认**。`energyAdjPercent` 是经验值不是剂量；不得只凭它大幅调整饲喂。
-5. **禁止只凭输出改变饲喂**。任何调整都应在复评周期内逐步进行并观察。
-6. **不替用户填保质期**。分装标签的「建议食用期限」必须由用户给出保质期天数；未给出时留空并提示「待定」。
-   拿经验值（如「冷冻一般能放 90 天」）填进去，就是把猜想印在贴纸上，而用户会照着它决定还吃不吃。
-
-## 用法
-
-在技能根目录下执行：
-
-```
-node scripts/cli.mjs <命令> '<JSON 参数>'
-node scripts/cli.mjs <命令> --stdin
-node scripts/cli.mjs --help
-node scripts/cli.mjs <命令> --help
-```
-
-> ⚠ 依赖共享内核 `junheng-core`。报「找不到源码目录」时先跑 `node scripts/sync-skills.mjs`。
-> ⚠ `recipe` 与 `req` 来自 `junheng-nutrition`，给了 `recipe` 才能把能量换算成「克/日」。
-> ⚠ 多宠命令（`plan-multi` / `purchase-list` / `portion-label`）：请把 `parseRecipeText` 里**未匹配**的原料一并传进
-> `pets[].unmatched`（`{ rawName, weight }`）。不传的后果有两个 —— 采购清单**不会列出**它们（静默少买），
-> 且这些库外原料**不会被安全闸筛到**（`recipe.lines` 里根本没有它们，库里查不到的禁用原料会因此漏网）。
-> ⚠ `portion-label` 的「建议食用期限」= 分装日期 + `shelfLifeDays`。**不给 `shelfLifeDays` 就留空**，
-> 本技能不猜保质期（贴纸会印「待定」）。缺保质期天数时请先向用户问明，不要把默认天数写进贴纸。
-
-## 命令一览
-
-| 命令 | 用途 |
-|------|------|
-| `plan` | 生成完整喂食计划（能量、克/日、餐次、过渡、监测、储存） |
-| `plan-multi` | 多宠聚合：逐宠算喂食量并合计，同时给出按物料编号归并的合并采购清单 |
-| `purchase-list` | 合并采购清单：只输出按物料编号归并的原料需求量（多宠合计，含未匹配原料） |
-| `portion-label` | 同日分装排期 + 分装标签：把每宠每日用量按「每袋 N 天」拆袋，出可打印贴纸（配方名/每份克数/分装日期/建议食用期限/解冻提示） |
-| `render` | 把喂食计划渲染成可直接粘贴的纯文本 |
-| `bcs-policy` | 按体况评分取喂养策略（能量调整幅度、是否减重、限制原因） |
-| `bcs-scale` | 查 9 分制判据表与分组（**须指定 species**：犬 4~5 分为理想、猫仅 5 分） |
-| `ideal-weight` | 由当前体重与体况评分估算理想体重 |
-| `life-stage` | 判定生命阶段与餐次建议 |
-| `transition` | 换粮过渡计划（默认 7 天） |
-| `monitoring` | 监测计划（按生命阶段与体况策略） |
-| `vet-signals` | 查需要就医的信号清单 |
-| `describe` | 输出机器可读的接口说明 |
-
-**参数详表、输出字段表、可运行示例** → [详细接口参考](references/interface-reference.md)。
-
-## 失败处理（退出码）
-
-| 退出码 | 含义 |
-|--------|------|
-| 0 | 成功。注意：**「算不出」也是 0** —— 请看 `ok` 与原因字段 |
  ...(+131 more diff lines)

### junheng-pipeline / SKILL.md
  diff_lines=197  src_sz=5923 mir_sz=5861
--- C:/Users/Administrator/WorkBuddy/2026-10-09-19-00-38/nutrition-agent-work/cli/skills\junheng-pipeline\SKILL.md	2026-10-30 21:22:14.364865200 +0800
+++ C:/Users/Administrator/.workbuddy/skills\junheng-pipeline\SKILL.md	2026-11-05 16:31:49.886588800 +0800
@@ -1,98 +1,96 @@
----
-name: junheng-pipeline
-description: 跨技能串联编排。一次调用跑完配方营养、个体需求、标签底稿、成本与喂食计划全套计算，替代手工搬运中间结果；多宠入口一次产出逐宠喂食量、合计采购清单与分装排期标签。问把配方完整评估一遍、一条命令跑全套时使用。
-description_en: Cross-skill orchestration. Computes recipe nutrition, individual requirements, label draft, cost sheet and feeding plan in a single call, replacing manual shuttling of 5-6 KB intermediate objects between skills. A multi-pet entry (run-multi) additionally goes from each pet's raw ingredients to per-pet feeding amounts, a combined purchase list, and same-day portioning schedules with printable labels.
-metadata:
-  author: Junheng NutriAgent
-  version: "1.1.0"
-compatibility: Requires Node.js 18+ (ESM) and a UTF-8 filesystem. No network access and no third-party dependencies. Loads its computation closure from the sibling shared-core skill junheng-core via the relative path ../../junheng-core/.
----
-
-# 跨技能串联编排（junheng-pipeline）
-
-## 目的与边界
-
-**做什么**：把分散在 4 个技能里的计算串成**一次调用**，消除手工搬运。
-
-**不做什么**：
-
-- **不含独立公式** —— 全部数值来自 `src/lib/` 的既有函数（`computeRecipe` / `computeRequirements` / `buildLabelDraft` / `computeCostSheetByMode` / `computeFeedingPlan`；多宠入口另用 `computeMultiPetPlan` / `computePortionLabels`）。结果与分别调用各技能**逐字段一致**。
-- **不替代单技能调用** —— 只想算一个东西时用对应技能更快，不必走本门面。
-- **不做配方决策** —— 不替用户选原料、不下合规结论。
-- **不静默跳过** —— 每一步都有 `status`（`ok`/`skipped`/`failed`/`error`）与 `reason`。
-
-## 诚实性红线
-
-1. **是编排层不是新算法**。输出里的每个数字都能在对应单技能里复现。
-2. **失败必须可见**。`ok:false` 时看 `summary.failed` 与每步的 `reason`，不要只看 `ok`。
-3. **跳过也要可见**。`summary.skipped > 0` 表示有步骤因缺参数没跑 —— 例如没给 `profile` 就不会算喂食计划，**这不是"算出来是空"**。
-4. **理论值 ≠ 检测值**；标签部分是**底稿不是定稿**；喂食部分是**建议不是处方**。
-5. **分装标签是厨房贴纸，不是合规标签**。`run-multi` 的 `portions` 只回答「这袋多少克、贴什么字」；
-   合规标签（保证值表 / 配料表）仍走 `junheng-labeling draft`。
-6. **不替用户填保质期**。`run-multi` 的「建议食用期限」必须在给了 `shelfLifeDays` 时才有值；
-   未给则留空并印「待定」—— 拿经验值填进去等于把猜想印在贴纸上。
-
-## 用法
-
-```
-node scripts/cli.mjs run '<JSON 参数>'
-node scripts/cli.mjs steps '{}'          # 只列步骤与所需参数，不计算
-node scripts/cli.mjs --help
-```
-
-> ⚠ 依赖共享内核 `junheng-core`。报「找不到源码目录」时先跑 `node scripts/sync-skills.mjs`。
-
-## 命令一览
-
-| 命令 | 用途 |
-|------|------|
-| `run` | 一次调用完成全套 5 步 |
-| `run-multi` | **多宠入口**：逐宠「原料→营养→需求→喂食量」→ 合计与合并采购清单 → 同日分装排期与分装标签 |
-| `steps` | 只列出会执行哪些步骤、各需要什么（排错与自检用；含 `multi` 段列 `run-multi` 的四步） |
-| `describe` | 输出机器可读的接口说明 |
-
-**参数详表、输出字段表、可运行示例、单步管道 `--as`** → [详细接口参考](references/interface-reference.md)。
-
-## 失败处理（退出码）
-
-| 退出码 | 含义 |
-|--------|------|
-| 0 | 命令执行完毕。注意：**步骤失败/跳过也是 0** —— 请看 `summary` 与各步 `reason` |
-| 1 | 内部错误（未预期异常） |
-| 2 | 用法或输入错误，命令未执行 |
-| 3 | 前置条件缺失（共享内核未同步） |
-
-## 与单技能的关系（该用哪个）
-
-| 场景 | 用什么 |
-|---|---|
-| 只算配方营养 | `junheng-nutrition recipe` |
-| 只出标签稿 | `junheng-labeling draft` |
-| 完整评估（多步） | **本门面 `run`** |
-| 多宠 + 采购清单 + 分装标签 | **本门面 `run-multi`**（只想单独做一段时用 `junheng-feeding` 的 `plan-multi` / `portion-label`） |
-| 想在 shell 里把某一步的结果接到下一步 | 任一技能 + `--as <参数名>`（见详参） |
-
-## 拒答与替代路径
-
-> 本节是**可机检**的边界契约（规范与判据见 `docs/技能边界与拒答契约_2026-10-13.md`）。
  ...(+117 more diff lines)

### junheng-attainment / SKILL.md
  diff_lines=227  src_sz=6199 mir_sz=6014
--- C:/Users/Administrator/WorkBuddy/2026-10-09-19-00-38/nutrition-agent-work/cli/skills\junheng-attainment\SKILL.md	2026-10-30 21:22:14.142620100 +0800
+++ C:/Users/Administrator/.workbuddy/skills\junheng-attainment\SKILL.md	2026-11-05 16:31:49.829879700 +0800
@@ -1,113 +1,111 @@
----
-name: junheng-attainment
-description: 配方目标达成度评估（钧衡 NutriAgent 出品）。给定配方与目标画像（物种/月龄/体况/目标市场），逐项对照法规限值，输出四态结论（达标 / 未达标 / 数据不足 / 无法判定）、缺口清单与配比建议。当用户问「这个配方达不达标」「差在哪」「离标准还差多少」「按国标能不能过」「钙磷比够不够」「粗蛋白差几个点」时使用。
-description_en: Recipe attainment evaluation. Compares a formula against regulatory limits for a target profile (species / age / market) and reports per-nutrient status, the shortfall list and mixing suggestions.
-metadata:
-  author: Junheng NutriAgent
-  version: "1.0.0"
-compatibility: Requires Node.js 18+ (ESM) and a UTF-8 filesystem. No network access and no third-party dependencies. Loads its computation closure from the sibling shared-core skill junheng-core via the relative path ../../junheng-core/.
----
-
-# 目标达成度评估（junheng-attainment）
-
-## 目的与边界
-
-**做什么**：一次调用回答「**这个配方，对这个目标对象，达不达标、差在哪**」。
-
-输入是**原料清单 + 目标画像**，输出是**逐项四态结论 + 缺口清单 + 配比建议**。
-
-**不做什么**：
-
-- **不含独立公式** —— 判定全部来自 `src/lib/nutrition.js` 的 `evaluateRecipe`，
-  与界面「⑤ 达标评估」、配方体检、标签稿的合规段**同一口径**；本门面不写任何限值数字。
-- **不替代 `junheng-nutrition recipe`** —— 那个只算**营养组成**（不判断达标与否）。
-- **不替用户做配方决策** —— 给缺口与建议，不给「这个配方能卖」的结论。
-- **不谎报未达标** —— 数据不足时如实标 `nodata` / `low`，算法见下。
-
-## 诚实性红线（★ 最要紧的一节）
-
-**四态，不是两态**。把 `nodata` 读成「未达标」是本项目最危险的误读：
-
-| `status` | 含义 | 该怎么说 |
-|---|---|---|
-| `ok` | 达标 | 「已达标准」 |
-| `fail` | 未达标 | 「低于下限 / 高于上限 X」 |
-| `low` | 数值达标，但**该指标覆盖的原料有数据缺口** | 「达标，但结论仅供参考（覆盖率 N%）」 |
-| `nodata` | **无法判定**（原料库无此字段，或本配方算不出） | 「**无法判定**，缺数据」—— **绝不能说成「未达标」** |
-
-> 原料库没有氨基酸字段，所以**赖氨酸 / 牛磺酸几乎总是 `nodata`**。这是数据缺口，不是配方缺陷。
-
-两个汇总标志**不可互相替代**：
-
-- `summary.allPass` —— 「**没有明确未达标项**」，`nodata` 项**不计入**（原样取自 evaluateRecipe）。
-- `summary.fullyVerified` —— 「**所有项都验过、且都达标**」。要下「全面达标」的结论**只能用它**。
-
-其余：`gap` 是**展示用算术差**（判定口径以 `status` 为准）；理论值 ≠ 检测值。
-
-## 用法
-
-```
-node scripts/cli.mjs assess  '<JSON 参数>'
-node scripts/cli.mjs targets '{}'        # 先看有哪些目标口径可选，不计算
-node scripts/cli.mjs --help
-```
-
-> ⚠ 依赖共享内核 `junheng-core`。报「找不到源码目录」时先跑 `node scripts/sync-skills.mjs`。
-
-## 命令一览
-
-| 命令 | 用途 |
-|------|------|
-| `assess` | 逐项达标度 + 缺口清单 + 配比建议 |
-| `targets` | 列出可用目标口径（市场 × 物种 × 阶段） |
-| `describe` | 输出机器可读的接口说明 |
-
-**参数详表、输出字段表、可运行示例** → [详细接口参考](references/interface-reference.md)。
-
-## 失败处理（退出码）
-
-| 退出码 | 含义 |
-|--------|------|
-| 0 | 评估执行完毕。**配方未达标也是 0** —— 请看 `summary` 与 `gaps` |
-| 1 | 内部错误（未预期异常） |
-| 2 | 用法或输入错误，命令未执行 |
-| 3 | 前置条件缺失（共享内核未同步） |
-
-## 与相关技能的分工（该用哪个）
-
  ...(+147 more diff lines)


# MIRROR_TAMPERED SKILL.md (mirror edited, source unchanged)

### junheng-standards / SKILL.md
  diff_lines=339  src_sz=10566 mir_sz=10532
--- C:/Users/Administrator/WorkBuddy/2026-10-09-19-00-38/nutrition-agent-work/cli/skills\junheng-standards\SKILL.md	2026-10-30 21:22:14.413571500 +0800
+++ C:/Users/Administrator/.workbuddy/skills\junheng-standards\SKILL.md	2026-11-05 16:31:49.896241400 +0800
@@ -1,169 +1,167 @@
----
-name: junheng-standards
-description: 宠物营养法规限值查询。按目标市场、物种、生命阶段与水分形态返回应同时满足的合并限值（蛋白、脂肪、灰分、纤维、钙磷、赖氨酸、牛磺酸、代谢能等），每项带条款出处与各体系原值；也可单查条款原文。问 AAFCO 下限、国标要求时使用。
-description_en: Chinese and international pet food nutrient limit lookup (GB/T 31216, GB/T 31217, AAFCO, FEDIAF) by market mode, species, life stage and moisture class; returns merged limits with clause citations, or a single clause's original text.
-metadata:
-  author: Junheng NutriAgent
-  version: "1.0.0"
-compatibility: Requires Node.js 18+ (ESM) and a UTF-8 filesystem. No network access and no third-party dependencies. Self-contained CLI facade; no dependency on other junheng-* skills.
----
-
-# 法规限值查询（junheng-standards）
-
-## 目的与边界
-
-**做什么**：回答「某类宠物食品在某市场、某生命阶段下，某营养项的限值是多少、出自哪一条」。
-
-**不做什么**（明确边界，避免误用）：
-
-- **不判定某个配方是否达标** —— 本技能只给限值，不给配方结论。需要判定请用配方营养计算能力。
-- **不返回检测值** —— 全部是条文引用值。
-- **不提供 AAFCO 现行版本年份的结论** —— AAFCO 数值尚未与官方出版物逐项核对（`verified: false`）。
-- **FEDIAF 不参与判定** —— 其主表以「每 MJ 代谢能」为基准，本轮数值待补，只登记不判。
-
-## 诚实性红线
-
-1. **限值必须有出处**。每个条目都带 `cites`（条款出处）。引用时请连同出处一起给，不要只给数字。
-2. **未核对的体系必须显式标注**。AAFCO 条目 `verified: false`，输出中会带 `note`；不得把它的数值当作已确认结论对外交付。
-3. **不可计算不等于通过**。系统无数据支撑的项目（如赖氨酸、牛磺酸）会返回 `available: false`、`active: false`，**绝不会**被算作「达标」。
-4. **换法规版本只改一个地方**。限值的唯一真源是项目内 `src/lib/standards.js`；改版本时改它并重新同步，不要在本技能内直接改数据。
-
-## 用法
-
-```
-node scripts/cli.mjs <命令> '<JSON 参数>'    # 参数必须是一个 JSON 对象
-node scripts/cli.mjs <命令> --stdin          # 参数从标准输入读（避免 shell 转义问题）
-node scripts/cli.mjs --help                  # 全部命令与退出码
-```
-
-## 命令一览
-
-| 命令 | 用途 |
-|------|------|
-| `list-markets` | 列出目标市场模式（决定要同时满足哪些标准体系） |
-| `list-sets` | 列出已登记的标准体系及其可信度状态 |
-| `resolve` | 解析合并后的营养限值表（多体系取最严，逐项带出处） |
-| `clause` | 查单一营养项的条款原文与出处 |
-| `classify-moisture` | 按水分百分比判定形态分级 |
  ...(+289 more diff lines)

### junheng-energy / SKILL.md
  diff_lines=177  src_sz=4874 mir_sz=4759
--- C:/Users/Administrator/WorkBuddy/2026-10-09-19-00-38/nutrition-agent-work/cli/skills\junheng-energy\SKILL.md	2026-10-30 21:22:14.237918000 +0800
+++ C:/Users/Administrator/.workbuddy/skills\junheng-energy\SKILL.md	2026-11-05 16:31:49.858457600 +0800
@@ -1,88 +1,86 @@
----
-name: junheng-energy
-description: 宠物食品能量计算。按常规成分算总能 GE、消化能 DE、代谢能 ME（改良 Atwater、经典 Atwater、NRC 三步法三种口径）、ME:GE 比、供能比、能量消化率与静息能量需求 RER；也可单查能量系数与出处。问配方代谢能、RER 怎么算时使用。
-description_en: Pet food energy computation (GE/DE/ME with modified-Atwater, classic Atwater and NRC three-step methods, ME:GE ratio, energy source distribution, digestibility, resting energy requirement) from as-fed proximate composition; plus coefficient and citation lookup.
-metadata:
-  author: Junheng NutriAgent
-  version: "1.0.0"
-compatibility: Requires Node.js 18+ (ESM) and a UTF-8 filesystem. No network access and no third-party dependencies. Self-contained CLI facade; no dependency on other junheng-* skills.
----
-
-# 能量计算（junheng-energy）
-
-## 目的与边界
-
-**做什么**：从原样基础常规成分算出能量学指标，每一口径给出明确出处。
-
-**不做什么**：
-
-- **不做配方** —— 输入是已经算好的常规成分（%），不是原料清单。原料 → 成分请用配方营养计算能力。
-- **不给 MER / 每日喂食量** —— 本技能只到 RER（静息需求）。MER 还要乘生命阶段、绝育、活动等系数，不在本技能范围内。
-- **不把「算不出」当 0** —— 水分缺失时 GE / DE / NRC 代谢能返回 `null`，同时在 `note` 里说明原因。
-
-## 诚实性红线
-
-1. **理论计算值不等于检测值**。每次输出都带 `basis: "theoretical"`，实测值与计算值通常有差异。
-2. **外推必须标注**。消化率方程是线性回归式，干物质基粗纤维超过 10% 时进入外推区，输出带 `digestibilityExtrapolated: true`，必须一并转述。
-3. **缺失必须显式为 null**。`ge: null` / `meNRC: null` 表示「未算出」，**不得**当作 0 代入后续计算。
-4. **系数不许改写**。`GE_FACTORS_KJ` 是 NRC 按 kJ 独立取整公布的值，**不是** `GE_FACTORS × 4.184`；要换算时必须说明是换算值。
-5. **供能比口径要讲清**。`source` 用的是改良 Atwater（碳水 3.5 kcal/g，标签惯例），与基于 GE 的占比不是一回事。
-
-## 用法
-
-在技能根目录下执行：
-
-```
-node scripts/cli.mjs <命令> '<JSON 参数>'
-node scripts/cli.mjs <命令> --stdin          # 参数从标准输入读
-node scripts/cli.mjs --help
-node scripts/cli.mjs <命令> --help
-```
-
-## 命令一览
-
-| 命令 | 用途 |
-|------|------|
-| `profile` | 算一整套能量学结果（GE / DE / ME 多口径 / ME:GE / 供能比） |
-| `rer` | 算静息能量需求 RER（kcal/日） |
  ...(+127 more diff lines)

### junheng-safety / SKILL.md
  diff_lines=185  src_sz=6160 mir_sz=6049
--- C:/Users/Administrator/WorkBuddy/2026-10-09-19-00-38/nutrition-agent-work/cli/skills\junheng-safety\SKILL.md	2026-10-30 21:22:14.392016200 +0800
+++ C:/Users/Administrator/.workbuddy/skills\junheng-safety\SKILL.md	2026-11-05 16:31:49.886588800 +0800
@@ -1,92 +1,90 @@
----
-name: junheng-safety
-description: 宠物食品有毒有害物质安全闸。按物种筛查配方中的禁用与慎用物质，返回禁用、慎用、安全、未收录四态结论并带来源机构与判定依据；可批量筛查并在命中禁用时阻断。未收录一律判未收录，绝不当作安全。问巧克力能不能喂狗时使用。
-description_en: Toxic-substance safety gate for pet food. Screens a recipe or a single ingredient for banned and caution substances (chocolate, xylitol, lilies, allium, grapes, macadamia, permethrin) by species, in four states — banned / caution / ok / unknown; unlisted substances are never reported as safe, and a banned hit blocks the recipe.
-metadata:
-  author: Junheng NutriAgent
-  version: "1.0.0"
-compatibility: Requires Node.js 18+ (ESM) and a UTF-8 filesystem. No network access and no third-party dependencies. Self-contained CLI facade; no dependency on other junheng-* skills.
----
-
-# 有毒有害物质安全闸（junheng-safety）
-
-## 目的与边界
-
-**做什么**：回答「某个原料 / 物质，对某物种而言能不能进配方」，并在批量筛查时于**命中禁用条目**处阻断。
-
-**不做什么**（明确边界，避免误用）：
-
-- **不判定营养是否达标** —— 安全与配比是两件事。营养结论请用配方营养计算能力；本技能只回答「能不能吃」。
-- **不给毒理学数值** —— 不提供 LD50、血药浓度、安全摄入量这类未经收录的量化结论。
-- **不提供诊断、用药与剂量** —— 宠物已出现症状时请就医，本技能不承担处置职责。
-- **不声明「安全」** —— 除非有显式来源支撑。绝大多数原料会返回 `unknown`（未收录），这是**如实**，不是缺陷。
-
-## 诚实性红线
-
-1. **未收录一律 `unknown`，绝不 `ok`**。把「查不到」兜底成「安全」，会让安全闸在最该拦的场景静默放行。守卫会构造该变异并判红。
-2. **`unknown` 不是「安全」也不是「不安全」**。对外交付时必须原样报出，不得省略、不得改写成「暂无风险」。
-3. **每条收录都必须能回溯到来源**。输出带 `sources`（机构 / 条目 / 链接 / 抓取日期）；引用时连同来源一起给，不要只给结论。
-4. **`species` 记「来源实际支持的物种」**。百合属、氯菊酯的来源只支持猫 ⇒ 只标 cat：猫配方判 `banned`、犬配方判 `unknown`（不越权外推）。
-5. **本技能是筛查提示，不是毒理学结论**。不构成诊断或治疗建议。
-
-## 用法
-
-在技能根目录下执行：
-
-```
-node scripts/cli.mjs <命令> '<JSON 参数>'
-node scripts/cli.mjs <命令> --stdin          # 参数从标准输入读（避免 shell 转义问题）
-node scripts/cli.mjs --help                  # 全部命令与退出码
-node scripts/cli.mjs <命令> --help           # 单个命令的参数表
-```
-
-参数必须是一个 JSON 对象。含空格或中文时，用单引号把整个 JSON 包住（Windows cmd 下用双引号）。
-
-## 命令一览
-
-| 命令 | 用途 |
  ...(+135 more diff lines)

### junheng-optimize / SKILL.md
  diff_lines=177  src_sz=6147 mir_sz=6032
--- C:/Users/Administrator/WorkBuddy/2026-10-09-19-00-38/nutrition-agent-work/cli/skills\junheng-optimize\SKILL.md	2026-10-30 21:22:14.342141300 +0800
+++ C:/Users/Administrator/.workbuddy/skills\junheng-optimize\SKILL.md	2026-11-05 16:31:49.881884500 +0800
@@ -1,88 +1,86 @@
----
-name: junheng-optimize
-description: 宠物食品配方最低成本逆解。给定原料成本与线性约束求最省配比，返回最优解、目标值、变量取值与边际、约束影子价格；不可行时给出极小冲突集与最小松弛量。只解连续线性模型，不做营养折算与法规判定。问怎么配最省钱时使用。
-description_en: Minimum-cost reverse solver for pet food formulas. Given ingredient costs and linear constraints, returns the cheapest feasible ratio plus dual information (shadow prices, reduced costs), or an infeasibility diagnosis with the minimal conflict set (drop any one member and the model becomes feasible) and the minimal relaxation amount. Continuous linear models only — no nutrient conversion, no unit conversion, no regulatory checks.
-metadata:
-  author: Junheng NutriAgent
-  version: "1.0.0"
-compatibility: Requires Node.js 18+ (ESM) and a UTF-8 filesystem. No network access and no third-party dependencies. Self-contained CLI facade; no dependency on other junheng-* skills.
----
-
-# 配方最低成本逆解（junheng-optimize）
-
-## 目的与边界
-
-**做什么**：回答「按给出的成本与约束，最省钱的配比是多少」，以及「若无解，是哪几条约束在打架、最少要松多少」。
-
-**不做什么**（明确边界，避免误用）：
-
-- **不做营养折算** —— 干物质折算、加工损失系数、单位换算一律不在本技能内。系数必须由调用方算好后写进模型；写错系数，错在模型，不在求解器。
-- **不做合规与安全判定** —— 结果是否合规请用标签 / 标准能力；原料能不能吃请用安全闸能力。本技能只保证「在给定模型下成本最优」。
-- **不回答非线性问题** —— 只解**连续线性**模型（目标与约束都是线性的）。整数约束、分段函数、多目标权衡都给不出结论。
-- **不解释业务含义** —— 影子价格是**数学量**，不是采购报价，也不是建议价。它只说明「右端动一点，最优值动多少」。
-
-## 诚实性红线
-
-1. **不可行 ≠ 现实中配不出来**。`infeasible` 只说明「在这套系数与约束下没有可行点」，几乎总是建模问题（约束矛盾、漏了松弛、量纲不齐）。必须原样报出，并指向 `diagnose`。
-2. **非最优时不给任何数值**。求解器不返回近似解，门面也不给残缺的配比 —— `objective` / `values` / 影子价格一律为 `null`。不得用「差不多」的数糊过去。
-3. **`unknown` 不是「可行」**。迭代上限、自检失败属于「没能判定」，诊断会返回 `unknown`；它既不是可行也不是不可行，不得归入任一结论。
-4. **影子价格只在本点附近成立**。只对绑定约束有意义，且只在该最优解的邻域内成立，**不可外推**为大范围结论。
-5. **无界 ≠ 不可行**。`unbounded` 说明「有可行点但没有最优解」（通常是漏了上界），诊断会判 `feasible` 并明确区分。
-
-## 用法
-
-在技能根目录下执行：
-
-```
-node scripts/cli.mjs <命令> '<JSON 参数>'
-node scripts/cli.mjs <命令> --stdin          # 参数从标准输入读（避免 shell 转义问题）
-node scripts/cli.mjs --help                  # 全部命令与退出码
-node scripts/cli.mjs <命令> --help           # 单个命令的参数表
-```
-
-## 命令一览
-
-| 命令 | 用途 |
-|------|------|
-| `solve` | 求最低成本配比（返回配比、影子价格、变量边际） |
  ...(+127 more diff lines)


# MIRROR_TAMPERED logic files (possible real fixes lost on revert)

### junheng-core / scripts/vendor/nutrition.js
  source_ex=False mirror_ex=True

### junheng-core / scripts/vendor/labeling.js
  source_ex=False mirror_ex=True

### junheng-core / scripts/vendor/feedingGuide.js
  source_ex=False mirror_ex=True

### junheng-core / scripts/vendor/multiPetPlan.js
  source_ex=False mirror_ex=True

### junheng-core / scripts/vendor/portionLabel.js
  source_ex=False mirror_ex=True

### junheng-pipeline / scripts/cli.mjs
  source_ex=False mirror_ex=True