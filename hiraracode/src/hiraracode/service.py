"""HTTP front end.

    uvicorn hiraracode.service:app --host 127.0.0.1 --port 8300

Same Toolset as the MCP server, so the two cannot drift apart in behaviour.

SECURITY: this service drives the Docker daemon, which is root-equivalent on the
host. Treat the service itself as privileged — bind it to loopback and put your
own auth in front. Never expose it to an untrusted network. The *executed code*
is sandboxed; the *service* is not.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from pydantic import BaseModel, Field

from .tools import Toolset

log = logging.getLogger("hiraracode.service")

_toolset = Toolset.from_env()

app = FastAPI(title="hiraracode", version="0.1.0")


class ExecuteRequest(BaseModel):
    """JSON body for execute_code."""

    language: str
    code: str
    stdin: str | None = None
    timeout: float | None = Field(default=None, gt=0)


class JobStartRequest(BaseModel):
    """JSON body for job_start."""

    language: str
    code: str
    stdin: str | None = None
    timeout: float | None = None


class JobStatusRequest(BaseModel):
    """JSON body for job_status."""

    job_id: str | None = None
    stdout_cursor: int = 0
    stderr_cursor: int = 0


class JobStopRequest(BaseModel):
    """JSON body for job_stop."""

    job_id: str


@app.get("/health")
async def health() -> dict:
    return _toolset.health()


@app.get("/schemas")
async def schemas() -> dict:
    """Tool definitions, ready to drop into an LLM `tools` array."""
    return {"tools": _toolset.schemas()}


@app.post("/execute_code")
async def execute_code(request: ExecuteRequest) -> dict:
    # Errors come back in the body rather than as HTTP status codes: the caller
    # is an agent loop, and "language not allowed" or a non-zero exit is a
    # result to reason about, not a transport failure.
    return await _toolset.execute(
        language=request.language,
        code=request.code,
        stdin=request.stdin,
        timeout=request.timeout,
    )


@app.post("/job_start")
async def job_start(request: JobStartRequest) -> dict:
    return await _toolset.job_start(**request.model_dump())


@app.post("/job_status")
async def job_status(request: JobStatusRequest) -> dict:
    return await _toolset.job_status(**request.model_dump())


@app.post("/job_stop")
async def job_stop(request: JobStopRequest) -> dict:
    return await _toolset.job_stop(job_id=request.job_id)
