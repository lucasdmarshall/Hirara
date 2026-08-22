"""Toolset schema + health."""

from __future__ import annotations

import pytest

from hirarabrowser.browser import FakeEngine
from hirarabrowser.config import BrowserConfig
from hirarabrowser.session import SessionStore
from hirarabrowser.tools import BROWSER_CLICK_SCHEMA, BROWSER_OPEN_SCHEMA, Toolset


def test_schema_ready():
    assert BROWSER_OPEN_SCHEMA["name"] == "browser_open"
    props = BROWSER_OPEN_SCHEMA["input_schema"]["properties"]
    assert {"url", "session_id", "timeout", "include_text"} <= set(props)
    assert "url" in BROWSER_OPEN_SCHEMA["input_schema"]["required"]

    assert BROWSER_CLICK_SCHEMA["name"] == "browser_click"
    cprops = BROWSER_CLICK_SCHEMA["input_schema"]["properties"]
    assert {"session_id", "selector", "timeout", "button", "click_count"} <= set(cprops)


@pytest.mark.asyncio
async def test_toolset_open_and_click(monkeypatch):
    monkeypatch.setattr(
        "hirarabrowser.browser.resolve_target",
        lambda url, **kw: object(),
    )
    ts = Toolset(
        config=BrowserConfig(),
        store=SessionStore(max_sessions=2, session_ttl=60),
        engine=FakeEngine(title="Hi"),
    )
    r = await ts.browser_open(url="https://example.com/")
    assert r["error"] is None
    assert r["title"] == "Hi"
    assert r["session_id"]

    c = await ts.browser_click(session_id=r["session_id"], selector="button.submit")
    assert c["error"] is None
    assert c["clicked"] is True
    assert c["selector"] == "button.submit"


@pytest.mark.asyncio
async def test_health():
    ts = Toolset(
        config=BrowserConfig(),
        store=SessionStore(max_sessions=2, session_ttl=60),
        engine=FakeEngine(),
    )
    h = ts.health()
    assert h["status"] == "ok"
    assert h["tools"] == ["browser_open", "browser_click"]
