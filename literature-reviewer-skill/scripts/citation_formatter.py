#!/usr/bin/env python3
"""
引用格式化工具

支持 GB/T 7714-2015 格式

著者录入规范（canonical input）
--------------------------------
英文著者一律采用「姓 + 名缩写」形式，且缩写后不加缩写点，例如 ``"Smith J"``、``"LeCun Y"``。
本模块会归一无歧义的其它写法：:

    "Smith, John"  -> "Smith J"     # 逗号式
    "Smith, J."    -> "Smith J"     # 逗号 + 缩写点
    "Y LeCun"      -> "LeCun Y"     # 缩写在前式
    "Smith J"      -> "Smith J"     # 已是规范形式，原样保留

著录规则（依 references/gb-t-7714-2015.md 「作者著录规则」）
----------------------------------------------------------
* 3 人以内：全部列出，用逗号分隔
* 超过 3 人：只列前 3 人，中文加 ``等``、英文加 ``et al.``
"""

import sys
from typing import Dict, List, Optional

#: 超过该人数即触发「只列前 3 人 + 等/et al.」规则
MAX_LISTED_AUTHORS = 3

#: 截断后缀（依语言区分）
TRUNCATION_SUFFIX = {"zh": "等", "en": "et al."}

#: 文献类型标识（GB/T 7714-2015 表 1；``PP`` 为 2025 版草案新增的预印本）
DOC_TYPES = {
    "M": "专著",
    "C": "会议录、论文集",
    "N": "报纸",
    "J": "期刊",
    "D": "学位论文",
    "R": "报告",
    "S": "标准",
    "P": "专利",
    "G": "汇编",
    "A": "档案",
    "Z": "其他",
    "DB": "数据库",
    "CP": "计算机程序",
    "EB": "电子公告",
    "PP": "预印本",
}

#: 电子资源类：载体标识 ``/OL`` 必须标出（GB/T 7714-2015 8.8）
ELECTRONIC_DOC_TYPES = {"DB", "CP", "EB", "PP"}

#: 专著类：著录项为「出版地: 出版者, 出版年: 页码」而非「刊名, 年, 卷(期): 页」
BOOK_DOC_TYPES = {"M", "G", "D", "R", "S", "P", "A", "Z"}

#: doc_type 缺省值（GB/T 7714 中期刊为绝大多数，且与本模块历史行为一致）
DEFAULT_DOC_TYPE = "J"

#: 缺省告警只报一次，避免 47 条文献刷屏
_warned_missing_doc_type = False


def _clean_str(value) -> str:
    """把 ``None`` / 非字符串安全归一为去首尾空白的字符串（P0-4）。"""
    if value is None:
        return ""
    if not isinstance(value, str):
        return str(value).strip()
    return value.strip()


def resolve_doc_type(paper: Dict, default: str = DEFAULT_DOC_TYPE) -> str:
    """解析条目的文献类型标识（P0-1）。

    取值优先级：``doc_type`` > ``document_type`` > ``default``。支持 ``"[M]"``、
    ``"m"``、``"J/OL"`` 等写法（自动去括号、转大写、取斜杠前的类型码）。

    缺省时回落 ``default`` 并**只在进程内告警一次**（不静默，也不刷屏）；
    显式给了但不在 `DOC_TYPES` 内则抛 ``ValueError``（失败大声报错，
    避免把错标一路带进交付物）。
    """
    global _warned_missing_doc_type

    raw = paper.get("doc_type")
    if raw in (None, ""):
        raw = paper.get("document_type")

    code = _clean_str(raw).strip("[]").upper()
    if not code:
        if not _warned_missing_doc_type:
            _warned_missing_doc_type = True
            print(
                "[citation_formatter] 警告：条目 %r 未指定 doc_type，按 [%s] 著录；"
                "同一进程内不再重复提示。请补 doc_type（见 DOC_TYPES）。"
                % (paper.get("id") or "<无 id>", default),
                file=sys.stderr,
            )
        return default

    if "/" in code:  # 兼容 "J/OL" 写法，载体标识交给 resolve_carrier
        code = code.split("/", 1)[0].strip()

    if code not in DOC_TYPES:
        raise ValueError(
            "非法的 doc_type=%r（条目 %r）；允许值：%s"
            % (raw, paper.get("id") or "<无 id>", ", ".join(sorted(DOC_TYPES)))
        )
    return code


