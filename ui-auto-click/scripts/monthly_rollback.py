#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多公众号 × 逐月回溯 采集调度器（打包「微信公众号文章批量下载工具」）。

它解决的是什么
--------------
用户口径（2026-11-01）：
  1. 每次只采集各公众号**最近一个月内**的文章；
  2. 一次要能批量采集**多个公众号**；
  3. 某号采满一个月后，**先检查是不是所有号都采完了这个月**；
     是 ⇒ 把时间窗口统一往前推一个月继续，如此逐月回溯。

第 3 条决定了它不能是"每个号各跑一遍全部历史"，而必须是**一个窗口一个窗口
推进的闸门**：窗口是一等公民，公众号是窗口里的任务。任何一个号没完成当前
窗口，窗口就不许前移——否则会出现"号 A 已经回溯到 2024 年、号 B 还停在
2026 年"的错位，之后再也对不齐。

为什么用「自定义」时间范围而不是工具自带的「一个月内」
------------------------------------------------------
「一个月内」是**相对今天**的滚动窗，推不回历史；「全部」一次抓完又不满足
"逐月推进"的节奏。只有「自定义」能精确指定起止日。日期框是 QDateEdit，
UIA 的 SetValue 假成功、逐字符输入被吞，可靠通道是点击+Ctrl+A+Ctrl+V
（已封成 clicker 的 `set_date` 动作，见其注释与真机取证）。

窗口语义（重要）
----------------
窗口是**闭区间**，相邻窗口在边界日**重叠一天**（W0 结束于 2026-11-01，
W1 也起于 2026-11-01）。这是故意的：下载工具按文章去重，重了不会多出文件；
漏一篇则是静默的、事后无从发现。宁可重，不可漏。

两种切窗策略
------------
  rolling （默认）W0=[anchor-1月, anchor]，W1=[anchor-2月, anchor-1月]…
           —— 永远"最近一个月"，符合口径 1 的字面意思。
  calendar        W0=[本月1日, anchor]，W1=[上月1日, 本月1日]…
           —— 按自然月切，便于按「2026-10 这一窗」对账。
anchor 在 init 时**固化写进 state**，之后每次运行都由它推导窗口：
如果每次用"今天"重算，隔天再跑窗口就会整体漂移、已采过的月份被重复劳动。

状态机
------
每个 (窗口, 公众号) 任务有 status：
    pending → running(隐含) → done
                            → failed（attempts+1，下次重试）
窗口 status：active → completed（**仅当该窗口所有账号都 done**）
推窗（把窗口前移一个月）只发生在"当前窗口 completed"之后，并且受
max_windows / stop_before 两道闸限制——回溯到设定下限就停，不会无限往回爬。

用法
----
  # 1. 初始化（把要采的号列清楚；article_url 是该号任意一篇能打开的文章）
  python scripts/monthly_rollback.py init \
      --account "食品研发与生产" --account "宠物食品研发号A" \
      --accounts-file accounts.yaml            # 也可以从文件读（见下）

  # 2. 看计划：当前窗口是哪个、每个号什么状态、下一步是谁
  python scripts/monthly_rollback.py status
  python scripts/monthly_rollback.py next

  # 3. 跑（真操作，必须 --yes）。--dry-run 只打印将要执行的命令
  python scripts/monthly_rollback.py run --yes
  python scripts/monthly_rollback.py run --yes --max-tasks 1

  # 外部驱动（例如另一个编排器）：先 next 拿任务，自己跑完再 mark
  python scripts/monthly_rollback.py mark --window W0001 --account "A" \
      --status done --md-new 12

accounts.yaml（可选，比命令行更适合多个号）
-------------------------------------------
  accounts:
    - name: 食品研发与生产
      article_url: https://mp.weixin.qq.com/s/xxxxxxxx
    - name: 宠物食品研发号A
      article_url: https://mp.weixin.qq.com/s/yyyyyyyy

退出码：0 完成 / 2 参数错 / 3 执行失败 / 6 环境不具备 / 7 被阻塞（有任务
重试超限，需人工介入）

产物不落在技能目录里（`--state` 默认仍指向技能 out/，正式用请指到数据目录）。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
CLICKER = SKILL / "scripts" / "clicker.py"
PROFILE = "wechat_batch_downloader"

