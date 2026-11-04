#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B4 双写桥 CLI（薄壳；核心逻辑见 vault_writer.py）。

保留独立回填入口：当已有一批「采集 JSONL」需要补写进本地 vault 时使用，
例如对云端资料库里既有、但本地 vault 还没同步的记录做一次性回填。

用法：
  python sync_to_vault.py --in out/b3_live_5.jsonl --dry-run      # 预览
  python sync_to_vault.py --in out/b3_live_5.jsonl --apply        # 真实写入

常驻流水线入口见 write_to_library.py 的 --vault 开关（B3 分类后自动双写）。
"""
from vault_writer import main

if __name__ == "__main__":
    raise SystemExit(main())
