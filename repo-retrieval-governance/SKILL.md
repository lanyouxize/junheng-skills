---
name: repo-retrieval-governance
display_name: 仓库检索面治理
display_name_en: Repo Retrieval Governance
description: 诊断并治理 AI 协作项目越用越贵的问题：量化检索面污染、常驻大文档、记忆层膨胀、会话累积与备份堆积五类 token 泄漏源，给出产物体检与处置方案。当用户问为何对话越来越贵、仓库暴涨、检索被副本淹没时用。
description_zh: 诊断并治理「AI 协作项目越用越贵」——当用户问「为什么每次对话 token 越来越大 / 怎么省 token / 越用越慢」，或发现仓库体积几个月涨了几百 MB、检索被重复副本淹没、备份与归档目录堆在源码树里时使用。覆盖：五类 token 泄漏源的量化方法（检索面污染 / 常驻大文档 / 记忆层膨胀 / 会话累积 / .bak 备份堆积）；「体积产物体检 → 只移可重建项出仓 → 立会红的断言」三步治理流水线；散落污染的归档 SOP（动手前先查守卫是否依赖它、归档落点必须在集合树之外）；源头治理：备份「不留原地」铁律 + 配套工具 safe_backup.py（--check 报落点是否在树内）+ 备份义务分级。附两种被实测推翻的错误直觉（工具会读 .gitignore / 看起来像垃圾就可弃）。触发词：token 消耗、越用越贵、省 token、仓库太大、检索太慢、dist 巨兽、检索面、体积产物出仓、sweep_artifacts、.bak 归档、备份不留原地、safe_backup。
description_en: 'Diagnose and fix AI-collaboration projects that get more expensive over time: quantify five token leak sources (retrieval pollution, resident large docs, memory bloat, session accumulation, backup piles), then run a three-step governance pipeline that only moves rebuildable artifacts out of the repo tree.'
category: 02-Engineering
version: 1.0.1
author: 彬总
---

# 仓库检索面治理 · 让 AI 协作成本不随时间上涨

## 一、先给结论：钱不是花在模型上，是花在**你自己的历史副本**上

2026-09-14 在 `<your-company-workbench>`（38 环公司管理工作台）实测到完整因果链：

| 观测 | 数值 |
|---|---|
| 仓库总量 | **905.9 MB / 42998 文件** |
| 其中 `dist/`（交付包产物） | **699.8 MB / 41151 文件** = 体积 77.4%、**文件数 95.7%** |
| `data/` 真实库与源文件 | 131.9 MB / 665 文件 |
| `backups/` | 46.4 MB / 132 文件 |
| 一次普通检索（`import_assets`） | 返回 **60 条命中，55 条来自 `dist/` 的历史副本** |

机制：**仓库每 `pack` 一次就多一份源码全量副本**（打包器默认 `keep_old=True`，旧包只改
名 `.bak_HHMMSS` 留在原地，只增不减；实测堆到 19 份总包 + 一个 441 MB 的
`_archive_superseded_*`）。而 **Grep/Glob 类工具多数不读 `.gitignore`** ——
于是：*对话越往后 → 仓库越大 → 检索命中越长 → 每次工具调用吃的 token 越多*。

## 二、四类泄漏源，按"能省多少"排序

| # | 泄漏源 | 症状 | 量级 | 治法 |
|---|---|---|---|---|
| ① | **检索面污染** | Grep 命中里一半以上来自副本；Glob 出一堆同义路径 | **最大**（本次 95.7% 文件数） | 把"可重建产物"移出仓库（§三） |
| ② | **常驻大文档** | 每次进上下文的长文档（SKILL.md / README / 总纲） | 单份 2~5 万 token | 拆「索引 + 分册」，按需读（§五） |
| ③ | **记忆层膨胀** | 日记忆 100+ KB / 篇，被"读一下记忆"整目录吃进去 | 一次 10 万 token 级 | 蒸馏进索引 + 老日记归档（§五） |
| ④ | **会话累积** | 单会话几十次工具调用，后半程每次都拖着前半程全部内容 | 线性上涨 | 一线一会话；状态落盘不靠上下文记（§五） |
| ⑤ | **`.bak` 备份堆积** | 「改一次文档就留一份 `.bak_<戳>`」，只增不减 | 中（2026-09-20 实测：项目内 **145 份 / 11.9 MB**；用户级 skills **42 份 / 7.4 MB**） | 归档到**集合树之外** + 清单可回迁（§七） |

**先量①，因为它最大、最好治、且零风险。**

## 三、三步治理流水线（①的核心动作）

