"""audio_sonify: turn a data series into sound.

A screen-reader user, or an agent producing audio-first output, can hear the
shape of a chart: each value becomes a short tone whose pitch follows the
value, panned left to right as the series advances. Missing values are rests.
Pitch is mapped on a musical (logarithmic) scale by default, so equal steps
in value sound like equal steps in pitch.
"""

from __future__ import annotations

import math

import numpy as np

from .errors import AudioError

MAX_POINTS = 5000


def _clean(values) -> list[float | None]:
    if not isinstance(values, (list, tuple)) or not values:
        raise AudioError("values must be a non-empty list of numbers (null for gaps)")
    if len(values) > MAX_POINTS:
        raise AudioError(f"at most {MAX_POINTS} values per series")
    out: list[float | None] = []
    for v in values:
        if v is None:
            out.append(None)
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            raise AudioError(f"not a number: {v!r}") from None
        out.append(f if math.isfinite(f) else None)
    if all(v is None for v in out):
        raise AudioError("values has no numbers")
    return out


def render(
    series: list[dict],
    *,
    duration: float | None,
    min_freq: float,
    max_freq: float,
    scale: str,
    waveform: str,
    min_value: float | None,
    max_value: float | None,
    sample_rate: int = 22050,
) -> tuple[np.ndarray, dict]:
    if not 40 <= min_freq < max_freq <= 8000:
        raise AudioError("need 40 <= min_freq < max_freq <= 8000")
    if scale not in ("musical", "linear"):
        raise AudioError("scale must be musical or linear")
    if waveform not in ("sine", "triangle", "square"):
        raise AudioError("waveform must be sine, triangle or square")
    cleaned = [(s.get("name") or f"series {i + 1}", _clean(s.get("values"))) for i, s in enumerate(series)]
    numbers = [v for _, vals in cleaned for v in vals if v is not None]
    lo = min(numbers) if min_value is None else float(min_value)
    hi = max(numbers) if max_value is None else float(max_value)
    if hi <= lo:
        hi = lo + 1.0

    points = sum(len(vals) for _, vals in cleaned)
    gap = 0.4 if len(cleaned) > 1 else 0.0
    total = duration if duration else min(60.0, max(2.0, points * 0.12))
    if not 0.5 <= total <= 300:
        raise AudioError("duration must be 0.5..300 seconds")
    note = max(0.03, (total - gap * (len(cleaned) - 1)) / points)

    def freq_for(v: float) -> float:
        x = (min(max(v, lo), hi) - lo) / (hi - lo)
        if scale == "linear":
            return min_freq + x * (max_freq - min_freq)
        return min_freq * (max_freq / min_freq) ** x

    def tone(freq: float, n: int) -> np.ndarray:
        phase = 2 * np.pi * freq * np.arange(n) / sample_rate
        if waveform == "sine":
            wave = np.sin(phase)
        elif waveform == "triangle":
            wave = 2 / np.pi * np.arcsin(np.sin(phase))
        else:
            wave = np.sign(np.sin(phase)) * 0.5
        attack = max(1, int(0.005 * sample_rate))
        env = np.ones(n)
        env[:attack] = np.linspace(0, 1, attack)
        release = max(1, int(min(0.02, note / 3) * sample_rate))
        env[-release:] = np.linspace(1, 0, release)
        return wave * env

    parts = []
    n_note = int(note * sample_rate)
    for k, (_, vals) in enumerate(cleaned):
        count = len(vals)
        for i, v in enumerate(vals):
            pan = 0.5 if count == 1 else i / (count - 1)
            left, right = math.cos(pan * math.pi / 2), math.sin(pan * math.pi / 2)
            mono = np.zeros(n_note) if v is None else tone(freq_for(v), n_note) * 0.5
            parts.append(np.stack([mono * left, mono * right], axis=1))
        if k < len(cleaned) - 1:
            parts.append(np.zeros((int(gap * sample_rate), 2)))
    audio = np.concatenate(parts).astype(np.float32)
    mapping = {
        "value_range": [lo, hi],
        "freq_range_hz": [min_freq, max_freq],
        "scale": scale,
        "note_seconds": round(note, 3),
        "series": [{"name": name, "points": len(vals),
                    "gaps": sum(v is None for v in vals)} for name, vals in cleaned],
        "panning": "left to right across each series",
    }
    return audio, mapping


__all__ = ["render"]
