#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""favorites_chain.py 离线测试：不截图、不点击、不调子进程、不起 GUI。

覆盖七步串联驱动器里**可以离线判定**的那部分逻辑（真机交互留给 `--dry-run`）：
  ① 剪贴板取值校验：只收 `/s/xxx` 文章链接，拒 profile_ext / 裸域名 / 空串；
  ② 从 clicker 日志里抠 profile_ext：抠不到必须留空，绝不拿文章链接冒充；
  ③ 行选择：按 y1 从上到下取第一个未处理行，全部处理过返回 None；
  ④ 参数闸门：真执行必须带 --yes，--dry-run 不需要；
  ⑤ 台账降级：ledger 模块缺失或抛异常时只告警，不让主流程失败；
  ⑥ 模板定位与兜底：「⊙」命中用模板中心，失配才退回 (997,44)。

这些都是"判错了会静默出错"的地方（点错菜单项、漏采、台账污染），
所以全部抽成纯函数单独测，不依赖真实微信窗口。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ["UIAC_NO_DPI_AWARE"] = "1"   # 测试进程不做 DPI 副作用
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import favorites_chain as fc  # noqa: E402
from PIL import Image  # noqa: E402

_ART = "https://mp.weixin.qq.com/s/p2F_6HPLdrLWKzwojIAvPw"


# --------------------------------------------------------------- ① 链接校验
@pytest.mark.parametrize("url", [
    _ART,
    "https://mp.weixin.qq.com/s/p2F_6HPLdrLWKzwojIAvPw?from=timeline",
    "http://mp.weixin.qq.com/s/abc123",
    "https://mp.weixin.qq.com/s?__biz=MzI5NTgx&mid=2650000001&idx=1&sn=dead",
])
def test_is_article_url_accepts_article_forms(url):
    assert fc.is_article_url(url) is True


@pytest.mark.parametrize("url", [
    # profile_ext 是"公众号主页"，不是某篇文章；喂给下载工具只会一直"获取密钥失败"
    "https://mp.weixin.qq.com/mp/profile_ext?action=home&__biz=MzI5NTgx",
    "https://mp.weixin.qq.com/",                       # 裸域名（公众平台登录页）
    "https://mp.weixin.qq.com/s",                      # 只有 /s 没有 id
    "https://mp.weixin.qq.com/s/",                     # /s/ 后面是空
    "https://example.com/s/abc",                       # 域名不对
    "",                                                # 空串
    None,                                              # 剪贴板读不到
    "不是链接",                                          # 纯文本
])
def test_is_article_url_rejects_non_article(url):
    assert fc.is_article_url(url) is False


def test_is_article_url_strips_whitespace():
    """剪贴板里的链接常带首尾换行：strip 后必须判成有效。"""
    assert fc.is_article_url("  %s\n" % _ART) is True


# ---------------------------------------------------------- ② profile_ext 抠取
_CLICKER_LOG = """\
目标窗口: '公众号文章批量下载工具' (handle=123456)
{"ts": "2026-10-26T10:00:00Z", "level": "info", "event": "step.done", "index": 18,
 "name": "填入微信文章链接（变量 ARTICLE_URL）", "detail": "%s"}
  [18] 填入微信文章链接（变量 ARTICLE_URL） ok    %s
{"ts": "2026-10-26T10:00:20Z", "level": "info", "event": "step.done", "index": 20,
 "name": "等日志给出 profile_ext 链接", "detail": "https://mp.weixin.qq.com/mp/profile_ext?action=home&__biz=MzI5NTgxNQ==&scene=124#wechat_redirect"}
{"ts": "2026-10-26T10:00:40Z", "level": "info", "event": "run.done", "warned": 0}
""" % (_ART, _ART)


def test_extract_profile_url_from_clicker_log():
    """日志里同时有文章链接和 profile_ext：必须挑 profile_ext（下游要用它取 cookie）。"""
    got = fc.extract_profile_url(_CLICKER_LOG)
    assert got.startswith("https://mp.weixin.qq.com/mp/profile_ext")
    assert "__biz=MzI5NTgxNQ==" in got


def test_extract_profile_url_strips_trailing_cjk_punctuation():
    """clicker 日志里 profile_ext 紧跟中文标点时，必须剥掉噪声、保留密钥链接完整。

    链级回归（2026-10-27 加固）：最终抽取走的是 wechat_open_url.find_url_in_text
    （其 _trim_url 在首个中文标点处截断）。若 favorites_chain 哪天改回用自己的正则
    绕过它，这条测试会把"多吞标点"暴露出来——密钥链接一旦带上 。，；： 就会被
    下载工具判成非法、永远『获取密钥失败』，且极难归因。
    """
    clean = ("https://mp.weixin.qq.com/mp/profile_ext?action=home"
             "&__biz=MzI5NTgxNQ==&scene=124#wechat_redirect")
    noisy = clean + "。复制链接成功，下次再试；请先在微信打开"
    text = '{"event": "step.done", "detail": "%s"}\n日志输出了链接。' % noisy
    got = fc.extract_profile_url(text)
    assert got == clean, "链级抽取不该把中文标点吞进密钥链接：%r" % got
    assert got.endswith("#wechat_redirect")
    assert "__biz=MzI5NTgxNQ==" in got


