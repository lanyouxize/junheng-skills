# -*- coding: utf-8 -*-
"""multi-search-engine 多源一致性检查器（引擎清单 + 版本号）

检查项：
  A. 引擎清单 —— 真源 = config.json 的 engines 数组
  B. 版本号   —— 无「可执行真源」，判据改为「全体声明一致」；
                 参考基准 = _skillhub_meta.json（市场侧已发布记录），仅用于提示

任何声明数、名单或版本号与判据不符即判 FAIL。

被检源：
  1. SKILL.md            —— frontmatter description / description_zh / description_en
                           正文章节 ### Domestic (N) / ### International (N) 的 N 与引擎名
                           工作流行 "Domestic search engines (...)" 的引擎名
                           frontmatter version
  2. metadata.json       —— description 文本中的数字 + engines 数值 + version
  3. _skillhub_meta.json —— description_zh / description_en + version
  4. CHANGELOG.md        —— 最新条目版本号
  5. CHANNELLOG.md       —— 描述行的引擎数与分区数 + 基本信息版本 + 最新条目版本号

退出码：0=全一致；1=存在不一致；2=真源自身可疑（含疑似非搜索引擎条目）

设计约束：
  - 只读，绝不修改任何文件
  - 引擎清单真源永远是 config.json，脚本不猜测、不"以文档为准"
  - 名单比较做归一化（小写、去多余空白），避免大小写造成误报
  - 文件名沿用 check_engine_consistency.py（历史引用兼容），实际已覆盖版本号

用法：
  python check_engine_consistency.py
  python check_engine_consistency.py --json
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

try:  # Windows 控制台默认 GBK，会炸中文
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent

# 常见通用搜索引擎名（仅用于「疑似非搜索引擎」WARN 提示，不参与一致性判定）
KNOWN_SEARCH_ENGINES = {
    "baidu", "bing cn", "bing int", "360", "sogou", "wechat", "shenma", "toutiao",
    "google", "google hk", "duckduckgo", "yahoo", "startpage", "brave",
    "ecosia", "qwant", "wolframalpha", "yandex", "searx", "mojeek", "naver",
}

UNKNOWN = "?"


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip().lower()


def _nums(text: str) -> list[int]:
    return [int(n) for n in re.findall(r"\d+", text or "")]


# ---------------------------------------------------------------- 真源
def load_truth() -> dict:
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    engines = cfg.get("engines", [])
    cn = [e["name"] for e in engines if e.get("region") == "cn"]
    gl = [e["name"] for e in engines if e.get("region") == "global"]
    other = [e["name"] for e in engines if e.get("region") not in ("cn", "global")]
    return {"cn": cn, "global": gl, "other": other, "total": len(engines)}


# ---------------------------------------------------------------- 被检源
def check_skill(truth: dict) -> list[dict]:
    out: list[dict] = []
    s = (ROOT / "SKILL.md").read_text(encoding="utf-8")

    # frontmatter
    fm: dict[str, str] = {}
    if s.lstrip().startswith("---"):
        body = s.lstrip()[3:]
        end = body.find("\n---")
        for line in body[:end].splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                fm[k.strip()] = v.strip().strip('"')

    def claim(source, text):
        n = _nums(text)
        if not n:
            return
        total = n[0]
        cn_n = n[1] if len(n) > 1 else UNKNOWN
        gl_n = n[2] if len(n) > 2 else UNKNOWN
        out.append({
            "source": source, "kind": "count",
            "total": total, "cn": cn_n, "global": gl_n,
            "ok": (total == truth["total"]
                   and (cn_n in (UNKNOWN, len(truth["cn"])))
                   and (gl_n in (UNKNOWN, len(truth["global"])))),
        })

    claim("SKILL.md:frontmatter.description", fm.get("description", ""))
    claim("SKILL.md:frontmatter.description_zh", fm.get("description_zh", ""))
    claim("SKILL.md:frontmatter.description_en", fm.get("description_en", ""))

    # 正文首行
    m = re.search(r"Integration of (\d+) search engines", s)
    if m:
        out.append({"source": "SKILL.md:正文首行", "kind": "count",
                    "total": int(m.group(1)), "cn": UNKNOWN, "global": UNKNOWN,
                    "ok": int(m.group(1)) == truth["total"]})

    # 章节标题
    dom_h = re.search(r"### Domestic \((\d+)\)", s)
    int_h = re.search(r"### International \((\d+)\)", s)
    if dom_h:
        out.append({"source": "SKILL.md:### Domestic (N)", "kind": "count",
                    "total": UNKNOWN, "cn": int(dom_h.group(1)), "global": UNKNOWN,
                    "ok": int(dom_h.group(1)) == len(truth["cn"])})
    if int_h:
        out.append({"source": "SKILL.md:### International (N)", "kind": "count",
                    "total": UNKNOWN, "cn": UNKNOWN, "global": int(int_h.group(1)),
                    "ok": int(int_h.group(1)) == len(truth["global"])})

    # 章节引擎名
    def section_names(header: str, stop: str) -> list[str]:
        if header not in s:
            return []
        seg = s.split(header, 1)[1]
        seg = seg.split(stop, 1)[0]
        return re.findall(r"-\s+\*\*(.+?)\*\*\s*:", seg)

    dom_names = section_names("### Domestic", "### International")
    int_names = section_names("### International", "\n## ")
    for label, got, want in (
        ("SKILL.md:Domestic 名单", dom_names, truth["cn"]),
        ("SKILL.md:International 名单", int_names, truth["global"]),
    ):
        if not got:
            continue
        gn, wn = {_norm(x) for x in got}, {_norm(x) for x in want}
        out.append({"source": label, "kind": "roster",
                    "missing": sorted(wn - gn), "extra": sorted(gn - wn),
                    "ok": gn == wn})

    # 工作流行
    wf = re.search(r"Domestic search engines \(([^)]+)\)", s)
    if wf:
        names = [x.strip() for x in wf.group(1).split(",")]
        gn, wn = {_norm(x) for x in names}, {_norm(x) for x in truth["cn"]}
        out.append({"source": "SKILL.md:工作流 Domestic 名单", "kind": "roster",
                    "missing": sorted(wn - gn), "extra": sorted(gn - wn),
                    "ok": gn == wn})
    return out


def check_metadata(truth: dict) -> list[dict]:
    out: list[dict] = []
    p = ROOT / "metadata.json"
    if not p.exists():
        return out
    d = json.loads(p.read_text(encoding="utf-8"))
    n = _nums(d.get("description", ""))
    if n:
        out.append({"source": "metadata.json:description", "kind": "count",
                    "total": n[0], "cn": n[1] if len(n) > 1 else UNKNOWN,
                    "global": n[2] if len(n) > 2 else UNKNOWN,
                    "ok": n[0] == truth["total"]})
    if isinstance(d.get("engines"), int):
        out.append({"source": "metadata.json:engines", "kind": "count",
                    "total": d["engines"], "cn": UNKNOWN, "global": UNKNOWN,
                    "ok": d["engines"] == truth["total"]})
    return out


def check_skillhub_meta(truth: dict) -> list[dict]:
    out: list[dict] = []
    p = ROOT / "_skillhub_meta.json"
    if not p.exists():
        return out
    d = json.loads(p.read_text(encoding="utf-8"))
    for key in ("description_zh", "description_en"):
        n = _nums(d.get(key, ""))
        if n:
            out.append({"source": f"_skillhub_meta.json:{key}", "kind": "count",
                        "total": n[0], "cn": n[1] if len(n) > 1 else UNKNOWN,
                        "global": n[2] if len(n) > 2 else UNKNOWN,
                        "ok": n[0] == truth["total"]})
    return out


def check_channellog(truth: dict) -> list[dict]:
    out: list[dict] = []
    p = ROOT / "CHANNELLOG.md"
    if not p.exists():
        return out
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        # 仅比对「总览描述行」：需同时提到国内与国际分区。
        # 版本历史行（如「新增9个国际搜索引擎」「初始版本：8个国内搜索引擎」）
        # 只含单一分区，属历史事实，不是当前声明 → 必须排除，否则误报。
        if ("搜索引擎" in line and re.search(r"\d+\s*个", line)
                and "国内" in line and "国际" in line):
            n = _nums(line)
            if not n:
                continue
            total = n[0]
            cn_n = n[1] if len(n) > 1 else UNKNOWN
            gl_n = n[2] if len(n) > 2 else UNKNOWN
            out.append({"source": f"CHANNELLOG.md:{i}", "kind": "count",
                        "total": total, "cn": cn_n, "global": gl_n,
                        "ok": (total == truth["total"]
                               and cn_n in (UNKNOWN, len(truth["cn"]))
                               and gl_n in (UNKNOWN, len(truth["global"])))})
    return out


# ---------------------------------------------------------------- 版本号
def _latest_changelog_version(path: Path) -> str | None:
    """取 changelog 中「语义最大」的版本号（而非文件顺序第一行）。

    用 max 而非首次出现：防止文件被追加成乱序时把旧版本当成最新。
    """
    if not path.exists():
        return None
    vs = re.findall(r"^##+\s*v?(\d+(?:\.\d+)*)", path.read_text(encoding="utf-8"), re.M)
    if not vs:
        return None
    return max(vs, key=lambda v: tuple(int(x) for x in v.split(".")))


def check_version() -> list[dict]:
    """版本号多源一致性。

    与引擎清单不同，版本号没有「可执行真源」——它就是各处的字面声明，
    因此判据是**全体一致**：只要有一个源与其余不同（或缺失），全体判 FAIL。
    参考基准 = _skillhub_meta.json（市场侧写入的已发布版本），仅作提示不参与判定。
    """
    srcs: dict[str, str | None] = {}

    p = ROOT / "SKILL.md"
    if p.exists():
        m = re.search(r"^version:\s*(.+?)\s*$", p.read_text(encoding="utf-8"), re.M)
        srcs["SKILL.md:frontmatter.version"] = m.group(1).strip().strip('"') if m else None

    for fn, label in (("metadata.json", "metadata.json:version"),
                      ("_skillhub_meta.json", "_skillhub_meta.json:version")):
        fp = ROOT / fn
        if fp.exists():
            srcs[label] = json.loads(fp.read_text(encoding="utf-8")).get("version")

    for fn in ("CHANGELOG.md", "CHANNELLOG.md"):
        fp = ROOT / fn
        if fp.exists():
            srcs[f"{fn}:最新条目"] = _latest_changelog_version(fp)

    fp = ROOT / "CHANNELLOG.md"
    if fp.exists():
        m = re.search(r"\*\*版本\*\*:\s*v?(\d+(?:\.\d+)*)", fp.read_text(encoding="utf-8"))
        if m:
            srcs["CHANNELLOG.md:基本信息.版本"] = m.group(1)

    declared = {v for v in srcs.values() if isinstance(v, str)}
    unanimous = bool(srcs) and len(declared) == 1 and all(isinstance(v, str) for v in srcs.values())
    ref = srcs.get("_skillhub_meta.json:version") or (max(declared) if declared else None)

    return [{"source": k, "kind": "version",
             "value": v if isinstance(v, str) else "(缺失)",
             "ref": ref, "ok": unanimous}
            for k, v in srcs.items()]


# ---------------------------------------------------------------- 主流程
def run(as_json: bool = False) -> int:
    if not (ROOT / "config.json").exists():
        print(f"[FATAL] 真源缺失: {ROOT / 'config.json'}", file=sys.stderr)
        return 1

    truth = load_truth()
    checks = (check_skill(truth) + check_metadata(truth)
              + check_skillhub_meta(truth) + check_channellog(truth)
              + check_version())

    suspects = [n for n in truth["cn"] + truth["global"]
                if _norm(n) not in KNOWN_SEARCH_ENGINES]
    fails = [c for c in checks if not c["ok"]]

    if as_json:
        print(json.dumps({
            "truth": {"total": truth["total"], "cn": truth["cn"],
                      "global": truth["global"], "other": truth["other"]},
            "checks": checks, "failures": len(fails),
            "suspects": suspects,
        }, ensure_ascii=False, indent=2))
    else:
        print("=" * 78)
        print("引擎清单多源一致性检查  (真源 = config.json)")
        print("=" * 78)
        print(f"真源: 合计 {truth['total']}  = cn {len(truth['cn'])} + "
              f"global {len(truth['global'])}"
              + (f" + other {len(truth['other'])}" if truth["other"] else ""))
        print(f"  cn     : {', '.join(truth['cn'])}")
        print(f"  global : {', '.join(truth['global'])}")
        print("-" * 78)
        for c in checks:
            mark = "OK  " if c["ok"] else "FAIL"
            if c["kind"] == "count":
                print(f"[{mark}] {c['source']:<42} total={c['total']} "
                      f"cn={c['cn']} global={c['global']}")
            elif c["kind"] == "roster":
                detail = ""
                if c["missing"]:
                    detail += f" 缺={c['missing']}"
                if c["extra"]:
                    detail += f" 多={c['extra']}"
                print(f"[{mark}] {c['source']:<42}{detail or ' 名单一致'}")
            else:  # version
                print(f"[{mark}] {c['source']:<42} v{c['value']}"
                      f"   (基准 v{c['ref']})")
        print("-" * 78)
        print(f"不一致项: {len(fails)} / 共检查 {len(checks)} 项")
        if suspects:
            print(f"[WARN] 真源含疑似非搜索引擎条目（需人工确认）: {suspects}")
        print("=" * 78)

    if fails:
        return 1
    if suspects:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(run(as_json="--json" in sys.argv))
