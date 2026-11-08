---
name: junheng-pipeline
description: 跨技能串联编排。一次调用跑完配方营养、个体需求、标签底稿、成本与喂食计划全套计算，替代手工搬运中间结果；多宠入口一次产出逐宠喂食量、合计采购清单与分装排期标签。问把配方完整评估一遍、一条命令跑全套时使用。
description_en: Cross-skill orchestration. Computes recipe nutrition, individual requirements, label draft, cost sheet and feeding plan in a single call, replacing manual shuttling of 5-6 KB intermediate objects between skills. A multi-pet entry (run-multi) additionally goes from each pet's raw ingredients to per-pet feeding amounts, a combined purchase list, and same-day portioning schedules with printable labels.
metadata:
  author: Junheng NutriAgent
  version: "1.1.0"
compatibility: Requires Node.js 18+ (ESM) and a UTF-8 filesystem. No network access and no third-party dependencies. Loads its computation closure from the sibling shared-core skill junheng-core via the relative path ../../junheng-core/.
license: Proprietary
---

# 跨技能串联编排（junheng-pipeline）

## 目的与边界

**做什么**：把分散在 4 个技能里的计算串成**一次调用**，消除手工搬运。

**不做什么**：

- **不含独立公式** —— 全部数值来自 `src/lib/` 的既有函数（`computeRecipe` / `computeRequirements` / `buildLabelDraft` / `computeCostSheetByMode` / `computeFeedingPlan`；多宠入口另用 `computeMultiPetPlan` / `computePortionLabels`）。结果与分别调用各技能**逐字段一致**。
- **不替代单技能调用** —— 只想算一个东西时用对应技能更快，不必走本门面。
- **不做配方决策** —— 不替用户选原料、不下合规结论。
- **不静默跳过** —— 每一步都有 `status`（`ok`/`skipped`/`failed`/`error`）与 `reason`。

## 诚实性红线

1. **是编排层不是新算法**。输出里的每个数字都能在对应单技能里复现。
2. **失败必须可见**。`ok:false` 时看 `summary.failed` 与每步的 `reason`，不要只看 `ok`。
3. **跳过也要可见**。`summary.skipped > 0` 表示有步骤因缺参数没跑 —— 例如没给 `profile` 就不会算喂食计划，**这不是"算出来是空"**。
4. **理论值 ≠ 检测值**；标签部分是**底稿不是定稿**；喂食部分是**建议不是处方**。
5. **分装标签是厨房贴纸，不是合规标签**。`run-multi` 的 `portions` 只回答「这袋多少克、贴什么字」；
   合规标签（保证值表 / 配料表）仍走 `junheng-labeling draft`。
6. **不替用户填保质期**。`run-multi` 的「建议食用期限」必须在给了 `shelfLifeDays` 时才有值；
   未给则留空并印「待定」—— 拿经验值填进去等于把猜想印在贴纸上。

## 用法

```
node scripts/cli.mjs run '<JSON 参数>'
node scripts/cli.mjs steps '{}'          # 只列步骤与所需参数，不计算
node scripts/cli.mjs --help
```

> ⚠ 依赖共享内核 `junheng-core`。报「找不到源码目录」时，到项目根 `packages/nutrition-agent-work` 跑 `node scripts/sync-skills.mjs`——技能目录是只读镜像，不含该脚本。

## 命令一览

| 命令 | 用途 |
|------|------|
| `run` | 一次调用完成全套 5 步 |
| `run-multi` | **多宠入口**：逐宠「原料→营养→需求→喂食量」→ 合计与合并采购清单 → 同日分装排期与分装标签 |
| `steps` | 只列出会执行哪些步骤、各需要什么（排错与自检用；含 `multi` 段列 `run-multi` 的四步） |
| `describe` | 输出机器可读的接口说明 |

**参数详表、输出字段表、可运行示例、单步管道 `--as`** → [详细接口参考](references/interface-reference.md)。

## 失败处理（退出码）

| 退出码 | 含义 |
|--------|------|
| 0 | 命令执行完毕。注意：**步骤失败/跳过也是 0** —— 请看 `summary` 与各步 `reason` |
| 1 | 内部错误（未预期异常） |
| 2 | 用法或输入错误，命令未执行 |
| 3 | 前置条件缺失（共享内核未同步） |

## 与单技能的关系（该用哪个）

| 场景 | 用什么 |
|---|---|
| 只算配方营养 | `junheng-nutrition recipe` |
| 只出标签稿 | `junheng-labeling draft` |
| 完整评估（多步） | **本门面 `run`** |
| 多宠 + 采购清单 + 分装标签 | **本门面 `run-multi`**（只想单独做一段时用 `junheng-feeding` 的 `plan-multi` / `portion-label`） |
| 想在 shell 里把某一步的结果接到下一步 | 任一技能 + `--as <参数名>`（见详参） |

## 拒答与替代路径

> 本节是**可机检**的边界契约（规范与判据见 `docs/技能边界与拒答契约_2026-10-13.md`）。
> 命中某一类时，按该类「话术」回复并给出「替代」路径；标「不适用」的类必须写明本技能层面的理由。

### R1 非犬猫物种
- **触发**：为非犬猫物种跑全套管道。
- **话术**：管道内的需求与达标口径只覆盖犬与猫，对其它物种不给结论。
- **替代**：请分步调用该物种的对应能力；犬猫配方可照常跑全套步骤。

### R2 医疗诊断
- **触发**：要求管道给出诊断或治疗性配方结论。
- **话术**：管道只搬运既有计算，不含诊断，也不下「这个配方能卖」的结论。
- **替代**：请咨询执业兽医；各步数值与合规段本管道会照常串联输出。

### R3 超出已收录法规体系
- **触发**：要求按未收录体系跑达标或标签步骤。
- **话术**：该体系未收录时对应步骤会标 `skipped` 并给出 `reason`，不会编造结论。
- **替代**：可用已收录体系跑到哪算哪；该体系补录后重跑即可。

### R4 数据缺口（`nodata`）
- **触发**：上游数据缺口导致某一步无法完成。
- **话术**：缺数据时该步标 `error` / `skipped` 并给出 `reason`，我不静默跳过。
- **替代**：请先补齐该步所需输入；补齐后重跑单步即可。
