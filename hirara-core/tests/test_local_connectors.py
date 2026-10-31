import json
import os

import httpx
import pytest

from hirara_core.local_connectors import discover, hub_proof, verify_hub


def local_file(tmp_path, monkeypatch):
    monkeypatch.setenv('HIRARA_CONNECTOR_LOCAL_DIR', str(tmp_path))
    tmp_path.chmod(0o700)
    path = tmp_path / 'local.json'
    path.write_text(json.dumps({'version': 1, 'url': 'http://127.0.0.1:9701', 'token': 'a' * 48}))
    path.chmod(0o600)
    return path


def test_discovery_rejects_untrusted_paths_addresses_and_permissions(tmp_path, monkeypatch):
    path = local_file(tmp_path, monkeypatch)
    assert discover().url == 'http://127.0.0.1:9701'
    for url in ['https://evil.test', 'http://localhost:9701', 'http://127.0.0.1:9701/other',
                'http://user:pass@127.0.0.1:9701', 'http://127.0.0.1:9701?secret=1', 42, None]:
        path.write_text(json.dumps({'version': 1, 'url': url, 'token': 'a' * 48}))
        assert discover() is None
    local_file(tmp_path, monkeypatch)
    if os.name != 'nt':
        path.chmod(0o644)
        assert discover() is None
    path.unlink()
    target = tmp_path / 'target'
    target.write_text('{}')
    path.symlink_to(target)
    assert discover() is None


def test_sdk_verifies_actual_hub_identity_before_sending_credentials(tmp_path, monkeypatch):
    local_file(tmp_path, monkeypatch)
    local = discover()
    def good(request):
        assert not request.headers.get('authorization')
        assert request.url.path == '/connectors/local-proof'
        challenge = json.loads(request.content)['challenge']
        return httpx.Response(200, json={'proof': hub_proof(local.token, 8080, challenge)})
    with httpx.Client(base_url='http://localhost:8080', transport=httpx.MockTransport(good)) as client:
        verify_hub(client, local, 'http://localhost:8080')
    def bad(request):
        assert not request.headers.get('authorization')
        return httpx.Response(200, json={'proof': 'forged'})
    with httpx.Client(base_url='http://localhost:8080', transport=httpx.MockTransport(bad)) as client:
        with pytest.raises(httpx.TransportError, match='identity verification failed'):
            verify_hub(client, local, 'http://localhost:8080')
