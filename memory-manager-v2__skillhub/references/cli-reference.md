# CLI 命令完整参考

> 本文件由 `memory_manager/_build_parser()` **实测生成**（2026-09-13），与代码零漂移。
> 约定：`<workspace>` 指工作空间路径（即包含 `.workbuddy/memory/` 的目录）。

**共 33 条子命令 + 32 条短别名。**

## 快速索引

| 命令 | 别名 | 说明 |
|------|------|------|
| `analyze` | stat | 分析记忆存储 |
| `archive` | ar | 归档旧记忆 |
| `auto-clean` | aclean | 差异清理 |
| `backup` | bk | 备份/恢复 |
| `cache-clean` | cclean | 清理缓存 |
| `cache-reminder` | crm | 缓存提醒 |
| `clean` | rm | 清理工作空间 |
| `compact` | cp | 自适应压实：按预算压掉大且旧的记忆 |
| `config` | cfg | 配置管理 |
| `dashboard` | dash | 省 Token 看板 |
| `dedup` | dd | 基于内容哈希去重 |
| `describe` | desc | 为记忆补写 front-matter description（提升选择器可见性） |
| `doctor` | doc | 诊断工具 - 检测配置异常和潜在问题 |
| `export` | exp | 导出记忆 |
| `govern` | gv | 写入治理审计（重复/空行/超长/陈旧） |
| `health` | hlt | 一键记忆体检（五维评分） |
| `import` | imp | 导入记忆 |
| `load` | get | 加载记忆 |
| `prompt-get` | pg | 获取Prompt模板内容 |
| `prompt-list` | pl | 列出Prompt模板 |
| `prompt-save` | ps | 保存Prompt模板 |
| `prompt-search` | psearch | 搜索Prompt模板 |
| `rank` | top | 记忆分级 |
| `report` | rep | 生成报告 |
| `scan` | — | 扫描工作空间 |
| `search` | find | 搜索记忆 |
| `selector-audit` | sa, sel | 审计平台记忆选择器可见性（描述就绪度/槽位压力/陈旧度） |
| `self-test` | — | 内置自检：模块完整性/滥用防护/核心命令冒烟 |
| `snapshot` | snap | 记忆快照：创建/列出/回滚 |
| `summarize` | sum | 生成摘要 |
| `throttle` | thr | 节流阀：压预算内精简记忆并报告 |
| `token-check` | tc | Token预算检查 |
| `token-trends` | tt | Token使用趋势(按日/周/月) |

## 命令详解

### analyze（别名 stat）
分析记忆存储

```bash
memory_manager.py analyze <workspace> --json
```
位置参数：`workspace`
选项：
- `--json` — JSON格式输出

### archive（别名 ar）
归档旧记忆

```bash
memory_manager.py archive <workspace> --json --days N --execute
```
位置参数：`workspace`
选项：
- `--json` — JSON格式输出
- `--days N`
- `--execute`

### auto-clean（别名 aclean）
差异清理

```bash
memory_manager.py auto-clean <workspace> --json --filter {push|personal_work|other|all} --execute
```
位置参数：`workspace`
选项：
- `--json` — JSON格式输出
- `--filter {push|personal_work|other|all}`
- `--execute`

### backup（别名 bk）
备份/恢复

```bash
memory_manager.py backup <workspace> --json --path VALUE --execute --restore
```
位置参数：`workspace`
选项：
- `--json` — JSON格式输出
- `--path VALUE` — 备份目录
- `--execute` — 执行备份
- `--restore` — 从备份恢复

### cache-clean（别名 cclean）
清理缓存

```bash
memory_manager.py cache-clean <workspace> --json --execute
```
位置参数：`workspace`
选项：
- `--json` — JSON格式输出
- `--execute`

### cache-reminder（别名 crm）
缓存提醒

```bash
memory_manager.py cache-reminder <workspace> --json
```
位置参数：`workspace`
选项：
- `--json` — JSON格式输出

### clean（别名 rm）
清理工作空间

```bash
memory_manager.py clean <workspace> --json --execute --force
```
位置参数：`workspace`
选项：
- `--json` — JSON格式输出
- `--execute`
- `--force` — 跳过交互确认（自动化/脚本调用）

### compact（别名 cp）
自适应压实：按预算压掉大且旧的记忆

```bash
memory_manager.py compact <workspace> --json --execute --budget N
```
位置参数：`workspace`
选项：
- `--json` — JSON格式输出
- `--execute` — 实际压实（默认仅预览）
- `--budget N` — 目标 token 预算（默认取全局预算）

### config（别名 cfg）
配置管理

```bash
memory_manager.py config <workspace> --json --set-key VALUE --set-value VALUE
```
位置参数：`workspace`
选项：
- `--json` — JSON格式输出
- `--set-key VALUE`
- `--set-value VALUE`

