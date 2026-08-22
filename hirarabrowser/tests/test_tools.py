"""Toolset schema + health."""

from __future__ import annotations

import pytest

from hirarabrowser.browser import FakeEngine
from hirarabrowser.config import BrowserConfig
from hirarabrowser.session import SessionStore
from hirarabrowser.tools import (
    BROWSER_CLICK_SCHEMA,
    BROWSER_OPEN_SCHEMA,
    BROWSER_SCREENSHOT_SCHEMA,
    BROWSER_TYPE_SCHEMA,
    Toolset,
)


def test_schema_ready():
    assert BROWSER_OPEN_SCHEMA["name"] == "browser_open"
    props = BROWSER_OPEN_SCHEMA["input_schema"]["properties"]
    assert {"url", "session_id", "timeout", "include_text"} <= set(props)

    assert BROWSER_CLICK_SCHEMA["name"] == "browser_click"
    cprops = BROWSER_CLICK_SCHEMA["input_schema"]["properties"]
    assert {"session_id", "selector", "timeout", "button", "click_count"} <= set(cprops)

    assert BROWSER_TYPE_SCHEMA["name"] == "browser_type"
    tprops = BROWSER_TYPE_SCHEMA["input_schema"]["properties"]
    assert {"session_id", "selector", "text", "clear", "press_enter"} <= set(tprops)

    assert BROWSER_SCREENSHOT_SCHEMA["name"] == "browser_screenshot"
    sprops = BROWSER_SCREENSHOT_SCHEMA["input_schema"]["properties"]
    assert {"session_id", "full_page", "selector", "image_format", "quality"} <= set(
        sprops
    )


@pytest.mark.asyncio
async def test_toolset_open_click_type_screenshot(monkeypatch):
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
    sid = r["session_id"]

    c = await ts.browser_click(session_id=sid, selector="button.submit")
    assert c["clicked"] is True

    t = await ts.browser_type(session_id=sid, selector="input#q", text="search")
    assert t["typed"] is True
    assert t["text"] == "search"
    assert t["cleared"] is True

    s = await ts.browser_screenshot(session_id=sid, full_page=True)
    assert s["error"] is None
    assert s["mime_type"] == "image/png"
    assert s["image_base64"]
    assert s["full_page"] is True


@pytest.mark.asyncio
async def test_health():
    ts = Toolset(
        config=BrowserConfig(),
        store=SessionStore(max_sessions=2, session_ttl=60),
        engine=FakeEngine(),
    )
    h = ts.health()
    assert h["status"] == "ok"
    assert h["tools"] == [
        "browser_open",
        "browser_click",
        "browser_type",
        "browser_screenshot",
    ]
