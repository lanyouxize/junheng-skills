#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分析 4 张用户截图，精确锁定导航模板裁切区域（仅分析，不改写生产代码）。"""
from pathlib import Path
import numpy as np
from PIL import Image

BASE = Path(r"C:/Users/Administrator/.workbuddy/clipboard-images")
TB = BASE / "clipboard-2026-10-28T12-25-30-513Z-fac7224f.png"
GZH = BASE / "clipboard-2026-10-28T12-25-30-514Z-1a33eea1.jpg"
PER = BASE / "clipboard-2026-10-28T12-25-30-515Z-51ebf955.jpg"
FAV = BASE / "clipboard-2026-10-28T12-25-30-515Z-2696ec17.png"


def load(p):
    return np.array(Image.open(p).convert("RGB"))


def green_blobs(a, thresh=200):
    r, g, b = a[:, :, 0].astype(int), a[:, :, 1].astype(int), a[:, :, 2].astype(int)
    mask = (g > 140) & (r < 90) & (b < 140) & (g - r > 60) & (g - b > 40)
    ys, xs = np.where(mask)
    print("  green pixel count:", int(mask.sum()))
    if mask.sum() == 0:
        return
    # 按 x 列聚类打印若干显著 run（连续绿色列区间）
    cols = np.where(mask.any(axis=0))[0]
    if len(cols):
        runs = []
        s = cols[0]; p = cols[0]
        for c in cols[1:]:
            if c - p <= 3:
                p = c
            else:
                runs.append((int(s), int(p), int(mask[:, s:p + 1].sum())))
                s = c; p = c
        runs.append((int(s), int(p), int(mask[:, s:p + 1].sum())))
        # 只打印像素较多的 run（>=30）
        big = [r_ for r_ in runs if r_[2] >= 30]
        print("  green horizontal runs (x1,x2,count):")
        for r_ in sorted(big, key=lambda z: -z[2])[:12]:
            # y 范围
            x1, x2, _ = r_
            sub = mask[:, x1:x2 + 1]
            ys2 = np.where(sub.any(axis=1))[0]
            print("    x[%d,%d] y[%d,%d] count=%d" % (x1, x2, int(ys2.min()), int(ys2.max()), int(sub.sum())))


def red_count(a, rect):
    x1, y1, x2, y2 = rect
    sub = a[y1:y2, x1:x2]
    r, g, b = sub[:, :, 0].astype(int), sub[:, :, 1].astype(int), sub[:, :, 2].astype(int)
    red = (r > 120) & (r - g > 50) & (r - b > 50)
    return int(red.sum())


print("=== TASKBAR (WeChat green logo) ===")
green_blobs(load(TB))

print("\n=== GZH crop proposal x[70,215] y[425,490] red check ===")
print("  red px:", red_count(load(GZH), (70, 425, 215, 490)))

print("\n=== PERSON crop proposal x[1020,1065] y[45,85] red check ===")
print("  red px:", red_count(load(PER), (1020, 1065, 45, 85) if False else (1020, 45, 1065, 85)))

print("\n=== FAV crop proposal x[150,235] y[118,146] red check ===")
print("  red px:", red_count(load(FAV), (150, 118, 235, 146)))
