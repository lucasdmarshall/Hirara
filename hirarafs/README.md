<div align="center">

# Hirarafs

**Self-hosted filesystem tools for AI agents — read files from allowlisted paths.**

Part of [Hirara](https://github.com/lucasdmarshall/Hirara). Paths are gated by
`CFS_ROOTS`; the Docker image only serves files under `/data`.

</div>

---

## Tools

| Tool | Status | What it does |
|---|---|---|
| **`file_read`** | ✅ shipped | Read a file → text or base64 |
| `file_write` | 📋 planned | Write / create a file |

---

## Quick start

```bash
pip install -e ".[service,mcp]"
```

```bash
uvicorn hirarafs.service:app --host 127.0.0.1 --port 8900
```

```bash
curl -X POST localhost:8900/file_read -H 'content-type: application/json' \
  -d '{"path":"/tmp/hello.txt"}'
```

```json
{
  "path": "/tmp/hello.txt",
  "resolved_path": "/tmp/hello.txt",
  "content": "hello\n",
  "encoding": "utf-8",
  "size": 6,
  "bytes_read": 6,
  "offset": 0,
  "truncated": false,
  "content_type": "text/plain",
  "is_binary": false,
  "error": null
}
```

Binary / explicit base64:

```bash
curl -X POST localhost:8900/file_read -H 'content-type: application/json' \
  -d '{"path":"./logo.png","encoding":"base64","max_bytes":50000}'
```

MCP:

```bash
python -m hirarafs.mcp_server
```

Docker (loopback; mount a host folder at `/data`):

```bash
CFS_DATA=/path/to/workspace docker compose up -d --build
```

---

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `CFS_MAX_BYTES` | `2000000` | Cap on bytes returned per read |
| `CFS_ROOTS` | _(empty)_ / `/data` (image) | Comma/colon-separated allowlisted roots |
| `CFS_ALLOW_ANY_PATH` | `true` (lib) / `false` (image) | Allow any path when roots are empty |
| `CFS_DEFAULT_ENCODING` | `auto` | `auto`, `utf-8`, `ascii`, `latin-1`, or `base64` |
| `CFS_PORT` | `8900` | Compose host port |
| `CFS_DATA` | `./data` | Host dir mounted read-only at `/data` |

---

## Security

- Bind to loopback or put auth in front before exposing the port.
- Prefer `CFS_ROOTS` (and `CFS_ALLOW_ANY_PATH=false`) on any shared host.
- The image resolves paths and rejects anything outside `/data`.
- Errors stay in the JSON `"error"` field — never as HTTP 5xx for missing/denied paths.

---

## License

Apache-2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
