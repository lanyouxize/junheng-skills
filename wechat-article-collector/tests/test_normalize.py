#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""normalize.py 单元测试：URL 规范化/记录组装/校验/PropertyValue 映射。"""
from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from normalize import (  # noqa: E402
    ARTICLE_FIELDS,
    COLUMN_CONFIGS,
    build_article,
    canonicalize_url,
    to_property_values,
    validate_article,
)


class TestCanonicalizeUrl(unittest.TestCase):
    def test_strips_tracking_params_keeps_biz_mid_idx(self) -> None:
        url = "https://mp.weixin.qq.com/s/AbCdEf?scene=123&src=11&sn=xyz&chksm=abc&__biz=MzA4&mid=265&idx=1&utm_source=wx"
        self.assertEqual(
            canonicalize_url(url),
            "https://mp.weixin.qq.com/s/AbCdEf?__biz=MzA4&idx=1&mid=265",
        )

    def test_scheme_less_input_upgraded(self) -> None:
        self.assertEqual(
            canonicalize_url("mp.weixin.qq.com/s/AbCdEf"),
            "https://mp.weixin.qq.com/s/AbCdEf",
        )

    def test_non_wechat_host_rejected(self) -> None:
        self.assertIsNone(canonicalize_url("https://example.com/s/1"))

    def test_empty_rejected(self) -> None:
        self.assertIsNone(canonicalize_url("  "))

    def test_spoof_host_rejected(self) -> None:
        self.assertIsNone(canonicalize_url("https://mp.weixin.qq.com.evil.com/s/1"))


class TestBuildArticle(unittest.TestCase):
    def test_record_id_deterministic_by_url(self) -> None:
        url = "https://mp.weixin.qq.com/s/Dup1"
        first = build_article(title="T", url=url, collect_layer="url", extractor="t", account="A", body_ref="b.html")
        second = build_article(title="T", url=url, collect_layer="url", extractor="t", account="A", body_ref="b.html")
        self.assertEqual(first["record_id"], second["record_id"])
        self.assertEqual(first["record_id"], str(uuid.uuid5(uuid.NAMESPACE_URL, url)))

    def test_all_25_fields_present(self) -> None:
        record = build_article(title="T", url="https://mp.weixin.qq.com/s/X1", collect_layer="url", extractor="t", account="A", body_ref="b.html")
        self.assertEqual(tuple(record.keys()), ARTICLE_FIELDS)

    def test_media_refs_null_when_no_media(self) -> None:
        record = build_article(title="T", url="https://mp.weixin.qq.com/s/X2", collect_layer="url", extractor="t", account="A", body_ref="b.html")
        self.assertEqual(record["images_count"], 0)
        self.assertIsNone(record["images_ref"])
        self.assertIsNone(record["videos_ref"])

    def test_media_refs_set_when_media_present(self) -> None:
        images = [{"url": "https://mmbiz.qpic.cn/a.png", "local_path": "a.png"}]
        record = build_article(
            title="T", url="https://mp.weixin.qq.com/s/X3", collect_layer="url", extractor="t",
            account="A", body_ref="b.html", media_ref="m.json", images=images,
        )
        self.assertEqual(record["images_count"], 1)
        self.assertEqual(record["images_ref"], "m.json")

    def test_license_attestation_fixed(self) -> None:
        record = build_article(title="T", url="https://mp.weixin.qq.com/s/X4", collect_layer="url", extractor="t", account="A", body_ref="b.html")
        self.assertEqual(record["license"], "collector-attestation: authorized-only")


class TestValidateArticle(unittest.TestCase):
    def _valid(self) -> dict:
        return build_article(title="T", url="https://mp.weixin.qq.com/s/V1", collect_layer="url", extractor="t", account="A", body_ref="b.html")

    def test_ok(self) -> None:
        status, reasons = validate_article(self._valid())
        self.assertEqual(status, "ok")
        self.assertEqual(reasons, [])

    def test_fail_on_missing_title(self) -> None:
        record = self._valid()
        record["title"] = ""
        status, reasons = validate_article(record)
        self.assertEqual(status, "fail")
        self.assertTrue(any("title" in r for r in reasons))

    def test_fail_on_invalid_url(self) -> None:
        record = self._valid()
        record["url"] = "https://evil.com/s/1"
        status, reasons = validate_article(record)
        self.assertEqual(status, "fail")
        self.assertTrue(any("url" in r for r in reasons))

    def test_fail_on_bad_enum(self) -> None:
        record = self._valid()
        record["media_type"] = "audio"
        status, _ = validate_article(record)
        self.assertEqual(status, "fail")

    def test_partial_when_count_without_ref(self) -> None:
        record = self._valid()
        record["images_count"] = 3
        record["images_ref"] = None
        status, notes = validate_article(record)
        self.assertEqual(status, "partial")
        self.assertTrue(notes)


