# -*- coding: utf-8 -*-
"""search-report 交叉核验器（mse.report/1）

契约定义见 references/result-contract.md（输入）与 references/report-contract.md（输出）。

职责：把「一次多引擎检索」的产出（mse.result/1）固化为**可机械判定的核验报告**，
使「某条结果只有单个引擎命中」不再依赖人眼扫报告。

核心判定（三态分离，禁止把「没得验」冒充「待核」）：
  cross-verified      该条目被 ≥min_engines 个**不同引擎**命中 → 已交叉印证
  single-engine       引擎可用数 ≥min_engines，但该条目只有 1 个引擎命中 → **待核**
  insufficient-engines 有 ok 结果的引擎数 < min_engines → 无从交叉，**无法核验**

第三态不是第一态的弱化：把「只有 1 个引擎成功返回」也算成「待核」，
会让「引擎全挂」伪装成「这条存疑」，既误导判断也污染上游统计。

退出码（三态，禁止把「没能验证」冒充「已损坏」）：
  0 = 核验完成（含 insufficient-engines 这类域内负结果）
  1 = 输入有缺陷（契约违规 / 多批次 query 不一致）
  3 = 无法验证（缺 config.json；输入文件不存在或非 JSON）

用法：
  python search_report.py results.json
  python search_report.py a.json b.json --md -o report.md
  python search_report.py results.json --json
  python search_report.py results.json --min-engines 3
  python search_report.py --selftest
"""
from __future__ import annotations

import difflib
import json
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

try:  # Windows 控制台默认 GBK，会炸中文
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate_results as vr  # noqa: E402  复用契约校验，不复制判据

ROOT = Path(__file__).resolve().parent.parent

REPORT_SCHEMA = "mse.report/1"
EXIT_OK = 0
EXIT_DEFECT = 1
EXIT_CANNOT = 3

DEFAULT_MIN_ENGINES = 2
DEFAULT_TITLE_THRESHOLD = 0.90

# 标题合并的上限：超过这个组数就跳过标题维度合并，并在 notes 里出声
# （降级必须有声音，且降级不等于通过）
TITLE_MERGE_MAX_GROUPS = 500

# URL 跟踪参数黑名单（显式列出，不用模糊猜测）
TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "utm_cid", "utm_reader", "utm_name", "utm_social",
    "fbclid", "gclid", "msclkid", "dclid", "yclid", "igshid", "igsh",
    "spm", "share_token", "share_source", "share_medium", "from", "src",
    "ref", "referrer", "scene", "vd_source",
}

# 标题归一化时剥离的连接/装饰符（只剥「分隔类」，不动内容字符）
_TITLE_STRIP = " \t\r\n\u3000-_|/\\>»>»«<【】[]()（）{}<>《》~*#·•—–=+.,;:!?。，；：！？、"


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


# ---------------------------------------------------------------- 归一化
def norm_url(url: str) -> str:
    """把「同一页面」的不同写法收敛到同一个键。

    处理：scheme/host 小写、去 www.、去默认端口、去 fragment、
    去跟踪参数（其余 query 参数排序保留）、去尾斜杠。
    不处理：页面实际内容差异（那是标题维度的事）。
    """
    if not isinstance(url, str):
        return ""
    u = url.strip()
    if not u:
        return ""
    m = re.match(r"^([a-zA-Z][a-zA-Z0-9+.-]*)://([^/?#]*)", u)
    if not m:
        return u.rstrip("/")
    scheme, hostport = m.group(1).lower(), m.group(2).lower()
    host = hostport
    port = ""
    if host.count(":") == 1:
        host, port = host.split(":", 1)
        if port in ("80", "443"):
            port = ""
    if host.startswith("www."):
        host = host[4:]
    netloc = host + (f":{port}" if port else "")

    rest = u[m.end():]
    frag = ""
    if "#" in rest:
        rest, frag = rest.split("#", 1)
    path, _, query = rest.partition("?")
    if path != "/" :
        path = path.rstrip("/")
    if not path:
        path = "/"

    if query:
        pairs = []
        for kv in query.split("&"):
            if not kv:
                continue
            k = kv.split("=", 1)[0].lower()
            if k in TRACKING_PARAMS:
                continue
            pairs.append(kv)
        query = "&".join(sorted(pairs))

    out = f"{netloc}{path}"
    return f"{out}?{query}" if query else out


