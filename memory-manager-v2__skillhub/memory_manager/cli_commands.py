# -*- coding: utf-8 -*-
"""
记忆管家 V3.0 - CLI 命令处理器（_h_*）
从 cli_handlers.py 拆分，降低单文件长度（file>800 硬限 P1）。
共享辅助（_emit/_require_confirmation/_make_progress）来自 cli_handlers。
"""
import json

from .config import get_colors, _
from .cli_handlers import (
    _confirm_text, _emit, _make_progress, _refuse_cancelled, _require_confirmation,
)
from .core import analyze_memory, search_memory, load_memory, rank_memory
from .summarize import summarize_memory
from .cache import cache_clean, cache_reminder
from .clean import (
    auto_clean_memory, archive_old_memory, dedup_memory,
    generate_cleanup_preview, scan_workspace, execute_cleanup,
)
from .io import export_memories, import_memories, backup_memory, restore_backup
from .report import (
    generate_memory_report, print_memory_analysis, print_preview, print_report,
)
from .token import token_check, token_trends, kb_to_tokens
from .prompt import list_prompts, get_prompt, save_prompt, search_prompts
from .cli_handlers import _handle_self_test
from .core_selector import selector_audit, apply_descriptions


def _h_analyze(args):
    result = analyze_memory(args.workspace)
    print_memory_analysis(result, format_type="json" if getattr(args, 'json', False) else "text")
    return 0


def _h_search(args):
    C = get_colors()
    tag = getattr(args, 'tag', None)
    folder = getattr(args, 'folder', None)
    result = search_memory(args.workspace, args.keyword, tag=tag, folder=folder)
    if getattr(args, 'json', False):
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    tag_info = f" [tag={tag}]" if tag else ""
    folder_info = f" [folder={folder}]" if folder else ""
    print(f"\n{C['bright']}\U0001f50d {_('search_header').format(keyword=args.keyword, tags=tag_info, folder=folder_info, total=result['total'])}{C['reset']}")
    for i, m in enumerate(result["matches"][:10], 1):
        tags_str = f" [{','.join(m['tags'])}]" if m.get('tags') else ""
        print(f"   [{i}] {m['file']}{tags_str} {_('score_paren').format(score=m['score'])} {m['modified']}")
    return 0


def _h_load(args):
    C = get_colors()
    result = load_memory(
        args.workspace, mode=args.mode, days=getattr(args, 'days', None),
        limit=getattr(args, 'top_k', None) or getattr(args, 'limit', 10),
        query=getattr(args, 'query', None),
        tags=[t.strip() for t in args.tags.split(",")] if getattr(args, 'tags', None) else None,
        auto_compact=not getattr(args, 'no_compact', False),
    )
    if getattr(args, 'json', False):
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    print(f"\n{C['bright']}\U0001f4da {_('load_header').format(n=len(result['loaded']))}{C['reset']}")
    print(f"   {_('load_token_est')}: {result['total_tokens_estimate']}{_('token_estimated_tag')}")
    if result.get('relevance_used'):
        print(f"   \U0001f9e0 {_('load_relevance_used')}")
    if result.get('compacted'):
        print(f"   \U0001f50d {_('load_auto_compacted')}")
    for item in result["loaded"][:10]:
        print(f"   \u2022 {item['file']} ({item['type']}) {item.get('keywords', [])}")
    return 0


def _h_summarize(args):
    result = summarize_memory(args.workspace, progress_callback=_make_progress(_("progress_summarizing")))
    if _emit(args, result):
        return 0
    print(f"\n\U0001f4dd {_('summarize_done').format(n=len(result['summarized']))}")
    return 0


def _h_report(args):
    res = generate_memory_report(args.workspace)
    if _emit(args, res or {"status": "report_generated"}):
        return 0
    return 0


def _h_cache_reminder(args):
    res = cache_reminder(args.workspace)
    if _emit(args, res or {"status": "ok"}):
        return 0
    return 0


def _h_cache_clean(args):
    res = cache_clean(args.workspace, dry_run=not getattr(args, 'execute', False),
                      confirm=getattr(args, 'execute', False), cache_type='all')
    if _emit(args, res or {"status": "ok"}):
        return 0
    return 0


