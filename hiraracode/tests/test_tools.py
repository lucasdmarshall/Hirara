"""Tests for the Hiraracode tool layer — schema, envelopes, error handling."""

from __future__ import annotations

import pytest

from hiraracode.config import ExecConfig
from hiraracode.runner import RunnerError
from hiraracode.tools import Toolset


def _toolset_with(client) -> Toolset:
    ts = Toolset(config=ExecConfig())
    ts.runner._client = client  # inject the fake daemon
    return ts


def test_schema_is_agent_ready():
    ts = Toolset(config=ExecConfig())
    schema = ts.schemas()[0]
    assert schema["name"] == "execute_code"
    props = schema["input_schema"]["properties"]
    assert set(schema["input_schema"]["required"]) == {"language", "code"}
    assert "python" in props["language"]["enum"]
    assert "stdin" in props and "timeout" in props


def test_schema_enum_follows_configured_languages(monkeypatch):
    monkeypatch.setenv(
        "CCODE_IMAGES",
        '{"go": {"image": "golang:1.22-alpine", "cmd": ["go", "run", "/workspace/main.go"], "filename": "main.go"}}',
    )
    ts = Toolset(config=ExecConfig.from_env())
    langs = ts.schemas()[0]["input_schema"]["properties"]["language"]["enum"]
    assert "go" in langs
    assert "python" in langs  # defaults are kept


@pytest.mark.asyncio
async def test_execute_returns_envelope(make_client):
    ts = _toolset_with(make_client(stdout=b"42\n", exit_code=0))
    result = await ts.execute(language="python", code="print(42)")
    assert result["error"] is None
    assert result["stdout"] == "42\n"
    assert result["exit_code"] == 0
    assert set(result) >= {
        "stdout",
        "stderr",
        "exit_code",
        "timed_out",
        "oom_killed",
        "duration",
        "truncated",
        "language",
        "image",
        "error",
    }


@pytest.mark.asyncio
async def test_execute_bad_language_is_error_envelope(make_client):
    ts = _toolset_with(make_client())
    result = await ts.execute(language="cobol", code="x")
    assert result["stdout"] is None
    assert result["error"]
    assert "not allowed" in result["error"]


@pytest.mark.asyncio
async def test_execute_surfaces_runner_error(make_client, monkeypatch):
    ts = _toolset_with(make_client())

    def boom(**kwargs):
        raise RunnerError("cannot reach the Docker daemon: nope")

    monkeypatch.setattr(ts.runner, "run", boom)
    result = await ts.execute(language="python", code="print(1)")
    assert result["error"]
    assert "Docker daemon" in result["error"]


def test_health_reports_runner_state(make_client):
    ts = _toolset_with(make_client())
    health = ts.health()
    assert health["status"] == "ok"
    assert health["runner"]["docker_reachable"] is True
    assert "python" in health["runner"]["languages"]
    assert health["runner"]["network"] == "disabled"


async def test_local_backend_contract():
    from hiraracode import tools

    assert tools.TOOL_NAMES == ("execute_code", "job_start", "job_status", "job_stop")
    assert [s["name"] for s in tools.tool_schemas()] == list(tools.TOOL_NAMES)
    with pytest.raises(KeyError):
        await tools.call_tool("nope", {})
