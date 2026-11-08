---
name: workbuddy-migration-assistant
version: 2.1.0
display_name: "WorkBuddy迁移助手"
display_name_en: "WorkBuddy Migration Assistant"
allowed-tools: Read,Write,Bash
description: WorkBuddy 跨机器资产迁移助手。换电脑时把旧机的 skills、memory、conversations、automations、MCP 与连接器配置、身份与专家偏好、信任决策与 OAuth 凭证等资产导出为主包加产物包两包，再一键导入新机。支持 lite 等预设档。
description_zh: WorkBuddy 国内版跨机器资产迁移助手：换电脑时一键导出/导入全部个人资产（技能、记忆、对话、配置、连接器凭证、会话产物索引等），两包分离快速传输、路径自动映射、导入后自动校验，跟着主线六步完成搬家。
description_en: Cross-machine asset migration assistant for WorkBuddy China edition. Export and restore all personal assets (skills, memory, conversations, configs, connector credentials, artifact index) when switching computers, with a two-package layout, automatic path remapping and post-import verification in six guided steps.
author: 该影
license: Proprietary
compatibility: Python 3.9+.
---

# WorkBuddy迁移助手

将一台旧电脑上的 WorkBuddy 国内版（`~/.workbuddy/`）全部个人资产，完整迁移到新电脑。两包分离、路径自动映射、冲突可见可控。

> **本文档只保留入口分派与关键约束**。命令参数、流程图、冲突规则、已知问题等细节按需加载 `references/`（见文末索引）。
## 三分钟迁移主线（换机全流程，从这条线开始）

**第 1 步 · 选场景**：换电脑选 `--profile lite`（最快）或 `--profile full`（含对话工作目录文件）；仅本机备份选 `--profile backup`。不确定就用 `lite`。

**第 2 步 · 旧电脑导出**（约 1 分钟）：

```bash
python scripts/export.py --source auto --output ~/Desktop/wb.zip --profile lite
```

预期输出：`Profile: lite` → 各资产 copied → `Main package: ...zip`。报错首行是 `[E-xxx]` 稳定错误码，按 `references/faq.md` 速查表定位。

**第 3 步 · 传包**：`wb.zip` 拷到新电脑（微信/网盘/U盘均可）。`full` 还会生成 `wb-workspaces.zip`（对话文件，单独传，丢了不影响主包导入）。

**第 4 步 · 新电脑预检**（dry-run 只看计划不写入）：

```bash
python scripts/import.py --package ~/Desktop/wb.zip --profile auto --dry-run
```

预期输出：各资产 `would-merge` 计划与冲突预览，确认无意外再执行。

**第 5 步 · 新电脑正式导入**：

```bash
python scripts/import.py --package ~/Desktop/wb.zip --profile auto
```

预期输出：各资产 merged → `✓ 资产校验：N/N 项全部就位` → `请重启 WorkBuddy`。缺项按报告 `verify` 段 missing 名单排查。

**第 6 步 · 重启验证**：完全关闭并重新打开 WorkBuddy。**完成标准**：报告 `verify.verdict = all-present` 且旧对话可打开、技能可用。

> 每步真实输出与 JSON 解读见 `references/walkthrough.md`，报错/异常查 `references/faq.md`；本机恢复 backup 包改用 `--auto-map`（避免丢凭证）；`python` 优先用 WorkBuddy managed Python（系统 3.8+ 亦可）。

## 适用场景

**适用**：换电脑（Mac / Linux / Windows 互迁）、备份恢复、多机同步。**不适用**：同机国内版↔海外版迁移（请使用 `WorkBuddy 资产迁移` 技能）。

> **与官方迁移功能的分工**（客户端 5.9.1+）：设置内「从其他电脑导入」仅覆盖任务/空间/定时任务三类且限同账号；本技能覆盖全部资产类型的跨机全量迁移，二者互补。对照详见 `references/known-issues.md`。

## 资产范围全景

迁移覆盖 WorkBuddy 个人数据的**全部**资产类型：