DEFAULT_STATE = SKILL / "out" / "monthly_rollback" / "state.json"
DEFAULT_BASE = "C:/Users/Administrator/Desktop/下载"
DEFAULT_EXE = "C:/Users/Administrator/Desktop/微信公众号批量下载工具4.0.exe"

STATE_VERSION = 1

EXIT_OK, EXIT_PARAM, EXIT_ERROR, EXIT_ENV, EXIT_BLOCKED = 0, 2, 3, 6, 7

#: 视为"这一窗采完了"的 clicker 退出码。5=部分成功（有 optional 步骤 warn），
#: 对下载任务而言仍然意味着「该窗已被完整走了一遍」，不能因此卡住整条回溯链；
#: 但 detail 里会记下来，供人工复核。
OK_CODES = {0, 5}


# ------------------------------------------------------------------ 窗口数学
def days_in_month(year: int, month: int) -> int:
    """该年该月有多少天（含闰年）。"""
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - date(year, month, 1)).days


def shift_months(d: date, months: int) -> date:
    """按自然月平移，日号越界时钳到当月最后一天。

    为什么必须钳：anchor 常落在 31 号（今天是月末时），往前推一个月得到
    2 月 31 日这种不存在的日期。直接 date() 会抛 ValueError；钳到 2 月 28/29
    是用户能接受且可预期的行为（"上个月的这一天"）。
    """
    total = (d.year * 12 + d.month - 1) + int(months)
    year, month = divmod(total, 12)
    month += 1
    return date(year, month, min(d.day, days_in_month(year, month)))


def window_bounds(anchor: date, index: int, policy: str = "rolling") -> tuple[date, date]:
    """第 index 个窗口的 (start, end)，闭区间，index=0 是最新窗口。"""
    if index < 0:
        raise ValueError("窗口序号不能为负")
    if policy == "calendar":
        first = date(anchor.year, anchor.month, 1)
        if index == 0:
            # 首窗从本月 1 日到今天；月初当天跑就是一天窗，这是 calendar
            # 策略的正常形态（它追求的是"按自然月对账"，不是"够 30 天"）。
            return first, anchor
        return shift_months(first, -index), shift_months(first, -(index - 1))
    if policy != "rolling":
        raise ValueError("未知窗口策略: %r（可选 rolling / calendar）" % (policy,))
    return shift_months(anchor, -(index + 1)), shift_months(anchor, -index)


def parse_date(text: str) -> date:
    """认 YYYY-MM-DD / YYYY/MM/DD；错就抛 ValueError（不猜）。"""
    s = str(text).strip().replace("/", "-")
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("日期要写成 YYYY-MM-DD，得到 %r" % (text,)) from exc


# ------------------------------------------------------------------ 状态读写
def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def new_state(accounts: list[dict], anchor: date | None = None,
              policy: str = "rolling", base: str = DEFAULT_BASE,
              max_windows: int = 24, stop_before: str = "2020-01-01",
              max_attempts: int = 3) -> dict:
    """建一份空状态：不带窗口，第一次 next/run 时才落第一个窗口。

    为什么不在这里就把 24 个窗口全建出来：窗口边界在 rolling 策略下虽然可
    推导，但"建出来"意味着"承诺要采"，回溯到一半改 anchor 就全乱了。按需
    建一个、完成一个、再建下一个，状态文件永远只描述"真实发生过的事"。
    """
    anchor_d = anchor or date.today()
    if not accounts:
        raise ValueError("至少要一个公众号")
    names = [a["name"] for a in accounts]
    if len(set(names)) != len(names):
        raise ValueError("公众号名称重复：%s" % names)
    return {
        "version": STATE_VERSION,
        "skill": "ui-auto-click/monthly_rollback",
        "created_at": _now(),
        "updated_at": _now(),
        "anchor": anchor_d.isoformat(),
        "policy": policy,
        "base": base,
        "max_windows": int(max_windows),
        "stop_before": stop_before,
        "max_attempts": int(max_attempts),
        "accounts": accounts,
        "windows": [],          # 新 → 旧
        "tasks": {},            # {window_id: {account: task}}
    }


