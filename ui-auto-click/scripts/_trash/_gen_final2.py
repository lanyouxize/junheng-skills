#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
import numpy as np
from PIL import Image

BASE = Path(r"C:/Users/Administrator/.workbuddy/clipboard-images")
TB = BASE / "clipboard-2026-10-28T12-25-30-513Z-fac7224f.png"
GZH = BASE / "clipboard-2026-10-28T12-25-30-514Z-1a33eea1.jpg"
PER = BASE / "clipboard-2026-10-28T12-25-30-515Z-51ebf955.jpg"
FAV = BASE / "clipboard-2026-10-28T12-25-30-515Z-2696ec17.png"
SKILL = Path(r"C:/Users/Administrator/.workbuddy/skills/ui-auto-click")
TPL = SKILL / "templates"
DBG = SKILL / "out/nav-debug"
TPL.mkdir(parents=True, exist_ok=True); DBG.mkdir(parents=True, exist_ok=True)


def mask_stroke(a):
    r, g, b = a[:, :, 0].astype(int), a[:, :, 1].astype(int), a[:, :, 2].astype(int)
    stroke = (r > 180) & (r - g > 40) & (r - b > 40)
    a[stroke] = (248, 248, 248)
    return a


def save(src, rect, name):
    a = mask_stroke(np.array(Image.open(src).convert("RGB")))
    x1, y1, x2, y2 = rect
    im = Image.fromarray(a[y1:y2, x1:x2])
    im.save(TPL / name); im.save(DBG / name)
    print("saved", name, im.size)


save(TB, (1442, 15, 1481, 49), "nav-taskbar-wechat.png")
save(GZH, (64, 626, 212, 696), "nav-gzh.png")
save(PER, (1502, 67, 1546, 111), "nav-person.png")
save(FAV, (178, 176, 352, 230), "nav-fav.png")
print("DONE")
