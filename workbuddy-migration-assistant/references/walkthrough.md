# 全流程实战样例（walkthrough）

一次真实的「Windows 旧机 → Windows 新机」lite 迁移全记录，所有终端输出均为实测抓取（已脱敏：路径替换为 `<演示目录>`，uid/主机名为演示值）。读完即可对照自己的执行结果逐行核对。

## 场景设定

| 角色 | 值 |
|------|-----|
| 源目录 | `<演示目录>/src-root`（模拟 `~/.workbuddy/`） |
| 迁移包 | `<演示目录>/wb.zip` |
| 目标目录 | `<演示目录>/target`（新机，已登录并创建过至少一条对话） |
| 预设 | 导出 `--profile lite`，导入 `--profile auto` |

包内资产：1 个技能、1 份记忆、3 份身份文件、3 份配置、2 条会话、1 个定时任务、1 条会话的 jsonl 记录。

---

## 第 1 步 · 导出预检（dry-run，只输出计划不写文件）

```bash
$ python scripts/export.py --source <演示目录>/src-root --output <演示目录>/wb.zip --profile lite --dry-run
```

```json
{
  "kind": "export-plan",
  "source": {
    "root": "<演示目录>\\src-root",
    "os": "win32",
    "home": "C:\\Users\\<用户名>",
    "user_ids": ["a1b2...8f90"],
    "exclude_session_ids": ["43c9...806b"]
  },
  "main_package": {
    "contents_summary": {
      "configs_present": ["settings.json", "mcp.json", "models.json"],
      "identity_files_present": ["IDENTITY.md", "SOUL.md", "USER.md"],
      "skills_count": 1,
      "memory_uids": ["a1b2...8f90"],
      "db_table_row_counts": { "sessions": 2, "automations": 1, "workspaces": 1 }
    }
  },
  "caveats": []
}
```

**怎么读**：`contents_summary` 是将打包的内容清单；`exclude_session_ids` 是自动排除的当前会话（防僵尸对话）；`caveats` 非空时逐条处理再导出。

## 第 2 步 · 正式导出

```bash
$ python scripts/export.py --source <演示目录>/src-root --output <演示目录>/wb.zip --profile lite
```

```
Profile: lite (no credentials)
Source: <演示目录>\src-root (variant=unknown)
DB: 4 rows across 5 tables
------------------------------------------------------------
[db] exported: sessions=2, automations=1, workspaces=1, ...
[file:skills] copied: count=1
[file:memory] copied: count=1
[file:settings.json] copied:
[file:app/app-config.json] field-extracted: fields=2
[conversations] copied: jsonl_count=1, meta_files=1, bytes=36, orphans_dropped=0
------------------------------------------------------------
  Main package: <演示目录>\wb.zip (0.0 MB)
------------------------------------------------------------
```

**怎么读**：`Profile: lite` 确认预设生效（主包 + 丢弃凭证）；`[db]` 各表行数；`field-extracted` 表示 app 配置只提取了 personalization 子树（本机开关不迁移）；`orphans_dropped` 是没有对应会话的孤立记录，丢弃属正常。大包时会出现 `[进度]` 节流行。

## 第 3 步 · 检视迁移包（可选）

```bash
$ python scripts/info.py --package <演示目录>/wb.zip
```

```
  文件:         <演示目录>\wb.zip
  大小:         4.9 KB
  工具版本:     1.5.0 (schema v2)
  源 OS / 主机 / Home: win32 / <主机名> / C:\Users\<用户名>
  当前 user_id: a1b2...8f90
  建议:         Use --auto-map for automatic cross-platform path remapping.
```

**怎么读**：`工具版本` 高于目标端工具版本时先升级技能再导入；跨机场景直接采纳建议用 `--auto-map`。

## 第 4 步 · 导入预检（dry-run）

```bash
$ python scripts/import.py --package <演示目录>/wb.zip --target auto --profile auto --dry-run
```

输出与正式导入同构，全部动作显示为 `would-merge` / `would-create`：`[db] would-merge`、`[file:skills] would-merge`、`[conversations] would-merge`。有冲突会在此步全部列出，确认无意外再进第 5 步。

> 报 `Cannot determine the target user_id automatically`：新机还没登录过 WorkBuddy，先打开客户端登录并随便建一条对话，再重跑；或显式传 `--uid-map 源uid=目标uid`。

