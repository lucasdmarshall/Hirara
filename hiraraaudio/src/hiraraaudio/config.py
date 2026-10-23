"""Runtime configuration for HiraraAudio.

Everything is overridable by environment variable (prefix ``HA_``) so the same
image works as a local stdio tool and as a network service.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw else default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw else default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    return raw.strip().lower() in {"1", "true", "yes", "on"} if raw else default


def _env_str(name: str, default: str) -> str:
    raw = os.getenv(name, "").strip()
    return raw or default


@dataclass(frozen=True)
class AudioConfig:
    """Limits and switches for the audio tools.

    Defaults suit a local, trusted process (MCP over stdio, a loopback
    service). For a network-exposed service set ``HA_ALLOW_LOCAL_PATH=false``
    and ``HA_ALLOW_OUTPUT_PATH=false`` so callers cannot name files on the
    host, and use base64 in and out instead.
    """

    # Largest input file accepted, by path, upload, base64 or URL.
    max_bytes: int = 200 * 1024 * 1024

    # Longest stretch of audio analysed. Longer input is analysed up to this
    # point and the result says it was truncated.
    max_duration: float = 4 * 3600.0

    # Read input files the caller names by path.
    allow_local_path: bool = True

    # Fetch input from http(s) URLs. Off by default; when on, every fetch goes
    # through hirara-core's SSRF guard (resolve-then-pin, redirect
    # re-validation, streamed byte cap).
    allow_url_fetch: bool = False
    url_timeout: float = 60.0

    # Write results to a caller-named output_path / output_dir.
    allow_output_path: bool = True

    # Largest audio or image returned inline as base64.
    max_output_bytes: int = 25 * 1024 * 1024

    # Wall-clock cap on any one ffmpeg / espeak-ng process.
    timeout: float = 900.0

    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    espeak: str = "espeak-ng"

    # audio_speak
    max_speak_chars: int = 5000

    # audio_fingerprint
    max_fingerprint_sources: int = 50

    # audio_watch
    max_watchers: int = 4
    max_watch_seconds: float = 12 * 3600.0
    # Let audio_watch reach private / loopback stream hosts. Off by default:
    # a stream URL is attacker-influenceable like any other URL.
    watch_allow_private: bool = False

    @classmethod
    def from_env(cls) -> "AudioConfig":
        return cls(
            max_bytes=_env_int("HA_MAX_BYTES", cls.max_bytes),
            max_duration=_env_float("HA_MAX_DURATION", cls.max_duration),
            allow_local_path=_env_bool("HA_ALLOW_LOCAL_PATH", cls.allow_local_path),
            allow_url_fetch=_env_bool("HA_ALLOW_URL_FETCH", cls.allow_url_fetch),
            url_timeout=_env_float("HA_URL_TIMEOUT", cls.url_timeout),
            allow_output_path=_env_bool("HA_ALLOW_OUTPUT_PATH", cls.allow_output_path),
            max_output_bytes=_env_int("HA_MAX_OUTPUT_BYTES", cls.max_output_bytes),
            timeout=_env_float("HA_TIMEOUT", cls.timeout),
            ffmpeg=_env_str("HA_FFMPEG", cls.ffmpeg),
            ffprobe=_env_str("HA_FFPROBE", cls.ffprobe),
            espeak=_env_str("HA_ESPEAK", cls.espeak),
            max_speak_chars=_env_int("HA_MAX_SPEAK_CHARS", cls.max_speak_chars),
            max_fingerprint_sources=_env_int(
                "HA_MAX_FINGERPRINT_SOURCES", cls.max_fingerprint_sources
            ),
            max_watchers=_env_int("HA_MAX_WATCHERS", cls.max_watchers),
            max_watch_seconds=_env_float("HA_MAX_WATCH_SECONDS", cls.max_watch_seconds),
            watch_allow_private=_env_bool(
                "HA_WATCH_ALLOW_PRIVATE", cls.watch_allow_private
            ),
        )


__all__ = ["AudioConfig"]
