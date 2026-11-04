#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""行几何探针：实时检测当前微信画面的列表行。

2026-10-23 之前本文件自带一份饱和度投影实现；模块化后算法只在
vision.detect_rows 一处维护（"改一处漏四处"的教训），这里只做
「截图 → 检测 → 打印 → 存证」，用于人工核对行几何。
"""
import json
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
import vision  # noqa: E402

OUT = SKILL / "out"

got = vision.grab_wechat()
if not got:
    print("拿不到干净的微信截图（窗口不存在/被遮挡/空白）")
    sys.exit(6)
img, rect, _ = got
rows = vision.detect_rows(img)
print("窗口 rect=%s 尺寸=%s" % (rect, img.size))
print("检出 %d 行:" % len(rows))
for i, r in enumerate(rows):
    print("   #%02d y=%4d..%4d center=%d account_box=%s click=%s"
          % (i, r["y1"], r["y2"], r["center"], r["account_box"], r["click_point"]))
if rows:
    ref = vision.draw_boxes(img, [tuple(r["account_box"]) + ("#%d" % i,)
                                  for i, r in enumerate(rows)])
    vision.save(ref, OUT / "wx-rows-probe.png")
    print("带框选参考图 → out/wx-rows-probe.png")
    (OUT / "wx-rows.json").write_text(json.dumps(
        {"rect": rect, "w": img.width, "h": img.height, "thumb_col": "auto",
         "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("已写 out/wx-rows.json")
else:
    # 没检出行就写文件，会把上一次的校准几何覆盖成空列表——scout 的
    # baked 兜底会直接失效。宁可不写，保留旧文件并说清楚。
    print("未检出任何行：不写 out/wx-rows.json（保留原有文件）。"
          "若当前不在文章列表页，属正常；若在列表页还检不出，"
          "请把 out/wx-rows-probe.png 发人工核对。")
