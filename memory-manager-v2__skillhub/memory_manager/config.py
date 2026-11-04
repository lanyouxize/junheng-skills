import logging
logger = logging.getLogger(__name__)

# -*- coding: utf-8 -*-
"""
记忆管家 V3.0 - 配置与工具函数模块
来源: memory_manager.py (常量/i18n/安全/工具函数)
V3.0: 模块化重构，零依赖（仅标准库）
"""

import json
import os
import sys
import gzip
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Iterator
from functools import lru_cache

# ============ 跨平台初始化 ============
if sys.platform == 'win32':
    try:
        import io
        if not isinstance(sys.stdout, io.TextIOWrapper):
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        if not isinstance(sys.stderr, io.TextIOWrapper):
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception as e:
        logger.warning("non-fatal: %s", e)


# ============ 全局缓存 ============
_CONFIG_CACHE = None
_CONFIG_CACHE_TIME = 0
_CONFIG_CACHE_KEY = "global"
_CONFIG_CACHE_TTL = 300

# ============ i18n 翻译支持 ============
_LANG = "zh"
_I18N_DATA = None

def init_i18n(lang="zh"):
    global _LANG, _I18N_DATA
    _LANG = lang
    i18n_path = Path(__file__).parent.parent / "i18n.json"
    if i18n_path.exists():
        try:
            # 文件大小预检（i18n.json 通常不超过 50KB）
            if i18n_path.stat().st_size > 100 * 1024:
                _I18N_DATA = {"zh": {}, "en": {}}
                return
            with open(i18n_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            # 完整性校验：必须是 dict，且至少包含 zh/en 键
            if not isinstance(data, dict) or not all(k in data for k in ("zh", "en")):
                _I18N_DATA = {"zh": {}, "en": {}}
                return
            _I18N_DATA = data
        except (json.JSONDecodeError, OSError, IOError):
            _I18N_DATA = {"zh": {}, "en": {}}
    else:
        _I18N_DATA = {"zh": {}, "en": {}}

def _(key: str) -> str:
    global _LANG, _I18N_DATA
    if _I18N_DATA is None:
        init_i18n()
    return _I18N_DATA.get(_LANG, {}).get(key, key)

def set_lang(lang: str):
    if lang in ("zh", "en"):
        init_i18n(lang)

# ============ 常量定义 ============
VERSION = "4.0.6"

TOKEN_RATIO = 2
MAX_OUTPUT_CHARS = 300

MEMORY_LARGE_SIZE_KB = 100
MEMORY_VERY_LARGE_SIZE_KB = 500
MEMORY_MANY_FILES = 20
MEMORY_VERY_MANY_FILES = 100
SCAN_LARGE_CACHE_KB = 50
DEFAULT_RETENTION_DAYS = 1
PERSONAL_WORK_REMIND_DAYS = 5
TOKEN_STATS_RETENTION_DAYS = 30
RECENT_DAYS = 7
OLD_DAYS = 30
SUMMARY_MIN_CHARS = 500

TOKEN_WARN_RATIO = 0.7
TOKEN_ALERT_RATIO = 1.0
DEFAULT_DAILY_BUDGET = 10000

PROTECTED_DIRS = {'memory'}

CLEANABLE_EXTS = {'.tmp', '.log', '.cache', '.bak', '.temp', '.swp', '.pyc', '__pycache__'}

# config_memory() 值域白名单：key → (最小值, 最大值)，None 表示无需范围校验
CONFIG_VALUE_LIMITS = {
    "retention_days": (1, 365),
    "auto_remind_days": (1, 90),
    "auto_archive": None,       # bool, 无需范围校验
    "lang": None,               # 枚举校验在 config_memory() 内处理
}
IMAGE_SIGNATURES = {
    'png': b'\x89PNG\r\n\x1a\n',
    'jpg': b'\xff\xd8\xff',
    'gif': b'GIF87a',
    'gif89': b'GIF89a',
    'bmp': b'BM',
    'webp': b'RIFF',
    'ico': b'\x00\x00\x01\x00',
}
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.ico'}

MAX_FILE_SIZE = 1 * 1024 * 1024
MAX_TOTAL_READ = 5 * 1024 * 1024
MAX_REPORT_ITEMS = 1000

SUMMARY_DIR = ".summary"
SUMMARY_MAX_CHARS = 300
SUMMARY_INDEX_FILE = "summary_index.json"

RANK_CORE_THRESHOLD = 0.7
RANK_NORMAL_THRESHOLD = 0.3

LOAD_BRIEF = "brief"
LOAD_NORMAL = "normal"
LOAD_FULL = "full"

try:
    from colorama import init, Fore, Style
    init(autoreset=True)
    C = {
        'red': Fore.RED, 'green': Fore.GREEN, 'yellow': Fore.YELLOW,
        'cyan': Fore.CYAN, 'magenta': Fore.MAGENTA, 'white': Fore.WHITE,
        'bright': Style.BRIGHT, 'reset': Style.RESET_ALL
    }
except ImportError:
    C = {k: '' for k in ['red', 'green', 'yellow', 'cyan', 'magenta', 'white', 'bright', 'reset']}

def get_colors():
    return C

# ============ 配置 ============
_GLOBAL_CONFIG_FILE = str(Path.home() / ".workbuddy" / "skills" / "memory-manager-v2" / "config.json")

def _migrate_v2_config():
    """配置目录统一为 memory-manager-v2（沿用 SkillHub 预留 ID）；
    兼容旧安装：若旧配置位于 memory-manager-v3 或 memory-manager-v2 目录，自动并入 v2。"""
    new_dir = Path.home() / ".workbuddy" / "skills" / "memory-manager-v2"
    for old_dir in (
        Path.home() / ".workbuddy" / "skills" / "memory-manager-v3",
        Path.home() / ".workbuddy" / "skills" / "memory-manager-v2",
    ):
        old_cfg = old_dir / "config.json"
        if old_dir != new_dir and old_cfg.exists() and not new_dir.exists():
            try:
                new_dir.mkdir(parents=True, exist_ok=True)
                import shutil
                shutil.copy2(old_cfg, new_dir / "config.json")
                break
            except (OSError, IOError, PermissionError) as e:
                logger.warning("non-fatal: %s", e)
        # 迁移失败不影响正常使用

_migrate_v2_config()

def _get_workspace_config_path(workspace_path=None):
    base = Path(workspace_path).resolve() if workspace_path else Path.cwd().resolve()
    # 安全边界校验：拒绝不存在或可疑路径
    if not base.exists():
        base.mkdir(parents=True, exist_ok=True)
    if not base.is_dir():
        return None
    # 确保路径规范化后不含路径穿越分量
    try:
        base.relative_to(base.resolve())
    except ValueError:
        return None
    return str(base / ".workbuddy" / "skills" / "memory-manager-v2" / "config.json")

DEFAULT_CONFIG = {
    "lang": "zh",
    "retention_days": 1,
    "auto_remind_days": 5,
    "auto_archive": True,
    "last_remind_date": "",
    "last_clean_date": "",
    "_automation_rules": {
        "push_content": {
            "retention_days": 1,
            "auto_clean": True,
            "keywords": ["推送", "AI动态", "历史推送摘要", "每日AI", "动态推送", "新闻推送"]
        },
        "personal_work_content": {
            "retention_days": 7,
            "auto_clean": False,
            "remind_days": 5,
            "keywords": ["个人", "工作", "项目", "客户", "企业", "MEMORY.md"]
        }
    }
}

# 分类关键词默认值随界面语言切换：en 用户默认用英文关键词，
# 避免 en 模式输出（config 命令）与持久化配置里出现中文。
_AUTOMATION_KEYWORDS = {
    "zh": {
        "push": ["推送", "AI动态", "历史推送摘要", "每日AI", "动态推送", "新闻推送"],
        "personal_work": ["个人", "工作", "项目", "客户", "企业", "MEMORY.md"],
    },
    "en": {
        "push": ["push", "AI digest", "daily AI", "news digest", "news push", "daily brief"],
        "personal_work": ["personal", "work", "project", "client", "company", "MEMORY.md"],
    },
}


def default_automation_rules():
    """按当前界面语言返回 _automation_rules 默认值（每次新副本，避免共享可变对象）。"""
    kw = _AUTOMATION_KEYWORDS.get(_LANG, _AUTOMATION_KEYWORDS["zh"])
    return {
        "push_content": {"retention_days": 1, "auto_clean": True,
                         "keywords": list(kw["push"])},
        "personal_work_content": {"retention_days": 7, "auto_clean": False,
                                  "remind_days": 5, "keywords": list(kw["personal_work"])},
    }


def _merge_global_lang_config(config):
    """合并全局 config.json 中的 lang 设置到 config。"""
    global_cfg_path = Path(_GLOBAL_CONFIG_FILE)
    if not global_cfg_path.exists():
        return
    try:
        with open(global_cfg_path, 'r', encoding='utf-8') as f:
            user_global = json.load(f)
        if "lang" in user_global:
            config["lang"] = user_global["lang"]
    except (json.JSONDecodeError, IOError, PermissionError) as e:
        logger.warning("non-fatal: %s", e)


def _merge_workspace_config(ws_cfg_path, config, workspace_path):
    """合并工作空间 config.json 到 config；不存在则创建默认。"""
    try:
        if ws_cfg_path.exists():
            with open(ws_cfg_path, 'r', encoding='utf-8') as f:
                user_ws = json.load(f)
            config.update(user_ws)
        else:
            save_config(config, workspace_path)
    except (json.JSONDecodeError, IOError, PermissionError) as e:
        logger.warning("non-fatal: %s", e)


def load_config(workspace_path=None):
    global _CONFIG_CACHE, _CONFIG_CACHE_TIME, _CONFIG_CACHE_KEY
    cache_key = workspace_path or "global"
    now = datetime.now().timestamp()
    if _CONFIG_CACHE is not None and (now - _CONFIG_CACHE_TIME) < _CONFIG_CACHE_TTL and _CONFIG_CACHE_KEY == cache_key:
        return _CONFIG_CACHE

    config = DEFAULT_CONFIG.copy()
    config["_automation_rules"] = default_automation_rules()
    _merge_global_lang_config(config)

    ws_cfg_path_str = _get_workspace_config_path(workspace_path)
    if ws_cfg_path_str is None:
        # workspace_path 无效，仅返回全局配置
        _CONFIG_CACHE = config
        _CONFIG_CACHE_TIME = now
        _CONFIG_CACHE_KEY = cache_key
        return config

    ws_cfg_path = Path(ws_cfg_path_str)
    _merge_workspace_config(ws_cfg_path, config, workspace_path)

    _CONFIG_CACHE = config
    _CONFIG_CACHE_TIME = now
    _CONFIG_CACHE_KEY = cache_key
    return config

def clear_config_cache():
    global _CONFIG_CACHE, _CONFIG_CACHE_TIME, _CONFIG_CACHE_KEY
    _CONFIG_CACHE = None
    _CONFIG_CACHE_TIME = 0
    _CONFIG_CACHE_KEY = "global"

def save_config(config, workspace_path=None):
    global_settings = {k: v for k, v in config.items() if k in ("lang",)}
    if global_settings:
        global_path = Path(_GLOBAL_CONFIG_FILE)
        global_path.parent.mkdir(parents=True, exist_ok=True)
        existing_global = {}
        if global_path.exists():
            try:
                with open(global_path, 'r', encoding='utf-8') as f:
                    existing_global = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning("non-fatal: %s", e)

        existing_global.update(global_settings)
        with open(global_path, 'w', encoding='utf-8') as f:
            json.dump(existing_global, f, ensure_ascii=False, indent=2)

    ws_settings = {k: v for k, v in config.items() if k not in ("lang",)}
    cfg_path_str = _get_workspace_config_path(workspace_path)
    if cfg_path_str is not None:
        cfg_path = Path(cfg_path_str)
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cfg_path, 'w', encoding='utf-8') as f:
            json.dump(ws_settings, f, ensure_ascii=False, indent=2)
    clear_config_cache()

