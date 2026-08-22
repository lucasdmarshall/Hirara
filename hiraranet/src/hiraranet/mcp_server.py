"""MCP front end — agents use network tools.

Run over stdio for Claude Code / Claude Desktop / Cursor::

    python -m hiraranet.mcp_server

Or over HTTP for a remote client::

    python -m hiraranet.mcp_server --transport streamable-http
"""

from __future__ import annotations

import argparse

from mcp.server.mcpserver import MCPServer

from .tools import Toolset

server = MCPServer(
    name="hiraranet",
    version="0.1.0",
    instructions=(
        "Self-hosted network tools, no API keys. Use dns_lookup to resolve a "
        "hostname, port_scan to find open TCP ports, and service_enum to "
        "identify what is speaking on those ports (banner + light probes). "
        "Resolved IPs are annotated with routable / block_reason."
    ),
)

_toolset = Toolset.from_env()


@server.tool(
    name="dns_lookup",
    description=(
        "Resolve a DNS name (or reverse-lookup an IP). Returns typed answers "
        "(A, AAAA, CNAME, MX, TXT, NS, SOA, PTR, SRV, CAA). A/AAAA values are "
        "annotated with routable / block_reason. DNS only — no TCP connect."
    ),
)
async def dns_lookup_tool(
    name: str,
    record_types: list[str] | None = None,
    nameserver: str | None = None,
) -> dict:
    """Resolve a hostname or reverse-lookup an IP.

    Args:
        name: Hostname (e.g. example.com) or IP address for PTR.
        record_types: Optional list of types; defaults to A and AAAA.
        nameserver: Optional recursive resolver IP/host.
    """
    return await _toolset.dns_lookup(
        name=name,
        record_types=record_types,
        nameserver=nameserver,
    )


@server.tool(
    name="port_scan",
    description=(
        "TCP-connect scan a host for open ports. Resolves once, then probes "
        "each port. Returns per-port status (open/closed/timeout/error), "
        "latency, and open_ports. Omit ports for a common-port default list; "
        "ranges like \"8000-8010\" are accepted."
    ),
)
async def port_scan_tool(
    host: str,
    ports: list[int | str] | str | None = None,
    timeout: float | None = None,
    concurrency: int | None = None,
) -> dict:
    """TCP-connect scan a hostname or IP.

    Args:
        host: Hostname or IP to scan.
        ports: Ports / ranges to probe, or omit for defaults.
        timeout: Per-port connect timeout in seconds.
        concurrency: Max simultaneous connect attempts.
    """
    return await _toolset.port_scan(
        host=host,
        ports=ports,
        timeout=timeout,
        concurrency=concurrency,
    )


@server.tool(
    name="service_enum",
    description=(
        "Identify services on TCP ports: connect, read banner / send a short "
        "probe, return service name, product, banner, and tls flag. Same ports "
        "shape as port_scan. Optional tls=true/false; omit to auto-select."
    ),
)
async def service_enum_tool(
    host: str,
    ports: list[int | str] | str | None = None,
    timeout: float | None = None,
    concurrency: int | None = None,
    tls: bool | None = None,
) -> dict:
    """Identify services listening on a host's ports.

    Args:
        host: Hostname or IP to probe.
        ports: Ports / ranges to probe, or omit for defaults.
        timeout: Per-port timeout in seconds.
        concurrency: Max simultaneous probes.
        tls: Force TLS on/off; omit for port-based auto.
    """
    return await _toolset.service_enum(
        host=host,
        ports=ports,
        timeout=timeout,
        concurrency=concurrency,
        tls=tls,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="HiraraNet MCP server")
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=["stdio", "sse", "streamable-http"],
        help="MCP transport to serve on (default: stdio).",
    )
    args = parser.parse_args()
    server.run(transport=args.transport)


if __name__ == "__main__":
    main()
