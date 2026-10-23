"""audio_watch, plus the local-backend contract and config."""

from __future__ import annotations

import asyncio
import time

import numpy as np
import pytest

from hiraraaudio import tools
from hiraraaudio.config import AudioConfig
from hiraraaudio.tools import Toolset
from hiraraaudio.watch import Analyzer, Settings, Watch


async def _poll_until_done(ts: Toolset, watch_id: str, timeout: float = 20.0) -> dict:
    deadline = time.monotonic() + timeout
    events, cursor = [], 0
    while time.monotonic() < deadline:
        r = await ts.audio_watch(action="poll", watch_id=watch_id, cursor=cursor)
        events += r["events"]
        cursor = r["cursor"]
        if r["status"] not in ("starting", "running"):
            r["all_events"] = events
            return r
        await asyncio.sleep(0.1)
    raise AssertionError("watch did not finish")


async def test_watch_file_reports_dead_air_and_end(toolset, media):
    r = await toolset.audio_watch(action="start", audio_path=str(media["speech"]), dead_air_s=2.0)
    assert r["error"] is None and r["watch_id"]
    done = await _poll_until_done(toolset, r["watch_id"])
    types = [e["type"] for e in done["all_events"]]
    assert done["status"] == "ended"
    assert types.count("dead_air") == 2
    assert types.count("audio_resumed") == 2
    assert types[-1] == "stream_ended"
    seqs = [e["seq"] for e in done["all_events"]]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)


async def test_watch_reports_dtmf_and_beep(toolset, media):
    r = await toolset.audio_watch(action="start", audio_path=str(media["dtmf"]))
    done = await _poll_until_done(toolset, r["watch_id"])
    digits = "".join(e["digit"] for e in done["all_events"] if e["type"] == "dtmf")
    assert digits == "4205#"
    assert any(e["type"] == "beep" and abs(e["freq_hz"] - 1000) < 15 for e in done["all_events"])


async def test_watch_stop_and_list(toolset, media):
    r = await toolset.audio_watch(action="start", audio_path=str(media["mix"]), realtime=True)
    wid = r["watch_id"]
    listed = await toolset.audio_watch(action="list")
    assert any(w["watch_id"] == wid for w in listed["watches"])
    stopped = await toolset.audio_watch(action="stop", watch_id=wid)
    assert stopped["status"] == "stopped"


async def test_watch_errors(toolset, media):
    r = await toolset.audio_watch(action="poll", watch_id="nope")
    assert "unknown watch_id" in r["error"]
    r = await toolset.audio_watch(action="start")
    assert "exactly one" in r["error"]
    r = await toolset.audio_watch(action="start", stream_url="http://127.0.0.1/live")
    assert "blocked" in r["error"]
    r = await toolset.audio_watch(action="dance")
    assert "action must be" in r["error"]


async def test_watch_limit(media):
    ts = Toolset(AudioConfig(max_watchers=1))
    first = await ts.audio_watch(action="start", audio_path=str(media["mix"]), realtime=True)
    second = await ts.audio_watch(action="start", audio_path=str(media["mix"]), realtime=True)
    assert "HA_MAX_WATCHERS" in second["error"]
    await ts.audio_watch(action="stop", watch_id=first["watch_id"])


def test_analyzer_level_spike():
    w = Watch(id="t", source="test", settings=Settings())
    a = Analyzer(w)
    quiet = 0.01 * np.sin(np.arange(1600) / 5)
    for _ in range(30):
        a.feed(quiet.astype(np.float32))
    a.feed((quiet * 40).astype(np.float32))
    assert [e["type"] for e in w.events] == ["level_spike"]


def test_backend_contract():
    assert len(tools.TOOL_NAMES) == 14
    assert [s["name"] for s in tools.tool_schemas()] == list(tools.TOOL_NAMES)
    for schema in tools.tool_schemas():
        assert schema["input_schema"]["additionalProperties"] is False
        assert schema["description"]
        method = getattr(Toolset, schema["name"])
        assert callable(method)


async def test_call_tool_dispatch(media):
    r = await tools.call_tool("audio_info", {"audio_path": str(media["dtmf"])})
    assert r["sample_rate"] == 8000
    with pytest.raises(KeyError):
        await tools.call_tool("nope", {})


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("HA_ALLOW_LOCAL_PATH", "false")
    monkeypatch.setenv("HA_MAX_BYTES", "1234")
    monkeypatch.setenv("HA_FFMPEG", "/opt/ffmpeg")
    cfg = AudioConfig.from_env()
    assert cfg.allow_local_path is False
    assert cfg.max_bytes == 1234
    assert cfg.ffmpeg == "/opt/ffmpeg"


def test_health(toolset):
    h = toolset.health()
    assert h["status"] == "ok"
    assert h["tools"] == list(tools.TOOL_NAMES)
