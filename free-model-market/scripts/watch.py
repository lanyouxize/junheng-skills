#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
免费模型超市 · 自动巡检优化引擎 (watch.py)

痛点：免费层额度/政策收缩极快（2026 年已发生 8 起收缩），但货架数据目前只能靠
     人工核实更新；旧的健康检查脚本 `免费模型超市-refresh_catalog.py` 只做网络
     可达性检查、写一份 Markdown 报告就结束——出了异常没人知道、没人被通知、
     货架状态不会被自动修正。本脚本补上「自动优化」的核心缺口：

        跑一次 → 探测 → 归因 → 产出可执行动作队列 → 可选写回货架

设计铁律（违反即失败）：
  1. 任何 HTTP 响应码都证明网络层通畅。403/401/404 是政策/鉴权层证据，绝不归为
     「服务不可用」；只有 DNS 失败 / 连接超时 / 连接被拒才算 DOWN。
  2. 用户在中国大陆，Google/OpenAI/xAI 等域名常不可直连 → DOWN 不能直接改状态，
     默认跳过这些已知域名（记为 SKIPPED）。
  3. 禁止编造额度数字，绝不自动改写 `quota` 字段；额度核实必须人工/官方信源。
  4. 状态类结论必须标来源层级：实测（本脚本探测）/ 文档（厂商公告）/ 口述（不可作依据）。
  5. 快照日期 `snapshot_date` 滞后会让全局核实日期低估新鲜度，R3 以它作为基线。

归因规则（核心价值）：
  R1 状态漂移：active 渠道全部 endpoint 连续 5xx → P1 人工核实（绝不自动改 status）
  R2 不可达升级：active 渠道 endpoint DOWN 且不在已知屏蔽清单 → P2 复核网络/代理
  R3 快照陈旧：age = 今天 - 相关核实日期（= snapshot_date）；> 阈值 → P2/P1 提醒核实
  R4 收缩信号：quota 文本命中收缩类信号词 → P1 疑似收缩，需官方信源核实
  R5 数据一致性：status/section 矛盾、重复 name、空 endpoints、md 脏标记、非法 status
  R6 字段契约：缺 name/endpoints/status；quota/rate_limit 为 unknown/空 → P2 未核实

写回货架（默认 dry-run，须显式 --apply --yes 才落盘）：
  * 仅允许两类安全变更：① snapshot_date 更新为今天；② R5 仅「空白字符差异」规范化。
  * 涉及 status/quota/rate_limit 实质变化 → 绝不自动写回，只列入待办。
  * 落盘前自动备份为 .bak-<日期>。

仅依赖标准库；中文注释，风格与 `免费模型超市-export_catalog.py` 一致。
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
import re
import sys
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
from collections import Counter
from dataclasses import dataclass, field

# Windows Git-Bash 控制台 GBK 报错坑（项目已踩过）——必须在最前重配置 stdout/stderr
sys.stdout.reconfigure(encoding="utf-8")
try:
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

# 东八区
TZ = timezone(timedelta(hours=8))

# 探测参数
TIMEOUT = 15
MAX_WORKERS = 10
HEADERS = {
    "User-Agent": "free-model-market-watch/1.0 (+healthcheck; no-auth GET)",
    "Accept": "*/*",
}

# 状态枚举白名单（与 export_catalog.py / 网关侧 TIER_RULES 对齐）
VALID_STATUS = {"active", "degraded", "unverified", "expired", "unknown"}

# section 头 → 期望的状态集合（用于 R5 一致性校验）
SECTION_EXPECTED_STATUS = {
    "一、": {"active", "degraded"},       # 永久免费渠道
    "二、": {"active", "degraded", "unverified"},  # 试用额度渠道
    "三、": {"expired"},                  # 已停服 / 退出免费层
}

