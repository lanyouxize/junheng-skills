#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ui-auto-click 引擎离线测试（不启动任何 GUI、不依赖 pywinauto/yaml 之外的东西）。

覆盖三块最容易回归的地方：
  ① 选择器解析（auto_id 优先 / 版本兜底列表 / index）；
  ② 动作语义（toggle 目标态+回读、set_value 回读不一致必须报错、wait_log 超时）；
  ③ 内置 profile 自检（动作合法、target 可解析形状、真执行必须 --yes）。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import clicker  # noqa: E402


class FakeToggleInterface:
    """对齐 UIA 的 IToggleProvider：CurrentToggleState 是属性，不是普通字段。

    注意别写成 SimpleNamespace(CurrentToggleState=property(...)) —— property
    放在实例 __dict__ 里不会触发描述符协议，读出来就是 property 对象本身。
    """

    def __init__(self, owner):
        self._owner = owner

    @property
    def CurrentToggleState(self):
        return int(self._owner.state)

    def Toggle(self):
        self._owner.toggle()


class FakeControl:
    """最小化控件替身：只实现引擎真正用到的方法。

    特意与真机 PySide6 控件对齐：`window_text()` 对 Edit 返回空串（Name 为空），
    真实文本在 Value 模式（`get_value()`）里；CheckBox 的 ToggleState 从
    `iface_toggle.CurrentToggleState` 读。
    """

    def __init__(self, name="", auto_id="", control_type="Button", state="0", text="",
                 enabled=True):
        self._name = name
        self._text = text
        self.state = state
        self.enabled = enabled
        self.invoked = 0
        self.element_info = SimpleNamespace(
            automation_id=auto_id, control_type=control_type, class_name="Fake")
        self.iface_toggle = FakeToggleInterface(self)

    def is_enabled(self):
        return self.enabled

    def window_text(self):
        return self._name

    def invoke(self):
        self.invoked += 1

    def toggle(self):
        self.state = "0" if self.state == "1" else "1"

    def set_edit_text(self, value):
        self._text = value

    def get_value(self):
        return self._text

    def rectangle(self):
        return SimpleNamespace(left=10, top=20)


class FakeWindow:
    """窗口替身。刻意复刻 pywinauto 0.6.9 的**敌意**：`descendants(auto_id=...)`
    会抛 TypeError（build_condition 不认 auto_id）。

    如果引擎把 auto_id 当 kwargs 传下去，这条 TypeError 会被"选择器列表兜底"
    吞掉，静默退到按 index 命中错误控件 —— 真机事故就是把等待时间写进了日志框。
    替身必须保留这个坑，否则测试会假绿。
    """

    def __init__(self, controls):
        self.controls = controls

    def descendants(self, **kwargs):
        if "auto_id" in kwargs:
            raise TypeError("IUIA.build_condition() got an unexpected keyword argument 'auto_id'")
        control_type = kwargs.get("control_type")
        out = []
        for control in self.controls:
            if control_type and control.element_info.control_type != control_type:
                continue
            out.append(control)
        return out


