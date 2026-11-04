# 动态通道能力与前置条件

| 通道 | 命令 | 前置 | 本机(2026-11-01) | 退出码 |
|---|---|---|---|---|
| `probe` | `probe` | 无 | 可用 | 0 |
| `proc` | `proc list/modules` | Windows + Python | 可用 | 0 / 3 |
| `cdp` | `cdp targets/eval/listen` | 目标带 `--remote-debugging-port` | 可用（Edge 156 实测） | 0 / 3 |
| `frida` | `frida plan` | 无 | 规格可用 | 0 |
| `frida` | `frida run` | frida-tools | 不可用 | 3 |
| `proxy` | `proxy plan` | 无 | addon 可用 | 0 |
| `proxy` | `proxy run` | mitmproxy | 不可用 | 3 |

## 为什么 CDP 手写而不用 websocket-client

本机实测 python 无 `websocket` / `websockets` 模块。装第三方包会：
1. 给"证据可复现"加前提（reproduce.cmd 要写 pip install）
2. 多一个供应链面（见 05-合规与安全门禁.md 的 G1/G2）

CDP 只需要 RFC6455 的一个子集：客户端握手、mask 发送、分片重组、ping/pong。约 200 行标准库可覆盖。

## 协议实现的可验证点

`selftest` 用内嵌 WS 服务端验证 5 项，且这 5 项都经过变异测试（删掉实现即变红）：

| 判据 | 被破坏时会怎样 |
|---|---|
| 帧 mask 编码正确 | 页面收到乱码，回显不符 |
| 分片重组 | 只拿到首片 |
| ping 自动回 pong | 服务端 30s 后断开 |
| 64 位长度分支 | >64KB 消息错位 |
| 代理绕过 | 有 HTTP_PROXY 时本地端点 502 |

## 宿主二进制绑定

`cdp` 与 `proc` 都依赖 Win32 API：
- `SystemInfo.getProcessInfo`（CDP 域）→ 浏览器主进程 pid
- `OpenProcess` + `QueryFullProcessImageNameW` → 可执行体路径
- 全量 sha256 → 写进 fact 的 `locator.file_sha256`

三步任一失败，本通道 `exit 3` 且不产事实。

## 加装 Frida / mitmproxy 后要补的动作

1. `pip install frida-tools` → `probe` 应显示 frida 可用
2. `frida plan` 生成 hook-spec + runner.js → `frida run --spec <dir> --pid <n>`
3. 首次跑通后，把实际命令写入该批事实的 `reproduce.cmd`，否则它只是探测记录
4. 事件 jsonl 里的 `got:false` 必须转成 `unknown`，不得补值
