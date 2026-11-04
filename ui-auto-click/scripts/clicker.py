#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ui-auto-click 引擎：按 YAML 步骤表驱动 Windows 桌面软件的控件。

设计要点（真机踩坑后定型，勿轻易改）：
  1. **模式优先**：Invoke / Toggle / SetValue 直接作用于控件，不需要窗口在前台，
     也不会把点击发到别的窗口上。`click`（真实鼠标）默认不参与流程，必须显式声明，
     且执行前校验 GetForegroundWindow == 目标窗口，否则直接判失败（不静默点错）。
     —— 真机事故：目标窗口被全屏程序遮挡时，click_input 的点击落到了前台全屏应用里。
  2. **automation_id 优先**：控件显示名随版本变，auto_id 稳定；选择器允许 auto_id
     + name 双写，命中后仍校验 name 以防同名控件错位。
  3. **可干跑、可自检**：--dry-run 只定位不动手；verify 对 toggle 步骤做开->关->还原
     并回读，证明链路通且可回滚。

退出码：0 ok / 2 参数或步骤表非法 / 3 执行失败 / 5 部分成功(有 warn) / 6 环境不具备
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXIT_OK, EXIT_PARAM, EXIT_ERROR, EXIT_PARTIAL, EXIT_ENV = 0, 2, 3, 5, 6

_PROFILE_DIR = Path(__file__).resolve().parent / "profiles"
_UIA_TOGGLE_PROP = 10015  # UIA_ToggleToggleStatePropertyId
_ACTIONS = {
    "invoke", "toggle", "set_value", "read", "exists", "wait_control", "wait_stable",
    "wait_log", "assert_log", "wait_file", "sleep", "screenshot", "click", "activate",
    "open_url", "set_date",
}


def _canon_date(value: str) -> str:
    """把日期写法收敛成 `yyyy/MM/dd`；认不出返回空串。

    工具日期框的显示格式就是 `yyyy/MM/dd`（真机读数是 `2000/01/01`）。
    这里同时接受 `2026-09-01` / `2026/9/1` / `20260901`：收敛后再用于
    写入与回读比较，避免「写的是 2026/9/1、回读是 2026/09/01」被当成失败。
    """
    m = re.search(r"(\d{4})\D?(\d{1,2})\D?(\d{1,2})", str(value or ""))
    if not m:
        return ""
    y, mo, d = (int(g) for g in m.groups())
    if not (1900 <= y <= 2999 and 1 <= mo <= 12 and 1 <= d <= 31):
        return ""
    return "%04d/%02d/%02d" % (y, mo, d)


# ------------------------------------------------------------------ 事件
def emit(level: str, event: str, **fields: Any) -> None:
    """输出一行 JSONL 事件到 stdout（便于管道与留痕）。"""
    record = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "level": level,
        "event": event,
    }
    record.update(fields)
    print(json.dumps(record, ensure_ascii=False), flush=True)


def say(text: str) -> None:
    """人类可读进度打到 stderr，不污染 stdout 的事件流。"""
    print(text, file=sys.stderr, flush=True)


# ------------------------------------------------------------------ 依赖
def _import_uia():
    try:
        from pywinauto import Application, Desktop
    except ImportError as exc:
        emit("env", "env.missing", dependency="pywinauto",
             hint="C:/Users/Administrator/.workbuddy/binaries/python/envs/default/Scripts/python.exe -m pip install pywinauto pywin32 comtypes")
        raise SystemExit(EXIT_ENV) from exc
    return Application, Desktop


def _load_yaml(path: Path) -> dict:
    try:
        import yaml
    except ImportError as exc:
        emit("env", "env.missing", dependency="pyyaml", hint="pip install pyyaml")
        raise SystemExit(EXIT_ENV) from exc
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        emit("param", "profile.unreadable", path=str(path), error=str(exc))
        raise SystemExit(EXIT_PARAM) from exc
    if not isinstance(data, dict):
        emit("param", "profile.invalid", path=str(path), reason="顶层必须是对象")
        raise SystemExit(EXIT_PARAM)
    return data


# ------------------------------------------------------------------ 窗口
def select_windows(candidates: list[dict], regex: str, classes: list[str] | None = None) -> list[dict]:
    """从候选窗口里挑目标（纯函数，便于离线测试）。

    给了 classes 白名单就以类名为准，标题正则只用于排序；没给白名单才按标题正则。
    """
    import re

    pattern = re.compile(regex) if regex else None
    allowed = {c.strip() for c in (classes or []) if c and c.strip()}
    found: list[dict] = []
    for item in candidates:
        title = item.get("title") or ""
        class_name = item.get("class_name") or ""
        title_hit = bool(pattern.search(title)) if pattern else False
        if allowed:
            if class_name not in allowed:
                continue
        elif not title_hit:
            continue
        merged = dict(item)
        merged["title_hit"] = title_hit
        found.append(merged)
    found.sort(key=lambda entry: (not entry["title_hit"], entry.get("handle") or 0))
    return found


def find_windows(regex: str, classes: list[str] | None = None) -> list[dict]:
    """枚举顶层窗口。

    匹配语义（真机踩坑后定型）：
      * 给了 classes 白名单 -> **以类名为准**，标题正则只用来排序偏好；
      * 没给白名单 -> 必须标题正则命中。

    原因：UIA 侧读到的 CurrentName 会变。真机实测同一个工具窗口，
    标题一会儿是「微信公众号文章批量下载工具4.0 by.长风998」、一会儿变成
    「wechatdownload」（进程名），按标题匹配会突然找不到窗口。
    类名（如 Mywindow / Qt51514QWindowIcon）才是稳定的。
    """
    _app, Desktop = _import_uia()
    candidates: list[dict] = []
    try:
        windows = Desktop(backend="uia").windows()
    except Exception as exc:
        emit("error", "window.enumerate_failed", error=str(exc))
        return []
    for window in windows:
        try:
            candidates.append({
                "pid": window.process_id(), "handle": window.handle,
                "title": window.window_text() or "",
                "class_name": window.class_name() or "",
            })
        except Exception:
            continue
    return select_windows(candidates, regex, classes)


def attach(window_info: dict):
    Application, _Desktop = _import_uia()
    app = Application(backend="uia").connect(process=window_info["pid"])
    window = app.window(handle=window_info["handle"])
    if not window.exists(timeout=3):
        raise RuntimeError(f"窗口句柄 {window_info['handle']} 存在但 UIA 节点不可用")
    return window


# ------------------------------------------------------------------ 选择器
def resolve(control_parent, selector, timeout: float = 2.0):
    """按选择器解析控件；支持 auto_id / control_type / name / name_regex / index。

    选择器可以是 dict，也可以是 dict 列表（按顺序尝试，实现"版本兜底"：
    新版按 auto_id 命中，老版按 name 命中），全部失败才报错。

    优先用 auto_id 精确定位（PySide/Qt 程序普遍暴露稳定 auto_id）；
    未给 auto_id 时退化为遍历匹配。命中后若同时给了 name，会做一次名称校验。
    """
    if isinstance(selector, (list, tuple)):
        errors = []
        for candidate in selector:
            try:
                return resolve(control_parent, candidate, timeout=timeout)
            except RuntimeError as exc:
                errors.append(str(exc))
        raise RuntimeError("全部选择器均未命中: " + " | ".join(errors))
    return _resolve_one(control_parent, selector, timeout)


def _resolve_one(control_parent, selector: dict, timeout: float = 2.0):
    import re

    if not isinstance(selector, dict) or not selector:
        raise RuntimeError("选择器为空（需要 auto_id / control_type / name 之一）")
    auto_id = (selector.get("auto_id") or "").strip()
    control_type = (selector.get("control_type") or "").strip()
    name = selector.get("name")
    name_regex = selector.get("name_regex")
    index = int(selector.get("index", 0) or 0)

    deadline = time.monotonic() + max(0.0, timeout)
    last_error = ""
    while True:
        try:
            # auto_id 必须在 Python 侧过滤，不能当 kwargs 传给 descendants()：
            # pywinauto 0.6.9 的 IUIA.build_condition() 只认 process/class_name/
            # title/control_type/content_only，传 auto_id 会抛 TypeError，而这条
            # 异常会被"选择器列表兜底"吞掉 —— 结果是 auto_id 静默失效、退到按
            # index 命中错误控件（真机事故：把等待时间写进了日志框）。
            if control_type:
                pool = control_parent.descendants(control_type=control_type)
            else:
                pool = control_parent.descendants()
            hits = []
            for item in pool:
                try:
                    info = item.element_info
                    if auto_id and (info.automation_id or "") != auto_id:
                        continue
                    if control_type and (info.control_type or "") != control_type:
                        continue
                    text = item.window_text() or ""
                    if name is not None and text.strip() != str(name).strip():
                        continue
                    if name_regex and not re.search(name_regex, text):
                        continue
                except Exception:
                    continue
                hits.append(item)
            if len(hits) > index:
                return hits[index]
            last_error = f"命中 {len(hits)} 个（需要 index={index}）"
        except Exception as exc:
            last_error = str(exc)
        if time.monotonic() >= deadline:
            raise RuntimeError(f"定位失败 {selector} -> {last_error}")
        time.sleep(0.2)


# ------------------------------------------------------------------ 状态读取
def read_toggle(control) -> str:
    """读 ToggleState（0/1/2）；三路兜底，全失败返回 '?'。"""
    try:
        return str(control.iface_toggle.CurrentToggleState)
    except Exception:
        pass
    try:
        return str(control.element_info.element.GetCurrentPropertyValue(_UIA_TOGGLE_PROP))
    except Exception:
        pass
    try:
        return "1" if control.get_toggle_state() else "0"
    except Exception:
        return "?"


def is_enabled(control) -> bool | None:
    """控件当前是否可用；读不到返回 None（当真处理，不做假设）。"""
    try:
        return bool(control.is_enabled())
    except Exception:
        pass
    try:
        return bool(control.element_info.element.CurrentIsEnabled)
    except Exception:
        return None


