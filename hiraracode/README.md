<div align="center">

# Hiraracode

**Sandboxed code execution for AI agents — Docker-isolated. No third-party API keys.**

Part of the [Hirara](https://github.com/lucasdmarshall/Hirara) tool hub. An
agent hands over a snippet; it runs in a throwaway container with no network, a
read-only root filesystem, a non-root user, dropped capabilities, and
CPU/memory/pids/time caps — then the container is destroyed.

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/MCP-compatible-8A2BE2.svg)](https://modelcontextprotocol.io/)

</div>

---

## The trust model, up front

A code executor is arbitrary remote code execution *by design*. The only thing
that makes it safe is where the trust boundary sits, so it is stated plainly:

| Component | Trusted? | Why |
|---|---|---|
| **The executor** (this service) | **yes — and privileged** | It talks to the Docker daemon, which is root-equivalent on the host. It must be authenticated and loopback-bound. |
| **The executed code** | **no** | It runs in a locked-down sibling container and is treated as hostile. |

The one rule that ties it together: **a caller names a *language*, never an
image.** Images come only from a server-side allowlist, so a caller can never
ask the daemon to run something arbitrary — only `python`, `node`, `bash`, or
whatever the operator has added.

This is the same shape as the rest of the hub: the dangerous primitive (there, a
URL fetch; here, running code) is wrapped so the untrusted side cannot widen its
own privileges.

---

## What the sandbox enforces

Every execution container is created with, by default:

- **No network** (`network_disabled`) — opt in per host with `CCODE_ALLOW_NETWORK`
- **Read-only root filesystem** — the only writable storage is tmpfs at
  `/workspace` and `/tmp`, which vanishes with the container
- **Non-root user** (`65534:65534`, nobody)
- **All Linux capabilities dropped** (`cap_drop: ALL`) and `no-new-privileges`
- **Memory cap** with swap disabled (`mem_limit == memswap_limit`)
- **CPU cap** (fractional CPUs via `nano_cpus`)
- **Process cap** (`pids_limit`) — blunts fork bombs
- **Wall-clock timeout** — a run past it is killed and flagged `timed_out`
- **Output caps** — stdout/stderr truncated, flagged `truncated`
- **Auto-removal** — the container is destroyed after each run

A non-zero exit from *your* code is a normal result (`exit_code`), not a tool
failure. OOM kills are reported (`oom_killed`).

---

## Requirements

A reachable **Docker daemon**. The executor drives it via the Docker SDK — it
does not need the `docker` CLI. In the container deployment, the host socket is
mounted in (see the security note in [docker-compose.yml](docker-compose.yml)).

---

## Quick start

```bash
pip install -e ".[service,mcp]"
```

Pre-pull the sandbox images (optional; otherwise pulled on first use):

```bash
docker pull python:3.12-slim && docker pull node:20-slim && docker pull bash:5
```

Run the HTTP service (bind to loopback — it is privileged):

```bash
uvicorn hiraracode.service:app --host 127.0.0.1 --port 8300
```

**Run** a snippet:

```bash
curl -X POST localhost:8300/execute_code -H 'content-type: application/json' \
  -d '{"language":"python","code":"print(sum(range(10)))"}'
```

```json
{"stdout":"45\n","stderr":"","exit_code":0,"timed_out":false,
 "oom_killed":false,"duration":0.31,"truncated":false,
 "language":"python","image":"python:3.12-slim","error":null}
```

With **stdin**:

```bash
curl -X POST localhost:8300/execute_code -H 'content-type: application/json' \
  -d '{"language":"python","code":"import sys;print(sys.stdin.read().upper())","stdin":"hello"}'
```

As an MCP server over stdio (Claude Desktop / Cursor / agent runtimes):

```bash
python -m hiraracode.mcp_server
```

With Docker Compose (mounts the host socket — read the security banner first):

```bash
docker compose up -d --build
```

---

## The tools

`execute_code` runs a program and waits for it:

| Field | Required | Meaning |
|---|---|---|
| `language` | yes | One of the allowlisted languages (`python`, `node`, `bash`, …) |
| `code` | yes | Source to run. Self-contained; print your results |
| `stdin` | no | Text fed to the program's standard input |
| `timeout` | no | Wall-clock seconds, clamped to the server ceiling |

Every response carries the same keys — `stdout`, `stderr`, `exit_code`,
`timed_out`, `oom_killed`, `duration`, `truncated`, `language`, `image`,
`error` — whether it succeeded or failed. Errors (bad language, daemon
unreachable) come back in `error`, not as an HTTP status code: the caller is an
agent loop, and a refusal is a result to reason about.

### Background jobs

For anything long-running (a dev server, a build, a test suite), use a job.
It runs in exactly the same locked-down container, detached:

| Tool | What it does |
|---|---|
| `job_start` | Start the program; returns a `job_id` immediately |
| `job_status` | State (`running` / `exited` / `timed_out` / `stopped`), exit code, and stdout / stderr written since the cursors you pass; without `job_id`, lists jobs |
| `job_stop` | Kill it, remove the container, return the final output |

A job past its timeout (default 10 minutes, `CCODE_JOB_MAX_TIMEOUT` ceiling)
is killed on the next status check. Finished jobs keep their logs for
`CCODE_JOB_RETENTION` seconds after the container is removed.

---

## Adding languages

Multi-language is just the allowlist. Add one without touching code via
`CCODE_IMAGES` (JSON, merged over the defaults):

```bash
export CCODE_IMAGES='{"go":{"image":"golang:1.22-alpine","cmd":["go","run","/workspace/main.go"],"filename":"main.go"}}'
```

The submitted code is written to `filename` in `/workspace`, then `cmd` is run.
Because the image is fixed here on the server, adding a language never lets a
caller choose an arbitrary image.

---

## Configuration

All via environment variable.

| Variable | Default | Notes |
|---|---|---|
| `CCODE_ALLOW_NETWORK` | `false` | Give executed code network access (trusted hosts only) |
| `CCODE_TIMEOUT` | `30` | Default wall-clock seconds per run |
| `CCODE_MAX_TIMEOUT` | `120` | Ceiling a caller-supplied timeout is clamped to |
| `CCODE_MEMORY` | `256m` | Container memory cap (swap disabled) |
| `CCODE_CPUS` | `1.0` | Fractional CPU cap |
| `CCODE_PIDS_LIMIT` | `128` | Max processes — blunts fork bombs |
| `CCODE_MAX_OUTPUT_BYTES` | `100000` | Per-stream output cap; result flags `truncated` |
| `CCODE_WORKSPACE_SIZE` | `64m` | tmpfs size for `/workspace` |
| `CCODE_TMP_SIZE` | `64m` | tmpfs size for `/tmp` |
| `CCODE_USER` | `65534:65534` | UID:GID code runs as — never `0` |
| `CCODE_AUTO_PULL` | `true` | Pull an allowlisted image if missing |
| `CCODE_IMAGES` | — | JSON to add/override languages |
| `CCODE_JOB_TIMEOUT` | `600` | Default wall-clock seconds per background job |
| `CCODE_JOB_MAX_TIMEOUT` | `3600` | Ceiling for a job's timeout |
| `CCODE_MAX_JOBS` | `4` | Background jobs running at once |
| `CCODE_JOB_RETENTION` | `3600` | Seconds a finished job's logs are kept |
| `CCODE_PORT` | `8300` | Published port (loopback only) |

---

## Testing

```bash
pip install -e ".[dev]"
pytest -q
```

The suite runs against a **fake Docker client**, so it needs no daemon. It
asserts on the security-relevant choices — network disabled, read-only root,
non-root user, capabilities dropped, swap off, pids capped — plus timeout kills,
OOM reporting, output truncation, the language allowlist, image pull policy, and
stdin delivery. For a real end-to-end check, run the service against a live
daemon and `curl` the examples above.

Verified end-to-end against a live Docker daemon (Docker 29.3): `python`, `node`
and `bash` execution, non-zero exit propagation, `stdin`, and timeout kills — and
the guarantees hold under test, with executed code hitting
`Network is unreachable` (no network), a read-only root filesystem, and
`uid=65534` (non-root).

---

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).

Copyright 2026 Lucas D Marshall (Kaung Myat San).

## Lifecycle and resource ceilings

See [the security guide](../SECURITY.md#docker-execution) for per-process admission,
independent job deadlines, bounded rolling logs, stable executor IDs, restart
cleanup, and dedicated-daemon deployment. Network MCP is disabled; use stdio.
