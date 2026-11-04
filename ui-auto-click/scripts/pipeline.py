#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公众号文章采集 → 元典智库：一条命令跑完全链路。

给一个公众号名称，依次完成 14 个阶段（每阶段失败即停，可断点续跑）：

    preflight  环境与前置检查（微信在跑、工具窗口、目录、node/python）
    scout      微信「赞和收藏」逐篇发现：只点"所属公众号还没采过"的文章（需先校准模板）
    download   启动/附着下载工具，按公众号批量下载（真操作，需 --yes）
    clean      修图片路径 + 清微信 UI 噪声（幂等，先备份）
    manifest   按 clean 后的文件生成入库清单（会继承已有元数据，不清零）
    meta       补原文链接 / 公众号 / 发表日期（发表时间需联网抓 var ct）
    package    打成 articles.ndjson 导入包 + 12 项回读核对
    ingest     写元典 vault（source 笔记 + 分类 JSON）
    guards     对 vault 笔记跑 recurring 守卫：空章节归正（幂等）；--reclassify 时额外重算归类
    images     把下载目录的图片压缩入库 vault/20_Sources/图片 + 引用核对（默认移库外重复进备份）
    maps       重建「智库链接模块」（公众号板块入口页）
    derived    重建 Home / hot / log / canvas / orphans
    export     导出静态站点 site/
    verify     validate.py --self-test 必须 PASS，且图片引用全部落地（audit-images）

scout 阶段默认可用 --skip 跳过；它需要先跑一次
scripts/capture_templates.py 校准 UI 模板（微信停在「赞和收藏」页且不被遮挡）。
设计说明见 references/wechat-favorites-flow.md。

两个关键设计（都是踩坑后定的）
--------------------------------
1. **下载工具的输出目录跟随它的 cwd**。实测：从技能目录启动，产物就落到技能目录里，
   不是桌面。所以本编排器在需要时**自己以 cwd=<base> 启动工具**（--tool-exe），
   而不是指望用户双击时恰好对。
2. **判成功只看产物，不看日志和 toast**。工具会弹「下载成功！」但正文其实没抓到；
   所以 download 阶段以「新增 md 数 > 0 且空壳比例 < 30%」为通过条件。

用法
----
  python scripts/pipeline.py --account "食品研发与生产" --plan
  python scripts/pipeline.py --account "食品研发与生产" --yes            # 全跑
  python scripts/pipeline.py --account "食品研发与生产" --yes --from-step clean
  python scripts/pipeline.py --account "X" --yes --skip download,export

前置（人工，脚本会提示）：在微信 PC 端打开该公众号任意一篇文章 →
复制链接 → 粘进下载工具的「文章下载」框并点一次，让工具拿到该号密钥。
**从 scout 阶段起步时这一步被自动接管**：scout 点开文章后默认不返回列表
（`--return-key none`），把文章页留给 download；只有 `--from-step download`
才需要人工先把文章页开着。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
CLICKER = SKILL / "scripts" / "clicker.py"
TOOLS = SKILL / "out" / "tools"

DEFAULT_BASE = "C:/Users/Administrator/Desktop/下载"
DEFAULT_VEIN = "D:/workbuddy重做系统后版本/2026-10-16-21-12-03"
DEFAULT_EXE = "C:/Users/Administrator/Desktop/微信公众号批量下载工具4.0.exe"


def _pick_python() -> Path:
    """挑一个真能 import pywinauto 的解释器。

    踩坑：本机 `sys.executable` 是 versions/3.13.12/python.exe（裸解释器），
    pywinauto 装在 envs/default 里；直接 sys.executable 跑会在 preflight
    阶段 SystemExit(6) 无声退出。Windows 下 envs\\X\\Scripts\\python.exe 是
    转发 launcher，会再 spawn versions\\<ver>\\python.exe —— 两条路径都能用，
    这里只验「谁能 import pywinauto」。
    """
    cands = []
    if os.environ.get("UIAC_PY"):
        cands.append(Path(os.environ["UIAC_PY"]))
    home = Path.home() / ".workbuddy" / "binaries" / "python" / "envs"
    if home.is_dir():
        cands += [p / "Scripts" / "python.exe" for p in sorted(home.iterdir())
                  if (p / "Scripts" / "python.exe").is_file()]
    cands.append(Path(sys.executable))
    for p in cands:
        try:
            r = subprocess.run([str(p), "-c", "import pywinauto"],
                               capture_output=True, timeout=60)
            if r.returncode == 0:
                return p
        except Exception:
            continue
    return Path(sys.executable)


