"""HiraraBrowser — self-hosted browser tools for AI agents.

Ships ``browser_open``, ``browser_click``, ``browser_type``, and
``browser_screenshot``.
"""

from .browser import (
    BrowserEngine,
    BrowserError,
    ClickResult,
    FakeEngine,
    OpenResult,
    PlaywrightEngine,
    ScreenshotResult,
    TypeResult,
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
from .session import Session, SessionStore
from .tools import (
    BROWSER_CLICK_SCHEMA,
    BROWSER_OPEN_SCHEMA,
    BROWSER_SCREENSHOT_SCHEMA,
    BROWSER_TYPE_SCHEMA,
    Toolset,
)

__all__ = [
    "BROWSER_CLICK_SCHEMA",
    "BROWSER_OPEN_SCHEMA",
    "BROWSER_SCREENSHOT_SCHEMA",
    "BROWSER_TYPE_SCHEMA",
    "BrowserConfig",
    "BrowserEngine",
    "BrowserError",
    "ClickResult",
    "FakeEngine",
    "OpenResult",
    "PlaywrightEngine",
    "ScreenshotResult",
    "Session",
    "SessionStore",
    "Toolset",
    "TypeResult",
    "browser_click",
    "browser_open",
    "browser_screenshot",
    "browser_type",
    "click_result_to_dict",
    "open_result_to_dict",
    "screenshot_result_to_dict",
    "type_result_to_dict",
]

__version__ = "0.1.0"
