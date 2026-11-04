---
name: academic-plotting
description: 为 ML 论文生成出版级插图：从论文章节或描述中抽取系统组件与关系，产出架构图/流程图等可直接入稿的图。当用户要给学术论文配图、画模型架构图时用。
version: 1.0.0
author: Orchestra Research
license: MIT
tags: [Academic Writing, Visualization, Matplotlib, Seaborn, Plotting, Figures, Diagrams, NeurIPS, ICML, ICLR, LaTeX]
dependencies: [matplotlib>=3.8.0, seaborn>=0.13.0, numpy, google-genai>=1.0.0]
---

# Academic Plotting for ML Papers

Generate publication-quality figures for ML/AI conference papers. Two distinct workflows:

1. **Diagram figures** (architecture, system design, workflows, pipelines) — AI image generation via Gemini
2. **Data figures** (line charts, bar charts, scatter plots, heatmaps, ablations) — matplotlib/seaborn

## When to Use Which Workflow

| Figure Type | Tool | Why |
|-------------|------|-----|
| Architecture / system diagram | Gemini (Workflow 1) | Complex spatial layouts with boxes, arrows, labels |
| Workflow / pipeline / lifecycle | Gemini (Workflow 1) | Multi-step processes with connections |
| Bar chart, line plot, scatter | matplotlib (Workflow 2) | Precise numerical data, reproducible |
| Heatmap, confusion matrix | matplotlib/seaborn (Workflow 2) | Structured grid data |
| Ablation table as chart | matplotlib (Workflow 2) | Grouped bars or line comparisons |
| Pie / donut chart | matplotlib (Workflow 2) | Proportional data (use sparingly in ML papers) |
| Training curves | matplotlib (Workflow 2) | Loss/accuracy over steps/epochs |

**Rule of thumb**: If the figure has numerical axes, use matplotlib. If the figure has boxes and arrows, use Gemini.

---

## Step 0: Context Analysis & Extraction

The user will typically provide one of these inputs — not a ready-made specification:

| Input Type | Example | What to Extract |
|-----------|---------|-----------------|
| Full paper / section draft | "Here's our method section..." | System components, their relationships, data flow |
| Description paragraph | "Our system has three layers that..." | Key entities, hierarchy, connections |
| Raw results / data table | "MMLU: 85.2, HumanEval: 72.1..." | Metrics, methods, comparison structure |
| CSV / JSON data | Experiment log files | Variables, trends, grouping dimensions |
| Vague request | "Make a figure for the overview" | Read surrounding paper context to infer content |

### Extraction Workflow

**For diagrams** (research context → architecture figure):

1. **Read the provided context** — paper section, abstract, or description paragraph
2. **Identify visual entities** — What are the main components/modules/stages?
   - Look for: nouns that represent system parts, named modules, layers, stages
   - Count them: if >8 top-level entities, consider grouping into sections
3. **Identify relationships** — How do components connect?
   - Look for: verbs describing data flow ("sends to", "queries", "feeds into")
   - Classify: data flow (solid arrow), control flow (gray), error path (dashed red)
4. **Determine layout pattern**:
   - Sequential pipeline → left-to-right flow
   - Layered architecture → horizontal bands stacked vertically
   - Hub-and-spoke → central node with radiating connections
   - Hierarchical → top-down tree
5. **Assign colors** — One accent color per logical group/layer
6. **Write every label exactly** — Extract exact terminology from the paper text

**For data charts** (results → figure):

1. **Read the provided data** — table, paragraph with numbers, CSV, or JSON
2. **Identify dimensions**:
   - What is being compared? (methods, models, configurations) → categorical axis
   - What is the metric? (accuracy, loss, latency, F1) → value axis
   - Is there a time/step dimension? → line plot
   - Are there multiple metrics? → multi-panel or grouped bars
3. **Choose chart type** automatically using this priority:
   - Has a step/time axis → **line plot**
   - Comparing N methods on M benchmarks → **grouped bar chart**
   - Single ranking → **horizontal bar** (leaderboard)
   - Correlation between two continuous variables → **scatter plot**
   - Square matrix of values → **heatmap**
   - Proportional breakdown → **stacked bar** (avoid pie charts)
