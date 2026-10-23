"""audio_split and audio_tighten."""

from __future__ import annotations

import base64

from hiraraaudio.config import AudioConfig
from hiraraaudio.media import probe


async def test_split_cuts_inside_pauses(toolset, media):
    r = await toolset.audio_split(audio_path=str(media["speech"]), min_seconds=4, max_seconds=9)
    assert r["error"] is None
    segs = r["segments"]
    assert len(segs) >= 3
    assert segs[0]["start"] == 0.0 and segs[-1]["end"] == r["duration"]
    for seg in segs[:-1]:
        assert 4.0 <= seg["duration"] <= 9.0
        assert seg["cut_after"] == "pause"
    # The 3 s pause after the first phrase (6.7..9.7 s) is the natural first cut.
    assert 6.7 <= segs[0]["end"] <= 9.7


async def test_split_writes_files(toolset, media, tmp_path):
    r = await toolset.audio_split(audio_path=str(media["speech"]), min_seconds=4, max_seconds=9,
                                  output_dir=str(tmp_path), output_format="flac")
    assert r["error"] is None
    assert len(r["files"]) == len(r["segments"])
    total = sum(probe(p, AudioConfig()).duration for p in r["files"])
    assert abs(total - r["duration"]) < 0.2


async def test_split_return_audio(toolset, media):
    r = await toolset.audio_split(audio_path=str(media["speech"]), min_seconds=8, max_seconds=15,
                                  return_audio=True)
    assert r["error"] is None
    assert all(base64.b64decode(s["audio_base64"])[:4] == b"RIFF" for s in r["segments"])


async def test_split_rejects_bad_bounds(toolset, media):
    r = await toolset.audio_split(audio_path=str(media["speech"]), min_seconds=10, max_seconds=5)
    assert "min_seconds < max_seconds" in r["error"]


async def test_tighten_dry_run_plans_only(toolset, media):
    r = await toolset.audio_tighten(audio_path=str(media["speech"]), dry_run=True)
    assert r["error"] is None
    assert r["output_path"] is None and r["audio_base64"] is None
    wheres = [p["where"] for p in r["pauses"]]
    assert wheres.count("between") == 2
    assert r["removed_s"] > 4.0


async def test_tighten_renders_and_verifies(toolset, media, tmp_path):
    out = tmp_path / "tight.wav"
    r = await toolset.audio_tighten(audio_path=str(media["speech"]), output_path=str(out),
                                    keep_pause=0.4, min_pause=1.0)
    assert r["error"] is None, r["error"]
    assert out.is_file()
    assert abs(r["verified"]["duration"] - r["planned_duration"]) < 0.1
    assert r["verified"]["longest_inner_pause_s"] <= 1.0
    # Verify with compare: only silence went missing.
    cmp = await toolset.audio_compare(a_path=str(media["speech"]), b_path=str(out))
    assert cmp["similarity"] >= 0.95
    assert {c["type"] for c in cmp["changes"]} <= {"silence_shortened"}


async def test_tighten_keeps_edges_when_asked(toolset, media):
    r = await toolset.audio_tighten(audio_path=str(media["speech"]), edges=False, dry_run=True)
    assert all(p["where"] == "between" for p in r["pauses"])


async def test_tighten_rejects_bad_pauses(toolset, media):
    r = await toolset.audio_tighten(audio_path=str(media["speech"]), min_pause=0.3, keep_pause=0.5)
    assert "keep_pause < min_pause" in r["error"]
