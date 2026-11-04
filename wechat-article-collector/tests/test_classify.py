#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""classify.py 的离线单测：钉住鉴汇3.0 的打分与闸门判据，不启 GUI、不写库。

运行：python -m unittest tests/test_classify.py -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import classify  # noqa: E402


class TestLoadRules(unittest.TestCase):
    def test_rules_non_empty(self):
        rs = classify.load_rules()
        self.assertGreater(len(rs["rules"]), 40, "rules 应覆盖全部 L2 类目")
        self.assertIsInstance(rs["negatives"], list)
        self.assertIn("levels", rs["tax"])
        self.assertIn("off_domain_blacklist", rs["tax"])

    def test_missing_rules_raises(self):
        with self.assertRaises((OSError, ValueError)):
            classify.load_rules("/nonexistent/tax.json", "/nonexistent/kw.json")


class TestTierGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rs = classify.load_rules()

    def test_tier1_two_title_keywords(self):
        """标题命中≥2 个不同词且 conf 足够 → 自动采纳(tier1)，归 A1。"""
        r = classify.classify_article({"record_id": "t1", "title": "乳化剂与表面活性剂选型",
                                       "digest": "", "body_ref": ""}, self.rs)
        self.assertEqual(r["tier"], 1, r)
        self.assertEqual(r["l2"], "A1", r)
        self.assertEqual(r["l1"], "A")
        self.assertGreaterEqual(r["title_keyword_hits"], 2)
        self.assertIn("乳化剂", r["tags"])
        self.assertEqual(r["classify_source"], "auto")

    def test_tier2_single_keyword_dominance(self):
        """标题仅 1 词但甩开次选 → 入库但标待核(tier2)。"""
        r = classify.classify_article({"record_id": "t2", "title": "山梨酸钾",
                                       "digest": "", "body_ref": ""}, self.rs)
        self.assertEqual(r["tier"], 2, r)
        self.assertEqual(r["l2"], "A3", r)
        self.assertEqual(r["classify_source"], "auto_check")

    def test_tier0_no_match(self):
        """无关键词命中 → 待人工(tier0)，不静默丢弃。"""
        r = classify.classify_article({"record_id": "t3", "title": "今天天气不错",
                                       "digest": "", "body_ref": ""}, self.rs)
        self.assertEqual(r["tier"], 0, r)
        self.assertEqual(r["l2"], "")
        self.assertEqual(r["classify_source"], "draft")

    def test_off_domain_blocked(self):
        """命中离域黑名单 → tier=None（调用方不写库），且留原因。"""
        r = classify.classify_article({"record_id": "t4", "title": "医疗器械注册与化妆品监管新规",
                                       "digest": "", "body_ref": ""}, self.rs)
        self.assertIsNone(r["tier"], r)
        self.assertTrue(r["off_domain"])
        self.assertEqual(r["applicability"], "none")
        self.assertEqual(r["classify_source"], "off_domain")

    def test_shape_skip_undoes_auto(self):
        """非纯文本形态：本来会自动采纳，也要撤销转人工，并记 shape_skip。"""
        r = classify.classify_article({"record_id": "t5", "title": "乳化剂与表面活性剂选型",
                                       "digest": "", "body_ref": "",
                                       "content_shape": "video"}, self.rs)
        self.assertEqual(r["tier"], 0, r)
        self.assertEqual(r["shape_skip"], "video")

    def test_industry_axis(self):
        """A 类 → CROSS 行业轴。"""
        r = classify.classify_article({"record_id": "t6", "title": "乳化剂与表面活性剂选型",
                                       "digest": "", "body_ref": ""}, self.rs)
        self.assertIn("CROSS", r["industry"])

    def test_classify_many_keeps_record_id(self):
        arts = [{"record_id": "x1", "title": "乳化剂与表面活性剂选型"},
                {"record_id": "x2", "title": "今天天气不错"}]
        out = classify.classify_many(arts, self.rs)
        self.assertEqual([o["record_id"] for o in out], ["x1", "x2"])


class TestScoringHelpers(unittest.TestCase):
    def test_confidence_monotonic_and_capped(self):
        low = classify.confidence_of([{"score": 1.0}])
        high = classify.confidence_of([{"score": 10.0}])
        self.assertLessEqual(low, high)
        self.assertLessEqual(high, 0.92)

    def test_dominance_no_second(self):
        self.assertEqual(classify.dominance([{"score": 5.0}]), 99.0)

    def test_l1_of_unknown(self):
        rs = classify.load_rules()
        self.assertEqual(classify.l1_of(rs["tax"], "ZZ9"), ("", "", ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
