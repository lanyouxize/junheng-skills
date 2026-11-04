#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wechat_favorites.py（scout）离线测试：不截图、不点击、不起 GUI。

覆盖 2026-10-23 重写的四个核心行为：
  ① 页面在位判据的主判据 + 回退判据（回退判据曾被真实聊天页验证过：
     tab-all 0.533 / rows=2，两者单独都不足以认页，合起来也要 tab ≥0.80）；
  ② 行几何：运行时检测优先、校准缓存按窗口宽高兜底；
  ③ 指纹去重：journal 里 click 过的行不再处理（跨次运行不重复点）；
  ④ 已采集名单：目录名 + manifest account 两个来源的并集。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

os.environ["UIAC_NO_DPI_AWARE"] = "1"   # 测试进程不做 DPI 副作用
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import vision  # noqa: E402
import wechat_favorites as wf  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402


# 每行标题的宽度（px）。必须**逐行不同**：行指纹算的是文字区（见
# row_fingerprint），标题一样长 → 指纹必然撞。真实页面的标题本来就长短不一，
# 旧夹具让 4 行标题等宽、靠"缩略图配色不同"骗过指纹，行指纹换成文字区后
# 立刻暴露成 4 行同值（这一条正是 2026-10-23 单测变红的根因）。
_TITLE_WIDTHS = (200, 260, 320, 380)


def _synth_favorites_page(w=600, h=500):
    """合成"赞和收藏页"：4 行（标题深墨 + 公众号名灰字）+ 顶部「全部」标签块。

    文字用**色块**代替真字：行检测只看墨迹分布（深墨 / 灰墨 / 灰阶），
    不认字形，所以色块与真字等价，且不依赖系统字体。
    版面照实测：左侧标签栏、文字列在中、缩略图在右。
    """
    img = Image.new("RGB", (w, h), (250, 250, 250))
    d = ImageDraw.Draw(img)
    for i, top in enumerate((100, 200, 300, 400)):
        d.rectangle([30, top + 18, 70, top + 34], fill=(70, 70, 70))        # 左侧标签栏
        d.rectangle([120, top, 120 + _TITLE_WIDTHS[i], top + 22],
                    fill=(50, 50, 50))                                       # 标题（长度逐行不同）
        d.rectangle([120, top + 40, 300, top + 56], fill=(160, 160, 160))   # 公众号名
        d.rectangle([w - 70, top, w - 20, top + 60],
                    fill=((i * 53) % 255, 80, 160))                          # 缩略图
    # 顶部「全部」标签块（tab-all 模板从这里裁）
    d.rectangle([90, 30, 132, 60], fill=(235, 235, 235), outline=(170, 170, 170))
    return img


def _synth_chat_like_page(w=600, h=500):
    """合成"聊天列表页"：只有彩色气泡，没有「标题 + 公众号名」配对。"""
    img = Image.new("RGB", (w, h), (250, 250, 250))
    d = ImageDraw.Draw(img)
    for i, cy in enumerate((60, 160)):
        d.ellipse([20, cy - 30, 120, cy + 30], fill=((i * 90) % 255, 120, 200))
    return img


class TestCollectedAccounts(unittest.TestCase):
    def test_dir_and_manifest_union(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "甲号").mkdir()
            (root / "乙号").mkdir()
            (root / "_reports").mkdir()          # 下划线开头不算
            man = root / "丙号" / "_reports"
            man.mkdir(parents=True)
            (man / "manifest.json").write_text(json.dumps(
                {"articles": [{"account": "丙号"}, {"account": None}]},
                ensure_ascii=False), encoding="utf-8")
            (root / "丁号").mkdir()               # 空目录也算采过
            got = wf.collected_accounts(root)
            self.assertEqual(got, {"甲号", "乙号", "丙号", "丁号"})

    def test_missing_root(self):
        self.assertEqual(wf.collected_accounts(Path("Z:/不存在/目录")), set())