PY = _pick_python()

ORDER = ["preflight", "scout", "download", "clean", "manifest", "meta",
         "package", "ingest", "guards", "images", "maps", "derived", "export", "verify"]


class StageFail(RuntimeError):
    pass


def run(cmd, cwd=None, timeout=1800, quiet=False) -> subprocess.CompletedProcess:
    """跑子进程；非零退出即抛，绝不吞错。"""
    shown = " ".join(str(c) for c in cmd)
    if not quiet:
        print(f"    $ {shown}")
    r = subprocess.run([str(c) for c in cmd], cwd=str(cwd) if cwd else None,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout)
    tail = (r.stdout or "").strip().splitlines()[-3:]
    for line in tail:
        print(f"      {line}")
    if r.returncode != 0:
        err = (r.stderr or "").strip().splitlines()[-6:]
        for line in err:
            print(f"      ! {line}")
        raise StageFail(f"退出码 {r.returncode}: {shown}")
    return r


def md_count(root: Path) -> int:
    return len(list(root.glob("*.md"))) if root.is_dir() else 0


# ---------------- 各阶段 ----------------

def stage_preflight(ctx) -> str:
    """检查前置。缺什么就明确说缺什么，不猜。"""
    notes = []
    if not ctx["base"].is_dir():
        ctx["base"].mkdir(parents=True, exist_ok=True)
        notes.append(f"已创建下载根目录 {ctx['base']}")
    root = ctx["root"]
    notes.append(f"目标目录 {root}（现有 {md_count(root)} 篇 md）")

    # 微信 PC 端：4.x 起进程名由 WeChat.exe 改为 Weixin.exe，只认旧名会永远误报「未检测到」
    wx = subprocess.run(["tasklist"], capture_output=True, text=True,
                        errors="replace").stdout.lower()
    wx_running = any(name in wx for name in ("wechat.exe", "weixin.exe"))
    notes.append("微信 PC 端：" + ("在运行" if wx_running
                                  else "未检测到 —— 下载前需先开微信并打开该号文章"))
    notes.append("文章链接：" + ("已提供" if ctx.get("article_url")
                                else "未提供（工具会没有输入可解析，建议加 --article-url）"))

    # 下载工具窗口（需要 pywinauto；缺了要在这里说清楚，别在 import 处无声退出）
    ck = subprocess.run([str(PY), "-c", "import pywinauto"], capture_output=True, text=True)
    if ck.returncode != 0:
        raise StageFail(f"{PY} 里没有 pywinauto，装一下：{PY} -m pip install pywinauto pywin32 comtypes")
    notes.append(f"python {PY}")
    sys.path.insert(0, str(SKILL / "scripts"))
    try:
        import clicker
    except SystemExit as e:                        # clicker 缺依赖时用 SystemExit(6)
        raise StageFail(f"clicker 导入失败（退出码 {e.code}）") from None
    wins = clicker.find_windows("", ["Mywindow"])
    if wins:
        notes.append("下载工具：已在运行（附着）")
    else:
        notes.append("下载工具：未运行" + ("，download 阶段会自动按正确 cwd 启动" if ctx["exe"].exists()
                                      else f"，且找不到 {ctx['exe']}"))
    # 元典
    vein = ctx["vein"]
    need = ["tools/import-wechat.py", "tools/classify/validate.py", "tools/export-site.mjs"]
    missing = [n for n in need if not (vein / n).exists()]
    if missing:
        raise StageFail(f"元典工作区缺文件：{missing}")
    notes.append(f"元典工作区 {vein}")
    nodes = subprocess.run(["node", "-v"], capture_output=True, text=True).stdout.strip()
    notes.append(f"node {nodes or '缺失'}")
    return "；".join(notes)


