---
name: junheng-optimize
description: 宠物食品配方最低成本逆解。给定原料成本与线性约束求最省配比，返回最优解、目标值、变量取值与边际、约束影子价格；不可行时给出极小冲突集与最小松弛量。只解连续线性模型，不做营养折算与法规判定。问怎么配最省钱时使用。
description_en: Minimum-cost reverse solver for pet food formulas. Given ingredient costs and linear constraints, returns the cheapest feasible ratio plus dual information (shadow prices, reduced costs), or an infeasibility diagnosis with the minimal conflict set (drop any one member and the model becomes feasible) and the minimal relaxation amount. Continuous linear models only — no nutrient conversion, no unit conversion, no regulatory checks.
author: Junheng NutriAgent
version: 1.0.0
---

# 配方最低成本逆解（junheng-optimize）

## 目的与边界

**做什么**：回答「按给出的成本与约束，最省钱的配比是多少」，以及「若无解，是哪几条约束在打架、最少要松多少」。

**不做什么**（明确边界，避免误用）：

- **不做营养折算** —— 干物质折算、加工损失系数、单位换算一律不在本技能内。系数必须由调用方算好后写进模型；写错系数，错在模型，不在求解器。
- **不做合规与安全判定** —— 结果是否合规请用标签 / 标准能力；原料能不能吃请用安全闸能力。本技能只保证「在给定模型下成本最优」。
- **不回答非线性问题** —— 只解**连续线性**模型（目标与约束都是线性的）。整数约束、分段函数、多目标权衡都给不出结论。
- **不解释业务含义** —— 影子价格是**数学量**，不是采购报价，也不是建议价。它只说明「右端动一点，最优值动多少」。

## 诚实性红线

1. **不可行 ≠ 现实中配不出来**。`infeasible` 只说明「在这套系数与约束下没有可行点」，几乎总是建模问题（约束矛盾、漏了松弛、量纲不齐）。必须原样报出，并指向 `diagnose`。
2. **非最优时不给任何数值**。求解器不返回近似解，门面也不给残缺的配比 —— `objective` / `values` / 影子价格一律为 `null`。不得用「差不多」的数糊过去。
3. **`unknown` 不是「可行」**。迭代上限、自检失败属于「没能判定」，诊断会返回 `unknown`；它既不是可行也不是不可行，不得归入任一结论。
4. **影子价格只在本点附近成立**。只对绑定约束有意义，且只在该最优解的邻域内成立，**不可外推**为大范围结论。
5. **无界 ≠ 不可行**。`unbounded` 说明「有可行点但没有最优解」（通常是漏了上界），诊断会判 `feasible` 并明确区分。

## 用法

在技能根目录下执行：

```
node scripts/cli.mjs <命令> '<JSON 参数>'
node scripts/cli.mjs <命令> --stdin          # 参数从标准输入读（避免 shell 转义问题）
node scripts/cli.mjs --help                  # 全部命令与退出码
node scripts/cli.mjs <命令> --help           # 单个命令的参数表
```

## 命令一览

| 命令 | 用途 |
|------|------|
| `solve` | 求最低成本配比（返回配比、影子价格、变量边际） |
| `diagnose` | 诊断不可行（极小冲突集 + 最小松弛量） |
| `describe` | 输出机器可读的接口说明（命令、参数、退出码） |

**参数详表、输出字段表、可运行示例** → [详细接口参考](references/interface-reference.md)。

## 失败处理（退出码）

| 退出码 | 含义 |
|--------|------|
| 0 | 成功，结果在 stdout 的 JSON 里（**含** `infeasible` / `unbounded` 这类域内结论） |
| 1 | 内部错误（未预期异常，属 bug，请保留 stderr 原文） |
| 2 | 用法或输入错误：命令名、JSON 语法、参数名或参数值不合法，命令未执行 |
| 3 | 前置条件缺失：源码目录不可读（技能镜像未同步） |

⚠ **业务结论一律读 `data.status`，不要用退出码判断**：不可行与无界都是**结论**而不是程序错误，退出码同样是 0。

失败时 stdout 为空，stderr 是一行 JSON：`{"ok":false,...,"error":{"kind","message","details"}}`。
`error.details[]` 逐条给出出错的参数路径与原因，按它逐项修正即可。

## 拒答与替代路径

> 本节是**可机检**的边界契约（规范与判据见 `docs/技能边界与拒答契约_2026-10-13.md`）。
> 命中某一类时，按该类「话术」回复并给出「替代」路径。

### R1 非犬猫物种
- **不适用**：本门面的模型不接收物种参数，系数与约束由调用方给，物种适用性不在本技能的判定范围内。

### R2 医疗诊断
- **触发**：要求用求出的配比做疾病诊断、治疗或用药建议（如「按这个最省配方能不能治好猫的肾病」）。
- **话术**：本技能只解成本最优的线性模型，不构成诊断、治疗或用药建议。
- **替代**：请由执业兽医给出营养处方；本技能可按兽医给定的约束求最低成本实现方案。

### R3 超出已收录法规体系
- **触发**：要求判定求出的配比是否合规（如「这样配符不符合 GB 或 AAFCO 的限值」）。
- **话术**：本技能只保证在给定模型下成本最优，最优解也可能完全不合规。
- **替代**：把配比交给标签 / 标准能力判定合规，交给安全闸能力逐条筛查原料。

### R4 数据缺口（`nodata`）
- **触发**：求解器未能判定（`iteration_limit` / `verify_failed`，或诊断返回 `unknown`）。
- **话术**：这是「没能判定」，既不等于无可行解、也不等于有可行解，本技能不冒充结论。
- **替代**：可放宽 `maxIterations` 重试；仍失败时请人工检查模型是否退化或系数跨多个数量级。
