import logging
logger = logging.getLogger(__name__)

# -*- coding: utf-8 -*-
"""
记忆管家 V3.0 - 报告生成与打印
来源: memory_manager.py (HTML/report/print)
V3.0: 模块化重构
"""

import json
from datetime import datetime
from pathlib import Path

from .config import (
    VERSION, _, _LANG, get_colors,
    MEMORY_LARGE_SIZE_KB, RECENT_DAYS, OLD_DAYS, DEFAULT_CONFIG,
    load_config,
)
from .token import kb_to_tokens, record_token_usage


def _print_report_stats(stats, C):
    print(f"\U0001f4ca {_('stats_overview')}:")
    print(f"   {_('total_files')}: {C['white']}{stats.get('total_files', 0)}{C['reset']}")
    print(f"   {_('total_usage')}: {C['yellow']}{stats.get('total_size_kb', 0):.2f} KB{C['reset']}")
    print(f"   {_('cleanable')}: {C['green']}{stats.get('cleanable_size_kb', 0):.2f} KB{C['reset']} ({stats.get('cleanable_files', 0)})")
    if "estimated_token_saving" in stats:
        print(f"   {_('estimated_token_saving')}: ~{C['magenta']}{stats['estimated_token_saving']}{C['reset']}")


def _print_report_files(files, C):
    print(f"\n\U0001f4c8 {_('file_distribution_top10')}:")
    for i, f in enumerate(files[:10], 1):
        if f.get("protected"):
            status = f"{C['red']}\U0001f512{C['reset']}"
        elif f.get("cleanable"):
            status = f"{C['green']}\U0001f5d1\ufe0f{C['reset']}"
        else:
            status = "\U0001f4c4"
        img = f" [{f.get('image_format')}]" if f.get("image_format") else ""
        print(f"   {status} {i}. {f['name'][:30]:30s} {f['size_kb']:>8.2f} KB {img}")


def _print_report_empty_dirs(empty_dirs):
    print(f"\n\U0001f4c2 {_('empty_dirs_count')} ({len(empty_dirs)})")
    for d in empty_dirs[:5]:
        print(f"   \u2022 {d}")
    if len(empty_dirs) > 5:
        print(f"   ... {_('and_more').format(count=len(empty_dirs)-5)}")


def _print_report_recs(recs):
    print(f"\n\U0001f4a1 {_('optimization_suggestions')}:")
    for r in recs:
        print(f"   {r}")


def print_report(result, format_type="text"):
    C = get_colors()
    if format_type == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    print(f"\n{C['bright']}{'='*50}{C['reset']}")
    print(f"{C['cyan']}\U0001f9e0 {_('memory_report')} V{VERSION}{C['reset']}")
    print(f"{C['bright']}{'='*50}{C['reset']}")
    print(f"\U0001f4c1 {_('workspace')}: {result.get('workspace', 'N/A')}")
    print(f"\u23f0 {_('timestamp')}: {result.get('timestamp', 'N/A')[:19]}")
    print()

    if "error" in result:
        print(f"{C['red']}\u274c {_('error')}: {result['error']}{C['reset']}")
        return

    _print_report_stats(result.get("stats", {}), C)

    if result.get("files"):
        _print_report_files(result["files"], C)
    if result.get("empty_dirs"):
        _print_report_empty_dirs(result["empty_dirs"])
    if result.get("recommendations"):
        _print_report_recs(result["recommendations"])
    if result.get("warning"):
        print(f"\n{C['yellow']}\u26a0\ufe0f  {_('warning')}: {result['warning']}{C['reset']}")

    print(f"\n{C['bright']}{'='*50}{C['reset']}")


def _print_analysis_files(files):
    print(f"\n\U0001f4dd {_('file_list')}:")
    for f in files[:20]:
        age = f.get("age_days", 0)
        status = "\U0001f195" if age <= RECENT_DAYS else "\U0001f4c5" if age <= OLD_DAYS else "\U0001f4c1"
        clean = "\U0001f5d1\ufe0f" if f.get("cleanable") else "  "
        print(f"   {status}{clean} {f['name']:30s} {f['size_kb']:>7.2f}KB  {f['modified']} ({age}{_('days_ago')})")
    if len(files) > 20:
        print(f"   ... {_('and_more').format(count=len(files)-20)} {_('files')}")


def _print_analysis_recs(recs):
    print(f"\n\U0001f4a1 {_('suggestions')}:")
    for r in recs:
        print(f"   {r}")


