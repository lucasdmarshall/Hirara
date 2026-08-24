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


class ProcessListRequest(BaseModel):
    """JSON body for process_list."""

    pattern: str | None = None
    user: str | None = None
    pid: int | None = None
    max_processes: int | None = None
    include_cmdline: bool = True


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


@app.post("/process_list")
async def process_list_endpoint(request: ProcessListRequest) -> dict:
    return await _toolset.process_list(
        pattern=request.pattern,
        user=request.user,
        pid=request.pid,
        max_processes=request.max_processes,
        include_cmdline=request.include_cmdline,
    )
