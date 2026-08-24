"""The tool layer: schema and JSON-ready results.

Tools: ``application_logs`` (``process_list`` / ``environment_read`` later).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .config import OpsConfig
from .logs import LogsError, application_logs as read_logs, result_to_dict

log = logging.getLogger(__name__)


APPLICATION_LOGS_SCHEMA = {
    "name": "application_logs",
    "description": (
        "Read lines from an application log file. Tail by default (from_end), "
        "or head with from_end=false. Filter with pattern (regex) and/or level "
        "(ERROR, WARN, …). Paths are gated by COPS_ROOTS; named sources via "
        "COPS_LOG_SOURCES. Errors stay in the JSON envelope."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Log file path (gated by COPS_ROOTS).",
            },
            "source": {
                "type": "string",
                "description": "Named source from COPS_LOG_SOURCES.",
            },
            "lines": {
                "type": "integer",
                "minimum": 1,
                "description": "Max lines to return (default 100).",
            },
            "from_end": {
                "type": "boolean",
                "description": "Tail (true, default) or head (false).",
            },
            "pattern": {
                "type": "string",
                "description": "Optional regex; only matching lines are returned.",
            },
            "level": {
                "type": "string",
                "enum": ["CRITICAL", "ERROR", "WARN", "INFO", "DEBUG", "TRACE"],
                "description": "Optional level filter (heuristic on line text).",
            },
            "max_bytes": {
                "type": "integer",
                "minimum": 1,
                "description": "Cap on bytes read from the file.",
            },
        },
        "additionalProperties": False,
    },
}


def _envelope(**overrides) -> dict:
    envelope = {
        "source": None,
        "path": None,
        "resolved_path": None,
        "lines": [],
        "line_count": 0,
        "total_lines_scanned": None,
        "from_end": True,
        "pattern": None,
        "level": None,
        "truncated": False,
        "bytes_read": None,
        "file_size": None,
        "error": None,
    }
    envelope.update(overrides)
    return envelope


@dataclass
class Toolset:
    """Ops tools sharing one config."""

    config: OpsConfig

    @classmethod
    def from_env(cls) -> "Toolset":
        return cls(config=OpsConfig.from_env())

    def schemas(self) -> list[dict]:
        return [APPLICATION_LOGS_SCHEMA]

    def health(self) -> dict:
        return {
            "status": "ok",
            "version": "0.1.0",
            "tools": ["application_logs"],
            "sources": sorted(self.config.resolved_sources()),
            "roots": list(self.config.roots),
            "allow_any_path": self.config.allow_any_path,
            "default_lines": self.config.default_lines,
            "max_lines": self.config.max_lines,
        }

    async def application_logs(
        self,
        *,
        path: str | None = None,
        source: str | None = None,
        lines: int | None = None,
        from_end: bool = True,
        pattern: str | None = None,
        level: str | None = None,
        max_bytes: int | None = None,
    ) -> dict:
        import asyncio

        try:
            result = await asyncio.to_thread(
                read_logs,
                path=path,
                source=source,
                lines=lines,
                from_end=from_end,
                pattern=pattern,
                level=level,
                max_bytes=max_bytes,
                config=self.config,
            )
            return result_to_dict(result)
        except LogsError as exc:
            return _envelope(
                path=path, source=source, from_end=from_end, error=str(exc)
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("application_logs failed")
            return _envelope(
                path=path,
                source=source,
                from_end=from_end,
                error=f"application_logs failed: {exc}",
            )


__all__ = [
    "APPLICATION_LOGS_SCHEMA",
    "Toolset",
    "TOOL_NAMES",
    "call_tool",
    "tool_schemas",
]


TOOL_NAMES = ("application_logs",)
_local_toolset: "Toolset | None" = None


def _backend() -> "Toolset":
    global _local_toolset
    if _local_toolset is None:
        _local_toolset = Toolset.from_env()
    return _local_toolset


async def call_tool(name: str, arguments: dict | None = None) -> dict:
    args = arguments or {}
    if name == "application_logs":
        return await _backend().application_logs(**args)
    raise KeyError(f"unknown tool: {name}")


def tool_schemas() -> list[dict]:
    return _backend().schemas()
