# 协作交接约定（HANDOFF）

> 性质：协作约定（C1 委派契约 + C2 共享上下文模板），**零行为变更**。
> 基础机制：复用现有 `handoff` 技能的真实接口（当前唯一存活副本为 `handoff__skillhub`，见 A4 审计），本约定不另造机制、不修改平台分发器。
> 来源：`plans/blazing-forging-tesla-vAXNs08a.md`（C1/C2）+ `handoff__skillhub/SKILL.md` 实测接口。

---

## 1. 委派契约（C1）

### 谁委派谁
- **委派方（delegator）**：持有完整任务上下文的主 agent / 用户；负责拆解子任务、选定承接方、定义完成信号。
- **承接方（delegate）**：被拉起的子 agent / 专家 / 技能；在限定范围内自主执行，产出结构化交接物。
- **通用化抽象**：把 `junheng-pipeline` 等"多段流水线"抽象为「委派 → 交接 → 恢复」通用模板——任何长任务都可拆为若干 delegate 段，每段以 handoff 文档作为段间契约，而非绑定某个具体技能的私有格式。

### 信号与生命周期（基于 `handoff` 技能真实接口）
- 共享 vault 根：`$HOME/.openclaw/shared/`（Obsidian vault）
  - 临时交接：`$HOME/.openclaw/shared/handoff/<project>/<YYYY-MM-DD>/...`
  - 永久知识：`$HOME/.openclaw/shared/knowledge/<project>/...`
- **创建交接**：`/handoff <project> [options]`（默认模式）
- **恢复交接**：`/handoff load <project> [--date YYYY-MM-DD]` —— 定位最近相关 handoff，摘要后询问更新/新建
- 原生 slash 不可用时回退：`/skill handoff <input>`

### 契约层纪律（复述自技能 Critical principles，作为强制约定）
1. **写前确认**：任何 `write`/`edit` 前须先报绝对路径并获用户确认。
2. **永久文档先 propose**：`--permanent` 模式须先输出 PROPOSED PATCH 并显式确认，仅 `--apply` + 确认后才落盘。

### 不触碰平台
本契约仅约定"如何交接"，不修改 Skill 分发器、不重写 `handoff` 技能；更强执行保证留待后续 Wave 机制化（不在本 Wave）。

---

## 2. 共享上下文模板（C2）

> 直接采用 `handoff` 技能定义的**临时文档必备字段**作为标准模板，避免重新发明。

### 标准 handoff 文档字段
1. **Title**：`Project Handoff: <project>`
2. **Header note**：标注 `temporary / discard after use`
3. **Key document links**：本次会话新建的永久文档链接 + 一句说明
4. **Session Goal**：本次目标
5. **Work Done**：已完成（简洁）
6. **Current Status**：产物/知识状态（非动作）
7. **Next Steps**：可行动的下一项
8. **YAML 头**（供索引）：
   ```yaml
   ---
   type: handoff
   temporary: true
   project: <project>
   date: <YYYY-MM-DD>
   created_at: <ISO8601>
   author: <agentId>
   session: <sessionKey if available>
   ---
   ```
9. （可选 `--log`）配套 `_work_log.md`：命令+关键输出、读写文件+改动摘要、假设/决策/错误（不与 handoff 的主体/目标/状态/下一步重复）

### 与本项目记忆的衔接
- **跨 agent / 跨会话的大型交接**：优先落 `handoff` 技能的共享 vault，便于 `/handoff load` 恢复。
- **本项目内部日度流水**：继续写 `.workbuddy/memory/YYYY-MM-DD.md`（既有实践）。两者互补——handoff 给"人/其他 agent 看的大图"，日度记忆给"本项目的日度增量"。
- **不塞敏感信息**：密钥 / provenance 类信息走各自治理文档（`MCP-GOVERNANCE.md` / `GOVERNANCE.md` §6），不在 handoff 文档明文写入。

---

## 3. 诚实边界
- `handoff` 技能当前仅 `handoff__skillhub` 变体存活（无基目录），本约定以其为真实接口来源；若未来基目录回归，接口以基目录为准。
- 模板字段直接取自技能定义；本文件不声称新增字段或改写技能行为。
- 无自动 hook 强制交接；纪律依赖使用者遵循。
