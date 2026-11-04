#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""clean 阶段的回归测试（2026-10-23 真机事故）。

事故复盘：
  `clean_noise_v2.py` 原来按 `manifest.json` 遍历待清洗文件，但编排器里
  clean 阶段跑在 **manifest 之前** —— 那一刻 manifest 还是上一轮的旧清单（95 篇），
  本轮新下的 46 篇不在里面。结果这 3 篇（1026现场直播 / 低学历不配 / 配方换了代糖）
  的 44 行「取消  允许」UI 残句一路带到 package 阶段，才以
  「body_md 无受限页残句」失败，且报错不点名。

这两类问题都要有测试守着：
  1. 遍历范围必须来自目录（clean/*.md），与 manifest 无关；
  2. 残留必须在本阶段就地拦截并点名，不能等 package。
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ["UIAC_NO_DPI_AWARE"] = "1"
SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))

import pipeline as pl  # noqa: E402

_spec = importlib.util.spec_from_file_location("clean_noise_v2", SKILL / "out" / "tools"
                                               / "clean_noise_v2.py")
cn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cn)

NOISY_TAIL = (
    "正文最后一段。\n\n预览时标签不可点\n\n阅读原文\n\n阅读\n\n不喜欢\n\n知道了\n\n"
    "****\n\n取消  允许\n\n****\n\n取消  允许\n\n____\n\n"
)


def _write(p: Path, text: str, crlf: bool = True) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    body = text.replace("\n", "\r\n") if crlf else text
    p.write_bytes(body.encode("utf-8"))


class TestSweepScope(unittest.TestCase):
    def test_sweeps_clean_dir_not_manifest(self):
        """clean/ 下有 3 篇、旧 manifest 只列 1 篇 —— 必须扫到 3 篇。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for name in ("a", "b", "c"):
                _write(root / "clean" / f"{name}.md", "x\n")
            _write(root / "_reports" / "manifest.json",
                   '{"articles": [{"title": "a", "local_md": "clean/a.md"}]}')
            got = [p.stem for p in cn.sweep(root)]
            self.assertEqual(got, ["a", "b", "c"])

    def test_falls_back_to_root_when_no_clean_dir(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(root / "raw1.md", "x\n")
            _write(root / "raw2.md", "x\n")
            self.assertEqual([p.stem for p in cn.sweep(root)], ["raw1", "raw2"])

    def test_sweep_is_manifest_free(self):
        """manifest 完全缺失也不许炸 —— 它不该是依赖。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(root / "clean" / "only.md", "x\n")
            self.assertEqual([p.stem for p in cn.sweep(root)], ["only"])


class TestCleanDropsResidue(unittest.TestCase):
    def test_double_space_cancel_allow(self):
        """真实残句是「取消␣␣允许」（两个空格），norm 压成一个后必须命中白名单。"""
        text = "正文。\n\n取消  允许\n"
        new, dropped, _ = cn.clean(text)
        self.assertEqual(dropped, 1)
        self.assertNotIn("允许", new)

    def test_noisy_tail_fully_removed(self):
        new, dropped, _ = cn.clean(NOISY_TAIL)
        for kw in pl.RESTRICTED:
            self.assertNotIn(kw, new)
        self.assertIn("正文最后一段。", new)
        self.assertGreater(dropped, 0)

    def test_real_content_line_kept(self):
        """正文里正常提到「允许」的句子不能被当成噪声删掉。"""
        line = "标签上必须写明允许使用的食品添加剂品种。"
        new, _dropped, _ = cn.clean(line + "\n")
        self.assertIn(line, new)


class TestStageCleanGuard(unittest.TestCase):
    def _ctx(self, root: Path):
        return {"root": root, "base": root.parent, "vein": root, "exe": root / "t.exe",
                "account": "某号", "scout_rounds": 1, "scout_dry": False,
                "return_key": "none"}

    def test_passes_when_no_residue(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(root / "clean" / "ok.md", "干净正文。\n")
            with mock.patch.object(pl, "run"):
                detail = pl.stage_clean(self._ctx(root))
            self.assertIn("0 篇残留", detail)

    def test_fails_and_names_file_when_residue_left(self):
        """清洗工具"跑成功"但文件里仍有残句时，本阶段必须失败并点名。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(root / "clean" / "配方换了代糖为什么喝起来不对味.md", NOISY_TAIL)
            with mock.patch.object(pl, "run"):     # 模拟工具跑过、没生效
                with self.assertRaises(pl.StageFail) as cm:
                    pl.stage_clean(self._ctx(root))
            msg = str(cm.exception)
            self.assertIn("配方换了代糖为什么喝起来不对味", msg)
            self.assertIn("取消  允许", msg)

    def test_clean_residue_lists_all_hits(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(root / "clean" / "a.md", "环境异常\n")
            _write(root / "clean" / "b.md", "使用完整服务\n")
            _write(root / "clean" / "c.md", "正常\n")
            bad = pl._clean_residue(root)
            self.assertEqual(len(bad), 2)
            self.assertTrue(any("a（环境异常）" in x for x in bad))

    def test_guard_reuses_same_keyword_list_as_package(self):
        """pipeline 与 export_import_package 的关键词表必须一致，否则守卫形同虚设。"""
        spec = importlib.util.spec_from_file_location(
            "eip", SKILL / "out" / "tools" / "export_import_package.py")
        eip = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(eip)
        self.assertEqual(tuple(eip.RESTRICTED), tuple(pl.RESTRICTED))


if __name__ == "__main__":
    unittest.main(verbosity=2)
