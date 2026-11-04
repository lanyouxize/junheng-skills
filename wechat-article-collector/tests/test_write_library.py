#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""write_to_library.py 单元测试：覆盖写（upsert）语义 + results 信封解析。

全部离线：_space_api 用 monkeypatch 替换，不触碰真实资料库。
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import write_to_library as wl  # noqa: E402


class TestUpdateProperties(unittest.TestCase):
    """_update_properties：新值覆盖 + 空值显式清空（真正的覆盖语义）。"""

    def test_empty_new_value_clears_old_value(self) -> None:
        # 真实缺陷：新记录 author 为空，库里旧值 '湖南' 必须被显式清空，
        # 而 to_property_values 会省略空串导致旧值残留。
        old = {"_id": "srv1", "author": "湖南", "digest": "脏"}
        new = {"title": "脂质代谢", "author": "", "digest": "干净摘要",
               "url": "https://mp.weixin.qq.com/s/x", "record_id": "r1"}
        props = wl._update_properties(new, old)
        self.assertEqual(props["author"], {"text": ""})
        self.assertEqual(props["digest"], {"text": "干净摘要"})

    def test_non_empty_new_value_overwrites(self) -> None:
        old = {"_id": "srv1", "author": "旧作者"}
        new = {"title": "T", "author": "新作者", "url": "https://x/y", "record_id": "r1"}
        props = wl._update_properties(new, old)
        self.assertEqual(props["author"], {"text": "新作者"})

    def test_field_absent_in_both_is_not_sent(self) -> None:
        # 两边都无值的字段不该出现在 payload 里（避免无意义的清空写）
        old = {"_id": "srv1"}
        new = {"title": "T", "url": "https://x/y", "record_id": "r1"}
        props = wl._update_properties(new, old)
        self.assertNotIn("account", props)
        self.assertNotIn("author", props)

    def test_old_only_field_gets_cleared(self) -> None:
        # 旧行有值、新记录没这个字段 ⇒ 也应清空（覆盖而非合并）
        old = {"_id": "srv1", "account": "旧公众号"}
        new = {"title": "T", "url": "https://x/y", "record_id": "r1"}
        props = wl._update_properties(new, old)
        self.assertEqual(props["account"], {"text": ""})


class TestUpdateFieldsPartial(unittest.TestCase):
    """--update-fields：只碰指定列，其余列既不覆盖也不清空。"""

    def test_only_listed_fields_are_sent(self) -> None:
        old = {"_id": "s", "author": "湖南", "digest": "脏", "account": "旧号"}
        new = {"title": "T", "url": "https://x/y", "record_id": "r1",
               "author": "", "digest": "净", "account": "新号"}
        props = wl._update_properties(new, old, ("author", "digest"))
        # 白名单内：author 清空、digest 覆盖
        self.assertEqual(props["author"], {"text": ""})
        self.assertEqual(props["digest"], {"text": "净"})
        # 白名单外：account 完全不出现（连新值都不写）
        self.assertNotIn("account", props)

    def test_unlisted_field_not_cleared(self) -> None:
        old = {"_id": "s", "account": "旧号"}
        new = {"title": "T", "url": "https://x/y", "record_id": "r1"}
        props = wl._update_properties(new, old, ("author",))
        self.assertNotIn("account", props)

    def test_empty_tuple_means_full_overwrite(self) -> None:
        # 不传 fields 时保持全覆盖语义（向后兼容）
        old = {"_id": "s", "account": "旧号"}
        new = {"title": "T", "url": "https://x/y", "record_id": "r1"}
        self.assertEqual(wl._update_properties(new, old), wl._update_properties(new, old, ()))


