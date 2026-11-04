---
author: "dashboard"
---

# 项目记忆管理 -- 跨会话项目记忆沉淀

## 输入要求

1. **记录类型**（必填）：session总结 / 决策记录 / 规范沉淀 / 已知问题清单 / 换机交接 / 记忆恢复
2. **内容详情**（必填）：具体要记录的信息
3. **项目标识**（可选）：项目名称或标识符

## 记忆文件存储位置

记忆沉淀和恢复遵循"**项目记忆跟随项目，用户偏好跟随用户**"原则。记忆结构统一为 **4 层 / 6 个文件 / 2 个作用域**（全文件唯一口径）：

- **项目作用域** `{PROJECT_ROOT}/.ai-memory/`（跟随项目迁移、可团队共享）承载三层：**L1 当日层**（`daily.md`、`topics.md`）、**L2 会话层**（`session_memory_{session-id}.jsonl`）、**L3 项目层**（`project_memory.md`、`handoff.md`）
- **用户作用域** `{USER_PROFILE}/.ai-memory/`（跨项目复用）承载 **L4 用户层**（`user_profile.md`）

层与文件的完整枚举以下方「记忆文件相对路径」表为唯一权威来源；写入/读取的决策单位是**文件**，层号仅表示生命周期与作用域归属。**严禁硬编码任何绝对路径**，确保跨 IDE（Trae CN / Trae / Marvis / VSCode 等）可用。

### 路径根目录探测协议

LLM 在首次写入或读取记忆前，必须按以下优先级链探测两个根目录：

#### `{PROJECT_ROOT}` 项目根目录（L3/L2/L1 记忆使用）

| 优先级 | 探测源 | 适用场景 | 示例 |
| ------ | ----------------------------- | -------------------------------------- | -------------------------------- |
| 1 | 环境变量 `PROJECT_ROOT` | 用户显式指定，跨 IDE 通用 | `set PROJECT_ROOT=D:\my-project` |
| 2 | Git 仓库根目录 | 已纳入 Git 管理的项目 | `git rev-parse --show-toplevel` |
| 3 | IDE 当前工作区根目录 | IDE 打开的项目目录 | 工作区路径 / cwd |
| 4 | 询问用户并写入 `PROJECT_ROOT` | 以上均未命中时，强制询问，不得自行假设 | 用户确认后写入环境变量 |

#### `{USER_PROFILE}` 用户主目录（L4 记忆使用）

| 优先级 | 探测源 | 适用场景 | 示例 |
| ------ | ----------------------- | ------------------------ | ----------------------------------------------- |
| 1 | 环境变量 `USER_PROFILE` | 用户显式指定 | `set USER_PROFILE=C:\Users\username` |
| 2 | 系统用户主目录 | 默认场景，跨平台自动识别 | Windows: `%USERPROFILE%` / macOS/Linux: `$HOME` |
| 3 | 询问用户 | 以上均未命中时，强制询问 | 用户确认后写入环境变量 |

### 记忆文件相对路径

探测到根目录后，**6 个记忆文件**按以下路径组织（**下表是层与文件的唯一权威枚举**：同一层可含多个文件，每行一个文件，路径即该文件的唯一标识）：

| 层 | 记忆文件（唯一路径） | 用途 | 作用域 |
| --------- | ------------------------------------------------------------------------ | ------------------------------- | ---- |
| L4 用户层 | `{USER_PROFILE}/.ai-memory/user_profile.md` | 跨项目用户偏好、技术栈、禁忌 | 用户 |
| L3 项目层 | `{PROJECT_ROOT}/.ai-memory/project_memory.md` | 项目规则、约束、约定、教训 | 项目 |
| L3 项目层 | `{PROJECT_ROOT}/.ai-memory/handoff.md` | 未完成任务的换机/换 IDE 交接 | 项目 |
| L2 会话层 | `{PROJECT_ROOT}/.ai-memory/{YYYYMMDD}/session_memory_{session-id}.jsonl` | 单次会话的任务/TODO/相关文件 | 项目 |
| L1 当日层 | `{PROJECT_ROOT}/.ai-memory/{YYYYMMDD}/daily.md` | 当日逐条操作日志（append-only） | 项目 |
| L1 当日层 | `{PROJECT_ROOT}/.ai-memory/{YYYYMMDD}/topics.md` | 当日会话主题摘要（5 字段） | 项目 |