def apply_toggle(control, want: bool | None, current: str) -> tuple[bool, str, str]:
    """把控件切到 want 状态（want=None 表示反相）。返回 (是否动作, 前, 后)。"""
    before = current
    if want is None:
        target = "0" if before == "1" else "1"
    else:
        target = "1" if want else "0"
    if before == target:
        return False, before, before
    # 要动它之前先确认它动得了：禁用控件点了没反应，绝不能记成"已成功"。
    enabled = is_enabled(control)
    if enabled is False:
        raise RuntimeError(
            f"控件已禁用（当前 {before}，目标 {target}）—— 界面上这个选项此刻不可用，"
            "先确认为什么灰掉（依赖项未勾选/需要先授权），不要硬点")
    try:
        control.toggle()
    except Exception:
        try:
            control.iface_toggle.Toggle()
        except Exception as exc:
            raise RuntimeError(f"Toggle 模式不可用: {exc}") from exc
    time.sleep(0.25)
    return True, before, read_toggle(control)


def _first_text(control, getters) -> str:
    """按顺序取第一个**非空**文本；全为空时返回取到的空串。

    必须跳过空串再试下一个 getter：Qt 的 Edit/PlainTextEdit 在 UIA 里
    `window_text()`（=CurrentName）经常是空串，真正的文本在 Value 模式里。
    只认第一个"返回值非 None"的 getter 会把日志读成 ""，导致 wait_log 永远不命中。
    """
    seen = ""
    for getter in getters:
        try:
            value = getattr(control, getter)()
        except Exception:
            continue
        if value is None:
            continue
        text = str(value)
        if text.strip():
            return text
        seen = text
    return seen


def read_text(control) -> str:
    """读控件文本（Edit / PlainTextEdit / 文本标签通用）。"""
    text = _first_text(control, ("window_text", "get_value", "text_block"))
    if text:
        return text
    try:
        return str(control.element_info.element.CurrentName or "")
    except Exception:
        return ""


def read_value(control) -> str:
    """读可写入控件的当前值：Value 模式优先，其次 Name。

    写后回读必须走这条路径 —— 若先取 window_text()，某些控件会返回控件名
    而不是输入值，导致"写成功却判失败"的假红。
    """
    return _first_text(control, ("get_value", "window_text"))


def _read_date(control) -> str:
    """读日期框当前值（QDateEdit 在 UIA 里是 Spinner）。

    Spinner **有** ValuePattern（可读，实测返回 `2000/01/01`）但 SetValue 不
    起作用 —— 所以读走 Value、写必须走剪贴板（见 set_date）。这里读不到时
    退回 read_value，保证回读判据在任何版本上都有值可比。
    """
    try:
        current = control.iface_value.CurrentValue
        if current:
            return str(current)
    except Exception:
        pass
    return read_value(control)


def describe(control) -> str:
    """给控件一个可用于留痕的身份串（干跑时证明命中的到底是哪个控件）。"""
    info = getattr(control, "element_info", None)
    auto_id = getattr(info, "automation_id", "") if info is not None else ""
    control_type = getattr(info, "control_type", "") if info is not None else ""
    try:
        text = (control.window_text() or "")[:24]
    except Exception:
        text = ""
    return f"{control_type or '?'}[{auto_id or '-'}]{text!r}"


# ------------------------------------------------------------------ 截图与文件证据
def capture_window(window, path: Path) -> str:
    """抓窗口图像，返回所用的方法名。

    优先 PrintWindow：抓的是窗口自己的绘制结果，**窗口被遮挡也能抓对**。
    （真机事故：window.capture_as_image() 是抓屏幕上那块矩形，目标窗口被全屏
    程序盖住时抓到的是全屏游戏画面，留证截图完全失去意义。）

    窗口最小化时 PrintWindow 只能抓到一条标题栏（实测 232×26 的废图），
    所以先临时恢复窗口、抓完再最小化回去 —— 留证不应该改变现场。
    """
    import ctypes

    path.parent.mkdir(parents=True, exist_ok=True)
    user32 = ctypes.windll.user32
    handle = getattr(window, "handle", None)
    was_iconic = bool(handle) and bool(user32.IsIconic(handle))
    if was_iconic:
        user32.ShowWindow(handle, 9)   # SW_RESTORE
        time.sleep(0.5)
    try:
        if handle:
            try:
                import win32gui
                import win32ui
                from PIL import Image

                left, top, right, bottom = win32gui.GetWindowRect(handle)
                width, height = right - left, bottom - top
                if width < 200 or height < 100:
                    raise RuntimeError(f"窗口尺寸异常 {width}x{height}，拒绝产出废图")
                hwnd_dc = win32gui.GetWindowDC(handle)
                mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
                save_dc = mfc_dc.CreateCompatibleDC()
                bitmap = win32ui.CreateBitmap()
                bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
                save_dc.SelectObject(bitmap)
                # pywin32 没导出 PrintWindow，走 ctypes；2 = PW_RENDERFULLCONTENT
                ok = user32.PrintWindow(handle, save_dc.GetSafeHdc(), 2)
                bits = bitmap.GetBitmapBits(True)
                image = Image.frombuffer("RGB", (width, height), bits, "raw", "BGRX", 0, 1)
                image.save(str(path))
                win32gui.DeleteObject(bitmap.GetHandle())
                save_dc.DeleteDC()
                mfc_dc.DeleteDC()
                win32gui.ReleaseDC(handle, hwnd_dc)
                if ok:
                    return "PrintWindow(临时恢复窗口)" if was_iconic else "PrintWindow"
            except Exception:
                pass
        window.capture_as_image().save(str(path))
        return "capture_as_image(需窗口在前台)"
    finally:
        if was_iconic:
            user32.ShowWindow(handle, 6)   # SW_MINIMIZE：还原现场


def _match_entries(path_pattern: str, recursive: bool) -> list[Path]:
    """把 path 解析成文件/目录列表：目录取直接子项，通配符走 glob。"""
    import glob as _glob

    base = Path(path_pattern)
    if any(char in path_pattern for char in "*?["):
        return [Path(p) for p in _glob.glob(path_pattern, recursive=recursive)]
    if base.is_dir():
        entries = list(base.glob("**/*" if recursive else "*"))
        return [p for p in entries if p.name]
    return [base] if base.exists() else []


def wait_for_files(step: dict) -> tuple[bool, str]:
    """轮询文件系统，直到匹配项数量达标。返回 (是否达标, 说明)。"""
    raw = str(step.get("path") or "").strip()
    if not raw:
        raise RuntimeError("wait_file 需要 path（目录或通配符）")
    min_count = int(step.get("min_count", 1) or 1)
    recursive = bool(step.get("recursive", False))
    only_new = bool(step.get("only_new", True))
    timeout = float(step.get("timeout", 120))
    interval = max(0.1, float(step.get("interval", 2.0)))
    started = time.time() - 2.0  # 容忍一点时钟抖动
    deadline = time.monotonic() + timeout
    seen: list[Path] = []
    while True:
        entries = _match_entries(raw, recursive)
        if only_new:
            fresh = []
            for item in entries:
                try:
                    if item.stat().st_mtime >= started:
                        fresh.append(item)
                except OSError:
                    continue
            entries = fresh
        seen = entries
        if len(entries) >= min_count:
            return True, f"{len(entries)}/{min_count} 项达标 · {raw}"
        if time.monotonic() >= deadline:
            return False, f"{len(entries)}/{min_count} 项（等待 {timeout:g}s 超时）· {raw}"
        time.sleep(interval)


# ------------------------------------------------------------------ 落盘日志（source=file）支撑
# 2026-10-28 真机教训：工具的 Qt Form.TextEdit 日志控件在 UIA 下**间歇性返回空串**
# （见 _first_text 注释），导致 wait_log/assert_log/wait_stable 全部以「控件为空」误判，
# 整链以 rc=3 死在步骤23。工具本体每一行都会**可靠地落盘**到 <保存目录>/log<YYYYMMDD>.txt，
# 所以用「读落盘文件」代替「读 UIA 控件」来判定进度才是稳的。
# 基线与原始 wait_log 保持一致：以「本次 run 第一次读到该文件时的字节偏移」为基准，只认
# 基准之后新增的内容 —— 既排除上一轮/前一天的旧行，又保留本轮全部产出（含报错）。
# 多个步骤若用同一个 path（glob 取最新），会**共享**这一条 run 级基线，等价于原始实现里
# 用同一个 target_spec 共享 baseline 的行为（步骤257 因此仍能看到步骤23 窗口里出现的
# 「获取公众号历史消息页面成功」）。

def _latest_log_file(pattern: str):
    """把 path 解析成「最新修改」的一个文件：通配符走 glob 取 mtime 最大者，
    否则按字面路径存在才返回。"""
    import glob as _glob
    if any(c in pattern for c in "*?["):
        files = [Path(p) for p in _glob.glob(pattern)]
    else:
        files = [Path(pattern)] if Path(pattern).exists() else []
    if not files:
        return None
    files.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    return files[0]


# ------------------------------------------------------- 下载工具状态探测
# 读工具权威日志（Desktop/下载/logYYYYMMDD.txt），探测「当前采集进行到哪一步」。
# 设计来源：完整 33 步流程里，工具的状态由日志里出现的最新里程碑标记决定；
# 只要读到最新里程碑，就能和总体步骤表对比、精准确定下一步该跑哪段 ——
# 避免像 2026-10-28 那样：工具已取密钥、却盲目从步骤1 重跑导致 wait_log 超时 rc=3。
_DOWNLOADER_MARKERS = [
    ("done", "下载完成!!!"),
    ("downloading", "起始下载页数"),
    ("keyed", "获取密钥成功"),
    ("id_ready", "获取公众号历史消息页面成功"),
    ("need_open", "请先在微信打开复制的链接"),
    ("need_open2", "请先在左面打开微信内置浏览器"),
    ("keying", "开始获取密钥"),
]
# 状态优先级（数值越大=流程越靠后）；同一行出现多个标记时取更靠后的
_STATE_PRIORITY = {
    "fresh": 0, "keying": 1, "id_ready": 2, "need_open": 2, "need_open2": 2,
    "keyed": 3, "downloading": 4, "done": 5,
}
_MARKER_TEXT = {
    "done": "下载完成", "downloading": "已开始下载", "keyed": "获取密钥成功",
    "id_ready": "获取公众号历史消息页面成功", "need_open": "需先在微信打开复制的链接",
    "need_open2": "需先打开微信内置浏览器", "keying": "开始获取密钥", "fresh": "尚无里程碑",
}


