# 裁决说明（2026-10-31 更新：同名冲突已消除）

本目录 `memory-manager-v2__skillhub` 是 `memory-manager-v2` 这一技能的**唯一功能实现**。

## 历史成因

- 基础目录 `memory-manager-v2/` 原本只含 `config.json`（`{"lang":"zh"}`）。按 `skills/GOVERNANCE.md` §1 的约定，它是**配置容器目录，不是独立技能**。
- 2026-10-25 有人给它补了一份 493 B 的极简 `SKILL.md`（自述 "Not a standalone skill"）。副作用：技能扫描器按「目录 + frontmatter」把它也注册成一个技能，与本目录 `SKILL.md` 里的 `name: memory-manager-v2` **同名冲突**，造成选择歧义。

## 2026-10-31 裁决

- 已移除基础目录中的 `SKILL.md`，**恢复 GOVERNANCE.md §1 的原意**。
  备份：`_prune_backup/2026-10-31/skills/memory-manager-v2.SKILL.md.removed`
- `config.json` **原地保留**，语言配置不受影响。
- 结果：`memory-manager-v2` 只剩一个注册实体（本目录），名称冲突消除。

## 后续（勿擅自处理）

目录名 `memory-manager-v2__skillhub` 与 `name: memory-manager-v2` 不一致，属命名规范问题，留待**批次 2 命名 lint** 统一处理。

⚠ **不要**为了对齐而直接改 frontmatter 的 `name`：需先确认平台是按 `name` 还是按目录名定位 `config.json`，否则可能让语言配置失效。
