#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
免费模型超市 · 智能排障引擎（doctor）

终端用户往往是小白：装了 Skill、往 ~/.workbuddy/models.json 配了自定义模型，
一调用就 401/403/404/超时，完全不知道原因。本脚本做三件事：

    1. 扫描 models.json（支持 Windows / Unix / --models-path 覆盖，不依赖 cwd）
    2. 逐条诊断（Key 形态、Base URL 形态、在线探测、免费层、能力标签、配置问题）
    3. 给出小白能看懂的「你该做什么」可执行修复

设计铁律：
    * 失败必须分层——任何 HTTP 响应码都证明网络层通畅，
      403/401/404 是政策/鉴权层证据，绝不归为「网络不通」。
    * 绝不打印完整 API Key，只显示前 6 + 后 4 字符（脱敏）。
    * 默认只读；只有 `--fix-safe --yes` 才会落盘，且只做绝对安全的修改
      （当前无 --fix-safe 项：原「去掉 url 末尾 /chat/completions」规则已于
      2026-10-09 删除，实测该改写会把可用配置改成 404），绝不改 apiKey、绝不删记录。

判定枚举：OK / MISMATCH / WARN / UNREACHABLE / ERROR / UNKNOWN

用法：
    python 免费模型超市-doctor.py                全量体检，输出 Markdown 报告
    python 免费模型超市-doctor.py --json          JSON 输出（供 AI 消费）
    python 免费模型超市-doctor.py --fix-safe      预览「绝对安全」的修复（不落盘）
    python 免费模型超市-doctor.py --fix-safe --yes  执行上述修复并写回
    python 免费模型超市-doctor.py --models-path <路径>  指定其他 models.json
    python 免费模型超市-doctor.py --no-probe      跳过在线探测（纯本地静态分析）

