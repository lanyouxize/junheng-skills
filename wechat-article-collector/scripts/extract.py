#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公众号文章页 HTML -> 文章字段（纯解析：BS4+lxml，无浏览器/网络依赖）。

三层取到的同一份 HTML 共用本解析器：L1 Playwright / L2 requests / L3 MITM。
输出字段与 normalize.build_article 入参 1:1 对应，由各采集层转成 25 列记录。
"""
from __future__ import annotations

import re
from html import unescape
from typing import Any
from urllib.parse import urljoin

from common import lazy_import

_JS_NAMES = ("msg_title", "nickname", "author", "msg_desc", "msg_cdn_url", "ct", "biz")
_EPOCH_RE = re.compile(r"^\d{9,11}$")
# 微信页面里发布时间的中文写法（#publish_time 元素文本）
_CN_DT_RE = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*(\d{1,2}):(\d{2})")
# 仅用于排除 .rich_media_meta_text 里的发布日期：年份可省略（如"10月21日"），
# 区别于 _CN_DT_RE（后者需完整年月日时分以解析时间戳）。
_CN_DATEISH_RE = re.compile(r"(\d{4}\s*年)?\s*\d{1,2}\s*月\s*\d{1,2}\s*日")
# 值尾部常见的链式调用/算术修正，需剥掉才拿得到字面量
_JS_SUFFIXES = (".html(false)", ".html(true)", ".html()")

# 中国省级行政区（省/直辖市/自治区/特别行政区，含带后缀写法）。新版式里
# `.rich_media_meta_text` 第一个常见值就是省份定位（如"湖南"），需排除，避免把
# 省份名当作者写进 author 列。
_PROVINCES = frozenset({
    "北京", "天津", "上海", "重庆",
    "河北", "山西", "辽宁", "吉林", "黑龙江", "江苏", "浙江", "安徽", "福建",
    "江西", "山东", "河南", "湖北", "湖南", "广东", "海南", "四川", "贵州",
    "云南", "陕西", "甘肃", "青海", "台湾",
    "内蒙古", "广西", "西藏", "宁夏", "新疆",
    "香港", "澳门",
    "北京市", "天津市", "上海市", "重庆市",
    "内蒙古自治区", "广西壮族自治区", "西藏自治区", "宁夏回族自治区",
    "新疆维吾尔自治区", "香港特别行政区", "澳门特别行政区",
})


def _js_literal(expr: str) -> str:
    """从一段 JS 表达式里取可用字符串。

    2026 版页面不再写纯字面量，常见三种形态需统一处理：
      htmlDecode("浙江农林大学宠物科学研究所")   -> 去包装
      '标题'.html(false)                        -> 去链式调用
      "MzkwNzgyNDk1Nw==" || ""                  -> `||` 回退链取首个非空字面量
      "1792666226" * 1                          -> 去算术修正
    取不到字符串字面量时返回 ""（例如压缩代码里的 `et(r,G)`），由调用方回退。
    """
    expr = (expr or "").strip()
    if not expr:
        return ""
    wrapped = re.fullmatch(r"htmlDecode\(\s*(.*?)\s*\)", expr, re.S)
    if wrapped:
        expr = wrapped.group(1).strip()
    for suffix in _JS_SUFFIXES:
        if expr.endswith(suffix):
            expr = expr[: -len(suffix)].strip()
            break
    if expr.endswith("* 1"):
        expr = expr[:-3].strip()
    for part in expr.split("||"):
        part = part.strip()
        if len(part) >= 2 and part[0] == part[-1] and part[0] in "\"'":
            value = re.sub(r"\\(['\"\\/])", r"\1", part[1:-1])
            value = unescape(value).strip()
            if value:
                return value
    return ""


def _js_var(html: str, name: str) -> str:
    """提取 `var <name> = <expr>;` 形式的页面 JS 变量（容忍转义引号与中文）。

    只匹配**同一行**内的声明：新版页面把大量逻辑压缩进单行，跨行匹配会命中
    `var ct = et(r,G);return ...` 这类打包代码，导致取到错误的“值”。
    """
    match = re.search(r"var\s+%s\s*=\s*([^\n]*?);" % re.escape(name), html)
    if not match:
        return ""
    return _js_literal(match.group(1))


def _meta_content(soup: Any, key: str) -> str:
    tag = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
    return str(tag.get("content") or "").strip() if tag else ""


def _text_of(node: Any) -> str:
    return node.get_text(" ", strip=True) if node else ""


def _first_non_empty(*values: str) -> str:
    for value in values:
        if value and value.strip():
            return value.strip()
    return ""


def _clean_text(t: str) -> str:
    """清洗微信页面转义/残留标签，输出干净文本。

    微信 digest/author 等字段在 HTML 里常带微信自有的字面转义（``\\x26`` 即字面
    ``&``，非 URL 编码 ``%26``）以及 topic-link 的转义 HTML，例如::

        \\x26lt;a class=\\x26quot;wx_topic_link\\x26quot; href=...\\x26gt;#主题\\x26lt;/a\\x26gt;

    解码链：``\\x26`` -> ``&`` -> ``unescape`` -> 剥 ``<a>`` 锚 -> 去残余标签 ->
    字面 ``\\x0a`` -> 换行 -> 压空白。title/account/author/digest 统一过本函数。
    """
    if not t:
        return ""
    t = t.replace("\\x26", "&")
    t = unescape(t)
    t = re.sub(r"<a\b[^>]*>.*?</a>", " ", t, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    t = t.replace("\\x0a", "\n")
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _epoch_to_iso(raw: str) -> str:
    """页面 JS 里的 epoch 秒 -> UTC ISO8601（Z 后缀）。"""
    if not _EPOCH_RE.match(raw or ""):
        return ""
    from datetime import datetime, timezone

    return datetime.fromtimestamp(int(raw), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _cn_time_to_iso(text: str) -> str:
    """`2026年10月22日 18:50` -> `2026-10-22T10:50:00Z`（按 +08:00 解释，统一存 UTC）。"""
    match = _CN_DT_RE.search(text or "")
    if not match:
        return ""
    from datetime import datetime, timedelta, timezone

    year, month, day, hour, minute = (int(part) for part in match.groups())
    try:
        moment = datetime(year, month, day, hour, minute,
                          tzinfo=timezone(timedelta(hours=8)))
    except ValueError:
        return ""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _absolute(link: str, base: str) -> str:
    link = (link or "").strip()
    if not link:
        return ""
    if link.startswith("//"):
        return "https:" + link
    return urljoin(base, link)


def _collect_images(soup: Any, content: Any, base: str) -> list[dict[str, str]]:
    """收集正文图片（data-src 优先、src 兜底）；仅保留微信 CDN，过滤统计像素/图标。"""
    scope = content if content is not None else soup
    seen: set[str] = set()
    images: list[dict[str, str]] = []
    for img in scope.find_all("img"):
        src = (img.get("data-src") or img.get("src") or "").strip()
        if not src or src.startswith("data:"):
            continue
        absolute = _absolute(src, base)
        if not absolute.startswith("https://") or absolute in seen:
            continue
        if "mmbiz" not in absolute and "qpic" not in absolute:
            continue
        seen.add(absolute)
        images.append({"url": absolute, "data_src": src})
    return images


def _find_video_url(soup: Any, html: str) -> str:
    """识别视频文章：iframe(v.qq.com/mpvideo) 或 <mpvideo> 标签；返回播放页 URL 或 ""。"""
    for iframe in soup.find_all("iframe"):
        src = (iframe.get("data-src") or iframe.get("src") or "").strip()
        if "v.qq.com" in src or "mpvideo" in src:
            return _absolute(src, "https://mp.weixin.qq.com")
    for tag in soup.find_all("mpvideo"):
        src = (tag.get("data-src") or "").strip()
        if src:
            return _absolute(src, "https://mp.weixin.qq.com")
    return ""


def _count_words(text: str) -> int:
    """正文字数：CJK 按字、拉丁/数字按词。"""
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    latin = len(re.findall(r"[A-Za-z0-9]+", text))
    return cjk + latin


def extract_article(html: str, url: str) -> dict[str, Any]:
    """解析文章页 HTML，返回字段 dict（键与 build_article 入参对应）。

    返回键：title/account/account_id/author/publish_time/digest/body_html/
    body_text/word_count/images[]/cover/video_url/media_type。
    body_html 为空表示正文缺失（调用方应置 status=fail 并留原因）。
    """
    bs4 = lazy_import("bs4", "pip install beautifulsoup4 lxml")
    BeautifulSoup = bs4.BeautifulSoup
    soup = BeautifulSoup(html, "lxml")

    title = _clean_text(_first_non_empty(
        _meta_content(soup, "og:title"),
        _js_var(html, "msg_title"),
        _text_of(soup.select_one("h1.rich_media_title, #activity-name")),
    ))
    account = _clean_text(_first_non_empty(
        _text_of(soup.select_one("#js_name, .rich_media_meta_nickname")),
        _js_var(html, "nickname"),
    ))
    author = _first_non_empty(
        _js_var(html, "author"),
        _text_of(soup.select_one("#js_author_name")),
    )
    if not author:
        # 旧版式把作者放在 .rich_media_meta_text；新版式该元素是省份定位或发布时间，
        # 直接取会把"湖南"或"2026年10月22日 18:50"当作者写进 author 列，故按形态排除；
        # 遍历所有匹配项，跳过日期/省份，取首个剩余项（避免定位信息污染）。
        for node in soup.select(".rich_media_meta_text"):
            meta_text = _text_of(node)
            if not meta_text:
                continue
            if _CN_DATEISH_RE.search(meta_text) or meta_text in _PROVINCES:
                continue
            author = meta_text
            break
    author = _clean_text(author)
    publish_time = _first_non_empty(
        _epoch_to_iso(_js_var(html, "create_time")),
        _epoch_to_iso(_js_var(html, "ct")),
        _cn_time_to_iso(_text_of(soup.select_one("#publish_time"))),
    )
    digest = _clean_text(_first_non_empty(
        _meta_content(soup, "description"),
        _js_var(html, "msg_desc"),
    ))
    cover = _first_non_empty(
        _js_var(html, "msg_cdn_url"),
        _meta_content(soup, "og:image"),
    )

    content = soup.select_one("#js_content") or soup.select_one(".rich_media_content")
    body_html = content.decode_contents() if content is not None else ""
    body_text = content.get_text("\n") if content is not None else ""

    video_url = _find_video_url(soup, html)
    return {
        "title": title,
        "account": account,
        "account_id": _js_var(html, "biz"),
        "author": author,
        "publish_time": publish_time,
        "digest": digest,
        "body_html": body_html,
        "body_text": body_text,
        "word_count": _count_words(body_text),
        "images": _collect_images(soup, content, url),
        "cover": _absolute(cover, url) if cover else "",
        "video_url": video_url,
        "media_type": "video-meta" if video_url else "text",
    }
