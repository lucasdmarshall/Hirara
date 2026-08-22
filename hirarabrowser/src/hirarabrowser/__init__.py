"""HiraraBrowser — self-hosted browser tools for AI agents.

Ships ``browser_open`` and ``browser_click``. ``browser_type`` and
``browser_screenshot`` land next.
"""

from .browser import (
    BrowserEngine,
    BrowserError,
    ClickResult,
    FakeEngine,
    OpenResult,
    PlaywrightEngine,
    browser_click,
    browser_open,
    click_result_to_dict,
    open_result_to_dict,
)
from .config import BrowserConfig
from .session import Session, SessionStore
from .tools import BROWSER_CLICK_SCHEMA, BROWSER_OPEN_SCHEMA, Toolset

__all__ = [
    "BROWSER_CLICK_SCHEMA",
    "BROWSER_OPEN_SCHEMA",
    "BrowserConfig",
    "BrowserEngine",
    "BrowserError",
    "ClickResult",
    "FakeEngine",
    "OpenResult",
    "PlaywrightEngine",
    "Session",
    "SessionStore",
    "Toolset",
    "browser_click",
    "browser_open",
    "click_result_to_dict",
    "open_result_to_dict",
]

__version__ = "0.1.0"
