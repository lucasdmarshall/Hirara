"""Verify initialization and tool errors through actual stdio framing."""
import os
import sys
import pytest

pytestmark = pytest.mark.skipif(os.getenv('HIRARA_INTEGRATION') != '1', reason='integration opt-in')


@pytest.mark.asyncio
async def test_stdio_protocol_is_not_corrupted_by_banner():
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
    params = StdioServerParameters(command=sys.executable, args=['-m', 'hirara_hub.mcp_server'],
                                   env=dict(os.environ, HUB_PROBE_TIMEOUT='0.1'))
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        initialized = await session.initialize()
        assert initialized.server_info.name == 'hirara-hub'
        result = await session.call_tool('unknown_audit_tool', {})
        assert result.is_error
