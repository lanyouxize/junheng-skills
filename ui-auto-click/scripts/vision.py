#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""视觉能力层：截图 + 模板匹配 + 拟人输入 + 列表结构识别。

为什么需要它（2026-10-23 实机取证结论）
--------------------------------------
微信 PC 4.x 是基于 CEF/Chromium 的自绘 UI。已用**两个独立后端**验证：
  * UIA  只能看到 Chromium 框架视图（GlassBrowserFrameView / ToolbarView /
          LocationBarView）与三个原生标题按钮（最小化/恢复/关闭）；
  * MSAA(win32) 只能看到 Chrome_RenderWidgetHostHWND → Intermediate D3D Window。
真实界面（个人中心 / 赞和收藏 / 文章列表）对两者都不可见，也没有调试端口。
⇒ 唯一可行的是「截图 + 图像匹配 + 坐标点击」，即 RPA 社区对 4.x 的通用路线。

依赖只用环境里已有的：pillow（截图）、opencv-python-headless（匹配）、numpy。
**不引入任何新第三方包**（OCR 引擎受阻的原因见 scripts/probe_wechat.py）。

截图必须用 ImageGrab 屏幕区域捕获，**不能用 PrintWindow**：
2026-10-23 实测 PrintWindow/BitBlt 对微信这种 Chromium + GPU 合成窗口
返回**全黑**（WM_PRINT 拿不到 DWM 合成后的内容）。

模块边界（2026-10-23 模块化收敛）
--------------------------------
本文件只放**与具体页面无关**的通用能力：窗口枚举、屏幕捕获、模板匹配、
输入注入、列表行检测、内容指纹。页面语义（赞和收藏页判据、已采集名单、
点击决策）全部在 wechat_favorites.py。
所有 GUI 脚本统一走 grab_wechat() 一个入口拿「干净截图」——在此之前
probe_shot / probe_restore / probe_rows / capture_templates / wechat_favorites
五个脚本各写了一遍「找窗口 → 置前 → 截图 → 判空」，改一处漏四处。
（probe_shot / probe_restore 这两个一次性取证脚本已归档到 out/diag/，
与 probe_wechat.py 为邻；它们会覆盖 out/wx-main.png 等共享证据图。）
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path

import cv2
import numpy as np
import win32gui
from PIL import Image, ImageGrab, ImageDraw


# ---------------------------------------------------------------- DPI 感知
# 多显示器混用不同缩放时，后台进程默认 DPI Unaware：GetWindowRect 返回的是
# **逻辑坐标**，而 SendInput 的 MOUSEEVENTF_ABSOLUTE 要**归一化物理坐标**，
# 两者差一个缩放因子，点击就会整体偏移（影刀/八键君社区实测的高发坑）。
# 解法：进程入口设 PER_MONITOR_AWARE_V2 + 一次光标自检。
def ensure_dpi_aware() -> bool:
    """设本进程为 PER_MONITOR_AWARE_V2（失败逐级回退）。返回自检是否通过。

    每个入口脚本 import vision 时就会调用一次（系统只认第一次设置，幂等）。
    测试可设 UIAC_NO_DPI_AWARE=1 跳过。
    """
    if os.environ.get("UIAC_NO_DPI_AWARE") == "1" or sys.platform != "win32":
        return False
    try:
        import ctypes
        u = ctypes.windll.user32
        # SetProcessDpiAwarenessContext((DPI_AWARENESS_CONTEXT)-4)
        # -4 = PER_MONITOR_AWARE_V2；-3 = PER_MONITOR_AWARE
        if u.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            pass
        elif u.SetProcessDpiAwarenessContext(ctypes.c_void_p(-3)):
            pass
        else:
            try:  # shcore.SetProcessDpiAwareness(2) = 每监视器感知
                ctypes.windll.shcore.SetProcessDpiAwareness(2)
            except Exception:
                u.SetProcessDpiAware()  # 最老的 API，至少系统级感知
        return _dpi_selfcheck()
    except Exception:
        return False


