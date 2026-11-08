import logging
logger = logging.getLogger(__name__)

# -*- coding: utf-8 -*-
"""
记忆管家 V3.0 - 缓存清理与提醒
来源: memory_manager.py (cache_clean/cache_reminder)
V3.0: 模块化重构
"""

import json
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

from .config import VERSION, _, get_colors, DEFAULT_DAILY_BUDGET
from .token import token_check
from .core_snapshot import snapshot_before_write


def _is_interactive_tty():
    """当前是否为交互式终端（cache 模块不依赖 CLI 层，故就地实现）。"""
    try:
        return sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def _rel_path(p, workspace):
    """返回相对路径字符串，越界则退回文件名。"""
    try:
        return str(p.relative_to(workspace))
    except ValueError:
        return p.name


def _collect_orphan_summaries(workbuddy_dir, workspace):
    """收集孤儿摘要（对应记忆 .md 已不存在）。"""
    items = []
    count = 0
    summary_dir = workbuddy_dir / ".summary"
    if summary_dir.exists():
        for sum_file in summary_dir.glob("*.summary"):
            memory_name = sum_file.stem
            memory_file = workbuddy_dir / "memory" / f"{memory_name}.md"
            if not memory_file.exists():
                items.append({
                    'path': _rel_path(sum_file, workspace), 'abs_path': str(sum_file),
                    'name': sum_file.name, 'type': 'orphan',
                    'size_kb': sum_file.stat().st_size / 1024
                })
                count += 1
    return items, count


def _collect_expired_stats(workbuddy_dir, workspace, days):
    """收集过期 token 统计文件。"""
    items = []
    count = 0
    stats_dir = workbuddy_dir / ".token_stats"
    if stats_dir.exists():
        cutoff = datetime.now() - timedelta(days=days)
        for stat_file in stats_dir.glob("*.json"):
            mtime = datetime.fromtimestamp(stat_file.stat().st_mtime)
            if mtime < cutoff:
                items.append({
                    'path': _rel_path(stat_file, workspace), 'abs_path': str(stat_file),
                    'name': stat_file.name, 'type': 'stats',
                    'size_kb': stat_file.stat().st_size / 1024,
                    'mtime': mtime.strftime('%Y-%m-%d')
                })
                count += 1
    return items, count


def _collect_pycache_dirs(workspace):
    """收集工作空间下所有 __pycache__ 目录及其体积。"""
    items = []
    for pycache in workspace.rglob("__pycache__"):
        if pycache.is_symlink() or not pycache.is_dir():
            continue
        try:
            pycache.resolve().relative_to(workspace)
        except ValueError:
            continue
        size_kb = sum(
            f.stat().st_size for f in pycache.rglob("*") if f.is_file() and not f.is_symlink()) / 1024
        items.append({
            'path': _rel_path(pycache, workspace), 'abs_path': str(pycache),
            'name': pycache.name + "/", 'type': 'temp', 'size_kb': size_kb
        })
    return items


def _collect_temp_files(workbuddy_dir, workspace):
    """收集记忆目录临时文件与 __pycache__ 目录。"""
    items = []
    count = 0
    temp_patterns = ['*.tmp', '*.cache', '*.bak', '*.swp', '*.temp']
    memory_dir = workbuddy_dir / "memory"
    if memory_dir.exists():
        for pattern in temp_patterns:
            for f in memory_dir.glob(pattern):
                if f.is_file():
                    items.append({
                        'path': _rel_path(f, workspace), 'abs_path': str(f),
                        'name': f.name, 'type': 'temp', 'size_kb': f.stat().st_size / 1024
                    })
                    count += 1
        for pycache in _collect_pycache_dirs(workspace):
            items.append(pycache)
            count += 1
    return items, count


