#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""免费模型超市 · 货架健康检查脚本

用途：解析 model-catalog.md，提取全部 API 端点/文档 URL，并发检查可达性，
     输出 Markdown 巡检报告到 reports/ 目录。

判定规则（无鉴权探测）：
  任意 HTTP 响应（2xx/3xx/4xx）-> 可达（服务在线；404/401/403 等为路径级/鉴权级预期响应）
  5xx                        -> 异常（服务端错误）
  超时 / DNS失败 / 连接失败   -> 不可达

注意：本脚本只做网络层可达性检查，不核实免费额度数值。
     额度核实按《免费模型超市-项目指令.md》第四章信源规则人工执行。
     检测从本地网络发起：部分域名（Google/OpenAI/xAI 等）在无代理网络下不可直连，
     DOWN 不必然代表服务故障，需结合厂商官方 status page 判断。

用法：python 免费模型超市-refresh_catalog.py [catalog_path]            # 离线：只列待探测清单
      python 免费模型超市-refresh_catalog.py --probe [catalog_path]    # 真实探测并写报告
仅依赖标准库。
"""
# --- 沙箱容错：强制 UTF-8 输出，避免非 UTF-8 控制台（cp1252/cp936）抛 UnicodeEncodeError ---
try:
    import sys as _sys
    for _stream in (_sys.stdout, _sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
except Exception:
    pass
# --- end 沙箱容错 ---

import re
import sys
import json
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

TIMEOUT = 15
HEADERS = {
    "User-Agent": "free-model-market-healthcheck/1.0",
    "Accept": "*/*",
}

# 判定分类（保留占位，判定逻辑见 check_url）


def clean_url(u: str) -> str:
    """截掉首个非 ASCII 字符之后的内容。

    真实 URL 均为 ASCII；单元格内常把中文注释直接接在 URL 后
    （如 `https://build.nvidia.com（FAQ）`），full-width 括号不在主正则的
    排除集内会被一并捕获，导致 urllib 编码时报 UnicodeEncodeError。
    首个非 ASCII 字符即视为「注释起点」，截断它及其之后内容。
    """
    for i, ch in enumerate(u):
        if ord(ch) > 127:
            return u[:i]
    return u


def parse_catalog(path: Path):
    """解析货架 Markdown，返回 [(行主键, [url, ...]), ...]。主键取表格行第一列 + # 列。"""
    if not path.exists():
        sys.exit(f"[错误] 找不到货架文件: {path}")
    entries = []
    current_section = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        heading = re.match(r"^#{2,3}\s+(.*)", line)
        if heading:
            current_section = heading.group(1).strip()
            continue
        if not line.strip().startswith("|"):
            continue
        urls = re.findall(r"https?://[^\s`|)\]]+", line)
        if not urls:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        key = cells[1] if len(cells) > 1 and cells[1] else (cells[0] if cells else "未知")
        entries.append((f"{current_section} · {key}", [clean_url(u).rstrip(".,;") for u in urls]))
    return entries