def _h_clean(args):
    C = get_colors()
    preview = generate_cleanup_preview(args.workspace, dry_run=True)
    if _emit(args, preview):
        return 0
    print_preview(preview)
    if getattr(args, 'execute', False):
        if _require_confirmation(
            f"\n{C['yellow']}\u26a0\ufe0f  {_('clean_confirm_header').format(n=len(preview.get('files_to_clean', [])))}\n"
            f"{C['yellow']}{_('confirm_reply_agree')}",
            force=getattr(args, 'force', False)
        ):
            exec_result = execute_cleanup(
                args.workspace, confirm=True,
                progress_callback=_make_progress(_("progress_cleaning")))
            print(f"\n{C['green']}\u2705 {_('clean_deleted').format(n=exec_result['deleted_count'], kb=exec_result['deleted_size_kb'])}")
            if exec_result.get('deleted_size_kb'):
                print(_("clean_release_line").format(
                    kb=exec_result['deleted_size_kb'],
                    tokens=kb_to_tokens(exec_result['deleted_size_kb'])))
        else:
            print(f"\n{C['yellow']}\u274c {_('cancelled')}")
    return 0


def _h_archive(args):
    C = get_colors()
    if getattr(args, 'execute', False):
        # V4.0.3：归档会真正 unlink 记忆文件，落盘前必须有交互确认门
        if not _require_confirmation(
                _confirm_text(_("confirm_archive_header").format(days=args.days)),
                                     force=getattr(args, 'force', False),
                                     machine_mode=getattr(args, "json", False)):
            return _refuse_cancelled(args, C)
    result = archive_old_memory(args.workspace, args.days, confirm=getattr(args, 'execute', False))
    if _emit(args, result):
        return 0
    print(f"\n{_('archive_result').format(n=result['archived_count'], kb=result['archived_size_kb'])}")
    print(_("archive_location").format(path=result['archive_path']))
    return 0


def _h_auto_clean(args):
    C = get_colors()
    content_filter = getattr(args, 'filter', None)
    confirm_action = getattr(args, 'execute', False)
    result = auto_clean_memory(args.workspace, dry_run=not confirm_action,
                               content_filter=content_filter, confirm_action=confirm_action)
    if _emit(args, result):
        return 0
    print(f"\n{C['bright']}{'='*50}{C['reset']}")
    print(f"{C['cyan']}\U0001f9f9 {_('differential_auto_clean')}{C['reset']}")
    print(f"{'='*50}")
    print(_("autoclean_push_line").format(n=result['clean_summary']['push_to_remind']))
    print(_("autoclean_personal_line").format(n=result['clean_summary']['personal_work_to_remind']))
    print(_("autoclean_other_line").format(n=result['clean_summary']['other_to_remind']))
    total_remind = sum(result["clean_summary"].values())
    total_kept = len(result["kept_files"])
    if total_remind > 0:
        print(_("autoclean_remind_header").format(n=total_remind))
        for f in result.get("remind_files", []):
            print(_("autoclean_remind_item").format(name=f['name'], age=f['age_days'], type=f['type']))
    print(_("autoclean_kept_header").format(n=total_kept))
    for f in result.get("kept_files", []):
        print(f"   \u2713 {f['name']} {f.get('reason', '')}")
    return 0


def _h_export(args):
    result = export_memories(args.workspace, args.output,
                             progress_callback=_make_progress(_("progress_exporting")))
    if _emit(args, result):
        return 0
    if "error" in result:
        print(f"\u274c {result['error']}")
    else:
        print(f"\u2705 {result.get('message', _('export_complete'))} {result['exported_file']} ({result['size_kb']}KB)")
    return 0


def _h_import(args):
    C = get_colors()
    # V4.0.3：导入会写入/覆盖记忆文件，补交互确认门（此前无任何确认）
    if not _require_confirmation(_confirm_text(_("confirm_import_header")),
                                 force=getattr(args, 'force', False),
                                 machine_mode=getattr(args, "json", False)):
        return _refuse_cancelled(args, C)
    result = import_memories(args.workspace, args.input)
    if _emit(args, result):
        return 0
    print(_("import_result").format(n=result.get('imported_files', 0), m=result.get('imported_summaries', 0)))
    return 0


def _h_config(args):
    C = get_colors()
    from .config import load_config      # V4.0.2：去掉多余的 __import__ 动态导入
    config = load_config(getattr(args, "workspace", None))
    if hasattr(args, 'key') and args.key and hasattr(args, 'value') and args.value:
        from .config import config_memory
        result = config_memory(args.workspace, key=args.key, value=args.value)
        if _emit(args, result):
            return 0
        print(f"\n{_('config_updated_line').format(key=args.key, value=args.value)}")
    else:
        if _emit(args, config):
            return 0
        print(f"\n{_('config_current')}")
        for k, v in sorted(config.items()):
            print(f"  {k}: {v}")
    return 0