def _dpi_selfcheck() -> bool:
    """光标自检：SetCursorPos(0,0) 后读回应一致；用完恢复原位不留副作用。"""
    try:
        import ctypes
        u = ctypes.windll.user32

        class _P(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        before = _P()
        u.GetCursorPos(ctypes.byref(before))
        u.SetCursorPos(0, 0)
        after = _P()
        u.GetCursorPos(ctypes.byref(after))
        ok = (after.x, after.y) == (0, 0)
        u.SetCursorPos(before.x, before.y)
        return ok
    except Exception:
        return False


ensure_dpi_aware()


@dataclass
class Match:
    x: int
    y: int
    w: int
    h: int
    score: float

    def to_dict(self) -> dict:
        return asdict(self)


def to_cv(img):
    """PIL Image → OpenCV BGR ndarray。"""
    arr = np.array(img.convert("RGB"))
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def to_pil(arr) -> Image:
    return Image.fromarray(cv2.cvtColor(arr, cv2.COLOR_BGR2RGB))


def capture_screen() -> Image:
    return ImageGrab.grab(all_screens=True)


def find_windows(title_regex: str = "", classes=None) -> list[dict]:
    """枚举顶层窗口，返回 [{hwnd, cls, title, rect, iconic}]。

    rect 用 win32gui.GetWindowRect 而不是 pywinauto 的 rectangle()：
    后者对**最小化**窗口返回 (0,0,0,0)，会把候选直接过滤掉，导致
    "微信被最小化"和"微信没开"无法区分（2026-10-23 实测踩到）。
    iconic=True 表示最小化，此时 rect 通常是 (-32000,-32000,…)。
    """
    from pywinauto import Desktop
    out = []
    rx = re.compile(title_regex) if title_regex else None
    for w in Desktop(backend="uia").windows():
        try:
            t = (w.window_text() or "").replace("\n", " ")
            c = w.class_name() or ""
        except Exception:
            continue
        if rx and not rx.search(t):
            continue
        if classes and c not in classes:
            continue
        try:
            h = w.handle
            out.append({"hwnd": h, "cls": c, "title": t,
                        "rect": list(win32gui.GetWindowRect(h)),
                        "iconic": bool(win32gui.IsIconic(h))})
        except Exception:
            pass
    return out


# 微信 PC 4.x 窗口识别（运行时枚举取证 + chain_run7 实机纠错结论）：
#   * 主窗口外壳 = Qt51514QWindowIcon（标题「微信」）；
#   * 内置 CEF 视图（收藏列表 / 文章阅读）= Chrome_WidgetWin_0（标题通常「微信」，
#     文章视图也可能是独立顶层窗、标题为空，但**同进程**）；
#   * 下载工具 = Mywindow（标题「微信公众号文章批量下载工具…」）；
#   * WorkBuddy / Edge 等 = Chrome_WidgetWin_1；
#   * 飞书会议 = Chrome_WidgetWin_0（标题「飞书会议」）—— 与微信 CEF 视图**同类名**！
#
# 关键坑（chain_run4 / chain_run7 两次实机事故）：
#   · chain_run4：旧白名单 Chrome_WidgetWin_0/1 + max(area) → 把最大化的 WorkBuddy
#     (Chrome_WidgetWin_1) 当微信，截到 WorkBuddy 界面。
#   · chain_run7：仅按类名（Chrome_WidgetWin_0）仍不够 —— 飞书会议同样是
#     Chrome_WidgetWin_0（标题「飞书会议」），一旦最大化，max(area) 又会误选飞书。
#   ⇒ 仅凭类名不可靠，最终判别必须叠加「标题精确==微信」+「同进程 pid」双保险
#     （见 wechat_windows()）。WECHAT_CLASSES 只是初筛，不作为唯一判据。
WECHAT_CLASSES = ("Qt51514QWindowIcon", "Chrome_WidgetWin_0")

# 最小化窗口的 GetWindowRect 返回值形如 (-32000,-32000,-31724,-31955)：
# Windows 把最小化窗口挪到屏幕外这个哨兵位置，坐标不是真实几何。
MINIMIZED_SENTINEL = -10000


def is_sentinel_rect(rect) -> bool:
    """rect 是否为"最小化哨兵"（左上角跑到 -10000 以外）。

    判据只看 left/top：正常窗口起点不可能为负一万（多显示器虚拟桌面也用不到），
    而最小化窗口恒为 -32000。宽高正常的负坐标虚拟屏（如 x=-1920）不受影响。
    """
    return rect[0] <= MINIMIZED_SENTINEL or rect[1] <= MINIMIZED_SENTINEL


def window_at_point(x: int, y: int) -> dict | None:
    """屏幕坐标 (x, y) 处**真正会收到鼠标事件**的顶层窗口；取不到返回 None。

    为什么必须有这个函数（2026-10-26 真机事故）：鼠标点击是"发给屏幕坐标"的，
    与焦点、与调用方的意图全无关系。当时「微信公众号文章批量下载工具」被
    `Wise Care 365` 完全盖住，脚本按 UIA 算出的坐标点下去，**三次点击全部落进了
    Wise Care 365**（一个系统清理工具），而日志照样写"已鼠标点击"——假成功。
    只查 GetForegroundWindow 挡不住这种情况（前台与 z 序可以不同），必须问系统
    "这个像素上是谁"。

    WindowFromPoint 命中子控件/内部句柄时，用 GetAncestor(GA_ROOT) 归到顶层，
    否则每次都要为"子窗口算不算目标窗口"再判一次、且极易判错。

        返回 {"hwnd", "pid", "title", "cls", "rect"}；任何异常（坐标越界、窗口刚销毁、
    无桌面访问权限）都返回 None —— 调用方必须把 None 当"无法证明安全"，
    按 fail-closed 处理（拒绝点击），不要当成"没窗口所以可以点"。

    `pid` 是 2026-10-26 补的：微信 4.x 会把文章内容渲染成**独立的顶层窗口**
    （同一个进程、同一个 `Chrome_WidgetWin_0` 类名，但 hwnd 不同、标题可能为空）。
    只看 hwnd 相等会把"点进微信自己的另一个窗口"误判成"点进别的程序"，
    所以调用方需要 pid 来判断"是不是同一个应用"。
    """
    try:
        hwnd = win32gui.WindowFromPoint((int(round(x)), int(round(y))))
        if not hwnd:
            return None
        GA_ROOT = 2
        root = int(win32gui.GetAncestor(hwnd, GA_ROOT) or hwnd)
        try:
            import win32process

            _, pid = win32process.GetWindowThreadProcessId(root)
        except Exception:
            pid = 0
        return {
            "hwnd": root,
            "pid": int(pid or 0),
            "title": win32gui.GetWindowText(root) or "",
            "cls": win32gui.GetClassName(root) or "",
            "rect": list(win32gui.GetWindowRect(root)),
        }
    except Exception:
        return None


def window_pid(hwnd: int) -> int:
    """窗口所属进程 pid；取不到返回 0。

    与 `window_at_point()["pid"]` 同源，避免调用方各自拼一遍 ctypes/pywin32
    （两套实现迟早漂移，而判据漂了直接决定"放行还是拒绝"）。
    """
    try:
        import win32process

        _, pid = win32process.GetWindowThreadProcessId(int(hwnd))
        return int(pid or 0)
    except Exception:
        return 0


def is_iconic(hwnd: int) -> bool:
    """hwnd 是否处于最小化。单次 API 调用，不枚举窗口，可在轮询里用。"""
    try:
        return bool(win32gui.IsIconic(hwnd))
    except Exception:
        return False


def wechat_windows() -> list[dict]:
    """微信 PC 4.x 主窗口候选（种子标题 + 同进程 pid 双保险）。

    判别策略（2026-10-29 chain_run7 实机纠错后定稿）：
      ① 先找「种子」窗口：类名 ∈ WECHAT_CLASSES 且**标题精确 == "微信"**。
         飞书会议(Chrome_WidgetWin_0, 标题"飞书会议")、WorkBuddy/Edge(Chrome_WidgetWin_1)、
         下载工具(Mywindow, 标题"微信公众号文章批量下载工具…") 全部被排除；
         仅微信自己的主窗/CEF 视图命中。
      ② 用种子窗口的 pid 反查**同进程**的所有 WECHAT_CLASSES 顶层窗口。
         微信 4.x 把文章阅读渲染成「同进程、同 Chrome_WidgetWin_0 类、标题可能为空」
         的独立顶层窗口，pid 一致即可一并纳入，避免漏掉文章视图；同时因 pid 不同，
         飞书/WorkBuddy 等其它进程的同名类窗口被彻底隔离。
      ③ 找不到种子 → 返回 [](fail-closed)，绝不回退到「类名即可」，否则会误选飞书。

    为什么不能只按类名（chain_run7 实证）：飞书会议也是 Chrome_WidgetWin_0，
    仅凭类名 + max(area) 在飞书最大化时必然误选飞书；叠加标题 + pid 后唯一命中微信。
    """
    seeds = find_windows(title_regex="^微信$", classes=WECHAT_CLASSES)
    if not seeds:
        return []
    pid = window_pid(seeds[0]["hwnd"])
    if not pid:
        return seeds
    same_pid = [w for w in find_windows(classes=WECHAT_CLASSES)
                if window_pid(w["hwnd"]) == pid]
    return same_pid or seeds


def wechat_window() -> dict | None:
    """挑微信「收藏列表所在」的窗口。

    候选来自 wechat_windows()（WECHAT_CLASSES 白名单：Qt51514QWindowIcon +
    Chrome_WidgetWin_0），已排除 WorkBuddy/下载工具等。

    选窗优先级（2026-10-29 运行时取证校正）：
      ① 可见 + Chrome_WidgetWin_0（CEF 内容视图，收藏列表/文章真正渲染在这里，
         实测其截图 page_state ok=True；而 Qt 主窗常处于最小化，截到的是哨兵
         区域、page_state 落入误判区）；
      ② 可见 + Qt51514QWindowIcon（主窗外壳，最小化时不可用）；
      ③ 最小化 + Chrome_WidgetWin_0（交给 activate_window 去 restore）；
      ④ 最小化 + Qt51514QWindowIcon；⑤ 都没有 → None。

    可见性优先于类名：绝不在有可见候选时去选一个最小化的窗口（最小化窗口
    GetWindowRect 是 -32000 哨兵，截出来是桌面角落，曾导致"截到桌面当微信"）。
    """
    ws = wechat_windows()
    if not ws:
        return None

    def _area(w):
        return (w["rect"][2] - w["rect"][0]) * (w["rect"][3] - w["rect"][1])

    CONTENT = "Chrome_WidgetWin_0"      # 真正渲染收藏列表/文章的 CEF 视图
    MAIN = "Qt51514QWindowIcon"         # 微信外壳（可能最小化）
    visible = [w for w in ws if not w["iconic"]]
    # 候选池：可见优先；可见集为空才用全量（含最小化）。
    for pool in ((visible, ws) if visible else (ws,)):
        content = [w for w in pool if w["cls"] == CONTENT]
        if content:
            return max(content, key=_area)
        main = [w for w in pool if w["cls"] == MAIN]
        if main:
            return max(main, key=_area)
    return None


def grab_wechat(settle: float = 0.6, activate: bool = True):
    """**唯一**的「拿一张干净的微信截图」入口：找窗口 → 置前 → 截图 → 判空。

    返回 (img, rect, win_dict)；任何一步不满足返回 None。
    置前失败**不**算致命（坐标点击只要求窗口不被遮挡），由调用方用页面
    判据兜底；判据不过才是真失败。
    """
    w = wechat_window()
    if not w:
        return None
    if activate:
        try:
            activate_window(w["hwnd"], settle)
        except Exception:
            pass
    got = capture_window(hwnd=w["hwnd"])
    if not got or is_blank(got[0]):
        return None
    return got[0], got[1], w


def capture_window(hwnd: int = 0, title_regex: str = ""):
    """截窗口。hwnd 优先；否则按 title_regex 找第一个。

    返回 (PIL.Image, (l, t, r, b))；失败返回 None。
    最小化窗口一律返回 None（rect 是 (-32000,-32000,…) 哨兵，截出来是
    屏幕左上角一块无关区域，曾导致"截到桌面却当成微信"）。
    """
    if not hwnd:
        if title_regex:
            wins = find_windows(title_regex)
            if not wins:
                return None
            hwnd = wins[0]["hwnd"]
        else:
            w = wechat_window()
            if not w:
                return None
            hwnd = w["hwnd"]
    l, t, r, b = win32gui.GetWindowRect(hwnd)
    if is_sentinel_rect((l, t, r, b)):
        return None
    if r - l <= 0 or b - t <= 0:
        return None
    # 屏幕区域捕获（见模块 docstring：PrintWindow 会拿到全黑）
    img = ImageGrab.grab(bbox=(l, t, r, b), all_screens=True)
    return img, (l, t, r, b)


def is_blank(img: Image, thresh: float = 0.985) -> bool:
    """判断截图是否几乎全黑/全白（窗口被遮挡时的兜底判据）。"""
    a = to_cv(img)
    if a.size == 0:
        return True
    g = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY)
    hist = cv2.calcHist([g], [0], None, [16], [0, 256]).flatten()
    return float(hist.max() / g.size) >= thresh


