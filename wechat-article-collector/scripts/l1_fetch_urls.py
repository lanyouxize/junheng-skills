#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L1 采集层：Playwright 直接抓取公众号文章 URL（单条 / 批量）。

模块契约（SPEC §4 / team-lead 任务书）：
  - register(subparsers) 注册子命令 "url"，set_defaults(func=run)；
  - run(args) -> int 返回进程退出码（common.EXIT_*）；
  - 顶层仅标准库 + 本地契约模块（common / normalize / extract）；
    playwright / requests / bs4 一律函数内 lazy_import，缺依赖时
    emit_event(LEVEL_ENV, ...) 并返回 EXIT_ENV，模块 import 本身永不失败；
  - 每条 URL 独立产出 25 列记录（status=ok/partial/fail），单条失败不中断整批；
  - 退出码：全部 ok -> EXIT_OK；有产出但存在 partial / fail -> EXIT_PARTIAL；
    全部 fail（ok==0 且 partial==0，零产出）-> EXIT_ERROR；
    无输入 -> EXIT_PARAM；playwright/requests 缺失 -> EXIT_ENV。

用法（独立自检）：
    python l1_fetch_urls.py url --urls "https://mp.weixin.qq.com/s/XXXX" [--out r.jsonl]
    python l1_fetch_urls.py url --url-file urls.txt --media-dir ./media --no-images
统一入口：
    python collect.py url --urls ... --yes [--config config.yaml]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

from common import (
    BROWSER_UA,
    EXIT_ENV,
    EXIT_ERROR,
    EXIT_OK,
    EXIT_PARAM,
    EXIT_PARTIAL,
    LEVEL_ENV,
    LEVEL_ERROR,
    LEVEL_INFO,
    LEVEL_PARAM,
    LEVEL_WARN,
    download_file,
    emit_event,
    guess_image_ext,
    lazy_import,
    load_config,
    sleep_polite,
    write_jsonl,
)
from extract import extract_article
from normalize import build_article, canonicalize_url, validate_article

EXTRACTOR = "l1:playwright"
COLLECT_LAYER = "url"

# 桌面 Chrome UA 与扩展名推断统一由 common 提供（L1/L2/L3 单一来源）
_BROWSER_UA = BROWSER_UA
_SCROLL_ROUNDS = 3          # 滚动触发懒加载的轮数
_SCROLL_INTERVAL_MS = 1000  # 每轮间隔 ~1s

# 限流软封重试：正文缺失但疑似"head 已加载、正文被拦"时自动重抓，避免偶发风控丢文。
RETRY_ATTEMPTS = 2          # 默认重试次数（--retries 可覆盖；0 关闭）
RETRY_BACKOFF_BASE = 5.0    # 首次重试额外退避（秒）
RETRY_BACKOFF_FACTOR = 2.0  # 退避倍增
# 命中即视为可重试软封（区别于真·空页 / 验证码硬封"环境异常"，后者不重试）。
_RETRYABLE_KEYWORDS = (
    "访问过于频繁", "操作过于频繁", "请稍候", "系统繁忙",
    "稍后再试", "网络繁忙", "正在加载",
)


class _EnvMissingError(RuntimeError):
    """playwright / requests / bs4 等运行时依赖缺失（区别于单条抓取失败）。"""


