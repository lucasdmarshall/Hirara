"""The tool layer: schemas and JSON-ready results.

Both front ends (HTTP service and MCP server) call into here, so the two can
never drift apart in behaviour — only in transport.
"""

from __future__ import annotations

import base64
import logging
import mimetypes
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from hirara_core import BlockedURL, DownloadError, safe_download

from .config import TranscribeConfig
from .engine import EngineError, WhisperEngine, build_engine, write_temp_audio

log = logging.getLogger(__name__)

# Agent-facing tool definition — drop into an LLM `tools` array as-is.
TRANSCRIBE_SCHEMA = {
    "name": "transcribe",
    "description": (
        "Transcribe speech from an audio or video file into text using "
        "open-source Whisper (no API keys, runs locally).\n\n"
        "Use this when the user provides audio/video and you need the spoken "
        "content as text: meetings, voice notes, interviews, podcasts, "
        "lectures, or any clip you cannot listen to directly.\n\n"
        "Provide exactly one audio source: audio_path (local file), "
        "audio_url (http/https, if the server allows URL fetch), or "
        "audio_base64 (raw bytes). Prefer audio_path or a multipart upload "
        "over base64 when the file is large.\n\n"
        "Set task=translate to get an English translation of non-English "
        "speech. Pass language (ISO-639-1) when you already know it to skip "
        "auto-detection."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "audio_path": {
                "type": "string",
                "description": "Absolute or relative path to a local audio/video file.",
            },
            "audio_url": {
                "type": "string",
                "description": "http(s) URL of an audio/video file (server must allow URL fetch).",
            },
            "audio_base64": {
                "type": "string",
                "description": "Base64-encoded audio/video bytes. Prefer path/upload for large files.",
            },
            "filename": {
                "type": "string",
                "description": "Original filename (helps pick a decoder when using audio_base64).",
            },
            "language": {
                "type": "string",
                "description": "Optional ISO-639-1 language code (e.g. en, es, ja). Omit to auto-detect.",
            },
            "task": {
                "type": "string",
                "enum": ["transcribe", "translate"],
                "description": (
                    "transcribe keeps the source language; translate outputs English."
                ),
            },
            "timestamps": {
                "type": "boolean",
                "description": "Include segment-level start/end timestamps (default true).",
            },
            "prompt": {
                "type": "string",
                "description": "Optional initial prompt to steer spelling, names, or style.",
            },
        },
        "additionalProperties": False,
    },
}


def _envelope(**overrides) -> dict:
    """Every transcribe response carries the same keys."""
    envelope = {
        "text": None,
        "language": None,
        "language_probability": None,
        "duration": None,
        "segments": [],
        "model": None,
        "backend": None,
        "task": "transcribe",
        "source": None,
        "error": None,
    }
    envelope.update(overrides)
    return envelope


def _suffix_for(filename: str | None, content_type: str | None = None) -> str:
    if filename:
        suffix = Path(filename).suffix
        if suffix:
            return suffix.lower()
    if content_type:
        guessed = mimetypes.guess_extension(content_type.split(";")[0].strip())
        if guessed:
            return guessed
    return ".wav"


