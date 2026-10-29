import socket
import httpx
import pytest
from hirarabrowser.egress import BrowserEgress
from hirarabrowser.session import SessionStore


class Request:
    method = 'GET'
    post_data_buffer = None
    def __init__(self, url): self.url = url
    async def all_headers(self): return {}


class Route:
    def __init__(self, url):
        self.request = Request(url)
        self.result = None
    async def abort(self, reason): self.result = ('blocked', reason)
    async def fulfill(self, **kw): self.result = ('fulfilled', kw)


@pytest.mark.asyncio
async def test_egress_uses_vetted_ip_and_refuses_private_redirect_hop():
    seen = []
    def handler(req):
        seen.append(req)
        return httpx.Response(302, headers={'location': 'http://127.0.0.1/'})
    def resolver(host, port, **kw):
        ip = '127.0.0.1' if host == '127.0.0.1' else '93.184.216.34'
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, port))]
    egress = BrowserEgress(allow_private=False, timeout=2, resolver=resolver,
                           transport=httpx.MockTransport(handler))
    try:
        first = Route('https://public.invalid/')
        await egress.handle(first)
        assert first.result[0] == 'fulfilled'
        assert seen[0].url.host == '93.184.216.34'
        assert seen[0].headers['host'] == 'public.invalid'
        assert seen[0].extensions['sni_hostname'] == 'public.invalid'
        second = Route('http://127.0.0.1/')
        await egress.handle(second)
        assert second.result[0] == 'blocked'
        assert len(seen) == 1
    finally:
        await egress.close()


@pytest.mark.asyncio
async def test_eviction_and_shutdown_await_resource_cleanup():
    closed = []
    class Resource:
        async def close(self): closed.append(True)
    store = SessionStore(max_sessions=1, session_ttl=60)
    store.create(page=Resource())
    store.create(page=Resource())
    await store.drain()
    assert len(closed) == 1
    await store.close()
    assert len(closed) == 2
