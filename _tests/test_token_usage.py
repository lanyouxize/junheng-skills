#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
token-usage 契约断言
核心不变量：
  - 统计脚本必须是「纯标准库」（该技能自我声明纯本地、离线可用，引入第三方即破坏承诺）
  - 必须提供 --json / --html 两个输出通道（SKILL.md 承诺的能力）
  - HTML 面板依赖的自包含 echarts 资产存在
"""
import ast
import re

SKILL = "token-usage"
PY = "scripts/token_stats.py"

STDLIB_HINT = {
    "argparse", "datetime", "glob", "json", "os", "sys", "re", "time", "collections",
    "pathlib", "html", "http", "urllib", "io", "typing", "math", "csv", "shutil",
    "subprocess", "threading", "functools", "itertools", "dataclasses", "logging",
    "tempfile", "sqlite3", "hashlib", "textwrap", "errno", "socket", "webbrowser",
    "contextlib", "traceback", "string", "random", "base64", "platform", "locale",
    # 3.9+ 起为标准库，易被漏列（zoneinfo 就是首次误报的来源）
    "zoneinfo", "unittest", "warnings", "queue", "concurrent", "asyncio", "signal",
    "statistics", "decimal", "fractions", "abc", "enum", "types", "copy", "pprint",
}


def _break_syntax(text):
    """插入语法错误 —— 证伪用。"""
    return text + "\ndef broken(:\n    pass\n"


FAULTS = {PY: _break_syntax}


def checks(ctx):
    out = []

    fm = ctx.frontmatter()
    out.append((fm.get("name") == SKILL, f"frontmatter name=={SKILL}（实际 {fm.get('name')!r}）"))
    out.append((bool(fm.get("license")), "frontmatter 含 license"))
    out.append((bool(fm.get("compatibility")), "frontmatter 含 compatibility"))

    if not ctx.exists(PY):
        out.append((False, f"{PY} 缺失"))
        return out

    src = ctx.read(PY)

    # 1. 语法可编译（证伪点：注入语法错误后必须失败）
    try:
        compile(src, PY, "exec")
        out.append((True, f"{PY} 语法可编译"))
    except SyntaxError as e:
        out.append((False, f"{PY} 语法错误：第{e.lineno}行 {e.msg}"))

    # 2. 纯标准库（AST 解析 import，比正则可靠）
    third = []
    try:
        tree = ast.parse(src)
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module.split(".")[0]]
            for n in names:
                if n not in STDLIB_HINT:
                    third.append(n)
    except SyntaxError:
        pass
    third = sorted(set(third))
    out.append((not third, "仅依赖 Python 标准库" + (f"；发现非标准库：{third}" if third else "")))

    # 3. 承诺的输出通道
    has_json = bool(re.search(r'add_argument\(\s*["\']--json', src))
    has_html = bool(re.search(r'add_argument\(\s*["\']--html', src))
    out.append((has_json, "提供 --json 输出通道"))
    out.append((has_html, "提供 --html 输出通道"))

    # 4. 自包含前端资产
    js = "scripts/echarts.min.js"
    if ctx.exists(js):
        import os
        size = os.path.getsize(ctx.path(js))
        out.append((size > 100_000, f"{js} 存在且 >100KB（实际 {size//1024}KB）"))
    else:
        out.append((False, f"{js} 缺失（HTML 面板将无法离线渲染）"))

    return out
