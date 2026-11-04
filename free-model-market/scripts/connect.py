#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
免费模型超市 · 一键接入引擎（connect）

把「挑模型 → 点一下接入 → 立刻能聊」做成一条确定性流水线，抹平用户侧
所有手工环节（找 Key、填接口、记模型名、刷新模型选择器）。

实测依据（本脚本每条行为都有 2026-10-20 一手实测支撑）：
  * **WorkBuddy 客户端不热加载 models.json**。对 WorkBuddy 安装目录
    app.asar.unpacked 全量检索 `chokidar` / `.watch(` 命中数为 **0**；
    models.json 仅在渲染进程的「自定义模型」设置面板里被读写。
    ⇒ 写入后**必须重启客户端**才生效，脚本会明确提示，绝不谎称「即时生效」。
  * **网关 `/api/combos` 用网关 Key 即可读**（实测 HTTP 200，含完整
    providerId / model / strategy），`/v1/chat/completions` 空体返 400 = 在线。
    ⇒ 组合链（模型名即 combo 名）可被脚本直接发现，无需用户记模型名。
  * **视觉真伪判据**：模型否认看到图片 / 复述错误细节 = 幻觉；
    说出正确主色 = 真视觉（2026-10-20 实测：nvidia/meta/llama-3.2-11b-vision-instruct
    对纯红 8x8 PNG 答 "Red."，而同链的 nvidia/openai/gpt-oss-20b 答 "Blue" 且带否认表述）。
    ⇒ 能力标签只按实测结果写，绝不按模型名猜。
  * **免费层并发上限 = 1**（NVIDIA NIM 2026-10-07 实测）。⇒ 探测必须**串行**，
    并发发请求会把「可用」误判成超时。

设计铁律（继承项目指令）：
  * 默认 dry-run，只读不改；`--apply` 才落盘，`--yes` 跳过交互确认。
  * 幂等：已存在且配置一致的条目跳过，不重复写。
  * 绝不臆造配额与能力标签；未核实项写 `unknown`。
  * **Key 只从环境变量 / 已存在的 models.json 读取，绝不写入任何产物、报告或日志。**
  * 识别 models.json 为数组或 {"models":[...]}；形态未知则中止，不猜。
  * 绝不擅自改用户已有的 apiKey —— 换 Key 的动作归用户。
  * 🔴 **绝不动用户的第三方 / 付费条目**：若同 id 条目已存在且其 url 不指向本地网关，
    一律跳过并提示，只有显式加 `--replace-foreign` 才覆盖（v1.0.16 修复：
    此前会按 id 整体替换，把用户自己的付费条目改写成指向本地网关，付费 Key 丢失）。

用法：
    python 免费模型超市-connect.py                       列出可选组合（默认动作）
    python 免费模型超市-connect.py --list                 同上，列出网关内可用 combo
    python 免费模型超市-connect.py --connect free-vision  预览接入 free-vision
    python 免费模型超市-connect.py --connect free-vision --apply --yes   落盘
    python 免费模型超市-connect.py --connect all --apply --yes           接入全部
    python 免费模型超市-connect.py --probe                实测网关各 combo 真实可用性
    python 免费模型超市-connect.py --models-path <路径>   指定其他 models.json

仅用标准库；Windows Git-Bash 下中文输出已做 stdout 编码处理。
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
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent if HERE.name == "scripts" else HERE
CATALOG_JSON = SKILL_ROOT / "references" / "model-catalog.json"

DEFAULT_GATEWAY = "http://127.0.0.1:20128"

