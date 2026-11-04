---
name: publish-to-workbuddy-openplatform
description: 将专家 / 技能 / 连接器 / Buddy 应用打包成 WorkBuddy 开放平台「发布管理」可上传的 zip 代码包（≤20MB，平台自动开包解析并校验）。当用户要"上传到开放平台 / 发布专家 / 发布技能 / 发布连接器 / 发布 Buddy 应用 / 把 XXX 做成可发布的包 / 发布管理上传报错怎么办"时使用。覆盖 plugin.json 字段对齐、PNG 手搓头像、分离布局打包、以及"按平台报错逐字修正"的完整迭代流程。即使用户只说"发布一下"、"做成能上传的包"、"上传失败"，也应触发本 Skill。
agent_created: true
version: 1.0.0
---

# 发布到 WorkBuddy 开放平台

## Overview

把四类资产（专家 / 技能 / 连接器 / Buddy 应用）生成符合开放平台「发布管理」上传规范的 zip 代码包。平台要求上传 **≤20MB 的 zip**，自动开包解析并做字段级校验。每类资产的目录约定与字段规则不同——本 Skill 沉淀了「发布专家」已实测验证的 4 条铁律，以及其余三类"先上传踩错、再一字不改修"的迭代流程。

## 何时用

- 用户要"发布 / 上传到开放平台"任意一类资产
- 「发布管理」上传后平台报错（解析失败 / 字段不一致 / 文件不存在）——把报错原文照搬进修复
- 需要给专家包造真 PNG 头像（避免 README 占位被拒）
- 需要把目录打成 zip（含"分离布局"：plugin.json 在 `.codebuddy-plugin/`，资源在 zip 根）

## 总体工作流

1. 在 `publish/<type>/` 下准备源文件（`plugin.json` / `SKILL.md` / `connector.json` / `manifest.yaml` + 入口 + 资源）
2. 用 `scripts/pack.py` 打成 zip；必要时补 PNG 头像（`scripts/make_png.py`）并自检（`scripts/validate_png.py`）
3. 双备份到 `Desktop/publish-mirror/<type>.zip`（避开 `publish/` 下可能的 watcher 回滚）
4. 把 zip 交给用户上传到「发布管理」对应入口
5. 用户上传后若平台报错，**把错误原文逐字贴回**，按下面"已知铁律 / 未知项"表定位修复，重打 zip

> 关键原则：平台规则以"报错"为唯一真相。已验证的规则写死；未验证的（skill / connector / buddy-app 目录约定）绝不乱猜，等报错再改。

## 已验证：专家包 4 条铁律

（来源：实测 5 轮迭代，平台逐步拦截）

1. **目录约定**：`plugin.json` 必须位于 `.codebuddy-plugin/plugin.json`（平台按隐藏目录解析，类似 Claude Code `.claude-plugin/`）
2. **字段对齐**：`quickPrompts[0].zh/.en` 与 `defaultInitPrompt.zh/.en` **字符级完全相同**（中英分别对齐；平台用 `.h` 简写指代 `.zh`）
3. **资源真实存在**：`avatar` 等文件引用字段，在 zip 内必须有真实二进制文件（PNG 需签名 / CRC / IDAT 合法）；只放 README 占位会被拒
4. **分离布局**：plugin.json 配置在 `.codebuddy-plugin/` 内，但 `agents/`、`avatars/` 等**资源放 zip 根平级**；字段写 `avatars/vcu-test-expert.png`、`agents/vcu-test-expert.md`（**无** `.codebuddy-plugin/` 前缀）

打包用：`python scripts/pack.py expert`（自动走分离布局）。

## 已验证：Team 专家包铁律（2026-09-03 · 24 人团 v9 + 5 人团）

> 来源：24 人团经 5+ 轮迭代收敛；5 人团 1:1 复用同一 schema，平台金标准详情页核对。

1. **`expertType:"team"`** + `agentName:"<lead-role>"` 二者都必填。
2. **主理人 leadAgent**：必须存在、且对应一个真实 agent md（`agents/<role>.md`）。
3. **settings.json 必须位于 zip 根**（plugin root）——平台后端 Go struct 硬性查找。同时建议**三写兜底**：
   - `.codebuddy-plugin/settings.json`（隐藏目录）
   - `codebuddy-plugin/settings.json`（中间名）
   - `settings.json`（zip 根 ← 平台主要查找点）
   三份内容字符级一致（已实测通过 24 人团）。
4. **plugin.json 也建议双写**：`.codebuddy-plugin/plugin.json` + zip 根 `plugin.json`。
5. **settings.json 11 字段铁律**（24 人团 v9 已平台通过）：
   ```
   version / name / displayName(dict{zh,en})
   agent(STRING, = lead role id) ← 不是对象
   leadAgent / description / quickPrompts(list[3])
   tags(list[3 object{zh,en}]) ← 固定 3 项
   examples(dict{zh,en})
   defaultInitPrompt(dict{zh,en})
   members(list[object{id,isLead,name}], 至少 1 个 isLead=true)
   ```
   - Go struct: `agent of type string`（不是 object）—— 之前传对象必死。
6. **tags 固定 3 项**：在 plugin.json 与 settings.json 都校验，多了少了都报「tags 须固定 3 个」。
7. **每个 agent md 必须有 YAML frontmatter 起头**（24 人团实测模板）：
   ```yaml
   ---
   name: <role>
   description: <英文简短描述>
   displayName:
     en: "<dn_en>"
     zh: "<dn_zh>"
   profession:
     en: "<pf_en>"
     zh: "<pf_zh>"
   maxTurns: 50
   ---
   ```
   - 平台报错原文：`agents/<role>.md: 文件开头缺少 frontmatter 分隔符 ---`

