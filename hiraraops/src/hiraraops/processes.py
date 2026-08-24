"""List running processes from /proc (Linux)."""

from __future__ import annotations

import pwd
import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import OpsConfig


class ProcessError(ValueError):
    """Caller-facing process_list validation / access failure."""


@dataclass
class ProcessInfo:
    pid: int
    name: str | None = None
    state: str | None = None
    ppid: int | None = None
    uid: int | None = None
    user: str | None = None
    cmdline: str | None = None


@dataclass
class ProcessListResult:
    processes: list[ProcessInfo] = field(default_factory=list)
    process_count: int = 0
    scanned: int = 0
    truncated: bool = False
    pattern: str | None = None
    user: str | None = None
    error: str | None = None


def process_to_dict(proc: ProcessInfo) -> dict:
    return {
        "pid": proc.pid,
        "name": proc.name,
        "state": proc.state,
        "ppid": proc.ppid,
        "uid": proc.uid,
        "user": proc.user,
        "cmdline": proc.cmdline,
    }


def result_to_dict(result: ProcessListResult) -> dict:
    return {
        "processes": [process_to_dict(p) for p in result.processes],
        "process_count": result.process_count,
        "scanned": result.scanned,
        "truncated": result.truncated,
        "pattern": result.pattern,
        "user": result.user,
        "error": result.error,
    }


def _uid_to_user(uid: int | None, cache: dict[int, str | None]) -> str | None:
    if uid is None:
        return None
    if uid in cache:
        return cache[uid]
    try:
        name = pwd.getpwuid(uid).pw_name
    except (KeyError, OSError):
        name = None
    cache[uid] = name
    return name


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _parse_status(text: str) -> tuple[str | None, str | None, int | None, int | None]:
    name = None
    state = None
    uid = None
    ppid = None
    for line in text.splitlines():
        if line.startswith("Name:"):
            name = line.split(":", 1)[1].strip()
        elif line.startswith("State:"):
            raw = line.split(":", 1)[1].strip()
            state = raw[:1] if raw else None
        elif line.startswith("Uid:"):
            parts = line.split(":", 1)[1].split()
            if parts:
                try:
                    uid = int(parts[0])
                except ValueError:
                    uid = None
        elif line.startswith("PPid:"):
            try:
                ppid = int(line.split(":", 1)[1].strip())
            except ValueError:
                ppid = None
    return name, state, uid, ppid


def _read_cmdline(path: Path) -> str | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if not raw:
        return ""
    parts = [p.decode("utf-8", errors="replace") for p in raw.split(b"\0") if p]
    return " ".join(parts)


def _iter_pids(proc_root: Path) -> list[int]:
    try:
        entries = list(proc_root.iterdir())
    except OSError as exc:
        raise ProcessError(f"cannot read proc root: {exc}") from exc
    pids: list[int] = []
    for entry in entries:
        if entry.name.isdigit():
            pids.append(int(entry.name))
    pids.sort()
    return pids


def process_list(
    *,
    pattern: str | None = None,
    user: str | None = None,
    pid: int | None = None,
    max_processes: int | None = None,
    include_cmdline: bool = True,
    config: OpsConfig | None = None,
    proc_root: str | Path | None = None,
) -> ProcessListResult:
    """List processes from ``/proc`` (or a fake root for tests)."""
    cfg = config or OpsConfig()

    if not cfg.allow_process_list:
        return ProcessListResult(
            pattern=pattern,
            user=user,
            error="process_list is disabled on this server (COPS_ALLOW_PROCESS_LIST=false)",
        )

    cap = cfg.max_processes if max_processes is None else int(max_processes)
    if cap <= 0:
        return ProcessListResult(
            pattern=pattern,
            user=user,
            error="max_processes must be > 0",
        )

    regex: re.Pattern[str] | None = None
    if pattern is not None and pattern != "":
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            return ProcessListResult(
                pattern=pattern,
                user=user,
                error=f"invalid pattern: {exc}",
            )

    user_filter = (user or "").strip() or None
    root = Path(proc_root) if proc_root is not None else Path(cfg.proc_root)

    try:
        if pid is not None:
            if int(pid) <= 0:
                return ProcessListResult(error="pid must be > 0")
            pids = [int(pid)]
        else:
            pids = _iter_pids(root)
    except ProcessError as exc:
        return ProcessListResult(pattern=pattern, user=user_filter, error=str(exc))

    uid_cache: dict[int, str | None] = {}
    matched: list[ProcessInfo] = []
    scanned = 0
    truncated = False

    for proc_pid in pids:
        scanned += 1
        status_text = _read_text(root / str(proc_pid) / "status")
        if status_text is None:
            continue
        name, state, uid, ppid = _parse_status(status_text)
        uname = _uid_to_user(uid, uid_cache)
        cmdline = (
            _read_cmdline(root / str(proc_pid) / "cmdline") if include_cmdline else None
        )

        if user_filter and uname != user_filter and str(uid) != user_filter:
            continue

        if regex is not None:
            hay = " ".join(x for x in (name or "", cmdline or "") if x)
            if regex.search(hay) is None:
                continue

        matched.append(
            ProcessInfo(
                pid=proc_pid,
                name=name,
                state=state,
                ppid=ppid,
                uid=uid,
                user=uname,
                cmdline=cmdline if include_cmdline else None,
            )
        )
        if len(matched) >= cap:
            truncated = pid is None
            break

    return ProcessListResult(
        processes=matched,
        process_count=len(matched),
        scanned=scanned,
        truncated=truncated,
        pattern=pattern,
        user=user_filter,
    )


__all__ = [
    "ProcessError",
    "ProcessInfo",
    "ProcessListResult",
    "process_list",
    "result_to_dict",
]
