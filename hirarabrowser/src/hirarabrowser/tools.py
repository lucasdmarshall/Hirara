"""The tool layer: schema and JSON-ready results.

Tools: ``browser_open``, ``browser_click``, ``browser_type``, ``browser_screenshot``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .browser import (
    browser_click,
    browser_open,
    browser_screenshot,
    browser_type,
    click_result_to_dict,
    open_result_to_dict,
    screenshot_result_to_dict,
    type_result_to_dict,
)
from .config import BrowserConfig
from .session import SessionStore

log = logging.getLogger(__name__)

BROWSER_OPEN_SCHEMA = {
    "name": "browser_open",
    "description": (
        "Open a URL in a headless browser and return the resulting page. Use "
        "this when you need a rendered document (JS-heavy sites, SPAs, pages "
        "that do not yield useful HTML to a plain HTTP fetch).\n\n"
        "Returns session_id (reuse for later browser_* tools), final url, "
        "title, and optional HTTP status. Pass include_text=true to also get "
        "visible body text. Pass an existing session_id to navigate that "
        "session to a new URL instead of opening a new browser."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "http(s) URL to open.",
            },
            "session_id": {
                "type": "string",
                "description": "Optional existing session to navigate.",
            },
            "timeout": {
                "type": "number",
                "minimum": 0.1,
                "description": "Navigation timeout in seconds.",
            },
            "include_text": {
                "type": "boolean",
                "description": "If true, include visible body text in the response.",
            },
        },
        "required": ["url"],
        "additionalProperties": False,
    },
}


BROWSER_CLICK_SCHEMA = {
    "name": "browser_click",
    "description": (
        "Click an element in an existing browser session. Use after "
        "browser_open. Pass a CSS selector (or text=… / role-based selector "
        "Playwright accepts). Returns the session's url/title after the click "
        "(useful when the click navigates)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "Session from browser_open.",
            },
            "selector": {
                "type": "string",
                "description": "Element selector to click (CSS, text=, etc.).",
            },
            "timeout": {
                "type": "number",
                "minimum": 0.1,
                "description": "Wait/click timeout in seconds.",
            },
            "button": {
                "type": "string",
                "enum": ["left", "right", "middle"],
                "description": "Mouse button (default left).",
            },
            "click_count": {
                "type": "integer",
                "minimum": 1,
                "maximum": 3,
                "description": "1 = single click, 2 = double click.",
            },
        },
        "required": ["session_id", "selector"],
        "additionalProperties": False,
    },
}


BROWSER_TYPE_SCHEMA = {
    "name": "browser_type",
    "description": (
        "Type text into an input/textarea in an existing browser session. "
        "Use after browser_open. By default clears the field first (fill); "
        "pass clear=false to append keystrokes. Optional press_enter submits "
        "the field afterward."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "Session from browser_open.",
            },
            "selector": {
                "type": "string",
                "description": "Input selector (CSS, text=, etc.).",
            },
            "text": {
                "type": "string",
                "description": "Text to type into the element.",
            },
            "timeout": {
                "type": "number",
                "minimum": 0.1,
                "description": "Wait/type timeout in seconds.",
            },
            "clear": {
                "type": "boolean",
                "description": "If true (default), replace existing value; if false, append.",
            },
            "press_enter": {
                "type": "boolean",
                "description": "If true, press Enter after typing.",
            },
            "delay_ms": {
                "type": "number",
                "minimum": 0,
                "description": "Per-keystroke delay in ms when clear=false.",
            },
        },
        "required": ["session_id", "selector", "text"],
        "additionalProperties": False,
    },
}


BROWSER_SCREENSHOT_SCHEMA = {
    "name": "browser_screenshot",
    "description": (
        "Capture a screenshot of the current page in an existing browser "
        "session. Returns image_base64 (PNG by default) plus mime_type. "
        "Pass full_page=true for the entire scrollable page, or selector to "
        "capture a single element."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "Session from browser_open.",
            },
            "full_page": {
                "type": "boolean",
                "description": "If true, capture the full scrollable page.",
            },
            "selector": {
                "type": "string",
                "description": "Optional element selector to screenshot instead of the viewport.",
            },
            "image_format": {
                "type": "string",
                "enum": ["png", "jpeg", "jpg"],
                "description": "Image format (default png).",
            },
            "quality": {
                "type": "integer",
                "minimum": 0,
                "maximum": 100,
                "description": "JPEG quality 0-100 (ignored for png).",
            },
            "timeout": {
                "type": "number",
                "minimum": 0.1,
                "description": "Screenshot timeout in seconds.",
            },
        },
        "required": ["session_id"],
        "additionalProperties": False,
    },
}


def _open_envelope(**overrides) -> dict:
    envelope = {
        "session_id": None,
        "url": None,
        "title": None,
        "status": None,
        "text": None,
        "truncated": False,
        "error": None,
    }
    envelope.update(overrides)
    return envelope


def _click_envelope(**overrides) -> dict:
    envelope = {
        "session_id": None,
        "selector": None,
        "url": None,
        "title": None,
        "clicked": False,
        "error": None,
    }
    envelope.update(overrides)
    return envelope


def _type_envelope(**overrides) -> dict:
    envelope = {
        "session_id": None,
        "selector": None,
        "text": None,
        "cleared": False,
        "url": None,
        "title": None,
        "typed": False,
        "error": None,
    }
    envelope.update(overrides)
    return envelope


def _screenshot_envelope(**overrides) -> dict:
    envelope = {
        "session_id": None,
        "url": None,
        "title": None,
        "image_base64": None,
        "mime_type": None,
        "byte_count": None,
        "full_page": False,
        "selector": None,
        "truncated": False,
        "error": None,
    }
    envelope.update(overrides)
    return envelope


@dataclass
class Toolset:
    """Browser tools sharing one config + session store."""

    config: BrowserConfig
    store: SessionStore
    engine: object | None = None

    @classmethod
    def from_env(cls) -> "Toolset":
        config = BrowserConfig.from_env()
        return cls(
            config=config,
            store=SessionStore(
                max_sessions=config.max_sessions, session_ttl=config.session_ttl
            ),
        )

    def schemas(self) -> list[dict]:
        return [
            BROWSER_OPEN_SCHEMA,
            BROWSER_CLICK_SCHEMA,
            BROWSER_TYPE_SCHEMA,
            BROWSER_SCREENSHOT_SCHEMA,
        ]

    def health(self) -> dict:
        return {
            "status": "ok",
            "version": "0.1.0",
            "tools": [
                "browser_open",
                "browser_click",
                "browser_type",
                "browser_screenshot",
            ],
            "sessions": len(self.store),
            "headless": self.config.headless,
        }

    async def browser_open(
        self,
        *,
        url: str,
        session_id: str | None = None,
        timeout: float | None = None,
        include_text: bool = False,
    ) -> dict:
        try:
            result = await browser_open(
                url,
                session_id=session_id,
                timeout=timeout,
                include_text=include_text,
                config=self.config,
                store=self.store,
                engine=self.engine,  # type: ignore[arg-type]
            )
            return open_result_to_dict(result)
        except Exception as exc:  # noqa: BLE001
            log.exception("browser_open failed")
            return _open_envelope(error=f"browser_open failed: {exc}")

    async def browser_click(
        self,
        *,
        session_id: str,
        selector: str,
        timeout: float | None = None,
        button: str = "left",
        click_count: int = 1,
    ) -> dict:
        try:
            result = await browser_click(
                session_id,
                selector,
                timeout=timeout,
                button=button,
                click_count=click_count,
                config=self.config,
                store=self.store,
            )
            return click_result_to_dict(result)
        except Exception as exc:  # noqa: BLE001
            log.exception("browser_click failed")
            return _click_envelope(
                session_id=session_id,
                selector=selector,
                error=f"browser_click failed: {exc}",
            )

    async def browser_type(
        self,
        *,
        session_id: str,
        selector: str,
        text: str,
        timeout: float | None = None,
        clear: bool = True,
        press_enter: bool = False,
        delay_ms: float | None = None,
    ) -> dict:
        try:
            result = await browser_type(
                session_id,
                selector,
                text,
                timeout=timeout,
                clear=clear,
                press_enter=press_enter,
                delay_ms=delay_ms,
                config=self.config,
                store=self.store,
            )
            return type_result_to_dict(result)
        except Exception as exc:  # noqa: BLE001
            log.exception("browser_type failed")
            return _type_envelope(
                session_id=session_id,
                selector=selector,
                text=text,
                error=f"browser_type failed: {exc}",
            )

    async def browser_screenshot(
        self,
        *,
        session_id: str,
        full_page: bool = False,
        selector: str | None = None,
        image_format: str = "png",
        quality: int | None = None,
        timeout: float | None = None,
    ) -> dict:
        try:
            result = await browser_screenshot(
                session_id,
                full_page=full_page,
                selector=selector,
                image_format=image_format,
                quality=quality,
                timeout=timeout,
                config=self.config,
                store=self.store,
            )
            return screenshot_result_to_dict(result)
        except Exception as exc:  # noqa: BLE001
            log.exception("browser_screenshot failed")
            return _screenshot_envelope(
                session_id=session_id,
                selector=selector,
                error=f"browser_screenshot failed: {exc}",
            )


__all__ = [
    "BROWSER_OPEN_SCHEMA",
    "BROWSER_CLICK_SCHEMA",
    "BROWSER_TYPE_SCHEMA",
    "BROWSER_SCREENSHOT_SCHEMA",
    "Toolset",
    "TOOL_NAMES",
    "call_tool",
    "tool_schemas",
]


TOOL_NAMES = (
    "browser_open",
    "browser_click",
    "browser_type",
    "browser_screenshot",
)
_local_toolset: "Toolset | None" = None


def _backend() -> "Toolset":
    global _local_toolset
    if _local_toolset is None:
        _local_toolset = Toolset.from_env()
    return _local_toolset


async def call_tool(name: str, arguments: dict | None = None) -> dict:
    args = arguments or {}
    if name == "browser_open":
        return await _backend().browser_open(**args)
    if name == "browser_click":
        return await _backend().browser_click(**args)
    if name == "browser_type":
        return await _backend().browser_type(**args)
    if name == "browser_screenshot":
        return await _backend().browser_screenshot(**args)
    raise KeyError(f"unknown tool: {name}")


def tool_schemas() -> list[dict]:
    return _backend().schemas()