```
~/.workbuddy/
├── workbuddy.db              → DB 表（sessions/automations/workspaces/buddy_snapshots/workspace_trust_decisions 等）
├── skills/                   → 所有已安装技能包
├── memory/                   → {uid}_memory.md 记忆文件
├── MEMORY.md                 → 根级长期记忆（5.3.3+，双轨并存）
├── assistant-display/        → 助手显示配置（5.4.x）
├── mcp-approvals.json  changes-detail/  changes-index/ → MCP 审批记录 / 文件变更过程详情（5.3.11+）
├── storage/                  → 用户级个性化数据（专家偏好/选择，uid 子目录自动重写，5.4.x）
├── credentials/              → 专家凭证（带警告迁移，导入后建议重新授权）
├── settings.json  mcp.json  models.json  IDENTITY.md  SOUL.md  USER.md → 设置/MCP/模型配置 + 人格身份/灵魂设定/用户信息
├── app/app-config.json       → App 级配置（仅迁移 personalization.* 子树：自定义指令 customPrompt、语气风格 toneStyle 等；sandboxSafetyEnabled 等本机运行时开关不迁移）
├── .credentials.json         → 全局 MCP OAuth 凭证（迁移后免重新授权，--no-credentials 可排除）
├── artifact-index/           → 会话产物索引（每会话的交付文件清单，5.4.4+；跨机自动重写路径）
├── buddy-snapshots/  buddy-skill-store/ → 行业 Buddy 应用快照实体与内置技能存储（5.5.0+）
├── workspace-display-names.json → 工作区自定义显示名
├── connectors/{uid}/         → 连接器状态与凭证
├── connectors/skills/        → 连接器技能包（connector-*，5.3.11+）
├── automation-backups/       → 定时任务配置备份
├── brain/  todos/  plans/  deliverables/ → 研究计划/任务/计划/交付物数据
├── experts/                  → 自定义专家（含专家团），4.24.0+
├── templates/  repeat-flow-report/ → 用户模板 / 流程挖掘工作区（脚本+报告）
├── plugins/                  → 仅 known_marketplaces.json + 自建专家包(my-experts)
├── projects/                 → 所有历史对话记录（.jsonl + meta.json）
└── ~/WorkBuddy/              → 对话工作目录（代码生成产物、下载文件等）⚡ 仅 --with-workspaces 打包
```

### 绝对不迁移的

| 资产 | 原因 |
|------|------|
| `binaries/`、`git-bash/`、`logs/`、`audit-log/` | 平台相关二进制 / 运行时日志，目标机自建 |
| `app/cache/`、`skills-marketplace/` | 缓存，首次启动自动重建 |
| `blobs/`、`cache/`、`backup/`、`shell-snapshots/` | 二进制/运行时缓存，目标端自动重建 |
| `connectors-marketplace/`、`plugin-marketplace-state-new/`、`pending-telemetry/` | 运行时状态，目标端自动重建 |
| `edge-sync-mapping*`（含 v2/v4） | 端云同步映射，跨机后客户端重建 |
| `device-id`、`qimei-cache.json` | 设备绑定标识，迁移会导致设备识别异常 |
| `last-launch.json`、`workspace-state.json`、`user-state.json`、`workspace/`、`tencent-docs-engine.port` | 运行时状态，目标端自生成 |
| `session_usage` 表 | 运行时用量统计 |
| `automation_delivery_outbox` / `__workbuddy_drizzle_migrations` 表 | 投递队列（含敏感 payload）/ ORM 内部记录 |
| 认证 token（`CodeBuddyExtension/Data/auth/`） | 绑定机器，跨机后失效 |
| `projects_repair_backup_*` | 客户端升级/修复自动生成的快照，每份数百 MB~GB，无迁移价值 |
| `file-tree-manifests/`（5.5.0+） | 请求级文件树清单缓存（绝对路径），客户端按新请求重建 |
| `app/memory/`、`app/sessions.json`、`app/playbook-covers/` | 轮询锁/会话列表缓存/Buddy 封面缓存（5.5.0+），目标端自生成 |
| `.workbuddy-sqlite-migrations/`、`skill-cloud-sync/`、`appearance-resources/`、`clipboard-images/`、`editor-sdk-sandbox-ws/`、`wbipc/`、`pw-profile-wb/` | 迁移记录/云同步标记/主题缓存/剪贴板历史/SDK 沙箱/IPC/浏览器 profile，客户端重建（5.6–5.7） |
| `failover.json*`、`epoch-marker*.json`、`.skill-list-cache.json`、`*.done` 升级哨兵、`desktop_conversation_migrated` | 故障转移/管道标记（含 pid 后缀变体）/技能列表缓存/迁移完成标记，目标端自生成（5.6–5.7） |
| `migration-reports/`、`unified-asset/`、`cloudstudio-deploy-history/`、`native-runtimes/`、`pw-profile-verify/`、`plugin-account-state/`、`plugin-status-daily.json`、`recent-visits.json`、`system-ca-bundle.pem`、`weread_login_qr.txt`、`device-id.machine`、`app/data/`、`cli-env/`、`extension-registry/`、`external-packages/` | 迁移导入报告/资产注册缓存/部署历史/内置运行时/验证 profile/插件状态/最近访问/CA 缓存/登录二维码/设备标识/专家历史/CLI 环境/扩展缓存/外部安装包（5.8–5.9） |

