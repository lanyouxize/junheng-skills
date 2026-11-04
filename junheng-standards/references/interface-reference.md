# junheng-standards · 详细接口参考

> 本文件是 `SKILL.md` 的**非规范性**详参：参数表、输出字段表、可运行示例、水分形态分级。
> 规范契约（目的与边界、诚实性红线、命令一览、退出码、拒答与替代路径 R1–R4）**仍在 `SKILL.md`**，
> 两者冲突时以 `SKILL.md` 为准。
>
> ⚠ **本文件不复制法规限值的数值与条款原文。** 它们的唯一真源是项目内 `src/lib/standards.js`
> （理由见 `SKILL.md` 诚实性红线第 4 条）。需要具体数值请**调用命令**取得，不要引用本文档里的数字。

## 1. 参数详表

**传参注意**：参数含空格或中文时，用单引号把整个 JSON 包住（Windows cmd 下用双引号）。

### `resolve`

| 参数 | 类型 | 必填 | 默认 | 允许值 |
|------|------|------|------|--------|
| `marketId` | string | 否 | `cn` | `cn` / `cn-intl` / `intl` |
| `species` | string | 否 | `cat` | `cat` / `dog` |
| `stage` | string | 否 | `adult` | `growth` / `adult` |
| `moistureClass` | string | 否 | `unknown` | `dry` / `semi-moist` / `wet` / `unknown` |

### 其它命令

| 命令 | 参数 |
|------|------|
| `clause` | `setId`（必填）、`key`（必填）、`species`、`stage` |
| `classify-moisture` | `moisture`（必填，0~100 的数字） |
| `list-markets` / `list-sets` | 无参数 |

`stage` 说明：生长、妊娠、泌乳在中国 GB 的分组里同属一档，统一用 `growth`。

**参数面真源**：`cli/lib/paramSchema.mjs` 与各门面的 `buildCommands(api)`。
`node scripts/cli.mjs <命令> --help` 由该真源**递归渲染**；本文表格与之不一致时，以命令输出为准。

## 2. 输出字段（`resolve`）

| 字段 | 说明 |
|------|------|
| `marketId` / `marketLabel` / `marketDesc` | 实际生效的市场模式（传了非法值会回落到默认值） |
| `setIds` / `setLabels` | 本次**实际参与判定**的体系 |
| `items[]` | 逐项限值 |
| `items[].key` / `.label` / `.unit` / `.kind` | 项目标识、名称、单位、类型（min 下限 / max 上限 / range 区间） |
| `items[].min` / `.max` / `.text` | 合并后的下限、上限、展示文案 |
| `items[].sources` | 各体系的原值文案（如 `{"CN-GB":"≥25.0"}`） |
| `items[].cites` | 条款出处数组 |
| `items[].available` / `.active` | 系统是否有该项数据 / 是否参与自动判定；`available:false` 表示**不可判定**，不是「未达标」 |
| `items[].wetApplied` | 是否因湿粮档启用了更严下限 |
| `warnings` | 需要注意的提示（含未核对体系、无数据项目、区间冲突） |

## 3. 水分形态分级（`classify-moisture`）

| 形态 | 判定 | 依据 |
|------|------|------|
| `dry` 干性 | 水分 < 14.0% | GB/T 31216 表3 / GB/T 31217 表2 |
| `semi-moist` 半湿性 | 14.0% ≤ 水分 < 60.0% | 同上 |
| `wet` 湿性 | 水分 ≥ 60.0% | 同上 |

上表是该命令输出的人类可读摘要；**实际判定以 `classify-moisture` 的返回为准**（真源 `src/lib/standards.js`）。

## 4. 可运行示例

```bash
# 成年猫、仅国标、干性
node scripts/cli.mjs resolve '{"species":"cat","stage":"adult","moistureClass":"dry"}'

# 幼犬、国标+国际双标（取最严）
node scripts/cli.mjs resolve '{"marketId":"cn-intl","species":"dog","stage":"growth"}'

# 成年猫湿粮 —— 牛磺酸会启用更严的湿粮下限，返回里 wetApplied=true
node scripts/cli.mjs resolve '{"species":"cat","stage":"adult","moistureClass":"wet"}'

# 单查一条：中国 GB 成年猫的粗蛋白
node scripts/cli.mjs clause '{"setId":"CN-GB","species":"cat","stage":"adult","key":"crude_protein"}'

# 水分 32% 属于什么形态（半湿性）
node scripts/cli.mjs classify-moisture '{"moisture":32.04}'

# 管道写法（避免转义问题）
echo '{"species":"dog"}' | node scripts/cli.mjs resolve --stdin
```