def test_extract_profile_url_empty_when_only_article_link():
    """只有文章链接时必须留空——不能把文章链接冒充成公众号主页链接。"""
    text = "ARTICLE_URL=%s\n复制链接成功 %s\n" % (_ART, _ART)
    assert fc.extract_profile_url(text) == ""


@pytest.mark.parametrize("text", ["", None])
def test_extract_profile_url_empty_input(text):
    assert fc.extract_profile_url(text) == ""


# ------------------------------------------- ②b 剪贴板写入序号判据（真机教训）
# 2026-10-26 真机：点「复制链接」前剪贴板里已经是同一篇文章的链接，WeChat 写进去
# 的是同一个字符串 ⇒ 只看"内容变没变"会把"重采同一篇"误判成"复制没生效"。
# 序号与内容无关，是"有没有人写过"的唯一可靠信号。
def test_clipboard_accepts_when_seq_changed_same_text():
    """序号变了 + 内容与点击前相同 + 内容是合法链接 → 接受（重采同一篇）。"""
    url, verdict = fc.read_copied_url(_ART, 100, 101, _ART)
    assert (url, verdict) == (_ART, "rewritten")


def test_clipboard_rejects_when_seq_unchanged_same_text():
    """序号没变 + 内容相同 → 复制真的没生效，仍判失败（护栏没被放松）。"""
    url, verdict = fc.read_copied_url(_ART, 100, 100, _ART)
    assert url is None and verdict == "unchanged"


def test_clipboard_rejects_invalid_text_even_if_seq_changed():
    """序号变了但写进来的是空/非链接 → 仍然不收（序号不是免死金牌）。"""
    for bad in ("", "   ", "https://mp.weixin.qq.com/mp/profile_ext?action=home", "随便一段话"):
        url, verdict = fc.read_copied_url(bad, 100, 101, bad)
        assert url is None and verdict == "bad", bad


def test_clipboard_accepts_new_link():
    """序号变了 + 内容变了 + 合法链接 → 正常路径。"""
    url, verdict = fc.read_copied_url("https://mp.weixin.qq.com/s/OLD", 100, 101, _ART)
    assert (url, verdict) == (_ART, "ok")


def test_clipboard_unknown_seq_falls_back_to_fail_closed():
    """读不到序号（-1）时不许放行：退回"只看内容"的老判据。"""
    url, verdict = fc.read_copied_url(_ART, -1, -1, _ART)
    assert url is None and verdict == "unchanged"


def test_clipboard_seq_zero_api_broken_still_accepts_changed_content():
    """序号 API 返回 0（Win32 下调用失败的约定返回值）时，靠内容判据兜住。

    没有这条降级，"API 全 0"会让序号永远相等 ⇒ 这台机器上**所有篇**都被判失败
    （把"同篇重跑"的假阴性扩大到整机）。内容变了+合法链接本身就是可信证据。
    """
    url, verdict = fc.read_copied_url("https://mp.weixin.qq.com/s/OLD", 0, 0, _ART)
    assert (url, verdict) == (_ART, "ok")


def test_clipboard_seq_zero_and_same_content_still_fails():
    """但要守住另一头：序号不可用 + 内容相同 → 仍 fail-closed（判不出就是判不出）。"""
    url, verdict = fc.read_copied_url(_ART, 0, 0, _ART)
    assert url is None and verdict == "unchanged"


def test_clipboard_handles_whitespace_and_none():
    """剪贴板文本常带首尾换行；None 也要安全（判 bad 而不是崩）。"""
    # 首尾换行必须被 strip 掉再比较，否则"同一篇"会被当成"内容变了"
    assert fc.read_copied_url("  %s\n" % _ART, 100, 101, _ART) == (_ART, "rewritten")
    assert fc.read_copied_url(None, 100, 101, None) == (None, "bad")


def test_clip_seq_returns_int():
    """_clip_seq 必须永远返回 int（失败返回 -1），不能抛异常。"""
    assert isinstance(fc._clip_seq(), int)


# ------------------------------------------------------------- ③ 行选择逻辑
def _rows(*ys):
    """构造行几何（只保留选择逻辑用得到的字段）。"""
    return [{"y1": y, "y2": y + 60, "center": y + 30,
             "thumb_x1": 1338, "account_box": [400, y + 34, 1330, y + 60],
             "click_point": [440, y + 30]} for y in ys]


def _fake_fp(row):
    """用 y1 冒充指纹：选择逻辑只关心"这个指纹处理过没有"，与真 dHash 无关。"""
    return "fp-%s" % row["y1"]


def test_annotate_rows_sorts_top_down_and_attaches_fp():
    rows = fc.annotate_rows(_rows(400, 100, 250), _fake_fp)
    assert [r["y1"] for r in rows] == [100, 250, 400]
    assert [r["fp"] for r in rows] == ["fp-100", "fp-250", "fp-400"]


