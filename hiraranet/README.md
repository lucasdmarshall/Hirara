<div align="center">

# Hiraranet

**Self-hosted network tools for AI agents — DNS lookup first. No API keys.**

Part of the [Hirara](https://github.com/lucasdmarshall/Hirara) tool hub.
Uses [dnspython](https://github.com/rthalley/dnspython). Resolved addresses are
annotated with [`hirara-core`](../hirara-core/)'s IP classification so agents
can see private/reserved answers without re-implementing the deny list.

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/MCP-compatible-8A2BE2.svg)](https://modelcontextprotocol.io/)

</div>

---

## Tools

| Tool | Status | What it does |
|---|---|---|
| **`dns_lookup`** | ✅ shipped | Resolve A/AAAA/MX/TXT/… ; annotate private IPs |
| **`port_scan`** | ✅ shipped | TCP-connect scan ports on a host |
| `service_enum` | 📋 planned | See [TOOLS.md](../TOOLS.md) |

`dns_lookup` **only queries DNS**. It never opens a connection to the
addresses it returns.

---

## Quick start

```bash
pip install -e ../hirara-core
pip install -e ".[service,mcp]"
```

As an HTTP service:

```bash
uvicorn hiraranet.service:app --host 127.0.0.1 --port 8600
```

**Look up** A/AAAA for a host:

```bash
curl -X POST localhost:8600/dns_lookup -H 'content-type: application/json' \
  -d '{"name":"example.com"}'
```

**MX + TXT**:

```bash
curl -X POST localhost:8600/dns_lookup -H 'content-type: application/json' \
  -d '{"name":"example.com","record_types":["MX","TXT"]}'
```

**Reverse lookup**:

```bash
curl -X POST localhost:8600/dns_lookup -H 'content-type: application/json' \
  -d '{"name":"1.1.1.1","record_types":["PTR"]}'
```

**Port scan** (TCP connect):

```bash
curl -X POST localhost:8600/port_scan -H 'content-type: application/json' \
  -d '{"host":"127.0.0.1","ports":[22,80,443,"8000-8002"]}'
```

Omit `ports` to use the built-in common-port list.

As an MCP server over stdio:

```bash
python -m hiraranet.mcp_server
```

With Docker (loopback-bound):

```bash
docker compose up -d --build
```

---

## Response shape

```json
{
  "name": "example.com",
  "record_types": ["A", "AAAA"],
  "answers": [
    {
      "type": "A",
      "value": "93.184.216.34",
      "ttl": 300,
      "routable": true,
      "block_reason": null
    }
  ],
  "answer_count": 1,
  "truncated": false,
  "nameserver": null,
  "error": null
}
```

Private/reserved answers still appear — with `routable: false` and a
`block_reason` from `hirara-core.check_ip` (e.g. `"127.0.0.1 is not globally
routable"`). That is intentional: agents need to *see* localhost / link-local
results, not have them silently dropped.

### `port_scan`

```json
{
  "host": "127.0.0.1",
  "ip": "127.0.0.1",
  "ports": [22, 80, 443],
  "results": [
    {"port": 22, "status": "closed", "latency_ms": 0.4, "error": null},
    {"port": 80, "status": "open", "latency_ms": 1.2, "error": null},
    {"port": 443, "status": "timeout", "latency_ms": 1500.0, "error": null}
  ],
  "open_ports": [80],
  "open_count": 1,
  "duration_ms": 1502.1,
  "routable": false,
  "block_reason": "127.0.0.1 is not globally routable",
  "truncated": false,
  "error": null
}
```

Errors (empty host, bad port range, resolve failure) come back in
`"error"`, not as HTTP status codes.

---

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `CNET_DEFAULT_RECORD_TYPES` | `A,AAAA` | Used when the caller omits `record_types` |
| `CNET_TIMEOUT` | `5` | Seconds per type |
| `CNET_MAX_TYPES` | `8` | Cap on types per call |
| `CNET_MAX_ANSWERS` | `64` | Cap on returned answers |
| `CNET_NAMESERVER` | _(system)_ | Optional recursive resolver |
| `CNET_ANNOTATE_IPS` | `true` | Tag IPs with routable / block_reason |
| `CNET_DEFAULT_SCAN_PORTS` | _(common list)_ | Used when `port_scan` omits `ports` |
| `CNET_SCAN_TIMEOUT` | `1.5` | Per-port connect timeout (seconds) |
| `CNET_SCAN_CONCURRENCY` | `32` | Max simultaneous connects |
| `CNET_MAX_SCAN_PORTS` | `256` | Cap on ports per call |
| `CNET_PORT` | `8600` | Compose host port (loopback) |

---

## Security

- **DNS only for `dns_lookup`.** No connect on that tool.
- **TCP connect for `port_scan`.** No SYN/raw packets, no UDP, no banner grab.
- **Loopback bind** in compose. Do not publish without auth — same rule as
  the other Hirara services.
- **Allowlisted DNS record types.** Odd/obscure types are refused.
- **Port caps.** `CNET_MAX_SCAN_PORTS` bounds how wide a single call can be.
- **IP annotation** reuses the hub's shared deny list so agents reason about
  private targets the same way `web_fetch` would.

---

## Testing

```bash
pip install -e ../hirara-core
pip install -e ".[dev]"
pytest -q
```

---

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
