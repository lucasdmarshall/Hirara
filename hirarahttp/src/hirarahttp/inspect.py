"""Structured inspection helpers for recorded HTTP exchanges."""

from __future__ import annotations

import re
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


# --- cookies -----------------------------------------------------------------

_WEEKDAYS = frozenset({"mon", "tue", "wed", "thu", "fri", "sat", "sun"})
_COOKIE_NAME_RE = re.compile(r"^[A-Za-z0-9!#$%&'*+\-.^_`|~]+=")
_SET_COOKIE_ATTRS = frozenset(
    {"expires", "max-age", "domain", "path", "secure", "httponly", "samesite"}
)


@dataclass
class CookieRecord:
    name: str
    value: str
    domain: str | None = None
    path: str | None = None
    expires: str | None = None
    max_age: int | None = None
    secure: bool = False
    httponly: bool = False
    samesite: str | None = None
    session: bool = True
    prefix: str | None = None
    flags_missing: list[str] = field(default_factory=list)
    raw: str | None = None


@dataclass
class CookieView:
    which: str
    cookies: list[CookieRecord] = field(default_factory=list)
    count: int = 0
    names: list[str] = field(default_factory=list)


@dataclass
class InspectCookiesResult:
    request_id: str | None = None
    which: str = "response"
    url: str | None = None
    method: str | None = None
    status: int | None = None
    request: CookieView | None = None
    response: CookieView | None = None
    error: str | None = None


def _header_values(raw: dict[str, str] | None, name: str) -> list[str]:
    if not raw:
        return []
    want = name.lower()
    out: list[str] = []
    for key, value in raw.items():
        if isinstance(key, str) and key.lower() == want and isinstance(value, str):
            text = value.strip()
            if text:
                out.append(text)
    return out


def split_set_cookie(value: str) -> list[str]:
    """Split one or more Set-Cookie values.

    httpx collapses multi-value headers with ``, ``, which also appears inside
    ``Expires=Wed, 21 Oct …``. Split on ``, `` only when the next token looks
    like a cookie-name, not a weekday.
    """
    text = (value or "").strip()
    if not text:
        return []
    if "\n" in text:
        return [p.strip() for p in text.splitlines() if p.strip()]

    parts: list[str] = []
    buf: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] == "," and i + 1 < n and text[i + 1] == " ":
            rest = text[i + 2 :].lstrip()
            if rest[:3].lower() in _WEEKDAYS:
                buf.append(text[i])
                i += 1
                continue
            if _COOKIE_NAME_RE.match(rest):
                chunk = "".join(buf).strip()
                if chunk:
                    parts.append(chunk)
                buf = []
                i += 2
                continue
        buf.append(text[i])
        i += 1
    chunk = "".join(buf).strip()
    if chunk:
        parts.append(chunk)
    return parts


def parse_cookie_header(value: str) -> list[CookieRecord]:
    """Parse a request Cookie header (``name=value; name2=value2``)."""
    records: list[CookieRecord] = []
    for piece in (value or "").split(";"):
        piece = piece.strip()
        if not piece:
            continue
        name, _, raw_value = piece.partition("=")
        name = name.strip()
        if not name:
            continue
        records.append(
            CookieRecord(
                name=name,
                value=raw_value.strip(),
                session=True,
                prefix=_cookie_prefix(name),
                raw=piece,
            )
        )
    return records


def parse_set_cookie(value: str) -> CookieRecord | None:
    """Parse a single Set-Cookie line into attributes."""
    text = (value or "").strip()
    if not text:
        return None
    segments = [s.strip() for s in text.split(";") if s.strip()]
    if not segments:
        return None
    name, _, raw_value = segments[0].partition("=")
    name = name.strip()
    if not name:
        return None
    rec = CookieRecord(
        name=name,
        value=raw_value.strip().strip('"'),
        raw=text,
        prefix=_cookie_prefix(name),
    )
    for attr in segments[1:]:
        key, _, attr_value = attr.partition("=")
        key_l = key.strip().lower()
        val = attr_value.strip().strip('"') if attr_value else ""
        if key_l == "secure":
            rec.secure = True
        elif key_l == "httponly":
            rec.httponly = True
        elif key_l == "samesite":
            rec.samesite = val or None
        elif key_l == "path":
            rec.path = val or None
        elif key_l == "domain":
            rec.domain = val or None
        elif key_l == "expires":
            rec.expires = val or None
        elif key_l == "max-age":
            try:
                rec.max_age = int(val)
            except ValueError:
                rec.max_age = None
        elif key_l in _SET_COOKIE_ATTRS:
            continue
    rec.session = rec.expires is None and rec.max_age is None
    missing: list[str] = []
    if not rec.secure:
        missing.append("Secure")
    if not rec.httponly:
        missing.append("HttpOnly")
    if not rec.samesite:
        missing.append("SameSite")
    rec.flags_missing = missing
    return rec