**路径变量解析**：

- `{PROJECT_ROOT}`：按上述探测协议动态获取，禁止硬编码
- `{USER_PROFILE}`：按上述探测协议动态获取，禁止硬编码
- `{YYYYMMDD}`：当日日期，目录不存在时由记忆系统自动创建
- `{session-id}`：会话标识，格式为 `YYYYMMDD-HHmm`。**生成时机与存储约定一律以 `references/execution-safety.md`「session_memory 标识（id）生成规则」为准**（本文件不复述，避免两处漂移；该规则明确为**本次会话首次进入 Step 0（新会话加载 / 探测阶段）即生成**）：写进当日 `daily.md` 顶部 `session-id: {YYYYMMDD-HHmm}` 行作为真相源，新会话先读该行再定位 `session_memory_{session-id}.jsonl`；旧会话无此行时取当日目录下时间戳最大的 `session_memory_*.jsonl` 兜底。

### `.ai-memory/` 目录结构示例

```
{PROJECT_ROOT}/
├── .ai-memory/                          # 项目记忆根目录（跟随项目）
│   ├── project_memory.md                # L3 项目层：规则、约束、教训
│   ├── handoff.md                       # L3 项目层：未完成任务恢复点
│   ├── 20260705/                        # L2/L1 按日期组织（{YYYYMMDD}/）
│   │   ├── topics.md                    # L1 当日层：当日会话主题摘要
│   │   ├── daily.md                     # L1 当日层：当日逐条操作日志（append-only）
│   │   ├── session_memory_20260813-1430.jsonl # L2 会话层：单次会话记录（id=YYYYMMDD-HHmm）
│   │   └── session_memory_20260813-1510.jsonl
│   ├── _archive/                        # 蒸馏前本地快照（见「30 天蒸馏周期」清理规则）
│   └── 20260706/
│       └── ...
├── .gitignore                           # 忽略规则见下方「.gitignore 建议」
└── ...（项目其他文件）
```

### 版本控制策略

| 路径 | 是否提交 Git | 原因 |
| --------------------------------------- | ------------ | ------------------------------------------ |
| `.ai-memory/project_memory.md` | ✅ 提交 | 项目规则和约定，团队共享，版本追溯 |
| `.ai-memory/handoff.md` | ✅ 提交 | 换电脑/换 IDE 时恢复未完成任务 |
| `.ai-memory/{YYYYMMDD}/topics.md` | ❌ 忽略 | 当日会话摘要，含个人上下文，不团队共享 |
| `.ai-memory/{YYYYMMDD}/daily.md` | ❌ 忽略 | 当日逐条操作日志，含个人上下文，不团队共享 |
| `.ai-memory/{YYYYMMDD}/session_*.jsonl` | ❌ 忽略 | 单次会话详情，含个人上下文，不团队共享 |
| `.ai-memory/_archive/` | ❌ 忽略 | 蒸馏前本地快照，含个人上下文，不团队共享 |
| `{USER_PROFILE}/.ai-memory/` | 不适用 | 用户主目录，不在项目仓库内 |

**`.gitignore` 建议添加**（否定规则必须写在忽略规则之后才生效）：

```
# 忽略 .ai-memory 下全部内容（日期目录、会话文件、归档等）
.ai-memory/**
# 例外：L3 项目层两个文件需纳入 Git 共享
!.ai-memory/project_memory.md
!.ai-memory/handoff.md
```

### 探测执行规则

首次执行时输出探测过程：`[MEMORY-PROBE] PROJECT_ROOT: 优先级X→命中/未命中; USER_PROFILE: 优先级X→命中/未命中`。命中后缓存当前会话。优先级1-3均未命中时禁止自行创建目录，必须询问用户：`未找到项目根目录，请指定 PROJECT_ROOT 路径（如 D:\my-project）`。

### 写入规则

