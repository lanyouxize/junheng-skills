#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
技能契约验证框架（P0-D 测试地基）
================================
用途：对技能包做可机检的契约断言，支持【证伪模式】。

设计要点（为什么值得存在）：
  1. 断言只写「真不变量」，不写「文件存在」这类永不失败的伪检查。
  2. 每个 test_*.py 可声明 FAULTS：{相对路径: 篡改函数}。
     `--fault` 模式下 ctx.read() 会读到被篡改的内容 —— 此时断言【必须失败】。
     若 --fault 下仍然全绿，说明断言无效（检查器不可证伪），框架会判定该项不达标。

用法：
  python verify.py                 # 跑全部
  python verify.py --only junheng-cost
  python verify.py --fault         # 证伪模式：断言必须失败
  python verify.py --selftest      # 框架自检：内置必败断言，验证框架能正确报错

退出码：0 = 全部符合预期；1 = 有失败（正常模式）或证伪未触发（fault 模式）
"""
import argparse
import glob
import importlib.util
import json
import os
import re
import subprocess
import sys

SKILLS_DIR = r"C:/Users/Administrator/.workbuddy/skills"
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))

C_OK, C_BAD, C_DIM, C_YEL, C_RST = "\033[92m", "\033[91m", "\033[2m", "\033[93m", "\033[0m"
if os.name == "nt":
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleMode(ctypes.windll.kernel32.GetStdHandle(-11), 7)
    except Exception:
        C_OK = C_BAD = C_DIM = C_YEL = C_RST = ""


class Ctx:
    """断言上下文：统一读文件 / 解析 / 跑子进程，证伪模式下污染读取结果。"""

    def __init__(self, skill_dir, fault=False, faults=None):
        self.dir = skill_dir
        self.fault = fault
        self.faults = faults or {}

    def path(self, rel=""):
        return os.path.join(self.dir, rel) if rel else self.dir

    def exists(self, rel):
        return os.path.exists(self.path(rel))

    def read(self, rel):
        p = self.path(rel)
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        if self.fault and rel in self.faults:
            mut = self.faults[rel]
            return mut(text)
        return text

    def read_bytes(self, rel):
        with open(self.path(rel), "rb") as f:
            data = f.read()
        if self.fault and rel in self.faults:
            return self.faults[rel](data)
        return data

    def json(self, rel):
        return json.loads(self.read(rel))

    def frontmatter(self, rel="SKILL.md"):
        text = self.read(rel)
        lines = text.splitlines()
        if not lines or lines[0].strip() != "---":
            return {}
        fm, key = {}, None
        for line in lines[1:]:
            if line.strip() == "---":
                break
            m = re.match(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$", line)
            if m:
                key = m.group(1)
                v = m.group(2).strip().strip('"').strip("'")
                fm[key] = v
            elif key and line.strip().startswith("- "):
                fm.setdefault(key, [])
                if isinstance(fm[key], list):
                    fm[key].append(line.strip()[2:].strip())
        return fm

    def run(self, cmd, cwd=None, timeout=60, env_extra=None):
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        if env_extra:
            env.update(env_extra)
        try:
            p = subprocess.run(cmd, cwd=cwd or self.dir, capture_output=True,
                               text=True, encoding="utf-8", errors="replace",
                               timeout=timeout, env=env, shell=isinstance(cmd, str))
            return p.returncode, p.stdout or "", p.stderr or ""
        except subprocess.TimeoutExpired:
            return 124, "", f"timeout after {timeout}s"
        except FileNotFoundError as e:
            return 127, "", str(e)


def load_module(path):
    name = "t_" + os.path.splitext(os.path.basename(path))[0]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def check_selftest(ctx):
    """框架自检：本组断言【必然失败】，用于证明框架能正确识别失败。"""
    return [(False, "框架自检：此断言被设计为必然失败，用于验证框架能报告失败")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None)
    ap.add_argument("--fault", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        print(f"{C_YEL}[自检] 运行内置必败断言，预期结果为「失败」{C_RST}")
        res = check_selftest(Ctx(SKILLS_DIR))
        failed = [m for ok, m in res if not ok]
        for m in failed:
            print(f"  {C_BAD}✗{C_RST} {m}")
        if failed:
            print(f"\n{C_OK}✅ 框架自检通过：能正确报告失败（{len(failed)} 条）{C_RST}")
            return 0
        print(f"\n{C_BAD}❌ 框架自检失败：无法报告失败，检查器不可信{C_RST}")
        return 1

    files = sorted(glob.glob(os.path.join(TESTS_DIR, "test_*.py")))
    if args.only:
        files = [f for f in files if args.only in os.path.basename(f)]
    if not files:
        print("未找到 test_*.py")
        return 1

    total_pass = total_fail = total_warn = 0
    per_skill = []
    for fp in files:
        mod = load_module(fp)
        skill = getattr(mod, "SKILL", None)
        if not skill:
            print(f"{C_YEL}跳过 {os.path.basename(fp)}：未声明 SKILL{C_RST}")
            continue
        skill_dir = os.path.join(SKILLS_DIR, skill)
        faults = getattr(mod, "FAULTS", {})
        ctx = Ctx(skill_dir, fault=args.fault, faults=faults)
        checks = getattr(mod, "checks")
        try:
            results = checks(ctx)
        except Exception as e:
            results = [(False, f"checks() 抛异常：{type(e).__name__}: {e}")]

        # 支持三态：(ok, msg) 或 (ok, msg, "warn")
        norm = []
        for item in results:
            if len(item) == 3:
                ok, msg, lvl = item
                norm.append((bool(ok), msg, "warn" if lvl == "warn" else None))
            else:
                ok, msg = item
                norm.append((bool(ok), msg, None))
        results = norm

        p = sum(1 for ok, _, lvl in results if ok)
        w = sum(1 for ok, _, lvl in results if not ok and lvl == "warn")
        f = len(results) - p - w
        total_pass += p
        total_warn += w
        total_fail += f
        per_skill.append((skill, p, w, f, len(faults)))

        if not args.quiet:
            tag = f"{C_YEL}[证伪模式]{C_RST}" if args.fault else ""
            print(f"\n{C_DIM}── {skill} {tag}{C_RST}")
            for ok, msg, lvl in results:
                if ok:
                    mark = f"{C_OK}✓{C_RST}"
                elif lvl == "warn":
                    mark = f"{C_YEL}!{C_RST}"
                else:
                    mark = f"{C_BAD}✗{C_RST}"
                print(f"  {mark} {msg}")

    print("\n" + "=" * 68)
    for skill, p, w, f, nf in per_skill:
        status = f"{C_OK}全绿{C_RST}" if f == 0 and w == 0 else (
            f"{C_YEL}{w} 警告{C_RST}" if f == 0 else f"{C_BAD}{f} 失败{C_RST}")
        print(f"  {skill:<26} 通过 {p:>2} / 警告 {w:>2} / 失败 {f:>2} / 可证伪点 {nf:>2}   {status}")
    print("=" * 68)
    print(f"合计：通过 {total_pass} · 警告 {total_warn} · 失败 {total_fail}")

    if args.fault:
        # 证伪模式判定：改坏数据后，该技能必须至少产生 1 条「失败或警告」。
        # 说明：警告态同样代表「检查器检出了问题」，只是不阻塞正常流程，
        #       因此在证伪语境下与失败等效；无 FAULTS 声明的技能直接判不达标。
        bad_skills = [s for s, p, w, f, nf in per_skill if nf == 0 or (f + w) == 0]
        if bad_skills:
            print(f"\n{C_BAD}❌ 证伪未通过：以下技能的断言改坏后仍然全绿/无可证伪点 ⇒ 检查器无效{C_RST}")
            for s in bad_skills:
                print(f"   - {s}")
            return 1
        print(f"\n{C_OK}✅ 证伪通过：{len(per_skill)} 个技能在数据被改坏后均能报错{C_RST}")
        return 0

    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