## 两包分离架构

| 包 | 文件名 | 内容 | 典型大小 | 必传 |
|----|--------|------|----------|------|
| **主包** | `wb-migration-{timestamp}.zip` | DB、Skills、Configs、Identity、Memory、Connectors、Conversations | 10-100 MB | ✅ 必须 |
| **产物包** | `wb-migration-{timestamp}-workspaces.zip` | 所有对话目录下的文件资料（代码、报告、图片、下载等） | 100 MB - 50 GB | ❌ 可选 |

**设计意图**：主包小而精可网盘/微信快传；产物包独立传输，下载失败不影响主包导入；可不传产物包（对话"可回顾但无文件"），后续按需补传。

## 关键约束（每次执行必须遵守）

1. **导入前必须退出 WorkBuddy 客户端**（SQLite 写锁冲突会导致导入失败）
2. **导入前必须关闭沙箱或确保核心配置目录可写**：WorkBuddy 沙箱的"剥写(strip_write)"策略会拦截对 `settings.json` 等核心配置的写入，导致导入中断。导入为幂等操作，被拦截后关闭沙箱重跑即可安全续传。
3. **必须排除当前迁移会话**（防止目标端出现僵尸对话）——优先级：环境变量 → 源端 DB 最新 session → `--exclude-session-id`
4. **默认合并不覆盖**（目标端已有资产保留，仅补充缺失），除非显式 `--overwrite`
5. **跨平台必做路径映射**：推荐 `--auto-map`（零配置），或手工 `--path-map` + `--target-os`
6. **导入后必须重启**：DB、models.json、settings.json 等需要重启才能生效
7. **导入前先用 dry-run 预览**：导出看计划、导入看冲突报告，确认后再正式执行
8. **推荐跨机排除凭证**：`--no-credentials`（OAuth token 跨机大概率失效），目标端到连接器面板重新授权

## Agent 调用入口分派

skill 自身不提问，由 host agent 交互。按意图关键词直接分发，不做多余预扫描：

| 用户意图 | 关键词 | 直接进入 |
|----------|--------|----------|
| 导出/备份 | 导出、备份、打包、export | 步骤 0（资产扫描）→ 流程 A |
| 导入/恢复 | 导入、恢复、import | 流程 B |
| 检视包内容 | 查看包、包里有什么、info | 流程 C |
| 未明确 | 迁移、搬家、换电脑（无方向） | 步骤 0（资产扫描）后再问 |

> 完整分派流程、步骤 0 资产扫描、流程 A/B/C：见 `references/flows.md`

## 内部参考（按需加载）

| 文件 | 何时加载 |
|------|----------|
| `references/index.md` | 需要细节时先查此索引 |
| `references/walkthrough.md` | 想看全流程真实输出样例、report JSON 字段解读时 |
| `references/faq.md` | 报错按错误码速查、导入后异常排查时 |
| `references/commands.md` | 构造 export/import/info 命令时 |
| `references/flows.md` | 导出/导入/检视执行时 |
| `references/conflict-pathmap.md` | 跨机路径重写、冲突处理、解析产物包时 |
| `references/known-issues.md` | 排查故障、准备回滚、核对版本时 |
| `references/asset_inventory.md` | 资产扫描/导出时（白名单数据驱动） |
| `references/workspace_excludes.md` | 产物包打包时（排除规则） |
