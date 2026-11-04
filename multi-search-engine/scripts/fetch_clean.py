# -*- coding: utf-8 -*-
"""mse.fetch/1 正文提取器（fetch-clean）

把「检索拿到一个链接」推进到「拿到一段可直接喂给 LLM 的 Markdown」。
对应方案 **O-4**（正文提取层）+ **F-2**（`fetch-clean` 正文清洗器）—— 二者是同一能力。

契约定义见 `references/fetch-contract.md`；校验器 / 消费者按 `schema: "mse.fetch/1"` 识别。

设计取舍：
  - **只用标准库**（与技能内其它脚本一致，拒绝第三方依赖）：HTML 解析走
    `html.parser.HTMLParser` 自建最小 DOM，不引入 bs4/lxml；Markdown 转换自写。
  - **默认诚实 UA**：`mse-fetch/1.0`。不伪装浏览器去硬闯 WAF；需要时由调用方显式
    `--ua browser`（CSDN 详情页在本环境即便用浏览器 UA 也返回 521，见下方 `ADAPTERS` 备注）。
  - **默认遵守 robots.txt**（技能 `SKILL.md`「Crawling Ethics」明确要求）。
    robots 取不到时按通行做法**放行**，但必须在 `notes` 里出声，绝不静默。

退出码（三态，禁止把「没能验证」冒充「已损坏」）：
  0 = 成功（含 `status=empty/blocked`，那是**页面的状态**，不是本工具的失败）
  1 = 用法或内部缺陷（如 URL 非法、写文件失败）
  3 = **无法验证**（网络不可达、超时、响应体超过上限且不可解析）

用法：
  python fetch_clean.py <url>                 # 输出 mse.fetch/1 JSON
  python fetch_clean.py <url> --md            # 只输出清洗后的 Markdown
  python fetch_clean.py <url> --md -o out.md  # 写文件
  python fetch_clean.py <url> --max-chars 4000
  python fetch_clean.py <url> --ignore-robots
  python fetch_clean.py --selftest            # 离线自检（内嵌 HTML 夹具，不联网）
  python fetch_clean.py --selftest-live       # 联网自检（真实站点，可能受网络影响）
"""
from __future__ import annotations

import gzip
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import zlib
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

try:  # Windows 控制台默认 GBK，会炸中文
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent

TZ = timezone(timedelta(hours=8))
SCHEMA = "mse.fetch/1"
STATUSES = ("ok", "empty", "blocked", "error")

EXIT_OK = 0
EXIT_DEFECT = 1
EXIT_UNVERIFIABLE = 3

DEFAULT_TIMEOUT = 20
DEFAULT_MAX_BYTES = 4 * 1024 * 1024   # 4 MB 响应体上限
HONEST_UA = "mse-fetch/1.0 (+multi-search-engine skill; stdlib-only fetcher)"
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# --------------------------------------------------------------------------- #
# 站点适配器表（**数据，不是代码**：新增站点只改这里）
# --------------------------------------------------------------------------- #
# selector 命中顺序即优先级；命中不到则回落到通用「主内容区探测」。
# verified 字段必须诚实：未在本环境实测通过的一律 False，并在 note 写明证据。
ADAPTERS = {
    "github": {
        "host_suffix": ("github.com",),
        "kind": "raw-markdown",     # 直接取 README 原文，无需 HTML→MD
        "verified": True,
        "note": "实测通过：raw.githubusercontent.com/<owner>/<repo>/HEAD/README.md 返 200 / 24,028 B。",
    },
    "github-raw": {
        "host_suffix": ("raw.githubusercontent.com",),
        "kind": "raw-markdown",
        "verified": True,
        "note": "实测通过：直接透传 Markdown 原文。",
    },
    "csdn": {
        "host_suffix": ("blog.csdn.net", "csdn.net"),
        "kind": "html",
        "selectors": ("#article_content", ".markdown_views", "#content_views", ".article_content"),
        "verified": False,
        "note": (
            "**未实测**：本环境对 blog.csdn.net 文章详情页请求稳定返回 HTTP 521"
            "（JS 挑战页，响应体仅 998 B），即便改用浏览器 UA 亦如此；首页可 200。"
            "选择器取自公开 DOM 结构，**未经真机验证**——命中不到会自动回落通用主内容区探测。"
        ),
    },
}

