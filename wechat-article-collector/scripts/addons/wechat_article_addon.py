# -*- coding: utf-8 -*-
"""wechat-article-collector L3 附加脚本：mitmproxy 捕获 PC 微信文章页 HTML。

加载方式（由 l3_drive_wechat.py 编排，需管理员运行 mitmdump）：
    mitmdump --mode local:WeChatAppEx.exe -s <本文件> \\
              --set listen_port=<port> --set confdir=<用户目录>/.mitmproxy

行为：
    - 命中条件：flow.request.pretty_host 含 "mp.weixin.qq.com"，且 path 以 "/s" 开头
      或含 "/mp/appmsg"，且 response content-type 含 "text/html"；
    - 动作：response body 写入 <WECHAT_CAPTURE_DIR>/<md5(url) 前 16 位>.html（同文件覆盖写），
      并向 <WECHAT_CAPTURE_DIR>/_meta.jsonl 追加 {"url","title","ts"} 一行；
    - 采集目录取环境变量 WECHAT_CAPTURE_DIR，缺省 "./wechat-capture"；
    - title 从 HTML <title> 正则提取；ts 为 UTC ISO8601（秒级、Z 后缀）。

契约约束：仅用标准库（hashlib/json/os/re/datetime）；mitmproxy -s 加载时 sys.path
只有本文件所在目录，禁止 import 兄弟模块（common/normalize/extract 等）。
异常静默跳过（不拖垮 mitmdump 进程），由 l3 编排侧按"缺文件/缺 meta"发现与重试。

与 l3_drive_wechat.py 的文件名约定：md5(request url) 前 16 位 + ".html"（两侧必须一致）。
"""
import hashlib
import json
import os
import re
from datetime import datetime, timezone

_TARGET_HOST = "mp.weixin.qq.com"
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_WHITESPACE_RE = re.compile(r"\s+")


def _capture_dir() -> str:
    """采集目录：环境变量 WECHAT_CAPTURE_DIR，缺省 ./wechat-capture。"""
    return os.environ.get("WECHAT_CAPTURE_DIR") or "./wechat-capture"


def _file_name_for(url: str) -> str:
    """URL -> 捕获文件名：md5(url) 前 16 位 + .html（与 l3 侧 _read_meta 约定一致）。"""
    return hashlib.md5(url.encode("utf-8")).hexdigest()[:16] + ".html"


def _title_from_html(body: bytes) -> str:
    """从 <title> 正则提取标题并折叠空白；无 <title> 返回空串。"""
    match = _TITLE_RE.search(body.decode("utf-8", "replace"))
    if not match:
        return ""
    return _WHITESPACE_RE.sub(" ", match.group(1)).strip()


def _is_article_flow(flow) -> bool:
    """命中判定：公众号文章页 HTML 响应（mp.weixin.qq.com + /s* 或 /mp/appmsg* + text/html）。"""
    request = getattr(flow, "request", None)
    response = getattr(flow, "response", None)
    if request is None or response is None:
        return False
    if _TARGET_HOST not in (getattr(request, "pretty_host", "") or "").lower():
        return False
    path = getattr(request, "path", "") or ""
    if not (path.startswith("/s") or "/mp/appmsg" in path):
        return False
    content_type = (response.headers.get("content-type", "") or "").lower()
    return "text/html" in content_type


def response(flow) -> None:
    """mitmproxy response 钩子：命中文章页则落盘 HTML 并追加 meta 一行。"""
    if not _is_article_flow(flow):
        return
    try:
        body = flow.response.content
        url = flow.request.url
        directory = _capture_dir()
        os.makedirs(directory, exist_ok=True)
        # 同文件覆盖写（重复打开同一文章不产生新文件，l3 侧按文件名去重）
        with open(os.path.join(directory, _file_name_for(url)), "wb") as handle:
            handle.write(body)
        record = {
            "url": url,
            "title": _title_from_html(body),
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        with open(os.path.join(directory, "_meta.jsonl"), "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:  # 防御性：addon 异常不得拖垮 mitmdump
        log = globals().get("ctx")
        if log is not None:
            try:
                log.log.warn("wechat_article_addon 捕获失败: %s" % exc)
            except Exception:
                pass
