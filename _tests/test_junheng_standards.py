#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
junheng-standards 契约断言（最硬的一组）
核心不变量：
  - NRC 六档齐备（dog/cat × growth/adult/reproduction），共 202 条
  - 每条同时具备 min（per 100g DM）与 minME（per 1000 kcal ME）
  - 【4:1 自洽】min × 2.5 ≈ minME（NRC 假定 1kg DM ≡ 4000 kcal ME）
    这是本项目已确立的污染自检核心判据 —— 任何 OCR 污染/单位错乱都会打破它。
实现：把 standards.js 复制到临时文件后用 node ESM 动态导入（仓无 type:module）。
"""
import json
import os
import re
import shutil
import tempfile

SKILL = "junheng-standards"
JS = "scripts/vendor/standards.js"


def _break_vitd(text):
    """把 NRC 犬生长档 vitamin_d 的 minME 放大 10 倍 -> 4:1 必然破。
    注意：实际写法是 `minME: 138.0`（带小数），用正则避免因空格/小数形式差异而不命中。"""
    return re.sub(r"(vitamin_d:\s*\{\s*min:\s*55\.2,\s*minME:\s*)138(\.0)?",
                  r"\g<1>1380", text, count=1)


FAULTS = {JS: _break_vitd}

PROBE = r"""
import { STANDARD_SETS } from %s;
const n = STANDARD_SETS?.NRC?.stages;
if (!n) { console.log(JSON.stringify({err:'NO_NRC'})); process.exit(0); }
const out = {};
for (const sp of ['dog','cat']) for (const st of ['growth','adult','reproduction']) {
  const o = n[sp]?.[st];
  if (!o) { out[sp+'.'+st] = null; continue; }
  const items = [];
  for (const k of Object.keys(o)) {
    const v = o[k];
    if (v && typeof v === 'object' && 'min' in v) items.push([k, v.min, v.minME]);
  }
  out[sp+'.'+st] = items;
}
console.log(JSON.stringify(out));
"""


def _run_probe(ctx):
    """把（可能被证伪污染的）standards.js 落到临时目录，用 node ESM 导入。"""
    tmpdir = tempfile.mkdtemp(prefix="jhtest_")
    try:
        src = ctx.read(JS)
        tmp = os.path.join(tmpdir, "standards.mjs")
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(src)
        url = "file:///" + tmp.replace("\\", "/")
        probe = os.path.join(tmpdir, "probe.mjs")
        with open(probe, "w", encoding="utf-8", newline="\n") as f:
            f.write(PROBE % json.dumps(url))
        rc, out, err = ctx.run(["node", probe], cwd=tmpdir, timeout=60)
        if rc != 0:
            return None, f"node 退出码 {rc}：{(err or out)[:300]}"
        return json.loads(out.strip().splitlines()[-1]), None
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def checks(ctx):
    out = []

    fm = ctx.frontmatter()
    out.append((fm.get("name") == SKILL, f"frontmatter name=={SKILL}（实际 {fm.get('name')!r}）"))
    out.append((bool(fm.get("license")), "frontmatter 含 license"))
    out.append((bool(fm.get("compatibility")), "frontmatter 含 compatibility"))

    if not ctx.exists(JS):
        out.append((False, f"{JS} 缺失"))
        return out

    data, err = _run_probe(ctx)
    if err:
        out.append((False, f"加载 standards.js 失败：{err}"))
        return out

    # 1. 六档齐备
    expect = [f"{sp}.{st}" for sp in ("dog", "cat") for st in ("growth", "adult", "reproduction")]
    missing = [k for k in expect if not data.get(k)]
    out.append((not missing, f"NRC 六档齐备（缺 {missing}）" if missing else "NRC 六档齐备"))

    # 2. 每档条目数下限（动态基准：批 B 已补全维生素/矿物质，202 是批发前旧值，不可硬编码）
    per = {k: len(v) for k, v in data.items() if v}
    thin = {k: n for k, n in per.items() if n < 32}
    out.append((not thin, f"六档每档条目数 >= 32（实际 {per}）" + (f"；偏少 {thin}" if thin else "")))
    total = sum(per.values())
    out.append((total >= 200, f"NRC 条目总数 >= 200（实际 {total}）"))

    # 3. 每条都有 min 与 minME
    bad_pair = []
    for k, items in data.items():
        if not items:
            continue
        for name, mn, me in items:
            if mn is None or me is None:
                bad_pair.append(f"{k}.{name}")
    out.append((not bad_pair, "每条均含 min 与 minME" + (f"；缺失 {bad_pair[:5]}" if bad_pair else "")))

    # 4. 4:1 自洽（min × 2.5 ≈ minME），容差 10%
    #    排除项：该类字段 min 与 minME 单位不同（% DM vs mg/1000kcal），本不适用 4:1
    MIXED_UNIT = {"sodium", "chloride", "magnesium", "iodine"}
    viol = []
    skipped = 0
    for k, items in data.items():
        if not items:
            continue
        for name, mn, me in items:
            if name in MIXED_UNIT:
                skipped += 1
                continue
            try:
                mn, me = float(mn), float(me)
            except (TypeError, ValueError):
                continue
            if mn <= 0:
                continue
            ratio = me / mn
            if abs(ratio - 2.5) > 2.5 * 0.10:
                viol.append(f"{k}.{name}={mn}/{me}(比值{ratio:.2f})")
    out.append((not viol,
                f"单位一致字段满足 4:1 自洽（min×2.5≈minME，容差 10%；"
                f"已排除混合单位字段 {skipped} 条）"
                + (f"；违例 {len(viol)} 项：{viol[:4]}" if viol else "")))

    return out
