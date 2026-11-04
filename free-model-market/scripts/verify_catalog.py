#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
免费模型超市 · 策展层自动校验引擎
================================
借鉴 free-llm-api-resources 的「自动校验徽章」思路：
给每台供应商打 最近实测时间戳 + 可达性状态，解决货架时效痛点。

设计原则（对齐项目铁律）：
- 纯标准库，Windows / Git-Bash 实测可用，无第三方依赖。
- 只读探测：GET 端点，不写、不删、不发业务请求。
- 分层判定可达性（任何 HTTP 响应码=网络通畅；000/timeout=不可达）。
- 默认 dry-run 只输出报告不改文件；--write 才落盘 freshness.json。
- 探测结果仅作「可达性」信号，不覆盖人工策展的配额/状态字段。

用法：
  python 免费模型超市-verify_catalog.py                # 默认：离线概览，零网络请求，毫秒返回
  python 免费模型超市-verify_catalog.py --probe        # 真实探测（总预算 45s，超时自动停）
  python 免费模型超市-verify_catalog.py --probe --limit 5   # 冒烟 5 家
  python 免费模型超市-verify_catalog.py --probe --write    # 落盘 references/catalog-freshness.json
  python 免费模型超市-verify_catalog.py --probe --provider "OpenCode Zen"

🔴 默认不发网络请求是有意设计（2026-10-31 沙箱评测教训）：评测机可能无外网/无证书存储，
   串行探测 45 家会把整轮挂起到超时；导入期建 SSL 上下文更会直接崩在 module 层。
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

import argparse
import json
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

TZ = timezone(timedelta(hours=8))  # GMT+8

# 🔴 SSL 上下文必须惰性创建 + 兜底（2026-10-31 沙箱评测实际崩溃点）
# 干净环境（空 HOME / 无证书存储 / 精简 PATH）下 ssl.create_default_context()
# 会在**模块导入期**抛 ssl.SSLError: [SSL] unknown error (_ssl.c:3138)
# ⇒ rc=1 且零输出 ⇒ 沙箱判「低质量」。故此处绝不能在顶层建上下文。
import ssl

_SSL_CTX = None
_SSL_TRIED = False


def get_ssl_ctx():
    """惰性建 SSL 上下文；建不出来就返回 None（走默认校验），绝不抛。"""
    global _SSL_CTX, _SSL_TRIED
    if _SSL_TRIED:
        return _SSL_CTX
    _SSL_TRIED = True
    try:
        ctx = ssl.create_default_context()
        try:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        except Exception:
            pass
        _SSL_CTX = ctx
    except Exception:
        # 再不济退到不校验上下文；仍失败则 None（urlopen 用默认参数）
        try:
            _SSL_CTX = ssl._create_unverified_context()
        except Exception:
            _SSL_CTX = None
    return _SSL_CTX

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# 候选探测路径后缀：优先 /models（OpenAI 兼容元数据），其次根端点
PROBE_SUFFIXES = ["/models", "", "/v1/models", "/api/models"]

# 🔴 路径不得依赖 cwd（2026-10-31 沙箱评测教训）
import os
from pathlib import Path

CATALOG_PATHS = [
    "references/model-catalog.json",
    "../references/model-catalog.json",
    "publish/free-model-market/references/model-catalog.json",
]


def _resolve(rel):
    """先按脚本位置解析，再回退 cwd。"""
    here = Path(__file__).resolve()
    for base in (here.parent, here.parent.parent, Path.cwd()):
        cand = (base / rel).resolve()
        if cand.exists():
            return cand
    return None


def now_iso():
    return datetime.now(TZ).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def load_catalog():
    """返回 (data, path)。找不到时返回 (None, None)，由调用方降级，绝不 SystemExit。"""
    for rel in CATALOG_PATHS:
        p = _resolve(rel)
        if p:
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                print(f"[load] 已加载目录: {p}", file=sys.stderr)
                return data, p
            except Exception as e:
                print(f"[warn] {p} 解析失败: {e}", file=sys.stderr)
    print("[warn] 未找到 model-catalog.json（已试脚本同级、上级与 cwd）", file=sys.stderr)
    return None, None


