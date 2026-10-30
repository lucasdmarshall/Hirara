"""MCP front end — decode, hash, and JWT helpers.

    python -m hirarautil.mcp_server
"""

from __future__ import annotations

from hirara_core.policy import mcp_errors

import argparse

from mcp.server.mcpserver import MCPServer

from typing import Any

from . import tools as T
from .tools import Toolset

server = MCPServer(
    name="hirarautil",
    version="0.4.0",
    instructions=(
        "Self-hosted utility tools, no API keys. Use decode for base64/hex/url/"
        "html/unicode_escape, hash for md5/sha*/blake2 digests, jwt_inspect for "
        "JWT structure/time claims, and jwt_decode for header/payload JSON "
        "(optional HS* verify)."
    ),
)

_toolset = Toolset.from_env()


@server.tool(
    name="decode",
    description=(
        "Decode base64, base64url, hex, url, html, or unicode_escape. "
        "format=auto detects when possible."
    ),
)
@mcp_errors
async def decode_tool(input: str, format: str = "auto") -> dict:
    """Decode an encoded string.

    Args:
        input: Encoded string.
        format: auto, base64, base64url, hex, url, html, or unicode_escape.
    """
    return await _toolset.decode(input=input, format=format)


@server.tool(
    name="hash",
    description=(
        "Compute digests (md5, sha1, sha256, sha512, sha3_*, blake2*). "
        "algorithms may be a name, list, or \"all\". encoding=utf-8|base64|hex; "
        "output_format=hex|base64."
    ),
)
@mcp_errors
async def hash_tool(
    input: str,
    algorithms: list[str] | str | None = None,
    encoding: str | None = None,
    output_format: str | None = None,
) -> dict:
    """Hash a string.

    Args:
        input: Text or encoded bytes to hash.
        algorithms: Algorithm name(s) or \"all\".
        encoding: utf-8, ascii, latin-1, base64, or hex.
        output_format: hex or base64.
    """
    return await _toolset.hash(
        input=input,
        algorithms=algorithms,
        encoding=encoding,
        output_format=output_format,
    )


@server.tool(
    name="jwt_inspect",
    description=(
        "Inspect a JWT: alg/typ/kid, claim keys, and exp/iat/nbf status. "
        "Optional include_claims for full payload."
    ),
)
@mcp_errors
async def jwt_inspect_tool(input: str, include_claims: bool = False) -> dict:
    """Inspect a JWT without verifying the signature.

    Args:
        input: JWT string (optional Bearer prefix).
        include_claims: Include full payload claims.
    """
    return await _toolset.jwt_inspect(input=input, include_claims=include_claims)


@server.tool(
    name="jwt_decode",
    description=(
        "Decode JWT header and payload. Optional HS256/HS384/HS512 verify "
        "with secret when verify=true."
    ),
)
@mcp_errors
async def jwt_decode_tool(
    input: str,
    verify: bool = False,
    secret: str | None = None,
    include_signature: bool = False,
) -> dict:
    """Decode a JWT to JSON.

    Args:
        input: JWT string (optional Bearer prefix).
        verify: Verify HMAC signature when true.
        secret: HMAC secret (required when verify=true).
        include_signature: Include raw signature segment.
    """
    return await _toolset.jwt_decode(
        input=input,
        verify=verify,
        secret=secret,
        include_signature=include_signature,
    )


@server.tool(name="time_now", description=T.TIME_NOW_SCHEMA["description"])
@mcp_errors
async def time_now_tool(timezones: list[str] | str | None = None) -> dict:
    return await _toolset.time_now(timezones=timezones)


@server.tool(name="date_calc", description=T.DATE_CALC_SCHEMA["description"])
@mcp_errors
async def date_calc_tool(
    operation: str,
    date: str | None = None,
    other: str | None = None,
    timezone: str | None = None,
    to_timezones: list[str] | str | None = None,
    years: int = 0,
    months: int = 0,
    weeks: int = 0,
    days: float = 0,
    hours: float = 0,
    minutes: float = 0,
    seconds: float = 0,
    business_days: int = 0,
    holidays: list[str] | None = None,
    weekend: list[str] | None = None,
) -> dict:
    return await _toolset.date_calc(
        operation=operation, date=date, other=other, timezone=timezone,
        to_timezones=to_timezones, years=years, months=months, weeks=weeks, days=days,
        hours=hours, minutes=minutes, seconds=seconds, business_days=business_days,
        holidays=holidays, weekend=weekend)


@server.tool(name="schema_validate", description=T.SCHEMA_VALIDATE_SCHEMA["description"])
@mcp_errors
async def schema_validate_tool(
    instance: Any,
    schema: Any,
    check_formats: bool = True,
    max_errors: int = 100,
) -> dict:
    return await _toolset.schema_validate(instance=instance, schema=schema,
                                          check_formats=check_formats, max_errors=max_errors)



@server.tool(name="json_query", description=T.JSON_QUERY_SCHEMA["description"])
@mcp_errors
async def json_query_tool(input: object, expression: str, syntax: str = "jmespath") -> dict:
    return await _toolset.json_query(input=input, expression=expression, syntax=syntax)



@server.tool(name="symbolic_math", description=T.SYMBOLIC_MATH_SCHEMA["description"])
@mcp_errors
async def symbolic_math_tool(operation: str, expression: str, variable: str = "x", variables: dict[str, float] | None = None, order: int = 1) -> dict:
    return await _toolset.symbolic_math(operation=operation, expression=expression, variable=variable, variables=variables, order=order)


def main() -> None:
    parser = argparse.ArgumentParser(description="HiraraUtil MCP server")
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=["stdio", "sse", "streamable-http"],
    )
    args = parser.parse_args()
    if args.transport != "stdio":
        parser.error("network MCP is disabled; use stdio or the authenticated HTTP hub")
    server.run(transport=args.transport)


if __name__ == "__main__":
    main()
