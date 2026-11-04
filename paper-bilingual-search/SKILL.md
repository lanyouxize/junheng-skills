---
name: paper-bilingual-search
display_name: 论文检索·中英对照
display_name_en: Bilingual Paper Search
description: 在学术检索镜像站按关键词批量检索论文，提取英文原题、作者、期刊、年份与摘要，产出中英对照的 Markdown 与 CSV；可选补全 DOI、期刊全名与完整摘要并去重。当用户要批量找论文、做中英对照题录时用。
description_zh: 按关键词批量检索论文，产出「英文在上、中文在下」的中英对照报告（Markdown + CSV），附证据分级候选（研究设计/物种/样本量/剂量 + A-D 等级）与 PRISMA 式检索日志；可选 Europe PMC 补全、跨关键词去重；内置宠物食品行业关键词库。遇到人机验证或登录拦截时暂停等待用户手动完成，绝不绕过。当用户要求「检索论文/文献调研/中英对照文献列表/按关键词搜论文/证据分级/PRISMA 检索日志」时使用。
description_en: Bilingual literature search skill. Batch-searches the academic search mirror kuluer (xs.essclick.com) by keyword, extracts English titles, authors, sources, years and abstracts, and uses the site's own "translate this page" AI output to build English-on-top / Chinese-below parallel reports (Markdown + CSV). Optional --enrich completes DOI, full journal name and full English abstracts via Europe PMC; --dedupe removes cross-keyword duplicates; --evidence emits structured evidence-grading candidates (study design, species, sample size, dose, plus A-D grade candidates) and a PRISMA-style search log. Ships a pet-food industry keyword library. Pauses for the user to solve CAPTCHAs manually and never bypasses them. Use when the user asks to search papers, run a literature survey, build a bilingual literature list, or produce evidence grading and PRISMA search logs.
---

# 论文检索·中英对照（paper-bilingual-search）

## 目的与边界

按关键词检索论文，产出可快速审核的中英对照文献报告，并附带**证据分级候选标记**与**PRISMA 式检索日志**。
定位是**高效初筛 + 可追溯 + 可复核**，不是全文获取工具，更不是自动文献评价工具。

五条诚实性红线（违反即失职）：
1. **检索页摘要是「摘要节选」**（约 2 行、以 `…` 截断），报告中如实标注，不得冒充完整摘要。需要完整摘要时用 `--enrich`（Europe PMC 原文摘要）或点「原文直链」（出版社页常遇 Cloudflare → 走暂停等人协议）。
2. **中文一律使用站点「翻译本页结果」的 AI 译文**，报告头注明「AI 译文，非人工校对」。脚本与 AI 都不改写、不补写英文原文；站点译文缺失则标注「（未获取到站点译文）」。
   ★ **「站点译文」一律取记录级真值**（该条**是否真的带译文**），**不得**记为「翻译动作已触发」；站点翻译失败时按「否」登记，并在 PRISMA「异常」列标出 `translate:（状态名）`（v4.7）。
3. **人机验证（站内图片点选、Cloudflare、登录墙）只检测、不绕过**：检测到即暂停并提示用户手动完成，等待期间部分结果照常落盘。
4. **补全必须可证伪**：Europe PMC 匹配需「标题相似度 ≥0.6 + 年份一致」双重校验，不匹配就写 `unmatched`，绝不猜配。
5. **证据分级是候选标记，不是判定**：`--evidence` 输出的每个字段都带「候选值 + 原文依据片段 + 置信度」，`needsReview` 恒为 `true`。理由：只有摘要节选时判定研究类型必然不可靠，一旦把候选冒充成判定来支撑功效宣称，比不做分级更危险。**删除这段代码里的"依据/置信度/needsReview"以提高"准确度"的修改，一律视为严重回归。**

## 输入

