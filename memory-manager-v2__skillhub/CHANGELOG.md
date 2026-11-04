# Changelog

## [4.0.6] - 2026-09-14
### 上架受阻修复：随包许可证改为带扩展名（零代码、零行为变更）
- **问题**：平台上传 `memory-manager-v2-4.0.5.zip` 被拒，报错「不允许的文件类型：LICENSE」。根因是包内随包许可证是**无扩展名文件** `LICENSE`，而上传器按扩展名白名单放行（现存包允许的后缀实测为 `.json .md .py .txt`）。这与 COMP-2（声明 MIT 须与随包 `LICENSE` 一致）**正面冲突**：合规要求必须带许可证文件，上传器却只认带后缀的文件。
- **修复**：随包许可证由 `LICENSE` 改名为 **`LICENSE.txt`**，内容一字未动（MIT 全文，1,076 字节，`md5 4e976c1514dc8ae8d878f4f83e5876a5`，LF 换行）。包内**不再有任何无扩展名条目**。
- **依据**：平台内置技能实测 18 例，技能根许可证一律带后缀，其中 `LICENSE.txt` 8 例（`skill-creator`、`expert-manager`、`skill-expert-manager`、`skill-skill-creator`）—— 这些来自 BuiltinMarket 渠道且已成功上架，是 `.txt` 可用的最强证据。
- **闸门补强**：合规复测新增 **UPLOAD-2「包内条目扩展名白名单」**（正向白名单 `.json .md .py .txt`）。此前 UPLOAD-1 是**黑名单**（列二进制后缀），天生抓不到「没有后缀」这一类，本事故即由此漏过。新增闸门写入 `memory_manager/tests/` 与终验脚本。
- **版本 4.0.5 → 4.0.6**：包内文件更名须升版。CLI 命令数 / 别名数 / Bridge 方法数 / i18n 键数 / 模块数 / 包内文件数（`38` / `.skill` `33`）**全部不变**。
- 触发原因：上架上传被平台拦下，详见 `记忆管家V4.0.6_上架受阻修复报告.md`。

## [4.0.5] - 2026-09-14
### 版本一致性基建（零功能变更、零包内文件增删）
- **P0-01 消除第 7 个版本落点**：`memory_manager/__init__.py` 改为 `VERSION = "4.0.5"` 与 `__version__ = VERSION`（同源派生）。此前**同一文件并存两行版本常量**，`__version__ = "4.0.2"` 自 V4.0.2 起静默漂移三个版本，并随 V4.0.3 / V4.0.4 两个发货包出厂。根因不是「忘了改」，而是它**没有任何消费方、不在任何闸门的观测面上**。
- **P0-02 建立单一版本源**：新增 `tools/version_sync.py`（`--check` / `--write`），以 `memory_manager/config.py::VERSION` 为**唯一真源**派生全部版本落点，`--check` 纳入发布闸门。需手改的落点 6 → **1**，机制上杜绝已发生过的三类事故：`requirements.txt` 注释陈旧、en 文案指纹表只改一半、`__version__` 长期漂移。
- **P1-03 平台面向字段统一口径**：`SKILL.md` frontmatter `description` 与 `skillhub.json` `description` 改为共用**同一段版本无关能力描述**。此前一个写 V4.0.3、一个写 V4.0.4 —— 描述同一套能力却叙事互斥。升版从此**不再需要改动平台路由字段**（落点再减 2）。
- **P1-04 en 构建源补齐工程结构**：`memory-manager-en/` 补上 `tests/`（12 个测试文件）并同步 `tools/` 探针，可**独立**跑 pytest 与 i18n 运行期探针（该缺口连续三版遗留）。`tests/` 与 `tools/` 均**不进发货包**。
- **P1-05 三副本单向派生**：新增 `tools/sync_copies.py`，`build/memory-manager-v3/` 为**唯一真源**，en 源与工厂根镜像由脚本派生。语言相关文件（`SKILL.md` / `CHANGELOG.md` / `skillhub.json` / `sbom.json`）进白名单，**永不从 zh 覆盖到 en** —— 这是「en SKILL.md 被中文版覆盖」事故的直接防线。同步从此靠脚本 + 反向 diff，而非纪律。
- **平台合规复核拦下并修正**：规范段首版把 en 侧写成 **1537 字符**，被平台 COMP-1（`description` 无尖括号且 **≤1024 字符**）拦下 —— 已压缩至 zh **551** / en **996**，并把该限额钉进包内测试与发布终验（`skillhub description 满足平台 COMP-1`）。
- **新增测试** `tests/test_version_consistency.py`（9 用例）：同源断言、跨文件版本一致、平台面向字段无裸版本号、两处 description 前缀契约、COMP-1 长度限额，并把 `version_sync.py --check` 当**运行期闸门**跑一遍（静态断言之外的独立路径）。
- **本版不改行为**：CLI 命令数 / 别名数 / Bridge 方法数 / i18n 键数 / 模块数 / 包内文件数**全部不变**，只改内容不加文件。

