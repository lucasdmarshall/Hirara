"""HTTP front end.

    uvicorn hirarareader.service:app --host 0.0.0.0 --port 8500

Same Toolset as the MCP server, so the two cannot drift apart in behaviour.

Bind this to localhost or keep it behind your own auth. Anyone who can reach it
can spend your CPU on arbitrary documents, and — if you enable file_path — read
files as this process.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, File, Form, UploadFile
from pydantic import BaseModel

from .tools import Toolset

log = logging.getLogger("hirarareader.service")

_toolset = Toolset.from_env()

app = FastAPI(title="hirarareader", version="0.1.0")


class ReadRequest(BaseModel):
    """JSON body for path / URL / base64 reads."""

    file_path: str | None = None
    file_url: str | None = None
    file_base64: str | None = None
    filename: str | None = None


class EmailReadRequest(ReadRequest):
    """JSON body for email_read."""

    read_attachments: bool = True
    include_html: bool = False
    max_messages: int = 50


@app.get("/health")
async def health() -> dict:
    return _toolset.health()


@app.get("/schemas")
async def schemas() -> dict:
    """Tool definition, ready to drop into an LLM `tools` array."""
    return {"tools": _toolset.schemas()}


@app.post("/office_read")
async def office_read(request: ReadRequest) -> dict:
    # Errors come back in the body, not as HTTP status codes: the caller is an
    # agent loop, and "unrecognized document" is a result to reason about.
    return await _toolset.read(
        file_path=request.file_path,
        file_url=request.file_url,
        file_base64=request.file_base64,
        filename=request.filename,
    )


@app.post("/office_read/upload")
async def office_read_upload(file: UploadFile = File(...)) -> dict:
    """Multipart upload — preferred for large documents from clients/devs."""
    data = await file.read()
    return await _toolset.read(file_bytes=data, filename=file.filename)


@app.post("/email_read")
async def email_read(request: EmailReadRequest) -> dict:
    return await _toolset.email_read(**request.model_dump())


@app.post("/email_read/upload")
async def email_read_upload(
    file: UploadFile = File(...),
    read_attachments: bool = Form(True),
    include_html: bool = Form(False),
    max_messages: int = Form(50),
) -> dict:
    """Multipart upload of an .eml / .msg / .mbox file."""
    data = await file.read()
    return await _toolset.email_read(file_bytes=data, filename=file.filename,
                                     read_attachments=read_attachments,
                                     include_html=include_html, max_messages=max_messages)
