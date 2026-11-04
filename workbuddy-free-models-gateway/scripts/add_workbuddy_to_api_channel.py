#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 workbuddy_to_api 暴露的「WorkBuddy 免费额度」模型接入本地 LLM Gateway。

背景（来源：公众号《俯仰未来》2026-09-17 文章）：
  workbuddy_to_api 是一个单文件开源项目，把 WorkBuddy 桌面客户端的免费 credits
  包装成标准 OpenAI 兼容 API，本地端点为 http://127.0.0.1:3000/v1 ，
  暴露 GLM-5.3、Kimi K3、DeepSeek V4、MiniMax M3 等 50+ 模型。

  本脚本把该本地端点作为网关的一个 openai 类型通道接入，使 WorkBuddy 等
  下游工具仍只指向网关(8000)，由网关统一编排/限流/缓存。

依赖前置（务必先满足）：
  1. 已克隆并运行 workbuddy_to_api：
       git clone https://github.com/yxxawa/workbuddy_to_api.git
       cd workbuddy_to_api && python ./workbuddy_to_api.py --background --api-key local
     端点默认 http://127.0.0.1:3000/v1 （可用 --base-url 覆盖）。
     注意：若 WorkBuddy 装在非默认盘（如 D 盘），需显式传：
       --workbuddy-exe "D:/.../WorkBuddy.exe" --cli-script "D:/.../cli/bin/codebuddy"
  2. WorkBuddy 桌面客户端已登录且能正常对话（workbuddy_to_api 会调用其底层 CLI）。
  3. 网关进程启动时需设置 NO_PROXY 含 127.0.0.1（否则本机代理会拦截对 3000 端口的调用）：
       $env:NO_PROXY="127.0.0.1,localhost"; $env:no_proxy="127.0.0.1,localhost"

免费类型标注（永久 / 限时）：
  脚本会读取 WorkBuddy 本地缓存（~/.workbuddy/local_storage/entry_*.info）中的
  modelPromotions / ModelTrialBanner 信息，自动区分：
    - 限时免费：命中「限时免费」「夜间免费」促销，或 trial 试用，或折扣因子为 0（真免费）。
    - 永久免费：其余走免费额度、无到期日的常驻模型。
  标注体现在 WorkBuddy 自定义模型列表（models.json）的显示名前缀：免费-永久-* / 免费-限时-*。

用法：
  python add_workbuddy_to_api_channel.py                 # 自动发现模型并接入（含永久/限时标注）
  python add_workbuddy_to_api_channel.py --discover      # 仅打印模型及其免费类型
  python add_workbuddy_to_api_channel.py --test          # 写入后直连上游做一次真实调用
  python add_workbuddy_to_api_channel.py --disable       # 写入但置为停用
  python add_workbuddy_to_api_channel.py --no-sync-models-json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
# 优先在「当前工作目录」找 gateway.db（用户在网关根目录运行本脚本时），
# 否则退回脚本所在目录。这样 skill 的脚本可直接在任意本地网关目录运行。
_CWD = os.getcwd()
DB_PATH = os.path.join(_CWD, "gateway.db") if os.path.exists(os.path.join(_CWD, "gateway.db")) else os.path.join(HERE, "gateway.db")
MODELS_JSON = os.path.join(os.path.expanduser("~"), ".workbuddy", "models.json")
LOCAL_STORAGE = os.path.join(os.path.expanduser("~"), ".workbuddy", "local_storage")

CHANNEL_NAME = "wb2api"
CHANNEL_TYPE = "openai"
DEFAULT_BASE_URL = "http://127.0.0.1:3000"   # 网关自动补 /v1/chat/completions
DEFAULT_KEY = "local"                          # 与 workbuddy_to_api --api-key 保持一致
FALLBACK_MODELS = [
    "glm-5.3", "glm-5.3-flash", "kimi-k3", "deepseek-v4",
    "deepseek-v4-flash", "minimax-m3", "qwen3.8-max",
]
EXPOSED_PREFIX = "wb-"   # 网关对外暴露名前缀，避免与其它渠道模型名冲突


def slug(model: str) -> str:
    # 保留点号，仅把其它非字母数字字符替换为横杠（如 glm-5.3 -> wb-glm-5.3）
    return EXPOSED_PREFIX + re.sub(r"[^a-z0-9.]+", "-", model.lower()).strip("-")