def load_state(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(
            "状态文件不存在：%s（先跑 init）" % path)
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("version") != STATE_VERSION:
        raise ValueError("状态文件版本 %r 与本脚本 %r 不一致，拒绝按旧格式猜"
                         % (state.get("version"), STATE_VERSION))
    return state


def save_state(path: Path, state: dict) -> None:
    """原子写：先写 .tmp 再 os.replace。

    调度器会被反复中断重跑，半截 JSON 会让整条回溯链丢失进度；os.replace
    在同一分区上是原子的，断电也只会留下旧文件。
    """
    state["updated_at"] = _now()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)


# ------------------------------------------------------------------ 窗口/任务操作
def window_id(index: int) -> str:
    """W0001、W0002… 固定宽度，方便排序与肉眼对账。"""
    return "W%04d" % (index + 1)


def task_of(state: dict, wid: str, account: str) -> dict:
    """取任务，没有就建一个 pending（幂等）。"""
    bucket = state["tasks"].setdefault(wid, {})
    task = bucket.get(account)
    if task is None:
        task = {"window": wid, "account": account, "status": "pending",
                "attempts": 0, "md_new": 0, "at": "", "detail": ""}
        bucket[account] = task
    return task


def open_next_window(state: dict) -> dict | None:
    """在已完成的窗口之后开一个新窗口；超出下限/上限返回 None。

    两道闸都会拦：
      * max_windows —— 回溯深度上限（默认 24 个月，两年）；
      * stop_before —— 窗口起点早于该日期就不再往回爬。
    这是"逐月回溯"必须有的刹车：没有它，一个循环写错就会一路爬到 2000 年。
    """
    index = len(state["windows"])
    if index >= int(state.get("max_windows", 24)):
        return None
    anchor = parse_date(state["anchor"])
    start, end = window_bounds(anchor, index, state.get("policy", "rolling"))
    stop_before = parse_date(state.get("stop_before") or "1970-01-01")
    if start < stop_before:
        return None
    win = {"id": window_id(index), "index": index,
           "start": start.isoformat(), "end": end.isoformat(),
           "status": "active", "created_at": _now()}
    state["windows"].append(win)
    for acct in state["accounts"]:
        task_of(state, win["id"], acct["name"])
    return win


def active_window(state: dict) -> dict | None:
    """当前正在推进的窗口（最新且未完成）。"""
    for win in reversed(state["windows"]):
        if win.get("status") != "completed":
            return win
    return None


def window_progress(state: dict, wid: str) -> dict:
    """某窗口的完成度：谁 done、谁 pending、谁失败、是否可推窗。

    「是否可推窗」的判据只有一条：**所有账号都 done**。失败不算完成、
    重试中不算完成——这正是用户口径 3 里"先检查所有公众号是否均已完成"
    的那个检查，把它做成函数是为了让 run 与 status 用同一份逻辑。
    """
    accts = [a["name"] for a in state["accounts"]]
    tasks = [task_of(state, wid, name) for name in accts]
    done = [t["account"] for t in tasks if t["status"] == "done"]
    failed = [t["account"] for t in tasks if t["status"] == "failed"]
    pending = [t["account"] for t in tasks if t["status"] not in ("done", "failed")]
    return {
        "window": wid, "total": len(accts),
        "done": done, "failed": failed, "pending": pending,
        "complete": len(done) == len(accts) and len(accts) > 0,
    }


def mark_window_if_complete(state: dict, wid: str) -> bool:
    """全完成就把窗口标记 completed（幂等）。返回是否发生了状态迁移。"""
    win = next((w for w in state["windows"] if w["id"] == wid), None)
    if win is None or win.get("status") == "completed":
        return False
    if not window_progress(state, wid)["complete"]:
        return False
    win["status"] = "completed"
    win["completed_at"] = _now()
    return True


