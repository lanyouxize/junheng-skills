# Multi Search Engine

## 基本信息

- **名称**: multi-search-engine
- **版本**: v2.4.1
- **描述**: 集成17个搜索引擎（8国内+9国际），支持高级搜索语法
- **发布时间**: 2026-02-06

## 搜索引擎

**国内（8个）**: 百度、必应 CN、必应 INT、360、搜狗、微信、头条、神马
**国际（9个）**: Google、Google HK、DuckDuckGo、Yahoo、Startpage、Brave、Ecosia、Qwant、WolframAlpha

## 核心功能

- 高级搜索操作符（site:, filetype:, intitle:等）
- DuckDuckGo Bangs快捷命令
- 时间筛选（小时/天/周/月/年）
- 隐私保护搜索
- WolframAlpha知识计算

## 更新记录

### v2.4.1 (2026-10-13)
- 一致性修正（M9 回归验证与文档同步），**无行为变更**。
- `scripts/search_report.py` 换行归一为 **LF** —— 它是 5 个脚本里唯一以 CRLF 存储的，
  与 `engine_health.py` / `fetch_clean.py` / `validate_results.py` / `check_engine_consistency.py` 不一致。
- 版本元数据五源统一为 `v2.4.1`（`SKILL.md` / `metadata.json` / `_skillhub_meta.json` /
  `CHANGELOG.md` / 本文件）。

### 补记 · M9 文档同步回填（2026-10-13）
> 下列两项**当时未随包登记**，本次按工作区报告 §10.1–10.4 回填；脚本与文档均在包内可查，
> 未推测未证实的细节。

- **M1（2026-10-11，对应 v2.1.3）**
  - 新增 `scripts/check_engine_consistency.py`：以 `config.json` 为唯一真源，交叉核验引擎清单
    （14 项）与版本号（6 项）；退出码 `0` 一致 / `1` 不一致 / `2` 真源可疑。
  - `references/advanced-search.md` 补入**头条搜索专章**（章节次序与 `config.json` 对齐）；
    `SKILL.md` 补入头条。
  - 名单裁决：移除 `Jisilu`（集思录，非搜索引擎）、补入 `Shenma`（神马）；国内组仍 8 个、总数仍 17。
  - 本文件国内/国际名单与 `config.json` 对齐（此前国内少列 1 项、国际缺 `Google HK`）。

- **M2（2026-10-12）**
  - 新增 `references/result-contract.md`：检索结果结构化契约 `mse.result/1`（规则 V1–V11）。
  - 新增 `scripts/validate_results.py`：契约校验器（`--selftest` 17 项 / `--json` / `--summary`）；
    `status` 四态 `ok`/`empty`/`blocked`/`error` 不可合并 —— 「引擎被拦截」不得伪装成「无结果」。

### v2.4.0 (2026-10-13)
- 新增 `scripts/engine_health.py`：引擎健康度台账（路线图 O-5）。每次检索按
  「批次 × 引擎」登记进 `engine-health.jsonl`，输出 `mse.health.summary/1` 可用性榜。
- `empty`（引擎可用但无结果）计入可用，`blocked`/`error` 不计 —— 「被拦截」不得伪装成「没结果」。
- 判定四态不可合并：`insufficient-data`（样本不足，**无法判定**）/ `unavailable`（可用率 0）/
  `degraded`（<80%）/ `healthy`（≥80%）。第三态确保「样本不够」不伪装成「引擎不健康」。
- 去重键 = `(batch_id, engine)`，作用域为整个台账；提交顺序 = 临时文件 → 回读校验
  （新记录在册且旧记录不丢）→ 原子替换。
- 接受多 query 批次（台账本就跨 query 累积，与 M5 的有意差异）；`--window N` /
  `--no-append` / `--prune-older-than N [--yes]`（默认 dry-run，无法判龄的一律保留）。
- 新增 `references/health-contract.md`；复用 `validate_results.py` 做 V1–V11 前置校验。
- 自检 55 项（含真源证伪：改 `config.json` 看判定是否翻转）；9 轮变异测试在修好一处
  不具判别力的夹具后全部转红。版本元数据五源统一为 v2.4.0。

### v2.3.0 (2026-10-13)
- 新增 `scripts/search_report.py`：把 `mse.result/1` 批次升级为 `mse.report/1` 交叉核验报告，
  机械标注「仅单引擎命中」为待核（路线图 F-1）。
- 三态判定不可合并：`cross-verified` / `single-engine`（待核）/ `insufficient-engines`（无法核验）——
  第三态确保「只有一个引擎成功返回」不会伪装成「这条结论存疑」。
- 聚类两维度：归一化 URL（去 www/默认端口/fragment/跟踪参数、query 排序、去尾斜杠）
  + 归一化标题相似度（默认 0.90，覆盖百度跳转链 vs 必应原站的同一篇）。
- 新增 `references/report-contract.md`；复用 `validate_results.py` 做 V1–V11 前置校验，不复制判据。
- 自检 36 项（含证伪用例）；5 轮变异测试全部转红；版本元数据五源统一为 v2.3.0。

### v2.2.0 (2026-10-12)
- **新增正文提取层** `scripts/fetch_clean.py`：URL → 可直接喂给 LLM 的 Markdown
  （对应方案 O-4 正文提取层 + F-2 `fetch-clean` 清洗器，二者是同一能力）
  - 仅标准库：`html.parser.HTMLParser` 自建最小 DOM，不引入 bs4/lxml，Markdown 转换自写
  - 清洗：连子树丢弃 script/style/nav/footer/aside/form 等；按 `<article>`/`<main>`
    + id/class 提示词 + 文本量打分选主内容区；转换标题/列表/代码/引用/表格/链接
  - 剔除永久链接锚点（`¶` 及 `class="headerlink"` 一类），它们属页面装饰不是正文
  - 站点适配器是**数据不是代码**（`ADAPTERS`）：`github`（仓库/blob → raw README）、
    `github-raw`；`csdn` 条目标注 `verified: false`（本环境对文章详情页稳定返 HTTP 521）
  - 默认诚实 UA + 默认遵守 robots.txt；`--ua browser` / `--ignore-robots` 为显式选择；
    robots 取不到时放行但**必须在 notes 里出声**
- **新增契约 `mse.fetch/1`**（`references/fetch-contract.md`）：四态 `status`
  （`ok` / `empty` / `blocked` / `error`），使「被 WAF 拦截」不会伪装成「页面没内容」
- 版本元数据统一为 v2.2.0（SKILL.md、metadata.json、_skillhub_meta.json、CHANGELOG.md、CHANNELLOG.md）

### v2.1.3 (2026-10-11)
- 版本元数据统一为 v2.1.3（SKILL.md、_skillhub_meta.json）
- 引擎集合确认为 17 个（8 国内 + 9 国际）

> ⚠ v2.1.0–v2.1.2 的变更明细未随本技能包分发，本地无可复原证据。
> 为不编造历史，此处不填充推测内容；完整历史请以市场侧发布记录为准。

### v2.0.1 (2026-02-06)
- 精简文档，优化发布

### v2.0.0 (2026-02-06)
- 新增9个国际搜索引擎
- 强化深度搜索能力

### v1.0.0 (2026-02-04)
- 初始版本：8个国内搜索引擎

## 使用示例

```javascript
// Google搜索
web_fetch({"url": "https://www.google.com/search?q=python"})

// 隐私搜索
web_fetch({"url": "https://duckduckgo.com/html/?q=privacy"})

// 站内搜索
web_fetch({"url": "https://www.google.com/search?q=site:github.com+python"})
```

MIT License
