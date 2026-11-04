#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`scripts/monthly_rollback.py` 的离线回归测试（纯逻辑，不启 GUI、不联网）。

守什么
------
1. **窗口数学**：月末钳位（3/31 回推 → 2/28 或 2/29）、跨年、闭区间；
2. **闸门**：任何号没采完当前月，窗口不许前移（这是用户口径的核心）；
3. **重试与阻塞**：失败重试到上限就阻塞，阻塞 ≠ 跳过 ≠ 推窗；
4. **刹车**：max_windows / stop_before 到线就停，不无限回溯；
5. **状态文件**：原子写、版本校验、未知窗口不被静默接受。

跑法（必须用装了 pytest 的解释器）：
  C:/Users/Administrator/.workbuddy/binaries/python/envs/default/Scripts/python.exe \
      -m pytest tests/test_monthly_rollback.py -q
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))

import monthly_rollback as mr  # noqa: E402


@pytest.fixture
def accounts():
    return [{"name": "饮食A", "article_url": "https://mp.weixin.qq.com/s/a"},
            {"name": "饮食B", "article_url": "https://mp.weixin.qq.com/s/b"}]


@pytest.fixture
def state(accounts):
    """已开窗的状态。

    `mark_task` 会校验窗口存在（不静默接受未知窗口），所以测试从"run 已经
    走出第一步"的现场开始——真实流程里窗口也是 next_task 落出来的。
    """
    s = mr.new_state(accounts, anchor=date(2026, 11, 1))
    mr.next_task(s)
    return s


# ---------------------------------------------------------------- 窗口数学
def test_shift_months_clamps_month_end():
    """3/31 回推一个月不能抛异常，要落在 2 月最后一天。"""
    assert mr.shift_months(date(2026, 3, 31), -1) == date(2026, 2, 28)
    assert mr.shift_months(date(2024, 3, 31), -1) == date(2024, 2, 29)


def test_shift_months_crosses_year():
    assert mr.shift_months(date(2026, 1, 15), -1) == date(2025, 12, 15)
    assert mr.shift_months(date(2026, 12, 15), 1) == date(2027, 1, 15)
    assert mr.shift_months(date(2026, 11, 1), -12) == date(2025, 11, 1)
    assert mr.shift_months(date(2026, 11, 1), -26) == date(2024, 9, 1)


def test_days_in_month():
    assert mr.days_in_month(2026, 2) == 28
    assert mr.days_in_month(2024, 2) == 29
    assert mr.days_in_month(2026, 12) == 31
    assert mr.days_in_month(2026, 4) == 30


def test_window_bounds_rolling_is_back_to_back():
    """rolling：W0 是最近一个月，W1 紧接往前，且边界日重叠一天（宁可重不漏）。"""
    anchor = date(2026, 11, 1)
    assert mr.window_bounds(anchor, 0, "rolling") == (date(2026, 10, 1), date(2026, 11, 1))
    assert mr.window_bounds(anchor, 1, "rolling") == (date(2026, 9, 1), date(2026, 10, 1))
    assert mr.window_bounds(anchor, 2, "rolling") == (date(2026, 8, 1), date(2026, 9, 1))
    # 重叠一天：W0.start_of_prev == W1.end
    assert mr.window_bounds(anchor, 1, "rolling")[1] == mr.window_bounds(anchor, 0, "rolling")[0]


def test_window_bounds_rolling_from_month_end_anchor():
    """anchor 落在 31 号时窗口不能崩：每一天都要是真实存在的日期。"""
    start, end = mr.window_bounds(date(2026, 3, 31), 0, "rolling")
    assert end == date(2026, 3, 31)
    assert start == date(2026, 2, 28)


def test_window_bounds_calendar():
    anchor = date(2026, 11, 1)
    assert mr.window_bounds(anchor, 0, "calendar") == (date(2026, 11, 1), date(2026, 11, 1))
    assert mr.window_bounds(anchor, 1, "calendar") == (date(2026, 10, 1), date(2026, 11, 1))
    assert mr.window_bounds(anchor, 2, "calendar") == (date(2026, 9, 1), date(2026, 10, 1))


def test_window_bounds_rejects_bad_input():
    with pytest.raises(ValueError):
        mr.window_bounds(date(2026, 11, 1), -1)
    with pytest.raises(ValueError):
        mr.window_bounds(date(2026, 11, 1), 0, "quarterly")


def test_parse_date_accepts_both_separators():
    assert mr.parse_date("2026-09-01") == date(2026, 9, 1)
    assert mr.parse_date("2026/09/01") == date(2026, 9, 1)
    with pytest.raises(ValueError):
        mr.parse_date("2026年9月")


