"""The tool layer: schema and JSON-ready results.

Both front ends (HTTP service and MCP server) call into here, so the two can
never drift apart in behaviour — only in transport.

Tools: ``file_read``, ``file_write``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .config import FsConfig
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

    def schemas(self) -> list[dict]:
        return [FILE_READ_SCHEMA, FILE_WRITE_SCHEMA]

    def health(self) -> dict:
        return {
            "status": "ok",
            "version": "0.1.0",
            "tools": ["file_read", "file_write"],
            "max_bytes": self.config.max_bytes,
            "max_write_bytes": self.config.max_write_bytes,
            "roots": list(self.config.roots),
            "allow_any_path": self.config.allow_any_path,
            "allow_write": self.config.allow_write,
        }

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


__all__ = [
    "FILE_READ_SCHEMA",
    "FILE_WRITE_SCHEMA",
    "Toolset",
    "TOOL_NAMES",
    "call_tool",
    "tool_schemas",
]


TOOL_NAMES = ("file_read", "file_write")
_local_toolset: "Toolset | None" = None


def _backend() -> "Toolset":
    global _local_toolset
    if _local_toolset is None:
        _local_toolset = Toolset.from_env()
    return _local_toolset


async def call_tool(name: str, arguments: dict | None = None) -> dict:
    """Run one tool in-process and return its response envelope."""
    args = arguments or {}
    if name == "file_read":
        return await _backend().file_read(**args)
    if name == "file_write":
        return await _backend().file_write(**args)
    raise KeyError(f"unknown tool: {name}")


def tool_schemas() -> list[dict]:
    return _backend().schemas()
