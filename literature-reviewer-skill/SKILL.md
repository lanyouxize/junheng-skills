---
name: literature-reviewer-skill
description: 系统性中英文文献回顾：8 阶段工作流，经浏览器自动化检索 CNKI、Web of Science、ScienceDirect 等库，产出含 GB/T 7714-2015 引文的 Markdown 综述。当用户要检索文献、写综述、找证据时用。
license: MIT
compatibility: Python 3.9+.
---

# 文献回顾（Literature Survey）

根据用户提供的论文主题，进行系统性的中英文文献检索、整理和综述撰写。
采用 **8阶段工作流**，无需API配置，通过浏览器自动化获取文献。

---

## 8阶段工作流

```
Phase 0: Session Log      → 创建会话目录
Phase 1: Query Analysis   → 生成中英文检索策略  
Phase 2: Parallel Search  → 浏览器自动化检索
Phase 3: Deduplication    → 标题相似度去重
Phase 4: Verification     → 基础元数据校验
Phase 5: Data Export      → 导出文献信息
Phase 6: Paper Analysis   → 单篇文献深度分析
Phase 7: Citation Format  → GB/T 7714-2015格式化
Phase 8: Synthesis        → 生成综述文档
```

---

## Phase 0: Session Log（会话管理）

创建会话目录，记录工作进度。

**目录结构**：
```
sessions/{YYYYMMDD}_{topic_short}/
├── session_log.md          # 工作日志
├── metadata.json           # 会话元数据
├── papers_raw.json         # 原始检索结果
├── papers_deduplicated.json # 去重后文献
├── papers_analysis.json    # 文献分析结果
└── output/
    ├── references.md       # 文献清单（含摘要）
    ├── papers_analysis.md  # 单篇文献分析
    └── literature_review.md # 最终综述
```

---

## Phase 0.5: Check Bus First（先查文献总线，避免重复检索）

> 2026-10-18 新增（批 15）。本节是**追加**，不改变 Phase 0 与 Phase 1–8 的任何既有行为。
> 目的：同一主题不要重复检索；且评审结论能回溯到总线记录。

文献总线是跨项目的文献真源（唯一写方是 `paper-bilingual-search/scripts/export-bus.cjs`）。
**检索前先查总线**，命中就复用，未命中再走 Phase 2 的原流程。

```bash
# 1) 按主题词查（标题/期刊/标签，不区分大小写）
node "C:/Users/Administrator/.workbuddy/skills/literature-reviewer-skill/scripts/query-bus.cjs" --kw "<主题词>"

# 2) 限定年份（可选）
node "C:/Users/Administrator/.workbuddy/skills/literature-reviewer-skill/scripts/query-bus.cjs" --kw "<主题词>" --year-from 2020

# 3) 机读（需要程序处理时）
node "C:/Users/Administrator/.workbuddy/skills/literature-reviewer-skill/scripts/query-bus.cjs" --kw "<主题词>" --json
```

**按退出码分支**（必须显式判断，不得凭印象）：

| 退出码 | 含义 | 下一步 |
|---|---|---|
| `0` | 命中 ≥1 条 | 把命中记录写入 `papers_deduplicated.json`（字段：`id`/`title`/`journal`/`year`/`sourceUrl`），**可跳过 Phase 2 的对应子查询**；仍需做 Phase 4–8 |
| `1` | 未命中 | 按原流程执行 Phase 1–8；新记录在结尾经 `export-bus.cjs` 回写总线（保持单写方） |
| `2` | 环境错误（总线文件缺失） | 不要静默跳过：在 `session_log.md` 记一条「总线不可用：<原因>」，然后按原流程执行 |

**三条硬约束**

1. **只读**：本节只允许调用 `query-bus.cjs`（它不写任何文件）。任何写入仍必须走 `export-bus.cjs`，不得直接改 `records.jsonl`。
2. **不编造**：总线未命中时明确记录「总线无匹配」，不得把总线里无关的记录当作证据引用。
3. **可回溯**：复用总线记录时，必须在 `output/references.md` 里保留总线 `id`（40 位 sha1），否则评审结论无法回到真源。

