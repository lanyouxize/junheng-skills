# junheng-feeding · 详细接口参考

> 本文件是 `SKILL.md` 的**非规范性**详参：参数表、输出字段表、可运行示例。
> 规范契约（目的与边界、诚实性红线、命令一览、退出码、拒答与替代路径 R1–R4）**仍在 `SKILL.md`**，
> 两者冲突时以 `SKILL.md` 为准。
>
> ⚠ **本文件不复制能量口径与 BCS 策略的数值配置。** 能量计算取自 `src/lib/`（`computeFeedingPlan` 等），
> BCS 判据表取自 `src/lib/bcsChart.js` —— 需要具体数值请**调用命令**取得，不要引用本文档里的数字。

## 1. 参数详表

**传参注意**：参数含空格或中文时，用单引号把整个 JSON 包住（Windows cmd 下用双引号）。

`plan`

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `profile` | object | 是 | — | 个体档案，见下 |
| `recipe` | object | 否 | — | `junheng-nutrition` 的 `recipe` 返回 data；**给了它才能出克/日** |
| `req` | object | 否 | — | `junheng-nutrition` 的 `requirements` 返回 data |

`profile` 子字段：`species`（`cat`/`dog`，默认 `cat`）、`weightKg`（**必填**）、`ageMonths` 或 `ageText`、`status`、`bcs`（1~9）、`activity`。

`bcs-policy`：`score`（必填，整数 1~9）、`species`（默认 `dog`）。

`ideal-weight`：`currentKg`（必填）、`score`（必填，整数）。

`transition`：`days`（默认 7）、`grams`（给了才换算成具体克数）。

`monitoring`：`score`（必填）、`species`、`stage`。

`plan-multi` / `purchase-list`（多宠聚合，两者参数面相同）

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `pets` | array | 是 | — | 宠物条目（1~20 条），元素字段见下 |
| `days` | number | 否 | 30 | 采购口径天数（1~365） |

`pets[]` 元素：`label`（宠物标签，采购清单按它追溯「哪只用了哪个物料」）、`name`、`profile`（**必填**，子字段同 `plan`）、`recipe`、`req`、`unmatched`。

`unmatched` 元素：`rawName`（**必填**，用户原样写的原料名）、`weight`（配方里的份量）。

> ⚠ **`unmatched` 不能省** —— `recipe.lines` 只含**命中原料库**的条目。库外原料
> （`parseRecipeText` 里 `ingredient: null` 的那些）若不一并传进来，会有两个后果：
> 采购清单**不会列出**它们（静默少买），且**安全闸筛不到**它们（库里查不到的禁用原料会漏网）。

**参数面真源**：`cli/lib/paramSchema.mjs` 与各门面的 `buildCommands(api)`；
`node scripts/cli.mjs <命令> --help` 由该真源渲染。本文表格与之不一致时，以命令输出为准。

## 2. 输出字段（`plan`）

| 字段 | 说明 |
|------|------|
| `ok` / `species` / `speciesLabel` | 结果状态与物种 |
| `pet` | 个体档案（归一化后） |
| `stage` | 生命阶段 |
| `bodyCondition` | 体况评估块（含 BCS 判定与调整幅度） |
| `bcsChart` | 该物种的体况判据 |
| `idealWeight` | 理想体重估算 |
| `energy` | 能量目标（RER / MER / 调整后） |
| `meals` | 餐次建议 |
| `ladder` | **喂食阶梯**（不同能量口径 / 克重下的克数对照） |
| `intake` | 每日摄入量（克/日） |

> ⚠ 具体字段名以 `node scripts/cli.mjs plan --help` 的参数表与 `describe` 输出为准。

## 2b. 输出字段（`plan-multi` / `purchase-list`）

| 字段 | 说明 |
|------|------|
| `ok` / `days` / `petCount` / `okCount` / `failedCount` | 总状态与口径 |
| `pets[]` | 每只的摘要：`label` / `ok` / `failReason` / `gramsPerDay` / `kcalPerDay` / `ingredients[]`（`code`/`name`/`share`/`grams`） / `unmatched[]` |
| `totals` | 合计。**只累加 `ok:true` 的宠物**（算不出的按 0 计入会得到一个假总量）；`costNote` 说明金额是否被低估 |
| `purchase.items[]` | 合并采购清单：`code` / `name` / `gramsPerDay` / `grams` / `kg` / `pets[]` / `pricePerKg` / `priceConflict` / `cost` |
| `purchase.unmatched[]` | 未匹配原料。`estimatedGramsPerDay` 是**按输入占比反推的估算值**（不是验算值） |
| `purchase.note[]` | 口径提示（无编号归并、单价冲突、估算值、损耗与分装余量） |
| `safety[]`（仅 `plan-multi`） | 逐宠安全筛查结论；`caution`/`unknown` 一并带出，不阻断但必须看得见 |

