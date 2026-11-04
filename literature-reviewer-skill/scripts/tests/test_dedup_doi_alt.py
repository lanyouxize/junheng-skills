#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""合并成员 DOI 留痕（P26/A，2026-10-20）

本文件守护「被合并掉的那条文献的 DOI 不得消失」。

背景：字段补全规则是「胜者已有非空值就不覆盖」，于是同一篇的预印本 /
期刊版 / 学位版（DOI 各不相同）合并后**只剩胜者一个 DOI**，成员 DOI 永久丢失。
实测泌尿交付 1 257 条里 25 组全部失联，事后只能拿题名去反搜。

为什么必须有行为测试而不能只靠交付物校验器：
`verify_v12` 的 V15 断言的是「JSON 里的 doi_alt 必须都能在 清单.md 第 5 节看到」。
若有人把 `_merge_into` 里的收集逻辑整段删掉，JSON 里就没有 doi_alt，
V15 变成「空集 == 空集」照样 PASS —— **判据守的是两边一致，不是功能存在**。
功能存在必须由本文件守。

断言方向：
* COLLECT —— 两侧 DOI 不同时必须收集成员侧
* NO-OP   —— 胜者原本无 DOI 时，成员 DOI 会成为胜者 DOI，**不应**再进 doi_alt
* CHAIN   —— 多级合并要累积，且同输入必须同序（幂等）

运行：

    cd <skill>/scripts && python -m unittest tests.test_dedup_doi_alt -v
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)

import deduplicate_papers as dp  # noqa: E402

# 完全相同的题名：确保一定能走到合并分支（不取决于相似度是否刚好卡线）
TITLE = "Urolithiasis in cats: a retrospective study of struvite and oxalate stones"


def _mk(pid, doi, title=TITLE):
    return {"id": pid, "title": title, "doi": doi}


class TestDoiAltCollect(unittest.TestCase):
    """COLLECT：两侧 DOI 不同，成员 DOI 必须落进 doi_alt。"""

    def test_preprint_and_journal_version(self):
        """预印本 + 期刊版，合并后成员 DOI 可追溯。"""
        papers = [_mk("A1", "10.1000/journal.2024.001"),
                  _mk("B1", "10.21203/rs.3.rs-123456/v1")]
        unique, removed = dp.deduplicate_papers(papers)
        self.assertEqual(len(unique), 1, "同题名应合并为 1 条")
        self.assertEqual(len(removed), 1)
        got = unique[0].get("doi_alt")
        self.assertEqual(got, ["10.21203/rs.3.rs-123456/v1"],
                         "成员 DOI 未留痕：%r" % (got,))
        # 胜者自己的 DOI 不能被写进 alt
        self.assertNotIn(unique[0]["doi"], got)

    def test_alt_never_contains_own_doi(self):
        """成员 DOI 与胜者相同 → 不产生 doi_alt（同一条被两个源重复收录）。"""
        papers = [_mk("A1", "10.1000/same.001"), _mk("B1", "10.1000/same.001")]
        unique, _ = dp.deduplicate_papers(papers)
        self.assertEqual(len(unique), 1)
        self.assertIsNone(unique[0].get("doi_alt"),
                          "重复收集了胜者自己的 DOI：%r" % (unique[0].get("doi_alt"),))


class TestDoiAltNoOp(unittest.TestCase):
    """NO-OP：胜者原本没 DOI 时，成员 DOI 会成为胜者 DOI，不该再进 alt。"""

    def test_winner_without_doi_inherits(self):
        papers = [_mk("A1", ""), _mk("B1", "10.1000/only.001")]
        unique, _ = dp.deduplicate_papers(papers)
        self.assertEqual(len(unique), 1)
        # A1 排序在前为胜者，DOI 由字段补全从 B1 继承
        self.assertEqual(unique[0]["doi"], "10.1000/only.001")
        self.assertIsNone(unique[0].get("doi_alt"),
                          "继承来的 DOI 被重复计入 alt：%r" % (unique[0].get("doi_alt"),))


class TestDoiAltChain(unittest.TestCase):
    """CHAIN：三级合并要累积，且同输入必须同序（幂等）。"""

    def test_three_versions_accumulate(self):
        dois = ["10.1000/v1", "10.2000/v2", "10.3000/v3"]
        papers = [_mk("A%d" % (i + 1), d) for i, d in enumerate(dois)]
        unique, _ = dp.deduplicate_papers(papers)
        self.assertEqual(len(unique), 1, "三条同题名应并成 1 条")
        alt = unique[0].get("doi_alt") or []
        winner_doi = unique[0]["doi"]
        self.assertEqual(len(alt), 2, "成员 DOI 应恰好 2 个：%r" % (alt,))
        self.assertEqual(set(alt), set(dois) - {winner_doi})

    def test_order_is_deterministic(self):
        """同输入跑两次，doi_alt 必须逐位相同（否则交付物字节不稳定）。"""
        papers = [_mk("A%d" % (i + 1), "10.%d000/v%d" % (i, i)) for i in range(4)]
        first = dp.deduplicate_papers(papers)[0][0].get("doi_alt")
        second = dp.deduplicate_papers(papers)[0][0].get("doi_alt")
        self.assertEqual(first, second, "doi_alt 顺序不稳定：%r vs %r" % (first, second))


class TestDoiAltPublicApi(unittest.TestCase):
    """公开 API `merge_papers` 也必须带这个行为（它有别的调用方）。"""

    def test_merge_papers_keeps_alt(self):
        winner = {"id": "W", "title": TITLE, "doi": "10.1000/w"}
        loser = {"id": "L", "title": TITLE, "doi": "10.1000/l"}
        merged = dp.merge_papers(winner, loser)
        self.assertEqual(merged.get("doi_alt"), ["10.1000/l"])
        self.assertIn("L", merged.get("merged_from") or [])
        # 入参不得被修改（深拷贝契约）
        self.assertNotIn("doi_alt", winner)
        self.assertNotIn("doi_alt", loser)


if __name__ == "__main__":
    unittest.main(verbosity=2)
