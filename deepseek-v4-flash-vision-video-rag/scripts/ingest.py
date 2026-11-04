"""ingest.py —— 为视频构建视觉索引（每份视频只需运行一次，结果缓存复用）。

依据 deepseek-vision 视频输入实测最佳实践：
- 模型"看视频"的唯一正确方式 = 按时间顺序的 JPEG 帧序列（GIF 只解码首帧，不可用）
- 宏观采样：短片段 1fps、长片自动降密度（0.5/0.25/0.1fps），全图直传不预缩放
- 每帧带 [t=Xs] 文本标签，prompt 声明数量/间隔/时间窗，模型才能建立时间轴
- 帧图经 Files API 上传（断点续传），批量 25 帧/请求，关推理 + JSON Output
- 段级卡片（默认 30s/段）由帧卡片本地聚合生成（零成本），供问答粗筛

用法：
  python ingest.py <video> [--fps auto] [--seg 30] [--batch 25] [--workers 6]
                        [--limit-frames N] [--force] [--clean]
"""
import argparse
import concurrent.futures
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from ds_client import DSClient, ChatError

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SKILL_DIR = Path(__file__).resolve().parents[1]
CACHE_ROOT = SKILL_DIR / ".cache"
BATCH_DEFAULT = 25
MAX_SIDE_PX = 3600  # 15+ 图/请求时 API 限制单边 4096px，留余量
MOTIONS = ("低", "中", "高")

INDEX_SYSTEM = """你是一个视频帧索引助手。你会收到按时间顺序排列的视频帧图像，每帧前有一个文本标签标明时刻（如 [t=12.0s]）。

请对收到的每一帧输出一条结构化记录，合并为一个 JSON 对象，格式示例：
{"frames": [{"t": 12.0, "scene": "室内厨房", "summary": "60字以内：画面里有谁、在做什么、关键物体与位置", "keywords": ["Tom", "炸药", "追逐"], "ocr": "画面中可见的文字，无则空字符串", "event": "相对前一帧发生的事件或变化", "motion": "低"}]}

字段说明：
- t: 时刻（秒），必须与图像前的 [t=Xs] 标签一致
- scene: 场景/环境（短语），如"室内厨房""雪地街道""游戏 Dust2"
- summary: 客观描述本帧画面：人物、动作、物体、位置关系
- keywords: 3-6 个便于检索的关键词（人物名/物体/动作/场景）
- ocr: 画面中出现的可见文字（字幕、招牌、HUD、标牌等），没有则 ""
- event: 相对前一帧的变化或事件（如"老鼠把炸药放到猫身边""场景切换"），首帧写画面整体内容
- motion: 低/中/高，表示画面运动剧烈程度（高=剧烈动作/快速运动）

必须覆盖收到的每一帧，不得遗漏、不得编造未给出的时刻。只输出 JSON。"""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ffprobe(path: Path) -> dict:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams",
         str(path)], capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        sys.exit(f"[error] ffprobe failed: {r.stderr[:300]}")
    data = json.loads(r.stdout)
    vstream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    if not vstream:
        sys.exit(f"[error] no video stream: {path}")
    duration = float(data.get("format", {}).get("duration", 0) or 0)
    return {"width": vstream["width"], "height": vstream["height"],
            "duration": duration, "has_audio": any(s.get("codec_type") == "audio"
                                                    for s in data.get("streams", []))}


def auto_fps(duration: float) -> float:
    if duration <= 60:
        return 1.0
    if duration <= 600:
        return 0.5
    if duration <= 1800:
        return 0.25
    return 0.1


