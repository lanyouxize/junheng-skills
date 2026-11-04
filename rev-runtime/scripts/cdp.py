#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CDP（Chrome DevTools Protocol）最小客户端 —— 纯标准库实现。

为什么手写而不装 websocket-client：
  1. rev-runtime 要在裸机上可用。本机实测 python 无 websocket/websockets 模块，
     装第三方包就多一个供应链面，而这里只需要 RFC6455 的一个子集。
  2. 依赖越少，"证据可复现"越容易成立 —— reproduce.cmd 里不用写 pip install。

只实现客户端必需部分：
  - HTTP GET /json/version、/json/list（纯 socket，不引 urllib 的 keep-alive 行为）
  - WebSocket 握手（RFC6455 §4.1）
  - 发送：仅 text 帧，必 mask（§5.3）
  - 接收：text/binary 分片重组、ping 自动回 pong、close 正常退出
  - 不支持：压缩扩展、TLS（wss）、服务端角色
"""

import base64
import json
import os
import socket
import struct
import time
import urllib.request


class CDPError(RuntimeError):
    pass


# ------------------------------------------------------------------ HTTP

def http_json(endpoint, path, timeout=5.0):
    """读 CDP 的 HTTP 端点。endpoint 形如 http://127.0.0.1:9222。

    必须显式绕过代理：CDP 端点永远在本机回环口，而 urllib 默认会读系统代理设置，
    在开了 HTTP_PROXY 的机器上会得到 502 Bad Gateway（本机实测）。
    curl 不走代理，所以"curl 通、python 不通"是典型症状。
    """
    url = endpoint.rstrip("/") + path
    req = urllib.request.Request(url, headers={"Host": _host_header(endpoint)})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _host_header(endpoint):
    body = endpoint.split("://", 1)[-1].rstrip("/")
    return body


def parse_ws_url(ws_url):
    """ws://127.0.0.1:9222/devtools/page/XXX -> (host, port, path)"""
    if not ws_url.startswith("ws://"):
        raise CDPError(f"只支持 ws://（不支持 wss，需 TLS 不在本模块范围）: {ws_url!r}")
    body = ws_url[5:]
    slash = body.find("/")
    if slash < 0:
        hostport, path = body, "/"
    else:
        hostport, path = body[:slash], body[slash:]
    if ":" in hostport:
        host, port = hostport.rsplit(":", 1)
        port = int(port)
    else:
        host, port = hostport, 80
    return host, port, path


# ------------------------------------------------------------------ WebSocket

class WebSocket:
    """RFC6455 客户端子集。所有 recv 都带超时，绝不无限阻塞。"""

    def __init__(self, ws_url, timeout=10.0):
        self.host, self.port, self.path = parse_ws_url(ws_url)
        self.timeout = timeout
        self.sock = socket.create_connection((self.host, self.port), timeout=timeout)
        self.sock.settimeout(timeout)
        self._buf = b""
        self._closed = False
        self._handshake()

    def _handshake(self):
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        req = (
            f"GET {self.path} HTTP/1.1\r\n"
            f"Host: {self.host}:{self.port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        self.sock.sendall(req.encode("ascii"))
        # 读到 \r\n\r\n 为止；多余的字节可能已含首帧，要留在缓冲里
        while b"\r\n\r\n" not in self._buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise CDPError("WebSocket 握手期间连接被关闭")
            self._buf += chunk
        head, self._buf = self._buf.split(b"\r\n\r\n", 1)
        lines = head.decode("latin-1").split("\r\n")
        status = lines[0]
        if "101" not in status:
            raise CDPError(f"WebSocket 握手失败: {status}")

    # -- 发送
    def send_text(self, text):
        payload = text.encode("utf-8")
        self._send_frame(0x1, payload)

    def _send_frame(self, opcode, payload):
        if self._closed:
            raise CDPError("连接已关闭")
        header = bytearray([0x80 | opcode])
        n = len(payload)
        mask_bit = 0x80
        if n < 126:
            header.append(mask_bit | n)
        elif n < (1 << 16):
            header.append(mask_bit | 126)
            header += struct.pack("!H", n)
        else:
            header.append(mask_bit | 127)
            header += struct.pack("!Q", n)
        mask = os.urandom(4)
        header += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes(header) + masked)

    # -- 接收
    def _recv_exact(self, n):
        while len(self._buf) < n:
            chunk = self.sock.recv(max(4096, n - len(self._buf)))
            if not chunk:
                raise CDPError("连接被对端关闭")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def recv_message(self, timeout=None):
        """返回一条完整应用层消息（str）。超时返回 None。"""
        if timeout is not None:
            self.sock.settimeout(timeout)
        try:
            fin, opcode, payload = self._read_frame()
        except socket.timeout:
            return None
        finally:
            self.sock.settimeout(self.timeout)

        # 控制帧先处理
        if opcode == 0x9:  # ping
            self._send_frame(0xA, payload)
            return self.recv_message(timeout)
        if opcode == 0xA:  # pong
            return self.recv_message(timeout)
        if opcode == 0x8:  # close
            self._closed = True
            try:
                self._send_frame(0x8, b"")
            except Exception:
                pass
            return None

        chunks = [payload]
        while not fin:
            fin, op2, p2 = self._read_frame()
            if op2 == 0x9:
                self._send_frame(0xA, p2)
                continue
            chunks.append(p2)
        return b"".join(chunks).decode("utf-8", "replace")

    def _read_frame(self):
        b0, b1 = self._recv_exact(2)
        fin = bool(b0 & 0x80)
        opcode = b0 & 0x0F
        masked = bool(b1 & 0x80)
        length = b1 & 0x7F
        if length == 126:
            (length,) = struct.unpack("!H", self._recv_exact(2))
        elif length == 127:
            (length,) = struct.unpack("!Q", self._recv_exact(8))
        mask = self._recv_exact(4) if masked else None
        payload = self._recv_exact(length) if length else b""
        if mask:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        return fin, opcode, payload

    def close(self):
        if not self._closed:
            try:
                self._send_frame(0x8, b"")
            except Exception:
                pass
            self._closed = True
        try:
            self.sock.close()
        except Exception:
            pass


