---
name: junheng-orchestrator
description: 钧衡 NutriAgent 配方研发多技能编排框架（非运行时）。把现有 junheng 域技能（证据→标准映射→配方计算→达成度验证→标签→合规→报告）按标准 pipeline 串联并施加质量门禁，使长流程可审计、可回放、不可跳过门禁。当用户需要「一键跑完配方研发全流程」「把多个 junheng 技能串成可审计闭环」「给配方任务加质量门禁与审计追踪」时使用。编排层只做串联与门禁，不重造域逻辑。
description_en: Junheng NutriAgent recipe-R&D multi-skill orchestration framework (not a runtime). Chains existing junheng domain skills (evidence→standards→formulation→attainment→labeling→compliance→report) into an auditable pipeline with quality gates. Use when the user wants a one-shot auditable recipe-R&D flow or to add quality gates/audit trails to a formulation task.
author: Junheng NutriAgent
version: 0.1.0
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

## 不照搬项（适配判断）

| metaswarm 项 | 本地替代 | 理由 |
|---|---|---|
| BEADS CLI | 本地 JSONL + git 状态 | 外部 CLI 依赖，违反零依赖铁律 |
| Claude Code 专有 Agent | WorkBuddy 现有 subagent | 平台已具备 |
| PR / CI / GTG merge gate | git commit + `vcs-all.sh lint` | 本地 lint 即等价门禁 |
| 18 个通用 SDLC persona | 不照搬；用 junheng 12 件套域技能 | 域能力已领先，通用角色是「全能壳」反模式 |
