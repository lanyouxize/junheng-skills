#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WorkBuddy Token 使用统计
========================
扫描本地会话转录（默认 ~/.codebuddy/projects/**/*.jsonl），
聚合 Token 消耗并输出：
  1) 终端中文摘要（默认）
  2) 自包含 HTML 可视化面板（--html <path>）
  3) 结构化 JSON（--json <path>）
  4) 实时面板服务（--serve [PORT]，每 30 秒自动刷新，可作快捷入口收藏）

仅依赖 Python 标准库。
"""

import argparse
import datetime as dt
import glob
import json
import os
import sys

# ---------------------------------------------------------------------------
# 数据采集
# ---------------------------------------------------------------------------

DEFAULT_DATA_DIR = os.path.expanduser("~/.codebuddy/projects")
DEFAULT_PORT = 8642


def extract_record(rec):
    """从一条转录记录中提取 usage 记录。

    usage_dict 统一为: {ts, model, input, output, total, cache_read, reasoning, requests, session}
    同一条记录的 providerData.usage 与 message.usage 为重复数据，只计一次。
    无有效 usage 时返回 None。
    """
    if not isinstance(rec, dict):
        return None
    pd = rec.get("providerData") if isinstance(rec.get("providerData"), dict) else {}
    msg = rec.get("message") if isinstance(rec.get("message"), dict) else {}

    u = pd.get("usage") or msg.get("usage")
    if not isinstance(u, dict):
        return None

    input_toks = u.get("inputTokens", u.get("input_tokens", 0)) or 0
    output_toks = u.get("outputTokens", u.get("output_tokens", 0)) or 0
    total = u.get("totalTokens", u.get("total_tokens", 0)) or 0
    if total == 0:
        total = input_toks + output_toks
    if total <= 0:
        return None

    cache_read = u.get("cache_read_input_tokens", 0) or 0
    if not cache_read:
        details = u.get("inputTokensDetails") or []
        if isinstance(details, list) and details:
            cache_read = sum(d.get("cached_tokens", 0) for d in details if isinstance(d, dict))

    reasoning = u.get("reasoning_tokens", 0) or 0
    if not reasoning:
        details = u.get("outputTokensDetails") or []
        if isinstance(details, list) and details:
            reasoning = sum(d.get("reasoning_tokens", 0) for d in details if isinstance(d, dict))

    model = pd.get("model") or pd.get("requestModelName") or msg.get("model") or "unknown"
    requests = u.get("requests", 1) or 1

    return {
        "ts": rec.get("timestamp"),
        "model": model,
        "input": input_toks,
        "output": output_toks,
        "total": total,
        "cache_read": cache_read,
        "reasoning": reasoning,
        "requests": requests,
        "session": rec.get("sessionId") or "",
    }


def iter_records(path):
    """逐行流式读取转录文件，yield usage 记录（解析失败的行跳过）。"""
    try:
        f = open(path, "r", encoding="utf-8", errors="replace")
    except OSError:
        return
    with f:
        for line in f:
            line = line.strip()
            if not line or '"usage"' not in line:
                continue  # 快速预过滤，避免全量 json.loads
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            r = extract_record(rec)
            if r:
                yield r


def discover_transcripts(data_dir):
    """发现所有会话转录文件（projects/<项目>/<sessionId>.jsonl）。"""
    pattern = os.path.join(data_dir, "**", "*.jsonl")
    return sorted(glob.glob(pattern, recursive=True))


# ---------------------------------------------------------------------------
# 聚合
# ---------------------------------------------------------------------------

def compute_stats(data_dir, tz_name=None):
    """扫描全部转录并聚合。返回统计 dict。"""
    tz = None
    if tz_name:
        try:
            import zoneinfo
            tz = zoneinfo.ZoneInfo(tz_name)
        except Exception:
            print(f"[warn] 无法识别时区 {tz_name}，使用系统本地时区", file=sys.stderr)

    def local_date(ts_ms):
        if ts_ms is None:
            return None
        try:
            return dt.datetime.fromtimestamp(ts_ms / 1000.0, tz).date()
        except (OSError, OverflowError, ValueError):
            return None

    files = discover_transcripts(data_dir)
    stats = {
        "files_scanned": len(files),
        "total_tokens": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "reasoning_tokens": 0,
        "requests": 0,
        "per_day": {},          # date -> {total, requests, models: {model: tokens}}
        "per_model": {},        # model -> {total, requests}
        "per_session": {},      # file -> {min_ts, max_ts, total, duration_sec}
    }

    for path in files:
        fmin, fmax, ftotal = None, None, 0
        finput, fcache, freq = 0, 0, 0
        for r in iter_records(path):
            ts = r["ts"]
            if ts is not None:
                fmin = ts if fmin is None else min(fmin, ts)
                fmax = ts if fmax is None else max(fmax, ts)
            stats["total_tokens"] += r["total"]
            stats["input_tokens"] += r["input"]
            stats["output_tokens"] += r["output"]
            stats["cache_read_tokens"] += r["cache_read"]
            stats["reasoning_tokens"] += r["reasoning"]
            stats["requests"] += r["requests"]

            d = local_date(r["ts"])
            if d is not None:
                day = stats["per_day"].setdefault(d.isoformat(), {"total": 0, "requests": 0, "models": {}})
                day["total"] += r["total"]
                day["requests"] += r["requests"]
                if r["model"]:
                    day["models"][r["model"]] = day["models"].get(r["model"], 0) + r["total"]

            m = stats["per_model"].setdefault(r["model"], {"total": 0, "requests": 0})
            m["total"] += r["total"]
            m["requests"] += r["requests"]

            ftotal += r["total"]
            finput += r["input"]
            fcache += r["cache_read"]
            freq += r["requests"]

        if ftotal > 0 and fmin and fmax:
            stats["per_session"][os.path.basename(path)] = {
                "min_ts": fmin, "max_ts": fmax, "total": ftotal,
                "input": finput, "cache_read": fcache, "requests": freq,
                "duration_sec": max(0, (fmax - fmin) / 1000.0),
            }

    # 峰值（单日最大）
    peak_day, peak_val = None, 0
    for d, v in stats["per_day"].items():
        if v["total"] > peak_val:
            peak_val, peak_day = v["total"], d

    # 连续天数
    active_days = sorted(dt.date.fromisoformat(d) for d in stats["per_day"] if stats["per_day"][d]["total"] > 0)
    day_set = set(active_days)

    def streak_from(anchor):
        cur, d = 0, anchor
        while d in day_set:
            cur += 1
            d -= dt.timedelta(days=1)
        return cur

    today = dt.date.today()
    if today in day_set:
        current_streak = streak_from(today)
    elif (today - dt.timedelta(days=1)) in day_set:
        current_streak = streak_from(today - dt.timedelta(days=1))
    else:
        current_streak = 0

    longest_streak, run, prev = 0, 0, None
    for d in active_days:
        run = run + 1 if (prev and (d - prev).days == 1) else 1
        longest_streak = max(longest_streak, run)
        prev = d

    longest_session = None
    if stats["per_session"]:
        best = max(stats["per_session"].items(), key=lambda kv: kv[1]["duration_sec"])
        longest_session = {"file": best[0], **best[1]}

    stats["peak_day"] = peak_day
    stats["peak_tokens"] = peak_val
    stats["current_streak"] = current_streak
    stats["longest_streak"] = longest_streak
    stats["longest_session"] = longest_session
    stats["active_days"] = [d.isoformat() for d in active_days]
    stats["session_count"] = len(stats["per_session"])

    # 识别当前活跃会话：sessions/*.json 中心跳最新的 interactive 会话；
    # 找不到（如自定义 --data-dir）则回退为最近有记录的转录文件
    current_sid = None
    sessions_dir = os.path.join(os.path.dirname(os.path.abspath(data_dir)), "sessions")
    best_hb = -1
    if os.path.isdir(sessions_dir):
        for p in glob.glob(os.path.join(sessions_dir, "*.json")):
            try:
                d = json.load(open(p))
            except Exception:
                continue
            if d.get("kind") != "interactive":
                continue
            hb = d.get("lastHeartbeat") or 0
            if hb > best_hb and d.get("sessionId"):
                best_hb, current_sid = hb, d["sessionId"]
    cur_file = f"{current_sid}.jsonl" if current_sid and f"{current_sid}.jsonl" in stats["per_session"] else None
    if cur_file is None and stats["per_session"]:
        cur_file = max(stats["per_session"].items(), key=lambda kv: kv[1]["max_ts"])[0]
    stats["current_session_file"] = cur_file
    return stats


# ---------------------------------------------------------------------------
# 格式化
# ---------------------------------------------------------------------------

def fmt_int(n):
    return f"{n:,}"


def fmt_tokens(n):
    """中文习惯的大数格式化。"""
    if n >= 1e8:
        v = n / 1e8
        return f"{v:.1f} 亿".replace(".0 亿", " 亿")
    if n >= 1e4:
        v = n / 1e4
        return f"{v:.1f} 万".replace(".0 万", " 万")
    return f"{n:,}"


def fmt_duration(seconds):
    if seconds is None or seconds <= 0:
        return "—"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h} 小时 {m} 分钟"
    if m > 0:
        return f"{m} 分钟"
    return f"{s} 秒"


def fmt_duration_compact(seconds):
    """面板卡片用：紧凑格式，避免溢出。"""
    if seconds is None or seconds <= 0:
        return "—"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}时{m:02d}分"
    if m > 0:
        return f"{m}分{s:02d}秒"
    return f"{s}秒"


# ---------------------------------------------------------------------------
# 输出：终端摘要
# ---------------------------------------------------------------------------

def print_summary(s):
    print("WorkBuddy Token 使用统计")
    print("=" * 46)
    print(f"累计 Token    : {fmt_tokens(s['total_tokens'])}  ({fmt_int(s['total_tokens'])})")
    print(f"  其中输入    : {fmt_tokens(s['input_tokens'])}（含缓存读取 {fmt_tokens(s['cache_read_tokens'])}）")
    print(f"  其中输出    : {fmt_tokens(s['output_tokens'])}（含推理 {fmt_tokens(s['reasoning_tokens'])}）")
    print(f"峰值(单日)    : {fmt_tokens(s['peak_tokens'])}" + (f"  ({s['peak_day']})" if s["peak_day"] else ""))
    print(f"最长会话时长  : {fmt_duration(s['longest_session']['duration_sec']) if s['longest_session'] else '—'}")
    print(f"当前连续天数  : {s['current_streak']} 天")
    print(f"最长连续天数  : {s['longest_streak']} 天")
    print(f"会话数        : {s['session_count']}  |  模型调用 {fmt_int(s['requests'])} 次  |  活跃天数 {len(s['active_days'])}")
    if s["per_model"]:
        print("-" * 46)
        print("模型用量（累计）:")
        models = sorted(s["per_model"].items(), key=lambda kv: -kv[1]["total"])
        for name, m in models:
            pct = (m["total"] / s["total_tokens"] * 100) if s["total_tokens"] else 0
            print(f"  {name:<28} {fmt_tokens(m['total']):>10}  {pct:5.1f}%  ({fmt_int(m['requests'])} 次)")
    print("-" * 46)
    print(f"数据来源: {s['files_scanned']} 个转录文件 @ {DEFAULT_DATA_DIR}")


# ---------------------------------------------------------------------------
# 输出：JSON
# ---------------------------------------------------------------------------

def dump_json(s, path):
    out = {k: v for k, v in s.items() if k not in ("per_day", "per_model", "per_session", "active_days")}
    out["active_days"] = s["active_days"]
    out["per_day"] = {d: v for d, v in sorted(s["per_day"].items())}
    out["per_model"] = s["per_model"]
    out["per_session"] = s["per_session"]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)


# ---------------------------------------------------------------------------
# 面板数据结构（静态 HTML 与实时服务共用）
# ---------------------------------------------------------------------------

def build_dashboard_data(s, tz_note="", live=False):
    today = dt.date.today()
    # 热力图范围：GitHub 式近 52 周（起点回退到周日）
    heat_start = today - dt.timedelta(days=363)
    heat_start -= dt.timedelta(days=(heat_start.weekday() + 1) % 7)  # 对齐到周日

    # 缓存命中率 = 缓存读取 / 输入 tokens
    cache_rate = round(s["cache_read_tokens"] / s["input_tokens"] * 100, 1) if s["input_tokens"] else 0.0

    # 当前会话
    cur = None
    cs_file = s.get("current_session_file")
    if cs_file and cs_file in s["per_session"]:
        c = s["per_session"][cs_file]
        cur = {
            "file": cs_file,
            "id": cs_file[:-6] if cs_file.endswith(".jsonl") else cs_file,
            "total": c["total"],
            "input": c.get("input", 0),
            "cacheRead": c.get("cache_read", 0),
            "requests": c.get("requests", 0),
            "cacheRate": round(c["cache_read"] / c["input"] * 100, 1) if c.get("input") else 0.0,
        }

    return {
        "totalTokens": s["total_tokens"],
        "inputTokens": s["input_tokens"],
        "outputTokens": s["output_tokens"],
        "cacheReadTokens": s["cache_read_tokens"],
        "cacheHitRate": cache_rate,
        "peakTokens": s["peak_tokens"],
        "peakDay": s["peak_day"],
        "longestSession": fmt_duration_compact(s["longest_session"]["duration_sec"]) if s["longest_session"] else "",
        "currentStreak": s["current_streak"],
        "longestStreak": s["longest_streak"],
        "currentSession": cur,
        "requests": s["requests"],
        "sessionCount": s["session_count"],
        "filesScanned": s["files_scanned"],
        "today": today.isoformat(),
        "tzNote": tz_note or "",
        "live": bool(live),
        "heatRange": [heat_start.isoformat(), today.isoformat()],
        "daily": [
            {"date": d, "total": v["total"], "requests": v["requests"],
             "models": {k: v2 for k, v2 in sorted(v["models"].items())}}
            for d, v in sorted(s["per_day"].items())
        ],
    }


# ---------------------------------------------------------------------------
# HTML 面板
# ---------------------------------------------------------------------------

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>使用统计 · WorkBuddy Token</title>
__ECHARTS__
<style>
  :root {
    --bg: #0d0d0f; --card: #17171a; --card2: #1d1d21; --border: #2a2a30;
    --text: #e8e8ea; --muted: #8a8a93; --accent: #3b82f6; --accent2: #60a5fa;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: "PingFang SC","Microsoft YaHei",-apple-system,"Segoe UI",Roboto,sans-serif; padding: 28px 32px; }
  .header { display:flex; align-items:center; gap:12px; margin-bottom:20px; }
  .header h1 { font-size: 24px; font-weight: 700; }
  .badge { background: var(--card2); color: var(--muted); font-size: 12px; padding: 4px 10px; border-radius: 6px; border: 1px solid var(--border); }
  .badge.live { color: #4ade80; border-color: #14532d; }
  .cards { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; margin-bottom: 16px; }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 16px 18px; min-width: 0; }
  .card .num { font-size: clamp(15px, 2vw, 26px); font-weight: 700; margin-bottom: 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .card .label { font-size: clamp(10px, 1.15vw, 13px); color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .panel { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 18px 20px; margin-bottom: 16px; }
  .panel h2 { font-size: 15px; font-weight: 600; margin-bottom: 4px; }
  .panel .sub { font-size: 12px; color: var(--muted); margin-bottom: 10px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  #heatmap { width: 100%; height: 190px; }
  .trend-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; gap: 10px; }
  .seg { display: inline-flex; background: var(--card2); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; flex-shrink: 0; }
  .seg button { background: transparent; border: 0; color: var(--muted); padding: 6px 16px; font-size: 13px; cursor: pointer; white-space: nowrap; }
  .seg button.on { background: var(--accent); color: #fff; }
  #trend { width: 100%; height: 320px; }
  .grid2 { display: grid; grid-template-columns: 3fr 2fr; gap: 16px; }
  #donut { width: 100%; height: 300px; }
  .legend { font-size: 13px; }
  .legend .row { display:flex; align-items:center; gap:8px; margin:10px 0; }
  .legend .dot { width:10px; height:10px; border-radius:50%; flex-shrink:0; }
  .legend .pct { color: var(--muted); margin-left: auto; white-space: nowrap; }
  .footer { color: var(--muted); font-size: 12px; margin-top: 8px; display:flex; justify-content: space-between; gap: 12px; }
  .footer span { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  @media (max-width: 700px){ body { padding: 20px 16px; } }
</style>
</head>
<body>
  <div class="header"><h1>使用统计</h1><span class="badge" id="badge">WorkBuddy Token 用量</span></div>

  <div class="cards">
    <div class="card"><div class="num" id="c-total">—</div><div class="label">累计 Token（全部会话）</div><div class="label" id="c-io" style="margin-top:2px"></div></div>
    <div class="card"><div class="num" id="c-cur">—</div><div class="label">当前会话消耗</div><div class="label" id="c-cur-sub" style="margin-top:2px"></div></div>
    <div class="card"><div class="num" id="c-cache">—</div><div class="label">缓存命中率</div><div class="label" id="c-cache-sub" style="margin-top:2px"></div></div>
    <div class="card"><div class="num" id="c-peak">—</div><div class="label">峰值 Token 数（单日）</div><div class="label" id="c-peak-sub" style="margin-top:2px"></div></div>
    <div class="card"><div class="num" id="c-dur">—</div><div class="label">最长会话时长</div><div class="label" id="c-dur-sub" style="margin-top:2px"></div></div>
  </div>

  <div class="panel">
    <h2>Token 活动</h2><div class="sub" id="heat-sub">每日总消耗 · 近一年</div>
    <div id="heatmap"></div>
  </div>

  <div class="panel">
    <div class="trend-head">
      <h2>每日 Token 趋势图</h2>
      <span class="seg"><button id="btn7" class="on" onclick="setRange(7)">近 7 日</button><button id="btn30" onclick="setRange(30)">近 30 日</button></span>
    </div>
    <div class="sub" id="trend-sub"></div>
    <div id="trend"></div>
  </div>

  <div class="grid2">
    <div class="panel">
      <h2>模型用量</h2><div class="sub" id="donut-sub"></div>
      <div id="donut"></div>
    </div>
    <div class="panel">
      <h2>明细</h2><div class="sub">按所选时间范围</div>
      <div class="legend" id="legend"></div>
    </div>
  </div>

  <div class="footer">
    <span id="meta"></span>
    <span id="gen"></span>
  </div>

<script>
const BOOT = __DATA__;
const LIVE = BOOT.live === true;
let CUR = BOOT;
let range = 7;

function fmtTok(n){
  if(n >= 1e8) return (n/1e8).toFixed(n % 1e8 ? 1 : 0) + ' 亿';
  if(n >= 1e4) return (n/1e4).toFixed(n % 1e4 ? 1 : 0) + ' 万';
  return (n||0).toLocaleString();
}

const chart = (id) => echarts.init(document.getElementById(id), null, {renderer:'canvas'});
const heatC = chart('heatmap'), trendC = chart('trend'), donutC = chart('donut');
window.addEventListener('resize', () => { heatC.resize(); trendC.resize(); donutC.resize(); });

const PALETTE = ['#3b82f6','#22c55e','#f59e0b','#a855f7','#ef4444','#14b8a6','#e879f9','#facc15'];
function modelColor(i){ return PALETTE[i % PALETTE.length]; }

// ---- 渲染入口（首次 + 实时热更新共用）----
function render(d){
  CUR = d;
  document.getElementById('c-total').textContent = fmtTok(d.totalTokens);
  document.getElementById('c-io').textContent = '输入 ' + fmtTok(d.inputTokens) + ' · 输出 ' + fmtTok(d.outputTokens);
  const cs = d.currentSession;
  document.getElementById('c-cur').textContent = cs ? fmtTok(cs.total) : '—';
  document.getElementById('c-cur-sub').textContent = cs
    ? fmtTok(cs.requests) + ' 轮 · 命中 ' + (cs.cacheRate || 0) + '% · ' + (cs.id || '').slice(0, 8)
    : '未识别到活跃会话';
  document.getElementById('c-cache').textContent = (d.cacheHitRate || 0) + '%';
  document.getElementById('c-cache-sub').textContent = '缓存读取 ' + fmtTok(d.cacheReadTokens) + ' / 输入 ' + fmtTok(d.inputTokens);
  document.getElementById('c-peak').textContent = fmtTok(d.peakTokens);
  document.getElementById('c-peak-sub').textContent = d.peakDay || '';
  document.getElementById('c-dur').textContent = d.longestSession || '—';
  document.getElementById('c-dur-sub').textContent = d.sessionCount + ' 个会话 · ' + d.requests.toLocaleString() + ' 轮调用';
  document.getElementById('heat-sub').textContent = '每日总消耗 · 近一年 · 当前连续 ' + d.currentStreak + ' 天 · 最长连续 ' + d.longestStreak + ' 天';
  document.getElementById('meta').textContent = '数据来源: ' + d.filesScanned + ' 个会话转录 · ' + d.sessionCount + ' 个会话 · ' + d.requests.toLocaleString() + ' 次模型调用';
  document.getElementById('gen').textContent = '更新于 ' + new Date().toLocaleTimeString('zh-CN', {hour12:false}) + (d.tzNote ? ' (' + d.tzNote + ')' : '');
  renderHeatmap(d);
  renderTrend();
}

function renderHeatmap(d){
  heatC.setOption({
    tooltip: { formatter: p => {
      const v = p.value[1] || 0, r = p.value[2] || 0;
      return p.value[0] + '<br/>' + fmtTok(v) + ' tokens · ' + r + ' 轮消息';
    }},
    visualMap: { show:false, min:0, max: Math.max(1, ...d.daily.map(x=>x.total)),
      inRange: { color: ['#1f2937','#1e3a8a','#2563eb','#3b82f6','#60a5fa','#93c5fd'] } },
    calendar: {
      top: 30, left: 46, right: 16, cellSize: ['auto', 14], splitLine: { show: false },
      yearLabel: { show: false }, monthLabel: { color: '#8a8a93', fontSize: 11 },
      dayLabel: { show:false },
      itemStyle: { color: '#141416', borderColor: '#0d0d0f', borderWidth: 2, borderRadius: 3 },
      range: d.heatRange
    },
    series: [{ type:'heatmap', coordinateSystem:'calendar', data: d.daily.map(x => [x.date, x.total, x.requests]),
      itemStyle: { borderRadius: 3, borderColor:'#0d0d0f', borderWidth: 2 } }]
  }, true);
}

// ---- 趋势 & 环形（联动时间范围；按日期取数、缺失日补零）----
function rangeData(){
  const endD = new Date(CUR.today + 'T00:00:00');
  const startD = new Date(endD); startD.setDate(startD.getDate() - (range - 1));
  const iso = d => d.getFullYear() + '-' + String(d.getMonth()+1).padStart(2,'0') + '-' + String(d.getDate()).padStart(2,'0');
  const byDate = {}; CUR.daily.forEach(x => byDate[x.date] = x);
  const days = [];
  for (let d = new Date(startD); d <= endD; d.setDate(d.getDate()+1)) {
    const key = iso(d), src = byDate[key];
    days.push(src ? src : {date: key, total: 0, requests: 0, models: {}});
  }
  const models = Array.from(new Set(days.flatMap(x => Object.keys(x.models))));
  models.sort((a,b) => {
    const sa = days.reduce((s,x)=>s+(x.models[a]||0),0), sb = days.reduce((s,x)=>s+(x.models[b]||0),0);
    return sb - sa;
  });
  const totals = {}; let sum = 0;
  models.forEach(m => { totals[m] = days.reduce((s,x)=>s+(x.models[m]||0),0); sum += totals[m]; });
  return { days, models, totals, sum };
}

function renderTrend(){
  const {days, models, totals, sum} = rangeData();
  trendC.setOption({
    tooltip: { trigger:'axis', valueFormatter: v => fmtTok(v||0) + ' tokens' },
    legend: { data: models, top: 6, textStyle:{color:'#8a8a93'}, icon:'circle', itemWidth:8 },
    grid: { left: 56, right: 24, top: 40, bottom: 28 },
    xAxis: { type:'category', data: days.map(x=>x.date.slice(5)), axisLine:{lineStyle:{color:'#2a2a30'}}, axisLabel:{color:'#8a8a93'} },
    yAxis: { type:'value', splitLine:{lineStyle:{color:'#1f1f24'}}, axisLabel:{color:'#8a8a93', formatter: v=>fmtTok(v)} },
    series: models.map((m,i) => ({
      name: m, type:'line', smooth: true, symbol:'circle', symbolSize: 5, showSymbol: false,
      data: days.map(x => x.models[m] || 0),
      lineStyle: { width: 2.5, color: modelColor(i) }, itemStyle: { color: modelColor(i) },
      areaStyle: models.length === 1 ? { opacity: 0.12, color: modelColor(i) } : undefined
    }))
  }, true);

  donutC.setOption({
    tooltip: { formatter: p => p.name + '<br/>' + fmtTok(p.value) + ' tokens (' + p.percent.toFixed(1) + '%)' },
    title: { text: fmtTok(sum), subtext: 'tokens', left:'center', top:'42%',
      textStyle:{color:'#e8e8ea',fontSize:22,fontWeight:700}, subtextStyle:{color:'#8a8a93',fontSize:12} },
    series: [{ type:'pie', radius:['58%','80%'], center:['50%','50%'], label:{show:false},
      itemStyle:{ borderColor:'#17171a', borderWidth:2, borderRadius:4 },
      data: models.map((m,i)=>({ name:m, value:totals[m], itemStyle:{color:modelColor(i)} })) }]
  }, true);

  document.getElementById('donut-sub').textContent = '近 ' + range + ' 日 · 合计 ' + fmtTok(sum) + ' tokens';
  const lg = document.getElementById('legend');
  lg.innerHTML = models.map((m,i) => {
    const pct = sum ? (totals[m]/sum*100).toFixed(1) : '0.0';
    return '<div class="row"><span class="dot" style="background:'+modelColor(i)+'"></span><span>'+m+'</span><span class="pct">'+pct+'% · '+fmtTok(totals[m])+'</span></div>';
  }).join('') || '<div class="row" style="color:#8a8a93">所选范围内暂无数据</div>';
}

function setRange(n){
  range = n;
  document.getElementById('btn7').classList.toggle('on', n===7);
  document.getElementById('btn30').classList.toggle('on', n===30);
  renderTrend();
}

render(BOOT);
if (BOOT.live) {
  document.getElementById('badge').textContent = '实时 · 每 30 秒自动刷新';
  document.getElementById('badge').classList.add('live');
  setInterval(async () => {
    try {
      const r = await fetch('/api/stats', {cache:'no-store'});
      if (r.ok) render(await r.json());
    } catch (e) { /* 服务暂不可达时保持当前画面 */ }
  }, 30000);
}
</script>
</body>
</html>
"""


