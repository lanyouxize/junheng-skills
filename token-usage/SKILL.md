---
name: "token-usage"
version: "1.0.0"
display_name: "Token 用量统计"
display_name_en: "Token Usage Dashboard"
description: 统计 WorkBuddy/CodeBuddy 的 token 消耗并生成可视化用量面板。当用户问 token 消耗、用量统计、花了多少额度，或要打开用量面板时使用；支持 30 秒自刷新的实时面板，产出明细与趋势。
description_zh: "统计 WorkBuddy/CodeBuddy 的 Token 消耗：实时面板（30 秒自刷新）、热力图、每日趋势、模型用量占比、当前会话拆分、JSON 导出。纯本地处理，不上传任何数据，离线可用。"
description_en: "Token usage dashboard for WorkBuddy/CodeBuddy: live panel (30s auto-refresh), heatmap, daily trend, model breakdown, per-session stats, JSON export. 100% local processing, zero data upload, works offline."
allowed-tools: "Bash, Read"
license: Proprietary
compatibility: Python 3.9+; Node.js 18+.
---

# WorkBuddy Token 使用统计 Skill

统计 WorkBuddy（CodeBuddy CLI 内核）在本机产生的 Token 消耗，输出与桌面端"使用统计"面板同风格的可视化报告。

## Purpose

从本地会话转录（JSONL）中聚合 Token 用量，回答三类问题：
1. **总量类**：累计消耗多少 token？输入/输出/缓存/推理各占多少？
2. **行为类**：哪些天活跃？连续使用几天？最长会话多久？
3. **结构类**：各模型的用量占比？近 7/30 日趋势如何？

## Trigger Conditions

**Use this skill when** 用户想要：
- 查看 token 消耗 / 用量 / 花费统计（"统计一下 token 消耗"、"我用了多少 token"）
- 看用量可视化面板 / 使用统计 / 热力图 / 趋势图 / 模型用量占比
- 导出用量 JSON 做进一步分析

**Do NOT use this skill when**：
- 询问 API 计费金额/价格（本 skill 不含价格表，只统计 token 数量）
- 统计其他产品（Claude Code、Cursor 等）的用量——数据目录不同

## 数据源与口径

| 项 | 说明 |
|---|---|
| 数据来源 | `~/.codebuddy/projects/**/*.jsonl` 会话转录（可用 `--data-dir` 覆盖） |
| 记录位置 | 每条模型响应记录的 `providerData.usage`（camelCase），兼容 `message.usage`（snake_case）兜底；同一条记录两处并存时只计一次 |
| Token 口径 | `totalTokens = inputTokens + outputTokens`（**含**缓存读取部分），与官方口径一致 |
| 轮次 | `providerData.usage.requests` 之和（一次模型调用 = 一轮） |
| 峰值 | 单日 `totalTokens` 最大值 |
| 最长会话时长 | 单个转录文件首尾时间戳的跨度（近似会话墙钟时长） |
| 当前会话 | `~/.codebuddy/sessions/*.json` 中心跳最新的 interactive 会话（回退：最近有记录的转录），面板"当前会话消耗"卡片即此口径 |
| 缓存命中率 | `cache_read / input_tokens`（缓存读取占输入比例） |
| 当前连续天数 | 从今天（或昨天）往前数的连续活跃天数 |
| 日期口径 | 时间戳按本地时区归日（可用 `--tz` 指定） |

**数据边界（重要）**：本 skill 只能统计 `--data-dir` 内实际存在的转录。agent 沙箱通常只挂载当前 Teams 会话的转录文件，**桌面客户端的历史会话数据存在用户本机**，沙箱读不到——用户想统计桌面端全部历史，需把本机 `~/.codebuddy/projects`（Windows: `%USERPROFILE%\.codebuddy\projects`）目录打包上传后用 `--data-dir` 指向它。

**已知局限**：会话时长按转录首尾时间戳估算，会话长时间空闲时会低估；转录文件被清理的历史数据无法统计；纯文本回复（无工具调用）的响应若未写入 usage 记录则不计入。

## Workflow

### 第 0 步：意图确认（对话选择框）

- 用户意图**明确**（如"打开 token 面板"）→ 直接执行方式 A，不要多问
- 用户意图**模糊或首次使用**（如只说"token"、"看看用量"）→ 用 AskUserQuestion 弹出选择框告知可选项：
  - **打开实时面板**（推荐）：预览区打开，30 秒自刷新
  - **生成静态快照**：自包含 HTML 文件，可转发/离线看
  - **导出 JSON 明细**：给 further 分析用
- 用户问题属于"看不到历史/数据不对"→ 先看下方"数据边界"解释，再给方案

### 方式 A：实时面板服务（推荐，可作快捷入口）

面板常驻本地端口，**每 30 秒自动刷新**，用户点击链接即可查看最新数据：

1. **健康检查**（服务可能已在运行）：

```bash
curl -s --max-time 2 http://127.0.0.1:8642/healthz
```

2. **未运行则后台拉起**（Bash 工具需 `run_in_background=true`）：

```bash
python3 <skill-directory>/scripts/token_stats.py --serve 8642 --tz Asia/Shanghai
```

