---
name: workbuddy-free-models-gateway
display_name: WorkBuddy 免费模型接入本地网关
display_name_en: WorkBuddy Free Models to Local Gateway
description: 把 WorkBuddy 免费模型额度（GLM、Kimi、DeepSeek、MiniMax、混元）接入本地网关，暴露为 3000 端口的 OpenAI 兼容 API 并完成接线。当用户要把免费额度接到本地或第三方客户端、需要兼容端点时使用。
description_zh: 把 WorkBuddy 免费模型额度（GLM-5.3、Kimi K3、DeepSeek V4、MiniMax M3、Hunyuan 等）通过 workbuddy_to_api 暴露为本地 OpenAI 兼容 API（3000 端口），再作为 openai 通道接入本地 LLM 网关（8000）。覆盖三大常见故障修复：WorkBuddy 装在非默认盘（如 D 盘）、本机 HTTP_PROXY 拦截 127.0.0.1、wb-* 别名 400 报错；并区分永久/限时免费、一键启动 3000+8000。触发词：把 WorkBuddy 免费模型接入网关、workbuddy_to_api 配置、免费大模型接入 OpenAI 兼容 API、wb-* 模型 400/502。
description_en: Expose WorkBuddy free model credits (GLM-5.3, Kimi K3, DeepSeek V4, MiniMax M3, Hunyuan) as a local OpenAI-compatible API on port 3000 via workbuddy_to_api, then wire it into a local LLM gateway (8000) as an openai channel. Fixes three common failures (non-default install drive, HTTP_PROXY intercepting 127.0.0.1, wb-* alias 400), labels permanent vs time-limited free models, and one-click launches 3000+8000.
category: 开发者工具
version: 1.0.0
author: 12168
---

# WorkBuddy 免费模型 → 本地 LLM 网关

## 概述

`workbuddy_to_api` 是一个开源单文件项目（upstream: https://github.com/yxxawa/workbuddy_to_api），
把 WorkBuddy 桌面客户端的免费 credits 包装成一个 **OpenAI 兼容 API**，本地端点默认
`http://127.0.0.1:3000/v1`，暴露 50+ 模型（GLM-5.3、Kimi K3、DeepSeek V4、MiniMax M3 等）。

本 skill 把该端点作为本地 LLM 网关的一个 `openai` 类型通道接入，使下游工具只认网关（8000），
由网关统一编排 / 限流 / 缓存。技能内置一套**自包含修复副本**与**一键启动脚本**，
并固化了三处会导致「不通」的真实坑（见 references/troubleshooting.md）。

## 何时使用

- 用户想把 WorkBuddy 免费模型接入自建/已有本地 LLM 网关。
- 用户参照公众号《俯仰未来》文章配置 `workbuddy_to_api` 报错（502 / 400 / FileNotFoundError）。
- 需要区分「永久免费」与「限时免费」并在 models.json / 网关 `/v1/models` 标注。
- 需要一键启动桥接（3000）+ 网关（8000）。

## 架构

```
WorkBuddy 客户端 / dashboard / 任意 OpenAI 客户端
        │  (models.json 里 wb-* 指向 8000)
        ▼
┌─────────────────────┐        ┌──────────────────────────┐
│ 本地 LLM 网关  8000  │ 转发   │ workbuddy_to_api  3000    │
│ 通道名: wb2api       │ ─────▶ │ (WorkBuddy 免费 credits)  │
└─────────────────────┘        └────────────┬─────────────┘
                                             │ --serve 委派
                                             ▼
                                    WorkBuddy 桌面端 (IPC)
```

> 所谓「免费」走的是 CodeBuddy 个人版 credits 额度池（5000 + 体验包 + 裂变包，各有到期周期），
> 并非「零成本无限」。额度耗尽或到期需自行充值。`assets/free_models_meta.json` 是标注的单一数据源。

## 前置条件

1. 已安装并登录 WorkBuddy 桌面客户端，能正常对话（workbuddy_to_api 调用其底层 CLI）。
2. 本机已有本地 LLM 网关项目（含 `gateway.db` 与 `.venv`），或准备单独使用 3000 桥接。
3. 若 WorkBuddy 装在非默认盘（如 D 盘，而 `LOCALAPPDATA` 指向 C 盘），启动脚本会自动探测；
   探测不到时再在 `assets/.env` 显式写 `WORKBUDDY_EXE` / `WORKBUDDY_CLI_SCRIPT` 绝对路径。

## 操作流程

### 步骤 1 — 探测环境（D 盘路径 + 本机代理）