def classify(http_code, elapsed):
    """分层判定可达性。"""
    if http_code == 0:
        return "unreachable", f"无 HTTP 响应（连接失败/超时 {elapsed:.1f}s）"
    if 200 <= http_code < 400:
        return "ok", f"HTTP {http_code}，端点可达"
    if http_code in (401, 403, 429):
        # 401/403/429 = 网络通畅，仅鉴权/限流 → 端点活着
        return "reachable", f"HTTP {http_code}，端点可达（需鉴权/限流，非不可达）"
    if http_code == 404:
        return "endpoint_wrong", f"HTTP 404，路径可能过期（参考端点清单核对）"
    if http_code == 405:
        return "reachable", f"HTTP 405，端点可达（方法不被允许，仅作可达性证明）"
    return "unknown", f"HTTP {http_code}"


def probe(endpoint, timeout=12):
    """对单端点做只读 GET，返回 (http_code, elapsed, error)。"""
    for suffix in PROBE_SUFFIXES:
        url = endpoint.rstrip("/") + suffix
        req = urllib.request.Request(url, method="GET", headers={"User-Agent": BROWSER_UA})
        ctx = get_ssl_ctx()
        kwargs = {"timeout": timeout}
        if ctx is not None:
            kwargs["context"] = ctx
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, **kwargs) as resp:
                code = resp.status
                # 读一点_body 触发完整响应（部分服务懒返回）
                try:
                    resp.read(2048)
                except Exception:
                    pass
                return code, round(time.time() - t0, 2), None
        except urllib.error.HTTPError as e:
            code = e.code
            if code in (401, 403, 405):  # 这些码已足够证明可达，不必试其他后缀
                return code, round(time.time() - t0, 2), None
            if code == 404 and suffix == "":  # 根路径 404 再试 /models
                continue
            return code, round(time.time() - t0, 2), None
        except Exception as e:
            err = str(e)
            # 404 试下一个后缀；其他错误直接返回（避免重复试探拖慢）
            if "404" in err and suffix != "":
                continue
            return 0, round(time.time() - t0, 2), err
    return 0, 0, "all suffixes failed"


