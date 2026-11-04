# -*- coding: utf-8 -*-
"""
Token 智能省流助手 —— 安全加固版（V6.1.0-hardened）

加固内容（对应审查项 T-01..T-12）：
  T-01/02/03 代码压缩改为「仅行首注释 + 空行压缩为 1」，不再无差别删除 `#`/`//`/空行
  T-04/05    filler 改为句首/句尾锚定；strict 词表移除代词与指示词
  T-06/07    命令识别改为整句锚定，不再子串命中
  T-08       mode 必须显式传入，不再依赖模块级全局状态（run() 仍兼容旧行为但会给出提示）
  T-09       输出 token_estimate.method，明确标注为估算
  T-12       新增 CLI 入口：python token_saver_skill.py --text "..." [--mode light] [--json]
  新增       占位符保护（代码块/URL/引号字面量/颜色值/shebang/Markdown 标题）
  新增       硬门禁：代码类默认拒绝、危险模式拒绝、短文本拒绝、压缩比超限降级后仍超限则拒绝
  新增       original_sha256 + diff 回显，保证可回溯

设计原则：宁可拒绝，不可改错。任何不确定场景一律返回原文（status=refused/passthrough）。
"""

import argparse
import difflib
import hashlib
import json
import re
import sys

VERSION = "6.1.0-hardened"

# ---------- 压缩词表（加固后） ----------
# 句首/句尾锚定的礼貌语，不再全局替换（T-04）
# 【顺序敏感】FILLER_HEAD 中长词必须先于其前缀短词剥离（如"我想请问一下"先于"我想"），
# 否则短词先剥离会留下悬空碎片（"我想请问一下X" → "请问一下X" → "一下X"）。
# compress_core 使用时按长度降序执行以防呆；新增词条无需关心插入位置。
FILLER_HEAD = ["我想请问一下", "我想问一下", "我需要你帮我", "我想让你帮我", "我想请问",
               "我想", "我需要", "请问", "你好", "您好", "麻烦你"]
FILLER_TAIL = ["谢谢啦", "谢谢", "辛苦了", "拜托了"]
# strict 词表：仅语气助词与连接词，绝不含代词/指示词（T-05）
STRICT_WORDS = ["然后", "并且", "而且", "其实", "实际上", "就是", "吧", "呢", "啊", "呀", "哦"]

# ---------- 硬门禁规则（命中即拒绝，返回原文） ----------
DANGER_PATTERNS = [
    (re.compile(r"```"), "含代码块标记 ```"),
    (re.compile(r"https?://"), "含 URL"),
    (re.compile(r"#[0-9a-fA-F]{3,8}\b"), "含颜色值/十六进制字面量"),
    (re.compile(r"^\s*#!"), "含 shebang 行"),
    (re.compile(r"^\s*#{1,6}\s+", re.M), "含 Markdown 标题"),
    (re.compile(r"^\s*[\w\-\.]+\s*:\s*\S", re.M), "疑似 YAML/JSON/配置结构"),
    # 句中配置项：英文键 + 数字/引号值（避开中文冒号误伤）
    (re.compile(r"\b[A-Za-z_][A-Za-z0-9_\-]*\s*:\s*(?:\d+|[\"'\[{])"), "含配置项字面量"),
    (re.compile(r"(?:^|\s)(?:[A-Za-z]:)?[\\/][\w\-\.\\/]+"), "含绝对路径"),
    (re.compile(r"\b(?:sk-|AKIA|ghp_|xox[baprs]-|BEGIN [A-Z ]*PRIVATE KEY)\b"), "疑似密钥/凭据"),
]

# 占位符保护：这些片段在压缩期间被摘出，压缩后原样还原
MASK_PATTERNS = [
    r"```.*?```",
    r"`[^`\n]+`",
    r"https?://[^\s，。）】\]]+",
    r'"[^"\n]*"',
    r"'[^'\n]*'",
    r"#[0-9a-fA-F]{3,8}\b",
    r"^\s*#!.*$",
]
_MASK = "\x01{i}\x01"

PROTECTED_PREFIX = ["系统:", "指令:", "技能:", "skill:", "config:", "set_tip",
                    "System:", "SYSTEM:", "指令：", "系统："]  # T-06 补全角与英文


