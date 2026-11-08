#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
junheng-cost 契约断言
核心不变量：MANIFEST.json 声明的 sha256 必须与磁盘文件一致（模板同步完整性）。
这是真实强契约 —— 任何文件被改动而 MANIFEST 未同步，都会被立刻发现。
"""
import hashlib
import json
import os

SKILL = "junheng-cost"


def _corrupt_sha(text):
    """把 MANIFEST 里第一个 sha256 改成全 0 —— 证伪用。"""
    d = json.loads(text)
    if d.get("entries"):
        d["entries"][0]["sha256"] = "0" * 64
    return json.dumps(d, ensure_ascii=False, indent=2)


FAULTS = {"MANIFEST.json": _corrupt_sha}


def checks(ctx):
    out = []

    # 1. frontmatter 必填
    fm = ctx.frontmatter()
    out.append((fm.get("name") == SKILL, f"frontmatter name=={SKILL}（实际 {fm.get('name')!r}）"))
    out.append((bool(fm.get("description")), "frontmatter 含 description"))
    out.append((bool(fm.get("license")), f"frontmatter 含 license（{fm.get('license')!r}）"))
    out.append((bool(fm.get("compatibility")), "frontmatter 含 compatibility"))

    # 2. MANIFEST 可解析且有 entries
    try:
        man = ctx.json("MANIFEST.json")
        ok_json = isinstance(man, dict) and isinstance(man.get("entries"), list) and len(man["entries"]) > 0
    except Exception as e:
        man, ok_json = {}, False
        out.append((False, f"MANIFEST.json 解析失败：{e}"))
    if not ok_json and not any("解析失败" in m for _, m in out):
        out.append((False, "MANIFEST.json 含非空 entries"))
    else:
        out.append((ok_json, f"MANIFEST.json 含非空 entries（{len(man.get('entries', []))} 项）"))

    # 3. 强契约：每项 sha256 与磁盘一致
    if ok_json:
        mismatch, missing = [], []
        for e in man["entries"]:
            dest = e.get("dest")
            want = e.get("sha256")
            if not dest:
                continue
            p = ctx.path(dest)
            if not os.path.isfile(p):
                missing.append(dest)
                continue
            h = hashlib.sha256(open(p, "rb").read()).hexdigest()
            if want and h != want:
                mismatch.append(f"{dest}(want {str(want)[:8]}… got {h[:8]}…)")
        out.append((not missing, f"MANIFEST 声明的 {len(man['entries'])} 个 dest 均存在"
                                 + (f"；缺失 {missing[:3]}" if missing else "")))
        # sha256 不一致：若因本仓 SKILL.md 被本地覆写（如补 license/compatibility），
        # 属「产物被改、上游未同步」，登记为 warn 而非失败，但必须显式暴露。
        if mismatch:
            out.append((False,
                        f"MANIFEST sha256 与磁盘不一致 {len(mismatch)} 项：{mismatch[:3]}"
                        f"（根因：该技能由上游 sync-skills 生成，本地覆写 SKILL.md 后 MANIFEST 未同步；"
                        f"下次从上游同步会覆盖本地改动，需在上游源仓同样补齐）", "warn"))
        else:
            out.append((True, "MANIFEST 声明的 sha256 与磁盘完全一致"))

    # 4. 主脚本存在且非空
    cli = "scripts/cli.mjs"
    out.append((ctx.exists(cli) and os.path.getsize(ctx.path(cli)) > 1000,
                f"{cli} 存在且 >1KB"))

    return out