- 探测到根目录后，写入前必须确认 `.ai-memory/` 目录存在，不存在时先创建
- 写入必须使用 UTF-8 无 BOM 编码，禁止使用 PowerShell 的 `Set-Content` / `Out-File`
- L1/L2 每日（`{YYYYMMDD}/`）一个目录；L3 每项目两个文件（`project_memory.md`、`handoff.md`）；L4 每用户一个文件（`user_profile.md`）
- Windows 环境下路径分隔符为 `\`，macOS/Linux 为 `/`，写入时按当前系统规范化

### 即时写入规则（写后即记）

`daily.md` 采用 **append-only** 模式，在每次实质性操作完成后**立即追加**，不经用户确认、不等待会话结束。写入触发条件、写入格式和运行位置见主 SKILL.md「Step 0: 工作记忆加载 → 写后即记协议」。

**实现规则**：

1. 每次追加前仅读取 `daily.md` 末尾 20 行确认已有记录（避免全量读取浪费上下文），然后直接 append
   > **口径说明**：此处 20 行是**写入前查重**口径（append-only 去重用），与下方「读取截断规则」中恢复加载的 120 行口径**用途不同**，两者不冲突、不可互替。
2. 写入使用 UTF-8 无 BOM 编码，Windows 换行符 `\r\n`
3. 若 `daily.md` 不存在，先创建带 `# 工作日志 - [YYYY-MM-DD]` 标题头的新文件再追加
4. 同一条记录的多个文件修改合并到一行 `daily.md` 条目，不拆条
5. `daily.md` 内容超过 8000 字符时，Agent 应在 Step 6 出示精简提醒，建议用户将旧记录蒸馏入 `project_memory.md`

### 读取规则

- 新会话开始时，按"记忆恢复"章节的三层渐进加载策略（Layer 1/2/3）读取
- 不得预读全量记忆，必须按当前任务相关性按需加载
- 总 token 预算控制在 1000 以内，超过时**按下方「读取截断规则」的统一丢弃顺序执行**（勿另立口径）
- 读取失败时不阻塞流程，正常进入意图识别

## 执行流程

### 第一步：会话结束记录（Session Summary）

会话结束时生成结构化summary。**载体为 JSON Lines（`.jsonl`）：每行一个独立 JSON 对象、无外层数组、无 Markdown 标题与列表**，追加写入文件。

**唯一格式示例（其他会话照此结构填写，字段名不得改写）**：

```jsonl
{"type":"session_summary","session_id":"20260813-1430","date":"2026-08-13","goal":"完成订单模块的退款流程改造"}
{"type":"completed","task":"退款接口重构","note":"拆分为独立 service，单测通过","files":["src/order/refund.service.ts"]}
{"type":"completed","task":"补充边界用例","note":"新增 6 个失败路径用例","files":["tests/refund.spec.ts"]}
{"type":"decision","decision":"退款采用异步补偿而非同步事务","context":"跨库调用无法保证事务一致","impact":"后续对账任务需读取补偿表"}
{"type":"blocker","issue":"沙箱缺少退款回调地址","next_action":"向运维申请沙箱回调域名"}
{"type":"next_step","order":1,"task":"接入退款对账定时任务"}
{"type":"next_step","order":2,"task":"补齐退款失败告警"}
{"type":"convention","rule":"金额字段统一用整数分表示，禁止浮点"}
```

**字段清单（必填项缺一不可）**：

| `type` | 必填字段 | 说明 |
| ---------------- | -------------------------------------------------------- | -------------------------- |
| `session_summary` | `session_id`、`date`、`goal` | **必须为首行**，一次会话一行 |
| `completed` | `task`、`note`、`files`（数组，无则 `[]`） | 已完成任务，一条一行 |
| `decision` | `decision`、`context`、`impact` | 关键决策，一条一行 |
| `blocker` | `issue`、`next_action` | 遗留问题 / Blockers |
| `next_step` | `order`、`task` | 下一步计划，按 `order` 升序 |
| `convention` | `rule` | 规范更新，一条一行 |

**写入约束**：

- 每行必须是**合法 JSON 对象**且以 `\n` 结尾（JSON Lines 语义），禁止写入 `##` 标题、`-` 列表等 Markdown 结构
- 文件不存在时直接创建；已存在时**追加**，不覆盖既有行
- 编码 UTF-8 无 BOM

> Session Summary 全文写入 `{PROJECT_ROOT}/.ai-memory/{YYYYMMDD}/session_memory_{session-id}.jsonl`（即上述 JSON Lines 结构）；同时向 `{PROJECT_ROOT}/.ai-memory/{YYYYMMDD}/topics.md` 写入「5 字段主题摘要」（项目 / 当前阶段 / 活跃任务 / 上次会话 / 交接状态，格式见第五步 Layer 1），供新会话快速恢复，**不写全文**。

