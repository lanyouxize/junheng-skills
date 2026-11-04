# 命令详解 · 安全与表单（8 个）

## 安全与表单 (8)

### encrypt — 加密

```bash
pdfkit.py encrypt --input doc.pdf --output out.pdf --user_password "secret"
pdfkit.py encrypt --input doc.pdf --output out.pdf \
  --user_password "read" --owner_password "admin" --allow_print --allow_copy
```

| Flag | 说明 |
|------|------|
| `--input` | **必填** 输入 PDF 路径 |
| `--output` | **必填** 输出 PDF 路径 |
| `--user_password` | **必填** 用户密码 |
| `--owner_password` | 所有者密码 |
| `--allow_print` | 允许打印，默认 `True` |
| `--allow_modify` | 允许修改，默认 `False` |
| `--allow_copy` | 允许复制，默认 `False` |

### decrypt — 解密

```bash
pdfkit.py decrypt --input encrypted.pdf --output out.pdf --password "secret"
```

| Flag | 说明 |
|------|------|
| `--input` | **必填** 输入 PDF 路径 |
| `--output` | **必填** 输出 PDF 路径 |
| `--password` | **必填** 密码 |

### form_detect — 检测表单

```bash
pdfkit.py form_detect --input form.pdf
```

| Flag | 说明 |
|------|------|
| `--input` | **必填** 输入 PDF 路径 |
| `--extract_structure` | 提取表单结构，默认 `True` |

### form_fill — 填写表单

```bash
pdfkit.py form_fill --input form.pdf --output filled.pdf \
  --fields '[{"field_id":"name","value":"张三"},{"field_id":"date","value":"2026-01-01"}]'
```

| Flag | 说明 |
|------|------|
| `--input` | **必填** 输入 PDF 路径 |
| `--output` | **必填** 输出 PDF 路径 |
| `--fields` | **必填** 字段值列表 JSON `[{"field_id":"...","value":"..."}]` |

### form_fill_annotation — 注释方式填表

```bash
pdfkit.py form_fill_annotation --input form.pdf --output filled.pdf \
  --form_fields '[{"page":0,"x":100,"y":200,"text":"张三","font_size":12}]'
```

| Flag | 说明 |
|------|------|
| `--input` | **必填** 输入 PDF 路径 |
| `--output` | **必填** 输出 PDF 路径 |
| `--coordinate_type` | 坐标类型，默认 `pdf`。可选 `pdf` / `image` |
| `--pages` | 页码列表 JSON |
| `--form_fields` | **必填** 填写字段列表 JSON |

### flatten — 扁平化

```bash
pdfkit.py flatten --input form.pdf --output flat.pdf
pdfkit.py flatten --input doc.pdf --output flat.pdf --flatten_annotations --pages '[0,1]'
```

| Flag | 说明 |
|------|------|
| `--input` | **必填** 输入 PDF 路径 |
| `--output` | **必填** 输出 PDF 路径 |
| `--flatten_forms` | 扁平化表单，默认 `True` |
| `--flatten_annotations` | 扁平化注释，默认 `True` |
| `--pages` | 页码列表 JSON |

### redact — 涂黑脱敏

```bash
# 按文本涂黑
pdfkit.py redact --input doc.pdf --output out.pdf \
  --redactions '[{"type":"text","text":"身份证号","page":-1}]'

# 按区域涂黑
pdfkit.py redact --input doc.pdf --output out.pdf \
  --redactions '[{"type":"area","rect":[100,200,300,230],"page":0}]'

# 按正则涂黑
pdfkit.py redact --input doc.pdf --output out.pdf \
  --redactions '[{"type":"regex","pattern":"\\d{18}","page":-1}]'
```

| Flag | 说明 |
|------|------|
| `--input` | **必填** 输入 PDF 路径 |
| `--output` | **必填** 输出 PDF 路径 |
| `--redactions` | **必填** 涂黑规则列表 JSON |
| `--fill_color` | 填充颜色 JSON，默认 `[0,0,0]`（黑色） |

redactions 支持的类型：

| type | 字段 |
|------|------|
| `text` | `text`, `page`（-1=所有页） |
| `area` | `rect` `[left, top, right, bottom]`, `page` |
| `regex` | `pattern`, `page` |

### sign_pdf — 数字签名

```bash
pdfkit.py sign_pdf --input doc.pdf --output signed.pdf \
  --signature '{"text":"张三","position":"bottom_right"}'

pdfkit.py sign_pdf --input doc.pdf --output signed.pdf \
  --signature '{"image":"seal.png","position":[400,50],"width":150,"height":60}' \
  --pages '[0]'
```

| Flag | 说明 |
|------|------|
| `--input` | **必填** 输入 PDF 路径 |
| `--output` | **必填** 输出 PDF 路径 |
| `--signature` | **必填** 签名配置 JSON |
| `--pages` | 页码列表 JSON |

signature 字段：

| 字段 | 说明 |
|------|------|
| `image` | 签章图片路径 |
| `text` | 签名文字 |
| `position` | `"bottom_right"` 等预设位置，或 `[x, y]` 坐标 |
| `width` | 宽度，默认 `150` |
| `height` | 高度，默认 `60` |
| `font_size` | 字号，默认 `10` |
| `opacity` | 透明度，默认 `1.0` |

---
