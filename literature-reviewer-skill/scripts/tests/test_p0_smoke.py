#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P0 冒烟测试（零第三方依赖，``python -m unittest`` 直接跑）

覆盖「优化方案 2026-10-18」第 1 批 A 档的五项 P0：

* P0-1 文献类型标识不再硬编码 ``[J]``
* P0-2 去重结果与输入顺序无关（全排列验证）+ 幂等
* P0-3 ``authors`` 误传字符串时按单作者处理，不再逐字符迭代
* P0-4 ``title=None`` 不再崩溃
* P0-5 去重替换时合并非空字段，败者元数据不丢

运行：:

    cd <skill>/scripts && python -m unittest discover -s tests -v
"""

import itertools
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)

import citation_formatter as cf  # noqa: E402
import deduplicate_papers as dp  # noqa: E402


class TestP01DocType(unittest.TestCase):
    """P0-1：类型标识按 doc_type 输出，缺省回落 [J] 且只告警一次。"""

    def setUp(self):
        cf._warned_missing_doc_type = False

    def test_journal_default_and_warning_once(self):
        paper = {
            "id": "E99", "title": "Some paper", "authors": ["Smith J"],
            "journal": "J Anim Sci", "year": 2020, "volume": "98", "issue": "3", "pages": "1-9",
        }
        out = cf.format_citation_gb7714(paper, "E99")
        self.assertIn("[J]", out)
        self.assertTrue(cf._warned_missing_doc_type, "缺省 doc_type 必须告警，不能静默")

    def test_book_and_preprint(self):
        book = {
            "id": "E17", "doc_type": "M", "title": "Grasses and Grassland",
            "authors": ["Dann J R"], "place": "London", "publisher": "IntechOpen",
            "year": 2021, "pages": "1-18",
        }
        out = cf.format_citation_gb7714(book, "E17")
        self.assertIn("[M]", out)
        self.assertIn("London: IntechOpen", out)
        self.assertIn("2021: 1-18", out)
        self.assertNotIn("[J]", out)

        preprint = {
            "id": "E1", "doc_type": "PP", "title": "Preprint title", "authors": ["Smith J"],
            "year": 2023, "source_url": "https://zenodo.org/record/1", "access_date": "2026-10-18",
        }
        out = cf.format_citation_gb7714(preprint, "E1")
        self.assertIn("[PP/OL]", out)
        self.assertIn("[引用日期: 2026-10-18]", out)

    def test_illegal_doc_type_raises(self):
        with self.assertRaises(ValueError):
            cf.format_citation_gb7714(
                {"id": "X1", "doc_type": "Journal", "title": "t", "authors": ["A B"]}, "X1"
            )

    def test_book_chapter_uses_double_slash(self):
        """书籍章节按 GB/T 用 ``//`` 引出专著题名，书名校名不丢。"""
        out = cf.format_citation_gb7714(
            {"id": "E7", "doc_type": "M", "title": "Trichobezoars", "authors": ["Wexler-Mitchell E"],
             "book_title": "The Feline Patient", "publisher": "Wiley", "year": 2025, "pages": "82-84"}, "E7"
        )
        self.assertIn("Trichobezoars[M]//The Feline Patient.", out)
        self.assertIn("Wiley, 2025: 82-84", out)

    def test_journal_not_auto_ol(self):
        """有 source_url 的期刊条目**不**自动变 [J/OL]（避免批量改写 45 条合规条目）。"""
        out = cf.format_citation_gb7714(
            {"id": "E2", "doc_type": "J", "title": "t", "authors": ["A B"],
             "journal": "Nature", "year": 2020, "source_url": "https://example.org/x"}, "E2"
        )
        self.assertIn("[J]", out)
        self.assertNotIn("[J/OL]", out)


class TestP02P05Dedup(unittest.TestCase):
    """P0-2 顺序无关 + P0-5 字段合并。"""

    def _papers(self):
        return [
            {"id": "E1", "title": "Hairball control with Miscanthus grass in cats",
             "doi": "10.2527/asasann.2017.236", "journal": "J Anim Sci", "year": 2017},
            {"id": "C9", "title": "Hairball control with Miscanthus grass in cats",
             "doi": "", "abstract": "CNKI 版摘要", "volume": "95", "issue": "4"},
            {"id": "E2", "title": "Dietary fibre and feline hairball", "doi": "10.1/xyz"},
            {"id": "E3", "title": "Unrelated topic about dogs", "doi": ""},
        ]

    def test_order_independent_over_all_permutations(self):
        papers = self._papers()
        baseline = None
        for perm in itertools.permutations(papers, len(papers)):
            unique, removed = dp.deduplicate_papers(list(perm))
            sig = (sorted(p["id"] for p in unique), len(unique), len(removed))
            if baseline is None:
                baseline = sig
            self.assertEqual(sig, baseline, "去重结果随输入顺序变化：%r" % (sig,))
        self.assertEqual(baseline[0], ["E1", "E2", "E3"])

    def test_merge_keeps_loser_metadata(self):
        unique, removed = dp.deduplicate_papers(self._papers())
        winner = next(p for p in unique if p["id"] == "E1")
        self.assertEqual(len(removed), 1)
        self.assertEqual(winner.get("abstract"), "CNKI 版摘要", "败者 abstract 必须并入胜者")
        self.assertEqual(winner.get("volume"), "95")
        self.assertEqual(winner.get("merged_from"), ["C9"])

    def test_idempotent(self):
        papers = self._papers()
        once, _ = dp.deduplicate_papers(papers)
        twice, removed2 = dp.deduplicate_papers(once)
        self.assertEqual([p["id"] for p in once], [p["id"] for p in twice])
        self.assertEqual(removed2, [])


class TestP03P04InputRobustness(unittest.TestCase):
    """P0-3 类型错误不产垃圾；P0-4 title=None 不崩溃。"""

    def test_authors_as_string(self):
        self.assertEqual(cf.format_authors("Smith J"), "Smith J")
        self.assertEqual(cf.format_authors("Smith J", "en"), "Smith J")
        self.assertNotIn("S, m, i", cf.format_authors("Smith J"))

    def test_authors_bad_type_raises(self):
        with self.assertRaises(TypeError):
            cf.format_authors(42)

    def test_title_none(self):
        unique, _ = dp.deduplicate_papers([{"id": "X1", "title": None, "doi": ""}])
        self.assertEqual([p["id"] for p in unique], ["X1"])
        out = cf.format_citation_gb7714({"id": "X1", "title": None, "authors": None}, "X1")
        self.assertIn("[J]", out)

    def test_non_dict_entry_raises(self):
        with self.assertRaises(TypeError):
            dp.deduplicate_papers(["not a dict"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
