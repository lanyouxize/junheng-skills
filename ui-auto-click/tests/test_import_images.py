#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""import-images.py 回归测试：图片落地 + 压缩 + 幂等 + prune-outside。

用临时 vault 夹具，不碰真实库；用 PIL 造大图当源。
跑法（生产解释器，含 Pillow）：
  python tests/test_import_images.py
"""
import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path

TOOL = Path(r"D:/workbuddy重做系统后版本/2026-10-16-21-12-03/tools/import-images.py")


def load():
    spec = importlib.util.spec_from_file_location("import_images_ut", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_jpeg(path: Path, w=2000, h=1500):
    from PIL import Image
    img = Image.new("RGB", (w, h), (120, 90, 200))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "JPEG", quality=95)


class ImportImagesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="imginfo_"))
        self.vault = self.tmp / "vault"
        self.web = self.vault / "20_Sources" / "web"
        self.imgdir = self.vault / "20_Sources" / "图片"
        self.src = self.tmp / "src"
        self.web.mkdir(parents=True)
        self.src.mkdir()
        # 笔记引用 ../图片/a.jpg 与 b.png（png 后缀也按 RGB 压，沿用工具既有行为）
        (self.web / "note.md").write_text(
            "# 标题\n\n正文 ![a](../图片/a.jpg) 与 ![b](../图片/b.png)\n", encoding="utf-8")
        make_jpeg(self.src / "a.jpg", 2000, 1500)
        make_jpeg(self.src / "b.png", 800, 600)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, *extra):
        mod = load()
        return mod.main(["--apply", "--src", str(self.src),
                         "--vault", str(self.tmp), *extra])

    def _run_check(self, *extra):
        # 只读门禁路径：只传 --check，绝不带 --apply，
        # 否则 apply 分支先执行会写库并 return，check 分支被绕过。
        mod = load()
        return mod.main(["--check", "--src", str(self.src),
                         "--vault", str(self.tmp), *extra])

    def test_landing_and_compress(self):
        rc = self._run()
        self.assertEqual(rc, 0)
        a, b = self.imgdir / "a.jpg", self.imgdir / "b.png"
        self.assertTrue(a.is_file(), "a.jpg 应落入库")
        self.assertTrue(b.is_file(), "b.png 应落入库")
        from PIL import Image
        im = Image.open(a)
        self.assertLessEqual(im.width, 1200, "长边应被压缩到 <=1200")
        self.assertEqual(im.height, round(1500 * 1200 / 2000))

    def test_idempotent_rerun(self):
        self._run()
        a = self.imgdir / "a.jpg"
        m1, s1 = a.stat().st_mtime_ns, a.stat().st_size
        rc = self._run()
        self.assertEqual(rc, 0)
        m2, s2 = a.stat().st_mtime_ns, a.stat().st_size
        self.assertEqual((m1, s1), (m2, s2), "复跑不应改变已入库图片")

    def test_prune_outside_moves_src(self):
        self._run("--prune-outside")
        self.assertFalse((self.src / "a.jpg").is_file(), "prune 后源应被移走")
        outside = list((self.tmp / ".staging").glob("img-outside-*"))
        self.assertTrue(outside, "应创建 img-outside 备份目录")
        self.assertTrue(list(outside[0].glob("*.jpg")), "备份里应有被移走的库外原图")

    def test_prune_outside_no_empty_backup(self):
        self._run()                      # 落库、不 prune，源仍在
        shutil.rmtree(self.src, ignore_errors=True)
        self.src.mkdir()                # 无库外副本
        rc = self._run("--prune-outside")
        self.assertEqual(rc, 0)
        staging = self.tmp / ".staging"
        if staging.is_dir():
            empties = [d for d in staging.glob("img-outside-*") if not any(d.iterdir())]
            self.assertEqual(empties, [], "无库外副本时不应建空备份目录")

    def test_check_passes_when_source_present(self):
        # a.jpg/b.png 在 src 中 ⇒ 可落地（源内可补），只读门禁应通过（退出 0，不写盘）
        rc = self._run_check()
        self.assertEqual(rc, 0)
        self.assertFalse(self.imgdir.is_dir(), "--check 不应写库")

    def test_check_fails_when_unresolvable(self):
        # 增加一篇引用 c.jpg（既不在库内也不在源里）⇒ 门禁失败（退出 5）
        (self.web / "note2.md").write_text(
            "# 另一篇\n\n![c](../图片/c.jpg)\n", encoding="utf-8")
        rc = self._run_check()
        self.assertEqual(rc, 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
