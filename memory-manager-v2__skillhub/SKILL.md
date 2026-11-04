---
name: memory-manager-v2
description: 管理 .workbuddy/memory/ 的记忆治理与 Token 节流工具：提供写入审计、快照回滚、自适应压实、Token 看板与五维体检，写入型命令带确认门并自动建快照。当要治理项目记忆、压缩上下文、回滚记忆改动时用。
---

# 记忆管家 Memory Manager V4.0.4（AI 记忆加速器 / Token 节流阀）

**许可证**：MIT · **兼容**：Python 3.9+（纯标准库；可选 colorama / jieba / tiktoken，缺失时自动回退，功能不受影响）

**定位：AI 加速器——让进上下文的记忆更小、更准、更省 Token。**
**三大目标：更懂你 · 更快回应 · 更省Token**

> 每一次会话都会把 `.workbuddy/memory` 读进上下文；文件越大 → 加载 token 越多 → 越贵越慢。
> 因此「省 Token」= 让进上下文的记忆更小更准。本技能即围绕节流阀定位设计。
>
> **V3.10 新增事实依据**（2026-09 三级核实：官方文档 + 架构资料 + 运行日志）：平台已内置
> `memorySelector`（lite 模型、0 工具，描述 "Select relevant memories for the current query."），
> 配合设置项 `memory.relevanceSelection`（默认开启），每次查询最多挑选 **5 条**记忆注入上下文，
> 挑选依据是「**文件名 + 描述**」。平台**不提供**干预记忆注入的钩子（Hooks 仅生命周期事件）。
> 因此本技能对 Token 的真实杠杆是**候选池质量**：把描述写清楚（`describe`）+ 把候选池压小压新
> （`selector-audit` 定位 + `archive` 归档）——平台自带的 5 槽选择器就会选得更准、注入更少。
>
> **V4.0.1 新增事实依据**：光「看得见」还不够——记忆是会被**写坏**的（重复行堆积、空行洪水、
> 分隔线堆砌、单文件无限膨胀），而写坏之后只能靠人肉眼排查。治理闭环因此成立：
> `govern` 审计并**只做幂等折叠**、`compact` 按「体积 × 陈旧度」压回预算、`dashboard` 量化
> 可省空间、`health` 五维打分给优先修复顺序；**任何落盘动作前自动建快照**（`snapshot`，
> 最多保留 5 个），误操作可 `snapshot --restore --execute` 一键还原。
>
> **V4.0.3 新增事实依据**：前两版的加固都集中在「读入的输入」（ZIP / 备份清单），
> 却漏了「写出的动作」—— `import` / `archive` / `backup --restore` / `snapshot --restore`
> 四个写入型命令**没有任何交互确认**，非 TTY 脚本一调就直接改记忆目录。
> 同时「备份完整性」长期只有内部 `hash` 字段却没有可外部验证的依据，
> 「目录权限」则完全依赖系统 umask。V4.0.3 把这三件事补上：
> 确认门（**6 个调用点**，非 TTY 直接拒绝；`--json` 下返回结构化拒绝而不打印提示）、
> **整文件** sha256 的 `SHA256SUMS` 清单 + `--verify` 只读校验、
> 以及 `harden` 权限收敛（POSIX 0700·0600；Windows 明确报「不适用」而非假装完成）。
> ⚠️ 校验和清单**不是签名** —— 能发现意外损坏与「只改文件不改清单」的篡改，
> 但挡不住能同时改写二者的攻击者；`references/security.md` §五 如实写明，不做「已防篡改」的表述。

---

# 触发词（Trigger Words）

## 一级触发词（直接激活）

| 触发词 | 命令 | 场景 |
|:--|:--|:--|
| `记忆管家` | analyze | "打开记忆管家" |
| `缓存提醒` / `缓存清理提醒` | cache-reminder | "有没有缓存要清理" |
| `Token检查` / `token-check` | token-check | "查一下Token用量" |
| `记忆分析` / `看看记忆状态` | analyze | "分析一下记忆文件" |

