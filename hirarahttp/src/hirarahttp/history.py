"""In-memory ring buffer of recent ``http_request`` calls.

Shared by the HTTP service and MCP server via :class:`~hirarahttp.tools.Toolset`
so agents can list or fetch prior exchanges (foundation for inspect / replay).
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class HistoryEntry:
    """One recorded HTTP exchange."""

    id: str
    ts: float  # unix epoch seconds
    method: str | None = None
    url: str | None = None
    final_url: str | None = None
    status: int | None = None
    reason: str | None = None
    request_headers: dict[str, str] = field(default_factory=dict)
    response_headers: dict[str, str] = field(default_factory=dict)
    body: str | None = None
    body_encoding: str | None = None
    truncated: bool = False
    bytes_downloaded: int | None = None
    elapsed_ms: int | None = None
    redirects: list[str] = field(default_factory=list)
    error: str | None = None
    body_stored: bool = True


class HistoryStore:
    """Bounded FIFO of recent requests. Thread-safe for uvicorn workers."""

    def __init__(self, *, max_entries: int, max_body_chars: int) -> None:
        self.max_entries = max(1, int(max_entries))
        self.max_body_chars = max(0, int(max_body_chars))
        self._entries: list[HistoryEntry] = []
        self._lock = threading.Lock()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def clear(self) -> int:
        with self._lock:
            n = len(self._entries)
            self._entries.clear()
            return n

    def record(self, result: dict[str, Any]) -> HistoryEntry:
        """Append a tool result dict; returns the stored entry (with id)."""
        body = result.get("body")
        body_stored = True
        if isinstance(body, str) and self.max_body_chars and len(body) > self.max_body_chars:
            body = body[: self.max_body_chars]
            body_stored = False
        elif body is not None and self.max_body_chars == 0:
            body = None
            body_stored = False

        entry = HistoryEntry(
            id=uuid.uuid4().hex,
            ts=time.time(),
            method=result.get("method"),
            url=result.get("url"),
            final_url=result.get("final_url"),
            status=result.get("status"),
            reason=result.get("reason"),
            request_headers=dict(result.get("request_headers") or {}),
            response_headers=dict(result.get("response_headers") or {}),
            body=body,
            body_encoding=result.get("body_encoding"),
            truncated=bool(result.get("truncated")),
            bytes_downloaded=result.get("bytes_downloaded"),
            elapsed_ms=result.get("elapsed_ms"),
            redirects=list(result.get("redirects") or []),
            error=result.get("error"),
            body_stored=body_stored and body is not None,
        )
        with self._lock:
            self._entries.append(entry)
            overflow = len(self._entries) - self.max_entries
            if overflow > 0:
                del self._entries[:overflow]
        return entry

    def get(self, entry_id: str) -> HistoryEntry | None:
        sid = (entry_id or "").strip()
        if not sid:
            return None
        with self._lock:
            for entry in self._entries:
                if entry.id == sid:
                    return entry
        return None

    def list(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[HistoryEntry], int]:
        """Newest-first page. Returns (page, total)."""
        lim = max(0, int(limit))
        off = max(0, int(offset))
        with self._lock:
            newest_first = list(reversed(self._entries))
            total = len(newest_first)
            page = newest_first[off : off + lim]
        return page, total


def entry_to_summary(entry: HistoryEntry) -> dict[str, Any]:
    """Compact list row (no bodies / headers)."""
    return {
        "id": entry.id,
        "ts": entry.ts,
        "method": entry.method,
        "url": entry.url,
        "final_url": entry.final_url,
        "status": entry.status,
        "reason": entry.reason,
        "elapsed_ms": entry.elapsed_ms,
        "bytes_downloaded": entry.bytes_downloaded,
        "redirect_count": len(entry.redirects),
        "truncated": entry.truncated,
        "error": entry.error,
    }


def entry_to_dict(entry: HistoryEntry, *, include_body: bool = True) -> dict[str, Any]:
    """Full entry for fetch-by-id or detailed list."""
    out = entry_to_summary(entry)
    out["redirects"] = list(entry.redirects)
    out["request_headers"] = dict(entry.request_headers)
    out["response_headers"] = dict(entry.response_headers)
    out["body_encoding"] = entry.body_encoding
    out["body_stored"] = entry.body_stored
    if include_body:
        out["body"] = entry.body
    else:
        out["body"] = None
    return out


__all__ = [
    "HistoryEntry",
    "HistoryStore",
    "entry_to_dict",
    "entry_to_summary",
]