## [4.0.4] - 2026-09-14
### 上架元数据合规补齐（纯元数据，零代码变更）
- **COMP-1 必备字段**：`skillhub.json` 新增 `homepage`（指向 SkillHub 条目页）与 `repository`（显式置空，与已上架的 `skillhub-release-playbook` 同口径）。
- **COMP-2 声明一致**：新增随包 `LICENSE`（MIT 全文），与 `skillhub.json` 的 `license: "MIT"` 声明一致。
- **版本 4.0.3 → 4.0.4**：包内新增文件必须升版。CLI 命令数 / i18n 键数 / Bridge 方法数 / 安全契约口径**全部不变**。
- **顺带修正**：`requirements.txt` 首行版本注释长期停留在 V4.0.2，同步为 V4.0.4。
- 触发原因：上架前置合规复核发现 COMP-1 / COMP-2 两处缺口，详见 `记忆管家V4.0.4_上架合规补齐报告.md`。

## [4.0.3] - 2026-09-14
### 安全加固（`references/security.md` §八 残余风险收敛 4 项 + 新增 2 项校验能力）
- **写入型命令补交互确认门**：`import` / `archive --execute` / `backup --restore --execute` / `snapshot --restore --execute` 此前**没有任何确认**，非 TTY 脚本调用即直接写入记忆目录。现全部走交互式二次确认（非 TTY 直接拒绝），`--force` 显式跳过。确认门由 2 个调用点增至 **6 个**。
- **`--json` 下不打印人类提示**：`--json` 模式直接返回 `{"status":"cancelled","reason":"confirmation_required"}`。此前提示散文会先写进 stdout，把机器可读输出污染成「散文 + JSON」混合体，下游 JSON 解析必然失败。该模式唯一放行方式是 `--force`。
- **SHA256SUMS 完整性清单**：快照与备份产物落盘时同时写一份 GNU coreutils 格式的校验和清单，可用系统 `sha256sum -c` 交叉验证。哈希为**整文件** sha256 —— `token.compute_content_hash` 只读前 50KB，拿它做清单会让 50KB 之后的改动完全逃逸（「假完整性」）。
- **新增 `backup --verify` / `snapshot --verify`**（只读）：判通过要求「哈希全对 **且** 无缺失 **且** 无清单外新增文件」；清单缺失返回 `ok=false` 而非「无从校验故放过」。
- **新增 `harden` 子命令（别名 `hd`）**：把记忆目录 / 快照目录 / 备份目录收敛为 **目录 0700 / 文件 0600**，默认只预览、`--execute` 才 chmod。**仅 POSIX 生效**：Windows 的 `os.chmod` 没有权限位语义，明确返回 `supported=false`（提示「不适用」）而不是跑一遍代码就当已保护。
- **产物自动收敛**：快照、备份目录与导出 ZIP 落盘后自动收敛权限（POSIX，best-effort，失败只记告警、不阻断主操作）。
- **文档纠错**：`SKILL.md` 的「安全门禁规则」表此前声称 `import` 等「必须 `--execute`」，而 `import` **连 `--execute` 参数都不存在** —— 属「写了但没验」的失实声明，已按实际行为改写。

