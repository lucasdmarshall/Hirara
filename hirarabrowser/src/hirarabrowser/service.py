"""HTTP front end.

    uvicorn hirarabrowser.service:app --host 0.0.0.0 --port 8700
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from pydantic import BaseModel

from .tools import Toolset

log = logging.getLogger("hirarabrowser.service")

_toolset = Toolset.from_env()

app = FastAPI(title="hirarabrowser", version="0.1.0")


class BrowserOpenRequest(BaseModel):
    url: str
    session_id: str | None = None
    timeout: float | None = None
    include_text: bool = False


@app.get("/health")
async def health() -> dict:
    return _toolset.health()


@app.get("/schemas")
async def schemas() -> dict:
    return {"tools": _toolset.schemas()}


@app.post("/browser_open")
async def browser_open(request: BrowserOpenRequest) -> dict:
    return await _toolset.browser_open(
        url=request.url,
        session_id=request.session_id,
        timeout=request.timeout,
        include_text=request.include_text,
    )
