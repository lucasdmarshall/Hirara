<div align="center">

# Hiraradb

**Self-hosted database tools for AI agents — query SQLite safely.**

Part of [Hirara](https://github.com/lucasdmarshall/Hirara). Read-only by
default; paths gated by `CDB_ROOTS`.

</div>

---

## Tools

| Tool | Status | What it does |
|---|---|---|
| **`database_query`** | ✅ shipped | Run one SQL statement → columns + rows |
| **`database_schema`** | ✅ shipped | List tables / columns (optional indexes, FKs) |

v1 supports **SQLite** only (`path` / `sqlite:///…` / `CDB_PATH`).

---

## Quick start

```bash
pip install -e ".[service,mcp]"
uvicorn hiraradb.service:app --host 127.0.0.1 --port 9100
```

```bash
curl -X POST localhost:9100/database_query -H 'content-type: application/json' \
  -d '{"sql":"SELECT 1 AS n","path":":memory:"}'
```

With a file DB and params:

```bash
curl -X POST localhost:9100/database_query -H 'content-type: application/json' \
  -d '{"sql":"SELECT id, name FROM users WHERE id = ?","params":[1],"path":"/tmp/app.db"}'
```

**Schema** (tables + columns):

```bash
curl -X POST localhost:9100/database_schema -H 'content-type: application/json' \
  -d '{"path":"/tmp/app.db","include_indexes":true}'
```

MCP: `python -m hiraradb.mcp_server`

Docker (mount DB files under `/data`):

```bash
CDB_DATA=/path/to/db-dir docker compose up -d --build
```

---

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `CDB_PATH` / `CDB_URL` | _(empty)_ / `/data/app.db` (image) | Default sqlite path |
| `CDB_DATABASES` | _(empty)_ | `name=path,name2=path2` |
| `CDB_READONLY` | `true` | Open sqlite `mode=ro`; block write SQL |
| `CDB_ROOTS` | _(empty)_ / `/data` (image) | Allowlisted roots for DB files |
| `CDB_ALLOW_ANY_PATH` | `true` (lib) / `false` (image) | Allow any path when roots empty |
| `CDB_MAX_ROWS` | `1000` | Default row cap |
| `CDB_MAX_SQL_CHARS` | `100000` | Cap on SQL length |
| `CDB_TIMEOUT` | `30` | sqlite busy timeout (seconds) |
| `CDB_PORT` | `9100` | Compose host port |

---

## Security

- Bind to loopback or put auth in front.
- Keep `CDB_READONLY=true` unless you intentionally allow writes.
- Prefer `CDB_ROOTS` on shared hosts.
- One statement per call; errors stay in the JSON `"error"` field.

---

## License

Apache-2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
