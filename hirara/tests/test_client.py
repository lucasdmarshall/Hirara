"""Client behaviour against a mock hub (httpx MockTransport)."""

from __future__ import annotations

import base64

import httpx
import pytest

from hirara import Client, HiraraError, HiraraToolError
from hirara._local import LocalBackends

_last: dict = {}

# The local-mode tests need the in-process backends installed
# (pip install hirara[local]); skip them cleanly when they are not.
_HAS_LOCAL = LocalBackends().has("pdf_create")
local_only = pytest.mark.skipif(
    not _HAS_LOCAL, reason="local backends not installed (pip install hirara[local])"
)


def _handler(request: httpx.Request) -> httpx.Response:
    _last["path"] = request.url.path
    _last["auth"] = request.headers.get("authorization")
    if request.url.path == "/call":
        import json

        body = json.loads(request.content)
        _last["name"] = body["name"]
        _last["arguments"] = body["arguments"]
        name = body["name"]
        if name == "boom":
            return httpx.Response(200, json={"error": "blocked URL", "tool": "boom"})
        if name == "web_search":
            return httpx.Response(200, json={"results": ["a", "b"], "error": None})
        return httpx.Response(200, json={"echo": body["arguments"], "error": None})
    if request.url.path == "/schemas":
        return httpx.Response(200, json={"tools": [{"name": "web_search"}], "unavailable": []})
    if request.url.path == "/health":
        return httpx.Response(200, json={"status": "ok"})
    return httpx.Response(404)


def _client(token: str | None = None) -> Client:
    c = Client("http://hub.local", token=token)
    c._client = httpx.Client(
        base_url="http://hub.local",
        transport=httpx.MockTransport(_handler),
        headers={"Authorization": f"Bearer {token}"} if token else {},
    )
    return c


def test_web_search_forwards_arguments():
    c = _client()
    r = c.web_search("rust", max_results=5)
    assert r["results"] == ["a", "b"]
    assert _last["name"] == "web_search"
    assert _last["arguments"] == {"query": "rust", "max_results": 5}


def test_execute_code():
    c = _client()
    c.execute_code("python", "print(1)", stdin="x")
    assert _last["arguments"] == {"language": "python", "code": "print(1)", "stdin": "x"}


def test_pdf_read_from_path_sends_pdf_base64(tmp_path):
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"%PDF-1.4 hello")
    c = _client()
    c.pdf_read(path=str(f))
    assert _last["name"] == "pdf_read"
    assert base64.b64decode(_last["arguments"]["pdf_base64"]) == b"%PDF-1.4 hello"


def test_office_read_from_path_sends_file_base64_and_filename(tmp_path):
    f = tmp_path / "deck.pptx"
    f.write_bytes(b"PK\x03\x04zip")
    c = _client()
    c.office_read(path=str(f))
    assert "file_base64" in _last["arguments"]
    assert _last["arguments"]["filename"] == "deck.pptx"


def test_ocr_read_url_uses_file_url():
    c = _client()
    c.ocr_read(url="https://example.com/a.png", languages=["en"])
    assert _last["arguments"]["file_url"] == "https://example.com/a.png"
    assert _last["arguments"]["languages"] == ["en"]


def test_requires_exactly_one_source(tmp_path):
    c = _client()
    with pytest.raises(ValueError):
        c.pdf_read()
    with pytest.raises(ValueError):
        c.pdf_read(url="x", base64="y")


def test_tool_error_raises():
    c = _client()
    with pytest.raises(HiraraToolError) as exc:
        c.call("boom", {})
    assert exc.value.tool == "boom"
    assert "blocked URL" in exc.value.error


def test_tool_error_can_be_returned():
    c = _client()
    r = c.call("boom", {}, raise_on_error=False)
    assert r["error"] == "blocked URL"


def test_auth_header_sent():
    c = _client(token="secret")
    c.tools()
    assert _last["auth"] == "Bearer secret"


def test_unauthorized_maps_to_hiraraerror():
    def unauth(request):
        return httpx.Response(401, json={"detail": "nope"})

    c = Client("http://hub.local")
    c._client = httpx.Client(base_url="http://hub.local", transport=httpx.MockTransport(unauth))
    with pytest.raises(HiraraError) as exc:
        c.web_search("x")
    assert "unauthorized" in str(exc.value).lower()


def test_discovery():
    c = _client()
    assert c.tools() == [{"name": "web_search"}]
    assert c.health()["status"] == "ok"


# --- local mode ------------------------------------------------------------


def test_auto_prefers_an_explicit_hub_over_local():
    """If the caller named a hub, local-capable tools still go to the hub."""
    c = Client("http://hub.local")  # local defaults to "auto"
    assert c._use_local("pdf_read") is False


