# -*- coding: utf-8 -*-
"""
记忆管家 V4.0.1 - 治理类命令处理器（govern / snapshot / compact / dashboard / health）

与 cli_commands.py 拆分，避免单文件过长（file>800 硬限 P1）。
共享 _emit / get_colors 来自 cli_handlers 与 config。
"""

from .cli_handlers import (
    _confirm_text, _emit, _refuse_cancelled, _require_confirmation,
)
from .config import _, get_colors
from .core_compact import apply_compact, compact_plan
from .core_govern import apply_govern, govern_audit
from .core_insight import memory_health, savings_dashboard
from .core_perms import harden_workspace
from .core_snapshot import (
    MAX_SNAPSHOTS, snapshot_create, snapshot_list, snapshot_restore, snapshot_verify,
)

BAR_WIDTH = 20


def _bar(score):
    """把 0-100 分渲染成 ASCII 进度条，纯文本界面也能一眼看强弱。"""
    filled = int(round(score / 100 * BAR_WIDTH))
    return "[" + "#" * filled + "." * (BAR_WIDTH - filled) + "]"


def _print_error(C, result):
    print(f"\n{C['red']}\u274c {result.get('error')}{C['reset']}")
    return 0


# ---------------- govern ----------------

def _print_govern_audit(C, res):
    t = res["totals"]
    print(f"\n{C['bright']}\U0001f9f9 {_('gov_title')}{C['reset']}")
    print("=" * 54)
    print(f"   {_('gov_score').format(score=res['score'])} {_bar(res['score'])}")
    print(f"   {_('gov_files').format(n=t['files'], tokens=t['tokens'])}")
    pct = round(t["removable_tokens"] / t["tokens"] * 100, 1) if t["tokens"] else 0.0
    print(f"   {_('gov_savable').format(n=t['removable_tokens'], pct=pct)}")
    print(f"   {_('gov_cross_dup').format(n=t['cross_dup_lines'])}")
    print(f"   {_('gov_oversize').format(n=4000, m=t['oversize'])}")
    print(f"   {_('gov_stale').format(d=res['stale_days'], m=t['stale'])}")
    if res["actions"]:
        print(f"\n{C['cyan']}{_('gov_actions')}{C['reset']}")
        for act in res["actions"]:
            print(f"   \u2192 {act['cmd']}")
    if t["removable_tokens"] == 0 and not res["actions"]:
        print(f"\n{C['green']}\u2705 {_('gov_no_issue')}{C['reset']}")
    print("=" * 54)


def _print_govern_plan(C, plan):
    print(f"\n{C['bright']}\U0001f9f9 {_('gov_title')}{C['reset']}")
    print("=" * 54)
    print(f"   {_('gov_applied').format(n=plan['files'], tokens=plan['saved_tokens'])}")
    if plan.get("snapshot"):
        print(f"   \U0001f4be {_('gov_snapshot').format(name=plan['snapshot'])}")
    if plan.get("score_after") is not None:
        print(f"   {_('gov_score_after').format(before=plan['score_before'], after=plan['score_after'])}")
    print("=" * 54)


def _h_govern(args):
    C = get_colors()
    sd = getattr(args, 'stale_days', 30)
    dry = not getattr(args, 'execute', False)
    if dry:
        res = govern_audit(args.workspace, stale_days=sd)
        if _emit(args, res):
            return 0
        if res.get("error"):
            return _print_error(C, res)
        _print_govern_audit(C, res)
        print(f"   \U0001f4a1 {_('gov_dry_hint')}")
        return 0
    plan = apply_govern(args.workspace, dry_run=False, stale_days=sd)
    if _emit(args, plan):
        return 0
    if plan.get("error"):
        return _print_error(C, plan)
    _print_govern_plan(C, plan)
    return 0


# ---------------- snapshot ----------------

def _h_snapshot_list(args, C):
    res = snapshot_list(args.workspace)
    if _emit(args, res):
        return 0
    print(f"\n{C['bright']}\U0001f4be {_('snap_list_title').format(n=MAX_SNAPSHOTS)}{C['reset']}")
    if not res["snapshots"]:
        print(f"   {_('snap_empty')}")
        return 0
    for item in res["snapshots"]:
        print(_("snap_item").format(**item))
    return 0


