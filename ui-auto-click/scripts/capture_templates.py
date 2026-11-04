#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校准：从当前微信画面固化成模板 + 行几何（templates/ 与 out/wx-rows.json）。

用法（微信必须停在「赞和收藏」页、且不被其他窗口遮挡）：
    python scripts/capture_templates.py            # 校准 + 证伪测试
    python scripts/capture_templates.py --verify   # 只验证已有模板

为什么要证伪测试
----------------
模板错了，下游所有判断都会假阳性。2026-10-23 实测踩过：按错误坐标截的
"页面标题"模板实际框到的是 Windows 设置的搜索框，导致遮挡检测对
"干净微信"和"被设置窗口盖住的微信"都返回 1.0 分 —— 检测器彻底失效。

判据是**判别余量**，不是绝对分数：
    目标页得分 ≥ 0.80   且   每个无关画面得分 < 0.80   且   目标页 − 最差无关画面 ≥ 0.25
为什么不用"无关画面 ≤ 0.50"这种绝对上限：2026-10-23 实测 tab-all 对微信
**聊天列表页**能打到 0.533（最容易被混淆的错页），按 0.50 上限会被误杀；
但它在工作阈值 0.80 处仍有 0.267 余量，完全可判别。真正要抓的是
"目标页和无关画面分数贴在一起"的模板（历史坏模板 page-title 两者只差 0.0001，
sidebar-favorites 对设置窗口 0.899，都是余量不足）。

2026-10-23 增补：负面样本默认取两个——
  ① out/wx-negative.png      微信被别的窗口压住时的画面（原有）；
  ② out/wx-negative-chat.png **微信聊天列表页**（新增，见上）。
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
import vision  # noqa: E402
from PIL import Image  # noqa: E402

TPL = SKILL / "templates"
OUT = SKILL / "out"

# 布局按窗口宽高归一化（换分辨率仍可用）。数值来自 2026-10-23 实测 1649x1518。
# ⚠ 这些是**经验值**，校准后必须人工核对；换微信版本要重新校准。
REGIONS = {
    "sidebar-favorites": (0.000, 0.075, 0.140, 0.118),
    "page-title": (0.030, 0.008, 0.200, 0.050),
    "tab-all": (0.150, 0.072, 0.220, 0.112),
}
MIN_TARGET, MAX_NEGATIVE, MIN_MARGIN = 0.80, 0.80, 0.25
# 证伪测试用的无关画面（按顺序取存在的）
NEGATIVE_SAMPLES = ("wx-negative.png", "wx-negative-chat.png")


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def load_negatives() -> list[tuple[str, Image.Image]]:
    """加载负面样本；损坏/不可读的文件跳过并告警，不让校准整体崩掉。"""
    out = []
    for name in NEGATIVE_SAMPLES:
        p = OUT / name
        if not p.is_file():
            continue
        try:
            out.append((name, Image.open(str(p))))
        except Exception as e:
            print("警告：负面样本 %s 打不开（%s），已跳过" % (p, e))
    return out


