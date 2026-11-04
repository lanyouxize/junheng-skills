#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rev-core —— 逆向分析流水线的入口与证据闸。

职责：授权开单 / 形态识别 / 路由分派 / 证据写入与校验 / 报告投影。
不做：任何技术分析、不解析二进制内容（除识别文件头）、不下技术结论。

退出码约定（全模块统一，不可被覆盖）：
    0  成功
    1  校验失败（工件不合规 / 闸门未通过）
    2  用法错误
    3  前置条件缺失（缺 target.json / 缺样本）
    4  策略拒绝（越过授权边界）—— 任何模块不得把 4 降级为 1

用法见 SKILL.md；自检见 `cli.py selftest --materialize`。
"""

import argparse
import hashlib
import io
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta

EXIT_OK, EXIT_INVALID, EXIT_USAGE, EXIT_PRECOND, EXIT_POLICY = 0, 1, 2, 3, 4

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(HERE)
SCHEMA_PATH = os.path.join(SKILL_ROOT, "references", "schema", "reva-1.json")
FIXTURE_DIR = os.path.join(SKILL_ROOT, "references", "fixtures")
TZ = timezone(timedelta(hours=8))

ANSI_RED, ANSI_YEL, ANSI_DIM, ANSI_OFF = "\033[31m", "\033[33m", "\033[2m", "\033[0m"


def _color(code, text, enabled=True):
    return f"{code}{text}{ANSI_OFF}" if enabled and sys.stdout.isatty() else text


def now_iso():
    return datetime.now(TZ).replace(microsecond=0).isoformat()


def load_schema():
    with io.open(SCHEMA_PATH, encoding="utf-8") as f:
        return json.load(f)


def sha256_file(path, limit=None):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        remaining = limit
        while True:
            n = 1 << 20 if remaining is None else min(1 << 20, remaining)
            if n <= 0:
                break
            chunk = f.read(n)
            if not chunk:
                break
            h.update(chunk)
            if remaining is not None:
                remaining -= len(chunk)
    return h.hexdigest()


def is_hex64(s):
    return isinstance(s, str) and len(s) == 64 and re.fullmatch(r"[0-9a-f]{64}", s or "") is not None


def read_json(path):
    with io.open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def append_jsonl(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with io.open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(obj, ensure_ascii=False, sort_keys=True) + "\n")


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    out = []
    with io.open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


# ---------------------------------------------------------------- 校验核心

def validate_envelope(obj, schema):
    """外壳校验：必填 / 未定义字段 / schema 版本。"""
    env = schema["envelope"]
    errs = []
    if not isinstance(obj, dict):
        return ["工件必须是 JSON 对象"]
    missing = [k for k in env["required"] if k not in obj]
    if missing:
        errs.append(f"外壳缺字段: {', '.join(missing)}")
    extra = [k for k in obj.keys() if k not in env["allowed"] and k not in schema["kinds"].get(obj.get("kind"), {}).get("allowed", [])]
    if extra:
        errs.append(f"外壳含未定义字段: {', '.join(sorted(extra))}")
    if obj.get("schema") != env["schema_value"]:
        errs.append(f"schema 版本不符: 期望 {env['schema_value']}，实为 {obj.get('schema')!r}（不做静默兼容）")
    if obj.get("status") not in env["status_values"]:
        errs.append(f"status 非法: {obj.get('status')!r}")
    prov = obj.get("provenance")
    if not isinstance(prov, dict):
        errs.append("provenance 必须是对象")
    else:
        pv = env["provenance"]
        pm = [k for k in pv["required"] if k not in prov]
        if pm:
            errs.append(f"provenance 缺字段: {', '.join(pm)}")
        pex = [k for k in prov.keys() if k not in pv["allowed"]]
        if pex:
            errs.append(f"provenance 含未定义字段: {', '.join(sorted(pex))}")
        ins = prov.get("inputs_sha256")
        if ins is not None and (not isinstance(ins, list) or any(not is_hex64(x) for x in ins)):
            errs.append("provenance.inputs_sha256 必须为 sha256 十六进制数组")
    return errs


def validate_evidence(obj, schema):
    spec = schema["kinds"]["evidence"]
    errs = []
    # 先判禁止字段：否则 confidence 会被外壳的「未定义字段」先吃掉，报错指向就错了
    forb = [k for k in spec.get("forbidden", []) if isinstance(obj, dict) and k in obj]
    if forb:
        errs.append(f"禁止手填字段: {', '.join(forb)}（confidence 必须由 grade 派生）")
    errs += validate_envelope(obj, schema)
    if errs and not isinstance(obj, dict):
        return errs
    if any(e.startswith("外壳缺字段") or e.startswith("schema 版本不符") for e in errs):
        return errs

    grade = obj.get("grade")
    if grade not in spec["grade_values"]:
        errs.append(f"grade 非法: {grade!r}，允许 {spec['grade_values']}")
        return errs
    ch = obj.get("channel")
    if ch not in spec["channel_values"]:
        errs.append(f"channel 非法: {ch!r}，允许 {spec['channel_values']}")

    needs_full = grade in ("E1", "E2", "E3")
    loc, dig, rep = obj.get("locator"), obj.get("digest"), obj.get("reproduce")

    if needs_full and not isinstance(loc, dict):
        errs.append(f"{grade} 级证据必须有 locator（缺则只能标 E0）")
    if needs_full and not isinstance(dig, dict):
        errs.append(f"{grade} 级证据必须有 digest（缺则只能标 E0）")
    if needs_full and not isinstance(rep, dict):
        errs.append(f"{grade} 级证据必须有 reproduce（缺则只能标 E0）")

    if isinstance(loc, dict):
        lspec = spec["locator"]
        lm = [k for k in lspec["required"] if k not in loc]
        if lm:
            errs.append(f"locator 缺字段: {', '.join(lm)}")
        lex = [k for k in loc.keys() if k not in lspec["allowed"]]
        if lex:
            errs.append(f"locator 含未定义字段: {', '.join(sorted(lex))}")
        if not is_hex64(loc.get("file_sha256")):
            errs.append("locator.file_sha256 必须是 sha256 十六进制")
        length = loc.get("length")
        if not isinstance(length, int) or isinstance(length, bool) or length <= 0:
            errs.append(f"locator.length 必须是正整数，实为 {length!r}")
        mode = loc.get("mode", lspec.get("mode_default", "file"))
        if mode not in lspec.get("mode_values", ["file"]):
            errs.append(f"locator.mode 非法: {mode!r}，允许 {lspec.get('mode_values')}")
        has_addr = isinstance(loc.get("addr"), int) and not isinstance(loc.get("addr"), bool)
        has_off = isinstance(loc.get("offset"), int) and not isinstance(loc.get("offset"), bool)
        if mode == "file" and needs_full and not (has_addr or has_off):
            errs.append("locator 必须给出 addr 或 offset 之一")
        if mode == "runtime":
            # 动态证据没有文件偏移，必须给运行时四元组；缺一项就不可复现
            rt = loc.get("runtime")
            rspec = lspec.get("runtime", {})
            if not isinstance(rt, dict):
                errs.append("locator.mode=runtime 时必须提供 runtime 子对象")
            else:
                rm = [k for k in rspec.get("required", []) if k not in rt]
                if rm:
                    errs.append(f"locator.runtime 缺字段: {', '.join(rm)}")
                rex = [k for k in rt.keys() if k not in rspec.get("allowed", list(rt.keys()))]
                if rex:
                    errs.append(f"locator.runtime 含未定义字段: {', '.join(sorted(rex))}")
                pid = rt.get("pid")
                if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
                    errs.append(f"locator.runtime.pid 必须是正整数，实为 {pid!r}")
                rva = rt.get("rva")
                if not isinstance(rva, int) or isinstance(rva, bool) or rva < 0:
                    errs.append(f"locator.runtime.rva 必须是非负整数，实为 {rva!r}")
                for k in ("host", "module", "session"):
                    v = rt.get(k)
                    if not isinstance(v, str) or not v.strip():
                        errs.append(f"locator.runtime.{k} 必须是非空字符串")
                if rt.get("host") not in ("windows", "linux", "android"):
                    errs.append(f"locator.runtime.host 非法: {rt.get('host')!r}")
            # 一致性：静态通道不可能产出运行时定位符
            if obj.get("channel") == "static":
                errs.append("channel=static 却给出 locator.mode=runtime（静态通道不得产出运行时定位符）")
        if mode == "file" and "runtime" in loc:
            errs.append("locator.mode=file 时不得带 runtime 子对象")

    if isinstance(dig, dict):
        dspec = spec["digest"]
        dm = [k for k in dspec["required"] if k not in dig]
        if dm:
            errs.append(f"digest 缺字段: {', '.join(dm)}")
        dex = [k for k in dig.keys() if k not in dspec["allowed"]]
        if dex:
            errs.append(f"digest 含未定义字段: {', '.join(sorted(dex))}")
        if dig.get("algo") not in dspec["algo_values"]:
            errs.append(f"digest.algo 非法: {dig.get('algo')!r}")
        if not is_hex64(dig.get("value")):
            errs.append("digest.value 必须是 sha256 十六进制（64 位小写十六进制）")

    if isinstance(rep, dict):
        rspec = spec["reproduce"]
        rm = [k for k in rspec["required"] if k not in rep]
        if rm:
            errs.append(f"reproduce 缺字段: {', '.join(rm)}")
        rex = [k for k in rep.keys() if k not in rspec["allowed"]]
        if rex:
            errs.append(f"reproduce 含未定义字段: {', '.join(sorted(rex))}")
        cmd = rep.get("cmd")
        if needs_full and (not isinstance(cmd, str) or not cmd.strip()):
            errs.append("reproduce.cmd 必须是非空命令")
        if "env" in rep and not isinstance(rep["env"], dict):
            errs.append("reproduce.env 必须是对象（可为空对象）")
    return errs


def validate_finding(obj, schema, evidence_index):
    spec = schema["kinds"]["finding"]
    errs = []
    forb = [k for k in spec.get("forbidden", []) if isinstance(obj, dict) and k in obj]
    if forb:
        errs.append(f"禁止手填字段: {', '.join(forb)}（finding 的 confidence 同样由 grade 派生）")
    errs += validate_envelope(obj, schema)
    if not isinstance(obj, dict):
        return errs
    if any(e.startswith("外壳缺字段") or e.startswith("schema 版本不符") for e in errs):
        return errs

    for k in ("claim", "scope"):
        if not isinstance(obj.get(k), str) or not obj[k].strip():
            errs.append(f"{k} 必须是非空字符串")
    refs = obj.get("evidence_refs")
    if not isinstance(refs, list) or not refs:
        errs.append("evidence_refs 必须是非空数组（无证据的结论不得成为 finding）")
        refs = []
    for r in refs:
        if r not in evidence_index:
            errs.append(f"引用了不存在的证据: {r!r}")
    for k in ("unknowns", "contradicts"):
        if not isinstance(obj.get(k), list):
            errs.append(f"{k} 必须是数组（可为空数组，但字段必须有）")
    state = obj.get("state")
    if state not in spec["state_values"]:
        errs.append(f"state 非法: {state!r}")
    if state == "corroborated":
        channels = {evidence_index[r]["channel"] for r in refs if r in evidence_index}
        if len(channels) < 2:
            errs.append(f"state=corroborated 需 >=2 条不同 channel 的证据，当前仅 {sorted(channels) or '无'}")
    return errs


def validate_unknown(obj, schema):
    errs = validate_envelope(obj, schema)
    if errs:
        return errs
    for k in ("question", "why_unknown", "unblock_condition", "owner_module"):
        if not isinstance(obj.get(k), str) or not obj[k].strip():
            errs.append(f"{k} 必须是非空字符串")
    if not isinstance(obj.get("blocking"), bool):
        errs.append("blocking 必须是布尔值")
    if not isinstance(obj.get("tried"), list):
        errs.append("tried 必须是数组（可为空数组，但字段必须有）")
    return errs


def validate_rebuild_target(obj, schema):
    errs = validate_envelope(obj, schema)
    if errs:
        return errs
    spec = schema["kinds"]["rebuild-target"]
    if obj.get("surface") not in spec["surface_values"]:
        errs.append(f"surface 非法: {obj.get('surface')!r}")
    if not isinstance(obj.get("spec_ref"), str) or not obj["spec_ref"].strip():
        errs.append("spec_ref 必须是非空字符串")
    for k in ("fixtures", "dod", "unknowns"):
        if not isinstance(obj.get(k), list):
            errs.append(f"{k} 必须是数组")
    for i, item in enumerate(obj.get("dod") or []):
        if not isinstance(item, str) or not item.strip().startswith("rev-"):
            errs.append(f"dod[{i}] 必须是以 'rev-' 开头的可机检命令，实为 {item!r}")
    return errs


def validate_target(obj):
    errs = []
    if not isinstance(obj, dict):
        return ["工件必须是 JSON 对象"]
    if obj.get("kind") != "target":
        errs.append(f"kind 应为 target，实为 {obj.get('kind')!r}")
    if not (isinstance(obj.get("target_id"), str) and obj["target_id"].startswith("tgt-")):
        errs.append("target_id 必须形如 tgt-xxxxxx")
    if not is_hex64(obj.get("sample_sha256")):
        errs.append("sample_sha256 必须是 sha256 十六进制")
    auth = obj.get("authorization")
    if not isinstance(auth, dict):
        errs.append("authorization 必须是对象")
    else:
        need = ["basis", "evidence_ref", "purpose", "scope_whitelist", "reviewed_at"]
        miss = [k for k in need if k not in auth]
        if miss:
            errs.append(f"authorization 缺字段: {', '.join(miss)}")
        if not auth.get("scope_whitelist"):
            errs.append("scope_whitelist 不得为空（白名单没写进去的能力一律不许调）")
    return errs


def validate_triage(obj):
    errs = []
    if not isinstance(obj, dict):
        return ["工件必须是 JSON 对象"]
    if obj.get("kind") != "triage":
        errs.append(f"kind 应为 triage，实为 {obj.get('kind')!r}")
    for k in ("format", "route_id"):
        if not isinstance(obj.get(k), str) or not obj[k].strip():
            errs.append(f"{k} 必须是非空字符串")
    dag = obj.get("dag")
    if not isinstance(dag, list):
        errs.append("dag 必须是数组")
    elif obj.get("route_policy") == "no-static" and any(str(n).startswith("static.") for n in dag):
        errs.append("route_policy=no-static 但 dag 含 static.* 节点")
    return errs


def validate_artifact(path, schema, evidence_index):
    try:
        obj = read_json(path)
    except Exception as e:  # noqa: BLE001
        return [f"读取失败: {e}"], None
    kind = obj.get("kind") if isinstance(obj, dict) else None
    if kind == "evidence":
        return validate_evidence(obj, schema), obj
    if kind == "finding":
        return validate_finding(obj, schema, evidence_index), obj
    if kind == "unknown":
        return validate_unknown(obj, schema), obj
    if kind == "rebuild-target":
        return validate_rebuild_target(obj, schema), obj
    if kind == "target":
        return validate_target(obj), obj
    if kind == "triage":
        return validate_triage(obj), obj
    return [f"未知 kind: {kind!r}"], obj


def derive_confidence(grade, channels, schema):
    ceil = schema["confidence"]["grade_ceiling"].get(grade, 0.0)
    return round(min(ceil, 0.35 + 0.25 * len(set(channels))), 2)


# ---------------------------------------------------------------- 命令实现

def _tdir(d):
    t = os.path.join(d, "target.json")
    if not os.path.exists(t):
        print(_color(ANSI_RED, f"缺 target.json：{t}。先跑 rev-core init"), file=sys.stderr)
        sys.exit(EXIT_PRECOND)
    return t, read_json(t)


MAGIC = [
    (b"MZ", "pe"),
    (b"\x7fELF", "elf"),
    (b"\xca\xfe\xba\xbe", "macho-or-class"),
    (b"PK\x03\x04", "zip"),
]


def detect_format(path):
    with open(path, "rb") as f:
        head = f.read(4096)
    fmt, arch, detail = "unknown", "unknown", []
    for magic, name in MAGIC:
        if head.startswith(magic):
            fmt = name
            break
    if fmt == "pe":
        arch = "x86-64" if head[:2] == b"MZ" and b"PE\x00\x00" in head and _pe_machine(head) == 0x8664 else "x86"
        if b"mscoree.dll" in head:
            detail.append("CLR 引用命中（疑似 .NET 程序集）")
            fmt = "pe-dotnet"
    if fmt == "zip":
        if b"AndroidManifest.xml" in head or b"classes.dex" in head:
            fmt, arch = "apk", "dalvik"
            detail.append("zip 内含 AndroidManifest/classes.dex")
        elif b"app.asar" in head:
            fmt, arch = "electron", "js"
            detail.append("zip 内含 app.asar")
    return fmt, arch, detail


def _pe_machine(head):
    idx = head.find(b"PE\x00\x00")
    if idx < 0 or idx + 6 > len(head):
        return None
    return int.from_bytes(head[idx + 4:idx + 6], "little")


ROUTES = {
    "pe":            ("native",        ["static.native", "runtime.frida", "runtime.proto", "verify.replay"]),
    "pe-dotnet":     ("dotnet",        ["static.dotnet", "runtime.proto", "verify.replay"]),
    "apk":           ("apk",           ["static.apk", "runtime.frida", "verify.replay"]),
    "electron":      ("electron",      ["static.js", "runtime.cdp", "runtime.proxy", "verify.replay"]),
    "zip":           ("archive",       ["static.js", "runtime.proto", "verify.replay"]),
    "elf":           ("native-elf",    ["static.native", "runtime.proto", "verify.replay"]),
    "macho-or-class": ("macho-or-class", ["static.native", "runtime.proto", "verify.replay"]),
}


def filter_dag(dag, policy):
    if policy == "no-static":
        kept = [n for n in dag if not n.startswith("static.")]
        return kept
    return dag


def cmd_init(args):
    basis_ok = {"self-owned", "written", "open-source", "public-spec"}
    purpose_ok = {"interop", "security-test", "malware-analysis", "migration", "compete-observe"}
    schema = load_schema()
    prohibited = set(schema["target"]["prohibited"])

    caps = set(args.allow or [])
    hit = caps & prohibited
    if args.basis not in basis_ok:
        print(_color(ANSI_RED, f"策略拒绝(4)：授权依据非法 {args.basis!r}"), file=sys.stderr)
        return EXIT_POLICY
    if args.purpose not in purpose_ok:
        print(_color(ANSI_RED, f"策略拒绝(4)：分析目的非法 {args.purpose!r}"), file=sys.stderr)
        return EXIT_POLICY
    if hit:
        print(_color(ANSI_RED, f"策略拒绝(4)：申请了禁止能力 {sorted(hit)}"), file=sys.stderr)
        return EXIT_POLICY
    if not os.path.exists(args.target):
        print(_color(ANSI_YEL, f"前置缺失(3)：样本不存在 {args.target}"), file=sys.stderr)
        return EXIT_PRECOND

    os.makedirs(args.dir, exist_ok=True)
    target_id = "tgt-" + sha256_file(args.target, limit=1 << 20)[:6]
    obj = {
        "schema": "reva/1",
        "kind": "target",
        "target_id": target_id,
        "sample": os.path.abspath(args.target),
        "sample_sha256": sha256_file(args.target),
        "authorization": {
            "basis": args.basis,
            "evidence_ref": args.evidence_ref or "",
            "purpose": args.purpose,
            "scope_whitelist": sorted(caps) or ["read-only"],
            "reviewed_at": now_iso(),
        },
        "route_policy": "no-static" if args.purpose == "compete-observe" else "default",
        "prohibited": sorted(prohibited),
    }
    write_json(os.path.join(args.dir, "target.json"), obj)
    print(f"target_id={target_id}  purpose={args.purpose}  policy={obj['route_policy']}")
    print(f"written: {os.path.join(args.dir, 'target.json')}")
    return EXIT_OK


def cmd_triage(args):
    tpath, tgt = _tdir(args.dir)
    sample = tgt.get("sample")
    if not sample or not os.path.exists(sample):
        print(_color(ANSI_YEL, f"前置缺失(3)：样本不可读 {sample}"), file=sys.stderr)
        return EXIT_PRECOND
    fmt, arch, detail = detect_format(sample)
    if fmt not in ROUTES:
        print(_color(ANSI_RED, f"无法识别格式（{fmt}）——按规矩不得进入下游"), file=sys.stderr)
        return EXIT_INVALID
    route_id, dag = ROUTES[fmt]
    dag = filter_dag(dag, tgt.get("route_policy", "default"))
    obj = {
        "schema": "reva/1", "kind": "triage", "id": "tri-" + tgt["target_id"][-6:],
        "produced_by": "rev-core", "produced_at": now_iso(), "target_id": tgt["target_id"],
        "provenance": {"tool": "rev-core/triage", "version": "1.0.0",
                       "command": f"triage {sample}", "inputs_sha256": [sha256_file(sample)]},
        "status": "ok", "refs": [],
        "format": fmt, "arch": arch, "route_id": route_id, "dag": dag,
        "route_policy": tgt.get("route_policy", "default"), "detail": detail,
    }
    write_json(os.path.join(args.dir, "triage.json"), obj)
    print(f"format={fmt}  arch={arch}  route={route_id}")
    print("dag = " + " -> ".join(dag or ["(空：策略过滤后无可用节点)"]))
    if not dag:
        print(_color(ANSI_RED, "策略过滤后 DAG 为空——该目的下这个目标不允许分析"), file=sys.stderr)
        return EXIT_POLICY
    return EXIT_OK


def cmd_dispatch(args):
    _, tgt = _tdir(args.dir)
    t = os.path.join(args.dir, "triage.json")
    if not os.path.exists(t):
        print(_color(ANSI_YEL, "前置缺失(3)：先跑 triage"), file=sys.stderr)
        return EXIT_PRECOND
    tr = read_json(t)
    dag = filter_dag(tr["dag"], tgt.get("route_policy", "default"))
    if any(n.startswith("static.") for n in dag) and tgt.get("route_policy") == "no-static":
        print(_color(ANSI_RED, "策略拒绝(4)：no-static 路由下出现静态节点"), file=sys.stderr)
        return EXIT_POLICY
    print("\n".join(f"{i+1}. {n}" for i, n in enumerate(dag)))
    return EXIT_OK


def cmd_evidence_add(args):
    schema = load_schema()
    _, tgt = _tdir(args.dir)
    obj = read_json(args.file)
    errs = validate_evidence(obj, schema)
    if errs:
        for e in errs:
            print(_color(ANSI_RED, "E " + e), file=sys.stderr)
        print(_color(ANSI_RED, f"拒绝写入（{len(errs)} 项不合规）"), file=sys.stderr)
        return EXIT_INVALID
    if obj.get("produced_by") != "rev-core" and not args.allow_forward:
        print(_color(ANSI_RED, "拒绝写入：只有 rev-core 是唯一写者。上游模块请用 --allow-forward 由 core 代写"),
              file=sys.stderr)
        return EXIT_INVALID
    if obj["target_id"] != tgt["target_id"]:
        print(_color(ANSI_RED, f"拒绝写入：target_id 不匹配（{obj['target_id']} != {tgt['target_id']}）"),
              file=sys.stderr)
        return EXIT_INVALID
    existing = {e["id"] for e in read_jsonl(os.path.join(args.dir, "evidence.jsonl"))}
    if obj["id"] in existing:
        print(_color(ANSI_RED, f"拒绝写入：evidence id 重复 {obj['id']}"), file=sys.stderr)
        return EXIT_INVALID
    # confidence 只在展示时派生，不落盘——落盘就会与「禁止手填」自相矛盾
    append_jsonl(os.path.join(args.dir, "evidence.jsonl"), obj)
    conf = derive_confidence(obj["grade"], [obj["channel"]], schema)
    print(f"written: {obj['id']}  grade={obj['grade']}  confidence(派生)={conf}")
    return EXIT_OK


def cmd_evidence_list(args):
    rows = read_jsonl(os.path.join(args.dir, "evidence.jsonl"))
    schema = load_schema()
    if not rows:
        print("(空)")
        return EXIT_OK
    for r in rows:
        conf = derive_confidence(r["grade"], [r["channel"]], schema)
        loc = r.get("locator") or {}
        where = loc.get("addr") if loc.get("addr") is not None else loc.get("offset")
        print(f"{r['id']:<12} {r['grade']}  ch={r['channel']:<7} conf={conf:<5} @{where} len={loc.get('length')}")
    print(f"\n共 {len(rows)} 条")
    return EXIT_OK


def cmd_gate(args):
    schema = load_schema()
    _, tgt = _tdir(args.dir)
    ev = read_jsonl(os.path.join(args.dir, "evidence.jsonl"))
    unk = read_jsonl(os.path.join(args.dir, "unknowns.jsonl"))
    errs = []
    if not ev:
        errs.append("证据库为空：没有任何 E1 及以上证据，不得交付")
    blocking = [u for u in unk if u.get("blocking") is True]
    if blocking:
        errs.append(f"存在 {len(blocking)} 条 blocking 未解项，不得交付：{[u['id'] for u in blocking]}")
    for e in ev:
        bad = validate_evidence(e, schema)
        if bad:
            errs.append(f"{e.get('id')}: " + "; ".join(bad))
    if errs:
        for e in errs:
            print(_color(ANSI_RED, "E " + e), file=sys.stderr)
        print(_color(ANSI_RED, "GATE FAILED"), file=sys.stderr)
        return EXIT_INVALID
    print(f"GATE PASSED  evidence={len(ev)}  unknowns={len(unk)}  blocking=0  target={tgt['target_id']}")
    return EXIT_OK


def cmd_report(args):
    schema = load_schema()
    _, tgt = _tdir(args.dir)
    ev = read_jsonl(os.path.join(args.dir, "evidence.jsonl"))
    unk = read_jsonl(os.path.join(args.dir, "unknowns.jsonl"))
    blocking = [u for u in unk if u.get("blocking") is True]
    if blocking and not args.draft:
        print(_color(ANSI_RED, f"拒绝生成交付版：{len(blocking)} 条 blocking 未解项未清零（用 --draft 出草稿）"),
              file=sys.stderr)
        return EXIT_INVALID
    hi = [e for e in ev if e["grade"] != "E0"]
    low = [e for e in ev if e["grade"] == "E0"]
    lines = [f"# 分析报告 · {tgt['target_id']}", "",
             f"> 生成时间 {now_iso()}｜授权依据 {tgt['authorization']['basis']}｜"
             f"目的 {tgt['authorization']['purpose']}｜草稿={'是' if args.draft else '否'}", "",
             "## 一、结论（E1 及以上，可重跑）", ""]
    if hi:
        lines += ["| evidence | 级 | 通道 | confidence | 位置 |", "|---|---|---|---|---|"]
        for e in hi:
            loc = e.get("locator") or {}
            where = loc.get("addr") if loc.get("addr") is not None else loc.get("offset")
            lines.append(f"| `{e['id']}` | {e['grade']} | {e['channel']} | "
                         f"{derive_confidence(e['grade'], [e['channel']], schema)} | `{where}` |")
    else:
        lines.append("（无。结论段为空，说明还没拿到可重跑的证据。）")
    lines += ["", "## 二、未验证（E0，仅记录，不作结论）", ""]
    lines += [f"- `{e['id']}`：{e.get('note', '（无说明）')}" for e in low] or ["（无）"]
    lines += ["", "## 三、未解清单", ""]
    if unk:
        lines += ["| id | 问题 | 阻断交付 | 解锁条件 | 责任模块 |", "|---|---|---|---|---|"]
        for u in unk:
            lines.append(f"| `{u['id']}` | {u['question']} | {'是' if u['blocking'] else '否'} | "
                         f"{u['unblock_condition']} | {u['owner_module']} |")
    else:
        lines.append("（无。注意：未解清单为空不等于没有未解项，见 SKILL.md『本技能的失效模式』。）")
    out = args.out or os.path.join(args.dir, "report.md")
    with io.open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    print(f"written: {out}")
    return EXIT_OK


def collect_evidence_index(paths):
    """从若干文件/目录收集 evidence，用于 finding 的引用校验。"""
    idx = {}
    for p in paths:
        if not p or not os.path.exists(p):
            continue
        if os.path.isdir(p):
            for root, _, names in os.walk(p):
                for n in sorted(names):
                    fp = os.path.join(root, n)
                    if n.endswith(".jsonl"):
                        for row in read_jsonl(fp):
                            if row.get("kind") == "evidence" and row.get("id"):
                                idx[row["id"]] = row
                    elif n.endswith(".json"):
                        try:
                            row = read_json(fp)
                        except Exception:  # noqa: BLE001
                            continue
                        if isinstance(row, dict) and row.get("kind") == "evidence" and row.get("id"):
                            idx[row["id"]] = row
        elif p.endswith(".jsonl"):
            for row in read_jsonl(p):
                if row.get("kind") == "evidence" and row.get("id"):
                    idx[row["id"]] = row
        else:
            try:
                row = read_json(p)
            except Exception:  # noqa: BLE001
                continue
            if isinstance(row, dict) and row.get("kind") == "evidence" and row.get("id"):
                idx[row["id"]] = row
    return idx


def cmd_lint(args):
    schema = load_schema()
    p = args.path
    if not os.path.exists(p):
        print(_color(ANSI_RED, f"路径不存在: {p}"), file=sys.stderr)
        return EXIT_USAGE

    # 找证据：显式 --evidence + 路径自身（若是目录或 jsonl）+ 同目录（单文件模式）
    sources = list(args.evidence or [])
    if os.path.isdir(p):
        sources.append(p)
        files = []
        for root, _, names in os.walk(p):
            for n in sorted(names):
                if n.endswith(".json"):
                    files.append(os.path.join(root, n))
        if not files:
            files = sorted(f for root, _, ns in os.walk(p) for n in ns if n.endswith(".jsonl")
                           for f in [os.path.join(root, n)])
    else:
        files = [p]
        sources.append(os.path.dirname(p) or ".")
    ev_index = collect_evidence_index(sources)

    total_err = 0
    if os.path.isfile(p) and p.endswith(".jsonl"):
        errs = []
        for row in read_jsonl(p):
            fn = {"evidence": validate_evidence, "unknown": validate_unknown,
                  "finding": lambda o, s: validate_finding(o, s, ev_index)}.get(row.get("kind"))
            if fn:
                errs += [f"{os.path.basename(p)}: {x}" for x in fn(row, schema)]
        if errs:
            for e in errs:
                print(_color(ANSI_RED, "E " + e))
            print(_color(ANSI_RED, f"\nLINT FAILED  共 {len(errs)} 项"))
            return EXIT_INVALID
        print(f"LINT OK  files=1  evidence_index={len(ev_index)}")
        return EXIT_OK

    for f in files:
        errs, _ = validate_artifact(f, schema, ev_index)
        if errs:
            total_err += len(errs)
            for e in errs:
                print(_color(ANSI_RED, f"E {os.path.basename(f)}: {e}"))
    if total_err:
        print(_color(ANSI_RED, f"\nLINT FAILED  共 {total_err} 项"))
        return EXIT_INVALID
    print(f"LINT OK  files={len(files)}  evidence_index={len(ev_index)}")
    return EXIT_OK


def cmd_manifest(args):
    root = args.root or SKILL_ROOT
    items = {}
    for base, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git")]
        for n in sorted(names):
            p = os.path.join(base, n)
            rel = os.path.relpath(p, root).replace("\\", "/")
            if rel == "MANIFEST.json":
                continue
            items[rel] = {"sha256": sha256_file(p), "bytes": os.path.getsize(p)}
    man = {"schema": "skill-manifest/1", "skill": "rev-core", "version": "1.0.0",
           "generated_at": now_iso(), "algorithm": "sha256", "files": items}
    write_json(os.path.join(root, "MANIFEST.json"), man)
    print(f"MANIFEST.json written: {len(items)} files")
    return EXIT_OK


# ---------------------------------------------------------------- 自检

def _env(kind, eid="ev-0001"):
    return {"schema": "reva/1", "kind": kind, "id": eid, "produced_by": "rev-core",
            "produced_at": "2026-11-01T22:40:00+08:00", "target_id": "tgt-abc123",
            "provenance": {"tool": "ghidra", "version": "11.3.2",
                           "command": "analyzeHeadless ... -postScript Xrefs.py",
                           "inputs_sha256": ["a" * 64]},
            "status": "ok", "refs": []}


def _ev(eid, grade="E1", channel="static", locator=True, digest=True, reproduce=True, length=8):
    o = _env("evidence", eid)
    if locator:
        o["locator"] = {"file_sha256": "b" * 64, "addr": 0x401000, "length": length}
    if digest:
        o["digest"] = {"algo": "sha256", "value": "c" * 64}
    if reproduce:
        o["reproduce"] = {"cmd": "python scripts/xrefs.py sample.exe 0x401000 8", "cwd": ".", "env": {}}
    o["grade"], o["channel"] = grade, channel
    return o


def build_fixtures():
    """12 个负例（每个只违反一条规则）+ 4 个正例。"""
    pos = []
    pos.append(("pos_ev_static_E1", _ev("ev-1001", "E1", "static"), []))

    e2 = _ev("ev-1002", "E2", "dynamic")
    pos.append(("pos_ev_dynamic_E2", e2, []))

    fd = _env("finding", "fd-1001")
    fd.update({"claim": "程序通过 COM3 以 9600/8N1 写入 6 字节帧", "scope": "该版本 2.1.4 的 GUI 前端",
               "evidence_refs": ["ev-1001", "ev-1002"], "unknowns": [], "contradicts": [],
               "state": "corroborated"})
    pos.append(("pos_finding_corroborated", fd, []))

    uk = _env("unknown", "uk-1001")
    uk.update({"question": "帧尾 2 字节是 CRC16-Modbus 还是累加和", "why_unknown": "只采到 3 组样本，不足以区分",
               "blocking": False, "tried": ["差分采样 3 组"], "unblock_condition": "再采 20 组不同载荷",
               "owner_module": "rev-runtime"})
    pos.append(("pos_unknown_nonblocking", uk, []))

    neg = []
    o = _ev("ev-2001"); o.pop("locator")
    neg.append(("neg_01_missing_locator", o, "必须有 locator"))

    neg.append(("neg_02_length_zero", _ev("ev-2002", length=0), "length 必须是正整数"))

    o = _ev("ev-2003"); o.pop("digest")
    neg.append(("neg_03_missing_digest", o, "必须有 digest"))

    o = _ev("ev-2004"); o["digest"]["value"] = "abc123"
    neg.append(("neg_04_digest_not_sha256", o, "digest.value"))

    o = _ev("ev-2005"); o["reproduce"].pop("cmd")
    neg.append(("neg_05_missing_reproduce_cmd", o, "reproduce 缺字段"))

    o = _ev("ev-2006"); o["reproduce"].pop("env")
    neg.append(("neg_06_missing_reproduce_env", o, "reproduce 缺字段"))

    neg.append(("neg_07_bad_grade", _ev("ev-2007", "E9"), "grade 非法"))

    o = _ev("ev-2008"); o["confidence"] = 0.9
    neg.append(("neg_08_manual_confidence", o, "禁止手填"))

    o = _ev("ev-2009"); o["note"] = "顺手记一句"
    neg.append(("neg_09_unknown_field", o, "未定义字段"))

    o = _ev("ev-2010"); o["schema"] = "reva/2"
    neg.append(("neg_10_schema_mismatch", o, "schema 版本不符"))

    f = _env("finding", "fd-2001")
    f.update({"claim": "x", "scope": "y", "evidence_refs": [], "unknowns": [], "contradicts": [],
              "state": "proposed"})
    neg.append(("neg_11_empty_evidence_refs", f, "evidence_refs 必须是非空数组"))

    f = _env("finding", "fd-2002")
    f.update({"claim": "两个静态点合起来算证实", "scope": "z", "evidence_refs": ["ev-1001", "ev-2001s"],
              "unknowns": [], "contradicts": [], "state": "corroborated"})
    neg.append(("neg_12_corroborated_single_channel", f, "不同 channel"))

    # ---- locator 双模（1.1.0）：动态证据用运行时定位符 ----
    def _rt(eid, grade="E2", channel="dynamic", **override):
        o = _ev(eid, grade, channel)
        rt = {"host": "windows", "pid": 4120, "module": "device_gui.exe",
              "rva": 0x2A1F0, "session": "rt-20261101-2240-a7f3",
              "captured_at": "2026-11-01T22:41:03+08:00"}
        rt.update(override.pop("rt", {}))
        o["locator"] = {"mode": "runtime", "file_sha256": "b" * 64, "length": 6, "runtime": rt}
        for k, v in override.items():
            o[k] = v
        return o

    pos.append(("pos_ev_runtime_locator", _rt("ev-1003"), []))

    o = _rt("ev-2011", rt={"session": ""})
    neg.append(("neg_13_runtime_locator_empty_session", o, "session 必须是非空字符串"))

    o = _rt("ev-2012", channel="static")
    neg.append(("neg_14_static_channel_with_runtime_locator", o, "静态通道不得产出运行时定位符"))

    o = _rt("ev-2013", rt={"pid": "4120"})
    neg.append(("neg_15_runtime_pid_not_int", o, "pid 必须是正整数"))

    o = _rt("ev-2014")
    o["locator"].pop("runtime")
    neg.append(("neg_16_runtime_mode_missing_block", o, "必须提供 runtime 子对象"))

    o = _rt("ev-2015", rt={"host": "darwin"})
    neg.append(("neg_17_runtime_host_unsupported", o, "host 非法"))

    o = _rt("ev-2016")
    o["locator"]["mode"] = "file"
    neg.append(("neg_18_file_mode_with_runtime_block", o, "不得带 runtime 子对象"))
    return pos, neg


def cmd_selftest(args):
    schema = load_schema()
    os.makedirs(FIXTURE_DIR, exist_ok=True)
    pos, neg = build_fixtures()

    # 负例 12 需要第二条同通道证据存在，才能验证"同通道不算证实"而不是"引用不存在"
    same_channel = _ev("ev-2001s", "E1", "static")
    ev_index = {"ev-1001": _ev("ev-1001", "E1", "static"),
                "ev-1002": _ev("ev-1002", "E2", "dynamic"),
                "ev-2001s": same_channel}

    failures = []
    sub_ok = os.path.join(FIXTURE_DIR, "positive")
    sub_bad = os.path.join(FIXTURE_DIR, "negative")
    if args.materialize:
        os.makedirs(sub_ok, exist_ok=True)
        os.makedirs(sub_bad, exist_ok=True)
        # 清掉早期落在根目录的扁平 fixture，避免正负例混在一起让整目录 lint 恒红
        for n in os.listdir(FIXTURE_DIR):
            if n.endswith(".json") and (n.startswith("pos_") or n.startswith("neg_")):
                os.remove(os.path.join(FIXTURE_DIR, n))
    for name, obj, _ in pos + neg:
        if args.materialize:
            target = sub_ok if name.startswith("pos_") else sub_bad
            write_json(os.path.join(target, name + ".json"), obj)

    for name, obj, _ in pos:
        errs = validate_evidence(obj, schema) if obj["kind"] == "evidence" else (
            validate_finding(obj, schema, ev_index) if obj["kind"] == "finding" else
            validate_unknown(obj, schema))
        if errs:
            failures.append(f"正例被判红：{name} -> {errs}")

    for name, obj, expect in neg:
        errs = validate_finding(obj, schema, ev_index) if obj["kind"] == "finding" else validate_evidence(obj, schema)
        if not errs:
            failures.append(f"负例被判绿（检查器失效）：{name}（应命中：{expect}）")
        elif expect not in " ".join(errs):
            failures.append(f"负例报错信息不含关键判据：{name} -> {errs}（期望含 {expect!r}）")

    print(f"正例 {len(pos)} 个 / 负例 {len(neg)} 个")
    if failures:
        for f in failures:
            print(_color(ANSI_RED, "FAIL " + f))
        print(_color(ANSI_RED, f"\nSELFTEST FAILED  {len(failures)} 项"))
        return EXIT_INVALID
    print(_color(ANSI_DIM, "负例全部判红、正例全部判绿"))
    print("SELFTEST PASSED")
    return EXIT_OK


# ---------------------------------------------------------------- 入口

def build_parser():
    p = argparse.ArgumentParser(prog="rev-core", description="逆向分析流水线的入口与证据闸")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="授权开单（越界 exit 4）")
    s.add_argument("--dir", required=True)
    s.add_argument("--target", required=True)
    s.add_argument("--basis", required=True, choices=["self-owned", "written", "open-source", "public-spec"])
    s.add_argument("--purpose", required=True,
                   choices=["interop", "security-test", "malware-analysis", "migration", "compete-observe"])
    s.add_argument("--allow", action="append", default=[])
    s.add_argument("--evidence-ref", default="")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("triage", help="形态识别与路由")
    s.add_argument("--dir", required=True)
    s.set_defaults(fn=cmd_triage)

    s = sub.add_parser("dispatch", help="打印按策略过滤后的 DAG")
    s.add_argument("--dir", required=True)
    s.set_defaults(fn=cmd_dispatch)

    s = sub.add_parser("evidence", help="证据库操作")
    es = s.add_subparsers(dest="ecmd", required=True)
    a = es.add_parser("add")
    a.add_argument("--dir", required=True)
    a.add_argument("--file", required=True)
    a.add_argument("--allow-forward", action="store_true", help="由 core 代上游模块写入")
    a.set_defaults(fn=cmd_evidence_add)
    a = es.add_parser("list")
    a.add_argument("--dir", required=True)
    a.set_defaults(fn=cmd_evidence_list)

    s = sub.add_parser("gate", help="交付闸门")
    s.add_argument("--dir", required=True)
    s.set_defaults(fn=cmd_gate)

    s = sub.add_parser("report", help="证据库投影为报告")
    s.add_argument("--dir", required=True)
    s.add_argument("--out", default=None)
    s.add_argument("--draft", action="store_true")
    s.set_defaults(fn=cmd_report)

    s = sub.add_parser("lint", help="工件校验")
    s.add_argument("--path", required=True)
    s.add_argument("--evidence", action="append", default=[],
                   help="补充证据来源（文件或目录），用于 finding 的引用校验")
    s.set_defaults(fn=cmd_lint)

    s = sub.add_parser("manifest", help="生成 MANIFEST.json（sha256 清单）")
    s.add_argument("--root", default=None)
    s.set_defaults(fn=cmd_manifest)

    s = sub.add_parser("selftest", help="跑 12 负例 + 4 正例")
    s.add_argument("--materialize", action="store_true", help="把 fixture 落盘")
    s.set_defaults(fn=cmd_selftest)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
