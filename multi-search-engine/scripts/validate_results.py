# -*- coding: utf-8 -*-
"""mse.result/1 检索结果契约校验器

契约定义见 references/result-contract.md。

职责：把「一次多引擎检索」的产出机械校验为可消费结构，
使「某条结果只有单引擎命中」这类判断不再依赖人眼。

退出码（三态，禁止把「没能验证」冒充「已损坏」）：
  0 = 通过
  1 = 存在违规（被测数据确有缺陷）
  3 = 无法验证（缺 config.json；输入不存在或非 JSON）

用法：
  python validate_results.py results.json
  python validate_results.py results.json --json
  python validate_results.py results.json --summary
  python validate_results.py --selftest
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

try:  # Windows 控制台默认 GBK，会炸中文
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent

SCHEMA = "mse.result/1"
STATUSES = ("ok", "empty", "blocked", "error")
LANGS = ("zh", "en", "other")

EXIT_OK = 0
EXIT_VIOLATION = 1
EXIT_CANNOT = 3

_URL_RE = re.compile(r"^https?://[^/\s]+", re.I)


class CannotValidate(Exception):
    """环境/输入前置条件不足 —— 对应 exit 3，永不等同于「有缺陷」。"""


# ---------------------------------------------------------------- 真源
def load_engines() -> dict[str, str]:
    """返回 {归一化引擎名: 规范名}。缺失或不可解析 → CannotValidate。"""
    p = ROOT / "config.json"
    if not p.exists():
        raise CannotValidate(f"真源缺失: {p}")
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        raise CannotValidate(f"真源不可解析: {e}") from e
    out: dict[str, str] = {}
    for e in d.get("engines", []):
        name = e.get("name")
        if isinstance(name, str) and name.strip():
            out[re.sub(r"\s+", " ", name).strip().lower()] = name
    if not out:
        raise CannotValidate("真源 config.json 无引擎条目")
    return out


# ---------------------------------------------------------------- 规则
def _iso_with_tz_ok(v) -> bool:
    """必须可解析为 ISO 8601 且**含时区**（无时区的时间戳无法跨引擎对齐）。"""
    if not isinstance(v, str) or not v.strip():
        return False
    try:
        dt = datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
    except ValueError:
        return False
    return dt.tzinfo is not None


def validate(batch, engines: dict[str, str]) -> list[dict]:
    """返回违规清单；空列表 = 通过。每条违规带 id（= 契约规则号）便于机械断言。"""
    V: list[dict] = []

    def add(vid: str, path: str, msg: str) -> None:
        V.append({"id": vid, "path": path, "msg": msg})

    if not isinstance(batch, dict):
        add("V1", "$", f"顶层必须是对象，得到 {type(batch).__name__}")
        return V

    # V1 schema
    if batch.get("schema") != SCHEMA:
        add("V1", "$.schema", f"应为 {SCHEMA!r}，得到 {batch.get('schema')!r}")

    # V2 query
    q = batch.get("query")
    if not isinstance(q, str) or not q.strip():
        add("V2", "$.query", "必须为非空字符串")

    # V11 language（可选字段）
    if "language" in batch and batch["language"] not in LANGS:
        add("V11", "$.language", f"应为 {LANGS} 之一，得到 {batch['language']!r}")

    # V3 results
    res = batch.get("results")
    if not isinstance(res, list):
        add("V3", "$.results", f"必须为数组，得到 {type(res).__name__}")
        return V

    for n, item in enumerate(res):
        p = f"$.results[{n}]"
        if not isinstance(item, dict):
            add("V3", p, f"条目必须是对象，得到 {type(item).__name__}")
            continue

        # V4 engine ∈ config.json
        eng = item.get("engine")
        if not isinstance(eng, str) or not eng.strip():
            add("V4", f"{p}.engine", "必须为非空字符串")
        elif re.sub(r"\s+", " ", eng).strip().lower() not in engines:
            add("V4", f"{p}.engine", f"{eng!r} 不在 config.json 引擎表中")

        # V5 status 四态
        st = item.get("status")
        if st not in STATUSES:
            add("V5", f"{p}.status", f"应为 {STATUSES} 之一，得到 {st!r}")

        # V6 fetched_at 含时区
        if not _iso_with_tz_ok(item.get("fetched_at")):
            add("V6", f"{p}.fetched_at", "必须是含时区的 ISO 8601 时间戳")

        # V7 status=ok 必须带 title / url
        if st == "ok":
            for k in ("title", "url"):
                v = item.get(k)
                if not isinstance(v, str) or not v.strip():
                    add("V7", f"{p}.{k}", "status=ok 时不可为空")

        # V8 url 形态
        u = item.get("url")
        if isinstance(u, str) and u.strip() and not _URL_RE.match(u.strip()):
            add("V8", f"{p}.url", f"{u!r} 不是 http(s):// 形式")

        # V9 rank
        if "rank" in item:
            r = item["rank"]
            if not isinstance(r, int) or isinstance(r, bool) or r < 1:
                add("V9", f"{p}.rank", f"应为 ≥1 的整数，得到 {r!r}")

    # V10 同引擎内 rank 重复
    seen: dict[tuple[str, int], int] = {}
    for n, item in enumerate(res):
        if not isinstance(item, dict):
            continue
        eng, r = item.get("engine"), item.get("rank")
        if isinstance(eng, str) and isinstance(r, int) and not isinstance(r, bool):
            key = (re.sub(r"\s+", " ", eng).strip().lower(), r)
            if key in seen:
                add("V10", f"$.results[{n}].rank",
                    f"引擎 {eng} 的 rank={r} 与 results[{seen[key]}] 重复")
            else:
                seen[key] = n

    return V


# ---------------------------------------------------------------- 统计
def summarize(batch) -> dict:
    """按引擎×状态计数 —— M5 交叉核验器 / M6 健康台账的输入。"""
    per: dict[str, dict[str, int]] = {}
    res = batch.get("results") if isinstance(batch, dict) else None
    if isinstance(res, list):
        for it in res:
            if not isinstance(it, dict):
                continue
            eng = it.get("engine")
            st = it.get("status")
            if not isinstance(eng, str):
                continue
            st = st if st in STATUSES else "invalid"
            per.setdefault(eng, {}).setdefault(st, 0)
            per[eng][st] += 1
    return {
        "engines_reporting": len(per),
        "engines_with_ok": sum(1 for c in per.values() if c.get("ok")),
        "per_engine": per,
    }


# ---------------------------------------------------------------- 自检
_BASE_RESULT = {
    "engine": "Baidu", "status": "ok",
    "title": "Python 官方教程", "url": "https://www.python.org/",
    "rank": 1, "fetched_at": "2026-10-12T22:40:00+08:00",
}


def _batch(**over):
    b = {"schema": SCHEMA, "query": "python 教程", "language": "zh",
         "results": [dict(_BASE_RESULT)]}
    b.update(over)
    return b


def _case(name, batch, exp_exit, exp_ids):
    return {"name": name, "batch": batch, "exp_exit": exp_exit, "exp_ids": set(exp_ids)}


def selftest() -> int:
    """自检：既证明「该过的过」，也证明「该红的红」且红在**正确的规则号**上。

    只断言退出码是不够的 —— 一条永远为红的守卫与一条正确守卫无法区分；
    因此每个反向用例都断言它命中的 check id。
    """
    try:
        engines = load_engines()
    except CannotValidate as e:
        print(f"[无法验证] {e}")
        return EXIT_CANNOT

    cases: list[dict] = []

    # —— 应当通过 ——
    cases.append(_case("合法 batch", _batch(), EXIT_OK, []))
    cases.append(_case("results 为空数组（全引擎无结果）",
                       _batch(results=[]), EXIT_OK, []))
    cases.append(_case("引擎名大小写不敏感（bing cn）",
                       _batch(results=[dict(_BASE_RESULT, engine="bing cn")]), EXIT_OK, []))
    cases.append(_case("blocked 条目无需 title/url",
                       _batch(results=[{"engine": "360", "status": "blocked",
                                        "fetched_at": "2026-10-12T22:40:00+08:00"}]),
                       EXIT_OK, []))
    cases.append(_case("Z 结尾 UTC 时间戳可解析",
                       _batch(results=[dict(_BASE_RESULT, fetched_at="2026-10-12T14:40:00Z")]),
                       EXIT_OK, []))

    # —— 应当失败，且必须红在指定规则号 ——
    cases.append(_case("schema 错误", _batch(schema="mse.result/2"), EXIT_VIOLATION, ["V1"]))
    cases.append(_case("query 为空", _batch(query=""), EXIT_VIOLATION, ["V2"]))
    cases.append(_case("results 非数组", _batch(results="oops"), EXIT_VIOLATION, ["V3"]))
    cases.append(_case("引擎名非法",
                       _batch(results=[dict(_BASE_RESULT, engine="NotAnEngine")]),
                       EXIT_VIOLATION, ["V4"]))
    cases.append(_case("status 非法",
                       _batch(results=[dict(_BASE_RESULT, status="maybe")]),
                       EXIT_VIOLATION, ["V5"]))
    cases.append(_case("fetched_at 无时区",
                       _batch(results=[dict(_BASE_RESULT, fetched_at="2026-10-12T22:40:00")]),
                       EXIT_VIOLATION, ["V6"]))
    cases.append(_case("ok 但缺 title",
                       _batch(results=[dict(_BASE_RESULT, title="")]),
                       EXIT_VIOLATION, ["V7"]))
    cases.append(_case("url 非 http",
                       _batch(results=[dict(_BASE_RESULT, url="ftp://x/y")]),
                       EXIT_VIOLATION, ["V8"]))
    cases.append(_case("rank 为 0",
                       _batch(results=[dict(_BASE_RESULT, rank=0)]),
                       EXIT_VIOLATION, ["V9"]))
    cases.append(_case("同引擎 rank 重复",
                       _batch(results=[dict(_BASE_RESULT),
                                       dict(_BASE_RESULT, title="另一条",
                                            url="https://example.com/b")]),
                       EXIT_VIOLATION, ["V10"]))
    cases.append(_case("language 非法", _batch(language="jp"), EXIT_VIOLATION, ["V11"]))
    cases.append(_case("status=empty 但带非法 url",
                       _batch(results=[{"engine": "Sogou", "status": "empty",
                                        "url": "not-a-url",
                                        "fetched_at": "2026-10-12T22:40:00+08:00"}]),
                       EXIT_VIOLATION, ["V8"]))

    fails: list[str] = []
    for c in cases:
        V = validate(c["batch"], engines)
        got_ids = {v["id"] for v in V}
        got_exit = EXIT_OK if not V else EXIT_VIOLATION

        if got_exit != c["exp_exit"]:
            fails.append(f"{c['name']}: 期望 exit={c['exp_exit']}，实得 {got_exit}（{sorted(got_ids)}）")
            continue
        if c["exp_ids"] and not c["exp_ids"] <= got_ids:
            fails.append(f"{c['name']}: 期望命中 {sorted(c['exp_ids'])}，实得 {sorted(got_ids)}")
            continue
        if c["exp_exit"] == EXIT_OK and got_ids:
            fails.append(f"{c['name']}: 期望通过，却报了 {sorted(got_ids)}")
            continue
        if c["exp_exit"] == EXIT_OK and V:
            fails.append(f"{c['name']}: 期望无违规，实得 {len(V)} 条")

    print("=" * 74)
    print("validate_results.py 自检  (真源 = config.json)")
    print("=" * 74)
    print(f"引擎表: {len(engines)} 个   |   用例: {len(cases)}")
    print("-" * 74)
    for c in cases:
        V = validate(c["batch"], engines)
        got_ids = {v["id"] for v in V}
        got_exit = EXIT_OK if not V else EXIT_VIOLATION
        ok = (got_exit == c["exp_exit"]
              and (not c["exp_ids"] or c["exp_ids"] <= got_ids)
              and not (c["exp_exit"] == EXIT_OK and got_ids))
        mark = "OK  " if ok else "FAIL"
        ids = f" 命中 {sorted(got_ids)}" if got_ids else ""
        print(f"[{mark}] exit={got_exit}  期望={c['exp_exit']}  {c['name']}{ids}")
    print("-" * 74)
    print(f"失败用例: {len(fails)} / {len(cases)}")
    for f in fails:
        print(f"  ✗ {f}")
    print("=" * 74)
    return EXIT_VIOLATION if fails else EXIT_OK


# ---------------------------------------------------------------- 主流程
def _usage() -> None:
    print(__doc__ or "用法: validate_results.py <results.json> [--json] [--summary]")


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return selftest()

    positional = [a for a in argv[1:] if not a.startswith("--")]
    if not positional:
        _usage()
        return EXIT_CANNOT

    try:
        engines = load_engines()
    except CannotValidate as e:
        print(f"[无法验证] {e}")
        return EXIT_CANNOT

    path = Path(positional[0])
    if not path.exists():
        print(f"[无法验证] 输入文件不存在: {path}")
        return EXIT_CANNOT
    try:
        batch = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        print(f"[无法验证] 输入不是合法 JSON: {e}")
        return EXIT_CANNOT

    V = validate(batch, engines)
    summary = summarize(batch)

    if "--json" in argv:
        print(json.dumps({"ok": not V, "violations": V, "summary": summary},
                         ensure_ascii=False, indent=2))
    else:
        print("=" * 74)
        print(f"契约校验: {path}")
        print("=" * 74)
        if not V:
            print("[OK  ] 通过 —— 无违规")
        else:
            for v in V:
                print(f"[FAIL] {v['id']:<4} {v['path']:<28} {v['msg']}")
        if "--summary" in argv or V:
            s = summary
            print("-" * 74)
            print(f"引擎上报数: {s['engines_reporting']}   含 ok 结果: {s['engines_with_ok']}")
            for eng, cnt in sorted(s["per_engine"].items()):
                detail = "  ".join(f"{k}={v}" for k, v in sorted(cnt.items()))
                print(f"  {eng:<12} {detail}")
        print("-" * 74)
        print(f"违规项: {len(V)}")
        print("=" * 74)

    return EXIT_OK if not V else EXIT_VIOLATION


if __name__ == "__main__":
    sys.exit(main(sys.argv))
