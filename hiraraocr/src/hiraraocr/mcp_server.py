"""MCP front end — agents and IDEs call OCR as a tool.

Run over stdio for Claude Code / Claude Desktop / Cursor::

    python -m hiraraocr.mcp_server

Or over HTTP for a remote client::

    python -m hiraraocr.mcp_server --transport stdio
"""

from __future__ import annotations

from hirara_core.policy import mcp_errors

import argparse

from mcp.server.mcpserver import MCPServer

from .tools import Toolset

server = MCPServer(
    name="hiraraocr",
    version="0.3.0",
    instructions=(
        "Self-hosted OCR, no API keys. Use ocr_read to read the text out of an "
        "image or a scanned PDF; use form_extract to pull structured fields and "
        "line-item tables out of an invoice, receipt, or form. Prefer a local "
        "file_path when the file is on disk; use file_base64 for small files."
    ),
)

_toolset = Toolset.from_env()


@server.tool(
    name="ocr_read",
    description=(
        "Read the text out of an image or a scanned PDF (OCR). Use when the "
        "content is inside a picture or scan and there is no selectable text: a "
        "photo of a document, a screenshot, a scanned page, a receipt. Provide "
        "one source: file_path, file_url (if enabled), or file_base64. Images "
        "and scanned PDFs are auto-detected. Returns markdown plus plain text; "
        "detail=layout also returns per-block boxes and confidence. Set "
        "languages (e.g. [\"en\"]) when known. Reads printed/typed text, not "
        "handwriting."
    ),
)
@mcp_errors
async def ocr_read_tool(
    file_path: str | None = None,
    file_url: str | None = None,
    file_base64: str | None = None,
    languages: list[str] | None = None,
    engine: str | None = None,
    preprocess: bool | None = None,
    detail: str = "markdown",
) -> dict:
    """Read text from an image or scanned PDF.

    Args:
        file_path: Local path to an image or PDF.
        file_url: http(s) URL of an image or PDF (if URL fetch is enabled).
        file_base64: Base64-encoded image or PDF bytes.
        languages: Language hints, e.g. ["en"] or ["en", "fr"].
        engine: Override the OCR engine ("paddleocr" or "tesseract").
        preprocess: Run the deskew/denoise/binarize pipeline (default on).
        detail: "markdown" (default) or "layout" (also return blocks).
    """
    return await _toolset.read(
        file_path=file_path,
        file_url=file_url,
        file_base64=file_base64,
        languages=languages,
        engine=engine,
        preprocess=preprocess,
        detail=detail,
    )


@server.tool(
    name="form_extract",
    description=(
        "Pull structured data out of a form, invoice, or receipt (image or PDF): "
        "labelled fields (total, subtotal, tax, invoice number, date) and a "
        "best-effort line-item table. Use when you need values, not just text — "
        "e.g. 'what is the total on this invoice'. Provide one source: "
        "file_path, file_url (if enabled), or file_base64. Pass templates to add "
        "or override fields for a known layout, e.g. {\"po_number\": [\"po #\"]}."
    ),
)
@mcp_errors
async def form_extract_tool(
    file_path: str | None = None,
    file_url: str | None = None,
    file_base64: str | None = None,
    languages: list[str] | None = None,
    engine: str | None = None,
    templates: dict | None = None,
) -> dict:
    """Extract fields and a line-item table from a form/invoice/receipt.

    Args:
        file_path: Local path to an image or PDF.
        file_url: http(s) URL (if URL fetch is enabled).
        file_base64: Base64-encoded image or PDF bytes.
        languages: Language hints, e.g. ["en"].
        engine: OCR engine to read the document with.
        templates: Extra/override fields, {name: [anchor phrase, ...]}.
    """
    return await _toolset.extract(
        file_path=file_path,
        file_url=file_url,
        file_base64=file_base64,
        languages=languages,
        engine=engine,
        templates=templates,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="HiraraOCR MCP server")
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=["stdio", "sse", "streamable-http"],
        help="MCP transport to serve on (default: stdio).",
    )
    args = parser.parse_args()
    if args.transport != "stdio":
        parser.error("network MCP is disabled; use stdio or the authenticated HTTP hub")
    server.run(transport=args.transport)


if __name__ == "__main__":
    main()
