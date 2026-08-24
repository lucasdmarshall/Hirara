"""HTTP front end.

    uvicorn hirarautil.service:app --host 0.0.0.0 --port 9000
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from pydantic import BaseModel

from .tools import Toolset

log = logging.getLogger("hirarautil.service")

_toolset = Toolset.from_env()

app = FastAPI(title="hirarautil", version="0.1.0")


class DecodeRequest(BaseModel):
    """JSON body for decode."""

    input: str
    format: str = "auto"


@app.get("/health")
async def health() -> dict:
    return _toolset.health()


@app.get("/schemas")
async def schemas() -> dict:
    return {"tools": _toolset.schemas()}


@app.post("/decode")
async def decode_endpoint(request: DecodeRequest) -> dict:
    return await _toolset.decode(input=request.input, format=request.format)
