"""MCP front end — logs, processes, and environment.

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
        "head a log file, process_list to inspect running processes from "
        "/proc, and environment_read to inspect process environment variables "
        "(with secret redaction by default)."
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


@server.tool(
    name="process_list",
    description=(
        "List running processes (pid, name, state, user, cmdline). Optional "
        "pattern, user, pid, and max_processes."
    ),
)
async def process_list_tool(
    pattern: str | None = None,
    user: str | None = None,
    pid: int | None = None,
    max_processes: int | None = None,
    include_cmdline: bool = True,
) -> dict:
    """List running processes.

    Args:
        pattern: Regex on name/cmdline.
        user: Username or uid filter.
        pid: Single process id.
        max_processes: Cap on results.
        include_cmdline: Include cmdline (default true).
    """
    return await _toolset.process_list(
        pattern=pattern,
        user=user,
        pid=pid,
        max_processes=max_processes,
        include_cmdline=include_cmdline,
    )


@server.tool(
    name="environment_read",
    description=(
        "Read environment variables for this process or another pid. Optional "
        "keys filter, pattern regex on key names, include_values, and redact."
    ),
)
async def environment_read_tool(
    pid: int | None = None,
    keys: list[str] | str | None = None,
    pattern: str | None = None,
    include_values: bool = True,
    redact: bool | None = None,
    max_vars: int | None = None,
) -> dict:
    """Read process environment variables.

    Args:
        pid: Optional process id; omit for this process.
        keys: Optional key name filter (list or comma-separated string).
        pattern: Optional regex on key names.
        include_values: Include values (default true).
        redact: Override secret redaction.
        max_vars: Cap on variables returned.
    """
    return await _toolset.environment_read(
        pid=pid,
        keys=keys,
        pattern=pattern,
        include_values=include_values,
        redact=redact,
        max_vars=max_vars,
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
