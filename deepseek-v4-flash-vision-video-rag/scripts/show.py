"""show.py —— 视频定位展示工具（无需先建索引）。

用法：
  python show.py <video> --at 00:07            # 渲染该时刻的帧（PNG）
  python show.py <video> --at 3.5,00:10        # 多个时刻
  python show.py <video> --clip 00:05-00:12    # 切出可播放片段（无损 copy，失败自动重编码）
  python show.py <video> --micro 00:04 --span 3  # 高帧率中心放大帧序列（看快速动作）
"""
import argparse
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT_DIR = Path("video-vision-out")
MICRO_FPS = 12


def to_sec(x: str) -> float:
    parts_ = [float(v) for v in x.split(":")]
    if len(parts_) == 3:
        h, m, s = parts_
    elif len(parts_) == 2:
        h, m, s = 0, parts_[0], parts_[1]
    else:
        h, m, s = 0, 0, parts_[0]
    return h * 3600 + m * 60 + s


def fmt_ts(sec: float) -> str:
    sec = max(0, int(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def run(cmd, timeout=600):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-300:])
    return r


def main():
    ap = argparse.ArgumentParser(description="Render frames / clips from a video")
    ap.add_argument("video", type=Path)
    ap.add_argument("--at", default="", help="时刻列表，如 00:07 或 3.5,00:10")
    ap.add_argument("--clip", default="", help="时间段，如 00:05-00:12")
    ap.add_argument("--micro", default="", help="微观窗口中心时刻（如 00:04），配合 --span")
    ap.add_argument("--span", type=float, default=3.0, help="微观窗口总时长（秒，默认3）")
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    args = ap.parse_args()

    video = args.video.resolve()
    if not video.is_file():
        sys.exit(f"video not found: {video}")
    args.out.mkdir(exist_ok=True)
    stem = video.name.rsplit(".", 1)[0]

    if args.at:
        for t_str in args.at.split(","):
            t = to_sec(t_str.strip())
            dst = args.out / f"{stem}_t{fmt_ts(t).replace(':', '')}.png"
            run(["ffmpeg", "-y", "-ss", f"{t:.2f}", "-i", str(video),
                 "-frames:v", "1", str(dst)])
            print(f"[{fmt_ts(t)}] {dst.resolve()}")

    if args.clip:
        m = args.clip.strip().split("-")
        if len(m) != 2:
            sys.exit("--clip 格式：00:05-00:12")
        a, b = to_sec(m[0]), to_sec(m[1])
        dst = args.out / f"{stem}_clip{fmt_ts(a).replace(':', '')}-{fmt_ts(b).replace(':', '')}.mp4"
        try:
            run(["ffmpeg", "-y", "-ss", f"{a:.2f}", "-i", str(video),
                 "-t", f"{b - a:.2f}", "-c", "copy", str(dst)])
        except RuntimeError:
            run(["ffmpeg", "-y", "-ss", f"{a:.2f}", "-i", str(video),
                 "-t", f"{b - a:.2f}", "-c:v", "libx264", "-preset", "fast",
                 "-crf", "23", "-c:a", "aac", str(dst)], timeout=1200)
        print(f"[{fmt_ts(a)}-{fmt_ts(b)}] {dst.resolve()}")

    if args.micro:
        c = to_sec(args.micro.strip())
        a, b = c - args.span / 2, c + args.span / 2
        out_dir = args.out / f"{stem}_micro_{fmt_ts(c).replace(':', '')}"
        out_dir.mkdir(exist_ok=True)
        run(["ffmpeg", "-y", "-ss", f"{max(0, a):.2f}", "-i", str(video),
             "-t", f"{b - a:.2f}",
             "-vf", f"fps={MICRO_FPS},crop=iw*0.4:ih*0.4,scale=iw*2:ih*2:flags=lanczos",
             "-q:v", "2", str(out_dir / "m_%05d.jpg")])
        n = len(list(out_dir.glob("m_*.jpg")))
        print(f"[{fmt_ts(a)}-{fmt_ts(b)}] @{MICRO_FPS}fps 中心放大 {n} 帧 -> {out_dir.resolve()}")

    if not (args.at or args.clip or args.micro):
        sys.exit("请指定 --at / --clip / --micro 之一")


if __name__ == "__main__":
    main()
