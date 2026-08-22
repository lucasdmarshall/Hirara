"""Raw HTTP request through the SSRF perimeter.

Clones the resolve → pin → stream-cap → re-validate-redirect loop from
``hirara_core.download.safe_download``, but accepts method / headers / body and
returns 4xx/5xx bodies instead of raising on HTTP errors.
"""

from __future__ import annotations

import base64
import logging
import time
from dataclasses import dataclass, field

import httpx

from hirara_core.ssrf import BlockedURL, Target, resolve_target

from .config import HttpConfig

log = logging.getLogger(__name__)

ALLOWED_METHODS = frozenset(
    {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}
)

# Headers the client must not override — we set Host / length ourselves, and
# hop-by-hop headers must not cross the pin boundary.
_BLOCKED_REQUEST_HEADERS = frozenset(
    {
        "host",
        "content-length",
        "transfer-encoding",
        "connection",
        "keep-alive",
        "proxy-connection",
        "proxy-authorization",
        "te",
        "trailer",
        "upgrade",
    }
)

_TEXTISH_TYPES = (
    "text/",
    "application/json",
    "application/xml",
    "application/javascript",
    "application/xhtml",
    "application/atom",
    "application/rss",
    "application/x-www-form-urlencoded",
    "application/problem+json",
    "application/ld+json",
    "image/svg+xml",
)


class RequestError(ValueError):
    """Caller-facing validation / transport failure (not SSRF)."""


@dataclass
class RequestResult:
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


def _pin(target: Target) -> httpx.URL:
    return httpx.URL(target.url).copy_with(host=target.ip)


async def _read_capped(response: httpx.Response, max_bytes: int) -> tuple[bytes, bool]:
    chunks: list[bytes] = []
    total = 0
    hit_cap = False
    async for chunk in response.aiter_bytes():
        remaining = max_bytes - total
        if len(chunk) >= remaining:
            chunks.append(chunk[:remaining])
            total += remaining
            hit_cap = True
            break
        chunks.append(chunk)
        total += len(chunk)
    return b"".join(chunks), hit_cap


def _normalize_headers(
    headers: dict[str, str] | None,
    *,
    max_headers: int,
    max_header_bytes: int,
) -> dict[str, str]:
    if not headers:
        return {}
    if not isinstance(headers, dict):
        raise RequestError("headers must be an object of string keys to string values")
    if len(headers) > max_headers:
        raise RequestError(f"too many headers (max {max_headers})")

    out: dict[str, str] = {}
    total = 0
    for key, value in headers.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise RequestError("headers must be string keys to string values")
        name = key.strip()
        if not name:
            raise RequestError("header name must be non-empty")
        lower = name.lower()
        if lower in _BLOCKED_REQUEST_HEADERS:
            raise RequestError(f"header {name!r} is not allowed")
        total += len(name) + len(value)
        if total > max_header_bytes:
            raise RequestError(f"headers exceed {max_header_bytes} bytes")
        out[name] = value
    return out


def _encode_body(body: str | bytes | None, *, max_bytes: int) -> bytes | None:
    if body is None:
        return None
    if isinstance(body, bytes):
        raw = body
    elif isinstance(body, str):
        raw = body.encode("utf-8")
    else:
        raise RequestError("body must be a string")
    if len(raw) > max_bytes:
        raise RequestError(f"request body exceeds {max_bytes} bytes")
    return raw


def _decode_body(raw: bytes, content_type: str) -> tuple[str, str]:
    ct = (content_type or "").lower()
    textish = any(ct.startswith(p) or p in ct for p in _TEXTISH_TYPES)
    if textish or not raw:
        charset = "utf-8"
        if "charset=" in ct:
            charset = (
                ct.split("charset=", 1)[1].split(";")[0].strip().strip("\"'") or "utf-8"
            )
        try:
            text = raw.decode(charset)
            enc = "utf-8" if charset.lower() in {"utf-8", "utf8"} else charset
            return text, enc
        except (LookupError, UnicodeDecodeError):
            return raw.decode("utf-8", errors="replace"), "utf-8"
    return base64.b64encode(raw).decode("ascii"), "base64"


def _header_map(headers: httpx.Headers) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in headers.multi_items():
        if key in out:
            out[key] = f"{out[key]}, {value}"
        else:
            out[key] = value
    return out


def _finalize(
    *,
    method: str,
    url: str,
    final_url: str,
    response: httpx.Response,
    body_bytes: bytes,
    truncated: bool,
    redirects: list[str],
    request_headers: dict[str, str],
    started: float,
    error: str | None = None,
) -> RequestResult:
    content_type = response.headers.get("content-type", "")
    body_text, encoding = _decode_body(body_bytes, content_type)
    return RequestResult(
        method=method,
        url=url,
        final_url=final_url,
        status=response.status_code,
        reason=response.reason_phrase or None,
        request_headers=request_headers,
        response_headers=_header_map(response.headers),
        body=body_text,
        body_encoding=encoding,
        truncated=truncated,
        bytes_downloaded=len(body_bytes),
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        redirects=list(redirects),
        error=error,
    )


