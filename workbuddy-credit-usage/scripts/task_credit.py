#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""任务级成本台账（四字段）。

为什么需要：``node_credit.py --turn`` 的口径是「自最近一条用户消息起的单轮消耗」，
回答不了「这一个任务总共花了多少、其中多少是子 agent 烧的」。而行业实践与本地铁律
都把计量单位从「调用」上移到了「任务」。

四字段定义：
    credits           积分总额（实测，含 subagent 消耗）
    subagent_spawns   子 agent 派发次数（实测，数 function_call.name == 'Agent'）
    retries           重试次数（**无法从日志可靠推断** ⇒ 默认 null:missing，须台账补录）
    human_interventions 人工介入次数（**无法从日志推断** ⇒ 默认 null:missing，须台账补录）

铁律：**缺失字段一律输出 null 并标 missing，禁止填 0 冒充实测**。0 与 unknown 是两件事。

用法：
    python task_credit.py --session <sid> --cwd <cwd>        # 读一个任务的四字段
    python task_credit.py --session <sid> --json             # 机器读
    python task_credit.py --session <sid> --record --retries 3 --human 1   # 补录后两项
    python task_credit.py --session <sid> --record --retries 0 --human 0   # 明确填 0

台账：``~/.workbuddy/skills/workbuddy-credit-usage/ledger/TASK-LEDGER.jsonl``（追加式）

退出码：0 正常 / 2 定位失败 / 3 --record 参数不全
"""

import argparse
import collections
import io
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import node_credit  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(HERE, "ledger", "TASK-LEDGER.jsonl")


def scan(session_file, sid):
    """扫描会话主文件 + subagent 目录，统计积分与调用。"""
    proj = os.path.dirname(session_file)
    paths = [session_file]
    sub_dir = os.path.join(proj, sid)
    if os.path.isdir(sub_dir):
        for root, _dirs, files in os.walk(sub_dir):
            for fn in sorted(files):
                if fn.endswith(".jsonl"):
                    paths.append(os.path.join(root, fn))

    credits = 0.0
    by_source = collections.Counter()
    tool_calls = collections.Counter()
    subagent_spawns = 0
    seen = set()

    for path in paths:
        real = os.path.realpath(path)
        if real in seen:
            continue
        seen.add(real)
        with io.open(path, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                t = d.get("type")
                if t == "credit-usage":
                    pd = d.get("providerData") or {}
                    value = pd.get("credit", d.get("credit"))
                    if isinstance(value, (int, float)):
                        credits += float(value)
                        by_source[pd.get("source") or "unknown"] += 1
                elif t == "function_call":
                    name = d.get("name") or "unknown"
                    tool_calls[name] += 1
                    if name == "Agent":
                        subagent_spawns += 1

    return {
        "credits": round(credits, 2),
        "subagent_spawns": subagent_spawns,
        "tool_calls_total": sum(tool_calls.values()),
        "tool_calls": dict(sorted(tool_calls.items())),
        "credit_records_by_source": dict(sorted(by_source.items())),
    }


def load_ledger(sid):
    """取该会话最后一次补录。返回 None 表示从未补录。"""
    if not os.path.exists(LEDGER):
        return None
    hit = None
    with io.open(LEDGER, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("session") == sid:
                hit = d
    return hit


def append_ledger(rec):
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    with io.open(LEDGER, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default=None, help="会话 sid（或 sid.jsonl）")
    ap.add_argument("--cwd", default=None, help="当前工作目录（用于定位）")
    ap.add_argument("--projects", default=node_credit.DEFAULT_PROJECTS, help="会话日志根目录")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    ap.add_argument("--record", action="store_true", help="把 retries/human 补录进台账")
    ap.add_argument("--retries", type=int, default=None, help="重试次数（补录用）")
    ap.add_argument("--human", type=int, default=None, help="人工介入次数（补录用）")
    ap.add_argument("--note", default=None, help="补录备注")
    args = ap.parse_args()

    try:
        session_file, sid = node_credit.resolve_session(args.projects, args.session, args.cwd)
    except SystemExit as e:
        print(str(e), file=sys.stderr)
        return 2

    stats = scan(session_file, sid)

    if args.record:
        if args.retries is None or args.human is None:
            print("[error] --record 必须同时给 --retries 与 --human（允许 0，但不许省略）", file=sys.stderr)
            return 3
        append_ledger({
            "session": sid,
            "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "credits": stats["credits"],
            "subagent_spawns": stats["subagent_spawns"],
            "retries": args.retries,
            "human_interventions": args.human,
            "note": args.note,
        })
        print("已补录 %s → %s" % (sid, LEDGER))

    ledger = load_ledger(sid)
    out = {
        "session": sid,
        "credits": stats["credits"],
        "subagent_spawns": stats["subagent_spawns"],
        "retries": ledger["retries"] if ledger and "retries" in ledger else None,
        "human_interventions": ledger["human_interventions"] if ledger and "human_interventions" in ledger else None,
        "missing": [k for k in ("retries", "human_interventions")
                    if not (ledger and k in ledger)],
        "measured": {
            "tool_calls_total": stats["tool_calls_total"],
            "tool_calls": stats["tool_calls"],
            "credit_records_by_source": stats["credit_records_by_source"],
        },
    }

    if args.json:
        print(json.dumps(out, ensure_ascii=False, sort_keys=True, indent=2))
    else:
        print("任务成本台账 · %s" % sid)
        print("  credits              %s" % out["credits"])
        print("  subagent_spawns      %s" % out["subagent_spawns"])
        print("  retries              %s" % (out["retries"] if out["retries"] is not None else "missing（未补录）"))
        print("  human_interventions  %s" % (out["human_interventions"] if out["human_interventions"] is not None else "missing（未补录）"))
        print("  工具调用合计 %d %s" % (stats["tool_calls_total"], stats["tool_calls"]))
        if out["missing"]:
            print("  ⚠ 缺 %d 项，补录：--record --retries N --human N" % len(out["missing"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
