#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L2 按公众号批量历史采集：cookie 复用 mp/profile_ext 翻页抓 general_msg_list。

命令端点（SPEC §5）：
    python l2_fetch_account.py account --biz <__biz> --cookie-file c.json \
        [--offset 0] [--count 10] [--limit 50] [--since/--until YYYY-MM-DD] \
        [--keyword KW] [--out out.jsonl] [--media-dir DIR] [--no-images]
    或经 collect.py 派发：python collect.py account --biz <__biz> ...

验收：AC-05 按 offset 翻页抓 general_msg_list 直到尽头/limit；
      AC-06 ret!=0/限流 -> tenacity 指数退避（共 3 次尝试），超阈即停并报告（EXIT_ERROR）。
合规：仅限采集本人自有或已获明确授权的公众号内容（AC-10 闸由 collect.py / main() 承担）。
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    EXIT_COMPLIANCE,
    EXIT_ENV,
    EXIT_ERROR,
    EXIT_OK,
    EXIT_PARAM,
    EXIT_PARTIAL,
    LEVEL_ENV,
    LEVEL_ERROR,
    LEVEL_INFO,
    LEVEL_PARAM,
    LEVEL_PARTIAL,
    LEVEL_WARN,
    attest,
    emit_event,
    lazy_import,
    load_config,
    sleep_polite,
    write_jsonl,
)
from extract import extract_article  # noqa: E402
from normalize import build_article, validate_article  # noqa: E402

_PROFILE_EXT = "https://mp.weixin.qq.com/mp/profile_ext"
_DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_PAGE_RETRY_ATTEMPTS = 3  # AC-06：初始 + 2 次指数退避；超阈即停并报告
_IMG_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
_CT_EXTS = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp"}


# ------------------------------------------------------------------ cookie
def _load_cookies(path: str) -> dict[str, str]:
    """加载 cookie（三种形态）：①JSON dict {name:value} ②JSON list [{"name","value"}] ③"k=v; k=v" 串。"""
    text = Path(path).read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"cookie 文件为空: {path}")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None
    cookies: dict[str, str] = {}
    if isinstance(data, dict):
        cookies = {str(k).strip(): str(v) for k, v in data.items() if str(k).strip()}
    elif isinstance(data, list):
        for entry in data:
            if isinstance(entry, dict) and str(entry.get("name") or "").strip():
                cookies[str(entry["name"]).strip()] = str(entry.get("value") or "")
    elif data is None:
        for part in text.split(";"):
            name, sep, value = part.strip().partition("=")
            if sep and name.strip():
                cookies[name.strip()] = value.strip()
    else:
        raise ValueError(f"无法识别的 cookie 形态（需 dict/list/k=v 串）: {path}")
    if not cookies:
        raise ValueError(f"cookie 为空或未解析出有效项: {path}")
    return cookies


# ------------------------------------------------------------------ 翻页取数
class _PageRetryable(Exception):
    """profile_ext ret!=0 / 响应非法（cookie 过期或被限频，SPEC §11 已知坑）——可退避重试。"""

    def __init__(self, message: str, ret: Any = None) -> None:
        super().__init__(message)
        self.ret = ret


def _fetch_page(session: Any, biz: str, offset: int, count: int) -> dict:
    """取一页 profile_ext getmsg（独立函数，便于自测注入假响应，不访问真实网络）。"""
    resp = session.get(
        _PROFILE_EXT,
        params={
            "action": "getmsg", "__biz": biz, "f": "json", "offset": offset,
            "count": count, "is_ok": 1, "scene": 124, "uin": 777, "key": 777,
            "pass_ticket": "", "wxtoken": "", "appmsg_token": "",
        },
        headers={"User-Agent": _DESKTOP_UA, "Referer": "https://mp.weixin.qq.com/"},
        timeout=30,
    )
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, dict):
        raise _PageRetryable("profile_ext 响应不是 JSON object")
    ret = payload.get("ret")
    if ret != 0:
        raise _PageRetryable(f"profile_ext ret={ret!r}（cookie 失效或限流）", ret=ret)
    return payload


