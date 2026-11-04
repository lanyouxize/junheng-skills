# junheng-labeling · 详细接口参考

> 本文件是 `SKILL.md` 的**非规范性**详参：参数表、输出字段表、可运行示例。
> 规范契约（目的与边界、诚实性红线、工作流、命令一览、失败处理、拒答与替代路径 R1–R4）**仍在 `SKILL.md`**，
> 两者冲突时以 `SKILL.md` 为准。
>
> ⚠ **本文件不复制法规条款、限值数值与保证值项目顺序。** 它们的唯一真源是项目内
> `src/lib/standards.js`（条款已核对 GB/T 31216-2014 / 31217-2014）。需要具体项目与限值请**调用命令**取得。

## 1. 参数详表

**传参注意**：参数含空格或中文时，用单引号把整个 JSON 包住（Windows cmd 下用双引号）。

| 命令 | 参数（必填加 **粗**） |
|------|------|
| `draft` | **`recipe`** · **`req`** · `meta`（产品名 / 品牌 / 净含量 / 批号 / 生产商 / 日期） |
| `guaranteed` / `ingredients-list` | **`recipe`** · **`req`** |
| `render` / `coverage` | **`draft`**（`draft` 命令返回的 data） |
| `disclaimers` / `describe` | 无 |

**参数面真源**：各门面的 `buildCommands(api)`；`node scripts/cli.mjs <命令> --help` 由该真源渲染。
本文表格与之不一致时，以命令输出为准。

## 2. 输出字段（`draft`）

| 字段 | 说明 |
|------|------|
| `ok` / `reason` | 是否生成成功；失败时给原因（配方未算成功 / 缺 req） |
| `formatVersion` | 稿件格式版本（改排版或字段口径时递增，便于回溯） |
| `product` | 产品元信息 |
| `guaranteed` | 营养保证值表（已按法规要求的项目与顺序过滤排序） |
| `ingredients` | 配料表（按占比降序） |
| `compliance` | 逐项合规结论（来自 `evaluateRecipe` 的 status） |
| `energy` | 标签口径能量（原样基础 ME，kcal/kg） |
| `internal` | 供研发核对：总重 / 成本-kg / 行数（**不属于标签内容**） |
| `risks[]` | 风险提示（超限项、缺数据项）—— **必须转述** |
| `disclaimers[]` | 必须随稿给出的声明 |

其余命令（`guaranteed` / `ingredients-list` / `render` / `coverage` / `disclaimers`）的字段以 `describe` 输出为准。

## 3. 可运行示例

> 下面每一行都**可直接执行**（在本技能根目录下）。不需要上游产物的排在最前。
> ⚠ `draft` / `guaranteed` / `ingredients-list` 的 `recipe` / `req` **只能**来自
> `junheng-nutrition` 的返回 `data` —— 手捏的瘦对象会被形状校验以 `exit 2` 拒绝。

```bash
# ① 不需要上游产物：声明清单 / 接口说明 / 帮助
node scripts/cli.mjs disclaimers
node scripts/cli.mjs describe
node scripts/cli.mjs --help
node scripts/cli.mjs draft --help
```

```bash
# ② 取真实上游产物（跑这两条拿到 data，就是 draft 要传的东西）
node ../junheng-nutrition/scripts/cli.mjs recipe '{"items":[{"code":"01020271","weight":300}],"species":"cat"}'
node ../junheng-nutrition/scripts/cli.mjs requirements '{"species":"cat","weightKg":4}'
```

```bash
# ③ 一行式串联出底稿：算配方 → 算需求 → 合成入参 → draft（全程不落盘）
{ node ../junheng-nutrition/scripts/cli.mjs recipe '{"items":[{"code":"01020271","weight":300}],"species":"cat"}'; node ../junheng-nutrition/scripts/cli.mjs requirements '{"species":"cat","weightKg":4}'; } | node -e "let s='';process.stdin.on('data',c=>s+=c).on('end',()=>{const[a,b]=s.trim().split('\n').map(x=>JSON.parse(x).data);console.log(JSON.stringify({recipe:a,req:b}))})" | node scripts/cli.mjs draft --stdin
```

```bash
# ④ 在 ③ 的管道末端再接一段，渲染成可直接粘贴的纯文本
{ node ../junheng-nutrition/scripts/cli.mjs recipe '{"items":[{"code":"01020271","weight":300}],"species":"cat"}'; node ../junheng-nutrition/scripts/cli.mjs requirements '{"species":"cat","weightKg":4}'; } | node -e "let s='';process.stdin.on('data',c=>s+=c).on('end',()=>{const[a,b]=s.trim().split('\n').map(x=>JSON.parse(x).data);console.log(JSON.stringify({recipe:a,req:b}))})" | node scripts/cli.mjs draft --stdin | node -e "let s='';process.stdin.on('data',c=>s+=c).on('end',()=>console.log(JSON.stringify({draft:JSON.parse(s).data})))" | node scripts/cli.mjs render --stdin
```
