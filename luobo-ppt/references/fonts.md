# 字体

PPT 里的字体由打开它的电脑渲染，字体没装就会被替换，所以选字体首先看兼容。

## 默认配置

| 角色 | 中文 | 西文 | 说明 |
|---|---|---|---|
| heading | Microsoft YaHei 微软雅黑 | Arial | Windows 自带，WPS 也有 |
| body | Microsoft YaHei | Arial | 同上 |
| display | 跟随 heading | Arial Black | 封面大标题、大数字，几何感强 |

build_deck.py 会同时写入西文字体（latin）和中文字体（ea），PowerPoint 和 WPS 都会按字符自动选用。

## 可选替换

| 风格 | 中文 | 西文 | 注意 |
|---|---|---|---|
| 苹果用户多 | PingFang SC | Helvetica Neue | Windows 上会回退 |
| 免费可商用、想更精致 | 思源黑体 Source Han Sans SC / 阿里巴巴普惠体 / HarmonyOS Sans SC | Montserrat | 需要对方电脑安装，交付时提醒 |
| 正式、文气 | 思源宋体 Source Han Serif SC | Georgia | 标题用宋体，正文仍用黑体 |

预设里黑金述职、蓝粉柔雾两套用的就是这组宋体标题。预览环境会把思源宋体、华文中宋、宋体这些名字映射到 Noto Serif CJK，所以预览看到的就是衬线效果；对方电脑没装思源宋体时会退回系统字体，交付时提醒安装，或者把 heading_ea 换成对方已有的宋体。

## 预览与实际的差别

云端环境没有微软雅黑，LibreOffice 预览时用思源黑体（Noto Sans CJK）替代，中文字宽基本一致，西文略有差异。
版式的字号计算和 QA 溢出检查都按思源黑体测量，并留了约 3% 余量。
用户反馈在自己电脑上有个别文字换行不同，通常是西文字体差异，微调那一页的字号即可。
