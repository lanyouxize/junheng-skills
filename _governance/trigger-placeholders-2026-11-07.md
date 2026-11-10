# 触发词占位符「—」分类标注（C2 交付物）

> 来源：`check_consistency.py` [C] 维度 + 重建后的 `INDEX.md`「触发词待补（25 个）」。
> 生成于 2026-11-07。`build_index.py` 仅在 description 含「当用户…时使用 / 触发词：」等句式时才抽触发词；以下 25 个抽不到，列此分类。
> **原则**：不臆造触发词。标注「建议补」的，需要把推荐短语写进该技能 `description` 后重跑 `build_index.py` 才会入索引——这是独立审批批次，本轮只标注不直接改技能。

## 一、无需触发词（元层 / 平台 / 常驻，靠显式调用或任务语义触发）

| 技能 | 理由 |
|---|---|
| `delivery-no-pseudoblock` | 交付前行为闸门，常驻随每次交付自动加载，不应由触发词命中 |
| `self-improving__skillhub`（Self-Improving + Proactive Agent） | 元层自学习，任务开始/收尾自动触发，非用户显式触发 |
| `nuwa-skill` | 人格 Skill 蒸馏，按需显式调用 |
| `skill-vetter` | 安装外部技能前的安全审查，显式调用 |
| `grill-me` | 苏格拉底式拷问入口，用户主动发起 |
| `handoff__skillhub`（handoff） | 交接文档生成，显式调用 |
| `python-crawler-architect__skillhub`（Python 爬虫架构师） | 编程专家类，任务语义触发 |
| `dev-expert` | 编程专家，任务语义触发 |
| `ima-skills` | IMA 笔记操作，显式调用 |
| `totorosir-workbuddy-score` | 积分助手，显式调用 |
| `workbuddy-migration-assistant` | 跨机迁移，显式调用 |
| `rev-core` / `rev-runtime` / `rev-static` | 逆向三件套，按授权场景显式调用 |

## 二、建议补触发词（描述里其实有清晰用途，只是没写「当用户…时使用」句式）

| 技能 | 推荐触发词（写入 description 后重跑 build_index 生效） |
|---|---|
| `free-model-market` | 查免费大模型 API、推荐免费模型、厂商免费额度多少（注：description 已被重写为能力摘要，旧触发词失效，建议恢复触发句式） |
| `github` | 用 gh 操作 GitHub、查 issue/PR/CI |
| `browser-use` | 无头浏览器自动化测试、填表、截图 |
| `web-access` | 操作已登录 Chrome、抓动态渲染页 |
| `ui-auto-click` | 固化桌面点击流程、自动点击步骤 |
| `mindmap-generator` | 文档/网页转脑图、生成思维导图 |
| `word-docx` | 处理 docx 样式/修订/表格 |
| `wechat-article-scraper` | 爬取公众号图文、导出知识库 |
| `workbuddy-credit-usage` | 查 WorkBuddy 积分消耗 |
| `workbuddy-speedup-diagnosis__skillhub`（workbuddy-speedup） | 变慢/卡死诊断、提速 |
| `systems-paper-writing` | 写 OSDI/SOSP/ASPLOS 系统论文 |

## 三、处置建议

- **第一类（12 个）**：在 `INDEX.md`「触发词待补」段标注「无需触发词（元层/平台，显式调用）」即可，无需改技能。
- **第二类（13 个）**：属真实可用技能，建议在其 `description` 末尾补「当用户…时使用」句式。这是按技能逐个审批的编辑批次，不在 A+C 本轮内执行。
- 全 25 个在 `check_consistency.py` 中仍为 W 级（非阻断），不影响路由；补完后该维度归零。
