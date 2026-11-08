# -*- coding: utf-8 -*-
"""记忆管家 V4.0.3 - 敏感产物权限收敛与完整性清单。

只针对**本技能自己创建的产物**（备份目录 / 快照目录 / 导出包）做两件事：

1. **权限收敛**：POSIX 下目录 0700、文件 0600，避免同机其他用户读到记忆明文。
   Windows 的 `os.chmod` 只能切换只读位、没有 POSIX 权限位语义，因此明确返回
   `supported=False`，而不是「跑了一遍代码就当已经保护」。
2. **完整性清单（SHA256SUMS）**：逐文件**全量** SHA256，GNU coreutils 的
   `<hash>  <relpath>` 格式，可直接用 `sha256sum -c` 交叉验证。
   注意 `token.compute_content_hash` 只读前 50KB，拿它做清单会让「尾部改动」逃逸，
   故此处独立实现全量哈希。

**诚实边界**：校验和清单**不是签名**。能发现意外损坏（磁盘 / 同步冲突 / 复制中断）
与「只改文件不改清单」的篡改；若攻击者能同时改写文件与清单，清单无法阻止。
`references/security.md` 如实写明这一点，不做「已防篡改」的表述。
"""

import hashlib
import logging
import os
from pathlib import Path

from .config import _, load_config

logger = logging.getLogger(__name__)

SUMS_FILENAME = "SHA256SUMS"
DIR_MODE = 0o700
FILE_MODE = 0o600
_CHUNK = 65536


def perms_supported():
    """当前平台是否支持 POSIX 权限位（Windows 返回 False）。"""
    return os.name == "posix"


def hash_file(file_path):
    """整文件 sha256。读失败返回空串 —— 调用方须把空串当「无法校验」，而非「校验通过」。"""
    digest = hashlib.sha256()
    try:
        with open(file_path, "rb") as fh:
            for chunk in iter(lambda: fh.read(_CHUNK), b""):
                digest.update(chunk)
    except (OSError, IOError, PermissionError) as e:
        logger.warning("non-fatal: %s", e)
        return ""
    return digest.hexdigest()


def _chmod_all(paths, mode):
    """批量 chmod，逐条收集失败原因（一条失败不影响其余）。"""
    errors = []
    for p in paths:
        try:
            os.chmod(p, mode)
        except OSError as e:
            errors.append("%s: %s" % (p.name, e))
    return errors


def harden_file(file_path, mode=FILE_MODE):
    """把单个文件收敛为 0600。仅 POSIX 生效；返回是否真的改了权限位。"""
    if not perms_supported():
        return False
    try:
        os.chmod(file_path, mode)
    except OSError as e:
        logger.warning("non-fatal: %s", e)
        return False
    return True


def _split_tree(root):
    """把 root 及其子孙分成 (目录, 文件) 两组。

    符号链接一律跳过 —— 权限收敛不跟随链接，否则可能改到目录树之外的目标上。
    """
    dirs, files = [root], []
    for p in root.rglob("*"):
        if p.is_symlink():
            continue
        (dirs if p.is_dir() else files).append(p)
    return dirs, files


def harden_tree(root, dir_mode=DIR_MODE, file_mode=FILE_MODE):
    """把 root 及其子孙收敛为 目录 0700 / 文件 0600。返回统计（本函数不抛异常）。"""
    if not perms_supported():
        return {"supported": False, "dirs": 0, "files": 0, "errors": []}
    root = Path(root)
    if not root.exists():
        return {"supported": True, "dirs": 0, "files": 0, "errors": []}
    dirs, files = _split_tree(root)
    # 先文件后目录：若中途因权限不足中断，至少不会先把自己锁在目录外
    errors = _chmod_all(files, file_mode) + _chmod_all(dirs, dir_mode)
    return {"supported": True, "dirs": len(dirs), "files": len(files), "errors": errors}


def format_sums_line(digest, rel):
    """GNU coreutils 格式（两个空格分隔）——`sha256sum -c` 可直接消费。"""
    return "%s  %s" % (digest, rel)


def _parse_sums(text):
    """解析清单文本为 {相对路径: 哈希}；空行与畸形行忽略。"""
    entries = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("  ", 1)
        if len(parts) != 2 or not parts[1].strip():
            continue
        entries[parts[1].strip()] = parts[0].strip().lower()
    return entries


