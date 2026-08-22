<div align="center">

# Hirarabrowser

**Self-hosted browser tools for AI agents — open pages via Playwright.**

Part of [Hirara](https://github.com/lucasdmarshall/Hirara). Headless Chromium by
default. URLs are checked with [`hirara-core`](../hirara-core/) before navigate.

</div>

---

## Tools

| Tool | Status | What it does |
|---|---|---|
| **`browser_open`** | ✅ shipped | Open URL → `session_id`, title, final URL |
| **`browser_click`** | ✅ shipped | Click a selector in a session |
| **`browser_type`** | ✅ shipped | Type into an input (fill or append) |
| `browser_screenshot` | 📋 planned | Capture a page screenshot |

---

## Quick start

```bash
pip install -e ../hirara-core
pip install -e ".[service,mcp]"
playwright install chromium
```

```bash
uvicorn hirarabrowser.service:app --host 127.0.0.1 --port 8700
```

```bash
curl -X POST localhost:8700/browser_open -H 'content-type: application/json' \
  -d '{"url":"https://example.com/","include_text":true}'
```

```json
{
  "session_id": "…",
  "url": "https://example.com/",
  "title": "Example Domain",
  "status": 200,
  "text": "Example Domain\n…",
  "truncated": false,
  "error": null
}
```

Reuse a session (navigate the same browser):

```bash
curl -X POST localhost:8700/browser_open -H 'content-type: application/json' \
  -d '{"url":"https://example.org/","session_id":"<id>"}'
```

**Click** in that session:

```bash
curl -X POST localhost:8700/browser_click -H 'content-type: application/json' \
  -d '{"session_id":"<id>","selector":"a#more-information"}'
```

**Type** into an input:

```bash
curl -X POST localhost:8700/browser_type -H 'content-type: application/json' \
  -d '{"session_id":"<id>","selector":"input[name=q]","text":"hirara","press_enter":true}'
```

MCP:

```bash
python -m hirarabrowser.mcp_server
```

Docker (loopback):

```bash
docker compose up -d --build
```

---

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `CBRO_HEADLESS` | `true` | Headless Chromium |
| `CBRO_NAV_TIMEOUT` | `30` | Navigation timeout (seconds) |
| `CBRO_MAX_SESSIONS` | `8` | Concurrent sessions |
| `CBRO_SESSION_TTL` | `600` | Idle session TTL (seconds) |
| `CBRO_MAX_TEXT_CHARS` | `50000` | Cap on `include_text` body |
| `CBRO_ALLOW_PRIVATE_URLS` | `true` (lib) / `false` (image) | Permit RFC1918 / loopback |
| `CBRO_BROWSER` | `chromium` | `chromium` / `firefox` / `webkit` |
| `CBRO_PORT` | `8700` | Compose host port |

---

## Security

- **URL check** via `hirara-core.resolve_target` before navigate.
- **Loopback bind** in compose. Put auth in front before exposing.
- **Session cap + TTL** so abandoned browsers do not pile up.
- Playwright still does its own DNS for the actual navigation — the pre-check
  rejects obviously private/reserved destinations when private URLs are off.

---

## Testing

```bash
pip install -e ../hirara-core
pip install -e ".[dev]"
pytest -q
```

Unit tests use `FakeEngine` — no Chromium download required.

---

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
