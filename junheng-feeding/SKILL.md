---
name: junheng-feeding
description: 宠物喂食指南与体况管理。按个体档案与配方算每日喂食计划（kcal、克/日、餐次）、体况策略、理想体重、换粮过渡与监测计划；支持多宠聚合产出合并采购清单与按每袋 N 天的分装排期标签。问猫每天吃多少克、BCS 7 分怎么喂时使用。
description_en: Pet feeding guide and body condition management (Junheng NutriAgent). Compute daily feeding plan (kcal, grams/day, meals), BCS-based energy adjustment, ideal weight estimate, diet transition schedule, monitoring plan and vet-visit signals. Also aggregates multiple pets' plans, produces a combined purchase list merged by material code, and splits daily amounts into labelled portion bags (recipe name, grams per portion, packaging date, use-by date, thawing note).
metadata:
  author: Junheng NutriAgent
  version: "1.2.0"
compatibility: Requires Node.js 18+ (ESM) and a UTF-8 filesystem. No network access and no third-party dependencies. Loads its computation closure from the sibling shared-core skill junheng-core via the relative path ../../junheng-core/.
---

# 喂食指南与体况管理（junheng-feeding）

## 目的与边界

**做什么**：回答「这只宠物该吃多少、怎么喂、多久复评、什么情况要就医」。

**不做什么**：

- **不是处方** —— 产物是喂养**建议**；目标体重与增减喂食量必须由人（最好含兽医）确认。
- **不替代实际体况触摸** —— 所有 BCS 判定都以触摸肋骨为准；只看轮廓会被毛量、原始袋、品种骨架误导。
- **不做疾病诊断** —— 体况评分是筛查工具，不是兽医诊断。
- **不做配方** —— 需要配方营养结果时用 `junheng-nutrition`，本技能只消费它的输出。

## 诚实性红线

1. **分子分母都要说清**。能量为理论计算值（非检测值）；喂食量取决于所用配方的实际能量。
2. **体况评分是筛查不是诊断**。不在理想区（犬 4~5 分、猫 5 分）的评分都建议请兽医评估。
3. **猫的减重必须比犬更慢**。猫减重过快会诱发肝脂沉积症（脂肪肝），可危及生命 —— 这条必须转述。
4. **目标体重需兽医确认**。`energyAdjPercent` 是经验值不是剂量；不得只凭它大幅调整饲喂。
5. **禁止只凭输出改变饲喂**。任何调整都应在复评周期内逐步进行并观察。
6. **不替用户填保质期**。分装标签的「建议食用期限」必须由用户给出保质期天数；未给出时留空并提示「待定」。
   拿经验值（如「冷冻一般能放 90 天」）填进去，就是把猜想印在贴纸上，而用户会照着它决定还吃不吃。

## 用法

在技能根目录下执行：

```
node scripts/cli.mjs <命令> '<JSON 参数>'
node scripts/cli.mjs <命令> --stdin
node scripts/cli.mjs --help
node scripts/cli.mjs <命令> --help
```

> ⚠ 依赖共享内核 `junheng-core`。报「找不到源码目录」时，到项目根 `packages/nutrition-agent-work` 跑 `node scripts/sync-skills.mjs`——技能目录是只读镜像，不含该脚本。
> ⚠ `recipe` 与 `req` 来自 `junheng-nutrition`，给了 `recipe` 才能把能量换算成「克/日」。
> ⚠ 多宠命令（`plan-multi` / `purchase-list` / `portion-label`）：请把 `parseRecipeText` 里**未匹配**的原料一并传进
> `pets[].unmatched`（`{ rawName, weight }`）。不传的后果有两个 —— 采购清单**不会列出**它们（静默少买），
> 且这些库外原料**不会被安全闸筛到**（`recipe.lines` 里根本没有它们，库里查不到的禁用原料会因此漏网）。
> ⚠ `portion-label` 的「建议食用期限」= 分装日期 + `shelfLifeDays`。**不给 `shelfLifeDays` 就留空**，
> 本技能不猜保质期（贴纸会印「待定」）。缺保质期天数时请先向用户问明，不要把默认天数写进贴纸。

## 命令一览

| 命令 | 用途 |
|------|------|
| `plan` | 生成完整喂食计划（能量、克/日、餐次、过渡、监测、储存） |
| `plan-multi` | 多宠聚合：逐宠算喂食量并合计，同时给出按物料编号归并的合并采购清单 |
| `purchase-list` | 合并采购清单：只输出按物料编号归并的原料需求量（多宠合计，含未匹配原料） |
| `portion-label` | 同日分装排期 + 分装标签：把每宠每日用量按「每袋 N 天」拆袋，出可打印贴纸（配方名/每份克数/分装日期/建议食用期限/解冻提示） |
| `render` | 把喂食计划渲染成可直接粘贴的纯文本 |
| `bcs-policy` | 按体况评分取喂养策略（能量调整幅度、是否减重、限制原因） |
| `bcs-scale` | 查 9 分制判据表与分组（**须指定 species**：犬 4~5 分为理想、猫仅 5 分） |
| `ideal-weight` | 由当前体重与体况评分估算理想体重 |
| `life-stage` | 判定生命阶段与餐次建议 |
| `transition` | 换粮过渡计划（默认 7 天） |
| `monitoring` | 监测计划（按生命阶段与体况策略） |
| `vet-signals` | 查需要就医的信号清单 |
| `describe` | 输出机器可读的接口说明 |

**参数详表、输出字段表、可运行示例** → [详细接口参考](references/interface-reference.md)。

## 失败处理（退出码）

| 退出码 | 含义 |
|--------|------|
| 0 | 成功。注意：**「算不出」也是 0** —— 请看 `ok` 与原因字段 |
| 1 | 内部错误（未预期异常） |
| 2 | 用法或输入错误，命令未执行（如 `score` 给了 0 或 12） |
| 3 | 前置条件缺失（共享内核未同步） |

## 拒答与替代路径

> 本节是**可机检**的边界契约（规范与判据见 `docs/技能边界与拒答契约_2026-10-13.md`）。
> 命中某一类时，按该类「话术」回复并给出「替代」路径；标「不适用」的类必须写明本技能层面的理由。

### R1 非犬猫物种
- **触发**：为非犬猫物种制定喂食计划。
- **话术**：本技能的 BCS 判定表与能量口径仅覆盖犬与猫。
- **替代**：请咨询该物种的兽医；猫犬的喂食量计算本技能可照常给。

### R2 医疗诊断
- **触发**：询问疾病、要不要就医以外的临床判断（如"是不是肾衰"）。
- **话术**：体况评分是筛查工具，不是诊断；我不能给出疾病判断。
- **替代**：出现异常体况或食欲变化时请就医；本技能负责把复评周期与预警信号列清。

### R3 超出已收录法规体系
- **触发**：要求按未收录体系的能量或体况标准出结果。
- **话术**：该体系未收录，我不能按它给出判定。
- **替代**：本技能的能量计算走本项目已核对的能量口径，可先出这一版。

### R4 数据缺口（`nodata`）
- **触发**：配方缺少实测能量或原料成分，无法算出喂食量。
- **话术**：能量为理论计算值，缺少配方实测能量时我无法给出可靠的喂食克数。
- **替代**：请先用配方营养计算补齐该配方的能量；本技能拿到结果后会给出喂食区间。