def probe_downloader_state(log_path: str | None = None) -> dict:
    """读下载工具权威日志，探测当前采集状态（只读，不操作任何软件）。

    返回 dict：state / raw_state / log_file / last_marker / last_marker_line /
    total_lines / detail。state ∈ {fresh,keying,id_ready,keyed,downloading,done}；
    need_open/need_open2 归并到 id_ready（都表示 id 已取、密钥待取，下一步都是
    "在微信打开 profile_ext 取密钥"）。

    「当前运行步骤」以「已达到的最新里程碑」表达，配合总体步骤表即可精准定下一步：
    - fresh/keying   → 整段重跑（config→取id→取密钥→下载），用 wechat_batch_downloader
    - id_ready       → 跳到取密钥+下载段，用 wechat_key_and_download
    - keyed          → 跳到下载段，用 wechat_download_only
    - downloading    → 续等静止（wechat_download_only 的 wait_stable）
    - done           → 工具空闲（上一轮已完成）；换篇需整段重跑，同号去重交给 ledger
    """
    if log_path is None:
        path = _latest_log_file("C:/Users/Administrator/Desktop/下载/log*.txt")
    else:
        path = Path(log_path)
    if path is None or not path.exists():
        return {"state": "fresh", "raw_state": "fresh", "log_file": None,
                "last_marker": None, "last_marker_line": -1, "total_lines": 0,
                "detail": "no log file"}
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    last = {}
    for i, line in enumerate(lines):
        for st, mk in _DOWNLOADER_MARKERS:
            if mk in line:
                last[st] = i
    if not last:
        return {"state": "fresh", "raw_state": "fresh", "log_file": str(path),
                "last_marker": None, "last_marker_line": -1, "total_lines": len(lines),
                "detail": "no milestone in log"}
    best_st, best_line = None, -1
    for st, ln in last.items():
        if ln > best_line or (ln == best_line
                               and _STATE_PRIORITY.get(st, 0) > _STATE_PRIORITY.get(best_st or "", 0)):
            best_st, best_line = st, ln
    state = "id_ready" if best_st in ("need_open", "need_open2") else best_st
    sample = lines[best_line] if 0 <= best_line < len(lines) else ""
    return {"state": state, "raw_state": best_st, "log_file": str(path),
            "last_marker": _MARKER_TEXT.get(best_st), "last_marker_line": best_line,
            "total_lines": len(lines), "detail": sample.strip()[:200]}


def _file_new_text(step: dict, context: dict):
    """source=file 时返回 (新增文本, 文件对象)。维护 run 级字节偏移基线。"""
    raw = _render(str(step.get("path") or ""), context).strip()
    path = _latest_log_file(raw)
    baselines = context.setdefault("file_baselines", {})
    off = baselines.get(raw)
    if off is None:
        try:
            off = path.stat().st_size if path else 0
        except OSError:
            off = 0
        baselines[raw] = off
    if path is None:
        return "", None
    try:
        with open(path, "rb") as f:
            f.seek(off)
            data = f.read().decode("utf-8", "replace")
    except OSError:
        data = ""
    return data, path


# ------------------------------------------------------------------ 置前 / 点击守卫
# 2026-10-23 真机教训：pipeline 起工具后点了「1.获取公众号id」，日志一个字都没变，
# 排查发现**点击落到了窗口之外**。三层根因，缺一条都会重演：
#   ① DPI：本进程没做 DPI 感知时，UIA 给的控件矩形是**物理像素**，而 GetWindowRect
#      是**逻辑像素**。两套坐标混用 → "按钮中心" 算到 (1744,252)，而窗口只有
#      (230,65)-(1234,779) ⇒ 真实鼠标点去了别的窗口。vision.py 一开头就设了 DPI
#      感知，clicker 没设 —— 同一个仓库两套坐标系，是最典型的隐形 bug。
#   ② Windows 前台锁：非前台进程 SetForegroundWindow 被静默忽略。工具刚启动
#      （自己是刚被创建的窗口）时能置前，几秒后前台换成微信，之后连试 3 次全被拒。
#   ③ 真实鼠标点击（SendInput）**只认屏幕坐标上最上层的窗口**，与"谁是前台"无关。
# 所以：先 DPI 感知（下面 _ensure_dpi_aware，import 时执行），再提 z 序
# （_raise_window），焦点尽力抢（_focus_window），最后用 WindowFromPoint 判归属。


def _ensure_dpi_aware() -> bool:
    """把本进程设成 DPI 感知（与 vision.ensure_dpi_aware 同策略，但不引 cv2）。

    必须在**任何**坐标计算前执行，所以放在 import 阶段。测试可设
    UIAC_NO_DPI_AWARE=1 跳过（改了进程级状态，个别用例不想被影响时用）。
    """
    if os.environ.get("UIAC_NO_DPI_AWARE") == "1" or sys.platform != "win32":
        return False
    import ctypes

    u = ctypes.windll.user32
    for api, arg in (("SetProcessDpiAwarenessContext", ctypes.c_void_p(-4)),
                     ("SetProcessDpiAwarenessContext", ctypes.c_void_p(-3))):
        fn = getattr(u, api, None)
        if fn is not None:
            try:
                if fn(arg):
                    return True
            except Exception:
                pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)     # 每监视器感知
        return True
    except Exception:
        pass
    try:
        return bool(u.SetProcessDPIAware())                # 至少系统级感知
    except Exception:
        return False


_ensure_dpi_aware()


def _raise_window(handle: int) -> None:
    """把窗口提到**非置顶**组的最上层（HWND_TOP），不改变 topmost 属性。

    用 HWND_TOP 而不是 HWND_TOPMOST：后者会让窗口在这次运行后一直压在所有窗口
    之上，用户想切走都难；HWND_TOP 只调整本组 z 序，正合"让鼠标点得到"。
    """
    import ctypes

    SWP_NOSIZE, SWP_NOMOVE, SWP_SHOWWINDOW = 0x0001, 0x0002, 0x0040
    ctypes.windll.user32.SetWindowPos(
        int(handle), 0, 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_SHOWWINDOW)


def _focus_window(handle: int) -> int:
    """尽力把窗口变成前台，返回最终前台句柄（可能仍不是它）。

    绕前台锁的两个标准做法叠用：AttachThreadInput 把本线程的输入状态挂到
    当前前台窗口的线程上；再敲一下 ALT 让系统认定"用户有输入意图"。
    两者都不保证成功，所以调用方必须能接受"焦点没抢到"。
    """
    import ctypes

    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    handle = int(handle)
    if user32.GetForegroundWindow() == handle:
        return handle
    cur = kernel32.GetCurrentThreadId()
    fg = user32.GetForegroundWindow()
    fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    attached = False
    try:
        if fg_thread and fg_thread != cur:
            attached = bool(user32.AttachThreadInput(cur, fg_thread, True))
        VK_MENU, KEYEVENTF_KEYUP = 0x12, 0x0002
        user32.keybd_event(VK_MENU, 0, 0, 0)
        user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
        user32.BringWindowToTop(handle)
        user32.SetForegroundWindow(handle)
        time.sleep(0.15)
        return user32.GetForegroundWindow()
    finally:
        if attached:
            user32.AttachThreadInput(cur, fg_thread, False)


def _window_rect(handle: int) -> tuple[int, int, int, int]:
    """窗口在屏幕坐标系下的矩形 (l, t, r, b)。

    单独抽出来是为了能被测试替身替换：真机 Bug 里"控件矩形与窗口矩形不在同一
    坐标系"这条判据（见下面 click 分支的守卫 0）必须能离线验证，不该依赖真窗口。
    """
    import win32gui

    return tuple(int(v) for v in win32gui.GetWindowRect(int(handle)))


def _window_at(x: float, y: float) -> int:
    """屏幕坐标 (x, y) 上真正会收到鼠标事件的那个**顶层**窗口句柄（0=查不到）。

    实现统一到 `vision.window_at_point`（2026-10-26 加固）：同一条判据必须只有
    一份实现，否则"clicker 查一个说法、favorites_chain 查另一个说法"，迟早分歧。
    保留这个私有名是因为测试全靠 patch 它来注入"落点归属"，改签名会波及一堆用例。
    WindowFromPoint 常返回子控件/内部句柄，`vision.window_at_point` 已用
    GetAncestor(GA_ROOT) 归到顶层。
    """
    info = _window_info(x, y)
    return int(info["hwnd"]) if info else 0


def _window_info(x: float, y: float) -> dict | None:
    """落点窗口的详细信息（hwnd/title/cls/rect）；查不到返回 None。

    单独抽出来只为**错误信息里能写出窗口标题**：只报 hwnd 时，人看到
    "实际归属窗口 723044" 根本不知道那是谁（2026-10-26 真机事故里它是
    「Wise Care 365」——一个系统清理工具，点上去后果不可控）。
    """
    try:
        import vision
        return vision.window_at_point(x, y)
    except Exception:
        return None


def _window_title(handle: int) -> str:
    """窗口标题（取不到返回空串，绝不抛异常）。"""
    try:
        import win32gui
        return win32gui.GetWindowText(int(handle)) or ""
    except Exception:
        return ""


def _screen_virtual_rect() -> tuple[int, int, int, int]:
    """虚拟屏幕（多显示器）矩形 (x, y, w, h)，坐标系与 WindowFromPoint 一致。"""
    import ctypes
    u = ctypes.windll.user32
    x = u.GetSystemMetrics(76)   # SM_XVIRTUALSCREEN
    y = u.GetSystemMetrics(77)   # SM_YVIRTUALSCREEN
    w = u.GetSystemMetrics(78)   # SM_CXVIRTUALSCREEN
    h = u.GetSystemMetrics(79)   # SM_CYVIRTUALSCREEN
    return (int(x), int(y), int(w), int(h))


