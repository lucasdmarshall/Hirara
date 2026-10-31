"""The hub's HTTP surface — one endpoint for the whole toolset.

    uvicorn hirara_hub.service:app --host 0.0.0.0 --port 8080

- GET  /health   liveness + per-backend up/down
- GET  /schemas  aggregated tool definitions (drop into an LLM `tools` array)
- POST /call     {"name": "...", "arguments": {...}} → forwarded to the backend

Auth is opt-in: set HUB_TOKEN to require `Authorization: Bearer <token>`. With no
token the gateway is open — run it on loopback only.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
import hmac

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel
from hirara_core.policy import install_validation_errors

from . import banner
from .config import HubConfig
from .gateway import Gateway
from .registry import TOOLS
from hirara_core.local_connectors import hub_proof

_config = HubConfig.from_env()
_gateway = Gateway(_config)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Printed once on startup (not on import), so it shows in the logs /
    # `docker compose up` output without spamming the test suite.
    banner.show(f"hub | HTTP :8080 | auth {'on' if _config.auth_enabled else 'off'}")
    yield


app = FastAPI(title="hirara-hub", version="0.6.0", lifespan=lifespan)
install_validation_errors(app)


async def require_auth(authorization: str | None = Header(default=None)) -> None:
    """Enforce the bearer token, but only when one is configured."""
    if not _config.auth_enabled:
        return
    expected = f"Bearer {_config.token}"
    if not hmac.compare_digest((authorization or "").encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="missing or invalid bearer token")


class CallRequest(BaseModel):
    name: str
    arguments: dict = {}


@app.get("/health")
async def health() -> dict:
    # Health is unauthenticated on purpose: a load balancer / uptime check
    # should not need the token, and it reveals only up/down.
    return await _gateway.health()


@app.get("/schemas", dependencies=[Depends(require_auth)])
async def schemas() -> dict:
    return await _gateway.schemas()


@app.get("/ready", dependencies=[Depends(require_auth)])
async def ready():
    from fastapi.responses import JSONResponse
    result = await _gateway.health()
    return JSONResponse(result, status_code=200 if result["ready"] else 503)


@app.post("/call", dependencies=[Depends(require_auth)])
async def call(request: CallRequest, authorization: str | None = Header(default=None)) -> dict:
    route = TOOLS.get(request.name)
    local = _gateway._local_connector() if route and route.service == "hiraraconnectors" else None
    if local and not _config.auth_enabled:
        if not hmac.compare_digest((authorization or "").encode(), f"Bearer {local.token}".encode()):
            raise HTTPException(status_code=401, detail="local connector authentication required; use the Hirara SDK or MCP stdio")
    return await _gateway.call(request.name, request.arguments)


@app.post("/connectors/local-proof")
async def local_connector_proof(body: dict, request: Request):
    local = _gateway._local_connector()
    challenge = body.get("challenge")
    if not local:
        raise HTTPException(status_code=404, detail="local connectors not running")
    if not isinstance(challenge, str) or not 32 <= len(challenge) <= 128 or any(c not in "0123456789abcdef" for c in challenge):
        raise HTTPException(status_code=422, detail="invalid challenge")
    # Bind to the actual listener port, never the caller-controlled Host header.
    address, port = request.scope["server"]
    if address != "127.0.0.1":
        raise HTTPException(status_code=403, detail="local identity proof requires an IPv4 loopback listener")
    from fastapi.responses import JSONResponse
    return JSONResponse({"proof": hub_proof(local.token, port, challenge)}, headers={"Cache-Control": "no-store"})
