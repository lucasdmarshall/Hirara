"""audio_info, audio_profile, audio_check and audio_fix."""

from __future__ import annotations

import base64

from hiraraaudio.config import AudioConfig
from hiraraaudio.tools import Toolset


async def test_info_reports_stream_facts(toolset, media):
    r = await toolset.audio_info(audio_path=str(media["mix"]))
    assert r["error"] is None
    assert r["sample_rate"] == 44100
    assert r["channels"] == 1
    assert abs(r["duration"] - 35.0) < 0.1
    assert "mono" in r["summary"]


async def test_info_accepts_base64(toolset, media):
    data = base64.b64encode(media["dtmf"].read_bytes()).decode()
    r = await toolset.audio_info(audio_base64=data, filename="x.wav")
    assert r["error"] is None
    assert r["sample_rate"] == 8000


async def test_missing_file_is_an_envelope(toolset, tmp_path):
    r = await toolset.audio_info(audio_path=str(tmp_path / "nope.wav"))
    assert r["error"].startswith("file not found")


async def test_not_audio_is_an_envelope(toolset, tmp_path):
    bad = tmp_path / "bad.wav"
    bad.write_text("not audio at all")
    r = await toolset.audio_profile(audio_path=str(bad))
    assert r["error"]
    assert r["timeline"] == []


async def test_source_rules(toolset, media):
    r = await toolset.audio_info()
    assert "provide exactly one" in r["error"]
    r = await toolset.audio_info(audio_path=str(media["mix"]), audio_base64="AAAA")
    assert "only one" in r["error"]
    r = await toolset.audio_info(audo_path=str(media["mix"]))
    assert r["error"] == "unexpected argument(s): audo_path"
    locked = Toolset(AudioConfig(allow_local_path=False))
    r = await locked.audio_info(audio_path=str(media["mix"]))
    assert "disabled" in r["error"]
    r = await toolset.audio_info(audio_url="https://example.com/a.mp3")
    assert "HA_ALLOW_URL_FETCH" in r["error"]


async def test_profile_timeline_and_events(toolset, media):
    r = await toolset.audio_profile(audio_path=str(media["mix"]))
    assert r["error"] is None
    kinds = [seg["kind"] for seg in r["timeline"]]
    assert kinds == ["music", "speech", "silence", "noise", "speech", "music"]
    silent = r["timeline"][2]
    assert abs(silent["start"] - 14.0) <= 1.0 and abs(silent["end"] - 18.0) <= 1.0
    assert any(e["type"] == "long_silence" for e in r["events"])
    assert r["summary"]["integrated_lufs"] is not None
    assert r["text"].splitlines()[0].startswith("0:35.0 total")


async def test_profile_span_offsets_times(toolset, media):
    r = await toolset.audio_profile(audio_path=str(media["mix"]), start=14.0, duration=8.0)
    assert r["error"] is None
    assert r["start"] == 14.0
    assert r["timeline"][0]["start"] == 14.0
    assert abs(r["duration"] - 8.0) < 0.1


async def test_profile_reports_clipping_and_hum(toolset, media):
    r = await toolset.audio_profile(audio_path=str(media["clipped"]))
    assert r["summary"]["clipped_samples"] > 0
    assert any(e["type"] == "clipping" for e in r["events"])
    r = await toolset.audio_profile(audio_path=str(media["hum"]))
    assert r["summary"]["hum"]["mains_hz"] == 60


async def test_profile_merges_to_max_segments(toolset, media):
    r = await toolset.audio_profile(audio_path=str(media["mix"]), max_segments=3)
    assert len(r["timeline"]) <= 3
    assert r["timeline"][0]["start"] == 0.0
    assert r["timeline"][-1]["end"] == r["duration"]


async def test_check_reports_failures_with_fixes(toolset, media):
    r = await toolset.audio_check(audio_path=str(media["hum"]), preset="podcast")
    assert r["error"] is None
    assert r["passed"] is False
    by_name = {c["name"]: c for c in r["checks"]}
    assert by_name["integrated_loudness"]["status"] == "fail"
    assert by_name["hum"]["status"] == "warn"
    assert by_name["dc_offset"]["status"] == "warn"
    assert r["suggested_fix"] == {"preset": "podcast", "target_lufs": -16.0,
                                  "remove_dc": True, "dehum": "60"}
    assert r["text"].startswith("podcast: FAIL")


async def test_check_clipping_and_phase(toolset, media):
    r = await toolset.audio_check(audio_path=str(media["clipped"]), preset="music_streaming")
    assert {c["name"]: c["status"] for c in r["checks"]}["clipping"] == "fail"
    r = await toolset.audio_check(audio_path=str(media["stereo"]), preset="music_streaming")
    assert {c["name"]: c["status"] for c in r["checks"]}["phase"] == "fail"


async def test_check_audiobook_and_stt(toolset, media):
    r = await toolset.audio_check(audio_path=str(media["speech"]), preset="audiobook")
    names = {c["name"]: c for c in r["checks"]}
    assert names["head_room_tone"]["status"] == "pass"
    assert names["noise_floor"]["status"] == "warn"  # digital silence, not room tone
    r = await toolset.audio_check(audio_path=str(media["speech"]), preset="stt_ready")
    assert {c["name"]: c["status"] for c in r["checks"]}["speech_present"] == "pass"
    r = await toolset.audio_check(audio_path=str(media["dtmf"]), preset="stt_ready")
    assert r["passed"] is False


async def test_check_unknown_preset(toolset, media):
    r = await toolset.audio_check(audio_path=str(media["mix"]), preset="vinyl")
    assert "unknown preset" in r["error"]


async def test_fix_closes_the_loop(toolset, media, tmp_path):
    check = await toolset.audio_check(audio_path=str(media["hum"]), preset="podcast")
    out = tmp_path / "fixed.wav"
    r = await toolset.audio_fix(audio_path=str(media["hum"]), output_path=str(out),
                                **check["suggested_fix"])
    assert r["error"] is None, r["error"]
    assert r["before"]["passed"] is False
    assert r["after"]["passed"] is True
    assert r["remaining"] == []
    assert out.is_file() and r["output_path"] == str(out)
    assert r["audio_base64"] is None
    again = await toolset.audio_check(audio_path=str(out), preset="podcast")
    assert again["passed"] is True
    assert abs(again["checks"][0]["measured"] + 16.0) <= 1.0


async def test_fix_inline_and_nothing_to_do(toolset, media):
    r = await toolset.audio_fix(audio_path=str(media["dtmf"]), target_lufs=-20, output_format="flac")
    assert r["error"] is None
    assert base64.b64decode(r["audio_base64"])[:4] == b"fLaC"
    r = await toolset.audio_fix(audio_path=str(media["mix"]), dehum="off")
    assert r["changed"] is False


async def test_fix_rejects_bad_output_path(toolset, media, tmp_path):
    r = await toolset.audio_fix(audio_path=str(media["mix"]), target_lufs=-16,
                                output_path=str(tmp_path / "missing" / "x.wav"))
    assert "output directory does not exist" in r["error"]
    locked = Toolset(AudioConfig(allow_output_path=False))
    r = await locked.audio_fix(audio_path=str(media["mix"]), target_lufs=-16,
                               output_path=str(tmp_path / "x.wav"))
    assert "HA_ALLOW_OUTPUT_PATH" in r["error"]