def _h_snapshot_restore(args, C):
    if not getattr(args, 'execute', False):
        # 还原会覆盖现有记忆，必须显式 --execute
        print(f"{C['yellow']}\u26a0\ufe0f  {_('gov_dry_hint')}{C['reset']}")
        return 0
    # V4.0.3：还原会覆盖同名记忆文件，补交互确认门
    if not _require_confirmation(_confirm_text(_("confirm_snap_restore_header")),
                                 force=getattr(args, 'force', False),
                                 machine_mode=getattr(args, "json", False)):
        return _refuse_cancelled(args, C)
    res = snapshot_restore(args.workspace, name=getattr(args, 'name', None))
    if _emit(args, res):
        return 0
    if not res.get("ok"):
        return _print_error(C, res)
    print(f"\n{C['green']}\u2705 {_('snap_restored').format(name=res['name'], n=res['restored'])}{C['reset']}")
    return 0


def _h_snapshot_verify(args, C):
    """snapshot --verify：只读校验某个快照的完整性清单。"""
    res = snapshot_verify(args.workspace, name=getattr(args, 'name', None))
    if _emit(args, res):
        return 0
    if res.get("error"):
        return _print_error(C, res)
    if res["ok"]:
        print(f"\n{C['green']}\u2705 "
              f"{_('snap_verify_ok').format(name=res['name'], n=res['checked'])}{C['reset']}")
        return 0
    counts = {"name": res["name"], "bad": len(res["mismatch"]),
              "missing": len(res["missing"]), "extra": len(res["extra"])}
    print(f"\n{C['red']}\u274c {_('snap_verify_bad').format(**counts)}{C['reset']}")
    return 0


def _h_snapshot_create(args, C):
    res = snapshot_create(args.workspace, label=getattr(args, 'label', 'manual') or 'manual')
    if _emit(args, res):
        return 0
    if not res.get("ok"):
        return _print_error(C, res)
    print(f"\n{C['green']}\u2705 {_('snap_created').format(**res)}{C['reset']}")
    if res.get("pruned"):
        print(f"   {_('snap_pruned').format(n=res['pruned'])}")
    return 0


def _h_snapshot(args):
    C = get_colors()
    if getattr(args, 'list', False):
        return _h_snapshot_list(args, C)
    if getattr(args, 'verify', False):
        return _h_snapshot_verify(args, C)
    if getattr(args, 'restore', False):
        return _h_snapshot_restore(args, C)
    return _h_snapshot_create(args, C)


# ---------------- compact ----------------

def _print_compact_plan(C, plan):
    print(f"\n{C['bright']}\U0001f5c3\ufe0f  {_('cmp_title')}{C['reset']}")
    print("=" * 54)
    print(f"   {_('cmp_total').format(tokens=plan['total_tokens'], files=plan.get('files', 0))}")
    print(f"   {_('cmp_budget').format(budget=plan['budget'])}")
    if not plan["needed"]:
        print(f"\n{C['green']}\u2705 {_('cmp_no_need')}{C['reset']}")
        print("=" * 54)
        return
    print(f"   {_('cmp_excess').format(n=plan['excess'])}")
    print(f"   {_('cmp_candidates').format(n=len(plan['candidates']), tokens=plan['saved_tokens'])}")
    for cand in plan["candidates"][:10]:
        print(f"      - {cand['file']}  {cand['tokens']:,} \u2192 {cand['after']:,}")
    print("=" * 54)


def _h_compact(args):
    C = get_colors()
    budget = getattr(args, 'budget', None)
    dry = not getattr(args, 'execute', False)
    if dry:
        plan = compact_plan(args.workspace, budget=budget)
        if _emit(args, plan):
            return 0
        if plan.get("error"):
            return _print_error(C, plan)
        _print_compact_plan(C, plan)
        if plan["needed"]:
            print(f"   \U0001f4a1 {_('cmp_dry_hint')}")
        return 0
    plan = apply_compact(args.workspace, dry_run=False, budget=budget)
    if _emit(args, plan):
        return 0
    if plan.get("error"):
        return _print_error(C, plan)
    print(f"\n{C['bright']}\U0001f5c3\ufe0f  {_('cmp_title')}{C['reset']}")
    print("=" * 54)
    print(f"   {_('cmp_applied').format(n=len(plan['applied']), tokens=plan['saved_tokens'])}")
    if plan.get("snapshot"):
        print(f"   \U0001f4be {_('gov_snapshot').format(name=plan['snapshot'])}")
    print("=" * 54)
    return 0


