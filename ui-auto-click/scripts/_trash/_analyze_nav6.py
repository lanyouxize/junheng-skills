#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""先遮红，再用颜色/形状定位 #2/#3/#4 三个目标元素。"""
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


def mask_red_np(a):
    r, g, b = a[:, :, 0].astype(int), a[:, :, 1].astype(int), a[:, :, 2].astype(int)
    red = (r > 120) & (r - g > 50) & (r - b > 50)
    a[red] = (248, 248, 248)
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


# ===== #2：遮红后找蓝色「公众号」图标 =====
a2 = mask_red_np(np.array(Image.open(GZH).convert("RGB")))
r2, g2, b2 = a2[:, :, 0].astype(int), a2[:, :, 1].astype(int), a2[:, :, 2].astype(int)
blue = (b2 > 110) & (b2 - r2 > 30) & (r2 < 170) & (g2 < 200)
print("=== #2 blue blobs x55-330 y380-560 (after red mask) ===")
sub = blue[380:560, 55:330]
for c in sorted(comps(sub, 30), key=lambda z: z[1]):
    X1, Y1 = c[0] + 55, c[1] + 380
    print("  x[%d,%d] y[%d,%d] n=%d" % (X1, c[2] + 55, Y1, c[3] + 380, c[4]))
    save_np(a2, (max(0, X1 - 8), max(0, Y1 - 8), c[2] + 55 + 8, c[3] + 380 + 8), "gzh_blue2_%d_%d.png" % (X1, Y1))

# ===== #3：遮红后找顶部右侧工具栏图标（偏离背景者） =====
a3 = mask_red_np(np.array(Image.open(PER).convert("RGB")))
L3 = (a3[:, :, 0] + a3[:, :, 1] + a3[:, :, 2]) // 3
reg = L3[25:100, 870:1180]
bg = int(np.median(reg))
print("\n=== #3 toolbar bg median L=%d ; deviating blobs x870-1180 y25-100 ===" % bg)
dev = np.abs(L3[25:100, 870:1180].astype(int) - bg) > 45
for c in sorted(comps(dev, 25), key=lambda z: z[0]):
    X1, Y1 = c[0] + 870, c[1] + 25
    print("  x[%d,%d] y[%d,%d] n=%d" % (X1, c[2] + 870, Y1, c[3] + 25, c[4]))
    save_np(a3, (max(0, X1 - 6), max(0, Y1 - 6), c[2] + 870 + 6, c[3] + 25 + 6), "per_ico2_%d_%d.png" % (X1, Y1))

# ===== #4：遮红后确认选中项(赞和收藏)区域，并保存文本裁切 =====
a4 = mask_red_np(np.array(Image.open(FAV).convert("RGB")))
print("\n=== #4 selected-item band y[176,237] x[152,329] -> 保存赞和收藏文本候选 ===")
save_np(a4, (148, 180, 240, 224), "fav_text.png")
# 也保存整条选中项（含背景）供参考
save_np(a4, (148, 176, 330, 238), "fav_sel.png")
print("done")
