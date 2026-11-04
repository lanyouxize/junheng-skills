"""ingest.py —— 为 PDF 构建视觉索引（GLM-5.3-Flash 版；每份 PDF 一次，缓存复用）。

与 DeepSeek 版的差异（实测）：GLM 无 Files API，页图以 base64 data URL 内联批量传送；
图片按分辨率计费（约750像素²/token），默认 dpi 从 150 降到 110 控制成本。

流程：
1. PyMuPDF 渲染每页 PNG
2. 抽取每页文本层（零成本，供本地检索）
3. 分批（默认 20 页/请求）把页图内联给视觉模型，reasoning_effort=low + JSON，
   产出每页结构化记录；截断/失败自动对半拆批重试
4. 由页级 headings 派生全书大纲
5. 落盘 .cache/<sha256>/index.json

用法：
  python ingest.py <pdf> [--force] [--limit N] [--batch 20] [--dpi 110] [--clean]
"""
import argparse
import hashlib
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import fitz  # PyMuPDF

from glm_client import GLMClient, ChatError, img_block

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SKILL_DIR = Path(__file__).resolve().parents[1]
CACHE_ROOT = SKILL_DIR / ".cache"
MAX_SIDE_PX = 3600  # 满足 15+ 图/请求时的尺寸约束
PAGE_TYPES = ("封面", "版权", "目录", "序言", "正文", "附录", "参考文献", "索引", "空白", "其他")

INDEX_SYSTEM = """你是一个 PDF 页面索引助手。你会收到一批 PDF 页面图像，每张图像前有一个文本标签标明物理页码（如 [第6页]）。

请对收到的每一页输出一条结构化记录，合并为一个 JSON 对象，格式示例：
{"pages": [{"page": 6, "type": "正文", "headings": [{"level": 1, "text": "§02 它被允许碰什么"}], "summary": "60字以内的中文摘要，概括本页讲了什么", "keywords": ["审批", "权限", "工作区"], "has": {"figure": false, "table": false, "code": false, "formula": false}}]}

字段说明：
- page: 物理页码，必须与图像前的 [第N页] 标签一致
- type: 只能取 封面/版权/目录/序言/正文/附录/参考文献/索引/空白/其他 之一
- headings: 本页正文中出现的标题（含章节号如 §02 或 1.2），level 1 为最高级；目录页和封面页必须为空数组
- summary: 60 字以内中文摘要，写实质内容而不是"本页介绍了..."
- keywords: 3-6 个便于检索的关键词（中文或原文英文术语）
- has: 页面是否包含 插图/表格/代码块/数学公式

必须覆盖收到的每一页，不得遗漏、不得编造未给出的页码。只输出 JSON。"""


def pdf_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def render_pages(doc, out_dir: Path, dpi: int):
    out_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for i, page in enumerate(doc):
        png = out_dir / f"p{i + 1:04d}.png"
        if not png.exists():
            long_side_in = max(page.rect.width, page.rect.height) / 72
            d = max(72, min(dpi, int(MAX_SIDE_PX / long_side_in)))
            page.get_pixmap(dpi=d).save(str(png))
        files.append(png)
    return files


