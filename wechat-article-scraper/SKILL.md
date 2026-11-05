---
name: wechat-article-scraper
display_name: 微信公众号图文爬取与知识库导出
display_name_en: WeChat Article Scraper
description_zh: 微信公众号图文内容爬取与多平台知识库导出工具 v1.2.0：搜狗微信搜索发现文章 + URL直接抓取全文、按公众号名称/关键词/时间范围组合检索、文章全文解析（标题/作者/日期/摘要/正文/图片）、Markdown/Text/HTML/JSON四种格式、ZIP打包导出、纯文本Markdown目录导出、IMA知识库/Dify Dataset/Obsidian Vault三大知识库一键同步（凭证走环境变量）、智能去重（规范链接+内容哈希+标题相似度并给出重复原因）、日期范围过滤+关键词过滤+相关性排序、离线抽取式摘要与关键词统计、爬取历史记账支持增量采集、图片本地化、请求限速+瞬时故障自动重试（遵守Retry-After）+缓存TTL+反爬验证页与429限流识别+导出目录越界防护。
description_en: 'WeChat Official Account article scraping and multi-platform knowledge base export v1.2.0: Sogou WeChat search discovery + direct URL full-text fetch, search by account name / keyword / date range, article parsing (title/author/date/summary/body/images), Markdown/Text/HTML/JSON formats, ZIP packaging plus text-only Markdown folder export, IMA/Dify/Obsidian sync (credentials from environment variables), intelligent dedup (canonical link + content hash + title similarity with reasons), date/keyword filtering + relevance ranking, offline extractive summarization and keyword extraction, scrape-history journal for incremental crawling, local image download, rate limiting + transient retry honoring Retry-After + cache TTL + anti-bot and HTTP 429 detection + export path containment.'
version: 1.2.0
description: 微信公众号图文爬取与多平台知识库导出。支持搜狗搜索发现、URL 直抓与批量一体化三种模式；输出 Markdown/Text/HTML/JSON；可一键同步到 IMA、Dify、Obsidian（API Key 优先读环境变量）并智能去重。
---

# wechat-article-scraper v1.2.0 — 微信公众号图文爬取与知识库导出

> **搜狗搜索 + URL直接抓取 + 批量一体化** | **4种格式 + 纯文本目录导出** | **IMA/Dify/Obsidian 三大知识库** | **智能去重 + 过滤排序 + 离线摘要** | **限速 + 瞬时重试 + 限流可见** | **MCP Server 21 工具**

## ⚡ 一键上手

```
帮我爬一下"人民日报"公众号最近7天的文章
爬取"36氪"公众号上关于AI的文章，从2025-01-01到2025-01-31
把这几个微信链接的内容获取下来：https://mp.weixin.qq.com/s/xxx
爬取"财联社"所有关于基金的文章，导出为ZIP
帮我把公众号文章同步到Obsidian知识库
增量爬一下"机器之心"，只给我没见过的文章
把这批文章的摘要和高频关键词整理出来
```

## 📐 架构总览

