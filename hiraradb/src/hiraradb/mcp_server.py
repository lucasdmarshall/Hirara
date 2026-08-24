"""MCP front end — query configured SQLite databases.

    python -m hiraradb.mcp_server
"""

from __future__ import annotations

import argparse
from typing import Any

from mcp.server.mcpserver import MCPServer

from .tools import Toolset

server = MCPServer(
    name="hiraradb",
    version="0.1.0",
    instructions=(
        "Self-hosted database tools, no API keys. Use database_query to run "
        "one SQL statement against a configured SQLite database. Read-only by "
        "default. Pass params for placeholders."
    ),
)

_toolset = Toolset.from_env()


@server.tool(
    name="database_query",
    description=(
        "Run one SQL statement on a configured SQLite database. Read-only by "
        "default. params is a list or object. Optional database name, path, "
        "max_rows."
    ),
)
async def database_query_tool(
    sql: str,
    params: list[Any] | dict[str, Any] | None = None,
    database: str | None = None,
    path: str | None = None,
    max_rows: int | None = None,
    readonly: bool | None = None,
) -> dict:
    """Run a SQL query.

    Args:
        sql: Single SQL statement.
        params: Positional list or named object.
        database: Named DB from config.
        path: Ad-hoc sqlite path.
        max_rows: Row cap.
        readonly: Force read-only for this call.
    """
    return await _toolset.database_query(
        sql=sql,
        params=params,
        database=database,
        path=path,
        max_rows=max_rows,
        readonly=readonly,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="HiraraDb MCP server")
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=["stdio", "sse", "streamable-http"],
    )
    args = parser.parse_args()
    server.run(transport=args.transport)


if __name__ == "__main__":
    main()
