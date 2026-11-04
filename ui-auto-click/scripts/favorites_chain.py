#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「赞和收藏」→ 公众号文章批量下载：七步串联驱动器（chain）。

这个脚本解决什么问题
--------------------
用户要的是"一条命令把收藏夹里的文章丢给下载工具"。这条链路横跨两个程序
（微信 PC 4.x + 「微信公众号文章批量下载工具」），中间靠剪贴板和微信内置
浏览器传参，任何一步断开都要人工补，所以必须有人把七步串起来并落台账。

七步与本脚本的对应关系（用户 2026-10-26 原话，顺序不可调）
--------------------------------------------------------
  1 从上到下顺序点「赞和收藏」列表里的文章      ← 本脚本：rows_for + 行指纹去重
  2 点文章页标签栏的「⊙」→ 菜单「复制链接」     ← 本脚本：模板定位 + 点击
  3 链接填进下载工具的「微信文章链接」输入框     ← profiles/wechat_batch_downloader.yaml
  4 点「1.获取公众号id」                        ← 同上
  5 复制工具给出的 profile_ext 链接              ← 同上（open_url 步骤内完成）
  6 用微信标题栏放大镜打开该链接（取密钥）        ← 同上
  7 点「批量下载文章」                          ← 同上

第 3~7 步全部在 profiles/wechat_batch_downloader.yaml 里（含真机校准时序），
本脚本只负责**第 1、2 步 + 编排 + 台账**，3~7 步用 subprocess 调
`clicker.py run --profile wechat_batch_downloader --var ARTICLE_URL=... --yes`。
不重写那套步骤表：真机时序（预热→激活→点 id→open_url→等密钥）是踩坑踩出来的，
复制一份必然分叉。

两个必须靠模板、绝不能硬编码的坑（2026-10-26 真机取证）
----------------------------------------------------
坑 1：「⊙」的 x 坐标随**文章标签标题长度**变化。实测点窗口内 (997,44) 能弹出
      菜单，但那是标题正好那么长时的值；换一篇标题长度不同，⊙ 就跟着搬家。
      所以必须先找 templates/wechat-more.png（30×28，实测 score=1.00），
      模板失配才退回 (997,44) 并打 chain.more_fallback —— 兜底是"这一篇也许
      还能过"，不是"坐标就是 997"。
坑 2：「刷新」菜单项紧邻「复制链接」上方，行高相近。从菜单顶部按固定偏移往下
      数第 N 行，会在菜单项顺序/数量变化时静默点到「刷新」（页面重载，看起来
      "什么都没发生"，最坏情况是把已打开的页面刷掉）。所以「复制链接」一律用
      templates/wechat-copy-link.png（115×30，实测 score=1.00）命中定位。

为什么每轮都重新截图（D1）
-------------------------
点击打开文章后界面已变；复用上一轮截图算出来的坐标会点到别处。每轮迭代
从 `_capture` 开始，几何/命中全部重算。

为什么用行指纹去重（D2）
----------------------
列表不会因为点开文章而消失，同一行还在最上方。只按"最上方一行"取，
--max>1 就会反复点同一篇。指纹（wf.row_fingerprint）+ journal 让"已点过的行"
跨进程也跳过。

为什么只有"整条链路成功"才记 decision=click（D3）
-----------------------------------------------
`wf.processed_fingerprints` 只认 decision=="click"，语义是"这行永远不用再处理"。
所以下载工具失败的那篇必须记成 download_failed（不参与去重），否则下次会被
静默跳过 —— 静默漏采比重复点一次严重得多（重复点还有 journal 与下游幂等兜底，
漏采没有任何人会发现）。同一次运行内不重复点同一篇，由内存里的 session 集合保证。

台账（scripts/ledger.py）
----------------------
只在**文章真下载成功**（clicker 返回码 0 或 5）时调 `ledger.append_record`：
预演 / --skip-download / 下载失败 / 没拿到链接一律不记 —— 台账的语义是"已采集"，
把没下载的东西记进去就和实际产物对不上了（这些情况 journal 里仍有完整记录，
事后可按 journal 补账）。

**账号级去重**：`profile_ext` 在第 27 步（「获取密钥成功」）就已经拿到，那时还一步
都没下载。所以跑下载器要拆成两段（段 A 1..27、段 B 28..33），中间查台账：
若该 `profile_ext` 已有行，就**整段跳过下载**，只把这篇的链接补进已有行的备注
「同号文章」——否则收藏里同一个号的 3 篇会把整号历史下 3 遍（时间 ×3、产物重复
覆盖），而台账仍然只有 1 行（靠 profile_ext 收敛），成本与记录完全对不上。
要强制重下拉一遍用 `--ignore-ledger`。

`account`/`title` 故意留空让 ledger 自己抓文章元信息（单篇 urllib，默认 20s 上限）。
批量跑嫌记账慢时可以不改代码，直接用环境变量把上限调小：
    UIAC_LEDGER_TIMEOUT=8 python scripts/favorites_chain.py --max 20 --yes
`append_record` 只写 CSV，md 是投影 —— 所以这里追加完会再调一次
`export_markdown()`，否则 docs/favorites-ledger.md 会停在旧数据上。
另：rc=5 且没抠到 profile_ext 时会打 `chain.partial_without_profile_url`（而不是普通
的 `chain.profile_url_missing`）—— 5 只表示"有可选步骤失败过"，不代表 id 拿到了，
这个事件名就是给"5 掩盖了 id 失败"那种情况留的抓手；记账仍按成功，不改判失败。

流程里多出来的一步：把微信切回列表页（restore_list）
------------------------------------------------
七步里没有它，但 --max>1 不加会必挂：下载工具的步骤表会用微信标题栏的放大镜
打开 profile_ext 链接，跑完微信停在那个页面上；下一轮第一件事就是截图判页，
于是直接判"不在列表页"退出，表现成"只处理了第一篇"。所以每次调完下载工具都要
先确认还在不在列表页、不在就按一次 Ctrl+W（只按一次，再按可能把列表页本身关掉）。

退出码（沿用仓库既有常量）
------------------------
0 ok / 2 参数错 / 3 执行失败 / 5 部分成功 / 6 环境不具备（没有微信窗口）

用法
----
  python scripts/favorites_chain.py --dry-run --max 1
  python scripts/favorites_chain.py --max 1 --yes
  python scripts/favorites_chain.py --max 3 --yes --skip-download
  python scripts/favorites_chain.py --max 5 --yes --range monthly  # 默认 monthly
  python scripts/favorites_chain.py --max 5 --yes --ignore-ledger  # 强制重下已有号

`--range`（all/monthly）会转成 `--var RANGE=` 传给下载器的步骤表，由 profile 里
两条互斥的「设置时间范围」步骤消费。**默认 monthly＝一个月内**：2026-10-28 真机
实测证明 `--range all`（全部历史）会让下载器引擎在 `起始下载页数：0` 后永久冻结、
0 产物（见 `下载/log20261027.txt`）；而 monthly 正常枚举并下载（44 篇真文章落地、
空壳率 11%）。all 仅在你确认工具已修复大历史枚举冻结、且确实需要全量时才显式传入。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import random
import re
import subprocess
import sys
import time
import win32gui
from datetime import datetime, timezone
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))

import clipboard  # noqa: E402
import clicker  # noqa: E402  （复用其 find_windows 权威匹配器，类名 Mywindow 是稳定标识）
import vision  # noqa: E402
import wechat_favorites as wf  # noqa: E402
import wechat_open_url  # noqa: E402

EXIT_OK, EXIT_PARAM, EXIT_ERROR, EXIT_PARTIAL, EXIT_ENV = 0, 2, 3, 5, 6

# 下载器冷启动后需等几秒把"自动获取密钥"钩子武装好，否则紧接着点「1.获取公众号id」
# 工具毫无反应（日志零新增 → wait_log 超时 rc=3）。用户手工开好的工具已温热不受影响。
TOOL_WARMUP_SETTLE = 8.0
TPL = SKILL / "templates"
OUT = SKILL / "out"
DEFAULT_JOURNAL = "out/favorites-chain-journal.jsonl"
DEFAULT_PROFILE = "wechat_batch_downloader"

# 状态探测 → 下一步 profile 映射（2026-10-28 新增）
# 工具状态由权威日志最新里程碑决定；与总体 33 步流程对比，精准选段：
#   fresh/keying → 完整链（config→取id→取密钥→下载）
#   id_ready     → 跳取密钥+下载段（wechat_key_and_download）
#   keyed        → 跳下载段（wechat_download_only）
#   downloading  → 续等静止（wechat_download_only）
#   done         → 工具空闲，换篇需整段重跑（同号去重交给 ledger，不在此误跳）
_PROFILE_BY_STATE = {
    "fresh": DEFAULT_PROFILE,
    "keying": DEFAULT_PROFILE,
    "id_ready": "wechat_key_and_download",
    "keyed": "wechat_download_only",
    "downloading": "wechat_download_only",
    "done": DEFAULT_PROFILE,
}
_STATE_NEXT = {
    "fresh": "整段重跑：配置→取id→取密钥→下载",
    "keying": "整段重跑：配置→取id→取密钥→下载",
    "id_ready": "跳到取密钥段：微信打开 profile_ext→等密钥→点下载",
    "keyed": "跳到下载段：直接点 2.批量下载文章",
    "downloading": "续等下载结束（wait_stable）",
    "done": "整段重跑：工具已空闲，换篇重新取 id/密钥/下载（同号去重看 ledger）",
}

