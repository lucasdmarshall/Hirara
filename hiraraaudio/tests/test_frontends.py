"""HTTP service and MCP server wiring."""

from __future__ import annotations

import json

import pytest

from hiraraaudio import tools

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from hiraraaudio.service import REQUESTS, app  # noqa: E402

client = TestClient(app)


def test_every_tool_has_an_endpoint_and_request_model():
    assert set(REQUESTS) == set(tools.TOOL_NAMES)
    routes = {r.path for r in app.routes}
    for name in tools.TOOL_NAMES:
        assert f"/{name}" in routes


def test_health_and_schemas():
    assert client.get("/health").json()["tools"] == list(tools.TOOL_NAMES)
    assert [t["name"] for t in client.get("/schemas").json()["tools"]] == list(tools.TOOL_NAMES)


def test_json_call_and_unknown_field(media):
    r = client.post("/audio_profile", json={"audio_path": str(media["mix"])})
    assert r.status_code == 200 and r.json()["error"] is None
    assert client.post("/audio_profile", json={"audio_pth": "x"}).status_code == 422


def test_upload(media):
    r = client.post(
        "/upload/audio_check",
        files={"file": ("hum.wav", media["hum"].read_bytes(), "audio/wav")},
        data={"arguments": json.dumps({"preset": "podcast"})},
    ).json()
    assert r["error"] is None and r["source"] == "hum.wav"
    r = client.post("/upload/audio_sonify", files={"file": ("x.wav", b"x")}).json()
    assert "does not take" in r["error"]
    r = client.post("/upload/audio_info", files={"file": ("x.wav", b"x")},
                    data={"arguments": "["}).json()
    assert "not valid JSON" in r["error"]


async def test_mcp_lists_every_tool():
    mcp = pytest.importorskip("mcp")
    del mcp
    from hiraraaudio import mcp_server

    listed = await mcp_server.server.list_tools()
    assert sorted(t.name for t in listed) == sorted(tools.TOOL_NAMES)
