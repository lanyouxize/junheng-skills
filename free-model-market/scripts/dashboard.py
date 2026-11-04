#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""免费模型超市 · 可视化仪表盘生成器（零依赖，仅标准库）

读取：
  - references/model-catalog.json      （货架导出，providers）
  - references/products.json           （配套商品，可选）
  - reports/external-catalog-signals-latest.md （外部信号，可选）
输出：
  单文件 HTML（内联 CSS/JS/SVG，无 CDN，离线可用，浅色主题）。

用法：
  python 免费模型超市-dashboard.py [输出路径]
  默认输出到 <仓库>/reports/free-model-market-dashboard.html
"""
# --- 沙箱容错：强制 UTF-8 输出，避免非 UTF-8 控制台（cp1252/cp936）抛 UnicodeEncodeError ---
try:
    import sys as _sys
    for _stream in (_sys.stdout, _sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
except Exception:
    pass
# --- end 沙箱容错 ---

import json
import re
import os
import sys
import html
from pathlib import Path

STATUS_LABEL = {
    "active": "active", "degraded": "degraded",
    "expired": "expired", "unverified": "unverified", "unknown": "unknown",
}


def find_base() -> Path:
    here = Path(__file__).resolve()
    for cand in (here.parent, here.parent.parent):
        if (cand / "references" / "model-catalog.json").exists():
            return cand
    if (Path.cwd() / "references" / "model-catalog.json").exists():
        return Path.cwd()
    sys.exit("[错误] 找不到 references/model-catalog.json")


def load_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:  # 优雅降级
        print(f"[WARN] 读取失败 {p}: {e}")
        return {}


def esc(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def short(s, n=44) -> str:
    s = re.sub(r"\s+", " ", "" if s is None else str(s)).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def host_of(url: str) -> str:
    m = re.match(r"https?://([^/]+)", url or "")
    return m.group(1) if m else ""


def section_key(sec: str) -> str:
    if "永久免费" in sec:
        return "perm"
    if "试用" in sec:
        return "trial"
    if "已停服" in sec or "退出" in sec:
        return "expired"
    return "other"


def parse_signals(path: Path) -> dict:
    out = {"ok": False, "aligned": "", "new": [], "dead": []}
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return out
    m = re.search(r"对齐:\s*(\d+)", text)
    if m:
        out["ok"] = True
        out["aligned"] = m.group(1)
    # 分段收集表格首列
    cur = None
    for line in text.splitlines():
        if line.startswith("## "):
            if "新增候选" in line:
                cur = "new"
            elif "可能失效" in line:
                cur = "dead"
            else:
                cur = None
            continue
        if cur and line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if not cells or cells[0] in ("外部名称", "货架名称") or set(cells[0]) <= set("-: "):
                continue
            out[cur].append(cells[0])
    return out


def build_html(cat: dict, prod: dict, sig: dict) -> str:
    provs = cat.get("providers", []) or []
    total = len(provs)
    by_status = {"active": 0, "degraded": 0, "expired": 0, "unverified": 0, "unknown": 0}
    sec = {"perm": 0, "trial": 0, "expired": 0, "other": 0}
    vendors = set()
    for p in provs:
        st = (p.get("status") or "unknown").strip().lower()
        by_status[st] = by_status.get(st, 0) + 1
        sec[section_key(p.get("section", ""))] += 1
        vendors.add(re.sub(r"[（(].*?[)）]", "", p.get("name", "")).strip())
    vendor_n = len(vendors)
    snapshot = cat.get("snapshot_date", "unknown")
    generated = cat.get("generated_at", "")

    # 状态堆叠条
    bar_colors = {"active": "#16a34a", "degraded": "#d97706", "expired": "#94a3b8", "unverified": "#7c3aed", "unknown": "#cbd5e1"}
    segs = []
    for k in ("active", "degraded", "unverified", "expired", "unknown"):
        n = by_status.get(k, 0)
        if n:
            pct = n / total * 100 if total else 0
            segs.append(f'<span class="seg" style="width:{pct:.2f}%;background:{bar_colors[k]}" title="{k} {n}"></span>')
    bar = "".join(segs) if segs else '<span class="seg" style="width:100%;background:#e2e8f0"></span>'

    # 表格行
    rows = []
    for i, p in enumerate(provs, 1):
        name = p.get("name", "")
        st = (p.get("status") or "unknown").strip().lower()
        sk = section_key(p.get("section", ""))
        eps = p.get("endpoints") or []
        host = host_of(eps[0]) if eps else ""
        quota = short(p.get("quota") or p.get("notes") or p.get("event") or "—", 48)
        rows.append(
            f'<tr data-status="{esc(st)}" data-sec="{sk}">'
            f'<td class="num">{i}</td>'
            f'<td class="name">{esc(name)}</td>'
            f'<td><span class="pill sec-{sk}">{esc({"perm":"永久免费","trial":"试用额度","expired":"已停服","other":"其他"}.get(sk,"其他"))}</span></td>'
            f'<td><span class="pill {esc("st-" + st)}">{esc(st)}</span></td>'
            f'<td class="q" title="{esc(p.get("quota") or p.get("event") or "")}">{esc(quota)}</td>'
            f'<td class="host">{esc(host or "—")}</td>'
            "</tr>"
        )
    row_html = "".join(rows)

    # 商品卡
    prods = prod.get("products", []) or []
    prod_html = ""
    if prods:
        q = prods[0]
        up = q.get("upstream", {})
        mech = "".join(f"<li>{esc(m)}</li>" for m in q.get("mechanism", []))
        good = "、".join(q.get("value_scope", {}).get("good_for", []))
        lim = "、".join(q.get("value_scope", {}).get("limited_for", []))
        prod_html = f"""
        <section class="card product">
          <div class="ph"><span class="badge">商品</span><h2>{esc(q.get("name",""))}</h2><span class="tagline">{esc(q.get("tagline",""))}</span></div>
          <p class="meta">上游 <b>{esc(up.get("repo",""))}</b> · {esc(up.get("license",""))} · v{esc(up.get("version",""))} · 仅 {esc(q.get("host",""))}</p>
          <ul class="mech">{mech}</ul>
          <div class="scope">
            <div class="good"><b>有效：</b>{esc(good)}</div>
            <div class="lim"><b>有限：</b>{esc(lim)}</div>
          </div>
        </section>"""
    else:
        prod_html = '<section class="card"><p class="muted">尚未上架配套商品。</p></section>'

    # 外部信号
    sig_html = '<p class="muted">未生成外部信号。</p>'
    if sig.get("ok"):
        newc = "".join(f'<span class="chip">{esc(x)}</span>' for x in sig["new"]) or '<span class="muted">无</span>'
        dead = "".join(f'<span class="chip dead">{esc(x)}</span>' for x in sig["dead"]) or '<span class="muted">无</span>'
        sig_html = f"""
        <div class="sigrow"><span class="kpi small"><b>{esc(sig["aligned"])}</b><span>对齐</span></span>
        <span class="kpi small"><b>{len(sig["new"])}</b><span>新增候选</span></span>
        <span class="kpi small"><b>{len(sig["dead"])}</b><span>可能失效</span></span></div>
        <div class="chiplabel">新增候选</div><div class="chips">{newc}</div>
        <div class="chiplabel">可能失效（仅信号，需实测复核，未转 expired）</div><div class="chips">{dead}</div>"""

    tpl = PAGE
    repl = {
        "__TOTAL__": str(total),
        "__VENDORS__": str(vendor_n),
        "__PERM__": str(sec["perm"]),
        "__TRIAL__": str(sec["trial"]),
        "__EXPIRED_SEC__": str(sec["expired"]),
        "__ACTIVE__": str(by_status.get("active", 0)),
        "__DEGRADED__": str(by_status.get("degraded", 0)),
        "__UNVERIFIED__": str(by_status.get("unverified", 0)),
        "__SNAPSHOT__": esc(snapshot),
        "__GENERATED__": esc(generated),
        "__BAR__": bar,
        "__ROWS__": row_html,
        "__PRODUCT__": prod_html,
        "__SIGNALS__": sig_html,
    }
    for k, v in repl.items():
        tpl = tpl.replace(k, v)
    return tpl


def main():
    base = find_base()
    cat = load_json(base / "references" / "model-catalog.json")
    prod = load_json(base / "references" / "products.json")
    sig = parse_signals(base / "reports" / "external-catalog-signals-latest.md")

    page = build_html(cat, prod, sig)

    if len(sys.argv) > 1:
        out = Path(sys.argv[1])
    else:
        reports = base / "reports"
        out = (reports if reports.exists() else base) / "free-model-market-dashboard.html"
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(page, encoding="utf-8")
        written = str(out)
    except Exception as e:
        # 只读文件系统 / 权限受限时降级：写到临时目录，不让整轮失败
        import tempfile as _tf
        written = os.path.join(_tf.gettempdir(), "free-model-market-dashboard.html")
        with open(written, "w", encoding="utf-8") as f:
            f.write(page)
        print(f"[WARN] 目标目录不可写（{e}），已改写到临时目录")

    n = len(cat.get("providers", []) or [])
    print(f"[OK] 仪表盘已生成 → {written}")
    print(f"     记录 {n} 条 · 商品 {len(prod.get('products', []) or [])} 个 · 外部信号 {'有' if sig.get('ok') else '无'} · {len(page)} 字节")


# —— 单文件模板（内联 CSS/JS/SVG，无 CDN）——
PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>免费模型超市 · 货架仪表盘</title>
<style>
:root{
  --bg:#f6f8fb; --panel:#ffffff; --ink:#0f172a; --muted:#64748b; --line:#e2e8f0;
  --brand:#2563eb; --green:#16a34a; --amber:#d97706; --gray:#94a3b8; --violet:#7c3aed;
}
*{box-sizing:border-box}
body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;background:var(--bg);color:var(--ink);font-size:14px;line-height:1.55}
.wrap{max-width:1180px;margin:0 auto;padding:28px 20px 56px}
header.top{display:flex;flex-wrap:wrap;align-items:flex-end;justify-content:space-between;gap:12px;margin-bottom:20px}
h1{font-size:26px;margin:0;letter-spacing:.3px}
h1 small{display:block;font-size:13px;font-weight:400;color:var(--muted);margin-top:6px}
.stamp{font-size:12px;color:var(--muted);text-align:right}
.kpis{display:grid;grid-template-columns:repeat(6,1fr);gap:12px;margin:18px 0}
.kpi{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.kpi b{display:block;font-size:24px;line-height:1.1}
.kpi span{font-size:12px;color:var(--muted)}
.kpi.small{display:inline-flex;align-items:baseline;gap:8px;padding:8px 12px;border-radius:10px}
.kpi.small b{font-size:18px;display:inline}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:18px 20px;margin:16px 0;box-shadow:0 1px 2px rgba(15,23,42,.03)}
.card h2{font-size:16px;margin:0 0 12px}
.bar{display:flex;height:18px;border-radius:9px;overflow:hidden;background:#eef2f7;margin:6px 0 10px}
.seg{display:block;height:100%}
.legend{display:flex;flex-wrap:wrap;gap:14px;font-size:12px;color:var(--muted)}
.legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px;vertical-align:-1px}
.toolbar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:12px}
.toolbar input{flex:1;min-width:200px;padding:9px 12px;border:1px solid var(--line);border-radius:10px;font-size:13px;background:#fff;color:var(--ink)}
.btn{border:1px solid var(--line);background:#fff;color:var(--ink);padding:8px 12px;border-radius:10px;font-size:12.5px;cursor:pointer}
.btn.active{background:var(--brand);border-color:var(--brand);color:#fff}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:9px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{position:sticky;top:0;background:#f8fafc;font-size:12px;color:var(--muted);font-weight:600;z-index:1}
td.num{color:var(--muted);width:40px}
td.name{font-weight:600;min-width:190px}
td.q{color:#334155;max-width:420px}
td.host{color:var(--muted);font-family:ui-monospace,Consolas,monospace;font-size:12px}
.pill{display:inline-block;padding:2px 9px;border-radius:999px;font-size:11.5px;border:1px solid transparent;white-space:nowrap}
.st-active{background:#dcfce7;color:#166534}
.st-degraded{background:#fef3c7;color:#92400e}
.st-expired{background:#e2e8f0;color:#475569}
.st-unverified{background:#ede9fe;color:#5b21b6}
.st-unknown{background:#f1f5f9;color:#475569}
.sec-perm{background:#e0f2fe;color:#075985}
.sec-trial{background:#f1f5f9;color:#334155}
.sec-expired{background:#f1f5f9;color:#64748b}
.sec-other{background:#f8fafc;color:#64748b}
.product{border-left:4px solid var(--brand)}
.ph{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:6px}
.badge{background:#dbeafe;color:#1e40af;font-size:11px;padding:2px 8px;border-radius:999px}
.ph h2{margin:0;font-size:18px}
.tagline{color:var(--muted);font-size:12.5px}
.meta{color:var(--muted);font-size:12.5px;margin:4px 0 10px}
.mech{margin:0 0 12px;padding-left:18px;color:#334155}
.mech li{margin:4px 0}
.scope{display:grid;grid-template-columns:1fr 1fr;gap:10px;font-size:12.5px}
.scope .good{background:#f0fdf4;border:1px solid #bbf7d0;border-radius:10px;padding:8px 10px;color:#166534}
.scope .lim{background:#fff7ed;border:1px solid #fed7aa;border-radius:10px;padding:8px 10px;color:#9a3412}
.sigrow{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:4px 0 12px}
.chip{background:#eff6ff;color:#1e40af;border:1px solid #bfdbfe;border-radius:8px;padding:3px 9px;font-size:12px}
.chip.dead{background:#f8fafc;color:#475569;border-color:#e2e8f0}
.chiplabel{font-size:12px;color:var(--muted);margin-top:6px}
.muted{color:var(--muted)}
footer{margin-top:22px;font-size:12px;color:var(--muted)}
@media (max-width:900px){.kpis{grid-template-columns:repeat(3,1fr)}.scope{grid-template-columns:1fr}td.q{max-width:220px}}
@media (max-width:560px){.kpis{grid-template-columns:repeat(2,1fr)}h1{font-size:21px}}
</style>
</head>
<body>
<div class="wrap">
  <header class="top">
    <h1>免费模型超市 · 货架仪表盘<small>免费大模型 API 渠道 · 额度 / 限速 / 状态 / 端点</small></h1>
    <div class="stamp">数据快照 __SNAPSHOT__<br>生成于 __GENERATED__</div>
  </header>

  <div class="kpis">
    <div class="kpi"><b>__TOTAL__</b><span>渠道记录</span></div>
    <div class="kpi"><b>__VENDORS__</b><span>厂商（去重）</span></div>
    <div class="kpi"><b>__PERM__</b><span>永久免费</span></div>
    <div class="kpi"><b>__TRIAL__</b><span>试用额度</span></div>
    <div class="kpi"><b>__EXPIRED_SEC__</b><span>已停服追溯</span></div>
    <div class="kpi"><b>__ACTIVE__</b><span>active 可用</span></div>
  </div>

  <section class="card">
    <h2>状态分布</h2>
    <div class="bar">__BAR__</div>
    <div class="legend">
      <span><i style="background:#16a34a"></i>active __ACTIVE__</span>
      <span><i style="background:#d97706"></i>degraded __DEGRADED__</span>
      <span><i style="background:#7c3aed"></i>unverified __UNVERIFIED__</span>
      <span><i style="background:#94a3b8"></i>expired __EXPIRED_SEC__</span>
    </div>
  </section>

  <section class="card">
    <h2>渠道明细</h2>
    <div class="toolbar">
      <input id="q" type="search" placeholder="搜索名称 / 额度 / 域名…">
      <button class="btn active" data-f="all">全部</button>
      <button class="btn" data-f="active">active</button>
      <button class="btn" data-f="degraded">degraded</button>
      <button class="btn" data-f="expired">expired</button>
      <button class="btn" data-f="unverified">unverified</button>
      <span class="muted" id="cnt"></span>
    </div>
    <table id="tbl">
      <thead><tr><th>#</th><th>名称</th><th>分区</th><th>状态</th><th>额度 / 说明</th><th>端点</th></tr></thead>
      <tbody>__ROWS__</tbody>
    </table>
  </section>

  __PRODUCT__

  <section class="card">
    <h2>外部信源交叉验证（只读信号）</h2>
    __SIGNALS__
  </section>

  <footer>免费额度随时可能调整，正式采用前请点击来源链接复核。外部信号仅作提示，未改动权威数据源。</footer>
</div>
<script>
(function(){
  var q=document.getElementById('q'), tbl=document.getElementById('tbl'),
      rows=[].slice.call(tbl.querySelectorAll('tbody tr')),
      btns=[].slice.call(document.querySelectorAll('.btn')), cnt=document.getElementById('cnt'),
      filter='all';
  function apply(){
    var kw=(q.value||'').trim().toLowerCase(), shown=0;
    rows.forEach(function(r){
      var okF=(filter==='all'||r.getAttribute('data-status')===filter);
      var okK=!kw||r.textContent.toLowerCase().indexOf(kw)>-1;
      var ok=okF&&okK; r.style.display=ok?'':'none'; if(ok)shown++;
    });
    cnt.textContent='显示 '+shown+' / '+rows.length;
  }
  q.addEventListener('input',apply);
  btns.forEach(function(b){b.addEventListener('click',function(){
    btns.forEach(function(x){x.classList.remove('active')});
    b.classList.add('active'); filter=b.getAttribute('data-f'); apply();
  })});
  apply();
})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
