"""The tool layer: schema and JSON-ready results.

Tools: ``application_logs``, ``process_list``, ``environment_read``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .config import OpsConfig
from .environ import EnvironError, environment_read as read_environ
from .environ import result_to_dict as environ_result_to_dict
from .logs import LogsError, application_logs as read_logs
from .logs import result_to_dict as logs_result_to_dict
from .processes import ProcessError, process_list as list_processes
from .processes import result_to_dict as process_result_to_dict

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


PROCESS_LIST_SCHEMA = {
    "name": "process_list",
    "description": (
        "List running processes from /proc (Linux). Returns pid, name, state, "
        "ppid, uid, user, and cmdline. Filter with pattern (regex on name/"
        "cmdline), user, or a single pid. Capped by max_processes."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Optional regex matched against name and cmdline.",
            },
            "user": {
                "type": "string",
                "description": "Optional username or numeric uid filter.",
            },
            "pid": {
                "type": "integer",
                "minimum": 1,
                "description": "If set, only return this process.",
            },
            "max_processes": {
                "type": "integer",
                "minimum": 1,
                "description": "Cap on processes returned.",
            },
            "include_cmdline": {
                "type": "boolean",
                "description": "Include cmdline (default true).",
            },
        },
        "additionalProperties": False,
    },
}


ENVIRONMENT_READ_SCHEMA = {
    "name": "environment_read",
    "description": (
        "Read environment variables for this process or another pid via "
        "/proc/<pid>/environ. Filter with keys and/or pattern (regex on key "
        "names). Secret-like keys are redacted by default (COPS_REDACT_ENV). "
        "Errors stay in the JSON envelope."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "pid": {
                "type": "integer",
                "minimum": 1,
                "description": "Optional process id; omit to read this process.",
            },
            "keys": {
                "description": (
                    "Optional key filter: list of names, or comma-separated string."
                ),
                "oneOf": [
                    {"type": "string"},
                    {"type": "array", "items": {"type": "string"}},
                ],
            },
            "pattern": {
                "type": "string",
                "description": "Optional regex matched against key names.",
            },
            "include_values": {
                "type": "boolean",
                "description": "Include values (default true); false returns keys only.",
            },
            "redact": {
                "type": "boolean",
                "description": (
                    "Override redaction (default follows COPS_REDACT_ENV)."
                ),
            },
            "max_vars": {
                "type": "integer",
                "minimum": 1,
                "description": "Cap on variables returned.",
            },
        },
        "additionalProperties": False,
    },
}


def _logs_envelope(**overrides) -> dict:
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


def _process_envelope(**overrides) -> dict:
    envelope = {
        "processes": [],
        "process_count": 0,
        "scanned": 0,
        "truncated": False,
        "pattern": None,
        "user": None,
        "error": None,
    }
    envelope.update(overrides)
    return envelope


def _environ_envelope(**overrides) -> dict:
    envelope = {
        "pid": None,
        "source": None,
        "variables": {},
        "keys": [],
        "variable_count": 0,
        "redacted_keys": [],
        "truncated": False,
        "pattern": None,
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
        return [
            APPLICATION_LOGS_SCHEMA,
            PROCESS_LIST_SCHEMA,
            ENVIRONMENT_READ_SCHEMA,
        ]

    def health(self) -> dict:
        return {
            "status": "ok",
            "version": "0.1.0",
            "tools": ["application_logs", "process_list", "environment_read"],
            "sources": sorted(self.config.resolved_sources()),
            "roots": list(self.config.roots),
            "allow_any_path": self.config.allow_any_path,
            "default_lines": self.config.default_lines,
            "max_lines": self.config.max_lines,
            "allow_process_list": self.config.allow_process_list,
            "max_processes": self.config.max_processes,
            "allow_environment_read": self.config.allow_environment_read,
            "redact_env": self.config.redact_env,
            "max_env_vars": self.config.max_env_vars,
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
            return logs_result_to_dict(result)
        except LogsError as exc:
            return _logs_envelope(
                path=path, source=source, from_end=from_end, error=str(exc)
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("application_logs failed")
            return _logs_envelope(
                path=path,
                source=source,
                from_end=from_end,
                error=f"application_logs failed: {exc}",
            )

    async def process_list(
        self,
        *,
        pattern: str | None = None,
        user: str | None = None,
        pid: int | None = None,
        max_processes: int | None = None,
        include_cmdline: bool = True,
    ) -> dict:
        import asyncio

        try:
            result = await asyncio.to_thread(
                list_processes,
                pattern=pattern,
                user=user,
                pid=pid,
                max_processes=max_processes,
                include_cmdline=include_cmdline,
                config=self.config,
            )
            return process_result_to_dict(result)
        except ProcessError as exc:
            return _process_envelope(pattern=pattern, user=user, error=str(exc))
        except Exception as exc:  # noqa: BLE001
            log.exception("process_list failed")
            return _process_envelope(
                pattern=pattern,
                user=user,
                error=f"process_list failed: {exc}",
            )

    async def environment_read(
        self,
        *,
        pid: int | None = None,
        keys: list[str] | str | None = None,
        pattern: str | None = None,
        include_values: bool = True,
        redact: bool | None = None,
        max_vars: int | None = None,
    ) -> dict:
        import asyncio

        try:
            result = await asyncio.to_thread(
                read_environ,
                pid=pid,
                keys=keys,
                pattern=pattern,
                include_values=include_values,
                redact=redact,
                max_vars=max_vars,
                config=self.config,
            )
            return environ_result_to_dict(result)
        except EnvironError as exc:
            return _environ_envelope(pid=pid, pattern=pattern, error=str(exc))
        except Exception as exc:  # noqa: BLE001
            log.exception("environment_read failed")
            return _environ_envelope(
                pid=pid,
                pattern=pattern,
                error=f"environment_read failed: {exc}",
            )


__all__ = [
    "APPLICATION_LOGS_SCHEMA",
    "PROCESS_LIST_SCHEMA",
    "ENVIRONMENT_READ_SCHEMA",
    "Toolset",
    "TOOL_NAMES",
    "call_tool",
    "tool_schemas",
]


TOOL_NAMES = ("application_logs", "process_list", "environment_read")
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
    if name == "process_list":
        return await _backend().process_list(**args)
    if name == "environment_read":
        return await _backend().environment_read(**args)
    raise KeyError(f"unknown tool: {name}")


def tool_schemas() -> list[dict]:
    return _backend().schemas()
