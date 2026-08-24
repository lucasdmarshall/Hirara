"""Read a file from an allowlisted path.

Resolves the path, enforces CFS_ROOTS (or allow_any_path), caps bytes, and
returns text or base64 content in a structured result.
"""

from __future__ import annotations

import base64
import mimetypes
from dataclasses import dataclass
from pathlib import Path

from .config import FsConfig

_TEXT_ENCODINGS = frozenset({"utf-8", "utf8", "ascii", "latin-1", "latin1", "cp1252"})
_BINARY_ENCODINGS = frozenset({"base64", "b64"})
_AUTO = frozenset({"auto", ""})


class ReadError(ValueError):
    """Caller-facing file_read validation / access failure."""


@dataclass
class ReadResult:
    path: str | None = None
    resolved_path: str | None = None
    content: str | None = None
    encoding: str | None = None
    size: int | None = None
    bytes_read: int | None = None
    offset: int = 0
    truncated: bool = False
    content_type: str | None = None
    is_binary: bool | None = None
    error: str | None = None


def result_to_dict(result: ReadResult) -> dict:
    return {
        "path": result.path,
        "resolved_path": result.resolved_path,
        "content": result.content,
        "encoding": result.encoding,
        "size": result.size,
        "bytes_read": result.bytes_read,
        "offset": result.offset,
        "truncated": result.truncated,
        "content_type": result.content_type,
        "is_binary": result.is_binary,
        "error": result.error,
    }


def _normalize_encoding(raw: str | None, default: str) -> str:
    value = (raw if raw is not None else default or "auto").strip().lower()
    if value in {"utf8"}:
        return "utf-8"
    if value in {"latin1"}:
        return "latin-1"
    if value in {"b64"}:
        return "base64"
    return value


def _parse_roots(config: FsConfig) -> list[Path]:
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


def resolve_path(path: str, *, config: FsConfig) -> Path:
    """Expand, resolve, and gate ``path`` against configured roots."""
    cleaned = (path or "").strip()
    if not cleaned:
        raise ReadError("path is required")

    roots = _parse_roots(config)
    if not roots and not config.allow_any_path:
        raise ReadError(
            "no filesystem roots configured (set CFS_ROOTS or CFS_ALLOW_ANY_PATH)"
        )

    candidate = Path(cleaned).expanduser()
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ReadError(f"file not found: {cleaned}") from exc
    except OSError as exc:
        raise ReadError(f"cannot resolve path: {exc}") from exc

    if not resolved.is_file():
        raise ReadError(f"not a regular file: {resolved}")

    if roots and not _under_root(resolved, roots):
        raise ReadError(f"path is outside allowed roots: {resolved}")

    return resolved


def file_read(
    path: str,
    *,
    encoding: str | None = None,
    max_bytes: int | None = None,
    offset: int = 0,
    config: FsConfig | None = None,
) -> ReadResult:
    """Read bytes from ``path`` and return a structured result."""
    cfg = config or FsConfig()
    requested = (path or "").strip() or None

    try:
        resolved = resolve_path(path, config=cfg)
    except ReadError as exc:
        return ReadResult(path=requested, error=str(exc))

    if offset < 0:
        return ReadResult(
            path=requested,
            resolved_path=str(resolved),
            error="offset must be >= 0",
        )

    cap = cfg.max_bytes if max_bytes is None else int(max_bytes)
    if cap <= 0:
        return ReadResult(
            path=requested,
            resolved_path=str(resolved),
            error="max_bytes must be > 0",
        )

    enc = _normalize_encoding(encoding, cfg.default_encoding)
    if enc not in _AUTO | _TEXT_ENCODINGS | _BINARY_ENCODINGS:
        return ReadResult(
            path=requested,
            resolved_path=str(resolved),
            error=(
                f"unsupported encoding: {encoding!r} "
                "(use auto, utf-8, ascii, latin-1, or base64)"
            ),
        )

    try:
        size = resolved.stat().st_size
    except OSError as exc:
        return ReadResult(
            path=requested,
            resolved_path=str(resolved),
            error=f"stat failed: {exc}",
        )

    try:
        with resolved.open("rb") as fh:
            if offset:
                fh.seek(offset)
            # Read one extra byte to detect truncation without a second pass.
            chunk = fh.read(cap + 1)
    except OSError as exc:
        return ReadResult(
            path=requested,
            resolved_path=str(resolved),
            size=size,
            offset=offset,
            error=f"read failed: {exc}",
        )

    truncated = len(chunk) > cap
    data = chunk[:cap]
    ctype, _ = mimetypes.guess_type(str(resolved))
    content_type = ctype

    if enc in _BINARY_ENCODINGS:
        return ReadResult(
            path=requested,
            resolved_path=str(resolved),
            content=base64.b64encode(data).decode("ascii"),
            encoding="base64",
            size=size,
            bytes_read=len(data),
            offset=offset,
            truncated=truncated,
            content_type=content_type,
            is_binary=True,
        )

    if enc in _AUTO:
        try:
            text = data.decode("utf-8")
            return ReadResult(
                path=requested,
                resolved_path=str(resolved),
                content=text,
                encoding="utf-8",
                size=size,
                bytes_read=len(data),
                offset=offset,
                truncated=truncated,
                content_type=content_type or "text/plain",
                is_binary=False,
            )
        except UnicodeDecodeError:
            return ReadResult(
                path=requested,
                resolved_path=str(resolved),
                content=base64.b64encode(data).decode("ascii"),
                encoding="base64",
                size=size,
                bytes_read=len(data),
                offset=offset,
                truncated=truncated,
                content_type=content_type or "application/octet-stream",
                is_binary=True,
            )

    # Explicit text encoding.
    codec = "utf-8" if enc == "utf-8" else enc
    try:
        text = data.decode(codec)
    except UnicodeDecodeError as exc:
        return ReadResult(
            path=requested,
            resolved_path=str(resolved),
            size=size,
            bytes_read=len(data),
            offset=offset,
            truncated=truncated,
            content_type=content_type,
            is_binary=True,
            error=f"decode failed as {codec}: {exc}; retry with encoding=base64",
        )

    return ReadResult(
        path=requested,
        resolved_path=str(resolved),
        content=text,
        encoding=codec,
        size=size,
        bytes_read=len(data),
        offset=offset,
        truncated=truncated,
        content_type=content_type or "text/plain",
        is_binary=False,
    )


__all__ = [
    "ReadError",
    "ReadResult",
    "file_read",
    "resolve_path",
    "result_to_dict",
]
