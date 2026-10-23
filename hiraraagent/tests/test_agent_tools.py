"""memory, ask_human, schedule and wait_until."""

from __future__ import annotations

import asyncio
import time

import pytest

from hiraraagent import tools
from hiraraagent.config import AgentConfig
from hiraraagent.store import parse_when
from hiraraagent.tools import Toolset


@pytest.fixture
def ts(tmp_path):
    return Toolset(AgentConfig(db=str(tmp_path / "a.db"), max_wait=5))


async def test_memory_set_get_search_list_delete(ts, tmp_path):
    r = await ts.memory(action="set", key="user.lang", value={"preferred": "Burmese"},
                        tags=["prefs", "user"])
    assert r["error"] is None and r["created"] is True
    r = await ts.memory(action="set", key="deploy", value="use blue/green, never on Fridays",
                        tags=["ops"])
    assert (await ts.memory(action="get", key="user.lang"))["entry"]["value"] == {"preferred": "Burmese"}
    s = await ts.memory(action="search", query="fridays deploy")
    assert [e["key"] for e in s["entries"]] == ["deploy"]
    s = await ts.memory(action="search", tags=["prefs"])
    assert [e["key"] for e in s["entries"]] == ["user.lang"]
    lst = await ts.memory(action="list")
    assert lst["total"] == 2 and "preview" in lst["entries"][0]
    # Survives a restart: a new toolset on the same file sees it.
    again = Toolset(AgentConfig(db=str(tmp_path / "a.db")))
    assert (await again.memory(action="get", key="deploy"))["found"] is True
    assert (await ts.memory(action="delete", key="deploy"))["deleted"] is True
    assert (await ts.memory(action="get", key="deploy"))["found"] is False


async def test_memory_namespaces_ttl_and_limits(tmp_path):
    ts = Toolset(AgentConfig(db=str(tmp_path / "b.db"), max_entries=2, max_value_bytes=50))
    await ts.memory(action="set", key="k", value=1, namespace="proj-a")
    assert (await ts.memory(action="get", key="k", namespace="proj-b"))["found"] is False
    await ts.memory(action="set", key="t", value=1, ttl_seconds=0.05)
    time.sleep(0.1)
    assert (await ts.memory(action="get", key="t"))["found"] is False
    assert "HG_MAX_VALUE_BYTES" in (await ts.memory(action="set", key="big", value="x" * 100))["error"]
    await ts.memory(action="set", key="a", value=1)
    await ts.memory(action="set", key="b", value=2)
    assert "HG_MAX_ENTRIES" in (await ts.memory(action="set", key="c", value=3))["error"]
    assert (await ts.memory(action="set", key="a", value=9))["error"] is None  # update is fine
    assert "needs key" in (await ts.memory(action="get"))["error"]
    assert "action must be" in (await ts.memory(action="burn"))["error"]


async def test_ask_human_approval_flow(ts):
    r = await ts.ask_human(action="ask", kind="approval", question="Delete 3 old branches?",
                           context="feature/a, feature/b, old-main")
    assert r["error"] is None and r["status"] == "pending" and r["options"] == ["approve", "reject"]
    assert r["notified"] is False
    rid = r["request_id"]
    assert [q["request_id"] for q in (await ts.ask_human(action="list"))["requests"]] == [rid]
    with pytest.raises(Exception, match="must be one of"):
        ts.store.req_answer(rid, "maybe", "ada", None)
    ts.store.req_answer(rid, "approve", "ada", "go ahead")
    c = await ts.ask_human(action="check", request_id=rid)
    assert (c["status"], c["answer"], c["answered_by"]) == ("answered", "approve", "ada")
    with pytest.raises(Exception, match="not pending"):
        ts.store.req_answer(rid, "reject", "bob", None)


async def test_ask_human_cancel_expire_and_errors(ts):
    r = await ts.ask_human(action="ask", question="Which region?", options=["eu", "us"],
                           allow_free_text=True)
    ts.store.req_answer(r["request_id"], "asia please", None, None)  # free text allowed
    r = await ts.ask_human(action="ask", question="Q", expires_in_seconds=0.05)
    time.sleep(0.1)
    assert (await ts.ask_human(action="check", request_id=r["request_id"]))["status"] == "expired"
    r = await ts.ask_human(action="ask", question="Q2")
    assert (await ts.ask_human(action="cancel", request_id=r["request_id"]))["status"] == "cancelled"
    assert "needs question" in (await ts.ask_human(action="ask"))["error"]
    assert "unknown request_id" in (await ts.ask_human(action="check", request_id="zzz"))["error"]


