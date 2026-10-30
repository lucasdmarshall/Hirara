"""Guarded HTTP transport for Rust research tools. No configurable endpoints."""
from __future__ import annotations

import asyncio
import time

from hirara_core.download import safe_download
from hirara_core.native import native_call

# Shared by Toolsets on the same event loop. Separate processes must coordinate
# externally if their combined traffic approaches provider limits.
_limits: dict[tuple[asyncio.AbstractEventLoop, str], tuple[asyncio.Lock, float]] = {}


def defer(provider: str, seconds: int) -> None:
    key = (asyncio.get_running_loop(), provider)
    lock, last = _limits.setdefault(key, (asyncio.Lock(), 0.0))
    _limits[key] = (lock, max(last, time.monotonic() + seconds))


async def _download(provider: str, url: str) -> str:
    if provider == "stackexchange_answers":
        provider = "stackexchange"
    key = (asyncio.get_running_loop(), provider)
    lock, _ = _limits.setdefault(key, (asyncio.Lock(), 0.0))
    async with lock:
        last = _limits[key][1]
        interval = 3.1 if provider == "arxiv" else 0.4
        await asyncio.sleep(max(0, last + interval - time.monotonic()))
        _limits[key] = (lock, time.monotonic())
        response = await safe_download(
            url, max_bytes=2_000_000, max_redirects=0, timeout=20,
            accept="application/atom+xml, application/json",
            allow_private_ips=False,
        )
        if response.truncated:
            raise ValueError("research response exceeds 2 MB")
        return response.content.decode("utf-8")


async def search(provider: str, query: str, max_results: int = 5, start: int = 0) -> dict:
    envelope = {"query": query, "provider": provider, "results": [], "total": None,
                "start": start, "error": None}
    try:
        if isinstance(max_results, bool) or not isinstance(max_results, int) or not 1 <= max_results <= 20:
            raise ValueError("max_results must be between 1 and 20")
        if isinstance(start, bool) or not isinstance(start, int) or not 0 <= start <= 10_000:
            raise ValueError("start must be between 0 and 10000")
        request = await native_call("research_request", provider=provider, query=query,
                                    max_results=max_results, start=start)
        if request.get("error"):
            return {**envelope, "error": request["error"]}
        body = await _download(provider, request["url"])
        if provider == "pubmed":
            ids = await native_call("research_parse", provider="pubmed_ids", body=body,
                                    max_results=max_results)
            if ids.get("error"):
                return {**envelope, "error": ids["error"]}
            envelope["total"] = ids["total"]
            if not ids["ids"]:
                return envelope
            body = await _download(provider, ids["url"])
        parsed = await native_call("research_parse", provider=provider, body=body,
                                   max_results=max_results)
        return {**envelope, **parsed}
    except Exception as exc:
        return {**envelope, "error": f"{provider} search failed: {exc}"}
