# 从零生成 PPT

输入可以是一篇文章或口播稿、一个题目、一份大纲，也可以是 .docx / .pdf / .pptx 素材。
生成和美化共用同一套设计引擎，区别只在前半程：美化是从原稿里抽出 deck.json，生成是自己写出 deck.json。
生成模式下文字可以改写、精简、重组，这是和美化最大的不同。

## 流程总览

| 步 | 做什么 | 工具 | 停下来确认 |
|---|---|---|---|
| G1 | 问清需求 | 一次提问 | 是 |
| G2 | 分析素材 | `analyze_source.py` | 否 |
| G3 | 写 deck.json | 按本文规则 | 否 |
| G4 | 检查大纲，给用户过目 | `outline_check.py` → outline.md | 是 |
| G5 | 定风格 | 有参考图走 `extract_style.py`；没有就 `style_previews.py --auto` 出三张样张 | 是 |
| G6 | 版式规划 | `plan_deck.py` → design_spec.md | 是（快速模式跳过） |
| G7 | 出图、组装、检查 | `pipeline.py` | 否 |
| G8 | 交付 | pptx + 预览图 + 一句话说明 | |

用户说"直接出""不用问我"时进入快速模式：G1 用默认值，G4、G5、G6 不停，自动选第一套风格样张，交付时把做过的选择列出来。

## G1 问清需求

用一次提问问完，没回答的用括号里的默认值。

- 用在哪里：口播视频 / 现场演讲 / 发出去给人读 / 工作汇报（口播视频）
- 给谁看：小白 / 有基础 / 专业同行 / 老板（小白）
- 多长：几分钟或几页（按素材估）
- 风格：有没有参考图；没有就出三张样张挑（出样张）
- 要不要口播备注（口播和演讲默认要）

场景决定密度：口播和演讲用 low（一页一个观点，屏幕字少，展开的话放备注），阅读和汇报用 high（一页能独立看懂，可以多放几条）。

## G2 分析素材

```bash
python3 $S/analyze_source.py $W --file 文章.md --scenario oral
python3 $S/analyze_source.py $W --topic "题目" --minutes 3
```

得到 analysis.md：字数、原文标题结构、可做成数据页的数字、风格线索、建议页数。
页数估算的经验是口播一页约 25 秒、对应 150 字左右原文；大纲按"每个二级标题至少一页"。

**只有题目时**，先定"观众看完要记住的一句话"，再列三到五个支撑点。涉及事实、数据、产品现状的，先用搜索查证，查不到的不写，绝不编数字。

## G3 写 deck.json

字段格式见 `deck_schema.md`。生成模式额外用到这些字段。

```json
{"meta": {"title": "…", "scenario": "oral", "audience": "小白", "density": "low",
          "storyline": "一句话讲清这份 PPT 的来龙去脉", "notes": true, "auto_page": true,
          "series": "页眉小字，可选", "anchor": {"description": "…", "glyph": "M"}},
 "slides": [{"n": 2, "type": "big_number", "purpose": "让观众一句话记住它是什么",
             "title": "…", "…": "…", "notes": "口播原话", "source": "数据出处，可选"}]}
```

### 先搭故事线

按场景挑一条主线，再往里填页。

- **讲解型**（口播科普默认）：开场钩子 → 它是什么 → 为什么值得关注（证据、数据）→ 怎么用 → 坑和边界 → 行动号召
- **方案型**（汇报）：现状和问题 → 目标 → 方案 → 计划和资源 → 风险 → 需要拍板的事
- **清单型**（技巧合集）：为什么需要 → 第一条到第 N 条 → 怎么组合 → 行动号召

把主线写进 `meta.storyline`，每页写 `purpose`（这一页在故事里负责什么）。

### 标题写结论

每页标题是一句能单独成立的结论，不是话题名。

| 话题名（不要） | 结论式（要） |
|---|---|
| 数据表现 | 它火得数据很硬 |
| 使用方法 | 上手先改权限，再连账号 |
| 注意事项 | 它会犯错，别把判断交出去 |

写完把所有标题按顺序连起来读，读下来是一个完整的故事才算过关；读不通就调整顺序或补页，别急着做设计。长度控制在 4 到 22 个字。

### 一页一件事

- 一页只讲一个观点。装不下就拆页，不缩字号硬塞。
- low 密度：屏幕上约 100 字以内、要点最多 4 条；high 密度：约 200 字以内、要点最多 6 条。
- 屏幕放关键词和短句，完整的话放 `notes`。
- 结尾页放结论或行动号召，不放"谢谢观看"。
- 超过 15 页时加章节分隔页（type: section）。

### 口播备注

`notes` 就是要念的稿子：口语、短句、和这一页的内容一一对应，一页 40 到 260 字（约 15 到 60 秒）。
从文章改写时，备注尽量保留作者原句和语气，屏幕文字再从备注里提炼。
环境里如果有用户自己的写作风格 skill，备注按那个风格写。

