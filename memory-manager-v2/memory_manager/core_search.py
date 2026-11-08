# -*- coding: utf-8 -*-
"""
记忆管家 V3.0 - 记忆搜索与任务相关性评分
从 core.py 拆分（降低单文件长度 file>800 硬限 P1）。
"""
import json
import logging
import re
from datetime import datetime
from pathlib import Path

from .config import (
    VERSION, _, SUMMARY_DIR, LOAD_BRIEF, LOAD_NORMAL, LOAD_FULL,
    is_symlink, safe_file_read, get_file_info, iter_memory_files, parse_front_matter,
)
from .summarize import generate_summary, extract_keywords, smart_truncate

logger = logging.getLogger(__name__)


def _char_bigrams(s):
    """生成字符 bigram 集合（忽略空白），用于中文/无空格查询的重叠匹配。"""
    s = re.sub(r'\s+', '', s.lower())
    if len(s) < 2:
        return set(s)
    return set(s[i:i+2] for i in range(len(s) - 1))


def _embedding_score(query, md_file, summary_path):
    """可选向量相似度：仅当 config.embedding_backend 配置且后端可导入时启用。

    离线默认返回 None → 上层回退到 bigram/关键词相关度。预留扩展点，避免硬依赖。
    """
    try:
        from .config import load_config, DEFAULT_CONFIG
        backend = load_config().get("embedding_backend") or DEFAULT_CONFIG.get("embedding_backend")
        if not backend:
            return None
        # 真实后端在外部注入（如 sentence-transformers）；此处仅占位安全降级
        return None
    except Exception:
        return None


def _relevance_keyword_score(q_tokens, summary_text, keywords, md_file):
    """关键词命中分：标签/摘要命中 +20/+10，正文命中 +5。"""
    score = 0
    st = summary_text.lower()
    kw = " ".join(keywords).lower()
    content = None
    for t in q_tokens:
        if t in kw:
            score += 20
        elif t in st:
            score += 10
        else:
            if content is None:
                content, _read_err = safe_file_read(md_file)
            if content and t in content.lower():
                score += 5
    return score


def _relevance_tag_score(tags, md_file):
    """标签命中分：任一目标标签出现在 front-matter 则 +30。"""
    content_raw, _read_err = safe_file_read(md_file)
    if not content_raw:
        return 0
    fm_tags = parse_front_matter(content_raw).get("tags", [])
    fm_tags_l = [x.lower() for x in fm_tags]
    if any(tg.lower() in fm_tags_l for tg in tags):
        return 30
    return 0


def _relevance_query_tokens(query):
    """解析查询为 bigram 集合与 token 集合（CJK 用 bigram）。"""
    q_bigrams = set()
    q_tokens = set()
    if not query:
        return q_bigrams, q_tokens
    if re.search(r'[\u4e00-\u9fff]', query) or len(query.split()) <= 1:
        q_bigrams = _char_bigrams(query)
    q_tokens = {t for t in re.split(r'[\s,.，。、；;:：]+', query.lower()) if t}
    return q_bigrams, q_tokens


def _relevance_bigram_score(q_bigrams, summary_text, keywords, md_file):
    """CJK bigram 重叠加点。"""
    if not q_bigrams:
        return 0
    doc_text = summary_text + " " + " ".join(keywords)
    doc_bigrams = _char_bigrams(doc_text)
    if not doc_bigrams:
        content, _read_err = safe_file_read(md_file)
        doc_bigrams = _char_bigrams(content or "")
    return len(q_bigrams & doc_bigrams) * 5


def _relevance_score(query, tags, md_file, summary_path):
    """任务相关性评分（零依赖）：CJK bigram 重叠 + 关键词/标签相关度。

    设计决策 7.3：默认零依赖（离线友好）。中文/无空格查询用字符 bigram 提升召回；
    若配置 embedding_backend 且后端可导入，则改用向量相似度（见 _embedding_score）。
    """
    score = 0.0
    q_bigrams, q_tokens = _relevance_query_tokens(query)

    summary_file = summary_path / f"{md_file.stem}.summary"
    summary_text = ""
    keywords = []
    if summary_file.exists():
        try:
            with open(summary_file, 'r', encoding='utf-8') as f:
                sd = json.load(f)
            summary_text = sd.get("summary", "")
            keywords = sd.get("keywords", [])
        except (json.JSONDecodeError, OSError, IOError):
            sd = {}

    # 可选向量后端
    emb = _embedding_score(query, md_file, summary_path)
    if emb is not None:
        return {"score": emb}

    # CJK 字符 bigram 重叠 + 关键词匹配 + 标签匹配
    score += _relevance_bigram_score(q_bigrams, summary_text, keywords, md_file)
    if q_tokens:
        score += _relevance_keyword_score(q_tokens, summary_text, keywords, md_file)
    if tags:
        score += _relevance_tag_score(tags, md_file)

    return {"score": score}