## 二级触发词（上下文激活）

| 触发词 | 命令 | 场景 |
|:--|:--|:--|
| `清理缓存` / `缓存清理` | cache-clean | "清理一下缓存" |
| `记忆清单` / `记忆报告` | report | "列出所有记忆" |
| `记忆搜索` + [关键词] | search [关键词] <workspace> | "搜索记忆中的xxx" |
| `搜索标签` + [标签名] | search [关键词] --tag [标签] <workspace> | "搜索带xxx标签的记忆（关键词必填）" |
| `搜索文件夹` + [项目名] | search [关键词] --folder [项目] <workspace> | "搜索xxx项目下的记忆（关键词必填）" |
| `智能加载` / `加载记忆` | load --days N | "加载最近7天的记忆" |
| `选择器审计` / `记忆可见性` | selector-audit | "为什么这条记忆没被选中/读不到" |
| `写入治理` / `记忆治理` / `折叠冗余` | govern | "记忆写得太乱，帮我治理一下" |
| `记忆快照` / `建个快照` | snapshot --label 变更说明 | "改动前给记忆做个快照" |
| `回滚记忆` / `恢复快照` | snapshot --restore --execute | "把记忆回滚到上一个快照" |
| `压实记忆` / `压到预算内` | compact --budget 2000 | "把记忆压到预算内" |
| `省Token看板` / `能省多少` | dashboard | "看看还能省多少 Token" |
| `记忆体检` / `打个分` | health | "给记忆做个整体体检" |
| `补描述` / `写描述` / `记忆描述` | describe | "给记忆补上描述" |
| `陈旧记忆` / `过期记忆` / `该归档了` | selector-audit --stale-days N | "有哪些过期记忆该清理" |
| `只加载最相关的K条` | load --top-k K --query [主题] | "只加载最相关的3条记忆" |
| `备份记忆` / `导出记忆` | export | "备份我的记忆" |
| `恢复记忆` / `导入记忆` | import | "恢复之前的记忆" |
| `去重` / `删除重复记忆` | dedup | "记忆有重复吗" |

## 三级触发词（明确请求时激活）

| 触发词 | 命令 | 场景 |
|:--|:--|:--|
| `诊断` / `健康检查` | doctor | "诊断记忆系统" |
| `自动清理` / `差异化清理` | auto-clean | "自动清理旧记忆" |
| `Token趋势` / `Token统计` | token-trends | "看看Token周趋势" |
| `Prompt模板` / `提示词` | prompt-list | "列出Prompt模板" |
| `保存Prompt` | prompt-save | "保存一个提示词模板" |
| `搜索Prompt` | prompt-search | "搜索提示词" |
| `记忆分级` / `重要性排名` | rank | "按重要性给记忆排序" |
| `切换语言` / `英文版` | --lang en | "切换到英文" |
| `节流阀` / `压预算` | throttle | "把记忆压到预算内再注入" |
| `相关性加载` + [主题] | load --query [主题] | "只加载和xx相关的记忆" |
| `强制清理` | clean --execute --force | "脚本里直接清理缓存" |
| `权限收敛` / `目录权限` | harden [--execute] | "把记忆目录权限收紧" |
| `完整性校验` / `备份校验` | snapshot --verify / backup --verify | "备份有没有被改过" |

## 排除规则

- 纯文件管理（不涉及 .workbuddy/memory）→ 通用文件工具
- 代码调试/重构 → 代码 Skill
- 系统级磁盘清理 → 系统工具
- "导出"/"导入" 不带"记忆"修饰词 → 不触发

---

# 安全门禁规则

