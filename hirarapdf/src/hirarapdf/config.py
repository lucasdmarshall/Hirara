"""Runtime configuration for Hirarapdf.

Everything is overridable by environment variable so the same image can run
locked down on a network-exposed host or wide open on a trusted laptop.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# Page sizes the maker understands, mapped to reportlab names lazily in maker.py
# so importing the config never requires reportlab to be installed.
PAGE_SIZES = ("A4", "LETTER", "LEGAL", "A3", "A5")


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw else default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw else default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    return raw.strip().lower() in {"1", "true", "yes", "on"} if raw else default


@dataclass(frozen=True)
class PdfConfig:
    """Reader + maker knobs.

    Defaults favour a self-hosted agent tool: pure-Python, offline, and safe to
    run on a loopback-bound service. Reading a URL is off until you opt in, and
    when on it goes through hirara-core's SSRF guard rather than a bare GET.
    """

    # --- reading (parser / reader) ---

    # Max size of an input PDF accepted from callers.
    max_bytes: int = 25 * 1024 * 1024

    # Cap on extracted text returned to the agent. Extraction stops once this
    # many characters have been collected and the result is flagged truncated.
    max_chars: int = 200_000

    # Allow fetching a PDF from an http(s) URL. Off by default. When on, the
    # fetch goes through hirara-core's safe_download — resolve-then-pin,
    # every redirect hop re-validated, streamed and size-capped — so enabling
    # it does not open an SSRF hole the way a bare httpx.get would.
    allow_url_fetch: bool = False
    url_timeout: float = 30.0

    # Allow reading or writing a local file the caller names by path. This is
    # the primary use run locally (MCP over stdio, or a loopback HTTP service):
    # "read /home/me/report.pdf". But over a network-exposed HTTP service,
    # pdf_path lets any caller name any file on the box, so set
    # CPDF_ALLOW_LOCAL_PATH=false there and use upload / base64 instead.
    allow_local_path: bool = True

    # --- creating (maker) ---

    # Default page size for pdf_create when the caller does not name one.
    default_page_size: str = "A4"

    # Cap on the length of source content accepted by pdf_create / html_to_pdf.
    max_create_chars: int = 500_000

    # html_to_pdf image map: count and total decoded bytes.
    max_html_images: int = 24
    max_html_image_bytes: int = 8_000_000

    @classmethod
    def from_env(cls) -> "PdfConfig":
        page = os.getenv("CPDF_PAGE_SIZE", cls.default_page_size).strip().upper()
        if page not in PAGE_SIZES:
            page = cls.default_page_size
        return cls(
            max_bytes=_env_int("CPDF_MAX_BYTES", cls.max_bytes),
            max_chars=_env_int("CPDF_MAX_CHARS", cls.max_chars),
            allow_url_fetch=_env_bool("CPDF_ALLOW_URL_FETCH", cls.allow_url_fetch),
            url_timeout=_env_float("CPDF_URL_TIMEOUT", cls.url_timeout),
            allow_local_path=_env_bool("CPDF_ALLOW_LOCAL_PATH", cls.allow_local_path),
            default_page_size=page,
            max_create_chars=_env_int("CPDF_MAX_CREATE_CHARS", cls.max_create_chars),
            max_html_images=_env_int("CPDF_MAX_HTML_IMAGES", cls.max_html_images),
            max_html_image_bytes=_env_int(
                "CPDF_MAX_HTML_IMAGE_BYTES", cls.max_html_image_bytes
            ),
        )
