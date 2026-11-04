#!/usr/bin/env python3
"""Import a WorkBuddy migration package into a target root, merging without clobbering."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from scripts import detect, manifest as M, db as DB, fs, configs, report as R, automap, validate
from scripts import field_extract as FE, sandbox_probe as SP, trace as TRACE
from scripts.pathmap import PathMapper


def _parse_uid_map(args_list: Optional[List[str]]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for s in args_list or []:
        if "=" not in s:
            raise ValueError(f"Bad --uid-map value: {s} (expected src=dst)")
        a, b = s.split("=", 1)
        a, b = a.strip(), b.strip()
        if not a or not b:
            raise ValueError(f"Bad --uid-map value: {s}")
        out[a] = b
    return out


def _parse_path_map(args_list: Optional[List[str]]) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    for s in args_list or []:
        if "=" not in s:
            raise ValueError(f"Bad --path-map value: {s} (expected src=dst)")
        a, b = s.split("=", 1)
        a, b = a.strip(), b.strip()
        if not a or not b:
            raise ValueError(f"Bad --path-map value: {s}")
        out.append((a, b))
    return out


def _unpack_to_temp(pkg: Path, td: Path) -> Path:
    """Return path to package root (containing manifest.json)."""
    if pkg.is_dir():
        return pkg
    if pkg.is_file() and pkg.suffix.lower() == ".zip":
        extract_to = td / "unpacked"
        extract_to.mkdir()
        with zipfile.ZipFile(pkg) as zf:
            names = zf.namelist()
            for i, n in enumerate(names, 1):
                zf.extract(n, extract_to)
                R.progress(i, len(names), "解压")
        return extract_to
    if pkg.is_file() and pkg.name.lower().endswith(".tar.gz"):
        import tarfile as _tar
        extract_to = td / "unpacked"
        extract_to.mkdir()
        with _tar.open(pkg, "r:gz") as tf:
            tf.extractall(extract_to)
        return extract_to
    raise ValueError(f"Unsupported package: {pkg}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Import a WorkBuddy migration package.")
    ap.add_argument("--package", required=True, help="zip or directory")
    ap.add_argument("--target", default="auto", help="Target root or 'auto'")
    ap.add_argument("--overwrite", action="store_true", help="Replace conflicts (auto backup)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--profile", default=None, choices=["auto"],
        help="One-flag preset (v1.5.0): auto = --auto-map + --no-credentials "
             "(the recommended cross-machine import). Explicit flags always win.",
    )
    ap.add_argument(
        "--uid-map", action="append", default=None, help="src=dst (may repeat)"
    )
    ap.add_argument("--no-credentials", action="store_true")
    ap.add_argument("--no-conversations", action="store_true")
    ap.add_argument("--skip-db", action="store_true")
    ap.add_argument("--skip-skills", action="store_true")
    ap.add_argument("--skip-configs", action="store_true")

    # Auto-map (v0.2.0)
    ap.add_argument(
        "--auto-map", action="store_true",
        help="Automatically detect and apply cross-platform path and user_id mapping "
             "from package manifest metadata. Equivalent to auto-generating "
             "--path-map and --uid-map from source/target platform info.",
    )
    ap.add_argument(
        "--target-user-id", default=None,
        help="Explicit target user_id for --auto-map when target DB is empty.",
    )
    ap.add_argument(
        "--no-validate", action="store_true",
        help="Skip post-restore data integrity validation.",
    )

    # Cross-machine
    ap.add_argument(
        "--path-map", action="append", default=None,
        help="Path prefix mapping src=dst. May repeat. Required when source machine "
             "(per manifest) and target machine layouts differ. Longest prefix wins.",
    )
    ap.add_argument(
        "--target-os", default=None,
        help="Target OS for path normalization (darwin|win32|linux). "
             "Default: current OS (sys.platform).",
    )
    ap.add_argument(
        "--workspaces-package", default=None,
        help="Path to <main>-workspaces.zip. If provided, workspace files are extracted.",
    )
    ap.add_argument(
        "--workspace-destination", default=None,
        help="Root dir for extracted workspaces when path-map can't resolve. "
             "Default: ~/wb-imported-workspaces/",
    )

    ap.add_argument(
        "--inventory",
        default=str(_HERE.parent / "references" / "asset_inventory.md"),
        help="Path to asset_inventory.md",
    )
    args = ap.parse_args()

    # v1.5.0: apply profile presets (additive; explicit flags are never unset).
    if args.profile == "auto":
        args.auto_map = True
        args.no_credentials = True


    # Fix encoding on Windows: default GBK codec corrupts non-ASCII output
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    rep = R.Report(mode="import", dry_run=args.dry_run, overwrite=args.overwrite)
    rep.start()
    inventory = M.load_inventory(Path(args.inventory))
    uid_map = _parse_uid_map(args.uid_map)
    path_map_rules = _parse_path_map(args.path_map)

    with tempfile.TemporaryDirectory(prefix="wb-import-") as td:
        pkg_root = _unpack_to_temp(Path(args.package).expanduser(), Path(td))
        manifest_path = pkg_root / "manifest.json"
        if not manifest_path.is_file():
            print(f"[error] manifest.json not found in package", file=sys.stderr)
            return 1
        meta = M.Manifest.load(manifest_path)
        try:
            meta.validate_for_import()
        except ValueError as e:
            print(f"[error] {e}", file=sys.stderr)
            return 1

        # Resolve target
        try:
            target = detect.resolve_root(args.target, must_exist=False, interactive=True)
        except FileNotFoundError as e:
            print(f"[error] {e}", file=sys.stderr)
            return 1
        rep.source = str(pkg_root)
        rep.target = str(target.path)
        target.path.mkdir(parents=True, exist_ok=True)

        # ---- R2 (v1.2.1): sandbox strip_write pre-probe ----
        # WorkBuddy agent sandbox may strip writes to core config dirs. Probe
        # BEFORE any real write; fail fast with E_PROBE_WRITE_DENIED.
        # Probe result is cached per-process and reused by the R1 import path.
        if not args.dry_run:
            probe_err = SP.check([target.path])
            if probe_err:
                # v1.5.0: display as stable code E-SANDBOX (internal code
                # E_PROBE_WRITE_DENIED is kept for backward compatibility).
                print(
                    f"[error] [E-SANDBOX] "
                    f"沙箱剥写拦截：{', '.join(probe_err['denied_dirs'])}",
                    file=sys.stderr,
                )
                print(f"  下一步：{probe_err['hint']}", file=sys.stderr)
                print(
                    "  更多：按错误码查 references/faq.md「按错误码速查」表。",
                    file=sys.stderr,
                )
                TRACE.add("probe", dirs=probe_err["denied_dirs"], denied=True)
                return 1
            TRACE.add("probe", dirs=[str(target.path)], denied=False)

        # ---- UID resolution ----
        # CN and Intl editions use different account systems, so user_id mismatch
        # is expected and normal. We must map every source uid to a target uid so
        # the imported data is visible to the currently logged-in account on the
        # target side.  If we cannot determine the target uid, the imported rows
        # would keep the source uid (via the ELSE branch in DB.merge_table's CASE
        # expression) and be invisible — block and ask the user to resolve.
        target_uids = detect.extract_user_ids(target.path / "workbuddy.db")
        target_primary = target_uids[0][0] if target_uids else None
        source_uids_all = meta.source_user_ids_all or (
            [meta.source_user_id] if meta.source_user_id else []
        )

        # First, check if user-provided --uid-map covers all source uids.
        # If --uid-map is explicitly provided and covers all source uids,
        # we can proceed even when target_primary is None (empty target DB).
        unmapped_src = [u for u in source_uids_all if u not in uid_map]

        if not target_primary and unmapped_src:
            print(
                "[error] Cannot determine the target user_id automatically.\n"
                "  The target database is empty (you haven't logged in to the "
                "target WorkBuddy edition yet, or have never created a session).\n"
                "  Without a target uid, imported sessions will keep the source "
                "uid and be invisible in the client.\n"
                "\n"
                "  Please do ONE of the following:\n"
                "    1. Open the target WorkBuddy edition, log in, and create "
                "at least one conversation — this writes your uid into the DB. "
                "Then re-run import.\n"
                "    2. Provide --uid-map <source_uid>=<target_uid> explicitly.\n"
                "\n"
                f"  Source uid(s) in package: {', '.join(source_uids_all)}",
                file=sys.stderr,
            )
            return 1

        # Resolve uid_map: user-provided --uid-map overrides take precedence;
        # any source uid not yet mapped defaults to target_primary.
        if target_primary:
            for u in unmapped_src:
                uid_map[u] = target_primary

        # ---- Cross-machine detection ----
        import socket
        target_os = args.target_os or sys.platform
        current_hostname = socket.gethostname()
        current_home = str(Path.home())
        is_same_machine = (
            meta.source_os == target_os
            and meta.source_hostname == current_hostname
            and meta.source_home == current_home
        )
        rep.note(
            f"Source machine: {meta.source_os}/{meta.source_hostname} ({meta.source_home})"
            if meta.source_os else "Source machine info: <unknown — pre-v2 package>"
        )
        rep.note(
            f"Target machine: {target_os}/{current_hostname} ({current_home})"
        )
        rep.note(
            f"Mode: {'same-machine' if is_same_machine else 'cross-machine'}"
        )

        # ---- Auto-map (v0.2.0) ----
        if args.auto_map:
            automap_plan = automap.plan(
                meta.to_dict(),
                target_db_path=(target.path / "workbuddy.db") if (target.path / "workbuddy.db").exists() else None,
            )
            if automap_plan.needs_remap:
                rep.note(f"Auto-map activated: {automap_plan.source_os} → {automap_plan.target_os}")
                rep.note(f"  Source home: {automap_plan.source_home}")
                rep.note(f"  Target home: {automap_plan.target_home}")
                if automap_plan.path_rules:
                    for src, dst in automap_plan.path_rules.items():
                        rep.note(f"  Path rule: {src} → {dst}")
                    # Merge auto-generated path rules with any user-provided ones
                    if not path_map_rules:
                        path_map_rules = list(automap_plan.path_rules.items())
                if automap_plan.uid_map and not uid_map:
                    uid_map = automap_plan.uid_map
                    rep.note(f"  UID map: {automap_plan.uid_map}")
            for note in automap_plan.notes:
                rep.note(f"  {note}")

        mapper: Optional[PathMapper] = None
        if path_map_rules or not is_same_machine:
            # Build mapper; if no rules provided, mapper just leaves paths as-is
            # but cross-machine import will warn loudly.
            if not path_map_rules and not is_same_machine:
                rep.warn(
                    "Cross-machine import but no --path-map rules provided. "
                    "DB paths and meta.json cwd fields will keep source values "
                    "(history will not open on target). Consider re-running with "
                    f"--path-map {meta.source_home or '<src>'}={current_home}"
                )
            mapper = PathMapper(
                rules=path_map_rules,
                src_os=meta.source_os or sys.platform,
                dst_os=target_os,
            )

        ts = fs.make_ts()

        # ---- DB merge ----
        if not args.skip_db:
            target_db = target.path / "workbuddy.db"
            src_db = pkg_root / "db" / "workbuddy.db"
            if src_db.is_file():
                if not args.dry_run:
                    bak = fs.backup(target_db, ts) if target_db.exists() else None
                    if bak:
                        rep.add_backup(bak)
                    db_section = _merge_db(
                        target_db,
                        src_db,
                        inventory["db_tables"],
                        overwrite=args.overwrite,
                        uid_map=uid_map,
                    )
                else:
                    db_section = _dryrun_db(
                        target_db, src_db, inventory["db_tables"]
                    )
                rep.add("db", db_section)
            else:
                rep.add("db", {"action": "skipped", "reason": "package has no db"})
        else:
            rep.add("db", {"action": "excluded via --skip-db"})

        # ---- File assets ----
        # ---- R4 (v1.2.1): BOOTSTRAP residual conflict guard ----
        # If target has a BOOTSTRAP.md and the package carries IDENTITY.md /
        # USER.md, the target machine was likely set up by a prior migration
        # leaving a bootstrap marker. Recoverable three-step sequence:
        #   ① backup BOOTSTRAP.md for evidence → ② overwrite IDENTITY/USER
        #   from package (atomic write) → ③ delete BOOTSTRAP.md.
        # When the condition is false, fall through to the normal path.
        if not args.dry_run:
            bootstrap_result = _handle_bootstrap_conflict(
                pkg_root, target.path, ts,
            )
            if bootstrap_result["action"] != "none":
                rep.add("bootstrap", bootstrap_result)
                if bootstrap_result.get("backup"):
                    rep.add_backup(Path(bootstrap_result["backup"]))
                TRACE.add("conflict", kind="bootstrap", **bootstrap_result)

        for asset in inventory["file_assets"]:
            rel = asset["path"]
            atype = asset["type"]
            merge_strategy = asset.get("merge")
            src = pkg_root / rel
            dst = target.path / rel

            if args.skip_skills and rel == "skills":
                rep.add(f"file:{rel}", {"action": "excluded via --skip-skills"})
                continue
            if args.skip_configs and rel in ("settings.json", "mcp.json", "models.json"):
                rep.add(f"file:{rel}", {"action": "excluded via --skip-configs"})
                continue

            if atype == "dir-of-dirs":
                if args.dry_run:
                    counts = _dryrun_dir_of_dirs(src, dst, asset.get("skip_indices", []))
                    rep.add(f"file:{rel}", counts)
                    continue
                if asset.get("uid_dirs"):
                    # v1.3.0: child dir names embed user_id (storage/user-<uid>/)
                    # — rewrite uid per uid_map before merging.
                    result = fs.merge_uid_dirs(
                        src, dst, overwrite=args.overwrite,
                        uid_map=uid_map,
                        pattern=asset.get("uid_dirs"),
                    )
                else:
                    result = fs.merge_skills_dir(
                        src, dst, overwrite=args.overwrite,
                        skip_indices=asset.get("skip_indices", []),
                    )
                rep.add(
                    f"file:{rel}",
                    {
                        "action": "merged",
                        "created": len(result["created"]),
                        "skipped": len(result["skipped"]),
                        "overwritten": len(result["overwritten"]),
                        "created_names": result["created"],
                        "skipped_names": result["skipped"],
                    },
                )
            elif atype == "dir-of-files" and rel == "memory":
                # Memory: per-uid file, append-with-separator
                if not src.is_dir():
                    rep.add(f"file:{rel}", {"action": "skipped", "reason": "src absent"})
                    continue
                created, appended, overwritten = [], [], []
                for child in sorted(src.glob(asset.get("pattern", "*"))):
                    if not child.is_file():
                        continue
                    if any(child.name.endswith(s) for s in asset.get("exclude_suffix", [])):
                        continue
                    # uid rewrite for filename
                    target_name = child.name
                    found = False
                    for src_uid, dst_uid in uid_map.items():
                        if child.name == f"{src_uid}_memory.md":
                            target_name = f"{dst_uid}_memory.md"
                            found = True
                            break
                    if uid_map and not found:
                        continue  # skip this file - uid not being migrated
                    target_file = dst / target_name
                    if args.dry_run:
                        if target_file.exists():
                            appended.append(target_name)
                        else:
                            created.append(target_name)
                        continue
                    if target_file.exists() and not args.overwrite:
                        # backup before appending to be safe
                        bak = fs.backup(target_file, ts)
                        if bak:
                            rep.add_backup(bak)
                    action = fs.merge_memory_file(
                        child, target_file,
                        overwrite=args.overwrite,
                        source_uid=child.stem.rsplit("_memory", 1)[0],
                        export_time=meta.export_time,
                    )
                    if action == "created":
                        created.append(target_name)
                    elif action == "appended":
                        appended.append(target_name)
                    elif action == "overwritten":
                        overwritten.append(target_name)
                rep.add(
                    f"file:{rel}",
                    {
                        "action": "merged",
                        "created": created,
                        "appended": appended,
                        "overwritten": overwritten,
                    },
                )
            elif atype == "dir-of-files":
                # v1.3.0 fix: generic loose-file merge (assistant-display,
                # changes-index, plans, automation-backups...). Previously only
                # memory/ had a dir-of-files branch — all other dir-of-files
                # assets were silently skipped on import.
                if not src.is_dir():
                    rep.add(f"file:{rel}", {"action": "skipped", "reason": "src absent"})
                    continue
                created, skipped_f, overwritten = [], [], []
                for child in sorted(src.glob(asset.get("pattern", "*"))):
                    if not child.is_file():
                        continue
                    if any(child.name.endswith(s) for s in asset.get("exclude_suffix", [])):
                        continue
                    tf = dst / child.name
                    existed = tf.exists()
                    if existed and not args.overwrite:
                        skipped_f.append(child.name)
                        continue
                    if args.dry_run:
                        (overwritten if existed else created).append(child.name)
                        continue
                    if existed:
                        bak = fs.backup(tf, ts)
                        if bak:
                            rep.add_backup(bak)
                    dst.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(child, tf)
                    (overwritten if existed else created).append(child.name)
                rep.add(
                    f"file:{rel}",
                    {
                        "action": "merged",
                        "created": created,
                        "skipped": skipped_f,
                        "overwritten": overwritten,
                    },
                )
            elif atype == "json":
                if not src.is_file():
                    rep.add(f"file:{rel}", {"action": "skipped", "reason": "src absent"})
                    continue
                if dst.exists() and not args.dry_run:
                    bak = fs.backup(dst, ts)
                    if bak:
                        rep.add_backup(bak)
                if args.dry_run:
                    rep.add(
                        f"file:{rel}",
                        {"action": "would-merge", "strategy": merge_strategy},
                    )
                    continue
                if merge_strategy == "shallow-target-wins":
                    rep.add(f"file:{rel}", configs.shallow_target_wins(src, dst, overwrite=args.overwrite))
                elif merge_strategy == "mcp-servers-by-name":
                    rep.add(f"file:{rel}", configs.merge_mcp_servers(src, dst, overwrite=args.overwrite))
                elif merge_strategy == "field-subtree-merge":
                    # v1.2.1 (R1): field-subtree deep merge (app/app-config.json).
                    # Sandbox probe result (R2) is cached in SP; if the target
                    # dir was denied we already failed fast earlier.
                    rep.add(
                        f"file:{rel}",
                        FE.merge_field_subtree(
                            src, dst, asset, overwrite=args.overwrite,
                        ),
                    )
                    TRACE.add("extract", asset=rel, action="import-merge")
                elif merge_strategy == "list-by-id":
                    rep.add(
                        f"file:{rel}",
                        configs.merge_list_by_id(
                            src, dst,
                            list_field=asset.get("list_field", "items"),
                            id_field=asset.get("id_field", "id"),
                            overwrite=args.overwrite,
                        ),
                    )
                else:
                    rep.add(f"file:{rel}", {"action": "skipped", "reason": "unknown strategy"})
            elif atype == "file" and merge_strategy == "imported-suffix":
                if not src.is_file():
                    continue
                if dst.exists() and not args.dry_run:
                    bak = fs.backup(dst, ts)
                    if bak:
                        rep.add_backup(bak)
                if args.dry_run:
                    rep.add(
                        f"file:{rel}",
                        {
                            "action": "would-keep-target+write-imported" if dst.exists() else "would-create",
                        },
                    )
                    continue
                action = fs.merge_identity_file(src, dst, overwrite=args.overwrite)
                rep.add(f"file:{rel}", {"action": action})

        # ---- Warned assets (default-migrate with warning) ----
        for asset in inventory["warned_assets"]:
            rel = asset["path"]
            atype = asset.get("type", "dir-of-userdirs")
            src = pkg_root / rel
            dst = target.path / rel
            section_key = f"warned:{rel}"

            # v1.6.0: file-type warned asset (root .credentials.json — the
            # global MCP OAuth store). Gated by --no-credentials on import too.
            if asset.get("type") == "file" or src.is_file():
                if not src.is_file():
                    rep.add(section_key, {"action": "skipped"})
                    continue
                if args.no_credentials:
                    rep.add(section_key, {"action": "skipped", "credentials_dropped": True})
                    continue
                if args.dry_run:
                    rep.add(section_key, {
                        "action": "would-create" if not dst.exists() else "would-keep-target",
                    })
                    continue
                if dst.exists():
                    bak = fs.backup(dst, ts)
                    if bak:
                        rep.add_backup(bak)
                dst.parent.mkdir(parents=True, exist_ok=True)
                if dst.suffix == ".json":
                    # mcpOAuth keys are "serverName|hash" — merge, never clobber
                    configs.shallow_target_wins(src, dst, overwrite=args.overwrite)
                else:
                    shutil.copy2(src, dst)
                rep.add(section_key, {"action": "merged", "credentials_dropped": False})
                if asset.get("warn"):
                    rep.warn(asset["warn"])
                continue

            if not src.is_dir():
                rep.add(section_key, {"action": "skipped"})
                continue

            # v1.3.0: credentials/<expert-name>/ etc — plain dir merge + warn
            if atype == "dir-of-dirs":
                if args.dry_run:
                    names = sorted([p.name for p in src.iterdir() if p.is_dir()])
                    rep.add(section_key, {"action": "would-merge", "dirs": names})
                    continue
                result = fs.merge_skills_dir(src, dst, overwrite=args.overwrite, skip_indices=[])
                rep.add(section_key, {"action": "merged", **result})
                if asset.get("warn"):
                    rep.warn(asset["warn"])
                continue

            # legacy: connectors/<uid>/ structure
            if args.dry_run:
                uids = sorted([p.name for p in src.iterdir() if p.is_dir()])
                rep.add(
                    section_key,
                    {"action": "would-merge", "uids": uids, "no_credentials": args.no_credentials},
                )
                continue
            # Top-level files (e.g. mcp.json) via shallow merge if json
            for child in src.iterdir():
                if child.is_file() and child.suffix == ".json":
                    if (dst / child.name).exists():
                        bak = fs.backup(dst / child.name, ts)
                        if bak:
                            rep.add_backup(bak)
                    configs.shallow_target_wins(child, dst / child.name, overwrite=args.overwrite)
            result = fs.merge_connectors_dir(
                src, dst,
                overwrite=args.overwrite,
                no_credentials=args.no_credentials,
                credentials_files=asset.get("credentials_files", []),
                uid_map=uid_map,
            )
            rep.add(section_key, {"action": "merged", **result})
            if asset.get("warn") and not args.no_credentials:
                rep.warn(asset["warn"])

        # ---- Conversations ----
        if args.no_conversations or not meta.options.get("conversations", True):
            rep.add("conversations", {"action": "excluded"})
        else:
            convo = inventory["conversations"]
            src_projects = pkg_root / convo["path"]
            dst_projects = target.path / convo["path"]
            if args.dry_run:
                count = len(fs.list_session_jsonls(src_projects))
                rep.add("conversations", {"action": "would-merge", "jsonl_count": count})
            else:
                result = fs.merge_projects_dir(
                    src_projects, dst_projects, overwrite=args.overwrite,
                    progress=lambda cur, tot: R.progress(cur, tot, "会话记录"),
                )
                rep.add("conversations", {"action": "merged", **result})

        # ---- Cross-machine: rewrite paths in DB + meta.json + JSON configs ----
        if mapper is not None and mapper.rules and not args.dry_run:
            target_db = target.path / "workbuddy.db"
            path_rewrite_spec = inventory.get("path_rewrite", {})
            db_cols = path_rewrite_spec.get("db_columns", [])
            if target_db.exists() and db_cols:
                try:
                    rewrite_conn = sqlite3.connect(str(target_db), timeout=5.0)
                    try:
                        rw_result = DB.rewrite_path_columns(
                            rewrite_conn, "main", db_cols, mapper
                        )
                        rep.add("path_rewrite_db", rw_result)
                    finally:
                        rewrite_conn.close()
                except sqlite3.Error as e:
                    rep.warn(f"DB path rewrite failed: {e}")

            # Rename projects/<oldId>/ dirs based on rewritten cwd
            target_projects = target.path / "projects"
            if target_projects.is_dir():
                rename_result = fs.rename_project_dirs(target_projects, mapper)
                rep.add("path_rewrite_projects", {
                    "renamed": len(rename_result["renamed"]),
                    "cwd_updated": len(rename_result["cwd_updated"]),
                    "skipped": rename_result["skipped"][:5],
                    "rename_sample": rename_result["renamed"][:5],
                })

            # Rewrite JSON file fields (settings.json, mcp.json, etc.)
            json_specs = path_rewrite_spec.get("files", [])
            json_results: List[Dict] = []
            for spec in json_specs:
                file_glob = spec["path"]
                for fp in target.path.glob(file_glob):
                    if not fp.is_file():
                        continue
                    rj = configs.rewrite_paths_in_json(fp, spec, mapper)
                    if rj.get("rewritten"):
                        json_results.append({"file": str(fp.relative_to(target.path)), **rj})
            if json_results:
                rep.add("path_rewrite_json", json_results)

            # v1.2.1 (R5): rewrite absolute-path tokens in memory files
            # (MEMORY.md + memory/{uid}_memory.md) via PathMapper only.
            mem_files: List[Path] = []
            root_memory = target.path / "MEMORY.md"
            if root_memory.is_file():
                mem_files.append(root_memory)
            mem_dir = target.path / "memory"
            if mem_dir.is_dir():
                mem_files.extend(sorted(mem_dir.glob("*_memory.md")))
            if mem_files:
                old_uid = meta.source_user_id if uid_map else None
                new_uid = next(iter(uid_map.values()), None) if uid_map else None
                mem_result = automap.rewrite_memory_path_tokens(
                    mem_files, mapper,
                    old_uid=old_uid, new_uid=new_uid,
                )
                if mem_result["tokens_replaced"]:
                    rep.add("path_rewrite_memory", mem_result)
                    # NOTE: TRACE.add signature is add(kind, **detail) — passing
                    # kind= as a keyword collides with the positional arg.
                    TRACE.add("automap", event="memory-tokens", **mem_result)

            # v1.6.0: rewrite URL-encoded absolute paths inside artifact-index/
            # (per-session artifact/deliverable lists). Without this, restored
            # conversations point at dead paths after a cross-machine move.
            artifact_dir = target.path / "artifact-index"
            if artifact_dir.is_dir():
                art_result = automap.rewrite_artifact_index(
                    artifact_dir, mapper,
                    old_uid=meta.source_user_id if uid_map else None,
                    new_uid=next(iter(uid_map.values()), None) if uid_map else None,
                )
                if art_result["rewritten_files"]:
                    rep.add("path_rewrite_artifact_index", art_result)
                    TRACE.add("automap", event="artifact-index", **art_result)

            # After path rewrite, ensure workspace directories exist on disk
            # so that WorkBuddy can open the imported conversations.
            ws_dir_result = _ensure_workspace_dirs(target_db, args.dry_run)
            if ws_dir_result["created"] or ws_dir_result["errors"]:
                rep.add("ensure_workspace_dirs", ws_dir_result)

            # Clean up leftover source-prefixed project dirs that weren't
            # renamed during the initial pass (e.g. dirs without meta.json).
            if target_projects.is_dir():
                cleanup_result = _cleanup_leftover_project_dirs(
                    target_projects, mapper, args.dry_run
                )
                if (
                    cleanup_result["moved_files"]
                    or cleanup_result["renamed_dirs"]
                    or cleanup_result["errors"]
                ):
                    rep.add("project_dir_cleanup", cleanup_result)

        # ---- Workspace bundle extraction ----
        if args.workspaces_package and not args.dry_run:
            bundle_path = Path(args.workspaces_package).expanduser()
            if not bundle_path.exists():
                rep.warn(f"Workspace bundle not found: {bundle_path}")
            else:
                dest_root = Path(
                    args.workspace_destination or Path.home() / "wb-imported-workspaces"
                ).expanduser()
                dest_root.mkdir(parents=True, exist_ok=True)
                ws_result = fs.extract_workspace_bundle(bundle_path, dest_root, mapper)
                rep.add("workspaces", {
                    "action": "extracted",
                    "count": len(ws_result["workspaces"]),
                    "errors": ws_result["errors"][:5],
                    "destinations_sample": [
                        w["destination"] for w in ws_result["workspaces"][:5]
                    ],
                })

    # ---- Post-restore validation (v0.2.0) ----
    if not args.dry_run and not args.no_validate:
        validation_report = validate.validate(target.path)
        rep.add("validation", validation_report.to_json())
        validate.print_report(validation_report)

    # ---- Finalize ----
    rep.finish()

    # Determine if restart is required (any of the always-restart resources changed)
    restart_spec = inventory.get("restart_required", {})
    needs_restart = _needs_restart(rep, restart_spec)
    if not args.dry_run:
        report_dir = target.path / "migration-reports"
        report_path = report_dir / f"import-{fs.make_ts()}.json"
        # Attach restart metadata to the report before writing
        rep.add("restart_required", needs_restart)
        rep.add("uid_mapping", uid_map if uid_map else "none")

        # ---- R6 (v1.2.1): sessions vs projects cross-check ----
        # Detect residual drift between manifest.sessions.count and the
        # projects/ dirs actually present after import; classify sources.
        diff = _sessions_projects_diff(meta, pkg_root, target.path, rep)
        if diff["difference"] > 0:
            rep.add("session_projects_diff", diff)
            TRACE.add("conflict", event="sessions-projects-diff", detail=diff)

        # ---- v1.5.0: verify — manifest inventory vs what actually landed ----
        verify_result = _verify_import(meta, target.path, uid_map, args)
        rep.add("verify", verify_result)

        TRACE.attach_to_report(rep)
        rep.write(report_path)
        rep.note(f"Report saved: {report_path}")

    R.print_report(rep)

    # Print restart hint to stdout (separate from report so it's always visible)
    if needs_restart["required"]:
        print()
        print("=" * 60)
        print("✓ 导入完成。请重启 WorkBuddy 客户端使改动生效。")
        print()
        print(f"重启后生效：{', '.join(needs_restart['restart_reasons'])}")
        if needs_restart["hot_reloaded"]:
            print(f"已热加载（不用重启）：{', '.join(needs_restart['hot_reloaded'])}")
        if uid_map:
            print()
            print(f"uid 自动映射：{uid_map}")
        # v1.5.0: verify summary (always visible, not just in the report)
        verify_sec = rep.sections.get("verify")
        if isinstance(verify_sec, dict):
            print()
            if verify_sec.get("missing_total"):
                print(
                    f"⚠ 资产校验：{verify_sec['present_total']}/"
                    f"{verify_sec['expected_total']} 项就位，"
                    f"{verify_sec['missing_total']} 项缺失（详见报告 verify 段"
                    f"，或按 faq.md 排查）。"
                )
            else:
                print(
                    f"✓ 资产校验：{verify_sec['expected_total']}/"
                    f"{verify_sec['expected_total']} 项全部就位。"
                )
        print()
        print("提示：直接关闭并重新打开 WorkBuddy 即可，无需退出账号。")
        print("=" * 60)

    return 0


def _needs_restart(rep, restart_spec: dict) -> dict:
    """Inspect what was actually touched in this import and decide if restart is needed."""
    touched: List[str] = list(rep.sections.keys())
    restart_after = restart_spec.get("restart_after_any_of", []) or []
    hot_reloaded_spec = restart_spec.get("hot_reloaded", []) or []
    reasons: List[str] = []
    hot: List[str] = []
    for t in touched:
        # t is like 'db', 'file:settings.json', 'file:IDENTITY.md', etc.
        bare = t.split(":", 1)[1] if ":" in t else t
        for trigger in restart_after:
            if trigger == bare or (trigger.endswith("/*") and bare.startswith(trigger[:-1])):
                reasons.append(bare)
                break
        for hot_trigger in hot_reloaded_spec:
            if hot_trigger == bare or (hot_trigger.endswith("/*") and bare.startswith(hot_trigger[:-1])):
                hot.append(bare)
                break
    # Dedup while preserving order
    seen: Set[str] = set()
    reasons = [r for r in reasons if not (r in seen or seen.add(r))]
    seen = set()
    hot = [h for h in hot if not (h in seen or seen.add(h))]
    return {
        "required": bool(reasons),
        "restart_reasons": reasons,
        "hot_reloaded": hot,
    }


# --- helpers ---

def _atomic_write(path: Path, content: str) -> None:
    """Write via temp file + rename for crash-safety (v1.2.1 R4)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".wb-tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def _handle_bootstrap_conflict(pkg_root: Path, target_root: Path, ts: str) -> dict:
    """R4 (v1.2.1): resolve BOOTSTRAP residual conflict for identity files.

    Trigger: target has BOOTSTRAP.md AND package carries IDENTITY.md and/or
    USER.md. Sequence (recoverable, each step traced):
      ① backup BOOTSTRAP.md → ② overwrite IDENTITY.md/USER.md from package
      (atomic write) → ③ delete BOOTSTRAP.md.
    Returns {"action": "cleaned"|"none", ...}. Never raises on cleanup.
    """
    bootstrap = target_root / "BOOTSTRAP.md"
    pkg_identity = pkg_root / "IDENTITY.md"
    pkg_user = pkg_root / "USER.md"
    has_identity = pkg_identity.is_file()
    has_user = pkg_user.is_file()
    if not bootstrap.is_file() or not (has_identity or has_user):
        return {"action": "none"}

    # ① backup BOOTSTRAP.md as evidence
    bak = fs.backup(bootstrap, ts)
    # ② overwrite identity files from package (atomic)
    written = []
    if has_identity:
        _atomic_write(target_root / "IDENTITY.md", pkg_identity.read_text(encoding="utf-8"))
        written.append("IDENTITY.md")
    if has_user:
        _atomic_write(target_root / "USER.md", pkg_user.read_text(encoding="utf-8"))
        written.append("USER.md")
    # ③ delete BOOTSTRAP.md (guarded: must stay inside target root)
    fs.safe_delete(bootstrap, target_root)
    return {
        "action": "cleaned",
        "backup": str(bak) if bak else None,
        "overwritten": written,
        "bootstrap_removed": True,
    }


