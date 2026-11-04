#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""免费模型超市 · 我的账本（ledger）

把网关的调用记录翻译成一本「你白嫖了多少」的账：
调用量、token 总量、按市场牌价折算的等价支出、主力渠道、作息画像、人设标签。

设计原则（三条，缺一不可）
1. **不写死任何价格**。牌价每次运行时从 OpenRouter 公开接口实时取
   （`https://openrouter.ai/api/v1/models`，返回 pricing.prompt / pricing.completion，
   单位 USD/token，无需 Key）。取不到就明说取不到，绝不拿记忆里的旧价糊弄。
2. **档位由市场分布决定**，不由主观认定谁是旗舰。取全部有效报价模型的分位数：
   P90 = 旗舰档、P50 = 主力档、P10 = 经济档，并打印每档实际命中的模型 ID，
   让每个金额都能溯源。
3. **零依赖 + 只读**。只用标准库，只读打开 SQLite（mode=ro），不改任何数据。

数据来源：网关 `storage.sqlite` 的 `usage_history` 表
（provider / model / tokens_input / tokens_output / latency_ms / success / timestamp）。
直连模式（inject_workbuddy 写 models.json）不经过网关，因此**没有**这份数据 ——
本脚本会如实告知，不会编造。

用法
    python ledger.py                # 最近 30 天
    python ledger.py --since 7d     # 最近 7 天
    python ledger.py --since all    # 全部历史
    python ledger.py --json         # 机器可读
    python ledger.py --db <path>    # 指定 storage.sqlite
    python ledger.py --no-price     # 不联网，只报 token 量（不算钱）

