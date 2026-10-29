"""Fulfill browser HTTP requests through a pinned transport.

The browser context is offline: Chromium never connects to a URL itself.
Redirects are returned to Chromium, whose next request enters this handler
again. Service workers and WebSockets are disabled by the engine.
"""
from __future__ import annotations

import asyncio
import httpx

from hirara_core import resolve_target


class BrowserEgress:
    def __init__(self, *, allow_private: bool, timeout: float, max_bytes: int = 5_242_880,
                 transport=None, resolver=None):
        self.allow_private = allow_private
        self.max_bytes = max_bytes
        self.resolver = resolver
        self.timeout = timeout
        self.slots = asyncio.Semaphore(8)
        # Environment proxies would move destination resolution outside this
        # boundary. Use only the vetted literal address and original TLS SNI.
        self.client = httpx.AsyncClient(timeout=timeout, follow_redirects=False,
                                        trust_env=False, transport=transport)

    async def handle(self, route):
        try:
            async with self.slots, asyncio.timeout(self.timeout):
                request = route.request
                kwargs = {"allow_private_ips": self.allow_private}
                if self.resolver is not None:
                    kwargs["resolver"] = self.resolver
                target = await asyncio.to_thread(resolve_target, request.url, **kwargs)
                headers = await request.all_headers()
                headers = {k: v for k, v in headers.items()
                           if k.lower() not in {"host", "content-length", "connection",
                                                "transfer-encoding", "proxy-authorization",
                                                "proxy-connection", "upgrade"}}
                headers["Host"] = target.host_header
                body = request.post_data_buffer
                if body is not None and len(body) > self.max_bytes:
                    raise ValueError("browser request body exceeds limit")
                pinned = httpx.URL(request.url).copy_with(host=target.ip)
                req = self.client.build_request(request.method, pinned, headers=headers,
                                                content=body,
                                                extensions={"sni_hostname": target.host})
                response = await self.client.send(req, stream=True)
                try:
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(data) + len(chunk) > self.max_bytes:
                            raise ValueError("browser response exceeds limit")
                        data.extend(chunk)
                    headers = {k: v for k, v in response.headers.items()
                               if k not in {"content-length", "content-encoding",
                                            "transfer-encoding", "connection"}}
                    await route.fulfill(status=response.status_code, headers=headers,
                                        body=bytes(data))
                finally:
                    await response.aclose()
        except Exception:
            # Never continue an unhandled request into Chromium's network stack.
            await route.abort("blockedbyclient")

    async def close(self):
        await self.client.aclose()
