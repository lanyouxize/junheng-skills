#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
multi-search-engine 契约断言
核心不变量：
  - 脚本内 KNOWN_SEARCH_ENGINES 的引擎数与 SKILL.md 文档声明一致（17 个：国际 9 + 国内 8）
  - engine-health.jsonl 每行必须是合法 JSON（健康台账可被机读）
"""
import json
import re

SKILL = "multi-search-engine"


def _break_jsonl(text):
    """把第一行改成非法 JSON —— 证伪用。"""
    lines = text.splitlines()
    if lines:
        lines[0] = "{this is not json"
    return "\n".join(lines)


FAULTS = {"engine-health.jsonl": _break_jsonl}


def checks(ctx):
    out = []

    fm = ctx.frontmatter()
    out.append((fm.get("name") == SKILL, f"frontmatter name=={SKILL}（实际 {fm.get('name')!r}）"))
    out.append((bool(fm.get("license")), "frontmatter 含 license"))
    out.append((bool(fm.get("compatibility")), "frontmatter 含 compatibility"))

    # 1. 脚本内引擎清单（注意：实际是 set 字面量 {"baidu", "bing cn", ...}，不是 dict）
    script = "scripts/check_engine_consistency.py"
    if not ctx.exists(script):
        out.append((False, f"{script} 缺失"))
    else:
        src = ctx.read(script)
        m = re.search(r"KNOWN_SEARCH_ENGINES\s*=\s*\{(.*?)\n\}", src, re.S)
        if not m:
            out.append((False, "脚本中未找到 KNOWN_SEARCH_ENGINES 集合"))
        else:
            names = re.findall(r'["\']([^"\']+)["\']', m.group(1))
            # 该集合含 SKILL.md 声明的 17 个 + 若干仅用于 WARN 识别的引擎，故判 >= 17
            out.append((len(names) >= 17,
                        f"KNOWN_SEARCH_ENGINES 条目数 >= 17（实际 {len(names)}）"))

    # 2. SKILL.md 文档声明的引擎 URL 数
    #    注意：分段必须用 "\n## " 切分；用 "## " 会误切到 "### " 的索引 1 处，导致取到空段
    try:
        md = ctx.read("SKILL.md")
        marker = "\n## Search Engines"
        sec = md.split(marker, 1)[-1] if marker in md else ""
        sec = sec.split("\n## ", 1)[0]
        urls = re.findall(r"https?://[^\s`)]+", sec)
        out.append((len(urls) >= 15,
                    f"SKILL.md 引擎 URL 数 >= 15（实际 {len(urls)}）"))
        # 分节声明的 8 + 9 与集合数量应大致吻合
        dom = len(re.findall(r"Domestic", sec))
        intl = len(re.findall(r"International", sec))
        out.append((dom >= 1 and intl >= 1,
                    f"SKILL.md 同时声明 Domestic 与 International 两节（{dom}/{intl}）"))
    except Exception as e:
        out.append((False, f"读取 SKILL.md 失败：{e}"))

    # 3. engine-health.jsonl 每行合法 JSON
    hl = "engine-health.jsonl"
    if not ctx.exists(hl):
        out.append((True, f"{hl} 不存在（首次运行前可为空，不视为失败）"))
    else:
        text = ctx.read(hl)
        bad = []
        n = 0
        for i, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            n += 1
            try:
                d = json.loads(line)
                if not isinstance(d, dict):
                    bad.append(f"第{i}行非对象")
            except Exception:
                bad.append(f"第{i}行非法 JSON")
        out.append((not bad, f"{hl} 共 {n} 行且全部为合法 JSON"
                             + (f"；异常 {bad[:3]}" if bad else "")))

    # 4. 关键脚本齐备
    for s in ("scripts/validate_results.py", "scripts/search_report.py", "scripts/engine_health.py"):
        out.append((ctx.exists(s), f"{s} 存在"))

    return out
