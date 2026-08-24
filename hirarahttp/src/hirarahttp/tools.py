"""The tool layer: schema and JSON-ready results.

Both front ends (HTTP service and MCP server) call into here, so the two can
never drift apart in behaviour — only in transport.

Tools: ``http_request``, ``http_history``, ``inspect_headers``,
``inspect_cookies``, ``inspect_response``, ``directory_enum``,
``request_replay``, ``parameter_test``, ``response_compare``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .compare import compare_result_to_dict, response_compare
from .config import HttpConfig
from .enum_dir import directory_enum, enum_result_to_dict
from .history import HistoryStore, entry_to_dict, entry_to_summary
from .inspect import (
    inspect_cookies_from_entry,
    inspect_cookies_from_maps,
    inspect_cookies_result_to_dict,
    inspect_headers_from_entry,
    inspect_headers_from_maps,
    inspect_headers_result_to_dict,
    inspect_response_from_entry,
    inspect_response_from_parts,
    inspect_response_result_to_dict,
)
from .replay import (
    parameter_test,
    parameter_test_result_to_dict,
    replay_result_to_dict,
    request_replay,
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


INSPECT_RESPONSE_SCHEMA = {
    "name": "inspect_response",
    "description": (
        "Summarize an HTTP response from a recorded http_request (pass id) "
        "or from raw status/body/headers. Returns status class, content-type, "
        "body_kind (json/html/xml/text/binary/empty), JSON keys/length when "
        "the body is JSON, an HTML title when present, and a short preview. "
        "Pass include_body=true for the full body (and parsed json)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "id": {
                "type": "string",
                "description": "History request_id from http_request / http_history.",
            },
            "include_body": {
                "type": "boolean",
                "description": "Include full body (and parsed json) in the result.",
            },
            "preview_chars": {
                "type": "integer",
                "minimum": 0,
                "maximum": 8000,
                "description": "Preview length (default 512).",
            },
            "status": {
                "type": "integer",
                "description": "HTTP status when id is omitted.",
            },
            "body": {
                "type": "string",
                "description": "Response body when id is omitted.",
            },
            "headers": {
                "type": "object",
                "additionalProperties": {"type": "string"},
                "description": "Response headers when id is omitted.",
            },
            "body_encoding": {
                "type": "string",
                "description": "utf-8 or base64 when passing a raw body.",
            },
        },
        "additionalProperties": False,
    },
}


DIRECTORY_ENUM_SCHEMA = {
    "name": "directory_enum",
    "description": (
        "Probe a base URL for existing paths. HEAD (default) or GET each "
        "relative path through Hirara's SSRF perimeter; does not follow "
        "redirects (Location is returned). Omit paths to use a built-in "
        "common-path list. Results hide 404/410 unless include_not_found=true. "
        "found lists statuses other than 404/410."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "Base http(s) URL (e.g. https://example.com/).",
            },
            "paths": {
                "description": (
                    "Relative paths to probe. Array of strings or a "
                    "comma/newline-separated string. Omit for the default list."
                ),
                "oneOf": [
                    {"type": "array", "items": {"type": "string"}},
                    {"type": "string"},
                ],
            },
            "method": {
                "type": "string",
                "enum": ["HEAD", "GET", "OPTIONS"],
                "description": "HTTP method (default HEAD).",
            },
            "timeout": {
                "type": "number",
                "minimum": 0.1,
                "description": "Per-path timeout in seconds.",
            },
            "concurrency": {
                "type": "integer",
                "minimum": 1,
                "description": "Max concurrent probes (server-capped).",
            },
            "include_not_found": {
                "type": "boolean",
                "description": "Include 404/410 rows in results (default false).",
            },
        },
        "required": ["url"],
        "additionalProperties": False,
    },
}



REQUEST_REPLAY_SCHEMA = {
    "name": "request_replay",
    "description": (
        "Re-issue a recorded http_request by history id. Optional url/method/"
        "headers/body overrides. Headers merge with the stored request by "
        "default (merge_headers=false replaces). Records a new history entry."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "id": {
                "type": "string",
                "description": "History request_id to replay.",
            },
            "url": {"type": "string", "description": "Optional URL override."},
            "method": {
                "type": "string",
                "enum": ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
                "description": "Optional method override.",
            },
            "headers": {
                "type": "object",
                "additionalProperties": {"type": "string"},
                "description": "Optional header overrides.",
            },
            "body": {"type": "string", "description": "Optional request body override."},
            "merge_headers": {
                "type": "boolean",
                "description": "Merge overrides into stored headers (default true).",
            },
            "timeout": {"type": "number", "minimum": 0.1},
            "follow_redirects": {"type": "boolean"},
            "max_redirects": {"type": "integer", "minimum": 0},
            "max_bytes": {"type": "integer", "minimum": 1},
        },
        "required": ["id"],
        "additionalProperties": False,
    },
}


PARAMETER_TEST_SCHEMA = {
    "name": "parameter_test",
    "description": (
        "Send a base request once per parameter value. Base comes from history "
        "id and/or url/method/headers/body. location is query, header, cookie, "
        "body, path, or url. For path/url, put {name} or {{name}} in the URL. "
        "Each probe is recorded in history."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "location": {
                "type": "string",
                "enum": ["query", "header", "cookie", "body", "path", "url"],
                "description": "Where to place the parameter.",
            },
            "name": {"type": "string", "description": "Parameter / header / cookie name."},
            "values": {
                "description": "Values to try (list or comma-separated string).",
                "oneOf": [
                    {"type": "array", "items": {"type": "string"}},
                    {"type": "string"},
                ],
            },
            "id": {"type": "string", "description": "Optional history id for the base request."},
            "url": {"type": "string", "description": "Base URL (required if no id)."},
            "method": {
                "type": "string",
                "enum": ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            },
            "headers": {
                "type": "object",
                "additionalProperties": {"type": "string"},
            },
            "body": {"type": "string"},
            "timeout": {"type": "number", "minimum": 0.1},
            "follow_redirects": {"type": "boolean"},
            "max_redirects": {"type": "integer", "minimum": 0},
            "max_bytes": {"type": "integer", "minimum": 1},
            "concurrency": {"type": "integer", "minimum": 1},
            "include_body": {
                "type": "boolean",
                "description": "Include body_preview per trial (default false).",
            },
            "body_preview_chars": {"type": "integer", "minimum": 0},
        },
        "required": ["location", "name", "values"],
        "additionalProperties": False,
    },
}


RESPONSE_COMPARE_SCHEMA = {
    "name": "response_compare",
    "description": (
        "Compare two HTTP responses by history id and/or inline status/"
        "headers/body. Reports status, header, and body differences. "
        "Volatile headers (date, etag, …) are ignored by default."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "left_id": {"type": "string"},
            "right_id": {"type": "string"},
            "left_status": {"type": "integer"},
            "right_status": {"type": "integer"},
            "left_headers": {
                "type": "object",
                "additionalProperties": {"type": "string"},
            },
            "right_headers": {
                "type": "object",
                "additionalProperties": {"type": "string"},
            },
            "left_body": {"type": "string"},
            "right_body": {"type": "string"},
            "compare_headers": {"type": "boolean"},
            "compare_body": {"type": "boolean"},
            "ignore_headers": {
                "description": "Header names to ignore (list or comma-separated).",
                "oneOf": [
                    {"type": "array", "items": {"type": "string"}},
                    {"type": "string"},
                ],
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
        "request_body": None,
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


def _inspect_response_envelope(**overrides) -> dict:
    envelope = {
        "request_id": None,
        "url": None,
        "final_url": None,
        "method": None,
        "status": None,
        "reason": None,
        "status_class": None,
        "ok": None,
        "content_type": None,
        "charset": None,
        "location": None,
        "body_kind": None,
        "body_chars": None,
        "bytes_downloaded": None,
        "truncated": False,
        "body_stored": True,
        "body_encoding": None,
        "json_type": None,
        "json_keys": None,
        "json_length": None,
        "json_error": None,
        "json": None,
        "html_title": None,
        "preview": None,
        "body": None,
        "redirects": [],
        "redirect_count": 0,
        "elapsed_ms": None,
        "error": None,
    }
    envelope.update(overrides)
    return envelope


def _directory_enum_envelope(**overrides) -> dict:
    envelope = {
        "url": None,
        "method": None,
        "paths": [],
        "results": [],
        "found": [],
        "found_count": 0,
        "probed": 0,
        "truncated": False,
        "duration_ms": None,
        "error": None,
    }
    envelope.update(overrides)
    return envelope



def _replay_envelope(**overrides) -> dict:
    envelope = {
        "source_id": None,
        "request": {},
        "response": {},
        "error": None,
    }
    envelope.update(overrides)
    return envelope


def _parameter_test_envelope(**overrides) -> dict:
    envelope = {
        "source_id": None,
        "location": None,
        "name": None,
        "values": [],
        "results": [],
        "probed": 0,
        "truncated": False,
        "duration_ms": None,
        "error": None,
    }
    envelope.update(overrides)
    return envelope


def _compare_envelope(**overrides) -> dict:
    envelope = {
        "left": None,
        "right": None,
        "same": None,
        "status_equal": None,
        "headers_equal": None,
        "body_equal": None,
        "status_diff": None,
        "header_diffs": [],
        "ignored_headers": [],
        "body_diff": None,
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
            INSPECT_RESPONSE_SCHEMA,
            DIRECTORY_ENUM_SCHEMA,
            REQUEST_REPLAY_SCHEMA,
            PARAMETER_TEST_SCHEMA,
            RESPONSE_COMPARE_SCHEMA,
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
                "inspect_response",
                "directory_enum",
                "request_replay",
                "parameter_test",
                "response_compare",
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

    async def inspect_response(
        self,
        *,
        id: str | None = None,
        include_body: bool = False,
        preview_chars: int = 512,
        status: int | None = None,
        body: str | None = None,
        headers: dict[str, str] | None = None,
        body_encoding: str | None = None,
    ) -> dict:
        try:
            sid = (id or "").strip() if id is not None else ""
            if sid:
                assert self.history is not None
                entry = self.history.get(sid)
                if entry is None:
                    return _inspect_response_envelope(
                        error=f"unknown history id: {id}",
                    )
                result = inspect_response_from_entry(
                    entry,
                    include_body=include_body,
                    preview_chars=preview_chars,
                )
                return inspect_response_result_to_dict(result)

            if status is None and body is None and not headers:
                return _inspect_response_envelope(
                    error="id or status/body/headers is required",
                )
            result = inspect_response_from_parts(
                status=status,
                headers=headers,
                body=body,
                body_encoding=body_encoding,
                include_body=include_body,
                preview_chars=preview_chars,
            )
            return inspect_response_result_to_dict(result)
        except Exception as exc:  # noqa: BLE001
            log.exception("inspect_response failed")
            return _inspect_response_envelope(
                error=f"inspect_response failed: {exc}",
            )

    async def directory_enum(
        self,
        *,
        url: str,
        paths: list[str] | str | None = None,
        method: str = "HEAD",
        timeout: float | None = None,
        concurrency: int | None = None,
        include_not_found: bool = False,
    ) -> dict:
        try:
            result = await directory_enum(
                url,
                paths=paths,
                method=method,
                timeout=timeout,
                concurrency=concurrency,
                include_not_found=include_not_found,
                config=self.config,
            )
            return enum_result_to_dict(result)
        except Exception as exc:  # noqa: BLE001
            log.exception("directory_enum failed")
            return _directory_enum_envelope(
                url=url,
                method=method,
                error=f"directory_enum failed: {exc}",
            )

    async def request_replay(
        self,
        *,
        id: str,
        url: str | None = None,
        method: str | None = None,
        headers: dict[str, str] | None = None,
        body: str | None = None,
        merge_headers: bool = True,
        timeout: float | None = None,
        follow_redirects: bool = True,
        max_redirects: int | None = None,
        max_bytes: int | None = None,
    ) -> dict:
        try:
            assert self.history is not None
            result = await request_replay(
                id=id,
                history=self.history,
                url=url,
                method=method,
                headers=headers,
                body=body,
                merge_headers=merge_headers,
                timeout=timeout,
                follow_redirects=follow_redirects,
                max_redirects=max_redirects,
                max_bytes=max_bytes,
                config=self.config,
                record=self.history.record,
            )
            return replay_result_to_dict(result)
        except Exception as exc:  # noqa: BLE001
            log.exception("request_replay failed")
            return _replay_envelope(
                source_id=id,
                error=f"request_replay failed: {exc}",
            )

    async def parameter_test(
        self,
        *,
        location: str,
        name: str,
        values: list[str] | str,
        id: str | None = None,
        url: str | None = None,
        method: str | None = None,
        headers: dict[str, str] | None = None,
        body: str | None = None,
        timeout: float | None = None,
        follow_redirects: bool = True,
        max_redirects: int | None = None,
        max_bytes: int | None = None,
        concurrency: int | None = None,
        include_body: bool = False,
        body_preview_chars: int = 200,
    ) -> dict:
        try:
            result = await parameter_test(
                location=location,
                name=name,
                values=values,
                id=id,
                url=url,
                method=method,
                headers=headers,
                body=body,
                history=self.history,
                timeout=timeout,
                follow_redirects=follow_redirects,
                max_redirects=max_redirects,
                max_bytes=max_bytes,
                concurrency=concurrency,
                include_body=include_body,
                body_preview_chars=body_preview_chars,
                config=self.config,
                record=self.history.record if self.history is not None else None,
            )
            return parameter_test_result_to_dict(result)
        except Exception as exc:  # noqa: BLE001
            log.exception("parameter_test failed")
            return _parameter_test_envelope(
                location=location,
                name=name,
                error=f"parameter_test failed: {exc}",
            )

    async def response_compare(
        self,
        *,
        left_id: str | None = None,
        right_id: str | None = None,
        left_status: int | None = None,
        right_status: int | None = None,
        left_headers: dict[str, str] | None = None,
        right_headers: dict[str, str] | None = None,
        left_body: str | None = None,
        right_body: str | None = None,
        compare_headers: bool = True,
        compare_body: bool = True,
        ignore_headers: list[str] | str | None = None,
    ) -> dict:
        try:
            result = response_compare(
                left_id=left_id,
                right_id=right_id,
                left_status=left_status,
                right_status=right_status,
                left_headers=left_headers,
                right_headers=right_headers,
                left_body=left_body,
                right_body=right_body,
                compare_headers=compare_headers,
                compare_body=compare_body,
                ignore_headers=ignore_headers,
                history=self.history,
            )
            return compare_result_to_dict(result)
        except Exception as exc:  # noqa: BLE001
            log.exception("response_compare failed")
            return _compare_envelope(error=f"response_compare failed: {exc}")



__all__ = [
    "HTTP_REQUEST_SCHEMA",
    "HTTP_HISTORY_SCHEMA",
    "INSPECT_HEADERS_SCHEMA",
    "INSPECT_COOKIES_SCHEMA",
    "INSPECT_RESPONSE_SCHEMA",
    "DIRECTORY_ENUM_SCHEMA",
    "REQUEST_REPLAY_SCHEMA",
    "PARAMETER_TEST_SCHEMA",
    "RESPONSE_COMPARE_SCHEMA",
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
    "inspect_response",
    "directory_enum",
    "request_replay",
    "parameter_test",
    "response_compare",
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
    if name == "inspect_response":
        return await _backend().inspect_response(**args)
    if name == "directory_enum":
        return await _backend().directory_enum(**args)
    if name == "request_replay":
        return await _backend().request_replay(**args)
    if name == "parameter_test":
        return await _backend().parameter_test(**args)
    if name == "response_compare":
        return await _backend().response_compare(**args)
    raise KeyError(f"unknown tool: {name}")


def tool_schemas() -> list[dict]:
    return _backend().schemas()
