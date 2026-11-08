---
name: junheng-orchestrator
description: 钧衡 NutriAgent 配方研发多技能编排框架（非运行时）。把现有 junheng 域技能（证据→标准映射→配方计算→达成度验证→标签→合规→报告）按标准 pipeline 串联并施加质量门禁，使长流程可审计、可回放、不可跳过门禁。当用户需要「一键跑完配方研发全流程」「把多个 junheng 技能串成可审计闭环」「给配方任务加质量门禁与审计追踪」时使用。编排层只做串联与门禁，不重造域逻辑。
description_en: Junheng NutriAgent recipe-R&D multi-skill orchestration framework (not a runtime). Chains existing junheng domain skills (evidence→standards→formulation→attainment→labeling→compliance→report) into an auditable pipeline with quality gates. Use when the user wants a one-shot auditable recipe-R&D flow or to add quality gates/audit trails to a formulation task.
author: Junheng NutriAgent
version: 0.1.0
license: Proprietary
compatibility: Node.js 18+; 需网络访问.
---

# 配方研发编排框架（junheng-orchestrator）

## 目的与边界

**做什么**：把现有 junheng 域技能串成**可审计、可回放、门禁不可跳过**的配方研发 pipeline，并对每个交接点施加质量门禁（对齐 metaswarm 范式的纪律，而非代码）。

**不做什么（铁律边界）**：

- **不是运行时，不替代域能力** —— 编排层只做串联与门禁；营养计算归 `junheng-formulate`、标准归 `junheng-standards`、核算归 `junheng-cost`、标签归 `junheng-labeling`、合规归 `junheng-safety`。**绝不重造域逻辑**（否则既违反「窄稳省」，又增加维护税）。
- **不引入任何外部依赖** —— 没有 BEADS/pulp/Claude Code 专有组件，纯 Node + git + 现有 skill。
- **不自动跳过门禁** —— VALIDATE 不过不进 REVIEW，REVIEW 不 PASS 不 COMMIT（见质量门禁三铁律）。

## 何时用本 skill

- 需要把「证据→配方→标签→合规→报告」长流程一次跑完且可追溯。
- 需要给配方任务加质量门禁（独立重算、对抗验证、审计落盘）。
- 流程中断（压缩/会话结束）后要从断点恢复（见 `audit/` 与状态文件）。

## 七阶段 pipeline（阶段定义 + DoD）

| 阶段 | 调用技能 | DoD 退出门禁 |
|---|---|---|
| ① 证据收集 | paper-bilingual-search / literature-reviewer / multi-search-engine / Exa / Context7 | 引用可溯、文献真实性已核 |
| ② 标准映射 | junheng-standards（`resolveStandard`） | 标准条款 available + cite 完整 |
| ③ 配方计算 | junheng-formulate（`solveLP`）+ junheng-nutrition | 配比 Σ=1、LP 收敛、单位成本产出 |
| ④ 达成度验证 | junheng-attainment | 各营养 min/max 实测达成、钙磷比在界 |
| ⑤ 标签生成 | junheng-labeling | 标签数值与配方一致 |
| ⑥ 合规校验 | junheng-safety + standards | 无超标、无缺失强制项 |
| ⑦ 报告产出 | word-docx / wps | 报告含证据链 + 标准出处 + 审计追踪 |

完整七阶段 DoD 模板见 `recipes/formulate-pipeline.md`。

## 质量门禁三铁律（照搬 metaswarm，硬约束）

1. **门禁 = 阻塞状态转换，非建议** —— VALIDATE 不过不进 REVIEW；REVIEW 不 PASS 不 COMMIT；FAIL 必须重试（≤3）或升级人工，**绝不可跳过**。
2. **Fresh Reviewer Rule** —— 重审必须换新审查实例（junheng 下 = **独立重算路径**，不复用前次结论，防锚定偏误）。
3. **DoD 必须有证据** —— 数值 / 行号 / 文献出处；无证据 = 未验证；「看起来对」≠ PASS；存疑即 FAIL。

### 4 阶段执行循环映射

| metaswarm | junheng 编排 |
|---|---|
| IMPLEMENT | 阶段技能执行（如 junheng-formulate 跑求解） |
| VALIDATE | **编排者独立重算**：不读技能自报，直接调 `resolveStandard` + `ingredient_db` 重新核对（如配方成本由 `junheng-cost` 独立重算） |
| ADVERSARIAL REVIEW | 独立 reviewer（另一计算路径 / 另一 skill）核对 DoD，二元 PASS/FAIL + 证据 |
| COMMIT | git commit + 审计落盘（`.junheng/run-<ts>.json`，见 `audit/README.md`） |

### 对抗验证范式（domain 特化）

