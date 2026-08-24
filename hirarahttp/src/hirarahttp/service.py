"""HTTP front end.

    uvicorn hirarahttp.service:app --host 0.0.0.0 --port 8800

Same Toolset as the MCP server, so the two cannot drift apart in behaviour.

Bind this to localhost or keep it behind your own auth.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from pydantic import BaseModel

from .tools import Toolset

log = logging.getLogger("hirarahttp.service")

_toolset = Toolset.from_env()

app = FastAPI(title="hirarahttp", version="0.1.0")


class HttpRequestBody(BaseModel):
    """JSON body for http_request."""

    url: str
    method: str = "GET"
    headers: dict[str, str] | None = None
    body: str | None = None
    timeout: float | None = None
    follow_redirects: bool = True
    max_redirects: int | None = None
    max_bytes: int | None = None


class HttpHistoryBody(BaseModel):
    """JSON body for http_history."""

    limit: int = 20
    offset: int = 0
    id: str | None = None
    include_body: bool = False
    clear: bool = False


@app.get("/health")
async def health() -> dict:
    return _toolset.health()


@app.get("/schemas")
async def schemas() -> dict:
    """Tool definitions, ready to drop into an LLM `tools` array."""
    return {"tools": _toolset.schemas()}


@app.post("/http_request")
async def http_request_endpoint(request: HttpRequestBody) -> dict:
    # Errors come back in the body, not as HTTP status codes: the caller is an
    # agent loop, and "404" / "blocked" are results to reason about.
    return await _toolset.http_request(
        url=request.url,
        method=request.method,
        headers=request.headers,
        body=request.body,
        timeout=request.timeout,
        follow_redirects=request.follow_redirects,
        max_redirects=request.max_redirects,
        max_bytes=request.max_bytes,
    )


@app.post("/http_history")
async def http_history_endpoint(request: HttpHistoryBody) -> dict:
    return await _toolset.http_history(
        limit=request.limit,
        offset=request.offset,
        id=request.id,
        include_body=request.include_body,
        clear=request.clear,
    )


class InspectHeadersBody(BaseModel):
    """JSON body for inspect_headers."""

    id: str | None = None
    which: str = "response"
    headers: dict[str, str] | None = None


@app.post("/inspect_headers")
async def inspect_headers_endpoint(request: InspectHeadersBody) -> dict:
    return await _toolset.inspect_headers(
        id=request.id,
        which=request.which,
        headers=request.headers,
    )


class InspectCookiesBody(BaseModel):
    """JSON body for inspect_cookies."""

    id: str | None = None
    which: str = "response"
    headers: dict[str, str] | None = None


@app.post("/inspect_cookies")
async def inspect_cookies_endpoint(request: InspectCookiesBody) -> dict:
    return await _toolset.inspect_cookies(
        id=request.id,
        which=request.which,
        headers=request.headers,
    )


class InspectResponseBody(BaseModel):
    """JSON body for inspect_response."""

    id: str | None = None
    include_body: bool = False
    preview_chars: int = 512
    status: int | None = None
    body: str | None = None
    headers: dict[str, str] | None = None
    body_encoding: str | None = None


@app.post("/inspect_response")
async def inspect_response_endpoint(request: InspectResponseBody) -> dict:
    return await _toolset.inspect_response(
        id=request.id,
        include_body=request.include_body,
        preview_chars=request.preview_chars,
        status=request.status,
        body=request.body,
        headers=request.headers,
        body_encoding=request.body_encoding,
    )