def _fetch_page_retry(session: Any, biz: str, offset: int, count: int) -> dict:
    """tenacity 指数退避取页：网络错误 / ret!=0 重试；超阈 reraise，由调用方即停并报告。"""
    tenacity = lazy_import("tenacity", "pip install tenacity")
    requests = lazy_import("requests", "pip install requests")

    def _before_sleep(state: Any) -> None:
        emit_event(LEVEL_WARN, "l2.page_retry", offset=offset,
                   attempt=state.attempt_number, error=str(state.outcome.exception()))

    retryer = tenacity.Retrying(
        stop=tenacity.stop_after_attempt(_PAGE_RETRY_ATTEMPTS),
        wait=tenacity.wait_exponential(multiplier=1.0, min=1.0, max=8.0),
        retry=tenacity.retry_if_exception_type((requests.RequestException, _PageRetryable)),
        reraise=True,
        before_sleep=_before_sleep,
    )
    return retryer(_fetch_page, session, biz, offset, count)


def _parse_general_msg_list(payload: dict) -> list[dict]:
    """解 general_msg_list：真实响应是转义 JSON 字符串（二次解包）；兼容直接 list / {"list": [...]}。"""
    raw = payload.get("general_msg_list")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            try:
                raw = json.loads(html.unescape(raw))  # 双重转义兜底
            except json.JSONDecodeError as exc:
                raise ValueError(f"general_msg_list 解析失败: {exc}") from exc
    if raw is None:
        return []
    if isinstance(raw, dict):
        raw = raw.get("list") or []
    if not isinstance(raw, list):
        raise ValueError(f"general_msg_list 类型异常: {type(raw).__name__}")
    return [item for item in raw if isinstance(item, dict)]


def _page_can_continue(payload: dict) -> bool:
    """can_msg_continue==0 即尽头；缺省回退 is_continue，再缺省视为不可继续。"""
    for key in ("can_msg_continue", "is_continue"):
        if key in payload:
            return bool(payload.get(key))
    return False


def _page_plan(payload: dict, offset: int, count: int) -> tuple[list[dict], bool, int]:
    """纯函数：一页响应 -> (list 项, 是否可继续翻页, 下一页 offset)。"""
    next_offset = payload.get("next_offset")
    if isinstance(next_offset, bool) or not isinstance(next_offset, int):
        next_offset = offset + count
    return _parse_general_msg_list(payload), _page_can_continue(payload), next_offset


# ------------------------------------------------------------------ 列表项归一化与过滤（纯函数）
def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _clean_url(value: Any) -> str:
    """profile_ext 的 content_url 常带 HTML 转义（&amp; 等），需反转义。"""
    url = _clean(value)
    return html.unescape(url) if url else ""


