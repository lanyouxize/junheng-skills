"""Human-friendly error translation with stable error codes (v1.5.0).

v1.4.0: exceptions → 中文说明 + 下一步指引（技术细节附尾）。
v1.5.0: every message now starts with a STABLE error code (E-LOCK,
E-PERM, ...). Codes give users and host agents a stable handle for
lookup in `references/faq.md` (症状→原因→一条命令解法，按码索引).

Stable-code contract:
  - Codes are part of the user-facing contract: they may gain new
    hints, but a code's meaning never changes and codes are never
    renamed or recycled.
  - `ERROR_CODES` is the machine-readable registry (kept in sync with
    references/faq.md "按错误码速查" table).

Usage: top-level `except Exception as e: print(humanize(e))` in the three
entry scripts (export/import/info). Errors already translated inline by
callers (e.g. sandbox E-SANDBOX) are unaffected.
"""
from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path
from typing import Optional

_KNOWN_ISSUES_REF = "references/known-issues.md"
_FAQ_REF = "references/faq.md"

# Stable error-code registry (mirrored in references/faq.md 速查表).
ERROR_CODES: dict = {
    "E-LOCK": "WorkBuddy 数据库被占用（客户端未退出或自动化任务在跑）",
    "E-PERM": "目标路径没有写入权限",
    "E-NOTFOUND": "路径不存在（源目录/迁移包路径拼写或位置不对）",
    "E-BADPKG": "迁移包损坏或不是有效压缩包（传输中断/下载不完整）",
    "E-JSON": "配置文件不是有效 JSON（损坏或被编辑器改坏）",
    "E-DB": "数据库操作失败（锁以外的 DB 层错误）",
    "E-SANDBOX": "沙箱剥写拦截（WorkBuddy 沙箱拦截了核心配置写入）",
    "E-UNKNOWN": "未归类错误（用 --dry-run 预检，再按 known-issues 排查）",
}


def _first_path(e: Exception) -> Optional[str]:
    """Best-effort extraction of a path from exception args."""
    for a in e.args:
        if isinstance(a, str) and (":\\" in a or a.startswith("/") or "/" in a):
            # First arg that looks path-like
            token = a.split("\n")[0].strip("'\"")
            if len(token) < 300:
                return token
    if isinstance(e, OSError) and e.filename:
        return e.filename
    return None


def humanize(e: BaseException) -> str:
    """Translate an exception to '[E-CODE] 中文说明 + 下一步指引（技术细节）'."""
    detail = str(e)
    path = _first_path(e)
    tech = f"  技术细节：{detail}"

    # --- sqlite lock: most common "database is locked" ---
    if isinstance(e, sqlite3.OperationalError) and "locked" in detail.lower():
        return (
            "[E-LOCK] 数据库被占用，无法写入。\n"
            "  下一步：请完全退出 WorkBuddy 客户端（包括系统托盘里的图标），\n"
            "  确认没有正在运行的自动化任务，然后重跑导入（幂等可安全重试）。\n"
            f"  更多：按错误码查 `{_FAQ_REF}`「按错误码速查」表。\n"
            f"{tech}"
        )

    # --- permission ---
    if isinstance(e, PermissionError):
        p = path or "目标路径"
        return (
            f"[E-PERM] 没有写入权限：{p}\n"
            "  下一步：① 关闭 WorkBuddy 客户端后重试；② Windows 下可尝试以\n"
            "  管理员身份运行终端；③ 确认目标目录未被杀毒软件锁定。\n"
            f"  更多：按错误码查 `{_FAQ_REF}`「按错误码速查」表。\n"
            f"{tech}"
        )

    # --- missing file/dir ---
    if isinstance(e, FileNotFoundError):
        p = path or "指定路径"
        return (
            f"[E-NOTFOUND] 路径不存在：{p}\n"
            "  下一步：请检查路径拼写；导出源可用 `--source auto` 自动探测，\n"
            "  或先用 `scripts/info.py` 确认迁移包内容。\n"
            f"  更多：按错误码查 `{_FAQ_REF}`「按错误码速查」表。\n"
            f"{tech}"
        )

    # --- corrupt package ---
    if isinstance(e, (zipfile.BadZipFile, zipfile.LargeZipFile)):
        p = path or "迁移包"
        return (
            f"[E-BADPKG] 迁移包无法读取（损坏或不是有效 zip）：{p}\n"
            "  下一步：请重新执行导出生成新包；传输中断可能导致包不完整，\n"
            "  建议对比源端与目标端的文件大小。\n"
            f"  更多：按错误码查 `{_FAQ_REF}`「按错误码速查」表。\n"
            f"{tech}"
        )

    # --- broken manifest ---
    if isinstance(e, json.JSONDecodeError):
        return (
            "[E-JSON] 配置文件内容不是有效的 JSON，可能已损坏。\n"
            "  下一步：若是迁移包内 manifest 损坏请重新导出；若是目标端配置\n"
            "  损坏，可从 `<name>.bak-<时间戳>` 备份恢复。\n"
            f"  更多：按错误码查 `{_FAQ_REF}`「按错误码速查」表。\n"
            f"{tech}"
        )

    # --- sqlite generic ---
    if isinstance(e, sqlite3.Error):
        return (
            "[E-DB] 数据库操作失败。\n"
            "  下一步：先完全退出 WorkBuddy 客户端重跑；若反复出现，请查阅\n"
            f"  `{_KNOWN_ISSUES_REF}` 的「DB 索引损坏」一节，或带 --dry-run 预检。\n"
            f"  更多：按错误码查 `{_FAQ_REF}`「按错误码速查」表。\n"
            f"{tech}"
        )

    # --- generic fallback ---
    return (
        f"[E-UNKNOWN] {detail}\n"
        "  下一步：先用 --dry-run 预检排除常见问题；若反复出现请查阅\n"
        f"  `{_KNOWN_ISSUES_REF}`。\n"
        f"  更多：按错误码查 `{_FAQ_REF}`「按错误码速查」表。\n"
        f"  技术细节：{type(e).__name__}"
    )
