"""inspect_headers unit tests."""

from __future__ import annotations

from hirarahttp.history import HistoryEntry
from hirarahttp.inspect import (
    inspect_headers_from_entry,
    inspect_headers_from_maps,
    inspect_headers_result_to_dict,
)


def test_response_interesting_and_missing():
    result = inspect_headers_from_maps(
        response_headers={
            "Content-Type": "text/html; charset=utf-8",
            "Server": "example",
            "X-Content-Type-Options": "nosniff",
        },
        which="response",
    )
    assert result.error is None
    assert result.response is not None
    assert result.response.content_type == "text/html; charset=utf-8"
    assert "content-type" in result.response.interesting
    assert "strict-transport-security" in result.response.missing_common
    assert "x-content-type-options" not in result.response.missing_common
    names = [h["name_lower"] for h in result.response.headers]
    assert names == sorted(names)


def test_request_side():
    result = inspect_headers_from_maps(
        request_headers={"User-Agent": "hirara", "Accept": "*/*"},
        which="request",
    )
    assert result.request is not None
    assert result.response is None
    assert result.request.interesting["user-agent"] == "hirara"
    assert result.request.missing_common == []


def test_both_from_entry():
    entry = HistoryEntry(
        id="abc",
        ts=1.0,
        method="GET",
        url="https://example.com/",
        final_url="https://example.com/",
        status=200,
        request_headers={"Host": "example.com"},
        response_headers={"Content-Type": "text/plain", "Content-Length": "2"},
    )
    result = inspect_headers_from_entry(entry, which="both")
    d = inspect_headers_result_to_dict(result)
    assert d["request_id"] == "abc"
    assert d["status"] == 200
    assert d["request"]["by_name"]["host"] == "example.com"
    assert d["response"]["content_length"] == 2


def test_bad_which():
    result = inspect_headers_from_maps(which="sideways")
    assert result.error and "which" in result.error
