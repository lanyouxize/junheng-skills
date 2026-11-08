import logging
logger = logging.getLogger(__name__)

# -*- coding: utf-8 -*-
"""
记忆管家 V3.0 - 摘要生成模块
来源: memory_manager.py (summary)
V3.0: 模块化重构
"""

import json
import os
import re
import concurrent.futures
from collections import Counter
from datetime import datetime
from pathlib import Path

from .config import (
    VERSION, _, SUMMARY_DIR,
    SUMMARY_MAX_CHARS, SUMMARY_MIN_CHARS,
    is_symlink, safe_file_read, get_file_info,
)
from .token import estimate_tokens, record_token_usage


def extract_keywords(content, max_keywords=5):
    stopwords = {
        '的', '了', '是', '在', '和', '与', '或', '等', '于', '对',
        '这', '那', '有', '我', '你', '他', '她', '它', '们',
        '一个', '我们', '他们', '这个', '什么', '如何', '怎么',
        '可以', '需要', '如果', '因为', '所以', '但是', '而且',
        '或者', '以及', '对于', '关于', '通过', '使用', '进行',
        '实现', '完成', '开始', '结束', '之后', '之前', '时候',
        '情况', '问题', '方法', '内容', '文件', '功能', '支持',
    }

    try:
        import jieba
        words = list(jieba.cut(content.lower()))
        words = [w.strip() for w in words if len(w.strip()) > 1 and w.strip() not in stopwords]
    except (ImportError, Exception):
        words = re.findall(r'[\w]{2,}', content.lower())
        words = [w for w in words if w not in stopwords and len(w) > 1]

    counter = Counter(words)
    return [w for w, _ in counter.most_common(max_keywords)]


def smart_truncate(text, max_chars=SUMMARY_MAX_CHARS):
    if len(text) <= max_chars:
        return text

    sentence_ends = ['。', '！', '？', '.', '!', '?']
    search_start = int(max_chars * 0.7)
    search_text = text[search_start:max_chars]

    for end_char in sentence_ends:
        pos = search_text.rfind(end_char)
        if pos != -1:
            actual_pos = search_start + pos + len(end_char)
            return text[:actual_pos] + "..."

    last_newline = text.rfind('\n', search_start, max_chars)
    if last_newline > search_start:
        return text[:last_newline] + "\n..."

    last_space = text.rfind(' ', search_start, max_chars)
    if last_space > search_start:
        return text[:last_space] + "..."

    return text[:max_chars] + "..."


def _summary_seed_parts(lines):
    """从标题与项目符号提取摘要种子。"""
    parts = []
    headers = [l.strip() for l in lines if l.strip().startswith('#') and len(l) < 100]
    if headers:
        parts.extend(headers[:3])
    bullets = [l.strip().lstrip('-*').strip() for l in lines
               if l.strip().startswith(('-', '*')) and len(l) > 5]
    if bullets:
        parts.extend(bullets[:5])
    return parts


def _summary_extend_paragraphs(summary, lines, max_chars):
    """当摘要过短，从段落补齐（不含标题行）。"""
    if len(summary) >= 100 or not lines:
        return summary
    for l in lines:
        if l.strip() and not l.strip().startswith('#'):
            para = l.strip()
            if len(summary) < max_chars:
                summary += '\n' + para
    return summary


def generate_summary(content, max_chars=SUMMARY_MAX_CHARS):
    if len(content) <= SUMMARY_MIN_CHARS:
        return content[:max_chars] if len(content) > max_chars else content

    lines = content.split('\n')
    summary = '\n'.join(_summary_seed_parts(lines))
    summary = _summary_extend_paragraphs(summary, lines, max_chars)
    if len(summary) > max_chars:
        summary = smart_truncate(summary, max_chars)

    return summary.strip()


def _iter_memory_files(memory_path):
    """公共迭代器：遍历记忆目录下的 .md 文件，跳过符号链接"""
    if not memory_path.exists():
        return
    for md_file in memory_path.glob("*.md"):
        if is_symlink(md_file):
            continue
        yield md_file


def _emit_progress(progress_callback, done, total, name):
    """2.3 进度回调安全封装：回调异常不影响主流程。"""
    if progress_callback is not None:
        try:
            progress_callback(done, total, name)
        except Exception as e:
            logger.warning("non-fatal: %s", e)



def _persist_summary_atomic(summary_data, summary_file):
    """原子写入摘要（临时文件 + rename；失败回退直写）。"""
    try:
        tmp = summary_file.with_suffix(".summary.tmp")
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(summary_data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, summary_file)
    except (OSError, IOError):
        try:
            summary_file.write_text(json.dumps(summary_data, ensure_ascii=False, indent=2), encoding='utf-8')
        except (OSError, IOError) as e:
            logger.warning("non-fatal: %s", e)


