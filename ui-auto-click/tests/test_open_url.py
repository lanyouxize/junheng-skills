#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「在微信内置浏览器打开链接」的离线测试（不启动微信、不发真实点击）。

为什么这一层必须有测试：这条链路的三步里，**没有任何一步能在事后验证**——
CEF 读不到页面文字，点没点中放大镜、剪贴板吃没吃下 URL，全都无迹可寻。
唯一能守住的是：
  ① 链接选对（profile_ext 而不是文章链接，否则工具永远「获取密钥失败」）；
  ② 放大镜定位有模板优先 + 右锚点兜底（换微信版本时不会直接崩）；
  ③ clicker 的 open_url 动作在拿不到链接/打开失败时必须**大声报错**，
     而不是静默往下走去点「2.批量下载文章」（那样只会等 300 秒超时，把真因埋掉）。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import clicker  # noqa: E402
import wechat_open_url as wou  # noqa: E402

ARTICLE_URL = "https://mp.weixin.qq.com/s/4i60xBe77q2QjTHNbSwZ6w"
PROFILE_URL = ("https://mp.weixin.qq.com/mp/profile_ext?action=home&__biz="
               "MzYyMzg4MjkxMg==&scene=124#wechat_redirect")


# ------------------------------------------------------------------ 链接选取
class TestFindUrlInText(unittest.TestCase):
    """日志里同时有文章链接和 profile_ext；只有后者能让工具读到 cookie。"""

    def test_prefers_profile_ext(self):
        text = "抓到文章 %s\n请在微信打开复制的链接 %s\ntail" % (ARTICLE_URL, PROFILE_URL)
        self.assertEqual(wou.find_url_in_text(text), PROFILE_URL)

    def test_falls_back_to_last_url(self):
        text = "旧链接 %s 新链接 %s" % (ARTICLE_URL, ARTICLE_URL.replace("4i60", "9x99"))
        self.assertIn("9x99", wou.find_url_in_text(text))

    def test_none_when_no_url(self):
        self.assertIsNone(wou.find_url_in_text("开始获取密钥...\n获取密钥失败"))
        self.assertIsNone(wou.find_url_in_text(""))

    def test_ignores_other_hosts(self):
        self.assertIsNone(wou.find_url_in_text("https://example.com/a?b=1"))

    def test_profile_ext_secret_link_intact(self):
        """密钥链接（profile_ext）必须字节级完整：__biz 的 == 与 #wechat_redirect
        都不能丢——丢了工具就拿不到 cookie、永远「获取密钥失败」。"""
        secret = ("https://mp.weixin.qq.com/mp/profile_ext?action=home"
                  "&__biz=Mzk0MjY5NTEzOA==&scene=124#wechat_redirect")
        self.assertEqual(wou.find_url_in_text(secret), secret)
        self.assertTrue(secret.endswith("#wechat_redirect"))
        self.assertIn("__biz=Mzk0MjY5NTEzOA==", wou.find_url_in_text(secret))

    def test_strips_trailing_cjk_punctuation(self):
        """链接后紧跟中文标点/符号时，多吞的部分要剥掉，不能带进 URL。"""
        base = ("https://mp.weixin.qq.com/mp/profile_ext?action=home"
                "&__biz=Mzk0MjY5NTEzOA==&scene=124#wechat_redirect")
        for tail in ("。下次再试", "，结尾", "；", "：说明", "！"):
            got = wou.find_url_in_text("请在微信打开复制的链接：" + base + tail)
            self.assertEqual(got, base, "尾部 %r 应被剥掉" % tail)

    def test_does_not_strip_valid_url_terminators(self):
        """合法结尾（== / #fragment / &参数 / .）绝不能误剥。"""
        secret = ("https://mp.weixin.qq.com/mp/profile_ext?action=home"
                  "&__biz=Mzk0MjY5NTEzOA==&scene=124#wechat_redirect")
        # 尾部无任何噪声时保持原样（回归：rstrip 不能削掉合法结尾）
        self.assertEqual(wou.find_url_in_text(secret + "  \n"), secret)
        self.assertEqual(wou.find_url_in_text("x " + secret), secret)


