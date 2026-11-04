#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
import numpy as np
import cv2
from PIL import Image

BASE = Path(r"C:/Users/Administrator/.workbuddy/clipboard-images")
GZH = BASE / "clipboard-2026-10-28T12-25-30-514Z-1a33eea1.jpg"
OUT = Path(r"C:/Users/Administrator/.workbuddy/skills/ui-auto-click/out/nav-debug")
OUT.mkdir(parents=True, exist_ok=True)


def red_comps(a, min_area=40):
    r, g, b = a[:, :, 0].astype(int), a[:, :, 1].astype(int), a[:, :, 2].astype(int)
    red = (r > 180) & (r - g > 50) & (r - b > 50)
    num, lab = cv2.connectedComponents((red.astype(np.uint8)) * 255, connectivity=8)
    out = []
    for i in range(1, num):
        ys, xs = np.where(lab == i)
        if len(ys) < min_area:
            continue
        out.append((int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()), int(len(ys))))
    return out


a2 = np.array(Image.open(GZH).convert("RGB"))
comps = sorted(red_comps(a2), key=lambda z: -z[4])
print("=== #2 red components ===")
for c in comps[:12]:
    X1, Y1, X2, Y2, n = c
    cx, cy = (X1 + X2) // 2, (Y1 + Y2) // 2
    print("  x[%d,%d] y[%d,%d] n=%d center=(%d,%d)" % (X1, X2, Y1, Y2, n, cx, cy))
# 取最大红圈（公众号标注）-> 裁剪整行查看
big = max(comps, key=lambda z: z[4])
X1, Y1, X2, Y2, _ = big
cx, cy = (X1 + X2) // 2, (Y1 + Y2) // 2
print("largest red circle center:", (cx, cy), "bbox y[%d,%d]" % (Y1, Y2))
# 裁整行（含红圈内全部内容，不遮红，原样查看）
Image.open(GZH).convert("RGB").crop((60, Y1 - 8, 330, Y2 + 8)).save(OUT / "gzh_redrow_raw.png")
print("saved gzh_redrow_raw")
