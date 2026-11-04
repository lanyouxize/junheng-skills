# 技能资产版本控制（VCS）操作手册

> 建立于 2026-11-04。仓库位置：`~/.workbuddy/skills/.git`，工作区就是技能根目录本身。
> 目的只有一个：**改了技能脚本能回退，删了能恢复**。此前 `export-bus.cjs` 从 34907 B
> 改到 41350 B，没有 diff、没有历史，回退只能手抄。

## 〇、三个仓库（同一套口径）

| 仓库 | 工作区 | 内容 | 为什么单独建 |
|---|---|---|---|
| skills | `~/.workbuddy/skills/` | 186 个技能源码与文档（1,595 文件 / 23.5 MB） | 主战场 |
| tools | `~/.workbuddy/tools/` | 判定脚本：`skill_audit.py` / `rules_lint.py` / `node_credit.py` 等（12 文件） | **判据比被判定对象更需要历史** |
| rules | `~/.workbuddy/rules/` | 九条铁律正文 `.mdc` + 历史 `.bak` + 全文参考（14 文件） | 铁律坏了是所有会话一起失灵 |

三者共用同一份 `.gitattributes`（字节相同）与同一套校验器，**不各写一份脚本**——
复制就会漂移，而漂移的判据比没有判据更糟（tools 那次事故的起因正是判据被单点改动）。

## 一、一句话用法

```bash
~/.workbuddy/tools/vcs-all.sh status     # 三仓库状态一次看完（谁被改了）
~/.workbuddy/tools/vcs-all.sh verify     # 三仓库全量字节校验 + clone 演练
~/.workbuddy/tools/vcs-all.sh bundle     # 打三份 bundle 到 D:/skill-vcs/ 并逐份校验
~/.workbuddy/tools/vcs-all.sh all        # verify + bundle，收尾用这个
```

单仓库操作（需要看细节时）：

```bash
cd ~/.workbuddy/skills
git status                 # 谁被改了（这一条就能抓「sync-skills 静默覆盖」那类事故）
git diff                   # 改了什么（文本差异正常可读）
git add <显式路径>          # 按规则：不用 git add -A 一把梭
git commit -m "..."        # 一个改动一个提交
git log --oneline -10      # 历史
```

## 二、恢复

| 场景 | 命令 |
|---|---|
| 某个文件改坏了 | `git checkout -- <path>` |
| 想退回某次提交的整份内容 | `git restore --source=<commit> -- <path>` |
| 看某文件历史版本 | `git log --oneline -- <path>` 然后 `git show <commit>:<path>` |
| 换电脑 / 目录被清空 | 见第四节 |

## 三、口径：什么入库、什么忽略

原则：**能从别处重建的忽略，丢了补不回来的入库。**

入库包括：全部技能的源码与文档、`_prune_backup/`（裁剪前旧技能 24 文件）、
历次 `*.bak` 手工备份、技能自带素材（PDF/PNG 等，最大 2.6 MB）、`_governance/` 治理脚本。

忽略项及理由（细节见 `.gitignore` 注释）：

| 忽略 | 理由 |
|---|---|
| `/werss-ctl/` | 它自带独立仓库（16 提交）。父仓库接管会被 git 当成 gitlink，clone 出来是空目录 |
| `node_modules/` `__pycache__/` `*.pyc` | 可重建 |
| `.pytest_cache/` | pytest 自己写 `*` 忽略，显式化避免对账困惑 |
| `.DS_Store` `Thumbs.db` `*.tmp` `*.swp` | 系统垃圾 |

**`werss-ctl` 的版本兜底由它自己的 `.git` 负责**，不在本仓库内。

## 四、换电脑怎么恢复

```bash
# 方式一：从异地 bundle（推荐，D 盘 / 移动硬盘都行）
git clone /d/skill-vcs/skills-YYYYMMDD.bundle ~/.workbuddy/skills-restored
# 方式二：目录还在，只是文件被删
cd ~/.workbuddy/skills && git checkout -- .
```

恢复后必须核一次（判据，不是建议）：跑第六节的 `vcs-verify.py`，
它会做全量比对（1593 个文件逐个比 sha，不抽样）并给出 PASS / FAIL。

## 五、行尾：为什么必须有 `.gitattributes`

本机 `git config --system` 带 `core.autocrlf=true`（Git for Windows 安装器写的），
而 **core.* 配置不随 clone 继承**。实测不加属性直接 clone：**1117 / 1592 个文件被
LF→CRLF 重写**，`GOVERNANCE.md` 11370 → 11497 B。

本目录行尾本来就混排：**468 个文件 CRLF、1124 个 LF**，任何统一的 `eol=` 规则都会
改坏另一侧。所以用 `* -text`：add / checkout 两个方向都不做转换，工作区 = 索引 = blob
三者恒等。

副作用经实测排除：`-text` 不影响 `git diff` 出 hunk（git 2.55，文本文件照常可读）。

## 六、校验脚本

```bash
cd ~/.workbuddy/skills
python -X utf8 _governance/vcs-verify.py           # 工作区 vs HEAD 全量字节比对
python -X utf8 _governance/vcs-verify.py --clone   # 克隆到临时目录再全量比对，验完自动删除

# 同一套判据校验另外两个仓库
python -X utf8 _governance/vcs-verify.py --root ~/.workbuddy/tools --clone
python -X utf8 _governance/vcs-verify.py --root ~/.workbuddy/rules --clone
```

`--clone` 是真正的「换机恢复」演练：它证明的不是「git 认为文件没变」，
而是「新克隆出来的文件与现有文件每一个字节都相同」。

## 七、边界（必须知道的三件事）

1. **没有 remote，没有 push。** 三个仓库都只在本机。`.git` 与工作区在同一目录里，
   平台重装若连目录一起清掉，仓库一起消失 —— 所以每轮收尾要打 bundle 到 D 盘：
   `git bundle create /d/skill-vcs/<repo>-YYYYMMDD.bundle --all`。
   当前三份：`skills-20261104.bundle`（12 MB）/ `tools-20261104.bundle`（38 KB）/
   `rules-20261104.bundle`（32 KB），均经 `git bundle verify` 判为 complete history，
   且各自 clone 出来与工作区逐字节一致。
2. **系统级 `core.autocrlf=true` 仍然存在**，但 `.gitattributes` 已覆盖它；
   若哪天在别的机器上 clone 后发现文件变大，先查 `git check-attr -a -- <path>`。
3. **覆盖范围与未覆盖项**：已覆盖 `skills/` `tools/` `rules/`。
   **仍未覆盖**：`settings.json`、`.skill-list-cache.json`、`workbuddy.db`（平台数据库）、
   `projects/`（会话日志）。前两者是配置，动它属平台行为；后者体量大且由平台自动管理。
   `agents/` `commands/` `hooks/` 三个目录本机不存在，无从覆盖。
