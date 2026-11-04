# 从参考图读出 style.json

参考图的作用是提供"气质"，内容一概不用。先跑 `extract_style.py` 拿到颜色聚类，再亲自看图补全。

## 看图时回答这几个问题

1. 主色是什么？通常是面积中等、饱和度最高的那个色相。它要能当标题色和实心卡片底色用，所以和白色的对比度至少 3.4，不够就加深（脚本已自动处理）。
2. 深色版主色 `primary_dark` 用于大标题和深色结尾页，和白色对比度至少 7。
3. 强调色 `accent` 取参考图里最跳的点缀色（示例里是那块黄色笔刷标签），用于笔刷高亮、插画点缀、警示图标底色。
4. 背景渐变 `bg_top` / `bg_bottom` 取参考图顶部和底部的大面积浅色。背景务必够浅，正文 `text` 放上去对比度要 7 以上。
5. 正文色 `text` 用接近黑的主色相深色，比纯黑更协调。`muted` 是说明文字，和背景对比度至少 4.5。
6. `tint` 是主色的极浅版，用于图标底圈和强调卡片；`line` 比 tint 略深，用于卡片描边。
7. 形状语言：参考图圆润就把 `shape.radius` 调到 0.18 到 0.24，偏硬朗的商务风用 0.06 到 0.1，卡片有无投影看参考图有没有柔和阴影。
8. 背景装饰 `background.decor` 按参考图里看到的母题选，封面 `cover_decor` 可以比内容页更丰富。

   | 参考图里看到的 | 选 | 相关参数 |
   |---|---|---|
   | 柔光大色斑、光点、淡色弧线 | `blobs` `bokeh` `arcs` | |
   | 云朵、底部起伏的山丘 | `clouds` `hills` | |
   | 点阵网格、颗粒质感 | `grid` `grain` | |
   | 两种颜色的大片柔雾渐变 | `mist` | 用 primary 和 accent 两色 |
   | 同心波纹线、声波一样的细线圈 | `rings` | `line_color`，默认 accent |
   | 流动的丝线、金色光带 | `silk` | `line_color`，默认 accent |
   | 撕纸边、笔刷边的深色色带 | `torn` | `band_color`，默认 primary_dark |
   | 红黄蓝绿的圆、半圆、三角、方块 | `geo` | `geo_colors` 颜色列表 |
   | 整块纯色条 | `band` | `band_color`，默认 primary |
   | 底部一整片扁平风景（风车、房子、山丘、树、太阳能板） | `scene` | 只画在封面和结尾；`scene_teal`、`scene_dark`、`scene_sky` 调颜色；封面配 `cover_center` 版式 |

   母题只选一到两个。参考图靠照片撑画面时，这里只能做出配色和版式，交付时要说清楚。
9. 其他装饰 `decor`：`leaf` 页眉叶片（自然、环保、清新类风格才开），`brush` 笔刷高亮（手绘感、活泼风格），`title_mark` 标题下小横条，`sparkles` 插画里的星光，`closing_dark` 结尾页用深色主色底。
   章节编号的样子由 `number_style` 决定，目录页和章节页共用，可选 `plain`（大号数字）、`badge`（实心圆）、`ring`（空心圆）、`block`（实心方块）、`diamond`（菱形描边）。
   章节页没有插画时，右侧会铺一个超大的淡色章节号，`number_watermark: false` 关掉，`watermark_color` 调颜色，如 `primary@0.1`。
   截图外框由 `shot_frame` 决定，`window`（带三个圆点的窄标题栏，默认）、`card`（只有卡片）、`none`（不加框）。单页也可以在 deck.json 里用 `frame` 覆盖。
10. 字体：参考图标题是宋体、衬线英文的（高端、文艺、国风类常见），`heading_ea` 写 `Source Han Serif SC`，`heading_latin` 和 `display_latin` 写 `Georgia`，正文仍用黑体。对方电脑没装思源宋体时会被替换，交付时提醒一句。
11. 插画风格 `illustration.style_prompt` 用英文写，描述画法、材质、光线、色调、情绪。例如 "clean flat vector illustration with soft gradients, mint green and teal tones, rounded friendly shapes, light airy mood, subtle soft shadows"。

## style.json 完整字段

```json
{
  "name": "mint-eco-flat",
  "reference": "ref.png",
  "palette": {
    "primary": "17806D", "primary_dark": "0F5A4D", "accent": "F5D76E",
    "bg_top": "C3EDDB", "bg_bottom": "F4FBF8", "surface": "FFFFFF",
    "tint": "DDF3EA", "text": "1E3A33", "muted": "50655E", "on_primary": "FFFFFF", "line": "CDE8DD"
  },
  "fonts": {"heading_ea": "Microsoft YaHei", "body_ea": "Microsoft YaHei",
            "heading_latin": "Arial", "body_latin": "Arial", "display_latin": "Arial Black"},
  "shape": {"radius": 0.18, "shadow": true, "card_alpha": 0.88},
  "decor": {"header": true, "leaf": true, "brush": true, "brush_color": "accent",
            "title_mark": true, "sparkles": true, "closing_dark": true},
  "background": {"decor": ["blobs", "bokeh", "arcs"],
                 "cover_decor": ["blobs", "clouds", "hills", "bokeh"],
                 "closing_decor": ["blobs", "bokeh", "arcs"]},
  "illustration": {"style_prompt": "…", "negative": "text, letters, words, watermark, logo, …"},
  "emphasis_color": "primary"
}
```