```
wechat-article-scraper/
├── SKILL.md              # 本文件：Skill 定义
├── mcp_server.py         # MCP Server（21 工具，stdio JSON-RPC，帧通道锁定 UTF-8）
├── config.json           # 全局配置（限速/重试/超时/自动取全文上限/缓存TTL）
├── requirements.txt      # Python 依赖
├── clean.py              # 清理脚本（上传前去掉二进制文件）
├── pytest.ini            # 测试配置（不生成 .pytest_cache）
├── run_tests.py          # 测试入口（禁用 .pyc 写入）
├── core/                 # 核心模块
│   ├── utils.py          # 日期/URL规范化/限速/重试退避/凭证/目录/反爬识别
│   ├── article_parser.py # 文章HTML解析（标题/作者/日期/摘要/正文/图片）
│   ├── filters.py        # 日期+关键词过滤+相关性排序+链接去重
│   ├── dedup.py          # 智能去重（规范链接+哈希+相似度，带原因）
│   ├── state_store.py    # 爬取历史记账（增量爬取依据，原子写入）
│   ├── summarizer.py     # 离线抽取式摘要+关键词+批量统计
│   └── image_downloader.py # 文章图片本地化 + Markdown 链接改写
├── scrapers/             # 爬取器
│   ├── sogou_search.py   # 搜狗微信搜索（文章/公众号发现、验证页识别）
│   ├── article_fetcher.py# 文章全文获取（URL→内容、缓存TTL、重试、计数器）
│   └── direct_url.py     # URL直接抓取（单个/批量/文本提取）
├── exporters/            # 导出器
│   ├── zip_exporter.py   # ZIP 多格式打包（写入临时目录，正文先转义再生成 HTML）
│   ├── markdown_exporter.py # 纯文本 Markdown 目录 + index.csv + 摘要
│   ├── ima_exporter.py   # IMA 知识库同步
│   ├── dify_exporter.py  # Dify Dataset 同步
│   └── obsidian_exporter.py # Obsidian Vault 同步（folder 不得越出 vault）
├── tests/                # 测试（conftest 隔离产物目录）
│   ├── conftest.py       # 每个用例把缓存/历史/导出指向临时目录
│   ├── test_core.py      # 基础能力
│   ├── test_v110_features.py # v1.1 特性与缺陷回归
│   ├── test_v120_hardening.py # v1.2 重试/转义/路径/凭证回归与文档对账闸
│   └── test_mcp_stdio.py # 真实子进程跑 MCP stdio 协议
└── data/                 # 运行期缓存与历史（可用环境变量改到别处）
```

运行期目录（默认都不落在技能包内）：
- 导出产物：`WECHAT_SCRAPER_EXPORT_DIR` > `config.export.default_output_dir` > 系统临时目录
- 缓存/历史：`WECHAT_SCRAPER_DATA_DIR` > `data/`
- 知识库凭证：`WECHAT_SCRAPER_IMA_API_KEY` / `WECHAT_SCRAPER_DIFY_API_KEY`
  优先于 `config.json`，密钥不必写进随包上传的配置文件

## 🔧 工具列表（MCP Tools）

| # | 工具名 | 功能 | 关键参数 |
|---|--------|------|----------|
| 1 | `search_wechat_articles` | 搜狗搜索微信文章 | account_name, keyword, start_date, end_date, keywords, max_articles, fetch_limit |
| 2 | `fetch_wechat_article` | URL获取全文 | urls（字符串/数组/混合文本） |
| 3 | `export_articles_zip` | ZIP多格式打包 | articles, output_dir, formats |
| 4 | `export_to_ima` | 导出到IMA知识库 | articles, kb_id |
| 5 | `export_to_dify` | 导出到Dify Dataset | articles, dataset_id |
| 6 | `export_to_obsidian` | 导出到Obsidian Vault | articles, vault_path, folder, group_by_account |
| 7 | `filter_articles` | 过滤+排序+去重 | articles, start_date, end_date, days, keep_undated, keywords, rank, dedup, limit |
| 8 | `batch_scrape` | 一体化批量爬取 | account_name, keyword, days, export_format, incremental, with_digest |
| 9 | `search_wechat_accounts` | 查找公众号账号 | account_name, max_pages |
| 10 | `parse_wechat_html` | 离线解析文章HTML | html / file_path, url |
| 11 | `extract_wechat_urls` | 从文本提取微信链接 | text, only_wechat |
| 12 | `scrape_from_file` | 从链接文件批量抓取 | file_path |
| 13 | `deduplicate_articles` | 去重并给出原因 | articles, similarity_threshold, use_content_hash |
| 14 | `summarize_articles` | 离线摘要+关键词+统计 | articles, top_keywords, max_sentences, output_md |
| 15 | `download_article_images` | 文章图片本地化 | articles, output_dir, max_images |
| 16 | `export_articles_markdown` | 纯文本Markdown目录导出 | articles, folder, group_by_account |
| 17 | `get_cache_status` | 缓存与历史状态 | — |
| 18 | `clear_article_cache` | 清理缓存/历史 | also_history |
| 19 | `get_scrape_history` | 查询爬取历史 | account, limit |
| 20 | `filter_new_articles` | 只保留未见过的文章 | articles, record |
| 21 | `get_skill_stats` | 环境自检（依赖/stdio 编码/目录/网络与凭证状态） | — |

## 🚦 使用模式