- 定位 WorkBuddy 安装目录：`WorkBuddy.exe` 与 `resources\app.asar.unpacked\cli\bin\codebuddy`。
  标准路径 `C:\Users\<user>\AppData\Local\Programs\WorkBuddy\`；若实际在 D 盘，`start_bridge.bat`
  会自动扫描，扫描不到再在 `assets/.env` 写死 `WORKBUDDY_EXE` / `WORKBUDDY_CLI_SCRIPT`。
- 检查本机代理：若环境变量 `HTTP_PROXY` / `HTTPS_PROXY` 指向 `127.0.0.1:xxxx` 且 `NO_PROXY` 为空，
  所有打 `127.0.0.1` 的调用会被发往代理 → 10061 连接拒绝。启动脚本已固化 `NO_PROXY=127.0.0.1,localhost`。

### 步骤 2 — 启动 workbuddy_to_api 桥接（3000）

优先使用技能自包含副本（`assets/`，已打 wb-* 别名补丁、`.env` 留空由 `start_bridge.bat` 自动探测 WorkBuddy/Python 路径）：

```bash
cd <skill>/assets
python workbuddy_to_api.py --api-key local
```

验证：

```
curl http://127.0.0.1:3000/health
curl http://127.0.0.1:3000/v1/models
```

两者应返回 200。若返回 502，先查 `NO_PROXY` 与 WorkBuddy 桌面端是否登录。

### 步骤 3 — 接入本地 LLM 网关（8000）

在**网关根目录**运行技能脚本（脚本会自动探测当前目录的 `gateway.db`）：

```
cd <你的网关目录>
python "<skill>/scripts/add_workbuddy_to_api_channel.py"
```

脚本会：
- 从 `http://127.0.0.1:3000/v1/models` 发现模型（绕过代理）；
- 读取 WorkBuddy 本地缓存 `entry_*.info`，区分「永久 / 限时」免费；
- 在 `gateway.db` 写入 `wb2api` 通道（`type=openai`、`base_url=3000`、全部模型 + `model_map` wb-*→真实名）；
- 写 `free_models_meta.json` 标注永久/限时；
- 同步 `~/.workbuddy/models.json`，模型名加「免费-永久」/「免费-限时」前缀。

可选参数：`--discover`（仅打印）、`--test`（直连上游真实调用）、`--disable`（置停用）、`--no-sync-models-json`。

> 网关动态读库，加通道通常无需重启；稳妥起见重启网关。

### 步骤 4 — 标注免费类型

`assets/free_models_meta.json` 为标注单一数据源，键为网关暴露名 `wb-*`，值含
`free_type`（permanent/limited）、`expires_at`、`note`。如需刷新（如促销到期），重跑步骤 3 即可。

### 步骤 5 — 一键启动桥接（3000）

双击 `assets/start_bridge.bat` 即可在新窗口启动 workbuddy_to_api（3000，key=local），
脚本已固化 `NO_PROXY` 并自动探测 WorkBuddy/Python 路径。该 bat 为**纯 ASCII**
（Windows 中文系统用 GBK 解析 .bat，UTF-8 中文注释会乱码并被当成命令执行，详见 troubleshooting.md）。

若你另有本地 LLM 网关，启动网关后再运行步骤 3 脚本接入；网关侧的一键启动请沿用你自己的网关项目。

### 验证

```
curl http://127.0.0.1:8000/v1/models        # 应暴露 52 个 wb-* 模型
curl http://127.0.0.1:8000/v1/chat/completions -H "Authorization: Bearer <网关key>" \
  -d "{\"model\":\"wb-glm-5.3\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"max_tokens\":50}"
```

## 关键限制

当前 WorkBuddy 版本的 `--serve` 把生成**委派给桌面端 IPC**。当 agent 会话（或任何桌面端对话）
正在进行时，`wb-*` 模型调用会排队等待、变慢甚至超时。**结束 agent 会话、桌面端空闲后再用**，
出字即正常。这是架构限制，非配置问题。

## 资源

- `scripts/add_workbuddy_to_api_channel.py` — 接入网关通道 + 永久/限时标注（自动探测网关目录）。
- `scripts/wait_health.py` — 健康检查 + 打印免费模型计数（可选工具）。
- `assets/` — 自包含修复副本（`workbuddy_to_api.py` 已打补丁 + `.env` + 自动探测版 `start_bridge.bat`）。
- `assets/free_models_meta.json` — 永久/限时标注示例（单一数据源）。
- `references/troubleshooting.md` — 三大常见坑的根因与修复命令。
