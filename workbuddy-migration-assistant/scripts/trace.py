"""Structured execution trace events (v1.2.1).

Collects lightweight structured events from export/import flows:
  probe    - sandbox strip_write pre-probe result
  extract  - field-subtree extraction (app-config.json)
  conflict - BOOTSTRAP / merge conflict handling
  automap  - auto path/user mapping decisions

Events are accumulated in a module-level list and can be dumped to JSON
(attached to import/export reports) or reset between runs.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class TraceEvent:
    kind: str                              # probe | extract | conflict | automap
    ts: str = ""
    detail: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.ts:
            self.ts = datetime.now().astimezone().isoformat(timespec="seconds")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


_events: List[TraceEvent] = []


def reset() -> None:
    """Clear accumulated events (call at the start of a run)."""
    _events.clear()


def add(kind: str, **detail: Any) -> None:
    """Record one structured event."""
    _events.append(TraceEvent(kind=kind, detail=detail))


def events() -> List[Dict[str, Any]]:
    return [e.to_dict() for e in _events]


def count(kind: str) -> int:
    return sum(1 for e in _events if e.kind == kind)


def to_json() -> str:
    return json.dumps(events(), ensure_ascii=False, indent=2)


def attach_to_report(rep) -> None:
    """Attach trace events to a Report section (if any events exist)."""
    if _events:
        rep.add("trace", {"count": len(_events), "events": events()})