class TestResolve(unittest.TestCase):
    def setUp(self):
        self.button = FakeControl("1.获取公众号id", "Form.PushButton", "Button")
        self.md_box = FakeControl("导出MD文件", "Form.CheckBox", "CheckBox", state="1")
        self.window = FakeWindow([self.button, self.md_box])

    def test_auto_id_hit(self):
        got = clicker.resolve(self.window, {"auto_id": "Form.PushButton"}, timeout=0.1)
        self.assertIs(got, self.button)

    def test_auto_id_plus_name_verification(self):
        """给了 name 就必须校验：auto_id 存在但名字不符应当失败（防同名控件错位）。"""
        with self.assertRaises(RuntimeError):
            clicker.resolve(self.window, {"auto_id": "Form.PushButton", "name": "别的按钮"},
                            timeout=0.1)

    def test_name_only_hit_for_old_version(self):
        got = clicker.resolve(self.window, {"control_type": "Button", "name": "1.获取公众号id"},
                              timeout=0.1)
        self.assertIs(got, self.button)

    def test_list_fallback_second_entry(self):
        """版本兜底：第一个（新版的 auto_id）不存在时，退到按名字命中。"""
        selector = [{"auto_id": "Form.NotExist"}, {"control_type": "Button", "name": "1.获取公众号id"}]
        got = clicker.resolve(self.window, selector, timeout=0.1)
        self.assertIs(got, self.button)

    def test_index_selects_nth(self):
        second = FakeControl("导出PDF", "Form.CheckBox_2", "CheckBox")
        window = FakeWindow([self.md_box, second])
        got = clicker.resolve(window, {"control_type": "CheckBox", "index": 1}, timeout=0.1)
        self.assertIs(got, second)

    def test_missing_raises_with_timeout(self):
        with self.assertRaises(RuntimeError):
            clicker.resolve(self.window, {"auto_id": "Form.Nope"}, timeout=0.1)

    def test_auto_id_wins_over_document_order(self):
        """真机事故复现：日志框是窗口里第一个 Edit。

        若 auto_id 失效退到 {control_type: Edit, index: 0}，就会命中日志框，
        把「等待时间」写进日志。按 auto_id 必须精确命中 LineEdit_2。
        """
        log = FakeControl("", "Form.PlainTextEdit", "Edit", text="日志")
        edit = FakeControl("", "Form.LineEdit_2", "Edit", text="10")
        window = FakeWindow([log, edit])
        got = clicker.resolve(window, {"auto_id": "Form.LineEdit_2", "control_type": "Edit"},
                              timeout=0.1)
        self.assertIs(got, edit)
        self.assertIsNot(got, log)

    def test_auto_id_without_control_type(self):
        """只给 auto_id 时也要能命中（枚举全部后代再按 automation_id 过滤）。"""
        log = FakeControl("", "Form.PlainTextEdit", "Edit", text="日志")
        edit = FakeControl("", "Form.LineEdit_3", "Edit", text="0")
        got = clicker.resolve(FakeWindow([log, edit]), {"auto_id": "Form.LineEdit_3"},
                              timeout=0.1)
        self.assertIs(got, edit)

    def test_auto_id_missing_does_not_silently_pass(self):
        """auto_id 不存在时必须报错，不能因为"枚举到别的控件"就算命中。"""
        window = FakeWindow([FakeControl("x", "Form.PlainTextEdit", "Edit")])
        with self.assertRaises(RuntimeError):
            clicker.resolve(window, {"auto_id": "Form.LineEdit_9", "control_type": "Edit"},
                            timeout=0.1)


class TestToggle(unittest.TestCase):
    def test_sets_wanted_state_and_reads_back(self):
        box = FakeControl("导出PDF", "Form.CheckBox_2", "CheckBox", state="1")
        acted, before, after = clicker.apply_toggle(box, False, clicker.read_toggle(box))
        self.assertTrue(acted)
        self.assertEqual((before, after), ("1", "0"))

    def test_noop_when_already_target(self):
        box = FakeControl("导出PDF", "Form.CheckBox_2", "CheckBox", state="1")
        acted, before, after = clicker.apply_toggle(box, True, clicker.read_toggle(box))
        self.assertFalse(acted)
        self.assertEqual(before, after)

    def test_invert_when_want_is_none(self):
        box = FakeControl("导出PDF", "Form.CheckBox_2", "CheckBox", state="0")
        _acted, before, after = clicker.apply_toggle(box, None, clicker.read_toggle(box))
        self.assertEqual((before, after), ("0", "1"))

    def test_disabled_control_raises_instead_of_fake_success(self):
        """真机事故：导出HTML文件 是灰的（禁用），toggle 点了没反应。

        此时必须报"控件已禁用"，不能把"没变"记成"已是目标态"。
        """
        box = FakeControl("导出HTML文件", "Form.CheckBox_4", "CheckBox",
                          state="0", enabled=False)
        with self.assertRaises(RuntimeError) as ctx:
            clicker.apply_toggle(box, True, "0")
        self.assertIn("禁用", str(ctx.exception))

    def test_disabled_but_already_at_target_is_noop(self):
        box = FakeControl("导出HTML文件", "Form.CheckBox_4", "CheckBox",
                          state="1", enabled=False)
        acted, before, after = clicker.apply_toggle(box, True, "1")
        self.assertFalse(acted)
        self.assertEqual((before, after), ("1", "1"))


