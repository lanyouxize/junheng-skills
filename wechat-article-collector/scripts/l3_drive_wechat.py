#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L3 采集层：PC 微信自动驱动（mitmproxy local/regular 模式 + pywinauto UI 触发，用户协助）。

模块契约（SPEC §4 / team-lead 任务书）：
  - register(subparsers) 注册子命令 "desktop"，set_defaults(func=run)；
  - run(args) -> int 返回进程退出码（common.EXIT_*）；
  - 顶层仅标准库 + 本地契约模块（common / normalize / extract）；
    pywinauto 一律函数内 lazy_import，模块 import 本身永不失败；
  - 采集产物与 L1 同约定：25 列记录、record_id=uuid5(canonical)、
    body_ref=<media>/<record_id>.html、media_ref=<media>/<record_id>.media.json。

风险声明（SPEC §10，随交付保留）：
  L3 受微信版本 / 证书锁定 / 风控影响，标"用户协助"，不为稳定性背书。
  协议级 MITM 在 2026 证书锁定下可能失效；本设计只做文章页 HTTPS 抓取，
  不触碰协议逆向 / 签名伪造（SPEC §3 Out-of-Scope）。需管理员运行
  （mitmproxy local 模式需向 WeChatAppEx.exe 注入，Spec §2 / §11）。

流程（SPEC §9 AC-07/AC-08）：
  预检 -> 启动 mitmdump（local 透明劫持；失败按 --mitm-mode 降级 regular + 系统代理）
  -> pywinauto 连接微信主窗口 ->（--account 非空时）UI 定位公众号历史页
  -> 采集循环（轮询 capture 目录新 html -> extract_article -> 落盘/build/validate）
  -> 收尾（终止 mitmdump -> 还原系统代理 -> 写 JSONL -> l3.done 事件）。

退出码：预检失败 EXIT_ENV（依赖缺失）/ EXIT_ERROR（进程/端口/UI/子进程）；
采集正常结束 EXIT_OK；存在 fail 行 EXIT_PARTIAL；参数非法 EXIT_PARAM。

用法（独立自检，仅到预检为止，不启动微信/mitmdump）：
    python l3_drive_wechat.py desktop --help
统一入口（用户协助，P2 硬 gate，Spec §12 V4）：
    python collect.py desktop --account "样本号" --assist --out /tmp/v4.jsonl --yes
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

from common import (
    EXIT_ENV,
    EXIT_ERROR,
    EXIT_OK,
    EXIT_PARAM,
    EXIT_PARTIAL,
    LEVEL_ENV,
    LEVEL_ERROR,
    LEVEL_INFO,
    LEVEL_PARAM,
    LEVEL_WARN,
    download_file,
    emit_event,
    guess_image_ext,
    lazy_import,
    load_config,
    sleep_polite,
    write_jsonl,
)
from extract import extract_article
from normalize import build_article, canonicalize_url, validate_article

EXTRACTOR = "l3:mitm+uia"
COLLECT_LAYER = "desktop"

_SCRIPT_DIR = Path(__file__).resolve().parent
_ADDON_PATH = _SCRIPT_DIR / "addons" / "wechat_article_addon.py"
_CONFDIR = Path.home() / ".mitmproxy"
_CA_CERT = _CONFDIR / "mitmproxy-ca-cert.cer"
_POLL_INTERVAL = 2.0        # 采集循环轮询间隔（秒）
_MITM_STARTUP_WAIT = 3.0    # mitmdump 启动后探活等待（秒）
_TYPEKEYS_SPECIAL_RE = re.compile(r"([{()^%+])")
_WECHAT_CANDIDATES = (
    r"%ProgramFiles%\Tencent\Weixin\Weixin.exe",           # 微信 4.x（2026 现行）
    r"%ProgramFiles(x86)%\Tencent\Weixin\Weixin.exe",
    r"%ProgramW6432%\Tencent\Weixin\Weixin.exe",
    r"%LOCALAPPDATA%\Tencent\Weixin\Weixin.exe",
    r"%ProgramFiles%\Tencent\WeChat\WeChat.exe",           # 微信 3.x（旧版）
    r"%ProgramFiles(x86)%\Tencent\WeChat\WeChat.exe",
    r"%ProgramW6432%\Tencent\WeChat\WeChat.exe",
    r"%LOCALAPPDATA%\Tencent\WeChat\WeChat.exe",
)
# 主进程映像名：4.x 为 Weixin.exe，3.x 为 WeChat.exe；tasklist 过滤大小写不敏感，两代都试
_WECHAT_IMAGES = ("Weixin.exe", "WeChat.exe")

# mitmproxy 工作模式：
#   local   —— WinDivert 内核过滤器透明劫持（无需改系统代理，但需驱动能加载）
#   regular —— 普通 HTTP 代理，需让微信走系统代理（不依赖内核驱动）
#   auto    —— 先试 local，启动即失败则自动降级 regular（并临时改系统代理）
_MITM_MODES = ("auto", "local", "regular")
# local 模式启动失败时 mitmdump 日志里的特征串（2026-10-22 真机实测：
# WinDivert 2.2.2 的驱动签名证书 2023-05 过期 + 本机 HVCI/驱动黑名单开启
# -> WinDivertOpen 返回 ERROR_ACCESS_DENIED(5)，redirector 立刻退出，
#    而 mitmdump 主进程仍活着 —— 只判"进程存活"会把启动失败当成成功）
_REDIRECTOR_FAIL_MARKS = (
    "redirect daemon exited prematurely",
    "Local redirector failed",
    "Task failed:",
)
_PROXY_BACKUP_NAME = "_proxy_backup.json"
_INTERNET_SETTINGS_KEY = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"


# ------------------------------------------------------------------ 参数注册
def register(subparsers: argparse._SubParsersAction) -> None:
    """注册子命令 "desktop"（供 collect.py 统一入口与本文件独立 main 复用）。"""
    parser = subparsers.add_parser(
        "desktop",
        help="L3：PC 微信自动驱动（mitmproxy + pywinauto，用户协助，P2 脆弱层）",
        description=(
            "L3 采集层：mitmproxy local 模式捕获 PC 微信文章页 HTML，"
            "pywinauto 辅助定位公众号历史页；需管理员 + 微信登录态（用户协助）。"
        ),
    )
    parser.add_argument(
        "--account", default="",
        help="公众号名称；为空则不自动定位，纯 --assist 人工触发文章页",
    )
    parser.add_argument(
        "--assist", action=argparse.BooleanOptionalAction, default=True,
        help="用户协助触发文章页（默认开；人工在微信中逐篇打开文章）",
    )
    parser.add_argument(
        "--wechat-path", default="",
        help="WeChat.exe 路径（默认取 config l3.wechat_path，为空则探测常见安装路径）",
    )
    parser.add_argument(
        "--capture-window", type=int, default=300,
        help="采集窗口秒数（默认 300；窗口内轮询 capture 目录）",
    )
    parser.add_argument("--out", default="", help="输出 JSONL 路径（默认写 stdout）")
    parser.add_argument(
        "--media-dir", default="",
        help="正文/媒体清单落盘目录（默认 '<out 去扩展名>.media/'；--out 省略时为 ./wechat-collected-media/）",
    )
    parser.add_argument(
        "--proxy-port", type=int, default=None,
        help="mitmdump 监听端口（默认取 config l3.proxy_port=8080）",
    )
    parser.add_argument(
        "--mitm-mode", choices=_MITM_MODES, default="auto",
        help=(
            "mitmproxy 工作模式：local=WinDivert 透明劫持（默认首选，需驱动可加载）；"
            "regular=普通 HTTP 代理（需微信走系统代理）；auto=先 local，启动失败自动降级 regular"
        ),
    )
    parser.add_argument(
        "--system-proxy", action=argparse.BooleanOptionalAction, default=None,
        help=(
            "regular 模式下是否临时把 Windows 系统代理指向本机 mitmdump（默认 auto 降级时自动开启）；"
            "无论成功失败都会在退出时还原原值"
        ),
    )
    parser.add_argument(
        "--timeout", type=int, default=30,
        help="单张图片下载超时秒（默认 30）",
    )
    parser.add_argument(
        "--download-images", dest="download_images", action="store_true", default=True,
        help="下载正文图片到媒体目录（默认行为，显式声明用）",
    )
    parser.add_argument(
        "--no-images", dest="download_images", action="store_false",
        help="只记录图片 URL 不下载（与 L1 同名参数一致）",
    )
    parser.set_defaults(func=run)


