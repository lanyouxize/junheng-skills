# -*- coding: utf-8 -*-
"""
S-gate：天工.skill 产物安全门禁（新增，不改变原有 verify-skill.py）

背景：verify-skill.py 只做结构/格式/规则冲突校验，安全项仅为建议级（fix_suggestion），
      生成的 Agent 即便声明宽泛 shell 权限也能通过。S-gate 补齐安全侧硬门禁。

用法：
    python scripts/s-gate.py <产物SKILL.md> [--json]
退出码：0 = PASS，1 = FAIL（FAIL 时禁止交付，回退蒸馏 3 / J3）

五项检查：
    S1 权限白名单  metadata.requires.bins / env / files 必须显式声明且落在允许清单内
    S2 危险模式    不得出现 rm -rf / del /S / format / chmod 777 / 无边界 shell 调用
    S3 密钥        不得出现 sk- / AKIA / ghp_ / xox[baprs]- / BEGIN PRIVATE KEY / 明文口令
    S4 网络最小化  若声明网络能力，必须写明域名白名单
    S5 免责声明    人格型产物（含"蒸馏"/人物名/emoji 人设）必须含 disclaimer 字段

只读脚本：不写入、不删除、不联网。
"""

import argparse
import json
import re
import sys

ALLOWED_BINS = {
    "python", "python3", "node", "npm", "npx", "git", "curl", "jq",
    "bash", "sh", "ls", "cat", "grep", "find", "rg", "ffmpeg", "pandoc",
}

DANGER_PATTERNS = [
    (re.compile(r"rm\s+-rf\s+/"), "rm -rf /"),
    (re.compile(r"rm\s+-rf\s+(?:\$|~|\*)"), "rm -rf 带变量/通配（无边界删除）"),
    (re.compile(r"del\s+/[sSfF]"), "del /S /F（Windows 批量删除）"),
    (re.compile(r"\bformat\s+[a-zA-Z]:"), "format 盘符"),
    (re.compile(r"chmod\s+777"), "chmod 777"),
    (re.compile(r"shell\s*=\s*True"), "shell=True（潜在命令注入面）"),
    (re.compile(r"os\.system\s*\("), "os.system 调用"),
    (re.compile(r"eval\s*\(|exec\s*\("), "eval/exec 动态执行"),
    (re.compile(r":\s*fork\s*bomb|:\(\)\{"), "fork bomb"),
]