4. **Determine figure sizing** — Single column vs full width based on data density
5. **Highlight "our method"** — Identify which entry is the paper's contribution and give it a distinct color

### Auto-Detection Examples

**Context → Diagram**: "Our system has a Planner, Executor, and Verifier. Planner sends plans to Executor, Executor returns results to Verifier, Verifier feeds back to Planner on failure."
→ 3 entities, cycle layout, dashed feedback arrow → **Workflow 1 (Gemini)**

**Data → Chart**: "GPT-4: MMLU 86.4, HumanEval 67.0. Ours: 88.1, 71.2. Llama-3: 79.3, 62.1."
→ 3 methods × 2 benchmarks → **Workflow 2 (grouped bar)**, highlight "Ours" in coral

---


### Step-by-step workflows live in references/

This file keeps the decision table and the publication-style quick reference. Read exactly one workflow file per figure type:

| Content | Read when | File |
|---------|-----------|------|
| Workflow 1 (full steps) | Drawing an architecture or system diagram and you need the whole style-then-prompt sequence | `references/workflow1-diagrams.md` |
| Workflow 2 (full steps) | Drawing a data-driven chart and you need the full checklist and code path | `references/workflow2-charts.md` |
| Diagram prompt library | Reusing ready-made style prompts and API notes | `references/diagram-generation.md` |
| Chart patterns | Reusing matplotlib / seaborn patterns and palettes | `references/data-visualization.md` |
| Publication style guide | Needing venue-specific font, size and colour rules | `references/style-guide.md` |

## Publication Style Quick Reference

| Venue | Single Col | Full Width | Font |
|-------|-----------|------------|------|
| NeurIPS | 5.5 in | 5.5 in | Times |
| ICML | 3.25 in | 6.75 in | Times |
| ICLR | 5.5 in | 5.5 in | Times |
| ACL | 3.3 in | 6.8 in | Times |
| AAAI | 3.3 in | 7.0 in | Times |

**Always export PDF** for vector quality. PNG only for AI-generated diagrams.

**Venue-specific details, LaTeX integration, font matching, accessibility checklist**: See [references/style-guide.md](references/style-guide.md)

---

## Common Issues

| Issue | Solution |
|-------|----------|
| Fonts look wrong in LaTeX | Export PDF, set `text.usetex=True`, or use `font.family=serif` |
| Figure too large for column | Check venue width limits, use `figsize` in inches |
| Colors indistinguishable in print | Use colorblind-safe palette + different line styles/markers |
| Gemini misspells labels | Spell out every label exactly in prompt, add "SPELL EXACTLY" constraint |
| Gemini ignores style | Add more negative constraints, be more specific about hex colors |
| Blurry figures in PDF | Export as PDF (vector), not PNG; or use 300+ DPI for PNG |
| Legend overlaps data | Use `bbox_to_anchor`, `loc="upper left"`, or external legend |
| Too many tick labels | Use `ax.xaxis.set_major_locator(MaxNLocator(5))` |

## When to Use vs Alternatives

| Need | This Skill | Alternative |
|------|-----------|-------------|
| Architecture diagrams | Gemini generation | TikZ (manual), draw.io (interactive), Mermaid (simple) |
| Data charts | matplotlib/seaborn | Plotly (interactive), R/ggplot2 (statistics-heavy) |
| Full paper writing | Use with `ml-paper-writing` | — |
| Poster figures | Larger fonts, wider | `latex-posters` skill |
| Presentation figures | Larger text, fewer details | PowerPoint/Keynote export |

---

## Quick Reference: File Naming Convention

```
figures/
├── gen_fig_<name>.py      # Generation script (always save for reproducibility)
├── fig_<name>.pdf         # Final vector output (for LaTeX)
├── fig_<name>.png         # Raster output (300 DPI, for AI-generated or fallback)
└── fig_<name>_attempt*.png # Gemini attempts (keep for comparison)
```
