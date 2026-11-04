# 技能治理框架（GOVERNANCE）

> 性质：治理文档（零行为变更）。仅厘清责任、消除重叠触发、降低误用，**不改动任何技能运行逻辑**。
> 来源：合并总排期 `plans/blazing-forging-tesla-vAXNs08a.md`（B2/B3/C3）+ 现有技能实测
> （`SKILLS-CATALOG.md`，2026-10-25 扫描得 83 项用户自定义技能）。
> 配套：同目录 `SKILLS-CATALOG.md`（逐技能清单）、`MCP-GOVERNANCE.md`（外部接入治理）。

---

## 1. 总原则

- **用户级技能根** = `~/.workbuddy/skills/`，全部可编辑；逐技能清单见 `SKILLS-CATALOG.md`。
- **分类按"功能职责"而非"目录位置"**：同一技能可能跨 Tier（如 `agent-dev-skills` 既含创建发布也含治理）。
- **治理边界**：本文件只做文档/约定层约束；平台 Skill 分发器非本地代码，本框架不声称改写引擎（C1 协作约定同理）。
- **`memory-manager-v2` 特殊说明**：当前仅 `config.json`（20B），无独立 SKILL.md，**不是独立技能**，只是某记忆管理技能的配置容器目录；其同名 `__skillhub` 变体才是功能副本（A4 已审计保留）。本框架不将其计入 Tier。

---

## 2. Tier 分级（B2：元层 Tier 治理）

四级，按"对谁负责 / 改的是什么"划分：

### Tier0 — 业务技能（直接交付用户领域价值）
- **职责**：面向具体领域，完成用户的一次性任务（算配方、搜文献、写文档、抓网页…）。
- **代表（实测分布）**：
  - 钧衡宠物食品域 **15**：`junheng-core`(共享内核/原料种子库) / `junheng-nutrition` / `junheng-labeling` / `junheng-cost` / `junheng-feeding` / `junheng-safety` / `junheng-standards` / `junheng-optimize` / `junheng-pipeline` / `junheng-attainment` / `junheng-energy` / `junheng-bcs` + `intel-compliance` / `intel-evidence` / `intel-formula` + `pet-nutrition-needs`
  - 学术研究 **8**（academic-plotting / ara-* / ml-paper-writing / literature-reviewer-skill / paper-bilingual-search / paper-quick-reader / sparse-autoencoder-training / systems-paper-writing）
  - 内容/联网 **8**（browser-skill / browser-use / multi-search-engine / web-access / wechat-article-* / videos-content-analyzer / douyin-video-extract-copywriter）
  - 办公文档 **6**（pdf / pdfkit-py / minimax-docx / word-docx / wps-office / officecli）
  - 平台基础设施 **2**（lark-unified / werss-ctl）
- **触发纪律**：按任务语义触发，**不与元层技能争触发词**；业务技能之间若功能重叠（如多个 PDF/多个微信采集），以"用户显式指定或最贴合子任务"为准，不静默互替。

### Tier1 — 元优化技能（优化"其他技能"与"自身表现"）
- **职责**：不直接交付业务，而是让 Tier0 更好 / 更省 / 更稳；**即铁律⑥常带三 skill**。
- **成员**：`skill-optimizer`（多维度质量评估 + 六步需求法，优化其他 skill）、`self-improving`（自我反思/批评/学习，固化改进）、`darwin-skill`（8 维 rubric 评估 SKILL.md + hill-climbing 优化）。
- **特征**：常驻但**不抢业务触发**；评分相互独立（互不覆盖）；业务任务中以"判据在场"形式存在，不主动全量加载（见 §4）。

### Tier2 — 安全学习与约束纪律（护栏）
- **职责**：fail-closed 的审查 / 闸门 / 节流，默认拦、可显式绕过。
- **成员**：`skill-vetter`（安装任何外部技能前的安全审查——D3 强制门禁）、`delivery-no-pseudoblock`（交付前伪阻断/缓干闸门，D1–D12 逐项扫描）、`repo-retrieval-governance`（token 与仓库体积治理）、`token-saver-qclaw`（纯自然语言长文本显式压缩硬门禁）。
- **特征**：凡是"先放行再干活"类诉求，应先过 Tier2 闸门；闸门被绕过须留下显式证据，不得用声明替代实际扫描。