def wait_until(predicate, timeout: float = 5.0, poll: float = 0.25) -> bool:
    """轮询直到 predicate() 为真或超时。返回是否成功。

    「先离开旧页、再认新页」的时序基础：页面切换是异步的，点完立刻截图
    看到的往往还是旧页，必须等状态真正翻转再判断（2026-10-23 设计约束）。
    """
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        try:
            if predicate():
                return True
        except Exception:
            pass  # 判据本身炸了（如截图失败）按「还没到位」继续等
        if time.monotonic() >= deadline:
            return False
        time.sleep(poll)


# ---------------------------------------------------------------- 模板匹配
def _edges(bgr):
    """Canny 边缘图：把「灰度/主题差异」转成「结构形状」差异。

    微信深浅色主题切换后同一按钮的灰度完全变了，但形状不变；边缘匹配
    因此对主题免疫（2026-10-23 联网调研结论，影刀社区同款用法）。
    """
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    return cv2.Canny(g, 60, 160)


def match_template(hay, needle, threshold: float = 0.85, max_n: int = 20,
                   edge: bool = False) -> list[Match]:
    """在 hay 里找 needle，返回按分数降序的去重命中列表。

    去重用 NMS：同一目标周围常连续高分，不去重会数出十几个"按钮"。
    edge=True 时两边都先转 Canny 再比（对主题/明暗变化免疫，牺牲一点纹理）。
    """
    hcv, ncv = to_cv(hay), to_cv(needle)
    if edge:
        hcv, ncv = _edges(hcv), _edges(ncv)
    if ncv.shape[0] > hcv.shape[0] or ncv.shape[1] > hcv.shape[1]:
        return []
    if ncv.size == 0:
        return []
    res = cv2.matchTemplate(hcv, ncv, cv2.TM_CCOEFF_NORMED)
    ys, xs = np.where(res >= threshold)
    cands = sorted(((float(res[y, x]), int(x), int(y)) for x, y in zip(xs, ys)),
                   reverse=True)
    out: list[Match] = []
    for score, x, y in cands:
        if any(abs(x - m.x) < m.w and abs(y - m.y) < m.h for m in out):
            continue
        out.append(Match(x, y, ncv.shape[1], ncv.shape[0], round(score, 4)))
        if len(out) >= max_n:
            break
    return out


