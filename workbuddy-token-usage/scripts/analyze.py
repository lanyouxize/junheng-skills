#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WorkBuddy Token Usage Analyzer
解析 ~/.workbuddy/traces/*/trace_*.json，统计 AI 调用的 Token 消耗与成本。
纯本地只读，不联网、不写 traces、不触碰任何凭证。

用法示例:
  python3 analyze.py --range yesterday
  python3 analyze.py --range last-7d --report html,csv
  python3 analyze.py --from 2026-09-01 --to 2026-09-03 --provider deepseek
  python3 analyze.py --range this-month --top 15 --dim agent,worker
"""
import json
import glob
import os
import sys
import argparse
from collections import defaultdict
from datetime import datetime, timezone, timedelta

# ---------- 基础配置 ----------
LOCAL_TZ = timezone(timedelta(hours=8))  # 本地时区 Asia/Shanghai (UTC+8)
UTC = timezone.utc
BASE = os.path.expanduser("~/.workbuddy/traces")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PRICES_PATH = os.path.join(SCRIPT_DIR, "..", "references", "prices.json")
SKILL_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
REPORT_DIR = os.path.join(SKILL_ROOT, "reports")


# ---------- 工具 ----------
def fmt(n):
    try:
        return f"{int(round(n)):,}"
    except Exception:
        return str(n)


def money(m):
    return f"¥{m:,.2f}"


def parse_ts(s):
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    d = datetime.fromisoformat(s)
    if d.tzinfo is None:
        d = d.replace(tzinfo=UTC)
    return d


def load_prices():
    with open(PRICES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------- 范围解析 ----------
def compute_range(args):
    now = datetime.now(LOCAL_TZ)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    # 显式日期优先于 --range 预设
    if args.frm or args.to:
        s = e = None
        if args.frm:
            s = datetime.strptime(args.frm, "%Y-%m-%d").replace(tzinfo=LOCAL_TZ)
        if args.to:
            e = datetime.strptime(args.to, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59, microsecond=0, tzinfo=LOCAL_TZ
            )
        if s is None:
            s = today_start - timedelta(days=1)
        if e is None:
            e = now
        return s, e
    if args.range == "today":
        return today_start, now
    if args.range == "yesterday":
        return today_start - timedelta(days=1), today_start
    if args.range == "last-7d":
        return today_start - timedelta(days=6), now
    if args.range == "last-30d":
        return today_start - timedelta(days=29), now
    if args.range == "this-week":
        # 周一为一周起点
        monday = today_start - timedelta(days=today_start.weekday())
        return monday, now
    if args.range == "this-month":
        first = today_start.replace(day=1)
        return first, now
    if args.range == "all":
        return None, now
    # 缺省: 昨天
    return today_start - timedelta(days=1), today_start


# ---------- trace 解析 ----------
def session_record(trace):
    mi = trace.get("modelInfo") or {}
    tt = trace.get("totalTokens")
    if isinstance(tt, dict):
        inp = tt.get("totalInputTokens") or mi.get("totalInputTokens") or 0
        out = tt.get("totalOutputTokens") or mi.get("totalOutputTokens") or 0
        cache = tt.get("totalCachedTokens") or mi.get("totalCachedTokens") or 0
    else:
        inp = mi.get("totalInputTokens") or 0
        out = mi.get("totalOutputTokens") or 0
        cache = mi.get("totalCachedTokens") or 0
    return {
        "startedAt": parse_ts(trace.get("startedAt")),
        "endedAt": parse_ts(trace.get("endedAt")),
        "agentName": trace.get("agentName") or "(unknown)",
        "workerHostname": trace.get("workerHostname") or "(unknown)",
        "workerPid": trace.get("workerPid"),
        "sessionId": trace.get("sessionId"),
        "name": trace.get("name"),
        "status": trace.get("status"),
        "input": inp,
        "output": out,
        "cache": cache,
        "callCount": mi.get("callCount") or 0,
        "models": ",".join(mi.get("models") or []) or "(unknown)",
        "total": inp + out,
    }


def collect_sessions(start_local, end_local):
    start_utc = start_local.astimezone(UTC) if start_local else None
    end_utc = end_local.astimezone(UTC)
    rows = []
    for fp in glob.glob(os.path.join(BASE, "*", "trace_*.json")):
        try:
            with open(fp, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            continue
        t = data.get("trace") if isinstance(data, dict) else None
        if not isinstance(t, dict):
            continue
        rec = session_record(t)
        st = rec["startedAt"]
        if st is None:
            continue
        if start_utc and st < start_utc:
            continue
        if st >= end_utc:
            continue
        if rec["input"] == 0 and rec["output"] == 0:
            continue
        rows.append(rec)
    rows.sort(key=lambda r: r["startedAt"])
    return rows


# ---------- 脱敏 ----------
def build_alias_map(rows):
    """workerHostname -> worker-N 的稳定映射（按出现顺序）。"""
    alias = {}
    seq = 0
    for r in rows:
        wh = r.get("workerHostname")
        if wh and wh not in alias:
            seq += 1
            alias[wh] = f"worker-{seq}"
    return alias


def apply_anonymize(rows, alias):
    """就地脱敏：workerHostname 泛化、sessionId 置空。"""
    for r in rows:
        r["workerHostname"] = alias.get(r.get("workerHostname"), "(unknown)")
        r["sessionId"] = None
    return rows


# ---------- 高峰/空闲拆分 ----------
def peak_idle_frac(start, end, peak_intervals):
    if not start or not end or end <= start:
        return 0.0, 1.0
    day = start.astimezone(LOCAL_TZ)
    midnight = datetime(day.year, day.month, day.day, tzinfo=LOCAL_TZ)
    s = (start.astimezone(LOCAL_TZ) - midnight)
    e = (end.astimezone(LOCAL_TZ) - midnight)
    peak = 0.0
    for a, b in peak_intervals:
        lo = max(s, timedelta(hours=a))
        hi = min(e, timedelta(hours=b))
        if hi > lo:
            peak += (hi - lo).total_seconds()
    total = (e - s).total_seconds()
    if total <= 0:
        return 0.0, 1.0
    return peak / total, 1 - peak / total


def session_cost(rec, model_rates, peak_intervals):
    pf, _ = peak_idle_frac(rec["startedAt"], rec["endedAt"], peak_intervals)
    cached = rec["cache"]
    miss = max(0, rec["input"] - cached)
    out = rec["output"]
    r = model_rates
    c = (cached * pf) * r["input_cached"]["peak"] + (cached * (1 - pf)) * r["input_cached"]["idle"]
    c += (miss * pf) * r["input_miss"]["peak"] + (miss * (1 - pf)) * r["input_miss"]["idle"]
    c += (out * pf) * r["output"]["peak"] + (out * (1 - pf)) * r["output"]["idle"]
    return c / 1e6, pf


# ---------- 聚合 ----------
def aggregate(rows, provider_cfg):
    peak_intervals = provider_cfg["peak_hours"]
    models = provider_cfg["models"]
    out = {
        "sessions": len(rows),
        "calls": sum(r["callCount"] for r in rows),
        "input": sum(r["input"] for r in rows),
        "output": sum(r["output"] for r in rows),
        "cache": sum(r["cache"] for r in rows),
        "total": sum(r["total"] for r in rows),
        "per_model": defaultdict(lambda: {"input": 0, "output": 0, "cache": 0, "total": 0, "calls": 0}),
        "per_agent": defaultdict(lambda: {"input": 0, "output": 0, "cache": 0, "total": 0}),
        "per_worker": defaultdict(lambda: {"input": 0, "output": 0, "cache": 0, "total": 0}),
        "by_day": defaultdict(lambda: {"input": 0, "output": 0, "cache": 0, "total": 0}),
        "by_hour": defaultdict(lambda: 0),
        "cost": {},
    }
    for r in rows:
        pm = out["per_model"][r["models"]]
        pm["input"] += r["input"]; pm["output"] += r["output"]
        pm["cache"] += r["cache"]; pm["total"] += r["total"]; pm["calls"] += r["callCount"]
        pa = out["per_agent"][r["agentName"]]
        pa["input"] += r["input"]; pa["output"] += r["output"]
        pa["cache"] += r["cache"]; pa["total"] += r["total"]
        pw = out["per_worker"][r["workerHostname"]]
        pw["input"] += r["input"]; pw["output"] += r["output"]
        pw["cache"] += r["cache"]; pw["total"] += r["total"]
        d = r["startedAt"].astimezone(LOCAL_TZ).strftime("%Y-%m-%d")
        bd = out["by_day"][d]
        bd["input"] += r["input"]; bd["output"] += r["output"]
        bd["cache"] += r["cache"]; bd["total"] += r["total"]
        h = r["startedAt"].astimezone(LOCAL_TZ).hour
        out["by_hour"][h] += r["total"]
        # 成本
        for mk, mr in models.items():
            c, _ = session_cost(r, mr, peak_intervals)
            out["cost"].setdefault(mk, 0.0)
            out["cost"][mk] += c
    return out


# ---------- SVG 图表 ----------
def svg_line_chart(series, width=720, height=240, color="#4f8cff"):
    """series: list of (label, value)"""
    if not series:
        return ""
    vals = [v for _, v in series]
    mx = max(vals) if max(vals) > 0 else 1
    n = len(series)
    pad_l, pad_r, pad_t, pad_b = 50, 20, 20, 40
    w = width - pad_l - pad_r
    h = height - pad_t - pad_b
    pts = []
    for i, (lab, v) in enumerate(series):
        x = pad_l + (w * i / max(1, n - 1)) if n > 1 else pad_l + w / 2
        y = pad_t + h - (h * v / mx)
        pts.append((x, y, lab, v))
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y, _, _ in pts)
    grid = ""
    for g in range(0, 5):
        gy = pad_t + h - (h * g / 4)
        grid += f'<line x1="{pad_l}" y1="{gy:.1f}" x2="{pad_l+w}" y2="{gy:.1f}" stroke="#eaeaea"/>'
        grid += f'<text x="{pad_l-8}" y="{gy+4:.1f}" font-size="10" fill="#999" text-anchor="end">{fmt(mx*g/4)}</text>'
    dots = ""
    labels = ""
    for i, (x, y, lab, v) in enumerate(pts):
        dots += f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{color}"/>'
        if n <= 16 or i % 2 == 0:
            labels += f'<text x="{x:.1f}" y="{pad_t+h+16:.1f}" font-size="9" fill="#999" text-anchor="middle">{lab[5:] if len(lab)>5 else lab}</text>'
    return (f'<svg viewBox="0 0 {width} {height}" width="100%" preserveAspectRatio="xMidYMid meet">'
            f'{grid}<polyline points="{poly}" fill="none" stroke="{color}" stroke-width="2"/>{dots}{labels}</svg>')


def svg_bar_v(values, labels, width=720, height=240, color="#4f8cff"):
    if not values:
        return ""
    mx = max(values) if max(values) > 0 else 1
    n = len(values)
    pad_l, pad_r, pad_t, pad_b = 50, 20, 20, 50
    w = width - pad_l - pad_r
    h = height - pad_t - pad_b
    bw = w / n * 0.6
    gap = w / n
    grid = ""
    for g in range(0, 5):
        gy = pad_t + h - (h * g / 4)
        grid += f'<line x1="{pad_l}" y1="{gy:.1f}" x2="{pad_l+w}" y2="{gy:.1f}" stroke="#eaeaea"/>'
        grid += f'<text x="{pad_l-8}" y="{gy+4:.1f}" font-size="10" fill="#999" text-anchor="end">{fmt(mx*g/4)}</text>'
    bars = ""
    for i, (v, lab) in enumerate(zip(values, labels)):
        x = pad_l + gap * i + (gap - bw) / 2
        bh = h * v / mx
        y = pad_t + h - bh
        bars += f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{bh:.1f}" fill="{color}" rx="3"/>'
        bars += f'<text x="{x+bw/2:.1f}" y="{y-4:.1f}" font-size="9" fill="#666" text-anchor="middle">{fmt(v)}</text>'
        bars += f'<text x="{x+bw/2:.1f}" y="{pad_t+h+14:.1f}" font-size="9" fill="#999" text-anchor="middle">{lab}</text>'
    return (f'<svg viewBox="0 0 {width} {height}" width="100%" preserveAspectRatio="xMidYMid meet">'
            f'{grid}{bars}</svg>')


def svg_donut(percent, size=160):
    r = size / 2 - 14
    c = size / 2
    circ = 2 * 3.14159 * r
    dash = circ * percent / 100
    return (f'<svg viewBox="0 0 {size} {size}" width="{size}" height="{size}">'
            f'<circle cx="{c}" cy="{c}" r="{r}" fill="none" stroke="#eee" stroke-width="16"/>'
            f'<circle cx="{c}" cy="{c}" r="{r}" fill="none" stroke="#3aa675" stroke-width="16" '
            f'stroke-dasharray="{dash:.1f} {circ:.1f}" stroke-dashoffset="0" transform="rotate(-90 {c} {c})"/>'
            f'<text x="{c}" y="{c-4:.1f}" font-size="22" fill="#333" text-anchor="middle" font-weight="bold">{percent:.1f}%</text>'
            f'<text x="{c}" y="{c+16:.1f}" font-size="11" fill="#999" text-anchor="middle">缓存命中</text></svg>')


# ---------- HTML 报表 ----------
CSS = """
* { box-sizing: border-box; }
body { font-family: -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
  margin:0; background:#f6f7f9; color:#222; }
.wrap { max-width:1000px; margin:0 auto; padding:28px 20px 60px; }
h1 { font-size:22px; margin:0 0 4px; }
.sub { color:#888; font-size:13px; margin-bottom:20px; }
.cards { display:flex; flex-wrap:wrap; gap:14px; margin-bottom:24px; }
.card { background:#fff; border:1px solid #ececec; border-radius:12px; padding:16px 18px; min-width:160px; flex:1; }
.card .k { font-size:12px; color:#999; }
.card .v { font-size:22px; font-weight:700; margin-top:6px; }
.card .v.small { font-size:18px; }
.section { background:#fff; border:1px solid #ececec; border-radius:12px; padding:18px 20px; margin-bottom:20px; }
.section h2 { font-size:16px; margin:0 0 12px; }
table { width:100%; border-collapse:collapse; font-size:13px; }
th,td { text-align:left; padding:8px 10px; border-bottom:1px solid #f0f0f0; }
th { color:#999; font-weight:600; }
td.num,th.num { text-align:right; font-variant-numeric:tabular-nums; }
.row2 { display:flex; gap:20px; flex-wrap:wrap; }
.row2 > div { flex:1; min-width:300px; }
.legend { font-size:12px; color:#999; margin-top:6px; }
.tag { display:inline-block; background:#eef3ff; color:#3a6; border-radius:6px; padding:1px 7px; font-size:11px; }
"""


HTML_TEMPLATE = r"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>WorkBuddy Token 消耗报表</title>
<style>
* { box-sizing: border-box; }
body { font-family: -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
  margin:0; background:#f6f7f9; color:#222; }
.wrap { max-width:1000px; margin:0 auto; padding:28px 20px 60px; }
h1 { font-size:22px; margin:0 0 4px; }
.sub { color:#888; font-size:13px; margin-bottom:20px; }
.cards { display:flex; flex-wrap:wrap; gap:14px; margin-bottom:24px; }
.card { background:#fff; border:1px solid #ececec; border-radius:12px; padding:16px 18px; min-width:160px; flex:1; }
.card .k { font-size:12px; color:#999; }
.card .v { font-size:22px; font-weight:700; margin-top:6px; }
.card .v.small { font-size:18px; }
.section { background:#fff; border:1px solid #ececec; border-radius:12px; padding:18px 20px; margin-bottom:20px; }
.section h2 { font-size:16px; margin:0 0 12px; }
table { width:100%; border-collapse:collapse; font-size:13px; }
th,td { text-align:left; padding:8px 10px; border-bottom:1px solid #f0f0f0; }
th { color:#999; font-weight:600; }
td.num,th.num { text-align:right; font-variant-numeric:tabular-nums; }
.row2 { display:flex; gap:20px; flex-wrap:wrap; }
.row2 > div { flex:1; min-width:300px; }
.legend { font-size:12px; color:#999; margin-top:6px; }
.filterbar { background:#fff; border:1px solid #d7e3ff; border-radius:12px; padding:16px 20px; margin-bottom:20px; }
.fline { display:flex; flex-wrap:wrap; gap:18px; align-items:flex-end; margin-bottom:12px; }
.fline label { font-size:13px; color:#555; }
.fgrp { margin-right:18px; }
.gl { display:block; font-size:12px; color:#999; margin-bottom:4px; }
.checks { display:flex; flex-wrap:wrap; gap:6px 12px; }
.chk { font-size:12px; color:#444; }
input[type=date],select { padding:5px 8px; border:1px solid #ccc; border-radius:8px; font-size:13px; }
</style></head>
<body><div class="wrap">
<h1>WorkBuddy Token 消耗分析</h1>
<div class="sub" id="metaSub"></div>

<div class="filterbar">
  <div class="fline">
    <label>开始 <input type="date" id="fStart"></label>
    <label>结束 <input type="date" id="fEnd"></label>
    <label>Top-N
      <select id="fTopn"><option>5</option><option selected>10</option><option>20</option></select>
    </label>
  </div>
  <div class="fline">
    <div class="fgrp"><span class="gl">模型</span><div id="fModels" class="checks"></div></div>
    <div class="fgrp"><span class="gl">Agent</span><div id="fAgents" class="checks"></div></div>
    <div class="fgrp"><span class="gl">Worker</span><div id="fWorkers" class="checks"></div></div>
  </div>
  <div class="sub" id="rangeLabel" style="margin-bottom:0;"></div>
</div>

<div class="cards" id="kpi"></div>

<div class="section"><h2>总览</h2>
<div class="row2"><div id="ov"></div><div style="display:flex;align-items:center;justify-content:center;" id="donut"></div></div></div>

<div class="section"><h2>成本换算（DeepSeek 官方价，含高峰/空闲混合）</h2><div id="cost"></div></div>

<div class="section"><h2>按模型拆分</h2><div id="model"></div></div>

<div class="section"><h2>每日 Token 趋势</h2><div id="trend"></div><div class="legend">横轴为本地日期，纵轴为当日总 Token。</div></div>

<div class="section"><h2>时段分布（按本地小时）</h2><div id="hour"></div><div class="legend">看用量是否集中在高峰计费时段。</div></div>

<div class="section"><h2>Top 最贵会话</h2><div id="top"></div></div>

<div class="row2">
  <div class="section"><h2>按 Agent 拆分 (Top 10)</h2><div id="agent"></div></div>
  <div class="section"><h2>按 机器/Worker 拆分 (Top 10)</h2><div id="worker"></div></div>
</div>

<div class="sub" style="margin-top:30px;">本报告由 workbuddy-token-usage 技能本地生成，数据仅来自 ~/.workbuddy/traces，未上传任何信息。分享前请注意：报表可能含设备名与 sessionId，建议脱敏后外发（运行脚本加 --anonymize）。</div>
</div>

<script>
const DATA = __DATA__;
const fmt = n => Math.round(n).toLocaleString('en-US');
const money = m => '¥' + m.toFixed(2);
const $ = id => document.getElementById(id);

function svgLine(series){
  if(!series.length) return '';
  const W=720,H=240,pl=50,pr=20,pt=20,pb=40; const w=W-pl-pr,h=H-pt-pb;
  const mx=Math.max.apply(null,series.map(s=>s[1]))||1; const n=series.length;
  const pts=series.map((s,i)=>{const x=n>1?pl+w*i/(n-1):pl+w/2; const y=pt+h-h*s[1]/mx; return [x,y,s[0],s[1]];});
  let grid=''; for(let g=0;g<=4;g++){const gy=pt+h-h*g/4; grid+='<line x1="'+pl+'" y1="'+gy+'" x2="'+(pl+w)+'" y2="'+gy+'" stroke="#eaeaea"/><text x="'+(pl-8)+'" y="'+(gy+4)+'" font-size="10" fill="#999" text-anchor="end">'+fmt(mx*g/4)+'</text>';}
  const poly=pts.map(p=>p[0].toFixed(1)+','+p[1].toFixed(1)).join(' ');
  let dots='',labels='';
  pts.forEach((p,i)=>{dots+='<circle cx="'+p[0].toFixed(1)+'" cy="'+p[1].toFixed(1)+'" r="3" fill="#4f8cff"/>'; if(n<=16||i%2===0){const lab=p[2].length>5?p[2].slice(5):p[2]; labels+='<text x="'+p[0].toFixed(1)+'" y="'+(pt+h+16)+'" font-size="9" fill="#999" text-anchor="middle">'+lab+'</text>';}});
  return '<svg viewBox="0 0 '+W+' '+H+'" width="100%" preserveAspectRatio="xMidYMid meet">'+grid+'<polyline points="'+poly+'" fill="none" stroke="#4f8cff" stroke-width="2"/>'+dots+labels+'</svg>';
}
function svgBar(values,labels){
  if(!values.length) return '';
  const W=720,H=240,pl=50,pr=20,pt=20,pb=50; const w=W-pl-pr,h=H-pt-pb;
  const mx=Math.max.apply(null,values)||1; const n=values.length; const gap=w/n, bw=gap*0.6;
  let grid=''; for(let g=0;g<=4;g++){const gy=pt+h-h*g/4; grid+='<line x1="'+pl+'" y1="'+gy+'" x2="'+(pl+w)+'" y2="'+gy+'" stroke="#eaeaea"/><text x="'+(pl-8)+'" y="'+(gy+4)+'" font-size="10" fill="#999" text-anchor="end">'+fmt(mx*g/4)+'</text>';}
  let bars='';
  values.forEach((v,i)=>{const x=pl+gap*i+(gap-bw)/2; const bh=h*v/mx; const y=pt+h-bh; bars+='<rect x="'+x.toFixed(1)+'" y="'+y.toFixed(1)+'" width="'+bw.toFixed(1)+'" height="'+bh.toFixed(1)+'" fill="#4f8cff" rx="3"/><text x="'+(x+bw/2).toFixed(1)+'" y="'+(y-4).toFixed(1)+'" font-size="9" fill="#666" text-anchor="middle">'+fmt(v)+'</text><text x="'+(x+bw/2).toFixed(1)+'" y="'+(pt+h+14)+'" font-size="9" fill="#999" text-anchor="middle">'+labels[i]+'</text>';});
  return '<svg viewBox="0 0 '+W+' '+H+'" width="100%" preserveAspectRatio="xMidYMid meet">'+grid+bars+'</svg>';
}
function svgDonut(pct){
  const size=160,r=size/2-14,c=size/2,circ=2*Math.PI*r,dash=circ*pct/100;
  return '<svg viewBox="0 0 '+size+' '+size+'" width="'+size+'" height="'+size+'"><circle cx="'+c+'" cy="'+c+'" r="'+r+'" fill="none" stroke="#eee" stroke-width="16"/><circle cx="'+c+'" cy="'+c+'" r="'+r+'" fill="none" stroke="#3aa675" stroke-width="16" stroke-dasharray="'+dash.toFixed(1)+' '+circ.toFixed(1)+'" transform="rotate(-90 '+c+' '+c+')"/><text x="'+c+'" y="'+(c-4)+'" font-size="22" fill="#333" text-anchor="middle" font-weight="bold">'+pct.toFixed(1)+'%</text><text x="'+c+'" y="'+(c+16)+'" font-size="11" fill="#999" text-anchor="middle">缓存命中</text></svg>';
}
function uniq(arr){return Array.from(new Set(arr)).sort();}
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}

const MODELS = uniq(DATA.rows.map(r=>r.models));
const AGENTS = uniq(DATA.rows.map(r=>r.agentName));
const WORKERS = uniq(DATA.rows.map(r=>r.worker));
function fillChecks(id, vals){
  $(id).innerHTML = vals.map(v=>'<label class="chk"><input type="checkbox" data-grp="'+id+'" value="'+esc(v)+'" checked> '+esc(v)+'</label>').join('');
}
fillChecks('fModels', MODELS);
fillChecks('fAgents', AGENTS);
fillChecks('fWorkers', WORKERS);
$('fStart').value=DATA.defaultStart; $('fEnd').value=DATA.defaultEnd;
['fStart','fEnd'].forEach(id=>{$(id).min=DATA.minDate; $(id).max=DATA.maxDate;});
$('metaSub').textContent='内嵌数据窗口：最近 90 天（'+DATA.minDate+' ~ '+DATA.maxDate+'）｜ 生成：'+DATA.gen+' ｜ 时区 Asia/Shanghai (UTC+8)';
function getSel(id){return Array.from(document.querySelectorAll('input[data-grp="'+id+'"]:checked')).map(x=>x.value);}

function render(){
  const s=$('fStart').value, e=$('fEnd').value;
  const sm=new Set(getSel('fModels')), sa=new Set(getSel('fAgents')), sw=new Set(getSel('fWorkers'));
  const topN=parseInt($('fTopn').value,10);
  const rows=DATA.rows.filter(r=> r.dateLocal>=s && r.dateLocal<=e
     && (sm.size===0||sm.has(r.models))
     && (sa.size===0||sa.has(r.agentName))
     && (sw.size===0||sw.has(r.worker)));
  let sessions=rows.length, calls=0, input=0, output=0, cache=0, total=0;
  const cost={}; Object.keys(DATA.prices.models).forEach(k=>cost[k]=0);
  const perModel={}, perAgent={}, perWorker={}, byDay={}; const byHour=Array(24).fill(0);
  for(const r of rows){
    calls+=r.callCount; input+=r.input; output+=r.output; cache+=r.cache; total+=r.total;
    for(const k in DATA.prices.models){const m=DATA.prices.models[k];
      cost[k]+= (r.cache*(r.peakFrac*m.input_cached.peak+(1-r.peakFrac)*m.input_cached.idle)
        + Math.max(0,r.input-r.cache)*(r.peakFrac*m.input_miss.peak+(1-r.peakFrac)*m.input_miss.idle)
        + r.output*(r.peakFrac*m.output.peak+(1-r.peakFrac)*m.output.idle))/1e6;
    }
    perModel[r.models]=perModel[r.models]||{input:0,output:0,cache:0,total:0,calls:0};
    const pm=perModel[r.models]; pm.input+=r.input;pm.output+=r.output;pm.cache+=r.cache;pm.total+=r.total;pm.calls+=r.callCount;
    perAgent[r.agentName]=perAgent[r.agentName]||{total:0,cache:0}; perAgent[r.agentName].total+=r.total;perAgent[r.agentName].cache+=r.cache;
    perWorker[r.worker]=perWorker[r.worker]||{total:0,cache:0}; perWorker[r.worker].total+=r.total;perWorker[r.worker].cache+=r.cache;
    byDay[r.dateLocal]=byDay[r.dateLocal]||{total:0,cache:0}; byDay[r.dateLocal].total+=r.total;byDay[r.dateLocal].cache+=r.cache;
    byHour[r.hourLocal]+=r.total;
  }
  const hit= input? cache/input*100 : 0;
  let kpi='<div class="card"><div class="k">有效会话</div><div class="v">'+fmt(sessions)+'</div></div>'
    +'<div class="card"><div class="k">AI 调用次数</div><div class="v">'+fmt(calls)+'</div></div>'
    +'<div class="card"><div class="k">总 Token</div><div class="v">'+fmt(total)+'</div></div>';
  for(const k in DATA.prices.models){ kpi+='<div class="card"><div class="k">'+esc(DATA.prices.models[k].label)+' 估算</div><div class="v small">'+money(cost[k])+'</div></div>';}
  $('kpi').innerHTML=kpi;
  $('ov').innerHTML='<table><tr><th>指标</th><th class="num">数值</th></tr>'
    +'<tr><td>输入 Token</td><td class="num">'+fmt(input)+'</td></tr>'
    +'<tr><td>输出 Token</td><td class="num">'+fmt(output)+'</td></tr>'
    +'<tr><td>缓存命中 Token</td><td class="num">'+fmt(cache)+'</td></tr>'
    +'<tr><td>净新增(非缓存输入+输出)</td><td class="num">'+fmt(Math.max(0,input-cache)+output)+'</td></tr></table>'
    +'<div class="legend">缓存命中率 = 缓存命中 / 输入。当前 '+hit.toFixed(1)+'%。</div>';
  $('donut').innerHTML=svgDonut(hit);
  let cr=''; for(const k in DATA.prices.models){ cr+='<tr><td>'+esc(DATA.prices.models[k].label)+'</td><td class="num">'+money(cost[k])+'</td></tr>';}
  $('cost').innerHTML='<table><tr><th>模型</th><th class="num">估算费用(¥)</th></tr>'+cr+'</table><div class="legend">单价见 references/prices.json。高峰 09:00-12:00/14:00-18:00 按高峰价，其余空闲价。按各会话真实时段加权。</div>';
  let mr=''; Object.keys(perModel).sort((a,b)=>perModel[b].total-perModel[a].total).forEach(k=>{const m=perModel[k]; mr+='<tr><td>'+esc(k)+'</td><td class="num">'+fmt(m.total)+'</td><td class="num">'+fmt(m.input)+'</td><td class="num">'+fmt(m.output)+'</td><td class="num">'+fmt(m.cache)+'</td><td class="num">'+fmt(m.calls)+'</td></tr>';});
  $('model').innerHTML='<table><tr><th>模型</th><th class="num">总Token</th><th class="num">输入</th><th class="num">输出</th><th class="num">缓存</th><th class="num">调用</th></tr>'+mr+'</table>';
  const days=Object.keys(byDay).sort();
  $('trend').innerHTML=svgLine(days.map(d=>[d,byDay[d].total]));
  $('hour').innerHTML=svgBar(byHour, Array.from({length:24},(_,i)=>String(i)));
  const top=rows.slice().sort((a,b)=>b.total-a.total).slice(0,topN);
  let tr=''; top.forEach(r=>{tr+='<tr><td>'+r.dateLocal+' '+String(r.hourLocal).padStart(2,'0')+':00</td><td>'+esc(r.models)+'</td><td class="num">'+fmt(r.total)+'</td><td class="num">'+fmt(r.cache)+'</td><td class="num">'+fmt(r.callCount)+'</td><td>'+esc(r.agentName)+'</td></tr>';});
  $('top').innerHTML='<table><tr><th>日期</th><th>模型</th><th class="num">总Token</th><th class="num">缓存</th><th class="num">调用</th><th>Agent</th></tr>'+tr+'</table>';
  let ar=''; Object.keys(perAgent).sort((a,b)=>perAgent[b].total-perAgent[a].total).slice(0,10).forEach(k=>{const v=perAgent[k]; ar+='<tr><td>'+esc(k)+'</td><td class="num">'+fmt(v.total)+'</td><td class="num">'+fmt(v.cache)+'</td></tr>';});
  $('agent').innerHTML='<table><tr><th>Agent</th><th class="num">总Token</th><th class="num">缓存</th></tr>'+ar+'</table>';
  let wr=''; Object.keys(perWorker).sort((a,b)=>perWorker[b].total-perWorker[a].total).slice(0,10).forEach(k=>{const v=perWorker[k]; wr+='<tr><td>'+esc(k)+'</td><td class="num">'+fmt(v.total)+'</td><td class="num">'+fmt(v.cache)+'</td></tr>';});
  $('worker').innerHTML='<table><tr><th>Worker</th><th class="num">总Token</th><th class="num">缓存</th></tr>'+wr+'</table>';
  $('rangeLabel').textContent='当前筛选：'+s+' ~ '+e+' ｜ 命中 '+fmt(sessions)+' 个会话';
}
['fStart','fEnd','fTopn'].forEach(id=>$(id).addEventListener('change',render));
document.querySelectorAll('input[type=checkbox][data-grp]').forEach(cb=>cb.addEventListener('change',render));
render();
</script>
</body></html>"""


def embed_rows(full_rows, provider_cfg):
    """把会话明细转为 JSON 安全的精简结构，供前端交互筛选（内嵌近 90 天）。"""
    peak = provider_cfg.get("peak_hours", [])
    out = []
    for r in full_rows:
        st = r["startedAt"]
        et = r["endedAt"]
        if st is None:
            continue
        pf, _ = peak_idle_frac(st, et, peak)
        out.append({
            "dateLocal": st.astimezone(LOCAL_TZ).strftime("%Y-%m-%d"),
            "hourLocal": st.astimezone(LOCAL_TZ).hour,
            "agentName": r["agentName"] or "(unknown)",
            "worker": r["workerHostname"] or "(unknown)",
            "models": r["models"] or "(unknown)",
            "input": r["input"],
            "output": r["output"],
            "cache": r["cache"],
            "callCount": r["callCount"],
            "total": r["total"],
            "peakFrac": round(pf, 4),
        })
    return out


def build_html(full_rows, provider_cfg, default_start, default_end, min_date, max_date):
    embedded = embed_rows(full_rows, provider_cfg)
    models_embed = {}
    for k, v in provider_cfg["models"].items():
        models_embed[k] = {
            "label": v.get("label", k),
            "input_cached": v["input_cached"],
            "input_miss": v["input_miss"],
            "output": v["output"],
        }
    payload = {
        "gen": datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M"),
        "defaultStart": default_start,
        "defaultEnd": default_end,
        "minDate": min_date,
        "maxDate": max_date,
        "rows": embedded,
        "prices": {"peak_hours": provider_cfg.get("peak_hours", []), "models": models_embed},
    }
    return HTML_TEMPLATE.replace("__DATA__", json.dumps(payload, ensure_ascii=False).replace("</", "<\\/"))


# ---------- CSV ----------
def build_csv(meta, rows):
    lines = ["startedAt,endedAt,agentName,workerHostname,models,sessionId,callCount,inputTokens,outputTokens,cachedTokens,totalTokens"]
    for r in rows:
        s = r["startedAt"].astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S")
        e = r["endedAt"].astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S") if r["endedAt"] else ""
        lines.append(f"{s},{e},{r['agentName']},{r['workerHostname']},{r['models']},{r['sessionId'] or ''},{r['callCount']},{r['input']},{r['output']},{r['cache']},{r['total']}")
    return "\n".join(lines)


# ---------- 控制台摘要 ----------
def print_summary(meta, agg, provider_cfg):
    hit = (agg["cache"] / agg["input"] * 100) if agg["input"] else 0
    print("=" * 64)
    print(f"WorkBuddy Token 消耗分析  |  区间: {meta['range_label']}")
    print("=" * 64)
    print(f"有效会话:   {agg['sessions']}")
    print(f"AI 调用:    {fmt(agg['calls'])}")
    print(f"总 Token:   {fmt(agg['total'])}")
    print(f"  输入:     {fmt(agg['input'])}")
    print(f"  输出:     {fmt(agg['output'])}")
    print(f"  缓存命中: {fmt(agg['cache'])}  ({hit:.1f}%)")
    print("-" * 64)
    print("成本换算 (DeepSeek):")
    for mk, mr in provider_cfg["models"].items():
        c = agg["cost"].get(mk, 0.0)
        print(f"  {mr['label']:18s} {money(c)}")
    print("-" * 64)
    print("按模型:")
    for mk, m in sorted(agg["per_model"].items(), key=lambda x: -x[1]["total"]):
        print(f"  {mk:14s} 总={fmt(m['total']):>14}  输入={fmt(m['input']):>14}  输出={fmt(m['output']):>10}  缓存={fmt(m['cache']):>14}  调用={fmt(m['calls'])}")
    print("-" * 64)
    print(f"Top 3 会话:")
    for r in sorted(meta["rows"], key=lambda x: -x["total"])[:3]:
        ts = r["startedAt"].astimezone(LOCAL_TZ).strftime("%m-%d %H:%M")
        print(f"  {ts}  {r['models']:12s} 总={fmt(r['total']):>14}  调用={fmt(r['callCount'])}  {r['agentName']}")
    print("=" * 64)


# ---------- 主流程 ----------
def main():
    ap = argparse.ArgumentParser(description="WorkBuddy Token Usage Analyzer")
    ap.add_argument("--range", default="yesterday",
                    choices=["today", "yesterday", "last-7d", "last-30d", "this-week", "this-month", "all"],
                    help="时间范围预设")
    ap.add_argument("--from", dest="frm", help="起始日期 YYYY-MM-DD")
    ap.add_argument("--to", help="结束日期 YYYY-MM-DD")
    ap.add_argument("--provider", default="deepseek", help="价目表 provider (默认 deepseek)")
    ap.add_argument("--models", help="逗号分隔的模型 key，默认 provider 下全部")
    ap.add_argument("--report", default="html,csv", help="输出: html,csv,none (逗号分隔)")
    ap.add_argument("--out", help="输出目录，默认技能内 reports/")
    ap.add_argument("--top", type=int, default=10, help="Top-N 最贵会话")
    ap.add_argument("--dim", default="agent,worker", help="下钻维度: agent,worker,session")
    ap.add_argument("--anonymize", action="store_true",
                    help="脱敏：workerHostname 泛化为 worker-1/2/...，sessionId 置空（用于对外分享报表）")
    args = ap.parse_args()

    prices = load_prices()
    provider_cfg = prices["providers"].get(args.provider)
    if not provider_cfg:
        print(f"未找到 provider: {args.provider}", file=sys.stderr)
        sys.exit(1)
    # 过滤模型
    if args.models:
        keys = [m.strip() for m in args.models.split(",")]
        provider_cfg = dict(provider_cfg)
        provider_cfg["models"] = {k: v for k, v in provider_cfg["models"].items() if k in keys}

    start_local, end_local = compute_range(args)
    range_label = (f"{start_local.astimezone(LOCAL_TZ).strftime('%Y-%m-%d') if start_local else '最早'} ~ "
                   f"{end_local.astimezone(LOCAL_TZ).strftime('%Y-%m-%d %H:%M')}")
    rows = collect_sessions(start_local, end_local)
    if not rows:
        print(f"区间 {range_label} 内未找到有效 trace 记录。")
        return
    # 内嵌数据窗口（最近 90 天）+ 脱敏映射（保证子集与内嵌数据别名一致）
    embed_start = (datetime.now(LOCAL_TZ) - timedelta(days=90)).replace(hour=0, minute=0, second=0, microsecond=0)
    embed_end = datetime.now(LOCAL_TZ)
    alias = None
    full_rows = None
    if args.anonymize:
        full_rows = collect_sessions(embed_start, embed_end)
        alias = build_alias_map(full_rows)
        apply_anonymize(rows, alias)
    agg = aggregate(rows, provider_cfg)
    meta = {
        "range_label": range_label,
        "gen": datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M"),
        "rows": rows,
    }
    print_summary(meta, agg, provider_cfg)
    if args.anonymize:
        print("\n[脱敏] 已生效：workerHostname 泛化为 worker-N，sessionId 已置空。")

    out_dir = args.out or REPORT_DIR
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.now(LOCAL_TZ).strftime("%Y%m%d_%H%M%S")
    rl = args.range if not (args.frm or args.to) else "custom"
    written = []
    reps = [x.strip() for x in args.report.split(",")]
    if "html" in reps:
        # 内嵌数据窗口：最近 90 天（默认上限），供前端交互筛选
        if full_rows is None:
            full_rows = collect_sessions(embed_start, embed_end)
        elif alias:
            apply_anonymize(full_rows, alias)
        min_date = embed_start.strftime("%Y-%m-%d")
        max_date = embed_end.strftime("%Y-%m-%d")
        def_start = (start_local.strftime("%Y-%m-%d") if start_local else min_date)
        def_end = end_local.strftime("%Y-%m-%d")
        html = build_html(full_rows, provider_cfg, def_start, def_end, min_date, max_date)
        p = os.path.join(out_dir, f"token_report_{rl}_{stamp}.html")
        with open(p, "w", encoding="utf-8") as f:
            f.write(html)
        written.append(p)
    if "csv" in reps:
        csv = build_csv(meta, rows)
        p = os.path.join(out_dir, f"token_detail_{rl}_{stamp}.csv")
        with open(p, "w", encoding="utf-8") as f:
            f.write(csv)
        written.append(p)
    if written:
        print("\n生成的文件:")
        for p in written:
            print(f"  {p}")


if __name__ == "__main__":
    main()