# ------------------------------------------------------------------ 参数注册
def register(subparsers: argparse._SubParsersAction) -> None:
    """注册子命令 "url"（供 collect.py 统一入口与本文件独立 main 复用）。"""
    parser = subparsers.add_parser(
        "url",
        help="L1：Playwright 直接抓取公众号文章 URL（单条/批量）",
        description="L1 采集层：Playwright 渲染公众号文章页并落盘正文/图片，输出 25 列 JSONL 记录。",
    )
    parser.add_argument("--urls", default="", help="逗号分隔的多个文章 URL")
    parser.add_argument("--url-file", default="", help="每行一个 URL 的文本文件（# 开头为注释行）")
    parser.add_argument("--out", default="", help="JSONL 输出路径（默认写 stdout）")
    parser.add_argument(
        "--media-dir", default="",
        help="媒体目录（默认 '<out 去扩展名>.media/'；--out 省略时为 ./wechat-collected-media/）",
    )
    parser.add_argument("--timeout", type=int, default=30, help="导航/图片下载超时秒（默认 30）")
    parser.add_argument(
        "--retries", type=int, default=RETRY_ATTEMPTS,
        help="正文为空但疑似限流软封时的重试次数（默认 2；0 关闭）",
    )
    parser.add_argument(
        "--headless", action=argparse.BooleanOptionalAction, default=True,
        help="无头浏览器模式（默认开启；--no-headless 显示浏览器界面）",
    )
    parser.add_argument(
        "--no-images", dest="download_images", action="store_false", default=True,
        help="只记录图片 URL 不下载（默认下载）",
    )
    parser.add_argument(
        "--download-images", dest="download_images", action="store_true", default=True,
        help="下载正文图片到媒体目录（默认行为，显式声明用）",
    )
    parser.set_defaults(func=run)


# ------------------------------------------------------------------ 主流程
def run(args: argparse.Namespace) -> int:
    """执行 L1 采集，返回退出码（EXIT_OK / EXIT_PARTIAL / EXIT_PARAM / EXIT_ENV / EXIT_ERROR）。"""
    urls = _collect_urls(args)
    if not urls:
        emit_event(
            LEVEL_PARAM, "l1.no_input",
            reason="--urls / --url-file / stdin 至少提供一个文章 URL",
        )
        return EXIT_PARAM

    config = load_config(getattr(args, "config", ""))
    media_dir = _resolve_media_dir(args)
    try:
        media_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        emit_event(LEVEL_ERROR, "l1.media_dir_error", media_dir=str(media_dir), error=str(exc))
        return EXIT_ERROR

    records: list[dict] = []
    env_missing = False
    for index, url in enumerate(urls):
        if index:
            sleep_polite(config)  # URL 之间的礼貌间隔（频率控制，跳过后台风控）
        try:
            record = _process_url(url, args, config, media_dir)
        except _EnvMissingError as exc:
            emit_event(LEVEL_ENV, "l1.env_missing", url=url, error=str(exc))
            env_missing = True
            break
        records.append(record)
        _emit_record_event(record)

    try:
        write_jsonl(getattr(args, "out", "") or None, records)
    except OSError as exc:
        emit_event(LEVEL_ERROR, "l1.write_failed", out=str(getattr(args, "out", "")), error=str(exc))
        return EXIT_ERROR

    counts = {"ok": 0, "partial": 0, "fail": 0}
    for record in records:
        status = str(record.get("status") or "fail")
        counts[status] = counts.get(status, 0) + 1
    emit_event(
        LEVEL_INFO, "l1.done",
        total=len(records), ok=counts["ok"], partial=counts["partial"], fail=counts["fail"],
    )

    if env_missing:
        return EXIT_ENV
    # 零产出 ≠ 部分成功：全 fail（ok==0 且 partial==0）时不存在"部分"，必须报 error。
    # partial>0 表示正文已抓到、仅附件等降级，仍属有产出，继续走 EXIT_PARTIAL。
    if records and counts["ok"] == 0 and counts["partial"] == 0:
        emit_event(LEVEL_ERROR, "l1.zero_yield", total=len(records), fail=counts["fail"])
        return EXIT_ERROR
    if counts["fail"] or counts["partial"]:
        return EXIT_PARTIAL
    return EXIT_OK