SECRET_PATTERNS = [
    (re.compile(r"\bsk-[A-Za-z0-9]{16,}"), "OpenAI 风格密钥"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}"), "AWS Access Key"),
    (re.compile(r"\bghp_[A-Za-z0-9]{20,}"), "GitHub Token"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"), "Slack Token"),
    (re.compile(r"BEGIN [A-Z ]*PRIVATE KEY"), "私钥块"),
    (re.compile(r"(?:password|passwd|pwd)\s*[:=]\s*['\"][^'\"]{6,}['\"]"), "明文口令"),
]

NET_HINTS = re.compile(r"\b(https?://|fetch\(|requests\.|urllib|curl\s|WebFetch|联网|网络请求)", re.I)
DOMAIN_WHITELIST = re.compile(r"(?:白名单|allowlist|whitelist|allowed_domains|域名)")
# S5 要求 front-matter 中显式存在 disclaimer 键（正文措辞不算，避免"基于公开资料"之类的弱匹配）
DISCLAIMER_FM = re.compile(r"^\s*disclaimer\s*:", re.I | re.M)
PERSONA_HINT = re.compile(r"蒸馏|人格|人物|人设|心智模型|persona", re.I)


def parse_front_matter(text):
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if not m:
        return None, text
    return m.group(1), text[m.end():]


def check_bins(fm):
    """S1：解析 metadata.requires.bins（简易 YAML 列表解析，不依赖第三方库）。

    覆盖两种 YAML 形态：
      1) flow 序列（单行）：  bins: [python, git]
      2) block 序列（多行）：bins:
                               - python
                               - git

    返回值 (declared, unknown)：
      - declared=None 表示 bins 键存在但解析不到任何条目（多行/畸形格式），
        调用方必须 fail-closed 判 FAIL，不得按"空声明"放行——否则白名单外
        程序可用多行格式声明绕过 S1。
      - declared=[] 且无 bins 键时为合法的空声明（无外部程序依赖）。
    """
    # 形态1：flow 序列（单行）
    m = re.search(r"bins\s*:\s*\[([^\]]*)\]", fm)
    if m:
        declared = [x.strip().strip("\"'") for x in m.group(1).split(",") if x.strip()]
        unknown = [b for b in declared if b.split("/")[-1] not in ALLOWED_BINS]
        return declared, unknown
    # 形态2：block 序列（多行，"- " 前缀行）
    m = re.search(r"bins\s*:\s*\n((?:[ \t]*-[ \t]*\S+[^\n]*(?:\n|$))+)", fm)
    if m:
        declared = []
        for ln in m.group(1).splitlines():
            item = ln.strip()
            if item.startswith("-"):
                item = item[1:].strip().strip("\"'")
                if item:
                    declared.append(item)
        unknown = [b for b in declared if b.split("/")[-1] not in ALLOWED_BINS]
        return declared, unknown
    # bins 键存在但两种形态都解析不到 → fail-closed 信号
    if re.search(r"\bbins\s*:", fm):
        return None, []
    # 无 bins 键 → 合法空声明
    return [], []


def run(path):
    try:
        text = open(path, encoding="utf-8").read()
    except Exception as e:
        return {"path": path, "result": "FAIL", "checks": [("S0", False, f"读取失败：{e}")]}, 1

    fm, body = parse_front_matter(text)
    checks = []

    # S1
    if fm is None:
        checks.append(("S1", False, "缺少 YAML front-matter，无法声明权限"))
    else:
        declared, unknown = check_bins(fm)
        if declared is None:
            checks.append(("S1", False, "bins 声明存在但无法解析（多行或畸形格式），按 fail-closed 拒绝放行"))
        elif unknown:
            checks.append(("S1", False, f"声明了白名单外的可执行程序：{unknown}"))
        else:
            checks.append(("S1", True, f"bins 已声明且在白名单内：{declared or '（空，无外部程序依赖）'}"))

    # S2/S3 只在「非代码片段」中检测 —— 文档里用反引号引用的规则字面量属于说明，不算真实声明。
    # 代价：把危险命令藏进代码块的产物不会被 S2/S3 拦下；S-gate 是声明级门禁，不是沙箱，
    # 运行时隔离由宿主负责（已在脚本顶部说明）。
    scan = re.sub(r"```.*?```", " ", text, flags=re.S)
    scan = re.sub(r"`[^`\n]+`", " ", scan)

    hits = [why for pat, why in DANGER_PATTERNS if pat.search(scan)]
    checks.append(("S2", not hits, "无危险模式" if not hits else f"命中危险模式：{hits}"))

    hits3 = [why for pat, why in SECRET_PATTERNS if pat.search(scan)]
    checks.append(("S3", not hits3, "无密钥/凭据" if not hits3 else f"疑似密钥：{hits3}"))

    # S4
    if NET_HINTS.search(text):
        ok4 = bool(DOMAIN_WHITELIST.search(text))
        checks.append(("S4", ok4, "已声明网络能力并给出域名白名单"
                       if ok4 else "声明了网络能力但未给出域名白名单"))
    else:
        checks.append(("S4", True, "未声明网络能力"))

    # S5
    if PERSONA_HINT.search(text):
        ok5 = bool(fm and DISCLAIMER_FM.search(fm))
        checks.append(("S5", ok5, "人格型产物已含免责声明"
                       if ok5 else "人格型产物缺少 disclaimer/免责声明字段"))
    else:
        checks.append(("S5", True, "非人格型产物，免检"))

    passed = all(ok for _, ok, _ in checks)
    return {
        "path": path,
        "gate": "S-gate v1.0",
        "result": "PASS" if passed else "FAIL",
        "checks": [{"id": i, "passed": ok, "detail": d} for i, ok, d in checks],
        "on_fail": "禁止交付；回退蒸馏 3 / J3 补充后再过门禁",
    }, (0 if passed else 1)


def main(argv=None):
    ap = argparse.ArgumentParser(description="天工产物安全门禁")
    ap.add_argument("skill_md", nargs="+", help="待检的 SKILL.md 路径（可多个）")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    rc = 0
    reports = []
    for p in a.skill_md:
        rep, code = run(p)
        reports.append(rep)
        rc = max(rc, code)

    if a.json:
        print(json.dumps({"overall": "PASS" if rc == 0 else "FAIL", "reports": reports},
                         ensure_ascii=False, indent=2))
    else:
        for rep in reports:
            print(f"[{rep['result']}] {rep['path']}")
            for c in rep["checks"]:
                flag = "OK  " if c["passed"] else "FAIL"
                print(f"   {flag} {c['id']}: {c['detail']}")
            if rep["result"] == "FAIL":
                print(f"   -> {rep['on_fail']}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