# 网关组合（combo）→ WorkBuddy 侧的展示名与能力标签。
# ⚠️ supportsImages 必须来自实测（见文件头「视觉真伪判据」），不得按模型名推断。
#    2026-10-20 实测（纯红 8x8 PNG 判据）：
#      nvidia/meta/llama-3.2-11b-vision-instruct 直连 → 答 "Red."（真视觉，3.7s）
#      nvidia/openai/gpt-oss-20b 直连 → 答 "Blue" 且带否认表述（纯文本模型，78.7s）
#    ⚠️ **Vision Bridge 混合链陷阱**（同日实测）：combo 内同时含视觉与非视觉节点时，
#      无论视觉节点排第几，网关都会启用 Vision Bridge 把图片转成文字描述，
#      模型遂答 "I'm unable to view the image."（11.2s / 17.8s）——**丢图**。
#      纯视觉单节点 combo 实测正常（答 "Red."，2.0s）。
#      ⇒ free-vision 已据此重建为纯视觉链，可安全声明 supportsImages=True。
COMBO_PROFILES = {
    "free-vision": {
        "name": "免费模型(文本+图片,推荐)",
        "supportsImages": True,
        "supportsToolCall": False,
        "supportsReasoning": True,
        "note": "纯视觉链（避开了 Vision Bridge 混合链丢图陷阱），实测可读图",
    },
    "free-multi": {
        "name": "自由模型组合(free-multi)",
        "supportsImages": False,
        "supportsToolCall": True,
        "supportsReasoning": True,
        "note": "文本主力组合，priority 策略额度用完自动切换",
    },
    "zero-cost-free": {
        "name": "零成本免费组合(zero-cost-free)",
        "supportsImages": False,
        "supportsToolCall": True,
        "supportsReasoning": True,
        "note": "最小最稳单链，适合判题/向量化等高频小调用",
    },
    "free-pool-expanded": {
        "name": "免费模型扩展池",
        "supportsImages": False,
        "supportsToolCall": True,
        "supportsReasoning": True,
        "note": "全量池，节点最多，容错最高",
    },
}

DEFAULT_PROFILE = {
    "name": None,
    "supportsImages": False,
    "supportsToolCall": True,
    "supportsReasoning": True,
    "note": "未在白名单中的组合，按保守默认写标签",
}


# ─────────────────────────────────────────────────────────────────────────────
# 0. 控制台编码处理（Windows Git-Bash 下 stdout 可能是 GBK，直接打印中文会崩）
# ─────────────────────────────────────────────────────────────────────────────
def _fix_stdio_encoding() -> None:
    for name in ("stdout", "stderr"):
        buf = getattr(sys, name, None)
        if buf is None:
            continue
        cur = getattr(buf, "encoding", "") or ""
        if cur.lower() in ("utf-8", "utf8", "utf8mb4"):
            continue
        try:
            raw = buf.buffer
        except Exception:
            continue
        try:
            setattr(sys, name, raw.reconfigure(encoding="utf-8", errors="replace"))
        except Exception:
            pass


TZ = timezone(timedelta(hours=8))


def now_str() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M GMT+8")


def mask(key: str) -> str:
    """脱敏显示：只给前 6 + 后 4 字符。"""
    if not key:
        return "<empty>"
    if len(key) <= 12:
        return key[:3] + "****"
    return key[:6] + "****" + key[-4:]


# ─────────────────────────────────────────────────────────────────────────────
# 1. 定位 WorkBuddy models.json
# ─────────────────────────────────────────────────────────────────────────────
def default_models_path() -> Path:
    home = Path(os.environ.get("USERPROFILE", os.environ.get("HOME", "~"))).expanduser()
    return home / ".workbuddy" / "models.json"


def load_models_json(path: Path):
    """返回 (entries, shape)。shape ∈ {missing, array, object-models, unknown}。"""
    if not path.exists():
        return [], "missing"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return None, f"parse-error:{e}"
    if isinstance(data, list):
        return data, "array"
    if isinstance(data, dict) and isinstance(data.get("models"), list):
        return data["models"], "object-models"
    return None, "unknown"


# ─────────────────────────────────────────────────────────────────────────────
# 2. 网关访问
# ─────────────────────────────────────────────────────────────────────────────
def gateway_key(models_path: Path) -> str:
    """读取可用于调用网关的 Key。

    优先级：**已配置的本地网关条目** → OMNIROUTE_API_KEY 环境变量。
    取已配置条目优先，有两个理由：
      ① 一致性——避免同一份 models.json 里出现两个不同 Key，用户在设置界面
         看到 Key 不一致会困惑；
      ② 权限最小化——环境变量里的 Key 是 CLI/管理面用的凭证，不应下沉到
         用户侧配置文件里。
    两者都只读，绝不回写、绝不打印完整值。
    """
    entries, shape = load_models_json(models_path)
    if isinstance(entries, list):
        for m in entries:
            url = str(m.get("url", ""))
            if "127.0.0.1:20128" in url or "localhost:20128" in url:
                k = str(m.get("apiKey", "")).strip()
                if k:
                    return k
    return os.environ.get("OMNIROUTE_API_KEY", "").strip()