# ------------------------------------------------------------------ 放大镜定位
class TestFindSearchIcon(unittest.TestCase):
    def _hay(self):
        from PIL import Image, ImageDraw

        img = Image.new("RGB", (1652, 400), (245, 245, 245))
        # 纹理必须落在模板裁剪区内（1417..1447 / 30..59），否则模板是纯色，
        # cv2.matchTemplate 会在 (0,0) 处以 1.0 命中 —— 测试假绿。
        d = ImageDraw.Draw(img)
        d.ellipse((1422, 34, 1434, 46), outline=(20, 20, 20), width=2)   # 镜片
        d.line((1433, 45, 1441, 53), fill=(20, 20, 20), width=2)          # 手柄
        return img

    def test_template_hit(self):
        import tempfile
        from PIL import Image

        hay = self._hay()
        tpl = hay.crop((1417, 30, 1447, 59))       # 与真机模板同尺寸 30x29
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tpl.png"
            tpl.save(path)
            x, y, source, score = wou.find_search_icon(hay, path)
        self.assertEqual(source, "template")
        self.assertAlmostEqual(score, 1.0, places=2)
        self.assertAlmostEqual(x, 1432, delta=2)
        self.assertAlmostEqual(y, 44, delta=2)

    def test_anchor_when_template_missing(self):
        """模板缺失也必须能点：右锚点按窗口宽度推算（按钮组右对齐）。"""
        x, y, source, score = wou.find_search_icon(
            self._hay(), Path("templates/__nope__.png"))
        self.assertEqual((source, score), ("anchor", None))
        self.assertEqual(x, 1652 - wou.SEARCH_RIGHT_OFFSET)
        self.assertEqual(y, wou.SEARCH_TOP)

    def test_anchor_when_hit_far_from_right_edge(self):
        """纯色画面 + 零方差模板会让 cv2 返回假 1.0 并命中 (0,0)。

        裸放行就会点到窗口左上角（比不点更糟）。位置守卫必须把它打回右锚点。
        """
        import tempfile
        from PIL import Image

        hay = Image.new("RGB", (1652, 400), (255, 255, 255))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tpl.png"
            Image.new("RGB", (30, 29), (0, 0, 0)).save(path)
            x, y, source, _score = wou.find_search_icon(hay, path)
        self.assertEqual(source, "anchor")
        self.assertEqual(x, 1652 - wou.SEARCH_RIGHT_OFFSET)
        self.assertEqual(y, wou.SEARCH_TOP)


# ------------------------------------------------------------------ open_in_wechat
class TestOpenInWechat(unittest.TestCase):
    def test_rejects_non_wechat_url(self):
        self.assertEqual(wou.open_in_wechat("https://example.com/x", dry_run=True),
                         wou.EXIT_PARAM)
        self.assertEqual(wou.open_in_wechat("", dry_run=True), wou.EXIT_PARAM)

    def test_env_missing_returns_6(self):
        with mock.patch.object(wou.vision, "grab_wechat", return_value=None):
            self.assertEqual(wou.open_in_wechat(ARTICLE_URL, dry_run=True), wou.EXIT_ENV)

    def test_dry_run_does_not_touch_clipboard_or_mouse(self):
        from PIL import Image

        got = (Image.new("RGB", (1652, 400), (250, 250, 250)), (0, 0, 1652, 400),
               {"hwnd": 123})
        with mock.patch.object(wou.vision, "grab_wechat", return_value=got), \
 mock.patch.object(wou.vision, "window_at_point",
                   return_value={"hwnd": 123, "title": "微信"}), \
             mock.patch.object(wou, "set_clipboard") as set_cb, \
             mock.patch.object(wou.vision, "click_at") as click, \
             mock.patch.object(wou.vision, "key_tap") as tap:
            code = wou.open_in_wechat(ARTICLE_URL, dry_run=True)
        self.assertEqual(code, wou.EXIT_OK)
        set_cb.assert_not_called()
        click.assert_not_called()
        tap.assert_not_called()

    def test_happy_path_click_paste_enter(self):
        """三步的顺序与实质：先写剪贴板 → 点放大镜 → Ctrl+V → 回车。"""
        from PIL import Image

        got = (Image.new("RGB", (1652, 400), (250, 250, 250)), (100, 200, 1752, 600),
               {"hwnd": 123})
        calls = []
        with mock.patch.object(wou.vision, "grab_wechat", return_value=got), \
 mock.patch.object(wou.vision, "window_at_point",
                   return_value={"hwnd": 123, "title": "微信"}), \
             mock.patch.object(wou, "set_clipboard", side_effect=lambda t: calls.append(("cb", t)) or True), \
             mock.patch.object(wou.vision, "click_at", side_effect=lambda x, y: calls.append(("click", x, y)) or True), \
             mock.patch.object(wou.vision, "key_tap", side_effect=lambda vk, modifiers=(): calls.append(("key", vk, modifiers))), \
             mock.patch.object(wou, "clipboard_text", return_value=""), \
             mock.patch.object(wou.vision, "capture_window", return_value=None), \
             mock.patch.object(wou.vision, "park_cursor"):
            code = wou.open_in_wechat(ARTICLE_URL, settle=0)
        self.assertEqual(code, wou.EXIT_OK)
        self.assertEqual(calls[0][0], "cb")
        self.assertEqual(calls[0][1], ARTICLE_URL)
        # 点击落在「窗口原点 + 放大镜在窗口内的坐标」= 屏幕绝对坐标。
        # 纯色画面模板必然失配 ⇒ 走右锚点 (1652-220, 44)。
        self.assertEqual(calls[1], ("click", 100 + 1652 - wou.SEARCH_RIGHT_OFFSET,
                                    200 + wou.SEARCH_TOP))
        self.assertEqual(calls[2], ("key", wou.vision._VK_V, (wou.vision._VK_CTRL,)))
        self.assertEqual(calls[3], ("key", wou.vision._VK_RETURN, ()))

    def test_click_failure_is_reported(self):
        from PIL import Image

        got = (Image.new("RGB", (1652, 400), (250, 250, 250)), (0, 0, 1652, 400),
               {"hwnd": 123})
        with mock.patch.object(wou.vision, "grab_wechat", return_value=got), \
 mock.patch.object(wou.vision, "window_at_point",
                   return_value={"hwnd": 123, "title": "微信"}), \
             mock.patch.object(wou, "set_clipboard", return_value=True), \
             mock.patch.object(wou.vision, "click_at", return_value=False), \
             mock.patch.object(wou.vision, "park_cursor"):
            self.assertEqual(wou.open_in_wechat(ARTICLE_URL, settle=0), wou.EXIT_ERROR)