def load_echarts_inline():
    """优先使用本地 vendored echarts.min.js；其次尝试下载内联；最后回退 CDN。"""
    here = os.path.dirname(os.path.abspath(__file__))
    for c in (os.path.join(here, "echarts.min.js"), os.path.join(here, "..", "echarts.min.js")):
        if os.path.exists(c):
            try:
                return "/* vendored echarts */\n" + open(c, "r", encoding="utf-8").read()
            except OSError:
                pass
    try:
        import urllib.request
        for url in (
            "https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js",
            "https://unpkg.com/echarts@5.5.1/dist/echarts.min.js",
        ):
            try:
                with urllib.request.urlopen(url, timeout=8) as resp:
                    return resp.read().decode("utf-8")
            except Exception:
                continue
    except Exception:
        pass
    return None


def render_html(data, echarts_js=None, tz_note=""):
    """把 dashboard 数据渲染为完整 HTML 字符串。"""
    if echarts_js is None:
        echarts_js = load_echarts_inline()
    if echarts_js:
        echart_tag = echarts_js
    else:
        echart_tag = 'document.write(\'<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js"><\\/script>\')'
    html = (HTML_TEMPLATE
            .replace("__ECHARTS__", "<script>" + echart_tag + "</script>")
            .replace("__DATA__", json.dumps(data, ensure_ascii=False)))
    return html


