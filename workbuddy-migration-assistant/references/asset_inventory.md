# 资产清单白名单

代码读取本文件来决定"导出/导入哪些资产"。修改本文件即可调整迁移范围，无需改代码。

格式约定：每一节顶部的 `<!-- machine: ... -->` 是机器可读的 JSON，代码会解析这段；正文是人读的说明。

## DB 表（必迁）

<!-- machine:db_tables
[
  {"name": "sessions", "has_deleted_at": true, "exclude_status": ["running", "Running", "in_progress", "InProgress", "active", "Active", "awaiting_input", "stopping", "working", "Working"], "exclude_self_session": true},
  {"name": "automations", "has_deleted_at": true},
  {"name": "automation_runs", "has_deleted_at": false, "fk": {"col": "automation_id", "ref_table": "automations", "ref_col": "id"}},
  {"name": "automation_runtime_state", "has_deleted_at": false, "fk": {"col": "automation_id", "ref_table": "automations", "ref_col": "id"}},
  {"name": "workspaces", "has_deleted_at": false},
  {"name": "buddy_snapshots", "has_deleted_at": false, "since": "v1.8.0", "description": "行业 Buddy 应用配置快照（5.5.0+），主键 snapshot_id"},
  {"name": "workspace_trust_decisions", "has_deleted_at": false, "since": "v2.0.0", "description": "工作区信任确认决策（5.7.0+），主键 workspace_key 为绝对路径，导入时按 PathMapper 重写（path_rewrite.db_columns 已声明，PK 冲突 target-wins）"}
]
-->

- `sessions`：会话元数据。`user_id` 来自 `account.uid`。导出时过滤：
  - `deleted_at IS NULL`（必须未软删除）
  - `status NOT IN (running/Running/in_progress/InProgress/active/Active/awaiting_input/stopping)`：**只跳过正在执行中的**对话——这些在目标端会呈现为"中断、待确认、无法停止"的僵尸态
  - 注意 `pending/Pending` **不在跳过列表**里。pending 是"新建未发消息"或"用户输入中"的静态态，跨机器后正常可用
  - `Completed/Failed/Terminated/error/archived` 是终态，正常迁
  - 同时跳过执行本次迁移的 session：通过 `--exclude-session-id <id>` 或环境变量 `WORKBUDDY_CURRENT_SESSION_ID` / `CODEBUDDY_SESSION_ID` 传入
- `automations`：定时任务。同上
- `automation_runs`：执行历史。外键 `automation_id` 必须在 automations 表内，否则丢弃并 warn
- `automation_runtime_state`：调度器运行时状态。主键也是 `automation_id`
- `workspaces`：工作区路径足迹。主键是 `path`，跨机路径不同也不冲突
- `buddy_snapshots`（v1.8.0，5.5.0+）：行业 Buddy 应用配置快照（config_json 含模板与场景配置），主键 `snapshot_id`；sessions 表新增 `buddy_snapshot_id`/`buddy_binding_json` 列由列交集导出自动兼容，无需代码改动
- `workspace_trust_decisions`（v2.0.0，5.7.0+）：工作区信任确认决策（首次打开含开发配置的工作区时用户点过「信任」的记录），主键 `workspace_key` 为工作区绝对路径，跨机导入时按 PathMapper 重写（PK 冲突时 target-wins）；不迁则换机后所有工作区需逐个人工重新信任

**不迁的表**（避免泄漏未列入清单的内容）：`session_usage`（缓存）、`migration_meta`（DB 自身的版本管理）、`automation_delivery_outbox`（投递出站队列，含敏感 payload_json，运行时状态）、`__workbuddy_drizzle_migrations`（ORM 迁移记录，内部状态）、未来新增的所有表

## 文件资产（必迁）