class TestTextReading(unittest.TestCase):
    """Edit 控件在 UIA 里 Name 常为空、正文在 Value 里 —— 读文本必须跨过空串继续试。"""

    def test_read_text_falls_back_to_value(self):
        edit = FakeControl("", "Form.PlainTextEdit", "Edit", text="获取公众号历史消息页面成功")
        self.assertEqual(edit.window_text(), "")
        self.assertEqual(clicker.read_text(edit), "获取公众号历史消息页面成功")

    def test_read_text_keeps_name_when_no_value(self):
        label = FakeControl("公众号文章批量下载工具", "Form.Label", "Text", text="")
        self.assertEqual(clicker.read_text(label), "公众号文章批量下载工具")

    def test_read_value_prefers_value_over_name(self):
        edit = FakeControl("等待时间", "Form.LineEdit_2", "Edit", text="15")
        self.assertEqual(clicker.read_text(edit), "等待时间")   # Name 有值就先返回 Name
        self.assertEqual(clicker.read_value(edit), "15")        # 但写后回读必须取 Value


class TestStepSemantics(unittest.TestCase):
    def setUp(self):
        self.log = FakeControl("", "Form.PlainTextEdit", "Edit", text="旧日志")
        self.edit = FakeControl("", "Form.LineEdit_2", "Edit", text="10")
        self.window = FakeWindow([self.log, self.edit])

    def test_set_value_ok(self):
        result = clicker.run_step(self.window, {
            "name": "设置等待时间", "action": "set_value", "value": "15",
            "target": {"auto_id": "Form.LineEdit_2"},
        }, {}, dry_run=False)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(self.edit.get_value(), "15")

    def test_set_value_readback_mismatch_raises(self):
        """控件吞掉输入（Qt 校验/掩码）时必须报错，不能假装写成功。"""
        stubborn = FakeControl("", "Form.LineEdit_2", "Edit", text="10")

        class Stubborn(FakeControl):
            def set_edit_text(self, value):
                pass  # 静默不生效

        stubborn.__class__ = Stubborn
        window = FakeWindow([stubborn])
        with self.assertRaises(RuntimeError):
            clicker.run_step(window, {
                "name": "设置", "action": "set_value", "value": "15",
                "target": {"auto_id": "Form.LineEdit_2"},
            }, {}, dry_run=False)

    def test_wait_log_hits(self):
        log = FakeControl("", "Form.PlainTextEdit", "Edit", text="获取公众号历史消息页面成功")
        window = FakeWindow([log])
        result = clicker.run_step(window, {
            "name": "等日志", "action": "wait_log", "timeout": 0.2, "interval": 0.05,
            "contains_any": ["获取公众号历史消息页面成功"], "target": {"auto_id": "Form.PlainTextEdit"},
        }, {}, dry_run=False)
        self.assertEqual(result["status"], "ok")

    def test_wait_log_timeout_raises(self):
        window = FakeWindow([self.log])
        with self.assertRaises(RuntimeError):
            clicker.run_step(window, {
                "name": "等日志", "action": "wait_log", "timeout": 0.15, "interval": 0.05,
                "contains_any": ["永远不出现的字样"], "target": {"auto_id": "Form.PlainTextEdit"},
            }, {}, dry_run=False)

    def test_dry_run_touches_nothing(self):
        result = clicker.run_step(self.window, {
            "name": "点按钮", "action": "invoke",
            "target": {"auto_id": "Form.LineEdit_2"},
        }, {}, dry_run=True)
        self.assertEqual(result["status"], "plan")

    def test_unknown_action_rejected(self):
        with self.assertRaises(RuntimeError):
            clicker.run_step(self.window, {"name": "x", "action": "explode"}, {}, dry_run=True)

    def test_click_checks_point_ownership_not_foreground(self):
        """点击守卫看的是**坐标归属**，不是前台窗口。

        旧实现在这里断言"前台不是目标窗口就拒绝"，2026-10-23 真机推翻：Windows
        前台锁让前台恒为别的窗口 ⇒ 一切点击被拒；而真正该拦的是"坐标上压着别的
        窗口"。归属不对仍必须拒绝（防误点），归属正确则焦点在谁手里都照点。
        """
        target = FakeWindow([self.edit])
        win = SimpleNamespace(handle=123, descendants=target.descendants)
        self.edit.rectangle = lambda: SimpleNamespace(left=10, top=20, right=90, bottom=60)
        self.edit.click_input = lambda: None
        # 归属不对 → 拒绝
        with mock.patch.object(clicker, "_window_at", return_value=999), \
             mock.patch.object(clicker, "_window_rect", return_value=(0, 0, 500, 500)), \
             mock.patch.object(clicker, "_raise_window"), \
             mock.patch.object(clicker, "_focus_window", return_value=999):
            with self.assertRaises(RuntimeError) as ctx:
                clicker.run_step(win, {"name": "点", "action": "click",
                                       "target": {"auto_id": "Form.LineEdit_2"}},
                                 {}, dry_run=False)
        self.assertIn("归属", str(ctx.exception))
        # 归属正确 → 放行（与前台无关）
        with mock.patch.object(clicker, "_window_at", return_value=123), \
             mock.patch.object(clicker, "_window_rect", return_value=(0, 0, 500, 500)):
            result = clicker.run_step(win, {"name": "点", "action": "click",
                                            "target": {"auto_id": "Form.LineEdit_2"}},
                                      {}, dry_run=False)
        self.assertEqual(result["status"], "ok")