def test_auto_uses_local_when_no_hub_is_configured(monkeypatch):
    monkeypatch.delenv("HIRARA_HUB_URL", raising=False)
    c = Client()  # no url, no env → auto should run in-process
    assert c._use_local("pdf_read") is _HAS_LOCAL


def test_local_false_never_uses_local():
    c = Client("http://hub.local", local=False)
    assert c._use_local("pdf_read") is False


def test_local_true_errors_for_a_tool_with_no_backend():
    c = Client(local=True)
    with pytest.raises(HiraraError, match="no in-process backend"):
        c.call("no_such_tool", {})


@local_only
def test_local_mode_runs_pdf_in_process():
    """No hub, no HTTP: pdf_create + pdf_read round-trip in this process."""
    c = Client(local=True)
    made = c.pdf_create("# Title\n\nBody text here.", format="markdown")
    assert made["error"] is None
    assert made["pdf_base64"]

    read = c.pdf_read(base64=made["pdf_base64"])
    assert read["error"] is None
    assert "Title" in (read["text"] or "")


@local_only
def test_local_tool_error_still_raises():
    """A local tool that reports an error raises HiraraToolError, like the hub."""
    c = Client(local=True)
    with pytest.raises(HiraraToolError):
        c.pdf_read(base64="not-valid-base64-@@@")


@local_only
def test_local_tools_listing_includes_backends():
    c = Client(local=True)
    names = {t["name"] for t in c.tools()}
    assert {"pdf_read", "web_fetch", "office_read"} <= names


# --- local argument errors ---------------------------------------------------

def _backends_with(module) -> LocalBackends:
    backends = LocalBackends()
    backends._loaded = True
    for name in module.TOOL_NAMES:
        backends._routes[name] = module
    return backends


class _FakeBackend:
    TOOL_NAMES = ("echo", "broken")

    @staticmethod
    async def _echo(*, input: str) -> dict:
        return {"output": input, "error": None}

    @staticmethod
    async def _broken(*, input: str) -> dict:
        return len(None)  # a real bug inside the tool, not bad input

    @staticmethod
    async def call_tool(name, arguments):
        if name == "echo":
            return await _FakeBackend._echo(**arguments)
        return await _FakeBackend._broken(**arguments)


def test_local_missing_argument_is_an_error_envelope():
    result = _backends_with(_FakeBackend).call("echo", {})
    assert result == {"error": "echo: missing 1 required keyword-only argument: 'input'"}


def test_local_unknown_argument_is_an_error_envelope():
    result = _backends_with(_FakeBackend).call("echo", {"input": "x", "nope": 1})
    assert "unexpected keyword argument 'nope'" in result["error"]


def test_local_type_error_inside_a_tool_still_raises():
    with pytest.raises(TypeError):
        _backends_with(_FakeBackend).call("broken", {"input": "x"})


@pytest.mark.parametrize(
    ("tool", "missing"),
    [("decode", "input"), ("file_read", "path"), ("dns_lookup", "name"), ("web_fetch", "url")],
)
def test_real_backends_report_missing_arguments(tool, missing):
    backends = LocalBackends()
    if not backends.has(tool):
        pytest.skip(f"{tool} backend not installed")
    result = backends.call(tool, {})
    assert result["error"].startswith(f"{tool}: missing")
    assert f"'{missing}'" in result["error"]


# --- SDK / hub alignment -----------------------------------------------------

def test_transcribe_from_path_sends_audio_base64_and_filename(tmp_path):
    f = tmp_path / "memo.m4a"
    f.write_bytes(b"audio")
    c = _client()
    c.transcribe(path=str(f), language="en")
    assert _last["name"] == "transcribe"
    assert _last["arguments"] == {
        "audio_base64": base64.b64encode(b"audio").decode(),
        "filename": "memo.m4a",
        "language": "en",
    }


def test_every_hub_tool_has_an_sdk_method_and_module_function():
    """A tool the hub routes but the SDK lacks is unreachable as hirara.<tool>()."""
    registry = pytest.importorskip("hirara_hub.registry")
    import hirara

    for name in registry.TOOLS:
        assert callable(getattr(Client, name, None)), f"Client.{name} is missing"
        assert callable(getattr(hirara, name, None)), f"hirara.{name} is missing"
        assert name in hirara.__all__, f"{name} is not exported from hirara"


# --- audio (hiraraaudio) -------------------------------------------------------

