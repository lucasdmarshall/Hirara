"""SQLite-backed state for memory, human questions and reminders.

One file, three tables, a lock around every statement. Small, durable,
inspectable with any SQLite client.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .errors import AgentError

SCHEMA = """
CREATE TABLE IF NOT EXISTS memory (
    namespace TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, tags TEXT NOT NULL,
    created REAL NOT NULL, updated REAL NOT NULL, expires REAL,
    PRIMARY KEY (namespace, key));
CREATE TABLE IF NOT EXISTS requests (
    id TEXT PRIMARY KEY, namespace TEXT NOT NULL, kind TEXT NOT NULL, question TEXT NOT NULL,
    context TEXT, options TEXT, allow_free_text INTEGER NOT NULL, urgency TEXT NOT NULL,
    status TEXT NOT NULL, answer TEXT, answered_by TEXT, comment TEXT,
    created REAL NOT NULL, answered REAL, expires REAL);
CREATE TABLE IF NOT EXISTS reminders (
    id TEXT PRIMARY KEY, namespace TEXT NOT NULL, title TEXT NOT NULL, note TEXT,
    due REAL NOT NULL, repeat_seconds REAL, status TEXT NOT NULL, created REAL NOT NULL,
    fired_count INTEGER NOT NULL DEFAULT 0, last_fired REAL);