def _sessions_projects_diff(
    meta: M.Manifest,
    pkg_root: Path,
    target_root: Path,
    rep: R.Report,
) -> dict:
    """R6 (v1.2.1): cross-check sessions count vs projects dirs.

    Manifest records source sessions count (after export filtering). The
    target projects/ dirs after import should roughly match. Any residual
    difference is classified into three sources:
      orphan_jsonl_filtered - JSONLs dropped at export (not tied to sessions)
      in_flight_skipped     - sessions skipped at import (defensive, e.g.
                              non-terminal status protection)
      source_only_state     - genuine source/target divergence
    Returns {"source_sessions", "target_projects", "difference", "breakdown"}.
    """
    src_sessions = 0
    db_inv = (meta.asset_inventory or {}).get("db", {})
    if isinstance(db_inv, dict):
        src_sessions = db_inv.get("sessions", 0) or 0

    target_projects = 0
    projects_dir = target_root / "projects"
    if projects_dir.is_dir():
        target_projects = sum(1 for p in projects_dir.iterdir() if p.is_dir())

    difference = max(0, src_sessions - target_projects)

    # Classification
    orphan = 0
    convo = rep.sections.get("conversations", {})
    if isinstance(convo, dict):
        orphan = convo.get("orphans_dropped", 0) or 0

    in_flight = 0
    db_sec = rep.sections.get("db", {})
    if isinstance(db_sec, dict):
        excluded = db_sec.get("excluded", {})
        if isinstance(excluded, dict):
            sess_ex = excluded.get("sessions", {})
            if isinstance(sess_ex, dict):
                by_status = sess_ex.get("by_status", {})
                if isinstance(by_status, dict):
                    for status, n in by_status.items():
                        if str(status).lower() in (
                            "working", "in_progress", "running", "active", "awaiting_input",
                        ):
                            in_flight += n if isinstance(n, (int, float)) else 0

    source_only = max(0, difference - orphan - in_flight)
    return {
        "source_sessions": src_sessions,
        "target_projects": target_projects,
        "difference": difference,
        "breakdown": {
            "orphan_jsonl_filtered": orphan,
            "in_flight_skipped": in_flight,
            "source_only_state": source_only,
        },
    }


