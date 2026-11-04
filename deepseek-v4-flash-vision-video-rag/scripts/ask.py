"""ask.py —— 基于视频视觉索引回答用户提问。

流程（常规 2 次调用；触发微观层时 +1 次）：
1. 本地粗筛：问题分词 × 段卡片 TF-IDF → 候选段 top10（毫秒级、零费用）
2. 视觉精排（关推理）：候选段代表帧+摘要 → 选 top3 段
3. 深读（开推理，max_tokens=32768——实测 reasoning 会吃预算，8192 会返回空）：
   选中段的全部宏观帧 + OCR 文字 → 带 [MM:SS] 时间戳引用的回答
4. 微观层（可选，视频特有）：问题涉及快速动作或命中高运动窗口时，
   ffmpeg 抽 12fps 中心裁切 2x 放大 + 1 张全图锚点（防裁切丢上下文）→ 追加分析
5. 回显：命中时刻关键帧 + ffmpeg 切可播放 mp4 片段 + 自包含 HTML 预览
   （答案 + 关键帧 + base64 内嵌 <video>，双击浏览器直接播放）

用法：
  python ask.py <video> "问题" [--top 3] [--cands 10]
                [--micro MM:SS-MM:SS] [--no-micro] [--no-media]
"""
import argparse
import base64
import hashlib
import html
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

from ds_client import DSClient, ChatError

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SKILL_DIR = Path(__file__).resolve().parents[1]
CACHE_ROOT = SKILL_DIR / ".cache"
OUT_DIR = Path("video-vision-out")
MICRO_FPS = 12
MICRO_HALF_WINDOW = 1.5  # 微观窗口 ±1.5s（best practice 实测）
CLIP_PAD = 5             # 回显片段前后各 5s
MAX_CLIPS = 3            # HTML 内嵌片段上限（控制体积）

STOP_TERMS = {"什么", "怎么", "哪些", "如何", "为什么", "这个", "那个", "请问", "告诉",
              "一下", "视频", "片段", "画面", "镜头", "里面", "出现", "发生", "时候",
              "时间", "时刻", "介绍", "描述", "the", "a", "an", "of", "in", "is",
              "what", "how", "which", "and", "to"}

ACTION_WORDS = {"瞄准", "准星", "枪", "开枪", "击杀", "击倒", "甩", "瞬间", "快速",
                "动作", "动作细节", "轨迹", "招式", "打斗", "闪避", "落点", "细节"}

RERANK_SYSTEM = """你是视频问答的片段筛选器。用户提出一个问题，你会看到若干候选时间段（如 [00:00-00:30]）的摘要和该段中间时刻的画面截图。
请选出最能用于回答该问题的时间段，最多选 {k} 个，按相关性从高到低排列。
不要为了凑数而选无关片段；如果一个都不相关，返回空列表。
输出 JSON：{{"segments": [{{"start": 0.0, "reason": "10字以内理由"}}]}}，start 为段起始秒数，只输出 JSON。"""

DEEP_SYSTEM = """你是深度观看助手。你会看到与用户问题相关的视频帧序列：按时间顺序排列，每帧前有 [t=Xs] 标签，相邻帧间隔约 {interval:.1f} 秒（这是抽样帧，不是全部画面）。
请把帧序列当作一段连续视频来理解，认真分析画面中的人物、动作、物体、场景和可见文字。
回答要求：
1. 用中文回答，准确、具体，先给结论再按时间或要点展开
2. 每个关键论点后标注来源时刻，格式如 [00:07]（分:秒）
3. 时刻只能引用你看到的帧时刻附近，不要编造没见过的画面
4. 若帧内容不足以回答问题，明确说明，不要脑补
5. 控制在 600 字以内"""

MICRO_SYSTEM = """你是视频微观动作分析助手。你会看到一个短时间窗口内以 {fps}fps 高密度抽取的画面：开头有 1 张全图作为上下文锚点，其余是屏幕中心区域放大画面，每帧前有 [t=Xs] 标签。
请专注分析这个窗口内的快速动作与细节（动作过程、先后顺序、位置变化）。
输出要点式中文分析，每个论点标注 [MM:SS] 时刻，300 字以内。不要编造看不清的内容。"""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_index(video: Path):
    sha = sha256_file(video)
    index_path = CACHE_ROOT / sha[:16] / "index.json"
    if not index_path.exists():
        sys.exit(f"[error] 未找到索引，请先运行: python ingest.py \"{video}\"")
    return json.loads(index_path.read_text("utf-8")), index_path.parent