### 第 1 步：体检（只读）
按目录汇总 (字节, 文件数)，**同时报两个口径**：
```python
for d in sorted(ROOT.iterdir()):
    if d.is_dir(): print(d.name, dir_size(d))   # dir_size = os.walk 累加 size/计数
```
⚠️ **必须看文件数**，不能只看 MB。检索面的真实代价是"有多少个文件会被扫"：
一个 52 MB / 4 文件的目录对检索**无害**，41151 个文件才是灾难。

### 第 2 步：只移"**能一键重建**"的项出仓
入选标准**只有一条**：

> **删了能一键重建吗？** 能 → 可移出；不能 → 不许碰。

| 判定 | 例子 |
|---|---|
| ✅ 可移出 | `dist/`（打包器重建）、`__pycache__/`（Python 重建）、`build/`、`node_modules/` |
| ❌ 不许碰 | `data/`（真实库/源文件）、**程序自己会写的目录**、含真实业务文件的归档目录 |

⚠️ **被实测推翻的直觉**：`backups/` 和 `archive/` 看起来最像垃圾，实际是**设计目录** ——
`core/backup.py` 里 `BACKUP_DIRNAME = "backups"` / `ARCHIVE_DIRNAME = "archive"`，
每次 `check/build` 都会往里落一份，另有测试读 `backups/desktop-entry-broken_*`，
`archive/inbound/` 里还躺着**真实业务合同**。**移了就是事故**（本次已回迁）。

实施纪律：
- **只 `move` 不删**（零删除），移到**仓库同级**的归档根（`<repo>.parent/<repo>-artifacts/`），
  刻意**不放仓库里** —— 否则"移出检索面"白做；
- **幂等**：目标已存在就叠一层带时间戳的子目录，不覆盖已归档的旧产物；
- **写清单**（`_sweep_manifest.json`，逐条记 `from`/`to`/bytes/files），支持 `--restore` 一键回迁；
- 归档根路径要**和打包器的输出路径同源**（都在一个模块/常量里定义），否则归档会分叉成两堆。

参考实现：`<your-company-workbench>/tools/sweep_artifacts.py`（`--dry` 体检 / 默认移出 / `--restore` 回迁）。

### 第 3 步：把"不许长回来"变成**会红的断言**
只移一次没有意义 —— 下一轮构建就长回来。两条断言（放既有测试文件里，别新建文件）：

```python
def test_pack_default_output_lands_outside_repo(self):
    """产物默认必须落在仓外（否则每构建一次就多一份全量副本）。"""
    out, root = Path(pk.DIST).resolve(), Path(pk.ROOT).resolve()
    self.assertFalse(out == root or root in out.parents, ...)

def test_repo_holds_no_bulk_artifact_dirs(self):
    """仓里不许再出现巨兽目录。判定**以文件数为准**，字节只作兜底。"""
    # MAX_FILES = 500（检索面代价）／MAX_MB = 300（单目录异常兜底）
```
并做**证伪**：把阈值调成 0 / 把 `DIST` 打回仓内 → 必须红（否则断言没牙）。

## 四、顺手会抓到的两类真缺陷（都值得修，不是噪声）

### ① 「落点被写死」——产物移走后测试**永远跳过**
本次改 `pack.DIST` 到仓外后，发现 `tests/test_pack.py` 里**写死** `ROOT / "dist"`
两处。后果：那两个用例从此**永远 `skipTest`** —— **跳过 ≠ 通过**，静默失去保护。
⇒ 凡是"路径/落点"必须**单源**（读 `pk.DIST`），不许在测试里重写一遍。
⇒ **教训**：说"没人依赖这个目录"之前，**先扫 `tests/`**，只扫 `core`/`tools` 会漏。

### ② 「不密闭的测试」——临时文件扔在真仓库里，守卫永久变红
实测：`test_voice_engine.py` 的「扫描器有牙」用例把探针写成 `ROOT/_tmp_xxx_probe.py`，
靠 `finally` 删。一旦进程被中断、或**两个进程并发跑同一测试文件**（例如同时跑
`run.py check` 与全量单测 —— `check` 内部也会跑全部单测），探针就**留在仓里**，
于是"全仓只有两处能读原文"那条断言**永久红**，而红因是"地上有个临时文件"、
不是"真有人开了读口"。**这种红会训练人「看到就先删文件」，最后把守卫删掉。**

修法（从根上，不打补丁）：
1. 把判据本体抽成 `readers_under(root)`，线上判据与"有牙"用例**共用同一份**；
2. "有牙"用例改用 `tempfile.mkdtemp()` 建临时仓库，喂正/反样本（真读口 / 只 COUNT 不读 body / `tests/` 下的同形文件），**不再往真仓库扔任何文件**；
3. ⚠️ **排查期间的纪律**：`run.py check` 会跑全部单测 ⇒ **绝不要把全量单测与 `check`/`build` 并发跑**，否则会得到假的失败（本次亲身踩到，白排查一轮）。

