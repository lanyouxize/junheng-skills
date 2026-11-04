#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""l2_fetch_account.py 单元测试（全离线，不访问网络）。

覆盖：
  - _load_cookies 三种形态与异常路径；
  - _normalize_item 嵌套（comm_msg_info/app_msg_ext_info/multi）与扁平双形态；
  - _match_filters since/until 含边界、datetime 缺失、keyword 大小写不敏感；
  - _page_plan 翻页终止（can_msg_continue=0 / 空页 / next_offset 回退）；
  - run() 全流程（假 requests/_fetch_page_retry/sleep_polite 注入）：
    退出码映射、JSONL 落盘、l2.done 统计、重试超阈即停。
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
import types
import unittest
import atexit
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import l2_fetch_account as l2  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
ARTICLE_URL = "https://mp.weixin.qq.com/s/AbCdEf123?scene=1&src=11"
EPOCH_2024 = 1704067200  # 2024-01-01T00:00:00Z
EPOCH_2001 = 1000000000  # 2001-09-09T01:46:40Z
EPOCH_2025 = 1735689600  # 2025-01-01T00:00:00Z


def _write_temp(content: str, suffix: str = ".txt") -> Path:
    handle = tempfile.NamedTemporaryFile("w", suffix=suffix, encoding="utf-8", delete=False)
    handle.write(content)
    handle.close()
    path = Path(handle.name)
    _TEMP_FILES.append(path)
    return path


_TEMP_FILES: list[Path] = []


@atexit.register
def _cleanup_temp_files() -> None:
    for path in _TEMP_FILES:
        path.unlink(missing_ok=True)


# ------------------------------------------------------------------ cookie 三形态
class TestLoadCookies(unittest.TestCase):
    def test_json_dict_form(self) -> None:
        path = _write_temp(json.dumps({"slave_user": "x", "data_ticket": "y"}), ".json")
        self.assertEqual(l2._load_cookies(str(path)), {"slave_user": "x", "data_ticket": "y"})

    def test_json_list_form(self) -> None:
        path = _write_temp(json.dumps(
            [{"name": "slave_user", "value": "x"}, {"name": "data_ticket", "value": "y"}]), ".json")
        self.assertEqual(l2._load_cookies(str(path)), {"slave_user": "x", "data_ticket": "y"})

    def test_json_list_skips_non_dict_entries(self) -> None:
        path = _write_temp(json.dumps(["junk", {"name": "a", "value": "1"}]), ".json")
        self.assertEqual(l2._load_cookies(str(path)), {"a": "1"})

    def test_cookie_header_string_form(self) -> None:
        path = _write_temp("slave_user=x; data_ticket=y")
        self.assertEqual(l2._load_cookies(str(path)), {"slave_user": "x", "data_ticket": "y"})

    def test_empty_file_raises(self) -> None:
        path = _write_temp("   \n  ")
        with self.assertRaises(ValueError):
            l2._load_cookies(str(path))

    def test_missing_file_raises_oserror(self) -> None:
        with self.assertRaises(OSError):
            l2._load_cookies("Z:/no/such/cookie.json")

    def test_json_scalar_form_raises(self) -> None:
        path = _write_temp("123", ".json")  # 合法 JSON 但既非 dict 也非 list
        with self.assertRaises(ValueError):
            l2._load_cookies(str(path))


