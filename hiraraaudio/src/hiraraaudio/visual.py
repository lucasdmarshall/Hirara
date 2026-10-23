"""audio_spectrogram: a labelled spectrogram PNG for vision-capable models.

A model that can read images can see hum lines, broadband noise, dropouts,
clipping splatter and where speech sits, in one picture. The image carries
its own axes (time and frequency labels, drawn with a tiny built-in bitmap
font), and the result includes the plot geometry so a pixel can be mapped
back to a time and a frequency. PNG encoding is done here with zlib, so the
package needs no imaging library.
"""

from __future__ import annotations

import math
import struct
import zlib

import numpy as np

from . import dsp
from .config import AudioConfig

# --- PNG ------------------------------------------------------------------------


def encode_png(rgb: np.ndarray) -> bytes:
    """``(height, width, 3)`` uint8 -> PNG bytes."""
    height, width, _ = rgb.shape
    raw = np.zeros((height, width * 3 + 1), dtype=np.uint8)
    raw[:, 1:] = rgb.reshape(height, width * 3)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(raw.tobytes(), 6)) + chunk(b"IEND", b""))


# --- 5x7 bitmap font (just the glyphs axis labels need) ------------------------

_FONT = {
    "0": (0x0E, 0x11, 0x13, 0x15, 0x19, 0x11, 0x0E),
    "1": (0x04, 0x0C, 0x04, 0x04, 0x04, 0x04, 0x0E),
    "2": (0x0E, 0x11, 0x01, 0x02, 0x04, 0x08, 0x1F),
    "3": (0x1F, 0x02, 0x04, 0x02, 0x01, 0x11, 0x0E),
    "4": (0x02, 0x06, 0x0A, 0x12, 0x1F, 0x02, 0x02),
    "5": (0x1F, 0x10, 0x1E, 0x01, 0x01, 0x11, 0x0E),
    "6": (0x06, 0x08, 0x10, 0x1E, 0x11, 0x11, 0x0E),
    "7": (0x1F, 0x01, 0x02, 0x04, 0x08, 0x08, 0x08),
    "8": (0x0E, 0x11, 0x11, 0x0E, 0x11, 0x11, 0x0E),
    "9": (0x0E, 0x11, 0x11, 0x0F, 0x01, 0x02, 0x0C),
    ":": (0x00, 0x0C, 0x0C, 0x00, 0x0C, 0x0C, 0x00),
    ".": (0x00, 0x00, 0x00, 0x00, 0x00, 0x0C, 0x0C),
    "-": (0x00, 0x00, 0x00, 0x1F, 0x00, 0x00, 0x00),
    "k": (0x10, 0x10, 0x12, 0x14, 0x18, 0x14, 0x12),
    "H": (0x11, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11),
    "z": (0x00, 0x00, 0x1F, 0x02, 0x04, 0x08, 0x1F),
    "s": (0x00, 0x00, 0x0F, 0x10, 0x0E, 0x01, 0x1E),
    " ": (0, 0, 0, 0, 0, 0, 0),
}


def text_width(text: str) -> int:
    return max(0, len(text) * 6 - 1)


def draw_text(img: np.ndarray, x: int, y: int, text: str, color) -> None:
    for ch in text:
        glyph = _FONT.get(ch, _FONT[" "])
        for row, bits in enumerate(glyph):
            for col in range(5):
                if bits & (1 << (4 - col)):
                    yy, xx = y + row, x + col
                    if 0 <= yy < img.shape[0] and 0 <= xx < img.shape[1]:
                        img[yy, xx] = color
        x += 6


# --- colour map (dark purple -> orange -> pale yellow) -------------------------

_STOPS = np.array([
    [0.00, 0, 0, 4],
    [0.25, 81, 18, 124],
    [0.50, 183, 55, 121],
    [0.75, 252, 137, 97],
    [1.00, 252, 253, 191],
])


def colormap(values: np.ndarray) -> np.ndarray:
    v = np.clip(values, 0.0, 1.0)
    out = np.empty(v.shape + (3,), dtype=np.uint8)
    for c in range(3):
        out[..., c] = np.interp(v, _STOPS[:, 0], _STOPS[:, c + 1]).astype(np.uint8)
    return out


# --- spectrogram ------------------------------------------------------------------

LEFT, RIGHT, TOP, BOTTOM = 40, 8, 8, 18
BG = (18, 18, 24)
FG = (210, 210, 215)
GRID = (90, 90, 100)


def _nice_step(span: float, max_ticks: int) -> float:
    for step in (0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200):
        if span / step <= max_ticks:
            return step
    return span / max_ticks


