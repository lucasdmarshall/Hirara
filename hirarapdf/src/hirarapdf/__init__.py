"""Hirarapdf — self-hosted PDF read / parse / create tools for AI agents.

No API keys, pure-Python: pypdf reads and parses, reportlab writes. URL fetches
route through hirara-core's SSRF guard.
"""

from .config import PAGE_SIZES, PdfConfig
from .htmlpdf import build_html_pdf
from .maker import MakeError, build_pdf
from .reader import PdfDocument, PdfPage, ReaderError, inspect_pdf, read_pdf
from .tools import (
    HTML_TO_PDF_SCHEMA,
    PDF_CREATE_SCHEMA,
    PDF_INFO_SCHEMA,
    PDF_READ_SCHEMA,
    Toolset,
)

__all__ = [
    "HTML_TO_PDF_SCHEMA",
    "PAGE_SIZES",
    "PDF_CREATE_SCHEMA",
    "PDF_INFO_SCHEMA",
    "PDF_READ_SCHEMA",
    "MakeError",
    "PdfConfig",
    "PdfDocument",
    "PdfPage",
    "ReaderError",
    "Toolset",
    "build_html_pdf",
    "build_pdf",
    "inspect_pdf",
    "read_pdf",
]

__version__ = "0.2.0"
