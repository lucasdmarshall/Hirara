<div align="center">

# Hiraraops

**Self-hosted ops tools for AI agents — read application logs safely.**

Part of [Hirara](https://github.com/lucasdmarshall/Hirara). Paths gated by
`COPS_ROOTS`; Docker serves files under `/logs`.

</div>

---

## Tools

| Tool | Status | What it does |
|---|---|---|
| **`application_logs`** | ✅ shipped | Tail / head / grep a log file |
| **`process_list`** | ✅ shipped | List running processes (`/proc`) |
| `environment_read` | 📋 planned | Read process environment |

---

## Quick start

```bash
pip install -e ".[service,mcp]"
uvicorn hiraraops.service:app --host 127.0.0.1 --port 9200
```

```bash
curl -X POST localhost:9200/application_logs -H 'content-type: application/json' \
  -d '{"path":"/var/log/app.log","lines":50,"level":"ERROR"}'
```

Named sources (`COPS_LOG_SOURCES=app=/logs/app.log`):

```bash
curl -X POST localhost:9200/application_logs -H 'content-type: application/json' \
  -d '{"source":"app","pattern":"timeout","lines":20}'
```

**Processes:**

```bash
curl -X POST localhost:9200/process_list -H 'content-type: application/json' \
  -d '{"pattern":"python","max_processes":20}'
```

MCP: `python -m hiraraops.mcp_server`

Docker:

```bash
COPS_LOGS=/var/log COPS_LOG_SOURCES=app=/logs/app.log docker compose up -d --build
```

---

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `COPS_ROOTS` | _(empty)_ / `/logs` (image) | Allowlisted roots |
| `COPS_ALLOW_ANY_PATH` | `true` (lib) / `false` (image) | Allow any path when roots empty |
| `COPS_LOG_SOURCES` | _(empty)_ | `name=path,name2=path2` |
| `COPS_DEFAULT_LINES` | `100` | Default `lines` |
| `COPS_MAX_LINES` | `5000` | Cap on `lines` |
| `COPS_MAX_BYTES` | `2000000` | Cap on bytes read per call |
| `COPS_MAX_PROCESSES` | `500` | Cap on processes returned |
| `COPS_ALLOW_PROCESS_LIST` | `true` | When false, `process_list` returns an error |
| `COPS_PROC_ROOT` | `/proc` | Proc filesystem root (tests / containers) |
| `COPS_PORT` | `9200` | Compose host port |

---

## License

Apache-2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