class TestMediaFiles(unittest.TestCase):
    """_media_files：正文 + 图片清单展开（自包含归档的前提）。"""

    def setUp(self) -> None:
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "body.html").write_text("<p>正文</p>", encoding="utf-8")
        (self.root / "0000.png").write_bytes(b"\x89PNG")
        (self.root / "0001.png").write_bytes(b"\x89PNG")
        (self.root / "manifest.json").write_text(json.dumps({
            "images": [
                {"url": "https://x/0.png", "local_path": str(self.root / "0000.png")},
                {"url": "https://x/1.png", "local_path": str(self.root / "0001.png")},
            ],
            "videos": [],
        }, ensure_ascii=False), encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_body_and_images_expanded(self) -> None:
        record = {"body_ref": str(self.root / "body.html"),
                  "images_ref": str(self.root / "manifest.json")}
        files = wl._media_files(record)
        kinds = [kind for kind, _ in files]
        self.assertEqual(kinds, ["body", "image", "image"])
        self.assertTrue(all(path.is_file() for _kind, path in files))

    def test_missing_manifest_is_skipped(self) -> None:
        # 清单文件不存在/损坏时不能炸，退化成只传正文
        record = {"body_ref": str(self.root / "body.html"),
                  "images_ref": str(self.root / "nope.json")}
        self.assertEqual([k for k, _ in wl._media_files(record)], ["body"])

    def test_no_images_means_body_only(self) -> None:
        record = {"body_ref": str(self.root / "body.html")}
        self.assertEqual([k for k, _ in wl._media_files(record)], ["body"])


class TestUploadOneModes(unittest.TestCase):
    """_upload_one：凭证有 drive / cos 两套模式，两种键都要转发（实测踩过的坑）。"""

    def setUp(self) -> None:
        import tempfile
        from unittest import mock
        self.tmp = tempfile.TemporaryDirectory()
        self.local = Path(self.tmp.name) / "body.html"
        self.local.write_text("<p>x</p>", encoding="utf-8")
        self.calls: list[dict] = []
        self.orig = wl._space_api

        def fake(config, api_name, payload):
            self.calls.append({"api": api_name, "payload": payload})
            if api_name == "space.importer.get-upload-credential":
                return dict(self.cred)
            return {"nodeBlockId": "nb1", "url": "https://x/nb1"}

        wl._space_api = fake
        # PUT 上传走 urllib，测试里屏蔽掉真实网络
        self.urlopen = mock.patch("urllib.request.urlopen").start()

    def tearDown(self) -> None:
        from unittest import mock
        mock.patch.stopall()
        wl._space_api = self.orig
        self.tmp.cleanup()

    def test_cos_mode_forwards_cos_key(self) -> None:
        # uploadType=cos：只有 cosKey，没有 confirmKey。不转发 cosKey 会让
        # import-local-file 报「cos_key、confirm_key 与文件字节不能同时为空」
        self.cred = {"uploadUrl": "https://cos/x", "cosKey": "temp/abc_body.html",
                     "taskId": "t1", "uploadType": "cos"}
        wl._upload_one({}, self.local, "")
        sent = [c for c in self.calls if c["api"] == "space.importer.import-local-file"]
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["payload"].get("cosKey"), "temp/abc_body.html")
        self.assertEqual(sent[0]["payload"].get("taskId"), "t1")
        self.assertNotIn("confirmKey", sent[0]["payload"])

    def test_drive_mode_forwards_confirm_key(self) -> None:
        self.cred = {"uploadUrl": "https://drive/x", "confirmKey": "ck-123",
                     "taskId": "t2", "uploadType": "drive", "headers": {"a": "b"}}
        wl._upload_one({}, self.local, "")
        sent = [c for c in self.calls if c["api"] == "space.importer.import-local-file"]
        self.assertEqual(sent[0]["payload"].get("confirmKey"), "ck-123")
        self.assertNotIn("cosKey", sent[0]["payload"])