### 实测口径（较 V4.0.2 的变动，均由 `tests/test_security_doc_claims.py` 三方互钉）
- 符号链接防护点 20 → **23 处**；工作区边界校验 21 → **23 处**（增量全部来自新增的 `core_perms.py`）。
- 交互式二次确认门 2 → **6 个调用点**。
- 新增钉死口径：完整性清单写入点 **2 处** / 校验入口 **2 处** / 权限收敛调用点 **4 处**。

### 测试
- 新增 `tests/test_hardening_v403.py`：整文件哈希（50KB 之后改写必须被检出）、清单往返、篡改 / 缺失 / 清单外新增的检出、快照与备份的清单固化、`harden` 平台诚实性、6 个确认门在非 TTY 下**确实没落盘**、`--json` 拒绝为纯 JSON。
- 运行期 i18n 探针把 `harden` 与 4 条确认门路径纳入矩阵，防止新文案成为「定义了却没接线」的死键。

## [4.0.2] - 2026-09-14
### 安全修复（科恩实验室视角 + 云鼎实验室视角评估的 P0 三项 + P1 六项，全部落地）
- **ZIP 路径穿越的首段例外**：`_path_has_traversal` 原写作 `... and i > 0`，对**首段**放行，于是 `../x.md` 被判为「无穿越」。现要求任一分量为 `..` 或空即拒，不再有位置豁免。此前该输入虽被工作区边界兜住，但「拒绝」被降级成了「碰巧拦下」。
- **ZIP 单文件超限改为拒绝落盘**：原实现只把超限写进 `errors` 却不跳过，20MB 文件照样落盘；而读取侧 1MB 上限又让它永远读不出来（`analyze` 报 0 文件，只有 `doctor` 报「异常大文件」）—— 等于往记忆目录里塞了颗哑弹。现在预检返回 `oversized` 集合并由写入循环跳过。
- **备份还原的「假完整性」**：备份清单记录了每文件哈希，`restore_backup` 却从不读取该字段。现逐文件校验，不一致即跳过并计入新增的 `skipped` 字段。
- **备份清单视为不可信输入**：还原前校验 key 的边界（穿越分量 / 绝对路径 / 解析越界一律拒绝）。此前把清单里的 key 直接拼进目标路径。
- **落盘前自动快照补齐至 6 处**：`clean` / `cache-clean` / `dedup` / `archive` 新增落盘前建快照（此前只有 `govern` / `compact` 有）；新增统一入口 `core_snapshot.snapshot_before_write()`，且**快照失败不阻断主操作**。其中 `archive` 是真正 `unlink` 记忆文件的路径，此前完全没有兜底。
- **`dedup --execute` 的静默假成功**：`_delete_dup_file` 把「相对记忆目录」的路径拼到了工作区根，`unlink` 必然 `FileNotFoundError` 并被 `non-fatal` 日志吞掉 —— 命令报告「已删除 N 个重复项、释放 X KB」，而磁盘上**一个文件都没删**。现拼接正确，且只按**实测**记账（新增 `deleted` / `freed_kb` / `errors`），部分失败在 CLI 上显式可见。
- **`cache_clean` 非 TTY 崩栈**：`dry_run=False, confirm=False` 且非交互终端时 `input()` 抛 `EOFError` 未被捕获。现先判 TTY，非交互直接安全取消。
- **移除 `_h_config` 中多余的 `__import__("memory_manager.config", ...)`** 动态导入（同函数下一行本就是普通 `from .config import ...`），使「0 处 `__import__`」的声明重新成立。
### 文档与供应链
- **删除失实安全声明**：`references/security.md` 原称「破坏性操作必须 `--confirm`」（该参数全库**不存在**，实际是 `-f/--force`）、「XSS 全字段 `html.escape()`」（**0 处**，且本技能**没有任何 HTML 输出面**，是面向不存在攻击面的虚假声明）；ZIP Slip 层数在 `SKILL.md` 与本文件之间**各写一个数字、互相矛盾**；「删除确认 34 处」实测只有 2 个调用点。现已全部改为**可复核的实测值**，并由新增的 `tests/test_security_doc_claims.py` 逐条钉死（文档值 == 测试字面量 == 源码实测值，任一方单独变动即失败）。
- **SBOM / requirements 补齐依赖清单**：`memory_manager/` 实际 import 的非标准库模块是 `{colorama, jieba, tiktoken}`，而原 `sbom.json` / `requirements.txt` **只声明了 tiktoken** —— 依赖清单漏报两项，漏洞响应链路因此失效。现补齐三项（均标 optional），并新增 `tests/test_dependency_manifest.py` 强制「声明 ⊇ 实际 import」双向一致。
- **`tiktoken` 版本约束收紧**：`>=0.7.0` → `>=0.13.0,<1.0.0`。下限依据：0.13.0 修复 RUSTSEC-2026-0176 / RUSTSEC-2026-0177（PyO3 升至 0.29，见 Fedora 安全更新 FEDORA-2026-e0bcb90c9f）。`known_cves` 由失实的 `"none (latest 0.7.0)"` 改为带**来源与检索日期**的陈述，并加注同名投毒包 `tiktoken-mcp`（MAL-2026-5326 / PYSEC-2026-1075 / GHSA-wj5q-fgqm-2wv6，受影响 0.13.1 / 0.13.2，无补丁版本）的包名混淆警示。
- 新增 `references/security.md` **§一 信任边界**：记忆内容一律视为**不可信数据**，只被计数 / 排序 / 截断 / 复制 / 删除，绝不作为指令执行；并明确本技能**不做注入拦截、不做内容脱敏、不做导出加密**。`SKILL.md` 同步补上该条款。
- 新增 `references/security.md` **§八 已知残余风险**（`import` / `restore` / `archive` 目前只有 `--execute` 而无交互确认门、导出为明文、目录权限未收敛、备份无签名），未缓解项一律如实列出，不再以「已防护」措辞掩盖。
- 子进程口径精确化：`self-test` 确需调用自身 CLI（**参数列表形式、不经 shell**，共 1 处），文档不再笼统声称「0 处子进程」。
### 代码质量
- **圈复杂度回补**：安全加固把 `restore_backup`(CC 14) / `archive_old_memory`(12) / `cache_clean`(12) / `import_memories`(11) / `_handle_dedup`(11) / `dedup_memory`(11) 推过 CC=10。而 CC>10 计入代码质量 P1 桶，**P1 > 5 会触发 8.0 封顶** —— 6 > 5，必须消除。以纯「提取函数」方式拆出 `_import_members` / `_restore_pair` / `_restore_one_file` / `_collect_cache_targets` / `_cache_clean_confirmed` / `_resolve_archive_dir` / `_archive_one_file` / `_record_archive_usage` / `_dedup_group_duplicates` / `_dedup_execute` / `_record_dedup_usage` / `_print_dedup_groups` / `_dedup_run_delete`，**对外行为逐字不变**。实测 **CC>10 = 0 · 嵌套>4 = 0 · 文件>800 行 = 0**（项目权威扫描器 `complexity_scan.py` 口径；安全评估的实测值与 `references/security.md` 表格均未受影响）。
- `archive` 归档失败不再静默：除 `failed_count` 计数外补一条 `non-fatal` 日志，失败原因可查。