def _verify_import(
    meta: M.Manifest,
    target_root: Path,
    uid_map: Dict[str, str],
    args,
) -> dict:
    """v1.5.0: compare the export-time manifest inventory against what
    actually landed on the target, so users get an explicit "everything is
    in place" (or a precise missing list) instead of guessing.

    Merge-without-overwrite semantics apply: an item counts as present if
    it exists on target under the (uid-rewritten) expected name, regardless
    of whether it came from the package or was already there.
    Skipped scopes (--skip-*) are reported as status=skipped, not missing.
    """
    inv = (meta.asset_inventory or {})
    checks: List[Dict] = []

    def _add(item: str, status: str, expected: int, present: int,
             missing: Optional[List[str]] = None) -> None:
        checks.append({
            "item": item, "status": status,
            "expected": expected, "present": present,
            **({"missing": missing} if missing else {}),
        })

    # 1. skills
    expected_skills = inv.get("skills") or []
    if args.skip_skills:
        _add("skills", "skipped", len(expected_skills), 0)
    else:
        skills_dir = target_root / "skills"
        tgt_skills = (
            {p.name for p in skills_dir.iterdir() if p.is_dir()}
            if skills_dir.is_dir() else set()
        )
        missing = sorted(s for s in expected_skills if s not in tgt_skills)
        _add("skills", "ok", len(expected_skills),
             len(expected_skills) - len(missing), missing)

    # 2. memory files (uid-rewritten names)
    expected_uids = inv.get("memory_uids") or []
    mem_dir = target_root / "memory"
    mem_missing = []
    for u in expected_uids:
        tgt_name = f"{(uid_map or {}).get(u, u)}_memory.md"
        if not (mem_dir / tgt_name).is_file():
            mem_missing.append(tgt_name)
    _add("memory", "ok", len(expected_uids),
         len(expected_uids) - len(mem_missing), mem_missing)

    # 3. identity files
    identity = inv.get("identity_files") or []
    id_missing = [f for f in identity if not (target_root / f).is_file()]
    _add("identity", "ok", len(identity), len(identity) - len(id_missing),
         id_missing)

    # 4. configs
    if args.skip_configs:
        cfg = inv.get("configs") or []
        _add("configs", "skipped", len(cfg), 0)
    else:
        cfg = inv.get("configs") or []
        cfg_missing = [f for f in cfg if not (target_root / f).is_file()]
        _add("configs", "ok", len(cfg), len(cfg) - len(cfg_missing),
             cfg_missing)

    # 5. conversations (target dir count should cover the exported count)
    proj_inv = inv.get("projects") or {}
    expected_jsonl = proj_inv.get("jsonl_count", 0) or 0
    if args.no_conversations or not meta.options.get("conversations", True):
        _add("conversations", "skipped", expected_jsonl, 0)
    else:
        projects_dir = target_root / "projects"
        tgt_dirs = (
            sum(1 for p in projects_dir.iterdir() if p.is_dir())
            if projects_dir.is_dir() else 0
        )
        present = min(tgt_dirs, expected_jsonl) if tgt_dirs >= expected_jsonl else tgt_dirs
        _add("conversations", "ok" if present >= expected_jsonl else "partial",
             expected_jsonl, present)

    # 6. db sessions (merge-without-overwrite: target >= exported count)
    db_inv = inv.get("db") or {}
    expected_sessions = db_inv.get("sessions", 0) or 0
    if args.skip_db or expected_sessions == 0:
        _add("db:sessions", "skipped", expected_sessions, 0)
    else:
        tgt_sessions = 0
        tgt_db = target_root / "workbuddy.db"
        if tgt_db.is_file():
            try:
                conn = sqlite3.connect(f"file:{tgt_db}?mode=ro", uri=True)
                try:
                    tgt_sessions = conn.execute(
                        "SELECT COUNT(*) FROM sessions"
                    ).fetchone()[0]
                finally:
                    conn.close()
            except sqlite3.Error:
                tgt_sessions = -1  # unreadable — surfaced as missing, not silently ok
        present = min(max(tgt_sessions, 0), expected_sessions)
        _add("db:sessions", "ok" if present >= expected_sessions else "partial",
             expected_sessions, present)

    # Aggregate (only non-skipped checks count toward the totals)
    expected_total = sum(c["expected"] for c in checks if c["status"] != "skipped")
    present_total = sum(min(c["present"], c["expected"])
                        for c in checks if c["status"] != "skipped")
    missing_total = max(0, expected_total - present_total)
    return {
        "action": "verified",
        "checks": checks,
        "expected_total": expected_total,
        "present_total": present_total,
        "missing_total": missing_total,
        "verdict": "all-present" if missing_total == 0 else "has-missing",
    }


