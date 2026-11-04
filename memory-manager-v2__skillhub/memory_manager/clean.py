import logging
logger = logging.getLogger(__name__)

# -*- coding: utf-8 -*-
"""
记忆管家 V3.0 - 清理、归档、去重、扫描模块
来源: memory_manager.py (auto_clean/archive/dedup/scan)
V3.0: 模块化重构
"""

import json
import os
import gzip
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .config import (
    VERSION, _, get_colors,
    MEMORY_VERY_MANY_FILES, SCAN_LARGE_CACHE_KB,
    DEFAULT_RETENTION_DAYS, PERSONAL_WORK_REMIND_DAYS,
    DEFAULT_CONFIG, PROTECTED_DIRS,
    MAX_REPORT_ITEMS, CLEANABLE_EXTS, IMAGE_EXTENSIONS,
    load_config, save_config,
    is_symlink, safe_resolve, get_file_info, detect_image_format,
    iter_memory_files,
)
from .token import compute_content_hash, kb_to_tokens, record_token_usage
from .core_snapshot import snapshot_before_write


def classify_content(file_path, rules, pre_read_content=None):
    if pre_read_content is not None:
        content = pre_read_content.lower()
    else:
        content = ""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read(2048).lower()
        except (OSError, IOError, UnicodeDecodeError) as e:
            logger.warning("non-fatal: %s", e)


    file_name_lower = file_path.name.lower()

    push_keywords = rules.get("push_content", {}).get("keywords", [])
    for kw in push_keywords:
        if kw.lower() in content or kw.lower() in file_name_lower:
            return "push"

    personal_keywords = rules.get("personal_work_content", {}).get("keywords", [])
    for kw in personal_keywords:
        if kw.lower() in content or kw.lower() in file_name_lower:
            return "personal_work"

    return "other"


def check_remind_due(config):
    last_remind = config.get("last_remind_date", "")
    remind_days = config.get("auto_remind_days", 5)
    if not last_remind:
        return True
    try:
        last_date = datetime.strptime(last_remind, "%Y-%m-%d").date()
        days_since = (datetime.now().date() - last_date).days
        return days_since >= remind_days
    except (ValueError, TypeError):
        return True


def _compress_file(src_path, dst_path):
    """通用文件压缩：>100MB 跳过压缩直接拷贝，否则 gzip 压缩"""
    file_size = src_path.stat().st_size
    if file_size > 100 * 1024 * 1024:
        shutil.copy2(src_path, dst_path)
    else:
        with open(src_path, 'rb') as f_in:
            with gzip.open(dst_path, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out, length=64 * 1024)


def _do_archive(md_file, mtime, base_path):
    archive_dir = base_path / ".workbuddy" / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_name = f"{md_file.stem}_{mtime.strftime('%Y%m%d')}.md.gz"
    archive_file = archive_dir / archive_name
    _compress_file(md_file, archive_file)
    md_file.unlink()


def _auto_clean_archive(md_file, mtime, base_path, result, size_kb):
    """执行归档（压缩+删除），记录成功/失败到 result。"""
    try:
        _do_archive(md_file, mtime, base_path)
        result["files_archived"] += 1
        result["size_freed_kb"] += size_kb
    except Exception as e:
        result["errors"].append(f"{md_file.name}: {str(e)}")


def _auto_clean_try_archive(result, md_file, mtime, base_path, size_kb, confirm_action, dry_run):
    """归档（压缩+删除）+ 计数，仅 confirm 且非 dry_run 时执行。"""
    if confirm_action and not dry_run:
        _auto_clean_archive(md_file, mtime, base_path, result, size_kb)