def _h_token_check(args):
    C = get_colors()
    result = token_check(args.workspace)
    if getattr(args, 'json', False):
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    print(f"\n{result['emoji']} {result['message']}")
    tag = _('token_estimated_tag')
    print(f"   {_('token_today_used')}: {result['today_tokens']:,} tokens {tag}")
    print(f"   {_('token_budget_label')}: {result['budget']:,} tokens")
    print(f"   {_('token_usage_rate')}: {result['ratio']*100:.1f}%")
    remaining = max(result['budget'] - result['today_tokens'], 0)
    print(f"   {_('token_remaining')}: {remaining:,} tokens {tag}")
    try:
        trend = token_trends(args.workspace, period="daily", days_back=7)
        avg = trend.get("totals", {}).get("avg_daily_tokens", 0)
        print(f"   {_('token_7d_avg')}: {avg:,} tokens {tag}")
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("non-fatal: %s", e)
    if result.get('note'):
        print(f"   {result['note']}")
    return 0


def _h_token_trends(args):
    C = get_colors()
    period = getattr(args, 'period', 'week')
    days_back = getattr(args, 'days', None)
    result = token_trends(args.workspace, period=period, days_back=days_back)
    if getattr(args, 'json', False):
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    period_label = {"daily": _("period_daily"), "week": _("period_week"),
                    "month": _("period_month")}.get(period, period)
    print(f"\n{C['cyan']}\U0001f4ca {_('token_trends_header').format(period=period_label)}{C['reset']}")
    print(f"{'='*50}")
    totals = result.get("totals", {})
    if totals.get("days_with_data", 0) == 0:
        print(f"   {_('token_trends_no_data')}")
    else:
        print(f"   {_('token_trends_total')}: {totals['total_tokens']:,} tokens {_('token_estimated_tag')}")
        print(f"   {_('token_trends_daily_avg')}: {totals['avg_daily_tokens']:,} tokens {_('token_estimated_tag')}")
        print(f"   {_('token_trends_ops')}: {totals['total_operations']:,}")
        print()
        for agg in result.get("aggregated", []):
            label = agg.get("label", "")
            tokens = agg.get("tokens", 0)
            ops = agg.get("operations_count", 0)
            bar_len = min(int(tokens / max(totals['avg_daily_tokens'], 1) * 10), 40)
            bar = "\u2588" * max(bar_len, 1)
            print(f"   {label:>12s} | {bar} {tokens:,} ({ops} ops)")
    print(f"{'='*50}")
    return 0


def _h_scan(args):
    result = scan_workspace(args.workspace)
    if _emit(args, result):
        return 0
    print_report(result)
    return 0


def _h_prompt_list(args):
    C = get_colors()
    result = list_prompts(args.workspace, tag=getattr(args, 'tag', None))
    if _emit(args, result):
        return 0
    if result["total"] == 0:
        print(f"\n{C['yellow']}\U0001f4cb {_('prompt_no_templates')}{C['reset']}")
        print(f"   {_('prompt_save_hint')}")
    else:
        print(f"\n{C['bright']}\U0001f4cb {_('prompt_list_header').format(n=result['total'])}{C['reset']}")
        print(f"{'='*50}")
        for p in result["prompts"]:
            tags_str = f" [{','.join(p['tags'])}]" if p.get('tags') else ""
            desc = f" - {p['description']}" if p.get('description') else ""
            print(f"   \U0001f4dd {p['name']}{tags_str}{desc}")
            print(f"      {_('version')}:{p['version']} | {_('prompt_modified')}:{p['modified']} | {p['size_kb']:.1f}KB")
    return 0


def _h_prompt_get(args):
    C = get_colors()
    result = get_prompt(args.workspace, args.name)
    if _emit(args, result):
        return 0
    if not result.get("found"):
        print(f"\n{C['red']}\u274c {result.get('error', _('prompt_not_found'))}{C['reset']}")
    else:
        print(f"\n{C['bright']}\U0001f4dd {result['name']}{C['reset']}")
        tags_str = f" [{','.join(result['tags'])}]" if result.get('tags') else ""
        print(f"   {_('tag_search_label')}:{tags_str} | {_('version')}:{result['version']}")
        print(f"{'='*50}")
        print(result["content"])
    return 0


def _h_prompt_save(args):
    C = get_colors()
    tags = [t.strip() for t in args.tags.split(",")] if getattr(args, 'tags', None) else None
    result = save_prompt(
        args.workspace, args.name,
        content=args.content,
        tags=tags,
        description=getattr(args, 'description', ''),
        category=getattr(args, 'category', ''),
    )
    if result.get("saved"):
        print(f"\n{C['green']}\u2705 {_('prompt_saved_line').format(name=result['name'], version=result['version'])}{C['reset']}")
        if result.get('tags'):
            print(f"   {_('tag_search_label')}: [{', '.join(result['tags'])}]")
    else:
        print(f"\n{C['red']}\u274c {_('prompt_save_failed_line').format(error=result.get('error', _('unknown_error')))}{C['reset']}")
    return 0


