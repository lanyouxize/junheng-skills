#!/usr/bin/env python3
"""
文献去重工具

功能：
- 基于 DOI 精确去重
- 基于标题相似度去重
- 命中即**合并字段**（P0-5），不同于旧版「整条替换、丢掉败者元数据」
- 结果与输入顺序**无关**（P0-2）：同一条文献无论先入表还是后入表，判定一致

不变式（可写成断言）
------------------
1. 幂等：``deduplicate_papers(deduplicate_papers(p)[0])[0]`` 与首次结果同集合
2. 顺序无关：任意排列 ``perm(p)`` 与 ``p`` 得到**同一簇集合**、每簇**同一胜者 id**
3. 输出顺序按「簇首次出现位置」保持稳定，便于参考文献编号不跳动
"""

import copy
import os
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Set, Tuple
from difflib import SequenceMatcher

#: 合并时可从败者身上「借」过来的字段（按具体需求可增补）
MERGEABLE_FIELDS = (
    "doi", "title", "authors", "abstract", "keywords", "journal", "publisher",
    "place", "year", "volume", "issue", "pages", "language", "doc_type",
    "carrier", "source_db", "source_url", "access_date",
)


def _as_text(value: Any) -> str:
    """``None`` / 非字符串安全归一为字符串（P0-4：``title=None`` 不再崩溃）。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _is_blank(value: Any) -> bool:
    """判断「空值」：None / 空串 / 纯空白 / 空容器。"""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) == 0
    return False


def normalize_title(title: Any) -> str:
    """标题归一：转小写、压缩空白。非字符串输入安全处理。"""
    return " ".join(_as_text(title).strip().lower().split())


def calculate_similarity(str1: str, str2: str) -> float:
    """
    计算两个字符串的相似度

    Args:
        str1: 第一个字符串
        str2: 第二个字符串

    Returns:
        相似度（0.0 - 1.0）
    """
    if not str1 or not str2:
        return 0.0

    s1 = str1.lower().strip()
    s2 = str2.lower().strip()

    return _ratio(s1, s2)


def _ratio(s1: str, s2: str) -> float:
    """已归一化字符串的相似度（内部用，调用方保证小写已压缩空白）。"""
    if s1 == s2:
        return 1.0
    return SequenceMatcher(None, s1, s2).ratio()


def _similar_enough(s1: str, s2: str, threshold: float) -> bool:
    """带**两级上界剪枝**的阈值判定，结果与 ``_ratio(s1,s2) >= threshold`` 等价。

    第 1 级（长度上界）：``ratio() == 2*M/(len1+len2)`` 且 ``M <= min(len1,len2)``，
    故 ``2*min/(len1+len2)`` 是相似度的**严格上界**，不到阈值即可返回 False。

    第 2 级（字符多重集上界）：``SequenceMatcher.quick_ratio()`` 只用字符计数求
    a、b 的字符多重集交集上限、不做任何匹配，同样是 ``ratio()`` 的上界，但比长度
    上界紧得多。实测拦掉 57.5% 的动态规划
    （1 415 条语料 601 236 对 -> 255 815 对，去重 126.5 s -> 68.9 s，
     uniq 1 389 / removed 26 与剪枝前**完全一致**）。

    警告：**不能**用 ``real_quick_ratio()``。CPython 的 ``real_quick_ratio()`` 就是
    ``2*min(la,lb)/(la+lb)``，与上面那道长度上界**逐字节相同**，放在这里拦截率恒为
    0%（实测 601 236 次闸门、拦截 0 次）。要做这一级必须用 ``quick_ratio()``。

    两级都只是**上界闸门**：过了闸门仍走真正的 ``ratio()``，故结果不可能改变。
    这里复用同一个 ``SequenceMatcher`` 实例，避免为闸门和终判各建一次。
    """
    if not s1 or not s2:
        return False
    if s1 == s2:
        return True
    la, lb = len(s1), len(s2)
    if 2.0 * (la if la < lb else lb) / (la + lb) < threshold:
        return False
    if ENGINE == "rapidfuzz" and _Indel is not None:
        # 快路径：单次比较实测 ~0.6 us（difflib ~330 us），但相似度会系统性偏高
        return _Indel.normalized_similarity(s1, s2) >= threshold
    sm = SequenceMatcher(None, s1, s2)
    if sm.quick_ratio() < threshold:
        return False
    return sm.ratio() >= threshold


# ---------------------------------------------------------------------------
# 令牌级否决：区分「同一篇的措辞差异」与「两篇不同文献」
# ---------------------------------------------------------------------------
# 动机（2026-10-19，泌尿语料 1 121 条全量回溯）：标题相似度阈值对「模板高度相似
# 但差一个关键实词」的题名毫无防御力 —— 实测
#   `sodium chloride ...` vs `potassium chloride ...`            相似度 0.932
#   `Urethral Obstruction in a Female Cat` vs `... in the male cat` 0.917
#   `... in the Turkey/Aydın` vs `... in the Czech Republic`      0.790
# 全部被 0.75 阈值判为重复。字符串相似度衡量的是「字面重合度」，不是
# 「是否同一篇文献」。故在相似度之上再叠一层**令牌否决**。
#
# 设计原则：**只减不增**。宁可多留一条重复，绝不合并两篇不同文献。
# 凡是无法确认「是同一篇」的情形，一律否决合并。

_STOPWORDS = frozenset(
    "a an the of in on for and or with to from by at as is are was were be been "
    "its their this that these those into during between among within without".split()
)

#: 增补型元词 —— 一侧独有、且**全部**落在此表内时，视为同一篇的措辞差异，允许合并。
#: 刻意保守：只收「不改变研究对象」的词。
_META_WORDS = frozenset(
    "evaluation assessment study studies review overview analysis investigation "
    "comparison comparisons effect effects role determination clinical experimental "
    "pharmacological preliminary update advances current perspective perspectives "
    "insight insights implication implications approach approaches management "
    "treatment therapy diagnosis prevention control".split()
)

#: 记录类型硬否决：评论 / 勘误 / 回复 / 撤稿是**独立条目**，与原文不得合并
_RECORD_TYPES = frozenset(
    "letter corrigendum erratum comment comments reply response retraction retracted".split()
)


def _canon(word: str) -> str:
    """极保守词干化：只去复数与 -ing/-ed，避免把 analysis 削成 analysi 这类过剥。"""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is", "ys")):
        return word[:-1]
    if len(word) > 5 and word.endswith("ing"):
        return word[:-3]
    if len(word) > 4 and word.endswith("ed"):
        return word[:-2]
    return word


def _tokens(title: Any) -> List[str]:
    """题名 -> 内容词元（去停用词、词干化）。**保留数字**：数字差异是强否决信号。"""
    raw = re.findall(r"[a-z0-9]+", normalize_title(title))
    return [_canon(w) for w in raw if w not in _STOPWORDS]


def _covered(word: str, pool: List[str]) -> bool:
    """``word`` 是否被 ``pool`` 覆盖（同词，或长度≥4 的前缀关系 towards/toward）。"""
    if word in pool:
        return True
    for other in pool:
        if len(word) >= 4 and len(other) >= 4:
            if word.startswith(other) or other.startswith(word):
                return True
    return False


def _token_diff(a: List[str], b: List[str]) -> Tuple[List[str], List[str]]:
    """双向差集，带前缀容忍（towards/toward、cats/cat）。"""
    return (
        [w for w in a if not _covered(w, b)],
        [w for w in b if not _covered(w, a)],
    )


def veto_reason(title_a: Any, title_b: Any) -> Optional[str]:
    """判定两条题名是否**不允许**合并；返回否决理由，``None`` 表示允许合并。

    三道否决，全部指向「宁可多留」：

    1. **记录类型**：letter / corrigendum / comment / reply 等出现在差异里 ——
       `letter regarding "X"` 与 `X` 是两条独立记录
    2. **数字差异**：part 1 / part 2、rc1 / rc2、年份 —— 分册与版本，不可合并
    3. **替换关系**：两侧各有对方没有的实质词（sodium↔potassium、turkey↔czech）。
       仅当单侧增补词**全部**是元词（evaluation for X）时才放行

    无内容词可比时返回 ``None``：交回相似度判定，不在此处猜测。
    """
    ta, tb = _tokens(title_a), _tokens(title_b)
    if not ta or not tb:
        return None

    # 过短题名不做模糊合并：`How to…` / `index` / `urolithiasis` 这类通用题名内容词
    # 不足 3 个，相似度再高也无法判断是否同一篇 —— 实测同一期刊两篇不同的 `How to…`
    # （DOI ...1114.14 与 ...0110.12）被并成一条。短题名只按 DOI 判重。
    # 必须放在 squash 通道**之前**：两篇同名的 `How to…` squash 后也相等，会走快捷放行。
    if len(ta) < 3 or len(tb) < 3:
        return "题名过短（内容词 %d/%d 个），仅按 DOI 判重" % (len(ta), len(tb))

    # 快捷通道：去掉全部非字母数字后仍相同 → 纯标点/连字符差异
    # （`Anti-urolithiatic` 与 `Antiurolithiatic` 分词后是 2 词 vs 1 词，
    #   会被误判成「替换关系」，故在此提前放行）
    squash_a = re.sub(r"[^a-z0-9]+", "", normalize_title(title_a))
    squash_b = re.sub(r"[^a-z0-9]+", "", normalize_title(title_b))
    if squash_a and squash_a == squash_b:
        return None

    d1, d2 = _token_diff(ta, tb)
    if not d1 and not d2:
        return None  # 内容词完全一致 → 同一篇

    diff_all = set(d1) | set(d2)

    hit = diff_all & _RECORD_TYPES
    if hit:
        return "记录类型差异 %s" % sorted(hit)

    digits = sorted(w for w in diff_all if w.isdigit())
    if digits:
        return "数字差异 %s" % digits

    if d1 and d2:
        return "替换关系 左独有%s 右独有%s" % (d1[:4], d2[:4])

    only = d1 or d2
    if not set(only) <= _META_WORDS:
        return "单侧增补实质词 %s" % sorted(only)[:4]
    return None


def normalize_doi(doi: str) -> str:
    """标准化DOI"""
    if not doi:
        return ""

    doi = doi.replace("https://doi.org/", "")
    doi = doi.replace("http://doi.org/", "")
    doi = doi.replace("doi.org/", "")
    doi = doi.replace("DOI:", "")
    doi = doi.replace("doi:", "")

    return doi.strip().lower()


def calculate_paper_quality_score(paper: Dict) -> float:
    """
    计算文献质量分数（用于决定保留哪个重复版本）
    """
    score = 0.0

    # 有DOI加分
    if paper.get("doi"):
        score += 10

    # 有完整元数据加分
    if paper.get("abstract"):
        score += 5
    if paper.get("volume") and paper.get("issue"):
        score += 3
    if paper.get("pages"):
        score += 2

    return score


def _trace_id(paper: Dict) -> str:
    """合并追溯标识：无 ``id`` 时用题名指纹兜底。

    旧实现写成 ``if source_id``，条目缺 ``id`` 时合并关系被**静默丢弃**，
    批量回溯时无法定位「谁被谁吃了」（本次排查只能靠标题相似度反推）。
    """
    sid = _as_text(paper.get("id")).strip()
    if sid:
        return sid
    fp = normalize_title(paper.get("title"))
    return "title:" + (fp[:60] if fp else "<untitled>")


def _merge_into(target: Dict, loser: Dict) -> None:
    """把 ``loser`` 的非空字段就地补进 ``target``（``target`` 须已是私有副本）。"""
    for key, value in loser.items():
        if key in ("id", "merged_from"):
            continue
        if key in MERGEABLE_FIELDS and _is_blank(target.get(key)) and not _is_blank(value):
            target[key] = copy.deepcopy(value)

    merged_from: List[str] = list(target.get("merged_from") or [])
    for source_id in list(loser.get("merged_from") or []) + [_trace_id(loser)]:
        if source_id and source_id not in merged_from:
            merged_from.append(source_id)
    if merged_from:
        target["merged_from"] = merged_from

    # 成员 DOI 留痕（P26/A）：上面的字段补全只保留**胜者**的 doi —— 同一篇的
    # 预印本 / 期刊版 / 学位版 DOI 各不相同，被合并方的 doi 就此永久消失，
    # 事后想核对只能拿题名去反搜（实测 1257 条交付里 25 组全部失联）。
    # 故把「最终不等于 target.doi 的那些」收进 doi_alt。
    # 顺序与 merged_from 同构（先 loser 的链、后 loser 自身）：同输入必同输出。
    target_doi = _as_text(target.get("doi")).strip().lower()
    alt: List[str] = list(target.get("doi_alt") or [])
    for cand in list(loser.get("doi_alt") or []) + [_as_text(loser.get("doi")).strip()]:
        c = _as_text(cand).strip()
        if not c or c.lower() == target_doi or c in alt:
            continue
        alt.append(c)
    if alt:
        target["doi_alt"] = alt


def merge_papers(winner: Dict, loser: Dict) -> Dict:
    """把 ``loser`` 的**非空**字段补进 ``winner``（P0-5）。

    规则：
    * 以 ``winner`` 为主，``winner`` 已有非空值的字段不被覆盖
    * ``loser`` 的 ``id`` 记入 ``merged_from``，合并可追溯
    * 深拷贝返回，不修改入参（避免调用方共享引用被静默改写）

    Args:
        winner: 保留方
        loser: 被合并方

    Returns:
        合并后的新字典
    """
    if not isinstance(winner, dict) or not isinstance(loser, dict):
        raise TypeError(
            "merge_papers 只接受 dict，收到 %s / %s"
            % (type(winner).__name__, type(loser).__name__)
        )
    merged: Dict = copy.deepcopy(winner)
    _merge_into(merged, loser)
    return merged


def _prepare(paper: Dict, index: int) -> Dict:
    """把原始条目预编译为「比对用记录」；不复制原字典（未做任何写入，零拷贝开销）。

    ``relevance`` 取自条目上已算好的 ``relevance_score``（打分必须在去重**之前**完成）。
    缺失或非数值一律记 0.0 —— 调用方没打分时行为退化为旧版的「纯元数据质量」排序。
    """
    if not isinstance(paper, dict):
        raise TypeError(
            "第 %d 条文献不是 dict，而是 %s：%r" % (index, type(paper).__name__, paper)
        )
    rel_raw = paper.get("relevance_score")
    try:
        relevance = float(rel_raw) if rel_raw is not None else 0.0
    except (TypeError, ValueError):
        relevance = 0.0
    return {
        "paper": paper,
        "doi": normalize_doi(_as_text(paper.get("doi"))),
        "title": normalize_title(paper.get("title")),
        "quality": calculate_paper_quality_score(paper),
        "relevance": relevance,
        "id": _as_text(paper.get("id")),
        "index": index,
    }


def _rank_key(item: Dict) -> Tuple:
    """胜者排序键：**相关性优先**，其次元数据质量，最后用 id/标题/原始位置定序。

    旧版只按元数据质量排序（DOI+10 / 摘要+5 / 卷期+3 / 页+2），与内容相关性无关 ——
    实测导致 23 分的 `Urethral Obstruction in a Female Cat` 被 16 分的
    `Urethral obstruction in the male cat` 顶掉，且该簇的「代表标题」也随之变成
    低分那条，进而把后续本该独立的条目吸附进来。
    """
    return (-item["relevance"], -item["quality"], item["id"], item["title"], item["index"])


def _new_cluster(item: Dict) -> Dict:
    """新建簇：``dois`` 供 O(1) 判重，``probe`` 为「代表标题」（当前质量最高者）。"""
    return {
        "members": [item],
        "dois": {item["doi"]} if item["doi"] else set(),
        "best": item,
        "probe": item["title"],
    }


def _absorb(cluster: Dict, item: Dict) -> None:
    """把一个条目并入簇，并维护 ``dois`` / 代表标题。"""
    cluster["members"].append(item)
    if item["doi"]:
        cluster["dois"].add(item["doi"])
    if _rank_key(item) < _rank_key(cluster["best"]):
        cluster["best"] = item
        cluster["probe"] = item["title"]


#: 语料小于此规模不做分块 —— 分块的固定开销在小语料上得不偿失。
_BLOCK_MIN_N = 50

# ---------------------------------------------------------------------------
# O5 可选快路径：rapidfuzz（默认**关闭**）
# ---------------------------------------------------------------------------
# 实测（1 415 条语料、262 270 对全部过 quick_ratio 闸门的对）：
#   完全相同（差 <1e-12） 1 919 对（0.7%）｜均值差 0.126｜最大差 0.470
#   跨过 0.75 阈值 17 对 —— rapidfuzz **系统性偏高**，因为它用真 LCS，
#   而 difflib 的 ratio 用最长匹配块递归（块总和 <= 真 LCS）。
#
# 本语料上最终去重结果恰好一致（那 17 对全被令牌否拦截下），但那是巧合而非保证：
# 换一份语料，偏高的相似度会**多合并**两篇不同文献 —— 这正是去重最不能犯的错。
# 故：默认 difflib；只有显式设 LITREV_FUZZ_ENGINE=rapidfuzz 才走快路径。
# 未安装 rapidfuzz 时静默回退，不报错（零依赖不可被破坏）。
try:
    from rapidfuzz.distance import Indel as _Indel
except ImportError:                      # pragma: no cover - 取决于环境
    _Indel = None

ENGINE = os.environ.get("LITREV_FUZZ_ENGINE", "difflib").strip().lower()
if ENGINE == "rapidfuzz" and _Indel is None:
    ENGINE = "difflib"                   # 想用但没装 -> 回退，不静默改变结果




def _blocking_index(papers: List[Dict], frac: float = 0.05) -> Set[str]:
    """预扫全部标题，返回「稀有 token」集合（文档频率 df <= frac * n）。

    为什么用「稀有」而不是全部 token：常见词（``cats``、``effect``、``study``）
    在几百条里都出现，按它建桶等于没分块；稀有 token 才是真正能区分文献的
    信息量所在（化合物名、物种亚型、地名、期刊特有词）。

    阈值取 ``max(1, int(frac*n))``：语料很小时保证不会「一个 token 都不稀有」。
    代价是 O(n) 次 token 化（1 415 条实测 <0.1 s），远小于它省下的比较成本。
    """
    df: Counter = Counter()
    for p in papers:
        df.update(set(_tokens(normalize_title(_as_text(p.get("title"))))))
    cut = max(1, int(frac * len(papers)))
    return {w for w, c in df.items() if c <= cut}


def _matches(cluster: Dict, item: Dict, threshold: float,
             cache: Optional[Dict] = None, stats: Optional[Dict] = None) -> bool:
    """判定 ``item`` 是否属于 ``cluster``：DOI 精确命中 或 与簇**代表标题**相似度达标。

    与「簇内任一成员」比对在数学上更严，但代价是 O(成员数)：N=1000 时实测由
    6.2s 退化到 95.7s（15.5×）。旧实现事实上也只与每簇**保留的那一方**比对，
    故此处取「代表标题」为比对对象，**召回不低于旧实现**，同时把每簇比较成本
    压到 O(1)。

    ``cache`` 为本次调用内的 ``(标题a, 标题b) -> bool`` 结果缓存：同题多来源变体
    反复出现，且相似度对称，缓存可省掉重复动态规划。
    """
    if item["doi"] and item["doi"] in cluster["dois"]:
        return True

    probe = cluster["probe"]
    if not item["title"] or not probe:
        return False  # 无标题无法做模糊比对，只靠 DOI 判重（不猜测）

    def _decide() -> bool:
        # 相似度达标**且**令牌否决未触发，才算重复。顺序不可颠倒：
        # 先跑相似度（含上界剪枝）能省掉大部分令牌计算。
        if stats is not None:
            stats["fuzzy_checks"] = stats.get("fuzzy_checks", 0) + 1
        if not _similar_enough(item["title"], probe, threshold):
            return False
        blocked = veto_reason(item["title"], probe) is not None
        if blocked and stats is not None:
            stats["veto_blocks"] = stats.get("veto_blocks", 0) + 1
        return not blocked

    if cache is None:
        return _decide()

    key = (item["title"], probe) if item["title"] <= probe else (probe, item["title"])
    hit = cache.get(key)
    if hit is None:
        hit = _decide()
        cache[key] = hit
    elif stats is not None:
        stats["cache_hits"] = stats.get("cache_hits", 0) + 1
    return hit


def deduplicate_papers(
    papers: List[Dict],
    title_similarity_threshold: float = 0.85,
    stats: Optional[Dict] = None,
    blocking: bool = True,
) -> Tuple[List[Dict], List[Dict]]:
    """
    文献去重主函数

    去重策略（单遍聚类 + 事后定格，因此对输入顺序不敏感）：

    1. 逐条判定：DOI 精确匹配任一簇成员，或标题与簇内任一标题相似度 ≥ 阈值 → 归入该簇
    2. 一次命中多个簇时**合并簇**（避免 A~B~C 链式漏检）
    3. 每簇定格胜者：质量分最高者；败者字段按 `merge_papers` 回填，不丢元数据

    Args:
        papers: 文献列表
        title_similarity_threshold: 标题相似度阈值（默认0.85）
        blocking: 是否启用候选对分块（默认 True）。**生产恒为 True**，
            传 False 只为在 A/B 中复现「全量比对」的旧结果：分块里的令牌
            倒排是近似层，只有与全量结果做集合差对比才能证明它没漏。
        stats: 可选的计数出参（原地填充，不传则零开销）。用途是让调用方
            **自证瓶颈**：``fuzzy_checks`` 实际模糊比较次数、``cache_hits``
            缓存命中、``veto_blocks`` 被令牌否决拦下的合并、
            ``clusters_peak``/``clusters_final`` 簇数峰值与终值。

    Returns:
        (去重后的文献列表, 被移除的重复文献列表)。被移除条目的非空字段已并入保留条目，
        其 id 记录在保留条目的 ``merged_from`` 中。

    Raises:
        TypeError: 列表元素不是 dict
    """
    if not papers:
        return [], []

    clusters: List[Dict] = []
    sim_cache: Dict[Tuple[str, str], bool] = {}  # 单次调用内的相似度缓存
    if stats is not None:
        for _k in ("fuzzy_checks", "cache_hits", "veto_blocks", "pairs_skipped"):
            stats.setdefault(_k, 0)
        stats["papers"] = len(papers)
        stats["clusters_peak"] = 0

    # ---- 候选对分块（O4）：把「与所有簇逐一比对」降为「只与候选簇比对」 ----
    # 全量比对是 O(n^2)：1 415 条实测 60 万次模糊比较、65 s，n=5 000 外推 26 分钟。
    # 三层叠加，**性质各不相同**，混用会漏：
    #   ① DOI 倒排（精确）：DOI 相同必须进候选，不受任何剪枝影响。
    #   ② 稀有 token 倒排（近似）：block key 取「全部成员稀有 token 的并集」，
    #      而不是代表标题 —— 代表标题会被 _absorb 换人，用并集才不会被换人打穿。
    #      实测本语料 27 对真重复全部落在桶内（probe_o4_cover）。
    #   ③ 兜底桶（修补 ② 的近似）：任何成员都不含稀有 token 的簇进 catch-all；
    #      不含稀有 token 的条目、以及 catch-all 簇，都退化为与所有簇比对，绝不漏。
    #   ④ 长度窗口（精确）：``ratio`` 上界 ``2*min/(la+lb) >= 阈值`` 是数学保证，
    #      与 _similar_enough 第一级同一公式，不达标的簇直接跳过。
    # 近似层即使漏了，也只影响「召回」不影响「正确性」—— 但那是数据完整性问题，
    # 故 blocking=False 保留为可复现的对照路径（生产恒 True）。
    rare = _blocking_index(papers) if (blocking and len(papers) >= _BLOCK_MIN_N) else set()
    inv: Dict[str, Set[int]] = {}      # 稀有 token -> 簇 seq 集合
    catchall: Set[int] = set()         # 全部成员都不含稀有 token 的簇
    by_seq: Dict[int, Dict] = {}       # seq -> 簇（簇被合并时 pop 掉，留墓碑 seq）
    doi_seq: Dict[str, int] = {}       # DOI -> 簇 seq
    seq_n = 0
    if stats is not None:
        stats["blocking"] = bool(rare)
        stats["rare_tokens"] = len(rare)

    for index, raw in enumerate(papers):
        item = _prepare(raw, index)
        rtok = {w for w in _tokens(item["title"]) if w in rare} if rare else set()

        if not rare or not rtok:
            cand = None                                  # 兜底：与所有簇比对
        else:
            cand = set(catchall)
            for w in rtok:
                cand.update(inv.get(w, ()))
            if stats is not None:
                stats["pairs_skipped"] += max(0, len(by_seq) - len(cand))

        seqs = set(by_seq) if cand is None else set(cand)
        doi_hit: Set[int] = set()
        if item["doi"]:
            s0 = doi_seq.get(item["doi"])
            if s0 is not None:
                seqs.add(s0)
                doi_hit.add(s0)

        # 按 seq 升序判定：seq 单调递增且 clusters 始终按 seq 有序，
        # 故命中顺序与「全量按 clusters 下标」完全一致（merged_from 顺序因此不变）。
        li = len(item["title"])
        hits: List[Dict] = []
        for s in sorted(seqs):
            cluster = by_seq.get(s)                      # 墓碑 seq（已合并）跳过
            if cluster is None:
                continue
            if s not in doi_hit:
                lp = len(cluster["probe"])
                if li + lp and (2.0 * (li if li < lp else lp) / (li + lp)
                                < title_similarity_threshold):
                    continue
            if _matches(cluster, item, title_similarity_threshold, sim_cache, stats):
                hits.append(cluster)

        if not hits:
            seq_n += 1
            cluster = _new_cluster(item)
            cluster["_seq"] = seq_n
            cluster["_toks"] = set(rtok)
            clusters.append(cluster)
            by_seq[seq_n] = cluster
            if rtok:
                for w in rtok:
                    inv.setdefault(w, set()).add(seq_n)
            else:
                catchall.add(seq_n)
            if item["doi"]:
                doi_seq[item["doi"]] = seq_n
            if stats is not None and len(clusters) > stats["clusters_peak"]:
                stats["clusters_peak"] = len(clusters)
            continue

        primary = hits[0]
        _absorb(primary, item)
        if item["doi"]:
            doi_seq[item["doi"]] = primary["_seq"]
        new_toks = rtok - primary["_toks"]
        if new_toks:                                     # 代表换人也不影响块键
            primary["_toks"] |= new_toks
            catchall.discard(primary["_seq"])
            for w in new_toks:
                inv.setdefault(w, set()).add(primary["_seq"])
        # 逆序合并：与旧实现（逆序 pop）保持同一吸收顺序，merged_from 才不会漂移
        for other in reversed(hits[1:]):
            for member in other["members"]:
                _absorb(primary, member)
            primary["dois"] |= other["dois"]
            add_toks = other["_toks"] - primary["_toks"]
            if add_toks:
                primary["_toks"] |= add_toks
                catchall.discard(primary["_seq"])
                for w in add_toks:
                    inv.setdefault(w, set()).add(primary["_seq"])
            for d in other["dois"]:
                doi_seq[d] = primary["_seq"]
            by_seq.pop(other["_seq"], None)
            catchall.discard(other["_seq"])
            clusters = [c for c in clusters if c["_seq"] != other["_seq"]]

    if stats is not None:
        stats["clusters_final"] = len(clusters)

    unique_papers: List[Dict] = []
    removed_papers: List[Dict] = []

    for cluster in clusters:
        ordered = sorted(cluster["members"], key=_rank_key)
        merged = copy.deepcopy(ordered[0]["paper"])
        for loser in ordered[1:]:
            _merge_into(merged, loser["paper"])  # 就地合并，避免逐步 deepcopy 的 O(k²)
        unique_papers.append(merged)
        removed_papers.extend(copy.deepcopy(m["paper"]) for m in ordered[1:])

    return unique_papers, removed_papers


def print_deduplication_report(
    original_count: int,
    unique_papers: List[Dict],
    removed_papers: List[Dict]
):
    """打印去重报告"""
    print("=" * 60)
    print("文献去重报告")
    print("=" * 60)

    print(f"\n原始文献数量: {original_count}")
    print(f"去重后数量: {len(unique_papers)}")
    print(f"移除重复: {len(removed_papers)}")

    if original_count > 0:
        print(f"去重率: {len(removed_papers) / original_count * 100:.1f}%")


if __name__ == "__main__":
    # 测试示例 —— 覆盖「同题、一条带 DOI、顺序不同」的 P0-2 场景
    base = {
        "title": "Deep learning for image recognition",
        "authors": ["Y LeCun"],
        "year": 2015,
        "journal": "Nature",
    }

    test_papers = [
        dict(base, id="E1", doi="10.1038/nature14539", volume="521", issue="7553", pages="436-444"),
        dict(base, id="W1", doi="", abstract="同一篇文献的无 DOI 版本（模拟 CNKI 条目）"),
        dict(base, id="E3", doi="", title="Deep learning for image recognition: A survey"),
        {"id": "E4", "title": "Attention is all you need", "authors": ["A Vaswani"],
         "year": 2017, "journal": "NIPS", "doi": "10.48550/arXiv.1706.03762"},
        {"id": "E5", "title": None, "doi": ""},  # P0-4：标题缺失不再崩溃
    ]

    for label, order in (("正序（带DOI在前）", test_papers), ("反序（带DOI在后）", list(reversed(test_papers)))):
        unique, removed = deduplicate_papers(order)
        ids = sorted(p["id"] for p in unique)
        print(f"{label}: 保留 {len(unique)} 条 → ids={ids}")
    print()

    unique, removed = deduplicate_papers(test_papers)
    print_deduplication_report(len(test_papers), unique, removed)
    for paper in unique:
        if paper.get("merged_from"):
            print(f"  {paper['id']} 合并自 {paper['merged_from']}；"
                  f"volume={paper.get('volume')!r} abstract={(paper.get('abstract') or '')[:18]!r}")
