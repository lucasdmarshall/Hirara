"""Write a file under an allowlisted path.

Encodes text or base64 content, enforces CFS_ROOTS / size caps, and returns
a structured result (errors in the envelope, not as exceptions to HTTP).
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

from .config import FsConfig
from .paths import PathError, resolve_write_target

_TEXT_ENCODINGS = frozenset({"utf-8", "utf8", "ascii", "latin-1", "latin1", "cp1252"})
_BINARY_ENCODINGS = frozenset({"base64", "b64"})


class WriteError(ValueError):
    """Caller-facing file_write validation / access failure."""


@dataclass
class WriteResult:
    path: str | None = None
    resolved_path: str | None = None
    bytes_written: int | None = None
    size: int | None = None
    encoding: str | None = None
    created: bool | None = None
    appended: bool = False
    error: str | None = None


def write_result_to_dict(result: WriteResult) -> dict:
    return {
        "path": result.path,
        "resolved_path": result.resolved_path,
        "bytes_written": result.bytes_written,
        "size": result.size,
        "encoding": result.encoding,
        "created": result.created,
        "appended": result.appended,
        "error": result.error,
    }


def _normalize_encoding(raw: str | None, default: str) -> str:
    value = (raw if raw is not None else default or "utf-8").strip().lower()
    if value in {"utf8"}:
        return "utf-8"
    if value in {"latin1"}:
        return "latin-1"
    if value in {"b64"}:
        return "base64"
    if value in {"auto", ""}:
        return "utf-8"
    return value


def _decode_content(content: str, encoding: str) -> tuple[bytes, str]:
    if content is None:
        raise WriteError("content is required")
    if not isinstance(content, str):
        raise WriteError("content must be a string")

    if encoding in _BINARY_ENCODINGS:
        try:
            return base64.b64decode(content, validate=False), "base64"
        except Exception as exc:  # noqa: BLE001
            raise WriteError(f"invalid base64 content: {exc}") from exc

    if encoding not in _TEXT_ENCODINGS:
        raise WriteError(
            f"unsupported encoding: {encoding!r} "
            "(use utf-8, ascii, latin-1, or base64)"
        )

    codec = "utf-8" if encoding == "utf-8" else encoding
    try:
        return content.encode(codec), codec
    except UnicodeEncodeError as exc:
        raise WriteError(f"encode failed as {codec}: {exc}") from exc


def file_write(
    path: str,
    content: str,
    *,
    encoding: str | None = None,
    append: bool = False,
    create_parents: bool = False,
    overwrite: bool = True,
    max_bytes: int | None = None,
    config: FsConfig | None = None,
) -> WriteResult:
    """Write ``content`` to ``path`` and return a structured result."""
    cfg = config or FsConfig()
    requested = (path or "").strip() or None

    if not cfg.allow_write:
        return WriteResult(
            path=requested,
            error="file_write is disabled on this server (CFS_ALLOW_WRITE=false)",
        )

    enc = _normalize_encoding(encoding, "utf-8")
    try:
        data, used_enc = _decode_content(content, enc)
    except WriteError as exc:
        return WriteResult(path=requested, error=str(exc))

    cap = cfg.max_write_bytes if max_bytes is None else int(max_bytes)
    if cap <= 0:
        return WriteResult(path=requested, error="max_bytes must be > 0")
    if len(data) > cap:
        return WriteResult(
            path=requested,
            encoding=used_enc,
            error=f"content exceeds max_bytes ({len(data)} > {cap})",
        )

    try:
        target = resolve_write_target(
            path, config=cfg, create_parents=create_parents
        )
    except PathError as exc:
        return WriteResult(path=requested, encoding=used_enc, error=str(exc))

    existed = target.exists()
    if existed and not overwrite and not append:
        return WriteResult(
            path=requested,
            resolved_path=str(target),
            encoding=used_enc,
            created=False,
            appended=False,
            error=f"file already exists (overwrite=false): {target}",
        )

    mode = "ab" if append else "wb"
    try:
        with target.open(mode) as fh:
            fh.write(data)
        size = target.stat().st_size
    except OSError as exc:
        return WriteResult(
            path=requested,
            resolved_path=str(target),
            encoding=used_enc,
            created=not existed,
            appended=append,
            error=f"write failed: {exc}",
        )

    return WriteResult(
        path=requested,
        resolved_path=str(target),
        bytes_written=len(data),
        size=size,
        encoding=used_enc,
        created=not existed,
        appended=append,
    )


__all__ = [
    "WriteError",
    "WriteResult",
    "file_write",
    "write_result_to_dict",
]
