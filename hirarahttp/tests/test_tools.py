"""Toolset schema + health + history integration."""

from __future__ import annotations

import httpx
import pytest

from hirarahttp.config import HttpConfig
from hirarahttp.history import HistoryStore
from hirarahttp.tools import (
    HTTP_HISTORY_SCHEMA,
    HTTP_REQUEST_SCHEMA,
    INSPECT_COOKIES_SCHEMA,
    INSPECT_HEADERS_SCHEMA,
    INSPECT_RESPONSE_SCHEMA,
    Toolset,
)


def test_schema_ready():
    assert HTTP_REQUEST_SCHEMA["name"] == "http_request"
    props = HTTP_REQUEST_SCHEMA["input_schema"]["properties"]
    assert {"url", "method", "headers", "body", "follow_redirects"} <= set(props)

    assert HTTP_HISTORY_SCHEMA["name"] == "http_history"
    hprops = HTTP_HISTORY_SCHEMA["input_schema"]["properties"]
    assert {"limit", "offset", "id", "include_body", "clear"} <= set(hprops)

    assert INSPECT_HEADERS_SCHEMA["name"] == "inspect_headers"
    iprops = INSPECT_HEADERS_SCHEMA["input_schema"]["properties"]
    assert {"id", "which", "headers"} <= set(iprops)

    assert INSPECT_COOKIES_SCHEMA["name"] == "inspect_cookies"
    cprops = INSPECT_COOKIES_SCHEMA["input_schema"]["properties"]
    assert {"id", "which", "headers"} <= set(cprops)

    assert INSPECT_RESPONSE_SCHEMA["name"] == "inspect_response"
    rprops = INSPECT_RESPONSE_SCHEMA["input_schema"]["properties"]
    assert {"id", "include_body", "preview_chars"} <= set(rprops)


@pytest.mark.asyncio
async def test_toolset_records_history(monkeypatch):
    import socket

    def resolver(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, headers={"content-type": "text/plain"}, content=b"ok"
        )
    )

    async def _wrapped(url, **kwargs):
        from hirarahttp.request import http_request as real

        kwargs.setdefault("resolver", resolver)
        kwargs.setdefault("transport", transport)
        return await real(url, **kwargs)

    monkeypatch.setattr("hirarahttp.tools.http_request", _wrapped)

    ts = Toolset(
        config=HttpConfig(history_size=10),
        history=HistoryStore(max_entries=10, max_body_chars=1000),
    )
    r = await ts.http_request(url="https://example.com/")
    assert r["error"] is None
    assert r["status"] == 200
    assert r["body"] == "ok"
    assert r["request_id"]

    hist = await ts.http_history(limit=5)
    assert hist["error"] is None
    assert hist["total"] == 1
    assert hist["count"] == 1
    assert hist["entries"][0]["id"] == r["request_id"]
    assert "body" not in hist["entries"][0]

    one = await ts.http_history(id=r["request_id"])
    assert one["count"] == 1
    assert one["entries"][0]["body"] == "ok"

    cleared = await ts.http_history(clear=True)
    assert cleared["cleared"] == 1
    empty = await ts.http_history()
    assert empty["total"] == 0


@pytest.mark.asyncio
async def test_inspect_headers_from_history(monkeypatch):
    import socket

    def resolver(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={
                "content-type": "text/plain",
                "x-content-type-options": "nosniff",
            },
            content=b"ok",
        )
    )

    async def _wrapped(url, **kwargs):
        from hirarahttp.request import http_request as real

        kwargs.setdefault("resolver", resolver)
        kwargs.setdefault("transport", transport)
        return await real(url, **kwargs)

    monkeypatch.setattr("hirarahttp.tools.http_request", _wrapped)

    ts = Toolset(
        config=HttpConfig(history_size=10),
        history=HistoryStore(max_entries=10, max_body_chars=1000),
    )
    r = await ts.http_request(url="https://example.com/")
    view = await ts.inspect_headers(id=r["request_id"], which="both")
    assert view["error"] is None
    assert view["response"]["content_type"] == "text/plain"
    assert "x-content-type-options" in view["response"]["interesting"]
    assert view["request"]["by_name"]["host"] == "example.com"


