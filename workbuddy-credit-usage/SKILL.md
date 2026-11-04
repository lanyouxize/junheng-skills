---
name: workbuddy-credit-usage
description: 读取 WorkBuddy 本节点与当前会话消耗的官方积分（credit）。用于任务收尾核对积分消耗、判断是否超过熔断阈值，或查当前会话累计与逐模型积分。数据源为本机会话日志的 rawUsage.credit，与 App 账单同源。
---

# WorkBuddy 本节点消耗积分（官方 credit）

## Purpose

读取**当前会话（= 本节点/本任务）**消耗的**官方积分**（credit），用于**节点**收尾的「**节点熔断**」判定（如 `≤30 可续 / >30 本节点结束、任务内开启下一节点`）。

- **单位对齐**：直接读 `providerData.rawUsage.credit`——**与 App「套餐与用量 → 积分消耗明细」同源**（口径对齐开源项目 `majiabin2020/workbuddy-token-dashboard` 的 `grab()`）。
- 区别于纯 token 统计：本技能给的是**积分**，即熔断阈值所用的单位。

## 数据源与口径

| 项 | 说明 |
|---|---|
| 数据来源 | `~/.workbuddy/projects/**/*.jsonl`（可用 `--projects` 覆盖） |
| 积分字段 | `providerData.rawUsage.credit`（float，逐请求） |
| Token 字段 | `providerData.rawUsage.total_tokens` / `usage.totalTokens`（兜底） |
| 模型 | `providerData.model` → `requestModelId` → `requestModelName` |
| 当前会话识别 | 优先在 **`cwd` 对应的项目目录**（`projects/<cwd 派生目录>/*.jsonl`）内取 **mtime 最新**者——多开 WorkBuddy 窗口时会话并发写入，全局取最新会**串台**到别的项目；其 `<sid>/subagents/**` 子代理用量**一并计入**。可用 `--session` / `--cwd` 覆盖 |
| 边界 | `credit` 缺失的老格式记录不计积分、仍计 token；日志清理后的历史无法回溯 |

## Workflow

脚本：`scripts/node_credit.py`（仅标准库）。

```bash
PY="<managed python>"   # 本机: C:/Users/Administrator/.workbuddy/binaries/python/envs/default/Scripts/python.exe
SC="<skill-dir>/scripts/node_credit.py"
SID="<本任务会话 sid>"   # 必填示例：如 2bae3620-445a-4bfe-b001-93c7ebf8fa67；自动探测会话在多项目并存时会串台（见下方「当前会话识别」）

# 任务【结束】处（推荐）：单轮口径 = 自最近一条用户消息起
#   与 App 消息下「共消耗」逐值同源，无需 --mark、天然对齐用户消息边界
#   ⚠ 必须显式 --session：铁律③硬要求，杜绝多项目串台
"$PY" "$SC" --turn --session "$SID"

# （普通档·软限预警）--turn 在 25~30 分会输出 [预警] 提示收尾（硬限 30 仍触发 --gate）
#   返回 JSON 含 turn_state: ok(<=25) / warn(25~30) / over(>30)

# （普通档·趋势周报）近 N 天按 日/项目/模型 拆解积分趋势，输出 CSV（不建看板）
"$PY" "$SC" --report --report-days 7 --report-out "<输出.csv>"

# （可选）跨多轮任务总量：开始 --mark、结束 --delta
#   delta 并列给出与 App 同口径的单轮值；检测到跨轮会告警
"$PY" "$SC" --mark --session "$SID"
"$PY" "$SC" --delta --session "$SID"

# 想直接看当前会话累计积分 / 逐模型拆分
"$PY" "$SC" --model --session "$SID"

# 机器可读（CI / 自动化）
"$PY" "$SC" --json --session "$SID"
```

### 两种口径（务必分清，2026-10-14 修正）

| 口径 | 命令 | 窗口 | 是否需 --mark | 适用 |
|---|---|---|---|---|
| **单轮** | `--turn` | 自**最近一条用户消息**起（= App「共消耗」） | 否 | **节点/批次末尾实测（推荐）** |
| 累计差 | `--delta` | 自 **--mark 那一时刻**起 | 是 | 跨多轮任务总量 |

