"""The tool layer: schema and JSON-ready results.

Both front ends (HTTP service and MCP server) call into here, so the two can
never drift apart in behaviour — only in transport.

Tools: ``file_read``, ``file_write``, ``file_edit``, ``file_search``,
``file_list``, ``archive_list``, ``archive_extract``.
"""

from __future__ import annotations

from hirara_core.policy import tool_permission, visible_schemas

import logging
from dataclasses import dataclass

from .archive import ArchiveError, archive_extract as extract_archive
from .archive import archive_list as list_archive
from .config import FsConfig
from .editor import EditError, file_edit as edit_file
from .search import SearchError, file_list as list_files, file_search as search_files
from .reader import ReadError, file_read as read_file, result_to_dict
from .writer import WriteError, file_write as write_file, write_result_to_dict

log = logging.getLogger(__name__)


FILE_READ_SCHEMA = {
    "name": "file_read",
    "description": (
        "Read a file from the local filesystem. Returns content as utf-8 text "
        "when possible, otherwise base64. Paths are gated by configured roots "
        "(CFS_ROOTS); size is capped by max_bytes. Use offset to page through "
        "large files. Errors return in the JSON envelope, not as HTTP failures."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute or relative path to a regular file.",
            },
            "encoding": {
                "type": "string",
                "enum": ["auto", "utf-8", "ascii", "latin-1", "base64"],
                "description": (
                    "How to return content. auto (default): utf-8 if decodable, "
                    "else base64. base64 always returns binary-safe content."
                ),
            },
            "max_bytes": {
                "type": "integer",
                "minimum": 1,
                "description": "Cap on bytes to return (after offset).",
            },
            "offset": {
                "type": "integer",
                "minimum": 0,
                "description": "Byte offset to start reading from (default 0).",
            },
        },
        "required": ["path"],
        "additionalProperties": False,
    },
}


FILE_WRITE_SCHEMA = {
    "name": "file_write",
    "description": (
        "Write content to a local file under configured roots (CFS_ROOTS). "
        "Content is utf-8 text by default, or base64 for binary. Optional "
        "append, create_parents, and overwrite. Size capped by max_bytes. "
        "Errors return in the JSON envelope, not as HTTP failures."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute or relative path to write.",
            },
            "content": {
                "type": "string",
                "description": "File contents (text or base64, per encoding).",
            },
            "encoding": {
                "type": "string",
                "enum": ["utf-8", "ascii", "latin-1", "base64"],
                "description": "How to interpret content (default utf-8).",
            },
            "append": {
                "type": "boolean",
                "description": "Append to the file instead of replacing it.",
            },
            "create_parents": {
                "type": "boolean",
                "description": "Create missing parent directories (under roots).",
            },
            "overwrite": {
                "type": "boolean",
                "description": (
                    "When false and the file exists (and append is false), "
                    "return an error instead of replacing it (default true)."
                ),
            },
            "max_bytes": {
                "type": "integer",
                "minimum": 1,
                "description": "Cap on content bytes after encoding.",
            },
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    },
}


FILE_EDIT_SCHEMA = {
    "name": "file_edit",
    "description": (
        "Edit a text file by exact string replacement instead of rewriting it. "
        "old_string must occur exactly once (quote enough context to make it "
        "unique) unless replace_all is set. Pass edits for several changes; all "
        "apply or none do. The file is replaced atomically and a unified diff "
        "is returned. dry_run shows the diff without writing."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File to edit (gated by CFS_ROOTS)."},
            "old_string": {"type": "string", "description": "Exact text to replace."},
            "new_string": {"type": "string", "description": "Replacement text (may be empty)."},
            "replace_all": {"type": "boolean", "description": "Replace every occurrence."},
            "edits": {
                "type": "array",
                "description": "Several edits applied in order, all or nothing.",
                "items": {
                    "type": "object",
                    "properties": {
                        "old": {"type": "string"},
                        "new": {"type": "string"},
                        "replace_all": {"type": "boolean"},
                    },
                    "required": ["old", "new"],
                },
            },
            "dry_run": {"type": "boolean", "description": "Return the diff only."},
        },
        "required": ["path"],
        "additionalProperties": False,
    },
}


