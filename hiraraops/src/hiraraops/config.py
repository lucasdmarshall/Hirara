"""Runtime configuration for HiraraOps."""

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


def _env_sources() -> dict[str, str]:
    """Parse COPS_LOG_SOURCES=name=path,name2=path2."""
    out: dict[str, str] = {}
    raw = os.getenv("COPS_LOG_SOURCES")
    if not raw:
        return out
    for part in raw.split(","):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, path = part.split("=", 1)
        name, path = name.strip(), path.strip()
        if name and path:
            out[name] = path
    return out


@dataclass(frozen=True)
class OpsConfig:
    """Ops-tool knobs."""

    # Named log sources: name -> file path.
    log_sources: dict[str, str] | None = None

    # Allowed directory roots for log paths.
    roots: tuple[str, ...] = ()

    # When True and roots empty, any path is allowed (laptop default).
    allow_any_path: bool = True

    # Default / max lines returned.
    default_lines: int = 100
    max_lines: int = 5_000

    # Cap on bytes read from a log file per call.
    max_bytes: int = 2_000_000

    # process_list: /proc root, max returned processes, kill switch.
    proc_root: str = "/proc"
    max_processes: int = 500
    allow_process_list: bool = True

    def resolved_sources(self) -> dict[str, str]:
        return dict(self.log_sources or {})

    @classmethod
    def from_env(cls) -> "OpsConfig":
        return cls(
            log_sources=_env_sources() or None,
            roots=_env_roots("COPS_ROOTS", cls.roots),
            allow_any_path=_env_bool("COPS_ALLOW_ANY_PATH", cls.allow_any_path),
            default_lines=_env_int("COPS_DEFAULT_LINES", cls.default_lines),
            max_lines=_env_int("COPS_MAX_LINES", cls.max_lines),
            max_bytes=_env_int("COPS_MAX_BYTES", cls.max_bytes),
            proc_root=(os.getenv("COPS_PROC_ROOT") or cls.proc_root).strip()
            or cls.proc_root,
            max_processes=_env_int("COPS_MAX_PROCESSES", cls.max_processes),
            allow_process_list=_env_bool(
                "COPS_ALLOW_PROCESS_LIST", cls.allow_process_list
            ),
        )


__all__ = ["OpsConfig"]
