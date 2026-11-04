# 技能索引（INDEX）

> **本文件是产物，不要手改。** 内容来自各技能 frontmatter + `_governance/taxonomy.json`（族群与摘要的人工知识）。
> 重建：`python _governance/build_index.py`｜校验：`python _governance/lint_skills.py --new-only`
> 生成于 2026-11-01 22:53 · 技能 86 个 · 族群 11 个

## 怎么用

1. **接任务先查这里**，按族群扫「一句话」定位候选，再用「触发词」确认是否命中。
2. **新建技能前先查重**：同一族群已有近似能力时，优先扩展现有技能而不是新建。
3. 本索引只解决「有哪些、该用哪个」；单个技能怎么用看它自己的 `SKILL.md`。

## 族群分布

| 族群 | 数量 | 覆盖范围 |
|---|---|---|
| 宠物食品与配方 | 16 | 配方计算、法规限值、标签、成本、体况与安全闸 |
| 学术研究与论文 | 14 | 选题、检索、精读、写作、评审与配图 |
| 内容采集与媒体理解 | 9 | 公众号抓取归档、视频转写、视觉问答 |
| 浏览器与联网检索 | 6 | 真实浏览器操作、多引擎检索、GitHub 操作 |
| 办公文档与演示 | 8 | PDF、Word、PPT、表格、脑图 |
| 写作与人化改写 | 3 | 去 AI 味、文风复刻 |
| 成本与 Token 治理 | 8 | 积分/token 统计、省流、性能诊断、免费模型渠道 |
| 技能工程与方法论 | 11 | 技能自优化、安全审查、交付闸门、思维拷问、交接 |
| 代码与 Agent 开发 | 2 | 编程专家、爬虫架构 |
| 平台与外部系统 | 5 | 飞书、IMA、记忆治理、跨机迁移、积分助手 |
| 逆向与软件解析 | 4 | 授权范围内的软件逆向、协议还原、agent 应用解析与证据链 |
| **合计** | **86** | — |

## 宠物食品与配方（16）

| 技能 | 一句话 | 触发词 | 来源 |
|---|---|---|---|
| `intel-compliance` | 文案宣称合规检查 | 这句能不能这么写、有没有踩线 | 自建 |
| `intel-evidence` | 证据颗粒度抽取 | 这段研究里样本量是多少、用的什么动物做的、哪些字段没识别出来 | 自建 |
| `intel-formula` | 配方剂量核对 | 添加量换算、高低判定或口径归属 | 自建 |
| `junheng-attainment` | 配方达成度评估 | 这个配方达不达标、钙磷比够不够、按国标能不能过 | 自建 |
| `junheng-bcs` | 宠物体况评分 BCS 9 分制查询与参考图生成 | 猫狗胖不胖、算几分 | 自建 |
| `junheng-core` | 钧衡 NutriAgent 共享内核（内部） | 技能找不到源码目录 | 自建 |
| `junheng-cost` | 配方成本核算 | 这个配方成本多少钱一公斤、冻干出成率和成本怎么算、猫条一支成本多少 | 自建 |
| `junheng-energy` | 宠物食品能量计算 | 配方代谢能、RER 怎么算 | 自建 |
| `junheng-feeding` | 宠物喂食指南与体况管理 | 猫每天吃多少克、BCS 7 分怎么喂 | 自建 |
| `junheng-labeling` | 配方 → 合规标签底稿：营养保证值表（法规项目与顺序，带条款出处）、配料表（按重量递减）… | 帮我做一份标签底稿、营养保证值怎么写、这个配方合不合规 | 自建 |
| `junheng-nutrition` | 宠物食品原料库查询与配方营养计算 | 原料含量、配方营养 | 自建 |
| `junheng-optimize` | 宠物食品配方最低成本逆解 | 怎么配最省钱 | 自建 |
| `junheng-pipeline` | 跨技能串联编排 | 把配方完整评估一遍、一条命令跑全套 | 自建 |
| `junheng-safety` | 宠物食品有毒有害物质安全闸 | 巧克力能不能喂狗 | 自建 |
| `junheng-standards` | 宠物营养法规限值查询 | AAFCO 下限、国标要求 | 自建 |
| `pet-nutrition-needs` | 核算犬猫营养需要量与比对安全红线：覆盖能量、粗蛋白、必需氨基酸、牛磺酸、钙磷比与维生素… | 查宠物营养标准、做配方核算、比对 AAFCO 与 FEDI… | 自建 |

