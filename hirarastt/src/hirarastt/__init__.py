"""Free open-source speech-to-text for AI agents — Whisper via HTTP and MCP."""

from .config import TranscribeConfig
from .engine import Segment, Transcription, WhisperEngine
from .tools import TRANSCRIBE_SCHEMA, Toolset

__all__ = [
    "TRANSCRIBE_SCHEMA",
    "Segment",
    "Toolset",
    "TranscribeConfig",
    "Transcription",
    "WhisperEngine",
]

__version__ = "0.2.0"
