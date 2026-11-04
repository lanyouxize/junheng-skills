#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公共基础设施：退出码 / 事件流 / 日志 / 配置 / 合规闸 / JSONL / 礼貌延迟。

退出码与事件 level 1:1 映射（SPEC §8）：
    ok/info -> 0    warn/partial -> 5    error -> 3
    compliance -> 4    param -> 2    env -> 6
"""
from __future__ import annotations

import importlib
import json
import logging
import random
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

# ------------------------------------------------------------------ 退出码
EXIT_OK = 0
EXIT_PARAM = 2
EXIT_ERROR = 3
EXIT_COMPLIANCE = 4
EXIT_PARTIAL = 5
EXIT_ENV = 6

# ------------------------------------------------------------------ 事件 level
LEVEL_OK = "ok"
LEVEL_INFO = "info"
LEVEL_WARN = "warn"
LEVEL_PARTIAL = "partial"
LEVEL_ERROR = "error"
LEVEL_COMPLIANCE = "compliance"
LEVEL_PARAM = "param"
LEVEL_ENV = "env"

_LEVEL_EXIT = {
    LEVEL_OK: EXIT_OK,
    LEVEL_INFO: EXIT_OK,
    LEVEL_WARN: EXIT_PARTIAL,
    LEVEL_PARTIAL: EXIT_PARTIAL,
    LEVEL_ERROR: EXIT_ERROR,
    LEVEL_ENV: EXIT_ENV,
    LEVEL_PARAM: EXIT_PARAM,
    LEVEL_COMPLIANCE: EXIT_COMPLIANCE,
}

COMPLIANCE_BANNER = (
    "合规声明：本工具仅限采集你本人自有或已获明确授权的公众号内容；"
    "继续运行即表示你确认对目标内容拥有采集与归档权利。"
)

DEFAULT_CONFIG: dict[str, Any] = {
    "rate_limit": {"min_delay_seconds": 3.0, "max_delay_seconds": 8.0, "max_per_day": 200},
    "library": {
        # library skill 的 space_api.py CLI 入口（写库转发器）；可用配置覆盖
        "api_cli": r"D:\workbuddy安装运行位置\resources\app.asar.unpacked\resources\plugins\workbuddy-builtin\skills\library\space_api.py",
        "node_id": "",
        "node_title": "",
        "space": "铭衍·元典",
        "database_name_prefix": "公众号采集归档",
        "batch_size": 50,
    },
    "l2": {"cookie_file": ""},
    "l3": {"wechat_path": "", "proxy_port": 8080},
    "exe": {"path": "", "output_dir": ""},
    "compliance": {"attestation": "collector-attestation: authorized-only"},
    "vault": {
        # B4 双写目标（默认关；--vault 显式开启，或本配置 enabled=true 常驻开启）
        "enabled": False,
        "root": r"D:\workbuddy重做系统后版本\2026-10-16-21-12-03\vault",
        "auto_apply": True,
    },
}


# ------------------------------------------------------------------ 基础
def now_iso() -> str:
    """UTC ISO8601（秒级、Z 后缀）——确定性输出，禁本地时区。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id() -> str:
    """随机 collectId（hex）。"""
    return uuid.uuid4().hex


