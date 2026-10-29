import pytest
from hirara_core.policy import BackendAuth, private_targets_allowed, tool_allowed, tool_permission


def test_allowlist_is_shared_and_empty_denies_all(monkeypatch):
    monkeypatch.delenv('HIRARA_ALLOWED_TOOLS', raising=False)
    assert tool_allowed('execute_code')
    monkeypatch.setenv('HIRARA_ALLOWED_TOOLS', 'web_fetch, pdf_read')
    assert tool_allowed('pdf_read')
    assert not tool_allowed('http_request')
    monkeypatch.setenv('HIRARA_ALLOWED_TOOLS', '')
    assert not tool_allowed('web_fetch')


@pytest.mark.asyncio
async def test_permission_denies_before_any_tool_side_effect(monkeypatch):
    calls = []
    @tool_permission('demo')
    async def demo(value):
        calls.append(value)
        return {'error': None}
    monkeypatch.setenv('HIRARA_ALLOWED_TOOLS', '')
    assert (await demo(1))['error']
    assert calls == []
    monkeypatch.delenv('HIRARA_ALLOWED_TOOLS')
    assert (await demo())['error']
    assert (await demo(1))['error'] is None


def test_global_network_policy_cannot_be_relaxed(monkeypatch):
    monkeypatch.setenv('HIRARA_ALLOW_PRIVATE_IPS', 'false')
    assert not private_targets_allowed(True)
    monkeypatch.setenv('HIRARA_ALLOW_PRIVATE_IPS', 'true')
    assert not private_targets_allowed(False)
    assert private_targets_allowed(True)


@pytest.mark.asyncio
async def test_backend_auth_rejects_without_dispatch(monkeypatch):
    calls, messages = [], []
    async def app(scope, receive, send):
        calls.append(scope['path'])
    monkeypatch.setenv('HIRARA_BACKEND_TOKEN', 'synthetic-token')
    middleware = BackendAuth(app)
    await middleware({'type': 'http', 'path': '/execute_code', 'headers': []}, None, _sender(messages))
    assert messages[0]['status'] == 401
    assert calls == []
    await middleware({'type': 'http', 'path': '/health', 'headers': []}, None, _sender(messages))
    await middleware({'type': 'http', 'path': '/execute_code', 'headers': [(b'authorization', b'Bearer synthetic-token')]}, None, _sender(messages))
    assert calls == ['/health', '/execute_code']


def _sender(messages):
    async def send(message):
        messages.append(message)
    return send
