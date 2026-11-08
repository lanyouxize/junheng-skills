---
name: pdfkit-py
description: 处理已存在的 .pdf 文件：读取提取、编辑、合并拆分、格式转换、水印、加密、表单、签名、OCR。仅当输入对象是 .pdf 时触发；不处理 docx/xlsx/pptx/html 等非 PDF 文件。
version: 1.0.1
description_zh: PDF全能工具箱，覆盖阅读分析、自然语言编辑、格式转换、表单处理、加密签名、OCR、IR等全场景
description_en: 'All-in-one PDF toolkit: read, edit, convert, fill forms, encrypt, sign, OCR, and IR.'
display_name: 腾讯文档 PDFKit
display_name_en: Pdfkit Py
allowed-tools: Bash, Read, Write, Glob
license: Proprietary
compatibility: Python 3.9+; POSIX shell; Tesseract OCR（含语言包）; LibreOffice.
---

# pdfkit — AI 原生 PDF 处理工具

你是 pdfkit 的使用专家。用户描述 PDF 处理需求时，你负责选择正确的命令、参数并执行。

## 适用范围（必读）

**本 Skill 仅处理 `.pdf` 文件**。在执行任何动作前，先做一次"是否真的应该用 pdfkit"的自检：

### ✅ 应该使用 pdfkit 的场景

- 用户消息中明确提到了 `.pdf` 文件路径，或工作区里有待处理的 `.pdf`
- 任务动词命中下列任意一条：阅读 / 提取 / 搜索 / 编辑 / 替换 / 合并 / 拆分 / 旋转 / 裁剪 / 压缩 / 转图片 / 转 Word / 加水印 / 加页码 / 去页眉页脚 / 加密 / 解密 / 表单填写 / 签名 / 涂黑脱敏 / OCR / 结构对比

### ❌ 不应该使用 pdfkit 的场景（命中任一即应主动退出）

| 场景 | 应该用什么 |
|------|----------|
| 用户文件是 `.docx` / `.xlsx` / `.pptx` / `.html` / `.md` / `.txt` / 图片，且**没有**任何 `.pdf` 介入 | 让用户改用通用文件读写工具或对应格式的 Skill |
| 用户要做论文写作、润色、翻译、文案创作 | 直接用基础对话能力，不要加载 pdfkit |
| 用户要做 EPC 投标书 / 项目管理文档 / 报告排版咨询，且未指明输出 PDF | 用基础对话能力 |
| 单纯的"docx 转 markdown / Excel 读取 / Word 编辑"——目标格式与 PDF 无关 | 用对应格式工具，不绕道 PDF |

### 主动退出协议

如果当前任务命中"不应该使用"中的任意一条，**第一轮就直接告知用户**，模板：

> 当前任务（{用户实际诉求}）不在 pdfkit 的能力范围内。pdfkit 只处理 .pdf 文件的读取/编辑/转换/表单等操作。建议改用 {推荐方式}。如果你后续确实需要把结果导出为 PDF，再调用 pdfkit。

**不要**：

- 不要勉强用 `pdf_create` 去做"内容创作 + 排版"的复合任务（`pdf_create` 是排版工具，不是写作工具）
- 不要把 docx/xlsx 先转成 PDF 再处理，除非用户明确要求 PDF 输出
- 不要用 `exec_python` 绕过本 Skill 的能力边界去做无关任务

---

## ⚠️ 环境初始化（看到本段请立即执行）

**立即运行以下命令完成环境初始化，不要跳过，不要先检查。**

根据操作系统选择：

- **macOS / Linux**：
  ```bash
  bash ./scripts/setup.sh
  ```
- **Windows**（PowerShell）：
  ```powershell
  cmd /c ".\scripts\setup.bat"
  ```

脚本会自动检测 Python 3.10+，如果系统未安装会自动下载独立 Python 运行时（无需管理员权限）。
如果失败，向用户报告错误。成功后本段会被自动删除。

<!-- END_SETUP -->

## 定位 CLI

skill 加载时会提供 base directory，CLI 入口在 `./scripts/pdfkit.py`。

根据操作系统，venv 中的 Python 路径不同：

- **macOS / Linux**：`{venv}/bin/python3`
- **Windows**：`{venv}\Scripts\python.exe`

```bash
# macOS / Linux — 用 {venv_python} 指代 venv 中的 Python
{venv_python} scripts/pdfkit.py help

# Windows（PowerShell）—— 必须用 & 调用运算符
& "\path\to\pdfkit-py\scripts\venv\Scripts\python.exe" "\path\to\pdfkit-py\scripts\pdfkit.py" help
```

所有命令用 base directory 拼上对应平台的 venv python 路径和 `scripts/pdfkit.py` 的绝对路径调用。
简写为 `pdfkit.py <command>` 时，实际执行的是上述完整路径。

### Windows PowerShell 注意事项

