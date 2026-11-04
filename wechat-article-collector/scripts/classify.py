#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分类筛选层（P0）：把鉴汇3.0 的关键词打分 + 置信度闸门移植到采集链路。

单一真源（勿另造第二套，否则与元典/vault 侧漂移）
------------------------------------------------
* 打分 —— werss-src/tools/classify_suggest.py
  分区权重 title=4.0 / desc=1.8 / content=1.0；同一分区命中词只算前 2 个满分、
  其余 ×0.5（起因：正文凑 5 个弱相关词压过标题强词，「黄芪」被益生菌类词盖过）；
  MIN_SCORE=1.0 不进候选；TOP_N=3。
* 闸门 —— werss-src/tools/auto_classify_plan.py
  tier1 = conf≥阈值(默认0.85) 且 标题命中≥2 个**不同**词 且 无负面词；
  tier2 = 标题命中≥1 且 top1/top2≥5.0（入库但标「待核」，错误可被一眼看出）；
  视频/图片/音频形态撤销自动采纳（正文文本不可靠），转人工但**不剔除**。
* 规则 —— tools/classify/{taxonomy,keywords}.json（vendor 快照见 references/classify/）
* 离域 —— taxonomy.industries["OUT"].keep=false/clear=true + off_domain_blacklist

与鉴汇3.0 的刻意差异（本模块的边界）
------------------------------------
本模块**不碰数据库、不写库**，只产出分类结论；调用方（write_to_library）据
`tier` 决定写不写。离域文章判 `tier=None`（不写库），**绝不静默丢弃**——结果
里带 `off_domain` 原因，便于审计（呼应 taxonomy 里 G7 因「静默跳过 10 篇」被迫
新增类目的教训）。

用法（库函数）::

    from classify import load_rules, classify_many
    ruleset = load_rules()                       # 默认读 references/classify/
    results = classify_many(articles, ruleset)   # articles: [dict]

