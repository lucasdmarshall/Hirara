"""request_replay / parameter_test / response_compare tests."""

from __future__ import annotations

import json

import httpx
import pytest

from hirarahttp.compare import response_compare
from hirarahttp.config import HttpConfig
from hirarahttp.history import HistoryStore
from hirarahttp.replay import build_variant, parameter_test, request_replay
from hirarahttp.tools import Toolset


class _Transport(httpx.AsyncBaseTransport):
    def __init__(self, handler):
        self.handler = handler
        self.calls: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        return self.handler(request)


def test_build_variant_query_header_cookie_json_body():
    url, method, headers, body = build_variant(
        url="https://example.com/api?x=1",
        method="GET",
        headers={},
        body=None,
        location="query",
        name="q",
        value="hi",
    )
    assert "q=hi" in url
    assert "x=1" in url

    _, _, headers, _ = build_variant(
        url=url,
        method="GET",
        headers={"Accept": "text/plain"},
        body=None,
        location="header",
        name="X-Test",
        value="1",
    )
    assert headers["X-Test"] == "1"

    _, _, headers, _ = build_variant(
        url=url,
        method="GET",
        headers={"Cookie": "a=1; b=2"},
        body=None,
        location="cookie",
        name="b",
        value="9",
    )
    assert "b=9" in headers["Cookie"]
    assert "a=1" in headers["Cookie"]

    _, _, headers, body = build_variant(
        url=url,
        method="POST",
        headers={"Content-Type": "application/json"},
        body='{"a":1}',
        location="body",
        name="a",
        value="2",
    )
    assert json.loads(body)["a"] == "2"


def test_build_variant_path_placeholder():
    url, _, _, _ = build_variant(
        url="https://example.com/users/{id}/profile",
        method="GET",
        headers={},
        body=None,
        location="path",
        name="id",
        value="42",
    )
    assert url == "https://example.com/users/42/profile"


def test_response_compare_inline_and_ignore():
    r = response_compare(
        left_status=200,
        right_status=200,
        left_headers={"content-type": "text/plain", "date": "old"},
        right_headers={"content-type": "text/plain", "date": "new"},
        left_body="hello",
        right_body="hello",
    )
    assert r.error is None
    assert r.same is True
    assert r.header_diffs == []

    r2 = response_compare(
        left_status=200,
        right_status=404,
        left_body="a",
        right_body="b",
        compare_headers=False,
    )
    assert r2.same is False
    assert r2.status_equal is False
    assert r2.body_equal is False
    assert r2.body_diff["first_diff_offset"] == 0


@pytest.mark.asyncio
async def test_request_replay_and_parameter_test():
    def handler(request: httpx.Request) -> httpx.Response:
        q = httpx.URL(str(request.url)).params.get("q", "")
        return httpx.Response(200, text=f"ok:{q}", headers={"content-type": "text/plain"})

    transport = _Transport(handler)
    store = HistoryStore(max_entries=20, max_body_chars=1000)
    cfg = HttpConfig(allow_private_ips=True)

    # Seed history via request_replay's dependency: manual record
    seed = store.record(
        {
            "method": "GET",
            "url": "https://example.com/search?q=seed",
            "status": 200,
            "request_headers": {"Accept": "text/plain", "Host": "example.com"},
            "request_body": None,
            "body": "ok:seed",
            "body_encoding": "utf-8",
        }
    )

    replayed = await request_replay(
        id=seed.id,
        history=store,
        config=cfg,
        transport=transport,
        record=store.record,
    )
    assert replayed.error is None
    assert replayed.response["status"] == 200
    assert "request_id" in replayed.response
    assert len(transport.calls) == 1

    tested = await parameter_test(
        location="query",
        name="q",
        values=["one", "two"],
        id=seed.id,
        history=store,
        config=cfg,
        transport=transport,
        record=store.record,
        include_body=True,
    )
    assert tested.error is None
    assert tested.probed == 2
    assert {t.value for t in tested.results} == {"one", "two"}
    assert all(t.status == 200 for t in tested.results)
    assert tested.results[0].body_preview.startswith("ok:")


@pytest.mark.asyncio
async def test_toolset_replay_compare():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="body", headers={"content-type": "text/plain"})

    transport = _Transport(handler)
    ts = Toolset(config=HttpConfig(allow_private_ips=True))
    # Bypass real network by monkeypatching http_request used inside replay —
    # call compare with history entries instead.
    a = ts.history.record(
        {
            "method": "GET",
            "url": "https://example.com/a",
            "status": 200,
            "response_headers": {"content-type": "text/plain"},
            "body": "aaa",
        }
    )
    b = ts.history.record(
        {
            "method": "GET",
            "url": "https://example.com/b",
            "status": 200,
            "response_headers": {"content-type": "text/html"},
            "body": "bbb",
        }
    )
    cmp = await ts.response_compare(left_id=a.id, right_id=b.id)
    assert cmp["error"] is None
    assert cmp["same"] is False
    assert cmp["body_equal"] is False
    assert any(d["name"] == "content-type" for d in cmp["header_diffs"])

    # unknown id
    bad = await ts.request_replay(id="missing")
    assert bad["error"] is not None
