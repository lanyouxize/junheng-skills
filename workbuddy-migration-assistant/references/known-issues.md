# 已知问题、回滚、FAQ 与版本演进

> 何时加载：排查故障、准备回滚、核对版本功能时。

## 已知问题

### DB 索引损坏导致 UNIQUE constraint failed

症状：
```
sqlite3.IntegrityError: UNIQUE constraint failed: sessions.id
```

根因：`workbuddy.db` 的 `sqlite_autoindex_sessions_1` 损坏。导出脚本内置了自动修复（`_dedup_duplicate_pks`），会在打包前对源 DB 副本执行 PK 去重 + REINDEX。正常情况下用户无需关心。

### macOS 上 Python 报 PermissionError

```
PermissionError: [Errno 1] Operation not permitted
```

若发生在 WorkBuddy agent 沙箱内 → 优先尝试系统 Python → 若无效则引导用户放开沙箱。若在终端手动执行 → 在系统设置中为该 Python 授予完全磁盘访问权限。

### 工作区路径含 `#` 字符

Windows / Linux / macOS 均允许文件名含 `#`，迁移按目录名原样复制不会丢失。但客户端 5.2.6 之前对含 `#` 的文件预览 / 链接存在乱码；若源端工作区路径含 `#`，导入后建议将客户端升级到 5.2.6+ 以正常预览。

### 专享版禁用 Memory 个性化

部分专享版套餐禁用了 Memory 个性化功能，源端可能不存在 `memory/` 目录。迁移助手对 `memory/` 为可选资产（skip-if-exists），源端无则跳过，不影响其他资产迁移。

### 对话消息含 reasoning-only / `@同事` 附件

5.2.6 起对话消息可能出现仅含推理过程、无正文的 `reasoning-only` 消息，以及 `/compact` 指令引用的 `@同事` 附件。迁移按 session 原样复制 `projects/*.jsonl`，结构兼容；跨机器后 `@同事` 附件若指向其他用户 / 会话可能失效，属预期行为，无需特殊处理。

### 连接器凭证实际存放于 `tokens/`

连接器凭证实际位于 `connectors/<uid>/tokens/` 目录，而非 `.credentials.json`。`--no-credentials` 仅排除 `.credentials.json`，**不会**排除 `tokens/`。跨机器迁移连接器建议导入后到连接器面板重新授权，或手动删除目标端 `tokens/` 再授权。

### MEMORY.md 与 memory/ 双轨记忆（5.3.3+）

5.3.3 起个性化页新增本地长期记忆展示与编辑，根级 `MEMORY.md` 与 `memory/{uid}_memory.md` 双轨并存。迁移助手两者均覆盖：`MEMORY.md` 用 `imported-suffix` 合并（目标端已有则写入 `MEMORY.imported.md`，不污染目标端记忆），`memory/{uid}_memory.md` 用 `append-with-separator`。若源端只有其一，另一轨自动跳过。

另注意根级 `user-<uid>-personal/` 目录（5.9.3 实测观察）：其内也有按账号的 `MEMORY.md`/`IDENTITY.md`/`SOUL.md`/`USER.md` 副本与 `workspace-state.json`，但该副本陈旧——`MEMORY.md` 停留在旧版本日期，而根级 `MEMORY.md` 为活写文件；`IDENTITY.md`/`SOUL.md`/`USER.md` 与根级逐字节相同。迁移助手只迁根级活文件，此目录不迁也不需迁（uid 为动态值无法静态声明，依赖白名单缺席天然排除）。

### 官方迁移功能与本技能的分工（客户端 5.9.1+）

5.9.1 起客户端设置内提供「从其他电脑导入」，覆盖三类数据：任务（`sessions` 表）、空间（`workspaces` 表）、定时任务（`automations` 表）；5.9.3 起支持按分类选择导入、上限 100GB。

**官方导入不包含**：skills/experts、memory 与 IDENTITY/SOUL/USER、`mcp.json`/`models.json`/`settings.json`、connectors 状态与凭证、`artifact-index/`、`buddy-snapshots/` 实体、`projects/` 对话消息体等。

分工建议：只需三类数据且同账号 → 用官方导入更快捷；换机全量资产、跨账号、或要求「迁移后免重新授权」→ 用本技能。两者可叠加（官方导三类 + 本技能补其余），互不冲突。

