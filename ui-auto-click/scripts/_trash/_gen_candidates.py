#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成三个候选模板（严格遮红 + 收紧裁切），供核对。"""
from pathlib import Path
import numpy as np
from PIL import Image

BASE = Path(r"C:/Users/Administrator/.workbuddy/clipboard-images")
TB = BASE / "clipboard-2026-10-28T12-25-30-513Z-fac7224f.png"
PER = BASE / "clipboard-2026-10-28T12-25-30-515Z-51ebf955.jpg"
FAV = BASE / "clipboard-2026-10-28T12-25-30-515Z-2696ec17.png"
OUT = Path(r"C:/Users/Administrator/.workbuddy/skills/ui-auto-click/out/nav-debug")
OUT.mkdir(parents=True, exist_ok=True)


def strict_mask(a):
    r, g, b = a[:, :, 0].astype(int), a[:, :, 1].astype(int), a[:, :, 2].astype(int)
    stroke = (r > 200) & (g < 120) & (b < 120) & (r - g > 80) & (r - b > 80)
    a[stroke] = (248, 248, 248)
    return a


def save(src, rect, name):
    a = strict_mask(np.array(Image.open(src).convert("RGB")))
    x1, y1, x2, y2 = rect
    Image.fromarray(a[y1:y2, x1:x2]).save(OUT / name)


save(TB, (1442, 15, 1481, 49), "cand_taskbar.png")
save(PER, (1024, 52, 1064, 90), "cand_person.png")
save(FAV, (196, 180, 328, 226), "cand_fav.png")
print("done")
