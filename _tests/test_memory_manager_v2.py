#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
memory-manager-v2 契约断言
核心不变量（安全类，最重要）：
  - 内置定时自动清理必须保持关闭（`_schedule_config.tasks.auto_clean.enabled == false`）
  - 推送类内容的自动清理必须保持关闭（`_automation_rules.push_content.auto_clean == false`）
  - 加固留痕字段存在（便于追溯谁在何时关闭了自动清理）
这三条直接对应「无人值守清理记忆」的风险 —— 被误改会造成数据丢失。
"""
import json
import os

SKILL = "memory-manager-v2"
CFG = "config.json"
PY = "memory_manager.py"


def _enable_auto_clean(text):
    """把自动清理打开 —— 证伪用（模拟高危误配置）。"""
    d = json.loads(text)
    d.setdefault("_automation_rules", {}).setdefault("push_content", {})["auto_clean"] = True
    d.setdefault("_schedule_config", {}).setdefault("tasks", {}).setdefault(
        "auto_clean", {})["enabled"] = True
    return json.dumps(d, ensure_ascii=False, indent=2)


def _break_compile(text):
    return text + "\ndef broken(:\n    pass\n"


FAULTS = {CFG: _enable_auto_clean, PY: _break_compile}


def checks(ctx):
    out = []

    fm = ctx.frontmatter()
    out.append((fm.get("name") == SKILL, f"frontmatter name=={SKILL}（实际 {fm.get('name')!r}）"))
    out.append((bool(fm.get("license")), "frontmatter 含 license"))
    out.append((bool(fm.get("compatibility")), "frontmatter 含 compatibility"))

    # 1. 配置安全不变量
    try:
        cfg = ctx.json(CFG)
    except Exception as e:
        out.append((False, f"{CFG} 解析失败：{e}"))
        cfg = {}

    sched = cfg.get("_schedule_config", {}).get("tasks", {}).get("auto_clean", {})
    out.append((sched.get("enabled") is False,
                f"定时自动清理保持关闭（auto_clean.enabled={sched.get('enabled')!r}，必须为 false）"))

    push = cfg.get("_automation_rules", {}).get("push_content", {})
    out.append((push.get("auto_clean") is False,
                f"推送类自动清理保持关闭（push_content.auto_clean={push.get('auto_clean')!r}，必须为 false）"))

    out.append((bool(cfg.get("_hardened_note")),
                "存在加固留痕 _hardened_note（可追溯关闭自动清理的原因与时间）"))

    # 2. 记忆治理参数合理性
    rd = cfg.get("retention_days")
    out.append((isinstance(rd, int) and rd >= 0,
                f"retention_days 为非负整数（实际 {rd!r}）"))

    # 3. 入口脚本可编译 + 包结构完整
    if ctx.exists(PY):
        try:
            compile(ctx.read(PY), PY, "exec")
            out.append((True, f"{PY} 语法可编译"))
        except SyntaxError as e:
            out.append((False, f"{PY} 语法错误：第{e.lineno}行 {e.msg}"))
    else:
        out.append((False, f"{PY} 缺失"))

    for pkg in ("memory_manager/cli.py", "memory_manager/clean.py"):
        out.append((ctx.exists(pkg), f"{pkg} 存在"))

    return out
