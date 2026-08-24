"""Structured inspection helpers for recorded HTTP exchanges."""

from __future__ import annotations

import json
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


# --- response body / status -------------------------------------------------

_TITLE_RE = re.compile(
    r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL
)
_JSON_MAX_KEYS = 50
_DEFAULT_PREVIEW = 512
_MAX_PREVIEW = 8000


def status_class_for(code: int | None) -> str | None:
    if code is None:
        return None
    bucket = int(code) // 100
    return {1: "1xx", 2: "2xx", 3: "3xx", 4: "4xx", 5: "5xx"}.get(bucket, "unknown")


def _charset_from_content_type(content_type: str | None) -> str | None:
    if not content_type:
        return None
    ct = content_type.lower()
    if "charset=" not in ct:
        return None
    return ct.split("charset=", 1)[1].split(";")[0].strip().strip("\"'") or None


def _media_type(content_type: str | None) -> str | None:
    if not content_type:
        return None
    return content_type.split(";", 1)[0].strip().lower() or None


def classify_body_kind(
    *,
    content_type: str | None,
    body: str | None,
    body_encoding: str | None,
) -> str:
    if body_encoding == "base64":
        return "binary"
    if body is None or body == "":
        return "empty"
    media = _media_type(content_type) or ""
    stripped = body.lstrip()
    if media.endswith("+json") or media in {"application/json", "text/json"}:
        return "json"
    if "html" in media:
        return "html"
    if "xml" in media or media.endswith("+xml"):
        return "xml"
    if media.startswith("text/") or media in {
        "application/javascript",
        "application/x-www-form-urlencoded",
    }:
        return "text"
    if stripped[:1] in "{[":
        return "json"
    if stripped[:1] == "<":
        lower = stripped[:64].lower()
        if "html" in lower or lower.startswith("<!doctype"):
            return "html"
        return "xml"
    if media:
        return "unknown"
    return "text"


def _json_shape(value: Any) -> tuple[str, list[str] | None, int | None]:
    if value is None:
        return "null", None, None
    if isinstance(value, bool):
        return "boolean", None, None
    if isinstance(value, (int, float)):
        return "number", None, None
    if isinstance(value, str):
        return "string", None, len(value)
    if isinstance(value, list):
        return "array", None, len(value)
    if isinstance(value, dict):
        keys = [str(k) for k in list(value.keys())[:_JSON_MAX_KEYS]]
        return "object", keys, len(value)
    return type(value).__name__, None, None


@dataclass
class InspectResponseResult:
    request_id: str | None = None
    url: str | None = None
    final_url: str | None = None
    method: str | None = None
    status: int | None = None
    reason: str | None = None
    status_class: str | None = None
    ok: bool | None = None
    content_type: str | None = None
    charset: str | None = None
    location: str | None = None
    body_kind: str | None = None
    body_chars: int | None = None
    bytes_downloaded: int | None = None
    truncated: bool = False
    body_stored: bool = True
    body_encoding: str | None = None
    json_type: str | None = None
    json_keys: list[str] | None = None
    json_length: int | None = None
    json_error: str | None = None
    json: Any = None
    html_title: str | None = None
    preview: str | None = None
    body: str | None = None
    redirects: list[str] = field(default_factory=list)
    redirect_count: int = 0
    elapsed_ms: int | None = None
    error: str | None = None


