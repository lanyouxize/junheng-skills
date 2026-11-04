#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""exe 模式：闭源采集 exe 兜底层（P2）。

通用策略（不假设具体 exe 的 CLI 形态）：
  1. 探测：`<exe> --help` 限时等待——能退出视为 CLI 工具，挂起超时视为 GUI 程序；
  2. 执行：CLI 模式同步等待退出（超时则按已产出内容扫描）；GUI 模式后台启动 + 等待
     --wait 秒后扫描，扫描结束统一清理进程（terminate -> kill），不遗留孤儿进程；
  3. 扫描：只认本次运行新产生（mtime >= 启动时刻）的文件，支持 *.json / *.jsonl /
     *.html / *.htm；其余后缀 warn 跳过；
  4. 归一：HTML 走 extract.py（先找 og:url/canonical/msg_link 还原文章 URL）；
     JSON/JSONL 按别名表映射 24 列；图片只记 URL 不下载（images_ref 为空 -> partial）。

record_id 一律由规范化 URL 派生（uuid5），不采用 exe 自有 id，避免与其他采集层冲突
（schema.md §4：覆盖需先评估冲突，此处选择不覆盖）。

用法：
    python collect.py --yes exe --exe "D:/tools/4.0.exe" --target "公众号名" --out out/v4e.jsonl
    python collect.py --yes exe --exe app.exe --target "公众号名" --output-dir ./exe-out --wait 90
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from html import unescape
from pathlib import Path

from common import (
    EXIT_ERROR,
    EXIT_OK,
    EXIT_PARAM,
    EXIT_PARTIAL,
    LEVEL_ERROR,
    LEVEL_INFO,
    LEVEL_PARAM,
    LEVEL_WARN,
    emit_event,
    load_config,
    write_jsonl,
)
from extract import extract_article
from normalize import build_article, canonicalize_url, validate_article

EXTRACTOR_PREFIX = "exe:"
_SCAN_SUFFIXES = {".json", ".jsonl", ".html", ".htm"}
_MTIME_TOLERANCE = 2.0  # 文件系统时间戳粒度容差（秒）
_EPOCH_RE = re.compile(r"^\d{9,11}$")

# exe 输出 JSON 的常见键名别名（按优先级取第一个非空值）
_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "title": ("title", "标题", "文章标题", "name"),
    "url": ("url", "link", "文章链接", "链接", "原文链接"),
    "account": ("account", "nickname", "公众号", "公众号名称", "账号"),
    "account_id": ("account_id", "biz", "__biz"),
    "author": ("author", "作者"),
    "publish_time": ("publish_time", "publishTime", "publish_date", "publishDate", "time", "发布时间", "日期"),
    "digest": ("digest", "summary", "desc", "摘要", "描述"),
    "cover": ("cover", "cover_url", "coverUrl", "封面", "封面图"),
    "video_url": ("video_url", "videoUrl", "视频链接"),
    "body_html": ("body_html", "content_html", "contentHtml", "html", "正文", "内容"),
    "body_text": ("body_text", "content", "text", "正文文本"),
    "images": ("images", "图片", "图片列表"),
    "word_count": ("word_count", "wordCount", "字数"),
    "media_type": ("media_type", "mediaType", "类型"),
}