def print_memory_analysis(result, format_type="text"):
    if format_type == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    print(f"\n{'='*50}")
    print(f"\U0001f9e0 {_('memory_analysis')} V{VERSION}")
    print(f"{'='*50}")
    print(f"\U0001f4c1 {_('workspace')}: {result.get('workspace', 'N/A')}")
    print()

    if "error" in result:
        print(f"\u274c {_('error')}: {result['error']}")
        return

    stats = result.get("stats", {})
    print(f"\U0001f4ca {_('memory_status')}:")
    print(f"   {_('total_files')}: {stats.get('total_files', 0)}")
    print(f"   {_('total_usage')}: {stats.get('total_size_kb', 0):.2f} KB")

    if result.get("files"):
        _print_analysis_files(result["files"])
    if result.get("recommendations"):
        _print_analysis_recs(result["recommendations"])

    print(f"\n{'='*50}")


def print_preview(preview):
    print(f"\n{'='*50}")
    print(f"\U0001f9f9 {_('clean_preview')} {'[Preview]' if preview.get('dry_run') else ''}")
    print(f"{'='*50}")

    if "error" in preview:
        print(f"\u274c {_('error')}: {preview['error']}")
        return

    files = preview.get("files_to_clean", [])
    print(f"{_('will_delete_n_files').format(count=len(files))} ({preview.get('total_size_kb', 0):.1f} KB)")
    print(f"{_('estimated_token_saving')}: ~{preview.get('token_saving', 0)}")
    print()

    for i, f in enumerate(files[:20], 1):
        print(f"   [{i}] {f['name'][:40]:40s} {f['size_kb']:>7.2f} KB")

    if len(files) > 20:
        print(f"   ... {_('and_more').format(count=len(files)-20)} {_('files')}")

    print(f"\n{preview.get('message', '')}")
    print(f"\n{'='*50}")


def _scan_memory_files(memory_dir, _rules, _TYPE_MAP):
    """扫描记忆目录，聚合文件数/大小/类型/日期/新旧文件。"""
    from .clean import classify_content
    total_files = 0
    total_size_kb = 0.0
    by_type = {v: 0 for v in _TYPE_MAP.values()}
    by_date = {}
    recent_files = []
    old_files = []
    if not memory_dir.exists():
        return total_files, total_size_kb, by_type, by_date, recent_files, old_files
    for md_file in sorted(memory_dir.glob("*.md")):
        if md_file.name in ["MEMORY.md", "memory.md"]:
            continue
        total_files += 1
        try:
            size_kb = md_file.stat().st_size / 1024
            total_size_kb += size_kb
            mtime = datetime.fromtimestamp(md_file.stat().st_mtime)
            date_key = mtime.strftime("%Y-%m-%d")
            try:
                raw_type = classify_content(md_file, _rules)
                content_type = _TYPE_MAP.get(raw_type, _TYPE_MAP.get("other"))
            except Exception:
                content_type = _TYPE_MAP.get("other")
            by_date.setdefault(date_key, []).append({
                "name": md_file.name,
                "size_kb": round(size_kb, 1),
                "type": content_type,
                "date": mtime.strftime("%Y-%m-%d %H:%M")
            })
            by_type[content_type] += 1
            days_old = (datetime.now() - mtime).days
            if days_old <= 7:
                recent_files.append(md_file.name)
            elif days_old > 30:
                old_files.append(md_file.name)
        except OSError as e:
            logger.warning("non-fatal: %s", e)
    return total_files, total_size_kb, by_type, by_date, recent_files, old_files


def _accum_stat_file_tokens(stat_file):
    """统计单个 token_stats JSON 的 token 数与体积（KB）。"""
    size_kb = stat_file.stat().st_size / 1024
    tokens = 0
    try:
        stat_data = json.loads(stat_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, IOError, AttributeError) as e:
        logger.warning("non-fatal: %s", e)
        return tokens, size_kb
    if not isinstance(stat_data, dict):
        return tokens, size_kb
    for op_data in stat_data.get("operations", {}).values():
        try:
            tokens += int(op_data.get("tokens", 0))
        except (ValueError, TypeError) as e:
            logger.warning("non-fatal: %s", e)
    return tokens, size_kb


def _scan_cache_stats(workbuddy_dir):
    """扫描 token 统计与摘要缓存，聚合 token 总量与缓存体积。"""
    total_tokens = 0
    cache_size_kb = 0.0
    stats_dir = workbuddy_dir / ".token_stats"
    if stats_dir.exists():
        for stat_file in stats_dir.glob("*.json"):
            tk, sz = _accum_stat_file_tokens(stat_file)
            total_tokens += tk
            cache_size_kb += sz
    summary_dir = workbuddy_dir / ".summary"
    if summary_dir.exists():
        for f in summary_dir.glob("*.summary"):
            cache_size_kb += f.stat().st_size / 1024
    return total_tokens, cache_size_kb


def _report_date_age_tag(days_ago):
    """按天数返回中文 age 标签。"""
    if days_ago > 0:
        return f"({days_ago}{_('days_ago')})"
    return _("recent_7_days").split(" ")[0] if _LANG == "zh" else "(today)"


