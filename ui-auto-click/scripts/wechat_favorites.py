#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""微信「赞和收藏」逐篇发现编排器（scout）。

任务目标：从上到下遍历「我已点赞」的文章，**每轮只处理一篇**；
仅当该篇所属公众号**尚未在本程序中采集过**时才点击，否则跳过。

为什么要这个脚本（2026-10-23 实机取证）
--------------------------------------
微信 PC 4.x 是 CEF/Chromium 自绘 UI，UIA 与 MSAA **都读不到界面内容**
（两个独立后端在同一台真机上验证过），也没有远程调试端口。
⇒ 只能走「截图 + 模板匹配 + 坐标点击」，即 RPA 社区对 4.x 的通用路线。
本脚本因此**不依赖控件树**，只依赖 vision.py 的截图/匹配/点击能力。

状态机（每轮走一遍，失败即停并留证）
------------------------------------
  INIT        微信进程在不在；不在则先按「任务栏微信图标」启动
  ENSURE_WIN  恢复最小化 + 置前 + 确认没被别的窗口盖住
  ENSURE_PAGE 确认停在「赞和收藏」页：标题模板 ≥0.80，或「全部」标签 ≥0.80
               且实时检出 ≥2 个列表行（回退判据，见 page_state）。
               不在页时**状态感知自动导航**：左侧「赞和收藏」已直接可见则直接点；
               否则走 公众号 → 个人中心（小人像）→ 赞和收藏；仍失败才报错
               （不再要求人工先到位，见 navigate_to_favorites / _try_click_fav_direct）
  SCAN        重新截图 → 运行时检测列表行 → 全量重扫所有可见行并按内容指纹构成集合
  IDENTIFY    账号身份用「名区域列投影指纹」归并同号多行；并 vs 已采集名单做次要对账
  DECIDE      同号指纹已点过 / 命中名单 → skip；否则 → click（去重靠指纹，重排安全）
  ACT         点击 → 等列表信号消失（文章页已开）→ 回列表 → 等信号恢复
  RECORD      追加一条决策记录（含指纹与证据图）→ 进入下一轮

三个 2026-10-23 修复的设计约束（都是踩坑后定的）
------------------------------------------------
  D1 每轮**重新截图**：旧实现全程复用首张截图，--max-rounds>1 时第 2 篇
     起的决策都基于已过期的画面（点击后界面早变了）。
  D2 行身份用**内容指纹**（dHash）：跨次运行靠 journal 去重，否则每次调用
     都从"最上方一行"开始，会重复点同一篇（违反 R2 不重复）。
  D3 页面切换**先离页再认页**：点完立刻截图看到的往往还是旧页，必须等
     列表信号先消失、再等它恢复，才算完成一次"出去又回来"。

退出码：0 ok / 2 参数 / 3 执行失败 / 5 部分成功 / 6 环境不具备
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import ctypes
import hashlib
import re

import cv2
import numpy as np

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
import vision  # noqa: E402
import clipboard  # noqa: E402  # 同目录 clipboard.py：正确用 GlobalLock 读 CF_UNICODETEXT

# 拟人节奏层（可选依赖）：缺失时降级为固定 sleep，功能不折、只是不拟人。
try:
    import rhythm as _rhythm_mod  # noqa: E402
except Exception:
    _rhythm_mod = None

EXIT_OK, EXIT_PARAM, EXIT_ERROR, EXIT_PARTIAL, EXIT_ENV = 0, 2, 3, 5, 6
TPL = SKILL / "templates"
OUT = SKILL / "out"
# 前置导航模板：从任务栏启动微信并自动进入「赞和收藏」所需的 4 个元素模板。
# 元素位置均来自用户提供的 4 张截图，经逐像素标定 + best_match 自验证（命中即源图坐标）。
NAV_TPL = {
    "taskbar": TPL / "nav-taskbar-wechat.png",  # 任务栏微信绿色双气泡图标
    "gzh": TPL / "nav-gzh.png",                  # 左侧聊天列表里的「公众号」行（图标+文字）
    "person": TPL / "nav-person.png",            # 公众号页右上角「个人中心」小人像
    "fav": TPL / "nav-fav.png",                  # 个人中心左栏「赞和收藏」菜单项
}
# 各步模板匹配阈值（best_match 分数；边缘匹配对颜色/选中态免疫，阈值留足余量）。
NAV_MIN_SCORE = {"taskbar": 0.60, "gzh": 0.55, "person": 0.55, "fav": 0.55}
DEFAULT_DOWNLOAD_ROOT = Path("C:/Users/Administrator/Desktop/下载")

# 公众号名识别阈值（2026-10-23 实测校准，见 account_score 注释）。
# 两道闸门同时成立才认：
#   IDENTIFY_THRESHOLD —— 绝对分下限。实测自匹配 0.76~0.82、无关名 ≤0.44。
#   IDENTIFY_MARGIN    —— 与第二名的差距。实测「宠物食品联盟 vs 宠物食品商情」
#                         只差 0.008（同一前缀四个字相同），这种必须判未知。
# 低于任一条一律判"新号"——宁可多点一次（下游 import 幂等会去重），不可漏采。
IDENTIFY_THRESHOLD = 0.70
IDENTIFY_MARGIN = 0.20
# 会话内"同号多行"判据：账号区域指纹内积 ≥ 此值即视为同一段文字（同一公众号）。
# 取 0.85 的依据：同源文字自匹配实测 0.76~0.82（不同时刻截图 + 抗锯齿差异），
# 不同号 ≤0.44；同一张截图里同号两行是**同一渲染**，只会比 0.82 更高。
ACCOUNT_SAME_MIN = 0.85
_PROFILE_BINS = 96        # 列投影重采样宽度：宽度归一到 96 格，字号差被吸收
# 页面在位判据：标题模板分，或「全部」标签分 + 实时行数（回退判据）。
PAGE_TITLE_MIN = 0.80
PAGE_TAB_MIN = 0.80
PAGE_MIN_ROWS = 2


