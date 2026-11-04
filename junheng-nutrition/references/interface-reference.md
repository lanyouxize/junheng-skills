# junheng-nutrition · 详细接口参考

> 本文件是 `SKILL.md` 的**非规范性**详参：参数表、输出字段表、可运行示例、传参注意。
> 规范契约（目的与边界、诚实性红线、命令一览、退出码、拒答与替代路径 R1–R4）**仍在 `SKILL.md`**，
> 两者冲突时以 `SKILL.md` 为准。
>
> ⚠ **本文件不复制原料库的成分与价格数值。** 它们取自原料库数据文件（`src/data/`）——需要具体数值请
> **调用命令**取得，不要引用本文档里的数字。

> **门面版本：1.1.0（2026-10-17）** · 本版行为变更：`moisturePercent` 硬下限 1%（`<1` 入参校验失败、exit 2）；
> 新增 `energy.meNRCAlt` / `meNRCAltGeRatio` 等**备选尿能口径**字段（仅并列展示，不参与判定）。

## 1. 参数详表

**传参注意**：参数含空格或中文时，用单引号把整个 JSON 包住（Windows cmd 下用双引号）。

`recipe`

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `items` | array | 是 | — | 配方条目；每项 `{ name 或 code, weight(克) }`。**name 与 code 二选一** |
| `species` | string | 否 | `dog` | `cat` / `dog`（决定能量口径） |
| `moisturePercent` | number | 否 | — | 成品水分 %，**硬下限 1**（上限 <100）。给定时按**干物质守恒**折算：湿基各项 ×k、水分 = 目标值、**干基组成不变**；省略 = 沿用原料加权水分。⚠ `<1` 视为无效（成品不可能零水分）⇒ 引擎**不施加并回退**，结果里标 `moistureAdjust.reason = 'below_min_moisture'`；物理越界（`<0` 或 `≥100`）标 `'out_of_range'` |
| `airDryMoisturePercent` | number | 否 | `3` | 风干参照水分 %（取值 `[0,100)`）。供结果里的 `airDry` 使用：`a = 干基 × (100 − w_ad) ÷ 100`。⚠ 与 `moisturePercent` **互不相干** —— 前者是「按什么口径放齐了比」的参照，后者是「成品实际含多少水」；**取同值时风干列会与湿基列逐格相同**。非法值 ⇒ `airDry.available = false`（不兜底、不出数） |
| `priceOverrides` | object | 否 | — | 价格覆盖表（键为编号或名称，值 ¥/kg） |

`ingredients`：`query`（关键词，省略则返回前 N 条）、`limit`（默认 20）。

`requirements`：`species`（默认 `cat`）、`weightKg`（必填）、`ageMonths` 或 `ageText`、`status`、`activity`、`breed`。

`analyze-label`：`asFed`（必填，原样基础营养值 `%`：crude_protein / crude_fat / crude_fiber / crude_ash / moisture / calcium / phosphorus / chloride）、`species`。

`evaluate`：`recipe`（recipe 命令的返回 data）、`req`（requirements 的返回 data）。

**参数面真源**：`cli/lib/paramSchema.mjs` 与各门面的 `buildCommands(api)`；
`node scripts/cli.mjs <命令> --help` 由该真源渲染。本文表格与之不一致时，以命令输出为准。

## 2. 输出字段（`recipe`）

| 字段 | 说明 |
|------|------|
| `ok` | 是否算成功；`false` 时看 `reason` |
| `lines[]` | 逐条原料：`code` / `name` / `weight` / `share`(%) / `price` / 各成分 |
| `totalWeight` | 配方总重（克） |
| `asFed` / `dm` / `dmPercent` | 原样基础 / 干物质基础 / 干物质含量(%) |
| `airDry` | **风干基础（ADB）**：`{ available, refMoisture, basis:'air-dry-basis', items, nfe, note }`。把干基值归一到统一的参照水分口径，便于**跨产品比较**。`available:false` 时 `items` 与 `refMoisture` 均为 `null`（参照水分非法 ⇒ 不兜底） |
| `moistureAdjust` | 成品水分折算结果；未给 `moisturePercent` 时为 `null`。**已施加**：`{ applied:true, sourceMoisture, targetMoisture, sourceDmPercent, targetDmPercent, scale, sourceCoverage, lowConfidence, note }`（`scale` 是**未取整**的精确 k）。**未施加**：`{ applied:false, reason, target, note }`，`reason` ∈ `out_of_range`（`<0` 或 `≥100`）/ `below_min_moisture`（`[0,1)`，另带 `min`）/ `no_ingredient_moisture` / `zero_dry_matter`。⚠ `applied:false` 时 `asFed`/`dm` **回退原料加权口径**，但 `energy.ge`/`de`/`meNRC` **照常出数**（「输入存在但无效」不等于「缺数据」） |
| `nfe` | 无氮浸出物 % |
| `energy` | 能量全谱：`meModified`（AAFCO 标签口径，判定挂它）/ `meAtwater` / `meNRC`（NRC 三步法，**主计算口径**）/ `meNRCAlt`（**备选尿能口径** PLOS One 2019 系数算出，仅并列展示、不参与判定）/ `ge` / `de` / `meGeRatio`（改良 Atwater 的 ME÷GE）/ `meNRCGeRatio`（NRC 三步法的 ME÷GE）/ `meNRCAltGeRatio` / `digestibility`。⚠ **两个 ME:GE 口径不同、数值不同**，引用时必须带口径名 |
| `caPRatio` | 钙磷比（原样与干物质基） |
| `cost` | `total` / `perKg` / `missingPrice[]` |
| `coverage` / `coverageSummary` / `dataGaps` | 数据覆盖率与缺口 |
| `zeroData[]` | 缺成分数据的原料名（进结果时按 0 计，会让数值偏低） |
| `unknown[]` | 没在库里找到的原料（本门面额外返回，**必须向用户转述**） |

## 3. 可运行示例

```bash
# 按关键词查原料
node scripts/cli.mjs ingredients '{"query":"鸡大胸","limit":5}'

# 按编号精确查
node scripts/cli.mjs ingredients '{"query":"01020271"}'

# 算配方营养（可混用名称与编号）
node scripts/cli.mjs recipe '{"items":[{"code":"01020271","weight":300},{"name":"鸡脂油","weight":50}],"species":"cat"}'

# 指定成品水分 5%（干物质守恒折算）+ 风干参照水分 3%（得 airDry 风干基础）
node scripts/cli.mjs recipe '{"items":[{"code":"01020271","weight":300},{"name":"鸡脂油","weight":50}],"species":"cat","moisturePercent":5,"airDryMoisturePercent":3}'

# 4kg 成年猫的需求
node scripts/cli.mjs requirements '{"species":"cat","weightKg":4,"ageMonths":24}'

# 管道写法（避免转义问题）
echo '{"query":"鸡"}' | node scripts/cli.mjs ingredients --stdin
```
