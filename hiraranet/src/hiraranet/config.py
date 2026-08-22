"""Runtime configuration for HiraraNet.

Everything is overridable by environment variable so the same image can run
on a trusted laptop or locked down on a network-exposed host.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# Record types agents commonly need. Keep the allowlist tight — DNS is free
# egress to whoever the resolver talks to, and odd types are rarely useful.
DEFAULT_RECORD_TYPES: tuple[str, ...] = ("A", "AAAA")
ALLOWED_RECORD_TYPES = frozenset(
    {"A", "AAAA", "CNAME", "MX", "TXT", "NS", "SOA", "PTR", "SRV", "CAA"}
)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw else default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw else default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    return raw.strip().lower() in {"1", "true", "yes", "on"} if raw else default


def _env_csv(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.getenv(name)
    if not raw:
        return default
    return tuple(part.strip().upper() for part in raw.split(",") if part.strip())


@dataclass(frozen=True)
class NetConfig:
    """Network-tool knobs."""

    # Default record types when the caller omits ``record_types``.
    default_record_types: tuple[str, ...] = DEFAULT_RECORD_TYPES

    # Wall-clock seconds for one DNS query (per type).
    timeout: float = 5.0

    # Cap on how many record types a single call may request.
    max_types: int = 8

    # Cap on answers returned across all types (agent-facing bound).
    max_answers: int = 64

    # Optional recursive resolver IP/host. Empty = system default resolvers.
    nameserver: str | None = None

    # When True, answers whose value is a non-global IP are still returned but
    # flagged via ``routable`` / ``block_reason`` (using hirara-core.check_ip).
    # There is no "block private answers" mode on purpose: DNS lookup is
    # read-only and agents need to *see* that a name points at 127.0.0.1.
    annotate_ips: bool = True

    @classmethod
    def from_env(cls) -> "NetConfig":
        nameserver = os.getenv("CNET_NAMESERVER") or None
        types = _env_csv("CNET_DEFAULT_RECORD_TYPES", cls.default_record_types)
        return cls(
            default_record_types=types or DEFAULT_RECORD_TYPES,
            timeout=_env_float("CNET_TIMEOUT", cls.timeout),
            max_types=_env_int("CNET_MAX_TYPES", cls.max_types),
            max_answers=_env_int("CNET_MAX_ANSWERS", cls.max_answers),
            nameserver=nameserver,
            annotate_ips=_env_bool("CNET_ANNOTATE_IPS", cls.annotate_ips),
        )


__all__ = [
    "ALLOWED_RECORD_TYPES",
    "DEFAULT_RECORD_TYPES",
    "NetConfig",
]
