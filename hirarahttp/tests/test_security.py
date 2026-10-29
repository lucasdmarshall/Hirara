import socket
import httpx
import pytest
from hirarahttp.request import http_request
from hirarahttp.config import HttpConfig
from hirarahttp.history import HistoryStore
from hirarahttp.replay import request_replay


def resolver(host, port, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', port))]


@pytest.mark.asyncio
async def test_cross_origin_redirect_drops_all_unscoped_credentials():
    seen = []
    def handler(req):
        seen.append(req)
        if len(seen) == 1:
            return httpx.Response(302, headers={'Location': 'https://second.invalid/'})
        return httpx.Response(200, text='ok')
    result = await http_request('https://first.invalid/',
                                headers={'Authorization': 'Bearer synthetic',
                                         'Cookie': 'demo=synthetic', 'X-Api-Key': 'synthetic'},
                                resolver=resolver, transport=httpx.MockTransport(handler))
    assert result.error is None
    assert 'authorization' in seen[0].headers
    for key in ('authorization', 'cookie', 'x-api-key'):
        assert key not in seen[1].headers


@pytest.mark.asyncio
async def test_https_downgrade_does_not_send_second_request():
    seen = []
    def handler(req):
        seen.append(req)
        return httpx.Response(302, headers={'Location': 'http://first.invalid/'})
    result = await http_request('https://first.invalid/', resolver=resolver,
                                transport=httpx.MockTransport(handler))
    assert 'downgrade' in result.error
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_replay_promotes_nested_failure():
    history = HistoryStore(max_entries=10, max_body_chars=100)
    seed = history.record({'url': 'http://127.0.0.1/', 'method': 'GET'})
    result = await request_replay(id=seed.id, history=history, config=HttpConfig())
    assert result.error and result.response['error'] == result.error
