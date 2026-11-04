"""Clean build/run artifacts from the skill package.

SkillHub rejects packages containing binary files (.pyc, .zip, .db ...), so
`check` is meant to be run right before packaging or upload.

`data/scrape_history.json` is the user's crawl history — real data, not a build
artifact. It is never touched unless `--all` is passed explicitly.
"""

import json
import os
import shutil
import sys
import zipfile

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
PACKAGE_NAME = os.path.basename(PROJECT_ROOT)

DIRS_TO_REMOVE = [
    "__pycache__",
    ".pytest_cache",
    "data/cache",
    "data/ima_export",
    "data/dify_export",
    "data/obsidian_export",
    "output",
]

ARTIFACT_SUFFIXES = (".pyc", ".pyo", ".zip", ".db", ".sqlite", ".sqlite3", ".log")

LOCAL_DATA_FILES = ["data/scrape_history.json"]

_SKIP_DIRS = {".git", "node_modules"}


def _rel(path: str) -> str:
    return os.path.relpath(path, PROJECT_ROOT).replace("\\", "/")


def _is_local_data(rel: str) -> bool:
    return rel in LOCAL_DATA_FILES or rel.startswith(
        tuple(f"{name}/" for name in LOCAL_DATA_FILES)
    )


def _walk():
    for root, dirs, files in os.walk(PROJECT_ROOT):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        yield root, dirs, files


def _is_artifact_dir(path: str) -> bool:
    """Match both bare names (`__pycache__`) and nested paths (`data/cache`).

    The old check compared a directory's basename against entries that contain
    a slash, so `data/cache` was never cleaned — and `--check` still said 干净.
    """
    rel = _rel(path).rstrip("/")
    base = os.path.basename(rel)
    return base in DIRS_TO_REMOVE or rel in DIRS_TO_REMOVE


def _find_artifacts(include_local_data: bool = False):
    """Return (dirs, files) that must not ship with the skill."""
    bad_dirs = []
    bad_files = []
    for root, dirs, files in _walk():
        for d in dirs:
            if _is_artifact_dir(os.path.join(root, d)):
                bad_dirs.append(os.path.join(root, d))
        for f in files:
            path = os.path.join(root, f)
            rel = _rel(path)
            if f.endswith(ARTIFACT_SUFFIXES):
                bad_files.append(path)
            elif include_local_data and _is_local_data(rel):
                bad_files.append(path)
    return bad_dirs, bad_files


def clean(include_local_data: bool = False):
    removed = []
    bad_dirs, bad_files = _find_artifacts(include_local_data)
    for path in bad_dirs:
        shutil.rmtree(path, ignore_errors=True)
        removed.append(path)
    for path in bad_files:
        if os.path.exists(path):
            os.remove(path)
            removed.append(path)
    return removed


def check(include_local_data: bool = False):
    """Report artifacts without removing them. Returns the offending paths."""
    bad_dirs, bad_files = _find_artifacts(include_local_data)
    return bad_dirs + bad_files


def _package_version() -> str:
    with open(os.path.join(PROJECT_ROOT, "config.json"), encoding="utf-8") as fh:
        return json.load(fh).get("version", "0.0.0")


def build_zip(dest_dir: str = None) -> str:
    """Clean, then write the upload archive, then re-open it and verify.

    The archive must land outside the package: a `.zip` inside the tree is
    itself a rejected binary, so an in-package build would fail the next check.
    """
    clean()
    dest_dir = dest_dir or os.path.dirname(PROJECT_ROOT)
    resolved = os.path.abspath(dest_dir)
    if resolved == PROJECT_ROOT or resolved.startswith(PROJECT_ROOT + os.sep):
        raise ValueError("zip 必须落在技能包目录之外，否则它自己就是被拒的二进制")
    os.makedirs(resolved, exist_ok=True)
    target = os.path.join(resolved, f"{PACKAGE_NAME}-v{_package_version()}.zip")

    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in _walk():
            dirs[:] = [d for d in dirs if not _is_artifact_dir(os.path.join(root, d))]
            for f in sorted(files):
                path = os.path.join(root, f)
                rel = _rel(path)
                if f.endswith(ARTIFACT_SUFFIXES) or _is_local_data(rel):
                    continue
                zf.write(path, f"{PACKAGE_NAME}/{rel}")

    # 归档里混进一个 .pyc 就会让整个上传被拒；上传前先在本地把这条拒掉。
    names = zipfile.ZipFile(target).namelist()
    offending = [n for n in names
                 if os.path.basename(n).endswith(ARTIFACT_SUFFIXES)
                 or _is_local_data(n.split("/", 1)[1])]
    if offending:
        os.remove(target)
        raise SystemExit(f"打包失败，归档内含二进制/本地数据: {offending[:5]}")
    return target


if __name__ == "__main__":
    include_data = "--all" in sys.argv
    if "--check" in sys.argv:
        issues = check(include_data)
        if issues:
            print(f"发现 {len(issues)} 个需清理的产物:")
            for p in issues:
                print("  " + p)
            sys.exit(1)
        print("干净：无二进制/运行期产物")
    elif "--zip" in sys.argv:
        dest = sys.argv[sys.argv.index("--zip") + 1] if len(sys.argv) > sys.argv.index("--zip") + 1 else None
        path = build_zip(dest)
        count = len(zipfile.ZipFile(path).namelist())
        print(f"已打包 {count} 个文件，归档内无二进制：{path}")
    else:
        removed = clean(include_data)
        if include_data:
            print("警告：--all 已一并移除本地数据（含爬取历史）")
        print(f"已清理 {len(removed)} 项")
        sys.exit(0)
