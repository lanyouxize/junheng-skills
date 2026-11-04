# 命令详解 · 阅读与分析（13 个）

## 阅读与分析 (13)

### page_count — 获取 PDF 页数

```bash
pdfkit.py page_count --input doc.pdf
```

| Flag | 说明 |
|------|------|
| `--input` | **必填** 输入 PDF 路径 |

### extract_text — 提取文本

> 💡 **支持自动 OCR 降级**：添加 `--ocr_fallback` 参数后，**纯扫描件页面**（完全无文字层）会自动使用 OCR 提取文字。
> **混合型页面**（有文字层 + 嵌入图片）仅提取文字层文本，图片上的文字**不会**被 OCR 提取。
> 不加 `--ocr_fallback` 时，扫描件页面会返回空并给出提示。

```bash
# 基本用法（仅提取文字层）
pdfkit.py extract_text --input doc.pdf --pages '[0,1]'

# 自动 OCR 降级（推荐：一次调用覆盖所有场景）
pdfkit.py extract_text --input scan.pdf --pages '[0]' --ocr_fallback

# 指定输出格式
pdfkit.py extract_text --input doc.pdf --format html --output /tmp/out.html
```

| Flag | 说明 |
|------|------|
| `--input` | **必填** 输入 PDF 路径 |
| `--pages` | 页码列表 JSON，如 `[0,1,3]` |
| `--output` | 输出文件路径 |
| `--format` | 输出格式，默认 `text`。可选 `text` / `dict` / `blocks` / `words` / `html` |
| `--ocr_fallback` | 自动 OCR 降级，默认 `False`。仅对纯扫描件页面（无文字层）自动 OCR，混合型页面中图片上的文字不提取（需要 tesseract） |
| `--lang` | OCR 语言，默认 `eng+chi_sim`（仅 `--ocr_fallback` 时生效） |

### to_images — 页面转图片

```bash
pdfkit.py to_images --input doc.pdf --output_dir /tmp/imgs/ --dpi 300
```

| Flag | 说明 |
|------|------|
| `--input` | **必填** 输入 PDF 路径 |
| `--output_dir` | **必填** 输出目录 |
| `--pages` | 页码列表 JSON |
| `--dpi` | 分辨率，默认 `150` |
| `--format` | 图片格式，默认 `png`。可选 `png` / `jpeg` |

### long_image — 多页拼接长图

```bash
pdfkit.py long_image --input doc.pdf --output /tmp/long.png
pdfkit.py long_image --input doc.pdf --output /tmp/long.png --pages '[0,1,2]' --gap 10
```

| Flag | 说明 |
|------|------|
| `--input` | **必填** 输入 PDF 路径 |
| `--output` | **必填** 输出图片路径 |
| `--pages` | 页码列表 JSON |
| `--dpi` | 分辨率，默认 `150` |
| `--gap` | 页间距像素，默认 `0` |

### extract_images — 提取内嵌图片

```bash
pdfkit.py extract_images --input doc.pdf --output_dir /tmp/imgs/
```

| Flag | 说明 |
|------|------|
| `--input` | **必填** 输入 PDF 路径 |
| `--output_dir` | **必填** 输出目录 |
| `--pages` | 页码列表 JSON |
| `--min_size` | 最小尺寸（像素），默认 `100` |

### extract_table — 提取表格

```bash
pdfkit.py extract_table --input doc.pdf --format markdown
pdfkit.py extract_table --input doc.pdf --pages '[0]' --format csv --output /tmp/table.csv
```

| Flag | 说明 |
|------|------|
| `--input` | **必填** 输入 PDF 路径 |
| `--pages` | 页码列表 JSON |
| `--format` | 输出格式，默认 `json`。可选 `csv` / `json` / `markdown` |
| `--output` | 输出文件路径 |
| `--method` | 提取方法，默认 `auto`。可选 `auto` / `lattice` / `stream` |
| `--header` | 是否将第一行作为表头，默认 `False`（原样输出所有行）。有表头行的表格传 `--header` |

### layout_analyze
```bash
pdfkit.py layout_analyze --input doc.pdf --pages '[0]' --detail full
```

| Flag | 说明 |
|------|------|
| `--input` | **必填** 输入 PDF 路径 |
| `--pages` | 页码列表 JSON |
| `--detail` | 详细程度，默认 `basic`。可选 `basic` / `full` |

### ocr_locate — OCR 定位文字

> 需要 `tesseract`

```bash
pdfkit.py ocr_locate --input scan.pdf --page 0 --text "合同编号"
```

| Flag | 说明 |
|------|------|
| `--input` | **必填** 输入 PDF 路径 |
| `--page` | 页码，默认 `0` |
| `--text` | 要定位的文字 |
| `--lang` | OCR 语言，默认 `eng+chi_sim` |

### chat_pdf — PDF 问答上下文提取

```bash
pdfkit.py chat_pdf --input doc.pdf --question "主要结论是什么"
```

| Flag | 说明 |
|------|------|
| `--input` | **必填** 输入 PDF 路径 |
| `--question` | 问题 |
| `--pages` | 页码列表 JSON |
| `--max_context_chars` | 最大上下文字数，默认 `8000` |

### chunk_pdf — 文档分块

```bash
pdfkit.py chunk_pdf --input doc.pdf --strategy paragraph
pdfkit.py chunk_pdf --input doc.pdf --strategy fixed --chunk_size 500 --overlap 100
```

| Flag | 说明 |
|------|------|
| `--input` | **必填** 输入 PDF 路径 |
| `--strategy` | 分块策略，默认 `paragraph`。可选 `page` / `paragraph` / `fixed` / `semantic` |
| `--chunk_size` | 块大小，默认 `1000` |
| `--overlap` | 重叠字数，默认 `200` |
| `--pages` | 页码列表 JSON |

### formula_detect — 数学公式检测

```bash
pdfkit.py formula_detect --input paper.pdf --pages '[0,1]'
```

| Flag | 说明 |
|------|------|
| `--input` | **必填** 输入 PDF 路径 |
| `--pages` | 页码列表 JSON |
| `--method` | 检测方法，默认 `heuristic`。可选 `heuristic` / `model` |

### reading_order — 阅读顺序检测

```bash
pdfkit.py reading_order --input doc.pdf --pages '[0]'
```

| Flag | 说明 |
|------|------|
| `--input` | **必填** 输入 PDF 路径 |
| `--pages` | 页码列表 JSON |

### schema_extract — Schema 结构化提取

```bash
pdfkit.py schema_extract --input invoice.pdf \
  --schema '{"invoice_no":"string","date":"string","items":[{"name":"string","amount":"number"}]}'
```

| Flag | 说明 |
|------|------|
| `--input` | **必填** 输入 PDF 路径 |
| `--schema` | **必填** 目标结构 JSON |
| `--pages` | 页码列表 JSON |

---
