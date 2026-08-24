"""Run a SQL query against a configured SQLite database."""

from __future__ import annotations

import base64
import re
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import date, datetime, time as dt_time
from decimal import Decimal
from pathlib import Path
from typing import Any

from .config import DbConfig

_WRITE_START = re.compile(
    r"^\s*(INSERT|UPDATE|DELETE|REPLACE|DROP|ALTER|CREATE|TRUNCATE|"
    r"ATTACH|DETACH|VACUUM|REINDEX|ANALYZE|PRAGMA)\b",
    re.IGNORECASE,
)
_MULTI_STMT = re.compile(r";\s*\S")


class QueryError(ValueError):
    """Caller-facing database_query validation / access failure."""


@dataclass
class QueryResult:
    database: str | None = None
    path: str | None = None
    sql: str | None = None
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    readonly: bool | None = None
    duration_ms: int | None = None
    error: str | None = None


def result_to_dict(result: QueryResult) -> dict:
    return {
        "database": result.database,
        "path": result.path,
        "sql": result.sql,
        "columns": list(result.columns),
        "rows": result.rows,
        "row_count": result.row_count,
        "truncated": result.truncated,
        "readonly": result.readonly,
        "duration_ms": result.duration_ms,
        "error": result.error,
    }


def _parse_roots(config: DbConfig) -> list[Path]:
    roots: list[Path] = []
    for item in config.roots:
        cleaned = (item or "").strip()
        if not cleaned:
            continue
        roots.append(Path(cleaned).expanduser().resolve())
    return roots


def _under_root(resolved: Path, roots: list[Path]) -> bool:
    for root in roots:
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _normalize_sqlite_path(raw: str) -> str:
    cleaned = (raw or "").strip()
    if not cleaned:
        raise QueryError("database path is empty")
    if cleaned == ":memory:":
        return ":memory:"
    if cleaned.startswith("sqlite:///"):
        # sqlite:///relative or sqlite:////absolute
        rest = cleaned[len("sqlite:///") :]
        if rest.startswith("/"):
            return "/" + rest.lstrip("/")
        return rest
    if cleaned.startswith("sqlite://"):
        raise QueryError(
            "unsupported sqlite URL form; use sqlite:///path or a filesystem path"
        )
    if "://" in cleaned:
        scheme = cleaned.split("://", 1)[0].lower()
        raise QueryError(
            f"unsupported database scheme: {scheme!r} "
            "(v1 supports sqlite paths / sqlite:/// URLs only)"
        )
    return cleaned


def resolve_db_path(raw: str, *, config: DbConfig) -> str:
    """Resolve and gate a sqlite path. Returns path or ``:memory:``."""
    path_str = _normalize_sqlite_path(raw)
    if path_str == ":memory:":
        return path_str

    roots = _parse_roots(config)
    if not roots and not config.allow_any_path:
        raise QueryError(
            "no filesystem roots configured (set CDB_ROOTS or CDB_ALLOW_ANY_PATH)"
        )

    candidate = Path(path_str).expanduser()
    # For read-only opens the file must exist; for write we still resolve parent.
    if candidate.exists():
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise QueryError(f"cannot resolve database path: {exc}") from exc
        if not resolved.is_file():
            raise QueryError(f"database path is not a file: {resolved}")
        if roots and not _under_root(resolved, roots):
            raise QueryError(f"database path is outside allowed roots: {resolved}")
        return str(resolved)

    # New DB only allowed when not readonly.
    if config.readonly:
        raise QueryError(f"database file not found: {candidate}")

    parent = candidate.parent
    if not parent.exists():
        raise QueryError(f"parent directory does not exist: {parent}")
    try:
        parent_resolved = parent.resolve(strict=True)
    except OSError as exc:
        raise QueryError(f"cannot resolve parent: {exc}") from exc
    target = (parent_resolved / candidate.name).resolve(strict=False)
    if roots and not _under_root(target, roots):
        raise QueryError(f"database path is outside allowed roots: {target}")
    return str(target)


def _pick_database(
    database: str | None,
    *,
    config: DbConfig,
    path_override: str | None,
) -> tuple[str, str]:
    if path_override:
        name = (database or "adhoc").strip() or "adhoc"
        return name, path_override

    dbs = config.resolved_databases()
    name = (database or "default").strip() or "default"
    if name not in dbs:
        if not dbs:
            raise QueryError(
                "no databases configured (set CDB_PATH / CDB_DATABASES, "
                "or pass path=)"
            )
        raise QueryError(
            f"unknown database: {name!r} (configured: {', '.join(sorted(dbs))})"
        )
    return name, dbs[name]


