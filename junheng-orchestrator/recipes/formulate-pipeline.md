# Recipe：配方研发七阶段流水线（formulate-pipeline）

> 本模板供 `junheng-orchestrator` 调用。每个阶段含 **输入 / 调用技能 / DoD 退出门禁 / 审计字段**。
> 编排者须严格按序执行，门禁不过不得进入下一阶段（质量门禁三铁律①）。

---

## 阶段总览（DAG 依赖）

```
① 证据收集 ─┐
             ├─→ ② 标准映射 ─→ ③ 配方计算 ─→ ④ 达成度验证 ─→ ⑤ 标签生成 ─→ ⑥ 合规校验 ─→ ⑦ 报告产出
① 证据收集 ─┘
```

② 依赖①（标准须有文献支撑）；③ 依赖②（约束来自 resolveStandard）；④ 依赖③；⑤ 依赖④；⑥ 依赖⑤；⑦ 依赖⑥。

---

## ① 证据收集（Evidence）

- **输入**：研究问题（如「排毛功能原料证据」「某营养素功能宣称」）
- **调用**：`paper-bilingual-search` / `literature-reviewer` / `multi-search-engine` / `Exa` / `Context7`
- **DoD 退出门禁**：
  - 每条引用可溯到文献名 + 版本/年份（不用文件名代替文献名）
  - 文献真实性已核（联网核验或 DOI 核验）
  - 证据强度分级（强 / 中 / 弱 / 无）
- **审计字段**：`evidence[] = { claim, source(文献名), year, strength, verified:bool }`
- **人类检查点**：无（只读检索）

## ② 标准映射（Standards）

- **输入**：物种 / 生命阶段 / 市场（intl / cn / cn-intl）、① 结论
- **调用**：`junheng-standards.resolveStandard({ marketId, species, stage, moistureClass })`
- **DoD 退出门禁**：
  - 参与约束的营养项 `available === true`（原料库有对应字段）
  - 每项 `cite` 完整（标准名 + 版本）
  - `verified` 标记明确（false 须显式标注「未核」）
- **审计字段**：`standardSet = { marketId, species, stage, items:[{key,min,max,cite,verified}] }`
- **人类检查点**：若需改标准值（如去 GB 污染类），停等批准（见 SKILL.md 人类检查点）

## ③ 配方计算（Formulate）

- **输入**：原料清单（价格 + %DM 营养）、② 的约束、`ingredient_max`（可选）、`strategy`（least_cost/balanced/nutrient_max）
- **调用**：`junheng-formulate.formulateLeastCost(...)` → `solveLP`
- **DoD 退出门禁**：
  - 配比 Σ = 1（数值容差 1e-6）
  - LP 状态 `optimal`（不可行须结构化报错，不得静默）
  - 单位成本已产出
- **审计字段**：`recipe = [{id,name,share,price}]`、`unitCost`、`strategy`、`ingredientMax`
- **人类检查点**：无（计算可复现）

## ④ 达成度验证（Attainment）

- **输入**：③ 的 recipe、② 的约束
- **调用**：`junheng-attainment`（或编排者独立重算：用 `resolveStandard` + `ingredient_db` 重新算配方营养）
- **DoD 退出门禁**：
  - 各营养 min 达成（≥）、max 不超标（≤）
  - 钙磷比 ∈ [caP.min, caP.max]
  - 独立重算与③ 自报一致（偏差 < 1e-6）
- **审计字段**：`achieved = [{key,value,min,max,ok:bool}]`、`caP` 达成、`independentCheck`
- **对抗验证**：换新计算路径重算（Fresh Reviewer Rule②），二元 PASS/FAIL + 数值证据

## ⑤ 标签生成（Labeling）

- **输入**：④ 的 recipe + achieved
- **调用**：`junheng-labeling`
- **DoD 退出门禁**：
  - 标签数值与④ achieved 一致（不允许标签 > 实测）
  - 单位 / 基准（%DM / 风干）标注清晰
- **审计字段**：`label = [{nutrient, declared, basis, unit}]`

## ⑥ 合规校验（Compliance）

- **输入**：⑤ 的 label、② 的标准
- **调用**：`junheng-safety` + `junheng-standards`
- **DoD 退出门禁**：
  - 无超标项（label 值 ≤ 标准 max）
  - 无缺失强制项（标准 required 项均有声明）
  - 添加剂 / 限制性物质在法规限值内
- **审计字段**：`compliance = { overLimit:[], missing:[], passed:bool }`

## ⑦ 报告产出（Report）

- **输入**：①–⑥ 全部产物
- **调用**：`word-docx` / `wps`
- **DoD 退出门禁**：
  - 报告含证据链（① source）+ 标准出处（② cite）+ 审计追踪（各阶段门禁结果）
  - 关键论断附 file:line / 数值证据
- **审计字段**：`reportPath`、`auditTrailRef = .junheng/run-<ts>.json`

---

## 门禁失败处理

- 任一阶段 DoD 未过 → 返回该阶段重试（≤3 次）→ 仍失败升级人工（Override / Defer / Cancel）。
- 不可跳过门禁、不可 `git --no-verify`、不可静默吞错。
