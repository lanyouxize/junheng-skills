# -*- coding: utf-8 -*-
"""Support python -m memory_manager invocation."""

import sys

from .cli import main

if __name__ == "__main__":
    # 5.5：将 main() 的返回值（如参数校验的退出码 2）正确传播给进程；
    # 部分命令 handler 返回 dict（诊断结果），非 int 时按成功(0)处理，避免 sys.exit(dict) 报错。
    rc = main()
    sys.exit(rc if isinstance(rc, int) else 0)