def test_audio_profile_sends_base64_and_filename(tmp_path):
    f = tmp_path / "ep.mp3"
    f.write_bytes(b"mp3")
    c = _client()
    c.audio_profile(path=str(f), max_segments=10)
    assert _last["name"] == "audio_profile"
    assert _last["arguments"] == {
        "audio_base64": base64.b64encode(b"mp3").decode(),
        "filename": "ep.mp3",
        "max_segments": 10,
    }


def test_audio_compare_and_find_sources(tmp_path):
    a, b = tmp_path / "a.wav", tmp_path / "b.wav"
    a.write_bytes(b"A")
    b.write_bytes(b"B")
    c = _client()
    c.audio_compare(a_path=str(a), b_url="https://x/b.wav")
    assert _last["arguments"] == {"a_base64": base64.b64encode(b"A").decode(),
                                  "b_url": "https://x/b.wav"}
    c.audio_find(url="https://x/long.mp3", clip_start=3.0, clip_end=6.0)
    assert _last["arguments"] == {"audio_url": "https://x/long.mp3", "clip_start": 3.0,
                                  "clip_end": 6.0}


def test_audio_fingerprint_speak_sonify_watch():
    c = _client()
    c.audio_fingerprint(["/data/a.mp3", "/data/b.mp3"])
    assert _last["arguments"] == {"audio_paths": ["/data/a.mp3", "/data/b.mp3"]}
    c.audio_speak("hello", voice="en-us")
    assert _last["arguments"] == {"text": "hello", "voice": "en-us"}
    c.audio_sonify([1, None, 3], duration=2)
    assert _last["arguments"] == {"values": [1, None, 3], "duration": 2}
    c.audio_watch("poll", watch_id="abc", cursor=4)
    assert _last["arguments"] == {"action": "poll", "watch_id": "abc", "cursor": 4}


# --- agent essentials (fs, util, http, code, reader, data, media, agent) --------------

def test_file_and_time_tools_forward_arguments():
    c = _client()
    c.file_edit("/w/a.py", "old", "new", replace_all=True)
    assert _last["arguments"] == {"path": "/w/a.py", "old_string": "old", "new_string": "new",
                                  "replace_all": True}
    c.file_list()
    assert _last["arguments"] == {}
    c.archive_extract("/w/x.zip", "/w/out")
    assert _last["arguments"] == {"path": "/w/x.zip", "dest": "/w/out"}
    c.time_now(["Asia/Yangon"])
    assert _last["arguments"] == {"timezones": ["Asia/Yangon"]}
    c.schema_validate({"a": 1}, {"type": "object"})
    assert _last["arguments"] == {"instance": {"a": 1}, "schema": {"type": "object"}}


def test_web_watch_and_jobs():
    c = _client()
    c.web_watch("https://example.com", selector="#price")
    assert _last["name"] == "web_watch"
    assert _last["arguments"] == {"action": "check", "url": "https://example.com",
                                  "selector": "#price"}
    c.job_start("python", "print(1)", timeout=60)
    assert _last["arguments"] == {"language": "python", "code": "print(1)", "timeout": 60}
    c.job_status()
    assert _last["arguments"] == {}


def test_file_sources_for_email_data_and_media(tmp_path):
    f = tmp_path / "m.eml"
    f.write_bytes(b"EML")
    c = _client()
    c.email_read(path=str(f))
    assert _last["arguments"] == {"file_base64": base64.b64encode(b"EML").decode(),
                                  "filename": "m.eml"}
    c.data_profile(data="a,b\n1,2\n")
    assert _last["arguments"] == {"data": "a,b\n1,2\n"}
    c.image_compare(a_url="https://x/a.png", b_url="https://x/b.png", threshold=0.2)
    assert _last["arguments"] == {"a_url": "https://x/a.png", "b_url": "https://x/b.png",
                                  "threshold": 0.2}


def test_agent_state_tools():
    c = _client()
    c.memory("set", key="k", value={"x": 1})
    assert _last["arguments"] == {"action": "set", "key": "k", "value": {"x": 1}}
    c.ask_human("ask", question="Deploy?", kind="approval")
    assert _last["arguments"] == {"action": "ask", "question": "Deploy?", "kind": "approval"}
    c.wait_until(request_id="abc", max_wait=30)
    assert _last["arguments"] == {"request_id": "abc", "max_wait": 30}


def test_stateful_local_backends_keep_their_event_loop():
    import asyncio
    from hirara._local import _run
    async def state():
        return asyncio.get_running_loop(), asyncio.create_task(asyncio.sleep(30))
    loop, task = _run(state())
    async def reuse():
        assert asyncio.get_running_loop() is loop
        assert not task.cancelled() and not task.done()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    _run(reuse())
