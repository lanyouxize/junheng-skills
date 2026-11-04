# P0-2 · 86 技能规范 lint 报告

> 生成：2026-11-02 23:3x｜执行：`python -X utf8 lint_skills.py`（既有脚本，未改动）
> 产物：`lint-report-20261102.json`（机器读）+ 本文件（人读）
> 性质：**只读扫描，未修改任何技能文件**

---

## 一、结论先行

| 项 | 值 |
|---|---|
| 扫描技能数 | **86** |
| 违规总数 | **62** |
| 基线外新增 | **0**（脚本判 PASS） |
| 其中 E 类（"必须修"） | **18**（占 29%） |
| 其中 W 类（"建议修"） | 44（W2 超长 43 / W1 空壳 1） |

**关键判断：这个 PASS 是假的。**

18 条 E 类违规被写进了 `baseline.json` 冻结。`--new-only` 的判定逻辑是「基线外无新增即 PASS」，因此这 18 条**永远不会再报红**。这不是 lint 的 bug，是**基线把合法例外和真问题一起冻住了**，导致信号归零。

---

## 二、62 条违规的真实构成（不是 62 个问题，是 3 类）

### 第 1 类 · 口径冲突：8 个 `__skillhub` 目录（占 16 条 E）

`E1`（目录名含 `__`）× 8 + `E2`（目录名 ≠ name）× 8，根因完全同一个：

| 目录 | frontmatter name |
|---|---|
| `handoff__skillhub` | `handoff` |
| `memory-manager-v2__skillhub` | `memory-manager-v2` |
| `perfectly-replicate-writing-skills__skillhub` | `perfect-dis…`（被截断，需核） |
| `python-crawler-architect__skillhub` | `Python 爬虫架构师` |
| `self-improving__skillhub` | `Self-Improving + Proactive Agent` |
| `tiangong-skill__skillhub` | `tiangong-skill` |
| `token-saver-qclaw__skillhub` | `token-saver-qclaw` |
| `workbuddy-speedup-diagnosis__skillhub` | `workbuddy-speedup`（目录名与 name 不一致） |

但 `GOVERNANCE.md` 明确写着：**`__skillhub` 是安装器标记，这些是真实技能，保留、不自动去后缀**。

⇒ **lint 规则与治理文档直接冲突**。同一个事实，文档说「合法」，脚本说「E 必须修」。按铁律「冲突时最具体者胜」，此处应以 `GOVERNANCE.md` 为准，把 E1 降为 W 或加白名单。**否则每跑一次 lint 都在提醒 8 个不该修的东西，真问题被淹没。**

### 第 2 类 · 真问题：2 条 name 非合法 slug

| 目录 | name | 问题 |
|---|---|---|
| `python-crawler-architect__skillhub` | `Python 爬虫架构师` | 含中文 + 空格 |
| `self-improving__skillhub` | `Self-Improving + Proactive Agent` | 含空格 + `+` |

这两个 `name` 无法作为稳定的程序标识符。而铁律⑥要求「加载名须写 displayName」，说明用户侧已经在用 displayName 兜底——**这不是命名洁癖，是平台匹配可能失败的隐患**。建议：改 `name` 为 slug，displayName 保留中文。

### 第 3 类 · 容量债：43 个 SKILL.md 超 10KB

`W2` 阈值 10240 字节。43 条超标，最重的几个：

| 技能 | SKILL.md 体积 | 倍数 |
|---|---|---|
| `nuwa-skill` | 37,967 B | 3.7× |
| `perfectly-replicate-writing-skills__skillhub` | 33,396 B | 3.3× |
| `totorosir-workbuddy-score` | 32,155 B | 3.1× |
| `paper-bilingual-search` | 27,809 B | 2.7× |
| `paper-quick-reader` | 27,627 B | 2.7× |
| `wechat-article-scraper` | 20,836 B | 2.0× |
| `ui-auto-click` | 20,374 B | 2.0× |
| `web-access` | 18,827 B | 1.8× |
| `skill-optimizer` | 18,261 B | 1.8× |
| `repo-retrieval-governance` | 16,598 B | 1.6× |

**与既有记录不符**：`10-15-18-08-41` 记忆里记的是「P1 共 **11** 个超长技能待拆」，实测 **43** 个。差 4 倍。可能原因：当时口径是"超 15KB"或只统计了自建技能。⇒ 既有结论需要用本次实测覆盖。

### 第 4 类 · 空壳目录 1 个

`memory-manager-v2` 无 SKILL.md（`W1`）。`GOVERNANCE.md` 已说明它是「配置容器，不是独立技能」，其 `__skillhub` 变体才是功能副本。**同类问题，同理应加白名单而非修**。

---

## 三、判据失效的证据链（这才是本次最有价值的产出）

```
基线冻结 62 条（含 18 条 E）
        ↓
--new-only 只比「基线外新增」
        ↓
新增 0 ⇒ 退出码 0 ⇒ PASS
        ↓
结论："技能体系健康"
        ↓
实际：18 条 E 永不被报，43 条容量债永不被处理
```

这与 19 期简报 11-01 那条「扫描器 clean ≠ 安全；advisory 未进 OSV 就报 clean」是**同一种失效**：不是工具坏了，是**判据的观察窗口被收窄到"只看向未来"**，存量问题被制度性失明。

---

## 四、建议动作（不改规则文件，只改 `_governance/` 内脚本）

| # | 动作 | 判据（可失败） | 优先级 |
|---|---|---|---|
| 1 | `lint_skills.py` 加 `--whitelist`：`__skillhub` 后缀与 `memory-manager-v2` 容器目录进白名单，E1/E2/W1 对这些不再计数 | 白名单后 E 类应从 18 降到 2 | high |
| 2 | 修 2 条 name 为 slug（`python-crawler-architect`、`self-improving`），displayName 保留原文 | 重跑 E3 归 0；且平台仍能按 displayName 加载（需新会话验证） | high |
| 3 | `baseline.json` 只允许冻结 W 类，**E 类禁止入基线** | 若再冻结 E 类，脚本应直接报错退出 | high |
| 4 | 43 条超长技能分批拆（每批 5 个），优先 `nuwa-skill` / `totorosir-workbuddy-score` / `paper-*` | 拆分后 W2 计数下降，且原触发词不丢（INDEX 重建后比对） | medium |
| 5 | 把「11 个超长」的旧记录更正为「43 个（实测）」 | 记忆文件与报告口径一致 | low |

**本轮不执行以上 5 条**——它们需要改 `_governance/` 脚本与 2 个技能的 frontmatter，属批 2 范围。本轮只交付诊断。

---

## 五、附：如何复现

```bash
cd ~/.workbuddy/skills/_governance
python -X utf8 lint_skills.py                 # 全量人读
python -X utf8 lint_skills.py --json          # 机器读
python -X utf8 lint_skills.py --new-only      # 判据模式（当前恒 PASS）
```

基线构成复核：
```bash
python -X utf8 -c "import json,io,collections; b=json.load(io.open('baseline.json',encoding='utf-8')); print(collections.Counter(i['rule'] for i in b['items']))"
```
