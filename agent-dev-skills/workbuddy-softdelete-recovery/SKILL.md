---
name: workbuddy-softdelete-recovery
description: 当 WorkBuddy 的自动化任务或会话"全部消失/列表为空"但数据实际仍在时，诊断并恢复被软删除（deleted_at 标记）的记录。触发词：自动化任务不见了、会话丢失、任务列表空白、近期任务丢失、recovered from workbuddy.db、软删除恢复。
---

# WorkBuddy 软删除恢复（自动化 / 会话误删）

## 适用场景
用户报告"自动化任务不见了""近期任务丢失了很多""会话消失了""任务列表空白"，但数据很可能并未真正删除——只是被隐藏。

## 根因
WorkBuddy 在 `~/.workbuddy/workbuddy.db`（SQLite）中用 `deleted_at` 列做**软删除**："删除"只是写入一个时间戳，列表查询 `WHERE deleted_at IS NULL` 据此隐藏整行。近期"账号所有权归属 / 清理对账"流程存在 bug，会在应用更新或启动（如某次 08:34）**批量软删** `sessions`（会话）与 `automations`（自动化）。同一秒删除几十条 = 程序行为，绝非用户手动。数据本身完好，可无损恢复。

## 诊断（只读，先读后写，绝不先改）
```python
import sqlite3, os
db = os.path.expanduser("~/.workbuddy/workbuddy.db")
con = sqlite3.connect(db); con.isolation_level = None   # 只 SELECT，不写
cur = con.cursor()
for t in ('automations', 'sessions'):
    cur.execute(f"SELECT COUNT(*) FROM {t} WHERE deleted_at IS NOT NULL")
    print(t, "soft-deleted:", cur.fetchone()[0])
# 删除时间分布：确认是否为批量事件（同一时间戳 = bug）
cur.execute("SELECT deleted_at FROM sessions WHERE deleted_at IS NOT NULL ORDER BY deleted_at")
```
- `automations` 关键列：id, name, status, deleted_at, owner_user_id, owner_status, rrule, cwds
- `sessions` 含 `deleted_at` 列
- 若 `workbuddy.db-wal` 存在，说明 WorkBuddy 应用正在运行：直接 UPDATE 会写入 WAL，应用下次查询即可见（无需立即重启）

## 修复（反删除，不丢任何数据）
1. **先备份**：`cp workbuddy.db workbuddy.db.bak.<时间戳>`（连同 `-wal` / `-shm` 一起备更稳妥）
2. 清空软删除标记：
```python
cur.execute("UPDATE automations SET deleted_at = NULL WHERE deleted_at IS NOT NULL")
cur.execute("UPDATE sessions    SET deleted_at = NULL WHERE deleted_at IS NOT NULL")
con.commit()
```
3. 校验：再次统计两表 `deleted_at IS NOT NULL` 应为 0；用 `automation_update(mode=list)` 确认列表恢复。
4. 提示用户**刷新 / 重开"自动化"面板与"历史"面板**即可看到；若必须重启应用，留意重启后是否再次消失。

## 复发与上报
- 若恢复后**重启应用又消失** = 该清理 bug 在每次更新/启动都会触发。此时不要再反复重启，保留 `workbuddy.db.bak.*` 备份，并向 WorkBuddy 官方反馈（附删除时间集中在同一秒的证据）。
- 不要对 `automation_runs` / `automation_runtime_state` 等执行记录做改动。
- 本流程是"反删除 / 恢复"，与"禁止用 DB 操作删除自动化"的安全规则不冲突。
