"""archive_list and archive_extract: zip and tar, safely.

Extracting an untrusted archive is a classic way to get owned: entries named
``../../.bashrc`` or ``/etc/cron.d/x`` (zip-slip), symlinks that point out of
the destination and are then written through, device files, and bombs that
declare 1 KB and inflate to terabytes. Every one of those is refused here,
and the size and count caps are enforced on the bytes actually written, not
on what the archive claims.
"""

from __future__ import annotations

import stat
import tarfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from .config import FsConfig
from .paths import PathError, resolve_existing_dir, resolve_existing_file

CHUNK = 1 << 16


class ArchiveError(ValueError):
    """Caller-facing archive failure."""


def _kind(path: Path) -> str:
    if zipfile.is_zipfile(path):
        return "zip"
    try:
        if tarfile.is_tarfile(path):
            return "tar"
    except OSError:
        pass
    raise ArchiveError("not a zip or tar archive (tar may be .gz, .bz2 or .xz compressed)")


def _unsafe_name(name: str) -> str | None:
    if not name:
        return "empty name"
    if name.startswith("/") or name.startswith("\\") or (len(name) > 1 and name[1] == ":"):
        return "absolute path"
    parts = PurePosixPath(name.replace("\\", "/")).parts
    if ".." in parts:
        return "path escapes the destination (..)"
    return None


def _members(path: Path, kind: str):
    """Yield dicts describing each entry, without reading data."""
    if kind == "zip":
        with zipfile.ZipFile(path) as zf:
            for info in zf.infolist():
                mode = (info.external_attr >> 16) & 0xFFFF
                if info.is_dir():
                    typ = "dir"
                elif stat.S_ISLNK(mode):
                    typ = "symlink"
                else:
                    typ = "file"
                yield {
                    "name": info.filename,
                    "type": typ,
                    "size": info.file_size,
                    "compressed_size": info.compress_size,
                    "modified": datetime(*info.date_time).isoformat() if info.date_time[0] >= 1980 else None,
                    "encrypted": bool(info.flag_bits & 0x1),
                }
    else:
        with tarfile.open(path) as tf:
            for m in tf:
                typ = ("dir" if m.isdir() else "file" if m.isfile() else
                       "symlink" if m.issym() else "hardlink" if m.islnk() else "special")
                yield {
                    "name": m.name,
                    "type": typ,
                    "size": m.size,
                    "compressed_size": None,
                    "modified": datetime.fromtimestamp(m.mtime, timezone.utc).isoformat(timespec="seconds"),
                    "encrypted": False,
                    **({"link_target": m.linkname} if typ in ("symlink", "hardlink") else {}),
                }


def _safe_dir(out: Path, parts: tuple[str, ...]) -> Path | None:
    """Create ``out/parts...`` one level at a time, refusing any symlink.

    Checking after ``mkdir(parents=True)`` would be too late: a symlinked
    directory already inside the destination would have carried the mkdir
    outside it. Walking step by step never touches anything but real
    directories under ``out``.
    """
    current = out
    for part in parts:
        current = current / part
        if current.is_symlink():
            return None
        if current.exists():
            if not current.is_dir():
                return None
        else:
            current.mkdir()
    return current


def archive_list(path: str, *, max_entries: int = 1000, config: FsConfig) -> dict:
    try:
        src = resolve_existing_file(path, config=config)
    except PathError as exc:
        raise ArchiveError(str(exc)) from exc
    kind = _kind(src)
    entries, count, total, unsafe = [], 0, 0, 0
    limit = max(1, min(int(max_entries), 20_000))
    for m in _members(src, kind):
        count += 1
        total += m["size"] or 0
        reason = _unsafe_name(m["name"])
        if m["type"] in ("symlink", "hardlink", "special"):
            reason = reason or f"{m['type']} (not extracted)"
        if reason:
            m["unsafe"] = reason
            unsafe += 1
        if len(entries) < limit:
            entries.append(m)
    compressed = src.stat().st_size
    return {
        "path": path,
        "format": kind,
        "entries": entries,
        "count": count,
        "total_size": total,
        "archive_size": compressed,
        "ratio": round(total / compressed, 1) if compressed else None,
        "unsafe_entries": unsafe,
        "truncated": count > len(entries),
        "error": None,
    }


