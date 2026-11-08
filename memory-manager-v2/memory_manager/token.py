import logging
logger = logging.getLogger(__name__)

# -*- coding: utf-8 -*-
"""
记忆管家 V3.0 - Token预算检查、统计与哈希计算
来源: memory_manager.py (hash/token/trends)
V3.0: 模块化重构
"""

import hashlib
import json
import os
import tempfile
from datetime import datetime, date, timedelta
from functools import lru_cache
from pathlib import Path

import re

from .config import VERSION, DEFAULT_DAILY_BUDGET, TOKEN_ALERT_RATIO, TOKEN_WARN_RATIO, _


def compute_content_hash(file_path):
    """计算文件内容SHA256哈希"""
    try:
        with open(file_path, 'rb') as f:
            return hashlib.sha256(f.read(50 * 1024)).hexdigest()
    except (OSError, IOError, PermissionError):
        return ""


def get_token_stats_dir(workspace_path):
    base_path = Path(workspace_path).resolve()
    stats_dir = base_path / ".workbuddy" / ".token_stats"
    stats_dir.mkdir(parents=True, exist_ok=True)
    return stats_dir


def record_token_usage(workspace_path, tokens, operation="load"):
    stats_dir = get_token_stats_dir(workspace_path)
    today = datetime.now().date().isoformat()
    stats_file = stats_dir / (today + ".json")
    # 读取已有统计；文件缺失/损坏/结构异常时回退为空白模板。
    # （3.5 边界：并发写或旧文件损坏不应导致崩溃；原子写入保证读取端不会看到半截文件）
    try:
        if stats_file.exists():
            data = json.loads(stats_file.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or "operations" not in data:
                raise ValueError("malformed stats")
            stats = data
        else:
            stats = {"date": today, "operations": {}}
    except (json.JSONDecodeError, OSError, ValueError, KeyError):
        stats = {"date": today, "operations": {}}
    if operation not in stats["operations"]:
        stats["operations"][operation] = {"count": 0, "tokens": 0}
    stats["operations"][operation]["count"] += 1
    stats["operations"][operation]["tokens"] += tokens
    # 原子性写入：先写临时文件再 rename，防止并发丢数据
    try:
        fd, tmp_path = tempfile.mkstemp(dir=str(stats_dir), suffix=".tmp")
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, str(stats_file))
    except (OSError, IOError):
        # 原子写入失败时回退到直接写入
        stats_file.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    return stats


def token_check(workspace_path, budget=DEFAULT_DAILY_BUDGET):
    workspace = Path(workspace_path).resolve()
    stats_dir = workspace / ".workbuddy" / ".token_stats"
    today = date.today().isoformat()
    today_file = stats_dir / f"{today}.json"

    today_tokens = 0
    if today_file.exists():
        try:
            data = json.loads(today_file.read_text(encoding="utf-8"))
            for op in data.get("operations", {}).values():
                today_tokens += int(op.get("tokens", 0))
        except (json.JSONDecodeError, OSError, KeyError) as e:
            logger.warning("non-fatal: %s", e)


    ratio = today_tokens / max(budget, 1)

    if ratio >= TOKEN_ALERT_RATIO:
        level, emoji, message = "red", "🔴", _("token_alert").format(today=today_tokens, budget=budget, pct=ratio*100)
    elif ratio >= TOKEN_WARN_RATIO:
        level, emoji, message = "yellow", "🟡", _("token_warn").format(today=today_tokens, budget=budget, pct=ratio*100)
    else:
        level, emoji, message = "green", "🟢", _("token_ok").format(today=today_tokens, budget=budget, pct=ratio*100)

    return {
        "today": today,
        "today_tokens": today_tokens,
        "budget": budget,
        "ratio": round(ratio, 2),
        "level": level,
        "emoji": emoji,
        "message": message,
        "note": _("token_estimated_note"),
    }


def _token_trends_read_daily(stats_dir, cutoff):
    """读取 cutoff 之后的每日 token/操作统计。返回 (daily, total_tokens, total_ops)。"""
    daily = []
    total_tokens = 0
    total_ops = 0
    if not stats_dir.exists():
        return daily, total_tokens, total_ops
    for stat_file in sorted(stats_dir.glob("*.json")):
        try:
            file_date = date.fromisoformat(stat_file.stem)
        except ValueError:
            continue
        if file_date < cutoff:
            continue
        day_tokens = 0
        day_ops = 0
        try:
            data = json.loads(stat_file.read_text(encoding="utf-8"))
            for op_data in data.get("operations", {}).values():
                day_tokens += int(op_data.get("tokens", 0))
                day_ops += int(op_data.get("count", 0))
        except (json.JSONDecodeError, OSError, KeyError, ValueError):
            continue
        daily.append({
            "date": file_date.isoformat(),
            "tokens": day_tokens,
            "operations_count": day_ops,
        })
        total_tokens += day_tokens
        total_ops += day_ops
    return daily, total_tokens, total_ops


def _token_trends_aggregate(period, daily):
    """按 period 聚合每日数据：daily=原样、week=按周、month=按月。"""
    if period == "daily":
        return daily
    if period == "week":
        buckets = {}
        for d in daily:
            dt = date.fromisoformat(d["date"])
            key = (dt - timedelta(days=dt.weekday())).isoformat()
            b = buckets.setdefault(key, {"tokens": 0, "operations_count": 0})
            b["tokens"] += d["tokens"]
            b["operations_count"] += d["operations_count"]
        return [{"label": f"{k} ~", "tokens": buckets[k]["tokens"],
                 "operations_count": buckets[k]["operations_count"]} for k in sorted(buckets)]
    if period == "month":
        buckets = {}
        for d in daily:
            key = date.fromisoformat(d["date"]).strftime("%Y-%m")
            b = buckets.setdefault(key, {"tokens": 0, "operations_count": 0})
            b["tokens"] += d["tokens"]
            b["operations_count"] += d["operations_count"]
        return [{"label": k, "tokens": buckets[k]["tokens"],
                 "operations_count": buckets[k]["operations_count"]} for k in sorted(buckets)]
    return []


