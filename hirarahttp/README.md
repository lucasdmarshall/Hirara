<div align="center">

# Hirarahttp

**Self-hosted HTTP tools for AI agents — raw requests via the SSRF perimeter.**

Part of [Hirara](https://github.com/lucasdmarshall/Hirara). Every URL (and every
redirect hop) goes through [`hirara-core`](../hirara-core/) resolve-then-pin.

</div>

---

## Tools

| Tool | Status | What it does |
|---|---|---|
| **`http_request`** | ✅ shipped | Send method/headers/body → status, headers, body |
| **`http_history`** | ✅ shipped | List / fetch recent requests from this process |
| **`inspect_headers`** | ✅ shipped | Structured view of request/response headers |
| **`inspect_cookies`** | ✅ shipped | Parse Cookie / Set-Cookie (flags, path, domain) |
| **`inspect_response`** | ✅ shipped | Status class, body kind, JSON keys, HTML title |
| **`directory_enum`** | ✅ shipped | Probe a base URL for existing paths |
| `request_replay` / `parameter_test` / `response_compare` | 📋 planned | Replay and compare |

---

## Quick start

```bash
pip install -e ../hirara-core
pip install -e ".[service,mcp]"
```

```bash
uvicorn hirarahttp.service:app --host 127.0.0.1 --port 8800
```

```bash
curl -X POST localhost:8800/http_request -H 'content-type: application/json' \
  -d '{"url":"https://example.com/","method":"GET"}'
```

```json
{
  "method": "GET",
  "url": "https://example.com/",
  "final_url": "https://example.com/",
  "status": 200,
  "reason": "OK",
  "request_headers": { "Host": "example.com", "…": "…" },
  "response_headers": { "content-type": "text/html; …", "…": "…" },
  "body": "<!doctype html>…",
  "body_encoding": "utf-8",
  "truncated": false,
  "bytes_downloaded": 1256,
  "elapsed_ms": 84,
  "redirects": [],
  "error": null
}
```

POST with a body:

```bash
curl -X POST localhost:8800/http_request -H 'content-type: application/json' \
  -d '{"url":"https://httpbin.org/post","method":"POST","headers":{"Content-Type":"application/json"},"body":"{\"hello\":\"hirara\"}"}'
```

**History** of recent calls (newest first; pass `"id"` for one full entry):

```bash
curl -X POST localhost:8800/http_history -H 'content-type: application/json' \
  -d '{"limit":10}'
```

**Inspect headers** from a `request_id` (or pass raw `"headers"`):

```bash
curl -X POST localhost:8800/inspect_headers -H 'content-type: application/json' \
  -d '{"id":"<request_id>","which":"both"}'
```

**Inspect cookies** (Cookie / Set-Cookie):

```bash
curl -X POST localhost:8800/inspect_cookies -H 'content-type: application/json' \
  -d '{"id":"<request_id>","which":"response"}'
```

**Inspect response** (status class, body kind, JSON keys / HTML title):

```bash
curl -X POST localhost:8800/inspect_response -H 'content-type: application/json' \
  -d '{"id":"<request_id>"}'
```

**Directory enum** (omit `paths` for the default list):

```bash
curl -X POST localhost:8800/directory_enum -H 'content-type: application/json' \
  -d '{"url":"https://example.com/","paths":["robots.txt","admin","api"]}'
```

MCP:

```bash
python -m hirarahttp.mcp_server
```

Docker (loopback):

```bash
docker compose up -d --build
```

---

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `CHTTP_TIMEOUT` | `30` | Request timeout (seconds) |
| `CHTTP_MAX_BYTES` | `2000000` | Cap on response body bytes |
| `CHTTP_MAX_REDIRECTS` | `5` | Default redirect hop budget |
| `CHTTP_MAX_REQUEST_BODY_BYTES` | `1000000` | Cap on outbound body |
| `CHTTP_MAX_HEADERS` | `40` | Cap on custom header count |
| `CHTTP_ALLOW_PRIVATE_IPS` | `true` (lib) / `false` (image) | Permit RFC1918 / loopback |
| `CHTTP_HISTORY_SIZE` | `100` | Max recorded `http_request` entries |
| `CHTTP_HISTORY_BODY_CHARS` | `32768` | Cap on body chars kept per entry |
| `CHTTP_ENUM_CONCURRENCY` | `8` | Max concurrent directory_enum probes |
| `CHTTP_ENUM_MAX_PATHS` | `200` | Cap on paths per directory_enum call |
| `CHTTP_ENUM_TIMEOUT` | `10` | Per-path timeout (seconds) |
| `CHTTP_USER_AGENT` | Hirara UA | Default User-Agent |
| `CHTTP_PORT` | `8800` | Compose host port |

---

## Security

- **URL check** via `hirara_core.resolve_target` on the start URL and every redirect hop.
- **IP pin** + real `Host` / SNI (same pattern as `safe_download` / `web_fetch`).
- **Streaming byte cap** after decompression.
- **Loopback bind** in compose. Put auth in front before exposing.
- Allowed destination ports follow hirara-core (`80`, `443`, `8080`, `8443`).

Unlike `web_fetch`, this tool returns raw status/headers/body — including 4xx/5xx —
so agents can inspect HTTP behaviour directly.

---

## Testing

```bash
pip install -e ../hirara-core
pip install -e ".[dev]"
pytest -q
```

Unit tests use `httpx.MockTransport` — no live network required.

---

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
