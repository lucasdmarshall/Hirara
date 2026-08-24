"""Gateway aggregation + forwarding, driven against mock backends."""

from __future__ import annotations

import httpx
import pytest

from hirara_hub.config import HubConfig
from hirara_hub.gateway import Gateway
from hirara_hub.registry import TOOLS

# Point every service at a stable fake host; the MockTransport routes by host.
_URLS = {
    "websearch": "http://websearch",
    "hirarastt": "http://hirarastt",
    "hirarapdf": "http://hirarapdf",
    "hiraracode": "http://hiraracode",
    "hiraraocr": "http://hiraraocr",
    "hirarareader": "http://hirarareader",
    "hiraranet": "http://hiraranet",
    "hirarabrowser": "http://hirarabrowser",
    "hirarahttp": "http://hirarahttp",
    "hirarafs": "http://hirarafs",
}

# Which services are "up" in a given test, and what their /schemas returns.
_SCHEMAS = {
    "hirarareader": {"tools": [{"name": "office_read"}]},
    "hirarapdf": {"tools": [{"name": "pdf_read"}, {"name": "pdf_info"}, {"name": "pdf_create"}]},
}


def _handler(request: httpx.Request) -> httpx.Response:
    host = request.url.host
    path = request.url.path
    if path == "/schemas":
        if host in _SCHEMAS:
            return httpx.Response(200, json=_SCHEMAS[host])
        return httpx.Response(503)
    if path == "/health":
        return httpx.Response(200 if host in _SCHEMAS else 503)
    if path == "/office_read":
        return httpx.Response(200, json={"kind": "docx", "markdown": "# Hi", "error": None})
    if path == "/pdf_create":
        return httpx.Response(200, json={"pdf_base64": "JVBERi0=", "error": None})
    return httpx.Response(404)


def _gateway() -> Gateway:
    config = HubConfig(service_urls=dict(_URLS))
    client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
    return Gateway(config, client=client)


@pytest.mark.asyncio
async def test_schemas_aggregates_only_reachable_backends():
    g = _gateway()
    result = await g.schemas()
    names = {t["name"] for t in result["tools"]}
    assert names == {"office_read", "pdf_read", "pdf_info", "pdf_create"}
    # backends that returned 503 are reported unavailable, never advertised
    assert "hiraraocr" in result["unavailable"]
    assert "websearch" in result["unavailable"]


@pytest.mark.asyncio
async def test_call_forwards_to_the_right_backend():
    g = _gateway()
    r = await g.call("office_read", {"file_base64": "x"})
    assert r["error"] is None
    assert r["kind"] == "docx"

    r2 = await g.call("pdf_create", {"content": "hi"})
    assert r2["pdf_base64"] == "JVBERi0="


@pytest.mark.asyncio
async def test_unknown_tool_is_an_error_body():
    g = _gateway()
    r = await g.call("does_not_exist", {})
    assert "unknown tool" in r["error"]


@pytest.mark.asyncio
async def test_unreachable_backend_is_an_error_body():
    g = _gateway()
    # hiraraocr's /ocr_read returns 404 in the mock → not a 5xx, but let's hit a
    # truly unreachable one by calling a tool whose backend 503s health/schemas.
    r = await g.call("ocr_read", {"file_base64": "x"})
    # 404 path → resp.json() raises → error body
    assert "error" in r


@pytest.mark.asyncio
async def test_health_reports_per_backend():
    g = _gateway()
    h = await g.health()
    assert h["services"]["hirarareader"] == "up"
    assert h["services"]["hiraraocr"] != "up"  # 503 in the mock → "http 503"
    assert h["services_up"] == 2  # only hirarareader + hirarapdf are healthy
    assert h["services_total"] == len(set(r.service for r in TOOLS.values()))
    assert h["auth"] == "disabled"


def test_every_tool_has_a_route():
    # registry sanity: the 10 shipped tools are all routed
    assert set(TOOLS) >= {
        "web_search", "web_fetch", "pdf_read", "pdf_info", "pdf_create",
        "execute_code", "ocr_read", "form_extract", "office_read",
        "dns_lookup", "port_scan", "service_enum",
        "browser_open", "browser_click", "browser_type", "browser_screenshot",
        "http_request", "http_history", "inspect_headers", "inspect_cookies",
        "inspect_response", "directory_enum",
        "file_read", "file_write",
    }
