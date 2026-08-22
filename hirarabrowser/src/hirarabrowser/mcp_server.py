"""MCP front end for browser tools."""

from __future__ import annotations

import argparse

from mcp.server.mcpserver import MCPServer

from .tools import Toolset

server = MCPServer(
    name="hirarabrowser",
    version="0.1.0",
    instructions=(
        "Self-hosted browser tools. Use browser_open to load a URL and get a "
        "session_id, then browser_click to click selectors in that session."
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


@server.tool(
    name="browser_click",
    description=(
        "Click an element in an existing browser session. Pass session_id from "
        "browser_open and a CSS/text selector. Returns url/title after click."
    ),
)
async def browser_click_tool(
    session_id: str,
    selector: str,
    timeout: float | None = None,
    button: str = "left",
    click_count: int = 1,
) -> dict:
    """Click a selector in a browser session.

    Args:
        session_id: Session from browser_open.
        selector: Element selector (CSS, text=, …).
        timeout: Wait/click timeout in seconds.
        button: left / right / middle.
        click_count: 1 or 2 for double-click.
    """
    return await _toolset.browser_click(
        session_id=session_id,
        selector=selector,
        timeout=timeout,
        button=button,
        click_count=click_count,
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