def test_annotate_rows_does_not_mutate_input():
    src = _rows(100)
    fc.annotate_rows(src, _fake_fp)
    assert "fp" not in src[0]


def test_pick_next_row_returns_topmost_unprocessed():
    """R1（从上到下）：即使 rows 顺序被打乱，也必须选 y1 最小的未处理行。"""
    rows = fc.annotate_rows(_rows(400, 200, 100), _fake_fp)
    got = fc.pick_next_row(rows, {"fp-100"})
    assert got["y1"] == 200


def test_pick_next_row_no_processed_picks_first():
    rows = fc.annotate_rows(_rows(300, 120), _fake_fp)
    assert fc.pick_next_row(rows, set())["y1"] == 120


def test_pick_next_row_none_when_all_processed():
    rows = fc.annotate_rows(_rows(100, 200), _fake_fp)
    assert fc.pick_next_row(rows, {"fp-100", "fp-200"}) is None


def test_pick_next_row_none_on_empty_rows():
    assert fc.pick_next_row([], set()) is None


def test_pick_next_row_skips_row_without_fingerprint():
    """算不出指纹的行不能点：无法保证"下次不重复点同一篇"。"""
    rows = [{"y1": 100, "click_point": [10, 20]},
            {"y1": 200, "fp": "fp-200", "click_point": [10, 30]}]
    got = fc.pick_next_row(rows, set())
    assert got["y1"] == 200


def test_count_processed():
    rows = fc.annotate_rows(_rows(100, 200, 300), _fake_fp)
    assert fc.count_processed(rows, {"fp-100", "fp-300"}) == 2


# --------------------------------------------------------------- ④ 参数闸门
def _args(**kw):
    base = {"max": 1, "dry_run": False, "yes": False}
    base.update(kw)
    return SimpleNamespace(**base)


def test_validate_args_requires_yes_for_real_run():
    code, msg = fc.validate_args(_args(yes=False))
    assert code == fc.EXIT_PARAM
    assert "--yes" in msg


def test_validate_args_dry_run_needs_no_yes():
    assert fc.validate_args(_args(dry_run=True)) == (fc.EXIT_OK, "")


def test_validate_args_ok_with_yes():
    assert fc.validate_args(_args(yes=True)) == (fc.EXIT_OK, "")


@pytest.mark.parametrize("bad", [0, -1])
def test_validate_args_rejects_bad_max(bad):
    code, msg = fc.validate_args(_args(max=bad, yes=True))
    assert code == fc.EXIT_PARAM
    assert "--max" in msg


def test_main_without_yes_exits_param(capsys):
    """main 的不带 --yes 路径必须在碰窗口之前就退出（2），不能先截图再报错。"""
    assert fc.main(["--max", "1"]) == fc.EXIT_PARAM
    assert "--yes" in capsys.readouterr().err


def test_main_rejects_zero_max():
    assert fc.main(["--max", "0", "--yes"]) == fc.EXIT_PARAM


# --------------------------------------------------------------- ⑤ 台账降级
def test_append_ledger_missing_module_is_silent(monkeypatch):
    """ledger.py 还没落盘（并行开发中）时，只告警、返回 False，不抛异常。"""
    monkeypatch.setitem(sys.modules, "ledger", None)   # import 必然失败
    assert fc.append_ledger({"url": _ART}) is False


def test_append_ledger_swallows_exception():
    def boom(_rec):
        raise RuntimeError("ledger 内部炸了")

    assert fc.append_ledger({"url": _ART},
                            mod=SimpleNamespace(append_record=boom)) is False


def test_append_ledger_passes_record_through():
    seen = []
    mod = SimpleNamespace(append_record=seen.append)
    rec = {"source": "赞和收藏", "account": "", "title": "", "url": _ART,
           "profile_url": "", "note": ""}
    assert fc.append_ledger(rec, mod=mod) is True
    assert seen == [rec]
    assert seen[0]["source"] == "赞和收藏"


def test_append_ledger_export_failure_is_not_fatal():
    """CSV 已写成功、只是 md 视图没刷新：仍算成功（不能因为展示层失败回滚记账）。"""
    def boom():
        raise OSError("磁盘满了")

    mod = SimpleNamespace(append_record=lambda rec: dict(rec), export_markdown=boom)
    assert fc.append_ledger({"url": _ART}, mod=mod) is True