def _report_file_type_icon(f_type):
    """按类型返回图标。"""
    _push_label = _("report_type_push_label")
    _pw_label = _("report_type_personal_work_label")
    return "\U0001f534" if f_type == _push_label else "\U0001f7e1" if f_type == _pw_label else "\U0001f7e2"


def _format_report_by_date(by_date):
    """拼接按日期归档的文件列表块。"""
    if not by_date:
        return f"\n   ({_('no_files_to_clean')})\n"
    block = ""
    for date_key in sorted(by_date.keys(), reverse=True)[:10]:
        files = by_date[date_key]
        days_ago = (datetime.now() - datetime.strptime(date_key, "%Y-%m-%d")).days
        block += f"\n   \U0001f4c5 {date_key} {_report_date_age_tag(days_ago)}\n"
        for f in files[:5]:
            block += f"      {_report_file_type_icon(f['type'])} {f['name']} ({f['size_kb']}KB)\n"
        if len(files) > 5:
            block += f"      ... {_('and_more').format(count=len(files)-5)}\n"
    return block


def _format_report_additional(recent_files, old_files, cache_size_kb):
    """拼接附加信息块（归档提示/清理提示）。"""
    block = ""
    if recent_files:
        block += f"   \u2022 {_('recent_7_days')}: {len(recent_files)}\n"
    if old_files:
        block += f"   \u2022 {_('older_than_30_days')}: {len(old_files)}\n"
        block += f"   \u2022 {_('recommend_archive')}\n"
    if cache_size_kb > MEMORY_LARGE_SIZE_KB:
        block += f"   \u2022 {_('run_cache_clean')}\n"
    return block


def _format_report_msg(total_files, total_size_kb, total_tokens, cache_size_kb,
                       by_type, by_date, recent_files, old_files):
    """拼接报告文本（保持原有中文格式与图标）。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    msg = f"""
{'='*55}
\U0001f4cb {_('report_title')}
{_('generate_time')}: {now}
{'='*55}

\U0001f4ca {_('sec_open')}{_('report_memory_usage_stats')}{_('sec_close')}
   \u251c\u2500 {_('report_file_count')}: {total_files}
   \u251c\u2500 {_('report_disk_usage')}: {total_size_kb:.1f} KB
   \u251c\u2500 {_('report_token_usage')}: {_('approx_tokens').format(n=total_tokens) if total_tokens > 0 else _('cache_reminder_token_no_data')}
   \u251c\u2500 {_('report_cache_size')}: {cache_size_kb:.1f} KB
   \u2502
   \u251c\u2500 \U0001f534 {_('report_type_push')}: {by_type[_('report_type_push_label')]}
   \u251c\u2500 \U0001f7e1 {_('report_type_personal_work')}: {by_type[_('report_type_personal_work_label')]}
   \u2514\u2500 \U0001f7e2 {_('report_type_other')}: {by_type[_('report_type_other_label')]}

\U0001f4c1 {_('sec_open')}{_('file_list')} ({_('by_date')}){_('sec_close')}
"""
    msg += _format_report_by_date(by_date)
    msg += f"""
{'='*55}
\U0001f4a1 {_('sec_open')}{_('additional_info')}{_('sec_close')}
"""
    msg += _format_report_additional(recent_files, old_files, cache_size_kb)
    msg += f"""
   \u2022 memory_manager.py stats / auto-clean / summarize
{'='*55}
"""
    return msg


def generate_memory_report(workspace_path):
    workspace = Path(workspace_path)
    workbuddy_dir = workspace / ".workbuddy"
    memory_dir = workbuddy_dir / "memory"
    config = load_config()
    _rules = config.get("_automation_rules", DEFAULT_CONFIG["_automation_rules"])
    _TYPE_MAP = {"push": _("report_type_push_label"), "personal_work": _("report_type_personal_work_label"), "other": _("report_type_other_label")}
    total_files, total_size_kb, by_type, by_date, recent_files, old_files = _scan_memory_files(memory_dir, _rules, _TYPE_MAP)
    total_tokens, cache_size_kb = _scan_cache_stats(workbuddy_dir)
    print(_format_report_msg(total_files, total_size_kb, total_tokens, cache_size_kb,
                             by_type, by_date, recent_files, old_files))
    # 3.2 预算记账覆盖：report 分析消耗入账（D4）
    if total_size_kb > 0:
        try:
            record_token_usage(workspace_path, kb_to_tokens(total_size_kb), operation="report")
        except Exception as e:
            logger.warning("non-fatal: %s", e)
    return {
        "total_files": total_files,
        "total_size_kb": round(total_size_kb, 1),
        "total_tokens": total_tokens,
        "cache_size_kb": round(cache_size_kb, 1),
        "by_type": by_type,
        "by_date": by_date,
        "recent_files_count": len(recent_files),
        "old_files_count": len(old_files)
    }
