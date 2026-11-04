#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把一条 URL 在**微信内置浏览器**里打开：点标题栏放大镜 → 粘贴 → 回车。

为什么必须有这一步（2026-10-23 真机取证）
-----------------------------------------
下载工具的「1.获取公众号id」只负责产出 `profile_ext` 链接，然后把链接放进剪贴板
并提示「请在微信打开复制的链接」。工具随后要读微信内置浏览器的 cookie 才能
「获取密钥成功」；如果没人去打开那个链接，日志会一直刷：

    开始获取密钥...
    获取密钥失败...请先在微信打开复制的链接

用户实测（截图）给出的三步就是本脚本的实现：
    ① 复制这段链接（工具已放进剪贴板，本脚本也会自己兜底复制）
    ② 点微信标题栏右侧的放大镜（搜索）
    ③ 在「在搜一搜中搜索，或输入网址」框里粘贴网址并回车

难点与对策
----------
* 微信 4.x 是 CEF/Chromium 自绘，控件树读不到（§2.1）⇒ 只能用模板匹配找放大镜。
  模板 `templates/wechat-search.png` 是从真机标题栏裁下来的（30×29），实测窗口
  宽 1652 时放大镜中心在 (1432, 44)，**距右边缘恒为 220px** —— 模板失配时用这个
  右锚点兜底，因为标题栏按钮组是右对齐的，窗口改宽只会让 x 平移。
* 粘贴用 Ctrl+V 而不是逐字符输入：URL 里有 `=`/`&` 等字符，逐字符输入在 CEF 的
  搜索框里会被当成快捷键/被吞掉；剪贴板是唯一可靠通道。
* 打开后**不校验页面内容**（CEF 读不到文字），只报"画面是否变化"。真正的
  成功判据在调用方：下载工具的日志出现「获取密钥成功」（见 pipeline 的 key_wait）。

用法
----
    python scripts/wechat_open_url.py --from-clipboard
    python scripts/wechat_open_url.py --url "https://mp.weixin.qq.com/mp/profile_ext?..."
    python scripts/wechat_open_url.py --from-log out/tool-log.txt   # 从工具日志里抠链接
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PIL import Image  # noqa: E402

import vision  # noqa: E402

EXIT_OK, EXIT_PARAM, EXIT_ERROR, EXIT_ENV = 0, 2, 3, 6

TPL = Path(__file__).resolve().parents[1] / "templates"
# 真机实测（微信内置浏览器窗口 1652×1518，DPI 175%）：
#   标题栏右端自右向左依次是 [×] [□] [—] [•• 问AI] [🔍]，放大镜中心在 (1335, 43)，
#   即**距窗口右边缘 317px**、距顶 43px。
# 2026-10-23 更正：早先按"220px"算过一次，点到了「问AI」按钮右侧的空白，页面照样
# 变了（因为焦点没变），所以"画面变了"证明不了点对了位置 —— 必须靠模板。
# 模板命中时以模板为准；未命中才用这组常数兜底。
SEARCH_RIGHT_OFFSET = 317
SEARCH_TOP = 43
_TITLEBAR_MAX_Y = 90     # 标题栏高度上限：放大镜中心实测 43，留一倍余量
URL_RE = re.compile(r"https?://mp\.weixin\.qq\.com(?:/[^\s\"'<>）)]*)?")
# 路径可选：`https://mp.weixin.qq.com/` 本身也是合法入口（自检/兜底用）。
# URI 里出现全角右括号就当链接结束——日志里常见「（链接）」这种包裹写法。
#
# 尾部噪声集（2026-10-27 加固）：`URL_RE` 为了兼容「（链接）」包裹，只把
# \s "'<>）) 当终止符，于是链接后紧跟 。，；：！？ 等中文标点时会被**多吞**进 URL
# （链接失效、工具永远「获取密钥失败」）。这些字符绝不可能是微信链接的一部分
# （链接字符集是 RFC 3986 的 -._~:/?#@!$&'()*+,;=% 加字母数字），所以取出后
# 在**第一个噪声字符处截断**——既能防截断，也能防增改，密钥链接的 `__biz=...==`、
# `&scene=124`、`#wechat_redirect` 全部原样保留。
_URL_TRAILING_JUNK = "。，、；：！？…—」』》〉｝｣\u3000\t\r\n "