def _execute_cache_cleanup(to_clean, workspace):
    """实际删除收集到的缓存项，返回 (cleaned, freed_kb, errors)。"""
    cleaned = 0
    freed_kb = 0
    errors = []
    for item in to_clean:
        try:
            p = Path(item.get('abs_path', item['path']))
            if not p.is_absolute():
                p = workspace / item['path']
            if p.is_symlink():
                errors.append(_("skip_symlink_named").format(name=item['name']))
                continue
            if p.is_file():
                freed_kb += item['size_kb']
                p.unlink()
                cleaned += 1
            elif p.is_dir():
                freed_kb += item['size_kb']
                shutil.rmtree(p, ignore_errors=True)
                cleaned += 1
        except Exception as e:
            errors.append(_("delete_failed_named").format(name=item['name'], error=e))
    return cleaned, freed_kb, errors


def _print_cache_clean_scan(C, cache_type, days, summary_count, stats_count,
                             temp_count, total_size_kb, to_clean):
    print(f"\n{C['bright']}\U0001f4ca {_('cache_scan_result')}:{C['reset']}")
    if cache_type in ('orphan', 'all'):
        print(f"   \U0001f4c4 {_('orphan_summaries')}: {summary_count}")
    if cache_type in ('stats', 'all'):
        print(f"   \U0001f4ca {_('expired_token_stats').format(days=days)}: {stats_count}")
    if cache_type in ('temp', 'all'):
        print(f"   \U0001f5c2\ufe0f  {_('temp_files_label')}: {temp_count}")
    print(f"   \U0001f4be {_('freeable_space')}: {total_size_kb:.1f} KB")
    print(f"\n{C['yellow']}\U0001f4cb {_('pending_clean_list')}:{C['reset']}")
    for i, item in enumerate(to_clean[:20], 1):
        print(f"   [{i}] [{item['type']}] {item['name']} ({item['size_kb']:.1f}KB)")
    if len(to_clean) > 20:
        print(f"   ... {_('and_more').format(count=len(to_clean)-20)}")


def _print_cache_clean_result(C, cleaned, freed_kb, errors, before_kb, after_kb, delta_kb):
    print(f"\n{C['green']}\u2705 {_('cleaned_n_files').format(count=cleaned, kb=f'{freed_kb:.1f}')}{C['reset']}")
    if errors:
        print(f"{C['red']}\u26a0\ufe0f  {_('clean_errors')}: {len(errors)}{''}")
        for err in errors[:5]:
            print(f"   {err}")
    if delta_kb > 0:
        print(f"\n{C['cyan']}\U0001f4ca {_('clean_size_comparison')}: {before_kb:.1f}KB \u2192 {after_kb:.1f}KB ({C['green']}-{delta_kb:.1f}KB{C['reset']}{C['cyan']}){C['reset']}")


def _collect_cache_targets(workbuddy_dir, workspace, cache_type, days):
    """按 cache_type 收集待清理缓存项，返回 (items, summary/stats/temp 计数)。"""
    to_clean = []
    summary_count = stats_count = temp_count = 0
    if cache_type in ('orphan', 'all'):
        items, summary_count = _collect_orphan_summaries(workbuddy_dir, workspace)
        to_clean.extend(items)
    if cache_type in ('stats', 'all'):
        items, stats_count = _collect_expired_stats(workbuddy_dir, workspace, days)
        to_clean.extend(items)
    if cache_type in ('temp', 'all'):
        items, temp_count = _collect_temp_files(workbuddy_dir, workspace)
        to_clean.extend(items)
    return to_clean, summary_count, stats_count, temp_count


def _cache_clean_confirmed(C, to_clean):
    """交互式二次确认门：非 TTY 直接安全取消，TTY 下要求输入 Y。

    V4.0.2 修复：非交互环境此前会走到 `input()` 并抛 EOFError 崩栈。
    """
    if not _is_interactive_tty():
        print(f"{C['green']}\u2705 {_('cancelled')}{C['reset']}")
        return False
    try:
        answer = input(
            f"\n{C['bright']}\u26a0\ufe0f  {_('confirm_clean_prompt').format(count=len(to_clean))}: {C['reset']}").strip().upper()
    except EOFError:
        answer = ""
    if answer != 'Y':
        print(f"{C['green']}\u2705 {_('cancelled')}{C['reset']}")
        return False
    return True


