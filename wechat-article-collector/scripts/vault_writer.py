#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B4 vault 双写共享模块（从 sync_to_vault.py 迁出）。

设计要点：
- 笔记 frontmatter + 章节 + article_id 幂等键 **逐字复用** import-wechat.py 的 note_text 契约，
  保证 vault 内格式一致、能被 agent-orchestrator 的 ingest / claim-extract 正确消费。
- 分类结论**优先复用**调用方已算好的字段（write_to_library.py 的 B3 步骤已写回
  topic_l1/l2/conf/source/basis），不重算；仅当记录缺分类且传入 ruleset 时才 classify。
- 离域(tier None) 与 未归类(l1/l2 空) 不写库，仅记日志（与云端一致：离域不入智库）。
- 幂等：article_id = local-<mpid>-<record_id[:16]>；同 doc_id16 已存在则跳过。
- 改 classification.json 前先备份（与 import-wechat.py 同一审慎做法）。
- 本模块是「纯副作用」：apply=False 只预览不写文件；apply=True 才落盘。
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import random
import re
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 复用本技能的分类内核（可选；仅当记录缺分类且传入 ruleset 时用于补充分类）
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import classify as classify_mod  # noqa: E402

DEFAULT_TAXONOMY = str(SCRIPT_DIR.parent / "references" / "classify" / "taxonomy.json")
MOC = "MOC--宠物食品知识分类"
CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
BAD_CHARS = re.compile(r'[\\/:*?"<>|&#%\r\n\t]')

# 与 import-wechat.py 完全一致的适用性映射（保证 vault 内枚举一致）
APPLICABILITY = {"A": "direct", "B": "direct", "C": "direct", "D": "direct",
                 "F": "direct", "H": "transferable", "E": "transferable", "G": "direct"}


# ----------------------------------------------------------------- 契约复用
def load_idx(tax_path: str) -> dict:
    """读 taxonomy，只构建 {code: {name, l2:{code:name}}}，用于 L1/L2 名称查表。"""
    raw = json.load(open(tax_path, encoding="utf-8"))
    idx: dict = {}
    for l1 in raw["levels"]:
        idx[l1["code"]] = {"name": l1["name"],
                           "l2": {x["code"]: x["name"] for x in l1["l2"]}}
    return idx


def ulid() -> str:
    ts = int(datetime.now(timezone.utc).timestamp() * 1000)
    head = ""
    for _ in range(10):
        head = CROCKFORD[ts % 32] + head
        ts //= 32
    return "kb-" + head + "".join(random.choice(CROCKFORD) for _ in range(16))


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def slug(text: str, limit: int = 28) -> str:
    s = BAD_CHARS.sub("", text or "").strip()
    s = re.sub(r"\s+", "", s)
    return s[:limit] or "untitled"


def yq(text) -> str:
    return str(text).replace("\\", "\\\\").replace('"', '\\"')


def plain(body: str) -> str:
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", body or "")
    t = re.sub(r"^#{1,6}\s*", "", t, flags=re.M)
    t = re.sub(r"[*_`>]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def decode_mpid(account_id: str) -> str:
    """WeChat account_id 是纯数字串的 base64；解码出数字 mpid 用于 article_id。失败回退 '0'。"""
    if not account_id:
        return "0"
    try:
        dec = base64.b64decode(account_id + "=" * (-len(account_id) % 4)).decode("ascii", "ignore")
        if dec.isdigit():
            return dec
    except Exception:
        pass
    return "0"


# ----------------------------------------------------------------- HTML -> MD
def resolve_body(rec: dict, in_path: str) -> str | None:
    br = rec.get("body_ref") or ""
    if not br:
        return None
    p = Path(br)
    if p.is_absolute() and p.exists():
        return str(p)
    for base in (Path(in_path).resolve().parent, SCRIPT_DIR, SCRIPT_DIR.parent):
        cand = base / br
        if cand.exists():
            return str(cand)
    return None


def html_to_md(html_path: str) -> str:
    """把微信文章 HTML(#js_content 优先) 转成轻量 Markdown：段落/标题/列表/图片/引用。"""
    from bs4 import BeautifulSoup  # 延迟导入：默认环境已装 bs4 + lxml
    raw = Path(html_path).read_bytes()
    text = None
    for enc in ("utf-8", "gbk", "utf-8-sig"):
        try:
            text = raw.decode(enc)
            break
        except Exception:
            continue
    if text is None:
        text = raw.decode("utf-8", "replace")
    soup = BeautifulSoup(text, "lxml")
    root = soup.select_one("#js_content") or soup.body or soup
    out: list[str] = []
    for el in root.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "ul", "ol",
                             "blockquote", "img", "br", "section", "strong", "em"]):
        tag = el.name
        if tag == "br":
            out.append("")
        elif tag == "img":
            alt = el.get("alt") or ""
            src = el.get("data-src") or el.get("src") or ""
            if src:
                out.append("![%s](%s)" % (yq(alt), src))
        elif tag in ("ul", "ol"):
            for li in el.find_all("li", recursive=False):
                out.append("- " + li.get_text(" ", strip=True))
            out.append("")
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            lvl = int(tag[1])
            out.append("#" * lvl + " " + el.get_text(" ", strip=True))
            out.append("")
        elif tag == "blockquote":
            out.append("> " + el.get_text(" ", strip=True))
            out.append("")
        elif tag in ("strong", "em"):
            continue
        else:
            txt = el.get_text(" ", strip=True)
            if txt:
                out.append(txt)
                out.append("")
    return "\n".join(out).strip()


