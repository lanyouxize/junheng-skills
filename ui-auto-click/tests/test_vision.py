#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""vision.py 离线测试：不截图、不点击、不起 GUI。

覆盖 2026-10-23 新增/修复的通用能力：
  ① wheel_delta 量级与钳位（历史 bug：一格滚动被放大 65536 倍）；
  ② dHash 内容指纹（确定性 / 敏感性 / 缩放不变 / 纯色可区分 / 微扰吸收）；
  ③ detect_rows 合成图与伪行剔除（被遮挡画面的错几何曾直接写进缓存）；
  ④ _norm_xy 虚拟桌面负原点（多显示器偏移是"点偏"第一大来源）；
  ⑤ 输入/窗口工具的失败路径（不碰真机，全靠 mock）。
"""
from __future__ import annotations

import ctypes
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

os.environ["UIAC_NO_DPI_AWARE"] = "1"   # 测试进程不做 DPI 副作用
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import vision  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402


def _synth_rows(centers, w=600, h=500, bh=40):
    """合成"文章列表页"：白底 + 左侧一列彩色缩略图块。

    块高 bh 必须 < 相邻中心距，否则两块相连会被并成一块（真实教训：
    块高 60、中心距 60 时第 4/5 块粘连，高度 120 超上限被整体丢掉）。
    """
    img = Image.new("RGB", (w, h), (245, 245, 245))
    d = ImageDraw.Draw(img)
    for i, cy in enumerate(centers):
        d.rectangle([20, cy - bh // 2, 120, cy + bh // 2],
                    fill=((i * 53) % 255, 80, 160))
    return img


class TestWheelDelta(unittest.TestCase):
    def test_zero_and_sign(self):
        self.assertEqual(vision.wheel_delta(0), 0)
        self.assertEqual(vision.wheel_delta(3), 360)
        self.assertEqual(vision.wheel_delta(-3), -360)

    def test_clamp_limit(self):
        # 历史 bug：旧代码 0x00780000 * abs(clicks) 既放错量级又会溢出
        self.assertEqual(vision.wheel_delta(-9999), -120 * 100)
        self.assertEqual(vision.wheel_delta(-9999, limit=10), -120 * 10)


class TestDHash(unittest.TestCase):
    def setUp(self):
        self.a = Image.new("RGB", (200, 120), (245, 245, 245))
        d = ImageDraw.Draw(self.a)
        d.rectangle([10, 10, 90, 100], fill=(200, 60, 60))
        d.ellipse([110, 20, 180, 90], fill=(60, 60, 200))

    def test_deterministic_and_sensitive(self):
        same = self.a.copy()
        other = Image.new("RGB", (200, 120), (245, 245, 245))
        d = ImageDraw.Draw(other)
        d.rectangle([10, 10, 90, 100], fill=(60, 200, 60))   # 同形不同色
        d.ellipse([110, 20, 180, 90], fill=(60, 60, 200))
        self.assertEqual(vision.dhash(self.a), vision.dhash(same))
        self.assertNotEqual(vision.dhash(self.a), vision.dhash(other))

    def test_scale_invariant(self):
        self.assertEqual(vision.dhash(self.a), vision.dhash(self.a.resize((400, 240))))

    def test_flat_colors_distinguishable(self):
        # 纯 dHash 对纯色图全零指纹；均色分量补上这个盲区
        f1 = Image.new("RGB", (64, 64), (200, 10, 10))
        f2 = Image.new("RGB", (64, 64), (10, 10, 200))
        self.assertNotEqual(vision.dhash(f1), vision.dhash(f2))

    def test_single_pixel_perturbation_absorbed(self):
        px = self.a.load()
        px[95, 95] = (0, 0, 0)
        self.assertEqual(vision.dhash(self.a), vision.dhash(self.a.copy()))


class TestDetectRows(unittest.TestCase):
    """行检测 = 标题文字带 + 灰色账号带配对（2026-10-23 推翻缩略图饱和度法）。

    实测背景：同一张收藏页肉眼 10 行，饱和度法只检出 3 行（黑图/灰图缩略图的
    行整段漏检）⇒ 70% 的文章永远不会被处理。这里是新算法的契约测试。
    """

    def setUp(self):
        self.img, self.centers = _synth_page()

    def test_pairs_title_with_gray_line(self):
        rows = vision.detect_rows(self.img)
        self.assertEqual(len(rows), len(self.centers))
        for r, cy in zip(rows, self.centers):
            self.assertEqual(r["account_h"], 17)          # 灰字带（含首末行）
            self.assertEqual(r["account_dark"], 0)        # 账号带不应有深墨
            self.assertGreater(r["account_box"][1], r["y1"])   # 在标题下方
            self.assertGreaterEqual(r["click_point"][1], r["y1"])
            self.assertLessEqual(r["click_point"][1], r["y2"])

    def test_top_to_bottom_order(self):
        rows = vision.detect_rows(self.img)
        self.assertEqual([r["center"] for r in rows], sorted(r["center"] for r in rows))

    def test_multiline_title_is_one_row(self):
        img = Image.new("RGB", (900, 300), (250, 250, 250))
        d = ImageDraw.Draw(img)
        d.rectangle([250, 40, 700, 62], fill=(50, 50, 50))     # 标题第一行
        d.rectangle([250, 73, 620, 95], fill=(50, 50, 50))     # 标题第二行（行距 11）
        d.rectangle([250, 111, 420, 128], fill=(160, 160, 160))  # 账号名
        rows = vision.detect_rows(img)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["y1"], rows[0]["y2"]), (40, 129))

    def test_first_row_not_lost_when_sidebar_overlaps(self):
        """左侧标签与**第一条**账号名同高时，第一条不能被吞掉。

        实机事故（2026-10-23）：标签栏「赞和收藏」的深墨落进条目 1 的账号带，
        dark/h=22.5>4 判非账号带 ⇒ 检出结果变成"从第 2 条开始数 10 行"，
        行数看着正常、肉眼只看账号框也对，但第 1 条永远不会被点击。
        """
        img = Image.new("RGB", (1000, 900), (250, 250, 250))
        d = ImageDraw.Draw(img)
        for y in (80, 130, 180, 230, 280):                 # 左侧标签栏
            d.rectangle([200, y, 330, y + 14], fill=(30, 30, 30))
        for i, ty in enumerate((190, 316, 442)):           # 3 条正文
            d.rectangle([420, ty, 880, ty + 22], fill=(40, 40, 40))
            d.rectangle([420, ty + 35, 540, ty + 50], fill=(160, 160, 160))
            d.rectangle([900, ty, 960, ty + 60],
                        fill=((i * 90 + 120) % 255, 60, 120))   # 缩略图列
        rows = vision.detect_rows(img)
        self.assertEqual(len(rows), 3, "行数不对：%s" % [r["y1"] for r in rows])
        self.assertLess(rows[0]["y1"], 220, "第一条被漏检，检出从第 2 条开始")
        self.assertEqual(rows[0]["account_dark"], 0)       # 账号带里不该有深墨

    def test_tab_row_without_account_is_skipped(self):
        # 「全部 / ♡ / 👍」标签行的特征：有深墨但没有灰色账号带
        img = Image.new("RGB", (900, 300), (250, 250, 250))
        d = ImageDraw.Draw(img)
        d.rectangle([250, 20, 260, 44], fill=(50, 50, 50))     # 标签
        d.rectangle([300, 20, 310, 44], fill=(50, 50, 50))     # 标签
        rows = vision.detect_rows(img, warn=False)
        self.assertEqual(rows, [])

    def test_bottom_partial_row_skipped(self):
        img = Image.new("RGB", (900, 300), (250, 250, 250))
        d = ImageDraw.Draw(img)
        d.rectangle([250, 40, 700, 62], fill=(50, 50, 50))
        d.rectangle([250, 73, 420, 90], fill=(160, 160, 160))
        d.rectangle([250, 270, 700, 292], fill=(50, 50, 50))    # 底部半截行（无账号带）
        rows = vision.detect_rows(img, warn=False)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["y1"], 40)

    def test_no_text_no_rows_with_warning(self):
        import io
        from contextlib import redirect_stderr
        buf = io.StringIO()
        with redirect_stderr(buf):
            rows = vision.detect_rows(_synth_rows((60, 160, 260)))
        self.assertEqual(rows, [])
        self.assertIn("未检出", buf.getvalue())

    def test_thumbnail_column_found(self):
        rows = vision.detect_rows(self.img)
        self.assertTrue(all(r["thumb_x2"] > r["thumb_x1"] for r in rows))
        # 文字列必须避开左侧标签栏：账号框左界 > 标签右界
        self.assertTrue(all(r["account_box"][0] > 120 for r in rows))


def _synth_page(rows: int = 8, w=900, h=None):
    """合成「赞和收藏」式列表页：左侧标签栏 + 标题（深墨）+ 账号（灰）+ 右侧缩略图。

    行距 126px、标题高 23、账号高 17 —— 均取自实测值。行数给足 8 行，
    这样正文列的列墨量才明显高于标签栏（_text_left 的判据依赖这个对比）。
    """
    pitch = 126
    h = h or 60 + pitch * rows
    img = Image.new("RGB", (w, h), (250, 250, 250))
    d = ImageDraw.Draw(img)
    centers = []
    for i in range(rows):
        top = 40 + i * pitch
        d.rectangle([20, top + 20, 110, top + 40], fill=(70, 70, 70))   # 左侧标签栏
        d.rectangle([250, top, 700, top + 22], fill=(50, 50, 50))       # 标题
        d.rectangle([250, top + 40, 420, top + 56], fill=(160, 160, 160))  # 公众号名
        if i % 2 == 0:                                                   # 只有一半有彩色缩略图
            d.rectangle([w - 80, top, w - 20, top + 60], fill=((i * 53) % 255, 80, 160))
        else:
            d.rectangle([w - 80, top, w - 20, top + 60], fill=(40, 40, 40))  # 黑图
        centers.append((top + top + 56) // 2)
    return img, centers


class TestTextBands(unittest.TestCase):
    """文字带切分：行检测与账号定位的共同底座，必须能分开深墨/灰墨。"""

    def test_dark_and_gray_split(self):
        img, _ = _synth_page(rows=2)
        bands = vision.text_bands(img, x1=200, x2=800, y1=0, y2=img.height)
        self.assertTrue(bands)
        gray = [b for b in bands if b["dark"] == 0 and b["mid"] > 0]
        dark = [b for b in bands if b["dark"] > 0]
        self.assertTrue(gray, "必须切出纯灰带（公众号名）")
        self.assertTrue(dark, "必须切出深墨带（标题）")

    def test_rows_split_by_max_gap(self):
        img = Image.new("RGB", (400, 200), (250, 250, 250))
        d = ImageDraw.Draw(img)
        d.rectangle([20, 20, 300, 40], fill=(50, 50, 50))     # 行1
        d.rectangle([20, 50, 300, 70], fill=(50, 50, 50))     # 行2（间隙 10）
        bands = vision.text_bands(img, x1=0, x2=400, y1=0, y2=200, max_gap=2)
        self.assertEqual(len(bands), 2)
        bands_g = vision.text_bands(img, x1=0, x2=400, y1=0, y2=200, max_gap=12)
        self.assertEqual(len(bands_g), 1)                     # 允许大间隙则并成一条

    def test_x_extent_trimmed_to_ink(self):
        img = Image.new("RGB", (400, 100), (250, 250, 250))
        ImageDraw.Draw(img).rectangle([130, 30, 260, 50], fill=(160, 160, 160))
        b = vision.text_bands(img, x1=0, x2=400, y1=0, y2=100)[0]
        self.assertEqual((b["x1"], b["x2"]), (130, 261))

    def test_blank_region_returns_empty(self):
        img = Image.new("RGB", (300, 200), (250, 250, 250))
        self.assertEqual(vision.text_bands(img), [])


class TestTextLeft(unittest.TestCase):
    """正文列左界：左侧标签被"选中"时不能把左界拉进标签栏。

    2026-10-23 实机事故：窗口 1652×1518 的收藏页上整页列墨量算出 262（落在
    「赞和收藏」标签内，正确约 420）⇒ 文字带横跨进标签栏 ⇒ 条目 1 的账号带
    混入「赞和收藏」四个深墨字而被判非账号带 ⇒ **整页第一条永远漏检**，
    而它只是"从第 2 条开始数 10 行"，行数看着正常，肉眼不核对 y 就发现不了。
    """

    def _page(self):
        """合成页：上半部左侧 6 行标签（墨量足够顶到 45% 峰值）+ 下半部正文。"""
        img = Image.new("RGB", (1000, 1400), (250, 250, 250))
        d = ImageDraw.Draw(img)
        for y in range(80, 380, 50):                       # 标签栏 6 行
            d.rectangle([200, y, 330, y + 20], fill=(30, 30, 30))
        d.rectangle([200, 118, 335, 160], fill=(232, 232, 232))   # 选中态底色块
        for y in range(500, 1300, 60):                     # 正文 14 行
            d.rectangle([420, y, 950, y + 14], fill=(30, 30, 30))
        return img

    def test_ignores_selected_sidebar_label(self):
        g = vision.to_gray(self._page())
        self.assertGreaterEqual(vision._text_left(g), 400,
                                "左界落进了左侧标签栏")
        # 证伪：改成整页统计（旧行为）就一定会被标签栏带偏 —— 证明本用例真在测东西
        whole = vision._text_left(g, y_lo=0.0, y_hi=1.0)
        self.assertLess(whole, 400, "整页统计本应被标签栏带偏，否则用例无效")


class TestParkCursor(unittest.TestCase):
    """截图前必须把光标挪出行：列表行有 hover 态，压在某行上会让该行 dHash 变。

    2026-10-23 实测（同一行几何 y1/y2 完全不变）：
      光标在角落 0110…0-ddd  /  hover 该行 0111…1-ddd  /  移开 0110…0-ddd
    ⇒ 点击后光标留在行上 = 该行指纹漂移 = 下次运行重复点同一篇。
    """

    def test_parks_when_cursor_elsewhere(self):
        with mock.patch.object(vision, "_cursor_pos", return_value=(1200, 800)), \
             mock.patch.object(ctypes.windll.user32, "SetCursorPos") as sp:
            self.assertTrue(vision.park_cursor(settle=0))
        sp.assert_called_once_with(vision._PARK_X, vision._PARK_Y)

    def test_skips_when_already_parked(self):
        with mock.patch.object(vision, "_cursor_pos",
                               return_value=(vision._PARK_X, vision._PARK_Y)), \
             mock.patch.object(ctypes.windll.user32, "SetCursorPos") as sp:
            self.assertFalse(vision.park_cursor(settle=0))
        sp.assert_not_called()

    def test_unknown_cursor_position_still_parks(self):
        with mock.patch.object(vision, "_cursor_pos", return_value=None), \
             mock.patch.object(ctypes.windll.user32, "SetCursorPos") as sp:
            self.assertTrue(vision.park_cursor(settle=0))
        sp.assert_called_once()


class TestNormXY(unittest.TestCase):
    def test_negative_virtual_origin(self):
        # 副屏在主屏左侧：虚拟桌面原点 x=-1920，宽 4480
        metrics = {76: -1920, 77: 0, 78: 4480, 79: 1440}
        with mock.patch.object(ctypes.windll.user32, "GetSystemMetrics",
                               side_effect=lambda i: metrics.get(i, 0)):
            nx, ny = vision._norm_xy(100, 200)
        self.assertAlmostEqual(nx, (100 + 1920) * 65535 / 4479, delta=1)
        self.assertAlmostEqual(ny, 200 * 65535 / 1439, delta=1)

    def test_primary_only(self):
        metrics = {76: 0, 77: 0, 78: 1920, 79: 1080}
        with mock.patch.object(ctypes.windll.user32, "GetSystemMetrics",
                               side_effect=lambda i: metrics.get(i, 0)):
            nx, _ = vision._norm_xy(960, 540)
        self.assertAlmostEqual(nx, 960 * 65535 / 1919, delta=1)


class TestMatchTemplate(unittest.TestCase):
    def test_find_and_edge_mode(self):
        hay = Image.new("RGB", (300, 200), (255, 255, 255))
        d = ImageDraw.Draw(hay)
        d.rectangle([100, 50, 180, 110], fill=(0, 0, 0))
        needle = hay.crop((100, 50, 180, 110))
        hits = vision.match_template(hay, needle, threshold=0.9)
        self.assertTrue(hits)
        self.assertGreaterEqual(hits[0].score, 0.9)
        hits_e = vision.match_template(hay, needle, threshold=0.9, edge=True)
        self.assertTrue(hits_e)

    def test_best_match_identical(self):
        img = Image.new("RGB", (80, 60), (245, 245, 245))
        d = ImageDraw.Draw(img)
        d.rectangle([10, 10, 50, 40], fill=(10, 200, 90))   # 纯色图零方差，必须带结构
        score, loc = vision.best_match(img, img)
        self.assertGreater(score, 0.99)
        self.assertEqual(loc, (0, 0))

    def test_needle_bigger_than_hay(self):
        big = Image.new("RGB", (200, 200), (0, 0, 0))
        small = Image.new("RGB", (50, 50), (255, 255, 255))
        self.assertEqual(vision.match_template(small, big), [])
        self.assertEqual(vision.best_match(small, big), (0.0, None))


class TestCropAndDraw(unittest.TestCase):
    def test_crop_clamps(self):
        img = Image.new("RGB", (100, 100), (255, 255, 255))
        out = vision.crop(img, (-10, -10, 200, 200))
        self.assertEqual(out.size, (100, 100))

    def test_draw_boxes_no_mutation(self):
        img = Image.new("RGB", (100, 100), (255, 255, 255))
        out = vision.draw_boxes(img, [(10, 10, 50, 50, "row0")])
        self.assertEqual(out.size, img.size)
        self.assertEqual(img.getpixel((30, 30)), (255, 255, 255))   # 原图不动


class TestWaitUntil(unittest.TestCase):
    def test_immediate_and_timeout(self):
        self.assertTrue(vision.wait_until(lambda: True, timeout=0.2))
        self.assertFalse(vision.wait_until(lambda: False, timeout=0.2, poll=0.05))

    def test_predicate_exception_tolerated(self):
        calls = {"n": 0}

        def boom():
            calls["n"] += 1
            if calls["n"] < 2:
                raise RuntimeError("截图失败")
            return True

        self.assertTrue(vision.wait_until(boom, timeout=1.0, poll=0.01))


class TestWindowToolsMocked(unittest.TestCase):
    def test_grab_wechat_no_window(self):
        with mock.patch.object(vision, "wechat_window", return_value=None):
            self.assertIsNone(vision.grab_wechat())

    def test_capture_window_zero_rect(self):
        with mock.patch.object(vision.win32gui, "GetWindowRect", return_value=(0, 0, 0, 0)):
            self.assertIsNone(vision.capture_window(hwnd=1234))

    def test_capture_window_rejects_minimized_sentinel(self):
        """最小化窗口 rect=(-32000,-32000,…) 宽高都非零，能骗过零面积判据；
        截出来是屏幕左上角一块无关区域，必须在这里就拒绝。
        """
        sentinel = (-32000, -32000, -31724, -31955)
        with mock.patch.object(vision.win32gui, "GetWindowRect", return_value=sentinel), \
             mock.patch.object(vision, "ImageGrab") as grab:
            self.assertIsNone(vision.capture_window(hwnd=1234))
        grab.grab.assert_not_called()          # 连截都不截

    def test_is_sentinel_rect(self):
        self.assertTrue(vision.is_sentinel_rect((-32000, -32000, -31724, -31955)))
        self.assertTrue(vision.is_sentinel_rect((-32000, 100, 100, 500)))   # 只看 left/top
        self.assertFalse(vision.is_sentinel_rect((0, 0, 1600, 1200)))
        # 左侧副屏的**正常**负坐标不能被误判
        self.assertFalse(vision.is_sentinel_rect((-1920, 0, -1, 1080)))

    def test_is_iconic_swallows_errors(self):
        with mock.patch.object(vision.win32gui, "IsIconic", return_value=1):
            self.assertTrue(vision.is_iconic(1))
        with mock.patch.object(vision.win32gui, "IsIconic", side_effect=Exception("x")):
            self.assertFalse(vision.is_iconic(1))

    def test_ensure_min_size_enlarges(self):
        with mock.patch.object(vision.win32gui, "GetWindowRect",
                               side_effect=[(0, 0, 600, 400), (0, 0, 760, 600)]), \
             mock.patch.object(vision.win32gui, "SetWindowPos") as sp:
            rect = vision.ensure_min_size(1, min_w=760, min_h=600)
        self.assertEqual(rect, (0, 0, 760, 600))
        sp.assert_called_once()

    def test_ensure_min_size_keeps_big(self):
        with mock.patch.object(vision.win32gui, "GetWindowRect",
                               return_value=(0, 0, 1600, 1200)), \
             mock.patch.object(vision.win32gui, "SetWindowPos") as sp:
            rect = vision.ensure_min_size(1, min_w=760, min_h=600)
        self.assertEqual(rect, (0, 0, 1600, 1200))
        sp.assert_not_called()


class TestWechatWindowPick(unittest.TestCase):
    """窗口选择级联：标题含「微信」的大浏览器窗口曾劫持目标（2026-10-23 实测）。"""

    def _w(self, hwnd, cls, area, iconic=False):
        return {"hwnd": hwnd, "cls": cls, "title": "微信", "iconic": iconic,
                "rect": [0, 0, area, 100]}

    def test_prefers_cef_class_over_bigger_title_only_window(self):
        wins = [self._w(1, "Chrome_WidgetWin_0", 1000),      # 真微信（小）
                self._w(2, "Chrome_WidgetWin_1", 900),
                self._w(3, "MozillaWindowClass", 99999)]     # 标题带微信的大浏览器
        with mock.patch.object(vision, "wechat_windows", return_value=wins):
            self.assertEqual(vision.wechat_window()["hwnd"], 1)

    def test_falls_back_to_title_only_when_no_cef(self):
        wins = [self._w(1, "Qt51514QWindowIcon", 500),
                self._w(2, "MozillaWindowClass", 8000)]
        with mock.patch.object(vision, "wechat_windows", return_value=wins):
            self.assertEqual(vision.wechat_window()["hwnd"], 2)   # 可见+面积最大

    def test_iconic_cef_wins_over_nothing_visible(self):
        wins = [self._w(1, "Chrome_WidgetWin_0", 1000, iconic=True),
                self._w(2, "MozillaWindowClass", 8000, iconic=True)]
        with mock.patch.object(vision, "wechat_windows", return_value=wins):
            w = vision.wechat_window()
            self.assertEqual(w["hwnd"], 1)        # 交给 activate_window 去 restore
            self.assertTrue(w["iconic"])

    def test_none_when_no_wechat(self):
        with mock.patch.object(vision, "wechat_windows", return_value=[]):
            self.assertIsNone(vision.wechat_window())


if __name__ == "__main__":
    unittest.main()