def _auto_clean_process_file(md_file, mtime, size_kb, content_type, content_filter,
                             rules, config, base_path, result, dry_run, confirm_action):
    """处理单个记忆文件的归类/提醒/归档，原地更新 result。"""
    age = (datetime.now() - mtime).days
    file_entry = {
        "name": md_file.name,
        "age_days": age,
        "size_kb": round(size_kb, 2),
        "modified": mtime.strftime("%Y-%m-%d"),
        "type": content_type
    }

    if content_filter and content_filter != content_type and content_filter != "all":
        result["kept_files"].append({**file_entry, "reason": _("content_filter_skip").format(type=content_type)})
        return

    if content_type == "push":
        push_retention = rules.get("push_content", {}).get("retention_days", 1)
        if age >= push_retention:
            result["remind_files"].append({**file_entry,
                                           "reason": _("file_type_push_remind").format(retention=push_retention)})
            result["clean_summary"]["push_to_remind"] += 1
        else:
            result["kept_files"].append({**file_entry,
                                         "reason": _("file_type_push_keeping").format(age=age)})

    elif content_type == "personal_work":
        if check_remind_due(config):
            result["remind_files"].append({**file_entry, "reason": _("file_type_personal_remind")})
            result["clean_summary"]["personal_work_to_remind"] += 1
        else:
            result["kept_files"].append(
                {**file_entry, "reason": _("file_type_personal_keeping").format(remind=PERSONAL_WORK_REMIND_DAYS)})

    else:
        default_retention = config.get("retention_days", 1)
        if age >= default_retention:
            result["remind_files"].append(
                {**file_entry, "reason": _("file_type_other_remind").format(retention=default_retention)})
            result["clean_summary"]["other_to_remind"] += 1
        else:
            result["kept_files"].append({**file_entry, "reason": _("within_retention").format(age=age)})

    if content_type != "personal_work":
        _auto_clean_try_archive(result, md_file, mtime, base_path, size_kb, confirm_action, dry_run)


def _auto_clean_scan_file(md_file, memory_path, rules, content_filter, confirm_action, dry_run, result, base_path, config):
    """处理单文件：读内容→分类→归档，返回本文件扫描体积(KB)。"""
    if md_file.name == "MEMORY.md":
        result["kept_files"].append({"name": md_file.name, "reason": _("file_type_core"), "type": "core"})
        return 0
    mtime, size_kb = get_file_info(md_file)
    size_kb = size_kb or 0
    try:
        with open(md_file, 'r', encoding='utf-8', errors='ignore') as f:
            pre_content = f.read(2048)
    except (OSError, IOError, UnicodeDecodeError) as e:
        logger.warning("non-fatal: %s", e)
        pre_content = None
    content_type = classify_content(md_file, rules, pre_read_content=pre_content)
    _auto_clean_process_file(md_file, mtime, size_kb, content_type, content_filter,
                             rules, config, base_path, result, dry_run, confirm_action)
    return size_kb


def auto_clean_memory(workspace_path, dry_run=True, content_filter=None, confirm_action=False):
    config = load_config()
    rules = config.get("_automation_rules", DEFAULT_CONFIG["_automation_rules"])
    base_path = Path(workspace_path).resolve()
    memory_path = base_path / ".workbuddy" / "memory"

    result = {
        "timestamp": datetime.now().isoformat(),
        "retention_days": config["retention_days"],
        "auto_remind_days": config["auto_remind_days"],
        "auto_archive": config["auto_archive"],
        "push_auto_clean_days": rules.get("push_content", {}).get("retention_days", 1),
        "personal_work_remind_days": rules.get("personal_work_content", {}).get("remind_days", 5),
        "files_archived": 0,
        "size_freed_kb": 0,
        "kept_files": [],
        "remind_files": [],
        "errors": [],
        "clean_summary": {
            "push_to_remind": 0,
            "personal_work_to_remind": 0,
            "other_to_remind": 0
        }
    }
    scanned_size_kb = 0

    if not memory_path.exists():
        result["error"] = _("memory_dir_not_exist")
        return result

    today = datetime.now().date()

    for md_file, mtime, size_kb, rel_path in iter_memory_files(memory_path, skip_memory_md=False):
        scanned_size_kb += _auto_clean_scan_file(
            md_file, memory_path, rules, content_filter, confirm_action, dry_run, result, base_path, config)

    if confirm_action and not dry_run:
        config["last_clean_date"] = today.isoformat()
        if result["remind_files"]:
            config["last_remind_date"] = today.isoformat()
        save_config(config)

    # 3.2 预算记账覆盖：auto-clean 扫描消耗入账（D4）
    if scanned_size_kb > 0:
        try:
            record_token_usage(workspace_path, kb_to_tokens(scanned_size_kb), operation="clean")
        except Exception as e:
            logger.warning("non-fatal: %s", e)

    return result


