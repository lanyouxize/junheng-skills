# 治理闭环设计说明（V4.0.1）

> 本文件回答一个问题：**为什么 V3.10 之后还要做治理闭环（govern / snapshot / compact / dashboard / health）？**
> 以及每个命令的判定口径、安全边界与已知局限。

---

## 1. 问题：记忆会被「写坏」，而不是只会被「写老」

V3.10 解决的是**可见性**（平台 `memorySelector` 只看「文件名 + 描述」）。
但实践里还有一类问题，可见性手段无解——**文件内容本身在退化**：

| 退化形态 | 表现 | 对 Token 的影响 |
|:--|:--|:--|
| 重复行堆积 | 同一条结论被反复追加 | 直接线性放大体积 |
| 空行洪水 | 连续空行 / 无意义换行 | 白占 token |
| 分隔线堆砌 | `---` / `===` 反复出现 | 视觉噪声 + token |
| 单文件膨胀 | 一个 md 从 2 KB 长到 200 KB | 命中即爆预算 |
| 陈旧沉淀 | 90 天前的决策仍占 top 位 | 挤掉真正相关的记忆 |

这些不是「排序」能解决的——它们需要**写入侧治理**（govern）+ **体积侧压实**（compact）。

---

## 2. 设计原则

1. **可回滚优先**：任何落盘动作（govern / compact）**先建快照**再写，出事 `snapshot --restore` 一键还原。
2. **只折叠不删除**：`govern --execute` 只做幂等折叠（压重复行 / 空行 / 分隔线），**不丢语义内容**。
3. **预览优先**：govern / compact 默认 dry-run，必须显式 `--execute`。
4. **零依赖**：不引入第三方库；CJK 用字符 bigram，时效用 90 天半衰期。
5. **不越界**：治理只作用于 `.workbuddy/memory/`，不碰任何其他目录。

---

## 3. 五个命令的判定口径

### `govern`（写入治理审计）

| 维度 | 判定 |
|:--|:--|
| 重复行 | 归一化（去空白）后在同一文件内出现 ≥2 次 |
| 空行洪水 | 连续空行 > 2 折叠为 1 |
| 分隔线堆砌 | 连续分隔符行折叠为 1 |
| 超大文件 | 单文件 token 超过全库均值 × 3（且 > 1000 token） |
| 陈旧 | mtime 超过 `--stale-days`（默认 30） |

输出：`totals`（files / tokens / removable_tokens / cross_dup_lines / oversize / stale）+ `score`（0-100，越高越健康）。
`--execute` 只应用**幂等折叠**，落盘前自动建快照。

### `snapshot`（快照与回滚）

- 存储：`.workbuddy/memory_snapshots/<时间戳>_<label>/`
- 保留：**最多 5 个**，超出自动淘汰最旧
- 回滚：`--restore --execute`，**只覆盖同名文件**，绝不因回滚删除文件
- 幂等：重复建同 label 快照不冲突（时间戳区分）

### `compact`（自适应压实）

排序依据：**体积 × 陈旧度**（复用 V3.10 的 `recency_factor`，90 天半衰期、下限 0.35）。
逐步挑候选压到预算内：

```
excess = total_tokens - budget
while excess > 0 and candidates:
    pick  argmax(tokens x staleness_weight)
    fold -> after_tokens
    excess -= (before - after)
```

默认预览；`--execute` 落盘前自动建快照。

### `dashboard`（省 Token 看板）

一屏四块：总量 / 预算占用率 / 可省空间 / 下一步建议（取 `health` 优先级最高的 3 条）。

### `health`（一键体检，五维 0-100）

| 维度 | 来源 | 满分含义 |
|:--|:--|:--|
| visibility 可见性 | `selector-audit` 平均就绪度 | 所有记忆都有清晰描述 |
| freshness 新鲜度 | 陈旧文件占比 | 无陈旧记忆 |
| duplication 去重度 | govern 可折叠 token 占比 | 无冗余 |
| size 体积 | 超大文件占比 | 无单文件膨胀 |
| budget 预算 | `token_check` 占用率 | 远低于预算 |

等级：A(≥90) / B(≥75) / C(≥60) / D(≥40) / E(<40)，并输出**优先修复清单**（按维度缺口排序）。

---

## 4. 与既有命令的边界（不重叠原则）

| 命令 | 职责 | 不做什么 |
|:--|:--|:--|
| `govern` | 写入卫生审计 + 幂等折叠 | 不删文件、不改语义 |
| `compact` | 按预算压实体积 | 不做去重判定 |
| `dedup` | 跨文件重复记忆识别 | 不折叠行内冗余 |
| `clean` / `archive` | 归档移出 | 不折叠、不压实 |
| `throttle` | 装载前压预算（一次性输出） | 不改磁盘 |
| `selector-audit` | 可见性审计 | 不管体积 |
| `health` / `dashboard` | 汇总与排序 | 只读，不改任何文件 |

---

## 5. 已知局限（诚实边界）

- **启发式不是语义**：重复行 / 空行 / 分隔线判定是规则式；语义级重复（换句话再说一遍）识别不了。
- **压实会丢细节**：`compact --execute` 压缩后原文细节不可恢复——这正是强制建快照的原因。
- **陈旧 ≠ 无用**：30 天未改不代表过时（长期项目基线可能半年不动）。`--stale-days` 可按需调大。
- **Token 是估算**：优先 tiktoken 真实分词，缺失时回退 CJK 启发式，非实际 API 消耗。

---

## 6. 推荐工作流

```bash
# 1) 先看全局，不做任何改动
memory_manager.py health .
memory_manager.py dashboard .

# 2) 按 health 给的优先修复清单逐项处理
memory_manager.py selector-audit .          # 可见性差 → describe
memory_manager.py describe --execute .
memory_manager.py govern .                  # 去重度差 → 折叠
memory_manager.py govern --execute .
memory_manager.py compact --budget 2000 .   # 超预算 → 压实
memory_manager.py compact --budget 2000 --execute .

# 3) 出问题随时回滚
memory_manager.py snapshot --list .
memory_manager.py snapshot --restore --execute .
```
