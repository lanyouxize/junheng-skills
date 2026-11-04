#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""l1_fetch_urls.py 离线单测：monkeypatch _fetch_html 返回 fixture，不启动浏览器、不联网。

覆盖 L1 全管线（_process_url / run）：
  ① 正常 URL -> 25 列记录 + body_ref/media_ref 落盘 + images 清单含 local_path；
  ② 非公众号 URL -> fail 且 fail_reason 含 canonicalize_url 说明、不调 _fetch_html；
  ③ empty body（broken fixture）-> fail；
  ④ --no-images -> images 只记 url 无 local_path；
  ⑤ 退出码映射（EXIT_OK / EXIT_PARTIAL / EXIT_PARAM / EXIT_ENV）。
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import l1_fetch_urls as l1  # noqa: E402
from common import load_config  # noqa: E402
from normalize import ARTICLE_FIELDS  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
TEXT_URL = "https://mp.weixin.qq.com/s/AbCdEf123?scene=1&src=11"
BAD_URL = "https://example.com/not-wechat"

# 限流软封模拟：head 已加载（og:title）且含限流关键词，但正文为空 -> 应触发重试
RETRYABLE_EMPTY_HTML = (
    '<html><head><meta property="og:title" content="X"></head>'
    '<body>访问过于频繁，请稍后再试</body></html>'
)
# 真·空页：无 og:title / 无限流关键词 -> 不应重试
NON_RETRYABLE_EMPTY_HTML = "<html><body>not a wechat article</body></html>"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _fake_download_image(requests, url: str, dest: Path, timeout: int) -> None:
    """假图片下载：本地写字节，不联网。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"\x89fake-image-bytes")


class L1OfflineTestCase(unittest.TestCase):
    """公共脚手架：patch _fetch_html / _download_image / sleep_polite + 临时目录。"""

    def setUp(self) -> None:
        patchers = [
            mock.patch.object(l1, "sleep_polite", return_value=0.0),
            mock.patch.object(l1, "_download_image", side_effect=_fake_download_image),
        ]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.out = root / "r.jsonl"
        self.media_dir = root / "r.media"
        self.media_dir.mkdir(parents=True, exist_ok=True)  # _process_url 直调需目录已存在
        self.config = load_config("")

    def _args(self, *, urls: str = TEXT_URL, download_images: bool = True):
        return l1.build_parser().parse_args([
            "url", "--urls", urls, "--out", str(self.out), "--media-dir", str(self.media_dir),
            *([] if download_images else ["--no-images"]),
        ])


class TestProcessUrl(L1OfflineTestCase):
    def test_normal_url_full_pipeline(self) -> None:
        with mock.patch.object(l1, "_fetch_html", return_value=_load("article_text.html")):
            record = l1._process_url(TEXT_URL, self._args(), self.config, self.media_dir)
        self.assertEqual(record["status"], "ok")
        for field in ARTICLE_FIELDS:  # 25 列齐全
            self.assertIn(field, record)
        self.assertEqual(record["collect_layer"], "url")
        self.assertEqual(record["extractor"], "l1:playwright")
        self.assertEqual(record["title"], "猫咪排毛攻略：膳食纤维的科学运用")
        self.assertEqual(record["account"], "宠 ingredients 研究所")
        self.assertEqual(record["publish_time"], "2024-10-22T10:40:00Z")
        self.assertEqual(record["images_count"], 3)

        body_ref = Path(record["body_ref"])
        self.assertTrue(body_ref.is_file())
        self.assertIn("甜菜粕", body_ref.read_text(encoding="utf-8"))

        media_ref = Path(record["images_ref"])
        self.assertTrue(media_ref.is_file())
        manifest = json.loads(media_ref.read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["images"]), 3)
        for image in manifest["images"]:
            self.assertIn("local_path", image)
            self.assertTrue(Path(image["local_path"]).is_file())
        self.assertEqual(manifest["videos"], [])

    def test_non_wechat_url_fails_without_fetching(self) -> None:
        fetch_mock = mock.Mock(side_effect=AssertionError("_fetch_html 不应被调用"))
        with mock.patch.object(l1, "_fetch_html", fetch_mock):
            record = l1._process_url(BAD_URL, self._args(urls=BAD_URL), self.config, self.media_dir)
        self.assertEqual(record["status"], "fail")
        self.assertIn("canonicalize_url", record["fail_reason"])
        fetch_mock.assert_not_called()

    def test_empty_body_fails(self) -> None:
        with mock.patch.object(l1, "_fetch_html", return_value=_load("article_broken.html")):
            record = l1._process_url(TEXT_URL, self._args(), self.config, self.media_dir)
        self.assertEqual(record["status"], "fail")
        self.assertIn("empty body", record["fail_reason"])

    def test_retries_on_soft_block_then_succeeds(self) -> None:
        """首次返回限流软封空页（og:title+限流词），重试后拿到正文 -> ok。"""
        calls = {"n": 0}

        def fake_fetch(url, a):
            calls["n"] += 1
            return RETRYABLE_EMPTY_HTML if calls["n"] == 1 else _load("article_text.html")

        with mock.patch.object(l1, "_fetch_html", side_effect=fake_fetch), \
                mock.patch.object(l1.time, "sleep", return_value=None):
            record = l1._process_url(TEXT_URL, self._args(), self.config, self.media_dir)
        self.assertEqual(record["status"], "ok")
        self.assertGreaterEqual(calls["n"], 2)  # 至少重试一次后成功

    def test_no_retry_on_non_retryable_empty(self) -> None:
        """真·空页（无 og:title / 无限流词）-> 不重试，单次抓取即判 fail。"""
        calls = {"n": 0}

        def fake_fetch(url, a):
            calls["n"] += 1
            return NON_RETRYABLE_EMPTY_HTML

        with mock.patch.object(l1, "_fetch_html", side_effect=fake_fetch):
            record = l1._process_url(TEXT_URL, self._args(), self.config, self.media_dir)
        self.assertEqual(record["status"], "fail")
        self.assertEqual(calls["n"], 1)

    def test_no_images_records_urls_only(self) -> None:
        with mock.patch.object(l1, "_fetch_html", return_value=_load("article_text.html")):
            record = l1._process_url(TEXT_URL, self._args(download_images=False),
                                     self.config, self.media_dir)
        self.assertEqual(record["status"], "ok")
        self.assertEqual(record["images_count"], 3)
        manifest = json.loads(Path(record["images_ref"]).read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["images"]), 3)
        for image in manifest["images"]:
            self.assertNotIn("local_path", image)
        self.assertFalse((self.media_dir / "images").exists())


class TestRunExitCodes(L1OfflineTestCase):
    def _run(self, argv):
        stderr, stdout = io.StringIO(), io.StringIO()
        with redirect_stderr(stderr), redirect_stdout(stdout):
            code = l1.run(l1.build_parser().parse_args(argv))
        events = []
        for line in stderr.getvalue().splitlines():
            line = line.strip()
            # 事件行是 JSON；第三方库告警（如 bs4/lxml DeprecationWarning）会写多行非 JSON，
            # unittest 默认 warnings=default 下尤其明显——只解析事件行，避免告警噪声导致误判。
            if line.startswith("{"):
                events.append(json.loads(line))
        return code, events

    def test_all_ok_returns_zero(self) -> None:
        with mock.patch.object(l1, "_fetch_html", return_value=_load("article_text.html")):
            code, events = self._run(["url", "--urls", TEXT_URL,
                                      "--out", str(self.out), "--media-dir", str(self.media_dir)])
        self.assertEqual(code, l1.EXIT_OK)
        records = [json.loads(line) for line in self.out.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([r["status"] for r in records], ["ok"])
        done = [e for e in events if e["event"] == "l1.done"][-1]
        self.assertEqual((done["total"], done["ok"], done["fail"]), (1, 1, 0))

    def test_mixed_ok_and_fail_returns_partial(self) -> None:
        def _fake_fetch(url, args):
            return _load("article_broken.html") if "broken" in url else _load("article_text.html")

        with mock.patch.object(l1, "_fetch_html", side_effect=_fake_fetch):
            code, _ = self._run(["url", "--urls", f"{TEXT_URL},https://mp.weixin.qq.com/s/broken1",
                                 "--out", str(self.out), "--media-dir", str(self.media_dir)])
        self.assertEqual(code, l1.EXIT_PARTIAL)
        records = [json.loads(line) for line in self.out.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(sorted(r["status"] for r in records), ["fail", "ok"])

    def test_all_fail_returns_error(self) -> None:
        """零产出：全部 URL 都 fail（ok=0 且 partial=0）-> EXIT_ERROR。

        冻结契约：1:1 映射 0 ok / 2 param / 3 error / 5 partial；ok==0 时不存在
        "部分成功"，上层按退出码分流不能把彻底失败当部分数据。partial>0 仍是 5
        （见 test_mixed_ok_and_fail_returns_partial）。
        """
        with mock.patch.object(l1, "_fetch_html", return_value=_load("article_broken.html")):
            code, events = self._run(["url", "--urls",
                                      "https://mp.weixin.qq.com/s/brokenA,https://mp.weixin.qq.com/s/brokenB",
                                      "--out", str(self.out), "--media-dir", str(self.media_dir)])
        self.assertEqual(code, l1.EXIT_ERROR)
        records = [json.loads(line) for line in self.out.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([r["status"] for r in records], ["fail", "fail"])
        zero = [e for e in events if e["event"] == "l1.zero_yield"]
        self.assertEqual(len(zero), 1)
        self.assertEqual(
            (zero[0]["level"], zero[0]["total"], zero[0]["fail"]), ("error", 2, 2),
        )

    def test_all_partial_returns_partial(self) -> None:
        """反面锁定 zero_yield 的 `partial == 0` 半：正文抓到、仅图片降级仍是产出 -> 5。"""
        with mock.patch.object(l1, "_fetch_html", return_value=_load("article_text.html")), \
                mock.patch.object(l1, "_download_image",
                                  side_effect=OSError("模拟图片下载失败")):
            code, events = self._run(["url", "--urls",
                                      "https://mp.weixin.qq.com/s/AbCdEf123,https://mp.weixin.qq.com/s/AbCdEf124",
                                      "--out", str(self.out), "--media-dir", str(self.media_dir)])
        self.assertEqual(code, l1.EXIT_PARTIAL)
        records = [json.loads(line) for line in self.out.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([r["status"] for r in records], ["partial", "partial"])
        self.assertFalse([e for e in events if e["event"] == "l1.zero_yield"])

    def test_no_input_returns_param(self) -> None:
        with mock.patch("sys.stdin", io.StringIO("")), \
                mock.patch.object(l1, "_fetch_html", side_effect=AssertionError("不应抓取")):
            code, events = self._run(["url", "--out", str(self.out), "--media-dir", str(self.media_dir)])
        self.assertEqual(code, l1.EXIT_PARAM)
        self.assertEqual(events[-1]["event"], "l1.no_input")

    def test_env_missing_returns_env(self) -> None:
        with mock.patch.object(l1, "_fetch_html",
                               side_effect=l1._EnvMissingError("缺少依赖 playwright")):
            code, events = self._run(["url", "--urls", TEXT_URL,
                                      "--out", str(self.out), "--media-dir", str(self.media_dir)])
        self.assertEqual(code, l1.EXIT_ENV)
        self.assertTrue(any(e["event"] == "l1.env_missing" for e in events))


if __name__ == "__main__":
    unittest.main()