| 参数 | 说明 | 默认 |
|---|---|---|
| `--keywords` | 关键词，可给多个（空格/换行分隔）。**必须带此开关** —— 裸词会被判「未知参数」并报错退出；也可改用 `--keywords-file`（每行一个，支持 `#` 注释） | 必填 |
| `--limit N` | 每关键词条数上限。**`0` = 计数探针** —— 只采集各检索式的「站点自报命中数」、**不抓取任何条目**（该模式下填充率 QC 自动豁免，**不会**以退出码 4 结束） | 10 |
| `--site` | **白名单枚举**，当前仅 `kuluer`（默认，无验证）。`panda985` 已探查但**本版本未接通**（v4.1 起传它会**报错退出**，不再静默回落） | kuluer |
| `--out DIR` | 输出目录（`--dir` 为等价别名） | 当前目录 |
| `--headless` | 无头模式（仅 kuluer） | 有头 |
| `--enrich` | 经 Europe PMC 补全 DOI/期刊全名/**英文原文完整摘要**（v4.3 起为**有界并发**） | 关 |
| `--enrich-concurrency N` | Europe PMC 补全并发度；`1` = 严格串行（v4.2 行为，可随时回退）；连续 429 会**自动降级串行**并告警 | 4 |
| `--fulltext` | **全文六级回退链**（v4.15）：T1 Europe PMC JATS XML（**有章节结构**）→ T2 PMC/EPMC 正文 HTML → **T2b PMC PDF**（扫描件的 OCR 文字层）→ T3 Unpaywall 定位 OA 版本 → **T3b OA PDF 直链** → T4 出版商页。抽方法学信号（随机化/盲法/交叉/洗脱/统计/对照），落盘 `fulltext/<PMCID或doi>.txt`（**偏移回查的唯一载体**）与 `.json`。**只补信息、不改等级**，抓取失败不降级。入口用 **PMCID 或 DOI**（站点通道由 `--enrich` 提供，多源通道自带）。实测 15 篇猫毛球：**6/15 → 9/15**（不开浏览器 8/15） | 关 |
| `--fulltext-concurrency N` | 全文抓取并发度（**上限 4**，全文响应比检索重得多）；`txt` 与 `json` 同时存在则直接复用，不重复下载 | 2 |
| `--fulltext-browser` | 为 T2/**T2b**/T4 启用**浏览器兜底**（过 JS 挑战 / PMC 的 PoW）。**默认关**：Cloudflare 那 4 篇（A1/A5/A6/A8）开与不开都拿不到（headless 与 headed 实测均 `Just a moment...`）；开了只多几分钟等待换 1 篇增量 —— 即 T2b 那个 PMC 扫描件。浏览器不可用时该级记 `skipped`，**不算失败** | 关 |
| `--dedupe` | 跨关键词去重（v4.2 起为**并查集连通**：DOI 归一化后与标题双向互链；同标题但年份已知且不同 → 视为不同文献；无可判定标识的记录**不参与去重**） | 关 |
| `--evidence` | **证据分级结构化**（研究设计/物种/样本量/剂量 + A-D 等级候选） | 关 |
| `--plan FILE` | `build-queries.cjs` 产出的 `plan.json` → 把每条检索式溯源到源清单章节 | 无 |
| `--fill-min F` | 标题填充率下限，低于则判静默降级失败（取值 `0`~`1`） | 0.9 |
| `--keyword-timeout S` | 单关键词硬超时（看门狗） | 300 |
| `--ready-timeout S` | **等待结果渲染超时**（站点高峰期实测需 30s，勿调低于 30） | 45 |
| `--gate-timeout S` | 验证等待上限 | 300 |
| `--interval A,B` | 页间随机间隔毫秒（需 `下限 ≤ 上限`） | 2500,4500 |
| `--sources SPEC` | **多源 HTTP 通道**（v4.15）：`all` / `http` / `europepmc,crossref` / `all,-crossref`。**检索层不启动浏览器**（playwright 惰性加载，无 Edge/Chrome 的 CI 可跑）；**全文层**（T2b/T4）仍可由 `--fulltext-browser` 显式开启（默认关）—— 两套浏览器互不影响，且**不再有站点 AI 译文**；不给则完全走原站点通道（v4.14 行为，零变化）。与 `--site` 互斥；`kuluer` 尚未迁入连接器层，传它会报错并给改法 | 无（站点通道） |
| `--mailto EMAIL` | 礼貌池标识（Crossref 建议带）。格式错会**报错**——错格式会被 Crossref 静默忽略，礼貌池不生效 | 无 |
| `--source-timeout S` | 单源外层超时。**必须大于连接器内层最坏值**（单次 25s × 3 次重试 + 退避），调小会制造假失败 | 120 |
| `--source-concurrency N` | http 源并发度（**上限 8**：公开 API 限流阈值普遍 5–10 QPS，再高只换来 429） | 2 |

