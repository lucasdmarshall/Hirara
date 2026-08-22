"""Runtime configuration for HiraraNet.

Everything is overridable by environment variable so the same image can run
on a trusted laptop or locked down on a network-exposed host.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# Record types agents commonly need. Keep the allowlist tight — DNS is free
# egress to whoever the resolver talks to, and odd types are rarely useful.
DEFAULT_RECORD_TYPES: tuple[str, ...] = ("A", "AAAA")
ALLOWED_RECORD_TYPES = frozenset(
    {"A", "AAAA", "CNAME", "MX", "TXT", "NS", "SOA", "PTR", "SRV", "CAA"}
)

# Well-known ports used when port_scan omits ``ports``.
DEFAULT_SCAN_PORTS: tuple[int, ...] = (
    21,
    22,
    23,
    25,
    53,
    80,
    110,
    111,
    135,
    139,
    143,
    443,
    445,
    993,
    995,
    1433,
    1521,
    1723,
    2049,
    3306,
    3389,
    5432,
    5900,
    6379,
    8080,
    8443,
    9200,
    27017,
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


def _env_ports(name: str, default: tuple[int, ...]) -> tuple[int, ...]:
    raw = os.getenv(name)
    if not raw:
        return default
    out: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        out.append(int(part))
    return tuple(out) if out else default


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

    # When True, answers / scan targets are annotated with routable /
    # block_reason via hirara-core.check_ip.
    annotate_ips: bool = True

    # --- port_scan ---
    default_scan_ports: tuple[int, ...] = DEFAULT_SCAN_PORTS
    scan_timeout: float = 1.5
    scan_concurrency: int = 32
    max_scan_ports: int = 256

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
            default_scan_ports=_env_ports(
                "CNET_DEFAULT_SCAN_PORTS", cls.default_scan_ports
            ),
            scan_timeout=_env_float("CNET_SCAN_TIMEOUT", cls.scan_timeout),
            scan_concurrency=_env_int(
                "CNET_SCAN_CONCURRENCY", cls.scan_concurrency
            ),
            max_scan_ports=_env_int("CNET_MAX_SCAN_PORTS", cls.max_scan_ports),
        )


__all__ = [
    "ALLOWED_RECORD_TYPES",
    "DEFAULT_RECORD_TYPES",
    "DEFAULT_SCAN_PORTS",
    "NetConfig",
]
