"""Federated stdio MCP, using backend schemas and explicit tool-error results.

Network MCP is deliberately disabled until an authenticated transport is
implemented. HUB_TOKEN protects the HTTP API; it is not a stdio credential.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from jsonschema import Draft202012Validator

from . import banner
from .config import HubConfig
from .gateway import Gateway
from .registry import TOOLS

_config = HubConfig.from_env()
_gateway = Gateway(_config)
_schemas: dict[str, dict] = {}


async def list_tools(context=None, params=None):
    payload = await _gateway.schemas()
    tools = []
    for schema in payload["tools"]:
        name = schema["name"]
        contract = schema.get("input_schema", {"type": "object"})
        Draft202012Validator.check_schema(contract)
        _schemas[name] = contract
        # Advertise native arguments and accept the previous nested wire shape.
        compatible = {"type": "object", "anyOf": [contract, {
            "type": "object", "properties": {"arguments": contract},
            "required": ["arguments"], "additionalProperties": False}]}
        tools.append(types.Tool(name=name, description=schema.get("description", ""),
                                inputSchema=compatible))
    return types.ListToolsResult(tools=tools)


async def call_tool(context, params):
    arguments = params.arguments or {}
    if set(arguments) == {"arguments"} and isinstance(arguments["arguments"], dict):
        arguments = arguments["arguments"]
    if params.name not in TOOLS:
        payload = {"error": f"unknown tool: {params.name}"}
    else:
        contract = _schemas.get(params.name)
        error = next(Draft202012Validator(contract).iter_errors(arguments), None) if contract else None
        if error:
            payload = {"error": f"invalid arguments: {error.message}", "tool": params.name}
        else:
            payload = await _gateway.call(params.name, arguments)
    return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(payload))],
                                structuredContent=payload, isError=bool(payload.get("error")))


server = Server("hirara-hub", version="0.4.0", on_list_tools=list_tools, on_call_tool=call_tool)


async def run_stdio():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main():
    parser = argparse.ArgumentParser(description="Hirara hub MCP server")
    parser.add_argument("--transport", default="stdio", choices=["stdio", "sse", "streamable-http"])
    args = parser.parse_args()
    if args.transport != "stdio":
        parser.error("network MCP is disabled: use stdio or the authenticated HTTP hub")
    print(banner.render("hub | MCP stdio"), file=sys.stderr, flush=True)
    asyncio.run(run_stdio())


if __name__ == "__main__":
    main()
