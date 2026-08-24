"""MCP front end — query and inspect configured SQLite databases.

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
        "one SQL statement, and database_schema to list tables/columns. "
        "Read-only by default."
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


@server.tool(
    name="database_schema",
    description=(
        "List SQLite tables/views and columns. Optional table filter; "
        "include_indexes, include_foreign_keys, include_sql for more detail."
    ),
)
async def database_schema_tool(
    database: str | None = None,
    path: str | None = None,
    table: str | None = None,
    include_views: bool = True,
    include_indexes: bool = False,
    include_foreign_keys: bool = False,
    include_sql: bool = False,
    max_tables: int | None = None,
) -> dict:
    """Inspect database schema.

    Args:
        database: Named DB from config.
        path: Ad-hoc sqlite path.
        table: Limit to one table/view.
        include_views: Include views (default true).
        include_indexes: Include indexes.
        include_foreign_keys: Include foreign keys.
        include_sql: Include CREATE SQL.
        max_tables: Cap on objects returned.
    """
    return await _toolset.database_schema(
        database=database,
        path=path,
        table=table,
        include_views=include_views,
        include_indexes=include_indexes,
        include_foreign_keys=include_foreign_keys,
        include_sql=include_sql,
        max_tables=max_tables,
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