"""


def iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


def parse_when(at: str | None, in_seconds: float | None, *, now: float) -> float:
    """An absolute ISO time or a delay; ``in 10m`` style shortcuts too."""
    if in_seconds is not None:
        if in_seconds < 0:
            raise AgentError("in_seconds must be >= 0")
        return now + float(in_seconds)
    if not at:
        raise AgentError("give at (ISO 8601) or in_seconds")
    text = at.strip()
    m = re.fullmatch(r"in\s+(\d+(?:\.\d+)?)\s*(s|sec|m|min|h|hr|d|day)s?", text, re.I)
    if m:
        unit = {"s": 1, "sec": 1, "m": 60, "min": 60, "h": 3600, "hr": 3600, "d": 86400,
                "day": 86400}[m.group(2).lower()]
        return now + float(m.group(1)) * unit
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00") if text.endswith("Z") else text)
    except ValueError as exc:
        raise AgentError(f"cannot read time {at!r}; use ISO 8601 (2026-10-24T09:00:00+06:30) "
                         "or 'in 10m'") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


class Store:
    def __init__(self, path: str) -> None:
        target = path if path == ":memory:" else str(Path(path).expanduser())
        if target != ":memory:":
            Path(target).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(target, check_same_thread=False, isolation_level=None)
        if target != ":memory:":
            self._db.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(SCHEMA)
        self.path = target

    def q(self, sql: str, args: tuple = ()) -> list[tuple]:
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    def x(self, sql: str, args: tuple = ()) -> int:
        with self._lock:
            return self._db.execute(sql, args).rowcount

    # --- memory ------------------------------------------------------------------

    def mem_set(self, ns: str, key: str, value, tags: list[str], ttl: float | None,
                *, max_bytes: int, max_entries: int) -> dict:
        raw = json.dumps(value, ensure_ascii=False)
        if len(raw.encode()) > max_bytes:
            raise AgentError(f"value is larger than HG_MAX_VALUE_BYTES ({max_bytes})")
        now = time.time()
        self.mem_purge(now)
        existing = self.q("SELECT created FROM memory WHERE namespace=? AND key=?", (ns, key))
        if not existing:
            (count,), = self.q("SELECT COUNT(*) FROM memory WHERE namespace=?", (ns,))
            if count >= max_entries:
                raise AgentError(f"namespace {ns!r} holds {count} entries (HG_MAX_ENTRIES); "
                                 "delete some first")
        created = existing[0][0] if existing else now
        expires = now + ttl if ttl else None
        self.x("INSERT OR REPLACE INTO memory VALUES (?,?,?,?,?,?,?)",
               (ns, key, raw, json.dumps(sorted(set(tags))), created, now, expires))
        return {"key": key, "created": not existing, "updated": iso(now), "expires": iso(expires)}

    def mem_purge(self, now: float) -> None:
        self.x("DELETE FROM memory WHERE expires IS NOT NULL AND expires <= ?", (now,))

    @staticmethod
    def _mem_row(row) -> dict:
        ns, key, value, tags, created, updated, expires = row
        return {"key": key, "value": json.loads(value), "tags": json.loads(tags),
                "created": iso(created), "updated": iso(updated), "expires": iso(expires),
                "namespace": ns}

    def mem_get(self, ns: str, key: str) -> dict | None:
        self.mem_purge(time.time())
        rows = self.q("SELECT * FROM memory WHERE namespace=? AND key=?", (ns, key))
        return self._mem_row(rows[0]) if rows else None

    def mem_query(self, ns: str, *, words: list[str], tags: list[str], limit: int,
                  offset: int) -> tuple[list[dict], int]:
        self.mem_purge(time.time())
        sql = "SELECT * FROM memory WHERE namespace=?"
        args: list = [ns]
        for w in words:
            sql += " AND (lower(key) LIKE ? OR lower(value) LIKE ? OR lower(tags) LIKE ?)"
            like = f"%{w.lower()}%"
            args += [like, like, like]
        for t in tags:
            sql += " AND tags LIKE ?"
            args.append(f'%"{t}"%')
        (total,), = self.q(sql.replace("SELECT *", "SELECT COUNT(*)", 1), tuple(args))
        rows = self.q(sql + " ORDER BY updated DESC LIMIT ? OFFSET ?", (*args, limit, offset))
        return [self._mem_row(r) for r in rows], total

    # --- human requests -------------------------------------------------------------

    def req_create(self, ns: str, kind: str, question: str, context: str | None,
                   options: list[str] | None, free: bool, urgency: str,
                   expires: float | None) -> dict:
        rid = uuid.uuid4().hex[:10]
        self.x("INSERT INTO requests (id, namespace, kind, question, context, options, "
               "allow_free_text, urgency, status, created, expires) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
               (rid, ns, kind, question, context, json.dumps(options) if options else None,
                int(free), urgency, "pending", time.time(), expires))
        return self.req_get(rid)

    def req_get(self, rid: str) -> dict:
        self.req_expire()
        rows = self.q("SELECT id, namespace, kind, question, context, options, allow_free_text, "
                      "urgency, status, answer, answered_by, comment, created, answered, expires "
                      "FROM requests WHERE id=?", (rid,))
        if not rows:
            raise AgentError(f"unknown request_id: {rid}")
        (rid, ns, kind, question, context, options, free, urgency, status, answer, by, comment,
         created, answered, expires) = rows[0]
        return {"request_id": rid, "namespace": ns, "kind": kind, "question": question,
                "context": context, "options": json.loads(options) if options else None,
                "allow_free_text": bool(free), "urgency": urgency, "status": status,
                "answer": answer, "answered_by": by, "comment": comment,
                "created": iso(created), "answered": iso(answered), "expires": iso(expires)}

    def req_list(self, ns: str | None, status: str | None) -> list[dict]:
        self.req_expire()
        sql, args = "SELECT id FROM requests WHERE 1=1", []
        if ns:
            sql += " AND namespace=?"
            args.append(ns)
        if status:
            sql += " AND status=?"
            args.append(status)
        return [self.req_get(r[0]) for r in self.q(sql + " ORDER BY created", tuple(args))]

    def req_answer(self, rid: str, answer: str, by: str | None, comment: str | None) -> dict:
        req = self.req_get(rid)
        if req["status"] != "pending":
            raise AgentError(f"request {rid} is {req['status']}, not pending")
        options = req["options"]
        if options and answer not in options and not req["allow_free_text"]:
            raise AgentError(f"answer must be one of: {', '.join(options)}")
        self.x("UPDATE requests SET status='answered', answer=?, answered_by=?, comment=?, "
               "answered=? WHERE id=? AND status='pending'", (answer, by, comment, time.time(), rid))
        return self.req_get(rid)

    def req_cancel(self, rid: str) -> dict:
        req = self.req_get(rid)
        if req["status"] == "pending":
            self.x("UPDATE requests SET status='cancelled' WHERE id=?", (rid,))
        return self.req_get(rid)

    def req_expire(self) -> None:
        self.x("UPDATE requests SET status='expired' WHERE status='pending' AND expires IS NOT NULL "
               "AND expires <= ?", (time.time(),))

    # --- reminders ---------------------------------------------------------------------

    def rem_create(self, ns: str, title: str, note: str | None, due: float,
                   repeat: float | None) -> dict:
        rid = uuid.uuid4().hex[:10]
        self.x("INSERT INTO reminders (id, namespace, title, note, due, repeat_seconds, status, "
               "created) VALUES (?,?,?,?,?,?,?,?)",
               (rid, ns, title, note, due, repeat, "scheduled", time.time()))
        return self.rem_get(rid)

    def rem_get(self, rid: str) -> dict:
        rows = self.q("SELECT id, namespace, title, note, due, repeat_seconds, status, created, "
                      "fired_count, last_fired FROM reminders WHERE id=?", (rid,))
        if not rows:
            raise AgentError(f"unknown reminder_id: {rid}")
        rid, ns, title, note, due, repeat, status, created, fired, last = rows[0]
        return {"reminder_id": rid, "namespace": ns, "title": title, "note": note, "due": iso(due),
                "due_in_seconds": round(due - time.time(), 1) if status == "scheduled" else None,
                "repeat_seconds": repeat, "status": status, "created": iso(created),
                "fired_count": fired, "last_fired": iso(last)}

    def rem_list(self, ns: str, include_done: bool) -> list[dict]:
        sql = "SELECT id FROM reminders WHERE namespace=?"
        if not include_done:
            sql += " AND status='scheduled'"
        return [self.rem_get(r[0]) for r in self.q(sql + " ORDER BY due", (ns,))]

    def rem_due(self, ns: str, *, consume: bool = True) -> list[dict]:
        """Reminders due now. Consuming marks one-shots done and moves repeats on."""
        now = time.time()
        rows = self.q("SELECT id, due, repeat_seconds FROM reminders WHERE namespace=? AND "
                      "status='scheduled' AND due <= ? ORDER BY due", (ns, now))
        out = []
        for rid, due, repeat in rows:
            item = self.rem_get(rid)
            item["was_due"] = iso(due)
            if consume:
                if repeat:
                    nxt = due
                    while nxt <= now:
                        nxt += repeat
                    self.x("UPDATE reminders SET due=?, fired_count=fired_count+1, last_fired=? "
                           "WHERE id=?", (nxt, now, rid))
                else:
                    self.x("UPDATE reminders SET status='done', fired_count=fired_count+1, "
                           "last_fired=? WHERE id=?", (now, rid))
            out.append(item)
        return out

    def rem_cancel(self, rid: str) -> dict:
        self.rem_get(rid)
        self.x("UPDATE reminders SET status='cancelled' WHERE id=? AND status='scheduled'", (rid,))
        return self.rem_get(rid)

    def next_due(self, ns: str) -> float | None:
        rows = self.q("SELECT MIN(due) FROM reminders WHERE namespace=? AND status='scheduled'", (ns,))
        return rows[0][0] if rows and rows[0][0] is not None else None


__all__ = ["Store", "iso", "parse_when"]
