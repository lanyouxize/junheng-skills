#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文章记录 schema（24 业务列）+ 归一化 / 校验 / 去重键 / 写库值映射。

25 列语义契约见 references/schema.md；本文件是列定义与值映射的唯一真源。
平台真实列类型词表（library/database/_db_types.py: VALID_TYPE_KEYS）没有
enum/int/datetime/text[]，映射关系（2026-10-22 实测 manifest 后确定）：
    text -> text | enum -> select | datetime -> date | int -> number
    text[](keyword_tags) -> text（逗号分隔）| url -> text
    以上两处均为 MVP 降级，留 update-field 升级。

keyword_tags 的降级原因（2026-10-22 真机 V2 实测，推翻原设计假设）：
    原设计用 multi_select + options=[]，理由是"标签值运行时按 option text 写入"。
    服务端直接拒绝：`code=11607 spaceengine/database: select/multi_select property
    requires non-empty options: keyword_tags` —— 空 options 的 select/multi_select
    根本建不出列。词表未定前，用 text 存逗号分隔标签（当前恒空，等于零损失），
    待标签词表确定后 update-field 升为 multi_select 并回填。
"""
from __future__ import annotations

import uuid
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from typing import Any

from common import now_iso

# ------------------------------------------------------------------ 列定义
ARTICLE_FIELDS: tuple[str, ...] = (
    "record_id", "title", "account", "account_id", "author", "publish_time",
    "collected_at", "media_type", "collect_layer", "status", "url", "cover_url",
    "video_url", "digest", "body_ref", "body_url", "images_count", "images_ref",
    "videos_count", "videos_ref", "keyword_tags", "word_count", "license",
    "extractor", "fidelity",
    # 分类筛选层（B2）：classify.py 产出，空值时写库自动省略键
    "topic_l1", "topic_l2", "industry", "applicability",
    "classify_conf", "classify_basis", "classify_source",
)

REQUIRED_FIELDS: tuple[str, ...] = (
    "record_id", "title", "url", "collected_at", "media_type",
    "collect_layer", "status", "body_ref", "images_count", "videos_count",
    "license", "extractor", "fidelity",
)
# account 已从必填移除：真实公众号页面存在变体（如部分文章 DOM 不含 #js_name /
# nickname 字面量），账号名无法抽取时不应因此丢弃已抓到的正文。
# account 为描述性元数据，记录身份由 record_id/url 承担，缺失可接受（写库时自动省略空值）。

MEDIA_TYPES: tuple[str, ...] = ("text", "video-meta", "video-file")
COLLECT_LAYERS: tuple[str, ...] = ("url", "account", "desktop", "exe")
LIBRARY_STATUSES: tuple[str, ...] = ("ok", "partial")
TRANSPORT_STATUSES: tuple[str, ...] = ("ok", "partial", "fail")
FIDELITIES: tuple[str, ...] = ("full", "partial")
LICENSE_ATTESTATION = "collector-attestation: authorized-only"

# ---- 分类筛选层（B2，2026-10-31）：字段口径与 scripts/classify.py 的产出对齐 ----
# applicability 与 vault 侧 import-wechat.py 的 APPLICABILITY 同义；none 表示离域不写库。
APPLICABILITIES: tuple[str, ...] = ("direct", "transferable", "unknown", "none")
# classify_source 记录结论来源：auto=tier1 自动 / auto_check=tier2 待核 /
# draft=待人工（默认不写库）/ off_domain=离域拦截 / review=人工复核 / yuandian=元典侧同步。
CLASSIFY_SOURCES: tuple[str, ...] = ("auto", "auto_check", "draft", "off_domain", "review", "yuandian")

# 25 列 -> 平台 PropertyConfig（create-database 一次性建表；add-field 仅用于事后补列）
COLUMN_CONFIGS: tuple[tuple[str, dict[str, Any]], ...] = (
    ("record_id", {"text": ""}),
    ("title", {"text": ""}),
    ("account", {"text": ""}),
    ("account_id", {"text": ""}),
    ("author", {"text": ""}),
    ("publish_time", {"date": {"format": "yyyy-mm-dd hh:mm"}}),
    ("collected_at", {"date": {"format": "yyyy-mm-dd hh:mm"}}),
    ("media_type", {"select": {"options": [{"text": value} for value in MEDIA_TYPES]}}),
    ("collect_layer", {"select": {"options": [{"text": value} for value in COLLECT_LAYERS]}}),
    ("status", {"select": {"options": [{"text": value} for value in LIBRARY_STATUSES]}}),
    ("url", {"text": ""}),
    ("cover_url", {"text": ""}),
    ("video_url", {"text": ""}),
    ("digest", {"text": ""}),
    ("body_ref", {"text": ""}),
    # body_url：正文上传到资料库后的访问 URL（本地路径保留在 body_ref，两者互补，
    # 使记录既知道原始落盘位置、又能直接跳转库内归档副本）
    ("body_url", {"text": ""}),
    ("images_count", {"number": {"decimalPlaces": 0, "useSeparate": False}}),
    ("images_ref", {"text": ""}),
    ("videos_count", {"number": {"decimalPlaces": 0, "useSeparate": False}}),
    ("videos_ref", {"text": ""}),
    ("keyword_tags", {"text": ""}),
    ("word_count", {"number": {"decimalPlaces": 0, "useSeparate": False}}),
    ("license", {"text": ""}),
    ("extractor", {"text": ""}),
    ("fidelity", {"select": {"options": [{"text": value} for value in FIDELITIES]}}),
    # —— 分类筛选层（B2）——
    ("topic_l1", {"text": ""}),
    ("topic_l2", {"text": ""}),
    ("industry", {"text": ""}),
    ("applicability", {"select": {"options": [{"text": value} for value in APPLICABILITIES]}}),
    ("classify_conf", {"number": {"decimalPlaces": 2, "useSeparate": False}}),
    ("classify_basis", {"text": ""}),
    ("classify_source", {"select": {"options": [{"text": value} for value in CLASSIFY_SOURCES]}}),
)

# 去重键只保留这些 query 参数，其余（sn/chksm/utm/scene/src...）一律剥离
_ALLOWED_QUERY_KEYS: tuple[str, ...] = ("__biz", "idx", "mid")


# ------------------------------------------------------------------ URL 规范化
def canonicalize_url(url: str) -> str | None:
    """规范化文章 URL 为去重键；非公众号域名或非法 URL 返回 None。"""
    raw = (url or "").strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = "https://" + raw
    try:
        parts = urlsplit(raw)
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    if not host.endswith("mp.weixin.qq.com"):
        return None
    kept = sorted(
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key in _ALLOWED_QUERY_KEYS
    )
    return urlunsplit(("https", host, parts.path or "/", urlencode(kept), ""))


# ------------------------------------------------------------------ 记录组装
def build_article(
    *,
    title: str,
    url: str,
    collect_layer: str,
    extractor: str,
    account: str = "",
    account_id: str = "",
    author: str = "",
    publish_time: str = "",
    digest: str = "",
    media_type: str = "text",
    cover_url: str | None = None,
    video_url: str | None = None,
    body_ref: str = "",
    body_url: str = "",
    media_ref: str = "",
    images: list[dict] | None = None,
    videos: list[dict] | None = None,
    keyword_tags: list[str] | None = None,
    word_count: int | None = None,
    fidelity: str = "full",
    collected_at: str | None = None,
    record_id: str | None = None,
    # 分类筛选层（B2）：默认空，采集侧不传则写库自动省略这些键
    topic_l1: str = "",
    topic_l2: str = "",
    industry: str = "",
    applicability: str = "",
    classify_conf: float | None = None,
    classify_basis: str = "",
    classify_source: str = "",
) -> dict[str, Any]:
    """组装 25 字段文章记录（传输 JSONL 行格式）。

    record_id 默认由规范化 URL 确定性派生（uuid5），保证重复采集幂等；
    images/videos 为 [{"url":..., "local_path":...}]，其清单文件路径经 media_ref 传入。
    """
    images = images or []
    videos = videos or []
    canonical = canonicalize_url(url) or url
    return {
        "record_id": record_id or str(uuid.uuid5(uuid.NAMESPACE_URL, canonical)),
        "title": (title or "").strip(),
        "account": (account or "").strip(),
        "account_id": (account_id or "").strip(),
        "author": (author or "").strip(),
        "publish_time": publish_time or None,
        "collected_at": collected_at or now_iso(),
        "media_type": media_type,
        "collect_layer": collect_layer,
        "status": "ok",
        "url": canonical,
        "cover_url": cover_url or None,
        "video_url": video_url or None,
        "digest": (digest or "").strip(),
        "body_ref": body_ref,
        "body_url": body_url or None,
        "images_count": len(images),
        "images_ref": (media_ref or None) if images else None,
        "videos_count": len(videos),
        "videos_ref": (media_ref or None) if videos else None,
        "keyword_tags": [str(tag) for tag in (keyword_tags or [])],
        "word_count": word_count,
        "license": LICENSE_ATTESTATION,
        "extractor": extractor,
        "fidelity": fidelity,
        # 分类筛选层（B2）
        "topic_l1": (topic_l1 or "").strip(),
        "topic_l2": (topic_l2 or "").strip(),
        "industry": (industry or "").strip(),
        "applicability": applicability,
        "classify_conf": classify_conf,
        "classify_basis": (classify_basis or "").strip(),
        "classify_source": classify_source,
    }


# ------------------------------------------------------------------ 校验
def validate_article(record: dict[str, Any]) -> tuple[str, list[str]]:
    """校验记录，返回 (status, reasons)。

    必填缺失 / 枚举非法 / URL 非法 -> ("fail", reasons)（写库前过滤，不静默）；
    count>0 但 ref 缺失 -> ("partial", notes)；否则保留调用方 status。
    """
    reasons: list[str] = []
    for field in REQUIRED_FIELDS:
        value = record.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            reasons.append(f"missing required field: {field}")
    if record.get("media_type") not in MEDIA_TYPES:
        reasons.append(f"invalid media_type: {record.get('media_type')!r}")
    if record.get("collect_layer") not in COLLECT_LAYERS:
        reasons.append(f"invalid collect_layer: {record.get('collect_layer')!r}")
    if record.get("fidelity") not in FIDELITIES:
        reasons.append(f"invalid fidelity: {record.get('fidelity')!r}")
    if canonicalize_url(record.get("url", "")) is None:
        reasons.append(f"invalid url: {record.get('url')!r}")
    if reasons:
        return "fail", reasons

    notes: list[str] = []
    if record.get("images_count") and not record.get("images_ref"):
        notes.append("images_count>0 但 images_ref 为空")
    if record.get("videos_count") and not record.get("videos_ref"):
        notes.append("videos_count>0 但 videos_ref 为空")
    if notes:
        return "partial", notes
    return str(record.get("status") or "ok"), []


# ------------------------------------------------------------------ 写库值映射
def to_property_values(record: dict[str, Any]) -> dict[str, Any]:
    """25 字段记录 -> batch-add-records 的 records 元素（map<字段名, PropertyValue>）。

    None / 空串值省略（服务端留空）；PropertyValue 为 oneof 结构，禁写 null。
    """
    values: dict[str, Any] = {}

    def put(field: str, type_key: str, raw: Any) -> None:
        """None / 空串 / 空列表一律省略该键（PropertyValue 是 oneof，禁写 null）。"""
        if raw is None:
            return
        if isinstance(raw, str) and raw == "":
            return
        if isinstance(raw, (list, tuple)) and not raw:
            return
        values[field] = {type_key: raw}

    put("record_id", "text", record.get("record_id"))
    put("title", "text", record.get("title"))
    put("account", "text", record.get("account"))
    put("account_id", "text", record.get("account_id"))
    put("author", "text", record.get("author"))
    put("publish_time", "date", record.get("publish_time"))
    put("collected_at", "date", record.get("collected_at"))
    put("media_type", "select", record.get("media_type"))
    put("collect_layer", "select", record.get("collect_layer"))
    put("status", "select", record.get("status"))
    put("url", "text", record.get("url"))
    put("cover_url", "text", record.get("cover_url"))
    put("video_url", "text", record.get("video_url"))
    put("digest", "text", record.get("digest"))
    put("body_ref", "text", record.get("body_ref"))
    put("body_url", "text", record.get("body_url"))
    put("images_count", "number", int(record.get("images_count") or 0))
    put("images_ref", "text", record.get("images_ref"))
    put("videos_count", "number", int(record.get("videos_count") or 0))
    put("videos_ref", "text", record.get("videos_ref"))
    tags = [str(tag) for tag in (record.get("keyword_tags") or []) if str(tag).strip()]
    put("keyword_tags", "text", ",".join(tags))
    put("word_count", "number", record.get("word_count"))
    put("license", "text", record.get("license"))
    put("extractor", "text", record.get("extractor"))
    put("fidelity", "select", record.get("fidelity"))
    # 分类筛选层（B2）：空值 put 自动省略 → 复用 25 列旧表也不会因未知列报错
    put("topic_l1", "text", record.get("topic_l1"))
    put("topic_l2", "text", record.get("topic_l2"))
    put("industry", "text", record.get("industry"))
    put("applicability", "select", record.get("applicability"))
    put("classify_conf", "number", record.get("classify_conf"))
    put("classify_basis", "text", record.get("classify_basis"))
    put("classify_source", "select", record.get("classify_source"))
    return values
