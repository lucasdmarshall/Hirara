"""HTTP front end.

    uvicorn hiraraops.service:app --host 0.0.0.0 --port 9200
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from pydantic import BaseModel

from .tools import Toolset

log = logging.getLogger("hiraraops.service")

_toolset = Toolset.from_env()

app = FastAPI(title="hiraraops", version="0.1.0")


class ApplicationLogsRequest(BaseModel):
    """JSON body for application_logs."""

    path: str | None = None
    source: str | None = None
    lines: int | None = None
    from_end: bool = True
    pattern: str | None = None
    level: str | None = None
    max_bytes: int | None = None


@app.get("/health")
async def health() -> dict:
    return _toolset.health()


@app.get("/schemas")
async def schemas() -> dict:
    return {"tools": _toolset.schemas()}


@app.post("/application_logs")
async def application_logs_endpoint(request: ApplicationLogsRequest) -> dict:
    return await _toolset.application_logs(
        path=request.path,
        source=request.source,
        lines=request.lines,
        from_end=request.from_end,
        pattern=request.pattern,
        level=request.level,
        max_bytes=request.max_bytes,
    )
