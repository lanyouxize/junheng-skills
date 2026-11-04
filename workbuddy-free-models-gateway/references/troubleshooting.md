# 故障排查：workbuddy_to_api 接入网关三大常见坑

本文件汇总把 WorkBuddy 免费模型接入本地 LLM 网关时，导致「服务不通」的三类根因与修复命令。
定位顺序建议：先看 `/health` 是否 200，再区分是桥接层（3000）还是网关层（8000）问题。

---

## 坑一：启动即 `FileNotFoundError: WorkBuddy.exe`

**现象**
```
FileNotFoundError: [Errno 2] No such file or directory: 'C:\\Users\\<user>\\AppData\\Local\\Programs\\WorkBuddy\\WorkBuddy.exe'
```

**根因**
WorkBuddy 实际装在 **D 盘**，但系统的 `LOCALAPPDATA` 仍指向 `C:\Users\<user>\AppData\Local`。
`workbuddy_to_api` 默认去 `LOCALAPPDATA\Programs\WorkBuddy\` 找 exe，路径不存在。

**修复**
在 `workbuddy_to_api.py` 同目录的 `.env` 中显式写死真实路径（`<your-user>` 换成你的用户名）：

```ini
WORKBUDDY_EXE=D:\Users\<your-user>\AppData\Local\Programs\WorkBuddy\WorkBuddy.exe
WORKBUDDY_CLI_SCRIPT=D:\Users\<your-user>\AppData\Local\Programs\WorkBuddy\resources\app.asar.unpacked\cli\bin\codebuddy
```

技能自包含副本 `assets//start_bridge.bat` 已能自动探测 D 盘安装位置；
仅当自动探测失败时，才需要在 `.env` 按本机实际安装盘显式填写上述路径。

**验证**
```
curl http://127.0.0.1:3000/health
```
返回 `{"status":"ok",...}` 即修复。

---

## 坑二：`/health`、`/v1/models` 返回 502（10061 连接被拒）

**现象**
```
urllib.error.URLError: <urlopen error [WinError 10061] 由于目标计算机积极拒绝...
```
或直接 `502 Bad Gateway`。

**根因**
本机存在 `HTTP_PROXY=http://127.0.0.1:44413`（或类似）且 `NO_PROXY` 为空。
所有打 `127.0.0.1:3000` / `127.0.0.1:8000` 的本地调用被**发往该代理**，代理无对应服务 → 连接拒绝。

**修复**
启动任何相关进程前，必须设置 `NO_PROXY` 含本地回环：

Windows cmd / bat：
```bat
set NO_PROXY=127.0.0.1,localhost
set no_proxy=127.0.0.1,localhost
```

PowerShell：
```powershell
$env:NO_PROXY="127.0.0.1,localhost"; $env:no_proxy="127.0.0.1,localhost"
```

bash：
```bash
export NO_PROXY=127.0.0.1,localhost
export no_proxy=127.0.0.1,localhost
```

技能所有启动脚本（`start_bridge.bat`）开头已固化该设置。

**注意**：`workbuddy_to_api.py` 在 Python 内已用 `ProxyHandler({})` 绕过代理拉 `/v1/models`，
但用户侧 curl / 网关转发仍需在进程环境变量层设置 `NO_PROXY`，否则仍走代理。

---

## 坑三：用 `wb-kimi-k3-1` 直连 3000 报 `400 not configured`

**现象**
```
{"error":"Model 'wb-kimi-k3-1' is not configured"}
```

**根因**
`workbuddy_to_api` 只认 `kimi-k3-1` 等**原始模型 id**，不认 `wb-` 前缀。网关用 `model_map`
做 wb-* → 真实名翻译后转发没问题，但**直连 3000** 或别名未生效时就会 400。

**修复（双保险）**
1. 网关通道 `model_map` 翻译：`wb-kimi-k3-1 -> kimi-k3-1`（由 `add_workbuddy_to_api_channel.py` 自动生成）。
2. 桥接层别名固化：在 `workbuddy_to_api.py` 的 `DEFAULT_ALIASES` 写死
   `{"wb-kimi-k3-1": "kimi-k3-1", ...}`，或 `.env` 的 `WORKBUDDY_MODEL_ALIASES`
   （JSON）声明，使直连 3000 也好使。

技能自包含副本 `assets//workbuddy_to_api.py` 已含 `DEFAULT_ALIASES` 补丁。

---

## 坑四：启动脚本（.bat）乱码，「不是内部或外部命令」

**现象**
窗口满屏 `锟斤拷` / `铸块很派肺绣镗虫构济聪才毁咄任锡？D 不是内部或外部命令`，
`workbuddy_to_api` / `run.py` 均无法识别。

**根因**
Windows 中文系统默认用 **GBK（代码页 936）** 解析 `.bat`。文件若保存为 UTF-8 且含中文注释/echo，
中文字节被当成命令名执行。

**修复**
启动脚本必须写成**纯 ASCII**（含 `REM` 注释与 `echo` 文本）。路径用 `%~dp0` 自动定位，
避免硬编码中文目录名。技能内 `assets//start_bridge.bat`
均已为纯 ASCII，并通过 `where python` 与常见目录扫描自动定位 Python / WorkBuddy.exe，不再写死本机路径。

---

## 坑五：出字极慢 / 超时（1 分 40 秒+ 仍在生成）

**根因**
当前 WorkBuddy 版本的 `--serve` 把生成**委派给桌面端 IPC**（端口 2020）。当 agent 会话（即
当前对话）或任何桌面端对话占用桌面端时，`--serve` 子进程排队等桌面端响应 → 极慢/超时。

**判断**
`/health` 与 `/v1/models` 均 200、子进程能成功 spawn（日志见 `*protocol.out.log` 监听端口），
但 chat 调用慢。说明配置正确，慢只因桌面端被占用。

**应对**
结束 agent 会话、桌面端空闲后，wb-* 模型出字即正常。这是架构限制，非配置问题。
可先用 `scripts/wait_health.py` 确认两端口就绪，再在桌面端空闲时实测对话。
