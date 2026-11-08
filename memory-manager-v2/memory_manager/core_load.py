# -*- coding: utf-8 -*-
"""
记忆管家 V3.0 - 记忆加载（load）
从 core.py 拆分（降低单文件长度 file>800 硬限 P1）。
"""
import json
import logging
import os
from datetime import datetime
from pathlib import Path

from .config import (
    VERSION, _, SUMMARY_DIR, MAX_OUTPUT_CHARS, MAX_TOTAL_READ,
    SUMMARY_MIN_CHARS, DEFAULT_DAILY_BUDGET,
    LOAD_BRIEF, LOAD_NORMAL, LOAD_FULL,
    is_symlink, safe_file_read, get_file_info, iter_memory_files,
)
from .summarize import generate_summary, extract_keywords, smart_truncate
from .token import record_token_usage, estimate_tokens
from .core_rank import rank_memory
from .core_search import _relevance_score
from .core_selector import recency_factor

logger = logging.getLogger(__name__)


def _read_summary_file(summary_path, stem):
    summary_file = summary_path / f"{stem}.summary"
    if not summary_file.exists():
        return None
    try:
        with open(summary_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _persist_summary(md_file, summary_path, content):
    """4.1b 写穿透：冷加载缺失 summary 时实时生成并原子落盘，使二载命中缓存。

    返回生成的 summary_data；落盘失败（权限等）不影响本次返回，仅下次不再命中。
    """
    summary = generate_summary(content)
    keywords = extract_keywords(content)
    mtime, size_kb = get_file_info(md_file)
    summary_data = {
        "file": md_file.name,
        "summary": summary,
        "keywords": keywords,
        "size_kb": size_kb,
        "modified": mtime.strftime("%Y-%m-%d") if mtime else "unknown",
        "generated": datetime.now().isoformat(),
        "token_estimate": estimate_tokens(summary),
    }
    try:
        summary_file = summary_path / f"{md_file.stem}.summary"
        tmp = summary_file.with_suffix(".summary.tmp")
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(summary_data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, summary_file)
    except (OSError, IOError) as e:
        logger.warning("non-fatal: %s", e)

    return summary_data


def _truncate_text(text, max_chars=MAX_OUTPUT_CHARS):
    return text if len(text) <= max_chars else text[:max_chars] + "..."


def _load_brief(md_file, summary_path, entry_base, persist_on_miss):
    summary_data = _read_summary_file(summary_path, md_file.stem)
    if summary_data:
        body = _truncate_text(summary_data.get("summary", ""))
        # 4.4 读取短路：summary 已命中且明显短于全文时，跳过读取全文
        if len(body) >= SUMMARY_MIN_CHARS:
            content, _read_err = safe_file_read(md_file)
            if content and len(body) >= len(content):
                return {**entry_base, "type": "truncated", "content": smart_truncate(content, SUMMARY_MIN_CHARS),
                        "keywords": [], "token_estimate": estimate_tokens(content)}
        return {**entry_base, "type": "summary", "content": body,
                "keywords": summary_data.get("keywords", []),
                "token_estimate": summary_data.get("token_estimate", 0)}
    # 冷路径：summary 缺失，实时生成
    content, _read_err = safe_file_read(md_file)
    if content is None:
        return None
    if persist_on_miss:
        sd = _persist_summary(md_file, summary_path, content)
        return {**entry_base, "type": "summary", "content": _truncate_text(sd["summary"]),
                "keywords": sd.get("keywords", []),
                "token_estimate": sd.get("token_estimate", 0)}
    summary = generate_summary(content, SUMMARY_MIN_CHARS)
    return {**entry_base, "type": "summary", "content": _truncate_text(summary),
            "keywords": extract_keywords(content),
            "token_estimate": estimate_tokens(summary)}


def _load_normal(md_file, summary_path, entry_base):
    content, _read_err = safe_file_read(md_file)
    if content is None:
        return None
    summary_data = _read_summary_file(summary_path, md_file.stem)
    if not summary_data:
        # 4.1b 写穿透：normal 冷路径同样落盘
        summary_data = _persist_summary(md_file, summary_path, content)
    summary = summary_data.get("summary", "") if summary_data else generate_summary(content, 500)
    key_lines = [l for l in content.split('\n') if l.strip().startswith(('-', '*'))][:5]
    extra = '\n'.join(key_lines)
    body = summary[:200] + ("\n\n关键要点:\n" + extra[:100] if extra else "")
    return {**entry_base, "type": "summary+keys", "content": _truncate_text(body, MAX_OUTPUT_CHARS),
            "keywords": summary_data.get("keywords", extract_keywords(content)),
            "token_estimate": estimate_tokens(body)}


def _load_full(md_file, entry_base):
    content, _read_err = safe_file_read(md_file)
    if content is None:
        return None
    return {**entry_base, "type": "full",
            "content": content[:5000] if len(content) > 5000 else content,
            "token_estimate": estimate_tokens(content)}


def _load_memory_file(md_file, load_mode, summary_path, persist_on_miss=True):
    """按 load_mode 加载单文件：brief=摘要/短路、normal=摘要+关键要点、full=原文。"""
    if is_symlink(md_file):
        return None
    mtime, size_kb = get_file_info(md_file)
    if mtime is None:
        return None
    entry_base = {
        "file": md_file.name,
        "path": str(md_file),
        "load_mode": load_mode,
        "modified": mtime.strftime("%Y-%m-%d"),
    }
    if load_mode == LOAD_BRIEF:
        return _load_brief(md_file, summary_path, entry_base, persist_on_miss)
    if load_mode == LOAD_NORMAL:
        return _load_normal(md_file, summary_path, entry_base)
    return _load_full(md_file, entry_base)


def _default_load_list(rank_result, memory_path, mode, limit):
    """默认分级加载列表：core→full、normal→mode、cold→brief（1.2 回退路径）。"""
    files_to_load = []
    for item in rank_result.get("core", [])[:limit]:
        files_to_load.append((memory_path / item["file"], LOAD_FULL))

    normal_limit = limit - len(files_to_load)
    for item in rank_result.get("normal", [])[:max(0, normal_limit)]:
        files_to_load.append((memory_path / item["file"], mode))

    cold_limit = limit - len(files_to_load)
    for item in rank_result.get("cold", [])[:max(0, cold_limit)]:
        files_to_load.append((memory_path / item["file"], LOAD_BRIEF))
    return files_to_load


def _relevance_files_to_load(query, tags, rank_result, memory_path, limit, summary_path):
    """按任务相关性排序取 top（1.2 语义化加载）；无命中返回 None 触发回退。"""
    candidates = []
    for bucket in ("core", "normal", "cold"):
        for item in rank_result.get(bucket, []):
            candidates.append(memory_path / item["file"])
    scored = []
    for md_file in candidates:
        rel = _relevance_score(query, tags, md_file, summary_path)
        if rel["score"] > 0:
            # L3 时效加权：陈旧记忆自然降权，避免旧内容挤占相关性 top
            mtime, _size_kb = get_file_info(md_file)
            scored.append((rel["score"] * recency_factor(mtime), md_file))
    if not scored:
        return None
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:max(1, limit)]
    full_n = min(3, len(top))
    files_to_load = []
    for idx, (sc, md_file) in enumerate(top):
        m = LOAD_FULL if idx < full_n else LOAD_NORMAL
        files_to_load.append((md_file, m))
    return files_to_load