def _trim_url(u: str) -> str:
    """在第一个噪声字符处截断（噪声字符绝不出现在合法微信链接里）。

    不用 rstrip：over-capture 形如 `...#wechat_redirect。下次再试`，尾部噪声后面还
    跟着正文（非噪声），rstrip 遇到 `试` 就停、剥不干净。在首个噪声字符处一刀切，
    才能把 `。下次再试` 整段去掉。若链接里本就没有噪声字符，原数返回。
    """
    for i, c in enumerate(u):
        if c in _URL_TRAILING_JUNK:
            return u[:i]
    return u


def log(level: str, event: str, **fields) -> None:
    rec = {"ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "level": level, "event": event}
    rec.update(fields)
    sys.stderr.write(json.dumps(rec, ensure_ascii=False) + "\n")
    sys.stderr.flush()


# ------------------------------------------------------------------ 链接来源
def find_url_in_text(text: str) -> str | None:
    """从一段文字（工具日志/剪贴板）里取文章链接；`profile_ext` 优先。

    优先 profile_ext：工具日志里同时会出现文章链接和 profile_ext 链接，只有后者
    能让工具读到 cookie。取错了不会报错，只会一直「获取密钥失败」——所以按优先级挑。

    取出后剥掉尾部中文标点/符号噪声（见 `_URL_TRAILING_JUNK`）：既保「不被截断」，
    也保「不被增改」——密钥链接的 `__biz=...==`、`&scene=124`、`#wechat_redirect`
    全部原样保留。
    """
    urls = URL_RE.findall(text or "")
    if not urls:
        return None
    for u in urls:
        if "profile_ext" in u:
            return _trim_url(u)
    return _trim_url(urls[-1])


def clipboard_text() -> str:
    try:
        import win32clipboard

        win32clipboard.OpenClipboard()
        try:
            return str(win32clipboard.GetClipboardData())
        finally:
            win32clipboard.CloseClipboard()
    except Exception as exc:                              # 剪贴板被别的进程占住
        log("warn", "clipboard.read_failed", error=str(exc))
        return ""


def set_clipboard(text: str) -> bool:
    try:
        import win32clipboard

        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(text)
        finally:
            win32clipboard.CloseClipboard()
        return True
    except Exception as exc:
        log("error", "clipboard.write_failed", error=str(exc))
        return False


# ------------------------------------------------------------------ 定位放大镜
def find_search_icon(img, tpl_path: Path | None = None):
    """返回放大镜中心在**窗口内**的坐标 (x, y, source, score)。

    source="template" 表示模板命中；"anchor" 表示模板失效、用右锚点推算（score=None）。
    模板文件缺失时也走 anchor —— 宁可点一个几何位置，也不要直接失败。
    """
    tpl_path = Path(tpl_path or (TPL / "wechat-search.png"))
    anchor_x = max(0, img.width - SEARCH_RIGHT_OFFSET)
    if tpl_path.is_file():
        try:
            tpl = Image.open(str(tpl_path)).convert("RGB")
            score, pos = vision.best_match(img, tpl)
            if pos and score >= 0.75:
                hit_x = pos[0] + tpl.width // 2
                hit_y = pos[1] + tpl.height // 2
                # 区域守卫（真机教训）：放大镜一定在**标题栏右半部分**里。早先写的是
                # "命中点必须贴住右锚点 ±40px"，结果窗口布局一变（多了/少了「问AI」
                # 按钮）就把**正确命中**判成误匹配，退回到一个错位的兜底坐标上去。
                # 现在只守真正的不变量：落在标题栏右半、y 在标题栏高度内。
                # 这一条仍然能挡住那个静默误点——纯色画面会让 cv2 的归一化相关返回假
                # 1.0 并命中 (0,0)，那是窗口左上角，不是标题栏右侧。
                if hit_x > img.width * 0.5 and hit_y <= _TITLEBAR_MAX_Y:
                    return (hit_x, hit_y, "template", round(float(score), 4))
                log("warn", "search.template_out_of_titlebar", score=round(float(score), 4),
                    hit=[hit_x, hit_y], window=[img.width, img.height],
                    hint="命中点不在标题栏右侧，判为误匹配，改用右锚点")
            else:
                log("warn", "search.template_miss", score=round(float(score), 4),
                    hint="模板分低于 0.75，改用右锚点；换过微信版本/主题后请重裁模板")
        except Exception as exc:
            log("warn", "search.template_error", error=str(exc))
    else:
        log("warn", "search.template_missing", path=str(tpl_path))
    return (anchor_x, SEARCH_TOP, "anchor", None)


# ------------------------------------------------------------------ 主流程
def _navigate(url: str, settle: float) -> int:
    """三步走一遍：定位放大镜 → 粘贴 → 回车。返回退出码。"""
    got = vision.grab_wechat(settle=0.6, activate=True)
    if not got:
        log("error", "env.no_wechat", hint="微信未运行/被完全遮挡/最小化，先人工打开")
        return EXIT_ENV
    img, rect, win = got
    x, y, source, score = find_search_icon(img)
    log("info", "search.icon", x=x, y=y, source=source, score=score,
        window=[rect[0], rect[1], rect[2], rect[3]])
    if not set_clipboard(url):                      # 先确保剪贴板里就是这条链接
        return EXIT_ERROR
    vision.park_cursor()
    ax, ay = rect[0] + x, rect[1] + y
    # 落点护栏：这里点的是**微信**窗口，不是 clicker profile 的目标窗口，所以
    # 必须按微信 hwnd 校验（拿 profile 的 window.hwnd 来比会 100% 误报）。
    # 为什么非查不可（2026-10-26 真机事故）：鼠标点击发给坐标而非发给进程，
    # 微信被别的窗口盖住时，放大镜坐标会落到那个窗口上，日志却照样"点击成功"。
    hit = vision.window_at_point(ax, ay)
    if hit and int(hit["hwnd"]) == int(win["hwnd"]):
        pass
    elif hit and vision.window_pid(win["hwnd"]) and \
            int(hit.get("pid") or 0) == vision.window_pid(win["hwnd"]):
        # 同进程放行：微信 4.x 会把文章/搜索面板渲染成独立顶层窗口（同 pid、
        # 同类名、hwnd 不同、标题常为空）。点下去仍落在微信里，不是别的程序。
        log("info", "search.point_same_process", xy=[ax, ay],
            hit_hwnd=hit["hwnd"], hit_title=hit["title"], hit_cls=hit.get("cls", ""),
            pid=hit.get("pid"), hint="落点属于微信同进程的另一个顶层窗口，放行")
    else:
        actual = ("%r(cls=%s) hwnd=%s pid=%s" % (hit["title"], hit.get("cls", ""),
                                                 hit["hwnd"], hit.get("pid"))
                  if hit else "无法查询（WindowFromPoint 返回空）")
        log("error", "search.occluded", xy=[ax, ay], actual=actual,
            expected="%r hwnd=%s pid=%s" % (win.get("title", ""), win["hwnd"],
                                            vision.window_pid(win["hwnd"])),
            hint="放大镜落点不属于微信窗口：微信被其他进程遮挡。已拒绝点击，"
                 "请把微信露出可见区域后重试（点错窗口可能点到别的程序里）")
        return EXIT_ERROR
    if not vision.click_at(ax, ay):
        log("error", "search.click_failed", xy=[ax, ay])
        return EXIT_ERROR
    time.sleep(0.9)                                  # 搜索面板展开动画
    vision.key_tap(vision._VK_V, modifiers=(vision._VK_CTRL,))
    time.sleep(0.4)
    vision.key_tap(vision._VK_RETURN)
    time.sleep(max(0.0, settle))
    return EXIT_OK


def open_in_wechat(url: str, settle: float = 3.0, dry_run: bool = False,
                   warmup: str = "") -> int:
    """把 url 在微信内置浏览器打开。

    warmup 非空时**先导航到 warmup 再导航到 url**，用来强制制造一次真实的
    「页面加载完成」事件 —— 这不是多此一举，是工具的工作机制决定的：

        工具提示原文：「先获取公众号id，然后在微信打开复制的链接，
                       **等公众号页面加载后**，软件会自动获取密钥」

    它只认"加载完成"这个时机。如果微信当前**已经**停在该 profile_ext 页上，
    再粘贴同一条 URL 等于原地不动（实测 changed_ratio 0.0279 ≈ 没变），
    没有加载事件，密钥永远抓不到（日志只会刷「获取密钥失败...请先在微信打开
    复制的链接」）。2026-10-23 真机踩到：同样的脚本，从文章页跳过来时
    changed_ratio 0.125 → 获取密钥成功；页面已在目标页时 0.0279 → 失败。
    """
    if not URL_RE.match(url or ""):
        log("error", "url.invalid", url=(url or "")[:120],
            hint="只接受 https://mp.weixin.qq.com/... 形式的链接")
        return EXIT_PARAM
    if dry_run:
        got = vision.grab_wechat(settle=0.6, activate=True)
        if not got:
            log("error", "env.no_wechat")
            return EXIT_ENV
        img, rect, _win = got
        x, y, source, score = find_search_icon(img)
        log("info", "search.icon", x=x, y=y, source=source, score=score,
            window=[rect[0], rect[1], rect[2], rect[3]])
        log("info", "open.dry_run", url=url[:120], click=[rect[0] + x, rect[1] + y],
            warmup=warmup[:60] or None)
        return EXIT_OK

    before = None
    if warmup:
        if warmup.strip() != url.strip():
            rc = _navigate(warmup, 2.0)
            if rc != EXIT_OK:
                return rc
            log("info", "open.warmup_done", warmup=warmup[:80])
            time.sleep(1.0)

    before_shot = vision.grab_wechat(settle=0.6, activate=True)
    before = before_shot[0] if before_shot else None
    rc = _navigate(url, settle)
    if rc != EXIT_OK:
        return rc
    # 只报"画面变了没有"：CEF 读不到文字，能证明的只有"发生了跳转"。
    # 注意它**不能**证明点对了位置（点偏了页面也可能变），真正的成功判据在调用方
    # 的「获取密钥成功」。页面本来就停在目标页时这里会接近 0，那是正常现象。
    if before is not None and before_shot:
        after = vision.capture_window(hwnd=before_shot[2]["hwnd"])
        if after:
            log("info", "open.done", changed_ratio=_changed_ratio(before, after[0]),
                url=url[:120])
        else:
            log("warn", "open.no_after_shot")
    return EXIT_OK



def _changed_ratio(a, b) -> float:
    """两张同尺寸截图的差异比例（0~1）。降采样到 160 宽，避免抗锯齿噪声。"""
    try:
        import numpy as np

        w = 160
        ga = np.asarray(a.convert("L").resize((w, int(w * a.height / a.width))), dtype=np.int16)
        gb = np.asarray(b.convert("L").resize((w, int(w * b.height / b.width))), dtype=np.int16)
        h = min(ga.shape[0], gb.shape[0])
        diff = (abs(ga[:h] - gb[:h]) > 12).mean()
        return round(float(diff), 4)
    except Exception:
        return -1.0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="在微信内置浏览器打开一条公众号链接")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--url", default="", help="直接给链接")
    src.add_argument("--from-clipboard", action="store_true", help="从剪贴板取（工具已复制）")
    src.add_argument("--from-log", default="", help="从工具日志文本里抠 profile_ext 链接")
    ap.add_argument("--settle", type=float, default=3.0, help="回车后等页面加载的秒数")
    ap.add_argument("--warmup", default="",
                    help="先导航到这个同域 URL，强制制造一次真实加载（工具只认"
                         "『页面加载完成』这个时机；页面已在目标页时必须用它）")
    ap.add_argument("--dry-run", action="store_true", help="只算坐标不点")
    args = ap.parse_args(argv)

    if args.from_log:
        try:
            text = Path(args.from_log).read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            log("param", "log.unreadable", error=str(exc))
            return EXIT_PARAM
        url = find_url_in_text(text)
    elif args.from_clipboard:
        url = find_url_in_text(clipboard_text())
    else:
        url = (args.url or "").strip()
    if not url:
        log("param", "url.missing", hint="剪贴板/日志里都没有 mp.weixin.qq.com 链接")
        return EXIT_PARAM
    return open_in_wechat(url, settle=args.settle, dry_run=args.dry_run,
                          warmup=args.warmup.strip())


if __name__ == "__main__":
    sys.exit(main())
