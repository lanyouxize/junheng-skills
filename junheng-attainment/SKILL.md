---
name: junheng-attainment
description: 配方达成度评估。给定配方与目标画像（物种/月龄/体况/目标市场）对照法规限值，输出达标/未达标/数据不足/无法判定四态、缺口与配比建议。当用户问「这个配方达不达标」「钙磷比够不够」「按国标能不能过」时使用。
description_en: Recipe attainment evaluation. Compares a formula against regulatory limits for a target profile (species / age / market) and reports per-nutrient status, the shortfall list and mixing suggestions.
metadata:
  author: Junheng NutriAgent
  version: "1.0.0"
compatibility: Requires Node.js 18+ (ESM) and a UTF-8 filesystem. No network access and no third-party dependencies. Loads its computation closure from the sibling shared-core skill junheng-core via the relative path ../../junheng-core/.
---

# 目标达成度评估（junheng-attainment）

## 目的与边界

**做什么**：一次调用回答「**这个配方，对这个目标对象，达不达标、差在哪**」。

输入是**原料清单 + 目标画像**，输出是**逐项四态结论 + 缺口清单 + 配比建议**。

**不做什么**：

- **不含独立公式** —— 判定全部来自 `src/lib/nutrition.js` 的 `evaluateRecipe`，
  与界面「⑤ 达标评估」、配方体检、标签稿的合规段**同一口径**；本门面不写任何限值数字。
- **不替代 `junheng-nutrition recipe`** —— 那个只算**营养组成**（不判断达标与否）。
- **不替用户做配方决策** —— 给缺口与建议，不给「这个配方能卖」的结论。
- **不谎报未达标** —— 数据不足时如实标 `nodata` / `low`，算法见下。

## 诚实性红线（★ 最要紧的一节）

**四态，不是两态**。把 `nodata` 读成「未达标」是本项目最危险的误读：

| `status` | 含义 | 该怎么说 |
|---|---|---|
| `ok` | 达标 | 「已达标准」 |
| `fail` | 未达标 | 「低于下限 / 高于上限 X」 |
| `low` | 数值达标，但**该指标覆盖的原料有数据缺口** | 「达标，但结论仅供参考（覆盖率 N%）」 |
| `nodata` | **无法判定**（原料库无此字段，或本配方算不出） | 「**无法判定**，缺数据」—— **绝不能说成「未达标」** |

> 原料库没有氨基酸字段，所以**赖氨酸 / 牛磺酸几乎总是 `nodata`**。这是数据缺口，不是配方缺陷。

两个汇总标志**不可互相替代**：

- `summary.allPass` —— 「**没有明确未达标项**」，`nodata` 项**不计入**（原样取自 evaluateRecipe）。
- `summary.fullyVerified` —— 「**所有项都验过、且都达标**」。要下「全面达标」的结论**只能用它**。

其余：`gap` 是**展示用算术差**（判定口径以 `status` 为准）；理论值 ≠ 检测值。

## 用法

```
node scripts/cli.mjs assess  '<JSON 参数>'
node scripts/cli.mjs targets '{}'        # 先看有哪些目标口径可选，不计算
node scripts/cli.mjs --help
```

> ⚠ 依赖共享内核 `junheng-core`。报「找不到源码目录」时，到项目根 `packages/nutrition-agent-work` 跑 `node scripts/sync-skills.mjs`——技能目录是只读镜像，不含该脚本。

## 命令一览

| 命令 | 用途 |
|------|------|
| `assess` | 逐项达标度 + 缺口清单 + 配比建议 |
| `targets` | 列出可用目标口径（市场 × 物种 × 阶段） |
| `describe` | 输出机器可读的接口说明 |

**参数详表、输出字段表、可运行示例** → [详细接口参考](references/interface-reference.md)。

## 失败处理（退出码）

| 退出码 | 含义 |
|--------|------|
| 0 | 评估执行完毕。**配方未达标也是 0** —— 请看 `summary` 与 `gaps` |
| 1 | 内部错误（未预期异常） |
| 2 | 用法或输入错误，命令未执行 |
| 3 | 前置条件缺失（共享内核未同步） |

## 与相关技能的分工（该用哪个）

| 场景 | 用什么 |
|---|---|
| 只想知道**营养组成**（蛋白/脂肪/钙磷比/能量） | `junheng-nutrition recipe` |
| 想知道**有哪些限值**、条款原文 | `junheng-standards resolve` / `clause` |
| **想知道达不达标、差在哪** | **本技能 `assess`** |
| 手里**已有** `recipe` 与 `req` 两个对象，只要原始对照表 | `junheng-nutrition evaluate` |
| 想要**全套**（营养 + 目标 + 标签 + 成本 + 喂食） | `junheng-pipeline run` |

> ★ 易混点：`junheng-nutrition evaluate` 需要**两个上游大对象**（`recipe` + `req`），
> 且明说「不替用户下是否达标的结论」；本技能 `assess` 只要**配方 + 画像**，
> 上游对象由它自己构造 —— 这是**一步到位版**，也是界面「⑤ 达标评估」的命令行等价物。

## 拒答与替代路径

> 本节是**可机检**的边界契约（规范与判据见 `docs/技能边界与拒答契约_2026-10-13.md`）。
> 命中某一类时，按该类「话术」回复并给出「替代」路径；标「不适用」的类必须写明本技能层面的理由。

### R1 非犬猫物种
- **触发**：目标对象不是犬或猫。
- **话术**：本技能的达标口径按犬猫目标画像定义，对其它物种无法给出结论。
- **替代**：请改用该物种的标准；犬猫的缺口清单与配比建议本技能可照常出。

### R2 医疗诊断
- **触发**：要求判断疾病，或据结果给出治疗性配方结论。
- **话术**：本技能只给逐项达标结论与缺口，不做诊断。
- **替代**：请咨询执业兽医；配方是否达标的逐项对照本技能可照常给。

### R3 超出已收录法规体系
- **触发**：要求按未收录体系的目标口径判定。
- **话术**：该口径未收录，我不能按它给出达标结论。
- **替代**：可用已收录口径先出这一版（市场 × 物种 × 阶段，见 `targets`）。

### R4 数据缺口（`nodata`）
- **触发**：库缺数据导致该项无法判定。
- **话术**：该项判为 `nodata` / `low` —— 无法判定，不等于未达标。
- **替代**：请补齐缺失数据；本技能会原样报 `nodata`，不谎报未达标。