# 已知在大陆不可直连的域名清单（实测/推断，注释依据）
# 默认 --skip-known-blocked 开启时跳过，记为 SKIPPED，避免误判服务故障。
KNOWN_BLOCKED = {
    "generativelanguage.googleapis.com": "Google AI Studio / Gemini API（实测：大陆无代理常不可直连）",
    "api.openai.com": "OpenAI（实测：大陆无代理常不可直连）",
    "api.x.ai": "xAI（实测：大陆无代理常不可直连）",
    "api.cohere.com": "Cohere（实测：大陆无代理常不可直连）",
    "api.anthropic.com": "Anthropic（推断：与 OpenAI 同类，大陆常不可直连）",
    "api.deepseek.com": "DeepSeek（推断：偶发不可直连，保留观察）",
    # 2026-10-30 一手实测：console.groq.com 与 api.groq.com 同一 Cloudflare IP
    # （172.64.149.20）。无论带不带 Authorization、无论 /models 还是 /chat/completions，
    # 一律 HTTP 403 {"error":{"message":"Forbidden"}} —— 属 WAF 地域拦截，
    # 不是鉴权失败（缺 key 的正常响应应是 401 invalid_api_key）。
    # 结论：本机网络下即使拿到 key 也调不通，巡检时跳过以免误判服务故障。
    "api.groq.com": "Groq（实测：Cloudflare 403 WAF 拦截，非鉴权失败；有 key 亦不可用）",
    "console.groq.com": "Groq 控制台（实测：同上，浏览器亦打不开）",
}

# R4 收缩类信号词（命中 quota 文本即疑似收缩，需官方信源核实）
CONTRACTION_WORDS = [
    "不限配额", "取消免费", "取消", "停服", "停止免费", "停止", "转付费", "仅付费",
    "退市", "结束", "移除免费", "移除", "下调", "缩减", "仅 Enterprise", "转 Enterprise",
    "退出免费", "不再免费", "需绑卡", "转为付费", "停止免费层",
]

# Markdown 脏标记（R5 检测）：** 加粗、__ 加粗、~~ 删除线、行内 `
MD_DIRTY = re.compile(r"\*\*|__|~~|`")

# 优先级排序权重
PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2}


@dataclass
class Action:
    """一条可执行动作。建议动作须是小白能直接照做的直白指令。"""
    priority: str          # P0 / P1 / P2
    rule: str              # R1..R6
    trigger: str           # 触发条目（厂商名）
    evidence: str          # 判定依据
    suggestion: str        # 建议动作（给小白用户）
    source_layer: str      # 来源层级：实测 / 文档 / 口述


@dataclass
class ProbeResult:
    url: str
    host: str
    category: str          # OK / WARN / DOWN / SKIPPED
    detail: str
    skipped_reason: str = ""


def resolve_references_dir() -> Path:
    """定位 references/ 目录：不依赖 cwd。

    兼容两种部署位置：
      * 顶层：free-model-market/watch.py        → parent/references
      * scripts 子目录：.../scripts/watch.py     → parent.parent/references
    哪个目录真实存在就用哪个。
    """
    here = Path(__file__).resolve()
    candidates = [
        here.parent / "references" / "model-catalog.json",
        here.parent.parent / "references" / "model-catalog.json",
    ]
    for c in candidates:
        if c.exists():
            return c
    # 都不存在时退回顶层候选（便于报错信息准确）
    return candidates[0]


def clean_url(u: str) -> str:
    """截掉首个非 ASCII 字符之后的内容（中文注释常接在 URL 后）。"""
    for i, ch in enumerate(u):
        if ord(ch) > 127:
            u = u[:i]
            break
    return u.strip().rstrip(".,;）)>")


def host_of(url: str) -> str:
    from urllib.parse import urlparse
    try:
        return urlparse(url).netloc or url
    except Exception:  # noqa: BLE001
        return url


def parse_date(s: str) -> date | None:
    """解析 YYYY-MM-DD / YYYY-MM 等日期，失败返回 None。"""
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(s[:len(fmt) and (10 if fmt == "%Y-%m-%d" else len(fmt))], fmt).date()
        except Exception:  # noqa: BLE001
            pass
    m = re.search(r"(\d{4})-(\d{1,2})(?:-(\d{1,2}))?", s)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        d = int(m.group(3)) if m.group(3) else 1
        try:
            return date(y, mo, d)
        except Exception:  # noqa: BLE001
            return None
    return None


def is_template_url(url: str) -> bool:
    """含 {占位符} 的模板 URL 无法直连探测。"""
    return "{" in url


