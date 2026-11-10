# 删除前留痕（DELETE LOG）

- 时间：2026-11-07 13:18:12

- 对象：`D:/workbuddy重做系统后版本/2026-10-23-14-10-52/_prune_backup/2026-10-31`

- 文件数：8，总字节：96305

- 性质：本目录本身即上轮剪枝的安全网备份；其原始内容（MEMORY.md/PITFALLS.md/perfect-distillation 技能/模板骨架）在主仓库对应位置仍存，删除为冗余快照清除。

- 铁律：删前留痕 + sha256 清单；用户于 2026-11-07 显式授权「立即执行」删除。


| 相对路径 | 字节 | sha256 |
|---|---|---|
| `MANIFEST.sha256` | 703 | `bb68f653938ef0d07acb6b723d1135de6a2b5dd5b7331cf66d055ae6049c8ea7` |
| `MEMORY.md.bak` | 11103 | `59b3052ca98d811266c1279bde582225789e83f1a2b1b7f73f5dc0804fa49410` |
| `PITFALLS.md.bak` | 49283 | `6002799d7dea2c549700ff1e7e3f20dadd3f26f2c59ffbcfb7e14b29f0e162b6` |
| `skills/_template_ORIG/SKILL.md` | 1535 | `e67a43a0b1cb8e334f6757ae3c1b04587a8ed39c0bf1b15bdef7a5ccab4c3d16` |
| `skills/_template_ORIG/references/README.md` | 540 | `1ee60ce6fa191d6a658647e014d890c6ba26dd198b7dffffe5ffc935655ecab6` |
| `skills/_template_ORIG/scripts/README.md` | 589 | `89a0d3ba8da8d5ef9feced0d09c684b792e0b85a03b4c2c6831fd64f7efa2880` |
| `skills/memory-manager-v2.SKILL.md.removed` | 493 | `25fd3186b43a7056963b5bb805e08ffba17761c15026cafa9083c8ad45f42f72` |
| `skills/perfect-distillation.SKILL.md.bak` | 32059 | `be2d3cdf4d1a294548b6bfdc84f18725a6a8eeea3e48fc05285ddea00ac4cd17` |

> 删除后本清单为唯一可重建依据；如需恢复，按相对路径从主仓库对应位置取原文件即可（非唯一数据）。

## 删除 _governance 临时备份回滚点 [2026-11-07T20:44:43]
- 授权：用户显式确认「确认删除全部10项」（C 盘发布副本对齐善后 / 本地临时备份清理）
- 删除项(10)：
  1. bak_2026-11-07/ (2文件)
  2. bak_2026-11-07_125117/ (3文件)
  3. bak_changelog_skills-manifest_2026-11-07.mjs (1文件)
  4. bak_mirror_2026-11-07/ (179文件)
  5. bak_mirror_preB_2026-11-07/ (162文件)
  6. bak_preclean_2026-11-07/ (27文件)
  7. bak_replica_preAlign_2026-11-07/ (14文件)
  8. bak_src_2026-11-07/ (14文件)
  9. 可删除_源独有保留块_2026-11-07.md (1文件)
 10. source-only-kept_2026-11-07.md (1文件)
- 合计：约 404 文件 / 3.94MB。本机 NukeOnDelete=1，不依赖回收站。
- 保留：DELETE_TODO/LOG.md、README、VCS.md、build_index/check_consistency/lint_*/snapshot/vcs-verify.py、taxonomy/SNAPSHOT/baseline.json 及全部 drift-*/mirror-sync-audit-*/consistency-baseline-* 审计文档。

## 删除 _governance 临时备份回滚点 [2026-11-07T21:08:03]
- 授权：用户显式确认「确认删除全部10项」（C 盘发布副本对齐善后 / 本地临时备份清理）
- 删除项(10)：
  1. bak_2026-11-07/ (2文件)
  2. bak_2026-11-07_125117/ (3文件)
  3. bak_changelog_skills-manifest_2026-11-07.mjs (1文件)
  4. bak_mirror_2026-11-07/ (179文件)
  5. bak_mirror_preB_2026-11-07/ (162文件)
  6. bak_preclean_2026-11-07/ (27文件)
  7. bak_replica_preAlign_2026-11-07/ (14文件)
  8. bak_src_2026-11-07/ (14文件)
  9. 可删除_源独有保留块_2026-11-07.md (1文件)
 10. source-only-kept_2026-11-07.md (1文件)
- 合计：约 404 文件 / 3.94MB。本机 NukeOnDelete=1，不依赖回收站。
- 保留：DELETE_TODO/LOG.md、README、VCS.md、build_index/check_consistency/lint_*/snapshot/vcs-verify.py、taxonomy/SNAPSHOT/baseline.json 及全部 drift-*/mirror-sync-audit-*/consistency-baseline-* 审计文档。

## 更正 [] - 上述删除的执行细节
-  因首轮 rm 路径误写连字符为下划线（kept_2026 vs kept-2026）而漏删，已于本轮用正确文件名补删成功。
- 最终状态：10 项临时备份全部删除完毕；_governance 仅保留活跃治理文件与审计文档。
