# 技能 SKILL.md frontmatter 字段声明表

> 任务 (x)：36+ 种 frontmatter 字段里，哪些**真被消费**，哪些是从未读取的死字段 / 重叠冗余字段。
> 目的：为后续 skill 治理（去重、清理、统一规范）提供可追溯的依据，而非凭印象删字段。

## 0. 扫描实况（可复现）

- 范围：`~/.workbuddy/skills/`（用户技能，**不含** `plugins/` 下的平台内置副本——那些会污染统计）
- 样本：**93 个 SKILL.md，全部含 frontmatter**（0 缺失）
- 字段数：**顶层唯一字段 37 个，含嵌套全部层级 54 个**
  - 备注：此前口称"36 种"是略估；精确值是 37 顶层。
- 方法：PowerShell 递归提取每个 SKILL.md 首段 `---` 之间的 YAML key（缩进 0 记为顶层）。

## 1. 消费方实证（不是猜）

### 1.1 平台官方（已查证两份文档）

- **WorkBuddy 开放平台** `open.workbuddy.cn/docs/skill` 标准 frontmatter 字段：
  `name`(必填/标识) · `display_name`(必填/中文展示名) · `display_name_en`(必填) ·
  `description`(必填/用途+触发词) · `description_zh`(必填/详情页) · `description_en`(必填) ·
  `version`(必填) · `author`(必填/合作方) · `allowed-tools`(逗号分隔白名单) ·
  `examples_zh` / `examples_en`(详情页"试试这样用")
- **WorkBuddy Code/CLI** `workbuddy.ai/docs/cli/skills` 标准字段：
  `name`(缺省取目录名) · `description` · `allowed-tools` ·
  `disable-model-invocation`(true=不出现在 Skill 工具，仅 `/skill-name` 手动) ·
  `user-invocable`(false=隐藏于 `/` 菜单，仅内部 AI 调用) ·
  `context`(fork=隔离子 agent) · `agent` · `model` · `hooks`

### 1.2 本地脚本（本机可证伪）

| 脚本 | 是否读 frontmatter | 消费的字段 | 证据 |
|---|---|---|---|
| `tools/check-skill-format.mjs` | 是 | `name` + `description`(含 `description_zh`/`description_en`) | 源码 F3 必查 name 与 description；注释明示"description 决定它会不会被选中" |
| `packages/.../skills-manifest.mjs` | **否** | 无 | 用**硬编码** `SKILLS` 表（facade/vendor/data/core/references），完全不解析 frontmatter |
| `sync-skills.mjs` | **否** | 无 | 调用 skills-manifest 的计划，从不读 SKILL.md 字段 |
| `skills/_governance/lint_scripts.py` S5 | 仅检测 | 重叠组（不消费） | 注释："platform 到底读哪个未知" |
| `tools/rules_lint.py` | 否（查 rules） | 不适用 | 只校验 `.mdc` 规则的 frontmatter |

**关键结论**：junheng 技能同步体系**完全不依赖 frontmatter 字段**（同步清单来自代码表）。frontmatter 字段的唯一真实消费方是 **WorkBuddy 平台本身**（按官方文档）与 `check-skill-format` 的 name/description 校验。

## 2. 字段声明表（37 顶层字段全部分类）

分类图例：
- **A 平台标准**：官方文档证实消费
- **B 本地脚本消费**：check-skill-format 实证
- **C 第三方工具字段**：skill-manager 跨平台映射用，WorkBuddy 官方文档未列
- **D 重叠/冗余**：lint S5 组，platform 读哪个未知，建议统一
- **E 死字段**：任何消费方均未读取

