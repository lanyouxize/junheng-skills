# Phase 8 综述生成 · 完整模板

> 本文件由 SKILL.md 的 Phase 8 段落【逐字】外置，一字未改。
> 进入 Phase 8 前必须完整读取本文件；SKILL.md 只保留骨架与导航。

### Phase 8.1: Outline（生成综述大纲）

**目标**：基于文献主题聚类，构建逻辑清晰的综述结构

**输入**：
- 研究主题
- 文献清单（含单篇分析结果）
- 目标语言

**AI 提示词模板**：

```
You are a renowned professor specializing in research methodology and academic writing.
Your task is to create a comprehensive, well-structured, and logically sound literature review outline.

Research topic:
<research_topic>
{{研究主题}}
</research_topic>

Collected literature analysis:
<collected_literature>
{{文献清单和分析}}
</collected_literature>

Target language:
<language>
{{中文/英文}}
</language>

Instructions:

1. Analyze all collected papers and identify 3-5 main themes or research directions.

2. Structure the outline as follows:
   a) Introduction (background, objectives, search strategy)
   b) Theoretical Foundation and Methods
   c) Main Body (3-5 sections based on theme clustering)
      - Domestic Research Status (Chinese literature)
      - International Research Status (English literature)
      - Or thematic sections (e.g., Algorithm Research, Clinical Applications)
   d) Discussion (comparative analysis, research gaps, trends)
   e) Conclusion
   f) References

3. For each main section, provide 3-5 specific subsections with clear titles.

4. Ensure logical flow:
   - From general to specific
   - From theory to application
   - From past to future directions

5. Allocate literature to appropriate sections:
   - Each paper should be referenced in at least one section
   - Highlight connections between papers

6. Output format:
   # Literature Review Outline: [Research Topic]
   
   ## 1 Introduction
   ### 1.1 Research Background
   ### 1.2 Research Objectives
   ### 1.3 Search Strategy
   
   ## 2 Theoretical Foundation
   ### 2.1 [Theory/Method 1]
   ### 2.2 [Theory/Method 2]
   
   ## 3 [Main Theme 1]
   ### 3.1 [Sub-theme]
   - Key papers: [C1], [E1], [E2]
   - Main arguments: ...
   ### 3.2 [Sub-theme]
   
   [Continue for all themes...]
   
   ## 4 Discussion
   ### 4.1 Comparative Analysis
   ### 4.2 Research Gaps
   ### 4.3 Future Directions
   
   ## 5 Conclusion
   
   ## References

7. Do not write any content for the sections, only the structure.

8. Ensure the outline can support a 3000-5000 word literature review.
```

**输出**：`outline.md` - 完整的综述大纲，含章节结构和文献分配

---

### Phase 8.2: Writing（撰写综述初稿）

**目标**：基于大纲撰写完整的综述内容，建立文献间的逻辑联系

**输入**：
- 综述大纲
- 文献清单和分析
- 单篇文献深度分析

**AI 提示词模板**：

```
You are a literature writing expert tasked with creating a high-quality, comprehensive academic literature review.

Input materials:
<outline>
{{综述大纲}}
</outline>

<collected_literature>
{{文献清单和摘要}}
</collected_literature>

<detailed_analysis>
{{单篇文献深度分析}}
</detailed_analysis>

Target language: {{中文/英文}}

Writing instructions:

1. Expand EACH section in the outline into detailed content:
   - Section 1 (Introduction): 300-500 words
   - Section 2 (Theoretical Foundation): 500-800 words
   - Section 3 (Main Body): 1500-2500 words (divided among subsections)
   - Section 4 (Discussion): 500-800 words
   - Section 5 (Conclusion): 200-300 words

2. For each subsection:
   - Start with a topic sentence summarizing the main point
   - Synthesize 3-5 relevant papers (do not summarize one by one)
   - Compare and contrast different studies
   - Highlight agreements and disagreements in the literature
   - Identify patterns and trends

3. Critical analysis requirements:
   - Evaluate methodological strengths and weaknesses
   - Point out inconsistencies or contradictions
   - Question assumptions and limitations
   - Suggest alternative interpretations

4. Citation format:
   - Use ([C1](url)), ([E1](url)) for in-text citations
   - Every claim should be supported by at least one citation
   - Group related citations: ([C1], [C2], [E1])

5. Writing style:
   - Academic and formal tone
   - Clear and concise sentences
   - Logical transitions between paragraphs
   - Avoid bullet points in main text (use prose)

6. Structure each paragraph:
   - Topic sentence
   - Evidence from literature (with citations)
   - Critical commentary
   - Transition to next point

7. Output the complete review in Markdown format without XML tags.

8. Do not include abstract or keywords yet (will be added in Phase 8.4).
```