def verify(templates: dict, target, negatives) -> list[dict]:
    """证伪测试：目标页要高分，每个无关画面都要明显低分（判别余量 ≥0.25）。"""
    report = []
    for name, tpl in templates.items():
        s_t, _ = (vision.best_match(target, tpl) if target else (0.0, None))
        negs = []
        for nname, nimg in negatives:
            s, _ = vision.best_match(nimg, tpl)
            negs.append({"sample": nname, "score": round(s, 4)})
        worst = max((n["score"] for n in negs), default=0.0)
        margin = round(s_t - worst, 4)
        ok = (s_t >= MIN_TARGET and worst < MAX_NEGATIVE and margin >= MIN_MARGIN)
        report.append({"name": name, "target": round(s_t, 4),
                       "negatives": negs, "worst_negative": round(worst, 4),
                       "margin": margin, "ok": ok})
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true", help="只验证已有模板，不重新截")
    args = ap.parse_args()

    if args.verify:
        negatives = load_negatives()
        tpls = {p.stem: Image.open(str(p)) for p in sorted(TPL.glob("*.png"))}
        if not tpls:
            print("templates/ 里没有模板")
            return 6
        if not negatives:
            print("没有负面样本（%s），证伪测试只能验一半"
                  % ", ".join(NEGATIVE_SAMPLES))
        for r in verify(tpls, None, negatives):
            neg_txt = " ".join("%s=%.4f" % (n["sample"], n["score"])
                               for n in r["negatives"]) or "（无负面样本）"
            # verify 模式没有目标页，只能查"会不会在错页上误触发"（工作阈值 0.80）
            safe = r["worst_negative"] < MIN_TARGET
            print("  %-20s %s %s" % (r["name"], neg_txt,
                                     "OK" if safe else "FAIL（会误触发）"))
        print("注：完整判别余量测试需要目标页在场，跑不带 --verify 的校准。")
        return 0

    # ---- 拿一张干净的微信截图（统一入口，见 vision.grab_wechat）----
    got = vision.grab_wechat()
    if not got:
        print("拿不到干净的微信截图：微信没开 / 被最小化 / 被其他窗口完全盖住")
        return 6
    img, rect, _win = got
    W, H = img.size
    print("微信窗口 %dxx%d rect=%s" % (W, H, rect))

    # 备份旧模板
    if TPL.is_dir() and any(TPL.iterdir()):
        bak = OUT / ("templates-bak-%s" % now())
        shutil.copytree(TPL, bak)
        print("旧模板已备份 → %s" % bak)
    TPL.mkdir(exist_ok=True)

    # ---- 1) UI 模板（先裁样、证伪过了才落库）----
    evidence = OUT / ("calib-crops-%s" % now())
    evidence.mkdir(parents=True, exist_ok=True)
    tpls = {}
    for name, (a, b, c, d) in REGIONS.items():
        box = (int(W * a), int(H * b), int(W * c), int(H * d))
        crop = vision.crop(img, box)
        tpls[name] = crop
        vision.save(crop, evidence / ("%s.png" % name))
        print("  候选模板 %-18s box=%s 尺寸=%s → %s"
              % (name, box, crop.size, evidence / ("%s.png" % name)))

    negatives = load_negatives()
    if not negatives:
        print("\n提示：没有负面样本，跳过证伪测试。")
        print("      建议在被其他窗口压住时跑一次 vision.py shot out/wx-negative.png，")
        print("      并在微信聊天列表页跑一次 vision.py shot out/wx-negative-chat.png，"
              "再 --verify。")
    else:
        print("\n证伪测试（目标页 ≥%.2f、无关画面 <%.2f、判别余量 ≥%.2f 才通过）:"
              % (MIN_TARGET, MAX_NEGATIVE, MIN_MARGIN))
        for r in verify(tpls, img, negatives):
            neg_txt = " ".join("%s=%.4f" % (n["sample"], n["score"])
                               for n in r["negatives"])
            print("   %-20s target=%.4f %s 余量=%.4f %s"
                  % (r["name"], r["target"], neg_txt, r["margin"],
                     "OK" if r["ok"] else "FAIL"))
            if r["ok"]:
                vision.save(tpls[r["name"]], TPL / ("%s.png" % r["name"]))
            else:
                print("       ↑ 该模板不可信，不写入 templates/（仅留证据）")
                (TPL / ("%s.png" % r["name"])).unlink(missing_ok=True)

    # ---- 2) 行几何（运行时检测逻辑在 vision.detect_rows，这里只落盘）----
    rows = vision.detect_rows(img)
    print("\n行几何：检出 %d 行" % len(rows))
    for i, r in enumerate(rows[:12]):
        print("   #%02d y=%d..%d center=%d account_box=%s"
              % (i, r["y1"], r["y2"], r["center"], r["account_box"]))
    (OUT / "wx-rows.json").write_text(json.dumps(
        {"rect": rect, "w": W, "h": H, "thumb_col": "auto",
         "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---- 3) 参考图（带行框选标注，人工核对用）----
    boxes = [tuple(r["account_box"]) + ("#%d" % i,)
             for i, r in enumerate(rows[:12])]
    ref = vision.draw_boxes(img, boxes)
    vision.save(ref, OUT / "wx-reference.png")
    print("\n整页参考图（带行框选）→ out/wx-reference.png")
    print("请人工核对：① 模板框选是否正确 ② account_box 是否覆盖公众号名文字。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
