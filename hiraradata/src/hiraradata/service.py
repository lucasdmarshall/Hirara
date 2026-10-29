"""HTTP front end.

    uvicorn hiraradata.service:app --host 0.0.0.0 --port 9400

Same Toolset as the MCP server, so the two cannot drift apart in behaviour.
Bind to localhost or put your own auth in front; turn off HD_ALLOW_LOCAL_PATH
and HD_ALLOW_OUTPUT_PATH before exposing it to a network.
"""

from __future__ import annotations

from hirara_core.policy import install_backend

from typing import Any

from fastapi import FastAPI, File, Form, UploadFile
from pydantic import BaseModel, ConfigDict

from .tools import Toolset

_toolset = Toolset.from_env()

app = FastAPI(title="hiraradata", version="0.2.0")

install_backend(app)


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProfileRequest(_Body):
    file_path: str | None = None
    file_url: str | None = None
    file_base64: str | None = None
    filename: str | None = None
    data: Any = None
    format: str | None = None
    sheet: str | None = None
    delimiter: str | None = None
    has_header: bool | None = None
    max_rows: int | None = None
    sample_rows: int = 5


class ChartRequest(_Body):
    type: str
    x: list | None = None
    series: list[dict] | None = None
    records: list[dict] | None = None
    x_field: str | None = None
    y_fields: list[str] | None = None
    title: str | None = None
    x_label: str | None = None
    y_label: str | None = None
    width: int = 900
    height: int = 500
    format: str = "png"
    stacked: bool = False
    log_y: bool = False
    legend: bool | None = None
    bins: int = 20
    output_path: str | None = None


class DiagramRequest(_Body):
    source: str
    language: str = "auto"
    format: str = "png"
    engine: str = "dot"
    output_path: str | None = None


@app.get("/health")
async def health() -> dict:
    return _toolset.health()


@app.get("/schemas")
async def schemas() -> dict:
    return {"tools": _toolset.schemas()}


@app.post("/data_profile")
async def data_profile(request: ProfileRequest) -> dict:
    # Errors come back in the body: the caller is an agent loop.
    return await _toolset.data_profile(**request.model_dump())


@app.post("/data_profile/upload")
async def data_profile_upload(file: UploadFile = File(...), format: str | None = Form(None),
                              sheet: str | None = Form(None),
                              max_rows: int | None = Form(None)) -> dict:
    data = await file.read()
    return await _toolset.data_profile(file_bytes=data, filename=file.filename, format=format,
                                       sheet=sheet, max_rows=max_rows)


@app.post("/chart_render")
async def chart_render(request: ChartRequest) -> dict:
    return await _toolset.chart_render(**request.model_dump())


@app.post("/diagram_render")
async def diagram_render(request: DiagramRequest) -> dict:
    return await _toolset.diagram_render(**request.model_dump())