def test_real_ledger_accepts_our_record_shape(tmp_path, monkeypatch):
    """与 ledger.py 的契约测试：我们这 6 个字段必须能被真实台账吃下去。

    ledger 由同事并行开发，字段口径一旦漂移，主流程会在"下载成功之后"才炸，
    最坏情况是文章下了但台账没记。这里把落盘路径改到 tmp、把联网抓元信息换成
    桩，端到端验证一次"我们发的 record 长什么样、它落成什么样"。

    重定向走 UIAC_LEDGER_CSV / UIAC_LEDGER_MD 两个环境变量（ledger 自己测试也
    这么用），不动模块常量：常量是进程级共享状态，改了万一没还原，后续用例会
    把真 out/ 当沙箱写。
    """
    ledger = pytest.importorskip("ledger")
    monkeypatch.setenv("UIAC_LEDGER_CSV", str(tmp_path / "ledger.csv"))
    monkeypatch.setenv("UIAC_LEDGER_MD", str(tmp_path / "ledger.md"))
    # 台账在 account/title 为空时会联网抓元信息；测试不许联网
    monkeypatch.setattr(ledger, "fetch_meta",
                        lambda url: {"account": "牧海宠物", "title": "牛磺酸缺乏的代价",
                                     "publish_time": "2026-10-20T00:00:00Z"})

    ok = fc.append_ledger({
        "source": "赞和收藏", "account": "", "title": "", "url": _ART,
        "profile_url": "https://mp.weixin.qq.com/mp/profile_ext?action=home&__biz=X",
        "note": "",
    }, mod=ledger)

    assert ok is True
    rows = ledger.load()
    assert len(rows) == 1
    assert rows[0]["来源渠道"] == "赞和收藏"
    assert rows[0]["文章链接"] == _ART
    assert rows[0]["公众号名称"] == "牧海宠物"        # 留空后由 ledger 自己抓
    assert rows[0]["profile_ext网址"].startswith("https://mp.weixin.qq.com/mp/profile_ext")
    assert (tmp_path / "ledger.md").is_file()          # 人可读视图同步刷新了


# ------------------------------------- rc=5 且拿不到 profile_ext 时的显性告警
_PROFILE = "https://mp.weixin.qq.com/mp/profile_ext?action=home&__biz=X"


@pytest.mark.parametrize("rc,profile_url,event", [
    (fc.EXIT_PARTIAL, "", "chain.partial_without_profile_url"),  # 5 且没 id → 显性告警
    (fc.EXIT_OK, "", "chain.profile_url_missing"),               # 0 且没 id → 普通告警
    (fc.EXIT_PARTIAL, _PROFILE, None),                           # 5 但拿到 id → 不告警
    (fc.EXIT_OK, _PROFILE, None),                                # 0 且拿到 id → 不告警
])
def test_id_missing_event_decision(rc, profile_url, event):
    """告警判定：只有"没拿到 profile_ext"才报；rc=5 单独一个事件名。

    为什么要单测这条：rc=5 只证明"有可选步骤失败过"，不能证明「1.获取公众号id」
    成功。今天 5 只来自「勾选导出HTML文件」（本机恒禁用），无害；但 rc=5 且连
    profile_ext 都没有，说明失败的可能不止那一步，而链路上一切"看起来正常"。
    这个事件名是唯一能让人发现台账退化的抓手。
    """
    got_event, hint = fc.id_missing_event(rc, profile_url)
    assert got_event == event
    if event is None:
        assert hint == ""
    else:
        assert hint


def test_partial_hint_spells_out_the_consequence():
    """rc=5 那条提示必须点明"降级为按文章链接去重 + 同号收敛失效"这个后果。"""
    _, hint = fc.id_missing_event(fc.EXIT_PARTIAL, "")
    assert "导出HTML文件" in hint
    assert "文章链接去重" in hint
    assert "同号收敛" in hint


def _stub_one_round(monkeypatch, rows, rc, profile_url):
    """把一整轮真跑（非预演）的副作用全部换成桩，返回 (events, journal)。

    点击/键/等待/下载工具/台账全打桩，**不碰真实窗口**；`fc.log` 换成记录器，
    这样可以断言"哪个事件、带了哪些字段"。
    """
    img = Image.new("RGB", (1821, 1518), (250, 250, 250))
    rect = (740, 0, 2561, 1518)
    events: list[tuple[str, str, dict]] = []

    monkeypatch.setattr(fc, "log",
                        lambda level, event, **kw: events.append((level, event, kw)))
    monkeypatch.setattr(fc.wf, "ensure_window",
                        lambda: {"hwnd": 1, "rect": list(rect)})
    monkeypatch.setattr(fc.wf, "_capture", lambda hwnd: (img, rect))
    monkeypatch.setattr(fc.wf, "page_state", lambda im: {
        "title": 1.0, "tab": 1.0, "tab_edge": 1.0, "rows": len(rows),
        "ok": True, "signal": "title"})
    monkeypatch.setattr(fc.wf, "rows_for", lambda im, rc_: (rows, "runtime"))
    monkeypatch.setattr(fc.wf, "row_fingerprint", lambda im, row: "fp-%s" % row["y1"])
    monkeypatch.setattr(fc.wf, "_nap", lambda base: None)
    monkeypatch.setattr(fc, "_click_abs", lambda rect_, x, y, jitter=4: True)
    monkeypatch.setattr(fc.vision, "wait_until", lambda *a, **k: True)
    monkeypatch.setattr(fc.vision, "key_tap", lambda *a, **k: None)
    monkeypatch.setattr(fc.vision, "close_tab", lambda: None)
    monkeypatch.setattr(fc, "restore_list", lambda hwnd, t=None: True)
    monkeypatch.setattr(fc, "copy_article_link",
                        lambda hwnd, clip_timeout=3.0: (_ART, {"reason": "ok"}))
    monkeypatch.setattr(fc, "run_downloader",
                        lambda url, index, profile=None, range_key="all",
                        from_step=1, max_steps=0, tag="":
                        (rc, "clicker 输出", profile_url if tag == "a" else ""))
    monkeypatch.setattr(fc, "account_already_collected",
                        lambda pu, mod=None: (False, 0))   # 不查真台账
    monkeypatch.setattr(fc, "append_ledger", lambda rec, mod=None: True)
    return events


