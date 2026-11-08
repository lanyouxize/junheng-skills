import logging
logger = logging.getLogger(__name__)

# -*- coding: utf-8 -*-
"""
记忆管家 V3.0 - 核心记忆分析入口
记忆搜索/分级/加载已拆分至 core_search.py / core_rank.py / core_load.py（降低单文件长度）。
本模块保留 analyze_memory，并重新导出 search_memory / rank_memory / load_memory，
使 `from .core import ...` 的既有调用方无需改动。
"""

from datetime import datetime
from pathlib import Path

from .config import (
    VERSION, _, MAX_TOTAL_READ, MAX_REPORT_ITEMS,
    MEMORY_LARGE_SIZE_KB, MEMORY_MANY_FILES,
    iter_memory_files,
)
from .core_search import search_memory
from .core_rank import rank_memory, RANK_CACHE_FILE
from .core_load import load_memory, _auto_compact


def _analyze_file_entry(md_file, mtime, size_kb, rel_path, age):
    """构造单文件分析条目（含可清理判定、子目录分组）。"""
    is_cleanable = md_file.name != "MEMORY.md" and age > 30
    parts = Path(rel_path).parts
    folder = parts[0] if len(parts) > 1 else "/"
    entry = {
        "name": md_file.name,
        "path": rel_path,
        "folder": folder,
        "size_kb": round(size_kb, 2),
        "modified": mtime.strftime("%Y-%m-%d"),
        "age_days": age,
        "cleanable": is_cleanable
    }
    return entry, is_cleanable, folder


def _analyze_update_stats(result, entry, folder, size_kb):
    """把单文件条目累计进 stats（总数/体积/可清理/按文件夹）。"""
    result["stats"]["total_files"] += 1
    result["stats"]["total_size_kb"] += size_kb
    if entry["cleanable"]:
        result["stats"]["cleanable_files"] += 1
        result["stats"]["cleanable_size_kb"] += size_kb
    by_folder = result["stats"]["by_folder"]
    if folder not in by_folder:
        by_folder[folder] = {"files": 0, "size_kb": 0}
    by_folder[folder]["files"] += 1
    by_folder[folder]["size_kb"] += size_kb


def analyze_memory(workspace_path, age_days=None, exclude_patterns=None):
    base_path = Path(workspace_path).resolve()
    memory_path = base_path / ".workbuddy" / "memory"
    result = {
        "version": VERSION,
        "workspace": workspace_path,
        "timestamp": datetime.now().isoformat(),
        "files": [],
        "stats": {
            "total_files": 0,
            "total_size_kb": 0,
            "cleanable_files": 0,
            "cleanable_size_kb": 0,
            "by_folder": {}
        },
        "recommendations": [],
        "warnings": []
    }

    if not memory_path.exists():
        result["error"] = _("memory_dir_not_exist")
        return result

    if exclude_patterns is None:
        exclude_patterns = []

    total_read = 0

    try:
        for md_file, mtime, size_kb, rel_path in iter_memory_files(
                memory_path, skip_memory_md=False, include_dirs=True):
            if total_read + int(size_kb * 1024) > MAX_TOTAL_READ:
                result["warnings"].append(_("scan_warning_limit").format(limit=MAX_TOTAL_READ // 1024))
                break

            age = (datetime.now() - mtime).days
            if age_days is not None and age > age_days:
                continue

            entry, _ign, folder = _analyze_file_entry(md_file, mtime, size_kb, rel_path, age)
            result["files"].append(entry)
            _analyze_update_stats(result, entry, folder, size_kb)

            if len(result["files"]) >= MAX_REPORT_ITEMS:
                result["warnings"].append(_("files_over_limit").format(limit=MAX_REPORT_ITEMS))
                break

        result["recommendations"] = _generate_recommendations(result["files"], result["stats"])

    except Exception as e:
        result["error"] = _("analyze_failed").format(error=f"{type(e).__name__}: {str(e)}")

    return result


def _generate_recommendations(files, stats):
    recs = []

    if stats["total_size_kb"] > MEMORY_LARGE_SIZE_KB:
        recs.append(_("rec_large_memory").format(size=f"{stats['total_size_kb']:.1f}"))

    if stats["total_files"] > MEMORY_MANY_FILES:
        recs.append(_("rec_many_files").format(count=stats['total_files']))

    cleanable_count = stats.get("cleanable_files", 0)
    if cleanable_count > 0:
        recs.append(_("rec_cleanable_count").format(count=cleanable_count))

    if not recs:
        recs.append(_("rec_good_state"))

    return recs