def config_memory(workspace_path, key=None, value=None):
    config = load_config()
    result = {"action": "view", "config": config}

    if key is not None and value is not None:
        if key not in DEFAULT_CONFIG:
            return {"error": _("unknown_config_key").format(key=key, keys=list(DEFAULT_CONFIG.keys()))}
        default_type = type(DEFAULT_CONFIG[key])
        try:
            typed_value = default_type(value)
        except (ValueError, TypeError):
            return {"error": _("value_type_error").format(value=value, type=default_type.__name__)}

        # 值域白名单校验
        if key == "lang" and typed_value not in ("zh", "en"):
            return {"error": _("invalid_lang_value").format(value=typed_value)}
        if key in CONFIG_VALUE_LIMITS and CONFIG_VALUE_LIMITS[key] is not None:
            lo, hi = CONFIG_VALUE_LIMITS[key]
            if not (lo <= typed_value <= hi):
                return {"error": _("value_out_of_range").format(value=typed_value, lo=lo, hi=hi)}

        config[key] = typed_value
        save_config(config)
        result = {"action": "update", "key": key, "value": typed_value, "config": config}

    return result

# ============ 安全函数 ============
def is_symlink(path):
    try:
        return path.is_symlink()
    except (OSError, ValueError):
        return False

def safe_resolve(path, base_path):
    try:
        abs_path = path.resolve()
        abs_base = base_path.resolve()
        try:
            abs_path.relative_to(abs_base)
            return abs_path
        except ValueError:
            return None
    except (OSError, ValueError):
        return None