## 已验证：技能包铁律（2026-09-04 · 5 个 agent-dev skill）

> 来源：兵哥上传 `agent-dev-skills-bundle.zip`（71KB）报「压缩包缺少 SKILL.md 文件」，定位 skill layout。

1. **`SKILL.md` 必须在 zip 根**——平台在 zip 根查找该文件，找不到就报「压缩包缺少 SKILL.md 文件」。
   - ❌ bundle 嵌套：`skills/<name>/SKILL.md`（找不到）
   - ❌ 隐藏目录：`.codebuddy-skill/SKILL.md`（找不到）
   - ✅ zip 根：`SKILL.md`（必备！）
2. **目录结构**（最小布局）：
   ```
   SKILL.md           ← zip 根（必备）
   icon.png           ← zip 根（推荐，platform 展示用）
   README.md          ← zip 根（自描述，可选）
   BUILD.txt          ← 破缓存用（时间戳每次变，强制 CDN 重拉）
   <其它子目录>/      ← 嵌套保留原结构（SKILL.md 引用）
   ```
3. **多 skill 可打包为 combo（一次上传得多个）**：zip 根放**一个**组合 `SKILL.md`（入口），5 个 skill 平铺到 `<name>/` 二级目录。platform 只解析 zip 根 SKILL.md，子目录 SKILL.md 作为资源不被单独注册——但内容完整可调用。
   - 适用场景：用户嫌逐个上传太累，要「一个总包」。
   - 反例：`skills/<name>/SKILL.md` 作为 zip **唯一** SKILL.md（platform 在 zip 根找不到 → 报「压缩包缺少 SKILL.md 文件」）。
4. **目录层级上限 = 2**（zip 根 → 二级目录 → 文件）：
   - platform 报「目录层级超限 — Skill 包仅支持两级目录结构（根目录/二级目录/文件）」即超了。
   - 解决：把 skill 内部深层子目录（prompts/ tools/ selves/ references/ scripts/）展平到 skill 二级目录，用 `<子路径>__<文件名>` 命名（如 `prompts/intake.md` → `prompts__intake.md`）。
5. **排除 `dist/`、`__pycache__/`、`.clawhub/`、`.codebuddy-skill/`**：发布包不打包开发期缓存与隐藏元数据目录。
6. **SKILL.md frontmatter 必填 4 字段**（platform 在 zip 根 SKILL.md 强校验）：
   ```yaml
   ---
   name: <skill-id>
   display_name: <中文展示名>           # 必填
   display_name_en: <English name>      # 必填
   description_zh: <中文描述>            # 必填
   description_en: <English description> # 必填
   ---
   ```
   - platform 报错原文（缺一即报对应行）：
     ```
     缺少 Skill 中文展示名（display_name），请在 SKILL.md frontmatter 中填写
     缺少 Skill 英文展示名（display_name_en），请在 SKILL.md frontmatter 中填写
     缺少 Skill 中文描述（description_zh），请在 SKILL.md frontmatter 中填写
     缺少 Skill 英文描述（description_en），请在 SKILL.md frontmatter 中填写
     ```
   - 现有 user-level skill 的 SKILL.md 多为旧 schema（只有 `name` + `description`），**不能直接打包**，需在打包脚本里用 wrapper 注入 4 字段。

> 参考脚本：`publish/pack_agent_dev_skills.py`（2026-09-04 实证可用，支持 combo + 5 个独立 zip 双备，已双备份到 Desktop/publish-mirror/）。

## 待验证：其余两类目录约定

| 类型 | 当前已知 | 下一步 |
|---|---|---|
| 技能 | ✅ `SKILL.md` 必须在 zip 根（2026-09-04 实测）<br/>✅ frontmatter 必填 4 字段（display_name / display_name_en / description_zh / description_en） | 已通过 5 个 skill 验证，可直接复用 `pack_agent_dev_skills.py` 模板 |
| 连接器 | 单 `connector.json`，目录名未知 | 同上 |
| Buddy 应用 | `manifest.yaml` + 入口，可能 `.buddy-app/` 或扁平 | 同上 |

通用打包：`python scripts/pack.py <type> [prefix]`，prefix 末尾带 `/`，如 `.codebuddy-skill/`。

## 资源引用字段自检清单

打包后务必核对（避免拿到缓存旧包）：

- **大小** = 预期字节数（手搓 PNG 约 15KB；带资源后专家包 ~22KB，远低于 20MB）
- **SHA256 一致**：`certutil -hashfile <zip> SHA256`（Windows）或 `sha256sum <zip>`
- **结构**：`unzip -l <zip>` 确认入口文件裸露在预期路径

## 踩坑备忘

- **zip 回滚**：`publish/` 下生成的 zip 曾被莫名还原为旧版（疑似 watcher / 同步进程）。对策：打完立即复制到 `Desktop/publish-mirror/`，上传前比对 SHA。
- **PowerShell `Compress-Archive`** 在该环境可能不写盘；用 Python `zipfile` 兜底。
- **Git Bash 无 `zip` 命令**；用 Python。
- 不要替平台猜目录约定——前一轮把 `avatar` 误写成 `.codebuddy-plugin/avatars/...` 完整路径反而错，真实规则是"资源放 zip 根、字段写无前缀路径"。

## Resources

- `scripts/pack.py` — 参数化打包：专家分离布局 / 通用前缀模式；打完打印 SHA256，可选 `--mirror` 双备份
- `scripts/make_png.py` — 无 PIL 依赖，手搓 256×256 渐变 PNG 头像（输出路径作首参）
- `scripts/validate_png.py` — 校验 PNG 签名 / CRC / IDAT 解压长度，定位"图非法"问题
- `references/expert-spec.md` — 专家包 `plugin.json` 完整字段规范 + Agent MD frontmatter 要求