def resolve_carrier(paper: Dict, doc_type: str) -> str:
    """解析载体标识（``OL`` 或空串）。

    显式 ``carrier`` 优先；电子资源类（``EB``/``DB``/``CP``/``PP``）强制 ``OL``。
    期刊/专著类**不**因存在 ``source_url`` 就自动加 ``/OL`` —— 那是「在线获取」
    与「在线发布」的差别，自动推断会把 45 条合规的 ``[J]`` 批量改成 ``[J/OL]``，
    故按「不猜测」原则留给上游显式声明。
    """
    raw = _clean_str(paper.get("carrier")).strip("/").upper()
    if raw:
        return raw
    return "OL" if doc_type in ELECTRONIC_DOC_TYPES else ""


def _vol_issue_pages(volume: str, issue: str, pages: str) -> str:
    """拼「卷(期): 页」/「页」/「卷」等片段，缺项自动省略。"""
    volume, issue, pages = _clean_str(volume), _clean_str(issue), _clean_str(pages)
    if volume:
        out = volume
        if issue:
            out += f"({issue})"
        if pages:
            out += f": {pages}"
        return out
    return pages


def _book_source(paper: Dict) -> str:
    """专著类出处：「出版地: 出版者」，缺出版者时回落 ``journal`` 字段。"""
    place = _clean_str(paper.get("place"))
    publisher = _clean_str(paper.get("publisher")) or _clean_str(paper.get("journal"))
    if place and publisher:
        return f"{place}: {publisher}"
    return publisher or place


def _url_is_doi(url: str, doi: str) -> bool:
    """判断 URL 是否只是该 DOI 的解析地址（避免 ``DOI:`` 与 URL 重复著录）。"""
    u, d = url.strip().lower(), doi.strip().lower()
    if not u or not d:
        return False
    for prefix in ("https://doi.org/", "http://doi.org/", "doi.org/", "doi:"):
        if u.startswith(prefix):
            u = u[len(prefix):]
    return u == d


def _is_initial_token(token: str) -> bool:
    """判断单个 token 是否为「名缩写」（如 ``J`` / ``J.`` / ``RG``）。

    规则：字母数 ≤ 2 且全大写。``Li`` / ``Smith`` 这类词不算缩写。
    """
    letters = "".join(ch for ch in token if ch.isalpha())
    return bool(letters) and len(letters) <= 2 and letters.isupper()


def _to_initials(tokens: List[str]) -> str:
    """把一组「名」token 归并为连续缩写串（不加缩写点）。

    - 已是缩写（``J.`` / ``RG``）→ 去点后原样
    - 完整名字（``John``）→ 取首字母
    """
    out: List[str] = []
    for token in tokens:
        letters = "".join(ch for ch in token if ch.isalpha())
        if not letters:
            continue
        if _is_initial_token(token):
            out.append(letters.upper())
        else:
            out.append(letters[0].upper())
    return "".join(out)


def format_author_name(name: str, lang: str = "en") -> str:
    """格式化单个作者姓名。

    英文规范形式为「姓 + 名缩写」（如 ``Smith J``）；本函数会归一逗号式与
    缩写在前式，其余情况原样保留（判定有歧义时不猜测 —— 例如 ``John Smith``
    与中文拼音 ``Li Wei`` 无法可靠区分，一律保留，由上游按规范录入）。

    Args:
        name: 作者姓名
        lang: 语言 (zh/en)

    Returns:
        格式化后的作者名
    """
    if not name:
        return ""
    if not isinstance(name, str):
        raise TypeError("作者姓名必须是字符串，收到 %s：%r" % (type(name).__name__, name))

    if lang == "zh":
        # 中文：保持原样
        return name.strip()

    raw = " ".join(name.split())
    if not raw:
        return ""

    # 形式一：逗号式 —— "Smith, John" / "Smith, J."
    if "," in raw:
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        if not parts:
            return ""
        if len(parts) == 1:
            return parts[0]
        surname = parts[0]
        initials = _to_initials(parts[1:])
        return f"{surname} {initials}".strip()

    tokens = raw.split()

    # 形式二：缩写在前 —— "Y LeCun" / "A Vaswani"
    if (
        len(tokens) >= 2
        and all(_is_initial_token(t) for t in tokens[:-1])
        and not _is_initial_token(tokens[-1])
    ):
        surname = tokens[-1]
        initials = _to_initials(tokens[:-1])
        return f"{surname} {initials}".strip()

    # 形式三：已是「姓 + 名缩写」或存在歧义 —— 原样保留
    return raw


