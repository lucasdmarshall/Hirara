"""audio_tones: DTMF digits, beeps, steady test tones and mains hum.

Classic detectors (Goertzel filters for DTMF, spectral peak tonality for
beeps) that turn a call recording or a broadcast into facts an agent can act
on: "the caller pressed 4-2-#", "there is a beep at 0:31", "60 Hz hum".
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

import numpy as np

from . import dsp

TONE_FRAME = 640  # 40 ms at 16 kHz
TONE_HOP = 320  # 20 ms
TONE_FFT = 4096
HOP_S = TONE_HOP / dsp.ANALYSIS_RATE

DTMF_ROWS = (697.0, 770.0, 852.0, 941.0)
DTMF_COLS = (1209.0, 1336.0, 1477.0, 1633.0)
DTMF_KEYS = ("123A", "456B", "789C", "*0#D")

_WINDOW = np.hanning(TONE_FRAME)
_TIME = np.arange(TONE_FRAME) / dsp.ANALYSIS_RATE
_DTMF_FREQS = np.array(DTMF_ROWS + DTMF_COLS)
_BASIS = np.exp(-2j * np.pi * _DTMF_FREQS[None, :] * _TIME[:, None]) * _WINDOW[:, None]
_FREQS = np.fft.rfftfreq(TONE_FFT, 1 / dsp.ANALYSIS_RATE)
_LOBE = int(np.ceil(2 * TONE_FFT / TONE_FRAME)) + 1  # Hann main lobe, in padded bins


def _frames(chunks: Iterable[np.ndarray], hum: dsp.HumAccumulator | None) -> Iterator[np.ndarray]:
    carry = np.zeros(0, dtype=np.float32)
    for chunk in chunks:
        if hum is not None:
            hum.update(chunk)
        buf = np.concatenate([carry, chunk])
        if len(buf) < TONE_FRAME:
            carry = buf
            continue
        count = (len(buf) - TONE_FRAME) // TONE_HOP + 1
        yield np.lib.stride_tricks.sliding_window_view(buf, TONE_FRAME)[::TONE_HOP][:count]
        carry = buf[count * TONE_HOP:]


def analyse_frames(frames: np.ndarray) -> dict[str, np.ndarray]:
    """Per-frame DTMF digit (or ''), tonal peak frequency and level."""
    x = frames.astype(np.float64)
    windowed = x * _WINDOW
    energy = (windowed ** 2).sum(axis=1)
    level = dsp.db(np.sqrt(np.mean(x ** 2, axis=1)))

    # DTMF: Goertzel-equivalent projections onto the 8 tone frequencies,
    # normalised so a single pure tone scores 1 and a clean pair ~0.5 each.
    proj = np.abs(x @ _BASIS) ** 2
    scale = (_WINDOW.sum() ** 2 / 4) * (2 * np.maximum(energy, dsp.EPS) / (_WINDOW ** 2).sum())
    p = proj / scale[:, None]
    rows, cols = p[:, :4], p[:, 4:]
    r_best, c_best = rows.argmax(axis=1), cols.argmax(axis=1)
    r_val = rows[np.arange(len(p)), r_best]
    c_val = cols[np.arange(len(p)), c_best]
    r_second = np.sort(rows, axis=1)[:, -2]
    c_second = np.sort(cols, axis=1)[:, -2]
    twist = r_val / np.maximum(c_val, dsp.EPS)
    is_dtmf = (
        (level > -45)
        & (r_val > 0.15) & (c_val > 0.15) & (r_val + c_val > 0.7)
        & (r_second < 0.25 * r_val) & (c_second < 0.25 * c_val)
        & (twist > 0.16) & (twist < 6.3)
    )
    digits = np.array([DTMF_KEYS[r][c] for r, c in zip(r_best, c_best)], dtype=object)
    digits[~is_dtmf] = ""

    # Tonal peak: share of power in the main lobe around the strongest bin.
    spec = np.abs(np.fft.rfft(windowed, TONE_FFT, axis=1)) ** 2
    peak = spec.argmax(axis=1)
    total = spec.sum(axis=1) + dsp.EPS
    lobe = np.zeros(len(spec))
    for k in range(-_LOBE, _LOBE + 1):
        idx = np.clip(peak + k, 0, spec.shape[1] - 1)
        lobe += spec[np.arange(len(spec)), idx]
    tonality = lobe / total
    freq = _FREQS[peak]
    tonal = (tonality > 0.85) & (level > -50) & (freq >= 80) & (freq <= 7800) & ~is_dtmf
    return {"digit": digits, "freq": freq, "tonal": tonal, "level": level}


class FrameTonality:
    """Per-20 ms flag: is this frame a pure tone or a DTMF pair?

    Fed the same 16 kHz stream as the profile features, so flag i
    lines up with feature frame i. Lets the profile label beeps and key tones
    as "tones" instead of mistaking their on/off pattern for speech.
    """

    def __init__(self) -> None:
        self._carry = np.zeros(0, dtype=np.float32)
        self._parts: list[np.ndarray] = []

    def update(self, chunk: np.ndarray) -> None:
        buf = np.concatenate([self._carry, chunk])
        if len(buf) < TONE_FRAME:
            self._carry = buf
            return
        count = (len(buf) - TONE_FRAME) // TONE_HOP + 1
        frames = np.lib.stride_tricks.sliding_window_view(buf, TONE_FRAME)[::TONE_HOP][:count]
        res = analyse_frames(frames)
        self._parts.append(res["tonal"] | (res["digit"] != ""))
        self._carry = buf[count * TONE_HOP:]

    def flags(self, frames: int) -> np.ndarray:
        out = np.concatenate(self._parts) if self._parts else np.zeros(0, dtype=bool)
        if out.size < frames:
            out = np.concatenate([out, np.zeros(frames - out.size, dtype=bool)])
        return out[:frames].astype(bool)


def detect(chunks: Iterable[np.ndarray], *, offset: float = 0.0, dtmf: bool = True,
           beeps: bool = True, hum: bool = True, min_tone_s: float = 0.08,
           limit: int = 500) -> dict:
    acc = dsp.HumAccumulator() if hum else None
    digits, freqs, tonal, levels = [], [], [], []
    for frames in _frames(chunks, acc):
        res = analyse_frames(frames)
        digits.append(res["digit"])
        freqs.append(res["freq"])
        tonal.append(res["tonal"])
        levels.append(res["level"])
    if digits:
        digit = np.concatenate(digits)
        freq = np.concatenate(freqs)
        is_tonal = np.concatenate(tonal)
        level = np.concatenate(levels)
    else:
        digit = np.zeros(0, dtype=object)
        freq = level = np.zeros(0)
        is_tonal = np.zeros(0, dtype=bool)

    def t(i: int) -> float:
        return round(offset + i * HOP_S, 2)

    keys: list[dict] = []
    if dtmf:
        i = 0
        while i < len(digit):
            if not digit[i]:
                i += 1
                continue
            j = i
            while j + 1 < len(digit) and digit[j + 1] == digit[i]:
                j += 1
            if j - i + 1 >= 2:  # at least ~40 ms
                keys.append({"digit": str(digit[i]), "start": t(i),
                             "end": round(t(j) + TONE_FRAME / dsp.ANALYSIS_RATE, 2)})
            i = j + 1

    tones: list[dict] = []
    if beeps:
        i = 0
        while i < len(is_tonal) and len(tones) < limit:
            if not is_tonal[i]:
                i += 1
                continue
            j = i
            while (j + 1 < len(is_tonal) and is_tonal[j + 1]
                   and abs(freq[j + 1] - freq[i]) <= 0.03 * freq[i]):
                j += 1
            dur = (j - i) * HOP_S + TONE_FRAME / dsp.ANALYSIS_RATE
            if dur >= min_tone_s:
                tones.append({
                    "start": t(i),
                    "end": round(t(i) + dur, 2),
                    "freq_hz": round(float(np.median(freq[i: j + 1])), 1),
                    "level_db": round(float(np.median(level[i: j + 1])), 1),
                    "kind": "beep" if dur < 1.5 else "tone",
                })
            i = j + 1

    hum_info = dsp.detect_hum(acc.spectrum()) if acc is not None else None
    return {"dtmf": keys, "tones": tones, "hum": hum_info}


def text(result: dict) -> str:
    lines = []
    if result["dtmf"]:
        seq = "".join(k["digit"] for k in result["dtmf"])
        lines.append(f"DTMF {seq} (first at {dsp.fmt_time(result['dtmf'][0]['start'])})")
    for tone in result["tones"][:30]:
        lines.append(f"{dsp.fmt_time(tone['start'])} {tone['kind']} {tone['freq_hz']:g} Hz "
                     f"for {tone['end'] - tone['start']:.2f}s ({tone['level_db']} dB)")
    if len(result["tones"]) > 30:
        lines.append(f"… {len(result['tones']) - 30} more tones")
    if result["hum"]:
        lines.append(f"{result['hum']['mains_hz']} Hz mains hum")
    return "\n".join(lines) or "no DTMF, tones or hum found"


__all__ = ["FrameTonality", "analyse_frames", "detect", "text"]
