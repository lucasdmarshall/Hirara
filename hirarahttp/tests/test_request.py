"""http_request — MockTransport, no live network."""

from __future__ import annotations

import base64
import socket

import httpx
import pytest

from hirarahttp.config import HttpConfig
from hirarahttp.request import http_request


def fake_resolver(*addresses: str):
    def _resolve(host, port, *args, **kwargs):
        out = []
        for address in addresses:
            family = socket.AF_INET6 if ":" in address else socket.AF_INET
            sockaddr = (
                (address, port, 0, 0) if family == socket.AF_INET6 else (address, port)
            )
            out.append((family, socket.SOCK_STREAM, 6, "", sockaddr))
        return out

    return _resolve


PUBLIC = fake_resolver("93.184.216.34")


def handler_returning(*responses):
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        return queue.pop(0)

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_get_happy_path():
    transport = handler_returning(
        httpx.Response(
            200,
            headers={"content-type": "text/plain; charset=utf-8"},
            content=b"hello",
        )
    )
    r = await http_request(
        "https://example.com/",
        resolver=PUBLIC,
        transport=transport,
        config=HttpConfig(allow_private_ips=False),
    )
    assert r.error is None
    assert r.status == 200
    assert r.body == "hello"
    assert r.body_encoding == "utf-8"
    assert r.bytes_downloaded == 5
    assert r.request_headers.get("Host") == "example.com"


@pytest.mark.asyncio
async def test_returns_404_as_data():
    transport = handler_returning(
        httpx.Response(404, headers={"content-type": "text/plain"}, content=b"missing")
    )
    r = await http_request(
        "https://example.com/missing",
        resolver=PUBLIC,
        transport=transport,
    )
    assert r.error is None
    assert r.status == 404
    assert r.body == "missing"


@pytest.mark.asyncio
async def test_blocks_metadata():
    r = await http_request(
        "http://169.254.169.254/latest/meta-data/",
        resolver=fake_resolver("169.254.169.254"),
        transport=handler_returning(httpx.Response(200, content=b"x")),
        config=HttpConfig(allow_private_ips=False),
    )
    assert r.error and "blocked" in r.error


@pytest.mark.asyncio
async def test_redirect_to_metadata_blocked():
    calls = {"n": 0}

    def resolver(host, port, *args, **kwargs):
        calls["n"] += 1
        address = "93.184.216.34" if host == "public.example" else "169.254.169.254"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

    transport = handler_returning(
        httpx.Response(302, headers={"location": "http://metadata.evil/latest/"}),
    )
    r = await http_request(
        "http://public.example/a",
        resolver=resolver,
        transport=transport,
        config=HttpConfig(allow_private_ips=False),
    )
    assert r.error and "blocked" in r.error
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_follows_safe_redirect():
    transport = handler_returning(
        httpx.Response(302, headers={"location": "https://example.com/final"}),
        httpx.Response(
            200, headers={"content-type": "text/plain"}, content=b"final"
        ),
    )
    r = await http_request(
        "https://example.com/start",
        resolver=PUBLIC,
        transport=transport,
    )
    assert r.error is None
    assert r.body == "final"
    assert r.final_url == "https://example.com/final"
    assert r.redirects == ["https://example.com/start"]


@pytest.mark.asyncio
async def test_no_follow_redirects():
    transport = handler_returning(
        httpx.Response(
            302,
            headers={"location": "https://example.com/final", "content-type": "text/plain"},
            content=b"go",
        )
    )
    r = await http_request(
        "https://example.com/start",
        follow_redirects=False,
        resolver=PUBLIC,
        transport=transport,
    )
    assert r.error is None
    assert r.status == 302
    assert r.final_url == "https://example.com/start"
    assert r.redirects == []


@pytest.mark.asyncio
async def test_byte_cap():
    big = b"x" * 10_000
    transport = handler_returning(
        httpx.Response(200, headers={"content-type": "text/plain"}, content=big)
    )
    r = await http_request(
        "https://example.com/big",
        max_bytes=1000,
        resolver=PUBLIC,
        transport=transport,
        config=HttpConfig(max_bytes=5_000_000),
    )
    assert r.truncated is True
    assert r.bytes_downloaded == 1000


@pytest.mark.asyncio
async def test_binary_body_base64():
    raw = b"\x00\x01\xff"
    transport = handler_returning(
        httpx.Response(
            200, headers={"content-type": "application/octet-stream"}, content=raw
        )
    )
    r = await http_request(
        "https://example.com/bin",
        resolver=PUBLIC,
        transport=transport,
    )
    assert r.body_encoding == "base64"
    assert base64.b64decode(r.body) == raw


@pytest.mark.asyncio
async def test_post_body():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            201, headers={"content-type": "application/json"}, content=b'{"ok":true}'
        )

    r = await http_request(
        "https://example.com/api",
        method="POST",
        headers={"Content-Type": "application/json"},
        body='{"a":1}',
        resolver=PUBLIC,
        transport=httpx.MockTransport(handler),
    )
    assert r.error is None
    assert r.status == 201
    assert r.body == '{"ok":true}'
    assert seen[0].content == b'{"a":1}'
    assert seen[0].method == "POST"


@pytest.mark.asyncio
async def test_rejects_get_with_body():
    r = await http_request(
        "https://example.com/",
        method="GET",
        body="nope",
        resolver=PUBLIC,
        transport=handler_returning(httpx.Response(200, content=b"x")),
    )
    assert r.error and "body" in r.error


@pytest.mark.asyncio
async def test_rejects_host_header():
    r = await http_request(
        "https://example.com/",
        headers={"Host": "evil.example"},
        resolver=PUBLIC,
        transport=handler_returning(httpx.Response(200, content=b"x")),
    )
    assert r.error and "not allowed" in r.error


@pytest.mark.asyncio
async def test_empty_url():
    r = await http_request("")
    assert r.error and "required" in r.error


@pytest.mark.asyncio
async def test_bad_method():
    r = await http_request("https://example.com/", method="TRACE")
    assert r.error and "unsupported" in r.error