# ---------------------------------------------------------------- 初始化与状态文件
def test_new_state_rejects_duplicate_accounts(accounts):
    with pytest.raises(ValueError):
        mr.new_state([accounts[0], dict(accounts[0])], anchor=date(2026, 11, 1))


def test_new_state_rejects_empty_accounts():
    with pytest.raises(ValueError):
        mr.new_state([], anchor=date(2026, 11, 1))


def test_state_roundtrip_is_atomic(tmp_path, state):
    path = tmp_path / "state.json"
    mr.save_state(path, state)
    assert path.is_file()
    assert not (tmp_path / "state.json.tmp").exists()   # 临时文件必须被 replace 掉
    again = mr.load_state(path)
    assert again["anchor"] == "2026-11-01"
    assert [a["name"] for a in again["accounts"]] == ["饮食A", "饮食B"]


def test_load_state_rejects_version_mismatch(tmp_path, state):
    path = tmp_path / "state.json"
    state["version"] = 99
    path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError):
        mr.load_state(path)


def test_load_state_missing_file_gives_actionable_error(tmp_path):
    with pytest.raises(FileNotFoundError) as exc:
        mr.load_state(tmp_path / "nope.json")
    assert "init" in str(exc.value)


# ---------------------------------------------------------------- 闸门状态机
def test_first_next_opens_window_one(accounts):
    state = mr.new_state(accounts, anchor=date(2026, 11, 1))
    task, why = mr.next_task(state)
    assert why.startswith("pending:")
    assert task["window"] == "W0001"
    assert task["account"] == "饮食A"
    assert state["windows"][0]["start"] == "2026-10-01"
    assert state["windows"][0]["end"] == "2026-11-01"


def test_window_does_not_advance_until_every_account_done(state):
    """核心口径：A 采完这个月后，必须先检查 B；B 没完就不许推窗。"""
    mr.mark_task(state, "W0001", "饮食A", "done", md_new=12)
    assert mr.window_progress(state, "W0001")["complete"] is False
    assert state["windows"][0]["status"] == "active"

    task, _ = mr.next_task(state)
    assert task["account"] == "饮食B"          # 仍在同一窗口
    assert task["window"] == "W0001"


def test_window_advances_after_all_accounts_done(state):
    mr.mark_task(state, "W0001", "饮食A", "done", md_new=12)
    mr.mark_task(state, "W0001", "饮食B", "done", md_new=7)
    assert state["windows"][0]["status"] == "completed"

    task, _ = mr.next_task(state)
    assert task["window"] == "W0002"
    assert task["account"] == "饮食A"
    win2 = state["windows"][1]
    assert (win2["start"], win2["end"]) == ("2026-09-01", "2026-10-01")


def test_failure_is_retried_not_skipped(state):
    """同窗内先补齐所有 pending，再回头重试失败的号——失败不推窗、也不顶掉别人。"""
    mr.mark_task(state, "W0001", "饮食A", "failed", detail="rc=3")
    task, why = mr.next_task(state)
    assert task["account"] == "饮食B"           # B 还 pending，先让它跑完
    assert why.startswith("pending:")

    mr.mark_task(state, "W0001", "饮食B", "done", md_new=4)
    task, why = mr.next_task(state)
    assert task["account"] == "饮食A"           # 现在才回头重试 A
    assert why.startswith("retry:")
    assert task["attempts"] == 1


def test_failure_after_max_attempts_blocks_without_advancing(state):
    state["max_attempts"] = 2
    mr.mark_task(state, "W0001", "饮食A", "done", md_new=3)
    for _ in range(2):
        mr.mark_task(state, "W0001", "饮食B", "failed", detail="rc=3")
    task, why = mr.next_task(state)
    assert task is None
    assert why.startswith("blocked:")
    assert "饮食B" in why
    # 关键：阻塞 ≠ 推窗，窗口必须停在原地
    assert state["windows"][0]["status"] == "active"
    assert len(state["windows"]) == 1


def test_blocked_account_does_not_stall_other_accounts(state):
    """B 卡住了，A 下一窗仍不该偷偷开——但同窗里 A 的 pending 要先跑完。"""
    state["max_attempts"] = 1
    mr.mark_task(state, "W0001", "饮食B", "failed", detail="rc=3")
    task, why = mr.next_task(state)
    assert task["account"] == "饮食A" and why.startswith("pending:")
    mr.mark_task(state, "W0001", "饮食A", "done", md_new=1)
    task, why = mr.next_task(state)
    assert task is None and why.startswith("blocked:")


