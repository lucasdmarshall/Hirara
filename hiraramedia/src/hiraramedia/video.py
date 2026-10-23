"""video_profile: let an agent "watch" a video.

A model cannot play a video. It can read a timeline and look at a handful of
images. This makes one FFmpeg pass over a downscaled, low-frame-rate copy to
find scene cuts, black stretches and frozen stretches, pulls a keyframe at the
start of each scene (topped up or thinned to ``max_keyframes``), tiles them
into one labelled contact sheet, and, when hiraraaudio is installed, adds the
audio timeline (speech / music / silence) for the soundtrack.
"""

from __future__ import annotations

import io
import json
import re
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

from .config import MediaConfig
from .errors import MediaError

SHOWINFO = re.compile(r"pts_time:([0-9.]+)")
BLACK = re.compile(r"black_start:([0-9.]+)\s+black_end:([0-9.]+)")
FREEZE_START = re.compile(r"freeze_start:\s*([0-9.]+)")
FREEZE_END = re.compile(r"freeze_end:\s*([0-9.]+)")
LOCAL_ONLY = ["-protocol_whitelist", "file,pipe,fd"]


def fmt_time(seconds: float) -> str:
    minutes, secs = divmod(max(0.0, seconds), 60)
    hours, minutes = divmod(int(minutes), 60)
    return f"{hours}:{minutes:02d}:{secs:04.1f}" if hours else f"{minutes}:{secs:04.1f}"


def _run(args: list[str], config: MediaConfig) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(args, capture_output=True, timeout=config.timeout, check=False)
    except FileNotFoundError as exc:
        raise MediaError(f"{args[0]} is not installed (apt-get install ffmpeg) or set HM_FFMPEG") from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaError(f"{Path(args[0]).name} timed out after {config.timeout:.0f}s") from exc


def probe(path: Path, config: MediaConfig) -> dict:
    proc = _run([config.ffprobe, "-v", "error", *LOCAL_ONLY, "-print_format", "json",
                 "-show_format", "-show_streams", str(path)], config)
    if proc.returncode != 0:
        raise MediaError("not a readable video: " + proc.stderr.decode("utf-8", "replace").strip()[-200:])
    data = json.loads(proc.stdout or b"{}")
    streams = data.get("streams") or []
    v = next((s for s in streams if s.get("codec_type") == "video"
              and not (s.get("disposition") or {}).get("attached_pic")), None)
    if v is None:
        raise MediaError("no video stream found")
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    fmt = data.get("format") or {}
    num, _, den = (v.get("avg_frame_rate") or "0/1").partition("/")
    fps = float(num) / float(den) if den and float(den) else None
    duration = float(v.get("duration") or fmt.get("duration") or 0) or None
    rotation = None
    for sd in v.get("side_data_list") or []:
        if "rotation" in sd:
            rotation = sd["rotation"]
    return {
        "duration": round(duration, 3) if duration else None,
        "width": v.get("width"),
        "height": v.get("height"),
        "fps": round(fps, 3) if fps else None,
        "video_codec": v.get("codec_name"),
        "audio_codec": a.get("codec_name") if a else None,
        "audio_channels": a.get("channels") if a else None,
        "bit_rate": int(fmt["bit_rate"]) if fmt.get("bit_rate") else None,
        "format": fmt.get("format_name"),
        "rotation": rotation,
        "has_audio": a is not None,
    }


def analyse(path: Path, config: MediaConfig, *, scene_threshold: float, analysis_fps: float,
            black_min: float, freeze_min: float) -> dict:
    vf = (f"fps={analysis_fps},scale=320:-2,"
          f"blackdetect=d={black_min}:pix_th=0.10,"
          f"freezedetect=n=0.003:d={freeze_min},"
          f"select='gt(scene\\,{scene_threshold})',showinfo")
    proc = _run([config.ffmpeg, "-nostdin", "-hide_banner", *LOCAL_ONLY, "-i", str(path), "-an",
                 "-vf", vf, "-f", "null", "-"], config)
    err = proc.stderr.decode("utf-8", "replace")
    if proc.returncode != 0:
        tail = err.strip().splitlines()[-1][-200:] if err.strip() else f"exit {proc.returncode}"
        raise MediaError(f"video analysis failed: {tail}")
    scenes = sorted({round(float(t), 2) for t in SHOWINFO.findall(err)})
    blacks = [(float(a), float(b)) for a, b in BLACK.findall(err)]
    starts = [float(x) for x in FREEZE_START.findall(err)]
    ends = [float(x) for x in FREEZE_END.findall(err)]
    freezes = [(s, ends[i] if i < len(ends) else None) for i, s in enumerate(starts)]
    return {"scene_cuts": scenes, "black": blacks, "frozen": freezes}


def pick_times(duration: float, cuts: list[float], limit: int) -> list[float]:
    """Scene starts, thinned or topped up to ``limit`` well-spread times."""
    starts = [0.0] + [c for c in cuts if 0.5 < c < duration - 0.25]
    # Sample a little into each scene, past any transition.
    times = [min(s + 0.5, max(0.0, duration - 0.1)) for s in starts]
    if len(times) > limit:
        idx = [round(i * (len(times) - 1) / (limit - 1)) for i in range(limit)] if limit > 1 else [0]
        times = [times[i] for i in sorted(set(idx))]
    while len(times) < min(limit, max(1, int(duration))) and duration > 0:
        gaps = sorted(zip(times, times[1:] + [duration]), key=lambda g: g[1] - g[0], reverse=True)
        a, b = gaps[0]
        if b - a < 1.0:
            break
        times = sorted(times + [round((a + b) / 2, 2)])
    return [round(t, 2) for t in times]