def _build_summary(md_file, summary_path, regenerate):
    """为单个记忆文件生成（或复用）摘要。

    命中缓存且非 regenerate 时直接返回缓存；否则实时生成并原子写入 .summary。
    线程安全：每个文件独立读写，无共享可变状态，可安全并行。
    """
    if is_symlink(md_file):
        return None

    summary_file = summary_path / f"{md_file.stem}.summary"

    if summary_file.exists() and not regenerate:
        try:
            with open(summary_file, 'r', encoding='utf-8') as f:
                return json.loads(f.read())
        except (json.JSONDecodeError, OSError, IOError) as e:
            logger.warning("non-fatal: %s", e)


    content, status = safe_file_read(md_file)
    if content is None:
        return None

    summary = generate_summary(content)
    keywords = extract_keywords(content)

    mtime, size_kb = get_file_info(md_file)

    summary_data = {
        "file": md_file.name,
        "summary": summary,
        "keywords": keywords,
        "size_kb": size_kb,
        "modified": mtime.strftime("%Y-%m-%d") if mtime else "unknown",
        "generated": datetime.now().isoformat(),
        "token_estimate": estimate_tokens(summary)
    }

    _persist_summary_atomic(summary_data, summary_file)

    return summary_data


def _summarize_named_file(memory_path, summary_path, file_name, regenerate, result, progress_callback):
    """处理单文件模式：生成/复用摘要，返回该文件 token 估计。"""
    md_file = memory_path / file_name
    if not md_file.exists():
        result["error"] = _("file_not_exist").format(name=file_name)
        return 0
    data = _build_summary(md_file, summary_path, regenerate)
    _emit_progress(progress_callback, 1, 1, file_name)
    if not data:
        result["errors"].append(_("process_failed").format(name=file_name))
        return 0
    result["summarized"].append(data)
    return data.get("token_estimate", 0)


def _parallel_build_summaries(md_files, summary_path, regenerate, max_workers, progress_callback):
    """线程池并行生成，返回 {md_file: data}。"""
    results = {}
    total = len(md_files)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        future_to_file = {
            ex.submit(_build_summary, mf, summary_path, regenerate): mf
            for mf in md_files
        }
        done = 0
        for future in concurrent.futures.as_completed(future_to_file):
            mf = future_to_file[future]
            try:
                data = future.result()
            except Exception:
                data = None
            results[mf] = data
            done += 1
            _emit_progress(progress_callback, done, total, mf.name)
    return results


def _summarize_directory(memory_path, summary_path, regenerate, max_workers, progress_callback, result):
    """目录模式：线程池并行生成摘要，确定性顺序收集，返回累计 token。"""
    md_files = sorted(_iter_memory_files(memory_path), key=lambda f: f.name)
    if not md_files:
        return 0

    # jieba 懒加载在并发首切易竞争；主线程先预热一次
    try:
        extract_keywords("warmup")
    except Exception as e:
        logger.warning("non-fatal: %s", e)

    if max_workers is None:
        max_workers = min(8, max(1, os.cpu_count() or 1))

    results = _parallel_build_summaries(md_files, summary_path, regenerate, max_workers, progress_callback)

    # 确定性顺序收集（与串行结果一致，便于测试/缓存）
    total_tokens = 0
    for mf in md_files:
        data = results.get(mf)
        if data:
            result["summarized"].append(data)
            total_tokens += data.get("token_estimate", 0)
        else:
            result["skipped"].append(mf.name)
    return total_tokens


def summarize_memory(workspace_path, file_name=None, regenerate=False, max_workers=None,
                     progress_callback=None):
    """生成/刷新记忆摘要。

    4.1 性能：目录模式用 ThreadPoolExecutor 并行生成（零依赖，标准库 concurrent.futures），
    主线程先预热 jieba 避免并发首切竞争。输出顺序与文件名字典序一致（确定性）。
    2.3 进度：progress_callback(done, total, name) 在每文件处理完后触发（None 表示不报告）。
    """
    base_path = Path(workspace_path).resolve()
    memory_path = base_path / ".workbuddy" / "memory"
    summary_path = base_path / ".workbuddy" / SUMMARY_DIR

    summary_path.mkdir(parents=True, exist_ok=True)

    result = {
        "version": VERSION,
        "timestamp": datetime.now().isoformat(),
        "summarized": [],
        "skipped": [],
        "errors": []
    }

    if not memory_path.exists():
        result["error"] = _("memory_dir_not_exist")
        return result

    if file_name:
        total_tokens = _summarize_named_file(
            memory_path, summary_path, file_name, regenerate, result, progress_callback)
    else:
        total_tokens = _summarize_directory(
            memory_path, summary_path, regenerate, max_workers, progress_callback, result)

    # 3.2 预算记账覆盖：summarize 消耗入账（D4）
    if total_tokens > 0:
        try:
            record_token_usage(workspace_path, total_tokens, operation="summarize")
        except Exception as e:
            logger.warning("non-fatal: %s", e)

    return result
