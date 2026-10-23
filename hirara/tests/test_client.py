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
        c.call("execute_code", {"language": "python", "code": "print(1)"})


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