### 模式一：按公众号+时间爬取
```python
call_tool("batch_scrape", {
    "account_name": "36氪",
    "start_date": "2025-06-01",
    "end_date": "2025-06-30",
    "export_format": "zip",
    "output_dir": "D:/微信文章"
})
```
`batch_scrape` 返回 `pipeline` 段，逐步骤给出：搜索条数、去重删除数、历史已跳过数、
全文获取成功数、新记账条数。结束日期按"整天"计算，当天发布的文章不会被漏掉。
`search_wechat_articles` 默认只给前 20 篇取全文（`fetch_limit` 可调，0=不限），
超限部分保留标题与摘要，结果里会明确回 `fetch_capped` 而不是悄悄少给。

### 模式二：按关键词搜索
```python
call_tool("search_wechat_articles", {
    "keyword": "基金投资",
    "max_pages": 10,
    "keywords": ["基金", "ETF"],
    "fetch_content": True
})
```

### 模式三：URL直接抓取
```python
call_tool("fetch_wechat_article", {
    "urls": "https://mp.weixin.qq.com/s/xxx https://mp.weixin.qq.com/s/yyy"
})
```
返回中的 `skipped_non_wechat` 列出被丢弃的非微信链接，`failed` 列出获取失败的链接。
搜狗搜索结果里的 `/link?url=` 跳转链接同样可以直接取全文。

### 模式四：同步到知识库
```python
result = call_tool("search_wechat_articles", {"account_name": "人民日报", "days": 7})
call_tool("export_to_obsidian", {
    "articles": result["articles"],
    "vault_path": "D:/MyVault",
    "folder": "微信公众号/人民日报"
})
```

### 模式五：增量爬取（只采新文章）
```python
# 第一次：记账并返回全部
call_tool("filter_new_articles", {"articles": articles, "record": True})
# 以后每次：先筛出新文章，再决定要不要取全文
call_tool("batch_scrape", {"account_name": "机器之心", "incremental": True})
call_tool("get_scrape_history", {"account": "机器之心", "limit": 20})
```
历史以规范化链接为键记账，带 `chksm`/`from`/`scene` 等跟踪参数的同一篇文章只会记一条。

### 模式六：离线分析与纯文本导出
```python
call_tool("summarize_articles", {"articles": articles, "max_sentences": 3})
call_tool("export_articles_markdown", {"articles": articles, "folder": "本周采集"})
call_tool("download_article_images", {"articles": articles, "output_dir": "D:/微信图片"})
```
摘要走纯 stdlib 的词频抽取式算法，不需要 API Key、不联网；`export_articles_markdown`
只产出 `.md` 与 `.csv`，适合入库、review 和上传（ZIP 是二进制，默认落在临时目录）。

## 🔑 知识库配置

API Key 建议放环境变量，避免随技能包上传：

```bash
export WECHAT_SCRAPER_IMA_API_KEY=your-ima-key
export WECHAT_SCRAPER_DIFY_API_KEY=your-dify-key
```

也可以写在 `config.json` 里（环境变量优先）：

```json
{
  "ima": { "api_key": "your-ima-key" },
  "dify": { "api_key": "your-dify-key", "base_url": "https://api.dify.ai/v1" },
  "obsidian": { "vault_path": "D:/MyObsidianVault" }
}
```

**未配置 API Key 时**，IMA 和 Dify 会自动回退为本地文件导出（Markdown/Text），
不会拼出 `Bearer None` 这类请求，也不会报错。`get_skill_stats` 只回报"是否已配置"
和来源（env/config），任何情况下都不会把密钥本身回传。

## ⚠️ 注意事项

1. **限速与重试**：默认搜狗搜索间隔 3-8 秒、文章获取间隔 2-5 秒；`config.net` 管重试
   （默认 3 次、退避按 2 的幂、遵守服务端 `Retry-After`、单次最多等 60 秒）。
   只对 429/5xx/超时/连接错误重试；404 与签名错误是永久失败，重试它们只会更快撞上验证码
2. **反爬与限流可见**：搜狗返回验证/限流页、或重试后仍持续 403/429 时不再静默显示
   "0 条结果"，工具会回 `blocked: true` + 提示降速或配代理，并重试计数一并回报；
   `config.sogou.raise_on_block` 可改为直接抛错