<!-- machine:file_assets
[
  {"path": "skills", "type": "dir-of-dirs", "merge": "skip-if-exists", "skip_indices": ["agent-created-skills.json", "_bm_skillid_migration.json", ".disable_to_model_invocation_migration.json", ".model_invocation_to_override_migration.json", ".user_invocable_only_to_off_migration.json"]},
  {"path": "memory", "type": "dir-of-files", "pattern": "*_memory.md", "exclude_suffix": [".bak"], "merge": "append-with-separator"},
  {"path": "settings.json", "type": "json", "merge": "shallow-target-wins"},
  {"path": "mcp.json", "type": "json", "merge": "mcp-servers-by-name"},
  {"path": "models.json", "type": "json", "merge": "list-by-id", "list_field": "models", "id_field": "id"},
  {"path": "IDENTITY.md", "type": "file", "merge": "imported-suffix"},
  {"path": "SOUL.md", "type": "file", "merge": "imported-suffix"},
  {"path": "USER.md", "type": "file", "merge": "imported-suffix"},
  {"path": "plugins/known_marketplaces.json", "type": "json", "merge": "list-by-id", "list_field": "marketplaces", "id_field": "name"},
  {"path": "tasks", "type": "dir-of-dirs", "merge": "skip-if-exists", "description": "任务管理数据（按 session_id 分目录）", "optional": true},
  {"path": "teams", "type": "dir-of-dirs", "merge": "skip-if-exists", "description": "团队配置数据", "optional": true},
  {"path": "sessions", "type": "dir-of-dirs", "merge": "skip-if-exists", "description": "活跃会话状态", "optional": true},
  {"path": "local_storage", "type": "dir-of-files", "merge": "skip-if-exists", "description": "本地键值存储", "optional": true},
  {"path": "traces", "type": "dir-of-dirs", "merge": "skip-if-exists", "description": "执行追踪日志", "optional": true},
  {"path": "file-history", "type": "dir-of-dirs", "merge": "skip-if-exists", "description": "文件版本历史", "optional": true},
  {"path": "experts", "type": "dir-of-dirs", "merge": "skip-if-exists", "description": "自定义专家定义（含专家团），4.24.0+", "optional": true},
  {"path": "plugins/marketplaces/my-experts", "type": "dir-of-dirs", "merge": "skip-if-exists", "description": "自建专家技能包", "optional": true},
  {"path": "MEMORY.md", "type": "file", "merge": "imported-suffix", "description": "根级长期记忆（5.3.3+，与 memory/{uid}_memory.md 双轨并存）", "optional": true},
  {"path": "assistant-display", "type": "dir-of-files", "pattern": "*.json", "merge": "skip-if-exists", "description": "助手显示配置（per-assistant json，5.4.x）", "optional": true, "since": "v1.3.0"},
  {"path": "mcp-approvals.json", "type": "json", "merge": "shallow-target-wins", "description": "MCP 工具审批记录（用户已批准的工具授权，迁移后免重新逐个确认，5.4.x）", "optional": true, "since": "v1.3.0"},
  {"path": "changes-detail", "type": "dir-of-dirs", "merge": "skip-if-exists", "description": "文件变更过程详情（per-session，5.3.11 开关 + 5.4.5 云端变更文件）", "optional": true, "since": "v1.3.0"},
  {"path": "changes-index", "type": "dir-of-files", "pattern": "*.json", "merge": "skip-if-exists", "description": "文件变更索引（per-session json，配套 changes-detail）", "optional": true, "since": "v1.3.0"},
  {"path": "storage", "type": "dir-of-dirs", "merge": "skip-if-exists", "uid_dirs": "user-{uid}", "description": "用户级个性化数据（专家偏好/选择/preferences，子目录名含 uid 需重写，5.4.x）", "optional": true, "since": "v1.3.0"},
  {"path": "app/app-config.json", "type": "json", "mode": "field-subtree", "extract_fields": ["personalization.customPrompt", "personalization.toneStyle"], "exclude_fields": ["sandboxSafetyEnabled"], "on_missing": "skip", "on_invalid": "warn-skip", "merge": "field-subtree-merge", "description": "App 级配置（仅迁 personalization.* 子树：自定义指令、语气风格；sandboxSafetyEnabled 等本机运行时开关不迁移）", "optional": true, "since": "v1.2.1"},
  {"path": "connectors/skills", "type": "dir-of-dirs", "merge": "skip-if-exists", "description": "连接器技能包（connector-*，随连接器安装生成），5.3.11+", "optional": true},
  {"path": "automation-backups", "type": "dir-of-files", "merge": "skip-if-exists", "description": "自动化配置备份（含 prompt 真实数据）", "optional": true},
  {"path": "brain", "type": "dir-of-dirs", "merge": "skip-if-exists", "description": "研究计划数据（research_plan_*.md）", "optional": true},
  {"path": "todos", "type": "dir-of-dirs", "merge": "skip-if-exists", "description": "任务/待办数据", "optional": true},
  {"path": "plans", "type": "dir-of-files", "merge": "skip-if-exists", "description": "计划文件（plan 会话产物）", "optional": true},
  {"path": "deliverables", "type": "dir-of-dirs", "merge": "skip-if-exists", "description": "交付物数据", "optional": true},
  {"path": "artifact-index", "type": "dir-of-files", "pattern": "*.json", "merge": "skip-if-exists", "path_rewrite": "artifact-index", "description": "会话产物索引（per-session json，记录该会话产出的交付文件清单；5.4.4 起产物区改版、5.4.5 修复历史会话早期产物丢失后成为产物列表的唯一来源），uri 为 URL 编码绝对路径，导入时按 PathMapper 重写", "optional": true, "since": "v1.6.0"},
  {"path": "buddy-snapshots", "type": "dir-of-dirs", "merge": "skip-if-exists", "description": "行业 Buddy 应用快照实体目录（bs_<hash>/skills/...，与 DB 表 buddy_snapshots 配套：表存元数据、此目录存技能包实体；内容寻址 hash 命名，同名即同内容故 skip-if-exists 安全，5.5.0+）", "optional": true, "since": "v2.0.0"},
  {"path": "buddy-skill-store", "type": "dir-of-dirs", "merge": "skip-if-exists", "description": "行业 Buddy 应用内置技能存储（cb_<id>/builtin--skill_*/...，Buddy 应用运行时依赖的技能包实体，5.5.0+）", "optional": true, "since": "v2.0.0"},
  {"path": "workspace-display-names.json", "type": "json", "merge": "shallow-target-wins", "description": "工作区自定义显示名（workspaces 字典按路径 key 合并，目标端已有同名 key 保留）", "optional": true, "since": "v2.0.0"},
  {"path": "templates", "type": "dir-of-files", "pattern": "*.md", "merge": "skip-if-exists", "description": "用户模板文件（如 project-doc-tree.md 重定向桩，project-doc-tree-init 技能约定落点；源端无则跳过）", "optional": true, "since": "v2.1.0"},
  {"path": "repeat-flow-report", "type": "dir-of-files", "merge": "skip-if-exists", "description": "可复用流程挖掘工作区顶层产物（需求聚类/排名报告 .md、flow-data/demand 数据 .json、last-run.json；过程草稿 .work/ 不迁）", "optional": true, "since": "v2.1.0"},
  {"path": "repeat-flow-report/.tools", "type": "dir-of-files", "pattern": "*.py", "merge": "skip-if-exists", "description": "可复用流程挖掘脚本（extract_intents/mine_demand/final_mine/auto_map2/cluster_1022/rank_1022_v2/run_window_1022 等；同目录中间 json 产物不迁，重跑即可再生）", "optional": true, "since": "v2.1.0"}
]
-->

