"""Real Rust connector HTTP service behind the Hirara MCP stdio hub."""
import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("HIRARA_CONNECTOR_INTEGRATION") != "1", reason="connector integration opt-in"
)


@pytest.mark.asyncio
async def test_rust_connector_through_hub_mcp(tmp_path):
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    root = Path(__file__).resolve().parents[1]
    binary = root / "hirara-connectors/target/debug/hirara-connectors"
    subprocess.run([str(binary), "init", str(tmp_path / "secrets")], check=True, capture_output=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    token = (tmp_path / "secrets/hub-token").read_text()
    env = dict(os.environ, HCONNECT_CLIENTS_FILE=str(tmp_path / "secrets/clients.json"),
               HCONNECT_ADMIN_TOKEN_FILE=str(tmp_path / "secrets/admin-token"),
               HCONNECT_KEY_FILE=str(tmp_path / "secrets/vault-key"),
               HCONNECT_STORE_DIR=str(tmp_path / "vault"), HCONNECT_BIND=f"127.0.0.1:{port}",
               HCONNECT_PUBLIC_URL=f"http://127.0.0.1:{port}", HCONNECT_TRUST_PROXY="true",
               HIRARA_CONNECTOR_TOKEN=token, HUB_HIRARACONNECTORS_URL=f"http://127.0.0.1:{port}",
               HIRARA_ALLOWED_TOOLS="connector_status,connector_call,connector_connect",
               NO_PROXY="127.0.0.1,localhost", HUB_PROBE_TIMEOUT="0.2")
    process = subprocess.Popen([str(binary)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        async with httpx.AsyncClient(trust_env=False) as client:
            for _ in range(100):
                assert process.poll() is None, "connector exited during startup"
                try:
                    response = await client.get(f"http://127.0.0.1:{port}/health")
                    if response.status_code == 200:
                        break
                except httpx.ConnectError:
                    pass
                await asyncio.sleep(.05)
            else:
                pytest.fail("connector did not become healthy")
        params = StdioServerParameters(command=sys.executable, args=["-m", "hirara_hub.mcp_server"], env=env)
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            initialized = await session.initialize()
            assert "provided through Hirara" in initialized.instructions
            listed = await session.list_tools()
            assert {t.name for t in listed.tools} == {"connector_status", "connector_call", "connector_connect"}
            status = await session.call_tool("connector_status", {})
            assert not status.is_error
            payload = json.loads(status.content[0].text)
            assert payload["connections"] == []
            assert payload["_hirara"]["upstream_verified_by_hirara"] is False
            missing = await session.call_tool("connector_call", {"connection_id": "not-owned", "tool_name": "read"})
            assert missing.is_error
            assert json.loads(missing.content[0].text)["error"] == "connection not found"
            private = await session.call_tool("connector_connect", {"endpoint": "https://127.0.0.1/mcp"})
            assert private.is_error
            assert "private destination denied" in json.loads(private.content[0].text)["error"]
    finally:
        process.terminate()
        process.wait(timeout=5)
        process.stderr.close()
