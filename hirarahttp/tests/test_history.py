"""HistoryStore ring buffer."""

from __future__ import annotations

from hirarahttp.history import HistoryStore, entry_to_dict, entry_to_summary


def test_record_and_list_newest_first():
    store = HistoryStore(max_entries=10, max_body_chars=1000)
    a = store.record({"method": "GET", "url": "https://a.example/", "status": 200})
    b = store.record({"method": "POST", "url": "https://b.example/", "status": 201})
    page, total = store.list(limit=10, offset=0)
    assert total == 2
    assert [e.id for e in page] == [b.id, a.id]


def test_ring_evicts_oldest():
    store = HistoryStore(max_entries=2, max_body_chars=100)
    store.record({"url": "https://1.example/"})
    store.record({"url": "https://2.example/"})
    store.record({"url": "https://3.example/"})
    assert len(store) == 2
    page, total = store.list(limit=10)
    assert total == 2
    assert page[0].url == "https://3.example/"
    assert page[1].url == "https://2.example/"


def test_body_cap():
    store = HistoryStore(max_entries=5, max_body_chars=5)
    e = store.record({"body": "abcdefgh", "body_encoding": "utf-8"})
    assert e.body == "abcde"
    assert e.body_stored is False


def test_get_and_clear():
    store = HistoryStore(max_entries=5, max_body_chars=100)
    e = store.record({"url": "https://example.com/", "body": "hi"})
    assert store.get(e.id) is not None
    assert store.get("missing") is None
    assert store.clear() == 1
    assert len(store) == 0


def test_entry_shapes():
    store = HistoryStore(max_entries=5, max_body_chars=100)
    e = store.record(
        {
            "method": "GET",
            "url": "https://example.com/",
            "status": 200,
            "body": "hi",
            "request_headers": {"Host": "example.com"},
            "response_headers": {"content-type": "text/plain"},
            "redirects": ["https://example.com/old"],
        }
    )
    summary = entry_to_summary(e)
    assert "body" not in summary
    assert summary["redirect_count"] == 1
    full = entry_to_dict(e, include_body=True)
    assert full["body"] == "hi"
    assert full["request_headers"]["Host"] == "example.com"
    assert full["request_body"] is None
