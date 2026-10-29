"""Real Chromium, with a mock upstream transport and no external requests."""
import os
import shutil
import httpx
import pytest
from hirarabrowser.browser import PlaywrightEngine, browser_open, browser_click
from hirarabrowser.config import BrowserConfig
from hirarabrowser.session import SessionStore
import hirarabrowser.egress as egress

pytestmark = pytest.mark.skipif(os.getenv('HIRARA_INTEGRATION') != '1', reason='integration opt-in')


@pytest.mark.asyncio
async def test_real_chromium_routes_every_navigation_and_subresource(monkeypatch):
    seen = []
    def handler(request):
        seen.append(str(request.url))
        if request.url.path == '/redirect':
            return httpx.Response(302, headers={'location': 'http://127.0.0.1/private'})
        return httpx.Response(200, headers={'content-type': 'text/html'}, text='''
            <html><body><h1>safe-marker</h1>
            <iframe src="http://127.0.0.1/private"></iframe>
            <img src="http://169.254.169.254/metadata">
            <a id="private" href="http://127.0.0.1/private">private</a>
            <script>new WebSocket('ws://127.0.0.1/socket')</script>
            </body></html>''')
    original = egress.BrowserEgress
    monkeypatch.setattr(egress, 'BrowserEgress', lambda **kw: original(**kw, transport=httpx.MockTransport(handler)))
    cfg = BrowserConfig(executable_path=os.getenv('CBRO_EXECUTABLE_PATH') or shutil.which('chromium'))
    engine = PlaywrightEngine(cfg)
    store = SessionStore(max_sessions=1, session_ttl=60)
    try:
        result = await browser_open('http://93.184.216.34/', include_text=True,
                                    config=cfg, engine=engine, store=store)
        assert result.error is None, result.error
        assert 'safe-marker' in result.text
        assert all('93.184.216.34' in url for url in seen)
        await browser_click(result.session_id, '#private', config=cfg, store=store)
        assert all('93.184.216.34' in url for url in seen)
        result = await browser_open('http://93.184.216.34/redirect',
                                    config=cfg, engine=engine, store=store)
        assert result.error
        assert not any('127.0.0.1' in url or '169.254' in url for url in seen)
    finally:
        await store.close()
        await engine.close()
