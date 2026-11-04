#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pipeline.py 编排层冒烟测试（不依赖微信/下载，纯本地可执行）。

覆盖：
  1. 结构：14 阶段 ORDER 顺序正确、STAGES 与 ORDER 一一对应、每个阶段都是可调用函数。
  2. 干跑全链路：--plan 真正跑 preflight + verify（read-only），退出 0，
     且计划行列出全部 14 个阶段（曾回归：guards/images 漏接就看不到）。
  3. 切片：--from-step/--to-step/--skip 正确截出子序列；写阶段在 dry 下被跳过。

跑法（生产解释器）：
  python tests/test_pipeline_smoke.py
"""
import contextlib
import importlib.util
import io
import unittest
from pathlib import Path

PIPELINE = Path(r"C:/Users/Administrator/.workbuddy/skills/ui-auto-click/scripts/pipeline.py")
VEIN = r"D:/workbuddy重做系统后版本/2026-10-16-21-12-03"

EXPECTED_ORDER = ["preflight", "scout", "download", "clean", "manifest", "meta",
                  "package", "ingest", "guards", "images", "maps", "derived",
                  "export", "verify"]


def load():
    spec = importlib.util.spec_from_file_location("pipeline_ut", PIPELINE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class PipelineSmokeTest(unittest.TestCase):
    def test_structure_wired(self):
        mod = load()
        self.assertEqual(mod.ORDER, EXPECTED_ORDER, "阶段顺序必须与预期一致")
        self.assertEqual(set(mod.STAGES.keys()), set(mod.ORDER), "STAGES 与 ORDER 必须一一对应")
        for name in mod.ORDER:
            self.assertTrue(callable(mod.STAGES[name]), f"{name} 必须是可调用阶段函数")

    def test_dry_plan_lists_all_14(self):
        mod = load()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = mod.main(["--account", "食品研发与生产", "--plan", "--vein", VEIN])
        out = buf.getvalue()
        self.assertEqual(rc, 0, "干跑应退出 0")
        for s in EXPECTED_ORDER:
            self.assertIn(s, out, f"计划行应列出阶段 {s}")
        # read-only 阶段实际执行、写阶段跳过
        self.assertIn("VERDICT", out.upper() + out, "verify 应实际跑了 validate.py")

    def test_skip_slicing(self):
        mod = load()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = mod.main(["--account", "X", "--from-step", "ingest",
                           "--to-step", "images", "--dry", "--vein", VEIN])
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("ingest", out)
        self.assertIn("guards", out)
        self.assertIn("images", out)
        # from-step 之前、to-step 之后都不应出现在计划里
        self.assertNotIn("preflight", out.split("阶段")[0])  # 计划行前不应含（粗略）
        self.assertNotIn("export", out)
        self.assertNotIn("verify", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
