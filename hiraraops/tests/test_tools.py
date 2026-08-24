"""Toolset / schema / health."""

from __future__ import annotations

import pytest

from hiraraops.config import OpsConfig
from hiraraops.tools import (
    APPLICATION_LOGS_SCHEMA,
    ENVIRONMENT_READ_SCHEMA,
    PROCESS_LIST_SCHEMA,
    TOOL_NAMES,
    Toolset,
    call_tool,
)


def test_schema():
    assert APPLICATION_LOGS_SCHEMA["name"] == "application_logs"
    assert PROCESS_LIST_SCHEMA["name"] == "process_list"
    assert ENVIRONMENT_READ_SCHEMA["name"] == "environment_read"


def test_health():
    h = Toolset(
        config=OpsConfig(log_sources={"app": "/logs/app.log"}, roots=("/logs",))
    ).health()
    assert h["status"] == "ok"
    assert h["tools"] == ["application_logs", "process_list", "environment_read"]
    assert h["sources"] == ["app"]
    assert h["allow_process_list"] is True
    assert h["allow_environment_read"] is True
    assert h["redact_env"] is True


@pytest.mark.asyncio
async def test_toolset_logs(tmp_path):
    f = tmp_path / "t.log"
    f.write_text("one\ntwo\n", encoding="utf-8")
    ts = Toolset(config=OpsConfig(allow_any_path=True))
    r = await ts.application_logs(path=str(f), lines=10)
    assert r["error"] is None
    assert r["line_count"] == 2


@pytest.mark.asyncio
async def test_toolset_process_list(tmp_path):
    proc = tmp_path / "proc" / "1"
    proc.mkdir(parents=True)
    (proc / "status").write_text(
        "Name:\tinit\nState:\tS (sleeping)\nUid:\t0\t0\t0\t0\nPPid:\t0\n",
        encoding="utf-8",
    )
    (proc / "cmdline").write_bytes(b"/sbin/init\0")
    ts = Toolset(config=OpsConfig(proc_root=str(tmp_path / "proc")))
    r = await ts.process_list()
    assert r["error"] is None
    assert r["process_count"] == 1
    assert r["processes"][0]["name"] == "init"


@pytest.mark.asyncio
async def test_toolset_environment_read():
    ts = Toolset(config=OpsConfig(redact_env=True))
    # Force deterministic input via process self-read is flaky; call core via
    # tool with empty keys filter on real env is fine — just check envelope.
    r = await ts.environment_read(keys=["PATH"], include_values=True)
    assert r["error"] is None
    assert r["source"] == "self"
    assert "PATH" in r["keys"]


@pytest.mark.asyncio
async def test_call_tool_unknown():
    assert TOOL_NAMES == ("application_logs", "process_list", "environment_read")
    with pytest.raises(KeyError):
        await call_tool("nope", {})
