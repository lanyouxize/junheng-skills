#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rev-core 端到端验收：在临时目录跑完整流水，断言每一步的退出码。

判据（任一不符即 FAIL）：
    1. init 正常 → 0；申请禁止能力 → 4；无授权依据 → 2（argparse 层）
    2. triage 能识别 PE 并给出非空 DAG
    3. compete-observe 目的下 DAG 不含任何 static.*
    4. evidence add：合规 → 0；不合规 → 1；非 rev-core 写者 → 1
    5. gate：有 blocking 未解项 → 1；无 → 0
    6. report：无 blocking → 0 且生成 report.md；有 blocking 且非 draft → 1
    7. 重复 evidence id → 1

用法：python scripts/e2e_check.py [--sample C:\\Windows\\System32\\notepad.exe]
"""

import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(HERE, "cli.py")
EXIT_OK, EXIT_INVALID, EXIT_PRECOND, EXIT_POLICY = 0, 1, 3, 4

results = []


def run(args, expect, label):
    p = subprocess.run([sys.executable, CLI] + args, capture_output=True, text=True)
    ok = p.returncode == expect
    results.append((ok, label, expect, p.returncode, (p.stdout + p.stderr).strip().splitlines()[:2]))
    return p


def write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")


def env(kind, eid, **kw):
    o = {"schema": "reva/1", "kind": kind, "id": eid, "produced_by": "rev-core",
         "produced_at": "2026-11-01T22:45:00+08:00", "target_id": kw.pop("target_id", "tgt-000000"),
         "provenance": {"tool": "rev-core", "version": "1.0.0", "command": "e2e",
                        "inputs_sha256": ["a" * 64]},
         "status": "ok", "refs": []}
    o.update(kw)
    return o


def ev(eid, target_id, grade="E1", channel="static"):
    o = env("evidence", eid, target_id=target_id)
    o.update({"locator": {"file_sha256": "b" * 64, "addr": 4198400, "length": 6},
              "digest": {"algo": "sha256", "value": "c" * 64},
              "reproduce": {"cmd": "python xrefs.py sample.exe 0x401000 6", "cwd": ".", "env": {}},
              "grade": grade, "channel": channel})
    return o


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", default=r"C:\Windows\System32\notepad.exe")
    args = ap.parse_args()
    if not os.path.exists(args.sample):
        print(f"SKIP：样本不存在 {args.sample}")
        return EXIT_PRECOND

    tmp = tempfile.mkdtemp(prefix="reva-e2e-")
    try:
        # 1. 策略拒绝 → 4（在任何分析之前）
        run(["init", "--dir", os.path.join(tmp, "a"), "--target", args.sample,
             "--basis", "self-owned", "--purpose", "interop", "--allow", "drm-bypass"],
            EXIT_POLICY, "init 申请 drm-bypass → exit 4")

        # 2. 正常开单 → 0
        c1 = os.path.join(tmp, "c1")
        run(["init", "--dir", c1, "--target", args.sample,
             "--basis", "self-owned", "--purpose", "interop"], EXIT_OK, "init 正常 → exit 0")

        # 3. triage → 0 且 DAG 非空
        p = run(["triage", "--dir", c1], EXIT_OK, "triage → exit 0")
        tri = json.load(io.open(os.path.join(c1, "triage.json"), encoding="utf-8"))
        results.append((bool(tri.get("dag")), "triage 产出非空 DAG", True, bool(tri.get("dag")), [str(tri.get("dag"))[:80]]))
        results.append((tri.get("format", "").startswith("pe"), "triage 识别为 PE 系", "pe*", tri.get("format"), []))
        tid = tri["target_id"] if "target_id" in tri else json.load(
            io.open(os.path.join(c1, "target.json"), encoding="utf-8"))["target_id"]

        # 4. compete-observe → DAG 无 static.*
        c2 = os.path.join(tmp, "c2")
        run(["init", "--dir", c2, "--target", args.sample,
             "--basis", "public-spec", "--purpose", "compete-observe"], EXIT_OK, "init compete-observe → exit 0")
        run(["triage", "--dir", c2], EXIT_OK, "triage(compete) → exit 0")
        tri2 = json.load(io.open(os.path.join(c2, "triage.json"), encoding="utf-8"))
        no_static = all(not n.startswith("static.") for n in tri2.get("dag", []))
        results.append((no_static, "compete-observe DAG 不含 static.*", True, no_static, [str(tri2.get("dag"))[:80]]))
        if not tri2.get("dag"):
            run(["dispatch", "--dir", c2], EXIT_POLICY, "compete 过滤后 DAG 空 → exit 4")

        # 5. 合规证据写入 → 0
        f1 = os.path.join(tmp, "e1.json")
        write(f1, ev("ev-9001", tid, "E1", "static"))
        run(["evidence", "add", "--dir", c1, "--file", f1], EXIT_OK, "evidence add 合规 → exit 0")

        # 6. 重复 id → 1
        run(["evidence", "add", "--dir", c1, "--file", f1], EXIT_INVALID, "evidence add 重复 id → exit 1")

        # 7. 不合规证据 → 1
        bad = ev("ev-9002", tid); bad.pop("locator")
        f2 = os.path.join(tmp, "e2.json"); write(f2, bad)
        run(["evidence", "add", "--dir", c1, "--file", f2], EXIT_INVALID, "evidence add 缺 locator → exit 1")

        # 8. 非 rev-core 写者 → 1
        o = ev("ev-9003", tid); o["produced_by"] = "rev-static"
        f3 = os.path.join(tmp, "e3.json"); write(f3, o)
        run(["evidence", "add", "--dir", c1, "--file", f3], EXIT_INVALID, "evidence add 非 core 写者 → exit 1")
        run(["evidence", "add", "--dir", c1, "--file", f3, "--allow-forward"], EXIT_OK,
            "evidence add 代写(allow-forward) → exit 0")

        # 9. gate 通过 → 0
        run(["gate", "--dir", c1], EXIT_OK, "gate 无 blocking → exit 0")

        # 10. report → 0 且文件生成
        run(["report", "--dir", c1], EXIT_OK, "report 交付版 → exit 0")
        results.append((os.path.exists(os.path.join(c1, "report.md")), "report.md 已生成", True,
                        os.path.exists(os.path.join(c1, "report.md")), []))

        # 11. 注入 blocking unknown → gate 1、report 1、draft 0
        uk = env("unknown", "uk-9001", target_id=tid)
        uk.update({"question": "帧尾校验算法未定", "why_unknown": "样本不足", "blocking": True,
                   "tried": [], "unblock_condition": "再采 20 组", "owner_module": "rev-runtime"})
        with io.open(os.path.join(c1, "unknowns.jsonl"), "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(uk, ensure_ascii=False) + "\n")
        run(["gate", "--dir", c1], EXIT_INVALID, "gate 有 blocking → exit 1")
        run(["report", "--dir", c1], EXIT_INVALID, "report 有 blocking → exit 1")
        run(["report", "--dir", c1, "--draft"], EXIT_OK, "report --draft → exit 0")

        # 12. lint 干净 → 0
        run(["lint", "--path", c1], EXIT_OK, "lint 案卷 → exit 0")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    bad = [r for r in results if not r[0]]
    for ok, label, exp, got, detail in results:
        mark = "OK  " if ok else "FAIL"
        print(f"{mark} {label:<44} expect={exp} got={got}" + (f"  {detail}" if detail and not ok else ""))
    print()
    if bad:
        print(f"E2E FAILED  {len(bad)}/{len(results)}")
        return EXIT_INVALID
    print(f"E2E PASSED  {len(results)}/{len(results)}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