def archive_extract(path: str, *, dest: str, members: list[str] | None = None,
                    overwrite: bool = False, config: FsConfig) -> dict:
    if not config.allow_write:
        raise ArchiveError("extraction is disabled (CFS_ALLOW_WRITE=false)")
    try:
        src = resolve_existing_file(path, config=config)
        out = resolve_existing_dir(dest, config=config)
    except PathError as exc:
        raise ArchiveError(str(exc)) from exc
    kind = _kind(src)
    wanted = set(members) if members else None

    extracted, skipped = [], []
    written = 0
    files = 0

    def target_for(name: str) -> Path | None:
        reason = _unsafe_name(name)
        if reason:
            skipped.append({"name": name, "reason": reason})
            return None
        rel = PurePosixPath(name.replace("\\", "/"))
        parent = _safe_dir(out, rel.parts[:-1])
        if parent is None:
            skipped.append({"name": name, "reason": "parent is a symlink or a file"})
            return None
        final = parent / rel.parts[-1]
        if final.is_symlink():
            skipped.append({"name": name, "reason": "destination is a symlink"})
            return None
        if final.exists() and not overwrite:
            skipped.append({"name": name, "reason": "exists (set overwrite=true)"})
            return None
        return final

    def copy(stream, final: Path, name: str) -> None:
        nonlocal written, files
        if files >= config.max_extract_files:
            raise ArchiveError(f"more than CFS_MAX_EXTRACT_FILES ({config.max_extract_files}) files")
        tmp = final.with_name(f".{final.name}.part")
        size = 0
        try:
            with open(tmp, "wb") as handle:
                while True:
                    chunk = stream.read(CHUNK)
                    if not chunk:
                        break
                    size += len(chunk)
                    if written + size > config.max_extract_bytes:
                        raise ArchiveError(
                            f"extracted data exceeds CFS_MAX_EXTRACT_BYTES ({config.max_extract_bytes}); "
                            "possible archive bomb, stopped")
                    handle.write(chunk)
            tmp.replace(final)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        written += size
        files += 1
        extracted.append({"name": name, "path": str(final), "size": size})

    if kind == "zip":
        with zipfile.ZipFile(src) as zf:
            for info in zf.infolist():
                if wanted is not None and info.filename not in wanted:
                    continue
                mode = (info.external_attr >> 16) & 0xFFFF
                if stat.S_ISLNK(mode):
                    skipped.append({"name": info.filename, "reason": "symlink (not extracted)"})
                    continue
                if info.flag_bits & 0x1:
                    skipped.append({"name": info.filename, "reason": "encrypted"})
                    continue
                if info.is_dir():
                    if _unsafe_name(info.filename) is None:
                        _safe_dir(out, PurePosixPath(info.filename).parts)
                    continue
                final = target_for(info.filename)
                if final is None:
                    continue
                with zf.open(info) as stream:
                    copy(stream, final, info.filename)
    else:
        with tarfile.open(src) as tf:
            for m in tf:
                if wanted is not None and m.name not in wanted:
                    continue
                if m.isdir():
                    if _unsafe_name(m.name) is None:
                        _safe_dir(out, PurePosixPath(m.name).parts)
                    continue
                if not m.isfile():
                    kind_name = "symlink" if m.issym() else "hardlink" if m.islnk() else "special file"
                    skipped.append({"name": m.name, "reason": f"{kind_name} (not extracted)"})
                    continue
                final = target_for(m.name)
                if final is None:
                    continue
                stream = tf.extractfile(m)
                if stream is None:
                    skipped.append({"name": m.name, "reason": "unreadable entry"})
                    continue
                with stream:
                    copy(stream, final, m.name)

    if wanted is not None:
        found = {e["name"] for e in extracted} | {s["name"] for s in skipped}
        for name in sorted(wanted - found):
            skipped.append({"name": name, "reason": "not in archive"})
    return {
        "path": path,
        "dest": str(out),
        "format": kind,
        "extracted": extracted[:2000],
        "extracted_count": len(extracted),
        "bytes_written": written,
        "skipped": skipped[:2000],
        "skipped_count": len(skipped),
        "error": None,
    }


__all__ = ["ArchiveError", "archive_extract", "archive_list"]
