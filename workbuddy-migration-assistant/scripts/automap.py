"""Automatic cross-platform path and user_id mapping for WorkBuddy migration.

Inspired by wb-migrate v2.0.3's --auto-map feature.

Reads source metadata (OS, username, home) from the migration package manifest,
detects the target platform, and automatically derives path-map rules.
Applies them to DB columns, JSON fields, and project directory names.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, unquote

from . import pathmap as PM


# --- Platform detection --------------------------------------------------------

OS_HOME_PATTERNS = {
    "Darwin":  "/Users/{username}",
    "Windows": "{drive}:\\Users\\{username}",
    "Linux":   "/home/{username}",
}


def get_target_info() -> Dict[str, str]:
    """Gather target machine platform info."""
    return {
        "os": platform.system(),
        "os_release": platform.release(),
        "username": os.environ.get("USER") or os.environ.get("USERNAME") or "unknown",
        "hostname": platform.node(),
        "home": str(Path.home()),
    }


def infer_source_home(manifest: dict) -> Optional[str]:
    """Derive the source machine's home directory from manifest metadata."""
    src_os = manifest.get("source_os", "")
    src_user = manifest.get("source_username", "")
    src_home = manifest.get("source_home", "")
    src_root = manifest.get("source_root", "")

    if src_home:
        return src_home

    # Fallback: reconstruct from source_root (typically ~/.workbuddy)
    if src_root:
        if src_root.endswith("/.workbuddy"):
            return src_root[:-len("/.workbuddy")]
        if src_root.endswith("\\.workbuddy"):
            return src_root[:-len("\\.workbuddy")]

    # Last fallback: use OS patterns
    if src_os == "Darwin":
        return f"/Users/{src_user}" if src_user else None
    elif src_os == "Windows":
        return f"C:\\Users\\{src_user}" if src_user else None
    elif src_os == "Linux":
        return f"/home/{src_user}" if src_user else None

    return None


def needs_remapping(manifest: dict) -> bool:
    """Check whether cross-platform or different-user mapping is needed."""
    src_os = manifest.get("source_os", "")
    target = get_target_info()
    # Different OS → definitely needs remapping
    if src_os and src_os != target["os"]:
        return True
    # Same OS but different home path → user might have changed
    src_home = infer_source_home(manifest)
    if src_home and Path(src_home) != Path(target["home"]):
        return True
    return False


def generate_rules(manifest: dict) -> Dict[str, str]:
    """Auto-generate path-map rules from manifest metadata.

    Returns dict of {source_prefix: target_prefix} for PathMapper.
    """
    src_home = infer_source_home(manifest)
    target = get_target_info()
    rules: Dict[str, str] = {}

    if not src_home:
        return rules

    target_home = target["home"]
    src_os = manifest.get("source_os", "")

    # Primary rule: source_home → target_home
    if src_home != target_home:
        rules[src_home] = target_home

    # Additional: if usernames differ, add username-only remapping
    src_user = manifest.get("source_username", "")
    tgt_user = target.get("username", "")
    if src_user and tgt_user and src_user != tgt_user:
        if src_os == "Darwin" or src_os == "Linux":
            rules[f"/Users/{src_user}"] = target_home
            rules[f"/home/{src_user}"] = target_home
        elif src_os == "Windows":
            rules[f"C:\\Users\\{src_user}"] = target_home

    return rules


# --- User ID auto-mapping -------------------------------------------------------

@dataclass
class UIDMapping:
    source_uids: List[str] = field(default_factory=list)
    target_uid: str = ""
    mapping: Dict[str, str] = field(default_factory=dict)


def detect_source_uids(db_path: Path) -> List[str]:
    """Extract all distinct user_ids from a migration DB."""
    import sqlite3
    if not db_path.is_file():
        return []
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        rows = conn.execute(
            "SELECT DISTINCT user_id FROM sessions WHERE user_id IS NOT NULL AND user_id != ''"
        ).fetchall()
        conn.close()
        return [r[0] for r in rows]
    except sqlite3.Error:
        return []