def best_match(hay, needle, edge: bool = False) -> tuple[float, tuple[int, int] | None]:
    """只返回最高分与位置（不设阈值，用于输出"到底有多像"的证据）。"""
    hcv, ncv = to_cv(hay), to_cv(needle)
    if edge:
        hcv, ncv = _edges(hcv), _edges(ncv)
    if ncv.shape[0] > hcv.shape[0] or ncv.shape[1] > hcv.shape[1] or ncv.size == 0:
        return 0.0, None
    res = cv2.matchTemplate(hcv, ncv, cv2.TM_CCOEFF_NORMED)
    _, mx, _, loc = cv2.minMaxLoc(res)
    return float(mx), loc


def crop(img, rect):
    """rect = (x1, y1, x2, y2)，越界自动裁剪。"""
    x1, y1, x2, y2 = rect
    box = (max(0, int(x1)), max(0, int(y1)),
           min(img.width, int(x2)), min(img.height, int(y2)))
    return img.crop(box)


def save(img, path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(p))
    return p


def draw_boxes(img, boxes, color=(220, 30, 30), width: int = 2) -> Image:
    """在图上画矩形框（人工核对用；不改原图，返回新图）。

    boxes = [(x1,y1,x2,y2), ...] 或 [(x1,y1,x2,y2,"标签"), ...]。
    校准产物 out/wx-reference.png 带上它，人工一眼看出行框选对不对。
    """
    out = img.convert("RGB").copy()
    d = ImageDraw.Draw(out)
    for b in boxes:
        x1, y1, x2, y2 = int(b[0]), int(b[1]), int(b[2]), int(b[3])
        label = str(b[4]) if len(b) >= 5 else ""
        d.rectangle([x1, y1, x2, y2], outline=color, width=width)
        if label:
            d.text((x1 + 2, max(0, y1 - 14)), label, fill=color)
    return out


# ---------------------------------------------------------------- 内容指纹
def dhash(img, size: int = 8) -> str:
    """差异哈希 + 量化均色：给「列表行」一个跨次运行稳定的身份。

    用途：处理过的行不再点（R2 不重复）。选 dHash 而不是整图 md5：缩放到
    9×8 后 ±1px 渲染差、抗锯齿差异都被吸收，但换一张内容指纹必变。
    纯 dHash 有个盲区——**纯色图没有梯度，指纹全零**，两张不同的纯色图会
    撞指纹；所以拼一个 4bit/通道 的量化均色（3 位十六进制），纯色也能分开。
    格式：16 位梯度指纹 + "-" + 3 位色指纹，如 "0110…1010-f3a"。
    """
    g = np.asarray(img.convert("L").resize((size + 1, size), Image.BILINEAR),
                   dtype=np.int16)
    diff = g[:, 1:] > g[:, :-1]
    bits = "".join("1" if b else "0" for b in diff.flatten())
    arr = np.asarray(img.convert("RGB"), dtype=np.uint16)
    if arr.size:
        mean = arr.reshape(-1, 3).mean(axis=0) / 16.0
        color = "%x%x%x" % (int(mean[0]), int(mean[1]), int(mean[2]))
    else:
        color = "000"
    return bits + "-" + color


# ---------------------------------------------------------------- 列表行检测
_INK_THR = 210        # 低于此灰度算「墨迹」（实测：页面底 250、公众号名 160、标题 30~80）
_DARK_THR = 100       # 低于此算「深墨」（标题级），用于把标题带与灰字带分开
_PAGE_BG = 250        # 微信浅色主题页面底色（实测，不是纯白 255）


def to_gray(img) -> np.ndarray:
    """灰度 ndarray（PIL / BGR ndarray 都收，返回 2 维数组）。"""
    g = to_cv(img)
    return cv2.cvtColor(g, cv2.COLOR_BGR2GRAY) if g.ndim == 3 else g


