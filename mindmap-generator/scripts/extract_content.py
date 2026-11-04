#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract_content.py —— 脑图前置步骤：从「本地文档 / 网页 / 公众号文章」提取纯文字正文。

设计原则
--------
1. 零第三方依赖（HTML 解析用标准库 html.parser），只要 Python 3.8+ 即可运行。
2. 图片、二维码、广告、关注引导、平台水印等非核心内容一律剔除。
3. 输出 **Markdown 中间稿**：`#{1,6}` 标题 + 段落，作为下一步 build_mindmap.py 的输入。

支持来源
--------
URL        http(s) 链接；mp.weixin.qq.com 走专用解析（js_content 容器 + msg_title）
.docx      Word（需 python-docx，缺失时给出安装提示）
.pdf       PDF（需 pypdf 或 PyPDF2）
.pptx      PPT（需 python-pptx）
.txt/.md   直接读取
.html/.htm 本地网页
其他        按纯文本尽力读取

用法
----
python extract_content.py --source <路径或URL> --output <中间稿.md> [--max-chars N]
python extract_content.py --source <路径或URL> --stdout-only
python extract_content.py --source <路径或URL> --report      # 额外输出剔除统计
"""

import argparse
import io
import os
import re
import sys
import urllib.request
from html.parser import HTMLParser

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")

# ---------------------------------------------------------------- 结构
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input",
             "link", "meta", "param", "source", "track", "wbr"}

# 整块丢弃的标签
DROP_TAGS = {
    "script", "style", "noscript", "iframe", "svg", "canvas", "form",
    "nav", "header", "footer", "aside", "button", "select", "option",
    "textarea", "input", "video", "audio", "map", "object", "embed",
    "figure", "figcaption", "picture", "template", "dialog",
}

# class / id 命中即整块丢弃
DROP_HINT = re.compile(
    r"(^|[-_ ])("
    r"ad|ads|advert|advertisement|banner|promo|sponsor|"
    r"qr|qrcode|erweima|scan|"
    r"share|sharing|comment|comments|recommend|related|hot|"
    r"nav|navbar|menu|breadcrumb|crumb|sidebar|side|aside|"
    r"footer|header|top-bar|toolbar|social|subscribe|follow|"
    r"copyright|statement|disclaimer|"
    r"reward|donate|pay|tip|"
    r"recommend-list|read-more|next-article|prev-article"
    r")([-_ ]|$)", re.I)

# 图片型 / 表情类字符（emoji、装饰符号）清理
EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF"
    "\U00002190-\U000021FF\U00002B00-\U00002BFF\uFE0F\u200D]+")

# 行级“非核心内容”过滤规则（顺序执行）
BOILERPLATE_PATTERNS = [
    r"^\s*\W*(点击|长按|扫描|识别|猛戳)\s*(上方|下方|下方二维码|二维码|蓝字|图片|链接)?.*$",
    r"^.*(长按|扫描|识别|扫一扫|微信扫一扫).{0,8}(二维码|小程序|关注).*$",
    r"^.*(关注|订阅)(我们|本号|公众号|本公众号|德安杰|微信公众号).*$",
    r"^.*(点赞|在看|分享|转发|收藏|留言|评论区|一键三连|星标|置顶).{0,12}$",
    r"^.*(阅读原文|原文链接|点击阅读|查看原文|往期回顾|历史文章).*$",
    r"^.*(免责声明|版权声明|版权归|转载|来源：|内容仅代表|如有侵权).*$",
    r"^预览时标签不可点.*$",
    r"^.*(使用小程序|微信扫一扫|前往小程序).*$",
    r"^.{0,24}(微信号|ID|微信ID|公众号ID|投稿邮箱|商务合作|联系邮箱)[：: ].*$",
    r"^.{0,20}(编辑|排版|校对|审核|责编|美编|策划|监制|来源|原标题|作者|记者|摄影)[：: ].{0,40}$",
    r"^[（(【\[]?\s*(图|图片|配图|示意图|资料图|海报|视频|截图|图片来源|图源)[：:、/／].{0,60}[)）】\]]?\s*$",
    r"^\s*(上一篇|下一篇|更多精彩|推荐阅读|相关阅读|猜你喜欢).*$",
    r"^\s*[·•●◆■□▲▼※*—\-=_~]{2,}\s*$",
    r"^\s*(原创|转载|声明|广告)\s*$",
]
BOILERPLATE_RE = [re.compile(p, re.I) for p in BOILERPLATE_PATTERNS]

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
MD_BULLET_RE = re.compile(r"^\s*([-*+]|\d{1,2}[.)])\s+(.*\S)\s*$")


# ---------------------------------------------------------------- HTML → 块
class Node:
    __slots__ = ("tag", "attrs", "children", "text", "parent")

    def __init__(self, tag="", attrs=None, parent=None):
        self.tag = tag
        self.attrs = dict(attrs or {})
        self.children = []
        self.text = ""
        self.parent = parent

    def cls_id(self):
        v = (self.attrs.get("class") or "") + " " + (self.attrs.get("id") or "")
        return v.strip()


class DomBuilder(HTMLParser):
    """把 HTML 解析为一棵轻量 DOM 树。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root")
        self.stack = [self.root]
        self.title = ""
        self.og_title = ""
        self.og_desc = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "title":
            self._in_title = True
        if tag == "meta":
            prop = (a.get("property") or a.get("name") or "").lower()
            if prop in ("og:title", "twitter:title") and not self.og_title:
                self.og_title = a.get("content", "")
            elif prop in ("og:description", "description") and not self.og_desc:
                self.og_desc = a.get("content", "")
        node = Node(tag, a, self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag.lower() not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self.stack:
            self.stack[-1].text += data


def drop_subtree(node):
    """判断该节点是否属于“非核心内容”块。"""
    if node.tag in DROP_TAGS:
        return True
    ci = node.cls_id()
    if ci and DROP_HINT.search(ci):
        return True
    if node.attrs.get("aria-hidden") == "true" or node.attrs.get("hidden") is not None:
        return True
    style = (node.attrs.get("style") or "").replace(" ", "").lower()
    if "display:none" in style or "visibility:hidden" in style:
        return True
    return False


def node_text_len(node):
    n = len(node.text.strip())
    for c in node.children:
        n += node_text_len(c)
    return n


def collect_blocks(node, out, skip_deeper_drop=True):
    """递归收集 (level, text) 块。level: 0 段落 / 1-6 标题 / -1 列表项。"""
    for child in node.children:
        if skip_deeper_drop and drop_subtree(child):
            continue
        t = child.tag
        if t in ("h1", "h2", "h3", "h4", "h5", "h6"):
            txt = flatten(child)
            if txt:
                out.append((int(t[1]), txt))
        elif t in ("p", "div", "section", "blockquote", "td", "th", "dd", "dt"):
            # 含块级子元素则继续下钻，避免重复
            has_block = any(c.tag in ("p", "div", "section", "li", "ul", "ol", "h1", "h2",
                                      "h3", "h4", "h5", "h6", "table", "tr", "blockquote")
                            for c in child.children)
            if has_block:
                collect_blocks(child, out)
            else:
                txt = flatten(child)
                if txt:
                    out.append((0, txt))
        elif t == "li":
            txt = flatten(child, stop_at=("ul", "ol"))
            if txt:
                out.append((-1, txt))
            for c in child.children:
                if c.tag in ("ul", "ol"):
                    collect_blocks(c, out)
        elif t == "tr":
            cells = [flatten(c) for c in child.children if c.tag in ("td", "th")]
            cells = [c for c in cells if c]
            if cells:
                out.append((0, " | ".join(cells)))
        elif t in ("ul", "ol", "table", "tbody", "thead", "tr", "article", "main", "body",
                   "#root", "span", "a", "strong", "b", "em", "i", "font", "center",
                   "br", "hr", "label", "time", "small", "sub", "sup", "u", "mark"):
            collect_blocks(child, out)
        else:
            txt = flatten(child)
            if txt and len(txt) > 30:
                out.append((0, txt))


def flatten(node, stop_at=()):
    """取节点内所有可见文字（跳过丢弃块与被 stop_at 命中的子块）。"""
    parts = []
    if node.tag == "br":
        parts.append(" ")
    if node.text:
        parts.append(node.text)
    for c in node.children:
        if c.tag in DROP_TAGS or c.tag in stop_at or drop_subtree(c):
            continue
        parts.append(flatten(c, stop_at))
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def pick_main(root):
    """在整棵树中挑选正文容器：优先 article / 语义化容器 / 文字量最大的块。"""
    candidates = []

    def walk(n, depth):
        if drop_subtree(n):
            return
        if n.tag in ("article",):
            candidates.append((node_text_len(n) + 100000, n))
        ci = (n.attrs.get("id") or "") + " " + (n.attrs.get("class") or "")
        if re.search(r"(article[-_]?content|rich_media_content|js_content|post[-_]?content|"
                     r"entry[-_]?content|content[-_]?body|main[-_]?content|"
                     r"markdown[-_]?body|article|content|main|post|entry)", ci, re.I):
            candidates.append((node_text_len(n), n))
        for c in n.children:
            walk(c, depth + 1)

    walk(root, 0)
    if candidates:
        candidates.sort(key=lambda x: -x[0])
        best = candidates[0][1]
        if node_text_len(best) > 200:
            return best
    body = find_tag(root, "body") or root
    return body


def find_tag(node, tag):
    if node.tag == tag:
        return node
    for c in node.children:
        r = find_tag(c, tag)
        if r is not None:
            return r
    return None


# ---------------------------------------------------------------- 清洗
def clean_text(s):
    s = s.replace("\u3000", " ").replace("\xa0", " ")
    s = EMOJI.sub("", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    return s.strip()


def is_boilerplate(line):
    if not line:
        return True
    for r in BOILERPLATE_RE:
        if r.match(line):
            return True
    core = re.sub(r"[\s\W_]+", "", line)
    if len(core) <= 2 and not HEADING_RE.match(line):
        return True
    if re.fullmatch(r"[\d\s.,%+\-/：:年月日·]+", line):
        return True
    return False


def blocks_to_markdown(blocks, report=None):
    lines, dropped = [], 0
    for level, raw in blocks:
        text = clean_text(raw)
        if not text:
            continue
        if level > 0:
            text = re.sub(r"\s+", " ", text)
            # 标题通常应短小；过长则视为被误标的正文，降级处理
            if len(text) > 60:
                if is_boilerplate(text):
                    dropped += 1
                    continue
                lines.append(text)
                continue
            if is_boilerplate(text):
                dropped += 1
                continue
            lines.append("#" * min(level, 6) + " " + text)
        elif level == -1:
            text = re.sub(r"\s+", " ", text)
            if is_boilerplate(text):
                dropped += 1
                continue
            lines.append("- " + text)
        else:
            if is_boilerplate(text):
                dropped += 1
                continue
            lines.append(text)
    if report is not None:
        report["dropped"] = dropped
        report["kept"] = len(lines)
    return lines


def normalize_markdown(lines):
    """规整空行：标题前后留空行，段落之间留空行，去掉连续空行。"""
    out = []
    for ln in lines:
        is_head = ln.startswith("#")
        prev = out[-1] if out else ""
        if is_head and out and prev != "":
            out.append("")
        if not is_head and not ln.startswith("- ") and prev.startswith("#") and prev:
            pass
        out.append(ln)
    res, blanks = [], 0
    for ln in out:
        if ln == "":
            blanks += 1
            if blanks > 1:
                continue
        else:
            blanks = 0
        res.append(ln)
    while res and res[-1] == "":
        res.pop()
    return res


# ---------------------------------------------------------------- 各来源提取
def decode_bytes(raw, content_type=""):
    m = re.search(r"charset=([\w-]+)", content_type or "", re.I)
    encodings = [m.group(1)] if m else []
    m2 = re.search(rb'charset=["\']?([\w-]+)', raw[:4000], re.I)
    if m2:
        encodings.append(m2.group(1).decode("ascii", "ignore"))
    encodings += ["utf-8", "gb18030", "gbk", "big5", "latin-1"]
    for enc in encodings:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "ignore")


def fetch_url(url, timeout=25):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        ctype = resp.headers.get("Content-Type", "")
    return decode_bytes(raw, ctype)


def extract_from_html(html, report=None, url=""):
    """HTML → (title, blocks)"""
    # 公众号优先走专用容器，避免被通用启发式挑错
    is_wx = "mp.weixin.qq.com" in url or "js_content" in html
    title = ""

    m = re.search(r"var\s+msg_title\s*=\s*['\"](.+?)['\"]\s*[;.]", html, re.S)
    if not m:
        m = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\'](.*?)["\']', html, re.I | re.S)
    if not m:
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if m:
        title = re.sub(r"\s+", " ", m.group(1)).strip()

    builder = DomBuilder()
    try:
        builder.feed(html)
        builder.close()
    except Exception as e:  # 容错：解析中断也要拿到已解析的部分
        if report is not None:
            report["parse_warning"] = str(e)
    root = builder.root
    if not title:
        title = (builder.og_title or builder.title or "").strip()
        title = re.sub(r"\s+", " ", title)

    target = None
    if is_wx:
        target = find_by_id(root, "js_content")
    if target is None:
        target = pick_main(root)
    blocks = []
    collect_blocks(target, blocks)
    return title, blocks


