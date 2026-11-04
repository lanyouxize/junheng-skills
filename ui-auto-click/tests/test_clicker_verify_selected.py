#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""click 动作的 `verify_selected` 三段式选中校验（离线：不发育鼠标事件、不需要真窗口）。

为什么要这一整套：**"点了"不等于"生效了"**。2026-10-26 真机事故里，点「全部」时
鼠标三次都送进了压在上面的另一个程序，clicker 日志却照样写 `status: ok`；后来又
抓到"点完选中态毫无变化"的情形，日志同样写 ok。选中态（`SelectionItem.
CurrentIsSelected`）是唯一独立于"我有没有调用点击 API"的证据。

三段式：
  1. 点前先看目标是不是已选中 —— 是就**不发鼠标事件**，明确记「未产生任何鼠标动作」
     （这时"点错"在物理上不可能发生，因为根本没有点击）；
  2. 没选中才走原有坐标守卫并点击；
  3. 点后回读：目标=1 且同组其余=0 才算生效，否则抛错并带出 点前/点后 选中项名称。

测试优先证明**副作用零发生**，而不是只看返回值：noop 分支必须证明所有真实发鼠标
的入口一个都没被调用。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import clicker  # noqa: E402


class FakeSelectionItem:
    """对齐 UIA 的 ISelectionItemProvider：CurrentIsSelected 是**属性**不是字段。

    （同类坑见 FakeToggleInterface：property 放进实例 __dict__ 不会触发描述符协议。）
    """

    def __init__(self, owner):
        self._owner = owner

    @property
    def CurrentIsSelected(self):
        return 1 if self._owner.selected else 0


class FakeRadio:
    """单选按钮替身。`clicks` 是"真实鼠标落下去了几次"的唯一真相来源。"""

    def __init__(self, name, selected=False):
        self._name = name
        self.selected = selected
        self.clicks = 0
        self._group = None
        self.element_info = SimpleNamespace(
            automation_id="Radio." + name, control_type="RadioButton",
            class_name="Fake")

    def __repr__(self):
        return "<FakeRadio %s selected=%s clicks=%d>" % (
            self._name, self.selected, self.clicks)

    @property
    def iface_selection_item(self):
        return FakeSelectionItem(self)

    def window_text(self):
        return self._name

    def rectangle(self):
        return SimpleNamespace(left=10, top=20, right=100, bottom=44)

    def click_input(self):
        self.clicks += 1
        # 真单选按钮是互斥的：选中自己的同时其他会掉。替身必须复刻这一点，
        # 否则互斥检查永远挂在一个假的"两个都选中"上，测不到真实缺陷。
        if self._group:
            for r in self._group.radios:
                if r is not self:
                    r.selected = False
        self.selected = True

    def parent(self):
        return self._group


class SilentRadio(FakeRadio):
    """鼠标确实落下、但控件毫无反应的替身 —— 复现 2026-10-26 15:00 那次事故。"""

    def click_input(self):
        self.clicks += 1          # 点了，但选中态不跟着变


class UnreadableRadio(FakeRadio):
    """不暴露 SelectionItem 模式：读选中位必然失败（用来验 fail-closed）。"""

    @property
    def iface_selection_item(self):
        raise AttributeError("该控件不支持 SelectionItem 模式")


class FakeGroup:
    def __init__(self, radios):
        self.radios = list(radios)
        for r in self.radios:
            r._group = self

    def descendants(self, **kwargs):
        want = kwargs.get("control_type")
        return [r for r in self.radios
                if not want or r.element_info.control_type == want]


class FakeWindow:
    def __init__(self, group):
        self.handle = 123
        self.group = group

    def descendants(self, **kwargs):
        return self.group.descendants(**kwargs)


def make_window(*specs):
    """specs: (name, selected) 或 (name, selected, cls)；返回 (window, {名字: 控件})。"""
    radios = []
    for spec in specs:
        name, selected = spec[0], spec[1]
        cls = spec[2] if len(spec) > 2 else FakeRadio
        radios.append(cls(name, selected=selected))
    group = FakeGroup(radios)
    return FakeWindow(group), {r._name: r for r in radios}


def step(**extra):
    base = {"name": "设置时间范围", "action": "click",
            "target": {"auto_id": "Radio.全部"}}
    base.update(extra)
    return base