class TestToPropertyValues(unittest.TestCase):
    def test_mapping_shapes_and_omissions(self) -> None:
        record = build_article(
            title="标题", url="https://mp.weixin.qq.com/s/P1", collect_layer="account",
            extractor="l2:profile_ext", account="号", account_id="biz1", author="作者",
            publish_time="2024-10-22T08:00:00Z", digest="摘要", media_type="video-meta",
            cover_url="https://mmbiz.qpic.cn/c.jpg", video_url="https://v.qq.com/x",
            body_ref="b.html", media_ref="m.json",
            images=[{"url": "u", "local_path": "l"}],
            videos=[{"url": "v", "local_path": "lv"}],
            keyword_tags=["排毛", "膳食纤维"], word_count=120,
        )
        values = to_property_values(record)
        self.assertEqual(values["title"], {"text": "标题"})
        self.assertEqual(values["publish_time"], {"date": "2024-10-22T08:00:00Z"})
        self.assertEqual(values["media_type"], {"select": "video-meta"})
        self.assertEqual(values["collect_layer"], {"select": "account"})
        self.assertEqual(values["images_count"], {"number": 1})
        self.assertEqual(values["keyword_tags"], {"text": "排毛,膳食纤维"})
        self.assertEqual(values["word_count"], {"number": 120})
        for key, value in values.items():
            self.assertIsNotNone(value, key)
            self.assertNotIn(None, value.values(), key)

    def test_null_optional_fields_omitted(self) -> None:
        record = build_article(title="T", url="https://mp.weixin.qq.com/s/P2", collect_layer="url", extractor="t", account="A", body_ref="b.html")
        values = to_property_values(record)
        for omitted in ("account_id", "author", "publish_time", "digest", "cover_url", "video_url", "images_ref", "videos_ref", "keyword_tags", "word_count"):
            self.assertNotIn(omitted, values)
        self.assertEqual(values["images_count"], {"number": 0})
        self.assertEqual(values["status"], {"select": "ok"})

    def test_classification_fields_mapped(self) -> None:
        """B2：classify.py 产出 7 列按 oneof 正确映射。"""
        record = build_article(title="T", url="https://mp.weixin.qq.com/s/P3", collect_layer="url",
                               extractor="t", body_ref="b.html", topic_l1="A", topic_l2="A3",
                               industry="CROSS", applicability="direct", classify_conf=0.88,
                               classify_basis="[自动] 命中 防腐剂（标题）", classify_source="auto")
        values = to_property_values(record)
        self.assertEqual(values["topic_l1"], {"text": "A"})
        self.assertEqual(values["topic_l2"], {"text": "A3"})
        self.assertEqual(values["industry"], {"text": "CROSS"})
        self.assertEqual(values["applicability"], {"select": "direct"})
        self.assertEqual(values["classify_conf"], {"number": 0.88})
        self.assertEqual(values["classify_source"], {"select": "auto"})

    def test_classification_fields_omitted_when_empty(self) -> None:
        """B2：未分类（采集侧未跑 classify）时，7 列全部省略，复用旧表不报未知列。"""
        record = build_article(title="T", url="https://mp.weixin.qq.com/s/P4", collect_layer="url", extractor="t", body_ref="b.html")
        values = to_property_values(record)
        for omitted in ("topic_l1", "topic_l2", "industry", "applicability",
                        "classify_conf", "classify_basis", "classify_source"):
            self.assertNotIn(omitted, values)


class TestColumnConfigs(unittest.TestCase):
    def test_columns_aligned_with_fields(self) -> None:
        # 2026-10-31 B2：25 -> 32，新增 classification 7 列（topic_l1/topic_l2/
        # industry/applicability/classify_conf/classify_basis/classify_source）
        self.assertEqual(len(COLUMN_CONFIGS), 32)
        self.assertEqual(tuple(name for name, _ in COLUMN_CONFIGS), ARTICLE_FIELDS)

    def test_select_columns_carry_options(self) -> None:
        configs = dict(COLUMN_CONFIGS)
        for column in ("media_type", "collect_layer", "status", "fidelity",
                       "applicability", "classify_source"):
            self.assertIn("select", configs[column])
            self.assertTrue(configs[column]["select"]["options"])

    def test_no_select_column_has_empty_options(self) -> None:
        """服务端契约：select/multi_select 的 options 必须非空，否则建表直接拒绝。

        真机实测（2026-10-22 V2）：`keyword_tags` 原设计为 multi_select + options=[]
        -> `code=11607 ... requires non-empty options: keyword_tags`，整张表都建不出来。
        该用例锁死"任何 select/multi_select 列都必须带非空 options"。
        """
        for name, config in COLUMN_CONFIGS:
            for type_key in ("select", "multi_select"):
                if type_key in config:
                    self.assertTrue(
                        config[type_key].get("options"),
                        f"{name} 是 {type_key} 但 options 为空 -> 建表会被服务端拒绝(11607)",
                    )


if __name__ == "__main__":
    unittest.main()