class TestBuiltinProfile(unittest.TestCase):
    """内置 profile 的自检：动作合法、结构完整、真执行必须 --yes。"""

    @classmethod
    def setUpClass(cls):
        cls.profile = clicker._load_yaml(
            Path(__file__).resolve().parents[1] / "scripts" / "profiles" / "wechat_batch_downloader.yaml")

    def test_window_spec_present(self):
        self.assertIn("regex", self.profile["window"])
        self.assertTrue(self.profile["window"]["regex"])

    def test_all_actions_whitelisted(self):
        for step in self.profile["steps"]:
            self.assertIn(step["action"], clicker._ACTIONS, step.get("name"))

    def test_every_step_has_target_except_pure_actions(self):
        for step in self.profile["steps"]:
            if step["action"] in ("sleep", "screenshot", "wait_file", "activate"):
                continue
            self.assertIn("target", step, step.get("name"))

    def test_targets_are_dicts_or_lists_of_dicts(self):
        for step in self.profile["steps"]:
            target = step.get("target")
            if target is None:
                continue
            candidates = target if isinstance(target, list) else [target]
            self.assertTrue(candidates, step.get("name"))
            for candidate in candidates:
                self.assertIsInstance(candidate, dict, step.get("name"))
                self.assertTrue(
                    {"auto_id", "control_type", "name", "name_regex"} & set(candidate),
                    f"{step.get('name')} 的选择器没有可用键")

    def test_run_requires_yes_when_not_dry_run(self):
        code = clicker.main(["run", "--profile", "wechat_batch_downloader"])
        self.assertEqual(code, clicker.EXIT_PARAM)

    def test_collection_policy_matches_user_spec(self):
        """采集口径（2026-10-23 用户截图指定）：只留 MD + 图片/音频/视频。

        为什么这条要写成断言而不是注释：工具会**记住上次的勾选**，实测残留
        「下载评论/下载评论回复 = 开」；一旦 profile 只写"勾选想要的那几个"，
        残留项就会被静默带进来，产物多出一堆评论区文本，下游还得重洗。
        所以每个开关都必须被**显式**设成 true/false，不允许沉默。
        """
        want_on = {"导出MD文件", "下载图片/音频/视频"}
        want_off = {"导出PDF", "导出WORD", "导出MHTML文件", "下载评论", "下载评论回复",
                    "文件开头添加日期", "自动监听剪切板", "只下载原创"}
        states = {}
        for step in self.profile["steps"]:
            if step["action"] != "toggle":
                continue
            names = [c.get("name") for c in
                     (step["target"] if isinstance(step["target"], list) else [step["target"]])]
            key = next((n for n in names if n), None)
            states[key] = step["state"]
        for n in want_on:
            self.assertIs(states.get(n), True, "%s 必须勾选" % n)
        for n in want_off:
            self.assertIs(states.get(n), False, "%s 必须显式取消" % n)
        # 证伪：除了上面这些 + 本机恒灰的 HTML，不允许有"没被显式设置"的开关
        self.assertEqual(set(states), want_on | want_off | {"导出HTML文件"})

    def test_time_range_is_last_month(self):
        """时间范围固定在「一个月内」，且必须是真实鼠标点击（单选对 Invoke 假成功）。"""
        hits = [s for s in self.profile["steps"] if s.get("name", "").endswith("（一个月内）")]
        self.assertEqual(len(hits), 1, "缺「设置时间范围（一个月内）」这一步")
        self.assertEqual(hits[0]["action"], "click")

    def test_numeric_settings(self):
        """等待 10s / 阅读量阈值 0 / 页数 -1（全部）三个数值必须写死。"""
        nums = {s["name"]: s["value"] for s in self.profile["steps"]
                if s["action"] == "set_value"}
        self.assertEqual(nums.get("设置等待时间（秒）"), "10")
        self.assertEqual(nums.get("设置下载超过阅读量的文章阈值"), "0")
        self.assertEqual(nums.get("设置开始下载页数（-1 = 全部）"), "-1")