async def test_schedule_create_due_repeat_cancel(ts):
    one = await ts.schedule(action="create", title="check deploy", note="look at /status",
                            in_seconds=0)
    rep = await ts.schedule(action="create", title="daily digest", at="in 0s", repeat_seconds=3600)
    later = await ts.schedule(action="create", title="later", at="in 2h")
    assert later["due_in_seconds"] > 7000
    due = await ts.schedule(action="due")
    assert {d["title"] for d in due["due"]} == {"check deploy", "daily digest"}
    assert (await ts.schedule(action="due"))["count"] == 0  # consumed
    listed = await ts.schedule(action="list")
    assert {r["title"] for r in listed["reminders"]} == {"daily digest", "later"}
    assert ts.store.rem_get(one["reminder_id"])["status"] == "done"
    assert ts.store.rem_get(rep["reminder_id"])["fired_count"] == 1
    assert (await ts.schedule(action="cancel", reminder_id=later["reminder_id"]))["status"] == "cancelled"
    assert "repeat_seconds" in (await ts.schedule(action="create", title="x", in_seconds=1,
                                                  repeat_seconds=5))["error"]
    assert "ISO 8601" in (await ts.schedule(action="create", title="x", at="tomorrowish"))["error"]


def test_parse_when():
    now = 1_000_000.0
    assert parse_when(None, 30, now=now) == now + 30
    assert parse_when("in 10m", None, now=now) == now + 600
    assert parse_when("2026-10-24T00:00:00+06:30", None, now=now) == 1792776600.0
    assert parse_when("2026-10-23T17:30:00Z", None, now=now) == 1792776600.0


async def test_wait_until_answer_reminder_time_and_timeout(ts):
    r = await ts.ask_human(action="ask", question="ok?")

    async def answer_soon():
        await asyncio.sleep(0.3)
        ts.store.req_answer(r["request_id"], "yes", "ada", None)

    asyncio.get_running_loop().create_task(answer_soon())
    w = await ts.wait_until(request_id=r["request_id"], max_wait=3)
    assert w["reason"] == "answered" and w["request"]["answer"] == "yes" and w["waited"] < 2
    await ts.schedule(action="create", title="ping", in_seconds=0.3)
    w = await ts.wait_until(reminder_due=True, max_wait=3)
    assert w["reason"] == "reminder_due" and w["due"][0]["title"] == "ping"
    w = await ts.wait_until(in_seconds=0.2)
    assert w["reason"] == "time_reached"
    w = await ts.wait_until(in_seconds=60, max_wait=0.2)
    assert w["reason"] == "timeout"
    assert "give request_id" in (await ts.wait_until())["error"]


async def test_wait_is_capped_by_server(tmp_path):
    ts = Toolset(AgentConfig(db=str(tmp_path / "c.db"), max_wait=0.2))
    t = time.monotonic()
    w = await ts.wait_until(in_seconds=60, max_wait=999)
    assert w["reason"] == "timeout" and time.monotonic() - t < 1.5


def test_human_page_and_api():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from hiraraagent import service

    c = TestClient(service.app)
    r = c.post("/ask_human", json={"action": "ask", "kind": "approval",
                                   "question": "Ship <b>v2</b>?", "urgency": "high"}).json()
    page = c.get("/human").text
    assert "Ship &lt;b&gt;v2&lt;/b&gt;?" in page and 'value="approve"' in page
    done = c.post("/human/form", data={"request_id": r["request_id"], "answer": "approve"},
                  follow_redirects=False)
    assert done.status_code == 303
    assert c.post("/ask_human", json={"action": "check", "request_id": r["request_id"]}).json()["answer"] == "approve"
    r2 = c.post("/ask_human", json={"action": "ask", "question": "Name?"}).json()
    assert c.get("/human/pending").json()["count"] >= 1
    ok = c.post("/human/answer", json={"request_id": r2["request_id"], "answer": "Ada"}).json()
    assert ok["status"] == "answered"
    bad = c.post("/human/answer", json={"request_id": r2["request_id"], "answer": "again"})
    assert bad.status_code == 400


def test_human_token_required(monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from hiraraagent import service

    monkeypatch.setattr(service._toolset, "config", AgentConfig(db="unused", human_token="s3cret"))
    c = TestClient(service.app)
    assert c.get("/human").status_code == 401
    assert c.get("/human/pending").status_code == 401
    assert c.get("/human?token=s3cret").status_code == 200
    assert c.get("/human/pending", headers={"Authorization": "Bearer s3cret"}).status_code == 200


def test_contract():
    assert tools.TOOL_NAMES == ("memory", "ask_human", "schedule", "wait_until")
    mcp = pytest.importorskip("mcp")
    del mcp
    from hiraraagent import mcp_server

    listed = asyncio.run(mcp_server.server.list_tools())
    assert sorted(t.name for t in listed) == sorted(tools.TOOL_NAMES)