def dump_html(s, path, tz_note=""):
    data = build_dashboard_data(s, tz_note=tz_note, live=False)
    html = render_html(data, tz_note=tz_note)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    size_kb = os.path.getsize(path) / 1024
    inline = "内联" if load_echarts_inline() else "CDN 回退"
    print(f"[ok] HTML 面板已生成: {path} ({size_kb:.0f} KB, ECharts {inline})", file=sys.stderr)


# ---------------------------------------------------------------------------
# 实时面板服务（快捷入口）
# ---------------------------------------------------------------------------

def serve_dashboard(port, host="127.0.0.1", data_dir=DEFAULT_DATA_DIR, tz_name=None):
    """常驻 HTTP 服务：/ 实时面板（30s 自刷新） · /api/stats JSON · /healthz 健康检查。"""
    import threading
    import time
    import urllib.parse
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    echarts_js = load_echarts_inline() or ""
    cache = {"ts": 0.0, "stats": None}
    lock = threading.Lock()

    def get_stats():
        with lock:
            now = time.time()
            if cache["stats"] is None or now - cache["ts"] > 3.0:
                cache["stats"] = compute_stats(data_dir, tz_name)
                cache["ts"] = now
            return cache["stats"]

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # 静默访问日志
            pass

        def _send(self, code, body: bytes, ctype="text/html; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")  # 允许 widget 卡片跨源拉取实时数据
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            path = urllib.parse.urlparse(self.path).path
            if path in ("/", "/dashboard"):
                s = get_stats()
                data = build_dashboard_data(s, tz_note=tz_name or "", live=True)
                self._send(200, render_html(data, echarts_js, tz_name or "").encode("utf-8"))
            elif path == "/api/stats":
                s = get_stats()
                data = build_dashboard_data(s, tz_note=tz_name or "", live=True)
                self._send(200, json.dumps(data, ensure_ascii=False).encode("utf-8"),
                           "application/json; charset=utf-8")
            elif path == "/echarts.min.js":
                self._send(200, echarts_js.encode("utf-8"), "application/javascript; charset=utf-8")
            elif path == "/healthz":
                self._send(200, b"ok", "text/plain; charset=utf-8")
            else:
                self._send(404, b"not found", "text/plain; charset=utf-8")

    ThreadingHTTPServer.allow_reuse_address = True
    srv = ThreadingHTTPServer((host, port), Handler)
    print(f"[ok] Token 面板服务已启动: http://{host}:{port}  (Ctrl+C 停止)", file=sys.stderr)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="WorkBuddy Token 使用统计")
    ap.add_argument("--data-dir", default=DEFAULT_DATA_DIR, help="转录根目录（默认 ~/.codebuddy/projects）")
    ap.add_argument("--html", metavar="PATH", help="生成 HTML 可视化面板（静态快照）")
    ap.add_argument("--json", dest="json_path", metavar="PATH", help="输出结构化 JSON")
    ap.add_argument("--tz", default=None, help="时区，如 Asia/Shanghai（默认系统本地时区）")
    ap.add_argument("--quiet", action="store_true", help="不打印终端摘要")
    ap.add_argument("--serve", nargs="?", const=DEFAULT_PORT, default=None, type=int,
                    metavar="PORT", help=f"启动实时面板服务（默认端口 {DEFAULT_PORT}），面板每 30 秒自动刷新")
    ap.add_argument("--host", default="127.0.0.1", help="服务绑定地址（默认 127.0.0.1）")
    args = ap.parse_args()

    if not os.path.isdir(args.data_dir):
        print(f"[error] 数据目录不存在: {args.data_dir}", file=sys.stderr)
        sys.exit(1)

    if args.serve:
        serve_dashboard(args.serve, args.host, args.data_dir, args.tz)
        return

    s = compute_stats(args.data_dir, args.tz)

    if args.json_path:
        dump_json(s, args.json_path)
        print(f"[ok] JSON 已生成: {args.json_path}", file=sys.stderr)
    if args.html:
        dump_html(s, args.html, tz_note=args.tz)
    if not args.quiet:
        print_summary(s)

    if s["files_scanned"] == 0:
        print("[warn] 未找到任何 .jsonl 转录文件", file=sys.stderr)


if __name__ == "__main__":
    main()