def _epoch_or_none(value: Any) -> int | None:
    """发布时间 epoch -> int 秒；容忍毫秒/数字字符串，非法返回 None。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        secs = float(value)
    elif isinstance(value, str) and value.strip().isdigit():
        secs = float(value.strip())
    else:
        return None
    if secs <= 0:
        return None
    return int(secs / 1000) if secs > 1e12 else int(secs)


def _epoch_iso(secs: int | None) -> str:
    """epoch 秒 -> UTC ISO8601（Z 后缀），与 common/extract 时间格式一致。"""
    if not secs:
        return ""
    return datetime.fromtimestamp(secs, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_item(item: dict) -> list[dict]:
    """一条 general_msg_list 项 -> 0..N 篇文章（多图文：父项即首篇 + multi_app_msg_item_list）。

    兼容两种形态：真实嵌套结构（comm_msg_info + app_msg_ext_info）与扁平直取
    （title/link/digest/cover/datetime 在项内，自测用）。只保留有 url 的篇目。
    """
    comm = item.get("comm_msg_info") if isinstance(item.get("comm_msg_info"), dict) else {}
    ext = item.get("app_msg_ext_info") if isinstance(item.get("app_msg_ext_info"), dict) else {}
    when = _epoch_or_none(comm.get("datetime", item.get("datetime")))
    author = _clean(ext.get("author") or item.get("author"))
    account = _clean(item.get("account") or item.get("nickname"))
    parent_cover = _clean_url(ext.get("cover") or item.get("cover"))

    def _one(fields: dict) -> dict:
        return {
            "title": _clean(fields.get("title")),
            "url": _clean_url(fields.get("content_url") or fields.get("link") or fields.get("url")),
            "digest": _clean(fields.get("digest")),
            "cover": _clean_url(fields.get("cover")) or parent_cover,
            "datetime": when,
            "author": author,
            "account": account,
        }

    articles = [_one(ext)] if (ext.get("title") or ext.get("content_url")) else []
    if not articles and (item.get("title") or item.get("link")):
        articles = [_one(item)]
    multi = ext.get("multi_app_msg_item_list")
    if isinstance(multi, list):
        articles.extend(_one(sub) for sub in multi if isinstance(sub, dict))
    return [art for art in articles if art["url"]]


def _match_filters(article: dict, since: date | None, until: date | None, keyword: str) -> tuple[bool, str]:
    """纯函数：时间窗 + 关键词过滤。返回 (保留?, 跳过原因)。

    publish_time 按 UTC 日期与 since/until 比较（含边界）；datetime 缺失时无法验证时间窗，记原因跳过；
    keyword 大小写不敏感命中 title/digest。
    """
    when = article.get("datetime")
    if since or until:
        if not when:
            return False, "发布时间缺失，无法应用 since/until 过滤"
        day = datetime.fromtimestamp(when, tz=timezone.utc).date()
        if since and day < since:
            return False, f"发布日 {day} 早于 since {since}"
        if until and day > until:
            return False, f"发布日 {day} 晚于 until {until}"
    if keyword:
        haystack = f"{article.get('title') or ''}\n{article.get('digest') or ''}".lower()
        if keyword.lower() not in haystack:
            return False, "标题/摘要未命中 keyword"
    return True, ""


# ------------------------------------------------------------------ 媒体落盘
def _guess_ext(url: str, content_type: str = "") -> str:
    parts = urlsplit(url)
    fmt = parse_qs(parts.query).get("wx_fmt", [""])[0].strip().lower()
    if fmt:
        return "." + fmt
    suffix = Path(parts.path).suffix.lower()
    if suffix in _IMG_EXTS:
        return suffix
    return _CT_EXTS.get((content_type or "").split(";")[0].strip().lower(), ".jpg")


def _download_media(session: Any, url: str, dest_stem: Path, referer: str) -> tuple[bool, Path, str]:
    """下载单个媒体（失败不致命）：dest_stem + 推断扩展名落盘，返回 (ok, path, error)。"""
    try:
        resp = session.get(url, headers={"Referer": referer}, timeout=30)
        resp.raise_for_status()
        dest = dest_stem.with_suffix(_guess_ext(url, resp.headers.get("Content-Type", "")))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(resp.content)
        return True, dest, ""
    except Exception as exc:
        return False, dest_stem, str(exc)


def _process_article(
    session: Any,
    article: dict,
    *,
    config: dict,
    media_dir: Path,
    biz: str,
    page_account: str,
    download_images: bool,
) -> tuple[dict, list[str]]:
    """单篇：礼貌延迟 -> GET 文章页 -> extract_article -> 正文/图片落盘 -> build/validate。

    返回 (record, reasons)；单篇失败只记 fail/partial，不中断整轮。
    媒体落盘与 L1 约定一致（schema.md §7）：正文 <media>/<record_id>.html，
    按篇清单 <media>/<record_id>.media.json = {"images":[...], "videos":[]}。
    """
    url = article.get("url") or ""
    reasons: list[str] = []
    sleep_polite(config)
    page_html = ""
    try:
        resp = session.get(url, headers={"Referer": "https://mp.weixin.qq.com/"}, timeout=30)
        resp.raise_for_status()
        resp.encoding = "utf-8"
        page_html = resp.text or ""
    except Exception as exc:
        reasons.append(f"文章页请求失败: {exc}")
    fields = extract_article(page_html, url) if page_html else {}

    record = build_article(
        title=(fields.get("title") or article.get("title") or "(无标题)"),
        url=url,
        collect_layer="account",
        extractor="l2:profile_ext",
        account=(fields.get("account") or article.get("account") or page_account or ""),
        account_id=biz,
        author=(fields.get("author") or article.get("author") or ""),
        publish_time=(_epoch_iso(article.get("datetime")) or fields.get("publish_time") or None),
        digest=(article.get("digest") or fields.get("digest") or ""),
        media_type=(fields.get("media_type") or "text"),
        cover_url=(fields.get("cover") or article.get("cover") or None),
        video_url=(fields.get("video_url") or None),
        word_count=fields.get("word_count"),
    )
    rid = record["record_id"]

    body_html = fields.get("body_html") or ""
    if body_html.strip():
        body_path = media_dir / f"{rid}.html"
        body_path.parent.mkdir(parents=True, exist_ok=True)
        body_path.write_text(body_html, encoding="utf-8")
        record["body_ref"] = str(body_path)
    else:
        record["status"] = "fail"
        record["fidelity"] = "partial"
        reasons.append("正文缺失（body 为空）")

    # 图片：下载失败不致命（保留 url、无 local_path，整体降级 partial）；--no-images 只记 URL
    images_out: list[dict] = []
    for i, img in enumerate(fields.get("images") or []):
        img_url = (img.get("url") or "").strip()
        if not img_url:
            continue
        if download_images:
            ok, dest, _err = _download_media(session, img_url, media_dir / "images" / rid / f"{i:03d}", url)
            if ok:
                images_out.append({"url": img_url, "local_path": str(dest)})
                continue
            reasons.append(f"图片下载失败: {img_url}")
        images_out.append({"url": img_url})

    # 按篇媒体清单（schema.md §7，与 L1 一致）；rid 由 build 派生，故此处回填计数与引用
    media_json = media_dir / f"{rid}.media.json"
    media_json.parent.mkdir(parents=True, exist_ok=True)
    media_json.write_text(
        json.dumps({"images": images_out, "videos": []}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    record["images_count"] = len(images_out)
    record["images_ref"] = str(media_json) if images_out else None

    if record["status"] != "fail" and reasons:
        record["status"] = "partial"
        record["fidelity"] = "partial"
    status, val_reasons = validate_article(record)
    record["status"] = status
    reasons.extend(val_reasons)
    return record, reasons


# ------------------------------------------------------------------ 参数与媒体目录
def _parse_day(value: str | None, flag: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError(f"{flag} 需为 YYYY-MM-DD: {value!r}") from exc


def _resolve_media_dir(args: Any) -> Path:
    """--media-dir 优先；否则 <out 去扩展名>.media/；stdout 场景落 l2_account.media/。"""
    if getattr(args, "media_dir", None):
        base = Path(args.media_dir).expanduser()
    elif getattr(args, "out", None):
        base = Path(args.out).expanduser().with_suffix(".media")
    else:
        base = Path("l2_account.media")
    return base.resolve()


# ------------------------------------------------------------------ 子命令注册
def register(subparsers: Any) -> None:
    """注册子命令 "account"（collect.py 派发契约：set_defaults(func=run)）。"""
    parser = subparsers.add_parser(
        "account",
        help="L2 按公众号批量历史采集（cookie 复用 profile_ext 翻页）",
        description="L2：按 __biz 翻页抓 mp/profile_ext general_msg_list，逐篇提取并归一化为 25 列 JSONL（AC-05/AC-06）。",
    )
    # --config/--yes 同时挂主解析器（collect.py 派发与本文件独立入口共用）；
    # 子命令再挂一份（SUPPRESS 默认不覆盖），使 `account ... --yes` 后置写法也可用
    parser.add_argument("--config", default=argparse.SUPPRESS, help="YAML 配置路径（默认内置 DEFAULT_CONFIG）")
    parser.add_argument("--yes", action="store_true", default=argparse.SUPPRESS,
                        help="合规闸：确认已获授权（非交互/自动化必填）")
    parser.add_argument("--biz", required=True, help="目标公众号 __biz（profile_ext 必需）")
    parser.add_argument("--cookie-file", default=None,
                        help="cookie 文件：JSON dict / JSON list[{'name','value'}] / 'k=v; k=v' 串（默认取 config l2.cookie_file）")
    parser.add_argument("--offset", type=int, default=0, help="起始翻页 offset（默认 0）")
    parser.add_argument("--count", type=int, default=10, help="每页条数（默认 10）")
    parser.add_argument("--limit", type=int, default=50, help="总篇数上限（默认 50）")
    parser.add_argument("--since", default=None, metavar="YYYY-MM-DD", help="仅保留该日起（含）发布的文章")
    parser.add_argument("--until", default=None, metavar="YYYY-MM-DD", help="仅保留该日止（含）发布的文章")
    parser.add_argument("--keyword", default=None, help="标题或摘要包含该关键词才保留（大小写不敏感）")
    parser.add_argument("--out", default=None, help="JSONL 输出路径（默认 stdout）")
    parser.add_argument("--media-dir", default=None, help="媒体目录（默认 <out 去扩展名>.media/）")
    parser.add_argument("--download-images", dest="download_images", action="store_true", default=True,
                        help="下载正文图片到媒体目录（默认开启）")
    parser.add_argument("--no-images", dest="download_images", action="store_false", help="关闭图片下载")
    parser.set_defaults(func=run)


# ------------------------------------------------------------------ 主流程
def run(args: Any) -> int:
    """L2 主流程（collect.py account / 独立入口共用）。"""
    keyword = (getattr(args, "keyword", None) or "").strip()
    try:
        since = _parse_day(getattr(args, "since", None), "--since")
        until = _parse_day(getattr(args, "until", None), "--until")
    except ValueError as exc:
        emit_event(LEVEL_PARAM, "l2.param", error=str(exc))
        return EXIT_PARAM
    if args.offset < 0 or args.count < 1 or args.limit < 1:
        emit_event(LEVEL_PARAM, "l2.param", error="--offset 必须 >= 0，--count/--limit 必须 >= 1")
        return EXIT_PARAM
    if since and until and until < since:
        emit_event(LEVEL_PARAM, "l2.param", error="--until 早于 --since")
        return EXIT_PARAM

    try:
        config = load_config(getattr(args, "config", None))
    except ValueError as exc:
        emit_event(LEVEL_PARAM, "l2.config", error=str(exc))
        return EXIT_PARAM
    except RuntimeError as exc:
        emit_event(LEVEL_ENV, "l2.env", error=str(exc))
        return EXIT_ENV

    cookie_file = (getattr(args, "cookie_file", None)
                   or (config.get("l2") or {}).get("cookie_file") or "").strip()
    if not cookie_file:
        emit_event(LEVEL_PARAM, "l2.cookie",
                   error="未提供 --cookie-file，且 config l2.cookie_file 为空")
        return EXIT_PARAM
    try:
        cookies = _load_cookies(cookie_file)
    except (OSError, ValueError) as exc:
        emit_event(LEVEL_PARAM, "l2.cookie", error=str(exc), path=cookie_file)
        return EXIT_PARAM

    # 依赖预检（缺失 -> EXIT_ENV，先于任何网络动作）
    try:
        requests = lazy_import("requests", "pip install requests")
        lazy_import("tenacity", "pip install tenacity")
        lazy_import("bs4", "pip install beautifulsoup4 lxml")
    except RuntimeError as exc:
        emit_event(LEVEL_ENV, "l2.env", error=str(exc))
        return EXIT_ENV

    media_dir = _resolve_media_dir(args)

    session = requests.Session()
    session.cookies.update(cookies)
    session.headers.update({"User-Agent": _DESKTOP_UA})

    stats = {"pages": 0, "total": 0, "ok": 0, "partial": 0, "fail": 0}
    outcome = {"code": EXIT_OK}

    def _generate():
        offset = args.offset
        fetched = 0
        page_account = ""
        while True:
            # AC-06：ret!=0/网络错误 -> 退避重试；超阈即停并报告，不无限重试
            try:
                payload = _fetch_page_retry(session, args.biz, offset, args.count)
            except _PageRetryable as exc:
                emit_event(LEVEL_ERROR, "l2.ret", ret=exc.ret, offset=offset,
                           attempts=_PAGE_RETRY_ATTEMPTS, error=str(exc))
                outcome["code"] = EXIT_ERROR
                return
            except requests.RequestException as exc:
                emit_event(LEVEL_ERROR, "l2.network", offset=offset,
                           attempts=_PAGE_RETRY_ATTEMPTS, error=str(exc))
                outcome["code"] = EXIT_ERROR
                return
            stats["pages"] += 1
            page_account = _clean(payload.get("nickname") or payload.get("account")) or page_account
            try:
                items, can_continue, next_offset = _page_plan(payload, offset, args.count)
            except ValueError as exc:
                emit_event(LEVEL_WARN, "l2.parse", offset=offset, error=str(exc))
                break
            emit_event(LEVEL_INFO, "l2.page", offset=offset, items=len(items),
                       can_continue=can_continue, fetched=fetched)
            hit_limit = False
            for item in items:
                arts = _normalize_item(item)
                if not arts:
                    emit_event(LEVEL_INFO, "l2.skip", offset=offset, reason="列表项缺 title/content_url")
                    continue
                for art in arts:
                    if fetched >= args.limit:
                        hit_limit = True
                        break
                    fetched += 1
                    stats["total"] += 1
                    keep, why = _match_filters(art, since, until, keyword)
                    if not keep:
                        emit_event(LEVEL_INFO, "l2.skip", url=art.get("url"), reason=why)
                        continue
                    record, reasons = _process_article(
                        session, art, config=config, media_dir=media_dir, biz=args.biz,
                        page_account=page_account, download_images=args.download_images,
                    )
                    stats[record["status"]] = stats.get(record["status"], 0) + 1
                    if record["status"] == "fail":
                        emit_event(LEVEL_WARN, "l2.article_fail", record_id=record["record_id"],
                                   url=record.get("url"), reasons=reasons)
                    elif record["status"] == "partial":
                        emit_event(LEVEL_PARTIAL, "l2.article_partial", record_id=record["record_id"],
                                   url=record.get("url"), reasons=reasons)
                    yield record
                if hit_limit:
                    break
            if hit_limit or fetched >= args.limit or not items or not can_continue:
                break
            offset = next_offset
            sleep_polite(config)

    written: int | None = None
    try:
        written = write_jsonl(getattr(args, "out", None), _generate())
    except Exception as exc:  # 未预期错误：不静默，保留已写部分
        emit_event(LEVEL_ERROR, "l2.abort", error=str(exc))
        outcome["code"] = EXIT_ERROR

    emit_event(LEVEL_INFO, "l2.done", pages=stats["pages"], total=stats["total"],
               ok=stats["ok"], partial=stats["partial"], fail=stats["fail"], written=written)
    if outcome["code"] != EXIT_OK:
        return outcome["code"]
    # 零产出：一篇都没成功（ok==0 且 partial==0）时不存在"部分成功"，按 error 上报；
    # partial>0 表示正文已抓到但降级，仍属"有产出"，必须落在 EXIT_PARTIAL。
    if stats["total"] and stats["ok"] == 0 and stats["partial"] == 0:
        emit_event(LEVEL_ERROR, "l2.zero_yield", total=stats["total"], fail=stats["fail"])
        return EXIT_ERROR
    if stats["fail"] or stats["partial"]:
        return EXIT_PARTIAL
    if stats["total"] == 0:
        emit_event(LEVEL_WARN, "l2.empty", biz=args.biz,
                   hint="该号无历史文章，或 cookie 失效/被限流")
    return EXIT_OK


# ------------------------------------------------------------------ 独立入口与离线自测
def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", default=argparse.SUPPRESS, help="YAML 配置路径（默认内置 DEFAULT_CONFIG）")
    common.add_argument("--yes", action="store_true", default=argparse.SUPPRESS,
                        help="合规闸：确认已获授权（非交互/自动化必填）")
    parser = argparse.ArgumentParser(prog="l2_fetch_account.py", description=__doc__, parents=[common])
    parser.add_argument("--selfcheck", action="store_true", help="运行内置离线自测（不访问网络）后退出")
    sub = parser.add_subparsers(dest="mode", metavar="<mode>")
    register(sub)
    parser.set_defaults(func=None)
    return parser


_TOP_FLAGS = ("--config", "--yes", "--selfcheck")


def main(argv: list[str] | None = None) -> int:
    tokens = list(sys.argv[1:] if argv is None else argv)
    if tokens and tokens[0] != "account" and not tokens[0].startswith(_TOP_FLAGS) \
            and tokens[0] not in ("-h", "--help"):
        tokens = ["account"] + tokens  # 直跑省略 mode 前缀时自动补全
    parser = build_parser()
    args = parser.parse_args(tokens)
    if getattr(args, "selfcheck", False):
        return _selfcheck()
    if not getattr(args, "mode", None):
        parser.print_help()
        return EXIT_PARAM
    if not attest(args):
        return EXIT_COMPLIANCE
    handler = getattr(args, "func", None)
    if handler is None:
        parser.print_help()
        return EXIT_PARAM
    return int(handler(args) or 0)


def _selfcheck() -> int:
    """离线自测（不访问网络）：假 profile_ext JSON 验证翻页终止 / limit 截止 / 过滤逻辑。"""
    pages = {
        0: {"ret": 0, "can_msg_continue": 1, "next_offset": 10, "general_msg_list": json.dumps([
            {"title": "甲文章", "link": "https://mp.weixin.qq.com/s?__biz=B1&mid=1&idx=1&sn=a", "digest": "摘要甲", "datetime": 1704067200},
            {"title": "旧文章", "link": "https://mp.weixin.qq.com/s?__biz=B1&mid=2&idx=1&sn=b", "digest": "过期", "datetime": 1000000000}])},
        10: {"ret": 0, "can_msg_continue": 0, "next_offset": 20, "general_msg_list": json.dumps([
            {"title": "乙文章", "link": "https://mp.weixin.qq.com/s?__biz=B1&mid=3&idx=1&sn=c", "digest": "关键词乙", "datetime": 1735689600}])},
    }

    class _Resp:
        def __init__(self, payload): self._p = payload
        def raise_for_status(self): return None
        def json(self): return self._p

    class _Session:
        def __init__(self): self.calls = []
        def get(self, url, params=None, headers=None, timeout=None):
            self.calls.append(params["offset"])
            return _Resp(pages[params["offset"]])

    def _crawl(limit):
        sess, got, offset = _Session(), [], 0
        while True:
            items, go, nxt = _page_plan(_fetch_page(sess, "B1", offset, 10), offset, 10)
            for it in items:
                arts = _normalize_item(it)
                if len(got) + len(arts) > limit:
                    break
                got.extend(arts)
            if len(got) >= limit or not items or not go:
                break
            offset = nxt
        return sess, got

    sess, got = _crawl(50)
    assert [a["title"] for a in got] == ["甲文章", "旧文章", "乙文章"], got
    assert sess.calls == [0, 10], sess.calls  # 翻到 can_msg_continue=0 为止，共 2 页
    sess2, got2 = _crawl(2)
    assert len(got2) == 2 and sess2.calls == [0], sess2.calls  # limit=2：首页即止，不请求第二页
    assert _match_filters(got[1], date(2024, 1, 1), None, None)[0] is False  # 2001 年旧文被 since 挡掉
    assert _match_filters(got[0], date(2024, 1, 1), None, None)[0] is True   # 2024-01-01 当天含边界
    assert _match_filters(got[2], None, None, "乙")[0] is True               # keyword 命中标题
    assert _match_filters(got[2], None, None, "不存在")[0] is False          # keyword 不命中
    print("selfcheck OK: 翻页 2 页/3 篇终止于 can_msg_continue=0；limit=2 首页即止；since/keyword 过滤符合预期")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
