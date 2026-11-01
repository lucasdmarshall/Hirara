"""Exercise the Rust forge CLI and real MCP stdio protocol without provider access."""
import json
import os
from pathlib import Path
import subprocess

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("HIRARA_CONNECTOR_INTEGRATION") != "1", reason="connector integration opt-in"
)


@pytest.mark.asyncio
async def test_generated_tools_over_stdio(tmp_path):
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    root = Path(__file__).resolve().parents[1]
    binary = root / "hirara-connectors/target/debug/hirara-connectors"
    package = tmp_path / "inventory.json"
    result = subprocess.run([
        str(binary), "forge", "build", "--spec", str(root / "examples/forge/inventory.openapi.json"),
        "--name", "inventory", "--out", str(package), "--credential-env", "INVENTORY_TOKEN",
    ], check=True, capture_output=True, text=True)
    pin = json.loads(result.stdout)["sha256"]
    fixtures = subprocess.run([
        str(binary), "forge", "test", "--package", str(package),
        "--fixtures", str(root / "examples/forge/cases.json"),
    ], check=True, capture_output=True, text=True)
    assert json.loads(fixtures.stdout)["passed"] == 4
    env = dict(os.environ, HCONNECT_TRUST_PROXY="true", INVENTORY_TOKEN="fixture-secret")
    params = StdioServerParameters(command=str(binary), args=[
        "forge", "mcp", "--package", str(package), "--sha256", pin,
    ], env=env)
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            info = await session.initialize()
            assert "Hirara" in info.instructions
            tools = await session.list_tools()
            assert [t.name for t in tools.tools] == ["inventory__getstock"]
            result = await session.call_tool("inventory__getstock", {"path": {"sku": "../bad"}})
            assert result.is_error
            assert "fixture-secret" not in str(result)
    # Denied tools are hidden as well as blocked at call time.
    params.env = dict(env, HIRARA_ALLOWED_TOOLS="other_tool")
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            assert not (await session.list_tools()).tools
            assert (await session.call_tool("inventory__getstock", {})).is_error
    package.write_text(package.read_text() + "\n")
    rejected = subprocess.run([str(binary), *params.args], capture_output=True, text=True, env=env)
    assert rejected.returncode != 0
    assert "digest changed" in rejected.stderr
