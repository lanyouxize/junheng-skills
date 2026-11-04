#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证 4 个导航模板能否在源截图中被 best_match 命中（校准阈值 + 证明模板可用）。"""
from pathlib import Path
import vision  # 复用脚本目录的 vision

BASE = Path(r"C:/Users/Administrator/.workbuddy/clipboard-images")
SKILL = Path(r"C:/Users/Administrator/.workbuddy/skills/ui-auto-click")
TPL = SKILL / "templates"

cases = [
    ("taskbar", BASE / "clipboard-2026-10-28T12-25-30-513Z-fac7224f.png",
     TPL / "nav-taskbar-wechat.png", False, (1442, 15)),
    ("gzh", BASE / "clipboard-2026-10-28T12-25-30-514Z-1a33eea1.jpg",
     TPL / "nav-gzh.png", True, (62, 628)),
    ("person", BASE / "clipboard-2026-10-28T12-25-30-515Z-51ebf955.jpg",
     TPL / "nav-person.png", True, (1502, 67)),
    ("fav", BASE / "clipboard-2026-10-28T12-25-30-515Z-2696ec17.png",
     TPL / "nav-fav.png", True, (180, 178)),
]

for name, src, tpl, edge, expect in cases:
    hay = vision.Image.open(str(src)).convert("RGB")
    needle = vision.Image.open(str(tpl)).convert("RGB")
    score, loc = vision.best_match(hay, needle, edge=edge)
    ok = loc is not None and abs(loc[0] - expect[0]) < 40 and abs(loc[1] - expect[1]) < 40
    print("%-9s edge=%-5s score=%6.3f loc=%s expect=%s -> %s" %
          (name, edge, score, loc, expect, "OK" if ok else "MISMATCH/FAIL"))