# ------------------------------------------------------------------ 主流程
def run(args: argparse.Namespace) -> int:
    """执行 L3 采集，返回退出码（EXIT_OK / EXIT_PARTIAL / EXIT_PARAM / EXIT_ENV / EXIT_ERROR）。"""
    config = load_config(getattr(args, "config", ""))
    out_path = (getattr(args, "out", "") or "").strip()
    media_dir = _resolve_media_dir(args)
    capture_dir = _capture_dir_for(out_path)
    window = int(getattr(args, "capture_window", 300) or 0)
    port = _resolve_port(args, config)
    wechat_path = _resolve_wechat_path(args, config)
    account = (getattr(args, "account", "") or "").strip()

    if window <= 0:
        emit_event(LEVEL_PARAM, "l3.param", reason="--capture-window 必须为正整数")
        return EXIT_PARAM
    if not 0 < port < 65536:
        emit_event(LEVEL_PARAM, "l3.param", reason=f"--proxy-port 非法: {port}")
        return EXIT_PARAM

    emit_event(
        LEVEL_INFO, "l3.start",
        account=account or None, assist=bool(getattr(args, "assist", True)),
        capture_window=window, out=out_path or "stdout", media_dir=str(media_dir),
        capture_dir=str(capture_dir), proxy_port=port, wechat_path=wechat_path or None,
        mitm_mode=str(getattr(args, "mitm_mode", "auto") or "auto"),
    )

    # 1) 预检（AC-08：任一不过即非零退出，不盲目运行）
    mitm_cmd = _resolve_mitmdump()
    precheck = _precheck(mitm_cmd, wechat_path, port)
    if precheck is not None:
        _remove_if_empty(capture_dir)
        return precheck

    try:
        os.makedirs(capture_dir, exist_ok=True)
    except OSError as exc:
        emit_event(LEVEL_ERROR, "l3.capture_dir", ok=False, capture_dir=str(capture_dir), error=str(exc))
        return EXIT_ERROR

    # 2) 启动 mitmdump 子进程（模式按 --mitm-mode；auto 时 local 失败自动降级 regular）
    #    先清掉上次被强杀可能残留的代理备份，避免"代理指向已死端口"的断网状态
    if _recover_stale_proxy_backup(capture_dir):
        emit_event(LEVEL_WARN, "l3.proxy", step="recover", ok=True,
                   note="检测到上次运行残留的系统代理备份，已先还原")
    proc, mitm_mode, proxy_backup = _bring_up_mitm(args, mitm_cmd, port, capture_dir)
    if proc is None:
        return EXIT_ERROR

    # 3) UI 自动定位 + 4) 采集循环；finally 保证 mitmdump 一定被收尾
    try:
        if account:
            try:
                main_window = _connect_main_window(wechat_path)
                _ui_open_account_history(main_window, account)
            except Exception as exc:
                # UI 自动导航只是"省一次手动点击"的便利，不是采集前置条件：
                # mitmdump 已在拦截，只要用户在窗口期内打开文章就照样能抓到。
                # 故 assist 模式下降级为 warn 继续（真机实测：微信 4.x Qt 重写后
                # 主窗口类名/树结构全变，pywinauto 定位必然失败——不能因此判死）。
                if bool(getattr(args, "assist", True)):
                    emit_event(
                        LEVEL_WARN, "l3.ui", step="navigate", ok=False, account=account,
                        error=str(exc),
                        note="UI 自动导航失败，已降级为人工触发：微信窗口已尽量置前，请在微信中手动打开目标文章",
                        hint=(
                            "微信 4.x 主窗口为自绘 Qt（实测一级子控件仅 2 个不透明 Pane："
                            "Weixin / MMUIRenderSubWindow），无可用 UIA 控件树 => 深层点击不可自动化；"
                            "拦截侧不受影响，人工打开文章仍会被捕获"
                        ),
                    )
                else:
                    emit_event(
                        LEVEL_ERROR, "l3.ui", step="navigate", ok=False, account=account,
                        error=str(exc),
                        hint="未开启 --assist 且 UI 自动定位失败，无人工兜底；"
                             "可加 --assist 后手动打开文章",
                    )
                    return EXIT_ERROR
        else:
            emit_event(
                LEVEL_INFO, "l3.ui", step="navigate", skipped=True,
                note="未提供 --account，跳过 UI 自动定位（纯 --assist 人工触发）",
            )

        if bool(getattr(args, "assist", True)):
            _print_assist_hint(account)

        records, stats, loop_status = _capture_loop(
            capture_dir, media_dir, proc, window, account,
            {
                "download_images": bool(getattr(args, "download_images", True)),
                "timeout": int(getattr(args, "timeout", 30) or 30),
                "config": config,
            },
        )
    finally:
        _stop_mitmdump(proc)
        # 系统代理必须无条件还原（哪怕采集抛异常）：否则整机流量指向已关闭端口
        if proxy_backup:
            if _system_proxy_restore(proxy_backup):
                emit_event(LEVEL_INFO, "l3.proxy", step="restored", ok=True,
                           note="系统代理已还原为运行前设置")
                try:
                    (Path(capture_dir) / _PROXY_BACKUP_NAME).unlink(missing_ok=True)
                except OSError:
                    pass
            else:
                emit_event(
                    LEVEL_WARN, "l3.proxy", step="restore", ok=False,
                    backup=proxy_backup,
                    hint="系统代理还原失败，请手工检查『设置 -> 网络和 Internet -> 代理』"
                         "或重置为运行前值",
                )

    # 5) 收尾：写 JSONL + l3.done 事件
    if out_path:
        try:
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            emit_event(LEVEL_ERROR, "l3.out", ok=False, out=out_path, error=str(exc))
            return EXIT_ERROR
    written = write_jsonl(out_path or None, records)
    emit_event(
        LEVEL_INFO, "l3.done",
        captured=stats["captured"], total=len(records),
        ok=stats["ok"], partial=stats["partial"], fail=stats["fail"],
        written=written, status=loop_status,
    )

    # 6) 退出码
    if loop_status == "mitmdump_died":
        return EXIT_ERROR
    if loop_status == "interrupted":
        return EXIT_PARTIAL
    if stats["fail"] > 0:
        return EXIT_PARTIAL
    return EXIT_OK


