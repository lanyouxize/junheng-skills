#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""条件跳步（when_var / when_equals / when_in / when_default）的离线测试。

存在理由：同一位置需要"按运行参数二选一"的互斥步骤（下载工具的时间范围是单选
按钮，想取全部历史点「全部」、按月取点「一个月内」）。`${VAR}` 渲染只作用于
`value`，改不了 selector 的 `name`，所以只能在步骤粒度上做条件执行。

这套判据有一个致命的失败模式必须锁死：**判错就跳错**——跳掉的偏偏是唯一真正
生效的那一步，产物照样"成功"，只是少了内容，比报错更难发现。所以断言不能只看
返回值，还要证明副作用函数（resolve / click_input / set_edit_text）**零调用**。
"""
from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import clicker  # noqa: E402


class FakeEdit:
    """最小 Edit 替身：只实现 set_value 真正用到的三个方法。"""

    def __init__(self):
        self.text = ""
        self.set_calls = 0

    def set_edit_text(self, value):
        self.set_calls += 1
        self.text = value

    def get_value(self):
        return self.text

    def window_text(self):
        return ""


class FakeWindow:
    def __init__(self, controls):
        self.controls = list(controls)
        self.handle = 1

    def descendants(self, **kwargs):
        control_type = kwargs.get("control_type")
        if control_type:
            return [c for c in self.controls
                    if c.element_info.control_type == control_type]
        return list(self.controls)


def edit_control(auto_id="Form.LineEdit_2"):
    control = FakeEdit()
    control.element_info = SimpleNamespace(
        automation_id=auto_id, control_type="Edit", class_name="Fake")
    return control


def set_value_step(**extra):
    step = {"name": "写一个值", "action": "set_value", "value": "10",
            "target": {"auto_id": "Form.LineEdit_2"}}
    step.update(extra)
    return step


class TestNoCondition(unittest.TestCase):
    """回归：没写任何 when_* 字段的步骤，行为必须和以前一字不差。"""

    def test_plain_step_executes(self):
        control = edit_control()
        result = clicker.run_step(FakeWindow([control]), set_value_step(), {}, dry_run=False)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(control.text, "10")
        self.assertEqual(control.set_calls, 1)


class TestWhenEquals(unittest.TestCase):
    def test_match_executes(self):
        control = edit_control()
        result = clicker.run_step(
            FakeWindow([control]),
            set_value_step(when_var="RANGE", when_equals="all"),
            {"vars": {"RANGE": "all"}}, dry_run=False)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(control.set_calls, 1)

    def test_mismatch_skips_without_touching_anything(self):
        """不匹配时必须**真的什么都不做**：连选择器解析都不许发生。"""
        control = edit_control()
        window = FakeWindow([control])
        with mock.patch.object(clicker, "resolve",
                               side_effect=AssertionError("跳过的步骤不该去定位控件")) as resolver:
            result = clicker.run_step(
                window, set_value_step(when_var="RANGE", when_equals="all"),
                {"vars": {"RANGE": "monthly"}}, dry_run=False)
        resolver.assert_not_called()
        self.assertEqual(result["status"], "skip")
        self.assertIn("RANGE=monthly", result["detail"])
        self.assertEqual(control.set_calls, 0)
        self.assertEqual(control.text, "")


class TestWhenIn(unittest.TestCase):
    def test_hit_executes(self):
        control = edit_control()
        result = clicker.run_step(
            FakeWindow([control]),
            set_value_step(when_var="RANGE", when_in=["all", "全部"]),
            {"vars": {"RANGE": "全部"}}, dry_run=False)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(control.set_calls, 1)

    def test_miss_skips(self):
        control = edit_control()
        result = clicker.run_step(
            FakeWindow([control]),
            set_value_step(when_var="RANGE", when_in=["all", "全部"]),
            {"vars": {"RANGE": "monthly"}}, dry_run=False)
        self.assertEqual(result["status"], "skip")
        self.assertEqual(control.set_calls, 0)


class TestWhenDefault(unittest.TestCase):
    def test_missing_var_runs_default_branch(self):
        """缺省分支：不传 RANGE 时走 when_default 那条（默认取全部历史）。"""
        control = edit_control()
        result = clicker.run_step(
            FakeWindow([control]),
            set_value_step(when_var="RANGE", when_in=["all"], when_default=True),
            {"vars": {}}, dry_run=False)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(control.set_calls, 1)

    def test_missing_var_without_default_skips(self):
        control = edit_control()
        result = clicker.run_step(
            FakeWindow([control]),
            set_value_step(when_var="RANGE", when_in=["monthly"]),
            {"vars": {}}, dry_run=False)
        self.assertEqual(result["status"], "skip")
        self.assertEqual(control.set_calls, 0)

    def test_default_does_not_leak_into_a_mismatch(self):
        """传了值就按值判：when_default 只兜"没传"，不能变成"永远执行"。"""
        control = edit_control()
        result = clicker.run_step(
            FakeWindow([control]),
            set_value_step(when_var="RANGE", when_in=["all"], when_default=True),
            {"vars": {"RANGE": "monthly"}}, dry_run=False)
        self.assertEqual(result["status"], "skip")
        self.assertEqual(control.set_calls, 0)


class TestUnknownActionStillFails(unittest.TestCase):
    def test_action_typo_is_not_swallowed_by_skip(self):
        """动作名写错必须当场报错：不能被"这一步恰好没轮到"掩盖成 skip。"""
        with self.assertRaises(RuntimeError):
            clicker.run_step(None, {"name": "x", "action": "clik",
                                    "when_var": "RANGE", "when_equals": "all"},
                             {"vars": {"RANGE": "monthly"}}, dry_run=True)


class TestCmdRunExitCode(unittest.TestCase):
    """skip 是合法分支：不许把退出码拉成 5（PARTIAL）。

    这条只能在 `cmd_run` 级别验：`run_step` 只返回 dict，退出码是 `cmd_run` 累加
    `warned` 算出来的。曾经把 skip 混进 warned，结果是编排层把正常流程判成"部分
    失败"并重跑，而重跑还是跳同一步，永远收不了尾。
    """

    PROFILE = """