合并策略说明：
- `skip-if-exists`：同名目录存在则跳过整个目录（除非 `--overwrite`）
- `append-with-separator`：文件存在时追加分隔符再 append 源内容，保留导入端原文在前
- `shallow-target-wins`：JSON 浅合并，导入端已有 key 保留
- `mcp-servers-by-name`：`mcpServers` 字典按 server name 合并，同名 skip
- `list-by-id`：数组类型，按指定 id 字段去重合并
- `imported-suffix`：目标已存在则写为 `<name>.imported<.md>`，避免人格污染
- `field-subtree-merge`（v1.2.1 新增）：字段级白名单合并——仅迁 `extract_fields` 指定的子树字段，子树内逐 key target-wins；`exclude_fields` 显式拒绝；源端缺失时按 `on_missing` 策略处理，JSON 损坏时按 `on_invalid` 策略处理

## 默认迁但加警告

<!-- machine:warned_assets
[
  {"path": "connectors", "type": "dir-of-userdirs", "warn": "OAuth refresh_token 可能跨机器/跨变体失效，建议导入后重新授权", "credentials_files": [".credentials.json"]},
  {"path": "credentials", "type": "dir-of-dirs", "warn": "专家凭证（token.json 等）跨机器可能失效，建议导入后到专家面板重新授权", "allow_non_uid_dirs": true},
  {"path": ".credentials.json", "type": "file", "warn": "根级 MCP OAuth 凭证（mcpOAuth：serverName/accessToken/clientId），跨机器可能失效，建议导入后到连接器面板重新授权", "credentials_files": [".credentials.json"], "since": "v1.6.0"}
]
-->