def fmt_ts(sec: float) -> str:
    sec = max(0, int(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _ts_to_sec(ts_str: str) -> int:
    parts_ = [int(v) for v in ts_str.split(":")]
    if len(parts_) == 3:
        h, m, s = parts_
    else:
        h, m, s = 0, parts_[0], parts_[1]
    return h * 3600 + m * 60 + s


_TS_RANGE = r"\[(\d{1,2}:\d{2}(?::\d{2})?)\s*[-–~]\s*(\d{1,2}:\d{2}(?::\d{2})?)\]"
_TS_ONE = r"\[(\d{1,2}:\d{2}(?::\d{2})?)\]"


def parse_ts(text: str):
    """解析 [MM:SS] / [H:MM:SS] / [MM:SS-MM:SS] 区间 / 第N秒 引用，返回秒列表。"""
    secs = []
    for a, b in re.findall(_TS_RANGE, text):
        secs.extend((_ts_to_sec(a), _ts_to_sec(b)))
    for t in re.findall(_TS_ONE, text):
        secs.append(_ts_to_sec(t))
    for s in re.findall(r"第\s*(\d+(?:\.\d+)?)\s*秒", text):
        secs.append(float(s))
    return sorted(set(round(x, 1) for x in secs))


def terms_of(question: str):
    terms = set(re.findall(r"[A-Za-z0-9_.]{2,}", question.lower()))
    for run in re.findall(r"[\u4e00-\u9fff]+", question):
        if len(run) == 1:
            terms.add(run)
        else:
            terms.update(run[i:i + 2] for i in range(len(run) - 1))
    return terms - STOP_TERMS


def seg_doc(index, seg):
    """段检索文档：段摘要/关键词×3 + 段内 OCR×2 + 帧摘要×1。"""
    parts = [seg["summary"]] * 3 + seg["keywords"] * 3
    for fi in seg["frame_idx"]:
        f = index["frames"][fi]
        if f["ocr"]:
            parts.append(f["ocr"])
        parts.append(f["summary"])
    return "\n".join(parts)


def score_segments(index, question):
    terms = terms_of(question)
    if not terms:
        return list(range(len(index["segments"])))
    segs = index["segments"]
    docs = [seg_doc(index, s) for s in segs]
    df = {}
    for t in terms:
        df[t] = sum(1 for d in docs if t in d)
    n = len(docs)
    scored = []
    for i, d in enumerate(docs):
        s = 0.0
        for t in terms:
            tf = d.count(t)
            if tf:
                s += math.log(1 + n / df[t]) * min(tf, 8)
        scored.append((i, s))
    scored.sort(key=lambda x: -x[1])
    return [i for i, s in scored if s > 0]


def ensure_files(client: DSClient, cache_dir: Path, files_map: dict, frame_idxs):
    files_json = cache_dir / "files.json"
    changed = False
    for i in frame_idxs:
        fid = files_map.get(str(i))
        if not fid or not client.file_exists(fid):
            png = cache_dir / "frames" / f"f_{i:05d}.jpg"
            files_map[str(i)] = client.upload_image(str(png))
            changed = True
            print(f"[files] re-uploaded frame {i}", flush=True)
    if changed:
        files_json.write_text(json.dumps(files_map, ensure_ascii=False, indent=1), "utf-8")


def mid_frame_idx(seg):
    return seg["frame_idx"][len(seg["frame_idx"]) // 2]


def rerank(client, index, files_map, cand, k, question):
    blocks = []
    for si in cand:
        seg = index["segments"][si]
        blocks.append({"type": "text",
                       "text": f"[{fmt_ts(seg['start'])}-{fmt_ts(seg['end'])}] 摘要：{seg['summary'][:150]}"})
        blocks.append({"type": "file", "file_id": files_map[str(mid_frame_idx(seg))]})
    blocks.append({"type": "text", "text": f"用户问题：{question}\n请选出最多 {k} 个最相关的时间段。"})
    try:
        data, _ = client.chat_json(blocks, system=RERANK_SYSTEM.format(k=k),
                                   thinking=False, max_tokens=600, temperature=0)
    except ChatError as e:
        print(f"[rerank] failed ({e}), falling back to local ranking", flush=True)
        return cand[:k]
    starts = {s["start"] for s in index["segments"]}
    picked = []
    for item in data.get("segments") or []:
        try:
            st = round(float(item["start"]), 2)
            for si in cand:
                if index["segments"][si]["start"] == st and si not in picked:
                    picked.append(si)
                    break
        except (KeyError, TypeError, ValueError):
            continue
    return picked[:k] or cand[:k]


def run_deep(client, index, files_map, picked, question):
    interval = 1 / index["sample_fps"]
    segs = [index["segments"][si] for si in picked]
    idxs = sorted({i for seg in segs for i in seg["frame_idx"]})
    ensure_files(client, index["_cache_dir"], files_map, idxs)
    blocks = []
    for i in idxs:
        blocks.append({"type": "text", "text": f"[t={index['frames'][i]['t']:.1f}s]"})
        blocks.append({"type": "file", "file_id": files_map[str(i)]})
    ocr = "\n".join(f"[{fmt_ts(index['frames'][i]['t'])}] {index['frames'][i]['ocr']}"
                    for i in idxs if index["frames"][i]["ocr"])
    blocks.append({"type": "text", "text": f"可见文字汇总：\n{ocr}\n\n用户问题：{question}"})
    print(f"[ask] 深读 {len(idxs)} 帧（t={index['frames'][idxs[0]]['t']:.0f}s-"
          f"{index['frames'][idxs[-1]]['t']:.0f}s）", flush=True)
    text, finish = client.chat(blocks, system=DEEP_SYSTEM.format(interval=interval),
                               thinking=True, max_tokens=32768, retries=3)
    if finish == "length":
        text += "\n\n（注：回答因长度限制被截断）"
    return text


def micro_extract(video: Path, cache_dir: Path, t0: float, t1: float):
    """抽微观帧：12fps 中心裁切 40% 区域 2x 放大（lanczos）。返回 (jpg路径列表, 时间戳列表)。"""
    out_dir = cache_dir / "micro" / f"{t0:.1f}_{t1:.1f}"
    out_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(out_dir.glob("m_*.jpg"))
    if files:
        return files, [t0 + i / MICRO_FPS for i in range(len(files))]
    r = subprocess.run(
        ["ffmpeg", "-y", "-ss", f"{t0:.2f}", "-i", str(video),
         "-t", f"{t1 - t0:.2f}",
         "-vf", (f"fps={MICRO_FPS},crop=iw*0.4:ih*0.4,"
                 f"scale=iw*2:ih*2:flags=lanczos"),
         "-q:v", "2", "-start_number", "0", str(out_dir / "m_%05d.jpg")],
        capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"micro extract failed: {r.stderr[-200:]}")
    # fps=12 从 -ss 后的 0 点起采样，时间戳换算回视频绝对时间
    files = sorted(out_dir.glob("m_*.jpg"))
    return files, [t0 + i / MICRO_FPS for i in range(len(files))]


def pick_micro_center(index, cited):
    """微观窗口中心：优先选引用时刻中运动强度最高的（交战/快速动作段）。"""
    best_t, best_rank = cited[0], -1
    for t in cited:
        fi = min(round(t * index["sample_fps"]), len(index["frames"]) - 1)
        rank = ("低", "中", "高").index(index["frames"][fi].get("motion", "低"))
        if rank > best_rank:
            best_rank, best_t = rank, t
    return best_t


def run_micro(client, video: Path, cache_dir: Path, files_map, anchor_idx, t_center, duration):
    a = max(0.0, t_center - MICRO_HALF_WINDOW)
    b = min(duration, t_center + MICRO_HALF_WINDOW)
    if b - a < 0.5:
        return None
    print(f"[micro] 窗口 t={a:.1f}s-{b:.1f}s @{MICRO_FPS}fps 中心放大", flush=True)
    files, ts = micro_extract(video, cache_dir, a, b)
    if not files:
        return None
    ensure_files(client, cache_dir, files_map, [anchor_idx])
    blocks = [{"type": "text", "text": f"[t={ts[0]:.1f}s 全图锚点]"}]
    blocks.append({"type": "file", "file_id": files_map[str(anchor_idx)]})
    for p, t in zip(files, ts):
        b64 = base64.b64encode(p.read_bytes()).decode()
        blocks.append({"type": "text", "text": f"[t={t:.2f}s 放大]"})
        blocks.append({"type": "image_url",
                       "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
    try:
        text, _ = client.chat(blocks, system=MICRO_SYSTEM.format(fps=MICRO_FPS),
                              thinking=True, max_tokens=32768, retries=3)
    except ChatError as e:
        print(f"[micro] failed: {e}", flush=True)
        return None
    return text


def cut_clip(video: Path, out_dir: Path, t: float, duration: float, stem: str) -> Path:
    a, b = max(0.0, t - CLIP_PAD), min(duration, t + CLIP_PAD)
    dst = out_dir / f"{stem}_clip{fmt_ts(t).replace(':', '')}.mp4"
    if dst.exists():
        return dst
    r = subprocess.run(
        ["ffmpeg", "-y", "-ss", f"{a:.2f}", "-i", str(video), "-t", f"{b - a:.2f}",
         "-c", "copy", str(dst)], capture_output=True, text=True, timeout=300)
    if r.returncode != 0:  # 关键帧对不齐时降级重编码
        r = subprocess.run(
            ["ffmpeg", "-y", "-ss", f"{a:.2f}", "-i", str(video), "-t", f"{b - a:.2f}",
             "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-c:a", "aac", str(dst)],
            capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            return None
    return dst


def md_inline_to_html(text: str) -> str:
    s = html.escape(text)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"<em>\1</em>", s)
    s = re.sub(r"`([^`\n]+?)`", r"<code>\1</code>", s)
    s = re.sub(r"^[-•]\s+", "• ", s, flags=re.MULTILINE)
    return s


def write_html_preview(video_name, question, answer, keyframes, clips):
    stem = video_name.rsplit(".", 1)[0]
    slug = re.sub(r"[^\w\u4e00-\u9fff]+", "_", question).strip("_")[:24] or "answer"
    head = f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8"><title>{html.escape(question[:60])}</title>
<style>
body{{font-family:system-ui,"Microsoft YaHei",sans-serif;max-width:920px;margin:0 auto;padding:24px;color:#222}}
.q{{font-size:15px;color:#555;margin-bottom:8px}}
.answer{{white-space:pre-wrap;background:#f6f7f9;padding:16px 20px;border-radius:10px;font-size:15px;line-height:1.7}}
.answer code{{background:#e8e8ec;padding:1px 5px;border-radius:3px;font-size:0.9em}}
h2{{margin-top:36px;border-bottom:2px solid #e8e8e8;padding-bottom:6px}}
h3{{color:#666;font-weight:600;margin-bottom:0}}
img{{width:100%;border:1px solid #ddd;border-radius:6px;margin:6px 0 28px}}
video{{width:100%;border:1px solid #ddd;border-radius:6px;margin:6px 0 28px;background:#000}}
</style></head><body>
<h1>{html.escape(video_name)}</h1>
<div class="q">问题：{html.escape(question)}</div>
<div class="answer">{md_inline_to_html(answer)}</div>"""
    parts = [head]
    if clips:
        parts.append("<h2>引用时刻片段（可直接播放）</h2>")
        for t, path in clips:
            b64 = base64.b64encode(path.read_bytes()).decode()
            parts.append(f'<h3>[{fmt_ts(t)}] 前后 {CLIP_PAD}s</h3>'
                         f'<video controls preload="metadata" src="data:video/mp4;base64,{b64}"></video>')
    if keyframes:
        parts.append("<h2>引用时刻关键帧</h2>")
        for t, path in keyframes:
            b64 = base64.b64encode(path.read_bytes()).decode()
            parts.append(f'<h3>[{fmt_ts(t)}]</h3>'
                         f'<img alt="{fmt_ts(t)}" src="data:image/jpeg;base64,{b64}">')
    parts.append("</body></html>")
    out = OUT_DIR / f"{stem}_{slug}.html"
    out.write_text("".join(parts), "utf-8")
    return out


def main():
    ap = argparse.ArgumentParser(description="Ask a question about an indexed video")
    ap.add_argument("video", type=Path)
    ap.add_argument("question")
    ap.add_argument("--top", type=int, default=3, help="精排选出的段数")
    ap.add_argument("--cands", type=int, default=10, help="本地粗筛候选段数")
    ap.add_argument("--micro", type=str, default="", help="强制微观分析窗口，如 00:04-00:07")
    ap.add_argument("--no-micro", action="store_true", help="禁用自动微观层")
    ap.add_argument("--no-media", action="store_true", help="不产出图片/片段/HTML")
    args = ap.parse_args()

    video = args.video.resolve()
    index, cache_dir = load_index(video)
    index["_cache_dir"] = cache_dir
    files_map = json.loads((cache_dir / "files.json").read_text("utf-8"))
    print(f"[ask] {index['video_name']} 索引 {index['frames_indexed']} 帧 @ {index['sample_fps']}fps, "
          f"{len(index['segments'])} 段, 时长 {index['duration']:.0f}s", flush=True)

    ranked = score_segments(index, args.question)[:args.cands]
    if not ranked:
        ranked = list(range(min(args.cands, len(index["segments"]))))
    print(f"[ask] 本地粗筛 top{min(len(ranked), 8)}: "
          f"{[fmt_ts(index['segments'][i]['start']) for i in ranked[:8]]}", flush=True)

    client = DSClient()
    need = sorted({mid_frame_idx(index["segments"][i]) for i in ranked})
    ensure_files(client, cache_dir, files_map, need)

    picked = rerank(client, index, files_map, ranked, args.top, args.question)
    print(f"[ask] 视觉精排选中: {[fmt_ts(index['segments'][i]['start']) + '-' + fmt_ts(index['segments'][i]['end']) for i in picked]}", flush=True)

    answer = run_deep(client, index, files_map, picked, args.question)

    # ---- 微观层（自动触发：动作类问题且深读有引用；或 --micro 显式指定） ----
    cited = parse_ts(answer)
    micro_text = None
    if not args.no_micro:
        window_center = None
        if args.micro:
            m = re.match(r"(\d{1,2}:\d{2}(?::\d{2})?)-(\d{1,2}:\d{2}(?::\d{2})?)", args.micro)
            if m:
                def to_sec(x):
                    parts_ = [int(v) for v in x.split(":")]
                    return parts_[0] * 3600 + parts_[1] * 60 + (parts_[2] if len(parts_) > 2 else 0)
                window_center = (to_sec(m.group(1)) + to_sec(m.group(2))) / 2
        elif cited and any(w in args.question for w in ACTION_WORDS):
            window_center = pick_micro_center(index, cited)
        if window_center is not None:
            anchor_idx = min(range(len(index["frames"])),
                             key=lambda i: abs(index["frames"][i]["t"] - window_center))
            micro_text = run_micro(client, video, cache_dir, files_map,
                                   anchor_idx, window_center, index["duration"])
            if micro_text:
                answer = answer + "\n\n**微观细节分析**（高帧率中心放大）：\n" + micro_text
                cited = parse_ts(answer)

    print("\n=== 答案 ===")
    print(answer)

    cited = [t for t in cited if 0 <= t <= index["duration"]]
    print("\n=== 引用时刻 ===")
    print("、".join(fmt_ts(t) for t in cited) if cited else "（回答中无显式时刻引用）")

    if args.no_media or not cited:
        return
    OUT_DIR.mkdir(exist_ok=True)
    stem = index["video_name"].rsplit(".", 1)[0]
    fps = index["sample_fps"]

    keyframes, done_t = [], []
    for t in cited:
        if any(abs(t - d) < 1.0 for d in done_t):
            continue
        done_t.append(t)
        fi = min(round(t * fps), len(index["frames"]) - 1)
        src = cache_dir / "frames" / f"f_{fi:05d}.jpg"
        if src.exists():
            dst = OUT_DIR / f"{stem}_t{fmt_ts(t).replace(':', '')}.jpg"
            shutil.copyfile(src, dst)
            keyframes.append((t, dst))
    clips = []
    for t, _ in keyframes[:MAX_CLIPS]:
        clip = cut_clip(video, OUT_DIR, t, index["duration"], stem)
        if clip:
            clips.append((t, clip))

    print("\n=== 关键帧 ===")
    for t, p in keyframes:
        print(f"[{fmt_ts(t)}] {p.resolve()}")
    print("\n=== 可播放片段 ===")
    for t, p in clips:
        print(f"[{fmt_ts(t)}±{CLIP_PAD}s] {p.resolve()}")
    preview = write_html_preview(index["video_name"], args.question, answer, keyframes, clips)
    print("\n=== 预览（双击浏览器打开：答案 + 片段播放 + 关键帧） ===")
    print(preview.resolve())


if __name__ == "__main__":
    main()