def extract_frames(video: Path, out_dir: Path, fps: float, max_side: int):
    """宏观抽帧：全图 JPEG q3；源分辨率超限时才等比缩小。返回文件列表（0 起始索引对齐）。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(out_dir.glob("f_*.jpg"))
    if files:
        return files
    vf = f"fps={fps}"
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height", "-of", "csv=p=0", str(video)],
        capture_output=True, text=True, timeout=60)
    try:
        w, h = (int(x) for x in r.stdout.strip().split(","))
        if max(w, h) > max_side:
            vf += f",scale={max_side}:{max_side}:force_original_aspect_ratio=decrease"
    except ValueError:
        pass
    cmd = ["ffmpeg", "-y", "-i", str(video), "-vf", vf, "-q:v", "3",
           "-start_number", "0", str(out_dir / "f_%05d.jpg")]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if r.returncode != 0:
        sys.exit(f"[error] ffmpeg extract failed: {r.stderr[-300:]}")
    return sorted(out_dir.glob("f_*.jpg"))


def detect_scene_cuts(video: Path) -> list:
    """本地场景切换检测（零 API 成本），返回切换时刻列表（秒）。"""
    r = subprocess.run(
        ["ffmpeg", "-i", str(video), "-vf", "select='gt(scene,0.3)',showinfo", "-f", "null", "-"],
        capture_output=True, text=True, timeout=1800)
    cuts = []
    for line in r.stderr.splitlines():
        if "pts_time:" in line and "showinfo" in line:
            try:
                cuts.append(round(float(line.split("pts_time:")[1].split()[0]), 2))
            except (IndexError, ValueError):
                pass
    return cuts


def save_json(path: Path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")


def upload_all(client: DSClient, frame_files, files_json: Path, workers: int):
    files_map = json.loads(files_json.read_text("utf-8")) if files_json.exists() else {}
    todo = {i: p for i, p in enumerate(frame_files) if str(i) not in files_map}
    if not todo:
        print(f"[upload] all {len(frame_files)} frames already uploaded", flush=True)
        return files_map
    t0 = time.time()
    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(client.upload_image, str(p)): i for i, p in todo.items()}
        for fut in concurrent.futures.as_completed(futs):
            files_map[str(futs[fut])] = fut.result()
            done += 1
            if done % 20 == 0 or done == len(todo):
                save_json(files_json, files_map)
                print(f"[upload] {done}/{len(todo)} ({time.time() - t0:.0f}s)", flush=True)
    return files_map


def normalize_card(rec: dict, t: float) -> dict:
    rec["t"] = round(t, 2)
    rec["scene"] = str(rec.get("scene", "")).strip()[:60]
    rec["summary"] = str(rec.get("summary", "")).strip()[:200]
    kws = rec.get("keywords") or []
    rec["keywords"] = [str(k).strip()[:30] for k in kws if str(k).strip()][:8]
    rec["ocr"] = str(rec.get("ocr", "")).strip()[:200]
    rec["event"] = str(rec.get("event", "")).strip()[:200]
    if rec.get("motion") not in MOTIONS:
        rec["motion"] = "低"
    return rec


def batch_blocks(idxs, ts, files_map, interval):
    blocks = []
    for i in idxs:
        blocks.append({"type": "text", "text": f"[t={ts[i]:.1f}s]"})
        blocks.append({"type": "file", "file_id": files_map[str(i)]})
    blocks.append({"type": "text",
                   "text": (f"共 {len(idxs)} 帧，时间 t={ts[idxs[0]]:.1f}s 至 t={ts[idxs[-1]]:.1f}s，"
                            f"相邻帧间隔约 {interval:.1f}s。请输出每一帧的 JSON 记录。")})
    return blocks


def index_frames(client: DSClient, idxs, ts, files_map, interval):
    """索引一组帧；截断/失败对半拆批递归。返回 {帧索引: card}。"""
    if not idxs:
        return {}
    try:
        data, finish = client.chat_json(batch_blocks(idxs, ts, files_map, interval),
                                        system=INDEX_SYSTEM, thinking=False, max_tokens=8192)
    except ChatError as e:
        if len(idxs) == 1:
            print(f"[index] frame {idxs[0]} failed: {e}", flush=True)
            return {}
        mid = len(idxs) // 2
        return {**index_frames(client, idxs[:mid], ts, files_map, interval),
                **index_frames(client, idxs[mid:], ts, files_map, interval)}
    cards = {}
    raw = data.get("frames") if isinstance(data, dict) else data
    for c in raw or []:
        try:
            i = min(range(len(ts)), key=lambda k: abs(ts[k] - float(c.get("t", -1))))
            cards[i] = normalize_card(c, ts[i])  # 时刻以我们的标签为准
        except (TypeError, ValueError):
            continue
    missing = [i for i in idxs if i not in cards]
    if finish == "length" and len(idxs) > 1:
        mid = len(idxs) // 2
        print(f"[index] batch f{idxs[0]}-{idxs[-1]} truncated, splitting", flush=True)
        cards.update(index_frames(client, idxs[:mid], ts, files_map, interval))
        cards.update(index_frames(client, idxs[mid:], ts, files_map, interval))
    elif missing and len(missing) < len(idxs):
        cards.update(index_frames(client, missing, ts, files_map, interval))
    return cards


def build_segments(frame_records, seg_sec: float):
    """帧卡片本地聚合为段卡片（默认 30s/段）。"""
    segs = {}
    for rec in sorted(frame_records, key=lambda r: r["t"]):
        key = int(rec["t"] // seg_sec)
        segs.setdefault(key, {"start": key * seg_sec, "frames": []})["frames"].append(rec)
    out = []
    for key in sorted(segs):
        g = segs[key]
        summaries, kw_freq = [], {}
        for rec in g["frames"]:
            if rec["summary"]:
                summaries.append(rec["summary"])
            for k in rec["keywords"]:
                kw_freq[k] = kw_freq.get(k, 0) + 1
        kws = sorted(kw_freq, key=lambda k: -kw_freq[k])[:10]
        out.append({
            "start": g["start"],
            "end": round(g["start"] + seg_sec, 2),
            "summary": "；".join(dict.fromkeys(summaries))[:600] or "（无摘要）",
            "keywords": kws,
            "motion_max": max((r["motion"] for r in g["frames"]), key=MOTIONS.index, default="低"),
            "frame_idx": [r["idx"] for r in g["frames"]],
        })
    return out


def main():
    ap = argparse.ArgumentParser(description="Build vision index for a video")
    ap.add_argument("video", type=Path)
    ap.add_argument("--fps", type=float, default=0, help="宏观采样率（默认按时长自动：≤60s→1，≤10min→0.5，≤30min→0.25，更长→0.1）")
    ap.add_argument("--seg", type=float, default=30, help="段长（秒），问答检索单元")
    ap.add_argument("--batch", type=int, default=BATCH_DEFAULT)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit-frames", type=int, default=0, help="只索引前 N 帧（测试用）")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--clean", action="store_true", help="删除该视频的本地缓存后退出")
    args = ap.parse_args()

    video = args.video.resolve()
    if not video.is_file():
        sys.exit(f"video not found: {video}")
    sha = sha256_file(video)
    cache_dir = CACHE_ROOT / sha[:16]
    if args.clean:
        if cache_dir.exists():
            for f in cache_dir.glob("*"):
                f.unlink()
            cache_dir.rmdir()
            print(f"[clean] removed {cache_dir}")
        return

    meta = ffprobe(video)
    duration = meta["duration"]
    fps = args.fps if args.fps > 0 else auto_fps(duration)
    n_expect = int(duration * fps) + 1
    index_path = cache_dir / "index.json"

    if index_path.exists() and not args.force:
        try:
            old = json.loads(index_path.read_text("utf-8"))
            if old.get("sample_fps") == fps and old.get("frames_indexed", 0) >= min(n_expect, args.limit_frames or n_expect):
                print(f"[cache] index exists: {cache_dir}")
                print(f"[cache] {old['frames_indexed']} frames @ {fps}fps, use --force to rebuild")
                return
        except json.JSONDecodeError:
            pass

    print(f"[ingest] {video.name}: {meta['width']}x{meta['height']}, {duration:.1f}s, "
          f"fps={fps} (≈{n_expect} frames){', audio ignored' if meta['has_audio'] else ''}", flush=True)
    t0 = time.time()

    frame_files = extract_frames(video, cache_dir / "frames", fps, MAX_SIDE_PX)
    if args.limit_frames > 0:
        frame_files = frame_files[:args.limit_frames]
    n = len(frame_files)
    ts = [i / fps for i in range(n)]
    print(f"[frames] extracted {n} frames -> {cache_dir / 'frames'} ({time.time() - t0:.0f}s)", flush=True)

    client = DSClient()
    files_map = upload_all(client, frame_files, cache_dir / "files.json", args.workers)

    cards = {}
    for i in range(0, n, args.batch):
        chunk = list(range(i, min(i + args.batch, n)))
        cards.update(index_frames(client, chunk, ts, files_map, 1 / fps))
        print(f"[index] {min(i + args.batch, n)}/{n} done ({time.time() - t0:.0f}s)", flush=True)

    fallback = 0
    frames = []
    for i in range(n):
        if i in cards:
            frames.append({"idx": i, **cards[i]})
        else:
            fallback += 1
            frames.append({"idx": i, "t": round(ts[i], 2), "scene": "", "summary": "",
                           "keywords": [], "ocr": "", "event": "", "motion": "低"})
    if fallback:
        print(f"[index] WARNING: {fallback} frames have no card", flush=True)

    print(f"[scenes] detecting scene cuts (local, no API)...", flush=True)
    scene_cuts = detect_scene_cuts(video)

    index = {
        "video": str(video),
        "video_name": video.name,
        "sha256": sha,
        "model": client.model,
        "created": datetime.now().isoformat(timespec="seconds"),
        "duration": duration,
        "width": meta["width"],
        "height": meta["height"],
        "has_audio": meta["has_audio"],
        "sample_fps": fps,
        "seg_sec": args.seg,
        "total_frames_extracted": n,
        "frames_indexed": len(cards),
        "frames": frames,
        "segments": build_segments(frames, args.seg),
        "scene_cuts": scene_cuts,
    }
    save_json(index_path, index)
    motions = {}
    for f in frames:
        motions[f["motion"]] = motions.get(f["motion"], 0) + 1
    print(f"[done] {len(cards)}/{n} frame cards, {len(index['segments'])} segments, "
          f"{len(scene_cuts)} scene cuts in {time.time() - t0:.0f}s -> {index_path}", flush=True)
    print(f"[done] motion stats: {motions}", flush=True)


if __name__ == "__main__":
    main()
