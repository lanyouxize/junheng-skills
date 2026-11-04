#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WorkBuddy 本节点消耗积分（官方 credit）读取工具。

数据源 : ~/.workbuddy/projects/**/*.jsonl
字段口径: providerData.rawUsage.credit  —— 官方积分，与 App「套餐与用量」账单同源
基准实现: github.com/majiabin2020/workbuddy-token-dashboard 的 grab()（官方 credit 口径）

用法:
  python node_credit.py                # 当前会话累计消耗积分（人读）
  python node_credit.py --json         # 机器可读 JSON
  python node_credit.py --turn         # 单次读数：自最近一条用户消息起（本轮）的消耗
  python node_credit.py --turn --gate  # 单次读数 + 节点熔断机检（超阈值退出码 1）
  python node_credit.py --selftest     # 自证（每条判据都必须能失败）
  python node_credit.py --mark         # 任务开始：记录基线快照（默认按会话隔离存储）
  python node_credit.py --delta        # 任务结束：读自基线增量（并并列给出与 App 同口径的单轮值）
  python node_credit.py --session SID  # 指定会话（sid 或 sid.jsonl）
  python node_credit.py --projects DIR # 指定日志根目录（默认 ~/.workbuddy/projects）
  python node_credit.py --model        # 附逐模型积分拆分
  python node_credit.py --report --report-days 7 --report-out out.csv  # 普通档：近 N 天 日/项目/模型 积分趋势 CSV