def http_json(url: str, key: str, timeout: int = 15, method: str = "GET", body=None):
    """返回 (status, parsed_json_or_None, raw_text)。HTTPError 也返回状态码。"""
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, method=method, data=data,
        headers={"authorization": "Bearer " + key, "content-type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            try:
                return r.status, json.loads(raw), raw
            except Exception:  # noqa: BLE001
                return r.status, None, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw), raw
        except Exception:  # noqa: BLE001
            return e.code, None, raw
    except Exception as e:  # noqa: BLE001
        return 0, None, str(e)


def gateway_online(base: str, key: str) -> tuple[bool, str]:
    """探针：POST /v1/chat/completions 空体返 400 = 在线标志。"""
    status, _j, raw = http_json(
        base + "/v1/chat/completions", key, timeout=12, method="POST", body={}
    )
    if status == 400:
        return True, "HTTP 400（在线标志）"
    if status == 0:
        return False, "连不上（网关未启动或端口不通）"
    return False, f"HTTP {status}（非预期，可能鉴权异常）"


def list_combos(base: str, key: str):
    """GET /api/combos → (ok, combos, error)。"""
    status, j, raw = http_json(base + "/api/combos", key, timeout=15)
    if status == 200 and isinstance(j, dict) and isinstance(j.get("combos"), list):
        return True, j["combos"], None
    return False, [], f"HTTP {status}: {raw[:200]}"


def probe_combo(base: str, key: str, combo: str, timeout: int = 45):
    """实测一个 combo 是否真能出内容（判据：HTTP 200 且 content 非空）。

    返回 dict: {ok, status, ms, content, error, vision}
    """
    payload = {
        "model": combo,
        "messages": [{"role": "user", "content": "Reply with the single word OK"}],
        "max_tokens": 2000,
    }
    t0 = time.time()
    status, j, raw = http_json(
        base + "/v1/chat/completions", key, timeout=timeout, method="POST", body=payload
    )
    ms = int((time.time() - t0) * 1000)
    content = None
    err = None
    if isinstance(j, dict):
        choices = j.get("choices") or []
        if choices:
            content = (choices[0].get("message") or {}).get("content")
        if j.get("error"):
            e = j["error"]
            err = str(e.get("message") if isinstance(e, dict) else e)[:160]
    ok = status == 200 and content is not None and str(content).strip() != ""
    return {"ok": ok, "status": status, "ms": ms, "content": content, "error": err}


# ─────────────────────────────────────────────────────────────────────────────
# 3. 组装 models.json 条目
# ─────────────────────────────────────────────────────────────────────────────
def build_entry(combo: str, base: str, key: str) -> dict:
    prof = COMBO_PROFILES.get(combo, DEFAULT_PROFILE)
    name = prof.get("name") or combo
    return {
        "id": combo,
        "name": name,
        "vendor": "OmniRoute 本地网关",
        "url": base + "/v1",
        "apiKey": key,
        "supportsToolCall": bool(prof.get("supportsToolCall")),
        "supportsImages": bool(prof.get("supportsImages")),
        "supportsReasoning": bool(prof.get("supportsReasoning")),
        "useCustomProtocol": False,
        "maxInputTokens": 32768,
    }


def entry_matches(old: dict, new: dict) -> bool:
    """比较除 id 外的关键字段是否已一致（用于幂等判定）。"""
    keys = ("url", "vendor", "supportsToolCall", "supportsImages",
            "supportsReasoning", "useCustomProtocol", "maxInputTokens")
    for k in keys:
        if old.get(k) != new.get(k):
            return False
    return True


LOCAL_GATEWAY_HINTS = ("127.0.0.1:20128", "localhost:20128", "[::1]:20128")