| 操作类型 | 默认行为 | 覆盖方式 |
|:--|:--|:--|
| **只读** (analyze/report/search/load/rank/token-check/doctor/cache-reminder/summarize/token-trends/selector-audit/dashboard/health) | 直接执行 | — |
| **预览** (auto-clean/cache-clean/dedup/scan/govern/compact) | 默认 dry-run | `--execute` 才落盘（落盘前**自动建快照**） |
| **写入型** (import/archive/restore/clean/snapshot --restore) | 需交互式二次确认；**非 TTY 直接拒绝** | `--force` 显式跳过（脚本/自动化）；其中 `archive`/`restore`/`clean`/`snapshot --restore` 另需 `--execute` |
| **机器可读** (上述任一 + `--json`) | 不打印人类提示，直接返回 `{"status":"cancelled"}` | 唯一放行方式是 `--force` |
| **快照** (snapshot) | 创建/列出只读 | 仅 `--restore --execute` 覆盖同名文件，**绝不因回滚删文件** |
| **配置** (config) | 交互式引导 | 逐步确认 |

---

# 命令速查

```bash
# 基础（<workspace> 为必填参数，可用 . 表示当前目录）
memory_manager.py analyze <workspace>                  # 分析记忆状态
memory_manager.py search 关键词 <workspace>            # 搜索记忆
memory_manager.py load --days 7 <workspace>            # 加载最近7天记忆

# Token
memory_manager.py token-check <workspace>              # Token消费 vs 预算
memory_manager.py token-trends <workspace>             # Token使用趋势
memory_manager.py token-trends --period month <workspace>  # 按月统计

# 缓存与清理
memory_manager.py cache-reminder <workspace>           # 缓存提醒
memory_manager.py cache-clean <workspace>              # 缓存清理（默认预览）
memory_manager.py cache-clean --execute <workspace>    # 执行清理（含前后对比）
memory_manager.py auto-clean <workspace>               # 差异化自动清理
memory_manager.py dedup <workspace>                    # 去重

# 数据安全
memory_manager.py export <workspace> <output>   # 导出
memory_manager.py import <workspace> <input>    # 导入

# 高级
memory_manager.py doctor <workspace>                   # 诊断
memory_manager.py rank <workspace>                     # 分级
memory_manager.py summarize <workspace>                # 摘要
memory_manager.py prompt-list .                        # Prompt模板（. 即 workspace）
memory_manager.py prompt-search . --keyword 审查       # 搜索模板

# V3.9 新能力
memory_manager.py throttle <workspace>                 # 节流阀：压预算内精简记忆并报告
memory_manager.py load --query "Semantic记忆" <workspace>   # 按任务相关性加载（CJK 字符 bigram + 关键词/标签）
memory_manager.py clean --execute --force <workspace>  # 自动化强制清理（跳过TTY确认）
memory_manager.py self-test                            # 内置自检：模块/滥用防护/核心命令冒烟（CI 证据，输出 JSON）

# V4.0.1 治理闭环（默认预览，落盘前自动建快照）
memory_manager.py health <workspace>                   # 一键体检：五维 0-100 分 + 优先修复清单
memory_manager.py dashboard <workspace>                # 省Token看板：总量/预算占用/可省空间/下一步
memory_manager.py govern <workspace>                   # 写入治理审计：重复行/空行洪水/分隔线/超大/陈旧
memory_manager.py govern --execute <workspace>         # 只做幂等折叠（不删内容），落盘前自动建快照
memory_manager.py compact --budget 2000 <workspace>    # 自适应压实：按「体积×陈旧度」压回预算内
memory_manager.py snapshot --label 变更前 <workspace>  # 手动建快照（最多保留 5 个）
memory_manager.py snapshot --list <workspace>          # 列出快照
memory_manager.py snapshot --restore --execute <workspace>  # 回滚到最新快照（只覆盖同名文件）

# V4.0.3 加固（写入型确认门 / 完整性清单 / 权限收敛）
memory_manager.py harden <workspace>                   # 预览敏感目录权限（不落盘）
memory_manager.py harden --execute <workspace>         # 收敛为 目录0700/文件0600（仅 POSIX）
memory_manager.py snapshot --verify <workspace>        # 只读校验最新快照的 SHA256SUMS
memory_manager.py backup --verify <workspace>          # 只读校验备份目录的 SHA256SUMS
memory_manager.py import <workspace> <in.zip> --force  # 跳过确认门（脚本/自动化）
# 任意命令加 --json 即输出结构化 JSON：analyze/search/load/rank/summarize/report/
# token-check/token-trends/throttle/doctor/dedup/archive/auto-clean/export/import/
# config/scan/cache-reminder/cache-clean/clean/prompt-list/prompt-get/prompt-search/
# backup 均支持，便于程序化消费与自动化编排。
```