window:
  regex: '.*不存在的窗口.*'
  classes: [NoSuchClass]
steps:
  - name: 走不到的分支
    action: sleep
    seconds: 0
    when_var: RANGE
    when_in: ["all"]
  - name: 走得到的分支
    action: sleep
    seconds: 0
    when_var: RANGE
    when_in: ["monthly"]
"""

    def _run(self, var_args):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "when_case.yaml"
            path.write_text(self.PROFILE, encoding="utf-8")
            win = {"handle": 1, "pid": 1, "title": "t", "class_name": "NoSuchClass"}
            out = io.StringIO()
            # cmd_run 现在会先 _window_rect(handle) 记下窗口原位（点击避让遮挡后还原）。
            # 假窗口的 handle=1 不是真句柄，不替身掉就会 GetWindowRect 报 1400
            # —— 与被测行为（skip 不该变成 PARTIAL）无关，故在这里挡掉。
            with mock.patch.object(clicker, "find_windows", return_value=[win]), \
                    mock.patch.object(clicker, "_window_rect",
                                      return_value=(0, 0, 1920, 1080)), \
                    mock.patch.object(clicker, "attach", return_value=win), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                code = clicker.main(["run", "--profile", str(path), "--dry-run"]
                                    + list(var_args))
            return code, out.getvalue()

    def test_skip_does_not_become_partial(self):
        code, out = self._run(["--var", "RANGE=monthly"])
        self.assertEqual(code, clicker.EXIT_OK, "skip 不许把退出码变成 5（PARTIAL）")
        self.assertIn('"skipped": 1', out)
        self.assertIn('"warned": 0', out)

    def test_no_warn_event_for_skip(self):
        _code, out = self._run(["--var", "RANGE=monthly"])
        self.assertNotIn('"level": "warn"', out)


class TestProfileRangeSteps(unittest.TestCase):
    """内置 profile 的时间范围必须是**互斥分支**，且默认走「全部历史」。

    为什么把结构也写成断言：这些步骤一旦退化成一步（或多加一条无条件步骤），
    RANGE 参数就变成摆设 —— 表里跑得通、参数也传了，但点下去的还是原来那个
    范围，产物照旧缺篇，从输出上完全看不出来。

    2026-11-01 起多了一条「自定义」分支（逐月回溯要有精确起止日：工具的
    「一个月内」相对今天、推不回历史），所以断言从"必须恰好两步"改成
    "单选分支三条互斥 + 日期两步只属于自定义分支"。
    """

    @classmethod
    def setUpClass(cls):
        cls.steps = clicker._load_yaml(
            Path(__file__).resolve().parents[1] / "scripts" / "profiles"
            / "wechat_batch_downloader.yaml")["steps"]
        cls.range_steps = [s for s in cls.steps if s.get("when_var") == "RANGE"]
        cls.radio_steps = [s for s in cls.range_steps if s["action"] == "click"]
        cls.date_steps = [s for s in cls.range_steps if s["action"] == "set_date"]

    def test_range_branches_are_exclusive_clicks(self):
        self.assertEqual(len(self.radio_steps), 3,
                         "时间范围三条互斥单选：全部 / 一个月内 / 自定义")
        for step in self.radio_steps:
            self.assertEqual(step["action"], "click",
                             "单选按钮对 Invoke 假成功，必须真实鼠标点击")
            self.assertNotIn("when_equals", step)
            self.assertEqual(len(step["when_in"]), 2, "中英两种取值都要认")
        # 三个分支的 when_in 不许重叠，否则两条同时命中 → 点两次、最后点的赢
        seen = set()
        for step in self.radio_steps:
            overlap = seen & set(step["when_in"])
            self.assertFalse(overlap, "分支取值重复：%s" % overlap)
            seen |= set(step["when_in"])
        self.assertEqual(seen, {"all", "全部", "monthly", "一个月内", "custom", "自定义"})

    def test_date_steps_belong_to_custom_branch_only(self):
        """日期两步只在 RANGE=custom 时跑；否则会把默认范围偷偷改成自定义。"""
        self.assertEqual(len(self.date_steps), 2, "自定义要起止两个日期")
        for step in self.date_steps:
            self.assertEqual(step["when_in"], ["custom", "自定义"])
            self.assertIn("${DATE_", step["value"], "日期必须由变量注入，不能写死")
        # 必须有 target 指向真实日期框（auto_id 是唯一稳定标识）
        ids = [c.get("auto_id") for s in self.date_steps for c in s["target"]]
        self.assertIn("Form.layoutWidget.dateEdit", ids)
        self.assertIn("Form.layoutWidget.dateEdit_2", ids)

    def test_date_steps_sit_right_after_custom_radio(self):
        """顺序约束：先点「自定义」单选，再写日期（顺序反了日期框会重排）。"""
        names = [s.get("name") for s in self.steps]
        custom_at = next(i for i, s in enumerate(self.steps)
                         if s["action"] == "click"
                         and "自定义" in (s.get("when_in") or []))
        self.assertEqual([s["action"] for s in self.steps[custom_at + 1:custom_at + 3]],
                         ["set_date", "set_date"])

    def test_default_is_all_history(self):
        default = [s for s in self.range_steps if s.get("when_default")]
        self.assertEqual(len(default), 1, "只允许一条缺省分支，否则两边都执行")
        names = [c.get("name") for c in default[0]["target"]]
        self.assertIn("全部", names, "缺省必须取全部历史（一个月内会漏掉更早的篇目）")

    def test_both_sit_right_after_the_link_step(self):
        """顺序约束：切换时间范围会重排日期框，必须排在其他设置之后。

        这里锚定"紧跟在填入微信文章链接之后、且两步相邻"，比断言"最后一步"稳：
        后面还有真操作段（点按钮/等日志），它们不依赖日期框坐标。
        """
        names = [s.get("name") for s in self.steps]
        link_at = names.index("填入微信文章链接（变量 ARTICLE_URL）")
        first, second = self.range_steps[0]["name"], self.range_steps[1]["name"]
        body = names[link_at + 1:link_at + 4]
        # 中间那条 activate 是硬要求（见下一条用例），顺序：链接 → activate → 两条范围
        self.assertEqual(body[1:], [first, second], body)

    def test_activate_precedes_the_range_clicks(self):
        """两条范围点击之前必须有一条 activate，且是紧邻的。

        2026-10-26 真机教训：鼠标点击落到"屏幕上该坐标最上层窗口"，与焦点无关。
        工具被别的窗口盖住时，实测点了「全部」、回读仍是「一年内」=1，而当时日志
        报的是 ok —— 既没生效也没报错。全表另外两处真实点击都配了 activate，
        只有这两步漏了。后人看到这里会以为是冗余步骤，所以把它锁成断言。
        """
        names = [s.get("name") for s in self.steps]
        at = names.index(self.range_steps[0]["name"])
        prev = self.steps[at - 1]
        self.assertEqual(prev["action"], "activate",
                         "设置时间范围前的上一步必须是 activate（否则点击可能落到遮挡窗口）")
        self.assertIn("遮挡", prev["name"], "步骤名要自带原因，避免被当成冗余删掉")


if __name__ == "__main__":
    unittest.main()
