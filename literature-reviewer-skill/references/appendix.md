# 附录 · 数据库/输出/依赖/边界/示例

> 本文件由 SKILL.md 的附录段落【逐字】外置，一字未改。

## 数据库访问指南

### CNKI

**访问地址**：`https://kns.cnki.net/kns8/AdvSearch`

**字段代码**：
| 代码 | 含义 |
|------|------|
| SU | 主题 |
| TI | 篇名 |
| KY | 关键词 |
| TKA | 篇关摘 |

**来源筛选**：CSSCI、北大核心、CSCD

### Web of Science

**访问地址**：`https://www.webofscience.com/wos/woscc/advanced-search`

**常用字段**：
- TS=Topic
- TI=Title
- AB=Abstract
- SO=Source

### ScienceDirect

**访问地址**：`https://www.sciencedirect.com/search`

---

## 输出文件说明

| 文件 | 内容 | 用途 |
|------|------|------|
| `references.md` | 完整文献清单（含摘要） | 文献查阅 |
| `papers_analysis.md` | 单篇文献深度分析 | 理解每篇文献 |
| `literature_review.md` | 结构化综述（含摘要、关键词） | 直接使用 |
| `gb7714_citations.txt` | GB/T格式引文列表 | 复制到论文 |

---

## 依赖 Skills

- **docx** - 生成Word格式综述（可选）
- **web_search** - 辅助获取文献信息
- **browser** - 数据库检索自动化

---

## 与 autoresearch 的分工边界（避免重复检索）

> 2026-10-20 新增。本节是**追加**，不改变 Phase 0–8 的任何既有行为，
> 也不新增任何外部依赖 —— 它与 autoresearch 之间**双向零调用**（已全目录核验）。

两套技能都覆盖「文献检索」这一段，但**目的、通道、停止条件都不同**，实际是各跑各的：

| 维度 | literature-reviewer-skill（本技能） | autoresearch（Orchestra Research 出品） |
|---|---|---|
| 产物 | 穷尽式清单 + GB/T 7714 引文 + 综述 | 假设 + 实验闭环 + 会议/期刊论文 |
| 文献阶段定位 | **全部工作**（Phase 0–8） | 仅 Bootstrap 的一环，**够用即止**（原文：`the goal is to start experimenting, not to produce an exhaustive survey`） |
| 检索通道 | 浏览器自动化：CNKI / Web of Science / ScienceDirect / PubMed | Exa MCP、Semantic Scholar、arXiv、CrossRef |
| 学科取向 | 通用学术（本项目用于宠物营养 / 兽医泌尿） | ML / AI / Systems（NeurIPS、ICML、OSDI、SOSP） |
| 文献落地 | 回写**跨项目文献总线**（唯一写方 `export-bus.cjs`） | 项目内 `literature/`（一文献一文件 + `literature/survey.md`） |
| 停止条件 | 覆盖充分 | 能开始做实验即止 |

**路由判定**

| 用户意图 | 用谁 |
|---|---|
| "帮我做一份 XX 的文献综述 / 清单" | **本技能** |
| "我要围绕 XX 跑实验、出论文" | **autoresearch**（其 Bootstrap 会自行扫文献） |
| 两者都要 | 先本技能产出 `references.md`；再让 autoresearch 的 Bootstrap **直接读它**，不要重搜 |

**两条易错的交接点**

1. **从 autoresearch 切到本技能时，总线大概率查不到。** autoresearch 的文献存在项目内
   `literature/`，**不进文献总线**（总线唯一写方是 `export-bus.cjs`）。所以 Phase 0.5
   用 `query-bus.cjs` 查不到时，**不能据此断定"这个主题没人检索过"** —— 先去看项目里
   有没有 `research-state.yaml` 与 `literature/`，有就说明 autoresearch 在主导，直接复用它的线索。
2. **从本技能切到 autoresearch 时，要显式告知产物位置。** autoresearch 的 Bootstrap 默认走
   Exa/S2/arXiv/CrossRef，它**不会**自动发现本技能的 `output/references.md`；
   交接时要点名该文件，否则同一主题被检索两遍。

---

## 使用示例

**用户**：帮我做一个关于"深度学习在肺癌早期诊断中的应用"的文献回顾

**执行流程**：
1. AI生成中英文关键词和检索策略
2. 并行检索 CNKI、WOS、ScienceDirect、PubMed
3. 整理去重，保留中英文各20篇
4. 导出 `references.md`
5. **单篇文献深度分析** → `papers_analysis.md`
6. 生成综述大纲 → 撰写 → 审查 → 润色 → `literature_review.md`
7. 输出 GB/T 7714-2015 格式引文

---

