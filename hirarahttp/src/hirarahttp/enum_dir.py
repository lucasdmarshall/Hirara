"""Probe a base URL for existing paths (directory / file enum).

HEAD/GET each path through the same resolve → pin perimeter as
``http_request``. Does not follow redirects (reports Location instead) and
does not record into http_history.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx

from hirara_core.ssrf import BlockedURL, Target, resolve_target

from .config import HttpConfig

log = logging.getLogger(__name__)

DEFAULT_PATHS: tuple[str, ...] = (
    "robots.txt",
    "sitemap.xml",
    "favicon.ico",
    "security.txt",
    ".well-known/security.txt",
    ".well-known/openid-configuration",
    "admin",
    "login",
    "signin",
    "api",
    "api/v1",
    "docs",
    "swagger",
    "swagger.json",
    "openapi.json",
    "graphql",
    "health",
    "healthz",
    "ready",
    "status",
    "metrics",
    "static",
    "assets",
    "uploads",
    "images",
    "css",
    "js",
    "backup",
    "backups",
    ".git/HEAD",
    ".env",
    "index.html",
    "index.php",
    "README.md",
    "LICENSE",
    "server-status",
    "phpmyadmin",
    "wp-admin",
    "wp-login.php",
)

_ENUM_METHODS = frozenset({"HEAD", "GET", "OPTIONS"})
_HIDE_STATUSES = frozenset({404, 410})


class EnumError(ValueError):
    """Caller-facing directory_enum validation failure."""


@dataclass
class PathHit:
    path: str
    url: str | None = None
    status: int | None = None
    reason: str | None = None
    location: str | None = None
    content_type: str | None = None
    content_length: int | None = None
    elapsed_ms: int | None = None
    error: str | None = None


@dataclass
class EnumResult:
    url: str | None = None
    method: str | None = None
    paths: list[str] = field(default_factory=list)
    results: list[PathHit] = field(default_factory=list)
    found: list[PathHit] = field(default_factory=list)
    found_count: int = 0
    probed: int = 0
    truncated: bool = False
    duration_ms: int | None = None
    error: str | None = None


def _pin(target: Target) -> httpx.URL:
    return httpx.URL(target.url).copy_with(host=target.ip)


def normalize_paths(
    paths: list[str] | str | None,
    *,
    default: tuple[str, ...],
    max_paths: int,
) -> tuple[list[str], bool]:
    """Parse paths; returns (unique list, truncated)."""
    if paths is None:
        raw_items: list[str] = list(default)
    elif isinstance(paths, str):
        raw_items = [
            p.strip()
            for p in paths.replace("\n", ",").split(",")
            if p.strip()
        ]
    elif isinstance(paths, list):
        raw_items = [str(p).strip() for p in paths if str(p).strip()]
    else:
        raise EnumError("paths must be a list of strings or a comma-separated string")

    seen: set[str] = set()
    out: list[str] = []
    truncated = False
    for item in raw_items:
        cleaned = _clean_path(item)
        if cleaned in seen:
            continue
        if len(out) >= max_paths:
            truncated = True
            break
        seen.add(cleaned)
        out.append(cleaned)
    return out, truncated


def _clean_path(path: str) -> str:
    cleaned = (path or "").strip().lstrip("/")
    if not cleaned:
        raise EnumError("path must be non-empty")
    if len(cleaned) > 256:
        raise EnumError("path exceeds 256 characters")
    if "://" in cleaned or cleaned.startswith("//") or "\\" in cleaned:
        raise EnumError(f"path is not a relative path: {path!r}")
    if ".." in cleaned.split("/"):
        raise EnumError("path must not contain '..'")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in cleaned):
        raise EnumError("path contains control characters")
    if "@" in cleaned:
        raise EnumError("path must not contain '@'")
    return cleaned


def _join(base: str, path: str) -> str:
    root = base.rstrip("/") + "/"
    return str(httpx.URL(root).join(path))


def hit_to_dict(hit: PathHit) -> dict:
    return {
        "path": hit.path,
        "url": hit.url,
        "status": hit.status,
        "reason": hit.reason,
        "location": hit.location,
        "content_type": hit.content_type,
        "content_length": hit.content_length,
        "elapsed_ms": hit.elapsed_ms,
        "error": hit.error,
    }


def enum_result_to_dict(result: EnumResult) -> dict:
    return {
        "url": result.url,
        "method": result.method,
        "paths": list(result.paths),
        "results": [hit_to_dict(h) for h in result.results],
        "found": [hit_to_dict(h) for h in result.found],
        "found_count": result.found_count,
        "probed": result.probed,
        "truncated": result.truncated,
        "duration_ms": result.duration_ms,
        "error": result.error,
    }


def _content_length(headers: httpx.Headers) -> int | None:
    raw = headers.get("content-length")
    if raw is None:
        return None
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


async def directory_enum(
    url: str,
    *,
    paths: list[str] | str | None = None,
    method: str = "HEAD",
    timeout: float | None = None,
    concurrency: int | None = None,
    include_not_found: bool = False,
    config: HttpConfig | None = None,
    resolver=None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> EnumResult:
    """Probe ``url`` + each path; return statuses without following redirects."""
    cfg = config or HttpConfig()
    started = time.perf_counter()

    cleaned = (url or "").strip()
    if not cleaned:
        return EnumResult(error="url is required")
    parts = urlsplit(cleaned)
    if parts.scheme not in {"http", "https"}:
        return EnumResult(url=cleaned, error="url must be http(s)")
    if not parts.hostname:
        return EnumResult(url=cleaned, error="url has no host")

    verb = (method or "HEAD").strip().upper()
    if verb not in _ENUM_METHODS:
        return EnumResult(
            url=cleaned,
            method=verb,
            error=f"unsupported method: {method!r} (HEAD, GET, or OPTIONS)",
        )

    wait = cfg.enum_timeout if timeout is None else float(timeout)
    if wait <= 0:
        return EnumResult(url=cleaned, method=verb, error="timeout must be > 0")
    workers = cfg.enum_concurrency if concurrency is None else int(concurrency)
    if workers < 1:
        return EnumResult(url=cleaned, method=verb, error="concurrency must be >= 1")
    max_workers = max(1, cfg.enum_concurrency)
    workers = min(workers, max_workers)

    try:
        path_list, truncated = normalize_paths(
            paths, default=DEFAULT_PATHS, max_paths=cfg.enum_max_paths
        )
    except EnumError as exc:
        return EnumResult(url=cleaned, method=verb, error=str(exc))
    if not path_list:
        return EnumResult(url=cleaned, method=verb, error="no paths to probe")

    resolve_kwargs: dict = {"allow_private_ips": cfg.allow_private_ips}
    if resolver is not None:
        resolve_kwargs["resolver"] = resolver

    try:
        resolve_target(cleaned, **resolve_kwargs)
    except BlockedURL as exc:
        return EnumResult(
            url=cleaned,
            method=verb,
            paths=path_list,
            truncated=truncated,
            duration_ms=int((time.perf_counter() - started) * 1000),
            error=f"blocked: {exc}",
        )

    limits = httpx.Limits(max_connections=workers, max_keepalive_connections=0)
    sem = asyncio.Semaphore(workers)

    async def probe(client: httpx.AsyncClient, path: str) -> PathHit:
        target_url = _join(cleaned, path)
        t0 = time.perf_counter()
        async with sem:
            try:
                target = resolve_target(target_url, **resolve_kwargs)
            except BlockedURL as exc:
                return PathHit(
                    path=path,
                    url=target_url,
                    elapsed_ms=int((time.perf_counter() - t0) * 1000),
                    error=f"blocked: {exc}",
                )
            try:
                request = client.build_request(
                    verb,
                    _pin(target),
                    headers={
                        "Host": target.host_header,
                        "Accept": "*/*",
                        "User-Agent": cfg.user_agent,
                    },
                    extensions={"sni_hostname": target.host},
                )
                response = await client.send(request, stream=True)
                try:
                    loc = response.headers.get("location")
                    ctype = response.headers.get("content-type")
                    return PathHit(
                        path=path,
                        url=target_url,
                        status=response.status_code,
                        reason=response.reason_phrase or None,
                        location=loc,
                        content_type=(
                            ctype.split(";")[0].strip().lower() if ctype else None
                        ),
                        content_length=_content_length(response.headers),
                        elapsed_ms=int((time.perf_counter() - t0) * 1000),
                    )
                finally:
                    await response.aclose()
            except httpx.TimeoutException as exc:
                return PathHit(
                    path=path,
                    url=target_url,
                    elapsed_ms=int((time.perf_counter() - t0) * 1000),
                    error=f"timeout: {exc}",
                )
            except httpx.HTTPError as exc:
                return PathHit(
                    path=path,
                    url=target_url,
                    elapsed_ms=int((time.perf_counter() - t0) * 1000),
                    error=f"transport error: {exc}",
                )

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(wait),
            follow_redirects=False,
            limits=limits,
            transport=transport,
        ) as client:
            hits = list(await asyncio.gather(*[probe(client, p) for p in path_list]))
    except Exception as exc:  # noqa: BLE001
        log.exception("directory_enum failed")
        return EnumResult(
            url=cleaned,
            method=verb,
            paths=path_list,
            truncated=truncated,
            duration_ms=int((time.perf_counter() - started) * 1000),
            error=f"directory_enum failed: {exc}",
        )

    hits.sort(key=lambda h: h.path)
    found = [
        h
        for h in hits
        if h.error is None and h.status is not None and h.status not in _HIDE_STATUSES
    ]
    results = hits if include_not_found else found
    return EnumResult(
        url=cleaned.rstrip("/") + "/",
        method=verb,
        paths=path_list,
        results=results,
        found=found,
        found_count=len(found),
        probed=len(hits),
        truncated=truncated,
        duration_ms=int((time.perf_counter() - started) * 1000),
    )


__all__ = [
    "DEFAULT_PATHS",
    "EnumError",
    "EnumResult",
    "PathHit",
    "directory_enum",
    "enum_result_to_dict",
    "hit_to_dict",
    "normalize_paths",
]
