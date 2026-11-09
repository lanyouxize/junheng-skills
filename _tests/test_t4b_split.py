#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T4 推广验收固化：3 个超大技能拆分后能力不得退化。

真不变量（自包含，不依赖工作区临时备份）：
  1. 主体 < 500 行
  2. 「渐进式披露导航（必读）」区块存在
  3. 导航区块恰好列出全部 references（full_table）或指向主体两表+新增附录（index_pointer）
  4. 外置文件存在、行数与首行与逐字外置契约一致（不是空壳、不是改写）
  5. 外置文件头部声明「唯一执行依据」
  6. frontmatter name 未变
  7. 代码围栏闭合
  8. 自指路由 / L0 闸门 / 尾部自检仍留在主体
  9. CRLF 保持

可证伪：FAULTS 把 3 个主体里新增外置文件的路径全局替换成 REMOVED.md
        => 各技能的断言 3 必须失败（只认导航区块/导航段落，全文提及不算）。
"""
import os
import re

import yaml

SKILL = "_t4b_split"  # 横切标签：避免与同名的技能级模块重复计入覆盖率
FENCE = chr(96) * 3
NAV = "## 渐进式披露导航（必读）"

SPECS = [
    {
        "dir": "perfectly-replicate-writing-skills__skillhub",
        "mode": "full_table",
        "name": "perfectly-replicate-writing-skills",
        "nav_files": [
            "7-dimensions-framework.md", "persona-template.md",
            "writing-formulas.md", "phase3-output-templates.md",
            "phase4-5-and-appendix.md",
        ],
        "ext": [
            ("phase3-output-templates.md", 112, "### Phase 3: 输出生成"),
            ("phase4-5-and-appendix.md", 212, "### Phase 4: 双引擎盲测验证"),
        ],
        "must_keep": ["### Phase 1: 双引擎并行分析", "### Phase 2.5", "## 最后"],
        "fault_path": "references/phase3-output-templates.md",
    },
    {
        "dir": "nuwa-skill",
        "mode": "full_table",
        "name": "nuwa-skill",
        "nav_files": [
            "extraction-framework.md", "fidelity-scorecard.md",
            "skill-template.md", "phase1-swarm-templates.md",
            "workflow-and-appendix.md",
        ],
        "ext": [
            ("phase1-swarm-templates.md", 97, "#### Agent prompt模板"),
            ("workflow-and-appendix.md", 204, FENCE + "markdown"),
        ],
        "must_keep": ["### Phase 0: 入口分流", "### Phase 1.5", "## 版本自检（静默）"],
        "fault_path": "references/phase1-swarm-templates.md",
    },
    {
        "dir": "dev-expert",
        "mode": "index_pointer",
        "name": "dev-expert",
        "nav_files": [
            "priority-matrix-and-collaboration.md",
            "project-kickoff-and-faq.md",
        ],
        "ext": [
            ("priority-matrix-and-collaboration.md", 104, "## 子技能优先级矩阵"),
            ("project-kickoff-and-faq.md", 27, "## 项目启动模板"),
        ],
        "must_keep": ["### 专项 reference 映射", "## 子技能索引",
                      "## 执行边界与熔断", "## 长任务断点登记（bg_check）"],
        "fault_path": "references/priority-matrix-and-collaboration.md",
    },
]

# 证伪：三个主体各自把「新增外置文件路径」全局抹掉
FAULTS = {}
for _s in SPECS:
    _p = "../%s/SKILL.md" % _s["dir"]
    FAULTS[_p] = (lambda old: (lambda t: t.replace(old, "references/REMOVED.md")))(
        _s["fault_path"])


def nav_block(sk, mode):
    """只取导航区块：full_table 认表格行；index_pointer 认到下一个 ## 标题。"""
    tail = sk.split(NAV, 1)[-1] if NAV in sk else ""
    if mode == "index_pointer":
        return tail.split("\n## ", 1)[0]
    rows, started = [], False
    for line in tail.splitlines():
        if line.startswith("|"):
            started = True
            rows.append(line)
        elif started and line.strip():
            break
    return "\n".join(rows)


def checks(ctx):
    out = []
    for s in SPECS:
        d = s["dir"]
        rel = "../%s/" % d
        sk = ctx.read(rel + "SKILL.md")
        lines = sk.splitlines()
        tag = "[%s] " % d[:22]

        # 1. 主体行数
        out.append((len(lines) < 500, tag + f"主体 {len(lines)} 行 < 500"))

        # 2. 导航区块存在
        out.append((NAV in sk, tag + "渐进式披露导航区块存在"))

        # 3. 导航覆盖（只认区块内，全文提及不算）
        block = nav_block(sk, s["mode"])
        if s["mode"] == "full_table":
            listed = set(re.findall(r"references/([A-Za-z0-9._-]+\.md)", block))
            expected = set(s["nav_files"])
            miss, extra = sorted(expected - listed), sorted(listed - expected)
            ok = not miss and not extra
            out.append((ok, tag + "导航表恰好列出 %d 个 references" % len(expected)
                        + (f"；缺 {miss}；多 {extra}" if not ok else "")))
        else:
            need = ["专项 reference 映射", "子技能索引"] + [
                "references/" + f for f in s["nav_files"]]
            lack = [x for x in need if x not in block]
            out.append((not lack, tag + "导航指向主体两表 + 2 份新增附录"
                        + (f"；缺 {lack}" if lack else "")))

        # 4 + 5. 外置文件逐字契约
        for fn, n_expected, first in s["ext"]:
            p = rel + "references/" + fn
            if not os.path.isfile(ctx.path(p)):
                out.append((False, tag + f"外置 {fn} 缺失"))
                continue
            body = ctx.read(p)
            bl = body.splitlines()
            out.append((len(bl) == n_expected and bl[4].startswith(first),
                        tag + f"外置 {fn} 行数={len(bl)}(期{n_expected}) 首行匹配"
                        + ("" if len(bl) == n_expected and bl[4].startswith(first)
                           else f" 实得首行={bl[4][:36] if len(bl) > 4 else 'N/A'}")))
            out.append(("唯一执行依据" in body,
                        tag + f"外置 {fn} 声明唯一执行依据"))

        # 6. frontmatter
        try:
            e = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
            fm = yaml.safe_load("\n".join(lines[1:e]))
            ok = isinstance(fm, dict) and fm.get("name") == s["name"]
            out.append((bool(ok), tag + f"frontmatter name={fm.get('name') if isinstance(fm, dict) else '?'}"))
        except Exception as ex:
            out.append((False, tag + "frontmatter 解析失败 " + type(ex).__name__))

        # 7. 围栏闭合
        nf = sum(1 for l in lines if l.lstrip().startswith(FENCE))
        out.append((nf % 2 == 0, tag + f"代码围栏闭合（{nf} 个）"))

        # 8. 自指/闸门/尾部仍在主体
        lack = [k for k in s["must_keep"] if k not in sk]
        out.append((not lack, tag + "关键自指章节仍在主体"
                    + (f"；缺 {lack}" if lack else "")))

        # 9. CRLF（直接从磁盘读字节，不受证伪污染；非证伪目标）
        raw = open(ctx.path(rel + "SKILL.md"), "rb").read()
        out.append((b"\r\n" in raw and raw.count(b"\n") == raw.count(b"\r\n"),
                    tag + "CRLF 全量保持"))
    return out
