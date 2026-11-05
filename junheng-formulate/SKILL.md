---
name: junheng-formulate
description: 宠物食品最低成本配方求解（钧衡 NutriAgent 出品）。给定原料清单（含价格与 %DM 营养）与营养约束（来自 junheng-standards 的 resolveStandard），用零依赖纯 JS 两阶段单纯形求解最低成本配方，并附约束达成度与可行性诊断。当用户问「在满足 AAFCO/FEDIAF 营养下限的前提下怎么配最省钱」「原料怎么搭配成本最低」「这个约束有没有可行解」时使用。
description_en: Pet food least-cost formulation (Junheng NutriAgent). Given an ingredient list (price + %DM nutrients) and nutrient constraints (from junheng-standards resolveStandard), solve the least-cost recipe with a zero-dependency pure-JS two-phase simplex, with constraint attainment and feasibility diagnostics.
author: Junheng NutriAgent
version: 0.1.0-POC
---

# 最低成本配方求解（junheng-formulate）

## 目的与边界

**做什么**：在「营养约束 + 原料价格 + 总占比=1」的前提下，求**成本最低**的配方比例。

**不做什么（当前 POC 范围）**：

- **不是配方设计器** —— 只做「给定原料集合下的最优配比」，不替你选原料、不保证适口性/工艺可行。
- **不替代 junheng-cost** —— 本 skill 求「最低成本配方比例」；把得到的比例交给 `junheng-cost` 做精细成本核算（加工费/损耗/收得率）。两者是上下游。
- **POC 阶段只接 `%DM` 营养字段** —— 原料库当前仅有粗蛋白等少数 `%DM` 字段；氨基酸/矿物/维生素（A1 批 A 已登记但未落字段）暂无法参与约束，但求解器本身支持任意营养键。
- **不处理非 %DM 单位** —— 矿物 mg/kg、维生素 IU/kg 等需先归一化到 %DM 或 DM 基准，留待批 B。

## 求解器事实（无第三方依赖）

- 纯 Node ESM 实现 **两阶段单纯形（Two-Phase Simplex）**，见 `scripts/formulate.mjs` 的 `solveLP`。
- 支持约束 `<= / >= / =`；变量非负。原料最大添加量 `x_i <= cap` 直接作为 `<=` 约束接入，同一套约束机。
- **刻意不引入** `javascript-lp-solver` / `glpk.js`：零安装、零网络、可逐行验证，符合「可在其他电脑直接运行」。
- 验证：运行 `node scripts/poc.mjs` —— 12 项断言全绿（合成用例 + 真实 junheng 数据用例）。

## 接线方式（formulateLeastCost）

```js
import { formulateLeastCost } from './formulate.mjs'
// ingredients: [{ id, name, price, nutrients: { crude_protein: <占DM%> } }]
// constraints: 来自 resolveStandard(...).items（已 available 过滤，含 min/max/unit）
const r = formulateLeastCost({ ingredients, constraints })
// r.recipe            → [{ id, name, share, price }]
// r.unitCost          → 最低单位成本（元/kg）
// r.achieved          → 各营养实际达成度（用于质量门禁）
// r.status            → 'optimal' | 'infeasible' | 'unbounded'
```

真实数据接线示例（已通过 POC）：

```js
import { resolveStandard } from '<junheng-standards>/scripts/vendor/standards.js'
const std = resolveStandard({ marketId: 'intl', species: 'dog', stage: 'adult' })
const cp = std.items.find(i => i.key === 'crude_protein') // min=18, %DM
// 原料营养须折算 %DM：cpDM = 风干前粗蛋白 / (1 - 水分/100)
// 价格取自原料库 ing.price
```

## 质量门禁（对齐 feedformulator-api 范式，A2 评估结论）

- **不可行诊断**：`status:'infeasible'` 时，应回退报「无可行解」并列出冲突约束，而非静默给 0。
- **未达标提示**：`achieved[key].value` 低于 `min` 时显式标红（POC 已能算出但 UI 提示待接）。
- **诚实性**：原料库缺某营养字段 → 该约束 `available:false`（见 junheng-standards），求解器不会假装满足。

## 诚实性红线

1. **最低成本 ≠ 推荐配方**。成本是单一目标，适口性/工艺/合规需人工叠加判断。
2. **约束来自标准，但标准可能未核**。junheng-standards 的 AAFCO 部分条目 `verified:false`，结论须标注来源可信度。
3. **仅限 %DM 可比**。未归一化的单位（mg/kg、IU/kg）混入会导致约束失效，必须先统一基准。
