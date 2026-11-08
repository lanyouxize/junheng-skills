---
name: word-docx
display_name: Word/DOCX 文档专家
display_name_en: Word & DOCX Document Expert
description: 创建、检查、编辑 Word 与 .docx 的方法论。把 .docx 当 OOXML（zip 内 XML 部件）处理样式、编号、修订、表格、分节与域，保证 Word 与 LibreOffice 之间往返不跑版。适用于含修订批注、域或版式约束的文档任务。
description_zh: 创建、检查、编辑 Word 和 .docx 的方法论专家。把 .docx 当 OOXML（zip 内 XML 部件）而非纯文本处理，对样式、编号、修订痕迹、批注、表格、分节、域做可靠读写，保证 Word/Google Docs/LibreOffice 往返不跑版。适用于所有以 Word/.docx 为产物的任务，尤其带修订、批注、域、表格、模板、复杂分节版式的文档。当用户说改 docx、调版面、改页眉页脚编号、接受修订、修表格宽度、处理批注时使用。零脚本零依赖。
description_en: Methodology expert for creating, inspecting, and editing Microsoft Word documents and .docx files. Treats a .docx as OOXML (a zip of XML parts) rather than plain text, and handles styles, numbering, tracked changes, comments, tables, sections, and fields reliably so documents survive round-trip editing (Word ↔ Google Docs ↔ LibreOffice) without layout drift. Use whenever the deliverable is a Word/.docx file, especially with tracked changes, comments, fields, tables, templates, or page-layout constraints. Use when the user says edit/modify a docx, fix layout, adjust headers/footers/numbering, accept revisions, fix table widths, or handle comments. Pure methodology, zero scripts, zero dependencies.
category: productivity
version: 1.0.2
author: 开心一点
license: Proprietary
compatibility: LibreOffice.
---

# Word / DOCX 文档专家

围绕 **Word 与 `.docx`** 的创建、检查、编辑方法论。这套规则把 `.docx` 当作 **OOXML**（`.docx` = 一个 ZIP，内含若干 XML 部件）来对待，而不是当成能看到字就和能编辑的纯文本。

> 核心立场：`document.xml`、`styles.xml`、`numbering.xml`、页眉页脚、关系文件（relationships）每一样都有讲究；**能重排、能改、能来回存而不错版**才是真本事，而不是「删几个字还能打开」。

## 何时用

当主产物是 Word 文档或 `.docx`，尤其是涉及**修订痕迹、批注、页眉页脚、编号、域、表格、模板、兼容性**时。

## 核心规则

### 1. 把 DOCX 当成 OOXML，别当纯文本

- `.docx` 是 ZIP 里的 XML 部件，结构比「能看到的文字」重要得多。
- 关键部件通常是 `word/document.xml`、`styles.xml`、`numbering.xml`、页眉页脚、关系文件。
- 文字可能被拆到多个 run，永远不要假设一个词/一句在一个 XML 节点里。
- 刻意区分三条工作路径：快速读取用**结构化抽取**、新建文件用**样式驱动生成**、脆弱的存量文档用 **OOXML 感知编辑**。
- 主要只做阅读/抽取/审阅时，先走结构保持的读取路径，再碰 OOXML。
- 深改前先看包结构（在哪里一个 zip unzip 看部件），别只信渲染出来的样子。
- 读取、生成、保留一份已被审过的文档是**三件不同的事**，即便格式相同。
- 老式 `.doc` 输入通常要先转换，不能直接套用现代 `.docx` 假设。

### 2. 样式与直接格式要刻意保留

- 优先用「命名样式」而不是直接格式，文档才能持续可编辑。
- 样式分三层：段落样式、字符样式、直接格式，行为各不相同。
- 移除直接格式往往比继续堆内联格式更安全。
- 编辑存量文档时，延续已有样式体系，而不是另造一套并行的。
- 在文档间复制内容会**静默带入外部样式、主题设置、编号定义**，要多加小心。

### 3. 列表与编号是独立系统

- 项目符号和编号存在于 Word 的编号定义里，不是粘贴的 Unicode 字符。
- `abstractNum`、`num`、段落编号属性都关键，重启行为很少只是「视觉上的」。
- 缩进和编号有关但不同；一个列表缩进对了不代表编号没坏。
- 一个在某个编辑器里看着正常的列表，如果底层编号状态不对，之后可能重启、拍平或重新编号。

### 4. 页面版式活在分节里