- `connectors/<uid>/`：包含 `mcp.json`、`connector-states.v3.json`、`.credentials.json`、`tokens/`、`README-DO-NOT-DELETE.txt`
- 根级 `.credentials.json`（v1.6.0 新增）：全局 MCP OAuth 凭证（`mcpOAuth` 结构），迁移它才能真正兑现"迁移后免重新授权"；受同一 `--no-credentials` 门控
- `.credentials.json` 受 `--no-credentials` 门控（推荐跨机器时排除）
- `tokens/` 内为连接器 OAuth 凭证，跨机大概率失效，建议导入后重新授权
- `README-DO-NOT-DELETE.txt` 为客户端标记文件，迁移原样保留即可，勿删

## Conversations（默认带，可选）

<!-- machine:conversations
{"path": "projects", "type": "session-keyed-jsonl", "filter": "by_sessions_table_id", "controlled_by": "--no-conversations"}
-->

- `projects/<projectFolder>/...jsonl`：消息体存档
- 导出时按 sessions 表的 `id` 集合过滤，只带和 session 关联的，孤儿 jsonl 不带
- 包体可能很大（GB 级），可用 `--no-conversations` 排除

## 严禁迁移

<!-- machine:never_migrate
[
  "logs/",
  "audit-log/",
  "usage-log.json",
  "binaries/",
  "git-bash/",
  "skills-marketplace/",
  "app/cache/",
  "session_usage (table)",
  "projects_repair_backup_*/",
  "blobs/",
  "backup/",
  "shell-snapshots/",
  "cache/",
  "connectors-marketplace/",
  "plugin-marketplace-state-new/",
  "pending-telemetry/",
  "edge-sync-mapping*",
  "device-id",
  "qimei-cache.json",
  "last-launch.json",
  "workspace-state.json",
  "user-state.json",
  "session_fragment_repair_done*",
  "tencent-docs-engine.port",
  "workspace/",
  "workbuddy.db-wal",
  "workbuddy.db-shm",
  "ioa-im-override.json",
  "security/",
  "claw-state/",
  "file-tree-manifests/",
  "app/memory/",
  "app/sessions.json",
  "app/playbook-covers/",
  ".workbuddy-sqlite-migrations/",
  "skill-cloud-sync/",
  "appearance-resources/",
  "clipboard-images/",
  "editor-sdk-sandbox-ws/",
  "wbipc/",
  "pw-profile-wb/",
  "failover.json*",
  "epoch-marker*.json",
  ".skill-list-cache.json",
  ".legacy-localstorage-migration.done",
  ".playwright-driver-node-reuse.done",
  "desktop_conversation_migrated",
  "migration-reports/",
  "unified-asset/",
  "cloudstudio-deploy-history/",
  "native-runtimes/",
  "pw-profile-verify/",
  "plugin-account-state/",
  "plugin-status-daily.json",
  "recent-visits.json",
  "system-ca-bundle.pem",
  "weread_login_qr.txt",
  "device-id.machine",
  "app/data/",
  "cli-env/",
  "extension-registry/",
  "external-packages/"
]
-->

