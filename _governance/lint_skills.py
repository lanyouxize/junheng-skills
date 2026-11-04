#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""技能命名与结构 lint。

用途：把「命名规范」从文档约定变成可执行判据。只读扫描，不改任何技能文件。

用法：
    python lint_skills.py                  # 全量报告（红黄分级）
    python lint_skills.py --baseline       # 把当前存量写入 baseline.json（冻结基线）
    python lint_skills.py --new-only       # 只报基线之外的新增违规（退出码即判据）
    python lint_skills.py --json           # 机器可读输出
    python lint_skills.py --strict-warn    # 警告也计入失败

规则（E=必须修，W=建议修）：
    E1 dir-suffix   目录名含 ``__``（skillhub 等安装器残留后缀）
    E2 dir-vs-name  目录名 ≠ frontmatter 的 name
    E3 name-slug    name 不是合法 slug（只允许 a-z 0-9 . _ -）
    E4 frontmatter  frontmatter 缺失 / YAML 无法解析 / name 字段缺失
    E5 desc-empty   description 缺失或有效字符 < 10
    W1 orphan-dir   非 ``_``/``.`` 开头的目录里没有 SKILL.md（空壳）
    W2 oversize     SKILL.md > 10240 字节（渐进披露阈值）
    W3 desc-long    description > 1024 字符（挤占系统提示预算）
    W4 desc-short   description < 20 字符（触发线索不足）

退出码：0 = 通过（无基线外新增）；1 = 有新增 E；2 = 有新增 W（仅 --strict-warn）。

不在本检查器内的项（正则判不准语义，交人工）：
    - description 是否写得能命中触发（由 INDEX.md 的「触发词」列人工核对）
    - 技能之间语义是否重复（由合并评审判断）
