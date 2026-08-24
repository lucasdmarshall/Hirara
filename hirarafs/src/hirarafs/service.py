"""HTTP front end.

    uvicorn hirarafs.service:app --host 0.0.0.0 --port 8900

Same Toolset as the MCP server, so the two cannot drift apart in behaviour.

Bind this to localhost or keep it behind your own auth. Mount a workspace
volume and set CFS_ROOTS when running in Docker.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from pydantic import BaseModel

from .tools import Toolset

log = logging.getLogger("hirarafs.service")

_toolset = Toolset.from_env()

app = FastAPI(title="hirarafs", version="0.1.0")


class FileReadRequest(BaseModel):
    """JSON body for file_read."""

    path: str
    encoding: str | None = None
    max_bytes: int | None = None
    offset: int = 0


@app.get("/health")
async def health() -> dict:
    return _toolset.health()


@app.get("/schemas")
async def schemas() -> dict:
    """Tool definitions, ready to drop into an LLM `tools` array."""
    return {"tools": _toolset.schemas()}


@app.post("/file_read")
async def file_read_endpoint(request: FileReadRequest) -> dict:
    # Errors come back in the body, not as HTTP status codes: the caller is an
    # agent loop, and "file not found" is a result to reason about.
    return await _toolset.file_read(
        path=request.path,
        encoding=request.encoding,
        max_bytes=request.max_bytes,
        offset=request.offset,
    )