def _auto_compact(result, budget, summary_path):
    """超预算硬预算闸（1.3）：在预算内自动压实。

    策略：反复把「token 最高且仍可降低模式」的条目从 full→normal→brief 降级，
    已为 brief 的则直接丢弃，直到回到预算内或无可降。优先降高消耗项以最小化
    丢弃条数、保留相关性高的内容。返回是否发生过压实。
    """
    loaded = result["loaded"]
    guard = 0
    while result["total_tokens_estimate"] > budget and guard < 300:
        guard += 1
        # 保留至少 1 条记忆，避免极紧预算下清空全部上下文
        if len(loaded) <= 1:
            break
        downgradable = [e for e in loaded if e.get("load_mode") != LOAD_BRIEF]
        if downgradable:
            e = max(downgradable, key=lambda x: x["token_estimate"])
            new_mode = LOAD_NORMAL if e["load_mode"] == LOAD_FULL else LOAD_BRIEF
            new = _load_memory_file(Path(e["path"]), new_mode, summary_path)
            if new:
                result["total_tokens_estimate"] += new["token_estimate"] - e["token_estimate"]
                e.update(new)
                e["load_mode"] = new_mode
            else:
                loaded.remove(e)
                result["total_tokens_estimate"] -= e["token_estimate"]
        elif loaded:
            e = max(loaded, key=lambda x: x["token_estimate"])
            loaded.remove(e)
            result["total_tokens_estimate"] -= e["token_estimate"]
        else:
            break
    return guard > 0


