---
name: humanizer-studio
display_name: 去AI味·文本人化工坊
display_name_en: Humanizer Studio
description: "去AI味文本人化工作室：把AI生成或模板化的文字改写成自然、像人写的文案与文章，支持简体中文/繁体中文/英文/日文。一键检测AI腔（套路词、机械排比、过度结构化、虚词滥用），给出人化改写与口语化建议，保留原意与信息密度。触发词：去AI味、去机械感、humanizer、AI检测、文本润色、口语化、自然写作、去套路、文章改写、英文润色、日文润色、学术降重、文案人化。"
description_zh: "去AI味·文本人化工坊：把AI生成或模板化的文字改写成自然、有人味的中文/英文/日文。自动识别AI腔套路（值得注意的是、总而言之、delve、in today's world、机械排比、过度使用项目符号），按语种给出人化改写、口语化与节奏调整建议，保留原意与关键信息。触发词：去AI味、去机械感、humanizer、AI检测、文本润色、口语化、自然写作、文章改写、英文润色、日文润色、繁体中文、跨境文案人化。"
description_en: "Humanizer Studio: rewrite AI-generated or robotic text into natural, human-sounding copy in Simplified Chinese, Traditional Chinese, English and Japanese. Detects AI tells (stock phrases, mechanical parallelism, over-structured lists, filler words) and produces a humanized rewrite with tone and rhythm tuning while preserving meaning. Triggers: humanizer, remove AI tone, natural writing, AI detection, text polish, colloquialize, article rewrite, English editing, Japanese editing."
category: marketing
version: 1.0.0
author: 汪老师
license: Proprietary
compatibility: Python 3.9+.
---

# Humanizer Studio（去AI味·文本人化工坊）

本 skill 帮你（AI）把**AI 生成或模板化**的文字，改写成**自然、像真人写的**文案与文章。与 `copywriting-studio`（从零写营销文案）、`social-content`（写社媒帖子）的区别：它**处理"已有草稿"**——去 AI 味、去机械感、口语化、调节奏，是"改稿"而非"写稿"。支持简中 / 繁中 / 英文 / 日文四语。

## 工作流（6 步）

1. **Intake（先收集简报）**
   用 `assets/humanize_brief.md` 追问，必拿：① 待改原文；② 目标语言（zh-CN / zh-TW / en / ja）；③ 读者与场景（朋友圈 / 公众号 / 论文 / 工作报告 / 跨境帖）；④ 人化强度（轻：只润色 / 中：重组句式 / 重：重写语气）；⑤ 约束（是否保留术语、是否限定字数）。

2. **诊断 AI 腔**
   跑 `scripts/humanize.py --input 原文.txt --lang <语言>` 得到 **AI 腔评分 + 套路清单**；也可对照 `references/ai-tells.md` 人工判断。信息不足主动追问，不凭空编内容。

3. **定人化强度**
   轻 = 只删套路词、修语病；中 = 在中基础上重组句子节奏、长短交错；重 = 重写语气、加入具体细节与个人视角。强度越高越自然，但也越可能偏离原文措辞，需用户确认。

4. **套人化规则**
   读 `references/rewrite-rules.md` 的 7 条原则；按语种取 `references/templates-multilang.md` 的"AI 腔 → 人话"替换表。

5. **产出人化稿**
   保留原意与关键信息，做到：开场直接、句式多变、虚词精简、有 1 个具体细节/例子、结尾落地。多给一版"轻"一版"重"供选。

6. **合规过筛**
   读 `references/compliance.md`：不得用于学术/考试作弊、不得恶意规避 AI 检测器欺骗读者；涉及公开署名内容应披露 AI 辅助。只做"让表达更自然"，不做" disguised 欺骗"。

## 文件导航
- 诊断与启发式清理 → `scripts/humanize.py`
- AI 腔特征库（中英日） → `references/ai-tells.md`
- 人化 7 原则 → `references/rewrite-rules.md`
- 语种替换表 → `references/templates-multilang.md`
- 多行业 before/after → `references/examples-multi-industry.md`
- 合规边界 → `references/compliance.md`
- 简报清单 → `assets/humanize_brief.md`
