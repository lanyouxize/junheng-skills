# -*- coding: utf-8 -*-
"""mse.health/1 引擎健康度台账（路线图 O-5）

职责：把「今天哪个引擎挂了」从记忆变成数据。
消费 mse.result/1 批次（references/result-contract.md），逐引擎登记 status，
落 engine-health.jsonl，并输出「引擎可用性榜」mse.health.summary/1。

status 四态沿用结果契约且**不可合并**：
  ok       正常返回且有结果
  empty    请求成功但该引擎确实无结果   → 记「可用」（引擎是好的，只是没命中）
  blocked  被拦截（403/429/验证码）     → 记「不可用」
  error    网络或解析异常               → 记「不可用」
把 blocked 并入 empty，会让「引擎坏掉」伪装成「没有结果」。

引擎判定四态（不可合并；第三态保护「样本不足」不伪装成「不健康」）：
  insufficient-data  样本数 < --min-attempts，无法判定
  unavailable        窗口内可用率 = 0
  degraded           0 < 可用率 < HEALTHY_USABLE
  healthy            可用率 ≥ HEALTHY_USABLE

退出码（三态，禁止把「没能验证」冒充「已损坏」）：
  0 = 通过（含域内负结果：无台账 / 窗口内无记录 / 无需新增 / 无需清理）
  1 = 确有缺陷（输入违规、台账损坏、回读校验失败）
  3 = 无法验证（缺 config.json；输入不存在或非 JSON；参数非法）

用法：
  python engine_health.py results.json [more.json ...]   # 登记 + 出榜
  python engine_health.py results.json --no-append       # 只预演，不落账
  python engine_health.py --summary                      # 只出榜（读台账）
  python engine_health.py --summary --window 7           # 最近 7 天
  python engine_health.py --prune-older-than 90 [--yes]  # 清理（默认 dry-run）
  python engine_health.py --selftest
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:  # Windows 控制台默认 GBK，会炸中文
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate_results as vr  # noqa: E402  复用契约校验，不复制判据

ROOT = Path(__file__).resolve().parent.parent

LEDGER_SCHEMA = "mse.health/1"
SUMMARY_SCHEMA = "mse.health.summary/1"
DEFAULT_LEDGER = ROOT / "engine-health.jsonl"
DEFAULT_WINDOW_DAYS = 30
DEFAULT_MIN_ATTEMPTS = 3
HEALTHY_USABLE = 0.8                       # 可用率门槛：≥ healthy，< degraded
SEVERITY = {"empty": 1, "blocked": 2, "error": 3}   # 同引擎混合状态取最严重
LEDGER_FIELDS = ("schema", "batch_id", "engine", "status", "fetched_at")

EXIT_OK = 0
EXIT_DEFECT = 1
EXIT_CANNOT = 3

_USAGE = __doc__ or "用法: engine_health.py <results.json...> [--summary] [--ledger PATH]"


# ---------------------------------------------------------------- 基础
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_dt(v):
    """解析 ISO 8601；无时区按 UTC（避免与 aware 的 now 比较时炸 TypeError）。"""
    if not isinstance(v, str) or not v.strip():
        return None
    try:
        dt = datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def batch_id(batch: dict) -> str:
    """批次内容身份证：规范化 JSON 的 sha256。

    同一份内容（哪怕换了文件名）= 同一次检索，重复登记应被跳过；
    内容有变（重新检索、结果不同）= 新的一次，应单独计数。
    """
    canon = json.dumps(batch, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- 记录构建
def engine_records(batch: dict, engines: dict[str, str], now: datetime | None = None) -> list[dict]:
    """把一个批次展开为「每引擎一条」的台账记录。

    同引擎多条目时的归并规则（显式声明，避免隐没判断）：
      - 有 ok 条目 → status=ok，result_count=ok 条目数；
        同时存在非 ok 条目 → note 记 mixed:<状态列表>（ok 优先，样本不失真）。
      - 无 ok 条目 → 取最严重状态（error > blocked > empty），
        多种非 ok 并存 → note 记 mixed:<状态列表>。
    """
    now = now or datetime.now(timezone.utc)
    grouped: dict[str, list[dict]] = {}
    for r in batch.get("results", []):
        raw = re.sub(r"\s+", " ", str(r.get("engine", ""))).strip()
        name = engines.get(raw.lower(), raw)
        if name:
            grouped.setdefault(name, []).append(r)

    bid = batch_id(batch)
    query = str(batch.get("query", "")).strip()
    out: list[dict] = []
    for name in sorted(grouped):
        items = grouped[name]
        oks = [r for r in items if r.get("status") == "ok"]
        others = [r for r in items if r.get("status") != "ok"]
        statuses = sorted({str(r.get("status")) for r in others})
        note = None
        if oks:
            status, count = "ok", len(oks)
            if others:
                note = "mixed:" + ",".join(statuses)
        elif others:
            status = max(statuses, key=lambda s: SEVERITY.get(s, 0))
            count = 0
            if len(statuses) > 1:
                note = "mixed:" + ",".join(statuses)
        else:
            continue
        dated = [(_parse_dt(r.get("fetched_at")), r.get("fetched_at", "")) for r in items]
        dated = [(d, s) for d, s in dated if d is not None]
        fetched = max(dated, key=lambda x: x[0])[1] if dated else ""
        out.append({
            "schema": LEDGER_SCHEMA,
            "batch_id": bid,
            "recorded_at": now.isoformat(timespec="seconds"),
            "query": query,
            "engine": name,
            "status": status,
            "result_count": count,
            "fetched_at": fetched,
            "note": note,
        })
    return out


# ---------------------------------------------------------------- 台账 IO
def read_ledger(path: Path) -> tuple[list[dict], list[str]]:
    """读台账。任何一行损坏都是**缺陷**（exit 1），绝不静默跳过。"""
    problems: list[str] = []
    records: list[dict] = []
    if not path.exists():
        return records, problems
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        return [], [f"台账不可读取: {e}"]
    for i, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except Exception as e:  # noqa: BLE001
            problems.append(f"第 {i} 行不是合法 JSON: {e}")
            continue
        if not isinstance(rec, dict):
            problems.append(f"第 {i} 行不是对象")
            continue
        missing = [k for k in LEDGER_FIELDS if k not in rec]
        if missing:
            problems.append(f"第 {i} 行缺字段: {','.join(missing)}")
            continue
        if rec.get("schema") != LEDGER_SCHEMA:
            problems.append(f"第 {i} 行 schema 应为 {LEDGER_SCHEMA}，实为 {rec.get('schema')!r}")
            continue
        if rec.get("status") not in vr.STATUSES:
            problems.append(f"第 {i} 行 status 非法: {rec.get('status')!r}")
            continue
        records.append(rec)
    return records, problems


def _atomic_write(path: Path, lines: list[str]) -> None:
    """同目录临时文件 + os.replace，保证「要么全旧要么全新」。"""
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines) + "\n")
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _rec_key(rec: dict) -> tuple:
    """台账去重键 = (batch_id, engine)。

    批次内**每引擎一条**记录，故去重必须落到「批次 × 引擎」粒度；
    只用 batch_id 会把同批次的第二条引擎记录误判成重复（自检 B1 抓出）。
    """
    return (rec.get("batch_id"), rec.get("engine"))


def append_records(ledger: Path, new_records: list[dict],
                   existing: list[dict]) -> tuple[list[dict], list[str], list[str]]:
    """把新记录并入台账。返回 (已写入记录, 已跳过键, 问题清单)。

    去重作用域 = **整个台账**（不是某个分桶）：同一「批次 × 引擎」重复登记直接跳过。
    提交顺序：写临时文件 → 回读校验（新记录在册 **且** 原有记录不丢）→ 才替换。
    任一步不过 → 删临时文件、原台账字节不变。
    """
    known = {_rec_key(r) for r in existing}
    to_write: list[dict] = []
    skipped: list[str] = []
    for rec in new_records:
        key = _rec_key(rec)
        if key in known:
            skipped.append(f"{key[0][:8]}/{key[1]}")
            continue
        known.add(key)
        to_write.append(rec)

    if not to_write:
        return [], skipped, []

    lines = [json.dumps(r, ensure_ascii=False, sort_keys=True) for r in existing + to_write]
    problems: list[str] = []
    tmp_path: Path | None = None
    try:
        ledger.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=str(ledger.parent),
                                        prefix=ledger.name + ".", suffix=".tmp")
        tmp_path = Path(tmp_name)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines) + "\n")
        # 先校验临时文件，再提交 —— 字节落盘 ≠ 内容在册
        back, back_problems = read_ledger(tmp_path)
        problems.extend(f"临时文件校验: {p}" for p in back_problems)
        back_keys = {_rec_key(r) for r in back}
        miss = [f"{_rec_key(r)[0][:8]}/{_rec_key(r)[1]}" for r in to_write
                if _rec_key(r) not in back_keys]
        if miss:
            problems.append(f"回读校验未通过，新记录未落册: {','.join(miss)}")
        lost = {_rec_key(r) for r in existing} - back_keys
        if lost:
            problems.append("回读校验未通过，原有记录丢失: "
                            + ",".join(f"{k[0][:8]}/{k[1]}" for k in sorted(lost, key=str)))
        if problems:
            return [], skipped, problems
        os.replace(tmp_path, ledger)
        tmp_path = None
    except OSError as e:
        problems.append(f"台账写入失败: {e}")
        return [], skipped, problems
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except OSError:
                pass
    return to_write, skipped, problems


# ---------------------------------------------------------------- 汇总
def verdict_of(usable_rate: float, attempts: int, min_attempts: int) -> str:
    """四态判定，次序即语义：样本不足优先，杜绝「没法判」冒充「不健康」。"""
    if attempts < min_attempts:
        return "insufficient-data"
    if usable_rate <= 0:
        return "unavailable"
    if usable_rate < HEALTHY_USABLE:
        return "degraded"
    return "healthy"


def summarize(records: list[dict], window_days: int, min_attempts: int,
              now: datetime | None = None, known_engines: dict[str, str] | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    notes: list[str] = []
    kept: list[dict] = []
    excluded = 0
    undated = 0

    for r in records:
        dt = _parse_dt(r.get("fetched_at"))
        if dt is None:
            kept.append(r)
            undated += 1
            continue
        if window_days and window_days > 0 and dt < now - timedelta(days=window_days):
            excluded += 1
        else:
            kept.append(r)
    if excluded:
        notes.append(f"窗口外 {excluded} 条已排除")
    if undated:
        notes.append(f"{undated} 条 fetched_at 无法解析，按窗口内保留（不冤杀）")

    per: dict[str, dict] = {}
    for r in kept:
        e = str(r.get("engine", ""))
        d = per.setdefault(e, {"engine": e, "attempts": 0, "ok": 0, "empty": 0,
                               "blocked": 0, "error": 0, "result_total": 0})
        d["attempts"] += 1
        st = r.get("status")
        if st in d:
            d[st] += 1
        try:
            d["result_total"] += int(r.get("result_count") or 0)
        except (TypeError, ValueError):
            pass

    engines: list[dict] = []
    for d in per.values():
        usable = d["ok"] + d["empty"]
        rate = usable / d["attempts"] if d["attempts"] else 0.0
        engines.append({
            "engine": d["engine"],
            "attempts": d["attempts"],
            "ok": d["ok"],
            "empty": d["empty"],
            "blocked": d["blocked"],
            "error": d["error"],
            "usable_rate": round(rate, 4),
            "block_rate": round(d["blocked"] / d["attempts"], 4) if d["attempts"] else 0.0,
            "ok_rate": round(d["ok"] / d["attempts"], 4) if d["attempts"] else 0.0,
            "avg_results": round(d["result_total"] / d["attempts"], 2) if d["attempts"] else 0.0,
            "verdict": verdict_of(rate, d["attempts"], min_attempts),
            "verdict_basis": f"attempts={d['attempts']},min_attempts={min_attempts}",
        })
    # 榜：可用率降序 → 样本数降序 → 名称，保证输出稳定
    engines.sort(key=lambda x: (-x["usable_rate"], -x["attempts"], x["engine"]))

    counts = {s: sum(1 for r in kept if r.get("status") == s) for s in vr.STATUSES}
    verdicts: dict[str, int] = {}
    for e in engines:
        verdicts[e["verdict"]] = verdicts.get(e["verdict"], 0) + 1

    if known_engines is not None:
        unknown = sorted({str(r.get("engine", "")) for r in kept} - set(known_engines.values()))
        if unknown:
            notes.append(f"{len(unknown)} 个引擎不在当前 config.json（历史数据或已下架）: "
                         + ", ".join(unknown))

    return {
        "schema": SUMMARY_SCHEMA,
        "status": "ok" if kept else "empty",
        "generated_at": now.isoformat(timespec="seconds"),
        "window_days": window_days,
        "min_attempts": min_attempts,
        "record_count": len(kept),
        "excluded_by_window": excluded,
        "counts": counts,
        "verdicts": verdicts,
        "engines": engines,
        "notes": notes,
    }


# ---------------------------------------------------------------- 渲染
def render_markdown(s: dict) -> str:
    L: list[str] = []
    L.append(f"# 引擎可用性榜（{s['schema']}）")
    L.append("")
    win = f"最近 {s['window_days']} 天" if s["window_days"] else "全部历史"
    L.append(f"- 窗口：{win}；判定门槛：样本 ≥ {s['min_attempts']}，"
             f"可用率 ≥ {HEALTHY_USABLE:.0%} 为 healthy")
    L.append(f"- 窗口内记录 {s['record_count']} 条（排除窗口外 {s['excluded_by_window']} 条）；"
             f"生成时间 {s['generated_at']}")
    L.append("")
    if s["status"] == "empty":
        L.append("> 窗口内无记录 —— 尚无数据可判。**不等于「引擎全挂」**。")
        L.append("")
    else:
        L.append("| 引擎 | 样本 | ok | empty | blocked | error | 可用率 | 均结果数 | 判定 |")
        L.append("|---|---|---|---|---|---|---|---|---|")
        for e in s["engines"]:
            L.append(f"| {e['engine']} | {e['attempts']} | {e['ok']} | {e['empty']} "
                     f"| {e['blocked']} | {e['error']} | {e['usable_rate']:.0%} "
                     f"| {e['avg_results']} | {e['verdict']} |")
        L.append("")
        c = s["counts"]
        L.append(f"状态合计：ok {c.get('ok', 0)} / empty {c.get('empty', 0)} / "
                 f"blocked {c.get('blocked', 0)} / error {c.get('error', 0)}")
        v = s["verdicts"]
        L.append(f"判定分布：healthy {v.get('healthy', 0)} / degraded {v.get('degraded', 0)} / "
                 f"unavailable {v.get('unavailable', 0)} / "
                 f"insufficient-data {v.get('insufficient-data', 0)}")
        L.append("")
    for n in s["notes"]:
        L.append(f"- 注：{n}")
    return "\n".join(L).rstrip() + "\n"


# ---------------------------------------------------------------- 输入
def load_batches(paths: list[str], engines: dict[str, str],
                 err=sys.stderr) -> tuple[list[tuple[str, dict]], int | None]:
    """读入并逐批做 V1–V11 校验。

    与 M5 的**有意差异**：台账本就跨 query 累积，故不要求多批次 query 一致。
    返回 ([(文件名, batch)], 提前退出码或 None)。
    """
    batches: list[tuple[str, dict]] = []
    for p in paths:
        path = Path(p)
        if not path.exists():
            print(f"[无法验证] 输入文件不存在: {path}", file=err)
            return [], EXIT_CANNOT
        try:
            batch = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"[无法验证] 输入不是合法 JSON: {path}: {e}", file=err)
            return [], EXIT_CANNOT
        V = vr.validate(batch, engines)
        if V:
            for v in V:
                print(f"[FAIL] {path.name} {v['id']} {v['path']} {v['msg']}", file=err)
            return [], EXIT_DEFECT
        batches.append((path.name, batch))
    return batches, None


def _emit(summary: dict, want_json: bool, md_out, out, err) -> int:
    if want_json:
        print(json.dumps(summary, ensure_ascii=False, indent=2), file=out)
    else:
        print(render_markdown(summary), file=out)
    if md_out:
        try:
            Path(md_out).write_text(render_markdown(summary), encoding="utf-8", newline="\n")
            print(f"[已写入] {md_out}", file=out)
        except OSError as e:
            print(f"[无法验证] 写入失败: {e}", file=err)
            return EXIT_CANNOT
    return EXIT_OK


# ---------------------------------------------------------------- CLI
def main(argv: list[str], out=sys.stdout, err=sys.stderr) -> int:
    """argv[0] 为程序名（进程内调用自备占位）。"""
    args = list(argv[1:])
    if "--selftest" in args:
        return selftest(out, err)

    ledger_path = DEFAULT_LEDGER
    window_days = DEFAULT_WINDOW_DAYS
    min_attempts = DEFAULT_MIN_ATTEMPTS
    no_append = False
    summary_only = False
    want_json = False
    md_out = None
    prune_days = None
    apply_prune = False
    positional: list[str] = []

    i = 0
    while i < len(args):
        a = args[i]
        if a == "--ledger":
            if i + 1 >= len(args):
                print("[无法验证] --ledger 缺少路径", file=err)
                return EXIT_CANNOT
            ledger_path = Path(args[i + 1])
            i += 2
        elif a == "--window":
            if i + 1 >= len(args):
                print("[无法验证] --window 缺少天数", file=err)
                return EXIT_CANNOT
            try:
                window_days = int(args[i + 1])
            except ValueError:
                print(f"[无法验证] --window 需要整数，得到 {args[i + 1]!r}", file=err)
                return EXIT_CANNOT
            if window_days < 0:
                print("[无法验证] --window 不得为负（0 = 全部历史）", file=err)
                return EXIT_CANNOT
            i += 2
        elif a == "--min-attempts":
            if i + 1 >= len(args):
                print("[无法验证] --min-attempts 缺少数值", file=err)
                return EXIT_CANNOT
            try:
                min_attempts = int(args[i + 1])
            except ValueError:
                print(f"[无法验证] --min-attempts 需要整数，得到 {args[i + 1]!r}", file=err)
                return EXIT_CANNOT
            if min_attempts < 1:
                print("[无法验证] --min-attempts 须 ≥ 1", file=err)
                return EXIT_CANNOT
            i += 2
        elif a == "--no-append":
            no_append = True
            i += 1
        elif a == "--summary":
            summary_only = True
            i += 1
        elif a == "--json":
            want_json = True
            i += 1
        elif a == "--md":
            if i + 1 >= len(args):
                print("[无法验证] --md 缺少输出路径", file=err)
                return EXIT_CANNOT
            md_out = args[i + 1]
            i += 2
        elif a == "--prune-older-than":
            if i + 1 >= len(args):
                print("[无法验证] --prune-older-than 缺少天数", file=err)
                return EXIT_CANNOT
            try:
                prune_days = int(args[i + 1])
            except ValueError:
                print(f"[无法验证] --prune-older-than 需要整数，得到 {args[i + 1]!r}", file=err)
                return EXIT_CANNOT
            if prune_days < 1:
                print("[无法验证] --prune-older-than 须 ≥ 1", file=err)
                return EXIT_CANNOT
            i += 2
        elif a == "--yes":
            apply_prune = True
            i += 1
        elif a.startswith("--"):
            print(f"[无法验证] 未知参数: {a}", file=err)
            print(_USAGE, file=err)
            return EXIT_CANNOT
        else:
            positional.append(a)
            i += 1

    # --- 清理模式（与登记/出榜互斥，避免一次调用做两类事） ---
    if prune_days is not None:
        if positional:
            print("[无法验证] --prune-older-than 不接受输入文件（请分两次调用）", file=err)
            return EXIT_CANNOT
        return _cmd_prune(ledger_path, prune_days, apply_prune, out, err)

    if not positional and not summary_only:
        print(_USAGE, file=err)
        return EXIT_CANNOT

    try:
        engines = vr.load_engines()
    except vr.CannotValidate as e:
        print(f"[无法验证] {e}", file=err)
        return EXIT_CANNOT

    now = datetime.now(timezone.utc)

    # --- 只出榜：读台账 ---
    if not positional:
        records, problems = read_ledger(ledger_path)
        if problems:
            for p in problems:
                print(f"[FAIL] 台账损坏: {p}", file=err)
            return EXIT_DEFECT
        summary = summarize(records, window_days, min_attempts, now, engines)
        return _emit(summary, want_json, md_out, out, err)

    # --- 登记（或预演） ---
    batches, code = load_batches(positional, engines, err)
    if code is not None:
        return code

    records: list[dict] = []
    for _, batch in batches:
        records.extend(engine_records(batch, engines, now))

    if no_append:
        summary = summarize(records, window_days, min_attempts, now, engines)
        summary["notes"].append("--no-append 预演：未写入台账")
        return _emit(summary, want_json, md_out, out, err)

    existing, problems = read_ledger(ledger_path)
    if problems:
        for p in problems:
            print(f"[FAIL] 台账损坏: {p}", file=err)
        return EXIT_DEFECT

    added, skipped, problems = append_records(ledger_path, records, existing)
    if problems:
        for p in problems:
            print(f"[FAIL] {p}", file=err)
        return EXIT_DEFECT
    print(f"[台账] {ledger_path}：新增 {len(added)} 条 / "
          f"跳过 {len(skipped)} 条（同批次同引擎重复登记）", file=out)

    records_after, problems = read_ledger(ledger_path)
    if problems:
        for p in problems:
            print(f"[FAIL] 落账后复核失败: {p}", file=err)
        return EXIT_DEFECT
    summary = summarize(records_after, window_days, min_attempts, now, engines)
    return _emit(summary, want_json, md_out, out, err)


def _cmd_prune(ledger_path: Path, days: int, apply_: bool, out, err) -> int:
    now = datetime.now(timezone.utc)
    records, problems = read_ledger(ledger_path)
    if problems:
        for p in problems:
            print(f"[FAIL] 台账损坏: {p}", file=err)
        return EXIT_DEFECT
    if not records:
        print("[台账] 无记录可清理", file=out)
        return EXIT_OK

    cutoff = now - timedelta(days=days)
    keep, drop, undated = [], [], 0
    for r in records:
        dt = _parse_dt(r.get("fetched_at"))
        if dt is None:
            keep.append(r)      # 无法判龄的一律保留（不冤杀）
            undated += 1
        elif dt < cutoff:
            drop.append(r)
        else:
            keep.append(r)

    mode = "已清理" if apply_ else "预演（加 --yes 才落盘）"
    print(f"[台账] {mode}：丢弃 {len(drop)} 条 / 保留 {len(keep)} 条"
          f"（阈值 {days} 天，早于 {cutoff.date()}）", file=out)
    if undated:
        print(f"  其中 {undated} 条 fetched_at 无法解析，已保留", file=out)
    if drop:
        print("  涉及引擎：" + ", ".join(sorted({str(r.get('engine')) for r in drop})), file=out)

    if apply_ and drop:
        try:
            _atomic_write(ledger_path,
                          [json.dumps(r, ensure_ascii=False, sort_keys=True) for r in keep])
        except OSError as e:
            print(f"[无法验证] 清理写入失败: {e}", file=err)
            return EXIT_CANNOT
        back, back_problems = read_ledger(ledger_path)
        if back_problems or len(back) != len(keep):
            for p in back_problems:
                print(f"[FAIL] 清理回读校验: {p}", file=err)
            print(f"[FAIL] 清理回读条数不符: 期望 {len(keep)}，实得 {len(back)}", file=err)
            return EXIT_DEFECT
        print(f"[台账] 已落盘，现存 {len(back)} 条", file=out)
    return EXIT_OK


# ---------------------------------------------------------------- 自检
PROG = "engine_health.py"


def _batch(query: str, results: list[dict]) -> dict:
    return {"schema": vr.SCHEMA, "query": query, "language": "zh", "results": results}


def _r(engine, status="ok", title="标题", url="https://example.com/a",
       at="2026-10-13T09:00:00+08:00", rank=None):
    d = {"engine": engine, "status": status, "fetched_at": at}
    if status == "ok":
        d["title"] = title
        d["url"] = url
    if rank is not None:
        d["rank"] = rank
    return d


def _write_json(path: Path, obj) -> Path:
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return path


def selftest(out=sys.stdout, err=sys.stderr) -> int:
    """自检入口：崩溃一律判 FAIL（退出码 1），绝不与「通过」混淆。"""
    try:
        return _selftest_body(out, err)
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc(file=err)
        print(f"\n  [FAIL] 自检自身崩溃 —— 崩溃不等于通过：{type(e).__name__}: {e}", file=out)
        return EXIT_DEFECT


def _selftest_body(out, err) -> int:
    import io

    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, bool(ok), detail))
        mark = "[PASS]" if ok else "[FAIL]"
        print(f"  {mark} {name}" + (f"   ← {detail}" if detail and not ok else ""), file=out)

    print("mse.health/1 引擎健康度台账自检（离线夹具 + 临时目录，不碰真实台账）", file=out)

    engines = vr.load_engines()

    # ---------- A. 记录构建 ----------
    b1 = _batch("宠物食品 烘焙粮 适口性", [
        _r("bing cn", rank=1), _r("Baidu", rank=1), _r("Baidu", rank=2),
    ])
    recs = engine_records(b1, engines, now=datetime(2026, 10, 13, 9, 0, tzinfo=timezone.utc))
    check("A1 引擎名规范化：bing cn → Bing CN（读 config.json 真源）",
          any(r["engine"] == "Bing CN" for r in recs),
          str([r["engine"] for r in recs]))
    check("A2 每引擎一条记录", len(recs) == 2, str(len(recs)))
    need = {"schema", "batch_id", "recorded_at", "query", "engine",
            "status", "result_count", "fetched_at", "note"}
    check("A3 记录字段齐全", all(need <= set(r) for r in recs))
    check("A4 result_count = ok 条目数",
          [r["result_count"] for r in recs if r["engine"] == "Baidu"] == [2])
    check("A5 query 去空白", all(r["query"] == "宠物食品 烘焙粮 适口性" for r in recs))

    b_mix = _batch("q", [_r("Baidu", rank=1), _r("Baidu", status="blocked")])
    rmix = engine_records(b_mix, engines)[0]
    check("A6 混合状态 ok+blocked → status=ok 且 note 留痕",
          rmix["status"] == "ok" and rmix["note"] == "mixed:blocked",
          f"{rmix['status']}/{rmix['note']}")
    b_mix2 = _batch("q", [_r("Baidu", status="blocked"), _r("Baidu", status="error")])
    rmix2 = engine_records(b_mix2, engines)[0]
    check("A7 混合非 ok 取最严重（error > blocked，且与字典序不同）且 note 留痕",
          rmix2["status"] == "error" and rmix2["note"] == "mixed:blocked,error",
          f"{rmix2['status']}/{rmix2['note']}")

    check("A8 batch_id 同内容稳定（与文件名无关）",
          batch_id(b1) == batch_id(json.loads(json.dumps(b1))))
    b1_changed = json.loads(json.dumps(b1))
    b1_changed["results"][0]["title"] = "改过的标题"
    check("A9 batch_id 内容敏感（改标题即变）", batch_id(b1) != batch_id(b1_changed))

    # ---------- B. 台账 IO ----------
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        led = root / "engine-health.jsonl"
        p1 = _write_json(root / "a.json", b1)

        added, skipped, probs = append_records(led, engine_records(b1, engines), [])
        check("B1 首次登记 2 条、无问题", len(added) == 2 and not probs,
              f"{len(added)}/{probs}")
        check("B2 台账行数 = 2", len(read_ledger(led)[0]) == 2)

        added2, skipped2, probs2 = append_records(led, engine_records(b1, engines),
                                                  read_ledger(led)[0])
        check("B3 同内容重复登记 → 全跳过、行数不变",
              not added2 and len(skipped2) == 2 and not probs2
              and len(read_ledger(led)[0]) == 2,
              f"added={len(added2)} skipped={len(skipped2)}")

        p1b = _write_json(root / "a-copy.json", b1)   # 同内容换文件名
        added3, _, probs3 = append_records(led, engine_records(b1, engines),
                                           read_ledger(led)[0])
        check("B4 同内容换文件名 → 仍跳过（batch_id 认内容不认文件名）",
              not added3 and not probs3, f"added={len(added3)}")

        b2 = _batch("另一个 query", [_r("Sogou", status="empty")])
        append_records(led, engine_records(b2, engines), read_ledger(led)[0])
        check("B5 新批次追加后旧记录仍在（不丢历史）",
              {r["batch_id"] for r in read_ledger(led)[0]} == {batch_id(b1), batch_id(b2)})
        check("B6 追加后无临时文件残留",
              not list(root.glob("*.tmp")), str(list(root.glob('*.tmp'))))

        # 损坏行必须出声
        for name, line in [
            ("B7 损坏行：非 JSON", "{这不是 json"),
            ("B8 损坏行：缺字段", json.dumps({"schema": LEDGER_SCHEMA, "batch_id": "x"})),
            ("B9 损坏行：schema 不符", json.dumps({"schema": "other", "batch_id": "x",
                                                 "engine": "Baidu", "status": "ok",
                                                 "fetched_at": "2026-10-13T09:00:00+08:00"})),
            ("B10 损坏行：status 非法", json.dumps({"schema": LEDGER_SCHEMA, "batch_id": "x",
                                                  "engine": "Baidu", "status": "weird",
                                                  "fetched_at": "2026-10-13T09:00:00+08:00"})),
        ]:
            bad = root / "bad.jsonl"
            bad.write_text(json.dumps({"schema": LEDGER_SCHEMA, "batch_id": "ok1",
                                       "engine": "Baidu", "status": "ok",
                                       "fetched_at": "2026-10-13T09:00:00+08:00"},
                                      ensure_ascii=False) + "\n" + line + "\n", encoding="utf-8")
            _, bp = read_ledger(bad)
            check(name, len(bp) == 1 and "第 2 行" in bp[0], str(bp))

    # ---------- C. 汇总与判定 ----------
    def _recs(statuses, engine="Baidu", day=13):
        return [{"schema": LEDGER_SCHEMA, "batch_id": f"b{i}", "query": "q",
                 "engine": engine, "status": s, "result_count": 3,
                 "fetched_at": f"2026-10-{day:02d}T09:00:00+08:00", "note": None}
                for i, s in enumerate(statuses)]

    now = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)
    s_ok = summarize(_recs(["ok", "empty", "ok"]), 30, 3, now)
    e = s_ok["engines"][0]
    check("C1 可用率 3/3 → healthy", e["verdict"] == "healthy", e["verdict"])
    s_deg = summarize(_recs(["ok", "empty", "blocked", "error"]), 30, 3, now)
    check("C2 可用率 2/4 → degraded",
          s_deg["engines"][0]["verdict"] == "degraded", s_deg["engines"][0]["verdict"])
    s_un = summarize(_recs(["blocked", "error", "blocked"]), 30, 3, now)
    check("C3 可用率 0 → unavailable",
          s_un["engines"][0]["verdict"] == "unavailable", s_un["engines"][0]["verdict"])
    s_ins = summarize(_recs(["blocked", "blocked"]), 30, 3, now)
    v = s_ins["engines"][0]["verdict"]
    check("C4 样本 2 < 3 → insufficient-data（第三态）", v == "insufficient-data", v)
    check("C5 第三态保护：样本不足不得伪装成 unavailable",
          v != "unavailable" and s_ins["engines"][0]["verdict_basis"].startswith("attempts=2"),
          s_ins["engines"][0]["verdict_basis"])
    check("C6 blocked 不计入可用（C3 的前提）",
          s_un["engines"][0]["usable_rate"] == 0.0)
    check("C7 verdict_basis 记录样本数与门槛",
          s_ok["engines"][0]["verdict_basis"] == "attempts=3,min_attempts=3",
          s_ok["engines"][0]["verdict_basis"])

    s_win = summarize(_recs(["ok"], day=1) + _recs(["blocked"], day=13), 7, 3, now)
    check("C8 窗口排除旧记录且计数",
          s_win["excluded_by_window"] == 1 and s_win["record_count"] == 1,
          f"excl={s_win['excluded_by_window']} kept={s_win['record_count']}")
    check("C9 窗口外排除进 notes（降级有声音）",
          any("窗口外" in n for n in s_win["notes"]), str(s_win["notes"]))
    s_all = summarize(_recs(["ok"], day=1) + _recs(["blocked"], day=13), 0, 3, now)
    check("C10 window=0 取全部", s_all["record_count"] == 2 and s_all["excluded_by_window"] == 0)

    undated = [{"schema": LEDGER_SCHEMA, "batch_id": "u1", "query": "q", "engine": "Baidu",
                "status": "ok", "result_count": 1, "fetched_at": "not-a-date", "note": None}]
    s_un2 = summarize(undated, 7, 3, now)
    check("C11 fetched_at 不可解析 → 保留 + note（不冤杀）",
          s_un2["record_count"] == 1 and any("无法解析" in n for n in s_un2["notes"]),
          str(s_un2["notes"]))

    multi = _recs(["ok", "ok", "ok"]) + [
        {"schema": LEDGER_SCHEMA, "batch_id": "s1", "query": "q", "engine": "Sogou",
         "status": "ok", "result_count": 1, "fetched_at": "2026-10-13T09:00:00+08:00"}]
    s_rank = summarize(multi, 30, 3, now)
    check("C12 排名按可用率降序（Baidu 100% 在 Sogou 100% 前，样本多者优先）",
          [x["engine"] for x in s_rank["engines"]] == ["Baidu", "Sogou"],
          str([x["engine"] for x in s_rank["engines"]]))
    check("C13 状态合计", s_rank["counts"] == {"ok": 4, "empty": 0, "blocked": 0, "error": 0},
          str(s_rank["counts"]))

    s_none = summarize([], 30, 3, now)
    check("C14 无记录 → status=empty（域内负结果，不等于全挂）",
          s_none["status"] == "empty" and s_none["record_count"] == 0)

    hist = [{"schema": LEDGER_SCHEMA, "batch_id": "h1", "query": "q", "engine": "已下架引擎",
             "status": "ok", "result_count": 1, "fetched_at": "2026-10-13T09:00:00+08:00"}]
    s_hist = summarize(hist, 30, 3, now, engines)
    check("C15 历史引擎不在 config → note 说明（不崩）",
          any("不在当前 config.json" in n for n in s_hist["notes"]), str(s_hist["notes"]))

    # ---------- D. CLI 退出码 ----------
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        led = root / "ledger.jsonl"
        good = _write_json(root / "good.json", b1)

        buf, eb = io.StringIO(), io.StringIO()
        rc = main([PROG, str(good), "--ledger", str(led)], out=buf, err=eb)
        check("D1 合法输入 → exit 0 且建账", rc == EXIT_OK and led.exists(), f"rc={rc}")
        check("D2 登记条数播报", "新增 2 条" in buf.getvalue(), buf.getvalue()[:120])
        check("D3 榜含引擎可用率表", "引擎可用性榜" in buf.getvalue())

        buf, eb = io.StringIO(), io.StringIO()
        rc = main([PROG, str(good), "--ledger", str(led)], out=buf, err=eb)
        check("D4 重复登记 → exit 0 且跳过（幂等）",
              rc == EXIT_OK and "跳过 2 条" in buf.getvalue(), buf.getvalue()[:120])

        bad = _write_json(root / "bad-status.json",
                          _batch("q", [_r("Baidu", status="weird")]))
        buf, eb = io.StringIO(), io.StringIO()
        rc = main([PROG, str(bad), "--ledger", str(led)], out=buf, err=eb)
        check("D5 输入违规（V5）→ exit 1", rc == EXIT_DEFECT, f"rc={rc} {eb.getvalue()[:80]}")

        buf, eb = io.StringIO(), io.StringIO()
        rc = main([PROG, str(root / "nope.json"), "--ledger", str(led)], out=buf, err=eb)
        check("D6 输入不存在 → exit 3", rc == EXIT_CANNOT, f"rc={rc}")

        notjson = root / "plain.txt"
        notjson.write_text("hello", encoding="utf-8")
        buf, eb = io.StringIO(), io.StringIO()
        rc = main([PROG, str(notjson), "--ledger", str(led)], out=buf, err=eb)
        check("D7 输入非 JSON → exit 3", rc == EXIT_CANNOT, f"rc={rc}")

        buf, eb = io.StringIO(), io.StringIO()
        rc = main([PROG], out=buf, err=eb)
        check("D8 无参数无 --summary → exit 3 + 用法", rc == EXIT_CANNOT and "用法" in eb.getvalue())

        buf, eb = io.StringIO(), io.StringIO()
        rc = main([PROG, "--bogus"], out=buf, err=eb)
        check("D9 未知参数 → exit 3", rc == EXIT_CANNOT and "未知参数" in eb.getvalue())

        buf, eb = io.StringIO(), io.StringIO()
        rc = main([PROG, str(good), "--window", "abc", "--ledger", str(led)], out=buf, err=eb)
        check("D10 --window 非整数 → exit 3", rc == EXIT_CANNOT)

        # 只出榜：无台账 → 域内负结果
        buf, eb = io.StringIO(), io.StringIO()
        rc = main([PROG, "--summary", "--ledger", str(root / "none.jsonl"), "--json"],
                  out=buf, err=eb)
        payload = json.loads(buf.getvalue())
        check("D11 无台账 → exit 0 且 status=empty",
              rc == EXIT_OK and payload["status"] == "empty", f"rc={rc}")

        # --no-append 不落账
        preview_led = root / "preview.jsonl"
        buf, eb = io.StringIO(), io.StringIO()
        rc = main([PROG, str(good), "--no-append", "--ledger", str(preview_led)],
                  out=buf, err=eb)
        check("D12 --no-append → exit 0 且不建账、有预演标注",
              rc == EXIT_OK and not preview_led.exists()
              and "未写入台账" in buf.getvalue())

        # --json / --md
        buf, eb = io.StringIO(), io.StringIO()
        rc = main([PROG, "--summary", "--ledger", str(led), "--json"], out=buf, err=eb)
        payload = json.loads(buf.getvalue())
        check("D13 --json 输出可解析且 schema 正确",
              rc == EXIT_OK and payload["schema"] == SUMMARY_SCHEMA)
        md_path = root / "report.md"
        buf, eb = io.StringIO(), io.StringIO()
        rc = main([PROG, "--summary", "--ledger", str(led), "--md", str(md_path)],
                  out=buf, err=eb)
        check("D14 --md 落盘且含表格",
              rc == EXIT_OK and md_path.exists() and "| 引擎 |" in md_path.read_text(encoding="utf-8"))

        # 多 query 批次允许（台账的语义本就跨 query）
        q2 = _write_json(root / "q2.json", _batch("完全不同的检索词", [_r("Sogou", status="empty")]))
        buf, eb = io.StringIO(), io.StringIO()
        rc = main([PROG, str(good), str(q2), "--ledger", str(led)], out=buf, err=eb)
        check("D15 多 query 批次允许（与 M5 的有意差异）",
              rc == EXIT_OK and "新增 1 条" in buf.getvalue(), f"rc={rc} {eb.getvalue()[:80]}")

        # 清理：dry-run 不动盘
        before = led.read_text(encoding="utf-8")
        buf, eb = io.StringIO(), io.StringIO()
        rc = main([PROG, "--prune-older-than", "3650", "--ledger", str(led)], out=buf, err=eb)
        check("D16 清理 dry-run → exit 0 且磁盘不变",
              rc == EXIT_OK and led.read_text(encoding="utf-8") == before
              and "预演" in buf.getvalue())

        # 造一条老记录后真清理
        old = root / "old.jsonl"
        old.write_text(json.dumps({"schema": LEDGER_SCHEMA, "batch_id": "old1", "query": "q",
                                   "engine": "Baidu", "status": "blocked", "result_count": 0,
                                   "fetched_at": "2020-01-01T09:00:00+08:00"},
                                  ensure_ascii=False) + "\n", encoding="utf-8")
        buf, eb = io.StringIO(), io.StringIO()
        rc = main([PROG, "--prune-older-than", "30", "--yes", "--ledger", str(old)],
                  out=buf, err=eb)
        left = read_ledger(old)[0]
        check("D17 真清理 → 老记录被删、新记录保留、回读一致",
              rc == EXIT_OK and left == [], f"rc={rc} left={len(left)}")

        # 清理保留无法判龄的
        mixed = root / "mixed.jsonl"
        mixed.write_text(
            json.dumps({"schema": LEDGER_SCHEMA, "batch_id": "m1", "query": "q",
                        "engine": "Baidu", "status": "ok", "result_count": 1,
                        "fetched_at": "2020-01-01T09:00:00+08:00"}, ensure_ascii=False) + "\n"
            + json.dumps({"schema": LEDGER_SCHEMA, "batch_id": "m2", "query": "q",
                          "engine": "Sogou", "status": "ok", "result_count": 1,
                          "fetched_at": "bad-date"}, ensure_ascii=False) + "\n",
            encoding="utf-8")
        buf, eb = io.StringIO(), io.StringIO()
        rc = main([PROG, "--prune-older-than", "30", "--yes", "--ledger", str(mixed)],
                  out=buf, err=eb)
        left_ids = {r["batch_id"] for r in read_ledger(mixed)[0]}
        check("D18 清理保留 fetched_at 不可解析的记录",
              rc == EXIT_OK and left_ids == {"m2"}, f"rc={rc} {left_ids}")

    # ---------- E. 真源依赖证伪 ----------
    orig_root = vr.ROOT
    try:
        empty_dir = Path(tempfile.mkdtemp())
        vr.ROOT = empty_dir                      # 无 config.json
        buf, eb = io.StringIO(), io.StringIO()
        rc = main([PROG, "--summary"], out=buf, err=eb)
        check("E1 真源缺失 → exit 3（不冒充缺陷）",
              rc == EXIT_CANNOT and "无法验证" in eb.getvalue(), f"rc={rc}")

        cfg_dir = Path(tempfile.mkdtemp())
        (cfg_dir / "config.json").write_text(json.dumps(
            {"engines": [{"name": "Baidu"}]}, ensure_ascii=False), encoding="utf-8")
        vr.ROOT = cfg_dir                        # 真源只剩 Baidu
        batch_other = _write_json(cfg_dir / "x.json",
                                  _batch("q", [_r("Bing CN")]))
        buf, eb = io.StringIO(), io.StringIO()
        rc = main([PROG, str(batch_other), "--no-append"], out=buf, err=eb)
        check("E2 真源改为只含 Baidu 后 Bing CN 判违规 → exit 1（证明真在被读）",
              rc == EXIT_DEFECT and "V4" in eb.getvalue(), f"rc={rc} {eb.getvalue()[:100]}")
        batch_ok = _write_json(cfg_dir / "y.json", _batch("q", [_r("baidu")]))
        buf, eb = io.StringIO(), io.StringIO()
        rc = main([PROG, str(batch_ok), "--no-append"], out=buf, err=eb)
        check("E3 同一真源下 baidu（小写）→ exit 0（规范化生效）",
              rc == EXIT_OK and "Baidu" in buf.getvalue(), f"rc={rc} {eb.getvalue()[:80]}")
    finally:
        vr.ROOT = orig_root

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"\n自检结果：{passed}/{total} 通过", file=out)
    if passed != total:
        print("失败项：", file=out)
        for name, ok, detail in results:
            if not ok:
                print(f"  - {name}   ← {detail}", file=out)
        return EXIT_DEFECT
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv))