---

## Phase 1: Query Analysis（查询分析）

AI 智能分析研究主题，生成相关关键词和检索策略。

### AI 提示词模板

```
You are tasked with generating relevant keywords or phrases for a given research direction.

The research direction is provided below:
<research_direction>
{{用户输入的研究主题}}
</research_direction>

To complete this task:

1. Carefully analyze the provided research direction.
2. Identify core concepts, methods, techniques, or topics in this research area.
3. Generate 5 to 8 of the most relevant and representative keywords or phrases.
4. Ensure keywords are concise, typically 1-3 words each.
5. Make sure the keywords cover different aspects of the research direction.
6. Order the keywords by importance or relevance.
7. Separate keywords with English commas (,).
8. Do not include any explanations, descriptions, or additional text.
9. Provide keywords in both Chinese and English.

Present your result in the following format:

中文关键词：keyword1, keyword2, keyword3, ...
英文关键词：english_keyword1, english_keyword2, english_keyword3, ...

Example for "人工智能在医疗诊断中的应用":
中文关键词：人工智能, 医疗诊断, 机器学习, 深度学习, 医学影像, 辅助诊断, 疾病预测, 智能诊疗
英文关键词：artificial intelligence, medical diagnosis, machine learning, deep learning, medical imaging, computer-aided diagnosis, disease prediction, intelligent diagnosis
```

### 输出格式

```yaml
研究主题: "基于深度学习的医学图像诊断研究"

中文关键词:
  - 深度学习
  - 医学图像
  - 诊断
  - 神经网络
  - 计算机辅助诊断
  
英文关键词:
  - deep learning
  - medical imaging
  - diagnosis
  - neural network
  - computer-aided diagnosis

检索策略:
  CNKI: "SU=('深度学习'+'神经网络')*('医学图像'+'影像')*('诊断'+'辅助诊断')"
  WOS: "TS=((deep learning OR neural network) AND (medical imaging) AND (diagnosis))"
```

---

## Phase 2: Parallel Search（并行检索）

**核心数据库**（无需API，浏览器自动化）：

| 数据库 | 优先级 | 检索方式 |
|--------|--------|----------|
| CNKI | 1 | 浏览器访问高级检索页面 |
| Web of Science | 2 | 浏览器访问检索页面 |
| ScienceDirect | 3 | 浏览器访问检索页面 |
| PubMed | 4 | 网页搜索 + 浏览器访问 |
| Google Scholar | 5 | 网页搜索 |

**检索步骤**：
1. 使用 `browser_navigate` 访问各数据库检索页面
2. 填充检索式，执行搜索
3. 提取前50条结果的标题、作者、期刊、年份、DOI、摘要
4. 保存到 `papers_raw.json`

**字段提取**：
```json
{
  "source_db": "cnki",
  "title": "文献标题",
  "authors": ["作者1", "作者2"],
  "journal": "期刊名称",
  "year": 2023,
  "volume": "46",
  "issue": "5",
  "pages": "1023-1035",
  "doi": "10.xxxx",
  "abstract": "摘要内容...",
  "keywords": ["关键词1", "关键词2"],
  "url": "原文链接"
}
```

---

## Phase 3: Deduplication（去重筛选）

**简化去重策略**：

1. **DOI匹配** - 相同DOI视为重复
2. **标题相似度** - Levenshtein距离 > 0.85 视为重复
3. **保留规则** - 保留信息更完整的记录

**筛选条件**：
- 时间：近10年优先
- 来源：优先保留核心期刊/高质量来源
- 数量：中英文各15-25篇，总计30-50篇

---

## Phase 4: Verification（基础验证）

简化验证流程：

1. **元数据完整性检查** - 确保标题、作者、期刊、年份存在
2. **DOI格式校验** - 检查DOI格式有效性
3. **明显错误过滤** - 排除标题为"无"或作者缺失的记录

---

## Phase 5: Data Export（数据导出）

导出文献信息到Markdown文件。

**输出文件**：`output/references.md`

