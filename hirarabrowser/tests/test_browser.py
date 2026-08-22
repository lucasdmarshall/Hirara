"""browser_open — FakeEngine, no Chromium required."""

from __future__ import annotations

import pytest

from hirara_core import BlockedURL

from hirarabrowser.browser import FakeEngine, browser_open
from hirarabrowser.config import BrowserConfig
from hirarabrowser.session import SessionStore


@pytest.mark.asyncio
async def test_open_happy_path(monkeypatch):
    monkeypatch.setattr(
        "hirarabrowser.browser.resolve_target",
        lambda url, **kw: object(),
    )
    engine = FakeEngine(title="Example Domain", text="Example Domain")
    store = SessionStore(max_sessions=4, session_ttl=60)
    r = await browser_open(
        "https://example.com/",
        include_text=True,
        config=BrowserConfig(allow_private_urls=True),
        store=store,
        engine=engine,
    )
    assert r.error is None
    assert r.session_id
    assert r.title == "Example Domain"
    assert r.url == "https://example.com/"
    assert r.status == 200
    assert r.text == "Example Domain"
    assert engine.opened == ["https://example.com/"]
    assert len(store) == 1


@pytest.mark.asyncio
async def test_open_rejects_empty_url():
    r = await browser_open("")
    assert r.error and "required" in r.error


@pytest.mark.asyncio
async def test_open_blocks_private_when_disallowed(monkeypatch):
    def _block(url, **kw):
        raise BlockedURL("127.0.0.1 is not globally routable")

    monkeypatch.setattr("hirarabrowser.browser.resolve_target", _block)
    r = await browser_open(
        "http://127.0.0.1/",
        config=BrowserConfig(allow_private_urls=False),
        engine=FakeEngine(),
        store=SessionStore(max_sessions=2, session_ttl=60),
    )
    assert r.error and "blocked" in r.error


@pytest.mark.asyncio
async def test_reuse_session_navigates(monkeypatch):
    monkeypatch.setattr(
        "hirarabrowser.browser.resolve_target",
        lambda url, **kw: object(),
    )
    engine = FakeEngine(title="One")
    store = SessionStore(max_sessions=4, session_ttl=60)
    first = await browser_open(
        "https://example.com/",
        store=store,
        engine=engine,
        config=BrowserConfig(),
    )
    engine.title = "Two"
    # Fake page keeps its own title; update via goto path — FakeEngine page
    # title is fixed at creation. For reuse we just check session_id + url.
    second = await browser_open(
        "https://example.org/",
        session_id=first.session_id,
        store=store,
        engine=engine,
        config=BrowserConfig(),
    )
    assert second.error is None
    assert second.session_id == first.session_id
    assert second.url == "https://example.org/"
    assert len(store) == 1


@pytest.mark.asyncio
async def test_unknown_session(monkeypatch):
    monkeypatch.setattr(
        "hirarabrowser.browser.resolve_target",
        lambda url, **kw: object(),
    )
    r = await browser_open(
        "https://example.com/",
        session_id="does-not-exist",
        store=SessionStore(max_sessions=2, session_ttl=60),
        engine=FakeEngine(),
        config=BrowserConfig(),
    )
    assert r.error and "unknown session" in r.error
