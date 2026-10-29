"""HTTP front end.

    uvicorn hiraramedia.service:app --host 0.0.0.0 --port 9500

Same Toolset as the MCP server, so the two cannot drift apart in behaviour.
Bind to localhost or put your own auth in front; turn off HM_ALLOW_LOCAL_PATH
and HM_ALLOW_OUTPUT_PATH before exposing it to a network.
"""

from __future__ import annotations

from hirara_core.policy import install_backend

from fastapi import FastAPI, File, Form, UploadFile
from pydantic import BaseModel, ConfigDict

from .tools import Toolset

_toolset = Toolset.from_env()

app = FastAPI(title="hiraramedia", version="0.2.0")

install_backend(app)


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VideoRequest(_Body):
    file_path: str | None = None
    file_url: str | None = None
    file_base64: str | None = None
    filename: str | None = None
    max_keyframes: int = 12
    frame_width: int = 480
    scene_threshold: float = 0.3
    include_audio: bool = True
    include_frames: bool = False
    output_dir: str | None = None


class CompareRequest(_Body):
    a_path: str | None = None
    a_url: str | None = None
    a_base64: str | None = None
    b_path: str | None = None
    b_url: str | None = None
    b_base64: str | None = None
    threshold: float = 0.1
    min_region: int = 16
    ignore: list[list[int]] | None = None
    resize: bool = True
    include_diff_image: bool = True
    output_path: str | None = None


class BarcodeRequest(_Body):
    file_path: str | None = None
    file_url: str | None = None
    file_base64: str | None = None
    filename: str | None = None


class QrRequest(_Body):
    data: str
    error_correction: str = "M"
    scale: int = 8
    border: int = 4
    format: str = "png"
    dark: str = "#000000"
    light: str = "#ffffff"
    output_path: str | None = None


def _clean(model: BaseModel) -> dict:
    return {k: v for k, v in model.model_dump().items() if v is not None}


@app.get("/health")
async def health() -> dict:
    return _toolset.health()


@app.get("/schemas")
async def schemas() -> dict:
    return {"tools": _toolset.schemas()}


@app.post("/video_profile")
async def video_profile(request: VideoRequest) -> dict:
    return await _toolset.video_profile(**_clean(request))


@app.post("/video_profile/upload")
async def video_profile_upload(file: UploadFile = File(...), max_keyframes: int = Form(12),
                               include_audio: bool = Form(True)) -> dict:
    data = await file.read()
    return await _toolset.video_profile(file_bytes=data, filename=file.filename,
                                        max_keyframes=max_keyframes, include_audio=include_audio)


@app.post("/image_compare")
async def image_compare(request: CompareRequest) -> dict:
    return await _toolset.image_compare(**_clean(request))


@app.post("/barcode_read")
async def barcode_read(request: BarcodeRequest) -> dict:
    return await _toolset.barcode_read(**_clean(request))


@app.post("/barcode_read/upload")
async def barcode_read_upload(file: UploadFile = File(...)) -> dict:
    return await _toolset.barcode_read(file_bytes=await file.read(), filename=file.filename)


@app.post("/qr_generate")
async def qr_generate(request: QrRequest) -> dict:
    return await _toolset.qr_generate(**_clean(request))
