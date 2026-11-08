import logging
logger = logging.getLogger(__name__)

# -*- coding: utf-8 -*-
"""
记忆管家 V3.0 - 导入导出备份恢复
来源: memory_manager.py (export/import/backup/restore)
V3.0: 模块化重构
"""

import json
import shutil
import gzip
from datetime import datetime
from pathlib import Path

from .config import (
    VERSION, _, get_colors,
    MAX_FILE_SIZE,
    load_config,
    is_symlink, get_file_info,
)
from .token import compute_content_hash
from .core_perms import harden_file, harden_tree, verify_sums, write_sums

# ZIP 安全限制常量
MAX_IMPORT_SINGLE_FILE_SIZE = MAX_FILE_SIZE          # 单文件 1MB 上限
MAX_IMPORT_TOTAL_SIZE = 50 * 1024 * 1024             # 解压总大小 50MB 上限
MAX_IMPORT_ENTRIES = 1000                             # ZIP 条目数上限


def _export_invoke_progress(progress_callback, done, total, name):
    """安全调用进度回调（忽略非致命异常）。"""
    if progress_callback is None:
        return
    try:
        progress_callback(done, total, name)
    except Exception as e:
        logger.warning("non-fatal: %s", e)


def _export_summary_entries(zf, summary_dir):
    """将 .summary 目录下的摘要文件追加进导出 ZIP。"""
    if not summary_dir.exists():
        return
    for sum_file in summary_dir.glob("*.summary"):
        if is_symlink(sum_file):
            continue
        safe_name = (".summary/" + sum_file.name)
        zf.write(sum_file, arcname=safe_name)


def export_memories(workspace_path, output_file, progress_callback=None):
    workspace = Path(workspace_path).resolve()
    memory_dir = workspace / ".workbuddy" / "memory"
    output_path = Path(output_file)

    if not memory_dir.exists():
        return {"error": _("memory_dir_not_exist_detail")}

    error_note = _("export_failed") if _("export_failed") != "export_failed" else "Export failed"

    try:
        import zipfile

        md_files = [f for f in memory_dir.glob("*.md") if not is_symlink(f)]
        total = len(md_files)
        done = 0
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for md_file in md_files:
                safe_name = md_file.relative_to(memory_dir).as_posix()
                zf.write(md_file, arcname=safe_name)
                done += 1
                _export_invoke_progress(progress_callback, done, total, md_file.name)

            _export_summary_entries(zf, workspace / ".workbuddy" / ".summary")

        file_size = output_path.stat().st_size
        harden_file(output_path)     # V4.0.3：导出包含记忆明文，POSIX 下收敛为 0600
        return {
            "exported_file": str(output_path),
            "size_kb": round(file_size / 1024, 2),
            "message": _("export_success")
        }
    except ImportError:
        return {"error": error_note}


