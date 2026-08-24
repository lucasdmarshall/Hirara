"""Read process environment variables (self or /proc/<pid>/environ)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import OpsConfig


class EnvironError(ValueError):
    """Caller-facing environment_read validation / access failure."""


@dataclass
class EnvironResult:
    pid: int | None = None
    source: str | None = None  # self | proc
    variables: dict[str, str | None] = field(default_factory=dict)
    keys: list[str] = field(default_factory=list)
    variable_count: int = 0
    redacted_keys: list[str] = field(default_factory=list)
    truncated: bool = False
    pattern: str | None = None
    error: str | None = None


def result_to_dict(result: EnvironResult) -> dict:
    return {
        "pid": result.pid,
        "source": result.source,
        "variables": dict(result.variables),
        "keys": list(result.keys),
        "variable_count": result.variable_count,
        "redacted_keys": list(result.redacted_keys),
        "truncated": result.truncated,
        "pattern": result.pattern,
        "error": result.error,
    }


def _parse_environ_bytes(raw: bytes) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in raw.split(b"\0"):
        if not part:
            continue
        try:
            text = part.decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            continue
        if "=" not in text:
            continue
        key, value = text.split("=", 1)
        if key:
            out[key] = value
    return out


def _read_proc_environ(proc_root: Path, pid: int) -> dict[str, str]:
    path = proc_root / str(pid) / "environ"
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise EnvironError(f"process not found: {pid}") from exc
    except PermissionError as exc:
        raise EnvironError(f"permission denied reading environ for pid {pid}") from exc
    except OSError as exc:
        raise EnvironError(f"cannot read environ for pid {pid}: {exc}") from exc
    return _parse_environ_bytes(raw)


def _should_redact(key: str, patterns: tuple[str, ...]) -> bool:
    lowered = key.lower()
    for pat in patterns:
        p = pat.strip().lower()
        if not p:
            continue
        if p in lowered:
            return True
    return False


def environment_read(
    *,
    pid: int | None = None,
    keys: list[str] | str | None = None,
    pattern: str | None = None,
    include_values: bool = True,
    redact: bool | None = None,
    max_vars: int | None = None,
    config: OpsConfig | None = None,
    proc_root: str | Path | None = None,
    environ: dict[str, str] | None = None,
) -> EnvironResult:
    """Read environment variables for this process or another pid."""
    cfg = config or OpsConfig()

    if not cfg.allow_environment_read:
        return EnvironResult(
            pid=pid,
            pattern=pattern,
            error=(
                "environment_read is disabled on this server "
                "(COPS_ALLOW_ENVIRONMENT_READ=false)"
            ),
        )

    do_redact = cfg.redact_env if redact is None else bool(redact)
    cap = cfg.max_env_vars if max_vars is None else int(max_vars)
    if cap <= 0:
        return EnvironResult(pid=pid, error="max_vars must be > 0")

    key_filter: set[str] | None = None
    if keys is not None:
        if isinstance(keys, str):
            items = [k.strip() for k in keys.replace("\n", ",").split(",") if k.strip()]
        elif isinstance(keys, list):
            items = [str(k).strip() for k in keys if str(k).strip()]
        else:
            return EnvironResult(error="keys must be a string or list of strings")
        key_filter = set(items)

    regex: re.Pattern[str] | None = None
    if pattern is not None and pattern != "":
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            return EnvironResult(pattern=pattern, error=f"invalid pattern: {exc}")

    try:
        if pid is not None:
            if int(pid) <= 0:
                return EnvironResult(error="pid must be > 0")
            root = Path(proc_root) if proc_root is not None else Path(cfg.proc_root)
            raw_env = _read_proc_environ(root, int(pid))
            source = "proc"
            used_pid = int(pid)
        else:
            raw_env = dict(environ) if environ is not None else dict(os.environ)
            source = "self"
            used_pid = os.getpid()
    except EnvironError as exc:
        return EnvironResult(pid=pid, pattern=pattern, error=str(exc))

    redacted: list[str] = []
    selected: dict[str, str | None] = {}
    for key in sorted(raw_env):
        if key_filter is not None and key not in key_filter:
            continue
        if regex is not None and regex.search(key) is None:
            continue
        if do_redact and _should_redact(key, cfg.redact_patterns):
            selected[key] = "***" if include_values else None
            redacted.append(key)
        elif include_values:
            selected[key] = raw_env[key]
        else:
            selected[key] = None

    truncated = len(selected) > cap
    if truncated:
        keep_keys = list(selected.keys())[:cap]
        selected = {k: selected[k] for k in keep_keys}
        redacted = [k for k in redacted if k in selected]

    return EnvironResult(
        pid=used_pid,
        source=source,
        variables=selected if include_values else {},
        keys=list(selected.keys()),
        variable_count=len(selected),
        redacted_keys=redacted,
        truncated=truncated,
        pattern=pattern,
    )


__all__ = [
    "EnvironError",
    "EnvironResult",
    "environment_read",
    "result_to_dict",
]
