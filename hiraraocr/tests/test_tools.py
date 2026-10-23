"""Toolset orchestration against a fake engine (no models required)."""

from __future__ import annotations

import base64
import io

import pytest
from PIL import Image

from hiraraocr.config import OcrConfig
from hiraraocr.engines import OcrBlock
from hiraraocr.tools import FORM_EXTRACT_SCHEMA, OCR_READ_SCHEMA, Toolset


class FakeEngine:
    def __init__(self, blocks=None, name="fake"):
        self.blocks = blocks if blocks is not None else [
            OcrBlock("hello", (10, 10, 60, 30), 0.99),
            OcrBlock("world", (70, 10, 120, 30), 0.98),
        ]
        self._name = name
        self.calls: list[dict] = []

    def info(self):
        return {"engine": self._name}

    def ensure_loaded(self):
        pass

    def recognize(self, image, *, languages):
        self.calls.append({"languages": languages, "shape": getattr(image, "shape", None)})
        return list(self.blocks)


def _png_b64() -> str:
    im = Image.new("RGB", (140, 40), "white")
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _toolset(engine=None, **cfg) -> Toolset:
    ts = Toolset(config=OcrConfig(preprocess=False, **cfg))
    ts.engine = engine or FakeEngine()
    return ts


def test_schema_is_agent_ready():
    assert OCR_READ_SCHEMA["name"] == "ocr_read"
    props = OCR_READ_SCHEMA["input_schema"]["properties"]
    assert {"file_path", "file_url", "file_base64", "languages"} <= set(props)
    assert props["detail"]["enum"] == ["markdown", "layout"]


@pytest.mark.asyncio
async def test_read_base64_image():
    ts = _toolset()
    r = await ts.read(file_base64=_png_b64(), languages=["en"])
    assert r["error"] is None
    assert r["text"] == "hello world"
    assert r["markdown"] == "hello world"
    assert r["page_count"] == 1
    assert r["engine"] == "fake"
    assert r["source"] == "file_base64"
    assert r["blocks"] is None  # markdown detail omits blocks


@pytest.mark.asyncio
async def test_layout_detail_returns_blocks():
    ts = _toolset()
    r = await ts.read(file_base64=_png_b64(), detail="layout")
    assert r["blocks"] is not None
    assert r["blocks"][0]["blocks"][0]["text"] == "hello"
    assert "bbox" in r["blocks"][0]["blocks"][0]


@pytest.mark.asyncio
async def test_languages_reach_the_engine():
    engine = FakeEngine()
    ts = _toolset(engine=engine)
    await ts.read(file_base64=_png_b64(), languages=["fr"])
    assert engine.calls[0]["languages"] == ["fr"]


@pytest.mark.asyncio
async def test_rejects_multiple_sources():
    ts = _toolset()
    r = await ts.read(file_base64=_png_b64(), file_path="/x.png")
    assert r["error"] and "only one" in r["error"]


@pytest.mark.asyncio
async def test_missing_source_returns_envelope():
    ts = _toolset()
    r = await ts.read()
    assert r["error"] and r["text"] is None
    assert set(r) >= {"text", "markdown", "pages", "engine", "source", "error"}


@pytest.mark.asyncio
async def test_url_fetch_disabled_by_default():
    ts = _toolset(allow_url_fetch=False)
    r = await ts.read(file_url="https://example.com/a.png")
    assert r["error"] and "COCR_ALLOW_URL_FETCH" in r["error"]


@pytest.mark.asyncio
async def test_local_path_can_be_disabled():
    ts = Toolset(config=OcrConfig(preprocess=False, allow_local_path=False))
    ts.engine = FakeEngine()
    r = await ts.read(file_path="/etc/passwd.png")
    assert r["error"] and "COCR_ALLOW_LOCAL_PATH" in r["error"]


