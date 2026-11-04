# 每日自动刷新订阅文章（refresh 编排）

把采集层 + 写库层编排成「每日刷新」：定时调度、按订阅源拉新、去重增量、失败重试、
运行日志、状态监控、异常告警。

**编排器只做外壳，不重写采集/写库逻辑。** 每个采集层、写库层均以**子进程**隔离调用，
单源崩溃不连累整轮；复用既有 `write` 的 URL 差减去重 + vault 幂等。

## 命令

```bash
# 1) 准备订阅源清单：复制 subscriptions.example.yaml 为 subscriptions.yaml，填 sources

# 2) 手动触发一次（不传 --config 时回退技能根 subscriptions.yaml）
python collect.py refresh run --yes --config subscriptions.yaml
#    --vault       临时开启本地 vault 双写
#    --dry-run     仅打印将要执行的各源/写库命令
#    --since-days N  给所有 account 源注入 --since（today-N，覆盖源配置的 since）

# 3) 注册 Windows 计划任务（每日 08:00，重启存活、无常驻进程）
python collect.py refresh install --config subscriptions.yaml --time 08:00
#    --dry-run 仅生成 run-refresh.bat 与 schtasks 命令，不实际注册

# 4) 查看上次运行状态
python collect.py refresh status --config subscriptions.yaml

# 5) 注销计划任务
python collect.py refresh uninstall --config subscriptions.yaml

# 离线自测（不联网，验证重试/合并/告警/状态核心逻辑）
python collect.py refresh selfcheck
```

## 运行产物

默认 `out/refresh/`，可在 subscriptions.yaml 的 `refresh.output_dir` 改：

| 文件 | 内容 |
|---|---|
| `status.json` | 上次运行状态（退出码 / 拉取数 / 写入数 / 数据表 ID / 各源明细） |
| `run-<时间戳>.jsonl` | 本轮机读事件流（含各子进程转发的 emit_event） |
| `alerts.log` | 异常告警追加记录（`refresh.alert.on` 命中时；可选 webhook POST） |
| `combined-<时间戳>.jsonl` + `src-<源名>-*.jsonl` | 本轮采集中间产物 |

## 去重与增量

- `write` 按规范化 URL 与云端表**差减去重**。
- 首跑建表后把 `database_id` 存进 `out/refresh/state.json`，后续自动复用同一张表做跨天增量。
- 也可在 yaml 显式填 `refresh.database_id`。

## 写库目标节点

refresh 把 `--config`（即 subscriptions.yaml）透传给 `write` 子进程，由其中的
`library.node_id` / `library.node_title` 解析智库节点。默认两者都是空串 → **解析失败**。

⚠ 真机验证发现 `--node-title` 可能模糊首匹配写错节点，建议**显式填 `library.node_id`**（精确目标，零歧义）。

## 重试与告警

- **重试**：单源 `EXIT_ERROR` / `ENV` / `PARTIAL` 按 `max_retries` + 指数退避重试；`PARAM` / `COMPLIANCE` 不重试。
- **告警**：`refresh.alert.on` 命中（`error` / `partial` / `zero_yield` / `source_failed`）时写 `alerts.log`；
  填了 `webhook_url` 再 POST 一份 JSON 摘要。
