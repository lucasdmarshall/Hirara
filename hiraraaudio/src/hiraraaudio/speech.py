"""audio_speak: lightweight text-to-speech with eSpeak NG.

eSpeak NG is a formant synthesiser: a few megabytes, no model weights, more
than a hundred languages, instant on CPU. It sounds synthetic, which suits
notifications, accessibility read-outs, pronunciation checks and test audio
rather than polished narration.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from .config import AudioConfig
from .errors import AudioError
from .media import run, transcode

_VOICE = re.compile(r"^[A-Za-z0-9_+\-]{1,40}$")


def _espeak_missing(config: AudioConfig) -> AudioError:
    return AudioError(
        f"{config.espeak} is not installed. Install eSpeak NG "
        "(e.g. apt-get install espeak-ng) or set HA_ESPEAK."
    )


def list_voices(config: AudioConfig, language: str | None = None) -> list[dict]:
    arg = "--voices" if not language else f"--voices={language}"
    if language and not _VOICE.match(language):
        raise AudioError("language must be a code like en, en-us or de")
    try:
        out, _ = run([config.espeak, arg], config)
    except AudioError as exc:
        if "not installed" in str(exc):
            raise _espeak_missing(config) from exc
        raise
    voices = []
    for line in out.decode("utf-8", "replace").splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 4:
            voices.append({"language": parts[1], "gender": parts[2].split("/")[-1],
                           "name": parts[3].replace("_", " ")})
    return voices


def synthesize(text: str, config: AudioConfig, *, voice: str | None, speed: int | None,
               pitch: int | None, ssml: bool, fmt: str) -> tuple[Path, int]:
    """Render ``text`` to a temp file in ``fmt``. Returns (path, word count)."""
    if not text or not text.strip():
        raise AudioError("text is required")
    if len(text) > config.max_speak_chars:
        raise AudioError(f"text is longer than HA_MAX_SPEAK_CHARS ({config.max_speak_chars})")
    if voice and not _VOICE.match(voice):
        raise AudioError("voice must be a code like en, en-us, de or fr+f3")
    wav = Path(tempfile.mkstemp(prefix="hiraraaudio-tts-", suffix=".wav")[1])
    args = [config.espeak, "--stdin", "-w", str(wav)]
    if voice:
        args += ["-v", voice]
    if speed is not None:
        if not 80 <= speed <= 450:
            raise AudioError("speed must be 80..450 words per minute")
        args += ["-s", str(speed)]
    if pitch is not None:
        if not 0 <= pitch <= 99:
            raise AudioError("pitch must be 0..99")
        args += ["-p", str(pitch)]
    if ssml:
        args.append("-m")
    try:
        run(args, config, input_bytes=text.encode("utf-8"))
    except AudioError as exc:
        wav.unlink(missing_ok=True)
        if "not installed" in str(exc):
            raise _espeak_missing(config) from exc
        raise
    if fmt == "wav":
        return wav, len(text.split())
    out = Path(tempfile.mkstemp(prefix="hiraraaudio-tts-", suffix=f".{fmt}")[1])
    try:
        transcode(wav, out, fmt, config)
    finally:
        wav.unlink(missing_ok=True)
    return out, len(text.split())


__all__ = ["list_voices", "synthesize"]