def save_json(path: Path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")


def normalize_record(rec: dict, page: int) -> dict:
    rec["page"] = page
    if rec.get("type") not in PAGE_TYPES:
        rec["type"] = "其他"
    heads = []
    for h in rec.get("headings") or []:
        if isinstance(h, dict) and str(h.get("text", "")).strip():
            try:
                lvl = max(1, min(6, int(h.get("level", 1))))
            except (TypeError, ValueError):
                lvl = 1
            heads.append({"level": lvl, "text": str(h["text"]).strip()[:120]})
    rec["headings"] = heads
    rec["summary"] = str(rec.get("summary", "")).strip()[:200]
    kws = rec.get("keywords") or []
    rec["keywords"] = [str(k).strip()[:40] for k in kws if str(k).strip()][:8]
    has = rec.get("has") or {}
    rec["has"] = {k: bool(has.get(k, False)) for k in ("figure", "table", "code", "formula")}
    return rec


def batch_blocks(pages, cache_dir: Path):
    blocks = []
    for p in pages:
        png = cache_dir / "pages" / f"p{p:04d}.png"
        blocks += img_block(png, f"[第{p}页]")
    blocks.append({"type": "text",
                   "text": f"请输出第{pages[0]}页到第{pages[-1]}页（共{len(pages)}页）每一页的JSON记录。"})
    return blocks


def index_pages(client: GLMClient, pages, cache_dir: Path):
    """索引一组页。截断/解析失败时对半拆批递归；返回 {页码: record}。"""
    if not pages:
        return {}
    try:
        data, finish = client.chat_json(batch_blocks(pages, cache_dir),
                                        system=INDEX_SYSTEM, effort="low", max_tokens=16384)
    except ChatError as e:
        if len(pages) == 1:
            print(f"[index] page {pages[0]} failed: {e}", flush=True)
            return {}
        mid = len(pages) // 2
        return {**index_pages(client, pages[:mid], cache_dir),
                **index_pages(client, pages[mid:], cache_dir)}

    records = {}
    raw = data.get("pages") if isinstance(data, dict) else data
    for r in raw or []:
        try:
            records[int(r["page"])] = normalize_record(r, int(r["page"]))
        except (KeyError, TypeError, ValueError):
            continue

    missing = [p for p in pages if p not in records]
    if finish == "length" and len(pages) > 1:
        mid = len(pages) // 2
        print(f"[index] batch p{pages[0]}-{pages[-1]} truncated, splitting", flush=True)
        records.update(index_pages(client, pages[:mid], cache_dir))
        records.update(index_pages(client, pages[mid:], cache_dir))
    elif missing and len(missing) < len(pages):
        records.update(index_pages(client, missing, cache_dir))
    return records


def build_outline(pages_records):
    outline, seen = [], set()
    for rec in sorted(pages_records, key=lambda r: r["page"]):
        if rec["type"] in ("目录", "封面", "版权", "空白", "索引"):
            continue
        for h in rec["headings"]:
            key = h["text"]
            if key in seen:
                continue
            seen.add(key)
            outline.append({"level": h["level"], "text": key, "page": rec["page"]})
    return outline


def main():
    ap = argparse.ArgumentParser(description="Build vision index for a PDF (GLM)")
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="只索引前 N 页（测试用）")
    ap.add_argument("--batch", type=int, default=20)
    ap.add_argument("--dpi", type=int, default=110, help="渲染分辨率（GLM按分辨率计费，110≈1500tok/页）")
    ap.add_argument("--clean", action="store_true", help="删除该 PDF 的本地缓存后退出")
    args = ap.parse_args()

    pdf = args.pdf.resolve()
    if not pdf.is_file():
        sys.exit(f"PDF not found: {pdf}")

    sha = pdf_sha256(pdf)
    cache_dir = CACHE_ROOT / sha[:16]
    if args.clean:
        if cache_dir.exists():
            for f in cache_dir.glob("*"):
                f.unlink()
            cache_dir.rmdir()
            print(f"[clean] removed {cache_dir}")
        return

    doc = fitz.open(str(pdf))
    total = len(doc)
    n_pages = min(total, args.limit) if args.limit > 0 else total
    index_path = cache_dir / "index.json"

    if index_path.exists() and not args.force:
        try:
            old = json.loads(index_path.read_text("utf-8"))
            if old.get("pages_indexed", 0) >= n_pages:
                print(f"[cache] index exists: {cache_dir}")
                print(f"[cache] {old['pages_indexed']}/{old['total_pages']} pages indexed, use --force to rebuild")
                return
        except json.JSONDecodeError:
            pass

    print(f"[ingest] {pdf.name}: {total} pages, indexing {n_pages}, sha={sha[:16]}, dpi={args.dpi}", flush=True)
    t0 = time.time()

    page_files = render_pages(doc, cache_dir / "pages", args.dpi)[:n_pages]
    texts = [doc[i].get_text() for i in range(n_pages)]
    print(f"[render] {len(page_files)} pages -> {cache_dir / 'pages'} ({time.time() - t0:.0f}s)", flush=True)

    client = GLMClient()
    records = {}
    all_pages = list(range(1, n_pages + 1))
    for i in range(0, n_pages, args.batch):
        chunk = all_pages[i:i + args.batch]
        got = index_pages(client, chunk, cache_dir)
        records.update(got)
        print(f"[index] {min(len(records), i + len(chunk))}/{n_pages} done "
              f"(p{chunk[0]}-p{chunk[-1]}, {time.time() - t0:.0f}s)", flush=True)

    fallback = 0
    for p in all_pages:
        if p not in records:
            fallback += 1
            records[p] = normalize_record(
                {"summary": texts[p - 1][:150], "type": "其他",
                 "keywords": [], "headings": []}, p)
    if fallback:
        print(f"[index] WARNING: {fallback} pages fell back to text-layer-only", flush=True)

    ordered = [records[p] for p in all_pages]
    index = {
        "pdf": str(pdf),
        "pdf_name": pdf.name,
        "sha256": sha,
        "model": client.model,
        "created": datetime.now().isoformat(timespec="seconds"),
        "total_pages": total,
        "pages_indexed": n_pages,
        "partial": n_pages < total,
        "pages": ordered,
        "page_texts": texts,
        "outline": build_outline(ordered),
    }
    save_json(index_path, index)

    types = {}
    for r in ordered:
        types[r["type"]] = types.get(r["type"], 0) + 1
    print(f"[done] {n_pages} pages indexed in {time.time() - t0:.0f}s -> {index_path}", flush=True)
    print(f"[done] page types: {types}", flush=True)
    print(f"[done] outline entries: {len(index['outline'])}", flush=True)


if __name__ == "__main__":
    main()
