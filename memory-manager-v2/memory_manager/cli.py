import logging
logger = logging.getLogger(__name__)

# -*- coding: utf-8 -*-
"""
记忆管家 V3.0 - CLI 入口与参数校验
V3.0: 模块化重构；处理器与解析器拆分至 cli_handlers.py 以降低单文件长度。
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from .config import (
    VERSION, _, set_lang, get_colors, init_i18n,
)
from .cli_handlers import (
    _build_parser, _handle_rank_display, _handle_throttle,
    _handle_doctor, _handle_dedup, _handle_backup,
)
from .cli_commands import (
    _h_analyze, _h_search, _h_load, _h_summarize, _h_report,
    _h_cache_reminder, _h_cache_clean, _h_clean, _h_archive, _h_auto_clean,
    _h_export, _h_import, _h_config, _h_token_check, _h_token_trends, _h_scan,
    _h_prompt_list, _h_prompt_get, _h_prompt_save, _h_prompt_search, _h_self_test,
    _h_selector_audit, _h_describe,
)
from .cli_governance import (
    _h_govern, _h_snapshot, _h_compact, _h_dashboard, _h_health, _h_harden,
)

init_i18n()

# 命令 → 处理器 分发表（置于所有处理器导入之后，避免导入期引用未定义符号）
DISPATCH = {
    "analyze": _h_analyze, "search": _h_search, "load": _h_load,
    "rank": _handle_rank_display, "summarize": _h_summarize, "report": _h_report,
    "cache-reminder": _h_cache_reminder, "cache-clean": _h_cache_clean,
    "clean": _h_clean, "archive": _h_archive, "auto-clean": _h_auto_clean,
    "export": _h_export, "import": _h_import, "config": _h_config,
    "token-check": _h_token_check, "token-trends": _h_token_trends, "scan": _h_scan,
    "throttle": _handle_throttle,
    "prompt-list": _h_prompt_list, "prompt-get": _h_prompt_get,
    "prompt-save": _h_prompt_save, "prompt-search": _h_prompt_search,
    "doctor": _handle_doctor, "dedup": _handle_dedup, "backup": _handle_backup,
    "selector-audit": _h_selector_audit, "describe": _h_describe,
    "govern": _h_govern, "snapshot": _h_snapshot, "compact": _h_compact,
    "dashboard": _h_dashboard, "health": _h_health, "harden": _h_harden,
    "self-test": _h_self_test,
}

# 2.4 别名 → 规范命令名映射（argparse 会把 args.command 设为命中的别名，
# 故路由前归一为规范名，确保 dispatch / _validate_args 一致）。
ALIAS_MAP = {
    "stat": "analyze", "find": "search", "get": "load", "top": "rank",
    "sum": "summarize", "rep": "report", "crm": "cache-reminder",
    "cclean": "cache-clean", "rm": "clean", "ar": "archive",
    "aclean": "auto-clean", "exp": "export", "imp": "import", "cfg": "config",
    "tc": "token-check", "tt": "token-trends", "thr": "throttle",
    "doc": "doctor", "dd": "dedup", "bk": "backup",
    "pl": "prompt-list", "pg": "prompt-get", "ps": "prompt-save",
    "psearch": "prompt-search",
    "sel": "selector-audit", "sa": "selector-audit", "desc": "describe",
    "gv": "govern", "snap": "snapshot", "cp": "compact",
    "dash": "dashboard", "hlt": "health", "hd": "harden",
}


def _validate_args(args):
    """5.5 参数校验：workspace 不存在 / 非目录 / days<0 / limit<1 → 友好报错。"""
    C = get_colors()
    ws = getattr(args, 'workspace', None)
    workspace_commands = {
        'analyze', 'search', 'load', 'rank', 'summarize', 'report', 'cache-reminder',
        'cache-clean', 'clean', 'archive', 'auto-clean', 'export', 'import',
        'token-check', 'token-trends', 'scan', 'throttle',
        'prompt-list', 'prompt-get', 'prompt-save', 'prompt-search',
        'doctor', 'dedup', 'selector-audit', 'describe',
        'govern', 'snapshot', 'compact', 'dashboard', 'health', 'harden',
    }
    if args.command in workspace_commands and ws:
        p = Path(ws)
        if not p.exists():
            print(f"{C['red']}\u274c {_('workspace_not_exist').format(path=ws)}{C['reset']}")
            return 2
        if not p.is_dir():
            print(f"{C['red']}\u274c {_('workspace_not_dir').format(path=ws)}{C['reset']}")
            return 2
    days = getattr(args, 'days', None)
    if isinstance(days, int) and days < 0:
        print(f"{C['red']}\u274c {_('arg_days_invalid').format(days=days)}{C['reset']}")
        return 2
    limit = getattr(args, 'limit', None)
    if isinstance(limit, int) and limit < 1:
        print(f"{C['red']}\u274c {_('arg_limit_invalid').format(limit=limit)}{C['reset']}")
        return 2
    return 0


def _prescan_lang(argv):
    """在构建 parser 之前预扫 --lang，使 --help / 用法文本也能本地化。

    解析器在 main() 起始处构建，而 --lang 需经 parse_args 才能读到；
    不预扫则 --help 永远用默认语言渲染。返回 'zh'/'en' 或 None。
    """
    for i, tok in enumerate(argv):
        if tok == "--lang" and i + 1 < len(argv) and argv[i + 1] in ("zh", "en"):
            return argv[i + 1]
        if tok.startswith("--lang=") and tok.split("=", 1)[1] in ("zh", "en"):
            return tok.split("=", 1)[1]
    return None


def main():
    pre_lang = _prescan_lang(sys.argv[1:])
    if pre_lang:
        set_lang(pre_lang)
    parser = _build_parser()
    args = parser.parse_args()
    if args.command is not None and args.command in ALIAS_MAP:
        args.command = ALIAS_MAP[args.command]
    if hasattr(args, 'lang') and args.lang:
        set_lang(args.lang)
    rc = _validate_args(args)
    if rc:
        return rc
    if not args.command:
        parser.print_help()
        return 1
    handler = DISPATCH.get(args.command)
    if handler is None:
        parser.print_help()
        return 1
    result = handler(args)
    return result if isinstance(result, int) else 0


if __name__ == "__main__":
    sys.exit(main())
