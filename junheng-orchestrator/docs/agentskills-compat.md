# agentskills.io 兼容性核查清单（junheng 技能）

> 用途：核对本地 `junheng-*` 技能是否符合 [agentskills.io](https://agentskills.io) 开放标准，
> 使技能可被任意兼容 agentskills.io 的 agent 发现、加载、复用。
> 检查器：`scripts/check-agentskills.mjs`（零依赖 Node，可 CI 门禁）。

## 1. 规范依据（来源分级，不臆造强制项）

- **Tier 1 强制 — agentskills.io 开放标准（已抓取验证）**
  agentskills.io 官方页明确：*“a skill is a folder containing a SKILL.md file. This file includes metadata (name and description, at minimum) and instructions … Optional: scripts/, references/, assets/.”*
  即：技能 = 含 `SKILL.md` 的文件夹；`SKILL.md` 至少含 `name` + `description` + 指令正文。
- **Tier 2 推荐 — Anthropic 开放标准惯例（来源：agentskills.io 标注“originally developed by Anthropic, open standard”）**
  非 agentskills.io 强制，但属通用良好实践，且部分为钧衡内部约定。明确标注，不冒充强制。

## 2. 核查项清单（13 项）

| 编号 | 层级 | 核查项 | 判定标准 |
|---|---|---|---|
| C1 | T1 | SKILL.md 存在 | 技能根目录有 `SKILL.md` |
| C2 | T1 | frontmatter 合法 | 首对 `---` 围栏可解析 |
| C3 | T1 | `name` 非空 | frontmatter 含 `name` 且非空 |
| C4 | T1 | `description` 非空 | frontmatter 含 `description` 且非空 |
| C5 | T1 | 含指令正文 | `---` 之后正文 > 50 字符 |
| C6 | T2 | `name` == 目录名 | 便于 discovery 映射 |
| C7 | T2 | `name` 符合 `^[a-z0-9]+(-[a-z0-9]+)*$` | 小写字母/数字/连字符 |
| C8 | T2 | `description` ≤ 1024 字符 | 控制发现期上下文占用 |
| C9 | T2 | `description` 含触发词 | 含“当用户/使用/问/when”之一 |
| C10 | T2 | 双语 `description_en` | 钧衡内部约定（中英文描述） |
| C11 | T2 | `author` 存在 | 溯源 |
| C12 | T2 | `version` 存在 | 版本管理 |
| C13 | INFO | 可选目录 | `scripts/ references/ assets/` 按需使用 |

> 退出码：任一 T1 = FAIL → `1`（不兼容，阻断）；仅 T2 WARN → `0`（兼容，WARN 供人工跟进）。

## 3. 运行方式

```bash
# 核查整个技能目录（默认 $HOME/.workbuddy/skills）
node scripts/check-agentskills.mjs

# 核查指定根目录
node scripts/check-agentskills.mjs /path/to/skills

# 机器可读输出
node scripts/check-agentskills.mjs --json
```

## 4. 运行快照（2026-11-06，真实运行）

对本地 14 个 `junheng-*` 技能运行结果：**Tier1 FAIL 0 / Tier2 WARN 0，14/14 全 PASS**。

| 技能 | T1 强制 | T2 推荐 | 结论 |
|---|---|---|---|
| junheng-attainment | ✓ | ✓ | PASS |
| junheng-bcs | ✓ | ✓ | PASS |
| junheng-core | ✓ | ✓ | PASS |
| junheng-cost | ✓ | ✓ | PASS |
| junheng-energy | ✓ | ✓ | PASS |
| junheng-feeding | ✓ | ✓ | PASS |
| junheng-formulate | ✓ | ✓ | PASS |
| junheng-labeling | ✓ | ✓ | PASS |
| junheng-nutrition | ✓ | ✓ | PASS |
| junheng-optimize | ✓ | ✓ | PASS |
| junheng-orchestrator | ✓ | ✓ | PASS |
| junheng-pipeline | ✓ | ✓ | PASS |
| junheng-safety | ✓ | ✓ | PASS |
| junheng-standards | ✓ | ✓ | PASS |

**结论**：全部 14 个 junheng 技能兼容 agentskills.io 强制规范，且全部满足推荐项，可直接被任意 agentskills.io 兼容 agent 发现与加载。

附：同目录其余非 junheng 技能（如 `workbuddy-speedup-diagnosis__skillhub`、`workbuddy-token-usage`、`wps-office` 等）存在 T2 WARN（缺 `author` / 缺 `description_en` / `name`≠目录名 等），属各技能自身维护范围，不在本清单治理对象内；检查器已正确识别（证明检查器可证伪）。

## 5. 后续维护

- 新增/修改 `junheng-*` 技能后，重跑本检查器；T1 FAIL 必须修复后方可合并。
- 若 agentskills.io / Anthropic 规范更新强制字段，先在本文 §1–§2 更新依据与清单，再调整 `check-agentskills.mjs`，保持“依据—清单—检查器”三者一致。
