#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""去重令牌否决 + 相关性优先胜者（2026-10-19）

本文件守护「文献去重不得合并两篇不同文献」这条底线。

背景：泌尿语料 1 121 条全量回溯发现，标题相似度 0.75 阈值对「模板高度相似但
差一个关键实词」的题名毫无防御力 —— 实测 21 组高分被低分代表吞掉，其中包含
`sodium chloride` vs `potassium chloride`（0.932）、`Female Cat` vs `male cat`
（0.917）这类明确不同的文献。抽检发现的 4 组已固化为 DENY 用例。

三条断言方向：
* DENY   —— 必须**不**合并（错杀一篇文献，比多留一条重复严重）
* MERGE  —— 必须合并（措辞差异、记录类型相同）
* RANK   —— 胜者必须取相关性高者，且合并关系必须可追溯

每个 DENY 用例都附带「相似度必须 ≥ 阈值」的前置断言：若哪天用例被改成
相似度本来就不达标的题名，断言会先失败，避免测试空转（看似绿、实则没测到）。

运行：:

    cd <skill>/scripts && python -m unittest tests.test_dedup_token_veto -v
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)

import deduplicate_papers as dp  # noqa: E402

THRESHOLD = 0.75


def _mk(pid, title, **extra):
    return dict({"id": pid, "title": title, "doi": ""}, **extra)


def _merged_ids(papers, threshold=THRESHOLD):
    """返回 (保留条数, 被合并掉的 id 集合)。"""
    unique, removed = dp.deduplicate_papers(papers, title_similarity_threshold=threshold)
    return len(unique), {p["id"] for p in removed}


class TestTokenVetoDeny(unittest.TestCase):
    """必须**不合并**：只差一个关键实词的题名。"""

    def _assert_kept_separate(self, a, b, expect_reason=None):
        # 前置：该用例必须落在「相似度已达标」的危险区，否则测不到否决层
        self.assertGreaterEqual(
            dp.calculate_similarity(a, b), THRESHOLD,
            "用例相似度未达阈值，无法验证否决层：\n  A=%s\n  B=%s" % (a, b),
        )
        reason = dp.veto_reason(a, b)
        self.assertIsNotNone(reason, "规则层未否决：\n  A=%s\n  B=%s" % (a, b))
        if expect_reason:
            self.assertIn(expect_reason, reason)

        n, merged = _merged_ids([_mk("A1", a, abstract="abs-a"), _mk("B1", b, abstract="abs-b")])
        self.assertEqual(n, 2, "两条不同文献被端到端合并：\n  A=%s\n  B=%s" % (a, b))
        self.assertEqual(merged, set())

    def test_sodium_vs_potassium_chloride(self):
        """两种不同的盐 —— 实测 0.932，被旧阈值判为重复。"""
        self._assert_kept_separate(
            "Effect of dietary sodium chloride on urinary calcium in cats",
            "Effect of dietary potassium chloride on urinary calcium in cats",
            "替换关系",
        )

    def test_male_vs_female_cat(self):
        """性别不同即不同研究 —— 实测 0.917。"""
        self._assert_kept_separate(
            "Urethral obstruction in the male cat: diagnosis and management",
            "Urethral obstruction in a female cat: diagnosis and management",
            "替换关系",
        )

    def test_country_difference(self):
        """不同国家的流行病学调查。"""
        self._assert_kept_separate(
            "Clinicopathological characteristics of cats with obstructive lower urinary "
            "tract disease in the Czech Republic",
            "Clinicopathological characteristics of cats with obstructive lower urinary "
            "tract disease in Turkey Aydin province",
            "替换关系",
        )

    def test_part_one_vs_part_two_roman(self):
        """分册编号（罗马数字）不同 —— 同一模板、只差结尾，相似度极高。"""
        self._assert_kept_separate(
            "Approach to urethral obstruction in cats: part I",
            "Approach to urethral obstruction in cats: part II",
            "替换关系",
        )

    def test_part_digit_veto(self):
        """阿拉伯数字分册：相似度可能低于阈值，但规则层必须给出数字否决理由。"""
        a = ("Approach to urethral obstruction in cats. part 1: presentation and stabilisation")
        b = ("Approach to urethral obstruction in cats. part 2: catheterising and "
             "postobstruction management")
        reason = dp.veto_reason(a, b)
        self.assertIsNotNone(reason, "数字分册未被否决")
        self.assertIn("数字差异", reason)
        n, _ = _merged_ids([_mk("A1", a), _mk("B1", b)])
        self.assertEqual(n, 2)


class TestTokenVetoRecordType(unittest.TestCase):
    """评论 / 勘误是独立记录，与原文不得合并。"""

    def test_letter_regarding_is_separate(self):
        a = "Benign ureteral obstruction in cats: outcome with medical management"
        b = ("Letter regarding benign ureteral obstruction in cats: outcome with medical "
             "management")
        self.assertGreaterEqual(dp.calculate_similarity(a, b), THRESHOLD)
        self.assertIn("记录类型", dp.veto_reason(a, b) or "")
        n, _ = _merged_ids([_mk("A1", a), _mk("B1", b)])
        self.assertEqual(n, 2, "letter 与原文被合并")

    def test_corrigendum_is_separate(self):
        a = "Beneficial effects of a prescription home-prepared diet on urine calcium"
        b = ("Corrigendum to beneficial effects of a prescription home-prepared diet on "
             "urine calcium")
        self.assertGreaterEqual(dp.calculate_similarity(a, b), THRESHOLD)
        self.assertIn("记录类型", dp.veto_reason(a, b) or "")
        n, _ = _merged_ids([_mk("A1", a), _mk("B1", b)])
        self.assertEqual(n, 2, "勘误与原文被合并")