**输出**：`draft.md` - 完整的综述初稿（3000-5000字）

---

### Phase 8.3: Review（质量审查与评估）

**目标**：系统性审查综述质量，识别问题和改进点

**输入**：
- 综述初稿
- 原始文献清单
- 研究主题

**AI 提示词模板**：

```
You are an experienced academic review expert specializing in literature reviews.
Conduct a comprehensive, rigorous multi-dimensional assessment of the submitted literature review.

Materials to review:
<literature_review_draft>
{{综述初稿}}
</literature_review_draft>

<original_topic>
{{研究主题}}
</original_topic>

<collected_papers>
{{原始文献清单}}
</collected_papers>

Review criteria:

a) ACCURACY AND COMPREHENSIVENESS (Weight: 25%)
   - Are all factual claims accurate?
   - Are there any misrepresentations of cited studies?
   - Does it cover all important aspects of the topic?
   - Are significant papers missing or overlooked?
   - Score: ___/10

b) LOGICAL ARGUMENTATION (Weight: 25%)
   - Is the overall structure logical and coherent?
   - Do arguments flow naturally from one to another?
   - Are all claims adequately supported by evidence?
   - Are there any logical fallacies or gaps?
   - Score: ___/10

c) LITERATURE CITATIONS (Weight: 20%)
   - Are citations accurate and properly formatted?
   - Is the citation density appropriate (not too sparse or excessive)?
   - Are cited papers relevant to the claims made?
   - Is there a balance between different sources?
   - Score: ___/10

d) CRITICAL ANALYSIS (Weight: 15%)
   - Does it go beyond mere summarization?
   - Are methodological strengths/weaknesses discussed?
   - Are contradictions and controversies identified?
   - Is there genuine synthesis (not just listing papers)?
   - Score: ___/10

e) LANGUAGE AND STYLE (Weight: 10%)
   - Is the language clear, concise, and academic?
   - Are there grammatical errors or awkward phrasing?
   - Is the tone appropriate for academic writing?
   - Score: ___/10

f) INNOVATION AND INSIGHT (Weight: 5%)
   - Does it provide new insights or perspectives?
   - Are future research directions clearly identified?
   - Is there a theoretical framework proposed?
   - Score: ___/10

Deliverables:

1. Overall Quality Score: ___/100

2. Detailed Assessment:

<review>
<major_strengths>
[List 3-5 major strengths of the review with specific examples]
</major_strengths>

<critical_issues>
[List critical issues that MUST be fixed, with specific locations (section/paragraph)]
</critical_issues>

<areas_for_improvement>
[List areas that could be improved for better quality]
</areas_for_improvement>

<missing_elements>
[List important elements missing from the review]
</missing_elements>

<specific_suggestions>
[Provide detailed, actionable suggestions for revision]
1. Section X, Paragraph Y: [Specific issue] → [Suggested fix]
2. ...
</specific_suggestions>

<citation_issues>
[Identify any citation errors or missing citations]
</citation_issues>
</review>

3. Revision Priority:
   - CRITICAL (Must fix): [List]
   - HIGH (Should fix): [List]
   - MEDIUM (Nice to have): [List]
```

**输出**：`review_report.md` - 详细的审查报告，含评分和改进建议

---

### Phase 8.4: Final（最终润色与定稿）

