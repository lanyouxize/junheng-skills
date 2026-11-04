---
name: rev-core
description: 逆向分析流水线的唯一入口。需要拆软件/还原协议/解析 agent 应用时先跑它开单与形态识别，它管授权闸、路由 DAG、证据库与报告投影。不做任何技术分析。
description_zh: 逆向分析入口与证据闸：授权开单、形态识别、证据校验、报告投影
description_en: "Reverse-engineering pipeline entry with authorization gate, triage, evidence ledger and report projection"
version: 1.0.0
display_name: rev-core
---

# rev-core

逆向分析的**入口**与**唯一写者**。它不解析二进制、不下技术结论——它负责"这件事能不能做、按什么顺序做、结论怎么存才算数"。

## 不做什么（先读这一段）

- **不做任何技术分析**：不读函数、不反编译、不解析协议。那是 `rev-static` / `rev-runtime` 的事。
- **不判断可行性**：只按 DAG 分派，不承诺"这个目标能拆开"。
- **不代上游下结论**：上游模块只能提交**候选**，正式证据只能由 `rev-core evidence add` 写入。
- **不做保护绕过**：DRM、授权校验、加密狗、证书固定、完整性校验，一律 `exit 4`。这不是配置项，是硬编码。
- **不装第三方逆向工具**：它只调用本机已有的 Ghidra / jadx / Frida / mitmproxy。

## 何时用

| 触发场景 | 典型说法 |
|---|---|
| 要拆一个没有源码的软件 | "这个 exe 怎么控制设备的"、"把这个 GUI 的接口还原出来" |
| 要解析 agent 应用 | "看看这个 agent 的提示词和工具注册" |
| 要做协议还原 | "抓一下它和服务器怎么通信" |
| 要出分析报告 | "把这次分析写成可追溯的报告" |
| 分析做到一半要交付 | "能不能结论了" → 先跑 `gate` 看阻断项 |

## 命令速查

所有命令都在 `scripts/cli.py`，退出码统一：`0` 成功 / `1` 校验失败 / `2` 用法错误 / `3` 前置缺失 / **`4` 策略拒绝**。

```bash
# 1. 开单（越界直接 exit 4）
python scripts/cli.py init --dir D:/reva/cases/demo --target D:/reva/cases/demo/sample.exe \
    --basis self-owned --purpose interop --allow read-only

# 2. 形态识别 + 路由（写在 triage.json 的 dag 字段）
python scripts/cli.py triage --dir D:/reva/cases/demo

# 3. 看按策略过滤后的 DAG（compete-observe 会剔掉全部 static.*）
python scripts/cli.py dispatch --dir D:/reva/cases/demo

# 4. 写证据（只有本命令能写正式证据库）
python scripts/cli.py evidence add --dir D:/reva/cases/demo --file ev-0001.json
python scripts/cli.py evidence list --dir D:/reva/cases/demo

# 5. 交付闸门（有 blocking 未解项即 exit 1）
python scripts/cli.py gate --dir D:/reva/cases/demo

# 6. 报告投影（三段：结论 / 未验证 / 未解清单）
python scripts/cli.py report --dir D:/reva/cases/demo
```

## 三步上手

**第一步：开单，先答五问。** `--basis` 四选一（self-owned / written / open-source / public-spec），`--purpose` 五选一。答不上来就别开——`init` 会拒绝非法的 basis/purpose，也会拒绝申请 `drm-bypass` 这类能力。

**第二步：`triage` 看 DAG。** 它只做一件事：读文件头判断形态（PE / .NET / APK / Electron / ELF / Mach-O），给出该形态的标准路线。识别不出来就 `exit 1`，**不猜**。

**第三步：让上游模块干活，回来写证据。** 证据必须带三件套：

```json
{
  "locator": {"file_sha256": "<64位>", "addr": 4198400, "length": 6},
  "digest": {"algo": "sha256", "value": "<64位>"},
  "reproduce": {"cmd": "python xrefs.py sample.exe 0x401000 6", "cwd": ".", "env": {}}
}
```

缺任何一项，`evidence add` 直接拒绝写入——**不是降级，是拒收**。降级只发生在"你自己标 E0"的时候。

## 工件契约

四类对象（完整定义见 `references/schema/reva-1.json`）：

| 对象 | 一句话 | 关键约束 |
|---|---|---|
| `evidence` | 一条可重跑的事实 | `locator` + `digest` + `reproduce` 三件套；`confidence` 禁止手填 |
| `finding` | 一条可判真假的结论 | 必须引用 ≥1 条 evidence；`corroborated` 需 ≥2 条**不同 channel** 的证据 |
| `unknown` | 一个没解出来的问题 | 一等公民，`blocking=true` 时 gate 拒绝交付 |
| `rebuild-target` | 一个要重建的接口 | `dod` 每条必须是以 `rev-` 开头的可机检命令 |

**confidence 派生公式**：`min(grade上限, 0.35 + 0.25 × 独立通道数)`。E1 上限 0.60，E2 0.85，E3 1.00。**"看两遍"不涨分，"换种手段看"才涨分。**

## 三条边界（Always / Ask first / Never）

- **Always**：开单前答五问；每条结论挂 evidence id；交付前跑 `gate`。
- **Ask first**：`--purpose compete-observe`（会强制剔除全部静态节点，只出报告不出实现）；`--allow-forward`（以上游名义代写证据）。
- **Never**：申请 `drm-bypass` / `license-check-bypass` / `certificate-pinning-bypass` / `integrity-check-bypass`；手填 `confidence`；把 `exit 4` 当成 `exit 1` 处理。

## 验收（两条命令，都能失败）

```bash
python scripts/cli.py selftest          # 12 个负例必须全判红，4 个正例必须全判绿
python scripts/e2e_check.py             # 20 项端到端，含 exit 4 / 重复 id / blocking 阻断
```

`selftest` 若有任一负例被判绿，说明**检查器本身失效**，后续所有验收结论一律作废。

## 本技能的失效模式

1. **`unknown` 防得住"忘了写"，防不住"故意不写"**。报告结尾那句"未解清单为空不等于没有未解项"，就是为这个留的。
2. **`compete-observe` 的边界靠路由代码保证**，不靠人。绕过本技能直接调 `rev-static`，它管不到。
3. **`triage` 只读文件头 4 KB**，对打包器套娃（如加壳后再打包）可能误判形态。误判的表现是下游 DAG 跑不通，不是静默出错。
4. **无真沙箱**。它只能拒跑，不能强制隔离。

## 文件

```
rev-core/
├── SKILL.md
├── MANIFEST.json                      sha256 清单（版本锁用）
├── scripts/
│   ├── cli.py                         全部命令
│   └── e2e_check.py                   20 项端到端验收
└── references/
    ├── schema/reva-1.json             四类工件定义 + confidence 表
    └── fixtures/                      12 负例 + 4 正例（selftest 生成）
```
