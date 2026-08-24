"""Replay recorded requests and vary one parameter across values."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from .config import HttpConfig
from .history import HistoryEntry, HistoryStore
from .request import ALLOWED_METHODS, _BLOCKED_REQUEST_HEADERS, http_request
from .request import result_to_dict as request_result_to_dict

log = logging.getLogger(__name__)

_PARAM_LOCATIONS = frozenset({"query", "header", "cookie", "body", "path", "url"})


class ReplayError(ValueError):
    """Caller-facing replay / parameter_test validation failure."""


@dataclass
class ReplayResult:
    source_id: str | None = None
    request: dict[str, Any] = field(default_factory=dict)
    response: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class ParameterTrial:
    value: str
    url: str | None = None
    status: int | None = None
    reason: str | None = None
    elapsed_ms: int | None = None
    bytes_downloaded: int | None = None
    body_preview: str | None = None
    request_id: str | None = None
    error: str | None = None


@dataclass
class ParameterTestResult:
    source_id: str | None = None
    location: str | None = None
    name: str | None = None
    values: list[str] = field(default_factory=list)
    results: list[ParameterTrial] = field(default_factory=list)
    probed: int = 0
    truncated: bool = False
    duration_ms: int | None = None
    error: str | None = None


def replay_result_to_dict(result: ReplayResult) -> dict:
    return {
        "source_id": result.source_id,
        "request": dict(result.request),
        "response": dict(result.response),
        "error": result.error,
    }


def parameter_test_result_to_dict(result: ParameterTestResult) -> dict:
    return {
        "source_id": result.source_id,
        "location": result.location,
        "name": result.name,
        "values": list(result.values),
        "results": [
            {
                "value": t.value,
                "url": t.url,
                "status": t.status,
                "reason": t.reason,
                "elapsed_ms": t.elapsed_ms,
                "bytes_downloaded": t.bytes_downloaded,
                "body_preview": t.body_preview,
                "request_id": t.request_id,
                "error": t.error,
            }
            for t in result.results
        ],
        "probed": result.probed,
        "truncated": result.truncated,
        "duration_ms": result.duration_ms,
        "error": result.error,
    }


def _client_headers(raw: dict[str, str] | None) -> dict[str, str]:
    """Drop hop-by-hop / Host headers that http_request rejects or rewrites."""
    out: dict[str, str] = {}
    if not raw:
        return out
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        name = key.strip()
        if not name:
            continue
        if name.lower() in _BLOCKED_REQUEST_HEADERS:
            continue
        out[name] = value
    return out


def _merge_headers(
    base: dict[str, str],
    overrides: dict[str, str] | None,
    *,
    merge: bool,
) -> dict[str, str]:
    if not merge:
        return _client_headers(overrides) if overrides is not None else {}
    out = _client_headers(base)
    if overrides:
        out.update(_client_headers(overrides))
    return out


def _normalize_values(values: list[str] | str | None) -> list[str]:
    if values is None:
        raise ReplayError("values is required")
    if isinstance(values, str):
        items = [v.strip() for v in values.replace("\n", ",").split(",") if v.strip()]
    elif isinstance(values, list):
        items = [str(v) for v in values]
    else:
        raise ReplayError("values must be a string or list of strings")
    if not items:
        raise ReplayError("values must be non-empty")
    return items


def _set_query(url: str, name: str, value: str) -> str:
    parts = urlsplit(url)
    pairs = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != name]
    pairs.append((name, value))
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(pairs), parts.fragment)
    )


def _set_cookie_header(headers: dict[str, str], name: str, value: str) -> dict[str, str]:
    out = dict(headers)
    cookie_key = None
    for key in out:
        if key.lower() == "cookie":
            cookie_key = key
            break
    existing = out.get(cookie_key, "") if cookie_key else ""
    parts = [p.strip() for p in existing.split(";") if p.strip()]
    kept = []
    for part in parts:
        if "=" not in part:
            kept.append(part)
            continue
        k, _ = part.split("=", 1)
        if k.strip() != name:
            kept.append(part)
    kept.append(f"{name}={value}")
    joined = "; ".join(kept)
    if cookie_key:
        out[cookie_key] = joined
    else:
        out["Cookie"] = joined
    return out


def _set_body_param(
    body: str | None,
    headers: dict[str, str],
    name: str,
    value: str,
) -> tuple[str, dict[str, str]]:
    text = "" if body is None else body
    placeholder = "{{" + name + "}}"
    if placeholder in text:
        return text.replace(placeholder, value), headers

    ct = ""
    for key, val in headers.items():
        if key.lower() == "content-type":
            ct = val.lower()
            break

    if "application/x-www-form-urlencoded" in ct or (
        not ct and text and "=" in text and "&" in text
    ):
        pairs = [(k, v) for k, v in parse_qsl(text, keep_blank_values=True) if k != name]
        pairs.append((name, value))
        out_headers = dict(headers)
        if not any(k.lower() == "content-type" for k in out_headers):
            out_headers["Content-Type"] = "application/x-www-form-urlencoded"
        return urlencode(pairs), out_headers

    if "application/json" in ct or (text[:1] in {"{", "["}):
        try:
            data = json.loads(text) if text else {}
        except json.JSONDecodeError as exc:
            raise ReplayError(f"body is not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ReplayError("JSON body must be an object to set a named parameter")
        data[name] = value
        out_headers = dict(headers)
        if not any(k.lower() == "content-type" for k in out_headers):
            out_headers["Content-Type"] = "application/json"
        return json.dumps(data, separators=(",", ":")), out_headers

    raise ReplayError(
        "cannot set body parameter: use form-urlencoded/JSON body, "
        f"or include placeholder {{{{{name}}}}} in the body"
    )


def _set_path(url: str, name: str, value: str) -> str:
    parts = urlsplit(url)
    path = parts.path
    token_braces = "{" + name + "}"
    token_mustache = "{{" + name + "}}"
    if token_mustache in path:
        path = path.replace(token_mustache, value)
    elif token_braces in path:
        path = path.replace(token_braces, value)
    elif token_mustache in url or token_braces in url:
        rebuilt = url.replace(token_mustache, value).replace(token_braces, value)
        return rebuilt
    else:
        raise ReplayError(
            f"path/url has no {{{name}}} or {{{{{name}}}}} placeholder to replace"
        )
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))


def build_variant(
    *,
    url: str,
    method: str,
    headers: dict[str, str],
    body: str | None,
    location: str,
    name: str,
    value: str,
) -> tuple[str, str, dict[str, str], str | None]:
    loc = location.strip().lower()
    if loc not in _PARAM_LOCATIONS:
        raise ReplayError(
            f"location must be one of {', '.join(sorted(_PARAM_LOCATIONS))}"
        )
    if loc == "query":
        return _set_query(url, name, value), method, headers, body
    if loc == "header":
        hdrs = dict(headers)
        hdrs[name] = value
        return url, method, hdrs, body
    if loc == "cookie":
        return url, method, _set_cookie_header(headers, name, value), body
    if loc == "body":
        new_body, hdrs = _set_body_param(body, headers, name, value)
        return url, method, hdrs, new_body
    if loc in {"path", "url"}:
        return _set_path(url, name, value), method, headers, body
    raise ReplayError(f"unsupported location: {location}")


async def request_replay(
    *,
    id: str,
    history: HistoryStore,
    url: str | None = None,
    method: str | None = None,
    headers: dict[str, str] | None = None,
    body: str | None = None,
    merge_headers: bool = True,
    timeout: float | None = None,
    follow_redirects: bool = True,
    max_redirects: int | None = None,
    max_bytes: int | None = None,
    config: HttpConfig | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    record=None,
) -> ReplayResult:
    """Re-issue a recorded request, with optional field overrides."""
    cfg = config or HttpConfig()
    sid = (id or "").strip()
    if not sid:
        return ReplayResult(error="id is required")
    entry = history.get(sid)
    if entry is None:
        return ReplayResult(source_id=sid, error=f"unknown history id: {id}")
    if not entry.url and not url:
        return ReplayResult(source_id=entry.id, error="history entry has no url")

    verb = (method or entry.method or "GET").strip().upper()
    if verb not in ALLOWED_METHODS:
        return ReplayResult(
            source_id=entry.id,
            error=f"unsupported method: {verb!r}",
        )

    target_url = (url or entry.url or "").strip()
    req_headers = _merge_headers(
        entry.request_headers, headers, merge=merge_headers
    )
    req_body = entry.request_body if body is None else body

    request_meta = {
        "method": verb,
        "url": target_url,
        "headers": req_headers,
        "body": req_body,
    }
    try:
        result = await http_request(
            target_url,
            method=verb,
            headers=req_headers,
            body=req_body,
            timeout=timeout,
            follow_redirects=follow_redirects,
            max_redirects=max_redirects,
            max_bytes=max_bytes,
            config=cfg,
            transport=transport,
        )
        payload = request_result_to_dict(result)
    except Exception as exc:  # noqa: BLE001
        log.exception("request_replay failed")
        return ReplayResult(
            source_id=entry.id,
            request=request_meta,
            error=f"request_replay failed: {exc}",
        )

    if record is not None:
        recorded = record(payload)
        payload["request_id"] = recorded.id

    return ReplayResult(source_id=entry.id, request=request_meta, response=payload)


async def parameter_test(
    *,
    location: str,
    name: str,
    values: list[str] | str,
    id: str | None = None,
    url: str | None = None,
    method: str | None = None,
    headers: dict[str, str] | None = None,
    body: str | None = None,
    history: HistoryStore | None = None,
    timeout: float | None = None,
    follow_redirects: bool = True,
    max_redirects: int | None = None,
    max_bytes: int | None = None,
    concurrency: int | None = None,
    include_body: bool = False,
    body_preview_chars: int = 200,
    config: HttpConfig | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    record=None,
) -> ParameterTestResult:
    """Send one base request once per parameter value."""
    cfg = config or HttpConfig()
    started = time.perf_counter()
    source_id = None

    try:
        value_list = _normalize_values(values)
    except ReplayError as exc:
        return ParameterTestResult(
            location=location, name=name, error=str(exc)
        )

    max_values = cfg.param_test_max_values
    truncated = len(value_list) > max_values
    value_list = value_list[:max_values]

    base_url = (url or "").strip()
    base_method = (method or "GET").strip().upper()
    base_headers = _client_headers(headers)
    base_body = body

    sid = (id or "").strip() if id is not None else ""
    if sid:
        if history is None:
            return ParameterTestResult(
                location=location,
                name=name,
                error="id requires an in-process history store",
            )
        entry = history.get(sid)
        if entry is None:
            return ParameterTestResult(
                location=location,
                name=name,
                error=f"unknown history id: {id}",
            )
        source_id = entry.id
        base_url = base_url or (entry.url or "")
        base_method = (method or entry.method or "GET").strip().upper()
        if headers is None:
            base_headers = _client_headers(entry.request_headers)
        else:
            base_headers = _merge_headers(
                entry.request_headers, headers, merge=True
            )
        if body is None:
            base_body = entry.request_body

    if not base_url:
        return ParameterTestResult(
            source_id=source_id,
            location=location,
            name=name,
            error="url or id with a recorded url is required",
        )
    if not (name or "").strip():
        return ParameterTestResult(
            source_id=source_id,
            location=location,
            name=name,
            error="name is required",
        )
    if base_method not in ALLOWED_METHODS:
        return ParameterTestResult(
            source_id=source_id,
            location=location,
            name=name,
            error=f"unsupported method: {base_method!r}",
        )

    workers = cfg.param_test_concurrency if concurrency is None else int(concurrency)
    if workers <= 0:
        return ParameterTestResult(
            source_id=source_id,
            location=location,
            name=name,
            error="concurrency must be > 0",
        )

    sem = asyncio.Semaphore(workers)
    preview = max(0, int(body_preview_chars))

    async def one(value: str) -> ParameterTrial:
        try:
            v_url, v_method, v_headers, v_body = build_variant(
                url=base_url,
                method=base_method,
                headers=base_headers,
                body=base_body,
                location=location,
                name=name.strip(),
                value=value,
            )
        except ReplayError as exc:
            return ParameterTrial(value=value, error=str(exc))

        async with sem:
            try:
                result = await http_request(
                    v_url,
                    method=v_method,
                    headers=v_headers,
                    body=v_body,
                    timeout=timeout,
                    follow_redirects=follow_redirects,
                    max_redirects=max_redirects,
                    max_bytes=max_bytes,
                    config=cfg,
                    transport=transport,
                )
                payload = request_result_to_dict(result)
            except Exception as exc:  # noqa: BLE001
                log.exception("parameter_test probe failed")
                return ParameterTrial(
                    value=value, url=v_url, error=f"parameter_test failed: {exc}"
                )

        request_id = None
        if record is not None:
            recorded = record(payload)
            request_id = recorded.id
            payload["request_id"] = request_id

        body_text = payload.get("body")
        body_preview = None
        if include_body and isinstance(body_text, str):
            body_preview = body_text if preview <= 0 else body_text[:preview]

        return ParameterTrial(
            value=value,
            url=payload.get("final_url") or payload.get("url") or v_url,
            status=payload.get("status"),
            reason=payload.get("reason"),
            elapsed_ms=payload.get("elapsed_ms"),
            bytes_downloaded=payload.get("bytes_downloaded"),
            body_preview=body_preview,
            request_id=request_id,
            error=payload.get("error"),
        )

    trials = await asyncio.gather(*(one(v) for v in value_list))
    return ParameterTestResult(
        source_id=source_id,
        location=location.strip().lower(),
        name=name.strip(),
        values=list(value_list),
        results=list(trials),
        probed=len(trials),
        truncated=truncated,
        duration_ms=int((time.perf_counter() - started) * 1000),
    )


__all__ = [
    "ParameterTestResult",
    "ParameterTrial",
    "ReplayError",
    "ReplayResult",
    "build_variant",
    "parameter_test",
    "parameter_test_result_to_dict",
    "request_replay",
    "replay_result_to_dict",
]