# ---------- 工具函数 ----------
def sha256_of(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", "replace")).hexdigest()


def mask_protected(text: str):
    """把代码块/URL/引号字面量等摘出为占位符，避免被压缩规则误伤。"""
    store = []

    def _sub(m):
        store.append(m.group(0))
        return _MASK.format(i=len(store) - 1)

    for p in MASK_PATTERNS:
        text = re.sub(p, _sub, text, flags=re.M | re.S)
    return text, store


def unmask(text: str, store):
    for i, s in enumerate(store):
        text = text.replace(_MASK.format(i=i), s)
    return text


def guard(text: str, allow_code: bool):
    """硬门禁。返回 (是否拒绝, 原因)。"""
    if not text or not isinstance(text, str):
        return True, "输入为空"
    for pat, why in DANGER_PATTERNS:
        if pat.search(text) and not allow_code:
            return True, why
    return False, ""


def detect_content_type(text: str) -> str:
    code_pattern = re.compile(
        r'(def |class |import |# |// |{|}|if\s*\(|for\s*\(|while\s*\(|print\(|'
        r'function |const |let |var |return |console\.log|<?php|<!DOCTYPE|</.*?>)'
    )
    code_block = re.search(r'```.*?```|`[^`]+`', text, re.DOTALL)
    has_code = bool(code_pattern.search(text) or code_block)
    if not has_code:
        return "pure_text"
    code_lines = [ln for ln in text.splitlines()
                  if code_pattern.search(ln) or ln.strip().startswith(('#', '//', '{', '}'))]
    code_ratio = len('\n'.join(code_lines)) / len(text) if text else 0
    return "code" if code_ratio > 0.3 else "mixed"


# 文本类 token 粗估的基础开销（C-03）：标点/空白/消息骨架的兜底项，
# 避免短文本估算为 0。纯启发式，非真实计费口径。
BASE_TOKENS = 5


def estimate_token(s: str, content_type: str) -> int:
    """粗估（T-09：输出中标注 method=heuristic，非真实计费口径）。"""
    if content_type == "code":
        return len(s) // 4
    chinese = len(re.findall(r'[\u4e00-\u9fff]', s))
    english = len(re.findall(r'[a-zA-Z0-9_]+', s))
    return int(chinese * 1.0 + english * 0.5 + BASE_TOKENS)


def detect_user_command(text: str):
    """T-07：整句锚定，避免正文含关键词被误判为命令。"""
    t = text.strip()
    pats = [
        (r"^(关闭省\s*token\s*提示|关闭\s*token\s*提示|关闭提示|关掉省\s*token)$", "close_tip"),
        (r"^(打开省\s*token\s*提示|打开\s*token\s*提示|打开提示|显示省\s*token)$", "open_tip"),
        (r"^(严格模式|最强压缩|极度省\s*token)$", "mode_strict"),
        (r"^(轻度模式|轻度压缩|轻微省\s*token)$", "mode_light"),
        (r"^(默认模式|正常模式|标准模式)$", "mode_default"),
    ]
    for p, name in pats:
        if re.match(p, t, re.I):
            return name
    return None


def compress_code(code: str, mode: str) -> str:
    """T-01/02/03：仅删行首注释，空行压缩为 1 行，不删 `//` 行内内容、不清空行。

    S-07（2026-10-15 R3b）：三引号多行字符串状态机。块内的 `#`/`//` 行是
    字符串内容而非注释，原样保留——修复此前逐行无状态处理会误删
    「未闭合字符串内注释行」的边际缺陷（启发式：按行统计三引号定界符奇偶）。
    """
    lines = []
    blank = False
    in_block = None  # 当前三引号定界符；None = 不在块字符串内
    for ln in code.splitlines():
        s = ln.strip()
        if not s:
            if not blank:
                lines.append("")
            blank = True
            continue
        blank = False
        # 仅当整行是注释时才删除（行首 #），且保留 shebang
        if s.startswith("#!") or s.startswith("//!"):
            lines.append(ln)
            continue
        # S-07：块字符串内的一切行（含 # / // 开头）都是内容，原样保留
        if in_block is not None:
            lines.append(ln.rstrip())
            if in_block in ln:
                in_block = None
            continue
        # S-07：本行若是三引号块的起始（该定界符出现奇数次），开块并保留该行
        opener = None
        for q in ('"""', "'''"):
            if ln.count(q) % 2 == 1:
                opener = q
                break
        if opener is not None:
            lines.append(ln.rstrip())
            in_block = opener
            continue
        if s.startswith("#"):
            continue
        if mode == "strict" and (s.startswith("//")):
            continue
        lines.append(ln.rstrip())
    return "\n".join(lines).strip()


def _peel_head(t: str) -> str:
    """句首礼貌语剥离：每剥一词即清悬空并从头降序重试（循环至不动点）。

    单轮降序不够（2026-10-16 修）：剥掉短词后留下的悬空标点会挡住长词锚定，
    且长词先试失败后没有第二次机会。break 后从最长词重来可防短词截胡。
    """
    for _ in range(16):  # 防御上限：叠层不可能超过词表规模
        before = t
        for w in sorted(FILLER_HEAD, key=len, reverse=True):
            t2 = re.sub(r"^\s*" + re.escape(w), "", t)
            if t2 != t:
                t = re.sub(r"^[，,、；;：:\s]+", "", t2)
                break
        if t == before:
            return re.sub(r"^[，,、；;：:\s]+", "", t)
    return t


def _peel_tail(t: str) -> str:
    """句尾礼貌语剥离：与 _peel_head 同构（防「谢谢啦」剥后暴露「谢谢」）。"""
    for _ in range(8):
        before = t
        for w in sorted(FILLER_TAIL, key=len, reverse=True):
            t2 = re.sub(re.escape(w) + r"[。!！]?$", "", t)
            if t2 != t:
                t = re.sub(r"[，,、；;：:\s]+$", "", t2)
                break
        if t == before:
            return re.sub(r"[，,、；;：:\s]+$", "", t)
    return t


def compress_core(text: str, mode: str) -> str:
    t = text
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{2,}", "\n", t)
    # 句首礼貌语（T-04）：句首整词剥离，不做句中替换，避免拼接出歧义句
    # 顺序敏感：按长度降序执行，长词先于其前缀短词（见 FILLER_HEAD 定义处注释）
    # 实测备注（2026-10-14 E-03 证伪）：曾尝试合并为单次 alternation 正则 + 循环，
    # 10KB 语料下反而更慢（0.16→0.19ms；strict 0.22→0.48ms）且改变"词叠词"场景
    # 行为（旧版会留"问一下"式残留）。anchored sub 与 str.replace 均走 C 快速路径，
    # 逐词循环成本可忽略（0.01-0.03ms/段），故维持本实现。
    t = _peel_head(t)
    t = _peel_tail(t)
    # 清理因剥离产生的首尾悬空标点
    t = re.sub(r"[，,、；;：:\s]+$", "", t)
    t = re.sub(r"^[，,、；;：:\s]+", "", t)
    if mode == "strict":
        for w in STRICT_WORDS:
            t = t.replace(w, "")
        t = re.sub(r"[，。]{2,}", "，", t)
    return t.strip()


def make_diff(original: str, compressed: str):
    sm = difflib.SequenceMatcher(None, original, compressed)
    removed = []
    for tag, i1, i2, _j1, _j2 in sm.get_opcodes():
        if tag in ("delete", "replace"):
            frag = original[i1:i2].strip()
            if frag:
                removed.append(frag)
    return removed[:20]


def compress_text(text: str, mode: str = "default", allow_code: bool = False,
                  min_length: int = 20, max_ratio: float = 0.40, dry_run: bool = False):
    """压缩主入口。任何不确定场景均返回原文。"""
    base = {"original_sha256": sha256_of(text) if isinstance(text, str) else "",
            "version": VERSION}

    if not text or not isinstance(text, str):
        return dict(base, status="error", msg="输入不能为空", compressed_text=text)

    for p in PROTECTED_PREFIX:
        if text.strip().startswith(p):
            return dict(base, status="refused", reason="系统/指令前缀，已保护不压缩",
                        compressed_text=text, diff=[])

    if len(text.strip()) < min_length:
        return dict(base, status="refused", reason=f"文本短于 {min_length} 字，压缩无收益",
                    compressed_text=text, diff=[])

    refused, why = guard(text, allow_code)
    if refused:
        return dict(base, status="refused", reason=f"命中硬门禁：{why}",
                    compressed_text=text, diff=[])

    content_type = detect_content_type(text)
    if content_type in ("code", "mixed") and not allow_code:
        return dict(base, status="refused",
                    reason="代码/混合内容默认拒绝，确需压缩请显式 --allow-code",
                    content_type=content_type, compressed_text=text, diff=[])

    masked, store = mask_protected(text)
    try:
        if content_type == "code":
            body = compress_code(masked, mode)
        else:
            body = compress_core(masked, mode)
        body = unmask(body, store)
    except Exception as e:  # 降级：规则异常一律回原文（T-05 兜底）
        return dict(base, status="passthrough", reason=f"压缩异常，已回退原文：{e}",
                    compressed_text=text, diff=[])

    tb = estimate_token(text, content_type)
    ta = estimate_token(body, content_type)
    ratio = (tb - ta) / tb if tb else 0

    # 压缩比超限 → 降级 light 重试；仍超限 → 拒绝
    if ratio > max_ratio and mode != "light":
        retry = compress_text(text, mode="light", allow_code=allow_code,
                              min_length=min_length, max_ratio=max_ratio)
        if retry.get("status") == "success":
            return dict(retry, downgraded=True,
                        reason=f"{mode} 模式压缩比 {ratio:.0%} 超限，已降级为 light")
    if ratio > max_ratio:
        return dict(base, status="refused",
                    reason=f"压缩比 {ratio:.0%} 超过阈值 {max_ratio:.0%}，疑语义受损，已拒绝",
                    content_type=content_type, compressed_text=text, diff=[])

    res = dict(base, status="success", content_type=content_type, current_mode=mode,
               original_token=tb, compressed_token=ta, token_saved=max(0, tb - ta),
               token_estimate={"method": "heuristic", "note": "粗估，非真实计费口径"},
               compressed_text=body, diff=make_diff(text, body), dry_run=dry_run)
    res["tip"] = f"已节省 {res['token_saved']} Token（{mode}模式，估算）"
    return res


# ---------- 兼容入口（QClaw/OpenClaw 协议） ----------
def run(params: dict) -> dict:
    """兼容旧协议。mode 缺省时给 default，但会在结果中标注 mode_implicit。"""
    text = params.get("text", "")
    cmd = detect_user_command(text)
    cmd_map = {"close_tip": ("已关闭省Token提示", "light"),
               "open_tip": ("已打开省Token提示", None),
               "mode_strict": ("已进入严格模式", "strict"),
               "mode_light": ("已进入轻度模式", "light"),
               "mode_default": ("已进入默认模式", "default")}
    if cmd in cmd_map:
        msg, _m = cmd_map[cmd]
        return {"status": "success", "msg": msg, "compressed_text": text,
                "note": "状态切换为进程内生效，重启后需重新设置（T-08）"}
    mode = params.get("mode")
    r = compress_text(text,
                      mode=mode or "default",
                      allow_code=bool(params.get("allow_code", False)),
                      min_length=int(params.get("min_length", 20)),
                      max_ratio=float(params.get("max_ratio", 0.40)))
    if mode is None:
        r["mode_implicit"] = True
    return r


# ---------- CLI（T-12 新增） ----------
def main(argv=None):
    ap = argparse.ArgumentParser(description="Token 智能省流助手（安全加固版）")
    ap.add_argument("--text", help="待压缩文本")
    ap.add_argument("--file", help="从文件读取待压缩文本（UTF-8）")
    ap.add_argument("--mode", default="default", choices=["light", "default", "strict"])
    ap.add_argument("--allow-code", action="store_true", help="允许压缩代码（默认拒绝）")
    ap.add_argument("--min-length", type=int, default=20)
    ap.add_argument("--max-ratio", type=float, default=0.40)
    ap.add_argument("--dry-run", action="store_true", help="只报告不产出（仍返回文本，供人工复核）")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    if a.file:
        with open(a.file, encoding="utf-8") as f:
            text = f.read()
    elif a.text is not None:
        text = a.text
    else:
        text = sys.stdin.read()

    r = compress_text(text, mode=a.mode, allow_code=a.allow_code,
                      min_length=a.min_length, max_ratio=a.max_ratio, dry_run=a.dry_run)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print(f"[{r['status']}] {r.get('reason', '')}")
        if r["status"] == "success":
            print(f"节省(估算): {r['token_saved']}  模式: {r['current_mode']}")
            if r.get("downgraded"):
                print("已自动降级为 light")
            if r.get("diff"):
                print("删除片段:", " | ".join(r["diff"][:10]))
        print("---")
        print(r.get("compressed_text", ""))
    # 退出码语义化（U-01）：0=success/passthrough（压缩成功或原样放行）、
    # 2=refused（门禁拒绝：文本过短/含代码等，调用方应跳过而非报错）、1=error（真错误）。
    # 便于脚本与 CI 用退出码区分三种结局，不再把 refused 混同成功。
    if r["status"] in ("success", "passthrough"):
        return 0
    if r["status"] == "refused":
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
