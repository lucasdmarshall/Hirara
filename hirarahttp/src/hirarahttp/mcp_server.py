"""MCP front end — agents use HTTP tools.

Run over stdio for Claude Code / Claude Desktop / Cursor::

    python -m hirarahttp.mcp_server

Or over HTTP for a remote client::

    python -m hirarahttp.mcp_server --transport streamable-http
"""

from __future__ import annotations

import argparse

from mcp.server.mcpserver import MCPServer

from .tools import Toolset

server = MCPServer(
    name="hirarahttp",
    version="0.1.0",
    instructions=(
        "Self-hosted HTTP tools, no API keys. Use http_request to send a raw "
        "HTTP request, http_history, inspect_*, directory_enum, request_replay, "
        "parameter_test, and response_compare. URLs and redirect hops go "
        "through Hirara's SSRF perimeter."
    ),
)

_toolset = Toolset.from_env()


@server.tool(
    name="http_request",
    description=(
        "Send an HTTP request and return status, headers, and body. Pass "
        "method, optional headers/body, and follow_redirects. 4xx/5xx are "
        "returned as data; blocked URLs set error."
    ),
)
async def http_request_tool(
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: str | None = None,
    timeout: float | None = None,
    follow_redirects: bool = True,
    max_redirects: int | None = None,
    max_bytes: int | None = None,
) -> dict:
    """Send an HTTP request through the SSRF perimeter.

    Args:
        url: http(s) URL to request.
        method: GET / HEAD / POST / PUT / PATCH / DELETE / OPTIONS.
        headers: Optional request headers.
        body: Optional UTF-8 body (not with GET/HEAD).
        timeout: Timeout in seconds.
        follow_redirects: Follow redirects when true.
        max_redirects: Max hops.
        max_bytes: Cap on response body bytes.
    """
    return await _toolset.http_request(
        url=url,
        method=method,
        headers=headers,
        body=body,
        timeout=timeout,
        follow_redirects=follow_redirects,
        max_redirects=max_redirects,
        max_bytes=max_bytes,
    )


@server.tool(
    name="http_history",
    description=(
        "List or fetch recent http_request calls from this process. Newest "
        "first. Pass id for one full entry; clear=true to wipe the buffer."
    ),
)
async def http_history_tool(
    limit: int = 20,
    offset: int = 0,
    id: str | None = None,
    include_body: bool = False,
    clear: bool = False,
) -> dict:
    """List or fetch recorded HTTP exchanges.

    Args:
        limit: Max entries (default 20).
        offset: Skip newest N for pagination.
        id: Fetch one entry by request_id.
        include_body: Include bodies in list mode.
        clear: Wipe history when true.
    """
    return await _toolset.http_history(
        limit=limit,
        offset=offset,
        id=id,
        include_body=include_body,
        clear=clear,
    )


@server.tool(
    name="inspect_headers",
    description=(
        "Inspect HTTP headers from a recorded request (id) or a raw headers "
        "object. Returns sorted list, by_name, interesting fields, and "
        "missing_common security headers for responses."
    ),
)
async def inspect_headers_tool(
    id: str | None = None,
    which: str = "response",
    headers: dict[str, str] | None = None,
) -> dict:
    """Inspect request or response headers.

    Args:
        id: History request_id.
        which: request / response / both.
        headers: Raw header map when id is omitted.
    """
    return await _toolset.inspect_headers(id=id, which=which, headers=headers)


@server.tool(
    name="inspect_cookies",
    description=(
        "Parse Cookie / Set-Cookie from a recorded request (id) or a raw "
        "headers object. Returns name/value plus Set-Cookie attributes and "
        "flags_missing (Secure, HttpOnly, SameSite)."
    ),
)
async def inspect_cookies_tool(
    id: str | None = None,
    which: str = "response",
    headers: dict[str, str] | None = None,
) -> dict:
    """Parse request or response cookies.

    Args:
        id: History request_id.
        which: request / response / both.
        headers: Raw header map when id is omitted.
    """
    return await _toolset.inspect_cookies(id=id, which=which, headers=headers)


@server.tool(
    name="inspect_response",
    description=(
        "Summarize an HTTP response from a recorded request (id) or raw "
        "status/body/headers. Returns status class, body_kind, JSON keys, "
        "HTML title, and a preview. Pass include_body=true for the full body."
    ),
)
async def inspect_response_tool(
    id: str | None = None,
    include_body: bool = False,
    preview_chars: int = 512,
    status: int | None = None,
    body: str | None = None,
    headers: dict[str, str] | None = None,
    body_encoding: str | None = None,
) -> dict:
    """Summarize status and body structure.

    Args:
        id: History request_id.
        include_body: Include full body and parsed json.
        preview_chars: Preview length.
        status: Raw status when id is omitted.
        body: Raw body when id is omitted.
        headers: Raw response headers when id is omitted.
        body_encoding: utf-8 or base64 for a raw body.
    """
    return await _toolset.inspect_response(
        id=id,
        include_body=include_body,
        preview_chars=preview_chars,
        status=status,
        body=body,
        headers=headers,
        body_encoding=body_encoding,
    )