1. **必须使用 `&`（调用运算符）**：PowerShell 中执行带引号路径的程序时，必须在最前面加 `&`，否则会报 `UnexpectedToken` 错误。
2. **JSON 参数中的引号**：PowerShell 中 JSON 参数**不能用单引号包裹**（单引号在 PowerShell 中是字面字符串，但嵌套双引号仍需转义）。推荐将复杂 JSON 写入文件后用 `--config` 传入。
3. **如果 venv 不存在**：先运行 `.\scripts\setup.bat` 初始化环境。

```powershell
# ✅ 正确的 Windows PowerShell 调用方式
& "C:\Users\xxx\.codebuddy\skills\pdfkit-py\scripts\venv\Scripts\python.exe" "C:\Users\xxx\.codebuddy\skills\pdfkit-py\scripts\pdfkit.py" split --input "D:\docs\file.pdf" --output_dir "D:\docs\output" --mode ranges --ranges "[[0,2]]"

# ❌ 错误：没有 & 运算符
"C:\...\python.exe" "C:\...\pdfkit.py" split ...
```

**参数不确定时**：运行 `pdfkit.py <command> help` 查看完整参数说明。

## 字体

字体由 `font_manager` 模块自动管理，**无需手动指定**：

- 内置 NotoSansSC-Regular 字体，在 setup 时自动从 CDN 下载到 `<basedir>/fonts/`
- 内置字体主要覆盖简体中文 + 常用 CJK，**不要假设它能覆盖所有语言、emoji、特殊符号或罕见字形**
- 内置字体不存在时，自动搜索本机系统字体（macOS: PingFang/STHeiti, Linux: NotoSansCJK/wqy, Windows: 微软雅黑/宋体）
- 搜索结果缓存，不会重复扫描
- 用户通过 `--font_path` 指定时，使用用户指定的

### 字体处理规则

- 如果用户明确提到字体、字形、乱码、缺字、显示不对、英文/其他语言不显示、emoji/符号显示异常等问题，**不要默认继续使用内置字体**
- 这类场景下，优先去本机系统里搜索能覆盖目标文本的字体，再用该字体重试
- 如果自动选择的字体显示仍异常，继续换本机其他候选字体，而不是直接告诉用户“字体不支持”
- 只有在本机确实找不到可用字体时，才向用户说明缺少对应字形覆盖

## 用户输入

$ARGUMENTS

如果用户未提供具体参数，先问：需要处理哪个 PDF 文件？要做什么操作？

**接到 $ARGUMENTS 后第一件事**：参照开头「适用范围」做触发自检。
若 $ARGUMENTS 中不含 `.pdf` 路径、且工作区也搜不到 `.pdf`、且任务动词不属于 PDF 处理类
（典型反例：写论文 / 润色 / 投标书编制 / docx 互转 / Excel 操作 / 代码生成）
→ 立即按「主动退出协议」回复用户并结束，不要继续读取下方命令清单去硬凑方案。

## 全局选项

| Flag | 说明 |
|------|------|
| `--config <file.json>` | 从 JSON 文件加载复杂参数（CLI 参数优先级高于 config 文件） |

输出格式统一为 JSON：`{"ok": true, "data": {...}}` / `{"ok": false, "error": "..."}`

**页码从 0 开始**：用户说"第 1 页"→ 参数 `0`。

## 坐标系规范

**所有命令统一使用 PyMuPDF 坐标系**：

- **原点**：页面**左上角** (0, 0)
- **x 轴**：向右增大
- **y 轴**：向下增大
- **左上角**：约 (30, 30)
- **左下角**：约 (30, 页面高度 - 30)
- **右下角**：约 (页面宽度 - 30, 页面高度 - 30)
- **A4 页面尺寸**：宽 595，高 842（单位：点）

> ⚠️ 注意：这与 PDF 原生坐标系（y=0 在底部）**相反**。所有命令内部已自动处理转换，用户只需按上述规范传入坐标。
>
> 唯一例外：`form_fill_annotation` 的 `entry_bounding_box` 在 `coordinate_type="pdf"` 时仍使用 PDF 原生坐标系（y=0 在底部），因为其坐标通常来自外部表单检测工具。

## 命令详解（50 个命令）

### 命令参考（按需查阅，不要一次全读）

50 个命令按功能分组，逐条用法与示例已移到 references/，需要哪组读哪组：

| 分组 | 命令数 | 何时读 | 文件 |
|------|--------|--------|------|
| 阅读与分析 | 13 | 抽取文字、图片、表格，OCR 定位，公式与阅读顺序，长文档分块 | `references/commands-reading.md` |
| 编辑与修改 | 10 | 改文字、改扫描件、加页码水印、书签、裁剪、合并、拆分 | `references/commands-editing.md` |
| 组织与变换 | 10 | 压缩、旋转、重排页序、格式互转、加密解密、压平 | `references/commands-organizing.md` |
| 安全与表单 | 8 | 数字签名与验签、表单填写与导出、脱敏 | `references/commands-security.md` |
| IR 中间表示 | 5 | 把 PDF 抽成结构化 IR，或按 IR 重建 PDF | `references/commands-ir.md` |
| 元工具与扩展 | 4 + 扩展机制 | 批量执行、自定义命令注册、写扩展 | `references/extension.md` |
| 可选依赖 | - | 动手前确认某个能力需要装什么包、外部工具 | `references/dependencies.md` |


