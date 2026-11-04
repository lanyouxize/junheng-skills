#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rhythm.py 离线单测：档位语义、nap 只加长、限流配额/冷却/持久化、落点抖动。

全部不联网、不点微信、不截图。限流测试把冷却注入成 0.05~0.10s，断言
"真的睡了"但不真睡 30~75 秒；写动作时间戳落在 tempdir，不碰 <skill>/out/。
"""
from __future__ import annotations

import contextlib
import io
import json
import msvcrt          # 锁常量名回归测试用（LK_LOCK/LK_UNLCK 真实存在）
import os
import random
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import rhythm  # noqa: E402


class TestLevelTable(unittest.TestCase):
    """档位表与设计稿逐项对齐（窗口/冷却这些行为测试覆盖不到的数字）。"""

    def test_levels_tuple(self):
        self.assertEqual(rhythm.LEVELS, ("off", "fast", "natural", "calm"))

    def test_natural_and_calm_specs(self):
        # 直接查档位表：行为测试只能验证区间，验证不了"120s/300s"这种绝对值。
        nat = rhythm._LEVEL_SPECS["natural"]
        self.assertEqual((nat.nap_mult, nat.gap, nat.quota, nat.window, nat.cooldown),
                         ((1.0, 1.45), (2.5, 6.0), 6, 120.0, (30.0, 75.0)))
        calm = rhythm._LEVEL_SPECS["calm"]
        self.assertEqual((calm.nap_mult, calm.gap, calm.quota, calm.window, calm.cooldown),
                         ((1.0, 2.0), (6.0, 14.0), 3, 300.0, (60.0, 150.0)))


class TestLevelResolution(unittest.TestCase):
    """档位解析：默认 natural、env 覆盖、非法回退 + stderr 只 warn 一次。"""

    def test_default_is_natural(self):
        with mock.patch.dict(os.environ):
            os.environ.pop(rhythm.ENV_LEVEL, None)
            self.assertEqual(rhythm.Rhythm().level, "natural")

    def test_env_overrides_level(self):
        for level in rhythm.LEVELS:
            with mock.patch.dict(os.environ, {rhythm.ENV_LEVEL: level}):
                self.assertEqual(rhythm.Rhythm().level, level)

    def test_env_value_is_trimmed_and_case_insensitive(self):
        with mock.patch.dict(os.environ, {rhythm.ENV_LEVEL: "  CALM "}):
            self.assertEqual(rhythm.Rhythm().level, "calm")

    def test_invalid_env_falls_back_and_warns_once(self):
        """坏值回退 natural；同一进程同一坏值只 warn 一次（按值去重）。"""
        bad = "env-level-bogus"
        buf = io.StringIO()
        with mock.patch.dict(os.environ, {rhythm.ENV_LEVEL: bad}):
            with contextlib.redirect_stderr(buf):
                first = rhythm.Rhythm()
                second = rhythm.Rhythm()   # 第二次构造：不该再刷一行
        self.assertEqual(first.level, "natural")
        self.assertEqual(second.level, "natural")
        self.assertEqual(buf.getvalue().count(bad), 1)
        self.assertIn("natural", buf.getvalue())

    def test_invalid_explicit_level_also_warns(self):
        bad = "explicit-level-bogus"
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            r = rhythm.Rhythm(bad)
        self.assertEqual(r.level, "natural")
        self.assertIn(bad, buf.getvalue())


class TestNap(unittest.TestCase):
    """nap：等待只加长不缩短；off 原样返回且不睡。"""

    def test_natural_nap_only_lengthens(self):
        """200 次采样：base <= 实睡 <= base*1.45（乘数上限 1.45）。

        sleep 被打假——这里验证的是"乘数决策"而不是 wall clock；真睡的
        行为由 test_nap_really_sleeps 与 off 档测试覆盖。
        """
        r = rhythm.Rhythm("natural", rng=random.Random(20260921))
        base = 0.01
        with mock.patch("time.sleep") as fake_sleep:
            for _ in range(200):
                slept = r.nap(base)
                self.assertGreaterEqual(slept, base)
                self.assertLessEqual(slept, base * 1.45)
                fake_sleep.assert_called_once_with(slept)
                fake_sleep.reset_mock()

    def test_nap_really_sleeps(self):
        r = rhythm.Rhythm("natural", rng=random.Random(3))
        began = time.monotonic()
        slept = r.nap(0.05)
        elapsed = time.monotonic() - began
        self.assertGreaterEqual(slept, 0.05)
        self.assertGreaterEqual(elapsed, slept - 0.005)   # 留计时粒度余量

    def test_fast_nap_multiplier_is_one(self):
        r = rhythm.Rhythm("fast", rng=random.Random(5))
        with mock.patch("time.sleep") as fake_sleep:
            self.assertEqual(r.nap(0.3), 0.3)
            fake_sleep.assert_called_once_with(0.3)

    def test_calm_nap_multiplier_within_two(self):
        r = rhythm.Rhythm("calm", rng=random.Random(9))
        with mock.patch("time.sleep") as fake_sleep:
            for _ in range(100):
                slept = r.nap(0.01)
                self.assertGreaterEqual(slept, 0.01)
                self.assertLessEqual(slept, 0.02)
                fake_sleep.reset_mock()

    def test_off_nap_returns_base_without_sleeping(self):
        """off = 关闭节奏管理，不是跳过等待：原样返回 base，睡不睡由调用方定。"""
        r = rhythm.Rhythm("off", rng=random.Random(1))
        began = time.monotonic()
        self.assertEqual(r.nap(1.0), 1.0)
        self.assertEqual(r.nap(0.25), 0.25)
        self.assertLess(time.monotonic() - began, 0.05)   # 单调时钟：真的没睡


class TestWriteGap(unittest.TestCase):
    """write_gap：按档位取写间隔；off 返回 0.0 不睡。"""

    def test_fast_gap_range(self):
        r = rhythm.Rhythm("fast", rng=random.Random(17))
        with mock.patch("time.sleep") as fake_sleep:
            for _ in range(100):
                gap = r.write_gap()
                self.assertGreaterEqual(gap, 0.2)
                self.assertLessEqual(gap, 0.5)
                fake_sleep.assert_called_once_with(gap)
                fake_sleep.reset_mock()

    def test_fast_gap_really_sleeps(self):
        """fast 档允许真睡（上限 0.5s）：验证返回值与真实耗时一致。"""
        r = rhythm.Rhythm("fast", rng=random.Random(4))
        began = time.monotonic()
        gap = r.write_gap()
        self.assertGreaterEqual(gap, 0.2)
        self.assertLessEqual(gap, 0.5)
        self.assertGreaterEqual(time.monotonic() - began, gap - 0.005)

    def test_natural_and_calm_gap_ranges(self):
        cases = {"natural": (2.5, 6.0), "calm": (6.0, 14.0)}
        for level, (low, high) in cases.items():
            r = rhythm.Rhythm(level, rng=random.Random(23))
            with mock.patch("time.sleep"):
                for _ in range(50):
                    gap = r.write_gap()
                    self.assertGreaterEqual(gap, low, level)
                    self.assertLessEqual(gap, high, level)

    def test_off_write_gap_returns_zero(self):
        r = rhythm.Rhythm("off", rng=random.Random(1))
        began = time.monotonic()
        self.assertEqual(r.write_gap(), 0.0)
        self.assertLess(time.monotonic() - began, 0.05)


class TestJitter(unittest.TestCase):
    """jitter_xy：控件内随机落点，不越界、可复现。"""

    def test_within_default_radius(self):
        r = rhythm.Rhythm("natural", rng=random.Random(31))
        for _ in range(200):
            x, y = r.jitter_xy(500, 300)
            self.assertLessEqual(abs(x - 500), 5)
            self.assertLessEqual(abs(y - 300), 5)

    def test_radius_honoured(self):
        r = rhythm.Rhythm("natural", rng=random.Random(32))
        for _ in range(100):
            x, y = r.jitter_xy(100, 100, radius=2)
            self.assertLessEqual(abs(x - 100), 2)
            self.assertLessEqual(abs(y - 100), 2)

    def test_seed_makes_it_reproducible(self):
        """UIAC_RHYTHM_SEED 存在时同种子同序列——单测确定性的根基。"""
        with mock.patch.dict(os.environ, {rhythm.ENV_SEED: "42"}):
            a, b = rhythm.Rhythm("natural"), rhythm.Rhythm("natural")
            seq_a = [a.jitter_xy(0, 0) for _ in range(5)]
            seq_b = [b.jitter_xy(0, 0) for _ in range(5)]
        self.assertEqual(seq_a, seq_b)
        self.assertGreater(len(set(seq_a)), 1)   # 防"永远是 (0,0)"的假绿

    def test_bad_seed_falls_back_silently(self):
        with mock.patch.dict(os.environ, {rhythm.ENV_SEED: "not-a-number"}):
            r = rhythm.Rhythm("natural")
        x, y = r.jitter_xy(10, 10, radius=3)     # 不抛、仍可用
        self.assertLessEqual(abs(x - 10), 3)
        self.assertLessEqual(abs(y - 10), 3)


class TestSingleton(unittest.TestCase):
    """get_rhythm 单例 + set_rhythm_for_test 注入 + 模块级函数委托。"""

    def test_get_rhythm_is_process_singleton(self):
        self.assertIs(rhythm.get_rhythm(), rhythm.get_rhythm())

    def test_set_rhythm_for_test_replaces_singleton(self):
        r = rhythm.Rhythm("off", rng=random.Random(1))
        self.assertIs(rhythm.set_rhythm_for_test(r), rhythm.get_rhythm())
        # 模块级 nap/write_gap/jitter_xy 都走单例
        began = time.monotonic()
        self.assertEqual(rhythm.nap(1.0), 1.0)
        self.assertEqual(rhythm.write_gap(), 0.0)
        self.assertLess(time.monotonic() - began, 0.05)
        x, y = rhythm.jitter_xy(50, 60, radius=3)
        self.assertLessEqual(abs(x - 50), 3)
        self.assertLessEqual(abs(y - 60), 3)

    def test_default_singleton_is_natural(self):
        with mock.patch.dict(os.environ):
            os.environ.pop(rhythm.ENV_LEVEL, None)
            rhythm.set_rhythm_for_test(rhythm.Rhythm())
            self.assertEqual(rhythm.get_rhythm().level, "natural")


class TestWriteRateLimiter(unittest.TestCase):
    """写动作限流：滑动窗口配额、超限冷却、状态持久化、损坏静默重置。

    冷却注入成 (0.05, 0.10)s：断言"睡了"但不真睡 30~75 秒。
    """

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="uac-rhythm-"))
        self.state = self.dir / "rhythm-state.json"

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _limiter(self, **overrides):
        params = dict(state_path=self.state, level="natural",
                      cooldown_range=(0.05, 0.1), rng=random.Random(2024))
        params.update(overrides)
        return rhythm.WriteRateLimiter(**params)

    def test_six_writes_pass_seventh_cools_down(self):
        """natural 配额 6 次/120s：前 6 次放行，第 7 次睡冷却。"""
        lim = self._limiter()
        for i in range(6):
            began = time.monotonic()
            cool = lim.before_write()
            self.assertEqual(cool, 0.0, "第 %d 次不该触发冷却" % (i + 1))
            self.assertLess(time.monotonic() - began, 0.05)
        began = time.monotonic()
        cool = lim.before_write()
        elapsed = time.monotonic() - began
        self.assertGreaterEqual(cool, 0.05)        # 冷却值不低于注入区间下限
        self.assertGreaterEqual(elapsed, 0.05)     # 且真的睡到了冷却结束
        stamps = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(len(stamps), 1)           # 睡完作废旧历史，只记本次

    def test_state_file_records_every_write(self):
        lim = self._limiter()
        for _ in range(3):
            lim.before_write()
        stamps = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(len(stamps), 3)
        self.assertTrue(all(isinstance(t, float) for t in stamps))

    def test_second_instance_sees_first_instances_writes(self):
        """跨实例（= 跨进程语义）持久化：新实例必须从文件看到旧记录。"""
        first = self._limiter()
        for _ in range(6):
            first.before_write()
        second = self._limiter()          # 同 state_path，全新实例
        began = time.monotonic()
        cool = second.before_write()
        self.assertGreaterEqual(cool, 0.05)        # 看见 6 条 → 超配额
        self.assertGreaterEqual(time.monotonic() - began, 0.05)

    def test_window_slides(self):
        """窗口是"最近 N 秒"而不是"每 N 秒重置"：旧记录滑出后就放行。"""
        lim = self._limiter(quota=2, window=0.3)
        self.assertEqual(lim.before_write(), 0.0)
        self.assertEqual(lim.before_write(), 0.0)
        time.sleep(0.35)                # 让前两次滑出 0.3s 窗口
        began = time.monotonic()
        self.assertEqual(lim.before_write(), 0.0)  # 窗口内计数归零 → 放行
        self.assertLess(time.monotonic() - began, 0.05)

    def test_corrupt_state_file_resets_silently(self):
        self.state.write_text("{不是 JSON", encoding="utf-8")
        lim = self._limiter()
        began = time.monotonic()
        self.assertEqual(lim.before_write(), 0.0)  # 不抛，按空历史放行
        self.assertLess(time.monotonic() - began, 0.05)
        stamps = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(len(stamps), 1)           # 坏文件被合法内容覆盖

    def test_state_file_with_garbage_entries_is_filtered(self):
        """脏条目（字符串/None/布尔）静默过滤，有效时间戳保留。"""
        self.state.write_text(json.dumps(["x", None, True, time.time()]),
                              encoding="utf-8")
        lim = self._limiter()
        self.assertEqual(lim.before_write(), 0.0)
        stamps = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(len(stamps), 2)           # 1 条有效旧记录 + 本次

    def test_missing_state_file_is_fine(self):
        lim = self._limiter()                       # 文件不存在
        self.assertEqual(lim.before_write(), 0.0)
        self.assertTrue(self.state.is_file())

    def test_fast_and_off_limiters_spin_free(self):
        """fast 不限流、off 空转：都不记录、不建状态文件。"""
        for level in ("fast", "off"):
            with self.subTest(level=level):
                lim = rhythm.WriteRateLimiter(state_path=self.state, level=level)
                began = time.monotonic()
                for _ in range(10):
                    self.assertEqual(lim.before_write(), 0.0)
                self.assertLess(time.monotonic() - began, 0.05)
                self.assertFalse(self.state.exists())

    def test_default_state_path_points_into_skill_out(self):
        """默认落 <skill>/out/rhythm-state.json：跨进程/跨重启累计的关键。"""
        lim = rhythm.WriteRateLimiter(level="natural")
        self.assertEqual(lim.state_path, rhythm.DEFAULT_STATE_PATH)
        self.assertEqual(lim.state_path.parent.name, "out")
        self.assertEqual(lim.state_path.name, "rhythm-state.json")

    def test_concurrent_writes_do_not_lose_records(self):
        """并发 before_write 不丢记录（last-write-wins 回归测试）。

        旧实现"读出全部→改→整体写回"，两个实例同时写会互相覆盖；
        现在读-改-写在文件锁内完成，两条记录都必须落在文件里。
        用两个独立实例（= 两个独立句柄）而不是同一实例，才复现得了
        跨进程语义的竞态。
        """
        import threading
        results = []
        lock = threading.Lock()

        def worker():
            lim = self._limiter(quota=100)     # 配额放大，确保都走放行分支
            cool = lim.before_write()
            with lock:
                results.append(cool)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        stamps = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(len(stamps), 8, "并发写丢了记录：%d/8" % len(stamps))
        self.assertEqual(len(results), 8)

    def test_lock_constant_exists(self):
        """msvcrt 常量名回归：LK_LK 不存在（曾因写错被 except 静默吞掉，
        整个限流器空转还不报错）。锁相关常量必须真实存在。"""
        self.assertTrue(hasattr(msvcrt, "LK_LOCK"))
        self.assertTrue(hasattr(msvcrt, "LK_UNLCK"))
        self.assertFalse(hasattr(msvcrt, "LK_LK"))


if __name__ == "__main__":
    unittest.main()
