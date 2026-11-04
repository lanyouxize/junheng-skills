# 命令详解 · 编辑与修改（10 个）

## 编辑与修改 (10)

### smart_edit — 智能编辑（自动判断文字层/扫描件）

```bash
# 替换文本（所有页）
pdfkit.py smart_edit --input doc.pdf --output out.pdf \
  --edits '[{"type":"replace_text","find":"旧文本","replace":"新文本","page":-1}]'

# 添加文本
pdfkit.py smart_edit --input doc.pdf --output out.pdf \
  --edits '[{"type":"add_text","text":"新文本","x":100,"y":200,"page":0}]'

# 预览模式
pdfkit.py smart_edit --input doc.pdf --output out.pdf --dry_run \
  --edits '[{"type":"replace_text","find":"旧","replace":"新"}]'
```

| Flag | 说明 |
|------|------|
| `--input` | **必填** 输入 PDF 路径 |
| `--output` | **必填** 输出 PDF 路径 |
| `--edits` | **必填** 编辑操作列表 JSON |
| `--dry_run` | 预览模式，不实际修改，默认 `False` |

edits 支持的操作类型：

| type | 字段 |
|------|------|
| `replace_text` | `find`, `replace`, `page`（-1=所有页），`color`（可选，[r,g,b] 0-1 范围） |
| `add_text` | `text`, `x`, `y`（坐标原点在页面**左上角**，y 向下增大；左上角≈y:30，左下角≈y:页高-30）, `page`, `font_size`（默认12）, `color`（可选，[r,g,b] 0-1 范围，如红色 [1,0,0]） |
| `delete_text` | `find`, `page` |
| `replace_image` | `page`, `image_index`, `new_image`（图片路径） |

### pymupdf_edit — 文字层文本编辑

```bash
pdfkit.py pymupdf_edit --input doc.pdf --output out.pdf \
  --edits '[{"find":"旧","replace":"新","page":0}]'
```

| Flag | 说明 |
|------|------|
| `--input` | **必填** 输入 PDF 路径 |
| `--output` | **必填** 输出 PDF 路径 |
| `--edits` | **必填** 编辑操作列表 JSON |

### edit_scanned — 扫描件编辑

> 需要 `tesseract`

```bash
pdfkit.py edit_scanned --input scan.pdf --output out.pdf \
  --page 0 --find "旧文本" --replace "新文本" --font fonts/DroidSansFallback.ttf
```

| Flag | 说明 |
|------|------|
| `--input` | **必填** 输入 PDF 路径 |
| `--output` | **必填** 输出 PDF 路径 |
| `--page` | 页码，默认 `0` |
| `--find` | **必填** 查找文本 |
| `--replace` | **必填** 替换文本 |
| `--font` | 字体路径（中文需指定） |
| `--lang` | OCR 语言，默认 `eng+chi_sim` |

### search_text — 文本搜索

```bash
pdfkit.py search_text --input doc.pdf --find "关键词"
pdfkit.py search_text --input doc.pdf --find "关键词" --page 0 --engine fuzzy
```

| Flag | 说明 |
|------|------|
| `--input` | **必填** 输入 PDF 路径 |
| `--find` | **必填** 搜索文本 |
| `--page` | 页码，默认 `-1`（全部页） |
| `--engine` | 搜索引擎，默认 `auto`。可选 `pymupdf` / `pdfplumber` / `fuzzy` / `ocr` / `auto` |

### overlay_text — 文本覆盖

```bash
pdfkit.py overlay_text --input doc.pdf --output out.pdf \
  --overlays '[{"page":0,"bbox":[100,30,300,60],"text":"覆盖文本","font_size":12}]'
```

| Flag | 说明 |
|------|------|
| `--input` | **必填** 输入 PDF 路径 |
| `--output` | **必填** 输出 PDF 路径 |
| `--overlays` | **必填** 覆盖配置列表 JSON `[{page, bbox, text, font_size, color, bg_color}]`。bbox 格式 `[x0,y0,x1,y1]` 使用统一坐标系（左上角原点，y↓） |

### pdf_create — 创建 PDF