def find_by_id(node, wanted):
    if node.attrs.get("id") == wanted:
        return node
    for c in node.children:
        r = find_by_id(c, wanted)
        if r is not None:
            return r
    return None


def extract_docx(path):
    try:
        import docx  # python-docx
    except ImportError:
        raise SystemExit("缺少 python-docx：请执行  pip install python-docx  后重试。")
    d = docx.Document(path)
    blocks = []
    for p in d.paragraphs:
        txt = clean_text(p.text)
        if not txt:
            continue
        style = (p.style.name or "") if p.style is not None else ""
        lvl = 0
        m = re.search(r"Heading\s*(\d)", style, re.I) or re.search(r"标题\s*(\d)", style)
        if m:
            lvl = int(m.group(1))
        elif style.lower().startswith("title") or style in ("Title",):
            lvl = 1
        blocks.append((lvl, txt))
    for t in d.tables:
        for row in t.rows:
            cells = [clean_text(c.text) for c in row.cells]
            cells = [c for c in cells if c]
            if cells:
                blocks.append((-1, " | ".join(cells)))
    return blocks


def extract_pptx(path):
    try:
        from pptx import Presentation
    except ImportError:
        raise SystemExit("缺少 python-pptx：请执行  pip install python-pptx  后重试。")
    prs = Presentation(path)
    blocks = []
    for i, slide in enumerate(prs.slides, 1):
        title = ""
        try:
            if slide.shapes.title and slide.shapes.title.text:
                title = clean_text(slide.shapes.title.text)
        except Exception:
            title = ""
        blocks.append((2, title or ("第 %d 页" % i)))
        for sh in slide.shapes:
            if not getattr(sh, "has_text_frame", False):
                continue
            for para in sh.text_frame.paragraphs:
                txt = clean_text("".join(r.text for r in para.runs))
                if txt and txt != title:
                    blocks.append((-1, txt))
    return blocks