3. **跳转两跳**：搜索结果里的 `weixin.sogou.com/link?url=` 不是 HTTP 跳转，而是用
   JS 拼出真实链接再 `location.replace`。全文抓取会自动解析拼接结果并二次请求，
   且复用搜索时的会话（搜狗对无 Cookie 的请求直接反回反爬页），因此
   `search_wechat_articles` / `batch_scrape` 默认能拿到正文
4. **内容完整性**：部分历史文章可能无法获取全文（已删除/限制访问），此时保留搜索
   阶段的标题/摘要/公众号，不会被空结果覆盖
5. **代理与超时**：在 `config.json` 的 `sogou.proxy` / `fetch.proxy` 字段设置 HTTP 代理；
   `sogou.timeout`（默认 15 秒）与 `fetch.timeout`（默认 20 秒）控制单次请求上限
6. **缓存**：命中缓存不再重复请求；同时按搜狗跳转链接与解析出的稳定
   `mp.weixin` 链接两个键保存，避免跳转 token 每次变化导致缓存失效；
   `fetch.cache_max_age_days` 可设过期天数，获取失败的页面不会被写入也不会被当命中读出；
   `get_cache_status` 查看条数与体积
7. **增量爬取**：`core/state_store.py` 记录历史，`filter_new_articles` / `batch_scrape.incremental`
   据此只处理新文章
8. **产物位置**：ZIP 与图片等二进制默认写入系统临时目录，技能包目录保持纯源码；
   上传用 `python clean.py --zip`（先清理、归档写到包外、再重开归档自检），
   `--check` 只报告不删除。`data/scrape_history.json` 是你的爬取历史，默认不会被删
   （只有 `python clean.py --all` 才连它一起清），也**不会**被打进上传包
9. **自动取全文上限**：`search_wechat_articles` 默认只给前 `config.fetch.max_auto_fetch`
   （20）篇取全文，其余保留标题+摘要并在结果里回 `fetch_capped`；用 `fetch_limit`
   指定上限，`0` 表示不限——单篇要睡 2-5 秒，几十篇会把 stdio 循环堵到客户端超时
10. **导出目录不会越界**：`export_to_obsidian` 的 `folder` 只能是 vault 内的相对子目录，
    含 `..` 或直接给绝对路径会被拒绝并回 `error`，不会把笔记写到 vault 外面
11. **MCP 帧编码**：服务端启动即把 stdin/stdout 锁成 UTF-8。中文 Windows 上默认按 ANSI
    代码页读写管道，文章标题里的 emoji 会让服务端在读帧/写帧时当场崩掉；
    `get_skill_stats` 的 `stdio_encoding` 会回报实际编码，便于排查

## 📦 安装

```bash
cd wechat-article-scraper
pip install -r requirements.txt
python mcp_server.py          # 启动 MCP stdio Server（21 工具）
```

## 🧪 测试

```bash
python run_tests.py           # 337 项
pytest tests/ -v              # 直接跑也可以
```
测试通过 `tests/conftest.py` 把缓存/历史/导出目录重定向到临时目录，产物不落技能包。
唯一例外是直接 `pytest`：pytest 写 `conftest.py` 自己的字节码发生在 conftest 设
`dont_write_bytecode` 之前，于是包内的 `.pyc` 完整性检查会提示运行 `clean.py`；
`run_tests.py` 已经用 `PYTHONDONTWRITEBYTECODE=1` 起子进程，没有这个问题。
`tests/test_mcp_stdio.py` 用真实子进程跑 stdio 协议，`tests/test_v120_hardening.py`
里有一道文档对账闸：SKILL.md 的工具表必须与 `TOOLS` schema 逐条一致。

## 📋 变更记录

