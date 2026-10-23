"""Tests for HiraraSTT tool scaffolding (no Whisper weights required)."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from hirarastt.config import TranscribeConfig, WHISPER_MODELS
from hirarastt.engine import EngineError, Transcription, write_temp_audio
from hirarastt.tools import TRANSCRIBE_SCHEMA, Toolset


class FakeEngine:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def info(self) -> dict:
        return {"backend": "fake", "model": "base", "loaded": True}

    def ensure_loaded(self) -> None:
        pass

    async def transcribe(self, audio_path, *, language=None, task="transcribe", timestamps=True, initial_prompt=None):
        self.calls.append(
            {
                "audio_path": str(audio_path),
                "language": language,
                "task": task,
                "timestamps": timestamps,
                "initial_prompt": initial_prompt,
            }
        )
        segments = []
        if timestamps:
            from hirarastt.engine import Segment

            segments = [Segment(id=0, start=0.0, end=1.5, text="hello world")]
        return Transcription(
            text="hello world",
            language=language or "en",
            language_probability=0.99,
            duration=1.5,
            segments=segments,
            model="base",
            backend="fake",
            task=task,
        )


def test_schema_is_agent_ready():
    assert TRANSCRIBE_SCHEMA["name"] == "transcribe"
    props = TRANSCRIBE_SCHEMA["input_schema"]["properties"]
    assert "audio_path" in props
    assert "audio_url" in props
    assert "audio_base64" in props
    assert props["task"]["enum"] == ["transcribe", "translate"]


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("TN_MODEL", "small")
    monkeypatch.setenv("TN_DEVICE", "cuda")
    monkeypatch.setenv("TN_ALLOW_URL_FETCH", "true")
    cfg = TranscribeConfig.from_env()
    assert cfg.model == "small"
    assert cfg.device == "cuda"
    assert cfg.allow_url_fetch is True
    assert "small" in WHISPER_MODELS


@pytest.mark.asyncio
async def test_transcribe_path(tmp_path: Path):
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"RIFF" + b"\x00" * 64)

    toolset = Toolset(config=TranscribeConfig(allow_url_fetch=False))
    fake = FakeEngine()
    toolset.engine = fake

    result = await toolset.transcribe(audio_path=str(audio), language="en")
    assert result["error"] is None
    assert result["text"] == "hello world"
    assert result["source"] == str(audio)
    assert fake.calls[0]["language"] == "en"


@pytest.mark.asyncio
async def test_transcribe_base64():
    toolset = Toolset(config=TranscribeConfig())
    fake = FakeEngine()
    toolset.engine = fake

    payload = base64.b64encode(b"\x00" * 32).decode()
    result = await toolset.transcribe(audio_base64=payload, filename="note.wav")
    assert result["error"] is None
    assert result["text"] == "hello world"
    assert Path(fake.calls[0]["audio_path"]).exists() is False  # temp cleaned up


@pytest.mark.asyncio
async def test_rejects_multiple_sources(tmp_path: Path):
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"x")
    toolset = Toolset(config=TranscribeConfig())
    toolset.engine = FakeEngine()

    result = await toolset.transcribe(
        audio_path=str(audio),
        audio_base64=base64.b64encode(b"x").decode(),
    )
    assert result["error"]
    assert "only one" in result["error"]


@pytest.mark.asyncio
async def test_url_fetch_disabled_by_default():
    toolset = Toolset(config=TranscribeConfig(allow_url_fetch=False))
    toolset.engine = FakeEngine()
    result = await toolset.transcribe(audio_url="https://example.com/a.wav")
    assert result["error"]
    assert "TN_ALLOW_URL_FETCH" in result["error"]


@pytest.mark.asyncio
async def test_max_bytes_enforced(tmp_path: Path):
    audio = tmp_path / "big.wav"
    audio.write_bytes(b"x" * 100)
    toolset = Toolset(config=TranscribeConfig(max_bytes=50))
    toolset.engine = FakeEngine()
    result = await toolset.transcribe(audio_path=str(audio))
    assert result["error"]
    assert "TN_MAX_BYTES" in result["error"]


def test_write_temp_audio_roundtrip(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    path = write_temp_audio(b"abcd", suffix=".wav")
    assert path.read_bytes() == b"abcd"
    path.unlink()


@pytest.mark.asyncio
async def test_url_fetch_routes_through_the_ssrf_guard(monkeypatch):
    """A blocked audio_url comes back as an error envelope, not an exception.

    The block itself is hirara-core's job (and is tested there); here we
    prove hirarastt actually calls it and surfaces the refusal.
    """
    from hirara_core import BlockedURL
    import hirarastt.tools as tools_module

    async def fake_download(url, **kwargs):
        raise BlockedURL("169.254.169.254 is not globally routable")

    monkeypatch.setattr(tools_module, "safe_download", fake_download)

    toolset = Toolset(config=TranscribeConfig(allow_url_fetch=True))
    toolset.engine = FakeEngine()
    result = await toolset.transcribe(audio_url="http://169.254.169.254/a.wav")
    assert result["text"] is None
    assert "blocked" in result["error"]


@pytest.mark.asyncio
async def test_url_fetch_happy_path_uses_downloaded_bytes(monkeypatch):
    from hirara_core import DownloadResult
    import hirarastt.tools as tools_module

    async def fake_download(url, **kwargs):
        return DownloadResult(
            content=b"RIFFfake-wav-bytes",
            final_url=url,
            status=200,
            content_type="audio/wav",
            truncated=False,
            redirects=[],
        )

    monkeypatch.setattr(tools_module, "safe_download", fake_download)

    toolset = Toolset(config=TranscribeConfig(allow_url_fetch=True))
    fake = FakeEngine()
    toolset.engine = fake
    result = await toolset.transcribe(audio_url="https://example.com/clip.wav")
    assert result["error"] is None
    assert result["text"] == "hello world"
    assert len(fake.calls) == 1  # the engine was handed the temp file


@pytest.mark.asyncio
async def test_url_fetch_truncation_is_reported(monkeypatch):
    from hirara_core import DownloadResult
    import hirarastt.tools as tools_module

    async def fake_download(url, **kwargs):
        return DownloadResult(
            content=b"x" * 10,
            final_url=url,
            status=200,
            content_type="audio/wav",
            truncated=True,  # safe_download hit the byte cap mid-stream
            redirects=[],
        )

    monkeypatch.setattr(tools_module, "safe_download", fake_download)

    toolset = Toolset(config=TranscribeConfig(allow_url_fetch=True, max_bytes=10))
    toolset.engine = FakeEngine()
    result = await toolset.transcribe(audio_url="https://example.com/big.wav")
    assert result["error"]
    assert "TN_MAX_BYTES" in result["error"]


@pytest.mark.asyncio
async def test_local_path_can_be_disabled(tmp_path: Path):
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"x" * 10)
    toolset = Toolset(config=TranscribeConfig(allow_local_path=False))
    toolset.engine = FakeEngine()
    result = await toolset.transcribe(audio_path=str(audio))
    assert result["error"]
    assert "TN_ALLOW_LOCAL_PATH" in result["error"]


@pytest.mark.asyncio
async def test_local_path_allowed_by_default(tmp_path: Path):
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"x" * 10)
    toolset = Toolset(config=TranscribeConfig())
    toolset.engine = FakeEngine()
    result = await toolset.transcribe(audio_path=str(audio))
    assert result["error"] is None
    assert result["text"] == "hello world"


@pytest.mark.asyncio
async def test_missing_source_returns_envelope():
    toolset = Toolset(config=TranscribeConfig())
    toolset.engine = FakeEngine()
    result = await toolset.transcribe()
    assert set(result) >= {
        "text",
        "language",
        "segments",
        "model",
        "backend",
        "task",
        "source",
        "error",
    }
    assert result["error"]
    assert result["text"] is None


async def test_local_backend_contract():
    from hirarastt import tools

    assert tools.TOOL_NAMES == ("transcribe",)
    assert [s["name"] for s in tools.tool_schemas()] == ["transcribe"]
    with pytest.raises(KeyError):
        await tools.call_tool("nope", {})
    # A missing source is answered without loading Whisper.
    result = await tools.call_tool("transcribe", {})
    assert result["error"].startswith("provide exactly one of")