def grab(path: Path, t: float, width: int, config: MediaConfig) -> Image.Image:
    proc = _run([config.ffmpeg, "-nostdin", "-v", "error", "-ss", f"{t:.3f}", *LOCAL_ONLY,
                 "-i", str(path), "-frames:v", "1", "-vf", f"scale={width}:-2",
                 "-f", "image2pipe", "-vcodec", "png", "-"], config)
    if proc.returncode != 0 or not proc.stdout:
        raise MediaError(f"could not extract a frame at {t:.2f}s")
    return Image.open(io.BytesIO(proc.stdout)).convert("RGB")


def contact_sheet(frames: list[tuple[float, Image.Image]], *, columns: int = 4) -> Image.Image:
    w, h = frames[0][1].size
    rows = (len(frames) + columns - 1) // columns
    label_h = 18
    sheet = Image.new("RGB", (columns * w + (columns + 1) * 4, rows * (h + label_h) + (rows + 1) * 4),
                      (24, 24, 28))
    draw = ImageDraw.Draw(sheet)
    for i, (t, frame) in enumerate(frames):
        r, c = divmod(i, columns)
        x = 4 + c * (w + 4)
        y = 4 + r * (h + label_h + 4)
        sheet.paste(frame.resize((w, h)), (x, y + label_h))
        draw.text((x + 2, y + 3), f"#{i + 1}  {fmt_time(t)}", fill=(230, 230, 235))
    return sheet


def to_jpeg(img: Image.Image, quality: int = 80) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def audio_summary(path: Path) -> dict | None:
    """Soundtrack timeline via hiraraaudio, if it is installed."""
    try:
        from hiraraaudio.analysis import measure, profile_result
        from hiraraaudio.config import AudioConfig
    except ImportError:
        return None
    cfg = AudioConfig.from_env()
    m = measure(path, cfg, native=False)
    r = profile_result(m, str(path), max_segments=20)
    return {"text": r["text"], "summary": r["summary"], "timeline": r["timeline"]}


def profile(path: Path, config: MediaConfig, *, max_keyframes: int = 12, frame_width: int = 480,
            scene_threshold: float = 0.3, include_audio: bool = True,
            output_dir: Path | None = None) -> dict:
    info = probe(path, config)
    duration = info["duration"] or 0.0
    fps = min(5.0, info["fps"] or 5.0)
    found = analyse(path, config, scene_threshold=scene_threshold, analysis_fps=fps,
                    black_min=0.5, freeze_min=2.0)
    limit = max(1, min(int(max_keyframes), config.max_keyframes))
    times = pick_times(duration, found["scene_cuts"], limit)
    width = max(64, min(int(frame_width), 1280))
    frames = [(t, grab(path, t, width, config)) for t in times]
    keyframes = []
    for i, (t, frame) in enumerate(frames, 1):
        item = {"index": i, "time": t, "width": frame.size[0], "height": frame.size[1]}
        if output_dir is not None:
            target = output_dir / f"keyframe_{i:03d}_{t:.2f}s.jpg"
            frame.save(target, format="JPEG", quality=85)
            item["path"] = str(target)
        keyframes.append(item)
    sheet = contact_sheet([(t, f.resize((240, int(240 * f.size[1] / f.size[0])))) for t, f in frames],
                          columns=4 if len(frames) > 4 else len(frames))
    sheet_bytes = to_jpeg(sheet)
    audio = audio_summary(path) if include_audio and info["has_audio"] else None

    cuts = found["scene_cuts"]
    lines = [f"{fmt_time(duration)} video, {info['width']}x{info['height']} @ {info['fps']} fps, "
             f"{len(cuts) + 1} shot(s)" + ("" if info["has_audio"] else ", no audio")]
    bounds = [0.0] + cuts + [duration]
    for i in range(len(bounds) - 1):
        if i >= 40:
            lines.append(f"… {len(bounds) - 1 - i} more shots")
            break
        lines.append(f"shot {i + 1}: {fmt_time(bounds[i])}–{fmt_time(bounds[i + 1])}")
    for a, b in found["black"]:
        lines.append(f"! black {fmt_time(a)}–{fmt_time(b)}")
    for a, b in found["frozen"]:
        lines.append(f"! frozen {fmt_time(a)}–{fmt_time(b) if b else 'end'}")
    if audio:
        lines.append("audio: " + audio["text"].splitlines()[0])
    return {
        "info": info,
        "scene_cuts": cuts,
        "shots": len(cuts) + 1,
        "black_segments": [{"start": round(a, 2), "end": round(b, 2)} for a, b in found["black"]],
        "frozen_segments": [{"start": round(a, 2), "end": round(b, 2) if b else None}
                            for a, b in found["frozen"]],
        "keyframes": keyframes,
        "frames": frames,
        "contact_sheet": sheet_bytes,
        "contact_sheet_size": list(sheet.size),
        "audio": audio,
        "text": "\n".join(lines),
    }


__all__ = ["pick_times", "probe", "profile"]
