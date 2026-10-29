"""HiraraReader — self-hosted Office-document reader for AI agents. No API keys.

One tool, office_read, reads Word (.docx), PowerPoint (.pptx), and Excel (.xlsx)
files into clean markdown + plain text. URL fetches route through hirara-core's
SSRF guard.
"""

from .config import KINDS, ReaderConfig
from .readers import Document, ReaderError, detect_kind, read_office
from .tools import OFFICE_READ_SCHEMA, Toolset

__all__ = [
    "KINDS",
    "OFFICE_READ_SCHEMA",
    "Document",
    "ReaderConfig",
    "ReaderError",
    "Toolset",
    "detect_kind",
    "read_office",
]

__version__ = "0.2.0"
