"""inspect_headers unit tests."""

from __future__ import annotations

from hirarahttp.history import HistoryEntry
from hirarahttp.inspect import (
    inspect_cookies_from_maps,
    inspect_headers_from_entry,
    inspect_headers_from_maps,
    inspect_headers_result_to_dict,
    inspect_response_from_parts,
    parse_cookie_header,
    parse_set_cookie,
    split_set_cookie,
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


def test_parse_cookie_header():
    cookies = parse_cookie_header("session=abc; theme=dark")
    assert [c.name for c in cookies] == ["session", "theme"]
    assert cookies[0].value == "abc"


def test_parse_set_cookie_flags():
    rec = parse_set_cookie(
        "session=tok; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=3600"
    )
    assert rec is not None
    assert rec.name == "session"
    assert rec.value == "tok"
    assert rec.path == "/"
    assert rec.secure is True
    assert rec.httponly is True
    assert rec.samesite == "Lax"
    assert rec.max_age == 3600
    assert rec.session is False
    assert rec.flags_missing == []


def test_set_cookie_flags_missing():
    rec = parse_set_cookie("id=1; Path=/app")
    assert rec is not None
    assert rec.session is True
    assert rec.flags_missing == ["Secure", "HttpOnly", "SameSite"]


def test_split_set_cookie_keeps_expires_comma():
    raw = (
        "sid=abc; Expires=Wed, 21 Oct 2015 07:28:00 GMT; Path=/, "
        "theme=dark; Path=/"
    )
    parts = split_set_cookie(raw)
    assert len(parts) == 2
    assert parts[0].startswith("sid=")
    assert "Wed, 21 Oct" in parts[0]
    assert parts[1].startswith("theme=")


def test_inspect_cookies_from_maps():
    result = inspect_cookies_from_maps(
        request_headers={"Cookie": "a=1; b=2"},
        response_headers={
            "Set-Cookie": "sess=x; Path=/; Secure; HttpOnly; SameSite=Strict"
        },
        which="both",
    )
    assert result.error is None
    assert result.request is not None and result.request.names == ["a", "b"]
    assert result.response is not None
    cookie = result.response.cookies[0]
    assert cookie.name == "sess"
    assert cookie.secure is True
    assert cookie.flags_missing == []


def test_inspect_response_json():
    result = inspect_response_from_parts(
        status=200,
        reason="OK",
        headers={"Content-Type": "application/json; charset=utf-8"},
        body='{"a":1,"b":[2,3]}',
        include_body=True,
    )
    assert result.error is None
    assert result.ok is True
    assert result.status_class == "2xx"
    assert result.body_kind == "json"
    assert result.json_type == "object"
    assert result.json_keys == ["a", "b"]
    assert result.json == {"a": 1, "b": [2, 3]}
    assert result.charset == "utf-8"
    assert result.body is not None


def test_inspect_response_html_title():
    result = inspect_response_from_parts(
        status=404,
        headers={"Content-Type": "text/html"},
        body="<html><head><title> Not Found </title></head></html>",
        include_body=False,
        preview_chars=20,
    )
    assert result.ok is False
    assert result.status_class == "4xx"
    assert result.body_kind == "html"
    assert result.html_title == "Not Found"
    assert result.body is None
    assert result.preview == "<html><head><title> "


def test_inspect_response_json_error():
    result = inspect_response_from_parts(
        status=200,
        headers={"Content-Type": "application/json"},
        body="{not json",
    )
    assert result.body_kind == "json"
    assert result.json_error
    assert result.json is None