> ⚠ `purchase-list` 只返回 `ok`/`days`/计数/`reason`/`purchase`/`warnings`，**不含 `pets` 明细与 `safety`**。
> 需要逐宠明细或安全结论时用 `plan-multi`。

## 2c. 输出字段（`portion-label`）

**参数**：`pets[]`（同 `plan-multi`，多一个可选 `recipeName`：贴纸上的配方名）、`days`（默认 30）、
`portionDays`（每袋覆盖天数，默认 7 = 按周）、`filledDate`（分装日期 `YYYY-MM-DD`，缺省今天）、
`shelfLifeDays`（保质期天数）、`form`（`frozen_raw` / `frozen_cooked` / `dry` / `wet`）。

| 字段 | 说明 |
|------|------|
| `filledDate` / `portionDays` | 同日分装的口径：**所有标签共用同一个 `filledDate`**，食用期限均由此起算 |
| `schedules[]` | 每条（每宠）的排期摘要：`recipeName` / `petLabel` / `gramsPerDay` / `totalGrams` / `portionCount` / `ok` / `reason` |
| `labels[]` | 贴纸字段：`recipeName` / `petLabel` / `seq` / `portionCount` / `grams` / `daysCovered` / `filledDate` / `useByDate` / `shelfLifeDays` / `shelfLifeMissing` / `form` / `thawNote` |
| `text` | 全部标签拼成的纯文本（可直接打印） |
| `labelCount` | 标签张数（=== Σ `schedules[].portionCount`） |
| `failedPets[]` | 未算出喂食量的宠物（**未参与分装**，不按 0 出 0 克贴纸） |

> ⚠ **`useByDate` 只在给了 `shelfLifeDays` 时才有值**；未给则为 `null` 且 `shelfLifeMissing: true`，
> 贴纸上印「待定（未提供保质期，请按产品实际保质期填写）」。本命令**不猜保质期**。
> ⚠ **克数守恒**：Σ(该条全部标签 `grams`) === 该条 `totalGrams`（末袋吸收舍入余量）。
> ⚠ 末袋覆盖天数不足时 `daysCovered < portionDays`（例：30 天 ÷ 每袋 7 天 ⇒ 5 袋，末袋 2 天）。
> ⚠ 这是**厨房贴纸**，不是合规标签；合规标签用 `junheng-labeling draft`。

## 3. 可运行示例

```bash
# 完整喂食计划（4kg 成年猫、BCS 5 分）
node scripts/cli.mjs plan '{"profile":{"species":"cat","weightKg":4,"ageMonths":24,"bcs":5}}'

# 7 分的猫 —— 会进入减重策略
node scripts/cli.mjs bcs-policy '{"score":7,"species":"cat"}'

# 估算理想体重
node scripts/cli.mjs ideal-weight '{"currentKg":5.5,"score":7}'

# 7 天换粮过渡
node scripts/cli.mjs transition '{"days":7,"grams":60}'

# 就医信号
node scripts/cli.mjs vet-signals

# 多宠合并采购清单（recipe 从 junheng-nutrition 的 recipe 命令取，此处省略以保持可读）
node scripts/cli.mjs purchase-list '{"days":30,"pets":[
  {"label":"狗-大金","profile":{"species":"dog","weightKg":10,"bcs":5},"recipe":{},"unmatched":[{"rawName":"马铃薯淀粉","weight":100}]},
  {"label":"猫-小白","profile":{"species":"cat","weightKg":4,"bcs":5},"recipe":{}}
]}'

# 分装排期 + 分装标签（按周分装；不给 shelfLifeDays ⇒ 食用期限留空）
node scripts/cli.mjs portion-label '{"days":30,"portionDays":7,"shelfLifeDays":30,"form":"frozen_raw","pets":[
  {"label":"狗-大金","recipeName":"鲜鸡犬粮","profile":{"species":"dog","weightKg":10,"bcs":5},"recipe":{}}
]}'

# 管道写法
echo '{"profile":{"species":"cat","weightKg":4}}' | node scripts/cli.mjs plan --stdin
```

