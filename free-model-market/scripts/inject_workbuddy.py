#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
免费模型超市 · Kilo 免 Key 注入器（2026-10-30 换源版）

把 Kilo AI Gateway 的免注册免费模型写入 WorkBuddy 的 ~/.workbuddy/models.json，
实现「不填 Key、不记模型名」的真正零配置接入。

【为什么换源】
本脚本原先注入 OpenCode Zen。2026-10-13 复测：Zen 的 9 个 -free 模型外部调用
（含 WorkBuddy）全部 403 FreeTierError，原唯一可用节点 space-bunny-free 也已归零，
VERIFIED_OK 因此为空 —— 注入器实际处于「空转」状态：跑完什么也没写进去。
2026-10-30 换源到 Kilo AI Gateway，理由是有实测支撑：

    POST https://api.kilo.ai/api/gateway/v1/chat/completions
    不带任何 Authorization 头，max_tokens=2000
    → 16 个 isFree 模型中 14 个返回 200 且 content 非空（1.0–2.5s），
      2 个返回 429 Provider returned error（限流，非永久失效）

【为什么 max_tokens 必须给足】
Kilo 的 beam-free 等模型带 reasoning，实测 max_tokens=20 时 20 个 token 全被推理
吃掉、content 为空串（finish_reason=length）。给到 2000 才有正文。判断「能不能用」
不能只看 HTTP 200，要看 content 是否非空。

【能力标签口径】
context 取自接口 top_provider.context_length；supportsImages 取自
architecture.input_modalities 含 image；supportsToolCall / supportsReasoning 取自
supported_parameters。这些是上游自报值，非本机逐一验证 —— 已在注释标明。

设计约束（沿用）：
- 只读优先：默认 dry-run，绝不改动文件。
- 幂等：已存在 id 跳过。
- 写入需授权：--apply 交互确认；--yes 跳过确认（需明确）。
- schema 保护：识别 models.json 为数组或 {"models":[...]}；形态未知则中止。
- 绝不臆造配额；能力标签用上游自报值或保守默认。

用法：
    python inject_workbuddy.py                 # dry-run，只看会注入什么
    python inject_workbuddy.py --apply         # 写入（交互确认）
    python inject_workbuddy.py --apply --yes   # 写入（不确认，脚本化场景）
    python inject_workbuddy.py --force         # 连 429 待复测的一起注入
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

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent if HERE.name == "scripts" else HERE
CATALOG = SKILL_ROOT / "references" / "model-catalog.json"

VENDOR = "Kilo AI Gateway"
# ⚠️ 必须是 anonymous。实测鉴权口径（2026-10-22 记录，2026-10-30 复核）：
#   不带 Authorization 头 → 200/429（鉴权通过）
#   Bearer anonymous      → 200/429（鉴权通过）
#   Bearer kilo / public / none / 任意 sk-… → 401 INVALID_TOKEN
# 写成 "kilo" 会让 WorkBuddy 带 Bearer kilo 请求，必然 401 —— 这是换源时踩过的坑。
API_KEY = "anonymous"
ENDPOINT = "https://api.kilo.ai/api/gateway/v1/chat/completions"
MODEL_LIST_URL = "https://api.kilo.ai/api/gateway/v1/models"

# 2026-10-30 逐个体测通过（HTTP 200 且 content 非空）：
# id -> (maxInputTokens, supportsToolCall, supportsImages, supportsReasoning)
VERIFIED_OK: dict[str, tuple[int, bool, bool, bool]] = {
    "kilo-auto/free": (256000, True, False, True),
    "reflection/beam-free": (1048576, True, False, True),
    "nvidia/nemotron-3-ultra-550b-a55b:free": (1000000, True, False, True),
    "nvidia/nemotron-3.5-lightning:free": (1000000, True, False, True),
    "nvidia/nemotron-3.5-super-vl:free": (1000000, True, True, True),
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free": (256000, True, True, True),
    "nvidia/nemotron-3.5-content-safety:free": (128000, False, True, True),
    "dots-studio/dots-3-note-preview:free": (512000, True, True, True),
    "recursive/flint-v1.0:free": (262144, True, False, True),
    "stealth/glyph-cluster": (256000, True, False, True),
    "cohere/north-mini-code:free": (256000, True, False, True),
    "poolside/laguna-s-2.1:free": (262144, True, False, True),
    "liquid/lfm-2.5-2.6b:free": (65536, True, False, True),
    "openrouter/free": (200000, True, True, True),
}

# 2026-10-30 实测 429 Provider returned error（限流，非永久失效）：
# 默认跳过；--force 可注入，但用户可能撞限流。
PENDING_429: dict[str, tuple[int, bool, bool, bool]] = {
    "xingchen-agi/xing4.0-29b-a4b:free": (262144, True, False, True),
    "poolside/laguna-xs-2.1:free": (262144, True, False, True),
}

DEFAULT_CAP = (262144, False, False, False)


