# junheng-energy · 详细接口参考

> 本文件是 `SKILL.md` 的**非规范性**详参：参数表、输出字段表、可运行示例。
> 规范契约（目的与边界、诚实性红线、命令一览、退出码、拒答与替代路径 R1–R4）**仍在 `SKILL.md`**，
> 两者冲突时以 `SKILL.md` 为准。
>
> ⚠ **本文件不复制能量系数与出处的数值/原文。** 唯一真源是项目内 `src/lib/energy.js`
> （如 `GE_FACTORS_KJ`）。需要具体系数或条款原文请**调用命令**（`factors` / `cites`）取得。

## 1. 参数详表

**传参注意**：参数含空格或中文时，用单引号把整个 JSON 包住（Windows cmd 下用双引号）。

`profile`

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `asFed` | object | 是 | — | 原样基础常规成分 %，**至少给一项**。子字段：`crude_protein` / `crude_fat` / `crude_fiber` / `crude_ash` / `moisture`，均为 0~100 数字 |
| `species` | string | 否 | `dog` | `cat` / `dog`（决定消化率方程与尿能扣减系数） |
| `dmPercent` | number | 否 | 100 − 水分 | 干物质含量 %；给了就用它 |
| `moistureCoverage` | number | 否 | `1` | 水分覆盖率 0~1；小于 1 时结果标 `reliable: false` |

`rer`：`kg`（必填，0.1~200）、`species`。
`ge`：`asFed`（必填）、`dmPercent`。
`digestibility`：`cfPercentDM`（必填，粗纤维干物质基 %）、`species`。
`factors` / `cites`：无参数。

**参数面真源**：各门面的 `buildCommands(api)`；`node scripts/cli.mjs <命令> --help` 由该真源渲染。
本文表格与之不一致时，以命令输出为准。

## 2. 输出字段（`profile`）

| 字段 | 说明 |
|------|------|
| `ge` / `geDM` / `geKJ` / `gePer100g` | 总能（原样基础 / 干物质基 / kJ / 每 100g）；水分缺失时为 `null` |
| `de` / `deDM` | 消化能；水分缺失时为 `null` |
| `meModified` / `meModifiedDM` | 代谢能（改良 Atwater，**AAFCO 标签算法**，判定口径） |
| `meAtwater` | 代谢能（经典 Atwater，仅作参照，非标签算法） |
| `meNRC` / `meNRCDM` | 代谢能（NRC 三步法：GE → 消化率 → 扣尿能）。**主计算口径** |
| `meGeRatio` / `meNRCGeRatio` | ME:GE 百分比。前者是**改良 Atwater** 的 ME÷GE，后者是 **NRC 三步法**的 ME÷GE —— 两者口径不同、数值不同，引用时必须带口径名 |
| `meNRCAlt` / `meNRCAltDM` / `meNRCAltGeRatio` | 用**备选尿能口径**（PLOS One 2019）算出的 ME 与 ME:GE。**仅并列展示、不参与任何判定** |
| `urine` | 尿能口径披露块：`{ applied:{key,label,factor,cite}, alternative:{...}, disclosure, note }`。`applied.key` 恒为 `nrc2006`（= 真正算进 `meNRC` 的那套）。⚠ `disclosure` 是界面/导出的**唯一文案来源**，不要各处重拼 |
| `digestibility` / `digestibilityExtrapolated` | 能量消化率 %、是否进入外推区 |
| `cfDM` | 粗纤维干物质基 % |
| `nfe` / `carbPercent` | 无氮浸出物 / 碳水（含粗纤维）% |
| `source[]` / `sourceBasis` | 供能比（蛋白/脂肪/碳水）与口径说明 |
| `ok` / `reliable` / `noMoisture` / `moistureCoverage` / `note` | 状态与原因 —— **先看这几个字段再看数值** |
| `cites` | 各口径出处 |

## 3. 可运行示例

```bash
# 成年猫配方（含水分）—— 常规成分给全，GE/DE/ME 都能出
node scripts/cli.mjs profile '{"asFed":{"crude_protein":30,"crude_fat":15,"crude_fiber":3,"crude_ash":7,"moisture":10},"species":"cat"}'

# 只给蛋白和脂肪：ME(Atwater) 有值，GE/DE/NRC 为 null（ok:false + note 说明缺水分）
node scripts/cli.mjs profile '{"asFed":{"crude_protein":30,"crude_fat":15},"species":"cat"}'

# 4kg 猫的静息能量需求
node scripts/cli.mjs rer '{"species":"cat","kg":4}'

# 粗纤维 12%DM（超过 10 的外推线，返回 digestibilityExtrapolated=true）
node scripts/cli.mjs digestibility '{"species":"dog","cfPercentDM":12}'

# 查系数与出处
node scripts/cli.mjs factors
node scripts/cli.mjs cites

# 管道写法
echo '{"species":"dog","kg":10}' | node scripts/cli.mjs rer --stdin
```