class TestNoopAlreadySelected(unittest.TestCase):
    """第 1 段：已是目标态 → 零点击；且这类情形不许记成 warn。"""

    def setUp(self):
        self.win, self.radios = make_window(
            ("全部", True), ("一个月内", False), ("一年内", False), ("自定义", False))

    def test_noop_returns_ok(self):
        result = clicker.run_step(self.win, step(verify_selected=True), {}, dry_run=False)
        self.assertEqual(result["status"], "ok",
                         "已是目标态是预期行为，不能用 warn（warn 会把本次 run 拉成 rc=5）")
        self.assertIn("未产生任何鼠标动作", result["detail"])
        self.assertIn("全部=1", result["detail"])
        self.assertIn("其他 3 个=0", result["detail"])

    def test_noop_never_touches_the_mouse(self):
        """核心断言：真实发鼠标的入口一次都不能被调用。"""
        with mock.patch.object(clicker, "_window_rect",
                               side_effect=AssertionError("noop 分支不该再去查坐标")), \
                mock.patch.object(clicker, "_window_at",
                                  side_effect=AssertionError("noop 分支不该做落点归属检查")):
            clicker.run_step(self.win, step(verify_selected=True), {}, dry_run=False)
        self.assertEqual(self.radios["全部"].clicks, 0, "已选中就不许再点")

        # 兜住"将来把 clicker 改成走 vision.click_at"的情况：那条路也不许发出点击。
        # 注意：当前实现里 clicker 的发鼠标入口是 control.click_input，所以上面那条
        # self.radios["全部"].clicks == 0 才是实质断言，这条是给未来重构上的护栏。
        vision_stub = mock.MagicMock()
        vision_stub.click_at.side_effect = AssertionError("noop 分支发了鼠标事件")
        with mock.patch.dict(sys.modules, {"vision": vision_stub}), \
                mock.patch.object(clicker, "_window_rect", return_value=(0, 0, 500, 500)), \
                mock.patch.object(clicker, "_window_at", return_value=123):
            clicker.run_step(self.win, step(verify_selected=True), {}, dry_run=False)
        vision_stub.click_at.assert_not_called()

    def test_mutual_exclusion_broken_raises_without_click(self):
        win, radios = make_window(("全部", True), ("一个月内", True), ("一年内", False))
        with self.assertRaises(RuntimeError) as ctx:
            clicker.run_step(win, step(verify_selected=True), {}, dry_run=False)
        self.assertIn("互斥被破坏", str(ctx.exception))
        self.assertIn("一个月内", str(ctx.exception))
        self.assertEqual(radios["全部"].clicks, 0)

    def test_unreadable_selection_pattern_fails_closed(self):
        """读不到 SelectionItem 必须报错，绝不能当成"没选中"继续点下去。"""
        win, radios = make_window(("全部", True, UnreadableRadio), ("一个月内", False))
        with self.assertRaises(RuntimeError) as ctx:
            clicker.run_step(win, step(verify_selected=True), {}, dry_run=False)
        self.assertIn("无法回读", str(ctx.exception))
        self.assertEqual(radios["全部"].clicks, 0)


class TestClickAndVerify(unittest.TestCase):
    """第 2/3 段：走到这一步必须过坐标守卫，点完必须回读证明生效。"""

    def run_click(self, win, **extra):
        with mock.patch.object(clicker, "_window_rect", return_value=(0, 0, 500, 500)), \
                mock.patch.object(clicker, "_window_at", return_value=123):
            return clicker.run_step(win, step(verify_selected=True, **extra),
                                    {}, dry_run=False)

    def test_click_applies_then_readback_ok(self):
        win, radios = make_window(("全部", False), ("一个月内", True))
        result = self.run_click(win)
        self.assertEqual(result["status"], "ok")
        self.assertIn("回读选中项=全部", result["detail"])
        self.assertIs(radios["全部"].selected, True)
        self.assertIs(radios["一个月内"].selected, False, "单选必须互斥")

    def test_click_without_effect_raises_with_before_after_names(self):
        """2026-10-26 15:00 事故复现：点前「一年内」=1，点「全部」后仍是「一年内」=1。

        断言到"报错里同时出现点前和点后的选中项名称" —— 真跑的人只看一行报错，
        报错不写清"一年内 → 一年内"等于还得回去翻截图。
        """
        win, radios = make_window(("全部", False, SilentRadio), ("一年内", True),
                                  ("一个月内", False))
        with self.assertRaises(RuntimeError) as ctx:
            self.run_click(win)
        msg = str(ctx.exception)
        self.assertIn("一年内", msg, "必须写出点击前选中的是谁")
        self.assertIn("全部", msg, "必须写出点击的是谁")
        self.assertIn("没有生效", msg)
        self.assertEqual(radios["全部"].clicks, 1, "鼠标确实落了一次，只是没生效")

    def test_names_present_even_when_nothing_selected(self):
        """点前点后都无人选中时名称也得写全，「无」比空更有信息量。"""
        win, _ = make_window(("全部", False, SilentRadio), ("一年内", False))
        with self.assertRaises(RuntimeError) as ctx:
            self.run_click(win)
        msg = str(ctx.exception)
        self.assertIn("点击前选中「无」", msg)
        self.assertIn("点击「全部」后仍选中「无」", msg)

    def test_mutual_exclusion_after_click_raises(self):
        class BothSelected(FakeRadio):
            def click_input(self):
                self.clicks += 1
                self.selected = True
                others = [r for r in self._group.radios if r is not self and not r.selected]
                if others:
                    others[0].selected = True      # 模拟控件状态错乱：两个都被选中

        win, _ = make_window(("全部", False, BothSelected), ("一个月内", True))
        with self.assertRaises(RuntimeError) as ctx:
            self.run_click(win)
        self.assertIn("互斥被破坏", str(ctx.exception))


class TestRegressionWithoutFlag(unittest.TestCase):
    """不写 verify_selected 的步骤必须和以前一字不差。"""

    def test_plain_click_still_clicks_unconditionally(self):
        win, radios = make_window(("全部", True), ("一个月内", False))
        with mock.patch.object(clicker, "_window_rect", return_value=(0, 0, 500, 500)), \
                mock.patch.object(clicker, "_window_at", return_value=123):
            result = clicker.run_step(win, step(), {}, dry_run=False)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["detail"], "已鼠标点击 (55,32)")
        # 已经选中了也照样点 —— 旧行为原样保留（这正是三段式要修的那件事）
        self.assertEqual(radios["全部"].clicks, 1)

    def test_dry_run_unaffected(self):
        win, radios = make_window(("全部", True), ("一个月内", False))
        result = clicker.run_step(win, step(verify_selected=True), {}, dry_run=True)
        self.assertEqual(result["status"], "plan")
        self.assertEqual(radios["全部"].clicks, 0)


if __name__ == "__main__":
    unittest.main()