def _merge_db(
    target_db: Path,
    src_db: Path,
    tables: list,
    *,
    overwrite: bool,
    uid_map: Dict[str, str],
) -> dict:
    """Apply ATTACH-based merge. Returns section dict."""
    target_db.parent.mkdir(parents=True, exist_ok=True)
    # If target_db doesn't exist, copy src as initial (no merge needed)
    if not target_db.exists():
        shutil.copy2(src_db, target_db)
        # Apply uid_map rewrite in place if needed
        if uid_map:
            conn = sqlite3.connect(str(target_db))
            try:
                for src_uid, dst_uid in uid_map.items():
                    conn.execute(
                        "UPDATE sessions SET user_id = ? WHERE user_id = ?",
                        (dst_uid, src_uid),
                    )
                conn.commit()
            finally:
                conn.close()
        return {"action": "initialized", "reason": "target db absent"}

    # Try to lock target db
    try:
        lock_conn = DB.acquire_write_lock(target_db)
        lock_conn.execute("ROLLBACK")  # release immediate, keep connection
    except BlockingIOError as e:
        raise SystemExit(f"[error] {e}\nexit code: 2") from e

    conn = lock_conn
    try:
        conn.execute("ATTACH DATABASE ? AS src", (str(src_db),))
        section: dict = {"action": "merged", "tables": {}, "orphan_runs_dropped": 0}

        # Snapshot for sessions.deleted_at protection (only if overwrite)
        deleted_at_snapshot: dict = {}
        if overwrite:
            deleted_at_snapshot = DB.protect_sessions_deleted_at(conn, "main")

        for t in tables:
            name = t["name"]
            extra_where = ""
            if name == "automation_runs":
                # Drop orphans
                orphan = DB.count_orphan_runs(conn, "src", "main")
                section["orphan_runs_dropped"] = orphan
                extra_where = (
                    "automation_id IN (SELECT id FROM main.automations) "
                    "OR automation_id IN (SELECT id FROM src.automations)"
                )
            if t.get("has_deleted_at"):
                extra_where = (
                    f"({extra_where}) AND deleted_at IS NULL"
                    if extra_where
                    else "deleted_at IS NULL"
                )
            # Defensive: also skip in-flight sessions on import side, in case
            # the package was built by an older tool that didn't filter.
            ex_status = t.get("exclude_status") or []
            if ex_status:
                in_list = ", ".join(DB.sqlite3_literal(s) for s in ex_status)
                clause = f"status NOT IN ({in_list})"
                extra_where = f"({extra_where}) AND {clause}" if extra_where else clause
                # Count what we're defensively skipping
                cur = conn.execute(
                    f"SELECT COUNT(*) FROM src.{name} WHERE status IN ({in_list})"
                )
                defensive_skip = cur.fetchone()[0]
                if defensive_skip:
                    section.setdefault("defensive_in_flight_skipped", {})[name] = defensive_skip

            inserted, skipped = DB.merge_table(
                conn,
                target_schema="main",
                source_schema="src",
                table=name,
                overwrite=overwrite,
                extra_where=extra_where,
                transform_user_id=uid_map or None,
            )
            section["tables"][name] = {"inserted": inserted, "skipped_or_replaced": skipped}

        if overwrite and deleted_at_snapshot:
            restored = DB.restore_sessions_deleted_at(conn, "main", deleted_at_snapshot)
            section["sessions_deleted_at_restored"] = restored

        conn.commit()
        conn.execute("DETACH DATABASE src")
        return section
    finally:
        conn.close()


