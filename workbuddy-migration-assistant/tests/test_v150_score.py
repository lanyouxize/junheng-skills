"""test_v150_score.py — v1.5.0 SkillHub score-driven iteration.

Covers:
  - errors.ERROR_CODES stable registry + humanize() prefixing [E-xxx]
  - export --profile lite preset (manifest option, credentials dropped)
  - import --profile auto preset + verify section (all-present verdict)
  - _verify_import() missing detection (has-missing verdict + missing list)
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

SRC = Path(__file__).resolve().parent.parent  # 技能根目录（相对定位，安装到任意位置均可自检）
sys.path.insert(0, str(SRC))

from scripts.errors import humanize, ERROR_CODES  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name + (("  | " + str(detail)) if detail and not cond else ""))


UID = "a1b2c3d4e5f60718293a4b5c6d7e8f90"
TGT_UID = "f0e9d8c7b6a54433221100ffeeddccb0"
ENV = dict(os.environ, PYTHONIOENCODING="utf-8")


def build_fixture(root: Path, with_credentials: bool = False) -> Path:
    db = root / "workbuddy.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, user_id TEXT, cwd TEXT, status TEXT, deleted_at TEXT, updated_at TEXT)")
    con.execute("CREATE TABLE automations (id TEXT PRIMARY KEY, name TEXT, cwds TEXT, deleted_at TEXT)")
    con.execute("CREATE TABLE workspaces (path TEXT PRIMARY KEY)")
    ws = root.parent / "ws"
    ws.mkdir(exist_ok=True)
    cwd = str(ws)
    con.execute("INSERT INTO sessions VALUES ('s-1', ?, ?, 'completed', NULL, '2026-08-30T10:00:00')", (UID, cwd))
    con.execute("INSERT INTO automations VALUES ('auto-1', '提醒', ?, NULL)", (json.dumps([cwd]),))
    con.execute("INSERT INTO workspaces VALUES (?)", (cwd,))
    con.commit()
    con.close()

    (root / "skills" / "skill-demo").mkdir(parents=True)
    (root / "skills" / "skill-demo" / "SKILL.md").write_text("# demo\n", encoding="utf-8")
    (root / "memory").mkdir(exist_ok=True)
    (root / "memory" / f"{UID}_memory.md").write_text("## 记忆\n", encoding="utf-8")
    (root / "MEMORY.md").write_text("# 长期记忆\n", encoding="utf-8")
    for f in ("IDENTITY.md", "USER.md", "SOUL.md"):
        (root / f).write_text(f + "\n", encoding="utf-8")
    (root / "settings.json").write_text(json.dumps({"theme": "dark"}), encoding="utf-8")
    (root / "mcp.json").write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
    (root / "models.json").write_text(json.dumps({"models": []}), encoding="utf-8")
    (root / "mcp-approvals.json").write_text(json.dumps({"approved": []}), encoding="utf-8")
    appdir = root / "app"
    appdir.mkdir(exist_ok=True)
    (appdir / "app-config.json").write_text(json.dumps({
        "personalization": {"customPrompt": "结论先行"},
        "sandboxSafetyEnabled": True,
    }), encoding="utf-8")
    pid = "".join(c if c.isalnum() else "-" for c in cwd)
    proj = root / "projects" / pid
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "s-1.jsonl").write_text('{"type":"user"}\n', encoding="utf-8")
    (proj / "s-1.meta.json").write_text(json.dumps({"cwd": cwd}), encoding="utf-8")
    if with_credentials:
        cred = root / "credentials" / "expert-x"
        cred.mkdir(parents=True, exist_ok=True)
        (cred / "token.json").write_text("{}", encoding="utf-8")
    return ws


def build_target(target: Path):
    target.mkdir(parents=True, exist_ok=True)
    tdb = target / "workbuddy.db"
    con = sqlite3.connect(tdb)
    con.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, user_id TEXT, cwd TEXT, status TEXT, deleted_at TEXT, updated_at TEXT)")
    con.execute("CREATE TABLE automations (id TEXT PRIMARY KEY, name TEXT, cwds TEXT, deleted_at TEXT)")
    con.execute("CREATE TABLE workspaces (path TEXT PRIMARY KEY)")
    con.execute("INSERT INTO sessions VALUES ('t-1', ?, NULL, 'completed', NULL, '2026-09-01T08:00:00')", (TGT_UID,))
    con.commit()
    con.close()


def test_error_codes():
    check("错误码注册表含 8 个稳定码", len(ERROR_CODES) == 8, sorted(ERROR_CODES))
    cases = [
        ("E-LOCK", sqlite3.OperationalError("database is locked")),
        ("E-PERM", PermissionError(13, "denied", "C:\\x\\a.json")),
        ("E-NOTFOUND", FileNotFoundError(2, "no", "C:\\nope")),
        ("E-BADPKG", zipfile.BadZipFile("not zip")),
        ("E-JSON", json.JSONDecodeError("bad", "{", 0)),
        ("E-DB", sqlite3.Error("db fail")),
        ("E-UNKNOWN", RuntimeError("weird")),
    ]
    for code, exc in cases:
        h = humanize(exc)
        check(f"{code} 前缀", h.startswith(f"[{code}]"), h[:40])
        check(f"{code} 指向 faq 速查表", "faq.md" in h)
    check("E-SANDBOX 在注册表", "E-SANDBOX" in ERROR_CODES)


def test_profile_export_and_import():
    workdir = Path(tempfile.mkdtemp(prefix="wb_v150_"))
    try:
        root = workdir / "src-root"
        root.mkdir()
        ws = build_fixture(root)
        pkg = workdir / "wb.zip"
        target = workdir / "target"
        build_target(target)

        # --- export --profile lite ---
        r = subprocess.run(
            [sys.executable, "scripts/export.py", "--source", str(root),
             "--output", str(pkg), "--profile", "lite"],
            capture_output=True, text=True, cwd=str(SRC), env=ENV,
        )
        check("lite 导出成功", r.returncode == 0, r.stderr[-300:])
        check("lite 输出含 Profile 行", "Profile: lite" in r.stdout)
        with zipfile.ZipFile(pkg) as zf:
            names = zf.namelist()
            meta = json.loads(zf.read("manifest.json").decode("utf-8"))
        check("manifest 记录 profile=lite", meta["options"].get("profile") == "lite")
        check("lite 无 credentials 目录", not any(n.startswith("credentials/") for n in names))
        check("lite 无产物包", not (workdir / "wb-workspaces.zip").exists())

        # --- import --profile auto ---
        r2 = subprocess.run(
            [sys.executable, "scripts/import.py", "--package", str(pkg),
             "--target", str(target), "--profile", "auto"],
            capture_output=True, text=True, cwd=str(SRC), env=ENV,
        )
        check("auto 导入成功", r2.returncode == 0, r2.stderr[-300:])
        check("auto 输出含资产校验行", "资产校验" in r2.stdout, r2.stdout[-300:])
        check("校验为全部就位", "项全部就位" in r2.stdout, r2.stdout[-400:])
        reports = sorted((target / "migration-reports").glob("import-*.json"))
        check("导入报告存在", bool(reports))
        if reports:
            rep = json.loads(reports[-1].read_text(encoding="utf-8"))
            v = (rep.get("sections") or {}).get("verify") or {}
            check("verify verdict=all-present", v.get("verdict") == "all-present", v.get("verdict"))
            check("verify 检查 6 项", len(v.get("checks", [])) == 6, len(v.get("checks", [])))
            check("verify 缺失为 0", v.get("missing_total") == 0, v.get("missing_total"))
            check("uid 自动映射生效", (rep.get("sections") or {}).get("uid_mapping") != "none")

        # --- verify missing detection (unit level) ---
        import importlib.util as _ilu
        _spec = _ilu.spec_from_file_location("wb_import", SRC / "scripts" / "import.py")
        IMP = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(IMP)
        from scripts.manifest import Manifest as MM  # noqa: E402
        shutil.rmtree(target / "skills" / "skill-demo")
        (target / "memory" / f"{TGT_UID}_memory.md").unlink()
        args = SimpleNamespace(skip_skills=False, skip_configs=False,
                               no_conversations=False, skip_db=False)
        mobj = MM.load_text(json.dumps(meta))
        v2 = IMP._verify_import(mobj, target, {UID: TGT_UID}, args)
        check("缺失场景 verdict=has-missing", v2["verdict"] == "has-missing", v2["verdict"])
        check("缺失总数 > 0", v2["missing_total"] > 0, v2["missing_total"])
        skill_check = next(c for c in v2["checks"] if c["item"] == "skills")
        check("缺失名单含 skill-demo", "skill-demo" in skill_check.get("missing", []), skill_check)
        mem_check = next(c for c in v2["checks"] if c["item"] == "memory")
        tgt_mem = f"{TGT_UID}_memory.md"
        check("缺失名单含 uid 重写后记忆文件", tgt_mem in mem_check.get("missing", []), mem_check)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    test_error_codes()
    test_profile_export_and_import()
    print(f"\n==== RESULT: {len(PASS)} PASS / {len(FAIL)} FAIL ====")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)
