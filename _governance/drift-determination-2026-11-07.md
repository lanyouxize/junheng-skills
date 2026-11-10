# 镜像漂移逐处判定表（2026-11-07）

> 判定依据：`scripts/lib/skills-verify.mjs` 的 `classifyDrift(manifestSha, sourceSha, mirrorSha)`。
> 权威侧一律为 **SOURCE**（SKILL.md/per-skill 脚本 → `cli/skills/<name>/`；core vendor 模块 → `src/lib/`）。
> 镜像（`.workbuddy/skills/<name>/`）是只读部署副本，须对齐源。
> 冲突项（13 项）的镜像独有编辑见 `drift-conflict-review-2026-11-07.md`，须人工定夺后再决定是否写同步。

## 一、机械可定（18 项）→ 源权威，可安全重同步

| # | 技能 | 文件 | 漂移类型 | 权威侧 | 动作 |
|---|------|------|----------|--------|------|
| 1 | junheng-standards | scripts/lib/locate.mjs | SOURCE_DRIFTED | 源 | 同步镜像←源 |
| 2 | junheng-energy | scripts/lib/locate.mjs | SOURCE_DRIFTED | 源 | 同步镜像←源 |
| 3 | junheng-bcs | scripts/lib/locate.mjs | SOURCE_DRIFTED | 源 | 同步镜像←源 |
| 4 | junheng-safety | scripts/lib/locate.mjs | SOURCE_DRIFTED | 源 | 同步镜像←源 |
| 5 | junheng-optimize | scripts/lib/locate.mjs | SOURCE_DRIFTED | 源 | 同步镜像←源 |
| 6 | junheng-nutrition | scripts/cli.mjs | SOURCE_DRIFTED | 源 | 同步镜像←源 |
| 7 | junheng-nutrition | scripts/lib/locate.mjs | SOURCE_DRIFTED | 源 | 同步镜像←源 |
| 8 | junheng-labeling | scripts/lib/locate.mjs | SOURCE_DRIFTED | 源 | 同步镜像←源 |
| 9 | junheng-cost | scripts/lib/locate.mjs | SOURCE_DRIFTED | 源 | 同步镜像←源 |
| 10 | junheng-feeding | scripts/lib/locate.mjs | SOURCE_DRIFTED | 源 | 同步镜像←源 |
| 11 | junheng-pipeline | scripts/lib/locate.mjs | SOURCE_DRIFTED | 源 | 同步镜像←源 |
| 12 | junheng-attainment | scripts/lib/locate.mjs | SOURCE_DRIFTED | 源 | 同步镜像←源 |
| 13 | junheng-standards | scripts/vendor/standards.js | MIRROR_TAMPERED | 源 | 回退镜像→源 |
| 14 | junheng-energy | SKILL.md | MIRROR_TAMPERED | 源 | 回退镜像→源 |
| 15 | junheng-safety | SKILL.md | MIRROR_TAMPERED | 源 | 回退镜像→源 |
| 16 | junheng-optimize | SKILL.md | MIRROR_TAMPERED | 源 | 回退镜像→源 |
| 17 | junheng-pipeline | scripts/cli.mjs | MIRROR_TAMPERED | 源 | 回退镜像→源 |
| 18 | junheng-core | SKILL.md | MIRROR_TAMPERED | 源 | 回退镜像→源 |

## 二、须人工定夺（13 项）→ 源为基线，但镜像含独有编辑，盲目重同步会丢失

| # | 技能 | 文件 | 漂移类型 | 镜像独有行数 | 待决策 |
|---|------|------|----------|--------------|--------|
| 19 | junheng-bcs | SKILL.md | BOTH_CHANGED | 85 | 回写源 / 丢弃 |
| 20 | junheng-core | SKILL.md | BOTH_CHANGED | 91 | 回写源 / 丢弃 |
| 21 | junheng-nutrition | SKILL.md | BOTH_CHANGED | 97 | 回写源 / 丢弃 |
| 22 | junheng-labeling | SKILL.md | BOTH_CHANGED | 221 | 回写源 / 丢弃 |
| 23 | junheng-cost | SKILL.md | BOTH_CHANGED | 136 | 回写源 / 丢弃（镜像独有行 > 源，优先审阅） |
| 24 | junheng-feeding | SKILL.md | BOTH_CHANGED | 103 | 回写源 / 丢弃 |
| 25 | junheng-pipeline | SKILL.md | BOTH_CHANGED | 96 | 回写源 / 丢弃 |
| 26 | junheng-attainment | SKILL.md | BOTH_CHANGED | 111 | 回写源 / 丢弃 |
| 27 | junheng-core | scripts/vendor/nutrition.js | MIRROR_TAMPERED | 2093(diff) | 回写源 / 丢弃（差异极大，必审） |
| 28 | junheng-core | scripts/vendor/labeling.js | MIRROR_TAMPERED | 429(diff) | 回写源 / 丢弃 |
| 29 | junheng-core | scripts/vendor/feedingGuide.js | MIRROR_TAMPERED | 1292(diff) | 回写源 / 丢弃 |
| 30 | junheng-core | scripts/vendor/multiPetPlan.js | MIRROR_TAMPERED | 348(diff) | 回写源 / 丢弃 |
| 31 | junheng-core | scripts/vendor/portionLabel.js | MIRROR_TAMPERED | 394(diff) | 回写源 / 丢弃 |

> 注：#27–#31 的"diff 行数"为镜像 vs `src/lib` 真源的全量差异（非纯独有行），因 core vendor 为逻辑文件，差异即代表被改程度。

## 三、EXTRA_FILE 警告（12 项，不影响运行）

12 个技能目录内各有未登记 `CHANGELOG.md`（属 warn 级，scripts/ 外）。建议：从镜像移除（使镜像严格等于源），或反向把 CHANGELOG 登记进源再同步。低优先级。

- junheng-standards / energy / bcs / safety / optimize / core / nutrition / labeling / cost / feeding / pipeline / attainment 各 1 个 `CHANGELOG.md`

## 四、写同步执行建议（待你裁决）

- **可直接跑** `node scripts/sync-skills.mjs`：仅修复 #1–#18（源权威，无镜像独有编辑风险）。
- **不可盲目跑**：#19–#31 含镜像独有编辑，须先就 `drift-conflict-review-2026-11-07.md` 逐处定"回写源 / 丢弃"，再同步。
- 当前**未执行任何写同步**（本文件仅为判定）。
