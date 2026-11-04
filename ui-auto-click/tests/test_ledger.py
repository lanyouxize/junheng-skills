#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`scripts/ledger.py` 的离线回归测试（全部用 tmp_path 隔离，绝不碰真实 out/）。

守什么
------
1. 序号从 1 起、逐条 +1 —— 用户按序号对账，跳号会以为丢数据；
2. 去重：同 `profile_ext` 收敛成一行（同号文章进备注）、同文章链接不新增行；
3. 抓取失败/`--no-fetch` 时字段留空且不抛异常（网络函数是可替换的桩）；
4. 每个信息类型标签至少一条命中，含全角 `ＧＢ２８０５０—２０２５` 与小写 `haccp`；
5. 手工 `--tags` 与自动标签合并（去重保序、手工在前）；
6. CSV 是 `utf-8-sig`（Excel 双击打开中文不乱码）；
7. 原子写：走 `os.replace`，且失败不留半截文件。

跑法（生产解释器）：
  C:/Users/Administrator/.workbuddy/binaries/python/envs/default/Scripts/python.exe \
      -m pytest tests/test_ledger.py -q
"""
from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))

import ledger  # noqa: E402

ARTICLE_A = "https://mp.weixin.qq.com/s/AAAA1111"
ARTICLE_B = "https://mp.weixin.qq.com/s/BBBB2222"
ARTICLE_C = "https://mp.weixin.qq.com/s/CCCC3333"
PROFILE = "https://mp.weixin.qq.com/mp/profile_ext?action=home&__biz=TESTBIZ"


@pytest.fixture
def paths(tmp_path, monkeypatch):
    """把 CSV/MD 指到 tmp_path，并把网络抓取打成空桩（默认离线）。"""
    csv_path = tmp_path / "out" / "favorites-ledger.csv"
    md_path = tmp_path / "docs" / "favorites-ledger.md"
    monkeypatch.setenv("UIAC_LEDGER_CSV", str(csv_path))
    monkeypatch.setenv("UIAC_LEDGER_MD", str(md_path))
    monkeypatch.setattr(ledger, "fetch_meta", lambda url: {})
    return csv_path, md_path


def _add(**kw):
    rec = {"source": "赞和收藏", "no_fetch": True}
    rec.update(kw)
    return ledger.append_record(rec)


# ------------------------------------------------------------------ 序号 / 落盘
def test_first_record_starts_at_one(paths):
    row = _add(url=ARTICLE_A, title="第一篇")
    assert row["序号"] == 1
    assert row["采集时间"].endswith("Z")
    assert len(ledger.load()) == 1


def test_sequence_increments_per_new_article(paths):
    _add(url=ARTICLE_A, title="第一篇")
    second = _add(url=ARTICLE_B, title="第二篇")
    assert second["序号"] == 2
    assert [r["序号"] for r in ledger.load()] == [1, 2]


def test_csv_is_utf8_sig_for_excel(paths):
    csv_path, _ = paths
    _add(url=ARTICLE_A, title="中文标题")
    raw = csv_path.read_bytes()
    # BOM 必须存在，否则 Excel 双击打开中文列名是乱码
    assert raw.startswith(b"\xef\xbb\xbf")
    with csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
        header = next(csv.reader(fh))
    assert header == ledger.COLUMNS
    assert "公众号名称" in header and "profile_ext网址" in header


def test_write_is_atomic_via_os_replace(paths, monkeypatch):
    csv_path, _ = paths
    calls: list[tuple[str, str]] = []
    real_replace = os.replace

    def spy(src, dst):
        calls.append((str(src), str(dst)))
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy)
    _add(url=ARTICLE_A, title="原子写")

    assert calls, "写入必须经过 os.replace"
    assert calls[-1][1] == str(csv_path)
    # 临时文件不能残留；原文件完整可读
    assert not list(csv_path.parent.glob("*.tmp"))
    assert len(ledger.load()) == 1


# ------------------------------------------------------------------ 去重
def test_same_profile_ext_merges_into_one_row(paths):
    first = _add(url=ARTICLE_A, profile_url=PROFILE, title="第一篇")
    second = _add(url=ARTICLE_B, profile_url=PROFILE, title="第二篇")

    assert second["序号"] == first["序号"] == 1
    assert len(ledger.load()) == 1             # 同号不同文章不新增行
    assert second["文章标题"] == "第二篇"        # 标题被新值更新
    assert second["文章链接"] == ARTICLE_A       # 原链接不被覆盖
    assert ARTICLE_B in second["备注"]          # 同号文章进备注
    assert ledger.SIBLING_MARK in second["备注"]


def test_same_profile_appends_multiple_siblings(paths):
    _add(url=ARTICLE_A, profile_url=PROFILE, title="甲")
    _add(url=ARTICLE_B, profile_url=PROFILE, title="乙")
    row = _add(url=ARTICLE_C, profile_url=PROFILE, title="丙")

    core, siblings = ledger.parse_remark(row["备注"])
    assert siblings == [ARTICLE_B, ARTICLE_C]
    assert ARTICLE_A not in siblings            # 本行自己的链接不进同号清单


def test_same_profile_does_not_duplicate_sibling(paths):
    _add(url=ARTICLE_A, profile_url=PROFILE, title="甲")
    _add(url=ARTICLE_B, profile_url=PROFILE, title="乙")
    row = _add(url=ARTICLE_B, profile_url=PROFILE, title="乙")
    assert ledger.parse_remark(row["备注"])[1] == [ARTICLE_B]


def test_same_url_without_profile_merges(paths):
    _add(url=ARTICLE_A, title="旧标题")
    row = _add(url=ARTICLE_A, title="新标题")

    assert len(ledger.load()) == 1
    assert row["文章标题"] == "新标题"


def test_merge_keeps_existing_values_when_new_ones_empty(paths):
    _add(url=ARTICLE_A, title="原标题", account="某公众号", note="原备注")
    row = _add(url=ARTICLE_A)                  # 只带链接，其余全空

    assert row["文章标题"] == "原标题"
    assert row["公众号名称"] == "某公众号"
    assert "原备注" in row["备注"]


def test_profile_fills_in_on_later_merge_by_url(paths):
    _add(url=ARTICLE_A, title="甲")
    row = _add(url=ARTICLE_A, profile_url=PROFILE)
    assert row["profile_ext网址"] == PROFILE


# ------------------------------------------------------------------ 抓取降级
def test_no_fetch_leaves_fields_blank(paths):
    row = _add(url=ARTICLE_A)
    assert row["公众号名称"] == ""
    assert row["文章标题"] == ""
    assert row["发布时间"] == ""


def test_fetch_failure_does_not_raise(paths, monkeypatch):
    def boom(url):
        raise RuntimeError("网络断了")

    monkeypatch.setattr(ledger, "fetch_meta", boom)
    row = ledger.append_record({"url": ARTICLE_A})   # 未传 no_fetch，必须走抓取失败分支

    assert row["序号"] == 1
    assert row["公众号名称"] == ""
    assert row["文章标题"] == ""


def test_fetch_meta_returns_blank_on_network_error(monkeypatch):
    def boom(url, timeout=ledger.DEFAULT_TIMEOUT):
        raise OSError("DNS 失败")

    monkeypatch.setattr(ledger, "_fetch_html", boom)
    assert ledger.fetch_meta(ARTICLE_A) == {}


def test_fetch_timeout_env_override(monkeypatch):
    # 批量记账嫌 20s 太久时用环境变量调小；非法值必须回到默认而不是崩
    monkeypatch.delenv("UIAC_LEDGER_TIMEOUT", raising=False)
    assert ledger._fetch_timeout() == ledger.DEFAULT_TIMEOUT
    monkeypatch.setenv("UIAC_LEDGER_TIMEOUT", "3")
    assert ledger._fetch_timeout() == 3
    monkeypatch.setenv("UIAC_LEDGER_TIMEOUT", "abc")
    assert ledger._fetch_timeout() == ledger.DEFAULT_TIMEOUT


def test_fetch_meta_fills_fields_from_stub(paths, monkeypatch):
    monkeypatch.setattr(ledger, "fetch_meta", lambda url: {
        "account": "牧海宠物", "title": "牛磺酸与猫粮", "publish_time": "2026-10-11T08:13:29Z",
        "digest": "猫粮里的牛磺酸",
    })
    row = ledger.append_record({"url": ARTICLE_A})

    assert row["公众号名称"] == "牧海宠物"
    assert row["文章标题"] == "牛磺酸与猫粮"
    assert row["发布时间"] == "2026-10-11T08:13:29Z"
    assert "宠物食品" in row["信息类型"]


# ------------------------------------------------------------------ 标签命中
@pytest.mark.parametrize("title,expected", [
    ("猫粮里的牛磺酸到底有多少", "宠物食品"),
    ("益生菌与酶制剂在犬粮中的应用", "添加剂"),
    ("卵磷脂与单甘酯的乳化稳定性", "乳化剂"),
    ("肉粉、鱼粉与豆粕的替代方案", "原料"),
    ("GB 28050—2025 营养标示要求解读", "法规标准"),
    ("haccp 体系审核与微生物检测", "检测认证"),
    ("宠物行业融资并购观察", "行业信息"),
    ("2026 宠物消费趋势报告", "趋势"),
    ("DeepSeek 大模型在配方研发中的应用", "AI"),
])
def test_classify_hits_each_tag(title, expected):
    assert expected in ledger.classify(title)


def test_classify_fullwidth_and_long_dash():
    # 用户文档里的全角写法必须与半角等价（NFKC + 破折号归一）
    assert "法规标准" in ledger.classify("ＧＢ２８０５０—２０２５ 解读")
    assert "法规标准" in ledger.classify("GB28050-2025 解读")


def test_classify_case_insensitive():
    assert "检测认证" in ledger.classify("HACCP 体系")
    assert "AI" in ledger.classify("ai 排产")


def test_classify_fallback_only_when_nothing_hits():
    assert ledger.classify("今天天气不错，随手拍了几张") == ["其他"]
    assert ledger.classify("") == ["其他"]
    # 命中任何标签时不得混入"其他"
    assert "其他" not in ledger.classify("猫粮配方")


def test_classify_uses_digest_too():
    # 标题太泛，摘要里才有关键词
    assert "添加剂" in ledger.classify("一篇科普", "本文讲防腐剂与抗氧化剂")


def test_auto_tags_written_into_cell(paths):
    row = _add(url=ARTICLE_A, title="猫粮与益生菌")
    tags = ledger.parse_tags_cell(row["信息类型"])
    assert tags[0] == "宠物食品"
    assert "添加剂" in tags


# ------------------------------------------------------------------ 标签合并
def test_manual_tags_merge_with_auto_keep_order(paths):
    row = _add(url=ARTICLE_A, title="猫粮与牛磺酸", tags="添加剂,宠物食品")
    tags = ledger.parse_tags_cell(row["信息类型"])

    assert tags[:2] == ["添加剂", "宠物食品"]      # 手工在前，且按用户给的顺序
    assert len(tags) == len(set(tags))            # 不重复


def test_manual_tags_drop_other_fallback(paths):
    row = _add(url=ARTICLE_A, title="随手拍", tags="行业信息")
    assert ledger.parse_tags_cell(row["信息类型"]) == ["行业信息"]


def test_manual_tag_separators_supported():
    assert ledger.split_tags("宠物食品、添加剂,乳化剂；原料") == [
        "宠物食品", "添加剂", "乳化剂", "原料",
    ]


# ------------------------------------------------------------------ record_key
def test_record_key_prefers_profile_url():
    assert ledger.record_key({"url": ARTICLE_A, "profile_url": PROFILE}) == PROFILE
    assert ledger.record_key({"url": ARTICLE_A}) == ARTICLE_A
    assert ledger.record_key({"文章链接": ARTICLE_A}) == ARTICLE_A
    assert ledger.record_key({"profile_ext网址": PROFILE}) == PROFILE


# ------------------------------------------------------------------ 导出
def test_export_markdown_table(paths):
    md_path = paths[1]
    _add(url=ARTICLE_A, title="甲", tags="宠物食品", note="备注一")
    _add(url=ARTICLE_B, title="乙", tags="添加剂")
    ledger.export_markdown()

    text = md_path.read_text(encoding="utf-8")
    assert "# 文章采集台账" in text
    assert "| " + " | ".join(ledger.COLUMNS) + " |" in text
    assert "## 标签分布" in text
    assert "| 宠物食品 | 1 |" in text and "| 添加剂 | 1 |" in text

    data_rows = [ln for ln in text.splitlines() if ln.startswith("| 1 |") or ln.startswith("| 2 |")]
    assert len(data_rows) == 2


def test_export_markdown_handles_empty_ledger(paths):
    md_path = paths[1]
    ledger.export_markdown()
    text = md_path.read_text(encoding="utf-8")
    assert "（暂无记录）" in text


def test_export_markdown_escapes_pipe_and_newline(paths):
    md_path = paths[1]
    _add(url=ARTICLE_A, title="含|竖线", note="第一行\n第二行")
    ledger.export_markdown()
    text = md_path.read_text(encoding="utf-8")
    assert "含\\|竖线" in text
    assert "第一行<br>第二行" in text


# ------------------------------------------------------------------ CLI
def test_cli_add_end_to_end(paths, capsys):
    code = ledger.main([
        "add", "--url", ARTICLE_A, "--profile-url", PROFILE,
        "--tags", "宠物食品", "--no-fetch",
    ])
    assert code == 0
    rows = ledger.load()
    assert len(rows) == 1
    assert rows[0]["来源渠道"] == "赞和收藏"
    assert rows[0]["profile_ext网址"] == PROFILE
    assert paths[1].exists()                    # add 会顺手刷新 md

    code = ledger.main(["list", "--tag", "宠物食品"])
    assert code == 0
    assert "宠物食品" in capsys.readouterr().out


def test_cli_tags_lists_full_taxonomy(capsys):
    ledger.main(["tags"])
    out = capsys.readouterr().out
    for tag in ledger.TAGS:
        assert tag in out
    assert "其他" in out