- 页边距、方向、页眉页脚、页码是**分节级**行为。
- 首页页眉和奇偶页页眉可以在同一文档里不同，修一个页眉不等于修好整篇。
- 显式设置页面尺寸——A4 和美式 Letter 默认不同，会改分页与表格宽度。
- 版式改动用**分节符**；手动空段和散落的分页符通常造成漂移。
- 页眉页脚的媒体用部件专属关系，复制来的 ID 常会弄坏图片或链接。
- 表格、分页符、页眉经常一起飘，所以版式修复要当整篇的事，不是局部化妆品。
- 表格几何依赖页面宽度、页边距和固定列宽，「看着差不多」的表格编辑常会在 Google Docs 或 LibreOffice 里碎掉。

### 5. 修订、批注、域要精确编辑

- 开了修订后，看得见的文字不是文档全部。
- 增删、批注携带元数据，草率编辑可能把它们弄丢。
- 被删除的文字可能仍留在 XML 里，即便屏幕上已不显示。
- 批注锚点与审阅范围在文本移动时容易悬空/错位。
- 批注标记和审阅包装器不随内联格式走，乱移文本会 orphan 批注。
- 批注、脚注、书签、关联媒体可能住在**独立部件**，不只在正文里。
- 目录、页码、日期、交叉引用、邮件合并占位符**都是域**。
- 改域源要谨慎，缓存显示值要刷新后才会变。
- 超链接、书签、引用在 ID 或关系不对时容易断。
- 书签、脚注、批注范围、交叉引用依赖稳定锚点，即使可见文字没动。
- 文档可能看着正常，但藏着过期的域输出，接收方刷新后会变成别的样子。
- 审阅工作流里，做**最小替换**而不是整段重写。
- 修订痕迹工作流里，只有被改的片段看起来像被改；大段重写会产生噪音审阅、毁掉原始格式上下文。
- 对法务、学术、商务审阅文档，默认审阅式编辑而非整段重写，除非用户明确要重写。

### 6. 交付前验证往返兼容

- 复杂文档在 Word、LibreOffice、Google Docs、转换工具之间会移位。
- 表格、页眉、嵌入字体、复制的样式是版式漂移的常见来源。
- `.docm` 带宏、风险更高；`.doc` 是老输入，通常要先转换。
- 版式重要时，**显式表格宽度**比 auto-fit / 百分比这类会被不同编辑器重解的行为安全。
- 一个过了文字检查的文档，接收方打开后仍可能倒在分页、表格宽度或引用刷新上。

## 常见陷阱

- 复制粘贴会带入多余样式和编号定义。
- 页眉页脚图片用部件专属关系，乱复用 ID 会坏图。
- 用空段落当间距会让模板变脆；间距应写在段落设置里。
- 看着干净的导出可能仍藏着未解决的修订、批注或过期域值。
- 「肉眼」重启列表基本会失败，因为编号状态不在段落文字里。
- 一句能看到的短语可能被拆在多个 run、书签、修订标签或域边界里。
- 为了改一个连词就整段替换，常会弄坏审阅质量、书签、批注或周边内联格式。
- 把段落的可见文字全删，仍可能留下空段落符、空项目符号或不稳的编号。
- 表格 auto-fit / 百分比宽度在 Word 里看着没事，到了 Google Docs / LibreOffice 会漂。
- LibreOffice 和 Google Docs 会移位复杂表格、分节行为和嵌入字体，即使 Word 里完美。
- 兼容模式会静默限制新特性或改分页。
- 一个页面尺寸或边距默认值的改动，会一路波及表格、页眉、目录、交叉引用。
- 修订流程可能屏幕上看接受，但残留元数据、批注或域缓存仍让文件之后不稳。
- 目录条目、脚注、交叉引用要等接收方更新域后，才可能露出断掉的锚点。

## 交付习惯

- 快读抽取：走结构保持的读取路径，别一上来就改 XML。
- 生改新文件：样式驱动，优先命名样式。
- 编辑存量/被审过的文档：OOXML 感知、最小替换、保序。
- 涉及审阅：经典最小替换，不整段重写。
- 交付前在至少一个「另一款编辑器」心里过一遍往返兼容。

## 相关能力

- 普通文档处理与格式互转、简明商务写作、长文起草与编辑结构，可另行调用对口的通用文档能力。

## 反馈与维护

- 方法随 OOXML 与你常用编辑器（Word / LibreOffice / Google Docs）的版本演进而更新。