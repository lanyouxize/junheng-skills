#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T4 验收固化：literature-reviewer-skill 拆分后能力不得退化。

真不变量（自包含，不依赖工作区临时备份）：
  1. SKILL.md 主体 < 500 行（规范建议线）
  2. 渐进式披露导航表列出全部 5 个 references 文件，且每个真实存在
  3. 两个外置文件存在且 >100 行（不是空壳）
  4. Phase 8 唯一执行依据的导航铁律仍在
  5. 批 C-2 断点段落三命令完整保留
  6. frontmatter 合法且 name == 目录名
  7. 代码块围栏闭合

可证伪：FAULTS 从导航表删掉 phase8-synthesis.md 路径 => 断言 2/4 必须失败。
"""
import os
import re

import yaml

SKILL = "_t4_split"  # 横切标签，避免与 test_literature_reviewer_skill.py 同名
TARGET = "../literature-reviewer-skill/"
NAV_FILES = [
    "cnki-guide.md", "database-access.md", "gb-t-7714-2015.md",
    "phase8-synthesis.md", "appendix.md",
]

FAULTS = {
    TARGET + "SKILL.md":
        lambda t: t.replace("references/phase8-synthesis.md",
                            "references/REMOVED.md"),  # 全局替换：该路径出现 3 处
}


def checks(ctx):
    out = []
    sk = ctx.read(TARGET + "SKILL.md")
    lines = sk.splitlines()

    # 1. 主体行数
    out.append((len(lines) < 500, f"SKILL.md 主体 {len(lines)} 行 < 500"))

    # 2. 只认「渐进式披露导航」区块内列出的路径（全文提及不算导航）
    nav_sec = sk.split("## 渐进式披露导航", 1)[-1].split("\n## ", 1)[0]
    listed = set(re.findall(r"references/([A-Za-z0-9._-]+\.md)", nav_sec))
    expected = set(NAV_FILES)
    missing_ref = sorted(expected - listed)
    extra_ref = sorted(listed - expected)
    missing_disk = [f for f in NAV_FILES
                    if not os.path.isfile(ctx.path(TARGET + "references/" + f))]
    out.append((not missing_ref and not extra_ref and not missing_disk,
                "导航区块恰好列出 5 个 references 文件且均存在"
                + (f"；表缺 {missing_ref}；表多 {extra_ref}；盘缺 {missing_disk}"
                   if missing_ref or extra_ref or missing_disk else "")))

    # 3. 外置文件非空
    thin = []
    for f in ("phase8-synthesis.md", "appendix.md"):
        n = len(ctx.read(TARGET + "references/" + f).splitlines())
        if n <= 100:
            thin.append(f"{f}={n}行")
    out.append((not thin, "两个外置文件均 >100 行" + (f"；过薄 {thin}" if thin else "")))

    # 4. Phase 8 唯一执行依据
    out.append(("唯一执行依据" in sk and "phase8-synthesis.md" in sk,
                "Phase 8 唯一执行依据铁律仍在"))

    # 5. 批 C-2 断点段落完整
    cmds = [c for c in ("--declare", "--complete", "--resume") if c in sk]
    out.append((len(cmds) == 3,
                f"断点段落三命令完整（实得 {cmds}）"))

    # 6. frontmatter
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
        fm = yaml.safe_load("\n".join(lines[1:end]))
        ok = isinstance(fm, dict) and fm.get("name") == "literature-reviewer-skill"
        out.append((bool(ok), "frontmatter 合法且 name 未变"))
    except Exception as e:
        out.append((False, f"frontmatter 解析失败：{type(e).__name__}"))

    # 7. 代码块围栏
    fences = sum(1 for l in lines if l.startswith("```"))
    out.append((fences % 2 == 0, f"代码块围栏闭合（{fences} 个）"))

    return out
