---
name: junheng-standards
description: 宠物营养法规限值查询。按目标市场、物种、生命阶段与水分形态返回应同时满足的合并限值（蛋白、脂肪、灰分、纤维、钙磷、赖氨酸、牛磺酸、代谢能等），每项带条款出处与各体系原值；也可单查条款原文。问 AAFCO 下限、国标要求时使用。
description_en: Chinese and international pet food nutrient limit lookup (GB/T 31216, GB/T 31217, AAFCO, FEDIAF) by market mode, species, life stage and moisture class; returns merged limits with clause citations, or a single clause's original text.
author: Junheng NutriAgent
version: 1.0.0
---

# 法规限值查询（junheng-standards）

## 目的与边界

**做什么**：回答「某类宠物食品在某市场、某生命阶段下，某营养项的限值是多少、出自哪一条」。

**不做什么**（明确边界，避免误用）：

- **不判定某个配方是否达标** —— 本技能只给限值，不给配方结论。需要判定请用配方营养计算能力。
- **不返回检测值** —— 全部是条文引用值。
- **不提供 AAFCO 现行版本年份的结论** —— AAFCO 数值尚未与官方出版物逐项核对（`verified: false`）。
- **FEDIAF 不参与判定** —— 其主表以「每 MJ 代谢能」为基准，本轮数值待补，只登记不判。

## 诚实性红线

1. **限值必须有出处**。每个条目都带 `cites`（条款出处）。引用时请连同出处一起给，不要只给数字。
2. **未核对的体系必须显式标注**。AAFCO 条目 `verified: false`，输出中会带 `note`；不得把它的数值当作已确认结论对外交付。
3. **不可计算不等于通过**。系统无数据支撑的项目（如赖氨酸、牛磺酸）会返回 `available: false`、`active: false`，**绝不会**被算作「达标」。
4. **换法规版本只改一个地方**。限值的唯一真源是项目内 `src/lib/standards.js`；改版本时改它并重新同步，不要在本技能内直接改数据。

## 用法

```
node scripts/cli.mjs <命令> '<JSON 参数>'    # 参数必须是一个 JSON 对象
node scripts/cli.mjs <命令> --stdin          # 参数从标准输入读（避免 shell 转义问题）
node scripts/cli.mjs --help                  # 全部命令与退出码
```

## 命令一览

| 命令 | 用途 |
|------|------|
| `list-markets` | 列出目标市场模式（决定要同时满足哪些标准体系） |
| `list-sets` | 列出已登记的标准体系及其可信度状态 |
| `resolve` | 解析合并后的营养限值表（多体系取最严，逐项带出处） |
| `clause` | 查单一营养项的条款原文与出处 |
| `classify-moisture` | 按水分百分比判定形态分级 |
| `describe` | 输出机器可读的接口说明（命令、参数、退出码） |

**参数详表、输出字段表、可运行示例、水分形态分级** → [详细接口参考](references/interface-reference.md)。

## 失败处理（退出码）

| 退出码 | 含义 |
|--------|------|
| 0 | 成功，结果在 stdout 的 JSON 里 |
| 1 | 内部错误（未预期异常，属 bug，请保留 stderr 原文） |
| 2 | 用法或输入错误：命令名、JSON 语法、参数名或参数值不合法，命令未执行 |
| 3 | 前置条件缺失：源码目录不可读（技能镜像未同步） |

失败时 stdout 为空，stderr 是一行 JSON：`{"ok":false,...,"error":{"kind","message","details"}}`。
`error.details[]` 逐条给出出错的参数路径与原因，按它逐项修正即可。

## 拒答与替代路径

> 本节是**可机检**的边界契约（规范与判据见 `docs/技能边界与拒答契约_2026-10-13.md`）。
> 命中某一类时，按该类「话术」回复并给出「替代」路径；标「不适用」的类必须写明本技能层面的理由。

### R1 非犬猫物种
- **触发**：询问对象不是犬或猫（如兔、貂、爬宠、异宠），或要求套用非犬猫的参考体系。
- **话术**：本技能收录的限值体系仅覆盖犬与猫，对其它物种无法给出可靠限值。
- **替代**：请使用该物种的专属营养标准并咨询兽医营养师；本技能仍可查已收录原料的成分事实（不含物种适用性判断）。

### R2 医疗诊断
- **触发**：询问疾病诊断、治疗、用药或处方剂量。
- **话术**：本技能只提供营养项限值与条款出处，不构成诊断或处方。
- **替代**：请咨询执业兽医；如需核对配方在已收录法规下的限值，本技能可直接用。

### R3 超出已收录法规体系
- **触发**：询问的市场或体系不在已收录清单内（如 AAFCO 未完成官方核对、FEDIAF 主表待补）。
- **话术**：该体系本版本未收录或未完成核对，我不能给出它的限值结论。
- **替代**：可给出已核对体系的同名营养项作为对照；待该体系核对完成后再查。

