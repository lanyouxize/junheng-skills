#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
import numpy as np
from PIL import Image

BASE = Path(r"C:/Users/Administrator/.workbuddy/clipboard-images")
PER = BASE / "clipboard-2026-10-28T12-25-30-515Z-51ebf955.jpg"
OUT = Path(r"C:/Users/Administrator/.workbuddy/skills/ui-auto-click/out/nav-debug")
OUT.mkdir(parents=True, exist_ok=True)


def broad_mask(a):
    r, g, b = a[:, :, 0].astype(int), a[:, :, 1].astype(int), a[:, :, 2].astype(int)
    stroke = (r > 180) & (r - g > 50) & (r - b > 50)
    a[stroke] = (248, 248, 248)
    return a


a3 = broad_mask(np.array(Image.open(PER).convert("RGB")))
# 个人中心红圈中心 (1524,89)，裁 44x44 含图标（遮红后）
cx, cy = 1524, 89
Image.fromarray(a3[cy-22:cy+22, cx-22:cx+22]).save(OUT / "cand_per2.png")
print("person center crop saved around", (cx, cy))