def cache_clean(workspace_path, dry_run=True, confirm=False, cache_type='all', days=30, C=None):
    if C is None:
        C = get_colors()
    workspace = Path(workspace_path).resolve()
    workbuddy_dir = workspace / ".workbuddy"
    before_kb = _calc_workbuddy_size(workbuddy_dir)
    print(f"{C['cyan']}\U0001f9f9 {_('cache_clean_analyzing')}{C['reset']}")
    to_clean, summary_count, stats_count, temp_count = _collect_cache_targets(
        workbuddy_dir, workspace, cache_type, days)
    total_size_kb = sum(item['size_kb'] for item in to_clean)
    _print_cache_clean_scan(C, cache_type, days, summary_count, stats_count,
                            temp_count, total_size_kb, to_clean)
    if not to_clean:
        print(f"\n{C['green']}\u2705 {_('no_cache_to_clean')}{C['reset']}")
        return {"cleaned": 0, "freed_kb": 0}
    if dry_run:
        print(f"\n{C['yellow']}\U0001f4a1 {_('preview_mode_notice')}{C['reset']}")
        print(f"{C['yellow']}\U0001f4a1 {_('add_execute_param')}{C['reset']}")
        return {"preview": len(to_clean), "freed_kb": total_size_kb,
                "before_kb": before_kb, "after_kb": before_kb, "delta_kb": 0}
    if not confirm and not _cache_clean_confirmed(C, to_clean):
        return {"cleaned": 0, "freed_kb": 0}
    snapshot = snapshot_before_write(workspace_path, "cache-clean")
    cleaned, freed_kb, errors = _execute_cache_cleanup(to_clean, workspace)
    after_kb = _calc_workbuddy_size(workbuddy_dir)
    delta_kb = round(before_kb - after_kb, 1)
    _print_cache_clean_result(C, cleaned, freed_kb, errors, before_kb, after_kb, delta_kb)
    return {"cleaned": cleaned, "freed_kb": freed_kb, "errors": errors,
            "snapshot": snapshot,
            "before_kb": round(before_kb, 1), "after_kb": round(after_kb, 1), "delta_kb": delta_kb}


def _accum_summary_sizes(summary_dir):
    """统计孤儿摘要数与占用大小（对应 .md 已不存在）。"""
    count = 0
    size_kb = 0.0
    if not summary_dir.exists():
        return count, size_kb
    for sum_file in summary_dir.glob("*.summary"):
        memory_name = sum_file.stem
        memory_file = summary_dir.parent / "memory" / f"{memory_name}.md"
        if not memory_file.exists():
            count += 1
        try:
            size_kb += sum_file.stat().st_size / 1024
        except OSError as e:
            logger.warning("non-fatal: %s", e)
    return count, size_kb


def _sum_op_tokens(stat_data):
    """聚合 operations.{op}.tokens（忽略异常值）。"""
    total = 0
    for op_data in stat_data.get("operations", {}).values():
        try:
            total += int(op_data.get("tokens", 0))
        except (ValueError, TypeError) as e:
            logger.warning("non-fatal: %s", e)
    return total


def _accum_stats_sizes(stats_dir):
    """统计过期统计文件数、占用大小与累计 token。"""
    count = 0
    size_kb = 0.0
    total_tokens = 0
    if not stats_dir.exists():
        return count, size_kb, total_tokens
    cutoff = datetime.now() - timedelta(days=30)
    for stat_file in stats_dir.glob("*.json"):
        mtime = datetime.fromtimestamp(stat_file.stat().st_mtime)
        if mtime < cutoff:
            count += 1
        try:
            size_kb += stat_file.stat().st_size / 1024
        except OSError as e:
            logger.warning("non-fatal: %s", e)
        try:
            stat_data = json.loads(stat_file.read_text(encoding="utf-8"))
            if isinstance(stat_data, dict):
                total_tokens += _sum_op_tokens(stat_data)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("non-fatal: %s", e)
    return count, size_kb, total_tokens