def _validate_sql(sql: str, *, readonly: bool, max_chars: int) -> str:
    cleaned = (sql or "").strip()
    if not cleaned:
        raise QueryError("sql is required")
    if len(cleaned) > max_chars:
        raise QueryError(f"sql exceeds max_sql_chars ({len(cleaned)} > {max_chars})")
    if _MULTI_STMT.search(cleaned):
        raise QueryError("multiple SQL statements are not allowed")
    # Strip a single trailing semicolon for execution.
    body = cleaned.rstrip().rstrip(";").strip()
    if not body:
        raise QueryError("sql is required")
    if readonly and _WRITE_START.match(body):
        raise QueryError(
            "write/DDL statements are blocked while readonly=true "
            f"(starts with {_WRITE_START.match(body).group(1)})"
        )
    return body


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {
            "__type__": "bytes",
            "base64": base64.b64encode(bytes(value)).decode("ascii"),
        }
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dt_time):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def _connect(path: str, *, readonly: bool, timeout: float) -> sqlite3.Connection:
    if path == ":memory:":
        if readonly:
            # Memory DB in RO is useless for queries without prior setup in-process;
            # still open normally — caller owns the lifecycle in tests via path=.
            conn = sqlite3.connect(":memory:", timeout=timeout)
        else:
            conn = sqlite3.connect(":memory:", timeout=timeout)
    elif readonly:
        uri = Path(path).as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=timeout)
    else:
        conn = sqlite3.connect(path, timeout=timeout)
    conn.row_factory = sqlite3.Row
    if readonly:
        try:
            conn.execute("PRAGMA query_only = ON")
        except sqlite3.Error:
            pass
    return conn


def database_query(
    sql: str,
    *,
    params: list[Any] | dict[str, Any] | None = None,
    database: str | None = None,
    path: str | None = None,
    max_rows: int | None = None,
    readonly: bool | None = None,
    config: DbConfig | None = None,
) -> QueryResult:
    """Execute one SQL statement and return rows as JSON-ready lists."""
    cfg = config or DbConfig()
    started = time.perf_counter()
    ro = cfg.readonly if readonly is None else bool(readonly)
    # Cannot escalate above server policy.
    if cfg.readonly:
        ro = True

    try:
        body = _validate_sql(sql, readonly=ro, max_chars=cfg.max_sql_chars)
        name, raw_path = _pick_database(database, config=cfg, path_override=path)
        resolved = resolve_db_path(raw_path, config=cfg)
    except QueryError as exc:
        return QueryResult(
            database=database,
            sql=(sql or "")[:200] or None,
            readonly=ro,
            duration_ms=int((time.perf_counter() - started) * 1000),
            error=str(exc),
        )

    limit = cfg.max_rows if max_rows is None else int(max_rows)
    if limit <= 0:
        return QueryResult(
            database=name,
            path=resolved,
            sql=body,
            readonly=ro,
            duration_ms=int((time.perf_counter() - started) * 1000),
            error="max_rows must be > 0",
        )

    bind: list[Any] | dict[str, Any] = params if params is not None else []
    if not isinstance(bind, (list, tuple, dict)):
        return QueryResult(
            database=name,
            path=resolved,
            sql=body,
            readonly=ro,
            duration_ms=int((time.perf_counter() - started) * 1000),
            error="params must be a list or object",
        )

    try:
        conn = _connect(resolved, readonly=ro, timeout=cfg.timeout)
    except sqlite3.Error as exc:
        return QueryResult(
            database=name,
            path=resolved,
            sql=body,
            readonly=ro,
            duration_ms=int((time.perf_counter() - started) * 1000),
            error=f"connect failed: {exc}",
        )

    try:
        cur = conn.execute(body, bind)
        if cur.description is None:
            # Non-row-returning statement (only possible when not readonly).
            conn.commit()
            return QueryResult(
                database=name,
                path=resolved,
                sql=body,
                columns=[],
                rows=[],
                row_count=cur.rowcount if cur.rowcount is not None and cur.rowcount >= 0 else 0,
                truncated=False,
                readonly=ro,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )

        columns = [col[0] for col in cur.description]
        fetched = cur.fetchmany(limit + 1)
        truncated = len(fetched) > limit
        rows_raw = fetched[:limit]
        rows = [[_jsonable(row[i]) for i in range(len(columns))] for row in rows_raw]
        return QueryResult(
            database=name,
            path=resolved,
            sql=body,
            columns=columns,
            rows=rows,
            row_count=len(rows),
            truncated=truncated,
            readonly=ro,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    except sqlite3.Error as exc:
        return QueryResult(
            database=name,
            path=resolved,
            sql=body,
            readonly=ro,
            duration_ms=int((time.perf_counter() - started) * 1000),
            error=f"query failed: {exc}",
        )
    finally:
        conn.close()


__all__ = [
    "QueryError",
    "QueryResult",
    "database_query",
    "resolve_db_path",
    "result_to_dict",
]