def test_partial_without_profile_url_warn_fires(monkeypatch, tmp_path):
    """rc=5 且 profile_url 为空：必须报 chain.partial_without_profile_url。

    同时锁住两件事：① 事件带够排查字段（rc/round/article_url/clicker_log）；
    ② 仍按**成功**记账（decision=click），不许改判 download_failed。
    """
    journal = tmp_path / "chain.jsonl"
    rows = _rows(100)
    events = _stub_one_round(monkeypatch, rows, fc.EXIT_PARTIAL, "")

    code = fc.main(["--max", "1", "--yes", "--journal", str(journal)])

    assert code == fc.EXIT_OK
    hits = [e for e in events if e[1] == "chain.partial_without_profile_url"]
    assert len(hits) == 1
    level, _, kw = hits[0]
    assert level == "warn"
    assert kw["rc"] == fc.EXIT_PARTIAL
    assert kw["round"] == 0
    assert kw["article_url"] == _ART
    # 分两段跑之后，段 B（真正点批量下载那段）的日志是 chain-clicker-00b.log
    assert kw["clicker_log"].endswith("chain-clicker-00b.log")
    assert "同号收敛" in kw["hint"]

    rec = json.loads(journal.read_text(encoding="utf-8").splitlines()[-1])
    assert rec["decision"] == "click"              # 仍参与去重，没改判失败
    assert rec["result"] == "ok_no_profile_ext"
    assert rec["clicker_rc"] == fc.EXIT_PARTIAL


def test_partial_with_profile_url_does_not_warn(monkeypatch, tmp_path):
    """rc=5 但 profile_url 拿到了：不该有任何"缺 profile_ext"的告警。"""
    journal = tmp_path / "chain.jsonl"
    events = _stub_one_round(monkeypatch, _rows(100), fc.EXIT_PARTIAL, _PROFILE)

    code = fc.main(["--max", "1", "--yes", "--journal", str(journal)])

    assert code == fc.EXIT_OK
    names = [e[1] for e in events]
    assert "chain.partial_without_profile_url" not in names
    assert "chain.profile_url_missing" not in names
    rec = json.loads(journal.read_text(encoding="utf-8").splitlines()[-1])
    assert rec["result"] == "ok" and rec["profile_url"] == _PROFILE
    # 采集口径要留在台账之外也能追溯：journal 里必须记下本次请求的 range
    assert rec["range"] == "all"


