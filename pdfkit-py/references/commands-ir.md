# 命令详解 · IR 中间表示（5 个）

## IR 中间表示 (5)

### ir_export — 导出 PDF 结构为 JSON

```bash
pdfkit.py ir_export --input doc.pdf --output structure.json
pdfkit.py ir_export --input doc.pdf --output structure.json --include_images --include_fonts
```

| Flag | 说明 |
|------|------|
| `--input` | **必填** 输入 PDF 路径 |
| `--output` | **必填** JSON 输出路径 |
| `--pages` | 页码列表 JSON |
| `--include_images` | 包含图片数据，默认 `False` |
| `--include_fonts` | 包含字体信息，默认 `False` |

### ir_import — 从 JSON 重建 PDF

```bash
pdfkit.py ir_import --input structure.json --output rebuilt.pdf
```

| Flag | 说明 |
|------|------|
| `--input` | **必填** IR JSON 路径 |
| `--output` | **必填** 输出 PDF 路径 |

### ir_inspect — 结构摘要

```bash
pdfkit.py ir_inspect --input doc.pdf
pdfkit.py ir_inspect --input doc.pdf --pages '[0]'
```

| Flag | 说明 |
|------|------|
| `--input` | **必填** 输入 PDF 路径 |
| `--pages` | 页码列表 JSON |

### ir_modify — 精准修改

```bash
pdfkit.py ir_modify --input doc.pdf --output out.pdf \
  --operations '[{"type":"replace_text","page":0,"find":"旧文本","replace":"新文本"}]'
```

| Flag | 说明 |
|------|------|
| `--input` | **必填** 输入 PDF 路径 |
| `--output` | **必填** 输出 PDF 路径 |
| `--operations` | **必填** 操作列表 JSON |

operations 支持的类型：

| type | 字段 |
|------|------|
| `replace_text` | `page`, `find`, `replace` |
| `replace_image` | `page`, `image_index`, `new_image`（图片路径） |
| `add_annotation` | `page`, `annot_type`（如 `freetext`）, `rect` `[x,y,x2,y2]`, `content` |

### ir_diff — 对比差异

```bash
pdfkit.py ir_diff --left old.pdf --right new.pdf
pdfkit.py ir_diff --left old.pdf --right new.pdf --output diff.json --text_only
```

| Flag | 说明 |
|------|------|
| `--left` | **必填** 左侧 PDF 路径 |
| `--right` | **必填** 右侧 PDF 路径 |
| `--output` | 输出路径 |
| `--text_only` | 仅对比文本，默认 `False` |

---