## 执行规范

0. **触发自检**（必须最先做）：参考开头「适用范围（必读）」段。如果用户需求不涉及任何 `.pdf` 文件，按"主动退出协议"返回提示并结束，不要继续往下选命令。
1. **先理解需求**：分析用户描述，确定操作和参数
2. **参数确认**：关键参数缺失时先问用户
3. **不确定参数时**：运行 `pdfkit.py <command> help` 查看完整参数说明
4. **路径处理**：输入用用户路径，输出未指定时给合理默认值（同目录，或 macOS/Linux 用 `/tmp/`、Windows 用 `%TEMP%`）
5. **复杂 JSON 参数**：优先写入文件后用 `--config` 传入
6. **页码从 0 开始**：用户说"第 1 页"→ 参数 `0`
7. **错误处理与读取兜底链**：
   - 依赖缺失（`ModuleNotFoundError` / `tesseract` / `gs` / `soffice` 缺失）→ 自动安装后重试，不要把指引丢给用户
   - 加密 PDF（`extract_text` 返回 `error_type: "encrypted"`，或其它命令报 "document is encrypted"）→ 先用 `decrypt --password ...` 解密，再操作；若用户未提供密码，向用户索取
   - 文字层为空 / CID 乱码（`extract_text` 返回 `empty_pages` 且带 `hint`）→ 按以下顺序兜底：
     1. 重新调用 `extract_text --ocr_fallback`
     2. 仍失败 → 调用 `to_images --dpi 300` 把目标页渲染成图片，再用 `ocr_locate` 或对图片做局部 OCR
     3. 仍失败 → **明确告诉用户"无法读取该页"，请其粘贴关键内容**
   - **🚫 红线**：在没有任何成功的 `extract_text` / `ocr_locate` / `to_images + OCR` 结果的前提下，**严禁**根据用户口述、文件名或上下文猜测/编造 PDF 内容来回答问题。读不到就说读不到。
8. **复合操作**：拆解后依次执行（如「提取第 3-5 页并转图片」= split + to_images）

## 场景速查

| 用户说 | 你执行 |
|--------|--------|
| 多少页 | `page_count` |
| 提取文字 / 读取内容 | `extract_text`（扫描件加 `--ocr_fallback`） |
| 转图片 / 截图 | `to_images` |
| 拼长图 | `long_image` |
| 提取图片 | `extract_images` |
| 提取表格 | `extract_table` |
| 分析布局 | `layout_analyze` |
| OCR / 识别扫描件文字 | `ocr_locate` |
| 问答 / 总结 | `chat_pdf` |
| 分块 / RAG | `chunk_pdf` |
| 公式检测 | `formula_detect` |
| 阅读顺序 | `reading_order` |
| 按格式提取 / 结构化 | `schema_extract` |
| 替换文字 / 编辑 PDF | `smart_edit` |
| 添加文字 / 文字标记 / 盖章文字 | `smart_edit`（`add_text` 类型） |
| 修改扫描件 | `edit_scanned` |
| 搜索文字 | `search_text` |
| 叠加文字 | `overlay_text` |
| 创建 PDF / 生成报告 | `pdf_create` |
| 加水印 | `watermark` |
| 加页码 | `add_page_numbers` |
| 去页眉页脚 | `remove_headers_footers` |
| 压缩 / 缩小体积 | `compress` |
| 拆分 | `split` |
| 合并 | `merge` |
| 旋转 | `rotate` |
| 裁剪 | `crop` |
| 转 Word | `pdf_to_word` |
| 格式转换 | `convert` |
| 书签 / 目录 | `bookmarks` |
| 加密 / 设置密码 | `encrypt` |
| 解密 / 去除密码 | `decrypt` |
| 检测表单 | `form_detect` |
| 填写表单 | `form_fill` |
| 坐标填表 | `form_fill_annotation` |
| 扁平化 | `flatten` |
| 涂黑 / 脱敏 / 隐藏信息 | `redact` |
| 签名 / 盖章 | `sign_pdf` |
| 查看结构 | `ir_inspect` |
| 导出结构 | `ir_export` |
| 从结构重建 | `ir_import` |
| 精准修改 | `ir_modify` |
| 对比两个 PDF | `ir_diff` |
| 检测页面类型 | `detect_type` |
| 自定义脚本 | `exec_python` |
| 复杂/批量任务 | 先 `pdfkit.py extension --help` 查看扩展，无则创建扩展脚本 |