`emphasis_color` 是正文里 `**加粗**` 片段的颜色。

另有两个角色由脚本自动推导，一般不用写。`strong` 是大标题色，浅色背景下等于 primary_dark，深色背景下是提亮的主色；
`highlight` 是彩色文字色（大数字、侧栏标题），浅色背景下等于 primary，深色背景下是提亮的主色。需要时也可以在 palette 里显式指定覆盖。
`card_alpha` 是白色卡片的不透明度，背景越花越要调高。

## 参考图是深色时

深色参考图（科技风、夜景）照样能做，但要注意两点。

- `bg_top` / `bg_bottom` 用深色，`text` 改成近白色，`muted` 用浅灰，`surface` 用比背景略亮的深色，`card_alpha` 0.7 左右
- `on_primary` 看主色深浅决定黑或白，主色和 on_primary 的对比度要到 4.5，否则实心卡片里的小字会被 QA 报警
- `decor.brush_color` 改成 `primary`，浅色笔刷在深底上发灰；`leaf` 通常关掉
- `closing_dark` 可以关掉，结尾页沿用深色背景
- 程序化插画的瓷砖是浅色的，在深色背景上反而醒目，可以保留

## 预设风格

用户没给参考图时，从 `references/style-*.json` 的十四套预设里挑。

- 原有六套偏柔和插画风：薄荷清新、商务蓝、暖橙活力、深色科技、雾紫柔和、纸感手记
- 六套靠装饰母题和字体撑画面：黑金述职、几何色块、钴蓝字体、黑灰荧绿、蓝粉柔雾、蓝线发布
- 两套杂志编辑风，几乎不用装饰：墨水杂志（宋体、纸色、细线）、硬边网格（直角、黑白加一个信号橙）

`index.json` 按质感、情绪、字体感觉、密度四个维度打了标签，写了适合和不适合的场景，还有一个 `imagery` 标签说明这套风格靠什么撑画面。没配生图模型时，`--auto` 不会推荐 `photo` 类风格，`illustration` 类会往后排。
`style_previews.py --auto` 会按素材关键词挑出稳妥、大胆、意外三套，用用户自己的内容出样张；`--apply <id>` 把选中的预设写成 style.json。
预设里的 `rules` 是这套风格的硬规则，手工调版式时也要遵守；`illustration.fallback_look` 为 flat 时，程序化插画改用描边贴纸风格。
另有两个可选键。`prefer_layouts` 让某个页型优先用某个版式，比如 `{"toc": "toc_row"}`；`illustration.skip_layouts` 列出不放插画的版式，靠字体撑画面的风格常把封面、章节页、结尾页放进去。

### 排版规矩字段

这些字段决定"怎么用"颜色和字，从参考图里读出来，或者按风格气质定。

| 字段 | 说明 |
|---|---|
| `palette.secondary` / `palette.subtle` | 文字第二、第四级灰，不写会自动推导。四级依次是正文 text、次要 secondary、说明 muted、元信息 subtle（页码、来源、页脚） |
| `shape.depth` | 卡片层次：flat 只有底色，ring 一条细边，whisper 极淡晕影，shadow 经典投影。参考图卡片没有阴影就别用 shadow |
| `decor.bullet` | 列表符号：icon、dash、number |
| `decor.emphasis` | 标题强调词：color 换色，serif 换色加换宋体 |
| `title_emphasis_color` | 标题强调词的颜色，默认 highlight |
| `decor.chrome` | standard 或 editorial（杂志式页眉页脚） |
| `type_scale` | 自定字号阶梯，false 关闭吸附 |
| `accent_max` | 强调色上限，默认 `{"uses": 3, "area": 0.08}`，QA 超了会警告 |
| `forbid` | 这套风格的禁区，QA 会检查：`pure_white` 不用纯白底，`pure_black` 不用纯黑，`shadow` 不用阴影，`radius_over` 圆角上限 |

从参考图判断的经验：纸感、杂志感的参考图通常是 ring 加 dash 加 editorial；科技发布会、深色风格多是 ring 加 number；柔和插画风保留 shadow 或 whisper 加 icon。

## 常见误区

- 把参考图里面积最大的浅色当主色，结果标题发灰。主色看饱和度，不看面积。
- 强调色用得太多。accent 只出现在笔刷、少量图标底圈和插画点缀上。
- 参考图有 LOGO、具体插画、具体文字，把它们当成要复刻的元素。只提取风格。
