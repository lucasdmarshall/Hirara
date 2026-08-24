"""HTTP front end.

    uvicorn hiraradb.service:app --host 0.0.0.0 --port 9100
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from .tools import Toolset

log = logging.getLogger("hiraradb.service")

_toolset = Toolset.from_env()

app = FastAPI(title="hiraradb", version="0.1.0")


class DatabaseQueryRequest(BaseModel):
    """JSON body for database_query."""

    sql: str
    params: list[Any] | dict[str, Any] | None = None
    database: str | None = None
    path: str | None = None
    max_rows: int | None = None
    readonly: bool | None = None


class DatabaseSchemaRequest(BaseModel):
    """JSON body for database_schema."""

    database: str | None = None
    path: str | None = None
    table: str | None = None
    include_views: bool = True
    include_indexes: bool = False
    include_foreign_keys: bool = False
    include_sql: bool = False
    max_tables: int | None = None


@app.get("/health")
async def health() -> dict:
    return _toolset.health()


@app.get("/schemas")
async def schemas() -> dict:
    return {"tools": _toolset.schemas()}


@app.post("/database_query")
async def database_query_endpoint(request: DatabaseQueryRequest) -> dict:
    return await _toolset.database_query(
        sql=request.sql,
        params=request.params,
        database=request.database,
        path=request.path,
        max_rows=request.max_rows,
        readonly=request.readonly,
    )


@app.post("/database_schema")
async def database_schema_endpoint(request: DatabaseSchemaRequest) -> dict:
    return await _toolset.database_schema(
        database=request.database,
        path=request.path,
        table=request.table,
        include_views=request.include_views,
        include_indexes=request.include_indexes,
        include_foreign_keys=request.include_foreign_keys,
        include_sql=request.include_sql,
        max_tables=request.max_tables,
    )