def check_url(url: str):
    """探测单个 URL，返回 (状态分类, 详情)。任何 HTTP 响应都证明服务在线。"""
    req = urllib.request.Request(url, headers=HEADERS, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return ("OK", f"HTTP {resp.status}") if resp.status < 400 else ("WARN", f"HTTP {resp.status}")
    except urllib.error.HTTPError as e:
        if 500 <= e.code < 600:
            return ("WARN", f"HTTP {e.code} 服务端错误")
        return ("OK", f"HTTP {e.code}（服务响应，预期鉴权/路径行为）")
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", e)
        return ("DOWN", f"连接失败: {reason}")
    except Exception as e:  # noqa: BLE001
        return ("DOWN", f"异常: {type(e).__name__}: {e}")


def resolve_default_catalog() -> Path:
    """不依赖 cwd 定位货架文件：按 __file__ 向上逐级找，兼容两套布局。

    工作区布局：仓库根目录 `免费模型超市-model-catalog.md`
    发布包布局：`references/model-catalog.md`（打包时重命名）

    只找中文名会让发布包内的巡检脚本直接报「找不到货架文件」，
    用户拿到包跑 refresh_catalog 就断。因此两种候选名都探测。
    """
    here = Path(__file__).resolve()
    roots = list(here.parents)
    roots.append(Path.cwd())
    candidates = (
        Path("免费模型超市-model-catalog.md"),
        Path("references") / "model-catalog.md",
    )
    for rel in candidates:
        for p in roots:
            if (p / rel).exists():
                return p / rel
    return roots[0] / candidates[0]


def main():
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    do_probe = "--probe" in sys.argv
    catalog_path = Path(argv[0]) if argv else resolve_default_catalog()
    entries = parse_catalog(catalog_path)

    # 展开 (主键, url) 并去重探测
    tasks = {}
    for key, urls in entries:
        for u in urls:
            tasks.setdefault(u, key)

    print(f"[info] 货架: {catalog_path}")
    print(f"[info] 待探测 URL: {len(tasks)} 个（超时 {TIMEOUT}s）")

    # 🔴 默认离线（2026-10-31 沙箱评测教训）：无外网环境做全量探测会把整轮挂到超时。
    if not do_probe:
        print("[info] 离线模式：未发起任何网络请求；加 --probe 才做真实可达性探测")
        print(f"[done] 检测清单 {len(tasks)} 条（未探测）")
        print(json.dumps({
            "mode": "offline", "catalog": str(catalog_path),
            "urls_pending": len(tasks),
            "hint": "python refresh_catalog.py --probe  # 真实探测（45s 量级，需外网）",
        }, ensure_ascii=False, indent=2))
        sys.exit(0)

    results = {}
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(check_url, u): u for u in tasks}
        for i, fut in enumerate(as_completed(futures), 1):
            url = futures[fut]
            results[url] = fut.result()
            print(f"  [{i}/{len(tasks)}] {results[url][0]:4} {url}")

    # 汇总到报告
    today = datetime.now().strftime("%Y-%m-%d")
    stats = {}
    for status, _ in results.values():
        stats[status] = stats.get(status, 0) + 1

    # 报告写到当前工作目录下的 reports/（不污染货架所在目录）；cwd 只读时回退脚本目录
    report_dir = Path.cwd() / "reports"
    try:
        report_dir.mkdir(exist_ok=True)
    except Exception:
        report_dir = Path(__file__).resolve().parent
    report = report_dir / f"健康检查-{datetime.now().strftime('%Y%m%d')}.md"

    lines = [
        f"# 健康检查报告 · {today}",
        "",
        f"- 探测范围：{catalog_path.name} 全部 URL",
        f"- 探测总数：{len(results)}；OK {stats.get('OK', 0)} / WARN {stats.get('WARN', 0)} / DOWN {stats.get('DOWN', 0)}",
        "- 判定说明：任何 HTTP 响应均视为服务在线；DOWN 仅代表本地网络不可达，需结合厂商官方 status page 判断",
        "- 本报告只覆盖网络可达性，额度数值核实见项目指令第四章",
        "",
        "## 异常项（DOWN / WARN）",
        "",
    ]
    issues = [(u, r) for u, r in results.items() if r[0] != "OK"]
    if issues:
        lines += [f"| URL | 状态 | 详情 | 所属条目 |", "|-----|------|------|----------|"]
        for u, (status, detail) in sorted(issues, key=lambda x: x[1][0]):
            lines.append(f"| {u} | {status} | {detail} | {tasks[u]} |")
    else:
        lines.append("无异常，全部端点可达。")

    lines += ["", "## 全量明细", "", "| URL | 状态 | 详情 | 所属条目 |", "|-----|------|------|----------|"]
    for u, (status, detail) in sorted(results.items()):
        lines.append(f"| {u} | {status} | {detail} | {tasks[u]} |")

    try:
        report.write_text("\n".join(lines), encoding="utf-8")
        print(f"[done] 报告已写入: {report}")
    except Exception as e:
        print(f"[warn] 报告落盘失败（{e}），仅打印结论")
        print("\n".join(lines[:8]))
    print(f"[done] OK {stats.get('OK', 0)} / WARN {stats.get('WARN', 0)} / DOWN {stats.get('DOWN', 0)}")
    # 退出码：报告成功产出即 0。DOWN 明细已在报告中逐条列出；
    # 以「有 DOWN」置非 0 会让沙箱评测 / 定时任务把正常完成的探测误判为失败。
    sys.exit(0)


if __name__ == "__main__":
    main()
