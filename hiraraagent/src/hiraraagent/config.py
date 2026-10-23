"""Runtime configuration for HiraraAgent (environment prefix ``HG_``)."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw else default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw else default


@dataclass(frozen=True)
class AgentConfig:
    # One SQLite file holds memory, questions and reminders. Persistence is
    # the point of these tools, so the default is a file, not ":memory:".
    db: str = "~/.hirara/agent.db"

    max_value_bytes: int = 100_000
    max_entries: int = 20_000

    # wait_until never blocks longer than this.
    # Below the hub's default 120 s request timeout, so a wait through the hub
    # returns before the hub gives up on it.
    max_wait: float = 100.0

    # Optional webhook told about each new ask_human request (ntfy, Slack,
    # Discord, a script...). Operator-configured, so it may be internal.
    notify_url: str | None = None
    notify_timeout: float = 10.0

    # Protects the /human answer page and API. Unset = open (fine on loopback).
    human_token: str | None = None

    # Link to the answer page included in notifications.
    public_url: str | None = None

    @classmethod
    def from_env(cls) -> "AgentConfig":
        return cls(
            db=os.getenv("HG_DB") or cls.db,
            max_value_bytes=_env_int("HG_MAX_VALUE_BYTES", cls.max_value_bytes),
            max_entries=_env_int("HG_MAX_ENTRIES", cls.max_entries),
            max_wait=_env_float("HG_MAX_WAIT", cls.max_wait),
            notify_url=os.getenv("HG_NOTIFY_URL") or None,
            notify_timeout=_env_float("HG_NOTIFY_TIMEOUT", cls.notify_timeout),
            human_token=os.getenv("HG_HUMAN_TOKEN") or None,
            public_url=os.getenv("HG_PUBLIC_URL") or None,
        )


__all__ = ["AgentConfig"]
