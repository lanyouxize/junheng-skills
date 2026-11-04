# junheng-optimize · 详细接口参考

> 本文件是 `SKILL.md` 的**非规范性**详参：参数表、输出字段表、可运行示例。
> 规范契约（目的与边界、诚实性红线、命令一览、失败处理、拒答与替代路径 R1–R4）**仍在 `SKILL.md`**，
> 两者冲突时以 `SKILL.md` 为准。
>
> ⚠ **参数面与状态面的真源都不在本文件**：参数真源是 `cli/optimize.mjs` 的 `buildCommands(api)`，
> 求解状态枚举真源是 `src/lib/optimizer.js` 的 `LP_STATUS`，诊断状态真源是 `src/lib/optimizerDiagnose.js`。
> 下表与之不一致时，以 `node scripts/cli.mjs <命令> --help` 与 `describe` 的输出为准。

## 1. 参数详表

**传参注意**：参数必须是一个 JSON 对象；含空格或中文时，用单引号把整个 JSON 包住（Windows cmd 下用双引号）。

`solve` / `diagnose` 用**同一套模型输入**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `variables[]` | array | 是 | 决策变量（每种原料一个），至少 1 项 |
| `constraints[]` | array | 是 | 线性约束，至少 1 项 |
| `maxIterations` | number | 否 | 迭代上限；一般不用给 |

`variables[]` 的字段：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | 是 | 变量名（即原料名，必须唯一） |
| `cost` | number | 是 | 单位成本（目标系数，最小化） |
| `lower` | number | 否 | 用量下界（缺省 0） |
| `upper` | number | 否 | 用量上界（缺省不限） |
| `coefficients[]` | array | 否 | 本变量在各约束里的系数，形如 `[{"constraint":"蛋白","value":65}]`；**未列出的约束按 0 计** |

`constraints[]` 的字段：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | 是 | 约束名（必须唯一，变量的系数按它对应） |
| `lower` | number | 否 | 下界（**与 `upper` 至少给一个**） |
| `upper` | number | 否 | 上界 |
| `weight` | number | 否 | 松弛权重（仅 `diagnose` 用，缺省 1；越大越不愿松这条） |

## 2. 输出字段

| 字段 | 说明 |
|------|------|
| `status` | `optimal` / `infeasible` / `unbounded` / `iteration_limit` / `verify_failed` / `bad_input` |
| `ok` | 仅在 `optimal` 为 `true` |
| `objective` | 最低成本（仅 `optimal`） |
| `values[]` | 每个变量的取值与其所在界（`basic` / `lower` / `upper`）、`reducedCost` |
| `constraintValues[]` | 每条约束的实际取值与是否满足 |
| `shadowPrices[]` | 每条约束的对偶值：`binding` 表示是否绑定，`activity` 是余量（仅 `optimal`） |
| `variableMarginals[]` | 变量的边际（`reducedCost`）与所在界（仅 `optimal`） |
| `conflicts[].constraints[]` | 诊断：极小冲突集（删掉其中任意一条，模型即变可行） |
| `relaxation.items[]` | 诊断：最小松弛量（每条约束要松多少才可行） |

## 3. 可运行示例

```bash
# 三种原料、两条约束，求最省配比
node scripts/cli.mjs solve '{
  "variables": [
    {"name":"鸡肉粉","cost":12.5,"upper":40,"coefficients":[{"constraint":"蛋白","value":65},{"constraint":"总量","value":1}]},
    {"name":"鸡脂油","cost":8,"upper":20,"coefficients":[{"constraint":"总量","value":1}]},
    {"name":"马铃薯淀粉","cost":3,"coefficients":[{"constraint":"总量","value":1}]}
  ],
  "constraints": [
    {"name":"总量","lower":100,"upper":100},
    {"name":"蛋白","lower":28}
  ]
}'

# 约束冲突时（x+y≥10 与 x+y≤4 同时成立不可能），先看哪几条打架
node scripts/cli.mjs diagnose '{
  "variables": [
    {"name":"鸡粉","cost":1,"coefficients":[{"constraint":"a","value":1},{"constraint":"b","value":1}]},
    {"name":"豆粕","cost":1,"coefficients":[{"constraint":"a","value":1},{"constraint":"b","value":1}]}
  ],
  "constraints": [{"name":"a","lower":10},{"name":"b","upper":4}]
}'

# 管道写法（避免转义问题）
echo '{"variables":[{"name":"x","cost":1}],"constraints":[{"name":"c","lower":1}]}' | node scripts/cli.mjs solve --stdin
```
