# AI 腔特征库（中英日）

"AI 味"不是某一句话，而是一组可识别的**套路信号**。诊断时按类别排查，命中越多越像机器写的。

## 中文（zh-CN / zh-TW 通用）
| 类别 | 典型套路 |
|---|---|
| 套路开场 | 在当今…、在当下、随着人工智能的发展、在快节奏的…、毋庸置疑、值得注意的是、需要指出的是 |
| 总结套话 | 总而言之、综上所述、总的来说、一言以蔽之、不难发现 |
| 虚词滥用 | 可以说、实际上、事实上、某种程度上、在一定程度上、从根本上 |
| 机械连接 | 首先…其次…然后…最后、一方面…另一方面 |
| 营销黑话 | 赋能、闭环、抓手、组合拳、底层逻辑、认知、颗粒度、对齐、心智 |
| 标点/结构 | 滥用分号、整齐的三段排比、每段都以"首先"开头、emoji 过度堆砌 |

## 英文（en）
| 类别 | 典型套路 |
|---|---|
| 套路开场 | In today's world / In the rapidly evolving landscape / It is worth noting / Needless to say / Undoubtedly |
| 填充词 | Actually / Basically / Simply put / At the end of the day / When it comes to / Leverage / Utilize / In order to |
| 机械连接 | Firstly / Secondly / Lastly / In conclusion / To summarize / Overall |
| 用词 | Delve / Navigating / Unlock / Game-changer / Testament to / Robust / Seamless |
| 结构 | 每段同构、过度使用 em-dash（—）、bullet 列表堆砌 |

## 日文（ja）
| 类别 | 典型套路 |
|---|---|
| 決まり文句 | 〜において、〜に関して言えば、言うまでもなく、総じて言えば、現代において |
| 機械接続 | まず、次に、最後に、一方で、他方で |
| 硬い表現 | 〜である（连体形叠加）、ですます 调过度统一、漢語名詞連発（〜性、〜的） |

## 怎么用
把原文丢进 `scripts/humanize.py` —— 它会按语言打出命中清单与 AI 腔评分（0–100，越高越机器）。人工再对照上表补漏（脚本只覆盖高频词，长难句节奏得靠人/AI 判断）。