async def http_request(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: str | None = None,
    timeout: float | None = None,
    follow_redirects: bool = True,
    max_redirects: int | None = None,
    max_bytes: int | None = None,
    config: HttpConfig | None = None,
    resolver=None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> RequestResult:
    """Issue an HTTP request through the SSRF guard."""
    cfg = config or HttpConfig()
    started = time.perf_counter()

    cleaned_url = (url or "").strip()
    if not cleaned_url:
        return RequestResult(error="url is required")

    verb = (method or "GET").strip().upper()
    if verb not in ALLOWED_METHODS:
        return RequestResult(
            method=verb or None,
            url=cleaned_url,
            error=f"unsupported method: {method!r}",
        )

    wait = cfg.timeout if timeout is None else float(timeout)
    if wait <= 0:
        return RequestResult(method=verb, url=cleaned_url, error="timeout must be > 0")

    hop_budget = cfg.max_redirects if max_redirects is None else int(max_redirects)
    if hop_budget < 0:
        return RequestResult(
            method=verb, url=cleaned_url, error="max_redirects must be >= 0"
        )
    if not follow_redirects:
        hop_budget = 0

    body_cap = cfg.max_bytes if max_bytes is None else int(max_bytes)
    if body_cap <= 0:
        return RequestResult(method=verb, url=cleaned_url, error="max_bytes must be > 0")
    body_cap = min(body_cap, cfg.max_bytes)

    try:
        custom = _normalize_headers(
            headers,
            max_headers=cfg.max_headers,
            max_header_bytes=cfg.max_header_bytes,
        )
        payload = _encode_body(body, max_bytes=cfg.max_request_body_bytes)
    except RequestError as exc:
        return RequestResult(method=verb, url=cleaned_url, error=str(exc))

    if payload is not None and verb in {"GET", "HEAD"}:
        return RequestResult(
            method=verb,
            url=cleaned_url,
            error=f"{verb} requests cannot include a body",
        )

    resolve_kwargs: dict = {"allow_private_ips": cfg.allow_private_ips}
    if resolver is not None:
        resolve_kwargs["resolver"] = resolver

    redirects: list[str] = []
    current = cleaned_url
    sent_headers: dict[str, str] = {}
    active_method = verb
    active_body = payload

    limits = httpx.Limits(max_connections=4, max_keepalive_connections=0)
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(wait),
            follow_redirects=False,
            limits=limits,
            transport=transport,
        ) as client:
            for hop in range(hop_budget + 1):
                try:
                    target = resolve_target(current, **resolve_kwargs)
                except BlockedURL as exc:
                    return RequestResult(
                        method=verb,
                        url=cleaned_url,
                        final_url=current,
                        redirects=list(redirects),
                        elapsed_ms=int((time.perf_counter() - started) * 1000),
                        error=f"blocked: {exc}",
                    )

                req_headers = {
                    "Host": target.host_header,
                    "Accept": "*/*",
                    "Accept-Encoding": "gzip, deflate",
                    "User-Agent": cfg.user_agent,
                }
                req_headers.update(custom)
                req_headers["Host"] = target.host_header
                sent_headers = dict(req_headers)

                request = client.build_request(
                    active_method,
                    _pin(target),
                    headers=req_headers,
                    content=active_body,
                    extensions={"sni_hostname": target.host},
                )

                response = await client.send(request, stream=True)
                try:
                    if response.is_redirect and hop < hop_budget:
                        location = response.headers.get("location")
                        if not location:
                            body_bytes, truncated = await _read_capped(
                                response, body_cap
                            )
                            return _finalize(
                                method=active_method,
                                url=cleaned_url,
                                final_url=current,
                                response=response,
                                body_bytes=body_bytes,
                                truncated=truncated,
                                redirects=redirects,
                                request_headers=sent_headers,
                                started=started,
                                error="redirect with no Location header",
                            )
                        redirects.append(current)
                        # 303 always becomes GET without body; 301/302 drop body
                        # for methods that typically resubmit as GET.
                        if response.status_code == 303 or (
                            response.status_code in {301, 302}
                            and active_method
                            in {"POST", "PUT", "PATCH", "DELETE"}
                        ):
                            active_method = "GET"
                            active_body = None
                        current = str(httpx.URL(current).join(location))
                        continue

                    body_bytes, truncated = await _read_capped(response, body_cap)
                finally:
                    await response.aclose()

                return _finalize(
                    method=active_method,
                    url=cleaned_url,
                    final_url=current,
                    response=response,
                    body_bytes=body_bytes,
                    truncated=truncated,
                    redirects=redirects,
                    request_headers=sent_headers,
                    started=started,
                )

            return RequestResult(
                method=active_method,
                url=cleaned_url,
                final_url=current,
                redirects=list(redirects),
                request_headers=sent_headers,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                error=f"exceeded {hop_budget} redirects",
            )
    except httpx.TimeoutException as exc:
        return RequestResult(
            method=verb,
            url=cleaned_url,
            final_url=current,
            redirects=list(redirects),
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            error=f"timeout: {exc}",
        )
    except httpx.HTTPError as exc:
        return RequestResult(
            method=verb,
            url=cleaned_url,
            final_url=current,
            redirects=list(redirects),
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            error=f"transport error: {exc}",
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("http_request failed")
        return RequestResult(
            method=verb,
            url=cleaned_url,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            error=f"http_request failed: {exc}",
        )


def result_to_dict(result: RequestResult) -> dict:
    return {
        "method": result.method,
        "url": result.url,
        "final_url": result.final_url,
        "status": result.status,
        "reason": result.reason,
        "request_headers": result.request_headers,
        "response_headers": result.response_headers,
        "body": result.body,
        "body_encoding": result.body_encoding,
        "truncated": result.truncated,
        "bytes_downloaded": result.bytes_downloaded,
        "elapsed_ms": result.elapsed_ms,
        "redirects": list(result.redirects),
        "error": result.error,
    }


__all__ = [
    "ALLOWED_METHODS",
    "RequestError",
    "RequestResult",
    "http_request",
    "result_to_dict",
]
