"""Field-subtree extraction and deep-merge engine (v1.2.1).

Handles the `field-subtree` asset mode declared in asset_inventory.md for
`app/app-config.json`:

- Export side: read the source JSON, extract ONLY the `extract_fields`
  subtree (dotted paths, e.g. "personalization.customPrompt"), and
  explicitly drop `exclude_fields` (e.g. "sandboxSafetyEnabled" — a
  per-machine runtime switch that must NOT migrate).
- Import side: deep-merge the extracted subtree into the target JSON —
  per-key target-wins inside the subtree (unless --overwrite), and do not
  touch any fields outside the subtree.

Whitelist (extract_fields) + blacklist (exclude_fields) double gate
prevents over-migration of machine-local state.

on_missing / on_invalid policy values come from the inventory entry:
  on_missing: "skip" (default) — source file absent → skip silently
  on_invalid: "warn-skip" — source JSON broken → warn and skip
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


def _dig(node: Any, dotted: str) -> Optional[Any]:
    """Walk a dotted path ('personalization.customPrompt') into a JSON tree."""
    cur = node
    for seg in dotted.split("."):
        if not isinstance(cur, dict) or seg not in cur:
            return None
        cur = cur[seg]
    return cur


def _set_path(node: Dict[str, Any], dotted: str, value: Any) -> None:
    """Create nested dicts as needed and set the dotted path."""
    parts = dotted.split(".")
    cur = node
    for seg in parts[:-1]:
        cur = cur.setdefault(seg, {})
    cur[parts[-1]] = value


def extract_subtree(data: Any, extract_fields: List[str],
                    exclude_fields: Optional[List[str]] = None) -> Dict[str, Any]:
    """Build a shallow-ish copy containing only the requested dotted paths.

    Non-dict source → returns {} (callers decide policy via on_invalid).
    """
    out: Dict[str, Any] = {}
    if not isinstance(data, dict):
        return out
    for dotted in extract_fields or []:
        v = _dig(data, dotted)
        if v is not None:
            _set_path(out, dotted, v)
    # Blacklist pass: remove any excluded field that happens to be inside
    # a whitelisted branch (defense in depth).
    for dotted in exclude_fields or []:
        parts = dotted.split(".")
        cur = out
        for seg in parts[:-1]:
            if not isinstance(cur, dict):
                cur = None
                break
            cur = cur.get(seg)
        if isinstance(cur, dict):
            cur.pop(parts[-1], None)
    return out


def merge_deep(target: Dict[str, Any], patch: Dict[str, Any],
               overwrite: bool) -> Dict[str, List[str]]:
    """Deep-merge patch into target. Per-leaf: target wins unless overwrite.

    Returns {"added": [...], "replaced": [...], "skipped": [...]} of dotted
    paths, so import reports are machine-checkable.
    """
    added: List[str] = []
    replaced: List[str] = []
    skipped: List[str] = []

    def walk(t_node: Dict[str, Any], p_node: Dict[str, Any], prefix: str) -> None:
        for k, pv in p_node.items():
            sub = (prefix + "." + k) if prefix else k
            if isinstance(pv, dict):
                if not isinstance(t_node.get(k), dict):
                    t_node[k] = {}
                walk(t_node[k], pv, sub)
            else:
                # leaf
                if k in t_node and not overwrite:
                    skipped.append(sub)
                else:
                    existed = k in t_node
                    t_node[k] = pv
                    (replaced if existed else added).append(sub)

    walk(target, patch, "")
    return {"added": added, "replaced": replaced, "skipped": skipped}


def extract_from_file(src: Path, asset: Dict[str, Any]) -> Dict[str, Any]:
    """Read src JSON and return the extracted subtree + policy action.

    Returns {"action": "extracted"|"skip"|"warn-skip", "data": {...}|None,
             "reason": str|None}.
    """
    if not src.is_file():
        return {"action": "skip", "data": None, "reason": "src absent"}
    try:
        raw = json.loads(src.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        return {"action": "warn-skip", "data": None, "reason": f"invalid json: {e}"}
    sub = extract_subtree(
        raw,
        asset.get("extract_fields", []),
        asset.get("exclude_fields", []),
    )
    return {"action": "extracted", "data": sub, "reason": None}


def merge_field_subtree(src: Path, dst: Path, asset: Dict[str, Any],
                        *, overwrite: bool) -> Dict[str, Any]:
    """Import-side merge for field-subtree assets. Returns report dict."""
    if not src.is_file():
        return {"action": "skipped", "reason": "src absent"}

    try:
        src_data = json.loads(src.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        return {"action": "skipped", "reason": f"invalid src json: {e}"}

    if not isinstance(src_data, dict):
        return {"action": "skipped", "reason": "src not dict"}

    patch = extract_subtree(
        src_data,
        asset.get("extract_fields", []),
        asset.get("exclude_fields", []),
    )

    if dst.is_file():
        try:
            target_data = json.loads(dst.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            target_data = {}
        if not isinstance(target_data, dict):
            target_data = {}
    else:
        target_data = {}

    stats = merge_deep(target_data, patch, overwrite)

    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(target_data, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    return {
        "action": "merged",
        "extract_fields": asset.get("extract_fields", []),
        "exclude_fields": asset.get("exclude_fields", []),
        **stats,
    }
