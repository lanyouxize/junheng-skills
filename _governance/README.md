# `_governance` — 技能索引与命名检查

三个文件，职责不重叠：

| 文件 | 是什么 | 谁维护 |
|---|---|---|
| `taxonomy.json` | 族群分类 + 中文摘要的**单一真源** | 手工改 |
| `build_index.py` | 读 taxonomy + 各 SKILL.md，生成 `../INDEX.md` | 不用改 |
| `lint_skills.py` | 命名与结构的机器判据（9 条规则） | 不用改 |
| `check_consistency.py` | 声明↔缓存↔INDEX↔连接器↔数据引用 五维一致性（批次5 项18） | 不用改 |
| `baseline.json` | 已接受存量的冻结快照 | 由 `--baseline` 生成 |
| `REVIEW-CADENCE.md` | 月度复核清单 + 台账（批次5 项17） | 手工填台账 |

`INDEX.md` 是**产物**。想改索引内容，改 `taxonomy.json` 再重跑；不要手改 `INDEX.md`，下次重建会被覆盖。

## 日常三条命令

```bash
cd ~/.workbuddy/skills/_governance

python build_index.py --check          # 校验：有没有技能漏分类 / frontmatter 坏 / 映射失效
python build_index.py                  # 重建 ../INDEX.md
python lint_skills.py --new-only       # 判据：只看基线外新增，exit 0 才算过
python check_consistency.py --strict    # 五维一致性闸门，exit 0 才算过（建议 --strict）
```

## 什么时候跑

| 时机 | 跑什么 |
|---|---|
| 装了新技能 / 新建了技能 | `build_index.py`（会提示未分类）+ `lint_skills.py --new-only` |
| 改过某个 SKILL.md 的 frontmatter | `lint_skills.py --new-only` |
| 准备合并或删除技能之前 | `build_index.py` 先重建，确认索引是最新的 |
| 每批治理动作收尾 | 三条全跑，把输出贴进治理台账 |
| 月度复核（见 `REVIEW-CADENCE.md`） | 五步走，每条命令对应一档，结果填进台账表格 |

## 基线怎么用（重要）

`baseline.json` 存的不是"允许违规"，而是"**已经知道、还没修**"。它的唯一作用是让检查器只对**新引入**的问题报警，避免 62 条存量噪声淹没 1 条新问题。

三条纪律：

1. **修完一批必须刷新基线**：先跑 `--new-only` 看「已消解 N 条」，确认数字对得上，再 `python lint_skills.py --baseline` 覆盖基线。
2. **刷新前必须解释消解**。如果消解数莫名其妙变大，说明有技能被误删或改坏了，先查再刷。
3. **不许为了变绿而刷基线**。基线里每一条都对应一个待修项，写进 `INDEX.md` 附录的清单里；清单变短才是进展。

## 自己验证检查器还有效

检查器如果从不报错，就等于没有。造一个假的违规技能，确认它报红，再删掉：

```bash
cd ~/.workbuddy/skills
mkdir _linttest && printf -- '---\nname: Wrong Name\n---\n\nbody\n' > _linttest/SKILL.md
cd _governance && python lint_skills.py --new-only    # 应 exit=1，报 E2/E3/E5 三条
cd .. && rm -rf _linttest
cd _governance && python lint_skills.py --new-only    # 应恢复 exit=0
```

2026-10-31 实测结果与预期一致（exit=1 → 3 条 E → 清理后 exit=0）。

## 规则清单

E 级（必须修，违反规范）：

| 规则 | 判据 |
|---|---|
| E1 dir-suffix | 目录名含 `__`（skillhub 等安装器残留后缀） |
| E2 dir-vs-name | 目录名 ≠ frontmatter `name` |
| E3 name-slug | `name` 不是合法 slug（只允许 `a-z0-9._-`） |
| E4 frontmatter | frontmatter 缺失 / YAML 解析失败 / 缺 `name` |
| E5 desc-empty | `description` 缺失或有效字符 < 10 |

W 级（建议修）：

| 规则 | 判据 |
|---|---|
| W1 orphan-dir | 非 `_`/`.` 开头的目录里没有 `SKILL.md` |
| W2 oversize | `SKILL.md` > 10240 字节 |
| W3 desc-long | `description` > 1024 字符 |
| W4 desc-short | `description` < 20 字符 |

## 有意不做的检查

| 不管什么 | 为什么 |
|---|---|
| description 能不能命中触发 | 语义判断，正则做必然误报。改由 `INDEX.md` 的「触发词」列人工核对 |
| 两个技能功能是否重复 | 同样是语义判断，只能在合并评审时逐对看 |
| 技能内容质量 | 那是 `skill-optimizer` / `darwin-skill` 的职责，不是命名 lint |

早期版本曾有一条 W5「description 无触发线索词」，实测 21 条命中里多数是误报（描述用「适用于」「for web testing」这类合理句式），已删除——留着它只会训练人忽略检查器输出。