MORE_TPL = "wechat-more.png"
COPY_TPL = "wechat-copy-link.png"
# 阈值来自真机实测：more 1.00（菜单已开着时降到 0.87，仍 >0.85）、copy-link 1.00。
# 0.85/0.80 是"宁可用兜底/重试也不误点"的折中，别为了一次侥幸调低。
MORE_THRESHOLD = 0.85
COPY_THRESHOLD = 0.80
# 「赞和收藏」标签模板（由 chain_test2 失败截图裁出，score 应≈1.0）；点它从文章页切回列表。
# 0.80 容错：标签在非激活态渲染，亮度/描边可能微变，但「赞和收藏」四字形状稳定。
FAV_TAB_TPL = "wechat_fav_tab.png"
FAV_TAB_THRESHOLD = 0.80
# 坑 1 的兜底值（2026-10-26 实测，标题长度恰好时的坐标）。只在模板失配时用。
MORE_FALLBACK = (997, 44)
# 「×」相对「⊙」中心的水平偏移（2026-10-26 真机两次实测）：
#   文章标签页：⊙ 中心 997 → × 中心 1043（+46，墨迹团块测出）
#   下载完停的 profile_ext 浮窗：⊙ 304 → × 约 355（+51，用户截图，× 区域被红圈
#   标注污染故读数偏大）
# 取 48 落在区间内；真值随 DPI/版本变化，但两者同在 46~53，48 是安全取法。
CLOSE_DX = 48

# 文章链接校验：必须以 https?://mp.weixin.qq.com/s 开头，且 /s 后面还有内容。
# 为什么不用 clipboard.URL_PATTERN：它只校验域名，profile_ext（/mp/profile_ext）
# 也会通过；而这一步的语义是"这篇文章的链接"，多认一类就是多一类误投喂。
ARTICLE_URL_RE = re.compile(r"^https?://mp\.weixin\.qq\.com/s(?:/[^\s/]+|\?[^\s]+)$")


def log(level: str, event: str, **kw) -> None:
    rec = {"ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "level": level, "event": event}
    rec.update(kw)
    print(json.dumps(rec, ensure_ascii=False), file=sys.stderr)


# --------------------------------------------------------- 纯函数（可离线单测）
def is_article_url(url) -> bool:
    """是不是一篇公众号文章的链接（`/s/xxx` 或 `/s?__biz=`）。

    strip 后再判：剪贴板里的链接常带首尾换行，原样匹配会冤判成无效。
    profile_ext（/mp/profile_ext）、裸域名（https://mp.weixin.qq.com/）、
    只有 /s 没有 id 的都不算 —— 后者喂给下载工具只会得到"获取失败"。
    """
    if not isinstance(url, str):
        return False
    return bool(ARTICLE_URL_RE.match(url.strip()))


def extract_profile_url(text: str) -> str:
    """从 clicker 的 stdout/stderr 里抠 profile_ext 链接；抠不到返回空串。

    复用 wechat_open_url.find_url_in_text（它优先挑 profile_ext），但它**在
    没有 profile_ext 时会退而返回最后一个 mp.weixin.qq.com 链接**——那多半是
    文章链接。这里再验一次 profile_ext 关键字：台账里宁可留空，也不许把文章
    链接伪装成公众号主页链接（下游会拿着它去取 cookie，取错了只会一直"获取
    密钥失败"，极难归因）。
    """
    u = wechat_open_url.find_url_in_text(text or "")
    if u and "profile_ext" in u:
        return u
    return ""


def annotate_rows(rows, fp_fn) -> list[dict]:
    """给每行算指纹并按 y1 从上到下排序（返回新 dict，不改调用方数据）。

    排序不能省：detect_rows 天然有序，但校准缓存 out/wx-rows.json 的顺序
    取决于生成时的窗口状态，"最上方"必须以当前几何为准（R1 从上到下）。
    """
    out = []
    for row in sorted(rows, key=lambda r: int(r.get("y1") or 0)):
        item = dict(row)
        item["fp"] = fp_fn(row)
        out.append(item)
    return out


def pick_next_row(rows, processed) -> dict | None:
    """取最上方一个未处理行；全部处理过返回 None。

    `rows` 应来自 annotate_rows（已带 fp、已排序）；这里再排一次是防御性的，
    代价是一次 O(n log n) 的排序，n ≤ 十几行。
    """
    for row in sorted(rows, key=lambda r: int(r.get("y1") or 0)):
        if row.get("fp") and row["fp"] in processed:
            continue
        if not row.get("fp"):
            continue        # 算不出指纹的行无法保证不重复点，宁可不点
        return row
    return None


def count_processed(rows, processed) -> int:
    """本画面里有多少行是"已处理"的（只用于汇总与告警文案）。"""
    return sum(1 for r in rows if r.get("fp") and r["fp"] in processed)


def validate_args(args) -> tuple[int, str]:
    """参数校验，返回 (退出码, 说明)。非 0 即应直接退出。

    `--yes` 是真执行闸门：这条链路会点开文章、还会让下载工具真的开始下载，
    不带 --yes 一律拒绝（与 clicker.py 同一约定）。
    """
    if int(args.max) < 1:
        return EXIT_PARAM, "--max 必须 ≥1"
    if not args.dry_run and not args.yes:
        return EXIT_PARAM, ("真执行必须带 --yes（--dry-run 不需要）：本流程会点开文章并"
                           "调用下载工具真的开始下载")
    return EXIT_OK, ""


def decode_output(raw) -> str:
    """把子进程输出解成文本：先 utf-8，再 gbk，最后带替换字符兜底。

    为什么要兜：clicker 的中文日志走 Windows 控制台编码（cp936），但我们给
    子进程设了 PYTHONIOENCODING=utf-8。两种都可能出现（用户手动跑过、或将来
    有人去掉那个 env），解不干净会把 profile_ext 前后的日志变成乱码，排查时
    读不懂"到底哪一步失败了"。
    """
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "replace")


def append_ledger(record: dict, mod=None) -> bool:
    """台账落盘；ledger 缺失或抛异常时只告警并返回 False，绝不让主流程失败。

    为什么容错到这个程度：ledger.py 与本脚本是并行开发的（不同人），它可能
    还没落盘、也可能因为字段口径变化而抛错。台账是"记录"，不是"产出"——
    为了一条记录把已经拿到的文章链接和下载结果丢掉，是本末倒置。
    """
    if mod is None:
        try:
            import ledger as mod  # noqa: F811  (延迟导入：文件可能尚不存在)
        except Exception as exc:
            log("warn", "chain.ledger_missing",
                err="%s: %s" % (type(exc).__name__, exc),
                hint="台账模块不可用，本次跳过落盘（不影响下载与 journal）")
            return False
    try:
        mod.append_record(record)
    except Exception as exc:
        log("warn", "chain.ledger_failed", err="%s: %s" % (type(exc).__name__, exc),
            hint="台账写入失败，本次跳过（journal 里仍有完整记录）")
        return False
    # 顺手刷新人可读的 md（ledger 的 add 子命令也这么做）。不刷会让 docs 里那张
    # 表格停在旧数据上，而 CSV 已经变了——两份"同一数据源"的呈现互相打脸。
    exporter = getattr(mod, "export_markdown", None)
    if callable(exporter):
        try:
            exporter()
        except Exception as exc:
            log("warn", "chain.ledger_export_failed",
                err="%s: %s" % (type(exc).__name__, exc),
                hint="CSV 已写入，只是 md 视图没刷新；可手动跑 "
                     "python scripts/ledger.py export")
    return True


