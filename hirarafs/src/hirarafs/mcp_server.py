"""MCP front end — agents read/write files on allowlisted paths.

Run over stdio for Claude Code / Claude Desktop / Cursor::

    python -m hirarafs.mcp_server

Or over HTTP for a remote client::

    python -m hirarafs.mcp_server --transport streamable-http
"""

from __future__ import annotations

import argparse

from mcp.server.mcpserver import MCPServer

from . import tools as T
from .tools import Toolset

server = MCPServer(
    name="hirarafs",
    version="0.1.0",
    instructions=(
        "Self-hosted filesystem tools, no API keys. Find files with file_list / "
        "file_search, read with file_read, change a file with file_edit (exact "
        "string replacement, never a full rewrite), create with file_write. "
        "archive_list / archive_extract handle zip and tar safely. Paths outside "
        "CFS_ROOTS are rejected."
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


@server.tool(
    name="file_write",
    description=(
        "Write content to a local file under configured roots. utf-8 text by "
        "default, or base64 for binary. Optional append, create_parents, "
        "overwrite."
    ),
)
async def file_write_tool(
    path: str,
    content: str,
    encoding: str | None = None,
    append: bool = False,
    create_parents: bool = False,
    overwrite: bool = True,
    max_bytes: int | None = None,
) -> dict:
    """Write a file on the local filesystem.

    Args:
        path: Absolute or relative path to write.
        content: Text or base64 contents.
        encoding: utf-8, ascii, latin-1, or base64.
        append: Append instead of replace.
        create_parents: Create missing parent directories.
        overwrite: When false, refuse to replace an existing file.
        max_bytes: Cap on encoded content size.
    """
    return await _toolset.file_write(
        path=path,
        content=content,
        encoding=encoding,
        append=append,
        create_parents=create_parents,
        overwrite=overwrite,
        max_bytes=max_bytes,
    )


@server.tool(name="file_edit", description=T.FILE_EDIT_SCHEMA["description"])
async def file_edit_tool(
    path: str,
    old_string: str | None = None,
    new_string: str | None = None,
    replace_all: bool = False,
    edits: list[dict] | None = None,
    dry_run: bool = False,
) -> dict:
    return await _toolset.file_edit(path=path, old_string=old_string, new_string=new_string,
                                    replace_all=replace_all, edits=edits, dry_run=dry_run)


@server.tool(name="file_search", description=T.FILE_SEARCH_SCHEMA["description"])
async def file_search_tool(
    pattern: str,
    path: str | None = None,
    glob: str | None = None,
    regex: bool = True,
    case_sensitive: bool = False,
    context: int = 0,
    max_results: int = 200,
    include_hidden: bool = False,
) -> dict:
    return await _toolset.file_search(pattern=pattern, path=path, glob=glob, regex=regex,
                                      case_sensitive=case_sensitive, context=context,
                                      max_results=max_results, include_hidden=include_hidden)


@server.tool(name="file_list", description=T.FILE_LIST_SCHEMA["description"])
async def file_list_tool(
    path: str | None = None,
    pattern: str | None = None,
    recursive: bool = False,
    include_hidden: bool = False,
    max_entries: int = 500,
) -> dict:
    return await _toolset.file_list(path=path, pattern=pattern, recursive=recursive,
                                    include_hidden=include_hidden, max_entries=max_entries)


@server.tool(name="archive_list", description=T.ARCHIVE_LIST_SCHEMA["description"])
async def archive_list_tool(path: str, max_entries: int = 1000) -> dict:
    return await _toolset.archive_list(path=path, max_entries=max_entries)


@server.tool(name="archive_extract", description=T.ARCHIVE_EXTRACT_SCHEMA["description"])
async def archive_extract_tool(
    path: str,
    dest: str,
    members: list[str] | None = None,
    overwrite: bool = False,
) -> dict:
    return await _toolset.archive_extract(path=path, dest=dest, members=members,
                                          overwrite=overwrite)


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
