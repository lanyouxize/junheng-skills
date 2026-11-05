#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""技能「脚本与引用」lint —— 补 lint_skills.py 的观察窗口。

## 为什么需要这个文件

`lint_skills.py` 有一条硬事实：**它只读 `<skill>/SKILL.md` 一个文件**。

    raw, text = read_text(md)      # 全文唯一一次读文件

`scan()` 只 listdir 根目录一层，不进子目录、不递归。九条规则（E1–E5 / W1–W4）
全部作用在 frontmatter 与 SKILL.md 字节数上。实测规模：86 个技能里 59 个带脚本、
共 601 个脚本、72 个在 SKILL.md 里写了路径引用 —— 这些它一个字节都没看过。

它的文档也诚实写着「不在本检查器内」的只有两条（触发词命中、语义重复），
没有提「脚本与引用完全不在观察窗口内」。这就是要补的部分。

## 规则

    S1 ref-dangling   SKILL.md 引用的相对路径在技能目录里不存在
    S2 syntax         脚本语法错误（node --check / py_compile）
    S3 no-scripts-dir SKILL.md 写了 `node scripts/x` 但目录里没有 scripts/
    S4 hidden-skill   隐藏目录下存在 SKILL.md，主 lint 因 startswith(".") 跳过
    S5 fm-overlap     frontmatter 存在语义重叠字段组（platform 读哪个未知）
    S6 fm-whitelist  frontmatter 含非白名单顶层字段（以官方文档并集为合法集）

E = 必须修；W = 需人工判断。

## 为什么 S1 必须分类而不是「路径不存在就报红」

第一版朴素实现报出 21 条悬空引用。逐条核对后**只有 7 条是真的**（全部是
`junheng-*` 的 `node scripts/sync-skills.mjs`——镜像里没有该脚本，也不能放进去）。
其余 14 条是四类噪声，每一类都逼出判据里的一条规则：

    占位示例      scripts/xxx.py、references/research/0X-xxx.md         → PLACEHOLDER_RE
    输出路径      「调研结果必须写入 references/research/01-writings.md」 → OUTPUT_VERB_RE
    跨技能        「See `20-ml-paper-writing` skill's references/…」      → CROSS_SKILL_RE
    示例/区间     「// File: …task.csx (or a new .cs)」、「01-06.md」     → ILLUSTRATIVE_RE / 区间

21 条里 14 条是噪声（67%）。把噪声当缺陷报，就等于让这个检查器学会说谎；
而判据收得太紧又会让真问题漏掉——四轮才收敛，过程记录在
`AI前沿融合方案/23-脚本与引用体检.md`。跳过的每一条都进 skipped 计数，不静默丢弃。

## known.json：带到期日的豁免，而不是冻结基线

`lint_skills.py` 的 baseline.json 把 18 条 E 冻进去，`--new-only` 之后永不报红
——那是「判据的观察窗口被收窄成只看向未来」。本文件的 known.json 每条必须带
`reason` 与 `review_by`（YYYY-MM-DD）；超过 review_by，该项**自动重新报红**并
标注「豁免到期」。豁免因此有寿命，不会变成永久失明。

用法：
    python lint_scripts.py                    # 全量报告
    python lint_scripts.py --json             # 机器可读
    python lint_scripts.py --strict           # W 也计入失败（退出码 2）
    python lint_scripts.py --no-syntax        # 跳过语法检查（快，约 1s）
    python lint_scripts.py --root <dir>       # 指定技能根

