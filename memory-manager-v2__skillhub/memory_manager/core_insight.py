import logging
logger = logging.getLogger(__name__)

# -*- coding: utf-8 -*-
"""
记忆管家 V4.0.1 - 省 Token 看板（D1）与一键记忆体检（D2）

dashboard：一屏回答「现在多大 / 预算用多少 / 还能省多少 / 该做哪一步」。
health    ：把可见性、新鲜度、重复度、体积、预算五维压成一个 0-100 分，
            并给出按收益排序的修复命令。两者均为只读。
"""

from datetime import datetime
from pathlib import Path

from .config import DEFAULT_DAILY_BUDGET, VERSION, _
from .core_govern import govern_audit
from .core_selector import selector_audit
from .token import token_check

DIM_WEIGHTS = {
    "visibility": 0.25, "freshness": 0.20, "duplication": 0.20,
    "size": 0.15, "budget": 0.20,
}
GRADE_A = 85
GRADE_B = 70
GRADE_C = 55


def _clamp(v, low=0, high=100):
    return max(low, min(high, v))


def _pct(part, whole):
    return (part / whole) if whole else 0.0


def _sel_metrics(sel):
    """selector_audit 的聚合指标在 metrics 子字典里，取不到时退化为 0。"""
    return sel.get("metrics", {}) or {}


def _dim_visibility(sel):
    return _clamp(int(_sel_metrics(sel).get("avg_readiness", 0)))


def _dim_freshness(gov):
    total = gov["totals"]["tokens"]
    return _clamp(100 - int(_pct(gov["totals"].get("stale_tokens", 0), total) * 150))


def _dim_duplication(gov):
    total = gov["totals"]["tokens"]
    return _clamp(100 - int(_pct(gov["totals"]["removable_tokens"], total) * 200))


def _dim_size(gov):
    return _clamp(100 - gov["totals"]["oversize"] * 12 - max(0, gov["totals"]["files"] - 40))


def _dim_budget(check):
    ratio = check.get("ratio", 0.0)
    return _clamp(int(100 - min(ratio, 1.0) * 100))


def _dims(gov, sel, check):
    return {
        "visibility": _dim_visibility(sel),
        "freshness": _dim_freshness(gov),
        "duplication": _dim_duplication(gov),
        "size": _dim_size(gov),
        "budget": _dim_budget(check),
    }


def _grade(score):
    if score >= GRADE_A:
        return "A"
    if score >= GRADE_B:
        return "B"
    if score >= GRADE_C:
        return "C"
    return "D"


def _health_actions(dims, gov, sel, check):
    """按收益从高到低给出可执行的下一步命令。"""
    actions = []
    if gov["totals"]["removable_tokens"] > 0:
        actions.append({
            "reason": "duplication", "saving": gov["totals"]["removable_tokens"],
            "cmd": "govern <workspace> --execute",
        })
    if _sel_metrics(sel).get("frontmatter_missing"):
        actions.append({
            "reason": "visibility", "saving": 0,
            "cmd": "describe <workspace> --execute",
        })
    if gov["totals"]["oversize"]:
        actions.append({
            "reason": "size", "saving": 0,
            "cmd": "compact <workspace> --execute",
        })
    if gov["totals"]["stale"]:
        actions.append({
            "reason": "freshness", "saving": 0,
            "cmd": "archive <workspace> --execute",
        })
    if check.get("ratio", 0) >= 0.8:
        actions.append({
            "reason": "budget", "saving": 0,
            "cmd": "throttle <workspace>",
        })
    actions.sort(key=lambda a: -a["saving"])
    return actions


def memory_health(workspace_path, stale_days=30):
    """一键体检：五维打分 + 总分 + 等级 + 优先修复清单。只读。"""
    base = Path(workspace_path).resolve()
    result = {
        "ok": True, "version": VERSION, "workspace": str(base),
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "score": 0, "grade": "D", "dims": {}, "actions": [], "error": None,
    }
    if not (base / ".workbuddy" / "memory").exists():
        result["ok"] = False
        result["error"] = _("memory_dir_not_exist")
        return result
    gov = govern_audit(workspace_path, stale_days)
    sel = selector_audit(workspace_path, stale_days)
    check = token_check(workspace_path)
    dims = _dims(gov, sel, check)
    score = int(sum(dims[k] * w for k, w in DIM_WEIGHTS.items()))
    result["dims"] = dims
    result["score"] = _clamp(score)
    result["grade"] = _grade(result["score"])
    result["actions"] = _health_actions(dims, gov, sel, check)
    result["metrics"] = {
        "files": gov["totals"]["files"],
        "tokens": gov["totals"]["tokens"],
        "stale_files": gov["totals"]["stale"],
        "oversize_files": gov["totals"]["oversize"],
        "missing_description": len(_sel_metrics(sel).get("frontmatter_missing", [])),
        "budget_usage": check.get("ratio", 0.0),
    }
    return result


def savings_dashboard(workspace_path, stale_days=30):
    """省 Token 看板：总量 / 预算 / 可省空间 / 趋势 / 下一步。只读。"""
    base = Path(workspace_path).resolve()
    dash = {
        "ok": True, "version": VERSION, "workspace": str(base),
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "files": 0, "tokens": 0, "budget": DEFAULT_DAILY_BUDGET,
        "today_tokens": 0, "usage": 0.0,
        "savable_tokens": 0, "savable_pct": 0.0,
        "stale_tokens": 0, "stale_files": 0,
        "missing_description": 0, "next": [], "error": None,
    }
    if not (base / ".workbuddy" / "memory").exists():
        dash["ok"] = False
        dash["error"] = _("memory_dir_not_exist")
        return dash
    gov = govern_audit(workspace_path, stale_days)
    sel = selector_audit(workspace_path, stale_days)
    check = token_check(workspace_path)
    totals = gov["totals"]
    savable = totals["removable_tokens"]
    dash.update({
        "files": totals["files"], "tokens": totals["tokens"],
        "budget": check.get("budget", DEFAULT_DAILY_BUDGET),
        "today_tokens": check.get("today_tokens", 0),
        "usage": check.get("ratio", 0.0),
        "savable_tokens": savable,
        "savable_pct": round(_pct(savable, totals["tokens"]) * 100, 1),
        "stale_tokens": totals.get("stale_tokens", 0),
        "stale_files": totals["stale"],
        "missing_description": len(_sel_metrics(sel).get("frontmatter_missing", [])),
    })
    dash["next"] = _health_actions(_dims(gov, sel, check), gov, sel, check)[:3]
    return dash
