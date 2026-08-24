"""Toolset / schema / health."""

from __future__ import annotations

import pytest

from hirarafs.config import FsConfig
from hirarafs.tools import FILE_READ_SCHEMA, TOOL_NAMES, Toolset, call_tool


def test_schema_name():
    assert FILE_READ_SCHEMA["name"] == "file_read"
    assert "path" in FILE_READ_SCHEMA["input_schema"]["required"]


def test_health():
    ts = Toolset(config=FsConfig(roots=("/data",), allow_any_path=False))
    h = ts.health()
    assert h["status"] == "ok"
    assert h["tools"] == ["file_read"]
    assert h["roots"] == ["/data"]
    assert h["allow_any_path"] is False


@pytest.mark.asyncio
async def test_toolset_file_read(tmp_path):
    f = tmp_path / "note.md"
    f.write_text("# hi\n", encoding="utf-8")
    ts = Toolset(config=FsConfig(allow_any_path=True))
    r = await ts.file_read(path=str(f))
    assert r["error"] is None
    assert r["content"] == "# hi\n"
    assert r["encoding"] == "utf-8"


@pytest.mark.asyncio
async def test_call_tool(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("z", encoding="utf-8")
    # call_tool uses the process-global backend; override via env is awkward —
    # exercise the Toolset path above and just check TOOL_NAMES here.
    assert TOOL_NAMES == ("file_read",)
    with pytest.raises(KeyError):
        await call_tool("nope", {})