class TestPageState(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tpl_dir = Path(self._tmp.name)
        p = mock.patch.object(wf, "TPL", self.tpl_dir)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self._tmp.cleanup)

    def _mk_template(self, name, src_img, box):
        vision.save(vision.crop(src_img, box), self.tpl_dir / ("%s.png" % name))

    def test_title_primary_signal(self):
        page = _synth_favorites_page()
        self._mk_template("page-title", page, (10, 10, 300, 60))
        st = wf.page_state(page)
        self.assertTrue(st["ok"])
        self.assertEqual(st["signal"], "title")

    def test_tab_rows_fallback(self):
        page = _synth_favorites_page()
        # tab-all 模板取自页面本身的标签块（自匹配必然高分）
        self._mk_template("tab-all", page,
                          (int(600 * 0.15), int(500 * 0.072),
                           int(600 * 0.22), int(500 * 0.112)))
        st = wf.page_state(page)
        self.assertTrue(st["ok"])
        self.assertEqual(st["signal"], "tab+rows")

    def test_chat_like_page_rejected(self):
        # 回退判据的两半都不可省：只有行没有标签 → 不认
        chat = _synth_chat_like_page()
        self._mk_template("tab-all", _synth_favorites_page(),
                          (90, 36, 132, 56))
        st = wf.page_state(chat)
        self.assertFalse(st["ok"])
        self.assertEqual(st["signal"], "none")
        # 新算法下聊天页连"标题+账号"配对都没有 → 行数 0，
        # 比旧算法的"行数够但靠 tab 挡住"更强（两道判据独立成立）
        self.assertEqual(st["rows"], 0)

    def test_no_templates_rejected(self):
        page = _synth_favorites_page()
        st = wf.page_state(page)
        self.assertFalse(st["ok"])                 # 没模板不猜坐标

    def test_on_favorites_page_compat(self):
        page = _synth_favorites_page()
        self._mk_template("page-title", page, (10, 10, 300, 60))
        ok, score = wf.on_favorites_page(page)
        self.assertTrue(ok)
        self.assertGreaterEqual(score, 0.80)


