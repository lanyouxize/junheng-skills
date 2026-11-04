---
name: intel-evidence
description: 证据颗粒度抽取。从原文抽研究设计/样本量/试验动物/终点类型/亚组限定/利益相关六字段，给出未识别清单与展示排序。当用户问「这段研究里样本量是多少」「用的什么动物做的」「哪些字段没识别出来」时使用。
description_en: Evidence granularity extraction — pull study design, sample size, test species, endpoint type, subgroup qualifier and conflict-of-interest out of a source text; report unrecognized fields and provide display ordering.
---

# 证据颗粒度（intel-evidence）

## 目的与边界

**做什么**：从一段原文里抽出六个「这个来源能不能支撑这个结论」的字段，并把**没抽到的**如实列出来。

**不做什么**：

- **不评价研究好不好** —— 六个字段记录的是「原文写了什么」，不是「这研究强不强」。`样本量 32` 不等于「结论可靠」。
- **不填默认值** —— 抽不到就是空，并在 `gaps` 里点名。留空是「没识别出来」，**不是**「原文没写」，这两件事的处置方式完全不同。
- **不判定终点类型** —— 规则通道一律留空。判定「替代终点 vs 临床终点」需要领域判断，猜错的形态是**把替代终点悄悄升级成临床终点**，比留空坏得多。
- **不合并猫与犬** —— 没有「宠物」这一档。合并后就无法回答「这条结论能不能用在只做猫的配方上」。

## 诚实性红线

1. **`basis` 恒为 `rule-channel`** —— 这是**规则通道抽取**的结果，不是对研究质量的评价。
2. **留空 = 未识别**。`meta.endpointType` 为空是**常态**，不是缺陷；界面与下游必须显式标「未识别」，不得把空字段藏起来（藏起来与「原文确实没写」长得一模一样）。
3. **两个字段空着本身就是要紧信息**：`mustShowEmpty` 恒为 `["species","endpointType"]` —— 试验动物与终点类型空着，说明这条来源**能不能支撑面向犬猫的宣称**尚不可知。
4. **不可控值按未识别处理并显式披露**。例如 `species` 传入「宠物」：内核按未识别留空，同时在 `rejectedValues` 里记下 `{field, input, reason}` —— 不能悄悄丢掉调用方给的信息。
5. **排序只回答「先看哪一条」**。`sort` 的 `sortKey.identified` 是「识别出的字段数」，不是质量评分。

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
| `meta` | 从一段原文抽取六字段 |
| `sort` | 按 evidenceSortKey 排序一批条目（识别字段多者先，其次样本量大者先） |
| `gaps` | 列出未识别字段，并标出「空着也必须说出来」的两个 |
| `designs` | 输出 8 档设计梯度 + 5 个设计大类 + 终点类型 + 受控物种与各自上限 |
| `describe` | 输出机器可读的接口说明 |

## 参数

`meta`

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `text` | string | 是 | 待抽取的原文（一句或一段），长度 1..2000 |

`sort`

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `items` | array | 是 | — | 待排序条目，1..200 项；每项可为 `{id?, text?, meta?}` |
| `by` | string | 否 | `identified` | 排序主键：`identified` / `sampleSize` |

`gaps`

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `meta` | object | 是 | 上游产出的结果对象，字段不可穷举，**原样透传** |

`designs`：无参数。

## 输出字段

| 命令 | `data` 关键字段 |
|------|----------------|
| `meta` | `meta:{studyDesign,sampleSize,species,endpointType,subgroup,conflictFlag}`、`gaps[]`、`mustShowEmpty[]`、`identified`、`hasAny`、`chips[]`、`text`、`rejectedValues[]` |
| `sort` | `items:[{id, meta, sortKey:{identified,sampleSize}, gaps}]`、`order[]` |
| `gaps` | `gaps[]`、`mustShowEmpty[]`、`identified`、`total`、`rejectedValues[]`、`note` |
| `designs` | `designs[]`(8)、`groups[]`(5)、`endpointTypes[]`(2)、`speciesValues[]`(7)、`fields[]`(6)、`limits` |