def write_sums(root):
    """在 root 下写 SHA256SUMS，覆盖其中全部普通文件（不含清单自身）。"""
    root = Path(root)
    lines = []
    for p in sorted(root.rglob("*")):
        if p.is_symlink() or not p.is_file() or p.name == SUMS_FILENAME:
            continue
        lines.append(format_sums_line(hash_file(p), p.relative_to(root).as_posix()))
    target = root / SUMS_FILENAME
    try:
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except (OSError, IOError, PermissionError) as e:
        logger.warning("non-fatal: %s", e)
        return {"ok": False, "files": 0, "error": str(e)}
    return {"ok": True, "files": len(lines), "path": str(target)}


def _collect_actual(root):
    """root 下实际存在的文件相对路径集合（排除清单自身与符号链接）。"""
    return {p.relative_to(root).as_posix() for p in root.rglob("*")
            if p.is_file() and not p.is_symlink() and p.name != SUMS_FILENAME}


def _diff_entries(root, expected):
    """逐条比对清单：返回 (哈希不符, 文件缺失)。"""
    mismatch, missing = [], []
    for rel, want in sorted(expected.items()):
        target = root / rel
        if not target.is_file():
            missing.append(rel)
        elif hash_file(target) != want:
            mismatch.append(rel)
    return mismatch, missing


def _empty_result(present, error):
    return {"ok": False, "present": present, "checked": 0,
            "mismatch": [], "missing": [], "extra": [], "error": error}


def verify_sums(root):
    """按 root/SHA256SUMS 校验目录内容。

    返回 {ok, present, checked, mismatch, missing, extra, error}。
    `ok` 要求「哈希全对 **且** 无缺失 **且** 无清单外新增文件」——
    只报不判会让「多出来的文件」永远没人看。
    """
    root = Path(root)
    sums_file = root / SUMS_FILENAME
    if not sums_file.exists():
        return _empty_result(False, _("sums_missing"))
    try:
        expected = _parse_sums(sums_file.read_text(encoding="utf-8"))
    except (OSError, IOError, UnicodeDecodeError) as e:
        return _empty_result(True, _("sums_broken").format(msg=e))
    if not expected:
        return _empty_result(True, _("sums_broken").format(msg="empty"))
    mismatch, missing = _diff_entries(root, expected)
    extra = sorted(_collect_actual(root) - set(expected))
    return {"ok": not (mismatch or missing or extra), "present": True,
            "checked": len(expected), "mismatch": mismatch, "missing": missing,
            "extra": extra, "error": None}


# ---------------------------------------------------------------- 工作区级入口

def _mode_of(path):
    """返回八进制权限串（如 '755'）；非 POSIX 或读取失败返回 '-'。"""
    if not perms_supported():
        return "-"
    try:
        return oct(path.stat().st_mode & 0o777)[2:]
    except OSError:
        return "-"


def _perm_targets(workspace_path):
    """需要收敛权限的目标：记忆目录 / 快照目录 / 配置里的备份目录。"""
    base = Path(workspace_path).resolve()
    targets = [base / ".workbuddy" / "memory", base / ".workbuddy" / "memory_snapshots"]
    backup_dir = load_config().get("_backup_config", {}).get("local_path", "")
    if backup_dir:
        targets.append(Path(backup_dir))
    return targets


def harden_workspace(workspace_path, execute=False):
    """收敛工作区内敏感目录权限（`harden` 子命令的底层实现）。

    execute=False 只列出目标与当前权限；execute=True 才真正 chmod。
    非 POSIX 平台返回 supported=False —— 报「不适用」好过假装已保护。
    """
    supported = perms_supported()
    targets = _perm_targets(workspace_path)
    rows = [{"path": str(t), "exists": t.exists(), "mode": _mode_of(t)} for t in targets]
    result = {"supported": supported, "executed": False, "targets": rows,
              "dirs": 0, "files": 0, "errors": []}
    if not (execute and supported):
        return result
    result["executed"] = True
    for t in targets:
        if not t.exists():
            continue
        stats = harden_tree(t)
        result["dirs"] += stats["dirs"]
        result["files"] += stats["files"]
        result["errors"] += stats["errors"]
    return result
