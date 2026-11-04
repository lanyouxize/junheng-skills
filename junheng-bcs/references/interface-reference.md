# junheng-bcs · 详细接口参考

> 本文件是 `SKILL.md` 的**非规范性**详参：参数表、输出字段表、可运行示例。
> 规范契约（目的与边界、诚实性红线、命令一览、退出码、拒答与替代路径 R1–R4）**仍在 `SKILL.md`**，
> 两者冲突时以 `SKILL.md` 为准。
>
> ⚠ **本文件不复制 9 分制判定表与体脂率数值。** 判据真源是 `src/lib/bcsChart.js`，
> 参考图由 `src/lib/bcsFigure.js` 自绘 —— 需要具体判据请**调用命令**取得，不要引用本文档里的数字。

## 1. 参数详表

**传参注意**：参数含空格或中文时，用单引号把整个 JSON 包住（Windows cmd 下用双引号）。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `species` | string | 否 | `dog` | `dog` / `cat` |
| `score` | number | 是（`row` / `assess`） | — | 整数 1~9 |
| `typeId` | string | 是（`figure-svg`） | — | `smallDog` / `largeDog` / `cat` |
| `levelKey` | string | 是（`figure-svg`） | — | `thin` / `ideal` / `over` |
| `aria` | string | 否 | 自动生成 | SVG 的无障碍描述 |

`chart` / `figures` / `caveats` 只接 `species`（`figures` 与 `caveats` 无参数）。

**参数面真源**：`cli/lib/paramSchema.mjs` 与各门面的 `buildCommands(api)`；
`node scripts/cli.mjs <命令> --help` 由该真源渲染。本文表格与之不一致时，以命令输出为准。

## 2. 输出字段

`assess`（最常用）

| 字段 | 说明 |
|------|------|
| `species` / `score` | 归一化后的物种与分数 |
| `row` | 该分的判定行：`label` 中文名、`group` 四档归类、`fatText` / `fatMin` / `fatMax` 体脂率、`lateral` / `dorsal` / `palpation` 三列判据 |
| `isIdeal` / `idealScores` | 是否理想区、该物种的理想分数 |
| `inObesityScreeningZone` / `screeningZone` | 是否在临床肥胖筛查区（7~9） |
| `speciesNote` | 该物种的易误判点（犬/猫不同） |
| `caveats` | 可靠性边界与就医建议（**必须一并转述**） |
| `source` | 判定标准出处 |

`figure-svg` 返回 `svg`（一个完整 `<svg>` 字符串，自包含，可离线内联）。

## 3. 可运行示例

```bash
# 7 分的猫：判定行 + 筛查区标记 + 物种提示
node scripts/cli.mjs assess '{"species":"cat","score":7}'

# 只看某一分（返回结构同上）
node scripts/cli.mjs row '{"species":"dog","score":5}'

# 整张 9 行判定表
node scripts/cli.mjs chart '{"species":"cat"}'

# 大型犬偏胖档的参考图（SVG 字符串）
node scripts/cli.mjs figure-svg '{"typeId":"largeDog","levelKey":"over"}'

# 先看有哪些体型与档位可选
node scripts/cli.mjs figures

# 全部边界与出处
node scripts/cli.mjs caveats

# 管道写法
echo '{"species":"cat","score":5}' | node scripts/cli.mjs assess --stdin
```