## 五、②③④ 的治法（文档/记忆/会话）

- **常驻大文档**：把"每次都可能进上下文"的长文档拆成「**索引 + 分册**」——
  主文件只留**路由表 + 不可变结论 + 铁律**，细则挪到 `references/*.md` 按需读。
  实测待治理样本：`SKILL.md` 119.4 KB（≈2.7 万 token）、`README.md` 81.2 KB（≈1.8 万）、
  `docs/00-建设总纲.md` 167.6 KB（≈3.8 万）—— **三份合计 ≈8.3 万 token**。
- **记忆层**：日记忆按"**只读最新 1~2 篇 + 一份索引**"使用；≤30 天的旧日记蒸馏进
  `MEMORY.md` 后归档（零删除，`mv` 到归档目录）；`.bak` 备份别躺在"会被整目录读"的地方。
- **会话**：**一条任务线一个会话**；关键状态**落盘**（记忆文件）而不是靠上下文记着。
  —— 靠上下文记 = 「声明端」；落盘 = 「消费端」；只落声明端正是本工程反复抓的
  「声明 ≠ 实际」同型病。
- **检索纪律（最省 token 的习惯）**：所有 Grep/Glob **一律带 `path=` 限定**到源码目录
  （`core`/`tools`/`tests`/`seeds`/`docs`），**不对仓根做无范围检索**。

## 六、`.bak` 类污染的归档 SOP（2026-09-20 实操）

**与 §三 的区别**：§三 治的是「巨兽目录」（按**文件数**报警）；`.bak` 是**散落**的 ——
单个目录都不超标，闸门不响，但**每次检索都会被扫到**，而且越积越多。它是"温水型"污染。

### ⚠️ 动手前必须先查的一件事：**守卫会不会因此变红**

`.bak` 是被**显式排除**的类别，不是"没人管"。查法：
```bash
# 搜测试里的过滤逻辑，而不是先动手
grep -rn "\.bak" <repo>/tests/
```
2026-09-20 在 `<your-company-workbench>` 实测结论（可直接作为先例）：
- `test_determinism.py` / `test_doc_numbers.py` / `test_voice_engine.py` 的
  「活代码」扫描器**都显式滤掉** `.bak_*` 与 `*.bak`；
- `test_backup_snapshot_count_is_bounded` 数的是 **`*.manifest.json` 快照份数**，与 `.bak` 无关；
- 巨兽闸门按文件数报警 ⇒ 移走 `.bak` 只会**降**计数，永不触发。
⇒ **结论：归档 `.bak` 是安全动作**（守卫本就不依赖它们）。
**但这条结论必须每次现查** —— 别把"上次安全"当成"这次也安全"。

### 归档落点：**必须在集合树之外**

| 集合 | 归档落点 | 为什么 |
|---|---|---|
| 项目仓 `<repo>/` | `<repo>.parent/<repo>-artifacts/bak-retired.<stamp>/` | 与 §三 同源，仓外才算真出检索面 |
| **用户级 skills** `~/.workbuddy/skills/` | **`~/.workbuddy/_archive/skill-bak-retired.<stamp>/`** | skills 目录**没有任何退休机制**，只会涨；放 `skills/_archive/` 等于没移走 |

⚠️ **`~/.workbuddy/skills/` 是本工程最容易被忽略的一处**：它不归任何项目管、
没有闸门、没有 `prune`，靠"改 SKILL.md 时手留 `.bak`"一路堆到 42 份 —— 而它**每次开工都会被检索**。

### 执行纪律（沿用 §三，一条不少）

- **只 `mv` 不 `rm`**；目标已存在就叠带时间戳的子目录，不覆盖；
- **保留相对路径**（`<集合根>/<skill或子目录>/<文件名>`），回迁才能对得上；
- **逐条写 `_manifest.json`**（`rel` / `bytes` / `mode:"mv-only"` / `source` / `dest`），支持整目录回迁；
- 移完**当场校验三件事**：① 源侧残留计数 = 0；② 主文件仍在（`SKILL.md` / `LESSONS.md` 等，逐个 `Test-Path`）；③ 两个归档区清单可被解析出正确的 `count`/`dest`。

### 2026-09-20 执行记录（可作为量级参照）