class TestWindowSelect(unittest.TestCase):
    """窗口挑选：类名稳定、标题会变（真机实测会变成进程名 wechatdownload）。"""

    def test_class_whitelist_wins_when_title_changes(self):
        candidates = [
            {"pid": 1, "handle": 100, "title": "wechatdownload", "class_name": "Mywindow"},
            {"pid": 2, "handle": 200, "title": "微信公众号文章批量下载工具4.0", "class_name": "Other"},
        ]
        got = clicker.select_windows(candidates, ".*公众号.*下载工具.*", ["Mywindow"])
        self.assertEqual([w["handle"] for w in got], [100])

    def test_title_only_still_works_without_whitelist(self):
        candidates = [{"pid": 1, "handle": 100, "title": "微信文章工具", "class_name": "X"}]
        self.assertEqual(len(clicker.select_windows(candidates, "微信文章", None)), 1)
        self.assertEqual(clicker.select_windows(candidates, "不存在的标题", None), [])

    def test_prefers_title_hit_among_same_class(self):
        candidates = [
            {"pid": 1, "handle": 100, "title": "辅助窗", "class_name": "Mywindow"},
            {"pid": 1, "handle": 300, "title": "公众号下载工具", "class_name": "Mywindow"},
        ]
        got = clicker.select_windows(candidates, "公众号下载工具", ["Mywindow"])
        self.assertEqual(got[0]["handle"], 300)


class TestWaitFile(unittest.TestCase):
    """下载完成不能只靠日志：落盘文件是独立证据。"""

    def setUp(self):
        import tempfile

        self.dir = Path(tempfile.mkdtemp(prefix="uac-"))

    def tearDown(self):
        import shutil

        shutil.rmtree(self.dir, ignore_errors=True)

    def test_ok_when_enough_fresh_files(self):
        (self.dir / "a.md").write_text("x", encoding="utf-8")
        (self.dir / "b.pdf").write_text("x", encoding="utf-8")
        result = clicker.run_step(None, {
            "name": "等文件", "action": "wait_file", "path": str(self.dir / "*"),
            "min_count": 2, "timeout": 1, "interval": 0.1,
        }, {}, dry_run=False)
        self.assertEqual(result["status"], "ok")
        self.assertIn("2/2", result["detail"])

    def test_times_out_raises(self):
        with self.assertRaises(RuntimeError):
            clicker.run_step(None, {
                "name": "等文件", "action": "wait_file", "path": str(self.dir / "*"),
                "min_count": 3, "timeout": 0.2, "interval": 0.1,
            }, {}, dry_run=False)

    def test_optional_degrades_to_warn(self):
        result = clicker.run_step(None, {
            "name": "等文件", "action": "wait_file", "path": str(self.dir / "*"),
            "min_count": 3, "timeout": 0.2, "interval": 0.1, "optional": True,
        }, {}, dry_run=False)
        self.assertEqual(result["status"], "warn")

    def test_old_files_ignored_when_only_new(self):
        """目录里本来就有旧文件时，不能因为"数到了"就判下载成功。"""
        old = self.dir / "old.md"
        old.write_text("x", encoding="utf-8")
        import os
        import time

        stamp = time.time() - 3600
        os.utime(old, (stamp, stamp))
        with self.assertRaises(RuntimeError):
            clicker.run_step(None, {
                "name": "等文件", "action": "wait_file", "path": str(self.dir / "*"),
                "min_count": 1, "timeout": 0.2, "interval": 0.1, "only_new": True,
            }, {}, dry_run=False)
        # 关掉 only_new 就该数到它
        result = clicker.run_step(None, {
            "name": "等文件", "action": "wait_file", "path": str(self.dir / "*"),
            "min_count": 1, "timeout": 1, "interval": 0.1, "only_new": False,
        }, {}, dry_run=False)
        self.assertEqual(result["status"], "ok")


