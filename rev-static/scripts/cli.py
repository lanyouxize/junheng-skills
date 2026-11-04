#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rev-static —— 静态解构（只产候选事实，绝不写正式证据库）。

五通道分两类：
  零依赖（纯 Python，裸机可用）    strings / pe-imports / pe-sections
  外部工具（缺失即报 unavailable） ghidra / dotnet / jadx / apk / asar / pyinstaller

设计铁律：
  1. 没有工具不是"返回空"，而是 `status=unavailable` + 具体原因 + exit 3。
     空数组会让下游误以为"没有事实"，这是本方案最不能犯的错。
  2. 每条事实必须带 locator（offset + length）与 digest（对该字节段实算的 sha256）。
     digest 是"可回读验证"的锚——selftest 会重算并比对。
  3. 不写 evidence.jsonl。候选事实交给 rev-core evidence add 才成为正式证据。

退出码：0 成功 / 1 校验失败 / 2 用法错误 / 3 前置缺失或工具不可用 / 4 策略拒绝
"""

import argparse
import hashlib
import io
import json
import math
import os
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta

EXIT_OK, EXIT_INVALID, EXIT_USAGE, EXIT_PRECOND, EXIT_POLICY = 0, 1, 2, 3, 4
HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(HERE)
TZ = timezone(timedelta(hours=8))

PRINTABLE = set(range(0x20, 0x7F)) | {0x09}


def now_iso():
    return datetime.now(TZ).replace(microsecond=0).isoformat()


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha256_file(path, limit=None):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        left = limit
        while True:
            n = 1 << 20 if left is None else min(1 << 20, left)
            if n <= 0:
                break
            c = f.read(n)
            if not c:
                break
            h.update(c)
            if left is not None:
                left -= len(c)
    return h.hexdigest()


def read_bytes(path, max_bytes):
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        data = f.read(max_bytes)
    return data, size, size > len(data)


def write_json(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


# ---------------------------------------------------------------- 工具探测

EXTERNAL = {
    "ghidra": ["analyzeHeadless", "analyzeHeadless.bat"],
    "dotnet": ["ilspycmd", "ilspycmd.exe"],
    "jadx": ["jadx", "jadx.bat", "jadx.exe"],
    "apktool": ["apktool", "apktool.bat"],
    "asar": ["asar", "asar.cmd", "npx"],
    "pycdc": ["pycdc", "pycdc.exe"],
}


def find_tool(names):
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


def detect_table():
    rows = {
        "python": {"path": sys.executable, "ok": True},
        "java": {"path": find_tool(["java"]), "ok": bool(find_tool(["java"]))},
        "node": {"path": find_tool(["node"]), "ok": bool(find_tool(["node"]))},
    }
    for k, names in EXTERNAL.items():
        p = find_tool(names)
        rows[k] = {"path": p, "ok": bool(p)}
    return rows


def cmd_detect(args):
    rows = detect_table()
    print(f"{'tool':<12} {'状态':<6} 路径")
    for k, v in rows.items():
        print(f"{k:<12} {'可用' if v['ok'] else '缺失':<6} {v['path'] or '—'}")
    miss = [k for k, v in rows.items() if not v["ok"] and k in EXTERNAL]
    if miss:
        print(f"\n不可用的外部通道: {', '.join(miss)}"
              f"\n零依赖通道（strings / pe）不受影响，仍然可用。")
    if args.json:
        write_json(args.json, {"schema": "revstatic-detect/1", "generated_at": now_iso(),
                               "tools": {k: {"path": v["path"], "available": v["ok"]} for k, v in rows.items()}})
        print(f"\nwritten: {args.json}")
    return EXIT_OK


# ---------------------------------------------------------------- 事实封装

def make_result(channel, sample, target_id, status, facts, stats, reason=None, tool=None):
    return {
        "schema": "revfact/1",
        "producer": "rev-static",
        "channel": channel,
        "target_id": target_id,
        "sample": os.path.abspath(sample),
        "sample_sha256": sha256_file(sample),
        "tool": tool or {"name": f"rev-static/{channel}", "version": "1.0.0"},
        "generated_at": now_iso(),
        "status": status,
        "unavailable_reason": reason,
        "facts": facts,
        "stats": stats,
    }


def fact(channel, idx, kind, value, file_sha, offset, raw, **extra):
    f = {
        "id": f"{channel}-{idx:04d}",
        "kind": kind,
        "value": value,
        "locator": {"file_sha256": file_sha, "offset": offset, "length": len(raw)},
        "digest": {"algo": "sha256", "value": sha256_bytes(raw)},
        "confidence_hint": "E1",
    }
    f.update(extra)
    return f


def target_id_of(sample):
    return "tgt-" + sha256_file(sample, limit=1 << 20)[:6]


def emit(out_dir, channel, result):
    p = os.path.join(out_dir, "facts", f"{channel}.json")
    write_json(p, result)
    n = len(result["facts"])
    print(f"{channel:<14} status={result['status']:<12} facts={n}")
    if result["unavailable_reason"]:
        print(f"  原因: {result['unavailable_reason']}")
    print(f"  written: {p}")
    return EXIT_OK


# ---------------------------------------------------------------- strings

def cmd_strings(args):
    data, total, truncated = read_bytes(args.sample, args.max_bytes)
    fsha = sha256_file(args.sample)
    tid = args.target_id or target_id_of(args.sample)
    facts, idx, cut = [], 1, False

    def add(kind, value, off, raw):
        nonlocal idx, cut
        if idx > args.limit:
            cut = True
            return
        facts.append(fact("strings", idx, kind, value[:200], fsha, off, raw))
        idx += 1

    # ASCII 连续可打印串
    start = None
    for i, b in enumerate(data):
        if b in PRINTABLE:
            if start is None:
                start = i
        else:
            if start is not None and i - start >= args.min_len:
                add("string-ascii", data[start:i].decode("latin-1"), start, data[start:i])
            start = None
    if start is not None and len(data) - start >= args.min_len:
        add("string-ascii", data[start:].decode("latin-1"), start, data[start:])

    # UTF-16LE：可打印 + 0x00 成对。
    # 起点按 1 字节推进而非 2 —— UTF-16 序列在文件里不保证偶对齐，
    # 只走偶数偏移会整段漏掉（合成样本已把这个失效模式钉住）。
    if args.utf16:
        i = 0
        n = len(data)
        while i + 3 < n:
            s = i
            while i + 3 < n and data[i] in PRINTABLE and data[i + 1] == 0:
                i += 2
            if i - s >= args.min_len * 2:
                raw = data[s:i]
                add("string-utf16le", raw.decode("utf-16-le", errors="replace"), s, raw)
            if i == s:
                i += 1

    stats = {"total_bytes": total, "scanned_bytes": len(data),
             "file_truncated": truncated, "results_truncated": cut,
             "min_len": args.min_len, "limit": args.limit,
             "by_kind": dict(Counter(f["kind"] for f in facts))}
    emit(args.out, "strings", make_result("strings", args.sample, tid, "ok", facts, stats))
    return EXIT_OK


# ---------------------------------------------------------------- PE 解析

def _u16(b, o):
    return int.from_bytes(b[o:o + 2], "little")


def _u32(b, o):
    return int.from_bytes(b[o:o + 4], "little")


def _u64(b, o):
    return int.from_bytes(b[o:o + 8], "little")


def _cstr(b, off, limit=512):
    end = b.find(b"\x00", off)
    if end < 0 or end - off > limit:
        end = min(off + limit, len(b))
    return b[off:end]


def parse_pe(buf):
    """返回 dict(sections, imports, is64, machine)，失败返回 None。"""
    if len(buf) < 0x40 or buf[:2] != b"MZ":
        return None
    e = _u32(buf, 0x3C)
    if e <= 0 or e + 24 > len(buf) or buf[e:e + 4] != b"PE\x00\x00":
        return None
    coff = e + 4
    machine = _u16(buf, coff)
    nsec = _u16(buf, coff + 2)
    size_opt = _u16(buf, coff + 16)
    opt = coff + 20
    magic = _u16(buf, opt)
    is64 = magic == 0x20B
    num_dd_off = opt + (108 if is64 else 92)
    dd_off = opt + (112 if is64 else 96)
    num_dd = _u32(buf, num_dd_off) if num_dd_off + 4 <= len(buf) else 0

    sec_off = opt + size_opt
    sections = []
    for i in range(nsec):
        o = sec_off + i * 40
        if o + 40 > len(buf):
            break
        sections.append({
            "name": buf[o:o + 8].rstrip(b"\x00").decode("latin-1", "replace"),
            "vsize": _u32(buf, o + 8),
            "vaddr": _u32(buf, o + 12),
            "raw_size": _u32(buf, o + 16),
            "raw_ptr": _u32(buf, o + 20),
            "header_off": o,
        })

    def rva2off(rva):
        for s in sections:
            span = max(s["vsize"], s["raw_size"])
            if s["vaddr"] <= rva < s["vaddr"] + span:
                return s["raw_ptr"] + (rva - s["vaddr"])
        return None

    imports = []
    if num_dd > 1 and dd_off + 16 <= len(buf):
        imp_rva = _u32(buf, dd_off + 8)   # data directory[1] = import
        if imp_rva:
            off = rva2off(imp_rva)
            while off and off + 20 <= len(buf):
                desc = buf[off:off + 20]
                if desc == b"\x00" * 20:
                    break
                oft, _ts, _fc, name_rva = _u32(desc, 0), _u32(desc, 4), _u32(desc, 8), _u32(desc, 12)
                ft = _u32(desc, 16)
                n_off = rva2off(name_rva) if name_rva else None
                if n_off is None:
                    off += 20
                    continue
                dll_raw = _cstr(buf, n_off, 260)
                imports.append({"dll": dll_raw.decode("latin-1", "replace"),
                                "dll_offset": n_off, "dll_length": len(dll_raw),
                                "functions": []})
                thunk_rva = oft or ft
                t_off = rva2off(thunk_rva) if thunk_rva else None
                step = 8 if is64 else 4
                guard = 0
                while t_off and t_off + step <= len(buf) and guard < 4096:
                    val = _u64(buf, t_off) if is64 else _u32(buf, t_off)
                    if val == 0:
                        break
                    if not (val & (1 << (63 if is64 else 31))):
                        fn_off = rva2off(val & 0x7FFFFFFF if is64 else val)
                        if fn_off is not None and fn_off + 2 < len(buf):
                            nm = _cstr(buf, fn_off + 2, 256)
                            if nm:
                                imports[-1]["functions"].append({
                                    "name": nm.decode("latin-1", "replace"),
                                    "offset": fn_off + 2, "length": len(nm)})
                    t_off += step
                    guard += 1
                off += 20
    return {"sections": sections, "imports": imports, "is64": is64, "machine": machine,
            "num_dd": num_dd}


def entropy(b):
    if not b:
        return 0.0
    c = Counter(b)
    n = len(b)
    return round(-sum((v / n) * math.log2(v / n) for v in c.values()), 3)


def cmd_pe(args):
    data, total, truncated = read_bytes(args.sample, args.max_bytes)
    fsha = sha256_file(args.sample)
    tid = args.target_id or target_id_of(args.sample)
    pe = parse_pe(data)
    if pe is None:
        r = make_result("pe", args.sample, tid, "unavailable", [],
                        {"total_bytes": total},
                        reason="不是可解析的 PE 文件（MZ/PE 签名校验失败）")
        emit(args.out, "pe", r)
        return EXIT_PRECOND

    facts, idx = [], 1
    for s in pe["sections"]:
        raw = data[s["raw_ptr"]:s["raw_ptr"] + s["raw_size"]] if s["raw_size"] else b""
        facts.append(fact("pe", idx, "section", s["name"], fsha, s["header_off"],
                          data[s["header_off"]:s["header_off"] + 8],
                          vaddr=s["vaddr"], raw_ptr=s["raw_ptr"], raw_size=s["raw_size"],
                          entropy=entropy(raw)))
        idx += 1
    for imp in pe["imports"]:
        facts.append(fact("pe", idx, "import-dll", imp["dll"], fsha, imp["dll_offset"],
                          data[imp["dll_offset"]:imp["dll_offset"] + imp["dll_length"]]))
        idx += 1
        for fn in imp["functions"]:
            facts.append(fact("pe", idx, "import-func", fn["name"], fsha, fn["offset"],
                              data[fn["offset"]:fn["offset"] + fn["length"]], dll=imp["dll"]))
            idx += 1

    high = [f["value"] for f in facts if f["kind"] == "section" and f.get("entropy", 0) > 7.2]
    stats = {"total_bytes": total, "file_truncated": truncated, "is64": pe["is64"],
             "machine": hex(pe["machine"]), "sections": len(pe["sections"]),
             "import_dlls": len(pe["imports"]),
             "import_funcs": sum(len(i["functions"]) for i in pe["imports"]),
             "high_entropy_sections": high,
             "packer_hint": bool(high)}
    emit(args.out, "pe", make_result("pe", args.sample, tid, "ok", facts, stats))
    return EXIT_OK


# ---------------------------------------------------------------- 外部通道

EXT_SPEC = {
    "ghidra": {
        "bins": EXTERNAL["ghidra"],
        "hint": "需 Ghidra + JDK 21；见 06-落地手册 第 3 步",
        "args": ["{bin}", "--help"],
    },
    "dotnet": {
        "bins": EXTERNAL["dotnet"],
        "hint": "需 dotnet tool install -g ilspycmd",
        "args": ["{bin}", "--version"],
    },
    "jadx": {
        "bins": EXTERNAL["jadx"],
        "hint": "需 jadx + JDK；见 06-落地手册 第 4 步",
        "args": ["{bin}", "--version"],
    },
    "apktool": {
        "bins": EXTERNAL["apktool"],
        "hint": "需 apktool + JDK；见 06-落地手册 第 4 步",
        "args": ["{bin}", "--version"],
    },
    "asar": {
        "bins": EXTERNAL["asar"],
        "hint": "需 Node；npx asar extract <app.asar> <out>",
        "args": ["{bin}", "--version"],
    },
    "pyinstaller": {
        "bins": EXTERNAL["pycdc"],
        "hint": "需 pycdc；PyInstaller 包先用 pyinstxtractor-ng 取 CArchive",
        "args": ["{bin}", "--version"],
    },
}


def cmd_external(args, channel):
    spec = EXT_SPEC[channel]
    tid = args.target_id or target_id_of(args.sample)
    binary = find_tool(spec["bins"])
    if not binary:
        reason = (f"工具不可用：未在 PATH 找到 {spec['bins'][0]}。{spec['hint']}。"
                  f"零依赖通道（strings / pe）不受影响。")
        r = make_result(channel, args.sample, tid, "unavailable", [], {}, reason=reason)
        emit(args.out, channel, r)
        print(f"\n以 exit 3 退出：这是『工具没装』，不是『分析结果为无』。", file=sys.stderr)
        return EXIT_PRECOND

    probe = [a if a != "{bin}" else binary for a in spec["args"]]
    try:
        p = subprocess.run(probe, capture_output=True, text=True, timeout=60)
        ver = (p.stdout or p.stderr).strip().splitlines()[:1]
    except Exception as e:  # noqa: BLE001
        ver = [f"probe failed: {e}"]
    facts = [fact(channel, 1, "tool-probe", binary, sha256_file(args.sample),
                  0, b"", note="工具已就位；实际分析参数需按目标形态补充")]
    stats = {"tool_path": binary, "probe": ver, "note": "本通道只做可用性探测与参数骨架，"
                                                      "具体分析命令由使用者按目标形态补齐并写入 reproduce"}
    emit(args.out, channel, make_result(
        channel, args.sample, tid, "partial", facts, stats,
        tool={"name": os.path.basename(binary), "version": ver[0] if ver else "unknown"}))
    return EXIT_OK


# ---------------------------------------------------------------- 自检

def cmd_selftest(args):
    sample = args.sample
    if not os.path.exists(sample):
        print(f"SKIP：样本不存在 {sample}", file=sys.stderr)
        return EXIT_PRECOND
    import tempfile
    tmp = tempfile.mkdtemp(prefix="revstatic-")
    fails = []

    def check(cond, label, detail=""):
        if not cond:
            fails.append(f"{label} {detail}")

    # 1. strings
    p = subprocess.run([sys.executable, os.path.join(HERE, "cli.py"), "strings",
                        "--sample", sample, "--out", tmp, "--min-len", "5", "--limit", "300"],
                       capture_output=True, text=True)
    check(p.returncode == 0, "strings 退出码应为 0", f"got={p.returncode} {p.stderr[:200]}")
    sfile = os.path.join(tmp, "facts", "strings.json")
    check(os.path.exists(sfile), "strings 结果文件应生成")
    if os.path.exists(sfile):
        r = json.load(io.open(sfile, encoding="utf-8"))
        check(len(r["facts"]) > 0, "strings 应至少产出 1 条事实")
        check(r["status"] == "ok", "strings status 应为 ok")
        # 关键判据：每条 digest 必须与文件字节实算一致
        with open(sample, "rb") as f:
            blob = f.read(r["stats"]["scanned_bytes"])
        bad = []
        for f_ in r["facts"]:
            loc = f_["locator"]
            seg = blob[loc["offset"]:loc["offset"] + loc["length"]]
            if hashlib.sha256(seg).hexdigest() != f_["digest"]["value"]:
                bad.append(f_["id"])
        check(not bad, "strings 每条 locator+digest 必须可回读验证", f"不一致 {bad[:3]}")

    # 2. pe
    q = subprocess.run([sys.executable, os.path.join(HERE, "cli.py"), "pe",
                        "--sample", sample, "--out", tmp], capture_output=True, text=True)
    pfile = os.path.join(tmp, "facts", "pe.json")
    check(os.path.exists(pfile), "pe 结果文件应生成")
    if os.path.exists(pfile):
        r = json.load(io.open(pfile, encoding="utf-8"))
        if args.expect_pe:
            check(q.returncode == 0, "样本应被识别为 PE", f"got={q.returncode}")
            check(r["stats"]["sections"] >= 2, "PE 应至少 2 个节", str(r["stats"]))
            check(len(r["facts"]) >= 4, "PE 应产出节与导入事实", f"facts={len(r['facts'])}")
            with open(sample, "rb") as f:
                blob = f.read()
            bad = [f_["id"] for f_ in r["facts"]
                   if hashlib.sha256(blob[f_["locator"]["offset"]:
                                          f_["locator"]["offset"] + f_["locator"]["length"]]).hexdigest()
                   != f_["digest"]["value"]]
            check(not bad, "pe 每条 locator+digest 必须可回读验证", f"不一致 {bad[:3]}")
        else:
            check(r["status"] in ("ok", "unavailable"), "非 PE 样本应给 ok 或 unavailable")

    # 3. 外部通道缺失时必须 unavailable 且 exit 3
    w = subprocess.run([sys.executable, os.path.join(HERE, "cli.py"), "ghidra",
                        "--sample", sample, "--out", tmp], capture_output=True, text=True)
    gfile = os.path.join(tmp, "facts", "ghidra.json")
    if args.expect_no_ghidra:
        check(w.returncode == EXIT_PRECOND, "缺 Ghidra 时应 exit 3（而非 0）", f"got={w.returncode}")
        check(os.path.exists(gfile), "缺工具时仍应写结果文件以留痕")
        if os.path.exists(gfile):
            r = json.load(io.open(gfile, encoding="utf-8"))
            check(r["status"] == "unavailable", "缺工具时 status 必须是 unavailable 而非 ok")
            check(r["facts"] == [], "缺工具时不得产出事实（避免空数组冒充『无事实』）")
            check(bool(r["unavailable_reason"]), "缺工具时必须给出原因")

    # 3.5 合成样本：证明扫描器在已知偏移上取到已知串（含 UTF-16LE）
    synth = os.path.join(tmp, "synth.bin")
    ascii_str = b"REVA-ASCII-MARKER"
    utf16_str = "REVA-UTF16-标记".encode("utf-16-le")
    blob = b"\x00" * 32 + ascii_str + b"\x00" * 16 + utf16_str + b"\x00" * 32
    with open(synth, "wb") as f:
        f.write(blob)
    a_off = 32
    u_off = 32 + len(ascii_str) + 16
    y = subprocess.run([sys.executable, os.path.join(HERE, "cli.py"), "strings",
                        "--sample", synth, "--out", tmp, "--min-len", "4", "--limit", "100"],
                       capture_output=True, text=True)
    check(y.returncode == 0, "合成样本 strings 应 exit 0", f"got={y.returncode}")
    sf = os.path.join(tmp, "facts", "strings.json")
    if os.path.exists(sf):
        rr = json.load(io.open(sf, encoding="utf-8"))
        got_a = [x for x in rr["facts"] if x["kind"] == "string-ascii" and "REVA-ASCII-MARKER" in x["value"]]
        got_u = [x for x in rr["facts"] if x["kind"] == "string-utf16le" and "REVA-UTF16" in x["value"]]
        check(bool(got_a), "应检出 ASCII 标记串")
        check(bool(got_u), "应检出 UTF-16LE 标记串")
        if got_a:
            check(got_a[0]["locator"]["offset"] == a_off,
                  "ASCII 串 offset 必须精确", f"期望 {a_off} 实为 {got_a[0]['locator']['offset']}")
            check(got_a[0]["locator"]["length"] == len(ascii_str),
                  "ASCII 串 length 必须精确", f"期望 {len(ascii_str)}")
        if got_u:
            check(got_u[0]["locator"]["offset"] == u_off,
                  "UTF-16 串 offset 必须精确", f"期望 {u_off} 实为 {got_u[0]['locator']['offset']}")
            check(got_u[0]["value"].startswith("REVA-UTF16-"),
                  "UTF-16 串解码应正确", repr(got_u[0]["value"])[:40])

    # 4. detect
    d = subprocess.run([sys.executable, os.path.join(HERE, "cli.py"), "detect"],
                       capture_output=True, text=True)
    check(d.returncode == 0, "detect 应 exit 0")
    check("python" in d.stdout, "detect 输出应含 python 行")

    shutil.rmtree(tmp, ignore_errors=True)
    if fails:
        for f in fails:
            print(f"FAIL {f}")
        print(f"\nSELFTEST FAILED  {len(fails)} 项")
        return EXIT_INVALID
    print("SELFTEST PASSED  所有 locator+digest 已回读验证")
    return EXIT_OK


# ---------------------------------------------------------------- 入口

def build_parser():
    p = argparse.ArgumentParser(prog="rev-static", description="静态解构：只产候选事实")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("detect", help="探测外部工具可用性")
    s.add_argument("--json", default=None)
    s.set_defaults(fn=cmd_detect)

    def common(sp):
        sp.add_argument("--sample", required=True)
        sp.add_argument("--out", required=True)
        sp.add_argument("--target-id", default=None)
        sp.add_argument("--max-bytes", type=int, default=268435456)

    s = sub.add_parser("strings", help="零依赖字符串提取（ASCII + UTF-16LE）")
    common(s)
    s.add_argument("--min-len", type=int, default=5)
    s.add_argument("--limit", type=int, default=5000)
    s.add_argument("--no-utf16", dest="utf16", action="store_false", default=True)
    s.set_defaults(fn=cmd_strings)

    s = sub.add_parser("pe", help="零依赖 PE 解析（节表 + 导入表 + 熵）")
    common(s)
    s.set_defaults(fn=cmd_pe)

    for name, help_text in [
        ("ghidra", "Ghidra headless 通道（需 JDK + Ghidra）"),
        ("dotnet", ".NET 通道（ilspycmd）"),
        ("jadx", "APK 代码通道（jadx）"),
        ("apk", "APK 资源通道（apktool）"),
        ("asar", "Electron 通道（asar）"),
        ("pyinstaller", "PyInstaller 通道（pycdc）"),
    ]:
        s = sub.add_parser(name, help=help_text)
        common(s)
        s.set_defaults(fn=(lambda a, ch=name: cmd_external(a, ch)))

    s = sub.add_parser("selftest", help="零依赖通道自检（digest 回读验证）")
    s.add_argument("--sample", default=r"C:\Windows\System32\notepad.exe")
    s.add_argument("--expect-pe", action="store_true", default=True)
    s.add_argument("--expect-no-ghidra", action="store_true", default=True)
    s.set_defaults(fn=cmd_selftest)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
