# 架构与 Bridge API 文档

## 模块结构

```
memory_manager/
├── __init__.py    # Bridge API (MemoryManager 类，19 方法)
├── cache.py       # 缓存清理 + 前后大小对比
├── clean.py       # 差异化清理 + 归档 + 去重
├── cli.py         # CLI 入口 (17 子命令)
├── config.py      # 配置 + i18n + 前端标签解析 + 文件迭代器
├── core.py       # 核心：analyze/search/load/rank
├── io.py          # 导入/导出/备份/恢复 (ZIP Slip 5层防御)
├── prompt.py      # Prompt 模板管理 (PROMPT_ 前缀)
├── report.py      # 报告生成
├── summarize.py   # 摘要生成
└── token.py       # Token 统计 + 预算 + 趋势聚合
```

## Bridge API (MemoryManager 类)

### 核心方法 (19)

| 方法 | 说明 | 返回 |
|------|------|------|
| `analyze(workspace_path)` | 全量分析 | `{stats, files, recommendations, warnings}` |
| `search(workspace_path, keyword, mode, folder, tag)` | 关键词+标签+文件夹搜索 | `{results, total}` |
| `load(workspace_path, mode, keyword, limit, days, folder)` | 智能加载 | `{content, stats}` |
| `rank(workspace_path, weights, days, folder)` | 重要性分级 | `{rankings, stats}` |
| `summarize(workspace_path)` | 生成摘要 | `{summaries, count}` |
| `report(workspace_path)` | 记忆清单 | `{total_files, ...}` |
| `token_check(workspace_path, budget)` | Token预算检查 | `{used, budget, warning_level, note}` |
| `token_trends(workspace_path, period, days_back)` | Token趋势聚合 | `{daily, aggregated, totals}` |
| `cache_reminder(workspace_path)` | 缓存提醒+Token预警 | `{cache_status, token_status}` |
| `cache_clean(workspace_path, dry_run)` | 缓存清理+前后对比 | `{cleaned/freed_kb, before_kb, after_kb, delta_kb}` |
| `auto_clean(workspace_path, dry_run)` | 差异化自动清理 | `{kept, reminded, cleaned}` |
| `dedup(workspace_path, dry_run)` | 内容去重 | `{duplicates, count}` |
| `scan(workspace_path)` | 工作空间扫描 | `{cache, storage, recommendations}` |
| `export(workspace_path, output_path)` | 导出ZIP | `{exported, path}` |
| `import_data(workspace_path, file_path, mode, confirm)` | 导入ZIP | `{imported, skipped}` |
| `prompt_list(workspace_path, tag)` | Prompt模板列表 | `{prompts, count}` |
| `prompt_get(workspace_path, name)` | 获取Prompt内容 | `{content, metadata}` |
| `prompt_save(workspace_path, name, content, tags, description, category)` | 保存Prompt模板 | `{saved, version}` |
| `prompt_search(workspace_path, keyword, tag)` | 搜索Prompt模板 | `{results, count}` |

### 使用示例

```python
from memory_manager import MemoryManager

mm = MemoryManager()

# 分析记忆状态
result = mm.analyze("/path/to/workspace")

# Token检查
token = mm.token_check("/path/to/workspace", budget=5000)

# 缓存清理（含前后对比）
clean = mm.cache_clean("/path/to/workspace", dry_run=False)
print(f"清理前: {clean['before_kb']}KB → 清理后: {clean['after_kb']}KB (释放 {clean['delta_kb']}KB)")

# Token趋势
trends = mm.token_trends("/path/to/workspace", period="week")

# Prompt管理
mm.prompt_save("/path/to/workspace", "代码审查", "请审查以下代码...", tags=["代码", "审查"])
prompts = mm.prompt_list("/path/to/workspace")
```

## 配置文件

### 全局配置
路径：`~/.workbuddy/skills/memory-manager-v2/config.json`

```json
{
  "lang": "zh",
  "_automation_rules": { ... }
}
```

### 工作空间配置
路径：`{workspace}/.workbuddy/skills/memory-manager-v2/config.json`

```json
{
  "personal_work_content": {
    "retention_days": 7,
    "auto_remind_days": 5
  },
  "push_content": {
    "retention_days": 7
  },
  "daily_token_budget": 5000,
  "backup_path": ""
}
```

值域白名单：
- `retention_days`: 1-365
- `auto_remind_days`: 1-90
- `lang`: zh / en

## Front-matter 标签格式

记忆文件支持 YAML front-matter：

```markdown
---
tags: [项目A, 重构, 架构决策]
category: 项目A
---

# 2026-06-12 工作日志
...
```

解析规则（`parse_front_matter()`）：
- `tags`: 支持数组 `[tag1, tag2]` 或逗号分隔 `tag1, tag2`
- `category`: 字符串
- 其他自定义字段原样保留
- 搜索时标签匹配加 +30 分

## Prompt 模板格式

PROMPT_ 前缀自动识别：

```markdown
---
name: 代码审查
tags: [代码, 审查, 重构]
version: 2
description: 代码审查模板
category: 开发
---

请审查以下代码...
```

- 文件名：`PROMPT_代码审查.md`（或 `开发/PROMPT_代码审查.md`）
- `version`：保存时自动递增
- `category`：可选，保存到对应子目录

## i18n

231 键，zh/en 100% 同步。通过 `_()` 函数翻译：

```python
from memory_manager.config import _

msg = _("token_warn").format(today=5000, budget=8000, pct=62)
```

CLI 切换：`--lang zh` 或 `--lang en`