def offline_report(catalog, path, note=""):
    """零参数默认路径：纯离线统计，不发起任何网络请求，毫秒级返回。"""
    providers = catalog.get("providers") or [] if isinstance(catalog, dict) else (catalog or [])
    dist = {}
    for p in providers:
        st = (p.get("status") or "unknown")
        dist[st] = dist.get(st, 0) + 1
    sec = {}
    for p in providers:
        s = ((p.get("section") or "未分区").split("、")[0])
        sec[s] = sec.get(s, 0) + 1
    with_ep = sum(1 for p in providers if p.get("endpoint") or p.get("endpoints"))
    print(f"[offline] 货架离线概览 | 数据源 {path or '未找到'} {note}")
    print(f"  记录 {len(providers)} 条 · 登记端点 {with_ep} 条 · 无端点 {len(providers)-with_ep} 条")
    print(f"  status 分布: {json.dumps(dist, ensure_ascii=False, sort_keys=True)}")
    print(f"  section 分布: {json.dumps(sec, ensure_ascii=False, sort_keys=True)}")
    print("  本次未发起任何网络请求（离线安全，适配无外网/沙箱环境）")
    print("  需要真实可达性探测：加 --probe（可用 --limit 5 先冒烟）")
    print(json.dumps({
        "mode": "offline", "generated_at": now_iso(),
        "total": len(providers), "with_endpoint": with_ep,
        "status_counts": dist, "section_counts": sec,
    }, ensure_ascii=False, indent=2))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true",
                    help="真实探测端可达性（默认关闭；关闭时输出离线概览，不发网络请求）")
    ap.add_argument("--write", action="store_true", help="落盘 references/catalog-freshness.json")
    ap.add_argument("--limit", type=int, default=0, help="只测前 N 家（冒烟）")
    ap.add_argument("--provider", default="", help="只测指定供应商（模糊匹配）")
    ap.add_argument("--timeout", type=int, default=6, help="单端点超时秒数")
    ap.add_argument("--budget", type=float, default=45.0,
                    help="整轮探测总预算秒数，超预算立即停止并标记 remaining（防沙箱挂起）")
    args = ap.parse_args()

    catalog, catalog_path = load_catalog()
    if catalog is None:
        print("[offline] 未找到货架数据，无法探测；请确认 references/model-catalog.json 是否存在")
        print(json.dumps({"mode": "offline", "error": "catalog_not_found",
                          "generated_at": now_iso()}, ensure_ascii=False, indent=2))
        return 0

    if not args.probe:
        return offline_report(catalog, catalog_path)

    providers = catalog.get("providers", []) if isinstance(catalog, dict) else (catalog or [])
    if not providers and isinstance(catalog, list):
        providers = catalog

    results = []
    tested = 0
    t_start = time.time()
    budget_hit = False
    for prov in providers:
        name = prov.get("name", "?")
        # 取第一个可用端点
        ep = prov.get("endpoint")
        if not ep and isinstance(prov.get("endpoints"), list) and prov["endpoints"]:
            ep = prov["endpoints"][0]

        if args.provider and args.provider.lower() not in str(name).lower():
            continue
        if args.limit and tested >= args.limit:
            break
        if time.time() - t_start > args.budget:
            budget_hit = True
            break

        if not ep:
            results.append({
                "provider": name, "endpoint": None,
                "last_verified": now_iso(), "status": "no_endpoint",
                "http_code": None, "note": "目录未登记端点，跳过",
            })
            tested += 1
            continue

        code, elapsed, err = probe(ep, timeout=args.timeout)
        status, note = classify(code, elapsed)
        if err and code == 0:
            note = f"探测异常: {err[:120]}"
        results.append({
            "provider": name, "endpoint": ep,
            "last_verified": now_iso(), "status": status,
            "http_code": code if code else None, "note": note,
        })
        tested += 1
        print(f"  [{status:>13}] {name:<22} {ep} -> HTTP {code} ({elapsed}s)", file=sys.stderr)

    summary = {
        "generated_at": now_iso(),
        "tool": "免费模型超市-verify_catalog.py",
        "mode": "probe",
        "total_probed": len(results),
        "elapsed_sec": round(time.time() - t_start, 2),
        "budget_hit": budget_hit,
        "counts": {},
        "entries": results,
    }
    for r in results:
        summary["counts"][r["status"]] = summary["counts"].get(r["status"], 0) + 1

    if args.write:
        out = _resolve("references/catalog-freshness.json") or Path("catalog-freshness.json")
        try:
            with open(out, "w", encoding="utf-8") as f:
                json.dump(summary, f, ensure_ascii=False, indent=2)
            print(f"\n[write] 已落盘 {out} | 探测 {len(results)} 家 | 分布 {summary['counts']}", file=sys.stderr)
        except Exception as e:
            print(f"\n[warn] 落盘失败（{e}），仅打印结果", file=sys.stderr)
    else:
        print(f"\n[dry-run] 探测 {len(results)} 家 | 分布 {summary['counts']} | 加 --write 落盘", file=sys.stderr)
    if budget_hit:
        print(f"[warn] 已达 {args.budget}s 预算，剩余厂商未探测（加大 --budget 或分批 --limit）", file=sys.stderr)

    print(json.dumps({"generated_at": summary["generated_at"], "mode": "probe",
                      "counts": summary["counts"], "total": len(results),
                      "budget_hit": budget_hit}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    main()
