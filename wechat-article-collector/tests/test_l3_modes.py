#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""l3_drive_wechat.py 模式编排单元测试（离线，不启动 mitmdump / 不动注册表）。

覆盖 2026-10-22 真机事故后的三处加固：
  ① local 模式"进程活着但 redirector 已死"的假成功判据；
  ② auto 模式 local 失败 -> 自动降级 regular；
  ③ 系统代理备份/还原的"宁可不改"边界（空备份、非 Windows）。
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import l3_drive_wechat as l3  # noqa: E402


class TestMitmModeArgs(unittest.TestCase):
    """--mode 参数拼装：local 走透明劫持、regular 走监听端口。"""

    def test_local_uses_windivert_target(self):
        self.assertEqual(
            l3._mitm_mode_args("local", 18081),
            ["--mode", "local:WeChatAppEx.exe"],
        )

    def test_local_ignores_port(self):
        """local 模式不监听端口：换端口不应改变参数（旧版误把端口当判据）。"""
        self.assertEqual(l3._mitm_mode_args("local", 1), l3._mitm_mode_args("local", 65000))

    def test_regular_listens_on_port(self):
        self.assertEqual(
            l3._mitm_mode_args("regular", 18081),
            ["--mode", "regular", "--listen-port", "18081"],
        )

    def test_unknown_mode_falls_back_to_local(self):
        """未收录的模式名不该抛异常（防御性：配置里写错也不炸）。"""
        self.assertEqual(l3._mitm_mode_args("", 18081), ["--mode", "local:WeChatAppEx.exe"])


class TestRedirectorFailed(unittest.TestCase):
    """日志特征判定：真机原文必须命中，正常启动行必须不命中。"""

    REAL_FAILURE = (
        "[20:26:56.464] Loading script addons/wechat_article_addon.py\n"
        "[20:26:56.526] Local redirector started.\n"
        "[20:26:56.571] Task failed: failed to propagate interception config update\n"
    )

    def test_real_failure_log_hits(self):
        self.assertTrue(l3._redirector_failed(self.REAL_FAILURE))

    def test_healthy_startup_does_not_hit(self):
        healthy = (
            "[20:23:20.611] Loading script addons/wechat_article_addon.py\n"
            "[20:23:20.716] Local redirector started.\n"
        )
        self.assertEqual(l3._redirector_failed(healthy), "")

    def test_empty_log_does_not_hit(self):
        self.assertEqual(l3._redirector_failed(""), "")

    def test_regular_mode_banner_does_not_hit(self):
        """regular 模式正常启动（监听端口）不能被误判为 redirector 失败。"""
        regular = (
            "[20:26:59.308] Loading script addons/wechat_article_addon.py\n"
            "[20:26:59.311] HTTP(S) proxy listening at *:18081.\n"
        )
        self.assertEqual(l3._redirector_failed(regular), "")


