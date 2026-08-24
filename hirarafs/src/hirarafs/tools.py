"""The tool layer: schema and JSON-ready results.

Both front ends (HTTP service and MCP server) call into here, so the two can
never drift apart in behaviour — only in transport.

Tools: ``file_read``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .config import FsConfig
from .reader import ReadError, file_read as read_file, result_to_dict

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


def _envelope(**overrides) -> dict:
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


@dataclass
class Toolset:
    """Filesystem tools sharing one config."""

    config: FsConfig

    @classmethod
    def from_env(cls) -> "Toolset":
        return cls(config=FsConfig.from_env())

    def schemas(self) -> list[dict]:
        return [FILE_READ_SCHEMA]

    def health(self) -> dict:
        return {
            "status": "ok",
            "version": "0.1.0",
            "tools": ["file_read"],
            "max_bytes": self.config.max_bytes,
            "roots": list(self.config.roots),
            "allow_any_path": self.config.allow_any_path,
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
            return _envelope(path=path, offset=offset, error=str(exc))
        except Exception as exc:  # noqa: BLE001 — agent gets a body, not a 500
            log.exception("file_read failed")
            return _envelope(
                path=path,
                offset=offset,
                error=f"file_read failed: {exc}",
            )


__all__ = [
    "FILE_READ_SCHEMA",
    "Toolset",
    "TOOL_NAMES",
    "call_tool",
    "tool_schemas",
]


TOOL_NAMES = ("file_read",)
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
    raise KeyError(f"unknown tool: {name}")


def tool_schemas() -> list[dict]:
    return _backend().schemas()
