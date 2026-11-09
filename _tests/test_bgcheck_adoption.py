#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T2 验收固化：5 个长任务技能必须真正接入 bg_check.py 断点纪律。

真不变量（不是"文件存在"这类永不失败的伪检查）：
  1. 5 个技能均无 MANIFEST.json —— 保证改动不会被 sync 覆盖 / 不破坏 sha256
  2. 每个 SKILL.md 都含完整三条命令 --declare / --complete / --resume
  3. 每条命令都指向真实存在的 bg_check.py，且工具自身 --selftest 通过
  4. 段落含「不做什么」边界，防止被当成万能流程滥用

可证伪：FAULTS 把 multi-search-engine 的 --declare 改名，断言 2 必须失败。
"""
import os
import sys

# 横切契约（覆盖 5 个技能），用独立标签避免与 test_multi_search_engine.py 同名
SKILL = "_bg_adoption"
SKILLS_DIR = r"C:/Users/Administrator/.workbuddy/skills"
TOOL = r"C:/Users/Administrator/.workbuddy/tools/bg_check.py"
MARK = "## 长任务断点登记（bg_check）"

TARGETS = [
    "literature-reviewer-skill",
    "dev-expert",
    "wechat-article-scraper",
    "multi-search-engine",
    "free-model-market",
]

# 证伪：把 multi-search-engine 的 --declare 改掉 => 断言 2 必须失败
FAULTS = {
    "../multi-search-engine/SKILL.md":
        lambda t: t.replace("--declare", "--DECL-REMOVED"),
}


def _read(name, ctx):
    """ctx.dir 是虚拟标签目录，统一经 ../<name>/SKILL.md 解析；
    这样 FAULTS 能污染指定文件，实现可证伪。"""
    return ctx.read("../%s/SKILL.md" % name)


def checks(ctx):
    out = []

    # 1. 无 MANIFEST（防止改成只读镜像）
    mirrored = [n for n in TARGETS
                if os.path.isfile(os.path.join(SKILLS_DIR, n, "MANIFEST.json"))]
    out.append((not mirrored,
                "5 个断点技能均非只读镜像（无 MANIFEST）"
                + (f"；违规 {mirrored}" if mirrored else "")))

    # 2. 三命令齐全（核心契约）
    missing = []
    for n in TARGETS:
        try:
            t = _read(n, ctx)
        except Exception as e:
            missing.append(f"{n}:读取失败 {type(e).__name__}")
            continue
        for cmd in ("--declare", "--complete", "--resume"):
            if cmd not in t:
                missing.append(f"{n} 缺 {cmd}")
        if MARK not in t:
            missing.append(f"{n} 缺段落标记")
    out.append((not missing,
                "5 个技能均含断点段落与 declare/complete/resume 三命令"
                + (f"；缺失 {missing[:5]}" if missing else "")))

    # 3. 工具真实存在且自检通过（真运行时验证）
    out.append((os.path.isfile(TOOL), f"bg_check.py 存在于 {TOOL}"))
    if os.path.isfile(TOOL):
        rc, so, se = ctx.run([sys.executable, TOOL, "--selftest"],
                             cwd=SKILLS_DIR, timeout=60)
        out.append((rc == 0 and "selftest: PASS" in (so + se),
                    f"bg_check.py --selftest 通过（exit={rc}）"))
    else:
        out.append((False, "bg_check.py --selftest 无法执行（工具缺失）"))

    # 4. 边界声明（防止万能流程化）
    no_boundary = [n for n in TARGETS
                   if "不做什么" not in _read(n, ctx)]
    out.append((not no_boundary,
                "5 个技能均写明「不做什么」边界"
                + (f"；缺 {no_boundary}" if no_boundary else "")))

    return out
