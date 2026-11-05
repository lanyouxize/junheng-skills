---
name: junheng-energy
description: 宠物食品能量计算。按常规成分算总能 GE、消化能 DE、代谢能 ME（改良 Atwater、经典 Atwater、NRC 三步法三种口径）、ME:GE 比、供能比、能量消化率与静息能量需求 RER；也可单查能量系数与出处。问配方代谢能、RER 怎么算时使用。
description_en: Pet food energy computation (GE/DE/ME with modified-Atwater, classic Atwater and NRC three-step methods, ME:GE ratio, energy source distribution, digestibility, resting energy requirement) from as-fed proximate composition; plus coefficient and citation lookup.
author: Junheng NutriAgent
version: 1.0.0
---

# 能量计算（junheng-energy）

## 目的与边界

**做什么**：从原样基础常规成分算出能量学指标，每一口径给出明确出处。

**不做什么**：

- **不做配方** —— 输入是已经算好的常规成分（%），不是原料清单。原料 → 成分请用配方营养计算能力。
- **不给 MER / 每日喂食量** —— 本技能只到 RER（静息需求）。MER 还要乘生命阶段、绝育、活动等系数，不在本技能范围内。
- **不把「算不出」当 0** —— 水分缺失时 GE / DE / NRC 代谢能返回 `null`，同时在 `note` 里说明原因。

## 诚实性红线

1. **理论计算值不等于检测值**。每次输出都带 `basis: "theoretical"`，实测值与计算值通常有差异。
2. **外推必须标注**。消化率方程是线性回归式，干物质基粗纤维超过 10% 时进入外推区，输出带 `digestibilityExtrapolated: true`，必须一并转述。
3. **缺失必须显式为 null**。`ge: null` / `meNRC: null` 表示「未算出」，**不得**当作 0 代入后续计算。
4. **系数不许改写**。`GE_FACTORS_KJ` 是 NRC 按 kJ 独立取整公布的值，**不是** `GE_FACTORS × 4.184`；要换算时必须说明是换算值。
5. **供能比口径要讲清**。`source` 用的是改良 Atwater（碳水 3.5 kcal/g，标签惯例），与基于 GE 的占比不是一回事。

## 用法

在技能根目录下执行：

```
node scripts/cli.mjs <命令> '<JSON 参数>'
node scripts/cli.mjs <命令> --stdin          # 参数从标准输入读
node scripts/cli.mjs --help
node scripts/cli.mjs <命令> --help
```

## 命令一览

| 命令 | 用途 |
|------|------|
| `profile` | 算一整套能量学结果（GE / DE / ME 多口径 / ME:GE / 供能比） |
| `rer` | 算静息能量需求 RER（kcal/日） |
| `ge` | 只算总能 GE（NRC 2006 表 VII-5 燃烧热系数） |
| `digestibility` | 算 NRC 2006 能量消化率（并标出是否外推） |
| `factors` | 查全部能量系数与适用边界 |
| `cites` | 查各口径的出处原文 |
| `describe` | 输出机器可读的接口说明 |

**参数详表、输出字段表、可运行示例** → [详细接口参考](references/interface-reference.md)。

## 失败处理（退出码）

| 退出码 | 含义 |
|--------|------|
| 0 | 成功。注意：**「算不出」也是 0** —— 请看 `ok` 与 `note`，不要只看退出码 |
| 1 | 内部错误（未预期异常） |
| 2 | 用法或输入错误，命令未执行 |
| 3 | 前置条件缺失（技能镜像未同步） |

## 拒答与替代路径

> 本节是**可机检**的边界契约（规范与判据见 `docs/技能边界与拒答契约_2026-10-13.md`）。
> 命中某一类时，按该类「话术」回复并给出「替代」路径；标「不适用」的类必须写明本技能层面的理由。

### R1 非犬猫物种
- **触发**：为非犬猫物种计算能量学指标。
- **话术**：本技能的能量系数（NRC 2006）只对犬与猫给出，对其它物种不能套用。
- **替代**：请改用该物种的能量体系；已给犬猫常规成分的能量口径仍可照算。

### R2 医疗诊断
- **触发**：要求用能量结果判断疾病或制定治疗性饮食。
- **话术**：本技能只出能量学指标，不做诊断也不给治疗方案。
- **替代**：请咨询执业兽医；各口径能量值与出处本技能可直接查。

### R3 超出已收录法规体系
- **触发**：要求按未收录体系的能量系数计算。
- **话术**：该体系的系数未收录，我不能按它出结果。
- **替代**：可先出本项目已核对的口径（GE / DE / NRC 代谢能），并标注是否属于外推。

### R4 数据缺口（`nodata`）
- **触发**：常规成分缺水分等关键项，能量无法计算。
- **话术**：关键成分缺失时 GE / DE / NRC 代谢能返回 `null`，我不填 0。
- **替代**：请补齐常规成分实测值；本技能会在 `note` 里说明缺失原因，不省略。