## 学术研究与论文（14）

| 技能 | 一句话 | 触发词 | 来源 |
|---|---|---|---|
| `academic-plotting` | 为 ML 论文生成出版级架构图/流程图 | 给学术论文配图、画模型架构图 | 自建 |
| `ara-compiler` | 把论文/仓库/日志/笔记编译为 ARA 研究工件 | 把散落研究材料结构化为可复用工件 | 自建 |
| `ara-research-manager` | 会话收尾记录研究溯源：决策、实验、死胡同、转向 | 沉淀项目过程、复盘研究路径 | 自建 |
| `ara-rigor-reviewer` | ARA 工件严谨度六维评审与定级 | 审查研究结论是否站得住、给工件定级 | 自建 |
| `autoresearch` | 端到端自主 AI 研究编排：内循环实验 + 外循环综合 | 自动跑一轮 ML/CS 研究 | 自建 |
| `brainstorming-research-ideas` | 结构化创意框架找研究选题与转向 | 要找研究选题、换方向、脑暴想法 | 自建 |
| `creative-thinking-for-research` | 用认知科学创造性框架（组合式创意、类比推理）找新颖方向 | 跳出常规思路、生成原创研究想法 | 自建 |
| `literature-reviewer-skill` | 8 阶段中英文文献回顾，产出 GB/T 7714 引文的综述 | 检索文献、写综述、找证据 | 自建 |
| `ml-paper-writing` | 撰写可投稿的 ML/AI 论文… | 写或改机器学习论文 | 自建 |
| `paper-bilingual-search` | 在学术检索镜像站按关键词批量检索论文，提取英文原题、作者、期刊、年份与摘要… | 批量找论文、做中英对照题录 | 自建 |
| `paper-quick-reader` | 论文速读与对比：提供裸读、引导、精读三档深度，回答带页码级溯源以防幻觉，支持多篇横向对比 | 第几页提到什么 | skillhub |
| `presenting-conference-talks` | 论文转会议演讲：Beamer PDF + 可编辑 PPTX + 讲稿 | 准备口头报告、spotlight 或会议汇报 | 自建 |
| `sparse-autoencoder-training` | 用 SAELens 训练与分析稀疏自编码器，做特征可解释性 | 训练 SAE、做特征可解释性分析、解读模型内部表示 | 自建 |
| `systems-paper-writing` | 面向 OSDI/SOSP/ASPLOS/NSDI/EuroSys 的系统类论文写作 | — | 自建 |

## 内容采集与媒体理解（9）

| 技能 | 一句话 | 触发词 | 来源 |
|---|---|---|---|
| `deepseek-v4-flash-vision-video-rag` | 基于 DeepSeek 视觉大模型的视频理解与问答：支持剧情理解、事件时间线… | 或要定位某一秒发生了什么 | skillhub |
| `douyin-video-extract-copywriter` | 抖音视频文案提取技能 | 下载抖音视频、提取抖音文案、抖音音频文案提取、抖音口播提取、抖音视频场景描述文案 | skillhub |
| `glm-53-flash-vision-rag` | 基于 GLM 视觉大模型的 PDF 深度问答与检索：支持扫描件、图表、表格… | 或要定位某一页 | skillhub |
| `videos-content-analyzer` | 分析视频内容，支持今日头条、抖音、B站、西瓜视频、小红书、快手等平台 | 提供视频链接并要求分析视频内容、总结视频、看看视频讲什么 | skillhub |
| `wechat-article-archive` | 把微信公众号的整站历史文章抓成全量语料，交付三种归档件：可点读的单文件 HTML 阅读器… | 把某公众号文章整理成可读档 | skillhub |
| `wechat-article-collector` | 自动采集微信公众号文章（图文/视频元数据）并归档写入「铭衍·元典」资料库数据表 | 采集/保存/批量下载公众号文章、按公众号批量抓历史、把微信文章入库或导出 JSONL | 自建 |
| `wechat-article-scraper` | 微信公众号图文爬取与多平台知识库导出 | — | skillhub |
| `wechat-article-search` | 按关键词检索公众号文章，返回标题、概要、时间与链接 | 查找微信公众号文章、整理参考资料或快速获取文章信息 | skillhub |
| `werss-ctl` | WeRSS 服务控制与守护 | WeRSS 怎么启停或服务是不… | 自建 |

## 浏览器与联网检索（6）

