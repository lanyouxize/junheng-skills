---
name: junheng-core
description: 钧衡 NutriAgent 共享内核（内部）。nutrition/-labeling/-cost/-feeding 四技能共同依赖的源码镜像与 286 条种子库，无业务命令。当出现「junheng-nutrition 报前置条件缺失」「技能找不到源码目录」或需更新法规/原料库并同步时使用。
description_en: Shared computation core for Junheng NutriAgent skills. Holds the single copy of the mirrored source closure (nutrition/standards/energy/bcsChart/labeling/costModes/feedingGuide) and the 286-ingredient seed database, consumed by junheng-nutrition, -labeling, -cost and -feeding. Not user-facing; no business commands of its own.
metadata:
  author: Junheng NutriAgent
  version: "1.0.0"
compatibility: Requires Node.js 18+ (ESM) and a UTF-8 filesystem. No network access and no third-party dependencies. Holds the mirrored source closure (vendor modules) and the ingredient seed database shared by the junheng-* skill family.
---

# 共享计算内核（junheng-core）

## 目的与边界

`junheng-core` 不是给用户提问用的技能，而是 **nutrition / labeling / cost / feeding / pipeline 五个技能共同的地基**：把项目源码单向镜像成技能可直接加载的形态。

| 目录 | 内容 | 唯一真源 |
|---|---|---|
| `scripts/vendor/*.js` | **12 个**模块：`nutrition` `dataQuality` `standards` `energy` `bcsChart` `labeling` `costModes` `feedingGuide` `species` `toxicology` `multiPetPlan` `portionLabel` | `src/lib/` |
| `scripts/data/ingredient_db.js` | 286 条原料种子库 | `src/data/` |
| `MANIFEST.json` | 每个条目的 sha256 指纹（引用方另记 `coreRef`） | 同步器生成 |

单独成层是为了「一份闭包，五个引用方」：换法规或换种子库**只改一处**，漂移只在这一处报，引用方经 `coreRef` 校验版本。

**边界**：本层**不含逻辑、不新增数值与判定** —— 全部计算能力都在 `src/lib/`，本层只是它的只读镜像。

### 目录布局与一处易踩的坑

数据放 `scripts/data/` 而**不是** `scripts/vendor/data/`：`nutrition.js` 写的是 `import RAW_DB from '../data/ingredient_db.js'`，从 `scripts/vendor/` 出发正好解析到 `scripts/data/`，两种布局都成立（零源码改动）；放错位置报 `ERR_MODULE_NOT_FOUND`（已实测）。

## 诚实性红线

1. 本层**不含任何逻辑**，只是 `src/lib/` 与 `src/data/` 的只读镜像。
2. **不得在技能侧改本层内容** —— 会被判 `MIRROR_TAMPERED`；应改源码再同步。
3. 本层**不新增数值、不新增判定** —— 有出入改项目源码，不是这里。
4. 引用方报告的数值都是**理论计算值**，不是检测值。

## 用法

> 以下命令均在**项目根**（`nutrition-agent-work`）运行。技能目录内**不含**该脚本：
> 技能侧是只读镜像，自造逻辑会被校验器判 `EXTRA_FILE` 错误（已实测），
> 所以同步器不能放进技能目录——放进去它会把技能目录误当项目根，全部条目报 `SOURCE_MISSING`。

```bash
node scripts/sync-skills.mjs          # 改完 src/ 后同步（写盘 + 自动校验）
node scripts/sync-skills.mjs --check  # 只校验：有漂移 exit 1，源文件缺失 exit 3
node scripts/sync-skills.mjs --dry    # 预览会同步什么，不写盘
```

## 命令一览

| 命令（前缀 `node scripts/` 省略） | 作用 |
|---|---|
| `sync-skills.mjs` | 同步门面 + 镜像 + MANIFEST（写盘），结束自动校验 |
| `sync-skills.mjs --check` | 只校验不写盘；有漂移 exit 1，源文件缺失 exit 3 |
| `sync-skills.mjs --dry` | 只打印同步计划，不写盘 |

**参数详表、输出字段表、可运行示例** → [详细接口参考](references/interface-reference.md)。

## 失败处理（退出码）

| 退出码 | 含义 |
|---|---|
| 0 | 校验一致，或同步成功 |
| 1 | 检出**漂移**（跑一次同步即可修复），或同步后仍有漂移 |
| 2 | 用法 / 输入错误（未知选项、`--skills-dir` 缺参数） |
| 3 | **前置条件缺失**：计划里声明的**源文件**不在磁盘上（`SOURCE_MISSING`）—— 同步**也修不了**，须先补源 |

> **为什么 3 不并进 1**：漂移的下一步动作是「跑同步」，源缺的下一步动作是「去补仓库里的文件」。
> 两者混成一个码，调用方就只能靠 grep 日志分辨该重试还是该报缺件。

`--check` 给每条问题打 `code`，对症处理：`SOURCE_DRIFTED`（源变了 → 跑同步）、`MIRROR_TAMPERED`（镜像被改 → 改回源）、`BOTH_CHANGED`（两边都变 → 先定夺回写谁）、`CORE_REF_MISMATCH` / `CORE_MISSING`（核心版本不符 / 缺失 → 跑同步）、**`SOURCE_MISSING`（源文件不存在 → 退出码 **3**，先补源，同步救不了）**、其余 `MISSING_MANIFEST` / `BAD_MANIFEST` / `MISSING_ENTRY` / `MISSING_FILE` / `EXTRA_FILE`（目录未同步或清单不一致 → 修正后跑同步）。

## 拒答与替代路径

> 本节是**可机检**的边界契约（规范与判据见 `docs/技能边界与拒答契约_2026-10-13.md`）。
> 命中某一类时，按该类「话术」回复并给出「替代」路径；标「不适用」的类必须写明本技能层面的理由。

### R1 非犬猫物种
- **不适用**：本层不接收物种参数，物种适用性由调用方门面判定；本层只做源码只读镜像。

### R2 医疗诊断
- **不适用**：本层不产出面向用户的文本，诊断与拒答边界由各门面技能声明，本层不含判定逻辑。

### R3 超出已收录法规体系
- **触发**：要求本层提供未收录体系的限值条目。
- **话术**：本层只镜像 `src/lib/` 的既有条目，未收录的体系我这里也没有。
- **替代**：请查 `junheng-standards` 的收录清单；待 `src/lib/` 补录后重新同步即可。

### R4 数据缺口（`nodata`）
- **触发**：某模块或原料条目缺失，引用方报 `ERR_MODULE_NOT_FOUND`。
- **话术**：本层是只读镜像，缺条目时我不兜底，直接报错。
- **替代**：请跑 `sync-skills.mjs --check` 定位漂移并重新同步；不要手改镜像（会被判 `MIRROR_TAMPERED`）。
