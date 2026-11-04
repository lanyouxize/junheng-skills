#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文章采集台账：把「赞和收藏 → 复制链接 → 下载工具取公众号id → 放大镜打开 → 批量下载」
这条流水线上每一步产出的信息，按**文章/公众号一行**记下来。

解决什么问题
------------
自动化跑久了会散落一堆链接：文章链接、工具吐出的 `profile_ext` 链接、来源公众号名，
以及"这篇到底是宠物食品、添加剂还是行业趋势"。人肉对不上号，也没法回头统计某个号
到底收了多少篇、哪个品类跑得多。这份台账把它们收敛成一张表，两种呈现同一数据源：

  * 机器可读：`out/favorites-ledger.csv`（`utf-8-sig`，Excel 双击不乱码）
  * 人可读：  `docs/favorites-ledger.md`（Markdown 表格 + 标签分布统计）

列（顺序固定，新增列只能往后加，否则历史 CSV 会错位）
-----------------------------------------------------
  序号 / 采集时间 / 来源渠道 / 公众号名称 / 文章标题 / 发布时间 /
  文章链接 / profile_ext网址 / 信息类型 / 备注

  采集时间统一 UTC（`YYYY-MM-DDTHH:MM:SSZ`），与仓库其它模块一致 —— 本地时间会让
  跨机合并的台账出现"同一篇两个时间"的假冲突。

去重规则（重点，不是每次追加一行）
----------------------------------
主键优先级：`profile_ext网址`（非空时） > `文章链接`。
同一个公众号的所有文章共享同一条 `profile_ext` 链接，所以拿到 id 之后按它去重，
能把"同一个号的多篇"收敛成一行，其余文章的链接记进备注的「同号文章」清单 ——
用户要的正是"这个号收了哪几篇"，而不是十行重复的号名。

  * 已有同 `profile_ext`：更新标题/发布时间/备注（仅当新值非空），文章链接追加进
    备注「同号文章」，**不覆盖**原文章链接，返回原行；日志打 `ledger.merged`。
  * 否则已有同 `文章链接`：更新非空字段，返回原行（同样打 `ledger.merged`）。
  * 都没有：新增一行，序号 = 现有最大序号 + 1；日志打 `ledger.appended`。

读改写全程原子：先写同目录临时文件再 `os.replace` —— 采集是长时间批量跑的，
进程被打断时若直接原地写，会留下半截 CSV，Excel 打开报错且此前数据全丢。

信息类型标签
------------
固定枚举（见 `TAGS`），不自由发挥，否则统计没法聚合。自动分类走标题+摘要的关键词
命中；`--tags` 手工指定的标签与自动标签**合并**（去重保序，手工在前），不互相覆盖。

命令行
------
    python scripts/ledger.py add --url <文章链接> [--profile-url <profile_ext>]
                                 [--account 名称] [--title 标题] [--tags a,b]
                                 [--note 备注] [--source 赞和收藏] [--no-fetch]
    python scripts/ledger.py export
    python scripts/ledger.py list [--tag 宠物食品] [--limit 20]
    python scripts/ledger.py tags

Python API（供 pipeline / 其它脚本调用，签名固定）
--------------------------------------------------
    append_record(rec: dict) -> dict
    load() -> list[dict]
    classify(title: str, digest: str = "") -> list[str]
    record_key(rec: dict) -> str

⚠️ `append_record` **只写 CSV**，md 是 CSV 的投影，不会自动刷新 —— 调用方改完数据要
自己调 `export_markdown()`（只有 CLI 的 `add` 会顺手刷 md）。这样"数据层写数据、
导出层生成视图"职责清晰，也避免批量 append 时每篇都重画一次整张表。

环境变量
--------
    UIAC_LEDGER_CSV      覆盖 CSV 路径（测试/临时跑用，避免污染真实 out/）
    UIAC_LEDGER_MD       覆盖 md 路径
    UIAC_LEDGER_TIMEOUT  抓元信息的单篇超时秒数（默认 20）；批量记账嫌慢时可调小
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import tempfile
import unicodedata
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
DEFAULT_CSV = SKILL / "out" / "favorites-ledger.csv"
DEFAULT_MD = SKILL / "docs" / "favorites-ledger.md"

# 模块级路径常量在函数里**读取**而不是当默认参数绑定，测试才能 monkeypatch 到 tmp_path
LEDGER_CSV = DEFAULT_CSV
LEDGER_MD = DEFAULT_MD