class TestShortGenericTitle(unittest.TestCase):
    """通用短题名（How to… / index）只按 DOI 判重。"""

    def test_short_generic_title_only_by_doi(self):
        """`How to…` 这类通用短题名：同题不同 DOI 属两篇不同文章，不得合并。

        实测同一期刊的两篇 `How to…`（DOI ...1114.14 与 ...0110.12）被并成一条。
        """
        a, b = "How to…", "How to…"
        self.assertEqual(dp.calculate_similarity(a, b), 1.0)
        self.assertIn("题名过短", dp.veto_reason(a, b) or "")
        unique, _ = dp.deduplicate_papers([
            _mk("H1", a, doi="10.22233/20412495.1114.14"),
            _mk("H2", b, doi="10.22233/20412495.0110.12"),
        ])
        self.assertEqual(len(unique), 2, "两篇同名短文被合并")

    def test_short_title_same_doi_still_merges(self):
        """同题短题名但 DOI 相同 → 靠 DOI 精确合并，不受短题名规则影响。"""
        unique, _ = dp.deduplicate_papers([
            _mk("H1", "How to…", doi="10.22233/20412495.1114.14"),
            _mk("H2", "How to…", doi="10.22233/20412495.1114.14"),
        ])
        self.assertEqual(len(unique), 1)


class TestTokenVetoMerge(unittest.TestCase):
    """必须**合并**：真重复与纯措辞差异。改造不得把这类也否决掉。"""

    def _assert_merged(self, a, b):
        self.assertIsNone(dp.veto_reason(a, b), "不应否决：\n  A=%s\n  B=%s" % (a, b))
        n, merged = _merged_ids([_mk("A1", a), _mk("B1", b)])
        self.assertEqual(n, 1, "同一篇被拆成两条：\n  A=%s\n  B=%s" % (a, b))

    def test_identical_title(self):
        self._assert_merged(
            "Serum cytokine profiling in cats with acute idiopathic cystitis",
            "Serum cytokine profiling in cats with acute idiopathic cystitis",
        )

    def test_meta_word_addition(self):
        """单侧增补 `evaluation for` 不改变研究对象 —— 实测同一篇。"""
        self._assert_merged(
            "Association between urolithiasis and chronic kidney disease in cats",
            "Evaluation for association between urolithiasis and chronic kidney disease in cats",
        )

    def test_plural_and_prefix_tolerance(self):
        """cats/cat、toward/towards 属词形差异，不应否决。"""
        self._assert_merged(
            "Risk factors for struvite urolithiasis in cat",
            "Risk factors for struvite urolithiasis in cats",
        )

    def test_hyphenation_variant(self):
        """连字符写法差异（anti-urolithiatic / antiurolithiatic）不算不同文献。"""
        self._assert_merged(
            "Anti-urolithiatic effect of a polyherbal formulation in cats",
            "Antiurolithiatic effect of a polyherbal formulation in cats",
        )


class TestRelevanceWins(unittest.TestCase):
    """胜者必须取相关性高者，而非元数据最全者。"""

    def test_higher_relevance_wins(self):
        papers = [
            # 元数据齐全但相关性低
            {"id": "LOW", "title": "Urethral obstruction in the male cat", "doi": "10.1/low",
             "abstract": "a", "volume": "1", "issue": "2", "pages": "3-4",
             "relevance_score": 16},
            # 元数据少但相关性高
            {"id": "HIGH", "title": "Urethral obstruction in the male cats: clinical review",
             "doi": "10.1/high", "relevance_score": 23},
        ]
        unique, removed = dp.deduplicate_papers(papers, title_similarity_threshold=THRESHOLD)
        self.assertEqual(len(unique), 1)
        self.assertEqual(unique[0]["id"], "HIGH", "胜者应取相关性高者")
        # 败者的元数据必须补进来，不能因换了胜者而丢字段
        self.assertEqual(unique[0].get("volume"), "1")
        self.assertEqual(unique[0].get("pages"), "3-4")
        self.assertEqual(unique[0].get("merged_from"), ["LOW"])

    def test_no_relevance_falls_back_to_quality(self):
        """未调用方不打分时，行为退化回「元数据质量」排序（向后兼容）。"""
        papers = [
            {"id": "PLAIN", "title": "Hairball control with Miscanthus grass in cats", "doi": ""},
            {"id": "FULL", "title": "Hairball control with Miscanthus grass in cats",
             "doi": "10.1/x", "abstract": "a", "volume": "1", "issue": "2", "pages": "3-4"},
        ]
        unique, _ = dp.deduplicate_papers(papers)
        self.assertEqual(unique[0]["id"], "FULL")


class TestMergeTraceable(unittest.TestCase):
    """无 id 条目的合并关系必须可追溯（旧实现静默丢弃）。"""

    def test_no_id_falls_back_to_title(self):
        # A1 元数据更全 → 必然胜出，败者是「无 id」那条，才能测到兜底分支
        papers = [
            {"id": "A1", "title": "Dietary fibre and feline hairball", "doi": "10.1/a",
             "abstract": "有 id 版本", "volume": "1", "issue": "2", "pages": "3-4"},
            {"title": "Dietary fibre and feline hairball", "doi": ""},
        ]
        unique, _ = dp.deduplicate_papers(papers)
        self.assertEqual(len(unique), 1)
        trace = unique[0].get("merged_from") or []
        self.assertEqual(len(trace), 1, "无 id 条目的合并关系被丢弃：%r" % (trace,))
        self.assertTrue(trace[0].startswith("title:"), "兜底标识应可辨认：%r" % (trace[0],))


if __name__ == "__main__":
    unittest.main(verbosity=2)