### dashboard（别名 dash）
省 Token 看板

```bash
memory_manager.py dashboard <workspace> --json --stale-days N
```
位置参数：`workspace`
选项：
- `--json` — JSON格式输出
- `--stale-days N` — 陈旧判定阈值（天，默认30）

### dedup（别名 dd）
基于内容哈希去重

```bash
memory_manager.py dedup <workspace> --json --execute
```
位置参数：`workspace`
选项：
- `--json` — JSON格式输出
- `--execute` — 执行去重

### describe（别名 desc）
为记忆补写 front-matter description（提升选择器可见性）

```bash
memory_manager.py describe <workspace> --json --execute --stale-days N
```
位置参数：`workspace`
选项：
- `--json` — JSON格式输出
- `--execute` — 实际写入（默认仅预览）
- `--stale-days N` — 陈旧判定阈值（天，默认30）

### doctor（别名 doc）
诊断工具 - 检测配置异常和潜在问题

```bash
memory_manager.py doctor <workspace> --json
```
位置参数：`workspace`
选项：
- `--json` — JSON格式输出

### export（别名 exp）
导出记忆

```bash
memory_manager.py export <workspace> <output> --json
```
位置参数：`workspace`、`output`
选项：
- `--json` — JSON格式输出

### govern（别名 gv）
写入治理审计（重复/空行/超长/陈旧）

```bash
memory_manager.py govern <workspace> --json --execute --stale-days N
```
位置参数：`workspace`
选项：
- `--json` — JSON格式输出
- `--execute` — 执行安全折叠（默认仅预览）
- `--stale-days N` — 陈旧判定阈值（天，默认30）

### health（别名 hlt）
一键记忆体检（五维评分）

```bash
memory_manager.py health <workspace> --json --stale-days N
```
位置参数：`workspace`
选项：
- `--json` — JSON格式输出
- `--stale-days N` — 陈旧判定阈值（天，默认30）

### import（别名 imp）
导入记忆

```bash
memory_manager.py import <workspace> <input> --json
```
位置参数：`workspace`、`input`
选项：
- `--json` — JSON格式输出

### load（别名 get）
加载记忆

```bash
memory_manager.py load <workspace> --json --mode {brief|normal|full} --limit N --top-k N --days N --query VALUE --tags VALUE --no-compact
```
位置参数：`workspace`
选项：
- `--json` — JSON格式输出
- `--mode {brief|normal|full}`
- `--limit N` — 最多加载文件数（>=1）
- `--top-k N` — 只保留相关性最高的 K 条（等价 --limit，语义更直观）
- `--days N` — 只加载N天内的记忆
- `--query VALUE` — 按任务相关性加载（关键词，零依赖语义检索）
- `--tags VALUE` — 按标签过滤（逗号分隔）
- `--no-compact` — 禁用超预算自动压实

### prompt-get（别名 pg）
获取Prompt模板内容

```bash
memory_manager.py prompt-get <name> <workspace> --json
```
位置参数：`name`、`workspace`
选项：
- `--json` — JSON格式输出

### prompt-list（别名 pl）
列出Prompt模板

```bash
memory_manager.py prompt-list <workspace> --json --tag VALUE
```
位置参数：`workspace`
选项：
- `--json` — JSON格式输出
- `--tag VALUE` — 按标签过滤

### prompt-save（别名 ps）
保存Prompt模板

```bash
memory_manager.py prompt-save <name> <workspace> --json --content VALUE --tags VALUE --description VALUE --category VALUE
```
位置参数：`name`、`workspace`
选项：
- `--json` — JSON格式输出
- `--content VALUE` — Prompt内容
- `--tags VALUE` — 标签（逗号分隔）
- `--description VALUE` — 描述
- `--category VALUE` — 分类/子目录

### prompt-search（别名 psearch）
搜索Prompt模板

```bash
memory_manager.py prompt-search <workspace> --json --keyword VALUE --tag VALUE
```
位置参数：`workspace`
选项：
- `--json` — JSON格式输出
- `--keyword VALUE` — 关键词
- `--tag VALUE` — 按标签过滤

### rank（别名 top）
记忆分级

```bash
memory_manager.py rank <workspace> --json --days N
```
位置参数：`workspace`
选项：
- `--json` — JSON格式输出
- `--days N` — 只分析N天内的文件

### report（别名 rep）
生成报告

```bash
memory_manager.py report <workspace> --json
```
位置参数：`workspace`
选项：
- `--json` — JSON格式输出

### scan
扫描工作空间

```bash
memory_manager.py scan <workspace> --json
```
位置参数：`workspace`
选项：
- `--json` — JSON格式输出

### search（别名 find）
搜索记忆

