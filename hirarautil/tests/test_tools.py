"""Toolset / schema / health."""

from __future__ import annotations

import pytest

from hirarautil.config import UtilConfig
from hirarautil.tools import DECODE_SCHEMA, TOOL_NAMES, Toolset, call_tool


def test_schema():
    assert DECODE_SCHEMA["name"] == "decode"
    assert "input" in DECODE_SCHEMA["input_schema"]["required"]


def test_health():
    h = Toolset(config=UtilConfig()).health()
    assert h["status"] == "ok"
    assert h["tools"] == ["decode"]


@pytest.mark.asyncio
async def test_toolset_decode():
    ts = Toolset(config=UtilConfig())
    r = await ts.decode(input="aGVsbG8=", format="base64")
    assert r["error"] is None
    assert r["output"] == "hello"


@pytest.mark.asyncio
async def test_call_tool_unknown():
    assert TOOL_NAMES == ("decode",)
    with pytest.raises(KeyError):
        await call_tool("nope", {})
