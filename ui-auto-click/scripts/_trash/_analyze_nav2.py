#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精细分析 + 生成调试裁切图，供人工/视觉核对模板区域。"""
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


def mask_red(img: Image.Image) -> Image.Image:
    a = np.array(img.convert("RGB"))
    r, g, b = a[:, :, 0].astype(int), a[:, :, 1].astype(int), a[:, :, 2].astype(int)
    red = (r > 120) & (r - g > 50) & (r - b > 50)
    a[red] = (250, 250, 250)
    return Image.fromarray(a)


def save_crop(src, rect, name, do_mask=False):
    x1, y1, x2, y2 = rect
    im = Image.open(src).convert("RGB").crop((x1, y1, x2, y2))
    if do_mask:
        im = mask_red(im)
    p = OUT / name
    im.save(p)
    return p


# ---- 任务栏：绿色连通域 ----
a = np.array(Image.open(TB).convert("RGB"))
r, g, b = a[:, :, 0].astype(int), a[:, :, 1].astype(int), a[:, :, 2].astype(int)
green = ((g > 140) & (r < 90) & (b < 140) & (g - r > 60) & (g - b > 40)).astype(np.uint8) * 255
num, lab = cv2.connectedComponents(green, connectivity=8)
print("taskbar green components:", num - 1)
comps = []
for i in range(1, num):
    ys, xs = np.where(lab == i)
    if len(ys) < 30:
        continue
    x1, x2, y1, y2 = xs.min(), xs.max(), ys.min(), ys.max()
    comps.append((int(x1), int(y1), int(x2), int(y2), int(len(ys))))
comps.sort(key=lambda z: z[0])
for c in comps:
    x1, y1, x2, y2, n = c
    print("  blob x[%d,%d] y[%d,%d] n=%d" % (x1, x2, y1, y2, n))
    save_crop(TB, (max(0, x1 - 4), max(0, y1 - 4), x2 + 5, y2 + 5), "tb_blob_%d_%d.png" % (x1, x2))

# ---- GZH：尝试多个裁切区域，报红像素数，保存遮红版 ----
gzh_img = np.array(Image.open(GZH).convert("RGB"))
for rect in [(70, 425, 215, 490), (68, 432, 210, 486), (120, 438, 210, 472), (100, 434, 210, 484)]:
    x1, y1, x2, y2 = rect
    sub = gzh_img[y1:y2, x1:x2]
    sr, sg, sb = sub[:, :, 0].astype(int), sub[:, :, 1].astype(int), sub[:, :, 2].astype(int)
    red = (sr > 120) & (sr - sg > 50) & (sr - sb > 50)
    print("  GZH rect %s red=%d" % (rect, int(red.sum())))
save_crop(GZH, (68, 432, 210, 486), "gzh_masked.png", do_mask=True)
save_crop(GZH, (120, 438, 210, 472), "gzh_text.png", do_mask=True)

# ---- PERSON / FAV：直接裁切（已验证红=0） ----
save_crop(PER, (1020, 45, 1065, 85), "person.png")
save_crop(FAV, (150, 118, 235, 146), "fav.png")
print("done; debug images in", OUT)