def _dryrun_db(target_db: Path, src_db: Path, tables: list) -> dict:
    out = {"action": "would-merge", "tables": {}}
    if not target_db.exists():
        out["note"] = "target db absent → would initialize from package"
        return out
    src_conn = sqlite3.connect(f"file:{src_db}?mode=ro", uri=True)
    try:
        for t in tables:
            name = t["name"]
            try:
                cur = src_conn.execute(f"SELECT COUNT(*) FROM {name}")
                src_rows = cur.fetchone()[0]
            except sqlite3.Error:
                src_rows = 0
            out["tables"][name] = {"src_rows": src_rows}
    finally:
        src_conn.close()
    return out


def _dryrun_dir_of_dirs(src: Path, dst: Path, skip_indices: list) -> dict:
    if not src.is_dir():
        return {"action": "skipped", "reason": "src absent"}
    src_names = [p.name for p in src.iterdir() if p.is_dir() and p.name not in skip_indices]
    dst_names = set(p.name for p in dst.iterdir() if p.is_dir()) if dst.is_dir() else set()
    would_create = [n for n in src_names if n not in dst_names]
    would_skip = [n for n in src_names if n in dst_names]
    return {
        "action": "would-merge",
        "would_create": would_create,
        "would_skip": would_skip,
    }