# 通用主内容区探测的 id/class 提示词（权重越高越优先）
CONTENT_HINTS = (
    ("markdown", 30), ("content", 30), ("article", 25), ("post", 20),
    ("entry", 15), ("main", 20), ("story", 12), ("detail", 10), ("body", 8),
)
# 明确排除的容器提示词（导航/侧栏/广告）
NOISE_HINTS = ("nav", "menu", "sidebar", "aside", "footer", "header", "comment",
               "advert", "ads", "推荐", "related", "breadcrumb", "pagination")

# 连子树一起丢弃的标签
DROP_TAGS = {
    "script", "style", "noscript", "svg", "iframe", "frame", "frameset",
    "form", "input", "button", "select", "textarea", "option",
    "template", "link", "meta", "base", "head", "object", "embed", "applet",
    "canvas", "audio", "video", "source", "track", "map",
    "nav", "footer", "aside", "ins", "del", "iframe",
}
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input",
             "link", "meta", "param", "source", "track", "wbr"}
HEADING_TAGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
TEXT_NODE = "#text"
# 永久链接锚点字形（标题旁的 ¶ / # 之类），属页面装饰，须剔除
ANCHOR_GLYPHS = {"¶", "§", "#", "^", "🔗"}
# 行内标签：只做行内渲染，不产生独立 block
INLINE_ONLY_TAGS = {
    "a", "abbr", "b", "bdi", "bdo", "cite", "code", "data", "dfn", "em", "i",
    "kbd", "label", "mark", "q", "s", "samp", "small", "span", "strong", "sub",
    "sup", "time", "u", "var", "wbr", "font", "tt", "big", "nobr",
}


# --------------------------------------------------------------------------- #
# 最小 DOM
# --------------------------------------------------------------------------- #

class Node:
    __slots__ = ("tag", "attrs", "children", "text")

    def __init__(self, tag: str, attrs: dict | None = None, text: str = ""):
        self.tag = tag
        self.attrs = attrs or {}
        self.children: list[Node] = []
        self.text = text

    def ident(self) -> str:
        return (self.attrs.get("id", "") + " " + self.attrs.get("class", "")).lower()


