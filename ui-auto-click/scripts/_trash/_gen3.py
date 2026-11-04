#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
import numpy as np
import cv2
from PIL import Image

BASE = Path(r"C:/Users/Administrator/.workbuddy/clipboard-images")
GZH = BASE / "clipboard-2026-10-28T12-25-30-514Z-1a33eea1.jpg"
PER = BASE / "clipboard-2026-10-28T12-25-30-515Z-51ebf955.jpg"
FAV = BASE / "clipboard-2026-10-28T12-25-30-515Z-2696ec17.png"
OUT = Path(r"C:/Users/Administrator/.workbuddy/skills/ui-auto-click/out/nav-debug")
OUT.mkdir(parents=True, exist_ok=True)


def broad_mask(a):
    r, g, b = a[:, :, 0].astype(int), a[:, :, 1].astype(int), a[:, :, 2].astype(int)
    stroke = (r > 180) & (r - g > 50) & (r - b > 50)
    a[stroke] = (248, 248, 248)
    return a


def comps(mask, min_area=30):
    num, lab = cv2.connectedComponents((mask.astype(np.uint8)) * 255, connectivity=8)
    out = []
    for i in range(1, num):
        ys, xs = np.where(lab == i)
        if len(ys) < min_area:
            continue
        out.append((int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()), int(len(ys))))
    return out


def save(a, rect, name):
    x1, y1, x2, y2 = rect
    Image.fromarray(a[y1:y2, x1:x2]).save(OUT / name)


# ----- #2：遮红后裁公众号 icon+text -----
a2 = broad_mask(np.array(Image.open(GZH).convert("RGB")))
save(a2, (68, 426, 205, 494), "cand_gzh2.png")

# ----- #3：用红色圈定位小人像 -----
a3 = np.array(Image.open(PER).convert("RGB")).astype(int)
r3, g3, b3 = a3[:, :, 0], a3[:, :, 1], a3[:, :, 2]
red3 = (r3 > 180) & (r3 - g3 > 50) & (r3 - b3 > 50)
print("=== #3 red components (annotation circles) ===")
red_comps = sorted(comps(red3, 40), key=lambda z: -z[4])
for c in red_comps[:8]:
    X1, Y1, X2, Y2, n = c
    cx, cy = (X1 + X2) // 2, (Y1 + Y2) // 2
    print("  red bbox x[%d,%d] y[%d,%d] n=%d  center=(%d,%d)" % (X1, X2, Y1, Y2, n, cx, cy))
    if cx > 800:  # 取右侧那个（个人中心红圈）
        a3m = broad_mask(np.array(Image.open(PER).convert("RGB")))
        save(a3m, (max(0, cx - 22), max(0, cy - 22), cx + 22, cy + 22), "cand_per2.png")
        print("  -> saved cand_per2 around center")

# ----- #4：赞和收藏（已确认完整） -----
a4 = broad_mask(np.array(Image.open(FAV).convert("RGB")))
save(a4, (180, 178, 342, 228), "cand_fav2.png")
print("done")
