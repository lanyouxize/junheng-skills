# 插画提示词

## 视觉锚点

一套 PPT 里的插画看起来像一家人，靠的是**同一个主角反复出现**。示例里是"机械手托着 M 图标"，每页只换它周围的道具。

写 `meta.anchor.description` 时遵循三点。

1. 选一个能代表主题的具体物件：产品就用它的应用图标或吉祥物，课程主题可以是一本书、一个地球、一株植物
2. 描述要具体到材质和颜色，例如 "a glossy mint-teal rounded-square app icon with a bold white letter M"
3. 可以加一个动作载体，让不同页面有变化空间，例如 "held by a sleek white robotic hand"

`glyph` 填一个字母，程序化插画会把它画在主瓷砖上。

## 单页提示词公式

make_assets.py 会自动在每条提示词后面拼上风格、色板、构图和负面约束，所以 plan.json 里只写**这页画什么**。

```
{锚点或锚点的一部分} + {和这页内容相关的道具/动作} + {情绪}
```

| 页面内容 | 提示词示例 |
|---|---|
| 封面 | hero shot of {anchor}, floating above a soft round pedestal, small chat bubble and chart badges orbiting around it |
| 是什么 | {anchor} presented alone, simple and iconic, gentle glow |
| 数据增长 | {anchor} next to a rising bar chart with an upward arrow, a few floating download icons |
| 云端电脑 | a friendly cloud-shaped computer inside a transparent protective shield, a small {anchor} badge on it |
| 上手步骤 | a checklist card with a big check mark and a small lock, {anchor} peeking from behind |
| 例句提示词 | a large speech bubble with quote marks, {anchor} typing on it |
| 低风险任务 | {anchor} calmly reading a document with a magnifier |
| 风险提醒 | a gentle caution sign and a closed shop door, {anchor} standing aside, not scary |
| 隐私 | a padlock and a key beside a mailbox, soft protective glow |
| 结尾 | {anchor} waving hello, sparkles around, optimistic |

## 自动拼接的部分（无需手写）

- `Visual style:` 取自 `style.illustration.style_prompt`
- `Color palette:` 取自色板的 primary、primary_dark、accent、tint
- 构图：主体居中、完整可见、四周留白；需要透明底时加 "isolated on a plain pure white background"
- `Do not include:` 取自 `style.illustration.negative`

用 `python3 $S/make_assets.py $W --dry-run` 可以打印最终提示词而不调用接口。

## 透明底

- OpenAI `gpt-image-1` 支持原生透明背景，脚本会自动请求
- 其他模型生成白底图，脚本用 rembg（已安装时）或边缘泛洪去白底，适合扁平插画；写实风格建议装 rembg：`pip install rembg --break-system-packages`

## 程序化兜底

没有配置生图模型时，`fallback` 字段决定兜底插画长什么样。

| scene | 画面 | 适合 |
|---|---|---|
| `tile` | 发光主瓷砖（字母或图标）、轨道、卫星小图标、底座 | 封面、定义页、结尾 |
| `badge` | 圆形大徽章加一个图标 | 概念、原理、警示 |
| `cards` | 叠放的卡片，带列表线条 | 清单、步骤、文档类 |
| `chart` | 柱状图卡片加上升折线 | 数据页 |

兜底插画的小图标默认取该页 `icons`，也可以在 `fallback.icons` 里单独指定。颜色全部来自 style.json，所以换风格后重新生成即可。
