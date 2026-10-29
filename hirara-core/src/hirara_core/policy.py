"""Small process-wide policy shared by HTTP, MCP and local tool dispatch.

Unset HIRARA_ALLOWED_TOOLS preserves the trusted-operator toolset. An explicitly
empty value denies every tool. Destination policy can only tighten tool config.
"""
from __future__ import annotations

import functools
import inspect
import os


def tool_allowed(name: str) -> bool:
    raw = os.getenv("HIRARA_ALLOWED_TOOLS")
    return raw is None or name in {s.strip() for s in raw.split(",")}


def tool_permission(name: str):
    def decorate(method):
        signature = inspect.signature(method)
        def invalid(args, kwargs):
            try:
                signature.bind(*args, **kwargs)
            except TypeError as exc:
                return {"error": f"{name}: {exc}", "tool": name}
            return None
        def refusal():
            return {"tool": name, "error": f"tool '{name}' disabled by HIRARA_ALLOWED_TOOLS"}
        if inspect.iscoroutinefunction(method):
            @functools.wraps(method)
            async def guarded(*args, **kwargs):
                if not tool_allowed(name):
                    return refusal()
                error = invalid(args, kwargs)
                if error:
                    return error
                return await method(*args, **kwargs)
        else:
            @functools.wraps(method)
            def guarded(*args, **kwargs):
                if not tool_allowed(name):
                    return refusal()
                error = invalid(args, kwargs)
                if error:
                    return error
                return method(*args, **kwargs)
        return guarded
    return decorate


def private_targets_allowed(requested: bool) -> bool:
    """A global denial cannot be relaxed by a package-specific override."""
    raw = os.getenv("HIRARA_ALLOW_PRIVATE_IPS")
    return requested and (raw is None or raw.lower().strip() in {"1", "true", "yes", "on"})


def visible_schemas(method):
    @functools.wraps(method)
    def filtered(*args, **kwargs):
        return [s for s in method(*args, **kwargs) if tool_allowed(s["name"])]
    return filtered


class BackendAuth:
    """Optional service-to-service bearer token; health stays public."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        import hmac
        token = os.getenv("HIRARA_BACKEND_TOKEN", "").strip()
        path = scope.get("path", "")
        # Human endpoints have their own HG_HUMAN_TOKEN authorization.
        human = path == "/human" or path.startswith("/human/")
        if scope["type"] == "http" and token and path != "/health" and not human:
            headers = dict(scope.get("headers", []))
            expected = f"Bearer {token}".encode()
            if not hmac.compare_digest(headers.get(b"authorization", b""), expected):
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"application/json"),
                                        (b"www-authenticate", b"Bearer")]})
                await send({"type": "http.response.body",
                            "body": b'{"error":"missing or invalid backend token"}'})
                return
        await self.app(scope, receive, send)


def install_backend(app):
    app.add_middleware(BackendAuth)
    install_validation_errors(app)


def install_validation_errors(app):
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse
    async def validation_error(request, exc):
        return JSONResponse({"error": "invalid tool arguments", "details": [
            {"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]}, status_code=422)
    app.add_exception_handler(RequestValidationError, validation_error)


def mcp_errors(method):
    """Preserve JSON envelopes while marking execution failures for MCP."""
    @functools.wraps(method)
    async def guarded(*args, **kwargs):
        import json
        from mcp import types
        result = await method(*args, **kwargs)
        if isinstance(result, dict) and result.get("error"):
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=json.dumps(result))],
                structuredContent=result, isError=True)
        return result
    return guarded