def _cookie_prefix(name: str) -> str | None:
    if name.startswith("__Host-"):
        return "__Host-"
    if name.startswith("__Secure-"):
        return "__Secure-"
    return None


def cookie_record_to_dict(rec: CookieRecord) -> dict[str, Any]:
    return {
        "name": rec.name,
        "value": rec.value,
        "domain": rec.domain,
        "path": rec.path,
        "expires": rec.expires,
        "max_age": rec.max_age,
        "secure": rec.secure,
        "httponly": rec.httponly,
        "samesite": rec.samesite,
        "session": rec.session,
        "prefix": rec.prefix,
        "flags_missing": list(rec.flags_missing),
        "raw": rec.raw,
    }


def cookie_view_to_dict(view: CookieView) -> dict[str, Any]:
    cookies = [cookie_record_to_dict(c) for c in view.cookies]
    return {
        "which": view.which,
        "cookies": cookies,
        "count": view.count,
        "names": list(view.names),
    }


def build_cookie_view_from_headers(
    raw: dict[str, str] | None, *, which: str
) -> CookieView:
    cookies: list[CookieRecord] = []
    if which == "request":
        for value in _header_values(raw, "cookie"):
            cookies.extend(parse_cookie_header(value))
    else:
        for value in _header_values(raw, "set-cookie"):
            for piece in split_set_cookie(value):
                rec = parse_set_cookie(piece)
                if rec is not None:
                    cookies.append(rec)
    return CookieView(
        which=which,
        cookies=cookies,
        count=len(cookies),
        names=[c.name for c in cookies],
    )


def inspect_cookies_from_maps(
    *,
    request_headers: dict[str, str] | None = None,
    response_headers: dict[str, str] | None = None,
    which: str = "response",
    request_id: str | None = None,
    url: str | None = None,
    method: str | None = None,
    status: int | None = None,
) -> InspectCookiesResult:
    side = (which or "response").strip().lower()
    if side not in {"request", "response", "both"}:
        return InspectCookiesResult(
            request_id=request_id,
            which=side,
            error=f"which must be 'request', 'response', or 'both' (got {which!r})",
        )
    result = InspectCookiesResult(
        request_id=request_id,
        which=side,
        url=url,
        method=method,
        status=status,
    )
    if side in {"request", "both"}:
        result.request = build_cookie_view_from_headers(
            request_headers, which="request"
        )
    if side in {"response", "both"}:
        result.response = build_cookie_view_from_headers(
            response_headers, which="response"
        )
    return result


def inspect_cookies_from_entry(
    entry: HistoryEntry,
    *,
    which: str = "response",
) -> InspectCookiesResult:
    return inspect_cookies_from_maps(
        request_headers=entry.request_headers,
        response_headers=entry.response_headers,
        which=which,
        request_id=entry.id,
        url=entry.final_url or entry.url,
        method=entry.method,
        status=entry.status,
    )


def inspect_cookies_result_to_dict(result: InspectCookiesResult) -> dict[str, Any]:
    return {
        "request_id": result.request_id,
        "which": result.which,
        "url": result.url,
        "method": result.method,
        "status": result.status,
        "request": cookie_view_to_dict(result.request) if result.request else None,
        "response": cookie_view_to_dict(result.response) if result.response else None,
        "error": result.error,
    }


__all__ = [
    "CookieRecord",
    "CookieView",
    "HeaderView",
    "InspectCookiesResult",
    "InspectHeadersResult",
    "build_cookie_view_from_headers",
    "build_header_view",
    "cookie_record_to_dict",
    "cookie_view_to_dict",
    "header_view_to_dict",
    "inspect_cookies_from_entry",
    "inspect_cookies_from_maps",
    "inspect_cookies_result_to_dict",
    "inspect_headers_from_entry",
    "inspect_headers_from_maps",
    "inspect_headers_result_to_dict",
    "parse_cookie_header",
    "parse_set_cookie",
    "split_set_cookie",
]