# ------------------------------------------------- ⑥ 模板定位与「⊙」兜底
def test_more_point_uses_template_center():
    """模板命中时按命中中心算坐标（坑 1：x 随标签标题长度变，不能硬编码）。"""
    img = Image.new("RGB", (800, 600), (250, 250, 250))
    tpl = Image.open(str(fc.TPL / fc.MORE_TPL)).convert("RGB")
    img.paste(tpl, (100, 50))
    x, y, fallback = fc.more_point(img)
    assert fallback is False
    assert (x, y) == (100 + tpl.width // 2, 50 + tpl.height // 2)


def test_more_point_falls_back_when_template_misses():
    """模板失配才退回实测常数，且必须明确告知调用方"这是兜底"。"""
    blank = Image.new("RGB", (800, 600), (250, 250, 250))
    x, y, fallback = fc.more_point(blank)
    assert fallback is True
    assert (x, y) == fc.MORE_FALLBACK == (997, 44)


# ------------------------------------------------------- 子进程输出与 journal
def test_decode_output_utf8_and_gbk():
    assert fc.decode_output("中文日志".encode("utf-8")) == "中文日志"
    assert fc.decode_output("中文日志".encode("gbk")) == "中文日志"
    assert fc.decode_output(None) == ""
    assert fc.decode_output("已是文本") == "已是文本"


def test_decode_output_never_raises_on_garbage():
    """解不干净的字节也要给出可读结果（带替换字符），不能把整条链路炸掉。"""
    assert isinstance(fc.decode_output(b"\xff\xfe\x00\x01\x02"), str)


def test_append_journal_writes_readable_jsonl(tmp_path):
    """journal 用 ensure_ascii=False：中文要能直接看懂，排查时少一道解码。"""
    p = tmp_path / "sub" / "chain.jsonl"      # 目录不存在也要能建
    fc.append_journal(p, {"decision": "click", "reason": "已拿到文章链接", "fp": "x"})
    fc.append_journal(p, {"decision": "not_opened", "fp": "y"})
    lines = p.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert "已拿到文章链接" in lines[0]
    assert json.loads(lines[0])["fp"] == "x"
    assert json.loads(lines[1])["decision"] == "not_opened"


def test_journal_decision_click_is_what_dedup_recognises(tmp_path):
    """只有 decision=="click" 会被 wf.processed_fingerprints 当成已处理。

    这条不是实现细节：失败分支若误记成 click，那篇文章会被永久静默跳过
    （静默漏采）；反过来记错成别的值只会重复点一次。这里把两种记法都过一遍
    真实的 wf.processed_fingerprints，防止将来改字段名时静默失配。
    """
    p = tmp_path / "chain.jsonl"
    fc.append_journal(p, {"decision": "click", "fp": "ok-fp"})
    fc.append_journal(p, {"decision": "download_failed", "fp": "retry-fp"})
    fc.append_journal(p, {"decision": "link_ok", "fp": "skip-fp"})
    got = fc.wf.processed_fingerprints(p)
    assert got == {"ok-fp"}


# --------------------------------------------- ⑧ 账号级去重（同一 profile_ext）
_PROFILE2 = "https://mp.weixin.qq.com/mp/profile_ext?action=home&__biz=MzI5NTgxNQ=="


def _stub_download_round(monkeypatch, rows, *, ledger_hit=(False, 0),
                         profile_url=_PROFILE2, rc=5):
    """一轮完整真跑（全桩），返回 (calls, events)。

    `run_downloader` 被换成记录器：它能看出这一轮到底跑了几段（tag='a'/'b'），
    这正是"账号已采集时不该下载"的判据 —— 断言比"返回码看起来对不对"更硬。
    """
    calls = {"downloader": [], "ledger": []}
    img = Image.new("RGB", (1821, 1518), (250, 250, 250))
    rect = (740, 0, 2561, 1518)
    events: list[tuple[str, str, dict]] = []

    monkeypatch.setattr(fc, "log",
                        lambda level, event, **kw: events.append((level, event, kw)))
    monkeypatch.setattr(fc.wf, "ensure_window",
                        lambda: {"hwnd": 1, "rect": list(rect)})
    monkeypatch.setattr(fc.wf, "_capture", lambda hwnd: (img, rect))
    monkeypatch.setattr(fc.wf, "page_state", lambda im: {
        "title": 1.0, "tab": 1.0, "tab_edge": 1.0, "rows": len(rows),
        "ok": True, "signal": "title"})
    monkeypatch.setattr(fc.wf, "rows_for", lambda im, rc_: (rows, "runtime"))
    monkeypatch.setattr(fc.wf, "row_fingerprint", lambda im, row: "fp-%s" % row["y1"])
    monkeypatch.setattr(fc.wf, "_nap", lambda base: None)
    monkeypatch.setattr(fc, "_click_abs", lambda *a, **k: True)
    monkeypatch.setattr(fc.vision, "wait_until", lambda *a, **k: True)
    monkeypatch.setattr(fc.vision, "key_tap", lambda *a, **k: None)
    monkeypatch.setattr(fc.vision, "close_tab", lambda: None)
    monkeypatch.setattr(fc, "restore_list", lambda hwnd, t=None: True)
    monkeypatch.setattr(fc, "copy_article_link",
                        lambda hwnd, clip_timeout=3.0: (_ART, {"reason": "ok"}))
    monkeypatch.setattr(fc, "account_already_collected",
                        lambda pu, mod=None: ledger_hit)

    def fake_downloader(url, index, profile=None, range_key="all",
                        from_step=1, max_steps=0, tag=""):
        calls["downloader"].append({"tag": tag, "from_step": from_step,
                                    "max_steps": max_steps})
        return rc, "clicker 输出", (profile_url if tag == "a" else "")

    monkeypatch.setattr(fc, "run_downloader", fake_downloader)
    monkeypatch.setattr(fc, "append_ledger",
                        lambda rec, mod=None: calls["ledger"].append(rec) or True)
    return calls, events


def test_same_account_skips_the_download_phase(monkeypatch, tmp_path):
    """台账已有该 profile_ext → 只跑段 A（拿 id），**段 B 一次都不许跑**。

    这条是成本护栏的核心：收藏里同一个号 3 篇，按行指纹去重只会整号下载 3 遍。
    """
    journal = tmp_path / "chain.jsonl"
    calls, _ = _stub_download_round(monkeypatch, _rows(100), ledger_hit=(True, 7))

    code = fc.main(["--max", "1", "--yes", "--journal", str(journal)])

    assert code == fc.EXIT_OK          # 处理完了（台账备注已更新），不是"部分成功"
    assert [c["tag"] for c in calls["downloader"]] == ["a"], "不该进入段 B（下载）"
    assert len(calls["ledger"]) == 1, "仍要把这篇的链接补进已有行的备注"
    rec = json.loads(journal.read_text(encoding="utf-8").splitlines()[-1])
    assert rec["decision"] == "same_account_skipped"
    assert rec["existing_row"] == 7
    assert rec["profile_url"] == _PROFILE2


def test_same_account_skip_does_not_enter_fingerprint_dedup(monkeypatch, tmp_path):
    """`same_account_skipped` 不能被算成"这一行永久处理过"。

    否则台账哪天被清空、想重采这个号时，这些文章会被静默跳过 —— 用真实的
    `wf.processed_fingerprints` 断言，而不是自己造一个假实现。
    """
    journal = tmp_path / "chain.jsonl"
    _stub_download_round(monkeypatch, _rows(100), ledger_hit=(True, 1))
    fc.main(["--max", "1", "--yes", "--journal", str(journal)])
    assert fc.wf.processed_fingerprints(journal) == set()
    assert json.loads(journal.read_text(encoding="utf-8").splitlines()[-1])["fp"] == "fp-100"


def test_new_account_runs_both_phases_and_records(monkeypatch, tmp_path):
    """台账没有这个号 → 段 A + 段 B 都跑，正常记账，decision=click。"""
    journal = tmp_path / "chain.jsonl"
    calls, _ = _stub_download_round(monkeypatch, _rows(100), ledger_hit=(False, 0))

    code = fc.main(["--max", "1", "--yes", "--journal", str(journal)])

    assert code == fc.EXIT_OK
    assert [c["tag"] for c in calls["downloader"]] == ["a", "b"]
    assert calls["downloader"][0]["max_steps"] == fc.PROFILE_SPLIT_STEP
    assert calls["downloader"][1]["from_step"] == fc.PROFILE_SPLIT_STEP + 1
    rec = json.loads(journal.read_text(encoding="utf-8").splitlines()[-1])
    assert rec["decision"] == "click" and rec["result"] == "ok"
    assert calls["ledger"][0]["profile_url"] == _PROFILE2


def test_ignore_ledger_forces_download_even_when_account_exists(monkeypatch, tmp_path):
    """`--ignore-ledger` → 即使台账里已有这个号，也必须照常完整下载。"""
    journal = tmp_path / "chain.jsonl"
    calls, _ = _stub_download_round(monkeypatch, _rows(100), ledger_hit=(True, 3))
    called = []
    monkeypatch.setattr(fc, "account_already_collected",
                        lambda pu, mod=None: called.append(pu) or (True, 3))

    code = fc.main(["--max", "1", "--yes", "--ignore-ledger", "--journal", str(journal)])

    assert code == fc.EXIT_OK
    assert called == [], "--ignore-ledger 时根本不该去查台账（省一次 IO）"
    assert [c["tag"] for c in calls["downloader"]] == ["a", "b"]


def test_account_lookup_degrades_to_download_when_ledger_unreadable():
    """台账读失败 → 返回 (False, 0) 并告警，绝不因台账坏了就不下载。"""
    class Boom:
        @staticmethod
        def load():
            raise OSError("CSV 被 Excel 独占打开")

    assert fc.account_already_collected(_PROFILE2, mod=Boom) == (False, 0)


def test_account_lookup_degrades_when_ledger_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "ledger", None)
    assert fc.account_already_collected(_PROFILE2) == (False, 0)


