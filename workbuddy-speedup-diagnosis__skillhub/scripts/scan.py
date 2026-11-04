#!/usr/bin/env python3
"""WorkBuddy 变慢卡顿诊断 · 一句话诊断引擎

把用户原话 + 本机只读扫描交叉验证，直接给出 1 个结论 + 1 个动作。
全程只读，不写入、不联网、不打印任何凭证。

用法：
    python3 scan.py --symptom "用户原话"   # 主用法：一句话直接出结论
    python3 scan.py                        # 无症状，纯环境体检
    python3 scan.py --symptom "..." --json # 结构化输出
"""
import json, os, re, sqlite3, sys, tempfile
import statistics
from pathlib import Path


def _friendly_crash(etype, value, tb):
    if etype is KeyboardInterrupt:
        sys.exit(130)
    print(f"[!] 体检脚本中途出错了（{etype.__name__}），这不是你电脑的问题，多半是 WorkBuddy 升级后数据格式变了。")
    print("[>] 给用户的话：点开对话框右下角的灰色小圈，展开看哪一项占得最大，告诉我。")
    print("[内部] 按退出码 2 处理：走 SKILL.md「脚本跑不起来」的路由表。")
    sys.exit(2)


sys.excepthook = _friendly_crash

HOME = Path.home()
MARKERS = ("workbuddy.db", "settings.json", "skills", "memory")


R = {"ok": True, "notes": []}


def note(m):
    if m not in R["notes"]:
        R["notes"].append(m)


def find_root():
    """按优先级探三个候选，用标记文件确认，而不是写死一个路径。"""
    cands, explicit = [], []
    for var in ("WORKBUDDY_CONFIG_DIR", "WORKBUDDY_DIR", "WORKBUDDY_HOME"):
        if os.environ.get(var):
            cands.append(Path(os.environ[var]))
            explicit.append((var, os.environ[var]))
    cands += [HOME / ".workbuddy", HOME / ".workbuddy-ai"]
    for c in cands:
        if c.is_dir() and any((c / m).exists() for m in MARKERS):
            for var, val in explicit:
                if Path(val) != c:
                    note(f"环境变量 {var} 指向的 {val} 里没有 WorkBuddy 数据，已自动改查默认位置")
            return c
    return None


ROOT = find_root()


def load_json(name):
    p = ROOT / name
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def query(sql):
    """只读 URI 直连。实测这样能读到 WAL 里的最新写入，
    复制 db/wal/shm 再读反而可能拿到旧数据。"""
    db = ROOT / "workbuddy.db"
    if not db.exists():
        return None
    err = None
    # mode=ro 需要能在目录里建 -shm；沙箱/权限受限时退到 immutable（读不到未落盘的 WAL，但总比没有强）
    for uri in (f"file:{db}?mode=ro", f"file:{db}?immutable=1"):
        try:
            con = sqlite3.connect(uri, uri=True)
            try:
                return con.execute(sql).fetchall()
            finally:
                con.close()
        except Exception as e:
            err = e
    msg = str(err).lower()
    if "locked" in msg or "busy" in msg:
        note("会话数据正被 WorkBuddy 占用，这次没读到用量——关掉 WorkBuddy 再跑一次，或直接看右下角小圈")
    elif "no such" in msg:
        note("这个 WorkBuddy 版本的数据格式和脚本认识的不一样，会话用量这项跳过了（其余照常）；以界面上小圈的读数为准")
    else:
        note(f"会话数据这次没读出来（{type(err).__name__}），用量一项跳过了；以界面上小圈的读数为准")
    return None


# ---------- 0. 安装检测 ----------
if ROOT is None:
    print("[!] 没在这台电脑上找到 WorkBuddy 的数据，自动体检做不了。")
    print("    常见原因：① WorkBuddy 装在另一台电脑上；② 还没打开过 WorkBuddy；")
    print("              ③ 数据放在了别的位置（可设环境变量 WORKBUDDY_HOME 指过去）。")
    print("    这不影响诊断，只是改成「问一句答一句」：")
    print("[>] 给用户的话：点开对话框右下角的灰色小圈，展开看哪一项占得最大，告诉我。")
    print("[内部] 退出码 2 → 按 SKILL.md「脚本跑不起来」走路由表。")
    sys.exit(2)