def detect_target_uid(db_path: Path) -> Optional[str]:
    """Detect target machine's current user_id from DB."""
    import sqlite3
    if not db_path.is_file():
        return None
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        row = conn.execute(
            "SELECT user_id FROM sessions WHERE user_id IS NOT NULL AND user_id != '' "
            "ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
        conn.close()
        return row[0] if row else None
    except sqlite3.Error:
        return None


def generate_uid_map(source_uids: List[str], target_uid: str) -> Dict[str, str]:
    """Map all source user_ids to target_uid."""
    if not target_uid or not source_uids:
        return {}
    return {uid: target_uid for uid in source_uids}


# --- Apply auto-mapping ---------------------------------------------------------

@dataclass
class AutoMapPlan:
    needs_remap: bool
    source_os: str
    target_os: str
    source_home: str
    target_home: str
    path_rules: Dict[str, str]
    uid_map: Dict[str, str]
    notes: List[str] = field(default_factory=list)


def plan(manifest: dict, target_db_path: Optional[Path] = None) -> AutoMapPlan:
    """Generate an auto-mapping plan without applying anything.

    Returns AutoMapPlan with all detected rules and mapping suggestions.
    """
    src_os = manifest.get("source_os", "unknown")
    target = get_target_info()
    tgt_os = target["os"]
    src_home = infer_source_home(manifest) or "unknown"
    tgt_home = target["home"]
    path_rules = generate_rules(manifest)

    # UID detection
    uid_map: Dict[str, str] = {}
    src_uids = manifest.get("user_ids", [])
    tgt_uid = None
    if target_db_path:
        tgt_uid = detect_target_uid(target_db_path)
    if src_uids and tgt_uid:
        uid_map = generate_uid_map(src_uids, tgt_uid)

    plan_obj = AutoMapPlan(
        needs_remap=needs_remapping(manifest),
        source_os=src_os,
        target_os=tgt_os,
        source_home=src_home,
        target_home=tgt_home,
        path_rules=path_rules,
        uid_map=uid_map,
    )

    if not plan_obj.needs_remap:
        plan_obj.notes.append("Same platform and home directory, no remapping needed.")
    if path_rules:
        plan_obj.notes.append(
            f"Auto-detected {len(path_rules)} path mapping rule(s)."
        )
    if uid_map:
        plan_obj.notes.append(
            f"Mapping {len(uid_map)} source uid(s) → target uid {tgt_uid}."
        )
    if not uid_map and src_uids:
        plan_obj.notes.append(
            "Target user_id not found. Use --target-user-id to specify."
        )

    return plan_obj


def apply_path_remapping(
    db_path: Path,
    path_rules: Dict[str, str],
    src_os: str = "unknown",
    dst_os: str = "",
) -> int:
    """Apply path remapping to target DB in-place.

    Returns count of rows remapped.
    """
    import sqlite3

    if not path_rules:
        return 0

    mapper = PM.PathMapper(
        rules=[(src, dst) for src, dst in path_rules.items()],
        src_os=src_os,
        dst_os=dst_os or platform.system().lower(),
    ) if hasattr(PM, 'PathMapper') else None

    if not mapper:
        return 0

    total = 0
    conn = sqlite3.connect(str(db_path))

    # sessions.cwd
    for row in conn.execute("SELECT id, cwd FROM sessions WHERE cwd IS NOT NULL").fetchall():
        result = mapper.rewrite(row[1])
        if result and result.new_path != row[1]:
            conn.execute("UPDATE sessions SET cwd = ? WHERE id = ?", (result.new_path, row[0]))
            total += 1

    # workspaces.path
    for row in conn.execute("SELECT path FROM workspaces").fetchall():
        result = mapper.rewrite(row[0])
        if result and result.new_path != row[0]:
            conn.execute("UPDATE workspaces SET path = ? WHERE path = ?", (result.new_path, row[0]))
            total += 1

    # automations.cwds (JSON array)
    for row in conn.execute("SELECT id, cwds FROM automations WHERE cwds IS NOT NULL").fetchall():
        try:
            cwds = json.loads(row[1])
            if isinstance(cwds, list):
                new_cwds = []
                changed = False
                for c in cwds:
                    r = mapper.rewrite(c) if isinstance(c, str) else None
                    if r and r.new_path != c:
                        new_cwds.append(r.new_path)
                        changed = True
                    else:
                        new_cwds.append(c)
                if changed:
                    conn.execute("UPDATE automations SET cwds = ? WHERE id = ?",
                                 (json.dumps(new_cwds), row[0]))
                    total += 1
        except (json.JSONDecodeError, TypeError):
            pass

    # automation_runs.source_cwd
    for row in conn.execute("SELECT id, source_cwd FROM automation_runs WHERE source_cwd IS NOT NULL").fetchall():
        result = mapper.rewrite(row[1])
        if result and result.new_path != row[1]:
            conn.execute("UPDATE automation_runs SET source_cwd = ? WHERE id = ?",
                         (result.new_path, row[0]))
            total += 1

    conn.commit()
    conn.close()
    return total


def apply_uid_remapping(
    db_path: Path,
    uid_map: Dict[str, str],
    projects_dir: Optional[Path] = None,
    memory_dir: Optional[Path] = None,
    connectors_dir: Optional[Path] = None,
) -> Dict[str, int]:
    """Rewrite user_id in DB and rename associated files/dirs.

    Returns counts: {db_sessions, memory_files, connectors_dirs, projects}
    """
    import sqlite3

    counts = {"db_sessions": 0, "memory_files": 0, "connectors_dirs": 0, "projects": 0}
    if not uid_map:
        return counts

    # DB: update sessions.user_id
    conn = sqlite3.connect(str(db_path))
    for src_uid, dst_uid in uid_map.items():
        c = conn.execute(
            "UPDATE sessions SET user_id = ? WHERE user_id = ?",
            (dst_uid, src_uid),
        ).rowcount
        counts["db_sessions"] += c
    conn.commit()
    conn.close()

    # Rename memory files
    if memory_dir and memory_dir.is_dir():
        for src_uid, dst_uid in uid_map.items():
            src_file = memory_dir / f"{src_uid}_memory.md"
            dst_file = memory_dir / f"{dst_uid}_memory.md"
            if src_file.exists() and not dst_file.exists():
                shutil.move(str(src_file), str(dst_file))
                counts["memory_files"] += 1

    # Rename connectors subdirs
    if connectors_dir and connectors_dir.is_dir():
        for src_uid, dst_uid in uid_map.items():
            src_sub = connectors_dir / src_uid
            dst_sub = connectors_dir / dst_uid
            if src_sub.is_dir() and not dst_sub.is_dir():
                shutil.move(str(src_sub), str(dst_sub))
                counts["connectors_dirs"] += 1

    return counts


# --- v1.2.1 (R5): memory-path token rewriting -------------------------------

def rewrite_memory_path_tokens(
    files: List[Path],
    mapper,
    old_uid: Optional[str] = None,
    new_uid: Optional[str] = None,
) -> Dict[str, Any]:
    """Rewrite absolute-path tokens inside memory files (MEMORY.md and
    memory/{uid}_memory.md).

    v1.2.1 R5: memory files may embed absolute workspace paths (e.g.
    `C:\\Users\\old\\projects\\x`). On cross-machine migration these must be
    rewritten. Rules (no hand-rolled regex):
      - ONLY tokens the PathMapper actually matches (mapper.rewrite()) are
        replaced — avoids false positives on non-path strings.
      - old_uid/new_uid only come from the manifest / uid_map, never from
        user free-text.
    Returns {"rewritten_files": int, "tokens_replaced": int, "files": [...]}.
    """
    import re as _re

    # Path-like token pattern: drive path, POSIX path, or home anchor.
    # Matched tokens are then validated through mapper.rewrite() — only
    # tokens the mapper recognizes get replaced.
    token_pat = _re.compile(
        r"(?<![A-Za-z0-9])(?:[A-Za-z]:[\\/][^\s\"',;)]+|"
        r"/(?:[A-Za-z0-9._-]+/)+[A-Za-z0-9._-]+)"
    )

    rewritten_files = 0
    tokens_replaced = 0
    touched = []
    for fp in files:
        if not fp.is_file():
            continue
        try:
            text = fp.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        changed = False
        new_text = text

        def _replace(match: _re.Match) -> str:
            nonlocal tokens_replaced, changed
            tok = match.group(0)
            # uid token rewrite first (deterministic, manifest-derived)
            if old_uid and new_uid and old_uid in tok:
                tok2 = tok.replace(old_uid, new_uid)
                if tok2 != tok:
                    tokens_replaced += 1
                    changed = True
                    tok = tok2
            # path token rewrite via PathMapper only
            r = mapper.rewrite(tok)
            if r and r.matched and r.new_path != tok:
                tokens_replaced += 1
                changed = True
                return r.new_path
            return tok

        new_text = token_pat.sub(_replace, new_text)
        if changed:
            fp.write_text(new_text, encoding="utf-8")
            rewritten_files += 1
            touched.append(str(fp))
    return {
        "rewritten_files": rewritten_files,
        "tokens_replaced": tokens_replaced,
        "files": touched,
    }


# --- v1.6.0: artifact-index path rewriting ----------------------------------

_SCHEME_RE = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.\-]*://)(.*)$", re.DOTALL)
# Keys whose values carry a filesystem location inside artifact-index records.
_URI_KEYS = {"uri", "path", "filePath", "cwd", "workspacePath", "absolutePath"}