def test_max_windows_stops_backtracking(accounts):
    state = mr.new_state(accounts, anchor=date(2026, 11, 1), max_windows=2)
    mr.next_task(state)                 # 先落出 W0001
    for _ in range(2):
        win = state["windows"][-1]
        for acct in ("饮食A", "饮食B"):
            mr.mark_task(state, win["id"], acct, "done", md_new=1)
        mr.next_task(state)             # 触发开下一窗/判定收尾
    task, why = mr.next_task(state)
    assert task is None and why == "all_done"
    assert len(state["windows"]) == 2


def test_stop_before_blocks_window_creation(accounts):
    """下限卡在 W0002 起点之后 ⇒ W0002 根本开不出来（不是"开出来再丢掉"）。"""
    state = mr.new_state(accounts, anchor=date(2026, 11, 1),
                         stop_before="2026-09-15")
    mr.next_task(state)                 # 先落出 W0001（10-01~11-01，起点合法）
    for acct in ("饮食A", "饮食B"):
        mr.mark_task(state, "W0001", acct, "done", md_new=1)
    task, why = mr.next_task(state)
    assert task is None
    assert why == "all_done"
    assert len(state["windows"]) == 1


def test_mark_rejects_unknown_window(state):
    mr.next_task(state)                       # 先落出 W0001
    with pytest.raises(ValueError):
        mr.mark_task(state, "W9999", "饮食A", "done")


def test_mark_rejects_bad_status(state):
    mr.next_task(state)
    with pytest.raises(ValueError):
        mr.mark_task(state, "W0001", "饮食A", "skipped")


def test_rewind_resets_window(accounts, tmp_path):
    """rewind 走真实 CLI 函数：窗口回 active、所有任务回 pending、重试计数清零。"""
    state = mr.new_state(accounts, anchor=date(2026, 11, 1))
    mr.next_task(state)
    mr.mark_task(state, "W0001", "饮食A", "done", md_new=5)
    mr.mark_task(state, "W0001", "饮食B", "done", md_new=5)
    assert state["windows"][0]["status"] == "completed"

    path = tmp_path / "s.json"
    mr.save_state(path, state)
    rc = mr.cmd_rewind(argparse.Namespace(state=str(path), window="W0001"))
    assert rc == 0

    reloaded = mr.load_state(path)
    win = reloaded["windows"][0]
    assert win["status"] == "active" and "completed_at" not in win
    for acct in ("饮食A", "饮食B"):
        t = mr.task_of(reloaded, "W0001", acct)
        assert t["status"] == "pending" and t["attempts"] == 0
    task, _ = mr.next_task(reloaded)
    assert task["window"] == "W0001" and task["account"] == "饮食A"


def test_rewind_rejects_unknown_window(accounts, tmp_path):
    state = mr.new_state(accounts, anchor=date(2026, 11, 1))
    path = tmp_path / "s.json"
    mr.save_state(path, state)
    rc = mr.cmd_rewind(argparse.Namespace(state=str(path), window="W9999"))
    assert rc == mr.EXIT_PARAM


def test_progress_counts():
    accounts = [{"name": "A", "article_url": ""}, {"name": "B", "article_url": ""}]
    state = mr.new_state(accounts, anchor=date(2026, 11, 1))
    mr.next_task(state)
    mr.mark_task(state, "W0001", "A", "done", md_new=2)
    mr.mark_task(state, "W0001", "B", "failed")
    p = mr.window_progress(state, "W0001")
    assert p["done"] == ["A"] and p["failed"] == ["B"] and p["pending"] == []
    assert p["complete"] is False and p["total"] == 2


# ---------------------------------------------------------------- 命令组装
def test_build_clicker_cmd_carries_custom_range():
    cmd = mr.build_clicker_cmd("py.exe", "2026-09-01", "2026-10-01",
                              "https://mp.weixin.qq.com/s/abc")
    assert "RANGE=custom" in cmd
    assert "DATE_START=2026-09-01" in cmd
    assert "DATE_END=2026-10-01" in cmd
    assert "ARTICLE_URL=https://mp.weixin.qq.com/s/abc" in cmd
    assert "--yes" in cmd


def test_build_clicker_cmd_omits_empty_url():
    cmd = mr.build_clicker_cmd("py.exe", "2026-09-01", "2026-10-01", "")
    assert not any(c.startswith("ARTICLE_URL=") for c in cmd)


def test_windows_are_created_lazily(accounts):
    """init 之后不该预先塞一堆窗口：状态只描述真实发生过的事。"""
    state = mr.new_state(accounts, anchor=date(2026, 11, 1))
    assert state["windows"] == []
    mr.next_task(state)
    assert len(state["windows"]) == 1
