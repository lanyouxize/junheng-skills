---
name: pdf
version: 1.0.1
display_name: PDF 文档处理
display_name_en: PDF Document Processing
description: PDF 处理工具箱：提取文本与表格、新建 PDF、合并与拆分文档、填写表单。当用户要读取、生成、拆分合并或填表处理 PDF 时用。
description_zh: PDF 文档处理工具，支持文本与表格提取、PDF 创建、合并拆分、表单填写及批量分析。
description_en: Process PDF documents by extracting text and tables, creating, merging, splitting, filling forms, and performing batch analysis.
license: Proprietary. LICENSE.txt has complete terms
---

# PDF Processing Guide

## Overview

This guide covers essential PDF processing operations using Python libraries and command-line tools. For advanced features, JavaScript libraries, and detailed examples, see reference.md. If you need to fill out a PDF form, read forms.md and follow its instructions.

## Setup and verification

Run commands from this skill directory, or use absolute script paths.
Install Python dependencies with `python -m pip install -r requirements.txt`.
PDF rendering also requires Poppler (`brew install poppler` on macOS, or
`apt-get install poppler-utils` on Debian/Ubuntu).
The bundled form scripts require pypdf 6.21.1 or newer within major version 6;
they do not patch library internals.

After creating or filling a PDF, render the output and inspect the affected
pages for missing text, clipping, incorrect selections and alignment. Re-read
interactive field values as well. A successful write alone is not verification.
For non-interactive forms, use `pages.json` from the image converter to obtain
the displayed page dimensions needed by `fields.json`.

For regression tests, install `requirements-dev.txt` and run
`python -m unittest discover -s scripts -p '*_test.py'`.

## Quick Start

### 需要细节时再读

具体库 API 与 CLI 参数已移到 references/，按当前做法选一个读，不要两个都读：

| 内容 | 何时读 | 文件 |
|------|--------|------|
| Python 库对照 | 要写代码、需要具体库的 API 与代码片段时 | `references/python-libraries.md` |
| 命令行工具 | 走 CLI 而不写代码时 | `references/cli-tools.md` |


```python
from pypdf import PdfReader, PdfWriter

# Read a PDF
reader = PdfReader("document.pdf")
print(f"Pages: {len(reader.pages)}")

# Extract text
text = ""
for page in reader.pages:
    text += page.extract_text()
```

## Common Tasks

### Extract Text from Scanned PDFs
```python
# Requires: pip install pytesseract pdf2image
import pytesseract
from pdf2image import convert_from_path

# Convert PDF to images
images = convert_from_path('scanned.pdf')

# OCR each page
text = ""
for i, image in enumerate(images):
    text += f"Page {i+1}:\n"
    text += pytesseract.image_to_string(image)
    text += "\n\n"

print(text)
```

### Add Watermark
```python
from pypdf import PdfReader, PdfWriter

# Create watermark (or load existing)
watermark = PdfReader("watermark.pdf").pages[0]

# Apply to all pages
reader = PdfReader("document.pdf")
writer = PdfWriter()

for page in reader.pages:
    page.merge_page(watermark)
writer.append(reader)

with open("watermarked.pdf", "wb") as output:
    writer.write(output)
```

### Extract Images
```bash
# Using pdfimages (poppler-utils)
pdfimages -j input.pdf output_prefix

# This extracts all images as output_prefix-000.jpg, output_prefix-001.jpg, etc.
```

### Password Protection
```python
from pypdf import PdfReader, PdfWriter

reader = PdfReader("input.pdf")
writer = PdfWriter()

writer.append(reader)

# Add password
writer.encrypt("userpassword", "ownerpassword")

with open("encrypted.pdf", "wb") as output:
    writer.write(output)
```

## Quick Reference

| Task | Best Tool | Command/Code |
|------|-----------|--------------|
| Merge PDFs | pypdf | `writer.append(reader)`; namespace duplicate form names |
| Split PDFs | pypdf | One page per file |
| Extract text | pdfplumber | `page.extract_text()` |
| Extract tables | pdfplumber | `page.extract_tables()` |
| Create PDFs | reportlab | Canvas or Platypus |
| Command line merge | qpdf | `qpdf --empty --pages ...` |
| OCR scanned PDFs | pytesseract | Convert to image first |
| Fill PDF forms | pdf-lib or pypdf (see forms.md) | See forms.md |

## Next Steps

- For advanced pypdfium2 usage, see reference.md
- For JavaScript libraries (pdf-lib), see reference.md
- If you need to fill out a PDF form, follow the instructions in forms.md
- For troubleshooting guides, see reference.md