# ------------------------------------------------------------------ 预检（AC-08）
def _precheck(mitm_cmd: list[str] | None, wechat_path: str, port: int) -> int | None:
    """返回 None 表示通过；否则返回退出码（事件已发出，不盲目运行）。"""
    # ① pywinauto 可导入（依赖缺失 -> EXIT_ENV）
    try:
        lazy_import("pywinauto", "pip install pywinauto pywin32 comtypes")
    except RuntimeError as exc:
        emit_event(LEVEL_ENV, "l3.precheck", step="pywinauto", ok=False, error=str(exc))
        return EXIT_ENV
    emit_event(LEVEL_INFO, "l3.precheck", step="pywinauto", ok=True)

    # ② mitmdump 可用（PATH / 当前 Python Scripts / python -m mitmproxy 探活）
    if mitm_cmd is None:
        emit_event(
            LEVEL_ENV, "l3.precheck", step="mitmdump", ok=False,
            error="未找到 mitmdump（PATH 与当前 Python Scripts 目录均无，python -m mitmproxy 探活失败）",
            hint="pip install mitmproxy==12.2.1",
        )
        return EXIT_ENV
    emit_event(LEVEL_INFO, "l3.precheck", step="mitmdump", ok=True, cmd=mitm_cmd[0])

    # ③ addon 文件在位（技能自身文件，缺失按依赖缺失处理）
    if not _ADDON_PATH.is_file():
        emit_event(
            LEVEL_ENV, "l3.precheck", step="addon", ok=False,
            error=f"mitmproxy addon 不存在: {_ADDON_PATH}",
        )
        return EXIT_ENV
    emit_event(LEVEL_INFO, "l3.precheck", step="addon", ok=True, addon=str(_ADDON_PATH))

    # ④ mitmproxy CA 已生成（AC-08 / Spec §11：CA 未装 -> 预检失败退出）
    if not _CA_CERT.is_file():
        emit_event(
            LEVEL_ENV, "l3.precheck", step="ca", ok=False,
            error=f"未找到 mitmproxy CA 证书: {_CA_CERT}",
            hint="先运行一次 mitmdump 生成 CA，再以管理员执行 "
                 "certutil -addstore Root mitmproxy-ca-cert.cer 装入受信任根",
        )
        return EXIT_ENV
    emit_event(
        LEVEL_INFO, "l3.precheck", step="ca", ok=True, ca=str(_CA_CERT),
        note="已找到 CA 文件；请确认已装入『受信任的根证书颁发机构』（否则微信不信任、无法解密）",
    )

    # ⑤ 微信进程在运行（tasklist 映像名，兼容 WeChat.exe/Wechat.exe；进程缺失 -> EXIT_ERROR）
    running, reason = _wechat_running()
    if not running:
        emit_event(
            LEVEL_ERROR, "l3.precheck", step="wechat_process", ok=False,
            error=reason or "未检测到 WeChat.exe 进程",
            hint=(f"请先启动并登录 PC 微信（探测路径: {wechat_path}）" if wechat_path
                  else "请先启动并登录 PC 微信（未探测到安装路径，可用 --wechat-path 指定）"),
        )
        return EXIT_ERROR
    emit_event(LEVEL_INFO, "l3.precheck", step="wechat_process", ok=True)

    # ⑥ 残留 mitmdump 进程（local 模式用 WinDivert 驱动，多实例会互相抢过滤器 -> EXIT_ERROR）
    #    注意：**不检测端口占用**——local 模式是透明劫持，根本不监听端口（2026-10-22 实测：
    #    regular 模式端口可达=True，local 模式可达=False 但进程正常工作）。
    #    旧版拿"端口在监听"当启动成功判据，会在任何机器上把 L3 判死。
    if _mitmdump_running():
        emit_event(
            LEVEL_ERROR, "l3.precheck", step="mitmdump_stale", ok=False,
            error="检测到已在运行的 mitmdump.exe（WinDivert 过滤器会被抢占）",
            hint="先结束残留进程：taskkill /IM mitmdump.exe /F；或确认上次 L3 已正常退出",
        )
        return EXIT_ERROR
    emit_event(LEVEL_INFO, "l3.precheck", step="mitmdump_stale", ok=True,
               port=port, mode="按 --mitm-mode 选择（local 透明劫持不监听端口；regular 监听端口）")

    # 管理员提示（local 模式注入通常需要；不硬拦截，交给 mitmdump 启动探活）
    if not _is_admin():
        emit_event(
            LEVEL_WARN, "l3.precheck", step="admin", ok=False,
            note="当前非管理员会话；mitmproxy local 模式注入通常需要管理员权限，启动可能失败",
        )
    return None


