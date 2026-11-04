# -*- coding: utf-8 -*-
"""
记忆管家 V3.0 - 记忆分级（rank）
从 core.py 拆分（降低单文件长度 file>800 硬限 P1）。
"""
import hashlib
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

from .config import (
    VERSION, _, SUMMARY_DIR, SUMMARY_INDEX_FILE,
    RANK_CORE_THRESHOLD, RANK_NORMAL_THRESHOLD,
    is_symlink, iter_memory_files,
)

logger = logging.getLogger(__name__)


# ============ 4.2 排序复用的磁盘缓存 ============
RANK_CACHE_FILE = "rank_cache.json"


def _rank_signature(memory_path, access_counts, weights):
    """目录签名：文件集合(mtime/size/路径) + 访问计数 + 权重 + 版本。

    任一输入变化即改变签名 → 缓存失效重算。排序结果仅由这些输入决定，
    故签名相同即可安全复用历史分级，跳过全量 I/O 与重算。

    关键：必须用「实时 stat」而非 lru 缓存的 get_file_info——否则同进程内
    原地修改文件会因缓存命中而算出不降费签名，导致缓存永不失效。
    """
    h = hashlib.sha256()
    h.update(VERSION.encode("utf-8"))
    h.update(json.dumps(weights, sort_keys=True).encode("utf-8"))
    entries = []
    if memory_path.exists():
        for md_file in memory_path.rglob("*.md"):
            if is_symlink(md_file):
                continue
            try:
                md_file.resolve().relative_to(memory_path.resolve())
            except ValueError:
                continue
            try:
                st = md_file.stat()
            except OSError:
                continue
            entries.append((str(md_file.relative_to(memory_path)), st.st_mtime, st.st_size / 1024))
    for rel_path, mtime, size_kb in sorted(entries, key=lambda x: x[0]):
        h.update(f"{rel_path}\x00{int(mtime)}\x00{round(size_kb, 3)}".encode("utf-8"))
    h.update(json.dumps(access_counts, sort_keys=True).encode("utf-8"))
    return h.hexdigest()


def _load_rank_cache(cache_file, signature):
    try:
        if not cache_file.exists():
            return None
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("signature") != signature:
            return None
        items = data.get("items")
        if not isinstance(items, list):
            return None
        return items
    except (json.JSONDecodeError, OSError, ValueError, KeyError):
        return None


def _save_rank_cache(cache_file, signature, items):
    """原子写入 rank 缓存（先临时文件再 rename，防止并发读半截文件）。"""
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache_file.with_suffix(".tmp")
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({"version": VERSION, "signature": signature, "items": items},
                      f, ensure_ascii=False, indent=2)
        os.replace(tmp, cache_file)
    except (OSError, IOError) as e:
        logger.warning("non-fatal: %s", e)


def _bucket_rank_items(items, cutoff_date, folder):
    """按 score 分级 + 应用 days/folder 过滤（缓存命中与全新计算共用）。

    内部字段 _mtime_epoch 用于 days 过滤，分级后从输出条目中剔除，不泄露。
    """
    core, normal, cold = [], [], []
    for it in items:
        mtime_epoch = it.get("_mtime_epoch")
        if cutoff_date is not None and mtime_epoch is not None and mtime_epoch < cutoff_date.timestamp():
            continue
        if folder and it.get("folder", "/") != folder:
            continue
        s = it.get("score", 0)
        if s >= RANK_CORE_THRESHOLD * 100:
            bucket = core
        elif s >= RANK_NORMAL_THRESHOLD * 100:
            bucket = normal
        else:
            bucket = cold
        it.pop("_mtime_epoch", None)
        bucket.append(it)
    core.sort(key=lambda x: x["score"], reverse=True)
    normal.sort(key=lambda x: x["score"], reverse=True)
    cold.sort(key=lambda x: x["score"], reverse=True)
    return core, normal, cold


def _rank_default_weights():
    return {"access": 0.4, "recency": 0.3, "length": 0.15, "keywords": 0.15}


def _rank_load_access_counts(index_file):
    """读取 summary 索引中的 access_counts；缺失/损坏返回 {}。"""
    if not index_file.exists():
        return {}
    try:
        with open(index_file, 'r', encoding='utf-8') as f:
            index_data = json.load(f)
        return index_data.get("access_counts", {})
    except (json.JSONDecodeError, OSError, IOError):
        return {}


