"""Toolset / schema / health."""

from __future__ import annotations

import pytest

from hirarafs.config import FsConfig
from hirarafs.tools import (
    FILE_READ_SCHEMA,
    FILE_WRITE_SCHEMA,
    TOOL_NAMES,
    Toolset,
    call_tool,
)


def test_schema_names():
    assert FILE_READ_SCHEMA["name"] == "file_read"
    assert FILE_WRITE_SCHEMA["name"] == "file_write"
    assert "path" in FILE_READ_SCHEMA["input_schema"]["required"]
    assert set(FILE_WRITE_SCHEMA["input_schema"]["required"]) == {"path", "content"}


def test_health():
    ts = Toolset(config=FsConfig(roots=("/data",), allow_any_path=False))
    h = ts.health()
    assert h["status"] == "ok"
    assert h["tools"] == ["file_read", "file_write"]
    assert h["roots"] == ["/data"]
    assert h["allow_any_path"] is False
    assert h["allow_write"] is True


@pytest.mark.asyncio
async def test_toolset_roundtrip(tmp_path):
    f = tmp_path / "note.md"
    ts = Toolset(config=FsConfig(allow_any_path=True))
    w = await ts.file_write(path=str(f), content="# hi\n")
    assert w["error"] is None
    assert w["created"] is True
    r = await ts.file_read(path=str(f))
    assert r["error"] is None
    assert r["content"] == "# hi\n"


@pytest.mark.asyncio
async def test_call_tool_unknown():
    assert TOOL_NAMES == ("file_read", "file_write")
    with pytest.raises(KeyError):
        await call_tool("nope", {})