@pytest.mark.asyncio
async def test_inspect_headers_raw_map():
    ts = Toolset(config=HttpConfig())
    view = await ts.inspect_headers(
        headers={"Content-Type": "application/json", "Server": "x"},
        which="response",
    )
    assert view["error"] is None
    assert view["response"]["interesting"]["content-type"] == "application/json"


@pytest.mark.asyncio
async def test_inspect_cookies_from_history(monkeypatch):
    import socket

    def resolver(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={
                "content-type": "text/plain",
                "set-cookie": "sid=abc; Path=/; HttpOnly; Secure; SameSite=Lax",
            },
            content=b"ok",
        )
    )

    async def _wrapped(url, **kwargs):
        from hirarahttp.request import http_request as real

        kwargs.setdefault("resolver", resolver)
        kwargs.setdefault("transport", transport)
        return await real(url, **kwargs)

    monkeypatch.setattr("hirarahttp.tools.http_request", _wrapped)

    ts = Toolset(
        config=HttpConfig(history_size=10),
        history=HistoryStore(max_entries=10, max_body_chars=1000),
    )
    r = await ts.http_request(url="https://example.com/")
    view = await ts.inspect_cookies(id=r["request_id"], which="response")
    assert view["error"] is None
    assert view["response"]["names"] == ["sid"]
    cookie = view["response"]["cookies"][0]
    assert cookie["httponly"] is True
    assert cookie["secure"] is True
    assert cookie["samesite"] == "Lax"
    assert cookie["flags_missing"] == []


@pytest.mark.asyncio
async def test_inspect_cookies_raw_map():
    ts = Toolset(config=HttpConfig())
    view = await ts.inspect_cookies(
        headers={"Cookie": "theme=dark; lang=en"},
        which="request",
    )
    assert view["error"] is None
    assert view["request"]["names"] == ["theme", "lang"]


@pytest.mark.asyncio
async def test_inspect_response_from_history(monkeypatch):
    import socket

    def resolver(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            201,
            headers={"content-type": "application/json"},
            content=b'{"ok":true,"id":7}',
        )
    )

    async def _wrapped(url, **kwargs):
        from hirarahttp.request import http_request as real

        kwargs.setdefault("resolver", resolver)
        kwargs.setdefault("transport", transport)
        return await real(url, **kwargs)

    monkeypatch.setattr("hirarahttp.tools.http_request", _wrapped)

    ts = Toolset(
        config=HttpConfig(history_size=10),
        history=HistoryStore(max_entries=10, max_body_chars=1000),
    )
    r = await ts.http_request(url="https://example.com/")
    view = await ts.inspect_response(id=r["request_id"])
    assert view["error"] is None
    assert view["status"] == 201
    assert view["ok"] is True
    assert view["body_kind"] == "json"
    assert view["json_type"] == "object"
    assert set(view["json_keys"]) == {"ok", "id"}
    assert view["body"] is None
    assert view["json"] is None

    full = await ts.inspect_response(id=r["request_id"], include_body=True)
    assert full["json"] == {"ok": True, "id": 7}


@pytest.mark.asyncio
async def test_inspect_response_raw():
    ts = Toolset(config=HttpConfig())
    view = await ts.inspect_response(
        status=302,
        headers={"Location": "https://example.com/next", "Content-Type": "text/plain"},
        body="go",
    )
    assert view["error"] is None
    assert view["status_class"] == "3xx"
    assert view["ok"] is False
    assert view["location"] == "https://example.com/next"
    assert view["body_kind"] == "text"


@pytest.mark.asyncio
async def test_history_unknown_id():
    ts = Toolset(config=HttpConfig())
    r = await ts.http_history(id="nope")
    assert r["error"] and "unknown" in r["error"]


def test_health():
    ts = Toolset(config=HttpConfig())
    h = ts.health()
    assert h["status"] == "ok"
    assert h["tools"] == [
        "http_request",
        "http_history",
        "inspect_headers",
        "inspect_cookies",
        "inspect_response",
    ]
    assert h["history_count"] == 0
