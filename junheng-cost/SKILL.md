---
name: junheng-cost
description: 宠物食品配方成本核算（钧衡 NutriAgent 出品）。把配方（原料+用量）换算成成本行，再按通用（烘焙粮/产品明细表）、冻干、猫条三种口径算成本，含各项加工费、损耗率、收得率与单位成本（元/kg、元/支）。当用户问「这个配方成本多少钱一公斤」「冻干出成率和成本怎么算」「猫条一支成本多少」「加工费怎么摊」「损耗算进去没」时使用。
description_en: Pet food recipe cost accounting (Junheng NutriAgent). Convert a recipe into cost lines, then compute cost under general / freeze-dry / cat-stick modes with processing fees, loss rate, yield rate and unit cost.
metadata:
  author: Junheng NutriAgent
  version: "1.0.0"
compatibility: Requires Node.js 18+ (ESM) and a UTF-8 filesystem. No network access and no third-party dependencies. Loads its computation closure from the sibling shared-core skill junheng-core via the relative path ../../junheng-core/.
---

# 配方成本核算（junheng-cost）

## 目的与边界

**做什么**：算「某个配方在某加工口径下的成本是多少」，并把费用与损耗摊到单位成本。

**不做什么**：

- **不是报价** —— 不含税、不含议价、不含利润与渠道加价。只做成本算术。
- **不猜价格** —— 库里没价的原料按 0 计入并列入 `missingPrice`，**必须向用户提示**。
- **不替你选口径** —— 通用/冻干/猫条的成本结构不同，选哪个由你判断。
- **不吃配方结果** —— `costModes` 要的是「成本行」，需先用 `lines` 命令把配方转换（见下）。

## 诚实性红线

1. **是理论成本不是报价**。每次输出带 `basis: "theoretical"` 与免责声明。
2. **缺价必须显式**。`missingPrice[]` 列出所有无价格原料 —— 缺价会让总成本**偏低**，先看它再看数值。
3. **损耗与收得率是经验配置**。来自代码内的 `FREEZE_DRY_CONFIG` / `WORKSHOP_LOSS_CONFIG`，实际产线可能有差异，须一并说明。
4. **口径不同不可比**。通用 / 冻干 / 猫条的成本结构不同（如冻干按「解冻前用料」计、成品出成约 22%），不要把不同口径的数字直接横向比较。

## 成本可交付性判定（输出必带三字段）

> 光给数字不够。任何成本结论必须同时回答「这个数能不能拿去用」。三字段缺一即视为未完成。

| 字段 | 取值 | 说明 |
|------|------|------|
| `deliverable` | `usable` / `usable_with_caveat` / `not_usable` | 三档，判据见下表 |
| `confidence` | 0 ~ 1 | = 有价原料的重量占比；全有价时取 1.0 |
| `basis` | 对象 | 必含 `missingCount`（无价原料条数）、`missingWeightRatio`（无价原料重量占比）、`mode`（口径 id）、`feeSource`（费率来源） |

**三档判据（自上而下，命中即取）**：

| 档 | 触发条件 |
|----|----------|
| `not_usable` | `unknown[]` 非空，**或** `missingWeightRatio > 0.30` |
| `usable_with_caveat` | `missingPrice[]` 非空（占比 ≤ 0.30），**或** 用户未指定口径而由你代选 |
| `usable` | `missingPrice[]` 与 `unknown[]` 均空，且口径由用户明确指定 |

**禁止**：

1. 缺价时给 `usable`——缺价会让总成本偏低，等于给出乐观假数。
2. 只给数字不给 `basis`——对方无法判断这个数基于多少缺失数据。
3. 用 `confidence` 替代 `deliverable`——置信度低不等于不可用，两者不可互相顶替。
4. 把不同 `mode` 的 `deliverable` 直接放到一张表里比较。

**示例**（配方两原料，其一无价，占比 30%）：

```
deliverable: usable_with_caveat
confidence: 0.70
basis: { missingCount: 1, missingWeightRatio: 0.30, mode: "general", feeSource: "WORKSHOP_LOSS_CONFIG" }
```

## 工作流（两步，顺序不可颠倒）