### 内容形状决定页型

| 内容长什么样 | type | 默认版式 |
|---|---|---|
| 一个核心数字或一句话定义 | big_number | statement_number |
| 两到四个数据 | stats | stats_row |
| 有先后顺序的两到五步 | process | steps_flow |
| 做法建议，一条重点一条补充 | steps | side_cards |
| 两种东西对比、前后对比 | compare | compare_split |
| 循环往复的环节 | cycle | cycle |
| 有层级、有基础和上层 | layers | pyramid |
| 几个并列概念的解释 | definitions | rows_side |
| 三到六个短要点 | list / grid | grid_cards |
| 例句、提示词、原话 | quotes | quote_cards |
| 风险和坑，加一句总结 | warnings | cards_quote |
| 一句主张加解释 | statement | statement_hero |
| 示意图加讲解 | diagram_text | media_text |
| 一张截图讲清几个操作点 | screenshot | shot_notes |
| 几张截图走完一个流程，或电脑和手机对照 | screenshots | shot_stack |
| 按时间排的里程碑、发展历程 | timeline | timeline |
| 一层层转化、筛选、流失 | funnel | funnel |
| 一个核心辐射出几个部分 | hub | hub |
| 按两个维度给事情分类、排优先级 | matrix | matrix |
| 多个方案在多个维度上比较 | table | table |
| 数字之间比大小、看趋势、看占比 | chart | chart |
| 优劣势、外部环境、竞争格局、商业模式 | framework | framework |
| 章节开头 | section | section |
| 分了章节的稿子，封面后面 | toc | toc |
| 抛出一个问题，下一页再回答 | question | question |
| 一句值得单独成页的原话 | big_quote | big_quote |

同一种页型别连续出现三次，换一种讲法。各页型的字段见 `deck_schema.md`，每个版式装得下多少用 `python3 $S/layout_info.py <版式名>` 查，里面还带一段能直接改的示例。

数据页的取舍：只想让人记住一两个数字，用 big_number 或 stats；要让人看出谁大谁小、往哪走、占多少，才上 chart。chart 的标题就是图里最重要的那个结论，insights 补一两条标题没说完的发现。

分析框架别为了显得专业硬套。SWOT 四格里有一格只能凑出空话，就说明这页该换成 compare 或 warnings。

标题里最关键的一个词可以用 `**…**` 包起来，它会变成强调色；一个标题最多标一处，标多了就没有重点。

### 从三种输入出发的要点

- **文章或口播稿**：先按段落切出故事线，一段往往就是一页；数字优先做成数据页；原文金句可以直接当标题或 takeaway。
- **大纲**：每个二级标题至少一页；带顺序的列表用 process，"坑""误区"类用 warnings，"写在最后"做结尾页。大纲通常没有展开的话，备注需要补写，补写的事实要查证。
- **题目**：见 G2 的做法，先查证再写。

## G4 检查大纲

```bash
python3 $S/outline_check.py $W
```

它会打印幽灵稿（只读标题），检查话题式标题、密度、要点条数、备注长度、页数、页型重复和结尾页，还会按版式容量报出装不下的页，并给出能装下的替代版式。
修到没有 ERROR、WARN 都看过为止，然后把 outline.md 的"只读标题"部分发给用户确认。

## G5 定风格

- 用户给了参考图：走美化流程的第 2 步（`extract_style.py` + 看图写 style.json + `style_card.py`）。
- 没有参考图：
  ```bash
  python3 $S/style_previews.py $W --auto          # 或 --presets a,b,c 自己挑三套
  python3 $S/style_previews.py $W --apply <id>    # 用户选定后
  ```
  三张样张分别是稳妥、大胆、意外各一，都是用户自己的封面和第一页内容。把 `previews/sheet.png` 发给用户，并在对话里说明 1、2、3 各是什么风格、适合什么。预设清单见 `references/style-index.json`，每套的硬规则在对应的 json 里，排版时遵守。

## G6 版式规划

```bash
python3 $S/plan_deck.py $W --level full            # 有生图模型时可加 --sheets，一张大图切多张小插画
```

它写出 plan.json 和 design_spec.md。审一遍：版式是否贴合内容、每页视觉焦点是否清楚、插画提示词是否具体（见 `image_prompts.md`）。
可以在 plan.json 每页补 `relation`（和前后页的关系，比如"承接上页的数据，转入怎么做"），帮助统一节奏。
把 design_spec.md 的表格发给用户确认后再出图，出图是最花钱的一步。

## G7 出图、组装、检查

```bash
python3 $S/pipeline.py $W
```

生成模式下 QA 以 deck.json 为准，检查每段文字都上了页面，其余检查和美化相同。
AI 插画的最终提示词会写进 `prompts/`，要改某张图就改它的提示词文件，再 `make_assets.py $W --only hero_05 --force`。

## G8 交付

pptx、预览图，加一两句说明：用了哪套风格、插画来源（模型或程序化）、有没有需要用户补充核实的内容。
