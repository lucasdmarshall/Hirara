"""Automatic setup, authenticated Hub discovery, browser approval and restart."""
import asyncio
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys

import httpx
import pytest

pytestmark = pytest.mark.skipif(os.getenv('HIRARA_CONNECTOR_INTEGRATION') != '1', reason='connector integration opt-in')


@pytest.mark.asyncio
async def test_automatic_local_browser_onboarding_and_restart(tmp_path, monkeypatch):
    from hirara import Client
    from hirara_core.local_connectors import hub_proof
    binary = Path(__file__).resolve().parents[1] / 'hirara-connectors/target/debug/hirara-connectors'
    for name in ('HIRARA_CONNECTOR_TOKEN', 'HIRARA_CONNECTOR_TOKEN_FILE', 'HUB_HIRARACONNECTORS_URL', 'HUB_TOKEN', 'HIRARA_HUB_TOKEN'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('HIRARA_CONNECTOR_LOCAL_DIR', str(tmp_path))
    env = dict(os.environ, NO_PROXY='127.0.0.1,localhost')
    process = hub_process = None
    def start():
        return subprocess.Popen([str(binary), 'local', '--data-dir', str(tmp_path), '--no-browser', '--trust-proxy'], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    async def ready():
        async with httpx.AsyncClient(trust_env=False) as client:
            for _ in range(150):
                assert process.poll() is None, 'local service exited'
                try:
                    data = json.loads((tmp_path / 'local.json').read_text())
                    if (await client.get(data['url'] + '/health')).status_code == 200:
                        return data
                except (OSError, ValueError, httpx.HTTPError):
                    pass
                await asyncio.sleep(.05)
        pytest.fail('local service did not become ready')
    try:
        process = start()
        data = await ready()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
        hub_url = f'http://127.0.0.1:{port}'
        hub_process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'hirara_hub.service:app', '--host', '127.0.0.1', '--port', str(port)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        async with httpx.AsyncClient(base_url=hub_url, trust_env=False) as http:
            for _ in range(150):
                assert hub_process.poll() is None, 'hub exited'
                try:
                    proof = await http.post('/connectors/local-proof', json={'challenge': 'a' * 48})
                    if proof.status_code == 200: break
                except httpx.ConnectError: pass
                await asyncio.sleep(.05)
            else: pytest.fail('hub did not become ready')
            assert (await http.post('/call', json={'name': 'connector_status', 'arguments': {}})).status_code == 401
            forged_host = await http.post('/connectors/local-proof', json={'challenge': 'a' * 48}, headers={'Host': '127.0.0.1:9'})
            assert forged_host.json()['proof'] == hub_proof(data['token'], port, 'a' * 48)
        sdk = Client(hub_url, local=False)
        assert sdk.connector_status()['connections'] == []
        proposal = sdk.connector_connect(endpoint='https://1.1.1.1/mcp')
        async with httpx.AsyncClient(base_url=data['url'], trust_env=False) as http:
            ticket_url = re.search(r'content="0;url=([^"]+)"', (tmp_path / 'browser-launch.html').read_text())[1]
            ticket = ticket_url.split('#', 1)[1]
            assert (await http.post('/local/session', json={'ticket': ticket}, headers={'Origin': 'https://evil.test'})).status_code == 401
            login = await http.post('/local/session', json={'ticket': ticket}, headers={'Origin': data['url']})
            browser_token = login.json()['token']
            assert browser_token != data['token']
            assert (await http.post('/local/session', json={'ticket': ticket}, headers={'Origin': data['url']})).status_code == 401
            page = await http.get(proposal['approval_url'])
            assert 'name=admin' not in page.text
            assert "script-src 'nonce-" in page.headers['content-security-policy']
            form = {'mode': 'none', 'tools': 'read'}
            assert (await http.post(proposal['approval_url'], data=form, headers={'Authorization': 'Bearer ' + data['token'], 'Origin': data['url']})).status_code == 401
            assert (await http.post(proposal['approval_url'], data=form, headers={'Authorization': 'Bearer ' + browser_token, 'Origin': 'https://evil.test'})).status_code == 401
            assert (await http.post(proposal['approval_url'], data=form, headers={'Authorization': 'Bearer ' + browser_token, 'Origin': data['url']})).status_code == 200
        assert len(sdk.connector_status()['connections']) == 1
        key = (tmp_path / 'secrets/vault-key').read_bytes()
        process.send_signal(signal.SIGINT); process.wait(timeout=5); process.stderr.close()
        process = start(); updated = await ready()
        assert updated['token'] != data['token']
        assert (tmp_path / 'secrets/vault-key').read_bytes() == key
        assert len(sdk.connector_status()['connections']) == 1
        async with httpx.AsyncClient(trust_env=False) as http:
            assert (await http.post(updated['url'] + '/connector_status', json={}, headers={'Authorization': 'Bearer ' + data['token']})).status_code == 401
    finally:
        for child in (hub_process, process):
            if child:
                if child.poll() is None: child.terminate()
                child.wait(timeout=5)
                child.stderr.close()