def _rank_score_item(md_file, mtime, size_kb, rel_path, access_counts, weights, summary_path):
    """计算单文件分级条目（含内部 _mtime_epoch）。"""
    age_days = (datetime.now() - mtime).days
    size_kb = size_kb or 0
    access_score = min(100, access_counts.get(md_file.name, 0) * 20)
    recency_score = max(0, 100 - age_days * 2)

    if size_kb < 0.5:
        length_score = size_kb * 100
    elif size_kb > 10:
        length_score = max(0, 100 - (size_kb - 10) * 5)
    else:
        length_score = 100

    keyword_score = 50
    summary_file = summary_path / f"{md_file.stem}.summary"
    if summary_file.exists():
        try:
            with open(summary_file, 'r', encoding='utf-8') as f:
                summary_data = json.load(f)
        except (json.JSONDecodeError, OSError, IOError):
            summary_data = {}
        # keywords 提取必须在 try/except 之外，否则仅在异常时执行
        if summary_data.get("keywords", []):
            keyword_score = 70

    total_score = (
        access_score * weights["access"] +
        recency_score * weights["recency"] +
        length_score * weights["length"] +
        keyword_score * weights["keywords"]
    ) / 100

    info = {
        "file": md_file.name,
        "path": rel_path,
        "folder": Path(rel_path).parts[0] if len(Path(rel_path).parts) > 1 else "/",
        "score": round(total_score, 2),
        "size_kb": round(size_kb, 2),
        "age_days": age_days,
        "modified": mtime.strftime("%Y-%m-%d"),
        "details": {
            "access_score": round(access_score, 1),
            "recency_score": round(recency_score, 1),
            "length_score": round(length_score, 1),
            "keyword_score": round(keyword_score, 1)
        }
    }
    info["_mtime_epoch"] = mtime.timestamp()  # 仅供 days 过滤，不入缓存外的输出
    return info


def _rank_compute(memory_path, summary_path, access_counts, weights, use_cache=True):
    """全量重算并落磁盘缓存；返回统一条目列表（含内部 _mtime_epoch）。"""
    normalized = []
    store_items = []
    for md_file, mtime, size_kb, rel_path in iter_memory_files(memory_path):
        info = _rank_score_item(md_file, mtime, size_kb, rel_path, access_counts, weights, summary_path)
        normalized.append(info)
        store_items.append(dict(info))

    if use_cache:
        sig = _rank_signature(memory_path, access_counts, weights)
        _save_rank_cache(summary_path / RANK_CACHE_FILE, sig, store_items)
    return normalized


def _rank_normalize_cached(cached):
    """缓存命中：重算 age_days/modified，保留 _mtime_epoch 供 days 过滤。"""
    now = datetime.now()
    normalized = []
    for it in cached:
        mtime_epoch = it.get("_mtime_epoch")
        if mtime_epoch is not None:
            mtime = datetime.fromtimestamp(mtime_epoch)
            it["age_days"] = (now - mtime).days
            it["modified"] = mtime.strftime("%Y-%m-%d")
        normalized.append(it)
    return normalized


def rank_memory(workspace_path, weights=None, days=None, folder=None, use_cache=True):
    base_path = Path(workspace_path).resolve()
    memory_path = base_path / ".workbuddy" / "memory"

    if weights is None:
        weights = _rank_default_weights()

    result = {
        "version": VERSION,
        "timestamp": datetime.now().isoformat(),
        "days_filter": days,
        "folder_filter": folder,
        "core": [],
        "normal": [],
        "cold": [],
        "stats": {
            "total": 0,
            "core_count": 0,
            "normal_count": 0,
            "cold_count": 0
        }
    }

    if not memory_path.exists():
        result["error"] = _("memory_dir_not_exist")
        return result

    cutoff_date = None
    if days is not None:
        cutoff_date = datetime.now() - timedelta(days=days)

    summary_path = base_path / ".workbuddy" / SUMMARY_DIR
    index_file = summary_path / SUMMARY_INDEX_FILE
    access_counts = _rank_load_access_counts(index_file)

    # ---- 4.2 排序复用：目录签名命中时反序列化，跳过全量 I/O + 重算 ----
    normalized = None
    if use_cache:
        sig = _rank_signature(memory_path, access_counts, weights)
        cached = _load_rank_cache(summary_path / RANK_CACHE_FILE, sig)
        if cached is not None:
            normalized = _rank_normalize_cached(cached)

    if normalized is None:
        normalized = _rank_compute(memory_path, summary_path, access_counts, weights, use_cache)

    core, normal, cold = _bucket_rank_items(normalized, cutoff_date, folder)
    result["core"] = core
    result["normal"] = normal
    result["cold"] = cold
    result["stats"]["total"] = len(core) + len(normal) + len(cold)
    result["stats"]["core_count"] = len(core)
    result["stats"]["normal_count"] = len(normal)
    result["stats"]["cold_count"] = len(cold)

    return result
