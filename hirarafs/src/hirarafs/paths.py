"""Shared path resolution and root gating for hirarafs."""

from __future__ import annotations

from pathlib import Path

from .config import FsConfig


class PathError(ValueError):
    """Caller-facing path validation / access failure."""


def parse_roots(config: FsConfig) -> list[Path]:
    roots: list[Path] = []
    for item in config.roots:
        cleaned = (item or "").strip()
        if not cleaned:
            continue
        roots.append(Path(cleaned).expanduser().resolve())
    return roots


def under_root(resolved: Path, roots: list[Path]) -> bool:
    for root in roots:
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def require_roots(config: FsConfig) -> list[Path]:
    roots = parse_roots(config)
    if not roots and not config.allow_any_path:
        raise PathError(
            "no filesystem roots configured (set CFS_ROOTS or CFS_ALLOW_ANY_PATH)"
        )
    return roots


def resolve_existing_file(path: str, *, config: FsConfig) -> Path:
    """Expand, resolve, and gate an existing regular file."""
    cleaned = (path or "").strip()
    if not cleaned:
        raise PathError("path is required")

    roots = require_roots(config)
    candidate = Path(cleaned).expanduser()
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise PathError(f"file not found: {cleaned}") from exc
    except OSError as exc:
        raise PathError(f"cannot resolve path: {exc}") from exc

    if not resolved.is_file():
        raise PathError(f"not a regular file: {resolved}")

    if roots and not under_root(resolved, roots):
        raise PathError(f"path is outside allowed roots: {resolved}")

    return resolved


def resolve_write_target(
    path: str,
    *,
    config: FsConfig,
    create_parents: bool = False,
) -> Path:
    """Resolve a write destination; file may not exist yet.

    Gates the final path (and any created parents) against configured roots.
    """
    cleaned = (path or "").strip()
    if not cleaned:
        raise PathError("path is required")
    if cleaned.endswith("/") or cleaned.endswith("\\"):
        raise PathError("path must name a file, not a directory")

    roots = require_roots(config)
    candidate = Path(cleaned).expanduser()

    if candidate.exists():
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise PathError(f"cannot resolve path: {exc}") from exc
        if resolved.is_dir():
            raise PathError(f"path is a directory: {resolved}")
        if not resolved.is_file():
            raise PathError(f"not a regular file: {resolved}")
        if roots and not under_root(resolved, roots):
            raise PathError(f"path is outside allowed roots: {resolved}")
        return resolved

    # New file: resolve / create parent, then join the final name.
    parent = candidate.parent
    if not parent.exists():
        if not create_parents:
            raise PathError(f"parent directory does not exist: {parent}")
        # Find the deepest existing ancestor; it must be under a root.
        cursor = parent
        while not cursor.exists() and cursor != cursor.parent:
            cursor = cursor.parent
        if not cursor.exists():
            raise PathError(f"cannot create parents under missing root: {parent}")
        try:
            ancestor = cursor.resolve(strict=True)
        except OSError as exc:
            raise PathError(f"cannot resolve parent: {exc}") from exc
        if not ancestor.is_dir():
            raise PathError(f"parent is not a directory: {ancestor}")
        if roots and not under_root(ancestor, roots):
            raise PathError(f"path is outside allowed roots: {parent}")
        try:
            parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise PathError(f"cannot create parent directories: {exc}") from exc

    try:
        parent_resolved = parent.resolve(strict=True)
    except FileNotFoundError as exc:
        raise PathError(f"parent directory does not exist: {parent}") from exc
    except OSError as exc:
        raise PathError(f"cannot resolve parent: {exc}") from exc

    if not parent_resolved.is_dir():
        raise PathError(f"parent is not a directory: {parent_resolved}")

    target = (parent_resolved / candidate.name).resolve(strict=False)
    # After resolve(strict=False), still ensure we did not escape via symlink parents.
    if roots and not under_root(target, roots):
        raise PathError(f"path is outside allowed roots: {target}")
    if target.exists() and target.is_dir():
        raise PathError(f"path is a directory: {target}")
    return target


__all__ = [
    "PathError",
    "parse_roots",
    "require_roots",
    "resolve_existing_file",
    "resolve_write_target",
    "under_root",
]