退出码：0 通过 / 1 有 E / 2 仅 W 且 --strict / 3 环境错误
"""

import argparse
import concurrent.futures
import datetime
import io
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT_DEFAULT = os.path.dirname(HERE)
KNOWN_PATH = os.path.join(HERE, "lint_scripts_known.json")

SCRIPT_EXT = {".js", ".cjs", ".mjs", ".py", ".sh", ".ps1", ".cmd", ".bat"}
SYNTAX_EXT = {".js", ".cjs", ".mjs", ".py"}
SKIP_DIRS = {"node_modules", "__pycache__", ".git", ".pytest_cache"}

# 引用路径：只认这三类约定目录，且不含占位标记
REF_RE = re.compile(
    r"(?:[\w.\-]+/)*"
    r"(?:scripts|references|assets|templates)/"
    r"[\w.\-/]+\.[A-Za-z0-9]+"
)
# 占位标记：出现即视为示例，不判
PLACEHOLDER_RE = re.compile(r"(?:xxx|XXX|XXx|xx\.|<[^>]*>|\{[^}]*\}|\.\.\.|example|sample)", re.I)

# frontmatter 语义重叠组：同组出现多个即为 W（platform 到底读哪个，无法从本机确认）
#
# 刻意**不含** description_en / description_zh / display_name_en / display_name_zh：
# 那是中英双语约定（61 个技能用 description_en、46 个用 display_name），是规范不是冗余。
# 第一版把它们当重叠组，一次刷出 111 条 W —— 把约定当缺陷，等于让检查器学会说谎。
FM_OVERLAP_GROUPS = [
    ("name", "slug"),                                       # 同一标识两个字段
    ("display_name", "displayName"),                        # 纯拼写差异（下划线 vs 驼峰）
    ("description", "summary"),                             # 主描述 vs 摘要
    ("category", "domain", "type"),                         # 分类维度三套命名
    ("tags", "triggers", "trigger_words", "auto_trigger"),  # 触发线索四套命名
]

# frontmatter 合法字段白名单（S6 判据）。
#
# 来源 = 两份官方文档的并集（任务 x 已核实），外加第三方跨平台工具需要的 2 个字段：
#   - 开放平台 open.workbuddy.cn/docs/skill
#   - CLI      workbuddy.ai/docs/cli/skills
# 另含 1 个本地治理保留字段 `category`（重叠组 {category,domain,type} 经 (x) 裁决选定为规范字段，
# 平台官方未列但保留为本地分类约定，见 FRONTMATTER-WHITELIST.md §3）。
#
# 关键：白名单取**两份文档的并集**，包含当前 93 个技能里尚未使用的合法字段
# （context / agent / model / hooks / examples_zh / examples_en 等）。这样 S6 不会把
# 「官方合法但本机未用」的字段误判为死字段——避免检查器学会说谎（同 S1/S5 的收敛教训）。
# 机器真源即此常量；人读规范见 _governance/FRONTMATTER-WHITELIST.md。
FM_WHITELIST = {
    # 开放平台标准字段
    "name", "display_name", "display_name_en", "description", "description_zh",
    "description_en", "version", "author", "allowed-tools", "examples_zh", "examples_en",
    # CLI 标准字段
    "disable-model-invocation", "user-invocable", "context", "agent", "model", "hooks",
    # 本地治理保留：重叠组 {category, domain, type} 经 (x) 裁决选定 category 为规范字段（见白皮书 §3）
    "category",
    # 第三方跨平台工具需要（保留）
    "license", "metadata",
}

# metadata 内容约束：若把 author/version 塞进 metadata（junheng-core 现状），
# 第三方工具读不到、平台也读不到——应提升为顶层字段。
METADATA_SHOULD_BE_TOPLEVEL = ("author", "version")

# 输出动词：句子在描述「写到哪」时，路径是运行时产物，不该要求已存在。
# 实测依据：nuwa-skill 写「调研结果必须写入 references/research/0X-xxx.md」、
# luobo-ppt 写「assets/manifest.json 记录错误」——两者目录里本就没有该文件。
OUTPUT_VERB_RE = re.compile(
    r"写入|写到|输出|生成|保存|落到|记录|产出|导出|"
    r"\bwrite|\bsave|\boutput|\bgenerate|\bexport|\bdump",
    re.I,
)

# 跨技能引用：句子指向的是**另一个技能**的文件，不该按本技能的目录去判存在性。
# 实测依据：autoresearch 第 71 行「See `20-ml-paper-writing` skill's
# `references/citation-workflow.md`」——文件在 20-ml-paper-writing 里，不在 autoresearch。
CROSS_SKILL_RE = re.compile(r"`[A-Za-z0-9_.\-]+`\s*(?:skill\b|技能)|skill's|技能的", re.I)

# 示例/约定：路径在讲「文件该放这里」或给模板，不是现存文件的指引。
# 实测依据：minimax-docx「// File: scripts/dotnet/task.csx (or a new .cs ...)」。
ILLUSTRATIVE_RE = re.compile(r"\bor a new\b|\bFile:\s*scripts?/|例如|示例|模板位于", re.I)

# 项目根声明：段落里已写明「这些命令在项目根运行 / 技能目录内不含该脚本」，
# 则路径基准不是技能目录，不能按技能目录判存在性。
# 实测依据：junheng-core 的「用法」节有这句声明，其代码块里的 node scripts/sync-skills.mjs
# 是指项目根下的脚本——判它悬空等于否认文档自己的说明。
PROJECT_ROOT_RE = re.compile(r"项目根|仓库根|技能目录内.{0,6}不含|只读镜像", re.I)


def read_text(path):
    with open(path, "rb") as fh:
        return fh.read().decode("utf-8", "replace")


def frontmatter_keys(text):
    m = re.match(r"^\ufeff?---\r?\n(.*?)\r?\n---", text, re.S)
    if not m:
        return []
    out = []
    for line in m.group(1).split("\n"):
        mm = re.match(r"^([A-Za-z_][\w-]*)\s*:", line)
        if mm:
            out.append(mm.group(1))
    return out


def metadata_subkeys(text):
    """返回 frontmatter 里 `metadata:` 容器下的直接子键（一层）。无则空列表。"""
    m = re.match(r"^\ufeff?---\r?\n(.*?)\r?\n---", text, re.S)
    if not m:
        return []
    in_meta = False
    subs = []
    for line in m.group(1).split("\n"):
        if re.match(r"^metadata\s*:\s*$", line):
            in_meta = True
            continue
        if in_meta:
            # 遇到下一个顶层 key（缩进 0 的非空行）即退出 metadata 块
            if line and not line[0].isspace():
                break
            mm = re.match(r"^\s+([A-Za-z_][\w-]*)\s*:", line)
            if mm:
                subs.append(mm.group(1))
    return subs


def iter_scripts(skill_dir):
    for dp, dn, fn in os.walk(skill_dir):
        dn[:] = [d for d in dn if d not in SKIP_DIRS]
        for f in fn:
            if os.path.splitext(f)[1].lower() in SCRIPT_EXT:
                yield os.path.join(dp, f)


def check_syntax(path):
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext in (".js", ".cjs", ".mjs"):
            proc = subprocess.run(["node", "--check", path], capture_output=True,
                                  text=True, encoding="utf-8", errors="replace", timeout=60)
        elif ext == ".py":
            proc = subprocess.run([sys.executable, "-X", "utf8", "-m", "py_compile", path],
                                  capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=60)
        else:
            return None
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return "无法检查: %s" % type(exc).__name__
    if proc.returncode == 0:
        return None
    # 取含 Error 的那一行：node 的 stderr 末尾是版本号横幅（"Node.js v22.22.2"），
    # 直接取 tail[-1] 会把版本号当成错误信息贴出来。
    lines = [l.strip() for l in (proc.stderr or "").split("\n") if l.strip()]
    errs = [l for l in lines if "Error" in l or "error" in l]
    return (errs[0] if errs else (lines[-1] if lines else "退出码 %d" % proc.returncode))[:140]


def scan(root, do_syntax=True, workers=8):
    skills, findings, skipped = [], [], []
    for name in sorted(os.listdir(root)):
        path = os.path.join(root, name)
        if not os.path.isdir(path):
            continue

        # S4：隐藏目录下的技能，主 lint 完全看不见
        if name.startswith("."):
            for dp, dn, fn in os.walk(path):
                dn[:] = [d for d in dn if d not in SKIP_DIRS]
                if "SKILL.md" in fn:
                    rel = os.path.relpath(os.path.join(dp, "SKILL.md"), root).replace("\\", "/")
                    findings.append(("W", "S4", rel, "隐藏目录下的技能，lint_skills.py 不扫描"))
            continue

        md = os.path.join(path, "SKILL.md")
        if not os.path.isfile(md):
            continue
        text = read_text(md)
        skills.append(name)

        # S3：写了 scripts 调用但没有 scripts 目录
        # 先算 S3，再算 S1：两者会命同一行（无 scripts 目录 ⇒ 引用必然不存在），
        # 重复报红会让「6 条问题」看起来像 12 条，修的人会以为漏了一半。
        lines = text.split("\n")
        has_scripts_dir = os.path.isdir(os.path.join(path, "scripts"))
        calls = re.findall(r"(?:node|python3?|py|bash|sh)\s+([\w./\-]*scripts/[\w.\-/]+)", text)
        calls = [c for c in calls if not PLACEHOLDER_RE.search(c)]
        suppress_refs = set()
        if calls and not has_scripts_dir:
            call_ctx = "\n".join(
                "\n".join(lines[max(0, i - 8):i + 1])
                for i, l in enumerate(lines)
                if any(c in l for c in calls)
            )
            # 与 S1 同一条判据：段落已声明在项目根运行，就不该按技能目录查 scripts/
            if PROJECT_ROOT_RE.search(call_ctx):
                skipped.append(("S3", name, calls[0], "项目根命令（段落已声明基准）"))
            else:
                findings.append(("E", "S3", name, "调用 %s 但无 scripts/ 目录" % calls[0]))
                suppress_refs = set(calls)

        # S1：引用路径存在性
        for ref in sorted(set(REF_RE.findall(text))):
            head = ref.split("/")[0]
            if head not in ("scripts", "references", "assets", "templates"):
                continue
            if ref in suppress_refs:
                continue  # 已由 S3 报过，不重复
            if PLACEHOLDER_RE.search(ref):
                skipped.append(("S1", name, ref, "占位示例"))
                continue
            if os.path.exists(os.path.join(path, ref)):
                continue
            # 允许解析到技能根（少数技能引用平级目录）
            if os.path.exists(os.path.join(root, ref)):
                continue
            # 上下文取「命中行 + 前 8 行」：路径性质往往由段首的声明决定，
            # 只看命中行本身会漏掉「以下命令均在项目根运行」这类前提。
            hit = [i for i, l in enumerate(lines) if ref in l]
            ctx = "\n".join("\n".join(lines[max(0, i - 8):i + 1]) for i in hit)
            if PROJECT_ROOT_RE.search(ctx):
                skipped.append(("S1", name, ref, "项目根命令（段落已声明基准）"))
                continue
            if OUTPUT_VERB_RE.search(ctx):
                skipped.append(("S1", name, ref, "运行时产物（上下文含输出动词）"))
                continue
            if CROSS_SKILL_RE.search(ctx):
                skipped.append(("S1", name, ref, "跨技能引用（指向另一技能）"))
                continue
            if ILLUSTRATIVE_RE.search(ctx):
                skipped.append(("S1", name, ref, "示例/约定（非现存文件指引）"))
                continue
            # 区间记法：01-06.md 表示 01.md ~ 06.md 一组文件，不是单个文件名
            if re.search(r"/\d{2}-\d{2}\.[A-Za-z0-9]+$", ref):
                skipped.append(("S1", name, ref, "区间记法（一组文件）"))
                continue
            findings.append(("E", "S1", name, "引用不存在: %s" % ref))

        # S2：语法
        if do_syntax:
            scripts = list(iter_scripts(path))
            if scripts:
                with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
                    results = list(pool.map(check_syntax, scripts))
                for sp, err in zip(scripts, results):
                    if not err:
                        continue
                    rel = os.path.relpath(sp, path).replace("\\", "/")
                    # scripts/ 下是真正的可执行入口 → E；其余目录可能是文档容器 → W
                    level = "E" if rel.startswith("scripts/") else "W"
                    findings.append((level, "S2", name, "语法错误 %s: %s" % (rel, err)))

        # S5：frontmatter 字段重叠
        keys = frontmatter_keys(text)
        for group in FM_OVERLAP_GROUPS:
            present = [k for k in group if k in keys]
            if len(present) > 1:
                findings.append(("W", "S5", name, "语义重叠字段并存: %s" % " / ".join(present)))

        # S6：frontmatter 非白名单字段（判据 = FM_WHITELIST 并集）。
        # 只对顶层 key 做差集；嵌套合法（如 metadata 容器本身合法，但其子键受下方约束）。
        for key in keys:
            if key not in FM_WHITELIST:
                findings.append(
                    ("W", "S6", name, "非白名单 frontmatter 字段: %s（建议删除或并入合法字段）" % key)
                )
        # metadata 内容约束：author/version 应提升为顶层
        if "metadata" in keys:
            for sub in metadata_subkeys(text):
                if sub in METADATA_SHOULD_BE_TOPLEVEL:
                    findings.append(
                        ("W", "S6", name, "metadata.%s 应提升为顶层字段（平台/工具读不到）" % sub)
                    )
    return findings, skills, skipped


def load_known():
    if not os.path.isfile(KNOWN_PATH):
        return []
    try:
        with io.open(KNOWN_PATH, encoding="utf-8") as fh:
            return json.load(fh).get("items", [])
    except Exception:
        return []


def apply_known(findings, known):
    """命中的豁免项移出 findings；review_by 过期的留在 findings 并升级为 E。"""
    today = datetime.date.today().isoformat()
    by_key = {}
    for k in known:
        by_key[(k.get("rule"), k.get("target"))] = k
    kept, used, expired = [], [], []
    for level, rule, target, detail in findings:
        k = by_key.get((rule, target))
        if not k:
            kept.append((level, rule, target, detail))
            continue
        if str(k.get("review_by", "")) < today:
            kept.append(("E", rule, target, "%s（豁免已到期 %s）" % (detail, k.get("review_by"))))
            expired.append(k)
        else:
            used.append(k)
    return kept, used, expired


def main(argv=None):
    ap = argparse.ArgumentParser(description="技能脚本与引用 lint")
    ap.add_argument("--root", default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--no-syntax", action="store_true", help="跳过语法检查")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args(argv)

    root = os.path.abspath(args.root) if args.root else ROOT_DEFAULT
    if not os.path.isdir(root):
        print("环境错误：技能根不存在 %s" % root, file=sys.stderr)
        return 3

    t0 = time.time()
    findings, skills, skipped = scan(root, do_syntax=not args.no_syntax, workers=args.workers)
    known = load_known()
    findings, used, expired = apply_known(findings, known)
    findings.sort(key=lambda x: (x[0], x[1], x[2]))
    errs = [f for f in findings if f[0] == "E"]
    warns = [f for f in findings if f[0] == "W"]
    elapsed = time.time() - t0

    if args.json:
        print(json.dumps({
            "root": root,
            "skill_count": len(skills),
            "elapsed_s": round(elapsed, 1),
            "errors": [{"rule": r, "skill": s, "detail": d} for _, r, s, d in errs],
            "warnings": [{"rule": r, "skill": s, "detail": d} for _, r, s, d in warns],
            "skipped_refs": len(skipped),
            "known_applied": len(used),
            "known_expired": len(expired),
        }, ensure_ascii=False, indent=1))
    else:
        print("技能根：%s" % root)
        print("扫描：%d 个技能 · 语法检查 %s · %.1fs"
              % (len(skills), "关" if args.no_syntax else "开", elapsed))
        print("-" * 70)
        if errs:
            print("[E] %d 条（必须修）" % len(errs))
            for _, r, s, d in errs:
                print("    %s  %-34s %s" % (r, s, d))
        if warns:
            print("[W] %d 条（需人工判断）" % len(warns))
            for _, r, s, d in warns:
                print("    %s  %-34s %s" % (r, s, d))
        if not findings:
            print("无违规。")
        print("-" * 70)
        print("占位引用跳过 %d 条 · 生效豁免 %d 条 · 到期豁免 %d 条"
              % (len(skipped), len(used), len(expired)))
        print("结论：%s" % ("FAIL（%d 条 E）" % len(errs) if errs else "PASS（0 条 E）"))

    if errs:
        return 1
    if args.strict and warns:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