注意目录归属：`migration-reports/` 是本技能自身的导入报告目录（import.py 写入目标端），并非官方客户端专属；5.9.1 起官方迁移功能或复用同名目录。无论归属，源端该目录的历史报告不迁移（见「严禁迁移」清单）。

### 连接器技能包 connectors/skills/（5.3.11+）

5.3.11 起连接器附带的技能包（`connector-*`）存放于 `connectors/skills/`。迁移按目录 skip-if-exists：目标端已有同名连接器技能包则跳过整个目录，属预期行为（连接器版本可能不同）。该目录随连接器安装自动生成，源端无则跳过。

### 投递队列与 ORM 记录不迁移

`automation_delivery_outbox`（投递出站队列，含敏感 payload_json）与 `__workbuddy_drizzle_migrations`（ORM 迁移记录）为运行时/内部状态，**不迁移**。导出时白名单机制天然排除；若目标端 DB 已存在同名表，导入不会触碰。

### 沙箱 strip_write 拦截导致导入中断（v1.2.1 已处理）

症状：
```
PermissionError: [Errno 13] Permission denied: 'C:\\Users\\<user>\\.workbuddy\\settings.json'
[sandbox] 命令被沙箱拦截，以下操作被拒绝：... 剥写(strip_write)
```

根因：WorkBuddy 沙箱的"剥写"策略拦截对核心配置文件的写入。导入脚本在写 `settings.json` 等核心配置前会先做金丝雀探测，被拦截时快速失败并提示"关闭沙箱后重跑"。导入为幂等操作，重跑安全。

解法：关闭沙箱后重新执行导入命令。已完成的步骤不会重复执行。

### 自定义指令（personalization.customPrompt）迁移（v1.2.1 新增）

自定义指令存储在 `~/.workbuddy/app/app-config.json` 的 `personalization.customPrompt` 字段。v1.2.1 起纳入迁移范围，但仅迁移 `personalization.*` 子树（customPrompt、toneStyle 等），`sandboxSafetyEnabled` 等本机运行时开关不迁移。

### 目标端 BOOTSTRAP.md 残留导致身份文件冲突（v1.2.1 已处理）

症状：导入后 `IDENTITY.md` / `USER.md` 仍为模板内容，真实身份被写成 `*.imported.md`。

根因：目标端首次启动生成的 `BOOTSTRAP.md` 引导模板未被清理，导入时为避免人格污染而将真实身份写入 `.imported.md` 副本。

解法：v1.2.1 起自动检测 BOOTSTRAP 残留，备份后用备份覆盖 `IDENTITY.md`/`USER.md` 并删除 `BOOTSTRAP.md`。备份文件为 `BOOTSTRAP.md.bak-<ts>`，确认无误后可手动删除。

### 记忆文件内嵌路径未被 auto-map 重写（v1.2.1 已处理）

症状：导入后 `MEMORY.md` 和 `memory/{uid}_memory.md` 中仍引用旧用户名路径（如 `C:\Users\15810`）。

根因：auto-map 默认只重写 DB 和配置文件中的路径，不触及 memory 正文。

解法：v1.2.1 起 memory 文件纳入路径重写范围，复用 `PathMapper` 做锚定路径替换（仅替换形如绝对路径的 token，避免误伤自然语言文本中的数字）。

### 客户端升级导致会话/记录丢失（5.3.x–5.4.x 高频问题，v1.3.0 收录）

客户端多个版本出现过升级后数据丢失类问题（官方 Changelog 已修复，但升级前做一次迁移导出是最稳妥的保险）：

- 5.4.3：升级后**已置顶的任务和会话丢失**
- 5.3.11：升级后**本地助理聊天记录丢失**、重启后聊天历史全部消失、内置技能未更新到最新版

解法：升级客户端前，先用本技能执行 `export.py --dry-run` 预检 + 实际导出，升级出现异常可用产物包恢复。

### 端云同步映射版本演进（v1.3.0 已处理）

`edge-sync-mapping.db` 在 5.4.x 已演进为 `edge-sync-mapping-v2.db` / `edge-sync-mapping-v4.db`（含 -shm/-wal WAL 文件）。旧版排除规则只写单一文件名会漏排。v1.3.0 起排除规则改用 `edge-sync-mapping*` 通配，端云映射跨机后由客户端重建，全部不迁。