def _entry(mid: str, cap: tuple[int, bool, bool, bool]) -> dict:
    ctx, tc, img, rs = cap
    return {
        "id": mid,
        "name": mid,
        "vendor": VENDOR,
        "url": ENDPOINT,
        "apiKey": API_KEY,
        "maxInputTokens": ctx,
        "supportsToolCall": tc,
        "supportsImages": img,
        "supportsReasoning": rs,
    }


def build_entries(force: bool = False):
    entries: list[dict] = []
    for mid, cap in VERIFIED_OK.items():
        entries.append(_entry(mid, cap))
    forced: list[str] = []
    if force:
        for mid, cap in PENDING_429.items():
            entries.append(_entry(mid, cap))
            forced.append(mid)
    return entries, forced


def load_models_json(path: Path):
    if not path.exists():
        return None, "missing"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return None, f"parse-error:{e}"
    if isinstance(data, list):
        return data, "array"
    if isinstance(data, dict) and isinstance(data.get("models"), list):
        return data["models"], "object-models"
    return None, "unknown"


def main() -> None:
    apply_ = "--apply" in sys.argv
    yes = "--yes" in sys.argv
    force = "--force" in sys.argv
    dry = not apply_

    print("[数据来源] Kilo AI Gateway 免注册免 Key 匿名池")
    print(f"[模型清单] {MODEL_LIST_URL}（GET，公开可读）")
    print(f"[对话端点] {ENDPOINT}")
    print("[实测口径] 2026-10-30 逐个 POST，不带任何 Authorization，max_tokens=2000，"
          "以 content 非空为通过")
    print(f"[实测结果] {len(VERIFIED_OK)} 个通过，{len(PENDING_429)} 个 429 待复测"
          f"（共 {len(VERIFIED_OK) + len(PENDING_429)} 个 isFree）")
    print("[能力标签] context / 模态 / tools 取自上游接口自报，非本机逐项验证")

    entries, forced = build_entries(force)
    print(f"\n[将注入] {len(entries)} 个模型：")
    for e in entries:
        flags = []
        if e["supportsImages"]:
            flags.append("视觉")
        if e["supportsReasoning"]:
            flags.append("推理")
        if e["supportsToolCall"]:
            flags.append("工具")
        tag = " / ".join(flags) or "纯文本"
        note = "  [--force，可能限流]" if e["id"] in forced else ""
        print(f"  + {e['id']:<52} ctx={e['maxInputTokens']:>7}  [{tag}]{note}")

    if not force and PENDING_429:
        print(f"\n[跳过] {len(PENDING_429)} 个实测 429（限流，非永久失效），"
              f"加 --force 可一并注入：")
        print("   ", ", ".join(PENDING_429))
    if CATALOG.exists():
        try:
            cat = json.loads(CATALOG.read_text(encoding="utf-8"))
            hit = any(p.get("name") == VENDOR for p in cat.get("providers", []))
            if not hit:
                print(f"[提示] 货架中未见「{VENDOR}」条目，建议先跑 doctor 检查数据完整性")
        except Exception:  # noqa: BLE001
            pass

    if dry:
        print("\n[dry-run] 未做任何改动。加 --apply 实际写入（会再确认一次）。")
        return

    home = Path(os.environ.get("USERPROFILE", os.environ.get("HOME", "~"))).expanduser()
    models_path = home / ".workbuddy" / "models.json"
    existing, shape = load_models_json(models_path)
    if shape == "missing":
        existing, shape = [], "array"
        print(f"\n[apply] 目标不存在，将新建 {models_path}")
    elif shape == "unknown":
        sys.exit(f"[错误] {models_path} 结构无法识别，中止写入以免损坏，请人工检查后重试。")
    else:
        print(f"\n[apply] 目标 {models_path}（形态 {shape}）")

    existing_ids = {m.get("id") for m in existing} if isinstance(existing, list) else set()
    to_add = [e for e in entries if e["id"] not in existing_ids]
    skip = len(entries) - len(to_add)
    print(f"[apply] 新增 {len(to_add)}，跳过已存在 {skip}")
    if not to_add:
        print("[apply] 无新增，结束。")
        return

    if not yes:
        if not sys.stdin.isatty():
            print("[apply] 非交互环境，未确认。请加 --yes 明确同意写入。")
            return
        ans = input("确认写入以上条目到 models.json？(y/N) ").strip().lower()
        if ans != "y":
            print("[apply] 已取消。")
            return

    merged = existing + to_add
    models_path.parent.mkdir(parents=True, exist_ok=True)
    if shape == "object-models":
        raw = json.loads(models_path.read_text(encoding="utf-8")) if models_path.exists() else {}
        raw["models"] = merged
        out = raw
    else:
        out = merged
    models_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] 已写入 {len(to_add)} 个模型 → {models_path}")
    print("[提示] WorkBuddy 不会热加载 models.json，重启客户端后生效。")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    sys.exit(0)