def _process_url(url: str, args: argparse.Namespace, config: dict, media_dir: Path) -> dict:
    """处理单个 URL：域名闸 -> 抓取 -> 解析 -> 落盘 -> 组装 25 列记录。"""
    canonical = canonicalize_url(url)
    if canonical is None:
        # 非 mp.weixin.qq.com 域名或非法 URL：记 fail，不需要浏览器，不中断整批
        return _fail_record(url, None, (
            f"invalid url: 非 mp.weixin.qq.com 域名或 URL 非法"
            f"（canonicalize_url 返回 None）: {url}"
        ))

    # record_id 与 normalize 内派生规则一致：uuid5(NAMESPACE_URL, canonical)
    record_id = str(uuid.uuid5(uuid.NAMESPACE_URL, canonical))

    try:
        html = _fetch_html(url, args)
    except _EnvMissingError:
        raise
    except Exception as exc:  # 导航超时 / 浏览器崩溃等：单条失败，不中断整批
        return _fail_record(url, record_id, f"页面抓取失败: {exc}")

    try:
        fields, fail_reason = _extract_with_retry(url, html, args, config, record_id)
    except _EnvMissingError:
        raise
    except RuntimeError as exc:  # bs4/lxml 等解析依赖缺失 -> 环境问题
        raise _EnvMissingError(str(exc)) from exc
    except Exception as exc:
        return _fail_record(url, record_id, f"页面解析失败: {exc}")
    if fields is None:
        # 重试后仍空（或解析异常兜底）→ 判 fail，fail_reason 已含原因
        return _fail_record(url, record_id, fail_reason or "empty body: 正文缺失或页面未渲染")

    body_html = (fields.get("body_html") or "").strip()
    if not body_html:
        return _fail_record(
            url, record_id, fail_reason or "empty body: 正文缺失或页面未渲染", fields=fields,
        )

    # 1) 正文落盘
    html_path = media_dir / f"{record_id}.html"
    html_path.write_text(body_html, encoding="utf-8")

    # 2) 图片（下载失败不致命：保留 url、无 local_path，整体降级 partial）
    images_out, image_failures = _handle_images(
        fields.get("images") or [], record_id, media_dir, args, config,
    )

    # 3) 媒体清单
    media_json = media_dir / f"{record_id}.media.json"
    media_json.write_text(
        json.dumps({"images": images_out, "videos": []}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 4) 组装 + 校验
    record = build_article(
        title=fields["title"],
        url=url,
        collect_layer=COLLECT_LAYER,
        extractor=EXTRACTOR,
        account=fields["account"],
        account_id=fields["account_id"],
        author=fields["author"],
        publish_time=fields["publish_time"],
        digest=fields["digest"],
        media_type=fields["media_type"],
        cover_url=fields["cover"] or None,
        video_url=fields["video_url"] or None,
        body_ref=str(html_path),
        media_ref=str(media_json),
        images=images_out,
        videos=[],
        word_count=fields["word_count"],
        record_id=record_id,
    )
    status, reasons = validate_article(record)
    record["status"] = status
    if status == "fail":
        record["fail_reason"] = "; ".join(reasons)
    elif image_failures:
        record["status"] = "partial"
        record["fail_reason"] = "; ".join([*(reasons or []), *image_failures])
    return record


def _is_retryable_empty(html: str) -> bool:
    """正文缺失但是否值得重试：真文章 head 已加载（og:title 存在且页面不小）
    或命中明确限流/繁忙提示。验证码硬封（环境异常）无 og:title 且不命中关键词，不重试。"""
    if "og:title" in html and len(html) >= 8000:
        return True
    for kw in _RETRYABLE_KEYWORDS:
        if kw in html:
            return True
    return False


def _extract_with_retry(
    url: str, html: str, args: argparse.Namespace, config: dict, record_id: str | None,
) -> tuple[dict | None, str | None]:
    """抽取正文；遇限流软封（head 已加载但正文被拦）自动重试。

    返回 (fields, fail_reason_or_None)。fields 为 None 表示最终失败（reason 含原因）。
    """
    fields = extract_article(html, url)
    if (fields.get("body_html") or "").strip():
        return fields, None
    # 正文缺失但不可重试（真·空页 / 验证码硬封）→ 直接失败，不浪费请求
    if not _is_retryable_empty(html):
        return None, "empty body: 正文缺失或页面未渲染"
    max_retry = int(getattr(args, "retries", RETRY_ATTEMPTS))
    last_reason = "empty body: 重试后仍缺失正文"
    for attempt in range(1, max_retry + 1):
        delay = RETRY_BACKOFF_BASE * (RETRY_BACKOFF_FACTOR ** (attempt - 1))
        emit_event(
            LEVEL_WARN, "l1.retry_empty", url=url, record_id=record_id,
            attempt=attempt, delay=int(delay),
            reason="限流软封疑似：head 已加载但正文缺失，重试抓取",
        )
        sleep_polite(config)
        time.sleep(delay)
        try:
            html2 = _fetch_html(url, args)
        except _EnvMissingError:
            raise  # 环境缺失必须上抛 -> EXIT_ENV
        except Exception as exc:
            last_reason = f"页面抓取失败（重试 {attempt}）: {exc}"
            break
        fields = extract_article(html2, url)
        if (fields.get("body_html") or "").strip():
            return fields, None
    return None, last_reason


def _fail_record(
    url: str, record_id: str | None, reason: str, fields: dict | None = None,
) -> dict:
    """构造 fail 记录（保留已提取到的元数据，便于排查）。"""
    fields = fields or {}
    record = build_article(
        title=fields.get("title") or "",
        url=url,
        collect_layer=COLLECT_LAYER,
        extractor=EXTRACTOR,
        account=fields.get("account") or "",
        account_id=fields.get("account_id") or "",
        author=fields.get("author") or "",
        publish_time=fields.get("publish_time") or "",
        digest=fields.get("digest") or "",
        media_type=fields.get("media_type") or "text",
        cover_url=fields.get("cover") or None,
        video_url=fields.get("video_url") or None,
        record_id=record_id,
    )
    record["status"] = "fail"
    record["fail_reason"] = reason
    return record


def _emit_record_event(record: dict) -> None:
    """单条记录进度事件；fail 逐条 emit warn（契约 §8）。"""
    if record.get("status") == "fail":
        emit_event(
            LEVEL_WARN, "l1.url_fail",
            url=record.get("url", ""),
            record_id=record.get("record_id"),
            fail_reason=record.get("fail_reason", ""),
        )
    else:
        emit_event(
            LEVEL_INFO, "l1.url_done",
            url=record.get("url", ""),
            record_id=record.get("record_id"),
            status=record.get("status"),
        )


# ------------------------------------------------------------------ 浏览器抓取
def _fetch_html(url: str, args: argparse.Namespace) -> str:
    """Playwright 渲染文章页并返回 HTML（每次调用独立浏览器实例，互不污染）。"""
    try:
        sync_api = lazy_import(
            "playwright.sync_api",
            "pip install playwright && playwright install chromium",
        )
    except RuntimeError as exc:
        raise _EnvMissingError(str(exc)) from exc

    with sync_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=bool(getattr(args, "headless", True)))
        try:
            context = browser.new_context(
                user_agent=_BROWSER_UA,
                viewport={"width": 1280, "height": 800},
            )
            page = context.new_page()
            page.goto(url, wait_until="networkidle", timeout=int(args.timeout) * 1000)
            for _ in range(_SCROLL_ROUNDS):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(_SCROLL_INTERVAL_MS)
            return page.content()
        finally:
            context.close()
            browser.close()