def _import_validate_zip(zf, result):
    """ZIP Bomb 预检。返回 (total_uncompressed, hard_error, oversized)。

    V4.0.2 修复：单文件超限此前**只记 errors 不跳过**，20MB 文件照样落盘；
    而读取侧的 1MB 硬上限又让它永远读不出来（analyze 报 0 文件，doctor 才报
    「异常大文件」）——等于往记忆目录里塞了一颗哑弹。现在超限条目名会被
    收集进 oversized，由调用方在写入前跳过。
    """
    total_uncompressed = 0
    entry_count = 0
    oversized = []
    for member in zf.infolist():
        entry_count += 1
        total_uncompressed += member.file_size
        if member.file_size > MAX_IMPORT_SINGLE_FILE_SIZE:
            oversized.append(member.filename)
            result["errors"].append(
                _("io_refuse_single_file").format(
                    name=member.filename, kb=member.file_size // 1024))
    if entry_count > MAX_IMPORT_ENTRIES:
        return total_uncompressed, _("io_refuse_entries").format(
            n=entry_count, limit=MAX_IMPORT_ENTRIES), oversized
    if total_uncompressed > MAX_IMPORT_TOTAL_SIZE:
        return total_uncompressed, _("io_refuse_total").format(
            mb=total_uncompressed // (1024 * 1024),
            limit=MAX_IMPORT_TOTAL_SIZE // (1024 * 1024)), oversized
    return total_uncompressed, None, oversized


def _path_has_traversal(raw_name):
    """检测 ZIP 条目 / 清单 key 是否含路径穿越或空路径分量（不做位置豁免）。

    V4.0.2 修复：早期实现写作 `... and i > 0`，对**首段**放行，
    于是 `../x.md` 被判定为「无穿越」而通过——虽被后续的工作区边界兜住，
    但它把「拒绝」降级成了「碰巧拦下」。首段 `..` 与首段空分量同样必须拒绝。
    """
    parts = raw_name.replace('\\', '/').split('/')
    return any(p in ('..', '') for p in parts)


def _path_is_absolute(raw_name):
    """检测 ZIP 条目是否为绝对路径（含盘符）。"""
    return (raw_name.startswith('/') or raw_name.startswith('\\')
            or (len(raw_name) >= 2 and raw_name[1] == ':'))


def _import_safe_target(raw_name, workspace, memory_dir, summary_dir):
    """ZIP Slip 五层防御：返回 (target_path, is_summary, error)。
    error 非空=拒绝该条目；target_path 为 None 且 error 为空=空路径跳过。"""
    if _path_has_traversal(raw_name):
        return None, False, _("io_refuse_traversal").format(name=raw_name)
    if _path_is_absolute(raw_name):
        return None, False, _("io_refuse_absolute").format(name=raw_name)
    safe_path = raw_name.replace('\\', '/').lstrip('/')
    if not safe_path or safe_path in ('.', '..'):
        return None, False, None  # 空路径：静默跳过
    if not (safe_path.endswith('.md') or safe_path.endswith('.summary')):
        return None, False, _("io_refuse_type").format(name=safe_path)

    is_summary = safe_path.startswith('.summary/')
    target_dir = summary_dir if is_summary else memory_dir
    target_name = safe_path[len('.summary/'):] if is_summary else safe_path
    target_path = target_dir / target_name

    # 5) 最终边界校验：解析后必须落在工作空间内（防御符号链接逃逸）
    try:
        resolved = target_path.resolve()
        resolved.relative_to(workspace)
    except (ValueError, OSError):
        return None, False, _("io_refuse_outside").format(name=safe_path)

    return resolved, is_summary, None


def _safe_unlink(target_path):
    """安全删除（忽略非致命错误）。"""
    try:
        target_path.unlink()
    except OSError as e:
        logger.warning("non-fatal: %s", e)


def _copy_zip_member_chunks(source, target_path, result, counter, dest):
    """分块复制 ZIP 成员，追踪总字节，超限返回 'exceed'。"""
    while True:
        chunk = source.read(64 * 1024)
        if not chunk:
            return "ok"
        counter[0] += len(chunk)
        if counter[0] > MAX_IMPORT_TOTAL_SIZE:
            _safe_unlink(target_path)
            result["errors"].append(
                _("io_refuse_total_interrupt").format(
                    limit=MAX_IMPORT_TOTAL_SIZE // (1024 * 1024)))
            return "exceed"
        dest.write(chunk)


def _import_write_member(zf, member, target_path, is_summary, result, counter):
    """安全写入单条 ZIP 成员（分块 + ZIP Bomb 总字节追踪）。
    counter=[extracted_total] 跨成员累计；返回 'exceed' 表示中断整个导入。"""
    try:
        with zf.open(member) as source:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with open(target_path, 'wb') as dest:
                status = _copy_zip_member_chunks(source, target_path, result, counter, dest)
        if status == "exceed":
            return "exceed"
        if is_summary:
            result["imported_summaries"] += 1
        else:
            result["imported_files"] += 1
        return "ok"
    except Exception as e:
        result["errors"].append(f"{target_path.name}: {str(e)}")
        return "error"


def _import_members(zf, workspace, memory_dir, summary_dir, result):
    """逐条导入 ZIP 成员；返回 ZIP Bomb 预检的硬错误文案，无硬错误返回 None。

    V4.0.2 抽为独立函数：import_memories 原本把预检、遍历、写入、中断
    全揉在一个函数里，圈复杂度 11。逻辑一字未改，只是换了个位置。
    """
    # ---- ZIP Bomb 防御：预检 ----
    _uncompressed, precheck_err, oversized = _import_validate_zip(zf, result)
    if precheck_err:
        return precheck_err
    oversized = set(oversized)

    counter = [0]  # 实际写入字节数追踪（ZIP Bomb 防御，跨成员累计）

    for member in zf.infolist():
        if member.filename in oversized:
            continue          # 超限条目：已在 errors 中留痕，绝不落盘
        target_path, is_summary, error = _import_safe_target(
            member.filename, workspace, memory_dir, summary_dir)
        if error:
            result["errors"].append(error)
            continue
        if target_path is None:
            continue

        status = _import_write_member(zf, member, target_path, is_summary, result, counter)
        if status == "exceed":
            return None
    return None


def import_memories(workspace_path, input_file):
    workspace = Path(workspace_path).resolve()
    memory_dir = workspace / ".workbuddy" / "memory"
    summary_dir = workspace / ".workbuddy" / ".summary"
    input_path = Path(input_file)

    if not input_path.exists():
        return {"error": _("import_file_not_exist")}

    error_note = _("import_failed") if _("import_failed") != "import_failed" else "Import failed"

    memory_dir.mkdir(parents=True, exist_ok=True)
    summary_dir.mkdir(parents=True, exist_ok=True)

    try:
        import zipfile

        result = {"imported_files": 0, "imported_summaries": 0, "errors": []}

        with zipfile.ZipFile(input_path, 'r') as zf:
            hard_error = _import_members(zf, workspace, memory_dir, summary_dir, result)

        if hard_error:
            return {**result, "error": hard_error}
        return result
    except ImportError:
        return {"error": error_note}


def _backup_load_manifest(manifest_file):
    """读取上次备份清单（不存在/损坏返回空）。"""
    if not manifest_file.exists():
        return {}
    try:
        return json.loads(manifest_file.read_text(encoding="utf-8")).get("files", {})
    except (json.JSONDecodeError, IOError, KeyError) as e:
        logger.warning("non-fatal: %s", e)
        return {}


def _backup_one_file(md_file, backup_path, memory_path, last_backup, incremental, dry_run, result):
    """备份单文件：dry_run 只计数，否则拷贝并计数。"""
    mtime, size_kb = get_file_info(md_file)
    if mtime is None:
        return
    rel = md_file.relative_to(memory_path)
    file_key = str(rel)
    current_hash = compute_content_hash(md_file)
    if incremental and file_key in last_backup and last_backup[file_key].get("hash") == current_hash:
        return
    is_new = file_key not in last_backup
    key = "files_copied" if is_new else "files_updated"
    if dry_run:
        result[key] += 1
        result["total_size_kb"] += size_kb
        return
    try:
        (backup_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(md_file, backup_path / rel)
        result[key] += 1
        result["total_size_kb"] += size_kb
    except (OSError, IOError, PermissionError) as e:
        logger.warning("non-fatal: %s", e)


def _backup_write_manifest(backup_path, memory_path):
    """写入备份清单（含哈希与体积）。"""
    manifest = {
        "last_backup": datetime.now().isoformat(),
        "files": {
            str(f.relative_to(memory_path)): {
                "hash": compute_content_hash(f),
                "size_kb": get_file_info(f)[1],
            }
            for f in memory_path.glob("*.md") if not is_symlink(f)
        },
    }
    (backup_path / ".backup_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _finalize_backup(backup_path):
    """给备份目录写完整性清单并收敛权限（POSIX）。

    先写清单再 chmod：清单自身也要落在收敛范围内，不能漏在 0600 之外。
    两步都只记告警 —— 备份内容已落盘，附加动作失败不该把整次备份判为失败。
    """
    try:
        files = write_sums(backup_path).get("files", 0)
    except (OSError, IOError) as e:
        logger.warning("non-fatal: %s", e)
        files = 0
    try:
        harden_tree(backup_path)
    except (OSError, IOError) as e:
        logger.warning("non-fatal: %s", e)
    return files


def backup_memory(workspace_path, backup_path=None, dry_run=True, incremental=True):
    config = load_config()
    bp_cfg = config.get("_backup_config", {})
    if backup_path is None:
        backup_path = bp_cfg.get("local_path", "")
    if not backup_path:
        return {"error": _("backup_config_missing")}
    backup_path = Path(backup_path).resolve()
    base_path = Path(workspace_path).resolve()
    memory_path = base_path / ".workbuddy" / "memory"
    result = {"backup_path": str(backup_path), "files_copied": 0, "files_updated": 0, "total_size_kb": 0}
    if not memory_path.exists():
        result["error"] = _("memory_dir_not_exist")
        return result
    if not dry_run:
        backup_path.mkdir(parents=True, exist_ok=True)

    manifest_file = backup_path / ".backup_manifest.json"
    last_backup = _backup_load_manifest(manifest_file)

    for md_file in memory_path.glob("*.md"):
        if is_symlink(md_file):
            continue
        _backup_one_file(md_file, backup_path, memory_path, last_backup, incremental, dry_run, result)

    if not dry_run:
        _backup_write_manifest(backup_path, memory_path)
        result["integrity_files"] = _finalize_backup(backup_path)
    return result


def _restore_pair(backup_path, memory_path, file_key):
    """把备份清单 key 解析为 (备份源文件, 还原目标)；越界/非法返回 (None, None)。

    清单是**不可信输入**（备份目录可能来自他人机器或被篡改），
    因此与 ZIP 导入采用同款边界校验：先拒穿越与绝对路径，再要求 `resolve()`
    后仍落在备份目录、以及记忆目录之内（同时防住符号链接逃逸）。
    """
    if _path_has_traversal(file_key) or _path_is_absolute(file_key):
        return None, None
    src = backup_path / file_key
    dst = memory_path / file_key
    try:
        src.resolve().relative_to(backup_path.resolve())
    except (ValueError, OSError):
        return None, None
    try:
        dst.resolve().relative_to(memory_path.resolve())
    except (ValueError, OSError):
        return None, None
    return src, dst


def _restore_one_file(backup_path, memory_path, file_key, meta, dry_run, result):
    """还原单个备份文件：边界校验 → 存在性 → 哈希完整性 →（真正）拷贝。"""
    # ① key 边界校验（清单可能被篡改，不能当成可信路径直接拼接）
    src, dst = _restore_pair(backup_path, memory_path, file_key)
    if src is None:
        result["errors"].append(_("restore_unsafe_key").format(name=file_key))
        return
    if not src.exists():
        return
    # ② 完整性校验：清单里记了 hash 就必须对得上
    #    V4.0.2 修复 —— 此前 manifest 存了每文件 hash 却从不读取，
    #    被破坏/被替换的备份会被静默还原（"假完整性"）。
    expected = meta.get("hash") if isinstance(meta, dict) else None
    if expected and compute_content_hash(src) != expected:
        result["skipped"].append(file_key)
        result["errors"].append(_("restore_hash_mismatch").format(name=file_key))
        return
    if dry_run:
        result["files_restored"] += 1
        return
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        result["files_restored"] += 1
    except (OSError, IOError, PermissionError) as e:
        logger.warning("non-fatal: %s", e)


def restore_backup(workspace_path, backup_path=None, dry_run=True):
    config = load_config()
    bp_cfg = config.get("_backup_config", {})
    if backup_path is None:
        backup_path = bp_cfg.get("local_path", "")
    if not backup_path:
        return {"error": _("backup_config_missing")}
    backup_path = Path(backup_path).resolve()
    manifest_file = backup_path / ".backup_manifest.json"
    if not manifest_file.exists():
        return {"error": _("backup_record_not_exist")}
    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError):
        return {"error": _("backup_record_corrupted")}
    result = {"files_restored": 0, "skipped": [], "errors": []}
    memory_path = Path(workspace_path).resolve() / ".workbuddy" / "memory"
    for file_key, meta in manifest.get("files", {}).items():
        _restore_one_file(backup_path, memory_path, file_key, meta, dry_run, result)
    return result


def verify_backup(backup_path=None):
    """校验备份目录的 SHA256SUMS（只读，不改任何文件）。

    清单缺失时返回 ok=False 而非「无从校验就放过」—— 沉默放行等于没有校验。
    """
    if backup_path is None:
        backup_path = load_config().get("_backup_config", {}).get("local_path", "")
    if not backup_path:
        return {"error": _("backup_config_missing")}
    return verify_sums(Path(backup_path).resolve())
