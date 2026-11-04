# 元典站点包 · 论文检索·中英对照报告（2026-10-21）

本目录是**自包含**的：`index.md` 引用的图都在 `charts/` 下，没有外部依赖。

## 怎么收录

1. 整目录拷到 vault 的目标位置（如 `docs/site/` 或某个专题目录）。
2. 把 `moc-entry.md` 里那一行加进对应的 MOC（`40_Maps/MOC--*.md`）—— **本工具不直接改 MOC**，
   因为 MOC 的归属是人工判断，脚本猜错会把页面挂到不相干的主题下。
3. 收录后跑一次 `node scripts/pack-site.cjs --verify <本目录>` 确认包未被改动。

## 文件

| 文件 | 说明 |
|---|---|
| `index.md` | 站点页正文（frontmatter + 警示 + 完整报告） |
| `charts/*.svg` | 三张分布图（除非原目录没出图） |
| `moc-entry.md` | 挂载片段 |
| `manifest.json` | 机器可读清单（sha256 / 统计 / 清单项） |

## 校验

```bash
node scripts/pack-site.cjs --verify <本目录>
```

`manifest.json` 里的 sha256 是**打包当时**的内容指纹。校验失败说明包被改过 —— 要么是有人手改了正文（那行号可能已经与表格不对应），要么是文件拷坏了。两种都不该静默通过。