### Tier3 — 创建与发布（改动"技能宇宙"本身）
- **职责**：造新技能/agent、迁移资产、安装来源；改动面最大，须最高审慎 + 真实核实。
- **成员**：`agent-dev-skills`（agent 全生命周期：角色库 / 人物蒸馏 / 发布 / 软删恢复）、`nuwa-skill`（蒸馏思维框架生成 persona Skills）、`tiangong-skill`（智能体设计师）、`workbuddy-migration-assistant`（跨机资产迁移）。
- **纪律**：任何外部技能安装须经 `skill-vetter` 且登记 provenance（来源/commit/哈希，见 D3）；发布前须本地真实验证，不得仅凭 README 声称。

---

## 3. 五类实体区别与选用时机（B3）

> 基于公开标准与现有工具命名，**不臆测平台内部实现**；仅描述"何时选哪类"的判别法。

| 实体 | 是什么 | 暴露/管理方式 | 选用时机 | 选错症状 |
|------|--------|--------------|----------|----------|
| **Skill** | 本地能力包（`SKILL.md` + 脚本/资源），经 Skill 工具加载，受 `~/.workbuddy/skills/` 管理 | 用户级/项目级目录，可编辑 | 需要**可复用的方法论/工作流/领域知识**，希望随项目或用户级分发 | 把"想让它自己跑完多步"写成 skill（应是 Agent）；把"一次性能力"硬塞进 agent |
| **MCP server** | 按 Model Context Protocol 标准暴露 `tools` 的外部服务 | 本地 `mcp.json` 配置端点 | 需接入**外部系统**（笔记库、云盘等），且对方提供标准 MCP 端点 | 对方已是平台认证通道还手搓 MCP（应用 Connector） |
| **Connector（连接器）** | 平台托管的集成（如企业微信、腾讯文档），由平台侧维护接入 | 以 `connectorIds` 引用，平台认证 | 走**平台已认证通道**、不想自建 MCP 时 | 能直接用 connector 却自己拼 API/密钥 |
| **Expert（专家）** | 领域专家包，封装特定领域 SOP/知识，由 expert-manager 转化维护，可对话调用 | expert 包 + expertId | 需要**角色化领域 SOP**（而非通用工具），且希望专家随更新迭代 | 把"通用工具能力"包装成专家（应是 Skill/MCP） |
| **Agent（子代理/团队角色）** | 可独立执行多步任务的**执行者**，由 Agent/TeamCreate 拉起 | 运行时 agent/team | 需要**一个干活的实体自主决策步骤**，而非一份"被调用的知识/流程" | 把"多步自主流程"压进一个被动 skill（应是 Agent） |

**核心判别**：
- skill = **能力**（被动、被调用、单次完成一个明确子任务）；
- agent = **执行者**（主动、多步、自己决定怎么走）；
- MCP / connector = **外部能力接入通道**（数据/操作原子能力）；
- expert = **角色化知识包**（领域 SOP，对话式调用）。
- 经验法则：**"我希望某段逻辑被调用"→ Skill；"我希望有个实体自己把活干完"→ Agent；"我要接外部系统"→ 先看有无 Connector，否则 MCP。**

---

## 4. 常带三 skill 纪律（C3）

- **铁律⑥**：每次任务常带 `self-improving` + `skill-optimizer` + `darwin-skill` 三 skill；三者评分独立、互不覆盖。
- **铁律④（darwin-skill 边界）**：**零额外加载、按判据推理、不调 Skill**；仅当任务是 **skill 评估 / 优化** 时才 `Skill` 全量加载其 `SKILL.md`；普通业务任务中 darwin 仅作为"在场判据基线"，**不主动激活**。
- **"常带"≠"每次全量加载其 SKILL.md"**：元层技能以"判据在场"形式存在，避免 token 浪费与误触发；仅在命中其职责（优化/反思/评估）时展开。
- **冲突裁决**：元层技能不改业务结论，只改进过程；若元层判据与业务技能输出冲突，以**业务正确性**优先，元层意见作为可复核备注，不强制改写。