- 认证 token 不在根目录下，在 `~/Library/Application Support/CodeBuddyExtension/Data/Public/auth/`，绑定机器和 authId，不迁
- 审计日志是哈希链结构，断了就废，不迁
- node binaries 和 git-bash 是平台相关二进制，目标机器自己构建
- skills-marketplace、app/cache 是缓存，目标端首次启动自动重建
- blobs/ 是二进制对象缓存（可能数百 MB），backup/、cache/、connectors-marketplace/、plugin-marketplace-state-new/、pending-telemetry/、shell-snapshots/ 均为客户端运行时自管目录，目标端自动重建，不迁
- `edge-sync-mapping*`（v1.3.0 通配）：端云同步映射已演进为 v2/v4 版本（含 -shm/-wal），跨机后由客户端重建，全部不迁
- `device-id`/`qimei-cache.json` 绑定设备标识（v1.3.0 显式声明），迁移会导致设备识别异常，绝不迁
- `last-launch.json`/`workspace-state.json`/`user-state.json`/`session_fragment_repair_done*`/`tencent-docs-engine.port`/`ioa-im-override.json`（v1.3.0 显式声明）为运行时状态或环境配置，目标端自生成
- `workspace/`（v1.3.0 显式声明）为会话级运行时状态（permission.json/modify_backup/snapfile），由 projects/ 会话数据承载真实上下文，不迁
- `workbuddy.db-wal`/`-shm` 为 SQLite WAL 运行时文件，导出已用 backup API 取一致性快照，不迁
- `security/`（v1.6.0 显式声明）为威胁特征库（threat-database），客户端启动时自动更新重建，不迁
- `claw-state/`（v1.6.0 显式声明）为 Claw 通道运行时状态（如 weixin 子目录），目标端自生成，不迁
- `file-tree-manifests/`（v1.8.0 显式声明，5.5.0+）为请求级文件树清单缓存（按 createdAt 记最近请求，全部绝对路径），客户端按新请求重建，不迁
- `app/memory/`（v1.8.0）为内存轮询租约锁文件（polling-lease-<用户名>.json），运行时状态，不迁
- `app/sessions.json`（v1.8.0）为 app 级会话列表缓存，目标端启动重建，不迁（真实会话元数据在 DB sessions 表）
- `app/playbook-covers/`（v1.8.0，5.5.0+）为行业 Buddy 应用封面图缓存（hash.png + meta.json），应用侧可重建，不迁
- `.workbuddy-sqlite-migrations/`（v2.0.0，5.6.x+）为客户端 SQLite schema 迁移脚本执行记录，目标端按自身版本重放，不迁
- `skill-cloud-sync/`（v2.0.0）为技能云同步的迁移标记（market-config-migration.json），目标端自生成，不迁
- `appearance-resources/`（v2.0.0）为主题外观资源缓存（theme-*/），客户端启动重建，不迁
- `clipboard-images/`（v2.0.0）为剪贴板粘贴图片历史（clipboard-*.png），属对话过程临时产物，不迁（正式产物在 artifact-index/projects）
- `editor-sdk-sandbox-ws/`（v2.0.0）为编辑器 SDK 沙箱工作区，运行时状态，不迁
- `wbipc/`（v2.0.0）为 IPC 端点配置（endpoint.json 含本机管道名），运行时状态，不迁
- `pw-profile-wb/`（v2.0.0）为 Playwright 浏览器 profile，平台相关运行时，不迁
- `failover.json*`（v2.0.0 声明，v2.1.0 改通配）为服务故障转移配置（trustedOrigins/fallbackAddresses/circuit）及其临时残留（`failover.json.<pid>.tmp`），网络层运行时状态，目标端自生成，不迁
- `epoch-marker*.json`（v2.0.0 声明，v2.1.0 改通配）为沙箱管道 epoch 标记（命名管道地址，实测存在 `epoch-marker-<pid>.json` 数字后缀变体），运行时状态，不迁
- `.skill-list-cache.json`（v2.0.0）为技能列表扫描缓存（含各技能 SKILL.md 摘要），客户端按需重建，不迁
- `.legacy-localstorage-migration.done` / `.playwright-driver-node-reuse.done` / `desktop_conversation_migrated`（v2.0.0）均为客户端升级迁移完成标记（防重跑哨兵），目标端按自身版本重跑迁移，不迁
- `skills/` 下的 `.disable_to_model_invocation_migration.json` / `.model_invocation_to_override_migration.json` / `.user_invocable_only_to_off_migration.json`（v2.0.0，5.6.x 技能迁移标记）已通过 skills 条目 `skip_indices` 排除（代码层生效），同 `_bm_skillid_migration.json` 先例
- 根级裸 uid 目录（如 `0028c709-.../`，v2.0.0 观察）内为 `sidebar-list-snapshot.json` 侧栏列表快照缓存，客户端重建；uid 为动态值无法静态声明，依赖白名单制天然排除，显式声明防误加
- `migration-reports/`（v2.1.0）为本工具自身的导入报告目录（`import-<ts>.json`，import.py 写入目标端 `<target>/migration-reports/`，供导入后在目标机查找审计记录）；源端的历史报告是过往迁移的行为记录，迁过去只会误导，不迁（5.9.1 起官方客户端迁移功能或复用同名目录，同理不迁）
- `unified-asset/`（v2.1.0）为统一资产注册缓存（skills/experts/connectors 的 localKey→目录映射，如 `ex_xxx → skill-design-team`），客户端按目录扫描重建，不迁
- `cloudstudio-deploy-history/`（v2.1.0）为 CloudStudio 部署历史（per-deploy json，含 absolutePath/workspacePath 等本机绝对路径），属部署台账，不迁
- `native-runtimes/`（v2.1.0，5.8.3 起随版本切换）为内置运行时（browser-use/computer-use 及 state.json），平台相关二进制与版本绑定状态，目标端自行准备，不迁
- `pw-profile-verify/`（v2.1.0）为 Playwright 验证浏览器 profile，同 `pw-profile-wb/` 先例，平台相关运行时，不迁
- `plugin-account-state/`（v2.1.0）为每账号插件激活状态（`<uid>.json`：各插件 enabled/activatedAt），账号级运行时状态，目标端按激活行为重建，不迁
- `plugin-status-daily.json`（v2.1.0）为插件每日状态上报时间戳（launchReportAt/focusWindowReportAt 等），遥测类运行时状态，不迁
- `recent-visits.json`（v2.1.0）为「最近访问」UI 状态（条目含 URL 编码绝对路径），界面 recents 缓存，不迁
- `system-ca-bundle.pem`（v2.1.0）为系统 CA 证书 bundle 缓存（约 100KB，企业代理/证书环境相关），客户端从系统信任库重建，不迁
- `weread_login_qr.txt`（v2.1.0）为微信读书登录二维码临时文件（登录完成后即失效），瞬时产物，不迁
- `device-id.machine`（v2.1.0）为设备标识变体（同 `device-id` 先例），绑定设备，绝不迁
- `app/data/`（v2.1.0）为 app 级专家历史记录（expert-history.json，最近使用专家列表），UI recents 缓存，不迁
- `cli-env/`（v2.1.0）为 CLI 环境脚本（如 wecom-cli.sh，含本机路径与环境假设），目标端自生成，不迁
- `extension-registry/`（v2.1.0）为扩展目录缓存（audience-index.json 等），客户端重建，不迁
- `external-packages/`（v2.1.0）为外部安装包落地目录（如 pdf-cli），平台相关二进制，目标端按需自装，不迁
- 根级 `user-<uid>-personal/`（v2.1.0 观察）内为 IDENTITY/SOUL/USER/MEMORY.md 的按账号副本与 `workspace-state.json`。实测（5.9.3）：该副本陈旧——MEMORY.md 停留在旧版本日期，而根级 MEMORY.md 为活写文件；IDENTITY/SOUL/USER 与根级逐字节相同。活文件均已在白名单，此目录依赖白名单缺席天然排除；uid 为动态值无法静态声明，同裸 uid 目录处理

