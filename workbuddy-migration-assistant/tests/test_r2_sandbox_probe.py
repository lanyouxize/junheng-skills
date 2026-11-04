"""test_r2_sandbox_probe.py — strip_write pre-probe (v1.2.1).

Covers:
  - probe returns writable=True for a normal temp dir
  - probe cache works (second call no re-write)
  - check() returns None when all writable
  - ERROR_CODE / FIX_HINT surface
"""
import os
import sys
import tempfile
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent  # 技能根目录（相对定位，安装到任意位置均可自检）
sys.path.insert(0, str(SRC))

from scripts import sandbox_probe as SP  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name + (("  | " + str(detail)) if detail and not cond else ""))


def test_probe_writable():
    with tempfile.TemporaryDirectory(prefix="wb_sp_") as td:
        ok = SP.probe([Path(td)])
        check("正常目录可写探测 True", ok.get(td) is True, ok)
        # sentinel cleaned up
        leftovers = [p for p in Path(td).iterdir() if p.name.startswith(".wb-probe-")]
        check("哨兵文件已清理", len(leftovers) == 0, leftovers)


def test_probe_cache():
    with tempfile.TemporaryDirectory(prefix="wb_sp2_") as td:
        SP.reset_cache()
        d = Path(td)
        r1 = SP.probe([d])
        r2 = SP.probe([d])
        check("缓存命中（两次结果一致）", r1 == r2)
        # cache size should be 1 after dedup
        check("缓存仅 1 条", len(SP._cache) == 1, SP._cache)


def test_check_all_writable():
    with tempfile.TemporaryDirectory(prefix="wb_sp3_") as td:
        SP.reset_cache()
        res = SP.check([Path(td)])
        check("check() 全部可写返回 None", res is None)


def test_error_constants():
    check("ERROR_CODE 定义", SP.ERROR_CODE == "E_PROBE_WRITE_DENIED")
    check("FIX_HINT 中文提示存在", "沙箱" in SP.FIX_HINT and "重跑" in SP.FIX_HINT)


if __name__ == "__main__":
    test_probe_writable()
    test_probe_cache()
    test_check_all_writable()
    test_error_constants()
    print(f"\n==== RESULT: {len(PASS)} PASS / {len(FAIL)} FAIL ====")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)
