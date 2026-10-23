"""Runtime configuration for HiraraMedia (environment prefix ``HM_``)."""

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


@dataclass(frozen=True)
class MediaConfig:
    """Limits and switches. Defaults suit a local, trusted process; for a
    network-exposed service turn off local paths and output paths."""

    max_bytes: int = 1024 * 1024 * 1024
    allow_local_path: bool = True
    allow_url_fetch: bool = False
    url_timeout: float = 120.0
    allow_output_path: bool = True
    max_output_bytes: int = 25 * 1024 * 1024
    # Wall-clock cap per ffmpeg / ffprobe process.
    timeout: float = 900.0
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    # Largest image accepted, in pixels (decompression-bomb guard).
    max_pixels: int = 60_000_000
    max_keyframes: int = 48

    @classmethod
    def from_env(cls) -> "MediaConfig":
        return cls(
            max_bytes=_env_int("HM_MAX_BYTES", cls.max_bytes),
            allow_local_path=_env_bool("HM_ALLOW_LOCAL_PATH", cls.allow_local_path),
            allow_url_fetch=_env_bool("HM_ALLOW_URL_FETCH", cls.allow_url_fetch),
            url_timeout=_env_float("HM_URL_TIMEOUT", cls.url_timeout),
            allow_output_path=_env_bool("HM_ALLOW_OUTPUT_PATH", cls.allow_output_path),
            max_output_bytes=_env_int("HM_MAX_OUTPUT_BYTES", cls.max_output_bytes),
            timeout=_env_float("HM_TIMEOUT", cls.timeout),
            ffmpeg=(os.getenv("HM_FFMPEG") or cls.ffmpeg).strip(),
            ffprobe=(os.getenv("HM_FFPROBE") or cls.ffprobe).strip(),
            max_pixels=_env_int("HM_MAX_PIXELS", cls.max_pixels),
            max_keyframes=_env_int("HM_MAX_KEYFRAMES", cls.max_keyframes),
        )


__all__ = ["MediaConfig"]