### 专家凭证跨机失效（v1.3.0 收录）

`credentials/<expert-name>/token.json` 等专家凭证默认随包迁移（v1.3.0 纳入 warned_assets），但 token 通常绑定环境，导入后建议到专家面板重新授权。若导入报告 warnings 中出现 credentials 警告，属预期行为。

### 根级 .credentials.json 曾被漏迁（v1.6.0 修复）

全局 MCP OAuth 凭证存在**根级 `.credentials.json`**（`mcpOAuth` 结构，key 为 `serverName|hash`），与 `connectors/<uid>/.credentials.json` 是两回事。v1.6.0 之前白名单只覆盖后者，导致「迁移后免重新授权」只兑现了一半——导入后连接器仍要逐个重新授权。v1.6.0 起根级凭证纳入 warned_assets（同受 `--no-credentials` 门控）。

### PathMapper 的 dst_os 取值会改变分隔符（v1.6.0 记录，未改代码）

`PathMapper(rules=..., src_os=..., dst_os=...)` 的 `dst_os` 必须传 `sys.platform` 风格值（`win32`/`darwin`/`linux`）。若传 `platform.system()` 的 `Windows`，重写结果会出现混合分隔符（如 `C:\Users\x\newws/report.md`）。import.py 传入的 `target_os` 已是 `win32` 风格，生产路径无此问题；新增调用方（如 artifact-index 重写）请沿用同一取值，勿混用展示用的 `Windows`。

## 回滚步骤

导入前脚本会自动备份目标端文件为 `<name>.bak-<timestamp>`：

```
~/.workbuddy/workbuddy.db.bak-20260615-092435
~/.workbuddy/settings.json.bak-20260615-092435
~/.workbuddy/mcp.json.bak-20260615-092435
~/.workbuddy/memory/<uid>_memory.md.bak-20260615-092435
...
```

回滚方法：
1. 退出 WorkBuddy
2. 在目标根目录下执行：
   ```bash
   cd ~/.workbuddy
   ts=20260615-092435  # 改成实际备份时间戳
   for f in *.bak-$ts memory/*.bak-$ts; do
     mv "$f" "${f%.bak-$ts}"
   done
   ```
3. 启动 WorkBuddy 验证

备份**不会自动清理**，确认无误后手动删除。

## FAQ

**Q: 国内版和海外版的 DB schema 一样吗？**
A: 完全一致。脚本用 `PRAGMA table_info` 做列交集 INSERT，即便未来一边加字段也能兼容（多余列丢弃并 warn）。

**Q: 包里多大？**
A: 不含对话时几 MB（skills 多可能更大）；含对话记录可能几百 MB 到几 GB。建议先 `--no-conversations` 试一次。

**Q: 迁移包里的 `.credentials.json` 安全吗？**
A: 含 access_token / refresh_token 明文。**不要传到不可信通道**。推荐用 `--no-credentials` 导出，到目标端重新授权。

**Q: 我有多个 user_id，怎么办？**
A: 使用 `--auto-map` 会自动将所有源 uid 映射到目标端当前 uid。如需手动控制，用 `--uid-map src=dst` 逐条指定。

**Q: 跨平台迁移后对话打不开？**
A: 使用 `--auto-map` 可自动处理路径映射。若仍有问题，检查恢复后校验报告中 workspace 目录不存在的条目。

## 版本演进说明