def log(level: str, event: str, **kw) -> None:
    rec = {"ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "level": level, "event": event}
    rec.update(kw)
    print(json.dumps(rec, ensure_ascii=False), file=sys.stderr)


# ----------------------------------------------------------- 拟人节奏（可选）
def _rhythm():
    if _rhythm_mod is None:
        return None
    try:
        return _rhythm_mod.get_rhythm()
    except Exception:
        return None


_R = _rhythm()
_LIMITER = None


def _limiter():
    """写动作限流器（懒构造）：节奏层缺失/构造失败时返回 None（放行）。"""
    global _LIMITER
    if _LIMITER is None and _rhythm_mod is not None:
        try:
            _LIMITER = _rhythm_mod.WriteRateLimiter()
        except Exception:
            _LIMITER = False      # 标记不可用，别每次重试构造
    return _LIMITER or None


def _nap(base: float) -> None:
    """功能等待（如等文章页加载）：节奏层把等待加长，且**内部睡**。

    off 档的 nap 只返回不睡——但"等页面打开"是功能等待不是节奏装饰，
    所以 off 档在这里补睡，不能让等待被静默吞掉。
    """
    r = _R
    if r is not None and hasattr(r, "nap"):
        try:
            secs = float(r.nap(base) or 0.0)
        except Exception:
            secs = -1.0
        if secs >= 0:
            if getattr(r, "level", "") == "off" and secs > 0:
                time.sleep(secs)
            return
    time.sleep(base)


def _write_gap() -> None:
    """写动作（点击/按键）前的拟人间隔；节奏层内部会睡，缺失时空转。"""
    r = _R
    if r is not None and hasattr(r, "write_gap"):
        try:
            r.write_gap()
        except Exception:
            pass


def _before_write() -> None:
    """写动作频率闸门：超窗口配额会被冷却（内部睡）；缺失时放行。"""
    lim = _limiter()
    if lim is not None:
        try:
            lim.before_write()
        except Exception:
            pass


def _jitter_xy(x: int, y: int, radius: int = 5):
    """控件内随机落点；节奏层缺失时原样返回。"""
    r = _R
    if r is not None and hasattr(r, "jitter_xy"):
        try:
            return r.jitter_xy(x, y, radius)
        except Exception:
            pass
    return x, y


# ----------------------------------------------------------- 已采集名单
def collected_accounts(download_root: Path) -> set[str]:
    """已采集过的公众号 = 下载根目录下的子目录名 + 清单里的 account 字段。

    两个来源都要：目录名是"这个号已经采过"的最直接证据；manifest 的 account
    字段能兜住"目录建了但还没下完"的情况。
    """
    names: set[str] = set()
    if download_root.is_dir():
        for d in sorted(download_root.iterdir()):
            if d.is_dir() and not d.name.startswith(("_", ".")):
                names.add(d.name)
    for man in download_root.glob("*/_reports/manifest.json"):
        try:
            data = json.loads(man.read_text(encoding="utf-8"))
            for a in data.get("articles", []):
                acc = a.get("account")
                if acc:
                    names.add(acc)
        except Exception:
            continue
    return names


def refresh_registry(download_root: Path, prev: set[str] | None = None) -> set[str]:
    """重读已采集名单；与上次**不同**才打日志（避免每轮刷同一条）。

    为什么要每轮重读（2026-10-23 修）：真实跑完一篇后，下载侧会新建子目录 /
    写 manifest，名单随之增长。只在启动读一次 ⇒ 名单是过期快照，
    `--max-rounds>1` 遇到"同一公众号在列表里占多行"时会连点同号多篇。
    名单是廉价的目录扫描（几十个目录），每轮读一次不值一提。
    """
    reg = collected_accounts(download_root)
    if prev is None or reg != prev:
        log("info", "scout.registry", accounts=sorted(reg), count=len(reg),
            refreshed=prev is not None,
            grew=sorted(reg - prev) if prev is not None else [])
    return reg


# ----------------------------------------------------------- 窗口与页面
def ensure_window() -> dict | None:
    """找微信窗口并置前。窗口选择逻辑在 vision.wechat_window()
    （CEF 类名优先——标题含「微信」的大浏览器窗口曾劫持过目标，见那里注释）。
    """
    ws = vision.wechat_windows()
    if not ws:
        log("error", "scout.no_wechat", hint="请先启动微信 PC 端并登录")
        return None
    w = vision.wechat_window() or max(
        ws, key=lambda x: (x["rect"][2] - x["rect"][0]) * (x["rect"][3] - x["rect"][1]))
    # 最小化窗口：wechat_window 会回退选到最小化窗（其 rect 是 -32000 哨兵区）。先还原，
    # 再重选一次——还原后 CEF 内容视图(Chrome_WidgetWin_0)变为可见，应优先选中它，
    # 否则后面 page_check 会截到哨兵区误判。还原后若不在赞和收藏页，page_check 仍会
    # 如实报错停下（不替用户猜导航），这里只负责"把窗口弄成可见可截"。
    if w["iconic"]:
        log("warn", "scout.restoring_minimized", hwnd=w["hwnd"],
            hint="微信处于最小化，先还原窗口再继续；若还原后不在赞和收藏页，脚本仍会判错并停下")
        vision.activate_window(w["hwnd"])
        w = vision.wechat_window() or w
    log("info", "scout.window_pick", hwnd=w["hwnd"], cls=w["cls"],
        iconic=w["iconic"], candidates=len(ws))
    if not vision.activate_window(w["hwnd"]):
        log("warn", "scout.not_foreground", hwnd=w["hwnd"], iconic=w["iconic"],
            hint="没能把微信置前；若被其他窗口遮挡，点击会点错，请人工切到微信")
    # 置前后重读 rect：最小化窗口的 rect 是 (-32000,-32000) 哨兵，拿它算坐标
    # 会点飞到桌面角落（实测日志里曾出现 rect=[-32000,-32000,-31724,-31955]）。
    fresh = vision.find_windows(classes=vision.WECHAT_CLASSES)
    for x in fresh:
        if x["hwnd"] == w["hwnd"]:
            w = x
            break
    return w


def page_state(img) -> dict:
    """当前画面是不是「赞和收藏」文章列表页。返回全部证据分数。

    主判据 = templates/page-title.png ≥ 0.80。
    回退判据 = templates/tab-all.png ≥ 0.80 **且** 实时检出 ≥2 个列表行。
    回退判据存在的理由：2026-10-23 校准时微信被设置窗口压住，page-title
    模板被证伪测试拒绝移除，导致只有一个模板时 scout 完全跑不了。
    回退判据的两半都不可省：tab-all 单独在**聊天页**上能到 0.533（实测），
    单靠它会误判；"≥2 行"单独在聊天页也成立（聊天气泡图会被当成行）。
    两者同时满足才认。
    """
    st = {"title": 0.0, "tab": 0.0, "tab_edge": 0.0, "rows": 0,
          "ok": False, "signal": "none"}
    tpl = TPL / "page-title.png"
    if tpl.is_file():
        st["title"] = round(vision.best_match(img, vision.Image.open(str(tpl)))[0], 4)
    tab = TPL / "tab-all.png"
    if tab.is_file():
        needle = vision.Image.open(str(tab))
        st["tab"] = round(vision.best_match(img, needle)[0], 4)
        st["tab_edge"] = round(vision.best_match(img, needle, edge=True)[0], 4)
    # 这里只数行（回退判据用），不是取几何：warn=False，免得在聊天页等
    # 无关画面上刷「未定位到公众号名」的噪声日志。
    st["rows"] = len(vision.detect_rows(img, warn=False))
    if st["title"] >= PAGE_TITLE_MIN:
        st["ok"], st["signal"] = True, "title"
    elif st["tab"] >= PAGE_TAB_MIN and st["rows"] >= PAGE_MIN_ROWS:
        st["ok"], st["signal"] = True, "tab+rows"
    return st


def on_favorites_page(img) -> tuple[bool, float]:
    """兼容旧签名：(是否在页, 主分数)。主判据分优先，回退判据时给 tab 分。"""
    st = page_state(img)
    score = st["title"] if st["title"] > 0 else st["tab"]
    return st["ok"], score


# ----------------------------------------------------------- 前置导航
def _click_template(hay, rect, tpl_path, edge, label):
    """在 hay（PIL.Image）里匹配 tpl_path 并点击其几何中心。

    rect 为 hay 在屏幕上的绝对坐标基准：全屏截图时传 (0,0,W,H)，窗口截图时传窗口
    rect。返回 (score, (abs_x, abs_y))；不匹配或低于阈值返回 (None, None)。
    命中失败一律返回 None 不上报“已点击”，避免误点坐标——宁可停下来报错。
    """
    needle = vision.Image.open(str(tpl_path))
    nw, nh = needle.size
    score, loc = vision.best_match(hay, needle, edge=edge)
    if loc is None or score < NAV_MIN_SCORE[label]:
        log("warn", "nav.no_match", label=label, score=(round(score, 3) if score else None),
            min=NAV_MIN_SCORE[label])
        return None, None
    cx = rect[0] + loc[0] + nw // 2
    cy = rect[1] + loc[1] + nh // 2
    _before_write()
    _write_gap()
    jx, jy = _jitter_xy(cx, cy, 5)
    vision.click_at(jx, jy)
    log("info", "nav.click", label=label, score=round(score, 3), xy=[cx, cy])
    return score, (cx, cy)


def _wait_template(hwnd, tpl_path, edge, label, timeout: float = 8.0):
    """轮询：反复截图并在微信窗口里匹配模板，直到命中或超时。

    用于点击后确认页面已切到下一步目标（避免异步加载未完成就点下一个）。
    返回 (score, loc, rect)；超时返回 None。
    """
    needle = vision.Image.open(str(tpl_path))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        got = _capture(hwnd)
        if got:
            img, rect = got
            score, loc = vision.best_match(img, needle, edge=edge)
            if loc is not None and score >= NAV_MIN_SCORE[label]:
                return score, loc, rect
        time.sleep(0.3)
    return None


def launch_wechat_from_taskbar() -> bool:
    """从 Windows 任务栏点击微信图标启动微信（仅当微信未运行时调用）。

    命中任务栏模板后点击其几何中心；点击后轮询等待微信窗口出现。
    若微信本就运行，调用方不应走此分支（点击任务栏图标会最小化窗口）。
    """
    img = vision.capture_screen()
    needle = vision.Image.open(str(NAV_TPL["taskbar"]))
    score, loc = vision.best_match(img, needle, edge=False)
    if loc is None or score < NAV_MIN_SCORE["taskbar"]:
        log("error", "nav.taskbar_nomatch", score=(round(score, 3) if score else None))
        return False
    nw, nh = needle.size
    cx, cy = loc[0] + nw // 2, loc[1] + nh // 2
    _before_write()
    _write_gap()
    jx, jy = _jitter_xy(cx, cy, 3)
    vision.click_at(jx, jy)
    log("info", "nav.taskbar_click", score=round(score, 3), xy=[cx, cy])
    ok = vision.wait_until(lambda: vision.wechat_window() is not None, timeout=12.0, poll=0.3)
    if not ok:
        log("error", "nav.wechat_no_window",
            hint="点击任务栏微信图标后未检测到微信窗口，请确认微信已安装且未被托盘隐藏")
        return False
    return True


def _try_click_fav_direct(hwnd) -> bool:
    """若左侧面板已直接显示「赞和收藏」入口（公众号列表页等常见态），点击它。

    返回 True 表示**已点击**（不代表已落页）；落页与否由调用方用 _wait_on_fav 判断。
    实证（2026-10-28 实机）：微信停在公众号列表页时，左侧面板就有「赞和收藏」，
    无需绕「公众号 → 个人中心」。模板 nav-fav.png 在该态 best_match 0.989 命中。
    """
    got = _capture(hwnd)
    if not got:
        return False
    img, rect = got
    needle = vision.Image.open(str(NAV_TPL["fav"]))
    nw, nh = needle.size
    score, loc = vision.best_match(img, needle, edge=True)
    if loc is None or score < NAV_MIN_SCORE["fav"]:
        return False
    cx, cy = rect[0] + loc[0] + nw // 2, rect[1] + loc[1] + nh // 2
    _before_write()
    _write_gap()
    jx, jy = _jitter_xy(cx, cy, 5)
    vision.click_at(jx, jy)
    log("info", "nav.click", label="fav-direct", score=round(score, 3), xy=[cx, cy])
    return True


def _wait_on_fav(hwnd, timeout: float = 8.0) -> bool:
    """等待落在「赞和收藏」列表页（page_state 通过）。"""
    return vision.wait_until(_page_pred(hwnd, True), timeout=timeout, poll=0.25)


def navigate_to_favorites() -> bool:
    """自动进入「赞和收藏」列表页，状态感知、走最短可用路径。

    2026-10-28 实机证伪修订：原写死「公众号 → 个人中心 → 赞和收藏」只适用微信停在
    **首页**的情形；但微信常停在上次离开的**公众号列表页**，此时左侧面板已直接有
    「赞和收藏」入口，原流程第一步找"公众号"必然 0 匹配失败。

    修订后逻辑：
    - 捷径优先：每步前先探测左侧「赞和收藏」是否已直接可见，是则点它、等落页；
    - 完整流程兜底：不可见时才走 公众号 → 个人中心 → 赞和收藏；
    两条路径都通，且全程每步前复核，绝不绕冤枉路。返回最终是否停在目标列表页。
    """
    win = ensure_window()
    if not win:
        log("error", "nav.no_window", hint="导航时未能定位/置前微信窗口")
        return False
    hwnd = win["hwnd"]

    # 捷径优先：左侧「赞和收藏」已直接可见
    if _try_click_fav_direct(hwnd) and _wait_on_fav(hwnd):
        return True

    steps = [("gzh", NAV_TPL["gzh"]), ("person", NAV_TPL["person"]), ("fav", NAV_TPL["fav"])]
    for i, (label, tpl) in enumerate(steps):
        # 走完整流程途中，「赞和收藏」也可能已提前出现（如点完公众号就到了列表页），
        # 每步前再确认一次，可见就直接点，避免无意义绕到个人中心。
        if _try_click_fav_direct(hwnd) and _wait_on_fav(hwnd):
            return True
        got = _capture(hwnd)
        if not got:
            log("error", "nav.capture_failed", step=label)
            return False
        img, rect = got
        score, _ = _click_template(img, rect, tpl, True, label)
        if score is None:
            return False
        if i < len(steps) - 1:
            # 等待下一步目标出现，确认本步已切页
            nxt_label = steps[i + 1][0]
            if _wait_template(hwnd, steps[i + 1][1], True, nxt_label, timeout=8.0) is None:
                log("error", "nav.step_timeout", after=label,
                    hint="点击%s后未出现%s，页面可能未切换或被遮挡" % (label, nxt_label))
                return False
        else:
            # 最后一步：等待落在「赞和收藏」列表页
            if not _wait_on_fav(hwnd):
                log("error", "nav.not_on_fav_page",
                    hint="点击赞和收藏后未进入列表页（page_state 不通过）")
                return False
    return True


def _capture(hwnd: int):
    """截一次窗口并判空。返回 (img, rect) 或 None。

    最小化窗口的 rect 是 (-32000,-32000,…) 哨兵，vision.capture_window 已
    统一拒绝（返回 None），但那一步拒绝后调用方拿不到"为什么"。这里先用
    IsIconic 补一条可操作的告警——单次 API 调用，轮询里也不贵。

    截之前先把光标停到屏幕角落：列表行有 hover 态，鼠标压在某行上会让该行
    dHash 变（实测同一行几何 0110…→0111…），进而让 journal 里的指纹失效、
    同一篇文章被重复点。详见 vision.park_cursor。
    """
    if vision.is_iconic(hwnd):
        log("error", "scout.window_minimized", hwnd=hwnd,
            hint="微信窗口处于最小化状态，请先手动还原窗口（或点任务栏图标）后重跑")
        return None
    vision.park_cursor()
    got = vision.capture_window(hwnd=hwnd)
    if not got:
        return None
    img, rect = got
    if vision.is_blank(img):
        return None
    return got


def _page_pred(hwnd: int, want_on_page: bool):
    """轮询谓词：当前画面是否（不）在列表页。每次轮询只截一次图。"""
    def pred() -> bool:
        got = _capture(hwnd)
        if not got:
            return False
        return _page_ok(got[0]) is want_on_page
    return pred


def _page_ok(img) -> bool:
    return page_state(img)["ok"]


# ----------------------------------------------------------- 行几何
def baked_rows() -> list[dict]:
    """校准缓存 out/wx-rows.json 里的行几何（按窗口宽高缓存，见 rows_for）。"""
    p = OUT / "wx-rows.json"
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    out = []
    for r in data.get("rows", []):
        cy = r.get("center") or (r.get("y1", 0) + r.get("y2", 0)) // 2
        out.append({"y1": r.get("y1"), "y2": r.get("y2"), "center": cy,
                    "thumb_x1": r.get("thumb_x1"),
                    "thumb_x2": r.get("thumb_x2"),
                    "account_box": r.get("account_box") or [0, 0, 0, 0],
                    "click_point": r.get("click_point") or [r.get("x1", 300), cy]})
    return out


def rows_for(img, rect) -> tuple[list[dict], str]:
    """拿当前画面的行几何：运行时检测优先，校准缓存兜底。

    运行时检测是主路径——窗口被移动/缩放、列表滚动后坐标全变，只有从当前
    截图重新检测才跟得上（2026-10-23 实测窗口从 [882,0,2531,1518] 被搬到
    [613,86,2237,1370]，缓存坐标整体失效）。缓存只在运行时检测失败时用，
    且要求窗口尺寸一致，否则宁可报错不猜坐标。
    """
    rows = vision.detect_rows(img)
    if rows:
        return rows, "runtime"
    baked = baked_rows()
    if baked:
        w = rect[2] - rect[0]
        try:
            data = json.loads((OUT / "wx-rows.json").read_text(encoding="utf-8"))
            cached_w = int(data.get("w", 0))
        except Exception:
            cached_w = 0
        if cached_w and abs(cached_w - w) <= 2:
            # 走缓存说明运行时检测**失败**了（图片没加载完/被遮挡/版面变了）。
            # 缓存只保证窗口宽度一致，不保证滚动位置一致，所以必须留痕。
            log("warn", "scout.baked_geometry", rows=len(baked),
                hint="运行时行检测失败，改用校准缓存几何；列表可能已滚动，"
                     "点击前请人工确认页面与滚动位置")
            return baked, "baked"
        log("warn", "scout.baked_stale",
            cached_w=cached_w, now_w=w,
            hint="校准缓存的窗口宽高与当前不一致，弃用缓存；请重跑 capture_templates.py")
    return [], "none"


def _scroll_list_down(rect, step: int = 3) -> None:
    """在「赞和收藏」列表向下滚 step 格（负 clicks = 向下，见 run 中 scroll 用法）。

    仅负责滚动；是否到底由调用方比对滚动前后顶部行指纹判断。
    """
    cx = rect[0] + (rect[2] - rect[0]) // 2
    cy = rect[1] + (rect[3] - rect[1]) // 2
    vision.scroll_at(cx, cy, clicks=-abs(step))


# ----------------------------------------------------------- 决策去重
# 行几何算法版本。行指纹按 (thumb_x1, y1, W, y2) 裁图算 dHash，算法一变
# 同一条文章的指纹就变（2026-10-23 把正文左界从整页改成下半部统计，每行 y
# 整体上移 109px）⇒ journal 里的旧记录不再命中 ⇒ **已点过的行会被重复点一次**
# （实测：升级后第一次运行把「WorkBuddy 越用越慢」又点了一遍）。
# 这里用 journal 记录的 algo 字段识别"旧指纹"，只告警、不删记录：
# 一条回放记录的价值远大于少点一次；下游按 account 幂等去重能兜住重复。
FP_ALGO = "rows-v3"


def journal_stale_count(journal: Path, algo: str = FP_ALGO) -> int:
    """journal 里"非当前算法"的 click 条数（无 algo 字段的老记录也算）。

    老记录没有 algo 字段 ⇒ 正常首次升级也会 ≥1，这是刻意的：提醒"该核对了"，
    而不是静默地把旧指纹当成有效。
    """
    n = 0
    if not journal.is_file():
        return 0
    try:
        for line in journal.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("decision") == "click" and rec.get("algo") != algo:
                n += 1
    except Exception:
        return n
    return n


def processed_fingerprints(journal: Path) -> set[str]:
    """journal 里已点击过的行指纹。跨次运行去重靠它（D2）。"""
    fps: set[str] = set()
    if not journal.is_file():
        return fps
    try:
        for line in journal.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("decision") == "click" and rec.get("fp"):
                fps.add(rec["fp"])
    except Exception:
        return fps
    return fps


def row_fingerprint(img, row: dict) -> str:
    """行内容指纹：**文字区**（左沿到缩略图左沿）的 16 位 dHash。

    2026-10-23 两次推翻后的结论：
    ① 曾用「缩略图左沿 → 窗口右沿」整行（含缩略图）——实测 10 行只出 **9 个**
       唯一值：缩略图缩放到 9×8 后梯度高度雷同（都是"左深右浅"），真正有区分
       度的是标题文字。两行撞指纹的后果不是"少点一次"，而是**点了 A 行之后
       B 行被当成已处理跳过 ⇒ 静默漏采**。
    ② 只去掉缩略图还不够：`size=8`（64 位）仍会把不同标题压成同一梯度模式。
       改 `size=16`（256 位）后同一页面 **10/10** 唯一。
    ③ 左边界取 0 而不是 title_box[0]：标题首字笔画不同会让 x1 漂移上百像素
       （实测 262 vs 439），固定从 0 开始才稳定；左侧标签栏是静态文字，
       不影响区分度。
    """
    cx = row.get("thumb_x1") or img.width
    box = (0, int(row["y1"]), max(40, int(cx) - 8), int(row["y2"]))
    return vision.dhash(vision.crop(img, box), size=16)


# ----------------------------------------------------------- 主流程
def run(args) -> int:
    OUT.mkdir(exist_ok=True)
    journal = OUT / "favorites-journal.jsonl"

    root = Path(args.download_root)
    registry = refresh_registry(root)

    # journal 里若有旧算法指纹，本次会把那几篇重复点一次——先说清楚，不静默
    stale = journal_stale_count(journal)
    if stale:
        log("warn", "scout.fingerprint_algo", stale=stale, algo=FP_ALGO,
            hint="journal 里有 %d 条旧算法指纹（行几何算法已变更），这些文章"
                 "可能被重复点一次；下游按 account 幂等去重可兜住。要避免就先"
                 "把 out/favorites-journal.jsonl 归档再跑" % stale)

    # 1) 窗口：微信未运行则先从任务栏点击微信图标启动，再自动进入「赞和收藏」
    #    严格按用户给定流程：开始栏微信图标 → 公众号 → 个人中心（小人像）→ 赞和收藏。
    win = ensure_window()
    if not win:
        log("warn", "scout.no_window_try_launch",
            hint="未检测到微信窗口，尝试从任务栏点击微信图标启动")
        if not launch_wechat_from_taskbar():
            return EXIT_ENV
        win = ensure_window()
        if not win:
            return EXIT_ENV
    log("info", "scout.window", hwnd=win["hwnd"], rect=win["rect"])

    # 2) 首张截图 + 页面校验；不在页则自动导航（公众号→个人中心→赞和收藏）
    got = _capture(win["hwnd"])
    if not got:
        log("error", "scout.capture_failed", hint="截图空白：微信可能被完全遮挡")
        return EXIT_ERROR
    img, rect = got
    st = page_state(img)
    log("info", "scout.page_check", on_favorites=st["ok"], signal=st["signal"],
        title=st["title"], tab=st["tab"], tab_edge=st["tab_edge"], rows=st["rows"])
    if not st["ok"]:
        log("warn", "scout.wrong_page_nav", state=st,
            hint="当前不在「赞和收藏」页，尝试自动导航：公众号 → 个人中心 → 赞和收藏")
        if not navigate_to_favorites():
            log("error", "scout.wrong_page", state=st,
                hint=("自动导航失败。请确认微信停留在可用界面（含左侧「公众号」入口），"
                      "或手动进入：公众号 → 个人中心 → 赞和收藏；也可先跑 "
                      "scripts/capture_templates.py 校准模板"))
            vision.save(img, OUT / "scout-wrong-page.png")
            return EXIT_ERROR
        # 导航后重新截图校验（页面已切到「赞和收藏」列表页才算成功）
        got = _capture(win["hwnd"])
        if not got:
            log("error", "scout.capture_failed", hint="导航后截图空白")
            return EXIT_ERROR
        img, rect = got
        st = page_state(img)
        log("info", "scout.page_check_after_nav", on_favorites=st["ok"],
            signal=st["signal"], title=st["title"], tab=st["tab"],
            tab_edge=st["tab_edge"], rows=st["rows"])
        if not st["ok"]:
            log("error", "scout.wrong_page", state=st,
                hint=("自动导航后仍不在「赞和收藏」页。请手动进入：公众号 → "
                      "个人中心 → 赞和收藏；或先跑 scripts/capture_templates.py 校准模板"))
            vision.save(img, OUT / "scout-wrong-page.png")
            return EXIT_ERROR

    # 3) 可选：扫描前先往下滚（走完整列表时用）
    if args.scroll:
        cx, cy = rect[0] + (rect[2] - rect[0]) // 2, rect[1] + (rect[3] - rect[1]) // 2
        vision.scroll_at(cx, cy, clicks=-abs(args.scroll))
        _nap(1.0)
        got = _capture(win["hwnd"])
        if not got:
            log("error", "scout.capture_failed", hint="滚动后截图空白")
            return EXIT_ERROR
        img, rect = got
        st = page_state(img)
        if not st["ok"]:
            log("error", "scout.wrong_page", state=st, hint="滚动后页面判据不过")
            vision.save(img, OUT / "scout-wrong-page.png")
            return EXIT_ERROR
        log("info", "scout.scrolled", clicks=-abs(args.scroll), rows=st["rows"])

    vision.save(img, OUT / "scout-capture.png")
    log("info", "scout.captured", size=list(img.size), rect=rect)

    # 4) 采集主循环（2026-10-28 改造：全量重扫 + 账号指纹归并 + 收敛判停）
    # 解决"点赞导致列表重排 → 漏采/重采"的三道机制：
    #   A) 每轮回到列表后**整屏重扫**所有可见行，按内容指纹构成集合，而非只取最上方一行。
    #      点赞会把已点文章顶到最上方，但指纹集合不依赖位置 → 重排不影响去重与进度锚点。
    #   B) 账号身份用「公众号名区域列投影指纹」(account_key) 归并同号多行，
    #      替代 identify_account 的 0.70 文字模板匹配（实测置信度仅 0.24/0.46，
    #      会漏识、偶有错判已采而漏采）。指纹归并稳定、与字号无关。
    #   C) 收敛判停：覆盖全部滚动位置 + 连续 2 轮"可见区 0 新增"才判定采完
    #      （单轮 0 新增不足为据——可能身处列表中段，下方还有未扫文章）。
    seen: set[str] = set(processed_fingerprints(journal))
    session_keys: list = []           # 已点账号指纹，用于同号多行归并（机制 B）

    # 链接采集（最佳档）跨次去重集合：已采到的 __biz 不再重复写入 account_links.csv
    links_path = OUT / "account_links.csv"
    collected_biz: set[str] = _load_collected_biz(links_path)
    clicked = skipped = 0
    no_new_streak = 0
    prev_sig = None

    while True:
        # 安全上限：--max-rounds 限制"点开文章"的总次数，防止失控
        if args.max_rounds and (clicked + skipped) >= args.max_rounds:
            log("info", "scout.round_cap", cap=args.max_rounds,
                hint="已达 --max-rounds 上限，停止；如需采全表请加 --traverse 并给足上限")
            break

        # 名单每轮重读：上一轮真跑完可能已让下载侧新建了目录（见 refresh_registry）
        registry = refresh_registry(root, registry)

        if (clicked + skipped) > 0:
            got = _capture(win["hwnd"])
            if not got:
                log("error", "scout.capture_failed", hint="本轮截图空白")
                return EXIT_PARTIAL if clicked else EXIT_ERROR
            img, rect = got
            st = page_state(img)
            if not st["ok"]:
                log("error", "scout.lost_page", state=st,
                    hint="本轮已不在列表页（上轮返回失败？）；已处理进度按指纹记录，"
                         "不会重复点击，人工返回列表页后重跑即可")
                vision.save(img, OUT / "scout-lost-page.png")
                return EXIT_PARTIAL if clicked else EXIT_ERROR

        rows, src = rows_for(img, rect)
        log("info", "scout.rows", count=len(rows), source=src)
        if not rows:
            log("error", "scout.no_rows",
                hint="没有行几何数据。请先跑 scripts/capture_templates.py 生成 "
                     "out/wx-rows.json（需要微信停在赞和收藏页且不被遮挡）")
            return EXIT_PARTIAL if clicked else EXIT_ERROR

        # —— 全量重扫（机制 A）：所有可见行算指纹，构成集合 ——
        fresh = []
        fps = []
        for row in rows:
            fp = row_fingerprint(img, row)
            row["fp"] = fp
            fps.append(fp)
            if fp not in seen:
                fresh.append(row)
        # 可见区签名：用于侦测"点赞重排 / 滚动"导致的内容变化（不用于去重，去重靠指纹）
        sig = tuple(sorted(fps))
        if prev_sig is not None and sig != prev_sig:
            log("info", "scout.reordered", prev_rows=len(prev_sig), now_rows=len(sig),
                hint="列表可见区指纹签名变化（点赞重排或滚动），按内容指纹去重不受影响")
        prev_sig = sig

        if not fresh:
            # 当前屏都已决策过：未开 --traverse 则停下，让用户决定是否继续往下滚
            if not args.traverse:
                log("warn", "scout.view_exhausted",
                    hint="当前屏无新文章；加 --traverse 自动向下滚动覆盖全表，"
                         "或人工往下翻后重跑")
                break
            # 自动滚动覆盖（机制 C）：先记顶部指纹，滚后若顶部指纹不变说明已到底
            top_before = fps[0] if fps else None
            _scroll_list_down(rect, step=args.scroll_step)
            _nap(0.8)
            got2 = _capture(win["hwnd"])
            if got2:
                img2, rect2 = got2
                r2, _ = rows_for(img2, rect2)
                top_after = row_fingerprint(img2, r2[0]) if r2 else None
                moved = not (top_before is not None and top_after is not None
                             and top_before == top_after)
            else:
                moved = False
            if not moved:
                no_new_streak += 1
            else:
                no_new_streak = 0
            if no_new_streak >= 2:
                log("info", "scout.converged", no_new_rounds=no_new_streak,
                    hint="连续 2 轮可见区 0 新增且滚动无进展，判定全表采集完成")
                break
            continue

        no_new_streak = 0
        # 挑选：取最上方未处理行（位置仅用于挑选，去重仍靠指纹集合，重排安全）
        row = min(fresh, key=lambda r: (r.get("center") or r["y1"]))

        acct_region = vision.crop(img, row["account_box"])
        acct_png = OUT / ("scout-acct-%02d.png" % (clicked + skipped))
        vision.save(acct_region, acct_png)

        acct_fp = account_key(acct_region)
        same = (max(float((k * acct_fp).sum()) for k in session_keys)
                if (acct_fp is not None and session_keys) else None)
        # 机制 B（主）：同号多行按名区域指纹相似度归并，只采一篇
        match_name, match_score = None, 0.0
        if same is not None and same >= ACCOUNT_SAME_MIN:
            decision = "skip"
            reason = ("本会话已点过同一公众号（账号指纹相似度 %.3f）：列表里同号占多行"
                      % same)
        else:
            # 已采集名单匹配（次）：名单里已有 → 跳过，避免重采已知号
            match_name, match_score = identify_account(acct_region, registry)
            if match_name:
                decision = "skip"
                reason = "命中已采集名单：%s(score=%.3f)" % (match_name, match_score)
            else:
                decision = "click"
                reason = "未命中已采集名单（视为新公众号）"

        # dry-run 的"点击"记 would_click 而不是 click：journal 是去重依据
        # （processed_fingerprints 只认 click），预演绝不能把行标记成已处理，
        # 否则预演一次之后真跑会全部跳过（2026-10-23 验证者实测抓到的 bug）。
        logged_decision = ("would_click"
                           if (args.dry_run and decision == "click") else decision)

        rec = {"round": clicked + skipped, "fp": row["fp"], "algo": FP_ALGO,
               "row": row,
               "account": match_name if (decision == "skip" and match_name) else None,
               "score": round(match_score, 4),
               "same_account_sim": (round(same, 4) if same is not None else None),
               "decision": logged_decision, "reason": reason,
               "evidence": str(acct_png), "rect": rect, "page_signal": st["signal"],
               "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        with journal.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

        log("info", "scout.decide", round=clicked + skipped,
            decision=logged_decision, account=match_name, score=round(match_score, 4),
            fp=row["fp"],
            same_account_sim=(round(same, 4) if same is not None else None))

        if decision == "skip":
            skipped += 1
            # 跳过在**内存**标记已看过：否则会反复评估同一行原地打转。
            # 只进内存、不进 journal —— 跨进程重启后 skip 行应被重新评估
            # （那个号可能后来才采到），processed_fingerprints 只认 click 正是为此。
            seen.add(row["fp"])
            continue

        # 5) 点击（窗口内坐标 → 屏幕绝对坐标；节奏层控速 + 控件内随机落点）
        cx = row["click_point"][0] + rect[0]
        cy = row["click_point"][1] + rect[1]
        if acct_fp is not None:
            session_keys.append(acct_fp)
        if args.dry_run:
            log("info", "scout.would_click", abs_xy=[cx, cy])
            clicked += 1
            # 预演走内存去重：否则 --dry-run 只是把同一行重复预览 N 次。
            # 只进内存集合、不进 journal（journal 里是 would_click，
            # processed_fingerprints 不认它），预演不留跨进程状态。
            seen.add(row["fp"])
            continue
        _before_write()
        _write_gap()
        jx, jy = _jitter_xy(cx, cy, 5)
        vision.click_at(jx, jy)
        clicked += 1
        # 内存集合同步更新：否则第 2 轮会把刚点过的同一行再点一次
        # （列表不会因为点开文章就消失，行还在最上方）。
        seen.add(row["fp"])
        log("info", "scout.clicked", abs_xy=[cx, cy], jittered=[jx, jy])

        # 6) 先离页再认页（D3）：等列表信号消失 → 回列表 → 等信号恢复
        left = vision.wait_until(_page_pred(win["hwnd"], False),
                                 timeout=args.open_timeout, poll=0.25)
        if not left:
            log("warn", "scout.not_left",
                hint="点击后列表页信号没消失（可能没点开）；不重试点，避免重复打开同一篇")
            snap = _capture(win["hwnd"])
            vision.save(snap[0] if snap else img, OUT / "scout-not-left.png")
            continue
        log("info", "scout.article_opened")
        _nap(args.settle)

        # 6b) 链接采集（最佳档）：文章打开后、回列表前，复制本号一篇真实 URL
        if args.collect_links:
            link = _collect_account_link(win, args)
            if link:
                biz = link["__biz"]
                if biz and biz in collected_biz:
                    log("info", "link.dedup", __biz=biz,
                        hint="本号链接已采集，跳过重复写入")
                else:
                    row_out = {
                        "name": match_name or "",
                        "__biz": biz or "",
                        "article_url": link["article_url"],
                        "fingerprint": (acct_fp.tobytes().hex()
                                        if acct_fp is not None else row["fp"]),
                        "evidence": acct_png.name,
                        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    }
                    _append_csv(links_path, row_out, _LINKS_FIELDS)
                    if biz:
                        collected_biz.add(biz)
                    log("info", "link.collected", name=row_out["name"],
                        __biz=biz, article_url=link["article_url"][:90])
            # 复制链接若弹出了菜单但没关掉，按 Esc 关掉，避免遮挡后续回列表
            vision.key_tap(vision._VK_ESCAPE)
            _nap(0.3)

        if args.return_key == "ctrlw":
            vision.close_tab()
        elif args.return_key == "altleft":
            vision.key_tap(vision._VK_LEFT, modifiers=(vision._VK_MENU,))
        elif args.return_key == "esc":
            vision.key_tap(vision._VK_ESCAPE)
        else:
            log("info", "scout.no_return", hint="return-key=none，人工返回列表页")
            break

        back = vision.wait_until(_page_pred(win["hwnd"], True),
                                 timeout=args.back_timeout, poll=0.25)
        if not back:
            log("error", "scout.return_failed", return_key=args.return_key,
                hint="回列表失败。默认 ctrlw（微信 4.x 文章页 Escape/Alt+Left 实测无效）；"
                     "若仍失败可试 --return-key altleft；已处理进度按指纹记录，"
                     "人工返回列表页后重跑不会重复点")
            snap = _capture(win["hwnd"])
            vision.save(snap[0] if snap else img, OUT / "scout-return-failed.png")
            return EXIT_PARTIAL if (clicked + skipped) > 1 else EXIT_ERROR
        log("info", "scout.back_on_list")
        _nap(0.5)

    log("info", "scout.summary", clicked=clicked, skipped=skipped,
        traversed=args.traverse)
    return EXIT_OK if (clicked + skipped) else EXIT_PARTIAL


def _ink_mask(im):
    """灰度墨迹二值图（1=墨）。阈值与 vision 的文字带检测同源，避免两套口径。"""
    g = np.asarray(im.convert("L"))
    return (g < vision._INK_THR).astype(np.float32)


def _tight(m):
    """裁到墨迹外接框；无墨返回 None。"""
    ys, xs = np.where(m > 0)
    if not len(ys):
        return None
    return m[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def _col_profile(im, bins: int = _PROFILE_BINS):
    """「文字墨迹的列投影」指纹：宽度归一到 bins 格、去均值、L2 归一。

    为什么不用像素模板匹配：实测同一段文字自匹配只有 0.31，无关名也有
    0.21~0.31——**区分度几乎为零**（灰细字 + 字体渲染差异把相关分压平了）。
    列投影只看「每一列有多少墨」，对字体/字重/抗锯齿不敏感，实测自匹配
    0.76~0.82、无关名 ≤0.44，余量从 0.03 提到 0.3 以上。
    """
    t = _tight(_ink_mask(im))
    if t is None or t.shape[1] < 8 or t.shape[0] < 6:
        return None
    p = t.sum(axis=0).reshape(1, -1).astype(np.float32)
    p = cv2.resize(p, (bins, 1))[0]
    p = p - p.mean()
    n = float(np.linalg.norm(p))
    return p / n if n > 1e-6 else None


# ---------------------------------------------------------------------------
# 链接采集（最佳档：2026-10-29 新增）
# 目的：点开文章后，从文章页右上角「...」菜单「复制链接」取一篇该号真实 URL
#       （含 __biz），按 __biz 去重写入 account_links.csv，供 favorites_chain
#        批量下载全号历史文章。仅 --collect-links 开启时触发，默认不干扰原采集。
# 依赖：微信文章页「...」菜单坐标（相对窗口右上角偏移，可标定）；剪贴板读 CF_UNICODETEXT。
#   无 OCR / 无 pywin32 依赖：剪贴板用 ctypes 零依赖读取。
# ---------------------------------------------------------------------------
_LINK_URL_RE = re.compile(r'https?://[^\s"\'<>]+')
_BIZ_RE = re.compile(r'__biz=([A-Za-z0-9=]+)')
_LINKS_FIELDS = ["name", "__biz", "article_url", "fingerprint", "evidence", "ts"]


def _read_clipboard_text() -> str | None:
    """读剪贴板 CF_UNICODETEXT。委托 clipboard.py（已实机验证的 GlobalLock 方案）。

    旧实现直接把 GetClipboardData 返回的 HGLOBAL 句柄当指针传给 wstring_at，
    64 位下句柄未设 restype=c_void_p 会被截断、且缺 GlobalLock，导致
    "access violation reading 0xFFFFFFFF..."。这里统一走 clipboard.read_text()。
    """
    try:
        return clipboard.read_text()
    except Exception as e:
        log("warn", "clipboard.read_failed", err="%s: %s" % (type(e).__name__, e))
        return None


def _clear_clipboard() -> None:
    try:
        clipboard.clear()
    except Exception:
        pass


def _parse_link(text: str):
    """从剪贴板文本抽 (article_url, __biz)；抽不到返回 (None, None)。"""
    if not text:
        return None, None
    urls = _LINK_URL_RE.findall(text)
    for u in urls:
        if "mp.weixin.qq.com" in u:
            m = _BIZ_RE.search(u)
            return u, (m.group(1) if m else None)
    return None, None


def _append_csv(path: Path, row: dict, fieldnames) -> None:
    """追加一行（utf-8-sig 带 BOM，便于 Excel 打开中文）。文件不存在则先写表头。"""
    write_header = not path.exists()
    import csv as _csv
    with path.open("a", encoding="utf-8-sig", newline="") as f:
        w = _csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            w.writeheader()
        w.writerow(row)


def _load_collected_biz(path: Path) -> set[str]:
    """从已有 account_links.csv 读回已采集 __biz，做跨次运行去重。"""
    biz: set[str] = set()
    if not path.exists():
        return biz
    import csv as _csv
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            for r in _csv.DictReader(f):
                b = (r.get("__biz") or "").strip()
                if b:
                    biz.add(b)
    except Exception as e:
        log("warn", "link.load_failed", err="%s: %s" % (type(e).__name__, e))
    return biz


# --------------------------------------------------- 链接采集：模板定位（复用 favorites_chain 已实机验证的模板）
# 用 templates/wechat-more.png（⊙ 更多按钮）与 wechat-copy-link.png（菜单项）做模板匹配，
# **绝不硬编码坐标**：文章标签标题长度变化时 ⊙ 的 x 会跟着平移（favorites_chain 已实机
# 验证），硬编码绝对坐标必失准——早期 7 次标定失败的根因正是 more_x=2330 这种写法。
_TPL_DIR = Path(__file__).resolve().parents[1] / "templates"
_MORE_TPL = "wechat-more.png"
_COPY_TPL = "wechat-copy-link.png"
_MORE_THRESHOLD = 0.85
_COPY_THRESHOLD = 0.80
_MORE_FALLBACK = (997, 44)   # 模板失配兜底（标题恰好那个长度时的实测值）；仅兜底，非坐标真值
_NEEDLE_CACHE: dict = {}


def _needle(name: str):
    """按需加载模板图（缓存：一篇要匹配多次，别每次读盘）。"""
    img = _NEEDLE_CACHE.get(name)
    if img is None:
        img = vision.Image.open(str(_TPL_DIR / name))
        _NEEDLE_CACHE[name] = img
    return img


def _locate_more(img) -> tuple[int, int] | None:
    """在文章页截图定位标签栏「⊙」(更多) 按钮中心；找不到返回 None。

    多命中取最高分；多个文章 tab 同时开时"哪个 ⊙ 是当前页"模板本身回答不了，
    由调用方记日志留证据（与 favorites_chain.more_point 同策略）。
    """
    try:
        hits = vision.match_template(img, _needle(_MORE_TPL), _MORE_THRESHOLD, max_n=5)
    except Exception as e:
        log("warn", "link.more_match_failed", err="%s: %s" % (type(e).__name__, e))
        return None
    if not hits:
        return None
    m = hits[0]
    return m.x + m.w // 2, m.y + m.h // 2


def _locate_copy_link(img) -> tuple[int, int] | None:
    """在（已弹出菜单的）截图里定位「复制链接」菜单项中心；找不到返回 None。

    坑：绝不用"从菜单顶往下数第 N 行"——菜单项顺序/数量会变，「复制链接」上方
    紧邻「刷新」，数错会点到刷新（页面重载，看起来什么都没发生）。
    """
    try:
        hits = vision.match_template(img, _needle(_COPY_TPL), _COPY_THRESHOLD, max_n=3)
    except Exception as e:
        log("warn", "link.copy_match_failed", err="%s: %s" % (type(e).__name__, e))
        return None
    if not hits:
        return None
    m = hits[0]
    return m.x + m.w // 2, m.y + m.h // 2


def _collect_account_link(win, args):
    """点文章页标签栏「⊙」→ 弹菜单 → 点「复制链接」→ 读剪贴板 → 解析 __biz。

    返回 dict(article_url, __biz) 或 None。
    定位全部走模板匹配（见 _locate_more / _locate_copy_link），与 favorites_chain
    的 copy_article_link 同一套已验证逻辑，只是把产出收敛成 account_links.csv。
    """
    cap = _capture(win["hwnd"])
    if not cap:
        log("warn", "link.capture_failed", hint="文章页截图失败，跳过链接采集")
        return None
    art_img, art_rect = cap
    vision.save(art_img, OUT / "scout-article.png")  # 标定用：文章页原图

    more = _locate_more(art_img)
    if more is None:
        mx, my, fb = _MORE_FALLBACK[0], _MORE_FALLBACK[1], True
        log("warn", "link.more_fallback", xy=[mx, my],
            hint="wechat-more.png 未命中（阈值 %s）：退回兜底坐标，若持续出现请重跑 "
                 "capture_templates.py" % _MORE_THRESHOLD)
    else:
        mx, my, fb = more[0], more[1], False
    log("info", "link.more_located", xy=[mx, my], fallback=fb)

    jx, jy = _jitter_xy(art_rect[0] + mx, art_rect[1] + my, 3)
    vision.click_at(jx, jy)
    _nap(1.0)  # 等菜单弹出（CEF 渲染有帧延迟；favorites_chain._menu_wait 同值）

    snap = _capture(win["hwnd"])
    if snap:
        vision.save(snap[0], OUT / "scout-link-menu.png")  # 标定用：菜单图
    copy = _locate_copy_link(snap[0]) if snap else None
    if not copy:
        log("warn", "link.copy_menu_missing", more_xy=[mx, my],
            hint="菜单里没找到「复制链接」：多半是菜单没弹出来。Esc 收起，本轮跳过（下一轮重试）")
        vision.key_tap(vision._VK_ESCAPE)
        _nap(0.4)
        return None
    cx, cy = copy
    log("info", "link.copy_located", xy=[cx, cy])

    _clear_clipboard()
    jcx, jcy = _jitter_xy(art_rect[0] + cx, art_rect[1] + cy, 3)
    vision.click_at(jcx, jcy)

    # 轮询剪贴板直到出现微信文章链接（含 __biz）
    url = biz = None
    deadline = time.time() + args.link_timeout
    while time.time() < deadline:
        txt = _read_clipboard_text()
        if txt:
            u, b = _parse_link(txt)
            if u:
                url, biz = u, b
                break
        _nap(0.3)
    if not url:
        log("warn", "link.not_found",
            hint="剪贴板未取到微信文章链接；请核对菜单是否真弹出（参考 scout-link-menu.png）")
        return None
    return {"article_url": url, "__biz": biz}


def account_key(region):
    """账号区域的列投影指纹（未知号也能比），无墨迹返回 None。

    为什么不复用 registry 名字：识别命中意味着"名单里已有"，那种情况本来
    就 skip；真正要挡的是"同一个**未知**号在列表里占多行"——第一行点了，
    第二行的名字还没进名单（下载侧尚未落盘），按名字根本比不出来。
    指纹能比：同号两行的灰色小字完全同源，实测自匹配 0.76~0.82、
    不同号 ≤0.44，故 ACCOUNT_SAME_MIN 取 0.85 足以判"同一段文字"。
    """
    return _col_profile(region)


def account_score(region, name: str) -> float | None:
    """区域与某个候选名的最优相似分（多字号取最大）。无可比模板时返回 None。"""
    rp = _col_profile(region)
    if rp is None:
        return None
    best = None
    for tpl in render_account(name):
        tp = _col_profile(tpl)
        if tp is None:
            continue
        s = float((rp * tp).sum())
        if best is None or s > best:
            best = s
    return best


def identify_account(region, registry: set[str]) -> tuple[str | None, float]:
    """把公众号名区域与已采集名单逐一比对，返回 (命中名 or None, 最高分)。

    为什么用模板而不是 OCR：环境里没有 OCR 二进制，Windows 内置 WinRT OCR
    又因安全策略禁止运行时加载程序集而不可用（见 probe_wechat.py）。候选集
    是**已知且很小**的（已采集名单），所以"渲染候选 → 比指纹"是零依赖替代。

    判定规则（两道闸门，任一不满足都返回 None ＝ 当成新号去点）：
      ① 最高分 ≥ IDENTIFY_THRESHOLD；
      ② 最高分 − 第二名 ≥ IDENTIFY_MARGIN。

    ② 是必须的：2026-10-23 实测「宠物食品联盟」与「宠物食品商情」前四个字
    相同，两者 fingerprint 分只差 0.008，甚至可能错误名字反超（逐字单元
    方案实测 0.7691 vs 0.7610）。没有余量闸门就会**把新号误判成已采集而
    漏采**——这比多点一次严重得多。宁可能力弱，不可判错。
    """
    if region is None or region.width <= 0 or not registry:
        return None, 0.0
    scored = []
    for name in sorted(registry):
        s = account_score(region, name)
        if s is not None:
            scored.append((s, name))
    if not scored:
        print("[scout] 账号区域无可比墨迹（%dx%d），账号识别跳过"
              % (region.width, region.height), file=sys.stderr)
        return None, 0.0
    scored.sort(reverse=True)
    best_score, best_name = scored[0]
    second = scored[1][0] if len(scored) > 1 else 0.0
    if best_score < IDENTIFY_THRESHOLD:
        return None, best_score
    if best_score - second < IDENTIFY_MARGIN:
        print("[scout] 账号识别余量不足：%s=%.3f 与 %s=%.3f 差 %.3f < %.2f，判未知"
              % (best_name, best_score, scored[1][1], second,
                 best_score - second, IDENTIFY_MARGIN), file=sys.stderr)
        return None, best_score
    return best_name, best_score


_FONT_CACHE: dict[int, object] = {}
_FONT_PATHS = ("msyh.ttc", "C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttc",
               "C:/Windows/Fonts/Microsoft YaHei.ttc")

# 公众号名的配色与字号全部来自实测（out/wx-fav-clean.png，1649×1518）：
#   底色灰度 250（不是纯白 255）、字号灰度 160（整带 0 个 <100 的深墨像素）、
#   字高 20px（y253-272）、6 字宽 124px ⇒ 字号 ≈ 20。
# 字号档位必须**盖住实测值**：旧代码只渲染 14~18，而真实字是 20，模板偏小
# 且高 34px > 区域 26px，导致 score 恒 0.0。
_ACCT_SIZES = (14, 16, 18, 20, 22)
_ACCT_FG = (160, 160, 160)
_ACCT_BG = (250, 250, 250)


def _font(size: int):
    from PIL import ImageFont
    if size not in _FONT_CACHE:
        for p in _FONT_PATHS:
            try:
                _FONT_CACHE[size] = ImageFont.truetype(p, size)
                break
            except Exception:
                continue
        else:
            _FONT_CACHE[size] = None
    return _FONT_CACHE[size]


def render_account(name: str, sizes=_ACCT_SIZES):
    """把公众号名渲染成灰度小字图，用作匹配模板（多字号各一份）。

    模板高度必须**小于**账号区域高度，否则 matchTemplate 无解（见
    identify_account）。所以这里只留 2px 边距：h = size + 4。
    底色/字色用实测值（250 / 160），减少与真实截图的整体亮度差。
    """
    from PIL import Image, ImageDraw
    outs = []
    for size in sizes:
        f = _font(size)
        if f is None:
            continue
        w = int(len(name) * size * 1.15) + 8
        h = size + 4
        img = Image.new("RGB", (w, h), _ACCT_BG)
        ImageDraw.Draw(img).text((2, 1), name, fill=_ACCT_FG, font=f)
        outs.append(img)
    return outs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="微信「赞和收藏」逐篇发现（scout）")
    ap.add_argument("--download-root", default=str(DEFAULT_DOWNLOAD_ROOT),
                    help="已采集公众号的判定依据：下载根目录")
    ap.add_argument("--max-rounds", type=int, default=1,
                    help="本轮最多处理几篇（默认 1，符合「每轮仅点击一篇」的约定）")
    ap.add_argument("--settle", type=float, default=2.0,
                    help="点击后等文章页打开的基准秒数（节奏层会在此基础上加长）")
    ap.add_argument("--dry-run", action="store_true", help="只决策不点击")
    ap.add_argument("--scroll", type=int, default=0,
                    help="扫描前向下滚几格（走完整列表时用；默认 0 不滚）")
    ap.add_argument("--traverse", action="store_true",
                    help="采全表：自动向下滚动覆盖所有文章，并以「连续 2 轮可见区 0 新增」"
                         "收敛判停（解决点赞重排导致的漏采/重采）。需配合较大的 --max-rounds")
    ap.add_argument("--scroll-step", type=int, default=3,
                    help="--traverse 时每次向下滚动的格数（默认 3）")
    ap.add_argument("--return-key", choices=("ctrlw", "esc", "altleft", "none"),
                    default="ctrlw",
                    help="点击文章后怎么回列表（默认 ctrlw＝关闭文章 tab；"
                         "微信 4.x 文章页 Escape/Alt+Left 实测无效）")
    ap.add_argument("--open-timeout", type=float, default=8.0,
                    help="等文章页打开（列表信号消失）的最长秒数")
    ap.add_argument("--back-timeout", type=float, default=8.0,
                    help="等返回列表页（列表信号恢复）的最长秒数")
    ap.add_argument("--collect-links", action="store_true",
                    help="最佳档：点开文章后复制本号一篇真实 URL（含 __biz）写入 "
                         "account_links.csv，供 favorites_chain 批量下载全号历史")
    ap.add_argument("--link-timeout", type=float, default=6.0,
                    help="点复制链接后轮询剪贴板的最长秒数（--collect-links 用）")
    args = ap.parse_args(argv)
    if args.max_rounds < 1:
        print("--max-rounds 必须 ≥1", file=sys.stderr)
        return EXIT_PARAM
    # --traverse 采全表时，停止由"收敛判停"控制，--max-rounds 退化为安全上限；
    # 用户若未显式给上限（仍默认 1），抬高到足够大的值，避免一轮就停。
    if args.traverse and args.max_rounds == 1:
        args.max_rounds = 9999
    try:
        return run(args)
    except Exception as e:
        log("error", "scout.unexpected", err="%s: %s" % (type(e).__name__, e))
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
