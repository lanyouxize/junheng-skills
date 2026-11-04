import logging
logger = logging.getLogger(__name__)

# -*- coding: utf-8 -*-
"""
记忆管家 V4.0.1 - 写入治理与可回滚（N3）

写入侧的「卫生」问题会直接放大 token：重复行、空行洪水、分隔线堆砌、
单文件过大、内容陈旧。本模块做两件事：
  1) govern_audit  —— 只读审计，量化可省 token 与治理分；
  2) apply_govern  —— 仅执行「安全且幂等」的三种折叠（连续重复行 /
     连续空行 / 连续分隔线）；跨文件重复与超大文件只报告不代删。
落盘前自动建快照，可随时 snapshot --restore 还原。
"""

import os
import re
from datetime import datetime
from pathlib import Path

from .config import (
    VERSION, _, iter_memory_files, safe_file_read,
)
from .token import estimate_tokens
from .core_snapshot import snapshot_create

DUP_MIN_LEN = 12
OVERSIZE_TOKENS = 4000
SEPARATORS = ("---", "***", "___", "===")
_NOISE_RE = re.compile(r"^[\s\-_*=|>#:.`~]*$")


def _norm(line):
    """归一化：去空白与列表/标题前缀，用于重复判定。"""
    s = line.strip()
    while s[:1] in ("-", "*", "+", "#", ">", "|"):
        s = s[1:].strip()
    return s


def _is_noise(line):
    return bool(_NOISE_RE.match(line.strip()))


def _read(md_file):
    try:
        content, _read_err = safe_file_read(md_file)
    except Exception as e:
        logger.warning("non-fatal: %s", e)
        return ""
    return content or ""


def _drop_consecutive_dups(lines):
    out = []
    prev = ""
    for ln in lines:
        s = ln.strip()
        if s and s == prev:
            continue
        prev = s
        out.append(ln.rstrip())
    return out


def _collapse_blank_runs(lines):
    out = []
    run = 0
    for ln in lines:
        if ln.strip():
            run = 0
        else:
            run += 1
            if run > 1:
                continue
        out.append(ln.rstrip())
    return out


def _collapse_sep_runs(lines):
    out = []
    run = 0
    for ln in lines:
        s = ln.strip()
        if s in SEPARATORS:
            run += 1
            if run > 1:
                continue
        else:
            run = 0
        out.append(ln.rstrip())
    return out


def _strip_trailing_blanks(lines):
    out = list(lines)
    while out and not out[-1].strip():
        out.pop()
    return out


def compact_lines(lines):
    """按四种幂等折叠依次处理，返回折叠后的行列表。"""
    for fn in (_drop_consecutive_dups, _collapse_blank_runs,
               _collapse_sep_runs, _strip_trailing_blanks):
        lines = fn(lines)
    return lines


def _count_cross_dup(lines, index, rel):
    """统计该文件中「也出现在别处」的归一化行数。"""
    n = 0
    for ln in lines:
        s = _norm(ln)
        if len(s) < DUP_MIN_LEN or _is_noise(s):
            continue
        owners = index.get(s)
        if owners and len(owners) > 1 and rel in owners:
            n += 1
    return n


def _scan_files(memory_path):
    """第一遍：读全文，建立跨文件重复索引。"""
    files = []
    index = {}
    for md_file, mtime, size_kb, rel in iter_memory_files(memory_path):
        content = _read(md_file)
        lines = content.splitlines()
        for ln in lines:
            s = _norm(ln)
            if len(s) < DUP_MIN_LEN or _is_noise(s):
                continue
            index.setdefault(s, set()).add(rel)
        files.append({
            "path": md_file, "rel": rel, "content": content, "lines": lines,
            "size_kb": size_kb, "mtime": mtime,
        })
    return files, index


def _file_report(item, index, stale_days):
    """第二遍：为每个文件产出治理指标。"""
    content = item["content"]
    lines = item["lines"]
    tokens = estimate_tokens(content)
    folded = compact_lines(lines)
    removable = max(0, estimate_tokens(content) - estimate_tokens("\n".join(folded)))
    age = 0
    if item["mtime"]:
        age = max((datetime.now() - item["mtime"]).days, 0)
    return {
        "file": item["rel"],
        "tokens": tokens,
        "lines": len(lines),
        "age_days": age,
        "removable_tokens": removable,
        "cross_dup_lines": _count_cross_dup(lines, index, item["rel"]),
        "oversize": tokens > OVERSIZE_TOKENS,
        "stale": age > stale_days,
        "size_kb": round(item["size_kb"], 2),
    }