**文件格式**：
```markdown
# 文献清单

## 中文文献

### C1
- **标题**: 基于深度学习的医学图像诊断研究
- **作者**: 张三, 李四, 王五
- **期刊**: 计算机学报
- **年份**: 2023
- **卷期**: 46(5): 1023-1035
- **DOI**: 10.xxxx
- **摘要**: 本文研究了...
- **来源**: CNKI

## 英文文献

### E1
- **Title**: Deep Learning for Medical Image Analysis
- **Authors**: Smith J, Johnson K, Lee M
- **Journal**: Nature Medicine
- **Year**: 2022
- **Volume/Issue**: 28(8): 1500-1510
- **DOI**: 10.1038/s41591-022-01900-0
- **Abstract**: This study presents...
- **Source**: ScienceDirect
```

---

## Phase 6: Paper Analysis（单篇文献分析）

对每篇文献进行深度分析，提取关键信息。

### AI 提示词模板

```
You are an AI assistant tasked with analyzing and interpreting academic articles.

For each article, follow these steps:

1. Identify and summarize the main research question(s) and objective(s) of the article.
2. Describe the theoretical framework or model used in the study.
3. Summarize the research methodology and design employed.
4. Extract and summarize the key findings and conclusions.
5. Highlight any innovative aspects of the study and point out potential limitations.
6. Analyze how this article relates to other research in the field.
7. Identify any controversial points or unresolved issues mentioned in the article.
8. Identify any trends or emerging directions in the research field mentioned.

Present your analysis in the following structured format:

**文章[N]：[Article Title]**
**主要观点和结论**：[Summary of main points and conclusions]
**局限性**：[Discussion of limitations]
**争议点**：[Identified controversies or disputed points]
**研究内容缺陷**：[Areas not covered by the research]
**参考文献格式**：[GB/T 7714-2015 format for this paper]

Use "---" to separate each article analysis.

Ensure that you analyze and provide output for ALL articles. Do not omit any article from your analysis.
```

### 输出格式

```markdown
# 文献深度分析

---

**文章1：基于深度学习的医学图像诊断研究**

**主要观点和结论**：
本文提出了一种基于卷积神经网络的医学图像诊断方法，在肺结节检测任务上取得了95%的准确率。研究表明深度学习方法能够有效辅助医生进行病灶识别。

**局限性**：
1. 数据集规模相对较小，仅有1000例样本
2. 缺乏多中心验证
3. 模型对少见病例的泛化能力有待验证

**争议点**：
- 深度学习模型的"黑盒"特性与医疗可解释性需求的矛盾
- 辅助诊断系统的责任归属问题

**研究内容缺陷**：
- 未涉及模型的临床部署方案
- 缺少与现有商用系统的对比
- 未讨论数据隐私保护机制

**参考文献格式**：
张三, 李四, 王五. 基于深度学习的医学图像诊断研究[J]. 计算机学报, 2023, 46(5): 1023-1035. DOI:10.xxxx.

---
```

---

## Phase 7: Citation Format（引用格式化）

生成GB/T 7714-2015格式引文。

**中文期刊格式**：
```
[C1] 张三, 李四, 王五. 基于深度学习的医学图像诊断研究[J]. 计算机学报, 2023, 46(5): 1023-1035. DOI:10.xxxx.
```

**英文期刊格式**：
```
[E1] Smith J, Johnson K, Lee M. Deep learning for medical image analysis[J]. Nature Medicine, 2022, 28(8): 1500-1510. DOI:10.1038/s41591-022-01900-0.
```

**文献类型标识必须按实际类型著录**（不再一律 `[J]`）。在文献字典中提供 `doc_type`
（`scripts/citation_formatter.py` 的 `DOC_TYPES`）：

| `doc_type` | 标识 | 适用 | 著录形态 |
|---|---|---|---|
| `J` | `[J]` | 期刊论文（含期刊增刊收录的会议摘要） | 刊名, 年, 卷(期): 页 |
| `M` | `[M]` | 专著、书籍章节 | 出版地: 出版者, 年: 页 |
| `C` | `[C]` | 会议录、论文集 | 刊名/会议名, 年, 卷(期): 页 |
| `D` `R` `S` `P` `G` `A` | 同名标识 | 学位论文/报告/标准/专利/汇编/档案 | 出版地: 出版者, 年 |
| `EB` `DB` `CP` `PP` | `[EB/OL]` 等 | 电子公告/数据库/程序/预印本 | 年. [引用日期]. URL |