def next_task(state: dict) -> tuple[dict | None, str]:
    """下一个该跑的任务，或 (None, 原因)。

    推进顺序即闸门逻辑：
      1. 当前窗口里还有 pending ⇒ 跑它（**先把所有号的这一个月补齐**）；
      2. 没有 pending 但有 failed 且没超重试上限 ⇒ 重试它（不推窗）；
      3. 有 failed 且已达上限 ⇒ 返回 blocked，**绝不跳过该号去推窗**；
      4. 全部 done ⇒ 关窗、开下一窗，回到 1；
      5. 开不出新窗（到下限/上限）⇒ 返回 all_done。
    """
    while True:
        win = active_window(state)
        if win is None:
            nxt = open_next_window(state)
            if nxt is None:
                return None, "all_done"
            win = nxt
        wid = win["id"]
        accts = [a["name"] for a in state["accounts"]]
        max_attempts = int(state.get("max_attempts", 3))

        for name in accts:
            task = task_of(state, wid, name)
            if task["status"] == "pending":
                return task, "pending:%s/%s" % (wid, name)

        blocked = [name for name in accts
                   if task_of(state, wid, name)["status"] == "failed"
                   and task_of(state, wid, name)["attempts"] >= max_attempts]
        if blocked:
            return None, "blocked:%s:%s（重试已达 %d 次，需人工处理）" % (
                wid, ",".join(blocked), max_attempts)

        retry = [name for name in accts
                 if task_of(state, wid, name)["status"] == "failed"]
        if retry:
            return task_of(state, wid, retry[0]), "retry:%s/%s" % (wid, retry[0])

        # 全 done
        if mark_window_if_complete(state, wid):
            continue                      # 立刻开下一窗并重新判定
        return None, "inconsistent:%s 既非全完成也无可跑任务" % wid


def mark_task(state: dict, wid: str, account: str, status: str,
              md_new: int | None = None, detail: str = "") -> dict:
    """记录任务结果。status 只接受 done / failed / pending（重排）。"""
    if status not in ("done", "failed", "pending"):
        raise ValueError("status 只能是 done/failed/pending，得到 %r" % (status,))
    if not any(w["id"] == wid for w in state["windows"]):
        raise ValueError("未知窗口 %r（现有：%s）"
                         % (wid, [w["id"] for w in state["windows"]]))
    task = task_of(state, wid, account)
    if status == "done":
        task["status"] = "done"
    elif status == "failed":
        task["status"] = "failed"
        task["attempts"] = int(task.get("attempts", 0)) + 1
    else:
        task["status"] = "pending"
    if md_new is not None:
        task["md_new"] = int(md_new)
    task["at"] = _now()
    if detail:
        task["detail"] = str(detail)[:400]
    # 只有"全完成"才允许关窗；单独 mark 一个 done 不会误推窗
    mark_window_if_complete(state, wid)
    return task


# ------------------------------------------------------------------ 执行
def pick_python(explicit: str = "") -> str:
    """挑一个能 import pywinauto 的解释器（clicker 必须依赖它）。"""
    cands = []
    if explicit:
        cands.append(explicit)
    if os.environ.get("UIAC_PY"):
        cands.append(os.environ["UIAC_PY"])
    envs = Path.home() / ".workbuddy" / "binaries" / "python" / "envs"
    if envs.is_dir():
        cands += [str(p / "Scripts" / "python.exe") for p in sorted(envs.iterdir())
                  if (p / "Scripts" / "python.exe").is_file()]
    cands.append(sys.executable)
    for cand in cands:
        try:
            r = subprocess.run([cand, "-c", "import pywinauto"],
                               capture_output=True, timeout=60)
            if r.returncode == 0:
                return cand
        except Exception:
            continue
    return sys.executable


def md_count(root: Path) -> int:
    return len(list(root.glob("*.md"))) if root.is_dir() else 0


def build_clicker_cmd(py: str, start: str, end: str, article_url: str) -> list[str]:
    """组装 clicker 命令：自定义时间窗 + 该号文章链接。

    RANGE=custom 是新增分支（2026-11-01）；DATE_START/DATE_END 用 ISO 写法，
    由 profile 的 set_date 收敛成控件要的 yyyy/MM/dd。

    ARTICLE_URL 为空时**不传**：profile 那一步是 skip_if_empty，但工具的
    「微信文章链接」框留空时点「1.获取公众号id」不会写任何日志（实测），
    随后必然等到超时。所以 run 在更上层就拦掉无链接的账号（见 main）。
    """
    cmd = [py, str(CLICKER), "run", "--profile", PROFILE, "--yes",
           "--var", "RANGE=custom",
           "--var", "DATE_START=%s" % start,
           "--var", "DATE_END=%s" % end]
    if article_url:
        cmd += ["--var", "ARTICLE_URL=%s" % article_url]
    return cmd


