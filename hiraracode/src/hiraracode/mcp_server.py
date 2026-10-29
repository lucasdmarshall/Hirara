"""MCP front end — agents and IDEs run code as a tool.

Run over stdio for Claude Code / Claude Desktop / Cursor::

    python -m hiraracode.mcp_server

Or over HTTP for a remote client::

    python -m hiraracode.mcp_server --transport stdio

SECURITY: this server drives the Docker daemon (root-equivalent on the host).
Run it locally / behind auth. The executed code is sandboxed; the server is not.
"""

from __future__ import annotations

from hirara_core.policy import mcp_errors

import argparse

from mcp.server.mcpserver import MCPServer

from .tools import Toolset

_toolset = Toolset.from_env()
_languages = ", ".join(_toolset.runner.languages()) or "python, node, bash"

server = MCPServer(
    name="hiraracode",
    version="0.2.0",
    instructions=(
        "Run code in a sandboxed throwaway container and read its output. Use "
        "execute_code to actually run a snippet — check a calculation, test "
        "code, transform data — rather than reasoning about it. No network by "
        "default and no persistent filesystem: write self-contained code that "
        f"prints its results. Languages: {_languages}. For anything long-running "
        "(a server, a build, a test suite) use job_start, then job_status to "
        "read new output, and job_stop when done."
    ),
)


@server.tool(
    name="execute_code",
    description=(
        "Run a short program in a sandboxed, throwaway container and get back "
        "its stdout, stderr and exit code. Use it to actually run code rather "
        "than reason about it: check a calculation, test a snippet, parse or "
        "transform data. No network by default, no persistent filesystem — "
        "each call starts clean, so write self-contained code that prints its "
        f"results. Languages: {_languages}. A non-zero exit_code is a normal "
        "result, not a tool failure."
    ),
)
@mcp_errors
async def execute_code_tool(
    language: str,
    code: str,
    stdin: str | None = None,
    timeout: float | None = None,
) -> dict:
    """Run code in a sandboxed container.

    Args:
        language: Which runtime to use (e.g. python, node, bash).
        code: Source code to run. Make it self-contained and print output.
        stdin: Optional text fed to the program's standard input.
        timeout: Optional wall-clock limit in seconds (clamped to the ceiling).
    """
    return await _toolset.execute(
        language=language, code=code, stdin=stdin, timeout=timeout
    )


_job_schemas = {s["name"]: s for s in _toolset.schemas()}


@server.tool(name="job_start", description=_job_schemas["job_start"]["description"])
@mcp_errors
async def job_start_tool(language: str, code: str, stdin: str | None = None,
                         timeout: float | None = None) -> dict:
    return await _toolset.job_start(language=language, code=code, stdin=stdin, timeout=timeout)


@server.tool(name="job_status", description=_job_schemas["job_status"]["description"])
@mcp_errors
async def job_status_tool(job_id: str | None = None, stdout_cursor: int = 0,
                          stderr_cursor: int = 0) -> dict:
    return await _toolset.job_status(job_id=job_id, stdout_cursor=stdout_cursor,
                                     stderr_cursor=stderr_cursor)


@server.tool(name="job_stop", description=_job_schemas["job_stop"]["description"])
@mcp_errors
async def job_stop_tool(job_id: str) -> dict:
    return await _toolset.job_stop(job_id=job_id)


def main() -> None:
    parser = argparse.ArgumentParser(description="Hiraracode MCP server")
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=["stdio", "sse", "streamable-http"],
        help="MCP transport to serve on (default: stdio).",
    )
    args = parser.parse_args()
    if args.transport != "stdio":
        parser.error("network MCP is disabled; use stdio or the authenticated HTTP hub")
    server.run(transport=args.transport)


if __name__ == "__main__":
    main()