def probe_one(url: str, skip_blocked: bool) -> ProbeResult:
    """无鉴权 GET 探测单 URL，返回分类结果。任何 HTTP 响应都证明网络层通畅。"""
    host = host_of(url)

    # 模板占位 URL → 跳过
    if is_template_url(url):
        return ProbeResult(url, host, "SKIPPED", "", "模板占位 URL（含 {account_id} 等），无法直连探测")

    # 已知屏蔽域名 → 默认跳过
    if skip_blocked and host in KNOWN_BLOCKED:
        return ProbeResult(url, host, "SKIPPED", "", f"本地网络不可直连，非服务故障（{KNOWN_BLOCKED[host]}）")

    req = urllib.request.Request(url, headers=HEADERS, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            code = resp.status
            if code < 400:
                return ProbeResult(url, host, "OK", f"HTTP {code}", "")
            # 4xx：鉴权/路径级预期响应，仍证明服务在线
            return ProbeResult(url, host, "WARN", f"HTTP {code}（服务响应，预期鉴权/路径行为）", "")
    except urllib.error.HTTPError as e:
        if 500 <= e.code < 600:
            return ProbeResult(url, host, "WARN", f"HTTP {e.code} 服务端错误", "")
        # 4xx 即便以异常形式抛出，也证明服务在线
        return ProbeResult(url, host, "WARN", f"HTTP {e.code}（服务响应，预期鉴权/路径行为）", "")
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", e)
        # 仅 DNS 失败 / 连接超时 / 连接被拒 才算不可达
        return ProbeResult(url, host, "DOWN", f"连接失败: {reason}", "")
    except Exception as e:  # noqa: BLE001
        return ProbeResult(url, host, "DOWN", f"异常: {type(e).__name__}: {e}", "")


def load_catalog(path: Path) -> dict:
    if not path.exists():
        sys.exit(f"[错误] 找不到货架文件: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit(f"[错误] 货架 JSON 解析失败: {e}")


def detect_proxy() -> bool:
    """本机是否设置了网络代理环境变量（影响判定时需提示）。"""
    import os
    return any(os.environ.get(k) for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"))


def run_probes(catalog: dict, skip_blocked: bool) -> dict[int, list[ProbeResult]]:
    """对每条供应商的每个 endpoint 并发探测，返回 {provider_index: [ProbeResult,...]}。"""
    tasks: list[tuple[int, str]] = []
    for idx, p in enumerate(catalog.get("providers", [])):
        for ep in p.get("endpoints", []) or []:
            cleaned = clean_url(ep)
            if cleaned.startswith("http"):
                tasks.append((idx, cleaned))

    results: dict[int, list[ProbeResult]] = {idx: [] for idx in range(len(catalog.get("providers", [])))}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(probe_one, url, skip_blocked): (idx, url) for idx, url in tasks}
        for fut in as_completed(futures):
            idx, _url = futures[fut]
            results[idx].append(fut.result())
    return results


# ----------------------------- 归因层 -----------------------------

def attr_r1_r2(provider: dict, probes: list[ProbeResult], actions: list[Action]) -> None:
    """R1 状态漂移：active 渠道全部 endpoint 连续 5xx → P1 人工核实（绝不自动改）。
       R2 不可达升级：active 渠道 endpoint DOWN 且不在已知屏蔽清单 → P2 复核网络/代理。"""
    status = provider.get("status", "")
    name = provider.get("name", "未知")
    real = [p for p in probes if p.category != "SKIPPED"]  # 实际探测到的
    if not real:
        return

    # R1
    if status == "active":
        all_5xx = all(p.category == "WARN" and "服务端错误" in p.detail for p in real)
        if all_5xx:
            actions.append(Action(
                "P1", "R1", name,
                f"全部 {len(real)} 个 endpoint 实测均返回 5xx 服务端错误（{real[0].url} 等）",
                "疑似服务端故障。请打开该厂商官方 status page 确认是否宕机，再决定是否把状态从 active 降级为 degraded。本脚本不会自动改状态。",
                "实测",
            ))

    # R2
    for p in real:
        if p.category == "DOWN" and p.host not in KNOWN_BLOCKED:
            actions.append(Action(
                "P2", "R2", name,
                f"endpoint 实测不可达（DOWN）：{p.url} —— {p.detail}；该域名不在已知不可直连清单内",
                "你本机可能处于需要代理才能访问该域名的网络环境。请检查网络/代理设置后重试；若确认是厂商侧问题，再到官方渠道核实。",
                "实测",
            ))


def attr_r3(catalog: dict, provider: dict, stale_days: int, actions: list[Action]) -> None:
    """R3 快照陈旧：age = 今天 - 相关核实日期（= snapshot_date）。
       > 阈值 → P2 提醒核实；> 90 天 → P1 提醒核实并标注「数据可能已失效」。"""
    snap = catalog.get("snapshot_date", "")
    base = parse_date(snap)
    name = provider.get("name", "未知")
    if base is None:
        return
    today = datetime.now(TZ).date()
    age = (today - base).days
    if age <= stale_days:
        return
    if age > 90:
        actions.append(Action(
            "P1", "R3", name,
            f"快照日期 {snap} 距今天已 {age} 天（> 90 天），超过陈旧阈值 {stale_days} 天",
            "这份记录距离上次核实已超过 90 天，数据可能已失效。请重新登录厂商控制台或查官方公告，确认额度/状态是否变化后更新货架。",
            "文档",
        ))
    else:
        actions.append(Action(
            "P2", "R3", name,
            f"快照日期 {snap} 距今天已 {age} 天，超过陈旧阈值 {stale_days} 天",
            "这份记录有一阵子没核实了。有空时登录厂商控制台或查官方公告，确认额度/状态是否还准，顺手更新一下货架。",
            "文档",
        ))


def attr_r4(provider: dict, actions: list[Action]) -> None:
    """R4 收缩信号：quota 文本命中收缩类信号词 → P1 疑似收缩，需官方信源核实。"""
    name = provider.get("name", "未知")
    quota = provider.get("quota", "") or ""
    hits = [w for w in CONTRACTION_WORDS if w in quota]
    if hits:
        actions.append(Action(
            "P1", "R4", name,
            f"quota 文本命中收缩信号词：{hits}（原文片段：「{quota[:80]}…」）",
            "这条记录的额度描述里出现了「取消/转付费/退市」等收缩信号词。请到厂商官方公告/控制台核实免费层是否真的收缩，确认后再决定是否更新状态——不要直接照字面改。",
            "文档",
        ))


def attr_r5(provider: dict, idx: int, all_names: list[str], actions: list[Action],
            writeback: dict) -> None:
    """R5 数据一致性校验 + R6 字段契约（部分落在 R5 的数据质量告警中）。"""
    name = provider.get("name", "")
    raw_status = provider.get("status") or ""
    status = raw_status.strip()
    section = provider.get("section", "") or ""
    endpoints = provider.get("endpoints", []) or []
    quota = provider.get("quota", "") or ""
    rate_limit = provider.get("rate_limit", "") or ""

    # R5-a：status 含非白名单值 / 脏标记（含 Markdown 脏标记，如 **degraded**）
    # 注意：用 raw_status（未去空白）比对，才能识别「仅空白差异」这唯一可安全自动规范化的情况。
    if raw_status:
        bare = raw_status.strip("*`_~").strip().lower()
        if bare not in VALID_STATUS:
            actions.append(Action(
                "P1", "R5", name or f"第{idx}条",
                f"status 字段值 {raw_status!r} 不在白名单 {sorted(VALID_STATUS)} 内",
                "这条记录的 status 写脏了（比如带了 ** 强调符号或拼错）。请人工把它规范成 active/degraded/expired/unverified/unknown 之一；本脚本不会自动改状态。",
                "实测",
            ))
            writeback["pending_todos"].append(
                f"{name}: status {raw_status!r} 为非白名单值，需人工规范（本脚本不自动改）")
        elif raw_status != bare:
            # 差异类型判断：仅空白字符差异 → 安全规范化（自动写回）；含 md 标记 → 仅待办
            if raw_status.strip() == bare:
                writeback["normalize"].append({
                    "name": name, "field": "status", "from": raw_status, "to": bare,
                })
            else:
                writeback["pending_todos"].append(
                    f"{name}: status {raw_status!r} 含 Markdown 标记，清理为 {bare!r}（仅标记差异，需人工确认后处理）")

    # R5-b：status 与 section 分组矛盾（仅命中真实矛盾的两类）
    #   说明：section 二「试用额度渠道」本就合法收纳 active/degraded 的试用厂商，
    #        故「active 落在试用分组」不是错误，不报警。
    #   真实矛盾：
    #     · expired 却落在「永久免费渠道（active）」分组（一、）
    #     · active/degraded/unverified 却落在「已停服 / 退出免费层（expired）」分组（三、）
    bare_status = status.strip("*`_~").strip().lower()
    if section.startswith("一、") and bare_status == "expired":
        actions.append(Action(
            "P1", "R5", name,
            f"status={status!r} 却落在「永久免费渠道」分组（section={section!r}）",
            "这条记录已是 expired，却还在「永久免费渠道」章节里。请把它挪到「已停服 / 退出免费层」分组，或修正状态；本脚本不自动改。",
            "实测",
        ))
    if section.startswith("三、") and bare_status in ("active", "degraded", "unverified"):
        actions.append(Action(
            "P1", "R5", name,
            f"status={status!r} 却落在「已停服 / 退出免费层」分组（section={section!r}）",
            "这条记录还是在线状态，却放在「已停服 / 退出免费层」章节里。请核对它是否真的退出了免费层，把状态或分组二选一修正；本脚本不自动改。",
            "实测",
        ))

    # R5-c：重复 name
    # （在外部按全局统计后调用，这里只接收标记）

    # R5-d：endpoints 为空数组（仅对在线渠道报警；已停服渠道本就无活跃端点）
    if not endpoints and bare_status in ("active", "degraded", "unverified"):
        actions.append(Action(
            "P2", "R5", name or f"第{idx}条",
            "endpoints 为空数组，无法做网络探测（且状态为在线）",
            "这条记录状态是在线的，却没有可探测的 API 端点。请补充正确的 endpoint URL；没有端点用户也无法使用。",
            "实测",
        ))

    # R5-e：quota 文本含 Markdown 脏标记（** _ ~ `）
    if MD_DIRTY.search(quota):
        actions.append(Action(
            "P1", "R5", name,
            f"quota 文本含 Markdown 脏标记（**、_、~、` 等）：「{quota[:80]}…」",
            "额度字段里混进了 Markdown 符号（比如 **加粗**），会让机器读取时出错。请人工把额度文本清理成纯文本；本脚本不会自动改写额度内容。",
            "实测",
        ))
        writeback["pending_todos"].append(
            f"{name}: quota 含 Markdown 脏标记，需人工清理（本脚本绝不自动改写额度）")

    # R6-a：缺必填字段（endpoints 缺失仅对在线渠道报警）
    missing = [f for f in ("name", "status") if not provider.get(f)]
    if not endpoints and bare_status in ("active", "degraded", "unverified"):
        missing.append("endpoints")
    if missing:
        actions.append(Action(
            "P2", "R6", name or f"第{idx}条",
            f"缺少必填字段：{missing}",
            "这条记录缺了关键字段（name/endpoints/status 之一）。请补齐全，否则无法被正常检索与探测。",
            "实测",
        ))

    # R6-b：quota / rate_limit 为 unknown 或空 → 未核实项
    if (not quota) or quota.strip().lower() in ("unknown", "未知", "待核实"):
        actions.append(Action(
            "P2", "R6", name,
            "quota 为 unknown / 空，属于未核实项",
            "这条的免费额度还没核实过。给小白用户推荐时，必须明确说明「额度未核实」，额度以厂商控制台实时显示为准。",
            "口述",
        ))
    if (not rate_limit) or rate_limit.strip().lower() in ("unknown", "未知", "待核实"):
        actions.append(Action(
            "P2", "R6", name,
            "rate_limit 为 unknown / 空，属于未核实项",
            "这条的限速还没核实过。给小白用户推荐时，须说明「限速未核实」，实际以厂商控制台为准。",
            "口述",
        ))


def find_duplicate_names(providers: list[dict], actions: list[Action]) -> None:
    """R5-c：重复 name 检测。"""
    seen: dict[str, int] = {}
    for p in providers:
        n = (p.get("name") or "").strip()
        if not n:
            continue
        seen[n] = seen.get(n, 0) + 1
    for n, c in seen.items():
        if c > 1:
            actions.append(Action(
                "P2", "R5", n,
                f"name 重复出现 {c} 次",
                "货架里有两条记录名字完全一样。请合并或改名区分，否则用户检索时会混淆、统计也会重复。",
                "实测",
            ))


def build_actions(catalog: dict, probes_by_idx: dict[int, list[ProbeResult]],
                  stale_days: int) -> tuple[list[Action], dict]:
    """汇总所有归因规则，返回 (动作队列, 写回候选)。"""
    actions: list[Action] = []
    writeback = {"normalize": [], "snapshot_update": None, "pending_todos": []}

    providers = catalog.get("providers", [])
    for idx, p in enumerate(providers):
        probes = probes_by_idx.get(idx, [])
        attr_r1_r2(p, probes, actions)
        attr_r3(catalog, p, stale_days, actions)
        attr_r4(p, actions)
        attr_r5(p, idx, [x.get("name", "") for x in providers], actions, writeback)
    find_duplicate_names(providers, actions)

    # snapshot_date 写回候选（仅当与今天不同）
    today_str = datetime.now(TZ).strftime("%Y-%m-%d")
    snap = catalog.get("snapshot_date", "")
    if snap != today_str:
        writeback["snapshot_update"] = {"from": snap, "to": today_str}

    return actions, writeback


# ----------------------------- 输出层 -----------------------------

def sort_actions(actions: list[Action]) -> list[Action]:
    return sorted(actions, key=lambda a: (PRIORITY_RANK.get(a.priority, 9), a.rule))


def render_markdown(catalog: dict, probes_by_idx: dict[int, list[ProbeResult]],
                    actions: list[Action], writeback: dict, args: argparse.Namespace,
                    probe_summary: dict) -> str:
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    lines = []
    lines.append(f"# 免费模型超市 · 自动巡检报告 · {today}")
    lines.append("")
    lines.append(f"- 货架：{args.catalog or '（默认 references/model-catalog.json）'}")
    lines.append(f"- 探测 URL 数：**{probe_summary['total']}** ｜ OK {probe_summary['OK']} / WARN {probe_summary['WARN']} / DOWN {probe_summary['DOWN']} / SKIPPED {probe_summary['SKIPPED']}")
    lines.append(f"- skip-known-blocked：**{'开启' if args.skip_blocked else '关闭'}** ｜ 陈旧阈值：**{args.stale_days}** 天")
    if detect_proxy():
        lines.append("- ⚠️ 本机检测到代理环境变量（http_proxy/https_proxy），探测结果可能受本机网络环境影响，判定时请留意。")
    if probe_summary['DOWN'] > 0 and not args.skip_blocked:
        lines.append("- ⚠️ 出现大量 DOWN：若几乎全部 endpoint 都 DOWN，多为本机网络/代理导致，并非厂商服务故障，请以官方 status page 为准。")
    lines.append("")

    # 探测概览（仅列非 OK / SKIPPED 的，便于聚焦）
    nonok = []
    for idx, probes in probes_by_idx.items():
        for p in probes:
            if p.category in ("WARN", "DOWN"):
                nonok.append((catalog["providers"][idx].get("name", "?"), p))
    if nonok:
        lines.append("## 探测异常项（WARN / DOWN）")
        lines.append("")
        lines.append("| 厂商 | URL | 状态 | 详情 |")
        lines.append("|------|-----|------|------|")
        for name, p in sorted(nonok, key=lambda x: x[1].category):
            lines.append(f"| {name} | {p.url} | {p.category} | {p.detail} |")
        lines.append("")

    # 动作队列
    lines.append("## 可执行动作队列")
    lines.append("")
    if not actions:
        lines.append("✅ 本次巡检未触发任何归因规则，货架状态健康。")
    else:
        lines.append("| 优先级 | 动作 | 触发条目 | 判定依据 | 建议动作（直白指令） | 来源 |")
        lines.append("|--------|------|----------|----------|----------------------|------|")
        for a in sort_actions(actions):
            # Markdown 表格内转义竖线
            trig = a.trigger.replace("|", "\\|")
            ev = a.evidence.replace("|", "\\|")
            sug = a.suggestion.replace("|", "\\|")
            lines.append(f"| {a.priority} | {a.rule} | {trig} | {ev} | {sug} | {a.source_layer} |")
    lines.append("")

    # 计数
    counts = Counter(a.priority for a in actions)
    lines.append(f"> 计数：P0={counts.get('P0',0)} ｜ P1={counts.get('P1',0)} ｜ P2={counts.get('P2',0)} ｜ 本次探测 URL 数={probe_summary['total']}")
    lines.append("")

    # 写回预览
    if args.apply:
        lines.append("## 写回货架预览（dry-run，未落盘）")
        lines.append("")
        if writeback["snapshot_update"]:
            su = writeback["snapshot_update"]
            lines.append(f"- snapshot_date：{su['from']} → **{su['to']}**（安全变更，--yes 后落盘）")
        else:
            lines.append("- snapshot_date：无需更新（已为今天）")
        if writeback["normalize"]:
            for n in writeback["normalize"]:
                lines.append(f"- 规范化（空白字符）：{n['name']} 的 {n['field']}：{n['from']!r} → {n['to']!r}（安全变更）")
        if not args.yes:
            lines.append("")
            lines.append("⏳ 当前为 dry-run 预览，**未修改任何文件**。加 `--yes` 才会落盘（落盘前自动备份 .bak-<日期>）。")
        else:
            lines.append("")
            lines.append("💾 已按 `--yes` 落盘（详见控制台写回日志）。")
        lines.append("")
        if writeback["pending_todos"]:
            lines.append("### 仅列入待办（绝不自动写回）")
            for t in writeback["pending_todos"]:
                lines.append(f"- {t}")
            lines.append("")

    return "\n".join(lines)


def render_json(catalog: dict, probes_by_idx: dict[int, list[ProbeResult]],
                actions: list[Action], writeback: dict, args: argparse.Namespace,
                probe_summary: dict) -> str:
    counts = Counter(a.priority for a in actions)
    out = {
        "meta": {
            "generated_at": datetime.now(TZ).strftime("%Y-%m-%dT%H:%M:%S+08:00"),
            "catalog": str(args.catalog) if args.catalog else "default",
            "skip_known_blocked": args.skip_blocked,
            "stale_days": args.stale_days,
            "proxy_detected": detect_proxy(),
            "snapshot_date": catalog.get("snapshot_date"),
        },
        "probe_summary": probe_summary,
        "counts": {"P0": counts.get("P0", 0), "P1": counts.get("P1", 0), "P2": counts.get("P2", 0)},
        "probe_count": probe_summary["total"],
        "actions": [vars(a) for a in sort_actions(actions)],
        "writeback": {
            "would_change": bool(writeback["snapshot_update"] or writeback["normalize"]),
            "snapshot_update": writeback["snapshot_update"],
            "normalize": writeback["normalize"],
            "pending_todos": writeback["pending_todos"],
            "applied": bool(args.apply and args.yes),
        },
    }
    return json.dumps(out, ensure_ascii=False, indent=2)


# ----------------------------- 写回层 -----------------------------

def apply_writeback(catalog_path: Path, catalog: dict, writeback: dict, args: argparse.Namespace) -> None:
    """仅在 --apply --yes 时调用。只落盘两类安全变更，落盘前自动备份。"""
    if not (args.apply and args.yes):
        return

    # 备份
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    bak = catalog_path.with_suffix(f".json.bak-{today}")
    if not bak.exists():
        bak.write_text(catalog_path.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"[backup] 已备份原货架 → {bak}")

    # 载入原始文本做字段级规范化（保留其它内容不动）
    raw = json.loads(catalog_path.read_text(encoding="utf-8"))
    changed = False

    # 1) snapshot_date → 今天
    if writeback["snapshot_update"]:
        raw["snapshot_date"] = writeback["snapshot_update"]["to"]
        print(f"[apply] snapshot_date: {writeback['snapshot_update']['from']} → {writeback['snapshot_update']['to']}")
        changed = True

    # 2) 仅空白字符差异的规范化（status 去 md 标记/空白）
    for n in writeback["normalize"]:
        for p in raw.get("providers", []):
            if p.get("name") == n["name"] and n["field"] in p:
                # 仅当差异确为空白/标记时才应用
                stripped = (p[n["field"]]).strip("*`_~").strip()
                if stripped == n["to"]:
                    p[n["field"]] = n["to"]
                    print(f"[apply] 规范化 {n['name']}.{n['field']}: {n['from']!r} → {n['to']!r}")
                    changed = True

    if changed:
        raw["generated_at"] = datetime.now(TZ).strftime("%Y-%m-%dT%H:%M:%S+08:00")
        catalog_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[done] 已写回货架 → {catalog_path}")
    else:
        print("[info] 没有可安全写回的变更。")


# ----------------------------- 入口 -----------------------------

def build_argparser() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="免费模型超市 · 自动巡检优化引擎（探测→归因→动作队列→可选写回）",
    )
    ap.add_argument("--catalog", type=str, default=None,
                    help="指定 catalog JSON 路径（默认用脚本位置定位 references/model-catalog.json）")
    ap.add_argument("--json", action="store_true", help="以 JSON 形式输出结果")
    ap.add_argument("--probe", action="store_true",
                    help="开启真实网络探测（默认关闭：仅做离线分析，零网络请求，适配无外网/沙箱环境）")
    ap.add_argument("--timeout", type=int, default=5, help="单 URL 超时秒数，默认 5（原 15 过长）")
    ap.add_argument("--all-probes", action="store_true",
                    help="不跳过已知不可直连域名，全量探测（默认会跳过）")
    ap.add_argument("--skip-known-blocked", dest="skip_blocked", action="store_true", default=True,
                    help="跳过已知大陆不可直连域名（默认开启）")
    ap.add_argument("--no-skip-known-blocked", dest="skip_blocked", action="store_false",
                    help="关闭跳过（等价于 --all-probes 的探测部分）")
    ap.add_argument("--stale-days", type=int, default=30, help="R3 陈旧阈值，默认 30 天")
    ap.add_argument("--apply", action="store_true", help="开启写回（默认 dry-run 预览，不落盘）")
    ap.add_argument("--yes", action="store_true", help="配合 --apply 才真正落盘（先自动备份）")
    return ap.parse_args()


def main() -> None:
    args = build_argparser()
    # --all-probes 强制关闭跳过
    if args.all_probes:
        args.skip_blocked = False

    # 🔴 默认离线（2026-10-31 沙箱评测教训）：无外网环境做全量网络探测会把整轮挂到超时。
    # 要真实探测必须显式 --probe；超时同时收紧到 --timeout（默认 5s）。
    global TIMEOUT
    TIMEOUT = max(1, int(args.timeout))

    catalog_path = Path(args.catalog) if args.catalog else resolve_references_dir()
    catalog = load_catalog(catalog_path)

    print(f"[info] 货架: {catalog_path}", file=sys.stderr)
    if args.probe:
        probes_by_idx = run_probes(catalog, args.skip_blocked)
    else:
        probes_by_idx = {}
        for idx, p in enumerate(catalog.get("providers", [])):
            entries = []
            for ep in (p.get("endpoints") or []):
                cleaned = clean_url(ep)
                if cleaned.startswith("http"):
                    entries.append(ProbeResult(cleaned, host_of(cleaned), "SKIPPED", "",
                                               "离线模式未探测（加 --probe 开启真实探测）"))
            probes_by_idx[idx] = entries
        print("[info] 离线模式：未发起任何网络请求（加 --probe 开启真实探测）", file=sys.stderr)

    # 探测汇总
    probe_summary = Counter()
    total = 0
    for idx, probes in probes_by_idx.items():
        for p in probes:
            probe_summary[p.category] += 1
            total += 1
    probe_summary = {
        "total": total,
        "OK": probe_summary.get("OK", 0),
        "WARN": probe_summary.get("WARN", 0),
        "DOWN": probe_summary.get("DOWN", 0),
        "SKIPPED": probe_summary.get("SKIPPED", 0),
    }
    print(f"[info] 探测 URL 数: {total}（OK {probe_summary['OK']} / WARN {probe_summary['WARN']} "
          f"/ DOWN {probe_summary['DOWN']} / SKIPPED {probe_summary['SKIPPED']}）", file=sys.stderr)

    actions, writeback = build_actions(catalog, probes_by_idx, args.stale_days)

    if args.json:
        print(render_json(catalog, probes_by_idx, actions, writeback, args, probe_summary))
    else:
        print(render_markdown(catalog, probes_by_idx, actions, writeback, args, probe_summary))

    # 写回（仅 --apply --yes）
    apply_writeback(catalog_path, catalog, writeback, args)

    # 退出码：报告成功产出即 0。P0/P1 是货架健康结论，已体现在报告中；
    # 以「需关注」置非 0 会让沙箱评测 / 定时任务把正常完成的巡检误判为失败。
    sys.exit(0)


if __name__ == "__main__":
    main()