### 测试
- 新增 `tests/test_security_doc_claims.py`（4 用例）与 `tests/test_dependency_manifest.py`（3 用例）。
- 新增行为级复验脚本覆盖：首段 `..` 拒绝、20MB 单文件拒绝落盘、篡改备份被 `skipped`、非法清单 key 被拒、四类破坏性操作均建快照、`dedup` 真实删除、`cache_clean` 非 TTY 不崩栈。
- 全量 pytest **124 → 131 passed**。

## [4.0.1] - 2026-09-14
### 新增
- `govern`(gv)：写入治理审计（重复行 / 空行洪水 / 分隔线堆砌 / 超大文件 / 陈旧），`--execute` 只执行幂等折叠，落盘前自动建快照。
- `snapshot`(snap)：记忆快照创建 / 列出 / 回滚，最多保留 5 个；只覆盖同名文件，绝不因回滚误删。
- `compact`(cp)：自适应压实，按「体积 × 陈旧度」挑候选压回预算内；默认预览，`--execute` 才落盘。
- `dashboard`(dash)：省 Token 看板（总量 / 预算占用 / 可省空间 / 下一步）。
- `health`(hlt)：一键体检，五维（可见性 / 新鲜度 / 去重度 / 体积 / 预算）0-100 分 + 优先修复清单。
### 变更
- 压实优先级与相关性排序统一复用 `recency_factor`（时效衰减）。
- Bridge API +5：`govern` / `snapshot` / `compact` / `dashboard` / `health`。
- i18n 每语言 270 → 412 键（zh/en 严格等量）。
### 测试
- 新增 `tests/test_i18n_contract.py`（47 用例）：防漂移契约——en 模式 35 命令 × (text, json) 及 `--help` 输出零 CJK / 零全角字符；`--lang=en` 等号写法；zh 标签保留；最低 Python 版本三处一致且覆盖 `VERSION_SENSITIVE` API；i18n 键集等量、引用键已定义、动态拼接族与变量间接键存在性、死键白名单精确匹配，并由运行期探针断言「被调用的键都已定义」；审计工具与契约基线同口径。
- 全量 pytest **77 → 124 passed**。
### 修复
- 兼容性声明修正：文档曾称 Python 3.8+，但代码使用了 Python 3.9 才有的 `Path.is_relative_to()`；现统一声明 **Python 3.9+**（SKILL.md / skillhub.json / sbom.json 三处一致）。
- en 模式输出彻底本地化：此前 doctor / dedup / rank / throttle / token-check / token-trends / summarize / prompt-list / cache-clean / archive / load / config / clean / auto-clean / import / export / prompt-* / backup 等命令存在硬编码中文，en 用户看到中英混杂；现全部接入 i18n，**en 模式运行输出 0 中文（含 `--help`）**。
- `--help` 支持语言切换：`--lang` 改为在构建参数解析器之前预扫，`--help` / 用法文本随语言本地化。
- 接线此前 139 个「已定义但从未引用」的 i18n 键中的 38 个（doctor 诊断项、报告标签、缓存/调度文案等），并补齐缺失键。
- **i18n 死键彻底治理：静态死键 139 → 101 → 4**。新增运行期探针 `tools/i18n_runtime_probe.py`，实测全部子命令 × (text, json)、`--help` 与 TTY 交互分支（伪造 `isatty=True` + `input()`）后，把「静态扫描看不见但运行期确实命中」的 4 个变量间接引用键（`dash_next` / `hlth_actions` / `selector_plan_line` / `selector_applied_line`）固化为白名单；其余 97 个经**静态扫描 + 非 TTY 运行期 + TTY 运行期 + 动态调用点枚举 + 间接引用排查**五重确认无任何引用后删除（i18n 键集 509 → 412）。删除前原文已归档，操作可逆。
- `dedup --execute` 不再「先删后问」：原实现在用户确认之前就已删除文件，拒答也挽不回；现改为先只读扫描、确认通过后才真正删除。
- **打包改为白名单制**：`repackage_*.py` 从「黑名单排除」改为「白名单收录 + 构建源出现未归类文件即硬失败」。此前黑名单不认识陌生文件，会让它在 `dev=0 personal=0` 校验全部通过的情况下静默进包。
- 修复 `tools/i18n_runtime_probe.py` 的工作目录污染：第三个位置参数对 `export` 而言**就是输出 ZIP 路径**，原写死相对路径 `"AI"`，会把记忆归档写进构建源并被误打包；现改用临时目录内路径，并新增「工作目录污染」检测——探测过程一旦在 CWD 产生新文件即返回 rc=1。
- `config` 命令的默认分类关键词（push / personal_work）按界面语言生成，en 用户默认英文关键词。
- 移除 `safe_file_read` 中一处 `if ...: pass` 空分支死代码。
- 开发工具 `tools/i18n_audit.py` 的 `main` 圈复杂度 14 → ≤10（拆为 `_build_arg_parser` / `load_i18n` / `collect_errors` / `report`，现最大值 9），且该工具**不再随发布包分发**（dev 制品清零）。
- 修正 `tools/i18n_audit.py` 的检测口径缺陷：此前不展开 `_("dim_" + x)` 形式的**前缀拼接族**，把 4 族 16 个键误判为死键（报 117），与契约测试的 101 不一致，导致该工具在健康仓库上恒返回 rc=1、无法用作 CI 闸门。现按「定义中同前缀键」整体计入已用，并新增 `--unused-baseline`（默认与契约基线同源）替代「要求死键为 0」的不可达标准；`--strict` 现返回 rc=0。