COLUMNS = [
    "序号",
    "采集时间",
    "来源渠道",
    "公众号名称",
    "文章标题",
    "发布时间",
    "文章链接",
    "profile_ext网址",
    "信息类型",
    "备注",
]

DEFAULT_SOURCE = "赞和收藏"
DEFAULT_TIMEOUT = 20
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# 备注里「同号文章」段的标记：同一公众号的其它文章链接以空格分隔追加在这一行
SIBLING_MARK = "同号文章："

# 标签体系：顺序即输出顺序（统计报表按这个顺序排，改顺序会改变历史报表观感）
TAGS: dict[str, tuple[str, ...]] = {
    "宠物食品": (
        "宠物", "猫粮", "犬粮", "狗粮", "猫条", "冻干", "罐头", "处方粮", "主粮",
        "零食", "毛球", "排毛", "靓毛", "猫", "犬", "狗",
    ),
    "添加剂": (
        "添加剂", "防腐剂", "乳化剂", "增稠剂", "抗氧化剂", "香精", "色素", "甜味剂",
        "酶制剂", "益生菌", "益生元", "维生素", "矿物质", "氨基酸", "牛磺酸",
    ),
    "乳化剂": ("乳化剂", "乳化", "卵磷脂", "单甘酯", "蔗糖酯", "稳定剂", "均质"),
    "原料": (
        "原料", "肉粉", "鱼粉", "豆粕", "谷物", "淀粉", "油脂", "蛋白", "水解",
        "鲜肉", "副产品",
    ),
    "法规标准": (
        "GB", "法规", "标准", "办法", "条例", "公告", "征求意见", "合规", "标示",
        "标签", "限量", "禁用", "许可",
    ),
    "检测认证": (
        "检测", "检验", "认证", "审核", "体系", "HACCP", "ISO", "CMA", "CNAS",
        "微生物", "菌落", "超标", "召回",
    ),
    "行业信息": (
        "行业", "市场", "企业", "融资", "并购", "品牌", "渠道", "电商", "抖音",
        "直播", "销售", "营收",
    ),
    "趋势": ("趋势", "预测", "报告", "洞察", "增长", "消费", "渗透率", "风口", "前景"),
    "AI": ("AI", "人工智能", "大模型", "算法", "智能体", "DeepSeek", "GPT", "机器学习"),
}
FALLBACK_TAG = "其他"

# 各种破折号/连接号统一成半角 "-"：用户文档里 `GB28050-2025` 与 `GB 28050—2025`
# 指的是同一份标准，NFKC 不会折叠 U+2014（em dash），必须自己收口。
_DASHES = "—–－‐‑‒―~～"
_DASH_TABLE = str.maketrans({ch: "-" for ch in _DASHES})
_WS_RE = re.compile(r"\s+")
# 手工 --tags 的分隔符：半角逗号、中文顿号、分号都算（用户从文档里复制时常混用）
_TAG_SPLIT_RE = re.compile(r"[,，、;；]+")