def _clean_collect_files(workbuddy_path):
    """收集 .workbuddy 下所有待清理文件（跳过符号链接/越界/受保护目录）。"""
    files_to_delete = []
    for file_path in workbuddy_path.rglob("*"):
        if is_symlink(file_path):
            continue
        if safe_resolve(file_path, workbuddy_path) is None:
            continue
        if not file_path.is_file():
            continue
        rel_path = file_path.relative_to(workbuddy_path)
        parent_dir = str(rel_path.parts[0]) if rel_path.parts else ""
        if parent_dir in PROTECTED_DIRS:
            continue
        is_cleanable = (
            file_path.suffix.lower() in CLEANABLE_EXTS or
            'cache' in file_path.name.lower() or
            'temp' in file_path.name.lower()
        )
        if is_cleanable:
            files_to_delete.append(file_path)
    return files_to_delete


def _clean_delete_one(file_path, result):
    """删除单文件，更新 result 计数。"""
    try:
        mtime, size_kb = get_file_info(file_path)
        file_path.unlink()
        result["deleted_count"] += 1
        result["deleted_size_kb"] += size_kb if size_kb else 0
    except Exception as e:
        result["failed_count"] += 1
        result["errors"].append(f"{file_path.name}: {str(e)}")


def _clean_invoke_progress(progress_callback, done, total, name):
    """安全调用进度回调。"""
    try:
        progress_callback(done, total, name)
    except Exception as e:
        logger.warning("non-fatal: %s", e)


def _clean_delete_all(files_to_delete, result, workspace_path, workbuddy_path, before_kb, progress_callback):
    """执行删除并记账；原地更新 result。"""
    total = len(files_to_delete)
    done = 0
    for file_path in files_to_delete:
        _clean_delete_one(file_path, result)
        done += 1
        if progress_callback is not None:
            _clean_invoke_progress(progress_callback, done, total, file_path.name)
    after_kb = _calc_dir_size_kb(workbuddy_path)
    result["after_kb"] = round(after_kb, 1)
    result["delta_kb"] = round(before_kb - after_kb, 1)
    # 3.2 预算记账覆盖：clean 删除操作消耗入账（D4）
    if result["deleted_size_kb"] > 0:
        try:
            record_token_usage(workspace_path, kb_to_tokens(result["deleted_size_kb"]), operation="clean")
        except Exception as e:
            logger.warning("non-fatal: %s", e)


def execute_cleanup(workspace_path, confirm=False, progress_callback=None):
    base_path = Path(workspace_path).resolve()
    workbuddy_path = base_path / ".workbuddy"

    # 清理前快照
    before_kb = _calc_dir_size_kb(workbuddy_path)

    result = {
        "deleted_count": 0,
        "deleted_size_kb": 0,
        "failed_count": 0,
        "errors": [],
        "before_kb": round(before_kb, 1),
        "after_kb": round(before_kb, 1),
        "delta_kb": 0,
    }

    if not workbuddy_path.exists():
        result["errors"].append(_("workbuddy_dir_not_exist"))
        return result

    files_to_delete = _clean_collect_files(workbuddy_path)
    if confirm:
        if files_to_delete:
            result["snapshot"] = snapshot_before_write(workspace_path, "clean")
        _clean_delete_all(files_to_delete, result, workspace_path, workbuddy_path, before_kb, progress_callback)
    else:
        result["pending_delete"] = len(files_to_delete)

    return result


def _scan_recursive_collect(workbuddy_path):
    """递归收集 .workbuddy 下所有条目（跳过符号链接/越界路径），含文件与目录。"""
    collected = []

    def _walk(dir_path):
        try:
            with os.scandir(dir_path) as entries:
                for entry in entries:
                    if entry.is_symlink():
                        continue
                    try:
                        Path(entry.path).resolve().relative_to(workbuddy_path)
                    except (OSError, ValueError):
                        continue
                    collected.append(Path(entry.path))
                    if entry.is_dir():
                        _walk(Path(entry.path))
        except (OSError, PermissionError) as e:
            logger.warning("non-fatal: %s", e)

    _walk(workbuddy_path)
    return collected


def _classify_file(file_path, rel_path, exclude_dirs):
    """返回 (is_protected, is_cleanable)。"""
    parent_dir = str(rel_path.parts[0]) if rel_path.parts else ""
    is_protected = (
        parent_dir in PROTECTED_DIRS or
        any(ex in str(rel_path) for ex in exclude_dirs)
    )
    is_cleanable = (
        not is_protected and
        (
            file_path.suffix.lower() in CLEANABLE_EXTS or
            'cache' in file_path.name.lower() or
            'temp' in file_path.name.lower()
        )
    )
    return is_protected, is_cleanable


