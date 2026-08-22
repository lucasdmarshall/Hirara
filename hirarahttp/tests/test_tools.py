"""Toolset schema + health."""

from __future__ import annotations

import httpx
import pytest

from hirarahttp.config import HttpConfig
from hirarahttp.tools import HTTP_REQUEST_SCHEMA, Toolset


def test_schema_ready():
    assert HTTP_REQUEST_SCHEMA["name"] == "http_request"
    props = HTTP_REQUEST_SCHEMA["input_schema"]["properties"]
    assert {"url", "method", "headers", "body", "follow_redirects"} <= set(props)


@pytest.mark.asyncio
async def test_toolset_http_request(monkeypatch):
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

    ts = Toolset(config=HttpConfig())
    r = await ts.http_request(url="https://example.com/")
    assert r["error"] is None
    assert r["status"] == 200
    assert r["body"] == "ok"


def test_health():
    ts = Toolset(config=HttpConfig())
    h = ts.health()
    assert h["status"] == "ok"
    assert h["tools"] == ["http_request"]