```bash
pdfkit.py pdf_create --output report.pdf \
  --elements '[{"type":"heading","text":"标题"},{"type":"paragraph","text":"正文"}]' \
  --font_path fonts/DroidSansFallback.ttf

pdfkit.py pdf_create --output report.pdf \
  --elements '[{"type":"heading","text":"报告"},{"type":"paragraph","text":"内容"}]' \
  --page_size A4 --watermark '{"text":"草稿"}'
```

| Flag | 说明 |
|------|------|
| `--output` | **必填** 输出 PDF 路径 |
| `--elements` | **必填** 元素列表 JSON `[{type, text, ...}]` |
| `--page_size` | 页面大小，默认 `A4`。可选 `A4` / `A3` / `letter` / `legal` |
| `--orientation` | 方向，默认 `portrait` |
| `--font_path` | 字体路径（中文需指定） |
| `--margins` | 边距 JSON |
| `--header` | 页眉 JSON |
| `--footer` | 页脚 JSON |
| `--watermark` | 水印 JSON |
| `--title` | 文档标题 |
| `--author` | 作者 |

### watermark — 添加水印

```bash
# 自动搜索字体（推荐）
pdfkit.py watermark --input doc.pdf --output out.pdf --text "机密"

# 指定字体
pdfkit.py watermark --input doc.pdf --output out.pdf \
  --text "机密" --font_path /path/to/font.ttf

# 密集模式 + 自定义样式
pdfkit.py watermark --input doc.pdf --output out.pdf \
  --text "CONFIDENTIAL" --mode dense --opacity 0.1 --angle 30
```

| Flag | 说明 |
|------|------|
| `--input` | **必填** 输入 PDF 路径 |
| `--output` | **必填** 输出 PDF 路径 |
| `--text` | **必填** 水印文本 |
| `--font_path` | 字体路径（不指定则自动搜索） |
| `--mode` | 水印模式，默认 `sparse`。可选 `sparse` / `dense` |
| `--font_color` | 字体颜色，默认 `#CCCCCC` |
| `--angle` | 旋转角度，默认 `45` |
| `--opacity` | 透明度，默认 `0.15` |
| `--font_size` | 字号，默认 `50` |
| `--x_gap` | dense 模式水平间距，默认 `200` |
| `--y_gap` | dense 模式垂直间距，默认 `150` |

### add_page_numbers — 添加页码

```bash
pdfkit.py add_page_numbers --input doc.pdf --output out.pdf
pdfkit.py add_page_numbers --input doc.pdf --output out.pdf \
  --position bottom_right --format "第 {page} 页 / 共 {total} 页" \
  --font_path fonts/DroidSansFallback.ttf
```

| Flag | 说明 |
|------|------|
| `--input` | **必填** 输入 PDF 路径 |
| `--output` | **必填** 输出 PDF 路径 |
| `--position` | 位置，默认 `bottom_center`。可选 `bottom_center` / `bottom_left` / `bottom_right` / `top_center` / `top_left` / `top_right` |
| `--format` | 格式字符串，默认 `"{page} / {total}"` |
| `--start_number` | 起始页码，默认 `1` |
| `--font_size` | 字号，默认 `10` |
| `--font_color` | 颜色 JSON，默认 `[0,0,0]` |
| `--margin` | 边距（点），默认 `36` |
| `--pages` | 页码列表 JSON |
| `--font_path` | 字体路径（中文页码需指定） |

### remove_headers_footers — 清除页眉页脚

```bash
# 仅识别
pdfkit.py remove_headers_footers --input doc.pdf --extract_only

# 清除
pdfkit.py remove_headers_footers --input doc.pdf --output clean.pdf
```

| Flag | 说明 |
|------|------|
| `--input` | **必填** 输入 PDF 路径 |
| `--output` | 清除模式下必填，输出路径 |
| `--pages` | 页码列表 JSON |
| `--header_ratio` | 页眉区域比例，默认 `0.08` |
| `--footer_ratio` | 页脚区域比例，默认 `0.08` |
| `--extract_only` | 仅识别不清除，默认 `False` |

---
