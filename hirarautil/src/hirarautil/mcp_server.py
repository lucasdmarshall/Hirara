"""MCP front end — decode, hash, and JWT helpers.

    python -m hirarautil.mcp_server
"""

from __future__ import annotations

import argparse

from mcp.server.mcpserver import MCPServer

from .tools import Toolset

server = MCPServer(
    name="hirarautil",
    version="0.1.0",
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


def main() -> None:
    parser = argparse.ArgumentParser(description="HiraraUtil MCP server")
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=["stdio", "sse", "streamable-http"],
    )
    args = parser.parse_args()
    server.run(transport=args.transport)


if __name__ == "__main__":
    main()