class TestWarmup(unittest.TestCase):
    """工具只认「页面加载完成」这个时机，页面已在目标页时必须先跳走再跳回来。"""

    def _run(self, url, warmup):
        from PIL import Image

        got = (Image.new("RGB", (1652, 400), (250, 250, 250)), (0, 0, 1652, 400),
               {"hwnd": 123})
        calls = []
        with mock.patch.object(wou.vision, "grab_wechat", return_value=got), \
 mock.patch.object(wou.vision, "window_at_point",
                   return_value={"hwnd": 123, "title": "微信"}), \
             mock.patch.object(wou, "set_clipboard",
                               side_effect=lambda t: calls.append(t) or True), \
             mock.patch.object(wou.vision, "click_at", return_value=True), \
             mock.patch.object(wou.vision, "key_tap"), \
             mock.patch.object(wou.vision, "park_cursor"), \
             mock.patch.object(wou.vision, "capture_window", return_value=None), \
             mock.patch.object(wou, "_changed_ratio", return_value=0.0):
            code = wou.open_in_wechat(url, settle=0, warmup=warmup)
        return code, calls

    def test_warmup_navigates_twice(self):
        code, calls = self._run(ARTICLE_URL, "https://mp.weixin.qq.com/")
        self.assertEqual(code, wou.EXIT_OK)
        self.assertEqual(len(calls), 2, "warmup 必须先占一次导航")
        self.assertEqual(calls[0], "https://mp.weixin.qq.com/")
        self.assertEqual(calls[1], ARTICLE_URL)

    def test_same_warmup_is_skipped(self):
        """warmup 与目标相同时跳过一次导航，否则等于白点一遍。"""
        code, calls = self._run(ARTICLE_URL, ARTICLE_URL)
        self.assertEqual(code, wou.EXIT_OK)
        self.assertEqual(calls, [ARTICLE_URL])

    def test_no_warmup_single_navigation(self):
        code, calls = self._run(ARTICLE_URL, "")
        self.assertEqual(code, wou.EXIT_OK)
        self.assertEqual(calls, [ARTICLE_URL])


# ------------------------------------------------------------------ clicker 动作
class _LogControl:
    def __init__(self, text):
        self._text = text
        self.element_info = SimpleNamespace(
            automation_id="Form.TextEdit", control_type="Edit", class_name="Fake")

    def window_text(self):
        return self._text

    def get_value(self):
        return self._text


class _Win:
    def __init__(self, controls):
        self.controls = controls

    def descendants(self, **kwargs):
        if "auto_id" in kwargs:
            raise TypeError("build_condition() got an unexpected keyword argument 'auto_id'")
        return list(self.controls)