def extract_pdf(path):
    text = ""
    try:
        from pypdf import PdfReader
        reader = PdfReader(path)
        for page in reader.pages:
            text += (page.extract_text() or "") + "\n"
    except ImportError:
        try:
            from PyPDF2 import PdfReader  # type: ignore
            reader = PdfReader(path)
            for page in reader.pages:
                text += (page.extract_text() or "") + "\n"
        except ImportError:
            raise SystemExit("缺少 PDF 解析库：请执行  pip install pypdf  后重试。")
    # PDF 换行多为硬折行：行尾无句读且下一行小写/无标点时合并
    raw_lines = [clean_text(l) for l in text.split("\n")]
    raw_lines = [l for l in raw_lines if l]
    merged, buf = [], ""
    for ln in raw_lines:
        if buf and not re.search(r"[。！？；：.!?;:”\"）)】\]】]$", buf):
            buf += ln
        else:
            if buf:
                merged.append(buf)
            buf = ln
    if buf:
        merged.append(buf)
    return [(0, m) for m in merged]


def extract_plain(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        text = f.read()
    if text.strip().startswith("<") and re.search(r"<\w+[\s>]", text[:500]):
        return extract_from_html(text, url="")
    return [(0, l) for l in text.split("\n")]


# ---------------------------------------------------------------- main
def build(source, max_chars=80000, report=None):
    report = report if report is not None else {}
    is_url = re.match(r"^https?://", source, re.I) is not None

    if is_url:
        html = fetch_url(source)
        title, blocks = extract_from_html(html, report, url=source)
        report["source_type"] = "url"
    else:
        if not os.path.exists(source):
            raise SystemExit("找不到文件：%s" % source)
        ext = os.path.splitext(source)[1].lower()
        report["source_type"] = ext or "text"
        title = os.path.splitext(os.path.basename(source))[0]
        if ext == ".docx":
            blocks = extract_docx(source)
        elif ext == ".pptx":
            blocks = extract_pptx(source)
        elif ext == ".pdf":
            blocks = extract_pdf(source)
        elif ext in (".txt", ".md", ".markdown", ".text"):
            blocks = extract_plain(source)
            if ext in (".md", ".markdown"):
                # Markdown 已是结构化的，直接保留标题/列表语法
                return title, normalize_markdown([l.rstrip() for l in open(
                    source, encoding="utf-8", errors="ignore").read().split("\n")]), report
        elif ext in (".html", ".htm"):
            blocks = extract_from_html(open(source, encoding="utf-8", errors="ignore").read(),
                                       report, url="")
        else:
            blocks = extract_plain(source)

    lines = blocks_to_markdown(blocks, report)
    lines = normalize_markdown(lines)
    text = "\n".join(lines)
    # 确保首行是文章标题（公众号/网页抓取时常会丢标题行）
    if title and not any(
        re.match(r"^#\s", ln) and ln[1:].strip() == title.strip() for ln in lines
    ):
        lines = ["# " + title] + lines
        text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars]
        report["truncated"] = True
    report["chars"] = len(text)
    report["title"] = title
    return title, text.split("\n"), report