def is_local_gateway_entry(entry: dict) -> bool:
    """该条目是不是「指向本地 OmniRoute 网关」的条目（= 本工具自己的产物）。

    判据只看 url，不看 id / name / vendor —— 用户完全可以把条目改名改标签，
    但只要 url 还指着本地网关，它就是可安全更新的自家条目。
    """
    url = str(entry.get("url", ""))
    return any(h in url for h in LOCAL_GATEWAY_HINTS)


# ─────────────────────────────────────────────────────────────────────────────
# 4. 各动作
# ─────────────────────────────────────────────────────────────────────────────
def cmd_list(base: str, key: str, args) -> int:
    ok, combos, err = list_combos(base, key)
    print(f"[探测] 网关 {base} | Key {mask(key)} | {now_str()}")
    if not ok:
        print(f"[错误] 读取组合列表失败：{err}")
        print("[提示] 若网关未启动，请先运行「自由模型市场·网关」助手的 quickstart，或直接起网关。")
        return 2
    if not combos:
        print("[警告] 网关内没有任何组合（空库）。请检查 DATA_DIR 是否为绝对路径。")
        return 2
    print(f"[信息] 网关内共 {len(combos)} 个组合，可一键接入：\n")
    print("| 组合名 | 策略 | 节点数 | 展示名 | 说明 |")
    print("|---|---|---:|---|---|")
    for c in combos:
        nm = c.get("name", "?")
        prof = COMBO_PROFILES.get(nm, DEFAULT_PROFILE)
        print(f"| `{nm}` | {c.get('strategy', '?')} | {len(c.get('models', []))} | "
              f"{prof.get('name') or nm} | {prof.get('note', '')} |")
    print("\n[下一步] 接入命令：")
    for c in combos:
        nm = c.get("name")
        print(f"  python connect.py --connect {nm} --apply --yes")
    print("  python connect.py --connect all --apply --yes   # 一次接入全部")
    return 0


def cmd_probe(base: str, key: str, args) -> int:
    ok, combos, err = list_combos(base, key)
    print(f"[探测] 网关 {base} | {now_str()}")
    if not ok:
        print(f"[错误] 读取组合列表失败：{err}")
        return 2
    print("[说明] 免费层并发上限通常为 1，故**串行**探测；单组合超时 "
          f"{args.timeout}s。\n")
    print("| 组合名 | HTTP | 耗时 | 真出内容 | 内容 |")
    print("|---|---:|---:|---|---|")
    good = []
    for c in combos:
        nm = c.get("name", "?")
        r = probe_combo(base, key, nm, timeout=args.timeout)
        mark = "✅" if r["ok"] else "❌"
        body = (str(r["content"])[:40] if r["content"] is not None
                else (r["error"] or "-"))
        print(f"| `{nm}` | {r['status']} | {r['ms']}ms | {mark} | {body} |")
        if r["ok"]:
            good.append(nm)
    print(f"\n[结论] {len(good)}/{len(combos)} 个组合可真实出内容："
          f"{', '.join(good) if good else '（无）'}")
    if good:
        print("[下一步] 接入可用组合：")
        print(f"  python connect.py --connect {good[0]} --apply --yes")
    return 0 if good else 1


