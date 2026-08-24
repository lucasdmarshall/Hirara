"""directory_enum — MockTransport, no live network."""

from __future__ import annotations

import socket

import httpx
import pytest

from hirarahttp.config import HttpConfig
from hirarahttp.enum_dir import directory_enum, normalize_paths


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


def test_normalize_paths_default_and_cap():
    paths, truncated = normalize_paths(
        None, default=("a", "b", "c"), max_paths=2
    )
    assert paths == ["a", "b"]
    assert truncated is True


def test_normalize_rejects_dotdot():
    with pytest.raises(Exception, match=r"\.\."):
        normalize_paths(["../etc/passwd"], default=(), max_paths=10)


@pytest.mark.asyncio
async def test_enum_finds_existing_hides_404():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/admin"):
            return httpx.Response(200, headers={"content-type": "text/html"})
        if path.endswith("/secret"):
            return httpx.Response(302, headers={"location": "/login"})
        return httpx.Response(404)

    r = await directory_enum(
        "https://example.com/",
        paths=["admin", "missing", "secret"],
        resolver=PUBLIC,
        transport=httpx.MockTransport(handler),
        config=HttpConfig(allow_private_ips=False),
    )
    assert r.error is None
    assert r.probed == 3
    assert r.found_count == 2
    names = {h.path for h in r.found}
    assert names == {"admin", "secret"}
    secret = next(h for h in r.found if h.path == "secret")
    assert secret.status == 302
    assert secret.location == "/login"
    assert all(h.path != "missing" for h in r.results)


@pytest.mark.asyncio
async def test_enum_include_not_found():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    r = await directory_enum(
        "https://example.com/",
        paths=["nope"],
        include_not_found=True,
        resolver=PUBLIC,
        transport=httpx.MockTransport(handler),
    )
    assert r.probed == 1
    assert r.found_count == 0
    assert r.results[0].status == 404


@pytest.mark.asyncio
async def test_enum_blocks_metadata():
    r = await directory_enum(
        "http://169.254.169.254/",
        paths=["admin"],
        resolver=fake_resolver("169.254.169.254"),
        transport=httpx.MockTransport(lambda r: httpx.Response(200)),
        config=HttpConfig(allow_private_ips=False),
    )
    assert r.error and "blocked" in r.error


@pytest.mark.asyncio
async def test_enum_empty_url():
    r = await directory_enum("")
    assert r.error and "required" in r.error


@pytest.mark.asyncio
async def test_enum_rejects_method():
    r = await directory_enum(
        "https://example.com/",
        paths=["admin"],
        method="POST",
        resolver=PUBLIC,
        transport=httpx.MockTransport(lambda r: httpx.Response(200)),
    )
    assert r.error and "unsupported method" in r.error


def test_normalize_comma_string():
    paths, truncated = normalize_paths(
        "admin, login\napi", default=(), max_paths=10
    )
    assert paths == ["admin", "login", "api"]
    assert truncated is False
