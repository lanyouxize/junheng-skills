# l3-setup.md — L3 PC 微信采集环境搭建（mitmproxy + pywinauto）

> L3 = 本机 PC 微信驱动层：pywinauto 只负责 UI 触发，文章页数据经 mitmproxy local 模式抽取。
> 设计级可行、运行级待真机复测（硬 gate，见 §7）；不为稳定性背书。生成日期：2026-10-22。

## 1. 环境要求

| 项 | 要求 | 说明 |
|---|---|---|
| 操作系统 | Windows（win32） | pywinauto Windows-only |
| 权限 | **管理员** | mitmproxy local 模式进程重定向 + CA 写入根存储均需提权 |
| PC 微信 | 已安装并**已登录**（单开） | 仅本机 PC 微信；不支持手机微信/多开 |
| Python | 3.13.12（WorkBuddy 托管） | mitmproxy 12.2.1 / pywinauto 0.6.9 支持 3.13 |
| 依赖 | mitmproxy 12.2.1、pywinauto 0.6.9、pywin32、comtypes | pywinauto 的 UIA 后端依赖 |
| 合规 | 每次运行过合规闸（`--yes` 或交互确认） | AC-10，仅自有/已授权号 |

## 2. mitmdump local 模式启动

```bash
# 管理员 PowerShell；confdir 默认 ~/.mitmproxy（首次运行自动生成 CA）
# 与 l3_drive_wechat.py 实际构造一致（--set listen_port= / --set confdir= 双 --set 形式）
mitmdump --mode local:WeChatAppEx.exe ^
         -s scripts/addons/wechat_article_addon.py ^
         --set listen_port=8080 ^
         --set confdir=%USERPROFILE%\.mitmproxy
```

| 参数 | 说明 |
|---|---|
| `--mode local:WeChatAppEx.exe` | local 重定向模式：由 mitmproxy 拉起微信主进程并重定向其出站流量；**不依赖系统代理设置**。进程名以任务管理器实际为准（如版本差异带路径，用完整路径更稳） |
| `-s .../wechat_article_addon.py` | 附加脚本：过滤 `mp.weixin.qq.com/s?` 文章页响应，落 `<out>.media/<record_id>.html` 并产出 JSONL（消费 extract.py） |
| `--listen-port 8080` | 代理端口；与 common.py `l3.proxy_port` 默认值一致，可用配置覆盖 |
| `--set confdir=...` | CA 与配置目录；确定路径便于预检与审计 |

l3_drive_wechat.py 负责编排：预检（§3/§4）→ 拉起 mitmdump 子进程 → pywinauto 触发 → 收 JSONL → 清理子进程。addon 过滤规则与落盘结构以 addons/wechat_article_addon.py 为准（该模块实现中，契约待其落盘后对齐复核）。

### 2.1 两种工作模式（`--mitm-mode`）

| 模式 | 原理 | 依赖 | 何时用 |
|---|---|---|---|
| `local`（首选） | WinDivert 透明劫持 `WeChatAppEx.exe` 出站流量 | 内核驱动可加载 + 管理员；**不监听端口、不改系统代理** | 驱动能装的机器 |
| `regular` | 普通 HTTP 代理 + 临时把 Windows 系统代理指向 mitmproxy | 仅需端口可用；退出自动还原代理 | 驱动装不上（签名过期 / HVCI / 驱动黑名单）时 |
| `auto`（默认） | 先 local，启动探活失败则自动降级 regular 并接管系统代理 | 同上两者 | 不确定本机能否装驱动时 |

```bash
# 推荐：让编排器自己选（本机 WinDivert 不可用时会自动转 regular）
python scripts/collect.py desktop --account "样本号" --mitm-mode auto --out out/v3.jsonl
# 显式走 regular + 系统代理
python scripts/collect.py desktop --account "样本号" --mitm-mode regular --system-proxy --out out/v3.jsonl
```