**输入校验约定（v4 起，见 CHANGELOG）**：

- 数值参数只接受合法范围内的数：`--limit abc` / `--limit -1` / `--fill-min 1.5` / `--interval abc` 一律**报错退出（码 1）并给出示例**，不再静默回落默认值。
- 任一 `--xxx` 后缺值（如 `--keywords-file` 单独出现）→ 报「缺少取值 + 示例」，不产生裸栈。
- `--keywords` 后面若出现**未知的长选项**（如把 `--limit` 拼成 `--limt`）→ 报 `未知参数`，不再静默吞进关键词。
- `--keywords a b c` 与 `--keywords "a b c"` 含义不同（前者 3 条、后者 1 条）。解析出多条且都不含空格时会打印一条 `[提示]`；每次运行也会回显**生效关键词条数与来源**（命令行 / 文件）。
- 命令行关键词与文件关键词合并时：**命令行在前**、去重保留首次出现（即命令行优先）。
- `--out` / `--dir` 指向已存在的**普通文件**→ 报 `--out 需要目录`（脚本不会删除或改写你的文件）。
- 关键词文件路径不存在 / 指向目录 → 分别给出可执行提示。


### 需要细节时再读

主文件只留「怎么跑」。检索式构造与多轮迭代的完整细节在 references/，按当前问题选一篇读，不要两篇都读：

| 内容 | 何时读 | 文件 |
|------|--------|------|
| 检索式构造 | 要写或改检索式、判断走哪条通道、看计数探针读法时 | `references/query-construction.md` |
| 覆盖诊断与迭代 | 跑 `--apply` 补词、跑 `--iterate` 多轮、看到覆盖诊断失分时 | `references/rank-iterate.md` |
| 关键词库（可读版） | 只想直接读术语清单、不跑脚本时 | `references/petfood-keywords.md` |
| 关键词库（机器版） | 要程序化解析 35 组 / 854 术语时 | `assets/petfood-keywords.json`（只读产物） |
| 站点档案 | 要确认某站点实测能力与已知坑时 | `references/sites.md` |

## 执行流程

1. **预检**：`playwright-core`（托管工作区）+ 本机 Edge/Chrome（可用 `WB_BROWSER_PATH` 覆盖）。**不要用 agent-browser**（实测不可用，见 references/sites.md）。
2. **构造检索式**（可选）：按上节先生成 `queries.txt` + `plan.json`。
3. **检索**：`node scripts/search-papers.cjs --keywords-file q.txt --plan plan.json --limit N --out DIR [--headless] [--enrich] [--dedupe] [--evidence]`
4. **验证拦截**：检测到验证页 → 报告类型与已获条数 → 有头窗口等人 → 每 2 秒轮询至 `--gate-timeout`；超时保留部分结果，退出码 2。
5. **提取**：降级链（类名选择器 → 结构位置推断），每次提取记录**字段填充率**；同时采集站点自报的「约 N 条结果」计数（PRISMA Identification 用）；每页提取后立即落盘 `raw/NN-<关键词>.json`（`NN` 为关键词的保序序号，文件内含 `runId` 与 `kwIndex`）。
6. **质量自检（反静默降级）**：标题填充率 < `--fill-min` 即判失败（退出码 4）；另若**全部关键词 0 条且站点未给任何计数**，判为站点侧疑似不可用（退出码 5），**不得据此判定检索式无效**（2026-10-04 实测：站点渲染延迟达 30s，早于此的"无结果"是假阴性）。
7. **可选补全 / 去重 / 分级**：`--enrich` 调 Europe PMC 补全（**有界并发**，默认 4；`--enrich-concurrency 1` 回退严格串行；连续 429 自动降级串行并打印 `[WARN]`）；`--dedupe` 输出 `dedupe.json`；`--evidence` 本地纯计算，输出每条的四维候选与 `gradeBasis`。
8. **PRISMA 日志**：默认必写 `PRISMA.md` + `prisma.json`（识别/筛选/资格/纳入四段计数 + 各检索式明细 + 异常登记 + 方法学限制）。**工具恒不做资格排除**（`excludedByTool` 恒为 0），需人工复核的条目单独列表且仍计入纳入数。其中「**站点译文**」列 = **该检索式是否真的取到译文**（记录级真值，v4.7），翻译失败时原因在「**异常**」列显式标为 `translate:（状态名）`（如 `translate:all_failed`）。**v4.10 起**若加 `--fulltext`，另落盘 `fulltext/<pmcid>.txt`（文本化全文，**偏移回查的唯一载体**）与 `fulltext/<pmcid>.json`（方法学信号抽取结果），并在汇总里给出「**全文通道**」行：有 PMC 全文 N 条 / 已取 N（新抓+缓存）/ 失败 N / **OA 但无 PMC 全文 N 条**（矛盾态单列，不是抓取失败）。
9. **汇总**：`node scripts/assemble-report.cjs --dir DIR` → `report.md` + `report.csv`。空结果/异常关键词**必须显式列出**。
   同一目录里若混有**非本次运行**的陈旧 `raw/`（`runId` 不匹配）或**损坏**的 JSON，汇总端会跳过它们并在报告头显式登记「已忽略 N 个」「已跳过 N 个」，**不会静默并入、也不会整份崩掉**；`raw/` 内没有 `runId` 的旧产物按兼容分支照常纳入。