def _resolve_mitmdump() -> list[str] | None:
    """解析 mitmdump 启动命令（多重兜底）；不可用返回 None。"""
    found = shutil.which("mitmdump")
    if found:
        return [found]
    scripts_dir = Path(sys.executable).resolve().parent
    for name in ("mitmdump.exe", "mitmdump"):
        candidate = scripts_dir / name
        if candidate.is_file():
            return [str(candidate)]
    # 兜底：python -m mitmproxy 探活；包可用则经 tools.main 入口以 mitmdump 角色启动
    try:
        probe = subprocess.run(
            [sys.executable, "-m", "mitmproxy", "--version"],
            capture_output=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if probe.returncode == 0:
        return [sys.executable, "-c",
                "import sys; from mitmproxy.tools.main import mitmdump; sys.exit(mitmdump())"]
    return None


def _wechat_running() -> tuple[bool, str]:
    """tasklist 检测微信进程；中文/英文 Windows 映像名大小写兼容。

    字节模式判定（不做文本解码）：中文 Windows 的 tasklist 输出为 GBK，
    按 UTF-8 解码会静默丢输出导致误判，这里只做 ASCII 包含检查，编码无关。

    微信 4.x 起主进程映像名由 `WeChat.exe` 改为 `Weixin.exe`（2026-10-22 真机实测），
    只认旧名会把"已登录的微信"误判为未启动、直接把 L3 拦死，故两代名字都认。
    """
    last_error = ""
    for image in _WECHAT_IMAGES:
        try:
            proc = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {image}", "/NH"],
                capture_output=True, timeout=15,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            last_error = f"tasklist 执行失败: {exc}"
            continue
        if image.lower().encode("ascii") in (proc.stdout or b"").lower():
            return True, ""
    return False, last_error or (
        f"tasklist 未列出微信主进程（已尝试 {'/'.join(_WECHAT_IMAGES)}；"
        "微信未启动，或为未适配的新映像名）"
    )


def _mitmdump_running() -> bool:
    """是否已有 mitmdump.exe 在跑。

    local 模式用 WinDivert 内核过滤器劫持流量，同一时刻只能被一个实例持有；
    残留实例会让新实例静默失效（进程活着但抓不到包），故启动前必须先判。
    判定用字节包含（tasklist 输出受代码页影响，不做文本解码），与微信进程探测一致。

    历史教训（2026-10-22 真机实测）：旧版把"端口是否在监听"当作 mitmdump 启动成功
    的判据，但 local 模式**不监听任何端口**（regular 模式才监听），结果在任何机器上
    都会误判"启动失败"并把 L3 拦死；另外本机对无人监听的回环端口丢包而非回 RST，
    connect 试探也分不清"空闲"与"被过滤"。故此处改用进程判据，彻底不碰端口。
    """
    try:
        proc = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq mitmdump.exe", "/NH"],
            capture_output=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return b"mitmdump.exe" in (proc.stdout or b"").lower()


def _is_admin() -> bool:
    """Windows 管理员会话检测（非 Windows 或检测失败按非管理员处理）。"""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


# ------------------------------------------------------------------ mitmdump 子进程
def _read_log(log_path: Path, limit: int = 8192) -> str:
    """读取 mitmdump 日志尾部（UTF-8 容错；文件不存在/读失败返回空串）。"""
    try:
        data = log_path.read_bytes()
    except OSError:
        return ""
    return data[-limit:].decode("utf-8", "replace")


def _redirector_failed(log_text: str) -> str:
    """日志里是否出现 local 模式重定向器失败特征；命中则返回命中的特征串。"""
    lowered = (log_text or "").lower()
    for mark in _REDIRECTOR_FAIL_MARKS:
        if mark.lower() in lowered:
            return mark
    return ""


def _mitm_mode_args(mode: str, port: int) -> list[str]:
    """按模式拼 mitmdump 的 --mode 参数（local 透明劫持 / regular 普通代理）。"""
    if mode == "regular":
        return ["--mode", "regular", "--listen-port", str(port)]
    return ["--mode", "local:WeChatAppEx.exe"]


def _start_mitmdump(mitm_cmd: list[str], port: int, capture_dir: str, mode: str = "local"):
    """启动 mitmdump（指定模式 + addon），等待探活；失败返回 None（事件已发出）。

    探活判据（2026-10-22 真机校准，两条都必要）：
      ① 子进程存活 —— 排除"启动即崩"；
      ② 日志无重定向器失败特征 —— local 模式下 WinDivert 驱动装不上时，
         mitmdump 主进程会**继续存活**，只有 redirector 子进程退出，
         此时进程判据为真、功能为假（实测：5 分钟窗口 0 捕获）。
    """
    cmd = list(mitm_cmd) + _mitm_mode_args(mode, port) + [
        "-s", str(_ADDON_PATH),
        "--set", f"listen_port={port}",
        "--set", f"confdir={_CONFDIR}",
    ]
    env = os.environ.copy()
    env["WECHAT_CAPTURE_DIR"] = str(Path(capture_dir).resolve())
    # 关键：mitmdump 日志重定向到文件时 stdout 是块缓冲，被 terminate（Windows
    # TerminateProcess）终止时缓冲区整体丢弃 -> 日志永远 0 字节，故障无法定位。
    env["PYTHONUNBUFFERED"] = "1"
    log_path = Path(capture_dir) / "_mitmdump.log"
    try:
        log_handle = open(log_path, "w", encoding="utf-8", errors="replace")
    except OSError as exc:
        emit_event(LEVEL_ERROR, "l3.mitmdump", step="log", ok=False, error=str(exc))
        return None
    try:
        try:
            proc = subprocess.Popen(
                cmd, env=env, stdout=log_handle, stderr=subprocess.STDOUT, cwd=str(_SCRIPT_DIR),
            )
        except OSError as exc:
            emit_event(LEVEL_ERROR, "l3.mitmdump", step="spawn", ok=False, error=str(exc), cmd=cmd)
            return None
    finally:
        log_handle.close()

    time.sleep(_MITM_STARTUP_WAIT)
    if proc.poll() is not None:
        emit_event(
            LEVEL_ERROR, "l3.mitmdump", step="startup", ok=False, mode=mode,
            returncode=proc.returncode, log=str(log_path),
            log_tail=_read_log(log_path, 1200),
            hint="local 模式需管理员运行且微信已登录；regular 模式需端口未被占用。详见日志",
        )
        return None

    fail_mark = _redirector_failed(_read_log(log_path))
    if fail_mark:
        _stop_mitmdump(proc)
        emit_event(
            LEVEL_ERROR, "l3.mitmdump", step="redirector", ok=False, mode=mode,
            returncode=proc.returncode, log=str(log_path), matched=fail_mark,
            log_tail=_read_log(log_path, 1200),
            hint=(
                "local 模式透明劫持不可用：WinDivert 驱动未能加载"
                "（常见原因：驱动签名过期/被系统驱动黑名单拦截/HVCI 开启）。"
                "改用 --mitm-mode regular（配合 --system-proxy）可绕开内核驱动"
            ),
        )
        return None

    emit_event(
        LEVEL_INFO, "l3.mitmdump", step="started", ok=True, pid=proc.pid, port=port,
        capture_dir=str(Path(capture_dir).resolve()), log=str(log_path), mode=mode,
        note=(
            "local 模式已注入 WeChatAppEx.exe（透明劫持，不监听端口）；文章页 HTTPS 将经 mitmdump 解密"
            if mode == "local" else
            f"regular 模式监听 127.0.0.1:{port}；需微信走系统代理才能拦截文章页"
        ),
    )
    return proc


def _stop_mitmdump(proc) -> None:
    """收尾 mitmdump：terminate，超时 kill（不静默失败）。"""
    if proc is None:
        return
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=5)
            except subprocess.SubprocessError:
                pass
    emit_event(LEVEL_INFO, "l3.mitmdump", step="stopped", returncode=proc.returncode)