def _govern_score(totals):
    """治理分：可省比例 / 超大文件 / 陈旧占比 三项扣分。"""
    total = max(totals["tokens"], 1)
    score = 100
    score -= min(30, round(totals["removable_tokens"] / total * 150))
    score -= min(25, totals["oversize"] * 8)
    score -= min(25, round(totals["stale_tokens"] / total * 40))
    return max(0, min(100, score))


def _build_actions(totals, score):
    actions = []
    if totals["removable_tokens"] > 0:
        actions.append({"code": "fold", "saving": totals["removable_tokens"],
                        "cmd": "govern <workspace> --execute"})
    if totals["cross_dup_lines"] > 0:
        actions.append({"code": "cross_dup", "saving": 0, "cmd": "dedup <workspace>"})
    if totals["oversize"] > 0:
        actions.append({"code": "oversize", "saving": 0,
                        "cmd": "compact <workspace> --execute"})
    if totals["stale"] > 0:
        actions.append({"code": "stale", "saving": 0, "cmd": "archive <workspace> --execute"})
    return actions


def govern_audit(workspace_path, stale_days=30):
    """只读审计记忆写入质量，返回逐文件指标 + 总量 + 治理分 + 建议。"""
    base = Path(workspace_path).resolve()
    memory_path = base / ".workbuddy" / "memory"
    result = {
        "ok": True, "version": VERSION, "stale_days": stale_days,
        "files": [], "totals": {}, "score": 0, "actions": [],
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }
    if not memory_path.exists():
        result["ok"] = False
        result["error"] = _("memory_dir_not_exist")
        return result
    items, index = _scan_files(memory_path)
    reports = [_file_report(it, index, stale_days) for it in items]
    reports.sort(key=lambda r: -r["removable_tokens"])
    totals = {
        "files": len(reports),
        "tokens": sum(r["tokens"] for r in reports),
        "removable_tokens": sum(r["removable_tokens"] for r in reports),
        "cross_dup_lines": sum(r["cross_dup_lines"] for r in reports),
        "oversize": sum(1 for r in reports if r["oversize"]),
        "stale": sum(1 for r in reports if r["stale"]),
        "stale_tokens": sum(r["tokens"] for r in reports if r["stale"]),
    }
    result["files"] = reports
    result["totals"] = totals
    result["score"] = _govern_score(totals)
    result["actions"] = _build_actions(totals, result["score"])
    return result


def _write_atomic(path, text):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _fold_targets(workspace_path, targets):
    """对目标文件执行幂等折叠，返回实际落盘的相对路径列表。"""
    memory_path = Path(workspace_path).resolve() / ".workbuddy" / "memory"
    applied = []
    for rpt in targets:
        md_file = memory_path / rpt["file"]
        if not md_file.exists():
            continue
        content = _read(md_file)
        if not content:
            continue
        _write_atomic(md_file, "\n".join(compact_lines(content.splitlines())) + "\n")
        applied.append(rpt["file"])
    return applied


def apply_govern(workspace_path, dry_run=True, stale_days=30, snapshot=True):
    """执行安全折叠；dry_run=True 时只出计划不落盘。"""
    audit = govern_audit(workspace_path, stale_days)
    if not audit.get("ok"):
        return audit
    targets = [r for r in audit["files"] if r["removable_tokens"] > 0]
    plan = {
        "ok": True, "version": VERSION, "dry_run": dry_run,
        "files": len(targets),
        "saved_tokens": sum(r["removable_tokens"] for r in targets),
        "score_before": audit["score"],
        "snapshot": None, "applied": [], "error": None,
    }
    if not targets or dry_run:
        plan["applied"] = [r["file"] for r in targets]
        return plan
    if snapshot:
        snap = snapshot_create(workspace_path, label="govern")
        plan["snapshot"] = snap.get("name") if snap.get("ok") else None
    plan["applied"] = _fold_targets(workspace_path, targets)
    after = govern_audit(workspace_path, stale_days)
    plan["score_after"] = after.get("score", audit["score"])
    return plan
