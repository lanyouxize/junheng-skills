# 技能 SKILL.md frontmatter 白名单规范

> 任务 (x) 的后续治理动作（档 A：先立白名单规范 + lint 提示，再人工逐条裁决后改）。
> 本文是**唯一合法 frontmatter 字段集**的权威定义；`lint_scripts.py` 的 S6 检查以第 2 节为准。
> 任何不在白名单内的顶层字段，S6 一律报 W，交由人工裁决后删除/并入。
> **禁止脚本批量误删**（遵循「先证伪再删」原则——D/E 类共 24 字段占 37 的 65%，改 93 个文件属破坏性动作，须单独授权）。

## 1. 白名单来源（可复现，任务 x 已核实）

两份官方文档查证：

- **开放平台** `open.workbuddy.cn/docs/skill` 标准字段：
  `name` · `display_name` · `display_name_en` · `description` · `description_zh` · `description_en` · `version` · `author` · `allowed-tools` · `examples_zh` · `examples_en`
- **CLI** `workbuddy.ai/docs/cli/skills` 标准字段：
  `name` · `description` · `allowed-tools` · `disable-model-invocation` · `user-invocable` · `context` · `agent` · `model` · `hooks`

第三方跨平台工具需要（保留，平台官方未列但工具依赖）：

- `license`：跨平台映射保留的许可证字段
- `metadata`：第三方工具自定义元数据容器；**约束**——不允许在其内放 `author` / `version`（应提升为顶层字段）

> 注意：白名单取**两份官方文档的并集**，包含当前 93 个技能里尚未使用的合法字段
> （如 `context` / `agent` / `model` / `hooks` / `examples_zh` / `examples_en`）。
> 这样 S6 不会把「合法但本机未用」的字段误判为死字段——避免检查器学会说谎。

## 2. 白名单（19 字段，唯一合法集）

平台标准 17：

```
name, description, version, description_zh, description_en,
display_name, display_name_en, author, allowed-tools,
examples_zh, examples_en,
disable-model-invocation, user-invocable,
context, agent, model, hooks
```

第三方保留 2：

```
license, metadata
```

## 3. 非白名单字段处置（S6 报 W，待人工裁决）

**D 类（语义重叠，统一到一个合法字段）：**

| 字段 | 处置 |
|---|---|
| `slug` | 删除，标识用 `name` |
| `displayName` | 统一为 `display_name` |
| `summary` | 删除，并入 `description` |
| `category` / `domain` / `type` | 选 `category` 一个 |
| `tags` / `triggers` / `trigger_words` / `auto_trigger` | 触发线索写进 `description` |

**E 类（死字段，任何消费方均未读取，建议删除）：**
`visibility` · `agent_created` · `dependencies` · `homepage` · `display_name_zh` · `source` · `changelog` · `emoji` · `github` · `parentSkill` · `title` · `argument-hint` · `icon`

**C 类（第三方字段但平台不读）：**
`compatibility` —— 建议删除（junheng-core 写成一整段字符串，平台不读）

**`metadata` 子键约束：**
若含 `author` / `version` → 提升为顶层字段（junheng-core 当前违规，作规范范本修正）。

## 4. 与 lint 的关系

- S6 以本文第 2 节白名单为唯一判据，对 93 个 `SKILL.md` 的顶层 frontmatter key 做差集，命中即 W。
- S6 **不自动改写任何 `SKILL.md`**；改写需人工逐条裁决后单独授权（破坏性）。
- 机器真源 = `lint_scripts.py` 的 `FM_WHITELIST` 常量（单一事实源，避免与本文档漂移）；本文档仅作人读规范。

## 5. 裁决清单（由 S6 输出 + 7 个嵌套技能手工补齐，共 93 个技能的真实影响数）

> 计数口径：扁平 linter 覆盖 86/93 用户技能（遗漏 7 个嵌套技能）；下方数字已用
> `agent-dev-skills/*`（6 个）与 `lark-unified/skills/meegle` 补齐。其中
> `agent_created` 86 视图为 9、补嵌套 +2 → 11；`homepage` 2 +1 → 3；`parentSkill` 0 +1 → 1。
> **除这 3 个字段外，其余与 `lint_scripts.py` S6 直接输出一致。**

### D 类（语义重叠，统一到一个合法字段）

| 字段 | 影响技能数 | 建议处置 |
|---|---:|---|
| `tags` | 16 | 删，触发线索并入 `description` |
| `category` | 10 | 保留 `category`，删 `domain`/`type` |
| `slug` | 5 | 删，标识用 `name` |
| `displayName` | 5 | 统一为 `display_name` |
| `summary` | 3 | 删，并入 `description` |
| `domain` | 1 | 删，并入 `category` |
| `type` | 1 | 删，并入 `category` |
| `triggers` | 1 | 删 |
| `trigger_words` | 1 | 删 |
| `auto_trigger` | 1 | 删 |

### E 类（死字段，任何消费方均未读取，建议删除）

| 字段 | 影响技能数 | 建议处置 |
|---|---:|---|
| `visibility` | 16 | 删 |
| `agent_created` | 11 | 删 |
| `dependencies` | 9 | 删 |
| `homepage` | 3 | 删 |
| `display_name_zh` | 2 | 删，并入 `display_name` |
| `source` | 2 | 删 |
| `changelog` | 1 | 删 |
| `emoji` | 1 | 删 |
| `github` | 1 | 删 |
| `parentSkill` | 1 | 删 |
| `title` | 1 | 删 |
| `argument-hint` | 1 | 删 |
| `icon` | 1 | 删 |

### C 类（第三方字段，平台不读）

| 字段 | 影响技能数 | 建议处置 |
|---|---:|---|
| `compatibility` | 12 | 删（junheng-core 写成整段字符串，平台不读） |

### metadata 子键违规（应提升为顶层）

| 字段 | 影响技能数 | 建议处置 |
|---|---:|---|
| `metadata.author` | 14 | 提升为顶层 `author` |
| `metadata.version` | 13 | 提升为顶层 `version` |

---

**裁决状态（待用户确认后回填）**：全部 26 项问题（24 顶层字段 + 2 metadata 子键）默认处置如上，**未授权改写任何 SKILL.md**。改写须用户显式确认，并作为单一 git 提交以便回滚。