10. **可选·检索后过滤**：`node scripts/rank-records.cjs --dir DIR --topic "…" [--near "…"] [--exclude "…"]` → `ranked.md/csv/json`。
    **零站点请求**（纯本地重排，词表可反复调）；把真相关条目排到前面，**人只看前 N 条**。分档与权重见「检索后过滤」节。
11. **收尾**：向用户转述 summary 的 errors/warnings、QC 填充率、补全统计、证据等级分布与「需人工处理条目」数。

## 输出字段（顺序固定）

标题(EN) → 标题译文(ZH) → 作者 → 来源/期刊 → 年份 → 被引 → 期刊全名 → DOI → 来源域 → 链接 → 摘要节选(EN) → 完整摘要(Europe PMC，命中时) → 摘要译文(ZH) → **证据分级候选**（等级/设计/物种/样本量/剂量/复核标记）

## 证据分级规则（--evidence）

| 维度 | 取值 | 说明 |
|---|---|---|
| 设计等级 | L1 系统评价/Meta → L2 RCT → L3 对照/交叉/饲喂试验 → L4 观察性/病例/体外 → L5 综述/述评 → U 未识别 | 中英文双规则，取优先级最高者；跨等级命中差 ≥2 级或「综述 vs 原始研究」互斥时标 `design_conflict` |
| 物种相关性 | `target_species`（犬猫）/ `mixed_species` / `non_target_animal` / `in_vitro_only` / `unclear` | 命中畜禽·啮齿者标 `non_target_species_verify`，对应源清单「结论需人工排除猪鸡等畜禽文献」 |
| 样本量 / 剂量 | 多候选值 + 原文片段 | 宁可给候选让人工挑，也不猜一个 |
| 综合等级 | A/B/C/D = 设计等级 × 物种相关性（见 `lib/evidence.cjs` 的 GRADE_MATRIX） | A=靶动物 RCT/SR；D 档另给 `gradeBasis` **区分两种成因**：`design_unrecognized`（设计未识别·信息不足）与 `design_identified`（已判定但确证薄弱）—— v4.3 起报告中分开标注，避免真实试验被 U→D 的静默传导埋没 |

> v4.4 起：中文兜底规则已以 **20 条真实中文数据**量化（D 档 **−79%**，真阳性 **11/11**）；该规则族实际是「**汉字圈语言**」规则（日文文献共用汉字「消化率」同样命中）。

> v4.5 起：新增**物种语境排除** —— 靶物种词出现在病名 / 疫苗 / 毒株中时不计入物种识别（如「水貂接种**犬**瘟热疫苗」不再误判为犬）；同时补齐中文非靶物种词（水貂 / 雪貂 / 狐 / 貉 等）与英文 `rooster` / `cockerel`。详见 CHANGELOG v4.5。

> v4.6 起：**`--limit 0` = 计数探针** —— 只采集各检索式的「站点自报命中数」而不抓条目，用于**先比命中量、再决定跑哪条检索式**（零抓取成本）。
> 该模式下**豁免填充率 QC**（0 条是用户显式要求的结果）；此前它会被误判为「疑似选择器失效」并以退出码 4 结束，属**假诊断**。详见 CHANGELOG v4.6。

