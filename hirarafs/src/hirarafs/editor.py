"""file_edit: exact-string replacement in a text file.

Rewriting a whole file to change one line is how an agent loses the rest of
it. file_edit changes only what the caller quotes: each ``old`` string must
occur exactly once (or ``replace_all``), every edit must apply or none do, and
the file is replaced atomically. The result carries a unified diff so the
change can be checked without reading the file back.
"""

from __future__ import annotations

import difflib
import os
import tempfile
from pathlib import Path

from .config import FsConfig
from .paths import PathError, resolve_existing_file

MAX_DIFF_LINES = 400


class EditError(ValueError):
    """Caller-facing file_edit failure."""


def _normalise(edits, old_string, new_string, replace_all) -> list[dict]:
    if edits is not None and old_string is not None:
        raise EditError("give either edits or old_string/new_string, not both")
    if edits is None:
        if old_string is None:
            raise EditError("old_string (or edits) is required")
        edits = [{"old": old_string, "new": new_string if new_string is not None else "",
                  "replace_all": bool(replace_all)}]
    if not isinstance(edits, list) or not edits:
        raise EditError("edits must be a non-empty list")
    out = []
    for i, e in enumerate(edits):
        if not isinstance(e, dict):
            raise EditError(f"edits[{i}] must be an object with old and new")
        old, new = e.get("old"), e.get("new", "")
        if not isinstance(old, str) or old == "":
            raise EditError(f"edits[{i}].old must be a non-empty string")
        if not isinstance(new, str):
            raise EditError(f"edits[{i}].new must be a string")
        if old == new:
            raise EditError(f"edits[{i}] changes nothing (old == new)")
        out.append({"old": old, "new": new, "replace_all": bool(e.get("replace_all"))})
    return out


def file_edit(
    path: str,
    *,
    edits: list[dict] | None = None,
    old_string: str | None = None,
    new_string: str | None = None,
    replace_all: bool = False,
    dry_run: bool = False,
    config: FsConfig,
) -> dict:
    if not config.allow_write and not dry_run:
        raise EditError("file editing is disabled (CFS_ALLOW_WRITE=false)")
    plan = _normalise(edits, old_string, new_string, replace_all)
    try:
        target = resolve_existing_file(path, config=config)
    except PathError as exc:
        raise EditError(str(exc)) from exc

    raw = target.read_bytes()
    if len(raw) > config.max_write_bytes:
        raise EditError(f"file is larger than CFS_MAX_WRITE_BYTES ({config.max_write_bytes})")
    if b"\0" in raw:
        raise EditError("file looks binary (contains NUL bytes); file_edit only edits text files")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EditError("file is not utf-8 text; file_edit only edits text files") from exc

    # Keep the file's own line endings: an agent quotes "\n", a Windows file
    # has "\r\n". Match on a "\n" view, then write CRLF back if that is what
    # the file used.
    crlf = "\r\n" in text and text.count("\r\n") == text.count("\n")
    work = text.replace("\r\n", "\n") if crlf else text

    applied = []
    for i, e in enumerate(plan):
        old = e["old"].replace("\r\n", "\n") if crlf else e["old"]
        new = e["new"].replace("\r\n", "\n") if crlf else e["new"]
        count = work.count(old)
        if count == 0:
            raise EditError(f"edits[{i}].old was not found in {target.name}; nothing was changed")
        if count > 1 and not e["replace_all"]:
            raise EditError(
                f"edits[{i}].old occurs {count} times in {target.name}; quote more context "
                "to make it unique, or set replace_all. Nothing was changed"
            )
        first_line = work[: work.index(old)].count("\n") + 1
        work = work.replace(old, new) if e["replace_all"] else work.replace(old, new, 1)
        applied.append({"index": i, "replacements": count if e["replace_all"] else 1,
                        "first_line": first_line})

    result_text = work.replace("\n", "\r\n") if crlf else work
    data = result_text.encode("utf-8")
    if len(data) > config.max_write_bytes:
        raise EditError(f"edited file would exceed CFS_MAX_WRITE_BYTES ({config.max_write_bytes})")

    diff_lines = list(difflib.unified_diff(
        text.replace("\r\n", "\n").splitlines(), work.splitlines(),
        fromfile=f"a/{target.name}", tofile=f"b/{target.name}", lineterm="", n=2,
    ))
    truncated = len(diff_lines) > MAX_DIFF_LINES
    diff = "\n".join(diff_lines[:MAX_DIFF_LINES])

    if not dry_run:
        _atomic_write(target, data)

    return {
        "path": path,
        "resolved_path": str(target),
        "edits": applied,
        "replacements": sum(a["replacements"] for a in applied),
        "size": len(data),
        "dry_run": dry_run,
        "diff": diff,
        "diff_truncated": truncated,
        "error": None,
    }


def _atomic_write(target: Path, data: bytes) -> None:
    """Write next to the target and rename over it, keeping its mode."""
    mode = target.stat().st_mode & 0o7777
    fd, tmp = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


__all__ = ["EditError", "file_edit"]
