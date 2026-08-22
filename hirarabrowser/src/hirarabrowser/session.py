"""In-memory browser session store."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Session:
    """One agent browser session (page + metadata)."""

    session_id: str
    page: Any  # playwright Page or test double
    browser: Any | None = None
    context: Any | None = None
    created_at: float = field(default_factory=time.monotonic)
    last_used: float = field(default_factory=time.monotonic)
    url: str | None = None
    title: str | None = None


class SessionStore:
    """Bounded session map with idle TTL eviction."""

    def __init__(self, *, max_sessions: int, session_ttl: float) -> None:
        self.max_sessions = max_sessions
        self.session_ttl = session_ttl
        self._sessions: dict[str, Session] = {}

    def __len__(self) -> int:
        return len(self._sessions)

    def get(self, session_id: str) -> Session | None:
        self._evict_expired()
        session = self._sessions.get(session_id)
        if session is None:
            return None
        session.last_used = time.monotonic()
        return session

    def create(
        self,
        *,
        page: Any,
        browser: Any | None = None,
        context: Any | None = None,
        url: str | None = None,
        title: str | None = None,
    ) -> Session:
        self._evict_expired()
        if len(self._sessions) >= self.max_sessions:
            # Drop the oldest idle session.
            oldest = min(self._sessions.values(), key=lambda s: s.last_used)
            self.discard(oldest.session_id)
        session_id = uuid.uuid4().hex
        session = Session(
            session_id=session_id,
            page=page,
            browser=browser,
            context=context,
            url=url,
            title=title,
        )
        self._sessions[session_id] = session
        return session

    def discard(self, session_id: str) -> None:
        session = self._sessions.pop(session_id, None)
        if session is None:
            return
        # Best-effort close; tests use plain objects.
        for obj in (session.page, session.context, session.browser):
            close = getattr(obj, "close", None)
            if callable(close):
                try:
                    result = close()
                    # playwright close is async — fire-and-forget from sync path
                    # is handled by the browser engine's close_session.
                    if hasattr(result, "close"):
                        pass
                except Exception:  # noqa: BLE001
                    pass

    def _evict_expired(self) -> None:
        now = time.monotonic()
        expired = [
            sid
            for sid, s in self._sessions.items()
            if now - s.last_used > self.session_ttl
        ]
        for sid in expired:
            self.discard(sid)


__all__ = ["Session", "SessionStore"]