def log(level: str, event: str, **fields) -> None:
    """打结构化日志到 stderr，格式与 wechat_open_url / pipeline 保持一致。"""
    rec = {"ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "level": level, "event": event}
    rec.update(fields)
    sys.stderr.write(json.dumps(rec, ensure_ascii=False) + "\n")
    sys.stderr.flush()


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------------------ 路径
def _csv_path() -> Path:
    return Path(os.environ.get("UIAC_LEDGER_CSV") or LEDGER_CSV)


def _md_path() -> Path:
    return Path(os.environ.get("UIAC_LEDGER_MD") or LEDGER_MD)


# ------------------------------------------------------------------ 标签
def _norm(text: str) -> str:
    """匹配前的归一化：全角转半角(NFKC) + 小写 + 破折号统一。

    为什么不用裸 `str.lower()`：中文文档里常见的全角 `ＧＢ`、`ＨＡＣＣＰ` 以及
    `28050—2025` 这种长破折号，不归一化就完全命中不了关键词表。
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", str(text))
    return text.translate(_DASH_TABLE).lower()


def classify(title: str, digest: str = "") -> list[str]:
    """按固定标签体系给出信息类型；一个都没命中时返回 ["其他"]。

    标题与摘要一起匹配：标题常常只有「牛磺酸缺乏的代价」，光看标题会漏掉
    摘要里的"猫粮""添加剂"这类关键信息。
    """
    text = _norm(f"{title or ''} {digest or ''}")
    if not text.strip():
        return [FALLBACK_TAG]
    hits = [
        tag
        for tag, keywords in TAGS.items()
        if any(_norm(kw) in text for kw in keywords)
    ]
    # 兜底标签只在完全没有命中时出现 —— 否则每篇都会挂个"其他"，统计就废了
    return hits or [FALLBACK_TAG]


def split_tags(raw) -> list[str]:
    """把 `--tags` 的输入（字符串或列表）拆成去重保序的标签列表。"""
    if not raw:
        return []
    parts = raw if isinstance(raw, (list, tuple)) else _TAG_SPLIT_RE.split(str(raw))
    out: list[str] = []
    for part in parts:
        tag = str(part).strip()
        if tag and tag not in out:
            out.append(tag)
    return out


def merge_tags(manual: list[str], auto: list[str]) -> list[str]:
    """手工标签在前、自动标签在后，去重保序。

    手工标签是用户明确指定的，优先级高于规则命中；自动标签只是补全，不能覆盖。
    手工已经给了分类时丢弃自动的"其他"兜底 —— 它只表示"规则没认出来"，
    不是用户想看的分类。
    """
    merged = list(manual)
    for tag in auto:
        if tag == FALLBACK_TAG and manual:
            continue
        if tag not in merged:
            merged.append(tag)
    return merged


def format_tags(tags: list[str]) -> str:
    """列内多标签统一用中文顿号连接（与用户要求的写法一致）。"""
    return "、".join(t for t in tags if t)


def parse_tags_cell(cell: str) -> list[str]:
    return [t for t in str(cell or "").split("、") if t.strip()]


# ------------------------------------------------------------------ 备注
def parse_remark(remark: str) -> tuple[str, list[str]]:
    """把备注拆成 (正文备注, 同号文章链接列表)。

    备注里可能同时有用户写的说明和自动追加的「同号文章：」段，二者必须分开维护，
    否则更新备注时会把已收集的同号文章链接一起冲掉。
    """
    text = str(remark or "")
    if text.startswith(SIBLING_MARK):
        # 只有同号链接、没有用户备注时，备注整段以标记开头
        core, tail = "", text[len(SIBLING_MARK):]
    elif "\n" + SIBLING_MARK in text:
        core, _, tail = text.partition("\n" + SIBLING_MARK)
    else:
        # 兼容手工写在一行里的形式（备注正文 + 标记同一行）
        core, _, tail = text.partition(SIBLING_MARK)
    urls = re.findall(r"https?://[^\s、,，]+", tail) if tail else []
    cleaned: list[str] = []
    for url in urls:
        if url not in cleaned:
            cleaned.append(url)
    return core.strip(), cleaned


def build_remark(core: str, urls: list[str]) -> str:
    core = (core or "").strip()
    urls = [u for u in urls if u]
    if not urls:
        return core
    section = SIBLING_MARK + " ".join(urls)
    return f"{core}\n{section}" if core else section


# ------------------------------------------------------------------ 落盘
def _field(rec: dict, *names: str) -> str:
    for name in names:
        value = rec.get(name)
        if value not in (None, "", []):
            return str(value).strip()
    return ""


def load() -> list[dict]:
    """读 CSV 为字典列表；文件不存在返回空列表（不抛异常，首次运行即从这里开始）。"""
    path = _csv_path()
    if not path.exists():
        return []
    # utf-8-sig：读写都带 BOM，Excel 双击打开中文列名才不乱码
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        rows = [dict(row) for row in csv.DictReader(fh)]
    for row in rows:
        seq = str(row.get("序号") or "").strip()
        row["序号"] = int(seq) if seq.isdigit() else 0
    return rows


def _write_rows(rows: list[dict]) -> None:
    """原子写：同目录临时文件 → os.replace。进程被打断也不会留半截 CSV。"""
    path = _csv_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=COLUMNS, lineterminator="\n",
                                    extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({col: row.get(col, "") for col in COLUMNS})
            fh.flush()
            os.fsync(fh.fileno())       # 先落盘再 rename，断电时也不会得到空文件
        os.replace(tmp, path)
    except BaseException:
        # 失败时清掉临时文件；原文件保持上一次的完整状态
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def record_key(rec: dict) -> str:
    """去重主键：有 profile_ext 网址就用它，否则退回文章链接。

    同一公众号的全部文章共享同一条 profile_ext，所以拿到 id 之后按它去重，
    才能把"同一个号的多篇"收敛成一行。
    """
    profile = _field(rec, "profile_url", "profile_ext网址")
    if profile:
        return profile
    return _field(rec, "url", "文章链接")


# ------------------------------------------------------------------ 抓取
def _fetch_html(url: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    """拉文章页 HTML（标准库 urllib，不引第三方依赖）。"""
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - 固定域名白名单在调用方
        raw = resp.read()
    return raw.decode("utf-8", "replace")


# 老式页面里的三件套：`var nickname = "..."` / `var msg_title` / `var ct`（发布时间戳）
_JS_VAR_TMPL = r"""var\s+{name}\s*=\s*(?:"([^"]*)"|'([^']*)'|htmlDecode\(\s*["']([^"']*)["']\s*\))"""
_JS_VAR_RE = {
    name: re.compile(_JS_VAR_TMPL.format(name=name))
    for name in ("nickname", "msg_title", "ct", "msg_desc")
}


def _js_var_regex(html: str, name: str) -> str:
    match = _JS_VAR_RE[name].search(html or "")
    if not match:
        return ""
    return next((g for g in match.groups() if g), "")


def _epoch_to_iso(raw: str) -> str:
    if not str(raw or "").strip().isdigit():
        return ""
    ts = int(str(raw).strip())
    # 微信的 ct 是秒级；万一是毫秒则按 ms 处理
    if ts > 10_000_000_000:
        ts //= 1000
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OverflowError, OSError, ValueError):
        return ""


