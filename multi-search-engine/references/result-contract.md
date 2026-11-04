# 检索结果结构化契约（`mse.result/1`）

> 目的：把「一次多引擎检索」的产出固化为**机器可校验**的结构，
> 使「某条结果**只有单个引擎**命中」这类判断可以**机械判定**，而不是靠人眼扫一遍报告。
> 校验器：`scripts/validate_results.py`

---

## 1. 为什么需要契约

当前技能的产出是**自然语言报告**。这带来三个无法机械处理的问题：

| 问题 | 后果 |
|---|---|
| 结果条目非结构化 | 无法自动统计「有几个引擎命中同一信息」 |
| 引擎可用性无记录 | 无法回答「百度最近是不是一直失败」 |
| 失败与空结果混同 | 「引擎挂了」与「确实没有结果」都表现为"没内容" |

契约把三者都变成**可校验字段**。

---

## 2. 顶层结构

一次检索 = 一个 batch 对象：

```json
{
  "schema": "mse.result/1",
  "query": "宠物食品 烘焙粮 适口性",
  "language": "zh",
  "results": [
    {
      "engine": "Baidu",
      "rank": 1,
      "title": "烘焙粮适口性研究进展",
      "url": "https://example.com/a",
      "snippet": "……",
      "status": "ok",
      "fetched_at": "2026-10-12T22:40:00+08:00"
    }
  ]
}
```

| 字段 | 必填 | 类型 | 说明 |
|---|---|---|---|
| `schema` | ✅ | string | 固定 `mse.result/1`（版本化，便于后续演进） |
| `query` | ✅ | string | 本次检索词（**同一 batch 内所有结果共用**） |
| `language` | ⬜ | string | `zh` / `en` / `other`；决定用国内还是国际引擎 |
| `results` | ✅ | array | 结果条目数组，**可为空数组**（表示全部引擎都无结果） |

---

## 3. 结果条目

| 字段 | 必填 | 类型 | 约束 |
|---|---|---|---|
| `engine` | ✅ | string | 必须 ∈ `config.json` 的引擎名（**大小写不敏感**，`bing cn` 等同 `Bing CN`） |
| `status` | ✅ | string | ∈ `ok` / `empty` / `blocked` / `error` |
| `fetched_at` | ✅ | string | **ISO 8601**，须含时区（如 `2026-10-12T22:40:00+08:00`） |
| `title` | 条件 | string | `status=ok` 时**必须非空** |
| `url` | 条件 | string | `status=ok` 时**必须非空**且为 `http(s)://` |
| `rank` | ⬜ | int | ≥ 1；同一 `engine` 内不得重复 |
| `snippet` | ⬜ | string | 摘要，允许为空 |

### 3.1 `status` 四态（关键：区分「失败」与「没有」）

| 值 | 含义 | 典型场景 |
|---|---|---|
| `ok` | 正常返回且**有**结果 | — |
| `empty` | 请求成功，但**该引擎确实没有**匹配结果 | 冷门查询 |
| `blocked` | 被拦截：403 / 429 / 验证码 | 360 通道验证码拦截 |
| `error` | 网络或解析异常 | 超时、DNS 失败、HTML 结构变更 |

> **为什么必须分开**：把 `blocked` 与 `empty` 合并，会让「引擎坏掉」伪装成「没有结果」，
> 直接污染后续的引擎健康度统计（M6）。**降级必须有声音。**

---

## 4. 校验规则（违规编号即校验器的 check id）

| ID | 规则 |
|---|---|
| **V1** | 顶层必须含已知 `schema` |
| **V2** | 顶层 `query` 必须为非空字符串 |
| **V3** | 顶层 `results` 必须为数组 |
| **V4** | 每条结果 `engine` 必须 ∈ `config.json` |
| **V5** | 每条结果 `status` 必须 ∈ 四态枚举 |
| **V6** | 每条结果 `fetched_at` 必须可解析且含时区 |
| **V7** | `status=ok` 时 `title` 与 `url` 必须非空 |
| **V8** | `url` 必须为 `http(s)://` 且含主机名 |
| **V9** | `rank` 若存在必须为 ≥1 的整数 |
| **V10** | 同一 `engine` 内 `rank` 不得重复 |
| **V11** | `language` 若存在必须 ∈ `zh` / `en` / `other` |

### 4.1 退出码（三态，禁止把「没能验证」冒充「已损坏」）

| 码 | 含义 |
|---|---|
| `0` | 通过 |
| `1` | 存在违规（**被测数据确有缺陷**） |
| `3` | **无法验证**：缺 `config.json`、输入文件不存在或非 JSON |

> 工具/环境缺失**永远不得**产出 `1`——那会把「没得验」谎报成「验出问题」。

---

## 5. 用法

```bash
# 校验一批结果
python scripts/validate_results.py results.json

# 机器可读输出（供上游脚本消费）
python scripts/validate_results.py results.json --json

# 自检（内含应当失败的反向用例）
python scripts/validate_results.py --selftest

# 统计各引擎命中数（M5 交叉核验器的输入）
python scripts/validate_results.py results.json --summary
```

---

## 6. 最小合法示例

```json
{
  "schema": "mse.result/1",
  "query": "python 教程",
  "language": "zh",
  "results": [
    {"engine": "Baidu",  "status": "ok",    "title": "Python 官方教程", "url": "https://www.python.org/", "rank": 1, "fetched_at": "2026-10-12T22:40:00+08:00"},
    {"engine": "Sogou",  "status": "empty", "fetched_at": "2026-10-12T22:40:03+08:00"},
    {"engine": "360",    "status": "blocked", "fetched_at": "2026-10-12T22:40:06+08:00"}
  ]
}
```
