# junheng-pipeline · 详细接口参考

> 本文件是 `SKILL.md` 的**非规范性**详参：参数表、输出字段表、可运行示例、单步管道 `--as` 用法。
> 规范契约（目的与边界、诚实性红线、命令一览、退出码、技能分工、拒答与替代路径 R1–R4）**仍在 `SKILL.md`**，
> 两者冲突时以 `SKILL.md` 为准。
>
> ⚠ **本文件不复制各步的计算公式与数值。** 全部数值来自 `src/lib/` 的既有函数（编排层无独立算法）——
> 需要具体结果请**调用命令**取得，不要引用本文档里的数字。

## 1. 参数详表

**传参注意**：参数含空格或中文时，用单引号把整个 JSON 包住（Windows cmd 下用双引号）。

`run`

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `items` | array | **是** | 配方条目 `{ name 或 code, weight(克) }` |
| `profile` | object | 否 | 个体档案：`species` / `weightKg` / `ageMonths` / `ageText` / `status` / `bcs` / `activity` / `breed` |
| `meta` | object | 否 | 产品元信息（进标签稿）：`productName` / `brand` / `netWeight` / `batchNo` / `manufacturer` / `date` |
| `cost` | object | 否 | 成本口径：`mode`(`general`/`freeze_dry`/`cat_stick`) / `batchCount` / `gramPerBag` / `yieldKg` / `inputKg` / `outputKg` / `lossRate` / `processingFeePerTon` / `specId` / `packageGram` |

**哪些步骤需要什么**（`steps` 命令可直接查）：

| 步骤 | 需要 | 来源 |
|---|---|---|
| `recipe` | `items` | `computeRecipe` |
| `requirements` | `profile.weightKg` | `computeRequirements` |
| `labeling` | `recipe` + `req` + `meta` | `buildLabelDraft` |
| `cost` | `recipe` + `cost` | `computeCostSheetByMode` |
| `feeding` | `profile` + `recipe` | `computeFeedingPlan` |

**参数面真源**：`cli/lib/paramSchema.mjs` 与各门面的 `buildCommands(api)`；
`node scripts/cli.mjs <命令> --help` 由该真源渲染。本文表格与之不一致时，以命令输出为准。

`run-multi`（多宠入口）

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `pets` | array | **是** | 每只一条：`label` / `name` / `profile`（**必填**，字段同 `run` 的 `profile`）/ `items`（**必填**，该宠自己的配方原料 `{ name 或 code, weight(克) }`） |
| `days` | number | 否 | 总量/采购覆盖天数，默认 30 |
| `portionDays` | number | 否 | 每袋覆盖天数，默认 7（按周分装） |
| `filledDate` | string | 否 | 分装日期 `YYYY-MM-DD`（缺省今天；同日分装共用） |
| `shelfLifeDays` | number | 否 | 保质期天数。**不传 ⇒ 建议食用期限留空**（不猜） |
| `form` | string | 否 | `frozen_raw` / `frozen_cooked` / `dry` / `wet`；不传则提示语明说「请按实际形态填写」 |

> ⚠ 与 `junheng-feeding` 的 `plan-multi` / `portion-label` 的差别：那两个命令的 `pets[]` 收的是
> **上游算好的 `recipe` 对象**；`run-multi` 收的是**原始 `items`**（pipeline 的立身之本是「从原料出发」）。

## 2. 输出字段（`run`）

| 字段 | 说明 |
|---|---|
| `ok` | 全部步骤都成功才为 true |
| `summary` | `{ total, ok, skipped, failed }` —— **先看这里** |
| `steps[]` | 每步：`step` / `status` / `reason` / `data`（`data` 结构与对应单技能一致） |
| `unknown[]` | 没在库里找到的原料（**必须转述给用户**） |
| `note` | 有失败或跳过时的总体说明 |

## 2b. 输出字段（`run-multi`）

| 字段 | 说明 |
|---|---|
| `ok` | 全部步骤都成功才为 true |
| `summary` | `{ total, ok, skipped, failed, petCount, petOkCount, petFailedCount, labelCount }` —— **先看这里** |
| `steps[]` | 固定四步：`safety`（逐宠安全闸）/ `recipes`（逐宠配方与需求）/ `multiPlan`（喂食量 + 合计 + 采购清单）/ `portions`（分装排期与标签） |
| `steps[].data` | 与对应单技能一致：`multiPlan` 同 `junheng-feeding plan-multi`，`portions` 同 `portion-label` |
| `note` | 有宠物未算出喂食量时，**点名是哪几只**并说明它们未计入总量/采购/分装 |

> ⚠ `portions` 里另带 `failedPets[]`：未算出喂食量的宠物**不会**被分装成 0 克贴纸，而是单独报出。

## 3. 可运行示例

```bash
# 只看会跑哪些步骤、各需要什么（不计算）
node scripts/cli.mjs steps '{}'

# 完整评估：配方 + 4kg 成年猫 BCS5 + 通用成本口径
node scripts/cli.mjs run '{
  "items": [{"code":"01020271","weight":300},{"name":"鸡脂油","weight":50}],
  "profile": {"species":"cat","weightKg":4,"ageMonths":24,"bcs":5},
  "meta": {"productName":"测试猫粮"},
  "cost": {"mode":"general","batchCount":1000,"gramPerBag":50}
}'

# 只算配方与营养（最小调用，其余步骤会标 skipped 并说明原因）
node scripts/cli.mjs run '{"items":[{"code":"01020271","weight":300}]}'

# 多宠入口：两只宠从原料出发 → 喂食量 + 合计 + 采购清单 + 同日分装标签
node scripts/cli.mjs run-multi '{
  "days": 30, "portionDays": 7, "shelfLifeDays": 30, "form": "frozen_raw",
  "pets": [
    {"label":"狗-大金","profile":{"species":"dog","weightKg":10,"ageMonths":24,"bcs":5},
     "items":[{"code":"01020271","weight":700},{"name":"鸡脂油","weight":300}]},
    {"label":"猫-小白","profile":{"species":"cat","weightKg":4,"ageMonths":24,"bcs":5},
     "items":[{"code":"01020271","weight":300},{"name":"鸡脂油","weight":100}]}
  ]
}'

# 管道写法
echo '{"items":[{"code":"01020271","weight":300}]}' | node scripts/cli.mjs run --stdin
```

## 4. 单步管道：`--as`

任一技能都支持 `--as <参数名>`：把读到的 JSON **直接当作该参数**。上游输出的是信封
`{ok, skill, ..., data}`，`--as` 会**自动剥到 `data`**，所以单步串联可以直接写成：

```bash
node cli/nutrition.mjs recipe '{"items":[...]}' \
  | node cli/labeling.mjs guaranteed --stdin --as recipe
```

> `--as` 只解**单上游**。需要两个上游（如 `draft` 同时要 `recipe` 与 `req`）时用本门面。