def _time_label(t: float, step: float) -> str:
    if step < 1:
        return f"{t:.1f}"
    minutes, secs = divmod(int(round(t)), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def _freq_label(f: float) -> str:
    return f"{f / 1000:g}k" if f >= 1000 else f"{f:g}"


def render(
    chunks,
    *,
    sample_rate: int,
    duration: float,
    offset: float = 0.0,
    width: int = 1200,
    height: int = 400,
    min_freq: float = 50.0,
    max_freq: float | None = None,
    log_freq: bool = True,
    dynamic_range: float = 80.0,
) -> dict:
    n_fft = 2048 if sample_rate > 24000 else 1024
    hop = n_fft // 4
    nyquist = sample_rate / 2
    max_freq = min(max_freq or nyquist, nyquist)
    min_freq = max(1.0, min(min_freq, max_freq / 2))
    freqs = np.fft.rfftfreq(n_fft, 1 / sample_rate)

    # Row r (0 = top) covers [edges[r+1], edges[r]].
    if log_freq:
        edges = np.geomspace(max_freq, min_freq, height + 1)
    else:
        edges = np.linspace(max_freq, min_freq, height + 1)
    centers = np.sqrt(edges[:-1] * edges[1:]) if log_freq else (edges[:-1] + edges[1:]) / 2
    rowmap = np.zeros((freqs.size, height), dtype=np.float32)
    for r in range(height):
        sel = (freqs < edges[r]) & (freqs >= edges[r + 1])
        if sel.any():
            rowmap[sel, r] = 1.0 / sel.sum()
        else:
            rowmap[int(np.argmin(np.abs(freqs - centers[r]))), r] = 1.0

    est_frames = max(1, int(duration * sample_rate / hop))
    width = int(max(64, min(width, 4000, est_frames)))
    frames_per_col = est_frames / width
    cols = np.zeros((width, height))
    counts = np.zeros(width)
    mean_spec = np.zeros(freqs.size)
    frame = 0
    for power in dsp.stft_power(chunks, n_fft, hop):
        idx = np.minimum((np.arange(frame, frame + len(power)) / frames_per_col).astype(int),
                         width - 1)
        reduced = power @ rowmap
        np.add.at(cols, idx, reduced)
        np.add.at(counts, idx, 1)
        mean_spec += power.sum(axis=0)
        frame += len(power)
    used = counts > 0
    cols[used] /= counts[used, None]
    spec_db = dsp.db(cols + 1e-14, power=True)
    vmax = float(np.percentile(spec_db[used], 99.5)) if used.any() else 0.0
    vmin = vmax - dynamic_range
    norm = (spec_db - vmin) / dynamic_range
    norm[~used] = 0.0

    img = np.empty((TOP + height + BOTTOM, LEFT + width + RIGHT, 3), dtype=np.uint8)
    img[:] = BG
    img[TOP:TOP + height, LEFT:LEFT + width] = colormap(norm.T)

    # Frequency axis.
    if log_freq:
        ticks = [f for f in (50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000)
                 if min_freq <= f <= max_freq]
    else:
        step = _nice_step(max_freq - min_freq, 8)
        step = max(step, 100)
        ticks = list(np.arange(math.ceil(min_freq / step) * step, max_freq + 1, step))
    for f in ticks:
        if log_freq:
            pos = (np.log(max_freq) - np.log(f)) / (np.log(max_freq) - np.log(min_freq))
        else:
            pos = (max_freq - f) / (max_freq - min_freq)
        y = TOP + int(round(pos * (height - 1)))
        img[y, LEFT - 4:LEFT] = FG
        img[y, LEFT:LEFT + width:4] = GRID
        label = _freq_label(float(f))
        draw_text(img, LEFT - 6 - text_width(label), y - 3, label, FG)
    draw_text(img, 2, TOP, "Hz", FG)

    # Time axis.
    step = _nice_step(max(duration, 1e-3), 10)
    t = math.ceil(offset / step) * step
    while t <= offset + duration + 1e-9:
        x = LEFT + int(round((t - offset) / max(duration, 1e-9) * (width - 1)))
        img[TOP + height:TOP + height + 4, x] = FG
        label = _time_label(t, step)
        draw_text(img, max(0, x - text_width(label) // 2), TOP + height + 6, label, FG)
        t += step

    tones = _steady_tones(mean_spec / max(frame, 1), freqs, min_freq, max_freq)
    png = encode_png(img)
    return {
        "png": png,
        "width": img.shape[1],
        "height": img.shape[0],
        "plot_area": {"x": LEFT, "y": TOP, "width": width, "height": height},
        "time_range": [round(offset, 2), round(offset + duration, 2)],
        "freq_range": [round(min_freq, 1), round(max_freq, 1)],
        "freq_scale": "log" if log_freq else "linear",
        "db_range": [round(vmin, 1), round(vmax, 1)],
        "steady_tones": tones,
    }


def _steady_tones(spec: np.ndarray, freqs: np.ndarray, lo: float, hi: float) -> list[dict]:
    if spec.size < 40:
        return []
    out = []
    level = dsp.db(spec + 1e-14, power=True)
    # Ignore peaks in the empty top of a resampled file: a "tone" must carry
    # real energy, not just stand out from a near-silent neighbourhood.
    floor = float(level.max()) - 40.0
    for i in range(1, spec.size - 1):
        f = freqs[i]
        if f < lo or f > hi or level[i] < floor:
            continue
        if level[i] < level[i - 1] or level[i] < level[i + 1]:
            continue
        around = np.concatenate([level[max(0, i - 15): max(0, i - 3)], level[i + 4: i + 16]])
        if around.size < 6:
            continue
        prominence = float(level[i] - np.median(around))
        if prominence >= 15:
            out.append({"freq_hz": round(float(f), 1), "prominence_db": round(prominence, 1)})
    out.sort(key=lambda t: -t["prominence_db"])
    return out[:8]


def spectrogram(path, config: AudioConfig, *, start=None, duration=None, width=1200,
                height=400, min_freq=50.0, max_freq=None, log_freq=True,
                dynamic_range=80.0, total=None) -> dict:
    top = max_freq or 8000.0
    rate = int(min(48000, max(8000, 2 * top)))
    span = duration if duration is not None else max(0.0, (total or 0.0) - (start or 0.0))
    span = min(span or config.max_duration, config.max_duration)
    chunks = dsp.mono_chunks(path, config, start=start, duration=duration, sample_rate=rate)
    return render(chunks, sample_rate=rate, duration=span, offset=start or 0.0, width=width,
                  height=height, min_freq=min_freq, max_freq=top, log_freq=log_freq,
                  dynamic_range=dynamic_range)


__all__ = ["colormap", "draw_text", "encode_png", "render", "spectrogram"]
