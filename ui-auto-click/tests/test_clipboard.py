#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""clipboard.py 离线单测：剪贴板读取不抛异常 + wait_for_url 纯轮询全覆盖。

read_text() 在真机上跑，只断言"不抛异常且返回 str 或 None"——CI 容器里
没有剪贴板也必须过。wait_for_url 全部注入假 reader，绝不碰真剪贴板；
clear() 有破坏性（会抹掉使用者剪贴板）故意不测，见 clipboard.py 注释。
"""
from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import clipboard  # noqa: E402

ARTICLE = "https://mp.weixin.qq.com/s/AbCdEf123456"


class FakeReader:
    """按脚本逐次返回的假 reader：普通值原样返回，Exception 实例则抛出。

    脚本用完后重复最后一个值——"一直是 None"这类场景不必写一万个 None。
    """

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        item = self.script[min(self.calls - 1, len(self.script) - 1)]
        if isinstance(item, Exception):
            raise item
        return item


class TestReadText(unittest.TestCase):
    """真机只验证"不炸"：CI 无剪贴板时返回 None，有则返回 str。"""

    def test_read_text_never_raises(self):
        got = clipboard.read_text()
        self.assertTrue(got is None or isinstance(got, str))

    def test_snapshot_matches_read_text_contract(self):
        got = clipboard.snapshot()
        self.assertTrue(got is None or isinstance(got, str))


class TestUrlPattern(unittest.TestCase):
    """只认 mp.weixin.qq.com：别的域名（含微信其他域名）不算数。"""

    def test_matches_article_url(self):
        self.assertTrue(clipboard.URL_PATTERN.match(ARTICLE))

    def test_rejects_other_domains(self):
        for bad in ("https://example.com", "http://weixin.qq.com/x",
                    "ftp://mp.weixin.qq.com/s/x", "mp.weixin.qq.com/s/x"):
            self.assertFalse(clipboard.URL_PATTERN.match(bad), bad)


class TestWaitForUrl(unittest.TestCase):
    """四路全覆盖：命中 / 不匹配继续等 / 一直 None 超时 / reader 抛异常吞掉。"""

    def _assert_quick(self, began):
        self.assertLess(time.monotonic() - began, 2.0)

    def test_returns_url_when_it_appears(self):
        """① 第 3 次轮询出现匹配 URL → 返回它。"""
        reader = FakeReader([None, None, ARTICLE])
        began = time.monotonic()
        got = clipboard.wait_for_url(timeout=5, poll=0.02, reader=reader)
        self._assert_quick(began)
        self.assertEqual(got, ARTICLE)
        self.assertEqual(reader.calls, 3)

    def test_ignores_non_matching_url(self):
        """② 出现不匹配 URL → 不返回，继续等到超时。"""
        reader = FakeReader(["https://example.com/other"])
        began = time.monotonic()
        got = clipboard.wait_for_url(timeout=0.4, poll=0.02, reader=reader)
        self._assert_quick(began)
        self.assertIsNone(got)
        self.assertGreater(reader.calls, 1)        # 确实多轮询了，不是一次就退

    def test_times_out_when_never_appears(self):
        """③ 一直 None → 超时返回 None。"""
        reader = FakeReader([None])
        began = time.monotonic()
        got = clipboard.wait_for_url(timeout=0.3, poll=0.02, reader=reader)
        self._assert_quick(began)
        self.assertIsNone(got)

    def test_reader_exception_is_swallowed(self):
        """④ reader 抛异常 → 吞掉继续轮询，最终超时 None。"""
        reader = FakeReader([RuntimeError("clipboard busy")])
        began = time.monotonic()
        got = clipboard.wait_for_url(timeout=0.3, poll=0.02, reader=reader)
        self._assert_quick(began)
        self.assertIsNone(got)
        self.assertGreater(reader.calls, 1)

    def test_reader_recovers_after_exception(self):
        """附加路：先抛两次异常，第 3 次给出匹配 URL → 照常返回。"""
        reader = FakeReader([RuntimeError("busy"), OSError("locked"), ARTICLE])
        began = time.monotonic()
        got = clipboard.wait_for_url(timeout=5, poll=0.02, reader=reader)
        self._assert_quick(began)
        self.assertEqual(got, ARTICLE)

    def test_old_value_is_not_returned_again(self):
        """判重：与 old 相同的值不算"新"，否则点一次复制会读到上一次的链接。"""
        reader = FakeReader([ARTICLE])
        got = clipboard.wait_for_url(timeout=0.3, poll=0.02, reader=reader,
                                     old=ARTICLE)
        self.assertIsNone(got)

    def test_returns_stripped_url(self):
        """剪贴板里的链接常带首尾换行/空格：匹配前 strip，返回也是 strip 后的串。"""
        reader = FakeReader(["  " + ARTICLE + "\r\n"])
        got = clipboard.wait_for_url(timeout=1, poll=0.02, reader=reader)
        self.assertEqual(got, ARTICLE)

    def test_timeout_zero_still_probes_once(self):
        """timeout=0 也要真读一次：至少给调用方一次机会，而不是直接放弃。"""
        reader = FakeReader([ARTICLE])
        got = clipboard.wait_for_url(timeout=0, poll=0.02, reader=reader)
        self.assertEqual(got, ARTICLE)
        self.assertEqual(reader.calls, 1)


if __name__ == "__main__":
    unittest.main()