## 路径重写目标（跨机时）

跨机迁移会重写下列位置里的本机绝对路径。规则由 `--path-map <src>=<dst>` 提供，按最长前缀匹配。

<!-- machine:path_rewrite
{
  "db_columns": [
    {"table": "sessions", "column": "cwd"},
    {"table": "workspaces", "column": "path", "pk": true},
    {"table": "automations", "column": "cwds", "type": "json_array"},
    {"table": "automation_runs", "column": "source_cwd"},
    {"table": "workspace_trust_decisions", "column": "workspace_key", "pk": true}
  ],
  "files": [
    {"path": "projects/*/*.meta.json", "json_path": "cwd"},
    {"path": "settings.json", "json_path": "defaultWorkspaceRoot"},
    {"path": "mcp.json", "json_pattern": "mcpServers.*.{command,cwd}"},
    {"path": "connectors/*/mcp.json", "json_pattern": "mcpServers.*.{command,cwd}"}
  ],
  "directory_renames": [
    {"base": "projects", "encode": "compressWorkspacePath"}
  ]
}
-->

- 注意：`projects/<projectId>/` 的目录名本身就是 `compressWorkspacePath(cwd) = re.sub(r'[/\\\\:]+', '-', cwd).strip('-')`。重写 sessions.cwd 后必须同步 rename 这个目录，否则对话点开是空白
- automations.cwds 是 JSON array，逐条 rewrite
- `mcp.json` 里 stdio MCP 的 `command`/`cwd` 字段可能含本机路径，重写时按 json_pattern 扫
- prompt / memory / markdown 正文里可能内嵌路径，**默认不动**，但在 import 报告 `suspicious_path_refs` 段列出可疑位置让用户人工改；**v1.2.1 起例外**：`MEMORY.md` 与 `memory/{uid}_memory.md` 纳入重写范围，复用 `PathMapper` 做锚定路径 token 替换（仅替换形如绝对路径的 token，避免误伤自然语言文本）

