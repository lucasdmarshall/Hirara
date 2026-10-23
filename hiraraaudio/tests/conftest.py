"""Synthetic test audio. Everything is generated with NumPy, so the suite needs
FFmpeg but no fixture files and no network."""

from __future__ import annotations

import shutil
import wave
from pathlib import Path

import numpy as np
import pytest

from hiraraaudio.config import AudioConfig
from hiraraaudio.tools import Toolset

SR = 44100

if shutil.which("ffmpeg") is None:  # pragma: no cover - environment guard
    pytest.skip("ffmpeg is required for the hiraraaudio tests", allow_module_level=True)


def write_wav(path: Path, x: np.ndarray, sr: int = SR) -> Path:
    data = np.asarray(x, dtype=np.float64)
    if data.ndim == 1:
        data = data[:, None]
    pcm = (np.clip(data, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(data.shape[1])
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return path


def music(seconds: float, seed: int = 0, sr: int = SR) -> np.ndarray:
    """Sustained chords: steady energy, strongly tonal."""
    rng = np.random.default_rng(seed)
    out = np.zeros(int(seconds * sr))
    notes = [220, 247, 262, 294, 330, 349, 392, 440]
    step = 0.5
    for k in range(int(np.ceil(seconds / step))):
        n = int(step * sr)
        t = np.arange(n) / sr
        f = rng.choice(notes)
        s = sum(np.sin(2 * np.pi * c * t) + 0.5 * np.sin(4 * np.pi * c * t)
                for c in (f, f * 1.25, f * 1.5))
        env = np.minimum(1, t / 0.02) * np.exp(-t * 0.5)
        a = k * n
        seg = (s * env)[: max(0, len(out) - a)]
        out[a: a + len(seg)] += seg
    return 0.12 * out


def speech_like(seconds: float, seed: int = 0, sr: int = SR) -> np.ndarray:
    """Syllable-rate bursts of voiced harmonics and fricative noise with short
    gaps: the energy pattern the speech heuristic keys on."""
    rng = np.random.default_rng(seed)
    out = np.zeros(int(seconds * sr))
    pos = 0
    while pos < len(out):
        dur = int(rng.uniform(0.1, 0.25) * sr)
        t = np.arange(dur) / sr
        if rng.random() < 0.75:
            f0 = rng.uniform(110, 190)
            syl = sum(np.sin(2 * np.pi * f0 * h * t) / h for h in range(1, 12))
        else:
            syl = rng.standard_normal(dur) * 0.6
        env = np.sin(np.pi * np.arange(dur) / dur) ** 2
        seg = (syl * env)[: len(out) - pos]
        out[pos: pos + len(seg)] += seg
        pos += dur + int(rng.uniform(0.04, 0.18) * sr)
    return 0.15 * out / max(1e-9, np.abs(out).max()) * 4


def noise(seconds: float, level: float = 0.05, seed: int = 1, sr: int = SR) -> np.ndarray:
    return level * np.random.default_rng(seed).standard_normal(int(seconds * sr))


def silence(seconds: float, sr: int = SR) -> np.ndarray:
    return np.zeros(int(seconds * sr))


def tone(freq: float, seconds: float, amp: float = 0.3, sr: int = SR) -> np.ndarray:
    return amp * np.sin(2 * np.pi * freq * np.arange(int(seconds * sr)) / sr)


DTMF = {"1": (697, 1209), "2": (697, 1336), "3": (697, 1477), "4": (770, 1209),
        "5": (770, 1336), "6": (770, 1477), "7": (852, 1209), "8": (852, 1336),
        "9": (852, 1477), "*": (941, 1209), "0": (941, 1336), "#": (941, 1477)}


def dtmf(digits: str, sr: int = 8000) -> np.ndarray:
    parts = [np.zeros(sr // 2)]
    for d in digits:
        f1, f2 = DTMF[d]
        t = np.arange(int(0.1 * sr)) / sr
        parts += [0.25 * (np.sin(2 * np.pi * f1 * t) + np.sin(2 * np.pi * f2 * t)),
                  np.zeros(int(0.08 * sr))]
    parts.append(np.zeros(sr // 2))
    return np.concatenate(parts)


@pytest.fixture(scope="session")
def media(tmp_path_factory) -> dict[str, Path]:
    d = tmp_path_factory.mktemp("audio")
    files = {}
    files["mix"] = write_wav(d / "mix.wav", np.concatenate(
        [music(6), speech_like(8), silence(4), noise(4), speech_like(8, seed=2), music(5, seed=3)]))
    files["speech"] = write_wav(d / "speech.wav", np.concatenate(
        [silence(0.7), speech_like(6, seed=4), silence(3.0), speech_like(6, seed=5),
         silence(2.5), speech_like(5, seed=6), silence(1.5)]))
    t = np.arange(int(8 * SR)) / SR
    files["hum"] = write_wav(d / "hum.wav", 0.25 * speech_like(8, seed=7)
                             + 0.01 * np.sin(2 * np.pi * 60 * t)
                             + 0.004 * np.sin(2 * np.pi * 180 * t) + 0.01)
    clipped = np.clip(music(4, seed=9) * 12, -1, 1)
    files["clipped"] = write_wav(d / "clipped.wav", clipped)
    files["dtmf"] = write_wav(d / "dtmf.wav", np.concatenate(
        [dtmf("4205#"), tone(1000, 0.5, sr=8000), np.zeros(8000)]), sr=8000)
    files["stereo"] = write_wav(d / "stereo.wav",
                                np.stack([music(3), -music(3)], axis=1))
    return files


@pytest.fixture
def toolset() -> Toolset:
    return Toolset(AudioConfig())