用法（CLI）::

    python classify.py --in out.jsonl --out classified.jsonl [--threshold 0.85] [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------- 阈值常量（与鉴汇3.0 对齐）
ZONE_WEIGHT = {"title": 4.0, "desc": 1.8, "content": 1.0}
ZONE_DECAY = (2, 0.5)          # 同区前 2 词满分，其余打 5 折
MIN_SCORE = 1.0                # 低于此分不进候选
TOP_N = 3
ZONE_KIND = {"title": "topic", "desc": "topic", "content": "mention"}
AMBIGUITY_RATIO = 1.2          # top1/top2 低于此比值只提示「两者接近」，不作门槛
MIN_TITLE_KEYWORDS = 2         # tier1 要求标题命中≥2 个不同词
AUTO_CHECK_DOMINANCE = 5.0     # tier2 的领先倍数门槛
SHAPE_SKIP_LABEL = {"video": "视频型", "image": "图片型", "audio": "音频型"}
APPLICABILITY = {"A": "direct", "B": "direct", "C": "direct", "D": "direct",
                 "E": "transferable", "F": "direct", "G": "direct",
                 "H": "transferable"}
DEFAULT_THRESHOLD = 0.85
DEFAULT_RULES_DIR = Path(__file__).resolve().parent.parent / "references" / "classify"

try:  # CLI 用；被 import 时也要求 common 可导入（测试会 sys.path.insert scripts）
    from common import EXIT_ERROR, EXIT_OK, EXIT_PARAM
except Exception:  # pragma: no cover - 极端环境下退化
    EXIT_OK, EXIT_PARAM, EXIT_ERROR = 0, 2, 3


# ---------------------------------------------------------------- 规则加载
def _load_json(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_rules(taxonomy_path: str | Path | None = None,
               keywords_path: str | Path | None = None) -> dict:
    """加载 (taxonomy, rules, negatives)。规则文件缺失时抛 FileNotFoundError。"""
    tax_p = Path(taxonomy_path) if taxonomy_path else DEFAULT_RULES_DIR / "taxonomy.json"
    kw_p = Path(keywords_path) if keywords_path else DEFAULT_RULES_DIR / "keywords.json"
    tax = _load_json(tax_p)
    kw = _load_json(kw_p)
    rules = kw.get("rules") or {}
    negatives = (kw.get("negative") or {}).get("keywords") or []
    if not rules:
        raise ValueError(f"keywords.json 未含 rules：{kw_p}")
    return {"tax": tax, "rules": rules, "negatives": negatives,
            "taxonomy_path": str(tax_p), "keywords_path": str(kw_p)}


# ---------------------------------------------------------------- 文本准备
def _strip_tags(text: str) -> str:
    """极简去标签（与 classify_suggest.load_articles 同口径，够用即可）。"""
    text = (text or "").replace("</p>", "\n")
    guard = 0
    while "<" in text and ">" in text and guard < 20000:
        i = text.find("<")
        j = text.find(">", i)
        if j < 0:
            break
        text = text[:i] + " " + text[j + 1:]
        guard += 1
    return text


def article_text(article: dict) -> tuple[str, str, str]:
    """取 (title, desc, content)。content 优先读 body_ref 指向的正文文件，否则用 digest。"""
    title = (article.get("title") or "").strip()
    desc = (article.get("digest") or "").strip()
    content = ""
    ref = str(article.get("body_ref") or "").strip()
    if ref:
        try:
            content = _strip_tags(Path(ref).read_text(encoding="utf-8", errors="replace"))[:6000]
        except OSError:
            content = ""
    if not content:
        content = desc[:6000]
    return title, desc, content


# ---------------------------------------------------------------- 打分（移植）
def score_article(title: str, desc: str, content: str, rules: dict) -> list[dict]:
    """返回按分数降序的候选 [{'code','name','score','hits','zones','evidence'}]。"""
    zones = {"title": title, "desc": desc, "content": content}
    scored: list[dict] = []
    for code, rule in rules.items():
        total, hits = 0.0, []
        for zone, text in zones.items():
            if not text:
                continue
            zone_hits = [(kw, float(w)) for kw, w in (rule.get("keywords") or {}).items()
                         if kw and kw in text]
            zone_hits.sort(key=lambda x: -x[1])
            for idx, (kw, weight) in enumerate(zone_hits):
                factor = 1.0 if idx < ZONE_DECAY[0] else ZONE_DECAY[1]
                total += weight * ZONE_WEIGHT[zone] * factor
                hits.append({"kw": kw, "zone": zone, "w": weight})
        if total >= MIN_SCORE:
            cand = {"code": code, "name": rule.get("name", ""),
                    "score": round(total, 2), "hits": hits}
            cand["zones"] = _zone_split(cand)
            cand["evidence"] = evidence_of(cand)
            scored.append(cand)
    scored.sort(key=lambda x: -x["score"])
    return scored[:TOP_N]


def _zone_split(cand: dict) -> dict:
    out = {"title": 0.0, "desc": 0.0, "content": 0.0}
    for h in (cand.get("hits") or []):
        out[h["zone"]] = round(out.get(h["zone"], 0.0) + float(h["w"]), 2)
    return out


def evidence_of(cand: dict) -> str:
    zones = {h["zone"] for h in (cand.get("hits") or [])}
    if not zones:
        return ""
    return "topic" if any(ZONE_KIND.get(z) == "topic" for z in zones) else "mention_only"


def ambiguity_of(cands: list[dict]) -> dict:
    if len(cands) < 2 or not cands[1].get("score"):
        return {}
    ratio = round(cands[0]["score"] / cands[1]["score"], 2)
    return {"ratio": ratio, "rival": cands[1]["code"],
            "rival_name": cands[1].get("name", ""), "close": ratio < AMBIGUITY_RATIO}


def confidence_of(cands: list[dict]) -> float:
    if not cands:
        return 0.0
    top = cands[0]["score"]
    base = 0.42 + 0.13 * min(top, 3.5)
    if len(cands) > 1 and cands[1]["score"] >= 0.7 * top:
        base -= 0.12
    return round(min(0.92, max(0.3, base)), 2)


def dominance(cands: list[dict]) -> float:
    if not cands:
        return 0.0
    top = cands[0].get("score") or 0
    second = cands[1].get("score") if len(cands) > 1 else 0
    if top <= 0:
        return 0.0
    if not second or second <= 0:
        return 99.0
    return top / second


def title_keyword_hits(cands: list[dict]) -> int:
    """标题区命中的不同关键词个数（同词命中两次只算一个）。"""
    if not cands:
        return 0
    return len({h.get("kw") for h in cands[0].get("hits", []) if h.get("zone") == "title"})


def basis_of(top: dict, cands: list[dict]) -> str:
    zone_cn = {"title": "标题", "desc": "摘要", "content": "正文"}
    kws = ["%s（%s）" % (h["kw"], zone_cn[h["zone"]]) for h in top.get("hits", [])[:5]]
    text = "命中 " + "、".join(kws)
    if evidence_of(top) == "mention_only":
        text += "；仅正文提及，主题证据不足"
    if len(cands) > 1:
        text += "；次选 %s %s（%s）" % (cands[1]["code"], cands[1].get("name", ""), cands[1]["score"])
        if ambiguity_of(cands).get("close"):
            text += "，两者接近，建议人工定夺"
    return text


def l1_of(tax: dict, l2_code: str) -> tuple[str, str, str]:
    for lv in tax.get("levels") or []:
        for x in lv.get("l2") or []:
            if x.get("code") == l2_code:
                return lv.get("code", ""), lv.get("name", ""), x.get("name", "")
    return "", "", ""


# ---------------------------------------------------------------- 离域 / 行业轴
def off_domain_hit(title: str, desc: str, blacklist: dict) -> str:
    """命中离域黑名单则返回命中词，否则空串。zh 用子串，en 用词边界。"""
    text = "%s %s" % (title or "", desc or "")
    for term in (blacklist.get("zh") or []):
        if term and term in text:
            return str(term)
    for term in (blacklist.get("en") or []):
        if term and re.search(r"\b" + re.escape(str(term)) + r"\b", text, re.IGNORECASE):
            return str(term)
    return ""


def industry_of(tax: dict, l1_code: str) -> list[str]:
    val = (tax.get("l1_industry") or {}).get(l1_code)
    if isinstance(val, list):
        return [str(x) for x in val]
    if isinstance(val, str) and val:
        return [val]
    return []


# ---------------------------------------------------------------- 主判定
def classify_article(article: dict, ruleset: dict,
                     threshold: float = DEFAULT_THRESHOLD) -> dict:
    """单篇分类。返回结论 dict（含 tier：1 自动 / 2 待核 / 0 待人工 / None 离域）。"""
    tax, rules = ruleset["tax"], ruleset["rules"]
    negatives = ruleset.get("negatives") or []
    title, desc, content = article_text(article)
    od = off_domain_hit(title, desc, tax.get("off_domain_blacklist") or {})
    cands = score_article(title, desc, content, rules)
    conf = confidence_of(cands)
    neg_hits = [k for k in negatives if k and (k in title or k in desc)]
    shape = str(article.get("content_shape") or "").strip()
    hits = title_keyword_hits(cands)
    dom = dominance(cands)
    top = cands[0] if cands else {}

    l1 = l1_of(tax, top["code"])[0] if top else ""
    l1_name = l1_of(tax, top["code"])[1] if top else ""
    l2_name = top.get("name", "") if top else ""
    tags: list[str] = []
    for h in (top.get("hits") or []):
        if h.get("kw") not in tags:
            tags.append(h["kw"])

    tier: int | None = 0
    shape_skip = ""
    if od:
        # 离域优先于一切：不写库，但留原因
        tier = None
        basis = "[离域] 命中黑名单「%s」，不写库（不静默丢弃，保留可审计）" % od
        source = "off_domain"
        l1 = l1_name = l2_name = ""
        tags = []
    else:
        if cands and not neg_hits and conf >= threshold:
            if hits >= MIN_TITLE_KEYWORDS:
                tier = 1
            elif hits >= 1 and dom >= AUTO_CHECK_DOMINANCE:
                tier = 2
        if shape in SHAPE_SKIP_LABEL and tier:
            shape_skip = shape
            tier = 0
        prefix = "[自动] " if tier == 1 else "[待核] " if tier == 2 else "[待人工] "
        basis = prefix + (basis_of(top, cands) if cands else "未命中任何关键词（需人工归类）")
        if neg_hits:
            basis += "；含负面词 " + "、".join(neg_hits[:3])
        if shape_skip:
            basis += "；形态为%s，关键词投票不采信，转人工" % SHAPE_SKIP_LABEL[shape_skip]
        source = "auto" if tier == 1 else "auto_check" if tier == 2 else "draft"

    industry = industry_of(tax, l1) if l1 else []
    return {
        "record_id": article.get("record_id", ""),
        "title": title,
        "l1": l1, "l1_name": l1_name,
        "l2": top.get("code", "") if not od else "",
        "l2_name": l2_name,
        "industry": ",".join(industry),
        "applicability": "none" if od else APPLICABILITY.get(l1, "unknown"),
        "topic": evidence_of(top) if top else "",
        "confidence": conf,
        "basis": basis,
        "tier": tier,
        "shape_skip": shape_skip,
        "title_keyword_hits": hits,
        "dominance": None if dom >= 99 else round(dom, 2),
        "negative_hits": neg_hits,
        "off_domain": od,
        "tags": tags,
        "classify_source": source,
    }


def classify_many(articles: list[dict], ruleset: dict,
                  threshold: float = DEFAULT_THRESHOLD) -> list[dict]:
    return [classify_article(a, ruleset, threshold) for a in articles]


# ---------------------------------------------------------------- CLI
def _read_jsonl(path: str) -> list[dict]:
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="classify.py", description="鉴汇3.0 分类闸门（离线，不写库）")
    ap.add_argument("--in", dest="in_path", required=True, help="采集产出的 JSONL")
    ap.add_argument("--out", dest="out_path", default="", help="分类结果 JSONL（默认 stdout）")
    ap.add_argument("--taxonomy", default="", help="taxonomy.json 路径（默认 references/classify/）")
    ap.add_argument("--keywords", default="", help="keywords.json 路径（默认 references/classify/）")
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    ap.add_argument("--json", action="store_true", help="输出汇总 JSON 到 stderr")
    args = ap.parse_args(argv)
    try:
        ruleset = load_rules(args.taxonomy or None, args.keywords or None)
    except (OSError, ValueError) as exc:
        print(f"[classify] 规则加载失败：{exc}", file=sys.stderr)
        return EXIT_PARAM
    try:
        articles = _read_jsonl(args.in_path)
    except (OSError, ValueError) as exc:
        print(f"[classify] 读取输入失败：{exc}", file=sys.stderr)
        return EXIT_ERROR
    results = classify_many(articles, ruleset, args.threshold)
    lines = [json.dumps(r, ensure_ascii=False) for r in results]
    if args.out_path:
        Path(args.out_path).write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    else:
        for line in lines:
            print(line)
    if args.json:
        stats = {"total": len(results),
                 "auto": sum(1 for r in results if r["tier"] == 1),
                 "auto_check": sum(1 for r in results if r["tier"] == 2),
                 "draft": sum(1 for r in results if r["tier"] == 0),
                 "off_domain": sum(1 for r in results if r["tier"] is None),
                 "rules": ruleset["taxonomy_path"]}
        print(json.dumps(stats, ensure_ascii=False), file=sys.stderr)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