退出码：恒为 0（诊断类脚本，异常写进输出）。
"""
from __future__ import annotations

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
import os
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

CN_TZ = timezone(timedelta(hours=8))
PRICING_URL = "https://openrouter.ai/api/v1/models"
PRICING_TIMEOUT = 12

# 排除非对话类模型，避免把 embedding / 语音 / 绘图塞进分位统计
NON_CHAT_HINTS = (
    "embed", "whisper", "tts", "audio", "rerank", "moderation",
    "image", "video", "diffusion", "sd-", "dall", "flux",
    "safeguard", "guard", "content-safety", "ocr",
)

# 排除同一模型的计费变体：:batch（约半价）、:thinking、:extended、:online 等，
# 它们不代表标准牌价，混进分位会把档位拉低或拉高。
VARIANT_SUFFIXES = (":batch", ":thinking", ":extended", ":online", ":nitro", ":floor", ":free")

# 排除专用于检索/联网的模型：价格结构与通用对话模型不可比
SEARCH_HINTS = ("perplexity/", "sonar", "search", "gpt-4o-search", "online-")

# 分位选档时优先落在这批主流厂商上，让「对标模型」更有说服力
MAINSTREAM_PREFIXES = (
    "openai/", "anthropic/", "google/", "deepseek/", "meta-llama/",
    "mistralai/", "qwen/", "x-ai/", "moonshotai/", "z-ai/", "cohere/",
)


def c_cn(ts: datetime) -> str:
    return ts.astimezone(CN_TZ).strftime("%Y-%m-%d %H:%M")


def find_db(explicit: str | None) -> tuple[Path | None, str | None]:
    """按优先级定位网关 storage.sqlite。返回 (路径, 错误说明)。

    显式传了 --db 却不存在时**不回退**：用户明确指定了位置，静默换成别的库
    会让他看到一份不属于自己的账，属于误导。
    """
    if explicit:
        p = Path(explicit)
        if p.is_file():
            return p, None
        return None, f"指定的数据库不存在：{p}"

    cands: list[Path] = []
    env_dir = os.environ.get("DATA_DIR") or os.environ.get("OMNIROUTE_DATA_DIR")
    if env_dir:
        cands.append(Path(env_dir) / "storage.sqlite")
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            cands.append(Path(base) / "Temp" / "omniroute-data" / "storage.sqlite")
    cands.append(Path.home() / ".omniroute" / "storage.sqlite")
    for c in cands:
        try:
            if c.is_file():
                return c, None
        except OSError:
            continue
    return None, None


def since_iso(spec: str) -> str | None:
    spec = (spec or "30d").strip().lower()
    if spec in ("all", "0", "inf"):
        return None
    unit, num = spec[-1], spec[:-1]
    try:
        n = int(num)
    except ValueError:
        n = 30
        unit = "d"
    delta = {"d": timedelta(days=n), "w": timedelta(weeks=n), "h": timedelta(hours=n)}.get(unit, timedelta(days=30))
    return (datetime.now(timezone.utc) - delta).strftime("%Y-%m-%dT%H:%M:%S")


def fetch_prices() -> tuple[dict | None, str]:
    """实时取牌价。返回 (分位档位, 说明)。失败返回 (None, 原因)。"""
    req = urllib.request.Request(
        PRICING_URL,
        headers={"User-Agent": "free-model-market-ledger/1.0", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=PRICING_TIMEOUT) as r:
            raw = r.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        return None, f"无法获取实时牌价（{type(e).__name__}）"

    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except Exception as e:  # noqa: BLE001
        return None, f"牌价接口返回非 JSON（{e}）"

    rows = []
    for m in data.get("data", []) or []:
        mid = str(m.get("id") or "")
        if not mid:
            continue
        low = mid.lower()
        if any(low.endswith(s) for s in VARIANT_SUFFIXES):
            continue
        if any(h in low for h in NON_CHAT_HINTS):
            continue
        if any(h in low for h in SEARCH_HINTS):
            continue
        pr = m.get("pricing") or {}
        try:
            pin = float(pr.get("prompt") or 0)
            pout = float(pr.get("completion") or 0)
        except (TypeError, ValueError):
            continue
        if pin <= 0 or pout <= 0:
            continue
        rows.append((pin, pout, mid))

    if len(rows) < 12:
        return None, f"有效报价模型过少（{len(rows)} 个），分位统计不可靠"

    rows.sort(key=lambda x: x[0])
    total = len(rows)

    def pick(q: float) -> tuple[float, float, str]:
        """取分位点，并优先在附近选区里落在主流厂商上，避免命中冷门/特殊计费模型。"""
        idx = min(total - 1, max(0, int(round(q * (total - 1)))))
        window = max(4, total // 25)  # 附近 ±4% 左右
        lo, hi = max(0, idx - window), min(total, idx + window + 1)
        for cand in sorted(range(lo, hi), key=lambda i: abs(i - idx)):
            if rows[cand][2].lower().startswith(MAINSTREAM_PREFIXES):
                return rows[cand]
        return rows[idx]

    p10, p50, p90 = pick(0.10), pick(0.50), pick(0.90)
    tiers = {
        "economy": {"label": "经济档", "prompt": p10[0], "completion": p10[1], "model": p10[2]},
        "main": {"label": "主力档", "prompt": p50[0], "completion": p50[1], "model": p50[2]},
        "flagship": {"label": "旗舰档", "prompt": p90[0], "completion": p90[1], "model": p90[2]},
    }
    note = f"实时取自 openrouter.ai/api/v1/models（{total} 个有效报价模型，按输入价分位取档）"
    return tiers, note


def load_rows(db: Path, since: str | None) -> tuple[list[dict], str | None]:
    try:
        uri = f"file:{db.as_posix()}?mode=ro"
        con = sqlite3.connect(uri, uri=True, timeout=5)
    except sqlite3.Error as e:
        return [], f"打不开数据库（{e}）"
    try:
        names = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
        if "usage_history" not in names:
            return [], "该数据库没有 usage_history 表（不像 OmniRoute 网关库）"
        sql = (
            "select timestamp, provider, model, tokens_input, tokens_output, "
            "latency_ms, success from usage_history"
        )
        args: tuple = ()
        if since:
            sql += " where timestamp >= ?"
            args = (since,)
        cur = con.execute(sql + " order by timestamp", args)
        rows = [
            {
                "ts": r[0] or "",
                "provider": (r[1] or "unknown"),
                "model": (r[2] or "unknown"),
                "tin": int(r[3] or 0),
                "tout": int(r[4] or 0),
                "lat": float(r[5]) if r[5] is not None else None,
                "ok": bool(r[6]),
            }
            for r in cur
        ]
        return rows, None
    except sqlite3.Error as e:
        return [], f"查询失败（{e}）"
    finally:
        con.close()


def hour_bucket(ts: str) -> str:
    """按北京时间分三档：白天 06-18 / 晚间 18-22 / 深夜 22-06。"""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        h = dt.astimezone(CN_TZ).hour
    except Exception:  # noqa: BLE001
        return "未知"
    if 6 <= h < 18:
        return "白天"
    if 18 <= h < 22:
        return "晚间"
    return "深夜"


def pct(a: float, b: float) -> float:
    return (a / b * 100.0) if b else 0.0


def money(v: float) -> str:
    return f"${v:,.2f}" if v >= 0.01 else "$0.00"


def build_personas(agg: dict, tiers: dict | None) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    total_tok = agg["tin"] + agg["tout"]
    if total_tok >= 1_000_000 and agg["cost_any_zero"]:
        out.append(("白嫖王者", f"累计 {total_tok/1e6:.1f}M token，自付 $0"))
    deep = agg["buckets"].get("深夜", 0)
    if agg["calls"] and pct(deep, agg["calls"]) >= 40:
        out.append(("深夜码农", f"{pct(deep, agg['calls']):.0f}% 的调用发生在 22:00–06:00"))
    if agg["providers"]:
        top_p, top_t = agg["providers"][0][0], agg["providers"][0][2]
        if pct(top_t, total_tok) >= 70:
            out.append(("单点依赖", f"{top_p} 一家扛了 {pct(top_t, total_tok):.0f}% 的 token"))
    if agg["lat_n"] and agg["lat_avg"] >= 10000:
        out.append(("耐心选手", f"平均 {agg['lat_avg']/1000:.1f}s 一次响应，免费的价格是等待"))
    if len(agg["models"]) >= 10:
        out.append(("尝鲜党", f"试过 {len(agg['models'])} 个不同模型"))
    if agg["calls"] and pct(agg["ok"], agg["calls"]) >= 90:
        out.append(("稳如老狗", f"成功率 {pct(agg['ok'], agg['calls']):.0f}%"))
    if agg["calls"] and pct(agg["ok"], agg["calls"]) < 70:
        out.append(("渠道磨合中", f"成功率 {pct(agg['ok'], agg['calls']):.0f}%，免费渠道波动较大，建议看 watch 巡检") )
    return out


def main() -> None:
    ap = argparse.ArgumentParser(add_help=True, description="免费模型超市 · 我的账本")
    ap.add_argument("--since", default="30d", help="统计窗口：7d / 30d / 12w / all（默认 30d）")
    ap.add_argument("--db", default=None, help="指定网关 storage.sqlite 路径")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--no-price", action="store_true", help="不联网取牌价，只报 token 量")
    args = ap.parse_args()

    db, db_err = find_db(args.db)
    if not db:
        if db_err:
            if args.json:
                print(json.dumps({"ok": False, "error": "db-not-found", "detail": db_err}, ensure_ascii=False, indent=2))
            else:
                print(f"\n{db_err}\n")
            return
        msg = (
            "未找到网关数据库 storage.sqlite。\n"
            "  账本依赖网关的调用记录，可能的原因：\n"
            "  1) 还没装网关 —— 「自由模型市场·网关」装好并跑起来后会开始记账；\n"
            "  2) 用的是直连模式（inject_workbuddy 直接写 models.json）—— 请求不经网关，本地没有记录；\n"
            "  3) 数据目录不在默认位置 —— 用 --db 指定，或设置 DATA_DIR。\n"
            "  说明：直连模式同样能白嫖，只是没有账本可看。"
        )
        if args.json:
            print(json.dumps({"ok": False, "error": "db-not-found", "detail": msg}, ensure_ascii=False, indent=2))
        else:
            print("\n" + msg + "\n")
        return

    since = since_iso(args.since)
    rows, err = load_rows(db, since)
    if err:
        if args.json:
            print(json.dumps({"ok": False, "error": "db-error", "detail": err}, ensure_ascii=False, indent=2))
        else:
            print(f"\n读取失败：{err}\n  数据库：{db}\n")
        return

    if not rows:
        if args.json:
            print(json.dumps({"ok": False, "error": "no-data", "window": args.since}, ensure_ascii=False, indent=2))
        else:
            print(f"\n窗口「{args.since}」内没有调用记录。\n  数据库：{db}\n  换个窗口试试：--since all\n")
        return

    tin = sum(r["tin"] for r in rows)
    tout = sum(r["tout"] for r in rows)
    calls = len(rows)
    ok_n = sum(1 for r in rows if r["ok"])

    prov_map: dict[str, list[int]] = {}
    model_set = set()
    buckets = {"白天": 0, "晚间": 0, "深夜": 0, "未知": 0}
    lat_vals = []
    for r in rows:
        p = prov_map.setdefault(r["provider"], [0, 0, 0])
        p[0] += 1
        p[1] += r["tin"]
        p[2] += r["tout"]
        model_set.add(r["model"])
        buckets[hour_bucket(r["ts"])] += 1
        if r["lat"] is not None and r["lat"] > 0:
            lat_vals.append(r["lat"])

    providers = sorted(
        ((k, v[0], v[1] + v[2]) for k, v in prov_map.items()),
        key=lambda x: -x[2],
    )
    total_tok = tin + tout
    lat_avg = sum(lat_vals) / len(lat_vals) if lat_vals else 0.0

    agg = {
        "tin": tin, "tout": tout, "calls": calls, "ok": ok_n,
        "providers": providers, "models": model_set, "buckets": buckets,
        "lat_avg": lat_avg, "lat_n": len(lat_vals),
        "cost_any_zero": True,
    }

    tiers, price_note = (None, "已按 --no-price 跳过")
    if not args.no_price:
        tiers, price_note = fetch_prices()

    cost = {}
    if tiers:
        for key, t in tiers.items():
            cost[key] = tin * t["prompt"] + tout * t["completion"]

    personas = build_personas(agg, tiers)

    start = rows[0]["ts"][:19].replace("T", " ")
    end = rows[-1]["ts"][:19].replace("T", " ")
    days = 1
    try:
        d0 = datetime.fromisoformat(rows[0]["ts"].replace("Z", "+00:00"))
        d1 = datetime.fromisoformat(rows[-1]["ts"].replace("Z", "+00:00"))
        days = max(1, (d1 - d0).days + 1)
    except Exception:  # noqa: BLE001
        pass

    if args.json:
        payload = {
            "ok": True,
            "db": str(db),
            "window": args.since,
            "range": {"from": start, "to": end, "days": days},
            "calls": calls,
            "success": ok_n,
            "success_rate": round(pct(ok_n, calls), 1),
            "tokens_input": tin,
            "tokens_output": tout,
            "tokens_total": total_tok,
            "paid_usd": 0,
            "equivalents": (
                {k: {"label": v["label"], "model": v["model"],
                     "usd_per_m_input": round(v["prompt"] * 1e6, 4),
                     "usd_per_m_output": round(v["completion"] * 1e6, 4),
                     "usd": round(cost[k], 2)} for k, v in tiers.items()}
                if tiers else None
            ),
            "pricing_note": price_note,
            "providers": [{"provider": p, "calls": c, "tokens": t} for p, c, t in providers[:5]],
            "latency_avg_ms": round(lat_avg, 1),
            "buckets": buckets,
            "personas": [{"name": n, "why": w} for n, w in personas],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    W = sys.stdout.write
    line = "─" * 54
    W("\n")
    W("  我的免费模型账本\n")
    W(f"  {line}\n")
    # 首屏先给结论，让价值一眼可见；统计细节放后面。
    if tiers:
        W(f"\n  这 {days} 天，你白嫖了 {money(cost['flagship'])}\n")
        W(f"  {total_tok/1e6:.1f}M token · {calls:,} 次调用 · 实付 {money(0)}\n\n")
    else:
        W(f"\n  这 {days} 天，你白嫖了 {total_tok/1e6:.1f}M token\n")
        W(f"  {calls:,} 次调用 · 实付 {money(0)}\n\n")
    W(f"  统计窗口   {args.since}（{start[:10]} → {end[:10]}，共 {days} 天）\n")
    W(f"  调用次数   {calls:,} 次    成功 {ok_n:,} 次（{pct(ok_n, calls):.0f}%）\n")
    W(f"  Token     输入 {tin:,} + 输出 {tout:,} = 合计 {total_tok:,}\n")
    if lat_avg:
        W(f"  平均响应   {lat_avg/1000:.1f}s（{len(lat_vals)} 次采样）\n")

    W("\n  省了多少钱\n")
    W(f"  {line}\n")
    if tiers:
        W(f"  {'档位':<8}{'对标模型':<36}{'等价支出':>12}\n")
        for key in ("flagship", "main", "economy"):
            t = tiers[key]
            mid = t["model"]
            mid = mid if len(mid) <= 34 else mid[:33] + "…"
            W(f"  {t['label']:<8}{mid:<36}{money(cost[key]):>12}\n")
        lo, hi = cost["economy"], cost["flagship"]
        W(f"\n  你实际支付   {money(0)}\n")
        W(f"  相当于白捡   {money(hi)}（按旗舰档对标 {tiers['flagship']['model']}）\n")
        W(f"  保守口径     {money(lo)}（按经济档对标 {tiers['economy']['model']}）\n")
        W(f"  一句话版本   这批 {total_tok/1e6:.1f}M token，市价约 {money(lo)}–{money(hi)}，你花了 $0\n")
        W(f"  牌价来源     {price_note}\n")
        W(f"               单位 USD / 百万 token：")
        W("；".join(f"{tiers[k]['label']} {tiers[k]['prompt']*1e6:.2f}/{tiers[k]['completion']*1e6:.2f}"
                   for k in ("flagship", "main", "economy")) + "\n")
        W(f"  说明         我们是免费超市，不向用户收取任何费用；以上金额是「若按付费模型牌价\n")
        W(f"               调用同一批 token 需花多少」，用于衡量省下的钱，不代表真实账单。\n")
        W(f"               档位由当日全市场报价分位决定，模型名与单价均已打印，可自行复核。\n")
    else:
        W(f"  跳过金额计算：{price_note}\n")
        if args.no_price:
            W(f"  去掉 --no-price 重跑即可联网取当日牌价。\n")
        else:
            W(f"  牌价拿不到时不编造金额；可稍后重试，或用 --no-price 只看 token 量。\n")

    W("\n  谁在替你干活\n")
    W(f"  {line}\n")
    for p, c, t in providers[:5]:
        bar = "█" * max(1, int(pct(t, total_tok) / 3))
        W(f"  {p[:20]:<21}{c:>6} 次   {pct(t, total_tok):>5.1f}%  {bar}\n")
    if len(providers) > 5:
        W(f"  ……另有 {len(providers)-5} 个渠道\n")

    W("\n  作息分布\n")
    W(f"  {line}\n")
    for k in ("白天", "晚间", "深夜"):
        v = buckets.get(k, 0)
        W(f"  {k}  {v:>5} 次  {pct(v, calls):>5.1f}%\n")

    if personas:
        W("\n  你的画像\n")
        W(f"  {line}\n")
        for n, w in personas:
            W(f"  [{n}] {w}\n")

    W("\n")
    W(f"  数据库 {db}\n")
    W("\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as e:  # noqa: BLE001
        print(f"\n账本生成失败：{type(e).__name__}: {e}\n", file=sys.stderr)
    sys.exit(0)