def main():
    ap = argparse.ArgumentParser(description="提取本地文档/网页/公众号正文（脑图前置步骤）")
    ap.add_argument("--source", required=True, help="文件路径或 URL")
    ap.add_argument("--output", help="中间稿输出路径（.md）")
    ap.add_argument("--max-chars", type=int, default=80000, help="正文长度上限，默认 80000")
    ap.add_argument("--stdout-only", action="store_true", help="只打印，不落盘")
    ap.add_argument("--report", action="store_true", help="额外输出剔除统计")
    args = ap.parse_args()

    report = {}
    title, lines, report = build(args.source, args.max_chars, report)
    text = "\n".join(lines)

    if not text.strip():
        print("[WARN] 未提取到任何正文。若是图片型文章，请改用浏览器滚动截图 + OCR 兜底。",
              file=sys.stderr)

    out = None
    if not args.stdout_only:
        out = args.output
        if not out:
            base = re.sub(r'[\\/:*?"<>|]', "_", title or "extracted")[:60]
            out = os.path.join(os.getcwd(), base + ".md")
        out = os.path.abspath(out)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with io.open(out, "w", encoding="utf-8", newline="\n") as f:
            f.write(text + "\n")

    sys.stdout.write(text + "\n")
    if args.report:
        print("\n--- report ---", file=sys.stderr)
        print("title      : %s" % title, file=sys.stderr)
        print("source_type: %s" % report.get("source_type"), file=sys.stderr)
        print("blocks kept: %s" % report.get("kept"), file=sys.stderr)
        print("filtered   : %s" % report.get("dropped"), file=sys.stderr)
        print("chars      : %s" % report.get("chars"), file=sys.stderr)
        if report.get("truncated"):
            print("truncated  : yes", file=sys.stderr)
    if out:
        print("[OK] 中间稿已保存：%s" % out, file=sys.stderr)


if __name__ == "__main__":
    main()
