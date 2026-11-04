---
name: junheng-bcs
description: 宠物体况评分 BCS 9 分制查询与参考图生成。按物种取逐分判定表，判断某分是否落在理想区（犬 4-5、猫仅 5）或肥胖筛查区（7-9），给出易误判点与体脂率区间，并生成侧视加俯视矢量参考图。当用户问猫狗胖不胖、算几分时使用。
description_en: Pet body condition score (BCS 9-point scale) lookup and reference figure generation for dogs and cats: per-score criteria (lateral/dorsal/palpation), ideal range and obesity screening zone, species-specific pitfalls, estimated body-fat ranges, and a self-drawn side/top SVG reference figure.
metadata:
  author: Junheng NutriAgent
  version: "1.0.0"
compatibility: Requires Node.js 18+ (ESM) and a UTF-8 filesystem. No network access and no third-party dependencies. Self-contained CLI facade; no dependency on other junheng-* skills.
---

# 体况评分参考（junheng-bcs）

## 目的与边界

**做什么**：给出「某个分数对应什么外观与触感」的判据原文、是否属于理想区/筛查区、以及该物种的易误判点。

**不做什么**：

- **不做诊断**。BCS 是筛查工具；临床肥胖确诊需兽医结合肌肉状况、体重趋势、饮食史、活动能力与体检。
- **不代替实际触摸**。所有判定都要求以触摸肋骨为准；只看轮廓会被毛量、原始袋、品种骨架误导。
- **不给减重方案**。能给出的是「该不该请兽医评估」以及「猫的减重速度必须比犬更慢」这类边界提示。
- **不使用受版权保护的现成图**。本技能生成的 SVG 是按公开发表判据自绘的原创矢量图（画面与配色均为原创），不是任何机构的原图。

## 诚实性红线

1. **筛查不等于诊断**。7~9 分只是进入临床肥胖筛查区（`inObesityScreeningZone: true`），输出里必须同时给 `caveats`，不得表述成「确诊肥胖」。
2. **体脂率是近似估算**。个体误差约正负 5 个百分点；体脂超过约 45% 时 BCS 区分度明显下降，此时应改用体脂指数（BFI）、体尺测量或 DXA。
3. **犬猫理想区不同**。犬是 4~5 分，**猫只有 5 分** —— 把猫按 4 分长期饲喂等于偏瘦。
4. **非理想分数要建议就医**。任何不在理想区的评分都建议请兽医团队评估一次，不要只凭本表大幅增减喂食量或运动量。
5. **档位标注写区间，不写单点**。参考图的三档分别覆盖 1–3 / 4–5 / 6–9 分，只标单点分数会与实际分数对不上。

## 用法

在技能根目录下执行：

```
node scripts/cli.mjs <命令> '<JSON 参数>'
node scripts/cli.mjs <命令> --stdin
node scripts/cli.mjs --help
node scripts/cli.mjs <命令> --help
```

## 命令一览

| 命令 | 用途 |
|------|------|
| `chart` | 查某物种的完整逐分判定表（9 行 × 侧视/俯视/触摸三列） |
| `row` | 查单一分数的判定行（含理想区 / 筛查区标记） |
| `assess` | 体况评估总装：判定行 + 标记 + 物种差异提示 + 误差与就医声明 |
| `figures` | 列出参考图可用的体型分类与档位（给 `figure-svg` 取值用） |
| `figure-svg` | 生成一张自包含的「侧视 + 俯视」参考图 SVG 字符串 |
| `caveats` | 查全部可靠性边界、物种差异与出处 |
| `describe` | 输出机器可读的接口说明 |

**参数详表、输出字段表、可运行示例** → [详细接口参考](references/interface-reference.md)。

## 失败处理（退出码）

| 退出码 | 含义 |
|--------|------|
| 0 | 成功，结果在 stdout 的 JSON 里 |
| 1 | 内部错误（未预期异常） |
| 2 | 用法或输入错误，命令未执行（如 `score` 给了 0 或 12） |
| 3 | 前置条件缺失（技能镜像未同步） |

## 拒答与替代路径

> 本节是**可机检**的边界契约（规范与判据见 `docs/技能边界与拒答契约_2026-10-13.md`）。
> 命中某一类时，按该类「话术」回复并给出「替代」路径；标「不适用」的类必须写明本技能层面的理由。

### R1 非犬猫物种
- **触发**：查询非犬猫物种的体况评分表。
- **话术**：本技能的 9 分制判据表只覆盖犬与猫，对其它物种不适用。
- **替代**：请咨询该物种的兽医；犬猫的逐分判定行与参考图本技能可照常给。

### R2 医疗诊断
- **触发**：要求确诊肥胖或给出减重方案。
- **话术**：体况评分是筛查工具，不是诊断；我不做确诊也不开减重方案。
- **替代**：临床肥胖确诊需兽医结合肌肉状况、体重趋势与体检；本技能负责列清复评周期与就医信号。

### R3 超出已收录法规体系
- **触发**：要求按未收录的评分制式（非 9 分制）出判定。
- **话术**：本技能只收录 9 分制判据，其它制式我无法换算给结论。
- **替代**：可用 9 分制判定行做参照；跨制式换算需另行确认口径。

### R4 数据缺口（`nodata`）
- **不适用**：本技能不消费配方数据，判据表为固定 9 行，不存在「缺数据无法判定」的情形。
