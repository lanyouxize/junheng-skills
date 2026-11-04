# -*- coding: utf-8 -*-
"""
记忆管家 V3.10 - 选择器可见性 & 陈旧治理（selector / staleness）

【为什么是这个设计】2026-09 三级核实（官方文档 + 架构资料 + 本机日志）：
- 平台内置 `memorySelector` agent：描述 "Select relevant memories for the current query."，
  0 工具、lite 模型；配合 settings `memory.relevanceSelection`（默认 true），每次用户查询
  读取「候选记忆清单（文件名 + 描述）」+ query，**最多 5 条**注入上下文。
- 平台不提供「过滤 / 替换记忆注入」的钩子（Hooks 仅生命周期事件：Stop / SessionEnd /
  PreCompact / SubagentStop）。
=> 技能无法拦截注入；对 token 的唯一真实杠杆是【候选池质量】：
   L1 可见性：记忆文件必须有高信息量的 description，选择器读得到才选得准；
   L2 槽位压力：候选数远大于 5 时陈旧项挤占槽位、稀释选择质量；
   L3 时效：陈旧内容在加载排序中自然降权（见 recency_factor / core_load 复用）。

本模块只读 + 可恢复写入（仅补 front-matter description），默认 dry-run 预览，绝不删除。
"""
import os
import re
from datetime import datetime
from pathlib import Path

from .config import (
    VERSION, _, TOKEN_RATIO,
    safe_file_read, iter_memory_files, parse_front_matter,
)

SLOT_CAPACITY = 5
STALE_DAYS_DEFAULT = 30
FRESH_DAYS = 7
RECENCY_HALF_LIFE_DAYS = 90
RECENCY_FLOOR = 0.35

_MD_PREFIX_RE = re.compile(r'^\s*(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+|>\s*)')
_DATE_NAME_RE = re.compile(r'^\d{4}[-_]?\d{2}[-_]?\d{2}([-_].*)?$')