## [3.10.0] - 2026-09-13

主题：**上下文工程——选择器可见性 + 陈旧治理**（把「省 Token」落到真实杠杆上）

- **设计前提（三级核实）**：官方文档 + 架构资料 + 运行日志共同确认，平台内置 `memorySelector`
  （lite 模型、0 工具，描述 "Select relevant memories for the current query."），配合设置项
  `memory.relevanceSelection`（默认开启）每次查询**最多挑选 5 条**记忆注入上下文，依据是
  「**文件名 + 描述**」；平台**不提供**干预记忆注入的钩子（Hooks 仅生命周期事件）。因此技能无法
  做「拦截器」，正确形态是**候选池质量放大器**——这也是本版两件套的设计依据。（证据见
  `references/context-engineering.md`）
- **新增 `selector-audit`（sel/sa）**：只读审计候选池——逐文件的描述就绪度（0-100）、
  5 槽位压力（`candidate_count / 5` → ok/elevated/severe）、陈旧分级（fresh/aging/stale）、
  可回收 token 估算，并输出 issues + recommendations。
- **新增 `describe`（desc）**：为缺少 front-matter `description` 的记忆自动提炼一句话描述并写入
  front-matter。默认 **dry-run 预览**，`--execute` 才写入；**幂等**（已有 `description` 一律跳过）、
  **不破坏原有 front-matter 字段**、**只补不删**、原子写（tmp + os.replace）。