def test_account_lookup_matches_profile_ext_column():
    """命中判据读的是台账的 `profile_ext网址` 列（与 ledger 的列名一致）。"""
    rows = [{"序号": 2, "profile_ext网址": "https://other/x&__biz=Y"},
            {"序号": 9, "profile_ext网址": _PROFILE2}]
    mod = SimpleNamespace(load=lambda: rows)
    assert fc.account_already_collected(_PROFILE2, mod=mod) == (True, 9)
    assert fc.account_already_collected("https://mp.weixin.qq.com/mp/profile_ext?x=1",
                                        mod=mod) == (False, 0)


def test_account_lookup_ignores_empty_profile_url():
    """没有 profile_ext 时不做判重（空串绝不能匹配到别的空行上）。"""
    mod = SimpleNamespace(load=lambda: [{"序号": 1, "profile_ext网址": ""}])
    assert fc.account_already_collected("", mod=mod) == (False, 0)


# ------------------------------------------------- ⑦ run() 编排（预演，零点击）
def _stub_live(monkeypatch, rows):
    """把"真实微信"换成一屏固定的赞和收藏页（一行都没有点击副作用）。

    只替换入口：ensure_window / _capture / page_state / rows_for / row_fingerprint。
    点击与关标签页替换成**直接抛异常**——预演路径只要碰它们就说明有 bug，
    比断言"没被调用"更早爆出来。
    """
    img = Image.new("RGB", (1821, 1518), (250, 250, 250))
    rect = (740, 0, 2561, 1518)

    def forbidden(*_a, **_kw):
        raise AssertionError("--dry-run 不允许发生任何点击/按键")

    monkeypatch.setattr(fc.wf, "ensure_window",
                        lambda: {"hwnd": 1, "rect": list(rect)})
    monkeypatch.setattr(fc.wf, "_capture", lambda hwnd: (img, rect))
    monkeypatch.setattr(fc.wf, "page_state", lambda im: {
        "title": 1.0, "tab": 1.0, "tab_edge": 1.0, "rows": len(rows),
        "ok": True, "signal": "title"})
    monkeypatch.setattr(fc.wf, "rows_for", lambda im, rc: (rows, "runtime"))
    monkeypatch.setattr(fc.wf, "row_fingerprint", lambda im, row: "fp-%s" % row["y1"])
    monkeypatch.setattr(fc.wf, "_page_pred", lambda *a, **k: (lambda: True))
    for name in ("click_at", "close_tab", "key_tap"):
        monkeypatch.setattr(fc.vision, name, forbidden)
    return rect


