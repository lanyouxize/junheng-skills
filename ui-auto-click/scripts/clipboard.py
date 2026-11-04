#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""零 OCR 获取公众号文章链接：复制链接 → 读剪贴板。

来源与做法
----------
与 Gitee exlimit/wechat-article-urls 同款方案（已跑通）：文章页点右上角
「···」→ 复制链接 → 读剪贴板拿到 https://mp.weixin.qq.com/s/... 原文。
配套约束：微信窗口宽度要 ≥760，否则「更多」按钮被挤出可视区，模板匹配
点不中——窄窗是这条链路的头号失败原因。

为什么读剪贴板而不是 OCR
------------------------
本环境没有 OCR 二进制，Windows 内置 WinRT OCR 又因安全策略禁止运行时
加载程序集而不可用（取证见 scripts/probe_wechat.py）。而"复制链接"这个
动作恰好把 URL 以纯文本形式放进剪贴板——零依赖、零识别错误率，是这条
链路上最可靠的取值通道。

为什么用 ctypes 而不是 pywin32clipboard
--------------------------------------
ctypes.windll.user32/kernel32 是标准库自带的，不新增任何第三方依赖；
只用到 OpenClipboard/CloseClipboard/GetClipboardData/GlobalLock/
GlobalUnlock/EmptyClipboard 这几个 API，重试与 finally 全部自己管，
行为完全可预测。

Windows 剪贴板 API 的三个坑（都踩过）
------------------------------------
1. OpenClipboard 可能失败：剪贴板是全局资源，别的进程正拿着不放时返回
   FALSE。必须重试（最多 10 次 × Sleep(100)），否则高频率轮询时会随机
   读不到。
2. 64 位下 HANDLE 是指针：ctypes 默认 restype=c_int 会把句柄截断成
   32 位，GlobalLock 拿到野指针直接崩。所有句柄/指针必须显式
   restype=c_void_p。
3. GlobalLock 之后必须 GlobalUnlock，且整个读取过程要处在
   OpenClipboard/CloseClipboard 之间——所以成功路径用 try/finally 保证
   CloseClipboard，锁用嵌套 finally 保证成对。