def format_authors(authors: List[str], lang: str = "en") -> str:
    """格式化作者列表（GB/T 7714-2015）。

    3 人以内全部列出、逗号分隔；超过 3 人只列前 3 人，中文加 ``等``、
    英文加 ``et al.``（依 references/gb-t-7714-2015.md）。

    Args:
        authors: 作者列表；误传字符串时按**单作者**处理（P0-3，不再逐字符迭代）
        lang: 语言

    Returns:
        格式化后的作者字符串

    Raises:
        TypeError: ``authors`` 既不是字符串也不是可迭代的姓名序列
    """
    if not authors:
        return ""

    if isinstance(authors, str):
        authors = [authors]
    try:
        items = list(authors)
    except TypeError:
        raise TypeError(
            "authors 必须是字符串或姓名序列，收到 %s：%r" % (type(authors).__name__, authors)
        ) from None

    formatted = [format_author_name(_clean_str(a), lang) for a in items]
    formatted = [f for f in formatted if f]
    if not formatted:
        return ""

    if len(formatted) > MAX_LISTED_AUTHORS:
        head = formatted[:MAX_LISTED_AUTHORS]
        suffix = TRUNCATION_SUFFIX.get(lang, TRUNCATION_SUFFIX["en"])
        return ", ".join(head) + ", " + suffix

    # 3 人以内：全部列出，逗号分隔
    return ", ".join(formatted)


def format_citation_gb7714(paper: Dict, index: str = "") -> str:
    """
    格式化为 GB/T 7714-2015 格式

    文献类型标识由 ``paper["doc_type"]`` 决定（P0-1）：期刊 ``[J]``、专著/书籍章节
    ``[M]``、会议录 ``[C]``、预印本 ``[PP/OL]``…… 未指定时回落 ``[J]`` 并告警一次。
    载体标识 ``/OL`` 见 `resolve_carrier`。

    Args:
        paper: 文献字典
        index: 文献编号 (如 C1, E1)

    Returns:
        GB/T 7714-2015 格式的引文

    Raises:
        ValueError: ``doc_type`` 非法（避免错标一路带进交付物）
    """
    lang = _clean_str(paper.get("language")) or "en"
    title = _clean_str(paper.get("title"))
    journal = _clean_str(paper.get("journal"))
    year = _clean_str(paper.get("year"))
    pages = _clean_str(paper.get("pages"))
    doi = _clean_str(paper.get("doi"))
    url = _clean_str(paper.get("source_url")) or _clean_str(paper.get("url"))
    access_date = _clean_str(paper.get("access_date"))

    doc_type = resolve_doc_type(paper)
    carrier = resolve_carrier(paper, doc_type)
    marker = f"[{doc_type}/{carrier}]" if carrier else f"[{doc_type}]"

    # 格式化作者
    author_str = format_authors(paper.get("authors", []), lang)

    # 作者段与题名之间的分隔：
    # 英文「et al.」自带句点，此时仅需一个空格，避免双句点（"et al.. Title"）；
    # 中文「等」不含句点，仍按常规补 ". "（"张三, 李四, 王五, 等. 题名"）。
    if not author_str:
        author_sep = ""
    elif author_str.endswith("et al."):
        author_sep = " "
    else:
        author_sep = ". "

    # 题名 + 类型标识（含载体）
    citation = f"[{index}] {author_str}{author_sep}{title}{marker}"

    if doc_type in BOOK_DOC_TYPES:
        # 专著类：题名[M]//专著题名. 出版地: 出版者, 出版年: 页码
        # book_title 存在时为「析出文献」（书籍章节），按 GB/T 7714-2015 用 "//" 引出专著题名
        book_title = _clean_str(paper.get("book_title"))
        if book_title:
            citation += f"//{book_title}"
        source = _book_source(paper) or (journal if not book_title else "")
        if source:
            citation += f". {source}"
        if year:
            citation += f", {year}" if source else f". {year}"
        if pages:
            citation += f": {pages}"
    else:
        # 期刊/会议录类：刊名, 年, 卷(期): 页
        vol_issue = _vol_issue_pages(paper.get("volume", ""), paper.get("issue", ""), pages)
        if journal:
            citation += f". {journal}"
        if year:
            citation += f", {year}" if journal else f". {year}"
        if vol_issue:
            citation += f", {vol_issue}" if journal else f". {vol_issue}"
        if doc_type in ELECTRONIC_DOC_TYPES:
            if access_date:
                citation += f". [引用日期: {access_date}]"
            if url and not _url_is_doi(url, doi):
                citation += f". {url}"

    if doi:
        citation += f". DOI:{doi}"
    citation += "."

    return citation


def format_citation_list(papers: List[Dict], prefix: str = "E") -> List[str]:
    """
    格式化文献列表
    
    Args:
        papers: 文献列表
        prefix: 编号前缀 (C/E)
    
    Returns:
        格式化后的引文列表
    """
    citations = []
    for i, paper in enumerate(papers, 1):
        index = f"{prefix}{i}"
        citation = format_citation_gb7714(paper, index)
        citations.append(citation)
    
    return citations


