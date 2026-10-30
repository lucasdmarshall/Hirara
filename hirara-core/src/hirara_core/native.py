"""Small, lazy bridge to the optional Rust wheel. Never builds/downloads at runtime."""
from __future__ import annotations

import asyncio
import json


async def native_call(action: str, **arguments) -> dict:
    try:
        from hirara_native import run
    except ImportError:
        return {"error": "Rust backend unavailable; install hirara-native (see docs/native-tools.md)"}
    try:
        request = json.dumps({"action": action, **arguments}, ensure_ascii=False, allow_nan=False)
        return json.loads(await asyncio.to_thread(run, request))
    except (TypeError, ValueError, RuntimeError) as exc:
        return {"error": f"native tool failed: {exc}"}
