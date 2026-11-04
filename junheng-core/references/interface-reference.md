# junheng-core · 详细接口参考

> 本文件是 `SKILL.md` 的**非规范性**详参：参数表、输出字段表、可运行示例。
> 规范契约（目的与边界、诚实性红线、用法、命令一览、退出码、拒答与替代路径 R1–R4）**仍在 `SKILL.md`**，
> 两者冲突时以 `SKILL.md` 为准。
>
> ⚠ **本文件不复制 MANIFEST 的指纹值。** 清单由 `scripts/sync-skills.mjs` 生成，每条 `sha256` 由同步器
> 现算写入 —— 需要具体值请**查看镜像目录里的 `MANIFEST.json`**，不要引用本文档里的数字。

## 1. 参数详表

**传参注意**：选项名用双短横（`--check`）；带值的选项写成 `--skills-dir <路径>`。

| 参数 | 默认 | 说明 |
|---|---|---|
| `--check` | 关 | 只校验不写盘；有漂移 exit 1，源文件缺失 exit 3 |
| `--dry` | 关 | 只打印计划不写盘 |
| `--json` | 关 | 换成机器可读 JSON，可与上面组合 |
| `--skills-dir <路径>` | `~/.workbuddy/skills` | 覆盖目标目录（换机 / 测试） |
| `-h` / `--help` | — | 打印用法 |

技能根目录亦可用环境变量 `JUNHENG_SKILLS_DIR` 覆盖。

**参数面真源**：`scripts/sync-skills.mjs` 的选项解析；`-h` 由该真源渲染。
本文表格与之不一致时，以命令输出为准。

## 2. 输出字段（MANIFEST.json）

同步器在每个技能目录生成一份**只读** `MANIFEST.json`：

| 字段 | 说明 |
|---|---|
| `formatVersion` | 清单格式版本，当前 `1` |
| `generator` | 固定 `scripts/sync-skills.mjs` |
| `skill` | 本技能名 |
| `entries[].dest` / `.origin` | 技能目录内相对路径 / 项目内真源路径 |
| `entries[].kind` | `template` / `vendor`（src/lib）/ `vendor-data`（src/data） |
| `entries[].sha256` | 真源文件指纹 |

引用方另有 `coreRef: {name, manifestSha}` —— core 一变即报 `CORE_REF_MISMATCH`。

## 3. 可运行示例

```bash
$ node scripts/sync-skills.mjs --dry
将同步到：C:\Users\<你>\.workbuddy\skills
  junheng-core（11 个文件）
    SKILL.md  ←  cli/skills/junheng-core/SKILL.md
    ...
```
