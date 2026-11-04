# junheng-attainment · 详细接口参考

> 本文件是 `SKILL.md` 的**非规范性**详参：参数表、输出字段表、可运行示例。
> 规范契约（目的与边界、诚实性红线、命令一览、退出码、技能分工、拒答与替代路径 R1–R4）**仍在 `SKILL.md`**，
> 两者冲突时以 `SKILL.md` 为准。
>
> ⚠ **本文件不复制限值数值与判定公式。** 判定全部来自 `src/lib/nutrition.js` 的 `evaluateRecipe`
> （限值真源见 `src/lib/standards.js`）——需要具体结论请**调用命令**取得，不要引用本文档里的数字。

## 1. 参数详表

**传参注意**：参数含空格或中文时，用单引号把整个 JSON 包住（Windows cmd 下用双引号）。

`assess`

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `items` | array | **是** | 配方条目 `{ name 或 code, weight(克) }`，每项至少给一个标识 |
| `profile` | object | 否 | 目标画像，缺省按全站默认（物种缺省值 + 中国 GB + 成年维持档） |

**`profile` 字段**：

| 字段 | 说明 |
|---|---|
| `species` | `cat` / `dog`（缺省取 species.js 的 `DEFAULT_SPECIES`） |
| `market` | 目标市场模式（缺省 `cn`）—— 决定**同时满足哪些体系、取最严** |
| `status` | 生理状态；缺省由年龄推断（月龄 <12 → `growth` 生长档，**限值更严**） |
| `ageMonths` / `ageText` | 月龄 / 年龄文本（用于推断阶段） |
| `weightKg` | 体重 kg —— **只影响 MER 需求，不影响限值档位** |
| `bcs` / `activity` / `breed` | 体况 / 活动量 / 品种 |

> **水分形态不入参**：由本配方**实测水分**自动判定（湿性产品适用更严的牛磺酸下限）。

`targets` 无参数。

**参数面真源**：`cli/lib/paramSchema.mjs` 与各门面的 `buildCommands(api)`；
`node scripts/cli.mjs <命令> --help` 由该真源渲染。本文表格与之不一致时，以命令输出为准。

## 2. 输出字段（`assess`）

| 字段 | 说明 |
|---|---|
| `ok` | 评估是否**执行成功**（注意：配方未达标时它**仍是 true** —— 未达标是结论不是错误） |
| `target` | 本次判定用的口径：`species`/`stage`/`marketId`/`sourceLabel`/`stageLabel`/`wetFood` |
| `summary` | `{ total, ok, low, fail, nodata, judged, allPass, fullyVerified }` —— **先看这里** |
| `attained[]` | 达标项（精简行） |
| `gaps[]` | **未达标项 + 缺口**：每行含 `value`/`min`/`max`/`target`/`coverage` + `gap{direction,amount}` |
| `lowCoverage[]` | 达标但数据不足的项（附 `note` 说明覆盖率） |
| `undecided[]` | **无法判定**项（附原因：库无字段 / 本配方算不出） |
| `suggestions[]` | 配比建议（原样来自 evaluateRecipe，含具体添加量；覆盖率过低时不会给数字） |
| `unknown[]` | 没在库里找到的原料（**必须转述给用户**） |
| `warnings[]` | 标准体系的告警（如某体系待核对、条款区间无交集） |

## 3. 可运行示例

```bash
# 先看有哪些目标市场可选
node scripts/cli.mjs targets '{}'

# 4kg 成年猫，按中国 GB 判定
node scripts/cli.mjs assess '{
  "items": [{"code":"01020271","weight":300},{"name":"鸡脂油","weight":50}],
  "profile": {"species":"cat","weightKg":4,"ageMonths":24}
}'

# 同样配方，改判「国标 + 国际」双体系（取最严）
node scripts/cli.mjs assess '{
  "items": [{"code":"01020271","weight":300}],
  "profile": {"species":"cat","market":"cn_plus_intl"}
}'

# 管道写法
echo '{"items":[{"code":"01020271","weight":300}]}' | node scripts/cli.mjs assess --stdin
```
