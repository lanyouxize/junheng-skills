---
name: rev-static
description: 静态解构软件。目标不运行、只读文件时用它：提取字符串、解析 PE 节表与导入表、跑 Ghidra/jadx/ilspycmd 出反编译结果。只产候选事实，不写正式证据库。
description_zh: 静态解构：零依赖的字符串/PE 通道 + 外部工具通道（Ghidra/jadx/ilspycmd/asar/pycdc）
description_en: "Static deconstruction with zero-dependency strings/PE channels plus external tool channels"
version: 1.0.0
display_name: rev-static
---

# rev-static

静态解构。**只产候选事实**，正式证据由 `rev-core evidence add` 收编。

## 不做什么

- **不写 `evidence.jsonl`**。它产出的是 `facts/<channel>.json`，交给 core 才成为证据。
- **不执行目标**。不启动进程、不注入、不抓包——那是 `rev-runtime` 的事。
- **不做保护绕过**。加壳、脱壳、反调试对抗一律不管。
- **不猜**。工具缺失时报 `unavailable` + 原因 + `exit 3`，**绝不返回空数组**冒充"没有事实"。

## 两条通道类型（这是本技能最关键的设计）

| 类型 | 通道 | 需要什么 | 本机现状 |
|---|---|---|---|
| **零依赖**（纯 Python） | `strings` / `pe` | 只要 Python | **立即可用** |
| 外部工具 | `ghidra` / `dotnet` / `jadx` / `apk` / `asar` / `pyinstaller` | 装对应工具 | 缺 JDK，除 `asar` 外均不可用 |

**为什么必须保留零依赖通道**：本机没有 JDK，也就没有 Ghidra / jadx / apktool。若不带零依赖通道，这个技能在裸机上是废的。而 `strings` + `pe` 恰好覆盖了文章案例里最关键的一步——**在导入表里找串口 API**。

## 命令

```bash
# 先看有什么工具可用（每次都建议先跑）
python scripts/cli.py detect

# 零依赖：字符串（ASCII + UTF-16LE，各带精确 offset/length/sha256）
python scripts/cli.py strings --sample D:/reva/cases/demo/sample.exe --out D:/reva/cases/demo --min-len 5 --limit 2000

# 零依赖：PE 解析（节表 + 熵 + 导入 DLL 与函数名）
python scripts/cli.py pe --sample D:/reva/cases/demo/sample.exe --out D:/reva/cases/demo

# 外部工具通道（缺工具时 exit 3，并写 unavailable 结果留痕）
python scripts/cli.py ghidra --sample D:/reva/cases/demo/sample.exe --out D:/reva/cases/demo
```

## 产物格式 `revfact/1`

```json
{
  "schema": "revfact/1",
  "channel": "pe",
  "sample_sha256": "<64位>",
  "status": "ok | partial | unavailable",
  "unavailable_reason": null,
  "facts": [
    {"id": "pe-0012", "kind": "import-func", "value": "WriteFile",
     "locator": {"file_sha256": "...", "offset": 218432, "length": 9},
     "digest": {"algo": "sha256", "value": "..."},
     "confidence_hint": "E1", "dll": "KERNEL32.dll"}
  ],
  "stats": {"sections": 8, "import_dlls": 50, "import_funcs": 310, "packer_hint": false}
}
```

**每条事实的 `locator.offset + length` 指向的确切字节，`digest` 是对那段字节实算的 sha256。** `selftest` 会把它们逐条回读重算比对——这是"事实"与"说法"的分界线。

## 事实种类

| channel | kind | 含义 |
|---|---|---|
| `strings` | `string-ascii` / `string-utf16le` | 可打印串，带精确偏移 |
| `pe` | `section` | 节名、VA、原始偏移、大小、**熵**（> 7.2 提示可能加壳） |
| `pe` | `import-dll` | 导入的 DLL 名 |
| `pe` | `import-func` | 导入的函数名（含所属 DLL） |
| 外部通道 | `tool-probe` | 工具已就位；具体分析命令需按目标形态补齐 |

## 典型用法：找串口 API（对应文章案例的 U1）

```bash
python scripts/cli.py pe --sample motor_gui.exe --out .
# 然后筛 import-func 里的 CreateFileW / SetupComm / SetCommState / WriteFile
```

拿到函数名和偏移只是 E1 事实；**"它写的是 COM3、9600/8N1"还需要 `rev-runtime` 用 Frida hook 取实参**，那是另一条通道，不能靠静态猜。

## 三条边界

- **Always**：先 `detect` 再选通道；每条事实保留 offset；工具缺失时如实报 unavailable。
- **Ask first**：用外部通道跑大文件（可能几十分钟）；`--limit` 调大（事实数会影响上下文）。
- **Never**：把 `unavailable` 当成"没有事实"；把 `strings` 里出现的关键字直接当结论（字符串可能是注释、可能是诱饵、可能属于别的模块）。

## 验收

```bash
python scripts/cli.py selftest
```

它会验证：`strings` 每条 digest 回读一致；`pe` 每条 digest 回读一致；**合成样本上 ASCII 与 UTF-16 串的 offset 必须精确命中**；缺工具时必须是 `unavailable` + exit 3 + 空 facts。

## 已知失效模式

1. **`strings` 只看 4 KB 头部之外的全文**，对压缩/加密的节提取不到有意义的串——这是数据本身的问题，不是扫描器漏了。
2. **PE 解析只处理标准导入表**，不处理延迟导入（delay-load）与绑定导入；遇到这类目标会少一批函数。
3. **`packer_hint` 只是熵阈值启发**（> 7.2），高熵也可能来自资源或压缩图片，不等于加壳。
4. **外部通道只做可用性探测**（`tool-probe`），真正的分析命令要使用者按目标补齐并写进 `reproduce`——本技能不替你决定参数。
