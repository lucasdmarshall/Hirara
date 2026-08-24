"""MCP front end — read application logs from allowlisted paths.

    python -m hiraraops.mcp_server
"""

from __future__ import annotations

import argparse

from mcp.server.mcpserver import MCPServer

from .tools import Toolset

server = MCPServer(
    name="hiraraops",
    version="0.1.0",
    instructions=(
        "Self-hosted ops tools, no API keys. Use application_logs to tail or "
        "head a log file (optional regex/level filters). Paths must be under "
        "COPS_ROOTS when configured."
    ),
)

_toolset = Toolset.from_env()


@server.tool(
    name="application_logs",
    description=(
        "Read log lines (tail by default). Optional path or named source, "
        "lines, from_end, pattern regex, and level filter."
    ),
)
async def application_logs_tool(
    path: str | None = None,
    source: str | None = None,
    lines: int | None = None,
    from_end: bool = True,
    pattern: str | None = None,
    level: str | None = None,
    max_bytes: int | None = None,
) -> dict:
    """Read application log lines.

    Args:
        path: Log file path.
        source: Named source from COPS_LOG_SOURCES.
        lines: Max lines to return.
        from_end: Tail (true) or head (false).
        pattern: Optional regex filter.
        level: Optional level filter.
        max_bytes: Cap on bytes read.
    """
    return await _toolset.application_logs(
        path=path,
        source=source,
        lines=lines,
        from_end=from_end,
        pattern=pattern,
        level=level,
        max_bytes=max_bytes,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="HiraraOps MCP server")
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=["stdio", "sse", "streamable-http"],
    )
    args = parser.parse_args()
    server.run(transport=args.transport)


if __name__ == "__main__":
    main()
