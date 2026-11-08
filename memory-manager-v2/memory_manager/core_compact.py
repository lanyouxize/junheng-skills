import logging
logger = logging.getLogger(__name__)

# -*- coding: utf-8 -*-
"""
记忆管家 V4.0.1 - 自适应压实（N5）

与 load 内建的「一次性降级压实」不同，这里是**落盘级**压实：
当记忆总量超出预算时，按「体积 × 陈旧度」自适应挑选候选，
把原文替换为保留 front-matter 的精简版，永久降低候选池体积。
落盘前自动建快照（snapshot --restore 可还原）。默认仅预览。
"""

import os
from datetime import datetime
from pathlib import Path

from .config import (
    DEFAULT_DAILY_BUDGET, SUMMARY_MAX_CHARS, VERSION, _,
    iter_memory_files, safe_file_read,
)
from .token import estimate_tokens
from .core_selector import recency_factor
from .core_snapshot import snapshot_create
from .summarize import generate_summary

COMPACT_MIN_TOKENS = 120
COMPACT_KEEP_RATIO = 0.35
COMPACT_MARKER = "<!-- compacted by memory-manager -->"


def _read(md_file):
    try:
        content, _read_err = safe_file_read(md_file)
    except Exception as e:
        logger.warning("non-fatal: %s", e)
        return ""
    return content or ""


def _split_front_matter(content):
    """拆出 front-matter 与正文；无 front-matter 时返回 ("", content)。"""
    if not content.startswith("---"):
        return "", content
    end = content.find("\n---", 3)
    if end == -1:
        return "", content
    return content[:end + 4].rstrip() + "\n\n", content[end + 4:].lstrip("\n")


def compacted_content(content):
    """把一篇记忆压成「front-matter + 精简正文」。"""
    fm, body = _split_front_matter(content)
    if not body.strip():
        return content
    target = max(SUMMARY_MAX_CHARS, int(len(body) * COMPACT_KEEP_RATIO))
    return f"{fm}{COMPACT_MARKER}\n\n{generate_summary(body, max_chars=target)}\n"


def _weight(tokens, mtime):
    """压实优先级：越大越该被压（体积大 + 越陈旧）。"""
    if not mtime:
        return tokens * 0.9
    return tokens * (1.0 - recency_factor(mtime))


def _collect(memory_path):
    items = []
    for md_file, mtime, _kb, rel in iter_memory_files(memory_path):
        content = _read(md_file)
        tokens = estimate_tokens(content)
        summary = compacted_content(content)
        after = estimate_tokens(summary)
        items.append({
            "rel": rel, "path": md_file, "tokens": tokens,
            "after": after, "savable": max(0, tokens - after),
            "weight": _weight(tokens, mtime),
        })
    return items


def _select(items, excess):
    """按权重贪心挑选，直到可省量覆盖超预算部分。"""
    picked = []
    gain = 0
    for it in sorted(items, key=lambda x: (-x["weight"], -x["tokens"])):
        if gain >= excess:
            break
        if it["tokens"] < COMPACT_MIN_TOKENS or it["savable"] <= 0:
            continue
        picked.append(it)
        gain += it["savable"]
    return picked, gain


def compact_plan(workspace_path, budget=None, stale_days=30):
    """计算压实计划：是否需要压、压哪些、能省多少。只读。"""
    budget = budget or DEFAULT_DAILY_BUDGET
    base = Path(workspace_path).resolve()
    memory_path = base / ".workbuddy" / "memory"
    plan = {
        "ok": True, "version": VERSION, "budget": budget, "stale_days": stale_days,
        "total_tokens": 0, "excess": 0, "needed": False,
        "candidates": [], "saved_tokens": 0,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }
    if not memory_path.exists():
        plan["ok"] = False
        plan["error"] = _("memory_dir_not_exist")
        return plan
    items = _collect(memory_path)
    total = sum(it["tokens"] for it in items)
    plan["total_tokens"] = total
    plan["files"] = len(items)
    if total <= budget or not items:
        return plan
    plan["needed"] = True
    plan["excess"] = total - budget
    picked, gain = _select(items, plan["excess"])
    plan["candidates"] = [{
        "file": it["rel"], "tokens": it["tokens"],
        "after": it["after"], "savable": it["savable"],
    } for it in picked]
    plan["saved_tokens"] = gain
    return plan


def _write_atomic(path, text):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _compact_targets(workspace_path, candidates):
    """按候选列表压实文件，返回实际落盘的相对路径列表。"""
    memory_path = Path(workspace_path).resolve() / ".workbuddy" / "memory"
    applied = []
    for cand in candidates:
        md_file = memory_path / cand["file"]
        if not md_file.exists():
            continue
        content = _read(md_file)
        if not content:
            continue
        _write_atomic(md_file, compacted_content(content))
        applied.append(cand["file"])
    return applied


def apply_compact(workspace_path, dry_run=True, budget=None, snapshot=True):
    """执行压实；dry_run=True 时只返回计划。"""
    plan = compact_plan(workspace_path, budget=budget)
    if not plan.get("ok") or not plan.get("needed"):
        plan["dry_run"] = dry_run
        plan["applied"] = []
        return plan
    out = dict(plan)
    out["dry_run"] = dry_run
    out["snapshot"] = None
    out["applied"] = []
    if dry_run:
        out["applied"] = [c["file"] for c in plan["candidates"]]
        return out
    if snapshot:
        snap = snapshot_create(workspace_path, label="compact")
        out["snapshot"] = snap.get("name") if snap.get("ok") else None
    out["applied"] = _compact_targets(workspace_path, plan["candidates"])
    out["saved_tokens"] = sum(
        c["savable"] for c in plan["candidates"] if c["file"] in out["applied"]
    )
    return out
