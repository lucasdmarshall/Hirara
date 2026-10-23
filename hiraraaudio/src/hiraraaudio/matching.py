"""audio_find, audio_compare and audio_fingerprint.

Two signal-level techniques, no models:

* Landmark hashes (the constellation method behind music recognition): pairs
  of spectral peaks hashed with their time gap. They survive re-encoding and
  level changes, and a consistent time offset across many shared hashes is
  strong evidence that two recordings share material.
* Normalised cross-correlation of log band energies, for exact placement of
  a known clip, and to verify each hash-proposed alignment.

audio_compare puts them together to tell an agent what an edit did, which it
otherwise has no way to check: which spans survived, which were removed or
inserted, and where silence was shortened.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np

from . import dsp
from .config import AudioConfig

# --- landmark fingerprints ---------------------------------------------------

FP_FFT = 1024
FP_HOP = 256
FP_S = FP_HOP / dsp.ANALYSIS_RATE  # 16 ms
_FP_EDGES = np.geomspace(100, 5000, 7)
_FP_FREQS = np.fft.rfftfreq(FP_FFT, 1 / dsp.ANALYSIS_RATE)
_FP_BANDS = [
    np.flatnonzero((_FP_FREQS >= lo) & (_FP_FREQS < hi))
    for lo, hi in zip(_FP_EDGES[:-1], _FP_EDGES[1:])
]
MAX_DT = 63
FANOUT = 6


@dataclass
class Fingerprint:
    hashes: np.ndarray  # uint32
    times: np.ndarray  # int32, in FP frames
    duration: float

    @property
    def count(self) -> int:
        return int(self.hashes.size)


def fingerprint(chunks: Iterable[np.ndarray]) -> Fingerprint:
    bins_parts, mags_parts = [], []
    total = 0

    def counted(source):
        nonlocal total
        for c in source:
            total += len(c)
            yield c

    for power in dsp.stft_power(counted(chunks), FP_FFT, FP_HOP):
        logp = np.log10(power + 1e-10)
        b = np.zeros((len(power), len(_FP_BANDS)), dtype=np.int32)
        m = np.zeros((len(power), len(_FP_BANDS)), dtype=np.float32)
        for k, idx in enumerate(_FP_BANDS):
            sub = logp[:, idx]
            arg = np.argmax(sub, axis=1)
            b[:, k] = idx[arg]
            m[:, k] = sub[np.arange(len(sub)), arg]
        bins_parts.append(b)
        mags_parts.append(m)

    duration = total / dsp.ANALYSIS_RATE
    if not bins_parts:
        return Fingerprint(np.zeros(0, np.uint32), np.zeros(0, np.int32), duration)
    bins = np.concatenate(bins_parts)
    mags = np.concatenate(mags_parts)

    # A landmark is a band maximum that is also a local maximum over +-3
    # frames in time, and clearly above that band's typical level.
    padded = np.pad(mags, ((3, 3), (0, 0)), constant_values=-np.inf)
    is_peak = np.ones_like(mags, dtype=bool)
    for shift in (1, 2, 3):
        is_peak &= mags >= padded[3 - shift: 3 - shift + len(mags)]
        is_peak &= mags >= padded[3 + shift: 3 + shift + len(mags)]
    floor = np.median(mags, axis=0) + 0.5  # +5 dB in log10 power
    is_peak &= mags > floor
    t_idx, band_idx = np.nonzero(is_peak)
    if t_idx.size < 2:
        return Fingerprint(np.zeros(0, np.uint32), np.zeros(0, np.int32), duration)
    f_idx = bins[t_idx, band_idx]

    hashes, times = [], []
    for k in range(1, FANOUT + 1):
        a, b = t_idx[:-k], t_idx[k:]
        dt = b - a
        ok = (dt >= 1) & (dt <= MAX_DT)
        f1 = f_idx[:-k][ok].astype(np.uint32) & 0x1FF
        f2 = f_idx[k:][ok].astype(np.uint32) & 0x1FF
        hashes.append((f1 << 15) | (f2 << 6) | dt[ok].astype(np.uint32))
        times.append(a[ok].astype(np.int32))
    return Fingerprint(np.concatenate(hashes), np.concatenate(times), duration)


def file_fingerprint(path, config: AudioConfig, *, start=None, duration=None) -> Fingerprint:
    return fingerprint(dsp.mono_chunks(path, config, start=start, duration=duration))


def hash_pairs(a: Fingerprint, b: Fingerprint, max_bucket: int = 20) -> tuple[np.ndarray, np.ndarray]:
    """Matching hash pairs as (time in a, offset b - a), both in FP frames."""
    if a.count == 0 or b.count == 0:
        return np.zeros(0, np.int32), np.zeros(0, np.int32)
    order = np.argsort(b.hashes, kind="stable")
    hb, tb = b.hashes[order], b.times[order]
    lo = np.searchsorted(hb, a.hashes, "left")
    hi = np.searchsorted(hb, a.hashes, "right")
    cnt = hi - lo
    keep = (cnt > 0) & (cnt <= max_bucket)
    if not keep.any():
        return np.zeros(0, np.int32), np.zeros(0, np.int32)
    cnt_k = cnt[keep]
    rep_a = np.repeat(np.flatnonzero(keep), cnt_k)
    starts = np.repeat(lo[keep], cnt_k)
    within = np.arange(cnt_k.sum()) - np.repeat(np.cumsum(cnt_k) - cnt_k, cnt_k)
    t_a = a.times[rep_a]
    return t_a, tb[starts + within] - t_a


@dataclass
class Alignment:
    votes: int
    offset_s: float
    a_span: tuple[float, float]
    score: float


def best_alignment(a: Fingerprint, b: Fingerprint) -> Alignment | None:
    t_a, d = hash_pairs(a, b)
    if d.size == 0:
        return None
    # Allow +-1 frame of jitter by voting into 2-frame bins.
    keys = np.floor_divide(d, 2)
    uniq, counts = np.unique(keys, return_counts=True)
    i = int(np.argmax(counts))
    sel = keys == uniq[i]
    votes = int(counts[i])
    offset = float(np.median(d[sel])) * FP_S
    span = (float(t_a[sel].min()) * FP_S, float(t_a[sel].max()) * FP_S)
    score = votes / max(1, min(a.count, b.count))
    return Alignment(votes, offset, span, score)


def relation(a: Fingerprint, b: Fingerprint, *, min_votes: int = 10,
             min_score: float = 0.05) -> dict | None:
    """How ``b`` relates to ``a``: duplicate, contains, contained_in, overlaps."""
    al = best_alignment(a, b)
    if al is None or al.votes < min_votes or al.score < min_score:
        return None
    covered = max(0.0, al.a_span[1] - al.a_span[0])
    b_start = al.a_span[0] + al.offset_s
    # Hash times are anchor times; the last anchor's partner sits up to
    # MAX_DT frames later, so the matched span runs about that much longer.
    reach = covered + MAX_DT * FP_S
    cover_a = reach / max(a.duration, 1e-6)
    cover_b = reach / max(b.duration, 1e-6)
    if cover_a >= 0.8 and cover_b >= 0.8:
        kind = "duplicate"
    elif cover_a >= 0.8:
        kind = "contained_in"  # all of a is inside b
    elif cover_b >= 0.8:
        kind = "contains"  # all of b is inside a
    else:
        kind = "overlaps"
    return {
        "relation": kind,
        "offset_s": round(al.offset_s, 2),
        "a_span": [round(al.a_span[0], 2), round(al.a_span[1], 2)],
        "b_span": [round(max(0.0, b_start), 2), round(max(0.0, b_start + covered), 2)],
        "votes": al.votes,
        "score": round(min(1.0, al.score), 3),
    }


# --- band-feature matching ---------------------------------------------------

@dataclass
class MatchFeatures:
    feats: np.ndarray  # (frames, bands), 10 ms frames
    level_db: np.ndarray  # frame RMS in dB
    duration: float

    @property
    def frames(self) -> int:
        return len(self.feats)


def match_features(path, config: AudioConfig, *, start=None, duration=None) -> MatchFeatures:
    total = 0
    levels = []

    def tee(source):
        nonlocal total
        carry = np.zeros(0, dtype=np.float32)
        for c in source:
            total += len(c)
            buf = np.concatenate([carry, c])
            if len(buf) >= dsp.MATCH_FFT:
                count = (len(buf) - dsp.MATCH_FFT) // dsp.MATCH_HOP + 1
                view = np.lib.stride_tricks.sliding_window_view(buf, dsp.MATCH_FFT)
                frames = view[:: dsp.MATCH_HOP][:count]
                levels.append(dsp.db(np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1))))
                carry = buf[count * dsp.MATCH_HOP:]
            else:
                carry = buf
            yield c

    feats = dsp.band_features(tee(dsp.mono_chunks(path, config, start=start, duration=duration)))
    level = np.concatenate(levels) if levels else np.zeros(0)
    n = min(len(feats), len(level))
    return MatchFeatures(feats[:n], level[:n], total / dsp.ANALYSIS_RATE)


def find_clip(hay: MatchFeatures, clip: MatchFeatures, *, threshold: float,
              max_matches: int) -> list[dict]:
    scores = dsp.ncc_search(hay.feats, clip.feats)
    if scores.size == 0:
        return []
    peaks = dsp.pick_peaks(scores, threshold, max(1, int(clip.frames * 0.8)), max_matches)
    dur = clip.frames * dsp.MATCH_S
    return [
        {
            "start": round(i * dsp.MATCH_S, 2),
            "end": round(i * dsp.MATCH_S + dur, 2),
            "score": round(float(scores[i]), 3),
        }
        for i in peaks
    ]


# --- audio_compare -------------------------------------------------------------

WINDOW_S = 1.5
MATCH_SCORE = 0.85


def _silent(level: np.ndarray, threshold: float) -> bool:
    return level.size == 0 or float(np.mean(level < threshold)) >= 0.8


def _threshold(level: np.ndarray) -> float:
    if level.size == 0:
        return -50.0
    return float(np.clip(np.percentile(level, 5) + 12.0, -60.0, -35.0))


def _span_level(level: np.ndarray, a: int, b: int) -> float | None:
    seg = level[max(0, a): max(a + 1, b)]
    if seg.size == 0:
        return None
    return float(dsp.db(np.mean(10 ** (seg / 10)), power=True))


def compare(a_mf: MatchFeatures, b_mf: MatchFeatures, a_fp: Fingerprint,
            b_fp: Fingerprint) -> dict:
    """Align ``b`` against ``a`` window by window and describe the edit."""
    w = int(round(WINDOW_S / dsp.MATCH_S))
    thr_a, thr_b = _threshold(a_mf.level_db), _threshold(b_mf.level_db)
    t_a, d = hash_pairs(a_fp, b_fp)
    t_a_s = t_a * FP_S
    d_s = d * FP_S

    windows = []  # (a_start_frame, a_end_frame, offset_frames | None, score, silent)
    prev_offset: int | None = None
    starts = list(range(0, a_mf.frames, w))
    if len(starts) > 1 and a_mf.frames - starts[-1] < w:
        starts.pop()  # fold a short tail into the last full window
    for k, start in enumerate(starts):
        end = starts[k + 1] if k + 1 < len(starts) else a_mf.frames
        if _silent(a_mf.level_db[start:end], thr_a):
            windows.append((start, end, None, 0.0, True))
            continue
        candidates = []
        sel = (t_a_s >= start * dsp.MATCH_S) & (t_a_s < end * dsp.MATCH_S)
        if sel.sum() >= 3:
            keys, counts = np.unique(np.round(d_s[sel] / dsp.MATCH_S).astype(int) // 2,
                                     return_counts=True)
            for k in keys[np.argsort(counts)[::-1][:3]]:
                candidates.append(int(k) * 2)
        if prev_offset is not None:
            candidates.append(prev_offset)
        best = (None, 0.0)
        needle = a_mf.feats[start:end]
        for cand in dict.fromkeys(candidates):
            lo = max(0, start + cand - 30)
            hi = min(b_mf.frames, start + cand + (end - start) + 30)
            if hi - lo < end - start:
                continue
            scores = dsp.ncc_search(b_mf.feats[lo:hi], needle)
            if scores.size == 0:
                continue
            i = int(np.argmax(scores))
            if scores[i] > best[1]:
                best = (lo + i - start, float(scores[i]))
        # True matches score ~0.95+ even after lossy re-encoding; a looser bar
        # lets similar-sounding material elsewhere pass for a match.
        if best[0] is not None and best[1] >= MATCH_SCORE:
            prev_offset = best[0]
            windows.append((start, end, best[0], best[1], False))
        else:
            windows.append((start, end, None, best[1], False))

    # Group matched windows with a steady offset into aligned spans.
    spans: list[dict] = []
    for start, end, off, score, silent in windows:
        if off is None:
            continue
        if spans and abs(spans[-1]["offset"] - off) <= 3 and spans[-1]["a_end"] >= start - 4 * w:
            spans[-1]["a_end"] = end
            spans[-1]["scores"].append(score)
            spans[-1]["offset"] = off
        else:
            spans.append({"a_start": start, "a_end": end, "offset": off, "scores": [score]})

    S = dsp.MATCH_S
    changes: list[dict] = []
    aligned = []
    chain = _in_order(spans, slack=w)
    _refine_edges(chain, a_mf, b_mf, thr_a, thr_b)
    for sp in spans:
        a0, a1 = sp["a_start"], sp["a_end"]
        b0, b1 = a0 + sp["offset"], a1 + sp["offset"]
        la, lb = _span_level(a_mf.level_db, a0, a1), _span_level(b_mf.level_db, b0, b1)
        gain = None if la is None or lb is None else round(lb - la, 1)
        aligned.append({
            "a_start": round(a0 * S, 2), "a_end": round(a1 * S, 2),
            "b_start": round(b0 * S, 2), "b_end": round(b1 * S, 2),
            "score": round(float(np.mean(sp["scores"])), 3),
            "level_change_db": gain,
        })
        if sp not in chain:
            # Matched, but out of order relative to the rest: the material was
            # moved, or a repeat of it elsewhere in b is the closest match.
            changes.append({"type": "moved", "a_start": round(a0 * S, 2),
                            "a_end": round(a1 * S, 2), "b_start": round(b0 * S, 2),
                            "b_end": round(b1 * S, 2),
                            "detail": "found in b out of order (moved, or repeated material)"})
        elif gain is not None and abs(gain) >= 1.0:
            changes.append({"type": "level_changed", "a_start": round(a0 * S, 2),
                            "a_end": round(a1 * S, 2), "detail": f"{gain:+.1f} dB"})
    spans = chain

    def describe_gap(a0, a1, b0, b1):
        # b_len can be negative when neighbouring spans overlap in b (see
        # _in_order); that is material removed right at a span edge.
        a_len, b_len = (a1 - a0) * S, (b1 - b0) * S
        a_silent = _silent(a_mf.level_db[a0:a1], thr_a) if a1 > a0 else True
        b_silent = _silent(b_mf.level_db[max(0, b0):max(0, b1)], thr_b) if b1 > b0 else True
        base = {"a_start": round(a0 * S, 2), "a_end": round(a1 * S, 2),
                "b_start": round(max(0, b0) * S, 2), "b_end": round(max(0, b0, b1) * S, 2)}
        if abs(a_len) < 0.15 and abs(b_len) < 0.15:
            return None
        if a_silent and b_silent:
            diff = b_len - a_len
            if abs(diff) < 0.15:
                return None
            kind = "silence_shortened" if diff < 0 else "silence_lengthened"
            return {**base, "type": kind, "detail": f"{abs(diff):.2f}s"}
        if a_len < 0.15 or (a_silent and not b_silent):
            return {**base, "type": "inserted", "detail": f"{b_len:.2f}s new in b"}
        if b_len < 0.15 or b_silent:
            return {**base, "type": "removed",
                    "detail": f"{a_len - max(0.0, b_len):.2f}s of a is not in b"}
        return {**base, "type": "changed", "detail": f"{a_len:.2f}s in a became {b_len:.2f}s in b"}

    if spans:
        first, last = spans[0], spans[-1]
        gaps = [(0, first["a_start"], 0, first["a_start"] + first["offset"])]
        for s1, s2 in zip(spans, spans[1:]):
            gaps.append((s1["a_end"], s2["a_start"], s1["a_end"] + s1["offset"],
                         s2["a_start"] + s2["offset"]))
        gaps.append((last["a_end"], a_mf.frames, last["a_end"] + last["offset"], b_mf.frames))
        for g in gaps:
            item = describe_gap(*g)
            if item:
                changes.append(item)
    changes.sort(key=lambda c: c["a_start"])

    # Similarity: share of a's non-silent frames that sit inside an aligned span.
    sounding = a_mf.level_db >= thr_a
    covered = np.zeros(a_mf.frames, dtype=bool)
    for sp in spans:
        covered[sp["a_start"]:sp["a_end"]] = True
    content = int(sounding.sum())
    matched = int((sounding & covered).sum())
    return {
        "aligned": aligned,
        "changes": changes,
        "matched_s": round(matched * S, 2),
        "a_content_s": round(content * S, 2),
        "similarity": round(matched / content, 3) if content else None,
        "offset_s": round(spans[0]["offset"] * S, 2) if spans else None,
    }


def _frames_agree(a_mf: MatchFeatures, b_mf: MatchFeatures, i: int, j: int, gain: float,
                  thr_a: float, thr_b: float) -> bool:
    if j < 0 or j >= b_mf.frames or i < 0 or i >= a_mf.frames:
        return False
    la, lb = a_mf.level_db[i], b_mf.level_db[j]
    if la < thr_a and lb < thr_b:
        return True
    if la < thr_a or lb < thr_b or abs(la + gain - lb) > 4.0:
        return False
    fa, fb = a_mf.feats[i], b_mf.feats[j]
    denom = float(np.linalg.norm(fa) * np.linalg.norm(fb))
    return denom > 0 and float(fa @ fb) / denom >= 0.9


def _refine_edges(chain: list[dict], a_mf: MatchFeatures, b_mf: MatchFeatures,
                  thr_a: float, thr_b: float, patience: int = 3) -> None:
    """Grow each span frame by frame into the unmatched gap beside it.

    Spans come from whole comparison windows, so a window holding the end of
    a phrase plus a pause that was shortened fails to match as a whole. Its
    frames still agree at the span's offset up to the actual cut, so walking
    the edges outward places each change to the frame (10 ms).
    """
    for k, sp in enumerate(chain):
        off = sp["offset"]
        a0, a1 = sp["a_start"], sp["a_end"]
        both = (a_mf.level_db[a0:a1] >= thr_a)
        if both.any():
            j = np.clip(np.arange(a0, a1)[both] + off, 0, b_mf.frames - 1)
            gain = float(np.median(b_mf.level_db[j] - a_mf.level_db[a0:a1][both]))
        else:
            gain = 0.0
        limit_hi = chain[k + 1]["a_start"] if k + 1 < len(chain) else a_mf.frames
        limit_lo = chain[k - 1]["a_end"] if k > 0 else 0
        i, last, misses = a1, a1, 0
        while i < limit_hi and misses < patience:
            if _frames_agree(a_mf, b_mf, i, i + off, gain, thr_a, thr_b):
                last, misses = i + 1, 0
            else:
                misses += 1
            i += 1
        sp["a_end"] = last
        i, first, misses = a0 - 1, a0, 0
        while i >= limit_lo and misses < patience:
            if _frames_agree(a_mf, b_mf, i, i + off, gain, thr_a, thr_b):
                first, misses = i, 0
            else:
                misses += 1
            i -= 1
        sp["a_start"] = first


def _in_order(spans: list[dict], slack: int) -> list[dict]:
    """Longest-duration subsequence of spans (in a order) that also runs
    forward in b. Everything else is reported as moved.

    ``slack`` frames of overlap are allowed: span edges are only as precise
    as the comparison window, so a span that ends in removed silence can
    reach slightly past where the next one starts in b.
    """
    if not spans:
        return []
    n = len(spans)
    weight = [sp["a_end"] - sp["a_start"] for sp in spans]
    best = list(weight)
    prev = [-1] * n
    for i in range(n):
        bi = spans[i]["a_start"] + spans[i]["offset"]
        for j in range(i):
            bj_end = spans[j]["a_end"] + spans[j]["offset"]
            if bj_end <= bi + slack and best[j] + weight[i] > best[i]:
                best[i] = best[j] + weight[i]
                prev[i] = j
    i = max(range(n), key=lambda k: best[k])
    keep = []
    while i != -1:
        keep.append(spans[i])
        i = prev[i]
    return keep[::-1]


__all__ = [
    "Fingerprint",
    "MatchFeatures",
    "compare",
    "file_fingerprint",
    "find_clip",
    "fingerprint",
    "match_features",
    "relation",
]