class TestSliceSteps(unittest.TestCase):
    """分段推进：--from-step 必须真的"从中间开始"，否则会重复点有副作用的按钮。"""

    def setUp(self):
        self.steps = [{"name": f"s{i}"} for i in range(1, 16)]

    def test_default_runs_all(self):
        plan = clicker.slice_steps(self.steps)
        self.assertEqual([i for i, _ in plan], list(range(1, 16)))

    def test_from_step_starts_in_the_middle(self):
        plan = clicker.slice_steps(self.steps, from_step=12)
        self.assertEqual([i for i, _ in plan], [12, 13, 14, 15])
        self.assertEqual(plan[0][1]["name"], "s12")

    def test_max_steps_is_absolute_index(self):
        plan = clicker.slice_steps(self.steps, from_step=2, max_steps=4)
        self.assertEqual([i for i, _ in plan], [2, 3, 4])

    def test_max_steps_before_from_step_rejected(self):
        with self.assertRaises(ValueError):
            clicker.slice_steps(self.steps, from_step=10, max_steps=5)

    def test_bad_range_returns_param_exit(self):
        code = clicker.main(["run", "--profile", "wechat_batch_downloader",
                             "--dry-run", "--from-step", "10", "--max-steps", "5"])
        self.assertEqual(code, clicker.EXIT_PARAM)


class TestWaitControl(unittest.TestCase):
    """主按钮文字会在运行中变成「暂停中...」——必须等它变回来才点。"""

    def _flaky(self, settle_at=3):
        class Flaky(FakeControl):
            def __init__(self):
                super().__init__("暂停中...", "Form.PrimaryPushButton", "Button")
                self.calls = 0

            def window_text(self):
                self.calls += 1
                return "暂停中..." if self.calls < settle_at else "2.批量下载文章"

        return Flaky()

    def test_waits_until_text_settles(self):
        control = self._flaky(settle_at=3)
        result = clicker.run_step(FakeWindow([control]), {
            "name": "等就绪", "action": "wait_control", "timeout": 2, "interval": 0.01,
            "expect_name_regex": "批量下载", "require_enabled": True,
            "target": {"auto_id": "Form.PrimaryPushButton"},
        }, {}, dry_run=False)
        self.assertEqual(result["status"], "ok")
        self.assertGreaterEqual(control.calls, 3)

    def test_timeout_raises(self):
        control = self._flaky(settle_at=10 ** 6)
        with self.assertRaises(RuntimeError):
            clicker.run_step(FakeWindow([control]), {
                "name": "等就绪", "action": "wait_control", "timeout": 0.1, "interval": 0.01,
                "expect_name_regex": "批量下载",
                "target": {"auto_id": "Form.PrimaryPushButton"},
            }, {}, dry_run=False)

    def test_dry_run_does_not_assert_runtime_state(self):
        control = self._flaky(settle_at=10 ** 6)   # 永远不满足
        result = clicker.run_step(FakeWindow([control]), {
            "name": "等就绪", "action": "wait_control", "timeout": 1,
            "expect_name_regex": "批量下载",
            "target": {"auto_id": "Form.PrimaryPushButton"},
        }, {}, dry_run=True)
        self.assertEqual(result["status"], "plan")


