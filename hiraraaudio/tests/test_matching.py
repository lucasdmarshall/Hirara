"""audio_compare, audio_find and audio_fingerprint."""

from __future__ import annotations

import subprocess
import wave

import numpy as np
import pytest

from conftest import SR, music, noise, silence, speech_like, write_wav


def _read(path):
    with wave.open(str(path)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), "<i2") / 32768


@pytest.fixture(scope="module")
def versions(tmp_path_factory, media):
    d = tmp_path_factory.mktemp("versions")
    x = _read(media["mix"])
    edited = np.concatenate([x[: 9 * SR], x[12 * SR: 14 * SR], x[14 * SR: 15 * SR], x[18 * SR:]])
    quieter = d / "quieter.mp3"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(media["mix"]), "-af", "volume=-4dB",
                    "-b:a", "96k", str(quieter)], check=True)
    return {
        "edited": write_wav(d / "edited.wav", edited),
        "quieter": quieter,
        "clip": write_wav(d / "clip.wav", x[int(7 * SR): int(10 * SR)]),
        "other": write_wav(d / "other.wav", np.concatenate(
            [speech_like(6, seed=21), silence(1), noise(2, seed=8), speech_like(4, seed=22)])),
    }


async def test_compare_reencoded_copy_is_same_content(toolset, media, versions):
    r = await toolset.audio_compare(a_path=str(media["mix"]), b_path=str(versions["quieter"]))
    assert r["error"] is None
    assert r["same_content"] is True
    assert r["similarity"] >= 0.95
    assert [c["type"] for c in r["changes"]] == ["level_changed"]
    assert -5.0 <= float(r["changes"][0]["detail"].split()[0]) <= -3.0


async def test_compare_describes_the_edit(toolset, media, versions):
    r = await toolset.audio_compare(a_path=str(media["mix"]), b_path=str(versions["edited"]))
    assert r["error"] is None
    assert r["same_content"] is False
    kinds = {c["type"]: c for c in r["changes"]}
    assert "removed" in kinds
    removed = kinds["removed"]
    assert 8.0 <= removed["a_start"] <= 9.5 and 11.5 <= removed["a_end"] <= 12.5
    assert "silence_shortened" in kinds
    assert abs(float(kinds["silence_shortened"]["detail"].rstrip("s")) - 3.0) <= 0.3


async def test_compare_unrelated(toolset, media, versions):
    r = await toolset.audio_compare(a_path=str(media["mix"]), b_path=str(versions["other"]))
    assert r["error"] is None
    assert r["similarity"] is not None and r["similarity"] < 0.3


async def test_compare_needs_both_sources(toolset, media):
    r = await toolset.audio_compare(a_path=str(media["mix"]))
    assert "b_path" in r["error"]


async def test_find_clip_file(toolset, media, versions):
    r = await toolset.audio_find(audio_path=str(media["mix"]), clip_path=str(versions["clip"]))
    assert r["error"] is None
    assert len(r["matches"]) >= 1
    best = max(r["matches"], key=lambda m: m["score"])
    assert abs(best["start"] - 7.0) <= 0.05
    assert best["score"] > 0.95


async def test_find_own_span_in_reencoded_file(toolset, versions):
    r = await toolset.audio_find(audio_path=str(versions["quieter"]), clip_start=22.0,
                                 clip_end=25.0)
    assert r["error"] is None
    assert any(abs(m["start"] - 22.0) <= 0.05 for m in r["matches"])


async def test_find_absent_clip(toolset, versions):
    r = await toolset.audio_find(audio_path=str(versions["other"]), clip_path=str(versions["clip"]))
    assert r["error"] is None
    assert r["matches"] == []
    assert r["text"].startswith("no match")


async def test_find_argument_errors(toolset, media, versions):
    r = await toolset.audio_find(audio_path=str(media["mix"]))
    assert "clip_start" in r["error"]
    r = await toolset.audio_find(audio_path=str(media["mix"]), clip_path=str(versions["clip"]),
                                 clip_start=1.0)
    assert "not both" in r["error"]
    r = await toolset.audio_find(audio_path=str(media["mix"]), clip_start=1.0, clip_end=1.1)
    assert "0.3..120" in r["error"]


async def test_fingerprint_groups_duplicates(toolset, media, versions):
    r = await toolset.audio_fingerprint(audio_paths=[
        str(media["mix"]), str(versions["quieter"]), str(versions["clip"]), str(versions["other"])])
    assert r["error"] is None
    rel = {(m["a"], m["b"]): m["relation"] for m in r["matches"]}
    assert rel[(str(media["mix"]), str(versions["quieter"]))] == "duplicate"
    assert rel[(str(media["mix"]), str(versions["clip"]))] == "contains"
    assert not any(str(versions["other"]) in pair for pair in rel)
    assert [sorted(g) for g in r["duplicate_groups"]] == [
        sorted([str(media["mix"]), str(versions["quieter"])])]


async def test_fingerprint_needs_two(toolset, media):
    r = await toolset.audio_fingerprint(audio_paths=[str(media["mix"])])
    assert "at least two" in r["error"]
