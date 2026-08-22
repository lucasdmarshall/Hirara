"""MCP front end for browser tools."""

from __future__ import annotations

import argparse

from mcp.server.mcpserver import MCPServer

from .tools import Toolset

server = MCPServer(
    name="hirarabrowser",
    version="0.1.0",
    instructions=(
        "Self-hosted browser tools. Use browser_open to load a URL in a "
        "headless browser and get session_id / title / final url. Reuse "
        "session_id for later browser_* tools."
    ),
)

_toolset = Toolset.from_env()


@server.tool(
    name="browser_open",
    description=(
        "Open a URL in a headless browser. Returns session_id, final url, "
        "title, and optional status / body text. Pass session_id to navigate "
        "an existing session."
    ),
)
async def browser_open_tool(
    url: str,
    session_id: str | None = None,
    timeout: float | None = None,
    include_text: bool = False,
) -> dict:
    """Open a URL in a managed browser session.

    Args:
        url: http(s) URL to open.
        session_id: Optional existing session to navigate.
        timeout: Navigation timeout in seconds.
        include_text: Include visible body text when true.
    """
    return await _toolset.browser_open(
        url=url,
        session_id=session_id,
        timeout=timeout,
        include_text=include_text,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="HiraraBrowser MCP server")
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=["stdio", "sse", "streamable-http"],
    )
    args = parser.parse_args()
    server.run(transport=args.transport)


if __name__ == "__main__":
    main()