class TreeBuilder(HTMLParser):
    """容错 DOM 构建器：容忍未闭合标签、错序闭合、孤立结束标签。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root")
        self.stack: list[Node] = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(Node(tag, dict(attrs)))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return
        # 无匹配（孤立闭合）：忽略，不破坏栈

    def handle_data(self, data):
        if data:
            self.stack[-1].children.append(Node(TEXT_NODE, text=data))


def parse_html(html: str) -> Node:
    b = TreeBuilder()
    b.feed(html)
    b.close()
    return b.root


def walk(node: Node):
    yield node
    for c in node.children:
        yield from walk(c)


def text_of(node: Node) -> str:
    if node.tag == TEXT_NODE:
        return node.text
    return "".join(text_of(c) for c in node.children)


def prune(node: Node, counter: list[int]) -> None:
    """连子树一起丢弃噪声标签（去脚本/样式/导航/广告/表单）。"""
    keep: list[Node] = []
    for c in node.children:
        if c.tag in DROP_TAGS:
            counter[0] += 1
            continue
        prune(c, counter)
        keep.append(c)
    node.children = keep


# --------------------------------------------------------------------------- #
# HTML → Markdown
# --------------------------------------------------------------------------- #

def _squeeze(s: str) -> str:
    """压缩水平空白；`\\xa0`（&nbsp;）归一为普通空格。"""
    return re.sub(r"[ \t\xa0]+", " ", s).strip()


def inline(node: Node) -> str:
    """行内渲染：链接/强调/代码/图片保留 Markdown 标记，其余透传文本。"""
    if node.tag == TEXT_NODE:
        return node.text
    if node.tag in DROP_TAGS:
        return ""

    inner = "".join(inline(c) for c in node.children)
    tag = node.tag

    if tag == "a":
        href = node.attrs.get("href", "") or ""
        if not inner.strip():
            return inner
        # 永久链接锚点（`¶` / `#` 之类）是页面装饰，不是正文 —— 必须去掉，
        # 否则每个标题后面都会拖一个 ¶（docs.python.org 实测命中）。
        cls = (node.attrs.get("class", "") or "").lower()
        if any(k in cls for k in ("headerlink", "anchor", "permalink", "self-link")):
            return ""
        if inner.strip() in ANCHOR_GLYPHS:
            return ""
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            return inner
        return f"[{inner}]({href})"
    if tag == "img":
        src = node.attrs.get("src", "")
        alt = node.attrs.get("alt", "") or ""
        return f"![{alt}]({src})" if src else alt
    if tag in ("strong", "b"):
        return f"**{inner}**" if inner.strip() else ""
    if tag in ("em", "i"):
        return f"*{inner}*" if inner.strip() else ""
    if tag == "code":
        raw = text_of(node)
        return f"`{raw.strip()}`" if raw.strip() else ""
    if tag == "br":
        return " "
    return inner


def _render_rows(table: Node) -> list[str]:
    """表格 → 管道表（含表头分隔行）。"""
    rows: list[Node] = []
    for tr in walk(table):
        if tr.tag == "tr":
            rows.append(tr)
    out: list[str] = []
    for i, tr in enumerate(rows):
        cells = []
        for c in tr.children:
            if c.tag in ("td", "th"):
                cells.append(_squeeze(inline(c)).replace("|", "\\|"))
        if not any(cells):
            continue
        out.append("| " + " | ".join(cells) + " |")
        if i == 0:
            out.append("| " + " | ".join(["---"] * len(cells)) + " |")
    return out


def emit(node: Node, out: list[str]) -> None:
    """块级渲染：把子树转成若干 block（调用方用空行连接）。"""
    tag = node.tag
    if tag in DROP_TAGS:
        return

    if tag in HEADING_TAGS:
        t = _squeeze(inline(node))
        if t:
            out.append("#" * HEADING_TAGS[tag] + " " + t)
        return

    if tag == "p":
        t = _squeeze(inline(node))
        if t:
            out.append(t)
        return

    if tag in ("ul", "ol"):
        items = [c for c in node.children if c.tag == "li" or c.tag in ("ul", "ol")]
        lines: list[str] = []
        idx = 0
        for li in items:
            if li.tag != "li":                      # 嵌套列表：递归后整体缩进
                sub: list[str] = []
                emit(li, sub)
                lines += ["  " + l for l in sub]
                continue
            idx += 1
            t = _squeeze(inline(li))
            if t:
                lines.append((f"{idx}. " if tag == "ol" else "- ") + t)
        if lines:
            out.append("\n".join(lines))
        return

    if tag == "blockquote":
        sub = []
        for c in node.children:
            emit(c, sub)
        if sub:
            out.append("\n".join("> " + l for b in sub for l in b.split("\n")))
        return

    if tag == "pre":
        raw = text_of(node).strip("\n")
        if raw.strip():
            out.append("```\n" + raw + "\n```")
        return

    if tag == "table":
        rows = _render_rows(node)
        if rows:
            out.append("\n".join(rows))
        return

    if tag == "hr":
        out.append("---")
        return

    if tag == "br":
        out.append("")
        return

    if tag == "img":
        t = inline(node)
        if t:
            out.append(t)
        return

    if tag in INLINE_ONLY_TAGS:
        # 行内标签（a / span / strong / code / …）**绝不能**把它的文本子节点
        # 拆成独立 block —— 否则 `<a class="headerlink">¶</a>` 这类装饰锚点
        # 会变成正文里孤零零的一行 ¶（docs.python.org 实测残留 95 处）。
        t = _squeeze(inline(node))
        if t:
            out.append(t)
        return

    if tag == TEXT_NODE:
        t = _squeeze(node.text)
        if t:
            out.append(t)
        return

    # 其余容器标签（div/section/article/main/span/...）：先递归，
    # 若子节点没产出任何 block 但自身有文本，则把文本作为一个 block，避免整段丢失。
    before = len(out)
    for c in node.children:
        emit(c, out)
    if len(out) == before:
        t = _squeeze(inline(node))
        if t:
            out.append(t)


def pick_container(root: Node) -> Node:
    """主内容区探测：按标签语义 + id/class 提示词 + 文本量打分，取最高分容器。"""
    best, best_score = root, 1
    for n in walk(root):
        if n.tag not in ("article", "main", "div", "section"):
            continue
        ident = n.ident()
        if any(h in ident for h in NOISE_HINTS):
            continue
        score = 0
        if n.tag == "article":
            score += 60
        elif n.tag == "main":
            score += 50
        for kw, w in CONTENT_HINTS:
            if kw in ident:
                score += w
                break
        score += min(len(text_of(n)) // 200, 60)
        if score > best_score:
            best, best_score = n, score
    return best


def html_to_markdown(html: str, selectors: tuple[str, ...] = ()) -> tuple[str, dict]:
    """HTML → Markdown，返回 `(markdown, stats)`。"""
    root = parse_html(html)

    # 标题：在丢弃 head 之前取
    title = ""
    for n in walk(root):
        if n.tag == "title":
            title = _squeeze(text_of(n))
            break

    counter = [0]
    prune(root, counter)

    container = root
    selector_hit = None
    for sel in selectors:                      # 站点指定选择器优先
        target = sel.lstrip("#.")
        by_id = sel.startswith("#")
        hit = None
        for n in walk(root):
            if by_id and n.attrs.get("id") == target:
                hit = n
                break
            if not by_id and target in (n.attrs.get("class", "") or "").split():
                hit = n
                break
        if hit is not None:
            container, selector_hit = hit, sel
            break
    if container is root:
        container = pick_container(root)

    out: list[str] = []
    emit(container, out)
    md = "\n\n".join(b for b in out if b.strip())
    md = re.sub(r"[ \t]+\n", "\n", md)
    md = re.sub(r"\n{3,}", "\n\n", md).strip()

    return md, {
        "dropped_nodes": counter[0],
        "container": container.tag,
        "selector_hit": selector_hit,
        "title": title,
    }


# --------------------------------------------------------------------------- #
# 抓取
# --------------------------------------------------------------------------- #

def github_to_raw(url: str) -> str | None:
    """GitHub 仓库 / blob 链接 → raw 原文链接。非 GitHub 返回 None。"""
    u = urllib.parse.urlparse(url)
    host = u.netloc.lower()
    if host.endswith("raw.githubusercontent.com"):
        return url
    if not host.endswith("github.com"):
        return None
    parts = [p for p in u.path.split("/") if p]
    if len(parts) < 2:
        return None
    owner, repo = parts[0], parts[1].removesuffix(".git")
    if len(parts) >= 4 and parts[2] == "blob":        # /blob/<ref>/<path...>
        ref = parts[3]
        rest = "/".join(parts[4:]) or "README.md"
        return f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{rest}"
    return f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD/README.md"


def detect_adapter(url: str) -> tuple[str, dict]:
    host = urllib.parse.urlparse(url).netloc.lower()
    for name, cfg in ADAPTERS.items():
        for suffix in cfg["host_suffix"]:
            if host == suffix or host.endswith("." + suffix):
                return name, cfg
    return "generic", {"kind": "html", "verified": True, "note": "通用 HTTP→Markdown。"}


def decode_body(raw: bytes, content_type: str) -> str:
    enc = (urllib.parse.parse_qs(
        (urllib.parse.urlparse("x://?" + content_type.replace(";", "&", 1)).query)
    ).get("charset") or [None])[0]
    if not enc:
        m = re.search(rb'charset=["\']?\s*([\w-]+)', raw[:4096], re.I)
        enc = m.group(1).decode("ascii", "replace") if m else None
    for cand in (enc, "utf-8", "gb18030", "latin-1"):
        if not cand:
            continue
        try:
            return raw.decode(cand)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


class Robots:
    """极简 robots.txt 判定（User-agent: * 与本机 UA token 两组）。"""

    def __init__(self, ua: str, timeout: int):
        self.ua = ua
        self.timeout = timeout
        self.cache: dict[str, str] = {}

    def check(self, url: str) -> str:
        u = urllib.parse.urlparse(url)
        origin = f"{u.scheme}://{u.netloc}"
        if origin in self.cache:
            return self.cache[origin]
        verdict = "unreachable"
        try:
            req = urllib.request.Request(
                origin + "/robots.txt",
                headers={"User-Agent": self.ua, "Accept": "text/plain,*/*",
                         "Accept-Encoding": "gzip, deflate"},
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                body = _decompress(r.read(), r.headers.get("Content-Encoding", "")) \
                    .decode("utf-8", errors="replace")
            verdict = self._rule(body, u.path or "/")
        except Exception:
            verdict = "unreachable"      # 取不到 robots 按通行做法放行，但会出声
        self.cache[origin] = verdict
        return verdict

    def _rule(self, body: str, path: str) -> str:
        groups: dict[str, list[tuple[str, str]]] = {}
        agents: list[str] = []
        for line in body.splitlines():
            line = line.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            k, v = line.split(":", 1)
            k, v = k.strip().lower(), v.strip()
            if k == "user-agent":
                agents = [v.lower()]
                groups.setdefault(agents[0], [])
            elif k in ("disallow", "allow") and agents:
                for a in agents:
                    groups[a].append((k, v))
        rules = groups.get("*", []) + groups.get(self.ua.split("/")[0].lower(), [])
        best_allow, best_disallow = -1, -1
        for kind, p in rules:
            if not p:
                continue
            if path.startswith(p):
                if kind == "allow":
                    best_allow = max(best_allow, len(p))
                else:
                    best_disallow = max(best_disallow, len(p))
        if best_disallow >= 0 and best_disallow > best_allow:
            return "disallowed"
        return "allowed"


def _decompress(raw: bytes, encoding: str) -> bytes:
    enc = (encoding or "").lower()
    if "gzip" in enc:
        return gzip.decompress(raw)
    if "deflate" in enc:
        try:
            return zlib.decompress(raw)
        except zlib.error:
            return zlib.decompress(raw, -zlib.MAX_WBITS)
    return raw


def http_get(url: str, ua: str, timeout: int, max_bytes: int, retries: int):
    """GET，返回 `(status, headers, body)` 或抛异常。有限重试 + 体量上限。"""
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": ua,
                "Accept": "text/html,application/xhtml+xml,text/markdown,text/plain;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate",   # 不含 br：标准库无 brotli
            })
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read(max_bytes + 1)
                truncated = len(raw) > max_bytes
                return r.status, dict(r.headers), _decompress(
                    raw[:max_bytes], r.headers.get("Content-Encoding", "")
                ), r.geturl(), truncated
        except urllib.error.HTTPError as e:
            body = b""
            try:
                body = e.read(4096)
            except Exception:
                pass
            return e.code, dict(e.headers or {}), body, url, False
        except Exception as e:  # noqa: BLE001
            last = e
            if attempt >= retries:
                break
    raise last if last else RuntimeError("unreachable")


def classify_http(code: int) -> str:
    """HTTP 码 → 契约四态之一（仅凭状态码可判定的部分）。"""
    if code in (401, 403, 407, 429, 451):
        return "blocked"
    if code in (521, 522, 523, 524):      # 通常是 WAF / 回源失败的挑战页
        return "blocked"
    if 200 <= code < 400:
        return "ok"
    return "error"


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #

def fetch(url: str, *, ua: str = HONEST_UA, timeout: int = DEFAULT_TIMEOUT,
          max_bytes: int = DEFAULT_MAX_BYTES, retries: int = 1,
          respect_robots: bool = True, max_chars: int = 0,
          robots: Robots | None = None) -> dict:
    """抓取并清洗一个 URL，返回 `mse.fetch/1` 记录。"""
    now = datetime.now(TZ)
    rec: dict = {
        "schema": SCHEMA,
        "url": url,
        "final_url": url,
        "adapter": "generic",
        "status": "error",
        "fetched_at": now.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "http_status": None,
        "title": "",
        "markdown": "",
        "stats": {"raw_bytes": 0, "chars": 0, "lines": 0,
                  "dropped_nodes": 0, "truncated": False, "container": None},
        "robots": "not-checked",
        "notes": [],
    }

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        rec["status"] = "error"
        rec["notes"].append("URL 非法：scheme 必须为 http/https 且须含主机名")
        return rec

    if respect_robots:
        robots = robots or Robots(ua, timeout)
        verdict = robots.check(url)
        rec["robots"] = verdict
        if verdict == "disallowed":
            rec["status"] = "blocked"
            rec["notes"].append("robots.txt 禁止抓取该路径；如需继续请显式 --ignore-robots")
            return rec
        if verdict == "unreachable":
            rec["notes"].append("robots.txt 取不到，按通行做法放行（未获站点显式许可）")

    name, cfg = detect_adapter(url)
    rec["adapter"] = name
    target = url
    if cfg.get("kind") == "raw-markdown":
        mapped = github_to_raw(url)
        if mapped:
            target = mapped

    try:
        code, headers, body, final_url, truncated = http_get(
            target, ua, timeout, max_bytes, retries)
    except Exception as e:  # noqa: BLE001
        rec["status"] = "error"
        rec["notes"].append(f"网络异常：{type(e).__name__}: {e}")
        return rec

    rec["http_status"] = code
    rec["final_url"] = final_url
    rec["stats"]["raw_bytes"] = len(body)
    rec["stats"]["truncated"] = truncated
    if truncated:
        rec["notes"].append(f"响应体超过上限 {max_bytes} B，已截断（正文可能不完整）")

    rec["status"] = classify_http(code)
    if rec["status"] != "ok":
        rec["notes"].append(f"HTTP {code}：{STATUSES_NOTE.get(rec['status'], '')}".rstrip("："))
        return rec

    text = decode_body(body, headers.get("Content-Type", ""))

    if cfg.get("kind") == "raw-markdown":
        md = re.sub(r"\n{3,}", "\n\n", text).strip()
        title = ""
        for line in md.splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                break
        rec["markdown"] = md
        rec["title"] = title
    else:
        md, extra = html_to_markdown(text, tuple(cfg.get("selectors", ())))
        rec["markdown"] = md
        rec["title"] = extra["title"]
        rec["stats"]["dropped_nodes"] = extra["dropped_nodes"]
        rec["stats"]["container"] = extra["container"]
        if not cfg.get("verified", True):
            rec["notes"].append(
                f"站点适配器 {name} **未在本环境实测**：{cfg.get('note', '')}")

    if max_chars and len(rec["markdown"]) > max_chars:
        rec["markdown"] = rec["markdown"][:max_chars]
        rec["notes"].append(f"正文已按 --max-chars={max_chars} 截断")

    rec["stats"]["chars"] = len(rec["markdown"])
    rec["stats"]["lines"] = rec["markdown"].count("\n") + 1 if rec["markdown"] else 0
    if rec["status"] == "ok" and not rec["markdown"].strip():
        rec["status"] = "empty"
        rec["notes"].append("抓取成功但未提取到正文（可能是纯 JS 渲染页）")
    return rec


STATUSES_NOTE = {
    "ok": "正常",
    "empty": "有响应但无正文",
    "blocked": "被拦截（鉴权/限流/挑战页）",
    "error": "网络或服务端异常",
}


# --------------------------------------------------------------------------- #
# 离线自检（内嵌 HTML 夹具，不联网）
# --------------------------------------------------------------------------- #

FIXTURE = """<!DOCTYPE html>
<html><head><title>示例标题</title>
<style>body{color:red}</style>
<script>var a = 1 < 2 && "x";</script>
<meta charset="utf-8">
</head>
<body>
<nav class="nav"><a href="/a">首页</a><a href="/b">归档</a></nav>
<div class="sidebar">推荐阅读<ul><li>无关内容</li></ul></div>
<article id="content">
  <h1>一级标题</h1>
  <h2 id="sec">标题二<a class="headerlink" href="#sec">¶</a></h2>
  <dl><dt id="d1">条目名<a class="headerlink" href="#d1">¶</a></dt><dd>释义文本</dd></dl>
  <p>这是一段 &amp; 含有&nbsp;实体的正文，<strong>加粗</strong>与<em>斜体</em>，
     以及一个<a href="https://example.com/x">链接</a>。</p>
  <h2>列表</h2>
  <ul><li>第一项</li><li>第二项</li></ul>
  <ol><li>甲</li><li>乙</li></ol>
  <pre><code>print("hello")</code></pre>
  <blockquote>引用文本</blockquote>
  <table><tr><th>列一</th><th>列二</th></tr><tr><td>1</td><td>2</td></tr></table>
  <script>tracker();</script>
  <p>尾部段落：应当保留。</p>