def _h_prompt_search(args):
    C = get_colors()
    result = search_prompts(
        args.workspace,
        keyword=getattr(args, 'keyword', None),
        tag=getattr(args, 'tag', None),
    )
    if _emit(args, result):
        return 0
    if result["total"] == 0:
        print(f"\n{C['yellow']}\U0001f50d {_('prompt_no_match')}{C['reset']}")
    else:
        print(f"\n{C['bright']}\U0001f50d {_('prompt_search_header').format(n=result['total'])}{C['reset']}")
        for p in result["prompts"]:
            tags_str = f" [{','.join(p['tags'])}]" if p.get('tags') else ""
            score_str = " " + _("match_score_str").format(score=p['score']) if p.get('score') else ""
            print(f"   \U0001f4dd {p['name']}{tags_str}{score_str}")
    return 0


def _h_self_test(args):
    res = _handle_self_test(args)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


# ---- V3.10 上下文工程：选择器可见性 / 描述补写 ----

def _print_selector_summary(C, m):
    """打印候选池摘要三行（槽位压力 / 可见率 / token 占用）。"""
    level = _("selector_level_" + m["slot_pressure_level"])
    print(_("selector_candidates_line").format(
        candidates=m["candidate_count"], cap=m["slot_capacity"],
        pressure=m["slot_pressure"], level=level))
    print(_("selector_visible_line").format(
        visible=m["selector_visible_count"], total=m["candidate_count"],
        avg=m["avg_readiness"], stale=m["stale_count"]))
    print(_("selector_tokens_line").format(
        total=m["total_tokens_estimate"], reclaim=m["reclaimable_tokens_estimate"]))


def _print_selector_files(C, files):
    """打印候选记忆清单（就绪度升序，前 10 条）。"""
    print(f"\n{C['bright']}{_('selector_files_header')}{C['reset']}")
    icons = {"fresh": "\U0001f7e2", "aging": "\U0001f7e1", "stale": "\U0001f534"}
    for f in files[:10]:
        grade = _("selector_freshness_" + f["freshness"])
        icon = icons.get(f["freshness"], "\u26aa")
        label = _("selector_readiness_label")
        print(f"   {icon} {f['file']} [{grade}] {label}{f['readiness']} | {f['description'][:60]}")


def _h_selector_audit(args):
    C = get_colors()
    result = selector_audit(args.workspace, stale_days=getattr(args, 'stale_days', 30))
    if _emit(args, result):
        return 0
    if result.get("error"):
        print(f"\n{C['red']}\u274c {result['error']}{C['reset']}")
        return 0
    print(f"\n{C['bright']}\U0001f9f2 {_('selector_header')}{C['reset']}")
    print(f"{'='*54}")
    _print_selector_summary(C, result["metrics"])
    if result["issues"]:
        print(f"\n{C['yellow']}{_('selector_issues_header')}{C['reset']}")
        for item in result["issues"]:
            print(f"   \u26a0\ufe0f  {item}")
    if result["recommendations"]:
        print(f"\n{C['cyan']}{_('selector_recs_header')}{C['reset']}")
        for item in result["recommendations"]:
            print(f"   \u2192 {item}")
    if result["files"]:
        _print_selector_files(C, result["files"])
    print(f"{'='*54}")
    return 0


def _print_describe_items(rows, template_key):
    for row in rows[:15]:
        print("   " + _(template_key).format(
            file=row["file"], description=row["description"][:80]))


def _h_describe(args):
    C = get_colors()
    dry_run = not getattr(args, 'execute', False)
    result = apply_descriptions(args.workspace, dry_run=dry_run,
                                stale_days=getattr(args, 'stale_days', 30))
    if _emit(args, result):
        return 0
    if result.get("error"):
        print(f"\n{C['red']}\u274c {result['error']}{C['reset']}")
        return 0
    print(f"\n{C['bright']}\U0001f9f2 {_('selector_describe_header')}{C['reset']}")
    if result["dry_run"]:
        print("   " + _("selector_describe_planned").format(count=len(result["planned"])))
        _print_describe_items(result["planned"], "selector_plan_line")
    else:
        print("   " + _("selector_describe_applied").format(count=len(result["applied"])))
        _print_describe_items(result["applied"], "selector_applied_line")
    if result["skipped"]:
        print("   " + _("selector_describe_skipped").format(count=len(result["skipped"])))
    return 0
