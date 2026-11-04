# 可选依赖（Python 包与系统外部工具）

## 可选依赖

核心依赖在 setup 脚本首次运行时已安装。以下依赖**按需安装**——**当命令执行报错提示缺少某个包时，你应该自动用 venv 内的 pip 安装它，然后重试原命令，不要把安装指引丢给用户。**

### Python 可选包

pip 路径：

- **macOS / Linux**：`{venv_pip} install {package_name}`
- **Windows**：`.\scripts\venv\Scripts\pip.exe install <包名>`

| 包名 | 涉及命令 | 安装命令 |
|------|---------|---------|
| `camelot-py[cv]` | extract_table（lattice/stream 方法） | `pip install "camelot-py[cv]"` |
| `tabula-py` | extract_table（tabula 方法） | `pip install tabula-py` |
| `pdf2docx` | pdf_to_word（pdf2docx 方法） | `pip install pdf2docx` |
| `pikepdf` | compress（高级压缩优化） | `pip install pikepdf` |
| `pix2tex` | formula_detect（model 方法） | `pip install pix2tex` |

**安装流程**：执行命令 → 报错含 `ModuleNotFoundError` 或 `ImportError` → 用 venv pip 安装对应包 → 重试原命令。

### 系统外部工具

无需预装。**当命令执行报错提示缺少以下工具时，你应该自动执行对应的安装命令，安装完成后重试原命令，不要把安装指引丢给用户，也不要先反问用户要不要安装。**

| 工具 | 用途 | 涉及命令 | macOS 安装 | Windows 安装 | Linux 安装 |
|------|------|---------|-----------|-------------|-----------|
| `gs` | PDF 压缩 | compress | `brew install ghostscript` | `winget install ArtifexSoftware.GhostScript --accept-package-agreements --accept-source-agreements` | `sudo apt install -y ghostscript` |
| `tesseract` | OCR 识别 | smart_edit, edit_scanned, ocr_locate, search_text, extract_text | `brew install tesseract` | `winget install UB-Mannheim.TesseractOCR --accept-package-agreements --accept-source-agreements` | `sudo apt install -y tesseract-ocr` |
| `tesseract-lang` | OCR 中文语言包 | 同上（涉及中文 PDF 时需要） | `brew install tesseract-lang` | 安装 tesseract 时已包含 | `sudo apt install -y tesseract-ocr-chi-sim` |
| `soffice` | 格式转换 | convert, pdf_to_word | `brew install --cask libreoffice` | `winget install TheDocumentFoundation.LibreOffice --accept-package-agreements --accept-source-agreements` | `sudo apt install -y libreoffice` |

**安装流程**：执行命令 → 报错含"未找到 xxx 命令"或"语言包缺失" → 根据当前 OS 执行上表对应安装命令 → 重试原命令。

**OCR 特别规则**：

- 只要用户意图是编辑扫描件、OCR 定位、OCR 搜索、扫描件提取文本，且命令报缺少 `tesseract` 或语言包，就直接安装，不要询问用户是否安装
- 对应命令包括：`smart_edit`（扫描件路径）、`edit_scanned`、`ocr_locate`、`search_text --engine ocr`、`extract_text --ocr_fallback`
- 用户说“修改扫描件”“改图片里的字”“识别扫描 PDF”“OCR 找字”时，默认视为允许安装 OCR 依赖
- 只有安装命令本身失败、缺少管理员权限、或系统包管理器不可用时，才向用户报告阻塞点

---