FILE_SEARCH_SCHEMA = {
    "name": "file_search",
    "description": (
        "Search file contents under a directory (or one file) for a regex or "
        "literal, like grep. Returns path, line, column and the line text, with "
        "optional context lines. Skips binaries, files over the size cap, "
        "hidden files and dependency folders (.git, node_modules, ...)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Regex (or literal with regex=false)."},
            "path": {"type": "string", "description": "Directory or file (default: first root)."},
            "glob": {"type": "string", "description": "Only files matching, e.g. *.py."},
            "regex": {"type": "boolean", "description": "Treat pattern as regex (default true)."},
            "case_sensitive": {"type": "boolean", "description": "Default false."},
            "context": {"type": "integer", "minimum": 0, "maximum": 5,
                        "description": "Lines of context before/after."},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 5000,
                            "description": "Most matches returned (default 200)."},
            "include_hidden": {"type": "boolean", "description": "Search dotfiles too."},
        },
        "required": ["pattern"],
        "additionalProperties": False,
    },
}


FILE_LIST_SCHEMA = {
    "name": "file_list",
    "description": (
        "List a directory: names, type, size and modified time. Filter with a "
        "glob pattern; recursive walks the tree (skipping .git, node_modules "
        "and similar). Never follows a symlink outside the allowed roots."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Directory (default: first root)."},
            "pattern": {"type": "string", "description": "Glob, e.g. *.md or src/*.py."},
            "recursive": {"type": "boolean", "description": "Walk subdirectories."},
            "include_hidden": {"type": "boolean", "description": "Include dotfiles."},
            "max_entries": {"type": "integer", "minimum": 1, "maximum": 10000,
                            "description": "Most entries returned (default 500)."},
        },
        "additionalProperties": False,
    },
}


ARCHIVE_LIST_SCHEMA = {
    "name": "archive_list",
    "description": (
        "List what is inside a zip or tar (.tar, .tar.gz, .tgz, .tar.bz2, "
        ".tar.xz) without extracting: names, sizes, compression ratio, and any "
        "entries that would be unsafe to extract (absolute paths, .., links)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Archive file."},
            "max_entries": {"type": "integer", "minimum": 1, "maximum": 20000},
        },
        "required": ["path"],
        "additionalProperties": False,
    },
}


ARCHIVE_EXTRACT_SCHEMA = {
    "name": "archive_extract",
    "description": (
        "Extract a zip or tar into an existing directory, safely: entries that "
        "escape the destination, links and device files are skipped and "
        "reported, nothing is written through a symlink, and total size and "
        "file count are capped while writing (archive bombs are stopped). "
        "Existing files are kept unless overwrite is set."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Archive file."},
            "dest": {"type": "string", "description": "Existing destination directory."},
            "members": {"type": "array", "items": {"type": "string"},
                        "description": "Only these entry names (default all)."},
            "overwrite": {"type": "boolean", "description": "Replace existing files."},
        },
        "required": ["path", "dest"],
        "additionalProperties": False,
    },
}



def _mutation_schema(name, description, properties, required):
    return {"name": name, "description": description,
            "input_schema": {"type": "object", "properties": properties,
                             "required": required, "additionalProperties": False}}

FILE_COPY_SCHEMA = _mutation_schema("file_copy", "Copy one regular file within CFS_ROOTS. Requires CFS_ALLOW_WRITE. No directories or symlinks. Size capped by CFS_MAX_WRITE_BYTES. Existing destination is kept unless overwrite=true.",
    {"path": {"type": "string"}, "dest": {"type": "string"}, "overwrite": {"type": "boolean"}}, ["path", "dest"])
FILE_MOVE_SCHEMA = _mutation_schema("file_move", "Move one regular file within CFS_ROOTS. Requires CFS_ALLOW_WRITE. No directories or symlinks. Destination parent must exist; cross-filesystem moves fail safely. Default overwrite=false.",
    {"path": {"type": "string"}, "dest": {"type": "string"}, "overwrite": {"type": "boolean"}}, ["path", "dest"])
FILE_RENAME_SCHEMA = _mutation_schema("file_rename", "Rename one regular file in its current directory. name must be a filename, without directories. Requires CFS_ALLOW_WRITE. Default overwrite=false.",
    {"path": {"type": "string"}, "name": {"type": "string"}, "overwrite": {"type": "boolean"}}, ["path", "name"])
FILE_DELETE_SCHEMA = _mutation_schema("file_delete", "Permanently delete one regular file within CFS_ROOTS. Requires CFS_ALLOW_WRITE. Directories and symlinks are refused. No recursive deletion.",
    {"path": {"type": "string"}}, ["path"])

