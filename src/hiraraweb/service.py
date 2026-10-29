"""HTTP front end.

    uvicorn hiraraweb.service:app --host 0.0.0.0 --port 8000

Same Toolset as the MCP server, so the two cannot drift apart in behaviour.

Bind this to localhost or keep it behind your own auth. It is an egress
primitive: anyone who can reach it can make your server issue requests, and
while :mod:`hiraraweb.guard` stops those requests reaching your internal
network, an open instance is still someone else's free proxy.
"""

from __future__ import annotations

from hirara_core.policy import install_backend

from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel, Field

from .tools import WEB_FETCH_SCHEMA, WEB_SEARCH_SCHEMA, Toolset

_toolset = Toolset.from_env()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Clear expired rows once at boot; the table is small enough that this
    # is cheaper than carrying a background sweeper.
    await _toolset.cache.purge_expired()
    yield


app = FastAPI(title="hirara-web", version="0.2.0", lifespan=lifespan)

install_backend(app)


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    max_results: int = Field(5, ge=1, le=20)
    allowed_domains: list[str] | None = None
    blocked_domains: list[str] | None = None
    session_id: str | None = None


class FetchRequest(BaseModel):
    url: str = Field(..., min_length=1)
    max_chars: int = Field(50_000, ge=500)
    session_id: str | None = None


class RegisterUrlsRequest(BaseModel):
    """URLs the client vouches for — typically ones the user supplied."""

    session_id: str = Field(..., min_length=1)
    urls: list[str] = Field(..., min_length=1)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": app.version}


@app.get("/schemas")
async def schemas() -> dict:
    """Tool definitions, ready to drop into an Anthropic API tools array."""
    return {"tools": [WEB_SEARCH_SCHEMA, WEB_FETCH_SCHEMA]}


@app.post("/web_search")
async def search(request: SearchRequest) -> dict:
    return await _toolset.search(
        request.query,
        max_results=request.max_results,
        allowed_domains=request.allowed_domains,
        blocked_domains=request.blocked_domains,
        session_id=request.session_id,
    )


@app.post("/web_fetch")
async def fetch(request: FetchRequest) -> dict:
    # Errors come back in the body rather than as HTTP status codes: the
    # caller is an agent loop, and "this URL was blocked" is a result it
    # should reason about, not a transport failure.
    return await _toolset.fetch(
        request.url, max_chars=request.max_chars, session_id=request.session_id
    )


@app.post("/context/urls")
async def register_urls(request: RegisterUrlsRequest) -> dict:
    """Vouch for URLs so they become fetchable in this session.

    This endpoint is the trust boundary. Expose it only to the component that
    owns the conversation — never to the model. Anything that can call this can
    authorize its own fetches, which defeats the whole control.
    """
    added = _toolset.register_urls(request.session_id, request.urls)
    return {"session_id": request.session_id, "registered": added, "error": None}
