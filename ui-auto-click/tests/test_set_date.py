#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`clicker.set_date` 的离线回归测试（纯函数，不点任何控件）。

守什么
------
1. 日期写法收敛：`2026-9-1` / `2026/09/01` / `20260901` 都要变成控件认的
   `2026/09/01` —— 写入与回读比较共用同一个函数，才不会"写进去 2026/9/1、
   回读 2026/09/01"被判成假失败；
2. 非法输入一律返回空串（由调用方抛错），绝不猜一个日期出来；
3. `set_date` 必须在 _ACTIONS 里注册，否则 profile 会在运行时才炸。

真机取证（2026-11-01）：日期框是 QDateEdit(Qt)，ValuePattern.SetValue 假成功、
逐字符 keybd_event 被吞，唯一可行通道是「点击 → Ctrl+A → Ctrl+V」；
本文件只测它的字符串处理那一半，GUI 那一半靠 profile 的真机跑验证。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))

import clicker  # noqa: E402


@pytest.mark.parametrize("raw,expected", [
    ("2026-09-01", "2026/09/01"),
    ("2026/09/01", "2026/09/01"),
    ("2026-9-1", "2026/09/01"),
    ("20260901", "2026/09/01"),
    ("  2026-09-01  ", "2026/09/01"),
    ("2026年9月1日", "2026/09/01"),      # \D 分隔容忍中文年月日
])
def test_canon_date_accepts_common_forms(raw, expected):
    assert clicker._canon_date(raw) == expected


@pytest.mark.parametrize("raw", ["", None, "随便", "2026-13-01", "2026-00-05",
                                "2026-01-32", "1899-01-01", "2026-01"])
def test_canon_date_rejects_nonsense(raw):
    """认不出就返回空串：宁可在调用方抛错，也不猜一个日期写到控件里。"""
    assert clicker._canon_date(raw) == ""


def test_date_is_registered_action():
    assert "set_date" in clicker._ACTIONS


def test_canon_date_pads_single_digits():
    """回读比较全靠它：1 月 1 日必须和控件里的 2000/01/01 对得上。"""
    assert clicker._canon_date("2000-1-1") == "2000/01/01"