---

# Token 预警三色灯

- 🟢 **正常** (<70%): Token消费在安全范围
- 🟡 **警告** (≥70%): 接近预算上限
- 🔴 **超支** (≥100%): 超过每日预算
- ⚠️ Token 为「估算」性质：优先 tiktoken 真实分词（GPT-4o 用 o200k，其余 cl100k），离线/未安装时回退 CJK 启发式（中文≈0.6、英文≈4字/token），非实际 API 消耗。

---

# 定时自动化（WorkBuddy Automation）

推荐使用 `automation_update` 工具：

```
# 每天 18:00 缓存提醒
automation_update --mode create --name "记忆管家缓存提醒" \
  --scheduleType recurring --rrule "FREQ=DAILY;BYHOUR=18" \
  --prompt "执行记忆管家的 cache-reminder 命令" --status ACTIVE

# 会话启动自动节流（7.4：宿主支持启动钩子时配置；当前作为手动/脚本入口）
automation_update --mode create --name "记忆管家节流阀" \
  --scheduleType recurring --rrule "FREQ=DAILY;BYHOUR=9" \
  --prompt "执行记忆管家的 throttle 命令，将精简后的记忆注入本次会话上下文" \
  --status ACTIVE

# 每周一 9:00 缓存清理（默认预览，不自动动刀）
automation_update --mode create --name "记忆管家缓存清理(预览)" \
  --scheduleType recurring --rrule "FREQ=WEEKLY;BYDAY=MO;BYHOUR=9" \
  --prompt "执行记忆管家的 cache-clean 命令（预览/dry-run，不删除）" --status ACTIVE

# ⚠️ 仅当你明确要求「自动动刀」时，才启用带 --execute 的版本（周期性破坏性，需主动 opt-in）：
# automation_update --mode create --name "记忆管家缓存清理(自动归档)" \
#   --scheduleType recurring --rrule "FREQ=WEEKLY;BYDAY=MO;BYHOUR=9" \
#   --prompt "执行记忆管家的 cache-clean --execute 命令" --status ACTIVE

> **安全护栏（定时自动化的无人确认风险）**：`cache-clean --execute` 是**周期性破坏性（归档）动作**，一旦排定即在每周一无人工确认下执行。清理仅做归档（`.md.gz`，可恢复），但相关性/老化判定为本地零依赖启发式（关键词/bigram，非真语义），偶发误判可能静默归档你仍需要的记忆。因此：
> - **默认不自动动刀**：每周清理任务以**预览**形态排定（`cache-clean` 不带 `--execute`），由你定期查看报告再决定是否执行；仅当你明确要求时，才排 `--execute` 版本（opt-in）。
> - **throttle 同理**：相关性加载非真语义，定时自动剪枝时你看不到被丢弃内容；建议保留按需调用以保留可见性。
> - **上架审计备注**：评估系统的安全审计通常将「无人确认定时破坏性动作」标为 P1/P2；本技能已将其设为 opt-in（非默认启用），符合安全边界，不会因该条触发封顶。
```

---

# 安全特性

