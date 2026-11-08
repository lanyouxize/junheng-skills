---
name: token-saver-qclaw
description: token智能省流助手（安全加固版 6.1.0-hardened）。仅对「纯自然语言、长文本」做显式压缩；内置硬门禁，代码/URL/颜色值/路径/密钥/YAML 一律拒绝并返回原文。切勿作为输入预处理器自动全量生效。
license: Proprietary
compatibility: Python 3.9+; POSIX shell.
---

> **安全加固说明（2026-10-14 本地加固，基线备份见 outputs/_governance/_skill_backup_20261014_0022）**
> 原版存在「压缩破坏语义」高危缺陷：`#.*` 会删 `#fff`/锚点/shebang，`//.*` 会删 URL，
> 全局 filler 会误伤引号内字面量与否定句。本版改为**占位符保护 + 硬门禁 + 可回溯 diff**。
> **定位：显式工具，不是输入预处理器。禁止对用户全部输入自动生效。**

Token 智能省流助手
节省幅度取决于语料：客气话密集的长指令收益最大（实测 27 -> 17 token 量级（2026-10-16 修复后复测）），重复性长文收益很低（句中句式不动）；阈值与模式可调
面向 QClaw / OpenClaw 本地智能体的轻量化 Token 优化工具
一款专为本地大模型对话场景设计的无依赖、纯本地、安全可控的 Token 省流 Skill。由 Agent 或用户显式调用，仅对纯自然语言长文本（任务指令 / 说明 / 对话）做句首句尾礼貌语与多余空白清理；内置硬门禁，代码 / URL / 颜色值 / 路径 / 密钥 / YAML 一律拒绝并逐字返回原文。可降低单次对话与上下文长度，从而节省模型推理开销、延长对话窗口、提升响应速度。**显式工具，不是输入预处理器，禁止自动全量生效。**

核心功能

1. 智能内容类型识别
自动判断输入内容类型，采用差异化压缩策略：
纯文本：日常提问、咨询、长句描述、闲聊对话
代码内容：Python/Java/JS/Shell/HTML 等代码块（默认门禁拒绝，需调用方显式放行后才处理）
混合内容：文字提问 + 代码示例组合场景
识别为代码/URL/配置等形态时直接拒绝并返回原文，不会误判导致语义丢失或代码损坏。

2. 三级可切换压缩强度
支持用户通过自然语言自由切换压缩模式，全局记忆生效：
轻度模式
仅清理多余空格、换行、重复空白符，最大程度保留原文语气，适合需要完整表达的场景。
默认模式（推荐）
移除冗余语气词、礼貌用语、无效助词，适度简化长句，平衡省流效果与语义完整性。
严格模式
深度精简句式，删除连接词、代词、冗余修饰词，实现更高压缩比，适合长文本、连续对话。

3. 文本优化（首尾锚定，句中不动）
句首/句尾礼貌语削离
将 “你好，我想请问一下怎么用QClaw部署一个本地大模型，谢谢” 简化为 “怎么用QClaw部署一个本地大模型”（只削文本首尾的礼貌语，句中正文一律不动）
句中礼貌语不动
句中和段中出现的 “谢谢” 等按原样保留——只锚定首尾，不做句中替换（避免拼接出歧义句）
空格与格式规范化
统一换行、缩进、多空格，减少格式类 Token 浪费。

4. 代码安全压缩（需显式放行，不破坏逻辑）
仅当调用方显式传入放行参数后才处理代码；默认门禁对代码一律拒绝并返回原文
仅压缩格式：空行、多余缩进、连续空格
分级清理注释
默认模式清除行首 `#` 单行注释，严格模式进一步清除行首 `//` 单行注释，大幅降低代码类 Token 占用
三引号多行字符串内的注释行是字符串内容不是注释，原样保留（S-07）
不修改变量名、逻辑结构、语法关键字，压缩后代码可直接运行

5. 系统指令保护机制
自动识别并跳过以 “系统:、指令:、技能:、config:” 等开头的关键指令，避免因压缩导致功能异常、工具调用失败或智能体行为错乱。

6. 实时 Token 节省统计
精准估算原始 Token 与压缩后 Token
每次调用展示本次节省 Token 数量
展示当前压缩模式，用户一目了然

7. 自然语言指令控制（无需传参）
用户可直接开口控制，无需复杂参数配置：
打开省 Token 提示 / 关闭省 Token 提示
严格模式 / 轻度模式 / 默认模式
最强压缩 / 正常模式 等口语化指令

适用场景
QClaw / OpenClaw 本地智能体日常对话
代码提问、编程辅助、长文本咨询
上下文较长、容易超出模型窗口的对话
希望降低本地模型显存占用、提升响应速度
企业 / 个人私有化部署，追求安全、无外网依赖


