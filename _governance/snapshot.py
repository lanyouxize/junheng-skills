#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""技能资产快照：给 ~/.workbuddy/skills 的文本资产算 sha256 指纹。

用途：让「技能被谁改了」从不可回答变成可回答。只读，不修改任何技能文件。

用法：
    python snapshot.py              # 生成 SNAPSHOT.json
    python snapshot.py --check       # 与已有 SNAPSHOT.json 比对，有差异退出码 1
    python snapshot.py --stdout      # 只打印统计，不落盘

确定性约定（同 cost-rules CTX-03）：
    - JSON 键按字母序、indent=2、UTF-8 无 BOM
    - 路径统一正斜杠，相对 skills 根
    - 时间只写 UTC ISO8601 到 generated_at，--check 时忽略该字段
    - 同一输入连跑两次，除 generated_at 外字节一致

退出码：0 通过 / 1 有差异（--check）/ 2 环境错误
"""

import argparse
import hashlib
import io
import json
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "_governance", "SNAPSHOT.json")

EXCLUDE_DIRS = {"_prune_backup", "__pycache__", "node_modules", ".git", "_trash"}
INCLUDE_EXT = {".md", ".py", ".json", ".yaml", ".yml", ".txt", ".sh", ".cmd"}
# 快照自身不参与指纹，否则每次生成都会自变
EXCLUDE_FILES = {"SNAPSHOT.json", "lint-report-20261102.json"}


def iter_files():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDE_DIRS and not d.startswith("."))
        for name in sorted(filenames):
            if name in EXCLUDE_FILES:
                continue
            if os.path.splitext(name)[1].lower() not in INCLUDE_EXT:
                continue
            abspath = os.path.join(dirpath, name)
            rel = os.path.relpath(abspath, ROOT).replace("\\", "/")
            yield abspath, rel


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build():
    files = {}
    for abspath, rel in iter_files():
        files[rel] = {
            "sha256": sha256_of(abspath),
            "bytes": os.path.getsize(abspath),
        }
    return {
        "schema": 1,
        "root": ROOT.replace("\\", "/"),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "file_count": len(files),
        "total_bytes": sum(v["bytes"] for v in files.values()),
        "files": dict(sorted(files.items())),
    }


def load_old():
    if not os.path.exists(OUT):
        return None
    with io.open(OUT, encoding="utf-8") as f:
        return json.load(f)


def diff(old, new):
    o, n = old.get("files", {}), new.get("files", {})
    added = sorted(set(n) - set(o))
    removed = sorted(set(o) - set(n))
    changed = sorted(k for k in set(o) & set(n) if o[k]["sha256"] != n[k]["sha256"])
    return added, removed, changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="与已有快照比对")
    ap.add_argument("--stdout", action="store_true", help="只打印统计，不落盘")
    args = ap.parse_args()

    try:
        new = build()
    except OSError as e:
        print("E-SNAPSHOT-ENV: %s" % e, file=sys.stderr)
        return 2

    if args.check:
        old = load_old()
        if old is None:
            print("无已有快照，先运行 python snapshot.py")
            return 1
        added, removed, changed = diff(old, new)
        print("对比 %s -> %s" % (old.get("generated_at"), new.get("generated_at")))
        print("新增 %d / 删除 %d / 修改 %d" % (len(added), len(removed), len(changed)))
        for label, items in (("+", added), ("-", removed), ("~", changed)):
            for it in items[:20]:
                print("  %s %s" % (label, it))
            if len(items) > 20:
                print("  ... 另有 %d 条" % (len(items) - 20))
        return 0 if not (added or removed or changed) else 1

    if args.stdout:
        print("file_count=%d total_bytes=%d" % (new["file_count"], new["total_bytes"]))
        return 0

    with io.open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(new, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    print("已写 %s | file_count=%d | total_bytes=%d" % (OUT, new["file_count"], new["total_bytes"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