def token_trends(workspace_path, period="week", days_back=None):
    """聚合 Token 消耗趋势（按周/月）

    Args:
        workspace_path: 工作空间路径
        period: "week" | "month" | "daily"
        days_back: 回溯天数，默认 7(week)/30(month)/14(daily)

    Returns:
        dict: {period, days_back, daily: [{date, tokens, operations}],
               aggregated: [{label, tokens, operations_count}], totals}
    """
    workspace = Path(workspace_path).resolve()
    stats_dir = workspace / ".workbuddy" / ".token_stats"

    if days_back is None:
        days_back = {"week": 7, "month": 30, "daily": 14}.get(period, 7)

    cutoff = date.today() - timedelta(days=days_back)
    daily, total_tokens, total_ops = _token_trends_read_daily(stats_dir, cutoff)
    aggregated = _token_trends_aggregate(period, daily)
    avg_daily = total_tokens // max(len(daily), 1)

    return {
        "period": period,
        "days_back": days_back,
        "daily": daily,
        "aggregated": aggregated,
        "totals": {
            "days_with_data": len(daily),
            "total_tokens": total_tokens,
            "total_operations": total_ops,
            "avg_daily_tokens": avg_daily,
        },
    }


# ============ Token 估算核心（V3.1 计量精准化） ============
# 模型 → tiktoken 编码名；不在表中的模型回退到 cl100k_base（GPT-3.5/4 通用）
_MODEL_ENCODING = {
    "gpt-3.5-turbo": "cl100k_base",
    "gpt-3.5-turbo-16k": "cl100k_base",
    "gpt-4": "cl100k_base",
    "gpt-4-32k": "cl100k_base",
    "gpt-4-turbo": "cl100k_base",
    "gpt-4o": "o200k_base",
    "gpt-4o-mini": "o200k_base",
    "gpt-4.1": "o200k_base",
    "gpt-4.1-mini": "o200k_base",
}

# 回退启发式系数（无 tiktoken / 离线时使用）
_CJK_RATIO = 0.6        # CJK 字符（含全角标点/假名）≈ 0.6 token/字
_NON_CJK_RATIO = 0.25   # 非 CJK（ASCII/拉丁）≈ 4 字/token

# 磁盘字节 → token 折算系数（仅用于「只有文件大小、无文本内容」的场景，如 clean 节省估算）
# 0.2 token/字节 ≈ 中文 3 字节/字 × 0.2 = 0.6 token/字，与 CJK 字符口径量级一致
TOKEN_PER_BYTE = 0.2

# 匹配 CJK 汉字、全角标点、日文假名等「宽字符」（真实 tokenizer 通常 1 token/字）
_CJK_RE = re.compile(
    r'[\u3000-\u303f\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]'
)

_ENCODING_CACHE = {}


def _get_encoding(model):
    """获取 tiktoken 编码；不可用或模型未知时返回 None。"""
    if model in _ENCODING_CACHE:
        return _ENCODING_CACHE[model]
    enc = None
    try:
        import tiktoken
        enc = tiktoken.get_encoding(_MODEL_ENCODING.get(model, "cl100k_base"))
    except Exception:
        enc = None
    _ENCODING_CACHE[model] = enc
    return enc


@lru_cache(maxsize=512)
def _estimate_fallback_cached(text):
    """4.3 离线回退估算缓存：相同文本不重复计算 CJK 启发式。

    仅在 tiktoken 不可用时命中；文本差异大时缓存命中率低，但冷加载
    重复估算同一记忆时收益明显。lru_cache 上限 512 防止长文本内存膨胀。
    """
    cjk = len(_CJK_RE.findall(text))
    non_cjk = len(text) - cjk
    return int(round(cjk * _CJK_RATIO + non_cjk * _NON_CJK_RATIO))


def estimate_tokens(text, model=None):
    """估算文本 token 数（字符口径，优先真实分词）。

    - 若 tiktoken 可用：按模型选择编码真实分词（GPT-4o 用 o200k，其余用 cl100k）。
    - 不可用（离线/未安装）时回退 CJK 感知启发式（带缓存，见 _estimate_fallback_cached）：
      CJK≈0.6 token/字，非CJK≈0.25 token/字。
    空文本返回 0。结果随模型/标尺变化——属「估算」性质，输出已标注。
    """
    if not text:
        return 0
    enc = _get_encoding(model)
    if enc is not None:
        try:
            return len(enc.encode(text))
        except Exception as e:
            logger.warning("non-fatal: %s", e)

    return _estimate_fallback_cached(text)


def kb_to_tokens(size_kb):
    """将磁盘 KB（字节/1024）折算为 token 估算。

    仅用于没有文本内容、只有文件大小的场景（如 clean 删除/归档的节省估算）。
    采用统一字节口径 TOKEN_PER_BYTE，与 estimate_tokens 字符口径在混合
    中英文下量级一致；本就标注为「估算」，非精确值。
    """
    if not size_kb:
        return 0
    return int((size_kb * 1024) * TOKEN_PER_BYTE)
