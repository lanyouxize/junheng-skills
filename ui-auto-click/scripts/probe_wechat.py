#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实机探测微信 PC 客户端控件树 —— 为「个人中心 → 赞和收藏」自动点击流程取证。

只读，不动任何控件。用法：

    python scripts/probe_wechat.py                 # 顶层窗口 + 主窗口树摘要
    python scripts/probe_wechat.py --depth 6       # 更深
    python scripts/probe_wechat.py --grep 赞和收藏  # 全树搜文本
    python scripts/probe_wechat.py --full          # 不截断（可能很长）

为什么要先探：微信 PC 端是自绘 UI，UIA 能否读到控件没有保证；
在读到之前，任何 auto_id 都是猜。判据只信实机输出。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

MAX_NODES = 4000


def dump(ctrl, depth: int, max_depth: int, out: list, seen: list) -> None:
    if len(out) > MAX_NODES:
        out.append("...(超过 %d 节点，已截断)" % MAX_NODES)
        return
    try:
        info = ctrl.element_info
        at = info.automation_id or ""
        ct = info.control_type or ""
        nm = info.name or ""
        cls = info.class_name or ""
    except Exception as e:
        out.append("  " * depth + "<读取失败 %s>" % type(e).__name__)
        return
    txt = (nm or "").replace("\r", " ").replace("\n", " ")
    if len(txt) > 60:
        txt = txt[:60] + "…"
    line = "  " * depth + "[%s] id=%r cls=%r name=%r" % (ct, at, cls, txt)
    out.append(line)
    if depth >= max_depth:
        return
    try:
        kids = ctrl.children()
    except Exception:
        return
    for k in kids:
        dump(k, depth + 1, max_depth, out, seen)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--depth", type=int, default=4)
    ap.add_argument("--grep", default="", help="在全树里搜这段文本，命中即打印路径")
    ap.add_argument("--full", action="store_true", help="不截断节点数")
    ap.add_argument("--backend", default="uia", choices=["uia", "win32"],
                    help="uia=UIA；win32=MSAA。Chromium 系应用两个后端看到的可能完全不同")
    args = ap.parse_args()

    from pywinauto import Desktop
    print("== 顶层窗口（backend=%s）==" % args.backend)
    roots = Desktop(backend=args.backend).windows()
    print("共 %d 个顶层窗口" % len(roots))
    for w in roots:
        try:
            t = (w.window_text() or "").replace("\n", " ")
            print("  hwnd=%s cls=%r title=%r" % (w.handle, w.class_name(), t[:50]))
        except Exception as e:
            print("  <读失败 %s>" % type(e).__name__)

    # 找微信主窗口：标题含「微信」
    main = None
    for w in roots:
        try:
            if "微信" in (w.window_text() or ""):
                main = w
                break
        except Exception:
            continue
    if main is None:
        print("\n没找到标题含「微信」的顶层窗口 —— 微信可能没开或标题不同。")
        return 6

    print("\n== 主窗口控件树（depth=%d）==" % args.depth)
    out: list[str] = []
    dump(main, 0, args.depth, out, [])
    text = "\n".join(out)
    if args.grep:
        hits = [l for l in out if args.grep in l]
        print("搜索 %r：命中 %d 行" % (args.grep, len(hits)))
        for l in hits[:40]:
            print(l)
    else:
        print(text if args.full else text[:12000])
        if not args.full and len(text) > 12000:
            print("...（已截断，共 %d 行；要全量加 --full，或 --grep 定位）" % len(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
