"""Accumulate per-asset actions and render stdout / json reports."""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class Report:
    mode: str = "import"          # "export" | "import"
    started_at: str = ""
    finished_at: str = ""
    dry_run: bool = False
    overwrite: bool = False
    target: Optional[str] = None
    source: Optional[str] = None
    sections: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    backups: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    error: Optional[str] = None

    def start(self) -> None:
        self.started_at = datetime.now().astimezone().isoformat(timespec="seconds")

    def finish(self) -> None:
        self.finished_at = datetime.now().astimezone().isoformat(timespec="seconds")

    def add(self, key: str, value: Any) -> None:
        self.sections[key] = value

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def note(self, msg: str) -> None:
        self.notes.append(msg)

    def add_backup(self, path: Path) -> None:
        self.backups.append(str(path))

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")


def hr() -> str:
    return "-" * 60


def echo(msg: str, *, dry: bool = False, file=None) -> None:
    prefix = "[dry] " if dry else ""
    print(prefix + msg, file=file or sys.stdout)


def progress(current: int, total: int, label: str = "处理") -> None:
    """Throttled progress line for long-running file operations (v1.4.0).

    Prints at most ~10 lines per operation: every 10% milestone plus the
    final 100%. Skips entirely for tiny workloads (<20 items) to avoid noise.
    """
    if total < 20 or current <= 0:
        return
    if current == total or current % max(1, total // 10) == 0:
        pct = current * 100 // total
        print(f"[进度] {label} {pct:3d}% ({current}/{total})")


def render_section(key: str, value: Any) -> str:
    """Produce a short human-readable line for one section."""
    if isinstance(value, dict):
        if "action" in value:
            return f"[{key}] {value.get('action')}: " + _summarize_dict(value)
        return f"[{key}] " + _summarize_dict(value)
    if isinstance(value, list):
        return f"[{key}] {len(value)} items"
    return f"[{key}] {value}"


def _summarize_dict(d: Dict[str, Any]) -> str:
    parts = []
    for k, v in d.items():
        if k == "action":
            continue
        if k == "breakdown" and isinstance(v, dict):
            # v1.2.1 (R6): semantic annotation for sessions vs projects diff
            sub = ", ".join(f"{sk}={sv}" for sk, sv in v.items())
            parts.append(f"breakdown{{{sub}}}")
        elif isinstance(v, list):
            parts.append(f"{k}={len(v)}")
        else:
            parts.append(f"{k}={v}")
    return ", ".join(parts)


def print_report(report: Report) -> None:
    print(hr())
    print(f"{report.mode.upper()} {'(DRY RUN)' if report.dry_run else ''}")
    print(f"  source: {report.source}")
    print(f"  target: {report.target}")
    print(f"  overwrite: {report.overwrite}")
    print(hr())
    for k, v in report.sections.items():
        print(render_section(k, v))
    if report.backups:
        print(hr())
        print("Backups (NOT auto-cleaned, delete manually when you're sure):")
        for b in report.backups:
            print(f"  {b}")
    if report.warnings:
        print(hr())
        print("Warnings:")
        for w in report.warnings:
            print(f"  ! {w}")
    if report.notes:
        print(hr())
        for n in report.notes:
            print(f"  {n}")
    print(hr())
