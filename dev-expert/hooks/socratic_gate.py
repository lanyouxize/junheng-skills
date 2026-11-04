#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PreToolUse hook (GLOBAL, opt-in): 需求锁定门控强制化。

把「先锁定需求再执行」（见 references/requirement-lock-socratic.md）从
**指令约束**升级为**技术约束**：在核心目录写入源码前，检查本轮是否已有
状态为 LOCKED 或「已降级」的需求锁定卡；缺失则阻断写入（exit 2）。

设计原则（与本包其余 hook 一致）：
- **默认关闭**：仅当环境变量 SOCRATIC_GATE=1 时生效，未设置一律 exit 0。
  不改变未启用用户的行为，避免"装上就被卡"。
- **非侵入**：只拦「核心目录 + 源码扩展名」的写入，tests/Plan/文档/依赖/构建产物不拦。
- **可豁免**：Trivial Fix（非核心目录 / 非源码扩展名）自动放行；
  另支持显式豁免标记文件，用于用户已明确授权跳过质询的场景。
- 任何异常一律 exit 0（绝不影响原工具执行）。

退出码：
  0 = 放行（未启用 / 豁免 / 已存在锁定卡 / 异常）
  2 = 阻断（已启用、无锁定卡、命中核心目录源码写入）

启用：
  export SOCRATIC_GATE=1

显式豁免（用户已授权跳过质询时，由 Agent 落盘）：
  {PROJECT_ROOT}/.ai-memory/{YYYYMMDD}/socratic_bypass.md
  文件内写任意内容即可；建议注明授权原话与时间。