## 第 5 步 · 正式导入（含 verify 资产校验）

```bash
$ python scripts/import.py --package <演示目录>/wb.zip --target auto --profile auto
```

```
[db] merged: tables={'sessions': {'inserted': 2, 'skipped_or_replaced': 0}, ...}
[file:skills] merged: created=1, skipped=0, overwritten=0
[file:memory] merged: created=1, appended=0, overwritten=0
[file:settings.json] merged: added=1, replaced=0, skipped=0
[file:IDENTITY.md] created:
[conversations] merged: created=2, skipped=0, overwritten=0
[validation] passed=True, total_checks=5, passed_checks=4
[session_projects_diff] source_sessions=2, target_projects=1, difference=1
[verify] verified: checks=6, expected_total=11, present_total=11, missing_total=0, verdict=all-present
------------------------------------------------------------
✓ 导入完成。请重启 WorkBuddy 客户端使改动生效。
重启后生效：db, settings.json, models.json, SOUL.md, USER.md
已热加载（不用重启）：mcp.json, IDENTITY.md
uid 自动映射：{'a1b2...8f90': 'f0e9...ccb0'}
✓ 资产校验：11/11 项全部就位。
提示：直接关闭并重新打开 WorkBuddy 即可，无需退出账号。
```

**逐行解读**：

| 输出 | 含义 |
|------|------|
| `merged: inserted=2, skipped=0` | DB 按主键合并，目标已有同 id 行默认跳过（不覆盖） |
| `created=1 / skipped=0 / overwritten=0` | 技能目录：新建 1 个；目标已存在的会跳过除非 `--overwrite` |
| `appended` | 记忆文件按「分隔符追加」合并，不丢目标端已有记忆 |
| `[validation] passed=True` | 导入后 DB/文件完整性自检 |
| `[session_projects_diff]` | 会话数 vs 落地项目目录数差值三分类（orphan/in-flight/真实差异），difference>0 时给出 breakdown |
| `[verify] verdict=all-present` | **资产校验结论**：导出清单 11 项在目标端全部就位 |
| `已热加载` | 这些文件改完即生效，不用重启 |

**verify 报告 JSON（`<目标>/migration-reports/import-<ts>.json` 的 `sections.verify`）**：

```json
{
  "action": "verified",
  "checks": [
    { "item": "skills", "status": "ok", "expected": 1, "present": 1 },
    { "item": "memory", "status": "ok", "expected": 1, "present": 1 },
    { "item": "identity", "status": "ok", "expected": 3, "present": 3 },
    { "item": "configs", "status": "ok", "expected": 3, "present": 3 },
    { "item": "conversations", "status": "ok", "expected": 1, "present": 1 },
    { "item": "db:sessions", "status": "ok", "expected": 2, "present": 2 }
  ],
  "expected_total": 11,
  "present_total": 11,
  "missing_total": 0,
  "verdict": "all-present"
}
```

某项 `status=partial` 时，该 check 的 `missing` 数组列出缺失名单。`status=skipped` 表示你显式跳过了该范围（如 `--skip-skills`），不计入缺失。

## 第 6 步 · 重启验证

完全关闭 WorkBuddy（含托盘）→ 重新打开 → 检查旧对话、技能、记忆。**完成标准：verify verdict = all-present 且重启后旧对话可打开。**

---

## 报告 JSON 常用字段速查

| 字段 | 位置 | 用途 |
|------|------|------|
| `sections.verify` | import 报告 | 资产校验结论与缺失名单 |
| `sections.session_projects_diff` | import 报告 | 会话数与项目目录差值归因 |
| `sections.uid_mapping` | import 报告 | 本次生效的 uid 映射 |
| `restart_required` | import 报告 | 哪些资产需重启生效 / 哪些已热加载 |
| `backups` | import 报告 | 被覆盖资产的 `.bak-<ts>` 备份路径（回滚用，不自动清理） |
| `options.profile` | 包内 manifest.json | 导出时用的预设 |
| `asset_inventory` | 包内 manifest.json | 导出资产清单（verify 的比对基准） |

报错了？按错误码查 `faq.md`「按错误码速查」表；更冷门的问题查 `known-issues.md`。