# ------------------------------------------------------------------ 列表项归一化
class TestNormalizeItem(unittest.TestCase):
    def test_flat_form(self) -> None:
        item = {"title": "甲文章", "link": "https://mp.weixin.qq.com/s?__biz=B&mid=1&sn=a",
                "digest": "摘要", "cover": "", "datetime": EPOCH_2024}
        arts = l2._normalize_item(item)
        self.assertEqual(len(arts), 1)
        self.assertEqual(arts[0]["title"], "甲文章")
        self.assertEqual(arts[0]["datetime"], EPOCH_2024)

    def test_nested_multi_form_parent_first_then_children(self) -> None:
        item = {
            "comm_msg_info": {"datetime": EPOCH_2024, "type": 49},
            "app_msg_ext_info": {
                "title": "父篇", "content_url": "https://mp.weixin.qq.com/s?__biz=B&mid=1&idx=1&sn=a&amp;x=1",
                "digest": "d", "cover": "https://mmbiz.qpic.cn/x/640?wx_fmt=png",
                "author": "作者甲", "is_multi": 1,
                "multi_app_msg_item_list": [
                    {"title": "子篇2", "content_url": "https://mp.weixin.qq.com/s?__biz=B&mid=1&idx=2&sn=b",
                     "digest": "d2"},
                ],
            },
        }
        arts = l2._normalize_item(item)
        self.assertEqual([a["title"] for a in arts], ["父篇", "子篇2"])
        self.assertEqual(arts[0]["url"], "https://mp.weixin.qq.com/s?__biz=B&mid=1&idx=1&sn=a&x=1")  # &amp; 反转义
        self.assertEqual(arts[1]["cover"], "https://mmbiz.qpic.cn/x/640?wx_fmt=png")  # 子篇继承父封面
        self.assertEqual({a["datetime"] for a in arts}, {EPOCH_2024})  # 发布时间取 comm_msg_info
        self.assertEqual({a["author"] for a in arts}, {"作者甲"})

    def test_item_without_url_dropped(self) -> None:
        item = {"title": "无链接", "digest": "d", "datetime": EPOCH_2024}
        self.assertEqual(l2._normalize_item(item), [])

    def test_millisecond_epoch_normalized_to_seconds(self) -> None:
        item = {"title": "毫秒", "link": "https://mp.weixin.qq.com/s?__biz=B&mid=9&sn=z",
                "datetime": EPOCH_2024 * 1000}
        self.assertEqual(l2._normalize_item(item)[0]["datetime"], EPOCH_2024)

    def test_invalid_datetime_becomes_none(self) -> None:
        item = {"title": "坏时间", "link": "https://mp.weixin.qq.com/s?__biz=B&mid=8&sn=y",
                "datetime": "not-a-number"}
        self.assertIsNone(l2._normalize_item(item)[0]["datetime"])

    def test_epoch_iso_utc(self) -> None:
        self.assertEqual(l2._epoch_iso(EPOCH_2024), "2024-01-01T00:00:00Z")
        self.assertEqual(l2._epoch_iso(None), "")


# ------------------------------------------------------------------ 过滤
class TestMatchFilters(unittest.TestCase):
    def test_no_filters_keeps_everything(self) -> None:
        art = {"title": "t", "digest": "d", "datetime": EPOCH_2001}
        keep, why = l2._match_filters(art, None, None, "")
        self.assertTrue(keep)
        self.assertEqual(why, "")

    def test_since_boundary_inclusive(self) -> None:
        art = {"title": "t", "digest": "", "datetime": EPOCH_2024}
        keep, _ = l2._match_filters(art, date(2024, 1, 1), None, "")
        self.assertTrue(keep)

    def test_since_excludes_older(self) -> None:
        art = {"title": "t", "digest": "", "datetime": EPOCH_2001}
        keep, why = l2._match_filters(art, date(2024, 1, 1), None, "")
        self.assertFalse(keep)
        self.assertIn("早于 since", why)

    def test_until_boundary_inclusive(self) -> None:
        art = {"title": "t", "digest": "", "datetime": EPOCH_2024}
        keep, _ = l2._match_filters(art, None, date(2024, 1, 1), "")
        self.assertTrue(keep)

    def test_until_excludes_newer(self) -> None:
        art = {"title": "t", "digest": "", "datetime": EPOCH_2025}
        keep, why = l2._match_filters(art, None, date(2024, 12, 31), "")
        self.assertFalse(keep)
        self.assertIn("晚于 until", why)

    def test_missing_datetime_skipped_when_time_filter_set(self) -> None:
        art = {"title": "t", "digest": "", "datetime": None}
        keep, why = l2._match_filters(art, date(2024, 1, 1), None, "")
        self.assertFalse(keep)
        self.assertIn("发布时间缺失", why)

    def test_keyword_case_insensitive_on_title_and_digest(self) -> None:
        art_title = {"title": "Hello World", "digest": "", "datetime": EPOCH_2024}
        art_digest = {"title": "x", "digest": "包含 KEYWORD 的摘要", "datetime": EPOCH_2024}
        keep_t, _ = l2._match_filters(art_title, None, None, "hello")
        keep_d, _ = l2._match_filters(art_digest, None, None, "keyword")
        miss, why = l2._match_filters(art_title, None, None, "不存在")
        self.assertTrue(keep_t)
        self.assertTrue(keep_d)
        self.assertFalse(miss)
        self.assertIn("未命中 keyword", why)