# ---------- 1. L3 会话上下文用量 ----------
rows = query("""
  SELECT COALESCE(s.custom_title, s.title, '(无标题)'),
         u.used, u.size, s.mode, s.model, s.cwd, s.last_activity_at
  FROM session_usage u JOIN sessions s ON s.id = u.session_id
  WHERE s.deleted_at IS NULL AND u.size > 0
  ORDER BY s.last_activity_at DESC LIMIT 10
""") or []
sessions = [{
    "title": t, "sid": None, "used": used, "size": size,
    "pct": round(100.0 * used / size, 1),
    "mode": mode, "model": model, "cwd": cwd,
} for t, used, size, mode, model, cwd, _ in rows]
R["sessions"] = sessions

# ---------- 2. L2 常驻开销 ----------
settings = load_json("settings.json") or {}
overrides = settings.get("skillOverrides", {}) or {}
skills_dir = ROOT / "skills"
installed = []
if skills_dir.is_dir():
    for p in sorted(skills_dir.iterdir()):
        if p.name.startswith(("_", ".")):
            continue
        installed.append(p.name)
lazy = [k for k, v in overrides.items() if v == "user-invocable-only"]
plugins_on = [k for k, v in (settings.get("enabledPlugins", {}) or {}).items() if v]

mcp = load_json("mcp-tool-list.json") or {}
entries = mcp.get("entries", {}) or {}
tool_n = 0
for v in entries.values():
    if isinstance(v, list):
        tool_n += len(v)
    elif isinstance(v, dict):
        tool_n += len(v.get("tools", []) or [])

R["resident"] = {
    "skills_installed": len(installed),
    "skills_lazy": len(lazy),
    "skills_resident": max(len(installed) - len(lazy), 0),
    "plugins_enabled": len(plugins_on),
    "mcp_servers": len(entries),
    "mcp_tools": tool_n,
    "skill_names": installed,
}

# ---------- 3. L2 工作空间体积 ----------
ws = []
for (path,) in (query("SELECT path FROM workspaces ORDER BY last_opened_at DESC LIMIT 5") or []):
    d = Path(path)
    if not d.is_dir():
        continue
    n = 0
    for _, dirnames, filenames in os.walk(d):
        dirnames[:] = [x for x in dirnames if x not in
                       {".git", "node_modules", ".venv", "__pycache__", "dist", "build"}]
        n += len(filenames)
        if n > 5000:
            break
    ws.append({"path": path, "files": n})
R["workspaces"] = ws

