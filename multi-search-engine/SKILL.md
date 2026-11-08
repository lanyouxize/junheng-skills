---
name: multi-search-engine
description: 多引擎聚合检索：覆盖 8 个国内与 9 个国际引擎，支持高级检索语法、时间过滤、站内检索与知识问答。当用户要联网搜索、跨平台交叉验证或找最新资料时用。
description_zh: 集成 17 个搜索引擎（8 国内 + 9 国际），无需 API
description_en: Multi search engine integration with 17 engines (8 CN + 9 Global). Supports adva...
version: 2.4.1
display_name: multi-search-engine
display_name_en: multi-search-engine
license: Proprietary
compatibility: Python 3.9+.
---

# Multi Search Engine

Integration of 17 search engines for web crawling without API keys.

## Workflow

1. **Preparation**: AI Agent initializes an empty in-memory cookie store. Cookies are only acquired dynamically during search operations when access is denied

2. **Language Evaluation**: Detect the language attribute of the search query. If the query is in Chinese, use Domestic search engines (Baidu, Bing CN, Bing INT, 360, Sogou, WeChat, Toutiao, Shenma). If the query is non-Chinese, use International search engines (Google, Google HK, DuckDuckGo, Yahoo, Startpage, Brave, Ecosia, Qwant, WolframAlpha). Select engines based on query relevance and availability.

3. **Controlled Search**: Use web_fetch to execute search requests with rate limiting:
   - Add 1-2 second delay between requests to respect server load
   - Batch requests in groups of 3-4 engines with sequential execution between batches
   - Include standard browser headers to identify as legitimate user agent
   - If access is denied (403/429), fetch engine homepage to obtain fresh session cookies

4. **Cookie Management**: 
   - Cookies are stored ONLY in memory during runtime
   - Cookies are acquired on-demand when search requests fail
   - No cookies are read from or written to config.json or any file
   - Cookies are cleared after search session completes
   - Only session cookies from search engine domains are captured

5. **Retry Mechanism**: If a search fails due to cookie/session issues, retry once with freshly acquired cookies after a 2-second delay

6. **Result Aggregation**: Consolidate successful results from search engines, organize and summarize them to output a core search report. Emit the aggregated results in the **`mse.result/1` structure** (see `references/result-contract.md`) so that downstream consumers can validate them mechanically — e.g. to detect "only a single engine returned this item". Validate a batch with `python scripts/validate_results.py <results.json>`. Then run `python scripts/search_report.py <results.json>` to produce the **`mse.report/1` cross-verification report** (see `references/report-contract.md`): single-engine hits are mechanically flagged as pending review, and a shortage of usable engines is reported as *unable to cross-check* — never as "this claim is dubious". Finally register the batch with `python scripts/engine_health.py <results.json>` so that "which engine is down today" becomes data (see `references/health-contract.md`); `blocked` and `empty` are counted separately — an engine being intercepted must never masquerade as "no results".

## Search Engines

### Domestic (8)
- **Baidu**: `https://www.baidu.com/s?wd={keyword}`
- **Bing CN**: `https://cn.bing.com/search?q={keyword}&ensearch=0`
- **Bing INT**: `https://cn.bing.com/search?q={keyword}&ensearch=1`
- **360**: `https://www.so.com/s?q={keyword}`
- **Sogou**: `https://sogou.com/web?query={keyword}`
- **WeChat**: `https://wx.sogou.com/weixin?type=2&query={keyword}`
- **Toutiao**: `https://so.toutiao.com/search?keyword={keyword}`
- **Shenma**: `https://m.sm.cn/s?q={keyword}`

### International (9)
- **Google**: `https://www.google.com/search?q={keyword}`
- **Google HK**: `https://www.google.com.hk/search?q={keyword}`
- **DuckDuckGo**: `https://duckduckgo.com/html/?q={keyword}`
- **Yahoo**: `https://search.yahoo.com/search?p={keyword}`
- **Startpage**: `https://www.startpage.com/sp/search?query={keyword}`
- **Brave**: `https://search.brave.com/search?q={keyword}`
- **Ecosia**: `https://www.ecosia.org/search?q={keyword}`
- **Qwant**: `https://www.qwant.com/?q={keyword}`
- **WolframAlpha**: `https://www.wolframalpha.com/input?i={keyword}`

## Quick Examples