def _scan_process_file(file_path, workbuddy_path, exclude_dirs, result):
    """分类单文件并更新 result 的 files/stats；返回 True 表示已达上限需 break。"""
    mtime, size_kb = get_file_info(file_path)
    if mtime is None:
        return False

    rel_path = file_path.relative_to(workbuddy_path)
    is_protected, is_cleanable = _classify_file(file_path, rel_path, exclude_dirs)

    image_format = None
    if file_path.suffix.lower() in IMAGE_EXTENSIONS and int(size_kb) < 5000:
        image_format = detect_image_format(file_path)

    file_info = {
        "name": file_path.name,
        "path": str(rel_path),
        "size_kb": round(size_kb, 2),
        "modified": mtime.strftime("%Y-%m-%d"),
        "protected": is_protected,
        "cleanable": is_cleanable,
        "image_format": image_format
    }
    result["files"].append(file_info)
    result["stats"]["total_files"] += 1
    result["stats"]["total_size_kb"] += size_kb
    if is_cleanable:
        result["stats"]["cleanable_files"] += 1
        result["stats"]["cleanable_size_kb"] += size_kb
    elif is_protected:
        result["stats"]["protected_size_kb"] += size_kb

    if len(result["files"]) >= MAX_REPORT_ITEMS:
        result["warning"] = _("files_over_limit").format(limit=MAX_REPORT_ITEMS)
        return True
    return False


def _collect_empty_dir(file_path, workbuddy_path, result):
    """若目录为空（无成员），记入 empty_dirs。"""
    try:
        if not any(file_path.iterdir()):
            result["empty_dirs"].append(str(file_path.relative_to(workbuddy_path)))
    except (OSError, PermissionError) as e:
        logger.warning("non-fatal: %s", e)


def scan_workspace(workspace_path, exclude_dirs=None, clean_empty_dirs=False):
    base_path = Path(workspace_path).resolve()
    workbuddy_path = base_path / ".workbuddy"
    result = {
        "version": VERSION,
        "workspace": workspace_path,
        "timestamp": datetime.now().isoformat(),
        "files": [],
        "empty_dirs": [],
        "stats": {
            "total_files": 0,
            "total_size_kb": 0,
            "cleanable_files": 0,
            "cleanable_size_kb": 0,
            "protected_size_kb": 0
        },
        "recommendations": []
    }

    if not workbuddy_path.exists():
        result["error"] = _("workbuddy_dir_not_exist")
        return result

    if exclude_dirs is None:
        exclude_dirs = []

    scanned_files = _scan_recursive_collect(workbuddy_path)

    for file_path in scanned_files:
        if file_path.is_file():
            if _scan_process_file(file_path, workbuddy_path, exclude_dirs, result):
                break
        elif clean_empty_dirs and file_path.is_dir():
            _collect_empty_dir(file_path, workbuddy_path, result)

    result["files"].sort(key=lambda x: x["size_kb"], reverse=True)

    estimated_token_saving = kb_to_tokens(result["stats"]["cleanable_size_kb"])
    result["stats"]["estimated_token_saving"] = estimated_token_saving
    result["stats"]["token_saving_note"] = _("estimated_token_saving")

    result["recommendations"] = _generate_scan_recommendations(
        result["stats"],
        len(result["empty_dirs"])
    )

    return result


def _generate_scan_recommendations(stats, empty_dir_count):
    recs = []

    cleanable = stats["cleanable_size_kb"]
    if cleanable > SCAN_LARGE_CACHE_KB:
        recs.append(_("scan_rec_cleanable_cache").format(size=cleanable))
    elif cleanable > 0:
        recs.append(_("scan_rec_cleanable_cache_small").format(size=cleanable))

    if empty_dir_count > 0:
        recs.append(_("scan_rec_empty_dirs").format(count=empty_dir_count))

    if stats["total_files"] > MEMORY_VERY_MANY_FILES:
        recs.append(_("scan_rec_many_files").format(count=stats['total_files']))

    if cleanable == 0 and empty_dir_count == 0:
        recs.append(_("scan_rec_good_storage"))

    return recs


