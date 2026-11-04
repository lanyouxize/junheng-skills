---
name: role-library-to-experts
agent_created: true
description: 将外部 GitHub 角色库（如 agency-agents-zh、岗位库、人设集）批量转换为 WorkBuddy 专家包——生成独立 Agent 型专家，并按部门聚合为 Team 型专家团，注册进专家市场。可复用于任意类似角色库。
---

# 角色库 → WorkBuddy 专家包 批量转换

## 适用场景
- 用户想把某个 GitHub 角色/人设库（如 `agency-agents-zh`、prompts 角色集、岗位能力库）转成 WorkBuddy 专家
- 需要「独立专家 + 部门 Team 团」两套体系并存，且可一键复用于任意类似角色库
- 需要批量、可重复、可容错的转换流程（一次转换可能涉及 100+ 专家）

## 前置条件
- 必须先加载 `expert-manager` 技能（专家包标准格式以它为权威，尤其是 categoryId 枚举、frontmatter 规范、Team 型铁律）
- 专家目录固定为 `$WORKBUDDY_CONFIG_DIR/plugins/marketplaces/my-experts/plugins`（默认 `~/.workbuddy/plugins/marketplaces/my-experts/plugins`），禁止生成到其他路径
- 下载需要网络：沙箱内直连 GitHub 443 通常失败 → 用 `dangerouslyDisableSandbox: true` 解锁；但批量 raw 请求会被限流 → 用 codeload tarball 一次性拉全量

## 流程

### 1. 拉取角色库（避免限流 / 443 失败）
直连 `git clone` 与逐一 `raw.githubusercontent.com` 抓取都会失败或限流。用 codeload tarball 一次性打包：
```bash
curl -L "https://codeload.github.com/<owner>/<repo>/tar.gz/refs/heads/<branch>" -o /tmp/repo.tar.gz
mkdir -p /tmp/repo && tar -xf /tmp/repo.tar.gz -C /tmp/repo --strip-components=1
```
示例：`jnMetaCode/agency-agents-zh` 的 `main` 分支。

### 2. 解析角色 → 独立 Agent 型专家
- 每个角色一个 `agents/<id>.md`。**ID 用文件名本身**（如 `engineering-ai-engineer`），不要拼目录前缀 —— 否则会出现 `engineering-engineering-ai-engineer` 双前缀。
- 角色文件可能嵌套在子目录 → 用 `os.walk` 递归扫描，不要 `os.listdir`（会漏掉嵌套角色）。
- plugin.json（Agent 型）关键字段：
  - `name` kebab-case；`agentName` = MD 文件名；`agents: ["./agents/<id>.md"]`
  - `categoryId` 必须从 expert-manager 的 12 个枚举中选（不可凭直觉）
  - 从已有同类包读取分类时，先 `os.path.basename(path)` 得到 aid，再定位 `<aid>/.codebuddy-plugin/plugin.json` —— 千万别把完整路径当 id 去查（会查不到 → 回退成非法 `02-Executive`）
  - `tags` 固定 3 个；`quickPrompts` 前 3 个，第 1 个 = `defaultInitPrompt`

### 3. 按部门聚合 → Team 型专家团
- 按角色自带的 division/category 字段分组，每组一个 Team 包。
- 结构：主理人 `agents/<team>-team-lead.md` + 各成员 `agents/<member>.md`（复制原始 persona + 补 frontmatter）。
- plugin.json（Team 型）铁律（`expert-manager` 权威）：
  - `expertType: "team"`，`profession == displayName`（必须一致）
  - `teamInfo.memberAgents` 列成员（不含主理人）；`members` 数组含主理人（role=lead）
  - 同名专家已存在时：先校验再注册，不重新初始化目录
  - 头像：同团队风格统一

### 4. 注册
每个包 `init → validate → register`（用 expert-manager 的 `register_expert.py --session-id <sid>`）。批量时串行执行、每批验证、失败即停。

## 关键陷阱（实测必踩，已修复）
1. **双前缀 ID**：Agent ID 必须用文件名，不用相对路径前缀（否则 `engineering-engineering-xxx`）。
2. **嵌套目录**：角色文件可能在多级目录，必须用 `os.walk`，不能用 `os.listdir`。
3. **categoryId 解析**：从已生成包读分类时，`basename(path)` → aid → 再定位 `.codebuddy-plugin/plugin.json`；用完整路径当 aid 会查不到并回退非法分类。
4. **加载锁**：对已注册到市场的包执行 `rm -rf`/`mv` 会触发 WorkBuddy 加载锁 → `PermissionError`/`safe-delete` 拦截。**不要移动/删除已注册包**，直接覆盖写文件即可。
5. **批量头像**：ImageGen 在大批量（200+）下会烧 credits 且被限流，用户常拒绝。改用 Pillow 离线生成（深蓝底 `#0b1020` + 橙红渐变 `#ff6a2b→#ff3d3d`，字体 arial/simhei，512×512 PNG，纯 ASCII 路径）。
6. **小批量**：写/改操作每批 ≤10 文件，验证后继续，失败即停。
7. **镜像**：GitHub 不可达时优先走 Gitee 镜像或多个代理（ghfast.top / ghproxy.cn / hub.gitmirror.com），不要硬编码自己算时间戳。

## 决策规则
- 单角色 → Agent；多角色协作 → Team。
- categoryId 判定优先级：主要输出物领域 > 服务对象 > 最核心领域；跨领域选最核心的一个。
- 用户未指定目标目录/标准时，先 scan 报告、再确认，绝不递归删个人目录。

## 复用示例
用户：「把 X 角色库转成专家」→ 先确认仓库地址 + 是否要部门聚合，复用本 skill 跑全流程；如需定时重复运行，创建 automation（recurring）。