@server.tool(
    name="directory_enum",
    description=(
        "Probe a base URL for existing paths. HEAD/GET each relative path "
        "without following redirects. Omit paths for a built-in common list."
    ),
)
async def directory_enum_tool(
    url: str,
    paths: list[str] | str | None = None,
    method: str = "HEAD",
    timeout: float | None = None,
    concurrency: int | None = None,
    include_not_found: bool = False,
) -> dict:
    """Probe paths under a base URL.

    Args:
        url: Base http(s) URL.
        paths: Relative paths, or omit for defaults.
        method: HEAD, GET, or OPTIONS.
        timeout: Per-path timeout seconds.
        concurrency: Max concurrent probes.
        include_not_found: Include 404/410 in results.
    """
    return await _toolset.directory_enum(
        url=url,
        paths=paths,
        method=method,
        timeout=timeout,
        concurrency=concurrency,
        include_not_found=include_not_found,
    )


@server.tool(
    name="request_replay",
    description=(
        "Replay a recorded http_request by history id with optional "
        "url/method/headers/body overrides."
    ),
)
async def request_replay_tool(
    id: str,
    url: str | None = None,
    method: str | None = None,
    headers: dict[str, str] | None = None,
    body: str | None = None,
    merge_headers: bool = True,
    timeout: float | None = None,
    follow_redirects: bool = True,
    max_redirects: int | None = None,
    max_bytes: int | None = None,
) -> dict:
    """Replay a recorded request.

    Args:
        id: History request_id.
        url: Optional URL override.
        method: Optional method override.
        headers: Optional header overrides.
        body: Optional body override.
        merge_headers: Merge overrides into stored headers.
        timeout: Request timeout seconds.
        follow_redirects: Follow redirects.
        max_redirects: Max redirect hops.
        max_bytes: Response body cap.
    """
    return await _toolset.request_replay(
        id=id,
        url=url,
        method=method,
        headers=headers,
        body=body,
        merge_headers=merge_headers,
        timeout=timeout,
        follow_redirects=follow_redirects,
        max_redirects=max_redirects,
        max_bytes=max_bytes,
    )


@server.tool(
    name="parameter_test",
    description=(
        "Vary one parameter (query/header/cookie/body/path) across values "
        "against a base request from history id and/or url."
    ),
)
async def parameter_test_tool(
    location: str,
    name: str,
    values: list[str] | str,
    id: str | None = None,
    url: str | None = None,
    method: str | None = None,
    headers: dict[str, str] | None = None,
    body: str | None = None,
    timeout: float | None = None,
    follow_redirects: bool = True,
    max_redirects: int | None = None,
    max_bytes: int | None = None,
    concurrency: int | None = None,
    include_body: bool = False,
    body_preview_chars: int = 200,
) -> dict:
    """Test one parameter across multiple values.

    Args:
        location: query, header, cookie, body, path, or url.
        name: Parameter name.
        values: Values to try.
        id: Optional history base request.
        url: Base URL when not using history alone.
        method: HTTP method.
        headers: Request headers.
        body: Request body.
        timeout: Per-request timeout.
        follow_redirects: Follow redirects.
        max_redirects: Max redirect hops.
        max_bytes: Response body cap.
        concurrency: Max concurrent probes.
        include_body: Include body_preview per trial.
        body_preview_chars: Preview length.
    """
    return await _toolset.parameter_test(
        location=location,
        name=name,
        values=values,
        id=id,
        url=url,
        method=method,
        headers=headers,
        body=body,
        timeout=timeout,
        follow_redirects=follow_redirects,
        max_redirects=max_redirects,
        max_bytes=max_bytes,
        concurrency=concurrency,
        include_body=include_body,
        body_preview_chars=body_preview_chars,
    )


@server.tool(
    name="response_compare",
    description=(
        "Compare two responses by history id and/or inline status/headers/body."
    ),
)
async def response_compare_tool(
    left_id: str | None = None,
    right_id: str | None = None,
    left_status: int | None = None,
    right_status: int | None = None,
    left_headers: dict[str, str] | None = None,
    right_headers: dict[str, str] | None = None,
    left_body: str | None = None,
    right_body: str | None = None,
    compare_headers: bool = True,
    compare_body: bool = True,
    ignore_headers: list[str] | str | None = None,
) -> dict:
    """Diff two HTTP responses.

    Args:
        left_id: Left history id.
        right_id: Right history id.
        left_status: Inline left status.
        right_status: Inline right status.
        left_headers: Inline left headers.
        right_headers: Inline right headers.
        left_body: Inline left body.
        right_body: Inline right body.
        compare_headers: Include header diff.
        compare_body: Include body diff.
        ignore_headers: Headers to ignore.
    """
    return await _toolset.response_compare(
        left_id=left_id,
        right_id=right_id,
        left_status=left_status,
        right_status=right_status,
        left_headers=left_headers,
        right_headers=right_headers,
        left_body=left_body,
        right_body=right_body,
        compare_headers=compare_headers,
        compare_body=compare_body,
        ignore_headers=ignore_headers,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="HiraraHttp MCP server")
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=["stdio", "sse", "streamable-http"],
    )
    args = parser.parse_args()
    server.run(transport=args.transport)


if __name__ == "__main__":
    main()