## 失败处理（退出码）

| 退出码 | 含义 |
|--------|------|
| 0 | 成功。注意：**「抽不出」也是 0** —— 请看 `gaps` 与 `hasAny`，不要只看退出码 |
| 1 | 内部错误（未预期异常） |
| 2 | 用法或输入错误，命令未执行（未知命令/参数名会附拼写建议；超上限会给出上限值） |
| 3 | 前置条件缺失（源码镜像未同步） |

**域内负结果不是错误**：原文里没有研究线索、六字段全空、物种写成「宠物」，一律 `ok:true` + 退出码 0，并在 `data` 里说清原因。

## 示例

```bash
# 抽取六字段（梯度剂量 / n=32 / 猫，endpointType 留空属常态）
node scripts/cli.mjs meta '{"text":"32只猫的梯度剂量对照试验，结果显示吐毛减少"}'

# 看哪些字段没识别出来
node scripts/cli.mjs meta '{"text":"某品牌宣称添加菊粉有助于毛发"}' | less

# 物种给了「宠物」：按未识别处理，并在 rejectedValues 里显式披露
node scripts/cli.mjs gaps '{"meta":{"species":"宠物"}}'

# 对照：合法的「猫」不会进 rejectedValues
node scripts/cli.mjs gaps '{"meta":{"species":"猫","sampleSize":32}}'

# 按识别完整度排序一批结论
node scripts/cli.mjs sort '{"items":[{"id":"a","meta":{"species":"猫","sampleSize":32}},{"id":"b","meta":{"studyDesign":"综述"}}]}'

# 查设计梯度与受控物种
node scripts/cli.mjs designs

# 管道写法（三种入参形态结果一致）
echo '{"text":"16只犬的交叉试验"}' | node scripts/cli.mjs meta --stdin
```

## 维护

- 本技能目录下的 `scripts/vendor/evidence.js` 是 `src/lib/evidence.js` 的**只读镜像**（逐字节复制）。
  **禁止**直接改镜像 —— 改逻辑一律改源文件，再重新同步；否则 `--check` 会报 `MIRROR_TAMPERED`。
- **改了 `src/lib/**`（含 `evidence.js`）就必须跑 `npm run skills:check`**，确认镜像与源一致；
  不一致时跑 `npm run skills:sync` 重新同步。该脚本**只读**，可随时运行。
- `scripts/cli.mjs` 由 `cli/evidence.mjs` 生成；`SKILL.md` 由 `cli/skills/intel-evidence/SKILL.md` 生成。
  改逻辑改源文件，不要改技能目录里的副本。
- 新增/删除命令后，`SKILL.md` 的命令表必须与 `describe` 返回的命令集**双向相等**。

## 拒答与替代路径

> 本节是**可机检**的边界契约（规范与判据见 `docs/contracts/boundary-contract.md`）。
> 命中某一类时，按该类「话术」回复并给出「替代」路径；标「不适用」的类必须写明本技能层面的理由。

### R1 非犬猫物种
- **触发**：要求把猫与犬的结论合并成「宠物」一档。
- **话术**：本技能不合并猫与犬，没有「宠物」这一档。
- **替代**：请分别抽取猫与犬的条目；合并后就无法回答这条结论能不能用在只做猫的配方上。

### R2 医疗诊断
- **触发**：要求评价研究强弱，或据此判断临床结论。
- **话术**：本技能只记录原文写了什么，不评价研究质量。
- **替代**：请用 `designs` 给出的 8 档设计梯度对照原文；本技能负责把六字段与未识别项原样列清。

### R3 超出已收录法规体系
- **不适用**：本技能抽取的是文献原文的六字段，不核对任何法规限值，也不判断法规体系收录边界。

### R4 数据缺口（`nodata`）
- **触发**：某个字段没有识别出来。
- **话术**：抽不到就是空并在 `gaps` 里点名 —— 留空是「没识别出来」，不等于「原文没写」。
- **替代**：请回原文核对；本技能会把未识别字段原样列出，不填默认值。
