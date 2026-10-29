"""PDF maker — build a PDF from text or lightweight Markdown, via reportlab.

The agent hands in a string; this turns it into a real, paginating PDF. Two
input shapes:

* ``format="text"``     — plain text; blank lines separate paragraphs.
* ``format="markdown"`` — a lightweight Markdown subset: ``#``/``##``/``###``
  headings, ``-``/``*`` bullet lists, ``1.`` numbered lists, ```` ``` ````
  fenced code blocks, and inline ``**bold**``, ``*italic*`` and `` `code` ``.

It is deliberately a *subset*, not a full CommonMark engine — no tables, no
images, no nested blockquotes. That keeps the dependency surface to reportlab
alone (pure-Python, BSD-licensed) instead of pulling a browser engine in to
render HTML, which is the usual way "markdown to PDF" balloons a container.
"""

from __future__ import annotations

import html
import io
import re

_PAGE_SIZES: dict[str, str] = {
    "A4": "A4",
    "A3": "A3",
    "A5": "A5",
    "LETTER": "letter",
    "LEGAL": "legal",
}

# xhtml2pdf names its page sizes lowercase and drives them off CSS @page,
# so the maker keeps a separate mapping for the HTML path.
_HTML_PAGE_SIZES: dict[str, str] = {
    "A4": "a4",
    "A3": "a3",
    "A5": "a5",
    "LETTER": "letter",
    "LEGAL": "legal",
}


class MakeError(RuntimeError):
    """Raised when reportlab is missing or a document cannot be rendered."""


def _reportlab():
    try:
        from reportlab.lib import pagesizes
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            ListFlowable,
            ListItem,
            Paragraph,
            Preformatted,
            SimpleDocTemplate,
            Spacer,
        )
    except ImportError as exc:  # pragma: no cover - exercised via MakeError text
        raise MakeError(
            "reportlab is not installed. pip install 'hirarapdf' or "
            "pip install reportlab"
        ) from exc
    return {
        "pagesizes": pagesizes,
        "TA_LEFT": TA_LEFT,
        "ParagraphStyle": ParagraphStyle,
        "getSampleStyleSheet": getSampleStyleSheet,
        "mm": mm,
        "ListFlowable": ListFlowable,
        "ListItem": ListItem,
        "Paragraph": Paragraph,
        "Preformatted": Preformatted,
        "SimpleDocTemplate": SimpleDocTemplate,
        "Spacer": Spacer,
    }


# --- HTML rendering (xhtml2pdf) ----------------------------------------------


def _pisa():
    try:
        from xhtml2pdf import pisa
    except ImportError as exc:  # pragma: no cover - exercised via MakeError text
        raise MakeError(
            "xhtml2pdf is not installed. pip install 'hirarapdf' or "
            "pip install xhtml2pdf"
        ) from exc
    return pisa


def _build_html_pdf(
    content: str,
    *,
    title: str | None,
    author: str | None,
    subject: str | None,
    page_size: str,
) -> bytes:
    """Render an HTML string to PDF via xhtml2pdf (pisa), pure-Python.

    xhtml2pdf renders a practical subset of HTML + CSS on top of reportlab — no
    browser engine, no cairo/pango system libraries. It is not a full modern
    layout engine: flexbox, grid and most JS-driven styling do not apply. Feed
    it document-style HTML (headings, paragraphs, tables, simple CSS).

    A bare fragment is wrapped in a minimal document so ``title`` / ``author`` /
    ``subject`` land in the PDF metadata (xhtml2pdf reads ``<title>`` and
    ``<meta name=...>``). Content that is already a full ``<html>`` document is
    passed through untouched and controls its own head.
    """
    # Share the closed resource policy with html_to_pdf, independent of the
    # renderer version's default network/filesystem behavior.
    from .htmlpdf import build_html_pdf
    return build_html_pdf(content, title=title, author=author, subject=subject,
                          page_size=page_size)


# --- inline markup -----------------------------------------------------------

_CODE_RE = re.compile(r"`([^`]+)`")
_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")


def _inline(text: str) -> str:
    """Escape XML, then apply reportlab's mini-HTML for bold/italic/code.

    Escaping first is what makes user content with ``<`` or ``&`` safe: those
    become entities before any markup tags are introduced, so a document that
    literally contains ``<script>`` renders as text, not as broken markup.
    """
    escaped = html.escape(text, quote=False)
    escaped = _CODE_RE.sub(r'<font face="Courier">\1</font>', escaped)
    escaped = _BOLD_RE.sub(r"<b>\1</b>", escaped)
    escaped = _ITALIC_RE.sub(r"<i>\1</i>", escaped)
    return escaped


# --- block parsing -----------------------------------------------------------

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET_RE = re.compile(r"^[-*]\s+(.*)$")
_ORDERED_RE = re.compile(r"^\d+\.\s+(.*)$")