def execute_task(state: dict, task: dict, py: str, timeout: int,
                 dry_run: bool, echo=print) -> tuple[bool, int, str]:
    """跑一个任务，返回 (成功?, 新增md数, 说明)。不改 state，由调用方 mark。"""
    win = next(w for w in state["windows"] if w["id"] == task["window"])
    acct = next(a for a in state["accounts"] if a["name"] == task["account"])
    root = Path(state.get("base") or DEFAULT_BASE) / acct["name"]
    cmd = build_clicker_cmd(py, win["start"], win["end"], acct.get("article_url", ""))
    if dry_run:
        echo("    [dry] " + " ".join(cmd))
        return True, 0, "dry-run"

    before = md_count(root)
    echo("    $ " + " ".join(cmd))
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, 0, "超时 %ds 未结束" % timeout
    after = md_count(root)
    md_new = max(0, after - before)
    rc = r.returncode
    tail = [ln for ln in (r.stderr or "").strip().splitlines() if ln.strip()][-3:]
    note = "rc=%s 新增md=%d" % (rc, md_new)
    if tail:
        note += "；" + " / ".join(tail)
    return (rc in OK_CODES), md_new, note[:400]


# ------------------------------------------------------------------ CLI
def _fmt_progress(state: dict, wid: str) -> str:
    p = window_progress(state, wid)
    parts = []
    for name in [a["name"] for a in state["accounts"]]:
        t = task_of(state, wid, name)
        mark = {"done": "✓", "failed": "✗"}.get(t["status"], "·")
        extra = ("(%d篇)" % t["md_new"]) if t["status"] == "done" and t.get("md_new") else ""
        if t["status"] == "failed":
            extra = "(第%d次)" % t.get("attempts", 0)
        parts.append("%s %s%s" % (mark, name, extra))
    return "  ".join(parts)


def cmd_init(args) -> int:
    path = Path(args.state)
    if path.exists() and not args.force:
        print("状态文件已存在：%s（重来请加 --force，或换 --state）" % path,
              file=sys.stderr)
        return EXIT_PARAM
    accounts: list[dict] = []
    if args.accounts_file:
        import yaml

        doc = yaml.safe_load(Path(args.accounts_file).read_text(encoding="utf-8"))
        for item in (doc or {}).get("accounts") or []:
            if not isinstance(item, dict) or not item.get("name"):
                raise SystemExit("accounts 文件里每项都要有 name：%r" % (item,))
            accounts.append({"name": str(item["name"]).strip(),
                             "article_url": str(item.get("article_url") or "").strip()})
    for spec in args.account or []:
        # 允许 "名称=文章链接" 一行写完，省一次编辑
        name, _, url = str(spec).partition("=")
        accounts.append({"name": name.strip(), "article_url": url.strip()})
    if not accounts:
        print("至少给一个 --account 或 --accounts-file", file=sys.stderr)
        return EXIT_PARAM
    try:
        state = new_state(accounts, parse_date(args.anchor) if args.anchor else None,
                          policy=args.policy, base=args.base,
                          max_windows=args.max_windows,
                          stop_before=args.stop_before,
                          max_attempts=args.max_attempts)
    except ValueError as exc:
        print("参数不合法：%s" % exc, file=sys.stderr)
        return EXIT_PARAM
    save_state(path, state)
    print("已初始化 %s" % path)
    print("  公众号 %d 个：%s" % (len(accounts), "、".join(a["name"] for a in accounts)))
    print("  anchor=%s policy=%s 回溯上限=%d 窗 / 下限=%s"
          % (state["anchor"], state["policy"], state["max_windows"],
             state["stop_before"]))
    print("  下一步：%s" % " ".join([sys.executable, __file__, "status"]))
    return EXIT_OK