> v4.7 起：**站点 AI 翻译的「失败态」不再被记成「成功」**。站点 `/api/ai/translate` 限流（实测 429）时，
> 翻译面板会自渲染「翻译失败 / 重试」，而旧版只等面板**元素出现**即记为「站点译文=是」，
> 于是报告头「中文填充率 0%」与 PRISMA「站点译文＝是」**同时出现且自相矛盾**。
> 本版把判定拆成两层：**记录级真值**（`hasSiteTranslation`：该条是否真的带译文，权威、不依赖站点文案）
> + **动作级诊断**（`translateStatus`：`ok` / `partial_failed` / `all_failed` / `no_button` / `panel_timeout`）。
> 整批 0 条译文时报告会**显式提醒**（不再是静默的空列）。详见 CHANGELOG v4.7。

复核标记一览见 `report.md` 的「需人工处理条目」表。两个高频标记：
- `grading_from_snippet_only`：仅依据摘要节选分级，可靠性低 → **先 `--enrich` 补全再分级**是推荐做法；
- `non_target_species_verify`：物种可能不是犬猫靶动物，必须先人工剔除。

## 检索后过滤（rank-records，本地零站点请求）

站点检索引擎是**宽匹配** —— 布尔约束力弱，连 `AND` 都被稀释：实测 `(犬 OR 猫) AND (毛球 OR 化毛)` 自报 7 条，
取回的首条却是「哺乳动物**毛球**（毛囊球部）生长调控」——**字符串命中等同歧义命中**。
所以检索之后**必须**再做一次本地相关性过滤，人只需看前 N 条。

本步骤**不联网**：只读 `search-papers` 已落盘的 `raw/*.json`，产物里恒显式声明 `站点请求: 0`。
抓取贵（单条检索式 3~60 秒）、过滤应当廉价 ⇒ **改词表可零成本反复重排**。

```bash
node scripts/rank-records.cjs --dir DIR \
  --topic "毛球,毛球症,化毛,排毛,hairball,trichobezoar,bezoar" \
  --near "毛发,毛皮,皮肤,膳食纤维,fiber" \
  --exclude "毛囊,球部,follicle" \
  --top 10 --format both
```

| 参数 | 说明 |
|---|---|
| `--topic` | **必填**。主题术语，逗号分隔（中英文兼可）。**空词表直接报错**，防「没配词表」被当成「全部跑题」 |
| `--near` | 相邻词，只作弱信号（题名 ×1 / 摘要 ×0.5） |
| `--exclude` | 排除词，**一票否决**降为跑题，但记录与命中上下文**仍保留**（绝不静默丢弃） |
| `--top` / `--all` | md/csv 输出前 N 条（默认 10）/ 全量；**排序计算始终覆盖全量** |
| `--format` | `md` / `csv` / `json` / `both`（默认 both）；`--full` 让 json 附完整记录 |

**分档与权重**：题名 ×3 / 摘要 ×1。命中题名 → 「主题命中」；仅摘要命中 1 词 → 「相邻主题」；其余 → 「跑题/待人工」。
每份产物附「**命中上下文**」，供人工判断是精确命中还是**歧义命中** —— 这是目前唯一可靠的依据。

**与 `--evidence` 的分工（正交，可同时用于同一条记录）**：

| 维度 | `--evidence` | `rank-records` |
|---|---|---|
| 回答的问题 | 「这条研究的**设计**值几分证据」（A–D） | 「这条**是不是我要的主题**」（主题命中/相邻/跑题） |
| 时机 | 抓取时（`--evidence`） | 抓取**之后**，可反复重排 |

> v4.7 挂账（2026-10-16 实测）：13 条术语型结果中，2 条真相关**精确排到第 1、2 位**，歧义命中（毛囊球部）**被压到跑题档**；
> 对 N3 那批裸词结果排序得 exact **0/10**，**与此前人工字符串级核查完全吻合** ⇒ 本工具**不制造假阳性**。
> 详见 CHANGELOG `[v4.8]` 四。

**★ 词形边界已由代码自动归一（v4.7 挂账，2026-10-16 落地）**：

排序器在**压缩文本**上匹配 —— 归一化后**两侧同时**剥掉「空白 + 破折号族」，并做**繁 → 简**单字归一 ⇒ 三类形态差异自动等价：

