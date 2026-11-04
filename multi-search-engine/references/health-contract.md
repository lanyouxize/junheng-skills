# 引擎健康度契约（`mse.health/1` 台账 + `mse.health.summary/1` 榜单）

> 目的：把「今天哪个引擎挂了」从记忆变成数据（路线图 O-5）。
> 脚本：`scripts/engine_health.py`；上游输入：`mse.result/1` 批次（见 `result-contract.md`）。

---

## 1. 为什么需要台账

`mse.result/1` 只描述**一次**检索。跨时间累积后才回答得了：

| 问题 | 没有台账时 |
|---|---|
| 百度最近是不是一直失败？ | 靠回忆，且回忆会把「今天被拦一次」放大成「一直挂」 |
| 360 是挂了还是真的没结果？ | `blocked` 与 `empty` 在自然语言报告里都写作"没内容" |
| 该给哪个引擎更高优先级？ | 无依据 |

台账把每次检索的每引擎结局落成一行，榜单按可用率排序。

---

## 2. 台账记录（`mse.health/1`，JSONL 一行一条）

```json
{
  "schema": "mse.health/1",
  "batch_id": "2bde46ab3be0370d…",
  "recorded_at": "2026-10-13T00:51:16+00:00",
  "query": "宠物食品 烘焙粮 适口性 研究",
  "engine": "360",
  "status": "blocked",
  "result_count": 0,
  "fetched_at": "2026-10-01T09:00:00+08:00",
  "note": null
}
```

| 字段 | 说明 |
|---|---|
| `batch_id` | 批次内容身份证 = 规范化 JSON 的 sha256。**认内容不认文件名**：同一批次重复登记被跳过；重新检索（内容有变）算新的一次 |
| `recorded_at` | 登记时刻（UTC） |
| `engine` | 规范名（以 `config.json` 为真源，大小写不敏感） |
| `status` | 四态之一，语义与结果契约**完全一致** |
| `result_count` | 该引擎本次返回的 ok 条目数（产量指标） |
| `fetched_at` | 该引擎本次的**最晚**一条结果时间；窗口与清理都以它判龄 |
| `note` | 混合状态留痕，如 `mixed:blocked,error`；无则 `null` |

### 2.1 `status` 四态与「可用」的定义

| status | 含义 | 计入可用？ |
|---|---|---|
| `ok` | 正常返回且有结果 | ✅ |
| `empty` | 请求成功，该引擎确实无结果 | ✅（引擎是好的，只是没命中） |
| `blocked` | 403 / 429 / 验证码 | ❌ |
| `error` | 网络或解析异常 | ❌ |

> 把 `blocked` 并入 `empty`，等于让「引擎坏掉」伪装成「没有结果」——这是本契约存在的主要理由之一。

### 2.2 同引擎多条目时的归并（显式规则）

- 有 ok 条目 → `status=ok`，`result_count=ok 条目数`；同时存在非 ok 条目 → `note=mixed:<状态列表>`。
- 无 ok 条目 → 取**最严重**状态（`error` > `blocked` > `empty`）；多种并存 → 同样留 `note`。

---

## 3. 去重与提交（两条硬规则）

1. **去重键 = `(batch_id, engine)`**，作用域是**整个台账**（不是某个分桶）。
   批次内每引擎一条记录，故只按 `batch_id` 去重会把同批次的第二条引擎记录误判为重复。
2. **提交顺序**：写同目录临时文件 → 回读校验（新记录在册 **且** 原有记录不丢）→ 才 `os.replace`。
   任一步不过 → 删临时文件，原台账**字节不变**。

台账任一行损坏（非 JSON / 缺字段 / schema 不符 / status 非法）都是**缺陷**（exit 1），
定位到行号，绝不静默跳过。

---

## 4. 榜单（`mse.health.summary/1`）

