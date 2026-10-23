"""The tool layer: schemas and JSON-ready results.

Both front ends (HTTP service and MCP server) call into here, so the two can
never drift apart in behaviour — only in transport.

Tools: ``memory``, ``ask_human``, ``schedule``, ``wait_until``. Each takes an
``action``; all share one SQLite store.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

import httpx

from .config import AgentConfig
from .errors import AgentError
from .store import Store, iso, parse_when

log = logging.getLogger(__name__)

NS = {"type": "string", "description": "Separate memories / questions / reminders per project "
                                      "or agent (default 'default')."}

MEMORY_SCHEMA = {
    "name": "memory",
    "description": (
        "Long-term notes that survive between sessions. action=set stores a JSON "
        "value under a key (with optional tags and ttl_seconds); get reads one; "
        "search finds entries whose key, value or tags contain every word of "
        "query (and all of tags); list pages through keys; delete removes one. "
        "Save decisions, preferences, facts learned and progress, then search "
        "before redoing work."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["set", "get", "search", "list", "delete"]},
            "key": {"type": "string"},
            "value": {"description": "Any JSON value (set)."},
            "tags": {"type": "array", "items": {"type": "string"}},
            "ttl_seconds": {"type": "number", "description": "Forget after this long (set)."},
            "query": {"type": "string", "description": "Words to match (search)."},
            "limit": {"type": "integer", "minimum": 1, "maximum": 500},
            "offset": {"type": "integer", "minimum": 0},
            "namespace": NS,
        },
        "required": ["action"],
        "additionalProperties": False,
    },
}

ASK_HUMAN_SCHEMA = {
    "name": "ask_human",
    "description": (
        "Ask a person and get their answer later: before an irreversible or costly "
        "action (kind=approval, options default approve / reject), or when only "
        "they know (kind=question). action=ask returns a request_id at once and "
        "notifies the operator; action=check returns the status and answer; "
        "list shows pending requests; cancel withdraws one. Combine with "
        "wait_until(request_id=...) to wait for the reply. Do not proceed with an "
        "approval-gated action until the answer is approve."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["ask", "check", "list", "cancel"]},
            "question": {"type": "string"},
            "kind": {"type": "string", "enum": ["question", "approval"]},
            "options": {"type": "array", "items": {"type": "string"},
                        "description": "Allowed answers (approval default: approve, reject)."},
            "allow_free_text": {"type": "boolean",
                                "description": "Accept answers outside options (default false)."},
            "context": {"type": "string", "description": "Details the person needs to decide."},
            "urgency": {"type": "string", "enum": ["low", "normal", "high"]},
            "expires_in_seconds": {"type": "number"},
            "request_id": {"type": "string"},
            "namespace": NS,
        },
        "required": ["action"],
        "additionalProperties": False,
    },
}

SCHEDULE_SCHEMA = {
    "name": "schedule",
    "description": (
        "Reminders that come due later, so follow-ups are not forgotten between "
        "sessions. action=create with a title, an optional note (instructions for "
        "your future self) and when: at (ISO 8601, or 'in 10m' / 'in 2h' / 'in 1d') "
        "or in_seconds; repeat_seconds makes it recur. action=due returns what is "
        "due now and marks it fired; list shows upcoming; cancel removes one."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["create", "due", "list", "cancel"]},
            "title": {"type": "string"},
            "note": {"type": "string"},
            "at": {"type": "string"},
            "in_seconds": {"type": "number", "minimum": 0},
            "repeat_seconds": {"type": "number", "minimum": 60},
            "reminder_id": {"type": "string"},
            "include_done": {"type": "boolean"},
            "namespace": NS,
        },
        "required": ["action"],
        "additionalProperties": False,
    },
}

WAIT_UNTIL_SCHEMA = {
    "name": "wait_until",
    "description": (
        "Block until something happens, capped at max_wait (server limit, "
        "default 100 s): a human answers request_id, a reminder in the namespace "
        "comes due (reminder_due=true), or a time is reached (at / in_seconds). "
        "Returns why it stopped (answered, reminder_due, time_reached, timeout) "
        "with the answer or due reminders. On timeout, call it again."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "request_id": {"type": "string", "description": "Wait for this ask_human answer."},
            "reminder_due": {"type": "boolean", "description": "Wait for any reminder to come due."},
            "at": {"type": "string", "description": "Wait until this time."},
            "in_seconds": {"type": "number", "minimum": 0},
            "max_wait": {"type": "number", "minimum": 0},
            "namespace": NS,
        },
        "additionalProperties": False,
    },
}

SCHEMAS = [MEMORY_SCHEMA, ASK_HUMAN_SCHEMA, SCHEDULE_SCHEMA, WAIT_UNTIL_SCHEMA]
TOOL_NAMES = tuple(s["name"] for s in SCHEMAS)


def _ns(namespace: str | None) -> str:
    ns = (namespace or "default").strip()
    if not ns or len(ns) > 100:
        raise AgentError("namespace must be 1..100 characters")
    return ns


@dataclass
class Toolset:
    config: AgentConfig
    store: Store = field(init=False)

    def __post_init__(self) -> None:
        self.store = Store(self.config.db)

    @classmethod
    def from_env(cls) -> "Toolset":
        return cls(config=AgentConfig.from_env())

    def schemas(self) -> list[dict]:
        return list(SCHEMAS)

    def health(self) -> dict:
        return {"status": "ok", "version": "0.1.0", "tools": list(TOOL_NAMES),
                "db": self.store.path, "notify": bool(self.config.notify_url),
                "human_token": bool(self.config.human_token)}

    async def _guard(self, name: str, fn, **fields) -> dict:
        try:
            return await fn()
        except AgentError as exc:
            return {**fields, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001 — agent gets a body, not a 500
            log.exception("%s failed", name)
            return {**fields, "error": f"{name} failed: {exc}"}

    # --- memory --------------------------------------------------------------------

    async def memory(self, *, action: str, key: str | None = None, value=None,
                     tags: list[str] | None = None, ttl_seconds: float | None = None,
                     query: str | None = None, limit: int = 20, offset: int = 0,
                     namespace: str | None = None) -> dict:
        async def run():
            ns = _ns(namespace)
            act = (action or "").lower()
            if act in ("set", "get", "delete") and not (key and key.strip()):
                raise AgentError(f"{act} needs key")
            if act == "set":
                if value is None:
                    raise AgentError("set needs value")
                r = self.store.mem_set(ns, key.strip(), value, [t.strip() for t in tags or [] if t.strip()],
                                       ttl_seconds, max_bytes=self.config.max_value_bytes,
                                       max_entries=self.config.max_entries)
                return {"action": act, "namespace": ns, **r, "error": None}
            if act == "get":
                entry = self.store.mem_get(ns, key.strip())
                return {"action": act, "namespace": ns, "key": key, "found": entry is not None,
                        "entry": entry, "error": None}
            if act == "delete":
                n = self.store.x("DELETE FROM memory WHERE namespace=? AND key=?", (ns, key.strip()))
                return {"action": act, "namespace": ns, "key": key, "deleted": n > 0, "error": None}
            if act in ("search", "list"):
                words = (query or "").split() if act == "search" else []
                if act == "search" and not words and not tags:
                    raise AgentError("search needs query and/or tags")
                lim = max(1, min(int(limit), 500))
                entries, total = self.store.mem_query(ns, words=words, tags=tags or [], limit=lim,
                                                      offset=max(0, int(offset)))
                if act == "list":
                    for e in entries:
                        preview = str(e.pop("value"))
                        e["preview"] = preview[:120]
                return {"action": act, "namespace": ns, "entries": entries, "count": len(entries),
                        "total": total, "error": None}
            raise AgentError("action must be set, get, search, list or delete")

        return await self._guard("memory", run, action=action)

    # --- ask_human -------------------------------------------------------------------

    async def ask_human(self, *, action: str, question: str | None = None,
                        kind: str = "question", options: list[str] | None = None,
                        allow_free_text: bool = False, context: str | None = None,
                        urgency: str = "normal", expires_in_seconds: float | None = None,
                        request_id: str | None = None, namespace: str | None = None) -> dict:
        async def run():
            ns = _ns(namespace)
            act = (action or "").lower()
            if act == "ask":
                if not question or not question.strip():
                    raise AgentError("ask needs question")
                if kind not in ("question", "approval"):
                    raise AgentError("kind must be question or approval")
                if urgency not in ("low", "normal", "high"):
                    raise AgentError("urgency must be low, normal or high")
                opts = [o.strip() for o in (options or []) if o and o.strip()] or (
                    ["approve", "reject"] if kind == "approval" else None)
                expires = time.time() + expires_in_seconds if expires_in_seconds else None
                req = self.store.req_create(ns, kind, question.strip(), context, opts,
                                            allow_free_text, urgency, expires)
                notified = await self._notify(req)
                return {"action": act, **req, "notified": notified, "error": None}
            if act == "check":
                if not request_id:
                    raise AgentError("check needs request_id")
                return {"action": act, **self.store.req_get(request_id), "error": None}
            if act == "list":
                reqs = self.store.req_list(ns, "pending")
                return {"action": act, "namespace": ns, "requests": reqs, "count": len(reqs),
                        "error": None}
            if act == "cancel":
                if not request_id:
                    raise AgentError("cancel needs request_id")
                return {"action": act, **self.store.req_cancel(request_id), "error": None}
            raise AgentError("action must be ask, check, list or cancel")

        return await self._guard("ask_human", run, action=action, request_id=request_id)

    async def _notify(self, req: dict) -> bool:
        """Tell the operator a request is waiting. Best effort, never fatal."""
        url = self.config.notify_url
        if not url:
            return False
        link = (self.config.public_url or "").rstrip("/")
        text = f"[{req['urgency']}] {req['kind']}: {req['question']}"
        if req["options"]:
            text += f"  (options: {', '.join(req['options'])})"
        if link:
            text += f"\nAnswer: {link}/human"
        payload = {"text": text, "content": text, "request": req}
        try:
            async with httpx.AsyncClient(timeout=self.config.notify_timeout) as client:
                if "ntfy" in url:
                    r = await client.post(url, content=text.encode(),
                                          headers={"Title": "Hirara: agent needs you"})
                else:
                    r = await client.post(url, json=payload)
            return r.status_code < 400
        except httpx.HTTPError as exc:
            log.warning("notify failed: %s", exc)
            return False

    # --- schedule --------------------------------------------------------------------

    async def schedule(self, *, action: str, title: str | None = None, note: str | None = None,
                       at: str | None = None, in_seconds: float | None = None,
                       repeat_seconds: float | None = None, reminder_id: str | None = None,
                       include_done: bool = False, namespace: str | None = None) -> dict:
        async def run():
            ns = _ns(namespace)
            act = (action or "").lower()
            if act == "create":
                if not title or not title.strip():
                    raise AgentError("create needs title")
                if repeat_seconds is not None and repeat_seconds < 60:
                    raise AgentError("repeat_seconds must be at least 60")
                due = parse_when(at, in_seconds, now=time.time())
                rem = self.store.rem_create(ns, title.strip(), note, due, repeat_seconds)
                return {"action": act, **rem, "error": None}
            if act == "due":
                items = self.store.rem_due(ns)
                return {"action": act, "namespace": ns, "due": items, "count": len(items),
                        "next_due": iso(self.store.next_due(ns)), "error": None}
            if act == "list":
                items = self.store.rem_list(ns, include_done)
                return {"action": act, "namespace": ns, "reminders": items, "count": len(items),
                        "error": None}
            if act == "cancel":
                if not reminder_id:
                    raise AgentError("cancel needs reminder_id")
                return {"action": act, **self.store.rem_cancel(reminder_id), "error": None}
            raise AgentError("action must be create, due, list or cancel")

        return await self._guard("schedule", run, action=action)

    # --- wait_until ----------------------------------------------------------------------

    async def wait_until(self, *, request_id: str | None = None, reminder_due: bool = False,
                         at: str | None = None, in_seconds: float | None = None,
                         max_wait: float | None = None, namespace: str | None = None) -> dict:
        async def run():
            ns = _ns(namespace)
            if not (request_id or reminder_due or at or in_seconds is not None):
                raise AgentError("give request_id, reminder_due, at or in_seconds")
            start = time.time()
            cap = self.config.max_wait if max_wait is None else min(float(max_wait), self.config.max_wait)
            deadline = start + max(0.0, cap)
            target = parse_when(at, in_seconds, now=start) if (at or in_seconds is not None) else None
            if request_id:
                self.store.req_get(request_id)  # fail fast on an unknown id
            while True:
                now = time.time()
                if request_id:
                    req = self.store.req_get(request_id)
                    if req["status"] != "pending":
                        return {"reason": "answered" if req["status"] == "answered" else req["status"],
                                "request": req, "waited": round(now - start, 1), "error": None}
                if reminder_due:
                    due = self.store.rem_due(ns)
                    if due:
                        return {"reason": "reminder_due", "due": due,
                                "waited": round(now - start, 1), "error": None}
                if target is not None and now >= target:
                    return {"reason": "time_reached", "time": iso(now),
                            "waited": round(now - start, 1), "error": None}
                if now >= deadline:
                    return {"reason": "timeout", "waited": round(now - start, 1),
                            "hint": "nothing happened yet; call wait_until again", "error": None}
                wake = deadline
                if target is not None:
                    wake = min(wake, target)
                await asyncio.sleep(max(0.05, min(0.5, wake - now)))

        return await self._guard("wait_until", run, reason=None)


__all__ = [
    "ASK_HUMAN_SCHEMA",
    "MEMORY_SCHEMA",
    "SCHEDULE_SCHEMA",
    "SCHEMAS",
    "TOOL_NAMES",
    "Toolset",
    "WAIT_UNTIL_SCHEMA",
    "call_tool",
    "tool_schemas",
]


# --- local backend: in-process dispatch for the hirara SDK -------------------
_local_toolset: "Toolset | None" = None


def _backend() -> "Toolset":
    global _local_toolset
    if _local_toolset is None:
        _local_toolset = Toolset.from_env()
    return _local_toolset


async def call_tool(name: str, arguments: dict | None = None) -> dict:
    """Run one tool in-process and return its response envelope."""
    if name not in TOOL_NAMES:
        raise KeyError(f"unknown tool: {name}")
    return await getattr(_backend(), name)(**(arguments or {}))


def tool_schemas() -> list[dict]:
    return list(SCHEMAS)