QClaw 调用示例
json
{
  "skill": "token_saver_qclaw",
  "params": {
    "text": "你好，我想请问一下怎么用QClaw部署一个本地大模型，谢谢"
  }
}
返回结果示例：
json
{
  "status": "success",
  "content_type": "pure_text",
  "current_mode": "default",
  "original_token": 27,
  "compressed_token": 17,
  "token_saved": 10,
  "compressed_text": "怎么用QClaw部署一个本地大模型",
  "tip": "已节省 10 Token（default模式，估算）"
}

支持指令清单
提示开关
打开省 token 提示
关闭省 token 提示
打开提示
关闭提示
压缩强度
严格模式 / 最强压缩
轻度模式 / 轻度压缩
默认模式 / 正常模式 / 标准模式
版本信息
版本：6.1.0-hardened（安全加固版；平台包版本 1.0.1）
适配平台：QClaw / OpenClaw / 命令行
上架平台：SkillHub
运行方式：本地纯 Python 执行
依赖：无任何第三方库

---

## 安全门禁（硬规则，违反即拒绝并返回原文）

命中以下任一条 → `status: refused`，**原文逐字返回**：

| 规则 | 示例 |
|---|---|
| 含代码块标记 ``` 或行内反引号 | ```python ... ``` |
| 含 URL | `https://a.com` |
| 含十六进制颜色值 | `#fff` `#1a2b3c` |
| 含 shebang | `#!/usr/bin/env python` |
| 含 Markdown 标题 | `# 标题` |
| 疑似 YAML/JSON 结构 | `key: value` 多行 |
| 含绝对路径 | `C:\a\b.txt` `/usr/bin/x` |
| 疑似密钥/凭据 | `sk-` `AKIA` `ghp_` `BEGIN PRIVATE KEY` |
| 文本短于 20 字 | 压缩无收益 |
| 压缩比 > 40% | 疑语义受损（先降级 light 重试，仍超限则拒绝） |

**即使通过门禁，以下内容也被占位符保护、原样还原**：代码块、行内代码、URL、
单/双引号内字面量、十六进制颜色值、shebang 行。

## CLI 用法

```bash
python token_saver_skill.py --text "我想请问一下你能不能帮我写一个爬虫，谢谢" --mode default --json
python token_saver_skill.py --file note.md --mode light
cat note.md | python token_saver_skill.py --mode strict
python token_saver_skill.py --text "def f(): # 注释" --allow-code   # 代码需显式放行
```

## 禁止使用场景（明确不得调用）

- 代码文件、配置（YAML/JSON/TOML）、Markdown 文档
- 他人指令原文、待执行的任务描述、法律/医疗/金额等精确文本
- memory-manager 的输出、tiangong 生成的 SKILL.md（含 YAML front-matter 与表格）
- 任何"自动对用户全部输入生效"的管道配置

## 输出契约（四条必带）

`original_sha256`（可回溯原文）、`diff`（被删片段回显）、
`token_estimate.method`（标注 heuristic 粗估）、`status`（success/refused/passthrough）。

---

## 调用时机与 squeeze 工作流（2026-10-14 新增）

**定位重申：显式工具，不是输入预处理器。** 本环境无任何机制会自动调用本技能
（`run.sh` 仅为占位），一切压缩由 Agent 或用户显式发起。

### 触发时机（三条同时满足才调用）

1. 待发送文本 >= 500 字（阈值可用 `--min-len` 调整）
2. 纯自然语言指令/说明：无代码、无 URL、无配置、无表格、无路径
3. 有压缩价值：客气话密集的长指令、重复性说明

### 白名单 / 黑名单

- 白名单：长段任务指令、重复性说明、礼貌语密集的请求
- 黑名单：代码、YAML/JSON/TOML、Markdown 文档、表格、路径、密钥、
  memory-manager 输出、tiangong 生成的 SKILL.md、他人指令原文

### 推荐入口：squeeze（双层防线 + 台账）

```bash
python tools/skill_hardening_kit.py squeeze --text "..." --json          # 预检 dry-run，不落盘
python tools/skill_hardening_kit.py squeeze --file note.txt --apply --output note.squeezed.txt
```

squeeze 在 token-saver 门禁之外还有一层自有危险预检（`SQUEEZE_DANGER`），
即使 token-saver 被升级改坏仍有效。退出码：0 成功 / 1 用法错误 / 2 拒绝 / 3 文本过短跳过。
台账：`outputs/_governance/_squeeze_ledger.json`（仅 `--apply` 记账，含累计节省统计）。

### 收益预期（如实说明，勿夸大）

压缩只删「句首/句尾礼貌语 + 多余空白」，句中重复正文不动——
- 对客气话密集的长指令收益最大（实测 27 -> 17 token 量级（2026-10-16 修复后复测））
- 对重复性长文收益很低（句中句式不动）
- 限免窗口内积分成本为 0.00x，压缩的价值主要是上下文窗口利用率与响应速度