### 第二步：决策记录（Decision Record）

重要技术决策时记录：

```markdown
## Decision Record: [决策名称]

**日期**: [YYYY-MM-DD]
**问题**: [需要解决什么问题]

### 选项分析

| 选项    | 优势 | 劣势 | 复杂度   |
| ------- | ---- | ---- | -------- |
| [选项A] | ...  | ...  | 低/中/高 |
| [选项B] | ...  | ...  | 低/中/高 |

### 决策

**选择**: [最终选项]
**理由**: [为什么选这个]
**Trade-offs**: [接受了什么代价]

### 影响范围

- [影响的模块/文件]
- [需要同步更新的文档]

### 撤销条件

[什么情况下可以重新考虑这个决策]
```

> 模板必填项缺一不可。写入位置：`{PROJECT_ROOT}/.ai-memory/project_memory.md` 的 Decision Record 章节

### 第三步：规范沉淀（Convention Capture）

发现项目特定规范时记录：

```markdown
## Project Convention: [规范名称]

**类型**: [编码规范/命名规范/架构约束/工具配置]
**适用范围**: [哪些模块/文件适用]

### 规范内容

[具体规则]

### 示例

**正确**:
`[代码示例]`

**错误**:
`[代码示例]`

### 发现来源

[哪次会话/哪个任务中发现]
```

> 模板必填项缺一不可。

### 第三步点五：术语表维护（Glossary）

当对话中出现领域术语漂移（同一概念被多个名称指代、或不同概念被同一名称覆盖）时，记录到项目作用域的术语表。

**触发条件**：

- 同一概念在本次会话中被 ≥ 2 种不同名称指代
- 代码中出现的术语与需求文档中的术语不一致
- 跨模块调用时对同一概念使用了不同命名
- 用户纠正了 Agent 对某个术语的理解

**记录格式**：

```markdown
## Glossary Entry: [术语名称]

**规范名称**: [唯一推荐名称]
**别名/变体**: [同义但不推荐的名称列表]
**定义**: [一句话定义]
**适用范围**: [哪些模块/文件使用此术语]
**禁止使用**: [明确不应使用的名称]
**来源**: [需求文档/用户口头约定/行业标准]
```

**写入位置**：追加到 `{PROJECT_ROOT}/.ai-memory/project_memory.md` 的 Glossary 章节（首次写入时创建该章节）。

**使用规则**：

- 后续代码生成和讨论中，Agent 必须使用术语表的规范名称
- 发现术语表与当前使用不一致时，以术语表为准并提醒用户
- 新会话 Step 1.1 加载 project_memory.md 时，Glossary 章节随 Section Headers 一并加载

### 第三步点六：已知问题清单（Known Issues）

发现新 Bug 模式、兼容性陷阱、第三方依赖风险时记录到 `{PROJECT_ROOT}/.ai-memory/project_memory.md` 的「**Known Issues（Lessons Learned）**」章节（该章节标题为唯一名，跨会话按名查节一律使用此标题）：

```markdown
## Known Issues（Lessons Learned）: [问题名称]

**发现日期**: [YYYY-MM-DD]
**问题类型**: [Bug模式 / 兼容性陷阱 / 依赖风险 / 性能反模式 / 安全漏洞]
**严重度**: [致命 / 严重 / 一般 / 提示]

### 现象

[具体表现，含错误信息或日志片段]

### 根因

[根本原因分析]

### 规避方案

[具体的代码层面规避措施]

### 相关文件

- [文件路径:行号]

### 状态

[未修复 / 已修复 / 已规避 / 待验证]
```

> 模板必填项缺一不可。

### 第四步：换机/换 IDE 交接（Handoff Protocol）

当任务未完成且用户准备关闭 IDE、切换电脑、切换 IDE 或长时间暂停时，必须生成可迁移交接点。交接点写入 `{PROJECT_ROOT}/.ai-memory/handoff.md`，并提示用户随代码一起提交或同步。`handoff.md` 只记录恢复工作所需的最小上下文，不写入账号、密钥、个人聊天细节或临时 IDE 缓存路径。

