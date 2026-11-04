# 知识体系联网完善指南（Enrichment Protocol）

本 skill 的核心能力之一：**在本地蒸馏知识库（nutrition_needs.md）基础上，主动联网检索专业来源，对知识体系进行补全、交叉验证与更新**。遵循「先证伪、不臆造、强溯源」的纪律。

## 一、何时触发联网完善

满足任一即触发（用户显式要求或主动识别缺口）：

1. 用户问到本地库「待联网完善项」中尚未补全的内容（猫 VA 维持值、B 族完整表等）。
2. 用户要求「最新研究 / 现代议题 / 法规更新 / 与 AAFCO·FEDIAF 对比」。
3. 配方出现本地库未覆盖的原料特性、功能宣称或风险点，需要循证支撑。
4. 用户要求「找开源工具 / 数据库 / 配方计算项目」。

## 二、检索源分层（按可信度）

| 层级 | 来源 | 用途 |
| --- | --- | --- |
| L1 权威标准 | NRC / AAFCO / FEDIAF 官方 PDF·公报 | 需要量基准、合规红线 |
| L2 学术 | PubMed / ScienceDirect / NCBI / 中文知网(CNKI) | 剂量反应、缺乏症机制、DCM 与牛磺酸 |
| L3 开源 | **GitHub**（关键词见下）、HuggingFace、开源数据集 | 营养数据库、配方计算、原料成分表 |
| L4 专业社群 | 宠物营养师 / 宠物食品研发工程师博客、行业白皮书、厂商技术文档 | 实战经验、原料可消化性、工艺注意 |

## 三、GitHub 检索关键词（开源宠物营养 / 配方）

优先使用 `github` skill 或 WebSearch 检索下列组合（中英文各一）：

- `pet nutrition calculator dog cat formulation`
- ` canine feline nutrient requirement database`
- `pet food formulation software open source`
- `NRC dog cat nutrition requirements dataset`
- `taurine DCM grain free study`
- `raw feeding nutrient balance BARF calculator`
- `动物营养 配方 计算 开源` / `宠物食品 营养 数据库`

筛选标准：stars ≥ 20 或近 2 年有更新、含可机读营养数据（csv/json）、有许可证。

## 四、国内多引擎检索（multi-search-engine skill）

当用户语言为中文或需国内来源时，**必调 `multi-search-engine`**：中文国内 7 引擎、非中文国际 9 引擎；间隔 1–2 秒、3–4 个一批；同查询跨 ≥2 引擎交叉。关键词硬触发词（搜索/搜一下/查找/最新/有没有/网上）出现即必调。

## 五、引用与回填规范（铁律）

1. **引用用「文献/来源名称」而非文件名**：如「FEDIAF 2024 营养指南」「AAFCO 2023 官方公报」「Freeman et al. 2018, JAVMA 牛磺酸-DCM 综述」。
2. **每条新增知识必须带来源 + 检索日期 + 可信度层级（L1–L4）**。
3. **不覆盖、只追加**：新发现与原书冲突时，在 `enrichment_log.md` 标注「NRC 2006 vs 新来源差异」并给出建议采用值，不直接改写 nutrition_needs.md 的历史内容，除非用户确认升级。
4. **回填两处**：① `enrichment_log.md`（追加一条记录）；② 如已沉淀为稳定结论，同步更新 `nutrition_needs.md` 对应模块与「待联网完善项」勾选状态。

## 六、输出形态

- 结构化表格（带基准列、来源列、可信度列）。
- 明确标注「high / medium / low」优先级与「原书缺口 / 新补 / 交叉验证」类别。
- 对不确定项打标回退人工核查，不自动下结论。

## 七、enrichment_log.md 记录模板

```
### [YYYY-MM-DD] 主题：<一句话>
- 检索：<引擎/源/关键词>
- 新增/修正：<要点>
- 来源：<文献名称> · <可信度 L1-L4> · <检索日期>
- 处置：nutrition_needs.md §X 更新 / 待用户确认
```
