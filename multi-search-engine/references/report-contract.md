# 检索交叉核验报告契约（`mse.report/1`）

> 目的：把「一次多引擎检索」的产出（`mse.result/1`）升级为**可机械判定的核验报告**，
> 使「某条结果只有单个引擎命中」不再依赖人眼扫一遍自然语言报告。
> 生成器：`scripts/search_report.py`（输入契约见 `result-contract.md`）

---

## 1. 为什么需要这一层

`mse.result/1` 只回答「**各引擎各自返回了什么**」。
它还回答不了三个配方研发场景里的高频问题：

| 问题 | 为什么 `mse.result/1` 答不了 |
|---|---|
| 这条结论**只有一家搜索引擎**说过吗？ | 需要跨引擎比对同一信息，单看一份结果看不出 |
| 是「这条存疑」还是「**根本没得交叉**」？ | 需要知道有几个引擎真的成功返回了 |
| 哪个引擎今天又挂了？ | 需要把 blocked / error / empty 分开计数 |

本契约把三者都变成字段。

---

## 2. 三态判定（核心，禁止合并）

对每个「信息簇」（同一结论被多个引擎命中的聚类）给出判定：

| 判定 | 条件 | 含义 | 行动 |
|---|---|---|---|
| `cross-verified` | 簇内**不同引擎数** ≥ `min_engines` | 已交叉印证 | 可直接引用 |
| `single-engine` | 簇内引擎数 < `min_engines`，**且** `engines_with_ok` ≥ `min_engines` | **待核** | 须再找独立信源 |
| `insufficient-engines` | `engines_with_ok` < `min_engines` | 无从交叉，**无法核验** | 换引擎/换时段重试，**不得**记为待核 |

> **为什么第三态必须独立**：把「只有 1 个引擎成功返回」也归成「待核」，
> 会让「引擎全挂」伪装成「这条结论存疑」—— 判断方向完全相反，
> 且会污染后续的引擎健康度统计（M6）。**降级必须有声音。**

### 2.1 判定基数

`verdict_basis` 字段显式记录本次判定所依据的基数，例如：

```
engines_with_ok=4 vs min_engines=2
```

`engines_with_ok` 只数 `status=ok` 的引擎（`blocked` / `error` / `empty` 都不算），
因为只有它们**真的给出了可比对的内容**。

---

## 3. 信息簇的聚类规则

| 维度 | 规则 | 说明 |
|---|---|---|
| URL（主） | 归一化后相同即同簇 | 小写 scheme/host、去 `www.`、去默认端口、去 fragment、去跟踪参数（utm_*/fbclid/gclid/spm…）、query 排序、去尾斜杠 |
| 标题（辅） | 归一化后相似度 ≥ `title_threshold`（默认 0.90）即同簇 | 覆盖「百度给跳转链接、必应给原站」这类 URL 形式不同的同一篇 |

`matched_by` 字段记录该簇是靠哪个维度合并的（`url` / `title`），
便于人工判断合并是否可信。

**已知局限（诚实披露）**：
- 标题相似度是**字符级**比对（`difflib`），不理解语义；两篇标题相近但内容不同的文章可能被合并。
  缓解：阈值默认 0.90 且可调；报告始终显示 `matched_by` 与全部标题。
- 跟踪参数黑名单是**显式列举**，未覆盖的新参数不会被剥离（保守方向：宁可多算一个簇，不误并）。
- 簇数超过 500 时跳过标题维度合并，并在 `notes` 出声（结论偏保守）。

---

## 4. 顶层结构

```json
{
  "schema": "mse.report/1",
  "query": "宠物食品 烘焙粮 适口性 研究",
  "language": "zh",
  "generated_at": "2026-10-13T08:20:26+08:00",
  "sources": ["results.json"],
  "params": {"min_engines": 2, "title_threshold": 0.9},
  "cross_check": {
    "engines_reporting": 6,
    "engines_with_ok": 4,
    "engines_with_ok_names": ["Baidu", "Bing CN", "Bing INT", "Sogou"],
    "per_engine": {"Baidu": {"ok": 2}, "360": {"blocked": 1}},
    "min_engines": 2,
    "verdict_basis": "engines_with_ok=4 vs min_engines=2",
    "clusters": [
      {
        "verdict": "cross-verified",
        "engine_count": 2,
        "engines": ["Baidu", "Bing CN"],
        "matched_by": "title",
        "urls": ["https://www.baidu.com/link?url=aBcD123", "https://www.petnutrition.cn/paper/123"],
        "titles": ["烘焙粮适口性研究进展_宠物营养学报"],
        "entries": [ { "...": "mse.result/1 原始条目" } ]
      }
    ],
    "counts": {"cross-verified": 1, "single-engine": 3, "insufficient-engines": 0},
    "pending_review": [ { "...": "single-engine 簇，F-1 的核心产出" } ],
    "notes": []
  }
}
```

| 字段 | 说明 |
|---|---|
| `pending_review` | `verdict=single-engine` 的簇子集 —— 即「仅单引擎命中」的**待核清单** |
| `counts` | 三态计数；三者之和 = `clusters` 长度 |
| `notes` | 降级与提示（如跳过标题合并）；**空数组表示无降级** |

---

## 5. 用法

```bash
# 生成核验报告（人读 Markdown）
python scripts/search_report.py results.json

# 多批次合并核验（同一 query 分文件保存时）
python scripts/search_report.py baidu.json bing.json sogou.json

# 机器可读
python scripts/search_report.py results.json --json

# 落盘报告
python scripts/search_report.py results.json --md -o report.md

# 调整判定严格度
python scripts/search_report.py results.json --min-engines 3 --title-threshold 0.95

# 自检（内含应当失败的反向用例）
python scripts/search_report.py --selftest
```

---

## 6. 退出码（三态，与 `mse.result/1` 校验器一致）

| 码 | 含义 |
|---|---|
| `0` | 核验完成（**含** `insufficient-engines` 这类域内负结果） |
| `1` | 输入有缺陷：契约违规（V1–V11）、多批次 `query` / `language` 不一致 |
| `3` | **无法验证**：缺 `config.json`、输入文件不存在或非 JSON、参数非法 |

> 工具/环境缺失**永远不得**产出 `1`——那会把「没得验」谎报成「验出问题」。

---

## 7. 诚实边界

- 本契约目前是**约定**：`multi-search-engine` 是给 Agent 的指导书，不是可执行程序，
  不会自动产出 `mse.result/1`，因此也不会自动产出本报告。
  落地方式是「按文档产出 + 用 `search_report.py` 验收」。
- `search_report.py` **不联网**，它只消费已经抓好的 `mse.result/1` 批次；
  抓取由 Agent 按 `SKILL.md` 工作流完成（或用 `fetch_clean.py` 抓正文）。
- `min_engines` 的默认值 2 是**约定而非标准**：对高 stakes 结论（如配方法规引用），
  应在命令行显式提高，并在报告里留痕。