---

## 5. 命名空间约定（A2）

> 仅文档层约定，**不物理移动任何已有技能**（尤其插件缓存技能），仅对**新建**技能强制。权威清单见 `SKILLS-CATALOG.md`。

**约定**：
- **业务域前缀**（实测现有，供对齐参考）：
  - 钧衡宠物食品域：`junheng-*` / `intel-*` / `pet-nutrition-needs`
  - 学术研究：`academic-*` / `ara-*` / `ml-*` / `paper-*` / `literature-reviewer-skill`
  - 内容/联网：`web-access` / `multi-search-engine` / `wechat-*` / `browser-*`
  - 办公文档：`pdf*` / `word-docx` / `wps-office` / `officecli` / `minimax-docx` / `pdfkit-py`
  - 平台基础设施：`lark-unified` / `werss-ctl`
- **元层别名 `meta-`**：Tier1–Tier3（元优化/安全/创建发布）**建议**新技能采用 `meta-` 前缀别名（如 `meta-skill-optimizer`），在目录中显式区分"优化者"与"被优化者"。**仅对新技能强制；存量元层技能（`skill-optimizer`/`self-improving`/`darwin-skill`/`skill-vetter` 等）不强制改名**，避免破坏现有引用与 catalog 扫描。
- **命名一致性**：技能 `name` 字段与目录基名一致；`description` 单行、无 Markdown 特殊前缀字符（以 A3 已修复的 11 项为准）。

---

## 6. 外部技能安装门禁（D3）

> 任何**外部来源**技能（marketplace / 仓库 / 第三方）安装到 `~/.workbuddy/skills/` 前，须经 `skill-vetter` 审查并登记 provenance。属 §2 Tier3 发布纪律的落地细化。

**强制流程**：
1. **先审查**：安装前调用 `skill-vetter` 完成真实性核实 / 安全审计 / 完整性校验；未过审不安装。
2. **记 provenance**：每个外部技能安装（或来源可追溯的存量）登记一行：
   | 字段 | 含义 |
   |------|------|
   | `name` | 技能目录基名 |
   | `source` | 来源（marketplace 名 / 仓库 URL / 提供方） |
   | `commit` | 锁定来源 commit（如有） |
   | `sha256` | 核心文件 sha256（后续完整性复核） |
   | `installed_at` | 安装日期 `YYYY-MM-DD` |
   | `vetter` | `skill-vetter` 审查结论（pass/fail + 版本） |
   | `note` | 已知限制 / 钉死版本原因 |
3. **钉死与复核**：来源漂移（上游更新）须重新走 vetter + 更新台账；不得静默覆盖已钉死版本。

**诚实边界**：本约定为**流程纪律**，非自动闸门；当前无 hook 强制拦截未审查安装，依赖使用者自觉 + 后续可加安装包装器（不在本 Wave 范围）。`skills/manifest.json`（grilling 评测工作区）已是该思想的工程化实例，可作模板参考。

---

## 7. 诚实边界（本框架不覆盖 / 不声称）

- **平台 Skill 分发器**：非本地代码，本框架仅在文档/约定层消除重叠，不声称改写引擎。
- **实际误触发频率**：仅为结构性风险，未实测；B1（optimizer/darwin 分工）留待后续观察互补性后再细化。
- **Tier 归属主观性**：部分技能跨 Tier（如 `agent-dev-skills` 含创建与治理），本框架以"主要职责"归类，不排除次要职责。
- **A2/D3 强制范围**：仅约束**此后新建**技能与**外部安装**动作，不对存量批量重命名、不替代既有 vetter 调用。
- **MCP 现状**：见配套 `MCP-GOVERNANCE.md`，独立成册避免与本框架耦合。
