# Security boundaries and deployment

Hirara serves one trusted operator. It does not provide tenant isolation or
per-user credentials. A bearer token authorizes the configured toolset, so do
not give the same deployment to mutually untrusted users. Browser sessions,
HTTP history, jobs, and agent memory belong to that operator.

## Migrating existing deployments

- HTTP and browser private destinations are now disabled in local mode as well
  as container mode. Trusted intranet work requires `CHTTP_ALLOW_PRIVATE_IPS=true`,
  `CBRO_ALLOW_PRIVATE_URLS=true`, or `CNET_ALLOW_PRIVATE_TARGETS=true`, respectively.
  `HIRARA_ALLOW_PRIVATE_IPS=false` overrides those opt-ins. Compose sets the global
  denial by default; change it explicitly for an intranet deployment.
- `HIRARA_ALLOWED_TOOLS` is a comma-separated list of exact tool names. Unset
  preserves the trusted-operator toolset; an explicitly empty value denies all
  tools. Set it on the hub and backend processes. The full-stack Compose files
  pass the variable through only when it exists in the host environment.
  Restrictions apply to HTTP, MCP, direct Toolset methods, and local SDK calls.
- Only `web_fetch` implements conversation URL provenance. The shared SSRF guard
  is a destination check, not a provenance check. For a provenance-restricted
  agent, expose only `web_search` and `web_fetch`; do not expose alternate HTTP,
  browser, DNS, document URL, or network-enabled code tools.
- MCP uses stdio. Unauthenticated SSE and streamable HTTP entry points now fail
  at startup, including standalone tools. Use the authenticated HTTP hub for
  remote access. The hub advertises native backend schemas and still accepts
  the previous `{"arguments": {...}}` call shape.
- Environment redaction is now an operator ceiling: callers cannot disable
  `COPS_REDACT_ENV=true`. An operator may explicitly set it false for trusted
  debugging. Read/write size settings are also server ceilings; requests can
  lower them, not increase them.
- Backend validation retains HTTP 422 and adds an `error` envelope. The hub
  normalizes backend 4xx failures into its existing HTTP-200 tool-error envelope.
  Authentication remains HTTP 401. MCP tool failures set `isError=true`.

## Authentication and networks

Keep published ports on loopback unless an authenticated TLS frontend protects
access. Set `HUB_TOKEN` for hub authentication. `HIRARA_BACKEND_TOKEN` protects
backend endpoints other than `/health`; the gateway sends it to backends. In
full-stack Compose, it defaults to `HUB_TOKEN`, and can be set separately.
Do not publish backend ports. The human approval UI retains its separate
`HG_HUMAN_TOKEN` authorization.

The executor has a separate internal Compose network shared only with the hub.
Other tools cannot connect directly to it on the ordinary tool network. This
reduces lateral reachability; it does not turn a Docker socket into a sandbox.

## Docker execution

The executor controls the Docker daemon and is host-root-equivalent with a
rootful host socket. Run it on a dedicated machine/VM or a dedicated suitably
isolated daemon. Never mount the socket into a general tool container or into a
submitted-code container. A read-only socket mount is not a read-only Docker
API. A proxy that allows arbitrary container creation is still privileged.

Submitted code uses a separate non-root container with no host mounts, no
network by default, a read-only root, tmpfs storage, dropped capabilities,
no-new-privileges, and CPU/memory/PID limits. These share the host kernel; they
are not a VM boundary. Prefer digest-pinned language images through
`CCODE_IMAGES` and pre-pull reviewed images with `CCODE_AUTO_PULL=false`.

`CCODE_MAX_RUNS` bounds synchronous executions; `CCODE_MAX_JOBS` bounds background
jobs, including starts in flight. These limits are per service process. Run one
executor process/worker for each `CCODE_EXECUTOR_ID` and daemon; independent
executors sharing a daemon need different stable IDs. The default ID is
`default`. Do not run multiple replicas with that ID against the same daemon.

A supervisor enforces job deadlines without status polling. On first use after
a restart, the executor removes leftover containers labelled with its own ID
before accepting work. Old jobs are terminated, not resumed; job IDs do not
survive restart. If daemon cleanup fails, reconciliation is retried and new work
fails closed. Shutdown attempts to terminate tracked containers. Existing
containers from before owner labels were introduced require manual inspection
and removal; do not run blanket host-container cleanup commands.

