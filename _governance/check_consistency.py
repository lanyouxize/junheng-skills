#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""技能声明 vs 连接器状态 · 一致性检查器。

只读扫描，不改任何技能文件。把「技能声明 / 缓存 / INDEX / 连接器 / 数据引用」
之间的一致性从人工核对变成可执行判据，供月度复核与 CI 闸门使用。

用法：
    python check_consistency.py                 # 全量报告（红黄分级）
    python check_consistency.py --json          # 机器可读输出
    python check_consistency.py --strict        # 警告也计为失败（退出码 1）
    python check_consistency.py --no-data       # 跳过 data/ 下的 jsonl 引用检查

检查维度（每维度只报「不一致/断链」，不报正常项）：
    A. 缓存↔文件系统：缓存条目指向的目录缺失 / 有 SKILL.md 的目录未进缓存
    B. 命名规范：安装件（_skillhub_meta.json）校验 meta.slug 配对；自建技能仅报空 name 或含 __ 后缀（__skillhub 后缀是 skillhub 安装源合法命名，不报）
    C. INDEX.md↔实际技能：INDEX 有条目但无目录 / 目录存在但 INDEX 缺失 / 触发词列为占位符 —
    D. 连接器需求↔状态：技能描述声明的连接器，是否在 mcp.json 中声明且未禁用
    E. 数据引用：out/*.jsonl 的 body_ref/images_ref 指向缺失文件

退出码：0 = 无问题；1 = 有 E 级问题，或 --strict 下有 W 级；2 = 仅 W 级（非 strict）。
不在本检查器内的项（交人工）：description 能否真正命中触发、技能间语义是否重复。
"""

import argparse
import json
import os
import re
import sys

SKILLS_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
CACHE_PATH = os.path.normpath(os.path.join(SKILLS_DIR, "..", ".skill-list-cache.json"))
INDEX_PATH = os.path.join(SKILLS_DIR, "INDEX.md")
MCP_PATH = os.path.normpath(os.path.join(SKILLS_DIR, "..", "mcp.json"))
# data/ 是工作区相对路径，可能在不同机器上不同，缺失则跳过
WORKSPACE_DATA = os.path.join(
    "D:/workbuddy重做系统后版本/2026-10-23-14-10-52",
    "data", "wechat-article-collector", "out"
)

# 连接器关键词 -> mcp.json 中的 server 名（能直接比对 disabled 的）
CONNECTOR_KEYWORDS = {
    "junheng(ima)": (["ima", "钧衡", "nutriagent"], "junheng"),
    "engram": (["engram", "记忆库"], "engram"),
    "lighthouse-ops": (["lighthouse", "lightai"], "lighthouse-ops"),
    "github": (["github"], None),
    "tencent-docs": (["腾讯文档", "tencent-docs"], None),
    "kdocs": (["金山文档", "wps云文档", "kdocs"], None),
    "tmeet": (["腾讯会议", "tmeet"], None),
    "cnb-api": (["cnb", "coding"], None),
    "agent-mail": (["agent mail", "智能体邮箱", "agent-mail"], None),
}


def parse_frontmatter(path):
    """极简 frontmatter 解析：取首个 --- 块，按 key: value 抽取。"""
    try:
        text = open(path, encoding="utf-8").read()
    except Exception:
        return None
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
    if not m:
        return None
    fm = {}
    for line in m.group(1).splitlines():
        mm = re.match(r"^([A-Za-z0-9_-]+):\s?(.*)$", line)
        if mm:
            fm[mm.group(1)] = mm.group(2).strip()
    return fm


def load_cache():
    if not os.path.exists(CACHE_PATH):
        return None
    try:
        return json.load(open(CACHE_PATH, encoding="utf-8"))
    except Exception:
        return None


def list_skill_dirs():
    out = []
    if not os.path.isdir(SKILLS_DIR):
        return out
    for name in sorted(os.listdir(SKILLS_DIR)):
        d = os.path.join(SKILLS_DIR, name)
        if os.path.isdir(d) and not name.startswith("_") and not name.startswith("."):
            out.append(name)
    return out


def check_A(cache):
    """缓存↔文件系统一致性。"""
    issues = []
    if cache is None:
        issues.append(("W", "缓存文件缺失，跳过 A 维度", CACHE_PATH))
        return issues
    results = cache.get("results", []) or []
    # 缓存条目指向目录是否存在
    for it in results:
        fp = it.get("filePath", "")
        if not fp:
            continue
        if not os.path.exists(fp):
            issues.append(("E", "缓存条目指向的目录/文件不存在", it.get("name", "?")))
    # 有 SKILL.md 的目录是否进了缓存（候选 key：目录名 / 去后缀 / frontmatter name）
    cache_keys = set()
    for it in results:
        cache_keys.add(it.get("overrideKey") or it.get("name"))
    for d in list_skill_dirs():
        fm = parse_frontmatter(os.path.join(SKILLS_DIR, d, "SKILL.md"))
        candidates = {d, d.replace("__skillhub", ""), (fm or {}).get("name", "")}
        if not (candidates & cache_keys):
            issues.append(("W", "技能目录未在缓存中出现（可能 __ 后缀导致未被加载）", d))
    return issues


def check_B():
    """命名规范校验。

    安装件（含 _skillhub_meta.json）的目录名是平台分配的 slug，与 frontmatter
    name（显示名）本就不一致，属正常——改用 meta.slug == 目录去后缀名 配对校验。
    __skillhub 后缀是 skillhub 安装源的合法命名约定，不视为问题。
    仅对用户自建技能（无 meta）检查：name 为空、或目录含 __ 后缀。
    """
    issues = []
    for d in list_skill_dirs():
        fm = parse_frontmatter(os.path.join(SKILLS_DIR, d, "SKILL.md"))
        if fm is None:
            continue
        name = fm.get("name", "")
        meta_path = os.path.join(SKILLS_DIR, d, "_skillhub_meta.json")
        if os.path.exists(meta_path):
            # 安装件：校验 slug 配对，配对正常即放行
            try:
                meta = json.load(open(meta_path, encoding="utf-8"))
                slug = meta.get("slug", "")
            except Exception:
                slug = ""
            if slug and slug != d.replace("__skillhub", ""):
                issues.append(("W", f"skillhub 安装件目录名与 meta.slug 不匹配（slug='{slug}'）", d))
            continue
        # 自建技能：仅报空 name 或含 __ 后缀
        if not name:
            issues.append(("W", "frontmatter name 为空", d))
        elif "__" in d:
            issues.append(("W", "自建技能目录含 __ 后缀（命名待清理）", d))
    return issues


# INDEX.md 中以代码段出现、但不是技能名的词（列头/示例/frontmatter 字段）
INDEX_DENYLIST = {
    "name", "description", "族群", "owner", "source", "status", "type", "license",
    "合计", "触发词", "一句话", "自建", "skillhub", "安装件", "镜像", "目录", "文件",
    "key", "value", "示例", "用法", "说明", "本文", "frontmatter", "slug",
    "__", "a-z0-9._-", "skills", "readme", "skill", "json", "csv", "drive",
}


def _dir_matches(token, dirs):
    """INDEX 词条是否对应某个真实技能目录（宽松匹配，容忍短名/后缀差异）。"""
    for d in dirs:
        base = d.replace("__skillhub", "").replace("__", "")
        if token == d or token == base or base.startswith(token) or token.startswith(base):
            return True
    return False


def check_C():
    """INDEX.md↔实际技能。"""
    issues = []
    if not os.path.exists(INDEX_PATH):
        issues.append(("W", "INDEX.md 缺失，跳过 C 维度", INDEX_PATH))
        return issues
    text = open(INDEX_PATH, encoding="utf-8").read()
    dirs = list_skill_dirs()
    index_tokens = set(re.findall(r"`([a-z0-9\-_.]+)`", text))
    # 目录存在但 INDEX 无条目
    for dn in sorted(dirs):
        if not _dir_matches(dn, [dn]) and not _dir_matches(dn.replace("__skillhub", ""), dirs):
            issues.append(("W", "目录存在但 INDEX.md 无条目", dn))
    # INDEX 词条无对应目录（排除停用词与列头）
    for nm in sorted(index_tokens):
        if nm in INDEX_DENYLIST:
            continue
        if not _dir_matches(nm, dirs):
            issues.append(("W", "INDEX.md 有条目但无对应目录", nm))
    # 触发词列为占位符 —
    for line in text.splitlines():
        if line.count("|") >= 3 and "—" in line:
            cells = [c.strip() for c in line.split("|")]
            if len(cells) >= 4 and cells[3] == "—" and re.match(r"^`", cells[1]):
                issues.append(("W", "INDEX 触发词列为占位符 —", cells[1]))
    return issues


def check_D():
    """连接器需求↔状态（best-effort，仅报真实错配）。"""
    issues = []
    mcp = None
    if os.path.exists(MCP_PATH):
        try:
            mcp = json.load(open(MCP_PATH, encoding="utf-8"))
        except Exception:
            mcp = None
    servers = {}
    if mcp:
        for sname, scfg in (mcp.get("mcpServers") or {}).items():
            servers[sname] = bool(scfg.get("disabled", False))
    for d in list_skill_dirs():
        fm = parse_frontmatter(os.path.join(SKILLS_DIR, d, "SKILL.md"))
        if fm is None:
            continue
        desc = (fm.get("description", "") + " " + fm.get("name", "")).lower()
        for label, (kws, server) in CONNECTOR_KEYWORDS.items():
            if not any(kw.lower() in desc for kw in kws):
                continue
            if server is None:
                # 非 MCP 连接器（github / 腾讯文档等），由平台连接器系统承载，静默
                continue
            if server in servers and servers[server]:
                issues.append(("E", f"声明依赖连接器 {label}（{server} 在 mcp.json 中 disabled）", d))
            elif server not in servers:
                issues.append(("W", f"声明依赖连接器 {label}，但 mcp.json 无 {server} 服务", d))
            # 其余：已声明且未禁用 -> 正常，不报
    return issues


def check_E():
    """数据引用断链（out/*.jsonl）。"""
    issues = []
    if not os.path.isdir(WORKSPACE_DATA):
        return issues
    import glob
    for jf in sorted(glob.glob(os.path.join(WORKSPACE_DATA, "*.jsonl"))):
        try:
            lines = open(jf, encoding="utf-8").read().splitlines()
        except Exception:
            continue
        for ln in lines:
            ln = ln.strip()
            if not ln:
                continue
            try:
                rec = json.loads(ln)
            except Exception:
                continue
            rid = rec.get("record_id", "?")
            for key in ("body_ref", "images_ref", "videos_ref"):
                v = rec.get(key)
                if not v:
                    continue
                cand = v.replace("out\\", "").replace("out/", "", 1)
                full = os.path.join(WORKSPACE_DATA, cand)
                if not os.path.exists(full):
                    issues.append(("W", f"{os.path.basename(jf)}/{rid}: {key} 断链 -> {cand[-40:]}", ""))
    return issues


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    ap.add_argument("--strict", action="store_true", help="警告也计为失败")
    ap.add_argument("--no-data", action="store_true", help="跳过 data/ jsonl 检查")
    args = ap.parse_args()

    cache = load_cache()
    dims = [("A", check_A(cache))]
    dims.append(("B", check_B()))
    dims.append(("C", check_C()))
    dims.append(("D", check_D()))
    if not args.no_data:
        dims.append(("E", check_E()))

    sev_order = {"E": 0, "W": 1}
    total_e = sum(1 for _, iss in dims for s, _, _ in iss if s == "E")
    total_w = sum(1 for _, iss in dims for s, _, _ in iss if s == "W")

    if args.json:
        out = {
            "summary": {"E": total_e, "W": total_w},
            "dimensions": {k: [{"sev": s, "msg": m, "ctx": c} for s, m, c in iss] for k, iss in dims},
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print("=" * 64)
        print("技能一致性检查  ·  %s" % __file__)
        print("=" * 64)
        for k, iss in dims:
            iss_sorted = sorted(iss, key=lambda x: sev_order[x[0]])
            print("\n[%s] %s  %d 项" % (k, {"A": "缓存↔文件系统", "B": "name↔目录名",
                                              "C": "INDEX↔实际技能", "D": "连接器需求↔状态",
                                              "E": "数据引用断链"}[k], len(iss)))
            if not iss_sorted:
                print("    ✅ 无问题")
            for s, m, c in iss_sorted:
                tag = "❌ E" if s == "E" else "⚠ W"
                print("    %s %s%s" % (tag, m, ("  [" + c + "]") if c else ""))
        print("\n" + "=" * 64)
        print("汇总：E=%d  W=%d" % (total_e, total_w))
        print("=" * 64)

    if total_e > 0:
        return 1
    if total_w > 0 and args.strict:
        return 1
    if total_w > 0:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
