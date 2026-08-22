"""HiraraBrowser — self-hosted browser tools for AI agents.

v1 ships ``browser_open``. ``browser_click``, ``browser_type``, and
``browser_screenshot`` land next in this package.
"""

from .browser import (
    BrowserEngine,
    BrowserError,
    FakeEngine,
    OpenResult,
    PlaywrightEngine,
    browser_open,
    open_result_to_dict,
)
from .config import BrowserConfig
from .session import Session, SessionStore
from .tools import BROWSER_OPEN_SCHEMA, Toolset

__all__ = [
    "BROWSER_OPEN_SCHEMA",
    "BrowserConfig",
    "BrowserEngine",
    "BrowserError",
    "FakeEngine",
    "OpenResult",
    "PlaywrightEngine",
    "Session",
    "SessionStore",
    "Toolset",
    "browser_open",
    "open_result_to_dict",
]

__version__ = "0.1.0"