def cmd_connect(base: str, key: str, args) -> int:
    target = args.connect
    models_path = Path(args.models_path).expanduser() if args.models_path else default_models_path()

    ok, combos, err = list_combos(base, key)
    print(f"[探测] 网关 {base} | Key {mask(key)} | {now_str()}")
    if not ok:
        print(f"[错误] 读取组合列表失败：{err}")
        return 2
    names = [c.get("name") for c in combos]
    if target == "all":
        wanted = names
    else:
        if target not in names:
            print(f"[错误] 网关内没有组合 `{target}`。当前可用：{', '.join(names)}")
            return 2
        wanted = [target]
    if not wanted:
        print("[错误] 没有可接入的组合。")
        return 2

    entries, shape = load_models_json(models_path)
    if shape == "unknown":
        print(f"[错误] {models_path} 结构无法识别（{shape}），中止写入以免损坏，请人工检查。")
        return 2
    if shape.startswith("parse-error"):
        print(f"[错误] {models_path} 解析失败（{shape}），中止写入。")
        return 2
    if shape == "missing":
        entries = []
        print(f"[计划] {models_path} 不存在，将新建")
    else:
        print(f"[计划] {models_path}（形态 {shape}），现有 {len(entries)} 条")

    # 逐个组合实测 —— 只把真能出内容的写进去（不把死链塞给用户）
    picked, rejected = [], []
    for nm in wanted:
        r = probe_combo(base, key, nm, timeout=args.timeout)
        if r["ok"]:
            picked.append((nm, r))
        else:
            rejected.append((nm, r))
        print(f"[实测] {nm}: HTTP {r['status']} {r['ms']}ms → "
              f"{'可用' if r['ok'] else '不可用（' + str(r['error'])[:60] + '）'}")

    if rejected:
        print(f"\n[跳过] {len(rejected)} 个组合实测不可用，不写入：")
        for nm, r in rejected:
            print(f"  - {nm}: HTTP {r['status']} {r['error'] or ''}")

    if not picked:
        print("\n[错误] 没有任何组合实测可用，拒绝写入。")
        return 1

    existing_ids = {m.get("id") for m in entries if isinstance(m, dict)}
    to_add, skip, protected = [], 0, []
    for nm, _r in picked:
        new = build_entry(nm, base, key)
        old = next((m for m in entries if isinstance(m, dict) and m.get("id") == nm), None)
        if old is not None:
            if entry_matches(old, new):
                skip += 1
                print(f"[幂等] `{nm}` 已存在且配置一致，跳过")
            elif not is_local_gateway_entry(old) and not args.replace_foreign:
                # 用户自己的第三方 / 付费条目，只是 id 撞了 —— 不动它
                protected.append((nm, old))
                print(f"[保护] `{nm}` 已被一条**非本地网关**条目占用"
                      f"（{old.get('vendor') or '?'} → {str(old.get('url'))[:46]}），"
                      f"不覆盖。要用本地网关版本请改名，或显式加 --replace-foreign")
            else:
                to_add.append(("replace", nm, new))
                print(f"[更新] `{nm}` 存在但配置有差异，将更新")
        else:
            to_add.append(("add", nm, new))
            print(f"[新增] `{nm}` → {new['name']}")

    if protected:
        print(f"\n[汇总] {len(protected)} 条因 id 被非本地网关条目占用而跳过："
              + "、".join(f"`{n}`" for n, _ in protected))

    if not to_add:
        print(f"\n[结果] 无需变更（跳过 {skip} 条已存在"
              f"{'，保护 %d 条非本地网关条目' % len(protected) if protected else ''}）。")
        print("[生效] 无需重启客户端。")
        return 0

    if not args.apply:
        print(f"\n[dry-run] 预演：将写入/更新 {len(to_add)} 条，未做任何改动。")
        print("         加 --apply 实际落盘（--yes 跳过交互确认）。")
        return 0

    if not args.yes:
        ans = input("确认写入以上条目到 models.json？(y/N) ").strip().lower()
        if ans != "y":
            print("[apply] 已取消。")
            return 0

    # 备份（带时间戳，不覆盖上一次备份）
    if models_path.exists():
        bak = models_path.with_name(
            models_path.name + ".bak-" + datetime.now(TZ).strftime("%Y%m%d-%H%M%S"))
        bak.write_text(models_path.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"[备份] 原文件已备份 → {bak.name}")

    merged = list(entries)
    for action, nm, new in to_add:
        if action == "replace":
            merged = [m if not (isinstance(m, dict) and m.get("id") == nm) else new for m in merged]
        else:
            merged.append(new)

    models_path.parent.mkdir(parents=True, exist_ok=True)
    if shape == "object-models":
        raw = json.loads(models_path.read_text(encoding="utf-8")) if models_path.exists() else {}
        raw["models"] = merged
        out = raw
    else:
        out = merged
    models_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n[OK] 已写入 {len(to_add)} 条 → {models_path}")
    print("\n[生效方式 · 实测依据] WorkBuddy 客户端**不热加载** models.json"
          "（对安装目录 app.asar.unpacked 全量检索 chokidar/.watch( 命中数为 0，"
          "models.json 仅在「自定义模型」设置面板被读写）。")
    print("        ⇒ **请重启 WorkBuddy 客户端**，然后在模型选择器里就能看到新模型。")
    print("        （这一步无法省略：客户端没有文件监听，写完不重启不会生效。）")
    return 0