### R4 数据缺口（`nodata`）
- **触发**：询问的营养项在库中无字段支撑（如赖氨酸、牛磺酸）。
- **话术**：该项**无法判定** —— 这不等于达标，也不等于未达标。
- **替代**：请补充该项的实测值或换用有数据的原料；本技能会原样报出 `available:false`，不省略。

<!-- i18n:en:begin -->

# Standards Limit Lookup (junheng-standards)

## Purpose and scope

**What it does**: answer "for this kind of pet food, in this market, at this life stage, what is the limit for this nutrient, and which clause does it come from".

**What it does not do** (explicit boundaries, to prevent misuse):

- **Does not decide whether a recipe passes** — this skill returns limits only, never a recipe verdict. For a verdict use the recipe nutrition computation capability.
- **Does not return measured values** — every value is a clause citation.
- **Does not give a conclusion for the current AAFCO edition year** — AAFCO values are not yet reconciled item by item against the official publication (`verified: false`).
- **FEDIAF takes no part in judging** — its main table is based on "per MJ of metabolisable energy"; values are pending this round, so it is registered but not judged.

## Honesty red lines

1. **Every limit must carry a source.** Each entry carries `cites`. Quote the source together with the number; never give the number alone.
2. **Unverified systems must be marked explicitly.** AAFCO entries carry `verified: false` and an accompanying `note`; they must not be delivered as confirmed conclusions.
3. **Not computable is not a pass.** Items without data support (e.g. lysine, taurine) return `available: false` / `active: false` and are **never** counted as compliant.
4. **Regulation versions change in one place only.** The single source of truth for limits is `src/lib/standards.js`; edit it and re-sync, do not patch data inside this skill.

## Usage

```
node scripts/cli.mjs <command> '<JSON args>'   # args must be one JSON object
node scripts/cli.mjs <command> --stdin         # read args from stdin (avoids shell escaping)
node scripts/cli.mjs --help                    # all commands and exit codes
```

## Commands

| Command | Purpose |
|------|------|
| `list-markets` | List market modes (which standards must be satisfied together) |
| `list-sets` | List registered standards and their verification status |
| `resolve` | Resolve the merged limit table (strictest across systems, each with a source) |
| `clause` | Look up one nutrient's clause text and source |
| `classify-moisture` | Classify product form by moisture percentage |
| `describe` | Emit the machine-readable interface description (commands, args, exit codes) |

Parameter tables, output field tables and runnable examples → [interface reference](references/interface-reference.md).

## Failure handling (exit codes)

| Exit code | Meaning |
|--------|------|
| 0 | Success; the result is JSON on stdout |
| 1 | Internal error (unexpected exception, a bug — keep the raw stderr) |
| 2 | Usage or input error: command name, JSON syntax, argument name or value invalid; command not executed |
| 3 | Missing precondition: source directory unreadable (skill mirror not synced) |

On failure stdout is empty and stderr is one line of JSON: `{"ok":false,...,"error":{"kind","message","details"}}`.
`error.details[]` lists each failing argument path and reason; fix them item by item.

## Refusal and alternatives

> This section is a machine-checkable boundary contract (spec and checks in `docs/技能边界与拒答契约_2026-10-13.md`).
> When a class is hit, reply with that class's response and give the alternative path.

### R1 Non-dog/cat species
- **Trigger**: the subject is not a dog or cat (rabbit, marten, reptile, exotic pet), or a non-dog/cat reference system is requested.
- **Response**: the limit systems collected here cover dogs and cats only; for other species no reliable limit can be given.
- **Alternative**: use that species' dedicated nutrition standard and consult a veterinary nutritionist; ingredient facts already collected remain queryable (without species applicability judgement).

### R2 Medical diagnosis
- **Trigger**: questions about disease diagnosis, treatment, medication or prescription dosage.
- **Response**: this skill provides nutrient limits and clause sources only; it constitutes neither diagnosis nor prescription.
- **Alternative**: consult a licensed veterinarian; to check a recipe against collected regulations this skill still applies.

### R3 Beyond the collected regulatory systems
- **Trigger**: the market or system asked about is not in the collected list (e.g. AAFCO not yet officially reconciled, FEDIAF main table pending).
- **Response**: that system is not collected or not reconciled in this version; I cannot state its limit conclusions.
- **Alternative**: the same nutrient from reconciled systems can be given for comparison; re-query once that system is reconciled.

### R4 Data gap (`nodata`)
- **Trigger**: the nutrient has no supporting field in the library (e.g. lysine, taurine).
- **Response**: that item **cannot be judged** — which is neither compliant nor non-compliant.
- **Alternative**: supply a measured value for that item or switch to an ingredient that has data; this skill reports `available:false` verbatim and never omits it.

<!-- i18n:en:end -->
