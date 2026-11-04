# 通道能力与前置条件

| 通道 | 类型 | 前置 | status | 本机(2026-11-01) |
|---|---|---|---|---|
| `strings` | 零依赖 | Python 3.8+ | ok | 可用 |
| `pe` | 零依赖 | Python 3.8+ | ok | 可用 |
| `asar` | Node | `npx asar` | partial | 可用（探测） |
| `ghidra` | 外部 | Ghidra + JDK 21 | partial/unavailable | 不可用（缺 JDK） |
| `dotnet` | 外部 | `dotnet tool install -g ilspycmd` | partial | 不可用 |
| `jadx` | 外部 | jadx + JDK | partial | 不可用 |
| `apk` | 外部 | apktool + JDK | partial | 不可用 |
| `pyinstaller` | 外部 | pycdc | partial | 不可用 |

## status 语义

- `ok` —— 通道跑通，facts 完整
- `partial` —— 工具在，但只做了可用性探测或只覆盖部分目标形态（例如 pycdc 不支持的字节码版本）
- `unavailable` —— 工具缺失 / 目标形态不符；**必须给 unavailable_reason，facts 必须为空数组，退出码 3**

## 为什么保零依赖通道

本机无 JDK：Ghidra、jadx、apktool、ilspycmd 全部不可用。若不带零依赖通道，本技能在裸机上零产出。
`strings` + `pe` 覆盖了「在导入表里定位串口/文件/网络 API」这一步，是场景①的起手式。

## 加工具后要补的动作

1. 装 JDK 21 → 跑 `detect` 确认 java 行变为可用
2. 按 `06-落地手册-Windows.md` 第 3/4 步装 Ghidra 与 jadx
3. 首次使用某外部通道时，把实际命令与参数写入该条 fact 的 `reproduce`，否则它只是探测记录、不构成证据
