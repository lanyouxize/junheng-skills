#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
import numpy as np
from PIL import Image

BASE = Path(r"C:/Users/Administrator/.workbuddy/clipboard-images")
GZH = BASE / "clipboard-2026-10-28T12-25-30-514Z-1a33eea1.jpg"
PER = BASE / "clipboard-2026-10-28T12-25-30-515Z-51ebf955.jpg"
FAV = BASE / "clipboard-2026-10-28T12-25-30-515Z-2696ec17.png"
OUT = Path(r"C:/Users/Administrator/.workbuddy/skills/ui-auto-click/out/nav-debug")
OUT.mkdir(parents=True, exist_ok=True)


def strict_mask(a):
    r, g, b = a[:, :, 0].astype(int), a[:, :, 1].astype(int), a[:, :, 2].astype(int)
    stroke = (r > 200) & (g < 120) & (b < 120) & (r - g > 80) & (r - b > 80)
    a[stroke] = (248, 248, 248)
    return a


def save_masked(src, rect, name):
    a = strict_mask(np.array(Image.open(src).convert("RGB")))
    x1, y1, x2, y2 = rect
    Image.fromarray(a[y1:y2, x1:x2]).save(OUT / name)


def save_raw(src, rect, name):
    a = np.array(Image.open(src).convert("RGB"))
    x1, y1, x2, y2 = rect
    Image.fromarray(a[y1:y2, x1:x2]).save(OUT / name)


# #2 公众号 icon+text（绿底选中态；遮纯红笔迹即可，保留绿底与形状）
save_masked(GZH, (68, 428, 200, 492), "cand_gzh.png")
# #3 个人中心：先看原始区域（含红圈）定位小人像
save_raw(PER, (1000, 38, 1120, 105), "cand_per_view.png")
# #4 赞和收藏：加宽到把「藏」收全
save_masked(FAV, (180, 178, 342, 228), "cand_fav2.png")
print("done")
