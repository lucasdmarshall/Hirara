import asyncio
import time
import httpx
import pytest
from hirara_hub.config import HubConfig
from hirara_hub.gateway import Gateway


@pytest.mark.asyncio
async def test_validation_failure_is_an_error_envelope():
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda req: httpx.Response(422, json={'detail': [{'msg': 'required'}]}))) as client:
        result = await Gateway(HubConfig(), client).call('execute_code', {})
    assert result['error'] and result['backend_status'] == 422


@pytest.mark.asyncio
async def test_allowlist_denial_precedes_backend_access(monkeypatch):
    monkeypatch.setenv('HIRARA_ALLOWED_TOOLS', 'pdf_read')
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda req: pytest.fail('denied tool reached backend'))) as client:
        result = await Gateway(HubConfig(), client).call('execute_code', {})
    assert 'disabled' in result['error']


@pytest.mark.asyncio
async def test_probe_deadline_bounds_entire_fanout():
    async def handler(req):
        await asyncio.sleep(1)
        return httpx.Response(200, json={})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        start = time.monotonic()
        result = await Gateway(HubConfig(probe_timeout=0.05), client).health()
    assert time.monotonic() - start < 0.5
    assert not result['ready'] and result['status'] == 'degraded'


@pytest.mark.asyncio
async def test_degraded_backend_is_not_healthy():
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda req: httpx.Response(200, json={'status': 'degraded'}))) as client:
        result = await Gateway(HubConfig(), client).health()
    assert result['services_up'] == 0


@pytest.mark.asyncio
async def test_mcp_uses_native_schemas_and_explicit_error_flag(monkeypatch):
    from mcp import types
    import hirara_hub.mcp_server as mcp
    class Backend:
        async def schemas(self):
            return {'tools': [{'name': 'execute_code', 'description': 'Run code',
                     'input_schema': {'type': 'object', 'properties': {'code': {'type': 'string'}},
                                      'required': ['code'], 'additionalProperties': False}}]}
        async def call(self, name, args):
            return {'error': 'test failure', 'received': args}
    monkeypatch.setattr(mcp, '_gateway', Backend())
    listed = await mcp.list_tools()
    assert listed.tools[0].input_schema['anyOf'][0]['required'] == ['code']
    for args in ({'code': 'pass'}, {'arguments': {'code': 'pass'}}):
        result = await mcp.call_tool(None, types.CallToolRequestParams(name='execute_code', arguments=args))
        assert result.is_error
        assert result.structured_content['received'] == {'code': 'pass'}


@pytest.mark.asyncio
async def test_standalone_mcp_preserves_error_envelope():
    from hirara_core.policy import mcp_errors
    @mcp_errors
    async def failed(): return {'error': 'synthetic refusal'}
    result = await failed()
    assert result.is_error
    assert result.structured_content['error'] == 'synthetic refusal'