def safe_file_read(path, max_size=MAX_FILE_SIZE):
    try:
        mtime = path.stat().st_mtime
    except (OSError, ValueError):
        mtime = 0
    return _safe_file_cached(str(path.resolve()), max_size, mtime)

@lru_cache(maxsize=128)
def _safe_file_cached(path_str, max_size, mtime=0):
    path = Path(path_str)
    try:
        if is_symlink(path):
            return None, _("skip_symlink")

        stat = path.stat()
        if stat.st_size > max_size:
            return None, _("file_over_limit_msg").format(limit=max_size // 1024)

        chunk_size = 64 * 1024
        chunks = []
        bytes_read = 0

        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            while bytes_read < max_size:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                chunks.append(chunk)
                bytes_read += len(chunk.encode('utf-8', errors='ignore'))

        content = ''.join(chunks)
        if len(content.encode('utf-8')) > max_size:
            content = content[:max_size]
        return content, _("success")
    except Exception as e:
        return None, _("read_failed_short").format(error=type(e).__name__)

def get_file_info(path):
    return _get_file_info_cached(str(path.resolve()))

@lru_cache(maxsize=256)
def _get_file_info_cached(path_str):
    try:
        path = Path(path_str)
        stat = path.stat()
        return datetime.fromtimestamp(stat.st_mtime), stat.st_size / 1024
    except (OSError, ValueError):
        return None, None

def iter_memory_files(memory_path, skip_symlinks=True, skip_memory_md=True, include_dirs=False):
    """迭代记忆文件（支持子目录递归扫描）

    Args:
        memory_path: .workbuddy/memory/ 路径
        skip_symlinks: 跳过符号链接
        skip_memory_md: 跳过 MEMORY.md
        include_dirs: 是否返回子目录信息
    """
    if not memory_path.exists():
        return
    for md_file in memory_path.rglob("*.md"):
        if skip_symlinks and is_symlink(md_file):
            continue
        if skip_memory_md and md_file.name == "MEMORY.md":
            continue
        # 安全：确保文件仍在 memory_path 下（防止路径穿越）
        try:
            md_file.resolve().relative_to(memory_path.resolve())
        except ValueError:
            continue
        mtime, size_kb = get_file_info(md_file)
        if mtime is None:
            continue
        # 计算相对于 memory_path 的路径（含子目录信息）
        rel_path = str(md_file.relative_to(memory_path))
        yield md_file, mtime, size_kb, rel_path

def _match_image_signature(header):
    """根据文件头匹配图片格式（含 webp 二次校验）。"""
    for fmt, sig in IMAGE_SIGNATURES.items():
        if not header.startswith(sig):
            continue
        if fmt == 'webp':
            if len(header) >= 12 and header[8:12] == b'WEBP':
                return 'webp'
            continue
        return fmt
    return None


def detect_image_format(file_path):
    try:
        with open(file_path, 'rb') as f:
            header = f.read(16)
        return _match_image_signature(header)
    except (OSError, IOError):
        return None


def _strip_value_quotes(value):
    """去除前后引号。"""
    if (value.startswith('"') and value.endswith('"')) or \
       (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    return value


def _parse_fm_tags(value):
    """解析 tags 字段为列表。"""
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    return [t.strip().strip('"\'') for t in value.split(",") if t.strip()]


def _parse_fm_line(line, meta):
    """解析单行 front-matter 字段，写入 meta。"""
    if ":" not in line:
        return
    key, _, value = line.partition(":")
    key = key.strip()
    value = value.strip()

    if not value:
        return

    # 解析 tags: [tag1, tag2] 或 tags: tag1, tag2
    if key == "tags":
        meta["tags"] = _parse_fm_tags(value)
        return

    meta[key] = _strip_value_quotes(value)


def parse_front_matter(content):
    """解析 Markdown 文件的 front-matter（YAML 头部）

    支持格式:
        ---
        tags: [tag1, tag2]
        category: project-name
        ---

    Returns:
        dict: {tags: list, category: str, ...其他自定义字段}
    """
    meta = {}
    if not content or not content.startswith("---"):
        return meta

    try:
        end = content.index("---", 3)
    except ValueError:
        return meta

    fm_text = content[3:end].strip()
    for line in fm_text.split("\n"):
        _parse_fm_line(line.strip(), meta)

    return meta
