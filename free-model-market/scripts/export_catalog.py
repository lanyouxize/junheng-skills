#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
免费模型超市 · 货架导出器

把 `免费模型超市-model-catalog.md` 解析为机器可读的
`references/model-catalog.json`，作为「免费模型超市 ⇄ 自由模型市场·网关」
组合产品的外部共享数据源（external shared data source）。

网关侧 `sync_catalog.mjs` 通过 CATALOG_URL 拉取此 JSON，
即可在不读取本 Markdown 的前提下拿到额度/状态/端点的权威值，
满足两个 Skill 独立上架却可相互调用的设计目标。

用法：
    python 免费模型超市-export_catalog.py [货架.md] [输出.json]

默认输入 免费模型超市-model-catalog.md，输出 references/model-catalog.json。
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
import argparse
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# 东八区
TZ = timezone(timedelta(hours=8))

# 语义列 → 表头关键字（按“包含”匹配，避免全角/半角差异）
COLUMN_KEYWORDS = {
    "provider": ("厂商",),
    "endpoint": ("API 端点", "端点"),
    "status": ("状态",),
    "quota": ("免费额度", "额度"),
    "rate_limit": ("限速",),
    "credit_card": ("信用卡",),
    "models": ("免费模型", "模型 / 渠道", "模型"),
    "notes": ("备注",),
    "event": ("事件",),
    "effective_date": ("生效日期",),
}


def clean_url(u: str) -> str | None:
    """截断首个非 ASCII 字符（处理单元格里混进的全角括号/中文）。"""
    for i, ch in enumerate(u):
        if ord(ch) > 0x2000:
            u = u[:i]
            break
    u = u.strip().rstrip(".,;）)>")
    if not u.startswith("http"):
        return None
    return u


# 状态枚举白名单（与网关侧 sync_catalog.mjs 的 TIER_RULES 键对齐）
VALID_STATUS = {"active", "degraded", "unverified", "expired", "unknown"}


def clean_status(raw: str) -> str:
    """规范化状态值：剥离 Markdown 强调标记，输出下游可枚举的裸值。

    表格中常用 `**degraded**` 做视觉强调；直接导出会污染 machine-readable
    JSON，使网关侧 TIER_RULES 命中失败并静默落到 `review` 兜底档
    （2026-10-02 实测：OpenCode Zen 应得 low 却得 review）。
    """
    s = raw.strip().strip("*`_~").strip().lower()
    return s or "unknown"


def clean_md(raw: str) -> str:
    """剥离 Markdown 强调标记（* _ ~），**反引号代码段内原样保留**。

    货架表格为视觉醒目，常在 quota / notes 里写 `**250–14,400 请求/日**`、
    `~~旧值~~` 之类。这些标记对机器消费是脏值：JSON 导出若原样带出，
    下游网关 / recommend / watch 做关键词匹配时会被 `**` 干扰（2026-10-02
    watch 实测：Groq/Mistral/Hetzner/B.AI/Inception 共 5 条 quota 含脏标记）。

    ⚠️ 2026-10-30 修正（真实缺陷）：原实现对整串做 replace("*"/"_"/"~")，
    反引号**字符**虽未被删，但里面的内容照样被剥 —— 于是模型名
    `Meta-Llama-3_3-70B-Instruct` 被导出成 `Meta-Llama-33-70B-Instruct`，
    `Mistral-Small-3.2-24B-Instruct-2506` 之类同理失真，用户照抄必然 404。
    反引号内是代码 / 端点 / 模型 ID，属于**标识符**，必须逐字保留。
    """
    s = raw.strip()
    # 按反引号切分：偶数下标 = 段外（需清洗）；奇数下标 = 反引号内（原样保留）
    parts = s.split("`")
    for i in range(0, len(parts), 2):
        for ch in ("*", "_", "~"):
            parts[i] = parts[i].replace(ch, "")
    return "`".join(parts).strip()


def split_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def is_separator(cells: list[str]) -> bool:
    return all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c != "")