def stage_scout(ctx) -> str:
    """微信「赞和收藏」逐篇发现：只点所属公众号还没采过的文章。

    前置：先跑一次 scripts/capture_templates.py 校准 UI 模板
    （微信停在「赞和收藏」页且不被其他窗口遮挡）。没校准就硬跑会报错，
    这是故意的——不猜坐标。

    **交接约定**：下载工具的「1.获取公众号id」要求微信**正开着该号的文章**
    （否则日志只刷「请先在左面打开微信内置浏览器」，profile 里 wait_log 的
    `contains_any` 四个分支里就有这一条）。所以这里默认 `--return-key none`，
    点开后**不**用 Ctrl+W 关掉 tab，把文章页原样留给 download 阶段。
    2026-10-23 修：此前固定用默认 ctrlw，scout 把文章关掉后 download 必然拿不到
    密钥，链路看起来"能跑"但下载阶段永远 0 产出。
    scout 单独跑、想回到列表页时显式传 `--return-key ctrlw`。
    """
    rounds = str(ctx.get("scout_rounds", 1))
    cmd = [PY, SKILL / "scripts" / "wechat_favorites.py",
           "--download-root", str(ctx["base"]), "--max-rounds", rounds,
           "--return-key", str(ctx.get("return_key", "none"))]
    if ctx.get("scout_dry"):
        cmd.append("--dry-run")
    r = run(cmd, timeout=900)
    m = re.search(r'"clicked": (\d+), "skipped": (\d+)', r.stderr or r.stdout or "")
    if m:
        return f"点击 {m.group(1)} 篇 / 跳过 {m.group(2)} 篇"
    return "scout 已执行（未解析到汇总行，见 stderr JSONL）"


