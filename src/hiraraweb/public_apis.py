"""Orchestration only: Rust constructs/parses APIs; the shared guard performs HTTP."""
from __future__ import annotations

import asyncio
from hirara_core.native import native_call
from .research import _download, defer

_stack_locks: dict[asyncio.AbstractEventLoop, asyncio.Lock] = {}

async def _fetch(provider: str, request: dict, **args) -> dict:
    if request.get("error"):
        return request
    body = await _download(provider, request["url"])
    result = await native_call("external_parse", provider=provider, body=body, **args)
    backoff = result.get("backoff")
    if isinstance(backoff, int) and backoff > 0:
        defer("stackexchange", backoff)
    return result


async def search(provider: str, **args) -> dict:
    # Keep response parsing/backoff admission inside the same method lock.
    # The download's rate-limit lock alone ends before the response is parsed.
    if provider == "stackexchange":
        lock = _stack_locks.setdefault(asyncio.get_running_loop(), asyncio.Lock())
        async with lock:
            return await _search(provider, **args)
    return await _search(provider, **args)


async def _search(provider: str, **args) -> dict:
    try:
        if provider == "weather":
            request = await native_call("external_request", provider=provider, **args)
            if request.get("error"):
                return request
            location = None
            alternatives = []
            if request.get("phase") == "geocode":
                body = await _download("weather", request["url"])
                request = await native_call("external_parse", provider="weather_geocode", body=body, **args)
                if request.get("error"):
                    return request
                location, alternatives = request["location"], request["alternatives"]
            result = await _fetch("weather", request)
            return {**result, "location": location, "alternatives": alternatives}
        request = await native_call("external_request", provider=provider, **args)
        result = await _fetch(provider, request, max_results=args.get("max_results", 5))
        if provider == "stackexchange" and not result.get("error") and args.get("include_answers", True):
            ids = [r["accepted_answer_id"] for r in result["results"] if isinstance(r.get("accepted_answer_id"), int)]
            if ids and not result.get("backoff"):
                request = await native_call("external_request", provider="stackexchange_answers", ids=ids,
                                            site=args.get("site", "stackoverflow"), max_results=20)
                answers = await _fetch("stackexchange_answers", request, max_results=20)
                if answers.get("error"):
                    return {**result, "error": answers["error"], "answers_complete": False}
                by_id = {a["answer_id"]: a for a in answers["results"]}
                for question in result["results"]:
                    question["accepted_answer"] = by_id.get(question.get("accepted_answer_id"))
                result["quota_remaining"] = answers.get("quota_remaining")
                result["backoff"] = answers.get("backoff")
            result["answers_complete"] = all(
                not q.get("accepted_answer_id") or q.get("accepted_answer") is not None
                for q in result["results"])
        return result
    except Exception as exc:
        return {"results": [], "error": f"{provider} request failed: {exc}"}
