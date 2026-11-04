import sys, tempfile, os
sys.path.insert(0, r"C:/Users/Administrator/.workbuddy/skills/ui-auto-click/scripts")
import clicker

def mk(content):
    p = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8")
    p.write(content); p.close()
    return p.name

cases = {
    "fresh": "whatever no marker\n",
    "keying": "开始获取密钥...\n",
    "id_ready": "获取公众号历史消息页面成功\n",
    "need_open": "请先在微信打开复制的链接\n",
    "keyed": "获取密钥成功\n",
    "downloading": "开始下载：标题\n",
    "done": "下载完成!!!\n",
    "mixed_done": "获取密钥成功\n开始下载：x\n下载完成!!!\n",
    "mixed_keyed_after_done": "下载完成!!!\n获取密钥成功\n",
}
# 期望态：默认 = 用例名（need_open 归并到 id_ready）；
# mixed_done = 最新行是「下载完成!!!」→ done；
# mixed_keyed_after_done = 最新行是「获取密钥成功」→ keyed（最新行优先）。
expect_map = {
    "need_open": "id_ready",
    "mixed_done": "done",
    "mixed_keyed_after_done": "keyed",
}
ok = True
for name, content in cases.items():
    p = mk(content)
    try:
        r = clicker.probe_downloader_state(p)
    finally:
        os.unlink(p)
    exp = expect_map.get(name, name)
    got = r["state"]
    status = "PASS" if got == exp else "FAIL"
    if got != exp:
        ok = False
    print(f"{status} {name}: got={got} line={r['last_marker_line']} expect={exp}")
print("ALL_PASS" if ok else "SOME_FAIL")
sys.exit(0 if ok else 1)