- 符号链接防护 **23 处** + 工作区边界校验 **23 处** + ZIP Slip **4 道拒绝规则 + 1 步路径归一化**
- 单文件读取上限 1MB / ZIP 累计解压上限 50MB / ZIP Bomb 三重预检（单文件 · 条目数 · 总大小）
- **写入型命令一律先问**（**6 个调用点**：`clean` / `dedup` / `import` / `archive` / `backup --restore` / `snapshot --restore`）：需输入「同意」，**非 TTY 直接拒绝**，`--force` 显式跳过；`--json` 下不打印提示、直接返回结构化拒绝
- **完整性清单（V4.0.3）**：快照与备份产物同时写 `SHA256SUMS`（**整文件** sha256，GNU coreutils 格式，可用 `sha256sum -c` 交叉验证）；`snapshot --verify` / `backup --verify` 只读校验，哈希不符 / 文件缺失 / 清单外新增**均判不通过**。⚠️ 校验和清单**不是签名**，不做「已防篡改」承诺
- **权限收敛（V4.0.3）**：`harden` 把记忆 / 快照 / 备份目录收敛为 **目录 0700 / 文件 0600**，默认预览、`--execute` 落盘；**仅 POSIX**，Windows 明确返回「不适用」而非假装完成
- **上架元数据合规（V4.0.4）**：随包 `LICENSE`（MIT 全文，与 `skillhub.json` 的 `license` 声明一致）；`skillhub.json` 补 `homepage`（SkillHub 条目页）——对应平台合规报告 **COMP-1 / COMP-2**
- 受保护目录（memory/）永不删除；`MEMORY.md` 不被自动清理
- 0 处 bare-except / 0 处 eval·exec·`__import__` / 0 处 shell 执行 / 0 处网络外发 / 0 个 HTML 渲染面（子进程仅 1 处：`self-test` 以参数列表调用自身 CLI，不经 shell）
- **可回滚**：`govern` / `compact` / `clean` / `cache-clean` / `dedup` / `archive` 共 **6 处**落盘前自动建快照；`snapshot --restore` 只覆盖同名文件，绝不误删
- **只折叠不删除**：`govern --execute` 仅做幂等折叠（压重复行/空行/分隔线），不丢语义内容
- **信任边界：记忆内容一律视为不可信数据** —— 只被计数 / 排序 / 截断 / 复制 / 删除，绝不作为指令执行；本技能不做注入拦截、不做内容脱敏、不做导出加密（详见 `references/security.md`）
- 上列数字由 `tests/test_security_doc_claims.py` 逐条实测比对；改代码不改文档 → 测试失败

---

# 记忆文件结构

```
.workbuddy/
├── memory/           # 记忆文件（支持子目录）
│   ├── 项目A/        # 按项目/主题组织
│   └── 项目B/
├── .summary/         # 摘要缓存
├── .token_stats/     # Token统计
└── archive/          # 归档（.md.gz）
```

front-matter 标签格式：
```yaml
---
tags: [项目A, 重构, 架构决策]
category: 项目A
---
```

搜索：`search "关键词" --tag 架构决策 --folder 项目A <workspace>`

---

# 故障排查

| 错误 | 原因 | 解决方案 |
|------|------|----------|
| `No module named 'memory_manager'` | 未在正确目录运行 | cd 到技能根目录或 `python -m memory_manager` |
| `PermissionError` | 工作空间无写权限 | 检查 `.workbuddy/` 目录权限 |
| `UnicodeDecodeError` | 记忆文件编码异常 | 确保文件为 UTF-8 |
| Token 数据为空 | 首次使用无历史 | 运行几次操作后数据自动积累 |
| 摘要结果为空 | 文件内容过短 | 短文件自动跳过，无需处理 |

---

# 版本

**V4.0.6 | 中英双语 | 治理闭环（govern / snapshot / compact / dashboard / health / harden）| 每语言 433 / 共 866 i18n keys | 34 子命令 / 33 别名 / 26 Bridge 方法**


> **本地审计订正（2026-10-14）**：本文件原将哈希算法名写作无意义字符串 `SHA256`，与代码 `core_perms.py:41` 的 `hashlib.sha256()` 不一致（清单文件名 `SHA256SUMS` 保持不变，否则与既有快照产物不兼容）。现据代码事实将算法名订正为 `sha256`；该不一致疑似发布方批量字符串替换所致，来源仍需向发布方 indiv-aakook 核实。