@pytest.mark.asyncio
async def test_bad_image_bytes_report_cleanly():
    ts = _toolset()
    r = await ts.read(file_base64=base64.b64encode(b"not an image").decode())
    assert r["error"] and "decode image" in r["error"]


@pytest.mark.asyncio
async def test_max_bytes_enforced():
    ts = Toolset(config=OcrConfig(preprocess=False, max_bytes=10))
    ts.engine = FakeEngine()
    r = await ts.read(file_base64=_png_b64())
    assert r["error"] and "COCR_MAX_BYTES" in r["error"]


@pytest.mark.asyncio
async def test_text_truncation_flagged():
    long_blocks = [OcrBlock("x" * 100, (0, i * 10, 50, i * 10 + 8), 0.9) for i in range(10)]
    ts = Toolset(config=OcrConfig(preprocess=False, max_chars=20))
    ts.engine = FakeEngine(blocks=long_blocks)
    r = await ts.read(file_base64=_png_b64())
    assert r["truncated"] is True
    assert len(r["text"]) <= 20


@pytest.mark.asyncio
async def test_url_fetch_routes_through_the_ssrf_guard(monkeypatch):
    from hirara_core import BlockedURL
    import hiraraocr.tools as tools_module

    async def fake_download(url, **kwargs):
        raise BlockedURL("169.254.169.254 is not globally routable")

    monkeypatch.setattr(tools_module, "safe_download", fake_download)
    ts = Toolset(config=OcrConfig(preprocess=False, allow_url_fetch=True))
    ts.engine = FakeEngine()
    r = await ts.read(file_url="http://169.254.169.254/a.png")
    assert r["text"] is None
    assert "blocked" in r["error"]


@pytest.mark.asyncio
async def test_form_extract_from_ocr_blocks():
    invoice = FakeEngine(blocks=[
        OcrBlock("Total:", (0, 10, 50, 30), 0.9),
        OcrBlock("99.99", (120, 10, 180, 30), 0.9),
    ])
    ts = _toolset(engine=invoice)
    r = await ts.extract(file_base64=_png_b64(), languages=["en"])
    assert r["error"] is None
    assert r["fields"]["total"] == "99.99"
    assert r["engine"] == "fake"
    assert r["source"] == "file_base64"


@pytest.mark.asyncio
async def test_form_extract_schema_present():
    assert FORM_EXTRACT_SCHEMA["name"] == "form_extract"
    assert "templates" in FORM_EXTRACT_SCHEMA["input_schema"]["properties"]


@pytest.mark.asyncio
async def test_form_extract_missing_source():
    ts = _toolset()
    r = await ts.extract()
    assert r["error"]
    assert set(r) >= {"fields", "table", "text", "engine", "source", "error"}


@pytest.mark.asyncio
async def test_url_fetch_happy_path(monkeypatch):
    from hirara_core import DownloadResult
    import hiraraocr.tools as tools_module

    png = base64.b64decode(_png_b64())

    async def fake_download(url, **kwargs):
        return DownloadResult(
            content=png,
            final_url=url,
            status=200,
            content_type="image/png",
            truncated=False,
            redirects=[],
        )

    monkeypatch.setattr(tools_module, "safe_download", fake_download)
    ts = Toolset(config=OcrConfig(preprocess=False, allow_url_fetch=True))
    ts.engine = FakeEngine()
    r = await ts.read(file_url="https://example.com/a.png")
    assert r["error"] is None
    assert r["text"] == "hello world"
    assert r["source"] == "https://example.com/a.png"


async def test_local_backend_contract():
    from hiraraocr import tools

    assert tools.TOOL_NAMES == ("ocr_read", "form_extract")
    assert [s["name"] for s in tools.tool_schemas()] == list(tools.TOOL_NAMES)
    with pytest.raises(KeyError):
        await tools.call_tool("nope", {})
    # A missing source is answered without loading any OCR model.
    for name in tools.TOOL_NAMES:
        result = await tools.call_tool(name, {})
        assert result["error"].startswith("provide exactly one of")