def _move_window(handle: int, x: int, y: int) -> None:
    """仅移动窗口（保持尺寸），把它挪到指定左上角。

    用 SWP_NOSIZE 保持原尺寸，避免改动用户布局；SWP_SHOWWINDOW 顺手让它可见。
    """
    import win32gui
    win32gui.SetWindowPos(int(handle), 0, int(x), int(y), 0, 0,
                          win32gui.SWP_NOSIZE | win32gui.SWP_SHOWWINDOW)


def _try_clear_occlusion(window, target_spec, max_tries: int = 16):
    """落点被别的窗口盖住时，尝试把"目标窗口"挪到按钮点确实归它的屏幕位置。

    返回 (control, cx, cy) 表示已挪到清晰落点；全部失败返回 None。
    设计要点（解决真机 z 序竞态）：
      * 只挪"目标窗口"本身，绝不动微信等其他程序；
      * 仅在"按钮中心这个屏幕点 window_at_point 命中目标窗口"时才算成功；
      * 这样一来，即便微信随后抢回焦点，只要没挪到该坐标，真实鼠标点击仍落在
        目标窗口上 —— 彻底消除"校验时归它、点击时归别人"的窗口（工具与微信两个
        大窗重叠，按钮点被微信盖住，旧逻辑点了却落到微信身上，工具零反应）。
    """
    try:
        import win32gui
    except Exception:
        return None
    handle = int(window.handle)
    orig = _window_rect(handle)
    w = orig[2] - orig[0]
    h = orig[3] - orig[1]
    vx, vy, vw, vh = _screen_virtual_rect()
    vright, vbottom = vx + vw, vy + vh
    # 候选左上角：原位置优先（能不挪就不挪），再铺网格覆盖"按钮挪到微信上方
    # (y 很小)/右侧(x 很大)/左侧(x 很小)"等能避开大块遮挡的典型情形。
    xs = sorted({0, max(0, (vw - w) // 3), max(0, 2 * (vw - w) // 3),
                 max(0, vw - w)})
    ys = sorted({0, max(0, (vh - h) // 2), max(0, vh - h)})
    candidates = [(tx, ty) for tx in xs for ty in ys]
    candidates.insert(0, (orig[0], orig[1]))   # 原位置排第一
    for tx, ty in candidates[:max_tries]:
        # 落点（按钮中心）必须留在可见虚拟屏内，否则 WindowFromPoint 会落到桌面/0
        if tx < vx or ty < vy or tx + w > vright or ty + h > vbottom:
            continue
        _move_window(handle, tx, ty)
        time.sleep(0.12)
        try:
            ctrl = resolve(window, target_spec, timeout=1.0)
            r = ctrl.rectangle()
            cx = (r.left + r.right) / 2.0
            cy = (r.top + r.bottom) / 2.0
        except Exception:
            continue
        if not (vx <= cx <= vright and vy <= cy <= vbottom):
            continue
        if _window_at(cx, cy) == handle:
            return ctrl, cx, cy
    return None


# ------------------------------------------------- 单选选中态（verify_selected）
def _radio_name(control) -> str:
    """单选按钮的可读名字：显示名优先，没有再用 auto_id。"""
    try:
        text = (control.window_text() or "").strip()
    except Exception:
        text = ""
    if text:
        return text
    try:
        return (control.element_info.automation_id or "").strip() or "?"
    except Exception:
        return "?"


def _radio_selected(control) -> bool | None:
    """读 SelectionItem 模式的选中位；**读不到返回 None**（区分"未选中"与"不可读"）。

    为什么 None 要单独一级：value 一假又不明原因时最容易写成 else: return False，
    那样"模式不支持"会被当成"没选中"→ 点了 → 回读还是 False → 误判点击失败；
    更糟的是反过来把它当通过 —— 这一步的成败**只能**靠回读证明，读不到就必须报警。
    """
    try:
        return bool(control.iface_selection_item.CurrentIsSelected)
    except Exception:
        return None


def selected_radios(window, control) -> list[tuple[str, bool | None]]:
    """目标控件所在那组单选按钮的选中快照 `[(名字, 是否选中)]`，**目标必在其中**。

    为什么按容器取而不是按窗口全量取：一个界面可以有多组 RadioButton，全量取会把
    别的组算进来，互斥检查就失真了。容器取不到才退到窗口级（宁可宽，不能漏掉目标）。
    """
    pool: list = []
    try:
        parent = control.parent()
        if parent is not None:
            pool = list(parent.descendants(control_type="RadioButton"))
    except Exception:
        pool = []
    if not pool:
        try:
            pool = list(window.descendants(control_type="RadioButton"))
        except Exception:
            pool = []
    names = {_radio_name(c) for c in pool}
    if _radio_name(control) not in names:
        # 目标必须进快照：否则"点前/点后选中项名称"会拼出一段跟它无关的话
        pool.append(control)
    return [(_radio_name(c), _radio_selected(c)) for c in pool]


def _picked_name(state: list[tuple[str, bool | None]]) -> str:
    """快照里正被选中的那个名字；一个都没有就返回「无」。"""
    for name, selected in state:
        if selected:
            return name
    return "无"


def verify_selection_effect(window, control, before: list[tuple[str, bool | None]]) -> str:
    """点完之后回读，证明"这一下真的生效了"；返回写进 detail 的那句话。

    为什么必须有回读：2026-10-26 真机事故里，"点了但没生效"和"点生效了"在日志上
    长得一模一样（都写 ok）。选中态是唯一的独立证据。
    错误信息刻意同时带出**点前 / 点后**的选中项名称：人只看一行报错时，得能直接
    读出"一年内 → 一年内"，而不是回去翻截图。
    """
    target_name = _radio_name(control)
    after = selected_radios(window, control)
    if not dict(after).get(target_name):
        raise RuntimeError(
            "verify_selected 失败：点击前选中「%s」，点击「%s」后仍选中「%s」"
            "—— 鼠标点击没有生效。常见原因：① 目标窗口被别的窗口遮挡；"
            "② 该控件此刻不可交互；③ 点击被 UI 延迟吞掉。已拒绝当作成功"
            % (_picked_name(before), target_name, _picked_name(after)))
    extra = [n for n, s in after if n != target_name and s]
    if extra:
        raise RuntimeError(
            "verify_selected 发现互斥被破坏：点击后 %r 已选中，但同组还有 %d 个"
            "也选中（%s）—— 工具未必按我们以为的那个范围执行"
            % (target_name, len(extra), "、".join(extra)))
    return "回读选中项=%s（同组其余 %d 个均为 0）" % (target_name, len(after) - 1)


# ------------------------------------------------------------------ 单步执行
def _var_scope(context: dict) -> dict:
    """变量查找域：环境变量打底，`--var` 传入的覆盖它。

    单独抽出来是因为 `_render` 与条件跳步必须看到**同一份**变量表 —— 两边各拼一次
    迟早会漂移，而条件跳步一旦判错，跳的可能是唯一真正生效的那一步。
    """
    vars_ = dict(os.environ)
    vars_.update((context or {}).get("vars") or {})
    return vars_


def _render(value: str, context: dict) -> str:
    """把 `${VAR}` 换掉：优先 context["vars"]，其次环境变量，都没有就留空串。

    为什么要模板变量：profile 是**静态 YAML**，但「微信文章链接」框的内容每次运行
    都不同（必须是当前可访问的文章 URL）。2026-10-23 真机确认：这个框留空时点
    「1.获取公众号id」工具**一个日志字都不写**，只能靠猜 —— 所以必须能传值。
    """
    if "${" not in (value or ""):
        return value or ""
    vars_ = _var_scope(context)

    def sub(m):
        return str(vars_.get(m.group(1), ""))

    return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", sub, value)


def skip_reason(step: dict, context: dict) -> str:
    """条件跳步判据：返回跳过原因（空串＝这一步该执行）。

    为什么需要它：`${VAR}` 渲染只能改 `value`，改不了 selector 里的 `name`。
    而"同一位置按运行参数二选一"是真实需求 —— 下载工具的时间范围是单选按钮，
    想取全部历史就得点「全部」、想按月取就得点「一个月内」，两份 target 互斥，
    又不能同时点（后点的覆盖前点的）。所以在**步骤粒度**上做条件执行：
    三条 step 字段任选其一，都没写＝无条件执行，既有 profile 行为一字不变。
    """
    var = str(step.get("when_var") or "").strip()
    if not var:
        return ""
    scope = _var_scope(context)
    if var not in scope:
        # 变量压根没传，与"传了空串"是两件事：只有显式写了 when_default 才把
        # 缺省当成"走这条"，否则缺省应该是"谁都不走"（下面判据一条都不命中）。
        if step.get("when_default"):
            return ""
        return "when_var=%s 未提供（未写 when_default）" % var
    actual = str(scope[var])
    expected_in = step.get("when_in")
    if expected_in is not None:
        allowed = [str(x) for x in (expected_in if isinstance(expected_in, (list, tuple))
                                    else [expected_in])]
        if actual in allowed:
            return ""
        return "when_var=%s=%s 不匹配 %s" % (var, actual, "|".join(allowed))
    if step.get("when_equals") is not None:
        want = str(step.get("when_equals"))
        if actual == want:
            return ""
        return "when_var=%s=%s 不匹配 %s" % (var, actual, want)
    # 只声明了 when_var 却没给判据：视为"这个变量一旦给了就走这条"，
    # 比默默执行更接近作者意图（也不会因为少写一个键就把互斥步骤全点一遍）。
    return ""


def run_step(window, step: dict, context: dict, dry_run: bool) -> dict:
    """执行一步，返回 {name, action, status, detail}；失败抛 RuntimeError。"""
    action = (step.get("action") or "").strip()
    name = (step.get("name") or action or "?").strip()
    if action not in _ACTIONS:
        raise RuntimeError(f"未知动作: {action!r}（可用: {sorted(_ACTIONS)}）")

    # 条件不满足的步骤直接判 skip，**不抛错**：这是合法分支，不是故障
    #（profile 用互斥的两步表达"二选一"，走不到的那条本来就该安静地跳过）。
    # 动作名先校验再判条件：错字必须当场暴露，不能被"这一步恰好没轮到"掩盖。
    reason = skip_reason(step, context)
    if reason:
        return {"name": name, "action": action, "status": "skip", "detail": reason}

    if action == "sleep":
        seconds = float(step.get("seconds", 1) or 1)
        if not dry_run:
            time.sleep(seconds)
        return {"name": name, "action": action, "status": "ok", "detail": f"{seconds}s"}

    if action == "activate":
        # 把目标窗口恢复到非置顶组最上层。click（真实鼠标）之前必须先做这一步，
        # 否则点击会落到压在上面的别的窗口上。
        if dry_run:
            return {"name": name, "action": action, "status": "plan",
                    "detail": "将恢复窗口并提到最上层（会抢焦点）"}
        handle = getattr(window, "handle", None)
        if not handle:
            raise RuntimeError("activate 需要窗口句柄（window.handle）")
        import ctypes

        handle = int(handle)
        ctypes.windll.user32.ShowWindow(handle, 9)          # SW_RESTORE
        _raise_window(handle)                               # z 序：点击真正依赖这一条
        foreground = _focus_window(handle)                  # 焦点：尽力，不强求
        # 判"置前到底成没成"不能看 GetForegroundWindow：Windows 前台锁会让
        # 抢焦点反复失败（本机对微信实测就是如此），而 z 序其实已经提上去了。
        # 真正决定"鼠标能不能点到这里"的是**坐标归属**，所以用窗口中心点问系统
        # "这一像素归谁"。归属不是它 ⇒ 确实被盖住了 ⇒ 中止，别赌后面那一下点击。
        wl, wt, wr, wb = _window_rect(handle)
        ccx, ccy = (wl + wr) / 2.0, (wt + wb) / 2.0
        info = _window_info(ccx, ccy)
        if not info or int(info["hwnd"]) != handle:
            actual = ("%r hwnd=%s" % (info["title"], info["hwnd"])
                      if info else "无法查询（WindowFromPoint 返回空）")
            raise RuntimeError(
                "置前失败：窗口中心 (%d,%d) 归属 %s，不是目标窗口 %r hwnd=%s —— "
                "后续鼠标点击可能落到别的窗口，已中止（2026-10-26 真机事故：点击落进了"
                " Wise Care 365）。请把目标窗口移到可见区域；确需跳过此检查可给该步"
                "加 optional: true"
                % (int(ccx), int(ccy), actual, _window_title(handle), handle))
        if foreground == handle:
            return {"name": name, "action": action, "status": "ok",
                    "detail": f"已置前（焦点 + 坐标归属均为目标窗口）handle={handle}"}
        # 焦点没抢到 ≠ 不能点：窗口确实在本组最上层（上面已用坐标归属核实），
        # 鼠标点击照样能落到它上面。这里只如实报告，不把它当失败——把它当失败
        # 会让本机（前台被 WorkBuddy 占着、前台锁抢不到）永远跑不完。
        return {"name": name, "action": action, "status": "ok",
                "detail": f"已提到最上层且坐标归属为目标窗口，但前台仍为 {foreground}"
                          "（Windows 前台锁；点击由坐标归属校验兜底）"}

    if action == "screenshot":
        path = Path(str(step.get("path") or "out/step.png"))
        if dry_run:
            return {"name": name, "action": action, "status": "plan", "detail": str(path)}
        method = capture_window(window, path)
        return {"name": name, "action": action, "status": "ok",
                "detail": f"{path}（{method}）"}

    if action == "wait_file":
        if dry_run:
            return {"name": name, "action": action, "status": "plan",
                    "detail": f"等待 {step.get('path')}（min_count={step.get('min_count', 1)}）"}
        ok, detail = wait_for_files(step)
        if not ok:
            if step.get("optional"):
                return {"name": name, "action": action, "status": "warn",
                        "detail": f"未达标（可选，不中断）: {detail}"}
            raise RuntimeError(f"wait_file 未达标: {detail}")
        return {"name": name, "action": action, "status": "ok", "detail": detail}

    if action == "open_url":
        # 「在微信内置浏览器打开一条链接」——把用户口径的三步封进流程：
        #   ① 复制链接（下载工具产出 profile_ext 后已自行放进剪贴板，也能从日志抠）
        #   ② 点微信标题栏右侧放大镜
        #   ③ 在搜索框粘贴网址并回车
        # 为什么必须在流程里做：工具点完「1.获取公众号id」后要读微信内置浏览器的
        # cookie 才能「获取密钥成功」；没人去打开那个链接时日志只会一直刷
        # 「获取密钥失败...请先在微信打开复制的链接」，后面的下载按钮点了也白点。
        # 链接来源优先级：log 正文 > 剪贴板（日志是 UIA 直读，比剪贴板稳——剪贴板
        # 随时可能被别的进程覆盖）。所以默认 source=log 且允许 clipboard 兜底。
        source = (step.get("source") or "log").strip()
        settle = float(step.get("settle", 4.0))
        # warmup：先导航到同域首页，强制制造一次真实的「加载完成」事件。
        # 工具的提示原文是「等公众号页面加载后，软件会自动获取密钥」——它只认这个
        # 时机。微信已经停在该 profile_ext 页时，再粘贴同一条 URL 等于原地不动
        # （实测 changed_ratio 0.0279），没有加载事件，密钥永远抓不到。
        warmup = _render(str(step.get("warmup", "")), context).strip()
        target_spec = step.get("target") or {}
        if dry_run:
            return {"name": name, "action": action, "status": "plan",
                    "detail": f"将在微信内置浏览器打开链接（source={source}"
                              f"{'，先 warmup ' + warmup if warmup else ''}）"}
        try:
            import wechat_open_url
            from PIL import Image  # noqa: F401  （wechat_open_url 依赖，缺失要早报错）
        except Exception as exc:
            raise RuntimeError(f"open_url 依赖不可用: {exc}") from exc

        url = ""
        if source in ("log", "clipboard"):
            if source == "log" and target_spec:
                try:
                    control = resolve(window, target_spec, timeout=2)
                    url = wechat_open_url.find_url_in_text(read_text(control)) or ""
                except Exception as exc:
                    emit("warn", "open_url.log_unreadable", error=str(exc))
            if not url and step.get("fallback_clipboard", True):
                url = wechat_open_url.find_url_in_text(
                    wechat_open_url.clipboard_text()) or ""
        else:
            url = _render(str(step.get("value", "")), context).strip()
            if not url and step.get("skip_if_empty"):
                # 合法分支（本次没给该变量），不该把退出码拉成 5，更不该中断流程：
                # 预热只是"别让微信停在目标页"的保险，没有文章链接时交给现场状态兜底。
                return {"name": name, "action": action, "status": "skip",
                        "detail": "跳过：%s 为空" % step.get("value")}
        if not url:
            raise RuntimeError(
                "open_url 拿不到链接：日志里没有 mp.weixin.qq.com 链接、剪贴板也没有。"
                "先确认上一步「1.获取公众号id」是否真的成功（日志应有"
                "「获取公众号历史消息页面成功」并给出 profile_ext 链接）")

        code = wechat_open_url.open_in_wechat(url, settle=settle, warmup=warmup)
        if code == 6:
            raise RuntimeError("open_url 失败：微信未运行/被遮挡/最小化，先人工把微信露出来")
        if code != 0:
            raise RuntimeError(f"open_url 失败（exit={code}）：点放大镜/粘贴/回车这条链路没走通")
        return {"name": name, "action": action, "status": "ok",
                "detail": f"已打开 {url[:80]}"}

    target_spec = step.get("target") or {}
    if dry_run:
        control = resolve(window, target_spec, timeout=float(step.get("timeout", 2)))
        where = "?"
        try:
            rect = control.rectangle()
            where = "%d,%d" % (rect.left, rect.top)
        except Exception:
            pass
        extra = ""
        if action == "toggle":
            extra = f" state={read_toggle(control)}"
        elif action in ("set_value", "read"):
            extra = f" 现值={read_value(control)[:16]!r}"
        return {"name": name, "action": action, "status": "plan",
                "detail": f"命中 {describe(control)} @{where}{extra}"}

    if action == "wait_control":
        # 等控件的"文字/可用性"变成期望值。典型场景：主按钮在运行时显示「暂停中...」，
        # 只有变回「2.批量下载文章」才能点 —— 死等固定秒数或硬点都会出错。
        import re

        control = resolve(window, target_spec, timeout=float(step.get("timeout", 2)))
        # 注意：step 里的 name 是"步骤名"，不是控件文字，所以期望文字用 expect_* 独立键
        exact = step.get("expect_name")
        pattern = step.get("expect_name_regex")
        require_enabled = bool(step.get("require_enabled", False))
        timeout = float(step.get("timeout", 30))
        interval = max(0.2, float(step.get("interval", 0.5)))

        def _current() -> str:
            try:
                return control.window_text() or ""
            except Exception:
                return ""

        deadline = time.monotonic() + timeout
        while True:
            text = _current()
            matched = True
            if exact is not None and text.strip() != str(exact).strip():
                matched = False
            if pattern and not re.search(pattern, text):
                matched = False
            if require_enabled and is_enabled(control) is not True:
                matched = False
            if matched:
                return {"name": name, "action": action, "status": "ok",
                        "detail": f"就绪：{text[:24]!r}"}
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"等控件状态超时（期望 expect_name={exact!r} "
                    f"expect_name_regex={pattern!r} enabled={require_enabled}）"
                    f"当前文字={text[:40]!r}")
            time.sleep(interval)

    if action == "wait_stable":
        source = str(step.get("source") or "control").strip().lower()
        if source == "file":
            # 等落盘日志"不再增长"来判任务结束。同样用 run 级字节偏移基线：
            # 下载过程中工具不断 append（图片/文章行），结束后静止。比读 UIA 控件稳。
            # stable_seconds 不能太小：实测工具会「暂停19秒，防止访问被限制」，
            # 15 秒窗口会把限速暂停误判成结束。
            if dry_run:
                return {"name": name, "action": action, "status": "plan",
                        "detail": f"等落盘日志稳定 {step.get('stable_seconds', 60)}s"}
            raw = _render(str(step.get("path") or ""), context).strip()
            stable_seconds = float(step.get("stable_seconds", 60))
            timeout = float(step.get("timeout", 900))
            interval = max(0.5, float(step.get("interval", 5)))
            deadline = time.monotonic() + timeout
            baselines = context.setdefault("file_baselines", {})
            off = baselines.get(raw)
            if off is None:
                p0 = _latest_log_file(raw)
                off = p0.stat().st_size if p0 else 0
                baselines[raw] = off
            last_size = off
            last_change = time.monotonic()
            while True:
                time.sleep(interval)
                path = _latest_log_file(raw)
                try:
                    cur = path.stat().st_size if path else off
                except OSError:
                    cur = last_size
                if cur != last_size:
                    last_size = cur
                    last_change = time.monotonic()
                elif time.monotonic() - last_change >= stable_seconds:
                    return {"name": name, "action": action, "status": "ok",
                            "detail": f"{stable_seconds:g}s 文件无增长（{last_size} bytes）"}
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        f"等落盘日志稳定超时（{timeout:g}s 内未出现 {stable_seconds:g}s 的静止窗口，"
                        f"当前 {last_size} bytes）")
        # 等输出"不再变化"来判任务结束。比死等固定秒数靠得住，也比 wait_log 通用
        # （很多工具根本不打印"完成"）。stable_seconds 不能太小：实测工具会
        # 「暂停19秒，防止访问被限制」，15 秒的窗口会把限速暂停误判成结束。
        if dry_run:
            return {"name": name, "action": action, "status": "plan",
                    "detail": f"等输出稳定 {step.get('stable_seconds', 60)}s"}
        control = resolve(window, target_spec, timeout=float(step.get("timeout", 2)))
        stable_seconds = float(step.get("stable_seconds", 60))
        timeout = float(step.get("timeout", 900))
        interval = max(0.5, float(step.get("interval", 5)))
        deadline = time.monotonic() + timeout
        last = read_text(control)
        last_change = time.monotonic()
        while True:
            time.sleep(interval)
            current = read_text(control)
            if current != last:
                last = current
                last_change = time.monotonic()
            elif time.monotonic() - last_change >= stable_seconds:
                return {"name": name, "action": action, "status": "ok",
                        "detail": f"{stable_seconds:g}s 无变化（{len(current)} chars）"}
            # 超时必须无条件检查：输出一直在变时若 continue 掉，就会死循环（测试抓到过）
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"等输出稳定超时（{timeout:g}s 内没有出现 {stable_seconds:g}s 的静止窗口，"
                    f"当前 {len(current)} chars）")

    if action == "invoke":
        control = resolve(window, target_spec, timeout=float(step.get("timeout", 2)))
        try:
            control.invoke()
        except Exception:
            try:
                control.iface_invoke.Invoke()
            except Exception as exc:
                raise RuntimeError(f"Invoke 模式不可用: {exc}") from exc
        return {"name": name, "action": action, "status": "ok", "detail": "已触发"}

    if action == "toggle":
        control = resolve(window, target_spec, timeout=float(step.get("timeout", 2)))
        want = step.get("state")
        if want is not None:
            want = bool(want)
        before = read_toggle(control)
        acted, before, after = apply_toggle(control, want, before)
        if after == "?":
            return {"name": name, "action": action, "status": "warn",
                    "detail": "状态回读不可用（控件可能不支持 Toggle 模式）"}
        expect = want if want is not None else (after == "1")
        if after != ("1" if expect else "0"):
            raise RuntimeError(f"状态回读不一致: 期望 {expect} 实得 {after}")
        return {"name": name, "action": action, "status": "ok",
                "detail": f"{before}->{after}" + ("" if acted else "（已是目标态）")}

    if action == "set_value":
        value = _render(str(step.get("value", "")), context)
        if not value.strip() and step.get("skip_if_empty"):
            # 刻意不算 warn：跳过是**合法分支**（本次没提供该参数），不应把整条
            # 流程的退出码拉成 5（pipeline 把非零当阶段失败）。
            return {"name": name, "action": action, "status": "skip",
                    "detail": "跳过：%s 为空" % step.get("value")}
        control = resolve(window, target_spec, timeout=float(step.get("timeout", 2)))
        for setter in ("set_edit_text", "set_text"):
            try:
                getattr(control, setter)(value)
                break
            except Exception:
                continue
        else:
            raise RuntimeError("SetValue 失败（set_edit_text/set_text 均不可用）")
        time.sleep(0.2)
        actual = read_value(control).strip()
        if actual != value.strip():
            raise RuntimeError(f"写入回读不一致: 期望 {value!r} 实得 {actual!r}")
        return {"name": name, "action": action, "status": "ok", "detail": value}

    if action == "set_date":
        # 日期框专用写入（QDateEdit → UIA Spinner）。
        #
        # 为什么不复用 set_value（2026-11-01 真机逐项取证）：
        #   ① ValuePattern.SetValue **假成功** —— 不报错，回读值不变
        #      （`2026/09/01`/`2026-09-01`/`2026/9/1` 三种写法全部停在原值）；
        #   ② 逐字符 keybd_event **被吞** —— 点击后焦点确实在控件上
        #      （按 ↑ 能把月份 01→02），但数字键一个都没进去。
        # 唯一可靠通道就是人工也会的那三步：点进控件 → Ctrl+A → Ctrl+V。
        # 写入端见 clipboard.write_text；Tab 提交一步不能省，否则控件没失焦、
        # 值可能还没落到 model 上。
        raw = _render(str(step.get("value", "")), context)
        value = _canon_date(raw)
        if not value:
            if step.get("skip_if_empty") and not str(raw).strip():
                # 与 set_value 一致：合法分支，不算 warn，别把退出码拉成 5
                return {"name": name, "action": action, "status": "skip",
                        "detail": "跳过：%s 为空" % step.get("value")}
            raise RuntimeError(
                "set_date 需要 yyyy/MM/dd 形式的日期，得到 %r（也接受 2026-9-1 / "
                "20260901）" % (raw,))
        control = resolve(window, target_spec, timeout=float(step.get("timeout", 2)))
        before = _read_date(control)
        if _canon_date(before) == value:
            # 已是目标值就不动它：少一次真实输入 = 少一次可能失败的操作，
            # 也避免"点一下、日历弹出来、再收回去"这种无谓的界面扰动。
            return {"name": name, "action": action, "status": "ok",
                    "detail": "已是 %s（未改动）" % value}
        try:
            import clipboard
            import vision
        except Exception as exc:
            raise RuntimeError(f"set_date 依赖不可用: {exc}") from exc

        rect = control.rectangle()
        # 落点取控件左侧 35%：右侧是日历下拉箭头，点中会弹日历面板，
        # 之后的 Ctrl+A/Ctrl+V 就打到面板上去了。
        cx = int(rect.left + (rect.right - rect.left) * float(step.get("click_ratio", 0.35)))
        cy = int((rect.top + rect.bottom) / 2)
        handle = int(getattr(window, "handle", 0) or 0)
        # 盲按 Ctrl+V 是这台机器上最危险的失手方式：窗口被盖住时粘贴会进别人的
        # 输入框。所以先问系统"这个像素归谁"，不是目标窗口就中止。
        info = _window_info(cx, cy)
        if not info or (handle and int(info["hwnd"]) != handle):
            raise RuntimeError(
                "set_date 中止：落点 (%d,%d) 归属 %r，不是目标窗口 %r —— 盲按粘贴"
                "会写进别的窗口。请先跑 activate 步骤把窗口置前。"
                % (cx, cy, (info or {}).get("title"), _window_title(handle)))
        if not vision.click_at(cx, cy, delay=0.12):
            raise RuntimeError("set_date 点击未发出（SendInput 与 mouse_event 回退均失败）")
        time.sleep(float(step.get("settle", 0.35)))
        vision.key_tap(0x41, modifiers=(0x11,))        # Ctrl+A：全选，粘贴才会整体替换
        time.sleep(0.12)
        if not clipboard.write_text(value):
            raise RuntimeError("set_date 写剪贴板失败（OpenClipboard 被别的进程占用？）")
        time.sleep(0.12)
        vision.key_tap(0x56, modifiers=(0x11,))        # Ctrl+V
        time.sleep(0.25)
        vision.key_tap(0x09)                           # Tab：提交并失焦
        time.sleep(float(step.get("verify_wait", 0.3)))
        actual = _read_date(control)
        if _canon_date(actual) != value:
            raise RuntimeError("set_date 回读不一致：期望 %r 实得 %r" % (value, actual))
        return {"name": name, "action": action, "status": "ok",
                "detail": "%s -> %s" % (before or "?", value)}

    if action == "read":
        control = resolve(window, target_spec, timeout=float(step.get("timeout", 2)))
        value = read_text(control)
        key = step.get("save_as")
        if key:
            context[str(key)] = value
        return {"name": name, "action": action, "status": "ok",
                "detail": f"{len(value)} chars" + (f" -> {key}" if key else "")}

    if action == "exists":
        try:
            control = resolve(window, target_spec, timeout=float(step.get("timeout", 2)))
            return {"name": name, "action": action, "status": "ok",
                    "detail": f"存在: {(control.window_text() or '')[:40]}"}
        except RuntimeError:
            if step.get("optional"):
                return {"name": name, "action": action, "status": "warn", "detail": "不存在（可选）"}
            raise

    if action in ("wait_log", "assert_log"):
        source = str(step.get("source") or "control").strip().lower()
        if source == "file":
            contains_any = step.get("contains_any") or ([step["contains"]] if step.get("contains") else [])
            contains_all = step.get("contains_all") or []
            forbid = step.get("not_contains") or []
            timeout = float(step.get("timeout", 60))
            interval = max(0.1, float(step.get("interval", 1.0)))
            deadline = time.monotonic() + (timeout if action == "wait_log" else 0)
            last = ""
            while True:
                new_text, path = _file_new_text(step, context)
                last = new_text
                hit_any = (not contains_any) or any(t in new_text for t in contains_any)
                hit_all = all(t in new_text for t in contains_all)
                clean = not any(t in new_text for t in forbid)
                if hit_any and hit_all and clean:
                    return {"name": name, "action": action, "status": "ok",
                            "detail": f"命中（新增 {len(new_text)} chars）· {path.name if path else '?'}"}
                if action == "assert_log" or time.monotonic() >= deadline:
                    break
                time.sleep(interval)
            raise RuntimeError(
                f"{action}(file) 未满足（contains_any={contains_any} contains_all={contains_all} "
                f"not_contains={forbid}）快照后新增文本尾部: {last[-160:]!r}")
        control = resolve(window, target_spec, timeout=float(step.get("timeout", 2)))
        contains_any = step.get("contains_any") or ([step["contains"]] if step.get("contains") else [])
        contains_all = step.get("contains_all") or []
        forbid = step.get("not_contains") or []
        timeout = float(step.get("timeout", 60))
        interval = float(step.get("interval", 1.0))
        deadline = time.monotonic() + (timeout if action == "wait_log" else 0)
        # 运行级日志快照（修旧行误匹配）：下载工具窗口跨进程/跨次运行复用，其日志框按
        # 日累计；不隔离会把上一轮成功的「获取密钥成功 / 开始下载」当成这一轮已发生，
        # 造成假成功（真机事故见 favorites_chain 历史）。以"本次 run 第一次读该日志
        # 控件时的长度"为基准，只认基准之后新增的内容 —— 既排除历史旧行，又保留本轮
        # 全部产出（含本轮报错），不会让 assert_log 漏掉本该拦截的本轮错误。
        baselines = context.setdefault("log_baselines", {})
        bkey = repr(target_spec)
        baseline_len = baselines.get(bkey)
        if baseline_len is None:
            baseline_len = len(read_text(control) or "")
            baselines[bkey] = baseline_len
        last = ""
        while True:
            text = read_text(control) or ""
            new_text = text[baseline_len:] if len(text) >= baseline_len else text
            last = new_text
            hit_any = (not contains_any) or any(token in new_text for token in contains_any)
            hit_all = all(token in new_text for token in contains_all)
            clean = not any(token in new_text for token in forbid)
            if hit_any and hit_all and clean:
                return {"name": name, "action": action, "status": "ok",
                        "detail": f"命中（新增 {len(new_text)} chars）"}
            if action == "assert_log" or time.monotonic() >= deadline:
                break
            time.sleep(interval)
        hint = ""
        if not last.strip():
            hint = ("（快照之后日志控件仍为空：先确认 target 是否指到真正的日志控件；"
                    "若该控件根本不暴露 UIA 文本，改用 wait_file 以落盘文件为证据）")
        raise RuntimeError(
            f"{action} 未满足（contains_any={contains_any} contains_all={contains_all} "
            f"not_contains={forbid}）快照后新增文本尾部: {last[-160:]!r}{hint}")

    if action == "click":
        # 真实鼠标点击落到"屏幕该坐标上最上层的窗口"，与焦点无关 ⇒ 判据必须是
        # 坐标归属（WindowFromPoint），不是 GetForegroundWindow。旧判据把
        # "前台不是目标窗口"当成危险信号，结果在 Windows 前台锁下永远点不出去。
        control = resolve(window, target_spec, timeout=float(step.get("timeout", 2)))
        # ---- 三段式选中校验（verify_selected）第 1 段：点击**之前**先看是否已达目标态。
        # 放在所有坐标守卫之前是刻意的：已达目标态就不发鼠标事件 ⇒ 没有"落点" ⇒
        # 落点归属检查无从谈起（遮挡时对一个不点的步骤做归属断言只会制造假失败）。
        if step.get("verify_selected"):
            before = selected_radios(window, control)
            target_name = _radio_name(control)
            target_before = dict(before).get(target_name)
            if target_before is None:
                raise RuntimeError(
                    "verify_selected 无法回读：%r 不暴露 SelectionItem 模式"
                    "（CurrentIsSelected 读不到）—— 拒绝当作成功，因为这一步的成败"
                    "恰恰只能靠回读证明" % target_name)
            if target_before:
                extra = [n for n, s in before if n != target_name and s]
                if extra:
                    raise RuntimeError(
                        "verify_selected 发现单选互斥被破坏：目标 %r 已选中，同组还有 "
                        "%d 个也被选中（%s）—— 控件状态异常，不确定工具会按哪个执行"
                        % (target_name, len(extra), "、".join(extra)))
                emit("info", "step.noop_already_selected", name=name,
                     target=target_name, group=before)
                return {"name": name, "action": action, "status": "ok",
                        "detail": "已是目标态（%s=1，其他 %d 个=0），未产生任何鼠标动作"
                                  % (target_name, len(before) - 1)}
        rect = control.rectangle()
        cx, cy = (rect.left + rect.right) / 2.0, (rect.top + rect.bottom) / 2.0
        try:
            import win32gui  # noqa: F401  （仅用于确认 pywin32 可用，坐标查询走 _window_* ）

            wl, wt, wr, wb = _window_rect(int(window.handle))
            root = _window_at(cx, cy)
        except Exception as exc:
            raise RuntimeError(f"无法校验点击点归属，拒绝鼠标点击: {exc}") from exc
        # 守卫 0：点击点必须落在窗口矩形内。这一条专治"坐标系错位"——控件矩形
        # 来自 UIA（物理像素）、窗口矩形来自 GetWindowRect（逻辑像素）时，中心点会
        # 跑到窗口外面几百像素，靠归属校验才发现太晚（已经在别处点下去了没有）。
        for _retry in range(2):
            if wl - 2 <= cx <= wr + 2 and wt - 2 <= cy <= wb + 2:
                break
            control = resolve(window, target_spec, timeout=1.0)   # 重新取矩形
            rect = control.rectangle()
            cx, cy = (rect.left + rect.right) / 2.0, (rect.top + rect.bottom) / 2.0
            time.sleep(0.1)
        else:
            raise RuntimeError(
                f"点击点 ({int(cx)},{int(cy)}) 落在窗口矩形 ({wl},{wt},{wr},{wb}) 之外——"
                "控件矩形与窗口矩形不在同一坐标系（多为 DPI 感知不一致：UIA 给物理像素、"
                "GetWindowRect 给逻辑像素），已拒绝点击")
        # ---- 落点归属：被遮挡就把"目标窗口"挪到清晰落点再点 ----
        # 只挪目标窗口本身，不动微信等其他程序；只有当"按钮中心这个屏幕点确实归
        # 目标窗口"（window_at_point 命中它）时才算成功。这样即便微信随后抢回焦点，
        # 只要没挪到该坐标，真实鼠标点击仍落在目标窗口 —— 彻底消除"校验时归它、
        # 点击时归别人"的 z 序竞态（真机：工具与微信两个大窗重叠，按钮点被微信盖住，
        # 旧逻辑点了却落到微信身上，工具零反应）。
        clicked_control, cx, cy = control, cx, cy
        for _attempt in range(6):
            root = _window_at(cx, cy)
            if root == int(window.handle):
                control = clicked_control
                break
            cleared = _try_clear_occlusion(window, target_spec)
            if not cleared:
                # 期望/实际都带标题：只报 hwnd 时人根本不知道挡在前面的是谁。
                expected = "%r hwnd=%s" % (
                    _window_title(int(window.handle)), int(window.handle))
                hit = _window_info(cx, cy)
                actual = ("%r hwnd=%s" % (hit["title"], hit["hwnd"])
                          if hit else "无法查询（WindowFromPoint 返回空）")
                msg = (
                    "点击点 (%d,%d) 归属 %s（判定值 root=%s），不是目标窗口 %s —— "
                    "已尝试挪动目标窗口寻找清晰落点仍失败；请把目标窗口露出可见区域"
                    "（不要被微信等大窗完全盖住按钮）后重试；"
                    "确知自己在做什么可在该 step 上加 allow_occluded: true"
                    % (int(cx), int(cy), actual, root, expected))
                if not step.get("allow_occluded"):
                    raise RuntimeError(msg)
                # 逃生口：step 级、必须显式写，且状态记 warn（会让本次 run 返回 5）——
                # 不能让它看起来像一次正常点击。刻意不做命令行全局开关。
                emit("warn", "step.occluded_overridden", name=name,
                     point=[int(cx), int(cy)], actual=actual, expected=expected)
                say("  [!!] %-28s warn  落点不属于目标窗口，allow_occluded 强制继续: %s"
                    % (name, actual))
                clicked_control.click_input()
                note = verify_selection_effect(window, clicked_control, before) \
                    if step.get("verify_selected") else \
                    "落点归属 %s（allow_occluded 强制放行）" % actual
                return {"name": name, "action": action, "status": "warn",
                        "detail": f"已鼠标点击 ({int(cx)},{int(cy)})，{note}"}
            clicked_control, cx, cy = cleared
            control = clicked_control
        control.click_input()
        # ---- 三段式第 3 段：点完必须回读证明"真的生效了"，理由见 verify_selection_effect
        if step.get("verify_selected"):
            note = verify_selection_effect(window, control, before)
            return {"name": name, "action": action, "status": "ok",
                    "detail": f"已鼠标点击 ({int(cx)},{int(cy)})，{note}"}
        return {"name": name, "action": action, "status": "ok",
                "detail": f"已鼠标点击 ({int(cx)},{int(cy)})"}

    raise RuntimeError(f"动作未实现: {action}")


# ------------------------------------------------------------------ 子命令
def _preview_windows(windows: list[dict]) -> None:
    for item in windows:
        say("  pid=%(pid)s class=%(class_name)s title=%(title)r" % item)


def cmd_probe(args: argparse.Namespace) -> int:
    windows = find_windows(args.window_regex, args.window_class)
    emit("info", "probe.windows", regex=args.window_regex, count=len(windows),
         windows=windows)
    if not windows:
        say("没有匹配的窗口。可用 --window-regex 放宽，或先手动打开目标程序。")
        return EXIT_ENV
    say("匹配窗口:")
    _preview_windows(windows)
    window = attach(windows[0])
    rows = []
    for control_type in ("Button", "CheckBox", "RadioButton", "Edit", "ComboBox", "Spinner"):
        try:
            items = window.descendants(control_type=control_type)
        except Exception:
            continue
        for item in items:
            try:
                info = item.element_info
                rows.append({
                    "type": control_type,
                    "auto_id": info.automation_id or "",
                    "name": (item.window_text() or "")[:48],
                    "state": read_toggle(item) if control_type == "CheckBox" else "",
                })
            except Exception:
                continue
    for row in rows:
        emit("info", "probe.control", **row)
    say("\n可交互控件 %d 个（按类型）：" % len(rows))
    current = ""
    for row in rows:
        if row["type"] != current:
            current = row["type"]
            say("  [%s]" % current)
        state = f" state={row['state']}" if row["state"] else ""
        say("    %-26s %-22s%s" % (row["auto_id"], row["name"], state))
    return EXIT_OK


def _load_profile(name: str) -> dict:
    path = Path(name)
    if not path.is_file():
        candidate = _PROFILE_DIR / (name if name.endswith((".yaml", ".yml")) else name + ".yaml")
        path = candidate
    if not path.is_file():
        emit("param", "profile.missing", name=name, dir=str(_PROFILE_DIR))
        raise SystemExit(EXIT_PARAM)
    return _load_yaml(path)


def slice_steps(steps: list, from_step: int = 1, max_steps: int = 0) -> list[tuple[int, dict]]:
    """取出要执行的一段步骤，返回 [(绝对序号, step)]。

    `--from-step N` 从第 N 步开始跑，`--max-steps M` 跑到第 M 步为止（都是绝对序号）。
    分段推进时必须支持 from-step：否则第二段会从头再来一遍，
    把「1.获取公众号id」「2.批量下载文章」这类有副作用的按钮再点一次。
    """
    start = max(1, int(from_step or 1))
    stop = int(max_steps) if max_steps and max_steps > 0 else len(steps)
    if stop < start:
        raise ValueError(f"--max-steps({stop}) 小于 --from-step({start})，这段没有任何步骤可跑")
    return [(index, step) for index, step in enumerate(steps, 1) if start <= index <= stop]


def cmd_run(args: argparse.Namespace) -> int:
    profile = _load_profile(args.profile)
    window_spec = profile.get("window") or {}
    steps = profile.get("steps") or []
    if not isinstance(steps, list) or not steps:
        emit("param", "profile.no_steps", profile=args.profile)
        return EXIT_PARAM
    try:
        plan = slice_steps(steps, args.from_step, args.max_steps)
    except ValueError as exc:
        emit("param", "run.bad_range", error=str(exc))
        return EXIT_PARAM

    windows = find_windows(str(window_spec.get("regex") or ""), window_spec.get("classes"))
    emit("info", "run.start", profile=args.profile, dry_run=bool(args.dry_run),
         total_steps=len(steps), planned=len(plan), window_count=len(windows))
    if not windows:
        emit("error", "run.window_missing", regex=window_spec.get("regex"),
             hint="先手动打开目标软件；本技能不负责启动任意第三方程序")
        return EXIT_ENV
    window = attach(windows[0])
    _orig_rect = _window_rect(int(windows[0]["handle"]))   # 记下原位置，run 结束还原（点击可能挪动窗口避让遮挡）
    say("目标窗口: %r (handle=%s)" % (windows[0]["title"], windows[0]["handle"]))

    def _restore_win():
        # 还原工具窗口到进入时的位置，避免"避让遮挡挪动窗口"永久改变用户桌面布局。
        try:
            _move_window(int(windows[0]["handle"]), _orig_rect[0], _orig_rect[1])
        except Exception:
            pass

    context: dict = {}
    for item in getattr(args, "var", None) or []:
        if "=" not in item:
            emit("param", "run.bad_var", item=item, hint="--var 需要 KEY=VALUE 形式")
            return EXIT_PARAM
        key, _, val = item.partition("=")
        context.setdefault("vars", {})[key.strip()] = val
    results = []
    warned = 0
    skipped = 0
    for index, step in plan:
        label = step.get("name") or step.get("action")
        try:
            result = run_step(window, step, context, dry_run=bool(args.dry_run))
        except RuntimeError as exc:
            if step.get("optional"):
                # 可选步骤失败不打断流程（例如某台机器上这个选项是灰的）。
                # 但必须显式告警并计入 warned，不能静默放过。
                warned += 1
                emit("warn", "step.skipped", index=index, name=label, error=str(exc))
                say("  [%02d] %-28s warn  跳过（可选）: %s" % (index, label, exc))
                continue
            emit("error", "step.failed", index=index, name=label, error=str(exc))
            say("  [%02d] %-28s 失败: %s" % (index, label, exc))
            _restore_win()
            return EXIT_ERROR
        results.append(result)
        if result["status"] == "warn":
            warned += 1
        elif result["status"] == "skip":
            # skip 是合法分支（条件跳步/空变量），**只记账不计告警**：
            # 一旦混进 warned，退出码就变 5（PARTIAL），编排层会把正常流程当
            # 部分失败重跑，而重跑还会再跳一次，永远收不了尾。
            skipped += 1
        emit("info" if result["status"] != "warn" else "warn", "step.done",
             index=index, **result)
        say("  [%02d] %-28s %-5s %s" % (index, label, result["status"], result["detail"]))

    _restore_win()
    emit("info", "run.done", profile=args.profile, executed=len(results),
         skipped=skipped, warned=warned, dry_run=bool(args.dry_run))
    return EXIT_PARTIAL if warned else EXIT_OK


def cmd_verify(args: argparse.Namespace) -> int:
    """可逆自检：对每个 toggle 步骤做「开 -> 关 -> 还原」，不执行其他动作。"""
    profile = _load_profile(args.profile)
    window_spec = profile.get("window") or {}
    toggles = [s for s in (profile.get("steps") or [])
               if str(s.get("action")) == "toggle" and s.get("target")]
    if not toggles:
        emit("param", "verify.no_toggle_steps", profile=args.profile)
        return EXIT_PARAM
    windows = find_windows(str(window_spec.get("regex") or ""), window_spec.get("classes"))
    if not windows:
        emit("error", "verify.window_missing", regex=window_spec.get("regex"))
        return EXIT_ENV
    window = attach(windows[0])
    say("可逆自检: %d 个 toggle 步骤（每个开->关->还原）" % len(toggles))
    failures = 0
    skipped = 0
    for index, step in enumerate(toggles, 1):
        label = step.get("name") or "toggle"
        try:
            control = resolve(window, step["target"], timeout=float(step.get("timeout", 2)))
            origin = read_toggle(control)
            if origin == "?":
                emit("warn", "verify.unreadable", index=index, name=label,
                     note="控件不支持 Toggle 模式或状态不可读")
                failures += 1
                continue
            if is_enabled(control) is False:
                # 禁用控件翻不动是界面状态问题，不是链路坏了；如实记为跳过，
                # 否则会把"这个选项此刻灰着"误判成"自动点击失效"。
                emit("warn", "verify.disabled", index=index, name=label, origin=origin,
                     note="控件当前被禁用，无法翻转验证")
                say("  [%02d] %-20s %s  跳过（控件禁用，不可翻转）" % (index, label, origin))
                skipped += 1
                continue
            _acted, before, flipped = apply_toggle(control, None, origin)
            _acted2, _b2, restored = apply_toggle(control, None, flipped)
            ok = flipped != origin and restored == origin
            emit("info" if ok else "error", "verify.step", index=index, name=label,
                 origin=origin, flipped=flipped, restored=restored, ok=ok)
            say("  [%02d] %-20s %s -> %s -> %s  %s" % (
                index, label, origin, flipped, restored, "PASS" if ok else "FAIL"))
            if not ok:
                failures += 1
        except RuntimeError as exc:
            failures += 1
            emit("error", "verify.failed", index=index, name=label, error=str(exc))
            say("  [%02d] %-20s 失败: %s" % (index, label, exc))
    emit("info", "verify.done", checked=len(toggles), failures=failures, skipped=skipped)
    if failures:
        return EXIT_ERROR
    return EXIT_PARTIAL if skipped else EXIT_OK


# ------------------------------------------------------------------ 入口
def cmd_state(args: argparse.Namespace) -> int:
    """探测下载工具当前采集状态（读日志，只读）。返回 state JSON。"""
    res = probe_downloader_state(getattr(args, "log", None))
    emit("info", "downloader.state", **res)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="clicker.py", description="按 YAML 步骤表用 UIA 模式驱动桌面控件（模式优先，鼠标垫底）")
    sub = parser.add_subparsers(dest="command", required=True)

    probe = sub.add_parser("probe", help="侦察窗口与可交互控件（只读）")
    probe.add_argument("--window-regex", default=".*", help="窗口标题正则")
    probe.add_argument("--window-class", action="append", default=[],
                       help="类名白名单（可多次），不填则不限")
    probe.set_defaults(func=cmd_probe)

    run = sub.add_parser("run", help="执行步骤表")
    run.add_argument("--profile", required=True, help="profile 名（scripts/profiles/<name>.yaml）或路径")
    run.add_argument("--dry-run", action="store_true", help="只定位并打印将执行的步骤，不动控件")
    run.add_argument("--yes", action="store_true", help="确认执行（真执行写操作时必须带）")
    run.add_argument("--from-step", type=int, default=1, help="从第 N 步开始（分段推进用，默认 1）")
    run.add_argument("--max-steps", type=int, default=0, help="只跑到第 N 步（绝对序号，默认跑完）")
    run.add_argument("--var", action="append", default=[], metavar="KEY=VALUE",
                     help="模板变量：profile 里写 ${KEY}，这里传实际值（可重复）")
    run.set_defaults(func=cmd_run)

    verify = sub.add_parser("verify", help="可逆自检：toggle 步骤开->关->还原")
    verify.add_argument("--profile", required=True)
    verify.set_defaults(func=cmd_verify)

    state = sub.add_parser("state", help="探测下载工具当前采集状态（读日志，只读）")
    state.add_argument("--log", default=None,
                       help="指定日志文件（默认取当天最新 log*.txt）")
    state.set_defaults(func=cmd_state)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "run" and not args.dry_run and not args.yes:
        emit("param", "run.confirm_required",
             hint="真执行会真实操作目标软件，请加 --yes；只想看步骤用 --dry-run")
        return EXIT_PARAM
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