| 验证对象 | 独立验证方式 | 证据形式 |
|---|---|---|
| 营养达标度 | 用 `resolveStandard` + `ingredient_db` 独立重算配方营养 | 数值 + 来源行 |
| 标准引用 | 核对 `cite` 字段 + 文献真实性（联网核验） | 文献名 + 版本 |
| 合规结论 | 标签数值独立重算 vs 标准上下限 | 数值比对 |
| LP 正确性 | 解析解/手算用例比对（A2 已建 `poc.mjs` 31 断言范式） | 断言结果 |

## 人类检查点（主动暂停，非通知）

以下高风险决策**暂停等显式批准**（对齐铁律「先核查再执行」）：

- 删除 / 修改原料库条目（A1 已证实「删除即永久」风险）
- 生产部署（landscape 文档明确「每次生产部署前必须获得用户明确确认」）
- 标准值改动（如 A1 去 GB 污染类改动）
- 不可逆批量操作

## 与 `vcs-all.sh lint` 的衔接（代码层门禁）

- metaswarm 用「覆盖率三层级 + GTG merge gate」；junheng 已有 `vcs-all.sh lint`（**93 技能 · 0E0W**）作为同等代码层门禁。
- orchestrator 的 VALIDATE 阶段 = **`vcs-all.sh lint` + domain 门禁（数值正确性 / 标准引用完整性）**。
- commit 前强制 lint 通过（对齐 metaswarm "NEVER `--no-verify`" 纪律）。

```bash
bash ~/.workbuddy/tools/vcs-all.sh lint   # 编排 VALIDATE 阶段必跑
```

## 知识库（JSONL）

落地于 `knowledge/`，结构对齐 metaswarm（`id/type/fact/recommendation/confidence/provenance/tags/affectedFiles`）：

- `gotchas.jsonl`（踩坑，如「钙磷比必须按双字段线性化」）
- `patterns.jsonl`（有效模式，如「先证伪 guard 再实现」）
- `decisions.jsonl`（决策，如「选纯 JS 重写非 pulp」）
- `anti-patterns.jsonl`（反模式，如「依赖子 agent 自报」）

编排开始用 `prime` 脚本注入相关上下文（**grep 注入，零依赖**）：

```bash
node scripts/prime.mjs 钙磷比 脂肪酸      # 按关键词匹配 knowledge/*.jsonl 输出上下文块
```

`prime.mjs` 只读 `knowledge/*.jsonl`，按任意关键词命中即输出该条；无命中则提示可用 topic。

## 审计落盘格式

每次编排运行结束（或阶段完成）落盘 `.junheng/run-<ts>.json`，结构见 `audit/README.md`。包含任务 / 阶段 / 门禁结果 / 证据 / 人类检查点，使流程可回放。

## 运行时代码（阶段 B 落地）

阶段 A 仅固化纪律与审计格式；阶段 B 落地两个零依赖 Node 工具（纯 Node + 现有 skill 真源，可在其他电脑直接运行）。

### 1. `scripts/adversarial-check.mjs` — 对抗验证引擎（Fresh Reviewer，铁律②/③）

编排 VALIDATE / ADVERSARIAL REVIEW 阶段的「独立审查者」：**不读阶段自报的 achieved / unitCost**，独立从 `junheng-core` 的 `ingredient_db.js` + `junheng-standards` 的 `resolveStandard` 重算；每条 check 输出 expected/actual + 证据（文献 cite / 原料行 / 数值公式）。用 ingredient-outer 与 nutrient-outer 两条不同代码路径重算互为交叉验证，捕获任一方索引 bug。

```bash
# 合成手算可验用例（不依赖外部真源，验证引擎自身）
node scripts/adversarial-check.mjs selftest

# 对一份配方做独立重算校验（从真源重新拉标准+原料）
node scripts/adversarial-check.mjs verify \
  --recipe recipe.json --market intl --species dog --stage adult --moisture dry
# recipe.json = junheng-formulate formulateLeastCost 输出 {recipe, unitCost, achieved}
```

校验对象：Σ 占比=1（4dp 舍入容差 1e-3）、全部配方行溯源到原料库、双路径重算一致、各营养 min/max 达标（独立重算）、钙磷比∈[min,max]、阶段自报与独立重算偏差≤1e-2（捕获误报）、单位成本=Σ(price·share)。任一项 FAIL → 退出码 1。阶段④（达成度验证）必须用它产出 `independentCheck:true` 才能通过 COMMIT 门禁。

### 2. `scripts/orchestrate.mjs` — 编排状态机（DAG + 状态文件 + 审计落盘）

只做「串联与门禁」，不执行域逻辑。阶段结果由编排者(AI)提供，本脚本负责 DAG 依赖校验（门禁三铁律①）、`state.json` 持久化（断点续跑，蓝图§2.7）、质量门禁三铁律校验、`.junheng/run-<ts>.json` 审计落盘。

