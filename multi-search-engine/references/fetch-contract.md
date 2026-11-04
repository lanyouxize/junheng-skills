# 正文提取契约（`mse.fetch/1`）

> 目的：把「检索拿到一个链接」推进到「拿到一段可直接喂给 LLM 的 Markdown」，
> 并把**抓取的四态结果**（成功 / 无正文 / 被拦截 / 异常）变成**可机械判定**的字段。
> 实现：`scripts/fetch_clean.py`（仅标准库）。

对应方案 **O-4**（正文提取层）+ **F-2**（`fetch-clean` 正文清洗器）—— 二者是同一能力。

---

## 1. 为什么需要契约

只落地「一份 Markdown」会带来三个无法机械处理的问题：

| 问题 | 后果 |
|---|---|
| 抓取失败与「页面确实没内容」混同 | 「站点被 WAF 拦了」伪装成「这篇文章是空的」 |
| 未记 HTTP 码与最终 URL | 重定向/挑战页无从追查 |
| 站点适配器是否实测无从得知 | 未验证的选择器被当成可用能力写进文档 |

契约把三者都变成**可校验字段**。

---

## 2. 顶层结构

```json
{
  "schema": "mse.fetch/1",
  "url": "https://github.com/AMAP-ML/SkillClaw",
  "final_url": "https://raw.githubusercontent.com/AMAP-ML/SkillClaw/HEAD/README.md",
  "adapter": "github",
  "status": "ok",
  "fetched_at": "2026-10-12T23:20:10+08:00",
  "http_status": 200,
  "title": "SkillClaw",
  "markdown": "# SkillClaw …",
  "stats": {"raw_bytes": 24028, "chars": 23931, "lines": 520,
            "dropped_nodes": 0, "truncated": false, "container": null},
  "robots": "unreachable",
  "notes": ["robots.txt 取不到，按通行做法放行（未获站点显式许可）"]
}
```

### 2.1 字段

| 字段 | 必填 | 说明 |
|---|---|---|
| `schema` | ✅ | 固定 `mse.fetch/1` |
| `url` | ✅ | 输入 URL |
| `final_url` | ✅ | 跟随重定向后的实际 URL（GitHub 仓库链接会被改写为 raw 链接） |
| `adapter` | ✅ | `github` / `github-raw` / `csdn` / `generic`（未登记站点一律回落 `generic`） |
| `status` | ✅ | 四态，见 §3 |
| `fetched_at` | ✅ | ISO 8601，含时区 |
| `http_status` | ⬜ | 整数；网络异常时为 `null` |
| `title` | ⬜ | HTML `<title>`；raw-markdown 适配器取首个 `# ` 标题 |
| `markdown` | ⬜ | 清洗后的正文；`status=ok` 时必须非空 |
| `stats` | ✅ | `raw_bytes` / `chars` / `lines` / `dropped_nodes` / `truncated` / `container` |
| `robots` | ✅ | `allowed` / `disallowed` / `unreachable` / `not-checked` |
| `notes` | ✅ | 人类可读说明数组（降级、截断、未实测提示都在这里出声） |

### 2.2 `status` 四态（关键：区分「被拦」与「没有」）

| 值 | 含义 | 触发 |
|---|---|---|
| `ok` | 拿到非空正文 | 2xx/3xx 且提取到内容 |
| `empty` | 抓取成功但**未提取到正文** | 2xx 但正文为空（多为纯 JS 渲染页） |
| `blocked` | 被拦截 | HTTP 401/403/407/429/451/521–524；robots 禁止 |
| `error` | 网络或服务端异常 | 超时、DNS 失败、其他 4xx/5xx、URL 非法 |

> **为什么必须分开**：把 `blocked` 并入 `empty`，会让「站点反爬升级」伪装成「文章没内容」，
> 直接污染后续的健康度统计。**降级必须有声音。**

---

## 3. 清洗规则

