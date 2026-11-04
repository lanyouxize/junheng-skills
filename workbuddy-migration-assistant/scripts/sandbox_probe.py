"""Sandbox strip_write pre-probe (v1.2.1).

WorkBuddy's agent sandbox may "strip" writes to core config directories:
the write call appears to succeed but the file is never persisted (or is
filtered out). Importing into such a directory silently loses config.

This module probes each target directory BEFORE any real write by creating
a temporary sentinel file and reading it back. If the write was stripped,
we fail fast with error code E_PROBE_WRITE_DENIED and a Chinese fix hint.
Probe results are cached per-process so the R1 import path reuses them.

Design notes:
- Sentinel name is random to avoid clobbering; always cleaned up (best effort).
- Read-back check (not just write success) catches strip-write policies that
  only filter on read or content-scan.
- Cache keyed by resolved directory string; safe to call many times.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Dict, List, Optional

ERROR_CODE = "E_PROBE_WRITE_DENIED"
FIX_HINT = "请关闭沙箱后重跑，导入幂等可安全重复执行"

_cache: Dict[str, bool] = {}


def _probe_one(dir_path: Path) -> bool:
    """Return True if dir_path accepts + persists writes, False if stripped."""
    key = str(dir_path.resolve())
    if key in _cache:
        return _cache[key]
    try:
        dir_path.mkdir(parents=True, exist_ok=True)
    except OSError:
        _cache[key] = False
        return False
    sentinel = dir_path / f".wb-probe-{uuid.uuid4().hex[:12]}"
    ok = False
    try:
        sentinel.write_text("probe-ok", encoding="utf-8")
        ok = sentinel.read_text(encoding="utf-8") == "probe-ok"
    except OSError:
        ok = False
    finally:
        try:
            sentinel.unlink(missing_ok=True)
        except OSError:
            pass
    _cache[key] = ok
    return ok


def probe(dirs: List[Path]) -> Dict[str, bool]:
    """Probe all dirs. Returns {dir_str: writable_bool}."""
    return {str(d): _probe_one(d) for d in dirs}


def check(dirs: List[Path]) -> Optional[Dict[str, object]]:
    """Probe dirs; return None if all writable, else an error dict.

    Error dict: {"error_code", "denied_dirs", "hint"} — import should
    print it and exit non-zero WITHOUT performing any real write.
    """
    results = probe(dirs)
    denied = [d for d, ok in results.items() if not ok]
    if not denied:
        return None
    return {
        "error_code": ERROR_CODE,
        "denied_dirs": denied,
        "hint": FIX_HINT,
    }


def reset_cache() -> None:
    _cache.clear()