def _extract_by_collector(html: str, url: str) -> dict:
    """优先用采集技能的纯解析器（BS4，无浏览器依赖），失败返回 {}。

    直接 import 而不是 subprocess 调 l1_fetch_urls.py：后者要起 Playwright 渲染整页，
    台账只需要几个 head 字段，没必要为一次 add 拉起浏览器。
    """
    scripts = Path("C:/Users/Administrator/.workbuddy/skills/wechat-article-collector/scripts")
    if not scripts.exists():
        return {}
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    try:
        from extract import extract_article  # noqa: PLC0415 - 延迟导入，缺依赖不影响其它功能
    except Exception as exc:  # bs4/lxml 缺失或对方仓库结构变了
        log("warn", "ledger.extract_unavailable", error=str(exc))
        return {}
    try:
        data = extract_article(html, url)
    except Exception as exc:
        log("warn", "ledger.extract_failed", url=url, error=str(exc))
        return {}
    return {
        "account": str(data.get("account") or "").strip(),
        "title": str(data.get("title") or "").strip(),
        "publish_time": str(data.get("publish_time") or "").strip(),
        "digest": str(data.get("digest") or "").strip(),
    }


def _extract_by_regex(html: str) -> dict:
    """兜底解析：只认老式 `var nickname/msg_title/ct/msg_desc` 写法。

    这是"能拿多少算多少"的降级路径 —— 2026 版页面改用压缩变量名时这里会全军覆没，
    那就如实留空，绝不拿占位符瞎填（错数据比空数据更有害）。
    """
    return {
        "account": _js_var_regex(html, "nickname").strip(),
        "title": _js_var_regex(html, "msg_title").strip(),
        "publish_time": _epoch_to_iso(_js_var_regex(html, "ct")),
        "digest": _js_var_regex(html, "msg_desc").strip(),
    }


def _fetch_timeout() -> int:
    """单篇抓取超时；允许用 UIAC_LEDGER_TIMEOUT 调小（批量记账时嫌慢）。"""
    raw = str(os.environ.get("UIAC_LEDGER_TIMEOUT", "") or "").strip()
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    return DEFAULT_TIMEOUT


def fetch_meta(url: str) -> dict:
    """抓文章页元信息：{account, title, publish_time, digest}；失败全部留空。

    永不抛异常 —— 台账的核心价值是"链接先记下来"，抓不到元信息只是字段少一点，
    不能让一条 add 因为网络抖动整个失败。
    """
    if not url:
        return {}
    try:
        html = _fetch_html(url, timeout=_fetch_timeout())
    except Exception as exc:
        log("warn", "ledger.fetch_failed", url=url, error=str(exc))
        return {}
    meta = _extract_by_collector(html, url)
    if not (meta.get("title") and meta.get("account")):
        # 解析器认不出时用正则补/兜底；两边都空就留空
        fallback = _extract_by_regex(html)
        for key, value in fallback.items():
            if not meta.get(key) and value:
                meta[key] = value
    if not meta.get("title"):
        log("warn", "ledger.meta_empty", url=url)
    return meta


