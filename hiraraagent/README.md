<div align="center">

# HiraraAgent

**Memory, human-in-the-loop, reminders and waiting for AI agents.**

Part of [Hirara](https://github.com/lucasdmarshall/Hirara). One SQLite file, no
external services, no API keys.

</div>

---

## Tools

| Tool | What it gives an agent |
|---|---|
| **`memory`** | Notes that survive sessions: `set` / `get` / `search` / `list` / `delete` JSON values by key, with tags, TTLs and namespaces |
| **`ask_human`** | Ask a person a question or for approval (`ask` returns a `request_id`), then `check` the answer; `list`, `cancel`; optional webhook notification |
| **`schedule`** | Reminders that come due later: `create` (ISO time, `in 10m`, or seconds; optional repeat), `due`, `list`, `cancel` |
| **`wait_until`** | Block until a human answers, a reminder is due, or a time arrives, capped (default 100 s) |

An agent forgets everything between sessions, cannot pause for a person's
decision, and cannot wake itself up later. These four tools give it those
abilities with plain, inspectable state.

### Answering questions

People answer at **`/human`**, a small page (light and dark) that lists
pending requests with one button per option and a free-text box where
allowed. Scripts and chat bots can use `GET /human/pending` and
`POST /human/answer` instead. Set `HG_NOTIFY_URL` to be pinged when a request
arrives (ntfy topics get a plain-text push; anything else gets JSON with
`text` / `content`, which Slack and Discord webhooks accept).

**Security:** the agent's tools cannot answer questions; only the human side
can. Set `HG_HUMAN_TOKEN` before exposing the service beyond loopback and keep
that token away from the agent.

---

## Quick start

```bash
pip install -e ".[service,mcp]"
uvicorn hiraraagent.service:app --host 127.0.0.1 --port 9600
```

```bash
curl -X POST localhost:9600/memory -H 'content-type: application/json' \
  -d '{"action":"set","key":"deploy.rule","value":"never on Fridays","tags":["ops"]}'

curl -X POST localhost:9600/ask_human -H 'content-type: application/json' \
  -d '{"action":"ask","kind":"approval","question":"Drop the staging database?"}'
# open http://127.0.0.1:9600/human and click approve or reject

curl -X POST localhost:9600/wait_until -H 'content-type: application/json' \
  -d '{"request_id":"<id from ask>","max_wait":60}'
```

MCP: `python -m hiraraagent.mcp_server`. Docker: `docker compose up -d --build`.

---

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `HG_DB` | `~/.hirara/agent.db` | SQLite file (the image uses `/data/agent.db`) |
| `HG_MAX_WAIT` | `100` | Longest `wait_until` (keep under the hub's 120 s timeout) |
| `HG_MAX_VALUE_BYTES` | `100000` | Largest memory value |
| `HG_MAX_ENTRIES` | `20000` | Memory entries per namespace |
| `HG_NOTIFY_URL` | _(empty)_ | Webhook pinged for each new request |
| `HG_PUBLIC_URL` | _(empty)_ | Base URL put in notifications (link to `/human`) |
| `HG_HUMAN_TOKEN` | _(empty)_ | Required token for the human page and API |
| `HG_PORT` | `9600` | Compose host port |

---

## License

Apache-2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
