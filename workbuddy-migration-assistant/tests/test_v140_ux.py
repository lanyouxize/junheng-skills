"""test_v140_ux.py — v1.4.0 low-score-item fixes (TRACE external feedback).

Covers:
  - errors.humanize: common exceptions → 中文说明+下一步指引
  - fs.safe_delete: deletion guard (inside-root allowed, outside-root refused)
  - progress: throttled progress lines for large operations
"""
import json
import os
import sqlite3
import sys
import tempfile
import zipfile
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent  # 技能根目录（相对定位，安装到任意位置均可自检）
sys.path.insert(0, str(SRC))

from scripts.errors import humanize  # noqa: E402
from scripts import fs  # noqa: E402
from scripts import report as R  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name + (("  | " + str(detail)) if detail and not cond else ""))


def test_humanize_errors():
    e1 = sqlite3.OperationalError("database is locked")
    h1 = humanize(e1)
    check("sqlite locked → 中文+退出指引", "数据库被占用" in h1 and "退出" in h1)
    e2 = PermissionError(13, "Permission denied", r"C:\x\settings.json")
    h2 = humanize(e2)
    check("PermissionError → 权限说明", "没有写入权限" in h2 and "settings.json" in h2)
    e3 = FileNotFoundError(2, "No such file", r"C:\missing\dir")
    h3 = humanize(e3)
    check("FileNotFoundError → 路径说明", "路径不存在" in h3)
    e4 = zipfile.BadZipFile("File is not a zip file")
    h4 = humanize(e4)
    check("BadZipFile → 包损坏说明", "迁移包" in h4 and "重新" in h4)
    # 全部带技术细节尾巴
    for h in (h1, h2, h3, h4):
        check(f"技术细节附尾", "技术细节" in h)


def test_safe_delete_guard():
    with tempfile.TemporaryDirectory(prefix="wb_sd_") as td:
        td = Path(td)
        root = td / "root"
        root.mkdir()
        inside = root / "f.txt"
        inside.write_text("x", encoding="utf-8")
        outside = td / "outside.txt"
        outside.write_text("y", encoding="utf-8")
        # inside root: allowed
        check("root 内删除允许", fs.safe_delete(inside, root) is True and not inside.exists())
        # outside root: refused
        check("root 外删除拒绝", fs.safe_delete(outside, root) is False and outside.exists())
        # dir inside root: allowed
        d = root / "sub"
        d.mkdir()
        check("root 内目录删除允许", fs.safe_delete(d, root) is True and not d.exists())
        # missing path: False, no raise
        check("不存在路径返回 False", fs.safe_delete(root / "nope", root) is False)


def test_progress_throttle():
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        # tiny workload: silent
        for i in range(1, 11):
            R.progress(i, 10, "打包")
        # large workload: throttled ~10 lines + final
        for i in range(1, 101):
            R.progress(i, 100, "解压")
    out = buf.getvalue()
    check("小任务(<20)不输出进度", out.count("打包") == 0)
    lines = [l for l in out.splitlines() if "解压" in l]
    check("大任务输出节流进度(≤12行)", 1 <= len(lines) <= 12, len(lines))
    check("进度含百分比与计数", "100%" in out and "(100/100)" in out)


def test_export_has_progress_line():
    """Real export on the regression fixture should print at least one progress line."""
    import subprocess
    workdir = tempfile.mkdtemp(prefix="wb_prog_")
    try:
        root = os.path.join(workdir, "root")
        for i in range(25):  # ≥20 files so progress fires
            d = os.path.join(root, "skills", f"s{i}")
            os.makedirs(d)
            open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8").write("x")
        out_zip = os.path.join(workdir, "t.zip")
        r = subprocess.run(
            [sys.executable, "scripts/export.py", "--source", root, "--output", out_zip,
             "--no-conversations", "--no-credentials"],
            capture_output=True, text=True, cwd=str(SRC),
        )
        check("导出成功", r.returncode == 0, r.stderr[-200:])
        check("导出输出含进度行", "[进度]" in r.stdout, r.stdout[-200:])
    finally:
        import shutil
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    test_humanize_errors()
    test_safe_delete_guard()
    test_progress_throttle()
    test_export_has_progress_line()
    print(f"\n==== RESULT: {len(PASS)} PASS / {len(FAIL)} FAIL ====")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)