def _build_flowables(content: str, fmt: str, styles, rl) -> list:
    Paragraph = rl["Paragraph"]
    Preformatted = rl["Preformatted"]
    Spacer = rl["Spacer"]
    ListFlowable = rl["ListFlowable"]
    ListItem = rl["ListItem"]

    if fmt == "text":
        flow = []
        for block in re.split(r"\n\s*\n", content.strip()):
            block = block.strip()
            if not block:
                continue
            safe = _inline(block).replace("\n", "<br/>")
            flow.append(Paragraph(safe, styles["body"]))
            flow.append(Spacer(1, 6))
        return flow

    # markdown subset
    flow: list = []
    lines = content.replace("\r\n", "\n").split("\n")
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]

        # fenced code block
        if line.lstrip().startswith("```"):
            i += 1
            code_lines: list[str] = []
            while i < n and not lines[i].lstrip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1  # skip closing fence (or run off the end harmlessly)
            flow.append(Preformatted("\n".join(code_lines), styles["code"]))
            flow.append(Spacer(1, 6))
            continue

        # blank line
        if not line.strip():
            i += 1
            continue

        # heading
        m = _HEADING_RE.match(line)
        if m:
            level = min(len(m.group(1)), 3)
            flow.append(Paragraph(_inline(m.group(2).strip()), styles[f"h{level}"]))
            flow.append(Spacer(1, 4))
            i += 1
            continue

        # a run of list items (bulleted or ordered)
        if _BULLET_RE.match(line) or _ORDERED_RE.match(line):
            ordered = bool(_ORDERED_RE.match(line))
            items = []
            while i < n and (_BULLET_RE.match(lines[i]) or _ORDERED_RE.match(lines[i])):
                mm_ = _BULLET_RE.match(lines[i]) or _ORDERED_RE.match(lines[i])
                items.append(ListItem(Paragraph(_inline(mm_.group(1).strip()), styles["body"])))
                i += 1
            flow.append(
                ListFlowable(
                    items,
                    bulletType="1" if ordered else "bullet",
                    leftIndent=18,
                )
            )
            flow.append(Spacer(1, 6))
            continue

        # a paragraph: gather following non-blank, non-structural lines
        para_lines = [line]
        i += 1
        while i < n and lines[i].strip() and not (
            _HEADING_RE.match(lines[i])
            or _BULLET_RE.match(lines[i])
            or _ORDERED_RE.match(lines[i])
            or lines[i].lstrip().startswith("```")
        ):
            para_lines.append(lines[i])
            i += 1
        safe = _inline(" ".join(pl.strip() for pl in para_lines))
        flow.append(Paragraph(safe, styles["body"]))
        flow.append(Spacer(1, 6))

    return flow


def _styles(rl):
    base = rl["getSampleStyleSheet"]()
    ParagraphStyle = rl["ParagraphStyle"]
    return {
        "title": ParagraphStyle(
            "CpdfTitle", parent=base["Title"], spaceAfter=14
        ),
        "h1": ParagraphStyle("CpdfH1", parent=base["Heading1"]),
        "h2": ParagraphStyle("CpdfH2", parent=base["Heading2"]),
        "h3": ParagraphStyle("CpdfH3", parent=base["Heading3"]),
        "body": ParagraphStyle(
            "CpdfBody", parent=base["BodyText"], leading=15, spaceAfter=0
        ),
        "code": ParagraphStyle(
            "CpdfCode",
            parent=base["Code"],
            fontName="Courier",
            fontSize=9,
            leading=12,
            backColor="#f4f4f4",
            borderPadding=6,
            leftIndent=6,
        ),
    }


def build_pdf(
    content: str,
    *,
    fmt: str = "markdown",
    title: str | None = None,
    author: str | None = None,
    subject: str | None = None,
    page_size: str = "A4",
) -> bytes:
    """Render ``content`` to PDF bytes.

    Args:
        content: The document body (Markdown subset, plain text, or HTML).
        fmt: ``"markdown"``, ``"text"``, or ``"html"``.
        title: For markdown/text, rendered as a heading at the top; for all
            formats, written to PDF metadata.
        author, subject: Written to PDF metadata only.
        page_size: One of A4, A3, A5, LETTER, LEGAL.
    """
    if fmt not in {"markdown", "text", "html"}:
        raise MakeError("format must be 'markdown', 'text', or 'html'")
    if not content or not content.strip():
        raise MakeError("content is empty")

    # HTML takes a different engine (xhtml2pdf, still on top of reportlab):
    # it renders real HTML+CSS layout rather than the flowables the
    # markdown/text path builds by hand.
    if fmt == "html":
        return _build_html_pdf(
            content,
            title=title,
            author=author,
            subject=subject,
            page_size=page_size,
        )

    rl = _reportlab()

    size_name = _PAGE_SIZES.get(page_size.upper())
    if size_name is None:
        raise MakeError(f"unsupported page_size: {page_size}")
    pagesize = getattr(rl["pagesizes"], size_name)

    styles = _styles(rl)
    buffer = io.BytesIO()
    doc = rl["SimpleDocTemplate"](
        buffer,
        pagesize=pagesize,
        title=title or "",
        author=author or "",
        subject=subject or "",
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=54,
    )

    story: list = []
    if title:
        story.append(rl["Paragraph"](_inline(title), styles["title"]))
        story.append(rl["Spacer"](1, 6))
    story.extend(_build_flowables(content, fmt, styles, rl))

    try:
        doc.build(story)
    except Exception as exc:  # noqa: BLE001 — bad markup shouldn't 500 the caller
        raise MakeError(f"could not render PDF: {exc}") from exc

    return buffer.getvalue()


__all__ = ["MakeError", "build_pdf"]
