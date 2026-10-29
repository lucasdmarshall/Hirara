"""HTTP front end.

    uvicorn hiraraocr.service:app --host 0.0.0.0 --port 8400

Same Toolset as the MCP server, so the two cannot drift apart in behaviour.

Bind this to localhost or keep it behind your own auth. Anyone who can reach it
can spend your CPU/GPU on arbitrary images, and — if you enable file_path — read
files as this process.
"""

from __future__ import annotations

from hirara_core.policy import install_backend

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, UploadFile
from pydantic import BaseModel, Field

from .tools import Toolset

log = logging.getLogger("hiraraocr.service")

_toolset = Toolset.from_env()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warm the default engine (PaddleOCR downloads its models on first load) so
    # the first request is not paying for it. A failure is logged, not fatal:
    # the service still starts, /health reports the engine, and the first read
    # returns a real error instead of the container failing to boot.
    try:
        _toolset.engine.ensure_loaded()
        log.info("engine ready: %s", _toolset.engine.info())
    except Exception as exc:  # noqa: BLE001
        log.error("engine failed to load: %s — reads will error until fixed", exc)
    yield


app = FastAPI(title="hiraraocr", version="0.3.0", lifespan=lifespan)

install_backend(app)


class OcrRequest(BaseModel):
    """JSON body for path / URL / base64 OCR."""

    file_path: str | None = None
    file_url: str | None = None
    file_base64: str | None = None
    languages: list[str] | None = None
    engine: str | None = None
    preprocess: bool | None = None
    detail: str = Field("markdown", pattern="^(markdown|layout)$")


class FormRequest(BaseModel):
    """JSON body for form/invoice extraction."""

    file_path: str | None = None
    file_url: str | None = None
    file_base64: str | None = None
    languages: list[str] | None = None
    engine: str | None = None
    templates: dict | None = None


@app.get("/health")
async def health() -> dict:
    return _toolset.health()


@app.get("/schemas")
async def schemas() -> dict:
    """Tool definitions, ready to drop into an LLM `tools` array."""
    return {"tools": _toolset.schemas()}


@app.post("/ocr_read")
async def ocr_read(request: OcrRequest) -> dict:
    # Errors come back in the body, not as HTTP status codes: the caller is an
    # agent loop, and "could not decode image" is a result to reason about.
    return await _toolset.read(
        file_path=request.file_path,
        file_url=request.file_url,
        file_base64=request.file_base64,
        languages=request.languages,
        engine=request.engine,
        preprocess=request.preprocess,
        detail=request.detail,
    )


@app.post("/ocr_read/upload")
async def ocr_read_upload(
    file: UploadFile = File(...),
    languages: str | None = Form(None),
    engine: str | None = Form(None),
    preprocess: bool | None = Form(None),
    detail: str = Form("markdown"),
) -> dict:
    """Multipart upload — preferred for large images/PDFs from clients/devs."""
    data = await file.read()
    langs = [s.strip() for s in languages.split(",")] if languages else None
    return await _toolset.read(
        file_bytes=data,
        languages=langs,
        engine=engine,
        preprocess=preprocess,
        detail=detail,
    )


@app.post("/form_extract")
async def form_extract(request: FormRequest) -> dict:
    return await _toolset.extract(
        file_path=request.file_path,
        file_url=request.file_url,
        file_base64=request.file_base64,
        languages=request.languages,
        engine=request.engine,
        templates=request.templates,
    )


@app.post("/form_extract/upload")
async def form_extract_upload(
    file: UploadFile = File(...),
    languages: str | None = Form(None),
    engine: str | None = Form(None),
) -> dict:
    """Multipart upload for form/invoice extraction."""
    data = await file.read()
    langs = [s.strip() for s in languages.split(",")] if languages else None
    return await _toolset.extract(file_bytes=data, languages=langs, engine=engine)
