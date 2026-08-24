"""Compare two HTTP responses (by history id or inline snapshots)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .history import HistoryEntry, HistoryStore

_DEFAULT_IGNORE_HEADERS = frozenset(
    {
        "date",
        "age",
        "expires",
        "last-modified",
        "etag",
        "cf-ray",
        "x-request-id",
        "x-amzn-trace-id",
        "server-timing",
        "nel",
        "report-to",
    }
)


class CompareError(ValueError):
    """Caller-facing response_compare validation failure."""


@dataclass
class ResponseSnapshot:
    status: int | None = None
    reason: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    body: str | None = None
    body_encoding: str | None = None
    url: str | None = None
    method: str | None = None
    request_id: str | None = None


@dataclass
class CompareResult:
    left: ResponseSnapshot | None = None
    right: ResponseSnapshot | None = None
    same: bool | None = None
    status_equal: bool | None = None
    headers_equal: bool | None = None
    body_equal: bool | None = None
    status_diff: dict[str, Any] | None = None
    header_diffs: list[dict[str, Any]] = field(default_factory=list)
    ignored_headers: list[str] = field(default_factory=list)
    body_diff: dict[str, Any] | None = None
    error: str | None = None


def compare_result_to_dict(result: CompareResult) -> dict:
    def snap(s: ResponseSnapshot | None) -> dict | None:
        if s is None:
            return None
        return {
            "request_id": s.request_id,
            "method": s.method,
            "url": s.url,
            "status": s.status,
            "reason": s.reason,
            "headers": dict(s.headers),
            "body": s.body,
            "body_encoding": s.body_encoding,
        }

    return {
        "left": snap(result.left),
        "right": snap(result.right),
        "same": result.same,
        "status_equal": result.status_equal,
        "headers_equal": result.headers_equal,
        "body_equal": result.body_equal,
        "status_diff": result.status_diff,
        "header_diffs": list(result.header_diffs),
        "ignored_headers": list(result.ignored_headers),
        "body_diff": result.body_diff,
        "error": result.error,
    }


def _normalize_headers(raw: dict[str, str] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    if not raw:
        return out
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        name = key.strip().lower()
        if name:
            out[name] = value
    return out


def _from_entry(entry: HistoryEntry) -> ResponseSnapshot:
    return ResponseSnapshot(
        status=entry.status,
        reason=entry.reason,
        headers=dict(entry.response_headers or {}),
        body=entry.body,
        body_encoding=entry.body_encoding,
        url=entry.final_url or entry.url,
        method=entry.method,
        request_id=entry.id,
    )


def _from_parts(
    *,
    status: int | None,
    reason: str | None,
    headers: dict[str, str] | None,
    body: str | None,
    body_encoding: str | None,
    url: str | None,
    method: str | None,
    request_id: str | None,
) -> ResponseSnapshot:
    return ResponseSnapshot(
        status=status,
        reason=reason,
        headers=dict(headers or {}),
        body=body,
        body_encoding=body_encoding,
        url=url,
        method=method,
        request_id=request_id,
    )


def _first_diff_offset(left: str, right: str) -> int | None:
    n = min(len(left), len(right))
    for i in range(n):
        if left[i] != right[i]:
            return i
    if len(left) != len(right):
        return n
    return None


def _body_diff(left: str | None, right: str | None, *, preview: int = 120) -> dict:
    l = "" if left is None else left
    r = "" if right is None else right
    offset = _first_diff_offset(l, r)
    out: dict[str, Any] = {
        "left_chars": len(l),
        "right_chars": len(r),
        "left_none": left is None,
        "right_none": right is None,
        "first_diff_offset": offset,
    }
    if offset is not None:
        start = max(0, offset - 20)
        out["left_preview"] = l[start : start + preview]
        out["right_preview"] = r[start : start + preview]
    return out


def response_compare(
    *,
    left_id: str | None = None,
    right_id: str | None = None,
    left_status: int | None = None,
    right_status: int | None = None,
    left_headers: dict[str, str] | None = None,
    right_headers: dict[str, str] | None = None,
    left_body: str | None = None,
    right_body: str | None = None,
    left_reason: str | None = None,
    right_reason: str | None = None,
    left_url: str | None = None,
    right_url: str | None = None,
    left_method: str | None = None,
    right_method: str | None = None,
    compare_headers: bool = True,
    compare_body: bool = True,
    ignore_headers: list[str] | str | None = None,
    history: HistoryStore | None = None,
) -> CompareResult:
    """Diff two responses from history ids and/or inline snapshots."""

    def resolve_side(
        *,
        entry_id: str | None,
        status: int | None,
        reason: str | None,
        headers: dict[str, str] | None,
        body: str | None,
        url: str | None,
        method: str | None,
        label: str,
    ) -> ResponseSnapshot | str:
        sid = (entry_id or "").strip() if entry_id is not None else ""
        if sid:
            if history is None:
                return f"{label}_id requires an in-process history store"
            entry = history.get(sid)
            if entry is None:
                return f"unknown history id: {entry_id}"
            snap = _from_entry(entry)
            # Inline fields override the recorded snapshot when provided.
            if status is not None:
                snap.status = status
            if reason is not None:
                snap.reason = reason
            if headers is not None:
                snap.headers = dict(headers)
            if body is not None:
                snap.body = body
            if url is not None:
                snap.url = url
            if method is not None:
                snap.method = method
            return snap
        if status is None and headers is None and body is None:
            return f"{label}_id or {label} status/headers/body is required"
        return _from_parts(
            status=status,
            reason=reason,
            headers=headers,
            body=body,
            body_encoding=None,
            url=url,
            method=method,
            request_id=None,
        )

    left = resolve_side(
        entry_id=left_id,
        status=left_status,
        reason=left_reason,
        headers=left_headers,
        body=left_body,
        url=left_url,
        method=left_method,
        label="left",
    )
    if isinstance(left, str):
        return CompareResult(error=left)
    right = resolve_side(
        entry_id=right_id,
        status=right_status,
        reason=right_reason,
        headers=right_headers,
        body=right_body,
        url=right_url,
        method=right_method,
        label="right",
    )
    if isinstance(right, str):
        return CompareResult(left=left, error=right)

    ignored: set[str] = set(_DEFAULT_IGNORE_HEADERS)
    if ignore_headers is not None:
        if isinstance(ignore_headers, str):
            items = [
                p.strip().lower()
                for p in ignore_headers.replace("\n", ",").split(",")
                if p.strip()
            ]
        elif isinstance(ignore_headers, list):
            items = [str(p).strip().lower() for p in ignore_headers if str(p).strip()]
        else:
            return CompareResult(
                left=left, right=right, error="ignore_headers must be a string or list"
            )
        ignored = {i for i in items if i}

    status_equal = left.status == right.status
    status_diff = None
    if not status_equal:
        status_diff = {"left": left.status, "right": right.status}

    header_diffs: list[dict[str, Any]] = []
    headers_equal: bool | None = None
    if compare_headers:
        lh = _normalize_headers(left.headers)
        rh = _normalize_headers(right.headers)
        names = sorted((set(lh) | set(rh)) - ignored)
        for name in names:
            lv = lh.get(name)
            rv = rh.get(name)
            if lv != rv:
                header_diffs.append({"name": name, "left": lv, "right": rv})
        headers_equal = not header_diffs

    body_equal: bool | None = None
    body_diff = None
    if compare_body:
        body_equal = left.body == right.body
        if not body_equal:
            body_diff = _body_diff(left.body, right.body)

    same = status_equal
    if compare_headers:
        same = same and bool(headers_equal)
    if compare_body:
        same = same and bool(body_equal)

    return CompareResult(
        left=left,
        right=right,
        same=same,
        status_equal=status_equal,
        headers_equal=headers_equal,
        body_equal=body_equal,
        status_diff=status_diff,
        header_diffs=header_diffs,
        ignored_headers=sorted(ignored),
        body_diff=body_diff,
    )


__all__ = [
    "CompareError",
    "CompareResult",
    "ResponseSnapshot",
    "compare_result_to_dict",
    "response_compare",
]
