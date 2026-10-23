"""audio_spectrogram, audio_tones, audio_speak and audio_sonify."""

from __future__ import annotations

import base64
import shutil
import struct
import zlib

import numpy as np
import pytest

from hiraraaudio.config import AudioConfig
from hiraraaudio.tools import Toolset
from hiraraaudio.visual import encode_png


def _png_size(data: bytes) -> tuple[int, int]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", data[16:24])


def test_png_encoder_round_trip():
    img = np.zeros((3, 4, 3), dtype=np.uint8)
    img[1, 2] = (255, 10, 20)
    data = encode_png(img)
    assert _png_size(data) == (4, 3)
    idat = data[data.index(b"IDAT") + 4: data.index(b"IEND") - 8]
    raw = zlib.decompress(idat)
    row = raw[1 * 13 + 1: 2 * 13]
    assert tuple(row[6:9]) == (255, 10, 20)


async def test_spectrogram_png_and_geometry(toolset, media, tmp_path):
    out = tmp_path / "s.png"
    r = await toolset.audio_spectrogram(audio_path=str(media["mix"]), width=600, height=200,
                                        output_path=str(out))
    assert r["error"] is None
    png = base64.b64decode(r["png_base64"])
    assert _png_size(png) == (r["width"], r["height"])
    assert r["plot_area"] == {"x": 40, "y": 8, "width": 600, "height": 200}
    assert r["time_range"] == [0.0, 35.0]
    assert out.read_bytes() == png


async def test_spectrogram_reports_steady_tone(toolset, media):
    r = await toolset.audio_spectrogram(audio_path=str(media["dtmf"]), freq_scale="linear",
                                        max_freq=4000)
    assert r["error"] is None
    assert any(abs(t["freq_hz"] - 1000) < 20 for t in r["steady_tones"])


async def test_spectrogram_rejects_bad_range(toolset, media):
    r = await toolset.audio_spectrogram(audio_path=str(media["mix"]), min_freq=5000, max_freq=100)
    assert "min_freq < max_freq" in r["error"]


async def test_tones_dtmf_beep_and_hum(toolset, media):
    r = await toolset.audio_tones(audio_path=str(media["dtmf"]))
    assert r["error"] is None
    assert r["dtmf_sequence"] == "4205#"
    beeps = [t for t in r["tones"] if t["kind"] == "beep"]
    assert len(beeps) == 1 and abs(beeps[0]["freq_hz"] - 1000) < 15
    r = await toolset.audio_tones(audio_path=str(media["hum"]), detect=["hum"])
    assert r["hum"]["mains_hz"] == 60
    assert r["dtmf"] == [] and r["tones"] == []


async def test_tones_no_false_positives(toolset, media):
    r = await toolset.audio_tones(audio_path=str(media["mix"]))
    assert r["dtmf"] == []
    assert r["text"]


async def test_tones_rejects_unknown_detector(toolset, media):
    r = await toolset.audio_tones(audio_path=str(media["mix"]), detect=["sirens"])
    assert "unknown detect" in r["error"]


needs_espeak = pytest.mark.skipif(shutil.which("espeak-ng") is None, reason="espeak-ng not installed")


@needs_espeak
async def test_speak_wav_and_mp3(toolset, tmp_path):
    r = await toolset.audio_speak(text="Hello from Hirara.", voice="en-us")
    assert r["error"] is None
    assert base64.b64decode(r["audio_base64"])[:4] == b"RIFF"
    assert 0.5 < r["duration"] < 5
    out = tmp_path / "hi.mp3"
    r = await toolset.audio_speak(text="Hello again.", output_path=str(out))
    assert r["error"] is None and r["format"] == "mp3"
    assert out.stat().st_size > 1000 and r["audio_base64"] is None


@needs_espeak
async def test_speak_lists_voices(toolset):
    r = await toolset.audio_speak(list_voices=True, language="en")
    assert r["error"] is None
    assert any(v["language"].startswith("en") for v in r["voices"])


@needs_espeak
async def test_speak_output_is_speech(toolset, tmp_path):
    out = tmp_path / "s.wav"
    await toolset.audio_speak(text="The quick brown fox jumps over the lazy dog. " * 3,
                              output_path=str(out))
    r = await toolset.audio_profile(audio_path=str(out))
    assert r["summary"]["speech_pct"] >= 70


async def test_speak_errors(toolset):
    r = await toolset.audio_speak(text="  ")
    assert r["error"] == "text is required"
    r = await toolset.audio_speak(text="hi", voice="en; rm -rf /")
    assert "voice must be" in r["error"]
    missing = Toolset(AudioConfig(espeak="definitely-not-espeak"))
    r = await missing.audio_speak(text="hi")
    assert "not installed" in r["error"]


async def test_sonify_values(toolset):
    r = await toolset.audio_sonify(values=[1, 2, None, 4, 8], duration=2.0)
    assert r["error"] is None
    assert abs(r["duration"] - 2.0) < 0.05
    assert r["mapping"]["series"][0] == {"name": "values", "points": 5, "gaps": 1}
    assert base64.b64decode(r["audio_base64"])[:4] == b"RIFF"


async def test_sonify_series_pitch_follows_values(toolset, tmp_path):
    out = tmp_path / "up.wav"
    r = await toolset.audio_sonify(series=[{"name": "up", "values": [0, 10]}], duration=2.0,
                                   output_path=str(out), waveform="sine")
    assert r["error"] is None
    t = await toolset.audio_tones(audio_path=str(out), detect=["beeps"])
    freqs = [x["freq_hz"] for x in t["tones"]]
    assert len(freqs) == 2 and abs(freqs[0] - 220) < 10 and abs(freqs[1] - 880) < 15


async def test_sonify_errors(toolset):
    r = await toolset.audio_sonify()
    assert "values or series" in r["error"]
    r = await toolset.audio_sonify(values=[None, None])
    assert "no numbers" in r["error"]
    r = await toolset.audio_sonify(values=[1, "x"])
    assert "not a number" in r["error"]
    r = await toolset.audio_sonify(values=[1, 2], min_freq=900, max_freq=200)
    assert "min_freq" in r["error"]
