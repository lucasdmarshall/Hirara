"""HTTP front end.

    uvicorn hirarapdf.service:app --host 0.0.0.0 --port 8200

Same Toolset as the MCP server, so the two cannot drift apart in behaviour.

Bind this to localhost or keep it behind your own auth. Anyone who can reach it
can spend your CPU turning arbitrary bytes into (and out of) PDFs, and — if you
enable pdf_path / output_path — read and write files as this process.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, File, Form, UploadFile
from pydantic import BaseModel, Field

from .tools import Toolset

log = logging.getLogger("hirarapdf.service")

_toolset = Toolset.from_env()

app = FastAPI(title="hirarapdf", version="0.1.0")


class SourceRequest(BaseModel):
    """JSON body for the read/info tools — one source of PDF bytes."""

    pdf_path: str | None = None
    pdf_url: str | None = None
    pdf_base64: str | None = None
    password: str | None = None
    include_pages: bool = True


class CreateRequest(BaseModel):
    """JSON body for pdf_create."""

    content: str
    format: str = Field("markdown", pattern="^(markdown|text|html)$")
    title: str | None = None
    author: str | None = None
    subject: str | None = None
    page_size: str | None = None
    output_path: str | None = None


@app.get("/health")
async def health() -> dict:
    return _toolset.health()


@app.get("/schemas")
async def schemas() -> dict:
    """Tool definitions, ready to drop into an LLM `tools` array."""
    return {"tools": _toolset.schemas()}


# Errors come back in the body rather than as HTTP status codes: the caller is
# an agent loop, and "PDF too large" is a result to reason about, not a
# transport failure. Every response carries the same keys either way.


@app.post("/pdf_read")
async def pdf_read(request: SourceRequest) -> dict:
    return await _toolset.read(
        pdf_path=request.pdf_path,
        pdf_url=request.pdf_url,
        pdf_base64=request.pdf_base64,
        password=request.password,
        include_pages=request.include_pages,
    )


@app.post("/pdf_read/upload")
async def pdf_read_upload(
    file: UploadFile = File(...),
    password: str | None = Form(None),
    include_pages: bool = Form(True),
) -> dict:
    """Multipart upload — preferred for large PDFs from clients/devs."""
    data = await file.read()
    return await _toolset.read(
        pdf_bytes=data, password=password, include_pages=include_pages
    )


@app.post("/pdf_info")
async def pdf_info(request: SourceRequest) -> dict:
    return await _toolset.info(
        pdf_path=request.pdf_path,
        pdf_url=request.pdf_url,
        pdf_base64=request.pdf_base64,
        password=request.password,
    )


@app.post("/pdf_info/upload")
async def pdf_info_upload(
    file: UploadFile = File(...),
    password: str | None = Form(None),
) -> dict:
    data = await file.read()
    return await _toolset.info(pdf_bytes=data, password=password)


@app.post("/pdf_create")
async def pdf_create(request: CreateRequest) -> dict:
    return _toolset.create(
        content=request.content,
        format=request.format,
        title=request.title,
        author=request.author,
        subject=request.subject,
        page_size=request.page_size,
        output_path=request.output_path,
    )


class HtmlToPdfRequest(BaseModel):
    """JSON body for html_to_pdf."""

    html: str
    css: str | None = None
    images: dict[str, str] | None = None
    title: str | None = None
    author: str | None = None
    subject: str | None = None
    page_size: str | None = None
    output_path: str | None = None


@app.post("/html_to_pdf")
async def html_to_pdf(request: HtmlToPdfRequest) -> dict:
    return _toolset.html_to_pdf(
        html=request.html,
        css=request.css,
        images=request.images,
        title=request.title,
        author=request.author,
        subject=request.subject,
        page_size=request.page_size,
        output_path=request.output_path,
    )