可配置（环境变量）：
- SOCRATIC_GATE            ：1 启用 / 0 或未设置关闭（默认关闭）
- SOCRATIC_GATE_CORE_DIRS  ：核心目录名，分号分隔；默认与 plan_guard.py 对齐
- SOCRATIC_GATE_EXTS       ：受管扩展名，分号分隔
"""
import sys
import os
import re
import json
import time
import glob

# 核心目录：与 plan_guard.py 默认值对齐，保证两个门禁的适用范围一致
DEFAULT_CORE_DIRS = {"src", "app", "lib", "core", "internal", "system", "engine"}
# 排除目录：这些目录下的写入不属于"核心源码受影响面"
EXCLUDE_DIRS = {
    "tests", "test", "plan", "docs", "doc", "backup", "vendor", "node_modules",
    "uploads", ".codebuddy", ".ai-memory", "dist", "build", "public",
    "static", "assets", "__pycache__", ".git", "migrations", "fixtures",
}
# 受管扩展名
DEFAULT_EXTS = {
    ".php", ".phtml", ".js", ".jsx", ".ts", ".tsx", ".vue", ".py",
    ".java", ".go", ".rb", ".cs", ".kt", ".rs", ".c", ".cpp", ".h",
}
# 锁定卡中被认可的「已完成门控」状态
ACCEPTED_STATES = ("LOCKED", "已降级")


def _split_env(name, default):
    """从环境变量读取分号分隔的集合，未设置时用默认值。"""
    try:
        val = os.environ.get(name, "")
        if not val.strip():
            return default
        return set(p.strip().lower() for p in val.split(";") if p.strip())
    except Exception:
        return default


def _enabled():
    """门控是否启用。默认关闭。"""
    try:
        return os.environ.get("SOCRATIC_GATE", "").strip() == "1"
    except Exception:
        return False


def find_project_root(path):
    """向上找第一个含 .ai-memory 或 .git 或 Plan 的祖先目录作为项目根。"""
    try:
        d = os.path.dirname(os.path.abspath(path))
        for _ in range(12):  # 层数上限，避免在极端路径下长时间上溯
            if (os.path.isdir(os.path.join(d, ".ai-memory"))
                    or os.path.isdir(os.path.join(d, ".git"))
                    or os.path.isdir(os.path.join(d, "Plan"))):
                return d
            nd = os.path.dirname(d)
            if nd == d:
                return None
            d = nd
    except Exception:
        return None
    return None


def find_lock_state(project_root):
    """在最近若干天的记忆目录中查找需求锁定卡，返回 (found, state, lock_path)。

    只看最近 3 天：锁定卡按会话落盘，超过 3 天的卡片不应授权今天的改动。
    """
    try:
        memory_dir = os.path.join(project_root, ".ai-memory")
        if not os.path.isdir(memory_dir):
            return False, None, None
        candidates = []
        for day_dir in os.listdir(memory_dir):
            if not re.fullmatch(r"\d{8}", day_dir):
                continue
            full = os.path.join(memory_dir, day_dir)
            if not os.path.isdir(full):
                continue
            # 按目录名（YYYYMMDD）取最近 3 天
            try:
                day_ts = time.mktime(time.strptime(day_dir, "%Y%m%d"))
            except Exception:
                continue
            if time.time() - day_ts > 3 * 86400:
                continue
            for p in glob.glob(os.path.join(full, "requirement_lock_*.md")):
                candidates.append((os.path.getmtime(p), p))
        if not candidates:
            return False, None, None
        candidates.sort(reverse=True)
        newest = candidates[0][1]
        with open(newest, encoding="utf-8", errors="ignore") as f:
            content = f.read()
        for state in ACCEPTED_STATES:
            if state in content:
                return True, state, newest
        return False, None, newest
    except Exception:
        return False, None, None


def has_bypass(project_root):
    """显式豁免标记文件（用户已授权跳过质询）。"""
    try:
        today = time.strftime("%Y%m%d")
        memory_dir = os.path.join(project_root, ".ai-memory")
        if not os.path.isdir(memory_dir):
            return False
        if os.path.isfile(os.path.join(memory_dir, today, "socratic_bypass.md")):
            return True
        # 也接受任意近期日目录下的豁免标记
        return bool(glob.glob(os.path.join(memory_dir, "*", "socratic_bypass.md")))
    except Exception:
        return False


def main():
    try:
        if not _enabled():
            return 0

        raw = sys.stdin.read()
        if not raw.strip():
            return 0
        data = json.loads(raw)
    except Exception:
        return 0

    try:
        tool_input = data.get("tool_input", {}) or {}
        path = (
            tool_input.get("filePath")
            or tool_input.get("file_path")
            or tool_input.get("path")
            or ""
        )
        if not path:
            return 0
        path = os.path.abspath(path)
        ext = os.path.splitext(path)[1].lower()

        core_dirs = _split_env("SOCRATIC_GATE_CORE_DIRS", DEFAULT_CORE_DIRS)
        exts = _split_env("SOCRATIC_GATE_EXTS", DEFAULT_EXTS)

        # 仅管源码类扩展名
        if ext not in exts:
            return 0

        norm = path.replace("\\", "/").lower()
        parts = norm.split("/")
        # 排除非核心目录
        if any(part in EXCLUDE_DIRS for part in parts):
            return 0
        # 是否落在核心目录
        in_core = any(
            ("/%s/" % d) in norm or norm.endswith("/%s" % d) for d in core_dirs
        )
        if not in_core:
            return 0  # Trivial Fix 通道：非核心目录不拦

        project_root = find_project_root(path)
        if project_root is None:
            return 0  # 无 .ai-memory/.git/Plan 体系则不拦，避免误伤

        if has_bypass(project_root):
            return 0

        found, state, lock_path = find_lock_state(project_root)
        if found:
            return 0

        print("[SOCRATIC-GATE] 阻断：核心目录源码写入前须先完成「需求锁定门控」")
        print("目标: %s" % path)
        if lock_path:
            print("已找到锁定卡但状态未达 LOCKED / 已降级: %s" % lock_path)
        else:
            print("未找到锁定卡。预期位置: %s/.ai-memory/{YYYYMMDD}/requirement_lock_{session-id}.md"
                  % project_root)
        print("")
        print("请任选其一后重试：")
        print("  1) 按 references/requirement-lock-socratic.md 完成质询并落盘锁定卡")
        print("     （状态写 LOCKED，或降级时写「已降级」+ 假设清单）")
        print("  2) 若用户已明确授权跳过质询，落盘豁免标记：")
        print("     %s/.ai-memory/{YYYYMMDD}/socratic_bypass.md" % project_root)
        print("  3) 若不希望本门控生效，取消环境变量 SOCRATIC_GATE（默认即关闭）")
        return 2  # 阻断
    except Exception:
        return 0


if __name__ == "__main__":
    sys.exit(main())