- **v0.4.0**：导出支持 `--format tar.gz` 输出格式
- **v0.3.0**：新增 `info.py` 检视命令；纳入 tasks/teams/sessions/local_storage/traces/file-history/experts 资产
- **v0.2.0**：新增 `--auto-map` 自动路径映射；新增恢复后自动校验
- **v1.0.4**（2026-07-20）：适配 WorkBuddy 5.2.6——修正连接器状态文件名为 `connector-states.v3.json`；修复 sessions 进行中态 `working` 漏排除的 P0 缺陷；补充已知问题（`#` 路径、专享版 Memory、reasoning-only/`@同事`、tokens/ 凭证位置）
- **v1.1.0**（2026-07-31）：渐进式披露重构——SKILL.md 精简至入口+关键约束，命令/流程/冲突/已知问题下沉 references/（本目录）
- **v1.2.0**（2026-08-11）：适配 WorkBuddy 5.3.11——白名单纳入 MEMORY.md/connectors/skills/automation-backups/brain/todos/plans/deliverables；DB 不迁表声明 automation_delivery_outbox/__workbuddy_drizzle_migrations；排除 blobs/backup/shell-snapshots/cache/edge-sync-mapping.db 等；补充双轨记忆与连接器技能包已知问题
- **v1.2.1**（2026-08-27）：修复 2026-08-26 实际迁移暴露的 6 个坑点——①新增 app/app-config.json 字段级导出/导入（仅 personalization.* 子树，含自定义指令 customPrompt）；②新增导入前置 strip_write 沙箱探测，被拦截时快速失败并提示关闭沙箱重跑；③修复 info.py 大包静默失败，改为 manifest 直读 + --full 两段式；④新增 BOOTSTRAP.md 残留自动处理（备份→覆盖→删除三步序列）；⑤memory 文件纳入 auto-map 路径重写（复用 PathMapper）；⑥导入报告补充 sessions vs projects 差值语义标注（区分导出过滤/导入防御/源端原始状态）
- **v1.3.0**（2026-08-31）：适配 WorkBuddy 5.4.5——①白名单纳入 assistant-display/、mcp-approvals.json、changes-detail/、changes-index/、storage/（uid 子目录重写）；②credentials/ 专家凭证纳入 warned_assets 带警告迁移；③排除规则修正：edge-sync-mapping.db 改通配 edge-sync-mapping*（v2/v4 版本演进），显式声明 device-id/qimei-cache.json/last-launch.json/workspace-state.json/user-state.json/workspace/ 等设备绑定与运行时文件不迁；④收录 5.3.x–5.4.x 客户端升级数据丢失类已知问题（置顶会话丢失/聊天记录丢失）
- **v1.4.0**（2026-08-31）：SkillHub 外部 TRACE 评测低分项（≤4.3）迭代——①异常处理：新增 scripts/lib/errors.py，常见报错统一翻译为「中文说明+下一步指引+技术细节附尾」（数据库占用/权限不足/路径不存在/包损坏等），export/import/info 三入口顶层接入；②运行稳定性：export 打包/import 解压/会话记录复制新增节流进度显示（`[进度] n% (x/y)`，大任务每 10% 输出、小任务静默）；③安全性扫描：新增 fs.safe_delete 删除守卫（仅允许删除目标根目录内路径），export/import 全部删除操作（凭证排除/uid 过滤/BOOTSTRAP 清理）统一收口
- **v1.5.0**（2026-09-01）：SkillHub 二轮评分（综合 4.6）驱动，聚焦「上手路径」——①触发方式：SKILL.md 重构为「三分钟迁移主线」，六步一条线（选场景→导出→传包→预检→导入→重启验证），不再跨文档拼凑；②易用性：export 新增 `--profile lite|full|backup` 一键预设、import 新增 `--profile auto`（= --auto-map + --no-credentials），显式 flag 永远优先，选择记入 manifest options.profile；③增值：import 导入完成自动执行 verify 资产校验（导出清单 vs 落地结果逐项比对，报告 sections.verify 含 checks/missing 名单/verdict，stdout 显示「X/X 项就位」）；④异常处理：errors.py 升级稳定错误码体系（E-LOCK/E-PERM/E-NOTFOUND/E-BADPKG/E-JSON/E-DB/E-SANDBOX/E-UNKNOWN，码义恒定不重命名），沙箱拦截显示层统一为 E-SANDBOX（内部码 E_PROBE_WRITE_DENIED 保留兼容）；⑤文档：新增 references/faq.md（最常见问题 Top 10 + 按错误码速查表）、references/walkthrough.md（全流程实测输出样例+报告字段速查），index/commands 联动更新
- **v2.1.0**（2026-10-28）：适配 WorkBuddy 5.9.3（跨 5.7.7–5.9.3 共 9 版本；另调研蓝皮书 WorkBuddyGuide 仓库 549 文件，确认为纯用户向教程、无数据路径文档，无可收割项）——①never_migrate 显式声明 5.8–5.9 新增 15 项：`migration-reports/`（本工具导入报告目录，import.py 写入目标端；源端历史报告不迁，5.9.1 起官方客户端或复用同名目录）、`unified-asset/`（统一资产注册缓存）、`cloudstudio-deploy-history/`（部署历史含本机绝对路径）、`native-runtimes/`（5.8.3 内置运行时）、`pw-profile-verify/`、`plugin-account-state/`、`plugin-status-daily.json`、`recent-visits.json`、`system-ca-bundle.pem`、`weread_login_qr.txt`、`device-id.machine`、`app/data/`（专家历史）、`cli-env/`、`extension-registry/`、`external-packages/`；`failover.json`/`epoch-marker.json` 改通配（实测存在 pid 后缀变体）；②file_assets 纳入 3 项可选用户资产：`templates/`（用户模板）、`repeat-flow-report/` 及其 `.tools/*.py`（可复用流程挖掘工作区；`.work/` 草稿与中间 json 不迁）；③SKILL.md 描述 5.7.6→5.9.3、资产树与「绝对不迁」表同步（守 160 行门禁：mcp-approvals/changes-* 与 brain/todos/plans/deliverables 两组合并、settings/mcp/models 与 IDENTITY/SOUL/USER 合并），新增与官方迁移功能分工说明；④实测排除 `user-<uid>-personal/` 旧副本疑点（personal 版 MEMORY.md 停留旧日期、根级为活写；IDENTITY/SOUL/USER 与根级逐字节相同——活文件根级已在白名单，无需改代码）；⑤sessions 仍 40 列，列交集导出自动兼容。纯功能项（语音识别/快捷键、独立文件浏览器、安全中心备份大小上限、模型选择器自定义模型、Buddy One 会员、Gmail 连接器等）无本地资产，无需迁移改动
- **v2.0.0**（2026-10-07）：适配 WorkBuddy 5.7.6（跨 5.5.2–5.7.6 共 12 版本）——①db_tables 白名单纳入 `workspace_trust_decisions` 表（5.7.0 工作区信任确认决策，主键 workspace_key 为绝对路径；path_rewrite.db_columns 声明 PK 重写，复用 rewrite_path_columns 通用机制零代码改动，PK 冲突 target-wins）；②文件白名单纳入 `buddy-snapshots/`（Buddy 应用快照实体，与 DB 表 buddy_snapshots 配套：表存元数据、目录存技能包实体，hash 命名同名即同内容）、`buddy-skill-store/`（Buddy 内置技能存储）、`workspace-display-names.json`（工作区自定义显示名，shallow-target-wins 合并）；③skills 条目 skip_indices 补 3 个 5.6.x 技能迁移标记（.disable_to_model_invocation_migration.json 等，同 _bm_skillid_migration.json 先例）；④never_migrate 显式声明 13 项 5.6–5.7 新增：.workbuddy-sqlite-migrations/（schema 迁移记录）、skill-cloud-sync/、appearance-resources/（主题缓存）、clipboard-images/（剪贴板历史）、editor-sdk-sandbox-ws/、wbipc/（IPC 运行时）、pw-profile-wb/（Playwright profile）、failover.json、epoch-marker.json、.skill-list-cache.json、3 个升级哨兵标记（.done/desktop_conversation_migrated）；⑤sessions 表 30→40 列（transport/conversation_origin/visibility/group_* /agent_dirty 系列/verified_at/unread）由列交集导出自动兼容；⑥SKILL.md 描述 5.5.1→5.7.6、资产树补 3 项（settings/mcp/models 与 IDENTITY/SOUL/USER 两组三合一压缩守 160 行门禁）、「自动化」→「定时任务」官方新叫法同步（faq/walkthrough 联动）。纯功能项（全局搜索/定时任务汇总页/Gmail·Outlook 海外连接器/插件管理等）无本地资产，无需迁移改动
- **v1.9.0**（2026-09-03）：两平台统一（SkillHub 目录直传与开放平台 zip 内容/版本/架构一致，tests 保留进开放平台包）——①测试结构摊平：`tests/fixtures/app-config.sample.json` → `tests/app-config.sample.json`，消除三级嵌套，使技能包满足开放平台「两级目录结构（任意路径段数 ≤3）」硬约束；②SRC 动态化：7 个测试文件的 `SRC` 由硬编码绝对路径改为 `Path(__file__).resolve().parent.parent` 相对定位，安装到任意机器任意目录均可自检；③开放平台 zip 纳入 `tests/`（此前 v1.6.1 因嵌套超限被排除），两平台包内容从此一致
- **v1.8.0**（2026-09-03）：适配 WorkBuddy 5.5.1（含 5.5.0）——①db_tables 白名单纳入 `buddy_snapshots` 表（5.5.0 行业 Buddy 应用配置快照；sessions 新增 buddy_snapshot_id/buddy_binding_json 列由列交集导出自动兼容，零代码改动）；②never_migrate 显式声明 5.5.x 新增缓存：`file-tree-manifests/`（请求级文件树清单，全绝对路径，客户端重建）、`app/memory/`（轮询租约锁）、`app/sessions.json`（会话列表缓存）、`app/playbook-covers/`（Buddy 封面图缓存）；③SKILL.md 描述 5.4.7→5.5.1、资产树与「绝对不迁移」表同步（守 160 行门禁：description 折叠行重排 + 区块间空行压缩）。纯功能项（微信系统分享/图片处理内置技能/视频生成参数/敏感内容确认等）无本地资产，无需迁移改动
- **v1.7.1**（2026-09-02）：展示名与 H1 由「WorkBuddy 迁移助手」改为「WorkBuddy迁移助手」（去除专名与功能词之间空格，与 workbuddy-guide「WorkBuddy使用指南」先例一致）；版本同步 1.7.1
- **v1.7.0**（2026-09-02）：WorkBuddy 开放平台上架适配（解析失败修复：目录层级超限）——`scripts/lib/` 三级嵌套违反平台「两级结构」约束（根目录/二级目录/文件），将 lib 下 15 个模块全部平铺至 `scripts/` 单层（automap/detect/manifest/db/fs/configs/report/pathmap/errors/sandbox_probe/field_extract/trace/validate/walk + __init__.py 新增），入口与全部模块的 `scripts.lib.X` import 改写为 `scripts.X`（lib 内部相对导入 `from . import` 随包上移自动成立）；tests 7 个文件与主套件路径同步；全量回归 188 PASS + 端到端 export/import 验证通过。教训：开放平台两级结构是硬约束，上架前须按「任意路径段数 ≤3」校验
- **v1.6.1**（2026-09-02）：WorkBuddy 开放平台上架准备——SKILL.md frontmatter 新增 `description_zh`/`description_en`（开放平台必填）与 `author: 该影`，`display_name_en` 补齐；版本 bump 至 1.6.1。上架包结构参照 workbuddy-guide-openplatform.zip 先例：zip 顶层为 `{skill-name}/`，排除 `tests/`（开发产物）、`__pycache__`/`.pyc`/`.bak*`
- **v1.6.0**（2026-09-01）：适配 WorkBuddy 5.4.7（官方文档无 5.4.6 条目）——①白名单纳入根级 `.credentials.json`（全局 MCP OAuth 凭证 `mcpOAuth`；此前只迁 `connectors/<uid>/.credentials.json`，「迁移后免重新授权」承诺实际落空），受同一 `--no-credentials` 门控，export/import 的 warned_assets 分支新增「文件型资产」支持；②白名单纳入 `artifact-index/`（5.4.4 产物区改版后的会话产物索引，缺失会让历史会话产物列表为空、5.4.5 修复的「早期产物丢失」复现），automap 新增 `rewrite_artifact_index`：uri 为 URL 编码绝对路径（`file-changes://D%3A%5C...`），按「解码→PathMapper 重写→重新编码」处理，非路径字段不误伤；③严禁迁移清单显式声明 `security/`（威胁特征库）、`claw-state/`（Claw 通道运行时状态）；④faq.md 吸收官方口径：更新/重装会清空安装目录、升级后工作空间消失的找回方法、沙箱剥写的官方依据、官方错误码（1001/3002/…）的能力边界澄清；⑤修复潜伏 bug：`TRACE.add(kind, **detail)` 位置参数与 `kind=` 关键字冲突（memory-tokens 分支因 tokens_replaced 为 0 从未触发而未暴露）
