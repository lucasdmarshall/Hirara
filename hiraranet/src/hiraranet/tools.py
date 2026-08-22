"""The tool layer: schema and JSON-ready results.

Both front ends (HTTP service and MCP server) call into here, so the two can
never drift apart in behaviour — only in transport.

Tools: ``dns_lookup``, ``port_scan``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .config import NetConfig
from .lookup import LookupError, lookup_dns, result_to_dict
from .scan import ScanError, scan_ports, scan_result_to_dict

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


PORT_SCAN_SCHEMA = {
    "name": "port_scan",
    "description": (
        "TCP-connect scan a host for open ports. Use this to learn which "
        "ports accept connections on a hostname or IP — before talking to a "
        "service, checking local listeners, or mapping what a target exposes.\n\n"
        "Resolves the host once, then probes each port with a TCP connect "
        "under a concurrency cap. Returns per-port status (open / closed / "
        "timeout / error), latency, and a summary open_ports list. The "
        "resolved IP is annotated with routable / block_reason.\n\n"
        "Omit ports to scan a built-in common-port list. Ports may be ints, "
        "strings, or ranges like \"8000-8010\"."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "host": {
                "type": "string",
                "description": "Hostname or IP to scan (e.g. example.com, 127.0.0.1).",
            },
            "ports": {
                "description": (
                    "Ports to probe. Accepts an array of ints/strings "
                    "(e.g. [80, 443, \"8000-8010\"]) or a comma-separated "
                    "string (\"22,80,443\"). Omit for the default common-port list."
                ),
                "oneOf": [
                    {
                        "type": "array",
                        "items": {
                            "oneOf": [
                                {"type": "integer", "minimum": 1, "maximum": 65535},
                                {"type": "string"},
                            ]
                        },
                    },
                    {"type": "string"},
                ],
            },
            "timeout": {
                "type": "number",
                "minimum": 0.1,
                "description": "Per-port connect timeout in seconds (default from server).",
            },
            "concurrency": {
                "type": "integer",
                "minimum": 1,
                "description": "Max simultaneous connect attempts (default from server).",
            },
        },
        "required": ["host"],
        "additionalProperties": False,
    },
}


def _dns_envelope(**overrides) -> dict:
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


def _scan_envelope(**overrides) -> dict:
    envelope = {
        "host": None,
        "ip": None,
        "ports": [],
        "results": [],
        "open_ports": [],
        "open_count": 0,
        "duration_ms": None,
        "routable": None,
        "block_reason": None,
        "truncated": False,
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
        return [DNS_LOOKUP_SCHEMA, PORT_SCAN_SCHEMA]

    def health(self) -> dict:
        return {
            "status": "ok",
            "version": "0.1.0",
            "tools": ["dns_lookup", "port_scan"],
            "default_record_types": list(self.config.default_record_types),
            "default_scan_ports": list(self.config.default_scan_ports),
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
            return _dns_envelope(name=name, error=str(exc))
        except Exception as exc:  # noqa: BLE001 — agent gets a body, not a 500
            log.exception("dns_lookup failed")
            return _dns_envelope(name=name, error=f"dns_lookup failed: {exc}")

    async def port_scan(
        self,
        *,
        host: str,
        ports: list[int | str] | str | None = None,
        timeout: float | None = None,
        concurrency: int | None = None,
    ) -> dict:
        try:
            result = await scan_ports(
                host,
                ports=ports,
                timeout=timeout,
                concurrency=concurrency,
                config=self.config,
            )
            return scan_result_to_dict(result)
        except ScanError as exc:
            return _scan_envelope(host=host, error=str(exc))
        except Exception as exc:  # noqa: BLE001 — agent gets a body, not a 500
            log.exception("port_scan failed")
            return _scan_envelope(host=host, error=f"port_scan failed: {exc}")


__all__ = [
    "DNS_LOOKUP_SCHEMA",
    "PORT_SCAN_SCHEMA",
    "Toolset",
    "TOOL_NAMES",
    "call_tool",
    "tool_schemas",
]


# --- local backend: in-process dispatch for the hirara SDK -------------------
TOOL_NAMES = ("dns_lookup", "port_scan")
_local_toolset: "Toolset | None" = None


def _backend() -> "Toolset":
    global _local_toolset
    if _local_toolset is None:
        _local_toolset = Toolset.from_env()
    return _local_toolset


async def call_tool(name: str, arguments: dict | None = None) -> dict:
    """Run one tool in-process and return its response envelope."""
    args = arguments or {}
    if name == "dns_lookup":
        return await _backend().dns_lookup(**args)
    if name == "port_scan":
        return await _backend().port_scan(**args)
    raise KeyError(f"unknown tool: {name}")


def tool_schemas() -> list[dict]:
    return _backend().schemas()
