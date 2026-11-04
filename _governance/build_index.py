#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 taxonomy.json + 各 SKILL.md 重建 skills/INDEX.md。

设计要点：INDEX.md 是**产物**，不手改。要改索引内容，改 taxonomy.json 后重跑：

    python build_index.py            # 重建 INDEX.md
    python build_index.py --check    # 只校验数据完整性（不写文件）

数据完整性校验项：
    - assign 里有、技能目录里没有 → 失效映射
    - 技能目录里有、assign 里没有 → 未分类（阻断，必须补）
    - frontmatter 解析失败 → 无法入索引
"""

import argparse
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lint_skills import split_frontmatter, read_text, safe_stdout  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TAXONOMY = os.path.join(HERE, "taxonomy.json")
INDEX = os.path.join(ROOT, "INDEX.md")

ONE_LINER_MAX = 46
TRIGGER_MAX = 5


def one_liner(desc, override):
    if override:
        return override
    if not desc:
        return "（无描述）"
    s = re.split(r"。|\.\s", desc)[0].strip()
    # 剥掉「（XX 出品）」这类署名标注：16 个 junheng 技能都带，纯噪声
    s = re.sub(r"（[^）]{0,30}出品）", "", s)
    s = s.replace("|", "／").rstrip("。：: ")
    if len(s) > ONE_LINER_MAX:
        cut = s[: ONE_LINER_MAX - 1]
        # 优先在标点处断，避免断在括号或词中间
        pos = max(cut.rfind(c) for c in "，、；：,;")
        if pos >= 18:
            cut = cut[:pos]
        # 断在未闭合的括号里就往回退到括号前
        if cut.count("（") > cut.count("）"):
            p2 = cut.rfind("（")
            if p2 >= 12:
                cut = cut[:p2]
        s = cut.rstrip("，、；：,;（") + "…"
    return s


def _cut(seg, limit=16):
    """把长片段切成若干短触发词，不切碎成单字。"""
    seg = re.split(r"[（(]", seg)[0].strip(" ，,、")
    if not seg:
        return []
    if len(seg) <= limit:
        return [seg]
    out, buf = [], ""
    for piece in re.split(r"[、，,]", seg):
        piece = piece.strip().strip("“”\"'「」").strip()
        if not piece:
            continue
        cand = (buf + "、" + piece) if buf else piece
        if len(cand) <= limit:
            buf = cand
        else:
            if buf:
                out.append(buf)
            buf = piece if len(piece) <= limit else piece[: limit - 1] + "…"
        if len(out) >= 3:
            break
    if buf and len(out) < 3:
        out.append(buf)
    return out


def triggers(desc):
    """从 description 抽触发词。抽不到返回 []（不猜）。"""
    if not desc:
        return []
    d = desc.replace("|", "／")

    # 1) 显式声明（最可信）
    m = re.search(r"触(?:发词|发场景)\s*[：:]\s*(.+)", d)
    if m:
        seg = re.split(r"[。；;]", m.group(1))[0]
        items = [x.strip(" “”\"'「」") for x in re.split(r"[、，,]", seg)]
        items = [x for x in items if 1 < len(x) <= 14]
        if items:
            return items[:TRIGGER_MAX]

    # 2) 问…时用 / 当…时用（不跨句；注意交替顺序，要求/需要必须先于要）
    for pat in (r"问([^。「」]{2,90}?)时(?:使用|用|触发|调用)",
                r"当(?:用户|要|需要|出现)?([^。「」]{2,90}?)时(?:使用|用|触发|调用)"):
        m = re.search(pat, d)
        if not m:
            continue
        seg = re.sub(r"^(用户)?(要求|需要|问|说|要)", "", m.group(1)).strip()
        items = _cut(seg)
        if items:
            return items[:TRIGGER_MAX]

    # 3) 引号内的用户原话（最后兜底；过滤专名与库名）
    q = re.findall(r"[「“\"]([^」”\"]{4,20})[」”\"]", d)
    q = [x.strip() for x in q if "·" not in x and "资料库" not in x and "出品" not in x]
    if q:
        seen, out = set(), []
        for x in q:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out[:TRIGGER_MAX]

    # 4) 英文 Use when ...（英文按逗号切，字符预算放宽）
    m = re.search(r"[Uu]se (?:this skill )?when (.{5,120}?)(?:\.|$)", d)
    if m:
        seg = m.group(1).strip(" ,.")
        parts = [x.strip() for x in seg.split(",") if x.strip()]
        return [(p if len(p) <= 40 else p[:39] + "…") for p in parts][:3]

    return []


def collect():
    tax = json.load(open(TAXONOMY, "r", encoding="utf-8"))
    assign = tax["assign"]
    families = {f["id"]: f for f in tax["families"]}
    summaries = tax.get("summary_zh", {})

    skills, unclassified, broken, orphans = [], [], [], []
    for name in sorted(os.listdir(ROOT)):
        path = os.path.join(ROOT, name)
        if not os.path.isdir(path) or name.startswith("."):
            continue
        internal = name.startswith("_")
        md = os.path.join(path, "SKILL.md")
        if not os.path.isfile(md):
            if not internal:
                orphans.append(name)
            continue
        raw, text = read_text(md)
        fm, err = split_frontmatter(text)
        if err or not fm:
            broken.append((name, err or "无 frontmatter"))
            continue
        desc = fm.get("description") or ""
        desc = desc if isinstance(desc, str) else str(desc)
        fam = assign.get(name)
        if not fam:
            unclassified.append(name)
            continue
        if fam not in families:
            unclassified.append("%s（未知族群 %s）" % (name, fam))
            continue
        skills.append({
            "dir": name,
            "name": fm.get("name") or name,
            "desc": desc.strip(),
            "family": fam,
            "source": "skillhub" if os.path.isfile(os.path.join(path, "_skillhub_meta.json")) else "自建",
            "size": len(raw),
            "mtime": os.path.getmtime(md),
            "line": one_liner(desc.strip(), summaries.get(name)),
            "trig": triggers(desc.strip()),
        })
    stale = [d for d in assign if d not in {s["dir"] for s in skills} and d not in orphans]
    return tax, families, skills, unclassified, broken, orphans, stale


def render(tax, families, skills, unclassified, broken, orphans, stale):
    now = time.strftime("%Y-%m-%d %H:%M")
    total = len(skills)
    by_fam = {}
    for s in skills:
        by_fam.setdefault(s["family"], []).append(s)

    L = []
    L.append("# 技能索引（INDEX）")
    L.append("")
    L.append("> **本文件是产物，不要手改。** 内容来自各技能 frontmatter + `_governance/taxonomy.json`（族群与摘要的人工知识）。")
    L.append("> 重建：`python _governance/build_index.py`｜校验：`python _governance/lint_skills.py --new-only`")
    L.append("> 生成于 %s · 技能 %d 个 · 族群 %d 个" % (now, total, len(by_fam)))
    L.append("")
    L.append("## 怎么用")
    L.append("")
    L.append("1. **接任务先查这里**，按族群扫「一句话」定位候选，再用「触发词」确认是否命中。")
    L.append("2. **新建技能前先查重**：同一族群已有近似能力时，优先扩展现有技能而不是新建。")
    L.append("3. 本索引只解决「有哪些、该用哪个」；单个技能怎么用看它自己的 `SKILL.md`。")
    L.append("")
    L.append("## 族群分布")
    L.append("")
    L.append("| 族群 | 数量 | 覆盖范围 |")
    L.append("|---|---|---|")
    ordered = [f["id"] for f in tax["families"] if f["id"] in by_fam]
    for fid in ordered:
        f = families[fid]
        L.append("| %s | %d | %s |" % (f["label"], len(by_fam[fid]), f["desc"]))
    L.append("| **合计** | **%d** | — |" % total)
    L.append("")

    for fid in ordered:
        f = families[fid]
        rows = sorted(by_fam[fid], key=lambda x: x["name"])
        L.append("## %s（%d）" % (f["label"], len(rows)))
        L.append("")
        L.append("| 技能 | 一句话 | 触发词 | 来源 |")
        L.append("|---|---|---|---|")
        for s in rows:
            trig = "、".join(s["trig"]) if s["trig"] else "—"
            L.append("| `%s` | %s | %s | %s |" % (s["name"], s["line"], trig, s["source"]))
        L.append("")

    # 尾部：治理信息
    L.append("---")
    L.append("")
    L.append("## 附：治理现状")
    L.append("")
    L.append("判定口径：目录名必须等于 frontmatter `name`，且不含 `__` 安装器后缀；`name` 只允许 `a-z0-9._-`。")
    L.append("实时判据以 `_governance/lint_skills.py --new-only` 为准，本节只是本轮快照。")
    L.append("")

    mismatch = [s for s in skills if s["name"] != s["dir"] or "__" in s["dir"]]
    if mismatch:
        L.append("### 命名待修（%d 条，属「批次5 项3」，改名需先验证调用方）" % len(mismatch))
        L.append("")
        L.append("| 目录 | frontmatter name | 问题 |")
        L.append("|---|---|---|")
        for s in mismatch:
            issues = []
            if "__" in s["dir"]:
                issues.append("目录名含 `__` 后缀")
            if s["name"] != s["dir"]:
                issues.append("目录名 ≠ name")
            if not re.match(r"^[a-z0-9][a-z0-9._-]*$", s["name"]):
                issues.append("name 非 slug")
            L.append("| `%s` | `%s` | %s |" % (s["dir"], s["name"], "；".join(issues)))
        L.append("")

    no_trig = [s for s in skills if not s["trig"]]
    if no_trig:
        L.append("### 触发词待补（%d 个）" % len(no_trig))
        L.append("")
        L.append("这些技能的 description 里没有可抽取的触发短语（多为靠显式调用或任务语义触发的元层/平台技能）。")
        L.append("补法：在该技能 `description` 末尾加「当用户…时使用」，或在此处明细里人工确认「无需触发词」。")
        L.append("")
        L.append("　".join("`%s`" % s["dir"] for s in no_trig))
        L.append("")

    over = [s for s in skills if s["size"] > 10240]
    L.append("### 体积超限（%d 个 >10 KB，属「批次4 项10 渐进披露」）" % len(over))
    L.append("")
    L.append("　".join("`%s`(%dB)" % (s["dir"], s["size"]) for s in sorted(over, key=lambda x: -x["size"])))
    L.append("")
    if orphans:
        L.append("### 非技能目录（无 `SKILL.md`，不计入索引）")
        L.append("")
        L.append("、".join("`%s`" % o for o in orphans))
        L.append("")
    L.append("## 附：与其它文件的关系")
    L.append("")
    L.append("| 文件 | 作用 | 真源 |")
    L.append("|---|---|---|")
    L.append("| `INDEX.md`（本文件） | 路由索引：有哪些、该用哪个 | 本文件由脚本生成 |")
    L.append("| `SKILLS-CATALOG.md` | 逐技能完整档案（含版本、完整 description） | 2026-10-25 快照，已过期，重建跑 `~/.workbuddy/gen-skills-catalog.py` |")
    L.append("| `GOVERNANCE.md` | 责任边界与 Tier 分级（为什么这样管） | 手工维护 |")
    L.append("| `_governance/lint_skills.py` | 命名与结构的机器判据 | 脚本即判据 |")
    L.append("| `_governance/taxonomy.json` | 族群与中文摘要的单一真源 | 手工维护 |")
    L.append("")

    if unclassified or broken or stale:
        L.append("## 附：数据缺口（阻断级，必须补）")
        L.append("")
        for x in unclassified:
            L.append("- 未分类：`%s` → 在 `taxonomy.json` 的 `assign` 里补" % x)
        for n, e in broken:
            L.append("- frontmatter 不可解析：`%s`（%s）" % (n, e))
        for x in stale:
            L.append("- 失效映射：`taxonomy.json` 有 `%s`，但目录已不存在" % x)
        L.append("")
    return "\n".join(L) + "\n"


def main(argv=None):
    safe_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只校验，不写文件")
    args = ap.parse_args(argv)

    tax, families, skills, unclassified, broken, orphans, stale = collect()
    problems = unclassified or broken or stale
    print("技能 %d · 族群 %d · 未分类 %d · frontmatter 坏 %d · 失效映射 %d · 空壳 %d"
          % (len(skills), len({s["family"] for s in skills}), len(unclassified),
             len(broken), len(stale), len(orphans)))
    for x in unclassified:
        print("  [未分类] %s" % x)
    for n, e in broken:
        print("  [坏 fm] %s: %s" % (n, e))
    for x in stale:
        print("  [失效映射] %s" % x)

    if args.check:
        return 1 if problems else 0

    text = render(tax, families, skills, unclassified, broken, orphans, stale)
    with open(INDEX, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print("已写入 %s（%d B）" % (INDEX, len(text.encode("utf-8"))))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
