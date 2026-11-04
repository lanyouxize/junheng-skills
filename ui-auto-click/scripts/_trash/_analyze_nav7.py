#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""遮红后，#2 找绿色选中行+白色图标/文字；#3 找顶部浅色图标。"""
from pathlib import Path
import numpy as np
import cv2
from PIL import Image

BASE = Path(r"C:/Users/Administrator/.workbuddy/clipboard-images")
GZH = BASE / "clipboard-2026-10-28T12-25-30-514Z-1a33eea1.jpg"
PER = BASE / "clipboard-2026-10-28T12-25-30-515Z-51ebf955.jpg"
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


# ===== #2：遮红后找绿色选中行（公众号） =====
a2 = mask_red_np(np.array(Image.open(GZH).convert("RGB")))
r2, g2, b2 = a2[:, :, 0].astype(int), a2[:, :, 1].astype(int), a2[:, :, 2].astype(int)
green = (g2 > 110) & (g2 - r2 > 12) & (b2 < g2 + 5) & (r2 < 170)
print("=== #2 green px per y in x55-330 y380-560 ===")
for y in range(380, 560):
    c = int(green[y, 55:330].sum())
    if c > 20:
        xs = np.where(green[y, 55:330])[0]
        print("  y=%d green=%4d x[%d,%d]" % (y, c, int(xs.min()) + 55, int(xs.max()) + 55))
# 白色图标/文字（在绿行里偏白）
white = (r2 > 200) & (g2 > 200) & (b2 > 200)
print("=== #2 white blobs x55-330 y380-560 ===")
sub = white[380:560, 55:330]
for c in sorted(comps(sub, 25), key=lambda z: z[3]):
    X1, Y1 = c[0] + 55, c[1] + 380
    print("  x[%d,%d] y[%d,%d] n=%d" % (X1, c[2] + 55, Y1, c[3] + 380, c[4]))
    save_np(a2, (max(0, X1 - 8), max(0, Y1 - 8), c[2] + 55 + 8, c[3] + 380 + 8), "gzh_white_%d_%d.png" % (X1, Y1))

# ===== #3：遮红后找顶部浅色图标（在暗标题栏上的亮图标） =====
a3 = mask_red_np(np.array(Image.open(PER).convert("RGB")))
L3 = (a3[:, :, 0] + a3[:, :, 1] + a3[:, :, 2]) // 3
print("\n=== #3 light-pixel rows x780-1180 y15-160 (L3>165) ===")
for y in range(15, 160):
    row = L3[y, 780:1180]
    c = int((row > 165).sum())
    if c >= 5:
        xs = np.where(row > 165)[0]
        print("  y=%d light=%3d x[%d,%d]" % (y, c, int(xs.min()) + 780, int(xs.max()) + 780))
print("=== #3 dark-pixel rows x780-1180 y15-160 (L3<110) ===")
for y in range(15, 160):
    row = L3[y, 780:1180]
    c = int((row < 110).sum())
    if c >= 5:
        xs = np.where(row < 110)[0]
        print("  y=%d dark=%3d x[%d,%d]" % (y, c, int(xs.min()) + 780, int(xs.max()) + 780))
light = (L3 > 165)
sub = light[15:160, 780:1180]
for c in sorted(comps(sub, 25), key=lambda z: z[0]):
    X1, Y1 = c[0] + 780, c[1] + 15
    print("  LIGHT-cluster x[%d,%d] y[%d,%d] n=%d" % (X1, c[2] + 780, Y1, c[3] + 15, c[4]))
    save_np(a3, (max(0, X1 - 6), max(0, Y1 - 6), c[2] + 780 + 6, c[3] + 15 + 6), "per_light_%d_%d.png" % (X1, Y1))
print("done")