## Workspace 内容（可选迁移，跨机才有意义）

<!-- machine:workspace_bundles
{
  "controlled_by": "--with-workspaces",
  "default": false,
  "source": "workspaces table (path column)",
  "exclude_patterns_file": "workspace_excludes.md",
  "size_warn_per_dir_bytes": 1073741824,
  "size_warn_total_bytes": 10737418240,
  "size_limit_per_dir_bytes": 5368709120,
  "default_destination": "~/wb-imported-workspaces/"
}
-->

- 默认不带（避免莫名打出几 G 的包）
- 同机迁移（manifest source 三元组 == 目标） → 即便加 `--with-workspaces` 也跳过，因为本机路径已可直接访问
- 跨机迁移 → 走第二个 zip 包 `<main>-workspaces.zip`
- 单 workspace 排除后超过 `size_limit_per_dir_bytes`（5GB）默认 skip + warn，用户须 `--workspace-include` 显式带上
- 超过 `size_warn_per_dir_bytes`（1GB）继续但 warn

## 重启感知

<!-- machine:restart_required
{
  "restart_after_any_of": [
    "db",
    "models.json",
    "settings.json",
    "plugins/known_marketplaces.json",
    "SOUL.md",
    "USER.md",
    "connectors/*/connector-states.json"
  ],
  "hot_reloaded": [
    "mcp.json",
    "connectors/*/mcp.json",
    "memory/*_memory.md",
    "IDENTITY.md",
    "skills/*"
  ]
}
-->

- 99% 的迁移场景都会动 DB → 导入完成后向用户提示"请重启 WorkBuddy 客户端使改动生效"
- mcp.json / IDENTITY.md / memory / skills 有 watcher 或每轮重读，不用重启
- 已打开的会话即便 skill 是热加载的，system prompt 已注入旧 skill 列表，**新会话**才能看到新 skill
