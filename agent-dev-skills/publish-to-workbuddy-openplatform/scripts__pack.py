"""打包发布包目录到 zip。

用法：
  python pack.py expert                      # 专家：分离布局（plugin.json 进 .codebuddy-plugin/，资源放 zip 根）
  python pack.py skill .codebuddy-skill/     # 技能：通用前缀模式
  python pack.py connector                   # 扁平（无前缀）
  python pack.py buddy-app                   # 扁平
  python pack.py expert --mirror             # 打完顺便双备份到 Desktop/publish-mirror/

参数：
  <name>    源目录名（默认读 ./<name>/，输出 ./<name>.zip）
  [prefix]  通用模式下加在 zip 内每条路径前的前缀（末尾带 /），如 .codebuddy-skill/
  --src DIR 自定义源目录（默认 ./<name>）
  --out DIR 自定义输出 zip 所在目录（默认当前目录）
  --mirror  额外复制一份到 Desktop/publish-mirror/<name>.zip

专家分离布局规则（已验证）：
  plugin.json            -> .codebuddy-plugin/plugin.json
  avatars/README.md      -> .codebuddy-plugin/avatars/README.md
  agents/*               -> agents/*            (zip 根)
  avatars/*.{png,...}    -> avatars/*           (zip 根)
  README.md              -> README.md           (zip 根)
"""
import os
import sys
import zipfile
import hashlib
import shutil


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _add(zf, full, arc):
    zf.write(full, arc)
    print(f"     {arc}")


def pack_expert(src: str, dst: str) -> None:
    if os.path.exists(dst):
        os.remove(dst)
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(src):
            for fname in files:
                full = os.path.join(root, fname)
                rel = os.path.relpath(full, src).replace(os.sep, "/")
                if rel == "plugin.json":
                    _add(zf, full, ".codebuddy-plugin/plugin.json")
                elif rel == "avatars/README.md":
                    _add(zf, full, ".codebuddy-plugin/avatars/README.md")
                elif rel.startswith("agents/"):
                    _add(zf, full, rel)
                elif rel.startswith("avatars/"):
                    _add(zf, full, rel)
                elif rel == "README.md":
                    _add(zf, full, "README.md")
                else:
                    _add(zf, full, rel)
    print(f"OK  {os.path.basename(dst)}  {os.path.getsize(dst)/1024:6.1f} KB")
    print(f"    SHA256 {_sha256(dst)}")


def pack(name: str, src: str, dst: str, prefix: str = "") -> None:
    if os.path.exists(dst):
        os.remove(dst)
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(src):
            for fname in files:
                full = os.path.join(root, fname)
                rel = os.path.relpath(full, src).replace(os.sep, "/")
                arc = f"{prefix}{rel}" if prefix else rel
                _add(zf, full, arc)
    print(f"OK  {os.path.basename(dst)}  {os.path.getsize(dst)/1024:6.1f} KB")
    print(f"    SHA256 {_sha256(dst)}")


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    name = args[0]
    prefix = ""
    src = None
    out_dir = "."
    mirror = False
    for a in args[1:]:
        if a.startswith("--src"):
            src = a.split("=", 1)[1] if "=" in a else args[args.index(a) + 1]
        elif a.startswith("--out"):
            out_dir = a.split("=", 1)[1] if "=" in a else args[args.index(a) + 1]
        elif a == "--mirror":
            mirror = True
        elif a and not a.startswith("--"):
            prefix = a

    src = src or name
    dst = os.path.join(out_dir, f"{name}.zip")

    if name == "expert" and not prefix:
        pack_expert(src, dst)
    else:
        pack(name, src, dst, prefix)

    if mirror:
        mirror_dir = os.path.join(
            os.path.expanduser("~"), "Desktop", "publish-mirror"
        )
        os.makedirs(mirror_dir, exist_ok=True)
        mpath = os.path.join(mirror_dir, f"{name}.zip")
        shutil.copy2(dst, mpath)
        print(f"    mirror -> {mpath}  SHA256 {_sha256(mpath)}")


if __name__ == "__main__":
    main()
