#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""common.py 单元测试：配置合并/JSONL 往返/退出码映射/合规闸/礼貌延迟。"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import common  # noqa: E402


class TestConfig(unittest.TestCase):
    def test_default_config(self) -> None:
        config = common.load_config(None)
        self.assertEqual(config["library"]["batch_size"], 50)
        self.assertEqual(config["library"]["space"], "铭衍·元典")

    def test_missing_file_falls_back_to_default(self) -> None:
        config = common.load_config("/nonexistent/path/nope.yaml")
        self.assertEqual(config["rate_limit"]["min_delay_seconds"], 3.0)

    def test_deep_merge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "c.yaml"
            cfg_path.write_text(
                "library:\n  batch_size: 80\nrate_limit:\n  max_delay_seconds: 12.0\n",
                encoding="utf-8",
            )
            config = common.load_config(str(cfg_path))
        self.assertEqual(config["library"]["batch_size"], 80)
        self.assertEqual(config["rate_limit"]["max_delay_seconds"], 12.0)
        self.assertEqual(config["rate_limit"]["min_delay_seconds"], 3.0)
        self.assertEqual(config["library"]["space"], "铭衍·元典")


class TestJsonl(unittest.TestCase):
    def test_roundtrip(self) -> None:
        records = [{"a": 1}, {"b": "中文"}]
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "t.jsonl")
            count = common.write_jsonl(path, records)
            self.assertEqual(count, 2)
            loaded = list(common.read_jsonl(path))
        self.assertEqual(loaded, records)

    def test_bad_line_skipped_not_silent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.jsonl"
            path.write_text('{"a":1}\nnot-json\n{"b":2}\n', encoding="utf-8")
            loaded = list(common.read_jsonl(str(path)))
        self.assertEqual(loaded, [{"a": 1}, {"b": 2}])


class TestExitCodes(unittest.TestCase):
    def test_level_mapping(self) -> None:
        self.assertEqual(common.exit_code_for("ok"), 0)
        self.assertEqual(common.exit_code_for("info"), 0)
        self.assertEqual(common.exit_code_for("param"), 2)
        self.assertEqual(common.exit_code_for("error"), 3)
        self.assertEqual(common.exit_code_for("compliance"), 4)
        self.assertEqual(common.exit_code_for("partial"), 5)
        self.assertEqual(common.exit_code_for("warn"), 5)
        self.assertEqual(common.exit_code_for("env"), 6)


class TestAttest(unittest.TestCase):
    def test_yes_flag_passes(self) -> None:
        self.assertTrue(common.attest(argparse.Namespace(yes=True)))

    def test_non_interactive_without_yes_blocked(self) -> None:
        # 测试环境 stdin 非 tty，必须被拦截（不挂起）
        self.assertFalse(common.attest(argparse.Namespace(yes=False)))


class TestSleepPolite(unittest.TestCase):
    def test_bounds_with_small_window(self) -> None:
        config = {"rate_limit": {"min_delay_seconds": 0.01, "max_delay_seconds": 0.02}}
        for _ in range(3):
            seconds = common.sleep_polite(config)
            self.assertGreaterEqual(seconds, 0.01)
            self.assertLessEqual(seconds, 0.02)


if __name__ == "__main__":
    unittest.main()
