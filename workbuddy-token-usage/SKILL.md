---
name: workbuddy-token-usage
version: 1.0.0
description: 分析 WorkBuddy 的 AI 调用 Token 消耗与成本。解析本机 traces 日志，按模型、会话、Agent、机器拆分统计缓存命中率、每日趋势与 Top-N 异常会话，按官方价换算费用，产出自包含 HTML 报表与 CSV。当用户问消耗、花费、哪个模型最贵时使用。
display_name: WorkBuddy Token 消耗分析
display_name_en: WorkBuddy Token Usage Analysis
description_zh: 本地只读分析 WorkBuddy 每次 AI 调用的 Token 消耗与成本。统计总览、按模型/会话/Agent/机器拆分、缓存命中率、每日趋势、时段分布、Top-N 异常会话，并按 DeepSeek 官方价换算费用，生成自包含 HTML 报表与 CSV，支持日期区间与多维筛选。
description_en: Locally analyze (read-only) the Token consumption and cost of every WorkBuddy AI call. Summarizes totals, breaks down by model/session/agent/worker, cache hit rate, daily trend, hourly distribution, and Top-N costly sessions, then converts to cost using official DeepSeek pricing and produces a self-contained HTML report and CSV with date-range and multi-dimension filters.
category: skill
---

# WorkBuddy Token 消耗分析

纯本地、只读地分析 `~/.workbuddy/traces/*/trace_*.json` 中每次 AI 调用的 Token 明细，并换算成费用。不联网、不写 traces、不读取任何凭证或个人信息以外的文件。

## 触发场景

- 「看看昨天/今天/本周/本月消耗了多少 token」
- 「按 DeepSeek 价格算一下花了多少钱」
- 「哪个模型 / 哪个 Agent / 哪台机器 用得最多」
- 「最近 7 天 token 趋势」「哪天用量暴涨了」
- 「导出一份 token 报表 / CSV」

## 调用方式

脚本位置：`scripts/analyze.py`（用系统/托管 Python 3 运行）。

将用户的自然语言映射到参数：

| 用户意图 | 参数 |
|---|---|
| 今天 / 昨天 / 最近7天 / 最近30天 / 本周 / 本月 / 全部 | `--range today\|yesterday\|last-7d\|last-30d\|this-week\|this-month\|all` |
| 「9月1日到9月3日」 | `--from 2026-09-01 --to 2026-09-03` |
| 比价指定模型 | `--models v4-flash,v4-pro`（默认 provider 下全部） |
| 换厂商 | `--provider deepseek`（当前仅内置 deepseek） |
| 只出文本不要文件 | `--report none` |
| 只要 CSV / 只要 HTML | `--report csv` / `--report html` |
| Top-N 会话数 | `--top 15` |
| 脱敏（分享用） | `--anonymize`（workerHostname 泛化、sessionId 置空） |
| 指定输出目录 | `--out /path/to/dir` |

示例：
```bash
python3 scripts/analyze.py --range yesterday
python3 scripts/analyze.py --range last-7d --report html,csv
python3 scripts/analyze.py --from 2026-09-01 --to 2026-09-03 --top 15
```

## 输出

- **控制台摘要**：会话数、调用次数、总/输入/输出/缓存 Token、缓存命中率、各 DeepSeek 模型估算费用、按模型拆分、Top-3 会话。把关键数字转述给用户。
- **HTML 报表**（默认生成于 `reports/`）：KPI 卡片、缓存命中环形图、成本估算表（DeepSeek Flash/Pro）、按模型表、每日趋势折线图、24h 时段分布柱图、Top-N 会话、按 Agent / 机器下钻表。自包含、内嵌 SVG、离线可开。**直接写出文件并告知用户路径即可，不要用 present_files 启动本地静态预览服务，用户自行打开文件。**
- **CSV 明细**（默认生成）：每条会话一行，含时间、Agent、机器、模型、调用次数、各 Token 字段。加 `--anonymize` 可脱敏设备名与 sessionId，便于对外分享。

## 成本换算说明

- 单价见 `references/prices.json`（当前仅 DeepSeek V4 Flash / V4 Pro 官方价，单位 元/百万 token，含缓存命中/未命中/输出、高峰/空闲）。
- DeepSeek 高峰时段为北京时间 09:00–12:00、14:00–18:00，空闲时段价格为高峰一半。脚本按每条会话真实发生时段（startedAt→endedAt 与高峰窗口的重叠比例）加权计算「实际混合」费用。
- 缓存命中率 = 缓存命中 Token / 输入 Token。高命中率会大幅降低按量计费（可在报表中提示「若无缓存会多花约 X 倍」）。
- 如需新增厂商价目表，只需在 `references/prices.json` 的 `providers` 下追加，并把模型 key 写入 `--models` 即可。

## 安全

- 仅读取 `~/.workbuddy/traces/`，只读，绝不修改、删除或上传任何文件。
- 报表与 CSV 默认写在技能目录 `reports/` 下，均为本地文件。
