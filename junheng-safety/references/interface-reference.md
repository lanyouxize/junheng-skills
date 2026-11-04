# junheng-safety · 详细接口参考

> 本文件是 `SKILL.md` 的**非规范性**详参：参数表、输出字段表、可运行示例。
> 规范契约（目的与边界、诚实性红线、用法、命令一览、退出码、拒答与替代路径 R1–R4）**仍在 `SKILL.md`**，
> 两者冲突时以 `SKILL.md` 为准。
>
> ⚠ **本文件不复制有毒有害物质的条目与来源。** 四态判定、`conditions`、`basis`、`sources` 均取自
> 种子表 `src/data/toxicSubstances.js`（唯一真源）—— 需要具体条目请**调用命令**取得，
> 不要引用本文档里的任何结论。

## 1. 参数详表

**传参注意**：参数含空格或中文时，用单引号把整个 JSON 包住（Windows cmd 下用双引号）。

`check`

| 参数 | 类型 | 必填 | 默认 | 允许值 |
|------|------|------|------|--------|
| `name` | string | 是 | — | 物质或原料名（中英文均可，支持别名） |
| `species` | string | 否 | `cat` | `cat` / `dog` |

`screen`：`items`（必填，至少一项，形如 `[{"name":"洋葱","weight":5}]`）、`species`。
`list-substances`：`species`、`category`、`level`，均可选。
`list-sources`：无参数。

**参数面真源**：各门面的 `buildCommands(api)`；`node scripts/cli.mjs <命令> --help` 由该真源渲染。
本文表格与之不一致时，以命令输出为准。

## 2. 输出字段

| 字段 | 说明 |
|------|------|
| `level` | 四态之一：`banned` / `caution` / `ok` / `unknown` |
| `substance` / `latin` / `category` | 命中的条目名、学名、类别 |
| `conditions` | `caution` 条目必带：什么条件下才可用 |
| `basis` | 判定依据（事实陈述） |
| `sources[]` | 来源四元组：`org` / `item` / `url` / `fetchedAt` |
| `summary.blocked` | 批量筛查：是否命中禁用（命中即该配方不应给出） |
| `summary.unjudged` | 批量筛查：未收录条目的数量（**这些还没判过**，需人工确认） |

## 3. 可运行示例

```bash
# 木糖醇对犬 —— 禁用
node scripts/cli.mjs check '{"name":"木糖醇","species":"dog"}'

# 百合对猫 —— 禁用（来源仅支持猫；同样的查询换成 dog 会返回 unknown）
node scripts/cli.mjs check '{"name":"百合","species":"cat"}'

# 批量筛查一份猫配方
node scripts/cli.mjs screen '{"species":"cat","items":[{"name":"鸡胸肉","weight":100},{"name":"洋葱粉","weight":2}]}'

# 只看对猫适用、类别为 plants 的条目
node scripts/cli.mjs list-substances '{"species":"cat","category":"plants"}'

# 管道写法（避免转义问题）
echo '{"name":"葡萄","species":"dog"}' | node scripts/cli.mjs check --stdin
```
