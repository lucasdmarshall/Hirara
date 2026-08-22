"""MCP front end for browser tools."""

from __future__ import annotations

import argparse

from mcp.server.mcpserver import MCPServer

from .tools import Toolset

server = MCPServer(
    name="hirarabrowser",
    version="0.1.0",
    instructions=(
        "Self-hosted browser tools. Use browser_open to load a URL, "
        "browser_click to click selectors, browser_type to fill inputs, "
        "and browser_screenshot to capture the page in that session."
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


@server.tool(
    name="browser_type",
    description=(
        "Type text into an input in an existing browser session. Defaults to "
        "clearing the field first; pass clear=false to append. Optional "
        "press_enter after typing."
    ),
)
async def browser_type_tool(
    session_id: str,
    selector: str,
    text: str,
    timeout: float | None = None,
    clear: bool = True,
    press_enter: bool = False,
    delay_ms: float | None = None,
) -> dict:
    """Type into a selector in a browser session.

    Args:
        session_id: Session from browser_open.
        selector: Input selector.
        text: Text to type.
        timeout: Wait/type timeout in seconds.
        clear: Replace existing value when true.
        press_enter: Press Enter after typing.
        delay_ms: Per-key delay when clear=false.
    """
    return await _toolset.browser_type(
        session_id=session_id,
        selector=selector,
        text=text,
        timeout=timeout,
        clear=clear,
        press_enter=press_enter,
        delay_ms=delay_ms,
    )


@server.tool(
    name="browser_screenshot",
    description=(
        "Capture a screenshot of the current page in an existing browser "
        "session. Returns image_base64 (PNG by default) plus mime_type. "
        "Pass full_page=true for the entire scrollable page, or selector to "
        "capture a single element."
    ),
)
async def browser_screenshot_tool(
    session_id: str,
    full_page: bool = False,
    selector: str | None = None,
    image_format: str = "png",
    quality: int | None = None,
    timeout: float | None = None,
) -> dict:
    """Screenshot a page or element in a browser session.

    Args:
        session_id: Session from browser_open.
        full_page: Capture the full scrollable page when true.
        selector: Optional element selector instead of the viewport.
        image_format: png or jpeg.
        quality: JPEG quality 0-100 (ignored for png).
        timeout: Screenshot timeout in seconds.
    """
    return await _toolset.browser_screenshot(
        session_id=session_id,
        full_page=full_page,
        selector=selector,
        image_format=image_format,
        quality=quality,
        timeout=timeout,
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
