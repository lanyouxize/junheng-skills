#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""humanize.py — 去AI味诊断 + 启发式人化清理（纯标准库，零依赖）。

用法:
  python humanize.py --text "..." [--lang zh-CN|zh-TW|en|ja] [--out report.md]
  python humanize.py --input draft.txt [--lang en] [--out report.md]
  cat draft.txt | python humanize.py --lang zh-CN

输出 Markdown：AI腔评分 + 套路清单 + 人化清单 + 启发式改写稿。
说明：脚本只做"机械套路"检测与初步清理；真正的语气/节奏人化由 AI 或人执行。
"""
import argparse
import os
import re
import sys

# 各语言高频 AI 套路词/短语
TELLS = {
    "zh-CN": [
        ("套路开场", ["在当今", "在当下", "随着人工智能", "在快节奏的", "毋庸置疑", "值得注意的是", "需要指出的是"]),
        ("总结套话", ["总而言之", "综上所述", "总的来说", "一言以蔽之", "不难发现"]),
        ("虚词滥用", ["可以说", "实际上", "事实上", "某种程度上", "在一定程度上", "从根本上"]),
        ("机械连接", ["首先", "其次", "然后", "最后", "一方面", "另一方面"]),
        ("营销黑话", ["赋能", "闭环", "抓手", "组合拳", "底层逻辑", "认知", "颗粒度", "对齐", "心智"]),
    ],
    "en": [
        ("Stock openers", ["in today's", "in the world of", "it is worth noting", "it's worth noting",
                            "needless to say", "undoubtedly", "moreover", "furthermore", "delve"]),
        ("Filler", ["actually", "basically", "simply put", "at the end of the day",
                    "when it comes to", "leverage", "utilize", "in order to"]),
        ("Robotic transitions", ["firstly", "secondly", "lastly", "in conclusion",
                                  "to summarize", "overall"]),
    ],
    "ja": [
        ("決まり文句", ["言うまでもなく", "総じて", "現代において", "〜において"]),
        ("機械接続", ["まず", "次に", "最後に", "一方で", "他方で"]),
    ],
}


def detect(text, lang):
    tells = TELLS.get(lang, TELLS["zh-CN"])
    if lang == "zh-TW":
        tells = TELLS["zh-CN"]
    hits = []
    for cat, words in tells:
        for w in words:
            n = text.count(w)
            if n:
                hits.append((cat, w, n))
    return hits


def score(hits, text):
    raw = sum(n for _, _, n in hits)
    length = max(1, len(text))
    density = raw / (length / 100.0)
    return min(100, int(density * 20 + raw * 4))


def heuristic_rewrite(text, lang):
    t = text
    if lang.startswith("zh"):
        for w in ["值得注意的是，", "值得注意的是", "需要指出的是，", "需要指出的是",
                  "毋庸置疑，", "可以说，", "可以说", "事实上，", "事实上", "实际上，", "实际上",
                  "总而言之，", "总而言之", "综上所述，", "综上所述", "总的来说，", "总的来说"]:
            t = t.replace(w, "")
        t = re.sub(r"(首先|其次|然后|最后|一方面|另一方面)[，,]?", "", t)
        t = re.sub(r"\s+", "", t)
    else:
        for w in ["It is worth noting that ", "It's worth noting that ", "Needless to say, ",
                  "Moreover, ", "Furthermore, ", "In conclusion, ", "To summarize, ", "Overall, "]:
            t = t.replace(w, "")
        t = re.sub(r"\s+", " ", t).strip()
    return t


PLAYBOOK = [
    "砍掉套路开场与总结套话，第一句直接给信息或画面。",
    "把'首先/其次/最后'的机械顺序改成按重要性或自然过渡。",
    "每 3-4 句换一种句式（长短交错），别全用并列。",
    "虚词（可以说/事实上/实际上）能删就删，信息密度拉满。",
    "少用项目符号堆砌，关键处改成分段口语。",
    "加一个具体细节/个人视角/真实例子，破模板感。",
    "结尾别喊口号，给一句实在的下一步。",
]


def build_report(text, lang):
    hits = detect(text, lang)
    sc = score(hits, text)
    rewrite = heuristic_rewrite(text, lang)
    cats = {}
    for cat, w, n in hits:
        cats.setdefault(cat, []).append(f"{w}(×{n})")
    L = []
    L.append(f"# 去AI味诊断报告（{lang}）")
    L.append("")
    L.append(f"**AI腔评分：{sc}/100**  （越高越像机器写的）")
    L.append("")
    if cats:
        L.append("## 检测到的AI套路")
        for cat, ws in cats.items():
            L.append(f"- **{cat}**：{', '.join(sorted(set(ws)))}")
        L.append("")
    else:
        L.append("未检测到明显 AI 套路，文字已较自然。")
        L.append("")
    L.append("## 人化清单（交给 AI/自己逐条执行）")
    for i, p in enumerate(PLAYBOOK, 1):
        L.append(f"{i}. {p}")
    L.append("")
    L.append("## 启发式改写稿（机械清理版，仍需人工/AI 润色语气）")
    L.append("> " + rewrite.replace("\n", "\n> "))
    L.append("")
    L.append("> 合规提示：本工具仅做表达层面的自然化，请按需披露 AI 辅助，并遵守所在平台/机构的原创与诚信规范。")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="去AI味诊断与人化清理")
    ap.add_argument("--text", default=None, help="待分析文本")
    ap.add_argument("--input", default=None, help="原文文件路径")
    ap.add_argument("--lang", default="zh-CN", help="zh-CN/zh-TW/en/ja")
    ap.add_argument("--out", default=None, help="输出 markdown 路径")
    args = ap.parse_args()

    if args.input:
        with open(args.input, encoding="utf-8") as f:
            text = f.read()
    elif args.text:
        text = args.text
    else:
        text = sys.stdin.read()

    report = build_report(text, args.lang)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"written: {args.out}  ({len(report)} bytes)")
    else:
        print(report)


if __name__ == "__main__":
    main()
