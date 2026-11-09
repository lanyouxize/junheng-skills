#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""junheng-nutrition 契约断言（T5 生成，判据经 t5_probe_candidates.py 实测全绿）。

真不变量：frontmatter 严格 YAML / 顶层 JSON 数+可解析 / py 可 AST 编译 /
          MANIFEST.entries 数+sha256 与磁盘一致。
可证伪：FAULTS 篡改 MANIFEST.json => 至少 1 条断言失败。
"""
import ast
import hashlib
import json
import os

import yaml

SKILL = "junheng-nutrition"
N_JSON = 1
N_PY = 0
N_ENTRIES = 11

FAULTS = {
    "MANIFEST.json": lambda t: t.replace('"sha256"', '"sha256_BROKEN"', 1),
}


def _sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def checks(ctx):
    out = []

    # 1. frontmatter：严格 YAML + 必含 name/description（可证伪：污染 SKILL.md）
    try:
        t = ctx.read("SKILL.md")
        lines = t.splitlines()
        end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
        fm = yaml.safe_load("\n".join(lines[1:end])) if end else None
        ok = isinstance(fm, dict) and bool(fm.get("name")) and bool(fm.get("description"))
        out.append((ok, "frontmatter 严格 YAML 且含 name/description"))
    except Exception as e:
        out.append((False, f"frontmatter 解析失败：{type(e).__name__}"))

    # 2. 顶层 JSON：数量 == 实测基准 且 全部可解析
    js = sorted(f for f in os.listdir(ctx.dir) if f.endswith(".json"))
    bad = []
    for f in js:
        try:
            ctx.json(f)
        except Exception as e:
            bad.append(f + ":" + type(e).__name__)
    out.append((len(js) == N_JSON and not bad,
                f"顶层 JSON 数 == {N_JSON} 且全部可解析（实际 {len(js)}，坏 {bad[:3]}）"))

    # 3. scripts 下 .py：数量 == 实测基准 且 全部可 AST 编译
    pys = []
    for root, dirs, files in os.walk(ctx.dir):
        dirs[:] = [x for x in dirs if x not in ("__pycache__", "node_modules", ".git")]
        for f in files:
            if f.endswith(".py"):
                pys.append(os.path.relpath(os.path.join(root, f), ctx.dir).replace("\\", "/"))
    bad3 = []
    for rel in pys:
        try:
            ast.parse(ctx.read(rel))
        except Exception as e:
            bad3.append(rel + ":" + type(e).__name__)
    if N_PY > 0:
        out.append((len(pys) == N_PY and not bad3,
                    f"scripts .py 数 == {N_PY} 且全部可编译（实际 {len(pys)}，坏 {bad3[:3]}）"))
    else:
        out.append((True, "该技能无 .py 脚本，跳过语法判据（不写 vacuous 断言）"))

    # 4. MANIFEST：entries 数 == 实测基准 且 sha256 与磁盘一致
    if N_ENTRIES > 0:
        try:
            man = ctx.json("MANIFEST.json")
            ents = man.get("entries", [])
            missing, diff = [], []
            for e in ents:
                dest = e.get("dest")
                want = e.get("sha256")
                fp = os.path.join(ctx.dir, dest) if dest else None
                if not dest or not want or not fp or not os.path.isfile(fp):
                    missing.append(str(dest))
                elif _sha(fp) != want:
                    diff.append(dest)
            out.append((len(ents) == N_ENTRIES and not missing and not diff,
                        f"MANIFEST entries == {N_ENTRIES} 且 sha256 全一致"
                        f"（实际 {len(ents)}，缺 {missing[:2]}，异 {diff[:2]}）"))
        except Exception as e:
            out.append((False, f"MANIFEST 校验失败：{type(e).__name__}"))
    else:
        out.append((True, "该技能 MANIFEST 无 entries，跳过 sha 判据（0 条断言等于没检查）"))

    return out