# ------------------------------------------------------------------ 图片下载
def _handle_images(
    images: list[dict], record_id: str, media_dir: Path, args: argparse.Namespace, config: dict,
) -> tuple[list[dict], list[str]]:
    """下载正文图片到 media_dir/images/<record_id>/<序号>.<ext>。

    返回 (清单, 失败原因列表)；--no-images 时只记 URL；单图失败不致命。
    """
    if not images:
        return [], []
    if not getattr(args, "download_images", True):
        kept = [{"url": (img.get("url") or "").strip()} for img in images]
        return [item for item in kept if item["url"]], []

    try:
        requests = lazy_import("requests", "pip install requests")
    except RuntimeError as exc:
        raise _EnvMissingError(str(exc)) from exc

    image_root = media_dir / "images" / record_id
    out: list[dict] = []
    failures: list[str] = []
    last = len(images) - 1
    for index, image in enumerate(images):
        image_url = (image.get("url") or "").strip()
        if not image_url:
            continue
        local_path = image_root / f"{index:04d}.{_guess_image_ext(image_url)}"
        try:
            _download_image(requests, image_url, local_path, int(args.timeout))
        except Exception as exc:  # 单图失败不致命：保留 url、无 local_path
            failures.append(f"图片下载失败[{index}] {image_url}: {exc}")
            out.append({"url": image_url})
        else:
            out.append({"url": image_url, "local_path": str(local_path)})
        if index < last:
            sleep_polite(config)  # 每次下载之间的礼貌间隔
    return out, failures


