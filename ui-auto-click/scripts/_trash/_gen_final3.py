#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
import numpy as np
from PIL import Image

BASE = Path(r"C:/Users/Administrator/.workbuddy/clipboard-images")
GZH = BASE / "clipboard-2026-10-28T12-25-30-514Z-1a33eea1.jpg"
SKILL = Path(r"C:/Users/Administrator/.workbuddy/skills/ui-auto-click")
TPL = SKILL / "templates"; DBG = SKILL / "out/nav-debug"
TPL.mkdir(parents=True, exist_ok=True); DBG.mkdir(parents=True, exist_ok=True)


def mask_stroke(a):
    r, g, b = a[:, :, 0].astype(int), a[:, :, 1].astype(int), a[:, :, 2].astype(int)
    stroke = (r > 150) & (r - g > 30) & (r - b > 30)
    a[stroke] = (248, 248, 248)
    return a


a = mask_stroke(np.array(Image.open(GZH).convert("RGB")))
im = Image.fromarray(a[624:698, 64:230])
im.save(TPL / "nav-gzh.png"); im.save(DBG / "nav-gzh.png")
print("saved nav-gzh", im.size)
