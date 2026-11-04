#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pipeline.py 的阶段级测试：只验证「参数怎么传」，不执行任何写操作。

存在理由（2026-10-23 真机缺口）：pipeline 把 scout → download 串成一条链，但
scout 早期固定用默认 `--return-key ctrlw` —— 点开文章后立刻 Ctrl+W 关掉 tab，
而下载工具的「1.获取公众号id」要求微信里**正开着**该号文章（profile 的
wait_log 里就有一条「请先在左面打开微信内置浏览器」）。链条看起来能跑，实际
下载阶段永远 0 产出。这类"跨阶段约定"只能靠断言命令行来守，跑真机太贵。
"""
from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ["UIAC_NO_DPI_AWARE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import pipeline as pl  # noqa: E402


def _ctx(**kw):
    base = {"base": Path("C:/tmp/base"), "root": Path("C:/tmp/base/某号"),
            "vein": Path("C:/tmp/vein"), "exe": Path("C:/tmp/tool.exe"),
            "account": "某号", "scout_rounds": 1, "scout_dry": False,
            "return_key": "none"}
    base.update(kw)
    return base


class TestScoutHandoff(unittest.TestCase):
    def _cmd_of(self, ctx):
        done = SimpleNamespace(stdout='{"clicked": 1, "skipped": 0}',
                               stderr='{"clicked": 1, "skipped": 0}', returncode=0)
        with mock.patch.object(pl, "run", return_value=done) as m:
            detail = pl.stage_scout(ctx)
        self.assertIn("点击 1 篇", detail)
        return [str(c) for c in m.call_args[0][0]]

    def test_scout_keeps_article_open_by_default(self):
        """默认必须 --return-key none：文章页要留给 download 阶段。"""
        cmd = self._cmd_of(_ctx())
        self.assertEqual(cmd[cmd.index("--return-key") + 1], "none")
        self.assertIn("--download-root", cmd)
        self.assertNotIn("--dry-run", cmd)

    def test_explicit_return_key_is_honoured(self):
        """单独跑 scout 想回列表页时，显式值不能被默认值吃掉。"""
        cmd = self._cmd_of(_ctx(return_key="ctrlw"))
        self.assertEqual(cmd[cmd.index("--return-key") + 1], "ctrlw")

    def test_scout_dry_appends_dry_run(self):
        cmd = self._cmd_of(_ctx(scout_dry=True))
        self.assertIn("--dry-run", cmd)

    def test_rounds_forwarded(self):
        cmd = self._cmd_of(_ctx(scout_rounds=3))
        self.assertEqual(cmd[cmd.index("--max-rounds") + 1], "3")


class TestArgParsing(unittest.TestCase):
    """CLI 默认值也要守：默认 none，非法值直接报参数错。"""

    def test_default_return_key_is_none(self):
        captured = {}

        def fake_main_run():
            return 0

        # 只解析、不执行：把 ORDER 里的写阶段全部 skip 掉，只跑 preflight 的替身
        with mock.patch.dict(pl.STAGES, {"preflight": lambda ctx: captured.update(ctx) or "ok"}):
            rc = pl.main(["--account", "某号", "--skip",
                          "scout,download,clean,manifest,meta,package,ingest,maps,"
                          "derived,export,verify", "--dry"])
        self.assertEqual(rc, 0)
        self.assertEqual(captured.get("return_key"), "none")

    def test_invalid_return_key_rejected(self):
        with self.assertRaises(SystemExit):
            pl.main(["--account", "某号", "--return-key", "左右横跳"])


class TestCleanEnv(unittest.TestCase):
    """启动下载工具时必须剥掉代理环境变量。

    2026-10-23 真机：工具日志只刷「提示：可以把梯子关了试一试」。不是它的网络问题
    —— `curl https://mp.weixin.qq.com/` 直连 200，但本进程 env 里有
    HTTP_PROXY=http://127.0.0.1:58016（WorkBuddy 内部代理），subprocess 默认继承，
    工具的请求全被塞进那个代理。工具只访问微信，剥掉代理没有副作用。
    """

    def test_proxy_vars_stripped(self):
        polluted = {"HTTP_PROXY": "http://127.0.0.1:58016",
                    "https_proxy": "http://127.0.0.1:58016",
                    "ALL_PROXY": "socks5://127.0.0.1:7890",
                    "PATH": "/bin", "TEMP": "/tmp"}
        with mock.patch.dict(pl.os.environ, polluted, clear=True):
            env = pl._clean_env()
        for k in ("HTTP_PROXY", "https_proxy", "ALL_PROXY"):
            self.assertNotIn(k, env, "%s 必须剥掉，否则工具以为用户开了梯子" % k)
        self.assertEqual(env["PATH"], "/bin")          # 其余环境照常保留
        self.assertIn("mp.weixin.qq.com", env["NO_PROXY"])

    def test_no_proxy_kept_when_present(self):
        with mock.patch.dict(pl.os.environ, {"NO_PROXY": "corp.local"}, clear=True):
            self.assertEqual(pl._clean_env()["NO_PROXY"], "corp.local")


class TestDownloadPassesArticleUrl(unittest.TestCase):
    """`--article-url` 必须真的加成 `--var ARTICLE_URL=…` 传给 clicker。

    工具的「微信文章链接」框留空时点「1.获取公众号id」**不写任何日志**（2026-10-23
    实测），所以 pipeline 传不传这个值直接决定下载阶段能不能开工。这类"跨进程
    参数"只能靠断言命令行来守。
    """

    def _cmd_of(self, article_url, range_key=None):
        import clicker  # stage_download 内部 import 的同一个模块
        done = SimpleNamespace(stdout='{"clicked": 0}', stderr="", returncode=0)
        win = {"handle": 1, "pid": 1, "title": "t", "class_name": "Mywindow"}
        extra = {} if range_key is None else {"range": range_key}
        with tempfile.TemporaryDirectory() as td:
            ctx = _ctx(article_url=article_url,
                       base=Path(td), root=Path(td) / "某号", **extra)
            (Path(td) / "某号").mkdir()
            with mock.patch.object(pl, "run", return_value=done) as m, \
                 mock.patch.object(pl, "md_count", side_effect=[0, 3]), \
                 mock.patch.object(clicker, "find_windows", return_value=[win]), \
                 mock.patch.object(pl.time, "sleep"):
                pl.stage_download(ctx)
            return [str(c) for c in m.call_args[0][0]]

    def test_url_forwarded_as_var(self):
        cmd = self._cmd_of("https://mp.weixin.qq.com/s?__biz=ABC&sn=1")
        self.assertIn("--var", cmd)
        self.assertIn("ARTICLE_URL=https://mp.weixin.qq.com/s?__biz=ABC&sn=1", cmd)
        self.assertIn("wechat_batch_downloader", cmd)

    def test_no_url_means_no_var(self):
        cmd = self._cmd_of("")
        # 断言的是"没有 ARTICLE_URL 变量"：--var 本身总会出现（RANGE 永远显式传），
        # 用 "--var 不存在" 当判据会在加入 RANGE 后失效并误报。
        self.assertFalse([c for c in cmd if c.startswith("ARTICLE_URL=")], cmd)


class TestDownloadPassesRange(unittest.TestCase):
    """时间范围必须透传成 `--var RANGE=…`：传丢不会报错，只会静默少抓。

    profile 里两条互斥步骤靠 RANGE 二选一；参数没送到子进程时，走的永远是
    `when_default` 那条 —— 命令看起来成功了，产物却按别的口径抓的。
    """

    def _cmd_of(self, **kw):
        return TestDownloadPassesArticleUrl._cmd_of(self, "", **kw)

    def test_default_is_all(self):
        cmd = self._cmd_of()
        self.assertIn("RANGE=all", cmd, "默认应为全部历史，否则批量采集会漏早篇")

    def test_explicit_monthly_is_forwarded(self):
        cmd = self._cmd_of(range_key="monthly")
        self.assertIn("RANGE=monthly", cmd)

    def test_cli_flag_reaches_ctx(self):
        """`--range` 必须落进 ctx，否则 stage_download 读到的永远是缺省值。"""
        captured = {}
        stages = dict(pl.STAGES)
        stages["download"] = lambda ctx: captured.update(ctx) or "ok"
        with mock.patch.object(pl, "STAGES", stages), \
                contextlib.redirect_stdout(io.StringIO()):
            rc = pl.main(["--account", "X", "--from-step", "download",
                          "--to-step", "download", "--range", "monthly", "--yes"])
        self.assertEqual(rc, 0)
        self.assertEqual(captured.get("range"), "monthly")


if __name__ == "__main__":
    unittest.main()