def _resolve_archive_dir(archive_path, base_path):
    """归档目录：显式路径优先，否则落在工作区 `.workbuddy/archive`。"""
    return Path(archive_path) if archive_path else base_path / ".workbuddy" / "archive"


def _archive_one_file(md_file, mtime, size_kb, archive_dir, confirm, result):
    """压缩单个过期记忆文件；confirm 为真时删除原文件（真删除）。"""
    try:
        archive_file = archive_dir / f"{md_file.stem}_{mtime.strftime('%Y%m%d')}.md.gz"
        _compress_file(md_file, archive_file)
        if confirm:
            md_file.unlink()
        else:
            result["pending_delete"] = result.get("pending_delete", 0) + 1
        result["archived_count"] += 1
        result["archived_size_kb"] += size_kb
    except Exception as e:
        result["failed_count"] += 1
        logger.warning("non-fatal: %s", e)


def _record_archive_usage(workspace_path, result, confirm):
    """预算记账覆盖：archive 操作消耗入账（D4，仅在真正删除时记账）。"""
    if not (confirm and result["archived_size_kb"] > 0):
        return
    try:
        record_token_usage(workspace_path, kb_to_tokens(result["archived_size_kb"]), operation="archive")
    except Exception as e:
        logger.warning("non-fatal: %s", e)


def archive_old_memory(workspace_path, age_days=30, archive_path=None, confirm=False):
    base_path = Path(workspace_path).resolve()
    memory_path = base_path / ".workbuddy" / "memory"
    archive_dir = _resolve_archive_dir(archive_path, base_path)
    archive_dir.mkdir(parents=True, exist_ok=True)

    result = {
        "archived_count": 0,
        "archived_size_kb": 0,
        "failed_count": 0,
        "archive_path": str(archive_dir)
    }

    if not memory_path.exists():
        result["error"] = _("memory_dir_not_exist")
        return result

    snapshotted = False
    for md_file, mtime, size_kb, rel_path in iter_memory_files(memory_path, skip_memory_md=True):
        if (datetime.now() - mtime).days <= age_days:
            continue

        # 归档是**真正删除记忆文件**的操作（压缩后 unlink），落盘前必须有快照兜底
        if confirm and not snapshotted:
            result["snapshot"] = snapshot_before_write(workspace_path, "archive")
            snapshotted = True

        _archive_one_file(md_file, mtime, size_kb, archive_dir, confirm, result)

    # 3.2 预算记账覆盖：archive 操作消耗入账（D4）
    _record_archive_usage(workspace_path, result, confirm)

    return result


def _dedup_collect_hashes(memory_path, result):
    """遍历记忆文件，按内容哈希分组，累计 total_files / scanned_size_kb。"""
    file_hashes = {}
    scanned_size_kb = 0
    for md_file, mtime, size_kb, rel_path in iter_memory_files(memory_path):
        h = compute_content_hash(md_file)
        file_hashes.setdefault(h, [])
        # 安全：使用相对路径替代绝对路径，避免泄露用户目录结构
        file_hashes[h].append(
            {"path": rel_path, "name": md_file.name, "size_kb": round(size_kb, 2),
             "modified": mtime.strftime("%Y-%m-%d")})
        result["total_files"] += 1
        scanned_size_kb += size_kb
    return file_hashes, scanned_size_kb


def _delete_dup_file(base_path, dup, result):
    """删除单条重复文件，实际删除量与失败原因都记账。

    V4.0.2 修复：dup["path"] 来自 `_dedup_collect_hashes`，是**相对记忆目录**
    （`.workbuddy/memory/`）的路径；旧实现把它拼到工作区根，于是 unlink 必然
    FileNotFoundError 并被 `non-fatal` 日志吞掉 —— 命令对外报告「已删除 N 个
    重复项、释放 X KB」，磁盘上却一个文件都没动。现在拼接正确，且只按**实测**
    结果记账（deleted / freed_kb），失败条目进 errors。
    """
    memory_path = base_path / ".workbuddy" / "memory"
    try:
        dup_abs_path = memory_path / dup["path"]
        if not dup_abs_path.resolve().is_relative_to(base_path):
            result["errors"].append(
                _("delete_failed_named").format(name=dup["path"], error="outside workspace"))
            return
        if not dup_abs_path.is_file():
            result["errors"].append(
                _("delete_failed_named").format(name=dup["path"], error="not a regular file"))
            return
        size_kb = dup_abs_path.stat().st_size / 1024
        dup_abs_path.unlink()
        result["deleted"] += 1
        result["freed_kb"] = round(result["freed_kb"] + size_kb, 2)
    except (OSError, IOError, PermissionError) as e:
        result["errors"].append(
            _("delete_failed_named").format(name=dup["path"], error=e))


