"""web_watch: remember a page and report what changed since last time.

An agent asked to "tell me when the pricing page changes" has no memory
between runs. This keeps the last readable text of each watched URL in
SQLite (CHTTP_WATCH_DB; in memory by default) and, on each check, returns a
line diff of what changed. ``ignore`` regexes strip noise such as timestamps
and counters so they do not count as changes.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
import sqlite3
import threading
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

from .config import HttpConfig
from .request import http_request

BLOCK_TAGS = frozenset({
    "p", "div", "br", "li", "ul", "ol", "tr", "td", "th", "table", "h1", "h2", "h3", "h4",
    "h5", "h6", "section", "article", "header", "footer", "nav", "main", "aside", "pre",
    "blockquote", "dd", "dt", "form", "option", "label", "title",
})
SKIP_TAGS = frozenset({"script", "style", "noscript", "template", "svg", "head"})
MAX_DIFF_LINES = 300


class WatchError(ValueError):
    """Caller-facing web_watch failure."""


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in SKIP_TAGS:
            self._skip += 1
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS and self._skip:
            self._skip -= 1
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def readable_lines(body: str, content_type: str) -> list[str]:
    if "html" in content_type:
        parser = _Text()
        try:
            parser.feed(body)
        except Exception:  # noqa: BLE001
            pass
        body = "".join(parser.parts)
    return [" ".join(line.split()) for line in body.splitlines() if line.strip()]


class WatchStore:
    def __init__(self, path: str | None) -> None:
        target = path or ":memory:"
        if target != ":memory:":
            Path(target).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(target, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS watches (id TEXT PRIMARY KEY, url TEXT, "
                "ignore TEXT, lines TEXT, hash TEXT, created REAL, checked REAL, "
                "changed REAL, checks INTEGER, changes INTEGER)"
            )
            self._db.commit()

    def get(self, watch_id: str) -> dict | None:
        with self._lock:
            row = self._db.execute(
                "SELECT id, url, ignore, lines, hash, created, checked, changed, checks, changes "
                "FROM watches WHERE id = ?", (watch_id,)).fetchone()
        if row is None:
            return None
        keys = ("id", "url", "ignore", "lines", "hash", "created", "checked", "changed",
                "checks", "changes")
        out = dict(zip(keys, row))
        out["ignore"] = json.loads(out["ignore"] or "[]")
        out["lines"] = json.loads(out["lines"] or "[]")
        return out

    def put(self, rec: dict) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO watches VALUES (?,?,?,?,?,?,?,?,?,?)",
                (rec["id"], rec["url"], json.dumps(rec["ignore"]), json.dumps(rec["lines"]),
                 rec["hash"], rec["created"], rec["checked"], rec["changed"], rec["checks"],
                 rec["changes"]))
            self._db.commit()

    def all(self) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT id, url, created, checked, changed, checks, changes FROM watches "
                "ORDER BY created").fetchall()
        return [{"watch_id": r[0], "url": r[1], "created": _iso(r[2]), "last_check": _iso(r[3]),
                 "last_change": _iso(r[4]), "checks": r[5], "changes": r[6]} for r in rows]

    def delete(self, watch_id: str) -> bool:
        with self._lock:
            cur = self._db.execute("DELETE FROM watches WHERE id = ?", (watch_id,))
            self._db.commit()
        return cur.rowcount > 0


def _iso(ts: float | None) -> str | None:
    return None if ts is None else datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


def _compile(patterns) -> list[re.Pattern]:
    out = []
    for p in patterns or []:
        try:
            out.append(re.compile(p))
        except re.error as exc:
            raise WatchError(f"invalid ignore regex {p!r}: {exc}") from exc
    return out


async def web_watch(store: WatchStore, *, action: str = "check", url: str | None = None,
                    watch_id: str | None = None, ignore: list[str] | None = None,
                    config: HttpConfig) -> dict:
    action = (action or "check").strip().lower()
    if action == "list":
        return {"action": action, "watches": store.all(), "error": None}
    if action == "remove":
        if not watch_id:
            raise WatchError("watch_id is required")
        return {"action": action, "watch_id": watch_id, "removed": store.delete(watch_id),
                "error": None}
    if action != "check":
        raise WatchError("action must be check, list or remove")

    record = store.get(watch_id) if watch_id else None
    if watch_id and record is None and not url:
        raise WatchError(f"unknown watch_id: {watch_id}")
    target = url or (record or {}).get("url")
    if not target:
        raise WatchError("url (or an existing watch_id) is required")
    wid = watch_id or hashlib.sha256(target.encode()).hexdigest()[:12]
    record = record or store.get(wid)
    patterns = ignore if ignore is not None else (record or {}).get("ignore", [])
    rx = _compile(patterns)

    result = await http_request(target, config=config)
    now = time.time()
    if result.status is None or result.status >= 400:
        return {"action": action, "watch_id": wid, "url": target, "status": result.status,
                "changed": None, "first_check": record is None,
                "error": result.error or f"HTTP {result.status}; baseline kept"}
    ctype = (result.response_headers or {}).get("content-type", "")
    lines = readable_lines(result.body or "", ctype.lower())
    for pattern in rx:
        lines = [pattern.sub("", ln).strip() for ln in lines]
    lines = [ln for ln in lines if ln]
    digest = hashlib.sha256("\n".join(lines).encode()).hexdigest()

    if record is None:
        store.put({"id": wid, "url": target, "ignore": patterns, "lines": lines, "hash": digest,
                   "created": now, "checked": now, "changed": None, "checks": 1, "changes": 0})
        return {"action": action, "watch_id": wid, "url": target, "status": result.status,
                "first_check": True, "changed": False, "lines": len(lines),
                "text": f"baseline saved: {len(lines)} lines of text", "error": None}

    changed = digest != record["hash"]
    diff_lines = []
    added = removed = 0
    if changed:
        diff_lines = list(difflib.unified_diff(record["lines"], lines, "before", "after",
                                               lineterm="", n=1))
        added = sum(1 for d in diff_lines if d.startswith("+") and not d.startswith("+++"))
        removed = sum(1 for d in diff_lines if d.startswith("-") and not d.startswith("---"))
    store.put({"id": wid, "url": target, "ignore": patterns, "lines": lines, "hash": digest,
               "created": record["created"], "checked": now,
               "changed": now if changed else record["changed"],
               "checks": record["checks"] + 1, "changes": record["changes"] + int(changed)})
    return {
        "action": action,
        "watch_id": wid,
        "url": target,
        "status": result.status,
        "first_check": False,
        "changed": changed,
        "added_lines": added,
        "removed_lines": removed,
        "diff": "\n".join(diff_lines[:MAX_DIFF_LINES]) if changed else None,
        "diff_truncated": len(diff_lines) > MAX_DIFF_LINES,
        "previous_check": _iso(record["checked"]),
        "checks": record["checks"] + 1,
        "text": (f"changed: +{added} / -{removed} lines since {_iso(record['checked'])}"
                 if changed else f"no change since {_iso(record['checked'])}"),
        "error": None,
    }


__all__ = ["WatchError", "WatchStore", "readable_lines", "web_watch"]