# ------------------------------------------------------------------ 翻页终止
class TestPagePlan(unittest.TestCase):
    def test_can_msg_continue_zero_stops(self) -> None:
        payload = {"can_msg_continue": 0, "general_msg_list": "[]"}
        items, go, _ = l2._page_plan(payload, 0, 10)
        self.assertFalse(go)
        self.assertEqual(items, [])

    def test_can_msg_continue_one_continues(self) -> None:
        payload = {"can_msg_continue": 1, "general_msg_list": "[]"}
        _, go, _ = l2._page_plan(payload, 0, 10)
        self.assertTrue(go)

    def test_is_continue_fallback_and_default_stop(self) -> None:
        _, go, _ = l2._page_plan({"is_continue": 1, "general_msg_list": "[]"}, 0, 10)
        self.assertTrue(go)
        _, go2, _ = l2._page_plan({"general_msg_list": "[]"}, 0, 10)
        self.assertFalse(go2)

    def test_next_offset_used_when_int(self) -> None:
        payload = {"can_msg_continue": 1, "next_offset": 20, "general_msg_list": "[]"}
        _, _, nxt = l2._page_plan(payload, 0, 10)
        self.assertEqual(nxt, 20)

    def test_next_offset_falls_back_to_offset_plus_count(self) -> None:
        for bad in (None, "20", True):
            payload = {"can_msg_continue": 1, "next_offset": bad, "general_msg_list": "[]"}
            _, _, nxt = l2._page_plan(payload, 5, 10)
            self.assertEqual(nxt, 15)

    def test_general_msg_list_string_unwrapped(self) -> None:
        inner = [{"title": "t", "link": "https://mp.weixin.qq.com/s?__biz=B&mid=1&sn=a",
                  "datetime": EPOCH_2024}]
        payload = {"can_msg_continue": 1, "general_msg_list": json.dumps(inner)}
        items, _, _ = l2._page_plan(payload, 0, 10)
        self.assertEqual(len(items), 1)
        self.assertEqual(l2._normalize_item(items[0])[0]["title"], "t")

    def test_general_msg_list_direct_list_and_dict(self) -> None:
        one = [{"title": "t", "link": "https://mp.weixin.qq.com/s?__biz=B&mid=1&sn=a"}]
        self.assertEqual(len(l2._page_plan({"general_msg_list": one}, 0, 10)[0]), 1)
        self.assertEqual(len(l2._page_plan({"general_msg_list": {"list": one}}, 0, 10)[0]), 1)

    def test_unparseable_general_msg_list_raises(self) -> None:
        with self.assertRaises(ValueError):
            l2._page_plan({"can_msg_continue": 1, "general_msg_list": "not-json{"}, 0, 10)


# ------------------------------------------------------------------ run() 全流程（注入式）
class _FakeResponse:
    def __init__(self, *, text: str = "", content: bytes = b"", headers=None, payload=None):
        self.text = text
        self.content = content
        self.headers = headers or {}
        self._payload = payload
        self.encoding = None

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeSession:
    """按 URL 路由：文章页 -> fixture HTML；mmbiz 图片 -> 假字节（不联网）。"""

    def __init__(self, html: str, fail_substr: str = "", html_by_substr: dict | None = None):
        self._html = html
        self._fail_substr = fail_substr
        self._html_by_substr = html_by_substr or {}
        self.cookies: dict = {}
        self.headers: dict = {}

    def get(self, url, params=None, headers=None, timeout=None):
        if "mmbiz.qpic.cn" in url:
            if self._fail_substr and self._fail_substr in url:
                raise OSError(f"simulated image download failure: {url}")
            return _FakeResponse(content=b"\x89fake-image-bytes", headers={"Content-Type": "image/jpeg"})
        for marker, page_html in self._html_by_substr.items():
            if marker in url:
                return _FakeResponse(text=page_html)
        return _FakeResponse(text=self._html)