def _accum_temp_sizes(memory_dir):
    """统计临时文件（*.tmp / *.cache）数与占用大小。"""
    count = 0
    size_kb = 0.0
    if not memory_dir.exists():
        return count, size_kb
    for pattern in ["*.tmp", "*.cache"]:
        for f in memory_dir.glob(pattern):
            count += 1
            try:
                size_kb += f.stat().st_size / 1024
            except OSError as e:
                logger.warning("non-fatal: %s", e)
    return count, size_kb


def _format_cache_reminder(total_tokens, tk, total_cache_size_kb,
                            summary_count, stats_count, temp_count, total):
    msg = f"\U0001f9f9 {_('cache_reminder_title')}\n"
    if total_tokens > 0:
        msg += f"\U0001f4ca {_('cache_reminder_token_stats')}: ~{total_tokens:,} tokens {_('token_estimated_tag')}\n"
    else:
        msg += f"\U0001f4ca {_('cache_reminder_token_stats')}: {_('cache_reminder_token_no_data')}\n"

    msg += f"\n{tk['emoji']} {tk['message']}\n"

    if total_cache_size_kb > 1024:
        msg += f"\U0001f4be {_('cache_reminder_cache_size')}: {total_cache_size_kb / 1024:.1f} {_('cache_reminder_mb_unit')}\n"
    else:
        msg += f"\U0001f4be {_('cache_reminder_cache_size')}: {total_cache_size_kb:.1f} {_('cache_reminder_kb_unit')}\n"

    if summary_count > 0:
        msg += f"\U0001f4c4 {_('cache_reminder_orphan_summaries')}: {summary_count}\n"
    if stats_count > 0:
        msg += f"\U0001f4ca {_('cache_reminder_expired_stats')}: {stats_count}\n"
    if temp_count > 0:
        msg += f"\U0001f5c2\ufe0f {_('cache_reminder_temp_files')}: {temp_count}\n"

    if total == 0:
        msg += f"\u2705 {_('cache_reminder_no_cache_good')}"
    else:
        msg += f"\U0001f4a1 {_('cache_reminder_total_cleanable')}: {total}\n"
        msg += f"\U0001f4a1 {_('cache_reminder_manual_clean')}: memory_manager.py cache-clean --execute"
    return msg


def cache_reminder(workspace_path):
    workspace = Path(workspace_path)
    workbuddy_dir = workspace / ".workbuddy"

    summary_count, summary_kb = _accum_summary_sizes(workbuddy_dir / ".summary")
    stats_count, stats_kb, total_tokens = _accum_stats_sizes(workbuddy_dir / ".token_stats")
    temp_count, temp_kb = _accum_temp_sizes(workbuddy_dir / "memory")
    total_cache_size_kb = summary_kb + stats_kb + temp_kb

    total = summary_count + stats_count + temp_count

    tk = token_check(str(workspace), budget=DEFAULT_DAILY_BUDGET)
    msg = _format_cache_reminder(total_tokens, tk, total_cache_size_kb,
                                 summary_count, stats_count, temp_count, total)
    print(msg)

    return {
        "orphan": summary_count,
        "expired_stats": stats_count,
        "temp_files": temp_count,
        "total": total,
        "total_tokens": total_tokens,
        "cache_size_kb": round(total_cache_size_kb, 1)
    }


def _calc_workbuddy_size(workbuddy_dir):
    """计算 .workbuddy 目录总大小（KB）"""
    total = 0.0
    if not workbuddy_dir.exists():
        return 0.0
    try:
        for f in workbuddy_dir.rglob("*"):
            if f.is_file() and not f.is_symlink():
                try:
                    total += f.stat().st_size
                except (OSError, PermissionError) as e:
                    logger.warning("non-fatal: %s", e)

    except (OSError, PermissionError) as e:
        logger.warning("non-fatal: %s", e)

    return total / 1024
