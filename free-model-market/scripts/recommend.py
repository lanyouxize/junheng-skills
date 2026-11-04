#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
免费模型超市 · 选型推荐引擎

把用户的一句自然语言需求，确定性地映射为references/model-catalog.json 里的
渠道候选（Markdown 表格 / JSON），取代「AI 每次现场读静态选型表自由发挥」的不确定路径。

设计铁律（与 SKILL.md 一致，违反即视为 Bug）：
    1. 绝不编造额度数字——quota / rate_limit 一律原样转述 JSON 原文；
    2. 绝不推荐 expired / unverified（红线，直接排除）；
    3. degraded 候选必须带风险提示，并说明「为什么 degraded」；
    4. 每个候选带snapshot_date 作为核实日期；
    5. 无任何渠道命中时明确说「货架内无完全匹配」，不硬凑。

用法：
    python 免费模型超市-recommend.py "低延迟实时对话"
    python 免费模型超市-recommend.py "写代码，重构一个Python 项目"
    python 免费模型超市-recommend.py --list
    python 免费模型超市-recommend.py --json "语音转写"
    python 免费模型超市-recommend.py "长期稳定的免绑卡渠道" --top 5

说明：
    - 仅用标准库，不pip 任何东西；
    - 数据文件按 __file__ 反推目录定位，与当前工作目录（cwd）无关；
    - quota / rate_limit / notes 均为自由文本，本脚本只做「文本命中」，
      任何需要数值的判断只用于**排序**，绝不写进输出。
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
from pathlib import Path

# Windows 控制台默认 GBK，print 中文会UnicodeEncodeError —— 强制 UTF-8 输出。
# errors="replace" 兜底：极端编码环境下宁可显示替换符，也不要让脚本崩掉。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # 老版本 Python / 被重定向的流
        pass

SCRIPT_NAME = "免费模型超市-recommend.py"
CATALOG_FILENAME = "model-catalog.json"
DISCLAIMER = "免费额度随时可能调整，正式使用前请点击来源链接复核最新政策。"