# --------------------------------------------------------------------------
# 从 workbuddy_to_api 实时发现模型
# --------------------------------------------------------------------------
def discover_models(base_url: str, key: str, timeout: int = 20) -> list[str]:
    url = base_url.rstrip("/") + "/v1/models"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 绕过本机代理
    try:
        with opener.open(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        ids = [m.get("id") for m in data.get("data", []) if m.get("id")]
        print(f"[discover] 从 {url} 发现 {len(ids)} 个模型")
        return ids
    except Exception as e:
        print(f"[discover] 拉取 /v1/models 失败（{e}），回退到兜底清单")
        return list(FALLBACK_MODELS)


# --------------------------------------------------------------------------
# 读取 WorkBuddy 本地缓存，区分「永久免费 / 限时免费」
# --------------------------------------------------------------------------
def load_classification() -> tuple[dict, set, dict, dict]:
    """返回 (names_by_id, limited_set, notes_by_id, expires_by_id)。

    - names_by_id:  模型 id -> 显示名（取自缓存 models 列表）
    - limited_set:  命中限时免费促销 / 试用的模型 id 集合
    - notes_by_id:  模型 id -> 人类可读说明（到期日 / 夜间免费 / 试用天数）
    - expires_by_id: 模型 id -> 到期日 (YYYY-MM-DD)，无到期日则为 ""
    """
    names_by_id: dict[str, str] = {}
    limited_set: set[str] = set()
    notes_by_id: dict[str, str] = {}
    expires_by_id: dict[str, str] = {}

    if not os.path.isdir(LOCAL_STORAGE):
        return names_by_id, limited_set, notes_by_id, expires_by_id

    best = None
    for fn in os.listdir(LOCAL_STORAGE):
        if not fn.startswith("entry_") or not fn.endswith(".info"):
            continue
        path = os.path.join(LOCAL_STORAGE, fn)
        try:
            parsed = json.loads(open(path, encoding="utf-8-sig").read())
        except Exception:
            continue
        entries = parsed if isinstance(parsed, list) else [parsed]
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            d = entry.get("data") if isinstance(entry.get("data"), dict) else None
            if not d or not isinstance(d.get("models"), list):
                continue
            stamp = float(entry.get("ts") or os.path.getmtime(path) * 1000)
            if best is None or stamp > best[0]:
                best = (stamp, d)

    if not best:
        return names_by_id, limited_set, notes_by_id, expires_by_id

    data = best[1]
    for m in data.get("models", []):
        if isinstance(m, dict) and m.get("id"):
            names_by_id[m["id"]] = m.get("name") or m["id"]

    def _factor(promo):
        disc = promo.get("discount")
        if isinstance(disc, dict):
            f = disc.get("factor")
            if isinstance(f, (int, float)):
                return float(f)
            s = str(disc.get("discountedCredits") or "")
            m = re.match(r"([0-9.]+)x", s)
            if m:
                return float(m.group(1))
        return None

    # 促销：限时免费 / 夜间免费 / 真免费(因子0)
    for p in data.get("modelPromotions", []):
        if not p.get("enabled"):
            continue
        label = (p.get("badge") or {}).get("label") or ""
        f = _factor(p)
        sched = p.get("schedule") or {}
        valid_until = sched.get("validUntil")
        is_free_factor = (f is not None and f == 0)
        is_limited_badge = ("限时免费" in label) or ("夜间免费" in label)
        if not (is_free_factor or is_limited_badge):
            continue  # 仅是「折扣 / 优惠」角标，不算限时免费
        note = label
        if valid_until:
            note = f"{label}（至 {valid_until[:10]}）"
        for mid in p.get("modelIds", []):
            limited_set.add(mid)
            notes_by_id[mid] = note
            expires_by_id[mid] = valid_until[:10] if valid_until else ""

    # 试用横幅（trial）：仅标注「试用模型本身」（如 hy4-preview-f），不要覆盖
    # 其对应正式模型（targetModelId，如 hy4-preview）已有的「夜间免费/限时免费」说明。
    mb = (data.get("productFeaturesConfig") or {}).get("ModelTrialBanner") or {}
    for b in mb.get("banners", []):
        mid = b.get("modelId")
        days = b.get("trialDays")
        if mid:
            limited_set.add(mid)
            notes_by_id.setdefault(mid, f"试用 {days} 天" if days else "限时试用")

    return names_by_id, limited_set, notes_by_id, expires_by_id


# --------------------------------------------------------------------------
# 数据库操作
# --------------------------------------------------------------------------
def upsert_channel(key: str, base_url: str, models: list[str], enable: bool = True) -> dict:
    exposed = {slug(m): m for m in models}
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    row = cur.execute("SELECT id FROM channels WHERE name = ?", (CHANNEL_NAME,)).fetchone()

    if row:
        cur.execute(
            "UPDATE channels SET type=?, base_url=?, api_key=?, models=?, model_map=?, "
            "status=?, last_health='ok', fail_count=0, cooldown_until=NULL WHERE name=?",
            (CHANNEL_TYPE, base_url, key, json.dumps(list(exposed.keys()), ensure_ascii=False),
             json.dumps(exposed, ensure_ascii=False), 1 if enable else 0, CHANNEL_NAME),
        )
        action = "更新"
    else:
        cur.execute(
            "INSERT INTO channels (name, type, base_url, api_key, models, model_map, \"group\", "
            "weight, priority, status, pricing_ratio, used_quota, last_health, fail_count, "
            "cooldown_until, tested_at, created_at) "
            "VALUES (?,?,?,?,?,?,'default',1,0,?,1.0,0,'ok',0,NULL,NULL,?)",
            (CHANNEL_NAME, CHANNEL_TYPE, base_url, key,
             json.dumps(list(exposed.keys()), ensure_ascii=False),
             json.dumps(exposed, ensure_ascii=False), 1 if enable else 0, now),
        )
        action = "新增"
    conn.commit()

    row = cur.execute(
        "SELECT id, name, base_url, models, model_map, status FROM channels WHERE name = ?",
        (CHANNEL_NAME,),
    ).fetchone()
    conn.close()
    result = dict(row)
    result["action"] = action
    return result


# --------------------------------------------------------------------------
# 免费模型元数据（网关 /v1/models 与到期提醒脚本的单一数据源）
# --------------------------------------------------------------------------
def write_free_meta(models: list[str], limited: set, notes: dict, expires: dict,
                    path: str | None = None) -> int:
    """写入 free_models_meta.json：以网关对外暴露名（wb-*）为键。

    网关 /v1/models 与 check_free_expiry.py 都读这个文件，避免逻辑分散。
    """
    if path is None:
        path = os.path.join(os.path.dirname(DB_PATH), "free_models_meta.json")
    models_meta: dict[str, dict] = {}
    for m in models:
        mid = slug(m)
        is_limited = m in limited
        exp = expires.get(m) or None
        models_meta[mid] = {
            "free_type": "limited" if is_limited else "permanent",
            "expires_at": exp,
            "note": notes.get(m, ""),
        }
    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "WorkBuddy local cache entry_*.info (modelPromotions / ModelTrialBanner)",
        "models": models_meta,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    n_lim = sum(1 for v in models_meta.values() if v["free_type"] == "limited")
    print(f"[ok] 免费模型元数据已写入 {path}（共 {len(models_meta)} 个，限时 {n_lim} 个）")
    return len(models_meta)


# --------------------------------------------------------------------------
# WorkBuddy 自定义模型列表（models.json）—— 带 永久/限时 标注
# --------------------------------------------------------------------------
def sync_models_json(models: list[str], gateway_url: str, gateway_key: str,
                     limited: set, notes: dict, enable: bool = True) -> int:
    if not os.path.exists(MODELS_JSON):
        print(f"[warn] 未找到 {MODELS_JSON}，跳过 models.json 同步")
        return 0

    with open(MODELS_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 先清掉本脚本历史上写入的条目（id 以 wb- 开头），避免重复 / 旧 slug 残留
    before = len(data)
    data = [m for m in data if not (isinstance(m, dict) and str(m.get("id", "")).startswith(EXPOSED_PREFIX))]
    removed = before - len(data)

    added = 0
    for m in models:
        mid = slug(m)
        kind = "限时" if m in limited else "永久"
        note = notes.get(m, "")
        name = f"免费-{kind}-{m}" + (f"（{note}）" if note else "")
        data.append({
            "id": mid,
            "name": name,
            "vendor": "Custom",
            "url": gateway_url,
            "apiKey": gateway_key,
            "supportsToolCall": True,
            "supportsImages": False,
            "supportsReasoning": True,
            "useCustomProtocol": False,
        })
        added += 1

    with open(MODELS_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[ok] models.json 清理旧条目 {removed} 条，新增 {added} 条（含 永久/限时 标注）")
    return added


def read_gateway_cred() -> tuple[str, str]:
    url, key = "http://127.0.0.1:8000/v1", ""
    if os.path.exists(MODELS_JSON):
        with open(MODELS_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        for m in data:
            if m.get("url"):
                url = m["url"]
                key = m.get("apiKey", "")
                break
    return url, key


# --------------------------------------------------------------------------
# 连通性测试（绕过本机 HTTP 代理，直连上游）
# --------------------------------------------------------------------------
def test_upstream(key: str, base_url: str, model: str) -> bool:
    url = base_url.rstrip("/") + "/v1/chat/completions"
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "回复两个字：正常"}],
        "max_tokens": 32,
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=90) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        choices = body.get("choices") or []
        content = (choices[0].get("message", {}).get("content") if choices else "") or ""
        print(f"[test] {model} -> HTTP {resp.status}: {content.strip()[:120]}")
        return True
    except urllib.error.HTTPError as e:
        print(f"[test] {model} -> HTTP {e.code}: {e.read().decode('utf-8', 'ignore')[:300]}")
    except Exception as e:
        print(f"[test] {model} -> 失败: {e}")
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="接入 workbuddy_to_api（WorkBuddy 免费额度）渠道到 LLM Gateway")
    ap.add_argument("--key", default=DEFAULT_KEY, help=f"workbuddy_to_api 的 --api-key，默认 {DEFAULT_KEY}")
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL, help=f"默认 {DEFAULT_BASE_URL}")
    ap.add_argument("--discover", action="store_true", help="仅打印将从 /v1/models 发现的模型并退出")
    ap.add_argument("--test", action="store_true", help="写入后直连上游做一次真实调用验证")
    ap.add_argument("--disable", action="store_true", help="写入但置为停用")
    ap.add_argument("--no-sync-models-json", action="store_true", help="不改动 WorkBuddy 的 models.json")
    args = ap.parse_args()

    models = discover_models(args.base_url, args.key)
    if not models:
        print("[error] 未发现任何模型，退出")
        return 1

    names, limited, notes, expires = load_classification()
    n_limited = sum(1 for m in models if m in limited)
    print(f"[classify] 永久免费 {len(models) - n_limited} 个，限时免费 {n_limited} 个")

    if args.discover:
        for m in models:
            kind = "限时" if m in limited else "永久"
            note = f"  ({notes[m]})" if m in notes else ""
            print(f"{slug(m):40s} [{kind}]{note:24s} <- {m}")
        return 0

    if not os.path.exists(DB_PATH):
        print(f"[error] 未找到数据库 {DB_PATH}")
        return 1

    print(f"渠道名    : {CHANNEL_NAME}")
    print(f"上游地址  : {args.base_url}  (网关自动补 /v1/chat/completions)")
    print(f"鉴权 Key  : {args.key}")
    print(f"模型映射  :")
    for m in models:
        kind = "限时" if m in limited else "永久"
        print(f"    {slug(m):34s} [{kind}] -> {m}")

    ch = upsert_channel(args.key, args.base_url, models, enable=not args.disable)
    print(f"\n[ok] 渠道已{ch['action']}：id={ch['id']} name={ch['name']} status={ch['status']}")

    # 始终刷新免费模型元数据（网关 /v1/models 标注 + 到期提醒脚本共用）
    write_free_meta(models, limited, notes, expires)

    if not args.no_sync_models_json:
        gw_url, gw_key = read_gateway_cred()
        sync_models_json(models, gw_url, gw_key, limited, notes, enable=not args.disable)

    if args.test:
        print("\n[test] 直连上游验证（绕过本机代理）...")
        for m in models[:5]:
            test_upstream(args.key, args.base_url, m)

    print("\n[next] 重启网关后生效（注意先设置 NO_PROXY 含 127.0.0.1）：")
    print("    $env:NO_PROXY='127.0.0.1,localhost'; $env:no_proxy='127.0.0.1,localhost'")
    print("    .\\.venv\\Scripts\\python.exe run.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