def text_bands(img, x1=None, x2=None, y1=None, y2=None,
               min_h: int = 8, max_gap: int = 3, min_ink: int = 3) -> list[dict]:
    """把矩形内的文字按**行投影**切成「文字带」。

    返回 [{y1,y2,x1,x2,h,dark,mid,ink}]，窗口内坐标。
      * dark = 深墨像素数（<100）：标题/正文
      * mid  = 灰墨像素数（100..210）：公众号名、时间等次要文字
      * x1/x2 = 该带内墨迹的左右边界（不是传入的列范围）

    为什么要它：2026-10-23 实测发现「公众号名在哪一行」不能用「行中心 ±
    固定偏移」猜——标题换行时整个偏移都会框到标题上，导致 identify_account
    恒 0.0（静默失效）。按投影切带 + 按深墨占比分类，才不依赖行内布局。
    """
    g = to_gray(img)
    H, W = g.shape[:2]
    x1 = 0 if x1 is None else max(0, int(x1))
    x2 = W if x2 is None else min(W, int(x2))
    y1 = 0 if y1 is None else max(0, int(y1))
    y2 = H if y2 is None else min(H, int(y2))
    if x2 - x1 < 8 or y2 - y1 < min_h:
        return []

    sub = g[y1:y2, x1:x2]
    ink = sub < _INK_THR
    rows = ink.sum(axis=1)

    spans: list[tuple[int, int]] = []
    s = last = None
    for i, n in enumerate(rows):
        if n >= min_ink:
            if s is None:
                s = i
            last = i
        elif s is not None and i - last > max_gap:
            spans.append((s, last + 1)); s = None
    if s is not None:
        spans.append((s, last + 1))

    out = []
    for a, b in spans:
        if b - a < min_h:
            continue
        blk = sub[a:b]
        cols = (blk < _INK_THR).sum(axis=0) > 0
        xs = np.where(cols)[0]
        if not len(xs):
            continue
        dark = int((blk < _DARK_THR).sum())
        mid = int(((blk >= _DARK_THR) & (blk < _INK_THR)).sum())
        out.append({"y1": y1 + a, "y2": y1 + b,
                    "x1": x1 + int(xs.min()), "x2": x1 + int(xs.max()) + 1,
                    "h": b - a, "dark": dark, "mid": mid, "ink": dark + mid})
    return out


def _thumb_column(img) -> tuple[int, int] | None:
    """缩略图列带（彩色块最密的那一段列），只用来给指纹取样，不参与行定位。"""
    cv = to_cv(img)
    hsv = cv2.cvtColor(cv, cv2.COLOR_BGR2HSV)
    sat, val = hsv[:, :, 1].astype(float), hsv[:, :, 2].astype(float)
    colorful = (sat > 40) & (val > 40)
    colprof = colorful.sum(axis=0)
    if colprof.max() <= 0:
        return None
    on = colprof > colprof.max() * 0.25
    segs, s = [], None
    for i, v in enumerate(on):
        if v and s is None:
            s = i
        elif not v and s is not None:
            segs.append((s, i)); s = None
    if s is not None:
        segs.append((s, len(on)))
    segs = [ab for ab in segs if ab[1] - ab[0] >= 40]
    if not segs:
        return None
    return max(segs, key=lambda ab: ab[1] - ab[0])


def _text_left(g, lo_ratio: float = 0.15, hi_ratio: float = 0.55,
               y_lo: float = 0.35, y_hi: float = 0.95) -> int:
    """文章文字列的左界：跳过左侧分区标签栏（合集/赞和收藏/最近阅读…）。

    判据用**列墨量**：标签栏只有几行小字，每列墨量远低于正文列。取「首个
    ≥45% 峰值的列」，再向左让 20px 留边。

    **统计区间取页面下半部（y_lo~y_hi）**，这是 2026-10-23 实机补的：
    标签栏在顶部且只有 5~6 行字，若整页统计，一旦某个标签被选中（圆角底色块
    + 深色文字），它的列墨量会顶上来——实测窗口 1652×1518 的收藏页上整页算出
    **262**（落在「赞和收藏」标签内，正确值约 420），后果是文字带横跨到标签栏，
    条目 1 的账号带混入「赞和收藏」四个深墨字（dark/h=22.5 > 4）而被判"非账号带"
    ⇒ **整页第一条永远漏检**，而且它只是"从第 2 条开始数 10 行"，行数看起来正常。
    下半部只有正文，左下角偶有侧栏残留，但不会被选中态污染。
    下半部几乎没内容（列表很短）则回退整页。
    """
    H, W = g.shape[:2]
    band = g[int(H * y_lo):max(int(H * y_hi), int(H * y_lo) + 40), :]
    if (band < _INK_THR).sum() < 500:      # 下半部几乎无墨 → 用整页
        band = g
    lo, hi = int(W * lo_ratio), int(W * hi_ratio)
    if hi - lo < 40:
        return lo
    cols = (band[:, lo:hi] < _INK_THR).sum(axis=0)
    if cols.max() <= 0:
        return lo
    strong = cols >= cols.max() * 0.45
    idx = np.where(strong)[0]
    if not len(idx):
        return lo
    return max(lo, lo + int(idx.min()) - 20)


