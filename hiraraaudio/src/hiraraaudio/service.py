"""HTTP front end.

    uvicorn hiraraaudio.service:app --host 0.0.0.0 --port 9300

Same Toolset as the MCP server, so the two cannot drift apart in behaviour.
Every tool is ``POST /<tool>`` with a JSON body; ``POST /upload/<tool>``
takes a multipart file plus the other arguments as a JSON ``arguments`` field.

Bind this to localhost or keep it behind your own auth. With the default
config a caller can read files by path and write output files; set
HA_ALLOW_LOCAL_PATH=false and HA_ALLOW_OUTPUT_PATH=false before exposing it.
"""

from __future__ import annotations

import json
import logging

from fastapi import FastAPI, File, Form, UploadFile
from pydantic import BaseModel, ConfigDict

from .tools import TOOL_NAMES, Toolset

log = logging.getLogger("hiraraaudio.service")

_toolset = Toolset.from_env()

app = FastAPI(title="hiraraaudio", version="0.1.0")


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Source(_Body):
    audio_path: str | None = None
    audio_url: str | None = None
    audio_base64: str | None = None
    filename: str | None = None


class Span(_Body):
    start: float | None = None
    duration: float | None = None


class Output(_Body):
    output_format: str | None = None
    output_path: str | None = None
    return_audio: bool | None = None


class InfoRequest(Source):
    pass


class ProfileRequest(Source, Span):
    max_segments: int | None = None
    silence_db: float | None = None
    long_silence_s: float | None = None


class CheckRequest(Source, Span):
    preset: str | None = None


class FixRequest(Source, Output):
    preset: str | None = None
    target_lufs: float | None = None
    max_true_peak: float | None = None
    remove_dc: bool | None = None
    dehum: str | None = None
    highpass_hz: float | None = None
    denoise: bool | None = None
    sample_rate: int | None = None


class CompareRequest(_Body):
    a_path: str | None = None
    a_url: str | None = None
    a_base64: str | None = None
    b_path: str | None = None
    b_url: str | None = None
    b_base64: str | None = None


class FindRequest(Source):
    clip_path: str | None = None
    clip_url: str | None = None
    clip_base64: str | None = None
    clip_start: float | None = None
    clip_end: float | None = None
    threshold: float | None = None
    max_matches: int | None = None


class FingerprintRequest(_Body):
    audio_paths: list[str] | None = None
    audio_urls: list[str] | None = None


class SplitRequest(Source):
    min_seconds: float | None = None
    max_seconds: float | None = None
    silence_db: float | None = None
    output_dir: str | None = None
    output_format: str | None = None
    return_audio: bool | None = None


class TightenRequest(Source, Output):
    min_pause: float | None = None
    keep_pause: float | None = None
    edges: bool | None = None
    silence_db: float | None = None
    dry_run: bool | None = None


class SpectrogramRequest(Source, Span):
    width: int | None = None
    height: int | None = None
    min_freq: float | None = None
    max_freq: float | None = None
    freq_scale: str | None = None
    dynamic_range: float | None = None
    output_path: str | None = None


class TonesRequest(Source, Span):
    detect: list[str] | None = None


class SpeakRequest(Output):
    text: str | None = None
    voice: str | None = None
    speed: int | None = None
    pitch: int | None = None
    ssml: bool | None = None
    list_voices: bool | None = None
    language: str | None = None


class SonifyRequest(Output):
    values: list[float | None] | None = None
    series: list[dict] | None = None
    duration: float | None = None
    min_freq: float | None = None
    max_freq: float | None = None
    scale: str | None = None
    waveform: str | None = None
    min_value: float | None = None
    max_value: float | None = None


class WatchRequest(_Body):
    action: str
    stream_url: str | None = None
    audio_path: str | None = None
    watch_id: str | None = None
    cursor: int | None = None
    max_events: int | None = None
    dead_air_s: float | None = None
    silence_db: float | None = None
    spike_db: float | None = None
    detect_tones: bool | None = None
    max_seconds: float | None = None
    realtime: bool | None = None


REQUESTS: dict[str, type[_Body]] = {
    "audio_info": InfoRequest,
    "audio_profile": ProfileRequest,
    "audio_check": CheckRequest,
    "audio_fix": FixRequest,
    "audio_compare": CompareRequest,
    "audio_find": FindRequest,
    "audio_fingerprint": FingerprintRequest,
    "audio_split": SplitRequest,
    "audio_tighten": TightenRequest,
    "audio_spectrogram": SpectrogramRequest,
    "audio_tones": TonesRequest,
    "audio_speak": SpeakRequest,
    "audio_sonify": SonifyRequest,
    "audio_watch": WatchRequest,
}
assert set(REQUESTS) == set(TOOL_NAMES)


@app.get("/health")
async def health() -> dict:
    return _toolset.health()


@app.get("/schemas")
async def schemas() -> dict:
    """Tool definitions, ready to drop into an LLM `tools` array."""
    return {"tools": _toolset.schemas()}


def _endpoint(name: str, model: type[_Body]):
    # Errors come back in the body rather than as HTTP status codes: the
    # caller is an agent loop, and "file too large" is a result to reason
    # about, not a transport failure. Unset fields fall back to the tool's
    # own defaults.
    async def endpoint(request):
        return await getattr(_toolset, name)(**request.model_dump(exclude_none=True))

    # Set explicitly: with postponed annotations FastAPI would otherwise see
    # the string "model" and treat the body as a query parameter.
    endpoint.__annotations__ = {"request": model, "return": dict}
    endpoint.__name__ = f"{name}_endpoint"
    return endpoint


for _name, _model in REQUESTS.items():
    app.post(f"/{_name}")(_endpoint(_name, _model))


_UPLOADABLE = {name for name, model in REQUESTS.items() if issubclass(model, Source)}


@app.post("/upload/{tool}")
async def upload(tool: str, file: UploadFile = File(...), arguments: str = Form("{}")) -> dict:
    """Multipart upload for large audio: the file is the tool's audio source."""
    if tool not in _UPLOADABLE:
        return {"error": f"{tool} does not take an uploaded audio file"}
    try:
        args = json.loads(arguments or "{}")
    except json.JSONDecodeError as exc:
        return {"error": f"arguments is not valid JSON: {exc}"}
    if not isinstance(args, dict):
        return {"error": "arguments must be a JSON object"}
    for key in ("audio_path", "audio_url", "audio_base64"):
        args.pop(key, None)
    args["audio_bytes"] = await file.read()
    args.setdefault("filename", file.filename)
    return await getattr(_toolset, tool)(**args)