def _read_envelope(**overrides) -> dict:
    envelope = {
        "path": None,
        "resolved_path": None,
        "content": None,
        "encoding": None,
        "size": None,
        "bytes_read": None,
        "offset": 0,
        "truncated": False,
        "content_type": None,
        "is_binary": None,
        "error": None,
    }
    envelope.update(overrides)
    return envelope


def _write_envelope(**overrides) -> dict:
    envelope = {
        "path": None,
        "resolved_path": None,
        "bytes_written": None,
        "size": None,
        "encoding": None,
        "created": None,
        "appended": False,
        "error": None,
    }
    envelope.update(overrides)
    return envelope


@dataclass
class Toolset:
    """Filesystem tools sharing one config."""

    config: FsConfig

    @classmethod
    def from_env(cls) -> "Toolset":
        return cls(config=FsConfig.from_env())

    @visible_schemas
    def schemas(self) -> list[dict]:
        return [FILE_READ_SCHEMA, FILE_WRITE_SCHEMA, FILE_EDIT_SCHEMA, FILE_SEARCH_SCHEMA,
                FILE_LIST_SCHEMA, ARCHIVE_LIST_SCHEMA, ARCHIVE_EXTRACT_SCHEMA,
                FILE_COPY_SCHEMA, FILE_MOVE_SCHEMA, FILE_RENAME_SCHEMA, FILE_DELETE_SCHEMA]

    def health(self) -> dict:
        return {
            "status": "ok",
            "version": "0.3.0",
            "tools": list(TOOL_NAMES),
            "max_bytes": self.config.max_bytes,
            "max_write_bytes": self.config.max_write_bytes,
            "roots": list(self.config.roots),
            "allow_any_path": self.config.allow_any_path,
            "allow_write": self.config.allow_write,
        }

    @tool_permission('file_read')
    async def file_read(
        self,
        *,
        path: str,
        encoding: str | None = None,
        max_bytes: int | None = None,
        offset: int = 0,
    ) -> dict:
        import asyncio

        try:
            result = await asyncio.to_thread(
                read_file,
                path,
                encoding=encoding,
                max_bytes=max_bytes,
                offset=offset,
                config=self.config,
            )
            return result_to_dict(result)
        except ReadError as exc:
            return _read_envelope(path=path, offset=offset, error=str(exc))
        except Exception as exc:  # noqa: BLE001 — agent gets a body, not a 500
            log.exception("file_read failed")
            return _read_envelope(
                path=path,
                offset=offset,
                error=f"file_read failed: {exc}",
            )

    @tool_permission('file_write')
    async def file_write(
        self,
        *,
        path: str,
        content: str,
        encoding: str | None = None,
        append: bool = False,
        create_parents: bool = False,
        overwrite: bool = True,
        max_bytes: int | None = None,
    ) -> dict:
        import asyncio

        try:
            result = await asyncio.to_thread(
                write_file,
                path,
                content,
                encoding=encoding,
                append=append,
                create_parents=create_parents,
                overwrite=overwrite,
                max_bytes=max_bytes,
                config=self.config,
            )
            return write_result_to_dict(result)
        except WriteError as exc:
            return _write_envelope(path=path, error=str(exc))
        except Exception as exc:  # noqa: BLE001
            log.exception("file_write failed")
            return _write_envelope(
                path=path,
                error=f"file_write failed: {exc}",
            )


    async def _mutate(self, action: str, **args) -> dict:
        from hirara_core.native import native_call
        from .paths import require_roots, PathError
        if not self.config.allow_write:
            return {"error": "filesystem mutations disabled (CFS_ALLOW_WRITE=false)"}
        try:
            roots = [str(root) for root in require_roots(self.config)]
        except PathError as exc:
            return {"error": str(exc)}
        return await native_call(action, **args, roots=roots,
                                 allow_any_path=self.config.allow_any_path,
                                 allow_write=self.config.allow_write,
                                 max_bytes=self.config.max_write_bytes)

    @tool_permission("file_copy")
    async def file_copy(self, *, path: str, dest: str, overwrite: bool = False) -> dict:
        return await self._mutate("file_copy", path=path, dest=dest, overwrite=overwrite)

    @tool_permission("file_move")
    async def file_move(self, *, path: str, dest: str, overwrite: bool = False) -> dict:
        return await self._mutate("file_move", path=path, dest=dest, overwrite=overwrite)

    @tool_permission("file_rename")
    async def file_rename(self, *, path: str, name: str, overwrite: bool = False) -> dict:
        return await self._mutate("file_rename", path=path, name=name, overwrite=overwrite)

    @tool_permission("file_delete")
    async def file_delete(self, *, path: str) -> dict:
        return await self._mutate("file_delete", path=path)

    async def _run(self, name: str, fn, errors: tuple, envelope: dict, **kwargs) -> dict:
        import asyncio

        try:
            return await asyncio.to_thread(fn, config=self.config, **kwargs)
        except errors as exc:
            return {**envelope, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001 — agent gets a body, not a 500
            log.exception("%s failed", name)
            return {**envelope, "error": f"{name} failed: {exc}"}

    @tool_permission('file_edit')
    async def file_edit(self, *, path: str, old_string: str | None = None,
                        new_string: str | None = None, replace_all: bool = False,
                        edits: list[dict] | None = None, dry_run: bool = False) -> dict:
        return await self._run(
            "file_edit", lambda **kw: edit_file(path, **kw), (EditError,),
            {"path": path, "edits": [], "replacements": 0, "diff": None},
            edits=edits, old_string=old_string, new_string=new_string,
            replace_all=replace_all, dry_run=dry_run)

    @tool_permission('file_search')
    async def file_search(self, *, pattern: str, path: str | None = None,
                          glob: str | None = None, regex: bool = True,
                          case_sensitive: bool = False, context: int = 0,
                          max_results: int = 200, include_hidden: bool = False) -> dict:
        return await self._run(
            "file_search", lambda **kw: search_files(pattern, **kw), (SearchError,),
            {"pattern": pattern, "path": path, "matches": [], "count": 0},
            path=path, glob=glob, regex=regex, case_sensitive=case_sensitive,
            context=context, max_results=max_results, include_hidden=include_hidden)

    @tool_permission('file_list')
    async def file_list(self, *, path: str | None = None, pattern: str | None = None,
                        recursive: bool = False, include_hidden: bool = False,
                        max_entries: int = 500) -> dict:
        return await self._run(
            "file_list", lambda **kw: list_files(path, **kw), (SearchError,),
            {"path": path, "entries": [], "count": 0},
            pattern=pattern, recursive=recursive, include_hidden=include_hidden,
            max_entries=max_entries)

    @tool_permission('archive_list')
    async def archive_list(self, *, path: str, max_entries: int = 1000) -> dict:
        return await self._run(
            "archive_list", lambda **kw: list_archive(path, **kw), (ArchiveError,),
            {"path": path, "entries": [], "count": 0}, max_entries=max_entries)

    @tool_permission('archive_extract')
    async def archive_extract(self, *, path: str, dest: str, members: list[str] | None = None,
                              overwrite: bool = False) -> dict:
        return await self._run(
            "archive_extract", lambda **kw: extract_archive(path, **kw), (ArchiveError,),
            {"path": path, "dest": dest, "extracted": [], "skipped": []},
            dest=dest, members=members, overwrite=overwrite)


__all__ = [
    "ARCHIVE_EXTRACT_SCHEMA",
    "ARCHIVE_LIST_SCHEMA",
    "FILE_EDIT_SCHEMA",
    "FILE_LIST_SCHEMA",
    "FILE_READ_SCHEMA",
    "FILE_SEARCH_SCHEMA",
    "FILE_WRITE_SCHEMA",
    "Toolset",
    "TOOL_NAMES",
    "call_tool",
    "tool_schemas",
]


TOOL_NAMES = (
    "file_copy", "file_move", "file_rename", "file_delete",
    "file_read",
    "file_write",
    "file_edit",
    "file_search",
    "file_list",
    "archive_list",
    "archive_extract",
)
_local_toolset: "Toolset | None" = None


def _backend() -> "Toolset":
    global _local_toolset
    if _local_toolset is None:
        _local_toolset = Toolset.from_env()
    return _local_toolset


async def call_tool(name: str, arguments: dict | None = None) -> dict:
    """Run one tool in-process and return its response envelope."""
    if name not in TOOL_NAMES:
        raise KeyError(f"unknown tool: {name}")
    return await getattr(_backend(), name)(**(arguments or {}))


@visible_schemas
def tool_schemas() -> list[dict]:
    return _backend().schemas()
