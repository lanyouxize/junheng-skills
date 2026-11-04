#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""技能验收集运行器（黑盒 CLI 断言）。

为什么需要：86 个技能里回归测试为 0。改一个限值表、动一个计算分支，没有任何机制
能发现它把上一版改坏了。本运行器只做一件事：**跑真实 CLI，按判据断言，退化即报红**。

设计约束：
    - 纯黑盒：只调 `node scripts/cli.mjs <cmd> '<json>'`，不 import 技能内部模块
    - 用例只存「输入 + 判据」，**不存期望输出全文**（防过拟合）
    - 判据必须能失败：只允许 eq / ne / range / non_empty / empty / not_null / contains 七种
    - 已知缺陷用 ``known_defect: true`` 标记：失败不计入退出码，但必须显式列出

用法：
    python runner.py                      # 跑全部用例
    python runner.py --suite nutrition     # 只跑一个套件
    python runner.py --json                # 机器读
    python runner.py --mutate <suite>      # 变异测试：在副本里改坏常量，断言必须报红

退出码：0 全通过 / 1 有用例失败（不含 known_defect）/ 2 环境错误
"""

import argparse
import glob
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

SKILLS_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CASES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cases")


def get_path(obj, dotted):
    """按 a.b.c 取值；缺失返回 (False, None)。"""
    cur = obj
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return False, None
    return True, cur


def check(data, rule):
    """单条判据。返回 (passed, actual_repr)。"""
    kind = rule["type"]
    exists, actual = get_path(data, rule["path"])
    if kind == "not_null":
        ok = exists and actual is not None
    elif kind == "empty":
        ok = exists and (actual in ([], {}, "", None))
    elif kind == "non_empty":
        ok = exists and actual not in (None, [], {}, "")
    elif kind == "eq":
        ok = exists and actual == rule["value"]
    elif kind == "ne":
        ok = exists and actual != rule["value"]
    elif kind == "range":
        lo, hi = rule["value"][0], rule["value"][1]
        ok = exists and isinstance(actual, (int, float)) and lo <= actual <= hi
    elif kind == "contains":
        ok = exists and isinstance(actual, (list, str)) and rule["value"] in actual
    else:
        return False, "未知判据:%s" % kind
    shown = json.dumps(actual, ensure_ascii=False)[:80] if exists else "<缺失>"
    return ok, shown


def _resolve(obj, variables):
    """把 payload 里的 "$name" 递归替换成前置命令的产出。"""
    if isinstance(obj, str) and obj.startswith("$"):
        return variables.get(obj[1:], obj)
    if isinstance(obj, dict):
        return {k: _resolve(v, variables) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve(v, variables) for v in obj]
    return obj


def _exec(skill, cmd, payload, skills_root):
    """跑一次 CLI。返回 (rc, data_or_None, raw_err)。"""
    cwd = os.path.join(skills_root, skill)
    if not os.path.isdir(cwd):
        return 3, None, "技能目录不存在: %s" % skill
    argv = ["node", "scripts/cli.mjs", cmd, "--stdin"]
    try:
        proc = subprocess.run(argv, cwd=cwd, input=json.dumps(payload, ensure_ascii=False),
                              capture_output=True, text=True, encoding="utf-8", timeout=120)
    except FileNotFoundError:
        return 3, None, "node 不可用"
    except subprocess.TimeoutExpired:
        return 3, None, "超时 120s"
    raw = proc.stdout.strip() or proc.stderr.strip()
    data = None
    if raw:
        try:
            data = json.loads(raw)
        except ValueError:
            return proc.returncode, None, "输出非 JSON：%s" % raw[:150]
    return proc.returncode, data, ""


def run_case(case, skills_root):
    """单步用例或 pipeline 用例。pipeline 支持跨技能契约串联。"""
    steps = case.get("pipeline")
    if steps:
        variables = {}
        last_rc, last_data, last_err = 0, None, ""
        for step in steps:
            payload = _resolve(step.get("args") or {}, variables)
            rc, data, err = _exec(step["skill"], step["cmd"], payload, skills_root)
            if err:
                return {"id": case["id"], "passed": False,
                        "detail": "%s.%s %s" % (step["skill"], step["cmd"], err)}
            want = step.get("exit", 0)
            if rc != want:
                return {"id": case["id"], "passed": False,
                        "detail": "%s.%s 退出码 %d ≠ %d" % (step["skill"], step["cmd"], rc, want)}
            if step.get("as"):
                if step.get("pick"):
                    found, val = get_path(data, step["pick"])
                    variables[step["as"]] = val if found else None
                else:
                    variables[step["as"]] = data
            last_rc, last_data = rc, data
        rc, data = last_rc, last_data
    else:
        payload = case.get("args") or {}
        rc, data, err = _exec(case["skill"], case["cmd"], payload, skills_root)
        if err:
            return {"id": case["id"], "passed": False, "detail": err}

    expect = case.get("expect") or {}
    want_exit = expect.get("exit", 0)
    if rc != want_exit:
        return {"id": case["id"], "passed": False, "detail": "退出码 %d ≠ 期望 %d" % (rc, want_exit)}
    if data is None:
        if not (expect.get("assert") or []):
            return {"id": case["id"], "passed": True, "detail": ""}
        return {"id": case["id"], "passed": False, "detail": "输出为空但用例要求断言"}

    fails = []
    for rule in expect.get("assert") or []:
        ok, shown = check(data, rule)
        if not ok:
            fails.append("%s 实际=%s" % (rule["path"], shown))
    if fails:
        return {"id": case["id"], "passed": False, "detail": "；".join(fails)}
    return {"id": case["id"], "passed": True, "detail": ""}


def load_suites(only=None):
    suites = {}
    for path in sorted(glob.glob(os.path.join(CASES_DIR, "*.json"))):
        name = os.path.splitext(os.path.basename(path))[0]
        if only and name != only:
            continue
        with io.open(path, encoding="utf-8") as fh:
            suites[name] = json.load(fh)
    return suites


def _suite_skills(cases):
    """从用例里提取涉及的技能集合（兼容单步与 pipeline 两种写法）。"""
    found = []
    for case in cases:
        for step in case.get("pipeline") or []:
            if step["skill"] not in found:
                found.append(step["skill"])
        if case.get("skill") and case["skill"] not in found:
            found.append(case["skill"])
    return found


def do_mutate(suite_name, skills_root, fine=False):
    """变异测试：复制技能目录到临时目录 → 改坏一处 → 断言验收集报红。

    fine=False  粗粒度：改 cli.mjs 的字段名（验证链路整体失效能被发现）
    fine=True   细粒度：改 junheng-core 的法规限值（验证数值退化能被发现）
    """
    with io.open(os.path.join(CASES_DIR, suite_name + ".json"), encoding="utf-8") as fh:
        cases = json.load(fh)
    skills = _suite_skills(cases)
    if not skills:
        print("套件里没有可定位的技能", file=sys.stderr)
        return 2

    tmp_root = tempfile.mkdtemp(prefix="acc-mutate-")
    ignore = shutil.ignore_patterns("node_modules", "__pycache__")
    for skill in skills:
        src = os.path.join(skills_root, skill)
        if not os.path.isdir(src):
            shutil.rmtree(tmp_root, ignore_errors=True)
            print("技能目录不存在: %s" % skill, file=sys.stderr)
            return 2
        shutil.copytree(src, os.path.join(tmp_root, skill), ignore=ignore)
    # junheng-* 依赖共享内核 ../../junheng-core，必须一并复制到同级
    if any(s.startswith("junheng-") for s in skills):
        core_src = os.path.join(skills_root, "junheng-core")
        if os.path.isdir(core_src):
            shutil.copytree(core_src, os.path.join(tmp_root, "junheng-core"), ignore=ignore)

    if fine:
        target = os.path.join(tmp_root, "junheng-core", "scripts", "vendor", "standards.js")
        if not os.path.exists(target):
            shutil.rmtree(tmp_root, ignore_errors=True)
            print("未找到法规限值文件: %s" % target, file=sys.stderr)
            return 2
        with io.open(target, encoding="utf-8") as fh:
            text = fh.read()
        needle = "crude_ash: { max: 10.0"
        if needle not in text:
            shutil.rmtree(tmp_root, ignore_errors=True)
            print("未找到目标限值模式（crude_ash max 10.0），限值表可能已改版", file=sys.stderr)
            return 2
        text = text.replace(needle, "crude_ash: { max: 1.0")
        with io.open(target, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        what = "junheng-core 法规限值 crude_ash.max 10.0 → 1.0（细粒度）"
    else:
        mutated = False
        for skill in skills:
            target = os.path.join(tmp_root, skill, "scripts", "cli.mjs")
            if not os.path.exists(target):
                continue
            with io.open(target, encoding="utf-8") as fh:
                text = fh.read()
            if "weight" in text:
                with io.open(target, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(text.replace("weight", "weightX", 1))
                mutated = True
                break
        if not mutated:
            shutil.rmtree(tmp_root, ignore_errors=True)
            print("副本里找不到可变异点", file=sys.stderr)
            return 2
        what = "cli.mjs 的 weight 字段改名（粗粒度）"

    results = [run_case(c, tmp_root) for c in cases]
    shutil.rmtree(tmp_root, ignore_errors=True)
    failed = [r for r in results if not r["passed"] and not r.get("known_defect")]
    print("变异测试 · %s" % what)
    print("  用例 %d 个，报红 %d 个" % (len(results), len(failed)))
    for r in failed[:6]:
        print("  FAIL %s %s" % (r["id"], r["detail"][:110]))
    if failed:
        print("  结论：验收集有效（该粒度的退化能被发现）")
        return 0
    print("  结论：验收集无效 —— 该粒度改坏后全绿，判据需重设计")
    return 1


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", default=None, help="只跑一个套件（cases/<name>.json）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--mutate", default=None, metavar="SUITE", help="变异测试（粗粒度：改字段名）")
    ap.add_argument("--fine", action="store_true", help="与 --mutate 合用：细粒度变异（改法规限值）")
    ap.add_argument("--skills-root", default=SKILLS_ROOT)
    args = ap.parse_args(argv)

    if not os.path.isdir(CASES_DIR):
        print("用例目录不存在: %s" % CASES_DIR, file=sys.stderr)
        return 2

    if args.mutate:
        return do_mutate(args.mutate, args.skills_root, fine=args.fine)

    suites = load_suites(args.suite)
    if not suites:
        print("未找到用例套件（%s）" % CASES_DIR, file=sys.stderr)
        return 2

    all_rows, hard_fail = [], 0
    for name, cases in suites.items():
        for case in cases:
            r = run_case(case, args.skills_root)
            r["suite"] = name
            r["known_defect"] = bool(case.get("known_defect"))
            r["desc"] = case.get("desc", "")
            all_rows.append(r)
            if not r["passed"] and not r["known_defect"]:
                hard_fail += 1

    if args.json:
        print(json.dumps({"rows": all_rows, "hard_fail": hard_fail}, ensure_ascii=False, indent=2))
    else:
        print("验收集 · %d 个套件 / %d 个用例" % (len(suites), len(all_rows)))
        for r in all_rows:
            if r["passed"]:
                mark = "PASS"
            elif r["known_defect"]:
                mark = "KNOWN"
            else:
                mark = "FAIL"
            print("  [%s] %-6s %s %s" % (mark, r["suite"], r["id"], r["desc"]))
            if not r["passed"]:
                print("         %s" % r["detail"][:120])
        print("合计：通过 %d / 已知缺陷 %d / 失败 %d" % (
            sum(1 for r in all_rows if r["passed"]),
            sum(1 for r in all_rows if not r["passed"] and r["known_defect"]),
            hard_fail))
    return 0 if hard_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
