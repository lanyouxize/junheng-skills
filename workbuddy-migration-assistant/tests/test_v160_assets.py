"""test_v160_assets.py — v1.6.0 WorkBuddy 5.4.7 adaptation (asset gaps).

Covers the two real gaps found by comparing the on-disk ~/.workbuddy tree
against references/asset_inventory.md:

  - artifact-index/          : per-session artifact (deliverable) index;
                               uris are URL-encoded absolute paths → must be
                               remapped on cross-machine import.
  - root .credentials.json   : global MCP OAuth store (mcpOAuth); without it
                               the "no re-authorization after migration"
                               promise cannot hold. Gated by --no-credentials.
  - security/ + claw-state/  : declared never-migrate (runtime data).

Every new asset is asserted in BOTH directions (export AND import).
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
from urllib.parse import quote, unquote

SRC = Path(__file__).resolve().parent.parent  # 技能根目录（相对定位，安装到任意位置均可自检）
sys.path.insert(0, str(SRC))

from scripts import automap  # noqa: E402
from scripts.pathmap import PathMapper  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name + (("  | " + str(detail)) if detail and not cond else ""))


UID = "a1b2c3d4e5f60718293a4b5c6d7e8f90"
TGT_UID = "f0e9d8c7b6a54433221100ffeeddccb0"
ENV = dict(os.environ, PYTHONIOENCODING="utf-8")


def build_fixture(root: Path, ws: Path) -> None:
    """Minimal ~/.workbuddy tree incl. the two v1.6.0 assets."""
    db = root / "workbuddy.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, user_id TEXT, cwd TEXT, status TEXT, deleted_at TEXT, updated_at TEXT)")
    con.execute("CREATE TABLE automations (id TEXT PRIMARY KEY, name TEXT, cwds TEXT, deleted_at TEXT)")
    con.execute("CREATE TABLE workspaces (path TEXT PRIMARY KEY)")
    con.execute("INSERT INTO sessions VALUES ('s-1', ?, ?, 'completed', NULL, '2026-08-30T10:00:00')", (UID, str(ws)))
    con.execute("INSERT INTO automations VALUES ('auto-1', '提醒', ?, NULL)", (json.dumps([str(ws)]),))
    con.execute("INSERT INTO workspaces VALUES (?)", (str(ws),))
    con.commit()
    con.close()

    (root / "skills" / "skill-demo").mkdir(parents=True)
    (root / "skills" / "skill-demo" / "SKILL.md").write_text("# demo\n", encoding="utf-8")
    (root / "memory").mkdir()
    (root / "memory" / f"{UID}_memory.md").write_text("## 记忆\n", encoding="utf-8")
    for f in ("IDENTITY.md", "USER.md", "SOUL.md"):
        (root / f).write_text(f + "\n", encoding="utf-8")
    (root / "settings.json").write_text(json.dumps({"theme": "dark"}), encoding="utf-8")
    (root / "mcp.json").write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
    (root / "models.json").write_text(json.dumps({"models": []}), encoding="utf-8")

    # --- v1.6.0 asset 1: artifact-index (URL-encoded absolute uri) ---
    aidx = root / "artifact-index"
    aidx.mkdir()
    src_file_uri = "file-changes://" + quote(str(ws / "report.md"), safe="/")
    (aidx / "s-1.json").write_text(json.dumps({
        "version": 1,
        "lastUpdated": 1787745119758,
        "artifacts": [{
            "type": "file-changes",
            "uri": src_file_uri,
            "name": "report.md",
            "title": "report.md",
            "mimeType": "text/x-diff",
            "fileChangeInfo": {"uri": str(ws / "report.md")},
        }],
    }, ensure_ascii=False), encoding="utf-8")

    # --- v1.6.0 asset 2: root .credentials.json (global MCP OAuth) ---
    (root / ".credentials.json").write_text(json.dumps({
        "mcpOAuth": {
            "lighthouse-ops|407483f3c1a3513e": {
                "serverName": "lighthouse-ops",
                "serverUrl": "https://example.invalid/mcp",
                "accessToken": "dummy-token",
                "clientId": "dummy-client",
            }
        }
    }), encoding="utf-8")

    # --- runtime dirs that must NOT be exported ---
    (root / "security" / "threat-database").mkdir(parents=True)
    (root / "security" / "threat-database" / "state.json").write_text("{}", encoding="utf-8")
    (root / "claw-state" / "weixin").mkdir(parents=True)
    (root / "claw-state" / "weixin" / "state.json").write_text("{}", encoding="utf-8")


def build_target(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    tdb = target / "workbuddy.db"
    con = sqlite3.connect(tdb)
    con.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, user_id TEXT, cwd TEXT, status TEXT, deleted_at TEXT, updated_at TEXT)")
    con.execute("CREATE TABLE automations (id TEXT PRIMARY KEY, name TEXT, cwds TEXT, deleted_at TEXT)")
    con.execute("CREATE TABLE workspaces (path TEXT PRIMARY KEY)")
    con.execute("INSERT INTO sessions VALUES ('t-1', ?, NULL, 'completed', NULL, '2026-09-01T08:00:00')", (TGT_UID,))
    con.commit()
    con.close()


def test_unit_rewrite_encoded_uri():
    """PathMapper-based rewrite of URL-encoded artifact uris."""
    workdir = Path(tempfile.mkdtemp(prefix="wb_v160_unit_"))
    try:
        src_ws = workdir / "oldws"
        dst_ws = workdir / "newws"
        src_ws.mkdir()
        dst_ws.mkdir()
        aidx = workdir / "artifact-index"
        aidx.mkdir()
        uri = "file-changes://" + quote(str(src_ws / "report.md"), safe="/")
        (aidx / "a.json").write_text(json.dumps({
            "artifacts": [{"uri": uri, "fileChangeInfo": {"uri": str(src_ws / "report.md")}}],
            "note": "keep-me",
        }), encoding="utf-8")

        # dst_os uses the sys.platform value ("win32") — same as import.py passes
        # to PathMapper. ("Windows" from platform.system() is display-only and
        # yields mixed separators; see known-issues.md.)
        mapper = PathMapper(rules=[(str(src_ws), str(dst_ws))], src_os="win32", dst_os="win32")
        res = automap.rewrite_artifact_index(aidx, mapper)
        check("重写返回 rewitten_files=1", res["rewritten_files"] == 1, res)
        check("重写返回 uris_rewritten=2", res["uris_rewritten"] == 2, res)

        data = json.loads((aidx / "a.json").read_text(encoding="utf-8"))
        new_uri = data["artifacts"][0]["uri"]
        check("uri 仍保留 scheme", new_uri.startswith("file-changes://"), new_uri)
        decoded = unquote(new_uri[len("file-changes://"):])
        check("uri 解码后指向新路径", decoded == str(dst_ws / "report.md"), decoded)
        check("嵌套 fileChangeInfo.uri 同步重写",
              data["artifacts"][0]["fileChangeInfo"]["uri"] == str(dst_ws / "report.md"),
              data["artifacts"][0]["fileChangeInfo"]["uri"])
        check("非路径字段未被误改", data["note"] == "keep-me", data.get("note"))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def test_end_to_end():
    workdir = Path(tempfile.mkdtemp(prefix="wb_v160_"))
    try:
        root = workdir / "src-root"
        root.mkdir()
        src_ws = workdir / "oldws"
        src_ws.mkdir()
        build_fixture(root, src_ws)
        dst_ws = workdir / "newws"
        dst_ws.mkdir()
        target = workdir / "target"
        build_target(target)

        # --- export (default: credentials kept) ---
        pkg = workdir / "wb.zip"
        r = subprocess.run(
            [sys.executable, "scripts/export.py", "--source", str(root), "--output", str(pkg)],
            capture_output=True, text=True, cwd=str(SRC), env=ENV,
        )
        check("导出成功", r.returncode == 0, r.stderr[-300:])
        with zipfile.ZipFile(pkg) as zf:
            names = zf.namelist()
        check("包内含 artifact-index", any(n.startswith("artifact-index/") for n in names))
        check("包内含根级 .credentials.json", ".credentials.json" in names, [n for n in names if "cred" in n])
        check("包内不含 security/", not any(n.startswith("security/") for n in names))
        check("包内不含 claw-state/", not any(n.startswith("claw-state/") for n in names))

        # --- export with --no-credentials ---
        pkg_nc = workdir / "wb-nc.zip"
        r_nc = subprocess.run(
            [sys.executable, "scripts/export.py", "--source", str(root),
             "--output", str(pkg_nc), "--no-credentials"],
            capture_output=True, text=True, cwd=str(SRC), env=ENV,
        )
        check("no-credentials 导出成功", r_nc.returncode == 0, r_nc.stderr[-300:])
        with zipfile.ZipFile(pkg_nc) as zf:
            names_nc = zf.namelist()
        check("no-credentials 排除根级凭证", ".credentials.json" not in names_nc)
        check("no-credentials 仍带 artifact-index",
              any(n.startswith("artifact-index/") for n in names_nc))

        # --- import with path remap (cross-machine simulation) ---
        r2 = subprocess.run(
            [sys.executable, "scripts/import.py", "--package", str(pkg),
             "--target", str(target), "--auto-map",
             "--path-map", f"{src_ws}={dst_ws}",
             "--uid-map", f"{UID}={TGT_UID}"],
            capture_output=True, text=True, cwd=str(SRC), env=ENV,
        )
        check("导入成功", r2.returncode == 0, r2.stderr[-400:])
        check("目标端生成 artifact-index", (target / "artifact-index" / "s-1.json").is_file())
        check("目标端生成根级凭证", (target / ".credentials.json").is_file())
        check("目标端无 security/", not (target / "security").exists())
        check("目标端无 claw-state/", not (target / "claw-state").exists())

        art = json.loads((target / "artifact-index" / "s-1.json").read_text(encoding="utf-8"))
        got = unquote(art["artifacts"][0]["uri"][len("file-changes://"):])
        check("导入后 artifact uri 已重写到目标路径", got == str(dst_ws / "report.md"), got)
        check("导入后嵌套 uri 已重写",
              art["artifacts"][0]["fileChangeInfo"]["uri"] == str(dst_ws / "report.md"),
              art["artifacts"][0]["fileChangeInfo"]["uri"])
        cred = json.loads((target / ".credentials.json").read_text(encoding="utf-8"))
        check("导入后凭证内容完整", "lighthouse-ops|407483f3c1a3513e" in cred.get("mcpOAuth", {}))
        check("报告含 artifact-index 重写段",
              "path_rewrite_artifact_index" in r2.stdout, r2.stdout[-400:])

        # --- import with --no-credentials (must not land) ---
        target2 = workdir / "target-nc"
        build_target(target2)
        r3 = subprocess.run(
            [sys.executable, "scripts/import.py", "--package", str(pkg),
             "--target", str(target2), "--no-credentials",
             "--uid-map", f"{UID}={TGT_UID}"],
            capture_output=True, text=True, cwd=str(SRC), env=ENV,
        )
        check("no-credentials 导入成功", r3.returncode == 0, r3.stderr[-300:])
        check("no-credentials 导入不落地凭证", not (target2 / ".credentials.json").exists())
        check("no-credentials 导入仍落地 artifact-index",
              (target2 / "artifact-index" / "s-1.json").is_file())
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    test_unit_rewrite_encoded_uri()
    test_end_to_end()
    print(f"\n==== RESULT: {len(PASS)} PASS / {len(FAIL)} FAIL ====")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)