def _profile_ext_page(*articles, can_continue: int, next_offset: int) -> dict:
    items = [{"title": t, "link": u, "digest": d, "datetime": dt}
             for t, u, d, dt in articles]
    return {"ret": 0, "can_msg_continue": can_continue, "next_offset": next_offset,
            "general_msg_list": json.dumps(items)}


class _RunCaseMixin:
    """为 run() 注入假 requests / _fetch_page_retry / sleep_polite，全流程离线。"""

    def _install(self, pages, html: str, fail_substr: str = "", html_by_substr: dict | None = None):
        def _fake_lazy_import(name, hint):
            if name == "requests":
                return types.SimpleNamespace(
                    Session=lambda: _FakeSession(html, fail_substr, html_by_substr),
                    RequestException=Exception)
            return types.SimpleNamespace()  # tenacity/bs4 占位：预检即过，不实际使用

        page_iter = iter(pages)

        def _fake_fetch_page(session, biz, offset, count):
            return next(page_iter)

        patchers = [
            mock.patch.object(l2, "lazy_import", side_effect=_fake_lazy_import),
            mock.patch.object(l2, "_fetch_page_retry", side_effect=_fake_fetch_page),
            mock.patch.object(l2, "sleep_polite", return_value=0.0),
        ]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def _run_l2(self, argv, pages, html: str):
        self._install(pages, html)
        stderr = io.StringIO()
        stdout = io.StringIO()
        with redirect_stderr(stderr), redirect_stdout(stdout):
            code = l2.main(argv)
        events = [json.loads(line) for line in stderr.getvalue().splitlines() if line.strip()]
        return code, events

    def _argv(self, out: Path, media_dir: Path, cookie_file: Path, extra=()):
        return ["account", "--biz", "MzA4MjM0NTAxNg==", "--cookie-file", str(cookie_file),
                "--yes", "--out", str(out), "--media-dir", str(media_dir), *extra]