def _download_image(requests, url: str, dest: Path, timeout: int) -> None:
    """用桌面 UA + 公众号 Referer 下载单张图片（实现见 common.download_file）。"""
    download_file(requests, url, dest, timeout)


def _guess_image_ext(url: str) -> str:
    """推断图片扩展名（实现见 common.guess_image_ext，L1/L2/L3 共用一套规则）。"""
    return guess_image_ext(url)


# ------------------------------------------------------------------ 输入 / 输出路径
def _collect_urls(args: argparse.Namespace) -> list[str]:
    """汇总 --urls / --url-file / stdin 三路输入，按 canonical 键去重（保序）。"""
    raw: list[str] = []
    urls_arg = (getattr(args, "urls", "") or "").strip()
    if urls_arg:
        raw.extend(part.strip() for part in urls_arg.split(","))

    url_file = (getattr(args, "url_file", "") or "").strip()
    if url_file:
        try:
            text = Path(url_file).read_text(encoding="utf-8")
        except OSError as exc:
            emit_event(LEVEL_WARN, "l1.url_file_unreadable", path=url_file, error=str(exc))
        else:
            raw.extend(
                line.strip()
                for line in text.splitlines()
                if line.strip() and not line.strip().startswith("#")
            )

    if not raw and not urls_arg and not url_file:
        stdin = sys.stdin
        if stdin is not None and not stdin.isatty():
            raw.extend(
                line.strip()
                for line in stdin
                if line.strip() and not line.strip().startswith("#")
            )

    seen: set[str] = set()
    unique: list[str] = []
    for url in raw:
        if not url:
            continue
        key = canonicalize_url(url) or url  # 同一篇文章的不同追踪参数只采一次
        if key in seen:
            continue
        seen.add(key)
        unique.append(url)
    return unique


def _resolve_media_dir(args: argparse.Namespace) -> Path:
    """媒体目录：--media-dir > '<out 去扩展名>.media/' > ./wechat-collected-media/。"""
    explicit = (getattr(args, "media_dir", "") or "").strip()
    if explicit:
        return Path(explicit)
    out = (getattr(args, "out", "") or "").strip()
    if out:
        return Path(f"{Path(out).with_suffix('')}.media")
    return Path("./wechat-collected-media")


# ------------------------------------------------------------------ 独立入口
def build_parser() -> argparse.ArgumentParser:
    """独立运行时的解析器（collect.py 之外自检 / 单层直跑用）。

    与 L2 一致提供顶层 --config/--yes；mode 前缀可省略（main 自动补全）。
    """
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", default=argparse.SUPPRESS, help="YAML 配置路径（默认内置 DEFAULT_CONFIG）")
    common.add_argument("--yes", action="store_true", default=argparse.SUPPRESS,
                        help="合规闸：确认已获授权（非交互/自动化必填）")
    parser = argparse.ArgumentParser(
        prog="l1_fetch_urls.py",
        description="L1 采集层：Playwright 直接抓取公众号文章 URL（单条/批量）",
        parents=[common],
    )
    sub = parser.add_subparsers(dest="mode", metavar="<mode>")
    register(sub)
    parser.set_defaults(func=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    tokens = list(sys.argv[1:] if argv is None else argv)
    if tokens and tokens[0] != "url" and not tokens[0].startswith(("--config", "--yes")):
        tokens = ["url"] + tokens  # 直跑省略 mode 前缀（含 --help）时自动补全
    parser = build_parser()
    args = parser.parse_args(tokens)
    if not getattr(args, "mode", None):
        parser.print_help()
        return EXIT_PARAM
    handler = getattr(args, "func", None)
    if handler is None:
        parser.print_help()
        return EXIT_PARAM
    return int(handler(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