def inspect_response_from_parts(
    *,
    status: int | None = None,
    reason: str | None = None,
    headers: dict[str, str] | None = None,
    body: str | None = None,
    body_encoding: str | None = None,
    truncated: bool = False,
    body_stored: bool = True,
    bytes_downloaded: int | None = None,
    include_body: bool = False,
    preview_chars: int = _DEFAULT_PREVIEW,
    request_id: str | None = None,
    url: str | None = None,
    final_url: str | None = None,
    method: str | None = None,
    redirects: list[str] | None = None,
    elapsed_ms: int | None = None,
) -> InspectResponseResult:
    by_name = {k.lower(): v for k, v in (headers or {}).items() if isinstance(k, str) and isinstance(v, str)}
    content_type = by_name.get("content-type")
    preview_n = max(0, min(int(preview_chars), _MAX_PREVIEW))
    kind = classify_body_kind(
        content_type=content_type, body=body, body_encoding=body_encoding
    )
    result = InspectResponseResult(
        request_id=request_id,
        url=url,
        final_url=final_url,
        method=method,
        status=status,
        reason=reason,
        status_class=status_class_for(status),
        ok=None if status is None else 200 <= int(status) < 300,
        content_type=content_type,
        charset=_charset_from_content_type(content_type),
        location=by_name.get("location"),
        body_kind=kind,
        body_chars=len(body) if isinstance(body, str) else None,
        bytes_downloaded=bytes_downloaded,
        truncated=truncated,
        body_stored=body_stored,
        body_encoding=body_encoding,
        redirects=list(redirects or []),
        redirect_count=len(redirects or []),
        elapsed_ms=elapsed_ms,
    )
    if kind == "json" and isinstance(body, str) and body_encoding != "base64":
        try:
            parsed = json.loads(body)
            jtype, keys, length = _json_shape(parsed)
            result.json_type = jtype
            result.json_keys = keys
            result.json_length = length
            if include_body:
                result.json = parsed
        except json.JSONDecodeError as exc:
            result.json_error = str(exc)
    if kind == "html" and isinstance(body, str):
        match = _TITLE_RE.search(body)
        if match:
            title = re.sub(r"\s+", " ", match.group(1)).strip()
            result.html_title = title[:200] or None
    if isinstance(body, str) and preview_n and body_encoding != "base64":
        result.preview = body[:preview_n]
    elif isinstance(body, str) and preview_n and body_encoding == "base64":
        result.preview = body[:preview_n]
    if include_body:
        result.body = body
    return result


def inspect_response_from_entry(
    entry: HistoryEntry,
    *,
    include_body: bool = False,
    preview_chars: int = _DEFAULT_PREVIEW,
) -> InspectResponseResult:
    return inspect_response_from_parts(
        status=entry.status,
        reason=entry.reason,
        headers=entry.response_headers,
        body=entry.body,
        body_encoding=entry.body_encoding,
        truncated=entry.truncated,
        body_stored=entry.body_stored,
        bytes_downloaded=entry.bytes_downloaded,
        include_body=include_body,
        preview_chars=preview_chars,
        request_id=entry.id,
        url=entry.url,
        final_url=entry.final_url,
        method=entry.method,
        redirects=entry.redirects,
        elapsed_ms=entry.elapsed_ms,
    )


def inspect_response_result_to_dict(result: InspectResponseResult) -> dict[str, Any]:
    return {
        "request_id": result.request_id,
        "url": result.url,
        "final_url": result.final_url,
        "method": result.method,
        "status": result.status,
        "reason": result.reason,
        "status_class": result.status_class,
        "ok": result.ok,
        "content_type": result.content_type,
        "charset": result.charset,
        "location": result.location,
        "body_kind": result.body_kind,
        "body_chars": result.body_chars,
        "bytes_downloaded": result.bytes_downloaded,
        "truncated": result.truncated,
        "body_stored": result.body_stored,
        "body_encoding": result.body_encoding,
        "json_type": result.json_type,
        "json_keys": list(result.json_keys) if result.json_keys is not None else None,
        "json_length": result.json_length,
        "json_error": result.json_error,
        "json": result.json,
        "html_title": result.html_title,
        "preview": result.preview,
        "body": result.body,
        "redirects": list(result.redirects),
        "redirect_count": result.redirect_count,
        "elapsed_ms": result.elapsed_ms,
        "error": result.error,
    }


__all__ = [
    "CookieRecord",
    "CookieView",
    "HeaderView",
    "InspectCookiesResult",
    "InspectHeadersResult",
    "InspectResponseResult",
    "build_cookie_view_from_headers",
    "build_header_view",
    "classify_body_kind",
    "cookie_record_to_dict",
    "cookie_view_to_dict",
    "header_view_to_dict",
    "inspect_cookies_from_entry",
    "inspect_cookies_from_maps",
    "inspect_cookies_result_to_dict",
    "inspect_headers_from_entry",
    "inspect_headers_from_maps",
    "inspect_headers_result_to_dict",
    "inspect_response_from_entry",
    "inspect_response_from_parts",
    "inspect_response_result_to_dict",
    "parse_cookie_header",
    "parse_set_cookie",
    "split_set_cookie",
    "status_class_for",
]