def detect_rows(img, min_h: int = 40, max_h: int = 110, warn: bool = True) -> list[dict]:
    """从截图检测「文章列表行」= **标题文字带 + 紧随其后的灰色账号带**。

    返回 [{y1,y2,center,thumb_x1,thumb_x2,account_box,click_point}]，
    全部是**窗口内**坐标（调用方加窗口 rect 左上角才是屏幕绝对坐标）。

    为什么不再用「彩色缩略图块」定位（2026-10-23 实测推翻）：
    缩略图只有一部分是彩色的，黑图/灰图/浅色图的行整段漏检 —— 同一张收藏页
    （wx-fav-clean.png，肉眼 10 行）旧算法只检出 **3 行**，也就是 70% 的文章
    永远不会被处理。而"每行必有标题 + 公众号名"是版面契约，按文字带配对
    才是稳定的结构判据（同一张图 10/10 行）。

    配对规则与判据：
      * 标题带：深墨像素/行 ≥ 8（正文是深色，账号名不带深墨）
      * 多行标题：相邻深墨带行距 ≤ 12px 合并（单行行距约 11）
      * 账号带：紧随标题、深墨/行 ≤ 4、宽 30~500px、间距 ≤ 40px
    三条任一不成立就不算一行（标签栏「全部/♡/👍」、底部半截行都会被排除）。
    不做行距投票：多行标题使行距必然不均（实测 126 与 152 并存），投票会把
    真实行当伪行剔除；配对本身已是更强的结构过滤。
    """
    g = to_gray(img)
    H, W = g.shape[:2]
    thumb = _thumb_column(img)
    cx1, cx2 = thumb if thumb else (int(W * 0.84), W)
    text_x1 = _text_left(g)
    text_x2 = max(text_x1 + 40, cx1 - 8)
    bands = text_bands(img, x1=text_x1, x2=text_x2, y1=0, y2=H,
                       min_h=10, max_gap=2)
    if len(bands) < 2:
        return []

    rows = []
    i, n = 0, len(bands)
    while i < n:
        b = bands[i]
        if b["dark"] / b["h"] < 8:          # 不是标题带（标签栏/账号残留）
            i += 1
            continue
        # 多行标题：连续深墨带、行距不超过一行字高
        last = i
        while (last + 1 < n
               and bands[last + 1]["dark"] / bands[last + 1]["h"] >= 8
               and bands[last + 1]["y1"] - bands[last]["y2"] <= 12):
            last += 1
        acct = bands[last + 1] if last + 1 < n else None
        if (acct is None
                or acct["dark"] / acct["h"] > 4
                or not (30 <= acct["x2"] - acct["x1"] <= 500)
                or acct["y1"] - bands[last]["y2"] > 40
                or acct["mid"] / acct["h"] < 6):
            i = last + 1
            continue
        y1, y2 = b["y1"], acct["y2"]
        cy = (y1 + y2) // 2
        if not (min_h <= y2 - y1 <= max_h * 1.6):
            i = last + 2
            continue
        rows.append({
            "y1": y1, "y2": y2, "center": cy,
            "thumb_x1": cx1, "thumb_x2": cx2,
            "account_box": [max(0, acct["x1"] - 4), max(0, acct["y1"] - 4),
                            cx1 - 8, acct["y2"] + 4],
            "account_h": acct["h"],
            "account_dark": acct["dark"],
            "title_box": [b["x1"], b["y1"], b["x2"], bands[last]["y2"]],
            "click_point": [min(b["x1"] + 200, W - 10), cy],
        })
        i = last + 2

    if not rows and warn:
        print("[vision] 未检出「标题+账号」配对的列表行（可能不在文章列表页，"
              "或文字列左界判断失败）", file=sys.stderr)
    return rows


# ---------------------------------------------------------------- 输入注入
# 坐标一律是**屏幕绝对坐标**（含多显示器虚拟桌面，允许负值）；调用方要把
# 窗口内坐标加上窗口 rect 左上角。win32 坐标与 SendInput 归一化坐标的换算
# 见 _norm_xy（必须扣虚拟桌面原点）。
_INPUT_MOUSE = 0
_MOUSEEVENTF_MOVE = 0x0001
_MOUSEEVENTF_ABSOLUTE = 0x8000
_MOUSEEVENTF_VIRTUALDESK = 0x4000   # 归一化基准从"主屏"改成"整张虚拟桌面"
_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004
_MOUSEEVENTF_WHEEL = 0x0800
_WHEEL_DELTA = 120
_SM_XVIRTUALSCREEN, _SM_YVIRTUALSCREEN = 76, 77
_SM_CXVIRTUALSCREEN, _SM_CYVIRTUALSCREEN = 78, 79
_KEYEVENTF_KEYUP = 0x0002
_VK_MENU, _VK_ESCAPE, _VK_LEFT = 0x12, 0x1B, 0x25
_VK_CTRL, _VK_W = 0x11, 0x57
# 2026-10-23 追加：wechat_open_url 需要「粘贴 + 回车」。
# 逐字符输入在 CEF 的搜索框里会撞快捷键/被吞，剪贴板 + Ctrl+V 才是可靠通道。
_VK_RETURN, _VK_V, _VK_A = 0x0D, 0x56, 0x41
# 光标停靠点：屏幕左上角，任何窗口之外。仅移动、不点击，不改变焦点。
_PARK_X, _PARK_Y = 2, 2


def _norm_xy(x: int, y: int) -> tuple[int, int]:
    """绝对像素坐标 → SendInput 归一化坐标 (0..65535)。

    必须扣掉虚拟桌面**原点**：副屏在主屏左边时 SM_XVIRTUALSCREEN 是负数，
    不扣原点会把坐标整体平移一个主屏宽度（2026-10-23 调研结论：
    多显示器偏移是这类自动化"点偏"故障的第一大来源）。

    拿不到可用的虚拟桌面尺寸时**抛异常**而不是退回原值：原值是像素坐标，
    塞进 MOUSEEVENTF_ABSOLUTE 会被当成 0..65535 的归一化值，点击会落在
    左上角附近——静默点错比不点更糟（2026-10-23 验证者指出）。
    """
    import ctypes
    u = ctypes.windll.user32
    vx = u.GetSystemMetrics(_SM_XVIRTUALSCREEN)
    vy = u.GetSystemMetrics(_SM_YVIRTUALSCREEN)
    w = u.GetSystemMetrics(_SM_CXVIRTUALSCREEN)
    h = u.GetSystemMetrics(_SM_CYVIRTUALSCREEN)
    if w <= 1 or h <= 1:
        raise ValueError("GetSystemMetrics 虚拟桌面尺寸不可用：w=%r h=%r" % (w, h))
    return (int((x - vx) * 65535 / (w - 1)),
            int((y - vy) * 65535 / (h - 1)))


def _send_mouse(flags: int, dx: int, dy: int, data: int = 0) -> bool:
    """发一个鼠标输入事件。返回 SendInput 是否报告成功。"""
    import ctypes

    class _MI(ctypes.Structure):
        _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                    ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                    ("time", ctypes.c_ulong),
                    ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]

    class _I(ctypes.Union):
        _fields_ = [("mi", _MI)]

    class _Input(ctypes.Structure):
        _fields_ = [("type", ctypes.c_ulong), ("ii", _I)]

    inp = _Input(type=_INPUT_MOUSE)
    inp.ii.mi = _MI(dx, dy, data, flags, 0, None)
    return ctypes.windll.user32.SendInput(
        1, ctypes.byref(inp), ctypes.sizeof(inp)) == 1


def _cursor_pos() -> tuple[int, int] | None:
    """当前光标屏幕坐标；取不到返回 None。抽成函数便于测试注入。"""
    import ctypes
    from ctypes import wintypes
    pt = wintypes.POINT()
    try:
        if not ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
            return None
    except Exception:
        return None
    return (pt.x, pt.y)


