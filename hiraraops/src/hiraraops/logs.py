"""Read application log files (tail / head / grep) from allowlisted paths."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import OpsConfig

_LEVEL_RE = re.compile(
    r"\b(CRITICAL|FATAL|ERROR|WARN(?:ING)?|INFO|DEBUG|TRACE)\b",
    re.IGNORECASE,
)


class LogsError(ValueError):
    """Caller-facing application_logs validation / access failure."""


@dataclass
class LogLine:
    line_number: int
    text: str
    level: str | None = None


@dataclass
class LogsResult:
    source: str | None = None
    path: str | None = None
    resolved_path: str | None = None
    lines: list[LogLine] = field(default_factory=list)
    line_count: int = 0
    total_lines_scanned: int | None = None
    from_end: bool = True
    pattern: str | None = None
    level: str | None = None
    truncated: bool = False
    bytes_read: int | None = None
    file_size: int | None = None
    error: str | None = None


def line_to_dict(line: LogLine) -> dict:
    return {
        "line_number": line.line_number,
        "text": line.text,
        "level": line.level,
    }


def result_to_dict(result: LogsResult) -> dict:
    return {
        "source": result.source,
        "path": result.path,
        "resolved_path": result.resolved_path,
        "lines": [line_to_dict(x) for x in result.lines],
        "line_count": result.line_count,
        "total_lines_scanned": result.total_lines_scanned,
        "from_end": result.from_end,
        "pattern": result.pattern,
        "level": result.level,
        "truncated": result.truncated,
        "bytes_read": result.bytes_read,
        "file_size": result.file_size,
        "error": result.error,
    }


def _parse_roots(config: OpsConfig) -> list[Path]:
    roots: list[Path] = []
    for item in config.roots:
        cleaned = (item or "").strip()
        if not cleaned:
            continue
        roots.append(Path(cleaned).expanduser().resolve())
    return roots


def _under_root(resolved: Path, roots: list[Path]) -> bool:
    for root in roots:
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def resolve_log_path(path: str, *, config: OpsConfig) -> Path:
    cleaned = (path or "").strip()
    if not cleaned:
        raise LogsError("path is required")

    roots = _parse_roots(config)
    if not roots and not config.allow_any_path:
        raise LogsError(
            "no filesystem roots configured (set COPS_ROOTS or COPS_ALLOW_ANY_PATH)"
        )

    candidate = Path(cleaned).expanduser()
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise LogsError(f"log file not found: {cleaned}") from exc
    except OSError as exc:
        raise LogsError(f"cannot resolve path: {exc}") from exc

    if not resolved.is_file():
        raise LogsError(f"not a regular file: {resolved}")

    if roots and not _under_root(resolved, roots):
        raise LogsError(f"path is outside allowed roots: {resolved}")

    return resolved


def _pick_source(
    *,
    source: str | None,
    path: str | None,
    config: OpsConfig,
) -> tuple[str | None, str]:
    if path and (path or "").strip():
        return (source.strip() if source else "adhoc"), path.strip()

    sources = config.resolved_sources()
    name = (source or "").strip()
    if not name:
        if len(sources) == 1:
            only = next(iter(sources.items()))
            return only[0], only[1]
        if not sources:
            raise LogsError(
                "path or source is required (set COPS_LOG_SOURCES or pass path=)"
            )
        raise LogsError(
            "source is required when multiple log sources are configured "
            f"(available: {', '.join(sorted(sources))})"
        )
    if name not in sources:
        raise LogsError(
            f"unknown source: {name!r} (configured: {', '.join(sorted(sources)) or 'none'})"
        )
    return name, sources[name]


def _detect_level(text: str) -> str | None:
    m = _LEVEL_RE.search(text)
    if not m:
        return None
    raw = m.group(1).upper()
    if raw == "WARNING":
        return "WARN"
    if raw == "FATAL":
        return "CRITICAL"
    return raw


def _normalize_level(level: str | None) -> str | None:
    if level is None:
        return None
    value = level.strip().upper()
    if not value:
        return None
    if value == "WARNING":
        return "WARN"
    if value == "FATAL":
        return "CRITICAL"
    allowed = {"CRITICAL", "ERROR", "WARN", "INFO", "DEBUG", "TRACE"}
    if value not in allowed:
        raise LogsError(
            f"unsupported level: {level!r} "
            "(use CRITICAL, ERROR, WARN, INFO, DEBUG, or TRACE)"
        )
    return value


def _read_tail_bytes(path: Path, max_bytes: int) -> tuple[bytes, int, bool]:
    size = path.stat().st_size
    if size == 0:
        return b"", 0, False
    read_size = min(size, max_bytes)
    truncated = size > max_bytes
    with path.open("rb") as fh:
        if truncated:
            fh.seek(size - read_size)
        data = fh.read(read_size)
    return data, size, truncated


def _read_head_bytes(path: Path, max_bytes: int) -> tuple[bytes, int, bool]:
    size = path.stat().st_size
    if size == 0:
        return b"", 0, False
    with path.open("rb") as fh:
        data = fh.read(max_bytes)
    truncated = size > len(data)
    return data, size, truncated


def _decode_chunk(data: bytes, *, from_end: bool, byte_truncated: bool) -> str:
    if not data:
        return ""
    # If we started mid-file, drop a possible partial first line.
    if from_end and byte_truncated:
        nl = data.find(b"\n")
        if nl != -1 and nl + 1 < len(data):
            data = data[nl + 1 :]
    return data.decode("utf-8", errors="replace")


def application_logs(
    *,
    path: str | None = None,
    source: str | None = None,
    lines: int | None = None,
    from_end: bool = True,
    pattern: str | None = None,
    level: str | None = None,
    max_bytes: int | None = None,
    config: OpsConfig | None = None,
) -> LogsResult:
    """Return recent (or leading) log lines, optionally filtered."""
    cfg = config or OpsConfig()
    requested_path = (path or "").strip() or None

    try:
        src_name, raw_path = _pick_source(source=source, path=path, config=cfg)
        resolved = resolve_log_path(raw_path, config=cfg)
        want_level = _normalize_level(level)
    except LogsError as exc:
        return LogsResult(
            source=source,
            path=requested_path,
            from_end=from_end,
            pattern=pattern,
            level=level,
            error=str(exc),
        )

    n = cfg.default_lines if lines is None else int(lines)
    if n <= 0:
        return LogsResult(
            source=src_name,
            path=requested_path,
            resolved_path=str(resolved),
            from_end=from_end,
            error="lines must be > 0",
        )
    n = min(n, cfg.max_lines)

    cap = cfg.max_bytes if max_bytes is None else int(max_bytes)
    if cap <= 0:
        return LogsResult(
            source=src_name,
            path=requested_path,
            resolved_path=str(resolved),
            from_end=from_end,
            error="max_bytes must be > 0",
        )

    regex: re.Pattern[str] | None = None
    if pattern is not None and pattern != "":
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            return LogsResult(
                source=src_name,
                path=requested_path,
                resolved_path=str(resolved),
                from_end=from_end,
                pattern=pattern,
                error=f"invalid pattern: {exc}",
            )

    try:
        if from_end:
            data, file_size, byte_trunc = _read_tail_bytes(resolved, cap)
        else:
            data, file_size, byte_trunc = _read_head_bytes(resolved, cap)
        text = _decode_chunk(data, from_end=from_end, byte_truncated=byte_trunc)
    except OSError as exc:
        return LogsResult(
            source=src_name,
            path=requested_path,
            resolved_path=str(resolved),
            from_end=from_end,
            error=f"read failed: {exc}",
        )

    # Split preserving whether file ended with newline (empty trailing ignored).
    raw_lines = text.splitlines()
    numbered = list(enumerate(raw_lines, start=1))

    matched: list[LogLine] = []
    scanned = 0
    # When from_end + filters, keep the last N matches within the window.
    for num, line_text in numbered:
        scanned += 1
        detected = _detect_level(line_text)
        if want_level and detected != want_level:
            continue
        if regex is not None and regex.search(line_text) is None:
            continue
        matched.append(LogLine(line_number=num, text=line_text, level=detected))

    line_trunc = False
    if from_end:
        if len(matched) > n:
            matched = matched[-n:]
            line_trunc = True
    else:
        if len(matched) > n:
            matched = matched[:n]
            line_trunc = True

    return LogsResult(
        source=src_name,
        path=requested_path or raw_path,
        resolved_path=str(resolved),
        lines=matched,
        line_count=len(matched),
        total_lines_scanned=scanned,
        from_end=from_end,
        pattern=pattern,
        level=want_level,
        truncated=byte_trunc or line_trunc,
        bytes_read=len(data),
        file_size=file_size,
    )


__all__ = [
    "LogLine",
    "LogsError",
    "LogsResult",
    "application_logs",
    "resolve_log_path",
    "result_to_dict",
]
