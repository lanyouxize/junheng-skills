#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""落点归属护栏（occlusion guard）离线测试：不截图、不点击、不碰真实窗口。

为什么有这个文件
----------------
2026-10-26 真机事故：下载工具窗口被 `Wise Care 365` 完全盖住，脚本按控件坐标
点下去，**三次点击全部落进了那个系统清理工具**，而日志照样写"已鼠标点击"。
鼠标点击是"发给屏幕坐标"的，跟调用方想点谁毫无关系 —— 所以点击前必须问系统
"这个像素上的顶层窗口是谁"，答不上来或答错就必须拒绝，这就是 fail-closed。

覆盖四类入口（同一份判据 `vision.window_at_point` 派生）：
  ① clicker 的 `action: click`（含 `allow_occluded` 逃生口、dry-run 行为）
  ② clicker 的 `action: activate`（前台被占≠失败，真遮挡=失败）
  ③ clicker 的 `action: open_url` 里点微信放大镜（必须按**微信** hwnd 校验）
  ④ favorites_chain 自己的三处点击（点行/⊙/菜单项）走的 `_click_abs`

全部用 mock 打桩：`click_at` / `click_input` 的**调用次数**是本文件的硬断言 ——
"没抛错"不等于"没点下去"，护栏失效最典型的表现就是"报错了可鼠标还是动了"。
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