Docker log files rotate at 1 MB per container. Returned and retained streams are
bounded by `CCODE_MAX_OUTPUT_BYTES`; `truncated` indicates collection truncation.
Logs are a bounded rolling diagnostic window, not an archival stream. Finished
jobs are capped by `CCODE_MAX_RETAINED_JOBS` (default 100) and retention time.
`CCODE_MAX_INPUT_BYTES` caps combined code/stdin; image pulls and daemon outages
are infrastructure failures, not user-program exit codes.

## Browser and rendering

Chromium contexts stay offline. HTTP(S) requests are fulfilled through a
size-capped HTTP transport that resolves, validates and pins each connection,
including redirected and page-initiated requests. Browser service workers and
WebSockets are blocked. Chromium's native network stack also uses a dead local
proxy, with direct WebRTC UDP and QUIC disabled. Guarded operation currently
requires Chromium; other browser engines fail closed. Environment forward proxies are not used for this
transport because they would move DNS resolution outside its boundary.

The browser image installs Debian Chromium for the runtime user. A host browser
can be selected using `CBRO_EXECUTABLE_PATH`; otherwise Playwright's bundled
browser is used. Sessions are closed on eviction, idle expiry, and shutdown.
HTML-to-PDF entry points share a closed resource policy: use supplied base64
images; remote and arbitrary filesystem resources are refused.

## Validation and releases

Install matching source packages with `python scripts/install_dev.py` (or
`--sdk` for just the SDK, hub, and local backends), then run
`python scripts/test_all.py`. Suites run in separate processes
because test filenames overlap across packages. Optional native tools include
FFmpeg, Graphviz, eSpeak NG, zbar and Poppler.

The `Tests` workflow covers every package, Python 3.11/3.13 compatibility, and
real Docker, Chromium and MCP stdio integration. Both publishing workflows
require it. `constraints-release.txt` pins tested boundary dependencies for CI
and images; update pins together with these tests. Runtime libraries retain
compatible dependency ranges.

For local integration, use a disposable Docker daemon with `python:3.12-slim`
pre-pulled and Chromium installed, then run:

```sh
HIRARA_INTEGRATION=1 python -m pytest -q integration -o asyncio_mode=auto
```

Use `CBRO_EXECUTABLE_PATH=/usr/bin/chromium` for a system browser. Integration
containers use unique owner labels and never target unrelated host workloads.
`/health` is liveness plus backend diagnostics; authenticated `/ready` returns
503 when no backend is healthy. Partial backend availability is reported as
`degraded`, with individual service states.


### Optional Rust tools

The new file mutations reuse `CFS_ROOTS`, `CFS_ALLOW_ANY_PATH`, `CFS_ALLOW_WRITE`
and central tool permissions. They operate on regular files through root-relative
capabilities and do not provide recursive deletion. Copy limits cannot be widened
by a request. `json_query` has no executable extensions or external resources.
Research requests use fixed provider endpoints through the existing HTTP SSRF
guard, with redirects disabled and response caps.

PostgreSQL/MySQL endpoints are explicit administrator-configured network grants,
selected by database name. A request cannot supply a network DSN via `path=`.
These SQL connections are not governed by the public-HTTP private-address switch.
Use network restrictions and least-privilege database roles; a read-only SQL
transaction does not restrict privileged functions, FILE access or external
network extensions. No user transaction/session commands, COPY, SELECT INTO/export
or MySQL executable comments are accepted. DSNs are not returned in envelopes.
A timeout during a write can leave the outcome unknown and must not trigger a
blind retry. See [native tool limitations](docs/native-tools.md).


### Document collections and public API adapters

Gyrfalcon code is pinned to a Git revision. Model/collection paths come only
from administrator configuration; models and index internals must be trusted
and kept outside source-file roots. Source ingestion uses CFS capabilities
and byte limits. A collection grants access to retained indexed copies; source
file removal or root changes do not revoke those copies. Metadata filters are
not authorization. `CRAG_ALLOW_WRITE` controls collection mutations separately
from source-file writes. Only one process may own each collection.

Public Q&A/books/weather APIs use fixed endpoints and the shared HTTP guard,
including caps and redirect/private-target denial. Model-supplied credentials
and endpoints are not accepted. Provider backoff and search session budgets
apply; cached results remain subject to tool permissions. Public content is
untrusted, including accepted answers and document chunks.

Symbolic math parses a bounded expression grammar in Rust; it does not evaluate
Python, scripts, commands or filesystem/network operations. Its floating-point
CAS is not a proof system. See [operational limits](docs/search-and-math.md).