"""

import argparse
import io
import json
import os
import re
import sys
import time
import unicodedata

try:
    import yaml
except ImportError:  # 降级：用极简解析，仅保证不崩溃
    yaml = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "baseline.json")

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
OVERSIZE = 10240
DESC_MAX = 1024
DESC_MIN = 20

E_RULES = {"E1", "E2", "E3", "E4", "E5"}


def safe_stdout():
    """终端编码不匹配时用替换字符兜底，避免 UnicodeEncodeError 中断扫描。"""
    enc = (sys.stdout.encoding or "").lower().replace("-", "")
    if enc not in ("utf8", "gbk", "cp936", "utf16"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding=sys.stdout.encoding or "utf-8",
            errors="replace", line_buffering=True)


def read_text(path):
    with open(path, "rb") as f:
        raw = f.read()
    return raw, raw.decode("utf-8", errors="replace")


def split_frontmatter(text):
    """返回 (frontmatter_dict_or_None, error_str_or_None)。"""
    m = re.match(r"^\ufeff?---\r?\n(.*?)\r?\n---\s*(\r?\n|$)", text, re.S)
    if not m:
        return None, "无 frontmatter（首行须为 ---）"
    body = m.group(1)
    if yaml is None:
        out = {}
        for line in body.splitlines():
            mm = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", line)
            if mm:
                out[mm.group(1)] = mm.group(2).strip()
        return out, None
    try:
        data = yaml.safe_load(body)
    except Exception as exc:
        return None, "YAML 解析失败: %s" % str(exc).splitlines()[0][:120]
    if not isinstance(data, dict):
        return None, "frontmatter 不是键值映射"
    return data, None


def scan(root):
    findings = []
    skills = []
    for name in sorted(os.listdir(root)):
        path = os.path.join(root, name)
        if not os.path.isdir(path):
            continue
        if name.startswith("."):
            continue
        internal = name.startswith("_")
        md = os.path.join(path, "SKILL.md")
        if not os.path.isfile(md):
            if not internal:
                findings.append(("W1", name, "目录内无 SKILL.md（空壳目录）"))
            continue
        raw, text = read_text(md)
        size = len(raw)
        fm, err = split_frontmatter(text)
        rec = {"dir": name, "size": size, "name": None, "desc": "",
               "internal": internal, "mtime": os.path.getmtime(md), "ok": False}
        if err:
            findings.append(("E4", name, err))
            skills.append(rec)
            continue
        fm_name = fm.get("name")
        desc = fm.get("description") or ""
        if not isinstance(desc, str):
            desc = str(desc)
        rec["name"] = fm_name if isinstance(fm_name, str) else None
        rec["desc"] = desc.strip()
        rec["ok"] = True

        if not rec["name"]:
            findings.append(("E4", name, "frontmatter 缺 name 字段"))
        else:
            if not SLUG_RE.match(rec["name"]):
                findings.append(("E3", name, "name=%r 不是合法 slug" % rec["name"]))
            if rec["name"] != name:
                findings.append(("E2", name, "目录名 %r ≠ name %r" % (name, rec["name"])))
        if "__" in name:
            findings.append(("E1", name, "目录名含安装器后缀 __"))
        if len(rec["desc"]) < 10:
            findings.append(("E5", name, "description 缺失或过短（%d 字符）" % len(rec["desc"])))
        else:
            if len(rec["desc"]) > DESC_MAX:
                findings.append(("W3", name, "description %d 字符 > %d" % (len(rec["desc"]), DESC_MAX)))
            elif len(rec["desc"]) < DESC_MIN:
                findings.append(("W4", name, "description 仅 %d 字符 < %d" % (len(rec["desc"]), DESC_MIN)))
        if size > OVERSIZE:
            findings.append(("W2", name, "SKILL.md %d B > %d B" % (size, OVERSIZE)))
        skills.append(rec)
    return findings, skills


def key(item):
    return "%s|%s" % (item[0], item[1])


def load_baseline():
    if not os.path.isfile(BASELINE):
        return None
    try:
        with open(BASELINE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def main(argv=None):
    safe_stdout()
    ap = argparse.ArgumentParser(description="技能命名与结构 lint")
    ap.add_argument("--baseline", action="store_true", help="写入/刷新基线")
    ap.add_argument("--new-only", action="store_true", help="只报基线外新增")
    ap.add_argument("--json", action="store_true", help="JSON 输出")
    ap.add_argument("--strict-warn", action="store_true", help="警告也计入失败")
    ap.add_argument("--root", default=None, help="技能根目录（默认脚本上级）")
    args = ap.parse_args(argv)

    root = os.path.abspath(args.root) if args.root else ROOT
    findings, skills = scan(root)
    findings.sort(key=lambda x: (x[0], x[1]))

    if args.baseline:
        payload = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "root": root,
            "skill_count": len(skills),
            "count": len(findings),
            "items": [{"rule": r, "dir": d, "detail": t} for r, d, t in findings],
        }
        with open(BASELINE, "w", encoding="utf-8", newline="\n") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
            f.write("\n")
        print("已写入基线：%s（%d 条，%d 个技能）" % (BASELINE, len(findings), len(skills)))
        return 0

    base = load_baseline()
    known = {key((i["rule"], i["dir"])) for i in base["items"]} if base else set()
    fresh = [f for f in findings if key(f) not in known]
    resolved = []
    if base:
        now = {key(f) for f in findings}
        resolved = [i for i in base["items"] if "%s|%s" % (i["rule"], i["dir"]) not in now]

    errs = [f for f in fresh if f[0] in E_RULES]
    warns = [f for f in fresh if f[0] not in E_RULES]

    if args.json:
        print(json.dumps({
            "skill_count": len(skills),
            "total": len(findings),
            "baseline_count": len(known) if base else None,
            "new_errors": [{"rule": r, "dir": d, "detail": t} for r, d, t in errs],
            "new_warnings": [{"rule": r, "dir": d, "detail": t} for r, d, t in warns],
            "resolved": resolved,
        }, ensure_ascii=False, indent=1))
    else:
        by_rule = {}
        for r, d, t in findings:
            by_rule.setdefault(r, []).append((d, t))
        print("技能根：%s" % root)
        print("扫描：%d 个技能 · 存量问题 %d 条" % (len(skills), len(findings)))
        if base:
            print("基线：%s（%d 条）" % (base.get("generated_at", "?"), len(known)))
        print("-" * 68)
        if not args.new_only:
            for r in sorted(by_rule):
                print("[%s] %d 条" % (r, len(by_rule[r])))
                for d, t in by_rule[r]:
                    print("    - %-46s %s" % (d, t))
            print("-" * 68)
        if base is None:
            print("未建基线：全量即存量。跑 --baseline 冻结后，--new-only 可作 CI 判据。")
        else:
            print("基线外新增：E %d 条 / W %d 条" % (len(errs), len(warns)))
            for r, d, t in fresh:
                print("    + [%s] %s  %s" % (r, d, t))
            if resolved:
                print("已消解（基线有、现在无）：%d 条" % len(resolved))
                for i in resolved:
                    print("    - [%s] %s" % (i["rule"], i["dir"]))
        if not fresh:
            print("结论：PASS（无基线外新增违规）")

    if errs:
        return 1
    if args.strict_warn and warns:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