- **v1.2.0**（可靠性与边界加固，工具数仍为 21）：
  ① **重试真的接进了请求层**——v1.1 宣传的"自动重试"此前只有一个没人调用的 `retry()`，
  现在 `fetch_with_retry` 只重试 429/5xx/超时/连接错误，按 2 的幂退避、遵守 `Retry-After`，
  接进搜狗搜索与全文抓取的两跳请求；404 与签名错误不再浪费时间。
  重试次数记进 `stats.retries`，搜索结果里回 `retried_requests`、`get_skill_stats` 的
  `network.fetcher_stats` 一并可见；全部尝试都失败的请求同样计数（计数放在 `finally`，
  否则最坏情况反而报 0 次）。
  ② **HTTP 级限流不再伪装成"0 条结果"**：重试后仍是 403/429 会记为 blocked 并回报。
  ③ **搜索后自动取全文有上限**（默认 20 篇，`fetch_limit` 可调），几十篇全取会把
  单线程 stdio 循环堵到客户端超时；超限部分保留标题+摘要并回 `fetch_capped`。
  ④ **MCP 帧通道锁定 UTF-8**：中文 Windows 默认 ANSI 代码页读写管道，标题里的 emoji
  会当场崩掉整个循环；`get_skill_stats` 新增 `stdio_encoding` 与 `network` 段便于排查。
  ⑤ **HTML 实体还原补齐**：`og:title`/`og:description`/`og:url` 等 meta 值统一 unescape，
  规范链接不再带 `&amp;` 导致缓存键与去重口径漂移；JS 变量里的账号名同步还原。
  ⑥ **全文抓取不再跨调用串档**：去重器从进程级单例属性改为每次调用局部，
  第二次批量抓取不会因"标题与上一批相似"而静默丢文章。
  ⑦ 解析器 `<a>` 栈改为逐锚点配对，空 href 锚点不再偷走邻位链接；正文超链接成对正确。
  ⑧ **导出目录越界防护**：Obsidian 的 `folder` 拒绝 `..` 与绝对路径；
  ZIP 的本地 HTML 先把正文转义再做 Markdown 转换，抓到的 `<script>` 不会在浏览器里执行。
  ⑨ **凭证走环境变量**：`WECHAT_SCRAPER_IMA_API_KEY` / `WECHAT_SCRAPER_DIFY_API_KEY` 优先于
  `config.json`，自检只回报是否配置与来源，密钥本身不回显。
  ⑩ 无年份日期（"3月4日"）显式补当年年份，去掉那条在 Python 3.15 会变成错误的
  strptime 弃用告警；`merge_article` 不再把 `False` 当空值丢弃；同标题文章的图片目录按链接区分；
  清理未使用的 `truncate`/`retry`/空目录 `scripts`、`templates` 与冗余 import。
  ⑪ **上传闸门**：`clean.py --zip` 先清理、把归档写到技能包之外、再重开归档自检，
  混进 `.pyc` 或本地爬取历史就删掉归档并非零退出；顺带修掉 `data/cache` 这类带斜杠的
  条目按目录名匹配永不生效的缺陷（此前 `--check` 对着残留缓存也说"干净"）。测试 261→337。
- **v1.1.0**：MCP 工具 8→21（公众号检索、离线HTML解析、链接提取、文件批量、去重原因、
  离线摘要、图片本地化、纯文本导出、缓存/历史管理、环境自检）；新增爬取历史记账支持增量
  采集；URL规范化消除跟踪参数造成的重复条目；结束日期改为整天闭合；搜狗验证页显式报错
  而非"0 结果"；按线上真实页面修正解析（HTML 实体还原、跳转链接 `&amp;` 不再破坏签名、
  公众号名改取 `all-time-y2`、`timeConvert` 脚本不再污染标题）；全文抓取复用搜索会话并
  解析 JS 拼接跳转，两跳后拿到真实正文（实测 3/3 篇、1542/299/1441 字）；缓存按跳转链接
  与稳定链接双键保存；正文 div 边界修正，页尾噪声不再进入正文；图片转为 Markdown 且
  不计入字数；生成 HTML 全面转义；ZIP/图片默认落临时目录，Obsidian 重复导出
  不再堆副本；Dify 无 Key 时不再拼 `Bearer None`；缓存增加 TTL 与失败不缓存；
  修复中文紧跟链接时被一并吞进的提取缺陷；测试 26→261（含真实子进程 stdio 协议测试），
  `clean.py` 只清二进制、不再删爬取历史。
- **v1.0.0**：三大爬取模式 + 四种格式 + 三大知识库 + 去重过滤 + 批量一体化。
