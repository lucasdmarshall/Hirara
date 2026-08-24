"""Inspect SQLite schema: tables, columns, optional indexes / FKs."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any

from .config import DbConfig
from .query import QueryError, _connect, _pick_database, resolve_db_path


@dataclass
class ColumnInfo:
    name: str
    type: str | None = None
    notnull: bool = False
    pk: int = 0
    default: Any = None


@dataclass
class TableInfo:
    name: str
    type: str  # table | view
    columns: list[ColumnInfo] = field(default_factory=list)
    indexes: list[dict[str, Any]] | None = None
    foreign_keys: list[dict[str, Any]] | None = None
    sql: str | None = None


@dataclass
class SchemaResult:
    database: str | None = None
    path: str | None = None
    tables: list[TableInfo] = field(default_factory=list)
    table_count: int = 0
    truncated: bool = False
    duration_ms: int | None = None
    error: str | None = None


def column_to_dict(col: ColumnInfo) -> dict:
    return {
        "name": col.name,
        "type": col.type,
        "notnull": col.notnull,
        "pk": col.pk,
        "default": col.default,
    }


def table_to_dict(table: TableInfo) -> dict:
    out: dict[str, Any] = {
        "name": table.name,
        "type": table.type,
        "columns": [column_to_dict(c) for c in table.columns],
    }
    if table.indexes is not None:
        out["indexes"] = table.indexes
    if table.foreign_keys is not None:
        out["foreign_keys"] = table.foreign_keys
    if table.sql is not None:
        out["sql"] = table.sql
    return out


def schema_result_to_dict(result: SchemaResult) -> dict:
    return {
        "database": result.database,
        "path": result.path,
        "tables": [table_to_dict(t) for t in result.tables],
        "table_count": result.table_count,
        "truncated": result.truncated,
        "duration_ms": result.duration_ms,
        "error": result.error,
    }


def _list_objects(
    conn: sqlite3.Connection,
    *,
    include_views: bool,
    table: str | None,
    max_tables: int,
) -> tuple[list[tuple[str, str, str | None]], bool]:
    types = ("table", "view") if include_views else ("table",)
    placeholders = ",".join("?" * len(types))
    if table:
        rows = conn.execute(
            f"SELECT name, type, sql FROM sqlite_master "
            f"WHERE type IN ({placeholders}) AND name = ? "
            f"AND name NOT LIKE 'sqlite_%' "
            f"ORDER BY type, name",
            [*types, table],
        ).fetchall()
        return [(r["name"], r["type"], r["sql"]) for r in rows], False

    rows = conn.execute(
        f"SELECT name, type, sql FROM sqlite_master "
        f"WHERE type IN ({placeholders}) AND name NOT LIKE 'sqlite_%' "
        f"ORDER BY type, name",
        list(types),
    ).fetchall()
    items = [(r["name"], r["type"], r["sql"]) for r in rows]
    truncated = len(items) > max_tables
    return items[:max_tables], truncated


def _quote_ident(name: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise QueryError("invalid table name")
    if "\x00" in name:
        raise QueryError(f"invalid table name: {name!r}")
    return '"' + name.replace('"', '""') + '"'


def _columns(conn: sqlite3.Connection, name: str) -> list[ColumnInfo]:
    q = _quote_ident(name)
    rows = conn.execute(f"PRAGMA table_info({q})").fetchall()
    cols: list[ColumnInfo] = []
    for row in rows:
        cols.append(
            ColumnInfo(
                name=row["name"],
                type=(row["type"] or None),
                notnull=bool(row["notnull"]),
                pk=int(row["pk"] or 0),
                default=row["dflt_value"],
            )
        )
    return cols


def _indexes(conn: sqlite3.Connection, name: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for idx in conn.execute(f"PRAGMA index_list({_quote_ident(name)})").fetchall():
        idx_name = idx["name"]
        cols = [
            {"name": c["name"], "seq": c["seqno"]}
            for c in conn.execute(f"PRAGMA index_info({_quote_ident(idx_name)})").fetchall()
        ]
        keys = idx.keys()
        out.append(
            {
                "name": idx_name,
                "unique": bool(idx["unique"]),
                "origin": idx["origin"] if "origin" in keys else None,
                "columns": cols,
            }
        )
    return out


def _foreign_keys(conn: sqlite3.Connection, name: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for fk in conn.execute(f"PRAGMA foreign_key_list({_quote_ident(name)})").fetchall():
        out.append(
            {
                "id": fk["id"],
                "seq": fk["seq"],
                "table": fk["table"],
                "from": fk["from"],
                "to": fk["to"],
                "on_update": fk["on_update"],
                "on_delete": fk["on_delete"],
            }
        )
    return out


def database_schema(
    *,
    database: str | None = None,
    path: str | None = None,
    table: str | None = None,
    include_views: bool = True,
    include_indexes: bool = False,
    include_foreign_keys: bool = False,
    include_sql: bool = False,
    max_tables: int | None = None,
    config: DbConfig | None = None,
) -> SchemaResult:
    """Return tables/views and column metadata for a SQLite database."""
    cfg = config or DbConfig()
    started = time.perf_counter()
    # Schema inspection is always read-only.
    ro = True

    try:
        name, raw_path = _pick_database(database, config=cfg, path_override=path)
        resolved = resolve_db_path(raw_path, config=cfg)
    except QueryError as exc:
        return SchemaResult(
            database=database,
            duration_ms=int((time.perf_counter() - started) * 1000),
            error=str(exc),
        )

    cap = cfg.max_rows if max_tables is None else int(max_tables)
    if cap <= 0:
        return SchemaResult(
            database=name,
            path=resolved,
            duration_ms=int((time.perf_counter() - started) * 1000),
            error="max_tables must be > 0",
        )

    table_filter = (table or "").strip() or None

    try:
        conn = _connect(resolved, readonly=ro, timeout=cfg.timeout)
    except sqlite3.Error as exc:
        return SchemaResult(
            database=name,
            path=resolved,
            duration_ms=int((time.perf_counter() - started) * 1000),
            error=f"connect failed: {exc}",
        )

    try:
        objects, truncated = _list_objects(
            conn,
            include_views=include_views,
            table=table_filter,
            max_tables=cap,
        )
        if table_filter and not objects:
            return SchemaResult(
                database=name,
                path=resolved,
                tables=[],
                table_count=0,
                truncated=False,
                duration_ms=int((time.perf_counter() - started) * 1000),
                error=f"table not found: {table_filter}",
            )

        tables: list[TableInfo] = []
        for obj_name, obj_type, ddl in objects:
            info = TableInfo(
                name=obj_name,
                type=obj_type,
                columns=_columns(conn, obj_name),
            )
            if include_indexes and obj_type == "table":
                info.indexes = _indexes(conn, obj_name)
            if include_foreign_keys and obj_type == "table":
                info.foreign_keys = _foreign_keys(conn, obj_name)
            if include_sql:
                info.sql = ddl
            tables.append(info)

        return SchemaResult(
            database=name,
            path=resolved,
            tables=tables,
            table_count=len(tables),
            truncated=truncated,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    except QueryError as exc:
        return SchemaResult(
            database=name,
            path=resolved,
            duration_ms=int((time.perf_counter() - started) * 1000),
            error=str(exc),
        )
    except sqlite3.Error as exc:
        return SchemaResult(
            database=name,
            path=resolved,
            duration_ms=int((time.perf_counter() - started) * 1000),
            error=f"schema failed: {exc}",
        )
    finally:
        conn.close()


__all__ = [
    "ColumnInfo",
    "SchemaResult",
    "TableInfo",
    "database_schema",
    "schema_result_to_dict",
]
