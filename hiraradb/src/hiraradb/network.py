"""Rust SQL adapters selected only from administrator-configured database names."""
from __future__ import annotations

import math
import time

from hirara_core.native import native_call
from .config import DbConfig


def is_network(database: str | None, path: str | None, config: DbConfig) -> bool:
    # A URL passed through path= must not become a new SSRF/credential channel.
    if path:
        return "://" in path and not path.startswith("sqlite://")
    raw = config.resolved_databases().get((database or "default").strip(), "")
    return raw.split(":", 1)[0].lower() in {"postgres", "postgresql", "mysql"}


async def call(action: str, *, config: DbConfig, database: str | None, path: str | None,
               **args) -> dict:
    started = time.perf_counter()
    name = (database or "default").strip()
    if path:
        return {"database": name, "error": "network database URLs must be configured by the server; use database=, never path="}
    url = config.resolved_databases().get(name)
    if not url:
        return {"database": name, "error": "unknown configured database"}
    if not math.isfinite(config.timeout) or config.timeout <= 0:
        return {"database": name, "error": "CDB_TIMEOUT must be positive and finite"}
    for key in ("max_rows", "max_tables"):
        if key in args:
            requested = args[key]
            if requested is not None and (isinstance(requested, bool) or not isinstance(requested, int) or requested < 1):
                return {"database": name, "error": f"{key} must be a positive integer"}
            args[key] = min(requested or config.max_rows, config.max_rows)
    if action == "database_query":
        args["readonly"] = config.readonly or (config.readonly if args.get("readonly") is None else bool(args["readonly"]))
    result = await native_call(action, **args, url=url, timeout_ms=max(1, min(int(config.timeout*1000), 300_000)),
                               max_sql_chars=config.max_sql_chars)
    # Credentials/DSNs are never returned as path or diagnostic context.
    return {**result, "database": name, "path": None,
            "duration_ms": int((time.perf_counter()-started)*1000)}