| 族 | 归一方式 | 例（词表 ↔ 文献实际写法） |
|---|---|---|
| **破折号族 ↔ 空格** | 13 个码点（hyphen / soft hyphen / U+2010–U+2015 / minus / hyphen bullet / 小型与全角形）一律剥离 | `gut kidney axis` ↔ `gut–kidney axis`（en-dash） |
| **繁 ↔ 简** | 151 字高频表（**限域**：宠物营养 / 兽医临床 / 科研文献） | `肾脏` / `肠道` ↔ `腎臟` / `腸道` |
| **连写 ↔ 分写** | 空白剥离 ⇒ 两侧塌成同一形态 | `hairball` ↔ `hair ball` |

⚠️ **两条正交的防线，不可互相替代** ——
- **形态**由代码兜住（上表三类，**无需**再人肉列多形态）；
- **覆盖**仍靠人 —— 词表里**没有**的主题词永远不会命中。实测：繁体猫 CKD 学位论文经归一化
  从 rank 35/跑题 → **rank 16/相邻**，但题名仍 0 命中（词表缺「肾脏保健 / 乳酸杆菌」这类中文主题词）。

⇒ **判据修正**：上一节「主题有文献时可只看前 N 条」**仍须限定** —— 词表覆盖面未知时
**连「跑题档」一起通读**（真相关条目可能既缺词、又缺形态）。
⚠️ **已知边界（如实登记）**：压缩匹配会让「跨词边界的偶然拼接」也命中（词表 `cat dog` 命中 `concatdog`）
⇒ **排除词 + 人工核读（`snippet` 保留原文形态）仍是最后一道闸**。

**★ 本步骤不跨检索式去重**：同一文献会出现在它所命中的**每一条**检索式下（重复占位）。
多检索式同目录时，先按题名去重再排序（见 CHANGELOG `[v4.8]` 六）。

## 错误处理

| 退出码 | 含义 | 处置 |
|---|---|---|
| 0 | 成功（QC 通过） | — |
| 2 | 验证等待超时 | 说明等待时长与保留条数；建议换 kuluer 通道或有头重跑 |
| 3 | 疑似结构变化（有计数但无条目） | 人工核对截图，按 references/sites.md 校准 |
| 4 | **质量自检未通过**（大面积空字段 = 静默降级）。**`--limit 0` 计数探针除外**（0 条是预期结果） | 优先怀疑选择器/序列化问题，看 `diagnostics.json` 的 strategy 与 error |
| 5 | **疑似站点侧不可用**（全 0 条且无任何计数） | 加大 `--ready-timeout` 或稍后重试；**不要**据此改检索式 |
| 1 | 其他错误（网络/超时） | 转述具体错误 |

`no_results_unconfirmed`（站点未给明确无结果信号）属警告级，不计错误。

## 离线自检

`node scripts/test-unit.cjs` —— **569 项**纯逻辑离线自测：byline 解析、DOI、填充率、相似度、CSV 转义、证据分级（含中文规则）、检索式语法黑名单、PRISMA 计数，以及输入层、去重、全文六级回退各组的结构守卫。

覆盖面**完整清单** → [references/test-inventory.md](references/test-inventory.md)。

改动后必跑，退出码非 0 即为回归。

## 站点事实与校准

唯一事实来源是 **references/sites.md**（含 kuluer 完整 DOM 映射、EPMC 补全实测、序列化陷阱、延迟实测、校准流程；**v4.4 已撤回「突发 ⇒ 持续限流」的归因**，见其「★ 归因订正」小节）。提取异常时先读它再动脚本；改完用一个真实关键词跑 1 页验证再恢复批量。

## 版本

