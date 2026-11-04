#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""严格遮红（只去纯红笔迹，保留半透明红染的 UI），再用边缘/亮度定位目标。"""
from pathlib import Path
import numpy as np
import cv2
from PIL import Image

BASE = Path(r"C:/Users/Administrator/.workbuddy/clipboard-images")
TB = BASE / "clipboard-2026-10-28T12-25-30-513Z-fac7224f.png"
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


def comps(mask, min_area=20):
    num, lab = cv2.connectedComponents((mask.astype(np.uint8)) * 255, connectivity=8)
    out = []
    for i in range(1, num):
        ys, xs = np.where(lab == i)
        if len(ys) < min_area:
            continue
        out.append((int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()), int(len(ys))))
    return out


def save_np(a, rect, name):
    x1, y1, x2, y2 = rect
    Image.fromarray(a[y1:y2, x1:x2]).save(OUT / name)


# ===== 任务栏 WeChat（先确认无红，干净裁切） =====
a0 = strict_mask(np.array(Image.open(TB).convert("RGB")))
save_np(a0, (1437, 10, 1486, 53), "nav_taskbar_wechat.png")
print("taskbar wechat saved")

# ===== #2：严格遮红后，用 Canny 边缘找公众号图标（蓝色蝴蝶/花朵形状） =====
a2 = strict_mask(np.array(Image.open(GZH).convert("RGB")))
g2 = cv2.cvtColor(a2, cv2.COLOR_RGB2GRAY)
edges2 = cv2.Canny(g2, 60, 160)
print("=== #2 edge blobs x55-330 y400-510 ===")
for c in sorted(comps(edges2[400:510, 55:330], 15), key=lambda z: -z[4]):
    X1, Y1 = c[0] + 55, c[1] + 400
    print("  x[%d,%d] y[%d,%d] n=%d" % (X1, c[2] + 55, Y1, c[3] + 400, c[4]))
    save_np(a2, (max(0, X1 - 12), max(0, Y1 - 12), c[2] + 55 + 12, c[3] + 400 + 12), "gzh_edge_%d_%d.png" % (X1, Y1))
# 整行视图（含红染 UI）
save_np(a2, (55, 405, 330, 500), "gzh_row_view.png")

# ===== #3：严格遮红后找浅色图标（暗标题栏上的亮图标） =====
a3 = strict_mask(np.array(Image.open(PER).convert("RGB")))
L3 = (a3[:, :, 0] + a3[:, :, 1] + a3[:, :, 2]) // 3
light = (L3 > 175)
print("=== #3 light clusters x780-1180 y15-160 ===")
for c in sorted(comps(light[15:160, 780:1180], 20), key=lambda z: z[0]):
    X1, Y1 = c[0] + 780, c[1] + 15
    print("  x[%d,%d] y[%d,%d] n=%d" % (X1, c[2] + 780, Y1, c[3] + 15, c[4]))
    save_np(a3, (max(0, X1 - 8), max(0, Y1 - 8), c[2] + 780 + 8, c[3] + 15 + 8), "per_light_%d_%d.png" % (X1, Y1))

# ===== #4：赞和收藏文本（已确认在 x198-326 y183-223） =====
a4 = strict_mask(np.array(Image.open(FAV).convert("RGB")))
save_np(a4, (198, 183, 326, 223), "nav_fav.png")
print("fav saved")
print("done")