def cmd_catalog(args) -> int:
    """列出货架里 active 且可推荐候选的厂商（供挑选）。"""
    if not CATALOG_JSON.exists():
        print(f"[错误] 找不到 {CATALOG_JSON}")
        return 2
    data = json.loads(CATALOG_JSON.read_text(encoding="utf-8"))
    providers = data.get("providers", [])
    print(f"[货架] {len(providers)} 家厂商 | 快照 {data.get('snapshot_date', 'unknown')} | {now_str()}\n")
    print("| # | 厂商 | 状态 | 免费额度 | 端点 |")
    print("|---:|---|---|---|---|")
    for i, p in enumerate(providers, 1):
        st = p.get("status", "?")
        if st not in ("active",):
            continue
        print(f"| {i} | {p.get('name')} | {st} | {str(p.get('quota', ''))[:40]} | "
              f"`{str(p.get('endpoints', [''])[0] if p.get('endpoints') else '')}` |")
    print("\n[提示] 货架中 status=active 的渠道为可推荐候选；"
          "degraded / unverified / expired 仅作背景说明，不进推荐池。")
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# 5. 入口
# ─────────────────────────────────────────────────────────────────────────────
def main() -> int:
    _fix_stdio_encoding()
    ap = argparse.ArgumentParser(
        description="免费模型超市 · 一键接入引擎（挑模型 → 点一下接入 → 立刻能聊）"
    )
    ap.add_argument("--list", action="store_true", help="列出网关内可用组合")
    ap.add_argument("--probe", action="store_true", help="实测网关各组合真实可用性")
    ap.add_argument("--catalog", action="store_true", help="列出货架可推荐厂商")
    ap.add_argument("--connect", metavar="NAME", help="接入指定组合（all = 全部）")
    ap.add_argument("--apply", action="store_true", help="实际写入（默认 dry-run）")
    ap.add_argument("--yes", action="store_true", help="跳过交互确认")
    ap.add_argument("--models-path", metavar="PATH", help="指定 models.json 路径")
    ap.add_argument("--gateway", default=DEFAULT_GATEWAY, help=f"网关地址（默认 {DEFAULT_GATEWAY}）")
    ap.add_argument("--timeout", type=int, default=45, help="单次探测超时秒数（默认 45）")
    ap.add_argument("--replace-foreign", action="store_true",
                    help="允许覆盖 id 相同但指向第三方/付费端点的既有条目（默认保护，不覆盖）")
    args = ap.parse_args()

    if args.catalog:
        return cmd_catalog(args)

    base = args.gateway.rstrip("/")
    models_path = Path(args.models_path).expanduser() if args.models_path else default_models_path()
    key = gateway_key(models_path)

    # 优雅降级：无 Key / 网关不可达时，默认动作回退到离线货架总览（总有输出、正常退出），
    # 显式子命令（--probe / --connect / --list）才报错退出，便于排障。
    explicit = args.probe or args.connect or args.list
    if not key:
        print("[错误] 找不到网关 Key。请设环境变量 OMNIROUTE_API_KEY，"
              "或先在 models.json 里配置一条指向 127.0.0.1:20128 的条目。")
        if explicit:
            return 2
        print("[降级] 转为展示离线货架总览：\n")
        return cmd_catalog(args)

    online, detail = gateway_online(base, key)
    if not online:
        if explicit:
            print(f"[错误] 网关不可用：{detail}")
            print("[提示] 请先启动网关（自由模型市场·网关 助手），"
                  "或用 --gateway 指定地址。")
            return 2
        print(f"[警告] 网关探针异常：{detail}。")
        print("[降级] 转为展示离线货架总览：\n")
        return cmd_catalog(args)

    if args.probe:
        return cmd_probe(base, key, args)
    if args.connect:
        return cmd_connect(base, key, args)
    return cmd_list(base, key, args)


if __name__ == "__main__":
    sys.exit(main())
