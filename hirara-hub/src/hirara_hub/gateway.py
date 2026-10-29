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

log = logging.getLogger(__name__)


class Gateway:
    def __init__(self, config: HubConfig, client: httpx.AsyncClient | None = None) -> None:
        self.config = config
        self._client = client  # injected in tests; else made per-call

    def _aclient(self, timeout: float) -> tuple[httpx.AsyncClient, bool]:
        """Return (client, should_close)."""
        if self._client is not None:
            return self._client, False
        return httpx.AsyncClient(timeout=timeout), True

    def _url(self, service: str, path: str) -> str:
        base = self.config.service_urls.get(service, f"http://{service}")
        return f"{base}{path}"

    def _headers(self):
        import os
        token = os.getenv("HIRARA_BACKEND_TOKEN", "").strip()
        return {"Authorization": f"Bearer {token}"} if token else {}

    async def _probe(self, path):
        client, close = self._aclient(self.config.probe_timeout)
        slots = asyncio.Semaphore(4)
        async def one(service):
            async def request():
                async with slots:
                    resp = await client.get(self._url(service, path), headers=self._headers(),
                                            timeout=self.config.probe_timeout)
                    resp.raise_for_status()
                    return resp.json() if resp.content else {}
            try:
                return service, await asyncio.wait_for(request(), self.config.probe_timeout)
            except Exception:
                return service, None
        try:
            return await asyncio.gather(*(one(service) for service in services()))
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
                "version": "0.2.0", "auth": "enabled" if self.config.auth_enabled else "disabled",
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
        url = self._url(route.service, route.path)
        client, close = self._aclient(self.config.timeout)
        try:
            resp = await client.post(url, json=arguments or {}, headers=self._headers(), timeout=self.config.timeout)
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