| 步 | 命令 | 输入 → 输出 |
|----|------|-------------|
| **第 1 步** | `lines` | 配方 `items[{name 或 code, weight(克)}]` → **成本行 `data.lines[]`**（另含 `totalWeight` / `missingPrice[]` / `unknown[]`） |
| **第 2 步** | 成本命令**四选一** | 成本行 `lines[]` + 该口径的参数 → 单位成本（元/kg、元/支） |

第 2 步四选一：`sheet`（通用/烘焙粮，按批次数+克重）、`freeze-dry`（冻干，按投料→成品）、`cat-stick`（猫条，按规格）、`by-mode`（用 `mode` 切换的**统一入口**，参数是四者的并集）。

**中间产物形状契约** —— 成本行：
`{ code, name, unit:'kg', ratio(0~1), unitPrice(¥/kg), yieldRate }`。

第 2 步的 `lines` 必须**原样传第 1 步返回的 `data.lines`**（不要手捏；缺 `ratio`/`unitPrice` 会算错且不报错）。串联写法与坑见详参。

## 用法

在技能根目录下执行：

```
node scripts/cli.mjs <命令> '<JSON 参数>'
node scripts/cli.mjs <命令> --stdin
node scripts/cli.mjs --help
node scripts/cli.mjs <命令> --help
```

> ⚠ 依赖共享内核 `junheng-core`。报「找不到源码目录」时先跑 `node scripts/sync-skills.mjs`。

## 命令一览

| 命令 | 用途 |
|------|------|
| `lines` | 把配方（原料+重量）换算成成本行（**其它成本命令的前置**） |
| `modes` | 列出可用口径（id 用下划线，如 `freeze_dry`）与各类配置 |
| `sheet` | 通用成本表（需 `batchCount` + `gramPerBag`，或 `yieldKg`） |
| `by-mode` | 按口径 id 算成本（`general` / `freeze_dry` / `cat_stick`） |
| `freeze-dry` | 冻干成本（投料 → 成品，五项加工费 元/吨） |
| `cat-stick` | 猫条成本（按规格，含车间加工单价与损耗） |
| `format` | 成本数值格式化工具（与界面口径一致） |
| `describe` | 输出机器可读的接口说明 |

**参数详表、输出字段表、可运行示例、传参与串联注意** → [详细接口参考](references/interface-reference.md)。

## 失败处理（退出码）

| 退出码 | 含义 |
|--------|------|
| 0 | 成功。注意：**「算不出」也是 0** —— 请看返回里的 `ok:false` 与 `reason` |
| 1 | 内部错误（未预期异常） |
| 2 | 用法或输入错误，命令未执行 |
| 3 | 前置条件缺失（共享内核未同步） |

## 拒答与替代路径

> 本节是**可机检**的边界契约（规范与判据见 `docs/技能边界与拒答契约_2026-10-13.md`）。
> 命中某一类时，按该类「话术」回复并给出「替代」路径；标「不适用」的类必须写明本技能层面的理由。

### R1 非犬猫物种
- **触发**：为非犬猫产品线计算成本或套用其它物种口径。
- **话术**：本技能的成本口径按本项目犬猫产品线定义，对其它物种不做适配判断。
- **替代**：成本算术（费项摊到单位）本身通用；物种适配请另行确认后再套用。

### R2 医疗诊断
- **触发**：要求以成本结果做医疗、疗效或安全性判断。
- **话术**：本技能只做成本算术，不含诊断也不含疗效结论。
- **替代**：请咨询兽医或产品负责人；成本表与口径配置本技能可直接出。

### R3 超出已收录法规体系
- **触发**：要求按未收录的加工口径或税费体系摊费。
- **话术**：该口径未收录，我不能按它摊费。
- **替代**：可用已收录口径（`general` / `freeze_dry` / `cat_stick`）；新口径需先登记再算。

### R4 数据缺口（`nodata`）
- **触发**：原料库中该原料没有价格。
- **话术**：无价原料按 0 计入并列入 `missingPrice`，这个 0 不是真实成本。
- **替代**：请补录该原料价格；本技能会把缺价清单原样报出并提示。
