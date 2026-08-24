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


class DirectoryEnumBody(BaseModel):
    """JSON body for directory_enum."""

    url: str
    paths: list[str] | str | None = None
    method: str = "HEAD"
    timeout: float | None = None
    concurrency: int | None = None
    include_not_found: bool = False


@app.post("/directory_enum")
async def directory_enum_endpoint(request: DirectoryEnumBody) -> dict:
    return await _toolset.directory_enum(
        url=request.url,
        paths=request.paths,
        method=request.method,
        timeout=request.timeout,
        concurrency=request.concurrency,
        include_not_found=request.include_not_found,
    )


class RequestReplayBody(BaseModel):
    """JSON body for request_replay."""

    id: str
    url: str | None = None
    method: str | None = None
    headers: dict[str, str] | None = None
    body: str | None = None
    merge_headers: bool = True
    timeout: float | None = None
    follow_redirects: bool = True
    max_redirects: int | None = None
    max_bytes: int | None = None


@app.post("/request_replay")
async def request_replay_endpoint(request: RequestReplayBody) -> dict:
    return await _toolset.request_replay(
        id=request.id,
        url=request.url,
        method=request.method,
        headers=request.headers,
        body=request.body,
        merge_headers=request.merge_headers,
        timeout=request.timeout,
        follow_redirects=request.follow_redirects,
        max_redirects=request.max_redirects,
        max_bytes=request.max_bytes,
    )


class ParameterTestBody(BaseModel):
    """JSON body for parameter_test."""

    location: str
    name: str
    values: list[str] | str
    id: str | None = None
    url: str | None = None
    method: str | None = None
    headers: dict[str, str] | None = None
    body: str | None = None
    timeout: float | None = None
    follow_redirects: bool = True
    max_redirects: int | None = None
    max_bytes: int | None = None
    concurrency: int | None = None
    include_body: bool = False
    body_preview_chars: int = 200


@app.post("/parameter_test")
async def parameter_test_endpoint(request: ParameterTestBody) -> dict:
    return await _toolset.parameter_test(
        location=request.location,
        name=request.name,
        values=request.values,
        id=request.id,
        url=request.url,
        method=request.method,
        headers=request.headers,
        body=request.body,
        timeout=request.timeout,
        follow_redirects=request.follow_redirects,
        max_redirects=request.max_redirects,
        max_bytes=request.max_bytes,
        concurrency=request.concurrency,
        include_body=request.include_body,
        body_preview_chars=request.body_preview_chars,
    )


class ResponseCompareBody(BaseModel):
    """JSON body for response_compare."""

    left_id: str | None = None
    right_id: str | None = None
    left_status: int | None = None
    right_status: int | None = None
    left_headers: dict[str, str] | None = None
    right_headers: dict[str, str] | None = None
    left_body: str | None = None
    right_body: str | None = None
    compare_headers: bool = True
    compare_body: bool = True
    ignore_headers: list[str] | str | None = None


@app.post("/response_compare")
async def response_compare_endpoint(request: ResponseCompareBody) -> dict:
    return await _toolset.response_compare(
        left_id=request.left_id,
        right_id=request.right_id,
        left_status=request.left_status,
        right_status=request.right_status,
        left_headers=request.left_headers,
        right_headers=request.right_headers,
        left_body=request.left_body,
        right_body=request.right_body,
        compare_headers=request.compare_headers,
        compare_body=request.compare_body,
        ignore_headers=request.ignore_headers,
    )