def _search_folder_matches(rel_path, folder):
    if not folder:
        return True
    parts = Path(rel_path).parts
    return (parts[0] if len(parts) > 1 else "/") == folder


def _search_file_tags(md_file, tag):
    """返回 (file_tags, matched)。无 tag 时 matched=True、file_tags=[]。"""
    if not tag:
        return [], True
    content_raw, _read_err = safe_file_read(md_file)
    if not content_raw:
        return [], False
    file_tags = parse_front_matter(content_raw).get("tags", [])
    matched = any(t.lower() == tag.lower() for t in file_tags)
    return file_tags, matched


def _search_summary_score(summary_data, keyword_lower):
    """summary/关键词命中打分。"""
    if not summary_data:
        return 0
    score = 0
    if keyword_lower in summary_data.get("summary", "").lower():
        score += 10
    if keyword_lower in " ".join(summary_data.get("keywords", [])).lower():
        score += 20
    return score


def _search_bigram_score(md_file, summary_data, keyword_lower):
    """CJK bigram 重叠加分（中文/无空格查询召回提升）。"""
    if not (re.search(r'[\u4e00-\u9fff]', keyword_lower) or len(keyword_lower.split()) <= 1):
        return 0
    qb = _char_bigrams(keyword_lower)
    doc = ""
    if summary_data:
        doc = (summary_data.get("summary", "") + " " +
               " ".join(summary_data.get("keywords", []))).lower()
    if not doc.strip():
        content, _read_err = safe_file_read(md_file)
        doc = (content or "").lower()
    return len(qb & _char_bigrams(doc)) * 3


def _search_score(md_file, summary_path, keyword_lower, file_tags, tag):
    """单文件匹配分：summary/全文命中 + 标签加分 + CJK bigram 重叠。
    返回 (score, summary_data)。"""
    summary_file = summary_path / f"{md_file.stem}.summary"
    summary_data = None
    if summary_file.exists():
        try:
            with open(summary_file, 'r', encoding='utf-8') as f:
                summary_data = json.load(f)
        except (json.JSONDecodeError, OSError, IOError):
            summary_data = None
    if summary_data:
        score = _search_summary_score(summary_data, keyword_lower)
    else:
        content, _read_err = safe_file_read(md_file)
        score = 5 if (content and keyword_lower in content.lower()) else 1  # 1=纯标签匹配

    if tag and file_tags:
        score += 30  # 标签匹配额外加分

    score += _search_bigram_score(md_file, summary_data, keyword_lower)
    return score, summary_data


def _search_preview(md_file, summary_path, summary_data, mode):
    """按 mode 生成预览：brief=摘要前200、normal=全文摘要、full=原文前500。"""
    if mode == LOAD_BRIEF:
        return (summary_data or {}).get("summary", "")[:200] if summary_data else ""
    if mode == LOAD_NORMAL:
        return (summary_data or {}).get("summary", "") if summary_data else ""
    content, _read_err = safe_file_read(md_file)
    return content[:500] if content else ""


def _search_match_one(md_file, rel_path, summary_path, keyword_lower, folder, tag, mode):
    """对单文件执行过滤+评分+预览，返回匹配条目或 None。"""
    if not _search_folder_matches(rel_path, folder):
        return None
    file_tags, matched = _search_file_tags(md_file, tag)
    if not matched:
        return None
    score, summary_data = _search_score(md_file, summary_path, keyword_lower, file_tags, tag)
    if score <= 0:
        return None
    mtime, size_kb = get_file_info(md_file)
    return {
        "file": md_file.name,
        "path": rel_path,
        "folder": Path(rel_path).parts[0] if len(Path(rel_path).parts) > 1 else "/",
        "tags": file_tags,
        "score": score,
        "modified": mtime.strftime("%Y-%m-%d") if mtime else "unknown",
        "preview": _search_preview(md_file, summary_path, summary_data, mode),
        "size_kb": round(size_kb, 2) if size_kb else 0
    }


def search_memory(workspace_path, keyword, mode="brief", folder=None, tag=None):
    base_path = Path(workspace_path).resolve()
    memory_path = base_path / ".workbuddy" / "memory"
    summary_path = base_path / ".workbuddy" / SUMMARY_DIR

    result = {
        "version": VERSION,
        "timestamp": datetime.now().isoformat(),
        "keyword": keyword,
        "folder": folder,
        "tag": tag,
        "matches": [],
        "total": 0
    }

    if not memory_path.exists():
        result["error"] = _("memory_dir_not_exist")
        return result

    keyword_lower = keyword.lower()
    matches = []

    for md_file, mtime, size_kb, rel_path in iter_memory_files(
            memory_path, skip_memory_md=False):
        m = _search_match_one(md_file, rel_path, summary_path, keyword_lower, folder, tag, mode)
        if m:
            matches.append(m)

    matches.sort(key=lambda x: x["score"], reverse=True)
    result["matches"] = matches
    result["total"] = len(matches)

    return result