# ---------------- dashboard / health ----------------

def _print_actions(actions, header_key):
    if not actions:
        return
    print(f"\n   {_(header_key)}")
    for act in actions:
        tag = _("reason_" + act["reason"]) if act.get("reason") else ""
        print(f"   \u2192 {act['cmd']}" + (f"  ({tag})" if tag else ""))


def _h_dashboard(args):
    C = get_colors()
    res = savings_dashboard(args.workspace, stale_days=getattr(args, 'stale_days', 30))
    if _emit(args, res):
        return 0
    if res.get("error"):
        return _print_error(C, res)
    print(f"\n{C['bright']}\U0001f4ca {_('dash_title')}{C['reset']}")
    print("=" * 54)
    print(f"   {_('dash_files').format(n=res['files'])}")
    print(f"   {_('dash_tokens').format(tokens=res['tokens'])}")
    usage_pct = round(res["usage"] * 100, 1)
    print(f"   {_('dash_budget').format(budget=res['budget'], used=res['today_tokens'], pct=usage_pct)}")
    print(f"   {_('dash_savable').format(tokens=res['savable_tokens'], pct=res['savable_pct'])}")
    print(f"   {_('dash_stale').format(n=res['stale_files'], tokens=res['stale_tokens'])}")
    print(f"   {_('dash_nodesc').format(n=res['missing_description'])}")
    _print_actions(res["next"], "dash_next")
    print("=" * 54)
    return 0


def _h_health(args):
    C = get_colors()
    res = memory_health(args.workspace, stale_days=getattr(args, 'stale_days', 30))
    if _emit(args, res):
        return 0
    if res.get("error"):
        return _print_error(C, res)
    print(f"\n{C['bright']}\U0001fa7a {_('hlth_title')}{C['reset']}")
    print("=" * 54)
    print(f"   {_('hlth_score').format(score=res['score'], grade=res['grade'])} {_bar(res['score'])}")
    for key in ("visibility", "freshness", "duplication", "size", "budget"):
        name = _("dim_" + key)
        print(_("hlth_dim").format(name=name, score=res["dims"][key]))
    m = res["metrics"]
    usage_pct = round(m["budget_usage"] * 100, 1)
    metrics_line = _("hlth_metrics").format(
        files=m["files"], tokens=m["tokens"], stale=m["stale_files"],
        oversize=m["oversize_files"], nodesc=m["missing_description"], usage=usage_pct)
    print(f"\n   {metrics_line}")
    _print_actions(res["actions"], "hlth_actions")
    print("=" * 54)
    return 0


# ---------------- harden ----------------

def _h_harden(args):
    """harden：把敏感目录权限收敛为 目录 0700 / 文件 0600（POSIX）。"""
    C = get_colors()
    res = harden_workspace(args.workspace, execute=getattr(args, 'execute', False))
    if _emit(args, res):
        return 0
    print(f"\n{C['bright']}\U0001f512 {_('harden_title')}{C['reset']}")
    print("=" * 54)
    if not res["supported"]:
        print(f"   {_('harden_unsupported')}")
        print("=" * 54)
        return 0
    for item in res["targets"]:
        mark = "\u2713" if item["exists"] else "-"
        print(_("harden_item").format(mark=mark, path=item["path"], mode=item["mode"]))
    if res["executed"]:
        print(f"\n{C['green']}\u2705 "
              f"{_('harden_applied').format(dirs=res['dirs'], files=res['files'])}{C['reset']}")
        for err in res["errors"][:5]:
            print(f"   {C['yellow']}{err}{C['reset']}")
    else:
        print(f"\n   \U0001f4a1 {_('harden_execute_hint')}")
    print("=" * 54)
    return 0
