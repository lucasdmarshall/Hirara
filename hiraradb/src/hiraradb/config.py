"""Runtime configuration for HiraraDb."""

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


def _env_roots(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.getenv(name)
    if raw is None:
        return default
    parts = [p.strip() for p in raw.replace(":", ",").split(",") if p.strip()]
    return tuple(parts)


def _env_databases() -> dict[str, str]:
    """Parse CDB_DATABASES=name=path,name2=path2 plus CDB_PATH / CDB_URL."""
    out: dict[str, str] = {}
    raw = os.getenv("CDB_DATABASES")
    if raw:
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            if "=" not in part:
                continue
            name, path = part.split("=", 1)
            name, path = name.strip(), path.strip()
            if name and path:
                out[name] = path
    default = (os.getenv("CDB_PATH") or os.getenv("CDB_URL") or "").strip()
    if default and "default" not in out:
        out["default"] = default
    return out


@dataclass(frozen=True)
class DbConfig:
    """Database-tool knobs."""

    # Named sqlite databases: name -> path or sqlite URL.
    databases: dict[str, str] | None = None

    # Cap on returned rows.
    max_rows: int = 1_000

    # Cap on SQL character length.
    max_sql_chars: int = 100_000

    # sqlite3 connect / busy timeout (seconds).
    timeout: float = 30.0

    # When True, open sqlite in read-only mode and refuse writes.
    readonly: bool = True

    # Allowed directory roots for sqlite file paths.
    roots: tuple[str, ...] = ()

    # When True and roots empty, any sqlite path is allowed (laptop default).
    allow_any_path: bool = True

    def resolved_databases(self) -> dict[str, str]:
        return dict(self.databases or {})

    @classmethod
    def from_env(cls) -> "DbConfig":
        return cls(
            databases=_env_databases() or None,
            max_rows=_env_int("CDB_MAX_ROWS", cls.max_rows),
            max_sql_chars=_env_int("CDB_MAX_SQL_CHARS", cls.max_sql_chars),
            timeout=_env_float("CDB_TIMEOUT", cls.timeout),
            readonly=_env_bool("CDB_READONLY", cls.readonly),
            roots=_env_roots("CDB_ROOTS", cls.roots),
            allow_any_path=_env_bool("CDB_ALLOW_ANY_PATH", cls.allow_any_path),
        )


__all__ = ["DbConfig"]
