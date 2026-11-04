---
name: junheng-labeling
description: 配方 → 合规标签底稿：营养保证值表（法规项目与顺序，带条款出处）、配料表（按重量递减）、合规结论与风险提示。当用户问「帮我做一份标签底稿」「营养保证值怎么写」「这个配方合不合规」时使用。
description_en: "Generate a compliant pet food label draft from a recipe: guaranteed analysis table (regulated items in order, with clause citations), ingredient list (descending by weight), per-item compliance status, risk notes and mandatory disclaimers."
metadata:
  author: Junheng NutriAgent
  version: "1.0.0"
compatibility: Requires Node.js 18+ (ESM) and a UTF-8 filesystem. No network access and no third-party dependencies. Loads its computation closure from the sibling shared-core skill junheng-core via the relative path ../../junheng-core/.
---

# 标签底稿生成（junheng-labeling）

## 目的与边界

**做什么**：把「配方数值」排成一份**符合法规项目与顺序要求**的标签底稿，并给出逐项合规结论。

**不做什么**：

- **不是最终合规结论** —— 产物是**底稿**，提交前必须人工与现行法规原文逐条核对。
- **不自己发明数值** —— 限值全部来自 `standards.js`（条款已核对 GB/T 31216-2014 / 31217-2014）。
- **不给无数据项下结论** —— 库缺氨基酸等字段的项进 `nodata` 段，**既不算达标也不算未达标**。
- **不改配方** —— 本技能只呈现，不替你调整配方去满足限值。
- **不做 OCR** —— 读标签图片请用相应的视觉能力。

## 诚实性红线

1. **是底稿不是定稿**。每次输出都要连 `disclaimers` 一起转述，不得表述成「已合规」。
2. **未核对的体系必须显式标注**。AAFCO 数值尚未与官方出版物逐项核对（`verified: false`）。
3. **不可计算不等于通过**。`nodata` 项必须原样报出，不得省略、不得当作达标。
4. **风险提示必须转述**。`risks[]` 列出「不能直接印」的原因（如超限、缺数据），是使用者最容易漏看的部分。
5. **配料表排序可追溯**。按占比降序；并列重量时**保持用户录入顺序**（法规对并列无规定）。

## 工作流（三步，顺序不可颠倒）

| 步 | 命令 | 输入 → 输出 |
|---|------|------------|
| 1 | `junheng-nutrition recipe` | `items[]` → **recipe data** |
| 2 | `junheng-nutrition requirements` | `species` / `weightKg` → **req data** |
| 3 | **本技能 `draft`** | `{"recipe":…,"req":…}` → **draft data** |

第 3 步之后分两条支路：`render` / `coverage` 只吃第 3 步的 `draft`；`guaranteed` /
`ingredients-list` 只吃第 1、2 步的 `recipe` + `req`（不需要 `draft`）。两路都不必重跑前序。

**中间产物不能手捏**：第 1~3 步的 `data` 是**形状契约**的一部分 —— `draft` 校验 `recipe` 的
`dmPercent` / `asFed.crude_protein` / `energy.meModified` / `lines[]`；`render` / `coverage` 校验
`draft` 的 `product` / `basis` / `guaranteed.rows` / `ingredients.items` / `risks[]`。缺任一项会被
`exit 2` **点名拒绝**，而不是产出一份半截稿子。

> 想一步跑完 1~3 步（外加成本与喂食），用 `junheng-pipeline` 的 `run`。

## 用法

在技能根目录下执行 `node scripts/cli.mjs <命令> '<JSON 参数>'`（或 `--stdin` / 管道传参；
`--help` 与 `<命令> --help` 分别看全部命令与该命令的参数表）。

> ⚠ 依赖共享内核 `junheng-core`。报「找不到源码目录」时先跑 `node scripts/sync-skills.mjs`。

## 命令一览

| 命令 | 用途 |
|------|------|
| `draft` | 生成完整标签底稿（保证值 + 配料表 + 合规 + 风险 + 声明） |
| `guaranteed` | 只取营养保证值表 |
| `ingredients-list` | 只取配料表 |
| `render` | 把底稿渲染成可直接粘贴的纯文本 |
| `coverage` | 查底稿覆盖率（哪些项有据可依、哪些缺数据） |
| `disclaimers` | 查必须随稿给出的声明清单 |
| `describe` | 输出机器可读的接口说明 |