```markdown
## Handoff Checkpoint

**更新时间**: [YYYY-MM-DD HH:mm]
**当前目标**: [用户原始需求的核心交付物]
**当前阶段**: [需求/设计/实现/验证/交付]
**完成度**: [按已验证主线数计算的百分比]

### 已完成

- [已完成项]: [验证证据] -> [相关文件]

### 未完成

- [未完成项]: [下一步动作] -> [相关文件]

### 关键决策

- [决策]: [理由 / 影响范围 / 撤销条件]

### 恢复入口

- **首读文件**: [恢复时优先读取的文件]
- **关键命令**: [lint/test/build/启动命令]
- **验证路径**: [继续前必须跑的验证]

### 阻塞项

- [阻塞原因]: 需 [角色] 提供 [具体输入]
```

**写入触发条件**：

- 用户明确说“暂停/下次继续/换电脑/关闭 IDE/稍后接着做”
- 本轮存在未完成主线任务，且已产生文件修改或关键决策
- 任务依赖本地环境状态、运行命令、验证结果或人工确认
- 多 IDE 协同开发时，任何会影响下一位执行者的上下文变化

**同步规则**：

1. 写入 `handoff.md` 前先读取现有内容，保留仍有效的未完成项，删除已验证完成项。
2. `handoff.md` 必须随 `.ai-memory/project_memory.md` 一起纳入 Git 或共享存储同步。
3. 新电脑恢复时，先执行 `[MEMORY-PROBE]`，再读取 `handoff.md`、`project_memory.md` 和当前任务相关文件。
4. 恢复后若发现代码状态与 `handoff.md` 不一致，以工作区实际文件和测试结果为准，并更新交接点。
5. 任务完成后清空或改写 `handoff.md` 为“无未完成交接项”，避免旧任务污染新会话。

> 模板必填项缺一不可。写入位置：`{PROJECT_ROOT}/.ai-memory/handoff.md`，且不含敏感值。

### 第五步：新会话记忆恢复（Progressive Disclosure）

新会话开始时，按三层加载记忆：

**Layer 1: Metadata（~50 tokens）**

```
项目: [名称]
当前阶段: [阶段]
活跃任务: [任务名]
上次会话: [日期]
交接状态: [无 / 存在 handoff.md 未完成项]
```

**Layer 2: Body（~200 tokens）**

```
## 上次Session Summary
[最近一次的summary核心内容]

## Handoff Checkpoint
[handoff.md 中与当前任务相关的未完成项]

## 活跃决策
- [与当前任务相关的决策]
```

**Layer 3: References（按需加载，~500 tokens each）**

```
## 相关决策记录
[与当前任务相关的完整决策记录]

## 相关规范
[与当前任务相关的项目规范]
```

**加载策略**：

1. 始终加载Layer 1
2. 如果存在 `handoff.md` 且含未完成项，优先加载与当前任务相关的 Handoff Checkpoint
3. 如果当前任务与上次会话连续，加载Layer 2
4. 如果涉及历史决策或规范，按需加载Layer 3
5. 总token预算控制在1000以内，避免context rot

> 记忆来源文件不存在时不阻塞流程，正常进入意图识别。

## 记忆治理原则

记忆按 **L1 当日层 / L2 会话层 / L3 项目层 / L4 用户层** 四层组织，共 **6 个记忆文件 / 2 个作用域**（口径与上方「记忆文件存储位置」「记忆文件相对路径」表完全一致）。未验证信息只留在 L1，不得沉淀为 L3；只影响本轮的临时路径不得写入 L4；L4 用户偏好与 L3 项目约束冲突时优先遵守更具体、更高风险的项目约束。

记忆默认静默应用——用户长期偏好、项目固定路径、已验证技术约束、上轮已确认的下一步可静默使用；记忆与当前请求冲突、可能过期、会影响文件修改范围或交付判断时必须显式说明。

敏感信息（健康/财务/身份/凭据/密钥）不得在无关上下文中引用，不得写入普通规范。开发场景例外：可记"位置与访问方式"，不记"值"。

记忆膨胀/冲突/透明度不足时按时间、证据强度、风险等级收敛，旧规则标注过期。失败模式与主 SKILL.md「对话流异常边界」对齐。

