"""audio_split and audio_tighten: edits that need analysis to get right.

``ffmpeg -ss 60 -t 60`` will cut a recording into minutes, straight through
words. These tools first find where it is safe to cut (the quietest pause in
range), then cut there, render with short fades so joins do not click, and
return the plan so an agent can check it before or after applying it.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np

from . import dsp
from .config import AudioConfig
from .errors import AudioError
from .media import LOCAL_ONLY, StreamEncoder, decode_chunks, encode_args, run


# --- audio_split ----------------------------------------------------------------

def plan_split(features: dsp.Features, threshold: float, *, min_s: float, max_s: float) -> list[dict]:
    if min_s <= 0 or max_s <= 0 or min_s >= max_s:
        raise AudioError("need 0 < min_seconds < max_seconds")
    duration = features.duration
    level = dsp.smooth_level(features, 0.3)
    quiet = features.rms_db < threshold
    cuts: list[tuple[float, str, float]] = []
    start = 0.0
    while duration - start > max_s:
        a = int((start + min_s) / dsp.FRAME_S)
        b = min(len(level), int((start + max_s) / dsp.FRAME_S))
        if b <= a:
            break
        i = a + int(np.argmin(level[a:b]))
        kind = "pause" if quiet[i] else "forced"
        if quiet[i]:
            # Cut in the middle of the pause, not at its edge.
            lo = i
            while lo > a and quiet[lo - 1]:
                lo -= 1
            hi = i
            while hi < b - 1 and quiet[hi + 1]:
                hi += 1
            i = (lo + hi) // 2
        t = i * dsp.FRAME_S
        if t <= start:
            t = start + max_s
            kind = "forced"
        cuts.append((t, kind, float(level[min(i, len(level) - 1)])))
        start = t

    bounds = [0.0] + [c[0] for c in cuts] + [duration]
    segments = []
    for k in range(len(bounds) - 1):
        cut = cuts[k] if k < len(cuts) else None
        segments.append({
            "index": k,
            "start": round(bounds[k], 2),
            "end": round(bounds[k + 1], 2),
            "duration": round(bounds[k + 1] - bounds[k], 2),
            "cut_after": None if cut is None else cut[1],
            "cut_level_db": None if cut is None else round(cut[2], 1),
        })
    return segments


def write_segments(path: Path, segments: list[dict], out_dir: Path, stem: str, fmt: str,
                   config: AudioConfig) -> list[str]:
    files = []
    for seg in segments:
        target = out_dir / f"{stem}_{seg['index']:03d}.{fmt}"
        run(
            [config.ffmpeg, "-nostdin", "-v", "error", "-y", "-ss", f"{seg['start']:.3f}",
             *LOCAL_ONLY, "-i", str(path), "-t", f"{seg['duration']:.3f}", "-vn", *encode_args(fmt),
             str(target)],
            config,
        )
        files.append(str(target))
    return files


# --- audio_tighten -------------------------------------------------------------

def plan_tighten(features: dsp.Features, threshold: float, *, min_pause: float,
                 keep_pause: float, edges: bool) -> list[dict]:
    if keep_pause < 0 or min_pause <= keep_pause:
        raise AudioError("need 0 <= keep_pause < min_pause")
    duration = features.duration
    plan = []
    for s, e in dsp.silences(features, threshold, min_pause):
        leading = s <= dsp.FRAME_S
        trailing = e >= duration - dsp.FRAME_S
        if (leading or trailing) and not edges:
            continue
        if leading and trailing:
            continue  # all silence: nothing to tighten around
        if leading:
            cut = (s, e - keep_pause)
        elif trailing:
            cut = (s + keep_pause, e)
        else:
            cut = (s + keep_pause / 2, e - keep_pause / 2)
        if cut[1] - cut[0] < 0.05:
            continue
        plan.append({
            "start": round(s, 3),
            "end": round(e, 3),
            "pause_s": round(e - s, 2),
            "kept_s": round((e - s) - (cut[1] - cut[0]), 2),
            "remove": [round(cut[0], 3), round(cut[1], 3)],
            "where": "start" if leading else ("end" if trailing else "between"),
        })
    return plan


def keep_intervals(plan: list[dict], duration: float) -> list[tuple[float, float]]:
    """Spans to keep. A span that runs to the end of the file ends at
    ``inf``, so the renderer neither fades it out nor stops early."""
    keep, pos = [], 0.0
    for item in plan:
        a, b = item["remove"]
        if a > pos:
            keep.append((pos, a))
        pos = max(pos, b)
    if pos < duration:
        keep.append((pos, float("inf")))
    return keep


def render_keep(path: Path, config: AudioConfig, keep: list[tuple[float, float]], *,
                sample_rate: int, channels: int, fmt: str, fade_ms: float = 8.0) -> Path:
    """Write only the kept spans, with a short fade at every join.

    Streams at the source's own rate and channel count, so nothing is
    resampled and a long file never sits in memory.
    """
    out = Path(tempfile.mkstemp(prefix="hiraraaudio-edit-", suffix=f".{fmt}")[1])
    if not keep:
        raise AudioError("nothing left to keep")
    big = np.iinfo(np.int64).max // 2
    starts = np.array([round(a * sample_rate) for a, _ in keep], dtype=np.int64)
    ends = np.array([big if np.isinf(b) else round(b * sample_rate) for _, b in keep],
                    dtype=np.int64)
    fade = max(1, int(sample_rate * fade_ms / 1000))

    encoder = StreamEncoder(out, fmt, sample_rate, channels, config)
    pos = 0
    try:
        for chunk in decode_chunks(path, config, sample_rate=None, channels=None,
                                   native_rate=sample_rate, chunk_seconds=10.0):
            n = len(chunk)
            idx = pos + np.arange(n, dtype=np.int64)
            j = np.searchsorted(starts, idx, side="right") - 1
            valid = j >= 0
            jj = np.where(valid, j, 0)
            inside = valid & (idx < ends[jj])
            if inside.any():
                from_start = idx - starts[jj]
                to_end = ends[jj] - 1 - idx
                from_start = np.where(starts[jj] == 0, fade, from_start)
                gain = np.minimum(1.0, np.minimum((from_start + 1) / fade, (to_end + 1) / fade))
                encoder.write(chunk[inside] * gain[inside, None].astype(np.float32))
            pos += n
    finally:
        encoder.close()
    return out


__all__ = ["keep_intervals", "plan_split", "plan_tighten", "render_keep", "write_segments"]
