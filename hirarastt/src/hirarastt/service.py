"""HTTP front end.

    uvicorn hirarastt.service:app --host 0.0.0.0 --port 8100

Same Toolset as the MCP server, so the two cannot drift apart in behaviour.

Bind this to localhost or keep it behind your own auth. Anyone who can reach
it can spend your CPU/GPU on arbitrary audio.
"""

from __future__ import annotations

from hirara_core.policy import install_backend

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, UploadFile
from pydantic import BaseModel, Field

from .tools import TRANSCRIBE_SCHEMA, Toolset

log = logging.getLogger("hirarastt.service")

_toolset = Toolset.from_env()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Eager-load (and, on first ever boot, download) the model here so the
    # first agent call is not paying for a multi-hundred-MB download. This
    # awaits before serving, so the container is not "up" until the model is
    # ready — the weights land in the persistent TN_DOWNLOAD_ROOT volume, so
    # this cost is paid once, not per restart.
    #
    # A failure is logged loudly rather than swallowed: the old silent
    # `except: pass` let the service come up "healthy" and then fail every
    # transcription. We still yield so /health can report the broken engine
    # and the first transcribe returns a real error, but the log makes the
    # cause obvious.
    info = _toolset.engine.info()
    log.info("loading model: %s", info)
    try:
        _toolset.engine.ensure_loaded()
        log.info("model ready: %s", _toolset.engine.info())
    except Exception as exc:  # noqa: BLE001
        log.error(
            "model failed to load (%s: %s) — the service will start but "
            "transcription will error until this is fixed. Try: "
            "docker compose run --rm hirarastt python -m hirarastt.prefetch",
            type(exc).__name__,
            exc,
        )
    yield


app = FastAPI(title="hirarastt", version="0.2.0", lifespan=lifespan)

install_backend(app)


class TranscribeRequest(BaseModel):
    """JSON body for path / URL / base64 transcription."""

    audio_path: str | None = None
    audio_url: str | None = None
    audio_base64: str | None = None
    filename: str | None = None
    language: str | None = None
    task: str = Field("transcribe", pattern="^(transcribe|translate)$")
    timestamps: bool = True
    prompt: str | None = None


@app.get("/health")
async def health() -> dict:
    return _toolset.health()


@app.get("/schemas")
async def schemas() -> dict:
    """Tool definitions, ready to drop into an LLM `tools` array."""
    return {"tools": _toolset.schemas()}


@app.post("/transcribe")
async def transcribe_json(request: TranscribeRequest) -> dict:
    # Errors come back in the body rather than as HTTP status codes: the
    # caller is an agent loop, and "file too large" is a result to reason
    # about, not a transport failure.
    return await _toolset.transcribe(
        audio_path=request.audio_path,
        audio_url=request.audio_url,
        audio_base64=request.audio_base64,
        filename=request.filename,
        language=request.language,
        task=request.task,
        timestamps=request.timestamps,
        prompt=request.prompt,
    )


@app.post("/transcribe/upload")
async def transcribe_upload(
    file: UploadFile = File(...),
    language: str | None = Form(None),
    task: str = Form("transcribe"),
    timestamps: bool = Form(True),
    prompt: str | None = Form(None),
) -> dict:
    """Multipart upload — preferred for large audio from clients/devs."""
    if task not in {"transcribe", "translate"}:
        return {
            "text": None,
            "language": None,
            "language_probability": None,
            "duration": None,
            "segments": [],
            "model": None,
            "backend": None,
            "task": task,
            "source": file.filename,
            "error": "task must be 'transcribe' or 'translate'",
        }
    data = await file.read()
    return await _toolset.transcribe(
        audio_bytes=data,
        filename=file.filename,
        language=language,
        task=task,
        timestamps=timestamps,
        prompt=prompt,
    )
