"""Runtime configuration for HiraraUtil."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw else default


@dataclass(frozen=True)
class UtilConfig:
    """Utility-tool knobs."""

    # Cap on input character length for decode (and later hash).
    max_input_chars: int = 1_000_000

    # Cap on decoded output bytes before we stop and flag truncated.
    max_output_bytes: int = 2_000_000

    @classmethod
    def from_env(cls) -> "UtilConfig":
        return cls(
            max_input_chars=_env_int("CUTIL_MAX_INPUT_CHARS", cls.max_input_chars),
            max_output_bytes=_env_int("CUTIL_MAX_OUTPUT_BYTES", cls.max_output_bytes),
        )


__all__ = ["UtilConfig"]
