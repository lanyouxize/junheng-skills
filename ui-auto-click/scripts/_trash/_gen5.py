#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
import numpy as np
from PIL import Image

BASE = Path(r"C:/Users/Administrator/.workbuddy/clipboard-images")
GZH = BASE / "clipboard-2026-10-28T12-25-30-514Z-1a33eea1.jpg"
OUT = Path(r"C:/Users/Administrator/.workbuddy/skills/ui-auto-click/out/nav-debug")
OUT.mkdir(parents=True, exist_ok=True)


def mask(a):
    r, g, b = a[:, :, 0].astype(int), a[:, :, 1].astype(int), a[:, :, 2].astype(int)
    # 只去纯红/橙红笔迹（g、b 较低），保留半透明红染 UI（g、b 偏高）
    stroke = (r > 200) & (r - g > 80) & (g < 160) & (r - b > 60)
    a[stroke] = (248, 248, 248)
    return a


a2 = mask(np.array(Image.open(GZH).convert("RGB")))
Image.fromarray(a2[426:494, 66:208]).save(OUT / "cand_gzh3.png")
# 也尝试稍宽一点，确认文字/图标位置
Image.fromarray(a2[420:500, 60:230]).save(OUT / "cand_gzh_wide.png")
print("done")