class TestOpenUrlAction(unittest.TestCase):
    """clicker 的 open_url：链接来源、失败必须抛错、dry_run 不许动手。"""

    STEP = {"name": "取密钥", "action": "open_url", "source": "log", "settle": 0.1,
            "target": [{"auto_id": "Form.TextEdit"}]}

    def test_dry_run_is_plan(self):
        result = clicker.run_step(_Win([_LogControl(PROFILE_URL)]), self.STEP, {}, dry_run=True)
        self.assertEqual(result["status"], "plan")

    def test_reads_url_from_log_and_opens_it(self):
        win = _Win([_LogControl("开头 %s 结尾" % PROFILE_URL)])
        with mock.patch.object(wou, "open_in_wechat", return_value=0) as opener:
            result = clicker.run_step(win, self.STEP, {}, dry_run=False)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(opener.call_args[0][0], PROFILE_URL)

    def test_falls_back_to_clipboard_when_log_has_no_url(self):
        win = _Win([_LogControl("开始获取密钥...")])
        with mock.patch.object(wou, "clipboard_text", return_value=PROFILE_URL), \
             mock.patch.object(wou, "open_in_wechat", return_value=0) as opener:
            result = clicker.run_step(win, self.STEP, {}, dry_run=False)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(opener.call_args[0][0], PROFILE_URL)

    def test_no_url_anywhere_raises_loudly(self):
        win = _Win([_LogControl("获取密钥失败...请先在微信打开复制的链接")])
        with mock.patch.object(wou, "clipboard_text", return_value=""):
            with self.assertRaises(RuntimeError) as ctx:
                clicker.run_step(win, self.STEP, {}, dry_run=False)
        self.assertIn("拿不到链接", str(ctx.exception))

    def test_wechat_unavailable_raises(self):
        win = _Win([_LogControl(PROFILE_URL)])
        with mock.patch.object(wou, "open_in_wechat", return_value=wou.EXIT_ENV):
            with self.assertRaises(RuntimeError) as ctx:
                clicker.run_step(win, self.STEP, {}, dry_run=False)
        self.assertIn("微信", str(ctx.exception))

    def test_open_failure_raises(self):
        win = _Win([_LogControl(PROFILE_URL)])
        with mock.patch.object(wou, "open_in_wechat", return_value=wou.EXIT_ERROR):
            with self.assertRaises(RuntimeError) as ctx:
                clicker.run_step(win, self.STEP, {}, dry_run=False)
        self.assertIn("exit=3", str(ctx.exception))

    def test_warmup_passed_through(self):
        step = dict(self.STEP, warmup="https://mp.weixin.qq.com/")
        win = _Win([_LogControl(PROFILE_URL)])
        with mock.patch.object(wou, "open_in_wechat", return_value=0) as opener:
            clicker.run_step(win, step, {}, dry_run=False)
        self.assertEqual(opener.call_args.kwargs.get("warmup"), "https://mp.weixin.qq.com/")

    def test_empty_value_skips_when_allowed(self):
        """没传 ARTICLE_URL 时预热应跳过（合法分支），而不是抛错中断整条流程。"""
        step = {"name": "预热", "action": "open_url", "source": "value",
                "value": "${ARTICLE_URL}", "skip_if_empty": True}
        result = clicker.run_step(None, step, {"vars": {}}, dry_run=False)
        self.assertEqual(result["status"], "skip")

    def test_empty_value_without_flag_raises(self):
        step = {"name": "预热", "action": "open_url", "source": "value",
                "value": "${ARTICLE_URL}"}
        with self.assertRaises(RuntimeError):
            clicker.run_step(None, step, {"vars": {}}, dry_run=False)


