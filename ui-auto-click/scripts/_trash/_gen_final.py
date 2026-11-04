#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 4 个正式导航模板到 SKILL/templates/，并复制一份到 nav-debug 供核对。"""
from pathlib import Path
import numpy as np
from PIL import Image

BASE = Path(r"C:/Users/Administrator/.workbuddy/clipboard-images")
TB = BASE / "clipboard-2026-10-28T12-25-30-513Z-fac7224f.png"
GZH = BASE / "clipboard-2026-10-28T12-25-30-514Z-1a33eea1.jpg"
PER = BASE / "clipboard-2026-10-28T12-25-30-515Z-51ebf955.jpg"
FAV = BASE / "clipboard-2026-10-28T12-25-30-515Z-2696ec17.png"
SKILL = Path(r"C:/Users/Administrator/.workbuddy/skills/ui-auto-click")
TPL = SKILL / "templates"
DBG = SKILL / "out/nav-debug"
TPL.mkdir(parents=True, exist_ok=True)
DBG.mkdir(parents=True, exist_ok=True)


def mask_stroke(a):
    """去除纯红/橙红笔迹，保留半透明红染 UI 与原始颜色。"""
    r, g, b = a[:, :, 0].astype(int), a[:, :, 1].astype(int), a[:, :, 2].astype(int)
    stroke = (r > 200) & (r - g > 80) & (g < 160) & (r - b > 60)
    a[stroke] = (248, 248, 248)
    return a


def save(src, rect, name):
    a = mask_stroke(np.array(Image.open(src).convert("RGB")))
    x1, y1, x2, y2 = rect
    im = Image.fromarray(a[y1:y2, x1:x2])
    im.save(TPL / name)
    im.save(DBG / name)
    print("saved", name, "size", im.size)


# 1) 任务栏微信图标（绿色双气泡），收紧避免红笔迹
save(TB, (1442, 15, 1481, 49), "nav-taskbar-wechat.png")
# 2) 公众号 row：图标+文字（绿底选中态；遮红笔迹）
save(GZH, (66, 628, 205, 692), "nav-gzh.png")
# 3) 个人中心小人像（红圈中心 1524,89 周围）
save(PER, (1502, 67, 1546, 111), "nav-person.png")
# 4) 赞和收藏 文字（浅灰选中态）
save(FAV, (180, 178, 342, 228), "nav-fav.png")
print("ALL DONE")