def cmd_status(args) -> int:
    state = load_state(Path(args.state))
    print("状态文件 : %s" % args.state)
    print("anchor   : %s（policy=%s，回溯上限 %d 窗，下限 %s）"
          % (state["anchor"], state["policy"], state["max_windows"],
             state["stop_before"]))
    print("公众号   : %s" % "、".join(a["name"] for a in state["accounts"]))
    if not state["windows"]:
        print("窗口     : （尚未开始，第一次 run/next 才会落第一个窗口）")
    for win in state["windows"]:
        flag = "已完成" if win["status"] == "completed" else "进行中"
        print("  %s %s ~ %s [%s]  %s"
              % (win["id"], win["start"], win["end"], flag,
                 _fmt_progress(state, win["id"])))
    task, why = next_task(state)
    if task is None:
        print("\n下一步   : 无（%s）" % why)
    else:
        print("\n下一步   : %s 窗口 %s  →  %s"
              % (task["account"], task["window"], why))
    # next_task 会顺手开窗 / 关窗，状态可能有迁移，落盘保持与显示一致
    save_state(Path(args.state), state)
    return EXIT_OK


def cmd_next(args) -> int:
    state = load_state(Path(args.state))
    task, why = next_task(state)
    save_state(Path(args.state), state)
    if task is None:
        print(json.dumps({"task": None, "reason": why}, ensure_ascii=False))
        return EXIT_OK if why == "all_done" else EXIT_BLOCKED
    win = next(w for w in state["windows"] if w["id"] == task["window"])
    acct = next(a for a in state["accounts"] if a["name"] == task["account"])
    print(json.dumps({
        "task": {"window": win["id"], "start": win["start"], "end": win["end"],
                 "account": acct["name"], "article_url": acct.get("article_url", ""),
                 "attempts": task.get("attempts", 0)},
        "reason": why,
    }, ensure_ascii=False, indent=2))
    return EXIT_OK


def cmd_mark(args) -> int:
    path = Path(args.state)
    state = load_state(path)
    try:
        task = mark_task(state, args.window, args.account, args.status,
                         md_new=args.md_new, detail=args.detail)
    except ValueError as exc:
        print("标记失败：%s" % exc, file=sys.stderr)
        return EXIT_PARAM
    save_state(path, state)
    print("%s / %s → %s（attempts=%d）"
          % (task["window"], task["account"], task["status"], task["attempts"]))
    win = next(w for w in state["windows"] if w["id"] == task["window"])
    if win.get("status") == "completed":
        print("该窗口所有账号均已完成 → 已关闭，下次 run/next 会自动开下一窗")
    return EXIT_OK


def cmd_run(args) -> int:
    path = Path(args.state)
    state = load_state(path)
    py = pick_python(args.python)
    missing = [a["name"] for a in state["accounts"] if not a.get("article_url")]
    if missing and not args.allow_no_url:
        print("这些公众号缺 article_url：%s" % "、".join(missing), file=sys.stderr)
        print("「1.获取公众号id」要求微信里先打开该号文章；没有链接时工具不写任何"
              "日志、必然超时。用 init --account \"名称=链接\" 补上，"
              "或加 --allow-no-url 强行跑（不推荐）。", file=sys.stderr)
        return EXIT_PARAM
    if not args.dry_run and not args.yes:
        print("真操作需要 --yes（会驱动下载工具真的下载）", file=sys.stderr)
        return EXIT_PARAM

    print("python : %s" % py)
    print("窗口内 : %d 个公众号 / 每窗一次下载" % len(state["accounts"]))
    done_tasks = 0
    while True:
        if args.max_tasks and done_tasks >= args.max_tasks:
            print("已跑满 --max-tasks %d，停手（进度已存盘）" % args.max_tasks)
            break
        task, why = next_task(state)
        save_state(path, state)          # next_task 可能刚开了新窗口
        if task is None:
            print("\n结束：%s" % why)
            return EXIT_OK if why == "all_done" else EXIT_BLOCKED
        win = next(w for w in state["windows"] if w["id"] == task["window"])
        print("\n[%s] %s ~ %s  →  %s（第 %d 次尝试）"
              % (win["id"], win["start"], win["end"], task["account"],
                 int(task.get("attempts", 0)) + 1))
        ok, md_new, note = execute_task(state, task, py, args.timeout,
                                        args.dry_run)
        if args.dry_run:
            print("    （dry-run 不落状态）")
            done_tasks += 1
            if not args.max_tasks:
                break                     # dry-run 默认只演示第一个任务
            continue
        mark_task(state, task["window"], task["account"],
                  "done" if ok else "failed", md_new=md_new, detail=note)
        save_state(path, state)
        print("    %s %s" % ("✓" if ok else "✗", note))
        done_tasks += 1
        if not ok and args.stop_on_fail:
            print("\n任务失败已停手（--no-stop-on-fail 可继续其它账号）。"
                  "修好后重跑本命令会重试该任务。")
            return EXIT_ERROR


