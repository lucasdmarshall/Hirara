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


@pytest.mark.asyncio
async def test_click_happy_path(monkeypatch):
    from hirarabrowser.browser import browser_click

    monkeypatch.setattr(
        "hirarabrowser.browser.resolve_target",
        lambda url, **kw: object(),
    )
    engine = FakeEngine()
    store = SessionStore(max_sessions=4, session_ttl=60)
    opened = await browser_open(
        "https://example.com/",
        store=store,
        engine=engine,
        config=BrowserConfig(),
    )
    r = await browser_click(
        opened.session_id,
        "a#more",
        store=store,
        config=BrowserConfig(),
    )
    assert r.error is None
    assert r.clicked is True
    assert r.selector == "a#more"
    assert r.url.endswith("/clicked")
    assert engine.clicks == ["a#more"]


@pytest.mark.asyncio
async def test_click_requires_session_and_selector():
    from hirarabrowser.browser import browser_click

    r = await browser_click("", "a")
    assert r.error and "session_id" in r.error
    r2 = await browser_click("abc", "")
    assert r2.error and "selector" in r2.error


@pytest.mark.asyncio
async def test_click_unknown_session():
    from hirarabrowser.browser import browser_click

    r = await browser_click(
        "missing",
        "button",
        store=SessionStore(max_sessions=2, session_ttl=60),
    )
    assert r.error and "unknown session" in r.error


@pytest.mark.asyncio
async def test_type_happy_path(monkeypatch):
    from hirarabrowser.browser import browser_type

    monkeypatch.setattr(
        "hirarabrowser.browser.resolve_target",
        lambda url, **kw: object(),
    )
    engine = FakeEngine()
    store = SessionStore(max_sessions=4, session_ttl=60)
    opened = await browser_open(
        "https://example.com/",
        store=store,
        engine=engine,
        config=BrowserConfig(),
    )
    r = await browser_type(
        opened.session_id,
        "input[name=q]",
        "hello",
        store=store,
        config=BrowserConfig(),
    )
    assert r.error is None
    assert r.typed is True
    assert r.cleared is True
    assert r.text == "hello"
    assert engine.typed == [("input[name=q]", "hello", True)]


@pytest.mark.asyncio
async def test_type_append_without_clear(monkeypatch):
    from hirarabrowser.browser import browser_type

    monkeypatch.setattr(
        "hirarabrowser.browser.resolve_target",
        lambda url, **kw: object(),
    )
    engine = FakeEngine()
    store = SessionStore(max_sessions=4, session_ttl=60)
    opened = await browser_open(
        "https://example.com/",
        store=store,
        engine=engine,
        config=BrowserConfig(),
    )
    r = await browser_type(
        opened.session_id,
        "#q",
        "world",
        clear=False,
        store=store,
        config=BrowserConfig(),
    )
    assert r.error is None
    assert r.cleared is False
    assert engine.typed == [("#q", "world", False)]


@pytest.mark.asyncio
async def test_type_requires_fields():
    from hirarabrowser.browser import browser_type

    r = await browser_type("", "input", "x")
    assert r.error and "session_id" in r.error
    r2 = await browser_type("abc", "", "x")
    assert r2.error and "selector" in r2.error


@pytest.mark.asyncio
async def test_screenshot_happy_path(monkeypatch):
    import base64

    from hirarabrowser.browser import browser_screenshot

    monkeypatch.setattr(
        "hirarabrowser.browser.resolve_target",
        lambda url, **kw: object(),
    )
    engine = FakeEngine(title="Shot")
    store = SessionStore(max_sessions=4, session_ttl=60)
    opened = await browser_open(
        "https://example.com/",
        store=store,
        engine=engine,
        config=BrowserConfig(),
    )
    r = await browser_screenshot(
        opened.session_id,
        store=store,
        config=BrowserConfig(),
    )
    assert r.error is None
    assert r.truncated is False
    assert r.mime_type == "image/png"
    assert r.byte_count and r.byte_count > 0
    assert base64.b64decode(r.image_base64)
    assert engine.screenshots
    assert engine.screenshots[0]["type"] == "png"


@pytest.mark.asyncio
async def test_screenshot_selector(monkeypatch):
    from hirarabrowser.browser import browser_screenshot

    monkeypatch.setattr(
        "hirarabrowser.browser.resolve_target",
        lambda url, **kw: object(),
    )
    engine = FakeEngine()
    store = SessionStore(max_sessions=4, session_ttl=60)
    opened = await browser_open(
        "https://example.com/",
        store=store,
        engine=engine,
        config=BrowserConfig(),
    )
    r = await browser_screenshot(
        opened.session_id,
        selector="#hero",
        store=store,
        config=BrowserConfig(),
    )
    assert r.error is None
    assert r.selector == "#hero"
    assert r.full_page is False
    assert any(s.get("selector") == "#hero" for s in engine.screenshots)


@pytest.mark.asyncio
async def test_screenshot_unknown_session():
    from hirarabrowser.browser import browser_screenshot

    r = await browser_screenshot(
        "missing",
        store=SessionStore(max_sessions=2, session_ttl=60),
    )
    assert r.error and "unknown session" in r.error


@pytest.mark.asyncio
async def test_screenshot_bad_format(monkeypatch):
    from hirarabrowser.browser import browser_screenshot

    monkeypatch.setattr(
        "hirarabrowser.browser.resolve_target",
        lambda url, **kw: object(),
    )
    engine = FakeEngine()
    store = SessionStore(max_sessions=4, session_ttl=60)
    opened = await browser_open(
        "https://example.com/",
        store=store,
        engine=engine,
        config=BrowserConfig(),
    )
    r = await browser_screenshot(
        opened.session_id,
        image_format="gif",
        store=store,
        config=BrowserConfig(),
    )
    assert r.error and "unsupported" in r.error
