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
| `http_history` | 📋 planned | List recent requests from this process |
| `inspect_headers` / `inspect_cookies` / `inspect_response` | 📋 planned | Structured views of a response |
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