读 CF_UNICODETEXT(=13) 而不是 CF_TEXT(=1)：中文场景用 UTF-16 才不会
乱码；拿不到（非文本/空剪贴板）返回 None。
"""
from __future__ import annotations

import ctypes
import re
import sys
import time

CF_UNICODETEXT = 13
#: 只要公众号文章链接（mp.weixin.qq.com 域名）。别的链接——哪怕是微信
#: 生态里的其他域名——都不算数：调用方的语义是"这篇文章的链接"，
#: 多认一个域名就多一类误判，宁可严格。
URL_PATTERN = re.compile(r"^https?://mp\.weixin\.qq\.com")

_OPEN_RETRIES = 10          # OpenClipboard 失败时的重试次数
_OPEN_RETRY_SLEEP_MS = 100  # 每次重试前睡的毫秒数

# 非 Windows（或没有 window station 的 CI 容器）上 ctypes.windll 不存在：
# 导入即炸会让整个测试套件红掉，所以降级成"读不到"。技能本身只跑
# Windows，但单测要能在任何地方 import。
try:
    _user32 = ctypes.windll.user32
    _kernel32 = ctypes.windll.kernel32
except (AttributeError, OSError):
    _user32 = None
    _kernel32 = None

if _user32 is not None:
    # 句柄/指针一律 c_void_p（见模块 docstring 坑 2）；BOOL 用 c_int。
    _user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    _user32.OpenClipboard.restype = ctypes.c_int
    _user32.CloseClipboard.restype = ctypes.c_int
    _user32.GetClipboardData.argtypes = [ctypes.c_uint]
    _user32.GetClipboardData.restype = ctypes.c_void_p
    _user32.EmptyClipboard.restype = ctypes.c_int
    _kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    _kernel32.GlobalLock.restype = ctypes.c_void_p
    _kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    _kernel32.GlobalUnlock.restype = ctypes.c_int
    _kernel32.Sleep.argtypes = [ctypes.c_uint]
    # 写入端（write_text）需要这三个：GlobalAlloc 同样返回指针，漏了 restype
    # 会被截断成 32 位 → GlobalLock 拿到野指针 → 访问违例（2026-11-01 实测
    # 报 "access violation writing 0x0"，与坑 2 同一个根因）。
    _kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    _kernel32.GlobalAlloc.restype = ctypes.c_void_p
    _kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
    _kernel32.GlobalFree.restype = ctypes.c_void_p
    _user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    _user32.SetClipboardData.restype = ctypes.c_void_p


def _open_clipboard() -> bool:
    """带重试地打开剪贴板。失败返回 False（绝不抛异常）。"""
    for _ in range(_OPEN_RETRIES):
        if _user32.OpenClipboard(None):
            return True
        _kernel32.Sleep(_OPEN_RETRY_SLEEP_MS)
    return False


def read_text() -> str | None:
    """读剪贴板里的 CF_UNICODETEXT 文本；拿不到返回 None（不抛异常）。

    典型用法（判重，调用方负责在点击"复制链接"之前取旧快照）：
        old = clipboard.snapshot()
        ... 点击 ··· → 复制链接 ...
        url = clipboard.wait_for_url(old=old)
    """
    if _user32 is None:
        return None
    if not _open_clipboard():
        return None
    try:
        handle = _user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None                    # 剪贴板里没有文本（图片/文件/空）
        ptr = _kernel32.GlobalLock(handle)
        if not ptr:
            return None
        try:
            return ctypes.wstring_at(ptr)
        finally:
            _kernel32.GlobalUnlock(handle)  # 锁必须成对，否则内存块一直锁着
    finally:
        _user32.CloseClipboard()            # 成败都要关，否则别人打不开


def snapshot() -> str | None:
    """read_text 的语义别名：点击"复制链接"之前取旧值用。

    单独起一个名字是为了让调用点自解释——`old = clipboard.snapshot()`
    比 `old = clipboard.read_text()` 更直白这是"用于判重的旧快照"。
    """
    return read_text()


def clear() -> bool:
    """清空剪贴板（EmptyClipboard）。失败返回 False，不抛异常。

    单测故意不覆盖它：这会真的抹掉使用者剪贴板里的内容，属于有破坏性的
    真实操作，不放进自动化测试。
    """
    if _user32 is None:
        return False
    if not _open_clipboard():
        return False
    try:
        return bool(_user32.EmptyClipboard())
    finally:
        _user32.CloseClipboard()


def write_text(text: str) -> bool:
    """把文本写进剪贴板（CF_UNICODETEXT）。成功返回 True，失败返回 False，不抛异常。

    为什么需要"写"这一半
    --------------------
    下载工具的「自定义」时间范围是两个 QDateEdit（UIA 里是 Spinner）。对它们：
      · ValuePattern.SetValue **假成功**：不报错、回读值不变（2026-11-01 真机
        连试 `2026/09/01` / `2026-09-01` / `2026/9/1` 三种写法，值都停在原值）；
      · 逐字符 keybd_event **被吞**：点击后焦点确实在控件上（按 ↑ 能把月份
        01→02），但数字键一个都没进去。
    唯一可靠的通道是人工也会用的那三步：①点进控件 ②Ctrl+A ③Ctrl+V。
    本函数就是那条通道的写入端；键序在 clicker 的 `set_date` 动作里。

    所有权语义（Windows 剪贴板的老坑）
    ----------------------------------
    SetClipboardData 成功后内存块**归系统所有**，调用方不能再 GlobalFree；
    失败则系统没接手，必须自己释放，否则每失败一次泄漏一块全局内存。
    """
    if _user32 is None:
        return False
    GMEM_MOVEABLE = 0x0002
    data = text.encode("utf-16-le") + b"\x00\x00"
    handle = _kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
    if not handle:
        return False
    ptr = _kernel32.GlobalLock(handle)
    if not ptr:
        _kernel32.GlobalFree(handle)
        return False
    try:
        ctypes.memmove(ptr, data, len(data))
    finally:
        _kernel32.GlobalUnlock(handle)
    if not _open_clipboard():
        _kernel32.GlobalFree(handle)
        return False
    ok = False
    try:
        _user32.EmptyClipboard()
        ok = bool(_user32.SetClipboardData(CF_UNICODETEXT, handle))
    finally:
        _user32.CloseClipboard()
    if not ok:
        _kernel32.GlobalFree(handle)
    return ok


def wait_for_url(timeout: float = 10.0, poll: float = 0.25,
                 reader=read_text, pattern=URL_PATTERN,
                 old: str | None = None) -> str | None:
    """轮询等一个"新的"公众号文章链接出现在剪贴板里。

    reader 可注入（单测注入假 reader，绝不碰真剪贴板）；reader() 抛异常
    会被吞掉继续轮询——剪贴板被别的进程占用时 OpenClipboard 就是会失败，
    那是等待的理由，不是错误的理由。

    判重：返回值与 old 不同才算"新"。调用方负责在点击前取
    old = snapshot()，否则点一次"复制链接"后读到的是上一次的旧链接。

    匹配前 strip：剪贴板里的链接常带首尾换行/空格；返回的也是 strip 后的串。
    """
    deadline = time.monotonic() + timeout
    while True:
        try:
            current = reader()
        except Exception:
            current = None
        if current is not None and current != old:
            text = current.strip()
            if pattern.match(text):
                return text
        if time.monotonic() >= deadline:
            return None
        time.sleep(poll)


if __name__ == "__main__":
    # 用法: clipboard.py [read|snapshot|clear|wait [秒]]
    cmd = sys.argv[1] if len(sys.argv) > 1 else "read"
    if cmd == "read":
        print(read_text() or "(剪贴板没有文本)")
    elif cmd == "snapshot":
        print(snapshot() or "(剪贴板没有文本)")
    elif cmd == "clear":
        sys.exit(0 if clear() else 1)
    elif cmd == "wait":
        secs = float(sys.argv[2]) if len(sys.argv) > 2 else 10.0
        url = wait_for_url(timeout=secs)
        print(url or "(超时没等到公众号链接)")
        sys.exit(0 if url else 1)
    else:
        print("用法: clipboard.py [read|snapshot|clear|wait [秒]]", file=sys.stderr)
        sys.exit(2)
