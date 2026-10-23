"""Signal processing shared by the audio tools. NumPy only, no models.

Everything here works on streamed chunks so a long file is analysed in one
pass with bounded memory. The results are small (a few floats per 20 ms
frame), which is what lets the tools hand an agent a summary instead of
samples.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

import numpy as np

from .config import AudioConfig
from .media import DecodeStats, decode_chunks

ANALYSIS_RATE = 16000
FRAME = 320  # 20 ms at 16 kHz
FRAME_S = FRAME / ANALYSIS_RATE
HUM_MAX_HZ = 1000
EPS = 1e-12


def db(power_or_amp: np.ndarray | float, *, power: bool = False) -> np.ndarray | float:
    value = np.maximum(np.asarray(power_or_amp, dtype=np.float64), EPS)
    return (10.0 if power else 20.0) * np.log10(value)


def fmt_time(seconds: float) -> str:
    """``83.4`` -> ``1:23.4``; hours appear only when needed."""
    seconds = max(0.0, float(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours >= 1:
        return f"{int(hours)}:{int(minutes):02d}:{secs:04.1f}"
    return f"{int(minutes)}:{secs:04.1f}"


def mono_chunks(path, config: AudioConfig, *, start=None, duration=None,
                stats: DecodeStats | None = None, sample_rate: int = ANALYSIS_RATE,
                chunk_seconds: float = 30.0) -> Iterator[np.ndarray]:
    for chunk in decode_chunks(path, config, sample_rate=sample_rate, channels=1,
                               start=start, duration=duration, stats=stats,
                               chunk_seconds=chunk_seconds):
        yield chunk[:, 0]


def stft_power(chunks: Iterable[np.ndarray], n_fft: int, hop: int) -> Iterator[np.ndarray]:
    """Power spectra of Hann-windowed frames, streamed across chunk edges."""
    window = np.hanning(n_fft).astype(np.float32)
    carry = np.zeros(0, dtype=np.float32)
    for chunk in chunks:
        buf = np.concatenate([carry, chunk.astype(np.float32, copy=False)])
        if len(buf) < n_fft:
            carry = buf
            continue
        count = (len(buf) - n_fft) // hop + 1
        view = np.lib.stride_tricks.sliding_window_view(buf, n_fft)[::hop][:count]
        spec = np.fft.rfft(view * window, axis=1)
        yield (spec.real ** 2 + spec.imag ** 2).astype(np.float32)
        carry = buf[count * hop:]


# --- frame features ----------------------------------------------------------

@dataclass
class Features:
    """Per-20 ms descriptors of a mono 16 kHz signal."""

    rms_db: np.ndarray
    zcr: np.ndarray
    flatness: np.ndarray
    centroid: np.ndarray
    hum_spectrum: np.ndarray | None  # mean power, 1 Hz bins, 0..HUM_MAX_HZ
    duration: float
    truncated: bool = False

    @property
    def frames(self) -> int:
        return len(self.rms_db)

    def time(self, index: int) -> float:
        return index * FRAME_S


class HumAccumulator:
    """Mean power spectrum at 1 Hz resolution up to HUM_MAX_HZ, built from
    whole one-second blocks of a 16 kHz stream."""

    def __init__(self) -> None:
        self._acc = np.zeros(HUM_MAX_HZ + 1)
        self._count = 0
        self._carry = np.zeros(0, dtype=np.float32)
        self._window = np.hanning(ANALYSIS_RATE)

    def update(self, chunk: np.ndarray) -> None:
        buf = np.concatenate([self._carry, chunk])
        blocks = len(buf) // ANALYSIS_RATE
        if blocks:
            seconds = buf[: blocks * ANALYSIS_RATE].reshape(blocks, ANALYSIS_RATE)
            spec = np.abs(np.fft.rfft(seconds * self._window, axis=1)) ** 2
            self._acc += spec[:, : HUM_MAX_HZ + 1].sum(axis=0)
            self._count += blocks
        self._carry = buf[blocks * ANALYSIS_RATE:]

    def spectrum(self) -> np.ndarray | None:
        return self._acc / self._count if self._count else None


def extract_features(chunks: Iterable[np.ndarray], *, hum: bool = True,
                     stats: DecodeStats | None = None) -> Features:
    rms_parts, zcr_parts, flat_parts, cent_parts = [], [], [], []
    freqs = np.fft.rfftfreq(FRAME, 1 / ANALYSIS_RATE)
    window = np.hanning(FRAME)
    hum_acc = HumAccumulator() if hum else None
    carry = np.zeros(0, dtype=np.float32)
    total = 0

    for chunk in chunks:
        total += len(chunk)
        buf = np.concatenate([carry, chunk])
        usable = len(buf) - len(buf) % FRAME
        carry = buf[usable:]
        if usable:
            frames = buf[:usable].reshape(-1, FRAME).astype(np.float64)
            rms_parts.append(db(np.sqrt(np.mean(frames ** 2, axis=1))))
            signs = np.signbit(frames)
            zcr_parts.append(np.mean(signs[:, 1:] != signs[:, :-1], axis=1))
            power = np.abs(np.fft.rfft(frames * window, axis=1)) ** 2 + EPS
            body = power[:, 1:]
            flat_parts.append(
                np.exp(np.mean(np.log(body), axis=1)) / np.mean(body, axis=1)
            )
            cent_parts.append((power * freqs).sum(axis=1) / power.sum(axis=1))

        if hum_acc is not None:
            hum_acc.update(chunk)

    def cat(parts):
        return np.concatenate(parts) if parts else np.zeros(0)

    return Features(
        rms_db=cat(rms_parts),
        zcr=cat(zcr_parts),
        flatness=cat(flat_parts),
        centroid=cat(cent_parts),
        hum_spectrum=hum_acc.spectrum() if hum_acc is not None else None,
        duration=total / ANALYSIS_RATE,
        truncated=bool(stats and stats.truncated),
    )


def analyse(path, config: AudioConfig, *, start=None, duration=None, hum: bool = True) -> Features:
    stats = DecodeStats()
    return extract_features(
        mono_chunks(path, config, start=start, duration=duration, stats=stats),
        hum=hum,
        stats=stats,
    )


# --- levels and silence ------------------------------------------------------

DIGITAL_SILENCE_DB = -100.0


def noise_floor_db(features: Features) -> float | None:
    """10th percentile of frame level, ignoring digital silence."""
    live = features.rms_db[features.rms_db > DIGITAL_SILENCE_DB]
    if live.size == 0:
        return None
    return float(np.percentile(live, 10))


def silence_threshold(features: Features, override: float | None = None) -> float:
    """Level below which a frame counts as silence.

    Adaptive: a little above the recording's own noise floor, clamped so a
    clean studio file and a noisy phone call both get a sensible line.
    """
    if override is not None:
        return float(override)
    if features.frames == 0:
        return -50.0
    floor = float(np.percentile(features.rms_db, 5))
    return float(np.clip(floor + 12.0, -60.0, -35.0))


def runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """``[start, end)`` index pairs of consecutive True values."""
    if mask.size == 0:
        return []
    padded = np.concatenate([[False], mask.astype(bool), [False]])
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    return list(zip(edges[0::2].tolist(), edges[1::2].tolist()))


def silences(features: Features, threshold: float, min_seconds: float) -> list[tuple[float, float]]:
    """Silent spans at least ``min_seconds`` long, in seconds."""
    min_frames = max(1, int(round(min_seconds / FRAME_S)))
    out = []
    for a, b in runs(features.rms_db < threshold):
        if b - a >= min_frames:
            out.append((a * FRAME_S, b * FRAME_S))
    return out


def smooth_level(features: Features, seconds: float) -> np.ndarray:
    """Mean power (as dB) over a centred window, for picking quiet points."""
    n = max(1, int(round(seconds / FRAME_S)))
    power = 10 ** (features.rms_db / 10)
    kernel = np.ones(n) / n
    return db(np.convolve(power, kernel, mode="same"), power=True)


# --- content classification -------------------------------------------------

KINDS = ("silence", "speech", "music", "noise", "tones")


def classify_seconds(features: Features, threshold: float,
                     tonal: np.ndarray | None = None) -> list[str]:
    """One label per second: silence, speech, music, noise or tones.

    Classic feature heuristics, not a model, and labelled as an estimate in
    every tool that shows them. Speech alternates syllables and short gaps, so
    its energy keeps dipping (high low-energy ratio) and its zero-crossing
    rate jumps between voiced and unvoiced sounds. Music holds its energy and
    tonality. Noise is flat-spectrum and steady.
    """
    per = int(round(1.0 / FRAME_S))
    labels: list[str] = []
    for start in range(0, features.frames, per):
        sl = slice(start, start + per)
        level = features.rms_db[sl]
        if level.size < per // 4:
            break
        active = level > threshold
        if active.mean() < 0.3:
            labels.append("silence")
            continue
        if tonal is not None and tonal[sl].size and tonal[sl][active[: tonal[sl].size]].mean() >= 0.5:
            labels.append("tones")
            continue
        energy = 10 ** (level / 10)
        lster = float(np.mean(energy < 0.5 * energy.mean()))
        zcr = features.zcr[sl]
        hzcrr = float(np.mean(zcr > 1.5 * max(zcr.mean(), EPS)))
        flat = float(np.median(features.flatness[sl][active]))
        spread = float(np.std(level[active]))
        if flat > 0.3 and spread < 4.0:
            labels.append("noise")
        elif lster > 0.3 or (hzcrr > 0.12 and spread > 5.0) or (1 - active.mean()) > 0.15:
            labels.append("speech")
        else:
            labels.append("music")
    return _mode_filter(labels)


def _mode_filter(labels: list[str]) -> list[str]:
    """Remove one-second blips: a label differing from both neighbours that
    agree with each other takes their value."""
    out = list(labels)
    for i in range(1, len(labels) - 1):
        if labels[i - 1] == labels[i + 1] != labels[i]:
            out[i] = labels[i - 1]
    return out


def segments_from_labels(labels: list[str], duration: float) -> list[dict]:
    segs: list[dict] = []
    for i, label in enumerate(labels):
        start = float(i)
        end = min(float(i + 1), duration)
        if segs and segs[-1]["kind"] == label:
            segs[-1]["end"] = end
        else:
            segs.append({"start": start, "end": end, "kind": label})
    if segs:
        segs[-1]["end"] = duration
    return segs


def merge_short(segs: list[dict], limit: int) -> list[dict]:
    """Fold the shortest segments into a neighbour until at most ``limit`` remain."""
    segs = [dict(s) for s in segs]
    while len(segs) > max(1, limit):
        lengths = [s["end"] - s["start"] for s in segs]
        i = int(np.argmin(lengths))
        if i == 0:
            j = 1
        elif i == len(segs) - 1:
            j = i - 1
        else:
            left = segs[i - 1]["end"] - segs[i - 1]["start"]
            right = segs[i + 1]["end"] - segs[i + 1]["start"]
            j = i - 1 if left >= right else i + 1
        lo, hi = min(i, j), max(i, j)
        keep = segs[j]["kind"]
        segs[lo] = {"start": segs[lo]["start"], "end": segs[hi]["end"], "kind": keep}
        del segs[hi]
        # Neighbours may now share a kind.
        k = 1
        while k < len(segs):
            if segs[k]["kind"] == segs[k - 1]["kind"]:
                segs[k - 1]["end"] = segs[k]["end"]
                del segs[k]
            else:
                k += 1
    return segs


def segment_level(features: Features, start: float, end: float) -> float | None:
    a, b = int(start / FRAME_S), max(int(start / FRAME_S) + 1, int(end / FRAME_S))
    level = features.rms_db[a:b]
    if level.size == 0:
        return None
    return float(db(np.mean(10 ** (level / 10)), power=True))


# --- mains hum ---------------------------------------------------------------

def detect_hum(spectrum: np.ndarray | None, *, min_prominence: float = 10.0) -> dict | None:
    """50 or 60 Hz mains hum from a 1 Hz-resolution mean power spectrum.

    Looks at the fundamental and harmonics: hum often shows more at 100/120 Hz
    or 150/180 Hz than at the fundamental itself.
    """
    if spectrum is None or spectrum.size < 400:
        return None
    best = None
    for base in (50, 60):
        found = []
        for k in range(1, 7):
            f = base * k
            if f + 12 >= spectrum.size:
                break
            peak = spectrum[f - 1: f + 2].max()
            around = np.concatenate([spectrum[f - 12: f - 3], spectrum[f + 4: f + 13]])
            prominence = float(db(peak / (np.median(around) + EPS), power=True))
            if prominence >= min_prominence:
                found.append({"freq_hz": f, "prominence_db": round(prominence, 1)})
        if len(found) >= 2 or any(h["freq_hz"] == base for h in found):
            score = sum(h["prominence_db"] for h in found)
            if best is None or score > best["score"]:
                best = {"score": score, "mains_hz": base, "harmonics": found}
    if best is None:
        return None
    best.pop("score")
    return best


# --- full-resolution statistics ---------------------------------------------

@dataclass
class NativeStats:
    sample_rate: int
    channels: int
    duration: float
    peak_dbfs: float | None
    rms_dbfs: float | None
    dc_offset: list[float]
    clipped_runs: int
    clipped_samples: int
    clip_times: list[float] = field(default_factory=list)
    channel_correlation: float | None = None
    truncated: bool = False


def native_stats(path, config: AudioConfig, sample_rate: int, channels: int,
                 *, start=None, duration=None) -> NativeStats:
    """Peak, RMS, DC, clipping and stereo correlation at the source's own rate.

    Clipping must be judged here: resampling smears the flat tops that give
    it away.
    """
    stats = DecodeStats()
    n = 0
    sums = np.zeros(channels)
    squares = np.zeros(channels)
    cross = 0.0
    peak = 0.0
    clipped_runs = 0
    clipped_samples = 0
    clip_times: list[float] = []
    # A run of full-scale samples can straddle a chunk edge; carry it over.
    carry_len = 0
    carry_start = 0

    def count(length: int, first: int) -> None:
        nonlocal clipped_runs, clipped_samples
        if length >= 3:
            clipped_runs += 1
            clipped_samples += length
            if len(clip_times) < 50:
                clip_times.append(round(first / sample_rate, 3))

    for chunk in decode_chunks(path, config, sample_rate=None, channels=None,
                               native_rate=sample_rate, start=start,
                               duration=duration, stats=stats, chunk_seconds=10.0):
        if chunk.shape[1] != channels:
            channels = chunk.shape[1]
            sums = np.zeros(channels)
            squares = np.zeros(channels)
        x = chunk.astype(np.float64)
        sums += x.sum(axis=0)
        squares += (x ** 2).sum(axis=0)
        if channels >= 2:
            cross += float((x[:, 0] * x[:, 1]).sum())
        peak = max(peak, float(np.abs(x).max(initial=0.0)))
        hot = (np.abs(x) >= 0.999).any(axis=1)
        if carry_len and not hot[:1].any():
            count(carry_len, carry_start)
            carry_len = 0
        for a, b in runs(hot):
            length, first = b - a, n + a
            if a == 0 and carry_len:
                length += carry_len
                first = carry_start
                carry_len = 0
            if b == len(hot):
                carry_len, carry_start = length, first
                continue
            count(length, first)
        n += len(x)
    if carry_len:
        count(carry_len, carry_start)

    if n == 0:
        return NativeStats(sample_rate, channels, 0.0, None, None, [0.0] * channels, 0, 0)
    mean_square = float(squares.mean() / n)
    corr = None
    if channels >= 2 and squares[0] > 0 and squares[1] > 0:
        corr = float(cross / np.sqrt(squares[0] * squares[1]))
    return NativeStats(
        sample_rate=sample_rate,
        channels=channels,
        duration=n / sample_rate,
        peak_dbfs=float(db(peak)) if peak > 0 else None,
        rms_dbfs=float(db(mean_square, power=True)) if mean_square > 0 else None,
        dc_offset=[round(float(s / n), 5) for s in sums],
        clipped_runs=clipped_runs,
        clipped_samples=clipped_samples,
        clip_times=clip_times,
        channel_correlation=None if corr is None else round(corr, 3),
        truncated=stats.truncated,
    )


# --- band features and matching ---------------------------------------------

MATCH_HOP = 160  # 10 ms
MATCH_FFT = 512
MATCH_BANDS = 24
MATCH_S = MATCH_HOP / ANALYSIS_RATE


def _band_matrix(n_fft: int, bands: int, lo: float = 150.0, hi: float = 5000.0) -> np.ndarray:
    freqs = np.fft.rfftfreq(n_fft, 1 / ANALYSIS_RATE)
    edges = np.geomspace(lo, hi, bands + 1)
    m = np.zeros((freqs.size, bands), dtype=np.float32)
    for b in range(bands):
        sel = (freqs >= edges[b]) & (freqs < edges[b + 1])
        if not sel.any():
            sel[np.argmin(np.abs(freqs - edges[b]))] = True
        m[sel, b] = 1.0 / sel.sum()
    return m


_BANDS = _band_matrix(MATCH_FFT, MATCH_BANDS)


def band_features(chunks: Iterable[np.ndarray]) -> np.ndarray:
    """Log band energies, 10 ms frames, gain-normalised per frame.

    Subtracting each frame's mean log energy makes the features ignore an
    overall level change, so a clip still matches after normalisation.
    """
    parts = []
    for power in stft_power(chunks, MATCH_FFT, MATCH_HOP):
        bands = np.log10(power @ _BANDS + 1e-9)
        parts.append(bands.astype(np.float32))
    if not parts:
        return np.zeros((0, MATCH_BANDS), dtype=np.float32)
    feats = np.concatenate(parts)
    return feats - feats.mean(axis=1, keepdims=True)


def frame_energy_db(chunks: Iterable[np.ndarray]) -> np.ndarray:
    """Frame level in dB at the matching frame rate (for silence masks)."""
    parts = []
    for power in stft_power(chunks, MATCH_FFT, MATCH_HOP):
        parts.append(db(power.sum(axis=1) / (MATCH_FFT * MATCH_FFT / 8), power=True))
    return np.concatenate(parts) if parts else np.zeros(0)


def ncc_search(hay: np.ndarray, needle: np.ndarray) -> np.ndarray:
    """Normalised cross-correlation of ``needle`` at every offset in ``hay``.

    Both are ``(frames, bands)``. Returns one score in [-1, 1] per offset.
    Computed band by band with FFTs, so an hour-long haystack stays cheap.
    """
    th, tn = len(hay), len(needle)
    if tn == 0 or th < tn:
        return np.zeros(0)
    n = needle.astype(np.float64) - needle.mean()
    norm_n = float(np.sqrt((n ** 2).sum()))
    if norm_n < EPS:
        return np.zeros(th - tn + 1)
    size = 1 << int(np.ceil(np.log2(th + tn)))
    acc = np.zeros(size // 2 + 1, dtype=np.complex128)
    for b in range(hay.shape[1]):
        acc += np.fft.rfft(hay[:, b].astype(np.float64), size) * np.fft.rfft(n[::-1, b], size)
    num = np.fft.irfft(acc, size)[tn - 1: th]
    h = hay.astype(np.float64)
    rows = h.sum(axis=1)
    rows2 = (h ** 2).sum(axis=1)
    cs = np.concatenate([[0.0], np.cumsum(rows)])
    cq = np.concatenate([[0.0], np.cumsum(rows2)])
    window_sum = cs[tn:] - cs[:-tn]
    window_sq = cq[tn:] - cq[:-tn]
    var = np.maximum(window_sq - window_sum ** 2 / (tn * hay.shape[1]), 0.0)
    denom = np.sqrt(var) * norm_n
    with np.errstate(divide="ignore", invalid="ignore"):
        scores = np.where(denom > 1e-9, num / denom, 0.0)
    return np.clip(scores, -1.0, 1.0)


def pick_peaks(scores: np.ndarray, threshold: float, min_gap: int, limit: int) -> list[int]:
    """Indices of the best scores above ``threshold``, at least ``min_gap`` apart."""
    order = np.argsort(scores)[::-1]
    taken: list[int] = []
    for idx in order:
        if scores[idx] < threshold or len(taken) >= limit:
            break
        if all(abs(int(idx) - t) >= min_gap for t in taken):
            taken.append(int(idx))
    return sorted(taken)


__all__ = [
    "ANALYSIS_RATE",
    "FRAME_S",
    "Features",
    "HumAccumulator",
    "MATCH_S",
    "NativeStats",
    "analyse",
    "band_features",
    "classify_seconds",
    "db",
    "detect_hum",
    "extract_features",
    "fmt_time",
    "frame_energy_db",
    "merge_short",
    "mono_chunks",
    "native_stats",
    "ncc_search",
    "noise_floor_db",
    "pick_peaks",
    "runs",
    "segment_level",
    "segments_from_labels",
    "silence_threshold",
    "silences",
    "smooth_level",
    "stft_power",
]
