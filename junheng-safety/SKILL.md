---
name: junheng-safety
description: 宠物食品有毒有害物质安全闸。按物种筛查配方中的禁用与慎用物质，返回禁用、慎用、安全、未收录四态结论并带来源机构与判定依据；可批量筛查并在命中禁用时阻断。未收录一律判未收录，绝不当作安全。问巧克力能不能喂狗时使用。
description_en: Toxic-substance safety gate for pet food. Screens a recipe or a single ingredient for banned and caution substances (chocolate, xylitol, lilies, allium, grapes, macadamia, permethrin) by species, in four states — banned / caution / ok / unknown; unlisted substances are never reported as safe, and a banned hit blocks the recipe.
metadata:
  author: Junheng NutriAgent
  version: "1.0.0"
compatibility: Requires Node.js 18+ (ESM) and a UTF-8 filesystem. No network access and no third-party dependencies. Self-contained CLI facade; no dependency on other junheng-* skills.
---

# 有毒有害物质安全闸（junheng-safety）

## 目的与边界

**做什么**：回答「某个原料 / 物质，对某物种而言能不能进配方」，并在批量筛查时于**命中禁用条目**处阻断。

**不做什么**（明确边界，避免误用）：

- **不判定营养是否达标** —— 安全与配比是两件事。营养结论请用配方营养计算能力；本技能只回答「能不能吃」。
- **不给毒理学数值** —— 不提供 LD50、血药浓度、安全摄入量这类未经收录的量化结论。
- **不提供诊断、用药与剂量** —— 宠物已出现症状时请就医，本技能不承担处置职责。
- **不声明「安全」** —— 除非有显式来源支撑。绝大多数原料会返回 `unknown`（未收录），这是**如实**，不是缺陷。

## 诚实性红线

1. **未收录一律 `unknown`，绝不 `ok`**。把「查不到」兜底成「安全」，会让安全闸在最该拦的场景静默放行。守卫会构造该变异并判红。
2. **`unknown` 不是「安全」也不是「不安全」**。对外交付时必须原样报出，不得省略、不得改写成「暂无风险」。
3. **每条收录都必须能回溯到来源**。输出带 `sources`（机构 / 条目 / 链接 / 抓取日期）；引用时连同来源一起给，不要只给结论。
4. **`species` 记「来源实际支持的物种」**。百合属、氯菊酯的来源只支持猫 ⇒ 只标 cat：猫配方判 `banned`、犬配方判 `unknown`（不越权外推）。
5. **本技能是筛查提示，不是毒理学结论**。不构成诊断或治疗建议。

## 用法

在技能根目录下执行：

```
node scripts/cli.mjs <命令> '<JSON 参数>'
node scripts/cli.mjs <命令> --stdin          # 参数从标准输入读（避免 shell 转义问题）
node scripts/cli.mjs --help                  # 全部命令与退出码
node scripts/cli.mjs <命令> --help           # 单个命令的参数表
```

参数必须是一个 JSON 对象。含空格或中文时，用单引号把整个 JSON 包住（Windows cmd 下用双引号）。

## 命令一览

| 命令 | 用途 |
|------|------|
| `list-substances` | 列出已收录的有毒有害物质（可按物种 / 类别 / 严重度筛选） |
| `check` | 判定单一物质 / 原料（四态） |
| `screen` | 批量筛查配方全部原料，命中禁用即阻断 |
| `list-sources` | 列出来源清单（机构 / 条目 / 链接 / 抓取日期） |
| `describe` | 输出机器可读的接口说明（命令、参数、退出码） |

**参数详表、输出字段表、可运行示例** → [详细接口参考](references/interface-reference.md)。

## 失败处理（退出码）

| 退出码 | 含义 |
|--------|------|
| 0 | 成功，结果在 stdout 的 JSON 里 |
| 1 | 内部错误（未预期异常，属 bug，请保留 stderr 原文） |
| 2 | 用法或输入错误：命令名、JSON 语法、参数名或参数值不合法，命令未执行 |
| 3 | 前置条件缺失：源码目录不可读（技能镜像未同步） |

失败时 stdout 为空，stderr 是一行 JSON：`{"ok":false,...,"error":{"kind","message","details"}}`。
`error.details[]` 逐条给出出错的参数路径与原因，按它逐项修正即可。

## 拒答与替代路径

> 本节是**可机检**的边界契约（规范与判据见 `docs/技能边界与拒答契约_2026-10-13.md`）。
> 命中某一类时，按该类「话术」回复并给出「替代」路径；标「不适用」的类必须写明本技能层面的理由。

### R1 非犬猫物种
- **触发**：询问对象不是犬或猫（如兔、貂、鹦鹉、爬宠），或要求把犬猫的结论外推到其它物种。
- **话术**：本库条目按犬 / 猫分别标注来源支持的物种，对其它物种给不出可靠结论。
- **替代**：请咨询该物种的兽医或查阅专门的毒理学资料；本技能对未标注该物种的条目会返回 `unknown`，可原样当作「未判定」使用。

### R2 医疗诊断
- **触发**：询问中毒后的诊断、解毒、用药或剂量，或要求判断「已经吃了要不要紧」。
- **话术**：本技能只做配方原料筛查，不构成诊断、治疗或急救建议。
- **替代**：请立即联系执业兽医或宠物中毒咨询热线；就诊时本技能可提供疑似物质的来源与依据，供兽医参考。

### R3 超出已收录法规体系
- **触发**：询问本库来源未覆盖的毒理量化结论（如 LD50、血药浓度、安全摄入量），或要求引用未收录的机构口径。
- **话术**：本库只收录有权威来源支撑的禁用 / 慎用事实，不给出未收录的毒理数值。
- **替代**：可先给出已收录条目的来源四元组供追溯；需要新条目时请补充权威来源后收录，收录后才参与判定。

### R4 数据缺口（`nodata`）
- **触发**：询问的物质不在已收录种子表内（返回 `unknown`）。
- **话术**：该物质本库未收录，**无法判定** —— 这不等于安全，也不等于不安全。
- **替代**：请补充该物质的权威来源以纳入种子表；在收录前本技能会原样返回 `unknown`，不兜底成 `ok`。
