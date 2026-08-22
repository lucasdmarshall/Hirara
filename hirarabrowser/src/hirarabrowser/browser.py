"""Browser open — navigate a URL in a managed Playwright session.

``BrowserEngine`` is injectable so unit tests never need a real Chromium.
Production uses Playwright Chromium (headless by default).

URLs are cleared through ``hirara_core.resolve_target`` before navigation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit

from hirara_core import BlockedURL, resolve_target

from .config import BrowserConfig
from .session import Session, SessionStore

log = logging.getLogger(__name__)


class BrowserError(ValueError):
    """Caller-facing browser tool failure."""


@dataclass
class OpenResult:
    session_id: str | None = None
    url: str | None = None
    title: str | None = None
    status: int | None = None
    text: str | None = None
    truncated: bool = False
    error: str | None = None


@dataclass
class ClickResult:
    session_id: str | None = None
    selector: str | None = None
    url: str | None = None
    title: str | None = None
    clicked: bool = False
    error: str | None = None


@dataclass
class TypeResult:
    session_id: str | None = None
    selector: str | None = None
    text: str | None = None
    cleared: bool = False
    url: str | None = None
    title: str | None = None
    typed: bool = False
    error: str | None = None


class BrowserEngine(Protocol):
    async def open_page(self, url: str, *, timeout: float) -> tuple[Any, Any, Any, int | None]:
        """Return (browser, context, page, http_status)."""
        ...

    async def close_session(self, session: Session) -> None: ...


class FakeEngine:
    """In-memory engine for tests."""

    def __init__(
        self, *, title: str = "Example", status: int = 200, text: str = "hello"
    ) -> None:
        self.title = title
        self.status = status
        self.text = text
        self.opened: list[str] = []
        self.closed: list[str] = []
        self.clicks: list[str] = []
        self.typed: list[tuple[str, str, bool]] = []

    async def open_page(self, url: str, *, timeout: float) -> tuple[Any, Any, Any, int | None]:
        self.opened.append(url)
        engine = self

        class _Resp:
            def __init__(self, status: int) -> None:
                self.status = status

        class _Page:
            def __init__(self, title: str, text: str, url: str, status: int) -> None:
                self._title = title
                self._text = text
                self.url = url
                self._status = status
                self._values: dict[str, str] = {}

            async def title(self) -> str:
                return self._title

            async def inner_text(self, selector: str) -> str:
                return self._text

            async def goto(self, url: str, **kwargs):
                self.url = url
                return _Resp(self._status)

            async def click(self, selector: str, **kwargs):
                engine.clicks.append(selector)
                self.url = self.url.rstrip("/") + "/clicked"
                self._title = "Clicked"

            async def wait_for_selector(self, selector: str, **kwargs):
                return None

            async def fill(self, selector: str, value: str, **kwargs):
                self._values[selector] = value
                engine.typed.append((selector, value, True))

            async def type(self, selector: str, text: str, **kwargs):
                prev = self._values.get(selector, "")
                self._values[selector] = prev + text
                engine.typed.append((selector, text, False))

        page = _Page(self.title, self.text, url, self.status)
        return object(), object(), page, self.status

    async def close_session(self, session: Session) -> None:
        self.closed.append(session.session_id)


class PlaywrightEngine:
    """Real Playwright Chromium/Firefox/WebKit engine."""

    def __init__(self, config: BrowserConfig) -> None:
        self.config = config
        self._playwright = None

    async def _ensure(self):
        if self._playwright is None:
            from playwright.async_api import async_playwright

            self._playwright = await async_playwright().start()
        return self._playwright

    async def open_page(self, url: str, *, timeout: float) -> tuple[Any, Any, Any, int | None]:
        pw = await self._ensure()
        launcher = getattr(pw, self.config.browser_channel)
        browser = await launcher.launch(headless=self.config.headless)
        context = await browser.new_context()
        page = await context.new_page()
        response = await page.goto(
            url, wait_until="domcontentloaded", timeout=int(timeout * 1000)
        )
        status = response.status if response is not None else None
        return browser, context, page, status

    async def close_session(self, session: Session) -> None:
        for obj in (session.page, session.context, session.browser):
            if obj is None:
                continue
            close = getattr(obj, "close", None)
            if callable(close):
                try:
                    await close()
                except Exception:  # noqa: BLE001
                    pass


def _validate_url(url: str, *, allow_private: bool) -> str:
    cleaned = (url or "").strip()
    if not cleaned:
        raise BrowserError("url is required")
    parts = urlsplit(cleaned)
    if parts.scheme not in {"http", "https"}:
        raise BrowserError(f"scheme {parts.scheme!r} is not allowed")
    if not parts.hostname:
        raise BrowserError("url has no host")
    try:
        resolve_target(cleaned, allow_private_ips=allow_private)
    except BlockedURL as exc:
        raise BrowserError(f"url blocked: {exc}") from exc
    return cleaned


async def browser_open(
    url: str,
    *,
    session_id: str | None = None,
    timeout: float | None = None,
    include_text: bool = False,
    config: BrowserConfig | None = None,
    store: SessionStore | None = None,
    engine: BrowserEngine | None = None,
) -> OpenResult:
    """Open ``url`` in a browser session and return page metadata."""
    cfg = config or BrowserConfig()
    sessions = store if store is not None else SessionStore(
        max_sessions=cfg.max_sessions, session_ttl=cfg.session_ttl
    )
    eng = engine or PlaywrightEngine(cfg)

    try:
        target = _validate_url(url, allow_private=cfg.allow_private_urls)
    except BrowserError as exc:
        return OpenResult(error=str(exc))

    nav_timeout = cfg.nav_timeout if timeout is None else float(timeout)
    if nav_timeout <= 0:
        return OpenResult(error="timeout must be > 0")

    # Reuse session if provided: navigate existing page.
    if session_id:
        session = sessions.get(session_id)
        if session is None:
            return OpenResult(error=f"unknown session_id: {session_id}")
        try:
            page = session.page
            response = await page.goto(
                target, wait_until="domcontentloaded", timeout=int(nav_timeout * 1000)
            )
            status = response.status if response is not None else None
            title = await page.title()
            text = None
            truncated = False
            if include_text:
                text = await page.inner_text("body")
                if len(text) > cfg.max_text_chars:
                    text = text[: cfg.max_text_chars]
                    truncated = True
            session.url = page.url
            session.title = title
            return OpenResult(
                session_id=session.session_id,
                url=page.url,
                title=title,
                status=status,
                text=text,
                truncated=truncated,
            )
        except Exception as exc:  # noqa: BLE001
            return OpenResult(session_id=session_id, error=f"navigation failed: {exc}")

    try:
        browser, context, page, status = await eng.open_page(target, timeout=nav_timeout)
        title = await page.title()
        final_url = getattr(page, "url", target)
        text = None
        truncated = False
        if include_text:
            text = await page.inner_text("body")
            if len(text) > cfg.max_text_chars:
                text = text[: cfg.max_text_chars]
                truncated = True
        session = sessions.create(
            page=page,
            browser=browser,
            context=context,
            url=final_url,
            title=title,
        )
        return OpenResult(
            session_id=session.session_id,
            url=final_url,
            title=title,
            status=status,
            text=text,
            truncated=truncated,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("browser_open failed")
        return OpenResult(error=f"browser_open failed: {exc}")


def open_result_to_dict(result: OpenResult) -> dict:
    return {
        "session_id": result.session_id,
        "url": result.url,
        "title": result.title,
        "status": result.status,
        "text": result.text,
        "truncated": result.truncated,
        "error": result.error,
    }


async def browser_click(
    session_id: str,
    selector: str,
    *,
    timeout: float | None = None,
    button: str = "left",
    click_count: int = 1,
    config: BrowserConfig | None = None,
    store: SessionStore | None = None,
) -> ClickResult:
    """Click ``selector`` in an existing browser session."""
    cfg = config or BrowserConfig()
    sessions = store if store is not None else SessionStore(
        max_sessions=cfg.max_sessions, session_ttl=cfg.session_ttl
    )

    sid = (session_id or "").strip()
    sel = (selector or "").strip()
    if not sid:
        return ClickResult(error="session_id is required")
    if not sel:
        return ClickResult(session_id=sid or None, error="selector is required")
    if button not in {"left", "right", "middle"}:
        return ClickResult(session_id=sid, selector=sel, error=f"invalid button: {button!r}")
    if click_count < 1 or click_count > 3:
        return ClickResult(
            session_id=sid, selector=sel, error="click_count must be 1..3"
        )

    session = sessions.get(sid)
    if session is None:
        return ClickResult(session_id=sid, selector=sel, error=f"unknown session_id: {sid}")

    wait_timeout = cfg.nav_timeout if timeout is None else float(timeout)
    if wait_timeout <= 0:
        return ClickResult(session_id=sid, selector=sel, error="timeout must be > 0")

    page = session.page
    try:
        wait = getattr(page, "wait_for_selector", None)
        if callable(wait):
            await wait(sel, timeout=int(wait_timeout * 1000), state="visible")
        await page.click(
            sel,
            timeout=int(wait_timeout * 1000),
            button=button,
            click_count=click_count,
        )
        title = await page.title()
        url = getattr(page, "url", session.url)
        session.url = url
        session.title = title
        return ClickResult(
            session_id=sid,
            selector=sel,
            url=url,
            title=title,
            clicked=True,
        )
    except Exception as exc:  # noqa: BLE001
        return ClickResult(
            session_id=sid,
            selector=sel,
            url=getattr(page, "url", session.url),
            title=session.title,
            clicked=False,
            error=f"click failed: {exc}",
        )


def click_result_to_dict(result: ClickResult) -> dict:
    return {
        "session_id": result.session_id,
        "selector": result.selector,
        "url": result.url,
        "title": result.title,
        "clicked": result.clicked,
        "error": result.error,
    }


async def browser_type(
    session_id: str,
    selector: str,
    text: str,
    *,
    timeout: float | None = None,
    clear: bool = True,
    press_enter: bool = False,
    delay_ms: float | None = None,
    config: BrowserConfig | None = None,
    store: SessionStore | None = None,
) -> TypeResult:
    """Type ``text`` into ``selector`` in an existing browser session.

    When ``clear`` is true (default), uses Playwright ``fill`` (replace).
    When false, uses ``type`` (append keystrokes). Optional ``press_enter``
    sends Enter afterward.
    """
    cfg = config or BrowserConfig()
    sessions = store if store is not None else SessionStore(
        max_sessions=cfg.max_sessions, session_ttl=cfg.session_ttl
    )

    sid = (session_id or "").strip()
    sel = (selector or "").strip()
    if not sid:
        return TypeResult(error="session_id is required")
    if not sel:
        return TypeResult(session_id=sid or None, error="selector is required")
    if text is None:
        return TypeResult(session_id=sid, selector=sel, error="text is required")

    session = sessions.get(sid)
    if session is None:
        return TypeResult(
            session_id=sid, selector=sel, text=text, error=f"unknown session_id: {sid}"
        )

    wait_timeout = cfg.nav_timeout if timeout is None else float(timeout)
    if wait_timeout <= 0:
        return TypeResult(
            session_id=sid, selector=sel, text=text, error="timeout must be > 0"
        )

    page = session.page
    try:
        wait = getattr(page, "wait_for_selector", None)
        if callable(wait):
            await wait(sel, timeout=int(wait_timeout * 1000), state="visible")
        ms = int(wait_timeout * 1000)
        if clear:
            await page.fill(sel, text, timeout=ms)
        else:
            kwargs: dict = {"timeout": ms}
            if delay_ms is not None:
                kwargs["delay"] = float(delay_ms)
            await page.type(sel, text, **kwargs)
        if press_enter:
            press = getattr(page, "press", None)
            if callable(press):
                await press(sel, "Enter", timeout=ms)
            else:
                # Fallback: type a newline via keyboard if available.
                kb = getattr(page, "keyboard", None)
                if kb is not None and hasattr(kb, "press"):
                    await kb.press("Enter")
        title = await page.title()
        url = getattr(page, "url", session.url)
        session.url = url
        session.title = title
        return TypeResult(
            session_id=sid,
            selector=sel,
            text=text,
            cleared=clear,
            url=url,
            title=title,
            typed=True,
        )
    except Exception as exc:  # noqa: BLE001
        return TypeResult(
            session_id=sid,
            selector=sel,
            text=text,
            cleared=clear,
            url=getattr(page, "url", session.url),
            title=session.title,
            typed=False,
            error=f"type failed: {exc}",
        )


def type_result_to_dict(result: TypeResult) -> dict:
    return {
        "session_id": result.session_id,
        "selector": result.selector,
        "text": result.text,
        "cleared": result.cleared,
        "url": result.url,
        "title": result.title,
        "typed": result.typed,
        "error": result.error,
    }


__all__ = [
    "BrowserEngine",
    "BrowserError",
    "ClickResult",
    "FakeEngine",
    "OpenResult",
    "PlaywrightEngine",
    "TypeResult",
    "browser_click",
    "browser_open",
    "browser_type",
    "click_result_to_dict",
    "open_result_to_dict",
    "type_result_to_dict",
]
