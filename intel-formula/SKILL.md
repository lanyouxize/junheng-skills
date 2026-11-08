---
name: intel-formula
description: 配方剂量核对。把带单位的剂量归一到质量分数（%/‰/ppm/mg-kg/g-kg 互算），显式化口径（占总重/占干物质）后与参照区间比对，输出档位结论，支持整张配方表批量核对。当用户问添加量换算、高低判定或口径归属时使用。
description_en: Formulation dose cross-check — normalize dosed amounts to mass fraction across units, make the basis (product weight vs dry matter) explicit, locate the value within reference bands, and batch-check a whole formulation table row by row.
license: Proprietary
compatibility: Node.js 18+.
---

# 配方剂量核对（intel-formula）

## 目的与边界

**做什么**：把配方里的实际用量与参照值放在一起看，**只做方向核对** —— 给出「你的值落在参照区间的哪一段」。

**不做什么**：

- **不下达标/不达标结论** —— 那是判定结论，与参照值「不是判定依据」的定位冲突。参照值会随标准修订过期，正式引用前请回来源原文核对版本。
- **不猜量纲** —— 口径（`myBasis`）必填且**无默认**：口径猜错会得出系统性偏差结论（DM 与产品总重差一个水分因子，湿粮与干粮的同一个数字换算后能差 10% 以上）。
- **不把子指标压成一个区间** —— 一条参照值底下常有多个子指标（如 `aafco-cat-essential` 有 5 个可比项）。压区间会造出**不存在的上下限**（牛磺酸「成年 0.10%」与「生长 0.20%」是两个下限，不是区间），因此必须用 `metric` 指名。
- **不猜单位** —— 裸数（`12`）一律不解析（`parsed: null`），因为无法判断它是 % 还是 ppm。

## 诚实性红线

1. **`basis` 恒为 `reference-direction`** —— 方向核对，**不给**达标/不达标结论。
2. **口径必须显式**。`myBasis` 缺失即拒绝执行，不设默认值。
3. **档位措辞按参照值形态分开**。`point`（一个试验水平，如对照组 6% TdF）**不是下限** —— 说「低于参照下限」是错的；内核按形态给出不同措辞，不要自己改写。
4. **「核不了」与「还没做」必须分开**。`table` 的 `empty`（未填写）/ `unpicked`（填了用量没选参照值）/ `refused`（做了但被拒绝）是三件不同的事；`summary.pending` 只含前两者。
5. **`mine` 与 `refId` 在 `table` 里刻意可选** —— 强制必填会把「还没做」误判成错误，正好破坏内核要防的「漏行静默」。

## 用法

在技能根目录下执行：

```
node scripts/cli.mjs <命令> '<JSON 参数>'
node scripts/cli.mjs <命令> --stdin          # 参数从标准输入读
node scripts/cli.mjs --help
node scripts/cli.mjs <命令> --help
```

## 命令一览

| 命令 | 用途 |
|------|------|
| `dose` | 解析一条带单位剂量文本，归一到质量分数（无单位不猜） |
| `convert` | 剂量单位互算（同一量纲内，如 500 ppm → 0.05%） |
| `locate` | 把用量放进某参照值的某个子指标，给出区间档位 |
| `check` | 与参照值完整比对（额外回显参照值本体的口径与来源） |
| `table` | 整张配方表逐行核对（**补充能力**，见下） |
| `refs` | 列出可核对的子指标 + 被跳过项的原因 |
| `describe` | 输出机器可读的接口说明 |

### 关于 `table`（补充能力）

`table` 是**补充能力**：本批方案书原始命令清单未包含它，由 OD-04 裁决纳入。
纳入理由：内核 `checkFormulaTable` 已导出但**从未被 85 个服务端路由与浏览器侧暴露**；它是「批量上限」这条防线的唯一落点，且直接针对「漏行是静默的」这一失效模式 —— 漏掉的行根本没进过界面，不会报错。

它**未经与其它命令同等的评审**，请按此预期使用。`table --help` 与本文件均已标注这一点。

## 参数

`dose`

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `text` | string | 是 | — | 带单位的剂量文本，如 `0.3%` / `3000 ppm` |
| `basis` | string | 否 | `productWeight` | 口径（只影响 `basisHint` 文案，不影响比较结果） |

`convert`

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `value` | number | 是 | 数值（≥0） |
| `from` | string | 是 | 源单位 |
| `to` | string | 是 | 目标单位 |

单位枚举（9 个）：`%` `％` `‰` `ppm` `ppmw` `mg/kg` `ug/kg` `g/kg` `kg/t`

`locate` / `check`

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `mine` | string | 是 | 实际用量，**必须带单位** |
| `myBasis` | string | 是 | 口径：`productWeight` / `dryMatter`（**无默认**） |
| `refId` | string | 是 | 参照值 id（内核运行时派生，共 10 个） |
| `metric` | string | 否 | 子指标标签原文；一条参照值有多个子指标时**必须**指名 |

`table`（补充能力）

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `rows` | array | 是 | 配方表行，1..200 行；每行可为 `{name?, mine?, refId?, metric?, myBasis?}` |

`refs`

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `group` | string | 否 | 全部 | `urine` / `aafco` / `fiber` / `label` |
| `myBasis` | string | 否 | `productWeight` | 口径（决定哪些参照值可比） |