- **`load` 新增 `--top-k K`**：语义更直观的 top-k 出口（等价 `--limit`），配合 `--query` 即
  「只加载最相关的 K 条」。
- **相关性加载加入时效衰减（L3）**：`load --query` 的排序分乘以时效因子（半衰期 90 天，下限 0.35），
  陈旧记忆自然降权，避免旧内容挤占相关性 top。
- **`load --json` 结构化字段补全**：输出含 `relevance_used` / `compacted` / `total_tokens_estimate`
  / 每条 `load_mode` 与 `token_estimate`，便于工作流直接消费。
- **新模块 `core_selector.py`**（零外部依赖）：description 提炼、文件名语义判定、时效衰减因子、
  就绪度评分、候选池指标与问题推导、审计与描述补写；全部函数圈复杂度 ≤10。
- **Bridge API 新增**：`MemoryManager.selector_audit(stale_days=30)` 与
  `MemoryManager.describe_memories(dry_run=True, stale_days=30)`。
- **i18n**：新增 28 个中英双语键（每语言 242 → **270**），zh/en 键集严格等量。
- **self-test 加固**：`cli_json_smoke` 覆盖扩至 `analyze` / `rank` / `doctor` / `dedup` /
  `selector-audit` / `describe` / `backup --json`。
- **测试**：新增 `tests/test_selector.py`（18 用例，覆盖纯函数 / 审计 / 写入 / 幂等 / 边界）；
  全量 pytest **58 passed**。
- **规模**：28 子命令 / 27 别名 / 21 Bridge 方法。

## [3.9.1] - 2026-09-13