# ------------------------------------------------------------------ 系统代理（regular 模式）
def _wininet_notify() -> None:
    """通知 WinINet 设置已变更（否则新代理要等应用重启才生效）。失败静默。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        internet_option_refresh = 37
        internet_option_settings_changed = 39
        for option in (internet_option_settings_changed, internet_option_refresh):
            ctypes.windll.wininet.InternetSetOptionW(None, option, None, 0)
    except Exception:
        pass


def _system_proxy_read() -> dict:
    """读取当前用户代理设置；非 Windows 或读失败返回空 dict。"""
    if sys.platform != "win32":
        return {}
    try:
        import winreg

        state: dict = {}
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _INTERNET_SETTINGS_KEY) as key:
            for name in ("ProxyEnable", "ProxyServer", "ProxyOverride"):
                try:
                    state[name] = winreg.QueryValueEx(key, name)[0]
                except FileNotFoundError:
                    state[name] = None
        return state
    except OSError:
        return {}


def _system_proxy_apply(port: int, capture_dir: Path) -> dict:
    """把系统代理指向 127.0.0.1:<port>，并先落盘原值备份；返回备份 dict。

    备份写入 `<capture_dir>/_proxy_backup.json`：进程被强杀时，下次运行可据此还原，
    避免"代理被改成指向已关闭端口 -> 整机断网"这种最坏后果。
    """
    if sys.platform != "win32":
        return {}
    import winreg

    backup = _system_proxy_read()
    backup["_applied"] = True
    try:
        (Path(capture_dir) / _PROXY_BACKUP_NAME).write_text(
            json.dumps(backup, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _INTERNET_SETTINGS_KEY,
                        0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, f"127.0.0.1:{port}")
        if not backup.get("ProxyOverride"):
            winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, "<local>")
    _wininet_notify()
    return backup


def _system_proxy_restore(backup: dict) -> bool:
    """按备份还原系统代理；返回是否真的改了注册表。备份不完整则不动（宁可不改）。"""
    if sys.platform != "win32" or not backup:
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _INTERNET_SETTINGS_KEY,
                            0, winreg.KEY_SET_VALUE) as key:
            enable = backup.get("ProxyEnable")
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD,
                              int(enable) if enable is not None else 0)
            server = backup.get("ProxyServer")
            if server is not None:
                winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, str(server))
            override = backup.get("ProxyOverride")
            if override is not None:
                winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, str(override))
    except OSError:
        return False
    _wininet_notify()
    return True


def _recover_stale_proxy_backup(capture_dir: Path) -> bool:
    """上次运行被强杀留下的代理备份 -> 启动时先还原（幂等，无备份返回 False）。"""
    path = Path(capture_dir) / _PROXY_BACKUP_NAME
    if not path.is_file():
        return False
    try:
        backup = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        path.unlink(missing_ok=True)
        return False
    restored = _system_proxy_restore(backup)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
    return restored


# ------------------------------------------------------------------ 启动编排（模式降级）
def _bring_up_mitm(args, mitm_cmd: list[str], port: int, capture_dir: Path):
    """按 --mitm-mode 启动 mitmdump，必要时降级 regular；返回 (proc, mode, proxy_backup)。

    local（WinDivert 透明劫持）在驱动不能加载的机器上**必然**失败且 mitmdump 主进程
    仍存活，故先启动 local、读日志确认 redirector 起来没有；起不来再退 regular
    （普通代理，靠系统代理把微信流量导入，不需要内核驱动）。

    auto 语义：有一层能用就交付，不因为首选路径在本机不可用而把整层判死。
    """
    requested = str(getattr(args, "mitm_mode", "auto") or "auto")

    if requested in ("auto", "local"):
        proc = _start_mitmdump(mitm_cmd, port, capture_dir, mode="local")
        if proc is not None:
            return proc, "local", {}
        if requested == "local":
            return None, "local", {}
        emit_event(
            LEVEL_WARN, "l3.mitm_mode", step="fallback", ok=True, from_mode="local",
            to_mode="regular",
            note="local 模式不可用（内核驱动未能加载），自动降级为 regular 代理模式",
        )

    proc = _start_mitmdump(mitm_cmd, port, capture_dir, mode="regular")
    if proc is None:
        return None, "regular", {}

    want_proxy = getattr(args, "system_proxy", None)
    if want_proxy is None:
        want_proxy = True   # auto：降级到 regular 时默认接管系统代理，否则抓不到包
    proxy_backup: dict = {}
    if want_proxy:
        try:
            proxy_backup = _system_proxy_apply(port, capture_dir)
        except OSError as exc:
            emit_event(
                LEVEL_ERROR, "l3.proxy", step="apply", ok=False, error=str(exc),
                hint="无法写入 HKCU 系统代理；可手工把 Windows 代理设为 127.0.0.1:%d" % port,
            )
            _stop_mitmdump(proc)
            return None, "regular", {}
        emit_event(
            LEVEL_INFO, "l3.proxy", step="applied", ok=True, port=port,
            proxy_server=f"127.0.0.1:{port}",
            previous_enable=proxy_backup.get("ProxyEnable"),
            previous_server=proxy_backup.get("ProxyServer"),
            note="已临时把 Windows 系统代理指向 mitmdump；退出时自动还原",
        )
    return proc, "regular", proxy_backup


# ------------------------------------------------------------------ pywinauto UI 触发
# 微信主窗口的 UIA 定位偏好（2026-10-22 真机枚举结果）：
#   微信 4.x 主窗口 = class `Qt51514QWindowIcon` / title `微信`（主进程 Weixin.exe）；
#   3.x 主窗口      = class `WeChatMainWndForPC`；
#   同名的 `Chrome_WidgetWin_0` 是内置浏览器容器（WeChatAppEx 子进程），**不是**主窗口，
#   旧实现按 title_re='微信' + found_index=0 抓到的恰恰可能是它，于是后续点不到任何控件。
_WECHAT_MAIN_CLASSES = ("WeChatMainWndForPC", "Qt51514QWindowIcon")
# 标题必须是**精确等于**这几个之一：子串匹配会误收「微信公众平台 - Chrome」这类浏览器窗口
# （2026-10-22 用例反证：substring 匹配把 Chrome_WidgetWin_1 的公众号后台当成微信主窗口）。
_WECHAT_WINDOW_TITLES = frozenset({"微信", "wechat", "weixin"})


def _find_wechat_windows() -> list[dict]:
    """枚举顶层窗口，返回疑似微信主窗口的候选（按可信度排序）。

    判据：标题命中 _WECHAT_WINDOW_TITLES；class 命中 _WECHAT_MAIN_CLASSES 的排前面
    （Qt 主窗口 > 3.x 类名 > 其他同名 webview 容器）。读不到的窗口静默跳过。
    """
    pywinauto = lazy_import("pywinauto", "pip install pywinauto pywin32 comtypes")
    candidates: list[dict] = []
    try:
        desktop = pywinauto.Desktop(backend="uia")
        windows = desktop.windows()
    except Exception:
        return candidates
    for window in windows:
        try:
            title = (window.window_text() or "").strip()
            class_name = window.class_name() or ""
            pid = window.process_id()
            handle = window.handle
        except Exception:
            continue
        if not title or title.strip().casefold() not in _WECHAT_WINDOW_TITLES:
            continue
        rank = _WECHAT_MAIN_CLASSES.index(class_name) if class_name in _WECHAT_MAIN_CLASSES else len(_WECHAT_MAIN_CLASSES)
        candidates.append({
            "pid": pid, "handle": handle, "title": title,
            "class_name": class_name, "rank": rank,
        })
    candidates.sort(key=lambda item: item["rank"])
    return candidates


def _connect_main_window(wechat_path: str = ""):
    """连接微信主窗口（backend=uia）；失败抛 RuntimeError（附已探测到的候选，便于排错）。

    定位策略（2026-10-22 立）：不再"连上进程再猜窗口"，而是先枚举顶层窗口拿到
    真实 handle，再按 handle 连接 —— 微信 4.x 有 5 个 Weixin.exe 进程、且同名
    `Chrome_WidgetWin_0` 也叫『微信』，按进程 + title_re 猜必然连错窗口。
    """
    pywinauto = lazy_import("pywinauto", "pip install pywinauto pywin32 comtypes")
    candidates = _find_wechat_windows()
    if not candidates:
        raise RuntimeError(
            "未枚举到标题含『微信』的顶层窗口（请确认 PC 微信已启动并登录，且未最小化到托盘）"
        )
    chosen = candidates[0]
    try:
        app = pywinauto.Application(backend="uia").connect(process=chosen["pid"])
        main_window = app.window(handle=chosen["handle"])
    except Exception as exc:
        raise RuntimeError(
            f"已找到微信窗口（class={chosen['class_name']}, pid={chosen['pid']}）但连接失败: {exc}"
        ) from exc
    if not main_window.exists(timeout=3):
        raise RuntimeError(
            f"微信窗口句柄存在但 UIA 节点不可用（class={chosen['class_name']}, handle={chosen['handle']}）"
        )
    try:
        if main_window.get_show_state() == 2:  # SW_SHOWMINIMIZED
            main_window.restore()
        main_window.set_focus()
    except Exception:
        pass
    emit_event(
        LEVEL_INFO, "l3.ui", step="window", ok=True, class_name=chosen["class_name"],
        title=chosen["title"], pid=chosen["pid"], handle=chosen["handle"],
        candidate_count=len(candidates),
        note="已定位微信主窗口并置前；UIA 控件结构随微信版本变化，导航失败会自动降级为人工触发",
    )
    return main_window


def _find_child(parent, specs: list[dict], timeout: float = 1.0):
    """按兜底选择器列表（Name/ClassName/AutomationId/control_type 组合）查找子控件。"""
    for spec in specs:
        try:
            control = parent.child_window(**spec)
            if control.exists(timeout=timeout):
                return control
        except Exception:
            continue
    return None


def _escape_type_keys(text: str) -> str:
    """转义 type_keys 特殊字符（花括号强制按字面发送）。"""
    return _TYPEKEYS_SPECIAL_RE.sub(r"{\1}", text)


def _ui_controls_available(main_window) -> bool:
    """窗口是否暴露可交互的 UIA 控件（Edit / Button）。

    微信 4.x 主窗口是自绘 Qt：实测一级子控件只有 2 个不透明 Pane
    （`Weixin` / `MMUIRenderSubWindow`），整棵树没有 Edit/Button。
    此时后面的多选择器盲试纯属浪费（真机实测每条耗时约 15s，窗口期白烧），
    故先花一次探测把结论拿到，再直接降级人工触发。
    """
    for control_type in ("Edit", "Button"):
        try:
            if main_window.descendants(control_type=control_type):
                return True
        except Exception:
            continue
    return False


def _ui_open_account_history(main_window, account: str) -> None:
    """UI 自动定位公众号历史页；每步 try/except，失败抛 RuntimeError（调用方转 assist 提示）。

    UI 结构随微信版本漂移，不硬编码单一控件路径：
      0) 先探测窗口是否有 UIA 控件树（自绘窗口直接放弃，不做无效盲试）；
      1) 打开搜索（按钮多重选择器，失败兜底 Ctrl+F 快捷键）；
      2) 定位搜索输入框（Edit 多重选择器）并输入公众号名；
      3) 回车提交，点击搜索结果（名称包含 account 的条目优先，首个条目兜底）；
      4) 尽力进入历史文章页（按钮/条目名正则；失败仅告警不阻断，交由用户协助）。
    """
    # 0) 能力探测：没有控件树就不要盲试
    if not _ui_controls_available(main_window):
        raise RuntimeError(
            "窗口内没有任何 Edit/Button 控件（自绘 Qt 窗口，UIA 树不可交互）"
        )

    # 1) 打开搜索
    opened = False
    search = _find_child(main_window, [
        {"control_type": "Button", "title": "搜索"},
        {"title": "搜索"},
        {"auto_id": "search"},
        {"control_type": "Button", "title_re": "搜索"},
    ], timeout=2.0)
    if search is not None:
        try:
            search.click_input()
            opened = True
        except Exception:
            opened = False
    if not opened:
        try:
            main_window.type_keys("^f")  # PC 微信内置搜索快捷键兜底
            opened = True
        except Exception:
            opened = False
    if not opened:
        raise RuntimeError("无法打开搜索框（按钮点击与 Ctrl+F 快捷键均失败）")
    time.sleep(1.0)

    # 2) 定位输入框并输入公众号名
    edit = _find_child(main_window, [
        {"control_type": "Edit", "found_index": 0},
        {"auto_id": "search_input"},
        {"class_name": "Edit", "found_index": 0},
    ], timeout=2.0)
    if edit is None:
        raise RuntimeError("未找到搜索输入框（Edit 控件）")
    try:
        edit.set_focus()
    except Exception:
        pass
    try:
        edit.set_edit_text(account)
    except Exception:
        edit.type_keys(_escape_type_keys(account), with_spaces=True)
    time.sleep(0.5)

    # 3) 回车提交并点击搜索结果
    main_window.type_keys("{ENTER}")
    time.sleep(2.0)
    item = None
    try:
        items = main_window.descendants(control_type="ListItem")
    except Exception:
        items = []
    for candidate in items:
        try:
            name = candidate.window_text() or ""
        except Exception:
            name = ""
        if account in name:
            item = candidate
            break
    if item is None and items:
        item = items[0]
    if item is None:
        raise RuntimeError("搜索结果中未找到可点击条目（ListItem）")
    try:
        item.click_input()
        time.sleep(2.0)
    except Exception as exc:
        raise RuntimeError(f"点击搜索结果失败: {exc}") from exc

    # 4) 尽力进入历史文章页（按钮名随版本漂移；失败仅告警，转用户协助）
    history = _find_child(main_window, [
        {"control_type": "Button", "title_re": ".*(文章|历史消息|查看全部).*"},
        {"control_type": "ListItem", "title_re": ".*(文章|历史消息).*"},
        {"control_type": "Text", "title_re": ".*(查看全部文章|历史文章).*"},
    ], timeout=1.5)
    if history is not None:
        try:
            history.click_input()
            time.sleep(1.5)
        except Exception:
            pass
    else:
        emit_event(
            LEVEL_WARN, "l3.ui", step="history_tab", ok=False, account=account,
            note="未自动找到历史文章入口；请在微信中手动进入历史页后逐篇打开文章",
        )
    emit_event(
        LEVEL_INFO, "l3.ui", step="account_history", ok=True, account=account,
        note="已尝试打开公众号页面；请确认历史文章列表可见，随后逐篇打开文章",
    )


def _print_assist_hint(account: str) -> None:
    """--assist 模式：向用户打印人工操作提示（stderr 人类可读 + info 事件）。"""
    target = account if account else "（未指定 --account）"
    print(
        "[L3·用户协助] 目标公众号：%s\n"
        "  请在 PC 微信中逐篇打开目标文章页并停留 1-2 秒；\n"
        "  mitmdump 会自动捕获文章页 HTML 并解析为 25 列记录；\n"
        "  采集窗口结束（或 Ctrl+C）后自动写出 JSONL。" % target,
        file=sys.stderr, flush=True,
    )
    emit_event(
        LEVEL_INFO, "l3.assist", account=account or None,
        hint="请在微信中逐篇打开目标文章页面（每篇停留 1-2 秒）",
    )


# ------------------------------------------------------------------ 采集循环
def _capture_loop(
    capture_dir: str, media_dir: Path, proc, window: int, account: str,
    options: dict | None = None,
) -> tuple[list[dict], dict, str]:
    """轮询 capture 目录（每 2s）：新 html -> 读 HTML -> extract -> 落盘/build/validate。

    去重设计：
      - 文件名去重：比对已处理文件名集合（addon 同文件覆盖写，重复打开不重复处理）；
      - 陈旧文件：启动前已存在的 html 视为陈旧，预置进已处理集合，只处理本次新增；
      - meta 竞态：addon 先写 html 后补 _meta.jsonl，缺 meta 的文件下一轮重试；
      - 记录级去重：同一 record_id（canonical url 派生）只入缓冲一次。

    返回 (records, stats, status)；status: done / interrupted / mitmdump_died。
    """
    records: list[dict] = []
    stats = {"captured": 0, "ok": 0, "partial": 0, "fail": 0}
    seen_ids: set[str] = set()
    processed = {path.name for path in _list_html(capture_dir)}
    deadline = time.monotonic() + window
    next_progress = time.monotonic() + 30.0
    status = "done"
    emit_event(
        LEVEL_INFO, "l3.capture", status="started", window=window,
        capture_dir=str(Path(capture_dir).resolve()), skipped_existing=len(processed),
    )
    try:
        while True:
            if proc.poll() is not None:
                emit_event(
                    LEVEL_ERROR, "l3.capture", step="mitmdump", ok=False, returncode=proc.returncode,
                    hint="mitmdump 子进程已退出，请查看 capture 目录 _mitmdump.log",
                )
                status = "mitmdump_died"
                break
            meta_map = _read_meta(capture_dir)
            for path in _list_html(capture_dir):
                if path.name in processed:
                    continue
                meta = meta_map.get(path.name)
                if not meta or not meta.get("url"):
                    continue  # addon 先写 html 后补 meta，下一轮重试
                processed.add(path.name)
                record = _process_capture(path, meta, account, media_dir, stats, seen_ids, options)
                if record is not None:
                    records.append(record)
            now = time.monotonic()
            if now >= deadline:
                emit_event(LEVEL_INFO, "l3.capture", status="window_elapsed", window=window)
                break
            if now >= next_progress:
                emit_event(
                    LEVEL_INFO, "l3.capture", status="polling",
                    remaining=round(deadline - now, 1), **stats,
                )
                next_progress = now + 30.0
            time.sleep(_POLL_INTERVAL)
    except KeyboardInterrupt:
        status = "interrupted"
        emit_event(LEVEL_WARN, "l3.capture", status="interrupted", **stats)
    return records, stats, status


def _list_html(capture_dir: str) -> list[Path]:
    """capture 目录下的文章页 html（排除 _ 前缀内部文件），按名排序保证确定性。"""
    directory = Path(capture_dir)
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.glob("*.html") if not path.name.startswith("_"))


def _read_meta(capture_dir: str) -> dict[str, dict]:
    """读 _meta.jsonl 建 文件名 -> meta 映射（与 addon 的文件名约定 md5(url)[:16] 一致）。"""
    mapping: dict[str, dict] = {}
    meta_path = Path(capture_dir) / "_meta.jsonl"
    if not meta_path.is_file():
        return mapping
    try:
        with open(meta_path, "r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    entry = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                url = entry.get("url") if isinstance(entry, dict) else None
                if not url:
                    continue
                name = hashlib.md5(str(url).encode("utf-8")).hexdigest()[:16] + ".html"
                mapping[name] = entry
    except OSError:
        return mapping
    return mapping


def _collect_images(
    images: list, media_dir: Path, record_id: str, options: dict,
) -> tuple[list[dict], list[str]]:
    """下载正文图片到 <media>/images/<record_id>/，返回 (清单, 失败原因列表)。

    契约与 L1 `_handle_images` 一致：单图失败不致命（保留 url、不带 local_path），
    失败原因回传给调用方把整篇降级 partial；`--no-images` 只记 URL。
    """
    out: list[dict] = []
    failures: list[str] = []
    download = bool(options.get("download_images", True))
    timeout = int(options.get("timeout", 30) or 30)
    requests = None
    if download:
        try:
            requests = lazy_import("requests", "pip install requests")
        except Exception as exc:  # 依赖缺失 -> 退化为只记 URL，但不静默
            failures.append(f"图片下载不可用（requests 缺失）: {exc}")
            download = False
    image_root = media_dir / "images" / record_id
    last = len(images) - 1
    for index, image in enumerate(images):
        image_url = str((image or {}).get("url") or "").strip()
        if not image_url:
            continue
        if not download:
            out.append({"url": image_url})
            continue
        local_path = image_root / f"{index:04d}.{guess_image_ext(image_url)}"
        try:
            download_file(requests, image_url, local_path, timeout)
        except Exception as exc:  # 单图失败不致命
            failures.append(f"图片下载失败[{index}] {image_url}: {exc}")
            out.append({"url": image_url})
        else:
            out.append({"url": image_url, "local_path": str(local_path)})
        if index < last:
            sleep_polite(options.get("config") or {})
    return out, failures


def _process_capture(
    path: Path, meta: dict, account: str, media_dir: Path, stats: dict, seen_ids: set,
    options: dict | None = None,
) -> dict | None:
    """处理单个捕获文件：extract_article -> 落盘 -> build/validate（同 L1 约定）。"""
    url = str(meta.get("url") or "")
    try:
        html = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        emit_event(LEVEL_WARN, "l3.article_fail", url=url, file=path.name, fail_reason=f"读取失败: {exc}")
        return None
    stats["captured"] += 1

    fields: dict | None = None
    extract_error = ""
    try:
        fields = extract_article(html, url)
    except Exception as exc:
        extract_error = str(exc)
        emit_event(LEVEL_WARN, "l3.capture", step="extract", url=url, file=path.name, error=extract_error)

    # record_id 与 normalize 内派生规则一致：uuid5(NAMESPACE_URL, canonical)
    canonical = canonicalize_url(url) or url
    record_id = str(uuid.uuid5(uuid.NAMESPACE_URL, canonical))

    body_html = (fields.get("body_html") or "").strip() if fields else ""
    if not body_html:
        reason = (f"页面解析失败: {extract_error}" if extract_error
                  else "empty body: 正文缺失或页面未渲染（#js_content 为空）")
        return _fail_record(url, record_id, reason, fields, stats, seen_ids)

    # 1) 正文落盘（body_ref）
    html_path = media_dir / f"{record_id}.html"
    try:
        media_dir.mkdir(parents=True, exist_ok=True)
        html_path.write_text(body_html, encoding="utf-8")
    except OSError as exc:
        return _fail_record(url, record_id, f"正文落盘失败: {exc}", fields, stats, seen_ids)

    # 2) 图片：默认下载原图到 <media>/images/<record_id>/（对齐 L1 与 schema.md §7；
    #    归档场景图片 URL 衰减最快，只记 URL 等于没存）
    images_out, image_failures = _collect_images(
        fields.get("images") or [], media_dir, record_id, options or {},
    )
    media_json = media_dir / f"{record_id}.media.json"
    try:
        media_json.write_text(
            json.dumps({"images": images_out, "videos": []}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        return _fail_record(url, record_id, f"媒体清单落盘失败: {exc}", fields, stats, seen_ids)

    # 3) 组装 + 校验（25 列）
    record = build_article(
        title=fields["title"] or (meta.get("title") or ""),
        url=url,
        collect_layer=COLLECT_LAYER,
        extractor=EXTRACTOR,
        account=account or fields["account"],
        account_id=fields["account_id"],
        author=fields["author"],
        publish_time=fields["publish_time"],
        digest=fields["digest"],
        media_type=fields["media_type"],
        cover_url=fields["cover"] or None,
        video_url=fields["video_url"] or None,
        body_ref=str(html_path),
        media_ref=str(media_json),
        images=images_out,
        videos=[],
        word_count=fields["word_count"],
        record_id=record_id,
    )
    status, reasons = validate_article(record)
    record["status"] = status
    if status == "fail":
        record["fail_reason"] = "; ".join(reasons)
    elif image_failures:
        # 单图失败不致命：保留 url、无 local_path，整篇降级 partial（同 L1）
        record["status"] = "partial"
        record["fail_reason"] = "; ".join([*(reasons or []), *image_failures])
    elif status == "partial":
        record["fail_reason"] = "; ".join(reasons)
    status = record["status"]

    if record["record_id"] in seen_ids:
        return None
    seen_ids.add(record["record_id"])
    stats[status if status in stats else "ok"] += 1
    _emit_record_event(record)
    return record


def _fail_record(
    url: str, record_id: str, reason: str, fields: dict | None = None,
    stats: dict | None = None, seen_ids: set | None = None,
) -> dict | None:
    """构造 fail 记录（保留已提取到的元数据，便于排查；同 L1 约定）。

    记录级去重与 stats["fail"] 计数在此完成；重复 record_id 返回 None。
    """
    fields = fields or {}
    if seen_ids is not None:
        if record_id in seen_ids:
            return None
        seen_ids.add(record_id)
    record = build_article(
        title=fields.get("title") or "",
        url=url,
        collect_layer=COLLECT_LAYER,
        extractor=EXTRACTOR,
        account=fields.get("account") or "",
        account_id=fields.get("account_id") or "",
        author=fields.get("author") or "",
        publish_time=fields.get("publish_time") or "",
        digest=fields.get("digest") or "",
        media_type=fields.get("media_type") or "text",
        cover_url=fields.get("cover") or None,
        video_url=fields.get("video_url") or None,
        record_id=record_id,
    )
    record["status"] = "fail"
    record["fail_reason"] = reason
    if stats is not None:
        stats["fail"] += 1
    _emit_record_event(record)
    return record


def _emit_record_event(record: dict) -> None:
    """单条记录进度事件；fail 逐条 emit warn（契约 §8）。"""
    if record.get("status") == "fail":
        emit_event(
            LEVEL_WARN, "l3.article_fail",
            url=record.get("url", ""),
            record_id=record.get("record_id"),
            fail_reason=record.get("fail_reason", ""),
        )
    else:
        emit_event(
            LEVEL_INFO, "l3.article_done",
            url=record.get("url", ""),
            record_id=record.get("record_id"),
            status=record.get("status"),
            title=record.get("title"),
        )


# ------------------------------------------------------------------ 路径解析
def _resolve_media_dir(args: argparse.Namespace) -> Path:
    """媒体目录：--media-dir > '<out 去扩展名>.media/' > ./wechat-collected-media/（同 L1）。"""
    explicit = (getattr(args, "media_dir", "") or "").strip()
    if explicit:
        return Path(explicit)
    out = (getattr(args, "out", "") or "").strip()
    if out:
        return Path(f"{Path(out).with_suffix('')}.media")
    return Path("./wechat-collected-media")


def _capture_dir_for(out_path: str) -> str:
    """mitm addon 捕获目录：--out 给定则用 '<out 去扩展名>.capture'；否则临时目录（每次运行全新）。"""
    if out_path:
        return f"{Path(out_path).with_suffix('')}.capture"
    return tempfile.mkdtemp(prefix="wechat-capture-")


def _remove_if_empty(directory: str) -> None:
    """清理本次创建的空捕获目录（仅预检失败路径调用，不碰非空目录）。"""
    try:
        path = Path(directory)
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    except OSError:
        pass


def _resolve_port(args: argparse.Namespace, config: dict) -> int:
    """代理端口：--proxy-port > config l3.proxy_port > 8080。"""
    raw = getattr(args, "proxy_port", None)
    if raw:
        return int(raw)
    l3_config = config.get("l3") or {}
    return int(l3_config.get("proxy_port") or 8080)


def _resolve_wechat_path(args: argparse.Namespace, config: dict) -> str:
    """微信路径：--wechat-path > config l3.wechat_path > 探测常见安装路径（可能为空）。"""
    explicit = (getattr(args, "wechat_path", "") or "").strip()
    if not explicit:
        explicit = str((config.get("l3") or {}).get("wechat_path") or "").strip()
    if explicit:
        return explicit
    for pattern in _WECHAT_CANDIDATES:
        candidate = os.path.expandvars(pattern)
        if Path(candidate).is_file():
            return candidate
    return ""


# ------------------------------------------------------------------ 独立入口
def build_parser() -> argparse.ArgumentParser:
    """独立运行时的解析器（collect.py 之外自检 / 单层直跑用）。

    与 L1/L2 一致提供顶层 --config/--yes；mode 前缀可省略（main 自动补全）。
    """
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", default=argparse.SUPPRESS, help="YAML 配置路径（默认内置 DEFAULT_CONFIG）")
    common.add_argument("--yes", action="store_true", default=argparse.SUPPRESS,
                        help="合规闸：确认已获授权（非交互/自动化必填）")
    parser = argparse.ArgumentParser(
        prog="l3_drive_wechat.py",
        description="L3 采集层：PC 微信自动驱动（mitmproxy + pywinauto，用户协助，P2 脆弱层）",
        parents=[common],
    )
    sub = parser.add_subparsers(dest="mode", metavar="<mode>")
    register(sub)
    parser.set_defaults(func=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    tokens = list(sys.argv[1:] if argv is None else argv)
    if tokens and tokens[0] != "desktop" and not tokens[0].startswith(("--config", "--yes")):
        tokens = ["desktop"] + tokens  # 直跑省略 mode 前缀（含 --help）时自动补全
    parser = build_parser()
    args = parser.parse_args(tokens)
    if not getattr(args, "mode", None):
        parser.print_help()
        return EXIT_PARAM
    handler = getattr(args, "func", None)
    if handler is None:
        parser.print_help()
        return EXIT_PARAM
    return int(handler(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