</article>
<footer>版权所有 &copy; 2026</footer>
</body></html>
"""


def _selftest_body(results: list[tuple[str, bool, str]]) -> int:
    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, bool(ok), detail))
        mark = "[PASS]" if ok else "[FAIL]"
        print(f"  {mark} {name}" + (f"   ← {detail}" if detail and not ok else ""))

    md, extra = html_to_markdown(FIXTURE)

    # 1) 噪声剔除
    check("剥离 <script>（含 `<` 比较符不误判为标签）", "var a" not in md and "tracker" not in md)
    check("剥离 <style>", "color:red" not in md)
    check("剥离 <nav> 导航链接", "首页" not in md and "/a" not in md)
    check("剥离侧栏噪声", "无关内容" not in md)
    check("剥离 <footer>", "版权所有" not in md)

    # 2) 主内容区命中
    check("主内容区命中 <article id=content>", extra["container"] == "article", extra["container"])
    check("标题取自 <title>", extra["title"] == "示例标题", extra["title"])

    # 3) 结构转换
    check("h1 → `# `", "# 一级标题" in md)
    check("永久链接锚点 ¶ 被剔除（不混入标题）",
          "¶" not in md and "## 标题二" in md, str([l for l in md.splitlines() if "标题二" in l][:1]))
    check("行内标签不产生孤立 block（<dt> 里的 ¶ 不另起一行）",
          md.count("¶") == 0 and "条目名" in md and "释义文本" in md,
          str([l for l in md.splitlines() if "条目名" in l][:1]))
    check("h2 → `## `", "## 列表" in md)
    check("strong → `**`", "**加粗**" in md)
    check("em → `*`", "*斜体*" in md)
    check("链接 → `[文本](url)`", "[链接](https://example.com/x)" in md)
    check("无序列表 → `- `", "- 第一项" in md and "- 第二项" in md)
    check("有序列表序号递增", "1. 甲" in md and "2. 乙" in md, md[:400])
    check("代码块 → 围栏 ```", '```\nprint("hello")\n```' in md)
    check("引用 → `> `", "> 引用文本" in md)
    check("表格含表头分隔行", "| 列一 | 列二 |" in md and "| --- | --- |" in md)

    # 4) 实体与空白
    check("&amp; 解码为 &（且未残留 &amp; 字面量）",
          "&amp;" not in md and "一段 & 含有" in md,
          str([l for l in md.splitlines() if "含有" in l][:1]))
    check("&nbsp; 归一为空格后不残留 \\xa0", "\xa0" not in md)
    check("多行空行被压缩（无连续 3 换行）", "\n\n\n" not in md)
    check("尾部段落保留（未因末尾 script 而丢失）", "尾部段落：应当保留。" in md)

    # 5) 证伪：清洗确实改变了内容，且不是「原样返回」
    check("证伪·清洗后与原 HTML 不同（清洗是载荷）", md != FIXTURE)
    check("证伪·剔除计数 > 0（prune 确实生效）", extra["dropped_nodes"] > 0,
          str(extra["dropped_nodes"]))
    empty_md, empty_extra = html_to_markdown("<html><body><script>x</script></body></html>")
    check("证伪·全噪声页 → 空正文（不是恒非空）", empty_md.strip() == "", repr(empty_md[:40]))

    # 6) 纯函数：URL 路由
    check("github 仓库 → raw README",
          github_to_raw("https://github.com/AMAP-ML/SkillClaw")
          == "https://raw.githubusercontent.com/AMAP-ML/SkillClaw/HEAD/README.md",
          str(github_to_raw("https://github.com/AMAP-ML/SkillClaw")))
    check("github blob → raw 指定路径",
          github_to_raw("https://github.com/o/r/blob/main/docs/a.md")
          == "https://raw.githubusercontent.com/o/r/main/docs/a.md")
    check("github 仓库带 .git 后缀可处理",
          github_to_raw("https://github.com/o/r.git")
          == "https://raw.githubusercontent.com/o/r/HEAD/README.md")
    check("非 github 返回 None（不误判）", github_to_raw("https://example.com/x") is None)
    check("适配器识别 github", detect_adapter("https://github.com/o/r")[0] == "github")
    check("适配器识别 csdn", detect_adapter("https://blog.csdn.net/a/b")[0] == "csdn")
    check("未登记站点回落 generic",
          detect_adapter("https://docs.python.org/x")[0] == "generic")
    check("csdn 适配器诚实地标为未实测",
          ADAPTERS["csdn"]["verified"] is False)

    # 7) robots 判定（纯函数）
    rb = Robots(HONEST_UA, 1)
    body = "User-agent: *\nDisallow: /private/\nAllow: /private/open/\n"
    check("robots: 命中 Disallow → disallowed", rb._rule(body, "/private/x") == "disallowed")
    check("robots: 更长的 Allow 优先 → allowed", rb._rule(body, "/private/open/x") == "allowed")
    check("robots: 未命中任何规则 → allowed", rb._rule(body, "/public/x") == "allowed")
    check("robots: 空 Disallow 值不视为全禁", rb._rule("User-agent: *\nDisallow:\n", "/x") == "allowed")

    # 8) HTTP 码分类（纯函数）
    check("403/429/451 → blocked",
          all(classify_http(c) == "blocked" for c in (403, 429, 451)))
    check("521/522 → blocked（WAF 挑战页）",
          all(classify_http(c) == "blocked" for c in (521, 522)))
    check("404/500 → error", all(classify_http(c) == "error" for c in (404, 500)))
    check("200/301 → ok", all(classify_http(c) == "ok" for c in (200, 301)))

    # 9) URL 非法：域内拒绝，不是崩溃
    bad = fetch("not-a-url", respect_robots=False)
    check("证伪·非法 URL → status=error 且有说明（不抛异常）",
          bad["status"] == "error" and bad["notes"], str(bad["notes"])[:80])
    check("非法 URL 记录仍满足契约 schema", bad["schema"] == SCHEMA)

    return EXIT_OK


def selftest() -> int:
    """离线自检入口：崩溃一律判 FAIL（退出码 1），并保留崩溃前已达成的判定清单。"""
    results: list[tuple[str, bool, str]] = []
    try:
        rc = _selftest_body(results)
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc(file=sys.stderr)
        print(f"\n  [FAIL] 自检自身崩溃 —— 崩溃不等于通过：{type(e).__name__}: {e}")
        rc = EXIT_DEFECT

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"\n自检结果：{passed}/{total} 通过" + ("（被中断，计数不完整）" if rc != EXIT_OK else ""))
    if passed != total:
        for name, ok, detail in results:
            if not ok:
                print(f"  - {name}   ← {detail}")
    return EXIT_DEFECT if (passed != total or rc != EXIT_OK) else EXIT_OK


def selftest_live() -> int:
    """联网自检：真实站点。失败会明确列出，不静默。"""
    cases = [
        ("https://raw.githubusercontent.com/AMAP-ML/SkillClaw/HEAD/README.md", "github-raw"),
        ("https://github.com/AMAP-ML/SkillClaw", "github"),
        ("https://docs.python.org/3/library/urllib.request.html", "generic"),
        ("https://blog.csdn.net/2302_80237966/article/details/167472508", "csdn"),
    ]
    print("mse.fetch/1 联网自检（真实站点；网络波动会导致失败，属正常）")
    results = []
    for url, expect_adapter in cases:
        rec = fetch(url)
        ok = rec["status"] == "ok" and rec["markdown"].strip() != ""
        results.append((url, expect_adapter, ok, rec))
        mark = "[OK]" if ok else "[--]"
        print(f"  {mark} {expect_adapter:11} status={rec['status']:7} "
              f"http={rec['http_status']} chars={rec['stats']['chars']:>7}  {url}")
        for n in rec["notes"]:
            print(f"         note: {n[:110]}")
    ok_count = sum(1 for _, _, ok, _ in results if ok)
    print(f"\n联网自检：{ok_count}/{len(cases)} 个站点拿到正文（不达标项见上行 status）")
    return EXIT_OK


def usage() -> str:
    return __doc__


def main(argv: list[str]) -> int:
    args = argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(usage())
        return EXIT_OK
    if "--selftest" in args:
        return selftest()
    if "--selftest-live" in args:
        return selftest_live()

    url = None
    as_md = False
    out_path = None
    max_chars = 0
    timeout = DEFAULT_TIMEOUT
    retries = 1
    ignore_robots = False
    ua = HONEST_UA

    i = 0
    while i < len(args):
        a = args[i]
        if a == "--md":
            as_md = True
        elif a == "-o" and i + 1 < len(args):
            i += 1
            out_path = args[i]
        elif a == "--max-chars" and i + 1 < len(args):
            i += 1
            max_chars = int(args[i])
        elif a == "--timeout" and i + 1 < len(args):
            i += 1
            timeout = int(args[i])
        elif a == "--retries" and i + 1 < len(args):
            i += 1
            retries = int(args[i])
        elif a == "--ignore-robots":
            ignore_robots = True
        elif a == "--ua" and i + 1 < len(args):
            i += 1
            ua = BROWSER_UA if args[i] == "browser" else args[i]
        elif a.startswith("-"):
            print(f"[用法错误] 未知选项 {a}\n{usage()}")
            return EXIT_DEFECT
        elif url is None:
            url = a
        else:
            print("[用法错误] 只接受一个 URL")
            return EXIT_DEFECT
        i += 1

    if url is None:
        print("[用法错误] 缺少 URL\n" + usage())
        return EXIT_DEFECT

    try:
        rec = fetch(url, ua=ua, timeout=timeout, retries=retries,
                    respect_robots=not ignore_robots, max_chars=max_chars)
    except Exception as e:  # noqa: BLE001
        print(f"[退出码 {EXIT_UNVERIFIABLE}] 无法验证：{type(e).__name__}: {e}")
        return EXIT_UNVERIFIABLE

    if as_md:
        payload = rec["markdown"]
    else:
        payload = json.dumps(rec, ensure_ascii=False, indent=2)

    if out_path:
        try:
            Path(out_path).write_text(payload, encoding="utf-8")
            print(f"[OK] 已写入 {out_path}（status={rec['status']}, "
                  f"chars={rec['stats']['chars']}）")
        except OSError as e:
            print(f"[退出码 {EXIT_DEFECT}] 写文件失败：{e}")
            return EXIT_DEFECT
    else:
        print(payload)

    if rec["status"] == "error":
        return EXIT_UNVERIFIABLE
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv))
