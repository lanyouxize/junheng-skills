# 📊 Token Usage · WorkBuddy/CodeBuddy Token 用量统计插件

**安装即用**的 Token 消耗统计面板：实时数据 + GitHub 风格热力图 + 每日趋势图 + 模型用量占比 + 当前会话拆分。

> 你的 Token 花在哪、什么时候花的、被哪个模型吃掉了——一屏看完。

---

## 一、原理（30 秒看懂）

WorkBuddy / CodeBuddy（CLI 内核）会把每场对话的完整记录写进本机的**会话转录文件**（`.jsonl`），其中每一条模型响应都带有官方返回的 token 计量数据：

```
providerData.usage = { inputTokens, outputTokens, totalTokens, inputTokensDetails[{cached_tokens}], ... }
```

本插件做三件事：

1. **扫描**本机转录目录（默认 `~/.codebuddy/projects/**/*.jsonl`），流式解析每条用量记录
2. **聚合**成四个维度：按天 / 按模型 / 按会话 / 全局总量
3. **渲染**成可视化面板（终端摘要、HTML 面板、实时服务、JSON 四种输出）

### 🔒 隐私声明（重要）

- **所有数据只在你本机读取和计算，插件不含任何网络上传行为**
- 唯一的外部资源是图表库 ECharts，已直接内置在插件包内，**断网也能用**
- 面板服务默认只监听 `127.0.0.1`（本机回环地址），外部无法访问

---

## 二、安装

### 方式 1：从 Skills 市场安装（推荐）

在客户端插件/Skills 市场搜索 **token-usage**，一键安装。

### 方式 2：手动安装

把插件包解压后，整个目录放进：

```bash
~/.codebuddy/skills/token-usage/        # Linux / macOS
%USERPROFILE%\.codebuddy\skills\token-usage\   # Windows
```

> 目录结构要求：`token-usage/SKILL.md` + `token-usage/scripts/token_stats.py`。安装后**新开会话**生效。

### 环境要求

| 项 | 要求 |
|---|---|
| Python | 3.8+（**仅标准库，无需 pip 安装任何东西**） |
| 磁盘 | 插件约 1.1 MB（含内置 ECharts） |
| 网络 | 不需要（完全离线可用） |

---

## 三、怎么用

装好后，在对话里**直接说人话**即可：

| 你说 | 你会得到 |
|---|---|
| 「打开 token 面板」 | 实时面板显示在软件预览区，**每 30 秒自动刷新** |
| 「统计一下 token 消耗」 | 终端摘要 + 可视化面板 |
| 「导出 token 用量明细」 | JSON 文件（按天/按模型/按会话） |
| 「近 7 天哪个模型用得多」 | 模型用量拆分分析 |

### 触发条件

**会触发**：提到 token / 用量 / 消耗 / 面板 / 使用统计（如"我用了多少 token"）
**不会触发**：与用量无关的普通请求（如"帮我写周报"）——正常现象

首次使用时，插件会弹出**对话选择框**让你选：打开实时面板 / 生成静态快照 / 导出 JSON。之后意图明确时直接执行，不再多问。

---

## 四、面板里有什么

| 指标 | 口径说明 |
|---|---|
| 累计 Token | 全部转录的总消耗（输入+输出，**含**缓存读取部分，与官方 totalTokens 口径一致） |
| 当前会话消耗 | 自动识别你正在用的会话（按心跳文件匹配），单独统计 |
| 缓存命中率 | 缓存读取 ÷ 输入 tokens（越高说明上下文缓存利用越好） |
| 峰值（单日） | 历史上单日消耗最高的一天 |
| 最长会话时长 | 单个转录文件首尾时间戳跨度 |
| Token 活动热力图 | 近 52 周逐日消耗，颜色越深用量越大，悬浮显示"tokens · 轮次" |
| 每日趋势 | 近 7/30 日切换，按日历日补零，不漏天 |
| 模型用量环形图 | 各模型占比（联动 7/30 日范围） |

---

## 五、小白常见坑（FAQ）

### ❓ 点击"打开面板"按钮没反应？

部分客户端版本的组件环境不支持自动发送消息。**直接在对话框输入「打开 token 面板」**即可，效果完全一样。（插件已内置兜底：按钮点击无反应时会自动显示这行提示。）

### ❓ 面板里看不到历史数据 / 热力图只有一格？

这是**数据边界**，不是 bug：面板统计的是 **agent 沙箱内实际存在的转录文件**。桌面客户端的历史会话数据在你本机，沙箱读不到。想统计全部历史：把本机 `~/.codebuddy/projects`（Windows：`%USERPROFILE%\.codebuddy\projects`）目录打包发给 agent，并告诉它用 `--data-dir` 指向解压路径。

### ❓ 提示"数据目录不存在"？

不同产品/版本的数据目录可能不同。先确认转录文件在哪：

```bash
ls ~/.codebuddy/projects/*/    # 能看到 <会话ID>.jsonl 就是这里
```

然后运行时指定：`python3 token_stats.py --data-dir <你的目录>`

### ❓ 面板链接打不开 / 显示无法访问？

面板服务跑在 agent 运行环境里。两种情况：
1. **服务停了**（环境休眠会杀后台进程）→ 在对话里重新说「打开 token 面板」，agent 会自动拉起
2. **你的浏览器与运行环境网络不互通** → 用对话内的内置预览打开（agent 的 present_files 通道，必通）

### ❓ 提示端口被占用？

换端口：`python3 token_stats.py --serve 8643`，然后告诉 agent 用新地址打开。

### ❓ Windows 上提示时区警告？

Windows 缺时区数据库。执行 `pip install tzdata`，或忽略警告（自动回退系统时区）。

### ❓ 转录文件很大会很慢吗？

流式逐行解析，百 MB 级文件也在数秒内完成；实时服务对结果做了 3 秒缓存，连续刷新不重复计算。

### ❓ 统计口径和软件里显示的对得上吗？

对得上（都是官方 `totalTokens` 累加，含缓存读取）。差异只可能来自：转录文件被清理/未同步到统计环境。

### ❓ 如何卸载？

删除 `~/.codebuddy/skills/token-usage/` 目录（或市场里卸载），再结束 `token_stats.py --serve` 进程即可。不留任何残留。

---

## 六、进阶用法

```bash
# 实时面板（指定端口与时区）
python3 scripts/token_stats.py --serve 8642 --tz Asia/Shanghai

# 静态快照（自包含 HTML，可发给同事）
python3 scripts/token_stats.py --html report.html --tz Asia/Shanghai

# JSON 明细（按天/按模型/按会话全量字段）
python3 scripts/token_stats.py --json stats.json

# 统计自定义目录（如上传的历史数据）
python3 scripts/token_stats.py --data-dir /path/to/projects
```

---

## 七、文件清单

```
token-usage/
├── .codebuddy-plugin/plugin.json   # 插件元数据
├── SKILL.md                        # Agent 执行规范（触发条件/工作流/口径）
├── README.md                       # 本文件
└── scripts/
    ├── token_stats.py              # 核心脚本（纯标准库，单文件）
    └── echarts.min.js              # 内置图表库（离线可用）
```

## License

MIT