| 技能 | 一句话 | 触发词 | 来源 |
|---|---|---|---|
| `browser-skill` | 操控用户已登录的 Chromium 浏览器完成网页任务：读取页面、填表、抓数据… | 操作真实浏览器而非无头抓取 | skillhub |
| `browser-use` | 无头浏览器自动化：网页测试、填表、截图、数据抽取 | — | skillhub |
| `github` | 用 gh CLI 操作 GitHub：issue、PR、CI 运行、任意 API 查询 | — | skillhub |
| `multi-search-engine` | 多引擎聚合检索：覆盖 8 个国内与 9 个国际引擎，支持高级检索语法、时间过滤… | 联网搜索、跨平台交叉验证或找最新资料 | skillhub |
| `ui-auto-click` | 把人工在桌面软件上的点击流程固化为可复现的自动点击步骤表 | — | 自建 |
| `web-access` | 经 CDP 直连本地 Chrome，处理登录态与动态渲染页的抓取与操作 | — | skillhub |

## 办公文档与演示（8）

| 技能 | 一句话 | 触发词 | 来源 |
|---|---|---|---|
| `luobo-ppt` | 做 PPT 与美化 PPT 的一站式能力，输出可编辑的原生 .pptx：从题目… | 做 PPT、美化 PPT | skillhub |
| `mindmap-generator` | 文档/网页/公众号文章转交互式脑图，附 200 字摘要 | — | skillhub |
| `minimax-docx` | 用 OpenXML SDK 处理 Word 文档：支持从零新建、向既有文档填充内容… | 生成、编辑或排版 docx 文档 | skillhub |
| `officecli` | Word/Excel/PPT 的创建、分析、校对与修改 | the user wants to generate documents、inspect content、check formatting | skillhub |
| `pdf` | PDF 处理工具箱：提取文本与表格、新建 PDF、合并与拆分文档、填写表单 | 读取、生成、拆分合并或填表处理 PDF | skillhub |
| `pdfkit-py` | 处理已存在的 .pdf 文件：读取提取、编辑、合并拆分、格式转换、水印、加密、表单、签名… | 输入对象是 .pdf | skillhub |
| `word-docx` | 把 .docx 当 OOXML 处理：样式、编号、修订、表格、分节与域 | — | skillhub |
| `wps-office` | WPS 办公全流程助手，覆盖资深办公效率教练：文字排版长文档、表格函数与数据透视… | WPS、WPS文字、WPS表格、WPS演示、Word | skillhub |

## 写作与人化改写（3）

| 技能 | 一句话 | 触发词 | 来源 |
|---|---|---|---|
| `humanizer` | 润色文本以去除 AI 写作痕迹（浮夸象征、套路化表述等），使表达更自然、更像真人写作 | 改写、审校文稿或降低文本的机器感 | skillhub |
| `humanizer-studio` | 去AI味文本人化工作室：把AI生成或模板化的文字改写成自然、像人写的文案与文章… | 去AI味、去机械感、humanizer、AI检测、文本润色 | skillhub |
| `perfectly-replicate-writing-skills` | 双引擎蒸馏写作分身 | 思维+写作风格提示词、思维+写作分身子技能、双重复检系统 | skillhub |

## 成本与 Token 治理（8）

| 技能 | 一句话 | 触发词 | 来源 |
|---|---|---|---|
| `free-model-market` | 41 家厂商免费模型货架：选型推荐、配置排障、巡检更新 | 有哪些免费大模型 API 可用、推荐免费模型、XX 厂商免费额度多少 | skillhub |
| `repo-retrieval-governance` | 诊断并治理 AI 协作项目越用越贵的问题：量化检索面污染、常驻大文档、记忆层膨胀… | 为何对话越来越贵、仓库暴涨、检索被副本淹没 | skillhub |
| `token-saver-qclaw` | token智能省流助手（安全加固版 6.1.0-hardened） | 纯自然语言、长文本 | skillhub |
| `token-usage` | 统计本机 token 消耗并出可视化用量面板 | token 消耗、用量统计、花了多少额度、或要打开用量面板 | skillhub |
| `workbuddy-credit-usage` | 读取 WorkBuddy 本节点与当前会话消耗的官方积分（credit） | — | 自建 |
| `workbuddy-free-models-gateway` | 把 WorkBuddy 免费模型额度… | 把免费额度接到本地或第三方客户端、需要兼容端点 | skillhub |
| `workbuddy-speedup` | 变慢/卡死/报错码的诊断与提速处置 | — | skillhub |
| `workbuddy-token-usage` | 分析 WorkBuddy 的 AI 调用 Token 消耗与成本 | 消耗、花费、哪个模型最贵 | skillhub |