仅用标准库；Windows Git-Bash 下中文输出已做 stdout 编码处理。
"""
from __future__ import annotations

# --- 沙箱容错：强制 UTF-8 输出，避免非 UTF-8 控制台（cp1252/cp936）抛 UnicodeEncodeError ---
try:
    import sys as _sys
    for _stream in (_sys.stdout, _sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
except Exception:
    pass
# --- end 沙箱容错 ---

import argparse
import json
import os
import shutil
import socket
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# 0. 控制台编码处理（Windows Git-Bash 下 stdout 可能是 GBK，直接打印中文会崩）
# ─────────────────────────────────────────────────────────────────────────────
def _fix_stdio_encoding() -> None:
    """把 stdout/stderr 重新包成 UTF-8，避免 GBK 环境打印中文抛 UnicodeEncodeError。"""
    for name in ("stdout", "stderr"):
        buf = getattr(sys, name, None)
        if buf is None:
            continue
        cur = getattr(buf, "encoding", "") or ""
        if cur.lower() in ("utf-8", "utf8", "utf8mb4"):
            continue
        try:
            raw = buf.buffer  # TextIOWrapper 才有 .buffer
        except Exception:
            continue
        setattr(
            sys,
            name,
            type("__utf8io", (), {
                "write": lambda s, _b=raw: _b.write(s.encode("utf-8", "replace")),
                "flush": lambda: raw.flush(),
                "isatty": lambda: False,
            })(),
        )


_fix_stdio_encoding()

# 东八区时间戳
TZ = timezone(timedelta(hours=8))


# ─────────────────────────────────────────────────────────────────────────────
# 1. 关键诊断事实表（项目实测确认）
# ─────────────────────────────────────────────────────────────────────────────

# Key 前缀 → (期望厂商, 期望 Base URL)
# 顺序即匹配优先级：越长越特异的前缀放前面
KEY_VENDOR_RULES: list[tuple[str, str, str]] = [
    ("sk-or-v1-", "OpenRouter", "https://openrouter.ai/api/v1"),
    ("gsk_",      "Groq",        "https://api.groq.com/openai/v1"),
    ("hf_",       "Hugging Face", "https://api-inference.huggingface.co/models"),
    ("nvapi-",    "NVIDIA NIM",  "https://integrate.api.nvidia.com/v1"),
    ("AIza",      "Google AI Studio", "https://generativelanguage.googleapis.com/v1beta"),
    ("sk-",       "未知(OpenAI 类?)", ""),   # 无特征，无法判定
]

# host（后缀匹配）→ 期望厂商
HOST_VENDOR_RULES: list[tuple[str, str]] = [
    ("api.groq.com",                    "Groq"),
    ("openrouter.ai",                   "OpenRouter"),
    ("api.openai.com",                  "OpenAI"),
    ("api-inference.huggingface.co",    "Hugging Face"),
    ("integrate.api.nvidia.com",        "NVIDIA NIM"),
    ("generativelanguage.googleapis.com","Google AI Studio"),
    ("opencode.ai",                     "OpenCode Zen"),
]

# 厂商 → 期望 Base URL（用于生成修复建议）
VENDOR_BASE_URL: dict[str, str] = {
    "OpenRouter":          "https://openrouter.ai/api/v1",
    "Groq":                "https://api.groq.com/openai/v1",
    "Hugging Face":        "https://api-inference.huggingface.co/models",
    "NVIDIA NIM":          "https://integrate.api.nvidia.com/v1",
    "Google AI Studio":    "https://generativelanguage.googleapis.com/v1beta",
    "OpenAI":              "https://api.openai.com/v1",
    "OpenCode Zen":        "https://opencode.ai/zen/v1",
}

# 免密钥标记（不是秘密，不做脱敏）
PUBLIC_KEY_TOKENS = {"public", "免密钥", "none", "null", ""}

# 探测用 User-Agent。
# 2026-10-09 实测：opencode.ai 前置 Cloudflare，默认 python-urllib UA 会被
# 拦成 `403 error code: 1010`（UA 拦截），换浏览器 UA 立即 200。
# 故 doctor 探测统一带浏览器 UA，避免把「UA 拦截」误判成「服务不可用」。
PROBE_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# OpenCode Zen 免费层（2026-10-13 复测 9 个 -free 模型，带浏览器 UA）：
#   space-bunny-free           → 403 FreeTierError（2026-10-13，外部免费通道已归零）
#   jev/ling-3.1/longcat/mimo-v2.6/nemotron×2 → 403 FreeTierError（限 OpenCode 客户端）
#   muse-spark×2               → 403 RegionError（本地域拦截）
#   deepseek-v4-flash/fledge/mimo-v2.5        → 401 ModelError
#   ling-3.0-flash-fin         → 400 上游错误
#   exo-free                   → 410 ModelDeprecated（已下线）
# 结论（2026-10-13）：无任何外部可用节点，不再维护 OPENCODE_ZEN_EXTERNAL_OK_MODEL 常量。

# 判定优先级（数值越大越严重，用于决定「模型整体判定」）
SEVERITY = {
    "OK": 0,
    "UNKNOWN": 1,
    "WARN": 2,
    "UNREACHABLE": 3,
    "MISMATCH": 4,
    "ERROR": 5,
}


# ─────────────────────────────────────────────────────────────────────────────
# 2. 工具函数
# ─────────────────────────────────────────────────────────────────────────────

def mask_key(api_key: str) -> str:
    """API Key 脱敏：只显示前 6 + 后 4 字符，绝不打印完整 Key。"""
    if api_key is None:
        return "(空/未填)"
    k = str(api_key).strip()
    if k.lower() in PUBLIC_KEY_TOKENS:
        return f"(免密钥: {k})" if k else "(空/未填)"
    if len(k) <= 10:
        # 太短，整体打码，避免泄露
        return "****(已脱敏)"
    return f"{k[:6]}…{k[-4:]}"


def key_vendor(api_key: str) -> tuple[str, str]:
    """根据 Key 前缀判定「期望厂商」与「期望 Base URL」。返回 (vendor, base_url)。"""
    if api_key is None:
        return ("未知", "")
    k = str(api_key).strip()
    if k.lower() in PUBLIC_KEY_TOKENS:
        # public 是 OpenCode Zen 的免 Key 约定
        return ("OpenCode Zen", VENDOR_BASE_URL["OpenCode Zen"])
    for prefix, vendor, base in KEY_VENDOR_RULES:
        if k.startswith(prefix):
            return (vendor, base)
    return ("未知", "")


def host_vendor(url: str) -> str | None:
    """根据 url 的 host 后缀判定厂商；无法识别返回 None。"""
    if not url:
        return None
    try:
        from urllib.parse import urlparse
        host = urlparse(url).netloc.lower()
    except Exception:
        return None
    for suffix, vendor in HOST_VENDOR_RULES:
        if host == suffix or host.endswith("." + suffix) or host.endswith(suffix):
            return vendor
    return None


def strip_chat_completions(url: str) -> str:
    """去掉 OpenAI 兼容端点末尾可能多余的 /chat/completions，得到 Base URL。"""
    if not url:
        return url
    suffix = "/chat/completions"
    if url.rstrip("/").endswith(suffix):
        return url[: url.rstrip("/").rfind(suffix)]
    return url


# ─────────────────────────────────────────────────────────────────────────────
# 3. 诊断数据模型
# ─────────────────────────────────────────────────────────────────────────────

class Finding:
    """单条诊断发现。"""

    def __init__(self, level: str, code: str, message: str, fix: str,
                 safe_fix: dict | None = None):
        self.level = level          # OK/MISMATCH/WARN/UNREACHABLE/ERROR/UNKNOWN
        self.code = code            # 机器码，如 KEY_ENDPOINT_MISMATCH
        self.message = message      # 给人看的现象
        self.fix = fix              # 直白的「你该做什么」
        self.safe_fix = safe_fix    # 仅 --fix-safe 用：{"field":, "old":, "new":}

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "code": self.code,
            "message": self.message,
            "fix": self.fix,
            "safe_fix": self.safe_fix,
        }


class ModelReport:
    def __init__(self, raw: dict, idx: int):
        self.raw = raw
        self.idx = idx
        self.id = raw.get("id") or raw.get("name") or f"记录#{idx + 1}"
        self.name = raw.get("name", "")
        self.vendor = raw.get("vendor", "")
        self.url = raw.get("url", "")
        self.api_key = raw.get("apiKey", "")
        self.findings: list[Finding] = []
        self.probe: dict | None = None

    @property
    def verdict(self) -> str:
        if not self.findings:
            return "OK"
        return max((f.level for f in self.findings),
                   key=lambda lv: SEVERITY.get(lv, 0))

    def add(self, f: Finding) -> None:
        self.findings.append(f)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "vendor": self.vendor,
            "masked_key": mask_key(self.api_key),
            "url": self.url,
            "verdict": self.verdict,
            "findings": [f.to_dict() for f in self.findings],
            "probe": self.probe,
        }


# ─────────────────────────────────────────────────────────────────────────────
# 4. 在线探测（失败分层）
# ─────────────────────────────────────────────────────────────────────────────

def probe_url(base_url: str) -> dict:
    """对 base_url 发 GET 探测，超时 15 秒。

    铁律：任何 HTTP 响应码都证明网络层通畅；
    只有 connect=0 / DNS 失败 / 连接超时 才判 UNREACHABLE。
    """
    result = {"ok": False, "http_code": None, "detail": "", "level": None}
    if not base_url or not base_url.startswith("http"):
        result["detail"] = "url 非法，无法探测"
        result["level"] = "ERROR"
        return result
    try:
        req = urllib.request.Request(
            base_url,
            method="GET",
            headers={"User-Agent": PROBE_UA},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            code = resp.status
            result.update(
                ok=True,
                http_code=code,
                detail=f"HTTP {code}（网络层通畅，任何响应码都说明能连上）",
                level="OK",
            )
    except urllib.error.HTTPError as e:
        # HTTPError 仍代表收到了服务器响应 → 网络层 OK，属政策/鉴权层
        result.update(
            ok=True,
            http_code=e.code,
            detail=f"HTTP {e.code}（网络层通畅；{e.code} 属政策/鉴权层证据，不是网络不通）",
            level="OK",
        )
    except urllib.error.URLError as e:
        # URLError 通常是 DNS / 连接被拒 / 超时
        reason = str(getattr(e, "reason", e))
        result["detail"] = (
            f"不可达：{reason}。"
            "可能是本地网络无法直连该域名"
            "（你在中国大陆，Google/OpenAI/xAI 等常需代理），不是服务故障。"
        )
        result["level"] = "UNREACHABLE"
    except socket.timeout:
        result["detail"] = (
            "连接超时（15s）。可能是本地网络无法直连该域名"
            "（你在中国大陆，部分海外域名需代理），不是服务故障。"
        )
        result["level"] = "UNREACHABLE"
    except OSError as e:
        result["detail"] = (
            f"连接失败：{e}。"
            "可能是本地网络无法直连该域名（你在中国大陆常需代理），不是服务故障。"
        )
        result["level"] = "UNREACHABLE"
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 5. 逐条诊断
# ─────────────────────────────────────────────────────────────────────────────

def diagnose_model(raw: dict, idx: int, do_probe: bool) -> ModelReport:
    rep = ModelReport(raw, idx)

    # —— 规则 6：字段缺失（url / apiKey）——
    if not rep.url:
        rep.add(Finding(
            "ERROR", "MISSING_URL",
            "这条记录缺少 url（API 端点），WorkBuddy 不知道往哪发请求。",
            "补上 url 字段，例如 Groq 填 https://api.groq.com/openai/v1。",
        ))
    if not rep.api_key:
        rep.add(Finding(
            "ERROR", "MISSING_APIKEY",
            "这条记录缺少 apiKey，调用会被直接拒绝（401）。",
            "去对应厂商控制台复制 API Key 填到 apiKey 字段（OpenCode Zen 免费层可填 \"public\"）。",
        ))

    # —— 规则 2（2026-10-09 移除）：Base URL 形态（/chat/completions 后缀）——
    # 实测证据（Windows，2026-10-09，POST https://opencode.ai/zen/v1/chat/completions）：
    #   保留后缀（完整路径）+ 浏览器 UA → HTTP 200，content="OK"
    #   去掉后缀（/zen/v1）      + 浏览器 UA → HTTP 404（返回 HTML 页面）
    # 结论：对会自行拼接路径的端点，带后缀的完整路径才是正确写法。
    # 旧版 doctor 曾把该形态判为 WARN 并纳入 --fix-safe，会把唯一可用的
    # 零配置模型（space-bunny-free）改坏。规则本身是错的，已整体删除，
    # 不保留提示——留着等于继续诱导用户改坏配置。

    # —— 规则 1：Key 形态与端点厂商不匹配（最高频故障）——
    if rep.url and rep.api_key:
        k_vendor, k_base = key_vendor(rep.api_key)
        h_vendor = host_vendor(rep.url)
        if k_vendor.startswith("未知"):
            # 无特征 sk- 类（无法判定厂商）→ 标 WARN，不臆断为 MISMATCH
            if h_vendor:
                rep.add(Finding(
                    "WARN", "KEY_VENDOR_UNKNOWN",
                    f"Key 形态（sk- 开头）无法判定厂商，端点是 {h_vendor}；"
                    "无法确认两者是否匹配。",
                    f"若调用报 401/403，请核对该 Key 确实属于 {h_vendor}，"
                    f"或把端点改为对应厂商 Base URL（如 {VENDOR_BASE_URL.get(h_vendor, '')}）。",
                ))
            else:
                rep.add(Finding(
                    "UNKNOWN", "KEY_VENDOR_UNKNOWN",
                    "Key 形态无法判定厂商，且 url 域名也无法识别厂商；无法确认是否匹配。",
                    "请人工核对 Key 与 url 确实属于同一厂商。",
                ))
        elif h_vendor is None:
            # host 认不出厂商，无法确认匹配，标 UNKNOWN
            rep.add(Finding(
                "UNKNOWN", "HOST_VENDOR_UNKNOWN",
                f"无法从 url 的域名识别厂商（{rep.url}），无法确认与 Key（{k_vendor}）是否匹配。",
                "请人工核对 url 域名确实属于该 Key 对应的厂商。",
            ))
        elif k_vendor != h_vendor:
            rep.add(Finding(
                "MISMATCH", "KEY_ENDPOINT_MISMATCH",
                f"Key 属于「{k_vendor}」厂商，但端点域名属于「{h_vendor}」——"
                "厂商对不上，调用必然 401/403。",
                f"二选一：(A) 把 apiKey 换成「{h_vendor}」的 Key；"
                f"或 (B) 把 url 改为「{k_vendor}」的 Base URL：{k_base or VENDOR_BASE_URL.get(h_vendor, '')}。",
            ))

    # —— 规则 4：OpenCode Zen 免费层外部可用性 ——
    # 2026-10-09 修：models.json 条目通常没有 vendor 字段（实测本机 4 条全无），
    # 旧写法 `rep.vendor` 恒为空 → 规则永不触发，Zen 风险对用户完全不可见。
    # 改为 vendor 字段缺失时按 url 域名反推厂商。
    _vendor = (rep.vendor or "").strip() or (host_vendor(rep.url) or "")
    if "opencode zen" in _vendor.lower():
        # 2026-10-13 复测：9 个 -free 模型外部（含 WorkBuddy）调用全部 403（含原唯一可用节点
        # space-bunny-free），外部免费通道已归零，不再有任何外部可用节点。
        rep.add(Finding(
            "WARN", "OPENCODE_ZEN_FREETIER_RISK",
            "OpenCode Zen 免费层所有 -free 模型外部（含 WorkBuddy）调用均返回 403 FreeTierError"
            "（2026-10-13 带浏览器 UA 复测 9 个 -free，外部免费通道已归零，含原唯一可用节点 space-bunny-free）。",
            "无可用外部节点；建议改用 Groq / OpenRouter :free 等经实测可外部调用的渠道。",
        ))

    # —— 规则 5：能力标签与已知事实冲突（无法核实 → UNKNOWN，不臆断）——
    # 我们没有实时事实库，凡是 supports* 标签都无法自动确认，只在「其它都正常」时才提示未核实。
    caps = {k: raw.get(k) for k in
            ("supportsToolCall", "supportsImages", "supportsReasoning")}
    has_cap_fields = any(v is not None for v in caps.values())
    if has_cap_fields and rep.verdict in ("OK", "UNKNOWN"):
        # 仅在尚无更严重问题时，作为 UNKNOWN 提示
        if rep.verdict == "OK":
            rep.add(Finding(
                "UNKNOWN", "CAPABILITY_UNVERIFIED",
                "能力标签（推理/图像/工具调用）未在线核实，无法保证准确。",
                "请到厂商文档核对该模型真实能力，必要时修正 supports* 字段。",
            ))

    # —— 规则 3：在线探测（分层）——
    if do_probe and rep.url:
        base = strip_chat_completions(rep.url)
        p = probe_url(base)
        rep.probe = p
        if p.get("level") == "UNREACHABLE":
            rep.add(Finding(
                "UNREACHABLE", "NET_UNREACHABLE",
                p["detail"],
                "先确认本机能直连该域名（必要时开代理）；网络通了再排 Key/路径问题。",
            ))
        elif p.get("level") == "OK":
            # 网络通畅，作为正向证据（不单独成问题）
            rep.add(Finding(
                "OK", "NET_REACHABLE",
                f"在线探测可达：{p['detail']}",
                "网络层正常，问题若仍在，集中在 Key/路径/权限。",
            ))
        elif p.get("level") == "ERROR":
            rep.add(Finding(
                "ERROR", "NET_PROBE_ERROR",
                p["detail"],
                "url 非法，无法探测；请先修正 url。",
            ))

    # 没有任何发现 → 整体 OK（但能力未核实的 UNKNOWN 已在上文处理）
    if not rep.findings:
        rep.add(Finding(
            "OK", "NO_ISSUE",
            "静态检查未见明显问题。",
            "若仍调用失败，多为在线鉴权/权限问题，请用 --no-probe 之外的方式逐步排查。",
        ))

    return rep


# ─────────────────────────────────────────────────────────────────────────────
# 6. 定位 models.json
# ─────────────────────────────────────────────────────────────────────────────

def locate_models_path(cli_path: str | None) -> Path:
    """定位 models.json：--models-path 优先；否则 Windows %USERPROFILE% 或 Unix ~。"""
    if cli_path:
        return Path(cli_path).expanduser()
    candidates: list[Path] = []
    up = os.environ.get("USERPROFILE") or os.environ.get("HOME")
    if up:
        candidates.append(Path(up) / ".workbuddy" / "models.json")
    candidates.append(Path.home() / ".workbuddy" / "models.json")
    for c in candidates:
        if c.exists():
            return c
    # 都不存在：返回首选候选，供「文件缺失」报错使用
    return candidates[0]


# ─────────────────────────────────────────────────────────────────────────────
# 7. 文件级解析（规则 6）
# ─────────────────────────────────────────────────────────────────────────────

def load_models(path: Path) -> tuple[dict, list[dict] | None]:
    """返回 (file_status, records_or_None)。file_status: ok/missing/json_error/not_array。"""
    if not path.exists():
        return {"status": "missing", "path": str(path)}, None
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            text = path.read_text(encoding="gbk")
        except Exception:
            return {"status": "read_error", "path": str(path)}, None
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return {"status": "json_error", "path": str(path), "detail": str(e)}, None
    if not isinstance(data, list):
        return {"status": "not_array", "path": str(path)}, None
    return {"status": "ok", "path": str(path)}, data


# ─────────────────────────────────────────────────────────────────────────────
# 8. 安全修复（--fix-safe）
# ─────────────────────────────────────────────────────────────────────────────

def collect_safe_fixes(reports: list[ModelReport]) -> list[dict]:
    """收集绝对安全的修复：仅「去掉 url 末尾多余 /chat/completions」。"""
    fixes: list[dict] = []
    for r in reports:
        for f in r.findings:
            if f.safe_fix and f.safe_fix.get("field") == "url":
                fixes.append({
                    "id": r.id,
                    "name": r.name,
                    "field": "url",
                    "old": f.safe_fix["old"],
                    "new": f.safe_fix["new"],
                })
    # 去重（同一 id 可能多次命中）
    seen = set()
    uniq = []
    for fx in fixes:
        key = (fx["id"], fx["old"], fx["new"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(fx)
    return uniq


def apply_safe_fixes(path: Path, records: list[dict], fixes: list[dict]) -> None:
    """把安全修复写回 models.json：只改 url 字段，绝不碰 apiKey、绝不删记录。

    写入纪律（v1.0.16 加固）：
      ① 先备份成 `models.json.bak-YYYYmmdd-HHMMSS`，不覆盖历史备份；
      ② 先写临时文件再原子替换，避免写一半断电留下半截 JSON；
      ③ records 是**完整原始数组**（含用户的付费条目），本函数只做原地字段修改，
         不重建、不筛选、不丢弃任何条目。
    """
    by_id: dict[str, dict] = {}
    for rec in records:
        rid = rec.get("id") or rec.get("name")
        by_id[rid] = rec
    for fx in fixes:
        rec = by_id.get(fx["id"])
        if rec is not None:
            rec["url"] = fx["new"]

    if path.exists():
        stamp = datetime.now(TZ).strftime("%Y%m%d-%H%M%S")
        shutil.copy2(path, path.with_name(path.name + ".bak-" + stamp))

    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp, path)


# ─────────────────────────────────────────────────────────────────────────────
# 9. 输出渲染
# ─────────────────────────────────────────────────────────────────────────────

def render_markdown(path: Path, file_status: dict, reports: list[ModelReport],
                    fixes: list[dict], applied: bool) -> str:
    lines: list[str] = []
    lines.append("# 免费模型超市 · 排障报告（doctor）")
    lines.append("")
    lines.append(f"- 配置文件：`{file_status['path']}`")
    lines.append(f"- 生成时间：{datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S +08:00')}")
    lines.append(f"- 文件状态：{file_status['status']}")
    lines.append("")

    if file_status["status"] != "ok":
        lines.append("## ❌ 配置文件本身有问题，无法逐条诊断")
        lines.append("")
        if file_status["status"] == "missing":
            lines.append(f"找不到文件 `{file_status['path']}`。")
            lines.append("")
            lines.append("**你该做什么**：")
            lines.append("1. 在 WorkBuddy 设置里添加至少一个自定义模型，让它生成该文件；")
            lines.append("2. 或确认路径——Windows 在 `C:\\\\Users\\\\你的用户名\\\\.workbuddy\\\\models.json`。")
        elif file_status["status"] == "json_error":
            lines.append(f"JSON 格式错误：{file_status.get('detail', '')}")
            lines.append("")
            lines.append("**你该做什么**：用 JSON 校验工具（如 https://json.cn）检查并修复语法错误，")
            lines.append("常见原因：末尾多逗号、引号没闭合、用了中文引号。")
        elif file_status["status"] == "not_array":
            lines.append("文件顶层不是 JSON 数组（应该是 `[ ... ]` 包起来的多条模型记录）。")
            lines.append("")
            lines.append("**你该做什么**：把内容改成 `[ {模型1}, {模型2} ]` 形式。")
        lines.append("")
        return "\n".join(lines)

    # 空配置：明确说「还没配」，绝不给「全部检查通过」的假安慰
    # （2026-10-09 修：旧版空数组走 human_items 为空分支，输出
    #  「全部检查通过」，让刚装上 Skill 的用户误以为已就绪）
    if not reports:
        lines.append("## ⚠️ 还没配任何模型（配置为空）")
        lines.append("")
        lines.append("配置文件存在，但里面一条模型记录都没有。这不是「检查通过」，而是「尚未开始配置」。")
        lines.append("")
        lines.append("**你该做什么**（选一条路）：")
        lines.append("")
        lines.append("1. **零配置、免注册** → 让我跑注入器（我代执行，你不用碰终端）：")
        lines.append("   `python scripts/inject_workbuddy.py --apply --yes`，然后刷新模型选择器。")
        lines.append("  OpenCode Zen 外部免费通道已归零（2026-10-13 复测 9 个 -free 全部 403，含 space-bunny-free）；零配置直用当前不可用，请走路线 2（Groq）或路线 3（OpenRouter :free）。")
        lines.append("2. **要更多模型 / 更快速度** → 注册 Groq（30 秒、免绑卡），在 WorkBuddy")
        lines.append("   模型选择器点「配置自定义模型」填 4 个字段。细节问我，我逐屏给你指引。")
        lines.append("3. **只想查额度、做选型** → 直接问「推荐免费模型」，本 Skill 可零配置咨询。")
        lines.append("")
        return "\n".join(lines)

    # 主表
    lines.append("## 逐条诊断")
    lines.append("")
    lines.append("| 模型 | 判定 | 问题 | 修复动作 |")
    lines.append("| --- | --- | --- | --- |")
    for r in reports:
        problems = "；".join(f"[{f.level}] {f.message}" for f in r.findings
                             if f.level not in ("OK",))
        if not problems:
            problems = "未见明显问题"
        actions = "；".join(f.fix for f in r.findings if f.level not in ("OK",))
        if not actions:
            actions = "无需处理"
        lines.append(
            f"| {r.id} | **{r.verdict}** | {problems} | {actions} |"
        )
    lines.append("")

    # 安全修复预览
    if fixes:
        lines.append("## 🔧 可安全自动修复的项（--fix-safe）")
        lines.append("")
        lines.append("| 模型 | 字段 | 原值 | 将改为 |")
        lines.append("| --- | --- | --- | --- |")
        for fx in fixes:
            lines.append(f"| {fx['id']} | url | `{fx['old']}` | `{fx['new']}` |")
        lines.append("")
        if applied:
            lines.append("✅ 已按上述改动写回 models.json（仅改 url，未动 apiKey、未删记录）。")
        else:
            lines.append("⚠️ 以上为**预览**，未落盘。确认无误后加 `--yes` 才会真正写入：")
            lines.append("`python 免费模型超市-doctor.py --fix-safe --yes`")
        lines.append("")

    # 总结：需要人工介入的项
    lines.append("## 📌 需要人工介入的项 & 下一步")
    lines.append("")
    human_items: list[tuple[str, str, str]] = []  # (id, issue, next_step)
    for r in reports:
        for f in r.findings:
            if f.level in ("MISMATCH", "ERROR", "UNREACHABLE", "WARN", "UNKNOWN"):
                human_items.append((r.id, f"[{f.level}] {f.message}", f.fix))

    if not human_items:
        lines.append("✅ 全部检查通过，未发现需要人工处理的项。")
    else:
        for i, (mid, issue, step) in enumerate(human_items, 1):
            lines.append(f"{i}. **{mid}** — {issue}")
            lines.append(f"   👉 你该做：{step}")
            lines.append("")
    return "\n".join(lines)


def build_summary(reports: list[ModelReport], fixes: list[dict], applied: bool) -> dict:
    human: list[dict] = []
    for r in reports:
        for f in r.findings:
            if f.level in ("MISMATCH", "ERROR", "UNREACHABLE", "WARN", "UNKNOWN"):
                human.append({
                    "id": r.id,
                    "issue": f"[{f.level}] {f.message}",
                    "next_step": f.fix,
                })
    counts = {}
    for r in reports:
        counts[r.verdict] = counts.get(r.verdict, 0) + 1
    return {
        "human_intervention": human,
        "counts": counts,
        "safe_fixes": fixes,
        "applied": applied,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 10. 主流程
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="免费模型超市 · 智能排障引擎（doctor）",
    )
    parser.add_argument("--json", action="store_true", help="JSON 输出（供 AI 消费）")
    parser.add_argument("--fix-safe", action="store_true",
                        help="预览/执行绝对安全的修复（仅改 url 末尾 /chat/completions）")
    parser.add_argument("--yes", action="store_true",
                        help="与 --fix-safe 配合，确认写回 models.json")
    parser.add_argument("--models-path", default=None,
                        help="指定其它 models.json（测试用，不依赖 cwd）")
    parser.add_argument("--no-probe", action="store_true",
                        help="跳过在线探测，仅做本地静态分析")
    args = parser.parse_args()

    do_probe = not args.no_probe
    path = locate_models_path(args.models_path)
    file_status, records = load_models(path)

    out: dict = {
        "tool": "免费模型超市-doctor",
        "generated_at": datetime.now(TZ).strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "models_path": str(path),
        "file_status": file_status["status"],
    }

    # 文件级错误：直接出报告
    if file_status["status"] != "ok":
        if args.json:
            out["error_detail"] = file_status.get("detail")
            out["reports"] = []
            out["summary"] = build_summary([], [], False)
            print(json.dumps(out, ensure_ascii=False, indent=2))
        else:
            print(render_markdown(path, file_status, [], [], False))
        return

    # 逐条诊断
    reports = [diagnose_model(rec, i, do_probe) for i, rec in enumerate(records)]

    # 空配置：单独标记，别让「0 条报告」被读成「全部检查通过」
    if not records:
        out["setup_pending"] = True
        out["setup_hint"] = (
            "配置文件为空数组：尚未配置任何模型，不是「检查通过」。"
            "零配置路线 = scripts/inject_workbuddy.py --apply --yes（2026-10-13 复测 Zen 外部通道已归零，注入器默认不注入任何 Zen 模型）；"
            "多模型路线 = 注册 Groq 后在 WorkBuddy 模型选择器填自定义模型。"
        )

    # 规则 6：重复 id
    seen: dict[str, int] = {}
    for r in reports:
        key = r.id
        seen[key] = seen.get(key, 0) + 1
    for r in reports:
        if seen[r.id] > 1:
            r.add(Finding(
                "ERROR", "DUPLICATE_ID",
                f"id「{r.id}」出现 {seen[r.id]} 次，重复会导致 WorkBuddy 只认其中一条。",
                "把重复的模型改成不同的 id（如加后缀 -2），或删除多余的一条。",
            ))

    # 安全修复
    fixes = collect_safe_fixes(reports)
    applied = False
    if args.fix_safe:
        if args.yes and fixes:
            apply_safe_fixes(path, records, fixes)
            applied = True
        # 注意：--fix-safe 不传 --yes 时只预览，绝不落盘

    summary = build_summary(reports, fixes, applied)

    if args.json:
        out["reports"] = [r.to_dict() for r in reports]
        out["safe_fixes"] = fixes
        out["applied"] = applied
        out["summary"] = summary
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        md = render_markdown(path, file_status, reports, fixes, applied)
        print(md)


if __name__ == "__main__":
    main()
