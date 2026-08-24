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