| 类别 | 处理 |
|---|---|
| 连子树丢弃 | `script` `style` `noscript` `svg` `iframe` `form` `input` `button` `template` `nav` `footer` `aside` `object` `canvas` `audio` `video` … |
| 主内容区探测 | 未登记站点按 `<article>`/`<main>` + `id`/`class` 提示词（`content`/`article`/`post`/`markdown`/…）+ 文本量打分，取最高分容器；命中 `nav`/`sidebar`/`footer`/`comment`/`advert`/… 的容器一律排除 |
| 站点选择器 | 登记站点优先用 `ADAPTERS[*].selectors`，命中不到自动回落通用探测 |
| 结构转换 | `h1–h6`→`#`，`p`→段落，`ul/ol`→`- `/`1. `（含嵌套缩进），`pre`→围栏 ```，`blockquote`→`> `，`table`→管道表，`a`→`[文本](url)`，`img`→`![alt](src)` |
| 装饰剔除 | 永久链接锚点（`¶`/`#`，含 `class="headerlink"` 一类）**不进正文** |
| 实体与空白 | `&amp;`→`&`、`&nbsp;`→空格；水平空白压缩；连续 3+ 换行压成 2 |

---

## 4. 站点适配器表（`fetch_clean.py` 内 `ADAPTERS`，**数据不是代码**）

| 适配器 | 覆盖 | 类型 | `verified` |
|---|---|---|---|
| `github` | `github.com` | raw-markdown（仓库 → `raw.githubusercontent.com/<o>/<r>/HEAD/README.md`；`/blob/<ref>/<path>` → raw 对应路径） | ✅ 实测 |
| `github-raw` | `raw.githubusercontent.com` | raw-markdown（直接透传） | ✅ 实测 |
| `csdn` | `blog.csdn.net` 等 | html（选择器 `#article_content` / `.markdown_views` / `#content_views`） | ❌ **未实测** |

> **诚实边界**：`blog.csdn.net` 文章详情页在本环境稳定返回 **HTTP 521**（JS 挑战页，
> 响应体 998 B），即便改用浏览器 UA 亦如此；首页可 200。因此 CSDN 的选择器**未经真机验证**，
> 命中不到会自动回落通用主内容区探测。适配器表里的 `verified: false` 就是这个事实的机器可读记录，
> 抓取命中该适配器时会在 `notes` 里再次出声。
>
> **凡适配器表新增条目，未实测通过的一律标 `verified: false` 并写明证据。**

---

## 5. 抓取合规

- **默认遵守 robots.txt**（技能 `SKILL.md`「Crawling Ethics」要求）：取 `User-agent: *` 与本 UA 两组规则，
  最长匹配优先，`Allow` 长于 `Disallow` 则放行。
- robots **取不到时按通行做法放行，但必须在 `notes` 出声**，绝不静默。
- **默认诚实 UA** `mse-fetch/1.0`，不伪装浏览器硬闯 WAF；需要时由调用方显式 `--ua browser`。
- 需 `--ignore-robots` 才能越过 `disallowed`（默认会返回 `status=blocked`）。

---

## 6. 用法

```bash
python scripts/fetch_clean.py <url>                  # 输出 mse.fetch/1 JSON
python scripts/fetch_clean.py <url> --md             # 只输出 Markdown
python scripts/fetch_clean.py <url> --md -o out.md   # 写文件
python scripts/fetch_clean.py <url> --max-chars 4000 # 按字符截断
python scripts/fetch_clean.py <url> --ignore-robots  # 越过 robots 的 disallowed
python scripts/fetch_clean.py <url> --ua browser     # 换浏览器 UA（默认诚实 UA）
python scripts/fetch_clean.py --selftest             # 离线自检（内嵌 HTML 夹具，不联网）
python scripts/fetch_clean.py --selftest-live        # 联网自检（真实站点）
```

### 6.1 退出码（三态，禁止把「没能验证」冒充「已损坏」）

| 码 | 含义 |
|---|---|
| `0` | 工具执行成功 —— **含 `status=empty/blocked`，那是页面状态，不是工具失败** |
| `1` | 用法错误或内部缺陷（未知选项、写文件失败） |
| `3` | **无法验证**：网络异常导致根本没拿到响应 |

---

## 7. 最小合法示例（被拦截时）

```json
{
  "schema": "mse.fetch/1",
  "url": "https://blog.csdn.net/a/b/article/details/1",
  "final_url": "https://blog.csdn.net/a/b/article/details/1",
  "adapter": "csdn",
  "status": "blocked",
  "fetched_at": "2026-10-12T23:20:10+08:00",
  "http_status": 521,
  "title": "",
  "markdown": "",
  "stats": {"raw_bytes": 998, "chars": 0, "lines": 0,
            "dropped_nodes": 0, "truncated": false, "container": null},
  "robots": "allowed",
  "notes": ["HTTP 521：被拦截（鉴权/限流/挑战页）"]
}
```
