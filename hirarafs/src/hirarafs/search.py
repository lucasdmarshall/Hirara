"""file_search and file_list: find things under the allowed roots.

An agent cannot read a file it cannot find. These walk the tree once, skip
the usual noise (VCS metadata, dependency folders, binaries, huge files),
never follow a symlink out of the allowed roots, and stop at a cap instead
of running unbounded.
"""

from __future__ import annotations

import fnmatch
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from .config import FsConfig
from .paths import PathError, parse_roots, resolve_existing_dir, resolve_existing_file, under_root

SKIP_DIRS = frozenset({
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", ".tox", ".idea", ".cache", "dist", "build",
})


class SearchError(ValueError):
    """Caller-facing file_search / file_list failure."""


def _walk(base: Path, roots: list[Path], *, include_hidden: bool, skip_dirs: bool):
    """Yield (path, is_dir) under base, depth-first, without leaving the roots."""
    stack = [base]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                entries = sorted(it, key=lambda e: e.name)
        except OSError:
            continue
        dirs = []
        for entry in entries:
            if not include_hidden and entry.name.startswith("."):
                continue
            path = Path(entry.path)
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
                is_link = entry.is_symlink()
            except OSError:
                continue
            if is_link:
                # Report links, but never descend through one; a link can point
                # anywhere, including outside the allowed roots.
                try:
                    real = path.resolve(strict=True)
                except OSError:
                    continue
                if roots and not under_root(real, roots):
                    continue
                yield path, real.is_dir(), True
                continue
            if is_dir:
                if skip_dirs and entry.name in SKIP_DIRS:
                    continue
                dirs.append(path)
            yield path, is_dir, False
        stack.extend(reversed(dirs))


def file_list(path: str | None, *, pattern: str | None = None, recursive: bool = False,
              include_hidden: bool = False, max_entries: int = 500,
              config: FsConfig) -> dict:
    try:
        base = resolve_existing_dir(path, config=config)
    except PathError as exc:
        raise SearchError(str(exc)) from exc
    roots = parse_roots(config)
    limit = max(1, min(int(max_entries), 10_000))
    entries, truncated, total = [], False, 0
    walker = _walk(base, roots, include_hidden=include_hidden, skip_dirs=recursive)
    for p, is_dir, is_link in walker:
        rel = p.relative_to(base).as_posix()
        if not recursive and "/" in rel:
            continue
        if pattern and not (fnmatch.fnmatch(p.name, pattern) or fnmatch.fnmatch(rel, pattern)):
            continue
        total += 1
        if len(entries) >= limit:
            truncated = True
            continue
        try:
            st = p.stat() if not is_link else p.lstat()
        except OSError:
            continue
        entries.append({
            "path": rel + ("/" if is_dir and not is_link else ""),
            "type": "symlink" if is_link else ("dir" if is_dir else "file"),
            "size": None if is_dir else st.st_size,
            "modified": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(timespec="seconds"),
        })
        if not recursive and total > limit * 4:
            break
    return {
        "path": str(base),
        "pattern": pattern,
        "recursive": recursive,
        "entries": entries,
        "count": len(entries),
        "matched": total,
        "truncated": truncated,
        "error": None,
    }


def file_search(pattern: str, *, path: str | None = None, glob: str | None = None,
                regex: bool = True, case_sensitive: bool = False, context: int = 0,
                max_results: int = 200, include_hidden: bool = False,
                config: FsConfig) -> dict:
    if not pattern:
        raise SearchError("pattern is required")
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        rx = re.compile(pattern if regex else re.escape(pattern), flags)
    except re.error as exc:
        raise SearchError(f"invalid regex: {exc}") from exc
    context = max(0, min(int(context), 5))
    limit = max(1, min(int(max_results), 5000))

    roots = parse_roots(config)
    target = (path or "").strip()
    files: list[Path]
    if target and Path(target).expanduser().is_file():
        try:
            files = [resolve_existing_file(target, config=config)]
        except PathError as exc:
            raise SearchError(str(exc)) from exc
        base = files[0].parent
    else:
        try:
            base = resolve_existing_dir(target or None, config=config)
        except PathError as exc:
            raise SearchError(str(exc)) from exc
        files = []

    def candidates():
        if files:
            yield from files
            return
        for p, is_dir, is_link in _walk(base, roots, include_hidden=include_hidden, skip_dirs=True):
            if is_dir or is_link:
                continue
            rel = p.relative_to(base).as_posix()
            if glob and not (fnmatch.fnmatch(p.name, glob) or fnmatch.fnmatch(rel, glob)):
                continue
            yield p

    matches, scanned, skipped, truncated = [], 0, 0, False
    files_with_hits = set()
    for p in candidates():
        if scanned >= config.max_search_files:
            truncated = True
            break
        scanned += 1
        try:
            if p.stat().st_size > config.max_search_file_bytes:
                skipped += 1
                continue
            raw = p.read_bytes()
        except OSError:
            skipped += 1
            continue
        if b"\0" in raw[:8192]:
            skipped += 1  # binary
            continue
        text = raw.decode("utf-8", errors="replace")
        lines = text.splitlines()
        for i, line in enumerate(lines):
            m = rx.search(line)
            if not m:
                continue
            if len(matches) >= limit:
                truncated = True
                break
            files_with_hits.add(p)
            item = {
                "path": p.relative_to(base).as_posix() if p.is_relative_to(base) else str(p),
                "line": i + 1,
                "column": m.start() + 1,
                "text": line[:500],
            }
            if context:
                item["before"] = [ln[:500] for ln in lines[max(0, i - context): i]]
                item["after"] = [ln[:500] for ln in lines[i + 1: i + 1 + context]]
            matches.append(item)
        if truncated:
            break
    return {
        "pattern": pattern,
        "path": str(base),
        "matches": matches,
        "count": len(matches),
        "files_matched": len(files_with_hits),
        "files_scanned": scanned,
        "files_skipped": skipped,
        "truncated": truncated,
        "error": None,
    }


__all__ = ["SKIP_DIRS", "SearchError", "file_list", "file_search"]