说明:
  - 「当前会话」= projects/<项目>/<sid>.jsonl 中 mtime 最新的一个（正在被写入者）；
    其 <sid>/subagents/** 的子代理用量一并计入。
  - credit 为 None 的请求（老格式）不计入积分，但仍计入 token。
  - --mark / --delta 默认按会话隔离基线（.node_credit_baseline.<sid>.json），多窗口并发互不覆盖；
    旧共享基线（.node_credit_baseline.json）在同会话时自动兼容读取。
  - --turn 与 App 消息下方「共消耗」同口径（自最近一条用户消息起），已逐值校验（2026-10-13）。
  - 口径对照（2026-10-14 修正）：App「共消耗」是「单轮」口径 = 自最近一条用户消息起；
    --mark/--delta 是「累计差」口径，若 mark 落在轮中或跨轮，会系统性偏高（实测 7.06 vs 真值 4.94）。
    故 --delta 现并列输出 node_turn_credit，并在检测到跨轮时告警；单轮实测优先用 --turn。
  - 铁律③（节点熔断）：节点以 30 积分为界；节点末尾必跑 --turn，且须 --session 显式指定。
    --turn 现输出三档阈值判定（turn_threshold=30 / turn_warn=25 / turn_state=ok|warn|over / turn_within_threshold / turn_verdict）；
    warn 档（25~30）提示收尾但仍可续，over 档（>30）才触发 --gate 退出码 1（供门禁分支）。
  - --report 离线 CSV 周报：近 N 天按 日/项目/模型 拆解积分趋势（普通档新增，纯统计、零依赖）。
  - --turn 人类可读前两行是 credit_delta.py 的解析契约（积分/锚点/请求数三条正则），
    改动格式会静默破坏差值记账——selftest 第 7 组合同断言即守卫此事。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import time

DEFAULT_PROJECTS = os.path.join(os.path.expanduser("~"), ".workbuddy", "projects")
DEFAULT_BASELINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".node_credit_baseline.json")
NODE_LIMIT = 30  # 铁律③：节点以 30 积分为界
NODE_WARN = 25   # 普通档：软限预警（节点接近上限时提示收尾，非硬熔断）


def grab(o):
    """从一条日志记录中提取 usage；无有效 usage 返回 None。口径对齐 workbuddy-token-dashboard。"""
    pd = o.get("providerData")
    if not isinstance(pd, dict):
        return None
    ru = pd.get("rawUsage") or {}
    u = pd.get("usage") or {}
    tt = ru.get("total_tokens") or u.get("totalTokens")
    if not tt:
        return None
    c = ru.get("credit")
    return {
        "ts": o.get("timestamp") or 0,
        "total": int(tt),
        "input": int(ru.get("prompt_tokens") or u.get("inputTokens") or 0),
        "output": int(ru.get("completion_tokens") or u.get("outputTokens") or 0),
        "credit": float(c) if isinstance(c, (int, float)) else None,
        "model": pd.get("model") or pd.get("requestModelId") or pd.get("requestModelName") or "unknown",
    }


def cwd_to_projdir(cwd):
    """把工作目录映射为 projects/ 下的目录名：D:\\a\\b -> d-a-b（WorkBuddy 口径）。"""
    if not cwd:
        return None
    p = os.path.abspath(cwd).replace("\\", "/")
    if len(p) >= 2 and p[1] == ":":
        return p[0].lower() + "-" + p[2:].strip("/").replace("/", "-")
    return None


def find_current_session(projects, cwd=None):
    """返回 (session_jsonl_path, sid, projdir)。

    优先在「当前 cwd 对应的项目目录」内取 mtime 最新会话——多开 WorkBuddy 窗口时
    多个会话在并发写入，全局取 mtime 最新会串台到别的项目。目录不存在时回退全局最新。
    """
    projdir = cwd_to_projdir(cwd)
    if projdir:
        cand = glob.glob(os.path.join(projects, projdir, "*.jsonl"))
        if cand:
            newest = max(cand, key=os.path.getmtime)
            return newest, os.path.splitext(os.path.basename(newest))[0], projdir
    files = glob.glob(os.path.join(projects, "*", "*.jsonl"))
    if not files:
        return None, None, None
    newest = max(files, key=os.path.getmtime)
    return newest, os.path.splitext(os.path.basename(newest))[0], None


def resolve_session(projects, session, cwd=None):
    """按 --session 或自动探测定位会话文件。"""
    if session:
        sid = session[:-6] if session.endswith(".jsonl") else session
        projdir = cwd_to_projdir(cwd)
        hits = glob.glob(os.path.join(projects, projdir, sid + ".jsonl")) if projdir else []
        if not hits:
            hits = glob.glob(os.path.join(projects, "*", sid + ".jsonl"))
        if not hits:
            sys.exit("[error] 未找到会话 %s 的日志文件（在 %s 下）" % (sid, projects))
        return hits[0], sid
    path, sid, _ = find_current_session(projects, cwd)
    if not path:
        sys.exit("[error] %s 下没有任何会话日志" % projects)
    return path, sid


def collect(session_file, sid):
    """收集会话自身 + 其 subagents 目录下全部 jsonl 的 usage 记录。"""
    proj = os.path.dirname(session_file)
    session_dir = os.path.join(proj, sid)
    paths = [session_file]
    if os.path.isdir(session_dir):
        paths += glob.glob(os.path.join(session_dir, "**", "*.jsonl"), recursive=True)
    seen, recs = set(), []
    for p in paths:
        rp = os.path.realpath(p)
        if rp in seen:
            continue
        seen.add(rp)
        try:
            with open(p, encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    if '"rawUsage"' not in line and '"usage"' not in line:
                        continue
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        o = json.loads(line)
                    except Exception:
                        continue
                    r = grab(o)
                    if r:
                        recs.append(r)
        except OSError:
            continue
    return recs


def summarize(recs):
    credit = 0.0
    n_credit = 0
    tot = inp = out = 0
    per_model = {}
    for r in recs:
        tot += r["total"]
        inp += r["input"]
        out += r["output"]
        if r["credit"] is not None:
            credit += r["credit"]
            n_credit += 1
            per_model[r["model"]] = per_model.get(r["model"], 0.0) + r["credit"]
    return {
        "requests": len(recs),
        "credit_requests": n_credit,
        "credit": round(credit, 4),
        "total_tokens": tot,
        "input_tokens": inp,
        "output_tokens": out,
        "per_model_credit": {k: round(v, 4) for k, v in sorted(per_model.items(), key=lambda kv: -kv[1])},
    }


def load_baseline(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def turn_window(recs, t0):
    """本轮窗口：ts >= t0 的记录。t0 缺失/为 0 → 空窗。

    fail-closed：定位不到本轮起点时返回空窗（0 分），而不是把全会话当本轮——
    「不知道起点」和「本轮没消耗」必须可区分，调用方靠 turn_requests 识别。
    """
    if not t0:
        return []
    return [r for r in recs if r["ts"] and r["ts"] >= t0]


def turn_credit_of(win):
    """窗口内积分合计。credit 为 None 的老格式请求不计分（与 summarize 同口径）。"""
    return round(sum(r["credit"] for r in win if r["credit"] is not None), 4)


def threshold_verdict(credit, limit=NODE_LIMIT):
    """节点熔断判据（铁律③）：> limit 即超限。返回 (within, 文本)。

    边界口径：恰等于阈值算未超（<=），与 2026-10-14 起 --delta 的既有行为一致。
    """
    within = credit <= limit
    return within, ("未超，可续" if within else "超限：本节点结束、任务内开启下一节点")


def verdict_level(credit, warn=NODE_WARN, limit=NODE_LIMIT):
    """三档节点判定（普通档新增软限）：<=warn 正常 / warn~limit 预警(建议收尾) / >limit 超限(熔断)。

    返回 (level, within_limit, text)：
      level:        'ok' | 'warn' | 'over'
      within_limit: 是否未硬超限（--gate 仅 over 时返回 False，warn 不算熔断）
    口径边界：恰等于软限/硬限都按较低档（25->ok、30->warn 未硬超），与 threshold_verdict(<=limit) 一致。
    """
    if credit > limit:
        return "over", False, "超限：本节点结束、任务内开启下一节点"
    if credit > warn:
        return "warn", True, "接近节点上限（软限 %d）：建议本节点收尾、准备开下一节点" % warn
    return "ok", True, "未超，可续"


def render_turn(tc, t0_str, n, sid, cum, vtext):
    """--turn 的人类可读输出（四行）。

    前两行是 credit_delta.py 的解析契约（积分/锚点/请求数三条正则）——
    selftest 直接消费本函数做合同断言；改格式必须让 selftest 转红，不允许静默漂移。
    """
    return [
        "本轮（单次）消耗积分: %.2f" % tc,
        "  自最近一条用户消息起（%s） | 请求 %d 个" % (t0_str, n),
        "  会话 %s | 累计 %.2f" % (sid, cum),
        "  节点阈值 %d → %s" % (NODE_LIMIT, vtext),
    ]


def selftest():
    """自证：每条判据都必须能失败（从不失败的检查器＝没有检查器）。"""
    fails = []
    n = 0

    def check(cond, msg):
        nonlocal n
        n += 1
        if not cond:
            fails.append(msg)

    # 1. 窗口 fail-closed：定位不到本轮起点 → 空窗，而不是把全会话当本轮
    check(turn_window([{"ts": 5, "credit": 1.0}], 0) == [], "t0=0 未返回空窗（会把全会话计成本轮）")
    # 2. 窗口过滤：早于 t0 的记录不计入
    check(turn_window([{"ts": 5, "credit": 1.0}, {"ts": 9, "credit": 2.0}], 7)
          == [{"ts": 9, "credit": 2.0}], "窗口未滤掉旧记录")
    # 3. credit 为 None 不计分
    check(turn_credit_of([{"ts": 1, "credit": None}, {"ts": 2, "credit": 1.5}]) == 1.5,
          "None credit 被计分")
    # 4. 边界：恰等于阈值算未超（与 --delta 历史口径 <= 一致，防止口径漂移）
    check(threshold_verdict(30.0)[0] is True, "恰 30 分被判超限（口径漂移）")
    # 5. 超限：30.01 必须判超（熔断失职是最贵的漏报）
    check(threshold_verdict(30.01)[0] is False, "30.01 分未判超限（熔断失职）")
    check(threshold_verdict(0.0)[0] is True, "0 分被判超限")
    check(threshold_verdict(31.0)[1].startswith("超限"), "超限文案缺失")
    # 6. grab：无 usage 不编记录；缺 credit 必须显式 None（不得静默当 0）
    check(grab({}) is None, "空记录未被拒")
    ok_rec = grab({"providerData": {"rawUsage": {"total_tokens": 10}}})
    check(ok_rec is not None, "有效 usage 被拒")
    check(ok_rec is not None and ok_rec["credit"] is None, "缺 credit 未标 None")
    # 7. 合同断言：render_turn 前两行是 credit_delta.py 的解析契约，格式不许漂移。
    #    必须消费真实渲染函数（曾犯过错：selftest 自己硬编码一份文本，变异真代码它看不见——
    #    证伪驱动 M3 当场抓获，橡皮图章）。此处对真实函数输出打正则。
    lines = render_turn(7.92, "10-17 18:07:00", 27, "sid", 41.73, "未超，可续")
    check(re.search(r"消耗积分[:：]\s*([0-9]+(?:\.[0-9]+)?)", lines[0]) is not None,
          "合同行1 不再匹配 credit_delta 的积分正则")
    check(re.search(r"自最近一条用户消息起[（(]([^）)]+)[）)]", lines[1]) is not None,
          "合同行2 不再匹配 credit_delta 的锚点正则")
    check(re.search(r"请求\s*(\d+)\s*个", lines[1]) is not None,
          "合同行2 不再匹配 credit_delta 的请求数正则")
    # 8. 三档判定（普通档软限 25 / 硬限 30）：边界不得漂移
    check(verdict_level(24.0)[0] == "ok", "24 分未判 ok")
    check(verdict_level(25.0)[0] == "ok", "恰 25 分误判 warn（边界漂移）")
    check(verdict_level(25.01)[0] == "warn", "25.01 分未判 warn（软限漏报）")
    check(verdict_level(27.0)[0] == "warn", "27 分未判 warn（软限漏报）")
    check(verdict_level(30.0)[0] == "warn", "恰 30 分未判 warn（未硬超，应在软限顶）")
    check(verdict_level(30.01)[0] == "over", "30.01 分未判 over（熔断失职）")
    check(verdict_level(31.0)[1] is False, "over 时 within 未 False（--gate 会失效）")
    check(verdict_level(0.0)[0] == "ok", "0 分误判")

    for f in fails:
        print("  FAIL " + f)
    print(f'selftest: {"PASS" if not fails else "FAIL"}（{n - len(fails)}/{n}）')
    return 0 if not fails else 1


def fmt_ts(ms):
    try:
        return time.strftime("%m-%d %H:%M:%S", time.localtime(ms / 1000))
    except Exception:
        return str(ms)


def last_user_turn_ts(session_file):
    """返回会话文件中最近一条「真正用户消息」的时间戳（ms）；没有则返回 0。"""
    last = 0
    try:
        with open(session_file, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                if "startsNewUserRequest" not in line:
                    continue
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                pd = o.get("providerData")
                if isinstance(pd, dict) and pd.get("startsNewUserRequest") is True:
                    ts = o.get("timestamp") or 0
                    if ts > last:
                        last = ts
    except OSError:
        pass
    return last


def generate_report(projects, days, session=None, cwd=None, out_path=None):
    """普通档新增：离线 CSV 周报——按「日 / 项目 / 模型」拆解近 N 天积分趋势。

    纯统计、零新增依赖；输出到 out_path 或 stdout。与单会话读取同源（providerData.rawUsage.credit）。
    用途：把「单点熔断读数」升级为「趋势可观测」——对标开源 codeburn/ccusage 的按维度拆解，
    但不建看板（普通档只给 CSV，看板留待最佳档）。
    """
    cutoff = (time.time() * 1000) - days * 86400 * 1000
    if session:
        sid = session[:-6] if session.endswith(".jsonl") else session
        projdir = cwd_to_projdir(cwd)
        files = glob.glob(os.path.join(projects, projdir, sid + ".jsonl")) if projdir else []
        if not files:
            files = glob.glob(os.path.join(projects, "*", sid + ".jsonl"))
    else:
        files = glob.glob(os.path.join(projects, "*", "*.jsonl"))
    if not files:
        sys.exit("[error] 未找到任何会话日志（projects=%s）" % projects)
    rows = {}
    for f in files:
        proj = os.path.basename(os.path.dirname(f))
        sid_f = os.path.splitext(os.path.basename(f))[0]
        for r in collect(f, sid_f):
            if not r["ts"] or r["ts"] < cutoff:
                continue
            d = time.strftime("%Y-%m-%d", time.localtime(r["ts"] / 1000))
            key = (d, proj, r["model"])
            agg = rows.get(key)
            if agg is None:
                agg = [0, 0.0, 0]
                rows[key] = agg
            agg[0] += 1
            if r["credit"] is not None:
                agg[1] += r["credit"]
            agg[2] += r["total"]
    header = "date,project,model,requests,credit,total_tokens\n"
    out = [header]
    for (d, proj, model) in sorted(rows.keys()):
        a = rows[(d, proj, model)]
        out.append("%s,%s,%s,%d,%.2f,%d\n" % (d, proj, model, a[0], a[1], a[2]))
    csv_text = "".join(out)
    if out_path:
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(csv_text)
        print("周报已写出: %s（近 %d 天，%d 行明细）" % (out_path, days, len(rows)))
    else:
        sys.stdout.write(csv_text)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorkBuddy 本节点消耗积分（官方 credit）读取")
    ap.add_argument("--projects", default=DEFAULT_PROJECTS, help="会话日志根目录（默认 ~/.workbuddy/projects）")
    ap.add_argument("--session", default=None, help="指定会话 sid（或 sid.jsonl）")
    ap.add_argument("--cwd", default=None, help="当前工作目录（用于定位本任务会话；默认系统 cwd）")
    ap.add_argument("--baseline", default=DEFAULT_BASELINE, help="基线文件路径")
    ap.add_argument("--mark", action="store_true", help="记录基线快照（任务开始时用）")
    ap.add_argument("--delta", action="store_true", help="读自基线增量（任务结束时用；并列给出单轮口径）")
    ap.add_argument("--turn", action="store_true", help="单次读数：自最近一条用户消息起（本轮）的消耗")
    ap.add_argument("--gate", action="store_true", help="--turn 专用：超节点阈值时退出码 1（机检熔断）")
    ap.add_argument("--model", action="store_true", help="附逐模型积分拆分")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--selftest", action="store_true", help="自证：每条判据都必须能失败")
    ap.add_argument("--report", action="store_true", help="生成近 N 天积分趋势 CSV 周报（按 日/项目/模型 拆解）")
    ap.add_argument("--report-days", type=int, default=7, help="--report 统计天数（默认 7）")
    ap.add_argument("--report-out", default=None, help="--report 输出文件路径（默认打印到 stdout）")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    projects = os.path.expanduser(args.projects)
    if not os.path.isdir(projects):
        sys.exit("[error] 日志目录不存在: %s" % projects)

    cwd = args.cwd or os.getcwd()
    session_file, sid = resolve_session(projects, args.session, cwd)
    projdir = cwd_to_projdir(cwd)
    scope_warn = None
    if projdir and os.path.basename(os.path.dirname(session_file)) != projdir:
        scope_warn = ("会话 %s 不在当前项目目录 %s 内——多窗口并发时可能串台，"
                      "建议用 --session 显式指定" % (sid, projdir))
    recs = collect(session_file, sid)
    s = summarize(recs)

    result = {
        "session": sid,
        "session_file": session_file,
        "projects": projects,
        "cwd": cwd,
        "project_dir": projdir,
        "scope_warn": scope_warn,
        "session_credit": s["credit"],
        "requests": s["requests"],
        "credit_requests": s["credit_requests"],
        "total_tokens": s["total_tokens"],
        "input_tokens": s["input_tokens"],
        "output_tokens": s["output_tokens"],
        "per_model_credit": s["per_model_credit"],
        "generated_at": int(time.time() * 1000),
    }

    if args.turn:
        t0 = last_user_turn_ts(session_file)
        if not t0:
            sys.exit("[error] 未找到用户消息标记（startsNewUserRequest），无法定位本轮起点")
        win = turn_window(recs, t0)
        tc = turn_credit_of(win)
        level, within, vtext = verdict_level(tc)
        result["turn_start_ts"] = t0
        result["turn_start"] = fmt_ts(t0)
        result["turn_credit"] = tc
        result["turn_requests"] = len(win)
        result["turn_credit_requests"] = sum(1 for r in win if r["credit"] is not None)
        result["turn_threshold"] = NODE_LIMIT
        result["turn_warn"] = NODE_WARN
        result["turn_state"] = level
        result["turn_within_threshold"] = within
        result["turn_verdict"] = vtext
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            for ln in render_turn(tc, fmt_ts(t0), len(win), sid, s["credit"], vtext):
                print(ln)
            if level == "warn":
                print("  [预警] 已达软限 %d，强烈建议本节点收尾后再开新节点（硬限 %d）" % (NODE_WARN, NODE_LIMIT))
        if args.gate and not within:
            return 1
        return 0

    # 默认基线按会话隔离，避免多窗口并发互相覆盖（2026-10-13 竞态修复）
    if args.baseline == DEFAULT_BASELINE:
        baseline_path = DEFAULT_BASELINE[:-5] + "." + sid + ".json"
    else:
        baseline_path = args.baseline

    if args.mark and not args.delta:
        base = {"session": sid, "credit": s["credit"], "ts": result["generated_at"],
                "turn_ts": last_user_turn_ts(session_file)}
        with open(baseline_path, "w", encoding="utf-8") as fh:
            json.dump(base, fh, ensure_ascii=False, indent=2)
        result["baseline_marked"] = base
        result["baseline_file"] = baseline_path
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print("基线已记录（会话 %s）: 累计积分 = %.2f" % (sid, s["credit"]))
            print("基线文件: %s" % baseline_path)
        return 0

    if args.delta:
        base = load_baseline(baseline_path)
        if base is None and baseline_path != args.baseline:
            legacy = load_baseline(args.baseline)
            if legacy and legacy.get("session") == sid:
                base = legacy
        if not base:
            sys.exit("[error] 未找到基线，请先在任务开始处运行 --mark。基线文件: %s" % baseline_path)
        result["baseline_file"] = baseline_path
        if base.get("session") and base["session"] != sid:
            result["baseline_session_mismatch"] = base["session"]
        delta = round(s["credit"] - float(base.get("credit", 0.0)), 4)
        result["baseline"] = base
        result["node_delta_credit"] = delta
        # 单轮（本节点）口径：自最近一条用户消息起 —— 与 App 消息下「共消耗」同源同值。
        # 累计差 delta 会因 mark 时机落在轮中/跨轮而系统性偏高，故并列给出单轮值供对照（2026-10-14）。
        cur_turn_ts = last_user_turn_ts(session_file)
        turn_win = [r for r in recs if r["ts"] and r["ts"] >= cur_turn_ts] if cur_turn_ts else []
        turn_credit = round(sum(r["credit"] for r in turn_win if r["credit"] is not None), 4)
        result["node_turn_credit"] = turn_credit
        base_turn = base.get("turn_ts")
        crossed = bool(base_turn and cur_turn_ts and base_turn != cur_turn_ts)
        result["turn_crossed"] = crossed
        within, vtext = threshold_verdict(delta)
        result["threshold"] = NODE_LIMIT
        result["within_threshold"] = within
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print("本节点消耗积分（自基线累计增量）: %.2f" % delta)
            print("  会话 %s | 累计 %.2f（基线 %.2f）" % (sid, s["credit"], float(base.get("credit", 0.0))))
            print("  单轮口径（自最近一条用户消息起）: %.2f   ← 与 App「共消耗」同值" % turn_credit)
            if crossed:
                print("  [提示] 基线之后已跨用户消息轮次——累计增量含多轮；对照 App 单轮值请取上面的单轮口径（或 --turn）")
            print("  阈值 %d → %s" % (NODE_LIMIT, vtext))
            if result.get("baseline_session_mismatch"):
                print("  [warn] 基线属于另一会话 %s，增量仅供参考" % result["baseline_session_mismatch"])
            if scope_warn:
                print("  [warn] %s" % scope_warn)
        return 0

    if args.report:
        return generate_report(projects, args.report_days, session=args.session, cwd=cwd, out_path=args.report_out)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("WorkBuddy 本节点（当前会话）积分")
        print("=" * 44)
        print("会话            : %s" % sid)
        print("会话日志        : %s" % session_file)
        print("累计消耗积分    : %.2f   （官方 credit，与 App 账单同源）" % s["credit"])
        print("模型请求        : %d 次（其中 %d 条含 credit）" % (s["requests"], s["credit_requests"]))
        print("Token 合计      : %s  (输入 %s / 输出 %s)" % (
            f"{s['total_tokens']:,}", f"{s['input_tokens']:,}", f"{s['output_tokens']:,}"))
        if args.model and s["per_model_credit"]:
            print("-" * 44)
            print("逐模型积分:")
            for m, c in s["per_model_credit"].items():
                print("  %-28s %8.2f" % (m, c))
        if scope_warn:
            print("-" * 44)
            print("[warn] %s" % scope_warn)
        print("-" * 44)
        print("提示: 本节点（单轮）实测用 --turn（与 App「共消耗」同源同值）；跨多轮总量用 --mark/--delta。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