def _ensure_workspace_dirs(target_db: Path, dry_run: bool) -> dict:
    """Create any workspace directories referenced by sessions that don't exist on disk.

    After cross-machine import, session cwds point to mapped paths that may not
    exist yet. Without these directories, WorkBuddy cannot open the conversations.
    """
    result: dict = {"created": [], "existing": 0, "errors": []}
    conn = sqlite3.connect(str(target_db))
    try:
        cur = conn.execute(
            "SELECT DISTINCT cwd FROM sessions WHERE deleted_at IS NULL AND cwd IS NOT NULL"
        )
        cwds = [row[0] for row in cur if row[0]]
    finally:
        conn.close()

    for cwd in cwds:
        cwd_path = Path(cwd)
        if cwd_path.is_dir():
            result["existing"] += 1
            continue
        if dry_run:
            result["created"].append(cwd)
        else:
            try:
                cwd_path.mkdir(parents=True, exist_ok=True)
                result["created"].append(cwd)
            except OSError as e:
                result["errors"].append({"cwd": cwd, "error": str(e)})
    return result


def _cleanup_leftover_project_dirs(
    projects_root: Path, mapper, dry_run: bool
) -> dict:
    """After path rewrite, scan for leftover source-prefixed project dirs.

    Some dirs may not have been renamed during the initial pass (e.g. missing
    meta.json). This post-pass moves their JSONL files to the corresponding
    target-prefixed dir or renames the dir directly.
    """
    from scripts.pathmap import compress_workspace_path, decompress_workspace_path

    result = {"moved_files": 0, "renamed_dirs": [], "deleted_dirs": 0, "errors": []}
    if not projects_root.is_dir():
        return result

    # Walk existing dirs and find orphans
    for project_dir in sorted(projects_root.iterdir()):
        if not project_dir.is_dir():
            continue
        dir_name = project_dir.name

        # Try to reverse-engineer the original cwd from the dir name
        reconstructed = decompress_workspace_path(dir_name)
        if not reconstructed:
            continue

        rewritten = mapper.rewrite(reconstructed)
        if not rewritten:
            continue

        new_project_id = compress_workspace_path(rewritten.new_path)
        if new_project_id == dir_name:
            continue  # Already correct

        new_dir = projects_root / new_project_id
        if not new_dir.exists():
            # Target dir doesn't exist: just rename
            if not dry_run:
                try:
                    project_dir.rename(new_dir)
                    result["renamed_dirs"].append(
                        {"from": dir_name, "to": new_project_id}
                    )
                except OSError as e:
                    result["errors"].append(f"rename {dir_name}: {e}")
            else:
                result["renamed_dirs"].append(
                    {"from": dir_name, "to": new_project_id}
                )
        else:
            # Both exist: move files from old to new, then delete old
            if not dry_run:
                moved = 0
                for child in project_dir.rglob("*"):
                    if not child.is_file():
                        continue
                    rel = child.relative_to(project_dir)
                    dst = new_dir / rel
                    if dst.exists():
                        continue
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        shutil.move(str(child), str(dst))
                        moved += 1
                    except OSError:
                        pass
                result["moved_files"] += moved
                if moved > 0:
                    # Try to delete old dir if empty
                    try:
                        _rmtree_if_empty(project_dir)
                        result["deleted_dirs"] += 1
                    except OSError:
                        pass
            else:
                result["moved_files"] += len(
                    list(project_dir.rglob("*.jsonl"))
                )

    return result


def _rmtree_if_empty(d: Path) -> None:
    """Remove a directory tree if it contains no files."""
    has_files = False
    for root, dirs, files in os.walk(d):
        if files:
            has_files = True
            break
    if not has_files:
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:  # v1.4.0: human-friendly error surface
        from scripts.errors import humanize
        print(f"\n[错误] {humanize(e)}", file=sys.stderr)
        sys.exit(1)
