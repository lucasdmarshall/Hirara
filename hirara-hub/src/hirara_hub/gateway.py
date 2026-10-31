"""The aggregating gateway: fan out to backends, present one surface.

Holds no tool dependencies — it only speaks HTTP to the backend services. The
httpx client is injectable so the tests can drive it against mock backends.
"""

from __future__ import annotations

import logging
import asyncio

from hirara_core.policy import tool_allowed

import httpx

from .config import HubConfig
from .registry import TOOLS, services
from hirara_core.local_connectors import discover, verify

log = logging.getLogger(__name__)


class Gateway:
    def __init__(self, config: HubConfig, client: httpx.AsyncClient | None = None) -> None:
        self.config = config
        self._client = client  # injected in tests; else made per-call

    def _aclient(self, timeout: float, *, local: bool = False) -> tuple[httpx.AsyncClient, bool]:
        """Return (client, should_close)."""
        if self._client is not None:
            return self._client, False
        return httpx.AsyncClient(timeout=timeout, trust_env=not local), True

    def _local_connector(self):
        import os
        if any(os.getenv(k) for k in ("HIRARA_CONNECTOR_TOKEN", "HIRARA_CONNECTOR_TOKEN_FILE", "HUB_HIRARACONNECTORS_URL")):
            return None
        configured = self.config.service_urls.get("hiraraconnectors")
        if configured and configured not in {"http://localhost:9700", "http://127.0.0.1:9700"}:
            return None
        return discover()

    def _target(self, service, path):
        local = self._local_connector() if service == "hiraraconnectors" else None
        if local:
            return local.url + path, {"Authorization": f"Bearer {local.token}"}, local
        return self._url(service, path), self._headers(service), None

    def _url(self, service: str, path: str) -> str:
        base = self.config.service_urls.get(service, f"http://{service}")
        return f"{base}{path}"

    def _headers(self, service: str | None = None):
        import os
        token = os.getenv("HIRARA_CONNECTOR_TOKEN" if service == "hiraraconnectors" else "HIRARA_BACKEND_TOKEN", "").strip()
        if service == "hiraraconnectors" and not token:
            path = os.getenv("HIRARA_CONNECTOR_TOKEN_FILE", "").strip()
            if path:
                try:
                    from pathlib import Path
                    token = Path(path).read_text().strip()
                except (OSError, UnicodeError):
                    return {}
        if service == "hiraraconnectors" and not token:
            local = self._local_connector()
            token = local.token if local else ""
        if service == "hiraraconnectors" and (not token.isascii() or any(c.isspace() for c in token)):
            return {}
        return {"Authorization": f"Bearer {token}"} if token else {}

    async def _probe(self, path):
        client, close = self._aclient(self.config.probe_timeout)
        slots = asyncio.Semaphore(4)
        async def one(service):
            if service == "hiraraconnectors" and not self._headers(service):
                return service, None
            async def request():
                async with slots:
                    url, headers, local = self._target(service, path)
                    active, own = (self._aclient(self.config.probe_timeout, local=True) if local else (client, False))
                    try:
                        if local:
                            await verify(active, local, self.config.probe_timeout)
                        resp = await active.get(url, headers=headers, timeout=self.config.probe_timeout)
                        resp.raise_for_status()
                        return resp.json() if resp.content else {}
                    finally:
                        if own:
                            await active.aclose()
            try:
                return service, await asyncio.wait_for(request(), self.config.probe_timeout)
            except Exception:
                return service, None
        try:
            return await asyncio.gather(*(one(service) for service in services()
                                         if service != "hiraraconnectors" or self._headers(service)))
        finally:
            if close:
                await client.aclose()

    async def schemas(self) -> dict:
        tools, unavailable = [], []
        for service, payload in await self._probe("/schemas"):
            if not isinstance(payload, dict) or not isinstance(payload.get("tools"), list):
                unavailable.append(service)
                continue
            for schema in payload["tools"]:
                if not isinstance(schema, dict):
                    continue
                name = schema.get("name")
                route = TOOLS.get(name)
                if route and route.service == service and tool_allowed(name):
                    tools.append(schema)
        return {"tools": tools, "unavailable": unavailable}

    async def health(self) -> dict:
        status = {}
        for service, payload in await self._probe("/health"):
            if payload is None:
                status[service] = "down"
            elif isinstance(payload, dict) and payload.get("status", "ok") in {"ok", "healthy"}:
                status[service] = "up"
            else:
                status[service] = "degraded"
        up = sum(value == "up" for value in status.values())
        return {"status": "ok" if up == len(status) else "degraded",
                "version": "0.6.0", "auth": "enabled" if self.config.auth_enabled else "disabled",
                "services": status, "services_up": up, "services_total": len(status),
                "ready": up > 0}

    async def call(self, name: str, arguments: dict) -> dict:
        """Forward a tool call to its backend and return the backend's JSON.

        A missing tool or an unreachable backend comes back as an error body
        (not an exception), so the caller — an agent loop — gets something to
        reason about, consistent with how every tool behaves.
        """
        if not tool_allowed(name):
            return {"error": f"tool '{name}' disabled by HIRARA_ALLOWED_TOOLS", "tool": name}
        route = TOOLS.get(name)
        if route is None:
            return {"error": f"unknown tool: {name}", "tool": name}
        url, headers, local = self._target(route.service, route.path)
        if route.service == "hiraraconnectors" and not headers:
            return {"error": "connectors are not configured: run hirara-connectors local or set HIRARA_CONNECTOR_TOKEN", "tool": name}
        client, close = self._aclient(self.config.timeout, local=bool(local))
        try:
            if local:
                await verify(client, local, self.config.probe_timeout)
            resp = await client.post(url, json=arguments or {}, headers=headers, timeout=self.config.timeout)
            if resp.status_code >= 500:
                return {
                    "error": f"backend {route.service} error (HTTP {resp.status_code})",
                    "tool": name,
                    "backend_status": resp.status_code,
                }
            if resp.status_code >= 400:
                return {"error": f"backend {route.service} rejected request (HTTP {resp.status_code})",
                        "tool": name, "backend_status": resp.status_code}
            payload = resp.json()
            if not isinstance(payload, dict):
                return {"error": "backend returned a non-object response", "tool": name}
            return payload
        except httpx.HTTPError as exc:
            return {
                "error": f"tool '{name}' unavailable: {route.service} unreachable ({exc})",
                "tool": name,
            }
        except Exception as exc:  # noqa: BLE001
            log.exception("call %s failed", name)
            return {"error": f"gateway call failed: {exc}", "tool": name}
        finally:
            if close:
                await client.aclose()


__all__ = ["Gateway"]
