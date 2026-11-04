# 命令详解 · 组织与变换（10 个）

## 组织与变换 (10)

### compress — 压缩 PDF

```bash
pdfkit.py compress --input doc.pdf --output out.pdf --quality ebook
pdfkit.py compress --input doc.pdf --output out.pdf --target_size_mb 5
```

| Flag | 说明 |
|------|------|
| `--input` | **必填** 输入 PDF 路径 |
| `--output` | **必填** 输出 PDF 路径 |
| `--quality` | 压缩质量，默认 `ebook`。可选 `screen` / `ebook` / `printer` / `prepress` |
| `--target_size_mb` | 目标大小（MB） |

### split — 拆分 PDF

```bash
pdfkit.py split --input doc.pdf --output_dir /tmp/split/
pdfkit.py split --input doc.pdf --output_dir /tmp/split/ --mode ranges --ranges '[[0,2],[3,5]]'
```

| Flag | 说明 |
|------|------|
| `--input` | **必填** 输入 PDF 路径 |
| `--output_dir` | **必填** 输出目录 |
| `--mode` | 拆分模式，默认 `each`。可选 `each`（每页一个） / `ranges`（按范围） |
| `--ranges` | 范围 JSON `[[0,2],[3,5]]`，`mode=ranges` 时使用 |

### merge — 合并 PDF

```bash
pdfkit.py merge --inputs '["a.pdf","b.pdf"]' --output merged.pdf
```

| Flag | 说明 |
|------|------|
| `--inputs` | **必填** 输入文件列表 JSON |
| `--output` | **必填** 输出 PDF 路径 |

### rotate — 旋转页面

```bash
pdfkit.py rotate --input doc.pdf --output out.pdf --angle 90
pdfkit.py rotate --input doc.pdf --output out.pdf --angle 180 --pages '[0,2]'
```

| Flag | 说明 |
|------|------|
| `--input` | **必填** 输入 PDF 路径 |
| `--output` | **必填** 输出 PDF 路径 |
| `--angle` | 旋转角度，默认 `90`。可选 `90` / `180` / `270` / `-90` / `-180` / `-270` |
| `--pages` | 页码列表 JSON |

### crop — 裁剪页面

```bash
# 裁剪第一页，保留左上角 400x500 区域
pdfkit.py crop --input doc.pdf --output out.pdf --left 0 --top 0 --right 400 --bottom 500
```

| Flag | 说明 |
|------|------|
| `--input` | **必填** 输入 PDF 路径 |
| `--output` | **必填** 输出 PDF 路径 |
| `--left` | 裁剪区左边界 x，默认 `0` |
| `--top` | 裁剪区上边界 y，默认 `0`（页面顶部） |
| `--right` | 裁剪区右边界 x，默认 `612` |
| `--bottom` | 裁剪区下边界 y，默认 `792`（页面底部） |
| `--pages` | 页码列表 JSON |

坐标使用统一坐标系（左上角原点，y↓）。

### convert — 格式转换

```bash
pdfkit.py convert --input doc.pdf --output doc.docx --to_format docx
pdfkit.py convert --input doc.html --output doc.pdf --to_format pdf
```

| Flag | 说明 |
|------|------|
| `--input` | **必填** 输入文件路径 |
| `--output` | **必填** 输出文件路径 |
| `--from_format` | 源格式，默认 `auto`。可选 `auto` / `pdf` / `docx` / `html` / `md` / `images` |
| `--to_format` | 目标格式。可选 `pdf` / `docx` / `html` / `md` / `images` |

### pdf_to_word — PDF 转 Word

```bash
pdfkit.py pdf_to_word --input doc.pdf --output doc.docx
pdfkit.py pdf_to_word --input doc.pdf --output doc.docx --pages '[0,5]'
```

| Flag | 说明 |
|------|------|
| `--input` | **必填** 输入 PDF 路径 |
| `--output` | **必填** 输出 Word 路径 |
| `--pages` | 页码范围 JSON `[start, end]` |
| `--method` | 转换方法，默认 `auto`。可选 `auto` / `pdf2docx` / `libreoffice` |

### bookmarks — 书签管理

```bash
# 获取书签
pdfkit.py bookmarks --action get --input doc.pdf

# 设置书签
pdfkit.py bookmarks --action set --input doc.pdf --output out.pdf \
  --bookmarks '[{"level":1,"title":"第一章","page":0},{"level":2,"title":"1.1 节","page":2}]'
```

| Flag | 说明 |
|------|------|
| `--input` | **必填** 输入 PDF 路径 |
| `--action` | 操作，默认 `get`。可选 `get` / `set` |
| `--output` | `action=set` 时必填，输出路径 |
| `--bookmarks` | 书签列表 JSON `[{"level":1,"title":"...","page":0}]` |
| `--mode` | 设置模式，默认 `replace`。可选 `replace` / `append` |

---