# ------------------------------------------------------------------ 写入
def append_record(rec: dict) -> dict:
    """写入一条记录并返回落盘后的完整行（含 序号 / 采集时间 / 信息类型）。

    去重与更新规则见模块 docstring；rec 可含 source/account/title/url/profile_url/
    tags/note，另支持 publish_time、digest、no_fetch（True 时不联网抓元信息）。
    """
    rec = dict(rec or {})
    url = _field(rec, "url", "文章链接")
    profile = _field(rec, "profile_url", "profile_ext网址")

    if not url and not profile:
        raise ValueError("append_record 至少需要 url 或 profile_url")

    title = _field(rec, "title", "文章标题")
    account = _field(rec, "account", "公众号名称")
    digest = _field(rec, "digest", "摘要")

    # 只在缺字段时才联网：已经手工给了标题+公众号名就不该再发一次请求
    if url and not rec.get("no_fetch") and not (title and account):
        try:
            meta = fetch_meta(url) or {}
        except Exception as exc:  # 注入的抓取桩/网络层异常一律降级为"抓不到"
            log("warn", "ledger.fetch_error", url=url, error=str(exc))
            meta = {}
        title = title or meta.get("title", "")
        account = account or meta.get("account", "")
        digest = digest or meta.get("digest", "")
        rec.setdefault("publish_time", meta.get("publish_time", ""))

    manual = split_tags(rec.get("tags") or rec.get("信息类型"))
    auto = classify(title, digest)
    tags_cell = format_tags(merge_tags(manual, auto))

    publish_time = _field(rec, "publish_time", "发布时间")
    note_core = _field(rec, "note", "备注")
    source = _field(rec, "source", "来源渠道") or DEFAULT_SOURCE

    rows = load()
    target = None
    merge_by = ""

    if profile:
        for row in rows:
            if str(row.get("profile_ext网址") or "").strip() == profile:
                target, merge_by = row, "profile_ext"
                break
    if target is None and url:
        for row in rows:
            if str(row.get("文章链接") or "").strip() == url:
                target, merge_by = row, "url"
                break

    if target is not None:
        old_core, siblings = parse_remark(target.get("备注", ""))
        # 新值非空才覆盖，避免第二次 add 只带链接时把已经抓到的好数据擦掉
        if title:
            target["文章标题"] = title
        if publish_time:
            target["发布时间"] = publish_time
        if profile and not str(target.get("profile_ext网址") or "").strip():
            target["profile_ext网址"] = profile
        if account and not str(target.get("公众号名称") or "").strip():
            target["公众号名称"] = account
        if tags_cell and tags_cell != FALLBACK_TAG:
            target["信息类型"] = tags_cell
        elif not str(target.get("信息类型") or "").strip():
            target["信息类型"] = tags_cell

        # 同号文章：其它文章的链接记进备注，不覆盖本行已有的"文章链接"
        original = str(target.get("文章链接") or "").strip()
        if url and url != original and url not in siblings:
            siblings.append(url)
        target["备注"] = build_remark(note_core or old_core, siblings)
        _write_rows(rows)
        log("info", "ledger.merged", key=record_key(rec), by=merge_by,
            seq=target.get("序号"), url=url)
        return dict(target)

    seq = max((int(r.get("序号") or 0) for r in rows), default=0) + 1
    row = {
        "序号": seq,
        "采集时间": _field(rec, "采集时间") or _now_utc(),
        "来源渠道": source,
        "公众号名称": account,
        "文章标题": title,
        "发布时间": publish_time,
        "文章链接": url,
        "profile_ext网址": profile,
        "信息类型": tags_cell,
        "备注": build_remark(note_core, []),
    }
    rows.append(row)
    _write_rows(rows)
    log("info", "ledger.appended", key=record_key(rec), seq=seq, url=url, tags=tags_cell)
    return dict(row)


# ------------------------------------------------------------------ 导出
def _md_cell(value) -> str:
    """把单元格内容塞进 Markdown 表格：竖线要转义，换行转 <br>（表格里不能真换行）。"""
    text = str(value if value is not None else "")
    return text.replace("|", "\\|").replace("\r", "").replace("\n", "<br>").strip()


