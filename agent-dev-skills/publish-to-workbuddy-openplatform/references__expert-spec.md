# 专家包 plugin.json 字段规范（实测通过版）

来源：WorkBuddy 开放平台「发布管理 → 发布专家」上传，经 5 轮迭代实测通过。platform 自动开包后做字段级校验，任何不符直接「解析失败」并给出具体字段名。

## 目录布局（zip 内）

```
.codebuddy-plugin/plugin.json          # 配置入口，必须在此路径
.codebuddy-plugin/avatars/README.md    # 可选说明
agents/vcu-test-expert.md              # 专家主体，zip 根（无 .codebuddy-plugin 前缀）
avatars/vcu-test-expert.png            # 头像，zip 根（无前缀）
README.md                              # 可选
```

> 铁律：plugin.json 在 `.codebuddy-plugin/` 内；agents/、avatars/ 等资源放 **zip 根平级**；字段引用写无前缀路径（`avatars/xxx.png`、`agents/xxx.md`）。

## plugin.json 字段

```jsonc
{
  "name": "vcu-test-expert",                 // kebab-case，全局唯一
  "version": "1.0.0",
  "description": "VCU HIL test-development expert ...",  // 英文长描述
  "author": { "name": "IAMZEN", "email": "chenbing@sam.com" },
  "agents": ["./agents/vcu-test-expert.md"], // 数组，指向 agent 文件
  "expertType": "agent",
  "agentName": "vcu-test-expert",            // 必须与 agents/ 下的 .md 文件名一致
  "displayName": { "en": "VCU HIL Test Expert", "zh": "VCU HIL 测试开发专家" },
  "profession": { "en": "VCU HIL Test Engineer", "zh": "VCU HIL 测试开发工程师" },
  "displayDescription": {
    "en": "Specializes in VCU HIL testing ...",
    "zh": "专注 VCU HIL 测试、Simulink 建模、VeriStand 部署、CAN 信号映射与故障注入，覆盖 MIL/SIL/HIL 全流程验证。"
  },                                             // 中文 40-50 字为宜
  "avatar": "avatars/vcu-test-expert.png",     // zip 根相对路径，真 PNG 必须存在
  "categoryId": "02-Engineering",              // 分类 ID，按平台枚举填
  "defaultInitPrompt": {
    "zh": "你好，我是 VCU HIL 测试开发专家……请问有什么具体需求？",
    "en": "Hi, I am the VCU HIL test expert. Ask me about ..."
  },
  "plugin": "vcu-test-expert",
  "tags": [                                     // 固定 3 个
    { "en": "VCU", "zh": "VCU" },
    { "en": "HIL", "zh": "HIL" },
    { "en": "Simulink", "zh": "Simulink" }
  ],
  "quickPrompts": [                             // 固定 3 个；首项必须与 defaultInitPrompt 字符级一致
    { "zh": "你好，我是 VCU HIL 测试开发专家……请问有什么具体需求？",
      "en": "Hi, I am the VCU HIL test expert. Ask me about ..." },   // == defaultInitPrompt
    { "en": "How to parse VCU_VehSpd from DBC?", "zh": "怎么从 DBC 解析车速信号？" },
    { "en": "How to calculate NEDC torque demand?", "zh": "NEDC 工况的驱动扭矩怎么算？" }
  ]
}
```

## 字段级铁律（平台逐条拦截）

1. `quickPrompts[0].zh` 必须 **字符级等于** `defaultInitPrompt.zh`；`.en` 同理。平台用 `.h` 简写指代 `.zh`。
2. `agentName` 必须等于 `agents/` 下 `.md` 文件名（不含扩展名）。
3. `avatar` 路径在 zip 内必须有真实 PNG（签名 / CRC / IDAT 合法），不能只放 README 占位。
4. `tags` / `quickPrompts` 各固定 3 项。
5. `categoryId` 用平台枚举值（如 `02-Engineering`），不确定时先传一个看平台是否报错。

## Agent MD（agents/vcu-test-expert.md）要求

- frontmatter 仅需 `name` / `description`（与 plugin.json 的 name / displayDescription 同源）
- **不要声明 `tools` 字段**（专家型 Agent 不绑定工具清单，平台按 agent 型处理）
- 正文写专家人设、能力边界、典型问答示例

## 打包命令

```bash
python scripts/pack.py expert --mirror
# 输出 publish/expert.zip + 双备份 Desktop/publish-mirror/expert.zip
# 打印 SHA256，上传前比对
```
