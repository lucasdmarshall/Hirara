"""HTTP front end.

    uvicorn hiraranet.service:app --host 0.0.0.0 --port 8600

Same Toolset as the MCP server, so the two cannot drift apart in behaviour.

Bind this to localhost or keep it behind your own auth.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from pydantic import BaseModel

from .tools import Toolset

log = logging.getLogger("hiraranet.service")

_toolset = Toolset.from_env()

app = FastAPI(title="hiraranet", version="0.1.0")


class DnsLookupRequest(BaseModel):
    """JSON body for dns_lookup."""

    name: str
    record_types: list[str] | None = None
    nameserver: str | None = None


class PortScanRequest(BaseModel):
    """JSON body for port_scan."""

    host: str
    ports: list[int | str] | str | None = None
    timeout: float | None = None
    concurrency: int | None = None


@app.get("/health")
async def health() -> dict:
    return _toolset.health()


@app.get("/schemas")
async def schemas() -> dict:
    """Tool definitions, ready to drop into an LLM `tools` array."""
    return {"tools": _toolset.schemas()}


@app.post("/dns_lookup")
async def dns_lookup(request: DnsLookupRequest) -> dict:
    # Errors come back in the body, not as HTTP status codes: the caller is an
    # agent loop, and "NXDOMAIN" is a result to reason about.
    return await _toolset.dns_lookup(
        name=request.name,
        record_types=request.record_types,
        nameserver=request.nameserver,
    )


@app.post("/port_scan")
async def port_scan(request: PortScanRequest) -> dict:
    return await _toolset.port_scan(
        host=request.host,
        ports=request.ports,
        timeout=request.timeout,
        concurrency=request.concurrency,
    )
