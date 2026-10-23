"""Runtime configuration for HiraraData (environment prefix ``HD_``)."""

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
class DataConfig:
    """Limits and switches. Defaults suit a local, trusted process; for a
    network-exposed service turn off local paths and output paths."""

    max_bytes: int = 500 * 1024 * 1024
    # Rows profiled per file; the rest is counted as skipped.
    max_rows: int = 2_000_000
    max_columns: int = 500
    allow_local_path: bool = True
    allow_url_fetch: bool = False
    url_timeout: float = 60.0
    allow_output_path: bool = True
    max_output_bytes: int = 20 * 1024 * 1024
    # Wall-clock cap on Graphviz.
    timeout: float = 60.0
    dot: str = "dot"
    # Largest diagram / chart source accepted.
    max_source_chars: int = 200_000
    max_points: int = 200_000

    @classmethod
    def from_env(cls) -> "DataConfig":
        return cls(
            max_bytes=_env_int("HD_MAX_BYTES", cls.max_bytes),
            max_rows=_env_int("HD_MAX_ROWS", cls.max_rows),
            max_columns=_env_int("HD_MAX_COLUMNS", cls.max_columns),
            allow_local_path=_env_bool("HD_ALLOW_LOCAL_PATH", cls.allow_local_path),
            allow_url_fetch=_env_bool("HD_ALLOW_URL_FETCH", cls.allow_url_fetch),
            url_timeout=_env_float("HD_URL_TIMEOUT", cls.url_timeout),
            allow_output_path=_env_bool("HD_ALLOW_OUTPUT_PATH", cls.allow_output_path),
            max_output_bytes=_env_int("HD_MAX_OUTPUT_BYTES", cls.max_output_bytes),
            timeout=_env_float("HD_TIMEOUT", cls.timeout),
            dot=(os.getenv("HD_DOT") or cls.dot).strip(),
            max_source_chars=_env_int("HD_MAX_SOURCE_CHARS", cls.max_source_chars),
            max_points=_env_int("HD_MAX_POINTS", cls.max_points),
        )


__all__ = ["DataConfig"]