class TestImportMediaResume(unittest.TestCase):
    """_import_media 幂等：映射里已有的文件不重复上传。"""

    def setUp(self) -> None:
        import tempfile
        from unittest import mock
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.body = self.root / "body.html"
        self.body.write_text("<p>x</p>", encoding="utf-8")
        self.in_path = self.root / "in.jsonl"
        self.in_path.write_text("", encoding="utf-8")
        self.uploaded: list[str] = []
        self.orig = wl._upload_one
        wl._upload_one = lambda config, local, parent: (
            self.uploaded.append(str(local)) or {"nodeBlockId": "n1", "url": "https://x/n1"})
        self._mock = mock  # 保持引用以便 tearDown 恢复

    def tearDown(self) -> None:
        wl._upload_one = self.orig
        self.tmp.cleanup()

    def test_existing_entry_not_reuploaded(self) -> None:
        record = {"record_id": "r1", "body_ref": str(self.body)}
        map_path = self.root / "media-archive-testdb.json"
        # 旧条目没有 sha256 字段，兼容路径应退回按 local_path 判定
        Path(map_path).write_text(json.dumps([{
            "record_id": "r1", "kind": "body", "local_path": str(self.body),
            "node_block_id": "old", "url": "https://x/old",
        }]), encoding="utf-8")
        ok, fail, out = wl._import_media({}, "", [record], map_path)
        self.assertEqual(self.uploaded, [])          # 已传过，不再上传
        self.assertEqual((ok, fail), (0, 0))
        self.assertEqual(len(json.loads(Path(out).read_text(encoding="utf-8"))), 1)

    def test_new_file_uploaded_and_appended(self) -> None:
        record = {"record_id": "r1", "body_ref": str(self.body)}
        ok, fail, out = wl._import_media({}, "", [record], self.root / "media-archive-testdb.json")
        self.assertEqual(self.uploaded, [str(self.body)])
        self.assertEqual((ok, fail), (1, 0))
        saved = json.loads(Path(out).read_text(encoding="utf-8"))
        self.assertEqual(saved[0]["node_block_id"], "n1")
        self.assertTrue(saved[0].get("sha256"), "新条目必须带 sha256，供跨批次去重")

    def test_shared_index_dedups_across_input_files(self) -> None:
        """同一索引文件下，换一个 --in 也不该重复上传（按内容判定）。"""
        shared = self.root / "media-archive-db1.json"
        record = {"record_id": "r1", "body_ref": str(self.body)}
        first_ok, _, _ = wl._import_media({}, "", [record], shared)
        self.assertEqual(first_ok, 1)
        self.uploaded.clear()
        second_ok, _, _ = wl._import_media({}, "", [record], shared)
        self.assertEqual(second_ok, 0)
        self.assertEqual(self.uploaded, [])


class TestBackfillBodyUrl(unittest.TestCase):
    """_backfill_body_url：把上传后的正文 URL 写回 body_url（body_ref 不动）。"""

    def setUp(self) -> None:
        self.orig_index = wl._fetch_existing_index
        self.orig_batch = wl._batch_update_records
        self.calls: list[list] = []

    def tearDown(self) -> None:
        wl._fetch_existing_index = self.orig_index
        wl._batch_update_records = self.orig_batch

    def _run(self, index: dict, entries: list, records: list):
        wl._fetch_existing_index = lambda config, db, full=False: index

        def fake_batch(config, db, pairs, batch_size):
            self.calls.append(pairs)
            return len(pairs), 0

        wl._batch_update_records = fake_batch
        return wl._backfill_body_url({}, "db", records, entries, 50)

    def test_backfills_matching_record(self) -> None:
        record = {"record_id": "r1", "url": "https://mp.weixin.qq.com/s/abc"}
        index = {wl._url_key(record): {"_id": "srv1"}}
        entries = [{"record_id": "r1", "kind": "body",
                    "url": "https://www.workbuddy.cn/space/d/nb1"}]
        ok, fail = self._run(index, entries, [record])
        self.assertEqual((ok, fail), (1, 0))
        self.assertEqual(self.calls[0][0][0], "srv1")
        self.assertEqual(self.calls[0][0][1], {"body_url": {"text": "https://www.workbuddy.cn/space/d/nb1"}})

    def test_only_body_entries_used(self) -> None:
        # image 条目没有单独列，不能被当成正文 URL
        record = {"record_id": "r1", "url": "https://mp.weixin.qq.com/s/abc"}
        index = {wl._url_key(record): {"_id": "srv1"}}
        entries = [{"record_id": "r1", "kind": "image", "url": "https://x/img"}]
        ok, fail = self._run(index, entries, [record])
        self.assertEqual((ok, fail), (0, 0))
        self.assertEqual(self.calls, [])

    def test_missing_server_id_skipped(self) -> None:
        record = {"record_id": "r1", "url": "https://mp.weixin.qq.com/s/abc"}
        entries = [{"record_id": "r1", "kind": "body", "url": "https://x/nb1"}]
        ok, fail = self._run({}, entries, [record])   # 索引里查不到该 url
        self.assertEqual((ok, fail), (0, 0))
        self.assertEqual(self.calls, [])