class TestRunHappyPath(_RunCaseMixin, unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.out = root / "r.jsonl"
        self.media_dir = root / "r.media"
        self.cookie_file = _write_temp(json.dumps({"slave_user": "x"}))
        self.pages = [
            _profile_ext_page(
                ("猫咪排毛攻略：膳食纤维的科学运用", ARTICLE_URL, "排毛", EPOCH_2024),
                ("无关文章", "https://mp.weixin.qq.com/s?__biz=B&mid=2&sn=b", "无关", EPOCH_2024),
                can_continue=1, next_offset=10),
            _profile_ext_page(
                ("第二篇排毛", "https://mp.weixin.qq.com/s?__biz=B&mid=3&sn=c", "排毛二", EPOCH_2025),
                can_continue=0, next_offset=20),
        ]

    def test_full_pipeline_offline(self) -> None:
        code, events = self._run_l2(
            self._argv(self.out, self.media_dir, self.cookie_file, ["--keyword", "排毛"]),
            self.pages, (FIXTURES / "article_text.html").read_text(encoding="utf-8"))
        self.assertEqual(code, l2.EXIT_OK)

        records = [json.loads(line) for line in self.out.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(records), 2)  # 无关文章被 keyword 过滤
        record = records[0]
        self.assertEqual(record["status"], "ok")
        self.assertEqual(record["collect_layer"], "account")
        self.assertEqual(record["extractor"], "l2:profile_ext")
        self.assertEqual(record["account_id"], "MzA4MjM0NTAxNg==")
        self.assertEqual(record["account"], "宠 ingredients 研究所")
        self.assertEqual(record["publish_time"], "2024-01-01T00:00:00Z")  # 列表 datetime 优先
        self.assertEqual(record["images_count"], 3)

        body_ref = Path(record["body_ref"])
        self.assertTrue(body_ref.is_file())
        self.assertIn("甜菜粕", body_ref.read_text(encoding="utf-8"))
        # 按篇清单（schema.md §7）：<media>/<record_id>.media.json，非 run 级共享文件
        media_json = Path(record["images_ref"])
        self.assertEqual(media_json.name, f"{record['record_id']}.media.json")
        self.assertEqual(media_json.parent, self.media_dir)
        manifest = json.loads(media_json.read_text(encoding="utf-8"))
        self.assertEqual(set(manifest), {"images", "videos"})
        self.assertEqual(len(manifest["images"]), 3)
        for image in manifest["images"]:
            self.assertIn("local_path", image)  # 全成功：每张都有本地副本
            self.assertTrue(Path(image["local_path"]).is_file())
        # 封面不入按篇清单的 images，只记在记录的 cover_url 上
        self.assertTrue(record["cover_url"].startswith("https://mmbiz.qpic.cn/"))

        done = [e for e in events if e["event"] == "l2.done"][-1]
        self.assertEqual((done["pages"], done["total"], done["ok"], done["fail"]), (2, 3, 2, 0))
        skip = [e for e in events if e["event"] == "l2.skip"]
        self.assertTrue(any("未命中 keyword" in e.get("reason", "") for e in skip))


class TestRunExitCodes(_RunCaseMixin, unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.out = root / "r.jsonl"
        self.media_dir = root / "r.media"
        self.cookie_file = _write_temp(json.dumps({"slave_user": "x"}))

    def test_empty_body_article_fail_yields_error(self) -> None:
        """零产出（total>0 且 ok==0 且 partial==0）-> EXIT_ERROR，不得冒充 partial。"""
        pages = [_profile_ext_page(
            ("坏文章", "https://mp.weixin.qq.com/s?__biz=B&mid=1&sn=a", "d", EPOCH_2024),
            can_continue=0, next_offset=10)]
        code, events = self._run_l2(self._argv(self.out, self.media_dir, self.cookie_file),
                                    pages, (FIXTURES / "article_broken.html").read_text(encoding="utf-8"))
        self.assertEqual(code, l2.EXIT_ERROR)
        records = [json.loads(line) for line in self.out.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([r["status"] for r in records], ["fail"])
        fail_events = [e for e in events if e["event"] == "l2.article_fail"]
        self.assertTrue(fail_events)
        self.assertIn("正文缺失", fail_events[0]["reasons"][0])
        zero = [e for e in events if e["event"] == "l2.zero_yield"]
        self.assertEqual(len(zero), 1)
        self.assertEqual(zero[0]["level"], "error")
        self.assertEqual((zero[0]["total"], zero[0]["fail"]), (1, 1))

    def test_mixed_ok_and_fail_still_partial(self) -> None:
        """反面锁：已有产出（1 ok + 1 fail）必须仍是 EXIT_PARTIAL，零产出规则不得误伤。"""
        pages = [_profile_ext_page(
            ("好文章", ARTICLE_URL, "d", EPOCH_2024),
            ("坏文章", "https://mp.weixin.qq.com/s?__biz=B&mid=2&sn=b", "d", EPOCH_2024),
            can_continue=0, next_offset=10)]
        self._install(pages, (FIXTURES / "article_text.html").read_text(encoding="utf-8"),
                      html_by_substr={"mid=2": (FIXTURES / "article_broken.html").read_text(encoding="utf-8")})
        stderr, stdout = io.StringIO(), io.StringIO()
        with redirect_stderr(stderr), redirect_stdout(stdout):
            code = l2.main(self._argv(self.out, self.media_dir, self.cookie_file))
        self.assertEqual(code, l2.EXIT_PARTIAL)
        records = [json.loads(line) for line in self.out.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(sorted(r["status"] for r in records), ["fail", "ok"])
        events = [json.loads(line) for line in stderr.getvalue().splitlines() if line.strip()]
        self.assertFalse(any(e["event"] == "l2.zero_yield" for e in events))

    def test_limit_stops_pagination_early(self) -> None:
        pages = [
            _profile_ext_page(
                ("篇1", "https://mp.weixin.qq.com/s?__biz=B&mid=1&sn=a", "d", EPOCH_2024),
                ("篇2", "https://mp.weixin.qq.com/s?__biz=B&mid=2&sn=b", "d", EPOCH_2024),
                can_continue=1, next_offset=10),
            _profile_ext_page(  # limit=2 时本页不应被请求
                ("篇3", "https://mp.weixin.qq.com/s?__biz=B&mid=3&sn=c", "d", EPOCH_2024),
                can_continue=0, next_offset=20),
        ]
        code, events = self._run_l2(
            self._argv(self.out, self.media_dir, self.cookie_file, ["--limit", "2", "--no-images"]),
            pages, (FIXTURES / "article_text.html").read_text(encoding="utf-8"))
        self.assertEqual(code, l2.EXIT_OK)
        records = [json.loads(line) for line in self.out.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(records), 2)
        done = [e for e in events if e["event"] == "l2.done"][-1]
        self.assertEqual(done["pages"], 1)  # 第二页未请求
        # 按篇清单回归：两篇文章的 images_ref 指向不同文件，互不覆盖
        self.assertEqual(len({r["images_ref"] for r in records}), 2)
        for record in records:  # --no-images：只记 URL 不下载
            self.assertEqual(record["images_count"], 3)
            self.assertTrue(record["images_ref"])
            manifest = json.loads(Path(record["images_ref"]).read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["images"]), 3)
            self.assertTrue(all("local_path" not in img for img in manifest["images"]))
            self.assertFalse((self.media_dir / "images").exists())

    def test_image_failure_degrades_to_partial(self) -> None:
        pages = [_profile_ext_page(
            ("图文篇", ARTICLE_URL, "d", EPOCH_2024), can_continue=0, next_offset=10)]
        self._install(pages, (FIXTURES / "article_text.html").read_text(encoding="utf-8"),
                      fail_substr="img002")
        stderr, stdout = io.StringIO(), io.StringIO()
        with redirect_stderr(stderr), redirect_stdout(stdout):
            code = l2.main(self._argv(self.out, self.media_dir, self.cookie_file))
        self.assertEqual(code, l2.EXIT_PARTIAL)
        records = [json.loads(line) for line in self.out.read_text(encoding="utf-8").splitlines()]
        record = records[0]
        self.assertEqual(record["status"], "partial")
        self.assertEqual(record["images_count"], 3)  # 失败的图也计数（与 L1 语义一致）
        manifest = json.loads(Path(record["images_ref"]).read_text(encoding="utf-8"))
        with_local = [img for img in manifest["images"] if "local_path" in img]
        without_local = [img for img in manifest["images"] if "local_path" not in img]
        self.assertEqual((len(with_local), len(without_local)), (2, 1))
        self.assertTrue(Path(with_local[0]["local_path"]).is_file())
        events = [json.loads(line) for line in stderr.getvalue().splitlines() if line.strip()]
        self.assertTrue(any(e["event"] == "l2.article_partial" for e in events))

    def test_retry_threshold_exceeded_stops_with_error(self) -> None:
        self._install([], "")
        with mock.patch.object(l2, "_fetch_page_retry",
                               side_effect=l2._PageRetryable("profile_ext ret=20009", ret=20009)):
            stderr = io.StringIO()
            with redirect_stderr(stderr), redirect_stdout(io.StringIO()):
                code = l2.main(self._argv(self.out, self.media_dir, self.cookie_file))
        self.assertEqual(code, l2.EXIT_ERROR)
        events = [json.loads(line) for line in stderr.getvalue().splitlines() if line.strip()]
        ret_events = [e for e in events if e["event"] == "l2.ret"]
        self.assertEqual(len(ret_events), 1)
        self.assertEqual(ret_events[0]["ret"], 20009)
        self.assertEqual(ret_events[0]["level"], "error")
        self.assertEqual(self.out.read_text(encoding="utf-8"), "")

    def test_missing_cookie_returns_param(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr), redirect_stdout(io.StringIO()):
            code = l2.main(["account", "--biz", "MzTest", "--yes",
                            "--out", str(self.out), "--media-dir", str(self.media_dir)])
        self.assertEqual(code, l2.EXIT_PARAM)
        events = [json.loads(line) for line in stderr.getvalue().splitlines() if line.strip()]
        self.assertEqual(events[-1]["event"], "l2.cookie")


if __name__ == "__main__":
    unittest.main()