def park_cursor(settle: float = 0.12) -> bool:
    """把光标移到屏幕左上角（窗口外）；已经在那儿则不动、不睡。返回是否移动过。

    为什么截图前必须做（2026-10-23 实测）：微信收藏列表的**行有 hover 态**
    （背景变浅灰、缩略图提亮）。鼠标停在某行上时，该行的 dHash 会变：

        光标在 (2,2)：011000000110...1110000011100000-ddd
        hover 该行：  011100000111...1111000011110000-ddd
        移开后：      011000000110...1110000011100000-ddd   ← 完全恢复

    而我们的点击就是把光标留在那一行上 ⇒ 该行指纹漂移 ⇒ journal 里的记录
    下次运行匹配不上 ⇒ **同一篇文章被重复点**（实测 y1=1097 与 y1=324 各重复一次）。
    行几何完全没变（y1/y2 一致），所以只看坐标永远查不出来。

    放在截图入口而不是"点击后移开"：用户手动停在列表上同样会污染**首张**截图，
    那一行的指纹会被 hover 版写进 journal。
    """
    import ctypes
    pos = _cursor_pos()
    # 容差判断：SetCursorPos(2,2) 实测可能落在 (2,1)（系统取整），
    # 用严格相等会让每次截图都白睡 0.12s（wait_until 轮询里会放大）。
    if pos and abs(pos[0] - _PARK_X) <= 2 and abs(pos[1] - _PARK_Y) <= 2:
        return False
    ctypes.windll.user32.SetCursorPos(_PARK_X, _PARK_Y)
    if settle:
        time.sleep(settle)
    return True


def click_at(x: int, y: int, delay: float = 0.08, jitter: int = 0) -> bool:
    """在屏幕绝对坐标 (x,y) 上点一次左键。返回是否完成了一次真实点击。

    jitter>0 时在 ±jitter 像素内随机落点（控件内，不是整屏）——避免每次
    都点同一像素被风控画像（影刀社区案例，±5px）。
    SendInput 失败时回退 SetCursorPos + mouse_event（双实现互备，
    wechatauto-replica 同款策略：单条链路在个别应用上会静默失效）。
    两条路都失败 → 返回 False 并告警，**不假装点过**。
    """
    import random
    import ctypes
    if jitter > 0:
        x += random.randint(-jitter, jitter)
        y += random.randint(-jitter, jitter)
    try:
        nx, ny = _norm_xy(x, y)
    except Exception as e:
        print("[vision] 坐标换算失败，不点击：%s" % e, file=sys.stderr)
        return False
    flags = _MOUSEEVENTF_MOVE | _MOUSEEVENTF_ABSOLUTE | _MOUSEEVENTF_VIRTUALDESK
    ok = _send_mouse(flags, nx, ny)
    time.sleep(delay)
    ok = _send_mouse(_MOUSEEVENTF_LEFTDOWN, nx, ny) and ok
    time.sleep(delay)
    ok = _send_mouse(_MOUSEEVENTF_LEFTUP, nx, ny) and ok
    if not ok:  # SendInput 全线失败才走回退，别静默吞掉
        ctypes.windll.user32.SetCursorPos(int(x), int(y))
        time.sleep(delay)
        ok = (_send_mouse(_MOUSEEVENTF_LEFTDOWN, 0, 0)
              and _send_mouse(_MOUSEEVENTF_LEFTUP, 0, 0))
        if not ok:
            print("[vision] SendInput 与 mouse_event 回退均失败，点击未生效",
                  file=sys.stderr)
    return bool(ok)


def wheel_delta(clicks: int, limit: int = 100) -> int:
    """滚轮格数 → mouseData 值。正=上滚，负=下滚；0 或超限都钳位。

    WHEEL_DELTA=120/格。历史 bug：旧代码写 0x00780000（=120×65536），
    一格滚动被放大 65536 倍；且 clicks 大时 ctypes.c_ulong 溢出。
    """
    if not clicks:
        return 0
    return (1 if clicks > 0 else -1) * _WHEEL_DELTA * min(abs(int(clicks)), limit)


def scroll_at(x: int, y: int, clicks: int = -3) -> bool:
    """在 (x,y) 处滚轮；clicks 负=向下。返回是否发出成功。"""
    try:
        nx, ny = _norm_xy(x, y)
    except Exception as e:
        print("[vision] 坐标换算失败，不滚动：%s" % e, file=sys.stderr)
        return False
    data = wheel_delta(clicks) & 0xFFFFFFFF  # c_ulong 不接受负数，转无符号
    flags = (_MOUSEEVENTF_MOVE | _MOUSEEVENTF_ABSOLUTE | _MOUSEEVENTF_VIRTUALDESK
             | _MOUSEEVENTF_WHEEL)
    return _send_mouse(flags, nx, ny, data)


def key_tap(vk: int, hold: float = 0.05, modifiers=()) -> None:
    """按一下虚拟键（可带修饰键，如 Alt+Left = (0x12, 0x25)）。

    用途：文章页返回列表（见 close_tab / 历史 Escape 方案）。"""
    import ctypes
    u = ctypes.windll.user32
    for m in modifiers:
        u.keybd_event(m, 0, 0, 0)
    u.keybd_event(vk, 0, 0, 0)
    time.sleep(hold)
    u.keybd_event(vk, 0, _KEYEVENTF_KEYUP, 0)
    for m in reversed(list(modifiers)):
        u.keybd_event(m, 0, _KEYEVENTF_KEYUP, 0)


def close_tab() -> None:
    """关闭当前 tab（微信 4.x 文章页返回列表的**唯一可靠**方式）。

    2026-10-23 实机实测：点开收藏里的文章后，Escape 与 Alt+Left **都无效**
    （文章页是主窗口内嵌的 CEF tab，不是浏览器历史，Esc 不关闭也不后退），
    scout 因此在 `scout.return_failed` 卡死一次；改成 Ctrl+W 后 1.5s 内
    列表判据恢复（tab=1.0、rows=10）。
    """
    key_tap(_VK_W, modifiers=(_VK_CTRL,))


