"""Unit tests for the signal-processing helpers."""

from __future__ import annotations

import numpy as np

from conftest import write_wav
from hiraraaudio import dsp
from hiraraaudio.config import AudioConfig
from hiraraaudio.media import DecodeStats, decode
from hiraraaudio.tools import Toolset


def test_runs_and_fmt_time():
    assert dsp.runs(np.array([0, 1, 1, 0, 1], dtype=bool)) == [(1, 3), (4, 5)]
    assert dsp.runs(np.zeros(0, dtype=bool)) == []
    assert dsp.fmt_time(83.44) == "1:23.4"
    assert dsp.fmt_time(3725) == "1:02:05.0"


def test_ncc_finds_offset_and_ignores_gain():
    rng = np.random.default_rng(0)
    hay = rng.standard_normal((500, 8))
    needle = hay[200:260] * 3.0 + 1.5
    scores = dsp.ncc_search(hay, needle)
    assert int(np.argmax(scores)) == 200
    assert scores[200] > 0.999
    assert dsp.ncc_search(hay[:10], needle).size == 0


def test_pick_peaks_respects_gap():
    scores = np.array([0.1, 0.9, 0.95, 0.2, 0.0, 0.85, 0.3])
    assert dsp.pick_peaks(scores, 0.8, min_gap=2, limit=5) == [2, 5]


def test_mode_filter_removes_blips():
    assert dsp._mode_filter(["a", "b", "a", "a"]) == ["a", "a", "a", "a"]


def test_merge_short_keeps_bounds():
    segs = [{"start": 0, "end": 1, "kind": "a"}, {"start": 1, "end": 1.5, "kind": "b"},
            {"start": 1.5, "end": 9, "kind": "c"}]
    merged = dsp.merge_short(segs, 2)
    assert len(merged) == 2
    assert merged[0]["start"] == 0 and merged[-1]["end"] == 9


def test_clipping_run_across_chunk_edge(tmp_path):
    sr = 8000
    x = np.zeros(sr * 25)
    edge = sr * 10  # native_stats decodes in 10 s chunks
    x[edge - 2: edge + 3] = 1.0  # 5 full-scale samples straddling the edge
    path = write_wav(tmp_path / "edge.wav", x, sr=sr)
    stats = dsp.native_stats(path, AudioConfig(), sr, 1)
    assert stats.clipped_runs == 1
    assert stats.clipped_samples == 5
    assert abs(stats.clip_times[0] - (edge - 2) / sr) < 1e-3


def test_decode_respects_max_duration(tmp_path):
    path = write_wav(tmp_path / "long.wav", np.zeros(44100 * 5))
    stats = DecodeStats()
    x = decode(path, AudioConfig(max_duration=2.0), stats=stats)
    assert abs(len(x) / 16000 - 2.0) < 0.01
    assert stats.truncated is True


def test_hum_needs_prominent_harmonics():
    spec = np.ones(1001)
    assert dsp.detect_hum(spec) is None
    spec[50] = spec[100] = 1e3
    assert dsp.detect_hum(spec)["mains_hz"] == 50


async def test_url_source_goes_through_the_guard(media):
    ts = Toolset(AudioConfig(allow_url_fetch=True))
    r = await ts.audio_info(audio_url="http://127.0.0.1/a.wav")
    assert r["error"].startswith("audio_url blocked")
