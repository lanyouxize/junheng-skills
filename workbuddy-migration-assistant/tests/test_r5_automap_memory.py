"""test_r5_automap_memory.py — memory path token rewriting (v1.2.1 R5).

Covers rewrite_memory_path_tokens:
  - drive-path tokens matched by PathMapper get rewritten
  - uid token replacement derives from manifest/uid_map only
  - non-path strings are NOT touched (mapper rejects them)
"""
import os
import sys
import tempfile
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent  # 技能根目录（相对定位，安装到任意位置均可自检）
sys.path.insert(0, str(SRC))

from scripts import automap  # noqa: E402
from scripts.pathmap import PathMapper  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name + (("  | " + str(detail)) if detail and not cond else ""))


def test_memory_token_rewrite():
    with tempfile.TemporaryDirectory(prefix="wb_r5_") as td:
        td = Path(td)
        mem = td / "MEMORY.md"
        mem.write_text(
            "工作目录：C:\\Users\\olduser\\projects\\alpha\n"
            "另一条：D:\\data\\docs\\report.md\n"
            "普通文本无路径，user_id=u123abc 只是标识\n"
            "home: /home/olduser/work\n",
            encoding="utf-8",
        )
        mapper = PathMapper(
            rules=[(r"C:\Users\olduser", r"C:\Users\newuser")],
            src_os="win32", dst_os="win32",
        )
        res = automap.rewrite_memory_path_tokens([mem], mapper)
        text = mem.read_text(encoding="utf-8")
        check("C:\\Users\\olduser 前缀重写", r"C:\Users\newuser\projects\alpha" in text, text)
        check("未匹配的 D: 路径保留", "D:\\data\\docs\\report.md" in text, text)
        check("普通文本未被破坏", "普通文本无路径" in text, text)
        check("至少替换 1 个 token", res["tokens_replaced"] >= 1, res)


def test_uid_token_rewrite():
    with tempfile.TemporaryDirectory(prefix="wb_r5b_") as td:
        td = Path(td)
        mem = td / "u_old123_memory.md"
        mem.write_text("路径 C:\\Users\\olduser\\x\\u_old123_proj\n", encoding="utf-8")
        mapper = PathMapper(
            rules=[(r"C:\Users\olduser", r"C:\Users\newuser")],
            src_os="win32", dst_os="win32",
        )
        res = automap.rewrite_memory_path_tokens(
            [mem], mapper, old_uid="u_old123", new_uid="u_new456",
        )
        text = mem.read_text(encoding="utf-8")
        check("uid token 被替换", "u_new456_proj" in text, text)
        check("路径前缀同时重写", r"C:\Users\newuser" in text, text)


if __name__ == "__main__":
    test_memory_token_rewrite()
    test_uid_token_rewrite()
    print(f"\n==== RESULT: {len(PASS)} PASS / {len(FAIL)} FAIL ====")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)
