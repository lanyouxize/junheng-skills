#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐行像素剖面，揭示 #2/#3/#4 的真实版面（不依赖视觉坐标）。"""
from pathlib import Path
import numpy as np
from PIL import Image

BASE = Path(r"C:/Users/Administrator/.workbuddy/clipboard-images")
GZH = BASE / "clipboard-2026-10-28T12-25-30-514Z-1a33eea1.jpg"
PER = BASE / "clipboard-2026-10-28T12-25-30-515Z-51ebf955.jpg"
FAV = BASE / "clipboard-2026-10-28T12-25-30-515Z-2696ec17.png"


def profile(path, xr, yr, thr=240):
    a = np.array(Image.open(path).convert("RGB")).astype(int)
    L = (a[:, :, 0] + a[:, :, 1] + a[:, :, 2]) // 3
    print("=== %s  x[%d,%d] y[%d,%d] (L<%d) ===" % (path.name, xr[0], xr[1], yr[0], yr[1], thr))
    for y in range(yr[0], yr[1]):
        row = L[y, xr[0]:xr[1]]
        mask = row < thr
        c = int(mask.sum())
        if c >= 4:
            xs = np.where(mask)[0]
            print("  y=%d  count=%4d  x[%d,%d]" % (y, c, int(xs.min()) + xr[0], int(xs.max()) + xr[0]))


profile(GZH, (55, 330), (395, 520))
print()
profile(FAV, (90, 330), (60, 320))
print()
profile(PER, (870, 1180), (28, 105))