def detect_columns(headers: list[str]) -> dict[str, int]:
    """把表头单元格映射到语义列索引。"""
    mapping: dict[str, int] = {}
    for idx, h in enumerate(headers):
        for sem, kws in COLUMN_KEYWORDS.items():
            if sem in mapping:
                continue
            if any(kw in h for kw in kws):
                mapping[sem] = idx
                break
    return mapping


def parse_catalog(path: Path) -> dict:
    if not path.exists():
        sys.exit(f"[错误] 找不到货架文件: {path}")

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    # 顶层快照日期（警告里的“数据快照日期**：YYYY-MM-DD”）
    snapshot = ""
    m = re.search(r"数据快照日期\**\s*[：:]\s*(\d{4}-\d{2}-\d{2})", text)
    if m:
        snapshot = m.group(1)

    # §五 来源清单的核实日期
    # ⚠️ 2026-10-30 修正：原正则用 `[^\n|）)]+`，遇中文右括号即止 → 只要标题里出现
    # 「（space-bunny-free 归零）」这类嵌套括号，verify_note 就被截断在那一轮，
    # 后续轮次全部丢失。改为只以换行 / 竖线为界，末尾的括号由 strip 处理。
    verify_note = ""
    m = re.search(r"核实日期\**\s*[：:]\s*([^\n|]+)", text)
    if m:
        note = m.group(1).strip()
        # 只剥掉「（核实日期：…）」这一层的外层右括号，内层轮次括号必须保留，
        # 否则末轮说明会变成未闭合的「（…」形态。
        if note.endswith("）") or note.endswith(")"):
            note = note[:-1].rstrip()
        verify_note = note

    providers: list[dict] = []
    current_section = ""
    col_map: dict[str, int] = {}
    in_expired_section = False

    for line in lines:
        heading = re.match(r"^#{2,3}\s+(.*)", line)
        if heading:
            current_section = heading.group(1).strip()
            in_expired_section = "已停服" in current_section or "退出免费层" in current_section
            col_map = {}
            continue

        if not line.strip().startswith("|"):
            continue

        cells = split_row(line)
        if len(cells) < 2:
            continue

        # 表头行：检测列映射
        if any(kw in cells[1] for kws in COLUMN_KEYWORDS.values() for kw in kws) and not is_separator(cells):
            if any(kw in c for c in cells for kw in ("厂商", "端点", "状态", "额度", "事件")):
                col_map = detect_columns(cells)
                continue

        if is_separator(cells):
            continue

        # 数据行
        if not col_map:
            continue
        if "provider" not in col_map:
            continue
        pidx = col_map["provider"]
        if pidx >= len(cells):
            continue
        provider = cells[pidx].strip()
        if not provider or provider in ("厂商",):
            continue

        rec: dict = {
            "name": provider,
            "section": current_section,
        }

        if "endpoint" in col_map and col_map["endpoint"] < len(cells):
            urls = re.findall(r"https?://[^\s`|\)）]+", cells[col_map["endpoint"]])
            rec["endpoints"] = [u for u in (clean_url(x) for x in urls) if u]

        if "status" in col_map and col_map["status"] < len(cells):
            rec["status"] = clean_status(cells[col_map["status"]])
        elif in_expired_section:
            rec["status"] = "expired"

        for sem in ("quota", "rate_limit", "credit_card", "models", "notes", "event", "effective_date"):
            if sem in col_map and col_map[sem] < len(cells):
                val = clean_md(cells[col_map[sem]])
                if val:
                    rec[sem] = val

        providers.append(rec)

    return {
        "schema_version": 1,
        "generated_at": datetime.now(TZ).strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "source": "免费模型超市-model-catalog.md",
        "snapshot_date": snapshot,
        "verify_note": verify_note,
        "provider_count": len(providers),
        "providers": providers,
    }