def render_markdown(rows: list[dict]) -> str:
    """生成人可读台账：标题 + 标签分布统计 + 表格。"""
    stamp = _now_utc()
    counts: dict[str, int] = {}
    for row in rows:
        for tag in parse_tags_cell(row.get("信息类型", "")):
            counts[tag] = counts.get(tag, 0) + 1

    lines = [
        "# 文章采集台账",
        "",
        "> 由 `scripts/ledger.py` 生成，请勿手工编辑（改动会被下一次 export 覆盖）。",
        f"> 数据源：`{_csv_path().name}`　行数：{len(rows)}　生成时间：{stamp}",
        "",
        "## 标签分布",
        "",
    ]
    if counts:
        # 按固定标签体系顺序输出，新增标签排最后，保证历次报表观感一致
        ordered = [t for t in TAGS if t in counts] + [t for t in counts if t not in TAGS]
        lines += ["| 信息类型 | 篇数 |", "| --- | --- |"]
        lines += [f"| {tag} | {counts[tag]} |" for tag in ordered]
    else:
        lines.append("（暂无记录）")

    lines += ["", "## 台账明细", ""]
    if rows:
        lines.append("| " + " | ".join(COLUMNS) + " |")
        lines.append("| " + " | ".join("---" for _ in COLUMNS) + " |")
        for row in rows:
            lines.append("| " + " | ".join(_md_cell(row.get(col, "")) for col in COLUMNS) + " |")
    else:
        lines.append("（暂无记录）")
    lines.append("")
    return "\n".join(lines)


def export_markdown() -> Path:
    """只重新生成 md（数据仍是 CSV），返回 md 路径。"""
    rows = load()
    path = _md_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(render_markdown(rows), encoding="utf-8")
    os.replace(tmp, path)
    log("info", "ledger.exported", path=str(path), rows=len(rows))
    return path


# ------------------------------------------------------------------ CLI
def cmd_add(args) -> int:
    rec = {
        "url": args.url,
        "profile_url": args.profile_url or "",
        "account": args.account or "",
        "title": args.title or "",
        "tags": args.tags or "",
        "note": args.note or "",
        "source": args.source or DEFAULT_SOURCE,
    }
    if args.no_fetch:
        rec["no_fetch"] = True
    row = append_record(rec)
    export_markdown()
    print(json.dumps(row, ensure_ascii=False, indent=2))
    return 0


def cmd_export(args) -> int:
    path = export_markdown()
    print(str(path))
    return 0


def cmd_list(args) -> int:
    rows = load()
    if args.tag:
        # 子串匹配而不是精确等于：用户常拿"添加剂"筛出"宠物食品、添加剂"这类组合行
        rows = [r for r in rows if args.tag in str(r.get("信息类型") or "")]
    if args.limit:
        rows = rows[: args.limit]
    for row in rows:
        print("\t".join(
            str(row.get(col, "")) for col in
            ("序号", "采集时间", "公众号名称", "文章标题", "信息类型", "文章链接")
        ))
    return 0


def cmd_tags(args) -> int:
    for tag, keywords in TAGS.items():
        print(f"{tag}\t{'、'.join(keywords)}")
    print(f"{FALLBACK_TAG}\t（以上标签全部未命中时的兜底）")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ledger.py",
        description="文章采集台账：记录文章链接、profile_ext 网址、来源公众号与信息类型标签。",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="新增/合并一条采集记录")
    add.add_argument("--url", required=True, help="文章链接 https://mp.weixin.qq.com/s/...")
    add.add_argument("--profile-url", default="", help="「1.获取公众号id」得到的 profile_ext 链接")
    add.add_argument("--account", default="", help="公众号名称（缺省自动抓取）")
    add.add_argument("--title", default="", help="文章标题（缺省自动抓取）")
    add.add_argument("--tags", default="", help="手工标签，逗号或顿号分隔，与自动标签合并")
    add.add_argument("--note", default="", help="备注")
    add.add_argument("--source", default=DEFAULT_SOURCE, help=f"来源渠道（默认 {DEFAULT_SOURCE}）")
    add.add_argument("--no-fetch", action="store_true", help="不联网抓取公众号名称/标题")
    add.set_defaults(func=cmd_add)

    exp = sub.add_parser("export", help="只重新生成 docs/favorites-ledger.md")
    exp.set_defaults(func=cmd_export)

    lst = sub.add_parser("list", help="按标签列出记录")
    lst.add_argument("--tag", default="", help="信息类型过滤（子串匹配）")
    lst.add_argument("--limit", type=int, default=20, help="最多显示条数（默认 20，0 表示不限）")
    lst.set_defaults(func=cmd_list)

    tags = sub.add_parser("tags", help="打印标签体系与命中关键词")
    tags.set_defaults(func=cmd_tags)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
