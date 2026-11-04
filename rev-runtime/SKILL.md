---
name: rev-runtime
description: 运行动态观测。目标必须跑起来才能看到行为时用它：CDP 读写页面与 console、枚举进程模块、生成 Frida hook 规格、生成 mitmproxy 抓包 addon。只产候选事实，不写正式证据库。
description_zh: 动态观测：纯标准库 CDP 客户端 + Windows 进程/模块枚举 + Frida 与 mitmproxy 薄封装
description_en: "Dynamic observation with a stdlib-only CDP client, Windows process enumeration, and thin Frida/mitmproxy wrappers"
version: 1.0.0
display_name: rev-runtime
---

# rev-runtime

动态观测层。**只产候选事实**，正式证据由 `rev-core evidence add` 收编。

## 不做什么

- **不写 `evidence.jsonl`**。产出 `facts/<channel>.json`，交给 core 才成为证据。
- **不做越界绕过**。证书固定、反调试、反注入、加固脱壳、DRM 校验一律不管；遇到就记 `unknown{blocking:true}`，这是本技能与"破解工具链"的分界线。
- **不伪造定位**。动态事实没有文件偏移，一律写 `locator.mode=runtime`；绝不拿一个看似合理的近偏移顶替。
- **不假装跑过**。Frida / mitmproxy 未安装时报 `unavailable` + 原因 + `exit 3`，同时把已生成的规格文件留下供有环境时使用。
- **不用推测值补实参**。Frida 取不到的参数记 `got:false`，由采集侧转成 `unknown`。

## 通道

| 通道 | 命令 | 依赖 | 本机可用 |
|---|---|---|---|
| CDP | `cdp targets/eval/listen` | 仅 Python 标准库 + 一个带 `--remote-debugging-port` 的目标 | 是（Edge 实测） |
| 进程 | `proc list/modules` | 仅 Python 标准库（ctypes / Win32） | 是 |
| Frida | `frida plan/run` | frida-tools | 否（生成规格可用） |
| 代理 | `proxy plan/run` | mitmproxy | 否（生成 addon 可用） |

`probe` 一次看清四种通道在本机的真实状态。

## 关键约束：事实必须绑定到具体二进制

动态证据的 `locator` 要求：
- `file_sha256` = **宿主可执行体的全量哈希**（不是空串，不是截断哈希）
- `runtime.host / pid / module / rva / session`

拿不到宿主进程的可执行体哈希时，**本技能不产出任何事实并 `exit 3`**。理由：换一个 build 行为就可能不同，"我在某个 msedge 上看到过"不是证据。可用 `--pid` 显式指定宿主进程。

## 用法

```bash
# 0. 先看环境
python scripts/cli.py probe

# 1. 目标需带远程调试端口启动
#    msedge.exe --remote-debugging-port=9222 --user-data-dir=<隔离目录>
python scripts/cli.py cdp targets --endpoint http://127.0.0.1:9222 --out ./case
python scripts/cli.py cdp eval --ws "ws://127.0.0.1:9222/devtools/page/<id>" \
       --expr "navigator.userAgent" --out ./case
python scripts/cli.py cdp listen --ws "ws://..." --domains Runtime,Network \
       --seconds 5 --trigger "location.reload()" --out ./case

# 2. 进程与模块（找 Electron 应用的主进程、看加载了哪些 dll）
python scripts/cli.py proc list --match game --out ./case/proc.json
python scripts/cli.py proc modules --pid 4120 --out ./case/mods.json

# 3. 生成规格（工具未装也能做）
python scripts/cli.py frida plan --out ./case/hook --module kernel32.dll \
       --export CreateFileW --argtype wstr uint uint ptr
python scripts/cli.py proxy plan --out ./case/proxy
```

## 事实转证据

`facts/cdp-eval.json` 里每条 fact 的 `locator` 与 `digest` 可直接放进 evidence：

```json
{"kind":"evidence","id":"ev-cdp-001","grade":"E2","channel":"dynamic",
 "locator": <fact.locator>, "digest": <fact.digest>, ...}
```

然后 `rev-core evidence add --file ev.json`。**注意**：`rev-core init --target` 要求本地文件，CDP 场景请传宿主可执行体路径（如 `msedge.exe`），这样 `target.sample_sha256` 与事实里的 `file_sha256` 天然一致。

## 退出码

`0` 成功｜`1` 参数/内部错误｜`3` 通道不可用（工具缺失或宿主二进制无法绑定）

## 已知缺陷与设计取舍

- CDP 只支持 `ws://`，`wss://` 显式拒绝（TLS 不在实现范围）。
- `endpoint` 与 `ws` 指向同一实例是硬要求，实现上以 `ws` 为唯一信息源，避免两处参数不一致（这个缺陷真实发生过）。
- 本机 shell 带 `HTTP_PROXY` 时，urllib 默认走代理会让本地 CDP 端点返回 502；实现强制 `ProxyHandler({})`。
- CDP 的 `pid` 来自 `SystemInfo.getProcessInfo`（Browser 域），是承载调试端口的浏览器主进程，不是渲染进程。