3. **用 present_files 打开 `http://127.0.0.1:8642`** → 内置浏览器面板。用户收藏该链接/消息后即为常驻快捷入口。**渲染入口卡片的同时必须 present_files 打开面板**——卡片按钮只是"以后再开"的快捷方式，不能只给卡片不开面板。
4. 服务因沙箱休眠停止时，重复步骤 1-3 即可恢复。
5. **入口卡片刷新**：对话内的"📊 Token 实时面板"widget 卡片会每 30 秒自行拉取 `/api/stats`（服务已开 CORS）；若需重新渲染卡片，先 `curl /api/stats` 取最新值注入小字（累计/本会话/缓存命中率/轮次）。
6. **卡片规范（勿偏离）**：只用 show_widget 渲染，**仅一个「打开面板」按钮**，onclick 调用 `tpeOpen()`（脚本内置 sendPrompt 能力检测：可用则发送"打开 token 面板"；**不可用时自动显示兜底提示行**"请在对话框输入：打开 token 面板"——部分客户端 widget 环境没有 sendPrompt，直接调用会点击无反应）。**禁止加"新窗口/直连链接"类按钮**——用户在桌面客户端内操作，外链有歧义且可能不可达。卡片底部固定一行灰字说明："点击「打开面板」→ 在本软件的预览面板中显示，数据每 30 秒自动更新，无需其他操作"。数据行样式：绿色 `#4ade80`、`white-space:nowrap` 超宽省略。
7. **卡片出现时机**：widget 卡片是 agent 主动渲染的组件，**不会每轮自动出现**。凡触发本 skill（用户提到 token/面板/用量，或执行了面板打开操作），都应**重新渲染一次入口卡片**（用最新 `/api/stats` 数据），让用户当前对话里始终有可点击入口；用户收藏含卡片的消息后可跨对话复用。

服务端点：`/` 实时面板 · `/api/stats` JSON（live 数据）· `/healthz` 健康检查。

### 方式 B：静态快照 / 明细导出

```bash
# 生成自包含 HTML（ECharts 已内联，离线可开）+ JSON 明细 + 终端摘要
python3 <skill-directory>/scripts/token_stats.py \
  --html /workspace/token_dashboard.html \
  --json /workspace/token_stats.json \
  --tz Asia/Shanghai
```

生成后用 present_files 展示 HTML，并转述关键数字（累计、峰值、连击天数、Top 模型占比）。

### 参数速查

| 参数 | 说明 |
|---|---|
| `--serve [PORT]` | 启动实时面板服务（默认端口 8642），面板每 30 秒自动刷新 |
| `--host ADDR` | 服务绑定地址（默认 127.0.0.1） |
| `--data-dir PATH` | 转录根目录，默认 `~/.codebuddy/projects` |
| `--html PATH` | 生成自包含 HTML 面板（静态快照） |
| `--json PATH` | 输出结构化 JSON（含 per_day / per_model / per_session 明细） |
| `--tz NAME` | 时区，如 `Asia/Shanghai`；默认系统本地时区 |
| `--quiet` | 不打印终端摘要 |

## Output Specification

- **终端摘要**（默认输出）：累计/输入/输出/缓存/推理、峰值、最长会话、连续天数、模型占比表——可直接转述给用户
- **HTML 面板**：5 张指标卡 + 52 周 Token 活动热力图（tooltip：日期 · tokens · 轮次）+ 近 7/30 日趋势（可切换、按日补零）+ 模型用量环形图（中心显示合计，联动时间范围）
- **JSON**：`total_tokens` / `per_day` / `per_model` / `per_session` / `peak_*` / `*_streak` 等全量字段

## Quality Control

- 生成后用脚本自身输出的数字与终端摘要核对；HTML 中心合计应等于所选范围的 `per_day` 之和
- 若 `files_scanned == 0`，检查 `--data-dir` 是否正确、转录是否存在
- 抽查：任取一条 JSONL 记录的 `totalTokens`，应已包含在累计值中

## Failure Handling

| 现象 | 处理 |
|---|---|
| 数据目录不存在 | 脚本退出码 1；确认 `~/.codebuddy/projects` 存在或用 `--data-dir` 指定 |
| 面板链接打不开 | 先 `curl /healthz` 检查；服务已停则重新后台拉起（沙箱休眠会终止进程） |
| 端口被占用 | 换端口：`--serve 8643`，并用新 URL 打开面板 |
| ECharts 下载失败 | 自动回退 CDN 引用；断网环境可手动放置 `scripts/echarts.min.js` |
| 记录解析失败 | 单行跳过，不影响整体；大量失败时检查转录格式版本 |
| 时区报错 | 警告后回退系统本地时区 |

## Edge Cases

- 多项目目录（`projects/<项目名>/*.jsonl`）自动全量扫描
- 子代理/后台任务的转录一并计入（可从 JSON 的 `per_session` 按文件区分）
- 跨天长会话：token 按每条记录的时间戳归到各自日期
- 稀疏数据：趋势图按日历日补零，避免把范围外日期误算进"近 N 日"

## Examples

```text
用户：统计一下我最近的 token 消耗
→ python3 <skill-directory>/scripts/token_stats.py --html /workspace/token_dashboard.html --tz Asia/Shanghai
→ present_files /workspace/token_dashboard.html
→ 转述：累计 X tokens，峰值 Y（单日），连续使用 N 天，glm-* 占比 Z%…

用户：近 30 天哪个模型用得最多？
→ 脚本 --json 后读 per_day 近 30 日聚合，或直接看终端摘要的模型用量表
```

## Maintenance Strategy

- 转录格式升级（如 usage 字段更名）时，仅需修改 `extract_record()` 中的字段映射
- ECharts 版本升级：替换 `scripts/echarts.min.js`
- 未来可选迭代：价格/成本估算（需维护模型单价表）、按 agent 类型拆分、周报导出
