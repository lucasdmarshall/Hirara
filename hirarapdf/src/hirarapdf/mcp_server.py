"""MCP front end — agents and IDEs call the PDF tools directly.

Run over stdio for Claude Code / Claude Desktop / Cursor::

    python -m hirarapdf.mcp_server

Or over HTTP for a remote client::

    python -m hirarapdf.mcp_server --transport streamable-http
"""

from __future__ import annotations

import argparse

from mcp.server.mcpserver import MCPServer

from .tools import Toolset

server = MCPServer(
    name="hirarapdf",
    version="0.1.0",
    instructions=(
        "Self-hosted PDF tools, no API keys. pdf_read extracts a PDF's text; "
        "pdf_info inspects its structure (pages, metadata, outline, form "
        "fields); pdf_create builds a PDF from Markdown, plain text, or HTML; "
        "html_to_pdf renders HTML and CSS (with embedded images) for designed "
        "documents such as resumes. Prefer a local pdf_path when the file is "
        "already on disk; use pdf_base64 only for small files."
    ),
)

_toolset = Toolset.from_env()


@server.tool(
    name="pdf_read",
    description=(
        "Extract the text and metadata of a PDF so you can read a document you "
        "cannot open directly: reports, papers, invoices, contracts, ebooks. "
        "Provide one source: pdf_path (local file), pdf_url (http/https, if "
        "enabled), or pdf_base64. Returns full text, per-page text, page count "
        "and metadata. Reads the embedded text layer; it does not OCR images, "
        "so a scanned PDF with no text layer returns little or no text."
    ),
)
async def pdf_read_tool(
    pdf_path: str | None = None,
    pdf_url: str | None = None,
    pdf_base64: str | None = None,
    password: str | None = None,
    include_pages: bool = True,
) -> dict:
    """Extract text and metadata from a PDF.

    Args:
        pdf_path: Local path to a PDF file.
        pdf_url: http(s) URL of a PDF (if URL fetch is enabled).
        pdf_base64: Base64-encoded PDF bytes (small files only).
        password: Password for an encrypted PDF.
        include_pages: Include per-page text array.
    """
    return await _toolset.read(
        pdf_path=pdf_path,
        pdf_url=pdf_url,
        pdf_base64=pdf_base64,
        password=password,
        include_pages=include_pages,
    )


@server.tool(
    name="pdf_info",
    description=(
        "Inspect a PDF's structure without extracting all its text: page "
        "count, metadata, encryption, outline headings, form field names and "
        "page sizes. Provide one source: pdf_path, pdf_url, or pdf_base64."
    ),
)
async def pdf_info_tool(
    pdf_path: str | None = None,
    pdf_url: str | None = None,
    pdf_base64: str | None = None,
    password: str | None = None,
) -> dict:
    """Structural parse of a PDF (page count, metadata, outline, form fields).

    Args:
        pdf_path: Local path to a PDF file.
        pdf_url: http(s) URL of a PDF (if URL fetch is enabled).
        pdf_base64: Base64-encoded PDF bytes (small files only).
        password: Password for an encrypted PDF.
    """
    return await _toolset.info(
        pdf_path=pdf_path,
        pdf_url=pdf_url,
        pdf_base64=pdf_base64,
        password=password,
    )


@server.tool(
    name="pdf_create",
    description=(
        "Generate a PDF from Markdown, plain text, or HTML and return it as "
        "base64 (and optionally write it to output_path). Use to turn a "
        "report, letter or summary you produced into a shareable PDF. format "
        "is 'markdown' (# headings, - bullets, ``` code, **bold**, *italic*), "
        "'text', or 'html' (a practical subset of HTML + CSS; no JS/flexbox/"
        "grid). page_size is A4, LETTER, LEGAL, A3, or A5."
    ),
)
async def pdf_create_tool(
    content: str,
    format: str = "markdown",
    title: str | None = None,
    author: str | None = None,
    subject: str | None = None,
    page_size: str | None = None,
    output_path: str | None = None,
) -> dict:
    """Build a PDF from Markdown, plain text, or HTML.

    Args:
        content: Document body (Markdown subset, plain text, or HTML).
        format: "markdown", "text", or "html".
        title: Heading and PDF title metadata.
        author: PDF author metadata.
        subject: PDF subject metadata.
        page_size: A4, LETTER, LEGAL, A3, or A5.
        output_path: Write the PDF here (if local paths are enabled).
    """
    return _toolset.create(
        content=content,
        format=format,
        title=title,
        author=author,
        subject=subject,
        page_size=page_size,
        output_path=output_path,
    )


@server.tool(
    name="html_to_pdf",
    description=(
        "Render HTML and CSS to a PDF, including images. Use for resumes, "
        "CVs, and other designed documents. Pass html, optional css, and "
        "images as filename-to-base64 (PNG/JPEG/GIF). Remote URLs are blocked. "
        "Returns pdf_base64."
    ),
)
async def html_to_pdf_tool(
    html: str,
    css: str | None = None,
    images: dict[str, str] | None = None,
    title: str | None = None,
    author: str | None = None,
    subject: str | None = None,
    page_size: str | None = None,
    output_path: str | None = None,
) -> dict:
    """Build a PDF from HTML and CSS.

    Args:
        html: HTML fragment or full document.
        css: Optional stylesheet.
        images: Filename to base64 PNG, JPEG, or GIF.
        title: PDF title metadata.
        author: PDF author metadata.
        subject: PDF subject metadata.
        page_size: A4, LETTER, LEGAL, A3, or A5.
        output_path: Write the PDF here (if local paths are enabled).
    """
    return _toolset.html_to_pdf(
        html=html,
        css=css,
        images=images,
        title=title,
        author=author,
        subject=subject,
        page_size=page_size,
        output_path=output_path,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Hirarapdf MCP server")
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=["stdio", "sse", "streamable-http"],
        help="MCP transport to serve on (default: stdio).",
    )
    args = parser.parse_args()
    server.run(transport=args.transport)


if __name__ == "__main__":
    main()