未给 `doc_type` 时回落 `[J]` 并在 stderr **告警一次**；给了非法值直接抛 `ValueError`。
预印本示例：
```
[E1] Anjali, Amita Tiwari, Devendra Kumar Gupta, et al. Hairballs In Cats: Just A Grooming Problem Or A Hidden Health Warning?[PP/OL]. 2026. [引用日期: 2026-10-18]. DOI:10.5281/zenodo.22902521.
```

去重入口 `scripts/deduplicate_papers.py::deduplicate_papers` 的结果**与输入顺序无关**，
且命中重复时按字段合并（败者 `id` 记入保留条目的 `merged_from`），不再整条丢弃。

---

## Phase 8: Synthesis（综述生成）

综述生成是文献回顾的核心环节，采用**四步迭代法**确保输出高质量学术综述。

---

---

## 渐进式披露导航（必读）

本技能把长模板与参考细则外置到 `references/`，按阶段**按需读取**，不要一次全载。

| 何时 | 读取文件 | 内容 |
|---|---|---|
| Phase 2 检索 CNKI 前 | `references/cnki-guide.md` | CNKI 高级检索详细操作 |
| Phase 2 访问学术数据库时 | `references/database-access.md` | Web of Science / ScienceDirect 等访问指南 |
| Phase 7 生成 GB/T 7714 引文时 | `references/gb-t-7714-2015.md` | 著录规则与 BibTeX 对应关系 |
| **进入 Phase 8 前（必须）** | `references/phase8-synthesis.md` | 8.1–8.4 四步法完整提示词、大纲/初稿/审查/定稿模板、综述示例、输出文件与迭代机制 |
| 需要数据库清单、输出文件说明、依赖技能、与 autoresearch 分工边界、使用示例时 | `references/appendix.md` | 附录与边界说明 |

> 铁律：`references/phase8-synthesis.md` 是 Phase 8 的**唯一执行依据**；未读取不得开始撰写综述。
> 上述 3 个既有文件此前无任何导航指令，本表同时修复了「外置了却读不到」的问题。

## Phase 8 执行骨架（细节见 references/phase8-synthesis.md）

1. **8.1 Outline** — 生成综述大纲，确认结构后再进入写作。
2. **8.2 Writing** — 撰写初稿，逐条挂接引文。
3. **8.3 Review** — 质量审查与评估，按检查表逐项过。
4. **8.4 Final** — 最终润色与定稿，校验 GB/T 7714 格式。
5. 每步完成后按「长任务断点登记」标记分片，产物真实落盘后再继续。

---

## 触发关键词

- "文献回顾"
- "文献综述"
- "帮我找文献"
- "中英文文献搜索"
- "写综述"
- "literature survey"
- "systematic review"

## 长任务断点登记（bg_check）

适用：任务可拆成 >=3 个独立分片，或预计跨多轮、批量处理 >=5 项时。

开始前一次性登记：
1. `python ~/.workbuddy/tools/bg_check.py --template` 取声明模板。
2. 写声明 JSON：`shards[].deliverable` 用绝对路径，`write`/`read` 列全读写集。
3. `python ~/.workbuddy/tools/bg_check.py --declare <声明.json>` 登记。
   exit=1 且输出「满足 T3/T4，按规则派发」是派发语义，不是失败。

每个分片完成后（交付物必须真实存在且非空，否则工具拒记）：
4. `python ~/.workbuddy/tools/bg_check.py --complete --id <id> --shard <sN>`

中断后恢复（已完成且产物在的分片列入「复用」，只重跑未完成/产物丢失的）：
5. `python ~/.workbuddy/tools/bg_check.py --resume --id <id>`

不做什么：单步任务、纯问答、只读检索不登记；不手工编造完成状态，不用空文件冒充交付物。