当前 **v4.15**（2026-10-26）：**换掉单点依赖**——三批合成一版，动的都是「只有一个来源、挂了还看不出来」的地方。① **多源层**（`lib/sources/*` + `lib/scheduler.cjs` + `lib/multi-run.cjs`，参数 `--sources`）：同一批 4 条猫毛球检索式，kuluer 站点 3 条 `collect_failed`（`page.goto` 30s 超时），而整次运行只在「全 0 且无读数」时报警 ⇒ 部分失败完全静默，使用者可能据此**误排除一条本来有效的检索式**；改为 6 个零依赖连接器模块 + 调度器（**计数语义分流**：`none` 型源走 `not_applicable`，照搬三态会把「本次没有可计数的源」判成假故障并污染 `siteDegraded`；单源抛异常或超时只记一条告警；跨源去重 DOI 优先，无 DOI 按「规范化标题 + 年份 ±1」，`fibre`/`fiber` 用英式-美式白名单折叠）。给 `--sources` 即**检索层不启动浏览器**（playwright 改惰性加载，无 Edge/Chrome 的 CI 可跑）；全文层的浏览器是**另一套**（`fulltext-chain` 自己的 `openBrowser()`），默认关、给 `--fulltext-browser` 即可用—— 实测 `--sources europepmc --fulltext --fulltext-browser` 可走到 T2b（`byTier` 记 `T2b_pmc_pdf: 1`，72998 B）。② **全文六级回退链**（`lib/fulltext-chain.cjs`）：T1 EPMC JATS XML → T2 PMC 正文 HTML → **T2b PMC PDF** → T3 Unpaywall → **T3b OA PDF 直链** → T4 出版商页；入口从「只认 `enrich.pmcid`」改为 **pmcid / doi 双入口**——原缺陷的根因不是「没有全文」而是「只有一条路」，6 篇有 DOI 无 PMCID 的文献连入口都进不去。实测 15 篇猫毛球 **6/15 → 9/15**（不开浏览器 8/15）。③ **PDF 文本抽取**（`lib/pdf-extract.cjs`，零依赖、只用内置 `zlib`）：**抽不到就报原因，绝不产半截正文**——五类明确拒绝（加密 / 无文字层 / CID 无 ToUnicode / 控制字符超标 / **词间距丢失**），对 T1 XML 真值召回 **95.4%**。★ **两条新闸门**：**全文真伪**（标题实词命中 ≥2 且 ≥40%；标题缺失时**不做**归属校验，改要求 ≥800 词并登记 `titleCheck: unavailable`——只看字数会把挑战页与导航页判成全文，合成挑战页 808 词一度判 ok）；**样板页**（词数低于 400 且散文行占比低于 10% ⇒ `page_is_chrome`；判据取自真实样本 0.04 对 0.11–0.82，不是猜的）。★ **有链接 ≠ 下得下来**：Unpaywall 给 11 个 PDF 直链，实测仅 1 个真回 PDF 文件头（Wiley / Elsevier / MDPI 全 403，换 4 组请求头变体仍全 403）⇒ 下不动的只登记地址、**不计入已获取**，否则可得率虚高。★ 上一版上报的 9/15 里有 **1 篇是假阳性**（1960 年那篇 227 词中正文 0 词，全是站点样板），本版把它修成真全文 265 词。闸门 459 → **569**；变异 9/9 + 15/15 + 10/10 + 12/12 + 4/4 全部命中目标断言。详见 CHANGELOG `[v4.15]` 段。

历史版本（v4.14 及之前：v4.14 状态文件四条失效收口 / v4.13 资料库 direct-edit 预检 / v4.12 综合归纳与元典站点包 / v4.11 证据分布三张图 / v4.10 Europe PMC 全文通道 …）见 [CHANGELOG.md](CHANGELOG.md)。

> 正文中「v4.x 已撤回 / 新增」的标注是**出处引用**，需要细节时回查 CHANGELOG，不要据本节推测行为。
## 已知限制（如实告知用户）

- 摘要节选非全文；`--enrich` 命中率随文献年代/语种下降（英文生物医学文献高，中文文献多 `unmatched`）。
- 中文为站点 AI 译文；术语译名可能不统一，复核以英文原文为准。
- **证据分级为启发式候选**，未经全文核对；正式宣称支撑必须人工读方法学章节。
- 状态文件旁可能出现三类伴随文件：`<状态文件>.lock`（仅在持锁瞬间存在，**残留超过 10 s 即被视为崩溃遗留并被下一轮抢占**）、状态文件名加 `.corrupt-` / `.legacy-` 与 UTC 时间戳的备份（解析失败 / 版本不符时的逐字节留档）。这三种都不是故障，**不要手删**。
- **备份是留档，不是自动修复**：`corrupt` 时活文件仍会被重建成只含本轮主题的 1 个槽，恢复旧槽只能人工从备份取回（不做「猜格式抢救」—— 那会引入比丢失更糟的静默错误）。备份也不自动清理。
- PRISMA 日志遵循 PRISMA 2020 分段命名，但因数据源为学术搜索引擎镜像且未做人工资格评估，**不可直接用作正式系统综述的 flow diagram**。
- 无结果不代表该主题无研究，可能是索引覆盖、检索式写法或站点延迟问题。
