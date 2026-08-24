"""Toolset / schema / health."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json

import pytest

from hirarautil.config import UtilConfig
from hirarautil.tools import (
    DECODE_SCHEMA,
    HASH_SCHEMA,
    JWT_DECODE_SCHEMA,
    JWT_INSPECT_SCHEMA,
    TOOL_NAMES,
    Toolset,
    call_tool,
)


def _token() -> str:
    def b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    h = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    p = b64(json.dumps({"sub": "x"}).encode())
    sig = hmac.new(b"secret", f"{h}.{p}".encode(), hashlib.sha256).digest()
    return f"{h}.{p}.{b64(sig)}"


def test_schema():
    assert DECODE_SCHEMA["name"] == "decode"
    assert HASH_SCHEMA["name"] == "hash"
    assert JWT_INSPECT_SCHEMA["name"] == "jwt_inspect"
    assert JWT_DECODE_SCHEMA["name"] == "jwt_decode"


def test_health():
    h = Toolset(config=UtilConfig()).health()
    assert h["status"] == "ok"
    assert h["tools"] == ["decode", "hash", "jwt_inspect", "jwt_decode"]


@pytest.mark.asyncio
async def test_toolset_decode():
    ts = Toolset(config=UtilConfig())
    r = await ts.decode(input="aGVsbG8=", format="base64")
    assert r["error"] is None
    assert r["output"] == "hello"


@pytest.mark.asyncio
async def test_toolset_hash():
    ts = Toolset(config=UtilConfig())
    r = await ts.hash(input="hello", algorithms="sha256")
    assert r["error"] is None
    assert r["digest"] == hashlib.sha256(b"hello").hexdigest()


@pytest.mark.asyncio
async def test_toolset_jwt():
    ts = Toolset(config=UtilConfig())
    token = _token()
    insp = await ts.jwt_inspect(input=token, include_claims=True)
    assert insp["error"] is None
    assert insp["algorithm"] == "HS256"
    assert insp["claims"]["sub"] == "x"
    dec = await ts.jwt_decode(input=token, verify=True, secret="secret")
    assert dec["error"] is None
    assert dec["verified"] is True


@pytest.mark.asyncio
async def test_call_tool_unknown():
    assert TOOL_NAMES == ("decode", "hash", "jwt_inspect", "jwt_decode")
    with pytest.raises(KeyError):
        await call_tool("nope", {})