# ----------------------------------------------------------------- note_text 契约复用
def build_note(rec: dict, l1: str, l2: str, conf: float, basis: str, idx: dict,
               note_id: str, created: str, now: str, fname: str, status: str, body_md: str) -> str:
    l1_name, l2_name = idx[l1]["name"], idx[l1]["l2"][l2]
    title = rec.get("title") or ""
    excerpt = plain(body_md)[:220]
    url = rec.get("url") or ""
    account = rec.get("account") or ""
    pub = rec.get("publish_time") or rec.get("collected_at") or ""
    images_count = rec.get("images_count") or 0
    word_count = rec.get("word_count") or len(body_md)
    mpid = decode_mpid(rec.get("account_id"))
    doc_id = re.sub(r"[^A-Za-z0-9]", "", rec.get("record_id") or note_id)
    article_id = "local-%s-%s" % (mpid, doc_id[:16])
    refresh_due = iso(datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=180))
    head = [
        "---",
        'id: "%s"' % note_id,
        'title: "%s"' % yq(title),
        "type: source",
        "status: %s" % status,
        "origin: agent",
        "confidence: %s" % conf,
        'created: "%s"' % created,
        'modified: "%s"' % now,
        "source_type: web",
        'source: "%s"' % url,
        'canonicalUrl: "%s"' % url,
        'article_id: "%s"' % article_id,
        'mp_id: "%s"' % mpid,
        'account: "%s"' % yq(account),
        "applicability: %s" % APPLICABILITY.get(l1, "unknown"),
        'publish_at: "%s"' % pub,
        'link_local: "%s"' % fname,
        'link_original: "%s"' % url,
        'x: "%s"' % yq(excerpt),
        "x_src: extract",
        'locator: "%s"' % url,
        "authority: secondary",
        'independence_key: "%s"' % yq(account),
        'retrieved: "%s"' % now,
        'refresh_due: "%s"' % refresh_due,
        "review_state: %s" % ("auto-approved" if status == "approved" else "unreviewed"),
        'linked_pages: ["40_Maps/%s.md"]' % MOC,
        'author: ["%s"]' % yq(account),
        'topics: ["%s", "%s"]' % (l1_name, l2_name),
        'tags: ["%s/%s"]' % (l1_name, l2_name),
        'related: ["[[%s]]"]' % MOC,
        'cssclasses: ["kb-source"]',
        "word_count: %s" % word_count,
        "---",
        "",
        "%% 本笔记由 wechat-article-collector 同步自公众号采集（origin=agent）。"
        "全文在 `## 全文` 小节，原样保留。",
        "%% 主张请写进「要点」小节（顶格 bullet）；「全文」小节里的列表不参与主张抽取。",
        "",
        "# %s" % title,
        "",
        "## 原文引证",
        "",
        "- 公众号：%s" % account,
        "- 发布时间：%s" % pub,
        "- 原文链接：%s" % url,
        "- 正文字数：%s 字 / 图片 %s 张" % (word_count, images_count),
        "- 正文开头：%s%s" % (excerpt, "…" if len(plain(body_md)) > 220 else ""),
        "",
        "## 归类",
        "",
        "- 一级：%s（%s）" % (l1_name, l1),
        "- 二级：%s（%s）" % (l2_name, l2),
        "- 适用性：%s" % APPLICABILITY.get(l1, "unknown"),
        "- 置信度：%s" % conf,
        "- 归类依据：%s" % basis,
        "",
        "## 全文",
        "",
    ]
    body = body_md.rstrip()
    body_head, _, body_rest = body.partition("\n")
    if body_head.lstrip().startswith("#") and body_head.lstrip("#").strip() == title.strip():
        body = body_rest.lstrip("\n")
    return "\n".join(head) + body + "\n\n相关：[[" + MOC + "]]\n"