| # | 字段 | 次数 | 分类 | 消费方/依据 | 处置 |
|---|---|---:|---|---|---|
| 1 | `name` | 93 | A+B | 平台标识 + check-skill-format 必查 | 保留（核心） |
| 2 | `description` | 93 | A+B | 平台触发 + check-skill-format 必查 | 保留（核心） |
| 3 | `version` | 63 | A | 开放平台必填 | 保留；但 scripts 体系不读（硬编码表） |
| 4 | `description_en` | 62 | A | 开放平台必填 | 保留（双语规范） |
| 5 | `description_zh` | 48 | A | 开放平台必填 | 保留（双语规范） |
| 6 | `display_name` | 46 | A | 开放平台必填展示名 | 保留 |
| 7 | `display_name_en` | 40 | A | 开放平台必填 | 保留 |
| 8 | `author` | 24 | A | 开放平台必填（**独立顶层字段**） | 保留；从 `metadata.author` 提到顶层 |
| 9 | `allowed-tools` | 12 | A | CLI 工具白名单 | 保留 |
| 10 | `disable-model-invocation` | 2 | A | CLI 标准 | 保留（按需） |
| 11 | `user-invocable` | 1 | A | CLI 标准（默认 true） | 保留（按需） |
| 12 | `metadata` | 23 | C | 第三方 skill-manager"自定义元数据"；官方开放平台**未列** | 拆出 `author`/`version` 到顶层，余下仅第三方工具用 |
| 13 | `license` | 20 | C | 第三方映射 WorkBuddy 保留 license；官方开放平台文档未列 | 可保留（跨平台工具需要） |
| 14 | `compatibility` | 12 | C | 第三方 skill-manager 跨平台字段；官方未列 | **建议删除**（junheng-core 写成一整段字符串，平台不读） |
| 15 | `slug` | 5 | D | 与 `name` 重叠（S5 组） | 删（name 即标识） |
| 16 | `displayName` | 5 | D | `display_name` 的驼峰拼写变体（S5 组） | 统一为 `display_name` |
| 17 | `summary` | 3 | D | 与 `description` 重叠（S5 组） | 删（description 已涵盖） |
| 18 | `category` | 10 | D | 与 `domain`/`type` 重叠（S5 组） | 选其一（建议 category） |
| 19 | `domain` | 1 | D | 重叠组 | 删（并入 category） |
| 20 | `type` | 1 | D | 重叠组 | 删（并入 category） |
| 21 | `tags` | 16 | D | 与 triggers/trigger_words/auto_trigger 重叠（S5 组）；skill-manager classifier 用 name+description 关键词，**不读 tags 字段本身** | 删或并入 description 触发词 |
| 22 | `triggers` | 1 | D | 重叠组 | 删（触发词放 description） |
| 23 | `trigger_words` | 1 | D | 重叠组 | 删 |
| 24 | `auto_trigger` | 1 | D | 重叠组 | 删 |
| 25 | `visibility` | 16 | E | 任何消费方均未列 | **死字段，建议删** |
| 26 | `agent_created` | 11 | E | 仅腾讯云社区文章提及，官方两文档未列 | **死字段，建议删** |
| 27 | `dependencies` | 9 | E | 官方未列；junheng 用硬编码表不用它 | **死字段，建议删** |
| 28 | `homepage` | 3 | E | 未消费 | 删 |
| 29 | `display_name_zh` | 2 | E | 开放平台用 `display_name`+`display_name_en`，无 zh 变体；作者自创 | 删（并入 display_name） |
| 30 | `source` | 2 | E | 未消费 | 删 |
| 31 | `changelog` | 1 | E | 未消费 | 删 |
| 32 | `emoji` | 1 | E | 未消费 | 删 |
| 33 | `github` | 1 | E | 未消费 | 删 |
| 34 | `parentSkill` | 1 | E | 未消费 | 删 |
| 35 | `title` | 1 | E | 未消费 | 删 |
| 36 | `argument-hint` | 1 | E | 疑似 slash command 字段误用 | 删 |
| 37 | `icon` | 1 | E | 未消费 | 删 |

**汇总**：A 类 11 · B 类（已并入 A）· C 类 3 · D 类 10 · E 类 13。

## 3. 重叠组（lint S5 已标记）

```
name            <> slug                                   → 删 slug
display_name    <> displayName（驼峰/下划线拼写差异）       → 统一 display_name
description     <> summary                                 → 删 summary
category        <> domain <> type                          → 选 category
tags            <> triggers <> trigger_words <> auto_trigger → 触发线索统一写进 description
```
注：lint_scripts.py S5 已刻意**排除** `description_zh/en` 与 `display_name_zh/en`，因为它们是双语规范而非冗余——这点在声明表里与 D 类区分开了。

## 4. 关键发现：标杆技能也在用非标准字段

`junheng-core/SKILL.md`（用户自己写的共享内核，被 5 个技能依赖）frontmatter：
```yaml
name: junheng-core
description: ...
description_en: ...
metadata:
  author: Junheng NutriAgent      # ← 官方要求 author 是独立顶层字段
  version: "1.0.0"                # ← 官方要求 version 是独立顶层字段
compatibility: Requires Node.js 18+ ...   # ← 官方未列此字段，平台不读
```
即：**连标杆技能都把 `author`/`version` 塞进 `metadata`、写了无效的 `compatibility`**。
这说明死字段问题具有普遍性，清理前必须先统一"什么是合法 frontmatter"的规范，否则会反复漂移。

## 5. 处置建议（三档）

| 档 | 做法 | 收益 | 风险 | 优先级 |
|---|---|---|---|---|
| **A（推荐）** | 先立白名单规范（A 类 11 字段为合法集；`metadata` 仅留第三方工具需要项；C 类 license 保留、compatibility 删）；再跑 lint 提示 D/E 类字段，人工逐条裁决后再改 | 根治漂移、可机检、不误删 | 需人工裁决 23 个非 A 类字段 | **high** |
| B | 只产出本报告，不动任何 SKILL.md | 零风险 | 死字段继续存在、未来作者仍会复制错误写法 | medium |
| C | 脚本批量删除所有 D/E 类字段 | 一步清干净 | 破坏平台未知但可能读取的字段；不可逆；违背"先证伪再删"原则 | low（不推荐） |

**推荐 A**：与既有治理原则一致——先定判据（白名单 + lint），再人工核查，最后执行。D/E 类共 23 个字段（占 37 的 62%）是清理重点，其中 `visibility`(16)/`agent_created`(11)/`dependencies`(9)/`compatibility`(12) 出现次数高、影响面大，应优先裁决。

## 6. 待用户裁决项

- 是否采纳档 A（立白名单规范 + lint 提示）？
- C 类 `license` 保留、`compatibility` 删除的边界是否同意？
- 是否允许把 `junheng-core` 的 `metadata.author/version` 提到顶层（作为规范范本）？
- 清理动作本身（改 93 个 SKILL.md）是否授权？（破坏性、平台行为，本任务未授权，仅出表）