def activate_window(hwnd: int, settle: float = 0.6) -> bool:
    """恢复（如最小化）+ 置前。返回是否成功。

    选窗交给 wechat_window()（类名白名单已排除 WorkBuddy/下载工具等），
    本函数只负责把选中的那个微信窗口**可靠置前**——因为截图用的是
    ImageGrab.grab(bbox=窗口rect)，若微信被别的窗口遮挡，截到的就是遮挡物的
    像素（chain_run4 实证：截到 WorkBuddy），所以置前不是锦上添花而是必需。

    前台锁绕法（按可靠性顺序叠加）：
      ① LockSetForegroundWindow(LSFW_UNLOCK) 释放系统前台锁；
      ② AttachThreadInput 把本线程挂到前台线程，再 SetForegroundWindow。
    失败不算致命——坐标点击只要求窗口不被遮挡，但被遮挡会点错，所以尽力置前。
    """
    import ctypes
    import time
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, 9)  # SW_RESTORE
            time.sleep(settle)
        user32 = ctypes.windll.user32
        # ① 释放前台锁（很多"SetForegroundWindow 静默失败"是它导致的）
        try:
            user32.LockSetForegroundWindow(0)  # LSFW_UNLOCK = 0
        except Exception:
            pass
        # ② 挂到前台线程再置前（线程 id 用 pywin32 取，类型安全，避免 ctypes 截断 HWND）
        try:
            import win32process
            cur_tid, _ = win32process.GetWindowThreadProcessId(
                user32.GetForegroundWindow())
            tgt_tid, _ = win32process.GetWindowThreadProcessId(hwnd)
        except Exception:
            cur_tid = tgt_tid = 0
        if cur_tid and tgt_tid and cur_tid != tgt_tid:
            user32.AttachThreadInput(cur_tid, tgt_tid, True)
            try:
                win32gui.SetForegroundWindow(hwnd)
                win32gui.BringWindowToTop(hwnd)
            finally:
                user32.AttachThreadInput(cur_tid, tgt_tid, False)
        else:
            win32gui.SetForegroundWindow(hwnd)
        time.sleep(settle)
        return win32gui.GetForegroundWindow() == hwnd
    except Exception:
        return False


def ensure_min_size(hwnd: int, min_w: int = 760, min_h: int = 600):
    """窗口太小就放大到下限（只大不放）。返回新 rect。

    微信窗口宽 <760 时文章页「··· / 更多」按钮会被挤出屏幕（Gitee
    exlimit/wechat-article-urls 实测），复制链接前必须先保证宽度。
    放大后仍然不够（极少见，如窗口被锁定尺寸）会打警告——调用方不该
    把"调用过"当成"尺寸一定够了"。
    """
    l, t, r, b = win32gui.GetWindowRect(hwnd)
    w, h = r - l, b - t
    if w >= min_w and h >= min_h:
        return (l, t, r, b)
    try:
        import win32con
        win32gui.SetWindowPos(hwnd, 0, 0, 0, max(w, min_w), max(h, min_h),
                              win32con.SWP_NOMOVE | win32con.SWP_NOZORDER
                              | win32con.SWP_NOACTIVATE)
    except Exception as e:
        print("[vision] SetWindowPos 失败：%s" % e, file=sys.stderr)
    rect = win32gui.GetWindowRect(hwnd)
    if (rect[2] - rect[0]) < min_w or (rect[3] - rect[1]) < min_h:
        print("[vision] 放大后仍小于下限 %dx%d：实际 %s"
              % (min_w, min_h, rect), file=sys.stderr)
    return rect


def occlusion_ratio(img, template_path) -> float:
    """用模板匹配估计当前截图里"应该是微信内容"的区域是否被别的东西占了。

    做法：拿 templates/page-title.png 在整幅截图里找，找到说明微信标题栏
    在位；找不到说明被别的窗口盖住（或页面不对）。返回最高匹配分。
    """
    p = Path(template_path)
    if not p.is_file() or img is None:
        return 0.0
    needle = Image.open(str(p))
    score, _ = best_match(img, needle)
    return score


# ---------------------------------------------------------------- CLI
if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "windows"
    if cmd == "windows":
        rx = sys.argv[2] if len(sys.argv) > 2 else ""
        print(json.dumps(find_windows(rx), ensure_ascii=False, indent=1))
    elif cmd == "shot":
        # 与 wechat_favorites / grab_wechat 用**同一个**选窗函数（wechat_window）：
        # 以前这里写 find_windows("微信")[0]，会选中标题里带"微信"字样的浏览器
        # 窗口（2026-10-23 实测被劫持），拍出来的图与 scout 看到的不是一回事。
        out = sys.argv[2] if len(sys.argv) > 2 else "out/shot.png"
        w = wechat_window()
        if not w:
            print("没找到微信窗口")
            sys.exit(6)
        if w["iconic"]:
            print("微信窗口处于最小化（rect=%s），先恢复再截" % (w["rect"],))
            sys.exit(6)
        got = capture_window(hwnd=w["hwnd"])
        if not got:
            print("截图失败（rect=%s）" % (w["rect"],))
            sys.exit(3)
        img, rect = got
        save(img, out)
        print("窗口=%r 类名=%s\nrect=%s 尺寸=%s 全黑=%s → %s"
              % (w["title"], w["cls"], rect, img.size, is_blank(img), out))
    elif cmd == "occl":
        # 用法: vision.py occl <模板路径>
        tpl = sys.argv[2]
        got = capture_window()
        if not got:
            sys.exit(6)
        print("遮挡检测分数=%.4f（越高越像微信在位）" % occlusion_ratio(got[0], tpl))
    elif cmd == "rows":
        # 实时检测列表行（不依赖校准缓存），输出 JSON 供人工/下游使用
        got = grab_wechat()
        if not got:
            print("拿不到干净的微信截图（窗口不存在/被遮挡/空白）")
            sys.exit(6)
        img, rect, _ = got
        rows = detect_rows(img)
        print(json.dumps({"rect": rect, "size": list(img.size), "rows": rows},
                         ensure_ascii=False, indent=1))