def norm_title(title: str) -> str:
    """标题归一化：去空白、小写、剥分隔类装饰符。

    只做「同一标题的不同书写形态」收敛；不同标题不会被误合并
    （最终合并还受 title_threshold 约束）。
    """
    if not isinstance(title, str):
        return ""
    t = title.strip().lower()
    t = re.sub(r"\s+", "", t)
    return t.strip(_TITLE_STRIP)


def title_similarity(a: str, b: str) -> float:
    """归一化标题的相似度（0~1）。"""
    na, nb = norm_title(a), norm_title(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return difflib.SequenceMatcher(None, na, nb).ratio()


# ---------------------------------------------------------------- 聚类
class _UF:
    """并查集：按 URL 精确分组后，再按标题相似度跨组合并。"""

    def __init__(self, n: int) -> None:
        self.p = list(range(n))

    def find(self, x: int) -> int:
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def cluster_entries(results: list[dict], engines: dict[str, str],
                    title_threshold: float) -> tuple[list[dict], list[str]]:
    """把 ok 条目聚成「同一信息」的簇。

    engines: {归一化引擎名: 规范名}（来自 config.json 真源）
    返回 (clusters, notes)。每个 cluster:
      {engines, engine_count, entries, matched_by, urls, titles}
    matched_by: "url"  = URL 归一化后相同；"title" = URL 不同但标题足够相似。

    两阶段：先按归一化 URL 精确分组（并查集天然分组），
    再对**组间**做标题相似度合并 —— 百度跳转链接与原站 URL 形式不同，
    只有标题维度能识别它们是同一篇。
    """
    notes: list[str] = []
    ok_items = [r for r in results
                if isinstance(r, dict) and r.get("status") == "ok"]

    # 阶段 1：按归一化 URL 精确分组
    by_url: dict[str, list[int]] = {}
    for i, it in enumerate(ok_items):
        by_url.setdefault(norm_url(it.get("url", "")), []).append(i)
    groups: list[list[int]] = list(by_url.values())

    # 阶段 2：组间标题相似度合并（超上限则跳过并在 notes 出声）
    uf = _UF(len(groups))
    if len(groups) <= TITLE_MERGE_MAX_GROUPS:
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                a_titles = [ok_items[k].get("title", "") for k in groups[i]]
                b_titles = [ok_items[k].get("title", "") for k in groups[j]]
                best = max((title_similarity(a, b)
                            for a in a_titles for b in b_titles), default=0.0)
                if best >= title_threshold:
                    uf.union(i, j)
    else:
        notes.append(
            f"URL 分组数 {len(groups)} 超过 {TITLE_MERGE_MAX_GROUPS}，"
            f"已跳过标题维度合并（仅按 URL 归一化聚类）—— 结论可能偏保守"
        )

    merged: dict[int, list[int]] = {}
    for gi in range(len(groups)):
        merged.setdefault(uf.find(gi), []).extend(groups[gi])

    clusters: list[dict] = []
    for idxs in merged.values():
        items = [ok_items[k] for k in sorted(idxs)]
        engines_seen: list[str] = []
        for it in items:
            raw = str(it.get("engine", "")).strip()
            canon = engines.get(re.sub(r"\s+", " ", raw).lower(), raw)
            if canon and canon not in engines_seen:
                engines_seen.append(canon)
        urls: list[str] = []
        for it in items:
            u = it.get("url", "")
            if u and u not in urls:
                urls.append(u)
        titles: list[str] = []
        for it in items:
            t = it.get("title", "")
            if t and t not in titles:
                titles.append(t)
        clusters.append({
            "engines": engines_seen,
            "engine_count": len(engines_seen),
            "entries": items,
            "matched_by": "title" if len({norm_url(u) for u in urls}) > 1 else "url",
            "urls": urls,
            "titles": titles,
        })

    # 排序：先按引擎数降序（已印证的排前面），再按标题，保证输出稳定
    clusters.sort(key=lambda c: (-c["engine_count"], c["titles"][0] if c["titles"] else ""))
    return clusters, notes


# ---------------------------------------------------------------- 核验
def cross_check(results: list[dict], engines: dict[str, str],
                min_engines: int, title_threshold: float) -> dict:
    """对合并后的 results 做交叉核验。

    engines: {归一化引擎名: 规范名}（来自 config.json 真源）
    """
    per: dict[str, dict[str, int]] = {}
    for it in results:
        if not isinstance(it, dict):
            continue
        eng = it.get("engine")
        if not isinstance(eng, str) or not eng.strip():
            continue
        st = it.get("status")
        st = st if st in vr.STATUSES else "invalid"
        per.setdefault(eng, {}).setdefault(st, 0)
        per[eng][st] += 1

    engines_with_ok = sorted(
        (e for e, c in per.items() if c.get("ok")),
        key=str.lower,
    )

    clusters, notes = cluster_entries(results, engines, title_threshold)
    counts = {"cross-verified": 0, "single-engine": 0, "insufficient-engines": 0}
    verdict_clusters: list[dict] = []

    for c in clusters:
        if c["engine_count"] >= min_engines:
            verdict = "cross-verified"
        elif len(engines_with_ok) >= min_engines:
            # 引擎够多却只有一家命中 → 这条**应当被质疑**
            verdict = "single-engine"
        else:
            # 引擎本就不够 → 无从交叉，**不得**记作「待核」
            verdict = "insufficient-engines"
        counts[verdict] += 1
        verdict_clusters.append(dict(c, verdict=verdict))

    return {
        "engines_reporting": len(per),
        "engines_with_ok": len(engines_with_ok),
        "engines_with_ok_names": engines_with_ok,
        "per_engine": per,
        "min_engines": min_engines,
        "verdict_basis": (
            f"engines_with_ok={len(engines_with_ok)} vs min_engines={min_engines}"
        ),
        "clusters": verdict_clusters,
        "counts": counts,
        "pending_review": [c for c in verdict_clusters if c["verdict"] == "single-engine"],
        "notes": notes,
    }


# ---------------------------------------------------------------- 输入
def load_batches(paths: list[str]) -> tuple[list[dict], list[str]]:
    """读入并校验所有批次。返回 (batches, 问题清单)。

    问题分两级：环境/前置不足 → 由调用方转 exit 3；数据缺陷 → exit 1。
    """
    problems: list[str] = []
    try:
        engines = vr.load_engines()
    except vr.CannotValidate as e:
        return [], [f"CANNOT:{e}"]

    batches: list[dict] = []
    for p in paths:
        path = Path(p)
        if not path.exists():
            return [], [f"CANNOT:输入文件不存在: {path}"]
        try:
            batch = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            return [], [f"CANNOT:输入不是合法 JSON: {path}: {e}"]
        V = vr.validate(batch, engines)
        if V:
            for v in V:
                problems.append(f"VIOLATION:{path.name} {v['id']} {v['path']} {v['msg']}")
            continue
        batches.append(batch)

    if batches:
        queries = {b.get("query", "").strip() for b in batches}
        if len(queries) > 1:
            problems.append(
                "VIOLATION:多批次 query 不一致: " + " | ".join(sorted(queries))
            )
        langs = {b.get("language") for b in batches if "language" in b}
        if len(langs) > 1:
            problems.append(
                "VIOLATION:多批次 language 不一致: " + " | ".join(sorted(str(x) for x in langs))
            )

    return batches, problems


# ---------------------------------------------------------------- 渲染
def _esc(s: str) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def render_markdown(report: dict) -> str:
    """人读核验表。"""
    cc = report["cross_check"]
    q = report["query"]
    lines: list[str] = []
    lines.append(f"# 检索交叉核验报告（{REPORT_SCHEMA}）")
    lines.append("")
    lines.append(f"- **query**：{q}")
    lines.append(f"- **生成时间**：{report['generated_at']}")
    lines.append(
        f"- **引擎上报**：{cc['engines_reporting']} 个；"
        f"**含 ok 结果**：{cc['engines_with_ok']} 个"
        + (f"（{', '.join(cc['engines_with_ok_names'])}）" if cc["engines_with_ok_names"] else "")
    )
    lines.append(f"- **判定基数**：{cc['verdict_basis']}")
    lines.append(
        f"- **参数**：min_engines={cc['min_engines']}，"
        f"title_threshold={report['params']['title_threshold']}"
    )
    if report.get("sources"):
        lines.append(f"- **输入批次**：{', '.join(report['sources'])}")
    lines.append("")

    c = cc["counts"]
    lines.append("## 汇总")
    lines.append("")
    lines.append("| 判定 | 条目簇 | 含义 |")
    lines.append("|---|---|---|")
    lines.append(f"| `cross-verified` | {c['cross-verified']} | ≥{cc['min_engines']} 个引擎命中，已交叉印证 |")
    lines.append(f"| `single-engine` | {c['single-engine']} | **待核**：引擎够但只有一家命中 |")
    lines.append(f"| `insufficient-engines` | {c['insufficient-engines']} | 无从交叉，无法核验 |")
    lines.append("")

    if cc["pending_review"]:
        lines.append(f"## 待核清单（仅单引擎命中，{len(cc['pending_review'])} 条）")
        lines.append("")
        lines.append("| # | 引擎 | 标题 | URL |")
        lines.append("|---|---|---|---|")
        for i, cl in enumerate(cc["pending_review"], 1):
            it = cl["entries"][0]
            lines.append(
                f"| {i} | {_esc(', '.join(cl['engines']))} "
                f"| {_esc(it.get('title', ''))} | {_esc(it.get('url', ''))} |"
            )
        lines.append("")
    else:
        lines.append("## 待核清单")
        lines.append("")
        if c["insufficient-engines"]:
            lines.append(
                f"无「仅单引擎命中」条目；但有 {c['insufficient-engines']} 条"
                f"因引擎可用数不足而**无法核验**（见下）。"
            )
        else:
            lines.append("无 —— 全部条目均已交叉印证。")
        lines.append("")

    cross = [cl for cl in cc["clusters"] if cl["verdict"] == "cross-verified"]
    if cross:
        lines.append(f"## 已交叉印证（{len(cross)} 条）")
        lines.append("")
        lines.append("| # | 引擎数 | 引擎 | 标题 | 匹配依据 |")
        lines.append("|---|---|---|---|---|")
        for i, cl in enumerate(cross, 1):
            lines.append(
                f"| {i} | {cl['engine_count']} | {_esc(', '.join(cl['engines']))} "
                f"| {_esc(cl['titles'][0] if cl['titles'] else '')} | {cl['matched_by']} |"
            )
        lines.append("")

    ins = [cl for cl in cc["clusters"] if cl["verdict"] == "insufficient-engines"]
    if ins:
        lines.append(f"## 无法核验（引擎可用数 < {cc['min_engines']}，{len(ins)} 条）")
        lines.append("")
        lines.append("| # | 引擎 | 标题 | URL |")
        lines.append("|---|---|---|---|")
        for i, cl in enumerate(ins, 1):
            it = cl["entries"][0]
            lines.append(
                f"| {i} | {_esc(', '.join(cl['engines']))} "
                f"| {_esc(it.get('title', ''))} | {_esc(it.get('url', ''))} |"
            )
        lines.append("")

    lines.append("## 引擎明细")
    lines.append("")
    lines.append("| 引擎 | 状态计数 |")
    lines.append("|---|---|")
    for eng, cnt in sorted(cc["per_engine"].items(), key=lambda kv: kv[0].lower()):
        detail = "，".join(f"{k}={v}" for k, v in sorted(cnt.items()))
        lines.append(f"| {_esc(eng)} | {detail} |")
    lines.append("")

    if cc["notes"]:
        lines.append("## 降级与提示")
        lines.append("")
        for n in cc["notes"]:
            lines.append(f"- {n}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------- 主流程
def build_report(batches: list[dict], sources: list[str],
                 min_engines: int, title_threshold: float) -> dict:
    results: list[dict] = []
    for b in batches:
        results.extend(b.get("results", []))
    try:
        engines = vr.load_engines()
    except vr.CannotValidate as e:  # 理论上 load_batches 已挡过，这里双保险
        return {"error": f"CANNOT:{e}"}
    return {
        "schema": REPORT_SCHEMA,
        "query": (batches[0].get("query", "") if batches else "").strip(),
        "language": batches[0].get("language") if batches else None,
        "generated_at": _now_iso(),
        "sources": sources,
        "params": {"min_engines": min_engines, "title_threshold": title_threshold},
        "cross_check": cross_check(results, engines, min_engines, title_threshold),
    }


_USAGE = (
    "用法: search_report.py <results.json...> "
    "[--min-engines N] [--title-threshold F] [--json] [--md -o FILE] [--selftest]"
)


def main(argv: list[str], out=sys.stdout, err=sys.stderr) -> int:
    """argv[0] 约定为程序名（与 CLI 一致）；进程内调用须自备占位名。"""
    if "--selftest" in argv:
        return selftest(out, err)

    args = argv[1:]
    min_engines = DEFAULT_MIN_ENGINES
    title_threshold = DEFAULT_TITLE_THRESHOLD
    md_out: str | None = None
    as_json = False
    as_md = False
    positional: list[str] = []

    i = 0
    while i < len(args):
        a = args[i]
        if a == "--min-engines":
            if i + 1 >= len(args):
                print("[无法验证] --min-engines 缺少取值", file=err)
                return EXIT_CANNOT
            try:
                min_engines = int(args[i + 1])
            except ValueError:
                print(f"[无法验证] --min-engines 需要整数，得到 {args[i + 1]!r}", file=err)
                return EXIT_CANNOT
            i += 2
        elif a == "--title-threshold":
            if i + 1 >= len(args):
                print("[无法验证] --title-threshold 缺少取值", file=err)
                return EXIT_CANNOT
            try:
                title_threshold = float(args[i + 1])
            except ValueError:
                print(f"[无法验证] --title-threshold 需要浮点数，得到 {args[i + 1]!r}", file=err)
                return EXIT_CANNOT
            i += 2
        elif a == "-o":
            if i + 1 >= len(args):
                print("[无法验证] -o 缺少文件路径", file=err)
                return EXIT_CANNOT
            md_out = args[i + 1]
            i += 2
        elif a == "--json":
            as_json = True
            i += 1
        elif a == "--md":
            as_md = True
            i += 1
        elif a.startswith("--"):
            print(f"[无法验证] 未知参数: {a}", file=err)
            print(_USAGE, file=err)
            return EXIT_CANNOT
        else:
            positional.append(a)
            i += 1

    if not positional:
        print(_USAGE, file=err)
        return EXIT_CANNOT

    batches, problems = load_batches(positional)
    cannot = [p for p in problems if p.startswith("CANNOT:")]
    if cannot:
        for p in cannot:
            print(f"[无法验证] {p[7:]}", file=err)
        return EXIT_CANNOT
    viol = [p for p in problems if p.startswith("VIOLATION:")]
    if viol:
        for p in viol:
            print(f"[FAIL] {p[10:]}", file=err)
        return EXIT_DEFECT

    report = build_report(batches, [Path(p).name for p in positional],
                          min_engines, title_threshold)

    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2), file=out)
    else:
        print(render_markdown(report), file=out)

    if as_md:
        if not md_out:
            print("[无法验证] --md 需要配合 -o <文件>", file=err)
            return EXIT_CANNOT
        try:
            Path(md_out).write_text(render_markdown(report), encoding="utf-8")
            print(f"[已写入] {md_out}", file=out)
        except OSError as e:
            print(f"[无法验证] 写入失败: {e}", file=err)
            return EXIT_CANNOT

    return EXIT_OK