**参数详表、输出字段表、可运行示例** → [详细接口参考](references/interface-reference.md)。

## 失败处理（退出码）

| 退出码 | 含义 |
|--------|------|
| 0 | 成功，结果在 stdout 的 JSON 里 |
| 1 | 内部错误（未预期异常） |
| 2 | 用法或输入错误，命令未执行 |
| 3 | 前置条件缺失（共享内核未同步） |

**形状校验（`exit 2` 的常见来源）**：`draft` / `guaranteed` / `ingredients-list` 会校验 `recipe`
是否为 `junheng-nutrition` 的**完整 data**；`render` / `coverage` 会校验 `draft` 是否为 `draft`
命令的**完整 data**。传「`ok:true` 但字段不全」的**瘦对象**会被就地拒绝并**点名缺失字段**，
不会崩进内核（2026-10-11 之前 `render` / `coverage` 缺这条守卫，会 `exit 1` 且只报
`Cannot read properties of undefined`，已修）。

**域内负结果不是错误**：配方没算成功（`recipe.ok === false`）或底稿没生成成功
（`draft.ok === false`）都返回 `exit 0`，由内核给出原因（`reason` / 「标签稿生成失败：…」），
**不要**当成参数错误反复重试。

## 拒答与替代路径

> 本节是**可机检**的边界契约（规范与判据见 `docs/技能边界与拒答契约_2026-10-13.md`）。
> 命中某一类时，按该类「话术」回复并给出「替代」路径；标「不适用」的类必须写明本技能层面的理由。

### R1 非犬猫物种
- **触发**：为犬猫以外的物种生成标签底稿。
- **话术**：本技能的标签项目与顺序按犬猫食品法规组织，对非犬猫物种不适用。
- **替代**：请改用该物种适用的标签法规；本技能对已收录原料的占比排序逻辑仍可参考。

### R2 医疗诊断
- **触发**：要求声明产品具有疗效、诊断或治疗作用。
- **话术**：标签底稿不承载任何诊断或治疗声明，我也不会为其生成这类表述。
- **替代**：请咨询兽医与法规人员；成分与限值部分本技能可以照常出稿。

### R3 超出已收录法规体系
- **触发**：要求按未收录的标签法规出稿。
- **话术**：该法规体系未收录在案，我不能生成它的项目与顺序。
- **替代**：可先出已收录体系（GB/T 31216-2014 / 31217-2014）的底稿作为参照骨架。

### R4 数据缺口（`nodata`）
- **触发**：库缺氨基酸等字段，无法判定该项是否合规。
- **话术**：该项进 `nodata` 段 —— 既不算达标也不算未达标。
- **替代**：请补充该原料的实测值；本技能会把 `nodata` 与 `risks[]` 一并报出，不省略。

<!-- i18n:en:begin -->

# Label Draft Generation (junheng-labeling)

## Purpose and scope

**What it does**: lay out recipe values as a label draft that follows the **regulated item order**, and give a per-item compliance conclusion.

**What it does not do**:

- **Not a final compliance verdict** — the output is a **draft**; reconcile every item against the current regulation text before submission.
- **Does not invent values** — all limits come from `standards.js` (clauses reconciled against GB/T 31216-2014 / 31217-2014).
- **Does not conclude on items without data** — items lacking library fields such as amino acids go into `nodata`, counted as **neither compliant nor non-compliant**.
- **Does not change the recipe** — this skill presents only; it will not adjust the recipe to meet limits.
- **Does not do OCR** — read label images with the appropriate vision capability.

## Honesty red lines

1. **A draft, not a final document.** Always relay `disclaimers`; never phrase the output as "already compliant".
2. **Unverified systems must be marked explicitly.** AAFCO values are not yet reconciled item by item against the official publication (`verified: false`).
3. **Not computable is not a pass.** `nodata` items must be reported verbatim, never omitted or treated as passing.
4. **Risk notes must be relayed.** `risks[]` lists why the draft "cannot be printed directly" (over-limit, missing data) — the part users most often overlook.
5. **Ingredient ordering is traceable.** Descending by share; for equal weights **keep the user's input order** (regulations say nothing about ties).

## Workflow (three steps, order is fixed)

| Step | Command | Input → output |
|---|------|------------|
| 1 | `junheng-nutrition recipe` | `items[]` → **recipe data** |
| 2 | `junheng-nutrition requirements` | `species` / `weightKg` → **req data** |
| 3 | **this skill's `draft`** | `{"recipe":…,"req":…}` → **draft data** |

