# 上下文工程：平台记忆选择机制与本技能的角色

> 本文件记录 V3.10 的设计前提与实测证据。**结论会随平台版本变化，使用前建议用
> `selector-audit` 重新实测本机现状**（本项目遵循 verify-before-claim：不沿用旧结论）。

---

## 一、平台侧事实（2026-09 三级核实）

| 级别 | 来源 | 关键内容 |
|:--|:--|:--|
| A · 官方文档 | 设置配置页（记忆功能配置） | `memory.relevanceSelection`（默认 `true`）：「启用后根据用户查询自动选择**最多 5 个**相关记忆注入上下文」。同页还有 `autoMemoryEnabled` / `typedMemory` / `memoryExtraction` / `teamMemory` |
| B · 架构资料 | 平台内建 Agent 说明 | 内建 `memorySelector` Agent：**lite 模型、0 工具**；每次查询接收「用户 query + 可用记忆文件列表（**文件名 + 描述**）」→ 返回最多 5 个相关记忆文件名 → 只有被选中的才注入主 Agent 上下文 |
| C · 本机日志 | 运行日志中的 Agent 注册记录 | `agent=memorySelector ... resolved_models=["lite"]`、`tools=[]`，描述为 "Select relevant memories for the current query." —— 与 A/B 一致 |

**推论（关键）**：记忆注入链路是平台内部的，且**没有对外暴露的过滤/替换钩子**（平台 Hooks 仅覆盖
生命周期事件，如 Stop / SessionEnd / PreCompact / SubagentStop）。因此：

- ❌ 技能**不能**做「注入拦截器」——无法决定最终注入哪几条；
- ✅ 技能**能**做「**候选池质量放大器**」——决定平台选择器**看到什么、有多少候选**。

---

## 二、本技能的两个真实杠杆

### L1 可见性：让每条记忆「读得到」

选择器只读「文件名 + 描述」。若记忆文件既无 front-matter `description`，文件名又是纯日期
（如 `2026-05-16.md`），选择器只能靠文件名猜——**再相关也可能选不中**。

- `selector-audit` 逐文件给出**描述就绪度 0-100**（front-matter 描述 40 / 语义文件名 20 /
  新鲜度 30 / 描述长度 10）与 `description_source`（front_matter / heading / none）。
- `describe --execute` 为缺描述的记忆自动提炼一句描述写入 front-matter（幂等、只补不删、
  原子写、保留原有字段）。

### L2 槽位压力：候选越少越准

选择器每次只注入 **5 条**。候选数远超 5（例如每天一个日志文件、一年 300+）时，陈旧项会挤占槽位、
稀释选择质量，也让「记忆越多越懂你」的反面出现。

- `selector-audit` 计算 `slot_pressure = 候选数 / 5` 并分级（ok ≤1 / elevated ≤2 / severe >2）。
- `archive`（归档，可恢复）/ 人工合并日志 → 压缩候选池。
- 陈旧分级：`fresh`（≤7 天）/ `aging`（≤阈值）/ `stale`（>阈值，默认 30 天）。

### L3 时效：让旧内容自然降权

`load --query` 的相关性排序分乘以**时效衰减因子**（半衰期 90 天，下限 0.35），避免几个月前的旧
结论压过新结论。

---

## 三、推荐工作流

```bash
# 1) 体检：看描述就绪度 / 槽位压力 / 陈旧量（只读）
memory_manager.py selector-audit <workspace>

# 2) 提升可见性：先预览，再写入
memory_manager.py describe <workspace>
memory_manager.py describe --execute <workspace>

# 3) 压缩候选池：归档陈旧记忆（先看 selector-audit 的 stale 列表）
memory_manager.py archive <workspace> --days 30

# 4) 按需取最相关的 K 条（时效加权）
memory_manager.py load --query "发布流程" --top-k 3 <workspace>
```

> `describe` 只补 front-matter 描述，属可恢复写入（`backup` 兜底）；`archive` 为归档
> （`.md.gz`，可恢复）。二者默认都不「动刀」，破坏性动作需显式 `--execute`。

---

## 四、诚实边界（必须对用户讲清）

1. **本技能不参与选择**：最终注入哪 5 条由平台的 `memorySelector` 决定。技能只改善它看到的候选池。
2. **描述是启发式提炼**：`describe` 从标题 + 首几条要点提炼，不是语义理解；可能不够精准，
   建议人工过一眼（尤其 MEMORY.md 这类长期笔记）。
3. **陈旧阈值是本地判定**：`stale_days` 默认 30 天，与业务无关；请按自身节奏调整
   （如项目周期长可设 90）。
4. **平台差异**：不同版本/发行版的选择器实现可能不同（如 5 条上限、是否读 front-matter
   `description`）。如平台行为变化，请以 `selector-audit` 的实测结果为准，并更新本文件的证据表。