```javascript
// Basic search
web_fetch({"url": "https://www.google.com/search?q=python+tutorial"})

// Site-specific
web_fetch({"url": "https://www.google.com/search?q=site:github.com+react"})

// File type
web_fetch({"url": "https://www.google.com/search?q=machine+learning+filetype:pdf"})

// Time filter (past week)
web_fetch({"url": "https://www.google.com/search?q=ai+news&tbs=qdr:w"})

// Privacy search
web_fetch({"url": "https://duckduckgo.com/html/?q=privacy+tools"})

// DuckDuckGo Bangs
web_fetch({"url": "https://duckduckgo.com/html/?q=!gh+tensorflow"})

// Knowledge calculation
web_fetch({"url": "https://www.wolframalpha.com/input?i=100+USD+to+CNY"})
```

## Advanced Operators

| Operator | Example | Description |
|----------|---------|-------------|
| `site:` | `site:github.com python` | Search within site |
| `filetype:` | `filetype:pdf report` | Specific file type |
| `""` | `"machine learning"` | Exact match |
| `-` | `python -snake` | Exclude term |
| `OR` | `cat OR dog` | Either term |

## Time Filters

| Parameter | Description |
|-----------|-------------|
| `tbs=qdr:h` | Past hour |
| `tbs=qdr:d` | Past day |
| `tbs=qdr:w` | Past week |
| `tbs=qdr:m` | Past month |
| `tbs=qdr:y` | Past year |

## Privacy Engines

- **DuckDuckGo**: No tracking
- **Startpage**: Google results + privacy
- **Brave**: Independent index
- **Qwant**: EU GDPR compliant

## Bangs Shortcuts (DuckDuckGo)

| Bang | Destination |
|------|-------------|
| `!g` | Google |
| `!gh` | GitHub |
| `!so` | Stack Overflow |
| `!w` | Wikipedia |
| `!yt` | YouTube |

## WolframAlpha Queries

- Math: `integrate x^2 dx`
- Conversion: `100 USD to CNY`
- Stocks: `AAPL stock`
- Weather: `weather in Beijing`

## Documentation

- `references/advanced-search.md` - Domestic search guide
- `references/international-search.md` - International search guide
- `references/result-contract.md` - **`mse.result/1` result structure contract** (validator rules V1–V11)
- `references/report-contract.md` - **`mse.report/1` cross-verification report contract** (three-verdict model)
- `references/fetch-contract.md` - **`mse.fetch/1` full-text extraction contract** (URL → LLM-ready Markdown; 4-state `status`, robots handling, adapter table)
- `references/health-contract.md` - **`mse.health/1` engine health ledger + `mse.health.summary/1` availability board** (4-state statuses, 4 verdicts, dedupe & commit rules)
- `scripts/validate_results.py` - Result contract validator (`--selftest` / `--json` / `--summary`)
- `scripts/search_report.py` - **Cross-verification report**: consumes `mse.result/1` batches → `mse.report/1`; flags single-engine hits as pending review (`--min-engines` / `--title-threshold` / `--md -o` / `--json` / `--selftest`)
- `scripts/fetch_clean.py` - **Full-text extractor**: URL → clean Markdown (`--md` / `-o` / `--max-chars` / `--ignore-robots` / `--ua browser` / `--selftest` / `--selftest-live`)
- `scripts/engine_health.py` - **Engine health ledger & availability board**: registers every `mse.result/1` batch into `engine-health.jsonl` and ranks engines by usable rate (`--summary` / `--window N` / `--no-append` / `--prune-older-than N [--yes]` / `--selftest`)
- `scripts/check_engine_consistency.py` - Multi-source consistency check (engine roster + version)
- `CHANGELOG.md` - Version history (English)
- `CHANNELLOG.md` - Version history (Chinese)

## License

MIT

## Security & Privacy Notice

### Cookie Handling
- **Purpose**: Cookies are used ONLY to maintain search session state when access is denied (403/429 errors)
- **Storage**: Cookies are kept STRICTLY in memory during runtime - NEVER persisted to disk or config files
- **Acquisition**: Cookies are acquired on-demand from search engine homepages only when search requests fail
- **Scope**: Only session cookies from the specific search engine domain are captured
- **Lifecycle**: Cookies are cleared immediately after the search session completes
- **No Pre-configuration**: No cookies are loaded from config.json or any external file at startup
- **No API Keys**: This tool uses standard web search URLs, no authentication required

### Crawling Ethics
- **Rate Limiting**: Implement reasonable delays between requests (recommend 1-2 seconds)
- **Respect robots.txt**: Honor search engine crawling policies
- **Terms of Service**: Users are responsible for complying with search engine ToS
- **Purpose**: Designed for legitimate search aggregation, not mass data scraping

### Data Handling
- **No Personal Data**: Tool does not collect or transmit user personal information
- **Local Execution**: All operations run locally, no external data transmission
- **Session Isolation**: Cookies are session-specific and cleared after use
