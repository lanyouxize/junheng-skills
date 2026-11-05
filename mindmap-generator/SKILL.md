---
name: mindmap-generator
display_name: 帮我生成脑图
display_name_en: Mind Map Generator
version: 1.0.0
description: 把本地文档、网页或微信公众号文章转换成交互式脑图，先提取正文纯文字并剔除图片与广告，再提炼为带约 200 字摘要的结构化脑图。
description_zh: 把本地文档（docx/pdf/pptx/txt/md/html）、网页或微信公众号文章转换成交互式脑图。严格两步：先提取纯文字正文并剔除图片、广告等非核心内容，再提炼为带约 200 字摘要的结构化脑图，产出为自包含 HTML，支持导出 PNG 与 SVG。当用户要求生成脑图、做思维导图、把某份文档或链接画成脑图/知识图谱/结构图、总结成导图时使用。
description_en: Convert local documents (docx, pdf, pptx, txt, md, html), web pages, or WeChat official-account articles into an interactive mind map with an approximately 200-word summary. Two strict steps - first extract the plain body text and strip images, ads, QR codes and other non-core content, then distill it into a structured mind map rendered as a self-contained offline HTML file with PNG and SVG export. Trigger this skill when the user asks to generate a mind map, make a mind map or knowledge graph or structure chart from a document or link, or summarize content into a mind map.
category: 文档处理
---

# 帮我生成脑图

## 目标

把「本地文档 / 网页 / 公众号文章」转换成一张结构清晰的脑图。严格两步：

1. **提取文字内容**——剔除图片、广告、二维码、关注引导等非核心内容；
2. **制作脑图**——产出包含一段约 200 字摘要的交互式脑图（HTML）。

## 运行环境

- Python 解释器（隔离环境，含 python-docx / pypdf / python-pptx）：
  `C:\Users\Administrator\.workbuddy\binaries\python\envs\default\Scripts\python.exe`
- 两个脚本均为**零第三方依赖设计**（HTML 解析用标准库），缺 docx/pdf/pptx 库时会给安装提示。
- HTML 模板：`assets/mindmap_template.html`（占位符 `__XXX__` 勿改名）。

## 工作流

### 第一步：提取正文（脚本）

```bash
python scripts/extract_content.py --source "<文件路径或URL>" --output "<中间稿.md>" --report
```

| 参数 | 说明 |
| --- | --- |
| `--source` | 必填。本地路径或 http(s) 链接 |
| `--output` | 中间稿输出路径（建议放当前工作区） |
| `--report` | 在 stderr 输出剔除统计 |
| `--max-chars` | 正文长度上限，默认 80000 |

- 支持来源：`.docx` `.pdf` `.pptx` `.txt` `.md` `.html/.htm`、任意网页 URL、`mp.weixin.qq.com`。
- 公众号走专用解析（`js_content` 容器 + `msg_title`），输出首行自动补 `# 文章标题`。
- 脚本已自动剔除：图片/表情/二维码、点赞在看转发引导、关注提示、广告位、编辑/来源/免责声明、图注、平台水印（词表见 `references/content-rules.md`）。
- **失败兜底**：抓取受限、正文为空或图片型文章（文字全是图）→ 改用 browser agent 打开链接，多屏滚动截图 + OCR 逐段提取，不要直接放弃。
- 输出为 Markdown 中间稿：`#` 标题 + 普通段落。**这只是原料，下一步必须人工提炼。**

### 第二步：写摘要 + 整理大纲（由你完成）

阅读中间稿后，产出一份**大纲文件**（`.md`），格式严格如下：

```markdown
# 文章标题

## 摘要
（一段 200 字左右的摘要正文，140–300 字之间，单独一段）

## 分支一标题
- 短语叶子
- 短语叶子
  - 可再下一层的二级叶子

## 分支二标题
- ...
```

要求：

- 摘要约 200 字，覆盖"是什么、核心观点、结论/价值"，不堆砌细节。
- 根节点 `#` 只有 1 个；一级分支 `##` 建议 3–7 个；每个分支下叶子 3–8 条。
- 叶子要**短语化**（≤ 30 字），提炼关键词与逻辑关系，不整段复制原文。
- 需要展开细节时用缩进 2 空格的二级 `- `，整体不超过 4 层。
- 不使用 `>` 引用块、表格、代码块（脚本不解析）。
- 总节点数控制在 20–60 个，超出的做合并归纳。

### 第三步：生成脑图（脚本）

```bash
python scripts/build_mindmap.py --input "<大纲.md>" --output "<标题>_脑图.html" --source "<来源>" --require-summary
```

| 参数 | 说明 |
| --- | --- |
| `--input` | 第二步的大纲文件 |
| `--output` | 输出 HTML 路径（用户未指定则存桌面） |
| `--source` | 来源说明（原链接或文件名），显示在页头 |
| `--theme` | `light`（默认）/ `dark` |
| `--require-summary` | 缺少摘要时报错，建议始终加上 |
| `--summary-file` | 从独立 txt 读取摘要（可选） |

产出为**单文件 HTML**：零外部依赖、离线可打开，含顶部摘要卡片 + 摘要节点 + 可折叠脑图，支持滚轮缩放、拖拽平移、节点折叠、深色模式和「导出 PNG / 导出 SVG」。

完成后：
1. 用 `present_files` 呈现该 HTML；
2. 在回复中给出 200 字摘要与脑图分支概览（分支数、节点数）。

## 注意事项

- **摘要必须存在**：页面顶部卡片与脑图中的「摘要」节点都依赖它，缺失时脚本会警告或（加 `--require-summary` 时）报错。
- 中间稿 ≠ 大纲：直接把中间稿喂给第三步会得到一坨长段落节点，务必先做第二步提炼。
- 严格"不要图"：正文配图既不导出也不截图塞进脑图，图注一并剔除。
- 中文文件名路径直接可用；输出路径务必用绝对路径并真实落盘。
- 生成后清理中间产物（临时 .md、调试文件），保留最终 HTML。

## references / assets

- `references/content-rules.md` —— 剔除规则词表、来源适配细节、脑图结构规范与质量自检表。
- `assets/mindmap_template.html` —— 脑图渲染模板（由 `build_mindmap.py` 注入数据，占位符勿改）。
- `assets/example_mindmap.html` —— 成品示例（一篇公众号文章生成的脑图），可直接打开对照预期效果。