| 批次 | 范围 | 份数 | 体积 | 归档落点 |
|---|---|---|---|---|
| A | 用户级 skills 全部 `.bak*`（<your-company-workbench> 15 / 工作助理·data 21 / programming-master 4 / 视频-F闸门体检 2） | **42** | 7.4 MB | `~/.workbuddy/_archive/skill-bak-retired.20260920/` |
| B | `<your-artifacts-repo>/dist/*.bak_*`（打包器旧产物目录） | **14** 目录 | **196 MB / 12014 文件** | `<your-artifacts-repo>/dist-retired.20260920/` |
| C | 项目仓 `<your-company-workbench>/` 内散落 `.bak`（core/docs/tests/tools/seeds/data） | **145** | 11.9 MB | **未动** —— 该项目自带按批退休惯例（`archive/2026-09-13-batch51/` 等），不擅动 |

> ⚠️ **C 未做的理由要写清楚**：项目仓的 `.bak` 走的是**按批退休**（有 `_archive/2026-09-11-batch30/baks/` 这类成批目录），
> 手工零散退休会打乱它的批次记录。**"同类问题"不等于"同一个治法"** —— 先看对方有没有既定机制。


### 源头治理细节已外置

第七节（让它不再长出来）的完整规则与机检入口在 `references/source-governance.md`。一次性治理不必读，只有要建长期防线时才读：

| 内容 | 何时读 | 文件 |
|------|--------|------|
| 源头治理与门禁 | 要落地长期防线、写机检脚本、改忽略规则时 | `references/source-governance.md` |

## 八、验收清单（做完了要能自证）

- [ ] 体检表：治理前后**字节数与文件数**都有数（本次 `905.9 MB / 42998` → `210.8 MB / 1841`）
- [ ] `--dry` 报「已无体积产物」；仓内不再有巨兽目录
- [ ] 新断言**已证伪**（喂坏样本必红）
- [ ] 被打回仓内的项**全部回迁**且功能测试绿（本次回迁 `backups`+`archive`+`_archive` 382 文件）
- [ ] 单测/`check` **双版本 rc=0**，且**串行跑**（不并发）
- [ ] 交付一致性：相关文档里的数字一次改齐；SKILL 双副本比 `sha256`
- [ ] 🆕 **源头治理（§七）**：日常改码**不留原地备份** —— 目标目录 `ls` 不出 `.bak_*`；归档根在集合树**之外**（`safe_backup.py --check` 无红灯）；批量改写走 `safe_backup.py` 而非手搓 `cp`
- [ ] 🆕 **退路可证（§7.6）**：备份器自身跑一次 `python ~/.workbuddy/scripts/selftest_safe_backup.py` ⇒ **11/11 PASS**；**「备份过」不算达标，「能回迁」才算**
- [ ] 🆕 **归档走命令（§7.7）**：退休一律 `safe_backup.py --retire <通配...>`，**不再手搓脚本**；清单里 `mode=mv-only` + `count` 与实移数一致 + 源侧残留 0
- [ ] 🆕 **拆完必证零丢失（§7.8）**：`split_verify.py --src 原 --dst 主 外置目录` ⇒ **报「零丢失」**；少数「有意修改」的行要**逐条解释**
- [ ] 🆕 **两个视图都在（§7.9）**：新建 `*.d/` 后 —— 搜索面 T1 绿（`selftest_memory_search.py`）+ 体检表里仍列得出这些文件
- [ ] 🆕 **判据不误导（§7.10）**：`selftest_memory_search.py` ⇒ **9/9 PASS**（T8 守「引号多词不许静默 0 命中」）；**「命中 0」必须能区分「真没有」与「查法错」**
- [ ] 🆕 **判据不自噬（§7.11）**：`selftest_memory_audit.py` ⇒ **6/6 PASS**（T2/T3 守「锚点必须**行首**，正文提及不算」）；**凡「在文本里找标记」的判据，先问「标记名会不会出现在正文里」**
- [ ] 🆕 **同日也有独立退路（§7.12）**：同一天第二次改**破坏性**内容 ⇒ 备份加 `--again`（否则快照停在当天第一次改动之前，且**静默跳过**）
- [ ] 🆕 **退休后核验（§7.13）**：`verify_retire.py <工作区...>` ⇒ **全绿**（`mode=mv-only` + 件数对上 + **归档件全在 cold 搜索面** + 抽样端到端捞回）；**只移不删 ≠ 零丢失，能捞回才算**
- [ ] 🆕 **`.bak` 归档（§六）**：① 动手**前**已 grep 过 `tests/` 确认守卫不依赖 `.bak`；② 归档落点在**集合树之外**（项目 → `*-artifacts/`；用户级 skills → `~/.workbuddy/_archive/`）；③ 逐条 `_manifest.json` 可回迁；④ 源侧残留 = 0 且主文件（`SKILL.md`/`LESSONS.md`…）逐个 `Test-Path` 为真