def get_logger(name: str, level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(getattr(logging, str(level).upper(), logging.INFO))
        logger.propagate = False
    return logger


def emit_event(level: str, event: str, **fields: Any) -> None:
    """向 stderr 写一行 JSONL 事件（进度/告警，机器可读；stdout 只留给数据）。"""
    payload: dict[str, Any] = {"ts": now_iso(), "level": level, "event": event}
    payload.update(fields)
    print(json.dumps(payload, ensure_ascii=False), file=sys.stderr, flush=True)


def exit_code_for(level: str) -> int:
    return _LEVEL_EXIT.get(level, EXIT_ERROR)


def lazy_import(module_name: str, hint: str) -> Any:
    """延迟导入第三方依赖；缺失时抛出带安装指引的 RuntimeError。"""
    try:
        return importlib.import_module(module_name)
    except ImportError as exc:
        raise RuntimeError(f"缺少依赖 {module_name}：{hint}") from exc


# ------------------------------------------------------------------ 配置
def load_config(path: str | None) -> dict[str, Any]:
    """加载 YAML 配置并与 DEFAULT_CONFIG 深合并；无路径/文件不存在时返回默认配置。"""
    config = _deep_copy(DEFAULT_CONFIG)
    if not path:
        return config
    cfg_path = Path(path)
    if not cfg_path.is_file():
        emit_event(LEVEL_WARN, "config.missing", path=str(cfg_path))
        return config
    yaml = lazy_import("yaml", "pip install pyyaml")
    try:
        loaded = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"YAML 解析失败: {cfg_path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ValueError(f"配置文件顶层必须是对象: {cfg_path}")
    _deep_merge(config, loaded)
    return config


def _deep_copy(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _deep_copy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_deep_copy(item) for item in value]
    return value


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


# ------------------------------------------------------------------ 合规闸
def attest(args: Any) -> bool:
    """合规闸（AC-10）：打印声明；--yes 或交互确认后放行，否则调用方应返回 EXIT_COMPLIANCE。"""
    print(COMPLIANCE_BANNER, flush=True)
    if bool(getattr(args, "yes", False)):
        return True
    if not sys.stdin or not sys.stdin.isatty():
        emit_event(LEVEL_COMPLIANCE, "compliance.blocked", reason="非交互会话且未提供 --yes")
        return False
    try:
        answer = input("确认已获授权并继续？输入 yes 继续：").strip().lower()
    except EOFError:
        emit_event(LEVEL_COMPLIANCE, "compliance.blocked", reason="输入流结束")
        return False
    if answer not in {"yes", "y"}:
        emit_event(LEVEL_COMPLIANCE, "compliance.blocked", reason="用户未确认")
        return False
    return True


# ------------------------------------------------------------------ 媒体下载（L1/L2/L3 共用）
# 桌面 Chrome UA：公众号页对默认 headless UA 有环境校验，沿用真实浏览器标识
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
ALLOWED_IMAGE_EXTS = frozenset({"jpg", "jpeg", "png", "gif", "webp", "bmp"})
# mmbiz URL 的目录名暗含格式（mmbiz_jpg/mmbiz_png/...），优先于路径后缀
_MMBIZ_TOKENS = (
    ("mmbiz_webp", "webp"),
    ("mmbiz_png", "png"),
    ("mmbiz_gif", "gif"),
    ("mmbiz_jpg", "jpg"),
)
_MEDIA_REFERER = "https://mp.weixin.qq.com/"


def guess_image_ext(url: str) -> str:
    """推断图片扩展名：wx_fmt 查询参数 > mmbiz_* 目录标记 > 路径后缀 > 默认 jpg。"""
    from urllib.parse import parse_qs, urlsplit

    query = parse_qs(urlsplit(url).query)
    formats = query.get("wx_fmt") or []
    fmt = (formats[0] if formats else "").lower()
    if fmt == "jpeg":
        return "jpg"
    if fmt in ALLOWED_IMAGE_EXTS:
        return fmt
    lowered = url.lower()
    for token, ext in _MMBIZ_TOKENS:
        if token in lowered:
            return ext
    suffix = Path(urlsplit(url).path).suffix.lower().lstrip(".")
    if suffix == "jpeg":
        return "jpg"
    if suffix in ALLOWED_IMAGE_EXTS:
        return suffix
    return "jpg"


def download_file(session: Any, url: str, dest: Path, timeout: int,
                  referer: str = _MEDIA_REFERER) -> None:
    """用桌面 UA + 公众号 Referer 下载单个文件到 dest（失败抛异常，由调用方决定降级）。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    response = session.get(url, headers={"User-Agent": BROWSER_UA, "Referer": referer},
                           timeout=timeout)
    response.raise_for_status()
    dest.write_bytes(response.content)


# ------------------------------------------------------------------ 频率
def sleep_polite(config: dict[str, Any], jitter: bool = True) -> float:
    """按 rate_limit 配置休眠（默认 3–8s 抖动），返回实际休眠秒数。"""
    rate = config.get("rate_limit") or {}
    low = float(rate.get("min_delay_seconds", 3.0))
    high = float(rate.get("max_delay_seconds", 8.0))
    if high < low:
        low, high = high, low
    seconds = random.uniform(low, high) if jitter else low
    time.sleep(seconds)
    return seconds


# ------------------------------------------------------------------ JSONL
def write_jsonl(path: str | None, records: Iterable[dict]) -> int:
    """写 JSONL；path 为空时写 stdout。返回记录数。"""
    count = 0
    stream = open(path, "w", encoding="utf-8") if path else sys.stdout
    try:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
        stream.flush()
    finally:
        if path:
            stream.close()
    return count


def read_jsonl(path: str) -> Iterator[dict]:
    """逐行读 JSONL；坏行告警跳过，不静默。"""
    with open(path, "r", encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, 1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                record = json.loads(stripped)
            except json.JSONDecodeError as exc:
                emit_event(LEVEL_WARN, "jsonl.bad_line", line=lineno, error=str(exc))
                continue
            if isinstance(record, dict):
                yield record
            else:
                emit_event(LEVEL_WARN, "jsonl.not_object", line=lineno)
