"""HiraraBrowser — self-hosted browser tools for AI agents.

Ships ``browser_open``, ``browser_click``, and ``browser_type``.
``browser_screenshot`` lands next.
"""

from .browser import (
    BrowserEngine,
    BrowserError,
    ClickResult,
    FakeEngine,
    OpenResult,
    PlaywrightEngine,
    TypeResult,
    browser_click,
    browser_open,
    browser_type,
    click_result_to_dict,
    open_result_to_dict,
    type_result_to_dict,
)
from .config import BrowserConfig
from .session import Session, SessionStore
from .tools import (
    BROWSER_CLICK_SCHEMA,
    BROWSER_OPEN_SCHEMA,
    BROWSER_TYPE_SCHEMA,
    Toolset,
)

__all__ = [
    "BROWSER_CLICK_SCHEMA",
    "BROWSER_OPEN_SCHEMA",
    "BROWSER_TYPE_SCHEMA",
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
    "TypeResult",
    "browser_click",
    "browser_open",
    "browser_type",
    "click_result_to_dict",
    "open_result_to_dict",
    "type_result_to_dict",
]

__version__ = "0.1.0"