def _clean_env() -> dict:
    """给下载工具一份**剥掉代理变量**的环境。

    2026-10-23 真机事故：点「1.获取公众号id」后工具日志只刷一句
    「提示：可以把梯子关了试一试」＋ 一个 github issue 链接。查下来不是网络问题：
    `curl https://mp.weixin.qq.com/` 直连 200，但本进程的 env 里带着
    HTTP_PROXY/HTTPS_PROXY=http://127.0.0.1:58016（WorkBuddy 内部代理），
    subprocess 默认继承 env ⇒ 工具的请求全被塞进那个代理，于是它以为用户开了梯子。
    工具只访问微信，剥掉代理没有任何副作用。
    """
    drop = {"http_proxy", "https_proxy", "all_proxy", "ftp_proxy",
            "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "FTP_PROXY"}
    env = {k: v for k, v in os.environ.items() if k not in drop}
    env.setdefault("NO_PROXY", "mp.weixin.qq.com,localhost,127.0.0.1")
    env.setdefault("no_proxy", env["NO_PROXY"])
    return env


def stage_download(ctx) -> str:
    """按公众号名批量下载。以产物计数判成功。"""
    root = ctx["root"]
    before = md_count(root)
    mtimes = [p.stat().st_mtime for p in root.glob("*.md")] if root.is_dir() else []

    sys.path.insert(0, str(SKILL / "scripts"))
    import clicker
    wins = clicker.find_windows("", ["Mywindow"])
    if not wins:
        if not ctx["exe"].exists():
            raise StageFail(f"下载工具未运行且找不到 exe：{ctx['exe']}")
        # 必须以 **exe 所在目录** 作为 cwd 启动。这不是洁癖，是 2026-10-23 真机二分
        # 出来的硬约束：cwd=exe 目录时「获取密钥成功」3/3；cwd=下载目录/全新空目录
        # 时 3/3 失败（日志卡在「开始获取密钥...」或刷「请先在微信打开复制的链接」）。
        # 已排除的候选：缓存体积（清空 489MB 无效）、exe 与 cwd 同目录（复制 exe 到
        # 下载目录仍失败）。闭源工具的黑盒行为，只能按现象遵守。
        # 产物目录**不受** cwd 影响（实测 cwd=桌面时产物仍落 <base>/<号名>），所以
        # 这里不必再为了产物去改 cwd。
        print(f"    以 cwd={ctx['exe'].parent} 启动工具（cwd 必须是 exe 目录，否则取不到密钥）")
        subprocess.Popen([str(ctx["exe"])], cwd=str(ctx["exe"].parent), env=_clean_env())
        for _ in range(30):
            time.sleep(1)
            if clicker.find_windows("", ["Mywindow"]):
                break
        else:
            raise StageFail("工具启动后 30 秒内没出现主窗口")
        # 界面刚创建时控件事件还没接上，立刻点会**静默无效**（实测：日志一字不变）。
        time.sleep(float(ctx.get("tool_settle", 3.0)))

    cmd = [PY, CLICKER, "run", "--profile", "wechat_batch_downloader", "--yes"]
    if ctx.get("article_url"):
        # 工具的「微信文章链接」框留空时点「1.获取公众号id」不写任何日志（实测），
        # 所以有链接就填进去；没有就让 profile 的那一步 skip_if_empty 跳过。
        cmd += ["--var", "ARTICLE_URL=%s" % ctx["article_url"]]
    # 时间范围永远显式传下去（默认 all）：profile 里两条互斥步骤靠 RANGE 二选一，
    # 不传虽然也会走 when_default 的「全部」，但显式传能把"这一批按什么口径抓的"
    # 留在命令行里 —— 事后查证全靠它。
    cmd += ["--var", "RANGE=%s" % (ctx.get("range") or "all")]
    run(cmd)
    time.sleep(3)

    after = md_count(root)
    new = [p for p in root.glob("*.md") if p.stat().st_mtime > (max(mtimes) if mtimes else 0)]
    if after <= before and not new:
        raise StageFail(
            "无新增 md。常见原因：① 微信里没先打开该号文章（拿不到密钥）；"
            "② 没传 --article-url，工具「微信文章链接」框为空会让『获取公众号id』"
            "静默无响应；③ 工具的『保存目录』不在 %s；④ 时间范围/翻页设置不对。"
            "先看工具日志再重跑。" % root)
    shells = [p for p in root.glob("*.md") if p.stat().st_size < 400]
    ratio = len(shells) / max(after, 1)
    if ratio > 0.30:
        print(f"    ⚠ 空壳比例 {len(shells)}/{after} = {ratio:.0%}，建议先人工看一眼")
    return f"新增 md {len(new)} 个，现有 {after} 篇，空壳 {len(shells)} 个"


# 受限页/微信 UI 残句：正文里出现任何一个，说明这一篇没抓干净。
# 同一份清单在 package 阶段（export_import_package.py）里也有一份，两处必须一致。
RESTRICTED = ("微信扫一扫可打开此内容", "使用完整服务", "取消  允许", "环境异常")


def _clean_residue(root: Path) -> list[str]:
    """扫 clean/*.md，返回「文件（命中词）」清单；空列表 = 干净。"""
    clean_dir = root / "clean"
    files = sorted(clean_dir.glob("*.md")) if clean_dir.is_dir() else []
    bad = []
    for p in files:
        text = p.read_text(encoding="utf-8", errors="replace")
        hit = [k for k in RESTRICTED if k in text]
        if hit:
            bad.append(f"{p.stem}（{hit[0]}）")
    return bad


def stage_clean(ctx) -> str:
    run([PY, TOOLS / "localize_md.py", "--root", ctx["root"], "--apply"])
    # --root 必须显式传：该脚本默认目录写死为「食品研发与生产」，
    # 漏传会把别的号的 md 当成本批一起清洗。2026-10-23 修。
    run([PY, TOOLS / "clean_noise_v2.py", "--root", ctx["root"], "--apply"])
    # 后置判据：清洗完就不许再有受限页/UI 残句。
    # 这一项原本只在 package 阶段查，而 package 跑在 manifest 之后 ——
    # 2026-10-23 因 clean_noise 读旧 manifest 漏扫 3 篇，错误晚两个阶段才暴露，
    # 报错还只说"未通过"、不说哪几篇。提前到本阶段就地拦截，且点名。
    bad = _clean_residue(ctx["root"])
    if bad:
        raise StageFail(
            f"清洗后仍有 {len(bad)} 篇残留受限页/UI 残句："
            + "；".join(bad[:5]) + ("…" if len(bad) > 5 else ""))
    return "图片路径已本地化、UI 噪声已清（0 篇残留）"


def stage_meta(ctx) -> str:
    run([PY, TOOLS / "extract_meta.py", ctx["root"]])
    run([PY, TOOLS / "fetch_publish_time.py", "--root", ctx["root"], "--apply"])
    return "链接/公众号/发表日期已补"


def stage_manifest(ctx) -> str:
    cmd = [PY, TOOLS / "build_manifest.py", ctx["root"]]
    # 图片压缩入库后，真源是 <vault>/20_Sources/图片，下载目录不再持有它们。
    # 不告诉 manifest 这一点，图片引用会被统计成 0 处、package 再把 943 处判成断链。
    img_root = ctx["vein"] / "vault" / "20_Sources" / "图片"
    if img_root.is_dir():
        cmd += ["--img-root", img_root]
    run(cmd)
    man = json.loads((ctx["root"] / "_reports" / "manifest.json").read_text(encoding="utf-8"))
    if man.get("missing_metadata"):
        print(f"    ⚠ 仍有 {man['missing_metadata']} 篇缺元数据，ingest 会照常进行但 needs 非空")
    return f"清单 {man['article_count']} 篇 / 图片引用 {man['image_refs']} 处"


def stage_package(ctx) -> str:
    vp = ctx["root"] / "_reports" / "import" / "verify.json"
    try:
        run([PY, TOOLS / "export_import_package.py", "--root", ctx["root"]])
    except StageFail:
        # 核对失败时把「是哪几项没过、实际值多少」直接说出来，别只报项名
        bad = []
        if vp.is_file():
            try:
                v = json.loads(vp.read_text(encoding="utf-8"))
                bad = [f"{c['name']}（{c.get('value')}）"
                       for c in v.get("checks", []) if not c.get("ok")]
            except Exception:
                pass
        extra = ""
        residue = _clean_residue(ctx["root"])
        if residue:
            extra = f"；clean 残留 {len(residue)} 篇：" + "、".join(residue[:3])
        raise StageFail("导入包核对未通过：" + ("；".join(bad) if bad else "见上方输出") + extra) from None
    vf = json.loads(vp.read_text(encoding="utf-8"))
    return f"{vf['articles']} 条记录，核对 {len(vf['checks'])} 项全绿"


def stage_ingest(ctx) -> str:
    nd = ctx["root"] / "_reports" / "import" / "articles.ndjson"
    if not nd.exists():
        raise StageFail("缺少导入包，请先跑 package 阶段")
    r = run([PY, ctx["vein"] / "tools" / "import-wechat.py", "--apply", "--source", nd],
            cwd=ctx["vein"])
    out = r.stdout or ""
    m = re.search(r"写入 source 笔记 (\d+) 个；跳过 (\d+) 个；分类 JSON 现有条目 (\d+)", out)
    if m:
        return f"写入 {m.group(1)} 篇 / 跳过 {m.group(2)} 篇，vault 现有条目 {m.group(3)}"
    # 正则失配不当失败：以 vault 实际文件数为准（这才是真凭据）
    web = ctx["vein"] / "vault" / "20_Sources" / "web"
    n = len(list(web.glob("*.md"))) if web.is_dir() else 0
    if not n:
        raise StageFail("写入器没有报写入数，且 vault/20_Sources/web 为空 —— 需人工看输出")
    print(f"    ⚠ 未能解析写入器输出，改用 vault 实数 {n} 篇")
    return f"vault 现有 source 笔记 {n} 篇"


def stage_guards(ctx) -> str:
    """对 vault 笔记跑 recurring 守卫：空章节归正（幂等）。

    trim-duplicate-h1 / rename-unsafe-slugs 已由 import-wechat 在入库时内联处理
    （note_text 剥离标题 H1、BAD_CHARS 含 & # %），无需每批跑。
    --reclassify：分类法变更后用同一套规则重算已入库笔记归类，订正不一致项。
    """
    r = run([PY, ctx["vein"] / "tools" / "normalize-empty-headings.py", "--apply"],
            cwd=ctx["vein"])
    out = r.stdout or ""
    if "无需改动（幂等）" in out:
        note = "空章节归正：0 处（幂等）"
    else:
        note = "空章节归正完成"
    if ctx.get("reclassify"):
        nd = ctx["root"] / "_reports" / "import" / "articles.ndjson"
        if not nd.exists():
            raise StageFail("reclassify 需要导入包，请先跑 package 阶段")
        run([PY, ctx["vein"] / "tools" / "classify" / "reclassify-imported.py",
             "--source", nd, "--apply"], cwd=ctx["vein"])
        note += "；重分类完成"
    return note


def stage_images(ctx) -> str:
    """把新下载批次引用的图片压缩入库，并核对引用全部落地。

    图片真源是下载目录 <base>/<account>/图片（下载工具产出），而笔记引用指向
    vault/20_Sources/图片。导入只搬了 markdown，没搬图 —— 这正是之前 943 处全断链
    的根因。本阶段把前者压缩搬进后者，并（默认）把库外重复原图移入备份。
    本批次无图（纯文字文章）不算失败，只提示。

    --strict-images（CI 用）：写前先跑 --check 门禁。任一引用既不在库内、源里也没有
    ⇒ 整批不写库直接 StageFail（fail-fast），避免留下「落了一半、还有断链」的半截库。
    默认关：手动跑仍按「能落地的先落、缺的末尾报」的宽容行为，不因此中断全链路。
    """
    src = ctx["root"] / "图片"
    if not src.is_dir():
        return "本批次下载目录无 图片/ 子目录，跳过（无图可入库）"
    tool = ctx["vein"] / "tools" / "import-images.py"
    if ctx.get("strict_images"):
        # 写前 fail-fast：门禁不过 ⇒ run() 抛 StageFail，整批不写库。
        # （--check 只读、不写库；只顺带在 docs/reports 落一份报告，可被 audit 复用。）
        run([PY, tool, "--check", "--src", str(src), "--vault", str(ctx["vein"])],
            quiet=True)
    cmd = [PY, tool, "--apply", "--src", str(src), "--vault", str(ctx["vein"])]
    if ctx.get("prune_outside", True):
        cmd.append("--prune-outside")
    run(cmd)
    return "图片压缩入库 + 引用核对完成"


def stage_maps(ctx) -> str:
    run([PY, ctx["vein"] / "tools" / "build-link-module.py", "--apply"], cwd=ctx["vein"])
    return "智库链接模块已重建"


def stage_derived(ctx) -> str:
    run(["node", "tools/rebuild-derived.mjs"], cwd=ctx["vein"], timeout=600)
    return "Home / hot / log / canvas / orphans 已重建"


def stage_export(ctx) -> str:
    r = run(["node", "tools/export-site.mjs"], cwd=ctx["vein"], timeout=900)
    out = r.stdout or ""
    f = re.search(r"写入 (\d+) 个文件", out)
    d = re.search(r"内容指纹 ([0-9a-f]{16})", out)
    return (f"站点写入 {f.group(1)} 个文件" if f else "站点已导出") + \
           (f"，指纹 {d.group(1)}…（两次相同即幂等）" if d else "")


def stage_verify(ctx) -> str:
    r = run([PY, ctx["vein"] / "tools" / "classify" / "validate.py", "--self-test"], cwd=ctx["vein"])
    if "VERDICT: PASS" not in (r.stdout or ""):
        raise StageFail("validate.py 未通过，见上方输出")
    m = re.search(r"source 笔记 (\d+) 个 \| 分类条目 (\d+) 个 \| 问题 (\d+) 处", r.stdout or "")
    if m and m.group(1) != m.group(2):
        raise StageFail(f"笔记数 {m.group(1)} ≠ 分类条目数 {m.group(2)}，有笔记未归类")
    # 追加：图片引用必须全部落地（断图 = 站点不可用）。audit-images 退出码 5 即缺失，
    # run() 会据此抛 StageFail。
    run([PY, ctx["vein"] / "tools" / "audit-images.py", "--vault", str(ctx["vein"])],
        cwd=ctx["vein"])
    return (m.group(0) if m else "PASS") + "；图片引用全落地"


STAGES = {
    "preflight": stage_preflight, "scout": stage_scout, "download": stage_download,
    "clean": stage_clean, "meta": stage_meta, "manifest": stage_manifest,
    "package": stage_package, "ingest": stage_ingest, "guards": stage_guards,
    "images": stage_images, "maps": stage_maps,
    "derived": stage_derived, "export": stage_export, "verify": stage_verify,
}

# preflight 只读环境；verify 只跑 validate.py（--self-test 的坏样本写在 tempdir，
# 不碰 vault）⇒ 这两个 dry 模式也真跑，其余全部写盘。
# 2026-10-22 实测教训：只把 download/ingest/... 当写阶段，--plan 一跑就把
# 95 篇 source_url/published_at 清空了。所以这里是「减法」而非「加法」白名单。
READ_ONLY = {"preflight", "verify"}
WRITE_STAGES = set(ORDER) - READ_ONLY


def main(argv=None) -> int:
    # 依赖对齐：clicker 是**在进程内** import 的，所以光把子进程换成 PY 不够。
    # 当前解释器缺 pywinauto 时，用 PY 重新拉起自己并把退出码透传。
    # （不用 os.execv：Windows 上实测会丢掉子进程 stdout。）
    if os.environ.get("_UIAC_REEXEC") != "1":
        try:
            import pywinauto  # noqa: F401
        except ImportError:
            if PY.resolve() != Path(sys.executable).resolve():
                print(f"[env] 当前解释器缺 pywinauto，改用 {PY} 执行", file=sys.stderr)
                env = dict(os.environ, _UIAC_REEXEC="1")
                args = [str(PY), str(Path(__file__).resolve())] + \
                       (list(sys.argv[1:]) if argv is None else list(argv))
                return subprocess.run(args, env=env).returncode

    ap = argparse.ArgumentParser(description="公众号采集 → 元典入库 全链路")
    ap.add_argument("--account", required=True, help="任务目标：公众号名称（决定下载目录名）")
    ap.add_argument("--base", default=DEFAULT_BASE, help="下载根目录（默认 桌面\\下载）")
    ap.add_argument("--vein", default=DEFAULT_VEIN, help="元典工作区")
    ap.add_argument("--exe", default=DEFAULT_EXE, help="下载工具 exe（需要时由本脚本按正确 cwd 启动）")
    ap.add_argument("--from-step", default="", help="从该阶段开始")
    ap.add_argument("--to-step", default="", help="到该阶段为止")
    ap.add_argument("--skip", default="", help="逗号分隔要跳过的阶段")
    ap.add_argument("--dry", action="store_true", help="只打印计划与前置检查")
    ap.add_argument("--plan", action="store_true", help="等同 --dry")
    ap.add_argument("--yes", action="store_true", help="确认执行写操作（download/ingest/maps/derived/export）")
    ap.add_argument("--scout-rounds", type=int, default=1,
                    help="scout 阶段本轮处理几篇（默认 1）")
    ap.add_argument("--scout-dry", action="store_true",
                    help="scout 阶段只决策不点击")
    ap.add_argument("--return-key", default="none",
                    choices=("none", "ctrlw", "esc", "altleft"),
                    help="scout 点开文章后是否返回列表：默认 none＝把文章页留给 "
                         "download（工具的『获取公众号id』要求微信里正开着该号文章）；"
                         "单独跑 scout 想回列表用 ctrlw")
    ap.add_argument("--article-url", default="",
                    help="该号任意一篇**当前可访问**的文章链接：会填进工具的"
                         "「微信文章链接」框（留空时工具点『1.获取公众号id』不写任何日志）")
    ap.add_argument("--range", default="all", choices=("all", "monthly"),
                    help="下载工具的时间范围：all＝全部历史（默认），monthly＝一个月内。"
                         "批量采集一个号的历史时必须用 all，monthly 会静默漏掉更早的篇目")
    ap.add_argument("--reclassify", action="store_true",
                    help="guards 阶段额外用当前分类法重算已入库笔记归类（分类法变更后跑一次）")
    ap.add_argument("--keep-outside", action="store_true",
                    help="images 阶段不移动库外重复原图（默认会移入 .staging 备份）")
    ap.add_argument("--strict-images", action="store_true",
                    help="images 阶段写前 fail-fast：先用 --check 判门禁，任一引用不可落地"
                         "（库内无且源内也无）则整批不写库直接中断；默认关，CI 可显式开启")
    args = ap.parse_args(argv)

    dry = args.dry or args.plan
    skip = {s.strip() for s in args.skip.split(",") if s.strip()}
    bad = skip - set(ORDER)
    if bad:
        print(f"未知阶段: {bad}；可选: {ORDER}", file=sys.stderr)
        return 2

    i0 = ORDER.index(args.from_step) if args.from_step else 0
    i1 = ORDER.index(args.to_step) + 1 if args.to_step else len(ORDER)
    plan = [s for s in ORDER[i0:i1] if s not in skip]

    base = Path(args.base).resolve()
    ctx = {"base": base, "root": base / args.account, "vein": Path(args.vein).resolve(),
           "exe": Path(args.exe), "account": args.account,
           "scout_rounds": args.scout_rounds, "scout_dry": args.scout_dry,
           "return_key": args.return_key, "article_url": args.article_url.strip(),
           "range": args.range,
           "reclassify": args.reclassify, "prune_outside": not args.keep_outside,
           "strict_images": args.strict_images}

    print(f"目标公众号: {args.account}")
    print(f"下载目录  : {ctx['root']}")
    print(f"元典工作区: {ctx['vein']}")
    print(f"阶段      : {' → '.join(plan)}")
    if dry:
        print("\n[dry] 只做前置检查，不执行写操作\n")
    else:
        print()
        if not args.yes and (set(plan) & WRITE_STAGES):
            print("需要 --yes 才能执行写操作阶段：" + ", ".join(sorted(set(plan) & WRITE_STAGES)),
                  file=sys.stderr)
            return 2

    results, failed = [], None
    for name in plan:
        fn = STAGES[name]
        label = "（写）" if name in WRITE_STAGES else ""
        print(f"[{name}]{label}")
        if dry and name in WRITE_STAGES:
            print("    跳过：写操作，dry 模式不执行")
            results.append((name, "skip", "-"))
            continue
        t0 = datetime.now()
        try:
            detail = fn(ctx)
            results.append((name, "ok", detail))
        except StageFail as e:
            print(f"    ✗ {e}")
            results.append((name, "FAIL", str(e)[:120]))
            failed = name
            break
        except SystemExit as e:                    # 子模块用 SystemExit 表示环境不具备
            print(f"    ✗ 阶段内退出 SystemExit({e.code})，多为依赖缺失")
            results.append((name, "FAIL", f"SystemExit({e.code})"))
            failed = name
            break
        except Exception as e:                     # 未预期异常也要大声报
            print(f"    ✗ 未预期异常：{type(e).__name__}: {e}")
            results.append((name, "FAIL", f"{type(e).__name__}: {e}"))
            failed = name
            break
        print(f"    ✓ 用时 {(datetime.now()-t0).seconds}s")
        print()

    print("=" * 66)
    for name, status, detail in results:
        mark = {"ok": "✓", "skip": "·", "FAIL": "✗"}[status]
        print(f"  {mark} {name:<10} {detail}")
    print("=" * 66)
    if failed:
        print(f"中断于 {failed}。修好后续跑：--from-step {failed}")
        return 1
    print("全链路完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
