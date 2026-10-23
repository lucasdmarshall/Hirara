"""The tool layer: schema and JSON-ready results.

Both front ends (HTTP service and MCP server) call into here, so the two can
never drift apart in behaviour — only in transport.

One tool in v1: ``ocr_read`` — an image or scanned PDF in, text + markdown
(and optional layout) out.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass, field

from hirara_core import BlockedURL, DownloadError, safe_download

from .config import ENGINES, OcrConfig
from .engines import EngineError, OcrEngine, build_engine
from .extract import extract_form
from .preprocess import preprocess_image
from .render import OcrPage, blocks_to_text, pages_to_markdown

log = logging.getLogger(__name__)


OCR_READ_SCHEMA = {
    "name": "ocr_read",
    "description": (
        "Read the text out of an image or a scanned PDF (optical character "
        "recognition). Use this when the content you need is inside a picture "
        "or a scan — a photo of a document, a screenshot, a scanned page, a "
        "receipt — and there is no selectable text to extract.\n\n"
        "Provide exactly one source: file_path (local image/PDF), file_url "
        "(http/https, if the server allows URL fetch), or file_base64 (raw "
        "bytes). Images (PNG/JPG/…) and scanned PDFs are both accepted and "
        "auto-detected. Returns clean markdown plus the plain text; pass "
        "detail=layout to also get per-block bounding boxes and confidence.\n\n"
        "Set languages (e.g. [\"en\"], [\"en\",\"fr\"]) when you know them, for "
        "better accuracy. This reads printed/typed text; handwriting and "
        "form-field extraction are a separate, later capability."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Absolute or relative path to a local image or PDF.",
            },
            "file_url": {
                "type": "string",
                "description": "http(s) URL of an image or PDF (server must allow URL fetch).",
            },
            "file_base64": {
                "type": "string",
                "description": "Base64-encoded image or PDF bytes.",
            },
            "languages": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Language hints, e.g. [\"en\"] or [\"en\",\"fr\"].",
            },
            "engine": {
                "type": "string",
                "enum": list(ENGINES),
                "description": "Override the OCR engine for this call.",
            },
            "preprocess": {
                "type": "boolean",
                "description": "Run the deskew/denoise/binarize pipeline (default on).",
            },
            "detail": {
                "type": "string",
                "enum": ["markdown", "layout"],
                "description": "markdown (default) or layout (also return blocks with boxes).",
            },
        },
        "additionalProperties": False,
    },
}


FORM_EXTRACT_SCHEMA = {
    "name": "form_extract",
    "description": (
        "Pull structured data out of a form, invoice, or receipt image/PDF: "
        "labelled fields (total, subtotal, tax, invoice number, date) and a "
        "best-effort line-item table. Use this when you need *values*, not just "
        "the raw text — e.g. 'what is the total on this invoice'.\n\n"
        "Provide one source: file_path, file_url (if enabled), or file_base64. "
        "Runs OCR, then extracts by layout and pattern. Pass templates to add or "
        "override fields for a known document shape, e.g. "
        '{"po_number": ["po #", "purchase order"]}. Returns the fields, the '
        "table rows, and the underlying text.\n\n"
        "This is rule/layout-based extraction (CPU, self-hosted); it is strong "
        "on typical invoices and weaker on unusual layouts."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Local image or PDF path."},
            "file_url": {"type": "string", "description": "http(s) URL (if URL fetch enabled)."},
            "file_base64": {"type": "string", "description": "Base64 image or PDF bytes."},
            "languages": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Language hints, e.g. [\"en\"].",
            },
            "engine": {
                "type": "string",
                "enum": list(ENGINES),
                "description": "OCR engine to read the document with.",
            },
            "templates": {
                "type": "object",
                "description": "Extra/override fields: {name: [anchor phrase, ...]}.",
                "additionalProperties": {"type": "array", "items": {"type": "string"}},
            },
        },
        "additionalProperties": False,
    },
}


def _form_envelope(**overrides) -> dict:
    envelope = {
        "fields": {},
        "table": [],
        "text": None,
        "page_count": None,
        "engine": None,
        "languages": None,
        "source": None,
        "error": None,
    }
    envelope.update(overrides)
    return envelope


def _envelope(**overrides) -> dict:
    envelope = {
        "text": None,
        "markdown": None,
        "pages": [],
        "page_count": None,
        "blocks": None,
        "engine": None,
        "languages": None,
        "truncated": None,
        "source": None,
        "error": None,
    }
    envelope.update(overrides)
    return envelope


@dataclass
class Toolset:
    """OCR tools sharing one engine and config."""

    config: OcrConfig
    engine: OcrEngine = field(init=False)

    def __post_init__(self) -> None:
        self.engine = build_engine(self.config)

    @classmethod
    def from_env(cls) -> "Toolset":
        return cls(config=OcrConfig.from_env())

    def schemas(self) -> list[dict]:
        return [OCR_READ_SCHEMA, FORM_EXTRACT_SCHEMA]

    def health(self) -> dict:
        return {"status": "ok", "version": "0.2.0", "engine": self.engine.info()}

    # --- source resolution ---

    async def _resolve_bytes(
        self,
        *,
        file_path: str | None,
        file_url: str | None,
        file_base64: str | None,
        file_bytes: bytes | None,
    ) -> tuple[bytes, str]:
        provided = sum(
            1 for v in (file_path, file_url, file_base64, file_bytes) if v
        )
        if provided == 0:
            raise EngineError(
                "provide exactly one of file_path, file_url, file_base64, or an upload"
            )
        if provided > 1:
            raise EngineError(
                "provide only one source (file_path, file_url, file_base64, or upload)"
            )

        if file_bytes is not None:
            self._check_size(len(file_bytes))
            return file_bytes, "upload"

        if file_path:
            if not self.config.allow_local_path:
                raise EngineError(
                    "file_path is disabled on this server. It lets a caller name "
                    "any file on the host. Use an upload or file_base64 instead, "
                    "or set COCR_ALLOW_LOCAL_PATH=true if this server is trusted."
                )
            from pathlib import Path

            path = Path(file_path).expanduser()
            if not path.is_file():
                raise EngineError(f"file not found: {path}")
            self._check_size(path.stat().st_size)
            return path.read_bytes(), str(path)

        if file_base64:
            try:
                data = base64.b64decode(file_base64, validate=False)
            except Exception as exc:
                raise EngineError(f"invalid file_base64: {exc}") from exc
            self._check_size(len(data))
            return data, "file_base64"

        assert file_url is not None
        if not self.config.allow_url_fetch:
            raise EngineError(
                "file_url is disabled. Set COCR_ALLOW_URL_FETCH=true on a trusted "
                "network, or upload / file_base64 the file instead."
            )
        try:
            result = await safe_download(
                file_url, max_bytes=self.config.max_bytes, timeout=self.config.url_timeout
            )
        except BlockedURL as exc:
            raise EngineError(f"file_url blocked: {exc}") from exc
        except DownloadError as exc:
            raise EngineError(f"file_url download failed: {exc}") from exc
        if result.truncated:
            raise EngineError(f"file_url exceeds COCR_MAX_BYTES ({self.config.max_bytes} bytes)")
        return result.content, file_url

    def _check_size(self, size: int) -> None:
        if size > self.config.max_bytes:
            raise EngineError(f"file exceeds COCR_MAX_BYTES ({self.config.max_bytes} bytes)")

    # --- decoding: image OR scanned PDF -> page images ---

    def _decode_pages(self, data: bytes) -> list:
        """Return a list of page images (numpy arrays)."""
        import numpy as np

        if data[:1024].lstrip()[:4] == b"%PDF":
            try:
                from pdf2image import convert_from_bytes
            except ImportError as exc:
                raise EngineError(
                    "pdf2image is not installed (needed for scanned PDFs). "
                    "pip install pdf2image and install poppler-utils."
                ) from exc
            try:
                images = convert_from_bytes(
                    data, dpi=self.config.pdf_dpi, last_page=self.config.max_pages
                )
            except Exception as exc:  # noqa: BLE001 — poppler missing or bad PDF
                raise EngineError(f"could not rasterize PDF: {exc}") from exc
            return [np.array(im.convert("RGB")) for im in images]

        try:
            from PIL import Image
            import io

            im = Image.open(io.BytesIO(data)).convert("RGB")
        except Exception as exc:  # noqa: BLE001 — not a decodable image
            raise EngineError(f"could not decode image: {exc}") from exc
        return [np.array(im)]

    # --- the recognize pipeline (blocking; run in a thread) ---

    def _recognize(
        self,
        data: bytes,
        *,
        engine: OcrEngine,
        languages: list[str],
        preprocess: bool,
    ) -> list[OcrPage]:
        page_images = self._decode_pages(data)
        pages: list[OcrPage] = []
        for idx, img in enumerate(page_images, start=1):
            height = int(img.shape[0]) if hasattr(img, "shape") else None
            width = int(img.shape[1]) if hasattr(img, "shape") else None
            prepared = preprocess_image(img) if preprocess else img
            blocks = engine.recognize(prepared, languages=languages)
            pages.append(
                OcrPage(
                    page=idx,
                    text=blocks_to_text(blocks),
                    blocks=blocks,
                    width=width,
                    height=height,
                )
            )
        return pages

    async def read(
        self,
        *,
        file_path: str | None = None,
        file_url: str | None = None,
        file_base64: str | None = None,
        file_bytes: bytes | None = None,
        languages: list[str] | None = None,
        engine: str | None = None,
        preprocess: bool | None = None,
        detail: str = "markdown",
    ) -> dict:
        import asyncio

        source = file_path or file_url or "upload"
        langs = languages or self.config.languages
        do_prep = self.config.preprocess if preprocess is None else bool(preprocess)
        eng = self.engine if not engine or engine == self.config.engine else build_engine(
            self.config, engine
        )
        try:
            data, source = await self._resolve_bytes(
                file_path=file_path,
                file_url=file_url,
                file_base64=file_base64,
                file_bytes=file_bytes,
            )
            pages = await asyncio.to_thread(
                self._recognize, data, engine=eng, languages=langs, preprocess=do_prep
            )

            markdown = pages_to_markdown(pages)
            text = "\n\n".join(p.text for p in pages).strip()
            truncated = False
            if len(text) > self.config.max_chars:
                text = text[: self.config.max_chars]
                truncated = True
            if len(markdown) > self.config.max_chars:
                markdown = markdown[: self.config.max_chars]
                truncated = True

            page_meta = [
                {"page": p.page, "text": p.text, "width": p.width, "height": p.height}
                for p in pages
            ]
            blocks_out = None
            if detail == "layout":
                blocks_out = [
                    {"page": p.page, "blocks": [b.as_dict() for b in p.blocks]}
                    for p in pages
                ]

            return _envelope(
                text=text,
                markdown=markdown,
                pages=page_meta,
                page_count=len(pages),
                blocks=blocks_out,
                engine=eng.info().get("engine"),
                languages=langs,
                truncated=truncated,
                source=source,
                error=None,
            )
        except EngineError as exc:
            return _envelope(error=str(exc), source=source, languages=langs)
        except Exception as exc:  # noqa: BLE001 — agent gets a body, not a 500
            log.exception("ocr_read failed")
            return _envelope(error=f"ocr_read failed: {exc}", source=source, languages=langs)

    async def extract(
        self,
        *,
        file_path: str | None = None,
        file_url: str | None = None,
        file_base64: str | None = None,
        file_bytes: bytes | None = None,
        languages: list[str] | None = None,
        engine: str | None = None,
        templates: dict | None = None,
    ) -> dict:
        import asyncio

        source = file_path or file_url or "upload"
        langs = languages or self.config.languages
        eng = self.engine if not engine or engine == self.config.engine else build_engine(
            self.config, engine
        )
        try:
            data, source = await self._resolve_bytes(
                file_path=file_path,
                file_url=file_url,
                file_base64=file_base64,
                file_bytes=file_bytes,
            )
            # OCR every page, then extract fields per page and merge: a field
            # takes the first page it is found on; tables concatenate.
            pages = await asyncio.to_thread(
                self._recognize, data, engine=eng, languages=langs, preprocess=self.config.preprocess
            )
            merged_fields: dict[str, str | None] = {}
            table: list[list[str]] = []
            for page in pages:
                page_result = extract_form(page.blocks, templates=templates)
                for name, value in page_result["fields"].items():
                    if value and not merged_fields.get(name):
                        merged_fields[name] = value
                    merged_fields.setdefault(name, None)
                table.extend(page_result.get("table", []))

            text = "\n\n".join(p.text for p in pages).strip()
            if len(text) > self.config.max_chars:
                text = text[: self.config.max_chars]

            return _form_envelope(
                fields=merged_fields,
                table=table,
                text=text,
                page_count=len(pages),
                engine=eng.info().get("engine"),
                languages=langs,
                source=source,
                error=None,
            )
        except EngineError as exc:
            return _form_envelope(error=str(exc), source=source, languages=langs)
        except Exception as exc:  # noqa: BLE001
            log.exception("form_extract failed")
            return _form_envelope(error=f"form_extract failed: {exc}", source=source, languages=langs)


__all__ = [
    "FORM_EXTRACT_SCHEMA",
    "OCR_READ_SCHEMA",
    "Toolset",
    "TOOL_NAMES",
    "call_tool",
    "tool_schemas",
]


# --- local backend: in-process dispatch for the hirara SDK -------------------
# Discovered by the hirara SDK through the ``hirara.backends`` entry point and
# called directly (no HTTP hop). Reuses the same Toolset the service and MCP
# server use, so behaviour cannot drift between local and networked calls.
# OCR models load on first use, not here, so discovery stays cheap.
TOOL_NAMES = ("ocr_read", "form_extract")
_local_toolset: "Toolset | None" = None


def _backend() -> "Toolset":
    global _local_toolset
    if _local_toolset is None:
        _local_toolset = Toolset.from_env()
    return _local_toolset


async def call_tool(name: str, arguments: dict | None = None) -> dict:
    """Run one tool in-process and return its response envelope."""
    args = arguments or {}
    if name == "ocr_read":
        return await _backend().read(**args)
    if name == "form_extract":
        return await _backend().extract(**args)
    raise KeyError(f"unknown tool: {name}")


def tool_schemas() -> list[dict]:
    return [OCR_READ_SCHEMA, FORM_EXTRACT_SCHEMA]
