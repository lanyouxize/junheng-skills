---
name: agent-dev-skills
description: Agent 开发技能五件套：覆盖从构想到上线的全流程，含 CLI 工具发现、对话蒸馏为分身等能力。当用户要开发或增强自有 Agent、做 CLI 适配、把聊天记录沉淀为技能时用。
display_name: "Agent 开发技能集"
display_name_en: "Agent Development Skills"
description_zh: "Agent 开发技能集（5 件套组合包）—— 覆盖 agent 从灵感到落地运营的全链路：CLI 工具目录中心（agent-native CLI 工具发现）、数字分身蒸馏器（聊天/日记解构成 self-skill）、WorkBuddy 开放平台发布包打包工具（专家/技能/连接器/Buddy 应用发布）、角色库批量转换（外部 GitHub 角色库 → WorkBuddy 专家）、软删除诊断恢复（WorkBuddy 自动化/会话误删）。一键安装即得 5 件套 agent 开发利器。"
description_en: "Agent development skills bundle (5-in-1 combo) — covers the full agent lifecycle from idea to production: CLI Anything Hub (discover agent-native CLIs), Yourself Skill (distill chats/diaries into a digital twin skill), Publish to WorkBuddy Open Platform (package expert/skill/connector/Buddy app into uploadable zips), Role Library to Experts (bulk convert external GitHub role libraries into WorkBuddy experts), WorkBuddy Soft-Delete Recovery (diagnose & recover soft-deleted automations/sessions). One-click install gets 5 agent-dev power tools."
agent_created: true
version: 1.1.0
---

# Agent 开发技能集（agent-dev-skills）

本技能是一个**组合包**，在 zip 根下平铺 5 个完整 skill（各自 SKILL.md 在二级目录里）：

| Skill | 中文展示名 | 一句话 |
|---|---|---|
| `cli-anything-hub` | CLI 工具目录中心 | Agent-native CLI 工具目录中心——发现、安装、管理专业软件的命令行界面，让 AI agent 直接驱动 ... |
| `yourself-skill` | 数字分身蒸馏器 | 把自己蒸馏成 AI Skill——解构聊天记录、日记、社交媒体、照片，生成带人格和记忆模型的可运行数字分身，用于数字孪生... |
| `publish-to-workbuddy-openplatform` | WorkBuddy 开放平台发布包打包工具 | 把专家/技能/连接器/Buddy 应用打包成 WorkBuddy 开放平台「发布管理」可上传的 zip 代码包（≤20M... |
| `role-library-to-experts` | 角色库 → 专家批量转换 | 将外部 GitHub 角色库（如 agency-agents-zh、岗位库、人设集）批量转换为 WorkBuddy 专家... |
| `workbuddy-softdelete-recovery` | WorkBuddy 软删除恢复 | 当 WorkBuddy 的自动化任务或会话「全部消失/列表为空」但数据实际仍在时，诊断并恢复被软删除（deleted_a... |

## 内部布局（深度 ≤ 2，platform 「仅两级目录」约束）

```
SKILL.md                ← zip 根（组合入口，含 display_name/description_zh 4 必填字段）
icon.png / README.md    ← zip 根
BUILD.txt               ← zip 根（破缓存）
<name>/SKILL.md         ← 二级（5 个 skill 各自的入口文件）
<name>/<其它文件>       ← 二级（内部深层子目录已用 `__` 展平为文件名）
```

## 使用方式

每个子 skill 可独立调用：

- `cli-anything-hub/SKILL.md` —— CLI 工具目录中心
- `yourself-skill/SKILL.md` —— 数字分身蒸馏器
- `publish-to-workbuddy-openplatform/SKILL.md` —— WorkBuddy 开放平台发布包打包工具
- `role-library-to-experts/SKILL.md` —— 角色库 → 专家批量转换
- `workbuddy-softdelete-recovery/SKILL.md` —— WorkBuddy 软删除恢复