def _dedup_group_duplicates(file_hashes, result):
    """按哈希分组：>1 的组记入 duplicate_groups，返回待删文件清单。"""
    pending = []
    for h, files in file_hashes.items():
        if len(files) <= 1:
            continue
        files.sort(key=lambda x: x["modified"])
        dups = files[1:]
        result["duplicate_groups"].append(
            {"hash": h[:12] + "...", "original": files[0], "duplicates": dups})
        result["duplicates_found"] += len(dups)
        result["space_saved_kb"] += sum(f["size_kb"] for f in dups)
        pending.extend(dups)
    return pending


def _dedup_execute(base_path, workspace_path, pending, result):
    """两阶段删除的第二步：先统一建一次快照，再逐条删除。"""
    result["snapshot"] = snapshot_before_write(workspace_path, "dedup")
    for dup in pending:
        _delete_dup_file(base_path, dup, result)


def _record_dedup_usage(workspace_path, scanned_size_kb):
    """预算记账覆盖：dedup 扫描消耗入账（D4）。"""
    if scanned_size_kb <= 0:
        return
    try:
        record_token_usage(workspace_path, kb_to_tokens(scanned_size_kb), operation="dedup")
    except Exception as e:
        logger.warning("non-fatal: %s", e)


def dedup_memory(workspace_path, dry_run=True, delete_dup=False):
    base_path = Path(workspace_path).resolve()
    memory_path = base_path / ".workbuddy" / "memory"
    result = {"total_files": 0, "unique_files": 0, "duplicate_groups": [], "duplicates_found": 0,
              "space_saved_kb": 0,          # 预估可省（预览用）
              "deleted": 0, "freed_kb": 0.0,  # 实际删除量（--execute 用）
              "errors": []}
    if not memory_path.exists():
        result["error"] = _("memory_dir_not_exist")
        return result
    file_hashes, scanned_size_kb = _dedup_collect_hashes(memory_path, result)
    pending = _dedup_group_duplicates(file_hashes, result)
    # 删除前统一建一次快照（两阶段：先算清待删集合，再落盘）
    if not dry_run and delete_dup and pending:
        _dedup_execute(base_path, workspace_path, pending, result)

    # 3.2 预算记账覆盖：dedup 扫描消耗入账（D4）
    _record_dedup_usage(workspace_path, scanned_size_kb)

    result["unique_files"] = result["total_files"] - result["duplicates_found"]
    return result


def generate_cleanup_preview(workspace_path, dry_run=True):
    scan_result = scan_workspace(workspace_path)

    preview = {
        "version": VERSION,
        "timestamp": datetime.now().isoformat(),
        "dry_run": dry_run,
        "files_to_clean": [],
        "total_size_kb": 0,
        "token_saving": 0,
        "message": ""
    }

    if "error" in scan_result:
        preview["error"] = scan_result["error"]
        return preview

    for f in scan_result["files"]:
        if f["cleanable"]:
            preview["files_to_clean"].append(f)
            preview["total_size_kb"] += f["size_kb"]

    preview["token_saving"] = kb_to_tokens(preview["total_size_kb"])
    preview["token_saving_note"] = _("estimated_token_saving")

    if dry_run:
        preview["message"] = _("preview_mode_msg").format(count=len(preview['files_to_clean']), size=preview['total_size_kb'])
    else:
        preview["message"] = _("will_delete_n_files_msg").format(count=len(preview['files_to_clean']))

    return preview


def _calc_dir_size_kb(dir_path):
    """计算目录总大小（KB），用于清理前后对比"""
    total = 0.0
    if not dir_path.exists():
        return 0.0
    try:
        for f in dir_path.rglob("*"):
            if f.is_file() and not f.is_symlink():
                try:
                    total += f.stat().st_size
                except (OSError, PermissionError) as e:
                    logger.warning("non-fatal: %s", e)

    except (OSError, PermissionError) as e:
        logger.warning("non-fatal: %s", e)

    return total / 1024