def _rewrite_uri(value: str, mapper, old_uid: Optional[str],
                 new_uid: Optional[str]) -> str:
    """Rewrite one artifact URI / path string.

    Handles both URL-encoded absolute paths (artifact-index style:
    `file-changes://D%3A%5CUsers%5Calice%5Creport.md`) and plain paths.
    Only rewrites when the PathMapper actually matches the rule set, so
    unrelated strings are never touched.
    """
    if not isinstance(value, str) or not value:
        return value

    m = _SCHEME_RE.match(value)
    if m:
        scheme, rest = m.group(1), m.group(2)
        path = unquote(rest)
        r = mapper.rewrite(path)
        if r and r.matched and r.new_path != path:
            return scheme + quote(r.new_path, safe="/")
        return value

    r = mapper.rewrite(value)
    if r and r.matched and r.new_path != value:
        return r.new_path
    # uid token rewrite only for manifest-derived uids, never free text
    if old_uid and new_uid and old_uid in value:
        return value.replace(old_uid, new_uid)
    return value


def rewrite_artifact_index(
    dir_path: Path,
    mapper,
    old_uid: Optional[str] = None,
    new_uid: Optional[str] = None,
) -> Dict[str, Any]:
    """v1.6.0: rewrite absolute paths inside `artifact-index/*.json`.

    artifact-index stores, per session, the artifacts (deliverables) produced
    during that conversation — 5.4.4/5.4.5 reworked the artifact area and
    pinned "keep final deliverables / hide intermediates" into this index.
    Losing it means restored conversations show an empty artifact list and
    the official "early artifacts lost" fix regresses.

    Paths appear as URL-encoded absolute paths under `uri` / `fileChangeInfo.uri`,
    e.g. `file-changes://D%3A%5CUsers%5Calice%5Cproj%5Creport.md`. Cross-machine
    these must be remapped or the artifact list points at dead paths.

    Algorithm (no hand-rolled path parsing):
      1. split `<scheme>://<encoded-path>`;
      2. urllib.parse.unquote → real path;
      3. mapper.rewrite(path) — only matched paths are rewritten;
      4. urllib.parse.quote(path, safe="/") → re-encode, keep scheme.

    Returns {"files_seen": int, "rewritten_files": int, "uris_rewritten": int}.
    """
    if not dir_path or not dir_path.is_dir():
        return {"files_seen": 0, "rewritten_files": 0, "uris_rewritten": 0}

    files_seen = 0
    rewritten_files = 0
    uris_rewritten = 0

    def _rw(value: str) -> str:
        """Rewrite one value and count it only when it actually changed."""
        nonlocal uris_rewritten
        new = _rewrite_uri(value, mapper, old_uid, new_uid)
        if new != value:
            uris_rewritten += 1
        return new

    def _walk(node: Any) -> Any:
        """Recursively rewrite *_URI_KEYS values inside dicts/lists."""
        if isinstance(node, dict):
            return {
                k: (_rw(v) if k in _URI_KEYS and isinstance(v, str) else _walk(v))
                for k, v in node.items()
            }
        if isinstance(node, list):
            return [_walk(x) for x in node]
        return node

    for fp in sorted(dir_path.glob("*.json")):
        if not fp.is_file():
            continue
        files_seen += 1
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue  # corrupt index entry — leave untouched, never lose data

        before = json.dumps(data, ensure_ascii=False, sort_keys=True)
        new_data = _walk(data)
        after = json.dumps(new_data, ensure_ascii=False, sort_keys=True)
        if after == before:
            continue

        fp.write_text(
            json.dumps(new_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        rewritten_files += 1

    return {
        "files_seen": files_seen,
        "rewritten_files": rewritten_files,
        "uris_rewritten": uris_rewritten,
    }
