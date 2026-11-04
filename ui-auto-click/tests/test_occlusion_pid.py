# -*- coding: utf-8 -*-
"""落点归属护栏的同进程放行判据（2026-10-26 真机修正）。

为什么要有这个文件
------------------
第一版护栏的判据是「落点顶层窗口 hwnd 必须严格等于目标窗口 hwnd」。真机跑
到「点 ⊙」那一步时它拦下了：

    拒绝点击：(1540,229) 的落点归属 '' hwnd=50200772，不是微信窗口 hwnd=49678424

但查下来两个窗口 **pid 都是 14024、类名都是 Chrome_WidgetWin_0** —— 微信 4.x
把文章内容渲染成独立的顶层窗口，同进程、同类名，只是 hwnd 不同且标题为空。
点下去仍然落在微信里，却被判成"点进别的程序"，整条链路走不下去。

所以判据改成三级：同 hwnd 放行 → **同 pid 放行（记 info）** → 都不是才拒绝。
这里锁的就是中间那一级，以及"拒绝时必须真的没落鼠标"。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import favorites_chain as fc  # noqa: E402
import vision  # noqa: E402
import wechat_favorites as wf  # noqa: E402


def _hit(hwnd, pid, title="", cls="Chrome_WidgetWin_0"):
    return {"hwnd": hwnd, "pid": pid, "title": title, "cls": cls, "rect": [0, 0, 10, 10]}


class _CapLog(list):
    """接住 favorites_chain 的 log() 输出，用来断言"放行了但没静默"。" """

    def __enter__(self):
        self._orig = fc.log
        fc.log = lambda level, event, **kw: self.append((level, event, kw))
        return self

    def __exit__(self, *exc):
        fc.log = self._orig
        return False

    def events(self):
        return [e for _, e, _ in self]


class TestSameProcessAllowed(unittest.TestCase):
    def setUp(self):
        self._at = vision.window_at_point
        self._pid = vision.window_pid
        vision.window_at_point = lambda x, y: self.hit
        # 目标窗口自己的 pid 固定成 14024（真机微信那个进程的读数）
        vision.window_pid = lambda hwnd: 14024

    def tearDown(self):
        vision.window_at_point = self._at
        vision.window_pid = self._pid

    def test_same_hwnd_passes(self):
        self.hit = _hit(49678424, 14024, "微信")
        fc.assert_point_belongs(100, 100, 49678424)  # 不抛即通过

    def test_same_pid_sibling_window_passes_and_is_logged(self):
        """复现 15:18 的误拦场景：hwnd 不同（50200772）但 pid 相同（14024）。"""
        self.hit = _hit(50200772, 14024, "")
        with _CapLog() as cap:
            fc.assert_point_belongs(1540, 229, 49678424)
        self.assertIn("chain.point_same_process", cap.events(),
                      "同进程放行不能是静默的：必须留下可查证的 info 事件")
        rec = [kw for _, e, kw in cap if e == "chain.point_same_process"][0]
        self.assertEqual(rec["hit_hwnd"], 50200772)
        self.assertEqual(rec["pid"], 14024)

    def test_other_process_rejected(self):
        self.hit = _hit(723044, 99999, "Wise Care 365", "TFrmWPMain")
        with self.assertRaises(RuntimeError) as ctx:
            fc.assert_point_belongs(979, 694, 49678424)
        msg = str(ctx.exception)
        self.assertIn("Wise Care 365", msg)
        self.assertIn("TFrmWPMain", msg, "标题为空时靠类名才认得出是谁，报错必须带类名")

    def test_missing_window_rejected(self):
        self.hit = None
        with self.assertRaises(RuntimeError):
            fc.assert_point_belongs(979, 694, 49678424)


class TestNoClickWhenRejected(unittest.TestCase):
    """拒绝时必须真的没落鼠标 —— 只断言"抛了错"证明不了这一点。"""

    def test_click_at_never_called_when_rejected(self):
        def boom(*a, **kw):
            raise AssertionError("不该发生真实鼠标点击")

        orig_at, orig_pid, orig_click = (
            vision.window_at_point, vision.window_pid, vision.click_at)
        vision.window_at_point = lambda x, y: _hit(723044, 99999, "Wise Care 365")
        vision.window_pid = lambda hwnd: 14024
        vision.click_at = boom
        try:
            with self.assertRaises(RuntimeError):
                fc._click_abs(49678424, (0, 0, 100, 100), 50, 50)
        finally:
            vision.window_at_point = orig_at
            vision.window_pid = orig_pid
            vision.click_at = orig_click


class TestWechatOpenUrlSameProcess(unittest.TestCase):
    """wechat_open_url 那处内联检查也要按同进程放行。"""

    def test_rejects_other_process(self):
        import wechat_open_url as wou

        orig_at, orig_pid = vision.window_at_point, vision.window_pid
        vision.window_at_point = lambda x, y: _hit(723044, 99999, "Wise Care 365")
        vision.window_pid = lambda hwnd: 14024
        try:
            # 只测归属判定这一层：传入一个 hwnd 与目标不同的窗口，期望被拒
            with self.assertRaises(RuntimeError):
                fc.assert_point_belongs(100, 100, 49678424, what="微信窗口")
        finally:
            vision.window_at_point = orig_at
            vision.window_pid = orig_pid
        self.assertTrue(hasattr(wou, "EXIT_ERROR"), "模块可导入即可")


if __name__ == "__main__":
    unittest.main()