```bash
node scripts/orchestrate.mjs init --task "排毛配方 v3" --market intl --species dog --stage adult --moisture dry
node scripts/orchestrate.mjs next                       # 下一可执行阶段 + DoD + 子任务
node scripts/orchestrate.mjs record --stage 3 --gate PASS --result '{...}'   # 记录阶段结果
node scripts/orchestrate.mjs record --stage 1 --subtask 1.1 --gate PASS     # 递归子任务粒度
node scripts/orchestrate.mjs approve-checkpoint --stage 2   # 人工检查点授权（标准值改动）
node scripts/orchestrate.mjs status | resume | finalize --lint "PASS(95 技能 0E0W)"
```

七阶段 DAG（①证据→②标准→③配方→④达成度→⑤标签→⑥合规→⑦报告）含两级分解：阶段=epic，subtasks=工作单元。门禁三铁律硬约束：依赖未 PASS 拒绝记录（①）、阶段②含人工检查点须先批准（②）、finalize 须 freshReviewer(阶段④ independentCheck)+evidenceBacked 全满足（③）。

### 3. `scripts/reflect.mjs` — self-reflect 自动回写（阶段 C 落地）

关闭「自我改进」闭环：阶段运行后，编排者(AI)整理教训，本脚本把教训**结构化校验 + 按 type 路由 + 按 id 去重**持久化到正确的知识库文件，避免人工手改 JSONL 出错（对齐记忆治理 M3：原始 fact 只追加、不覆盖）。

路由表：`gotcha→knowledge/gotchas.jsonl`、`pattern→patterns.jsonl`、`decision→decisions.jsonl`、`anti-pattern→anti-patterns.jsonl`。

```bash
# 方式一：AI 在 run 收尾时整理的单条/批量教训
node scripts/reflect.mjs --lesson '{"id":"GOT-005","type":"gotcha","fact":"...","recommendation":"...","provenance":"B1 阶段C 实测","tags":["x"],"affectedFiles":["junheng-orchestrator/scripts/orchestrate.mjs"]}'
node scripts/reflect.mjs --lessons '[{...},{...}]'

# 方式二：从最新 .junheng/run-*.json 审计确定性派生（仅产出有真源支撑的条目）
node scripts/reflect.mjs --auto
```

校验规则（任一不满足即拒绝并 exit 1，符合「检查器必须可被证伪」）：`id` 非空、`type` ∈ 四值、`fact/recommendation/provenance` 非空字符串、`tags/affectedFiles` 为数组；`provenance` 缺失直接判失败（强制标注来源）。去重：按 `id` 精确匹配，已存在则跳过不覆盖。`--auto` 仅从审计派生三类有真源支撑的条目：全流程 PASS + Fresh Reviewer 生效→`pattern`；任一阶段 FAIL→`gotcha`；已批准人工检查点→`decision`；id 形如 `REF-<runId>-<type>-<n>` 保证跨 run 唯一。

### 4. `recover` 子命令 — 上下文恢复增强（阶段 C 落地）

在 `orchestrate.mjs` 新增 `recover`，输出**压缩式恢复简报**（目标/已完成/关键结论/待办/标识符/当前阶段），供断点续跑；**状态文件缺失时自动从最新审计重建 `state.json`**（审计真源优先于报错退出），满足「上下文恢复增强」。

```bash
node scripts/orchestrate.mjs recover          # 输出恢复简报；state 缺失时从审计重建
```

### 5. `check-agentskills.mjs` — agentskills.io 兼容性核查（B2 落地）

跨技能核查本地 `junheng-*` 是否兼容 [agentskills.io](https://agentskills.io) 开放标准；零依赖、可证伪、可 CI 门禁：
- **Tier1 强制**（agentskills.io 已抓取验证）：`SKILL.md` 存在、frontmatter 合法、`name`/`description` 非空、含指令正文；
- **Tier2 推荐**（Anthropic 开放标准惯例，明确非强制）：`name`==目录名、`name` 符合 `^[a-z0-9]+(-[a-z0-9]+)*$`、`description` ≤1024 字符且含触发词、双语 `description_en`、`author`/`version` 存在。

任一 T1 = FAIL → 退出码 `1`（阻断，不兼容）；仅 T2 WARN → 退出码 `0`（兼容，WARN 供人工跟进）。清单与运行快照见 `docs/agentskills-compat.md`。

```bash
node scripts/check-agentskills.mjs                  # 查默认 $HOME/.workbuddy/skills
node scripts/check-agentskills.mjs /path/to/skills  # 查指定根目录
node scripts/check-agentskills.mjs --json           # 机器可读输出
```

## 不照搬项（适配判断）

| metaswarm 项 | 本地替代 | 理由 |
|---|---|---|
| BEADS CLI | 本地 JSONL + git 状态 | 外部 CLI 依赖，违反零依赖铁律 |
| Claude Code 专有 Agent | WorkBuddy 现有 subagent | 平台已具备 |
| PR / CI / GTG merge gate | git commit + `vcs-all.sh lint` | 本地 lint 即等价门禁 |
| 18 个通用 SDLC persona | 不照搬；用 junheng 12 件套域技能 | 域能力已领先，通用角色是「全能壳」反模式 |