def generate_reference_md(papers_zh: List[Dict], papers_en: List[Dict]) -> str:
    """
    生成参考文献 Markdown 文档
    
    Args:
        papers_zh: 中文文献列表
        papers_en: 英文文献列表
    
    Returns:
        Markdown 格式的参考文献
    """
    lines = ["# 参考文献\n"]
    
    # 中文文献
    if papers_zh:
        lines.append("## 中文文献\n")
        for i, paper in enumerate(papers_zh, 1):
            citation = format_citation_gb7714(paper, f"C{i}")
            lines.append(f"{citation}\n")
        lines.append("")
    
    # 英文文献
    if papers_en:
        lines.append("## 英文文献\n")
        for i, paper in enumerate(papers_en, 1):
            citation = format_citation_gb7714(paper, f"E{i}")
            lines.append(f"{citation}\n")
        lines.append("")
    
    return "\n".join(lines)


if __name__ == "__main__":
    # 测试示例 —— 覆盖 GB/T 7714-2015 著者著录的四种情形
    cases = [
        ("中文·3人", {
            "id": "C1",
            "title": "基于深度学习的医学图像诊断研究",
            "authors": ["张三", "李四", "王五"],
            "journal": "计算机学报",
            "year": 2023, "volume": "46", "issue": "5", "pages": "1023-1035",
            "doi": "10.xxxx", "language": "zh",
        }),
        ("中文·超3人", {
            "id": "C2",
            "title": "样例题名",
            "authors": ["张三", "李四", "王五", "赵六"],
            "journal": "计算机学报",
            "year": 2023, "volume": "46", "issue": "5", "pages": "1-9",
            "doi": "", "language": "zh",
        }),
        ("英文·3人", {
            "id": "E1",
            "title": "Deep learning for medical image analysis",
            "authors": ["Smith J", "Johnson K", "Lee M"],
            "journal": "Nature Medicine",
            "year": 2022, "volume": "28", "issue": "8", "pages": "1500-1510",
            "doi": "10.1038/s41591-022-01900-0", "language": "en",
        }),
        ("英文·超3人", {
            "id": "E2",
            "title": "Deep Learning for Educational Data Mining: A Survey",
            "authors": ["Chen X", "Li Y", "Liu Z", "Wang Q"],
            "journal": "IEEE Transactions on Learning Technologies",
            "year": 2023, "volume": "16", "issue": "2", "pages": "234-248",
            "doi": "10.1109/TLT.2023.1234567", "language": "en",
        }),
    ]

    for label, paper in cases:
        print(f"{label}:")
        print(format_citation_gb7714(paper, paper["id"]))
        print()

    # P0-1 回归样例：类型标识不再硬编码 [J]
    typed_cases = [
        ("预印本（Zenodo，应 [PP/OL]）", {
            "id": "E1", "doc_type": "PP",
            "title": "Effect of dietary fibre on feline hairball expulsion",
            "authors": ["Smith J"], "year": 2023,
            "source_url": "https://zenodo.org/record/1234567",
            "access_date": "2026-10-18", "language": "en",
        }),
        ("书籍章节（IntechOpen，应 [M]）", {
            "id": "E17", "doc_type": "M",
            "title": "Grasses and Grassland - New Perspectives",
            "authors": ["Dann J R"], "journal": "IntechOpen",
            "place": "London", "publisher": "IntechOpen",
            "year": 2021, "pages": "1-18", "language": "en",
        }),
        ("期刊增刊会议摘要（应 [J]，可接受）", {
            "id": "E32", "doc_type": "J",
            "title": "Hairball control with Miscanthus grass",
            "authors": ["Dann J R"], "journal": "J Anim Sci",
            "year": 2017, "volume": "95", "issue": "suppl_4", "pages": "236",
            "doi": "10.2527/asasann.2017.236", "language": "en",
        }),
    ]
    print("文献类型标识（P0-1）:")
    for label, paper in typed_cases:
        print(f"  {label}:")
        print(f"    {format_citation_gb7714(paper, paper['id'])}")
    print()

    print("著者归一化（无歧义写法）:")
    for raw, lang in [
        ("Smith, John", "en"),
        ("Smith, J.", "en"),
        ("Y LeCun", "en"),
        ("Smith J", "en"),
        ("Li Wei", "en"),          # 有歧义 -> 原样保留，不猜测
    ]:
        print(f"  {raw!r:16} -> {format_author_name(raw, lang)!r}")