def cmd_rewind(args) -> int:
    """把一个窗口打回未完成，让它的任务重跑（改口径/补数据时用）。"""
    path = Path(args.state)
    state = load_state(path)
    win = next((w for w in state["windows"] if w["id"] == args.window), None)
    if win is None:
        print("未知窗口 %r（现有：%s）"
              % (args.window, [w["id"] for w in state["windows"]]), file=sys.stderr)
        return EXIT_PARAM
    win["status"] = "active"
    win.pop("completed_at", None)
    for acct in state["accounts"]:
        t = task_of(state, win["id"], acct["name"])
        t["status"] = "pending"
        t["attempts"] = 0
        t["detail"] = "rewind"
    save_state(path, state)
    print("%s 已打回：所有账号任务重置为 pending，window 重新 active" % win["id"])
    return EXIT_OK


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="多公众号 × 逐月回溯采集调度器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="窗口是闭区间，相邻窗口在边界日重叠一天（只有这套时间范围能"
               "精确回溯；工具的「一个月内」相对今天，推不回历史）。")
    ap.add_argument("--state", default=str(DEFAULT_STATE),
                    help="状态文件（默认技能 out/monthly_rollback/state.json）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="初始化账号清单与窗口策略")
    p.add_argument("--account", action="append", default=[],
                   help='公众号；可写 "名称=文章链接"（链接用于取公众号id）')
    p.add_argument("--accounts-file", default="", help="YAML：accounts: [{name, article_url}]")
    p.add_argument("--anchor", default="", help="窗口锚点日期 YYYY-MM-DD（默认今天）")
    p.add_argument("--policy", default="rolling", choices=("rolling", "calendar"))
    p.add_argument("--base", default=DEFAULT_BASE, help="下载根目录")
    p.add_argument("--max-windows", type=int, default=24, help="回溯窗口数上限")
    p.add_argument("--stop-before", default="2020-01-01", help="窗口起点早于此日就停")
    p.add_argument("--max-attempts", type=int, default=3, help="单任务重试上限")
    p.add_argument("--force", action="store_true", help="覆盖已存在的状态文件")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("status", help="看窗口矩阵与下一步")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("next", help="打印下一个任务（JSON，供外部编排器）")
    p.set_defaults(func=cmd_next)

    p = sub.add_parser("mark", help="外部执行完后回填任务结果")
    p.add_argument("--window", required=True)
    p.add_argument("--account", required=True)
    p.add_argument("--status", required=True, choices=("done", "failed", "pending"))
    p.add_argument("--md-new", type=int, default=None, help="本次新增 md 篇数")
    p.add_argument("--detail", default="", help="备注（写进状态，便于事后对账）")
    p.set_defaults(func=cmd_mark)

    p = sub.add_parser("run", help="自动推进：next → 执行 → mark，直到上限或失败")
    p.add_argument("--yes", action="store_true", help="确认真操作（必须）")
    p.add_argument("--dry-run", action="store_true", help="只打印命令不执行")
    p.add_argument("--max-tasks", type=int, default=0, help="最多跑几个任务（0=不限）")
    p.add_argument("--timeout", type=int, default=3600, help="单任务超时秒数")
    p.add_argument("--python", default="", help="指定解释器（缺省自动挑能 import pywinauto 的）")
    p.add_argument("--stop-on-fail", dest="stop_on_fail", action="store_true",
                   default=True, help="任务失败即停手（默认开）")
    p.add_argument("--no-stop-on-fail", dest="stop_on_fail", action="store_false",
                   help="失败也继续跑其它账号（仍不会推窗）")
    p.add_argument("--allow-no-url", action="store_true",
                   help="允许没有 article_url 的账号照跑（通常必然超时）")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("rewind", help="把某窗口打回未完成以重跑")
    p.add_argument("--window", required=True)
    p.set_defaults(func=cmd_rewind)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_PARAM
    except ValueError as exc:
        print("参数不合法：%s" % exc, file=sys.stderr)
        return EXIT_PARAM


if __name__ == "__main__":
    sys.exit(main())
