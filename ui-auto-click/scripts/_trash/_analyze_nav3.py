#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用像素分析自定位 #3 工具栏小人像 与 #4 左侧栏「赞和收藏」文本行，并复核 #2。"""
from pathlib import Path
import numpy as np
import cv2
from PIL import Image

BASE = Path(r"C:/Users/Administrator/.workbuddy/clipboard-images")
PER = BASE / "clipboard-2026-10-28T12-25-30-515Z-51ebf955.jpg"
FAV = BASE / "clipboard-2026-10-28T12-25-30-515Z-2696ec17.png"
GZH = BASE / "clipboard-2026-10-28T12-25-30-514Z-1a33eea1.jpg"
OUT = Path(r"C:/Users/Administrator/.workbuddy/skills/ui-auto-click/out/nav-debug")
OUT.mkdir(parents=True, exist_ok=True)


def comps(a, mask, min_area=25):
    num, lab = cv2.connectedComponents((mask.astype(np.uint8)) * 255, connectivity=8)
    out = []
    for i in range(1, num):
        ys, xs = np.where(lab == i)
        if len(ys) < min_area:
            continue
        out.append((int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()), int(len(ys))))
    return out


# ---------- #3 工具栏：中灰细线图标（小人像/铃铛/搜索） ----------
a = np.array(Image.open(PER).convert("RGB")).astype(int)
r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
gray = (np.abs(r - g) < 25) & (np.abs(g - b) < 25)
L = (r + g + b) // 3
line = gray & (L > 40) & (L < 180)
print("=== #3 toolbar line-icons (y 35-100, x 850-1150) ===")
m = line & (a.shape[0] > 0)  # placeholder
sub = line[35:100, 850:1150]
for c in sorted(comps(sub, sub), key=lambda z: z[0]):
    x1, y1, x2, y2, n = c
    print("  x[%d,%d] y[%d,%d] n=%d" % (x1 + 850, x2 + 850, y1 + 35, y2 + 35, n))
# 保存嫌疑人像区域（最右的一组）
Image.open(PER).convert("RGB").crop((1020, 40, 1070, 95)).save(OUT / "per_region.png")


# ---------- #4 左栏文本行聚类 ----------
a4 = np.array(Image.open(FAV).convert("RGB")).astype(int)
r4, g4, b4 = a4[:, :, 0], a4[:, :, 1], a4[:, :, 2]
L4 = (r4 + g4 + b4) // 3
dark = (L4 < 130)  # 深色文字/图标
# 只取左栏 x 90-300
col = dark[:, 90:300]
rows = []
for y in range(col.shape[0]):
    cnt = int(col[y].sum())
    if cnt >= 8:
        rows.append(y)
print("\n=== #4 left-sidebar dark rows (x90-300) ===")
# 聚类连续行
clusters = []
if rows:
    s = rows[0]; p = rows[0]
    for y in rows[1:]:
        if y - p <= 2:
            p = y
        else:
            clusters.append((s, p)); s = y; p = y
    clusters.append((s, p))
clusters = [(s, p) for s, p in clusters if (p - s) >= 3]
for i, (s, p) in enumerate(clusters[:12]):
    # x 范围
    sub = col[s:p + 1]
    xs = np.where(sub.any(axis=0))[0]
    print("  row#%d y[%d,%d] x[%d,%d]" % (i, s, p, int(xs.min()) + 90, int(xs.max()) + 90))
# 保存第 3 行（按 vision 顺序：关注/合集/赞和收藏 第3个）候选
if len(clusters) >= 3:
    s, p = clusters[2]
    xs = np.where(col[s:p + 1].any(axis=0))[0]
    x1, x2 = int(xs.min()) + 90, int(xs.max()) + 90
    Image.open(FAV).convert("RGB").crop((max(0, x1 - 6), s - 4, x2 + 6, p + 5)).save(OUT / "fav_row3.png")
    print("  saved fav_row3 from y[%d,%d] x[%d,%d]" % (s, p, x1, x2))


# ---------- #2 公众号区域复核 ----------
a2 = np.array(Image.open(GZH).convert("RGB")).astype(int)
r2, g2, b2 = a2[:, :, 0], a2[:, :, 1], a2[:, :, 2]
red = (r2 > 120) & (r2 - g2 > 50) & (r2 - b2 > 50)
print("\n=== #2 公众号 region (73,423)-(190,474) red check ===")
print("  red px:", int(red[423:474, 73:190].sum()))
# green highlight check
green = (g2 > 120) & (r2 < 150) & (b2 < 150) & (g2 - r2 > 20)
print("  green px in row band y423-474:", int(green[423:474, :].sum()))
Image.open(GZH).convert("RGB").crop((73, 423, 190, 474)).save(OUT / "gzh_region.png")
print("done")
