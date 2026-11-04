# -*- coding: utf-8 -*-
"""下载后「关掉新开的页面、回到赞和收藏列表」这一步（2026-10-26 用户要求）。

为什么补这一步
--------------
下载工具会用微信放大镜打开 profile_ext 页面，跑完微信就停在那个页面上
（截图里标题是「张宇航Neva」，右上角 ⊙ 与 × 并排）。原来只按一次 Ctrl+W，
15:47 那次实测失败——**Ctrl+W 是发给焦点窗口的，不发给微信**，当时前台是
WorkBuddy，键被别的程序吃了。

所以改成两级：先置前再按键；仍不回列表就点标签页的「×」（用 ⊙ 模板锚定后平移）。
这里锁的就是：已在列表时不乱动、置前发生、× 点击被护栏拒绝时不崩。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import favorites_chain as fc  # noqa: E402
import vision  # noqa: E402
import wechat_favorites as wf  # noqa: E402

FAKE_IMG = object()
RECT = (740, 0, 2561, 1518)


class _Base(unittest.TestCase):
    def setUp(self):
        self.caps = []
        p = mock.patch.object(fc.wf, "_capture", return_value=(FAKE_IMG, RECT))
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(fc.log, "__call__",
                              lambda *a, **kw: self.caps.append((a, kw)))
        # fc.log 是模块级函数对象，用 patch.object 替换它
        p = mock.patch.object(fc, "log",
                              lambda level, event, **kw: self.caps.append((event, kw)))
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(vision, "save", return_value=Path("x.png"))
        p.start()
        self.addCleanup(p.stop)

    def _events(self):
        return [e for e, _ in self.caps]


class TestAlreadyOnList(_Base):
    def test_no_action_when_already_on_favorites(self):
        """已在列表页时一个键都不按——多按一次就可能把列表页本身关掉。"""
        with mock.patch.object(fc.wf, "page_state", return_value={"ok": True}), \
             mock.patch.object(vision, "close_tab") as ct, \
             mock.patch.object(vision, "click_at") as ca:
            self.assertTrue(fc.restore_list(49678424))
        ct.assert_not_called()
        ca.assert_not_called()


class TestCtrlWPath(_Base):
    def test_activates_before_sending_ctrl_w(self):
        with mock.patch.object(fc.wf, "page_state", return_value={"ok": False}), \
             mock.patch.object(vision, "activate_window", return_value=True) as act, \
             mock.patch.object(vision, "close_tab") as ct, \
             mock.patch.object(vision, "wait_until", return_value=True):
            self.assertTrue(fc.restore_list(49678424))
        act.assert_called_once()
        ct.assert_called_once()
        self.assertIn("chain.restore_ok", self._events())


class TestCloseButtonFallback(_Base):
    def test_clicks_x_when_ctrl_w_failed(self):
        """Ctrl+W 没回去时，点 ⊙ 右侧的 ×。"""
        with mock.patch.object(fc.wf, "page_state", return_value={"ok": False}), \
             mock.patch.object(vision, "activate_window", return_value=True), \
             mock.patch.object(vision, "close_tab"), \
             mock.patch.object(vision, "wait_until", return_value=False), \
             mock.patch.object(fc, "more_point", return_value=(900, 44, False)), \
             mock.patch.object(fc.wf, "_jitter_xy", side_effect=lambda x, y, r=4: (x, y)), \
             mock.patch.object(fc.wf, "_before_write"), \
             mock.patch.object(fc.wf, "_write_gap"), \
             mock.patch.object(vision, "window_at_point",
                               return_value={"hwnd": 49678424, "pid": 1,
                                             "title": "微信", "cls": "c", "rect": [0] * 4}), \
             mock.patch.object(vision, "window_pid", return_value=1), \
             mock.patch.object(vision, "click_at", return_value=True) as ca:
            # 第二次 wait_until（点 × 之后）返回 True
            with mock.patch.object(vision, "wait_until", side_effect=[False, True]):
                ok = fc.restore_list(49678424)
        self.assertTrue(ok)
        ca.assert_called_once()
        # 落点必须是 ⊙ 中心 + CLOSE_DX
        self.assertEqual(ca.call_args[0][0], RECT[0] + 900 + fc.CLOSE_DX)

    def test_guard_refusal_is_warned_not_crashed(self):
        """点 × 被落点护栏拒绝时只能告警返回 False，不能让整轮崩掉。"""
        with mock.patch.object(fc.wf, "page_state", return_value={"ok": False}), \
             mock.patch.object(vision, "activate_window", return_value=True), \
             mock.patch.object(vision, "close_tab"), \
             mock.patch.object(vision, "wait_until", return_value=False), \
             mock.patch.object(fc, "more_point", return_value=(900, 44, False)), \
             mock.patch.object(fc.wf, "_jitter_xy", side_effect=lambda x, y, r=4: (x, y)), \
             mock.patch.object(fc.wf, "_before_write"), \
             mock.patch.object(fc.wf, "_write_gap"), \
             mock.patch.object(vision, "window_at_point",
                               return_value={"hwnd": 723044, "pid": 99999,
                                             "title": "Wise Care 365", "cls": "c",
                                             "rect": [0] * 4}), \
             mock.patch.object(vision, "window_pid", return_value=1), \
             mock.patch.object(vision, "click_at") as ca:
            self.assertFalse(fc.restore_list(49678424))
        ca.assert_not_called()
        self.assertIn("chain.restore_close_refused", self._events())
        self.assertIn("chain.restore_list_failed", self._events())


if __name__ == "__main__":
    unittest.main()