# ---------- 3.2 起步开销：一个新会话还没说话就背着多少 ----------
def baseline_tokens():
    """取最近若干会话「第一次请求」的 inputTokens 中位数。
    第一次请求时对话还没积累，这个数≈系统提示词+工具+技能+连接器的常驻量。"""
    firsts = []
    proj = ROOT / "projects"
    if not proj.is_dir():
        return None, 0
    files = sorted(proj.glob("*/*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:8]
    for f in files:
        try:
            with f.open(encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    try:
                        o = json.loads(line)
                    except Exception:
                        continue
                    u = (o.get("providerData") or {}).get("usage") or {}
                    if u.get("inputTokens"):
                        firsts.append(u["inputTokens"])
                        break
        except Exception:
            continue
    if not firsts:
        return None, 0
    return int(statistics.median(firsts)), len(firsts)


base_tok, base_n = baseline_tokens()
R["baseline"] = {"tokens": base_tok, "samples": base_n,
                 "pct": round(100.0 * base_tok / sessions[0]["size"], 1)
                 if base_tok and sessions and sessions[0]["size"] else None}


# ---------- 3.3 每个技能的定义占多大 ----------
def skill_sizes():
    out = []
    d = ROOT / "skills"
    if not d.is_dir():
        return out
    lazy_set = set(lazy)
    for sub in sorted(d.iterdir()):
        if sub.name.startswith(("_", ".")) or not sub.is_dir():
            continue
        md = sub / "SKILL.md"
        if not md.exists():
            cand = list(sub.glob("*/SKILL.md"))
            md = cand[0] if cand else None
        if not md:
            continue
        try:
            t = md.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        fm = t.split("---")[1] if t.startswith("---") else ""
        m = re.search(r"description:\s*(.+)", fm)
        out.append({"name": sub.name, "desc_chars": len(m.group(1)) if m else 0,
                    "resident": sub.name not in lazy_set})
    out.sort(key=lambda x: -x["desc_chars"])
    return out


sizes = skill_sizes()
R["skill_sizes"] = sizes
R["resident"]["desc_chars_total"] = sum(x["desc_chars"] for x in sizes if x["resident"])

# ---------- 3.5 客户端版本与平台 ----------
ll = load_json("last-launch.json") or {}
R["client"] = {
    "version": ll.get("version") or "—",
    "build": (ll.get("build") or "")[:7] or "—",
    "platform": sys.platform,
}

# ---------- 4. 症状匹配（用户原话） ----------
# 每条：层, 别名列表, 结论, 动作, 是否需要扫描数据佐证
SYMPTOMS = [
    ("L3", ["越聊越慢", "越用越慢", "越用越卡", "用久了", "用了一段时间", "聊久了", "聊到后面",
            "前几轮快", "前面快", "越来越慢", "越来越卡", "聊着聊着", "对话太长", "会话太长",
            "轮数多", "刚开始还行", "一开始挺快"],
     "会话堆积——上下文越背越重",
     "先让我整理一份任务检查点写进工作空间文件，再发 /compact 压缩这个对话（顺序不能反，压缩是有损的）"),
    ("L2", ["一开新会话就慢", "新会话就慢", "刚打开就慢", "什么都没聊", "一上来就慢",
            "开局就慢", "装了很多技能", "技能太多", "插件太多", "装了一堆"],
     "常驻开销偏重——每个会话都要重付一遍",
     "去技能管理页，把长期不用的技能关掉（关不是删，随时能开回来）"),
    ("L5", ["费积分", "掉积分", "积分快", "积分掉得", "又慢又费", "烧积分", "积分不够"],
     "Max 模式的代价——开着就不压缩、保留完整上下文，也更费积分",
     "看模型选择下拉的顶部，Max 模式是开是关；任务相互独立、或前面的讨论已经不需要再引用，就关掉"),
    ("L1", ["写代码", "改代码", "改文件", "重构", "整个项目", "多个文件", "git", "分支",
            "python", "java", "前端", "后端", "工程", "多模块", "大规模"],
     "任务和场景模式没对上——写代码却可能不在「代码开发」场景",
     "看对话区顶部当前是哪个场景，不是「代码开发」就切过去；它自带 Git 分支管理和 Worktree 并行"),
    ("L4", ["一句话交代", "一口气", "一次性", "一大堆", "一大坨", "交代了一堆", "让它做一堆",
            "任务很大", "转很久没", "没有中间产出", "没有任何产出"],
     "颗粒度太粗——一次交代太多步，它在原地打转",
     "把这活的第一步单独拎出来问一遍；第一步很快出结果就说明是颗粒度问题，按步推进即可"),
    ("L6", ["连接器", "mcp", "插件失败", "调用失败", "时好时坏", "间歇", "断开", "连不上"],
     "连接器/MCP 这一段的问题，多半不是 WorkBuddy 本身慢",
     "看那个连接器返回什么码：401 重新授权 / 403 查权限 / 429 把调用间隔拉到 2-3 秒 / 500·502·503 等 2-5 分钟再试 / 超时把 timeout 调到 600000"),
    ("L6", ["换了模型也没用", "换模型没用", "切模型没用", "都试过了", "怎么都慢", "换了个模型还是"],
     "模型侧已经排除，剩下的是网络或服务端",
     "先跑一次「帮助 → 网络检查」；报 3002/3003/3007 就是网络环境，关掉网络代理（建议设成「跟随系统」）或让 IT 放行"),
]

# 泛泛的「慢」不指向任何层，只用来确认这确实是提速问题
GENERIC = ["慢", "卡", "等半天", "转圈", "没反应", "要等", "不动"]

# 两层同时命中且分数接近时，用这一句把它们分开
TIEBREAK = {
    frozenset(["L1", "L4"]): "把第一步单独拎出来问一遍：第一步很快出结果就是颗粒度问题（L4）；"
                             "第一步光是开始就要先读一大堆文件，那是范围太大（L1），该拆成多个会话",
    frozenset(["L2", "L3"]): "点开右下角灰色小圈展开看分项：「连接器、MCP 及技能」那项最大是常驻开销（L2）；"
                             "「对话消息」那项最大是会话堆积（L3）",
    frozenset(["L3", "L4"]): "看这轮慢是不是跟对话长度相关：新开一个会话问同样的问题，"
                             "快了就是会话堆积（L3），一样慢就是这件事本身太大（L4）",
}

ALIAS_CODE = {"11115": ("L2", "输入内容过长", "精简这次输入，或换一个支持更大上下文的模型"),
              "6003": ("L5", "请求频率受限", "切换模型重试"),
              "6004": ("L5", "请求频率受限", "切换模型重试"),
              "1001": ("L5", "模型侧状态异常", "切换模型重试"),
              "14003": ("L5", "模型侧状态异常", "切换模型重试"),
              "11133": ("L5", "模型侧状态异常", "新开会话或切换模型重试"),
              "11134": ("L5", "模型侧状态异常", "新开会话或切换模型重试"),
              "3002": ("L6", "网络环境限制", "关掉网络代理（建议「跟随系统」）；公司网找 IT"),
              "3003": ("L6", "网络环境限制", "同 3002"),
              "3007": ("L6", "网络环境限制", "同 3002")}

def argval(flag):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv) and not sys.argv[i + 1].startswith("--"):
            return sys.argv[i + 1]
    return ""


symptom = argval("--symptom")
tried = argval("--tried")        # 用户已经做过、但没奏效的动作
low = symptom.lower()

code_hit = None    # 错误码是确定判据，直接定案
for code, (layer, what, fix) in ALIAS_CODE.items():
    if code in symptom:
        code_hit = (layer, f"错误码 {code} = {what}", fix, "实测数据",
                    f"你报的错误码 {code} 本身就是判据，不用再猜")
        break

# 加权打分：命中的关键词越长越具体，得分越高；裸「慢/卡」不计分
scores = {}
detail = {}
for layer, keys, what, fix in SYMPTOMS:
    hit = [k for k in keys if k in low]
    if not hit:
        continue
    sc = sum(len(k) for k in hit)
    if sc > scores.get(layer, 0):
        scores[layer] = sc
        detail[layer] = (what, fix, hit)
    elif layer in scores:
        scores[layer] += sc

is_speed_issue = bool(scores) or any(g in low for g in GENERIC)
R["matched"] = {l: {"score": scores[l], "keywords": detail[l][2]} for l in scores}

# ---------- 5. 扫描数据判读 + 交叉验证 ----------
findings = []
res = R["resident"]
cur = sessions[0] if sessions else None

scan_layers = {}
if cur and cur["pct"] >= 50:
    scan_layers["L3"] = ("实测数据", f"当前会话已用 {cur['pct']}%（{cur['used']}/{cur['size']} token），过了「一半」这条线")
if res["mcp_tools"] >= 60 or res["skills_resident"] >= 8:
    scan_layers["L2"] = ("代理判据", f"{res['skills_resident']} 个常驻技能、{res['plugins_enabled']} 个插件、"
                                     f"{res['mcp_servers']} 个 MCP 共 {res['mcp_tools']} 个工具定义")
big = [w for w in ws if w["files"] >= 300]
if big and "L2" not in scan_layers:
    scan_layers["L2"] = ("代理判据", "工作空间文件偏多：" +
                         "、".join(f"{Path(w['path']).name} {w['files']} 个" for w in big[:2]))

# 症状命中的层，如果扫描数据也指向它 → 升级为「就是」
verdict = code_hit          # 有错误码就直接定案，跳过交叉验证
ambiguous = None

if verdict is None and scores:
    # 本机数据佐证的层加权
    boosted = {l: sc + (40 if l in scan_layers else 0) for l, sc in scores.items()}
    ranked = sorted(boosted.items(), key=lambda kv: -kv[1])
    top, top_sc = ranked[0]
    what, fix, hit = detail[top]

    # 第二名分数接近（差距 < 30%）且有对应的分流问题 → 先分流，别硬判
    if len(ranked) > 1:
        second, sec_sc = ranked[1]
        key = frozenset([top, second])
        if sec_sc >= top_sc * 0.7 and key in TIEBREAK:
            ambiguous = (top, second, TIEBREAK[key])

    if ambiguous:
        a, b, how = ambiguous
        verdict = (f"{a}/{b}", f"这两层都对得上，光凭你这句话分不开",
                   how, "症状描述",
                   f"「{'、'.join(hit)}」既像 {a} 也像 {b}，得先分开才有准结论")
    elif top in scan_layers:
        t2, ev = scan_layers[top]
        verdict = (top, what, fix, "实测数据" if t2 == "实测数据" else "代理判据",
                   f"症状和本机数据对上了：{ev}")
    else:
        extra = ""
        if top in ("L2", "L3") and cur:
            extra = (f"（当前会话用量 {cur['pct']}%，"
                     + ("不算高，所以这条只是按你的描述判的）" if cur["pct"] < 50 else "也偏高）"))
        verdict = (top, what, fix, "症状描述", f"只有你的描述作依据{extra}")

if verdict is None and scan_layers:
    layer = "L3" if "L3" in scan_layers else next(iter(scan_layers))
    t2, ev = scan_layers[layer]
    what = {"L2": "常驻开销偏重——每个会话都要重付一遍",
            "L3": "会话堆积——上下文越背越重"}[layer]
    fix = {"L2": "去技能管理页，把长期不用的技能关掉（关不是删）",
           "L3": "先存任务检查点到工作空间文件，再发 /compact"}[layer]
    verdict = (layer, what, fix, t2, ev)

R["ambiguous"] = None if not ambiguous else {"a": ambiguous[0], "b": ambiguous[1]}
R["symptom"] = symptom
R["verdict"] = None if not verdict else {
    "layer": verdict[0], "conclusion": verdict[1],
    "action": verdict[2], "tier": verdict[3], "evidence": verdict[4]}
R["scan_layers"] = {k: {"tier": v[0], "evidence": v[1]} for k, v in scan_layers.items()}
for l, (t, e) in scan_layers.items():
    findings.append((l, f"[{t}] {e}"))
R["findings"] = [{"layer": l, "text": t} for l, t in findings]

# ---------- 5.3 六层一览：一次扫完，告诉用户哪些已经替他排除了 ----------
LAYER_NAME = {"L1": "场景/任务范围", "L2": "常驻开销（技能/插件/MCP）", "L3": "会话堆积",
              "L4": "一次交代太多", "L5": "模型与积分", "L6": "网络/连接器"}
overview = {}
for l in LAYER_NAME:
    if verdict and l in str(verdict[0]).split("/"):
        overview[l] = "指向"
    elif l in scan_layers:
        overview[l] = "可疑"
    elif l == "L2" and res["mcp_tools"] < 60 and res["skills_resident"] < 8 and not big:
        overview[l] = "已排除"
    elif l == "L3" and cur and cur["pct"] < 50:
        overview[l] = "已排除"
    else:
        overview[l] = "待测"
R["overview"] = overview

# ---------- 5.4 前后对比 ----------
SNAP = Path(tempfile.gettempdir()) / "wb-speedup-baseline.json"


def snapshot():
    return {"ts": int(__import__("time").time()),
            "baseline": R["baseline"], "resident": R["resident"]}


delta = None
if "--baseline" in sys.argv:
    try:
        SNAP.write_text(json.dumps(snapshot(), ensure_ascii=False), encoding="utf-8")
        R["baseline_saved"] = str(SNAP)
    except Exception as e:
        note(f"基线没存上（{type(e).__name__}，多半是临时目录没写权限）——不影响这次结论，只是改完后没法自动算降幅")
elif SNAP.exists():
    try:
        old = json.loads(SNAP.read_text(encoding="utf-8"))
        ob, nb = (old.get("baseline") or {}).get("tokens"), R["baseline"]["tokens"]
        orr, nr = old.get("resident") or {}, R["resident"]
        if ob and nb:
            delta = {
                "before_tokens": ob, "after_tokens": nb,
                "drop_pct": round(100.0 * (ob - nb) / ob, 1),
                "before_skills": orr.get("skills_resident"), "after_skills": nr["skills_resident"],
                "before_tools": orr.get("mcp_tools"), "after_tools": nr["mcp_tools"],
                "aged_hours": round((snapshot()["ts"] - old.get("ts", 0)) / 3600, 1),
            }
            R["delta"] = delta
    except Exception as e:
        note(f"上次存的基线读不出来（{type(e).__name__}）——重新带 --baseline 跑一次即可")

# ---------- 5.5 兜底：官方反馈文案 ----------
def build_report():
    """没匹配到结论时，拼一段可直接提交的反馈文案。
    只放非敏感事实：版本、平台、症状原话、占用比例、常驻规模、已排查项。
    绝不含会话标题、路径、user_id、device-id、任何凭证。"""
    c = R["client"]
    lines = ["【WorkBuddy 变慢反馈】"]
    lines.append(f"版本 {c['version']}（build {c['build']}）  平台 {c['platform']}")
    if symptom:
        lines.append(f"症状：{symptom.strip()[:60]}")
    else:
        lines.append("症状：响应变慢，无明确触发条件")
    if cur:
        lines.append(f"当前会话上下文占用 {cur['pct']}%（{cur['used']}/{cur['size']}），"
                     f"模式 {cur['mode'] or '—'}，模型 {cur['model'] or '—'}")
    lines.append(f"常驻规模：技能 {res['skills_resident']} 个、插件 {res['plugins_enabled']} 个、"
                 f"MCP {res['mcp_servers']} 个服务共 {res['mcp_tools']} 个工具定义")
    done = []
    if tried:
        done.append(f"已尝试：{tried.strip()[:40]}（无效）")
    if verdict:
        done.append(f"本机扫描指向 {verdict[0]}：{verdict[1]}")
    else:
        done.append("未匹配到已知的变慢模式")
    if cur and cur["pct"] < 50:
        done.append(f"上下文占用未过半（{cur['pct']}%）")
    if res["mcp_tools"] < 60 and res["skills_resident"] < 8:
        done.append("常驻开销不重")
    lines.append("已排查：" + "、".join(done))
    lines.append("期望：定位这台机器上响应变慢的原因。")
    text = "\n".join(lines)
    return text[:300]


# ---------- 6. 输出 ----------
if "--report" in sys.argv and not R.get("feedback_report"):
    R["feedback_report"] = build_report()

if "--json" in sys.argv:
    for x in R.get("sessions", []):
        x.pop("title", None)       # 会话标题是用户内容，不外泄
        x.pop("cwd", None)
    print(json.dumps(R, ensure_ascii=False, indent=2))
    sys.exit(0)

SAY = {"实测数据": "就是", "代理判据": "大概率是", "症状描述": "大概率是"}

if delta:
    sign = "降了" if delta["drop_pct"] > 0 else "反而涨了"
    print("[对比] 相比上次基线（%.1f 小时前）：起步占用 %s %s%%  %d→%d token" % (
        delta["aged_hours"], sign, abs(delta["drop_pct"]),
        delta["before_tokens"], delta["after_tokens"]))
    if delta["before_skills"] != delta["after_skills"] or delta["before_tools"] != delta["after_tools"]:
        print("        常驻技能 %s→%s，MCP 工具定义 %s→%s" % (
            delta["before_skills"], delta["after_skills"],
            delta["before_tools"], delta["after_tools"]))
    print()

if verdict:
    layer, what, fix, tier, ev = verdict
    print(f"[*] 结论：{SAY[tier]}{what}")
    print(f"[内部] 层={layer}（这是路由用的编号，**不要说给用户听**）")
    print(f"[>] 现在做这一件事：{fix}")
    print(f"[=] 依据（{tier}）：{ev}")
else:
    print("[!] 没匹配到已知的变慢模式，本机数据也没异常。")
    print("[>] 现在做这一件事：点开对话框右下角的灰色小圈，展开看哪一项占得最大，告诉我。")
    print("[=] 依据：装的技能/插件不多、当前对话也没背太重，这两个最常见的原因已经排除。")
    R["feedback_report"] = build_report()

if R.get("feedback_report"):
    print("\n" + "=" * 46)
    print("定位不下去了？把下面这段复制走，提交到 左下角头像 → 帮助与反馈 → 意见反馈")
    print("（记得勾「上传日志」；提交前自己核一遍描述准不准）")
    print("-" * 46)
    print(R["feedback_report"])
    print("=" * 46)

b = R["baseline"]
if b["tokens"]:
    print(f"\n[起步开销] 每开一个新会话，一个字还没说就先背着约 {b['tokens']:,} token"
          + (f"（预算的 {b['pct']}%）" if b["pct"] else "")
          + f"——这是 {b['samples']} 个会话首轮请求的中位数。**这句最值得讲给用户听。**")

top = [x for x in sizes if x["resident"]][:3]
if top and R["resident"]["desc_chars_total"]:
    names = "、".join(f"{x['name']}({x['desc_chars']}字符)" for x in top)
    print(f"[占地方的技能] 常驻定义合计 {R['resident']['desc_chars_total']} 字符，最大三个：{names}")
    print("             → 处方要点名这三个，别说「关掉不用的技能」，用户不知道关哪个。")

if cur:
    print(f"\n本机快照   当前会话 {cur['pct']}%（{cur['used']}/{cur['size']}）  "
          f"mode={cur['mode'] or '-'}  model={cur['model'] or '-'}")
print(f"           常驻 技能 {res['skills_installed']} 装/{res['skills_resident']} 常驻，"
      f"插件 {res['plugins_enabled']}，MCP {res['mcp_servers']} 服务 {res['mcp_tools']} 工具")

print("\n[六层一览] " + "  ".join(f"{LAYER_NAME[l]}:{v}" for l, v in overview.items()))
cleared = [LAYER_NAME[l] for l, v in overview.items() if v == "已排除"]
if cleared:
    print(f"            → 可以告诉用户：「{'、'.join(cleared)}我已经顺带查过，没问题」——省得他一项项去试。")

other = [f for f in findings if not verdict or f[0] != verdict[0]]
if other:
    print("\n[~] 顺带发现（先别动，等上面那条做完没效果再看）：")
    for l, t in other:
        print(f"      {l} {t}")

if R["notes"]:
    print("\n[提示] 有几项没读全，不影响上面的结论：")
for m in R["notes"]:
    print(f"      · {m}")
print("\n[口径] used 是当前上下文的输入 token（实测与会话记录里的峰值 inputTokens 完全一致），"
      "size 是这个会话的预算、不是模型上限——不同模型不一样，别跨会话比。")
print("[待验证] 关技能/改配置之后，必须**新开一个会话**再看一次占用才算数；"
      "改完当前会话不会自动变轻。")
print("[怎么证明有效] 让用户动手之前先跑一次 `--baseline` 存基线，改完再跑一次，"
      "脚本会直接打出降了百分之多少——比让用户凭感觉说「好像快了点」有说服力得多。")
print("[?] 读不到、必要时才问用户：上下文圈的分项占比、Max 模式开关、当前场景模式。")