After step 3 there are two branches: `render` / `coverage` take only step 3's `draft`; `guaranteed` /
`ingredients-list` take only steps 1-2's `recipe` + `req` (no `draft` needed). Neither branch re-runs the earlier steps.

**Intermediate data cannot be hand-made**: the `data` of steps 1-3 is part of the **shape contract** — `draft` validates
`recipe`'s `dmPercent` / `asFed.crude_protein` / `energy.meModified` / `lines[]`; `render` / `coverage` validate
`draft`'s `product` / `basis` / `guaranteed.rows` / `ingredients.items` / `risks[]`. A missing field is rejected
by name with `exit 2`, rather than producing a half draft.

> To run steps 1-3 (plus cost and feeding) in one go, use `run` from `junheng-pipeline`.

## Usage

Run `node scripts/cli.mjs <command> '<JSON args>'` in the skill root (or pass args via `--stdin` / a pipe;
`--help` and `<command> --help` show all commands and that command's parameter table).

> ⚠ Depends on the shared core `junheng-core`. If "source directory not found" appears, run `node scripts/sync-skills.mjs` first.

## Commands

| Command | Purpose |
|------|------|
| `draft` | Generate the full label draft (guaranteed analysis + ingredients + compliance + risks + disclaimers) |
| `guaranteed` | Return the guaranteed analysis table only |
| `ingredients-list` | Return the ingredient list only |
| `render` | Render the draft as paste-ready plain text |
| `coverage` | Report draft coverage (which items are sourced, which lack data) |
| `disclaimers` | Return the mandatory disclaimer list |
| `describe` | Emit the machine-readable interface description |

Parameter tables, output field tables and runnable examples → [interface reference](references/interface-reference.md).

## Failure handling (exit codes)

| Exit code | Meaning |
|--------|------|
| 0 | Success; the result is JSON on stdout |
| 1 | Internal error (unexpected exception) |
| 2 | Usage or input error; command not executed |
| 3 | Missing precondition (shared core not synced) |

**Shape validation (the usual source of `exit 2`)**: `draft` / `guaranteed` / `ingredients-list` check whether
`recipe` is the **complete data** of `junheng-nutrition`; `render` / `coverage` check whether `draft` is the
**complete data** of the `draft` command. A "skinny object" that is `ok:true` but missing fields is rejected
in place with the missing fields named, and never crashes into the core (before 2026-10-11 `render` / `coverage`
lacked this guard and would `exit 1` with only `Cannot read properties of undefined`, now fixed).

**In-domain negative results are not errors**: a recipe that did not compute (`recipe.ok === false`) or a draft
that was not produced (`draft.ok === false`) still returns `exit 0`, with the reason given by the core
(`reason` / "label draft generation failed: …"); do **not** treat them as input errors and retry.

## Refusal and alternatives

> This section is a machine-checkable boundary contract (spec and checks in `docs/技能边界与拒答契约_2026-10-13.md`).
> When a class is hit, reply with that class's response and give the alternative path.

### R1 Non-dog/cat species
- **Trigger**: generating a label draft for a species other than dog or cat.
- **Response**: this skill's label items and order follow dog and cat food regulations, and do not apply to non-dog/cat species.
- **Alternative**: switch to the label regulation applicable to that species; the descending-by-weight ordering logic still works for collected ingredients.

### R2 Medical diagnosis
- **Trigger**: asking the label to state efficacy, diagnosis or treatment.
- **Response**: a label draft carries no diagnostic or therapeutic claim, and I will not generate such wording.
- **Alternative**: consult a veterinarian and a regulatory specialist; the ingredient and limit sections can still be drafted here.

### R3 Beyond the collected regulatory systems
- **Trigger**: asking for a draft under a label regulation that is not collected.
- **Response**: that regulatory system is not collected, so I cannot generate its items and order.
- **Alternative**: a draft under a collected system (GB/T 31216-2014 / 31217-2014) can serve as a reference skeleton.

### R4 Data gap (`nodata`)
- **Trigger**: the library lacks fields such as amino acids, so compliance of that item cannot be judged.
- **Response**: that item goes into the `nodata` section — neither compliant nor non-compliant.
- **Alternative**: supply the measured value for that ingredient; `nodata` and `risks[]` are reported together and never omitted.

<!-- i18n:en:end -->
