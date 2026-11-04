#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一入口：python collect.py <mode> [--config X] [--yes] ...

mode: url | account | desktop | exe | write
各模式模块实现 register(subparsers) / run(args) -> int 契约（见各模块 docstring）；
采集层输出统一 JSONL（25 列记录，status=fail 的行在写库前被过滤）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import EXIT_PARAM, attest  # noqa: E402

_MODULES = (
    "l1_fetch_urls",
    "l2_fetch_account",
    "l3_drive_wechat",
    "exe_wrapper",
    "write_to_library",
    "refresh",
)


def build_parser() -> argparse.ArgumentParser:
    # default=SUPPRESS：避免子命令默认值覆盖主解析器已解析的 --config/--yes
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--config", default=argparse.SUPPRESS,
        help="YAML 配置路径（默认内置 DEFAULT_CONFIG，可复制 config.example.yaml）",
    )
    common.add_argument(
        "--yes", action="store_true", default=argparse.SUPPRESS,
        help="合规闸：确认已获授权（非交互/自动化必填）",
    )

    parser = argparse.ArgumentParser(prog="collect.py", description=__doc__, parents=[common])
    sub = parser.add_subparsers(dest="mode", metavar="<mode>")

    for module_name in _MODULES:
        module = __import__(module_name)
        module.register(sub)

    parser.set_defaults(func=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "mode", None):
        parser.print_help()
        return EXIT_PARAM
    # refresh 把 --yes/--config 放在子命令层（其参数在 rest 中），由 refresh 自行 attest；
    # 其余模式沿用顶层合规闸。
    if args.mode != "refresh" and not attest(args):
        return 4
    handler = getattr(args, "func", None)
    if handler is None:
        parser.print_help()
        return EXIT_PARAM
    return int(handler(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