class TestReadLog(unittest.TestCase):
    """日志读取：缺失文件返回空串（不抛）。"""

    def test_missing_file_returns_empty(self):
        self.assertEqual(l3._read_log(Path(tempfile.gettempdir()) / "no-such-mitm.log"), "")

    def test_tail_is_truncated(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "log.txt"
            path.write_text("A" * 100 + "TAIL", encoding="utf-8")
            tail = l3._read_log(path, limit=4)
            self.assertEqual(tail, "TAIL")


class TestSystemProxyRestore(unittest.TestCase):
    """系统代理还原：空/缺失备份必须不动注册表（防止把用户的代理清空）。"""

    def test_empty_backup_is_noop(self):
        self.assertFalse(l3._system_proxy_restore({}))

    def test_none_backup_is_noop(self):
        self.assertFalse(l3._system_proxy_restore(None))

    def test_backup_roundtrip_with_mocked_registry(self):
        """有备份时应写回全部三个键（值取自备份）。"""
        written: dict = {}

        class _FakeKey:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def fake_set(key, name, reserved, kind, value):
            written[name] = value

        with mock.patch.object(l3, "_wininet_notify"), \
             mock.patch("winreg.OpenKey", return_value=_FakeKey()), \
             mock.patch("winreg.SetValueEx", side_effect=fake_set), \
             mock.patch.object(l3.sys, "platform", "win32"):
            ok = l3._system_proxy_restore(
                {"ProxyEnable": 0, "ProxyServer": "127.0.0.1:7890", "ProxyOverride": "<local>"}
            )

        self.assertTrue(ok)
        self.assertEqual(written["ProxyEnable"], 0)
        self.assertEqual(written["ProxyServer"], "127.0.0.1:7890")
        self.assertEqual(written["ProxyOverride"], "<local>")


class TestBringUpMitm(unittest.TestCase):
    """启动编排：auto 降级、local 独用不成、regular 接管系统代理。"""

    class _Args:
        def __init__(self, mode, system_proxy=None):
            self.mitm_mode = mode
            self.system_proxy = system_proxy

    def test_auto_falls_back_to_regular(self):
        calls: list[str] = []

        def fake_start(cmd, port, capture_dir, mode="local"):
            calls.append(mode)
            return None if mode == "local" else object()

        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(l3, "_start_mitmdump", side_effect=fake_start), \
             mock.patch.object(l3, "_system_proxy_apply", return_value={"ProxyEnable": 0}), \
             mock.patch.object(l3, "emit_event"):
            proc, mode, backup = l3._bring_up_mitm(self._Args("auto"), ["mitmdump"], 18081, Path(tmp))

        self.assertIsNotNone(proc)
        self.assertEqual(mode, "regular")
        self.assertEqual(calls, ["local", "regular"])
        self.assertEqual(backup, {"ProxyEnable": 0})

    def test_local_only_failure_returns_none(self):
        """显式 --mitm-mode local 时不得偷偷降级（用户要的就是 local）。"""
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(l3, "_start_mitmdump", return_value=None), \
             mock.patch.object(l3, "emit_event"):
            proc, mode, backup = l3._bring_up_mitm(self._Args("local"), ["mitmdump"], 18081, Path(tmp))

        self.assertIsNone(proc)
        self.assertEqual(mode, "local")
        self.assertEqual(backup, {})

    def test_local_success_skips_proxy(self):
        """local 成功时不得改系统代理（透明劫持不需要）。"""
        proxy_apply = mock.Mock(return_value={})
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(l3, "_start_mitmdump", return_value=object()), \
             mock.patch.object(l3, "_system_proxy_apply", proxy_apply), \
             mock.patch.object(l3, "emit_event"):
            proc, mode, _ = l3._bring_up_mitm(self._Args("auto"), ["mitmdump"], 18081, Path(tmp))

        self.assertIsNotNone(proc)
        self.assertEqual(mode, "local")
        proxy_apply.assert_not_called()

    def test_regular_no_system_proxy_respected(self):
        """--no-system-proxy：常规代理照起，但不碰系统代理。"""
        proxy_apply = mock.Mock(return_value={})
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(l3, "_start_mitmdump", return_value=object()), \
             mock.patch.object(l3, "_system_proxy_apply", proxy_apply), \
             mock.patch.object(l3, "emit_event"):
            proc, mode, backup = l3._bring_up_mitm(
                self._Args("regular", system_proxy=False), ["mitmdump"], 18081, Path(tmp))

        self.assertIsNotNone(proc)
        self.assertEqual(mode, "regular")
        self.assertEqual(backup, {})
        proxy_apply.assert_not_called()

    def test_proxy_apply_failure_stops_mitm(self):
        """接管系统代理失败 => 收掉 mitmdump 并报错（不留"抓不到包还冒充成功"的状态）。"""
        stopped = mock.Mock()
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(l3, "_start_mitmdump", return_value=object()), \
             mock.patch.object(l3, "_system_proxy_apply", side_effect=OSError("denied")), \
             mock.patch.object(l3, "_stop_mitmdump", stopped), \
             mock.patch.object(l3, "emit_event"):
            proc, mode, _ = l3._bring_up_mitm(self._Args("regular"), ["mitmdump"], 18081, Path(tmp))

        self.assertIsNone(proc)
        stopped.assert_called_once()


class TestWechatWindowSelection(unittest.TestCase):
    """主窗口选择：真机有 2 个 title='微信' 的顶层窗口（Qt 主窗口 + Chromium 容器）。

    旧实现按 title_re='微信' + found_index=0 抓，可能抓到 Chromium 容器 ->
    后续点不到任何控件。这里锁定"按 class 可信度排序"的契约。
    """

    class _FakeWindow:
        def __init__(self, title, class_name, pid=100, handle=1):
            self._title = title
            self._class = class_name
            self._pid = pid
            self.handle = handle

        def window_text(self):
            return self._title

        def class_name(self):
            return self._class

        def process_id(self):
            return self._pid

    class _FakeDesktop:
        def __init__(self, windows):
            self._windows = windows

        def windows(self):
            return self._windows

    def _fake_pywinauto(self, windows):
        desktop = self._FakeDesktop(windows)

        class _Module:
            @staticmethod
            def Desktop(backend="uia"):
                return desktop

        return _Module

    def _find(self, windows):
        with mock.patch.object(l3, "lazy_import", return_value=self._fake_pywinauto(windows)):
            return l3._find_wechat_windows()

    def test_qt_main_window_ranks_above_chromium_container(self):
        found = self._find([
            self._FakeWindow("微信", "Chrome_WidgetWin_0", pid=20904, handle=655394),
            self._FakeWindow("微信", "Qt51514QWindowIcon", pid=21868, handle=131316),
        ])
        self.assertEqual(found[0]["class_name"], "Qt51514QWindowIcon")
        self.assertEqual(found[0]["pid"], 21868)

    def test_wechat3_class_wins_over_chromium(self):
        found = self._find([
            self._FakeWindow("微信", "Chrome_WidgetWin_1"),
            self._FakeWindow("微信", "WeChatMainWndForPC"),
        ])
        self.assertEqual(found[0]["class_name"], "WeChatMainWndForPC")

    def test_non_wechat_windows_excluded(self):
        found = self._find([
            self._FakeWindow("腾讯会议", "Chrome_WidgetWin_1"),
            self._FakeWindow("微信公众平台 - Chrome", "Chrome_WidgetWin_1"),
        ])
        self.assertEqual(found, [])

    def test_empty_title_skipped(self):
        found = self._find([self._FakeWindow("", "Qt51514QWindowIcon")])
        self.assertEqual(found, [])


class TestCollectImages(unittest.TestCase):
    """图片下载契约：单图失败不致命但降级 partial；--no-images 只记 URL。"""

    CONFIG = {"rate_limit": {"min_delay_seconds": 0, "max_delay_seconds": 0}}
    IMAGES = [
        {"url": "https://mmbiz.qpic.cn/mmbiz_png/AAA/640?wx_fmt=png"},
        {"url": "https://mmbiz.qpic.cn/mmbiz_jpg/BBB/640?wx_fmt=jpeg"},
    ]

    class _FakeResponse:
        content = b"\x89PNG\r\n\x1a\n" + b"0" * 32

        def raise_for_status(self):
            return None

    class _FakeSession:
        def __init__(self, fail_on=None):
            self.calls: list[str] = []
            self.fail_on = fail_on

        def get(self, url, headers=None, timeout=None):
            self.calls.append(url)
            if self.fail_on and self.fail_on in url:
                raise RuntimeError("boom")
            return TestCollectImages._FakeResponse()

    def test_downloads_all_and_sets_local_path(self):
        session = self._FakeSession()
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(l3, "lazy_import", return_value=session):
            out, failures = l3._collect_images(
                self.IMAGES, Path(tmp), "rid", {"download_images": True, "config": self.CONFIG})

        self.assertEqual(failures, [])
        self.assertEqual(len(out), 2)
        self.assertTrue(all("local_path" in item for item in out))
        self.assertTrue(out[0]["local_path"].endswith("0000.png"))
        self.assertTrue(out[1]["local_path"].endswith("0001.jpg"))  # wx_fmt=jpeg -> jpg

    def test_single_failure_keeps_url_without_local_path(self):
        session = self._FakeSession(fail_on="BBB")
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(l3, "lazy_import", return_value=session):
            out, failures = l3._collect_images(
                self.IMAGES, Path(tmp), "rid", {"download_images": True, "config": self.CONFIG})

        self.assertEqual(len(out), 2)
        self.assertIn("local_path", out[0])
        self.assertNotIn("local_path", out[1])
        self.assertEqual(len(failures), 1)
        self.assertIn("图片下载失败[1]", failures[0])

    def test_no_images_records_urls_only(self):
        session = self._FakeSession()
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(l3, "lazy_import", return_value=session):
            out, failures = l3._collect_images(
                self.IMAGES, Path(tmp), "rid", {"download_images": False, "config": self.CONFIG})

        self.assertEqual(failures, [])
        self.assertEqual(out, [{"url": item["url"]} for item in self.IMAGES])
        self.assertEqual(session.calls, [])

    def test_empty_url_skipped(self):
        session = self._FakeSession()
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(l3, "lazy_import", return_value=session):
            out, failures = l3._collect_images(
                [{"url": ""}, {"url": "https://x/1?wx_fmt=png"}],
                Path(tmp), "rid", {"download_images": True, "config": self.CONFIG})

        self.assertEqual(len(out), 1)
        self.assertEqual(failures, [])

    def test_missing_requests_degrades_to_urls(self):
        """requests 缺失：不抛异常，改为只记 URL 并给出失败原因（不静默）。"""
        def boom(name, hint=""):
            raise ImportError("no requests")

        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(l3, "lazy_import", side_effect=boom):
            out, failures = l3._collect_images(
                self.IMAGES, Path(tmp), "rid", {"download_images": True, "config": self.CONFIG})

        self.assertEqual(len(out), 2)
        self.assertTrue(all("local_path" not in item for item in out))
        self.assertEqual(len(failures), 1)
        self.assertIn("requests", failures[0])


class TestUiControlsAvailable(unittest.TestCase):
    """能力探测：自绘 Qt 窗口（只有不透明 Pane）应直接判"不可自动化"，不做无效盲试。"""

    class _Win:
        def __init__(self, control_types=(), raise_on=None):
            self._types = set(control_types)
            self._raise_on = raise_on

        def descendants(self, control_type=None):
            if self._raise_on and control_type == self._raise_on:
                raise RuntimeError("uia error")
            return [object()] if control_type in self._types else []

    def test_edit_present_is_available(self):
        self.assertTrue(l3._ui_controls_available(self._Win({"Edit"})))

    def test_button_present_is_available(self):
        self.assertTrue(l3._ui_controls_available(self._Win({"Button"})))

    def test_opaque_panes_only_is_unavailable(self):
        """真机微信 4.x：一级只有 Pane，无 Edit/Button。"""
        self.assertFalse(l3._ui_controls_available(self._Win()))

    def test_exception_treated_as_unavailable(self):
        self.assertFalse(l3._ui_controls_available(self._Win(raise_on="Edit")))


class TestStaleProxyBackupRecovery(unittest.TestCase):
    """上次被强杀留下的代理备份：下次启动先还原，避免整机代理指向死端口。"""

    def test_no_backup_returns_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(l3._recover_stale_proxy_backup(Path(tmp)))

    def test_corrupt_backup_is_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / l3._PROXY_BACKUP_NAME
            path.write_text("{not json", encoding="utf-8")
            self.assertFalse(l3._recover_stale_proxy_backup(Path(tmp)))
            self.assertFalse(path.exists())

    def test_valid_backup_is_restored_and_removed(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(l3, "_system_proxy_restore", return_value=True) as restore:
            path = Path(tmp) / l3._PROXY_BACKUP_NAME
            path.write_text('{"ProxyEnable": 0, "ProxyServer": "127.0.0.1:7890"}', encoding="utf-8")
            self.assertTrue(l3._recover_stale_proxy_backup(Path(tmp)))
            restore.assert_called_once()
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