**目标**：根据审查报告修订并生成最终版本，添加摘要和关键词

**输入**：
- 综述初稿
- 审查报告
- 研究主题

**AI 提示词模板**：

```
You are tasked with finalizing a literature review article based on a draft and review feedback.

Input materials:
<draft>
{{综述初稿}}
</draft>

<review_report>
{{审查报告}}
</review_report>

<research_topic>
{{研究主题}}
</research_topic>

Finalization steps:

1. ADDRESS REVIEW FEEDBACK:
   - Fix all CRITICAL issues identified in the review
   - Address HIGH priority suggestions
   - Consider MEDIUM priority improvements if time permits

2. STRUCTURE AND FORMATTING:
   - Ensure proper Markdown formatting
   - Apply consistent heading levels (# Title, ## Section, ### Subsection)
   - Check that all citations use format ([X](url))
   - Verify all URLs are valid

3. CONTENT REFINEMENT:
   - Strengthen weak arguments
   - Add missing citations
   - Improve transitions between sections
   - Ensure critical analysis is present throughout
   - Balance coverage across topics

4. WRITE ABSTRACT (200-300 words):
   Structure:
   - Background (1-2 sentences): Context and importance
   - Objective (1 sentence): Purpose of the review
   - Methods (1-2 sentences): Search strategy and inclusion criteria
   - Results (2-3 sentences): Main findings and themes
   - Conclusion (1-2 sentences): Key implications

5. SELECT KEYWORDS (5-8 keywords):
   - Include main research topics
   - Include key methods/technologies
   - Include application domains
   - Separate with semicolons

6. COMPILE REFERENCES:
   - Convert in-text citations to GB/T 7714-2015 format
   - Sort by citation number ([C1], [C2]..., [E1], [E2]...)
   - Ensure all cited papers are in the reference list

7. FINAL POLISH:
   - Proofread for spelling and grammar
   - Check for consistent terminology
   - Ensure academic tone throughout
   - Verify word count (target: 3000-5000 words excluding references)

Output format:

```markdown
# [Research Topic]: A Literature Review

## Abstract

[200-300 word abstract]

**Keywords**: keyword1; keyword2; keyword3; keyword4; keyword5

---

[Main content with all revisions applied]

---

## References

[C1] ...
[C2] ...
[E1] ...
...
```

Requirements:
- Output ONLY the finalized review in Markdown
- No XML tags
- No meta-commentary about the revision process
- Ready for direct use or submission
```

**输出**：`literature_review.md` - 最终定稿的完整综述（含摘要、关键词、参考文献）

---

### Phase 8 输出文件

| 文件 | 阶段 | 内容 |
|------|------|------|
| `outline.md` | 8.1 | 综述大纲，含章节结构和文献分配 |
| `draft.md` | 8.2 | 综述初稿（3000-5000字） |
| `review_report.md` | 8.3 | 质量审查报告，含评分和改进建议 |
| `literature_review.md` | 8.4 | **最终定稿**（含摘要、关键词、参考文献） |

---

### 四步法的质量保证

| 步骤 | 质量控制点 | 常见问题 |
|------|-----------|---------|
| **Outline** | 结构逻辑性、主题覆盖度 | 章节不平衡、遗漏重要主题 |
| **Writing** | 论证深度、批判性思维 | 简单罗列、缺乏分析 |
| **Review** | 准确性、完整性 | 事实错误、引用不当 |
| **Final** | 学术规范性、可读性 | 格式混乱、语言问题 |

---

### 迭代机制

如果审查报告显示严重问题（总分<70），可以：

1. **小修**（70-85分）：直接在 Final 阶段修正
2. **中修**（60-70分）：回到 Writing 阶段重写部分章节
3. **大修**（<60分）：回到 Outline 阶段重新规划结构

**默认流程**：按 8.1 → 8.2 → 8.3 → 8.4 顺序执行一次
**迭代流程**：8.4 发现问题 → 回到对应阶段 → 重新执行后续步骤

---

