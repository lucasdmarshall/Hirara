<div align="center">

# Hirarautil

**Self-hosted utility tools for AI agents — decode common encodings.**

Part of [Hirara](https://github.com/lucasdmarshall/Hirara).

</div>

---

## Tools

| Tool | Status | What it does |
|---|---|---|
| **`decode`** | ✅ shipped | Decode base64 / hex / url / html / unicode_escape |
| **`hash`** | ✅ shipped | Message digests (md5 / sha* / blake2) |
| `jwt_inspect` / `jwt_decode` | 📋 planned | JWT header/payload helpers |

---

## Quick start

```bash
pip install -e ".[service,mcp]"
uvicorn hirarautil.service:app --host 127.0.0.1 --port 9000
```

```bash
curl -X POST localhost:9000/decode -H 'content-type: application/json' \
  -d '{"input":"aGVsbG8=","format":"base64"}'
```

```json
{
  "input": "aGVsbG8=",
  "format": "base64",
  "detected_format": "base64",
  "output": "hello",
  "output_encoding": "utf-8",
  "is_binary": false,
  "input_chars": 8,
  "output_bytes": 5,
  "truncated": false,
  "error": null
}
```

**Hash:**

```bash
curl -X POST localhost:9000/hash -H 'content-type: application/json' \
  -d '{"input":"hello","algorithms":"sha256"}'
```

```json
{
  "input": "hello",
  "input_encoding": "utf-8",
  "input_chars": 5,
  "input_bytes": 5,
  "algorithms": ["sha256"],
  "digests": {"sha256": "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"},
  "digest": "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
  "algorithm": "sha256",
  "output_format": "hex",
  "error": null
}
```

MCP: `python -m hirarautil.mcp_server`

Docker: `docker compose up -d --build`

---

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `CUTIL_MAX_INPUT_CHARS` | `1000000` | Cap on input length |
| `CUTIL_MAX_OUTPUT_BYTES` | `2000000` | Cap on decoded output |
| `CUTIL_PORT` | `9000` | Compose host port |

---

## License

Apache-2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