# HTML 中还原文章 URL 的模式（按优先级）
_URL_PATTERNS = (
    r'<meta[^>]+property=["\']og:url["\'][^>]+content=["\']([^"\']+)["\']',
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:url["\']',
    r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)["\']',
    r"var\s+msg_link\s*=\s*['\"]([^'\"]+)['\"]",
    r"(https?://mp\.weixin\.qq\.com/s[^\s\"'<>]*)",
)


# ------------------------------------------------------------------ 参数注册
def register(subparsers: argparse._SubParsersAction) -> None:
    """注册子命令 "exe"。"""
    parser = subparsers.add_parser(
        "exe",
        help="exe 兜底：驱动闭源采集 exe 并扫描其输出目录",
        description="先探测 exe CLI（--help 能否退出），再以 CLI/GUI 两种模式驱动并扫描输出目录，"
                    "把 JSON/HTML 产物归一为 24 列记录。",
    )
    parser.add_argument("--exe", default="", help="闭源采集 exe 路径（必填）")
    parser.add_argument("--target", default="", help="采集目标：公众号名或文章 URL（必填）")
    parser.add_argument("--out", default="", help="JSONL 输出路径（默认写 stdout）")
    parser.add_argument(
        "--output-dir", default="",
        help="exe 输出目录（默认 config.exe.output_dir 或 ./wechat-exe-output/）",
    )
    parser.add_argument(
        "--wait", type=int, default=60,
        help="GUI 模式等待秒数 / CLI 模式执行超时秒数（默认 60）",
    )
    parser.add_argument("--probe-timeout", type=int, default=10, help="--help 探测超时秒（默认 10）")
    parser.add_argument("--exe-args", default="", help="透传给 exe 的额外参数（shlex 分割）")
    parser.set_defaults(func=run)


# ------------------------------------------------------------------ 主流程
def run(args: argparse.Namespace) -> int:
    """驱动 exe 并归一其输出，返回退出码。"""
    exe_path = (getattr(args, "exe", "") or "").strip()
    if not exe_path:
        emit_event(LEVEL_PARAM, "exe.no_exe", reason="--exe 必填（闭源采集 exe 路径）")
        return EXIT_PARAM
    if not Path(exe_path).is_file():
        emit_event(LEVEL_PARAM, "exe.exe_missing", path=exe_path)
        return EXIT_PARAM
    target = (getattr(args, "target", "") or "").strip()
    if not target:
        emit_event(LEVEL_PARAM, "exe.no_target", reason="--target 必填（公众号名或文章 URL）")
        return EXIT_PARAM

    config = load_config(getattr(args, "config", ""))
    exe_cfg = config.get("exe") or {}
    output_dir = Path(
        (getattr(args, "output_dir", "") or "").strip()
        or str(exe_cfg.get("output_dir") or "./wechat-exe-output/")
    )
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        emit_event(LEVEL_ERROR, "exe.output_dir_error", output_dir=str(output_dir), error=str(exc))
        return EXIT_ERROR

    extractor = EXTRACTOR_PREFIX + Path(exe_path).stem
    extra = shlex.split(getattr(args, "exe_args", "") or "")
    cmd = [exe_path, *extra, target]

    # 1) 探测：--help 能退出 -> CLI；挂起 -> GUI
    try:
        probe = subprocess.run(
            [exe_path, "--help"], capture_output=True, text=True, encoding="utf-8",
            timeout=int(args.probe_timeout),
        )
        cli_mode = True
        emit_event(
            LEVEL_INFO, "exe.probe_cli",
            returncode=probe.returncode,
            help_head=(probe.stdout or "")[:200].replace("\n", " "),
        )
    except subprocess.TimeoutExpired:
        cli_mode = False
        emit_event(LEVEL_INFO, "exe.probe_gui", reason="--help 挂起，按 GUI 程序处理")
    except OSError as exc:
        emit_event(LEVEL_ERROR, "exe.launch_failed", path=exe_path, error=str(exc))
        return EXIT_ERROR

    # 2) 执行（start_ts 之后的产物才算本次输出）
    start_ts = time.time()
    proc: subprocess.Popen | None = None
    try:
        if cli_mode:
            try:
                finished = subprocess.run(
                    cmd, cwd=str(output_dir), capture_output=True, text=True,
                    encoding="utf-8", timeout=int(args.wait),
                )
                emit_event(
                    LEVEL_INFO, "exe.cli_finished",
                    returncode=finished.returncode,
                    stdout_tail=(finished.stdout or "")[-200:],
                )
            except subprocess.TimeoutExpired:
                emit_event(
                    LEVEL_WARN, "exe.cli_timeout",
                    wait=int(args.wait), reason="超时未退出，按已产出内容扫描",
                )
        else:
            proc = subprocess.Popen(
                cmd, cwd=str(output_dir),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            emit_event(LEVEL_INFO, "exe.gui_launched", pid=proc.pid, wait=int(args.wait))
            time.sleep(max(int(args.wait), 0))
    except OSError as exc:
        emit_event(LEVEL_ERROR, "exe.run_failed", cmd=cmd, error=str(exc))
        return EXIT_ERROR
    finally:
        if proc is not None and proc.poll() is None:
            _terminate(proc)

    # 3) 扫描 + 4) 归一
    records: list[dict] = []
    for path in _scan_new_files(output_dir, start_ts):
        suffix = path.suffix.lower()
        if suffix not in _SCAN_SUFFIXES:
            emit_event(LEVEL_WARN, "exe.unsupported_file", path=str(path))
            continue
        try:
            if suffix in {".html", ".htm"}:
                records.append(_record_from_html(path.read_text(encoding="utf-8"), extractor))
            else:
                records.extend(_records_from_json(path, extractor))
        except Exception as exc:  # 单文件解析失败不中断整批
            emit_event(LEVEL_WARN, "exe.parse_failed", path=str(path), error=str(exc))

    if not records:
        emit_event(
            LEVEL_WARN, "exe.no_output",
            output_dir=str(output_dir), target=target,
            reason="未发现本次运行产生的可识别文章文件",
        )

    write_jsonl(getattr(args, "out", "") or None, records)

    counts = {"ok": 0, "partial": 0, "fail": 0}
    for record in records:
        counts[str(record.get("status") or "fail")] = counts.get(str(record.get("status") or "fail"), 0) + 1
    emit_event(
        LEVEL_INFO, "exe.done",
        total=len(records), ok=counts["ok"], partial=counts["partial"], fail=counts["fail"],
    )
    if counts["fail"] or (counts["ok"] == 0 and counts["partial"] == 0):
        return EXIT_PARTIAL
    if counts["partial"]:
        return EXIT_PARTIAL
    return EXIT_OK


# ------------------------------------------------------------------ 扫描 / 解析
def _scan_new_files(output_dir: Path, start_ts: float) -> list[Path]:
    """输出目录中本次运行新产生的文件（mtime >= start_ts - 容差），按名称排序。"""
    found: list[Path] = []
    for path in sorted(output_dir.iterdir()):
        if not path.is_file():
            continue
        try:
            if path.stat().st_mtime >= start_ts - _MTIME_TOLERANCE:
                found.append(path)
        except OSError:
            continue
    return found


def _records_from_json(path: Path, extractor: str) -> list[dict]:
    """解析 exe 的 JSON/JSONL 输出为记录列表（兼容单对象、{"articles": [...]} 包装、JSONL）。"""
    text = path.read_text(encoding="utf-8")
    items: list = []
    if path.suffix.lower() == ".jsonl":
        for line in text.splitlines():
            line = line.strip()
            if line:
                items.append(json.loads(line))
    else:
        payload = json.loads(text)
        if isinstance(payload, dict):
            for key in ("articles", "records", "list", "data", "results"):
                if isinstance(payload.get(key), list):
                    items = payload[key]
                    break
            else:
                items = [payload]
        elif isinstance(payload, list):
            items = payload

    records: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            emit_event(LEVEL_WARN, "exe.item_not_object", path=str(path))
            continue
        record = _record_from_mapping(item, extractor)
        if record is not None:
            records.append(record)
    return records


def _pick(item: dict, field: str) -> object:
    """按别名表取第一个非空值。"""
    for alias in _FIELD_ALIASES.get(field, ()):
        if alias in item:
            value = item[alias]
            if value is not None and not (isinstance(value, str) and not value.strip()):
                return value
    return None


def _normalize_images(value: object) -> list[dict]:
    """图片字段归一为 [{"url": ...}]（exe 层只记 URL，不下载）。"""
    images: list[dict] = []
    if isinstance(value, str):
        value = [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, list):
        for entry in value:
            if isinstance(entry, str) and entry.strip():
                images.append({"url": entry.strip()})
            elif isinstance(entry, dict):
                url = str(entry.get("url") or entry.get("src") or entry.get("link") or "").strip()
                if url:
                    images.append({"url": url})
    return images


def _normalize_publish_time(value: object) -> str:
    """发布时间归一：epoch 秒 -> UTC ISO；其余字符串原样透传（build/validate 容忍空）。"""
    text = str(value or "").strip()
    if _EPOCH_RE.match(text):
        return datetime.fromtimestamp(int(text), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return text


def _record_from_mapping(item: dict, extractor: str) -> dict | None:
    """exe JSON 条目 -> 24 列记录；无标题且无正文的条目跳过（warn）。"""
    title = str(_pick(item, "title") or "").strip()
    body_html = str(_pick(item, "body_html") or "")
    body_text = str(_pick(item, "body_text") or "")
    if not title and not body_html and not body_text:
        emit_event(LEVEL_WARN, "exe.item_not_article", keys=sorted(item.keys())[:12])
        return None

    url = str(_pick(item, "url") or "").strip()
    word_count = _pick(item, "word_count")
    record = build_article(
        title=title,
        url=url,
        collect_layer="exe",
        extractor=extractor,
        account=str(_pick(item, "account") or ""),
        account_id=str(_pick(item, "account_id") or ""),
        author=str(_pick(item, "author") or ""),
        publish_time=_normalize_publish_time(_pick(item, "publish_time")),
        digest=str(_pick(item, "digest") or ""),
        media_type=str(_pick(item, "media_type") or "text"),
        cover_url=str(_pick(item, "cover") or "") or None,
        video_url=str(_pick(item, "video_url") or "") or None,
        body_ref="",
        media_ref="",
        images=_normalize_images(_pick(item, "images")),
        videos=[],
        word_count=int(word_count) if isinstance(word_count, (int, float)) else None,
    )
    status, reasons = validate_article(record)
    record["status"] = status
    if status == "fail":
        record["fail_reason"] = "; ".join(reasons)
    return record


def _record_from_html(html: str, extractor: str) -> dict:
    """exe 保存的文章页 HTML -> 24 列记录（先还原 URL，再走共用解析器）。"""
    url = _find_article_url(html)
    if not url:
        record = build_article(
            title="", url="", collect_layer="exe", extractor=extractor,
        )
        record["status"] = "fail"
        record["fail_reason"] = "exe HTML 输出中找不到文章 URL（og:url/canonical/msg_link/mp.weixin 链接均缺失）"
        return record

    fields = extract_article(html, url)
    record = build_article(
        title=fields["title"],
        url=url,
        collect_layer="exe",
        extractor=extractor,
        account=fields["account"],
        account_id=fields["account_id"],
        author=fields["author"],
        publish_time=fields["publish_time"],
        digest=fields["digest"],
        media_type=fields["media_type"],
        cover_url=fields["cover"] or None,
        video_url=fields["video_url"] or None,
        body_ref="",
        media_ref="",
        images=[{"url": img["url"]} for img in fields.get("images") or []],
        videos=[],
        word_count=fields["word_count"],
    )
    status, reasons = validate_article(record)
    record["status"] = status
    if status == "fail":
        record["fail_reason"] = "; ".join(reasons)
    return record


def _find_article_url(html: str) -> str:
    """从保存的文章页 HTML 还原文章 URL（找不到返回 ""）。"""
    for pattern in _URL_PATTERNS:
        match = re.search(pattern, html, re.I)
        if not match:
            continue
        candidate = unescape(match.group(1) if match.groups() else match.group(0)).strip()
        if canonicalize_url(candidate):
            return candidate
    return ""


def _terminate(proc: subprocess.Popen) -> None:
    """清理本模块启动的进程：先 terminate，5 秒内不退则 kill。"""
    try:
        proc.terminate()
        proc.wait(timeout=5)
        emit_event(LEVEL_INFO, "exe.process_terminated", pid=proc.pid)
    except Exception:
        try:
            proc.kill()
            emit_event(LEVEL_INFO, "exe.process_killed", pid=proc.pid)
        except Exception as exc:  # noqa: BLE001 - 清理失败不升级
            emit_event(LEVEL_WARN, "exe.process_cleanup_failed", pid=proc.pid, error=str(exc))


# ------------------------------------------------------------------ 独立入口
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="exe_wrapper.py",
        description="exe 模式：闭源采集 exe 兜底（探测 CLI -> 驱动 -> 扫描输出 -> 归一 24 列）",
    )
    sub = parser.add_subparsers(dest="mode", metavar="<mode>")
    register(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
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
