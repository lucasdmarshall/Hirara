"""MCP front end — agents resolve DNS as a tool.

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
        "hostname (A/AAAA by default) or reverse-lookup an IP (PTR). Answers "
        "that are private/reserved IPs are annotated, not hidden. This tool "
        "never connects to the resolved addresses."
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
