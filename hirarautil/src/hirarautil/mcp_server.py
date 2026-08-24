"""MCP front end — decode common encodings.

    python -m hirarautil.mcp_server
"""

from __future__ import annotations

import argparse

from mcp.server.mcpserver import MCPServer

from .tools import Toolset

server = MCPServer(
    name="hirarautil",
    version="0.1.0",
    instructions=(
        "Self-hosted utility tools, no API keys. Use decode to turn base64, "
        "hex, url-encoded, html-entity, or unicode-escaped strings into text "
        "(or base64 when the result is binary)."
    ),
)

_toolset = Toolset.from_env()


@server.tool(
    name="decode",
    description=(
        "Decode base64, base64url, hex, url, html, or unicode_escape. "
        "format=auto detects when possible."
    ),
)
async def decode_tool(input: str, format: str = "auto") -> dict:
    """Decode an encoded string.

    Args:
        input: Encoded string.
        format: auto, base64, base64url, hex, url, html, or unicode_escape.
    """
    return await _toolset.decode(input=input, format=format)


def main() -> None:
    parser = argparse.ArgumentParser(description="HiraraUtil MCP server")
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=["stdio", "sse", "streamable-http"],
    )
    args = parser.parse_args()
    server.run(transport=args.transport)


if __name__ == "__main__":
    main()