> **为什么不能只判"mitmdump 进程活着"**：local 模式下 WinDivert 装不上时，mitmdump 主进程会继续存活，只有内部 redirector 子进程退出，日志打 `Task failed: ...`。此时进程判据为真、功能为假（真机实测：5 分钟窗口 0 捕获）。故启动探活必须同时读日志特征（判据见 `_redirector_failed`）。


## 3. CA 安装步骤

```bash
# 1) 首次运行 mitmdump 生成 CA（confdir 下出现 mitmproxy-ca-cert.cer 等四个文件）
mitmdump --set confdir=%USERPROFILE%\.mitmproxy   # 看到监听日志后 Ctrl+C 即可

# 2) 管理员安装到受信任根（关键：微信内置 Chromium 走系统 Schannel 信任根存储，
#    装 Root 存储即生效，无需像 Firefox 那样管理独立证书库）
certutil -addstore Root "%USERPROFILE%\.mitmproxy\mitmproxy-ca-cert.cer"
```

- 必须管理员：写 HKLM 根存储。
- 预检：`certutil -store Root | findstr mitmproxy` 有输出才放行；无输出退出码 6（EXIT_ENV），不盲目运行（AC-08）。
- 卸载：`certutil -delstore Root mitmproxy`（序列号见 `certutil -store Root` 输出）。

## 4. 防火墙放行

若 Defender/防火墙拦截代理进程或端口，用**精确规则**放行；禁止全域放行（Any 程序/Any 端口）：

```powershell
New-NetFirewallRule -DisplayName "WAC-mitmproxy-8080" `
    -Direction Inbound -Protocol TCP -LocalPort 8080 `
    -Action Allow -Program "C:\Python313\Scripts\mitmdump.exe"
```

| 要素 | 取值 | 理由 |
|---|---|---|
| Program | mitmdump.exe 绝对路径 | 限定到代理进程，避免放开其他程序 |
| LocalPort | 8080（与配置一致） | 只放代理端口 |
| Protocol/Direction | TCP / Inbound | local 模式重定向所需最小面 |

预检：`Get-NetFirewallRule -DisplayName "WAC-mitmproxy-8080"` 存在即过；策略不允许建规则时退出码 6 并提示人工放行。

## 5. pywinauto 连接微信主窗口

```python
from pywinauto import Application
app = Application(backend="uia").connect(path="WeChatAppEx.exe")  # 或用 connect(title_re=...)
win = app.window(class_name="WeChatMainWnd")  # 类名/标题随版本变化，需正则容错
```

| 注意事项 | 说明 |
|---|---|
| backend="uia" | 锁定 UIA 后端（Spec 架构表）；不要混用 win32 |
| 控件定位 | 用 Name/AutomationId + 正则容错，**不用绝对坐标**；定位失败即报错退出（退出码 6）转人工 |
| UI 漂移风险 | 微信版本更新会改控件树/标题；本设计把 UI 面缩到最小（只触发"打开历史页/文章页"），数据全部走 MITM，漂移只影响触发不影响数据正确性 |
| 会话状态 | 微信未启动/未登录 → 提示用户先登录；多开时 connect 可能命中错误进程，要求单开 |
| 权限一致 | pywinauto 与微信同权限级运行（都管理员或都普通），否则 UIA 连接被拒 |
| 卡死处置 | 触发后设超时轮询，超时未出现目标页面即停，不无限等待 |

## 6. 证书锁定背景（置信度说明）

| 事实 | 影响 |
|---|---|
| 2026 年微信在**协议层启用证书锁定（pinning）** | 协议级 MITM/签名伪造路径失效 → 明确不做（Spec §3 Out-of-Scope，永不） |
| **文章页 HTTPS 渲染**走内置 Chromium + 系统 Schannel 信任根 | 装证到 Root 后文章页响应仍可解密抽取，MITM 有效 |
| 综合置信度 ~70%（OPEN-DECISIONS Phase 1.5，原 50% 上调） | 设计级可行；**运行级真机复测 = 进入实施的硬 gate**，失败则 L3 降级为"用户协助手动导出"，不影响 L1/L2/exe |

## 7. 真机复测清单（V4 gate，Spec §12）

按序执行，任一步失败即停并记录，不带病推进：