### 读取截断规则

从 Step 0 / Step 1.1 新会话恢复调用，用于控制单次加载量，避免上下文溢出：

| 文件 | 阈值 | 读取动作 |
| ------------------- | ----------- | ------------------------------------------------- |
| `daily.md` | ≤ 8000 字符 | 全量读取 |
| `daily.md` | > 8000 字符 | 读取末尾 120 行（最新操作），并出示精简提醒（**用途：新会话恢复加载**；与「即时写入规则」中写前查重的 20 行口径用途不同，不可互替） |
| `project_memory.md` | ≤ 8000 字符 | 全量读取 |
| `project_memory.md` | > 8000 字符 | 先读目录结构 + Decision Record 章节，其余按需加载 |

**统一丢弃顺序（本文件唯一口径，其他位置涉及截断一律引用此处）**：Step 1.1 三层策略下，当总 token > 1000 时按序丢弃——① **Layer 3（references）** → ② **最旧 Layer 2**（历史 `session_memory` 记录，至少保留最近一次）→ ③ **Layer 1 保底**（仅在① ② 均丢弃后仍超预算时才裁剪，优先保留 `topics.md` 五字段摘要）。`handoff.md` 的未完成检查点全程保留。

### 记忆维护协议

#### 30 天蒸馏周期

每超过 30 天的 `{YYYYMMDD}/` 日志目录，其 `daily.md` 内容必须在下一个维护窗口中蒸馏入 `project_memory.md`：

1. **蒸馏时机**：Step 6 复盘时检查，若存在 >30 天的日志目录且仍未处理，触发蒸馏
2. **蒸馏规则**：
   - 提取 `daily.md` 中的关键决策 → 写入 `project_memory.md` 的 Decision Record 章节
   - 提取新发现的 Bug 模式/陷阱 → 写入 `project_memory.md` 的 Known Issues（Lessons Learned）章节
   - 提取项目约定/偏好 → 写入 `project_memory.md` 的 Project Convention 章节
   - 纯操作流水不蒸馏，直接丢弃
3. **清理规则（不可逆操作，必须先归档快照 + 用户确认，禁止静默删除）**：
   - **先归档**：确认蒸馏产物已正确写入 `project_memory.md` 后，先将整个 `{YYYYMMDD}/` 目录复制为本地快照 `{PROJECT_ROOT}/.ai-memory/_archive/{YYYYMMDD}/`，并向用户报告归档路径。
   - **再确认**：向用户显式提示——待删的 `daily.md`、`topics.md`、`session_*.jsonl` 均已被 `.gitignore` 忽略（见「版本控制策略」），**删除后无法通过 Git 恢复**；同时列出待删清单与快照路径，**等待用户明确确认**。
   - **确认后才删**：仅在用户明确确认后，删除该 `{YYYYMMDD}/` 目录及其内的 `daily.md`、`topics.md` 和所有 `session_*.jsonl`，且不得触碰其他日期目录或 `project_memory.md` / `handoff.md` / `_archive/`。
   - **用户未确认**：保留原目录不动，仅在 `project_memory.md` 标注「{YYYYMMDD} 已蒸馏，待用户确认清理」，待下次维护窗口再询问。
   - 归档快照同样受 `.gitignore` 忽略；如用户需要持久备份，可自行将快照手动提交至私有仓库或外部存储。
4. **防冲突**：若 `daily.md` 中的记录与 `project_memory.md` 现有条目冲突，追加修正条目并标注来源日期，不覆盖原有记录

#### daily.md 精简阈值

| 阈值 | 动作 |
| ------------ | -------------------------------------------------------------- |
| ≤ 8000 字符 | 正常追加，无需处理 |
| > 8000 字符 | Step 6 出示精简提醒，询问用户是否蒸馏当日旧记录 |
| > 12000 字符 | 强制精简：取最近 30 条记录保留，其余蒸馏入 `project_memory.md` |

#### 四层记忆生命周期（L1 → L4）

```
L1 daily.md（逐条操作日志）
  ↓ 会话结束
L2 session_memory_{id}.jsonl（会话总结，JSON Lines）+ L1 topics.md（主题摘要）
  ↓ >30 天
L3 project_memory.md（长期精选项目记忆）；L3 handoff.md（未完成交接恢复点，独立维护）
  ↓ 跨项目
L4 user_profile.md（用户级偏好，手动提炼）
```