## 退出码

| 退出码 | 含义 |
|--------|------|
| 0 | 成功。注意：**「解析不出」也是 0** —— 请看 `data.parsed` 与 `data.note`，不要只看退出码 |
| 1 | 内部错误（未预期异常） |
| 2 | 用法或输入错误，命令未执行（缺 `myBasis`、`refId` 拼错会附候选清单、`metric` 缺省会列出全部候选标签、超上限会给出上限值） |
| 3 | 前置条件缺失（源码镜像未同步） |

**域内负结果不是错误**：无单位（`dose`）、口径不可比、子指标不存在 —— 一律 `ok:true` + 退出码 0，并在 `data` 里带 `reason` 与 `advice`。

## 示例

```bash
# 剂量归一：2% 的菊粉 = 质量分数 0.02
node scripts/cli.mjs dose '{"text":"添加 2% 的菊粉"}'

# 无单位不猜：parsed 为 null，退出码仍是 0
node scripts/cli.mjs dose '{"text":"12"}'

# 单位互算：500 ppm = 0.05%
node scripts/cli.mjs convert '{"value":500,"from":"ppm","to":"%"}'

# 与 AAFCO 矿物质参照值比对（该条有 8 个子指标，必须指名 metric）
node scripts/cli.mjs check '{"mine":"0.3%","myBasis":"dryMatter","refId":"aafco-minerals","metric":"犬 · 生长与繁殖 · 钙（最低 / 最高）"}'

# 口径必填：缺 myBasis 直接拒绝并报出参数名
node scripts/cli.mjs check '{"mine":"0.3%","refId":"aafco-minerals"}'

# refId 拼错会给候选清单
node scripts/cli.mjs locate '{"mine":"0.3%","myBasis":"productWeight","refId":"aafco-mineral"}'

# 整表核对（补充能力）：空行/未选参照值/被拒绝 三态分别可见
node scripts/cli.mjs table '{"rows":[{"name":"菊粉","mine":"2%","refId":"hairball-fiber-dose","metric":"试验组 1","myBasis":"productWeight"},{"name":"还没填"},{"name":"只填了量","mine":"0.3%"}]}'

# 查有哪些子指标可核、哪些被跳过及原因
node scripts/cli.mjs refs '{"myBasis":"productWeight"}'

# 管道写法
echo '{"text":"3000 ppm"}' | node scripts/cli.mjs dose --stdin
```

## 维护

- 本技能目录下的 `scripts/vendor/{formula.js,reference-values.js}` 是 `src/lib/` 对应文件的**只读镜像**
  （逐字节复制）。**禁止**直接改镜像 —— 改逻辑一律改源文件再重新同步；否则 `--check` 会报 `MIRROR_TAMPERED`。
- **改了 `src/lib/**`（含 `formula.js` / `reference-values.js`）就必须跑 `npm run skills:check`**，
  确认镜像与源一致；不一致时跑 `npm run skills:sync` 重新同步。该脚本**只读**，可随时运行。
- `scripts/cli.mjs` 由 `cli/formula.mjs` 生成；`SKILL.md` 由 `cli/skills/intel-formula/SKILL.md` 生成。
  改逻辑改源文件，不要改技能目录里的副本。
- **单位枚举是「带守卫的镜像」**：内核 `UNIT_SUFFIX` 未导出，故 `cli/formula.mjs` 内固定声明 9 个单位，
  并由守卫断言逐个验证内核认得。增删单位**必须先改内核**，再同步本数组 ——
  只改数组会让守卫变红（这是有意的）。
- 新增/删除命令后，`SKILL.md` 的命令表必须与 `describe` 返回的命令集**双向相等**。

## 拒答与替代路径

> 本节是**可机检**的边界契约（规范与判据见 `docs/contracts/boundary-contract.md`）。
> 命中某一类时，按该类「话术」回复并给出「替代」路径；标「不适用」的类必须写明本技能层面的理由。

### R1 非犬猫物种
- **触发**：询问非犬猫物种的剂量参照值或方向核对。
- **话术**：本技能的参照值只覆盖犬与猫，对其它物种没有可比对的区间。
- **替代**：单位换算（同一量纲内）与物种无关，可照常用；方向核对请改用该物种的参照来源。

### R2 医疗诊断
- **触发**：要求据剂量给出治疗、用药或安全性结论。
- **话术**：本技能只做方向核对，不下达标结论也不给用药建议。
- **替代**：请咨询执业兽医；剂量归一到质量分数本技能可直接算。

### R3 超出已收录法规体系
- **触发**：要求按未收录体系的参照值核对。
- **话术**：该体系的参照值未收录，我无法给出可比对的子指标。
- **替代**：可用已收录参照值做方向核对；待该体系补录后再查，正式引用前请回来源原文核对版本。

### R4 数据缺口（`nodata`）
- **触发**：口径（`myBasis`）缺失，或输入是无单位的裸数。
- **话术**：口径必填且无默认，裸数我不解析 —— 猜口径或猜单位都会造成系统性偏差。
- **替代**：请给出量纲口径与单位；本技能会把 `parsed: null` 与跳过原因原样报出。