class TestWaitStable(unittest.TestCase):
    """判任务结束：靠"输出不再变化"，且窗口要够长（限速暂停会静止 19 秒）。"""

    def _feeding(self, frames):
        class Feeding(FakeControl):
            def __init__(self):
                super().__init__("", "Form.TextEdit", "Edit", text=frames[0])
                self.calls = 0

            def window_text(self):
                self.calls += 1
                index = min(self.calls // 2, len(frames) - 1)
                return frames[index]

        return Feeding()

    def test_done_after_output_stops(self):
        control = self._feeding(["a", "ab", "abc"])
        result = clicker.run_step(FakeWindow([control]), {
            "name": "等稳定", "action": "wait_stable",
            "stable_seconds": 0.3, "interval": 0.1, "timeout": 5,
            "target": {"auto_id": "Form.TextEdit"},
        }, {}, dry_run=False)
        self.assertEqual(result["status"], "ok")

    def test_busy_output_never_stabilises_times_out(self):
        class Busy(FakeControl):
            def __init__(self):
                super().__init__("", "Form.TextEdit", "Edit", text="x")
                self.n = 0

            def window_text(self):
                self.n += 1
                return "x" * self.n      # 每条都不一样，永远不稳定

        with self.assertRaises(RuntimeError):
            clicker.run_step(FakeWindow([Busy()]), {
                "name": "等稳定", "action": "wait_stable",
                "stable_seconds": 0.5, "interval": 0.1, "timeout": 0.5,
                "target": {"auto_id": "Form.TextEdit"},
            }, {}, dry_run=False)

    def test_dry_run_returns_plan(self):
        control = self._feeding(["a"])
        result = clicker.run_step(FakeWindow([control]), {
            "name": "等稳定", "action": "wait_stable", "stable_seconds": 60,
            "target": {"auto_id": "Form.TextEdit"},
        }, {}, dry_run=True)
        self.assertEqual(result["status"], "plan")


class _RectControl(FakeControl):
    """带真实矩形的控件替身：click 分支要算中心点，FakeControl 只有 left/top。"""

    def __init__(self, auto_id, name, left=100, top=200, right=180, bottom=240):
        super().__init__(name=name, auto_id=auto_id, control_type="Button")
        self._rect = SimpleNamespace(left=left, top=top, right=right, bottom=bottom)
        self.clicks = 0

    def rectangle(self):
        return self._rect

    def click_input(self):
        self.clicks += 1


class TestClickGuard(unittest.TestCase):
    """真实鼠标点击只认**坐标归属**，与"谁是前台"无关。

    2026-10-23 真机事故：pipeline 启动下载工具后点「1.获取公众号id」，日志一个字
    都没变 —— 点击落到了窗口之外。三层根因（都写进断言）：
      ① 坐标系错位：clicker 没做 DPI 感知 ⇒ UIA 给物理像素、GetWindowRect 给逻辑
         像素，按钮中心算到 (1744,252)，而窗口只有 (230,65,1234,779)；
      ② 前台锁让 SetForegroundWindow 静默失效，于是"前台不是自己"成了常态；
      ③ 真实鼠标点击只认最上层窗口，与焦点无关。
    """

    def _window(self, handle=4242):
        ctrl = _RectControl("Form.PushButton", "1.获取公众号id")
        win = FakeWindow([ctrl])
        win.handle = handle
        return win, ctrl

    def _patches(self, at, focus=4242, rect=(0, 0, 2000, 2000)):
        return [
            mock.patch.object(clicker, "_window_at", side_effect=at) if callable(at)
            else mock.patch.object(clicker, "_window_at", return_value=at),
            mock.patch.object(clicker, "_window_rect", return_value=rect),
            mock.patch.object(clicker, "_raise_window"),
            mock.patch.object(clicker, "_focus_window", return_value=focus),
        ]

    def test_refuses_when_point_belongs_to_other_window(self):
        win, ctrl = self._window()
        ps = self._patches(777)
        for p in ps:
            p.start()
            self.addCleanup(p.stop)
        with self.assertRaises(RuntimeError) as ctx:
            clicker.run_step(win, {
                "name": "点按钮", "action": "click",
                "target": {"auto_id": "Form.PushButton"},
            }, {}, dry_run=False)
        self.assertIn("777", str(ctx.exception))
        self.assertEqual(ctrl.clicks, 0, "归属不对时绝不能真点")

    def test_refuses_when_point_outside_window_rect(self):
        """守卫 0：点必须落在窗口矩形内 —— 这条专治坐标系错位。

        真机数据：按钮中心 (1744,252)、窗口 (230,65,1234,779)，差 500+ 像素。
        UIA 说是这个按钮，GetWindowRect 说窗口不在这儿，两者不可能同时对。
        """
        win, ctrl = self._window()
        ps = self._patches(4242, rect=(230, 65, 1234, 779))
        for p in ps:
            p.start()
            self.addCleanup(p.stop)
        with self.assertRaises(RuntimeError) as ctx:
            clicker.run_step(win, {
                "name": "点按钮", "action": "click",
                "target": {"auto_id": "Form.PushButton"},
            }, {}, dry_run=False)
        self.assertIn("坐标系", str(ctx.exception))
        self.assertEqual(ctrl.clicks, 0)

    def test_self_heals_once_after_raise(self):
        """第一次归属不对 → 提 z 序 + 抢焦点后重核，正确了才点。"""
        win, ctrl = self._window()
        seq = [888, 4242]
        ps = self._patches(lambda x, y: seq.pop(0))
        for p in ps:
            p.start()
            self.addCleanup(p.stop)
        result = clicker.run_step(win, {
            "name": "点按钮", "action": "click",
            "target": {"auto_id": "Form.PushButton"},
        }, {}, dry_run=False)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(ctrl.clicks, 1)

    def test_click_ok_when_point_belongs_to_target(self):
        win, ctrl = self._window()
        ps = self._patches(4242)
        ps[2] = mock.patch.object(clicker, "_raise_window")
        for p in ps:
            p.start()
            self.addCleanup(p.stop)
        result = clicker.run_step(win, {
            "name": "点按钮", "action": "click",
            "target": {"auto_id": "Form.PushButton"},
        }, {}, dry_run=False)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(ctrl.clicks, 1)

    def test_activate_does_not_raise_when_focus_blocked(self):
        """前台锁抢不到焦点不算失败：只要**坐标归属**是目标窗口就够。

        2026-10-23 真机：旧实现这里会连试 3 次然后抛错，整个 profile 直接中断 ——
        而工具其实是可以点的（真机上就是这么误判成"激活失败"）。
        2026-10-26 加固后判据换成"窗口中心坐标归属"：前台被别的程序占着
        （本机常态，前台是 WorkBuddy）但窗口确实在最上层 ⇒ 依然放行。
        """
        win, _ = self._window()
        import ctypes
        with mock.patch.object(clicker, "_raise_window") as raised, \
             mock.patch.object(clicker, "_focus_window", return_value=999), \
             mock.patch.object(clicker, "_window_rect", return_value=(0, 0, 800, 600)), \
             mock.patch.object(clicker, "_window_info",
                               return_value={"hwnd": 4242, "title": "工具",
                                             "cls": "Mywindow", "rect": [0, 0, 800, 600]}), \
             mock.patch.object(clicker, "time"), \
             mock.patch.object(ctypes.windll.user32, "ShowWindow", lambda *a: 1):
            result = clicker.run_step(win, {"name": "激活", "action": "activate"},
                                      {}, dry_run=False)
        self.assertEqual(result["status"], "ok")
        self.assertIn("999", result["detail"])
        raised.assert_called_once()


class TestTemplateVars(unittest.TestCase):
    """`${VAR}` 模板替换 + 空值跳过。

    存在的理由：profile 是静态 YAML，而「微信文章链接」框的内容每次运行都不同。
    2026-10-23 真机确认：这个框留空时点「1.获取公众号id」工具**一个日志字都不写**，
    所以必须能把值传进去，且"没传"要能干净地跳过（不是失败）。
    """

    def setUp(self):
        self.edit = FakeControl("", "Form.PlainTextEdit", "Edit", text="")
        self.window = FakeWindow([self.edit])

    def test_render_substitutes_from_vars(self):
        self.assertEqual(clicker._render("${A}/x", {"vars": {"A": "http://u"}}), "http://u/x")

    def test_render_missing_var_becomes_empty(self):
        self.assertEqual(clicker._render("${NOPE}", {"vars": {}}), "")

    def test_render_leaves_plain_value_alone(self):
        self.assertEqual(clicker._render("10", {}), "10")

    def test_set_value_with_var(self):
        result = clicker.run_step(self.window, {
            "name": "填链接", "action": "set_value", "value": "${ARTICLE_URL}",
            "target": {"auto_id": "Form.PlainTextEdit"},
        }, {"vars": {"ARTICLE_URL": "https://mp.weixin.qq.com/s?__biz=X"}}, dry_run=False)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(self.edit.get_value(), "https://mp.weixin.qq.com/s?__biz=X")

    def test_empty_var_skips_without_touching_control(self):
        result = clicker.run_step(self.window, {
            "name": "填链接", "action": "set_value", "value": "${ARTICLE_URL}",
            "skip_if_empty": True, "target": {"auto_id": "Form.PlainTextEdit"},
        }, {"vars": {}}, dry_run=False)
        self.assertEqual(result["status"], "skip")
        self.assertEqual(self.edit.get_value(), "")
        self.assertEqual(self.edit._text, "")

    def test_var_is_rendered_in_dry_run_plan(self):
        result = clicker.run_step(self.window, {
            "name": "填链接", "action": "set_value", "value": "${ARTICLE_URL}",
            "target": {"auto_id": "Form.PlainTextEdit"},
        }, {"vars": {"ARTICLE_URL": "abc"}}, dry_run=True)
        self.assertEqual(result["status"], "plan")


if __name__ == "__main__":
    unittest.main()
