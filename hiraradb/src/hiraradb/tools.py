"""The tool layer: schema and JSON-ready results.

Tools: ``database_query``, ``database_schema``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from .config import DbConfig
from .query import QueryError, database_query as run_query
from .query import result_to_dict as query_result_to_dict
from .schema import database_schema as run_schema
from .schema import schema_result_to_dict

log = logging.getLogger(__name__)


DATABASE_QUERY_SCHEMA = {
    "name": "database_query",
    "description": (
        "Run one SQL statement against a configured SQLite database. "
        "Read-only by default (CDB_READONLY). Pass params as a list or object "
        "for placeholders. Results are capped by max_rows. Multiple statements "
        "are rejected. v1 supports sqlite paths / sqlite:/// URLs only."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "sql": {
                "type": "string",
                "description": "Single SQL statement to execute.",
            },
            "params": {
                "description": "Positional list or named object for placeholders.",
                "oneOf": [
                    {"type": "array"},
                    {"type": "object"},
                ],
            },
            "database": {
                "type": "string",
                "description": "Named database from CDB_DATABASES / CDB_PATH (default).",
            },
            "path": {
                "type": "string",
                "description": "Ad-hoc sqlite file path (gated by CDB_ROOTS).",
            },
            "max_rows": {
                "type": "integer",
                "minimum": 1,
                "description": "Cap on returned rows.",
            },
            "readonly": {
                "type": "boolean",
                "description": "Force read-only for this call (cannot disable server policy).",
            },
        },
        "required": ["sql"],
        "additionalProperties": False,
    },
}


DATABASE_SCHEMA_TOOL = {
    "name": "database_schema",
    "description": (
        "Inspect SQLite schema: list tables/views and their columns. "
        "Optional table= filters to one object; include_indexes / "
        "include_foreign_keys / include_sql add detail. Always read-only."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "database": {
                "type": "string",
                "description": "Named database from CDB_DATABASES / CDB_PATH.",
            },
            "path": {
                "type": "string",
                "description": "Ad-hoc sqlite file path (gated by CDB_ROOTS).",
            },
            "table": {
                "type": "string",
                "description": "If set, only return this table or view.",
            },
            "include_views": {
                "type": "boolean",
                "description": "Include views (default true).",
            },
            "include_indexes": {
                "type": "boolean",
                "description": "Include index metadata per table.",
            },
            "include_foreign_keys": {
                "type": "boolean",
                "description": "Include foreign-key metadata per table.",
            },
            "include_sql": {
                "type": "boolean",
                "description": "Include CREATE SQL from sqlite_master.",
            },
            "max_tables": {
                "type": "integer",
                "minimum": 1,
                "description": "Cap on tables/views returned.",
            },
        },
        "additionalProperties": False,
    },
}


def _query_envelope(**overrides) -> dict:
    envelope = {
        "database": None,
        "path": None,
        "sql": None,
        "columns": [],
        "rows": [],
        "row_count": 0,
        "truncated": False,
        "readonly": None,
        "duration_ms": None,
        "error": None,
    }
    envelope.update(overrides)
    return envelope


def _schema_envelope(**overrides) -> dict:
    envelope = {
        "database": None,
        "path": None,
        "tables": [],
        "table_count": 0,
        "truncated": False,
        "duration_ms": None,
        "error": None,
    }
    envelope.update(overrides)
    return envelope


@dataclass
class Toolset:
    """Database tools sharing one config."""

    config: DbConfig

    @classmethod
    def from_env(cls) -> "Toolset":
        return cls(config=DbConfig.from_env())

    def schemas(self) -> list[dict]:
        return [DATABASE_QUERY_SCHEMA, DATABASE_SCHEMA_TOOL]

    def health(self) -> dict:
        dbs = self.config.resolved_databases()
        return {
            "status": "ok",
            "version": "0.1.0",
            "tools": ["database_query", "database_schema"],
            "databases": sorted(dbs),
            "readonly": self.config.readonly,
            "max_rows": self.config.max_rows,
        }

    async def database_query(
        self,
        *,
        sql: str,
        params: list[Any] | dict[str, Any] | None = None,
        database: str | None = None,
        path: str | None = None,
        max_rows: int | None = None,
        readonly: bool | None = None,
    ) -> dict:
        import asyncio

        try:
            result = await asyncio.to_thread(
                run_query,
                sql,
                params=params,
                database=database,
                path=path,
                max_rows=max_rows,
                readonly=readonly,
                config=self.config,
            )
            return query_result_to_dict(result)
        except QueryError as exc:
            return _query_envelope(sql=sql, database=database, error=str(exc))
        except Exception as exc:  # noqa: BLE001
            log.exception("database_query failed")
            return _query_envelope(
                sql=sql,
                database=database,
                error=f"database_query failed: {exc}",
            )

    async def database_schema(
        self,
        *,
        database: str | None = None,
        path: str | None = None,
        table: str | None = None,
        include_views: bool = True,
        include_indexes: bool = False,
        include_foreign_keys: bool = False,
        include_sql: bool = False,
        max_tables: int | None = None,
    ) -> dict:
        import asyncio

        try:
            result = await asyncio.to_thread(
                run_schema,
                database=database,
                path=path,
                table=table,
                include_views=include_views,
                include_indexes=include_indexes,
                include_foreign_keys=include_foreign_keys,
                include_sql=include_sql,
                max_tables=max_tables,
                config=self.config,
            )
            return schema_result_to_dict(result)
        except QueryError as exc:
            return _schema_envelope(database=database, error=str(exc))
        except Exception as exc:  # noqa: BLE001
            log.exception("database_schema failed")
            return _schema_envelope(
                database=database,
                error=f"database_schema failed: {exc}",
            )


__all__ = [
    "DATABASE_QUERY_SCHEMA",
    "DATABASE_SCHEMA_TOOL",
    "Toolset",
    "TOOL_NAMES",
    "call_tool",
    "tool_schemas",
]


TOOL_NAMES = ("database_query", "database_schema")
_local_toolset: "Toolset | None" = None


def _backend() -> "Toolset":
    global _local_toolset
    if _local_toolset is None:
        _local_toolset = Toolset.from_env()
    return _local_toolset


async def call_tool(name: str, arguments: dict | None = None) -> dict:
    args = arguments or {}
    if name == "database_query":
        return await _backend().database_query(**args)
    if name == "database_schema":
        return await _backend().database_schema(**args)
    raise KeyError(f"unknown tool: {name}")


def tool_schemas() -> list[dict]:
    return _backend().schemas()
