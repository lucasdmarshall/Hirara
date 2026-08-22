"""The tool layer: schema and JSON-ready results.

Both front ends (HTTP service and MCP server) call into here, so the two can
never drift apart in behaviour — only in transport.

One tool (v1): ``dns_lookup`` — resolve a hostname (or reverse-lookup an IP).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .config import NetConfig
from .lookup import LookupError, lookup_dns, result_to_dict

log = logging.getLogger(__name__)


DNS_LOOKUP_SCHEMA = {
    "name": "dns_lookup",
    "description": (
        "Resolve a DNS name (or reverse-lookup an IP). Use this when you need "
        "addresses, mail exchangers, TXT records, or other DNS answers for a "
        "host — before connecting, diagnosing reachability, or checking what "
        "a domain publishes.\n\n"
        "Returns typed answers (A, AAAA, CNAME, MX, TXT, NS, SOA, PTR, SRV, "
        "CAA). A/AAAA values are annotated with routable / block_reason using "
        "the same private/reserved IP rules as Hirara's SSRF guard — so you "
        "can see when a name points at localhost, link-local, or CGNAT "
        "without treating that as a tool failure.\n\n"
        "This tool only queries DNS; it never opens a TCP/UDP connection to "
        "the resolved addresses."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": (
                    "Hostname to resolve (e.g. example.com), or an IP address "
                    "when requesting PTR."
                ),
            },
            "record_types": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": [
                        "A",
                        "AAAA",
                        "CNAME",
                        "MX",
                        "TXT",
                        "NS",
                        "SOA",
                        "PTR",
                        "SRV",
                        "CAA",
                    ],
                },
                "description": (
                    "DNS record types to query. Defaults to [\"A\", \"AAAA\"] "
                    "when omitted."
                ),
            },
            "nameserver": {
                "type": "string",
                "description": (
                    "Optional recursive resolver IP/host. Omit to use the "
                    "server's system resolvers."
                ),
            },
        },
        "required": ["name"],
        "additionalProperties": False,
    },
}


def _envelope(**overrides) -> dict:
    envelope = {
        "name": None,
        "record_types": [],
        "answers": [],
        "answer_count": 0,
        "truncated": False,
        "nameserver": None,
        "error": None,
    }
    envelope.update(overrides)
    return envelope


@dataclass
class Toolset:
    """Network tools sharing one config."""

    config: NetConfig

    @classmethod
    def from_env(cls) -> "Toolset":
        return cls(config=NetConfig.from_env())

    def schemas(self) -> list[dict]:
        return [DNS_LOOKUP_SCHEMA]

    def health(self) -> dict:
        return {
            "status": "ok",
            "version": "0.1.0",
            "tools": ["dns_lookup"],
            "default_record_types": list(self.config.default_record_types),
        }

    async def dns_lookup(
        self,
        *,
        name: str,
        record_types: list[str] | None = None,
        nameserver: str | None = None,
    ) -> dict:
        import asyncio

        try:
            result = await asyncio.to_thread(
                lookup_dns,
                name,
                record_types=record_types,
                nameserver=nameserver,
                config=self.config,
            )
            return result_to_dict(result)
        except LookupError as exc:
            return _envelope(name=name, error=str(exc))
        except Exception as exc:  # noqa: BLE001 — agent gets a body, not a 500
            log.exception("dns_lookup failed")
            return _envelope(name=name, error=f"dns_lookup failed: {exc}")


__all__ = [
    "DNS_LOOKUP_SCHEMA",
    "Toolset",
    "TOOL_NAMES",
    "call_tool",
    "tool_schemas",
]


# --- local backend: in-process dispatch for the hirara SDK -------------------
TOOL_NAMES = ("dns_lookup",)
_local_toolset: "Toolset | None" = None


def _backend() -> "Toolset":
    global _local_toolset
    if _local_toolset is None:
        _local_toolset = Toolset.from_env()
    return _local_toolset


async def call_tool(name: str, arguments: dict | None = None) -> dict:
    """Run one tool in-process and return its response envelope."""
    if name != "dns_lookup":
        raise KeyError(f"unknown tool: {name}")
    return await _backend().dns_lookup(**(arguments or {}))


def tool_schemas() -> list[dict]:
    return _backend().schemas()
