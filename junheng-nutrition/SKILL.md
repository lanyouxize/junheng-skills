---
name: junheng-nutrition
description: 宠物食品原料库查询与配方营养计算。按名称或物料编号查 286 条原料（成分/价格/数据状态），或按配方加权算营养素组成、多口径能量、钙磷比与成本并给出数据覆盖率与缺口；也可算 RER/MER。问原料含量、配方营养时使用。
description_en: Pet food ingredient database lookup and recipe nutrient computation (Junheng NutriAgent). Look up any of 286 ingredients by name or code, or compute a recipe's nutrient profile, energy (GE/DE/ME with multiple methods), Ca:P ratio, cost, plus data coverage and gaps; also computes individual requirements (RER/MER).
metadata:
  author: Junheng NutriAgent
  version: "1.1.0"
compatibility: Requires Node.js 18+ (ESM) and a UTF-8 filesystem. No network access and no third-party dependencies. Loads its computation closure from the sibling shared-core skill junheng-core via the relative path ../../junheng-core/.
license: Proprietary
---

# 原料库与配方计算（junheng-nutrition）

## 目的与边界

**做什么**：回答「某个原料有什么成分」与「某个配方算出来是多少」。

**不做什么**：

- **不做配方** —— 本技能算的是「给定原料与配比的营养结果」，不替你选原料、不当配方师。
- **不给合规结论** —— 限值判定请用 `junheng-labeling`；这里只出数值。
- **不做标签排版** —— 标签稿请用 `junheng-labeling`。
- **不猜测原料** —— 库里没有的原料会进 `unknown` 列表并明确报出，不会静默按 0 计。
- **单价不含税、不含议价** —— 价格口径为原料库 ¥/kg。

## 诚实性红线

1. **全部为理论计算值，不是检测值**。每次输出带 `basis: "theoretical"`。
2. **缺数据必须显式**。缺成分的原料进 `zeroData`，无价格的进 `cost.missingPrice`；覆盖率不足时结果会标低可靠度。**先看这几个字段再看数值**。
3. **未匹配的原料不静默丢弃**。`unknown` 列出所有没找到的原料名/编号。
4. **总重为 0 不出数**。返回 `data.ok:false` + `data.reason`（如 `zero_total_weight`），而不是给一堆 0。
   ⚠ **两层 ok 不同义**：外层 `ok:true` 只表示「命令执行成功」，不代表算出了数；**判断是否出数必须看 `data.ok`**。这个同名不同义是本项目最容易误读的一处，读结果时先看 `data.ok`。

## 用法

在技能根目录下执行：

```
node scripts/cli.mjs <命令> '<JSON 参数>'
node scripts/cli.mjs <命令> --stdin          # 参数从标准输入读
node scripts/cli.mjs --help
node scripts/cli.mjs <命令> --help
```

> ⚠ 依赖共享内核 `junheng-core`。报「找不到源码目录」时，到项目根 `packages/nutrition-agent-work` 跑 `node scripts/sync-skills.mjs`——技能目录是只读镜像，不含该脚本。

## 命令一览

| 命令 | 用途 |
|------|------|
| `ingredients` | 按关键词查原料（名称/编号片段），返回成分、价格与数据状态 |
| `recipe` | 按配方（原料+重量）算营养素、能量、钙磷比与成本 |
| `analyze-label` | 按标签上的原样基础营养值算干物质基/能量/钙磷比（不做 OCR） |
| `requirements` | 算个体营养需求（RER / MER + 生命阶段系数） |
| `dose2formula` | 把「每天该摄入多少 mg」换算成「配方添加比例%」（含纯度/存留率折减与反向达成度） |
| `evaluate` | 把配方结果与需求逐项对照（不替你下「达标」结论） |
| `parse-recipe-text` | 把自由文本配方解析成结构化条目 |
| `describe` | 输出机器可读的接口说明 |

**参数详表、输出字段表、可运行示例、传参注意** → [详细接口参考](references/interface-reference.md)。

> `dose2formula` **只做换算，不判断合规**：它把「每天该摄入多少」变成「配方加百分之几」，
> 本身不含任何 FEDIAF / AAFCO / GB 限值。要回答「是否达标 / 是否超限」，
> 须由调用方提供现行标准的限值与依据 —— 不得由本技能代填（见 R3）。

## 失败处理（退出码）

| 退出码 | 含义 |
|--------|------|
| 0 | 成功。注意：**「算不出」也是 0** —— 请看 `ok` 与 `reason` |
| 1 | 内部错误（未预期异常） |
| 2 | 用法或输入错误，命令未执行 |
| 3 | 前置条件缺失（共享内核未同步） |

失败时 stdout 为空，stderr 是一行 JSON：`{"ok":false,...}`。`error.details[]` 逐条给出出错参数路径（数组错误定位到 `items[2].weight` 这一级）。

## 拒答与替代路径

> 本节是**可机检**的边界契约（规范与判据见 `docs/技能边界与拒答契约_2026-10-13.md`）。
> 命中某一类时，按该类「话术」回复并给出「替代」路径；标「不适用」的类必须写明本技能层面的理由。

### R1 非犬猫物种
- **触发**：询问非犬猫物种的配方营养结果或个体需求对照。
- **话术**：本技能的需求口径只覆盖犬与猫，对其它物种无法给出需求对照。
- **替代**：成分与配方数值仍可照算；需求对照请改用该物种的标准并咨询兽医营养师。

### R2 医疗诊断
- **触发**：要求判断疾病，或按治疗性饮食给出配方结论。
- **话术**：本技能只出营养数值，不做诊断也不开处方。
- **替代**：请咨询执业兽医；配方数值与干物质基换算本技能可直接给。

### R3 超出已收录法规体系
- **触发**：要求按未收录体系的需求标准做对照。
- **话术**：该体系的需求条目未收录，我不能给出它的对照结论。
- **替代**：已核对体系（如 GB 系列）可照常对照；待补录后重查即可。

### R4 数据缺口（`nodata`）
- **触发**：库缺该营养项（如赖氨酸、牛磺酸），或原料未收录。
- **话术**：该项进 `unknown` / `nodata` —— 无法判定，不等于达标也不等于未达标。
- **替代**：请补充原料实测值或换用有数据的原料；本技能会把缺项原样报出，不按 0 计。
