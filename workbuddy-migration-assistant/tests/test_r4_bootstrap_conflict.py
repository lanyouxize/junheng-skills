"""test_r4_bootstrap_conflict.py — BOOTSTRAP residual conflict guard (v1.2.1).

Covers the recoverable three-step sequence in import.py:
  ① backup BOOTSTRAP.md → ② overwrite IDENTITY/USER from package (atomic)
  → ③ delete BOOTSTRAP.md.
"""
import os
import sys
import tempfile
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent  # 技能根目录（相对定位，安装到任意位置均可自检）
sys.path.insert(0, str(SRC / "scripts"))
sys.path.insert(0, str(SRC))

from scripts import fs  # noqa: E402

# Import the helper from import.py (it is a script, so load as module)
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "wb_import_mod", SRC / "scripts" / "import.py"
)
wb_import = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wb_import)

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name + (("  | " + str(detail)) if detail and not cond else ""))


def test_bootstrap_conflict_cleaned():
    with tempfile.TemporaryDirectory(prefix="wb_r4_") as td:
        td = Path(td)
        pkg = td / "pkg"
        target = td / "target"
        pkg.mkdir()
        target.mkdir()
        (pkg / "IDENTITY.md").write_text("# 包内身份\n", encoding="utf-8")
        (pkg / "USER.md").write_text("# 包内用户\n", encoding="utf-8")
        (target / "BOOTSTRAP.md").write_text("# bootstrap 残留\n", encoding="utf-8")
        (target / "IDENTITY.md").write_text("# 目标端旧身份\n", encoding="utf-8")

        ts = fs.make_ts()
        res = wb_import._handle_bootstrap_conflict(pkg, target, ts)

        check("action=cleaned", res["action"] == "cleaned", res)
        check("BOOTSTRAP.md 已删除", not (target / "BOOTSTRAP.md").exists())
        check("IDENTITY.md 已覆盖为包内内容",
              (target / "IDENTITY.md").read_text(encoding="utf-8") == "# 包内身份\n")
        check("USER.md 已创建", (target / "USER.md").read_text(encoding="utf-8") == "# 包内用户\n")
        check("备份留证存在", res.get("backup") and Path(res["backup"]).exists(),
              res.get("backup"))
        check("overwritten 列表", res.get("overwritten") == ["IDENTITY.md", "USER.md"], res)


def test_no_bootstrap_no_action():
    with tempfile.TemporaryDirectory(prefix="wb_r4b_") as td:
        td = Path(td)
        pkg = td / "pkg"
        target = td / "target"
        pkg.mkdir()
        target.mkdir()
        (pkg / "IDENTITY.md").write_text("# 身份\n", encoding="utf-8")
        # no BOOTSTRAP.md on target
        res = wb_import._handle_bootstrap_conflict(pkg, target, fs.make_ts())
        check("无 BOOTSTRAP 时 action=none", res["action"] == "none", res)
        # no identity in package
        (target / "BOOTSTRAP.md").write_text("x\n", encoding="utf-8")
        (pkg / "IDENTITY.md").unlink()
        res2 = wb_import._handle_bootstrap_conflict(pkg, target, fs.make_ts())
        check("包内无身份文件时 action=none", res2["action"] == "none", res2)


if __name__ == "__main__":
    test_bootstrap_conflict_cleaned()
    test_no_bootstrap_no_action()
    print(f"\n==== RESULT: {len(PASS)} PASS / {len(FAIL)} FAIL ====")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)
