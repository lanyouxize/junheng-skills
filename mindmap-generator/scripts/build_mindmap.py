#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_mindmap.py —— 脑图第二步：把「结构化中间稿」渲染成自包含交互式 HTML 脑图。

输入：Markdown 中间稿（`#{1,6}` 标题为分支层级，`- ` 列表项 / 短段落为叶子）
      其中 `## 摘要` 小节会被抽出来，既作为页面顶部摘要卡片，也作为脑图中的「摘要」节点。
输出：单文件 HTML（内嵌模板 + 数据，零外部依赖、可离线打开），支持导出 PNG / SVG。

用法
----
python build_mindmap.py --input outline.md --output 脑图.html \
       [--title "标题"] [--source "来源"] [--theme light|dark] \
       [--summary-file summary.txt] [--require-summary] [--max-depth 4]
"""

import argparse
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, os.pardir, "assets", "mindmap_template.html")

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
BULLET_RE = re.compile(r"^(\s*)(?:[-*+]|\d{1,2}[.)])\s+(.*\S)\s*$")
HR_RE = re.compile(r"^\s*([-*_])\s*\1\s*\1[\s\1]*$")
SUMMARY_KEY = re.compile(r"摘要|内容概要|概述|导读|全文速览|导读摘要")

PARA_MAX = 120          # 段落型叶子文本上限
SUMMARY_TARGET = 200    # 摘要目标字数


def strip_inline(s):
    """去掉行内 Markdown 标记：**加粗**、*斜体*、`代码`、[文字](链接)。"""
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", s)          # 图片
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)      # 链接保留文字
    s = re.sub(r"`+([^`]*)`+", r"\1", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
    s = re.sub(r"__([^_]+)__", r"\1", s)
    s = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"\1", s)
    s = re.sub(r"~~([^~]+)~~", r"\1", s)
    s = re.sub(r"<[^>]+>", "", s)                       # 残留 HTML 标签
    s = s.replace("　", " ").strip()
    return s


def load_lines(path):
    with io.open(path, "r", encoding="utf-8", errors="ignore") as f:
        return [l.rstrip("\n").rstrip("\r") for l in f]


def parse(lines, max_depth=4, report=None):
    """解析中间稿 → (title, tree, summary, warns)"""
    report = report if report is not None else {}
    warns = []

    # ---------- 第一遍：抽取「摘要」小节 ----------
    summary_parts, keep = [], []
    i, n = 0, len(lines)
    while i < n:
        ln = lines[i]
        m = HEADING_RE.match(ln)
        if m and SUMMARY_KEY.search(m.group(2)) and len(m.group(1)) <= 3:
            level = len(m.group(1))
            i += 1
            while i < n:
                m2 = HEADING_RE.match(lines[i])
                if m2 and len(m2.group(1)) <= level:
                    break
                t = strip_inline(lines[i])
                if t:
                    b = BULLET_RE.match(lines[i])
                    summary_parts.append(strip_inline(b.group(2)) if b else t)
                i += 1
            continue
        keep.append(ln)
        i += 1

    # 行首「摘要：xxx」形式
    if not summary_parts:
        for ln in keep:
            if re.match(r"^\s*(摘要|内容摘要)\s*[:：]", ln):
                summary_parts.append(re.sub(r"^\s*(摘要|内容摘要)\s*[:：]\s*", "", strip_inline(ln)))
        if summary_parts:
            keep = [l for l in keep if not re.match(r"^\s*(摘要|内容摘要)\s*[:：]", l)]

    summary = " ".join(x for x in summary_parts if x).strip()
    summary = re.sub(r"\s{2,}", " ", summary)

    # ---------- 第二遍：构建树 ----------
    title = None
    root = {"name": "脑图", "children": []}
    stack = [(-1, root)]          # (heading_level, node)
    list_stack = []               # (indent, node)
    cur_parent = root

    for raw in keep:
        if not raw.strip() or HR_RE.match(raw):
            continue

        h = HEADING_RE.match(raw)
        if h:
            level = len(h.group(1))
            name = strip_inline(h.group(2))
            name = re.sub(r"^[一二三四五六七八九十\d]+[、.．)）]\s*", "", name)
            if not name:
                continue
            if title is None and level == 1:
                title = name
                root["name"] = name
                stack = [(1, root)]
                list_stack = []
                cur_parent = root
                continue
            while len(stack) > 1 and stack[-1][0] >= level:
                stack.pop()
            parent = stack[-1][1]
            node = {"name": name, "children": []}
            parent["children"].append(node)
            stack.append((level, node))
            list_stack = []
            cur_parent = node
            continue

        b = BULLET_RE.match(raw)
        if b:
            indent = len(b.group(1).replace("\t", "    "))
            name = strip_inline(b.group(2))
            if not name:
                continue
            while list_stack and list_stack[-1][0] >= indent:
                list_stack.pop()
            parent = list_stack[-1][1] if list_stack else cur_parent
            node = {"name": name, "children": []}
            parent["children"].append(node)
            list_stack.append((indent, node))
            continue

        # 普通段落 → 叶子节点
        text = strip_inline(raw)
        if not text:
            continue
        if len(text) > PARA_MAX:
            text = text[:PARA_MAX].rstrip() + "…"
            warns.append("段落过长已截断：%s…" % text[:24])
        node = {"name": text, "children": []}
        (list_stack[-1][1] if list_stack else cur_parent)["children"].append(node)

    if title is None:
        # 没有一级标题：取根下第一个纯文本子节点当标题（常见于纯文本/无标题文档）
        kids = root.get("children", [])
        for idx, c in enumerate(kids):
            if not c.get("children") and len(c.get("name", "")) >= 4:
                title = c["name"]
                root["name"] = title
                del kids[idx]
                break
    if title is None:
        title = root["name"]

    # ---------- 规整 ----------
    def prune(node, depth):
        """去掉空节点；限制层级（超深内容并入父节点文本）。"""
        kids = []
        for c in node.get("children", []):
            c = prune(c, depth + 1)
            if c:
                kids.append(c)
        node["children"] = kids
        node["name"] = re.sub(r"\s{2,}", " ", node.get("name", "")).strip()
        if not node["name"] and not kids:
            return None
        if not node["name"] and kids:
            return kids[0] if len(kids) == 1 else {"name": "（未命名）", "children": kids}
        return node

    root = prune(root, 0)
    if root is None:
        root = {"name": title or "脑图", "children": []}

    def count(node):
        return 1 + sum(count(c) for c in node.get("children", []))

    report["nodes"] = count(root) - 1
    report["depth"] = max_depth_of(root)
    report["warns"] = warns
    return title or root["name"], root, summary, warns


def max_depth_of(node, d=0):
    kids = node.get("children") or []
    return max([max_depth_of(c, d + 1) for c in kids] + [d])


def esc_html(s):
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def count_chars(s):
    """中文按字计，英文按词计。"""
    cjk = len(re.findall(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]", s))
    words = len(re.findall(r"[A-Za-z][A-Za-z'\-]*", s))
    return cjk + words


def render(template_html, title, source, tree, summary, theme, generated_at):
    data = {
        "title": title,
        "source": source,
        "generatedAt": generated_at,
        "summary": summary,
        "tree": tree,
    }
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")

    if summary:
        tree.setdefault("children", [])
        tree["children"] = [{"name": summary, "kind": "summary", "children": []}] + [
            c for c in tree["children"] if c.get("kind") != "summary"
        ]
        payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        payload = payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")

    repl = {
        "__TITLE__": esc_html(title),
        "__SOURCE__": esc_html(source or "未标注来源"),
        "__GENERATED_AT__": esc_html(generated_at),
        "__SUMMARY_HTML__": esc_html(summary) if summary else "（未提供摘要：请在中间稿加入 `## 摘要` 小节，或用 --summary-file 指定）",
        "__SUMMARY_COUNT__": str(count_chars(summary)) if summary else "0",
        "__DEFAULT_THEME__": theme,
        "__DATA_JSON__": payload,
    }
    out = template_html
    for k, v in repl.items():
        out = re.sub(re.escape(k), lambda _m, _v=v: _v, out)
    return out


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="Markdown 中间稿 → 交互式 HTML 脑图")
    ap.add_argument("--input", required=True, help="Markdown 中间稿路径")
    ap.add_argument("--output", help="输出的 .html 路径")
    ap.add_argument("--title", help="覆盖脑图标题")
    ap.add_argument("--source", default="", help="来源说明（文件名或链接）")
    ap.add_argument("--theme", default="light", choices=["light", "dark"], help="默认主题")
    ap.add_argument("--summary-file", help="从独立文件读取摘要（覆盖中间稿中的摘要）")
    ap.add_argument("--require-summary", action="store_true", help="缺少摘要时报错退出")
    ap.add_argument("--max-depth", type=int, default=4, help="层级上限提示值，默认 4")
    ap.add_argument("--template", help="自定义 HTML 模板路径")
    args = ap.parse_args()

    if not os.path.exists(args.input):
        raise SystemExit("找不到中间稿：%s" % args.input)

    tpl_path = args.template or TEMPLATE
    if not os.path.exists(tpl_path):
        raise SystemExit("找不到模板：%s" % tpl_path)
    with io.open(tpl_path, "r", encoding="utf-8") as f:
        template_html = f.read()

    report = {}
    title, tree, summary, warns = parse(load_lines(args.input), args.max_depth, report)

    if args.summary_file:
        if not os.path.exists(args.summary_file):
            raise SystemExit("找不到摘要文件：%s" % args.summary_file)
        with io.open(args.summary_file, "r", encoding="utf-8") as f:
            summary = re.sub(r"\s{2,}", " ", " ".join(
                l.strip() for l in f.read().split("\n") if l.strip()))
    if args.title:
        title = args.title
        tree["name"] = args.title
    if not args.source:
        args.source = os.path.basename(args.input)

    n_chars = count_chars(summary)
    if not summary and args.require_summary:
        raise SystemExit("中间稿缺少摘要（需 `## 摘要` 小节或 --summary-file）。")
    if summary and not (140 <= n_chars <= 300):
        print("[WARN] 摘要 %d 字，建议控制在 200 字左右（140–300 之间）。" % n_chars,
              file=sys.stderr)

    import datetime
    generated_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    html = render(template_html, title, args.source, tree, summary, args.theme, generated_at)

    out = args.output
    if not out:
        safe = re.sub(r'[\\/:*?"<>|]', "_", title or "脑图")[:60]
        out = os.path.join(os.path.expanduser("~"), "Desktop", safe + "_脑图.html")
    out = os.path.abspath(out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with io.open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)

    print("[OK] 脑图已生成：%s" % out)
    print("     标题：%s" % title)
    print("     节点：%d 个 / 层级 %d 层 / 摘要 %d 字" % (report.get("nodes", 0),
                                                       report.get("depth", 0), n_chars))
    for w in warns[:5]:
        print("     [WARN] %s" % w, file=sys.stderr)


if __name__ == "__main__":
    main()