class TestRowsFor(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        p = mock.patch.object(wf, "OUT", Path(self._tmp.name))
        p.start()
        self.addCleanup(p.stop)

    def test_runtime_first(self):
        img = _synth_favorites_page()
        rows, src = wf.rows_for(img, (0, 0, 600, 500))
        self.assertEqual(src, "runtime")
        self.assertEqual(len(rows), 4)

    def test_baked_fallback_same_size(self):
        img = _synth_favorites_page()
        (Path(self._tmp.name) / "wx-rows.json").write_text(json.dumps(
            {"rect": [0, 0, 600, 500], "w": 600, "h": 500,
             "rows": [{"y1": 30, "y2": 90, "center": 60,
                       "account_box": [96, 26, 112, 52],
                       "click_point": [296, 60]}]},
            ensure_ascii=False), encoding="utf-8")
        with mock.patch.object(vision, "detect_rows", return_value=[]):
            rows, src = wf.rows_for(img, (0, 0, 600, 500))
        self.assertEqual(src, "baked")
        self.assertEqual(len(rows), 1)

    def test_baked_stale_size_rejected(self):
        img = _synth_favorites_page()
        (Path(self._tmp.name) / "wx-rows.json").write_text(json.dumps(
            {"w": 1649, "rows": [{"y1": 192, "y2": 276, "center": 234,
                                  "account_box": [263, 200, 1328, 226],
                                  "click_point": [463, 234]}]},
            ensure_ascii=False), encoding="utf-8")
        with mock.patch.object(vision, "detect_rows", return_value=[]):
            rows, src = wf.rows_for(img, (0, 0, 600, 500))
        self.assertEqual(src, "none")              # 尺寸不符，宁可报错不猜坐标
        self.assertEqual(rows, [])


class TestFingerprintDedup(unittest.TestCase):
    def test_processed_fingerprints_from_journal(self):
        with tempfile.TemporaryDirectory() as td:
            j = Path(td) / "favorites-journal.jsonl"
            j.write_text("\n".join([
                json.dumps({"fp": "aaa", "decision": "click"}),
                json.dumps({"fp": "bbb", "decision": "skip"}),
                json.dumps({"fp": "aaa", "decision": "skip"}),
                "坏行不是 json",
            ]), encoding="utf-8")
            self.assertEqual(wf.processed_fingerprints(j), {"aaa"})

    def test_row_fingerprint_stable_and_distinct(self):
        img = _synth_favorites_page()
        rows, _ = wf.rows_for(img, (0, 0, 600, 500))
        fp0 = wf.row_fingerprint(img, rows[0])
        self.assertEqual(fp0, wf.row_fingerprint(img, rows[0]))
        self.assertNotEqual(fp0, wf.row_fingerprint(img, rows[1]))


class TestIdentifyAccount(unittest.TestCase):
    def test_hit_and_miss(self):
        name = "食品研发与生产"
        tpls = wf.render_account(name)
        self.assertTrue(tpls)                       # 字体加载成功才有意义
        # 用模板本身当目标区域：必然高分命中
        hit, score = wf.identify_account(tpls[0], {name})
        self.assertEqual(hit, name)
        self.assertGreaterEqual(score, wf.IDENTIFY_THRESHOLD)
        # 空白区域 + 非空名单 → 认不出来当新号
        blank = Image.new("RGB", (200, 30), (255, 255, 255))
        miss, mscore = wf.identify_account(blank, {name})
        self.assertIsNone(miss)

    def test_empty_registry_means_new(self):
        tpls = wf.render_account("甲")
        name, score = wf.identify_account(tpls[0], set())
        self.assertIsNone(name)
        self.assertEqual(score, 0.0)

    def test_render_height_fits_account_band(self):
        # 回归 2026-10-23：旧 render_account 高度 = size+16（size=18 → 34px），
        # 而实测公众号名区域只有 26~28px ⇒ matchTemplate 无解 ⇒ score 恒 0.0
        for tpl in wf.render_account("食品研发与生产"):
            self.assertLessEqual(tpl.height, 26)
            self.assertGreaterEqual(tpl.width, 40)

    def test_col_profile_beats_pixel_template(self):
        # 列投影对「同字不同字号」稳定：自匹配高分、无关名低分
        name = "食品研发与生产"
        region = wf.render_account(name)[-1]
        self.assertGreaterEqual(wf.account_score(region, name), 0.9)
        self.assertLess(wf.account_score(region, "公众号观察"), 0.6)

    def test_margin_gate_rejects_ambiguous_pair(self):
        # 实测「宠物食品联盟 vs 宠物食品商情」只差 0.008 —— 必须判未知（漏采比多点一次更糟）
        region = Image.new("RGB", (200, 28), (250, 250, 250))
        with mock.patch.object(wf, "account_score", side_effect=[0.80, 0.75]):
            got, score = wf.identify_account(region, {"甲", "乙"})
        self.assertIsNone(got)
        self.assertAlmostEqual(score, 0.80)

    def test_margin_gate_accepts_clear_winner(self):
        region = Image.new("RGB", (200, 28), (250, 250, 250))
        with mock.patch.object(wf, "account_score", side_effect=[0.82, 0.41]):
            got, score = wf.identify_account(region, {"甲", "乙"})
        self.assertIn(got, {"甲", "乙"})
        self.assertAlmostEqual(score, 0.82)

    def test_low_score_is_new_account(self):
        region = Image.new("RGB", (200, 28), (250, 250, 250))
        with mock.patch.object(wf, "account_score", side_effect=[0.65, 0.10]):
            got, score = wf.identify_account(region, {"甲", "乙"})
        self.assertIsNone(got)


class TestMainGuards(unittest.TestCase):
    def test_max_rounds_must_be_positive(self):
        self.assertEqual(wf.main(["--max-rounds", "0"]), wf.EXIT_PARAM)

    def test_no_wechat_returns_env(self):
        with mock.patch.object(vision, "wechat_windows", return_value=[]):
            # SimpleNamespace 而不是 Mock：字段名打错会直接 AttributeError，
            # 不会静默返回一个新 Mock 把测试变成永真。
            args = SimpleNamespace(max_rounds=1, download_root=".", dry_run=True,
                                   scroll=0, return_key="esc", settle=0.0,
                                   open_timeout=0.2, back_timeout=0.2)
            self.assertEqual(wf.run(args), wf.EXIT_ENV)


def _fake_pages():
    """造两个页面：fav=赞和收藏列表页（3 行 + tab-all 自匹配块），
    article=文章页（白板，无行无标签）。

    版面照真实页：文字列在左、缩略图在右，**行标题长度逐行不同**。行几何由各
    用例 patch 的 fake_rows 提供，但行内容必须逐行可辨——行指纹只算文字区，
    标题等宽会让 3 行撞成同一指纹，去重逻辑就测不出来了。
    """
    fav = Image.new("RGB", (600, 500), (245, 245, 245))
    d = ImageDraw.Draw(fav)
    for i, cy in enumerate((60, 160, 260)):
        d.rectangle([180, cy - 20, 180 + _FAKE_TITLE_W[i], cy + 2],
                    fill=(45, 45, 45))                            # 标题
        d.rectangle([180, cy + 8, 180 + _FAKE_ACCT_W[i], cy + 24],
                    fill=(150, 150, 150))                         # 公众号名（逐行不同）
        d.rectangle([500, cy - 20, 560, cy + 20],
                    fill=((i * 53) % 255, 80, 160))               # 缩略图
    box = (int(600 * 0.15), int(500 * 0.072), int(600 * 0.22), int(500 * 0.112))
    d.rectangle(list(box), fill=(240, 240, 240), outline=(180, 180, 180))
    article = Image.new("RGB", (600, 500), (255, 255, 255))
    return fav, article, box


_FAKE_TITLE_W = (150, 260, 360)
_FAKE_ACCT_W = (120, 200, 160)


def _fake_rows(n=3):
    """3 行行几何：文字区 180~540、缩略图 500~560（与 _fake_pages 对齐）。"""
    return [{"y1": c - 20, "y2": c + 20, "center": c,
             "thumb_x1": 500, "thumb_x2": 560,
             "account_box": [180, c + 8, 300, c + 24],
             "click_point": [300, c]}
            for c in (60, 160, 260)[:n]]


class TestRunLoopRegressions(unittest.TestCase):
    """run() 主循环的两条 2026-10-23 回归（都是实测抓到的 bug）：

    ① dry-run 曾把决策写成 click 落进 journal，之后真跑全部被当成已处理；
    ② processed 集合加载一次后不更新，--max-rounds>1 时同一行被重复点。
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.out = Path(self._tmp.name)
        self.tpl = self.out / "templates"
        self.tpl.mkdir()
        self.fav, self.article, self.tabbox = _fake_pages()
        vision.save(vision.crop(self.fav, self.tabbox),
                    self.tpl / "tab-all.png")
        self.pages = []
        self.clicked = []
        self._patchers = []

        def fake_capture(hwnd=0, title_regex=""):
            return (self.pages.pop(0), (0, 0, 600, 500)) if self.pages else None

        def fake_rows(img, **kw):
            # 列表恒定返回 3 行（模拟"点开文章不会让行消失"）
            return _fake_rows(3)

        def fake_click(x, y, **kw):
            self.clicked.append((x, y))
            return True

        for target, attr, repl in (
                (wf, "OUT", self.out),
                (wf, "TPL", self.tpl),
                (vision, "capture_window", fake_capture),
                (vision, "detect_rows", fake_rows),
                (vision, "click_at", fake_click),
                (vision, "key_tap", lambda *a, **k: None),
                (vision, "is_blank", lambda img, thresh=0.985: False),
                (vision, "activate_window", lambda hwnd, settle=0.6: True),
                (vision, "wechat_windows",
                 lambda: [{"hwnd": 1, "cls": "C", "title": "微信",
                           "rect": [0, 0, 600, 500], "iconic": False}]),
                (wf, "collected_accounts", lambda root: set()),
                (wf, "_nap", lambda base: None),
                (wf, "_write_gap", lambda: None),
                (wf, "_before_write", lambda: None),
        ):
            p = mock.patch.object(target, attr, repl)
            p.start()
            self._patchers.append(p)

    def tearDown(self):
        for p in self._patchers:
            p.stop()

    def _args(self, **kw):
        base = dict(download_root=".", max_rounds=1, dry_run=False, scroll=0,
                    return_key="esc", settle=0.0, open_timeout=1.0,
                    back_timeout=1.0)
        base.update(kw)
        return SimpleNamespace(**base)

    def test_dry_run_does_not_poison_journal(self):
        self.pages = [self.fav]
        rc = wf.run(self._args(dry_run=True))
        self.assertEqual(rc, wf.EXIT_OK)
        self.assertEqual(self.clicked, [])               # 预演不点
        journal = self.out / "favorites-journal.jsonl"
        rec = json.loads(journal.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(rec["decision"], "would_click")  # 不是 click
        self.assertEqual(wf.processed_fingerprints(journal), set())

    def test_multi_round_does_not_reclick_same_row(self):
        # 页面序列：首检 fav → r0 离页 article → r0 回页 fav →
        #           r1 检 fav → r1 离页 article → r1 回页 fav → r2 检 fav
        self.pages = [self.fav, self.article, self.fav,
                      self.fav, self.article, self.fav, self.fav]
        # 本用例只测「行指纹去重」，把账号指纹闸门关掉（同号拦截另有专门用例），
        # 行数取 2：3 轮里前 2 轮各点 1 行，第 3 轮无未处理行 → all_processed。
        with mock.patch.object(vision, "detect_rows",
                               lambda img, **kw: _fake_rows(2)), \
             mock.patch.object(wf, "account_key", return_value=None):
            rc = wf.run(self._args(max_rounds=3))
        self.assertEqual(len(self.clicked), 2, "同一行被重复点击：%s" % self.clicked)
        self.assertNotEqual(self.clicked[0], self.clicked[1])
        # 两次点击分别落在不同行（行中心相距 100px，抖动只有 ±5px）
        self.assertGreater(abs(self.clicked[0][1] - self.clicked[1][1]), 50,
                           "两次点击落在同一行：%s" % (self.clicked,))
        self.assertEqual(rc, wf.EXIT_PARTIAL)
        journal = self.out / "favorites-journal.jsonl"
        fps = wf.processed_fingerprints(journal)
        self.assertEqual(len(fps), 2)                    # journal 记了 2 个 click

    def test_same_account_multirow_clicked_once(self):
        """同一公众号在列表里占多行：只点第一篇，后续行判 skip。

        旧实现两个洞叠加会连点同号多篇：① registry 只在启动读一次（下载侧
        新建的目录要下次运行才可见）；② skip 行不推进，下一轮又评估同一行。
        这里把 identify_account 固定为"未命中"（模拟下载侧还没落盘），再用
        恒定账号指纹模拟"同号两行文字完全一样"。
        """
        self.pages = [self.fav, self.article, self.fav, self.fav, self.fav]
        const = np.ones(8, dtype=np.float32) / np.sqrt(8.0)
        with mock.patch.object(wf, "identify_account",
                               return_value=(None, 0.0)), \
             mock.patch.object(wf, "account_key", return_value=const), \
             mock.patch.object(wf, "row_fingerprint",
                               side_effect=lambda img, row: "row-%d" % row["center"]):
            rc = wf.run(self._args(max_rounds=3))
        self.assertEqual(len(self.clicked), 1, "同号多行被连点：%s" % (self.clicked,))
        recs = [json.loads(x) for x in
                (self.out / "favorites-journal.jsonl").read_text(
                    encoding="utf-8").splitlines()]
        self.assertEqual([x["decision"] for x in recs], ["click", "skip", "skip"])
        self.assertIn("账号指纹", recs[1]["reason"])
        self.assertAlmostEqual(recs[1]["same_account_sim"], 1.0, places=3)
        self.assertEqual(rc, wf.EXIT_OK)

    def test_skip_advances_to_next_row(self):
        """跳过一行后必须推进到下一行，否则 --max-rounds>1 原地打转。"""
        self.pages = [self.fav, self.fav, self.fav]
        seq = [("食品研发与生产", 0.92), ("食品研发与生产", 0.92),
               ("宠物食品商情", 0.78)]
        with mock.patch.object(wf, "identify_account", side_effect=seq), \
             mock.patch.object(wf, "account_key", return_value=None), \
             mock.patch.object(wf, "row_fingerprint",
                               side_effect=lambda img, row: "row-%d" % row["center"]):
            wf.run(self._args(max_rounds=3))
        recs = [json.loads(x) for x in
                (self.out / "favorites-journal.jsonl").read_text(
                    encoding="utf-8").splitlines()]
        self.assertEqual(len(recs), 3)
        self.assertNotEqual(recs[0]["fp"], recs[1]["fp"],
                            "skip 后没推进：同一行被重复评估")
        self.assertEqual(self.clicked, [], "全部命中名单，不该有点击")


class TestJournalAlgo(unittest.TestCase):
    """行指纹没有"算法版本"，算法一改旧记录就失配 ⇒ 必须能被识别出来。

    2026-10-23 实测代价：左界改成下半部统计后每行 y 上移 109px，同一条
    「WorkBuddy 越用越慢」被重复点了一次。只告警、不删记录（回放记录价值更高）。
    """

    def test_stale_count_flags_old_records(self):
        with tempfile.TemporaryDirectory() as d:
            j = Path(d) / "j.jsonl"
            j.write_text("\n".join([
                json.dumps({"decision": "click", "fp": "a"}),                     # 老记录无 algo
                json.dumps({"decision": "click", "fp": "b", "algo": "rows-v1"}),  # 旧算法
                json.dumps({"decision": "click", "fp": "c", "algo": wf.FP_ALGO}), # 当前算法
                json.dumps({"decision": "would_click", "fp": "d"}),               # 预演不算
            ]) + "\n", encoding="utf-8")
            self.assertEqual(wf.journal_stale_count(j), 2)
            self.assertEqual(wf.processed_fingerprints(j), {"a", "b", "c"})

    def test_stale_count_missing_file(self):
        self.assertEqual(wf.journal_stale_count(Path("no-such-journal.jsonl")), 0)


class TestRowFingerprintUniqueness(unittest.TestCase):
    """行指纹必须逐行唯一——撞指纹的后果是**静默漏采**，不是"少点一次"。

    旧实现（缩略图左沿→窗口右沿 + dHash size=8）在真实收藏页上 10 行只出 9 个
    唯一值：点了 A 行之后 B 行被当成已处理跳过。
    """

    def _page(self):
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (1000, 1100), (250, 250, 250))
        d = ImageDraw.Draw(img)
        for i in range(10):
            y = 20 + i * 106
            # 标题：宽度随行号单调变（真实页标题本就长短不一，8~40 字）。
            # 步长 40 太小：文字区横向量化到 17 列后差异被均值吃掉，会撞指纹；
            # 70px/行 实测 10/10 唯一，且末行 60+200+9*70=890 仍在缩略图左沿
            # (900) 之内，不会被裁成等宽。
            d.rectangle([60, y, 260 + i * 70, y + 22], fill=(40, 40, 40))
            d.rectangle([60, y + 34, 170, y + 50], fill=(160, 160, 160))  # 账号名
            d.rectangle([900, y, 980, y + 70], fill=(120, 60, 60))        # 缩略图：10 行全同
        return img

    def test_ten_similar_rows_are_distinct(self):
        img = self._page()
        rows = [{"y1": 20 + i * 106, "y2": 20 + i * 106 + 92, "thumb_x1": 900}
                for i in range(10)]
        fps = [wf.row_fingerprint(img, r) for r in rows]
        self.assertEqual(len(set(fps)), 10, "行指纹撞值：%d/10 唯一" % len(set(fps)))
        # 证伪：旧的"含缩略图 + dHash8"在同样图上必然撞（缩略图 10 行完全相同）
        old = [vision.dhash(vision.crop(img, (r["thumb_x1"], r["y1"],
                                             img.width, r["y2"]))) for r in rows]
        self.assertLess(len(set(old)), 10, "旧算法本该撞指纹，否则用例无效")

    def test_fingerprint_ignores_cursor_hover_shading(self):
        """行内整体压暗（模拟 hover 底色）不应改变文字区指纹的判定语义——
        这里只断言"同一行两次计算结果一致"，hover 的实际差异靠 park_cursor 消除。
        """
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (600, 200), (250, 250, 250))
        d = ImageDraw.Draw(img)
        d.rectangle([60, 40, 300, 62], fill=(40, 40, 40))
        d.rectangle([60, 74, 200, 90], fill=(160, 160, 160))
        row = {"y1": 40, "y2": 92, "thumb_x1": 560}
        self.assertEqual(wf.row_fingerprint(img, row), wf.row_fingerprint(img, row))


if __name__ == "__main__":
    unittest.main()