def resolve_default_paths() -> tuple[Path, Path]:
    """不依赖 cwd 定位货架与输出路径。

    工作区里货架在仓库根目录（中文文件名）、JSON 在 references/；
    发布包里货架在 references/model-catalog.md（英文名）。
    两套布局都要能找到，否则用户装包后直接报错——v1.0.7 及更早只认中文名，
    装包后跑export_catalog.py 必然 rc=1「找不到货架文件」。
    这里按__file__ 向上逐级探测，命中即止；显式命令行参数优先级最高。
    """
    here = Path(__file__).resolve()
    roots = list(here.parents)          # scripts/, 包根, 仓库根, ...
    roots.append(Path.cwd())

    # 工作区形态（中文名，仓库根）
    md_name = "免费模型超市-model-catalog.md"
    # 发布包形态（英文名，references/ 下）
    pkg_rel = Path("references") / "model-catalog.md"
    candidates = [p / md_name for p in roots] + [p / pkg_rel for p in roots]
    in_path = next((c for c in candidates if c.exists()),
                   roots[0] / md_name)   # 兜底：保持旧行为，报错信息仍指向货架名
    out_path = next(
        (p / "references" / "model-catalog.json"
         for p in roots if (p / "references" / "model-catalog.json").exists()),
        in_path.parent / "references" / "model-catalog.json",
    )
    return in_path, out_path


def main() -> None:
    # 🔴 必须走 argparse（2026-10-31 事故）：原先直接读 sys.argv[1]，
    #    跑 `export_catalog.py --help` 会把 "--help" 当输入文件名 → 解析出 0 条
    #    → 再用空数据覆盖 references/model-catalog.json，货架被静默写空。
    ap = argparse.ArgumentParser(
        description="把货架 md 导出为网关可读的 model-catalog.json",
        epilog="不传参数时自动按脚本位置定位货架与输出路径，不依赖当前工作目录。",
    )
    ap.add_argument("in_path", nargs="?", default=None, help="货架 md 路径（默认自动定位）")
    ap.add_argument("out_path", nargs="?", default=None, help="输出 JSON 路径（默认 references/model-catalog.json）")
    ap.add_argument("--allow-empty", action="store_true",
                    help="允许导出空货架（默认拒绝，防止把空数据覆盖到已有货架）")
    args = ap.parse_args()

    default_in, default_out = resolve_default_paths()
    in_path = Path(args.in_path) if args.in_path else default_in
    out_path = Path(args.out_path) if args.out_path else default_out

    # 输入不存在 → 报错且不落盘（绝不用空数据覆盖）
    if not in_path.is_file():
        print(f"[ERR] 货架文件不存在: {in_path}", file=sys.stderr)
        print("[ERR] 未写入任何文件（防止空数据覆盖货架）；如需导出请显式指定货架 md 路径", file=sys.stderr)
        return

    data = parse_catalog(in_path)

    # 解析出 0 条 → 拒绝覆盖已有文件
    if not data.get("providers") and not args.allow_empty:
        print(f"[ERR] 从 {in_path} 解析出 0 条厂商记录（章节锚点缺失或文件格式异常）", file=sys.stderr)
        if out_path.exists():
            print(f"[ERR] 已保留原有 {out_path} 不覆盖；确认要清空请加 --allow-empty", file=sys.stderr)
        return

    # 状态枚举校验：脏值会让网关侧静默落到 review 兜底档，必须在导出时就地暴露
    bad = [
        (p["name"], p["status"])
        for p in data["providers"]
        if p.get("status") not in VALID_STATUS
    ]
    if bad:
        print("[WARN] 以下记录状态值不在枚举白名单内，网关侧将落入 review 兜底档：", file=sys.stderr)
        for name, st in bad:
            print(f"       - {name}: {st!r}", file=sys.stderr)

    payload = json.dumps(data, ensure_ascii=False, indent=2)
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(payload, encoding="utf-8")
        print(f"[OK] 已导出 {data['provider_count']} 条厂商记录 → {out_path}")
    except Exception as e:
        # 只读文件系统 / 权限受限时降级为「只报告不落盘」，不让整轮变成失败
        print(f"[WARN] 目标不可写（{e}），改为只输出结果不落盘", file=sys.stderr)
        sec = {}
        for p in data["providers"]:
            k = (p.get("section") or "未分区").split("、")[0]
            sec[k] = sec.get(k, 0) + 1
        print(f"[OK] 已解析 {data['provider_count']} 条厂商记录（未落盘）| section 分布 {sec}")
        print(payload)


if __name__ == "__main__":
    main()