```json
{
  "schema": "mse.health.summary/1",
  "status": "ok",
  "window_days": 30,
  "min_attempts": 3,
  "record_count": 15,
  "excluded_by_window": 0,
  "counts": {"ok": 9, "empty": 2, "blocked": 3, "error": 1},
  "verdicts": {"healthy": 1, "degraded": 0, "unavailable": 1, "insufficient-data": 6},
  "engines": [
    {"engine": "Baidu", "attempts": 3, "ok": 3, "empty": 0, "blocked": 0, "error": 0,
     "usable_rate": 1.0, "block_rate": 0.0, "ok_rate": 1.0, "avg_results": 5.0,
     "verdict": "healthy", "verdict_basis": "attempts=3,min_attempts=3"}
  ],
  "notes": []
}
```

### 4.1 引擎判定四态（不可合并）

| 判定 | 条件 | 读法 |
|---|---|---|
| `insufficient-data` | `attempts < min_attempts`（默认 3） | **无法判定**——不是「不健康」 |
| `unavailable` | 可用率 = 0 | 窗口内一次都没用成 |
| `degraded` | `0 < 可用率 < 0.8` | 时好时坏，需人工看一眼 |
| `healthy` | 可用率 ≥ 0.8 | 可放心用 |

> **第三态是刻意的**：「样本不足」与「确认不健康」结论方向相反。合并会让一个只被检索过
> 两次的引擎显示成「不可用」，直接误导选型。判定时序即语义：先问样本够不够。

排序：可用率降序 → 样本数降序 → 引擎名（输出稳定）。

### 4.2 窗口与判龄

- `--window N`（默认 30，`0` = 全部历史）按 `fetched_at` 过滤；被排除的条数进 `excluded_by_window` 与 `notes`（降级必须有声音）。
- `fetched_at` 无法解析的记录**按窗口内保留**并出 note——不冤杀。
- 榜单 `status=empty`（窗口内无记录）是**域内负结果**：退出码仍为 0，不等于「引擎全挂」。

---

## 5. 退出码（三态）

| 码 | 含义 |
|---|---|
| `0` | 通过（含域内负结果：无台账 / 窗口内无记录 / 无需新增 / 无需清理） |
| `1` | 确有缺陷（输入违反 V1–V11、台账损坏、回读校验失败） |
| `3` | 无法验证（缺 `config.json`、输入不存在或非 JSON、参数非法） |

工具/环境缺失**永远不得**产出 `1`。

---

## 6. 用法

```bash
# 登记一批结果并出榜（默认台账：技能包内 engine-health.jsonl）
python scripts/engine_health.py results.json [more.json ...]

# 只预演不落账
python scripts/engine_health.py results.json --no-append

# 只出榜（读台账）
python scripts/engine_health.py --summary [--window 7] [--json]

# 清理：默认 dry-run，--yes 才落盘；无法判龄的一律保留
python scripts/engine_health.py --prune-older-than 90 [--yes]

# 自检（55 项，含证伪用例）
python scripts/engine_health.py --selftest
```

与 M5 的**有意差异**：台账本就跨 query 累积，故接受多批次 `query` 不一致
（M5 交叉核验的是同一 query，必须一致）。

---

## 7. 已知局限（诚实清单）

| 局限 | 影响 | 处置 |
|---|---|---|
| 台账内**既有**重复行不会被自动合并 | 历史脏数据会一直参与统计 | 避免静默改历史；如出现应以人工核对后重写台账 |
| 无趋势对比（本期 vs 上期） | 「正在恶化」要人自己比两次榜单 | 留待后续迭代，需要时再加 `--trend` |
| 判龄依赖上游提供的 `fetched_at` | 上游时钟错会让窗口算错 | 上游契约已要求 ISO 8601 含时区；本脚本对无时区值按 UTC 兜底 |
| `recorded_at` 与 `fetched_at` 可能差很久（补登记旧批次） | 补登记按 `fetched_at` 入窗，符合「这次检索发生在何时」的语义 | 有意为之，文档明示 |
