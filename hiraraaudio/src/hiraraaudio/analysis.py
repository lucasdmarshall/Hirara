"""audio_info and audio_profile, plus the shared measurement behind them.

The profile is the core idea of this package: an agent cannot listen, and it
cannot reason over a million samples either. So the signal is reduced to a
short, ordered description (what is where, how loud, what went wrong) that
fits in a context window and can be read like a log.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import dsp, tones
from .config import AudioConfig
from .media import DecodeStats
from .media import Loudness, MediaInfo, loudness, probe


@dataclass
class Measurement:
    info: MediaInfo
    features: dsp.Features
    threshold: float
    labels: list[str]
    native: dsp.NativeStats | None
    loud: Loudness | None
    offset: float = 0.0  # start of the analysed span within the file

    @property
    def duration(self) -> float:
        return self.features.duration

    def kind_share(self) -> dict[str, float]:
        total = max(1, len(self.labels))
        return {k: round(100.0 * self.labels.count(k) / total, 1) for k in dsp.KINDS}

    def silences(self, min_seconds: float) -> list[tuple[float, float]]:
        return dsp.silences(self.features, self.threshold, min_seconds)

    def leading_trailing_silence(self) -> tuple[float, float]:
        quiet = self.features.rms_db < self.threshold
        n = quiet.size
        if n == 0:
            return 0.0, 0.0
        if quiet.all():
            return self.duration, self.duration
        lead = int(np.argmin(quiet))
        trail = int(np.argmin(quiet[::-1]))
        return lead * dsp.FRAME_S, trail * dsp.FRAME_S

    def snr_db(self) -> float | None:
        active = self.features.rms_db[self.features.rms_db > self.threshold]
        floor = dsp.noise_floor_db(self.features)
        if active.size == 0 or floor is None:
            return None
        return float(np.median(active) - floor)

    def quietest_window_db(self, seconds: float = 0.5) -> float | None:
        """Level of the quietest stretch that is not digital silence (ACX
        "noise floor"). ``None`` if the file has no such stretch."""
        f = self.features
        n = max(1, int(round(seconds / dsp.FRAME_S)))
        if f.frames < n:
            return None
        power = 10 ** (f.rms_db / 10)
        windows = np.lib.stride_tricks.sliding_window_view(power, n)
        lows = np.lib.stride_tricks.sliding_window_view(f.rms_db, n).min(axis=1)
        # A window touching digital silence is not room tone; skip it.
        live = lows > dsp.DIGITAL_SILENCE_DB
        if not live.any():
            return None
        return float(dsp.db(windows[live].mean(axis=1).min(), power=True))


def measure(
    path: str | Path,
    config: AudioConfig,
    *,
    start: float | None = None,
    duration: float | None = None,
    silence_db: float | None = None,
    native: bool = True,
    with_loudness: bool = True,
    info: MediaInfo | None = None,
) -> Measurement:
    info = info or probe(path, config)
    tonality = tones.FrameTonality()
    stats = DecodeStats()

    def tee(chunks):
        for chunk in chunks:
            tonality.update(chunk)
            yield chunk

    features = dsp.extract_features(
        tee(dsp.mono_chunks(path, config, start=start, duration=duration, stats=stats)),
        stats=stats,
    )
    threshold = dsp.silence_threshold(features, silence_db)
    labels = dsp.classify_seconds(features, threshold, tonality.flags(features.frames))
    native_result = None
    if native and info.sample_rate and info.channels:
        native_result = dsp.native_stats(path, config, info.sample_rate, info.channels,
                                         start=start, duration=duration)
    loud = None
    if with_loudness and features.duration >= 0.4:
        loud = loudness(path, config, start=start, duration=duration)
    return Measurement(info, features, threshold, labels, native_result, loud,
                       offset=start or 0.0)


# --- audio_info ---------------------------------------------------------------

def info_result(info: MediaInfo, source: str) -> dict:
    out = info.as_dict()
    parts = [
        f"{dsp.fmt_time(info.duration or 0)}" if info.duration else "unknown length",
        info.codec or "unknown codec",
        f"{info.sample_rate} Hz" if info.sample_rate else None,
        _channels_text(info.channels),
        f"{round(info.bit_rate / 1000)} kb/s" if info.bit_rate else None,
    ]
    out["summary"] = ", ".join(p for p in parts if p)
    out["source"] = source
    out["error"] = None
    return out


def _channels_text(channels: int | None) -> str | None:
    return {None: None, 1: "mono", 2: "stereo"}.get(channels, f"{channels} channels")


# --- audio_profile ------------------------------------------------------------

def profile_result(m: Measurement, source: str, *, max_segments: int = 40,
                   long_silence: float = 3.0) -> dict:
    f = m.features
    segments = dsp.merge_short(dsp.segments_from_labels(m.labels, f.duration), max_segments)
    timeline = []
    for seg in segments:
        level = dsp.segment_level(f, seg["start"], seg["end"])
        timeline.append(
            {
                "start": round(seg["start"] + m.offset, 2),
                "end": round(seg["end"] + m.offset, 2),
                "kind": seg["kind"],
                "level_db": None if level is None or seg["kind"] == "silence" else round(level, 1),
            }
        )

    events: list[dict] = []
    for a, b in m.silences(long_silence):
        events.append({"time": round(a + m.offset, 2), "type": "long_silence",
                       "detail": f"{b - a:.1f}s of silence"})
    if m.native and m.native.clipped_runs:
        for t in m.native.clip_times[:10]:
            events.append({"time": round(t + m.offset, 2), "type": "clipping",
                           "detail": "samples at full scale"})
    events.extend(_level_jumps(m))
    hum = dsp.detect_hum(f.hum_spectrum)
    if hum:
        events.append({"time": round(m.offset, 2), "type": "hum",
                       "detail": f"{hum['mains_hz']} Hz mains hum throughout"})
    events.sort(key=lambda e: e["time"])

    share = m.kind_share()
    longest = max((b - a for a, b in m.silences(0.2)), default=0.0)
    summary = {
        "speech_pct": share["speech"],
        "music_pct": share["music"],
        "noise_pct": share["noise"],
        "tones_pct": share["tones"],
        "silence_pct": share["silence"],
        "noise_floor_db": _r(dsp.noise_floor_db(f)),
        "snr_db": _r(m.snr_db()),
        "longest_silence_s": round(longest, 2),
        "peak_dbfs": _r(m.native.peak_dbfs) if m.native else None,
        "clipped_samples": m.native.clipped_samples if m.native else None,
        "hum": hum,
    }
    if m.loud:
        summary.update(m.loud.as_dict())

    return {
        "source": source,
        "duration": round(f.duration, 2),
        "start": round(m.offset, 2),
        "info": m.info.as_dict(),
        "summary": summary,
        "timeline": timeline,
        "events": events[:100],
        "text": _profile_text(m, timeline, events, summary),
        "silence_threshold_db": round(m.threshold, 1),
        "truncated": f.truncated,
        "note": (
            "speech/music/noise/tones labels are signal-feature estimates, not a "
            "trained classifier; levels are dBFS, loudness is ITU-R BS.1770"
        ),
        "error": None,
    }


def _r(value: float | None, digits: int = 1) -> float | None:
    return None if value is None else round(float(value), digits)


def _level_jumps(m: Measurement, jump_db: float = 12.0, limit: int = 20) -> list[dict]:
    f = m.features
    levels = []
    for i, label in enumerate(m.labels):
        if label == "silence":
            levels.append(None)
            continue
        levels.append(dsp.segment_level(f, i, i + 1))
    out = []
    for i in range(1, len(levels)):
        a, b = levels[i - 1], levels[i]
        if a is None or b is None:
            continue
        if abs(b - a) >= jump_db:
            direction = "louder" if b > a else "quieter"
            out.append({"time": round(i + m.offset, 2), "type": "level_jump",
                        "detail": f"{abs(b - a):.0f} dB {direction}"})
            if len(out) >= limit:
                break
    return out


def _profile_text(m: Measurement, timeline: list[dict], events: list[dict], summary: dict) -> str:
    lines = []
    head = [f"{dsp.fmt_time(m.duration)} total"]
    for kind in ("speech", "music", "noise", "tones", "silence"):
        pct = summary[f"{kind}_pct"]
        if pct:
            head.append(f"{kind} {pct:.0f}%")
    if summary.get("integrated_lufs") is not None:
        head.append(f"{summary['integrated_lufs']} LUFS")
    if summary.get("true_peak_dbtp") is not None:
        head.append(f"peak {summary['true_peak_dbtp']} dBTP")
    lines.append(", ".join(head))
    for seg in timeline:
        level = "" if seg["level_db"] is None else f" ({seg['level_db']} dB)"
        lines.append(f"{dsp.fmt_time(seg['start'])}–{dsp.fmt_time(seg['end'])} {seg['kind']}{level}")
    for ev in events[:20]:
        lines.append(f"! {dsp.fmt_time(ev['time'])} {ev['type']}: {ev['detail']}")
    if len(events) > 20:
        lines.append(f"! … {len(events) - 20} more events")
    return "\n".join(lines)


__all__ = ["Measurement", "info_result", "measure", "profile_result"]
