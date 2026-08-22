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


class BrowserClickRequest(BaseModel):
    session_id: str
    selector: str
    timeout: float | None = None
    button: str = "left"
    click_count: int = 1


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


@app.post("/browser_click")
async def browser_click(request: BrowserClickRequest) -> dict:
    return await _toolset.browser_click(
        session_id=request.session_id,
        selector=request.selector,
        timeout=request.timeout,
        button=request.button,
        click_count=request.click_count,
    )
