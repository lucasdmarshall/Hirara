"""Runtime configuration for HiraraBrowser."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw else default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw else default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    return raw.strip().lower() in {"1", "true", "yes", "on"} if raw else default


@dataclass(frozen=True)
class BrowserConfig:
    """Browser-tool knobs."""

    # Chromium headless by default.
    headless: bool = True

    # Navigation timeout (seconds).
    nav_timeout: float = 30.0

    # Max concurrent browser sessions.
    max_sessions: int = 8

    # Idle session TTL (seconds); closed and discarded when exceeded.
    session_ttl: float = 600.0

    # Cap on returned text / HTML snippets.
    max_text_chars: int = 50_000

    # Cap on screenshot bytes returned (base64 payload is ~4/3 of this).
    max_screenshot_bytes: int = 5_000_000

    # When False, resolve_target rejects private/reserved destinations.
    # True on a trusted laptop; False in the Docker image.
    allow_private_urls: bool = True

    # Playwright browser channel: chromium | firefox | webkit
    browser_channel: str = "chromium"

    @classmethod
    def from_env(cls) -> "BrowserConfig":
        channel = (os.getenv("CBRO_BROWSER") or cls.browser_channel).strip().lower()
        if channel not in {"chromium", "firefox", "webkit"}:
            channel = "chromium"
        return cls(
            headless=_env_bool("CBRO_HEADLESS", cls.headless),
            nav_timeout=_env_float("CBRO_NAV_TIMEOUT", cls.nav_timeout),
            max_sessions=_env_int("CBRO_MAX_SESSIONS", cls.max_sessions),
            session_ttl=_env_float("CBRO_SESSION_TTL", cls.session_ttl),
            max_text_chars=_env_int("CBRO_MAX_TEXT_CHARS", cls.max_text_chars),
            max_screenshot_bytes=_env_int(
                "CBRO_MAX_SCREENSHOT_BYTES", cls.max_screenshot_bytes
            ),
            allow_private_urls=_env_bool(
                "CBRO_ALLOW_PRIVATE_URLS", cls.allow_private_urls
            ),
            browser_channel=channel,
        )


__all__ = ["BrowserConfig"]