# ----------------------------------------------------------------- 分类结论派生
def derive_classification(rec: dict, ruleset, threshold: float):
    """返回 (l1,l2,conf,basis,src,tier,off_domain)。

    - 记录已带 topic_l1（B3 已分类）→ 直接复用，不重算；tier 按 source 推（auto=1/其他=2）。
    - 记录缺分类且传入 ruleset → 调用 classify_article 补充。
    - 两者皆无 → 返回 None（调用方跳过并告警）。
    """
    l1 = rec.get("topic_l1")
    if l1:
        src = rec.get("classify_source") or "auto"
        tier = 1 if src == "auto" else 2
        return (l1, rec.get("topic_l2"), float(rec.get("classify_conf") or 0.85),
                rec.get("classify_basis") or "", src, tier, None)
    if not ruleset:
        return None
    res = classify_mod.classify_article(rec, ruleset, threshold)
    return (res["l1"], res["l2"], res["confidence"], res["basis"],
            res["classify_source"], res["tier"], res["off_domain"])


# ----------------------------------------------------------------- 主流程
def sync(records: list[dict], vault_root: str, taxonomy_path: str = DEFAULT_TAXONOMY,
         apply: bool = True, in_path: str = "", ruleset=None, threshold: float = 0.85,
         source_tool: str = "vault_writer") -> tuple[int, int, int]:
    """把一批记录双写到本地 vault（20_Sources/web + classification.json）。

    参数：
      records      : 采集记录列表（可已带 B3 分类，或需本模块 classify）
      vault_root   : vault 根目录
      taxonomy_path: taxonomy.json（L1/L2 名称查表）
      apply        : True=真实落盘；False=仅预览
      in_path      : 输入 JSONL 路径（用于相对解析 body_ref）
      ruleset      : 分类规则集（仅当记录缺分类时才用）
      source_tool : 写入 classification.json 的 source_tool 标记
    返回：(ok, skip, off_domain) 计数。
    """
    idx = load_idx(taxonomy_path)
    SRC = os.path.join(vault_root, "20_Sources", "web")
    CLS = os.path.join(vault_root, "90_System", "classification", "article-classification.json")

    # 幂等索引：已有笔记(local- 前缀) + 已有 classification.json 条目
    id_index: set[str] = set()
    if os.path.isdir(SRC):
        for name in os.listdir(SRC):
            if not name.endswith(".md"):
                continue
            try:
                h = open(os.path.join(SRC, name), encoding="utf-8").read(1500)
            except OSError:
                continue
            m = re.search(r'article_id: "local-\d+-([0-9a-f]{16})"', h)
            if m:
                id_index.add(m.group(1))
    payload = json.load(open(CLS, encoding="utf-8")) if os.path.exists(CLS) else {"_meta": {}, "items": []}
    known_ids = {it.get("article_id") for it in payload.get("items", [])}
    known_ids |= id_index

    written, skipped, offdom = [], [], []
    now = iso(datetime.now(timezone.utc).replace(microsecond=0))
    for rec in records:
        cls = derive_classification(rec, ruleset, threshold)
        if cls is None:
            skipped.append((rec.get("title"), "无可分类结论(缺 ruleset)"))
            print("[vault] 跳过(无可分类结论): %s" % ((rec.get("title") or "")[:30]), flush=True)
            continue
        l1, l2, conf, basis, src, tier, offterm = cls
        if tier is None:
            offdom.append((rec.get("title"), offterm))
            print("[vault] 离域跳过: %s ← %s" % ((rec.get("title") or "")[:30], offterm), flush=True)
            continue
        if not l1 or not l2:
            skipped.append((rec.get("title"), "未归类(l1/l2 空)"))
            print("[vault] 未归类跳过: %s" % ((rec.get("title") or "")[:30]), flush=True)
            continue
        doc_alnum = re.sub(r"[^A-Za-z0-9]", "", rec.get("record_id") or "")
        doc16 = doc_alnum[:16]
        if doc16 in known_ids:
            skipped.append((rec.get("title"), "已存在"))
            continue
        bp = resolve_body(rec, in_path)
        body_md = html_to_md(bp) if bp else (rec.get("digest") or "")
        if not body_md:
            body_md = rec.get("digest") or "(正文缺失)"
        status = "approved" if src == "auto" else "needs-review"
        date = (rec.get("publish_time") or rec.get("collected_at") or now)[:10]
        fname = "%s-%s-%s.md" % (date, slug(rec.get("title", "")), doc_alnum[-8:])
        note_id = ulid()
        text = build_note(rec, l1, l2, conf, basis, idx, note_id, now, now, fname, status, body_md)
        if not apply:
            written.append((fname, doc16, rec.get("title"), l1, l2, src))
            continue
        os.makedirs(SRC, exist_ok=True)
        with open(os.path.join(SRC, fname), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        payload["items"].append({
            "article_id": "local-%s-%s" % (decode_mpid(rec.get("account_id")), doc16),
            "title": rec.get("title"), "account": rec.get("account"), "url": rec.get("url"),
            "publish_at": rec.get("publish_time") or rec.get("collected_at"),
            "l1": l1, "l1_name": idx[l1]["name"],
            "l2": l2, "l2_name": idx[l1]["l2"][l2],
            "path": "%s/%s" % (idx[l1]["name"], idx[l1]["l2"][l2]),
            "applicability": APPLICABILITY.get(l1, "unknown"),
            "confidence": conf, "basis": basis,
            "note": "20_Sources/web/" + fname,
            "source_tool": source_tool,
        })
        written.append((fname, doc16, rec.get("title"), l1, l2, src))

    if apply and written:
        if os.path.exists(CLS):
            shutil.copy2(CLS, CLS + ".bak-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"))
        payload.setdefault("_meta", {})
        payload["_meta"]["wechat_collector_sync"] = {
            "tool": source_tool,
            "at": iso(datetime.now(timezone.utc)), "count": len(written),
        }
        with open(CLS, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1)

    mode = "APPLIED" if apply else "DRY-RUN"
    print("== B4 vault_writer %s ==" % mode)
    print("写/将写 %d 篇；离域跳过 %d；未归类/已存在跳过 %d" % (len(written), len(offdom), len(skipped)), flush=True)
    for f, d, t, l1, l2, s in written:
        print("   + %s  [%s/%s %s] %s" % (f, l1, l2, s, (t or "")[:30]), flush=True)
    for t, why in skipped:
        print("   - 跳过(%s): %s" % (why, (t or "")[:30]), flush=True)
    for t, term in offdom:
        print("   x 离域(%s): %s" % (term, (t or "")[:30]), flush=True)
    return len(written), len(skipped), len(offdom)


# ----------------------------------------------------------------- 独立入口（薄壳，保留回填能力）
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="采集记录 -> 铭衍·元典 本地 vault 双写桥")
    ap.add_argument("--in", dest="in_path", required=True, help="采集 JSONL（含 record_id/url/body_ref 等）")
    ap.add_argument("--vault", default=r"D:\workbuddy重做系统后版本\2026-10-16-21-12-03\vault",
                    help="铭衍·元典 本地 vault 根目录")
    ap.add_argument("--taxonomy", default=DEFAULT_TAXONOMY, help="taxonomy.json（L1/L2 名称查表）")
    ap.add_argument("--dry-run", action="store_true", help="仅预览，不写文件")
    ap.add_argument("--apply", action="store_true", help="真实写入（默认仅 dry-run）")
    args = ap.parse_args(argv)

    ruleset = classify_mod.load_rules()
    records = [json.loads(l) for l in open(args.in_path, encoding="utf-8") if l.strip()]
    sync(records, args.vault, args.taxonomy, apply=bool(args.apply),
         in_path=args.in_path, ruleset=ruleset, source_tool="wechat-article-collector/sync_to_vault.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
