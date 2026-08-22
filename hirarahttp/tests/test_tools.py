"""Toolset schema + health + history integration."""

from __future__ import annotations

import httpx
import pytest

from hirarahttp.config import HttpConfig
from hirarahttp.history import HistoryStore
from hirarahttp.tools import HTTP_HISTORY_SCHEMA, HTTP_REQUEST_SCHEMA, Toolset


def test_schema_ready():
    assert HTTP_REQUEST_SCHEMA["name"] == "http_request"
    props = HTTP_REQUEST_SCHEMA["input_schema"]["properties"]
    assert {"url", "method", "headers", "body", "follow_redirects"} <= set(props)

    assert HTTP_HISTORY_SCHEMA["name"] == "http_history"
    hprops = HTTP_HISTORY_SCHEMA["input_schema"]["properties"]
    assert {"limit", "offset", "id", "include_body", "clear"} <= set(hprops)


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
async def test_history_unknown_id():
    ts = Toolset(config=HttpConfig())
    r = await ts.http_history(id="nope")
    assert r["error"] and "unknown" in r["error"]


def test_health():
    ts = Toolset(config=HttpConfig())
    h = ts.health()
    assert h["status"] == "ok"
    assert h["tools"] == ["http_request", "http_history"]
    assert h["history_count"] == 0