def test_dry_run_plans_top_down_without_clicking(monkeypatch, tmp_path, capsys):
    """预演要按 y1 从小到大依次给出计划，且 journal 里留 would_click 供复盘。"""
    rows = _rows(400, 100, 250)
    _stub_live(monkeypatch, rows)
    journal = tmp_path / "chain.jsonl"

    code = fc.main(["--dry-run", "--max", "2", "--journal", str(journal)])

    assert code == fc.EXIT_OK
    recs = [json.loads(x) for x in journal.read_text(encoding="utf-8").splitlines()]
    assert [r["decision"] for r in recs] == ["would_click", "would_click"]
    # 两轮必须落在**不同**的行上（session 去重），且第一轮是最上方那行
    assert [r["row"]["y1"] for r in recs] == [100, 250]
    assert [r["click_abs"][1] for r in recs] == [130, 280]      # y1+30 + rect.top(0)
    assert [r["click_abs"][0] for r in recs] == [440 + 740] * 2
    out = capsys.readouterr().out
    assert "dry-run" in out and "汇总" in out
    # 「跳过」只统计 journal 里的历史记录：本次预演的两行属于"处理"，
    # 不能再算成"跳过"（否则 3 篇预演会报"处理 3 / 跳过 2"，自己跳自己）
    assert "处理 2 篇 / 成功 0 / 跳过 0 / 失败 0" in out


def test_dry_run_stops_partial_when_all_rows_processed(monkeypatch, tmp_path):
    """整屏都处理过时不该硬点，退出码是"部分成功"（有活可干但没得干）。"""
    rows = _rows(100, 200)
    _stub_live(monkeypatch, rows)
    journal = tmp_path / "chain.jsonl"
    for y in (100, 200):
        fc.append_journal(journal, {"decision": "click", "fp": "fp-%s" % y})

    code = fc.main(["--dry-run", "--max", "2", "--journal", str(journal)])

    assert code == fc.EXIT_PARTIAL
    # 没有新增记录：全处理过时连 would_click 都不该写
    lines = journal.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2


def test_summary_skipped_counts_history_not_current_session(monkeypatch, tmp_path,
                                                           capsys):
    """历史 journal 有 1 条已处理 → 跳过早该报 1，且不随轮次重复累加。

    这是 2026-10-26 真机预演抓到的口径 bug：把本会话进度混进"跳过"，
    3 篇预演报成"处理 3 / 跳过 2"。这里固定住正确口径：跳过 = 只数历史。
    """
    rows = _rows(100, 200, 300)
    _stub_live(monkeypatch, rows)
    journal = tmp_path / "chain.jsonl"
    fc.append_journal(journal, {"decision": "click", "fp": "fp-100"})

    code = fc.main(["--dry-run", "--max", "2", "--journal", str(journal)])

    assert code == fc.EXIT_OK
    out = capsys.readouterr().out
    assert "处理 2 篇 / 成功 0 / 跳过 1 / 失败 0" in out      # 不是 2，也不是 4



# --------------------------------------------------- ⑧ --range 透传给 clicker
def test_range_reaches_clicker_cmd(monkeypatch, tmp_path):
    """`--range` 必须真的出现在 clicker 的命令行里（`--var RANGE=…`）。

    这条只能靠断言命令行来守：RANGE 传丢了不会有任何报错，点击照常进行，
    只是悄悄按默认范围抓 —— 产物缺篇且看不出来，比失败更难发现。
    （这里把 subprocess.run 打成桩，不真起子进程。）
    """
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = list(cmd)
        return SimpleNamespace(returncode=0, stdout=b"{}", stderr=b"")

    monkeypatch.setattr(fc, "OUT", tmp_path)      # 别把日志写进真实 out/
    monkeypatch.setattr(fc.subprocess, "run", fake_run)

    fc.run_downloader(_ART, 1, range_key="monthly")
    assert "RANGE=monthly" in seen["cmd"]
    assert "ARTICLE_URL=" + _ART in seen["cmd"]


def test_range_defaults_to_all(monkeypatch, tmp_path):
    """默认必须是 all：batch 采集的口径是"取回完整历史"，monthly 会漏更早的篇目。"""
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = list(cmd)
        return SimpleNamespace(returncode=0, stdout=b"{}", stderr=b"")

    monkeypatch.setattr(fc, "OUT", tmp_path)
    monkeypatch.setattr(fc.subprocess, "run", fake_run)

    fc.run_downloader(_ART, 1)
    assert "RANGE=all" in seen["cmd"]
