<div align="center">

# hirara-hub

**One HTTP + MCP endpoint for the whole [Hirara](https://github.com/lucasdmarshall/Hirara) toolset.**

A thin aggregating gateway: it fronts every tool service, presents one
aggregated `/schemas`, forwards calls to the right backend, and adds opt-in
auth — without importing any tool's dependencies. Each tool stays isolated in
its own container.

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/MCP-compatible-8A2BE2.svg)](https://modelcontextprotocol.io/)

</div>

---

## Why a gateway (and not a monolith)

Putting every tool in one process would mean one giant image carrying PaddleOCR,
torch, a browser-less OCR stack **and** the Docker socket that `execute_code`
needs — host-root privilege sitting in the same process as everything else. The
gateway keeps each tool in its **own** container and only *routes* to them:

- **Isolation preserved** — `execute_code` uses a separate internal network; its Docker socket
  still grants daemon-level privilege, so use a dedicated execution host; a crash in one tool doesn't take down the rest.
- **No dependency conflicts** — the gateway depends on `httpx` + `fastapi`, full
  stop.
- **Honest availability** — `/schemas` aggregates from **live** backends, so the
  hub never advertises a tool it can't actually route to.

---

## What it exposes

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness + per-backend up/down (unauthenticated) |
| `GET /schemas` | Every reachable tool's definition, as one `tools` array |
| `POST /call` | `{"name": "...", "arguments": {...}}` → forwarded to the backend |

Plus a **federating MCP server** (`python -m hirara_hub.mcp_server`): agents
connect to one MCP endpoint and see every hub tool as a first-class MCP tool.

---

## Auth — opt-in

There is **no forced auth**. With no `HUB_TOKEN` set the gateway runs open,
which is correct for a **loopback / local** deployment (its only intended
default). Set `HUB_TOKEN` and every `/schemas` and `/call` must carry
`Authorization: Bearer <token>` — turn that on the moment you bind it to a
network. Same philosophy as the tools' `allow_url_fetch` / `allow_local_path`:
closed by default, you choose to open it.

`execute_code` is the reason auth matters once exposed: an open code-runner on a
network is arbitrary RCE for anyone who finds it.

---

## Run the whole hub

One command, from the repo root:

```bash
docker compose -f docker-compose.hub.yml up -d --build
```

Every tool comes up in its own container on a private network; only the gateway
publishes a port (loopback `8080`). Then:

```bash
curl localhost:8080/health
curl localhost:8080/schemas
curl -X POST localhost:8080/call -H 'content-type: application/json' \
  -d '{"name":"office_read","arguments":{"file_base64":"<...>"}}'
```

To require auth, set a token first:

```bash
HUB_TOKEN=$(openssl rand -hex 32) docker compose -f docker-compose.hub.yml up -d
```

### Just the gateway (backends elsewhere)

```bash
pip install -e ".[mcp]"
uvicorn hirara_hub.service:app --host 127.0.0.1 --port 8080
```

Point it at your backends with `HUB_<SERVICE>_URL` env vars (defaults are
`http://localhost:<port>`).

---

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `HUB_TOKEN` | _(unset)_ | Bearer token; unset = no auth (loopback only) |
| `HUB_TIMEOUT` | `120` | Per-call forward timeout (seconds) |
| `HUB_PROBE_TIMEOUT` | `5` | `/health` and `/schemas` probe timeout |
| `HUB_<SERVICE>_URL` | `http://localhost:<port>` | Backend base URL, e.g. `HUB_HIRARAOCR_URL` |

---

## Testing

```bash
pip install -e ".[dev]"
pytest -q
```

The suite drives the gateway against **mock backends** (httpx `MockTransport`):
schema aggregation skipping down services, call forwarding to the right backend,
unknown-tool and unreachable-backend error bodies, and the opt-in auth
dependency. Verified live: the gateway aggregated schemas from two real backends
and forwarded `office_read` and `pdf_create` end-to-end.

---

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).

Copyright 2026 Lucas D Marshall (Kaung Myat San).

## Security and compatibility

See [the deployment and migration guide](../SECURITY.md). Network MCP transports
are disabled; use stdio or authenticated HTTP. Set `HIRARA_BACKEND_TOKEN` on
the hub and backends to protect service-to-service calls. `HIRARA_ALLOWED_TOOLS`
restricts both discovery and execution. Probes share an overall deadline,
and `/ready` reports whether at least one backend is healthy.


## External MCP connectors

Hirara can discover MCP servers, connect with human approval, retain encrypted credentials, and call permitted upstream tools through a Rust service. See [connector setup, attribution and security boundaries](../docs/connectors.md).
