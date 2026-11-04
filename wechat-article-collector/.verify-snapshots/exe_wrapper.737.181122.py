#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""闭源 exe 兜底采集层（collect.py mode=exe，P2）。

契约：register(subparsers) / run(args) -> int（见 collect.py docstring）。
流程：
  1. 探测 exe CLI：依次跑 `<exe> --help|-h|/?`（probe-timeout 超时即杀），
     stdout/stderr 出现 usage/参数/选项等关键字判"支持 CLI"；
  2. 支持 CLI -> Popen(<exe> + --exe-args + targets)，wait(probe-timeout)；
     不支持   -> Popen(<exe> + --exe-args) 后轮询 --output-dir
                 （每 2s 一扫，最多 settle-seconds，进程退出即收尾）；
  3. 扫描输出目录（.html/.htm/.json/.csv + 视频文件）：.html 走
     extract_article；.json/.csv 按别名表映射 title/url/digest/publish_time/
     account/images；统一 build_article(collect_layer="exe",
     extractor="exe:<exe文件名stem>") + validate_article；
     record_id 由规范化 URL 派生（缺 url 用文件名）；
  4. 体积上限（ADR-003）：单文件 exe.max_file_mb（默认 32MB）、总产出
     exe.max_total_mb（默认 512MB）；超限 warn + 跳过 + 事件（文件/大小/上限）；
  5. 媒体：每篇写 <media>/<record_id>.media.json（schema.md §7 形态
     {"images":[{"url","local_path"?}],"videos":[{"url"|"local_path"}]}），
     正文 HTML 存 <media>/<record_id>.html；发现视频文件时归入 videos 并置
     media_type=video-file（有播放页 URL 无文件则 video-meta，否则 text）；
  6. 写 JSONL + exe.done 汇总；exe 缺失/零产物 -> exe.no_output + EXIT_ERROR；
     有 fail 行 -> EXIT_PARTIAL；全 ok -> EXIT_OK。
顶层仅标准库；bs4/lxml 由 extract.lazy_import 延迟加载（缺依赖时单文件记
parse_failed，不中断整体）。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import locale
import re
import shlex
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    EXIT_COMPLIANCE,
    EXIT_ERROR,
    EXIT_OK,
    EXIT_PARAM,
    EXIT_PARTIAL,
    LEVEL_ERROR,
    LEVEL_INFO,
    LEVEL_WARN,
    attest,
    emit_event,
    load_config,
    write_jsonl,
)
from extract import extract_article  # noqa: E402
from normalize import build_article, canonicalize_url, validate_article  # noqa: E402

_SCAN_SUFFIXES = (".html", ".htm", ".json", ".csv")
_VIDEO_SUFFIXES = (".mp4", ".mov", ".avi", ".mkv", ".flv", ".m4v", ".webm", ".wmv",
                   ".mpeg", ".mpg", ".m3u8")
_CLI_HELP_FLAGS = ("--help", "-h", "/?")
_CLI_HINTS = ("usage", "用法", "参数", "选项", "options", "commands", "help")
_SCRIPT_SUFFIXES = {".bat", ".cmd"}
_DEFAULT_MEDIA_DIR = "./wechat-collected-media"
_URL_PATTERNS = (
    r"""<meta[^>]+property=["']og:url["'][^>]+content=["']([^"']+)""",
    r"""<link[^>]+rel=["']canonical["'][^>]+href=["']([^"']+)""",
    r"""var\s+msg_link\s*=\s*["']([^"']+)""",
)
# exe 产物（json/csv）字段别名 -> 记录字段（键比较前统一小写）
_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "title": ("title", "文章标题", "标题", "name"),
    "url": ("url", "link", "msg_link", "文章链接", "链接"),
    "digest": ("digest", "desc", "description", "摘要"),
    "publish_time": ("publish_time", "publishtime", "publish_date", "date", "time", "发布时间"),
    "account": ("account", "nickname", "公众号", "公众号名称", "wechat_account"),
    "author": ("author", "作者"),
    "account_id": ("account_id", "biz", "__biz"),
    "images": ("images", "图片", "图片列表"),
}