def append_journal(path: Path, rec: dict) -> None:
    """追加一行 journal（jsonl）。ensure_ascii=False：中文要能直接看懂。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def account_already_collected(profile_url: str, mod=None) -> tuple[bool, int]:
    """台账里是否已有这个 `profile_ext` 的行；返回 (是否命中, 行序号)。

    为什么要它（账本级去重的成本问题）：收藏列表里同一个号常有 3 篇文章，
    按行指纹去重只认"这一行没点过"，于是会让下载器**整号全历史下载 3 次**
    —— 台账靠 profile_ext 收敛成 1 行（正确），但真机时间是 3 倍、产物重复覆盖。
    而 `profile_ext` 在「1.获取公众号id」之后就拿到了，**不需要下载完就知道**，
    所以这一步能把"重复整号下载"提前拦掉，成本几乎为零。

    台账读不到（模块缺失 / 文件损坏 / 字段异常）一律返回 (False, 0) 并告警：
    判重失败必须**退化成照常下载**，不能因为台账坏了就整批停摆——"多下一次"
    只是浪费，而"因为台账读不出就一篇文章都不处理"是让用户彻底没法干活。
    """
    if not profile_url:
        return False, 0
    if mod is None:
        try:
            import ledger as mod  # noqa: F811  (延迟导入：文件可能不存在)
        except Exception as exc:
            log("warn", "chain.ledger_missing_dedup",
                err="%s: %s" % (type(exc).__name__, exc),
                hint="台账不可用 ⇒ 无法做账号级去重，本次照常下载（只是可能重复下载同一号）")
            return False, 0
    try:
        rows = mod.load()
    except Exception as exc:
        log("warn", "chain.ledger_unreadable",
            err="%s: %s" % (type(exc).__name__, exc),
            hint="台账读取失败 ⇒ 跳过账号级去重，本次照常下载")
        return False, 0
    want = profile_url.strip()
    for row in rows or []:
        if str(row.get("profile_ext网址") or row.get("profile_url") or "").strip() == want:
            try:
                seq = int(row.get("序号") or 0)
            except Exception:
                seq = 0
            return True, seq
    return False, 0


# 没抠到 profile_ext 时的两条告警文案（按返回码分岔，见 id_missing_event）
_ID_MISSING_HINT = ("clicker 输出里没有 profile_ext 链接（可能日志格式变了）；"
                    "台账该字段留空，不影响本次下载")
_PARTIAL_NO_ID_HINT = ("rc=5 只说明有 optional 步骤失败过，本机常态是「导出HTML文件」"
                       "勾选框恒禁用（profile 里标了 optional）。但这次连 profile_ext "
                       "都没拿到，说明失败的可能不止那一步 —— 台账会安全降级为按文章"
                       "链接去重，「同号收敛」静默失效。")


def id_missing_event(rc: int, profile_url: str) -> tuple[str | None, str]:
    """拿不到 profile_ext 时报哪个事件、给什么提示：返回 (event|None, hint)。

    `event` 为 None 表示不该告警（profile_url 拿到了，没什么可说的）。
    按返回码分岔的理由：rc=5 只证明"有可选步骤失败过"，**不能证明 id 拿到**。
    今天唯一标 optional 的是「勾选导出HTML文件」（本机恒禁用），5 因此无害；
    但 rc=5 且连 profile_ext 都没有，说明失败的可能不止那一步，而链路上
    一切"看起来正常"——单独一个事件名，就是为了让这种情况 grep 得到。
    """
    if profile_url:
        return None, ""
    if rc == EXIT_PARTIAL:
        return "chain.partial_without_profile_url", _PARTIAL_NO_ID_HINT
    return "chain.profile_url_missing", _ID_MISSING_HINT


# --------------------------------------------------------------- 模板与点击
_NEEDLE_CACHE: dict[str, object] = {}


def _needle(name: str):
    """按需加载模板图（缓存：一篇文章要匹配 2~3 次，别每次重读磁盘）。"""
    img = _NEEDLE_CACHE.get(name)
    if img is None:
        img = vision.Image.open(str(TPL / name))
        _NEEDLE_CACHE[name] = img
    return img


def more_point(img) -> tuple[int, int, bool]:
    """在文章页截图上定位「⊙」中心，返回 (窗口内 x, y, 是否用了兜底)。

    坑 1：x 随标签标题长度变，所以模板优先、常数兜底。多命中时取最高分并在
    调用方记一条候选数日志 —— 多个文章 tab 同时开着时，"哪个 ⊙ 是当前页"
    模板本身回答不了，只能留证据让人一眼看出选错了。
    """
    hits = vision.match_template(img, _needle(MORE_TPL), MORE_THRESHOLD, max_n=5)
    if hits:
        m = hits[0]
        return m.x + m.w // 2, m.y + m.h // 2, False
    return MORE_FALLBACK[0], MORE_FALLBACK[1], True


def find_copy_link(hwnd) -> tuple[vision.Match, tuple] | None:
    """重新截图并找「复制链接」菜单项，返回 (Match, rect)；找不到返回 None。

    坑 2：绝不用"从菜单顶部往下数第 N 行"。菜单项顺序/数量会变，「复制链接」
    上方紧邻「刷新」，数错了点到的就是刷新（页面重载，看起来什么都没发生）。
    返回 rect 是因为坐标必须用**本张截图**的窗口原点换算，而不是点击 ⊙ 时那张。
    """
    got = wf._capture(hwnd)
    if not got:
        return None
    img, rect = got
    hits = vision.match_template(img, _needle(COPY_TPL), COPY_THRESHOLD, max_n=3)
    if not hits:
        return None
    return hits[0], rect


def assert_point_belongs(x: int, y: int, hwnd: int, what: str = "微信窗口") -> None:
    """断言屏幕坐标 (x,y) 上的顶层窗口就是 hwnd，否则抛 RuntimeError（fail-closed）。

    为什么必须查（2026-10-26 真机事故）：鼠标点击是**发给屏幕坐标**的，跟调用方
    想点谁毫无关系。当时「微信公众号文章批量下载工具」被 `Wise Care 365` 完全盖住，
    脚本按 UIA 算出的坐标点下去，三次点击全部落进了那个系统清理工具，日志却照样
    写"已鼠标点击"——假成功。collect 这条链路也一样：微信被盖住时，点列表行/⊙/
    「复制链接」会落到别的程序上，后果不可控。
    查不到（window_at_point 返回 None）同样按失败处理：无法证明安全就不许点，
    不要把它当成"没窗口所以随便点"。
    """
    hit = vision.window_at_point(x, y)
    if hit and int(hit["hwnd"]) == int(hwnd):
        return
    # 同进程放行（2026-10-26 真机）：微信 4.x 把文章内容渲染成**独立的顶层窗口**
    # ——同 pid、同 Chrome_WidgetWin_0 类名，但 hwnd 不同且标题常为空。只比对 hwnd
    # 会把"点进微信自己的另一个窗口"误判成"点进别的程序"，真跑时在 ⊙ 那一步
    # 直接中断（落点 hwnd=50200772 / pid=14024，与微信主窗口同进程）。
    # 同 pid 即视同同一应用：点击仍然落在微信里，不是点进别的程序。
    if hit:
        own_pid = vision.window_pid(hwnd)
        if own_pid and int(hit.get("pid") or 0) == own_pid:
            log("info", "chain.point_same_process",
                xy=[int(x), int(y)], hit_hwnd=hit["hwnd"], hit_title=hit["title"],
                hit_cls=hit.get("cls", ""), pid=own_pid, target_hwnd=int(hwnd),
                hint="落点属于同一进程的另一个窗口 —— 微信 4.x 会把文章渲染成独立"
                     "顶层窗口，同进程视同同一应用，放行")
            return
    actual = ("%r(cls=%s) hwnd=%s pid=%s" % (hit["title"], hit.get("cls", ""),
                                             hit["hwnd"], hit.get("pid"))
              if hit else "无法查询（WindowFromPoint 返回空）")
    raise RuntimeError(
        "拒绝点击：(%d,%d) 的落点归属 %s，不是%s hwnd=%s pid=%s —— 目标窗口被其他"
        "进程遮挡，点下去会落到别的程序里。请把微信露出屏幕可见区域后重跑"
        % (int(x), int(y), actual, what, int(hwnd), vision.window_pid(hwnd)))


def _click_abs(hwnd: int, rect, x: int, y: int, jitter: int = 4) -> bool:
    """窗口内坐标 → 屏幕绝对坐标后点击（点击前校验落点归属）。

    归属校验放在**抖动之后**：真正按下鼠标的是抖动后的坐标，校验原坐标等于放过
    了 ±jitter 那几像素——而"贴着窗口边缘的控件"恰好就是被遮挡时最先越界的地方。
    """
    sx, sy = wf._jitter_xy(rect[0] + int(x), rect[1] + int(y), jitter)
    assert_point_belongs(sx, sy, hwnd)
    # 校验先于限流/节奏等待：一次注定被拒绝的点击不该占用写动作配额
    wf._before_write()
    wf._write_gap()
    return vision.click_at(sx, sy)


def _menu_wait() -> None:
    """点开菜单后等它渲染完：0.8~1.2s 随机。

    固定延时是最明显的机器特征之一；而且菜单是 CEF 画的，弹出有帧延迟，
    给一个区间比给一个常数更稳。
    """
    wf._nap(random.uniform(0.8, 1.2))


def _clip_seq() -> int:
    """剪贴板**写入序号**（user32.GetClipboardSequenceNumber）：每写一次就 +1。

    为什么需要它（2026-10-26 真机抓到）：只看"内容变没变"会把"重采同一篇"
    误判成"复制没生效"——点击前剪贴板里已经是这篇的链接时，WeChat 写进去的
    是同一个字符串，内容前后一致，可它**确实被重写过**。序号与内容无关，是
    "有没有人写过"的唯一可靠信号。
    失败返回 -1：此时退回老判据（只看内容），绝不因为读不到序号就放行。
    """
    try:
        import ctypes
        return int(ctypes.windll.user32.GetClipboardSequenceNumber())
    except Exception:
        return -1


def read_copied_url(text_before: str | None, seq_before: int, seq_after: int,
                    text: str | None) -> tuple[str | None, str]:
    """判定这次「复制链接」到底写没写进剪贴板：返回 (url|None, verdict)。

    verdict：
      ok        内容变了且是合法文章链接（兜底分支，正常路径走这里）
      rewritten 内容与点击前相同，但**写入序号变了**且内容是合法链接（主分支）
      unchanged 内容相同且序号没变 —— 就是没复制成功
      bad       内容不是合法文章链接（含"序号变了但写进来的是空/非链接"）

    判据是**两个分支取「或」**，任一成立即接受（别只看到主分支就以为兜底被删了）：
      主分支    seq_after != seq_before  且 内容是合法文章链接
      兜底分支  内容 != 点击前的内容      且 内容是合法文章链接
    兜底分支存在的理由：序号 API 不可用（返回 -1）或被别的进程的剪贴板写入干扰时，
    "内容变了"依然是最朴素也最可信的证据；主分支存在的理由：重采同一篇时内容不会变，
    但序号会变，只有序号能证明"它真的被重写过"。
    两支都不成立才 fail-closed —— 两种失败各报各的原因。

    为什么 `rewritten` 可以放行（这不是把护栏放松了）：序号变了就证明
    **有人重写过剪贴板**，而这一步唯一的写入者是 WeChat 的「复制链接」，它写的
    一定是**当前打开的那篇文章**。所以「序号变 + 合法链接」⇒ 就是这一篇。
    护栏原本要防的是"复制其实没生效、剪贴板里还留着**上一篇**的链接"——那种
    情况下没人写剪贴板，**序号根本不会变**，仍然落到 unchanged 被判失败。
    """
    now = (text or "").strip()
    before = (text_before or "").strip()
    if not is_article_url(now):
        return None, "bad"          # 序号变了但内容非法，也不能收（两支都要求合法链接）
    if now != before:               # 兜底分支
        return now, "ok"
    rewritten = (seq_before >= 0 and seq_after >= 0 and seq_after != seq_before)
    if rewritten:                   # 主分支
        return now, "rewritten"
    return None, "unchanged"


# -------------------------------------------------------- 第 2 步：拿文章链接
def copy_article_link(hwnd, clip_timeout: float = 3.0) -> tuple[str | None, dict]:
    """「⊙」→「复制链接」→ 读剪贴板，返回 (文章链接|None, 证据信息)。

    菜单没弹出来是本步最常见的失败（点击落空 / CEF 还没画完），所以命中不到
    「复制链接」时判据是"菜单没开"而不是"这一步没救了"：Escape 收一次，
    重新定位 ⊙ 再来一遍。两次都不行才算失败 —— 不无限重试，避免反复点同一个
    位置被风控画像。
    """
    info: dict = {"more": None, "copy": None, "more_fallback": False,
                  "attempts": 0, "reason": ""}
    # 点击前取旧快照：只认"点完之后变了的值"，否则读到的是上一篇留下的链接
    old = clipboard.snapshot()
    for attempt in range(2):
        got = wf._capture(hwnd)
        if not got:
            info["reason"] = "capture_failed"
            return None, info
        img, rect = got
        mx, my, fallback = more_point(img)
        info.update(more=[mx, my], more_fallback=fallback)
        if fallback:
            # 模板失配是"这一篇可能还能过"的兜底信号，必须留痕：连续多次出现
            # 说明模板已过期（微信改版/DPI 变化），该重跑 capture_templates.py
            log("warn", "chain.more_fallback", xy=[mx, my],
                hint="wechat-more.png 未命中（阈值 %s），退回实测兜底坐标；"
                     "若持续出现请重跑 scripts/capture_templates.py" % MORE_THRESHOLD)
        if not _click_abs(hwnd, rect, mx, my, jitter=3):
            info["reason"] = "more_click_failed"
            return None, info
        _menu_wait()

        found = find_copy_link(hwnd)
        if not found:
            info["reason"] = "copy_menu_missing"
            log("warn", "chain.copy_menu_missing", attempt=attempt,
                more_xy=[mx, my],
                hint="菜单里没找到「复制链接」：多半是菜单没弹出来。先 Escape "
                     "收起，再重新点一次「⊙」")
            vision.key_tap(vision._VK_ESCAPE)
            wf._nap(0.4)
            continue

        match, rect2 = found
        info["copy"] = [match.x + match.w // 2, match.y + match.h // 2]
        info["copy_score"] = match.score
        info["attempts"] = attempt + 1
        # 序号与文本都在**点「复制链接」之前**取：判据要比较的是"这一次点击有没有
        # 让剪贴板被重写"，取早了会把别的原因造成的写入算进来。
        seq_before = _clip_seq()
        text_before = clipboard.read_text()
        if not _click_abs(hwnd, rect2, *info["copy"], jitter=3):
            info["reason"] = "copy_click_failed"
            return None, info
        # 「复制链接」→ 剪贴板写入不是同步的（CEF 走 IPC），等一小段再读
        wf._nap(0.8)
        # wait_for_url 同时管两件事：轮询等新值（≠old）+ 正则校验。
        # 用严格的文章链接正则，profile_ext / 首页链接一律不收。
        url = clipboard.wait_for_url(timeout=clip_timeout, poll=0.25,
                                     old=old, pattern=ARTICLE_URL_RE)
        if url:
            info["reason"] = "ok"
            return url, info
        raw = clipboard.read_text()
        # 内容没变：靠写入序号区分"重采同一篇"和"复制没生效"（见 read_copied_url）
        seq_after = _clip_seq()
        got_url, verdict = read_copied_url(text_before, seq_before, seq_after, raw)
        info["clipboard_sample"] = (raw or "")[:120]
        info["clip_seq"] = [seq_before, seq_after]
        info["verdict"] = verdict      # 判据结论进证据链，便于事后核对是哪个分支放行
        if verdict == "rewritten":
            info["reason"] = "rewritten_same_text"
            # warn 而不是 info：内容相同说明这篇之前已经复制过（用户手工复制过、
            # 或重跑同一篇），属正常但值得留痕，便于解释"为什么没读到新值"。
            log("warn", "chain.clipboard_rewritten_same_text", verdict=verdict,
                seq=[seq_before, seq_after],
                text_before=text_before, text_after=raw,
                hint="剪贴板内容与点击前相同，但写入序号变了 —— 说明「复制链接」确实"
                     "重写了剪贴板（重采同一篇），按成功处理")
            return got_url, info
        if verdict == "unchanged":
            info["reason"] = "clipboard_unchanged"
            log("error", "chain.clipboard_unchanged", verdict=verdict,
                sample=info["clipboard_sample"], seq=[seq_before, seq_after],
                hint="剪贴板内容与点击前相同，且写入序号没变 —— 这次「复制链接」没生效"
                     "（可能点到了相邻菜单项）。为免下载错文章判失败")
            return None, info
        info["reason"] = "bad_clipboard"
        log("error", "chain.bad_clipboard", verdict=verdict,
            sample=info["clipboard_sample"], seq=[seq_before, seq_after],
            hint="剪贴板里不是文章链接（序号变了也一样不收）。常见原因：点到了"
                 "「刷新」/「用浏览器打开」等相邻菜单项，或复制的是 profile_ext 链接")
        return None, info
    return None, info


# ------------------------------------------------------- 第 3~7 步：下载工具
# 一次 clicker 全量调用跑完步骤表（1..33 步），不再分段。
# 历史教训（真机证伪）：曾把"取密钥(1..27)"与"批量下载(28..33)"拆成两个独立
# clicker 子进程，想在中间插账号级判重；但子进程不共享密钥/会话 ⇒ 段B 新进程无
# 密钥卡在起始页 0 永冻、0 产物，且当日累计日志让段B 一进来就"命中"段A 旧行误判
# 成功。故改回单次全量调用（对齐已验证的受控实验路径），账号级去重后移到"下载
# 完成后查 ledger"（见主循环），不再靠拆段预判。
def run_downloader(article_url: str, index: int, profile: str = DEFAULT_PROFILE,
                   range_key: str = "monthly", from_step: int = 1, max_steps: int = 0,
                   tag: str = "", force_full: bool = False) -> tuple[int, str, str]:
    """调 clicker 跑下载器步骤表，返回 (返回码, 输出全文, profile_ext 链接)。

    为什么用子进程而不是 import clicker 调函数：步骤表执行有跨步骤上下文
    （warmup → activate → 点 id → open_url → 等密钥），clicker 的 main 已经
    处理好了退出码与日志；在进程内复刻一遍等于维护第二套实现。
    stdout/stderr 落盘到 out/chain-clicker-<序号><tag>.log，失败时才有原始证据可查。

    默认 from_step=1 / max_steps=0 表示整表一次跑完。本脚本主循环已改为单次全量
    调用（不再分段）；这两个参数保留，仅供手动调试按步推进时使用。

    状态探测前置（2026-10-28 新增）：先读工具权威日志判定当前进度，与总体 33 步
    流程对比，精准选择下一步该跑的 profile —— 避免「已 keyed」态盲目从步骤1 重跑
    导致 wait_log 超时 rc=3（真机已证伪）。done 态映射回完整 profile（换篇需整段
    重跑，同号去重交给 ledger，不在此误跳）。
    """
    # —— 状态探测：决定下一步跑哪段 ——
    st = clicker.probe_downloader_state()
    # 主循环每轮都现开一篇新文章：工具日志里的 "keyed" 态是上一篇文章取的密钥，
    # 跨文章复用旧密钥会让工具报「起始下载页数：0」、实际 0 文件（chain_run1 实证）。
    # 故 force_full（仅主循环置 True）强制走完整取密钥流程，对【当前打开的这篇】
    # 重新取 id/密钥，绝不复用旧密钥。
    if force_full:
        chosen = DEFAULT_PROFILE
    else:
        chosen = _PROFILE_BY_STATE.get(st["state"], DEFAULT_PROFILE)
    log("info", "chain.state_probe",
        detected_state=st["state"], raw_state=st.get("raw_state"),
        last_marker=st.get("last_marker"), overall_total_steps=33,
        chosen_profile=chosen, next_action=_STATE_NEXT.get(st["state"], "整段重跑"),
        log_file=st.get("log_file"))
    profile = chosen
    cmd = [sys.executable, "scripts/clicker.py", "run",
           "--profile", profile, "--var", "ARTICLE_URL=" + article_url,
           # 时间范围交给 profile 的两条互斥步骤二选一。默认 monthly（一个月内）：
           # 真机实测 all（全部历史）会让下载器引擎在起始页 0 永久冻结、0 产物，
           # 故默认走 monthly；需全量且工具已修复冻结时才显式传 all。
           "--var", "RANGE=" + range_key, "--yes"]
    # from_step/max_steps 仅对完整链有意义（其余 profile 是短流程，整段跑完）
    if profile == DEFAULT_PROFILE:
        if from_step and int(from_step) > 1:
            cmd += ["--from-step", str(int(from_step))]
        if max_steps and int(max_steps) > 0:
            cmd += ["--max-steps", str(int(max_steps))]
    log_path = OUT / ("chain-clicker-%02d%s.log" % (index, tag))
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"   # 子进程日志固定 utf-8，避免半个文件乱码
    log("info", "chain.clicker_start", index=index, cmd=cmd[1:], log=str(log_path))
    try:
        proc = subprocess.run(cmd, cwd=str(SKILL), capture_output=True, env=env)
    except Exception as exc:
        log("error", "chain.clicker_spawn_failed",
            err="%s: %s" % (type(exc).__name__, exc))
        return EXIT_ERROR, "", ""
    out, err = decode_output(proc.stdout), decode_output(proc.stderr)
    text = out + ("\n" + err if out and err else err)
    try:
        log_path.write_text(text, encoding="utf-8")
    except Exception as exc:
        log("warn", "chain.clicker_log_failed",
            path=str(log_path), err="%s: %s" % (type(exc).__name__, exc))
    return proc.returncode, text, extract_profile_url(text)





# ------------------------------------------------------------------ 主流程
def _cached_row_width() -> int:
    """校准缓存里的窗口宽度（0=没有缓存）。用于"0 行"时的可照做提示。"""
    try:
        data = json.loads((OUT / "wx-rows.json").read_text(encoding="utf-8"))
        return int(data.get("w") or 0)
    except Exception:
        return 0


def restore_via_fav_tab(hwnd, back_timeout: float = 8.0) -> bool:
    """点顶部「赞和收藏」标签，从文章/profile_ext 页切回列表页；成功返回 True。

    为什么用这个而不是 Ctrl+W（见 restore_list 主路）：Ctrl+W 是发给**前台窗口**的键，
    批量下载后下载器(Mywindow)常挡在前面，activate_window 未必抢到前台，Ctrl+W 就落空——
    chain_test2 实证：文章标签始终没关掉、restore_list 失败。鼠标点标签走绝对坐标、**不依赖
    前台焦点**，且经 _click_abs 的 assert_point_belongs 校验落点确在微信内（防点到下载器）。
    该标签只在"打开了文章"时出现，列表页本身没有 → 匹配不到就说明已不在文章页或页面异常，
    交给后续兜底/人工，不强行点。
    """
    # 先置前微信，避免下载器遮挡导致截图/点击落在别的窗口
    vision.activate_window(hwnd)
    time.sleep(0.3)
    got = wf._capture(hwnd)
    if not got:
        return False
    img, rect = got
    if wf.page_state(img)["ok"]:
        return True
    hits = vision.match_template(img, _needle(FAV_TAB_TPL), FAV_TAB_THRESHOLD, max_n=3)
    if not hits:
        return False
    m = hits[0]
    cx, cy = m.x + m.w // 2, m.y + m.h // 2
    try:
        _click_abs(hwnd, rect, cx, cy)
    except RuntimeError as exc:
        log("warn", "chain.restore_favtab_refused", err=str(exc),
            hint="点「赞和收藏」标签被落点护栏拒绝（微信被遮挡），保持现状等人工处理")
        return False
    if vision.wait_until(wf._page_pred(hwnd, True), timeout=back_timeout, poll=0.25):
        log("info", "chain.restore_ok", method="fav_tab", at=[rect[0] + cx, rect[1] + cy])
        return True
    return False


def restore_list(hwnd, back_timeout: float = 8.0) -> bool:
    """把微信切回「赞和收藏」列表页；成功返回 True。

    为什么必须有这一步（原七步流程没提，但 --max>1 不加上必挂）：
    下载工具的步骤表会用微信标题栏的放大镜打开 profile_ext 链接，跑完之后
    微信停在那个页面上。下一轮第一件事就是截图判页，于是直接判"不在列表页"
    退出 —— 表现成"只处理了第一篇"，极易被误读成第一篇失败。
    做法：先看当前是不是列表页（工具没换页时什么都不做，避免白按一次
    Ctrl+W）；不是才按一次 Ctrl+W 关掉工具打开的那个标签页。**只按一次**：
    再按就可能把列表页本身关掉，那种损失比"这一轮失败"大得多。
    """
    got = wf._capture(hwnd)
    if got and wf.page_state(got[0])["ok"]:
        return True
    log("info", "chain.restore_list", hint="下载工具跑完通常会停在 profile_ext 页，"
                                           "按一次 Ctrl+W 把它关掉")
    # Ctrl+W 是"发给焦点窗口"的按键，不是发给微信的。实测 15:47 那次失败就是
    # 因为焦点不在微信上（前台是 WorkBuddy），键被别的程序吃掉了。所以先把窗口
    # 提到最前，再按键——不置前就按，等于对着空气按。
    vision.activate_window(hwnd)
    time.sleep(0.3)
    vision.close_tab()
    if vision.wait_until(wf._page_pred(hwnd, True), timeout=back_timeout, poll=0.25):
        log("info", "chain.restore_ok", method="ctrl+w")
        return True

    # 主路②：直接点顶部「赞和收藏」标签切回列表（比 Ctrl+W 更稳，不依赖前台焦点；
    # chain_test2 实证 Ctrl+W 因下载器抢前台而落空，点标签走绝对坐标可破）。
    if restore_via_fav_tab(hwnd, back_timeout):
        return True

    # 备路：直接点标签页上的「×」。下载完停在 profile_ext 页时那个页面顶部是
    # 「favicon 标题 …… ⊙ ×」，× 紧贴 ⊙ 右侧。用 ⊙ 模板锚定再平移，不猜绝对坐标
    # ——⊙ 的 x 随标题长度变，绝对坐标必然漂。
    snap = wf._capture(hwnd)
    if snap:
        img, rect = snap
        mx, my, _fb = more_point(img)
        # 两次实测的 ⊙→× 间距：文章标签页 997→1043（+46）；用户截图的
        # profile_ext 浮窗 304→357（+53，含红圈标注误差）。取 48 落在两者之间。
        tx, ty = mx + CLOSE_DX, my
        try:
            _click_abs(hwnd, rect, tx, ty)
            if vision.wait_until(wf._page_pred(hwnd, True),
                                 timeout=back_timeout, poll=0.25):
                log("info", "chain.restore_ok", method="click_close",
                    at=[rect[0] + tx, rect[1] + ty])
                return True
        except RuntimeError as exc:
            log("warn", "chain.restore_close_refused", err=str(exc),
                hint="点 × 被落点护栏拒绝（微信被遮挡），保持现状等人工处理")

    snap = wf._capture(hwnd)
    evidence = None
    if snap:
        evidence = vision.save(snap[0], OUT / "chain-restore-list-failed.png")
    log("warn", "chain.restore_list_failed", back_timeout=back_timeout,
        evidence=str(evidence) if evidence else "",
        hint="Ctrl+W 与点「×」都没能回到列表页。下一轮会以 chain.lost_page 明确报出；"
             "请人工切回「赞和收藏」后重跑（已成功的文章按指纹记录，不会重复下载）")
    return False


# ------------------------------------------------------------------ 工具窗口生命周期
# 用户的固定 SOP（2026-10-28 指定）：每完成一次批量下载，就点下载工具窗口右上角 ×
# 把它关掉，再双击桌面「微信公众号批量…」（实为桌面上的 .exe）重新打开，作为下一篇
# 的干净起点。自动化必须复刻这段，否则工具累积状态（链接框残留旧 URL、前面步骤把窗口
# 挪动过等）会污染下一篇的下载。
#
# 只针对类名为 Mywindow 的下载工具窗口，绝不碰微信等其他程序。

def _find_tool_hwnd():
    """找下载工具窗口句柄；优先用 clicker 的权威匹配器（类名 Mywindow 是稳定标识，
    标题在「公众号…下载工具」与「wechatdownload」之间跳变时仍可靠）。"""
    wins = clicker.find_windows(r".*公众号.*下载工具.*", ["Mywindow"])
    return int(wins[0]["handle"]) if wins else None


def _desktop_tool_launcher():
    """桌面「微信公众号批量…」启动项路径（用户口中的"快捷方式"，实为 .exe）。

    优先匹配真正快捷方式 .lnk（尊重其工作目录/运行方式），其次退回同名 .exe。
    找不到返回 None。
    """
    desk = os.path.expanduser("~/Desktop")
    for ext in (".lnk", ".exe", ".bat", ".cmd"):
        cands = sorted(glob.glob(os.path.join(desk, "微信公众号批量*" + ext)))
        if cands:
            return cands[0]
    return None


# 下载工具是否由本脚本**冷拉起**（而非用户手工打开的温热态）。钩子只在启动瞬间且
# 当时微信内置浏览器打开时挂载；冷拉起后钩子几乎必然缺失，点「获取公众号id」零反应。
# 主循环据此跳过下载并提示用户手工开温热工具。warm-return 分支不复位它。
TOOL_COLD_STARTED = False


def ensure_tool_open(timeout: float = 20.0):
    """确保下载工具已打开；没开就双击桌面启动项启动，等到窗口出现。

    返回工具 hwnd；起不来返回 None（调用方据此让本轮下载失败，而不是卡死）。
    首轮（r=0）工具本来就是开着的，这里直接返回现有句柄，不会重复启动。
    """
    global TOOL_COLD_STARTED
    hwnd = _find_tool_hwnd()
    if hwnd:
        # 工具已开着：可能是用户手工打开的温热态（期望），也可能是上次冷拉起残留。
        # 不在本分支复位 TOOL_COLD_STARTED，避免把"冷拉起残留"误当温热。
        return hwnd
    path = _desktop_tool_launcher()
    if not path:
        log("error", "chain.tool_launcher_missing",
            hint="找不到桌面 微信公众号批量*（.lnk/.exe），无法自动重开下载工具；"
                 "请确认启动项存在且命名以「微信公众号批量」开头")
        return None
    log("info", "chain.tool_opening", launcher=path,
        hint="下载工具未运行，双击桌面启动项启动（等价于用户手动双击）")
    try:
        os.startfile(path)   # 等价于双击：尊重启动项的工作目录与运行方式
    except Exception as exc:
        log("error", "chain.tool_open_failed", err=str(exc))
        return None
    deadline = time.time() + timeout
    while time.time() < deadline:
        hwnd = _find_tool_hwnd()
        if hwnd:
            # 冷启动：等工具把"自动获取密钥"钩子武装好，再交点击器。否则紧接着点
            # 「1.获取公众号id」时工具毫无反应（日志零新增 → wait_log 超时 rc=3）。
            # ⚠️ 实测：即便等 8s 预热 + 失败重试，冷拉起的工具钩子仍不挂载（钩子只在
            # 启动瞬间且当时微信内置浏览器打开才挂得上；本机已实机证伪预热/重试无效）。
            # 故置 TOOL_COLD_STARTED，主循环据此跳过下载并提示用户手工开温热工具。
            TOOL_COLD_STARTED = True
            time.sleep(TOOL_WARMUP_SETTLE)
            log("info", "chain.tool_opened", hwnd=hwnd, cold=True)
            return hwnd
        time.sleep(0.5)
    log("warn", "chain.tool_open_timeout", timeout=timeout,
        hint="双击启动项后窗口未在预期时间内出现")
    return None


def close_tool(timeout: float = 8.0) -> None:
    """关掉下载工具窗口（等价于点右上角 × = WM_CLOSE）。

    关完等待窗口真正消失；若仍残留（可能弹了确认框），降级再发一次 SC_CLOSE 并告警。
    只针对 Mywindow 工具窗口，绝不碰微信。
    """
    hwnd = _find_tool_hwnd()
    if not hwnd:
        return
    try:
        win32gui.PostMessage(hwnd, 0x0010, 0, 0)   # WM_CLOSE
    except Exception as exc:
        log("warn", "chain.tool_close_failed", err=str(exc))
        return
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not clicker.find_windows(r".*公众号.*下载工具.*", ["Mywindow"]):
            log("info", "chain.tool_closed", hwnd=hwnd)
            return
        time.sleep(0.3)
    # 兜底：再发一次系统关闭命令（Alt+F4 = WM_SYSCOMMAND + SC_CLOSE）
    try:
        win32gui.SendMessage(hwnd, 0x0112, 0xF060, 0)   # SC_CLOSE
        time.sleep(0.5)
    except Exception:
        pass
    if clicker.find_windows(r".*公众号.*下载工具.*", ["Mywindow"]):
        log("warn", "chain.tool_close_timeout", hwnd=hwnd,
            hint="已发 WM_CLOSE/SC_CLOSE，窗口仍在，可能弹了确认框；请人工关闭")


def run(args) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    global TOOL_COLD_STARTED
    TOOL_COLD_STARTED = False   # 每轮运行重置：是否本运行冷拉起了下载工具
    journal = Path(args.journal)
    if not journal.is_absolute():
        # 相对路径按技能根目录解析：脚本可能被任何 cwd 调用，journal 必须唯一
        journal = SKILL / journal

    log("info", "chain.start", dry_run=bool(args.dry_run), max=int(args.max),
        skip_download=bool(args.skip_download), range=args.range,
        journal=str(journal))

    # 1) 窗口 + 首张截图 + 页面校验（不在页就停，绝不猜坐标）
    win = wf.ensure_window()
    if not win:
        return EXIT_ENV
    got = wf._capture(win["hwnd"])
    if not got:
        log("error", "chain.capture_failed",
            hint="截图空白/最小化：微信可能被完全遮挡，请还原窗口后重跑")
        return EXIT_ERROR
    img, rect = got
    st = wf.page_state(img)
    log("info", "chain.page_check", on_favorites=st["ok"], signal=st["signal"],
        title=st["title"], tab=st["tab"], rows=st["rows"], rect=rect)
    if not st["ok"]:
        evidence = vision.save(img, OUT / "chain-wrong-page.png")
        log("error", "chain.wrong_page", state=st, evidence=str(evidence),
            hint="当前不在「赞和收藏」页。请先手动进入：微信 → 公众号 → 个人中心 "
                 "→ 赞和收藏（当前若停在一篇文章页，按 Ctrl+W 关掉该标签页即可回到列表）")
        return EXIT_ERROR

    processed = wf.processed_fingerprints(journal)
    log("info", "chain.journal_loaded", path=str(journal), processed=len(processed),
        fp_algo=wf.FP_ALGO)

    # 本会话已尝试过的行（含 not_opened）：跨进程去重靠 journal，同一进程内的
    # "不重试同一篇"靠这个集合。两者语义不同，不能合并成一个。
    session_fps: set[str] = set()
    # 汇总里的"跳过"只统计 **journal 里跨次运行已处理**的行。
    # 不能用 processed|session_fps：那会把本会话刚处理/刚预演的行也算成"跳过"，
    # 于是 3 篇预演报成"处理 3 / 跳过 2"——自己跳自己，读日志的人会以为
    # 列表里有 2 篇是被历史记录挡下的（实测 2026-10-26 抓到）。
    # 同画面每轮都会重新扫到同一批行，所以用集合而不是累加（否则 10 行数成 30）。
    skipped_fps: set[str] = set()
    attempted = ok = skipped_download = failed = 0
    # 因「台账里这个 profile_ext 已存在」而整段跳过的篇数（省掉一次整号下载）
    same_account_skipped = 0

    # 列表滚动采集：收藏列表通常远多于一屏，必须向下滚才能触达全部篇目。
    # SCROLL_BUDGET 给 for 循环留出滚动余量（滚动不计入 attempted），并作为
    # 防异常无限滚的硬上限；每次滚动 < 一屏，保证与上一屏有重叠、不漏行。
    SCROLL_STEP = 4            # 每次向下滚动的滚轮格数
    SCROLL_SETTLE = 0.7        # 滚动后等列表渲染
    SCROLL_BUDGET = 400        # 滚动次数硬上限
    scrolls = 0

    for r in range(int(args.max) + SCROLL_BUDGET):
        if r > 0:
            # D1：每轮重新截图。点开文章后界面已变，上一轮的几何/坐标全作废。
            got = wf._capture(win["hwnd"])
            if not got:
                log("error", "chain.capture_failed", round=r, hint="本轮截图空白")
                return EXIT_PARTIAL if ok else EXIT_ERROR
            img, rect = got
            st = wf.page_state(img)
            if not st["ok"]:
                evidence = vision.save(img, OUT / ("chain-lost-page-%02d.png" % r))
                log("error", "chain.lost_page", round=r, state=st,
                    evidence=str(evidence),
                    hint="本轮回不到列表页（上一步关标签页失败？）。已处理的文章按"
                         "指纹记录，人工返回列表页后重跑不会重复点击")
                return EXIT_PARTIAL if (ok + skipped_download) else EXIT_ERROR

        rows, src = wf.rows_for(img, rect)
        if not rows:
            # 0 行是最容易误判成"没文章"的失败：今天实测就是窗口宽度变了
            # （缓存 1652、当前 1821）导致运行时不检出、缓存又因宽度不符被弃用。
            now_w = int(rect[2] - rect[0])
            cached_w = _cached_row_width()
            evidence = vision.save(img, OUT / ("chain-no-rows-%02d.png" % r))
            log("error", "chain.no_rows", round=r, source=src, now_w=now_w,
                cached_w=cached_w, evidence=str(evidence),
                hint="没有行几何数据。① 确认微信停在「赞和收藏」页且未被遮挡；"
                     "② 窗口宽度变了（当前 %d，校准缓存 %d）会让运行时检测与缓存"
                     "双双失效 —— 请重跑 `python scripts/capture_templates.py` "
                     "重新校准，然后再跑本脚本" % (now_w, cached_w))
            return EXIT_PARTIAL if (ok + skipped_download) else EXIT_ERROR

        rows = annotate_rows(rows, lambda row: wf.row_fingerprint(img, row))
        done = processed | session_fps
        # 只把"journal 里的历史记录"算作跳过（见 skipped_fps 的注释）；done 用于
        # 本轮诊断，说明这一屏里有多少行是"本会话或历史已碰过"的
        skipped_fps |= {x["fp"] for x in rows if x.get("fp") in processed}
        log("info", "chain.rows", round=r, count=len(rows), source=src,
            already=count_processed(rows, done))
        row = pick_next_row(rows, done)
        if row is None:
            # 当前可见行都处理过了：向下滚动列表，载入下方未处理的篇目。这是「批量
            # 采集 64 篇」能真正触达全部收藏的关键（原先无滚动，跑到一屏约 9 篇就
            # all_processed 停了）。指纹基于标题内容（非坐标），滚动后同一行指纹
            # 不变，不会重复处理；新露出的行指纹不在 done 里才会被点。
            if scrolls >= SCROLL_BUDGET:
                log("warn", "chain.all_processed", round=r, count=len(rows),
                    scroll=scrolls,
                    hint="滚动次数达上限仍未找到新行：列表可能已到底，或滚动未生效；"
                         "请人工确认收藏列表是否还有未处理篇目")
                break
            if args.dry_run:
                # 预演不真滚，只报告"将会滚动"
                log("info", "chain.would_scroll", round=r, scroll=scrolls + 1,
                    hint="dry-run：不真实滚动，下一篇将由滚动后重新检测得到")
                break
            wf._scroll_list_down(rect, step=SCROLL_STEP)
            scrolls += 1
            time.sleep(SCROLL_SETTLE)
            got2 = wf._capture(win["hwnd"])
            if not got2:
                log("error", "chain.capture_failed", round=r, hint="滚动后截图空白")
                break
            img2, rect2 = got2
            st2 = wf.page_state(img2)
            if not st2["ok"]:
                evidence = vision.save(img2, OUT / ("chain-lost-page-%02d.png" % r))
                log("error", "chain.lost_page", round=r, state=st2,
                    evidence=str(evidence),
                    hint="滚动后不在列表页；已处理的文章按指纹记录，人工返回后重跑")
                break
            rows2, src2 = wf.rows_for(img2, rect2)
            if not rows2:
                log("error", "chain.no_rows", round=r, source=src2,
                    hint="滚动后检测不到行几何；请确认窗口未被遮挡、宽度未变")
                break
            rows2 = annotate_rows(rows2, lambda row: wf.row_fingerprint(img2, row))
            before_set = {x.get("fp") for x in rows if x.get("fp")}
            after_set = {x.get("fp") for x in rows2 if x.get("fp")}
            new_unprocessed = [x for x in rows2 if x.get("fp") not in done]
            if after_set and after_set == before_set:
                # 滚动后可见行集合没变（列表已到底、无法再向下滚）→ 真正到底
                log("warn", "chain.all_processed", round=r, count=len(rows2),
                    scroll=scrolls,
                    hint="滚动后可见行无变化（列表已到底）：收藏全部处理完")
                break
            if new_unprocessed:
                # 滚动后露出了新行：回到循环顶部，用新截图重新检测 + 点
                log("info", "chain.scrolled", round=r, scroll=scrolls,
                    new_rows=len(new_unprocessed),
                    hint="向下滚动后露出 %d 条未处理行，继续" % len(new_unprocessed))
            else:
                # 滚动后可见行变了但没有新（未处理）行：多半是穿过一段已处理区，
                # 继续向下滚，下一轮再判（不在此误判为到底）
                log("info", "chain.scrolled", round=r, scroll=scrolls,
                    new_rows=0,
                    hint="滚动后露出的是已处理行，继续向下滚以越过该段")
            # r 由 for 循环负责自增；此处 continue 即可（不要手动 r+=1，会被下一轮
            # 的 for 赋值覆盖，纯属误导）
            continue

        cx = row["click_point"][0] + rect[0]
        cy = row["click_point"][1] + rect[1]
        attempted += 1
        if attempted > int(args.max):
            # 已达到目标采集篇数（滚动不计入 attempted），停止，不再开新篇
            log("info", "chain.reached_max", max=int(args.max), attempted=attempted)
            break
        base = {"round": r, "fp": row["fp"], "algo": wf.FP_ALGO, "rect": rect,
                "row": {k: row.get(k) for k in
                        ("y1", "y2", "center", "thumb_x1", "account_box",
                         "click_point")},
                "click_abs": [cx, cy], "ts": _now()}

        if args.dry_run:
            # 预演只打印计划：点行、点 ⊙ 都需要真实界面配合，预演不可能知道
            # ⊙ 在哪（它只在文章打开后才出现），所以只报"将会点的行坐标"。
            log("info", "chain.would_click", round=r, fp=row["fp"],
                click_abs=[cx, cy], account_box=row.get("account_box"),
                row_y=[row.get("y1"), row.get("y2")])
            print("[dry-run] 第 %d 篇：行 y=%s..%s → 点屏幕 (%d,%d)；"
                  "账号区域 %s；随后 ⊙/复制链接 由模板实时定位（不预演）"
                  % (r + 1, row.get("y1"), row.get("y2"), cx, cy,
                     row.get("account_box")))
            rec = dict(base, decision="would_click", result="planned",
                       reason="dry-run：只打印计划，未点击", article_url="",
                       profile_url="")
            append_journal(journal, rec)
            session_fps.add(row["fp"])   # 预演也要推进，否则 --max 3 会预览同一行
            continue

        # 1) 点这一行（R1：从上到下）
        if not _click_abs(win["hwnd"], rect, row["click_point"][0],
                          row["click_point"][1]):
            failed += 1
            append_journal(journal, dict(base, decision="failed",
                                         result="click_failed",
                                         reason="点击行失败（SendInput 与 mouse_event 均失败）"))
            log("error", "chain.click_failed", round=r, click_abs=[cx, cy])
            continue
        log("info", "chain.clicked_row", round=r, click_abs=[cx, cy], fp=row["fp"])

        # 2) 等列表页信号消失 = 文章已打开。超时不重试：重试会重复打开同一篇，
        #    而且"没打开"通常意味着点歪了/窗口被遮挡，重复点只会更糟。
        opened = vision.wait_until(wf._page_pred(win["hwnd"], False),
                                   timeout=args.open_timeout, poll=0.25)
        if not opened:
            snap = wf._capture(win["hwnd"])
            evidence = vision.save(snap[0] if snap else img,
                                   OUT / ("chain-not-opened-%02d.png" % r))
            session_fps.add(row["fp"])
            failed += 1
            journal_rec = dict(base, decision="not_opened", result="not_opened",
                               reason="点击后列表页信号未消失（文章可能没打开）",
                               evidence=str(evidence), article_url="",
                               profile_url="")
            append_journal(journal, journal_rec)
            log("warn", "chain.not_opened", round=r, evidence=str(evidence),
                hint="不重试同一篇（避免重复打开）；下一篇继续。下一篇若仍失败，"
                     "请人工确认窗口未被遮挡、列表行可点")
            # 有一种"慢开"：文章在超时之后才打开。此时画面已经不是列表页了，
            # 若不收掉这个标签页，下一轮会判 lost_page 直接退出整批。
            restore_list(win["hwnd"], args.back_timeout)
            continue
        log("info", "chain.article_opened", round=r)
        wf._nap(args.settle)     # 等文章正文/标签栏渲染完，否则 ⊙ 还没画出来

        # 3) 第 2 步：⊙ → 复制链接 → 读剪贴板
        url, info = copy_article_link(win["hwnd"], clip_timeout=args.clip_timeout)
        if not url:
            # 失败路径可能把菜单留在展开态，此时 Ctrl+W 会被菜单吃掉（标签页
            # 关不掉 → 下一轮判"不在列表页"直接退出）。先按 Esc 收起再关。
            vision.key_tap(vision._VK_ESCAPE)
            # 拿不到链接：关掉文章标签页回到列表，避免下一轮判"不在列表页"退出；
            # 这一支才需要关——见下方成功支的说明。
            vision.close_tab()
            back = vision.wait_until(wf._page_pred(win["hwnd"], True),
                                     timeout=args.back_timeout, poll=0.25)
            if not back:
                # 不中断：下一篇还会重新截图+判页，如果真回不去，下一轮会用
                # chain.lost_page 明确报出来，而不是在这里含糊地报"返回超时"
                log("warn", "chain.back_failed", round=r,
                    hint="Ctrl+W 后列表信号没恢复；若确认停在文章页，请手动关闭标签页")
            failed += 1
            session_fps.add(row["fp"])
            append_journal(journal, dict(base, decision="failed",
                                         result=info.get("reason") or "no_url",
                                         reason="没能拿到文章链接", copy=info,
                                         article_url="", profile_url=""))
            continue

        # 拿到链接：**保持文章标签页打开**，不要在此关掉。
        # 下载器的「1.获取公众号id」钩子要读微信内置浏览器当前正显示的文章页
        # 才能拿到 biz（见 profiles/wechat_batch_downloader.yaml 注释）。一旦在
        # 下载前关掉文章，钩子读不到 → 点取 id 零反应/空日志（chain_test4 实证：
        # close_tab 成功关掉文章后，下载器日志全程无新增）。
        # 早期 chain_test2 round0 之所以成功，正是当时 close_tab 失败、文章意外
        # 留开着 —— 这里把它转正为确定性行为。下载完成后由下方各分支的
        # restore_list 统一回到列表页（成功支/失败支都会调）。

        log("info", "chain.got_url", round=r, url=url, **{
            "more": info.get("more"), "copy": info.get("copy"),
            "more_fallback": info.get("more_fallback"),
            "attempts": info.get("attempts")})

        # journal 的 decision 只给**整条链路成功**的那一篇记 click：
        # wf.processed_fingerprints 只认 decision=="click"，而它的语义是
        # "这一行永久不用再处理"。若拿到链接就记 click，下载工具失败的那篇
        # 下次会被静默跳过 ⇒ 静默漏采（比重复点一次严重得多）。
        # 下方各分支因此用 link_ok / download_failed 等"不参与去重"的值，
        # 同一次运行内靠 session_fps 保证不会重复点同一篇。
        rec = dict(base, decision="click", result="url_ok", reason="已拿到文章链接",
                   article_url=url, profile_url="", copy=info)
        session_fps.add(row["fp"])

        if args.skip_download:
            skipped_download += 1
            append_journal(journal, dict(rec, decision="link_ok",
                                         result="download_skipped",
                                         reason="--skip-download：只验证微信侧 1~2 步"))
            log("info", "chain.download_skipped", round=r, url=url,
                hint="--skip-download：未调用下载工具，也不写台账（未下载的东西不该记账）")
            continue

        # 4) 第 3~7 步：交给**一次** clicker 全量调用（1..33 步）。
        #    原设计把"取密钥(1..27)"与"批量下载(28..33)"拆成两个独立 clicker 子进程，
        #    想在中间插账号级判重；真机证伪：子进程不共享密钥/会话，段B 新进程无密钥
        #    ⇒ 卡在起始页 0 永冻、0 产物，且当日累计日志让段B 一进来就"命中"段A 那一波
        #    旧行误判成功。改回单次全量调用（对齐已验证的受控实验路径），账号级去重
        #    后移到"下载完成后查 ledger"（见下方），不再靠拆段预判。
        # 下载前确保工具已开（首轮本来开着；上一轮收尾关掉后这里负责重开）
        if not ensure_tool_open():
            failed += 1
            session_fps.add(row["fp"])
            append_journal(journal, dict(base, decision="failed",
                                         result="tool_not_open",
                                         reason="下载工具未能打开（启动项缺失或启动超时）",
                                         article_url=url, profile_url=""))
            log("error", "chain.tool_not_open", round=r,
                hint="下载工具没能打开，本轮跳过；下一篇会继续尝试重开")
            continue
        if TOOL_COLD_STARTED:
            # 工具是脚本冷拉起的：其"自动获取密钥"钩子几乎必然未挂载（仅启动瞬间且需
            # 当时微信内置浏览器打开才挂得上；本机已实机证伪预热/重试均无效）。强约束：
            # 量产必须先用用户手工打开的温热工具，否则点「获取公众号id」零反应。
            log("error", "chain.tool_cold_started", round=r,
                hint="下载工具是脚本冷拉起的，钩子未挂载，点「获取公众号id」会零反应。"
                     "请先**手动双击桌面启动项**打开工具（保持微信在赞和收藏页），"
                     "让它温热后再运行本脚本。本篇跳过下载。")
            failed += 1
            session_fps.add(row["fp"])
            append_journal(journal, dict(base, decision="failed",
                                         result="tool_cold_started",
                                         reason="工具冷拉起，钩子未挂载，跳过下载",
                                         article_url=url, profile_url=""))
            restore_list(win["hwnd"], args.back_timeout)
            continue
        text = ""
        rec["range"] = args.range
        rc, text, profile_url = run_downloader(
            url, r, profile=args.profile, range_key=args.range,
            force_full=True, tag="")
        rec["profile_url"] = profile_url
        rec["clicker_rc"] = rc
        rec["clicker_log"] = str(OUT / ("chain-clicker-%02d.log" % r))
        if rc not in (EXIT_OK, EXIT_PARTIAL):
            # 首跑失败（工具是温热态但本次下载异常：网络/微信卡顿/页面信号抖动等）。
            # 重试一次——工具保持常开、钩子仍在，"自动获取密钥"通常能正常取
            # id/密钥。重试只针对这一篇（同一次运行内靠 session_fps 不重复点）。
            log("warn", "chain.downloader_retry", round=r, rc=rc,
                hint="首跑疑似下载器冷启动未就绪，重试一次（工具现已温热）")
            if not ensure_tool_open():
                failed += 1
                session_fps.add(row["fp"])
                append_journal(journal, dict(base, decision="failed",
                                             result="tool_not_open",
                                             reason="重试前下载工具未能打开",
                                             article_url=url, profile_url=""))
                log("error", "chain.tool_not_open", round=r)
                restore_list(win["hwnd"], args.back_timeout)
                continue
            rc, text, profile_url = run_downloader(
                url, r, profile=args.profile, range_key=args.range,
                force_full=True, tag="-r1")
            rec["profile_url"] = profile_url
            rec["clicker_rc"] = rc
            rec["clicker_log"] = str(OUT / ("chain-clicker-%02d-r1.log" % r))
        if rc not in (EXIT_OK, EXIT_PARTIAL):
            failed += 1
            rec.update(decision="download_failed", result="downloader_failed",
                       reason="下载工具返回码 %d（0/5 之外均视为失败）" % rc)
            append_journal(journal, rec)
            log("error", "chain.downloader_failed", round=r, rc=rc, phase="full",
                log=rec["clicker_log"],
                tail=text[-300:],
                hint="decision=download_failed 不参与去重，重跑会重试这一篇")
            restore_list(win["hwnd"], args.back_timeout)
            # 量产保持下载工具常开：不在每篇间 close_tool，避免下次冷拉起致钩子缺失、
            # 点「获取公众号id」零反应。工具由用户手工打开保持温热，整批不重开；本次真
            # 失败则下一篇复用同一温热工具重试，不在此关掉它。
            continue

        # 下载成功：工具跑完微信一般停在 profile_ext 页，先切回列表页，下一篇才接得上
        restore_list(win["hwnd"], args.back_timeout)
        # 量产保持下载工具常开：不在每篇间 close_tool（见上方失败分支说明），整批末尾统一关。
        ok += 1
        rec["result"] = "ok" if profile_url else "ok_no_profile_ext"
        # 账号级去重（后移版）：下载完成后查台账，若本号在"本次下载之前"就已采过，
        # 说明这次是重采（同一号在收藏列表常出现多篇）。只做信息提示（不再跳过下载），
        # 台账靠 profile_ext 幂等合并成 1 行；拆段预判已被证伪，无法在"下载前"跨进程
        # 拿到密钥/会话来提前判重。
        if profile_url and not args.ignore_ledger:
            hit, row_seq = account_already_collected(profile_url)
            if hit:
                same_account_skipped += 1
                session_fps.add(row["fp"])
                log("info", "chain.account_already_collected_post", round=r,
                    profile_url=profile_url, existing_row=row_seq, article_url=url,
                    hint="本号台账已有（序号 %s），本次为重采；产物覆盖/新增，台账幂等合并" % row_seq)
        # rc=5 且没拿到 profile_ext：仍然**按成功记账**（不改判 download_failed，
        # 5 只表示有 optional 步骤失败过），只把风险显性化。
        event, hint = id_missing_event(rc, profile_url)
        if event:
            log("warn", event, round=r, rc=rc, article_url=url,
                clicker_log=str(OUT / ("chain-clicker-%02d.log" % r)),
                hint=hint)
        append_journal(journal, rec)
        # 台账只记"真下载成功"的那一篇：预演/跳过下载/失败都不记，
        # 否则台账会变成"碰过的文章清单"，与实际产物对不上。
        ledger_ok = append_ledger({
            "source": "赞和收藏",
            "account": "",
            "title": "",
            "url": url,
            "profile_url": profile_url,
            "note": "",
        })
        log("info", "chain.recorded", round=r, ledger=ledger_ok, url=url,
            profile_url=profile_url)

    # 整批结束：量产期间下载工具始终保持打开（避免冷拉起致钩子缺失、点「获取公众号id」
    # 零反应）。此处统一收尾关闭（等价点右上角 ×）。中途异常早退则工具残留无害，
    # 用户可手关或直接重跑（温热态更稳）。
    close_tool()

    # 「跳过」分两种，含义不同，汇总里分开报：
    #   skipped_processed —— 列表里指纹已处理过的行（去重后计数）
    #   skipped_download  —— 拿到链接但因 --skip-download 没往下走
    #   same_account_skipped —— 本号已采过的"重采"次数（仍会真实下载，只是台账幂等
    #                          合并；不再像旧设计那样在下载前整段跳过，故恒 ≤ ok）
    skipped_processed = len(skipped_fps)
    skipped = skipped_download + skipped_processed + same_account_skipped
    log("info", "chain.summary", attempted=attempted, ok=ok, skipped=skipped,
        failed=failed, skipped_download=skipped_download,
        skipped_processed=skipped_processed,
        same_account_skipped=same_account_skipped,
        dry_run=bool(args.dry_run), journal=str(journal))
    print("汇总：处理 %d 篇 / 成功 %d / 跳过 %d / 失败 %d（journal: %s）"
          % (attempted, ok, skipped, failed, journal))

    if args.dry_run:
        return EXIT_OK if attempted else EXIT_PARTIAL
    if failed and ok:
        return EXIT_PARTIAL
    if failed and not ok:
        return EXIT_ERROR
    # 账号级去重已改为"下载后查台账"：same_account_skipped 计的是"已采号的重采"，
    # 它发生时 ok 必然已 +1，故本条件里它只是冗余保险；ok 为真即代表本批有成功产物，
    # 不应报"部分成功"——否则批量跑完看着像有失败，人还得逐条核对。
    return EXIT_OK if (ok or skipped_download or same_account_skipped) else EXIT_PARTIAL


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="「赞和收藏」→ 公众号文章批量下载：七步串联驱动器")
    ap.add_argument("--max", type=int, default=1, help="本次最多处理几篇（默认 1）")
    ap.add_argument("--dry-run", action="store_true",
                    help="只截图/判页/选行并打印计划，不点击、不调用下载工具")
    ap.add_argument("--yes", action="store_true",
                    help="确认真执行（会点开文章并让下载工具真的开始下载）")
    ap.add_argument("--skip-download", action="store_true",
                    help="跳过第 3~7 步：只验证微信侧能否稳定拿到文章链接")
    ap.add_argument("--ignore-ledger", action="store_true",
                    help="忽略账号级去重：即使台账里已有该公众号也照常完整下载一遍"
                         "（用于'就是要重新拉'的场景）")
    ap.add_argument("--journal", default=DEFAULT_JOURNAL,
                    help="决策台账（jsonl，跨次运行靠它去重）：默认 %s" % DEFAULT_JOURNAL)
    ap.add_argument("--profile", default=DEFAULT_PROFILE,
                    help="下载工具步骤表名：默认 %s" % DEFAULT_PROFILE)
    ap.add_argument("--range", default="monthly", choices=("all", "monthly"),
                    help="下载工具的时间范围：monthly＝一个月内（默认），all＝全部历史。"
                         "2026-10-28 真机实测 all 会让下载器在起始页 0 冻结、0 产物；"
                         "monthly 稳定。仅确认工具已修复全量枚举冻结且确需全量时才用 all")
    ap.add_argument("--settle", type=float, default=2.0,
                    help="点开文章后等页面渲染的基准秒数（节奏层会加长）")
    ap.add_argument("--open-timeout", type=float, default=8.0,
                    help="等文章打开（列表信号消失）的最长秒数")
    ap.add_argument("--back-timeout", type=float, default=8.0,
                    help="等回到列表页（列表信号恢复）的最长秒数")
    ap.add_argument("--clip-timeout", type=float, default=3.0,
                    help="点「复制链接」后等剪贴板出现新文章链接的最长秒数")
    args = ap.parse_args(argv)

    code, msg = validate_args(args)
    if code != EXIT_OK:
        print(msg, file=sys.stderr)
        return code
    try:
        return run(args)
    except KeyboardInterrupt:
        print("用户中断", file=sys.stderr)
        return EXIT_ERROR
    except Exception as exc:
        log("error", "chain.unexpected", err="%s: %s" % (type(exc).__name__, exc))
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