> ⚠ 教训：App「共消耗」是**单轮**值。曾用 `--mark/--delta` 当单轮值，因 mark 落在轮中（跨了半轮 + 一个中间轮）而**多算**（实测 delta=7.06 vs 平台真值 4.94）。**要对照 App，就用 `--turn`。** `--delta` 现也会并列打印单轮值并在跨轮时告警。

> **普通档新增（2026-10-20）**：节点阈值仍 **30（硬熔断）**，但 `--turn` 在 **25~30 分**额外输出 `[预警]`（`turn_state=warn`），提示本节点接近上限、建议收尾；仅 **>30** 才由 `--gate` 退出码 1 触发硬熔断。另新增 `--report`（近 N 天，按 **日/项目/模型** 拆解积分趋势的 CSV 周报，对标 `codeburn`/`ccusage` 的按维度拆解，但**不建看板**，看板留待最佳档）。

- `--mark` 把当前累计积分 + **当前用户消息边界（`turn_ts`）** 写入基线文件（默认**按会话隔离**：`scripts/.node_credit_baseline.<sid>.json`，可用 `--baseline` 改；多窗口并发互不覆盖，旧共享基线在同会话时自动兼容读取）。
- `--delta` 输出 `node_delta_credit`（累计差）、`node_turn_credit`（**单轮口径，与 App 同值**）、`threshold=30`、`within_threshold`，并在**会话切换**或**跨轮**（`turn_crossed`）时告警。
- `--session SID` 指定会话；`--cwd DIR` 指定工作目录（用于定位本任务会话，默认系统 cwd）；`--projects DIR` 指定日志根目录。
- **多窗口并发**：会话识别以 `--cwd` 派生的项目目录为作用域；若识别出的会话不属于该目录，脚本会打印 `[warn]` 提示并建议 `--session` 显式指定。

## Output

- 人读：会话 sid / 日志路径 / 累计积分 / 请求数 / token 合计（+ 可选逐模型积分）。
- JSON：`session` / `session_credit` / `requests` / `per_model_credit` /（delta 模式）`node_delta_credit` / `threshold` / `within_threshold` /（turn 模式）`turn_credit` / `turn_start` / `turn_requests` / `turn_state`(ok|warn|over) / `turn_warn`(25)。

## Quality Control

- **自证**：`--json` 的 `session_credit` 应等于会话（含子代理）内全部 `rawUsage.credit` 之和；`credit_requests` 接近 `requests`。
- **单位核对**：`--turn` 读数应与 App 消息下方「共消耗」逐值一致（2026-10-13 实测：单轮 4.73 = 4.73，零误差；2026-10-14 复核：封存轮 4.94 = 4.94，逐值吻合）；单请求实测区间约 0.02–4.5，单轮合计典型 3–6。
- **残余误差（可接受，结构性）**：`--turn` 读数发生在**轮次进行中**——其后的收尾请求（最终回复生成等）尚未落入日志，故实测值**略低于**轮末完整值。实测 3.58 vs 3.73（残余 ~0.15，约 4%）。**该残差必然存在、无法完全消除**（读数动作本身也在轮内）；对熔断判定（阈值 30）无实质影响。可在长期使用中观察是否需进一步逼近。
- **会话正确性**：`session_file` 的 mtime 应为最近时刻；若识别到别的会话，用 `--session` 显式指定。

## Failure Handling

| 现象 | 处理 |
|---|---|
| 日志目录不存在 | 脚本退出并提示；用 `--projects` 指定正确目录 |
| 未找到基线 | `--delta` 前先跑 `--mark` |
| 会话切换告警 | 基线属上一会话 → 重新 `--mark` |
| 累计增量与 App「共消耗」不符 | 系口径差异（delta 含跨轮）→ 改用 `--turn`（单轮口径），或取 `--delta` 打印的单轮值 |
| 串台告警（会话不在当前项目目录） | 用 `--cwd` 指向本任务工作目录，或 `--session` 显式指定 |
| credit 全为 0 / 缺失 | 老格式日志或非计费请求；改用 token 口径参考 |

## Notes

- **纯本地只读**，不上传任何数据。
- 基准来源：开源 `workbuddy-token-dashboard`（官方 credit 口径 `rawUsage.credit`）。本技能是其**最小可用子集**——只做「本节点积分」这一件事，供熔断判定调用。
