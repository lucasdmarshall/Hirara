"""MCP front end — agents use HTTP tools.

Run over stdio for Claude Code / Claude Desktop / Cursor::

    python -m hirarahttp.mcp_server

Or over HTTP for a remote client::

    python -m hirarahttp.mcp_server --transport streamable-http
"""

from __future__ import annotations

import argparse

from mcp.server.mcpserver import MCPServer

from .tools import Toolset

server = MCPServer(
    name="hirarahttp",
    version="0.1.0",
    instructions=(
        "Self-hosted HTTP tools, no API keys. Use http_request to send a raw "
        "HTTP request (any method) and get status, headers, and body. URLs and "
        "redirect hops go through Hirara's SSRF perimeter."
    ),
)

_toolset = Toolset.from_env()


@server.tool(
    name="http_request",
    description=(
        "Send an HTTP request and return status, headers, and body. Pass "
        "method, optional headers/body, and follow_redirects. 4xx/5xx are "
        "returned as data; blocked URLs set error."
    ),
)
async def http_request_tool(
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: str | None = None,
    timeout: float | None = None,
    follow_redirects: bool = True,
    max_redirects: int | None = None,
    max_bytes: int | None = None,
) -> dict:
    """Send an HTTP request through the SSRF perimeter.

    Args:
        url: http(s) URL to request.
        method: GET / HEAD / POST / PUT / PATCH / DELETE / OPTIONS.
        headers: Optional request headers.
        body: Optional UTF-8 body (not with GET/HEAD).
        timeout: Timeout in seconds.
        follow_redirects: Follow redirects when true.
        max_redirects: Max hops.
        max_bytes: Cap on response body bytes.
    """
    return await _toolset.http_request(
        url=url,
        method=method,
        headers=headers,
        body=body,
        timeout=timeout,
        follow_redirects=follow_redirects,
        max_redirects=max_redirects,
        max_bytes=max_bytes,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="HiraraHttp MCP server")
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=["stdio", "sse", "streamable-http"],
    )
    args = parser.parse_args()
    server.run(transport=args.transport)


if __name__ == "__main__":
    main()
