"""Toolset / schema / health."""

from __future__ import annotations

import pytest

from hiraraops.config import OpsConfig
from hiraraops.tools import APPLICATION_LOGS_SCHEMA, TOOL_NAMES, Toolset, call_tool


def test_schema():
    assert APPLICATION_LOGS_SCHEMA["name"] == "application_logs"


def test_health():
    h = Toolset(
        config=OpsConfig(log_sources={"app": "/logs/app.log"}, roots=("/logs",))
    ).health()
    assert h["status"] == "ok"
    assert h["tools"] == ["application_logs"]
    assert h["sources"] == ["app"]


@pytest.mark.asyncio
async def test_toolset(tmp_path):
    f = tmp_path / "t.log"
    f.write_text("one\ntwo\n", encoding="utf-8")
    ts = Toolset(config=OpsConfig(allow_any_path=True))
    r = await ts.application_logs(path=str(f), lines=10)
    assert r["error"] is None
    assert r["line_count"] == 2


@pytest.mark.asyncio
async def test_call_tool_unknown():
    assert TOOL_NAMES == ("application_logs",)
    with pytest.raises(KeyError):
        await call_tool("nope", {})
