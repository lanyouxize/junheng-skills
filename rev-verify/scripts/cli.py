#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rev-verify —— 验证对拍层：把"我看到过"变成"任何人都能再验一遍"。

三条硬规矩（本模块的全部价值都在这里）：
  1. 容忍度 0：声明的断言必须 100% 成立，没有"大致相同"。
  2. 空基线不算通过：facts 为空的 fixture 不能当基线，replay 直接判 fail。
     否则重放器永远绿，"验证"变成仪式。
  3. 断言分级：静态产物 digest 应完全可复现（exact）；动态观测天然带噪声
     （时间戳、session id、renderer 数量），只能声明 subset。把两者混为一谈，
     要么把动态验成假绿，要么把静态放过。

不做什么：
  - 不判断"结论对不对"（那是人的事），只判断"这次跑出来的东西和上次是不是同一批"
  - 不自动修 fixture：失配就报错退出，绝不自我更新成绿灯
"""

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import sys
from datetime import datetime, timedelta, timezone

CST = timezone(timedelta(hours=8))
EXIT_OK, EXIT_MISMATCH, EXIT_INVALID = 0, 1, 2


def now_iso():
    return datetime.now(CST).replace(microsecond=0).isoformat()


def read_json(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def write_json(p, obj):
    os.makedirs(os.path.dirname(os.path.abspath(p)) or ".", exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


# ---------------------------------------------------------------- fixture

def load_facts(path):
    """facts 文件必须是 revfact/1。别的格式直接拒绝 —— 宁可报错也不猜。"""
    d = read_json(path)
    if d.get("schema") != "revfact/1":
        raise ValueError("不是 revfact/1 事实文件: %s（schema=%r）" % (path, d.get("schema")))
    if not isinstance(d.get("facts"), list):
        raise ValueError("facts 字段不是数组: %s" % path)
    return d


def cmd_freeze(args):
    d = load_facts(args.facts)
    if not d["facts"]:
        print("拒绝冻结：facts 为空，空基线会让 replay 永远通过", file=sys.stderr)
        return EXIT_INVALID
    if args.mode not in ("exact", "subset"):
        print("mode 必须是 exact 或 subset", file=sys.stderr)
        return EXIT_INVALID
    # 动态通道默认不许用 exact —— 它天然带 session/时间噪声
    producer = d.get("producer")
    if args.mode == "exact" and producer != "rev-static":
        print("拒绝：producer=%r 的产物不允许 exact 基线（动态观测含 session/时间噪声），请用 subset"
              % producer, file=sys.stderr)
        return EXIT_INVALID

    entries = []
    for f in d["facts"]:
        entries.append({
            "id": f.get("id"),
            "kind": f.get("kind"),
            "value": f.get("value"),
            "digest": f.get("digest", {}).get("value"),
            "locator_mode": (f.get("locator") or {}).get("mode", "file"),
        })
    argv = None
    if args.argv:
        argv = json.loads(args.argv)
    elif args.cmd:
        argv = shlex.split(args.cmd, posix=(os.name != "nt"))
    fx = {
        "schema": "reva-fixture/1",
        "name": args.name or os.path.splitext(os.path.basename(args.facts))[0],
        "frozen_at": now_iso(),
        "mode": args.mode,
        "producer": producer,
        "channel": d.get("channel"),
        "target_id": d.get("target_id"),
        "sample_sha256": d.get("sample_sha256") or (d.get("runtime") or {}).get("exe_sha256"),
        "source_facts_sha256": sha256_file(args.facts),
        "argv": argv,
        "cwd": args.cwd,
        "status": d.get("status"),
        "count": len(entries),
        "entries": entries,
    }
    out = os.path.join(args.out, fx["name"] + ".fixture.json")
    write_json(out, fx)
    print("冻结 %d 条事实 -> %s  (mode=%s)" % (len(entries), out, fx["mode"]))
    if not argv:
        print("  注意：未记录 argv，replay 时需用 --argv/--cmd 显式给出重跑命令")
    return EXIT_OK


# ---------------------------------------------------------------- 比对

def compare(fx, result):
    errs = []
    if not fx.get("entries"):
        return ["fixture 为空基线，不能作为验证依据（空集合永远匹配空集合）"]

    if fx.get("status") and result.get("status") != fx["status"]:
        errs.append("status 不一致: 期望 %r 实为 %r" % (fx["status"], result.get("status")))

    if fx.get("producer") and result.get("producer") != fx["producer"]:
        errs.append("producer 不一致: 期望 %r 实为 %r" % (fx["producer"], result.get("producer")))

    # 源二进制必须同一版本 —— 换版本后行为不同是正常的，但那就不是同一次验证
    cur_sha = result.get("sample_sha256") or (result.get("runtime") or {}).get("exe_sha256")
    if fx.get("sample_sha256") and cur_sha and cur_sha != fx["sample_sha256"]:
        errs.append("输入二进制已变更: 基线 %s... 实为 %s..." % (fx["sample_sha256"][:16], cur_sha[:16]))

    cur = {}
    for f in result.get("facts", []):
        cur[f.get("id")] = f

    missing, digest_bad, value_bad = [], [], []
    for e in fx["entries"]:
        got = cur.get(e["id"])
        if not got:
            missing.append(e["id"])
            continue
        gd = (got.get("digest") or {}).get("value")
        if e.get("digest") and gd != e["digest"]:
            digest_bad.append((e["id"], e["digest"][:12], (gd or "")[:12]))
        if e.get("value") != got.get("value"):
            value_bad.append(e["id"])

    if missing:
        errs.append("基线中有 %d 条在本次结果中缺失: %s" % (len(missing), ", ".join(missing[:6])))
    if digest_bad:
        errs.append("digest 不符 %d 条: %s" % (
            len(digest_bad), "; ".join("%s 基线=%s 实为=%s" % x for x in digest_bad[:4])))
    if value_bad:
        errs.append("value 不符 %d 条: %s" % (len(value_bad), ", ".join(value_bad[:6])))

    if fx.get("mode") == "exact":
        extra = [i for i in cur if i not in {e["id"] for e in fx["entries"]}]
        if extra:
            errs.append("exact 模式下出现基线外新增事实 %d 条: %s" % (len(extra), ", ".join(sorted(extra)[:6])))
        if len(cur) != len(fx["entries"]):
            errs.append("事实条数不符: 基线 %d 实为 %d" % (len(fx["entries"]), len(cur)))
    return errs


def cmd_replay(args):
    fx = read_json(args.fixture)
    if fx.get("schema") != "reva-fixture/1":
        print("不是 reva-fixture/1: %s" % args.fixture, file=sys.stderr)
        return EXIT_INVALID

    argv = None
    if args.argv:
        argv = json.loads(args.argv)
    elif args.cmd:
        argv = shlex.split(args.cmd, posix=(os.name != "nt"))
    elif fx.get("argv"):
        argv = fx["argv"]

    if argv:
        cwd = args.cwd or fx.get("cwd") or "."
        print("重跑: %s  (cwd=%s)" % (" ".join(argv), cwd))
        r = subprocess.run(argv, cwd=cwd, capture_output=True, text=True)
        print("  退出码=%d" % r.returncode)
        if r.returncode != 0:
            print("  重跑失败，stdout/stderr 末尾：")
            print("  " + (r.stdout or "").strip()[-400:])
            print("  " + (r.stderr or "").strip()[-400:])
            return EXIT_INVALID
        out = args.facts
        if not out:
            print("重跑成功但未给 --facts 指向产物，无法比对", file=sys.stderr)
            return EXIT_INVALID
        result = load_facts(out)
    else:
        if not args.facts:
            print("未记录 argv，需 --facts 指向现成产物或 --cmd/--argv 给出重跑命令", file=sys.stderr)
            return EXIT_INVALID
        result = load_facts(args.facts)

    errs = compare(fx, result)
    if errs:
        print("\nREPLAY MISMATCH  %d 项（容忍度 0）" % len(errs))
        for e in errs:
            print("  E " + e)
        return EXIT_MISMATCH
    print("\nREPLAY OK  %d/%d 条一致  mode=%s" % (len(fx["entries"]), fx["count"], fx["mode"]))
    return EXIT_OK


def cmd_diff(args):
    a, b = load_facts(args.a), load_facts(args.b)
    ia = {f["id"]: f for f in a["facts"]}
    ib = {f["id"]: f for f in b["facts"]}
    only_a = sorted(set(ia) - set(ib))
    only_b = sorted(set(ib) - set(ia))
    changed = []
    for k in sorted(set(ia) & set(ib)):
        da = (ia[k].get("digest") or {}).get("value")
        db = (ib[k].get("digest") or {}).get("value")
        if da != db or ia[k].get("value") != ib[k].get("value"):
            changed.append(k)
    print("A=%d 条  B=%d 条" % (len(ia), len(ib)))
    print("  仅 A: %d %s" % (len(only_a), only_a[:8]))
    print("  仅 B: %d %s" % (len(only_b), only_b[:8]))
    print("  有差异: %d %s" % (len(changed), changed[:8]))
    return EXIT_OK if not (only_a or only_b or changed) else EXIT_MISMATCH


# ---------------------------------------------------------------- 自检

def cmd_selftest(args):
    checks = []

    def check(cond, name, detail=""):
        checks.append((bool(cond), name, detail))

    import tempfile
    tmp = tempfile.mkdtemp(prefix="reva-verify-")

    def mkfact(i, kind, value, fsha="a" * 64, mode="file"):
        raw = value.encode("utf-8") if isinstance(value, str) else json.dumps(value).encode()
        loc = {"file_sha256": fsha, "length": max(1, len(raw))}
        if mode == "runtime":
            loc = {"mode": "runtime", "file_sha256": fsha, "length": max(1, len(raw)),
                   "runtime": {"host": "windows", "pid": 100, "module": "a.exe", "rva": 0, "session": "s"}}
        else:
            loc["offset"] = i * 16
        return {"id": "f-%04d" % i, "kind": kind, "value": value, "locator": loc,
                "digest": {"algo": "sha256", "value": hashlib.sha256(raw).hexdigest()}}

    def mkresult(facts, producer="rev-static", status="ok", fsha="a" * 64, mode="file"):
        d = {"schema": "revfact/1", "producer": producer, "channel": "x", "target_id": "tgt-1",
             "status": status, "facts": facts}
        if mode == "file":
            d["sample_sha256"] = fsha
        else:
            d["runtime"] = {"exe_sha256": fsha}
        return d

    base_facts = [mkfact(1, "string-ascii", "AAA"), mkfact(2, "string-ascii", "BBB"),
                  mkfact(3, "import-func", "CreateFileW")]
    base = mkresult(base_facts)
    p_base = os.path.join(tmp, "base.json")
    write_json(p_base, base)

    fxdir = os.path.join(tmp, "fx")
    rc = cmd_freeze(argparse.Namespace(facts=p_base, out=fxdir, mode="exact", name="base",
                                       argv=None, cmd=None, cwd="."))
    check(rc == EXIT_OK, "可以冻结静态产物为 exact 基线", "rc=%d" % rc)
    fxp = os.path.join(fxdir, "base.fixture.json")
    fx = read_json(fxp)
    check(len(fx["entries"]) == 3, "基线记录全部 3 条事实", str(len(fx["entries"])))

    # 1. 完全一致 -> 通过
    check(compare(fx, mkresult(json.loads(json.dumps(base_facts)))) == [],
          "同输入重跑完全一致时应通过")

    # 2. 少一条 -> 必须失败
    e = compare(fx, mkresult(base_facts[:2]))
    check(bool(e) and any("缺失" in x for x in e), "少一条事实必须判失配", str(e)[:80])

    # 3. 值变了 -> 必须失败
    f2 = json.loads(json.dumps(base_facts))
    f2[0]["value"] = "AAA-changed"
    f2[0]["digest"]["value"] = hashlib.sha256(b"AAA-changed").hexdigest()
    e = compare(fx, mkresult(f2))
    check(bool(e) and any("value 不符" in x for x in e), "值变化必须判失配", str(e)[:80])

    # 4. 只改 digest 不改 value（伪造）-> 必须失败
    f3 = json.loads(json.dumps(base_facts))
    f3[0]["digest"]["value"] = "0" * 64
    e = compare(fx, mkresult(f3))
    check(bool(e) and any("digest 不符" in x for x in e), "digest 被改必须判失配", str(e)[:80])

    # 5. exact 模式多出一条 -> 必须失败
    e = compare(fx, mkresult(base_facts + [mkfact(9, "extra", "ZZZ")]))
    check(bool(e) and any("新增事实" in x for x in e), "exact 模式新增事实必须判失配", str(e)[:80])

    # 6. 二进制版本变了 -> 必须失败
    e = compare(fx, mkresult(base_facts, fsha="b" * 64))
    check(bool(e) and any("二进制已变更" in x for x in e), "输入二进制变更必须判失配", str(e)[:80])

    # 7. 空 fixture 不能冻结
    p_empty = os.path.join(tmp, "empty.json")
    write_json(p_empty, mkresult([]))
    rc = cmd_freeze(argparse.Namespace(facts=p_empty, out=fxdir, mode="exact", name="empty",
                                       argv=None, cmd=None, cwd="."))
    check(rc == EXIT_INVALID, "空 facts 必须拒绝冻结（否则重放永远绿）", "rc=%d" % rc)

    # 8. 动态产物不许 exact
    dyn = mkresult([mkfact(1, "console", "x", mode="runtime")], producer="rev-runtime", mode="runtime")
    p_dyn = os.path.join(tmp, "dyn.json")
    write_json(p_dyn, dyn)
    rc = cmd_freeze(argparse.Namespace(facts=p_dyn, out=fxdir, mode="exact", name="dyn",
                                       argv=None, cmd=None, cwd="."))
    check(rc == EXIT_INVALID, "动态产物禁止 exact 基线", "rc=%d" % rc)

    # 9. 动态 subset：允许新增，但不许缺
    rc = cmd_freeze(argparse.Namespace(facts=p_dyn, out=fxdir, mode="subset", name="dyn",
                                       argv=None, cmd=None, cwd="."))
    check(rc == EXIT_OK, "动态产物可冻结为 subset 基线", "rc=%d" % rc)
    fx_dyn = read_json(os.path.join(fxdir, "dyn.fixture.json"))
    more = [mkfact(1, "console", "x", mode="runtime"), mkfact(2, "console", "y", mode="runtime")]
    check(compare(fx_dyn, mkresult(more, producer="rev-runtime", mode="runtime")) == [],
          "subset 模式允许新增事实")
    e = compare(fx_dyn, mkresult([mkfact(2, "console", "y")], producer="rev-runtime", mode="runtime"))
    check(bool(e) and any("缺失" in x for x in e), "subset 模式仍不许缺失", str(e)[:80])

    # 10. 非 revfact 格式必须拒绝
    p_bad = os.path.join(tmp, "bad.json")
    write_json(p_bad, {"schema": "other/1", "facts": []})
    try:
        load_facts(p_bad)
        check(False, "非同 schema 文件必须拒绝")
    except ValueError:
        check(True, "非同 schema 文件必须拒绝")

    # 11. diff 自身
    pa, pb = os.path.join(tmp, "a.json"), os.path.join(tmp, "b.json")
    write_json(pa, mkresult(base_facts))
    write_json(pb, mkresult(base_facts))
    check(cmd_diff(argparse.Namespace(a=pa, b=pb)) == EXIT_OK, "相同两份 diff 应无差异")
    write_json(pb, mkresult(base_facts[:2]))
    check(cmd_diff(argparse.Namespace(a=pa, b=pb)) == EXIT_MISMATCH, "不同两份 diff 必须报差异")

    # 12. 真实重跑：用 rev-static 在真实 PE 上跑一次，再重放
    import shutil
    rs = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "rev-static", "scripts", "cli.py"))
    sample = "C:/Windows/System32/notepad.exe"
    if os.path.exists(rs) and os.path.exists(sample):
        out1 = os.path.join(tmp, "r1")
        argv = [sys.executable, rs, "strings", "--sample", sample, "--out", out1,
                "--min-len", "6", "--limit", "300"]
        r1 = subprocess.run(argv, capture_output=True, text=True)
        check(r1.returncode == 0, "rev-static strings 可运行（真实 PE）", r1.stderr[-120:])
        p_fx = os.path.join(tmp, "real")
        rc = cmd_freeze(argparse.Namespace(facts=os.path.join(out1, "facts", "strings.json"),
                                           out=p_fx, mode="exact", name="real",
                                           argv=json.dumps(argv), cmd=None, cwd="."))
        check(rc == EXIT_OK, "真实产物可冻结", "rc=%d" % rc)
        fx_real = read_json(os.path.join(p_fx, "real.fixture.json"))
        # 同命令再跑一次到不同目录
        argv2 = list(argv)
        argv2[argv2.index("--out") + 1] = os.path.join(tmp, "r2")
        out2 = os.path.join(tmp, "r2")
        r2 = subprocess.run(argv2, capture_output=True, text=True)
        check(r2.returncode == 0, "第二次重跑成功")
        res2 = load_facts(os.path.join(out2, "facts", "strings.json"))
        errs = compare(fx_real, res2)
        check(errs == [], "真实 PE 上两次独立运行结果完全一致（容忍度 0）", str(errs)[:120])
    else:
        check(True, "跳过真实 PE 重放（样本或 rev-static 不可用）")

    ok = sum(1 for c, _, _ in checks if c)
    for c, name, detail in checks:
        if not c:
            print("FAIL " + name + ("   -> " + str(detail) if detail else ""))
    print("自检 %d/%d 通过" % (ok, len(checks)))
    if ok != len(checks):
        print("SELFTEST FAILED")
        return EXIT_INVALID
    print("SELFTEST PASSED")
    return EXIT_OK


# ---------------------------------------------------------------- 入口

def main(argv=None):
    ap = argparse.ArgumentParser(prog="rev-verify", description="验证对拍：fixture 冻结与零容忍重放")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("freeze", help="把 facts 冻结为可重放基线")
    p.add_argument("--facts", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--mode", default="exact", choices=["exact", "subset"])
    p.add_argument("--name")
    p.add_argument("--argv", help='JSON 数组，例如 ["python","cli.py","pe","--sample","x"]')
    p.add_argument("--cmd", help="命令字符串（次选，Windows 下引号易失真）")
    p.add_argument("--cwd", default=".")
    p.set_defaults(fn=cmd_freeze)

    p = sub.add_parser("replay", help="重跑并零容忍比对")
    p.add_argument("--fixture", required=True)
    p.add_argument("--facts", help="现成产物路径（与 --cmd 二选一）")
    p.add_argument("--argv")
    p.add_argument("--cmd")
    p.add_argument("--cwd")
    p.set_defaults(fn=cmd_replay)

    p = sub.add_parser("diff", help="比对两份 facts 文件")
    p.add_argument("--a", required=True)
    p.add_argument("--b", required=True)
    p.set_defaults(fn=cmd_diff)

    p = sub.add_parser("selftest", help="自检（含真实 PE 双跑一致性）")
    p.set_defaults(fn=cmd_selftest)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