os.environ["UIAC_NO_DPI_AWARE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import clicker  # noqa: E402
import favorites_chain as fc  # noqa: E402

WECHAT_HWND = 49678424
OTHER_HWND = 723044          # 真机里是 'Wise Care 365'
OTHER_TITLE = "Wise Care 365"


class _Rect:
    def __init__(self, left, top, right, bottom):
        self.left, self.top, self.right, self.bottom = left, top, right, bottom


class _Ctrl:
    """UIA 控件替身：只记"被点了几次"。"""

    def __init__(self, rect=(100, 200, 300, 260)):
        self._rect = _Rect(*rect)
        self.clicks = 0

    def rectangle(self):
        return self._rect

    def click_input(self):
        self.clicks += 1


class _Win:
    def __init__(self, handle, ctrl):
        self.handle = handle
        self._ctrl = ctrl

    def window_text(self):
        return "微信公众号文章批量下载工具4.0 by.长风998"


def _info(hwnd, title="", rect=(0, 0, 2000, 2000)):
    return {"hwnd": hwnd, "title": title, "cls": "X", "rect": list(rect)}


def _target_clicks():
    """构造一个点击目标可解析的 click step。"""
    return {"name": "点按钮", "action": "click",
            "target": {"auto_id": "Form.PushButton"}}


class _PatchBase(unittest.TestCase):
    def _patches(self, clicker_at, *, rect=(0, 0, 2000, 2000), focus=WECHAT_HWND):
        """clicker 侧常用打桩；`clicker_at` 是 `_window_at` 的返回值/函数。"""
        at_patch = (mock.patch.object(clicker, "_window_at", side_effect=clicker_at)
                    if callable(clicker_at)
                    else mock.patch.object(clicker, "_window_at",
                                           return_value=clicker_at))
        return [at_patch,
                mock.patch.object(clicker, "_window_rect", return_value=rect),
                mock.patch.object(clicker, "_raise_window"),
                mock.patch.object(clicker, "_focus_window", return_value=focus),
                mock.patch.object(clicker, "_window_info",
                                  return_value=_info(clicker_at if isinstance(clicker_at, int)
                                                     else OTHER_HWND, OTHER_TITLE))]

    def _start(self, patches):
        for p in patches:
            p.start()
            self.addCleanup(p.stop)


# ---------------------------------------------------------------- ① click
class TestClickOcclusionGuard(_PatchBase):
    def setUp(self):
        self.ctrl = _Ctrl()
        self.win = _Win(WECHAT_HWND, self.ctrl)
        self._resolve = mock.patch.object(clicker, "resolve", return_value=self.ctrl)
        self._resolve.start()
        self.addCleanup(self._resolve.stop)

    def test_allows_when_point_belongs_to_target(self):
        """落点就是目标窗口 → 放行，且**真的点了一次**。"""
        self._start(self._patches(WECHAT_HWND))
        result = clicker.run_step(self.win, _target_clicks(), {}, dry_run=False)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(self.ctrl.clicks, 1, "落点正确时必须点下去，不能只报 ok")

    def test_refuses_when_point_belongs_to_other_window(self):
        """落点属于别的窗口 → 抛错，且**一次都不许点**。

        真机形态：点「全部」时落进 Wise Care 365。错误信息里必须能看见那个窗口名，
        否则人对着 hwnd=723044 根本判断不出"我刚把鼠标点到什么软件里了"。
        """
        self._start(self._patches(OTHER_HWND))
        with self.assertRaises(RuntimeError) as ctx:
            clicker.run_step(self.win, _target_clicks(), {}, dry_run=False)
        msg = str(ctx.exception)
        self.assertEqual(self.ctrl.clicks, 0, "归属不对时绝不能真点")
        self.assertIn("Wise Care 365", msg)          # 实际命中的窗口标题
        self.assertIn(str(WECHAT_HWND), msg)         # 期望窗口 hwnd
        self.assertIn("(200,230)", msg)              # 点击坐标

    def test_allow_occluded_is_step_level_escape_hatch(self):
        """step 上显式 `allow_occluded: true` → 放行，但状态必须是 warn 不是 ok。"""
        self._start(self._patches(OTHER_HWND))
        step = dict(_target_clicks(), allow_occluded=True)
        result = clicker.run_step(self.win, step, {}, dry_run=False)
        self.assertEqual(result["status"], "warn",
                         "逃生口放行的点击不能伪装成正常成功")
        self.assertEqual(self.ctrl.clicks, 1)
        self.assertIn("Wise Care 365", result["detail"])

    def test_window_at_point_none_is_fail_closed(self):
        """查不到落点归属（WindowFromPoint 返回空）→ 拒绝，不许当成"没窗口"。

        这里用 clicker 的真实 `_window_at` 走到 `vision.window_at_point` 的 None
        分支：把 `window_at_point` 打桩成 None，断言零点击。
        """
        self._start([mock.patch.object(clicker, "_window_at", return_value=0),
                     mock.patch.object(clicker, "_window_rect",
                                       return_value=(0, 0, 2000, 2000)),
                     mock.patch.object(clicker, "_raise_window"),
                     mock.patch.object(clicker, "_focus_window", return_value=WECHAT_HWND),
                     mock.patch.object(clicker, "_window_info", return_value=None)])
        with self.assertRaises(RuntimeError) as ctx:
            clicker.run_step(self.win, _target_clicks(), {}, dry_run=False)
        self.assertEqual(self.ctrl.clicks, 0)
        self.assertIn("无法查询", str(ctx.exception))

    def test_dry_run_neither_checks_nor_clicks(self):
        """dry-run 只打印计划：既不该查归属，也不该点。"""
        with mock.patch.object(clicker, "_window_at") as at:
            result = clicker.run_step(self.win, _target_clicks(), {}, dry_run=True)
        self.assertEqual(result["status"], "plan")
        self.assertEqual(self.ctrl.clicks, 0)
        at.assert_not_called()


# ------------------------------------------------------------- ② activate
class TestActivateGuard(_PatchBase):
    def setUp(self):
        self.ctrl = _Ctrl()
        self.win = _Win(WECHAT_HWND, self.ctrl)

    def _run(self, patches):
        import ctypes
        patches = patches + [mock.patch.object(clicker, "time"),
                             mock.patch.object(ctypes.windll.user32, "ShowWindow",
                                               lambda *a: 1)]
        self._start(patches)
        return clicker.run_step(self.win, {"name": "激活", "action": "activate"},
                                {}, dry_run=False)

    def test_activate_fails_when_window_is_really_covered(self):
        """窗口中心归属不是目标 ⇒ 置前确实失败 ⇒ step 失败（后续点击可能点错）。"""
        patches = self._patches(WECHAT_HWND, focus=OTHER_HWND)
        patches[-1] = mock.patch.object(clicker, "_window_info",
                                        return_value=_info(OTHER_HWND, OTHER_TITLE))
        with self.assertRaises(RuntimeError) as ctx:
            self._run(patches)
        msg = str(ctx.exception)
        self.assertIn("置前失败", msg)
        self.assertIn(OTHER_TITLE, msg)
        self.assertIn(str(WECHAT_HWND), msg)

    def test_activate_ok_when_only_focus_is_blocked(self):
        """前台被别人占着但窗口确实在最上层 ⇒ 不算失败（本机常态）。"""
        result = self._run(self._patches(WECHAT_HWND, focus=OTHER_HWND))
        self.assertEqual(result["status"], "ok")
        self.assertIn(str(OTHER_HWND), result["detail"])

    def test_activate_failure_is_downgraded_when_step_is_optional(self):
        """`optional: true` 的 activate 失败只告警（EXIT_PARTIAL），不中断整个 profile；

        同一 profile 去掉 optional 就必须 EXIT_ERROR。降级逻辑在 `cmd_run` 那一层，
        所以这里走真实的 `cmd_run`，而不是只断言 `run_step` 抛错。
        """
        rc_opt = self._cmd_run_with_activate(optional=True)
        rc_strict = self._cmd_run_with_activate(optional=False)
        self.assertEqual(rc_opt, clicker.EXIT_PARTIAL,
                         "optional 的 activate 失败应降级为 warn（返回 5），不该中断")
        self.assertEqual(rc_strict, clicker.EXIT_ERROR,
                         "非 optional 的 activate 失败必须中断（返回 3）")

    def _cmd_run_with_activate(self, optional: bool):
        import argparse
        import ctypes

        step = {"name": "激活", "action": "activate"}
        if optional:
            step["optional"] = True
        profile = {"window": {"regex": ".", "classes": []}, "steps": [step]}
        args = argparse.Namespace(profile="p", dry_run=False, yes=True,
                                  from_step=1, max_steps=0, var=[])
        with mock.patch.object(clicker, "_load_profile", return_value=profile), \
             mock.patch.object(clicker, "find_windows",
                               return_value=[{"title": "工具", "handle": WECHAT_HWND}]), \
             mock.patch.object(clicker, "attach", return_value=self.win), \
             mock.patch.object(clicker, "_window_at", return_value=OTHER_HWND), \
             mock.patch.object(clicker, "_window_rect", return_value=(0, 0, 800, 600)), \
             mock.patch.object(clicker, "_raise_window"), \
             mock.patch.object(clicker, "_focus_window", return_value=OTHER_HWND), \
             mock.patch.object(clicker, "_window_info",
                               return_value=_info(OTHER_HWND, OTHER_TITLE)), \
             mock.patch.object(clicker, "time"), \
             mock.patch.object(ctypes.windll.user32, "ShowWindow", lambda *a: 1):
            return clicker.cmd_run(args)


# ------------------------------------------------------------- ③ open_url
class TestOpenUrlUsesWechatHwnd(unittest.TestCase):
    """点微信放大镜时必须按**微信**的 hwnd 校验，不能误用 profile 的目标窗口。"""

    def _run(self, hit):
        got = (object(), (1000, 0, 2000, 1000), {"hwnd": WECHAT_HWND, "title": "微信"})
        with mock.patch.object(fc.vision, "grab_wechat", return_value=got), \
             mock.patch("wechat_open_url.vision.grab_wechat", return_value=got), \
             mock.patch("wechat_open_url.find_search_icon",
                        return_value=(100, 40, "template", 0.99)), \
             mock.patch("wechat_open_url.set_clipboard", return_value=True), \
             mock.patch("wechat_open_url.vision.park_cursor"), \
             mock.patch("wechat_open_url.vision.window_at_point", return_value=hit), \
             mock.patch("wechat_open_url.vision.click_at", return_value=True) as click, \
             mock.patch("wechat_open_url.vision.key_tap"), \
             mock.patch("wechat_open_url.time"):
            import wechat_open_url
            rc = wechat_open_url._navigate("https://mp.weixin.qq.com/mp/profile_ext?x=1",
                                           settle=0)
        return rc, click

    def test_passes_when_point_belongs_to_wechat(self):
        rc, click = self._run(_info(WECHAT_HWND, "微信"))
        self.assertEqual(rc, 0)
        self.assertEqual(click.call_count, 1)

    def test_refuses_when_wechat_is_covered(self):
        """微信被别的窗口盖住 → 不许点放大镜（否则点到那个窗口上）。"""
        rc, click = self._run(_info(OTHER_HWND, OTHER_TITLE))
        self.assertNotEqual(rc, 0)
        self.assertEqual(click.call_count, 0, "落点不是微信时绝不能点")

    def test_refuses_when_point_unknown(self):
        rc, click = self._run(None)
        self.assertNotEqual(rc, 0)
        self.assertEqual(click.call_count, 0)


# ------------------------------------------------- ④ favorites_chain 三处点击
class TestChainClickGuard(unittest.TestCase):
    RECT = (740, 0, 2561, 1518)

    def test_chain_refuses_when_point_is_not_wechat(self):
        """chain 自己点列表行/⊙/菜单项：落点不是微信 ⇒ 抛错且零点击。"""
        with mock.patch.object(fc.vision, "window_at_point",
                               return_value=_info(OTHER_HWND, OTHER_TITLE)), \
             mock.patch.object(fc.vision, "click_at") as click, \
             mock.patch.object(fc.wf, "_before_write"), \
             mock.patch.object(fc.wf, "_write_gap"), \
             mock.patch.object(fc.wf, "_jitter_xy", side_effect=lambda x, y, r=4: (x, y)):
            with self.assertRaises(RuntimeError) as ctx:
                fc._click_abs(WECHAT_HWND, self.RECT, 724, 244)
        self.assertEqual(click.call_count, 0)
        self.assertIn(OTHER_TITLE, str(ctx.exception))
        self.assertIn(str(WECHAT_HWND), str(ctx.exception))

    def test_chain_clicks_when_point_is_wechat(self):
        with mock.patch.object(fc.vision, "window_at_point",
                               return_value=_info(WECHAT_HWND, "微信")), \
             mock.patch.object(fc.vision, "click_at", return_value=True) as click, \
             mock.patch.object(fc.wf, "_before_write"), \
             mock.patch.object(fc.wf, "_write_gap"), \
             mock.patch.object(fc.wf, "_jitter_xy", side_effect=lambda x, y, r=4: (x, y)):
            ok = fc._click_abs(WECHAT_HWND, self.RECT, 724, 244)
        self.assertTrue(ok)
        self.assertEqual(click.call_count, 1)
        # 屏幕绝对坐标 = 窗口内坐标 + 窗口原点
        self.assertEqual(click.call_args[0], (724 + 740, 244 + 0))

    def test_chain_guards_the_jittered_point(self):
        """校验的必须是**抖动后**的坐标：真按下鼠标的是它，不是原坐标。"""
        seen = []

        def fake_wap(x, y):
            seen.append((x, y))
            return _info(WECHAT_HWND, "微信")

        with mock.patch.object(fc.vision, "window_at_point", side_effect=fake_wap), \
             mock.patch.object(fc.vision, "click_at", return_value=True) as click, \
             mock.patch.object(fc.wf, "_before_write"), \
             mock.patch.object(fc.wf, "_write_gap"), \
             mock.patch.object(fc.wf, "_jitter_xy", side_effect=lambda x, y, r=4: (x + 3, y - 2)):
            fc._click_abs(WECHAT_HWND, self.RECT, 724, 244)
        self.assertEqual(seen, [(724 + 740 + 3, 244 - 2)])
        self.assertEqual(click.call_args[0], (724 + 740 + 3, 244 - 2))

    def test_window_at_point_none_fails_closed(self):
        with mock.patch.object(fc.vision, "window_at_point", return_value=None), \
             mock.patch.object(fc.vision, "click_at") as click, \
             mock.patch.object(fc.wf, "_before_write"), \
             mock.patch.object(fc.wf, "_write_gap"), \
             mock.patch.object(fc.wf, "_jitter_xy", side_effect=lambda x, y, r=4: (x, y)):
            with self.assertRaises(RuntimeError):
                fc._click_abs(WECHAT_HWND, self.RECT, 10, 10)
        self.assertEqual(click.call_count, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