# ---------------------------------------------------------------- 自检
def _r(engine, rank, title, url, status="ok", at="2026-10-12T22:40:00+08:00"):
    return {"engine": engine, "rank": rank, "title": title, "url": url,
            "status": status, "fetched_at": at}


def _batch(results, query="宠物食品 烘焙粮 适口性", language="zh"):
    return {"schema": vr.SCHEMA, "query": query, "language": language,
            "results": results}


def _write_tmp(d: Path, name: str, obj: dict) -> str:
    p = d / name
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return str(p)


def selftest(out, err) -> int:
    """自检：既证明该过的过，也证明该红的花红在**正确的判定**上。

    关键：第三态 insufficient-engines 必须有独立用例，否则
    「引擎全挂」会被静气归成「待核」——那正是本工具要防的误导。
    """
    import io

    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, bool(ok), detail))

    print("=" * 74, file=out)
    print("search_report.py 自检（离线夹具，不联网；真源 = config.json）", file=out)
    print("=" * 74, file=out)

    # ---------- A. 归一化 ----------
    check("URL：utm 参数不产生新键",
          norm_url("https://a.com/p?utm_source=x&id=1") == norm_url("https://a.com/p?id=1"),
          norm_url("https://a.com/p?utm_source=x&id=1"))
    check("URL：fragment 不产生新键",
          norm_url("https://a.com/p#sec") == norm_url("https://a.com/p"))
    check("URL：尾斜杠不产生新键",
          norm_url("https://a.com/p/") == norm_url("https://a.com/p"))
    check("URL：www 与大小写不产生新键",
          norm_url("https://WWW.A.com/p") == norm_url("https://a.com/p"))
    check("URL：query 参数顺序不产生新键",
          norm_url("https://a.com/p?a=1&b=2") == norm_url("https://a.com/p?b=2&a=1"))
    check("URL：默认端口不产生新键",
          norm_url("https://a.com:443/p") == norm_url("https://a.com/p"))
    check("URL：**不同路径**必须产生不同键（证伪：归一化不能把不同页面并成一个）",
          norm_url("https://a.com/p1") != norm_url("https://a.com/p2"))
    check("URL：**非跟踪参数**必须保留（证伪：不能把所有参数都剥掉）",
          "id=1" in norm_url("https://a.com/p?id=1&utm_source=x"))
    check("标题：空白与装饰符不影响相等",
          title_similarity("Python 官方教程", "python官方教程！") == 1.0)
    check("标题：明显不同 → 相似度低于阈值",
          title_similarity("Python 官方教程", "Java 入门到精通") < 0.6)

    # ---------- B. 判定三态 ----------
    # B1 两引擎命中同一 URL → cross-verified
    r = _batch([
        _r("Baidu", 1, "烘焙粮适口性研究", "https://a.com/1"),
        _r("Sogou", 1, "烘焙粮适口性研究", "https://a.com/1"),
    ])
    cc = cross_check(r["results"], {}, 2, 0.90)
    check("两引擎同 URL → cross-verified",
          cc["counts"]["cross-verified"] == 1 and cc["counts"]["single-engine"] == 0,
          str(cc["counts"]))

    # B2 两引擎可用，但该条只有 Baidu 命中 → single-engine（待核）
    r = _batch([
        _r("Baidu", 1, "烘焙粮适口性研究", "https://a.com/1"),
        _r("Sogou", 1, "另一篇完全不同的文章", "https://b.com/2"),
    ])
    cc = cross_check(r["results"], {}, 2, 0.90)
    check("两引擎可用但仅一家命中 → single-engine ×2",
          cc["counts"]["single-engine"] == 2 and cc["counts"]["cross-verified"] == 0,
          str(cc["counts"]))
    check("待核清单长度与 single-engine 一致",
          len(cc["pending_review"]) == 2, str(len(cc["pending_review"])))

    # B3 **关键诚实性**：只有 1 个引擎有 ok 结果 → insufficient，不得判待核
    r = _batch([
        _r("Baidu", 1, "烘焙粮适口性研究", "https://a.com/1"),
        {"engine": "Sogou", "status": "blocked",
         "fetched_at": "2026-10-12T22:40:03+08:00"},
        {"engine": "360", "status": "error",
         "fetched_at": "2026-10-12T22:40:06+08:00"},
    ])
    cc = cross_check(r["results"], {}, 2, 0.90)
    check("仅 1 个引擎 ok → insufficient-engines（**不是** single-engine）",
          cc["counts"]["insufficient-engines"] == 1 and cc["counts"]["single-engine"] == 0,
          str(cc["counts"]))
    check("引擎不够时待核清单为空（不得伪造待核项）",
          cc["pending_review"] == [], str(len(cc["pending_review"])))

    # B4 URL 不同但标题相同 → 合并
    r = _batch([
        _r("Baidu", 1, "烘焙粮适口性研究进展", "https://a.com/1"),
        _r("Sogou", 1, "烘焙粮适口性研究进展", "https://b.com/2"),
    ])
    cc = cross_check(r["results"], {}, 2, 0.90)
    check("标题相同 URL 不同 → 合并为 cross-verified",
          cc["counts"]["cross-verified"] == 1 and cc["clusters"][0]["matched_by"] == "title",
          str(cc["counts"]))

    # B5 标题不同 URL 不同 → 两个独立簇
    r = _batch([
        _r("Baidu", 1, "烘焙粮适口性研究进展", "https://a.com/1"),
        _r("Sogou", 1, "冻干工艺对营养保留的影响", "https://b.com/2"),
    ])
    cc = cross_check(r["results"], {}, 2, 0.90)
    check("标题与 URL 都不同 → 2 个独立簇，各自 single-engine",
          len(cc["clusters"]) == 2 and cc["counts"]["single-engine"] == 2,
          f"{len(cc['clusters'])} {cc['counts']}")

    # B6 min_engines=3：3 个引擎有 ok，但两个簇分别只有 2/1 个引擎 → 都够不上
    r = _batch([
        _r("Baidu", 1, "烘焙粮适口性研究", "https://a.com/1"),
        _r("Sogou", 1, "烘焙粮适口性研究", "https://a.com/1"),
        _r("360", 1, "第三家的另一篇", "https://c.com/3"),
    ])
    cc = cross_check(r["results"], {}, 3, 0.90)
    check("min_engines=3 时 3 引擎可用但两簇分别 2/1 个 → 均 single-engine（参数生效）",
          cc["engines_with_ok"] == 3
          and cc["counts"]["cross-verified"] == 0
          and cc["counts"]["single-engine"] == 2,
          f"with_ok={cc['engines_with_ok']} {cc['counts']}")

    # B6b min_engines=1：单引擎即可印证 → cross-verified（下界生效）
    r = _batch([_r("Baidu", 1, "文章甲", "https://a.com/1")])
    cc = cross_check(r["results"], {}, 1, 0.90)
    check("min_engines=1 时单引擎命中即 cross-verified",
          cc["counts"]["cross-verified"] == 1 and cc["counts"]["single-engine"] == 0,
          str(cc["counts"]))

    # B7 同引擎两条不同 URL → 不构成交叉
    r = _batch([
        _r("Baidu", 1, "文章甲", "https://a.com/1"),
        _r("Baidu", 2, "文章乙", "https://b.com/2"),
    ])
    cc = cross_check(r["results"], {}, 2, 0.90)
    check("同一引擎多条不构成交叉印证",
          cc["counts"]["cross-verified"] == 0, str(cc["counts"]))

    # B8 全部 empty → 无簇、无待核、无 insufficient
    r = _batch([
        {"engine": "Baidu", "status": "empty", "fetched_at": "2026-10-12T22:40:00+08:00"},
        {"engine": "Sogou", "status": "empty", "fetched_at": "2026-10-12T22:40:01+08:00"},
    ])
    cc = cross_check(r["results"], {}, 2, 0.90)
    check("全 empty → 三态计数全 0（域内负结果，不是错误）",
          cc["counts"] == {"cross-verified": 0, "single-engine": 0,
                           "insufficient-engines": 0} and cc["clusters"] == [],
          str(cc["counts"]))

    # B9 跟踪参数不产生新簇
    r = _batch([
        _r("Baidu", 1, "文章甲", "https://a.com/1?utm_source=bd"),
        _r("Sogou", 1, "文章甲", "https://a.com/1"),
    ])
    cc = cross_check(r["results"], {}, 2, 0.90)
    check("utm 差异不拆开同一信息",
          cc["counts"]["cross-verified"] == 1 and cc["clusters"][0]["engine_count"] == 2,
          str(cc["counts"]))

    # B10 引擎名大小写不敏感
    r = _batch([
        _r("bing cn", 1, "文章甲", "https://a.com/1"),
        _r("Bing CN", 1, "文章甲", "https://a.com/1"),
    ])
    cc = cross_check(r["results"], {}, 2, 0.90)
    check("引擎名大小写不敏感 → 仍算 2 个引擎",
          cc["clusters"] and cc["clusters"][0]["engine_count"] == 2,
          str(cc["clusters"][0]["engine_count"]) if cc["clusters"] else "no cluster")

    # ---------- C. 主流程与退出码 ----------
    PROG = "search_report.py"   # main() 约定 argv[0] 为程序名
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        p_good = _write_tmp(d, "good.json", _batch([
            _r("Baidu", 1, "文章甲", "https://a.com/1"),
            _r("Sogou", 1, "文章甲", "https://a.com/1"),
        ]))
        p_bad = _write_tmp(d, "bad.json", _batch([
            _r("Baidu", 1, "文章甲", "https://a.com/1"),
        ], query="别的查询"))
        p_viol = _write_tmp(d, "viol.json", {"schema": "mse.result/9", "query": "x",
                                             "results": []})
        p_single = _write_tmp(d, "single.json", _batch([
            _r("Baidu", 1, "文章甲", "https://a.com/1"),
            {"engine": "Sogou", "status": "blocked",
             "fetched_at": "2026-10-12T22:40:03+08:00"},
        ]))

        buf, ebuf = io.StringIO(), io.StringIO()
        rc = main([PROG, p_good], out=buf, err=ebuf)
        check("合法单批次 → exit 0", rc == EXIT_OK, f"rc={rc}")
        check("报告含 query", "宠物食品 烘焙粮 适口性" in buf.getvalue())

        buf, ebuf = io.StringIO(), io.StringIO()
        rc = main([PROG, p_good, p_bad], out=buf, err=ebuf)
        check("query 不一致 → exit 1", rc == EXIT_DEFECT, f"rc={rc}")
        check("query 不一致时说出冲突内容", "不一致" in ebuf.getvalue())

        buf, ebuf = io.StringIO(), io.StringIO()
        rc = main([PROG, p_viol], out=buf, err=ebuf)
        check("schema 违规 → exit 1", rc == EXIT_DEFECT, f"rc={rc}")
        check("违规时报出规则号 V1", "V1" in ebuf.getvalue(), ebuf.getvalue()[:80])

        buf, ebuf = io.StringIO(), io.StringIO()
        rc = main([PROG, str(d / "nope.json")], out=buf, err=ebuf)
        check("文件不存在 → exit 3（不是 1）", rc == EXIT_CANNOT, f"rc={rc}")

        buf, ebuf = io.StringIO(), io.StringIO()
        rc = main([PROG, p_single, "--json"], out=buf, err=ebuf)
        payload = json.loads(buf.getvalue())
        check("单引擎可用 → exit 0（域内负结果不是错误）", rc == EXIT_OK, f"rc={rc}")
        check("JSON 报告判定为 insufficient-engines",
              payload["cross_check"]["counts"]["insufficient-engines"] == 1,
              str(payload["cross_check"]["counts"]))
        check("JSON 报告 schema 正确", payload["schema"] == REPORT_SCHEMA)

        md_path = d / "report.md"
        buf, ebuf = io.StringIO(), io.StringIO()
        rc = main([PROG, p_good, "--md", "-o", str(md_path)], out=buf, err=ebuf)
        check("--md -o 落盘 → exit 0", rc == EXIT_OK and md_path.exists(), f"rc={rc}")
        check("Markdown 含汇总表", "| 判定 | 条目簇 |" in md_path.read_text(encoding="utf-8"))

        buf, ebuf = io.StringIO(), io.StringIO()
        rc = main([PROG, p_good, "--min-engines", "abc"], out=buf, err=ebuf)
        check("--min-engines 非整数 → exit 3", rc == EXIT_CANNOT, f"rc={rc}")

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print("-" * 74, file=out)
    print(f"自检结果：{passed}/{total} 通过", file=out)
    if passed != total:
        print("失败项：", file=out)
        for name, ok, detail in results:
            if not ok:
                print(f"  - {name}   ← {detail}", file=out)
        print("=" * 74, file=out)
        return EXIT_DEFECT
    print("=" * 74, file=out)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv))
