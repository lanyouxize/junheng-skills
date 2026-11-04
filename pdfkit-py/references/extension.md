# 元工具与扩展机制

## 元工具 (4)

### detect_type — 检测页面类型

```bash
pdfkit.py detect_type --input doc.pdf
pdfkit.py detect_type --input doc.pdf --pages '[0,1]'
```

| Flag | 说明 |
|------|------|
| `--input` | **必填** 输入 PDF 路径 |
| `--pages` | 页码列表 JSON |

### exec_python — 沙箱执行 Python

> 最后手段，仅当现有命令无法完成时使用。

```bash
pdfkit.py exec_python --code 'import fitz; doc=fitz.open("doc.pdf"); print(len(doc))'
```

| Flag | 说明 |
|------|------|
| `--code` | **必填** Python 代码 |
| `--timeout` | 超时秒数，默认 `120` |

### layout_engine — 排版引擎

内部使用，一般不直接调用。

---

## 扩展机制（Extension）

当内置的命令无法满足复杂需求时（如多步骤批处理流程、特殊格式转换、业务定制逻辑等），可以通过**扩展脚本**来扩充能力。

### 工作原理

扩展脚本放在 skill basedir 的 `../pdfkit-extension/scripts/` 目录下，与内置命令遵循**完全相同的接口约定**（COMMAND、DESCRIPTION、PARAMS、handler），由 `pdfkit.py` 自动发现和注册。

```
/path/to/skills/                        ← skill basedir 的父目录
├── pdfkit-py/                          ← pdfkit skill 目录（skill basedir）
│   ├── scripts/
│   │   ├── pdfkit.py                   ← 入口（自动扫描扩展）
│   │   └── pdfkit/commands/            ← 内置 50 个命令
│   └── ...
└── pdfkit-extension/                   ← 扩展目录（用户创建，与 pdfkit-py 同级）
    └── scripts/
        ├── batch_watermark.py          ← 扩展脚本 1
        ├── invoice_extract.py          ← 扩展脚本 2
        └── ...
```

### 查看可用扩展

```bash
pdfkit.py extension --help
```

### 使用扩展命令

扩展命令可以像内置命令一样直接调用：

```bash
# 直接调用
pdfkit.py batch_watermark --input_dir /tmp/pdfs --text "机密"

# 通过 extension 子命令调用
pdfkit.py extension batch_watermark --input_dir /tmp/pdfs --text "机密"

# 查看扩展命令帮助
pdfkit.py batch_watermark help
```

### 创建扩展脚本

1. 创建扩展目录：
```bash
mkdir -p <skill basedir>/../pdfkit-extension/scripts
```

2. 复制模板：将 `scripts/pdfkit/extension_template.py` 复制到扩展目录并重命名。

3. 编辑脚本，修改 `COMMAND`、`DESCRIPTION`、`PARAMS` 和 `handler` 函数。

### 扩展脚本模板结构

```python
COMMAND = "my_extension"              # 命令名
DESCRIPTION = "我的自定义 PDF 扩展"     # 描述
CATEGORY = "extension"                # 分类
PARAMS = [
    {"name": "input", "type": "str", "required": True, "help": "输入 PDF"},
    {"name": "output", "type": "str", "required": True, "help": "输出 PDF"},
]

def handler(params):
    # 处理逻辑...
    return {"message": "done", "output": params["output"]}
```

### 适用场景

| 场景 | 说明 |
|------|------|
| 批量处理流程 | 如批量加水印、批量压缩、批量转格式 |
| 多步骤组合 | 如先提取 → 处理 → 重新生成的 pipeline |
| 业务定制 | 如发票批量解析、合同模板填充、报告自动生成 |
| 实验性功能 | 在内置命令基础上做定制化调整 |

### 执行策略

遇到复杂 PDF 任务时：

1. **先查看是否有可复用的扩展**：`pdfkit.py extension --help`
2. **有现成扩展** → 直接调用
3. **没有现成扩展但内置命令可组合完成** → 拆解为多个内置命令依次执行
4. **需要新扩展** → 为用户创建扩展脚本到 `../pdfkit-extension/scripts/`

---
