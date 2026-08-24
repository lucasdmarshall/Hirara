"""MCP front end — agents read files from allowlisted paths.

Run over stdio for Claude Code / Claude Desktop / Cursor::

    python -m hirarafs.mcp_server

Or over HTTP for a remote client::

    python -m hirarafs.mcp_server --transport streamable-http
"""

from __future__ import annotations

import argparse

from mcp.server.mcpserver import MCPServer

from .tools import Toolset

server = MCPServer(
    name="hirarafs",
    version="0.1.0",
    instructions=(
        "Self-hosted filesystem tools, no API keys. Use file_read to read a "
        "file from an allowlisted path. Content is utf-8 text when possible, "
        "otherwise base64. Paths outside CFS_ROOTS are rejected."
    ),
)

_toolset = Toolset.from_env()


@server.tool(
    name="file_read",
    description=(
        "Read a local file. Returns utf-8 text when possible, else base64. "
        "Optional encoding, max_bytes, and offset. Paths must be under "
        "configured roots when CFS_ALLOW_ANY_PATH is false."
    ),
)
async def file_read_tool(
    path: str,
    encoding: str | None = None,
    max_bytes: int | None = None,
    offset: int = 0,
) -> dict:
    """Read a file from the local filesystem.

    Args:
        path: Absolute or relative path to a regular file.
        encoding: auto, utf-8, ascii, latin-1, or base64.
        max_bytes: Cap on bytes returned after offset.
        offset: Byte offset to start reading from.
    """
    return await _toolset.file_read(
        path=path,
        encoding=encoding,
        max_bytes=max_bytes,
        offset=offset,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="HiraraFs MCP server")
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
