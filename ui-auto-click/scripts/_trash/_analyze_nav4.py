#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自定位 #2/#3/#4 的候选元素并保存裁切图，供视觉核对。"""
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


def comps(mask, min_area=20):
    num, lab = cv2.connectedComponents((mask.astype(np.uint8)) * 255, connectivity=8)
    out = []
    for i in range(1, num):
        ys, xs = np.where(lab == i)
        if len(ys) < min_area:
            continue
        out.append((int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()), int(len(ys))))
    return out


def save(im_path, rect, name):
    x1, y1, x2, y2 = rect
    Image.open(im_path).convert("RGB").crop((x1, y1, x2, y2)).save(OUT / name)


# ---------- #2：左聊天列表里的蓝色「公众号」图标 ----------
a = np.array(Image.open(GZH).convert("RGB")).astype(int)
r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
blue = (b > 110) & (b - r > 35) & (b - g > 10) & (r < 170) & (g < 200)
blue &= (a[:, :, 1] > 40)
print("=== #2 blue blobs in list x55-330 y380-560 ===")
sub = blue[380:560, 55:330]
for c in sorted(comps(sub, 30), key=lambda z: z[1]):
    x1, y1, x2, y2, n = c
    X1, Y1 = x1 + 55, y1 + 380
    print("  x[%d,%d] y[%d,%d] n=%d" % (X1, x2 + 55, Y1, y2 + 380, n))
    save(GZH, (max(0, X1 - 6), max(0, Y1 - 6), x2 + 55 + 6, y2 + 380 + 6), "gzh_blue_%d_%d.png" % (X1, Y1))

# ---------- #3：顶部右侧工具栏里的非背景图标（小人像等） ----------
a3 = np.array(Image.open(PER).convert("RGB")).astype(int)
r3, g3, b3 = a3[:, :, 0], a3[:, :, 1], a3[:, :, 2]
L3 = (r3 + g3 + b3) // 3
notbg = (L3 < 205) & ((np.abs(r3 - g3) > 18) | (np.abs(g3 - b3) > 18) | (np.abs(r3 - b3) > 18))
print("\n=== #3 non-bg blobs in toolbar y30-95 x880-1180 ===")
sub3 = notbg[30:95, 880:1180]
for c in sorted(comps(sub3, 25), key=lambda z: z[0]):
    x1, y1, x2, y2, n = c
    X1, Y1 = x1 + 880, y1 + 30
    print("  x[%d,%d] y[%d,%d] n=%d" % (X1, x2 + 880, Y1, y2 + 30, n))
    save(PER, (max(0, X1 - 5), max(0, Y1 - 5), x2 + 880 + 5, y2 + 30 + 5), "per_ico_%d_%d.png" % (X1, Y1))

# ---------- #4：左侧栏灰色菜单文本行 ----------
a4 = np.array(Image.open(FAV).convert("RGB")).astype(int)
r4, g4, b4 = a4[:, :, 0], a4[:, :, 1], a4[:, :, 2]
L4 = (r4 + g4 + b4) // 3
sat = (np.abs(r4 - g4) + np.abs(g4 - b4) + np.abs(r4 - b4)) // 3
gray_text = (L4 > 90) & (L4 < 215) & (sat < 35)
print("\n=== #4 gray-text rows x90-320 y60-320 ===")
col = gray_text[:, 90:320]
clusters = []
ys_rows = [y for y in range(col.shape[0]) if int(col[y].sum()) >= 6]
if ys_rows:
    s = p = ys_rows[0]
    for y in ys_rows[1:]:
        if y - p <= 2:
            p = y
        else:
            clusters.append((s, p)); s = y; p = y
    clusters.append((s, p))
clusters = [(s, p) for s, p in clusters if p - s >= 3]
for i, (s, p) in enumerate(clusters[:14]):
    xs = np.where(col[s:p + 1].any(axis=0))[0]
    x1, x2 = int(xs.min()) + 90, int(xs.max()) + 90
    print("  row#%d y[%d,%d] x[%d,%d]" % (i, s, p, x1, x2))
    save(FAV, (max(0, x1 - 8), s - 5, x2 + 8, p + 6), "fav_row_%02d.png" % i)
print("done")
