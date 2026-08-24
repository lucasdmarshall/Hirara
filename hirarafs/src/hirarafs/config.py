"""Runtime configuration for HiraraFs."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw else default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    return raw.strip().lower() in {"1", "true", "yes", "on"} if raw else default


def _env_roots(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.getenv(name)
    if raw is None:
        return default
    parts = [p.strip() for p in raw.replace(":", ",").split(",") if p.strip()]
    return tuple(parts)


@dataclass(frozen=True)
class FsConfig:
    """Filesystem-tool knobs."""

    # Cap on bytes returned per file_read (after offset).
    max_bytes: int = 2_000_000

    # Cap on bytes accepted per file_write.
    max_write_bytes: int = 2_000_000

    # Allowed directory roots. Empty + allow_any_path → any readable file.
    # Docker sets CFS_ROOTS=/data and CFS_ALLOW_ANY_PATH=false.
    roots: tuple[str, ...] = ()

    # When True and roots is empty, any path that resolves to a file is allowed.
    # When False, at least one root is required.
    allow_any_path: bool = True

    # When False, file_write returns an error without writing.
    allow_write: bool = True

    # Default content encoding when the caller omits encoding on file_read.
    # auto: utf-8 if decodable, else base64.
    default_encoding: str = "auto"

    @classmethod
    def from_env(cls) -> "FsConfig":
        return cls(
            max_bytes=_env_int("CFS_MAX_BYTES", cls.max_bytes),
            max_write_bytes=_env_int("CFS_MAX_WRITE_BYTES", cls.max_write_bytes),
            roots=_env_roots("CFS_ROOTS", cls.roots),
            allow_any_path=_env_bool("CFS_ALLOW_ANY_PATH", cls.allow_any_path),
            allow_write=_env_bool("CFS_ALLOW_WRITE", cls.allow_write),
            default_encoding=(
                os.getenv("CFS_DEFAULT_ENCODING") or cls.default_encoding
            ).strip()
            or cls.default_encoding,
        )


__all__ = ["FsConfig"]