class TestParseUpdateFields(unittest.TestCase):
    def test_parses_and_dedups(self) -> None:
        fields, err = wl._parse_update_fields("author, digest,author",
                                              {"author", "digest", "title"})
        self.assertEqual(err, "")
        self.assertEqual(fields, ["author", "digest"])

    def test_unknown_column_rejected(self) -> None:
        fields, err = wl._parse_update_fields("author,nope", {"author", "digest"})
        self.assertEqual(fields, [])
        self.assertIn("nope", err)

    def test_empty_is_not_an_error(self) -> None:
        # 空串表示「未启用」，不算错
        fields, err = wl._parse_update_fields("", {"author"})
        self.assertEqual((fields, err), ([], ""))

    def test_all_invalid_yields_error(self) -> None:
        fields, err = wl._parse_update_fields(" , ", {"author"})
        self.assertEqual(fields, [])
        self.assertTrue(err)


class TestBatchUpdateRecords(unittest.TestCase):
    """_batch_update_records：逐条解析 results 信封，不只看有没有抛异常。"""

    def setUp(self) -> None:
        self.original = wl._space_api
        self.calls: list[dict] = []

    def tearDown(self) -> None:
        wl._space_api = self.original

    def _fake(self, data):
        def _stub(config, api_name, payload):
            self.calls.append({"api": api_name, "payload": payload})
            return data
        return _stub

    def test_success_envelope(self) -> None:
        wl._space_api = self._fake({"results": [{"index": 0, "id": "srv1", "success": True}]})
        updated, failed = wl._batch_update_records({}, "db1", [("srv1", {"author": {"text": ""}})], 50)
        self.assertEqual((updated, failed), (1, 0))
        self.assertEqual(self.calls[0]["api"], "space.database.batch-update-records")
        self.assertEqual(self.calls[0]["payload"]["records"][0]["recordId"], "srv1")
        self.assertEqual(self.calls[0]["payload"]["records"][0]["properties"],
                         {"author": {"text": ""}})

    def test_per_item_failure_is_attributed(self) -> None:
        # 单条 schema 问题时整批仍 200，必须逐条解析 success
        wl._space_api = self._fake(
            {"results": [{"index": 0, "success": False, "error": "properties is empty"}]})
        updated, failed = wl._batch_update_records({}, "db1", [("srv1", {"author": {"text": ""}})], 50)
        self.assertEqual((updated, failed), (0, 1))

    def test_missing_results_counts_as_failure(self) -> None:
        wl._space_api = self._fake({})
        updated, failed = wl._batch_update_records({}, "db1", [("srv1", {"author": {"text": ""}})], 50)
        self.assertEqual((updated, failed), (0, 1))

    def test_hard_error_counts_whole_chunk(self) -> None:
        def _raise(config, api_name, payload):
            raise RuntimeError("code=50000 failedIDs:[1]")
        wl._space_api = _raise
        updated, failed = wl._batch_update_records(
            {}, "db1", [("srv1", {"a": {"text": "1"}}), ("srv2", {"a": {"text": "2"}})], 50)
        self.assertEqual((updated, failed), (0, 2))

    def test_mixed_results(self) -> None:
        wl._space_api = self._fake({"results": [
            {"index": 0, "success": True, "id": "srv1"},
            {"index": 1, "success": False, "error": "boom"},
        ]})
        updated, failed = wl._batch_update_records(
            {}, "db1", [("srv1", {"a": {"text": "1"}}), ("srv2", {"a": {"text": "2"}})], 50)
        self.assertEqual((updated, failed), (1, 1))


class TestUpdateExistingFlag(unittest.TestCase):
    def test_flag_registered(self) -> None:
        import argparse
        parser = argparse.ArgumentParser()
        subs = parser.add_subparsers()
        wl.register(subs)
        args = parser.parse_args(["write", "--in", "x.jsonl", "--update-existing"])
        self.assertTrue(args.update_existing)

    def test_flag_defaults_off(self) -> None:
        import argparse
        parser = argparse.ArgumentParser()
        subs = parser.add_subparsers()
        wl.register(subs)
        args = parser.parse_args(["write", "--in", "x.jsonl"])
        self.assertFalse(args.update_existing)

    def test_update_fields_flag_parsed(self) -> None:
        import argparse
        parser = argparse.ArgumentParser()
        subs = parser.add_subparsers()
        wl.register(subs)
        args = parser.parse_args(["write", "--in", "x.jsonl", "--update-fields", "author,digest"])
        self.assertEqual(args.update_fields, "author,digest")


if __name__ == "__main__":
    unittest.main()