| # | 步骤 | 通过标准 |
|---|---|---|
| 1 | CA 预检 | `certutil -store Root` 含 mitmproxy CA（否则退出码 6） |
| 2 | 防火墙/进程名预检 | 规则存在；`WeChatAppEx.exe` 进程名核实 |
| 3 | 文章页捕获 | mitmdump（local 或 regular）+ addon 抓到样本文章页响应，HTML 含 `#js_content` |
| 4 | JSONL 产出 | `collect.py desktop --account "样本号" --assist --out /tmp/v4.jsonl`，断言 status=ok 且 25 字段齐全 |
| 5 | exe 兜底启动 | `collect.py exe --exe "..." --target "样本号"` CLI 探测 → 不支持则进程+输出目录扫描，产出同 schema JSONL |
| 6 | 回归 | 同一 URL 经 L1/L3 各跑一次，record_id 一致（幂等） |

用户协助点：步骤 3–4 需用户在真实微信中点开目标文章页（本机无 GUI 微信，开发机不可自验）。

## 8. 故障对照表

| 现象 | 可能原因 | 处置 |
|---|---|---|
| 预检退出码 6，提示 CA 缺失 | CA 未生成/未装 Root | 重跑 §3；确认 confdir 路径一致 |
| `l3.mitmdump step=redirector`：`Task failed: failed to propagate interception config update` / `redirect daemon exited prematurely` | **WinDivert 内核驱动装不上**：驱动签名证书过期、或 HVCI（内存完整性）+ 驱动黑名单拦截（2026-10-22 真机实测：mitmproxy 12.2.1 自带 WinDivert 2.2.2，签名者证书 2023-05-26 已过期，本机 `HVCI Enabled=1` + `VulnerableDriverBlocklistEnable=1` ⇒ `WinDivertOpen` 返回 `ERROR_ACCESS_DENIED(5)`，`System32\drivers\WinDivert64.sys` 从未落盘、注册表无 `WinDivert` 服务键） | 改用 `--mitm-mode regular`（或 `auto` 让其自动降级）+ `--system-proxy`；**不要**为跑通去关 HVCI |
| mitmdump 启动即退 | 非管理员；端口被占；confdir 无写权限 | 管理员运行；换 `--listen-port`；修 confdir ACL |
| `_mitmdump.log` 恒为 0 字节 | 日志块缓冲 + Windows `TerminateProcess` 强杀 ⇒ 缓冲区整体丢弃 | 启动器已设 `PYTHONUNBUFFERED=1`（勿删）；手工复现时同样要设 |
| 微信流量未被代理（local 模式） | 进程名/路径不符；防火墙拦截；驱动装不上（见上） | 核实实际进程名改用完整路径；补 §4 精确规则；或转 regular |
| 微信流量未被代理（regular 模式） | 系统代理未生效：微信 4.x **确实读 Windows 系统代理**（2026-10-22 实测：`ProxyEnable=1 + 127.0.0.1:<port>` 后文章页可被抓到），故排查顺序为 ① `ProxyOverride` 是否包含 `mp.weixin.qq.com` ② 微信是否重启后仍用旧代理 ③ 是否有其他代理软件（如 7890 端口的 Clash）抢回设置 | 核对 HKCU `Internet Settings`；`--system-proxy` 会自动先备份再改、退出还原 |

| addon 未捕获文章页 | 用户未触发；URL 过滤过严；pinning 生效 | 人工点开文章；核对 filter；若 pinning 命中转 §6 降级路径 |
| pywinauto 连不上窗口 | 微信未启动/未登录；多开；权限不一致 | 先登录并单开；与微信同权限运行 |
| 抓到 HTML 但 extract 字段空 | 页面未渲染完成；改版 | 等 networkidle 后取；对照 references/wechat-endpoints.md §3 修订选择器 |
| 视频 URL 很快失效 | mpvideo token 时效性 | 只落 metadata+cover（media_type=video-meta），不强抓原文件 |
| JSONL 大面积 status=fail | 页面结构变化/缺必填 | 读 fail_reason 定位；停跑修订，不静默 |
