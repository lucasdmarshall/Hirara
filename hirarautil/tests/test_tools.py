"""Toolset / schema / health."""

from __future__ import annotations

import hashlib

import pytest

from hirarautil.config import UtilConfig
from hirarautil.tools import DECODE_SCHEMA, HASH_SCHEMA, TOOL_NAMES, Toolset, call_tool


def test_schema():
    assert DECODE_SCHEMA["name"] == "decode"
    assert HASH_SCHEMA["name"] == "hash"
    assert "input" in DECODE_SCHEMA["input_schema"]["required"]
    assert "input" in HASH_SCHEMA["input_schema"]["required"]


def test_health():
    h = Toolset(config=UtilConfig()).health()
    assert h["status"] == "ok"
    assert h["tools"] == ["decode", "hash"]


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
async def test_call_tool_unknown():
    assert TOOL_NAMES == ("decode", "hash")
    with pytest.raises(KeyError):
        await call_tool("nope", {})
