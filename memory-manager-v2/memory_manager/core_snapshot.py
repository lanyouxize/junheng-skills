import logging
logger = logging.getLogger(__name__)

# -*- coding: utf-8 -*-
"""
记忆管家 V4.0.1 - 记忆快照与回滚（N3 可回滚底座）

任何「写入型」操作（govern / compact）在落盘前先建快照，
出错或反悔时可按快照名整批还原。快照存于
<workspace>/.workbuddy/memory_snapshots/<时间戳_标签>/，
文件后缀统一为 .snap —— 既不会被 iter_memory_files 当成记忆，
也不会被 clean 的可清理扩展名误伤。
"""

import shutil
from datetime import datetime
from pathlib import Path

from .config import _, iter_memory_files
from .core_perms import harden_tree, verify_sums, write_sums

SNAPSHOT_ROOT = ".workbuddy"
SNAPSHOT_DIRNAME = "memory_snapshots"
SNAPSHOT_SUFFIX = ".snap"
MAX_SNAPSHOTS = 5


def snapshot_dir(workspace_path):
    """快照根目录：<workspace>/.workbuddy/memory_snapshots/"""
    return Path(workspace_path).resolve() / SNAPSHOT_ROOT / SNAPSHOT_DIRNAME


def _memory_dir(workspace_path):
    return Path(workspace_path).resolve() / SNAPSHOT_ROOT / "memory"


def _safe_label(label):
    """标签只允许字母数字与 -_，避免成为路径穿越载体。"""
    keep = [c for c in str(label) if c.isalnum() or c in "-_"]
    return "".join(keep)[:24] or "manual"


def _snapshot_name(label):
    return f"{datetime.now().strftime('%Y%m%d-%H%M%S')}_{_safe_label(label)}"


def _copy_into(memory_path, target):
    n = 0
    size = 0
    for md_file, _mtime, _kb, rel in iter_memory_files(memory_path):
        dst = target / (rel + SNAPSHOT_SUFFIX)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(md_file, dst)
        n += 1
        size += dst.stat().st_size
    return n, size


def _prune(snap_root, keep):
    """只保留最近 keep 个快照，防止快照自身把磁盘撑大。"""
    if keep <= 0:
        return 0
    names = sorted(p.name for p in snap_root.iterdir() if p.is_dir())
    dropped = 0
    for name in names[:-keep]:
        shutil.rmtree(snap_root / name, ignore_errors=True)
        dropped += 1
    return dropped


def _finalize_snapshot(target):
    """给新快照写完整性清单并收敛权限（POSIX）。

    快照本身就是安全网，因此这两步失败只记告警、**不阻断**建快照主流程。
    """
    try:
        n = write_sums(target).get("files", 0)
        harden_tree(target)
    except (OSError, IOError) as e:
        logger.warning("non-fatal: %s", e)
        return 0
    return n


def snapshot_create(workspace_path, label="manual", keep=MAX_SNAPSHOTS):
    """把当前 memory/ 全量复制为一个快照，返回快照名与统计。"""
    memory_path = _memory_dir(workspace_path)
    if not memory_path.exists():
        return {"ok": False, "error": _("memory_dir_not_exist")}
    root = snapshot_dir(workspace_path)
    target = root / _snapshot_name(label)
    target.mkdir(parents=True, exist_ok=True)
    n, size = _copy_into(memory_path, target)
    return {
        "ok": True, "name": target.name, "path": str(target),
        "files": n, "bytes": size, "pruned": _prune(root, keep),
        "sums": _finalize_snapshot(target),
    }


def snapshot_before_write(workspace_path, label):
    """破坏性操作落盘前的统一快照入口（govern / compact / clean / cache-clean / dedup / archive 共用）。

    快照是「尽力而为」的安全网：失败时返回 None 并记告警，**不阻断**主操作 ——
    否则一次磁盘配额问题就能让清理功能彻底不可用（安全网不该变成路障）。
    """
    try:
        snap = snapshot_create(workspace_path, label=label)
    except Exception as e:                       # noqa: BLE001 - 快照不得阻断主流程
        logger.warning("non-fatal: %s", e)
        return None
    return snap.get("name") if snap.get("ok") else None


def _snap_stat(path):
    files = 0
    size = 0
    for snap in path.rglob("*" + SNAPSHOT_SUFFIX):
        if snap.is_file():
            files += 1
            size += snap.stat().st_size
    return {
        "name": path.name, "files": files, "bytes": size,
        "created": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
    }


def snapshot_list(workspace_path):
    """列出已有快照（按名称升序，最后一个即最新）。"""
    root = snapshot_dir(workspace_path)
    if not root.exists():
        return {"ok": True, "snapshots": [], "total": 0}
    items = [_snap_stat(p) for p in sorted(root.iterdir(), key=lambda x: x.name) if p.is_dir()]
    return {"ok": True, "snapshots": items, "total": len(items)}


def snapshot_restore(workspace_path, name=None):
    """按快照名还原；name 为空时还原最新一个。

    只覆盖快照中存在的同名文件，不删除快照之外的记忆 —— 避免「回滚变成误删」。
    """
    root = snapshot_dir(workspace_path)
    if not root.exists():
        return {"ok": False, "error": _("snap_none")}
    if not name:
        dirs = sorted(p for p in root.iterdir() if p.is_dir())
        if not dirs:
            return {"ok": False, "error": _("snap_none")}
        name = dirs[-1].name
    src = root / name
    if not src.is_dir():
        return {"ok": False, "error": _("snap_not_found").format(name=name)}
    memory_path = _memory_dir(workspace_path)
    memory_path.mkdir(parents=True, exist_ok=True)
    restored = 0
    for snap in src.rglob("*" + SNAPSHOT_SUFFIX):
        rel = snap.relative_to(src).as_posix()[: -len(SNAPSHOT_SUFFIX)]
        dst = memory_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(snap, dst)
        restored += 1
    return {"ok": True, "name": name, "restored": restored}


def snapshot_verify(workspace_path, name=None):
    """按快照的 SHA256SUMS 校验完整性（默认最新一个）。

    只读：不还原、不修改记忆目录。清单缺失/不符/多余文件都判不通过。
    """
    root = snapshot_dir(workspace_path)
    if not root.exists():
        return {"ok": False, "error": _("snap_none")}
    if not name:
        dirs = sorted(p for p in root.iterdir() if p.is_dir())
        if not dirs:
            return {"ok": False, "error": _("snap_none")}
        name = dirs[-1].name
    target = root / name
    if not target.is_dir():
        return {"ok": False, "error": _("snap_not_found").format(name=name)}
    res = verify_sums(target)
    res["name"] = name
    return res