def _est_tokens(text):
    """与项目口径一致的粗略 token 估算（字符数 / TOKEN_RATIO）。"""
    if not text:
        return 0
    return max(1, len(text) // max(TOKEN_RATIO, 1))


def _clean_line(line):
    """去掉 markdown 前缀与装饰符号，得到纯文本。"""
    return _MD_PREFIX_RE.sub('', line).strip().strip('`*_ ')


def _name_is_self_describing(name):
    """判断文件名本身是否自带语义（如 `deploy-notes.md` 是，`2026-05-16.md` 不是）。"""
    stem = name[:-3] if name.lower().endswith('.md') else name
    if stem.upper() in ('MEMORY', 'README', 'INDEX'):
        return True
    if _DATE_NAME_RE.match(stem):
        return False
    return len(re.sub(r'[^0-9A-Za-z\u4e00-\u9fff]+', '', stem)) >= 3


def _first_heading(lines):
    for line in lines:
        if line.strip().startswith('#'):
            text = _clean_line(line)
            if text:
                return text
    return ""


def _first_points(lines, limit=2):
    """抓取前若干条要点（- / * / 1. ），供 description 使用。"""
    out = []
    for line in lines:
        s = line.strip()
        if not s or s.startswith('#'):
            continue
        is_bullet = s[:2] in ('- ', '* ') or (len(s) > 2 and s[0].isdigit() and s[1] in '.)')
        if is_bullet:
            text = _clean_line(s)
            if text:
                out.append(text)
        if len(out) >= limit:
            break
    return out


def describe_from_content(content, max_chars=160):
    """提炼选择器可读的 description。

    返回 (description, source)；source ∈ {front_matter, heading, none}。
    front-matter 里已有 description/summary 时直接采用（幂等，不覆盖）。
    """
    if not content:
        return "", "none"
    meta = parse_front_matter(content)
    for key in ("description", "summary", "desc"):
        value = meta.get(key)
        if value:
            return str(value)[:max_chars], "front_matter"
    lines = [l for l in content.splitlines() if not l.strip().startswith(('---', '<!--'))]
    parts = ([_first_heading(lines)] if _first_heading(lines) else []) + _first_points(lines)
    parts = [p for p in parts if p]
    if not parts:
        first = next((l.strip() for l in lines if l.strip()), "")
        if not first:
            return "", "none"
        parts = [_clean_line(first)]
    return " · ".join(parts)[:max_chars], "heading"


def freshness_grade(age_days, stale_days=STALE_DAYS_DEFAULT):
    """按天数分级：fresh(≤7) / aging(≤stale_days) / stale(>stale_days)。"""
    if age_days <= FRESH_DAYS:
        return "fresh"
    if age_days <= stale_days:
        return "aging"
    return "stale"


def recency_factor(mtime, half_life_days=RECENCY_HALF_LIFE_DAYS, floor=RECENCY_FLOOR):
    """时效衰减因子：新=1.0，每过一个半衰期减半，下限 floor（保证不归零）。"""
    if mtime is None:
        return 1.0
    age = max((datetime.now() - mtime).days, 0)
    return max(floor, 0.5 ** (age / max(half_life_days, 1)))


def _visibility_score(has_desc, self_desc, grade, desc_len):
    """选择器就绪度 0-100：front-matter 描述 40 / 语义文件名 20 / 新鲜度 30 / 描述长度 10。"""
    score = 40 if has_desc else (20 if desc_len else 0)
    if self_desc:
        score += 20
    score += {"fresh": 30, "aging": 20, "stale": 5}.get(grade, 10)
    score += min(desc_len, 60) // 6
    return min(score, 100)


def _file_entry(md_file, rel_path, mtime, size_kb, stale_days):
    """构造单文件的可见性条目。"""
    content, _read_err = safe_file_read(md_file)
    desc, source = describe_from_content(content or "")
    age = max((datetime.now() - mtime).days, 0)
    grade = freshness_grade(age, stale_days)
    self_desc = _name_is_self_describing(md_file.name)
    return {
        "file": md_file.name,
        "path": rel_path,
        "size_kb": round(size_kb, 2),
        "modified": mtime.strftime("%Y-%m-%d"),
        "age_days": age,
        "freshness": grade,
        "description": desc,
        "description_source": source,
        "self_describing_name": self_desc,
        "selector_visible": bool(desc),
        "readiness": _visibility_score(source == "front_matter", self_desc, grade, len(desc)),
        "doc_tokens_estimate": _est_tokens(content or ""),
    }


def _pressure_level(pressure):
    if pressure <= 1:
        return "ok"
    if pressure <= 2:
        return "elevated"
    return "severe"


def _summarize(files):
    """汇总候选池指标：槽位压力 / 可见率 / 陈旧量 / 可回收 token。"""
    n = len(files)
    visible = sum(1 for f in files if f["selector_visible"])
    stale = [f["file"] for f in files if f["freshness"] == "stale"]
    missing = [f["file"] for f in files if f["description_source"] != "front_matter"]
    pressure = round(n / SLOT_CAPACITY, 2) if SLOT_CAPACITY else 0.0
    return {
        "candidate_count": n,
        "slot_capacity": SLOT_CAPACITY,
        "slot_pressure": pressure,
        "slot_pressure_level": _pressure_level(pressure),
        "selector_visible_count": visible,
        "selector_visible_ratio": round(visible / n, 3) if n else 0.0,
        "avg_readiness": round(sum(f["readiness"] for f in files) / n, 1) if n else 0.0,
        "stale_files": stale,
        "stale_count": len(stale),
        "frontmatter_missing": missing,
        "reclaimable_tokens_estimate": sum(
            f["doc_tokens_estimate"] for f in files if f["freshness"] == "stale"),
        "total_tokens_estimate": sum(f["doc_tokens_estimate"] for f in files),
    }


def _build_issues(metrics, stale_days):
    """由指标推导问题与建议（纯函数，便于测试）。"""
    issues, recs = [], []
    if metrics["candidate_count"] == 0:
        return issues, [_("selector_no_files")]
    if metrics["frontmatter_missing"]:
        issues.append(_("selector_issue_missing_desc").format(
            count=len(metrics["frontmatter_missing"])))
        recs.append(_("selector_rec_describe"))
    if metrics["slot_pressure_level"] != "ok":
        issues.append(_("selector_issue_slot_pressure").format(
            candidates=metrics["candidate_count"], cap=SLOT_CAPACITY,
            pressure=metrics["slot_pressure"]))
        recs.append(_("selector_rec_merge"))
    if metrics["stale_files"]:
        issues.append(_("selector_issue_stale").format(
            count=metrics["stale_count"], days=stale_days,
            tokens=metrics["reclaimable_tokens_estimate"]))
        recs.append(_("selector_rec_archive").format(days=stale_days))
    if not issues:
        recs.append(_("selector_rec_ok"))
    return issues, recs


def selector_audit(workspace_path, stale_days=STALE_DAYS_DEFAULT):
    """审计工作区记忆的「选择器可见性 + 槽位压力 + 陈旧度」，只读。"""
    memory_path = Path(workspace_path).resolve() / ".workbuddy" / "memory"
    result = {
        "version": VERSION,
        "timestamp": datetime.now().isoformat(),
        "workspace": workspace_path,
        "stale_days": stale_days,
        "slot_capacity": SLOT_CAPACITY,
        "files": [],
        "metrics": {},
        "issues": [],
        "recommendations": [],
    }
    if not memory_path.exists():
        result["error"] = _("memory_dir_not_exist")
        return result

    files = [
        _file_entry(md_file, rel_path, mtime, size_kb, stale_days)
        for md_file, mtime, size_kb, rel_path in iter_memory_files(memory_path, skip_memory_md=False)
    ]
    files.sort(key=lambda f: (f["readiness"], -f["age_days"]))
    result["files"] = files
    result["metrics"] = _summarize(files)
    result["issues"], result["recommendations"] = _build_issues(result["metrics"], stale_days)
    return result


def _has_frontmatter(content):
    """是否已有 YAML front-matter（含闭合分隔符）。"""
    return content.startswith("---") and "---" in content[3:]


def _insert_description(content, desc, has_fm):
    """把 description 写入 front-matter：已有则插入，没有则新建。"""
    line = "description: " + desc
    if has_fm:
        end = content.index("---", 3)
        return content[:end].rstrip() + "\n" + line + "\n" + content[end:]
    return "---\n" + line + "\n---\n\n" + content


def _write_atomic(path, text):
    """原子写（tmp + os.replace），失败返回 False，绝不留下半截文件。"""
    try:
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
        return True
    except (OSError, IOError):
        return False


def apply_descriptions(workspace_path, dry_run=True, stale_days=STALE_DAYS_DEFAULT):
    """为缺少 front-matter description 的记忆补写描述（默认 dry-run 预览，可恢复）。"""
    memory_path = Path(workspace_path).resolve() / ".workbuddy" / "memory"
    result = {
        "version": VERSION,
        "timestamp": datetime.now().isoformat(),
        "workspace": workspace_path,
        "dry_run": bool(dry_run),
        "planned": [],
        "applied": [],
        "skipped": [],
    }
    if not memory_path.exists():
        result["error"] = _("memory_dir_not_exist")
        return result

    for md_file, _mtime, _size_kb, rel_path in iter_memory_files(memory_path, skip_memory_md=False):
        content, _read_err = safe_file_read(md_file)
        if content is None:
            result["skipped"].append({"file": rel_path, "reason": "unreadable"})
            continue
        if parse_front_matter(content).get("description"):
            result["skipped"].append({"file": rel_path, "reason": "already_described"})
            continue
        desc, source = describe_from_content(content)
        if not desc:
            result["skipped"].append({"file": rel_path, "reason": "no_content"})
            continue
        item = {"file": rel_path, "description": desc, "source": source}
        if dry_run:
            result["planned"].append(item)
        elif _write_atomic(md_file, _insert_description(content, desc, _has_frontmatter(content))):
            result["applied"].append(item)
        else:
            result["skipped"].append({"file": rel_path, "reason": "write_failed"})
    return result
