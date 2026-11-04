#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""技能仓库字节保真校验。

作用：证明「仓库里的内容」与「磁盘上的文件」逐字节相同 —— 不是抽样，是全量。
这条判据存在的理由：本仓库用 `* -text` 关掉行尾转换，但这件事必须每次都能被验证，
而不是相信配置。系统级 core.autocrlf=true 仍然在本机生效，任何一次属性被改动、
任何一次 clone 到别处，都可能让文件静默变大（LF→CRLF）。

用法：
    python -X utf8 vcs-verify.py            # 工作区 vs HEAD，全量比对
    python -X utf8 vcs-verify.py --clone     # 额外做一次克隆演练，验完自动删除
    python -X utf8 vcs-verify.py --json      # 机器可读

退出码：0 全量一致 / 1 有差异 / 2 环境错误
"""

import argparse
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def git(*args, cwd=None, binary=False):
    """binary=True 返回 bytes（路径要用 -z 取，避免中文被转义），否则返回 str。

    注意 text= 与返回值必须一致：写成 text=not binary 却无条件 .decode()，
    在 binary=False 时 stdout 已经是 str，会抛 AttributeError。
    """
    proc = subprocess.run(
        ["git"] + list(args),
        cwd=cwd or ROOT,
        capture_output=True,
        text=not binary,
    )
    return proc.stdout


def head_entries(ref="HEAD"):
    """返回 [(relpath, blob_sha)]。用 -z 取路径：中文名不会被转义加引号。

    这一点踩过坑：`git ls-files` 默认对非 ASCII 路径输出 "\\345\\245\\263..." 带引号，
    直接当路径用会判成「文件缺失」——11 个中文名文件因此被误报，实际全在。
    """
    raw = git("ls-tree", "-r", "-z", ref, binary=True)
    out = []
    for chunk in raw.split(b"\0"):
        if not chunk:
            continue
        meta, path = chunk.split(b"\t", 1)
        mode, typ, sha = meta.decode().split(" ")
        if typ != "blob":
            continue
        out.append((path.decode("utf-8"), sha))
    return out


def blob_sha(data):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with io.open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def compare(base_dir, entries):
    """比对 base_dir 下每个条目与 blob sha（git blob id 由内容直接算出，无需访问对象库）。"""
    missing, mismatch = [], []
    crlf = 0
    for rel, sha in entries:
        path = os.path.join(base_dir, rel)
        if not os.path.exists(path):
            missing.append(rel)
            continue
        with io.open(path, "rb") as fh:
            data = fh.read()
        if b"\r\n" in data:
            crlf += 1
        if blob_sha(data) != sha:
            mismatch.append(rel)
    return {
        "dir": base_dir,
        "files": len(entries),
        "missing": missing,
        "mismatch": mismatch,
        "crlf_files": crlf,
    }


def clone_drill(entries):
    """克隆到系统临时目录，做「换机恢复」演练。刻意不放技能目录：
    临时目录若落在工作区里，会变成 untracked 污染，正好破坏它要验证的东西。"""
    tmp = tempfile.mkdtemp(prefix="skill-vcs-")
    dst = os.path.join(tmp, "clone")
    try:
        proc = subprocess.run(
            ["git", "clone", "-q", "--no-local", ROOT, dst],
            capture_output=True,
        )
        if proc.returncode != 0:
            return {"ok": False, "error": "clone 失败: " + proc.stderr.decode("utf-8", "replace")[:200]}
        res = compare(dst, entries)
        # 克隆出的文件数也必须与源一致（防止属性导致误跳过）
        res["clone_files"] = int(git("ls-files", "-z", cwd=dst, binary=True).count(b"\0"))
        res["ok"] = not res["missing"] and not res["mismatch"] and res["clone_files"] == len(entries)
        return res
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description="技能仓库字节保真校验")
    ap.add_argument("--clone", action="store_true", help="额外做克隆演练")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    ap.add_argument("--ref", default="HEAD", help="对标引用，默认 HEAD")
    args = ap.parse_args()

    if not os.path.isdir(os.path.join(ROOT, ".git")):
        print("环境错误：%s 下没有 .git" % ROOT)
        return 2
    entries = head_entries(args.ref)
    if not entries:
        print("环境错误：%s 内没有任何 blob" % args.ref)
        return 2

    base = compare(ROOT, entries)
    dirty_lines = [l for l in git("status", "--porcelain").split("\n") if l.strip()]
    result = {"head": base, "dirty": len(dirty_lines)}
    if args.clone:
        result["clone"] = clone_drill(entries)

    ok = not base["missing"] and not base["mismatch"]
    if args.clone:
        ok = ok and result["clone"]["ok"]

    if args.json:
        result["ok"] = ok
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if ok else 1

    print("对标 %s：%d 个 blob" % (args.ref, base["files"]))
    print("  工作区缺失 %d | 字节不一致 %d | 含 CRLF %d 个文件"
          % (len(base["missing"]), len(base["mismatch"]), base["crlf_files"]))
    if result["dirty"]:
        print("  未提交改动 %d 项（新增/修改/删除，用 git status 看明细）" % result["dirty"])
    for rel in base["missing"][:5]:
        print("    缺: %s" % rel)
    for rel in base["mismatch"][:5]:
        print("    异: %s" % rel)
    if args.clone:
        c = result["clone"]
        if not c.get("ok") and c.get("error"):
            print("  克隆演练：%s" % c["error"])
        else:
            print("  克隆演练：%d 文件 | 缺失 %d | 不一致 %d → %s"
                  % (c["files"], len(c["missing"]), len(c["mismatch"]),
                     "可完整恢复" if c["ok"] else "不能恢复"))
    print("判定：%s" % ("PASS 全量字节一致" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