- **修复 `analyze` 崩溃（P0）**：`core.py` 中 `entry, _, folder = _analyze_file_entry(...)` 的 `_` 遮蔽了 i18n 翻译函数 `_`，导致 memory 目录缺失/为空或条目超限时 `analyze` 抛 `UnboundLocalError`。已改为 `_ign`；无 memory 目录时 `analyze --json` 现返回结构化 error JSON（rc=0），不再崩溃。
- **修复 `--json` 静默空输出（P1-1）**：`cli_handlers.py` 的 `doctor` / `dedup` / `rank`(display) / `backup` 四处在 `--json` 分支仅 `return <dict>`，而 `main()` 不打印返回值 → 静默空。统一改为 `_emit(args, res)` 后返回。
- **修复退出码与 stderr 污染（底层）**：`main()` 返回处理器字典时，`__main__` 的 `sys.exit(dict)` 会以 rc=1 退出并把字典打到 stderr。现归一化——非 int 返回值按成功（0）处理。
- **修正文档漂移（P2-1）**：`SKILL.md` 的 `export` / `import` 示例由 `--output` / `--file` 改为与真实 CLI 一致的位置参数 `export <workspace> <output>` / `import <workspace> <input>`。
- **self-test 加固**：新增 `cli_json_smoke` 检查（子进程运行 `analyze` / `rank` / `doctor` / `dedup` / `backup --json`，断言输出为非空合法 JSON，并验证无 memory 目录时 `analyze` 返回 error 而不崩）。self-test 现 **5/5 通过**。

## [3.9.0] - 2026-08-02

- **复杂度冲刺收尾（冲 9.5）**：AST 全函数（含类方法）扫描实测 **CC>10 = 1 · 嵌套>4 = 1 · 文件>800 行 = 0**；代码质量 HARD P1 = 2 ≤ 5，未触发「P1>5 → 8.0 封顶」；评估系统复评 **9.4 / 10**（Ready to publish）。余 1 处 CC>10：`tools/i18n_audit.py:main`(12)；1 处嵌套>4：`memory_manager/clean.py:_scan_recursive_collect`(5)，建议后续拆分。
- **定时自动化安全护栏**：SKILL.md `# 定时自动化` 节新增无人确认风险护栏——每周缓存清理默认以**预览**（`cache-clean`，不带 `--execute`）排定，仅当用户明确要求才排 `--execute`（opt-in）；定性为周期性归档（`.md.gz` 可恢复），但相关性/老化判定为本地零依赖启发式（非真语义），可能静默误归档，符合评估系统安全边界。
- **修复 `clean.py` silent-except**：`_collect_empty_dir` 的 `except (OSError, PermissionError): pass` 改为 `logger.warning("non-fatal: %s", e)`，repackage 供应链自检 `silent-except = 0`。
- **修复 `test_auto_compact` 回归**：`_load_memory_file` 重构时从 `core.py` 迁到 `core_load.py`，测试 monkeypatch 靶标同步改为 `core_load._load_memory_file`；`pytest tests/` **40 passed**、self-test 4/4。
- **frontmatter 合规**：收敛为 `name` + `description`（符合 SkillHub 规范，通过 skill-creator quick_validate）；许可证/兼容/分类/标签信息移至 `skillhub.json` 与正文。
- **供应链**：内置 `sbom.json` + `self-test` 4/4（Prompt 注入按数据处理、路径穿越五层防御）；零网络外发、零构建/安装步骤。
- **打包**：zip 29 文件 / skill 25 文件，已排除 `__pycache__` / `*.pyc` / `tests` / `.github` / `.pytest_cache` / `.workbuddy`（platform-safe）。

## [3.8.0] - 2026-08-01

- 拆分 `cli.py` → `cli_commands` + `cli_handlers`、`core.py` → `core_search` + `core_rank` + `core_load`（单文件长度达标）。
- tiktoken 真实分词计量、按任务相关性加载（`--query`/`--tags`：零依赖 CJK 字符 bigram + 关键词/标签）、超预算自动压实硬预算闸。
- 三色预算告警（🟢🟡🔔）+ 近 7 日均值、throttle 节流阀、`--json` 程序化输出、24 条短别名。
- 修复 `import_memories` UnboundLocalError、`rank_memory(use_cache=False)` 误写缓存。

## [3.6.0] - 2026-07

- 相关性/标签/文件夹搜索、重要性分级、并行摘要、去重、归档、缓存清理（默认预览、`--execute` 才真删）。
- 破坏性命令 `--force` 自动化友好；ZIP-Slip 五层防御。