# ---------------------------------------------------------------------------
# 一、数据源定位（与 cwd 解耦）
# ---------------------------------------------------------------------------
def find_catalog() -> Path:
    """按 __file__ 向上逐级找 references/model-catalog.json。

    同一份脚本要同时放在「工作区根目录」和「publish/.../scripts/」两处，
    深度不一致，所以逐级上溯而不是写死某一级。
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "references" / CATALOG_FILENAME
        if candidate.exists():
            return candidate
    # 最后兜底：cwd（仅在脚本被复制到别处时才会走到）
    return Path.cwd() / "references" / CATALOG_FILENAME


def load_catalog() -> dict:
    path = find_catalog()
    if not path.exists():
        sys.exit(f"[错误] 找不到货架数据文件：{path}")
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 二、需求解析：场景标签 + 约束条件
# ---------------------------------------------------------------------------
# 场景 → (权重, 关键词)。关键词在「厂商名 + 模型 + 备注 + 额度 + 层级」拼接文本上做
# 子串匹配；权重体现「命中该场景后，这个渠道有多大概率真的能胜任」。
SCENES: dict[str, tuple[int, tuple[str, ...]]] = {
    "low_latency": (30, ("低延迟", "延迟低", "延迟小", "快", "实时", "即时", "对话", "聊天", "客服", "低延迟", "响应快")),
    "coding": (28, ("代码", "编程", "coding", "写脚本", "重构", "debug", "程序", "写个", "coder")),
    "long_context": (26, ("长文", "长文档", "文档", "上下文", "context", "长记忆", "总结", "摘要", "长文本", "全书")),
    "speech": (30, ("语音", "音频", "转写", "whisper", "asr", "语音识别", "录音")),
    "vision": (26, ("图片", "看图", "视觉", "多模态", "图像", "识图", "截图")),
    "zero_config": (30, ("免注册", "零配置", "不注册", "不想注册", "无需注册", "免登录", "直接可用", "开箱")),
    "flagship": (24, ("最强", "旗舰", "最好质量", "质量最好", "最高质量", "最好的", "sota", "能力最强")),
    "multi_provider": (22, ("多模型", "随便试", "切换", "试遍", "一个 key", "一把key", "聚合", "路由")),
    "edge": (22, ("边缘", "serverless", "部署", "边缘计算", "自部署")),
    "chinese": (18, ("中文", "简体", "古文", "文案", "中文语料", "写作")),
    "web_search": (26, ("联网搜索", "联网", "实时信息", "实时新闻", "查资料", "搜索一下", "上网查", "今天的消息")),
}

# 约束条件关键词
CONSTRAINT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "no_card": ("不绑卡", "免绑卡", "不用绑卡", "不想绑卡", "不要绑卡", "不需要绑卡", "信用卡", "绑卡", "免信用卡"),
    "long_term": ("长期", "稳定", "持续", "一直用", "当日常用", "长期用", "长期稳定"),
}

# 约束键 → 中文名（输出用）
CONSTRAINT_LABELS: dict[str, str] = {
    "no_card": "要求免绑卡",
    "long_term": "要求长期稳定",
}

# 场景标签 → 中文名（输出用）
SCENE_LABELS: dict[str, str] = {
    "low_latency": "低延迟实时对话",
    "coding": "代码生成",
    "long_context": "长上下文/长文档",
    "speech": "语音转写",
    "vision": "图片/多模态",
    "zero_config": "零配置免注册",
    "flagship": "高质量旗舰模型",
    "multi_provider": "一个 Key 试遍多家",
    "edge": "边缘/Serverless",
    "chinese": "中文任务",
    "web_search": "联网搜索",
}


def parse_need(text: str) -> dict:
    """从自由文本需求中提取场景标签与约束条件。"""
    low = text.lower()
    hits: list[str] = []
    for scene, (_, keywords) in SCENES.items():
        if any(kw.lower() in low for kw in keywords):
            hits.append(scene)

    constraints = {
        name: any(kw.lower() in low for kw in kws)
        for name, kws in CONSTRAINT_KEYWORDS.items()
    }
    # 速度要求：命中低延迟场景即视为有速度要求
    constraints["speed"] = "low_latency" in hits
    return {"scenes": hits, "constraints": constraints}


# ---------------------------------------------------------------------------
# 三、渠道层级映射表（可配置，禁止硬编码条数）
# ---------------------------------------------------------------------------
# 依据：SKILL.md「先讲清楚：货架里的『免费』有三层」——把货架按额度性质分三档，
# 推荐优先级 真免费层 > 按月续额度 > 一次性试用。
# 这里维护「厂商名 → 层级」的显式映射，而不是靠名字猜或写死「8 家/2 家/22 家」：
# 货架增删条目时只改这张表即可，条数变化不会让引擎失效。
#
# 说明：未在此表出现的 active/degraded 渠道一律归入 ONETIME（最保守档），
# 保证「未知层级」不会被当成真免费层发给用户。
TIER_PERPETUAL = "perpetual"  # 真免费层：额度按日/月持续发放或按限速给量，无到期日
TIER_MONTHLY = "monthly"      # 按月续额度：名义免费，额度按月重置
TIER_ONETIME = "onetime"      # 一次性试用：获客赠金，多数 30 天过期，部分强制绑卡

TIER_MAP: dict[str, str] = {
    # —— 真免费层（SKILL.md 列举的 10 家）——
    "Kilo AI Gateway": TIER_PERPETUAL,  # 匿名免费池：免注册免 Key，无到期日（2026-10-22 新增）
    "Groq": TIER_PERPETUAL,
    "Cloudflare Workers AI": TIER_PERPETUAL,
    "Mistral La Plateforme（Experiment 计划）": TIER_PERPETUAL,
    "Cohere": TIER_PERPETUAL,
    "OpenRouter": TIER_PERPETUAL,
    "Google AI Studio": TIER_PERPETUAL,
    "NVIDIA NIM (build.nvidia.com)": TIER_PERPETUAL,
    "Hetzner Inference（Experiments）": TIER_PERPETUAL,
    # 额度为「每日刷新、无到期日」，形式上属真免费层；但限客户端内调用，
    # 故其不可外部消费的风险由 degraded 风险提示承担，不在此处降档。
    "OpenCode Zen": TIER_PERPETUAL,
    # —— 按月续额度（2 家）——
    "Hugging Face Inference Providers": TIER_MONTHLY,
    "Vercel AI Gateway": TIER_MONTHLY,
    # Modal 为 $30/月 免费计算额度，按月重置，归按月续额度而非一次性赠金
    "Modal": TIER_MONTHLY,
    # —— 其余 active/degraded 渠道均属获客赠金层，不在此表即落到 TIER_ONETIME ——
}

# 层级 →（加分, 长期稳定要求下的额外惩罚, 中文说明）
TIER_POLICY: dict[str, tuple[int, int, str]] = {
    TIER_PERPETUAL: (25, 0, "真免费层"),
    TIER_MONTHLY: (12, -8, "按月续额度"),
    TIER_ONETIME: (0, -40, "一次性试用"),
}

# 能力提示表：对「厂商名 + 模型 + 备注」自由文本命中不了的能力做人工补充。
# 只影响**排序**，不进入输出字段；增补依据均来自 catalog 对应条目的 models/notes 原文。
CAPABILITY_HINTS: dict[str, tuple[str, ...]] = {
    "vision": (
        "Kilo AI Gateway",
        "Google AI Studio", "Cloudflare Workers AI", "NVIDIA NIM (build.nvidia.com)",
        "Groq", "Mistral La Plateforme（Experiment 计划）", "OpenRouter",
        "Hetzner Inference（Experiments）", "Inception（Mercury 扩散式 LLM）",
    ),
    "long_context": (
        "Google AI Studio", "Hetzner Inference（Experiments）", "Inception（Mercury 扩散式 LLM）",
        "AI21", "Z.ai（智谱国际站）", "Alibaba Cloud (Model Studio 国际站)",
    ),
    "flagship": (
        "Anthropic", "Mistral La Plateforme（Experiment 计划）", "OpenAI", "xAI",
        "Inception（Mercury 扩散式 LLM）", "Alibaba Cloud (Model Studio 国际站)",
        "Z.ai（智谱国际站）",
    ),
    "chinese": (
        "Z.ai（智谱国际站）", "Alibaba Cloud (Model Studio 国际站)", "Cohere",
        "Google AI Studio", "Mistral La Plateforme（Experiment 计划）",
    ),
    "edge": ("Cloudflare Workers AI", "Modal", "Hugging Face Inference Providers"),
    "multi_provider": (
        "OpenRouter", "Vercel AI Gateway", "B.AI（聚合路由平台）",
    ),
    "zero_config": ("Kilo AI Gateway",),
    "speech": ("Groq", "Scaleway"),
}

# degraded 原因表：catalog 没有 status_note 字段，这里按各条目 notes 原文浓缩一句话，
# 保证 degraded 候选必须说清「为什么 degraded」。
DEGRADE_REASON: dict[str, str] = {
    "OpenCode Zen": "免费层限 OpenCode 客户端内调用，外部调用实测403（仅 space-bunny-free 可用）；实测响应较慢",
    "OpenAI": "原约 $5 自动额度已不稳定，额度政策频繁变动",
    "xAI": "$25 注册赠金政策不稳定、时有时无；数据共享计划已无官方记载",
    "B.AI（聚合路由平台）": "0 Credits 全免款 3 个月内从 6 款缩减至 3 款，高热度导致免费款快速收回",
    "Inception（Mercury 扩散式 LLM）": "免费 token 官方两页口径差 10 倍；实测吞吐与宣传差一个量级，结构化输出错误率 11.25%",
}

# OpenAI 兼容端点补充名单：凡notes/models 里没写「OpenAI 兼容」但端点为 /v1 形态的，
# 按行业通行约定归为 OpenAI 兼容；Anthropic 是 /v1 但**不**兼容，必须显式排除。
OPENAI_COMPAT_EXTRA: frozenset[str] = frozenset({
    "OpenRouter", "Mistral La Plateforme（Experiment 计划）", "xAI", "Cerebras",
    "AI21", "Upstage", "SambaNova", "Novita", "Hyperbolic", "Scaleway",
    "Z.ai（智谱国际站）", "Inception（Mercury 扩散式 LLM）",
})
OPENAI_COMPAT_EXCLUDE: frozenset[str] = frozenset({"Anthropic", "OpenCode Zen"})


# ---------------------------------------------------------------------------
# 四、文本工具
# ---------------------------------------------------------------------------
def build_text(provider: dict) -> str:
    """把自由文本字段拼成一张用于关键词匹配的「大文本」。

    只取 name / models / notes 三列，**刻意不含 quota 与 rate_limit**：
    这两列是额度与限速的自由文本，其中的「数百万 tokens」「250K TPM」等
    单位词会让「长上下文」这类场景产生假命中（实测 Cloudflare 因
    「数百万 tokens」被误判为长上下文渠道）。额度文本只在 card_kind
    里用于绑卡判断，不参与场景匹配。
    """
    parts = [
        provider.get("name", ""),
        provider.get("models", ""),
        provider.get("notes", ""),
        provider.get("section", ""),
    ]
    return "\n".join(parts).lower()


def clean_cell(value: str, limit: int = 0) -> str:
    """把自由文本压成安全的表格单元格：去换行、转义竖线、按需截断。

    quota / rate_limit 默认「原样转述」，只做排版清洗，不改动任何数字或措辞。
    """
    if not value:
        return "—"
    text = re.sub(r"\s+", " ", str(value)).strip()
    text = text.replace("|", "｜")
    if limit and len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text or "—"


def card_kind(provider: dict) -> str:
    """把绑卡要求归一为 no / yes / unknown 三种，只用于排序与风险提示。

    catalog 里不少条目没有 credit_card 字段，但 notes 原文写了绑卡政策
    （如 Anthropic「API 使用需绑卡」、AI21「官方确认无需信用卡」），
    因此以 credit_card 为主、notes/quota 为辅，避免把已知信息误报成「未标注」。
    """
    raw = " ".join(
        provider.get(k, "") for k in ("credit_card", "notes", "quota")
    )
    if not raw.strip():
        return "unknown"
    if any(k in raw for k in ("不需要", "免注册", "无需信用卡", "免信用卡", "不绑卡")):
        return "no"
    if any(k in raw for k in ("需要", "绑卡", "需账号", "需手机", "验证支付", "支付方式", "需验证手机号")):
        return "yes"
    return "unknown"


def rpm_upper_bound(provider: dict) -> int:
    """从 rate_limit 原文里取RPM 上界，仅作速度排序信号，绝不写进输出。"""
    nums = [
        int(m.replace(",", ""))
        for m in re.findall(r"([\d,]+)\s*RPM", provider.get("rate_limit", ""), re.IGNORECASE)
    ]
    return max(nums) if nums else 0


def is_openai_compat(provider: dict) -> bool:
    name = provider.get("name", "")
    if name in OPENAI_COMPAT_EXCLUDE:
        return False
    if name in OPENAI_COMPAT_EXTRA:
        return True
    text = f"{provider.get('notes', '')} {provider.get('models', '')}".lower()
    if "openai 兼容" in text or "compatible-mode" in text:
        return True
    endpoint = (provider.get("endpoints") or [""])[0]
    return endpoint.rstrip("/").endswith("/v1")


# ---------------------------------------------------------------------------
# 五、打分
# ---------------------------------------------------------------------------
def score_provider(provider: dict, need: dict, index: int) -> dict:
    """给单个渠道打分，返回 {score, hits, tier, reasons...}。"""
    name = provider.get("name", "")
    text = build_text(provider)
    scenes = need["scenes"]
    constraints = need["constraints"]

    hits: list[str] = []
    score = 0.0
    for scene in scenes:
        weight, keywords = SCENES[scene]
        if any(kw.lower() in text for kw in keywords) or name in CAPABILITY_HINTS.get(scene, ()):
            hits.append(scene)
            score += weight

    # 层级优先级
    tier = TIER_MAP.get(name, TIER_ONETIME)
    tier_bonus, long_term_penalty, tier_label = TIER_POLICY[tier]
    score += tier_bonus
    if constraints["long_term"] and tier == TIER_ONETIME:
        score += long_term_penalty

    # 免绑卡约束
    card = card_kind(provider)
    if card == "no":
        score += 8
    elif card == "yes":
        score += -6 if not constraints["no_card"] else -60

    # 速度信号：只影响排序
    if constraints["speed"] and rpm_upper_bound(provider):
        score += min(10, rpm_upper_bound(provider) / 20)

    # 状态：active 基准不变；degraded 降权（红线 expired/unverified 在调用方已排除）
    status = provider.get("status", "unknown")
    if status == "degraded":
        score += -18

    return {
        "index": index,
        "name": name,
        "score": round(score, 2),
        "hits": hits,
        "tier": tier,
        "tier_label": tier_label,
        "card": card,
        "status": status,
        "rpm": rpm_upper_bound(provider),
    }


def build_risk(provider: dict, tier: str, card: str) -> str:
    """生成风险提示：degraded 必须说明原因；试用层必须三说清（额度/有效期/绑卡）。"""
    name = provider.get("name", "")
    risks: list[str] = []
    if provider.get("status") == "degraded":
        reason = DEGRADE_REASON.get(name)
        risks.append(f"⚠️ degraded：{reason}" if reason else "⚠️ degraded：状态降级，采用前请复核来源链接")
    if tier == TIER_ONETIME:
        risks.append("一次性试用赠金，多数 30 天过期、不可持续")
    elif tier == TIER_MONTHLY:
        risks.append("赠金按月重置，非永久免费层")
    if card == "yes":
        risks.append("需绑卡/需验证支付方式")
    elif card == "unknown":
        risks.append("货架未标注绑卡要求，采用前请到控制台确认")
    return "；".join(risks) if risks else "无额外风险（仍以官方实时政策为准）"


def build_access(provider: dict, all_candidates: list[dict]) -> str:
    """按渠道特征生成接入方式。"""
    name = provider.get("name", "")

    # 零配置特例：OpenCode Zen免注册 + Key 固定 public
    if name == "OpenCode Zen":
        return "零配置：运行 inject_workbuddy.py --apply 即可直接对话"

    if is_openai_compat(provider):
        text = "注册拿 Key → WorkBuddy 配置自定义模型"
        # 同批候选里有多家 active OpenAI 兼容渠道时，追加网关自动路由提示
        peers = sum(
            1 for c in all_candidates
            if c.get("status") == "active" and is_openai_compat(c)
        )
        if peers >= 2:
            text += "；或用「自由模型市场·网关」自动路由"
        return text

    # 平台型（无API 端点、或卖的是计算/容器资源）
    if not provider.get("endpoints") or provider.get("endpoints") == ["https://modal.com"] or provider.get("endpoints") == ["https://ollama.com"]:
        return "官网注册开通控制台 → 按官方文档接入"
    return "按 endpoints 里的 API 端点接入（详见来源链接）"


# ---------------------------------------------------------------------------
# 六、候选筛选
# ---------------------------------------------------------------------------
# 判定「完全匹配」的最低分：至少要有一个场景命中，且总分过这条线。
EXACT_MATCH_FLOOR = 20.0


def recommend(catalog: dict, need_text: str, top: int) -> dict:
    need = parse_need(need_text)
    snapshot = catalog.get("snapshot_date", "未知")

    # 红线：expired / unverified 直接排除，绝不进入候选
    pool = [
        (i, p) for i, p in enumerate(catalog.get("providers", []))
        if p.get("status") in ("active", "degraded")
    ]

    scored = [score_provider(p, need, i) for i, p in pool]
    scored.sort(key=lambda s: (-s["score"], s["index"]))
    shortlist = scored[: max(top, 0)] if top else scored

    results: list[dict] = []
    for rank, s in enumerate(shortlist, start=1):
        provider = catalog["providers"][s["index"]]
        results.append({
            "rank": rank,
            "name": provider.get("name", ""),
            "models": clean_cell(provider.get("models", "")),
            "quota": clean_cell(provider.get("quota", "")),
            "rate_limit": clean_cell(provider.get("rate_limit", "")),
            "credit_card": clean_cell(provider.get("credit_card", "")),
            "snapshot_date": snapshot,
            "status": provider.get("status", ""),
            "tier": s["tier"],
            "tier_label": s["tier_label"],
            "score": s["score"],
            "matched_scenes": s["hits"],
            "matched_scene_labels": [SCENE_LABELS[x] for x in s["hits"]],
            "access": build_access(provider, [catalog["providers"][i] for i, _ in pool]),
            "risk": build_risk(provider, s["tier"], s["card"]),
            "endpoints": provider.get("endpoints", []),
        })

    # 判定「完全匹配」必须**至少命中一个场景**：仅靠层级分就能越过分数线，
    # 会让「我要一台量子计算机」这种完全跑偏的请求被误报成已匹配。
    exact = [r for r in results if r["matched_scenes"] and r["score"] >= EXACT_MATCH_FLOOR]

    # 约束冲突告警：用户要「长期稳定」但候选里混进了非真免费层，必须显式点破，
    # 否则小白用户会抱着零成本长期预期踩到额度耗尽那天（SKILL.md 明确要求）。
    warnings: list[str] = []
    if need["constraints"]["long_term"]:
        weak = [
            r["name"] for r in results
            if r["tier"] != TIER_PERPETUAL or r["status"] == "degraded"
        ]
        if weak:
            warnings.append(
                "你要求「长期稳定」，但以下候选不是永久免费层或状态已降级，"
                f"不建议作为长期主力：{'、'.join(weak)}"
            )
        if not any(r["tier"] == TIER_PERPETUAL and r["status"] == "active" for r in results):
            warnings.append(
                "货架内没有同时满足「active + 真免费层」的渠道，"
                "建议缩小需求或接受按月额度层。"
            )
    if need["constraints"]["no_card"]:
        need_card = [r["name"] for r in results if r["credit_card"] and "不" not in r["credit_card"]]
        if need_card:
            warnings.append(f"你要求「免绑卡」，以下候选需绑卡或需验证支付：{'、'.join(need_card)}")

    return {
        "query": need_text,
        "snapshot_date": snapshot,
        "catalog_generated_at": catalog.get("generated_at", ""),
        "parsed_scenes": need["scenes"],
        "parsed_scene_labels": [SCENE_LABELS[x] for x in need["scenes"]],
        "constraints": {k: v for k, v in need["constraints"].items() if k != "speed"},
        "needs_speed": need["constraints"]["speed"],
        "exact_match": bool(exact),
        "no_match_note": "" if exact else "货架内无完全匹配，以下是相近选项",
        "warnings": warnings,
        "excluded_count": len(catalog.get("providers", [])) - len(pool),
        "candidates": results,
        "disclaimer": DISCLAIMER,
    }


# ---------------------------------------------------------------------------
# 七、输出渲染
# ---------------------------------------------------------------------------
TABLE_HEADERS = ("渠道", "模型", "免费额度", "限速", "核实日期", "接入方式", "风险提示")


def render_table(rows: list[dict]) -> str:
    lines = [
        "| " + " | ".join(TABLE_HEADERS) + " |",
        "| " + " | ".join("---" for _ in TABLE_HEADERS) + " |",
    ]
    for r in rows:
        flag = "🟡" if r["status"] == "degraded" else "🟢"
        lines.append(
            f"| {flag} {r['rank']}. {r['name']}"
            f" | {r['models']}"
            f" | {r['quota']}"
            f" | {r['rate_limit']}"
            f" | {r['snapshot_date']}"
            f" | {r['access']}"
            f" | {r['risk']} |"
        )
    return "\n".join(lines)


def print_list(catalog: dict) -> None:
    """--list：列出全部可推荐渠道概览（active + degraded）。"""
    snapshot = catalog.get("snapshot_date", "未知")
    rows = []
    for p in catalog.get("providers", []):
        if p.get("status") not in ("active", "degraded"):
            continue
        tier = TIER_MAP.get(p.get("name", ""), TIER_ONETIME)
        card = card_kind(p)
        rows.append({
            "rank": len(rows) + 1,
            "name": p.get("name", ""),
            "models": clean_cell(p.get("models", "")),
            "quota": clean_cell(p.get("quota", "")),
            "rate_limit": clean_cell(p.get("rate_limit", "")),
            "snapshot_date": snapshot,
            "access": build_access(p, catalog.get("providers", [])),
            "risk": build_risk(p, tier, card),
            "status": p.get("status", ""),
        })

    active_n = sum(1 for r in rows if r["status"] == "active")
    degraded_n = len(rows) - active_n
    excluded = catalog.get("provider_count", 0) - len(rows)

    print(f"# 免费模型超市 · 货架概览（核实日期 {snapshot}）")
    print(f"可推荐 {len(rows)} 条：active {active_n} / degraded {degraded_n}；"
          f"已排除 {excluded} 条 expired / unverified（红线，不推荐）")
    print()
    print(render_table(rows))
    print()
    print(f"> {DISCLAIMER}")


def print_result(result: dict) -> None:
    print(f"# 推荐结果：{result['query']}")
    print(f"数据核实日期：{result['snapshot_date']}"
          f"（catalog 生成于 {result['catalog_generated_at']}）")

    labels = result["parsed_scene_labels"]
    cons = [CONSTRAINT_LABELS[k] for k, v in result["constraints"].items() if v]
    print(f"识别场景：{'、'.join(labels) if labels else '未识别到明确场景（按通用偏好排序）'}")
    print(f"约束条件：{'、'.join(cons) if cons else '无'}"
          f"{'；速度优先' if result['needs_speed'] else ''}")
    print()

    if not result["exact_match"]:
        print(f"> **{result['no_match_note']}**")
        print()

    if not result["candidates"]:
        print("货架内没有任何 active / degraded 渠道可供推荐。")
        print(f"> {DISCLAIMER}")
        return

    for w in result.get("warnings", []):
        print(f"> ⚠️ {w}")
    if result.get("warnings"):
        print()

    print(render_table(result["candidates"]))
    print()
    for r in result["candidates"]:
        if r["matched_scene_labels"]:
            print(f"- **{r['name']}**：命中场景 {'、'.join(r['matched_scene_labels'])}"
                  f"（{r['tier_label']}）")
        else:
            print(f"- **{r['name']}**：{r['tier_label']}，未直接命中场景，作为相近选项")
    print()
    print(f"> {DISCLAIMER}")


# ---------------------------------------------------------------------------
# 八、CLI
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=SCRIPT_NAME,
        description="免费模型超市 · 选型推荐引擎（自然语言需求 → 免费模型渠道候选）",
        epilog="示例：python recommend.py \"低延迟实时对话\" / --list / --json \"语音转写\"",
    )
    p.add_argument("query", nargs="*", help="用户需求描述，如「写代码，重构一个 Python 项目」")
    p.add_argument("--list", action="store_true", help="列出全部 active / degraded 渠道概览")
    p.add_argument("--json", action="store_true", help="以 JSON 输出（供程序消费）")
    p.add_argument("--top", type=int, default=3, help="候选数量，默认 3")
    return p


def main() -> None:
    args = build_parser().parse_args()
    catalog = load_catalog()
    query = " ".join(args.query).strip()

    if args.list:
        print_list(catalog)
        return

    if not query:
        # 零参数：直接给出货架总览（比打印 usage 更有用），末尾附用法提示
        print_list(catalog)
        print("\n[用法] python recommend.py \"你的需求描述\" 可按场景精确推荐，"
              "如：python recommend.py \"写代码，重构一个 Python 项目\"")
        return

    result = recommend(catalog, query, args.top)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_result(result)


if __name__ == "__main__":
    main()
