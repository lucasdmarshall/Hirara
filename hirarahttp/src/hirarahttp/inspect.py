"""Structured inspection helpers for recorded HTTP exchanges."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .history import HistoryEntry

# Headers agents often care about when reading a response.
_INTERESTING_RESPONSE = (
    "content-type",
    "content-length",
    "content-encoding",
    "transfer-encoding",
    "cache-control",
    "etag",
    "last-modified",
    "expires",
    "location",
    "server",
    "date",
    "vary",
    "set-cookie",
    "www-authenticate",
    "retry-after",
    "access-control-allow-origin",
    "access-control-allow-credentials",
    "access-control-allow-methods",
    "access-control-allow-headers",
    "access-control-expose-headers",
    "access-control-max-age",
    "strict-transport-security",
    "content-security-policy",
    "content-security-policy-report-only",
    "x-content-type-options",
    "x-frame-options",
    "x-xss-protection",
    "referrer-policy",
    "permissions-policy",
    "cross-origin-opener-policy",
    "cross-origin-resource-policy",
    "cross-origin-embedder-policy",
)

_INTERESTING_REQUEST = (
    "accept",
    "accept-encoding",
    "accept-language",
    "authorization",
    "cookie",
    "content-type",
    "content-length",
    "origin",
    "referer",
    "user-agent",
    "host",
    "x-requested-with",
    "if-none-match",
    "if-modified-since",
)

# Common response headers worth noting when absent (informational only).
_COMMON_SECURITY = (
    "strict-transport-security",
    "content-security-policy",
    "x-content-type-options",
    "x-frame-options",
    "referrer-policy",
)


@dataclass
class HeaderView:
    which: str
    headers: list[dict[str, str]] = field(default_factory=list)
    count: int = 0
    by_name: dict[str, str] = field(default_factory=dict)
    interesting: dict[str, str] = field(default_factory=dict)
    missing_common: list[str] = field(default_factory=list)
    set_cookie_count: int = 0
    content_type: str | None = None
    content_length: int | None = None


@dataclass
class InspectHeadersResult:
    request_id: str | None = None
    which: str = "response"
    url: str | None = None
    method: str | None = None
    status: int | None = None
    request: HeaderView | None = None
    response: HeaderView | None = None
    error: str | None = None


def _normalize_map(raw: dict[str, str] | None) -> dict[str, str]:
    """Lower-case keys; last value wins on duplicates."""
    out: dict[str, str] = {}
    if not raw:
        return out
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        name = key.strip()
        if not name:
            continue
        out[name.lower()] = value
    return out


def _items(raw: dict[str, str] | None) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    if not raw:
        return items
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        name = key.strip()
        if not name:
            continue
        items.append({"name": name, "value": value, "name_lower": name.lower()})
    items.sort(key=lambda row: row["name_lower"])
    return items


def _parse_content_length(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _set_cookie_count(raw: dict[str, str] | None) -> int:
    if not raw:
        return 0
    n = 0
    for key, value in raw.items():
        if isinstance(key, str) and key.lower() == "set-cookie" and value:
            # Collapsed multi-value uses ", " — count conservatively by
            # splitting on ", " only when it looks like another cookie pair.
            parts = [p for p in value.split("\n") if p.strip()]
            if len(parts) > 1:
                n += len(parts)
            else:
                n += 1
    return n


def build_header_view(raw: dict[str, str] | None, *, which: str) -> HeaderView:
    items = _items(raw)
    by_name = _normalize_map(raw)
    interesting_keys = (
        _INTERESTING_RESPONSE if which == "response" else _INTERESTING_REQUEST
    )
    interesting = {k: by_name[k] for k in interesting_keys if k in by_name}
    missing: list[str] = []
    if which == "response":
        missing = [k for k in _COMMON_SECURITY if k not in by_name]
    return HeaderView(
        which=which,
        headers=items,
        count=len(items),
        by_name=by_name,
        interesting=interesting,
        missing_common=missing,
        set_cookie_count=_set_cookie_count(raw),
        content_type=by_name.get("content-type"),
        content_length=_parse_content_length(by_name.get("content-length")),
    )


def header_view_to_dict(view: HeaderView) -> dict[str, Any]:
    return {
        "which": view.which,
        "headers": list(view.headers),
        "count": view.count,
        "by_name": dict(view.by_name),
        "interesting": dict(view.interesting),
        "missing_common": list(view.missing_common),
        "set_cookie_count": view.set_cookie_count,
        "content_type": view.content_type,
        "content_length": view.content_length,
    }


def inspect_headers_from_maps(
    *,
    request_headers: dict[str, str] | None = None,
    response_headers: dict[str, str] | None = None,
    which: str = "response",
    request_id: str | None = None,
    url: str | None = None,
    method: str | None = None,
    status: int | None = None,
) -> InspectHeadersResult:
    side = (which or "response").strip().lower()
    if side not in {"request", "response", "both"}:
        return InspectHeadersResult(
            request_id=request_id,
            which=side,
            error=f"which must be 'request', 'response', or 'both' (got {which!r})",
        )

    result = InspectHeadersResult(
        request_id=request_id,
        which=side,
        url=url,
        method=method,
        status=status,
    )
    if side in {"request", "both"}:
        result.request = build_header_view(request_headers, which="request")
    if side in {"response", "both"}:
        result.response = build_header_view(response_headers, which="response")
    return result


def inspect_headers_from_entry(
    entry: HistoryEntry,
    *,
    which: str = "response",
) -> InspectHeadersResult:
    return inspect_headers_from_maps(
        request_headers=entry.request_headers,
        response_headers=entry.response_headers,
        which=which,
        request_id=entry.id,
        url=entry.final_url or entry.url,
        method=entry.method,
        status=entry.status,
    )


def inspect_headers_result_to_dict(result: InspectHeadersResult) -> dict[str, Any]:
    return {
        "request_id": result.request_id,
        "which": result.which,
        "url": result.url,
        "method": result.method,
        "status": result.status,
        "request": header_view_to_dict(result.request) if result.request else None,
        "response": header_view_to_dict(result.response) if result.response else None,
        "error": result.error,
    }


__all__ = [
    "HeaderView",
    "InspectHeadersResult",
    "build_header_view",
    "header_view_to_dict",
    "inspect_headers_from_entry",
    "inspect_headers_from_maps",
    "inspect_headers_result_to_dict",
]