# ------------------------------------------------------------------ CDP 会话

class Session:
    """一条 CDP 连接 + 单调递增的 id。

    CDP 是"请求带 id、响应用 id 对回、事件无 id"的多路复用协议，
    所以必须自己维护 id → 响应 的配对，不能假设"下一条就是我的响应"。
    """

    def __init__(self, ws_url, timeout=10.0):
        self.ws = WebSocket(ws_url, timeout=timeout)
        self._id = 0
        self.pending_events = []

    def call(self, method, params=None, timeout=10.0):
        self._id += 1
        mid = self._id
        self.ws.send_text(json.dumps({"id": mid, "method": method, "params": params or {}}))
        deadline = time.time() + timeout
        while True:
            remain = max(0.05, deadline - time.time())
            if time.time() >= deadline:
                raise CDPError(f"{method} 超时（{timeout}s）")
            msg = self.ws.recv_message(timeout=remain)
            if msg is None:
                continue
            obj = json.loads(msg)
            if obj.get("id") == mid:
                if "error" in obj:
                    raise CDPError(f"{method} 失败: {obj['error']}")
                return obj.get("result", {})
            if "method" in obj:
                self.pending_events.append(obj)

    def enable(self, domains):
        for d in domains:
            try:
                self.call(f"{d}.enable")
            except CDPError:
                pass  # 某些域在部分 target 上不可用，不阻断其他域

    def drain(self, seconds):
        """收集 seconds 秒内的事件。故意用时间窗而非事件计数：
        事件计数会在静默 target 上永久阻塞。"""
        events = list(self.pending_events)
        self.pending_events = []
        deadline = time.time() + seconds
        while time.time() < deadline:
            remain = deadline - time.time()
            msg = self.ws.recv_message(timeout=min(remain, 0.5))
            if msg is None:
                continue
            obj = json.loads(msg)
            if "method" in obj:
                events.append(obj)
        return events

    def close(self):
        self.ws.close()


def list_targets(endpoint):
    """HTTP /json/list。type=page 的是页面，type=other 可能是 worker/服务。"""
    try:
        items = http_json(endpoint, "/json/list")
    except Exception:
        items = http_json(endpoint, "/json")
    out = []
    for t in items:
        out.append({
            "id": t.get("id"),
            "type": t.get("type"),
            "title": (t.get("title") or "")[:120],
            "url": (t.get("url") or "")[:300],
            "ws": t.get("webSocketDebuggerUrl"),
        })
    return out


def version(endpoint):
    return http_json(endpoint, "/json/version")