## 输出格式

各记忆类型的模板已在执行流程(第一/二/三/三点五/三点六/四/五步)中定义,输出时按对应模板填写。所有记忆写入 `{PROJECT_ROOT}/.ai-memory/` 或 `{USER_PROFILE}/.ai-memory/` 对应路径(见"记忆文件相对路径"表)。

## 质量标准

- Session Summary 会话结束时立即生成,以 **JSON Lines**（每行一个 JSON 对象）追加写入 `session_memory_{session-id}.jsonl`,含会话目标/已完成/关键决策/遗留问题/下一步,不得混入 Markdown 标题与列表
- 已知问题写入 `project_memory.md` 的「Known Issues（Lessons Learned）」章节,标题名唯一,不得改写
- Decision Record 必须含"撤销条件",避免过早固化
- Convention Capture 必须有正/反例,不能只有文字描述
- Handoff Checkpoint 必须能让新电脑在不依赖旧 IDE 会话的情况下恢复当前主线
- 记忆恢复优先加载与当前任务最相关的内容,总 token ≤ 1000
- 记忆默认静默应用,影响交付边界时显式说明依据
- 敏感记忆上下文隔离,开发场景可记位置不记值
- 记忆写入按 L1-L4 分层,不得跨层污染

## 失败回退机制

| 步骤 | 失败条件 | 回退目标 | 最大重试 |
| ------------------------- | ---------------------------- | -------------------------------------------- | -------- |
| 第一步 Session Summary | 会话信息不完整或多次中断 | 基于已有信息生成骨架,标注"信息可能不全" | 2 |
| 第二步 Decision Record | 决策选项信息不足 | 记录已知选项,标注"待补充" | 1 |
| 第三步 Convention Capture | 规范来源不清晰或正反例难提炼 | 仅记录规范内容,标注"示例待补充" | 2 |
| 第四步 Handoff | 交接信息不完整或验证缺失 | 保留当前目标、未完成项、首读文件和阻塞项 | 1 |
| 第五步 记忆恢复 | Layer 加载超 token 预算 | 按「读取截断规则」的统一丢弃顺序执行(Layer 3 → 最旧 Layer 2 → Layer 1 保底),handoff 检查点保留 | 1 |
| 敏感记忆污染 | 敏感信息被写入普通摘要 | 立即隔离,只保留任务必要风险描述 | 0 |
| 记忆膨胀 | 加载大量低价值历史 | 执行记忆瘦身,仅保留有效目标/决策/约束/阻塞项 | 1 |
| 记忆冲突 | 多个互斥规范 | 按时间/证据强度/风险等级裁决,旧规则标注过期 | 1 |

## 关联 reference

- **spec-driven-development**（Spec驱动开发）— 将spec和design决策记录到项目记忆
- **software-project**（软件项目总控）— 将通用项目边界、架构、发布和交付记录到项目记忆
- **website-project**（网站项目总控）— 将站点配置、部署路径、交付材料和运维清单记录到项目记忆
- **task-decomposition-and-execution**（任务拆解与执行）— 将task summary记录到项目记忆
- **tech-selection**（技术选型）— 选型决策自动记录到项目记忆
- **code-generation**（代码生成）— 编码前加载项目规范，编码后记录新发现规范
- **code-review**（代码审查）— 记录反复出现的坏味道、安全/性能问题修复模式 → 写入 `project_memory.md` 的「Known Issues（Lessons Learned）」
- **bug-diagnosis**（Bug诊断）— 记录 Bug 根因、修复方案与预防措施 → 写入 `project_memory.md` 的「Known Issues（Lessons Learned）」；重大取舍写入 `Decision Record`
- **refactoring**（重构）— 记录重构决策与新增编码规范 → 写入 `project_memory.md` 的 `Decision Record` 与 `Project Convention`
- **test-generation**（测试用例生成）— 记录测试策略、Mock/Stub 约定与覆盖率基线 → 写入 `project_memory.md` 的 `Project Convention`
- **doc-generation**（文档生成）— 记录文档结构、模板选择理由与 API 文档规范 → 写入 `project_memory.md` 的 `Project Convention`；术语命名 → `Glossary`
