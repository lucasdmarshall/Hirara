"""html_to_pdf — HTML/CSS plus embedded images, no remote fetches."""

from __future__ import annotations

import base64

from pypdf import PdfReader
import io

from hirarapdf.config import PdfConfig
from hirarapdf.htmlpdf import build_html_pdf
from hirarapdf.tools import HTML_TO_PDF_SCHEMA, Toolset

# 1x1 PNG.
_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _text(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def test_schema_name():
    assert HTML_TO_PDF_SCHEMA["name"] == "html_to_pdf"
    assert "html" in HTML_TO_PDF_SCHEMA["input_schema"]["required"]


def test_resume_html_and_css_roundtrip():
    html = """
    <h1>Ada Lovelace</h1>
    <p class="role">Mathematician</p>
    <h2>Experience</h2>
    <ul><li>Analytical Engine</li></ul>
    """
    css = "h1 { color: #1a365d; font-size: 22pt; } .role { color: #444; }"
    data = build_html_pdf(html, css=css, title="Ada Lovelace")
    assert data.startswith(b"%PDF-")
    text = _text(data)
    assert "Ada Lovelace" in text
    assert "Analytical Engine" in text


def test_image_map_is_embedded():
    html = '<h1>CV</h1><img src="photo.png" width="40" height="40"/>'
    data = build_html_pdf(html, images={"photo.png": _PNG})
    assert data.startswith(b"%PDF-")
    assert b"/Image" in data or b"/XObject" in data


def test_data_uri_image():
    html = f'<p>Portrait</p><img src="data:image/png;base64,{_PNG}" width="20" height="20"/>'
    data = build_html_pdf(html)
    assert data.startswith(b"%PDF-")


def test_remote_image_rejected():
    ts = Toolset(config=PdfConfig())
    result = ts.html_to_pdf(
        html='<img src="https://example.com/a.png"/>',
    )
    assert result["error"]
    assert "blocked" in result["error"]
    assert result["pdf_base64"] is None


def test_missing_image_rejected():
    ts = Toolset(config=PdfConfig())
    result = ts.html_to_pdf(html='<img src="photo.png"/>')
    assert result["error"]
    assert "photo.png" in result["error"]


def test_tool_returns_base64_and_page_count():
    ts = Toolset(config=PdfConfig())
    result = ts.html_to_pdf(
        html="<h1>Resume</h1><p>Skills</p>",
        css="body { font-family: Helvetica; }",
        title="Resume",
    )
    assert result["error"] is None
    raw = base64.b64decode(result["pdf_base64"])
    assert raw.startswith(b"%PDF-")
    assert result["page_count"] == 1
    assert result["page_size"] == "A4"
    assert result["image_count"] == 0