@dataclass
class Toolset:
    """Composed transcription tools sharing one engine and config."""

    config: TranscribeConfig
    engine: WhisperEngine = field(init=False)

    def __post_init__(self) -> None:
        self.engine = build_engine(self.config)

    @classmethod
    def from_env(cls) -> "Toolset":
        return cls(config=TranscribeConfig.from_env())

    def schemas(self) -> list[dict]:
        return [TRANSCRIBE_SCHEMA]

    def health(self) -> dict:
        info = self.engine.info()
        return {"status": "ok", "version": "0.1.0", "engine": info}

    async def _resolve_to_path(
        self,
        *,
        audio_path: str | None,
        audio_url: str | None,
        audio_base64: str | None,
        filename: str | None,
        audio_bytes: bytes | None = None,
    ) -> tuple[Path, str, bool]:
        """Return (path, source_label, is_temp)."""
        provided = sum(
            1
            for value in (audio_path, audio_url, audio_base64, audio_bytes)
            if value is not None and value != ""
        )
        if provided == 0:
            raise EngineError(
                "provide exactly one of audio_path, audio_url, audio_base64, or uploaded bytes"
            )
        if provided > 1:
            raise EngineError(
                "provide only one audio source (audio_path, audio_url, audio_base64, or upload)"
            )

        if audio_bytes is not None:
            if len(audio_bytes) > self.config.max_bytes:
                raise EngineError(
                    f"audio exceeds TN_MAX_BYTES ({self.config.max_bytes} bytes)"
                )
            path = write_temp_audio(audio_bytes, suffix=_suffix_for(filename))
            return path, filename or path.name, True

        if audio_path:
            if not self.config.allow_local_path:
                raise EngineError(
                    "audio_path is disabled on this server. It lets a caller name "
                    "any file on the host, which is unsafe over a network-exposed "
                    "service. Use a multipart upload or audio_base64 instead, or "
                    "set TN_ALLOW_LOCAL_PATH=true if this server is trusted/local."
                )
            path = Path(audio_path).expanduser()
            if not path.is_file():
                raise EngineError(f"audio file not found: {path}")
            size = path.stat().st_size
            if size > self.config.max_bytes:
                raise EngineError(
                    f"audio exceeds TN_MAX_BYTES ({self.config.max_bytes} bytes)"
                )
            return path, str(path), False

        if audio_base64:
            try:
                data = base64.b64decode(audio_base64, validate=False)
            except Exception as exc:
                raise EngineError(f"invalid audio_base64: {exc}") from exc
            if len(data) > self.config.max_bytes:
                raise EngineError(
                    f"audio exceeds TN_MAX_BYTES ({self.config.max_bytes} bytes)"
                )
            path = write_temp_audio(data, suffix=_suffix_for(filename))
            return path, filename or "audio_base64", True

        assert audio_url is not None
        if not self.config.allow_url_fetch:
            raise EngineError(
                "audio_url is disabled. Set TN_ALLOW_URL_FETCH=true on a "
                "trusted network, or upload/path the file instead."
            )

        # The fetch goes through hirara-core's safe_download rather than a
        # bare httpx.get: it runs the URL and every redirect hop through the
        # SSRF guard (so a public URL that 302s to 169.254.169.254 is rejected
        # at the hop) and streams with a hard byte cap, so max_bytes bounds
        # memory during the download instead of after it.
        try:
            result = await safe_download(
                audio_url,
                max_bytes=self.config.max_bytes,
                timeout=self.config.url_timeout,
            )
        except BlockedURL as exc:
            raise EngineError(f"audio_url blocked: {exc}") from exc
        except DownloadError as exc:
            raise EngineError(f"audio_url download failed: {exc}") from exc

        if result.truncated:
            raise EngineError(
                f"audio_url exceeds TN_MAX_BYTES ({self.config.max_bytes} bytes)"
            )

        parsed = urlparse(audio_url)
        name = filename or os.path.basename(parsed.path) or "remote-audio"
        path = write_temp_audio(result.content, suffix=_suffix_for(name, result.content_type))
        return path, audio_url, True

    async def transcribe(
        self,
        *,
        audio_path: str | None = None,
        audio_url: str | None = None,
        audio_base64: str | None = None,
        filename: str | None = None,
        audio_bytes: bytes | None = None,
        language: str | None = None,
        task: str = "transcribe",
        timestamps: bool = True,
        prompt: str | None = None,
    ) -> dict:
        temp_path: Path | None = None
        try:
            path, source, is_temp = await self._resolve_to_path(
                audio_path=audio_path,
                audio_url=audio_url,
                audio_base64=audio_base64,
                filename=filename,
                audio_bytes=audio_bytes,
            )
            if is_temp:
                temp_path = path
            result = await self.engine.transcribe(
                path,
                language=language,
                task=task,
                timestamps=timestamps,
                initial_prompt=prompt,
            )
            payload = result.as_dict()
            payload["source"] = source
            payload["error"] = None
            return payload
        except EngineError as exc:
            # safe_download's BlockedURL / DownloadError are already re-raised
            # as EngineError inside _resolve_to_path, so this one clause covers
            # bad sources, blocked URLs, and download failures alike.
            return _envelope(error=str(exc), task=task, source=audio_path or audio_url or filename)
        except Exception as exc:  # noqa: BLE001 — agent gets a body, not a 500
            log.exception("transcription failed")
            return _envelope(error=f"transcription failed: {exc}", task=task)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)


__all__ = ["TRANSCRIBE_SCHEMA", "Toolset", "TOOL_NAMES", "call_tool", "tool_schemas"]


# --- local backend: in-process dispatch for the hirara SDK -------------------
# Discovered by the hirara SDK through the ``hirara.backends`` entry point and
# called directly (no HTTP hop). Reuses the same Toolset the service and MCP
# server use, so behaviour cannot drift between local and networked calls.
# The Whisper model loads on first use, not here, so discovery stays cheap.
TOOL_NAMES = ("transcribe",)
_local_toolset: "Toolset | None" = None


def _backend() -> "Toolset":
    global _local_toolset
    if _local_toolset is None:
        _local_toolset = Toolset.from_env()
    return _local_toolset


async def call_tool(name: str, arguments: dict | None = None) -> dict:
    """Run one tool in-process and return its response envelope."""
    if name != "transcribe":
        raise KeyError(f"unknown tool: {name}")
    return await _backend().transcribe(**(arguments or {}))


def tool_schemas() -> list[dict]:
    return [TRANSCRIBE_SCHEMA]