def _build_load_result(mode, days, folder, query, tags):
    """构造 load_memory 的初始结果骨架。"""
    return {
        "version": VERSION,
        "timestamp": datetime.now().isoformat(),
        "mode": mode,
        "days_filter": days,
        "folder_filter": folder,
        "query": query,
        "loaded": [],
        "total_tokens_estimate": 0,
        "compacted": False,
        "relevance_used": bool(query or tags),
    }


def _apply_keyword_filter(files_to_load, keyword, summary_path):
    """按关键词/摘要存在折叠候选列表。"""
    if not keyword:
        return files_to_load
    keyword = keyword.lower()
    return [
        (f, m) for f, m in files_to_load
        if keyword in f.name.lower() or (summary_path / f"{f.stem}.summary").exists()
    ]


def _post_load_bookkeep(result, workspace_path):
    """超预算压实 + 预算记账。"""
    if result["total_tokens_estimate"] > 0:
        try:
            record_token_usage(workspace_path, result["total_tokens_estimate"], operation="load")
        except Exception as e:
            logger.warning("non-fatal: %s", e)


def load_memory(workspace_path, mode=LOAD_NORMAL, keyword=None, limit=10, days=None,
                folder=None, query=None, tags=None, budget=None, auto_compact=True,
                persist_on_miss=True):
    base_path = Path(workspace_path).resolve()
    memory_path = base_path / ".workbuddy" / "memory"
    summary_path = base_path / ".workbuddy" / SUMMARY_DIR

    result = _build_load_result(mode, days, folder, query, tags)

    if not memory_path.exists():
        result["error"] = _("memory_dir_not_exist")
        return result

    rank_result = rank_memory(workspace_path, days=days, folder=folder)

    # ---- 1.2 语义化加载：给定 query/tags 时按相关性排序，而非纯按天 ----
    if query or tags:
        files_to_load = _relevance_files_to_load(query, tags, rank_result, memory_path, limit, summary_path)
        if files_to_load is None:
            # 相关性无命中：回退默认分级加载，避免空集（6.2 引导）
            files_to_load = _default_load_list(rank_result, memory_path, mode, limit)
    else:
        files_to_load = _default_load_list(rank_result, memory_path, mode, limit)

    files_to_load = _apply_keyword_filter(files_to_load, keyword, summary_path)

    for md_file, load_mode in files_to_load:
        data = _load_memory_file(md_file, load_mode, summary_path, persist_on_miss=persist_on_miss)
        if data:
            result["loaded"].append(data)
            result["total_tokens_estimate"] += data.get("token_estimate", 0)

    # ---- 1.3 超预算自动压实（硬预算闸） ----
    if auto_compact:
        budget = budget or DEFAULT_DAILY_BUDGET
        if result["total_tokens_estimate"] > budget:
            result["compacted"] = _auto_compact(result, budget, summary_path)

    _post_load_bookkeep(result, workspace_path)
    return result