```bash
memory_manager.py search <keyword> <workspace> --json --tag VALUE --folder VALUE
```
位置参数：`keyword`、`workspace`
选项：
- `--json` — JSON格式输出
- `--tag VALUE` — 按标签过滤
- `--folder VALUE` — 按子目录过滤

### selector-audit（别名 sa, sel）
审计平台记忆选择器可见性（描述就绪度/槽位压力/陈旧度）

```bash
memory_manager.py selector-audit <workspace> --json --stale-days N
```
位置参数：`workspace`
选项：
- `--json` — JSON格式输出
- `--stale-days N` — 陈旧判定阈值（天，默认30）

### self-test
内置自检：模块完整性/滥用防护/核心命令冒烟

```bash
memory_manager.py self-test
```

### snapshot（别名 snap）
记忆快照：创建/列出/回滚

```bash
memory_manager.py snapshot <workspace> --json --list --restore --name VALUE --label VALUE --execute
```
位置参数：`workspace`
选项：
- `--json` — JSON格式输出
- `--list` — 列出已有快照
- `--restore` — 从快照还原（需 --execute）
- `--name VALUE` — 快照名（还原时指定，默认最新）
- `--label VALUE` — 创建时的快照标签
- `--execute` — 确认执行还原

### summarize（别名 sum）
生成摘要

```bash
memory_manager.py summarize <workspace> --json
```
位置参数：`workspace`
选项：
- `--json` — JSON格式输出

### throttle（别名 thr）
节流阀：压预算内精简记忆并报告

```bash
memory_manager.py throttle <workspace> --days N --no-compact --json
```
位置参数：`workspace`
选项：
- `--days N` — 只纳入N天内的记忆
- `--no-compact` — 仅诊断不压实
- `--json` — JSON格式输出

### token-check（别名 tc）
Token预算检查

```bash
memory_manager.py token-check <workspace> --json
```
位置参数：`workspace`
选项：
- `--json` — JSON格式输出

### token-trends（别名 tt）
Token使用趋势(按日/周/月)

```bash
memory_manager.py token-trends <workspace> --period {daily|week|month} --days N --json
```
位置参数：`workspace`
选项：
- `--period {daily|week|month}` — 聚合周期: daily/week/month
- `--days N` — 回溯天数
- `--json` — JSON格式输出

## 全局选项

```bash
memory_manager.py --lang zh|en <command> ...   # 界面语言（默认 zh）
memory_manager.py --version                     # 版本号
```

## JSON 输出

`--json` 输出的是**各命令自身的结构化字典**，不做统一信封包装；不同命令字段不同。实测字段示例：

```json
// analyze --json     → ['version', 'workspace', 'timestamp', 'files', 'stats', 'recommendations', 'warnings']
// token-check --json → ['today', 'today_tokens', 'budget', 'ratio', 'level', 'emoji', 'message', 'note']
```

## 意图识别决策树

```
输入包含"记忆"或"memory"?
├── 是 → 包含动作词?
│   ├── 查看/列表/清单/报告 → report 或 analyze
│   ├── 搜索/查找 + 关键词 → search <keyword> <workspace>
│   ├── 加载/读取 → load <workspace> (--days / --mode 可选)
│   ├── 清理/删除/归档 → auto-clean / cache-clean / dedup (需 --execute 确认)
│   ├── 摘要/总结 → summarize
│   ├── 备份/恢复 → backup <workspace> (恢复加 --restore)；导出 → export；导入 → import
│   ├── 分析/状态/诊断 → analyze / doctor
│   └── 分级/排名/排序 → rank
├── 否 → 包含 Token/token?
│   ├── 统计/检查/预警/预算 → token-check
│   ├── 趋势/统计图表/周月 → token-trends
│   └── 省/节省/优化 + Token → summarize + token-check 组合
├── 否 → 包含 缓存/cache?
│   ├── 提醒 → cache-reminder (含内置 Token 预警)
│   └── 清理 → cache-clean (默认预览模式)
├── 否 → 包含 选择器/可见性/描述/陈旧?
│   ├── 体检/为什么这条没被选中 → selector-audit（只读）
│   ├── 补描述/写描述 → describe（加 --execute 生效）
│   └── 陈旧/过期/该归档 → selector-audit --stale-days N，再 archive
├── 否 → 包含 治理/快照/回滚/压实/看板/体检?
│   ├── 体检/打分/整体健康 → health（只读，五维 0-100）
│   ├── 省多少/看板/收益 → dashboard（只读）
│   ├── 写乱了/冗余/折叠 → govern（默认预览，--execute 才落盘并自动建快照）
│   ├── 太大/压到预算内 → compact --budget N（默认预览）
│   ├── 建快照 → snapshot --label X；列出 → snapshot --list
│   └── 回滚 → snapshot --restore --execute（只覆盖同名文件）
└── 否 → "记忆管家"(品牌词) → analyze (默认全量分析)
```