def _decode(raw: bytes | None) -> str:
    """子进程输出解码：utf-8 优先，失败回退 locale（同机编码一致）。"""
    if not raw:
        return ""
    for encoding in ("utf-8", locale.getpreferredencoding() or "utf-8"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


# ------------------------------------------------------------------ 探测 / 启动
def _resolve_exe(exe: str) -> str | None:
    """解析 exe 路径：直接路径存在则用，否则按 PATH 查找。"""
    if not exe:
        return None
    candidate = Path(exe)
    if candidate.exists():
        return str(candidate)
    return shutil.which(exe)


def _run_probe(cmd: list[str], timeout: float) -> subprocess.CompletedProcess:
    """跑一次探测命令；.bat/.cmd 走 shell（CreateProcess 不认批处理）。"""
    if Path(cmd[0]).suffix.lower() in _SCRIPT_SUFFIXES:
        return subprocess.run(cmd, shell=True, capture_output=True, timeout=timeout)
    return subprocess.run(cmd, capture_output=True, timeout=timeout)


def _looks_like_cli_help(text: str) -> bool:
    lowered = (text or "").lower()
    return any(hint in lowered for hint in _CLI_HINTS)


def _probe_cli(exe: str, timeout: float) -> subprocess.CompletedProcess | None:
    """探测 exe 是否接受命令行参数；超时即杀，返回首个帮助类输出。"""
    for flag in _CLI_HELP_FLAGS:
        try:
            proc = _run_probe([exe, flag], timeout)
        except subprocess.TimeoutExpired:
            continue  # 该 flag 卡住（疑似 GUI/交互），换下一个
        except OSError as exc:
            raise RuntimeError(f"无法执行 exe: {exe}: {exc}") from exc
        text = _decode(proc.stdout) + "\n" + _decode(proc.stderr)
        if _looks_like_cli_help(text):
            return proc
    return None


def _spawn(cmd: list[str], cwd: Path | None = None) -> subprocess.Popen:
    """启动 exe（不接管其输出，避免管道缓冲死锁）。

    cwd 固定为输出目录：exe 的相对路径产物/日志/缓存不会污染调用方工作目录，
    同时让我们轮询的扫描目录能捕获这些产物。cwd 由 subprocess 直接使用，
    不经过 shell（shell=True 分支也无需额外加引号）。
    """
    workdir = str(cwd) if cwd else None
    if Path(cmd[0]).suffix.lower() in _SCRIPT_SUFFIXES:
        return subprocess.Popen(cmd, shell=True, cwd=workdir,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return subprocess.Popen(cmd, cwd=workdir,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _split_exe_args(raw: str) -> list[str]:
    """Windows 友好的参数字符串切分（保留反斜杠路径，剥离成对引号）。"""
    text = (raw or "").strip()
    if not text:
        return []
    try:
        tokens = shlex.split(text, posix=False)
    except ValueError:
        tokens = text.split()
    cleaned: list[str] = []
    for token in tokens:
        if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'":
            token = token[1:-1]
        if token:
            cleaned.append(token)
    return cleaned


# ------------------------------------------------------------------ 输出目录轮询
def _scan_once(output_dir: Path, seen: set[Path], since_ts: float = 0.0,
               stale_seen: set[Path] | None = None) -> list[Path]:
    """扫一轮新产物。

    since_ts > 0 时跳过 mtime 明显早于本次启动的文件：复用输出目录时，
    上一轮残留的产物不该被当成这一轮的产物重复入账。容差 1.0s —— FAT/exFAT
    的 mtime 粒度是 2s 且时钟可能跳变，用严格 `>` 会误杀本轮产物。
    stale_seen 收集被跳过的旧文件（跨轮去重，收尾只报一次总数）。
    """
    fresh: list[Path] = []
    if not output_dir.is_dir():
        return fresh
    for path in sorted(output_dir.rglob("*")):
        if path.is_file() and path not in seen and path.suffix.lower() in _SCAN_SUFFIXES:
            if since_ts and path.stat().st_mtime < since_ts - 1.0:
                if stale_seen is not None:
                    stale_seen.add(path)
                continue
            fresh.append(path)
    return fresh


def _emit_stale_skipped(stale: set[Path]) -> None:
    """旧产物被 mtime 过滤时说明一句，否则用户无法解释"这次产物怎么变少了"。"""
    if stale:
        emit_event(LEVEL_INFO, "exe.stale_skipped", count=len(stale))


def _collect_output_files(output_dir: Path, settle_seconds: float,
                          proc: subprocess.Popen | None,
                          since_ts: float = 0.0) -> list[Path]:
    """每 2s 扫描 output_dir 收集新产物；进程退出或达到 settle-seconds 收尾。"""
    seen: set[Path] = set()
    stale: set[Path] = set()
    collected: list[Path] = []
    interval = 2.0
    deadline = time.monotonic() + max(float(settle_seconds), 0.0)
    while True:
        fresh = _scan_once(output_dir, seen, since_ts, stale)
        if fresh:
            collected.extend(fresh)
            seen.update(fresh)
            emit_event(LEVEL_INFO, "exe.new_files", count=len(fresh),
                       files=[str(p) for p in fresh])
        if proc is not None and proc.poll() is not None:
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(interval)
    _emit_stale_skipped(stale)
    return collected


def _scan_videos(output_dir: Path) -> list[Path]:
    if not output_dir.is_dir():
        return []
    return [path for path in sorted(output_dir.rglob("*"))
            if path.is_file() and path.suffix.lower() in _VIDEO_SUFFIXES]


def _apply_size_limits(paths: list[Path], max_file_mb: float, max_total_mb: float,
                       used_bytes: int = 0) -> tuple[list[Path], int]:
    """ADR-003：单文件/总产出体积上限；超限 warn + 跳过（不静默、不崩溃）。"""
    kept: list[Path] = []
    file_limit = max_file_mb * 1024 * 1024 if max_file_mb > 0 else 0
    total_limit = max_total_mb * 1024 * 1024 if max_total_mb > 0 else 0
    for path in paths:
        try:
            size = path.stat().st_size
        except OSError as exc:
            emit_event(LEVEL_WARN, "exe.file_stat_failed", path=str(path), error=str(exc))
            continue
        size_mb = round(size / 1048576, 2)
        if file_limit and size > file_limit:
            emit_event(LEVEL_WARN, "exe.file_too_large", path=str(path),
                       size_mb=size_mb, limit_mb=max_file_mb)
            continue
        if total_limit and used_bytes + size > total_limit:
            emit_event(LEVEL_WARN, "exe.total_limit_exceeded", path=str(path),
                       size_mb=size_mb, limit_mb=max_total_mb,
                       used_mb=round(used_bytes / 1048576, 2))
            continue
        kept.append(path)
        used_bytes += size
    return kept, used_bytes


# ------------------------------------------------------------------ 产物解析
def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8", "gbk"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _html_url(html: str) -> str:
    """从文章页 HTML 提取文章 URL（og:url / canonical / msg_link）。"""
    for pattern in _URL_PATTERNS:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""


def _stage_html(path: Path, media_dir: Path | None, record_id: str) -> str:
    """正文 HTML 存 <media>/<record_id>.html（schema.md §7）。"""
    if media_dir is None:
        return str(path.resolve())
    target = media_dir / f"{record_id}.html"
    try:
        media_dir.mkdir(parents=True, exist_ok=True)
        if path.resolve() != target.resolve():
            shutil.copyfile(path, target)
        return str(target)
    except OSError as exc:
        emit_event(LEVEL_WARN, "exe.media_stage_failed", path=str(path), error=str(exc))
        return str(path.resolve())


def _stage_source(path: Path, media_dir: Path | None, output_dir: Path) -> str:
    """json/csv 批次产物按源文件暂存一次（<stem>_<hash8><ext>），返回 body_ref。"""
    if media_dir is None:
        return str(path.resolve())
    try:
        key = str(path.relative_to(output_dir)) if path.is_relative_to(output_dir) else path.name
    except ValueError:
        key = path.name
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:8]
    stem = re.sub(r"[^0-9A-Za-z._-]+", "_", path.stem).strip("_") or "source"
    target = media_dir / f"{stem}_{digest}{path.suffix.lower()}"
    try:
        media_dir.mkdir(parents=True, exist_ok=True)
        if path.resolve() != target.resolve():
            shutil.copyfile(path, target)
        return str(target)
    except OSError as exc:
        emit_event(LEVEL_WARN, "exe.media_stage_failed", path=str(path), error=str(exc))
        return str(path.resolve())


def _write_media_manifest(media_dir: Path | None, record_id: str,
                          images: list[dict], videos: list[dict]) -> str:
    """每篇一份 <media>/<record_id>.media.json（schema.md §7）；无媒体返回空串。"""
    if media_dir is None or not record_id or not (images or videos):
        return ""
    try:
        media_dir.mkdir(parents=True, exist_ok=True)
        target = media_dir / f"{record_id}.media.json"
        payload = {"images": images, "videos": videos}
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(target)
    except OSError as exc:
        emit_event(LEVEL_WARN, "exe.media_manifest_failed", record_id=record_id, error=str(exc))
        return ""


def _normalize_images(value: Any) -> list[dict]:
    """图片字段归一为 [{"url": ...}]（exe 层只记 URL 不下载）。"""
    if isinstance(value, str):
        value = [part.strip() for part in value.replace(";", ",").split(",") if part.strip()]
    images: list[dict] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.strip():
                images.append({"url": item.strip()})
            elif isinstance(item, dict):
                url = str(item.get("url") or item.get("src") or item.get("link") or "").strip()
                if url:
                    entry: dict[str, str] = {"url": url}
                    local = str(item.get("local_path") or "").strip()
                    if local:
                        entry["local_path"] = local
                    images.append(entry)
    return images


def _pick(mapping: dict[str, Any], field: str) -> Any:
    for key in _FIELD_ALIASES[field]:
        value = mapping.get(key)
        if value is not None and not (isinstance(value, str) and not value.strip()):
            return value
    return None


def _text_of(mapping: dict[str, Any], field: str) -> str:
    value = _pick(mapping, field)
    return str(value).strip() if value is not None else ""


def _norm_publish_time(raw: str) -> str:
    """epoch 秒/毫秒 -> UTC ISO8601；其余（ISO 串等）原样返回。"""
    value = (raw or "").strip()
    if value.isdigit() and len(value) >= 9:
        seconds = int(value)
        if len(value) >= 13:  # 毫秒
            seconds //= 1000
        return datetime.fromtimestamp(seconds, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return value


def _record_from_html(path: Path, media_dir: Path | None,
                      extractor: str) -> tuple[dict[str, Any], list[dict]]:
    html = _read_text(path)
    url = _html_url(html)
    fields = extract_article(html, url or "https://mp.weixin.qq.com/")
    canonical = canonicalize_url(url) if url else None
    record_id = str(uuid.uuid5(uuid.NAMESPACE_URL, canonical or path.name))
    images = _normalize_images(fields.get("images"))
    record = build_article(
        title=fields.get("title") or "",
        url=url,
        collect_layer="exe",
        extractor=extractor,
        account=fields.get("account") or "",
        account_id=fields.get("account_id") or "",
        author=fields.get("author") or "",
        publish_time=fields.get("publish_time") or "",
        digest=fields.get("digest") or "",
        media_type=fields.get("media_type") or "text",
        cover_url=fields.get("cover") or None,
        video_url=fields.get("video_url") or None,
        body_ref=_stage_html(path, media_dir, record_id),
        images=images,
        word_count=fields.get("word_count"),
        fidelity="full" if fields.get("body_html") else "partial",
        record_id=record_id,
    )
    return record, images


def _record_from_mapping(mapping: dict[str, Any], source: Path, index: int, body_ref: str,
                         extractor: str) -> tuple[dict[str, Any], list[dict]]:
    lookup = {str(key).strip().lower(): value for key, value in mapping.items() if key is not None}
    url = _text_of(lookup, "url")
    canonical = canonicalize_url(url) if url else None
    record_id = str(uuid.uuid5(uuid.NAMESPACE_URL, canonical or f"{source.stem}#{index}"))
    images = _normalize_images(_pick(lookup, "images"))
    record = build_article(
        title=_text_of(lookup, "title"),
        url=url,
        collect_layer="exe",
        extractor=extractor,
        account=_text_of(lookup, "account"),
        account_id=_text_of(lookup, "account_id"),
        author=_text_of(lookup, "author"),
        publish_time=_norm_publish_time(_text_of(lookup, "publish_time")),
        digest=_text_of(lookup, "digest"),
        body_ref=body_ref,
        images=images,
        record_id=record_id,
    )
    return record, images


def _entries_from_json(path: Path, body_ref: str, extractor: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(_read_text(path))
    except json.JSONDecodeError as exc:
        emit_event(LEVEL_WARN, "exe.json_parse_failed", path=str(path), error=str(exc))
        return []
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        rows = None
        for key in ("articles", "items", "list", "data", "records"):
            value = data.get(key)
            if isinstance(value, list):
                rows = value
                break
        if rows is None:
            rows = [data]
    else:
        rows = []
    entries: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if isinstance(row, dict):
            record, images = _record_from_mapping(row, path, index, body_ref, extractor)
            entries.append({"record": record, "images": images, "videos": [], "path": path})
        else:
            emit_event(LEVEL_WARN, "exe.json_row_not_object", path=str(path), index=index)
    return entries


def _entries_from_csv(path: Path, body_ref: str, extractor: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            for index, row in enumerate(csv.DictReader(handle)):
                if isinstance(row, dict):
                    record, images = _record_from_mapping(row, path, index, body_ref, extractor)
                    entries.append({"record": record, "images": images, "videos": [], "path": path})
    except OSError as exc:
        emit_event(LEVEL_WARN, "exe.csv_read_failed", path=str(path), error=str(exc))
    return entries


def _attach_videos(entries: list[dict[str, Any]], videos: list[Path]) -> int:
    """把输出目录里的视频文件归入记录：record_id 命中文件名 > 单记录兜底。"""
    if not videos or not entries:
        return 0
    by_id = {entry["record"].get("record_id"): entry for entry in entries}
    attached = 0
    pending: list[Path] = []
    for video in videos:
        match = next((rid for rid in by_id if rid and rid in video.stem), None)
        if match:
            by_id[match]["videos"].append({"local_path": str(video.resolve())})
            attached += 1
        else:
            pending.append(video)
    if pending and len(entries) == 1:
        for video in pending:
            entries[0]["videos"].append({"local_path": str(video.resolve())})
            attached += 1
        pending = []
    for video in pending:
        emit_event(LEVEL_WARN, "exe.video_unmatched", path=str(video))
    if attached:
        emit_event(LEVEL_INFO, "exe.video_attached", count=attached)
    return attached


def _finalize_media(entry: dict[str, Any], media_dir: Path | None) -> None:
    """按 schema.md §7 落每篇 media.json，回填 count/ref，并定媒体形态。"""
    record = entry["record"]
    images = entry["images"]
    videos = entry["videos"]
    record["images_count"] = len(images)
    record["videos_count"] = len(videos)
    if videos:
        record["media_type"] = "video-file"
    manifest = _write_media_manifest(media_dir, str(record.get("record_id") or ""), images, videos)
    record["images_ref"] = manifest if (manifest and images) else None
    record["videos_ref"] = manifest if (manifest and videos) else None


def _finalize(record: dict[str, Any]) -> dict[str, Any]:
    """validate_article 复核：fail 记 fail_reason，partial 降级并记 partial_reason。"""
    status, reasons = validate_article(record)
    if status != record.get("status"):
        record["status"] = status
    if reasons:
        record["fail_reason" if status == "fail" else "partial_reason"] = "; ".join(reasons)
    return record


# ------------------------------------------------------------------ 参数
def _load_targets(args: argparse.Namespace) -> list[str] | None:
    target = (getattr(args, "target", "") or "").strip()
    targets_file = (getattr(args, "targets_file", "") or "").strip()
    if target and targets_file:
        emit_event(LEVEL_PARAM, "exe.param_conflict", hint="--target 与 --targets-file 二选一")
        return None
    if targets_file:
        path = Path(targets_file)
        if not path.is_file():
            emit_event(LEVEL_PARAM, "exe.param_missing", field="targets-file", path=targets_file)
            return None
        targets = [line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines()
                   if line.strip()]
    elif target:
        targets = [target]
    else:
        emit_event(LEVEL_PARAM, "exe.param_missing", field="target",
                   hint="--target 与 --targets-file 至少提供一个")
        return None
    if not targets:
        emit_event(LEVEL_PARAM, "exe.param_missing", field="target", reason="目标列表为空")
        return None
    return targets


def _resolve_media_dir(args: argparse.Namespace) -> Path:
    """--media-dir > <out 去扩展名>.media/ > ./wechat-collected-media（schema.md §7）。"""
    raw = (getattr(args, "media_dir", "") or "").strip()
    if raw:
        return Path(raw)
    out = (getattr(args, "out", "") or "").strip()
    if out:
        out_path = Path(out)
        return out_path.parent / f"{out_path.stem}.media"
    return Path(_DEFAULT_MEDIA_DIR)


# ------------------------------------------------------------------ 入口
def register(subparsers) -> None:
    parser = subparsers.add_parser("exe", help="闭源 exe 兜底采集（探测 CLI / 启动+扫描输出目录）")
    parser.add_argument("--exe", default="", help="闭源 exe 路径（必填，或 config exe.path）")
    parser.add_argument("--target", default="", help="目标：公众号名称或文章 URL（与 --targets-file 二选一）")
    parser.add_argument("--targets-file", default="", help="目标清单文件，每行一个（与 --target 二选一）")
    parser.add_argument("--exe-args", default="", help="透传给 exe 的参数字符串（保留反斜杠路径）")
    parser.add_argument("--output-dir", default="", help="exe 输出目录（必填，或 config exe.output_dir；扫描用）")
    parser.add_argument("--out", default="", help="JSONL 输出路径（省略则写 stdout）")
    parser.add_argument("--media-dir", default="",
                        help="媒体目录（默认 <out 去扩展名>.media；--out 省略时 ./wechat-collected-media）")
    parser.add_argument("--probe-timeout", type=float, default=15.0,
                        help="CLI 探测/有界等待超时秒数（默认 15）")
    parser.add_argument("--settle-seconds", type=float, default=20.0,
                        help="启动后轮询输出目录的最大秒数（默认 20）")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    config = load_config(getattr(args, "config", None))
    exe_cfg = config.get("exe") or {}

    exe_path = (getattr(args, "exe", "") or exe_cfg.get("path") or "").strip()
    if not exe_path:
        emit_event(LEVEL_PARAM, "exe.param_missing", field="exe",
                   hint="--exe 或 config exe.path 至少提供一个")
        return EXIT_PARAM
    resolved = _resolve_exe(exe_path)
    if not resolved:
        emit_event(LEVEL_ERROR, "exe.no_output", reason="exe 不存在", exe=exe_path)
        return EXIT_ERROR

    targets = _load_targets(args)
    if targets is None:
        return EXIT_PARAM

    output_dir = (getattr(args, "output_dir", "") or exe_cfg.get("output_dir") or "").strip()
    if not output_dir:
        emit_event(LEVEL_PARAM, "exe.param_missing", field="output-dir",
                   hint="--output-dir 或 config exe.output_dir 至少提供一个")
        return EXIT_PARAM
    out_dir = Path(output_dir)
    probe_timeout = 15.0 if getattr(args, "probe_timeout", None) is None else float(args.probe_timeout)
    settle_seconds = 20.0 if getattr(args, "settle_seconds", None) is None else float(args.settle_seconds)
    media_dir = _resolve_media_dir(args)
    extractor = f"exe:{Path(resolved).stem}"
    try:
        max_file_mb = float(exe_cfg.get("max_file_mb", 32) or 32)
        max_total_mb = float(exe_cfg.get("max_total_mb", 512) or 512)
    except (TypeError, ValueError):
        max_file_mb, max_total_mb = 32.0, 512.0

    # 1. 探测 CLI
    try:
        probe = _probe_cli(resolved, probe_timeout)
    except RuntimeError as exc:
        emit_event(LEVEL_ERROR, "exe.no_output", reason="exe 无法执行", exe=resolved, error=str(exc))
        return EXIT_ERROR
    supports_cli = probe is not None
    emit_event(LEVEL_INFO, "exe.probe", exe=resolved, supports_cli=supports_cli,
               extractor=extractor)

    # 2. 启动（支持 CLI 则透传 targets；否则只传 --exe-args，靠轮询收产物）
    cmd = [resolved, *_split_exe_args(getattr(args, "exe_args", "") or "")]
    if supports_cli:
        cmd.extend(targets)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)  # cwd 目标：exe 相对产物落在扫描目录
        started_ts = time.time()  # 早于 spawn：本轮产物的 mtime 不会早于它
        proc = _spawn(cmd, cwd=out_dir)
    except OSError as exc:
        emit_event(LEVEL_ERROR, "exe.no_output", reason="exe 启动失败", exe=resolved, error=str(exc))
        return EXIT_ERROR
    emit_event(LEVEL_INFO, "exe.launched", cmd=cmd, supports_cli=supports_cli, pid=proc.pid,
               cwd=str(out_dir))

    if supports_cli:
        try:
            returncode = proc.wait(timeout=probe_timeout)
        except subprocess.TimeoutExpired:
            emit_event(LEVEL_INFO, "exe.cli_running",
                       hint="超过 probe-timeout 仍在运行，改为轮询输出目录")
            files = _collect_output_files(out_dir, settle_seconds, proc, started_ts)
        else:
            if returncode != 0:
                emit_event(LEVEL_WARN, "exe.cli_nonzero", returncode=returncode)
            stale: set[Path] = set()
            files = _scan_once(out_dir, set(), since_ts=started_ts, stale_seen=stale)
            _emit_stale_skipped(stale)
    else:
        files = _collect_output_files(out_dir, settle_seconds, proc, started_ts)

    if not files:
        emit_event(LEVEL_ERROR, "exe.no_output", reason="输出目录无可用产物",
                   output_dir=str(out_dir), suffixes=list(_SCAN_SUFFIXES))
        return EXIT_ERROR

    # 3. 体积上限（ADR-003，单文件 + 总产出）
    files, used_bytes = _apply_size_limits(files, max_file_mb, max_total_mb)
    videos, _ = _apply_size_limits(_scan_videos(out_dir), max_file_mb, max_total_mb, used_bytes)
    if not files:
        emit_event(LEVEL_ERROR, "exe.no_output", reason="产物均超过体积上限",
                   max_file_mb=max_file_mb, max_total_mb=max_total_mb)
        return EXIT_ERROR

    # 4. 解析产物 -> 24 列记录
    entries: list[dict[str, Any]] = []
    for path in files:
        suffix = path.suffix.lower()
        before = len(entries)
        try:
            if suffix in (".html", ".htm"):
                record, images = _record_from_html(path, media_dir, extractor)
                entries.append({"record": record, "images": images, "videos": [], "path": path})
            else:
                body_ref = _stage_source(path, media_dir, out_dir)
                if suffix == ".json":
                    entries.extend(_entries_from_json(path, body_ref, extractor))
                else:
                    entries.extend(_entries_from_csv(path, body_ref, extractor))
        except Exception as exc:  # 单文件失败不中断整体（缺 bs4 等走这里）
            emit_event(LEVEL_ERROR, "exe.parse_failed", path=str(path), error=str(exc))
            continue
        emit_event(LEVEL_INFO, "exe.file_done", path=str(path), records=len(entries) - before)

    if not entries:
        emit_event(LEVEL_ERROR, "exe.no_output", reason="产物均无法解析为记录", files=len(files))
        return EXIT_ERROR

    # 5. 视频归集 + 媒体清单 + 校验
    _attach_videos(entries, videos)
    records: list[dict[str, Any]] = []
    for entry in entries:
        _finalize_media(entry, media_dir)
        record = _finalize(entry["record"])
        if record.get("status") == "fail":
            emit_event(LEVEL_WARN, "exe.record_failed", path=str(entry["path"]),
                       record_id=record.get("record_id"), reasons=record.get("fail_reason"))
        records.append(record)

    # 6. 输出 + 汇总
    out_path = (getattr(args, "out", "") or "").strip()
    if out_path:
        parent = Path(out_path).parent
        if str(parent) and not parent.exists():
            parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(out_path or None, records)
    ok = sum(1 for r in records if r.get("status") == "ok")
    partial = sum(1 for r in records if r.get("status") == "partial")
    fail = sum(1 for r in records if r.get("status") == "fail")
    video_file = sum(1 for r in records if r.get("media_type") == "video-file")
    emit_event(LEVEL_INFO, "exe.done", total=len(records), ok=ok, partial=partial,
               fail=fail, files=len(files), video_files=video_file,
               out=out_path or None)
    return EXIT_PARTIAL if fail else EXIT_OK


def main(argv: list[str] | None = None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", default=None,
                        help="YAML 配置路径（默认内置 DEFAULT_CONFIG，可复制 config.example.yaml）")
    common.add_argument("--yes", action="store_true",
                        help="合规闸：确认已获授权（非交互/自动化必填）")
    parser = argparse.ArgumentParser(prog="exe_wrapper.py", description=__doc__, parents=[common])
    register(parser.add_subparsers(dest="mode", metavar="<mode>"))
    parser.set_defaults(func=None)
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return EXIT_PARAM
    if not attest(args):
        return EXIT_COMPLIANCE
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
