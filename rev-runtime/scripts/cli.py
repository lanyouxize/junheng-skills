#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rev-runtime —— 动态观测层：CDP / 进程模块 / Frida / 代理录制。

设计前提（本机实测 2026-11-01）：
  无 frida、无 mitmdump、无 adb、python 无 websocket 模块；有 Edge。
  => CDP 与进程枚举必须零依赖可跑；Frida / mitmproxy 只生成规格与封装，
     工具缺失时 status=unavailable 且 exit 3，绝不假装跑过。

与 rev-core 的契约：
  产出 revfact/1 事实（不是证据）。事实的 locator 用 mode=runtime，
  含 host/pid/module/rva/session —— 动态事实没有文件偏移，伪造 offset 不可复现。
  只有 rev-core 能把事实升格为 evidence。
"""

import argparse
import ctypes
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cdp  # noqa: E402

CST = timezone(timedelta(hours=8))
EXIT_OK, EXIT_INVALID, EXIT_UNAVAILABLE = 0, 1, 3


def now_iso():
    return datetime.now(CST).replace(microsecond=0).isoformat()


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def write_json(path, obj):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, sort_keys=False)
        f.write("\n")


def new_session():
    """采集会话 id：同一会话内的动态事实才能互相参照。"""
    return "rt-%s-%s" % (datetime.now(CST).strftime("%Y%m%d-%H%M%S"), os.urandom(3).hex())


# ---------------------------------------------------------------- 事实封装

def rt_fact(channel, idx, kind, value, fsha, runtime, channel_extra=None):
    """一条动态事实。

    digest 对 value 的 UTF-8 字节实算 —— 这样任何持有 value 的人都能重算校验，
    不需要重放那次采集（重放本来就不可保证：同一次执行未必能再出现）。
    """
    raw = value.encode("utf-8") if isinstance(value, str) else json.dumps(value, ensure_ascii=False).encode("utf-8")
    f = {
        "id": "%s-%04d" % (channel, idx),
        "kind": kind,
        "value": value,
        "locator": {
            "mode": "runtime",
            "file_sha256": fsha,
            "length": max(1, len(raw)),
            "runtime": runtime,
        },
        "digest": {"algo": "sha256", "value": sha256_bytes(raw)},
        "confidence_hint": "E2",
        "channel_type": "dynamic",
    }
    if channel_extra:
        f.update(channel_extra)
    return f


def runtime_locator(host, pid, module, rva, session, captured_at=None):
    return {
        "host": host,
        "pid": int(pid),
        "module": module,
        "rva": int(rva),
        "session": session,
        "captured_at": captured_at or now_iso(),
    }


def make_result(channel, target, status, facts, stats, reason=None, tool=None, runtime=None):
    return {
        "schema": "revfact/1",
        "producer": "rev-runtime",
        "channel": channel,
        "target_id": target.get("target_id") if isinstance(target, dict) else None,
        "target": target,
        "runtime": runtime,
        "tool": tool or {"name": "rev-runtime/" + channel, "version": "1.0.0"},
        "generated_at": now_iso(),
        "status": status,
        "unavailable_reason": reason,
        "facts": facts,
        "stats": stats,
    }


def emit(out_dir, channel, result):
    p = os.path.join(out_dir, "facts", "%s.json" % channel)
    write_json(p, result)
    print("%-12s status=%-12s facts=%d" % (channel, result["status"], len(result["facts"])))
    if result["unavailable_reason"]:
        print("  原因: " + result["unavailable_reason"])
    print("  written: " + p)
    return EXIT_OK if result["status"] in ("ok", "partial") else EXIT_UNAVAILABLE


# ---------------------------------------------------------------- probe

BROWSER_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


def probe_all():
    rows = {}

    def tool(name, path, reason_ok=None):
        p = shutil.which(path)
        rows[name] = {"available": bool(p), "path": p,
                      "reason": None if p else "%s 不在 PATH（%s）" % (path, reason_ok or "需另行安装")}

    tool("frida", "frida", "pip install frida-tools")
    tool("mitmdump", "mitmdump", "pip install mitmproxy")
    tool("adb", "adb", "Android Platform Tools")

    # CDP：不靠"装了浏览器"判断，靠"有没有活着在监听"判断
    live = []
    for port in (9222, 9223, 9333):
        try:
            v = cdp.version("http://127.0.0.1:%d" % port)
            live.append({"port": port, "browser": v.get("Browser")})
        except Exception:
            pass
    rows["cdp"] = {"available": bool(live), "endpoints": live,
                   "reason": None if live else "无 CDP 端点监听（需以 --remote-debugging-port 启动浏览器/Electron）"}

    br = [p for p in BROWSER_CANDIDATES if os.path.exists(p)]
    rows["browser_binary"] = {"available": bool(br), "paths": br,
                              "reason": None if br else "未发现 Edge/Chrome 安装"}
    return rows


def cmd_probe(args):
    rows = probe_all()
    print("%-16s %-10s %s" % ("通道", "可用", "说明"))
    for k, v in rows.items():
        print("%-16s %-10s %s" % (k, "是" if v["available"] else "否", v["reason"] or ""))
    if args.json:
        write_json(args.json, {"schema": "revrt-probe/1", "generated_at": now_iso(), "rows": rows})
        print("\nwritten: " + args.json)
    return EXIT_OK


# ---------------------------------------------------------------- proc（ctypes，零依赖）

TH32CS_SNAPPROCESS = 0x00000002
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010
MAX_PATH = 260


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", ctypes.c_ulong), ("cntUsage", ctypes.c_ulong),
                ("th32ProcessID", ctypes.c_ulong), ("th32DefaultHeapID", ctypes.c_void_p),
                ("th32ModuleID", ctypes.c_ulong), ("cntThreads", ctypes.c_ulong),
                ("th32ParentProcessID", ctypes.c_ulong), ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", ctypes.c_ulong), ("szExeFile", ctypes.c_wchar * MAX_PATH)]


class MODULEENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", ctypes.c_ulong), ("th32ModuleID", ctypes.c_ulong),
                ("th32ProcessID", ctypes.c_ulong), ("GlblcntUsage", ctypes.c_ulong),
                ("ProccntUsage", ctypes.c_ulong), ("modBaseAddr", ctypes.c_void_p),
                ("modBaseSize", ctypes.c_ulong), ("hModule", ctypes.c_void_p),
                ("szModule", ctypes.c_wchar * 256), ("szExePath", ctypes.c_wchar * MAX_PATH)]


def open_kernel32():
    if os.name != "nt":
        raise OSError("proc 通道仅实现 Windows（本机为 %s）" % os.name)
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    return k


def snapshot_processes(k):
    snap = k.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap in (None, ctypes.c_void_p(-1).value):
        raise OSError("CreateToolhelp32Snapshot 失败: %s" % ctypes.get_last_error())
    out = []
    try:
        e = PROCESSENTRY32W()
        e.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = k.Process32FirstW(ctypes.c_void_p(snap), ctypes.byref(e))
        while ok:
            out.append({"pid": e.th32ProcessID, "ppid": e.th32ParentProcessID,
                        "threads": e.cntThreads, "name": e.szExeFile})
            ok = k.Process32NextW(ctypes.c_void_p(snap), ctypes.byref(e))
    finally:
        k.CloseHandle(ctypes.c_void_p(snap))
    return out


def snapshot_modules(k, pid):
    snap = k.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
    if snap in (None, ctypes.c_void_p(-1).value):
        raise OSError("无法快照 pid=%d 的模块（权限不足或进程已退出）" % pid)
    out = []
    try:
        e = MODULEENTRY32W()
        e.dwSize = ctypes.sizeof(MODULEENTRY32W)
        ok = k.Module32FirstW(ctypes.c_void_p(snap), ctypes.byref(e))
        while ok:
            out.append({"name": e.szModule, "base": int(e.modBaseAddr or 0),
                        "size": e.modBaseSize, "path": e.szExePath})
            ok = k.Module32NextW(ctypes.c_void_p(snap), ctypes.byref(e))
    finally:
        k.CloseHandle(ctypes.c_void_p(snap))
    return out


def cmd_proc(args):
    try:
        k = open_kernel32()
    except OSError as e:
        print("proc 不可用: %s" % e)
        return EXIT_UNAVAILABLE
    if args.action == "list":
        rows = snapshot_processes(k)
        if args.match:
            rows = [r for r in rows if args.match.lower() in r["name"].lower()]
        rows.sort(key=lambda r: r["pid"])
        if args.out:
            write_json(args.out, {"schema": "revrt-proc/1", "generated_at": now_iso(),
                                  "count": len(rows), "processes": rows})
            print("written: %s  (count=%d)" % (args.out, len(rows)))
        else:
            for r in rows[:args.limit]:
                print("%6d %6d %4d  %s" % (r["pid"], r["ppid"], r["threads"], r["name"]))
        return EXIT_OK
    # modules
    if not args.pid:
        print("modules 需要 --pid")
        return EXIT_INVALID
    mods = snapshot_modules(k, args.pid)
    print("pid=%d 模块数=%d" % (args.pid, len(mods)))
    if args.out:
        write_json(args.out, {"schema": "revrt-modules/1", "generated_at": now_iso(),
                              "pid": args.pid, "count": len(mods), "modules": mods})
        print("written: " + args.out)
    else:
        for m in mods[:args.limit]:
            print("  %016X  %8d  %s" % (m["base"], m["size"], m["name"]))
    return EXIT_OK


# ---------------------------------------------------------------- cdp 通道

def cmd_cdp(args):
    # 端点与 ws 指向同一实例是硬要求。让 ws 成为唯一信息源：
    # --endpoint 显式给了就校验一致性，没给就从 ws 推出来。
    ep = args.endpoint
    if args.ws:
        derived = endpoint_from_ws(args.ws)
        if ep and _norm_host(ep) != _norm_host(derived):
            print("警告: --endpoint(%s) 与 --ws(%s) 不同源，以 --ws 为准" % (ep, derived))
            ep = derived
        elif not ep:
            ep = derived
    if not ep:
        ep = "http://127.0.0.1:9222"
    session = new_session()
    if args.action == "targets":
        try:
            v = cdp.version(ep)
            ts = cdp.list_targets(ep)
        except Exception as e:
            print("CDP 端点不可达: %s" % e)
            return EXIT_UNAVAILABLE
        print("browser: %s" % v.get("Browser"))
        for t in ts:
            print("  %-16s %-40s %s" % (t["type"], (t["title"] or "")[:40], t["url"][:60]))
        hb = host_binding(ep, args.pid)
        if not hb:
            reason = ("无法绑定宿主进程的二进制哈希（pid=%s）。动态证据必须锚定具体二进制版本，"
                      "缺失即不可复现，故不产出事实。请用 --pid 指定宿主进程。" %
                      (args.pid if args.pid else "自动解析失败"))
            print("不可用: " + reason)
            res = make_result("cdp", {"target_id": None, "endpoint": ep}, "unavailable", [], {},
                              reason=reason,
                              tool={"name": "rev-runtime/cdp", "version": cdp_version()},
                              runtime={"host": "windows", "session": session})
            if args.out:
                emit(args.out, "cdp", res)
            return EXIT_UNAVAILABLE
        facts, idx = [], 1
        for t in ts:
            facts.append(rt_fact("cdp", idx, "cdp-target", "%s|%s" % (t["type"], t["url"]),
                                 hb["exe_sha256"],
                                 runtime_locator("windows", hb["pid"], hb["name"], 0, session),
                                 {"session": session, "target_ws": t.get("ws")}))
            idx += 1
        res = make_result("cdp", {"target_id": None, "endpoint": ep}, "ok", facts,
                          {"targets": len(ts), "browser": v.get("Browser"),
                           "session": session, "pid": hb["pid"]},
                          tool={"name": "rev-runtime/cdp", "version": cdp_version()},
                          runtime={"host": "windows", "pid": hb["pid"], "exe": hb["name"],
                                   "exe_path": hb["exe"], "exe_sha256": hb["exe_sha256"],
                                   "session": session})
        if args.out:
            emit(args.out, "cdp", res)
        return EXIT_OK

    if not args.ws:
        print("需要 --ws（从 cdp targets 的 ws 字段取）")
        return EXIT_INVALID
    try:
        s = cdp.Session(args.ws, timeout=args.timeout)
    except Exception as e:
        print("连接 target 失败: %s" % e)
        return EXIT_UNAVAILABLE

    hb = host_binding(ep, args.pid)
    if not hb:
        s.close()
        reason = ("无法绑定宿主进程的二进制哈希（pid=%s）。动态证据必须锚定具体二进制版本，"
                  "缺失即不可复现，故不产出事实。请用 --pid 指定宿主进程。"
                  % (args.pid if args.pid else "自动解析失败"))
        print("不可用: " + reason)
        if args.out:
            emit(args.out, "cdp-" + args.action,
                 make_result("cdp", {"target_id": None, "ws": args.ws}, "unavailable", [], {},
                             reason=reason, tool={"name": "rev-runtime/cdp", "version": cdp_version()},
                             runtime={"host": "windows", "session": session}))
        return EXIT_UNAVAILABLE
    pid, modname, fsha = hb["pid"], hb["name"], hb["exe_sha256"]
    facts, idx = [], 1

    def add(kind, value, extra=None):
        nonlocal idx
        facts.append(rt_fact("cdp", idx, kind, value, fsha,
                             runtime_locator("windows", pid, modname, 0, session), extra))
        idx += 1

    try:
        if args.action == "eval":
            r = s.call("Runtime.evaluate", {"expression": args.expr, "returnByValue": True,
                                            "awaitPromise": bool(args.await_promise)},
                       timeout=args.timeout)
            res = r.get("result", {})
            val = res.get("value")
            if val is None and "description" in res:
                val = res["description"]
            print("type=%s value=%r" % (res.get("type"), val))
            add("cdp-eval-result", val if isinstance(val, str) else json.dumps(val, ensure_ascii=False),
                extra={"expression": args.expr})
        elif args.action == "listen":
            domains = [d.strip() for d in args.domains.split(",") if d.strip()]
            s.enable(domains)
            print("监听 %s 共 %ss ..." % (",".join(domains), args.seconds))
            if args.trigger:
                s.call("Runtime.evaluate", {"expression": args.trigger, "returnByValue": True})
            evs = s.drain(args.seconds)
            for e in evs:
                m = e.get("method", "")
                p = e.get("params", {})
                if m == "Runtime.consoleAPICalled":
                    txt = " ".join(str(a.get("value", a.get("description", ""))) for a in p.get("args", []))
                    add("console", txt, extra={"level": p.get("type")})
                elif m == "Log.entryAdded":
                    add("log-entry", p.get("entry", {}).get("text", ""),
                        extra={"level": p.get("entry", {}).get("level")})
                elif m == "Network.requestWillBeSent":
                    req = p.get("request", {})
                    add("net-request", "%s %s" % (req.get("method"), req.get("url")),
                        extra={"request_id": p.get("requestId"), "post_data": req.get("postData")})
                elif m == "Network.responseReceived":
                    rsp = p.get("response", {})
                    add("net-response", "%s %s" % (rsp.get("status"), rsp.get("url")),
                        extra={"request_id": p.get("requestId"), "mime": rsp.get("mimeType")})
                elif m in ("Runtime.exceptionThrown",):
                    add("exception", json.dumps(p.get("exceptionDetails", {}), ensure_ascii=False)[:500])
            print("事件 %d 条 -> 事实 %d 条" % (len(evs), len(facts)))
        else:
            print("未知 action: %s" % args.action)
            return EXIT_INVALID
    finally:
        s.close()

    res = make_result("cdp", {"target_id": None, "ws": args.ws, "action": args.action},
                      "ok", facts, {"facts": len(facts), "session": session, "pid": pid},
                      tool={"name": "rev-runtime/cdp", "version": cdp_version()},
                      runtime={"host": "windows", "pid": pid, "exe": modname,
                               "exe_path": hb["exe"], "exe_sha256": fsha, "session": session})
    if args.out:
        return emit(args.out, "cdp-" + args.action, res)
    return EXIT_OK


def cdp_version():
    return "1.0.0"


def endpoint_from_ws(ws):
    """从 ws URL 反推 HTTP 端点。CDP 的 HTTP 与 WS 同 host:port。"""
    host, port, _ = cdp.parse_ws_url(ws)
    return "http://%s:%d" % (host, port)


def _norm_host(ep):
    return ep.replace("https://", "http://").rstrip("/").lower()


def process_name_of(pid):
    """按 pid 取可执行体名。取不到返回 None（不猜）。"""
    if os.name != "nt":
        return None
    try:
        k = open_kernel32()
        for p in snapshot_processes(k):
            if p["pid"] == pid:
                return p["name"]
    except Exception:
        pass
    return None


def exe_path_of(pid):
    """按 pid 取可执行体完整路径（Windows API，零依赖）。

    为什么需要：动态证据必须锚定到具体二进制版本，否则"在某个 msedge 上观测到"
    这句话等于没说 —— 换一个 build 行为就可能不同。
    """
    if os.name != "nt":
        return None
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    try:
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.OpenProcess.restype = ctypes.c_void_p
        h = k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not h:
            return None
        try:
            size = ctypes.c_ulong(1024)
            buf = ctypes.create_unicode_buffer(1024)
            ok = k.QueryFullProcessImageNameW(ctypes.c_void_p(h), 0, buf, ctypes.byref(size))
            return buf.value if ok else None
        finally:
            k.CloseHandle(ctypes.c_void_p(h))
    except Exception:
        return None


def sha256_file(path, limit=None):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        left = limit
        while True:
            n = 1 << 20 if left is None else min(1 << 20, left)
            if n <= 0:
                break
            b = f.read(n)
            if not b:
                break
            h.update(b)
            if left is not None:
                left -= len(b)
    return h.hexdigest()


def host_binding(endpoint, pid_override=None):
    """确定"这次观测属于哪个二进制"：pid + exe 路径 + 全量 sha256。

    返回 None 表示绑定失败 —— 此时调用方必须不产出事实并发 exit 3。
    理由：动态证据若不能锚定具体二进制版本，换一个 build 就可能复现不出，
    那它就不是证据，只是"当时看到过"。
    """
    if pid_override:
        exe = exe_path_of(pid_override)
        sha = None
        if exe and os.path.exists(exe):
            try:
                sha = sha256_file(exe)
            except Exception:
                sha = None
        if not sha:
            return None
        return {"pid": int(pid_override), "name": process_name_of(pid_override) or os.path.basename(exe),
                "exe": exe, "exe_sha256": sha}
    info = resolve_cdp_process(endpoint)
    if not info or not info.get("exe_sha256"):
        return None
    return info


def resolve_cdp_process(endpoint):
    """确定这场 CDP 采集属于哪个进程。

    为什么必须做：动态事实的 locator 要写 pid，而 pid=0 不满足 rev-core 的
    "正整数"约束 —— 也就是说编不出 pid 的事实根本升格不成证据。
    办法是用 CDP 自己的 SystemInfo.getProcessInfo（Browser 域），
    取 type=browser 的那条，它是承载 --remote-debugging-port 的进程，
    也是"重新附着时要核对的那个进程"。
    """
    try:
        v = cdp.version(endpoint)
        bws = v.get("webSocketDebuggerUrl")
        if not bws:
            return None
        s = cdp.Session(bws, timeout=5)
        try:
            r = s.call("SystemInfo.getProcessInfo", timeout=5)
        finally:
            s.close()
        br = [x for x in r.get("processInfo", []) if x.get("type") == "browser"]
        if not br:
            return None
        pid = int(br[0]["id"])
        exe = exe_path_of(pid)
        exe_sha = None
        if exe and os.path.exists(exe):
            try:
                exe_sha = sha256_file(exe)  # 必须全量：截断哈希不是这个文件的哈希
            except Exception:
                exe_sha = None
        return {"pid": pid, "name": process_name_of(pid) or (os.path.basename(exe) if exe else "browser"),
                "exe": exe, "exe_sha256": exe_sha,
                "renderer_count": sum(1 for x in r.get("processInfo", []) if x.get("type") == "renderer"),
                "browser": v.get("Browser")}
    except Exception as e:  # noqa: BLE001
        # 不静默：pid 取不到会直接导致事实不可用，原因必须可见
        setattr(resolve_cdp_process, "last_error", repr(e))
        if os.environ.get("REV_RUNTIME_DEBUG"):
            print("[debug] resolve_cdp_process 失败: %r" % (e,), file=sys.stderr)
        return None


# ---------------------------------------------------------------- frida（薄封装）

FRIDA_RUNNER = r'''// rev-runtime Frida 薄封装 —— 由 `rev-runtime frida plan` 生成，请勿手改
// 设计要点：
//   1. 只做 Interceptor.attach + 参数解码，不做脱壳/反调试绕过（越界，见 SKILL.md 边界）
//   2. 每条事件一行 JSON 到 stdout，字段固定：ts/event/module/func/args_raw/args_decoded
//   3. 取不到的实参记 got:false，绝不用推测值顶替
'use strict';
var SPEC = __SPEC__;
var session = SPEC.session;

function decodeArg(spec, raw) {
  try {
    if (spec.type === 'wstr') return raw.readUtf16String();
    if (spec.type === 'cstr') return raw.readUtf8String();
    if (spec.type === 'int') return raw.toInt32();
    if (spec.type === 'uint') return raw.toUInt32();
    if (spec.type === 'ptr') return raw.toString();
    if (spec.type === 'bytes') return raw.readByteArray(spec.len || 16);
  } catch (e) {
    return { __decode_error: String(e) };
  }
  return String(raw);
}

function emit(obj) { send(JSON.stringify(obj)); }

SPEC.hooks.forEach(function (h) {
  var mod = Process.findModuleByName(h.module);
  if (!mod) { emit({ event: 'miss', module: h.module, func: h.export, session: session }); return; }
  var addr = mod.findExportByName(h.export);
  if (!addr) { emit({ event: 'miss', module: h.module, func: h.export, session: session }); return; }
  emit({ event: 'attach', module: h.module, func: h.export, addr: addr.toString(), session: session });
  Interceptor.attach(addr, {
    onEnter: function (args) {
      var rec = { ts: Date.now(), event: 'call', module: h.module, func: h.export,
                  session: session, args_raw: [], args_decoded: [], got: [] };
      (h.args || []).forEach(function (a) {
        var raw = args[a.index];
        rec.args_raw.push(raw.toString());
        if (raw.isNull()) { rec.args_decoded.push(null); rec.got.push(false); return; }
        rec.args_decoded.push(decodeArg(a, raw));
        rec.got.push(true);
      });
      emit(rec);
    }
  });
});
emit({ event: 'ready', hooks: SPEC.hooks.length, session: session });
'''


def cmd_frida(args):
    if args.action == "plan":
        spec = {
            "schema": "reva-frida-hookspec/1",
            "generated_at": now_iso(),
            "session": new_session(),
            "target": {"process": args.process, "pid": args.pid, "module_hint": args.module},
            "hooks": [
                {"module": args.module, "export": args.export,
                 "args": [{"index": i, "type": t} for i, t in enumerate(args.argtype)]},
            ],
            "notes": [
                "args.type 支持 wstr/cstr/int/uint/ptr/bytes；bytes 需在测点手工补 len",
                "取不到的实参 got=false，采集侧必须转成 unknown，不得补推测值",
            ],
        }
        out = args.out or "."
        write_json(os.path.join(out, "hook-spec.json"), spec)
        with open(os.path.join(out, "runner.js"), "w", encoding="utf-8", newline="\n") as f:
            f.write(FRIDA_RUNNER.replace("__SPEC__", json.dumps(spec, ensure_ascii=False, indent=2)))
        print("hook-spec.json + runner.js 已生成 -> %s" % os.path.abspath(out))
        print("  目标: %s | %s!%s" % (args.process or ("pid=" + str(args.pid)), args.module, args.export))
        print("  参数: %s" % (args.argtype or ["（未声明，仅记录指针）"]))
        print("  下一步（需已装 frida-tools）:")
        print("    frida -f %s -l %s --no-pause -q"
              % (args.process or "<pid>", os.path.join(out, "runner.js")))
        return EXIT_OK

    exe = shutil.which("frida")
    if not exe:
        print("frida 不可用：frida-tools 未安装（pip install frida-tools）")
        print("  已生成规格可用；本通道 status=unavailable，退出码 3")
        return EXIT_UNAVAILABLE
    script = os.path.join(args.spec, "runner.js")
    if not os.path.exists(script):
        print("规格目录缺 runner.js: %s" % args.spec)
        return EXIT_INVALID
    cmd = [exe]
    if args.pid:
        cmd += ["-p", str(args.pid)]
    elif args.process:
        cmd += ["-f", args.process]
    else:
        print("需要 --pid 或 --process")
        return EXIT_INVALID
    cmd += ["-l", script, "--no-pause", "-q"]
    print("运行: " + " ".join(cmd))
    return subprocess.call(cmd)


# ---------------------------------------------------------------- proxy（薄封装）

PROXY_ADDON = r'''# rev-runtime mitmproxy addon —— 由 `rev-runtime proxy plan` 生成
# 设计要点：
#   1. 响应体写原始字节到 blobs/，并记录它在文件中的相对偏移 —— 证据 locator 要指向具体字节
#   2. 任何写盘动作都不修改内容，只旁路记录
#   3. 遇到证书固定（pinning）失败的连接记 unknown，不做绕过（越界）
import hashlib
import json
import os
import time

OUT = __OUT__
BLOBS = os.path.join(OUT, "blobs")
SESSION = __SESSION__


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def _dump(kind, flow, body, offset):
    rec = {
        "ts": round(time.time(), 3),
        "session": SESSION,
        "kind": kind,
        "method": flow.request.method,
        "url": flow.request.pretty_url,
        "status": getattr(flow.response, "status_code", None),
        "req_headers": dict(flow.request.headers),
        "resp_headers": dict(flow.response.headers) if flow.response else {},
        "body_len": len(body) if body is not None else 0,
        "body_sha256": _sha(body) if body is not None else None,
        "blob_offset": offset,
        "blob_file": "blobs/capture.bin",
    }
    if body:
        os.makedirs(BLOBS, exist_ok=True)
        p = os.path.join(BLOBS, "capture.bin")
        with open(p, "ab") as f:
            f.write(body)
    with open(os.path.join(OUT, "proxy.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


class Recorder:
    def __init__(self):
        self.offset = 0
        os.makedirs(OUT, exist_ok=True)

    def response(self, flow):
        body = flow.response.raw_content if flow.response else None
        _dump("response", flow, body, self.offset)
        if body:
            self.offset += len(body)


addons = [Recorder()]
'''


def cmd_proxy(args):
    if args.action == "plan":
        out = os.path.abspath(args.out or ".")
        os.makedirs(out, exist_ok=True)
        text = PROXY_ADDON.replace("__OUT__", json.dumps(out)).replace("__SESSION__", json.dumps(new_session()))
        p = os.path.join(out, "proxy_addon.py")
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        print("proxy_addon.py 已生成 -> %s" % p)
        print("  启动: mitmdump -q -s %s --listen-port 8080" % p)
        print("  产出: proxy.jsonl（每请求一行）+ blobs/capture.bin（原始字节，offset 指这里）")
        return EXIT_OK
    exe = shutil.which("mitmdump")
    if not exe:
        print("mitmdump 不可用：mitmproxy 未安装（pip install mitmproxy）")
        print("  已生成 addon 可用；本通道 status=unavailable，退出码 3")
        return EXIT_UNAVAILABLE
    script = os.path.join(args.spec, "proxy_addon.py")
    if not os.path.exists(script):
        print("规格目录缺 proxy_addon.py: %s" % args.spec)
        return EXIT_INVALID
    cmd = [exe, "-q", "-s", script, "--listen-port", str(args.port)]
    print("运行: " + " ".join(cmd))
    return subprocess.call(cmd)


# ---------------------------------------------------------------- 自检

class MiniWSServer(threading.Thread):
    """内嵌最小 WebSocket 服务端，只用于验证客户端协议实现。

    存在理由：CDP 客户端若只对着真浏览器"跑通了"就算通过，
    那么它到底是"实现了 RFC6455"还是"恰好被浏览器容忍了"就无法区分。
    这个服务端只实现规范里必需的动作，客户端必须真的对才能通过。
    """

    GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

    def __init__(self, scenario="default"):
        super().__init__(daemon=True)
        self.scenario = scenario
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.got = {"pong": False, "client_payloads": []}
        self.error = None

    def run(self):
        try:
            conn, _ = self.sock.accept()
            conn.settimeout(10)
            self._handshake(conn)
            if self.scenario == "echo":
                payload = self._read_client_frame(conn)
                self.got["client_payloads"].append(payload)
                self._send(conn, 0x1, b"ECHO:" + payload)
                # 分片：fin=0 的首片 + fin=1 的续片
                self._send(conn, 0x1, b"FRAG-A", fin=False)
                self._send(conn, 0x0, b"FRAG-B", fin=True)
                # ping：客户端必须回 pong
                self._send(conn, 0x9, b"PINGP")
                # 70000 字节：走 16 位长度分支的上界之外，验证 64 位解析
                self._send(conn, 0x1, b"Z" * 70000)
                conn.settimeout(3)
                try:
                    while True:
                        op, pl = self._read_frame(conn)
                        if op == 0xA:
                            self.got["pong"] = True
                            break
                except socket.timeout:
                    pass
            conn.close()
        except Exception as e:  # noqa: BLE001
            self.error = e

    def _handshake(self, conn):
        buf = b""
        while b"\r\n\r\n" not in buf:
            c = conn.recv(4096)
            if not c:
                raise RuntimeError("客户端提前断开")
            buf += c
        key = ""
        for line in buf.decode("latin-1").split("\r\n"):
            if line.lower().startswith("sec-websocket-key:"):
                key = line.split(":", 1)[1].strip()
        accept = __import__("base64").b64encode(
            hashlib.sha1((key + self.GUID).encode()).digest()).decode()
        conn.sendall(("HTTP/1.1 101 Switching Protocols\r\n"
                      "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                      "Sec-WebSocket-Accept: %s\r\n\r\n" % accept).encode())

    def _recv_exact(self, conn, n):
        buf = b""
        while len(buf) < n:
            c = conn.recv(n - len(buf))
            if not c:
                raise RuntimeError("断开")
            buf += c
        return buf

    def _read_frame(self, conn):
        b0, b1 = self._recv_exact(conn, 2)
        op = b0 & 0x0F
        masked = bool(b1 & 0x80)
        n = b1 & 0x7F
        if n == 126:
            (n,) = __import__("struct").unpack("!H", self._recv_exact(conn, 2))
        elif n == 127:
            (n,) = __import__("struct").unpack("!Q", self._recv_exact(conn, 8))
        mask = self._recv_exact(conn, 4) if masked else None
        pl = self._recv_exact(conn, n) if n else b""
        if mask:
            pl = bytes(b ^ mask[i % 4] for i, b in enumerate(pl))
        return op, pl

    def _read_client_frame(self, conn):
        return self._read_frame(conn)[1]

    def _send(self, conn, opcode, payload, fin=True):
        head = bytearray([(0x80 if fin else 0x00) | opcode])
        n = len(payload)
        if n < 126:
            head.append(n)
        elif n < (1 << 16):
            head.append(126)
            head += __import__("struct").pack("!H", n)
        else:
            head.append(127)
            head += __import__("struct").pack("!Q", n)
        conn.sendall(bytes(head) + payload)

    def stop(self):
        try:
            self.sock.close()
        except Exception:
            pass


def cmd_selftest(args):
    checks = []

    def check(cond, name, detail=""):
        checks.append((bool(cond), name, detail))

    # 1. WebSocket 协议层：握手、mask 发送、回显
    srv = MiniWSServer("echo")
    srv.start()
    ws = cdp.WebSocket("ws://127.0.0.1:%d/devtools/x" % srv.port, timeout=8)
    ws.send_text("hello")
    m1 = ws.recv_message(timeout=5)
    check(m1 == "ECHO:hello", "回显正确（验证客户端帧 mask 编码）", repr(m1)[:60])
    check(srv.got["client_payloads"] and srv.got["client_payloads"][0] == b"hello",
          "服务端解出我方原文（证明 mask 与长度编码符合规范）")

    # 2. 分片重组
    m2 = ws.recv_message(timeout=5)
    check(m2 == "FRAG-AFRAG-B", "分片消息重组正确", repr(m2)[:60])

    # 3. ping → pong（客户端必须自动应答）
    m3 = ws.recv_message(timeout=5)  # 内部会先处理 ping
    check(m3 is not None and m3.startswith("ZZZ"), "跳过 ping 后仍能取到下一条消息", repr(m3)[:20] if m3 else None)
    check(len(m3 or "") == 70000, "70000 字节消息完整（64 位长度分支）", str(len(m3 or "")))
    srv.join(timeout=3)
    check(srv.got["pong"], "收到 ping 后自动回 pong")
    ws.close()
    srv.stop()

    # 4. 代理绕过：设一个坏代理，本地端点仍必须可达
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"Browser": "MiniTest/1.0"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    httpd = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]
    old = {k: os.environ.get(k) for k in ("HTTP_PROXY", "http_proxy", "NO_PROXY", "no_proxy")}
    os.environ["HTTP_PROXY"] = os.environ["http_proxy"] = "http://127.0.0.1:1"
    os.environ.pop("NO_PROXY", None)
    os.environ.pop("no_proxy", None)
    try:
        v = cdp.version("http://127.0.0.1:%d" % port)
        check(v.get("Browser") == "MiniTest/1.0", "坏代理环境下本地 CDP 端点仍可达（ProxyHandler 生效）", str(v))
    except Exception as e:  # noqa: BLE001
        check(False, "坏代理环境下本地 CDP 端点仍可达（ProxyHandler 生效）", str(e)[:120])
    finally:
        for k, val in old.items():
            if val is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = val
        httpd.shutdown()

    # 5. ws_url 解析
    h, p, path = cdp.parse_ws_url("ws://127.0.0.1:9333/devtools/page/AB12")
    check((h, p, path) == ("127.0.0.1", 9333, "/devtools/page/AB12"), "ws URL 解析正确", "%s %s %s" % (h, p, path))
    try:
        cdp.parse_ws_url("wss://x/y")
        check(False, "wss 必须显式拒绝（TLS 不在本模块范围）")
    except cdp.CDPError:
        check(True, "wss 必须显式拒绝（TLS 不在本模块范围）")

    # 6. 进程枚举（对本进程）
    if os.name == "nt":
        k = open_kernel32()
        procs = snapshot_processes(k)
        check(len(procs) > 5, "进程快照非空", "count=%d" % len(procs))
        me = [x for x in procs if x["pid"] == os.getpid()]
        check(bool(me), "能枚举到自身进程", str(me[:1]))
        mods = snapshot_modules(k, os.getpid())
        check(len(mods) >= 1, "能枚举自身进程模块", "count=%d" % len(mods))
        check(any(m["name"].lower() in ("python.exe", "python3.exe", "pythonw.exe") or
                  m["name"].lower().endswith(".exe") for m in mods),
              "模块名非空且含可执行体")
    else:
        check(True, "非 Windows 跳过进程枚举")

    # 7. 事实 digest 可回读
    f = rt_fact("t", 1, "k", "观测值-ABC", "b" * 64,
                runtime_locator("windows", 100, "a.exe", 16, "rt-x"))
    recalc = sha256_bytes("观测值-ABC".encode("utf-8"))
    check(f["digest"]["value"] == recalc, "事实 digest 可按 value 重算（可回读验证）")
    check(f["locator"]["mode"] == "runtime" and f["locator"]["runtime"]["pid"] == 100,
          "事实使用 runtime 定位符（不伪造文件偏移）")

    ok = sum(1 for c, _, _ in checks if c)
    for c, name, detail in checks:
        if not c:
            print("FAIL " + name + ("   -> " + str(detail) if detail else ""))
    print("自检 %d/%d 通过" % (ok, len(checks)))
    if ok != len(checks):
        print("SELFTEST FAILED")
        return EXIT_INVALID
    print("SELFTEST PASSED")
    return EXIT_OK


# ---------------------------------------------------------------- 入口

def main(argv=None):
    ap = argparse.ArgumentParser(prog="rev-runtime", description="动态观测：CDP / 进程 / Frida / 代理")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("probe", help="探测所有动态通道可用性")
    p.add_argument("--json")
    p.set_defaults(fn=cmd_probe)

    p = sub.add_parser("proc", help="进程与模块枚举（Windows，零依赖）")
    p.add_argument("action", choices=["list", "modules"])
    p.add_argument("--pid", type=int)
    p.add_argument("--match")
    p.add_argument("--limit", type=int, default=40)
    p.add_argument("--out")
    p.set_defaults(fn=cmd_proc)

    p = sub.add_parser("cdp", help="Chrome DevTools Protocol 观测")
    p.add_argument("action", choices=["targets", "eval", "listen"])
    p.add_argument("--endpoint", default=None,
                   help="CDP HTTP 端点；默认从 --ws 推导，二者都没有时用 127.0.0.1:9222")
    p.add_argument("--ws")
    p.add_argument("--expr")
    p.add_argument("--trigger", help="listen 前先执行的表达式（用来主动触发事件）")
    p.add_argument("--domains", default="Runtime,Log,Network")
    p.add_argument("--seconds", type=float, default=5.0)
    p.add_argument("--timeout", type=float, default=10.0)
    p.add_argument("--await-promise", action="store_true")
    p.add_argument("--pid", type=int, help="显式指定宿主进程 pid（自动解析失败时用）")
    p.add_argument("--out")
    p.set_defaults(fn=cmd_cdp)

    p = sub.add_parser("frida", help="Frida hook 规格与运行（需 frida-tools）")
    p.add_argument("action", choices=["plan", "run"])
    p.add_argument("--out", default=".")
    p.add_argument("--spec")
    p.add_argument("--process")
    p.add_argument("--pid", type=int)
    p.add_argument("--module", default="kernel32.dll")
    p.add_argument("--export", default="CreateFileW")
    p.add_argument("--argtype", nargs="*", default=[], help="按参数顺序：wstr cstr int uint ptr")
    p.set_defaults(fn=cmd_frida)

    p = sub.add_parser("proxy", help="mitmproxy addon 规格与运行（需 mitmproxy）")
    p.add_argument("action", choices=["plan", "run"])
    p.add_argument("--out", default=".")
    p.add_argument("--spec")
    p.add_argument("--port", type=int, default=8080)
    p.set_defaults(fn=cmd_proxy)

    p = sub.add_parser("selftest", help="协议层自检（内嵌 WS 服务端，不依赖浏览器）")
    p.set_defaults(fn=cmd_selftest)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