## 技能工程与方法论（11）

| 技能 | 一句话 | 触发词 | 来源 |
|---|---|---|---|
| `Self-Improving + Proactive Agent` | Agent 自省自评自学习：任务开始读记忆，收尾沉淀带来源的教训 | — | skillhub |
| `agent-dev-skills` | Agent 开发五件套：CLI 发现、对话蒸馏为分身等 | 开发或增强自有 Agent、做 CLI 适配、把聊天记录沉淀为技能 | skillhub |
| `darwin-skill` | 按 8 维 rubric + git 爬山式迭代优化 SKILL.md | 评估或改进某个 skill 的… | skillhub |
| `delivery-no-pseudoblock` | 交付前 D1–D12 行为闸门，拦伪阻断、半途交付与责任转嫁 | — | skillhub |
| `grill-me` | 苏格拉底式拷问会话入口，用来打磨方案与设计 | — | 自建 |
| `grilling` | 就一个方案/决策/想法持续追问，直到双方理解对齐 | the user wants to stress-test their thi…、or uses any 'grill' trigger phrase | 自建 |
| `handoff` | 生成临时交接文档，并把长期知识沉淀进共享 Obsidian 库 | — | skillhub |
| `nuwa-skill` | 从人物身上蒸馏思维框架，产出可运行的人格 Skill | — | skillhub |
| `skill-optimizer` | 优化其他 skill 的元技能：提供多维度质量评估清单、需求挖掘方法与迭代终止判据… | 评估或系统性改进一个 skill | skillhub |
| `skill-vetter` | 安装任何外部技能前的安全审查：红旗项、权限范围、供应链风险 | — | skillhub |
| `tiangong-skill` | 天工.skill(Tiangong Skill)智能体设计师 | 设计、创建或优化AI智能体/Agent、或基于真实人物蒸馏思维框架创建… | skillhub |

## 代码与 Agent 开发（2）

| 技能 | 一句话 | 触发词 | 来源 |
|---|---|---|---|
| `Python 爬虫架构师` | 资深Python爬虫与数据工程专家 | — | skillhub |
| `dev-expert` | 编程专家：P8 级编程助手 | — | skillhub |

## 平台与外部系统（5）

| 技能 | 一句话 | 触发词 | 来源 |
|---|---|---|---|
| `ima-skills` | IMA 笔记与知识库读写检索 | — | skillhub |
| `lark-unified` | 飞书与 Lark 的统一 CLI 套件：覆盖消息、文档、表格、多维表格、日历、邮件、任务… | 通过命令行操作飞书任一能力 | skillhub |
| `memory-manager-v2` | 管理 .workbuddy/memory/ 的记忆治理与 Token 节流工具… | 治理项目记忆、压缩上下文、回滚记忆改动 | skillhub |
| `totorosir-workbuddy-score` | WorkBuddy 积分助手 | — | skillhub |
| `workbuddy-migration-assistant` | WorkBuddy 跨机器资产迁移助手 | — | skillhub |

## 逆向与软件解析（4）

| 技能 | 一句话 | 触发词 | 来源 |
|---|---|---|---|
| `rev-core` | 逆向分析入口与证据闸：授权开单、形态识别、证据校验、报告投影 | — | 自建 |
| `rev-runtime` | 动态观测：标准库 CDP 客户端、进程模块枚举、Frida 与代理薄封装 | — | 自建 |
| `rev-static` | 静态解构：零依赖字符串/PE 通道 + 外部工具通道（Ghidra/jadx/ilspycmd） | — | 自建 |
| `rev-verify` | 验证对拍：fixture 冻结与零容忍重放（静态 exact / 动态 subset） | 我看到过、任何人都能再验一遍 | 自建 |

---

## 附：治理现状

判定口径：目录名必须等于 frontmatter `name`，且不含 `__` 安装器后缀；`name` 只允许 `a-z0-9._-`。
实时判据以 `_governance/lint_skills.py --new-only` 为准，本节只是本轮快照。

### 命名待修（8 条，属「批次5 项3」，改名需先验证调用方）

