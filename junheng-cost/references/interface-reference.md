# junheng-cost · 详细接口参考

> 本文件是 `SKILL.md` 的**非规范性**详参：参数表、输出字段表、可运行示例、传参与串联注意。
> 规范契约（目的与边界、诚实性红线、工作流、命令一览、退出码、拒答与替代路径 R1–R4）**仍在 `SKILL.md`**，
> 两者冲突时以 `SKILL.md` 为准。
>
> ⚠ **本文件不复制价格与费用配置的数值。** 价格取自原料库、加工费/损耗率取自代码内配置
> （`FREEZE_DRY_CONFIG` / `WORKSHOP_LOSS_CONFIG`）——它们各有唯一真源。需要具体数值请**调用命令**取得，
> 不要引用本文档里的数字。

## 1. 参数详表

**传参注意**：参数含空格或中文时，用单引号把整个 JSON 包住（Windows cmd 下用双引号）。

`lines`

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `items` | array | 是 | — | 配方条目 `{ name 或 code, weight(克) }`；name 与 code 二选一 |
| `priceOverrides` | object | 否 | — | 价格覆盖表（键为编号或名称，值 ¥/kg） |
| `yields` | object | 否 | — | 收得率表（键为编号或名称，值 0~1） |

`sheet`：`lines`（必填）、`productName`、`batchCount`、`gramPerBag`、`yieldKg`、`lossRate`、`processingFeePerTon`。

`freeze-dry`：`lines`（必填）、`inputKg`、`outputKg`、`lossRate`、`packageGram`、`feesPerTon`。

`cat-stick`：`lines`（必填）、`specId`、`inputKg`、`outputKg`、`lossRate`、`extraFeePerKg`、`lossGramPerStick`、`ratesPerStick`。

> `mode` 取值必须用**下划线**形式：`general` / `freeze_dry` / `cat_stick`（不是 `freeze-dry`）。

`modes` / `format` / `describe` 无必填参数。

**参数面真源**：各门面的 `buildCommands(api)`；`node scripts/cli.mjs <命令> --help` 由该真源渲染。
本文表格与之不一致时，以命令输出为准。

## 2. 输出字段

| 字段 | 说明 |
|------|------|
| `lines[]` | 逐条成本行：`ratio` / `unitPrice` / `addAmount` / `amount` |
| `totalKg` / `inputKg` / `outputKg` | 产量或投料量（按口径） |
| `lossRate` | 损耗率 |
| `fees[]` / `feePerTon` | 逐项费用 |
| 单位成本 | 各口径字段名不同（通用为 `unitCostPerKg` 类字段、猫条另含 `perStick`），以 `describe` 的字段表为准 |
| `missingPrice[]`（来自 `lines`） | 无价格原料 —— **必须向用户提示** |
| `unknown[]`（来自 `lines`） | 库里没找到的原料 |

## 3. 可运行示例

> 下面 6 条**逐条可直接执行**（已实跑 rc=0）。第 1 条返回的 `data.lines` 就是后面各条的 `lines` 入参。

```bash
# 第 1 步：配方 → 成本行
node scripts/cli.mjs lines '{"items":[{"code":"01020271","weight":300},{"name":"鸡脂油","weight":50}]}'
# 实测 data.lines = [{"code":"01020271","name":"鸡肉粉（连云港宠贝冠）","unit":"kg","ratio":0.8571428571428571,"unitPrice":11.7,"yieldRate":1},{"code":"02010081","name":"鸡脂油","unit":"kg","ratio":0.14285714285714285,"unitPrice":11.22,"yieldRate":1}]

# 第 2 步A：通用成本表（烘焙粮）—— 需 batchCount × gramPerBag（或 yieldKg）
node scripts/cli.mjs sheet '{"productName":"测试","batchCount":1000,"gramPerBag":50,"processingFeePerTon":3000,"lines":[{"code":"01020271","name":"鸡肉粉（连云港宠贝冠）","unit":"kg","ratio":0.8571428571428571,"unitPrice":11.7,"yieldRate":1},{"code":"02010081","name":"鸡脂油","unit":"kg","ratio":0.14285714285714285,"unitPrice":11.22,"yieldRate":1}]}'

# 第 2 步B：冻干（投料 100kg → 成品 22kg）
node scripts/cli.mjs freeze-dry '{"productName":"测试冻干","inputKg":100,"outputKg":22,"lines":[{"code":"01020271","name":"鸡肉粉（连云港宠贝冠）","unit":"kg","ratio":0.8571428571428571,"unitPrice":11.7,"yieldRate":1},{"code":"02010081","name":"鸡脂油","unit":"kg","ratio":0.14285714285714285,"unitPrice":11.22,"yieldRate":1}]}'

# 第 2 步C：猫条（规格 g10，输出含元/支）
node scripts/cli.mjs cat-stick '{"productName":"测试猫条","specId":"g10","lines":[{"code":"01020271","name":"鸡肉粉（连云港宠贝冠）","unit":"kg","ratio":0.8571428571428571,"unitPrice":11.7,"yieldRate":1},{"code":"02010081","name":"鸡脂油","unit":"kg","ratio":0.14285714285714285,"unitPrice":11.22,"yieldRate":1}]}'

# 第 2 步D：统一入口（用 mode 切换口径；参数为上述四者并集）
node scripts/cli.mjs by-mode '{"mode":"general","productName":"测试","batchCount":1000,"gramPerBag":50,"processingFeePerTon":3000,"lines":[{"code":"01020271","name":"鸡肉粉（连云港宠贝冠）","unit":"kg","ratio":0.8571428571428571,"unitPrice":11.7,"yieldRate":1},{"code":"02010081","name":"鸡脂油","unit":"kg","ratio":0.14285714285714285,"unitPrice":11.22,"yieldRate":1}]}'

# 查看全部口径 id 与配置（冻干加工费、损耗率、猫条规格）
node scripts/cli.mjs modes
```

## 4. 传参与串联注意

> ⚠ **管道串联的坑**：`lines` 命令的 `data` 是对象 `{ok, lines, totalWeight, …}`，**数组在 `.lines` 上**。
> 直接写 `lines … | sheet --stdin --as lines` 会因 `not_array` 报 **rc=2**（实测）；须先取出 `.lines` 再喂给第 2 步。