# ------------------------------------------------------------------ 流程编排
class TestProfileKeyHandoff(unittest.TestCase):
    """取密钥这一段必须**卡在正确位置**：取 id 成功后、点下载按钮之前。"""

    @classmethod
    def setUpClass(cls):
        cls.steps = clicker._load_yaml(
            Path(__file__).resolve().parents[1] / "scripts" / "profiles"
            / "wechat_batch_downloader.yaml")["steps"]
        cls.names = [s.get("name", "") for s in cls.steps]
        cls.actions = [s["action"] for s in cls.steps]

    def _index_of(self, token):
        for i, step in enumerate(self.steps):
            if token in (step.get("name") or ""):
                return i
        self.fail("步骤表里找不到 %r" % token)

    def test_open_url_exists(self):
        self.assertIn("open_url", self.actions)

    def test_warmup_happens_before_getid(self):
        """时序铁律：预热必须在**点「1.获取公众号id」之前**。

        工具的「自动获取密钥」只在点完取 id 之后的短窗口读一次微信当前页面，
        所以"离开目标页"必须早于点 id，"导航到目标页"必须晚于点 id。
        三次真机（2026-10-23）：别页→目标页=成功；已在目标页=失败；
        点 id 后才 warmup=刷一次「开始获取密钥」后死等。
        """
        warmups = [s for s in self.steps
                   if s.get("action") == "open_url" and s.get("source") == "value"]
        self.assertEqual(len(warmups), 1, "预热步骤应当唯一")
        warm = warmups[0]
        # 预热目标必须是该号文章页（同一变量），**不能**是 mp.weixin.qq.com 首页：
        # 那是「微信公众平台」扫码登录页，与流程无关且用户明确要求不要打开。
        self.assertEqual(warm.get("value"), "${ARTICLE_URL}")
        self.assertTrue(warm.get("skip_if_empty"))
        i_warm = self.steps.index(warm)
        self.assertLess(i_warm, self._index_of("点「1.获取公众号id」"),
                        "预热早于点取 id")
        self.assertLess(i_warm, self._index_of("激活窗口（真实鼠标点击前必须做）"),
                        "预热要排在 activate 之前，否则真实点击会落到微信窗口上")

    def test_never_opens_public_platform_homepage(self):
        """回归：预热曾用 `mp.weixin.qq.com/` 首页，那是「微信公众平台」扫码登录页。

        用户 2026-10-23 明确要求不要打开它。预热改成该号文章页（同一变量）后，
        流程里不该再出现这个 URL。
        """
        for step in self.steps:
            for key in ("value", "warmup"):
                val = str(step.get(key) or "").strip()
                self.assertNotEqual(val, "https://mp.weixin.qq.com/",
                                    "%s 不该打开公众平台首页" % step.get("name"))

    def test_target_open_has_no_warmup(self):
        """取密钥那一步不能带 warmup：那时工具正在读，先跳首页会直接读错。"""
        step = self.steps[self._index_of("在微信内置浏览器打开 profile_ext")]
        self.assertFalse(step.get("warmup"), "open_url 的 warmup 会破坏点火时机")

    def test_order_is_getid_then_open_then_download(self):
        get_id = self._index_of("点「1.获取公众号id」")
        opened = self._index_of("在微信内置浏览器打开 profile_ext")
        key_ok = self._index_of("等「获取密钥成功」")
        download = self._index_of("点「2.批量下载文章」")
        self.assertLess(get_id, opened, "必须先取 id 再取密钥")
        self.assertLess(opened, key_ok, "open_url 之后才可能「获取密钥成功」")
        self.assertLess(key_ok, download, "密钥没拿到就去点下载 = 白跑 300 秒")

    def test_key_success_is_a_real_gate(self):
        step = self.steps[self._index_of("在微信内置浏览器打开 profile_ext") + 1]
        self.assertEqual(step["action"], "wait_log")
        self.assertIn("获取密钥成功", step["contains_any"])
        self.assertGreaterEqual(step.get("timeout", 0), 30)

    def test_getid_wait_no_longer_treats_key_fail_as_fatal(self):
        """「获取密钥失败」在 open_url 之前每 2 秒刷一次，是正常中间态。"""
        step = self.steps[self._index_of("等日志给出 profile_ext")]
        self.assertNotIn("获取密钥失败", step.get("not_contains") or [])

    def test_no_blacklist_on_generic_log_noise(self):
        """回归：not_contains 黑「梯子建议」曾让每次运行都误中断。

        工具的启动横幅/建议只是 hint，与"当前是否真失败"无关。一旦拿它做黑名单，
        日志里出现该字样就中毒（2026-10-23 真机假阳性）。
        """
        for step in self.steps:
            forbid = step.get("not_contains") or []
            for token in ("可以把梯子关了试一试", "获取失败"):
                self.assertNotIn(token, forbid, "%s 不该黑 %r" % (step.get("name"), token))

    def test_positive_success_gate_exists(self):
        """成败判定必须是正向的：只认「获取公众号历史消息页面成功」。"""
        gate = self.steps[self._index_of("等「获取公众号历史消息页面成功」")]
        self.assertEqual(gate["action"], "wait_log")
        self.assertIn("获取公众号历史消息页面成功", gate["contains_any"])
        self.assertLess(self._index_of("等「获取公众号历史消息页面成功」"),
                        self._index_of("在微信内置浏览器打开 profile_ext"),
                        "必须先确认取 id 成功，再去微信打开链接")


if __name__ == "__main__":
    unittest.main()