| 目录 | frontmatter name | 问题 |
|---|---|---|
| `handoff__skillhub` | `handoff` | 目录名含 `__` 后缀；目录名 ≠ name |
| `memory-manager-v2__skillhub` | `memory-manager-v2` | 目录名含 `__` 后缀；目录名 ≠ name |
| `perfectly-replicate-writing-skills__skillhub` | `perfectly-replicate-writing-skills` | 目录名含 `__` 后缀；目录名 ≠ name |
| `python-crawler-architect__skillhub` | `Python 爬虫架构师` | 目录名含 `__` 后缀；目录名 ≠ name；name 非 slug |
| `self-improving__skillhub` | `Self-Improving + Proactive Agent` | 目录名含 `__` 后缀；目录名 ≠ name；name 非 slug |
| `tiangong-skill__skillhub` | `tiangong-skill` | 目录名含 `__` 后缀；目录名 ≠ name |
| `token-saver-qclaw__skillhub` | `token-saver-qclaw` | 目录名含 `__` 后缀；目录名 ≠ name |
| `workbuddy-speedup-diagnosis__skillhub` | `workbuddy-speedup` | 目录名含 `__` 后缀；目录名 ≠ name |

### 触发词待补（24 个）

这些技能的 description 里没有可抽取的触发短语（多为靠显式调用或任务语义触发的元层/平台技能）。
补法：在该技能 `description` 末尾加「当用户…时使用」，或在此处明细里人工确认「无需触发词」。

`browser-use`　`delivery-no-pseudoblock`　`dev-expert`　`github`　`grill-me`　`handoff__skillhub`　`ima-skills`　`mindmap-generator`　`nuwa-skill`　`python-crawler-architect__skillhub`　`rev-core`　`rev-runtime`　`rev-static`　`self-improving__skillhub`　`skill-vetter`　`systems-paper-writing`　`totorosir-workbuddy-score`　`ui-auto-click`　`web-access`　`wechat-article-scraper`　`word-docx`　`workbuddy-credit-usage`　`workbuddy-migration-assistant`　`workbuddy-speedup-diagnosis__skillhub`

### 体积超限（44 个 >10 KB，属「批次4 项10 渐进披露」）

`dev-expert`(65289B)　`nuwa-skill`(37967B)　`perfectly-replicate-writing-skills__skillhub`(33396B)　`totorosir-workbuddy-score`(32155B)　`literature-reviewer-skill`(28942B)　`paper-bilingual-search`(27809B)　`paper-quick-reader`(27627B)　`free-model-market`(24183B)　`creative-thinking-for-research`(22233B)　`lark-unified`(21394B)　`wechat-article-scraper`(20836B)　`luobo-ppt`(20705B)　`ui-auto-click`(20374B)　`brainstorming-research-ideas`(19519B)　`web-access`(18827B)　`memory-manager-v2__skillhub`(18658B)　`skill-optimizer`(18261B)　`ara-rigor-reviewer`(17922B)　`humanizer`(17709B)　`autoresearch`(16636B)　`repo-retrieval-governance`(16598B)　`minimax-docx`(15563B)　`ima-skills`(14920B)　`ara-compiler`(14904B)　`systems-paper-writing`(14573B)　`delivery-no-pseudoblock`(14556B)　`tiangong-skill__skillhub`(14076B)　`darwin-skill`(13911B)　`videos-content-analyzer`(13350B)　`junheng-labeling`(13293B)　`douyin-video-extract-copywriter`(13203B)　`sparse-autoencoder-training`(13051B)　`pdfkit-py`(12814B)　`ara-research-manager`(12747B)　`wechat-article-archive`(12633B)　`workbuddy-speedup-diagnosis__skillhub`(12275B)　`werss-ctl`(12268B)　`workbuddy-migration-assistant`(11935B)　`officecli`(11696B)　`browser-use`(11553B)　`ml-paper-writing`(11412B)　`junheng-standards`(10566B)　`presenting-conference-talks`(10507B)　`wechat-article-collector`(10485B)

### 非技能目录（无 `SKILL.md`，不计入索引）

`memory-manager-v2`

## 附：与其它文件的关系

| 文件 | 作用 | 真源 |
|---|---|---|
| `INDEX.md`（本文件） | 路由索引：有哪些、该用哪个 | 本文件由脚本生成 |
| `SKILLS-CATALOG.md` | 逐技能完整档案（含版本、完整 description） | 2026-10-25 快照，已过期，重建跑 `~/.workbuddy/gen-skills-catalog.py` |
| `GOVERNANCE.md` | 责任边界与 Tier 分级（为什么这样管） | 手工维护 |
| `_governance/lint_skills.py` | 命名与结构的机器判据 | 脚本即判据 |
| `_governance/taxonomy.json` | 族群与中文摘要的单一真源 | 手工维护 |

