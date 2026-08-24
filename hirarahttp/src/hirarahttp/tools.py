"""The tool layer: schema and JSON-ready results.

Both front ends (HTTP service and MCP server) call into here, so the two can
never drift apart in behaviour — only in transport.

Tools: ``http_request``, ``http_history``, ``inspect_headers``,
``inspect_cookies``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .config import HttpConfig
from .history import HistoryStore, entry_to_dict, entry_to_summary
from .inspect import (
    inspect_cookies_from_entry,
    inspect_cookies_from_maps,
    inspect_cookies_result_to_dict,
    inspect_headers_from_entry,
    inspect_headers_from_maps,
    inspect_headers_result_to_dict,
)
from .request import http_request, result_to_dict

log = logging.getLogger(__name__)


HTTP_REQUEST_SCHEMA = {
    "name": "http_request",
    "description": (
        "Send an HTTP request and return status, headers, and body. Use this "
        "for raw HTTP (any method) when you need the full response — not a "
        "cleaned page extract. URLs (and every redirect hop) are checked "
        "through Hirara's SSRF perimeter; 4xx/5xx responses are returned as "
        "data, not tool failures.\n\n"
        "Pass method, optional headers/body, and follow_redirects. Binary "
        "response bodies come back as base64 (body_encoding=base64); text "
        "and JSON as utf-8. Each call is recorded in-process; use "
        "http_history to list them (id is returned as request_id)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "http(s) URL to request.",
            },
            "method": {
                "type": "string",
                "enum": ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
                "description": "HTTP method (default GET).",
            },
            "headers": {
                "type": "object",
                "additionalProperties": {"type": "string"},
                "description": "Optional request headers (Host / hop-by-hop blocked).",
            },
            "body": {
                "type": "string",
                "description": "Optional request body (UTF-8). Not allowed with GET/HEAD.",
            },
            "timeout": {
                "type": "number",
                "minimum": 0.1,
                "description": "Request timeout in seconds.",
            },
            "follow_redirects": {
                "type": "boolean",
                "description": "Follow redirects (re-validated each hop). Default true.",
            },
            "max_redirects": {
                "type": "integer",
                "minimum": 0,
                "description": "Max redirect hops when follow_redirects is true.",
            },
            "max_bytes": {
                "type": "integer",
                "minimum": 1,
                "description": "Cap on response body bytes (server also caps).",
            },
        },
        "required": ["url"],
        "additionalProperties": False,
    },
}


HTTP_HISTORY_SCHEMA = {
    "name": "http_history",
    "description": (
        "List or fetch recent http_request calls from this process. Newest "
        "first. Pass id to retrieve one full entry (headers + body). Pass "
        "clear=true to wipe the ring buffer. List rows omit bodies unless "
        "include_body=true."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 200,
                "description": "Max entries to return (default 20).",
            },
            "offset": {
                "type": "integer",
                "minimum": 0,
                "description": "Skip this many newest entries (pagination).",
            },
            "id": {
                "type": "string",
                "description": "Fetch a single history entry by request_id.",
            },
            "include_body": {
                "type": "boolean",
                "description": "Include bodies in list results (default false).",
            },
            "clear": {
                "type": "boolean",
                "description": "If true, clear history and return how many were dropped.",
            },
        },
        "additionalProperties": False,
    },
}


INSPECT_HEADERS_SCHEMA = {
    "name": "inspect_headers",
    "description": (
        "Inspect HTTP headers from a recorded http_request (pass id) or from "
        "a raw headers object. Returns a sorted header list, lower-cased "
        "by_name map, interesting/common fields (content-type, cache, CORS, "
        "security headers, …), and missing_common security headers for "
        "responses. Use which=request|response|both (default response)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "id": {
                "type": "string",
                "description": "History request_id from http_request / http_history.",
            },
            "which": {
                "type": "string",
                "enum": ["request", "response", "both"],
                "description": "Which side to inspect (default response).",
            },
            "headers": {
                "type": "object",
                "additionalProperties": {"type": "string"},
                "description": (
                    "Optional raw headers to inspect when id is omitted. "
                    "Treated as the side selected by which (default response)."
                ),
            },
        },
        "additionalProperties": False,
    },
}


INSPECT_COOKIES_SCHEMA = {
    "name": "inspect_cookies",
    "description": (
        "Parse cookies from a recorded http_request (pass id) or from a raw "
        "headers object. Request Cookie headers become name/value pairs; "
        "Set-Cookie values become attributes (path, domain, expires, "
        "max-age, Secure, HttpOnly, SameSite) plus flags_missing. Use "
        "which=request|response|both (default response)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "id": {
                "type": "string",
                "description": "History request_id from http_request / http_history.",
            },
            "which": {
                "type": "string",
                "enum": ["request", "response", "both"],
                "description": "Which side to inspect (default response).",
            },
            "headers": {
                "type": "object",
                "additionalProperties": {"type": "string"},
                "description": (
                    "Optional raw headers when id is omitted. Cookie is used "
                    "for which=request; Set-Cookie for which=response."
                ),
            },
        },
        "additionalProperties": False,
    },
}


def _request_envelope(**overrides) -> dict:
    envelope = {
        "request_id": None,
        "method": None,
        "url": None,
        "final_url": None,
        "status": None,
        "reason": None,
        "request_headers": {},
        "response_headers": {},
        "body": None,
        "body_encoding": None,
        "truncated": False,
        "bytes_downloaded": None,
        "elapsed_ms": None,
        "redirects": [],
        "error": None,
    }
    envelope.update(overrides)
    return envelope


def _history_envelope(**overrides) -> dict:
    envelope = {
        "entries": [],
        "count": 0,
        "total": 0,
        "cleared": None,
        "error": None,
    }
    envelope.update(overrides)
    return envelope


def _inspect_headers_envelope(**overrides) -> dict:
    envelope = {
        "request_id": None,
        "which": None,
        "url": None,
        "method": None,
        "status": None,
        "request": None,
        "response": None,
        "error": None,
    }
    envelope.update(overrides)
    return envelope


def _inspect_cookies_envelope(**overrides) -> dict:
    envelope = {
        "request_id": None,
        "which": None,
        "url": None,
        "method": None,
        "status": None,
        "request": None,
        "response": None,
        "error": None,
    }
    envelope.update(overrides)
    return envelope


@dataclass
class Toolset:
    """HTTP tools sharing one config + history store."""

    config: HttpConfig
    history: HistoryStore | None = None

    def __post_init__(self) -> None:
        if self.history is None:
            self.history = HistoryStore(
                max_entries=self.config.history_size,
                max_body_chars=self.config.history_body_chars,
            )

    @classmethod
    def from_env(cls) -> "Toolset":
        return cls(config=HttpConfig.from_env())

    def schemas(self) -> list[dict]:
        return [
            HTTP_REQUEST_SCHEMA,
            HTTP_HISTORY_SCHEMA,
            INSPECT_HEADERS_SCHEMA,
            INSPECT_COOKIES_SCHEMA,
        ]

    def health(self) -> dict:
        return {
            "status": "ok",
            "version": "0.1.0",
            "tools": [
                "http_request",
                "http_history",
                "inspect_headers",
                "inspect_cookies",
            ],
            "max_bytes": self.config.max_bytes,
            "max_redirects": self.config.max_redirects,
            "history_size": self.config.history_size,
            "history_count": len(self.history),
        }

    async def http_request(
        self,
        *,
        url: str,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: str | None = None,
        timeout: float | None = None,
        follow_redirects: bool = True,
        max_redirects: int | None = None,
        max_bytes: int | None = None,
    ) -> dict:
        try:
            result = await http_request(
                url,
                method=method,
                headers=headers,
                body=body,
                timeout=timeout,
                follow_redirects=follow_redirects,
                max_redirects=max_redirects,
                max_bytes=max_bytes,
                config=self.config,
            )
            payload = result_to_dict(result)
        except Exception as exc:  # noqa: BLE001
            log.exception("http_request failed")
            payload = _request_envelope(
                method=method,
                url=url,
                error=f"http_request failed: {exc}",
            )
        entry = self.history.record(payload)
        payload["request_id"] = entry.id
        return payload

    async def http_history(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        id: str | None = None,
        include_body: bool = False,
        clear: bool = False,
    ) -> dict:
        try:
            if clear:
                cleared = self.history.clear()
                return _history_envelope(cleared=cleared, total=0, count=0)

            if id is not None and str(id).strip():
                entry = self.history.get(str(id))
                if entry is None:
                    return _history_envelope(
                        error=f"unknown history id: {id}",
                        total=len(self.history),
                    )
                return _history_envelope(
                    entries=[entry_to_dict(entry, include_body=True)],
                    count=1,
                    total=len(self.history),
                )

            lim = 20 if limit is None else int(limit)
            if lim < 1:
                return _history_envelope(error="limit must be >= 1")
            if lim > 200:
                lim = 200
            off = 0 if offset is None else int(offset)
            if off < 0:
                return _history_envelope(error="offset must be >= 0")

            page, total = self.history.list(limit=lim, offset=off)
            if include_body:
                entries = [entry_to_dict(e, include_body=True) for e in page]
            else:
                entries = [entry_to_summary(e) for e in page]
            return _history_envelope(entries=entries, count=len(entries), total=total)
        except Exception as exc:  # noqa: BLE001
            log.exception("http_history failed")
            return _history_envelope(error=f"http_history failed: {exc}")

    async def inspect_headers(
        self,
        *,
        id: str | None = None,
        which: str = "response",
        headers: dict[str, str] | None = None,
    ) -> dict:
        try:
            sid = (id or "").strip() if id is not None else ""
            if sid:
                assert self.history is not None
                entry = self.history.get(sid)
                if entry is None:
                    return _inspect_headers_envelope(
                        which=which,
                        error=f"unknown history id: {id}",
                    )
                result = inspect_headers_from_entry(entry, which=which)
                return inspect_headers_result_to_dict(result)

            if headers is not None:
                side = (which or "response").strip().lower()
                if side == "both":
                    return _inspect_headers_envelope(
                        which=side,
                        error="pass id to inspect both sides, or set which to request/response with headers",
                    )
                if side == "request":
                    result = inspect_headers_from_maps(
                        request_headers=headers, which="request"
                    )
                else:
                    result = inspect_headers_from_maps(
                        response_headers=headers, which="response"
                    )
                return inspect_headers_result_to_dict(result)

            return _inspect_headers_envelope(
                which=which,
                error="id or headers is required",
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("inspect_headers failed")
            return _inspect_headers_envelope(
                which=which,
                error=f"inspect_headers failed: {exc}",
            )

    async def inspect_cookies(
        self,
        *,
        id: str | None = None,
        which: str = "response",
        headers: dict[str, str] | None = None,
    ) -> dict:
        try:
            sid = (id or "").strip() if id is not None else ""
            if sid:
                assert self.history is not None
                entry = self.history.get(sid)
                if entry is None:
                    return _inspect_cookies_envelope(
                        which=which,
                        error=f"unknown history id: {id}",
                    )
                result = inspect_cookies_from_entry(entry, which=which)
                return inspect_cookies_result_to_dict(result)

            if headers is not None:
                side = (which or "response").strip().lower()
                if side == "both":
                    return _inspect_cookies_envelope(
                        which=side,
                        error="pass id to inspect both sides, or set which to request/response with headers",
                    )
                if side == "request":
                    result = inspect_cookies_from_maps(
                        request_headers=headers, which="request"
                    )
                else:
                    result = inspect_cookies_from_maps(
                        response_headers=headers, which="response"
                    )
                return inspect_cookies_result_to_dict(result)

            return _inspect_cookies_envelope(
                which=which,
                error="id or headers is required",
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("inspect_cookies failed")
            return _inspect_cookies_envelope(
                which=which,
                error=f"inspect_cookies failed: {exc}",
            )


__all__ = [
    "HTTP_REQUEST_SCHEMA",
    "HTTP_HISTORY_SCHEMA",
    "INSPECT_HEADERS_SCHEMA",
    "INSPECT_COOKIES_SCHEMA",
    "Toolset",
    "TOOL_NAMES",
    "call_tool",
    "tool_schemas",
]


TOOL_NAMES = (
    "http_request",
    "http_history",
    "inspect_headers",
    "inspect_cookies",
)
_local_toolset: "Toolset | None" = None


def _backend() -> "Toolset":
    global _local_toolset
    if _local_toolset is None:
        _local_toolset = Toolset.from_env()
    return _local_toolset


async def call_tool(name: str, arguments: dict | None = None) -> dict:
    args = arguments or {}
    if name == "http_request":
        return await _backend().http_request(**args)
    if name == "http_history":
        return await _backend().http_history(**args)
    if name == "inspect_headers":
        return await _backend().inspect_headers(**args)
    if name == "inspect_cookies":
        return await _backend().inspect_cookies(**args)
    raise KeyError(f"unknown tool: {name}")


def tool_schemas() -> list[dict]:
    return _backend().schemas()
