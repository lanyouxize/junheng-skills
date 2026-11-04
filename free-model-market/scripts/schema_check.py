#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""免费模型超市 · 结构与契约校验（零依赖，仅标准库）

目的：在源头拦截两类静默故障——
  1. 货架 md 缺少必需章节标题（如「## 二、试用额度渠道」），
     导出器会把该区条目并入上一区，造成大批条目误分类（2026-10-28 真实事故）。
  2. 导出 JSON 的契约漂移：provider_count 不符、status 越出枚举、
     section 为空、endpoint 非 http(s)。

只读校验，不改任何文件。退出码：0=通过，1=存在硬错误。

用法：
  python 免费模型超市-schema_check.py
"""
# --- 沙箱容错：强制 UTF-8 输出，避免非 UTF-8 控制台（cp1252/cp936）抛 UnicodeEncodeError ---
try:
    import sys as _sys
    for _stream in (_sys.stdout, _sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
except Exception:
    pass
# --- end 沙箱容错 ---

import json
import re
import sys
from pathlib import Path

# 必需章节（key 为标题片段，label 为人类可读名）
REQUIRED_SECTIONS = [
    ("一、永久免费", "永久免费渠道"),
    ("二、试用额度", "试用额度渠道"),
    ("三、已停服", "已停服 / 退出免费层"),
]

ALLOWED_STATUS = {"active", "degraded", "expired", "unverified", "unknown"}

MD_CANDIDATES = ["免费模型超市-model-catalog.md", "references/model-catalog.md"]
JSON_CANDIDATES = ["references/model-catalog.json"]

# 🔴 路径不得依赖 cwd（2026-10-31 沙箱评测教训）：评测机可能从任意目录调用脚本。
# 以脚本自身位置为基址，同时保留 cwd 相对路径作为回退。
_BASES = [Path(__file__).resolve().parent, Path(__file__).resolve().parent.parent]


def find_first(paths):
    seen = []
    for base in _BASES + [Path.cwd()]:
        for p in paths:
            cand = (base / p)
            seen.append(str(cand))
            if cand.exists():
                return cand.resolve()
    return None


def check_md(md: Path):
    errs = []
    heads = [ln.strip() for ln in md.read_text(encoding="utf-8").splitlines() if ln.startswith("## ")]
    head_text = "\n".join(heads)
    for key, label in REQUIRED_SECTIONS:
        if key not in head_text:
            errs.append(
                f"md 缺少章节标题「## {key}…」（{label}）——"
                f"导出会把该区条目并入上一区，导致静默误分类"
            )
    return heads, errs


def check_json(js: dict):
    errs, warns = [], []
    provs = js.get("providers", []) or []
    pc = js.get("provider_count")
    if pc is not None and pc != len(provs):
        errs.append(f"provider_count={pc} 与 providers 实际 {len(provs)} 不一致")
    if not provs:
        errs.append("providers 为空")
    for i, p in enumerate(provs, 1):
        name = p.get("name")
        if not isinstance(name, str) or not name.strip():
            errs.append(f"#{i} name 为空")
            name = f"#{i}"
        st = (p.get("status") or "").strip().lower()
        if st not in ALLOWED_STATUS:
            errs.append(f"#{i} {name} status={st!r} 不在枚举 {sorted(ALLOWED_STATUS)}")
        sec = p.get("section") or ""
        if not sec.strip():
            errs.append(f"#{i} {name} section 为空")
        eps = p.get("endpoints")
        if eps is not None and not isinstance(eps, list):
            errs.append(f"#{i} {name} endpoints 非列表")
            eps = []
        for u in (eps or []):
            if not re.match(r"^https?://", str(u)):
                errs.append(f"#{i} {name} endpoint 非 http(s): {u}")
        if st in ("active", "degraded") and "永久免费" in sec and not eps:
            warns.append(f"#{i} {name} 位于永久免费区但未登记端点")
    return provs, errs, warns


def main():
    md = find_first(MD_CANDIDATES)
    js = find_first(JSON_CANDIDATES)
    errs, warns, heads, provs = [], [], [], []

    if not md:
        errs.append("找不到货架 md（已试：" + " / ".join(MD_CANDIDATES) + "）")
    else:
        heads, e = check_md(md)
        errs += e

    if not js:
        errs.append("找不到 model-catalog.json（已试：" + " / ".join(JSON_CANDIDATES) + "）")
    else:
        try:
            data = json.loads(js.read_text(encoding="utf-8"))
        except Exception as e:
            errs.append(f"json 解析失败: {e}")
            data = {}
        provs, e2, w2 = check_json(data)
        errs += e2
        warns += w2

    status = "PASS" if not errs else "FAIL"
    print(f"[{status}] 结构/契约校验 · md={md or '缺失'} · json={js or '缺失'}")
    print(f"  章节 {len(heads)} 个 · 记录 {len(provs)} 条 · 错误 {len(errs)} · 警告 {len(warns)}")
    for x in errs:
        print("  [ERR]", x)
    for x in warns[:8]:
        print("  [WARN]", x)

    print(json.dumps(
        {"check": "schema", "status": status, "providers": len(provs),
         "errors": len(errs), "warnings": len(warns)},
        ensure_ascii=False,
    ))
    sys.exit(0 if not errs else 1)


if __name__ == "__main__":
    main()
